"""Lifecycle / step-status tools.

Each agent in the SA family signals where its step landed at end-of-turn
via ``set_step_status``. The frontend reads ``meta/engagement-status.yaml``
to decide whether to mark a step DONE on the Progress banner or to keep
showing the in-progress CTA.

Status values mirror the Completion Status convention (Decision 42 in
the v2spec):

  - ``DONE``                 — step finished cleanly; no concerns left
  - ``DONE_WITH_CONCERNS``   — step finished but advisory open-items remain
  - ``BLOCKED``              — step cannot proceed because of unresolved
                               blocking open-items
  - ``NEEDS_CONTEXT``        — waiting on user input (the agent's last
                               turn was a question)
  - ``NOT_STARTED``          — step hasn't run yet (default if absent)

Stored shape (one file per engagement, under engagement-scoped storage)::

    steps:
      discovery:
        status: DONE
        updated_at: "2026-05-17T11:23:45Z"
        agent: SADiscoveryAgent
        note: "Brief written; 2 advisory items remain."
      design:
        status: NOT_STARTED
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .._storage import read_yaml, write_yaml
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
from .artifact_tools import ToolResult


def _iso_to_dt(iso: str) -> datetime | None:
    """Parse a `_now_iso()`-style timestamp; tolerate trailing 'Z' or offset."""
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


_STATUS_VALUES = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT", "NOT_STARTED")
_STATUS_FILE = "meta/engagement-status.yaml"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def set_step_status(
    engagement_id: str, step: str, status: str,
    note: Optional[str] = None, agent: Optional[str] = None,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Persist a step's Completion Status to ``meta/engagement-status.yaml``.

    The agent calls this at end-of-turn (alongside emitting Completion
    Status in chat per Decision 42) so the frontend can show accurate
    lifecycle state on the Progress banner — file-existence heuristics
    are too fragile (an empty placeholder summary made Discovery look
    done when it wasn't).

    Parameters
    ----------
    engagement_id : str
        The active engagement.
    step : str
        Lifecycle step id — e.g. ``"discovery"``, ``"design"``,
        ``"review"``, ``"validation"``, ``"event-portal"``, ``"blueprint"``.
    status : str
        One of: DONE, DONE_WITH_CONCERNS, BLOCKED, NEEDS_CONTEXT,
        NOT_STARTED.
    note : str | None
        Optional 1-line summary surfaced in the UI (e.g. "Brief written;
        2 advisory items remain").
    agent : str | None
        Name of the agent recording the status. Defaults to the step id
        capitalised + "Agent" if absent.
    user_id : str | None
        Same user-namespace plumbing as the other storage-scoped tools —
        lift from the [Active engagement: ..., user_id=<uuid>] header.
    """
    if status not in _STATUS_VALUES:
        return ToolResult(ok=False, error=f"status must be one of {_STATUS_VALUES}, got {status!r}")
    if not step or not isinstance(step, str):
        return ToolResult(ok=False, error="step must be a non-empty string")

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, _STATUS_FILE, default={"steps": {}}) or {"steps": {}}
        if "steps" not in data or not isinstance(data["steps"], dict):
            data["steps"] = {}
        now_iso = _now_iso()
        prev = data["steps"].get(step) or {}
        started_at = prev.get("started_at") or now_iso
        data["steps"][step] = {
            "status": status,
            "started_at": started_at,
            "updated_at": now_iso,
            "agent": agent or "",
            "note": note or "",
        }
        write_yaml(engagement_id, _STATUS_FILE, data)

        # When a step completes, mirror the duration into meta/session.yaml's
        # timing_data so compute_timeline / Stats view reflect it. Never break
        # the status write if the timing append fails.
        if status in ("DONE", "DONE_WITH_CONCERNS"):
            try:
                started_dt = _iso_to_dt(started_at) or datetime.now(timezone.utc)
                wall_sec = max(0, int((datetime.now(timezone.utc) - started_dt).total_seconds()))
                session = read_yaml(engagement_id, "meta/session.yaml", default={}) or {}
                timing = dict(session.get("timing_data", {}) or {})
                timing[step] = {
                    "wall_sec": wall_sec,
                    "execution_sec": wall_sec,
                    "user_wait_sec": 0,
                    "recorded_at": now_iso,
                }
                session["timing_data"] = timing
                write_yaml(engagement_id, "meta/session.yaml", session)
            except Exception:
                pass
    return ToolResult(ok=True, data={"step": step, "status": status, "started_at": started_at})


