"""Validation tools (v2spec §5.4).

Requirement tracing via keyword + section-heading matching against artifact content.
"""

from __future__ import annotations

import re
from typing import Any

from .._storage import read_text
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


async def trace_requirements(discovery_brief: dict, artifact_names: list[str], engagement_id: str) -> ToolResult:
    """For each requirement in the brief, list the artifacts that address it."""
    requirements: dict[str, Any] = discovery_brief.get("requirements", {}) or {}
    # Also pull regulatory/audit/data-residency from constraints if present at the top.
    for top in ("regulatory", "audit"):
        if top in discovery_brief and top not in requirements:
            requirements[top] = discovery_brief[top]

    matrix: dict[str, list[str]] = {req: [] for req in requirements}
    unaddressed: list[str] = []

    # Pre-load artifact contents
    artifact_text: dict[str, str] = {}
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
