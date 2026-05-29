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
async def test_design_prefix_rejected():
    """The Design phase per-scope layout is FLAT — `topic-design/…`,
    `event-portal/…`. Domain agent hallucinations like `design/event-portal/
    event-portal-model.yaml` (observed 2026-05-24, hotel-reservation-eda)
    must be rejected so the agent retries with the canonical path.
    Without this, downstream agents looking at the canonical path see
    nothing on disk and the lifecycle stalls."""
    r = await artifact_tools.write_artifact(
        "eng-design-prefix",
        "design/event-portal/event-portal-model.yaml",
        "application_domain: {name: x}",
    )
    assert not r.ok
    assert "design/" in (r.error or "").lower()


@pytest.mark.asyncio
async def test_append_artifact_builds_file_in_chunks():
    """append_artifact lets the agent build a large prose file across several
    small calls (chunked write) so no single LLM turn has to emit the whole
    file — the mechanism that keeps generations under the upstream's streaming
    timeout. First chunk via write_artifact, rest via append_artifact."""
    eid = "eng-append"
    assert (await artifact_tools.write_artifact(eid, "topic-design/topic-design.md", "# Topic Design\n\n")).ok
    r = await artifact_tools.append_artifact(eid, "topic-design/topic-design.md", "chunk-two ")
    assert r.ok and r.data["appended_bytes"] == len("chunk-two ")
    assert (await artifact_tools.append_artifact(eid, "topic-design/topic-design.md", "chunk-three")).ok
    rd = await artifact_tools.read_artifact(eid, "topic-design/topic-design.md")
    assert rd.ok and rd.data == "# Topic Design\n\nchunk-two chunk-three"


@pytest.mark.asyncio
async def test_append_artifact_enforces_same_guards():
    # design/ prefix and forbidden terms must be rejected on append too.
    assert not (await artifact_tools.append_artifact("eng-append-2", "design/x.md", "y")).ok
    bad = await artifact_tools.append_artifact("eng-append-2", "topic-design/x.md", "use a connector")
    assert not bad.ok and bad.error_detail["terminology_check"]["violations"]


@pytest.mark.asyncio
async def test_append_artifact_accepts_content_alias():
    """The LLM often reuses write_artifact's `content=` on append_artifact; we
    accept it as an alias for `content_chunk` so the call doesn't error and burn
    a recovery round-trip. Either name works; neither = a clean error, not a crash."""
    eid = "eng-append-alias"
    assert (await artifact_tools.write_artifact(eid, "topic-design/topic-design.md", "# T\n")).ok
    # write_artifact-style `content=` must succeed on append_artifact
    r_alias = await artifact_tools.append_artifact(eid, "topic-design/topic-design.md", content="A ")
    assert r_alias.ok and r_alias.data["appended_bytes"] == len("A ")
    # canonical `content_chunk=` still works
    assert (await artifact_tools.append_artifact(eid, "topic-design/topic-design.md", content_chunk="B")).ok
    # neither provided → graceful error
    none_given = await artifact_tools.append_artifact(eid, "topic-design/topic-design.md")
    assert not none_given.ok and "content_chunk" in (none_given.error or "")
    rd = await artifact_tools.read_artifact(eid, "topic-design/topic-design.md")
    assert rd.ok and rd.data == "# T\nA B"


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
async def test_record_decision_is_idempotent_on_identity():
    """Re-asserting the same (source_agent, context, selected) — e.g. a scope the
    orchestrator re-dispatched after a stall — returns the existing decision
    instead of duplicating it. Rationale/recommendation rewording doesn't matter."""
    eid = "eng-dedup-1"
    r1 = await decision_tools.record_decision(
        eid, context="broker tier", recommendation="Enterprise", selected="Enterprise",
        rationale="fits throughput", source_agent="SADomainAgent")
    # Same identity, reworded rationale + recommendation → no new entry.
    r2 = await decision_tools.record_decision(
        eid, context="broker tier", recommendation="Enterprise tier",
        selected="Enterprise", rationale="reworded on retry", source_agent="SADomainAgent")
    assert r2.data["id"] == r1.data["id"]
    assert r2.data.get("duplicate") is True
    assert len((await decision_tools.read_decisions(eid)).data) == 1


