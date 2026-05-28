"""Measure the *composition* of every outgoing LLM request (instrumentation).

The telemetry ledger already records the **total** input-token count per call
(``prompt_token_count``, tagged by engagement/step — see
:mod:`solace_architect_core.agent_callbacks`). That tells us *how big* a step's
prompts are, but not *where the bytes come from*. The integration step fails
repeatedly under the 30s read-timeout (see project memory
``project_integration_scope_and_fetch_cache``); the open question before we
tighten tool-return sizes / offload to artifacts (SAM's "keep each call's input
small" pattern) is which slice dominates:

  - the authored ``system_instruction`` (grounding + preamble we inject), vs.
  - ``function_response`` parts (tool/artifact/grounding reads handed back to
    the model — the slice an artifact-offload cap would actually shrink), vs.
  - accumulated conversation history (which compaction, not capping, handles).

This probe logs that breakdown once per LLM call so we can grep ``sam.log`` and
decide on evidence. It is deliberately *measurement only* — it never mutates the
request — and is removable in one place once the #2 decision is made.

Hooking mirrors :mod:`solace_architect_core._waf_prompt_sanitizer`: wrap
``initialize_adk_agent`` (in both ``setup`` and ``component``), let SAM assemble
its ``before_model_callback`` chain, then wrap the result once more. We run the
inner chain FIRST so the measurement reflects the fully-assembled (and
WAF-sanitized) request that actually goes on the wire.

Disable without a code change via ``SA_LLM_INPUT_PROBE=0``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_installed = False


def _enabled() -> bool:
    return os.environ.get("SA_LLM_INPUT_PROBE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _safe_state_get(callback_context: Any, key: str) -> Any:
    """Read ``callback_context.state[key]`` without ever raising."""
    try:
        state = getattr(callback_context, "state", None)
        if state is None:
            return None
        return state.get(key)
    except Exception:
        return None


def _part_size(part: Any) -> tuple[str, int]:
    """Return ``(kind, char_count)`` for one ADK content Part.

    Buckets a part by the field it carries. ``function_response`` is the slice an
    artifact-offload cap would shrink, so it gets its own kind rather than being
    lumped with text.
    """
    try:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            return "text", len(text)

        fr = getattr(part, "function_response", None)
        if fr is not None:
            resp = getattr(fr, "response", fr)
            return "function_response", len(_stringify(resp))

        fc = getattr(part, "function_call", None)
        if fc is not None:
            args = getattr(fc, "args", fc)
            return "function_call", len(_stringify(args))

        inline = getattr(part, "inline_data", None)
        if inline is not None:
            data = getattr(inline, "data", b"") or b""
            return "inline_data", len(data)
    except Exception:
        pass
    return "other", 0


def _stringify(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return str(obj)


def _measure(callback_context: Any, llm_request: Any, agent_name: str) -> None:
    """Log a one-line composition breakdown for the assembled request.

    Fail-safe: any error is swallowed (this is instrumentation, never load-bearing).
    """
    try:
        # system_instruction
        sys_chars = 0
        cfg = getattr(llm_request, "config", None)
        si = getattr(cfg, "system_instruction", None) if cfg is not None else None
        if isinstance(si, str):
            sys_chars = len(si)

        # contents, bucketed by role and by part-kind
        contents = getattr(llm_request, "contents", None) or []
        by_role: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        part_count = 0
        largest = ("", "", 0)  # (role, kind, chars)
        contents_chars = 0
        for content in contents:
            role = str(getattr(content, "role", "?") or "?")
            for part in getattr(content, "parts", None) or []:
                part_count += 1
                kind, size = _part_size(part)
                contents_chars += size
                by_role[role] = by_role.get(role, 0) + size
                by_kind[kind] = by_kind.get(kind, 0) + size
                if size > largest[2]:
                    largest = (role, kind, size)

        total = sys_chars + contents_chars
        engagement = _safe_state_get(callback_context, "engagement_id")
        step = _safe_state_get(callback_context, "step_id")

        log.info(
            "[SA input-probe] agent=%s engagement=%s step=%s "
            "total=%dc (~%dtok) sys=%dc contents=%dc parts=%d "
            "by_kind=%s by_role=%s largest=%s/%s:%dc",
            agent_name,
            engagement,
            step,
            total,
            total // 4,  # rough; ledger has the exact prompt_token_count
            sys_chars,
            contents_chars,
            part_count,
            _stringify(by_kind),
            _stringify(by_role),
            largest[0] or "-",
            largest[1] or "-",
            largest[2],
        )
    except Exception as e:  # never break the model call
        log.debug("[SA input-probe] skipped (suppressed): %s", e)


def install() -> None:
    """Chain the probe onto every agent's ``before_model_callback``.

    Idempotent via a module-level flag (a function attribute is unreliable —
    sibling patches re-wrap ``initialize_adk_agent``; see the note in
    :mod:`solace_architect_core._waf_prompt_sanitizer`).
    """
    global _installed
    if _installed:
        return
    if not _enabled():
        log.info("[SA input-probe] disabled via SA_LLM_INPUT_PROBE")
        _installed = True
        return

    try:
        from solace_agent_mesh.agent.adk import setup as _sam_setup
    except Exception as e:  # pragma: no cover — SAM should import
        log.warning("[SA input-probe] skipped: cannot import SAM setup (%s)", e)
        return

    original = _sam_setup.initialize_adk_agent

    def patched_init(component, loaded_tools, enabled_builtin_tools):
        agent = original(component, loaded_tools, enabled_builtin_tools)
        try:
            inner_chain = agent.before_model_callback
        except Exception:
            inner_chain = None
        agent_name = getattr(component, "agent_name", None) or "unknown"

        async def with_input_probe(callback_context, llm_request):
            # Run the existing chain first so system_instruction is fully
            # assembled (and WAF-sanitized) before we measure. Preserve any
            # short-circuit response untouched.
            result = None
            if inner_chain is not None:
                rv = inner_chain(callback_context, llm_request)
                if hasattr(rv, "__await__"):
                    rv = await rv
                result = rv
            if result is not None:
                return result  # chain short-circuited; no model call to measure
            _measure(callback_context, llm_request, agent_name)
            return None

        try:
            agent.before_model_callback = with_input_probe
        except Exception as e:
            log.warning(
                "[SA input-probe] could not assign wrapped callback for '%s': %s",
                agent_name, e,
            )
        return agent

    _sam_setup.initialize_adk_agent = patched_init
    try:
        from solace_agent_mesh.agent.sac import component as _sam_component
        _sam_component.initialize_adk_agent = patched_init
    except Exception as e:
        log.warning(
            "[SA input-probe] could not patch component.initialize_adk_agent (%s)", e
        )
    _installed = True
    log.info("[SA input-probe] installed monkey-patch on initialize_adk_agent")
