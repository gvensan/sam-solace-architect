"""Route registration contract.

The plugin must expose the documented HTTP surface (v2spec §6.1 + §6.2).
These tests don't require a running SAM — they exercise the route table
and the underlying handlers against the file-backed storage.
"""

import pytest

from solace_architect_webui_entrypoint.routes.api import API_ROUTES


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


def test_api_routes_table_is_a_nonempty_list():
    assert isinstance(API_ROUTES, list)
    assert len(API_ROUTES) >= 20, f"expected ≥20 routes, got {len(API_ROUTES)}"


def test_every_route_is_well_formed():
    """Each route is (method, path, async-callable)."""
    for method, path, handler in API_ROUTES:
        assert method in ("GET", "POST", "PUT", "DELETE", "PATCH")
        assert path.startswith("/api/") or path.startswith("/reports/")
        assert callable(handler)


def test_required_dashboard_endpoints_present():
    paths = {p for _, p, _ in API_ROUTES}
    required = [
        "/api/projects",
        "/api/engagements/{engagement_id}/overview",
        "/api/engagements/{engagement_id}/timeline",
        "/api/engagements/{engagement_id}/decisions",
        "/api/engagements/{engagement_id}/open-items",
        "/api/engagements/{engagement_id}/artifacts",
        "/api/engagements/{engagement_id}/active-step",
        "/api/intake/preview",
        "/api/intake/submit",
    ]
    for r in required:
        assert r in paths, f"missing required route: {r}"


def test_method_for_known_routes():
    by_path = {(p, m) for m, p, _ in API_ROUTES}
    assert ("/api/projects", "POST") in by_path                              # create
    assert ("/api/projects", "GET") in by_path                               # list
    assert ("/api/intake/submit", "POST") in by_path
    assert ("/api/engagements/{engagement_id}/overview", "GET") in by_path


@pytest.mark.asyncio
async def test_list_projects_returns_list_even_when_empty():
    from solace_architect_webui_entrypoint.routes.api import list_engagements
    r = await list_engagements()
    assert isinstance(r, list)


@pytest.mark.asyncio
async def test_create_engagement_then_list_returns_it():
    from solace_architect_webui_entrypoint.routes.api import create_engagement, list_engagements
    p = await create_engagement(name="Pilot Test")
    assert p["id"]
    listed = await list_engagements()
    assert any(x["id"] == p["id"] for x in listed)


@pytest.mark.asyncio
async def test_intake_preview_returns_routing_decision():
    from solace_architect_webui_entrypoint.routes.api import intake_preview
    brief = {"systems": [{"name": "API"}],
             "requirements": {"topology": "single-site", "delivery_mode": "guaranteed",
                              "processing_guarantee": "at-least-once"},
             "existing_messaging": "",
             "preferences": {"provision_event_portal": False}}
    r = await intake_preview(partial_intake=brief)
    assert "included_steps" in r
    assert "skipped_steps" in r
    # event-portal (live provisioning) is opt-in → skipped when preference=false
    assert any(s["step"] == "event-portal" for s in r["skipped_steps"])


@pytest.mark.asyncio
async def test_intake_submit_creates_project_and_writes_brief():
    """intake_submit takes **kwargs (the adapter spreads body keys), so we mirror that here."""
    from solace_architect_webui_entrypoint.routes.api import intake_submit
    r = await intake_submit(
        project_name="Pilot E2E",
        project_type="new-build",
        systems=[{"name": "API"}],
        requirements={"topology": "single-site", "delivery_mode": "guaranteed"},
        preferences={"provision_event_portal": False},
    )
    assert r["engagement_id"]
    # Verify brief is on disk
    from solace_architect_core._storage import read_text
    brief = read_text(r["engagement_id"], "discovery/discovery-brief.yaml")
    assert "Pilot E2E" in brief
    # And the lossless JSON snapshot
    intake_json = read_text(r["engagement_id"], "discovery/intake.json")
    assert "Pilot E2E" in intake_json


