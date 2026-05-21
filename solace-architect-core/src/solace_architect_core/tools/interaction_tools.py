"""User-interaction tools (Phase B of discovery Q&A UX).

Provides ``ask_user_question``: a structured-question primitive agents call
when they need an answer from the user that has a well-defined shape
(single-choice, yes/no, multi-select, free-text). The tool returns a
payload the agent then echoes verbatim as a fenced ```question block in
its final message; the WebUI entrypoint frontend parses the block,
suppresses it from the rendered text, and renders an interactive form
card. The user's reply arrives back as an A2A ``DataPart`` (see
``solace-architect-webui-entrypoint`` chat POST handler).

Markdown Decision Brief format remains supported as a fallback when the
LLM forgets to call this tool — the prompt documents both shapes.
"""

from __future__ import annotations

from typing import Any, Optional

from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


_KINDS = ("single_choice", "yes_no", "multi_choice", "free_text")
_SEVERITIES = ("blocking", "advisory", "info")


def _coerce_options(options: Any) -> Any:
    """Tolerate JSON-string options.

    SAM's schema extractor (dynamic_tool._get_schema_from_signature) maps
    Optional[list[dict]] to ADK Schema.STRING when the parameterised
    type doesn't hit its type_map directly, so the LLM ends up sending
    options as a JSON-encoded string. Reject path was "options must be
    a list" — a real bug that bit Discovery on 2026-05-18. Coerce here
    so callers (LLM or Python) can pass either shape.
    """
    if isinstance(options, str):
        try:
            import json
            return json.loads(options)
        except (json.JSONDecodeError, ValueError):
            return options  # let the downstream isinstance check fail with the original list-error
    return options


def _validate_options(kind: str, options: Optional[list]) -> Optional[str]:
    """Return an error message if options don't satisfy the kind's contract."""
    if kind == "yes_no":
        return None  # frontend renders yes/no buttons; options ignored
    if kind == "free_text":
        return None  # no options for free text
    if not options:
        return f"kind={kind!r} requires options"
    if not isinstance(options, list):
        return "options must be a list (or a JSON-encoded list of dicts)"
    seen_ids: set[str] = set()
    for i, opt in enumerate(options):
        if not isinstance(opt, dict):
            return f"options[{i}] must be a dict"
        if "id" not in opt or "label" not in opt:
            return f"options[{i}] must have 'id' and 'label'"
        if opt["id"] in seen_ids:
            return f"options[{i}].id={opt['id']!r} is duplicated"
        seen_ids.add(opt["id"])
    if kind == "single_choice" and not (2 <= len(options) <= 8):
        return f"single_choice expects 2-8 options, got {len(options)}"
    if kind == "multi_choice" and not (2 <= len(options) <= 10):
        return f"multi_choice expects 2-10 options, got {len(options)}"
    return None


@coerce_args
async def ask_user_question(
    question_id: str,
    question: str,
    kind: str = "single_choice",
    options: Optional[list[dict]] = None,
    context: Optional[str] = None,
    recommended: Optional[str] = None,
    allow_custom: bool = True,
    severity: str = "blocking",
    counter: Optional[str] = None,
    example: Optional[str] = None,
    placeholder: Optional[str] = None,
) -> ToolResult:
    """Emit a structured question for the WebUI to render as a form card.

    Parameters
    ----------
    question_id : str
        Stable identifier so the user's reply can be correlated to the
        question that asked it (the reply DataPart carries the same id).
    question : str
        The question text, framed in user-outcome terms. Markdown allowed.
    kind : str
        One of ``single_choice``, ``yes_no``, ``multi_choice``, ``free_text``.
        - ``single_choice``: 2-4 mutually exclusive options (radio buttons).
        - ``yes_no``: two-button binary gate; ``options`` ignored.
        - ``multi_choice``: 2-8 options, user picks any subset (checkboxes).
        - ``free_text``: input box; ``options`` ignored, ``example`` and
          ``placeholder`` may guide format.
    options : list[dict] | None
        Required for single_choice / multi_choice. Each option:
        ``{"id": str, "label": str, "pros"?: str, "cons"?: str}``.
        Ids must be unique within the question.
    context : str | None
        1-2 sentence "why this matters" rendered as supporting copy. Skip
        platform jargon; frame in business / user-outcome terms.
    recommended : str | None
        Id of the recommended option (single_choice only). The frontend
        marks the matching row with a star. Optional for advisory items.
    allow_custom : bool
        When True (default), the form includes an "…or type a custom
        answer" escape hatch so users aren't locked into the offered
        options.
    severity : str
        ``blocking`` (default) | ``advisory`` | ``info`` — drives the
        badge color on the rendered card.
    counter : str | None
        Free-text running counter for user expectation-setting, e.g.
        ``"1 of ~5"``.
    example : str | None
        Free-text example reply (free_text kind), shown above the input
        box. Used for "system names", "site list", "approx event rate"
        style asks.
    placeholder : str | None
        Free-text placeholder (free_text kind), shown inside the input.

    Returns
    -------
    ToolResult
        On success, ``data`` carries the rendering payload. The agent must
        echo ``data["schema"]`` verbatim as a fenced ``question`` block in
        its final message — the frontend parses that block and renders
        the form card.

        Example final message body::

            I have one blocking question before I write the brief.

            ```question
            {
              "id": "delivery-mode-q1",
              "kind": "single_choice",
              "question": "...",
              ...
            }
            ```
    """
    if kind not in _KINDS:
        return ToolResult(ok=False, error=f"kind must be one of {_KINDS}, got {kind!r}")
    if severity not in _SEVERITIES:
        return ToolResult(ok=False, error=f"severity must be one of {_SEVERITIES}, got {severity!r}")
    if not question_id or not isinstance(question_id, str):
        return ToolResult(ok=False, error="question_id must be a non-empty string")
    if not question or not isinstance(question, str):
        return ToolResult(ok=False, error="question must be a non-empty string")
    if recommended is not None and kind != "single_choice":
        return ToolResult(ok=False, error="recommended is only meaningful for single_choice")

    options = _coerce_options(options)
    err = _validate_options(kind, options)
    if err:
        return ToolResult(ok=False, error=err)

    if recommended is not None:
        opt_ids = {o["id"] for o in (options or [])}
        if recommended not in opt_ids:
            return ToolResult(ok=False, error=f"recommended={recommended!r} not in options ids: {sorted(opt_ids)}")

    schema: dict[str, Any] = {
        "id": question_id,
        "kind": kind,
        "question": question,
        "severity": severity,
        "allow_custom": allow_custom,
    }
    if options:
        schema["options"] = options
    if context:
        schema["context"] = context
    if recommended:
        schema["recommended"] = recommended
    if counter:
        schema["counter"] = counter
    if example:
        schema["example"] = example
    if placeholder:
        schema["placeholder"] = placeholder

    return ToolResult(
        ok=True,
        data={
            "_widget": "question",
            "instructions": (
                "Echo the 'schema' object verbatim as a fenced ```question block "
                "at the end of your message. The frontend renders the form from "
                "that block. Brief 1-sentence preamble above the block is fine."
            ),
            "schema": schema,
        },
    )
