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


@pytest.mark.parametrize("config_path", PLUGINS, ids=lambda p: p.parent.name)
def test_per_agent_system_prompt_under_budget(config_path):
    data = yaml.safe_load(config_path.read_text())
    if "agent" not in data:
        pytest.skip("entrypoint plugin")
    prompt = data["agent"].get("system_prompt") or ""
    tokens = _approx_tokens(prompt)
    assert tokens <= PER_AGENT_BUDGET, \
        f"{config_path.parent.name}: system_prompt is ~{tokens} tokens (limit {PER_AGENT_BUDGET})"


def test_total_agent_prompt_budget():
    total = 0
    for config_path in PLUGINS:
        data = yaml.safe_load(config_path.read_text())
        if "agent" not in data:
            continue
        total += _approx_tokens(data["agent"].get("system_prompt") or "")
    assert total <= TOTAL_BUDGET, \
        f"total prompt size ~{total} tokens (limit {TOTAL_BUDGET})"


def test_token_budget_headroom_report():
    """Visibility test (not a regression gate) — prints headroom per agent."""
    print()
    for config_path in PLUGINS:
        data = yaml.safe_load(config_path.read_text())
        if "agent" not in data:
            continue
        prompt = data["agent"].get("system_prompt") or ""
        tokens = _approx_tokens(prompt)
        headroom = PER_AGENT_BUDGET - tokens
        print(f"  {config_path.parent.name:45s} ~{tokens:5d} tokens  (headroom: {headroom})")
