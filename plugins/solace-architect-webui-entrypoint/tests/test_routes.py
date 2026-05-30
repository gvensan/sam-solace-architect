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
async def test_intake_submit_propagates_execution_mode_auto_to_session():
    """User picks Auto at intake → session.yaml.execution_mode = 'auto'.
    Before this fix, the session always initialised as 'interactive' and
    the intake-time choice was silently discarded.
    """
    from solace_architect_core.tools import session_tools
    from solace_architect_webui_entrypoint.routes.api import intake_submit

    r = await intake_submit(
        project_name="Auto Mode Pilot",
        project_type="new-build",
        systems=[{"name": "API"}],
        requirements={"topology": "single-site"},
        preferences={"provision_event_portal": False, "execution_mode": "auto"},
    )
    assert r["engagement_id"]

    session = (await session_tools.read_session_state(r["engagement_id"])).data
    assert session["execution_mode"] == "auto", session


@pytest.mark.asyncio
async def test_intake_submit_defaults_to_interactive_when_preference_absent():
    """Form doesn't include preferences.execution_mode → session keeps
    the legacy 'interactive' default. Guards against accidental flips.
    """
    from solace_architect_core.tools import session_tools
    from solace_architect_webui_entrypoint.routes.api import intake_submit

    r = await intake_submit(
        project_name="Default Mode Pilot",
        project_type="new-build",
        systems=[{"name": "API"}],
        requirements={"topology": "single-site"},
        preferences={"provision_event_portal": False},
    )
    session = (await session_tools.read_session_state(r["engagement_id"])).data
    assert session["execution_mode"] == "interactive", session


@pytest.mark.asyncio
async def test_intake_submit_rejects_garbage_execution_mode():
    """Unknown execution_mode value → falls back to 'interactive' (the
    safer default — the user always gets to confirm decisions). Avoids
    persisting a bogus mode that no downstream code knows how to handle.
    """
    from solace_architect_core.tools import session_tools
    from solace_architect_webui_entrypoint.routes.api import intake_submit

    r = await intake_submit(
        project_name="Garbage Mode Pilot",
        project_type="new-build",
        systems=[{"name": "API"}],
        requirements={"topology": "single-site"},
        preferences={"provision_event_portal": False, "execution_mode": "yolo"},
    )
    session = (await session_tools.read_session_state(r["engagement_id"])).data
    assert session["execution_mode"] == "interactive", session


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
async def test_reset_discovery_wipes_all_engagement_decisions():
    """Restart Discovery clears EVERY decision in meta/decisions.yaml,
    including SAOrchestratorAgent-authored rows. Phase restarts
    (Design / Review / Validation / EP / Blueprint) still preserve
    orchestrator decisions; only a full Discovery restart treats the
    engagement as a clean slate.

    Rationale: with SAOrchestratorAgent as the default chat agent,
    design/EP decisions get recorded under the orchestrator and the
    user-visible "Decisions: N" tile never resets. Matches the
    Discovery-restart full-wipe policy already shipped for telemetry.
    """
    from solace_architect_core.tools import decision_tools
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "decisions-restart-eng"

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

    # All 8 cleared — orchestrator included.
    assert result["decisions_cleared"] == 8, result
    remaining = (await decision_tools.read_decisions(eid)).data
    assert remaining == [], remaining


@pytest.mark.asyncio
async def test_reset_design_preserves_orchestrator_decisions():
    """Inverse contract: phase restarts (here, Design) must NOT touch
    orchestrator decisions — only Discovery restart is a full-engagement
    clean slate. Without this, EVERY restart would wipe cross-cutting
    flow choices, defeating their purpose.
    """
    from solace_architect_core.tools import decision_tools
    from solace_architect_webui_entrypoint.routes.api import reset_design

    eid = "design-restart-preserves-orch"

    await decision_tools.record_decision(
        eid, context="design choice", recommendation="r", selected="s",
        rationale="r", source_agent="SADomainAgent",
    )
    await decision_tools.record_decision(
        eid, context="orchestrator flow choice", recommendation="r", selected="s",
        rationale="r", source_agent="SAOrchestratorAgent",
    )

    await reset_design(eid)

    remaining = (await decision_tools.read_decisions(eid)).data
    assert len(remaining) == 1, remaining
    assert remaining[0]["source_agent"] == "SAOrchestratorAgent"