@pytest.mark.asyncio
async def test_record_decision_distinct_selection_is_new():
    """A genuinely different choice (selected) for the same context is a NEW
    decision — dedup must not collapse a revised decision."""
    eid = "eng-dedup-2"
    await decision_tools.record_decision(
        eid, context="broker tier", recommendation="Enterprise", selected="Enterprise",
        rationale="x", source_agent="SADomainAgent")
    r2 = await decision_tools.record_decision(
        eid, context="broker tier", recommendation="Developer", selected="Developer",
        rationale="y", source_agent="SADomainAgent")
    assert r2.data["id"] == "D2"
    assert not r2.data.get("duplicate")
    assert len((await decision_tools.read_decisions(eid)).data) == 2


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


@pytest.mark.asyncio
async def test_unarchive_restores_to_default_list():
    p = await project_tools.create_project(name="ToRestore")
    pid = p.data["id"]
    await project_tools.archive_project(pid)
    # Sanity: gone from the default list before restore.
    lr = await project_tools.list_projects()
    assert not any(x["id"] == pid for x in lr.data)

    r = await project_tools.unarchive_project(pid)
    assert r.ok and r.data["status"] == "active"

    lr2 = await project_tools.list_projects()
    assert any(x["id"] == pid and x.get("status") == "active" for x in lr2.data)


@pytest.mark.asyncio
async def test_unarchive_missing_project_errors():
    r = await project_tools.unarchive_project("does-not-exist")
    assert not r.ok
    assert "not found" in (r.error or "")


@pytest.mark.asyncio
async def test_clone_copies_intake_json():
    """Clone seeds intake.json (and brief / md) so the intake editor can
    re-hydrate the form on the cloned project."""
    src = await project_tools.create_project(name="CloneSrc")
    src_id = src.data["id"]
    await artifact_tools.write_artifact(src_id, "discovery/intake.json", '{"project": {"name": "CloneSrc"}}')
    await artifact_tools.write_artifact(src_id, "discovery/discovery-brief.yaml", "project_name: CloneSrc\n")
    await artifact_tools.write_artifact(src_id, "discovery/intake.md", "**Project name:** CloneSrc")

    r = await project_tools.clone_project(src_id, new_name="CloneTarget")
    assert r.ok, r.error
    assert r.data["intake_seeded"] is True
    assert r.data["brief_seeded"] is True

    new_id = r.data["clone"]["id"]
    # The clone's discovery inputs MUST carry the clone's name, not the source's —
    # otherwise the intake editor re-hydrates the source name and the user's
    # explicit " (copy)" suffix is silently lost on the next save.
    import json
    intake = await artifact_tools.read_artifact(new_id, "discovery/intake.json")
    assert intake.ok
    intake_obj = json.loads(intake.data)
    assert intake_obj["project"]["name"] == "CloneTarget"

    brief = await artifact_tools.read_artifact(new_id, "discovery/discovery-brief.yaml")
    assert brief.ok and "project_name: CloneTarget" in brief.data

    md = await artifact_tools.read_artifact(new_id, "discovery/intake.md")
    assert md.ok and "**Project name:** CloneTarget" in md.data


@pytest.mark.asyncio
async def test_clone_default_new_name_gets_copy_suffix():
    """When the user accepts the default Clone name (input pre-populated with
    "(copy)"), the suffix must reach the project entry, intake.json, brief.yaml,
    and intake.md so everything is consistent."""
    src = await project_tools.create_project(name="Foo")
    src_id = src.data["id"]
    await artifact_tools.write_artifact(src_id, "discovery/intake.json", '{"project": {"name": "Foo"}}')

    # Frontend pre-populates name as `${source.name} (copy)`; pass that exact value.
    r = await project_tools.clone_project(src_id, new_name="Foo (copy)")
    assert r.ok
    assert r.data["clone"]["name"] == "Foo (copy)"
    new_id = r.data["clone"]["id"]
    import json
    intake = json.loads((await artifact_tools.read_artifact(new_id, "discovery/intake.json")).data)
    assert intake["project"]["name"] == "Foo (copy)"


@pytest.mark.asyncio
async def test_delete_removes_project_and_artifacts():
    p = await project_tools.create_project(name="ToDelete")
    pid = p.data["id"]
    await artifact_tools.write_artifact(pid, "discovery/intake.json", '{"x": 1}')

    r = await project_tools.delete_project(pid)
    assert r.ok, r.error
    assert r.data["artifacts_removed"] is True

    # No longer in any list (including include_archived).
    lr = await project_tools.list_projects(include_archived=True)
    assert not any(x["id"] == pid for x in lr.data)

    # Re-reading the deleted artifact should fail (the engagement dir is gone).
    rd = await artifact_tools.read_artifact(pid, "discovery/intake.json")
    assert not rd.ok


