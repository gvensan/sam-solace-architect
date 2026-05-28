"""Deterministic Event Portal model derivation (orchestrator/event_portal_model)."""

from __future__ import annotations

from solace_architect_core.orchestrator import event_portal_model as ep


def _taxonomy():
    return {
        "structure": {"pattern": "{region}/{domain}/{noun}/{verb}/v{N}/{entityID}"},
        "levels": {"domain": {"values": ["supplyChain"]}},
        "example_topics": [
            {"topic": "usEast/supplyChain/shipment/statusUpdated/v1/SH-1"},
            {"topic": "euWest/supplyChain/inventory/levelChanged/v1/SKU-9"},
        ],
    }


def _brief():
    return {"project": {"name": "supply-chain"},
            "landscape": {"systems": [
                {"name": "SAP", "role": "producer", "events": ["shipment-status-updated"]},
                {"name": "Snowflake", "role": "consumer", "events": []},
                {"name": "TMS", "role": "both", "events": ["order-created"]},
            ]}}


def test_domains_from_taxonomy_domain_level():
    d = ep.derive_domains(_taxonomy(), _brief())
    assert [x["name"] for x in d] == ["supplyChain"]


def test_domains_fallback_to_project_when_absent():
    d = ep.derive_domains({}, _brief())
    assert d and d[0]["name"] == "supply-chain"


def test_events_parsed_from_example_topics_by_pattern_position():
    evs = ep.derive_events(_taxonomy(), {"landscape": {"systems": []}})
    names = {e["name"] for e in evs}
    assert "shipment.statusUpdated" in names
    assert "inventory.levelChanged" in names
    sd = next(e for e in evs if e["name"] == "shipment.statusUpdated")
    assert sd["noun"] == "shipment" and sd["verb"] == "statusUpdated" and sd["domain"] == "supplyChain"


def test_events_union_landscape_dedup_normalised():
    evs = ep.derive_events(_taxonomy(), _brief())
    # 'shipment-status-updated' (landscape) normalises to the taxonomy
    # 'shipment.statusUpdated' → not double-counted.
    norms = [ep._norm(e["name"]) for e in evs]
    assert norms.count(ep._norm("shipment.statusUpdated")) == 1
    # 'order-created' from TMS is new → present.
    assert any(ep._norm("order-created") == ep._norm(e["name"]) for e in evs)


def test_applications_publish_subscribe_by_role():
    apps = {a["name"]: a for a in ep.derive_applications(_brief())}
    assert apps["SAP"]["publishes"] == ["shipment-status-updated"] and apps["SAP"]["subscribes"] == []
    assert apps["Snowflake"]["subscribes"] == [] and apps["Snowflake"]["publishes"] == []
    assert apps["TMS"]["publishes"] == ["order-created"] and apps["TMS"]["subscribes"] == ["order-created"]


def test_full_model_counts():
    m = ep.derive_event_portal_model(_taxonomy(), _brief())
    assert m["counts"]["domains"] == 1
    assert m["counts"]["applications"] == 3
    assert m["counts"]["events"] >= 3
    assert "domains" in m and "applications" in m and "events" in m
