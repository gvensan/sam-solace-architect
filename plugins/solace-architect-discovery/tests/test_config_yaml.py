"""Static checks that the agent's config.yaml is shaped to SAM's apps: contract."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
REQUIRED_BASELINE_TOOLS = {
    # Per v2spec §3.0: baseline tools every SA agent loads.
    "load_preamble",
    "load_jargon_list",
    "record_grounding_gap",
    "record_feedback",
}
DISCOVERY_TOOLS = {
    # Per v2spec §4.2: Discovery-specific tools.
    "load_grounding",
    "fetch_canonical_source",
    "query_integration_hub",
    "parse_intake_document",
    "import_source_context",
    "list_projects",
    "read_artifact",
    "write_artifact",
    "record_open_item",
    "read_open_items",
}


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def test_apps_block_shape(cfg):
    """SAM expects an `apps:` list with one entry pointing at the universal agent app."""
    assert "apps" in cfg, "config.yaml must have an apps: block"
    assert isinstance(cfg["apps"], list) and len(cfg["apps"]) == 1
    app = cfg["apps"][0]
    assert app["app_module"] == "solace_agent_mesh.agent.sac.app", \
        "agent plugins must use SAM's universal SamAgentApp (Decision 83 / SAM convention)"
    assert app["name"] == "sa-discovery-app"


def test_agent_name_and_card(cfg):
    """Agent name + agent_card published for SAM discovery."""
    app_config = cfg["apps"][0]["app_config"]
    assert app_config["agent_name"] == "SADiscoveryAgent"
    card = app_config["agent_card"]
    assert "Refines" in card["description"] or "discovery" in card["description"].lower()
    skill_ids = {s["id"] for s in card["skills"]}
    assert {"refine_intake", "pattern_match", "mi_verify", "brief_synthesis"} <= skill_ids


def test_baseline_tools_present(cfg):
    """§3.0 baseline tools must be in the tool list for every SA agent."""
    tools = cfg["apps"][0]["app_config"]["tools"]
    fn_names = {t["function_name"] for t in tools if t.get("tool_type") == "python"}
    missing = REQUIRED_BASELINE_TOOLS - fn_names
    assert not missing, f"missing baseline tools: {sorted(missing)}"


def test_discovery_specific_tools_present(cfg):
    """§4.2 Discovery-specific tools must be available."""
    tools = cfg["apps"][0]["app_config"]["tools"]
    fn_names = {t["function_name"] for t in tools if t.get("tool_type") == "python"}
    missing = DISCOVERY_TOOLS - fn_names
    assert not missing, f"missing Discovery tools: {sorted(missing)}"


def test_tool_modules_resolve_to_solace_architect_core(cfg):
    """Every tool must come from solace-architect-core — Discovery has no plugin-side tools."""
    tools = cfg["apps"][0]["app_config"]["tools"]
    for t in tools:
        if t.get("tool_type") != "python":
            continue
        mod = t["component_module"]
        assert mod.startswith("solace_architect_core."), \
            f"tool {t['function_name']} comes from {mod!r}; expected solace-architect-core"


def test_instruction_present_and_substantial(cfg):
    """The role-specific system prompt must be inline under instruction:."""
    instr = cfg["apps"][0]["app_config"]["instruction"]
    assert isinstance(instr, str)
    assert len(instr) > 1000, "instruction must contain the role-specific prompt"
    # Decision 83 — agent must call load_preamble() before any other action.
    assert "load_preamble" in instr
    # Decision 84 — agent must NOT silently assume defaults; every assumption logged.
    assert "record_open_item" in instr
