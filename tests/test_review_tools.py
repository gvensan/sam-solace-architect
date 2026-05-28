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
