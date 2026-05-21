"""Plugin-discovery contract.

SAM imports the app module and reads the module-level ``info`` dict to find
the App class. This test fails fast if that contract drifts.
"""

import importlib
import pytest


def test_app_module_imports():
    """SAM must be able to import the app module."""
    pytest.importorskip("solace_agent_mesh.gateway.base.app",
                        reason="solace-agent-mesh not installed in test env")
    mod = importlib.import_module("solace_architect_webui_entrypoint.app")
    assert mod is not None


def test_info_dict_present_and_valid():
    pytest.importorskip("solace_agent_mesh.gateway.base.app")
    mod = importlib.import_module("solace_architect_webui_entrypoint.app")
    assert isinstance(mod.info, dict)
    assert mod.info["class_name"] == "SolaceArchitectWebuiApp"
    assert "description" in mod.info and len(mod.info["description"]) > 20


def test_app_class_named_in_info_exists():
    pytest.importorskip("solace_agent_mesh.gateway.base.app")
    mod = importlib.import_module("solace_architect_webui_entrypoint.app")
    cls = getattr(mod, mod.info["class_name"])
    assert callable(cls)


def test_app_class_inherits_base_gateway_app():
    pytest.importorskip("solace_agent_mesh.gateway.base.app")
    from solace_agent_mesh.gateway.base.app import BaseGatewayApp
    from solace_architect_webui_entrypoint.app import SolaceArchitectWebuiApp
    assert issubclass(SolaceArchitectWebuiApp, BaseGatewayApp)


def test_app_declares_required_schema_params():
    pytest.importorskip("solace_agent_mesh.gateway.base.app")
    from solace_architect_webui_entrypoint.app import SolaceArchitectWebuiApp
    names = {p["name"] for p in SolaceArchitectWebuiApp.SPECIFIC_APP_SCHEMA_PARAMS}
    # Every entrypoint must declare these per cli-entrypoint precedent
    for required in ("adapter_config", "default_agent_name", "authorization_service"):
        assert required in names, f"missing schema param: {required}"


def test_app_returns_component_class():
    """_get_gateway_component_class must return the Component class itself, not None."""
    pytest.importorskip("solace_agent_mesh.gateway.base.app")
    from solace_agent_mesh.gateway.base.component import BaseGatewayComponent
    from solace_architect_webui_entrypoint.app import SolaceArchitectWebuiApp

    # We can't fully instantiate the App without SAM's runtime, but we can call
    # the method against a minimal stub by bypassing __init__.
    inst = SolaceArchitectWebuiApp.__new__(SolaceArchitectWebuiApp)
    cls = inst._get_gateway_component_class()
    assert issubclass(cls, BaseGatewayComponent)


def test_component_exposes_cancel_task_and_chat_cancel_handler():
    """The STOP-button feature requires both a high-level cancel_task()
    method (publishes the tasks/cancel A2A request) and the matching
    /api/chat/cancel HTTP handler (_chat_cancel). Lock in their presence
    so a refactor can't silently break the STOP button.
    """
    pytest.importorskip("solace_agent_mesh.gateway.base.component")
    from solace_architect_webui_entrypoint.component import SolaceArchitectWebuiComponent
    import inspect

    assert hasattr(SolaceArchitectWebuiComponent, "cancel_task"), "cancel_task method missing"
    assert hasattr(SolaceArchitectWebuiComponent, "_chat_cancel"), "_chat_cancel handler missing"
    # Signatures: cancel_task(self, task_id) and _chat_cancel(self, request).
    ct_sig = inspect.signature(SolaceArchitectWebuiComponent.cancel_task)
    assert "task_id" in ct_sig.parameters
    cc_sig = inspect.signature(SolaceArchitectWebuiComponent._chat_cancel)
    assert "request" in cc_sig.parameters


def test_component_source_registers_cancel_route():
    """Smoke-check that the route table registers /api/chat/cancel — the
    actual handler binding happens inside _start_http() which we can't
    invoke without a running event loop. Reading the source is good enough
    to catch the wiring regressing."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "src" / "solace_architect_webui_entrypoint" / "component.py"
    body = src.read_text()
    assert "/api/chat/cancel" in body, "cancel route not registered in component.py"
    assert "self._chat_cancel" in body, "_chat_cancel handler not bound to route"
