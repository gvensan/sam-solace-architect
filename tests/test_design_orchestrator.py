"""Tests for the deterministic Design orchestration state + decision brain.

The whole point of the rebuilt Design engine is that control flow is ordinary,
unit-testable code. These tests exercise it end-to-end with no storage, LLM, or
async in the loop — including the exact scenarios the classic path got wrong
(re-executing completed scopes; losing the "what's next" pointer).
"""

import pytest

from solace_architect_core.orchestrator import design_state as ds


SCOPES = ["topic-design", "broker-select", "protocol-select"]


# ── construction ──────────────────────────────────────────────────────────


def test_init_state_builds_ordered_pending_scopes():
    st = ds.init_state(SCOPES, mode="auto")
    assert st["mode"] == "auto"
    assert st["version"] == ds.STATE_VERSION
    assert [s["name"] for s in st["scopes"]] == SCOPES
    assert all(s["status"] == ds.PENDING for s in st["scopes"])
    assert all(s["attempts"] == 0 for s in st["scopes"])


def test_init_state_dedups_preserving_order():
    st = ds.init_state(["a", "b", "a", "c", "b"], mode="interactive")
    assert [s["name"] for s in st["scopes"]] == ["a", "b", "c"]
    assert st["mode"] == "interactive"


def test_init_state_rejects_empty_and_bad_mode():
    with pytest.raises(ValueError):
        ds.init_state([], mode="auto")
    with pytest.raises(ValueError):
        ds.init_state(SCOPES, mode="turbo")


# ── pure queries ────────────────────────────────────────────────────────────


def test_next_scope_and_completion_progression():
    st = ds.init_state(SCOPES)
    assert ds.next_scope(st) == "topic-design"
    assert not ds.is_complete(st)

    ds.complete_scope(st, "topic-design")
    assert ds.next_scope(st) == "broker-select"
    assert ds.done_scopes(st) == ["topic-design"]

    ds.complete_scope(st, "broker-select", with_concerns=True)
    assert ds.next_scope(st) == "protocol-select"
    assert ds.done_scopes(st) == ["topic-design", "broker-select"]

    ds.complete_scope(st, "protocol-select")
    assert ds.next_scope(st) is None
    assert ds.is_complete(st)


# ── the decision brain ────────────────────────────────────────────────────


def test_decide_next_dispatches_first_scope():
    st = ds.init_state(SCOPES)
    action = ds.decide_next(st)
    assert action == {
        "action": "dispatch",
        "scope": "topic-design",
        "attempt": 1,
        "done": [],
    }


def test_decide_next_in_flight_while_running():
    st = ds.init_state(SCOPES)
    ds.begin_scope(st, "topic-design")
    assert ds.scope_status(st, "topic-design") == ds.RUNNING
    assert st["scopes"][0]["attempts"] == 1
    assert ds.decide_next(st) == {"action": "in_flight", "scope": "topic-design"}


def test_decide_next_advances_after_completion():
    st = ds.init_state(SCOPES)
    ds.begin_scope(st, "topic-design")
    ds.complete_scope(st, "topic-design")
    action = ds.decide_next(st)
    assert action["action"] == "dispatch"
    assert action["scope"] == "broker-select"
    assert action["done"] == ["topic-design"]


def test_decide_next_completes_when_all_done():
    st = ds.init_state(SCOPES)
    for s in SCOPES:
        ds.complete_scope(st, s)
    assert ds.decide_next(st) == {"action": "complete"}


def test_decide_next_await_user_on_question():
    st = ds.init_state(SCOPES)
    ds.begin_scope(st, "topic-design")
    ds.needs_input(st, "topic-design", note="Which region encoding?")
    assert ds.decide_next(st) == {"action": "await_user", "scope": "topic-design"}


def test_decide_next_blocked():
    st = ds.init_state(SCOPES)
    ds.block_scope(st, "topic-design", note="brief missing throughput")
    assert ds.decide_next(st) == {
        "action": "blocked",
        "scope": "topic-design",
        "note": "brief missing throughput",
    }


# ── the bug we are eliminating: completed scopes must NEVER re-run ───────────


