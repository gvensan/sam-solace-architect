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
