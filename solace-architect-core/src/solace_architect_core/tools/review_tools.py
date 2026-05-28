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
