"""Unit tests for solace-architect-core tools.

Phase 1: against the file-based storage layer using a per-test tmp_path.
"""

import os
import pytest

from solace_architect_core.tools import (
    artifact_tools, decision_tools, project_tools,
    intake_tools, dashboard_tools, validation_tools,
    grounding_tools, telemetry_tools, lifecycle_tools,
)
from solace_architect_core import agent_callbacks


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """Each test gets its own artifact storage root."""
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


# ---------- artifact_tools ----------

@pytest.mark.asyncio
async def test_write_then_read():
    eid = "eng-1"
    r = await artifact_tools.write_artifact(eid, "discovery/brief.md", "hello world")
    assert r.ok
    r = await artifact_tools.read_artifact(eid, "discovery/brief.md")
    assert r.ok and r.data == "hello world"


@pytest.mark.asyncio
async def test_write_rejects_forbidden_term():
    r = await artifact_tools.write_artifact("eng-2", "test/x.md", "We use a connector for Kafka.")
    assert not r.ok
    assert r.error_detail["terminology_check"]["violations"]
    assert r.error_detail["terminology_check"]["violations"][0]["found"] == "connector"


@pytest.mark.asyncio
async def test_path_traversal_rejected():
    r = await artifact_tools.write_artifact("eng-3", "../escape.md", "x")
    assert not r.ok


@pytest.mark.asyncio
async def test_read_missing_artifact():
    r = await artifact_tools.read_artifact("eng-4", "missing/file.yaml")
    assert not r.ok


# ---------- decision_tools ----------

@pytest.mark.asyncio
async def test_decision_id_sequencing():
    eid = "eng-5"
    r1 = await decision_tools.record_decision(eid, context="c1", recommendation="r1",
                                              selected="s1", rationale="rt1", source_agent="SADomainAgent")
    r2 = await decision_tools.record_decision(eid, context="c2", recommendation="r2",
                                              selected="s2", rationale="rt2", source_agent="SADomainAgent")
    assert r1.data["id"] == "D1"
    assert r2.data["id"] == "D2"


@pytest.mark.asyncio
async def test_open_item_severity_filter():
    eid = "eng-6"
    await decision_tools.record_open_item(eid, severity="blocking", source="intake", description="x")
    await decision_tools.record_open_item(eid, severity="advisory", source="intake", description="y")
    r = await decision_tools.read_open_items(eid, severity="blocking")
    assert len(r.data) == 1 and r.data[0]["severity"] == "blocking"


@pytest.mark.asyncio
async def test_deferred_finding_creates_open_item():
    eid = "eng-7"
    f = await decision_tools.record_finding(eid, severity="critical", description="bad",
                                            affected_artifact="topic-design/x.yaml",
                                            recommendation="fix", source_agent="SAArchitectReviewerAgent")
    await decision_tools.update_finding_status(eid, finding_id=f.data["id"], new_status="deferred")
    items = (await decision_tools.read_open_items(eid)).data
    assert any(q["source"] == "review-deferred" and q["severity"] == "blocking" for q in items)


@pytest.mark.asyncio
async def test_feedback_rating_validation():
    r = await decision_tools.record_feedback("eng-fb", scope="topic-design", rating=6, category="depth", note="x")
    assert not r.ok


# ---------- project_tools ----------

@pytest.mark.asyncio
async def test_create_and_list_project():
    p = await project_tools.create_project(name="My Project")
    assert p.ok
    lr = await project_tools.list_projects()
    assert any(x["id"] == p.data["id"] for x in lr.data)


@pytest.mark.asyncio
async def test_archive_hides_from_default_list():
    p = await project_tools.create_project(name="ToArchive")
    await project_tools.archive_project(p.data["id"])
    lr = await project_tools.list_projects()
    assert not any(x["id"] == p.data["id"] for x in lr.data)
    lr2 = await project_tools.list_projects(include_archived=True)
    assert any(x["id"] == p.data["id"] for x in lr2.data)


