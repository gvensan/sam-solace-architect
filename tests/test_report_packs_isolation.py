"""Audience-pack filter rules honored (v2spec §5.5a).

Exercises blueprint_tools.filter_artifacts_for_pack against a synthetic
engagement that contains artifacts from every category. Asserts each pack
selects only what its filters intend, and that the Executive pack contains
no technical-detail leakage.
"""

import pytest

from solace_architect_core._storage import write_text
from solace_architect_core.tools.blueprint_tools import filter_artifacts_for_pack


# Synthetic engagement with one artifact per category
SAMPLE_ARTIFACTS = [
    "discovery/discovery-brief.yaml",
    "topic-design/topic-taxonomy.yaml",
    "topic-design/wildcard-subscriptions.md",
    "topic-design/antipattern-report.md",
    "broker-select/broker-recommendation.yaml",
    "protocol-select/protocol-map.yaml",
    "sam-design/sam-topology.yaml",
    "mesh-design/dmr-topology.yaml",
    "ha-dr/ha-dr-design.yaml",
    "migration/migration-plan.yaml",
    "integration/integration-map.yaml",
    "event-portal/event-portal-model.yaml",
    "blueprint/architecture.md",
    "blueprint/runbook.md",
    "blueprint/diagrams/topic-hierarchy.mermaid",
    "blueprint/diagrams/broker-topology.mermaid",
    "blueprint/diagrams/security-boundaries.mermaid",
    "blueprint/diagrams/protocol-stack.mermaid",
    "executive/executive-summary.md",
    "executive/roi-framework.md",
    "executive/business-architecture.mermaid",
    "reviews/architect-review.yaml",
    "reviews/developer-review.yaml",
    "reviews/ops-review.yaml",
    "reviews/security-review.yaml",
    "validation/validation-report.yaml",
    "provisioning/provisioned.yaml",
    "provisioning/asyncapi/order-app.yaml",
]


@pytest.fixture
def sample_engagement(tmp_path, monkeypatch):
    """Seed an isolated engagement with one artifact per category."""
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))
    eid = "isolation-test"
    for name in SAMPLE_ARTIFACTS:
        write_text(eid, name, f"placeholder content for {name}")
    return eid


# ---------- Per-pack inclusion ----------

def test_blueprint_pack_includes_everything(sample_engagement):
    eid = sample_engagement
    selected = filter_artifacts_for_pack(eid, "blueprint")
    # All categories represented
    for category in ("discovery/", "topic-design/", "broker-select/", "blueprint/", "provisioning/"):
        assert any(s.startswith(category) for s in selected), f"missing {category} in blueprint pack"


def test_executive_pack_includes_only_executive_artifacts(sample_engagement):
    eid = sample_engagement
    selected = filter_artifacts_for_pack(eid, "executive")
    # Must include executive/* (per the `dirs:` rule)
    assert "executive/executive-summary.md" in selected
    assert "executive/roi-framework.md" in selected
    # Must NOT include technical detail
    assert "topic-design/wildcard-subscriptions.md" not in selected
    assert "topic-design/antipattern-report.md" not in selected
    assert "blueprint/runbook.md" not in selected
    # blueprint/architecture.md IS explicitly in `files:` for executive
    assert "blueprint/architecture.md" in selected


def test_admin_ops_pack_includes_operational_artifacts(sample_engagement):
    eid = sample_engagement
    selected = filter_artifacts_for_pack(eid, "admin-ops")
    assert "broker-select/broker-recommendation.yaml" in selected
    assert "blueprint/runbook.md" in selected
    assert "provisioning/provisioned.yaml" in selected
    assert "ha-dr/ha-dr-design.yaml" in selected


def test_security_pack_includes_security_artifacts(sample_engagement):
    eid = sample_engagement
    selected = filter_artifacts_for_pack(eid, "security")
    assert "reviews/security-review.yaml" in selected
    # Globs match diagrams with 'security' in the name
    assert any("security" in s for s in selected)


def test_developers_pack_includes_topic_protocol_and_asyncapi(sample_engagement):
    eid = sample_engagement
    selected = filter_artifacts_for_pack(eid, "developers")
    assert "topic-design/topic-taxonomy.yaml" in selected
    assert "protocol-select/protocol-map.yaml" in selected
    assert "provisioning/asyncapi/order-app.yaml" in selected
    assert "reviews/developer-review.yaml" in selected


# ---------- Executive isolation (no technical-detail leakage) ----------

def test_executive_pack_has_no_technical_leakage(sample_engagement):
    eid = sample_engagement
    selected = filter_artifacts_for_pack(eid, "executive")
    technical_markers = (
        "wildcard-subscriptions",
        "antipattern-report",
        "topic-taxonomy",
        "dmr-topology",
        "protocol-map",
        "sam-topology",
        "integration-map",
        "ha-dr-design",
        "migration-plan",
    )
    leaks = [s for s in selected if any(m in s for m in technical_markers)]
    assert not leaks, f"Executive pack leaked technical artifacts: {leaks}"


def test_unknown_audience_returns_empty(sample_engagement):
    eid = sample_engagement
    assert filter_artifacts_for_pack(eid, "nonexistent") == []
