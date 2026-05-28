"""Deterministic validation checks (the rule-based lenses of SAValidationAgent).

Validation's 7-lens rubric is part judgment, part mechanics. The mechanical
lenses — subscription syntax (``>`` must be the last level), schema sanity
(required keys present / YAML parses), terminology (forbidden-term scan),
integration coverage (every landscape system has a strategy), and a few
cross-artifact consistency checks — are decidable from the artifacts, so we
compute them HERE rather than asking the LLM to eyeball them (which it gets
wrong, and which costs a stall-prone turn per artifact). The agent is then left
with the genuinely-evaluative lenses (antipattern interpretation, deferred-
finding triage) and writing the report narrative.

Pure functions over already-parsed artifacts — same shape as ``rules.py``, so
they unit-test without storage. A thin loader in the entrypoint/agent maps the
engagement's artifacts into these inputs and injects the findings.
"""

from __future__ import annotations

from typing import Any, Optional

# Top-level keys each design artifact must carry. Schema drift over time is
# tolerated by listing alternative acceptable keys per artifact (any one hit
# passes). Only artifacts that are PRESENT are checked — absence is a coverage
# concern handled by the workflow, not a schema error.
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "topic-design/topic-taxonomy.yaml": ("topics", "taxonomy", "levels", "structure"),
    "broker-select/broker-recommendation.yaml": ("sizing", "recommendation", "deployment"),
    "protocol-select/protocol-map.yaml": ("protocol_mapping", "protocols", "mappings", "systems"),
    "integration/integration-map.yaml": ("systems", "integrations", "integration_map"),
    "mesh-design/dmr-topology.yaml": ("topology_pattern", "topology", "sites", "dmr_links", "nodes", "links"),
    "ha-dr/ha-dr-design.yaml": ("ha_design", "ha", "rpo", "rto", "replication"),
    "event-portal/event-portal-model.yaml": ("domains", "applications", "events"),
}


def _finding(lens: str, severity: str, artifact: str, detail: str) -> dict:
    return {"lens": lens, "severity": severity, "artifact": artifact, "detail": detail}


# ── lens 7: subscription syntax (fully rule-based) ───────────────────────────


def subscription_violation(sub: str) -> Optional[str]:
    """Why ``sub`` is an invalid Solace subscription, or None if valid.

    Platform rule: a ``>`` multi-level wildcard MUST be the last character and
    occupy its own level. Flags ``>`` not-last, multiple ``>``, ``>`` at start.
    """
    s = (sub or "").strip()
    if ">" not in s:
        return None
    if s.count(">") > 1:
        return "multiple '>' wildcards in one subscription"
    if s.startswith(">") and len(s) > 1:
        return "'>' at the start — it must be the last character"
    if not s.endswith(">"):
        return "'>' must be the last character"
    return None


