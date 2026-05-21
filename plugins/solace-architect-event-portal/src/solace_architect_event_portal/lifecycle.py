"""Plugin init / cleanup for SAEventPortalAgent.

Two responsibilities:
1. Provide hooks for SAM's ``agent_init_function`` / ``agent_cleanup_function``
   config keys. Wiring those in config.yaml forces SAM to import the plugin
   package, which in turn triggers ``__init__.py`` and activates the
   per-plugin log handler.
2. Install the SA after_model_callback telemetry patch (idempotent — see
   solace_architect_core._sam_telemetry_patch).

These functions are deliberately plain ``def`` (not ``async def``) because
SAM calls ``init_function(self)`` synchronously at component.py:446
without awaiting — async hooks return an unawaited coroutine and the
body never runs (we hit this before; see the project-wide async→sync
sweep). Telemetry would silently miss every LLM call.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def init(*args, **kwargs):
    """Plugin init hook — runs once when SAM starts the agent."""
    from solace_architect_core._sam_telemetry_patch import install as _install_telemetry_patch
    from solace_architect_core._mcp_schema_guard import install as _install_mcp_schema_guard

    _install_telemetry_patch()
    # MCP schema guard: the EP Designer MCP server occasionally registers
    # tools whose JSON Schema crashes google-adk's _to_gemini_schema
    # converter ("'NoneType' object is not subscriptable"). Without this
    # guard, ONE bad MCP tool aborts the entire LLM call — every chat
    # to SAEventPortalAgent fails with "An unexpected error occurred…",
    # even for questions that wouldn't have needed MCP at all. The guard
    # catches the per-tool conversion error, logs the offender, and
    # omits just that tool from the LLM request. Everything else keeps
    # working.
    _install_mcp_schema_guard()
    log.info(
        "SAEventPortalAgent lifecycle.init() — plugin package imported, "
        "telemetry patch installed, MCP schema guard installed"
    )
    return None


def cleanup(*args, **kwargs):
    """Plugin cleanup hook — runs once on agent shutdown."""
    log.info("SAEventPortalAgent lifecycle.cleanup()")
    return None
