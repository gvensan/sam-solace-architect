"""Deterministic agent-switch suggestion for the orchestrator's chat dropdown.

When SAOrchestratorAgent delegates to the same peer agent twice or more in
the same gateway session, this guard appends a fenced ``switch_agent``
block to the orchestrator's final text response. The WebUI frontend parses
that block, suppresses it from the rendered message, and renders a "Switch
to <agent>" chip — clicking it re-targets the chat dropdown to the peer so
follow-up edits skip the orchestration round-trip.

Why deterministic (not LLM-prompted)? LLMs forget, hedge, or hallucinate
switch suggestions even when no delegation happened. By hooking
``PeerAgentTool.run_async`` we know with certainty when a delegation
was *attempted*, to which target, and at what session-cumulative count.
(We count attempts rather than successes — the user's iterative-edit
intent is the same whether the peer responded DONE or BLOCKED.)

Why "2nd+ delegation" and not "1st"? A single delegation might be a
one-shot Q&A — suggesting switch then would strand the user on a
phase-specific agent when their next question is about a different phase.
Waiting for the SECOND delegation to the same target is a clean signal
of "user is iterating on this phase; switching helps".

Memory note: ``_DELEGATION_COUNTS`` and ``_PENDING_SUGGESTION`` grow with
the set of unique (session, target) pairs the process has seen. Each
entry is small (~100 bytes), so a SAM process serving thousands of
sessions accumulates ~100KB. Acceptable for the current workload. If
that ever becomes a concern, add LRU eviction keyed on session_id —
sessions go cold quickly once the user closes the dashboard.

Install per-agent from ``lifecycle.init()`` — typically only the
orchestrator needs it; downstream agents are already specialized::

    from solace_architect_core._peer_agent_switch_hint import install
    install()

Same monkey-patch pattern as ``_sam_telemetry_patch`` and
``_mcp_schema_guard`` — idempotent via sentinel attributes, both patches
can coexist on the same agent because they wrap ``initialize_adk_agent``
with distinct sentinels.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger(__name__)


_SENTINEL_RUN = "_sa_switch_hint_run_patched"
_SENTINEL_INIT = "_sa_switch_hint_init_patched"

# Process-local delegation counter. Key: (session_id, target_agent_name).
# The state lives in-process; a SAM restart resets all counts. That's the
# correct behavior — a new process means a new conversation horizon for
# the user, so we re-evaluate whether a switch suggestion is warranted.
_DELEGATION_COUNTS: dict[tuple[str, str], int] = defaultdict(int)

# session_id -> target_agent_name awaiting injection into the next final
# text response from the orchestrator. Cleared after injection so repeat
# call-backs in the same response don't double-append.
_PENDING_SUGGESTION: dict[str, str] = {}


def _safe_get_session_id_from_tool(tool_context: Any) -> str | None:
    try:
        return tool_context._invocation_context.session.id  # type: ignore[union-attr]
    except Exception:
        return None


def _safe_get_session_id_from_callback(callback_context: Any) -> str | None:
    try:
        return callback_context._invocation_context.session.id  # type: ignore[union-attr]
    except Exception:
        return None


def _patch_peer_agent_tool() -> None:
    """Wrap ``PeerAgentTool.run_async`` to count delegations per session."""
    try:
        from solace_agent_mesh.agent.tools.peer_agent_tool import PeerAgentTool
    except ImportError as exc:
        log.warning("[switch_hint] PeerAgentTool not importable; skipping: %s", exc)
        return

    if getattr(PeerAgentTool.run_async, _SENTINEL_RUN, False):
        return

    original = PeerAgentTool.run_async

    async def wrapped_run_async(self, *, args, tool_context):
        # Update the counter BEFORE delegating. Even if the delegation
        # raises, the count moves — the user attempted to use this target
        # twice, that's the signal we care about.
        try:
            session_id = _safe_get_session_id_from_tool(tool_context)
            target = self.target_agent_name
            if session_id and target:
                key = (session_id, target)
                _DELEGATION_COUNTS[key] += 1
                count = _DELEGATION_COUNTS[key]
                if count >= 2:
                    _PENDING_SUGGESTION[session_id] = target
                    log.info(
                        "[switch_hint] session=%s target=%s count=%d -> queued suggestion",
                        session_id, target, count,
                    )
                else:
                    log.debug(
                        "[switch_hint] session=%s target=%s count=%d (no hint yet)",
                        session_id, target, count,
                    )
        except Exception as exc:
            log.debug("[switch_hint] counter update suppressed: %s", exc)
        return await original(self, args=args, tool_context=tool_context)

    setattr(wrapped_run_async, _SENTINEL_RUN, True)
    PeerAgentTool.run_async = wrapped_run_async  # type: ignore[method-assign]
    log.info("[switch_hint] PeerAgentTool.run_async wrapped")


def _patch_initialize_adk_agent() -> None:
    """Chain a switch-hint injector onto every agent's after_model_callback."""
    try:
        from solace_agent_mesh.agent.adk import setup as _sam_setup
        from solace_agent_mesh.agent.sac import component as _sam_component
    except ImportError as exc:
        log.warning("[switch_hint] SAM import failed: %s", exc)
        return

    if getattr(_sam_setup.initialize_adk_agent, _SENTINEL_INIT, False):
        return

    original_init = _sam_setup.initialize_adk_agent

    def patched_init(component, loaded_tools, enabled_builtin_tools):
        agent = original_init(component, loaded_tools, enabled_builtin_tools)
        # Whatever after_model_callback is here (could be SAM's chain,
        # could be telemetry-wrapped if that patch is also installed) —
        # we chain on top of it. Distinct sentinel so this is independent
        # of the telemetry patch's wrapping.
        existing = getattr(agent, "after_model_callback", None)
        agent_name = getattr(component, "agent_name", None) or "unknown"

        async def with_switch_hint(callback_context, llm_response):
            chain_result = None
            if existing is not None:
                try:
                    rv = existing(callback_context, llm_response)
                    if hasattr(rv, "__await__"):
                        rv = await rv
                    chain_result = rv
                except Exception as exc:
                    log.debug(
                        "[switch_hint] inner chain raised; continuing: %s",
                        exc,
                    )
            try:
                _maybe_inject_switch_block(callback_context, llm_response)
            except Exception as exc:
                log.debug("[switch_hint] inject suppressed: %s", exc)
            return chain_result

        try:
            agent.after_model_callback = with_switch_hint
            log.info(
                "[switch_hint] after_model_callback chained for agent '%s'",
                agent_name,
            )
        except Exception as exc:
            log.warning(
                "[switch_hint] could not assign callback for '%s': %s",
                agent_name, exc,
            )
        return agent

    setattr(patched_init, _SENTINEL_INIT, True)
    _sam_setup.initialize_adk_agent = patched_init
    # Mirror to the consumer-side binding — see _sam_telemetry_patch.py
    # for the full rationale on why this second assignment is required.
    try:
        _sam_component.initialize_adk_agent = patched_init
    except Exception as exc:
        log.warning("[switch_hint] could not patch component init: %s", exc)
    log.info("[switch_hint] initialize_adk_agent chain installed")


