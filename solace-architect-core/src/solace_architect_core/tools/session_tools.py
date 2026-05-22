"""Session-state tools (v2spec §3.5).

Phase 1: in-memory + JSON-persisted to ``meta/session.yaml`` per engagement.
Phase 2+: re-implemented against SAM ADK session management.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .._storage import read_yaml, safe_read_yaml, write_yaml
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


_DEFAULT_SESSION = {
    "current_phase": "idle",
    "execution_mode": "interactive",  # "auto" | "interactive"
    "completed_steps": [],
    "active_step": None,
    "timing_data": {},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


@coerce_args
async def write_checkpoint(
    engagement_id: str,
    step: str,
    state: dict,
    by_agent: Optional[str] = None,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Persist a per-step checkpoint so the next turn knows where the prior
    turn got to and can skip work that's already done.

    The intended pattern: at task start, call ``read_checkpoint`` to see
    what the previous invocation finished; mid-turn, call
    ``write_checkpoint`` after every meaningful unit of work (e.g. after
    each artifact write, after each batch of questions answered). On a
    crash / disconnect / token-budget cap, the next invocation reads the
    checkpoint and resumes from there instead of redoing everything.

    Replaces the checkpoint for ``step`` wholesale — pass the full state
    you want recorded, not a delta. ``state`` is opaque to this tool;
    each agent decides its own shape (e.g. SADiscoveryAgent might track
    ``{"sections_done": [...], "last_question_id": "..."}``; SAValidationAgent
    might track ``{"checks_completed": [...]}``).

    Stored under ``meta/session.yaml`` as::

        checkpoints:
          discovery:
            state: {...}     # agent-defined shape
            updated_at: "2026-05-22T10:30:00Z"
            by_agent: SADiscoveryAgent

    Per-step storage means restarting one step (via reset_<step>)
    naturally leaves other steps' checkpoints intact.

    Parameters
    ----------
    engagement_id : str
        Engagement this checkpoint belongs to.
    step : str
        Lifecycle step id — same identifiers used by ``set_step_status``
        (``"discovery"``, ``"design"``, ``"review"``, etc.).
    state : dict
        Free-form agent-defined state. Anything serialisable as YAML
        works; keep it small (KB, not MB) — this is for resume hints,
        not for storing artifacts.
    by_agent : str | None
        Recording agent's class name. Optional but useful for debugging
        ("which agent last touched this checkpoint?"). Defaults to the
        empty string.
    """
    if not step or not isinstance(step, str):
        return ToolResult(ok=False, error="step must be a non-empty string")
    if not isinstance(state, dict):
        return ToolResult(ok=False, error="state must be a dict (got "
                          f"{type(state).__name__})")

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, "meta/session.yaml", default=dict(_DEFAULT_SESSION))
        checkpoints = dict(data.get("checkpoints", {}) or {})
        checkpoints[step] = {
            "state": state,
            "updated_at": _now_iso(),
            "by_agent": by_agent or "",
        }
        data["checkpoints"] = checkpoints
        write_yaml(engagement_id, "meta/session.yaml", data)
    return ToolResult(ok=True, data=checkpoints[step])


async def read_checkpoint(
    engagement_id: str,
    step: str,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Read the prior turn's checkpoint for ``step``, if any.

    Returns ``{"state": {}, "updated_at": None, "by_agent": ""}`` when
    no checkpoint exists — the agent should treat that as "first turn,
    start fresh". Returns the structured shape written by
    ``write_checkpoint`` otherwise.

    Pure read; never mutates state. Use at task start in the agent
    prompt's "load context" step, before doing any artifact-producing
    work.
    """
    if not step or not isinstance(step, str):
        return ToolResult(ok=False, error="step must be a non-empty string")

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = safe_read_yaml(engagement_id, "meta/session.yaml",
                              default=dict(_DEFAULT_SESSION))
    entry = (data.get("checkpoints") or {}).get(step) or {}
    return ToolResult(ok=True, data={
        "state": entry.get("state") or {},
        "updated_at": entry.get("updated_at"),
        "by_agent": entry.get("by_agent", ""),
    })


async def clear_checkpoint(
    engagement_id: str,
    step: str,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Remove the checkpoint for ``step``. Called by the restart paths so
    a Restart Discovery (etc.) wipes the resume hint too — otherwise a
    fresh run would skip work based on the prior run's progress and
    leave stale state.
    """
    if not step or not isinstance(step, str):
        return ToolResult(ok=False, error="step must be a non-empty string")

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, "meta/session.yaml",
                         default=dict(_DEFAULT_SESSION))
        checkpoints = dict(data.get("checkpoints", {}) or {})
        removed = checkpoints.pop(step, None) is not None
        if removed:
            data["checkpoints"] = checkpoints
            write_yaml(engagement_id, "meta/session.yaml", data)
    return ToolResult(ok=True, data={"step": step, "removed": removed})
