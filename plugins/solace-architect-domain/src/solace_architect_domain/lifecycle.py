"""Plugin init / cleanup for SADomainAgent.

Two purposes:
1. Provide hooks for SAM's ``agent_init_function`` / ``agent_cleanup_function``
   config keys. Wiring those in config.yaml forces SAM to import the plugin
   package, which in turn triggers ``__init__.py`` and activates the
   per-plugin log handler from ``solace_architect_core.logging_setup``.
2. Phase 1+: warm caches, validate grounding sources, register Decision-84
   telemetry callbacks once SAM exposes a config hook for them.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def init(*args, **kwargs):
    """Plugin init hook — runs once when SAM starts the agent.

    Also installs the SA after_model_callback telemetry patch
    (idempotent — see solace_architect_core._sam_telemetry_patch).
    """
    from solace_architect_core._sam_telemetry_patch import install as _install_telemetry_patch

    _install_telemetry_patch()
    log.info(
        "SADomainAgent lifecycle.init() — plugin package imported, "
        "telemetry patch installed"
    )
    return None


def cleanup(*args, **kwargs):
    """Plugin cleanup hook — runs once on agent shutdown."""
    log.info("SADomainAgent lifecycle.cleanup()")
    return None