@pytest.mark.asyncio
async def test_delete_missing_project_errors():
    r = await project_tools.delete_project("does-not-exist")
    assert not r.ok
    assert "not found" in (r.error or "")


@pytest.mark.asyncio
async def test_delete_clears_active_marker_when_deleting_active():
    p = await project_tools.create_project(name="ActiveDelete")
    pid = p.data["id"]
    await project_tools.switch_active_project(pid)
    assert project_tools.get_active_project_id() == pid

    r = await project_tools.delete_project(pid)
    assert r.ok
    assert project_tools.get_active_project_id() == ""


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
    # Path A consolidation: the live Event Portal provisioning step was
    # renamed from "provisioning" to "event-portal" and is now opt-in via
    # preferences.provision_event_portal. Design-time scope is
    # "event-portal-design" (always-included).
    assert "event-portal" in skipped_steps  # opt-out → skipped
    assert "event-portal-design" in included_steps  # design scope unconditional


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


@pytest.mark.asyncio
async def test_overview_artifacts_count_excludes_meta_and_intake():
    """ARTIFACTS tile counts workflow-PRODUCED deliverables only — not
    meta/* system bookkeeping (decisions.yaml, session.yaml, ...) and not
    discovery/intake.{json,md} (the user's submitted form is an INPUT).

    Without this filter, a freshly-restarted engagement shows 8-9
    "artifacts" — all empty containers — and the user reasonably reports
    that Restart didn't clean up (when in fact it did, the count was lying).
    """
    p = await project_tools.create_project(name="ArtifactsCount")
    eid = p.data["id"]
    # System bookkeeping (should NOT count) — create_project already seeds
    # meta/decisions.yaml etc., so we just need to seed an additional one.
    # Plus the user's intake (INPUT, should not count).
    await artifact_tools.write_artifact(eid, "discovery/intake.json", '{"x": 1}')
    await artifact_tools.write_artifact(eid, "discovery/intake.md", "# intake")
    # Real workflow outputs (SHOULD count). Use canonical paths — the
    # Design phase's per-scope layout is FLAT (`topic-design/…`,
    # `integration/…`), not `design/…`. write_artifact rejects the
    # `design/` prefix as an LLM-hallucination guard, so the test must
    # use the real layout to land artifacts on disk.
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml",
                                        "systems: []\nrequirements: {}\npreferences: {}")
    await artifact_tools.write_artifact(eid, "discovery/discovery-report.md", "# report")
    await artifact_tools.write_artifact(eid, "topic-design/topic-taxonomy.yaml", "topics: []")
    await artifact_tools.write_artifact(eid, "integration/integration-map.yaml", "links: []")
    await artifact_tools.write_artifact(eid, "blueprint/architecture.md", "# arch")

    r = await dashboard_tools.compute_overview_stats(eid)
    # 5 workflow outputs above; meta/* (4 from create_project) + intake.* (2) excluded.
    assert r.data["artifacts_count"] == 5, r.data


# ---------- validation_tools ----------

@pytest.mark.asyncio
async def test_trace_requirements_finds_mention():
    eid = "eng-trace"
    await artifact_tools.write_artifact(eid, "topic-design/x.md",
                                        "## Delivery mode\nWe use guaranteed messaging for orders.")
    brief = {"requirements": {"delivery_mode": "guaranteed"}}
    r = await validation_tools.trace_requirements(eid, brief, ["topic-design/x.md"])
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

    # Native-artifact-block guardrail (#3): every agent must be told to persist
    # via write_artifact/append_artifact, never a fenced artifact block (which
    # SAM routes to a store the engagement can't read — the artifact vanishes).
    low = body.lower()
    assert "fenced" in low and "write_artifact" in body


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
async def test_token_usage_records_and_aggregates_duration():
    """duration_ms is stored when provided and summed over only the rows that
    carry it (timed_calls), so pre-instrumentation rows don't skew the average."""
    eid = "eng-tel-dur"
    await telemetry_tools.record_token_usage(
        eid, agent="SADomainAgent", model="m1",
        input_tokens=100, output_tokens=10, step_id="design", duration_ms=1200,
    )
    await telemetry_tools.record_token_usage(
        eid, agent="SADomainAgent", model="m1",
        input_tokens=200, output_tokens=20, step_id="design", duration_ms=800,
    )
    # A row WITHOUT a duration (pre-instrumentation / dropped measurement).
    await telemetry_tools.record_token_usage(
        eid, agent="SADomainAgent", model="m1",
        input_tokens=50, output_tokens=5, step_id="design",
    )
    r = await telemetry_tools.read_token_usage(eid, group_by="agent")
    assert r.ok
    row = {x["key"]: x for x in r.data["rows"]}["SADomainAgent"]
    assert row["duration_ms"] == 2000      # 1200 + 800; the untimed row contributes 0
    assert row["timed_calls"] == 2         # only the two timed rows
    assert row["calls"] == 3               # all three count toward token totals


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


