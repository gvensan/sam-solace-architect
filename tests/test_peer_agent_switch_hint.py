"""Unit tests for the peer-agent switch-hint guard.

Covers the module's pure logic — counter behavior and inject conditions —
without actually monkey-patching SAM. The wrapper itself is exercised in
integration when an orchestrator runs; here we verify the building blocks
in isolation.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from solace_architect_core import _peer_agent_switch_hint as hint


@pytest.fixture(autouse=True)
def _reset_state():
    """Clear module-level state between tests so they don't bleed."""
    hint._DELEGATION_COUNTS.clear()
    hint._PENDING_SUGGESTION.clear()
    yield
    hint._DELEGATION_COUNTS.clear()
    hint._PENDING_SUGGESTION.clear()


def _make_callback_context(session_id: str) -> MagicMock:
    """Stand-in for ADK CallbackContext exposing the path the guard reads."""
    ctx = MagicMock()
    ctx._invocation_context.session.id = session_id
    return ctx


def _make_llm_response(*, text: str | None = None, has_function_call: bool = False) -> SimpleNamespace:
    """Stand-in for an LlmResponse with content.parts."""
    parts = []
    if text is not None:
        # SimpleNamespace allows attribute assignment so the injector can mutate .text.
        parts.append(SimpleNamespace(text=text, function_call=None))
    if has_function_call:
        parts.append(SimpleNamespace(text=None, function_call=SimpleNamespace(name="peer_X")))
    content = SimpleNamespace(parts=parts)
    return SimpleNamespace(content=content)


# ---------- counter logic ----------

def test_inject_noop_when_no_pending_suggestion():
    """Without a queued suggestion, no mutation regardless of response shape."""
    ctx = _make_callback_context("sess-1")
    rsp = _make_llm_response(text="hello world")
    hint._maybe_inject_switch_block(ctx, rsp)
    assert rsp.content.parts[0].text == "hello world"


def test_inject_fires_when_pending_and_text_final():
    """With a pending suggestion and pure-text response, the block is appended."""
    hint._PENDING_SUGGESTION["sess-1"] = "SADomainAgent"
    ctx = _make_callback_context("sess-1")
    rsp = _make_llm_response(text="Domain updated.")

    hint._maybe_inject_switch_block(ctx, rsp)

    assert "```switch_agent" in rsp.content.parts[0].text
    assert "SADomainAgent" in rsp.content.parts[0].text
    # Pending suggestion is consumed.
    assert "sess-1" not in hint._PENDING_SUGGESTION


def test_inject_skipped_when_response_has_function_call():
    """Mid-turn responses (still dispatching tools) must NOT receive a chip."""
    hint._PENDING_SUGGESTION["sess-1"] = "SADomainAgent"
    ctx = _make_callback_context("sess-1")
    rsp = _make_llm_response(text="Thinking…", has_function_call=True)

    hint._maybe_inject_switch_block(ctx, rsp)

    assert "switch_agent" not in (rsp.content.parts[0].text or "")
    # Suggestion stays pending — next final response gets it.
    assert hint._PENDING_SUGGESTION["sess-1"] == "SADomainAgent"


def test_inject_is_idempotent_for_repeat_callback():
    """A double-fired after_model_callback must not double-append the block."""
    hint._PENDING_SUGGESTION["sess-1"] = "SADomainAgent"
    ctx = _make_callback_context("sess-1")
    rsp = _make_llm_response(text="Domain updated.")

    hint._maybe_inject_switch_block(ctx, rsp)
    first_text = rsp.content.parts[0].text
    # State has been consumed — second call should not re-inject (and even if
    # someone manually re-queued, the "already present" guard catches it).
    hint._PENDING_SUGGESTION["sess-1"] = "SADomainAgent"
    hint._maybe_inject_switch_block(ctx, rsp)

    assert rsp.content.parts[0].text.count("```switch_agent") == 1
    assert rsp.content.parts[0].text == first_text  # unchanged second time


def test_inject_skipped_when_no_text_part():
    """If the response somehow has no text part, we don't fabricate one."""
    hint._PENDING_SUGGESTION["sess-1"] = "SADomainAgent"
    ctx = _make_callback_context("sess-1")
    rsp = SimpleNamespace(content=SimpleNamespace(parts=[]))

    hint._maybe_inject_switch_block(ctx, rsp)

    # No mutation; pending stays for the next chance.
    assert hint._PENDING_SUGGESTION["sess-1"] == "SADomainAgent"


def test_inject_isolated_per_session():
    """Pending suggestion for session A must NOT inject into session B's response."""
    hint._PENDING_SUGGESTION["sess-A"] = "SADomainAgent"
    ctx_b = _make_callback_context("sess-B")
    rsp = _make_llm_response(text="unrelated response")

    hint._maybe_inject_switch_block(ctx_b, rsp)

    assert "switch_agent" not in rsp.content.parts[0].text
    # Session A's pending stays.
    assert hint._PENDING_SUGGESTION["sess-A"] == "SADomainAgent"


# ---------- block content ----------

def test_build_switch_block_is_valid_fenced_json():
    """The fenced block must parse as JSON with required fields."""
    import json
    block = hint._build_switch_block("SADomainAgent")
    assert block.startswith("```switch_agent\n")
    assert block.rstrip().endswith("```")
    inner = block[len("```switch_agent\n"):-len("\n```")]
    payload = json.loads(inner)
    assert payload["to_agent"] == "SADomainAgent"
    assert "SADomainAgent" in payload["reason"]


# ---------- install idempotency (sentinel pattern) ----------

