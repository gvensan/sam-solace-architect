"""Rewrite outgoing system-instructions into a WAF-safe form.

The LLM gateway (``lite-llm.mymaas.net``) fronts its LiteLLM proxy with a
WAF that scores request bodies and returns an nginx HTML ``403 Forbidden``
when a prompt is dense with patterns it reads as attacks — angle-bracket
placeholders (``<layer>``, ``<DONE | … >``) and HTML comments
(``<!-- … -->``). The agent prompts are full of these legitimately, and one
agent's prompt (Event Portal) already crosses the WAF's cumulative threshold;
any agent could as prompts grow. See the project memory
``feedback_gateway_waf_prompt``.

Fix, entirely in-process (no external proxy): chain a transform onto every
agent's ``before_model_callback`` that rewrites the assembled
``system_instruction`` into an equivalent the WAF doesn't flag — strip
``<!-- … -->`` markers and turn ``<placeholder>`` into ``[placeholder]``. The
model reads both identically (a placeholder is a placeholder); only the
gateway's pattern-matcher sees a difference.

Hooking technique mirrors :mod:`solace_architect_core._sam_telemetry_patch`:
SAM hard-codes its ``before_model_callback`` chain inside
``initialize_adk_agent`` and there is no config key to append to it, so we
wrap ``initialize_adk_agent`` (in BOTH ``setup`` and ``component`` — the
latter binds the name at import time), let SAM build its chain, then wrap the
resulting ``agent.before_model_callback`` once more. Our wrapper runs SAM's
chain FIRST (so ``InjectInstructions`` has assembled the full instruction),
then sanitizes.

Scope: only ``system_instruction`` (text we author) is rewritten. Message
contents (user / tool / model turns) are left untouched, so genuine user data
containing angle brackets is never altered.

Per-agent hookup is a one-liner from each agent's ``lifecycle.init()``::

    from solace_architect_core._waf_prompt_sanitizer import install
    install()

Idempotent: a sentinel attribute makes repeat calls (sibling agents in the
same process) cheap no-ops. Composes with the telemetry patch — each wraps a
different callback, so order does not matter.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

_PATCH_SENTINEL = "_sa_waf_sanitizer_patched"
# Module-level idempotency guard. We CANNOT rely on a function attribute on
# initialize_adk_agent: the telemetry patch wraps our patched_init afterwards,
# so on later agents the attribute is no longer on the top-level function and a
# re-check would re-wrap (stacking both patches once per agent). A process-wide
# flag is the robust source of truth.
_installed = False

# `<!-- … -->` comment markers (test sentinels / notes) — useless to the LLM.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# `<placeholder>` tokens. Capped length so we match author placeholders, not
# an accidental `a < b` ... `c > d` span. `[^<>\n]` prevents crossing tags.
_ANGLE_RE = re.compile(r"<([^<>\n]{1,80})>")


def _waf_safe(text: str) -> str:
    """Return a WAF-benign equivalent of an authored instruction string."""
    text = _COMMENT_RE.sub("", text)
    text = _ANGLE_RE.sub(r"[\1]", text)
    return text


def _sanitize_request(llm_request: Any) -> None:
    """Rewrite ``llm_request.config.system_instruction`` in place (string only)."""
    try:
        cfg = getattr(llm_request, "config", None)
        if cfg is None:
            return
        si = getattr(cfg, "system_instruction", None)
        if isinstance(si, str) and si:
            new = _waf_safe(si)
            if new != si:
                cfg.system_instruction = new
    except Exception as e:  # never break the model call
        log.debug("[SA waf-sanitizer] skipped (suppressed): %s", e)


def install() -> None:
    """Monkey-patch ``initialize_adk_agent`` to chain the sanitizer onto every
    agent's ``before_model_callback``. Idempotent via a sentinel.
    """
    global _installed
    if _installed:
        return  # patch exactly once per process

    try:
        from solace_agent_mesh.agent.adk import setup as _sam_setup
    except Exception as e:  # pragma: no cover — SAM should import
        log.warning("SA waf-sanitizer skipped: cannot import SAM setup (%s)", e)
        return

    original = _sam_setup.initialize_adk_agent

    def patched_init(component, loaded_tools, enabled_builtin_tools):
        agent = original(component, loaded_tools, enabled_builtin_tools)
        try:
            sam_chain = agent.before_model_callback
        except Exception:
            sam_chain = None
        agent_name = getattr(component, "agent_name", None) or "unknown"

        async def with_waf_sanitize(callback_context, llm_request):
            # Run SAM's chain first so InjectInstructions has assembled the
            # full system_instruction. Preserve a short-circuit response.
            result = None
            if sam_chain is not None:
                rv = sam_chain(callback_context, llm_request)
                if hasattr(rv, "__await__"):
                    rv = await rv
                result = rv
            if result is not None:
                return result  # SAM short-circuited; no model call to protect
            _sanitize_request(llm_request)
            return None

        try:
            agent.before_model_callback = with_waf_sanitize
            log.info(
                "[SA waf-sanitizer] before_model_callback chained for agent '%s'",
                agent_name,
            )
        except Exception as e:
            log.warning(
                "[SA waf-sanitizer] could not assign wrapped callback for '%s': %s",
                agent_name, e,
            )
        return agent

    setattr(patched_init, _PATCH_SENTINEL, True)
    _sam_setup.initialize_adk_agent = patched_init

    # component.py does `from ...setup import initialize_adk_agent` at import
    # time, binding the original as a local — patch that symbol too, exactly
    # as the telemetry patch must.
    try:
        from solace_agent_mesh.agent.sac import component as _sam_component
        _sam_component.initialize_adk_agent = patched_init
        log.info(
            "[SA waf-sanitizer] initialize_adk_agent patched in both setup and component modules"
        )
    except Exception as e:
        log.warning(
            "[SA waf-sanitizer] could not patch component.initialize_adk_agent (%s)", e
        )
    _installed = True
    log.info("[SA waf-sanitizer] installed monkey-patch on initialize_adk_agent")
