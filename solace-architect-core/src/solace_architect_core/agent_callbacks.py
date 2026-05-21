"""SAM callback helpers for Solace Architect agents (Decision 84).

Bridges between SAM's runtime callback contract and the telemetry tools, so each
agent's ``after_model_callback`` becomes a one-liner that captures token usage
into the engagement's append-only ledger.

Each agent's ``app.py`` is expected to wire a callback of the shape:

    from solace_architect_core.agent_callbacks import record_llm_call_telemetry

    async def after_model_callback(callback_context, llm_response):
        await record_llm_call_telemetry(
            llm_response=llm_response,
            agent="SADiscoveryAgent",
            engagement_id=callback_context.state.get("engagement_id"),
            step_id=callback_context.state.get("step_id"),
            sam_task_id=callback_context.state.get("logical_task_id"),
            model=callback_context.state.get("model_name", "unknown"),
        )
        return None  # SAM convention: returning None means no response mutation

The ``engagement_id``/``step_id``/``logical_task_id``/``model_name`` keys are
populated on ``callback_context.state`` by SAM and by each agent's own task-start
hook. ``engagement_id`` is the only one our recorder requires; if it's absent
the call is dropped with an explicit ``ToolResult.ok == False`` rather than
silently corrupting another engagement's ledger.
"""

from __future__ import annotations

from typing import Any, Optional

from .tools.artifact_tools import ToolResult
from .tools.telemetry_tools import record_token_usage


def _extract_usage(llm_response: Any) -> tuple[int, int, int]:
    """Pull ``(input, output, cached)`` token counts from a SAM ``LlmResponse``.

    SAM's ADK callback (``solace_agent_mesh/agent/adk/callbacks.py``) reads:

    - ``llm_response.usage_metadata.prompt_token_count``
    - ``llm_response.usage_metadata.candidates_token_count``
    - ``llm_response.usage_metadata.prompt_tokens_details.cached_tokens``
      (provider-specific; may be absent)

    Returns ``(0, 0, 0)`` when any of these are missing so a malformed response
    never crashes the callback.
    """
    usage = getattr(llm_response, "usage_metadata", None)
    if usage is None:
        return (0, 0, 0)
    input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    cached_tokens = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
    return (input_tokens, output_tokens, cached_tokens)


async def record_llm_call_telemetry(
    *,
    llm_response: Any,
    agent: str,
    engagement_id: Optional[str],
    model: str = "unknown",
    step_id: Optional[str] = None,
    sam_task_id: Optional[str] = None,
    source: str = "agent",
    user_id: Optional[str] = None,
) -> ToolResult:
    """Extract token usage from a SAM ``LlmResponse`` and append it to the ledger.

    Drops silently (returns ``ok=False`` without raising) when ``engagement_id``
    is missing — the agent may be handling a system / discovery / health-check
    request that isn't tied to an engagement, and we'd rather no-op than write
    to a default bucket and pollute the per-project view.

    ``user_id`` is lifted from the same ``[Active engagement: ..., user_id=…]``
    header the WebUI injects into each agent message; the patch layer parses
    it from ``callback_context`` and threads it here so the ledger lands under
    ``users/<user_id>/<engagement_id>/...`` to match every other artifact.
    """
    if not engagement_id:
        return ToolResult(ok=False, error="record_llm_call_telemetry: missing engagement_id; call dropped")

    input_tokens, output_tokens, cached_tokens = _extract_usage(llm_response)
    if input_tokens == 0 and output_tokens == 0:
        return ToolResult(ok=False, error="record_llm_call_telemetry: no usage_metadata on llm_response")

    return await record_token_usage(
        engagement_id,
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
        step_id=step_id,
        sam_task_id=sam_task_id,
        source=source,
        user_id=user_id,
    )
