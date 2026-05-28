"""Deterministic CANDIDATE findings to seed the reviewer agents.

Reviewer findings are judgment work — you can't *compute* "this design is
over-engineered." But several findings each reviewer dimension routinely raises
are mechanical signals in the artifacts: no HA under guaranteed delivery, no TLS
mentioned anywhere, DMR specified for a single site, no schema version in the
topic structure. Computing those HERE seeds each reviewer with a candidate list
to confirm/expand, so the LLM spends its turns on judgment + narrative rather
than re-deriving the obvious (and the consume turns that stall).

These are CANDIDATES, deliberately conservative (under-flag over over-flag): the
reviewer validates each and adds the judgment findings the rules can't see.

Pure functions over parsed artifacts + brief + a combined text blob (for keyword
scans). Finding shape: {dimension, severity, artifact, issue, recommendation}.
"""

from __future__ import annotations

import re
from typing import Any, Optional

DIMENSIONS = ("architect", "developer", "ops", "security")


def _dig(d: Any, *path: str) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _finding(dimension: str, severity: str, artifact: str, issue: str, rec: str) -> dict:
    return {"dimension": dimension, "severity": severity, "artifact": artifact,
            "issue": issue, "recommendation": rec, "source": "candidate"}


def _has_any(text: str, *terms: str) -> bool:
    low = (text or "").lower()
    return any(t in low for t in terms)


def _sites(brief: dict) -> list:
    s = _dig(brief, "requirements", "sites") or _dig(brief, "sites")
    return s if isinstance(s, list) else []


def _delivery_guaranteed(brief: dict) -> bool:
    dm = (_dig(brief, "requirements", "delivery_mode") or "").lower()
    pg = (_dig(brief, "requirements", "processing_guarantee") or "").lower()
    return dm in ("guaranteed", "mixed") or pg in ("at-least-once", "exactly-once")


# ── ops ───────────────────────────────────────────────────────────────────────


def ops_candidates(brief: dict, parsed: dict[str, Any]) -> list[dict]:
    out: list[dict] = []
    hadr = parsed.get("ha-dr/ha-dr-design.yaml")
    if _delivery_guaranteed(brief):
        hadr_text = str(hadr).lower() if hadr is not None else ""
        if not _has_any(hadr_text, "ha", "redundan", "replicat", "standby", "failover"):
            out.append(_finding(
                "ops", "important", "ha-dr/ha-dr-design.yaml",
                "Guaranteed/mixed delivery requested but the HA/DR design does not "
                "describe redundancy or replication.",
                "Specify an HA redundancy group (active/standby) and cross-site DR."))
    broker = parsed.get("broker-select/broker-recommendation.yaml")
    if isinstance(broker, dict) and not (broker.get("sizing") or _dig(broker, "recommendation", "sizing")):
        out.append(_finding(
            "ops", "important", "broker-select/broker-recommendation.yaml",
            "Broker recommendation has no explicit sizing block.",
            "Add a sizing block (spool, throughput band, service class) with the inputs."))
    return out


# ── security ──────────────────────────────────────────────────────────────────


def security_candidates(brief: dict, parsed: dict[str, Any], all_text: str) -> list[dict]:
    out: list[dict] = []
    if not _has_any(all_text, "tls", "ssl", "encrypt"):
        out.append(_finding(
            "security", "important", "(design)",
            "No transport encryption (TLS) mentioned in any design artifact.",
            "Specify TLS for client and DMR links; document cert management."))
    if not _has_any(all_text, "auth", "client-profile", "client profile", "acl", "oauth", "rbac"):
        out.append(_finding(
            "security", "important", "(design)",
            "No authentication/authorization (client-profile / ACL / OAuth) specified.",
            "Define client profiles + ACLs per producer/consumer; no anonymous publish."))
    residency = _dig(brief, "requirements", "data_residency_constraints") or \
        _dig(brief, "requirements", "data_residency")
    mesh = parsed.get("mesh-design/dmr-topology.yaml")
    if residency and mesh is not None:
        mesh_text = str(mesh).lower()
        if "selective" not in mesh_text and not _has_any(mesh_text, "filter", "residency"):
            out.append(_finding(
                "security", "critical", "mesh-design/dmr-topology.yaml",
                "Data-residency constraints exist but the mesh shows no selective "
                "replication / residency filter — events may cross regions.",
                "Apply selective DMR subscription filters enforcing residency boundaries."))
    return out


# ── developer ─────────────────────────────────────────────────────────────────


def developer_candidates(brief: dict, parsed: dict[str, Any], all_text: str) -> list[dict]:
    out: list[dict] = []
    taxonomy = parsed.get("topic-design/topic-taxonomy.yaml")
    if isinstance(taxonomy, dict):
        levels = taxonomy.get("levels") if isinstance(taxonomy.get("levels"), dict) else {}
        pattern = str(_dig(taxonomy, "structure", "pattern") or "")
        if "version" not in levels and not re.search(r"v\{?n", pattern.lower()):
            out.append(_finding(
                "developer", "important", "topic-design/topic-taxonomy.yaml",
                "Topic structure has no schema-version level.",
                "Add a version level (e.g. v{N}) to support schema evolution / blue-green."))
    schemas = _dig(brief, "landscape", "schemas")
    if schemas and not _has_any(all_text, "schema registry", "schema-registry", "version", "avro", "json schema"):
        out.append(_finding(
            "developer", "advisory", "(design)",
            "Brief notes schema governance but no artifact addresses schema "
            "registry / versioning.",
            "Document schema-registry usage and per-event versioning policy."))
    return out


# ── architect ─────────────────────────────────────────────────────────────────


def architect_candidates(brief: dict, parsed: dict[str, Any]) -> list[dict]:
    out: list[dict] = []
    mesh = parsed.get("mesh-design/dmr-topology.yaml")
    if mesh is not None and len(_sites(brief)) <= 1:
        mesh_text = str(mesh).lower()
        if _has_any(mesh_text, "dmr", "federation", "multi-region", "external link"):
            out.append(_finding(
                "architect", "important", "mesh-design/dmr-topology.yaml",
                "Single-site engagement but the mesh design specifies DMR/federation "
                "— likely over-engineered.",
                "Confirm a single broker suffices; reserve DMR for genuine multi-site."))
    return out


# ── aggregate ────────────────────────────────────────────────────────────────


def candidate_findings(brief: dict, parsed: dict[str, Any],
                       all_text: Optional[str] = None) -> dict:
    """All dimensions' candidate findings, grouped by dimension + a flat list."""
    text = all_text if all_text is not None else " ".join(
        str(v) for v in parsed.values() if v is not None)
    by_dim = {
        "architect": architect_candidates(brief, parsed),
        "developer": developer_candidates(brief, parsed, text),
        "ops": ops_candidates(brief, parsed),
        "security": security_candidates(brief, parsed, text),
    }
    flat = [f for dim in DIMENSIONS for f in by_dim[dim]]
    return {
        "by_dimension": by_dim,
        "findings": flat,
        "count": len(flat),
        "note": ("Candidate findings pre-computed from the artifacts (conservative). "
                 "Reviewer: confirm/adjust each, then add the judgment findings the "
                 "rules can't see. These are a floor, not the full review."),
    }
