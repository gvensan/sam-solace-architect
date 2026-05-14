"""Operator vocabulary + matchers in skill-routing.yaml."""

import pytest

from solace_architect_core._routing import evaluate_when
from solace_architect_core.tools.workflow_tools import get_engagement_plan


BANK_CHAT = {
    "systems": [{"name": "AI Chat Assistant"}, {"name": "Core Banking REST"}],
    "requirements": {"topology": "single-site", "delivery_mode": "mixed",
                     "processing_guarantee": "at-least-once"},
    "existing_messaging": "IBM MQ",
    "preferences": {"provision_event_portal": False},
}

MARKET_DATA = {
    "systems": [{"name": "Market Data Feed"}],
    "requirements": {"topology": "multi-region", "delivery_mode": "direct",
                     "processing_guarantee": "best-effort"},
    "existing_messaging": "",
    "preferences": {"provision_event_portal": True},
}


# ---------- evaluate_when operator coverage ----------

def test_equals():
    assert evaluate_when({"a": 1}, [{"field": "a", "op": "equals", "value": 1}])
    assert not evaluate_when({"a": 2}, [{"field": "a", "op": "equals", "value": 1}])


def test_in():
    assert evaluate_when({"x": "b"}, [{"field": "x", "op": "in", "value": ["a", "b", "c"]}])
    assert not evaluate_when({"x": "z"}, [{"field": "x", "op": "in", "value": ["a", "b"]}])


def test_contains_any_on_string():
    assert evaluate_when({"s": "AI Chat"},
                         [{"field": "s", "op": "contains_any", "value": ["chat", "agent"]}])
    assert not evaluate_when({"s": "REST API"},
                             [{"field": "s", "op": "contains_any", "value": ["chat", "agent"]}])


def test_contains_any_on_array_projection():
    brief = {"systems": [{"name": "AI Chat Assistant"}, {"name": "REST API"}]}
    clause = {"field": "systems[*].name", "op": "contains_any", "value": ["chat", "agent"]}
    assert evaluate_when(brief, [clause])


def test_not_empty():
    assert evaluate_when({"x": "IBM MQ"}, [{"field": "x", "op": "not_empty"}])
    assert not evaluate_when({"x": ""}, [{"field": "x", "op": "not_empty"}])
    assert not evaluate_when({}, [{"field": "x", "op": "not_empty"}])


def test_and_across_clauses():
    brief = {"a": 1, "b": 2}
    clauses = [{"field": "a", "op": "equals", "value": 1},
               {"field": "b", "op": "equals", "value": 2}]
    assert evaluate_when(brief, clauses)
    bad = [{"field": "a", "op": "equals", "value": 1},
           {"field": "b", "op": "equals", "value": 99}]
    assert not evaluate_when(brief, bad)


def test_any_of_for_or():
    brief = {"a": 1, "b": 999}
    when = {"any_of": [{"field": "a", "op": "equals", "value": 1},
                       {"field": "b", "op": "equals", "value": 2}]}
    assert evaluate_when(brief, when)


# ---------- get_engagement_plan integration ----------

@pytest.mark.asyncio
async def test_plan_bank_chat_sam_included_mesh_skipped():
    plan = (await get_engagement_plan(BANK_CHAT)).data
    by_step = {s["step"]: s for s in plan}
    assert by_step["sam-design"]["included"], "AI Chat triggers sam-design"
    assert not by_step["mesh-design"]["included"], "single-site skips mesh"
    assert by_step["ha-dr"]["included"], "at-least-once triggers ha-dr"
    assert by_step["migration"]["included"], "existing IBM MQ triggers migration"
    assert not by_step["provisioning"]["included"], "opt-out skips provisioning"


@pytest.mark.asyncio
async def test_plan_market_data_mesh_included_sam_skipped():
    plan = (await get_engagement_plan(MARKET_DATA)).data
    by_step = {s["step"]: s for s in plan}
    assert not by_step["sam-design"]["included"], "no chat/agent skips sam"
    assert by_step["mesh-design"]["included"], "multi-region triggers mesh"
    assert not by_step["ha-dr"]["included"], "best-effort skips ha-dr"
    assert not by_step["migration"]["included"], "greenfield skips migration"
    assert by_step["provisioning"]["included"], "opt-in includes provisioning"


@pytest.mark.asyncio
async def test_skip_reason_populated_when_excluded():
    plan = (await get_engagement_plan(BANK_CHAT)).data
    mesh = next(s for s in plan if s["step"] == "mesh-design")
    assert not mesh["included"]
    assert mesh["skip_reason"] and "Single-site" in mesh["skip_reason"]