@pytest.mark.asyncio
async def test_record_token_usage_writes_under_user_namespace_when_user_id_set(tmp_path):
    """The SAM after_model_callback runs outside the auth middleware's
    contextvar, so the writer must accept user_id and bind scoped_user
    itself. Without this, telemetry lands at <root>/<eid>/... while every
    other artifact lives at <root>/users/<uid>/<eid>/... — and the Usage
    page (which reads under the authenticated namespace) shows zeros.
    """
    from solace_architect_core._user_context import scoped_user
    root = os.environ["SA_STORAGE_ROOT"]
    eid = "eng-scoped-1"
    uid = "u-abc-123"

    # With user_id → writes under users/<uid>/<eid>/...
    r = await telemetry_tools.record_token_usage(
        eid, agent="SADiscoveryAgent", model="m",
        input_tokens=10, output_tokens=5, user_id=uid,
    )
    assert r.ok
    assert (tmp_path / "artifacts" / "users" / uid / eid / "meta" / "telemetry" / "llm-calls.jsonl").exists()
    assert not (tmp_path / "artifacts" / eid / "meta" / "telemetry" / "llm-calls.jsonl").exists()

    # Without user_id → falls back to legacy unscoped path (preserves CLI/test back-compat)
    r = await telemetry_tools.record_token_usage(
        "eng-anon", agent="SADiscoveryAgent", model="m",
        input_tokens=10, output_tokens=5,
    )
    assert r.ok
    assert (tmp_path / "artifacts" / "eng-anon" / "meta" / "telemetry" / "llm-calls.jsonl").exists()

    # The reader under scoped_user(uid) sees the user-scoped data; outside, it doesn't.
    with scoped_user(uid):
        r = await telemetry_tools.read_token_usage(eid, group_by="agent")
        assert r.ok
        assert r.data["totals"]["calls"] == 1
        assert r.data["totals"]["total_tokens"] == 15

    r = await telemetry_tools.read_token_usage(eid, group_by="agent")
    assert r.ok
    assert r.data["totals"]["calls"] == 0


@pytest.mark.asyncio
async def test_record_llm_call_telemetry_forwards_user_id_to_writer(tmp_path):
    """The patch layer parses user_id from the [Active engagement: ...]
    header and threads it through record_llm_call_telemetry. Verify the
    user_id keyword survives the call chain into record_token_usage so
    the file lands at the user-scoped path.
    """
    class _Usage:
        prompt_token_count = 7
        candidates_token_count = 3
        prompt_tokens_details = None

    class _LlmResponse:
        usage_metadata = _Usage()
        model = "claude-test"

    eid = "eng-uid-pass-through"
    uid = "u-xyz-999"

    r = await agent_callbacks.record_llm_call_telemetry(
        llm_response=_LlmResponse(),
        agent="SATestAgent",
        engagement_id=eid,
        user_id=uid,
    )
    assert r.ok
    assert (tmp_path / "artifacts" / "users" / uid / eid / "meta" / "telemetry" / "llm-calls.jsonl").exists()
    # And not under the unscoped fallback
    assert not (tmp_path / "artifacts" / eid / "meta" / "telemetry" / "llm-calls.jsonl").exists()


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
async def test_set_step_status_preserves_scope_progress():
    """set_step_status must NOT clobber scope_progress written earlier the same
    turn. The agent records scope progress, then calls set_step_status at
    end-of-turn (Completion-status rule); if the latter replaced the whole step
    entry, scope_progress.next was lost and Auto-mode advance re-ran completed
    scopes. This is the real-world order (the reverse of the test above)."""
    eid = "scope-eng-step-preserve"
    # Record scope progress FIRST (mid-turn, after a scope completes).
    await lifecycle_tools.record_scope_progress(
        engagement_id=eid, step="design",
        current_scope="broker-select", status="DONE",
        next_scope="protocol-select",
        scopes_done=["topic-design", "broker-select"],
    )
    # THEN the end-of-turn Completion-status write.
    await lifecycle_tools.set_step_status(
        engagement_id=eid, step="design", status="NEEDS_CONTEXT",
        note="broker-select complete; protocol-select next", agent="SADomainAgent",
    )
    status = await lifecycle_tools.get_engagement_status(engagement_id=eid)
    entry = status.data["steps"]["design"]
    assert entry["status"] == "NEEDS_CONTEXT"
    assert entry["note"] == "broker-select complete; protocol-select next"
    # The scope pointer must survive the status write.
    assert entry["scope_progress"]["current"] == "broker-select"
    assert entry["scope_progress"]["next"] == "protocol-select"
    assert entry["scope_progress"]["done"] == ["topic-design", "broker-select"]


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