# ---------- intake_tools ----------

@pytest.mark.asyncio
async def test_parse_intake_emits_blocking_for_missing_required(tmp_path):
    f = tmp_path / "intake.yaml"
    f.write_text("project_name: Test\n")   # missing project_type, systems, requirements
    r = await intake_tools.parse_intake_document(str(f))
    assert r.ok
    blocking = [q for q in r.data["open_items"] if q["severity"] == "blocking"]
    assert len(blocking) >= 3


@pytest.mark.asyncio
async def test_compute_intake_preview_matches_plan_shape():
    brief = {"systems": [{"name": "AI Chat"}],
             "requirements": {"topology": "single-site", "delivery_mode": "guaranteed",
                              "processing_guarantee": "at-least-once"},
             "existing_messaging": "IBM MQ",
             "preferences": {"provision_event_portal": False}}
    r = await intake_tools.compute_intake_preview(brief)
    included_steps = {s["step"] for s in r.data["included_steps"]}
    skipped_steps = {s["step"] for s in r.data["skipped_steps"]}
    assert "sam-design" in included_steps
    assert "mesh-design" in skipped_steps
    assert "provisioning" in skipped_steps


# ---------- dashboard_tools ----------

@pytest.mark.asyncio
async def test_overview_counts_decisions_and_open_items():
    p = await project_tools.create_project(name="Dash")
    eid = p.data["id"]
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml",
                                        "systems: []\nrequirements: {}\npreferences: {provision_event_portal: false}")
    await decision_tools.record_decision(eid, context="c", recommendation="r",
                                         selected="s", rationale="rt", source_agent="x")
    await decision_tools.record_open_item(eid, severity="blocking", source="intake", description="x")
    r = await dashboard_tools.compute_overview_stats(eid)
    assert r.data["decisions_count"] == 1
    assert r.data["open_items_blocking"] == 1
    assert r.data["ep_provisioning_status"] == "not-requested"


# ---------- validation_tools ----------

@pytest.mark.asyncio
async def test_trace_requirements_finds_mention():
    eid = "eng-trace"
    await artifact_tools.write_artifact(eid, "topic-design/x.md",
                                        "## Delivery mode\nWe use guaranteed messaging for orders.")
    brief = {"requirements": {"delivery_mode": "guaranteed"}}
    r = await validation_tools.trace_requirements(brief, ["topic-design/x.md"], eid)
    assert r.data["matrix"]["delivery_mode"] == ["topic-design/x.md"]
    assert not r.data["unaddressed"]


# ---------- grounding_tools ----------

@pytest.mark.asyncio
async def test_load_preamble_returns_content_with_load_bearing_sections():
    r = await grounding_tools.load_preamble()
    assert r.ok, f"load_preamble failed: {r.error}"
    body = r.data
    assert isinstance(body, str) and len(body) > 0

    for required_section in (
        "Accuracy and grounding discipline",
        "Inline citation",
        "Strict grounding in Solace",
        "Claim classification discipline",
        "Voice and writing principles",
        "Naming discipline",
        "Working style",
    ):
        assert required_section in body, f"missing required section: {required_section!r}"

    assert "Micro-Integration" in body
    assert "[doc:" in body and "[inference]" in body and "[user]" in body


# ---------- telemetry_tools ----------