def _walk_strings(obj: Any):
    """Yield every string leaf in a nested dict/list structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v)


def check_subscription_syntax(taxonomy: Any,
                              artifact: str = "topic-design/topic-taxonomy.yaml") -> list[dict]:
    """Scan every wildcard-bearing string in the taxonomy for syntax violations."""
    out: list[dict] = []
    seen: set[str] = set()
    for s in _walk_strings(taxonomy):
        if ">" not in s or s in seen:
            continue
        seen.add(s)
        why = subscription_violation(s)
        if why:
            out.append(_finding(
                "subscription-syntax", "blocking", artifact,
                f"Invalid subscription `{s}`: {why} "
                "(Solace platform rule — see solace-platform-reference.md → "
                "Smart Topic Architecture → Wildcard subscriptions)."))
    return out


# ── lens 6: schema sanity (parse + required keys) ────────────────────────────


def check_schema_sanity(artifacts: dict[str, Optional[dict]]) -> list[dict]:
    """``artifacts`` maps artifact-name → parsed object (or None = present but
    failed to parse). Missing-from-map artifacts are skipped (coverage, not
    schema).

    Parse failure is BLOCKING (a downstream consumer can't read it). A missing
    anchor key is only ADVISORY — artifact schemas drift, so an unrecognised
    top-level shape is "worth a look", not a hard gate; that keeps a stale
    key-list from ever manufacturing a spurious blocker."""
    out: list[dict] = []
    for name, parsed in artifacts.items():
        if parsed is None:
            out.append(_finding("schema-sanity", "blocking", name,
                                "Artifact present but did not parse as valid YAML."))
            continue
        required = _REQUIRED_KEYS.get(name)
        if required and isinstance(parsed, dict) and not any(k in parsed for k in required):
            out.append(_finding(
                "schema-sanity", "advisory", name,
                f"No recognised top-level key (expected one of {list(required)}); "
                "schema may have drifted — confirm the artifact is well-formed."))
    return out


# ── lens 5: terminology (forbidden-term scan) ────────────────────────────────


def check_terminology(texts: dict[str, str], forbidden_terms: list[str]) -> list[dict]:
    """Advisory finding per forbidden term found in an artifact's raw text."""
    out: list[dict] = []
    for name, text in (texts or {}).items():
        low = (text or "").lower()
        for term in forbidden_terms or []:
            if term and term.lower() in low:
                out.append(_finding("terminology", "advisory", name,
                                    f"Forbidden term {term!r} appears in this artifact."))
    return out


# ── lens 1/3: integration coverage + cross-artifact consistency ──────────────


def _system_names(brief: dict) -> list[str]:
    landscape = brief.get("landscape") if isinstance(brief, dict) else None
    systems = (landscape or {}).get("systems") if isinstance(landscape, dict) else None
    out = []
    for s in systems or []:
        if isinstance(s, dict) and s.get("name"):
            out.append(str(s["name"]))
    return out


def check_integration_coverage(brief: dict, integration_map: Any) -> list[dict]:
    """Every backend system in the landscape must appear in the integration map."""
    out: list[dict] = []
    systems = _system_names(brief)
    if not systems:
        return out
    mapped = {str(r.get("system")) for r in
              ((integration_map or {}).get("systems") or []) if isinstance(r, dict)}
    for name in systems:
        if name not in mapped:
            out.append(_finding(
                "requirement-coverage", "blocking", "integration/integration-map.yaml",
                f"Backend system {name!r} from the landscape has no integration strategy."))
    return out


def check_mesh_site_consistency(brief: dict, mesh: Any) -> list[dict]:
    """If the brief lists multiple sites, the mesh design should reference them."""
    out: list[dict] = []
    req = brief.get("requirements") if isinstance(brief, dict) else None
    sites = (req or {}).get("sites") if isinstance(req, dict) else None
    if not isinstance(sites, list) or len(sites) <= 1 or not isinstance(mesh, dict):
        return out
    mesh_text = " ".join(_walk_strings(mesh)).lower()
    missing = [s for s in sites if isinstance(s, str) and s.lower() not in mesh_text]
    if missing:
        out.append(_finding(
            "consistency", "advisory", "mesh-design/dmr-topology.yaml",
            f"Brief lists sites {sites} but the mesh design does not reference: {missing}."))
    return out


# ── aggregate ────────────────────────────────────────────────────────────────


def run_validation_rules(*, brief: dict,
                         parsed_artifacts: dict[str, Optional[dict]],
                         artifact_texts: Optional[dict[str, str]] = None,
                         forbidden_terms: Optional[list[str]] = None) -> dict:
    """Run all deterministic lenses; return findings + a per-severity tally.

    ``parsed_artifacts``: name → parsed object (None = present-but-unparseable);
    omit an artifact entirely if it doesn't exist yet.
    """
    findings: list[dict] = []
    taxonomy = parsed_artifacts.get("topic-design/topic-taxonomy.yaml")
    if taxonomy is not None:
        findings += check_subscription_syntax(taxonomy)
    findings += check_schema_sanity(parsed_artifacts)
    findings += check_terminology(artifact_texts or {}, forbidden_terms or [])
    findings += check_integration_coverage(brief, parsed_artifacts.get("integration/integration-map.yaml"))
    findings += check_mesh_site_consistency(brief, parsed_artifacts.get("mesh-design/dmr-topology.yaml"))
    blocking = sum(1 for f in findings if f["severity"] == "blocking")
    return {
        "findings": findings,
        "counts": {"blocking": blocking, "advisory": len(findings) - blocking, "total": len(findings)},
        "note": ("Deterministic validation lenses (subscription syntax, schema sanity, "
                 "terminology, integration coverage, mesh consistency) pre-computed. "
                 "Validator: record these as open-items verbatim; spend the LLM only on "
                 "antipattern interpretation + deferred-finding triage + the report narrative."),
    }