@pytest.mark.asyncio
async def test_reset_discovery_unlinks_design_folder_files():
    """The cascade must wipe files written to the current ``design/`` layout
    (design/topic-taxonomy.yaml, design/integration/integration-map.yaml,
    etc.), not just the legacy per-scope folders (topic-design/, broker-select/,
    etc.). Before this fix, real engagements showed 17 ARTIFACTS after a
    Restart Discovery — none of the design/ files got wiped because the
    cascade only iterated the legacy folder list.
    """
    from solace_architect_core.tools import artifact_tools
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "design-folder-wipe-eng"

    # Seed the current-layout design files (what real engagements have).
    for name in (
        "design/topic-taxonomy.yaml",
        "design/broker-recommendation.yaml",
        "design/integration/integration-map.yaml",
        "design/protocol-map.yaml",
        # Plus a legacy-layout file to verify both still get wiped.
        "topic-design/legacy-doc.yaml",
        # And the user's submitted intake — the docstring on reset_discovery
        # promises these survive. Without these assertions, a regression
        # that nuked intake.json/intake.md would slip through the test net.
        "discovery/intake.json",
        "discovery/intake.md",
    ):
        body = "topics: []" if name.endswith(".yaml") else "# stub"
        await artifact_tools.write_artifact(eid, name, body)

    await reset_discovery(eid)

    remaining = (await artifact_tools.list_artifacts(eid)).data or []
    design_left = [a for a in remaining if a.startswith(("design/", "topic-design/"))]
    assert design_left == [], f"design files still present after restart: {design_left}"
    # M1 fix: intake artifacts must SURVIVE — they're the user's submitted
    # form and a new Discovery run reads them as source-of-truth.
    assert "discovery/intake.json" in remaining, (
        f"intake.json was wiped — must survive Restart Discovery. remaining={remaining}"
    )
    assert "discovery/intake.md" in remaining, (
        f"intake.md was wiped — must survive Restart Discovery. remaining={remaining}"
    )


@pytest.mark.asyncio
async def test_reset_discovery_wipes_all_engagement_telemetry():
    """Restart Discovery wipes EVERY llm-calls.jsonl row for the engagement,
    including SAOrchestratorAgent rows. Phase restarts (Design / Review /
    Validation / EP / Blueprint) still preserve orchestrator history; only
    a full Discovery restart resets the engagement to a clean slate.

    Rationale: when SAOrchestratorAgent is the default chat agent (post-
    2026-05-21), ~86% of an engagement's tokens land under the orchestrator
    in real usage. Preserving orchestrator rows on Discovery restart
    leaves the Usage tile showing pre-restart numbers and the user
    reports "tokens didn't reset" (matches the user-visible symptom).
    """
    from solace_architect_core.tools import telemetry_tools
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "telemetry-restart-eng"

    seed = [
        ("SADiscoveryAgent", 100),
        ("SADomainAgent", 200),
        ("SAArchitectReviewerAgent", 50),
        ("SADeveloperReviewerAgent", 50),
        ("SAValidationAgent", 80),
        ("SAEventPortalAgent", 40),
        ("SABlueprintAgent", 90),
        ("SAOrchestratorAgent", 30),
    ]
    for agent, tok in seed:
        await telemetry_tools.record_token_usage(
            eid, agent=agent, model="m",
            input_tokens=tok, output_tokens=tok // 10,
        )

    result = await reset_discovery(eid)

    # All 8 rows wiped — orchestrator included.
    assert result["telemetry_rows_cleared"] == 8, result
    remaining = (await telemetry_tools.read_token_usage(eid, group_by="agent")).data
    assert remaining["totals"]["calls"] == 0, remaining
    assert remaining["rows"] == [], remaining