def test_completed_scope_is_never_redispatched():
    """The classic path re-executed topic-design/broker-select repeatedly. Here,
    advancing is strictly monotonic: once a scope is terminal it can never be
    chosen by next_scope/decide_next again."""
    st = ds.init_state(SCOPES)
    ds.complete_scope(st, "topic-design")
    ds.complete_scope(st, "broker-select")
    # No matter how many times we ask, it advances to protocol-select — never
    # back to a done scope.
    for _ in range(5):
        action = ds.decide_next(st)
        assert action["action"] == "dispatch"
        assert action["scope"] == "protocol-select"


def test_re_completing_is_idempotent():
    st = ds.init_state(SCOPES)
    ds.complete_scope(st, "topic-design")
    ds.complete_scope(st, "topic-design")  # no duplicate, stable status
    assert ds.scope_status(st, "topic-design") == ds.DONE
    assert [s["name"] for s in st["scopes"]] == SCOPES  # no scope added


# ── retry budget ─────────────────────────────────────────────────────────────


def test_retry_budget_exhausts_then_surfaces():
    st = ds.init_state(SCOPES)
    # Simulate MAX_ATTEMPTS failed dispatches of the first scope.
    for n in range(ds.MAX_ATTEMPTS):
        action = ds.decide_next(st)
        assert action["action"] == "dispatch"
        assert action["attempt"] == n + 1
        ds.begin_scope(st, "topic-design")        # bumps attempts, RUNNING
        ds.fail_scope(st, "topic-design", note="stall")  # back to PENDING
    # Budget spent and still not terminal → surfaced, not re-dispatched forever.
    action = ds.decide_next(st)
    assert action == {
        "action": "retry_exhausted",
        "scope": "topic-design",
        "attempts": ds.MAX_ATTEMPTS,
    }


def test_success_within_budget_advances_normally():
    st = ds.init_state(SCOPES)
    ds.begin_scope(st, "topic-design")
    ds.fail_scope(st, "topic-design")     # attempt 1 failed
    ds.begin_scope(st, "topic-design")
    ds.complete_scope(st, "topic-design")  # attempt 2 succeeded
    action = ds.decide_next(st)
    assert action["action"] == "dispatch"
    assert action["scope"] == "broker-select"


# ── guards ───────────────────────────────────────────────────────────────────


def test_set_status_unknown_scope_raises():
    st = ds.init_state(SCOPES)
    with pytest.raises(KeyError):
        ds.set_status(st, "does-not-exist", ds.DONE)


# ── storage round-trip (single-writer durability) ───────────────────────────


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    eid = "design-orch-eng-1"
    st = ds.init_state(SCOPES, mode="auto")
    ds.begin_scope(st, "topic-design")
    ds.complete_scope(st, "topic-design")
    ds.save_state(eid, st)

    loaded = ds.load_state(eid)
    assert loaded is not None
    assert loaded["mode"] == "auto"
    assert ds.scope_status(loaded, "topic-design") == ds.DONE
    assert ds.next_scope(loaded) == "broker-select"
    assert ds.decide_next(loaded)["scope"] == "broker-select"


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    assert ds.load_state("no-such-engagement") is None


# ── prose rendering (Phase C: structured-only design, deterministic prose) ───

from solace_architect_core.orchestrator import prose


def test_prose_renders_title_sections_scalars_and_lists():
    data = {
        "schema_version": 1.0, "engagement_id": "e", "scope": "broker-select",
        "recommendation": {
            "deployment_type": "solace-cloud",
            "high_availability": True,
            "regions": [
                {"name": "us-east-1", "cloud_provider": "AWS", "rationale": "prod"},
                {"name": "eu-west-1", "cloud_provider": "AWS", "rationale": "gdpr"},
            ],
        },
        "tags": ["a", "b"],
    }
    md = prose.render_scope_markdown("broker-select", data)
    assert md.startswith("# Broker Selection")
    assert "## Schema version" not in md            # meta keys skipped
    assert "## Recommendation" in md
    assert "**Deployment type**: solace-cloud" in md
    assert "**High availability**: yes" in md        # bool → yes
    assert "**us-east-1**" in md                      # list-of-dicts lead field
    assert "- a" in md and "- b" in md                # scalar list bullets


