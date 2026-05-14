"""EP provisioning 3-way contract (v2spec §4.10 + §5.6).

(a) Opt-in: refuse when preferences.provision_event_portal != true.
(b) MCP unavailable: halt — NEVER silently skip.
(c) Skip visible in dashboard's skip_reasons.
"""

import pytest

from solace_architect_core.tools import (
    artifact_tools, project_tools, dashboard_tools, ep_designer_mcp_tools, workflow_tools,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.delenv("SOLACE_API_TOKEN", raising=False)


# ---------- (a) Opt-in skipping ----------

@pytest.mark.asyncio
async def test_optout_skips_provisioning_in_engagement_plan():
    """When preferences.provision_event_portal=false, plan marks step skipped."""
    brief = {"systems": [{"name": "x"}],
             "requirements": {"topology": "single-site", "delivery_mode": "guaranteed",
                              "processing_guarantee": "at-least-once"},
             "preferences": {"provision_event_portal": False}}
    plan = (await workflow_tools.get_engagement_plan(brief)).data
    prov = next(s for s in plan if s["step"] == "provisioning")
    assert not prov["included"]
    assert "Provisioning not requested" in prov["skip_reason"]


@pytest.mark.asyncio
async def test_optin_includes_provisioning_in_engagement_plan():
    brief = {"systems": [{"name": "x"}],
             "requirements": {"topology": "single-site", "delivery_mode": "guaranteed",
                              "processing_guarantee": "at-least-once"},
             "preferences": {"provision_event_portal": True}}
    plan = (await workflow_tools.get_engagement_plan(brief)).data
    prov = next(s for s in plan if s["step"] == "provisioning")
    assert prov["included"]


# ---------- (b) MCP unavailable: halt, never silently skip ----------

@pytest.mark.asyncio
async def test_verify_tenant_access_reports_unavailable_when_token_missing():
    """SOLACE_API_TOKEN not set → tool reports available=False with remediation hint."""
    r = await ep_designer_mcp_tools.verify_tenant_access()
    assert r.ok  # the tool itself returned successfully
    assert r.data["available"] is False
    assert r.data["error"]                # carries the reason
    assert r.data["remediation"]          # carries the fix
    # Critical: it did NOT silently return "skipped" or pretend it succeeded.


@pytest.mark.asyncio
async def test_verify_tenant_access_reports_available_when_token_set(monkeypatch):
    monkeypatch.setenv("SOLACE_API_TOKEN", "fake-token-with-designer-rw")
    r = await ep_designer_mcp_tools.verify_tenant_access()
    assert r.data["available"] is True
    assert r.data["error"] is None


# ---------- (c) Opt-in skip visible in dashboard ----------

@pytest.mark.asyncio
async def test_optout_skip_visible_in_overview_skip_reasons():
    p = await project_tools.create_project(name="Opt-out test")
    eid = p.data["id"]
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml",
        "project_name: Opt-out test\nsystems: [{name: x}]\nrequirements: {topology: single-site, "
        "delivery_mode: guaranteed, processing_guarantee: at-least-once}\n"
        "preferences: {provision_event_portal: false}\n")
    r = await dashboard_tools.compute_overview_stats(eid)
    reasons = {item["step"]: item["reason"] for item in r.data["skip_reasons"]}
    assert "provisioning" in reasons, "Opt-out provisioning must appear in dashboard skip_reasons"
    assert "Provisioning not requested" in reasons["provisioning"]


@pytest.mark.asyncio
async def test_ep_provisioning_status_tile_reflects_optout():
    p = await project_tools.create_project(name="EP status")
    eid = p.data["id"]
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml",
        "preferences: {provision_event_portal: false}\nsystems: []\nrequirements: {}\n")
    r = await dashboard_tools.compute_overview_stats(eid)
    assert r.data["ep_provisioning_status"] == "not-requested"


@pytest.mark.asyncio
async def test_ep_provisioning_status_tile_reflects_optin_pending():
    p = await project_tools.create_project(name="EP pending")
    eid = p.data["id"]
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml",
        "preferences: {provision_event_portal: true}\nsystems: []\nrequirements: {}\n")
    r = await dashboard_tools.compute_overview_stats(eid)
    assert r.data["ep_provisioning_status"] == "pending"
