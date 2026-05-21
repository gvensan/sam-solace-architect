"""Regression tests for solace_architect_core.tools.interaction_tools.

The ``ask_user_question`` tool's ``options`` parameter is the most fragile
input shape in the SA toolset because ADK's schema extractor downgrades
``Optional[list[dict]]`` to ``STRING`` when the parameterised type doesn't
hit its type_map directly, so the LLM sends options as a JSON-encoded
string instead of a native list. SADiscoveryAgent flagged this bug on
2026-05-18 ("options must be a list" regardless of formatting).

``_coerce_options`` parses the JSON string back into a list before
validation. These tests pin that behavior — without them, a future
refactor could silently re-break every clickable-options question card
across all SA agents.
"""

from __future__ import annotations

import json

import pytest

from solace_architect_core.tools.interaction_tools import (
    _coerce_options,
    ask_user_question,
)


# ---------- _coerce_options ----------------------------------------------


def test_coerce_passes_through_native_list():
    """Native list shape (Python caller / well-typed LLM): no transformation."""
    opts = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
    assert _coerce_options(opts) is opts


def test_coerce_parses_json_string():
    """LLM sends a JSON-encoded string — coerce back to list of dicts."""
    raw = '[{"id":"a","label":"A"},{"id":"b","label":"B"}]'
    out = _coerce_options(raw)
    assert isinstance(out, list)
    assert out == json.loads(raw)


def test_coerce_returns_string_unchanged_on_malformed_json():
    """Malformed JSON falls through to the original string so the
    downstream isinstance check produces the canonical error message."""
    bad = "not really json"
    assert _coerce_options(bad) == bad


def test_coerce_passes_through_none():
    """None is valid for yes_no / free_text kinds."""
    assert _coerce_options(None) is None


# ---------- ask_user_question — both input shapes work --------------------


@pytest.mark.asyncio
async def test_ask_user_question_accepts_native_list():
    res = await ask_user_question(
        question_id="t1",
        question="Test?",
        kind="single_choice",
        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    )
    assert res.ok, res.error
    assert res.data["schema"]["options"] == [
        {"id": "a", "label": "A"},
        {"id": "b", "label": "B"},
    ]


@pytest.mark.asyncio
async def test_ask_user_question_accepts_json_string_options():
    """This is the regression — LLM sends options as a JSON string."""
    res = await ask_user_question(
        question_id="t2",
        question="Test?",
        kind="single_choice",
        options='[{"id":"a","label":"A"},{"id":"b","label":"B"}]',  # noqa
    )
    assert res.ok, res.error
    assert res.data["schema"]["options"] == [
        {"id": "a", "label": "A"},
        {"id": "b", "label": "B"},
    ]


@pytest.mark.asyncio
async def test_ask_user_question_rejects_garbage_options():
    """Malformed JSON string surfaces the canonical 'options must be a list' error."""
    res = await ask_user_question(
        question_id="t3",
        question="Test?",
        kind="single_choice",
        options="not really json",
    )
    assert not res.ok
    assert "must be a list" in res.error


@pytest.mark.asyncio
async def test_ask_user_question_multi_choice_accepts_json_string():
    """Same coercion applies to multi_choice (regression for affected kinds)."""
    res = await ask_user_question(
        question_id="t4",
        question="Pick some",
        kind="multi_choice",
        options='[{"id":"a","label":"A"},{"id":"b","label":"B"},{"id":"c","label":"C"}]',  # noqa
    )
    assert res.ok, res.error
    assert len(res.data["schema"]["options"]) == 3


@pytest.mark.asyncio
async def test_ask_user_question_yes_no_ignores_options():
    """yes_no doesn't take options at all — passing them must not error."""
    res = await ask_user_question(
        question_id="t5",
        question="Proceed?",
        kind="yes_no",
    )
    assert res.ok, res.error


@pytest.mark.asyncio
async def test_ask_user_question_free_text_no_options():
    res = await ask_user_question(
        question_id="t6",
        question="Describe X",
        kind="free_text",
        example="like this",
    )
    assert res.ok, res.error
    assert res.data["schema"]["example"] == "like this"


# ---------- Recommended-id validation (single_choice only) ----------------


@pytest.mark.asyncio
async def test_recommended_must_match_option_id():
    res = await ask_user_question(
        question_id="t7",
        question="Test?",
        kind="single_choice",
        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        recommended="c",  # not in options
    )
    assert not res.ok
    assert "not in options ids" in res.error


@pytest.mark.asyncio
async def test_recommended_only_for_single_choice():
    res = await ask_user_question(
        question_id="t8",
        question="Test?",
        kind="multi_choice",
        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        recommended="a",
    )
    assert not res.ok
    assert "only meaningful for single_choice" in res.error