def test_prose_handles_unknown_scope_and_nonmapping():
    md = prose.render_scope_markdown("custom-scope", {"k": "v"})
    assert md.startswith("# Custom scope")
    assert "## K" in md and "v" in md
    md2 = prose.render_scope_markdown("x", "just a string")
    assert "just a string" in md2


# ── rules engines (Phase B: deterministic decidable scopes) ──────────────────

from solace_architect_core.orchestrator import rules


def _brief_with_volume():
    return {
        "requirements": {
            "delivery_mode": "guaranteed",
            "processing_guarantee": "at-least-once",
            "topology": "multi-region",
            "sites": ["US-East", "EU-West", "APAC"],
            "data_residency_constraints": ["EU data in EU-West"],
            "event_volume": {
                "peak_events_per_sec": 2000,
                "average_message_size_kb": 5,
                "retention_hours": 24,
            },
        },
    }


def test_broker_sizing_matches_documented_formula():
    out = rules.broker_sizing(_brief_with_volume())
    c = out["computed"]
    assert c["spool_gb_per_region"] == 864.0          # 2000 × 5 × 86400 ÷ 1e6
    assert c["ingress_mb_per_sec"] == 10.0
    assert c["throughput_band"] == "medium"
    assert c["recommended_service_class"] == "Enterprise"  # guaranteed delivery


def test_broker_sizing_insufficient_inputs():
    out = rules.broker_sizing({"requirements": {}})
    assert out["computed"] is None
    assert "manually" in out["note"]


def test_mesh_topology_multiregion_with_residency_is_federation():
    m = rules.mesh_topology(_brief_with_volume())
    assert "federation" in m["recommended_mesh"]
    assert m["replication"] == "selective per data-residency policy"
    assert m["data_residency"] is True


def test_hadr_baseline_requires_ha_for_guaranteed():
    h = rules.hadr_baseline(_brief_with_volume())
    assert h["ha_required"] is True
    assert "HA redundancy group" in h["recommended"]


def test_compute_scope_rules_only_for_decidable():
    brief = _brief_with_volume()
    assert rules.compute_scope_rules("broker-select", brief)["sizing"]["computed"]["spool_gb_per_region"] == 864.0
    assert rules.compute_scope_rules("mesh-design", brief)["mesh"]["data_residency"] is True
    assert rules.compute_scope_rules("ha-dr", brief)["hadr"]["ha_required"] is True
    assert rules.compute_scope_rules("topic-design", brief) is None   # open scope


# ── integration map (the highest-fan-out scope, now decidable) ───────────────


def _brief_with_systems():
    """A landscape mirroring the supply-chain engagement that kept failing —
    8 systems spanning every transport so the priority order is exercised."""
    return {"landscape": {"systems": [
        {"name": "SAP", "role": "producer", "protocol": "REST, AMQP",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "Debezium", "role": "producer", "protocol": "Kafka",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "Oracle CDC", "role": "producer", "protocol": "REST, JDBC",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "Snowflake", "role": "consumer", "protocol": "REST, JDBC",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "S3", "role": "consumer", "protocol": "REST, S3 API",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "WMS", "role": "producer", "protocol": "MQTT, REST",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "TMS", "role": "both", "protocol": "REST, JMS",
         "mi_availability": {"direct": True, "indirect_via": None}},
        {"name": "Customer Portal", "role": "consumer", "protocol": "REST, WebSocket",
         "mi_availability": {"direct": True, "indirect_via": None}},
    ]}}


def test_integration_map_reproduces_per_system_picks():
    m = rules.integration_map(_brief_with_systems())
    assert m["system_count"] == 8
    picks = {r["system"]: r["recommended_protocol"] for r in m["systems"]}
    # The deterministic priority must match the hand-made decisions exactly.
    assert picks == {
        "SAP": "REST",                 # REST preferred over AMQP (simplest path)
        "Debezium": "Kafka",           # Kafka bridge wins
        "Oracle CDC": "REST",
        "Snowflake": "REST",
        "S3": "REST",
        "WMS": "MQTT 3.1.1",           # device transport over REST
        "TMS": "JMS 2.0",              # transactional / bi-directional
        "Customer Portal": "WebSocket",  # real-time push to a consumer
    }
    assert m["unresolved"] == []


