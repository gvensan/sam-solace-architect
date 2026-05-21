"""Token budget check for the Discovery system prompt (Decision 48 — ≤40K tokens)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

# Per-agent system-prompt ceiling from v2spec Decision 48.
TOKEN_CEILING = 40_000

# Char-to-token conversion. Anthropic's tokenizers run ~3.5-4 chars per token
# for English prose; we use 3 chars/token as a conservative upper bound so the
# test catches "almost over" cases before they ship.
CHARS_PER_TOKEN_CONSERVATIVE = 3


@pytest.fixture(scope="module")
def instruction() -> str:
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    return cfg["apps"][0]["app_config"]["instruction"]


def test_instruction_under_token_budget(instruction):
    """Role-specific prompt must leave room for grounding loads and conversation."""
    approx_tokens = len(instruction) // CHARS_PER_TOKEN_CONSERVATIVE
    assert approx_tokens <= TOKEN_CEILING, (
        f"Discovery role prompt {approx_tokens} tokens > {TOKEN_CEILING} budget. "
        f"Trim before merging."
    )


def test_instruction_well_under_with_preamble_headroom(instruction):
    """Leave at least 10K tokens of headroom for the shared preamble + jargon list."""
    HEADROOM_BUDGET = TOKEN_CEILING - 10_000  # ≤30K tokens role-specific
    approx_tokens = len(instruction) // CHARS_PER_TOKEN_CONSERVATIVE
    assert approx_tokens <= HEADROOM_BUDGET, (
        f"Discovery role prompt {approx_tokens} tokens; reserve ≥10K for preamble + jargon."
    )


def test_prompt_module_matches_config(instruction):
    """prompt.py SYSTEM_PROMPT must match config.yaml instruction (no content drift).

    Whitespace runs are normalized to single spaces before comparing — YAML's
    block-scalar parsing wraps long lines differently than the Python literal,
    and we don't want that cosmetic difference to fire the test. We catch
    actual content drift (words / punctuation changed).
    """
    import re
    from solace_architect_discovery.prompt import SYSTEM_PROMPT

    def _normalize(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    assert _normalize(SYSTEM_PROMPT) == _normalize(instruction), (
        "prompt.py and config.yaml have diverged. Update one to keep them in "
        "sync — they're the same content in two surfaces."
    )
