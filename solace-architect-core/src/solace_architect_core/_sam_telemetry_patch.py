"""Install per-engagement LLM token telemetry by monkey-patching SAM.

SAM hard-codes its ``after_model_callback`` chain inside
``solace_agent_mesh.agent.adk.setup.initialize_adk_agent`` and assigns the
chain directly to the freshly-built ``LlmAgent`` (see ``setup.py`` around
the ``final_after_model_wrapper`` block). There is no config key to append
to that chain, and the agent's ``agent_init_function`` lifecycle hook runs
*before* ``initialize_adk_agent`` is called, so it can't reach the agent
object directly.

The narrow window we use: wrap ``initialize_adk_agent`` itself. Call the
original, let SAM install its chain, then read the resulting
``agent.after_model_callback``, wrap it once more with our telemetry
recorder, and assign the wrapper back. From that point on every
per-LLM-call callback runs SAM's chain first and our recorder second.

Per-agent hookup is a one-liner from each agent's ``lifecycle.init()``::

    from solace_architect_core._sam_telemetry_patch import install
    install()

The first call patches; subsequent calls (from sibling agents in the same
process) are no-ops via a sentinel attribute. Agent identity is resolved
inside the wrapper from the host component's ``agent_name`` attribute, so
the same patch serves every agent.

Engagement id is extracted from the ``[Active engagement: engagement_id=…,
user_id=…]`` header the WebUI injects into every user message — the same
header the user_id auto-resolve work already relies on. Cached on
``callback_context.state["engagement_id"]`` after the first scan so
multi-turn invocations don't re-walk the session events.

If the header is absent (system message, health probe, anonymous mode),
``record_llm_call_telemetry`` drops the call silently by design rather
than polluting a default bucket. Telemetry failures NEVER break the model
response chain — every catch in this module logs at debug and continues.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


_HEADER_RE = re.compile(r"\[Active engagement:[^\]]*engagement_id=([^\s,\]]+)")
_PATCH_SENTINEL = "_sa_telemetry_patched"


def _safe_state_get(callback_context: Any, key: str) -> Any:
    """Tolerantly read ``callback_context.state[key]`` regardless of state's type."""
    try:
        state = getattr(callback_context, "state", None)
        if state is None:
            return None
        get = getattr(state, "get", None)
        if callable(get):
            return get(key)
        return state[key]  # type: ignore[index]
    except Exception:
        return None


def _safe_state_set(callback_context: Any, key: str, value: Any) -> None:
    """Tolerantly write ``callback_context.state[key] = value``."""
    try:
        state = getattr(callback_context, "state", None)
        if state is None:
            return
        state[key] = value  # type: ignore[index]
    except Exception:
        pass