def test_integration_map_direction_from_role():
    rows = {r["system"]: r for r in rules.integration_map(_brief_with_systems())["systems"]}
    assert rows["SAP"]["direction"].startswith("inbound")        # producer
    assert rows["Snowflake"]["direction"].startswith("outbound")  # consumer
    assert rows["TMS"]["direction"] == "bidirectional"            # both


def test_integration_map_flags_unresolved_systems():
    brief = {"landscape": {"systems": [
        {"name": "MainframeX", "role": "producer", "protocol": "SNA, 3270",  # no Solace transport
         "mi_availability": {"direct": False, "indirect_via": None}},
        {"name": "LegacyViaBridge", "role": "producer", "protocol": "REST",
         "mi_availability": {"direct": False, "indirect_via": "IBM MQ bridge"}},  # has a path
    ]}}
    m = rules.integration_map(brief)
    assert "MainframeX" in m["unresolved"]          # no transport AND no MI path
    assert "LegacyViaBridge" not in m["unresolved"]  # indirect path exists


def test_integration_wired_into_compute_scope_rules():
    out = rules.compute_scope_rules("integration", _brief_with_systems())
    assert out is not None and out["integration"]["system_count"] == 8
    assert "integration" in rules.DECIDABLE_SCOPES


def test_parse_protocols_ignores_non_solace_transports():
    # JDBC / S3 API are storage protocols, not Solace transports → dropped.
    assert rules._parse_protocols("REST, JDBC") == ["rest"]
    assert rules._parse_protocols("REST, S3 API") == ["rest"]
    assert rules._parse_protocols("MQTT, REST") == ["mqtt", "rest"]
    assert rules._parse_protocols("") == []


# ── metrics (Phase 8: orchestrated-engine observability) ─────────────────────


def test_metrics_clean_run_has_no_retries():
    st = ds.init_state(SCOPES)
    for s in SCOPES:
        ds.begin_scope(st, s)
        ds.complete_scope(st, s)
    m = ds.metrics(st)
    assert m["engine"] == "orchestrated"
    assert m["scopes_total"] == 3 and m["scopes_done"] == 3
    assert m["completion_pct"] == 100.0 and m["complete"] is True
    assert m["retries"] == 0            # the classic engine's bug, now measurable
    assert m["retried_scopes"] == []


def test_metrics_counts_retries_and_blocks():
    st = ds.init_state(SCOPES)
    # topic-design needed 3 attempts (2 retries); broker-select blocked.
    for _ in range(3):
        ds.begin_scope(st, "topic-design")
        ds.fail_scope(st, "topic-design")
    ds.complete_scope(st, "topic-design")
    ds.block_scope(st, "broker-select", note="missing input")
    m = ds.metrics(st)
    assert m["retries"] == 2
    assert m["retried_scopes"] == ["topic-design"]
    assert m["blocked_scopes"] == ["broker-select"]
    assert m["scopes_done"] == 1


def test_reset_scope_revives_exhausted_budget():
    st = ds.init_state(SCOPES)
    for _ in range(ds.MAX_ATTEMPTS):
        ds.begin_scope(st, "topic-design")
        ds.fail_scope(st, "topic-design")
    assert ds.decide_next(st)["action"] == "retry_exhausted"
    ds.reset_scope(st, "topic-design")
    a = ds.decide_next(st)
    assert a["action"] == "dispatch" and a["scope"] == "topic-design" and a["attempt"] == 1


# ── reconcile_with_artifacts ─────────────────────────────────────────────
# Guards the state↔artifact desync that bit neo-supply-chain-tracking
# (design-state.yaml said all scopes done; disk said no artifacts existed →
# the engine returned action=complete on Start Design without any work). The
# fix is a load-time reconcile that demotes done-but-evidence-less scopes.