async def get_engagement_status(
    engagement_id: str, user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Read all step statuses for an engagement.

    ``user_id`` auto-resolves from ``tool_context``.

    Returns ``{"steps": {step_id: {status, updated_at, agent, note}}}``.
    Missing steps are NOT defaulted to NOT_STARTED here — the caller
    treats absence as NOT_STARTED for free, and we want to keep the
    file shape honest about what's been recorded.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, _STATUS_FILE, default={"steps": {}}) or {"steps": {}}
    if "steps" not in data or not isinstance(data["steps"], dict):
        data["steps"] = {}
    return ToolResult(ok=True, data=data)


async def clear_step_status(
    engagement_id: str, step: str, user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Remove a step's status (used by the hard-reset flow). No-op if absent.

    ``user_id`` auto-resolves from ``tool_context``.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, _STATUS_FILE, default={"steps": {}}) or {"steps": {}}
        steps = data.get("steps", {})
        if step in steps:
            del steps[step]
            data["steps"] = steps
            write_yaml(engagement_id, _STATUS_FILE, data)
    return ToolResult(ok=True, data={"step": step, "cleared": True})


_SCOPE_STATUS_VALUES = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT")


async def record_scope_progress(
    engagement_id: str,
    step: str,
    current_scope: str,
    status: str,
    next_scope: Optional[str] = None,
    scopes_done: Optional[list] = None,
    note: Optional[str] = None,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Record progress through a multi-scope step (e.g. Design's 5 scopes).

    Each scope is dispatched as its own A2A task so the LLM-calls-per-task
    cap (default 30) doesn't bite mid-step. At end of each scope the agent
    calls this tool so the frontend's Auto-mode loop knows what to dispatch
    next; if ``next_scope`` is null the multi-scope step is done and the
    agent should ALSO call ``set_step_status(step, DONE)``.

    Stored shape under ``meta/engagement-status.yaml``::

        steps:
          design:
            status: NEEDS_CONTEXT     # step-level (unchanged)
            scope_progress:
              current: broker-select
              status: DONE_WITH_CONCERNS
              next: protocol-select
              done: [topic-design, broker-select]
              updated_at: "..."
              note: "auto-mode: ..."

    Parameters
    ----------
    engagement_id : str
        The active engagement.
    step : str
        Top-level lifecycle step (e.g. ``"design"``).
    current_scope : str
        Scope that just finished (e.g. ``"topic-design"``).
    status : str
        How the scope landed: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT.
    next_scope : str | None
        Scope to dispatch next; null if this was the final applicable scope.
    scopes_done : list[str] | None
        Full list of scopes completed so far (helps the frontend skip already-
        done scopes if the agent gets re-dispatched). The agent passes the
        running list; we don't merge — the agent is the source of truth.
    note : str | None
        Optional one-liner (e.g. ``"auto-mode: picked Direct for fanout"``).
    user_id : str | None
        Same user-namespace plumbing as other storage-scoped tools.
    """
    if status not in _SCOPE_STATUS_VALUES:
        return ToolResult(
            ok=False,
            error=f"status must be one of {_SCOPE_STATUS_VALUES}, got {status!r}",
        )
    if not step or not isinstance(step, str):
        return ToolResult(ok=False, error="step must be a non-empty string")
    if not current_scope or not isinstance(current_scope, str):
        return ToolResult(ok=False, error="current_scope must be a non-empty string")

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, _STATUS_FILE, default={"steps": {}}) or {"steps": {}}
        if "steps" not in data or not isinstance(data["steps"], dict):
            data["steps"] = {}
        step_entry = data["steps"].get(step) or {}
        step_entry["scope_progress"] = {
            "current": current_scope,
            "status": status,
            "next": next_scope or None,
            "done": list(scopes_done or []),
            "updated_at": _now_iso(),
            "note": note or "",
        }
        data["steps"][step] = step_entry
        write_yaml(engagement_id, _STATUS_FILE, data)
    return ToolResult(
        ok=True,
        data={
            "step": step,
            "current_scope": current_scope,
            "status": status,
            "next_scope": next_scope or None,
        },
    )
