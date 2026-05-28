"""Deterministic Design-phase orchestration state — the single source of truth.

ONE owner writes this document: the server-side Design orchestrator. The
per-scope worker (SADomainAgent in worker mode) never writes it. That
single-writer invariant is what makes the classic
``set_step_status``-clobbers-``scope_progress`` bug impossible here — there is
exactly one writer and one schema, so nothing can race or overwrite a field it
doesn't own.

The functions that compute *what happens next* (``next_scope``, ``is_complete``,
``decide_next``) are pure functions of a plain ``dict`` state document. They
have no storage, no LLM, and no async in the loop, so the entire control flow
is exercised by ordinary unit tests — which is the whole reason for pulling the
orchestration out of the agent. ``load_state`` / ``save_state`` wrap the dict in
engagement-scoped storage; they are the only I/O here.

State document shape (``meta/design-state.yaml``)::

    version: 1
    mode: auto                 # auto | interactive
    created_at: "2026-05-27T12:00:00Z"
    updated_at: "2026-05-27T12:34:00Z"
    scopes:                    # ordered — applicable scopes only
      - name: topic-design
        status: done           # pending|running|done|done_with_concerns|needs_input|blocked
        attempts: 1
        updated_at: "..."
        note: ""
      - name: broker-select
        status: pending
        attempts: 0
        updated_at: "..."
        note: ""
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .._storage import read_yaml, write_yaml
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user

STATE_FILE = "meta/design-state.yaml"
STATE_VERSION = 1

# Per-scope retry budget. A scope dispatched this many times without reaching a
# terminal-advance state is surfaced as ``retry_exhausted`` rather than
# re-dispatched forever (the classic path's infinite re-run failure mode).
MAX_ATTEMPTS = 3

# Scope lifecycle statuses.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
DONE_WITH_CONCERNS = "done_with_concerns"
NEEDS_INPUT = "needs_input"
BLOCKED = "blocked"

# Statuses that mean "the orchestrator no longer needs to act on this scope" —
# used to decide whether to advance to the next one.
_TERMINAL_ADVANCE = frozenset({DONE, DONE_WITH_CONCERNS})

VALID_MODES = frozenset({"auto", "interactive"})


def _now_iso() -> str:
    """UTC timestamp matching the format used elsewhere in core storage."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── construction ────────────────────────────────────────────────────────────


