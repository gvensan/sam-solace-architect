"""Deterministic validation lenses (orchestrator/validation_rules)."""

from __future__ import annotations

from solace_architect_core.orchestrator import validation_rules as vr


# ── subscription syntax ──────────────────────────────────────────────────────

def test_subscription_violation_rules():
    assert vr.subscription_violation("acme/orders/>") is None        # valid
    assert vr.subscription_violation("acme/orders/*/v1") is None      # no '>'
    assert vr.subscription_violation("acme/>/v1") == "'>' must be the last character"
    assert "multiple" in vr.subscription_violation("a/>/b/>")
    assert "start" in vr.subscription_violation(">/acme")
    assert vr.subscription_violation(">") is None                     # bare '>' ok


def test_check_subscription_syntax_finds_nested_violation():
    taxonomy = {"topics": {"sub": ["acme/orders/>", "acme/>/bad"]}}
    f = vr.check_subscription_syntax(taxonomy)
    assert len(f) == 1
    assert f[0]["severity"] == "blocking" and "acme/>/bad" in f[0]["detail"]


# ── schema sanity ─────────────────────────────────────────────────────────────

def test_schema_sanity_unparseable_blocks_missing_key_advisory():
    artifacts = {
        "topic-design/topic-taxonomy.yaml": {"topics": {}},           # ok → no finding
        "broker-select/broker-recommendation.yaml": {"foo": 1},       # unknown shape → advisory
        "integration/integration-map.yaml": None,                     # unparseable → blocking
    }
    f = {x["artifact"]: x for x in vr.check_schema_sanity(artifacts)}
    assert "topic-design/topic-taxonomy.yaml" not in f                # passed
    # Parse failure is a hard block; a drifted/unknown key shape is only advisory
    # (so a stale key-list never manufactures a spurious blocker).
    assert f["integration/integration-map.yaml"]["severity"] == "blocking"
    assert f["broker-select/broker-recommendation.yaml"]["severity"] == "advisory"


def test_schema_sanity_accepts_real_artifact_anchor_keys():
    # The keys the real design artifacts actually use must NOT be flagged.
    artifacts = {
        "protocol-select/protocol-map.yaml": {"protocol_mapping": {}},
        "mesh-design/dmr-topology.yaml": {"topology_pattern": "x", "sites": []},
        "ha-dr/ha-dr-design.yaml": {"ha_design": {}},
    }
    assert vr.check_schema_sanity(artifacts) == []


# ── terminology ───────────────────────────────────────────────────────────────

def test_terminology_scan_is_case_insensitive_advisory():
    texts = {"a.md": "We use a Topic Exchange here."}
    f = vr.check_terminology(texts, ["topic exchange"])
    assert len(f) == 1 and f[0]["severity"] == "advisory"


# ── integration coverage ─────────────────────────────────────────────────────

def test_integration_coverage_flags_unmapped_system():
    brief = {"landscape": {"systems": [{"name": "SAP"}, {"name": "WMS"}]}}
    imap = {"systems": [{"system": "SAP"}]}
    f = vr.check_integration_coverage(brief, imap)
    assert len(f) == 1 and "WMS" in f[0]["detail"] and f[0]["severity"] == "blocking"


def test_integration_coverage_clean_when_all_mapped():
    brief = {"landscape": {"systems": [{"name": "SAP"}]}}
    assert vr.check_integration_coverage(brief, {"systems": [{"system": "SAP"}]}) == []


def test_integration_coverage_normalises_cross_phase_punctuation_drift():
    """The integration phase rewrites punctuation (':' -> ' - '), so an exact
    match would falsely flag the system as having no strategy. Normalised
    matching must treat the two forms as the same system → no finding."""
    brief = {"landscape": {"systems": [{"name": "Debezium (CDC): MySQL"}]}}
    imap = {"systems": [{"system": "Debezium (CDC) - MySQL"}]}
    assert vr.check_integration_coverage(brief, imap) == []


