"""Per-model token-cost table — used by telemetry aggregation + LiteLLM registration.

Single source of truth for token pricing. Two consumers:

1. :mod:`solace_architect_core.tools.telemetry_tools` — `_aggregate` computes
   cost on the fly from each row's `(model, input_tokens, output_tokens,
   cached_input_tokens)`. Computed at READ time so price-table edits apply
   retroactively to historical rows without a backfill step.

2. :func:`register_with_litellm` — called from each plugin's lifecycle.init()
   to tell LiteLLM's cost calculator about our custom aliases (e.g.
   ``openai/vertex-claude-4-5-sonnet``). Without this, every LLM call logs
   the "Cost tracking unavailable for model …" warning at WARNING level,
   polluting sam.log.

Prices are USD per token, sourced from public provider docs at the time of
this commit. Update by hand when providers change prices — they don't change
often, but they DO change.

Provider doc references (verify on update):
  * Anthropic Claude pricing: https://www.anthropic.com/pricing
  * Vertex AI Claude pricing matches Anthropic API in most cases.
"""

from __future__ import annotations

from typing import Optional


# All prices are USD PER TOKEN. Compute from $/M-tokens by multiplying by 1e-6.
#
# Cache pricing semantics (Anthropic, OpenAI compatible):
#   * cache_write — prompt-cache CREATE on a new prefix. Typically priced
#     ~25% above the base input rate. We don't track cache_write separately
#     in our telemetry today, so this entry is informational; the row's
#     cached_input_tokens column counts cache READ hits only.
#   * cache_read — prompt-cache HIT, much cheaper than fresh input.
#
# Keys are LITERAL model strings as they appear in our telemetry rows.
# To handle aliasing (a model can be reached via multiple provider prefixes),
# duplicate the entry under every alias the WebUI/agents might log.
MODEL_PRICES: dict[str, dict[str, float]] = {
    # ── Claude Sonnet 4.5 (Anthropic Sept 2025 release) ────────────────────
    # $3/M input, $15/M output, $0.30/M cache-read, $3.75/M cache-write
    "claude-sonnet-4-5": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },
    "anthropic/claude-sonnet-4-5": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },
    # LiteLLM proxy alias used by the user's deploy. openai/ prefix is the
    # LiteLLM convention for "treat this as OpenAI-API-shape regardless of
    # actual backend". Vertex Claude via a LiteLLM proxy commonly lands here.
    "openai/vertex-claude-4-5-sonnet": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },
    "vertex-claude-4-5-sonnet": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },

    # ── Claude Sonnet 4 / 3.5 (legacy aliases — still active in some deploys) ──
    "claude-sonnet-4-20250514": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },
    "anthropic/claude-sonnet-4-20250514": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3.0e-6, "output": 15.0e-6,
        "cache_read": 0.30e-6, "cache_write": 3.75e-6,
    },

    # ── Claude Opus 4 / 4.7 (Anthropic premium tier) ───────────────────────
    # $15/M input, $75/M output (per published Opus pricing).
    "claude-opus-4-7": {
        "input": 15.0e-6, "output": 75.0e-6,
        "cache_read": 1.50e-6, "cache_write": 18.75e-6,
    },
    "anthropic/claude-opus-4-7": {
        "input": 15.0e-6, "output": 75.0e-6,
        "cache_read": 1.50e-6, "cache_write": 18.75e-6,
    },

    # ── Claude Haiku 4.5 (cheap tier) ──────────────────────────────────────
    # $0.80/M input, $4/M output.
    "claude-haiku-4-5-20251001": {
        "input": 0.80e-6, "output": 4.0e-6,
        "cache_read": 0.08e-6, "cache_write": 1.0e-6,
    },
    "anthropic/claude-haiku-4-5-20251001": {
        "input": 0.80e-6, "output": 4.0e-6,
        "cache_read": 0.08e-6, "cache_write": 1.0e-6,
    },
}


def price_for(model: str) -> Optional[dict[str, float]]:
    """Return per-token prices for ``model``, or None if unknown.

    Direct lookup first; if no exact match, try a suffix lookup so a model
    string like ``some-proxy/claude-sonnet-4-5`` matches the bare
    ``claude-sonnet-4-5`` entry.
    """
    if not model:
        return None
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    for key in MODEL_PRICES:
        if model.endswith("/" + key) or key in model:
            return MODEL_PRICES[key]
    return None


def cost_for_row(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> Optional[dict[str, float]]:
    """Compute USD cost for one telemetry row. Returns None for unknown models.

    Cached input tokens are billed at the cache-read rate (if known) instead
    of the base input rate — that's the whole point of prompt caching. If
    ``cache_read`` isn't published for a model, we conservatively assume
    10% of the input rate (Anthropic's typical cache discount).

    Fallback for legacy rows: if ``model`` is empty or the literal string
    ``"unknown"`` (the value the telemetry recorder wrote before the
    PEP-563 + agent-model-resolution fix landed), and the env var
    ``SA_DEFAULT_LLM_MODEL`` names a known model, use that model's prices.
    Lets historical rows get retroactive cost numbers without rewriting
    the on-disk ledger.
    """
    if not model or model == "unknown":
        import os as _os
        fallback = _os.environ.get("SA_DEFAULT_LLM_MODEL", "").strip()
        if fallback:
            model = fallback
    p = price_for(model)
    if not p:
        return None
    cache_rate = p.get("cache_read", p["input"] * 0.1)
    fresh_input = max(0, input_tokens - cached_input_tokens)
    input_cost = fresh_input * p["input"] + cached_input_tokens * cache_rate
    output_cost = output_tokens * p["output"]
    return {
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd": input_cost + output_cost,
    }


def register_with_litellm() -> None:
    """Tell LiteLLM about our custom model aliases so it stops warning.

    LiteLLM logs ``"Cost tracking unavailable for model …"`` at WARNING
    level for every LLM call against an unknown model. Calling
    ``litellm.register_model`` populates its internal model_cost map so the
    warning stops AND LiteLLM's own cost reporting (which some downstream
    tools consume) starts emitting numbers.

    Idempotent: registering the same model twice is a no-op. Silent on any
    failure — never break agent startup over a price-table issue.
    """
    try:
        import litellm    # local import: agent process always has it; tests don't.
    except ImportError:
        return
    try:
        for name, prices in MODEL_PRICES.items():
            litellm.register_model({
                name: {
                    "input_cost_per_token": prices["input"],
                    "output_cost_per_token": prices["output"],
                    "cache_read_input_token_cost": prices.get("cache_read", prices["input"] * 0.1),
                    "cache_creation_input_token_cost": prices.get("cache_write", prices["input"] * 1.25),
                    "litellm_provider": "openai",   # treat as openai-shape regardless of actual backend
                    "max_tokens": 200000,
                }
            })
    except Exception:
        # Don't break boot if LiteLLM's API changes shape.
        pass


__all__ = ["MODEL_PRICES", "price_for", "cost_for_row", "register_with_litellm"]
