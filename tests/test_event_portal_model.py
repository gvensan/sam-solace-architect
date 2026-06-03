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


def test_schemas_one_per_event():
    evs = ep.derive_events(_taxonomy(), _brief())
    schemas = ep.derive_schemas(evs)
    assert len(schemas) == len(evs)
    s = schemas[0]
    assert s["schema_type"] == "jsonSchema"
    assert s["content_type"] == "application/json"
    assert s["placeholder"] is True
    assert s["content"]["type"] == "object"
    # The inferred id property is required.
    assert s["content"]["required"]


def test_events_bound_to_schema():
    m = ep.derive_event_portal_model(_taxonomy(), _brief())
    by_name = {s["name"] for s in m["schemas"]}
    assert m["events"], "expected at least one event"
    for ev in m["events"]:
        assert ev.get("schema") in by_name


def test_full_model_counts_includes_schemas():
    m = ep.derive_event_portal_model(_taxonomy(), _brief())
    assert "schemas" in m
    assert m["counts"]["schemas"] == len(m["schemas"]) == len(m["events"])


# ── name-cleaning + gap surfacing (neo-supply-chain-tracking lessons) ─────
# Two things were wrong in that engagement:
#   (1) a system+event name like
#       "supplier-edi-messages (will be migrated to Solace JMS or REST)"
#       carried a trailing parenthetical through the brief → event → schema
#       → EP graph label;
#   (2) Snowflake / Amazon S3 were declared as consumers but their events list
#       was empty, so the EP graph showed them as floating nodes with no edges
#       and nothing surfaced the gap.
# These tests lock the cleanup + the gap surfacing so they can't silently
# regress.


def test_clean_event_name_strips_trailing_parenthetical():
    """Trailing ``(...)`` is dropped from the name, and what's inside is
    preserved as the returned description (whitespace-trimmed). Names
    without a trailing parenthetical pass through unchanged."""
    assert ep._clean_event_name("supplier-edi-messages (will be migrated to JMS)") == (
        "supplier-edi-messages", "will be migrated to JMS")
    assert ep._clean_event_name("purchase-order-created") == ("purchase-order-created", None)
    # Whitespace handling — leading/trailing trim.
    assert ep._clean_event_name("  inventory-level-changed  ") == ("inventory-level-changed", None)
    # Empty parens collapse to no description (don't fabricate an empty string).
    assert ep._clean_event_name("foo ()") == ("foo", None)


def test_clean_event_name_leaves_inner_parentheticals_alone():
    """Only the LAST trailing parenthetical is stripped — an inner one is
    part of the name. We don't want to mangle a legitimate name like
    ``foo (v2) bar`` by removing ``(v2)``."""
    assert ep._clean_event_name("foo (v2) bar") == ("foo (v2) bar", None)


def test_derive_events_cleans_landscape_event_names():
    """The bug: a brief event named with a parenthetical migration note
    used to land verbatim in the EP model and propagate to the schema + graph
    label. Cleaned name should appear; description should be preserved on
    the event row."""
    brief = {"landscape": {"systems": [
        {"name": "IBM MQ", "role": "producer",
         "events": ["supplier-edi-messages (will be migrated to Solace JMS or REST)"]},
    ]}}
    evs = ep.derive_events({}, brief)
    by_name = {e["name"]: e for e in evs}
    assert "supplier-edi-messages" in by_name
    assert not any("(" in n for n in by_name)            # no parens leaked into names
    assert "Solace JMS" in by_name["supplier-edi-messages"]["description"]


def test_derive_applications_cleans_app_and_event_names():
    """Names on the app row and on every event in publishes/subscribes must
    be cleaned consistently — otherwise the apps[].subscribes name won't
    match the events[].name and downstream wiring breaks."""
    brief = {"landscape": {"systems": [
        {"name": "IBM MQ (legacy supplier EDI gateway)", "role": "producer",
         "events": ["supplier-edi-messages (will be migrated)"]},
    ]}}
    apps = ep.derive_applications(brief)
    a = next(x for x in apps if x["name"] == "IBM MQ")
    assert a["publishes"] == ["supplier-edi-messages"]
    assert "legacy supplier EDI gateway" in a["description"]


def test_consumer_without_subscriptions_surfaces_as_gap():
    """neo-supply-chain-tracking: Snowflake + Amazon S3 declared consumer
    but events list empty → EP graph shows them as floating nodes. Surface
    that explicitly so the user knows to update the brief."""
    brief = {"landscape": {"systems": [
        {"name": "SAP", "role": "producer", "events": ["purchase-order-created"]},
        {"name": "Snowflake", "role": "consumer", "events": []},
        {"name": "Amazon S3", "role": "consumer"},   # missing events key entirely
    ]}}
    m = ep.derive_event_portal_model({}, brief)
    gap_apps = {g["application"] for g in m["gaps"]}
    assert gap_apps == {"Snowflake", "Amazon S3"}
    for g in m["gaps"]:
        assert g["kind"] == "consumer_without_subscriptions"
        assert g["severity"] == "advisory"
    # The summary note must surface count + names so the user sees it without
    # parsing the structured gaps list.
    assert "2 consumer(s) without subscriptions" in m["note"]
    assert "Snowflake" in m["note"] and "Amazon S3" in m["note"]


def test_consumer_with_subscriptions_has_no_gap():
    """Defensive: properly-subscribed consumers must NOT show up as gaps —
    otherwise the gap list becomes noise and users tune it out."""
    brief = {"landscape": {"systems": [
        {"name": "Snowflake", "role": "consumer",
         "events": ["purchase-order-created", "inventory-level-changed"]},
    ]}}
    m = ep.derive_event_portal_model({}, brief)
    assert m["gaps"] == []
    assert "without subscriptions" not in m["note"]


def test_both_role_with_no_events_also_flagged_as_gap():
    """A 'both' system with no events is ALSO a consumer-without-subscriptions
    case — and a producer-without-publishes case. We flag it once via the
    consumer lens because that's the more visible graph symptom (floating
    on the consumer side)."""
    brief = {"landscape": {"systems": [
        {"name": "Bridge", "role": "both", "events": []},
    ]}}
    m = ep.derive_event_portal_model({}, brief)
    assert len(m["gaps"]) == 1
    assert m["gaps"][0]["application"] == "Bridge"