def test_integration_coverage_missing_map_is_single_advisory_not_n_blockers():
    """A missing / unparseable / systemless map must NOT manufacture one blocking
    finding per system (that gated a whole pipeline on a transient read miss).
    It yields exactly ONE advisory."""
    brief = {"landscape": {"systems": [
        {"name": "SAP"}, {"name": "Debezium (CDC): MySQL"}, {"name": "Oracle CDC"},
        {"name": "Snowflake"}, {"name": "Amazon S3"}]}}
    for bad_map in (None, {}, {"systems": []}, {"systems": None}, "not-a-dict"):
        f = vr.check_integration_coverage(brief, bad_map)
        assert len(f) == 1, f"{bad_map!r} should yield 1 finding, got {len(f)}"
        assert f[0]["severity"] == "advisory", f"{bad_map!r} must be advisory, not blocking"


def test_integration_coverage_reads_name_or_system_key():
    """A map row may carry the name under 'system' or 'name' (schema drift);
    either should match so we don't false-flag."""
    brief = {"landscape": {"systems": [{"name": "SAP"}, {"name": "Oracle CDC"}]}}
    imap = {"systems": [{"system": "SAP"}, {"name": "Oracle CDC"}]}
    assert vr.check_integration_coverage(brief, imap) == []


def test_confirm_flag_marks_only_judgment_lenses():
    """Mechanical lenses are authoritative (confirm=False, recorded verbatim);
    the integration-coverage blocking finding is a candidate (confirm=True, the
    agent must verify before blocking) so it can't self-block on a false positive."""
    brief = {"landscape": {"systems": [{"name": "SAP"}, {"name": "WMS"}]}}
    # integration-coverage blocking → candidate.
    cov = vr.check_integration_coverage(brief, {"systems": [{"system": "SAP"}]})
    assert cov and all(f["confirm"] is True for f in cov)
    # subscription-syntax → authoritative.
    subs = vr.check_subscription_syntax({"topics": {"x": "a/>/bad"}})
    assert subs and all(f["confirm"] is False for f in subs)
    # schema parse-failure → authoritative.
    sch = vr.check_schema_sanity({"integration/integration-map.yaml": None})
    assert sch and all(f["confirm"] is False for f in sch)
    # the "couldn't verify" advisory is informational, not a candidate-blocker.
    adv = vr.check_integration_coverage(brief, None)
    assert adv and all(f["confirm"] is False for f in adv)


# ── mesh consistency ──────────────────────────────────────────────────────────

def test_mesh_site_consistency_flags_missing_site():
    brief = {"requirements": {"sites": ["US-East", "EU-West", "APAC"]}}
    mesh = {"nodes": ["US-East broker", "EU-West broker"]}  # APAC missing
    f = vr.check_mesh_site_consistency(brief, mesh)
    assert len(f) == 1 and "APAC" in f[0]["detail"]


def test_mesh_consistency_skipped_for_single_site():
    brief = {"requirements": {"sites": ["US-East"]}}
    assert vr.check_mesh_site_consistency(brief, {"nodes": []}) == []


# ── aggregate ─────────────────────────────────────────────────────────────────

def test_run_validation_rules_aggregates_and_tallies():
    brief = {"landscape": {"systems": [{"name": "SAP"}, {"name": "WMS"}]},
             "requirements": {"sites": ["US", "EU"]}}
    parsed = {
        "topic-design/topic-taxonomy.yaml": {"topics": {"x": "a/>/bad"}},  # subscription violation
        "integration/integration-map.yaml": {"systems": [{"system": "SAP"}]},  # WMS missing
        "broker-select/broker-recommendation.yaml": {"sizing": {}},        # ok
    }
    out = vr.run_validation_rules(brief=brief, parsed_artifacts=parsed,
                                  artifact_texts={"x.md": "topic exchange"},
                                  forbidden_terms=["topic exchange"])
    assert out["counts"]["total"] == len(out["findings"])
    lenses = {f["lens"] for f in out["findings"]}
    assert {"subscription-syntax", "requirement-coverage", "terminology"} <= lenses
    assert out["counts"]["blocking"] >= 2  # bad subscription + unmapped WMS
