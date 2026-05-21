"""Deprecated.

The SAM entrypoint contract uses class-based lifecycle (BaseGatewayApp +
BaseGatewayComponent), not standalone init/cleanup hooks. The previous
function-based lifecycle in this module has been superseded by:

- :mod:`solace_architect_webui_entrypoint.app`       — SAM App class
- :mod:`solace_architect_webui_entrypoint.component` — SAM Component class

This module is kept only so that existing imports don't break; new code
should import from .app and .component directly.
"""
