"""Plugin init / cleanup for SABlueprintAgent.

Two purposes:
1. Provide hooks for SAM's ``agent_init_function`` / ``agent_cleanup_function``
   config keys. Wiring those in config.yaml forces SAM to import the plugin
   package, which in turn triggers ``__init__.py`` and activates the
   per-plugin log handler.
2. Install the SA after_model_callback telemetry patch (idempotent — see
   solace_architect_core._sam_telemetry_patch).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def init(*args, **kwargs):
    """Plugin init hook — runs once when SAM starts the agent.

    Two responsibilities beyond importing the package:
      1. Install the SA after_model_callback telemetry patch.
      2. Register this plugin's HTML/PDF renderer with the core's
         blueprint_tools dispatcher, so render_audience_pack() can
         delegate to it. Without this, every /exports/render call
         (and the agent's render_audience_pack tool calls) return
         ``ok=False, error="no renderer registered"`` — which then
         hits the WebUI as ``null`` and crashes the View-pack click
         handler at ``app.js __renderPack`` with
         ``Cannot read properties of null (reading 'paths')``.
    """
    from solace_architect_core._sam_telemetry_patch import install as _install_telemetry_patch
    from solace_architect_core.tools.blueprint_tools import register_renderer
    from solace_architect_blueprint.report_generator import render_pack

    _install_telemetry_patch()
    register_renderer(render_pack)
    log.info("SABlueprintAgent lifecycle.init() — telemetry patch + audience-pack renderer registered")
    return None


def cleanup(*args, **kwargs):
    """Plugin cleanup hook — runs once on agent shutdown."""
    log.info("SABlueprintAgent lifecycle.cleanup()")
    return None