def _extract_engagement_id(callback_context: Any) -> str | None:
    """Resolve the active engagement id, fast path then slow path.

    Fast path: ``callback_context.state["engagement_id"]`` if a prior call
    in this invocation already cached it.

    Slow path: scan the ADK session's recorded events in reverse order
    looking for the ``[Active engagement: engagement_id=… ]`` header text
    the WebUI gateway injects into every user message. On hit, cache the
    value on state so subsequent LLM calls in the same invocation skip
    the scan.

    Returns ``None`` if the header isn't found anywhere — the recorder
    interprets that as "no engagement; drop this call".
    """
    cached = _safe_state_get(callback_context, "engagement_id")
    if cached:
        return cached

    try:
        invocation_ctx = getattr(callback_context, "_invocation_context", None)
        session = getattr(invocation_ctx, "session", None) if invocation_ctx else None
        events = getattr(session, "events", None) if session else None
        if not events:
            return None
    except Exception:
        return None

    try:
        for evt in reversed(list(events)):
            content = getattr(evt, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue
            for p in parts:
                text = getattr(p, "text", None)
                if not text or not isinstance(text, str):
                    continue
                m = _HEADER_RE.search(text)
                if m:
                    eid = m.group(1)
                    _safe_state_set(callback_context, "engagement_id", eid)
                    return eid
    except Exception:
        return None
    return None


def _resolve_model_name(callback_context: Any, llm_response: Any) -> str:
    """Best-effort model name. Tries callback state first, then the response."""
    name = _safe_state_get(callback_context, "model_name")
    if name:
        return str(name)
    try:
        model = getattr(llm_response, "model", None)
        if model:
            return str(model)
    except Exception:
        pass
    return "unknown"


def install() -> None:
    """Monkey-patch SAM's ``initialize_adk_agent`` to chain our telemetry
    recorder onto every agent built afterwards.

    Idempotent: a sentinel attribute on the patched function makes repeat
    calls (from sibling agents in the same process) cheap no-ops.

    The wrapper reads ``component.agent_name`` per call, so a single patch
    serves every agent — the "which agent fired this LLM call" attribution
    is resolved at call time, not patch time.
    """
    try:
        from solace_agent_mesh.agent.adk import setup as _sam_setup
    except Exception as e:  # pragma: no cover — SAM should always be importable
        log.warning("SA telemetry patch skipped: cannot import SAM setup (%s)", e)
        return

    if getattr(_sam_setup.initialize_adk_agent, _PATCH_SENTINEL, False):
        return  # already patched in this process

    # Imported here so a missing solace_architect_core install doesn't fail
    # the SAM agent boot — the patch becomes a no-op instead.
    try:
        from .agent_callbacks import record_llm_call_telemetry
    except Exception as e:
        log.warning("SA telemetry patch skipped: cannot import recorder (%s)", e)
        return

    original = _sam_setup.initialize_adk_agent

    def patched_init(component, loaded_tools, enabled_builtin_tools):
        agent = original(component, loaded_tools, enabled_builtin_tools)
        try:
            sam_chain = agent.after_model_callback
        except Exception:
            sam_chain = None

        agent_name = getattr(component, "agent_name", None) or "unknown"

        async def with_telemetry(callback_context, llm_response):
            # 1. Run SAM's chain first — preserves whatever response mutations
            #    it applies (artifact-block processing, max-token auto-continue,
            #    thinking-content stripping, etc.). Handles both sync and async.
            chain_result = None
            if sam_chain is not None:
                try:
                    rv = sam_chain(callback_context, llm_response)
                    if hasattr(rv, "__await__"):
                        rv = await rv
                    chain_result = rv
                except Exception as e:
                    log.exception(
                        "[SA telemetry] SAM after_model chain raised; "
                        "continuing to record telemetry anyway: %s", e,
                    )

            # 2. Record per-LLM-call token usage. Every failure path is
            #    swallowed so a bad telemetry write never breaks the agent.
            try:
                eid = _extract_engagement_id(callback_context)
                step_id = _safe_state_get(callback_context, "step_id")
                sam_task_id = _safe_state_get(callback_context, "logical_task_id")
                model = _resolve_model_name(callback_context, llm_response)
                await record_llm_call_telemetry(
                    llm_response=llm_response,
                    agent=agent_name,
                    engagement_id=eid,
                    step_id=step_id,
                    sam_task_id=sam_task_id,
                    model=model,
                )
            except Exception as e:
                log.debug("[SA telemetry] capture failed (suppressed): %s", e)

            return chain_result

        try:
            agent.after_model_callback = with_telemetry
            log.info(
                "[SA telemetry] after_model_callback chained for agent '%s'",
                agent_name,
            )
        except Exception as e:
            log.warning(
                "[SA telemetry] could not assign wrapped callback to agent '%s': %s",
                agent_name, e,
            )
        return agent

    setattr(patched_init, _PATCH_SENTINEL, True)
    _sam_setup.initialize_adk_agent = patched_init

    # The consumer module `solace_agent_mesh.agent.sac.component` does
    # `from solace_agent_mesh.agent.adk.setup import initialize_adk_agent`
    # at import time — that binds the ORIGINAL function as a local name,
    # so the call site at component.py:3619 ignores our monkey-patch of
    # setup.initialize_adk_agent unless we ALSO replace the bound symbol
    # in the consumer module. Without this second patch the wrapper was
    # silently installed but never reached → after_model_callback chain
    # never ran → llm-calls.jsonl stays empty → Usage view shows zero
    # tokens even after the agents have been running for an hour.
    try:
        from solace_agent_mesh.agent.sac import component as _sam_component
        _sam_component.initialize_adk_agent = patched_init
        log.info("[SA telemetry] initialize_adk_agent patched in both setup and component modules")
    except Exception as e:
        log.warning(
            "[SA telemetry] could not patch component.initialize_adk_agent (%s) — "
            "telemetry may not capture LLM calls",
            e,
        )
    log.info("[SA telemetry] installed monkey-patch on initialize_adk_agent")
