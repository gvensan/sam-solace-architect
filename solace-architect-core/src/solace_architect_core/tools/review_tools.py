"""Reviewer tool: one call that returns everything a reviewer needs.

Each reviewer (architect / developer / ops / security) otherwise runs
``list_artifacts`` + ~20 ``read_artifact`` calls just to gather the design, then
audits. That's ~20 LLM round-trips per reviewer (×4 reviewers) before any
judgment — token churn and stall exposure. ``get_review_pack`` collapses that to
ONE call: it bundles every design artifact AND the deterministic candidate
findings for the caller's dimension (computed by ``review_checks``). The reviewer
confirms/expands the candidates and audits the provided artifacts — no
per-artifact reads.

This is the bundled-read lever for the fan-out Review phase: reviewers are
dispatched as separate A2A tasks by SAOrchestratorAgent and read artifacts
themselves, so the deterministic content reaches them via THIS tool rather than
a kickoff injection (the way Validation/Blueprint get theirs).
"""

from __future__ import annotations

from typing import Any, Optional

from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult

# dimension → (source_agent, human title, perspective phrase). Mirrors the four
# reviewer agents. Used by backfill_review_narrative to map a dimension to the
# findings that reviewer recorded and to render a labelled narrative.
_DIMENSION_AGENT = {
    "architect": ("SAArchitectReviewerAgent", "Architecture", "architecture-perspective"),
    "developer": ("SADeveloperReviewerAgent", "Developer Experience", "developer-experience"),
    "ops": ("SAOpsReviewerAgent", "Operations", "operations-perspective"),
    "security": ("SASecurityReviewerAgent", "Security", "security-perspective"),
}

_SEVERITY_RANK = {"critical": 0, "important": 1, "advisory": 2}


def _render_review_narrative(dimension: str, agent: str, title: str,
                             perspective: str, findings: list[dict]) -> str:
    """Render a per-reviewer narrative .md from that reviewer's recorded findings.

    Deterministic recovery for when a reviewer recorded its findings but its
    narrative ``write_artifact`` was lost (transient stall / drop). The findings
    in ``meta/findings.yaml`` are the source of truth; this reconstructs the
    Verdict · Findings summary · Concerns · Out-of-scope skeleton the reviewer
    would have written. It is NOT the reviewer's own prose — the banner says so,
    and 'Strengths' can't be reconstructed from findings (findings are concerns),
    so that section is intentionally omitted.
    """
    ordered = sorted(findings, key=lambda f: (_SEVERITY_RANK.get(f.get("severity"), 3),
                                              f.get("id", "")))
    counts = {sev: sum(1 for f in findings if f.get("severity") == sev)
              for sev in ("critical", "important", "advisory")}
    verdict = "DONE_WITH_CONCERNS" if findings else "DONE"

    out_of_scope = " · ".join(
        f"{t.lower()} → {a}"
        for d, (a, t, _) in _DIMENSION_AGENT.items() if d != dimension
    )

    lines = [
        f"# {title} Review — {agent}",
        "",
        "> **Auto-reconstructed from recorded findings.** This reviewer's findings "
        "landed in `meta/findings.yaml`, but its narrative write was lost to a "
        "transient stall. This file was rebuilt deterministically from those "
        "findings — it is not the reviewer's original prose, and the Strengths "
        "section is omitted (not reconstructable from findings).",
        "",
        f"**Reviewer:** {agent}  ",
        f"**Perspective:** {perspective}  ",
        f"**Verdict:** {verdict}",
        "",
        "## Findings summary",
        "",
        f"- **Total:** {len(findings)}",
        f"- **Critical:** {counts['critical']}",
        f"- **Important:** {counts['important']}",
        f"- **Advisory:** {counts['advisory']}",
        "",
        "## Concerns",
        "",
    ]
    if ordered:
        for f in ordered:
            fid = f.get("id", "F?")
            sev = f.get("severity", "advisory")
            desc = (f.get("description") or "").strip()
            summary = desc.split(". ")[0][:100] if desc else "(no description)"
            lines += [
                f"### {fid} — {sev}: {summary}",
                f"**Affected:** {f.get('affected_artifact') or '(unspecified)'}  ",
                f"**Issue:** {desc or '(no description recorded)'}  ",
                f"**Recommendation:** {(f.get('recommendation') or '(none recorded)').strip()}",
                "",
            ]
    else:
        lines += ["_No findings were recorded by this reviewer._", ""]

    lines += [
        "## Out of scope",
        "",
        f"Handled by other reviewers: {out_of_scope}.",
        "",
    ]
    return "\n".join(lines)


