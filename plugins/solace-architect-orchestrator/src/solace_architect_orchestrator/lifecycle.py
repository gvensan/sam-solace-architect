"""Plugin init / cleanup for SAOrchestratorAgent.

Three purposes:
1. Provide hooks for SAM's ``agent_init_function`` / ``agent_cleanup_function``
   config keys. Wiring those in config.yaml forces SAM to import the plugin
   package, which in turn triggers ``__init__.py`` and activates the
   per-plugin log handler.
2. Install the SA after_model_callback telemetry patch (idempotent — see
   solace_architect_core._sam_telemetry_patch).
3. Install the peer-agent switch-hint patch (idempotent — see
   solace_architect_core._peer_agent_switch_hint). Only the orchestrator
   wires this on; downstream agents are already specialized and don't
   benefit from "switch the dropdown" suggestions.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def init(*args, **kwargs):
    """Plugin init hook — runs once when SAM starts the agent."""
    from solace_architect_core._sam_telemetry_patch import install as _install_telemetry_patch
    from solace_architect_core._peer_agent_switch_hint import install as _install_switch_hint

    _install_telemetry_patch()
    _install_switch_hint()
    log.info(
        "SAOrchestratorAgent lifecycle.init() — plugin package imported, "
        "telemetry patch + peer-agent switch-hint installed"
    )
    return None


def cleanup(*args, **kwargs):
    """Plugin cleanup hook — runs once on agent shutdown."""
    log.info("SAOrchestratorAgent lifecycle.cleanup()")
    return None
