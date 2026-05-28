"""Deterministic reviewer candidate findings (orchestrator/review_checks)."""

from __future__ import annotations

from solace_architect_core.orchestrator import review_checks as rc


# ── ops ───────────────────────────────────────────────────────────────────────

def test_ops_flags_no_ha_under_guaranteed_delivery():
    brief = {"requirements": {"delivery_mode": "guaranteed"}}
    parsed = {"ha-dr/ha-dr-design.yaml": {"notes": "best effort only"}}
    f = rc.ops_candidates(brief, parsed)
    assert any("HA" in x["issue"] or "redundancy" in x["issue"] for x in f)


def test_ops_no_flag_when_ha_present():
    brief = {"requirements": {"delivery_mode": "guaranteed"}}
    parsed = {"ha-dr/ha-dr-design.yaml": {"ha": "active/standby redundancy group"},
              "broker-select/broker-recommendation.yaml": {"sizing": {"spool_gb": 1}}}
    assert rc.ops_candidates(brief, parsed) == []


def test_ops_flags_missing_sizing():
    f = rc.ops_candidates({}, {"broker-select/broker-recommendation.yaml": {"tier": "Enterprise"}})
    assert any("sizing" in x["issue"].lower() for x in f)


# ── security ──────────────────────────────────────────────────────────────────

def test_security_flags_missing_tls_and_auth():
    f = rc.security_candidates({}, {}, all_text="topics and brokers, nothing else")
    issues = " ".join(x["issue"] for x in f).lower()
    assert "tls" in issues and "auth" in issues


def test_security_quiet_when_tls_and_auth_present():
    txt = "All links use TLS 1.3; client-profile + ACL per producer with OAuth."
    assert rc.security_candidates({}, {}, all_text=txt) == []


def test_security_residency_without_selective_replication_is_critical():
    brief = {"requirements": {"data_residency_constraints": ["EU in EU-West"]}}
    parsed = {"mesh-design/dmr-topology.yaml": {"topology": "full mesh, replicate everything"}}
    f = rc.security_candidates(brief, parsed, all_text="tls auth")  # silence tls/auth
    assert any(x["severity"] == "critical" and "residency" in x["issue"].lower() for x in f)


# ── developer ─────────────────────────────────────────────────────────────────

def test_developer_flags_no_version_level():
    parsed = {"topic-design/topic-taxonomy.yaml":
              {"structure": {"pattern": "{domain}/{noun}/{verb}"}, "levels": {"domain": {}}}}
    f = rc.developer_candidates({}, parsed, all_text="")
    assert any("version" in x["issue"].lower() for x in f)


def test_developer_quiet_when_version_in_pattern():
    parsed = {"topic-design/topic-taxonomy.yaml":
              {"structure": {"pattern": "{domain}/{noun}/{verb}/v{N}"}, "levels": {"version": {}}}}
    assert rc.developer_candidates({}, parsed, all_text="") == []


# ── architect ─────────────────────────────────────────────────────────────────

def test_architect_flags_dmr_for_single_site():
    brief = {"requirements": {"sites": ["US-East"]}}
    parsed = {"mesh-design/dmr-topology.yaml": {"topology": "DMR external-link federation"}}
    f = rc.architect_candidates(brief, parsed)
    assert any("over-engineered" in x["issue"].lower() for x in f)


def test_architect_quiet_for_multi_site_dmr():
    brief = {"requirements": {"sites": ["US-East", "EU-West"]}}
    parsed = {"mesh-design/dmr-topology.yaml": {"topology": "DMR federation"}}
    assert rc.architect_candidates(brief, parsed) == []


# ── aggregate ─────────────────────────────────────────────────────────────────

def test_candidate_findings_groups_by_dimension():
    brief = {"requirements": {"delivery_mode": "guaranteed", "sites": ["US-East"]}}
    parsed = {
        "ha-dr/ha-dr-design.yaml": {"notes": "tbd"},
        "mesh-design/dmr-topology.yaml": {"topology": "DMR federation"},
    }
    out = rc.candidate_findings(brief, parsed)
    assert set(out["by_dimension"]) == set(rc.DIMENSIONS)
    assert out["count"] == len(out["findings"]) > 0
    dims = {f["dimension"] for f in out["findings"]}
    assert "ops" in dims and "architect" in dims  # both fire on this design