def init_state(applicable_scopes: list, mode: str = "auto") -> dict:
    """Build a fresh state document from the ordered list of applicable scopes.

    ``applicable_scopes`` is the orchestrator's plan (e.g. from
    ``get_engagement_plan``), already filtered to the scopes this engagement
    needs and in canonical order. Order is preserved; duplicates are dropped
    defensively.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")
    scopes = [s for s in (applicable_scopes or []) if s]
    if not scopes:
        raise ValueError("applicable_scopes must be non-empty")
    seen: set = set()
    ordered: list = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    now = _now_iso()
    return {
        "version": STATE_VERSION,
        "mode": mode,
        "created_at": now,
        "updated_at": now,
        "scopes": [
            {"name": s, "status": PENDING, "attempts": 0, "updated_at": now, "note": ""}
            for s in ordered
        ],
    }


# ── pure queries ────────────────────────────────────────────────────────────


def _scope(state: dict, name: str) -> Optional[dict]:
    for sc in state.get("scopes", []):
        if sc.get("name") == name:
            return sc
    return None


def scope_status(state: dict, name: str) -> Optional[str]:
    sc = _scope(state, name)
    return sc.get("status") if sc else None


def next_scope(state: dict) -> Optional[str]:
    """First applicable scope not yet in a terminal-advance state.

    Returns ``None`` when every scope is ``done``/``done_with_concerns`` (Design
    complete). A ``blocked`` or ``needs_input`` scope is at the front of the line
    and IS returned, so the orchestrator surfaces it rather than skipping past
    unfinished work — the classic path's re-execution bug was precisely a failure
    to track "what's actually next", so this stays strict and ordered.
    """
    for sc in state.get("scopes", []):
        if sc.get("status") not in _TERMINAL_ADVANCE:
            return sc.get("name")
    return None


def done_scopes(state: dict) -> list:
    return [sc["name"] for sc in state.get("scopes", []) if sc.get("status") in _TERMINAL_ADVANCE]


def is_complete(state: dict) -> bool:
    scopes = state.get("scopes", [])
    return bool(scopes) and all(sc.get("status") in _TERMINAL_ADVANCE for sc in scopes)


def _parse_iso(ts: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def metrics(state: dict) -> dict:
    """Observability summary for an orchestrated Design run — derived purely from
    the state doc (no extra instrumentation). The headline number is
    ``retries``: dispatch attempts beyond the first, i.e. re-runs. The classic
    engine's defining failure was re-executing completed scopes; here that should
    sit at ~0, and this makes it measurable.
    """
    scopes = state.get("scopes", [])
    total = len(scopes)
    done = sum(1 for s in scopes if s.get("status") in _TERMINAL_ADVANCE)
    attempts = sum(int(s.get("attempts", 0)) for s in scopes)
    retries = sum(max(0, int(s.get("attempts", 0)) - 1) for s in scopes)
    started = _parse_iso(state.get("created_at"))
    updated = _parse_iso(state.get("updated_at"))
    wall = (updated - started).total_seconds() if (started and updated) else None
    return {
        "engine": "orchestrated",
        "scopes_total": total,
        "scopes_done": done,
        "completion_pct": round(100.0 * done / total, 1) if total else 0.0,
        "complete": is_complete(state),
        "total_attempts": attempts,
        "retries": retries,                              # re-runs beyond the first try
        "retried_scopes": [s["name"] for s in scopes if int(s.get("attempts", 0)) > 1],
        "blocked_scopes": [s["name"] for s in scopes if s.get("status") == BLOCKED],
        "wall_clock_seconds": round(wall, 1) if wall is not None else None,
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
    }


# ── transitions (the single mutation point) ──────────────────────────────────


def set_status(
    state: dict, name: str, status: str, *, note: str = "", bump_attempt: bool = False
) -> dict:
    """Transition one scope's status in place and return the state.

    Raising on an unknown scope is deliberate: the orchestrator should only ever
    transition scopes that exist in the plan, so a missing scope is a bug to
    surface, not a silent no-op.
    """
    sc = _scope(state, name)
    if sc is None:
        raise KeyError(f"scope {name!r} not in design state")
    sc["status"] = status
    if bump_attempt:
        sc["attempts"] = int(sc.get("attempts", 0)) + 1
    sc["note"] = note or ""
    now = _now_iso()
    sc["updated_at"] = now
    state["updated_at"] = now
    return state


def begin_scope(state: dict, name: str) -> dict:
    """Mark a scope RUNNING and count the dispatch attempt (retry budget)."""
    return set_status(state, name, RUNNING, bump_attempt=True)


def complete_scope(state: dict, name: str, *, with_concerns: bool = False, note: str = "") -> dict:
    """Mark a scope terminal-advance. Idempotent: re-completing is a stable no-op
    on status (the classic path duplicated work on re-entry; here it can't)."""
    return set_status(state, name, DONE_WITH_CONCERNS if with_concerns else DONE, note=note)


def needs_input(state: dict, name: str, *, note: str = "") -> dict:
    """The worker returned a question — pause this scope for the user."""
    return set_status(state, name, NEEDS_INPUT, note=note)


def fail_scope(state: dict, name: str, *, note: str = "") -> dict:
    """A dispatch failed/stalled. Return the scope to PENDING (attempt was already
    counted at ``begin_scope``) so ``decide_next`` either retries or, once the
    budget is spent, surfaces ``retry_exhausted``."""
    return set_status(state, name, PENDING, note=note)


def block_scope(state: dict, name: str, *, note: str = "") -> dict:
    return set_status(state, name, BLOCKED, note=note)


def reset_scope(state: dict, name: str, *, note: str = "") -> dict:
    """Clear a scope back to PENDING with a fresh retry budget (attempts=0).

    Used by the 'retry scope' affordance after retry_exhausted/blocked: without
    zeroing attempts, decide_next would immediately re-surface the same
    exhausted/blocked state."""
    sc = _scope(state, name)
    if sc is None:
        raise KeyError(f"scope {name!r} not in design state")
    sc["attempts"] = 0
    return set_status(state, name, PENDING, note=note)


# ── the decision brain (pure function of state) ──────────────────────────────


def decide_next(state: dict) -> dict:
    """Decide what happens next — a pure function of the current state.

    Returns an action dict the executor obeys verbatim::

        {"action": "complete"}                                all scopes terminal
        {"action": "blocked", "scope", "note"}                front scope blocked
        {"action": "await_user", "scope"}                     front scope asked a question
        {"action": "in_flight", "scope"}                      a dispatch is still running
        {"action": "retry_exhausted", "scope", "attempts"}    budget spent, not done
        {"action": "dispatch", "scope", "attempt", "done"}    run this scope next
    """
    nxt = next_scope(state)
    if nxt is None:
        return {"action": "complete"}
    sc = _scope(state, nxt) or {}
    status = sc.get("status")
    attempts = int(sc.get("attempts", 0))
    if status == BLOCKED:
        return {"action": "blocked", "scope": nxt, "note": sc.get("note", "")}
    if status == NEEDS_INPUT:
        return {"action": "await_user", "scope": nxt}
    if status == RUNNING:
        # A task for this scope is in flight; the executor should wait for its
        # outcome rather than double-dispatch.
        return {"action": "in_flight", "scope": nxt}
    if attempts >= MAX_ATTEMPTS:
        return {"action": "retry_exhausted", "scope": nxt, "attempts": attempts}
    return {
        "action": "dispatch",
        "scope": nxt,
        "attempt": attempts + 1,
        "done": done_scopes(state),
    }


# ── storage (the only I/O) ────────────────────────────────────────────────────


def load_state(engagement_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Load the design-state document, or None if this engagement has none yet."""
    with _scoped_user(_resolve_user_id(user_id, None)):
        data = read_yaml(engagement_id, STATE_FILE, default=None)
    return data or None


def save_state(engagement_id: str, state: dict, user_id: Optional[str] = None) -> dict:
    """Persist the design-state document. The orchestrator is the ONLY caller —
    that single-writer rule is the core invariant of this module."""
    state["updated_at"] = _now_iso()
    with _scoped_user(_resolve_user_id(user_id, None)):
        write_yaml(engagement_id, STATE_FILE, state)
    return state