@coerce_args
async def backfill_review_narrative(engagement_id: str, dimension: str,
                                    force: bool = False,
                                    user_id: Optional[str] = None,
                                    tool_context: Any = None) -> ToolResult:
    """Reconstruct ``reviews/<dimension>-review.md`` from recorded findings.

    Fallback for when a reviewer recorded findings but its narrative write was
    lost. ``dimension``: architect | developer | ops | security.

    Safe by default: if the narrative already exists it is NOT overwritten
    (returns ``skipped=True``) unless ``force=True`` — so a reviewer's genuine
    prose is never clobbered. If the reviewer recorded NO findings, nothing is
    written (the reviewer likely never ran) and ``ok=False`` is returned so the
    caller re-dispatches instead of fabricating an empty review.
    """
    from .._storage import safe_artifact_path, safe_read_yaml, write_text
    from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user

    dim = (dimension or "").strip().lower()
    if dim not in _DIMENSION_AGENT:
        return ToolResult(ok=False, error=f"unknown dimension '{dimension}' "
                          f"(expected one of {', '.join(_DIMENSION_AGENT)})")
    agent, title, perspective = _DIMENSION_AGENT[dim]
    artifact_name = f"reviews/{dim}-review.md"

    try:
        with _scoped_user(_resolve_user_id(user_id, tool_context)):
            if not force and safe_artifact_path(engagement_id, artifact_name).exists():
                return ToolResult(ok=True, data={"artifact_name": artifact_name,
                                                 "skipped": True,
                                                 "reason": "narrative already present"})
            findings = safe_read_yaml(engagement_id, "meta/findings.yaml",
                                      default={"findings": []})["findings"]
            mine = [f for f in findings if f.get("source_agent") == agent]
            if not mine:
                return ToolResult(ok=False, error=(
                    f"no findings recorded by {agent}; reviewer likely never ran — "
                    f"re-dispatch it rather than backfilling an empty narrative"))
            content = _render_review_narrative(dim, agent, title, perspective, mine)
            write_text(engagement_id, artifact_name, content)
        return ToolResult(ok=True, data={"artifact_name": artifact_name,
                                         "findings_rendered": len(mine),
                                         "backfilled": True})
    except Exception as e:
        return ToolResult(ok=False, error=f"backfill_review_narrative failed: {e}")


# Reviewer agent names — used to match the orchestrator's operational
# "<Reviewer> failed operationally during Review phase … Retry recommended"
# open-items against the reviewer that (later) actually succeeded.
_REVIEWER_AGENTS = {agent for (agent, _t, _p) in _DIMENSION_AGENT.values()}
_AGENT_TO_DIMENSION = {agent: dim for dim, (agent, _t, _p) in _DIMENSION_AGENT.items()}