@pytest.mark.asyncio
async def test_record_then_read_token_usage_groups_by_agent():
    eid = "eng-tel-1"
    await telemetry_tools.record_token_usage(
        eid, agent="SADiscoveryAgent", model="claude-sonnet-4-6",
        input_tokens=100, output_tokens=20, cached_input_tokens=80, step_id="discovery",
    )
    await telemetry_tools.record_token_usage(
        eid, agent="SADiscoveryAgent", model="claude-sonnet-4-6",
        input_tokens=200, output_tokens=40, cached_input_tokens=150, step_id="discovery",
    )
    await telemetry_tools.record_token_usage(
        eid, agent="SADomainAgent", model="claude-opus-4-7",
        input_tokens=500, output_tokens=80, step_id="topic-design",
    )

    r = await telemetry_tools.read_token_usage(eid, group_by="agent")
    assert r.ok
    by_agent = {row["key"]: row for row in r.data["rows"]}

    assert by_agent["SADiscoveryAgent"]["input_tokens"] == 300
    assert by_agent["SADiscoveryAgent"]["output_tokens"] == 60
    assert by_agent["SADiscoveryAgent"]["cached_input_tokens"] == 230
    assert by_agent["SADiscoveryAgent"]["total_tokens"] == 360
    assert by_agent["SADiscoveryAgent"]["calls"] == 2

    assert by_agent["SADomainAgent"]["total_tokens"] == 580
    assert by_agent["SADomainAgent"]["calls"] == 1

    assert r.data["totals"]["input_tokens"] == 800
    assert r.data["totals"]["output_tokens"] == 140
    assert r.data["totals"]["total_tokens"] == 940
    assert r.data["totals"]["calls"] == 3


@pytest.mark.asyncio
async def test_read_token_usage_groups_by_step_model_day():
    eid = "eng-tel-2"
    await telemetry_tools.record_token_usage(
        eid, agent="A", model="m1", input_tokens=10, output_tokens=2, step_id="s1",
        ts="2026-05-15T10:00:00.000Z",
    )
    await telemetry_tools.record_token_usage(
        eid, agent="A", model="m2", input_tokens=20, output_tokens=4, step_id="s2",
        ts="2026-05-15T11:00:00.000Z",
    )
    await telemetry_tools.record_token_usage(
        eid, agent="A", model="m1", input_tokens=30, output_tokens=6, step_id=None,
        ts="2026-05-16T10:00:00.000Z",
    )

    by_step = {r["key"]: r for r in (await telemetry_tools.read_token_usage(eid, group_by="step")).data["rows"]}
    assert by_step["s1"]["calls"] == 1
    assert by_step["s2"]["calls"] == 1
    assert by_step["<no-step>"]["calls"] == 1

    by_model = {r["key"]: r for r in (await telemetry_tools.read_token_usage(eid, group_by="model")).data["rows"]}
    assert by_model["m1"]["total_tokens"] == 48
    assert by_model["m2"]["total_tokens"] == 24

    by_day = {r["key"]: r for r in (await telemetry_tools.read_token_usage(eid, group_by="day")).data["rows"]}
    assert by_day["2026-05-15"]["calls"] == 2
    assert by_day["2026-05-16"]["calls"] == 1


@pytest.mark.asyncio
async def test_read_token_usage_since_until_filtering():
    from datetime import datetime, timezone
    eid = "eng-tel-3"
    await telemetry_tools.record_token_usage(
        eid, agent="A", model="m", input_tokens=10, output_tokens=2,
        ts="2026-05-14T10:00:00.000Z",
    )
    await telemetry_tools.record_token_usage(
        eid, agent="A", model="m", input_tokens=20, output_tokens=4,
        ts="2026-05-15T10:00:00.000Z",
    )
    await telemetry_tools.record_token_usage(
        eid, agent="A", model="m", input_tokens=30, output_tokens=6,
        ts="2026-05-16T10:00:00.000Z",
    )

    since = datetime(2026, 5, 15, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 16, 0, 0, tzinfo=timezone.utc)
    r = await telemetry_tools.read_token_usage(eid, group_by="day", since=since, until=until)
    assert r.data["totals"]["calls"] == 1
    assert r.data["totals"]["total_tokens"] == 24
    assert r.data["rows"][0]["key"] == "2026-05-15"