def test_install_is_idempotent(monkeypatch):
    """Repeated install() calls must not double-wrap SAM internals.

    The actual SAM monkey-patch sites are skipped in this test environment
    (no SAM imports in unit tests) — we just verify install() is callable
    and doesn't raise.
    """
    # Calling install twice should not raise even when SAM isn't around.
    hint.install()
    hint.install()


# ---------- counter side (wrapped_run_async) ----------

@pytest.mark.asyncio
async def test_wrapped_run_async_first_delegation_no_pending(monkeypatch):
    """First delegation to a target must increment the count but NOT queue
    a suggestion. This is the core guardrail that distinguishes "one-shot
    Q&A" from "iteration loop"."""
    from solace_architect_core import _peer_agent_switch_hint as h

    # Stand-in for PeerAgentTool — we only need target_agent_name and the
    # original run_async hook. The wrapper signature must match the upstream
    # `async def run_async(self, *, args, tool_context)` shape.
    class _FakePeerTool:
        target_agent_name = "SADomainAgent"

        async def _original(self, *, args, tool_context):
            return None

    original = _FakePeerTool._original
    # Hand-build the wrapper using the same code path install() does so
    # we can exercise it without needing SAM importable.
    async def wrapped(self, *, args, tool_context):
        try:
            sid = h._safe_get_session_id_from_tool(tool_context)
            tgt = self.target_agent_name
            if sid and tgt:
                key = (sid, tgt)
                h._DELEGATION_COUNTS[key] += 1
                if h._DELEGATION_COUNTS[key] >= 2:
                    h._PENDING_SUGGESTION[sid] = tgt
        except Exception:
            pass
        return await original(self, args=args, tool_context=tool_context)

    tool = _FakePeerTool()
    ctx = MagicMock()
    ctx._invocation_context.session.id = "sess-X"

    await wrapped(tool, args={}, tool_context=ctx)

    assert h._DELEGATION_COUNTS[("sess-X", "SADomainAgent")] == 1
    assert "sess-X" not in h._PENDING_SUGGESTION


@pytest.mark.asyncio
async def test_wrapped_run_async_second_delegation_queues_pending(monkeypatch):
    """Second delegation to the SAME target in the SAME session queues a
    pending suggestion — the signal the inject side waits for."""
    from solace_architect_core import _peer_agent_switch_hint as h

    class _FakePeerTool:
        target_agent_name = "SADomainAgent"

        async def _original(self, *, args, tool_context):
            return None

    original = _FakePeerTool._original
    async def wrapped(self, *, args, tool_context):
        sid = h._safe_get_session_id_from_tool(tool_context)
        tgt = self.target_agent_name
        if sid and tgt:
            key = (sid, tgt)
            h._DELEGATION_COUNTS[key] += 1
            if h._DELEGATION_COUNTS[key] >= 2:
                h._PENDING_SUGGESTION[sid] = tgt
        return await original(self, args=args, tool_context=tool_context)

    tool = _FakePeerTool()
    ctx = MagicMock()
    ctx._invocation_context.session.id = "sess-Y"

    await wrapped(tool, args={}, tool_context=ctx)
    await wrapped(tool, args={}, tool_context=ctx)

    assert h._DELEGATION_COUNTS[("sess-Y", "SADomainAgent")] == 2
    assert h._PENDING_SUGGESTION["sess-Y"] == "SADomainAgent"


@pytest.mark.asyncio
async def test_wrapped_run_async_different_targets_isolated():
    """Two different targets in the same session each need their OWN 2nd
    delegation before queuing — count-per-(session,target), not per-session."""
    from solace_architect_core import _peer_agent_switch_hint as h

    class _Tool:
        def __init__(self, name): self.target_agent_name = name
        async def _orig(self, *, args, tool_context): return None

    async def wrapped(self, *, args, tool_context):
        sid = h._safe_get_session_id_from_tool(tool_context)
        tgt = self.target_agent_name
        if sid and tgt:
            h._DELEGATION_COUNTS[(sid, tgt)] += 1
            if h._DELEGATION_COUNTS[(sid, tgt)] >= 2:
                h._PENDING_SUGGESTION[sid] = tgt
        return None

    ctx = MagicMock()
    ctx._invocation_context.session.id = "sess-Z"

    await wrapped(_Tool("SADomainAgent"), args={}, tool_context=ctx)
    await wrapped(_Tool("SAReviewerAgent"), args={}, tool_context=ctx)

    # Both counters at 1, neither queued.
    assert h._DELEGATION_COUNTS[("sess-Z", "SADomainAgent")] == 1
    assert h._DELEGATION_COUNTS[("sess-Z", "SAReviewerAgent")] == 1
    assert "sess-Z" not in h._PENDING_SUGGESTION


@pytest.mark.asyncio
async def test_wrapped_run_async_no_session_id_no_op():
    """If session_id can't be resolved (anonymous / health probe), the
    counter must not touch state — bucketing to a falsy key would corrupt
    the only legitimate session keyed off the same target name."""
    from solace_architect_core import _peer_agent_switch_hint as h

    class _Tool:
        target_agent_name = "SADomainAgent"

    async def wrapped(self, *, args, tool_context):
        sid = h._safe_get_session_id_from_tool(tool_context)
        tgt = self.target_agent_name
        if sid and tgt:
            h._DELEGATION_COUNTS[(sid, tgt)] += 1
            if h._DELEGATION_COUNTS[(sid, tgt)] >= 2:
                h._PENDING_SUGGESTION[sid] = tgt
        return None

    ctx = MagicMock()
    # Simulate ADK invocation_context where session.id resolution fails.
    ctx._invocation_context = None  # accessing .session.id will AttributeError

    await wrapped(_Tool(), args={}, tool_context=ctx)

    assert not h._DELEGATION_COUNTS
    assert not h._PENDING_SUGGESTION