def _maybe_inject_switch_block(callback_context: Any, llm_response: Any) -> None:
    """Append a fenced ``switch_agent`` block to a final text response.

    Only fires when:
      1. A pending suggestion is queued for this session
         (set by ``wrapped_run_async`` on count >= 2).
      2. The response is "final" — has text content and no function_calls.
         Mid-turn responses with pending tool calls are not the right
         place for a UI chip; the user wouldn't see it until the turn
         actually finishes.
      3. The block isn't already present (idempotent against double
         callbacks in the same response).
    """
    session_id = _safe_get_session_id_from_callback(callback_context)
    if not session_id:
        return
    target = _PENDING_SUGGESTION.get(session_id)
    if not target:
        return

    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) if content else None
    if not parts:
        return

    has_function_call = any(
        getattr(p, "function_call", None) is not None for p in parts
    )
    if has_function_call:
        return  # mid-turn — wait for the final synthesis

    text_part = None
    for p in parts:
        if getattr(p, "text", None) is not None:
            text_part = p
            break
    if text_part is None:
        return  # no text to attach to; skip rather than fabricate a part

    existing_text = text_part.text or ""
    if "```switch_agent" in existing_text:
        return  # idempotent — already injected on a prior callback for this response

    block = _build_switch_block(target)
    text_part.text = existing_text.rstrip() + "\n\n" + block

    _PENDING_SUGGESTION.pop(session_id, None)
    log.info(
        "[switch_hint] injected switch_agent block for session=%s target=%s",
        session_id, target,
    )


def _build_switch_block(target: str) -> str:
    payload = {
        "to_agent": target,
        "reason": (
            f"You've delegated to {target} more than once this session. "
            f"Switching the chat agent to {target} lets follow-up requests "
            f"skip the orchestrator round-trip."
        ),
    }
    return "```switch_agent\n" + json.dumps(payload, indent=2) + "\n```"


def install() -> None:
    """Install both monkey-patches. Idempotent across repeat calls."""
    _patch_peer_agent_tool()
    _patch_initialize_adk_agent()


__all__ = ["install"]