@coerce_args
async def reconcile_reviewer_failure_open_items(engagement_id: str,
                                                user_id: Optional[str] = None,
                                                tool_context: Any = None) -> ToolResult:
    """Resolve stale operational "<Reviewer> failed operationally … Retry
    recommended" open-items once that reviewer has actually recorded findings.

    When a reviewer's peer dispatch times out, SAOrchestratorAgent records an
    ADVISORY operational open-item as a breadcrumb. If the reviewer is later
    retried and succeeds (records findings + narrative), nothing closes that
    breadcrumb — it lingers as a stale "open" item that misrepresents the
    engagement (e.g. all four reviewers show "Retry recommended" while
    findings.yaml proves all four ran). This deterministically resolves any such
    item whose named reviewer now has findings. Safe + idempotent: only touches
    items that (a) are still open, (b) carry the operational-failure marker, and
    (c) name a reviewer present in findings; returns resolved=0 when nothing
    matches.
    """
    from .._storage import read_yaml, write_yaml, safe_read_yaml, safe_artifact_path
    from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user

    try:
        with _scoped_user(_resolve_user_id(user_id, tool_context)):
            findings = safe_read_yaml(engagement_id, "meta/findings.yaml",
                                      default={"findings": []})["findings"]
            finding_agents = {f.get("source_agent") for f in findings}
            data = read_yaml(engagement_id, "meta/open-items.yaml",
                             default={"open_items": []})
            resolved = []
            for it in data.get("open_items", []):
                if it.get("status") != "open":
                    continue
                desc = (it.get("description") or "").lower()
                if "failed operationally" not in desc:
                    continue
                named = next((a for a in _REVIEWER_AGENTS if a.lower() in desc), None)
                if not (named and named in finding_agents):
                    continue
                # Require the reviewer's canonical narrative artifact before
                # clearing the operational-retry breadcrumb. findings.yaml alone
                # is a partial-progress signal: reviewers record findings
                # (step 5) BEFORE writing reviews/<dim>-review.md (step 6), so a
                # single finding from a mid-stream timeout would otherwise
                # silently mark an incomplete audit as recovered.
                # backfill_review_narrative writes this .md from findings when
                # completion is genuine, so its presence here — original OR
                # backfilled — is the durable completion signal.
                dim = _AGENT_TO_DIMENSION.get(named)
                if not dim or not safe_artifact_path(
                        engagement_id, f"reviews/{dim}-review.md").exists():
                    continue
                it["status"] = "resolved"
                it["resolution_note"] = (
                    f"Auto-resolved: {named} produced reviews/{dim}-review.md "
                    f"with findings recorded; operational retry no longer needed.")
                resolved.append(it.get("id"))
            if resolved:
                write_yaml(engagement_id, "meta/open-items.yaml", data)
        return ToolResult(ok=True, data={"resolved": len(resolved),
                                         "resolved_ids": resolved})
    except Exception as e:
        return ToolResult(ok=False, error=f"reconcile_reviewer_failure_open_items failed: {e}")


@coerce_args
async def get_review_pack(engagement_id: str, dimension: str = "all",
                          user_id: Optional[str] = None,
                          tool_context: Any = None) -> ToolResult:
    """Return the design-artifact bundle + this dimension's candidate findings.

    ``dimension``: architect | developer | ops | security (else "all" → every
    dimension's candidates). ``user_id`` is auto-resolved from ``tool_context``
    (the A2A context SAM injects) the same way ``read_artifact`` does — so the
    reads land in the right user namespace without the agent passing it. One
    call replaces ~20 ``read_artifact`` round-trips.
    """
    import yaml as _yaml
    from ..orchestrator import context_pack as _cp
    from ..orchestrator import review_checks as _rc
    from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
    from .._storage import read_yaml

    dim = (dimension or "all").strip().lower()

    def _gather() -> dict:
        bundle = _cp.build_artifact_bundle(engagement_id)
        brief = read_yaml(engagement_id, "discovery/discovery-brief.yaml", default={}) or {}
        parsed: dict = {}
        for name, raw in bundle.get("artifacts", {}).items():
            try:
                parsed[name] = _yaml.safe_load(raw)
            except Exception:
                parsed[name] = None
        cf = _rc.candidate_findings(brief, parsed)
        candidates = cf["by_dimension"].get(dim, cf["findings"]) if dim in _rc.DIMENSIONS else cf["findings"]
        return {
            "dimension": dim,
            "artifacts": bundle.get("artifacts", {}),
            "present": bundle.get("present", []),
            "missing": bundle.get("missing", []),
            "candidate_findings": candidates,
            "note": ("All design artifacts are inlined here — do NOT call "
                     "list_artifacts / read_artifact for them again. The "
                     "candidate_findings are conservative deterministic findings "
                     "for your dimension: confirm/adjust each (record_finding) and "
                     "add the judgment findings the rules can't see."),
        }

    try:
        # Scope reads to the resolved user namespace (explicit user_id, else the
        # a2a_context SAM injects) — like read_artifact. Without this the bundle
        # reads UNSCOPED and comes back empty on real (user-namespaced) engagements.
        with _scoped_user(_resolve_user_id(user_id, tool_context)):
            data = _gather()
        return ToolResult(ok=True, data=data)
    except Exception as e:  # never hard-fail a reviewer turn
        return ToolResult(ok=False, error=f"get_review_pack failed: {e}")
