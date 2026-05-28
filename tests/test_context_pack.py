"""Bundled artifact read (orchestrator/context_pack)."""

from __future__ import annotations

import pytest

from solace_architect_core.orchestrator import context_pack as cp
from solace_architect_core._storage import write_text
from solace_architect_core._user_context import scoped_user


@pytest.fixture()
def _storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    return tmp_path


def test_bundle_collects_present_and_reports_missing(_storage):
    eid = "eng-bundle"
    write_text(eid, "topic-design/topic-taxonomy.yaml", "topics: {}")
    write_text(eid, "integration/integration-map.yaml", "systems: []")
    b = cp.build_artifact_bundle(eid)
    assert set(b["present"]) == {"topic-design/topic-taxonomy.yaml", "integration/integration-map.yaml"}
    assert "broker-select/broker-recommendation.yaml" in b["missing"]
    assert b["count"] == 2
    assert b["artifacts"]["integration/integration-map.yaml"] == "systems: []"


def test_bundle_truncates_oversize_artifact(_storage):
    eid = "eng-trunc"
    write_text(eid, "topic-design/topic-taxonomy.yaml", "x" * 50)
    b = cp.build_artifact_bundle(eid, max_chars_each=10)
    assert "topic-design/topic-taxonomy.yaml" in b["truncated"]
    assert b["artifacts"]["topic-design/topic-taxonomy.yaml"].endswith("<truncated>")


def test_bundle_respects_user_namespace(_storage):
    eid = "eng-user"
    uid = "user-abc"
    with scoped_user(uid):
        write_text(eid, "integration/integration-map.yaml", "systems: [SAP]")
    # Without the user scope the artifact is invisible (different namespace)…
    assert cp.build_artifact_bundle(eid)["count"] == 0
    # …with it, the bundle finds it.
    b = cp.build_artifact_bundle(eid, user_id=uid)
    assert b["count"] == 1 and "SAP" in b["artifacts"]["integration/integration-map.yaml"]


def test_render_bundle_block_lists_sections(_storage):
    eid = "eng-render"
    write_text(eid, "topic-design/topic-taxonomy.yaml", "topics: {}")
    block = cp.render_bundle_block(cp.build_artifact_bundle(eid))
    assert "DESIGN ARTIFACTS" in block
    assert "### topic-design/topic-taxonomy.yaml" in block
    assert "not produced:" in block  # the absent ones are listed


def test_custom_name_list(_storage):
    eid = "eng-custom"
    write_text(eid, "ha-dr/ha-dr-design.yaml", "rpo: 0")
    b = cp.build_artifact_bundle(eid, names=("ha-dr/ha-dr-design.yaml",))
    assert b["present"] == ["ha-dr/ha-dr-design.yaml"] and b["missing"] == []