def test_cost_for_row_matches_published_claude_sonnet_pricing():
    """Lock in published Anthropic prices for claude-sonnet-4-5 — $3/M
    input, $15/M output, $0.30/M cache-read. Catches a bad price-table
    edit (off-by-decimal-place is the classic risk).
    """
    from solace_architect_core._model_prices import cost_for_row
    c = cost_for_row("claude-sonnet-4-5",
                     input_tokens=1_000_000, output_tokens=1_000_000,
                     cached_input_tokens=0)
    assert c is not None
    assert abs(c["input_cost_usd"]  - 3.00) < 1e-6, c
    assert abs(c["output_cost_usd"] - 15.00) < 1e-6, c
    assert abs(c["total_cost_usd"]  - 18.00) < 1e-6, c
    # Cache-read discount applies to cached portion only.
    c2 = cost_for_row("claude-sonnet-4-5",
                      input_tokens=1_000_000, output_tokens=0,
                      cached_input_tokens=500_000)
    # 500k fresh @ $3/M + 500k cached @ $0.30/M = $1.50 + $0.15 = $1.65
    assert abs(c2["input_cost_usd"] - 1.65) < 1e-6, c2


def test_cost_for_row_falls_back_to_env_default_for_unknown_model(monkeypatch):
    """Legacy ledger rows have model=='unknown' (pre PEP-563-fix). The
    SA_DEFAULT_LLM_MODEL env var lets historical rows still get cost
    numbers retroactively.
    """
    from solace_architect_core._model_prices import cost_for_row
    monkeypatch.setenv("SA_DEFAULT_LLM_MODEL", "claude-sonnet-4-5")
    c = cost_for_row("unknown",
                     input_tokens=1_000_000, output_tokens=1_000_000,
                     cached_input_tokens=0)
    assert c is not None and abs(c["total_cost_usd"] - 18.00) < 1e-6, c
    # Without the env var, unknown stays unknown.
    monkeypatch.delenv("SA_DEFAULT_LLM_MODEL", raising=False)
    assert cost_for_row("unknown", 1_000_000, 1_000_000, 0) is None


@pytest.mark.asyncio
async def test_record_scope_progress_coerces_json_string_scopes_done():
    """Regression for the 2026-05-21 PEP-563 bug: when LiteLLM passes
    scopes_done as a JSON-encoded STRING (which it sometimes does instead
    of a native list), the @coerce_args decorator must JSON-parse it.
    Pre-fix: ``from __future__ import annotations`` left the param
    annotation as the string ``"Optional[list]"`` at runtime, so
    ``_is_list_annotation`` failed the type check and the decorator
    silently skipped coercion. The function body then ran
    ``[str(s) for s in scopes_done]`` against the raw string, producing
    a list of CHARACTERS — visible in the wild as scope_progress.done
    looking like ``['[', '"', 'e', 'v', 'e', 'n', 't', ...]``.

    Fix: _arg_coercion now uses typing.get_type_hints() which resolves
    string annotations into real types.
    """
    r = await lifecycle_tools.record_scope_progress(
        engagement_id="scope-pep563-eng", step="design",
        current_scope="event-delivery-characteristics", status="DONE",
        next_scope="broker-select",
        # JSON-encoded string — the LiteLLM-misbehaving shape.
        scopes_done='["event-delivery-characteristics"]',
    )
    assert r.ok, r.error
    from solace_architect_core._storage import read_yaml
    data = read_yaml("scope-pep563-eng", "meta/engagement-status.yaml")
    done = data["steps"]["design"]["scope_progress"]["done"]
    assert done == ["event-delivery-characteristics"], (
        f"expected a 1-element list of scope names; "
        f"got list-of-chars (decorator regression): {done}"
    )


