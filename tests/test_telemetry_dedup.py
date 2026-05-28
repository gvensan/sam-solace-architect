"""Telemetry de-duplication guard.

SAM occasionally invokes an agent's ``after_model_callback`` twice for a
single ``LlmResponse`` — observed in ``llm-calls.jsonl`` as two byte-identical
rows whose ``ts`` differ by ~1 ms. That double-bills tokens and double-renders
the chat activity pills. ``_already_recorded`` collapses the duplicate via two
independent guards (response-object identity + a short-window token
fingerprint). These tests pin both guards and the safety boundaries that keep
genuine turns from being suppressed.
"""

from __future__ import annotations

import solace_architect_core._sam_telemetry_patch as patch


class _State(dict):
    """Minimal stand-in for ADK ``callback_context.state`` (dict-like)."""


class _Ctx:
    def __init__(self) -> None:
        self.state = _State()


class _Resp:
    """A mutable fake LlmResponse — supports the object-identity stamp."""


def test_same_object_recorded_once():
    ctx, resp = _Ctx(), _Resp()
    assert patch._already_recorded(ctx, resp, "eng", "SADomainAgent", 100, 20) is False
    # Same object handed back a second time → recognised as a duplicate.
    assert patch._already_recorded(ctx, resp, "eng", "SADomainAgent", 100, 20) is True


def test_distinct_copy_same_fingerprint_within_window_is_duplicate():
    ctx = _Ctx()
    first, copy = _Resp(), _Resp()  # second invoke carries a *copy*
    assert patch._already_recorded(ctx, first, "eng", "SADomainAgent", 100, 20) is False
    assert patch._already_recorded(ctx, copy, "eng", "SADomainAgent", 100, 20) is True


def test_same_fingerprint_after_window_is_not_duplicate(monkeypatch):
    ctx = _Ctx()
    t = [1000.0]
    monkeypatch.setattr(patch.time, "monotonic", lambda: t[0])
    assert patch._already_recorded(ctx, _Resp(), "eng", "SADomainAgent", 100, 20) is False
    t[0] += patch._DEDUP_WINDOW_S + 0.1  # window elapsed → a genuine new turn
    assert patch._already_recorded(ctx, _Resp(), "eng", "SADomainAgent", 100, 20) is False


def test_different_token_counts_are_distinct_turns():
    ctx = _Ctx()
    assert patch._already_recorded(ctx, _Resp(), "eng", "SADomainAgent", 100, 20) is False
    # Input tokens climb every turn, so a different count is a real new turn.
    assert patch._already_recorded(ctx, _Resp(), "eng", "SADomainAgent", 180, 31) is False


def test_zero_usage_is_never_a_fingerprint_duplicate():
    # No usage metadata (in=out=0): guard-2 can't fingerprint, so distinct
    # objects are never collapsed — guard-1 still covers the same-object case.
    ctx = _Ctx()
    assert patch._already_recorded(ctx, _Resp(), "eng", "SADomainAgent", 0, 0) is False
    assert patch._already_recorded(ctx, _Resp(), "eng", "SADomainAgent", 0, 0) is False


def test_different_engagement_same_tokens_not_duplicate():
    ctx = _Ctx()
    assert patch._already_recorded(ctx, _Resp(), "eng-a", "SADomainAgent", 100, 20) is False
    assert patch._already_recorded(ctx, _Resp(), "eng-b", "SADomainAgent", 100, 20) is False


# ── step_id / sam_task_id resolution (were null before) ──────────────────────

class _Inv:
    def __init__(self, invocation_id=None, id=None):
        if invocation_id is not None:
            self.invocation_id = invocation_id
        if id is not None:
            self.id = id


class _CtxInv(_Ctx):
    def __init__(self, inv=None):
        super().__init__()
        self._invocation_context = inv


def test_step_id_derived_from_agent_when_state_empty():
    ctx = _Ctx()
    assert patch._resolve_step_id(ctx, "SADomainAgent") == "design"
    assert patch._resolve_step_id(ctx, "SAValidationAgent") == "validation"
    assert patch._resolve_step_id(ctx, "SAArchitectReviewerAgent") == "review"


def test_step_id_prefers_explicit_state():
    ctx = _Ctx(); ctx.state["step_id"] = "custom-step"
    assert patch._resolve_step_id(ctx, "SADomainAgent") == "custom-step"


def test_step_id_none_for_unknown_agent():
    assert patch._resolve_step_id(_Ctx(), "SomeOtherAgent") is None


def test_task_id_falls_back_to_invocation_id():
    ctx = _CtxInv(_Inv(invocation_id="inv-123"))
    assert patch._resolve_task_id(ctx) == "inv-123"


def test_task_id_prefers_explicit_state():
    ctx = _CtxInv(_Inv(invocation_id="inv-123"))
    ctx.state["logical_task_id"] = "task-abc"
    assert patch._resolve_task_id(ctx) == "task-abc"


def test_task_id_none_when_nothing_available():
    assert patch._resolve_task_id(_Ctx()) is None
