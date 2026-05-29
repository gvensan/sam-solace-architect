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
import time
from typing import Any

log = logging.getLogger(__name__)

# How close together (seconds) two recordings of the same (engagement, agent,
# token counts) fingerprint must be to count as the SAME response double-fired
# rather than two genuine turns. Input-token counts grow turn-over-turn within a
# session, so two real turns sharing a fingerprint inside this window is
# implausible — the window only ever collapses an accidental double-invoke.
_DEDUP_WINDOW_S = 1.5


_HEADER_RE = re.compile(r"\[Active engagement:[^\]]*engagement_id=([^\s,\]]+)")
_USER_HEADER_RE = re.compile(r"\[Active engagement:[^\]]*user_id=([^\s,\]]+)")
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


def _already_recorded(callback_context: Any, llm_response: Any,
                      eid: Any, agent_name: str,
                      in_tok: int, out_tok: int) -> bool:
    """Has this exact LLM response already been recorded this turn?

    SAM occasionally invokes ``after_model_callback`` twice for a single
    ``LlmResponse`` — observed in the ledger as two byte-identical rows whose
    ``ts`` differ by ~1 ms. Left unguarded that double-bills tokens and
    double-renders the activity pills. Two independent guards, either of which
    suppresses the duplicate:

    1. **Object identity** — stamp the response object; if SAM hands us the
       same object twice (the common case), we see the stamp and skip. Zero
       risk: a distinct response is a distinct object.
    2. **Short-window token fingerprint on state** — covers the case where the
       second invoke carries a *copy* of the response. A duplicate is the same
       ``(engagement, agent, input_tokens, output_tokens)`` seen again within
       :data:`_DEDUP_WINDOW_S`. Safe because input-token counts climb every
       turn, so two genuine turns never share a fingerprint this close together.

    Always returns a bool; never raises (telemetry must not break a turn).
    """
    # Guard 1 — object identity.
    try:
        if getattr(llm_response, "_sa_tel_recorded", False):
            return True
        try:
            setattr(llm_response, "_sa_tel_recorded", True)
        except Exception:
            pass  # immutable/slotted response → fall through to guard 2
    except Exception:
        pass

    # Guard 2 — short-window token fingerprint (JSON-safe scalars on state).
    if not (in_tok or out_tok):
        return False
    fp = f"{eid}|{agent_name}|{in_tok}|{out_tok}"
    now = time.monotonic()
    prev_fp = _safe_state_get(callback_context, "_sa_tel_last_fp")
    try:
        prev_t = float(_safe_state_get(callback_context, "_sa_tel_last_t") or 0.0)
    except (TypeError, ValueError):
        prev_t = 0.0
    if prev_fp == fp and 0.0 <= (now - prev_t) < _DEDUP_WINDOW_S:
        return True
    _safe_state_set(callback_context, "_sa_tel_last_fp", fp)
    _safe_state_set(callback_context, "_sa_tel_last_t", now)
    return False


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


def _extract_user_id(callback_context: Any) -> str | None:
    """Resolve the active user_id, fast path then slow path.

    Mirrors :func:`_extract_engagement_id` but for the ``user_id=…`` slice
    of the same ``[Active engagement: ...]`` header. Without this, telemetry
    writes lose the per-user namespace and land in the unscoped storage
    fallback — invisible to the dashboard's Usage view, which reads under
    the authenticated user's namespace.

    Returns ``None`` when the header has no ``user_id=…`` (anonymous /
    dev-bypass mode); the recorder then writes unscoped, matching legacy.
    """
    cached = _safe_state_get(callback_context, "user_id")
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
                m = _USER_HEADER_RE.search(text)
                if m:
                    uid = m.group(1)
                    _safe_state_set(callback_context, "user_id", uid)
                    return uid
    except Exception:
        return None
    return None


# Agent → lifecycle phase, so a telemetry row carries a ``step_id`` even when
# SAM didn't stamp one on state (the common case — these were null before).
_AGENT_STEP = {
    "SADiscoveryAgent": "discovery",
    "SADomainAgent": "design",
    "SAArchitectReviewerAgent": "review",
    "SADeveloperReviewerAgent": "review",
    "SAOpsReviewerAgent": "review",
    "SASecurityReviewerAgent": "review",
    "SAValidationAgent": "validation",
    "SAEventPortalAgent": "event-portal",
    "SABlueprintAgent": "blueprint",
    "SAOrchestratorAgent": "orchestrator",
}


def _resolve_step_id(callback_context: Any, agent_name: str) -> Any:
    """Lifecycle phase for this row. Prefer an explicit state value; else derive
    deterministically from the agent (these were null before — nothing populates
    ``state['step_id']``)."""
    sid = _safe_state_get(callback_context, "step_id")
    if sid:
        return sid
    return _AGENT_STEP.get(agent_name)


def _resolve_task_id(callback_context: Any) -> Any:
    """SAM/A2A task id for this row. Prefer ``state['logical_task_id']``; else
    fall back to the ADK invocation id off the invocation context (these were
    null before — SAM doesn't stamp logical_task_id on state)."""
    tid = _safe_state_get(callback_context, "logical_task_id")
    if tid:
        return tid
    try:
        ic = getattr(callback_context, "_invocation_context", None)
        return getattr(ic, "invocation_id", None) or getattr(ic, "id", None) if ic else None
    except Exception:
        return None