@pytest.mark.asyncio
async def test_reset_design_resets_only_design_and_downstream_telemetry():
    """Restart Design wipes design + downstream (review/validation/EP/
    blueprint) telemetry rows; upstream Discovery rows AND orchestrator
    rows survive.
    """
    from solace_architect_core.tools import telemetry_tools
    from solace_architect_webui_entrypoint.routes.api import reset_design

    eid = "telemetry-design-restart-eng"

    seed = [
        ("SADiscoveryAgent", 100),
        ("SADomainAgent", 200),
        ("SAArchitectReviewerAgent", 50),
        ("SAValidationAgent", 80),
        ("SAEventPortalAgent", 40),
        ("SABlueprintAgent", 90),
        ("SAOrchestratorAgent", 30),
    ]
    for agent, tok in seed:
        await telemetry_tools.record_token_usage(
            eid, agent=agent, model="m",
            input_tokens=tok, output_tokens=tok // 10,
        )

    result = await reset_design(eid)

    # 5 wiped (design + 4 downstream); discovery + orchestrator survive.
    assert result["telemetry_rows_cleared"] == 5, result
    remaining = (await telemetry_tools.read_token_usage(eid, group_by="agent")).data
    survivors = {row["key"] for row in remaining["rows"]}
    assert survivors == {"SADiscoveryAgent", "SAOrchestratorAgent"}, survivors


@pytest.mark.asyncio
async def test_reset_discovery_unlinks_stakeholder_report():
    """Restart Discovery deletes the stakeholder-ready narrative report
    alongside the brief + summary. Without this, the previous Discovery
    run's report.md survives and the next run lands on top of stale
    user-facing copy."""
    from solace_architect_core.tools import artifact_tools
    from solace_architect_webui_entrypoint.routes.api import reset_discovery

    eid = "report-restart-eng"
    for name in (
        "discovery/discovery-brief.yaml",
        "discovery/discovery-summary.md",
        "discovery/discovery-report.md",
        # intake.json must SURVIVE — it's the user's submitted form
        "discovery/intake.json",
    ):
        content = "topics: []" if name.endswith(".yaml") else "# stub"
        await artifact_tools.write_artifact(eid, name, content)

    result = await reset_discovery(eid)

    remaining = (await artifact_tools.list_artifacts(eid, category="discovery")).data or []
    # The three derived artifacts are gone; intake.json survives.
    assert "discovery/discovery-brief.yaml" not in remaining, remaining
    assert "discovery/discovery-summary.md" not in remaining, remaining
    assert "discovery/discovery-report.md" not in remaining, remaining
    assert "discovery/intake.json" in remaining, remaining
    # And the removed-artifacts list reports the deletions.
    removed = set(result.get("removed_artifacts", []))
    assert "discovery/discovery-report.md" in removed, removed


# ----- Design orchestrator (deterministic Design engine) -----

import asyncio

from solace_architect_core._storage import write_yaml, write_text
from solace_architect_core.orchestrator import design_state as ds
from solace_architect_webui_entrypoint.routes.api import design_advance, design_state_view


def _seed_minimal_brief(eid):
    """Greenfield brief with no AI / multi-site / guarantee / existing-messaging,
    so only the always-on design scopes apply (topic-design, broker-select, ...)."""
    write_yaml(eid, "discovery/discovery-brief.yaml", {
        "project": {"type": "greenfield"},
        "landscape": {"systems": [{"name": "orders-service"}]},
        "requirements": {},
    })


def test_design_orchestrator_routes_registered():
    paths = {(p, m) for m, p, _ in API_ROUTES}
    assert ("/api/engagements/{engagement_id}/design/advance", "POST") in paths
    assert ("/api/engagements/{engagement_id}/design/state", "GET") in paths


def test_design_advance_drives_scopes_in_order():
    eid = "orch-eng-1"
    _seed_minimal_brief(eid)

    # First advance: no state yet → init from the plan + dispatch the first scope.
    a1 = asyncio.run(design_advance(eid, mode="auto"))
    assert a1["action"] == "dispatch"
    assert a1["scope"] == "topic-design"
    assert a1["agent"] == "SADomainAgent"
    assert "WORKER MODE" in a1["kickoff"]
    assert "Scope: topic-design" in a1["kickoff"]
    assert a1["done"] == []

    # Worker "completes" topic-design by writing its structured artifact.
    write_text(eid, "topic-design/topic-taxonomy.yaml", "topics: []\n")

    # Next advance: orchestrator detects the artifact on disk → advances.
    a2 = asyncio.run(design_advance(eid, mode="auto", last_scope="topic-design"))
    assert a2["action"] == "dispatch"
    assert a2["scope"] == "broker-select"
    assert "topic-design" in a2["done"]

    view = asyncio.run(design_state_view(eid))
    assert view["exists"] is True
    assert ds.scope_status(view["state"], "topic-design") == ds.DONE