@pytest.mark.asyncio
async def test_reset_design_cascades_to_review_state():
    """Restart Design must wipe Review state — findings, reviews/*.md, review
    step status, and review-deferred open-items. Without this cascade, a
    re-run of Design would leave stale findings pointing at deleted
    artifacts. Lock this behavior in with a focused test.
    """
    from solace_architect_core.tools import (
        artifact_tools, decision_tools, lifecycle_tools,
    )
    from solace_architect_webui_entrypoint.routes.api import reset_design

    eid = "cascade-eng"

    # Seed design + review state.
    await artifact_tools.write_artifact(
        eid, "topic-design/topic-taxonomy.yaml", "topics: []",
    )
    await artifact_tools.write_artifact(
        eid, "reviews/architect-review.md", "# Architecture Review\n",
    )
    await artifact_tools.write_artifact(
        eid, "reviews/review-summary.md", "# Review Summary\n",
    )
    await decision_tools.record_finding(
        eid, severity="critical", description="seed",
        affected_artifact="topic-design/topic-taxonomy.yaml",
        recommendation="fix it", source_agent="SAArchitectReviewerAgent",
    )
    await lifecycle_tools.set_step_status(
        eid, step="design", status="DONE", agent="SADomainAgent",
    )
    await lifecycle_tools.set_step_status(
        eid, step="review", status="DONE_WITH_CONCERNS",
        agent="SAOrchestratorAgent",
    )
    # Add a review-deferred open-item (the side-effect of deferring a finding).
    await decision_tools.record_open_item(
        eid, severity="advisory", source="review-deferred",
        description="deferred F1",
    )

    # Trigger reset_design.
    result = await reset_design(eid)

    # Findings emptied.
    findings_after = (await decision_tools.read_findings(eid)).data
    assert findings_after == [], f"expected no findings after cascade, got {findings_after}"
    # reviews/*.md unlinked.
    review_artifacts_after = (await artifact_tools.list_artifacts(eid, category="reviews")).data
    assert not review_artifacts_after, f"expected no reviews/* artifacts, got {review_artifacts_after}"
    # review step status cleared.
    status_after = (await lifecycle_tools.get_engagement_status(eid)).data
    assert "review" not in status_after["steps"], status_after["steps"]
    # Design step also cleared (existing behavior preserved).
    assert "design" not in status_after["steps"], status_after["steps"]
    # review-deferred open-item superseded.
    items = (await decision_tools.read_open_items(eid, source="review-deferred")).data
    assert all(i["status"] == "superseded" for i in items), items
    # Response payload exposes the counts.
    assert result["findings_cleared"] == 1
    assert result["review_step_cleared"] is True
    assert any("reviews/" in a for a in result["removed_artifacts"]), result


@pytest.mark.asyncio
async def test_reset_design_cascades_to_all_downstream_phases():
    """Restart Design must wipe Validation + Event Portal + Blueprint state
    too, not just Review. Without this cascade, the user could re-run Design
    and find stale blueprint packages / event-portal records pointing at
    deleted scope artifacts. The cascade order is review → validation →
    event-portal → blueprint.
    """
    from solace_architect_core.tools import (
        artifact_tools, decision_tools, lifecycle_tools,
    )
    from solace_architect_webui_entrypoint.routes.api import reset_design

    eid = "cascade-full-eng"

    # Seed design + every downstream phase.
    await artifact_tools.write_artifact(eid, "topic-design/topic-taxonomy.yaml", "topics: []")
    await artifact_tools.write_artifact(eid, "reviews/architect-review.md", "# Review")
    await artifact_tools.write_artifact(eid, "validation/validation-report.md", "# Validation")
    await artifact_tools.write_artifact(eid, "event-portal/provisioned.yaml", "domains: []")
    await artifact_tools.write_artifact(eid, "blueprint/architecture.md", "# Architecture")
    await artifact_tools.write_artifact(eid, "exports/engagement-package.zip", "(zip)")
    for step in ("design", "review", "validation", "event-portal", "blueprint"):
        await lifecycle_tools.set_step_status(
            eid, step=step, status="DONE", agent="SA{}Agent".format(step.replace("-", "").capitalize()),
        )
    # Seed open-items from each cascading source.
    for source in ("domain", "review-deferred", "validation", "event-portal"):
        await decision_tools.record_open_item(
            eid, severity="advisory", source=source,
            description=f"seeded {source} item",
        )

    result = await reset_design(eid)

    # Every downstream phase's artifacts gone.
    remaining = (await artifact_tools.list_artifacts(eid)).data or []
    assert not any(a.startswith(("topic-design/", "reviews/", "validation/",
                                  "event-portal/", "blueprint/", "exports/"))
                    for a in remaining), remaining

    # Every downstream phase's step status cleared.
    status_after = (await lifecycle_tools.get_engagement_status(eid)).data
    for step in ("design", "review", "validation", "event-portal", "blueprint"):
        assert step not in status_after["steps"], f"{step} not cleared: {status_after['steps']}"

    # Every source's open-items superseded.
    for source in ("domain", "review-deferred", "validation", "event-portal"):
        items = (await decision_tools.read_open_items(eid, source=source)).data
        assert all(i["status"] == "superseded" for i in items), (source, items)

    # Response payload reports the full cascade.
    assert "validation" in result["cascaded_steps"]
    assert "event-portal" in result["cascaded_steps"]
    assert "blueprint" in result["cascaded_steps"]


