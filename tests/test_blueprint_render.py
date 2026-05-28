"""Deterministic blueprint assembly (orchestrator/blueprint_render)."""

from __future__ import annotations

from solace_architect_core.orchestrator import blueprint_render as br


def _brief():
    return {"project": {"name": "Supply Chain Tracking"}}


def _parsed():
    return {
        "topic-design/topic-taxonomy.yaml": {"structure": {"pattern": "{region}/{domain}"}},
        "broker-select/broker-recommendation.yaml": {"sizing": {"spool_gb": 864, "band": "medium"}},
        "integration/integration-map.yaml": {"systems": [{"name": "SAP", "recommended_protocol": "REST"}]},
        # ha-dr intentionally absent → its section must NOT render
    }


def test_blueprint_has_title_and_executive_summary():
    doc = br.render_blueprint(_brief(), _parsed())
    assert doc.startswith("# Supply Chain Tracking — Solace Architecture Blueprint")
    assert "## Executive Summary" in doc
    assert "<!-- NARRATIVE:" in doc  # narrative placeholders present


def test_only_present_artifacts_render():
    doc = br.render_blueprint(_brief(), _parsed())
    assert "## Topic Taxonomy" in doc
    assert "## Broker Selection & Sizing" in doc
    assert "## Micro-Integration Strategy" in doc
    assert "High Availability" not in doc          # ha-dr artifact absent → skipped


def test_structured_content_rendered_from_artifacts():
    doc = br.render_blueprint(_brief(), _parsed())
    assert "864" in doc                            # sizing value rendered
    assert "**Recommended protocol**: REST" in doc  # integration row rendered
    assert "- **SAP**" in doc                       # record led by its name field


def test_decisions_register_when_provided():
    decisions = [{"name": "broker", "selected": "Solace Cloud Enterprise"}]
    doc = br.render_blueprint(_brief(), _parsed(), decisions=decisions)
    assert "## Decisions Register" in doc
    assert "Solace Cloud Enterprise" in doc


def test_present_sections_helper():
    assert br.present_sections(_parsed()) == [
        "Topic Taxonomy", "Broker Selection & Sizing", "Micro-Integration Strategy"]


def test_title_fallback_without_project_name():
    doc = br.render_blueprint({}, {"ha-dr/ha-dr-design.yaml": {"rpo": 0}})
    assert doc.startswith("# Solace Architecture — Solace Architecture Blueprint")
    assert "## High Availability & Disaster Recovery" in doc