def test_design_advance_failed_attempts_exhaust_budget():
    eid = "orch-eng-2"
    _seed_minimal_brief(eid)
    last = None
    for _ in range(ds.MAX_ATTEMPTS):
        a = asyncio.run(design_advance(eid, mode="auto", last_scope=last, outcome="failed" if last else None))
        assert a["action"] == "dispatch"
        assert a["scope"] == "topic-design"
        last = "topic-design"
    final = asyncio.run(design_advance(eid, mode="auto", last_scope="topic-design", outcome="failed"))
    assert final["action"] == "retry_exhausted"
    assert final["scope"] == "topic-design"


def test_design_advance_question_parks_for_user():
    eid = "orch-eng-3"
    _seed_minimal_brief(eid)
    asyncio.run(design_advance(eid, mode="interactive"))  # dispatch topic-design
    a = asyncio.run(design_advance(eid, mode="interactive", last_scope="topic-design", outcome="question"))
    assert a["action"] == "await_user"
    assert a["scope"] == "topic-design"


def test_design_advance_renders_prose_companion():
    """Phase C: worker writes only the structured YAML; the orchestrator renders
    the .md companion deterministically."""
    from solace_architect_core._storage import read_text
    eid = "orch-eng-4"
    _seed_minimal_brief(eid)
    asyncio.run(design_advance(eid, mode="auto"))  # dispatch topic-design
    write_text(eid, "topic-design/topic-taxonomy.yaml",
               "scope: topic-design\nstructure:\n  pattern: domain/noun/verb\n")
    asyncio.run(design_advance(eid, mode="auto", last_scope="topic-design"))
    md = read_text(eid, "topic-design/topic-design.md")
    assert "# Topic Taxonomy" in md
    assert "Rendered from the `topic-design` structured artifact" in md
    assert "## Structure" in md


def test_event_portal_scope_completes_via_deterministic_write():
    """Event-portal is fully decided: the orchestrator materialises the derived
    model in SA storage itself, so the scope completes even when the worker emits
    its artifact as a SAM native block that never lands in SA's path (outcome=None,
    the real failing case). Without this, every attempt is counted a failure →
    retry_exhausted."""
    from solace_architect_core._storage import safe_artifact_path, read_yaml
    eid = "orch-eng-ep"
    _seed_minimal_brief(eid)
    # A taxonomy rich enough for derive_event_portal_model to produce a model.
    write_yaml(eid, "topic-design/topic-taxonomy.yaml", {
        "structure": {"pattern": "{region}/{domain}/{noun}/{verb}/v{N}/{entityID}"},
        "levels": {"domain": {"values": ["supplyChain"]}},
        "example_topics": [
            {"topic": "usEast/supplyChain/shipment/statusUpdated/v1/SH-1"},
            {"topic": "euWest/supplyChain/inventory/levelChanged/v1/SKU-9"},
        ],
    })
    # Orchestrator has not written the model yet.
    assert not safe_artifact_path(eid, "event-portal/event-portal-model.yaml").exists()
    # Simulate the worker's event-portal turn finishing WITHOUT a SA artifact.
    a = asyncio.run(design_advance(eid, mode="auto", last_scope="event-portal"))
    # The model is now on disk and the scope is done, not a failed attempt.
    assert safe_artifact_path(eid, "event-portal/event-portal-model.yaml").exists()
    model = read_yaml(eid, "event-portal/event-portal-model.yaml")
    assert model.get("domains") or model.get("events")
    view = asyncio.run(design_state_view(eid))
    assert ds.scope_status(view["state"], "event-portal") == ds.DONE
    assert a["action"] != "retry_exhausted"


def test_broker_select_kickoff_injects_computed_sizing():
    """Phase B: the orchestrator hands the worker the deterministic spool/band
    so it doesn't do the arithmetic itself."""
    eid = "orch-eng-5"
    write_yaml(eid, "discovery/discovery-brief.yaml", {
        "project": {"type": "greenfield"},
        "requirements": {
            "delivery_mode": "guaranteed",
            "event_volume": {"peak_events_per_sec": 2000, "average_message_size_kb": 5, "retention_hours": 24},
        },
    })
    # Complete topic-design so the next dispatch is broker-select.
    asyncio.run(design_advance(eid, mode="auto"))
    write_text(eid, "topic-design/topic-taxonomy.yaml", "scope: topic-design\n")
    a = asyncio.run(design_advance(eid, mode="auto", last_scope="topic-design"))
    assert a["action"] == "dispatch" and a["scope"] == "broker-select"
    assert "COMPUTED (authoritative" in a["kickoff"]
    assert "864" in a["kickoff"]      # spool GB injected