def _resolve_model_name(callback_context: Any, llm_response: Any) -> str:
    """Best-effort model name. Tries multiple sources in order:
      1. callback_context.state["model_name"] — fast path if SAM already
         resolved + cached it for this turn.
      2. llm_response.model — Gemini-style response object attribute.
      3. The agent's configured model — via
         callback_context._invocation_context.agent.model.
         This is what the ADK runner USES to dispatch the LLM call, so
         it's the most authoritative source for "which model billed this
         call?". Critically: this resolves to "openai/vertex-claude-4-5-sonnet"
         (or whatever's configured in config.yaml) even when (1) and (2)
         both return empty — the symptom that filled the ledger with
         ``"model": "unknown"`` before this fix.
      4. Fall back to "unknown" — preserves the legacy behavior for any
         row we genuinely can't attribute.
    """
    name = _safe_state_get(callback_context, "model_name")
    if name:
        return str(name)
    try:
        model = getattr(llm_response, "model", None)
        if model:
            return str(model)
    except Exception:
        pass
    # Source 3: the LlmAgent's own model attribute. ADK's LiteLlm wrapper
    # accepts either a string ("openai/vertex-claude-4-5-sonnet") or a
    # LiteLlm instance whose .model holds the string — handle both.
    try:
        invocation_ctx = getattr(callback_context, "_invocation_context", None)
        agent = getattr(invocation_ctx, "agent", None) if invocation_ctx else None
        agent_model = getattr(agent, "model", None) if agent else None
        if agent_model:
            # LiteLlm instance — unwrap to its model string.
            inner = getattr(agent_model, "model", None)
            if inner:
                return str(inner)
            return str(agent_model)
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

    Also registers our custom-alias model prices with LiteLLM (suppresses
    the "Cost tracking unavailable for model …" warnings that LiteLLM
    emits on every LLM call against an unknown model). See
    :mod:`solace_architect_core._model_prices`.
    """
    # Register model prices first — independent of the monkey-patch, safe to
    # repeat (LiteLLM dedupes registrations), so we run it on every install()
    # call rather than gating on the sentinel.
    try:
        from ._model_prices import register_with_litellm
        register_with_litellm()
    except Exception as exc:
        log.debug("[SA telemetry] model-price registration skipped: %s", exc)

    # Install the WAF prompt sanitizer (separate concern — see
    # _waf_prompt_sanitizer). It rides this install() because this is the one
    # bootstrap entrypoint every agent's lifecycle.init() already calls; the
    # plugins are installed non-editable, so we can't add a new call to their
    # lifecycle without a reinstall. Idempotent and fail-safe — a failure here
    # must never break agent boot.
    try:
        from ._waf_prompt_sanitizer import install as _install_waf_sanitizer
        _install_waf_sanitizer()
    except Exception as exc:
        log.warning("[SA telemetry] WAF prompt-sanitizer install skipped: %s", exc)

    # Install the LLM input-size probe (separate concern — see _llm_input_probe).
    # Rides this install() for the same reason as the WAF sanitizer. Installed
    # AFTER it so the probe wraps outermost and measures the post-sanitize request
    # that actually goes on the wire. Measurement only — never mutates the request.
    try:
        from ._llm_input_probe import install as _install_input_probe
        _install_input_probe()
    except Exception as exc:
        log.warning("[SA telemetry] LLM input-probe install skipped: %s", exc)

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
        from .agent_callbacks import record_llm_call_telemetry, _extract_usage
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

        # Stamp a per-call start time in a before-model hook so the recorder can
        # compute wall-clock latency. Chained here (not in _llm_input_probe) so
        # duration capture is independent of that probe's on/off flag.
        try:
            before_chain = agent.before_model_callback
        except Exception:
            before_chain = None

        async def with_start_stamp(callback_context, llm_request):
            result = None
            if before_chain is not None:
                try:
                    rv = before_chain(callback_context, llm_request)
                    if hasattr(rv, "__await__"):
                        rv = await rv
                    result = rv
                except Exception as e:
                    log.debug("[SA telemetry] before_model chain raised (suppressed): %s", e)
            if result is not None:
                return result  # chain short-circuited → no model call to time
            _safe_state_set(callback_context, "_sa_llm_start_t", time.monotonic())
            return None

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
                uid = _extract_user_id(callback_context)
                step_id = _resolve_step_id(callback_context, agent_name)
                sam_task_id = _resolve_task_id(callback_context)
                model = _resolve_model_name(callback_context, llm_response)
                in_tok, out_tok, _ = _extract_usage(llm_response)
                # Wall-clock since the before-model stamp (this call's latency).
                start_t = _safe_state_get(callback_context, "_sa_llm_start_t")
                duration_ms = None
                if isinstance(start_t, (int, float)):
                    duration_ms = int((time.monotonic() - start_t) * 1000)
                # Suppress SAM's occasional double-fire of this callback for one
                # response (else the ledger double-bills tokens + activity).
                if _already_recorded(callback_context, llm_response, eid,
                                     agent_name, in_tok, out_tok):
                    log.debug("[SA telemetry] duplicate after_model fire suppressed "
                              "(agent=%s in=%s out=%s)", agent_name, in_tok, out_tok)
                else:
                    await record_llm_call_telemetry(
                        llm_response=llm_response,
                        agent=agent_name,
                        engagement_id=eid,
                        step_id=step_id,
                        sam_task_id=sam_task_id,
                        model=model,
                        user_id=uid,
                        duration_ms=duration_ms,
                    )
            except Exception as e:
                log.debug("[SA telemetry] capture failed (suppressed): %s", e)

            return chain_result

        try:
            agent.before_model_callback = with_start_stamp
            agent.after_model_callback = with_telemetry
            log.info(
                "[SA telemetry] before/after_model_callback chained for agent '%s'",
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
