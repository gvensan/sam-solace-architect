"""YAML validity + required fields across all plugin config.yamls."""

import importlib
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).parent.parent
PLUGINS = sorted((REPO_ROOT / "plugins").glob("*/config.yaml"))


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_config_parses_as_yaml(config_path):
    assert yaml.safe_load(config_path.read_text())


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_config_has_required_top_level(config_path):
    """Config must use one of two top-level shapes:
    - ``apps:`` block (SAM's correct format — required for `sam run` to load the plugin)
    - ``agent:`` block (legacy local-tooling format — works for our tests but NOT for `sam run`)

    The 10 agent plugins are pending refactor to the SAM-standard ``apps:`` format
    (the WebUI entrypoint already uses it). Until then, both shapes are accepted here.
    """
    data = yaml.safe_load(config_path.read_text())
    assert "apps" in data or "agent" in data or "entrypoint" in data, \
        f"{config_path.parent.name}: must have 'apps' (SAM-standard) or 'agent' (legacy) top-level key"


def _agent_block(data: dict) -> dict | None:
    """Return the agent definition (name/agent_card/tools) from either config shape.

    SAM ``apps:`` block puts agent metadata under ``apps[0].app_config``;
    legacy local format uses a top-level ``agent:`` mapping. Returns None for
    entrypoints (no agent metadata).
    """
    if "apps" in data and isinstance(data["apps"], list) and data["apps"]:
        app = data["apps"][0]
        if app.get("app_module", "").endswith("agent.sac.app"):
            ac = app.get("app_config", {})
            return {
                "name": ac.get("agent_name"),
                "agent_card": ac.get("agent_card", {}),
                "tools": ac.get("tools", []),
            }
    if "agent" in data:
        return data["agent"]
    return None


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_agent_config_has_name_and_skills(config_path):
    data = yaml.safe_load(config_path.read_text())
    agent = _agent_block(data)
    if agent is None:
        pytest.skip("entrypoint plugin")
    assert agent.get("name"), f"{config_path.parent.name}: agent name missing"
    assert agent.get("agent_card", {}).get("skills"), \
        f"{config_path.parent.name}: agent_card.skills missing"


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_tool_references_resolve(config_path):
    """Every component_module + function_name must point to a real function."""
    data = yaml.safe_load(config_path.read_text())
    agent = _agent_block(data)
    if agent is None:
        pytest.skip("entrypoint plugin (no tool list)")
    for tool in (agent.get("tools") or []):
        if tool.get("tool_type") != "python":
            continue
        mod_name = tool["component_module"]
        fn_name = tool["function_name"]
        module = importlib.import_module(mod_name)
        assert hasattr(module, fn_name), f"{mod_name}.{fn_name} missing"


def test_all_11_plugin_configs_present():
    """All 11 SA plugins are present + named consistently.

    Count history:
      - 11 originally
      - 12 when SAEventPortalAgent was added alongside SAEPProvisioningAgent
      - 11 again after Path A consolidation absorbed SAEPProvisioningAgent
        into SAEventPortalAgent (the MCP-backed agent now owns both the
        ad-hoc EP queries and the live provisioning lifecycle phase).

    If the count changes again, update this list AND the lifecycle banner
    + PHASE_NEXT in the WebUI's app.js.
    """
    expected = {
        "solace-architect-orchestrator", "solace-architect-discovery",
        "solace-architect-domain",
        "solace-architect-reviewer-architect", "solace-architect-reviewer-developer",
        "solace-architect-reviewer-ops", "solace-architect-reviewer-security",
        "solace-architect-validation", "solace-architect-event-portal",
        "solace-architect-blueprint",
        "solace-architect-webui-entrypoint",
    }
    actual = {p.parent.name for p in PLUGINS}
    assert actual == expected, f"missing or extra plugins: {actual ^ expected}"
