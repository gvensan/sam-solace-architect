"""Session-state tools (v2spec §3.5).

Phase 1: in-memory + JSON-persisted to ``meta/session.yaml`` per engagement.
Phase 2+: re-implemented against SAM ADK session management.
"""

from __future__ import annotations

from typing import Any

from .._storage import read_yaml, safe_read_yaml, write_yaml
from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


_DEFAULT_SESSION = {
    "current_phase": "idle",
    "execution_mode": "interactive",  # "auto" | "interactive"
    "completed_steps": [],
    "active_step": None,
    "timing_data": {},
}


async def read_session_state(engagement_id: str) -> ToolResult:
    # safe_read_yaml: corrupt session.yaml degrades to defaults rather than
    # crashing the dashboard, which polls this every few seconds. The
    # update_session_state path below stays on the raising read_yaml so a
    # parse error there prevents us from overwriting an existing corrupt
    # file with default state (would silently destroy timing_data /
    # completed_steps).
    data = safe_read_yaml(engagement_id, "meta/session.yaml", default=dict(_DEFAULT_SESSION))
    data["engagement_id"] = engagement_id
    return ToolResult(ok=True, data=data)


@coerce_args
async def update_session_state(engagement_id: str, updates: dict) -> ToolResult:
    data = read_yaml(engagement_id, "meta/session.yaml", default=dict(_DEFAULT_SESSION))
    valid_keys = {"current_phase", "execution_mode", "completed_steps", "active_step", "timing_data"}
    bad = set(updates) - valid_keys
    if bad:
        return ToolResult(ok=False, error=f"invalid session keys: {sorted(bad)}")
    data.update(updates)
    write_yaml(engagement_id, "meta/session.yaml", data)
    data["engagement_id"] = engagement_id
    return ToolResult(ok=True, data=data)