@pytest.mark.asyncio
async def test_read_token_usage_empty_when_no_ledger():
    r = await telemetry_tools.read_token_usage("eng-never-touched", group_by="agent")
    assert r.ok
    assert r.data["rows"] == []
    assert r.data["totals"]["calls"] == 0
    assert r.data["row_count_raw"] == 0


# ---------- agent_callbacks ----------

class _FakeUsageMetadata:
    def __init__(self, prompt, candidates, cached=None):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        if cached is not None:
            class _D:  # noqa: D106
                pass
            d = _D()
            d.cached_tokens = cached
            self.prompt_tokens_details = d


class _FakeLlmResponse:
    def __init__(self, usage_metadata):
        self.usage_metadata = usage_metadata


@pytest.mark.asyncio
async def test_record_llm_call_telemetry_extracts_usage_metadata():
    eid = "eng-cb-1"
    resp = _FakeLlmResponse(_FakeUsageMetadata(prompt=123, candidates=45, cached=100))
    r = await agent_callbacks.record_llm_call_telemetry(
        llm_response=resp,
        agent="SADiscoveryAgent",
        engagement_id=eid,
        model="claude-sonnet-4-6",
        step_id="discovery",
        sam_task_id="task-xyz",
    )
    assert r.ok
    rr = await telemetry_tools.read_token_usage(eid, group_by="agent")
    assert rr.data["totals"]["input_tokens"] == 123
    assert rr.data["totals"]["output_tokens"] == 45
    assert rr.data["totals"]["cached_input_tokens"] == 100


@pytest.mark.asyncio
async def test_record_llm_call_telemetry_drops_when_engagement_id_missing():
    resp = _FakeLlmResponse(_FakeUsageMetadata(prompt=10, candidates=2))
    r = await agent_callbacks.record_llm_call_telemetry(
        llm_response=resp, agent="X", engagement_id=None, model="m",
    )
    assert not r.ok
    assert "engagement_id" in r.error


@pytest.mark.asyncio
async def test_record_llm_call_telemetry_drops_when_no_usage_metadata():
    resp = _FakeLlmResponse(usage_metadata=None)
    r = await agent_callbacks.record_llm_call_telemetry(
        llm_response=resp, agent="X", engagement_id="eng-x", model="m",
    )
    assert not r.ok
    assert "usage_metadata" in r.error


@pytest.mark.asyncio
async def test_read_user_token_usage_aggregates_across_projects():
    p1 = await project_tools.create_project(name="alpha")
    p2 = await project_tools.create_project(name="beta")
    eid1, eid2 = p1.data["id"], p2.data["id"]

    await telemetry_tools.record_token_usage(
        eid1, agent="SADiscoveryAgent", model="m1",
        input_tokens=100, output_tokens=20,
    )
    await telemetry_tools.record_token_usage(
        eid1, agent="SADomainAgent", model="m1",
        input_tokens=200, output_tokens=40,
    )
    await telemetry_tools.record_token_usage(
        eid2, agent="SADiscoveryAgent", model="m2",
        input_tokens=500, output_tokens=80,
    )

    r = await telemetry_tools.read_user_token_usage(group_by="project")
    assert r.ok
    by_proj = {row["key"]: row for row in r.data["rows"]}
    assert by_proj[eid1]["total_tokens"] == 360
    assert by_proj[eid1]["label"] == "alpha"
    assert by_proj[eid1]["calls"] == 2
    assert by_proj[eid2]["total_tokens"] == 580
    assert by_proj[eid2]["label"] == "beta"
    assert r.data["totals"]["calls"] == 3
    assert r.data["totals"]["total_tokens"] == 940
    assert r.data["project_count"] == 2

    r2 = await telemetry_tools.read_user_token_usage(group_by="agent")
    by_agent = {row["key"]: row for row in r2.data["rows"]}
    assert by_agent["SADiscoveryAgent"]["calls"] == 2
    assert by_agent["SADiscoveryAgent"]["total_tokens"] == 700
    assert by_agent["SADomainAgent"]["calls"] == 1


