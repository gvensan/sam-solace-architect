"""Validation tools (v2spec §5.4).

Requirement tracing via keyword + section-heading matching against artifact content.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .._storage import read_text
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


# Map requirement keys to keyword tokens that, if present in an artifact, indicate coverage.
_REQUIREMENT_KEYWORDS: dict[str, list[str]] = {
    "delivery_mode": ["delivery", "guaranteed", "direct messaging"],
    "ordering": ["ordering", "per-key", "fifo"],
    "processing_guarantee": ["at-least-once", "exactly-once", "best-effort"],
    "latency_tier": ["latency", "p99", "sub-second", "sub-millisecond"],
    "topology": ["topology", "site", "region", "dmr"],
    "regulatory": ["pci", "soc 2", "gdpr", "hipaa", "mifid", "finra", "compliance"],
    "data_residency": ["data residency", "region", "in-region"],
    "audit": ["audit", "retention", "log"],
}


@coerce_args
async def trace_requirements(
    engagement_id: str,
    discovery_brief: dict,
    artifact_names: list[str],
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """For each requirement in the brief, list the artifacts that address it.

    ``user_id`` auto-resolves from ``tool_context`` — same plumbing as
    the storage-scoped tools — so authenticated users hit the right
    ``users/<uid>/<engagement>/`` namespace.

    The engagement_id parameter is positional-first so the LLM gets the
    binding order right when emitting positional args.
    """
    requirements: dict[str, Any] = discovery_brief.get("requirements", {}) or {}
    # Also pull regulatory/audit/data-residency from constraints if present at the top.
    for top in ("regulatory", "audit"):
        if top in discovery_brief and top not in requirements:
            requirements[top] = discovery_brief[top]

    matrix: dict[str, list[str]] = {req: [] for req in requirements}
    unaddressed: list[str] = []

    # Pre-load artifact contents under the resolved user's namespace.
    artifact_text: dict[str, str] = {}
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        for name in artifact_names:
            try:
                artifact_text[name] = read_text(engagement_id, name)
            except (FileNotFoundError, ValueError):
                continue

    for req_key in requirements:
        keywords = _REQUIREMENT_KEYWORDS.get(req_key, [req_key.replace("_", " ")])
        for art_name, art_text in artifact_text.items():
            lower = art_text.lower()
            if any(kw.lower() in lower for kw in keywords):
                matrix[req_key].append(art_name)

        if not matrix[req_key]:
            unaddressed.append(req_key)

    return ToolResult(ok=True, data={
        "matrix": matrix,
        "unaddressed": unaddressed,
        "summary": f"{len(matrix) - len(unaddressed)}/{len(matrix)} requirements addressed",
    })
