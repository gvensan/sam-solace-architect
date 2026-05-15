"""Forbidden term scan across agent system prompts."""

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).parent.parent
PLUGINS = sorted((REPO_ROOT / "plugins").glob("*/config.yaml"))


def _extract_prompt(data: dict) -> str | None:
    """Return the agent's prompt string from either config shape, or None for entrypoints.

    Supports both legacy ``agent.system_prompt`` and SAM ``apps[0].app_config.instruction``.
    """
    if "apps" in data and isinstance(data["apps"], list) and data["apps"]:
        app = data["apps"][0]
        if app.get("app_module", "").endswith("agent.sac.app"):
            return app.get("app_config", {}).get("instruction") or ""
    if "agent" in data:
        return data["agent"].get("system_prompt") or ""
    return None


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_no_forbidden_terms_in_system_prompts(config_path):
    data = yaml.safe_load(config_path.read_text())
    raw = _extract_prompt(data)
    if raw is None:
        pytest.skip("entrypoint plugin")
    prompt = raw.lower()

    # 'connector' must always co-occur with 'micro-integration'
    if "connector" in prompt:
        assert "micro-integration" in prompt, \
            f"{config_path.parent.name}: 'connector' used without 'Micro-Integration'"

    # 'orchestrator agent' (two words, lowercase) is forbidden EXCEPT inside the
    # bracketed forbidden-term rule, marked with explicit sentinel comments:
    #   <!-- TERMINOLOGY-RULE-START --> ... <!-- TERMINOLOGY-RULE-END -->
    if "orchestrator agent" in prompt:
        # Strip out everything between the sentinels (case-insensitive)
        import re
        masked = re.sub(
            r"<!--\s*terminology-rule-start\s*-->.*?<!--\s*terminology-rule-end\s*-->",
            "", prompt, flags=re.DOTALL | re.IGNORECASE,
        )
        if "orchestrator agent" in masked:
            pytest.fail(
                f"{config_path.parent.name}: 'orchestrator agent' used outside the "
                f"<!-- TERMINOLOGY-RULE-START --> ... <!-- TERMINOLOGY-RULE-END --> sentinel "
                f"in the system prompt"
            )


def test_naming_conventions_doc_present():
    doc_path = (REPO_ROOT / "solace-architect-core" / "src" / "solace_architect_core" /
                "grounding" / "naming-conventions.md")
    assert doc_path.exists()
    doc = doc_path.read_text()
    assert "Micro-Integration" in doc
    assert "Direct messaging" in doc
    assert "Guaranteed messaging" in doc