def test_reconcile_demotes_done_scopes_with_no_evidence():
    """The canonical bug: state claims done, no artifact on disk → must demote
    so the engine actually runs the scope on the next decide_next."""
    st = ds.init_state(SCOPES)
    for s in SCOPES:
        ds.complete_scope(st, s)
    assert ds.is_complete(st)              # before reconcile: lies "complete"
    st2, demoted = ds.reconcile_with_artifacts(st, evidence_exists=lambda _s: False)
    assert demoted == SCOPES               # ordered, every scope demoted
    assert not ds.is_complete(st2)
    for s in SCOPES:
        sc = next(x for x in st2["scopes"] if x["name"] == s)
        assert sc["status"] == ds.PENDING
        assert sc["attempts"] == 0         # fresh retry budget
        assert "evidence missing" in sc["note"]
    # decide_next now dispatches the FIRST scope (no longer "complete").
    assert ds.decide_next(st2)["action"] == "dispatch"


def test_reconcile_preserves_scopes_with_evidence():
    """No-op for the steady-state case: every done scope has its artifact, so
    nothing should change. Critical — we don't want the integrity check to
    erase legitimate work."""
    st = ds.init_state(SCOPES)
    for s in SCOPES:
        ds.complete_scope(st, s)
    st2, demoted = ds.reconcile_with_artifacts(st, evidence_exists=lambda _s: True)
    assert demoted == []
    assert ds.is_complete(st2)


def test_reconcile_only_touches_terminal_advance_scopes():
    """Pending/running/blocked scopes have nothing to reconcile — only DONE
    and DONE_WITH_CONCERNS scopes can be 'wrongly done'."""
    st = ds.init_state(SCOPES)
    ds.complete_scope(st, "topic-design", with_concerns=True)
    ds.begin_scope(st, "broker-select")     # → RUNNING
    # protocol-select stays PENDING.
    st2, demoted = ds.reconcile_with_artifacts(st, evidence_exists=lambda _s: False)
    assert demoted == ["topic-design"]      # only the terminal-advance one
    assert ds.scope_status(st2, "broker-select") == ds.RUNNING
    assert ds.scope_status(st2, "protocol-select") == ds.PENDING


def test_reconcile_partial_disk_state_demotes_only_orphans():
    """Mixed reality: some scopes have artifacts, some don't. Only the
    evidence-less ones get demoted."""
    st = ds.init_state(SCOPES)
    for s in SCOPES:
        ds.complete_scope(st, s)
    have_evidence = {"topic-design"}
    st2, demoted = ds.reconcile_with_artifacts(
        st, evidence_exists=lambda s: s in have_evidence)
    assert demoted == ["broker-select", "protocol-select"]
    assert ds.scope_status(st2, "topic-design") == ds.DONE
    assert ds.scope_status(st2, "broker-select") == ds.PENDING


def test_reconcile_treats_predicate_exception_as_evidence_present():
    """A predicate that raises (transient I/O, broken path lookup) must not
    demote a scope — silent demotion on a flaky check would be worse than
    the original bug."""
    st = ds.init_state(SCOPES)
    ds.complete_scope(st, "topic-design")
    def raiser(_s):
        raise OSError("disk gremlin")
    st2, demoted = ds.reconcile_with_artifacts(st, evidence_exists=raiser)
    assert demoted == []
    assert ds.scope_status(st2, "topic-design") == ds.DONE


def test_reconcile_noop_does_not_bump_updated_at():
    """A no-op reconcile (every done scope has evidence) must not bump
    updated_at — otherwise every advance call would look like a fresh write
    to monitors and dashboards. (We don't assert the demote-branch bumps:
    _now_iso has 1-second granularity, so a same-second mutation may keep
    the same string. The per-scope updated_at on the demoted row is the
    audit-trail field that matters; the doc-level bump is just an mtime.)"""
    st = ds.init_state(SCOPES)
    ds.complete_scope(st, "topic-design")
    before = st["updated_at"]
    st_noop, demoted_noop = ds.reconcile_with_artifacts(
        st, evidence_exists=lambda _s: True)
    assert demoted_noop == [] and st_noop["updated_at"] == before
