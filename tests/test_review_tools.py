"""get_review_pack — the reviewer bundled-read + candidate-findings tool."""

from __future__ import annotations

import asyncio

import pytest

from solace_architect_core.tools import review_tools as rt
from solace_architect_core._storage import write_text, write_yaml


@pytest.fixture()
def _eng(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    eid = "rev-eng"
    write_yaml(eid, "discovery/discovery-brief.yaml",
               {"requirements": {"delivery_mode": "guaranteed", "sites": ["US-East"]}})
    write_text(eid, "ha-dr/ha-dr-design.yaml", "notes: best effort only")          # ops: no HA
    write_text(eid, "mesh-design/dmr-topology.yaml", "topology: DMR federation")   # architect: DMR single-site
    return eid


def test_pack_bundles_artifacts_and_dimension_candidates(_eng):
    res = asyncio.run(rt.get_review_pack(_eng, "ops"))
    assert res.ok
    d = res.data
    assert d["dimension"] == "ops"
    # Bundle present (one call, not ~20 reads)
    assert "ha-dr/ha-dr-design.yaml" in d["present"]
    # ops candidates only (the no-HA-under-guaranteed finding), not architect's
    assert d["candidate_findings"], "expected at least one ops candidate"
    assert all(f["dimension"] == "ops" for f in d["candidate_findings"])


def test_dimension_all_returns_every_dimension(_eng):
    res = asyncio.run(rt.get_review_pack(_eng, "all"))
    dims = {f["dimension"] for f in res.data["candidate_findings"]}
    # both ops (no HA) and architect (DMR single-site) fire on this fixture
    assert "ops" in dims and "architect" in dims


def test_unknown_dimension_falls_back_to_all(_eng):
    res = asyncio.run(rt.get_review_pack(_eng, "marketing"))
    assert res.ok and res.data["candidate_findings"]  # not crash; returns all


def test_missing_engagement_is_soft(_eng):
    res = asyncio.run(rt.get_review_pack("no-such-eng", "security"))
    # No artifacts → ok with empty present, no crash.
    assert res.ok and res.data["present"] == []


# ---------- backfill_review_narrative ----------

def _write_findings(eid, *findings):
    write_yaml(eid, "meta/findings.yaml", {"findings": list(findings)})


def _finding(fid, agent, severity="important"):
    return {"id": fid, "severity": severity, "description": f"{fid} issue.",
            "affected_artifact": "a.yaml", "recommendation": f"fix {fid}",
            "source_agent": agent, "status": "pending"}


def test_backfill_renders_from_findings(_eng):
    _write_findings(_eng,
                    _finding("F1", "SAOpsReviewerAgent", "critical"),
                    _finding("F2", "SAOpsReviewerAgent", "advisory"))
    res = asyncio.run(rt.backfill_review_narrative(_eng, "ops"))
    assert res.ok and res.data["backfilled"] and res.data["findings_rendered"] == 2
    from solace_architect_core._storage import read_text
    md = read_text(_eng, "reviews/ops-review.md")
    assert "Auto-reconstructed" in md           # honest banner
    assert "F1 — critical" in md and "F2 — advisory" in md
    assert "**Critical:** 1" in md and "DONE_WITH_CONCERNS" in md


def test_backfill_does_not_clobber_existing(_eng):
    write_text(_eng, "reviews/ops-review.md", "ORIGINAL REVIEWER PROSE")
    _write_findings(_eng, _finding("F1", "SAOpsReviewerAgent"))
    res = asyncio.run(rt.backfill_review_narrative(_eng, "ops"))
    assert res.ok and res.data["skipped"]
    from solace_architect_core._storage import read_text
    assert read_text(_eng, "reviews/ops-review.md") == "ORIGINAL REVIEWER PROSE"


def test_backfill_force_overwrites(_eng):
    write_text(_eng, "reviews/ops-review.md", "ORIGINAL")
    _write_findings(_eng, _finding("F1", "SAOpsReviewerAgent"))
    res = asyncio.run(rt.backfill_review_narrative(_eng, "ops", force=True))
    assert res.ok and res.data.get("backfilled")


def test_backfill_no_findings_fails(_eng):
    _write_findings(_eng, _finding("F1", "SAArchitectReviewerAgent"))
    # security recorded nothing → don't fabricate an empty review
    res = asyncio.run(rt.backfill_review_narrative(_eng, "security"))
    assert not res.ok and "never ran" in res.error


def test_backfill_unknown_dimension_fails(_eng):
    res = asyncio.run(rt.backfill_review_narrative(_eng, "marketing"))
    assert not res.ok and "unknown dimension" in res.error