# ---------- lifecycle_tools.set_step_status — timing instrumentation ----------

@pytest.mark.asyncio
async def test_set_step_status_clocks_user_wait_sec_on_needs_context_block(monkeypatch):
    """A step that goes IN_PROGRESS → NEEDS_CONTEXT → IN_PROGRESS → DONE
    must accumulate user_wait_sec from the NEEDS_CONTEXT block, and
    execution_sec must equal wall_sec - user_wait_sec.

    Before this fix user_wait_sec was hardcoded to 0 and execution_sec
    equalled wall_sec — the Stats tile was meaningless. Test pins the
    new behavior with deterministic time via monkeypatch on
    `datetime.now`.
    """
    from datetime import datetime, timedelta, timezone
    from solace_architect_core._storage import read_yaml
    from solace_architect_core.tools import lifecycle_tools as lt

    eid = "timing-eng-1"

    # Monotonic fake clock; tests bump t["sec"] between transitions.
    # Uses timedelta arithmetic so we don't trip on second > 59.
    t = {"sec": 0}
    real_dt = datetime
    _BASE = real_dt(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            base = _BASE if tz is None else _BASE.astimezone(tz)
            return base + timedelta(seconds=t["sec"])

    monkeypatch.setattr(lt, "datetime", _FakeDT)

    # t=0 — step starts (set IN_PROGRESS via set_step_status). The
    # status's started_at is recorded by _now_iso which uses
    # datetime.now() (patched), so wall-time math stays in our control.
    await lt.set_step_status(eid, step="discovery", status="NEEDS_CONTEXT", agent="SADiscoveryAgent")
    # Step enters NEEDS_CONTEXT immediately (started_at = NOW). t still 0.
    # User waits for 30s before answering.
    t["sec"] += 30
    await lt.set_step_status(eid, step="discovery", status="NEEDS_CONTEXT", agent="SADiscoveryAgent")
    # Self-transition NEEDS_CONTEXT → NEEDS_CONTEXT must NOT close+reopen
    # the block (would over-count wait). Verified by elapsed-time math below.
    t["sec"] += 10  # 40s of NEEDS_CONTEXT total now
    # User answers; agent goes back to IN_PROGRESS for compute.
    await lt.set_step_status(eid, step="discovery", status="NOT_STARTED")  # any non-NEEDS_CONTEXT closes the block
    # Wait closed: user_wait_sec should be 40 (30 + 10) — single block.
    session = read_yaml(eid, "meta/session.yaml") or {}
    assert session["timing_data"]["discovery"]["user_wait_sec"] == 40, session

    # Agent does another 20s of compute, asks ANOTHER question, user waits 15s.
    t["sec"] += 20
    await lt.set_step_status(eid, step="discovery", status="NEEDS_CONTEXT")
    t["sec"] += 15
    await lt.set_step_status(eid, step="discovery", status="DONE", note="brief written")

    timing = read_yaml(eid, "meta/session.yaml")["timing_data"]["discovery"]
    # Total wall = 30 + 10 + 20 + 15 = 75s. Wait blocks total = 40 + 15 = 55s.
    # Execution = wall - wait = 75 - 55 = 20s (the compute window between blocks).
    assert timing["wall_sec"] == 75, timing
    assert timing["user_wait_sec"] == 55, timing
    assert timing["execution_sec"] == 20, timing
    # _blocked_at must be dropped on finalize.
    assert "_blocked_at" not in timing, timing


@pytest.mark.asyncio
async def test_set_step_status_blocked_does_not_count_as_user_wait(monkeypatch):
    """BLOCKED is an agent-side block, not a user-wait. A step that
    transitions IN_PROGRESS → BLOCKED → IN_PROGRESS → DONE should
    register zero user_wait_sec.
    """
    from datetime import datetime, timedelta, timezone
    from solace_architect_core._storage import read_yaml
    from solace_architect_core.tools import lifecycle_tools as lt

    eid = "timing-eng-2"
    t = {"sec": 0}
    real_dt = datetime
    _BASE = real_dt(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            base = _BASE if tz is None else _BASE.astimezone(tz)
            return base + timedelta(seconds=t["sec"])

    monkeypatch.setattr(lt, "datetime", _FakeDT)

    await lt.set_step_status(eid, step="design", status="BLOCKED")
    t["sec"] += 50
    await lt.set_step_status(eid, step="design", status="DONE")

    timing = read_yaml(eid, "meta/session.yaml")["timing_data"]["design"]
    assert timing["user_wait_sec"] == 0, timing
    assert timing["execution_sec"] == 50, timing
    assert timing["wall_sec"] == 50, timing


# ---------- session_tools.write_checkpoint / read_checkpoint / clear_checkpoint ----------

@pytest.mark.asyncio
async def test_checkpoint_round_trip_per_step():
    """write_checkpoint then read_checkpoint round-trips the agent's
    state dict verbatim, and checkpoints are isolated per step.
    """
    from solace_architect_core.tools import session_tools

    eid = "ckpt-eng-1"

    # Empty initial read returns the shape-stable default.
    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.ok
    assert r.data == {"state": {}, "updated_at": None, "by_agent": ""}

    state = {"sections_done": ["systems", "requirements"], "last_question_id": "Q5"}
    r = await session_tools.write_checkpoint(
        eid, step="discovery", state=state, by_agent="SADiscoveryAgent",
    )
    assert r.ok
    assert r.data["state"] == state
    assert r.data["by_agent"] == "SADiscoveryAgent"
    assert r.data["updated_at"]

    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.ok
    assert r.data["state"] == state
    assert r.data["by_agent"] == "SADiscoveryAgent"

    # A different step is isolated — empty until written.
    r = await session_tools.read_checkpoint(eid, step="design")
    assert r.ok and r.data["state"] == {}

    # Writing Design's checkpoint doesn't disturb Discovery's.
    await session_tools.write_checkpoint(
        eid, step="design", state={"scopes_complete": ["topic-design"]},
        by_agent="SADomainAgent",
    )
    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.data["state"] == state, "Design write must not have touched Discovery"


@pytest.mark.asyncio
async def test_checkpoint_replace_is_wholesale():
    """write_checkpoint replaces the checkpoint for that step
    wholesale — agents pass the full current state, not a delta. A
    merge semantic would silently leak stale keys from prior turns.
    """
    from solace_architect_core.tools import session_tools

    eid = "ckpt-eng-2"
    await session_tools.write_checkpoint(eid, step="discovery", state={"a": 1, "b": 2})
    await session_tools.write_checkpoint(eid, step="discovery", state={"c": 3})
    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.data["state"] == {"c": 3}, "second write must wholesale-replace, not merge"


@pytest.mark.asyncio
async def test_clear_checkpoint_drops_just_that_step():
    """clear_checkpoint removes the named step's entry; other steps
    survive. Returns removed=False when there was nothing to drop.
    """
    from solace_architect_core.tools import session_tools

    eid = "ckpt-eng-3"
    await session_tools.write_checkpoint(eid, step="discovery", state={"x": 1})
    await session_tools.write_checkpoint(eid, step="design",    state={"y": 2})

    r = await session_tools.clear_checkpoint(eid, step="discovery")
    assert r.ok and r.data == {"step": "discovery", "removed": True}

    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.data["state"] == {}
    r = await session_tools.read_checkpoint(eid, step="design")
    assert r.data["state"] == {"y": 2}

    # Clearing a step with no checkpoint is a no-op (removed=False).
    r = await session_tools.clear_checkpoint(eid, step="review")
    assert r.ok and r.data == {"step": "review", "removed": False}


@pytest.mark.asyncio
async def test_checkpoint_input_validation():
    """Empty step rejected with a clear ToolResult error. Non-dict
    state is caught upstream by @coerce_args (TypeError) — that's also
    a rejection, just at a different layer.
    """
    from solace_architect_core.tools import session_tools

    r = await session_tools.write_checkpoint("eid", step="", state={})
    assert not r.ok and "step" in r.error

    # @coerce_args raises TypeError before our isinstance check fires —
    # also a "rejected" signal, just at a different layer.
    with pytest.raises(TypeError):
        await session_tools.write_checkpoint("eid", step="discovery", state="not a dict")

    r = await session_tools.read_checkpoint("eid", step="")
    assert not r.ok and "step" in r.error

    r = await session_tools.clear_checkpoint("eid", step="")
    assert not r.ok and "step" in r.error


@pytest.mark.asyncio
async def test_reset_discovery_clears_checkpoint():
    """Restart Discovery must drop the resume checkpoint, else a fresh
    run skips work based on the prior run's stale hints.
    """
    from solace_architect_core.tools import session_tools

    # Reinstall guarded — import-time symbol resolution against possibly-stale
    # editable install. Re-import on each test if needed.
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "ckpt-reset-eng"
    await session_tools.write_checkpoint(
        eid, step="discovery", state={"sections_done": ["systems"]},
        by_agent="SADiscoveryAgent",
    )
    # Sanity: checkpoint exists.
    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.data["state"] == {"sections_done": ["systems"]}

    await reset_discovery(eid)

    # Restart wiped the checkpoint.
    r = await session_tools.read_checkpoint(eid, step="discovery")
    assert r.data["state"] == {}, "Restart Discovery must clear the checkpoint"


@pytest.mark.asyncio
async def test_telemetry_records_activity_without_payloads(tmp_path, monkeypatch):
    """LLM telemetry now records the agent's activity (tool calls + status text,
    the chat-pill content) alongside tokens — but NEVER bulk payloads like a
    write_artifact body."""
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    from types import SimpleNamespace as NS
    from solace_architect_core import agent_callbacks as ac
    from solace_architect_core._storage import read_jsonl
    resp = NS(
        usage_metadata=NS(prompt_token_count=2100, candidates_token_count=80,
                          prompt_tokens_details=None),
        content=NS(parts=[
            NS(function_call=NS(name="read_artifact",
                                args={"artifact_name": "protocol-select/protocol-map.yaml"}), text=None),
            NS(function_call=None, text="Reading prior decisions"),
            NS(function_call=NS(name="write_artifact",
                                args={"artifact_name": "topic-design/topic-taxonomy.yaml",
                                      "content": "Z" * 5000}), text=None),
        ]),
    )
    await ac.record_llm_call_telemetry(llm_response=resp, agent="SADomainAgent",
                                       engagement_id="act-eng", model="m")
    rows = read_jsonl("act-eng", "meta/telemetry/llm-calls.jsonl")
    act = rows[-1]["activity"]
    assert {"tool": "read_artifact", "args": "artifact_name=protocol-select/protocol-map.yaml"} in act
    assert {"text": "Reading prior decisions"} in act
    # write_artifact captured by name only — the 5000-char body is NOT stored.
    blob = __import__("json").dumps(rows[-1])
    assert "topic-design/topic-taxonomy.yaml" in blob
    assert "ZZZZ" not in blob


def test_extract_usage_reads_cached_tokens_across_provider_dialects():
    """A prompt-cache hit must be captured regardless of which usage shape the
    gateway returns — so caching is visible the moment it's enabled upstream."""
    from types import SimpleNamespace as NS
    from solace_architect_core import agent_callbacks as ac
    # OpenAI/Gemini shape: prompt_tokens_details.cached_tokens
    u1 = NS(prompt_token_count=1000, candidates_token_count=50,
            prompt_tokens_details=NS(cached_tokens=600))
    assert ac._extract_usage(NS(usage_metadata=u1)) == (1000, 50, 600)
    # Anthropic-native shape: cache_read_input_tokens on the usage object.
    u2 = NS(prompt_token_count=1000, candidates_token_count=50,
            prompt_tokens_details=None, cache_read_input_tokens=700)
    assert ac._extract_usage(NS(usage_metadata=u2)) == (1000, 50, 700)
    # Vertex/Gemini shape: cached_content_token_count.
    u3 = NS(prompt_token_count=1000, candidates_token_count=50,
            prompt_tokens_details=None, cached_content_token_count=400)
    assert ac._extract_usage(NS(usage_metadata=u3)) == (1000, 50, 400)
    # No caching anywhere → 0 (current production reality).
    u4 = NS(prompt_token_count=1000, candidates_token_count=50, prompt_tokens_details=None)
    assert ac._extract_usage(NS(usage_metadata=u4)) == (1000, 50, 0)