def test_design_advance_reset_scope_revives_exhausted():
    """The 'retry scope' affordance: reset_scope clears the exhausted budget so
    the orchestrator dispatches it again instead of re-surfacing retry_exhausted."""
    eid = "orch-eng-6"
    _seed_minimal_brief(eid)
    last = None
    for _ in range(ds.MAX_ATTEMPTS):
        asyncio.run(design_advance(eid, mode="auto", last_scope=last,
                                   outcome="failed" if last else None))
        last = "topic-design"
    assert asyncio.run(design_advance(eid, mode="auto", last_scope="topic-design",
                                      outcome="failed"))["action"] == "retry_exhausted"
    a = asyncio.run(design_advance(eid, reset_scope="topic-design"))
    assert a["action"] == "dispatch" and a["scope"] == "topic-design"


def test_design_advance_reset_revives_awaiting_scope():
    """Resume path: a scope parked in needs_input (await_user) — its question
    orphaned across sessions — is re-dispatched when reset_scope is sent."""
    eid = "orch-eng-7"
    _seed_minimal_brief(eid)
    asyncio.run(design_advance(eid, mode="auto"))                                  # dispatch topic-design
    a = asyncio.run(design_advance(eid, mode="auto", last_scope="topic-design", outcome="question"))
    assert a["action"] == "await_user" and a["scope"] == "topic-design"
    # The FE's resume re-dispatches via reset_scope → back to a dispatch.
    a2 = asyncio.run(design_advance(eid, reset_scope="topic-design"))
    assert a2["action"] == "dispatch" and a2["scope"] == "topic-design"


def test_restart_design_clears_orchestrator_state():
    """Restart Design must delete meta/design-state.yaml so it reliably starts
    from scratch (not skip the now-artifact-less completed scopes)."""
    from solace_architect_core._storage import write_text, read_yaml
    from solace_architect_core.orchestrator import design_state as ds
    from solace_architect_webui_entrypoint.routes.api import reset_design
    eid = "orch-eng-restart"
    _seed_minimal_brief(eid)
    # Simulate an in-progress orchestrated run: design-state + a done artifact.
    ds.save_state(eid, ds.init_state(["topic-design", "broker-select"], mode="auto"))
    write_text(eid, "topic-design/topic-taxonomy.yaml", "scope: topic-design\n")
    assert ds.load_state(eid) is not None
    asyncio.run(reset_design(eid))
    # Orchestrator state gone → next Start re-inits from scratch.
    assert ds.load_state(eid) is None


# ── Adversarial-review regressions: oversized artifacts must stay correct ─────
# (Codex review 2026-05-28: truncated bundle content must NOT be parsed for
# validation schema checks, nor presented as authoritative to blueprint.)

from solace_architect_core._storage import write_text
from solace_architect_webui_entrypoint.routes.api import (
    _build_validation_kickoff, _build_blueprint_kickoff,
    _render_validation_findings_block,
)


def test_reset_clears_engagement_chat_history_anchored_no_prefix_collision(tmp_path):
    """A Restart wipes the engagement's SSE replay files (chat history) so the
    thread doesn't stale-reference findings/artifacts that no longer exist.
    Critical: the engagement-id prefix-collision trap — 'supply-chain-tracking'
    must NOT match files belonging to 'supply-chain-tracking-copy'."""
    from solace_architect_webui_entrypoint.routes.api import _clear_engagement_chat_history
    sse = tmp_path / "artifacts" / "__system__" / "sse_replay"
    sse.mkdir(parents=True)
    # Target engagement's chats (single hyphen-free tab_id at the end).
    (sse / "chat-supply-chain-tracking-cf037e1d.json").write_text("{}")
    (sse / "chat-supply-chain-tracking-1779.json").write_text("{}")
    # Prefix-colliding engagement — must NOT be wiped.
    (sse / "chat-supply-chain-tracking-copy-XYZ.json").write_text("{}")
    # Unrelated engagement.
    (sse / "chat-neo-supply-chain-tracking-abc.json").write_text("{}")
    removed = _clear_engagement_chat_history("supply-chain-tracking")
    assert removed == 2
    assert not (sse / "chat-supply-chain-tracking-cf037e1d.json").exists()
    assert not (sse / "chat-supply-chain-tracking-1779.json").exists()
    assert (sse / "chat-supply-chain-tracking-copy-XYZ.json").exists()
    assert (sse / "chat-neo-supply-chain-tracking-abc.json").exists()