@pytest.mark.asyncio
async def test_reset_discovery_cascades_through_full_lifecycle():
    """Restart Discovery wipes EVERY downstream phase since they all derive
    from the brief. Verifies the same cascade helper runs end-to-end.
    """
    from solace_architect_core.tools import (
        artifact_tools, decision_tools, lifecycle_tools,
    )
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "cascade-from-discovery-eng"

    # Seed every phase including discovery itself.
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml", "topics: []")
    await artifact_tools.write_artifact(eid, "topic-design/topic-taxonomy.yaml", "topics: []")
    await artifact_tools.write_artifact(eid, "reviews/architect-review.md", "# R")
    await artifact_tools.write_artifact(eid, "validation/validation-report.md", "# V")
    await artifact_tools.write_artifact(eid, "blueprint/architecture.md", "# B")
    for step in ("discovery", "design", "review", "validation", "blueprint"):
        await lifecycle_tools.set_step_status(
            eid, step=step, status="DONE", agent=f"SA{step.capitalize()}Agent",
        )

    result = await reset_discovery(eid)

    # Every downstream phase artifact gone (discovery folder may have other
    # files like intake.json which reset_discovery doesn't touch on purpose,
    # so we only assert the design+ phases are wiped).
    remaining = (await artifact_tools.list_artifacts(eid)).data or []
    assert not any(a.startswith(("topic-design/", "reviews/", "validation/", "blueprint/"))
                    for a in remaining), remaining

    # Step statuses for design+ are gone.
    status_after = (await lifecycle_tools.get_engagement_status(eid)).data
    for step in ("design", "review", "validation", "blueprint", "discovery"):
        assert step not in status_after["steps"], f"{step} not cleared: {status_after['steps']}"

    # Cascade scope covers design through blueprint, including the
    # event-portal step between validation and blueprint.
    assert set(result["cascaded_steps"]) == {
        "design", "review", "validation", "event-portal", "blueprint",
    }


@pytest.mark.asyncio
async def test_reset_discovery_drops_phase_decisions_but_keeps_orchestrator():
    """Restart wipes phase-authored decisions; orchestrator flow decisions
    survive. Counts come back in the response payload.
    """
    from solace_architect_core.tools import decision_tools
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "decisions-restart-eng"

    # Record one decision per phase + one orchestrator decision.
    seed = [
        ("SADiscoveryAgent", "discovery context"),
        ("SADomainAgent", "design context"),
        ("SAArchitectReviewerAgent", "arch review context"),
        ("SADeveloperReviewerAgent", "dev review context"),
        ("SAValidationAgent", "validation context"),
        ("SAEventPortalAgent", "ep context"),
        ("SABlueprintAgent", "blueprint context"),
        ("SAOrchestratorAgent", "orchestrator flow context"),
    ]
    for agent, ctx in seed:
        await decision_tools.record_decision(
            eid, context=ctx, recommendation="r", selected="s",
            rationale="r", source_agent=agent,
        )

    result = await reset_discovery(eid)

    # Seven phase-authored decisions wiped; one orchestrator decision survives.
    assert result["decisions_cleared"] == 7, result
    remaining = (await decision_tools.read_decisions(eid)).data
    assert len(remaining) == 1, remaining
    assert remaining[0]["source_agent"] == "SAOrchestratorAgent"
    assert remaining[0]["context"] == "orchestrator flow context"