@pytest.mark.asyncio
async def test_read_user_token_usage_empty_when_no_projects():
    r = await telemetry_tools.read_user_token_usage(group_by="project")
    assert r.ok
    assert r.data["rows"] == []
    assert r.data["totals"]["calls"] == 0
    assert r.data["project_count"] == 0


# ---------- lifecycle_tools.record_scope_progress ----------

@pytest.mark.asyncio
async def test_record_scope_progress_writes_progress_block():
    eid = "scope-eng-1"
    r = await lifecycle_tools.record_scope_progress(
        engagement_id=eid,
        step="design",
        current_scope="topic-design",
        status="DONE_WITH_CONCERNS",
        next_scope="broker-select",
        scopes_done=["topic-design"],
        note="auto-mode: GDPR favours region-at-root",
    )
    assert r.ok
    assert r.data == {
        "step": "design",
        "current_scope": "topic-design",
        "status": "DONE_WITH_CONCERNS",
        "next_scope": "broker-select",
    }

    status = await lifecycle_tools.get_engagement_status(engagement_id=eid)
    sp = status.data["steps"]["design"]["scope_progress"]
    assert sp["current"] == "topic-design"
    assert sp["status"] == "DONE_WITH_CONCERNS"
    assert sp["next"] == "broker-select"
    assert sp["done"] == ["topic-design"]
    assert sp["note"] == "auto-mode: GDPR favours region-at-root"
    assert sp["updated_at"]


@pytest.mark.asyncio
async def test_record_scope_progress_final_scope_marks_next_null():
    eid = "scope-eng-2"
    r = await lifecycle_tools.record_scope_progress(
        engagement_id=eid,
        step="design",
        current_scope="event-portal",
        status="DONE",
        next_scope=None,
        scopes_done=["topic-design", "broker-select", "protocol-select",
                     "integration", "mesh-design", "ha-dr", "event-portal"],
    )
    assert r.ok
    assert r.data["next_scope"] is None
    status = await lifecycle_tools.get_engagement_status(engagement_id=eid)
    sp = status.data["steps"]["design"]["scope_progress"]
    assert sp["next"] is None
    assert len(sp["done"]) == 7


@pytest.mark.asyncio
async def test_record_scope_progress_preserves_step_status():
    """scope_progress writes must NOT clobber the top-level step.status field."""
    eid = "scope-eng-3"
    # First, set the step-level status.
    await lifecycle_tools.set_step_status(
        engagement_id=eid, step="design", status="NEEDS_CONTEXT",
        note="mid-design", agent="SADomainAgent",
    )
    # Then, record scope progress.
    await lifecycle_tools.record_scope_progress(
        engagement_id=eid, step="design",
        current_scope="topic-design", status="DONE",
        next_scope="broker-select", scopes_done=["topic-design"],
    )
    status = await lifecycle_tools.get_engagement_status(engagement_id=eid)
    entry = status.data["steps"]["design"]
    assert entry["status"] == "NEEDS_CONTEXT"
    assert entry["note"] == "mid-design"
    assert entry["scope_progress"]["current"] == "topic-design"
    assert entry["scope_progress"]["next"] == "broker-select"


@pytest.mark.asyncio
async def test_record_scope_progress_rejects_bad_status():
    r = await lifecycle_tools.record_scope_progress(
        engagement_id="scope-eng-4", step="design",
        current_scope="topic-design", status="MOSTLY_OK",
        next_scope="broker-select",
    )
    assert not r.ok
    assert "status must be one of" in r.error


@pytest.mark.asyncio
async def test_record_scope_progress_rejects_empty_scope():
    r = await lifecycle_tools.record_scope_progress(
        engagement_id="scope-eng-5", step="design",
        current_scope="", status="DONE", next_scope="broker-select",
    )
    assert not r.ok
    assert "current_scope" in r.error