def test_validation_findings_block_splits_authoritative_from_candidates():
    """Mechanical findings render under AUTHORITATIVE (record verbatim); judgment
    findings (confirm=True) render under CANDIDATES with confirm-before-block
    guidance — so the agent can't self-block on a deterministic false positive."""
    result = {
        "findings": [
            {"lens": "subscription-syntax", "severity": "blocking",
             "artifact": "topic-design/topic-taxonomy.yaml", "detail": "bad >", "confirm": False},
            {"lens": "requirement-coverage", "severity": "blocking",
             "artifact": "integration/integration-map.yaml",
             "detail": "Backend system 'X' has no integration strategy.", "confirm": True},
        ],
        "counts": {"blocking": 2, "advisory": 0},
    }
    block = _render_validation_findings_block(result)
    assert "AUTHORITATIVE" in block and "CANDIDATES" in block
    before, after = block.split("CANDIDATES", 1)
    assert "subscription-syntax" in before          # authoritative section
    assert "requirement-coverage" in after          # candidate section
    assert "FALSE POSITIVE" in block                # dismiss-with-rationale guidance


def _big_valid_yaml(anchor_key: str, kb: int) -> str:
    # A VALID YAML doc with a recognised top-level key, padded past `kb` KB.
    pad = "\n".join(f"  note_{i}: filler line {i} " + "x" * 60 for i in range(kb * 12))
    return f"{anchor_key}:\n  real: true\n  detail:\n{pad}\n"


def test_validation_does_not_false_flag_a_large_valid_artifact():
    eid = "val-big"
    # >8 KB, valid, with the schema anchor key 'topics' — old code truncated it
    # in the bundle, safe_load failed, and schema-sanity emitted a false blocker.
    big = _big_valid_yaml("topics", 12)
    assert len(big) > 8000
    write_text(eid, "topic-design/topic-taxonomy.yaml", big)
    kickoff = _build_validation_kickoff(eid)
    # No server-induced "did not parse" blocker for the (valid-on-disk) artifact.
    assert "did not parse" not in kickoff
    assert "topic-design/topic-taxonomy.yaml" not in kickoff.split("PRECOMPUTED CHECKS")[-1] \
        or "blocking] schema-sanity @ topic-design/topic-taxonomy.yaml" not in kickoff


def test_blueprint_inlines_small_in_full_and_routes_large_to_read():
    eid = "bp-mix"
    small = "rpo: 0\nrto: 5\nha: active/standby\n"
    big = _big_valid_yaml("topology_pattern", 12)
    assert len(big) > 8000
    write_text(eid, "ha-dr/ha-dr-design.yaml", small)
    write_text(eid, "mesh-design/dmr-topology.yaml", big)
    kickoff = _build_blueprint_kickoff(eid)
    # Small artifact inlined IN FULL (its content present, under the full list).
    assert "PROVIDED IN FULL" in kickoff
    assert "active/standby" in kickoff
    # Large artifact is NOT inlined (no truncation marker), routed to read in full.
    assert "TOO LARGE TO INLINE" in kickoff
    assert "mesh-design/dmr-topology.yaml" in kickoff.split("TOO LARGE TO INLINE")[-1]
    assert "<truncated>" not in kickoff   # never present a truncated body as input


def test_design_advance_serialized_per_engagement():
    # The lock helper returns the SAME lock per engagement (atomic-claim guard)
    # and distinct locks for distinct engagements.
    from solace_architect_webui_entrypoint.routes.api import _design_advance_lock
    import asyncio as _aio
    a1 = _design_advance_lock("eng-A")
    a2 = _design_advance_lock("eng-A")
    b = _design_advance_lock("eng-B")
    assert a1 is a2 and a1 is not b
    assert isinstance(a1, _aio.Lock)
