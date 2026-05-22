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
  - ``IN_PROGRESS``          — agent is actively working on the step
                               and isn't waiting on user input. Call at
                               task start for long-running phases
                               (validation, blueprint) so the dashboard
                               shows mid-flight progress rather than
                               NOT_STARTED.
  - ``SKIPPED``              — step is not applicable to this engagement
                               (opt-out at intake, or brief-driven scope
                               exclusion). Treated as terminal-advance for
                               CTA chaining — the dashboard skips over it
                               instead of waiting on it.
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

from .._storage import read_yaml, safe_read_yaml, write_yaml
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


def _iso_to_dt(iso: str) -> datetime | None:
    """Parse a `_now_iso()`-style timestamp; tolerate trailing 'Z' or offset."""
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


_STATUS_VALUES = (
    "DONE", "DONE_WITH_CONCERNS", "BLOCKED",
    "NEEDS_CONTEXT",    # waiting on user input
    "IN_PROGRESS",      # agent actively working, not waiting on user
    "SKIPPED",
    "NOT_STARTED",
)
_STATUS_FILE = "meta/engagement-status.yaml"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _update_step_timing(
    session: dict, step: str, prev_status: str, new_status: str,
    started_at: str, now_iso: str, now_dt: datetime,
) -> dict:
    """Maintain ``timing_data[step]`` across step-status transitions.

    Clocks time spent in NEEDS_CONTEXT as ``user_wait_sec`` (per
    block, summed across re-entries) and derives
    ``execution_sec = wall_sec - user_wait_sec`` on finalize. Without
    this, ``user_wait_sec`` was hardcoded to 0 and ``execution_sec``
    equalled wall_sec — the Stats "user wait" and "execution" tiles
    were identical and meaningless.

    Internal ``_blocked_at`` key holds the open NEEDS_CONTEXT
    timestamp; popped when the block closes or the step finalizes.
    BLOCKED is NOT counted as user-wait (the agent is blocked, not
    the user) — only NEEDS_CONTEXT contributes.
    """
    timing = dict(session.get("timing_data", {}) or {})
    entry = dict(timing.get(step, {}) or {})

    # Closing a NEEDS_CONTEXT block — accumulate the wait into a
    # running total so re-entries (user answers, agent asks again)
    # add up across the step's lifetime.
    if prev_status == "NEEDS_CONTEXT" and new_status != "NEEDS_CONTEXT":
        blocked_at = entry.get("_blocked_at")
        if blocked_at:
            blocked_dt = _iso_to_dt(blocked_at)
            if blocked_dt:
                wait_delta = max(0, int((now_dt - blocked_dt).total_seconds()))
                entry["user_wait_sec"] = int(entry.get("user_wait_sec", 0)) + wait_delta
            entry.pop("_blocked_at", None)

    # Opening a NEEDS_CONTEXT block.
    if new_status == "NEEDS_CONTEXT" and prev_status != "NEEDS_CONTEXT":
        entry["_blocked_at"] = now_iso
        entry.setdefault("user_wait_sec", 0)

    # Finalize — compute wall_sec + the corrected execution_sec.
    # Always seed user_wait_sec to 0 on finalize so the field is present
    # even for steps that never entered NEEDS_CONTEXT (e.g. BLOCKED →
    # DONE). Stats consumers can then `t.get("user_wait_sec", 0)` AND
    # also see the field exists in the serialized YAML.
    if new_status in ("DONE", "DONE_WITH_CONCERNS"):
        started_dt = _iso_to_dt(started_at)
        if started_dt:
            wall_sec = max(0, int((now_dt - started_dt).total_seconds()))
            wait_sec = int(entry.get("user_wait_sec", 0))
            entry["wall_sec"] = wall_sec
            entry["user_wait_sec"] = wait_sec
            entry["execution_sec"] = max(0, wall_sec - wait_sec)
            entry["recorded_at"] = now_iso
        # Drop any open block — the step is over, nothing more to wait on.
        entry.pop("_blocked_at", None)

    if entry:
        timing[step] = entry
        session["timing_data"] = timing
    return session


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

        # Maintain timing_data on EVERY transition (not just finalize),
        # so user_wait_sec accumulates while the step sits in
        # NEEDS_CONTEXT. The finalize branch inside the helper computes
        # the corrected execution_sec = wall_sec - user_wait_sec. Never
        # break the status write if the timing update fails.
        try:
            prev_status = prev.get("status", "NOT_STARTED")
            now_dt = datetime.now(timezone.utc)
            session = read_yaml(engagement_id, "meta/session.yaml", default={}) or {}
            session = _update_step_timing(
                session, step, prev_status, status, started_at, now_iso, now_dt,
            )
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
        # safe_read_yaml: read-only, polled by dashboard / lifecycle banner
        # multiple times per minute. A corrupt status file degrades to
        # empty-steps + WARNING log rather than 500-ing the HTTP request.
        # set_step_status / clear_step_status (write paths) stay on
        # read_yaml so a parse error there blocks the write instead of
        # silently overwriting a corrupt-but-recoverable file.
        data = safe_read_yaml(engagement_id, _STATUS_FILE, default={"steps": {}}) or {"steps": {}}
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


@coerce_args
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

    # `scopes_done` arrives as a real list thanks to @coerce_args (it would
    # otherwise be a JSON-encoded string when LiteLLM/ADK fail to decode the
    # tool call). See _arg_coercion.py for the full rationale.

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        data = read_yaml(engagement_id, _STATUS_FILE, default={"steps": {}}) or {"steps": {}}
        if "steps" not in data or not isinstance(data["steps"], dict):
            data["steps"] = {}
        step_entry = data["steps"].get(step) or {}
        step_entry["scope_progress"] = {
            "current": current_scope,
            "status": status,
            "next": next_scope or None,
            "done": [str(s) for s in (scopes_done or [])],
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
