"""SAM App class for solace-architect-webui-entrypoint.

Discovered by SAM via the module-level ``info`` dict (see cli-entrypoint for
the reference pattern). At runtime SAM imports this module, reads ``info``,
instantiates the class named in ``info["class_name"]``, and calls into the
component returned by ``_get_gateway_component_class()``.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List

from solace_agent_mesh.gateway.base.app import BaseGatewayApp
from solace_agent_mesh.gateway.base.component import BaseGatewayComponent
from solace_architect_core.logging_setup import attach_plugin_file_handler

from solace_architect_webui_entrypoint.component import SolaceArchitectWebuiComponent

# Opt-in per-plugin log file (writes ${SA_LOG_DIR}/solace_architect_webui_entrypoint.log
# when SA_LOG_DIR is set; otherwise no-op so other deployments are unaffected).
attach_plugin_file_handler("solace_architect_webui_entrypoint")

log = logging.getLogger(__name__)


# Module-level discovery metadata — SAM reads this when loading the app module.
info = {
    "class_name": "SolaceArchitectWebuiApp",
    "description": (
        "Solace Architect — WebUI entrypoint. Serves the dashboard, intake form, "
        "audience-pack reports, and REST API. Bridges browser/REST traffic to the "
        "SAOrchestratorAgent over A2A."
    ),
}


class SolaceArchitectWebuiApp(BaseGatewayApp):
    """SAM App for the Solace Architect WebUI entrypoint.

    Adds entrypoint-specific config schema params on top of BaseGatewayApp's
    defaults (broker, gateway_id, namespace, artifact_service, etc.).
    """

    SPECIFIC_APP_SCHEMA_PARAMS: List[Dict[str, Any]] = [
        {
            "name": "adapter_config",
            "required": False,
            "type": "object",
            "default": {"port": 8080, "host": "0.0.0.0", "show_status_updates": True},
            "description": (
                "WebUI-specific config: port, host, show_status_updates, "
                "branding_overrides path."
            ),
        },
        {
            "name": "default_agent_name",
            "required": False,
            "type": "string",
            "default": "SAOrchestratorAgent",
            "description": "Default agent to route browser/REST messages to.",
        },
        {
            "name": "system_purpose",
            "required": False,
            "type": "string",
            "default": "",
            "description": "System purpose description forwarded to agents.",
        },
        {
            "name": "response_format",
            "required": False,
            "type": "string",
            "default": "",
            "description": "Response format guidance forwarded to agents.",
        },
        {
            "name": "authorization_service",
            "required": False,
            "type": "object",
            "default": {"type": "none"},
            "description": "Authorization service config (none | oidc).",
        },
    ]

    def __init__(self, app_info: Dict[str, Any], **kwargs):
        # Skip flow init when SAM is starting in a multi-config compound run —
        # users launch the WebUI separately. Mirrors cli-entrypoint's pattern.
        config_files = [f for f in sys.argv[1:] if f.endswith((".yaml", ".yml"))]
        self._skip_initialization = len(config_files) > 1
        super().__init__(app_info=app_info, **kwargs)

    def _initialize_flows(self) -> None:
        if self._skip_initialization:
            log.info(
                "WebUI entrypoint: skipping flow init (multi-config compound run). "
                "Launch it standalone: sam run plugins/solace-architect-webui-entrypoint/config.yaml"
            )
            return
        try:
            super()._initialize_flows()
        except Exception as exc:
            friendly = self._get_friendly_broker_error(exc)
            if friendly:
                print(f"\n  Error: {friendly}\n")
                sys.exit(1)
            raise

    def _get_friendly_broker_error(self, exc: Exception) -> str | None:
        """Extract a user-friendly message from broker-related exceptions.

        Mirrors cli-entrypoint's pattern so users see actionable broker errors
        instead of stack traces.
        """
        messages: list[str] = []
        cur: BaseException | None = exc
        while cur:
            messages.append(str(cur))
            cur = cur.__cause__ or cur.__context__
        full = " ".join(messages)
        broker_url = self.app_info.get("broker", {}).get("broker_url", "unknown")
        gateway_id = self.app_info.get("app_config", {}).get("gateway_id", "unknown")

        if "Max clients exceeded" in full:
            return (
                f"Could not start WebUI entrypoint '{gateway_id}'.\n"
                f"  Another process is already connected to this entrypoint's broker queue.\n\n"
                f"  Fix:\n"
                f"    1. Stop the other process, or\n"
                f"    2. Use a different entrypoint ID: WEBUI_ENTRYPOINT_ID=sa-webui-ep-02 sam run <config>"
            )
        if "Login Failure" in full or "UNAUTHORIZED" in full.upper():
            return (
                f"Broker authentication failed for '{broker_url}'.\n"
                f"  Check SOLACE_BROKER_USERNAME / PASSWORD / VPN in .env."
            )
        if "Unknown Host" in full or "Connection refused" in full.lower():
            return f"Cannot reach broker at '{broker_url}'. Is it running?"
        if "Timed Out" in full or "timed out" in full.lower():
            return f"Connection to broker at '{broker_url}' timed out."
        if "broker connection" in full.lower():
            return f"Could not connect to broker at '{broker_url}'. Details: {messages[-1]}"
        return None

    def _get_gateway_component_class(self) -> type[BaseGatewayComponent]:
        return SolaceArchitectWebuiComponent
