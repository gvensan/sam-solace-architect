"""Per-agent prompt size ceilings (v2spec §7.3).

Each agent's system_prompt ≤ 40K tokens; total across all agents ≤ 200K.
Token count is approximated as ``len(text) / 4`` (a common rule-of-thumb)
to avoid pulling in tiktoken as a test dep.
"""

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).parent.parent
PLUGINS = sorted((REPO_ROOT / "plugins").glob("*/config.yaml"))


def _approx_tokens(text: str) -> int:
    """Cheap heuristic: ~4 chars/token. Within ±20% of tiktoken for English prompts."""
    return len(text) // 4


PER_AGENT_BUDGET = 40_000
TOTAL_BUDGET = 200_000


def _extract_prompt(data: dict) -> str | None:
    """Return the agent's prompt string from either config shape, or None for entrypoints.

    Supports both:
    - Legacy ``agent.system_prompt`` (V1-style agent block, pre-SAM contract).
    - SAM ``apps:`` block with ``app_config.instruction`` (current).

    Returns None when the file has neither (i.e., an entrypoint plugin that
    isn't an agent at all). Skip those at the test level.
    """
    if "apps" in data and isinstance(data["apps"], list) and data["apps"]:
        app = data["apps"][0]
        if app.get("app_module", "").endswith("agent.sac.app"):
            return app.get("app_config", {}).get("instruction") or ""
    if "agent" in data:
        return data["agent"].get("system_prompt") or ""
    return None


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_per_agent_system_prompt_under_budget(config_path):
    data = yaml.safe_load(config_path.read_text())
    prompt = _extract_prompt(data)
    if prompt is None:
        pytest.skip("entrypoint plugin")
    tokens = _approx_tokens(prompt)
    assert tokens <= PER_AGENT_BUDGET, \
        f"{config_path.parent.name}: system_prompt is ~{tokens} tokens (limit {PER_AGENT_BUDGET})"


def test_total_agent_prompt_budget():
    total = 0
    for config_path in PLUGINS:
        data = yaml.safe_load(config_path.read_text())
        prompt = _extract_prompt(data)
        if prompt is None:
            continue
        total += _approx_tokens(prompt)
    assert total <= TOTAL_BUDGET, \
        f"total prompt size ~{total} tokens (limit {TOTAL_BUDGET})"


def test_token_budget_headroom_report():
    """Visibility test (not a regression gate) — prints headroom per agent."""
    print()
    for config_path in PLUGINS:
        data = yaml.safe_load(config_path.read_text())
        prompt = _extract_prompt(data)
        if prompt is None:
            continue
        tokens = _approx_tokens(prompt)
        headroom = PER_AGENT_BUDGET - tokens
        print(f"  {config_path.parent.name:45s} ~{tokens:5d} tokens  (headroom: {headroom})")
