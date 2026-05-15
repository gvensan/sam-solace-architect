"""Unit tests for solace-architect-core tools.

Phase 1: against the file-based storage layer using a per-test tmp_path.
"""

import os
import pytest

from solace_architect_core.tools import (
    artifact_tools, decision_tools, project_tools,
    intake_tools, dashboard_tools, validation_tools,
    grounding_tools,
)


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
