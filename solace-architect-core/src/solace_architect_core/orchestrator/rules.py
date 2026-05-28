"""Deterministic decision rules for the *decidable* design scopes (Phase B).

Several design scopes are decisions over discovery inputs, not open creativity:
broker sizing is arithmetic; mesh topology and HA/DR baseline follow from the
brief's topology / delivery guarantees. Computing them HERE — deterministically,
testably — means the LLM worker is used only to write rationale and the
genuinely-open parts, never to do arithmetic it can get wrong. Reproducible,
defensible, and a turn that does less is a turn that's less likely to stall.

Pure functions only. The orchestrator computes a scope's rules from the brief
and injects them (authoritatively) into the WORKER MODE kickoff. topic-design,
sam-design, and event-portal stay fully LLM-driven (genuinely open design).
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Scopes this module decides (others are open design → no rules block).
DECIDABLE_SCOPES = ("broker-select", "mesh-design", "ha-dr", "integration")


def _dig(d: Any, *path: str) -> Any:
    """Walk a dotted path through nested dicts; None if any hop is missing."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first(d: dict, *candidates) -> Any:
    """First non-None value among several dotted paths (tolerates schema drift
    between intake and brief field names)."""
    for path in candidates:
        val = _dig(d, *path.split("."))
        if val is not None:
            return val
    return None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── broker sizing (arithmetic — the strongest rules case) ────────────────────


def broker_sizing(brief: dict) -> dict:
    """Spool, throughput band, and recommended service class from event volume.

    Spool follows the documented methodology:
        spool_gb = rate(ev/s) × msg_size_kb × retention_seconds ÷ 1e6
    (e.g. 2000 × 5 × 86400 ÷ 1e6 = 864 GB). The deployment MODEL (Cloud /
    Software / Appliance) is a separate, non-sizing decision left to the worker.
    """
    rate = _num(_first(brief,
                        "requirements.event_volume.peak_events_per_sec",
                        "requirements.event_volume.event_rate_per_sec",
                        "requirements.event_rate_per_sec", "event_rate_per_sec"))
    size_kb = _num(_first(brief,
                          "requirements.event_volume.average_message_size_kb",
                          "requirements.event_volume.avg_message_size_kb",
                          "avg_message_size_kb"))
    retention_h = _num(_first(brief,
                              "requirements.event_volume.retention_hours",
                              "requirements.retention_hours", "retention_hours"))
    delivery = (_first(brief, "requirements.delivery_mode", "delivery_mode") or "").lower()

    out: dict = {"inputs": {
        "event_rate_per_sec": rate, "avg_message_size_kb": size_kb,
        "retention_hours": retention_h, "delivery_mode": delivery or None,
    }}
    if rate is None or size_kb is None:
        out["computed"] = None
        out["note"] = "Insufficient event-volume inputs in brief; worker must size manually."
        return out

    ingress_mb_per_sec = round(rate * size_kb / 1000.0, 2)
    band = _throughput_band(rate, ingress_mb_per_sec)
    spool_gb = None
    spool_calc = None
    if retention_h is not None:
        spool_gb = round(rate * size_kb * (retention_h * 3600) / 1_000_000.0, 1)
        spool_calc = (f"{int(rate)} ev/s × {int(size_kb)} KB × {int(retention_h*3600)} s "
                      f"÷ 1,000,000 = {spool_gb} GB")
    guaranteed = delivery in ("guaranteed", "mixed")
    out["computed"] = {
        "ingress_mb_per_sec": ingress_mb_per_sec,
        "throughput_band": band,
        "spool_gb_per_region": spool_gb,
        "spool_calculation": spool_calc,
        "recommended_service_class": _service_class(band, guaranteed),
    }
    return out


def _throughput_band(rate: float, mbps: float) -> str:
    def by_rate(r):
        if r < 1000: return "low"
        if r < 10000: return "medium"
        if r < 100000: return "high"
        return "very-high"
    def by_mbps(m):
        if m < 5: return "low"
        if m < 50: return "medium"
        if m < 500: return "high"
        return "very-high"
    order = ["low", "medium", "high", "very-high"]
    return max(by_rate(rate), by_mbps(mbps), key=order.index)


def _service_class(band: str, guaranteed: bool) -> str:
    if band == "very-high":
        return "Enterprise Kilo"
    if band == "low" and not guaranteed:
        return "Developer"
    return "Enterprise"


# ── mesh topology (follows from sites / topology / residency) ────────────────


def mesh_topology(brief: dict) -> dict:
    topology = (_first(brief, "requirements.topology", "topology") or "").lower()
    sites = _first(brief, "requirements.sites", "sites") or []
    residency = _first(brief, "requirements.data_residency_constraints",
                       "requirements.data_residency", "data_residency_constraints")
    has_residency = bool(residency)

    if topology in ("multi-region", "hybrid-cloud", "hybrid"):
        kind = "DMR external-link federation (per-region brokers linked)"
    elif topology in ("multi-site", "multi-az") or (isinstance(sites, list) and len(sites) > 1):
        kind = "DMR cluster"
    else:
        kind = "single broker (no mesh required)"
    return {
        "topology_input": topology or None,
        "site_count": len(sites) if isinstance(sites, list) else None,
        "recommended_mesh": kind,
        "replication": "selective per data-residency policy" if has_residency else "full DMR",
        "data_residency": bool(has_residency),
    }


# ── HA/DR baseline (follows from delivery guarantees) ────────────────────────


def hadr_baseline(brief: dict) -> dict:
    delivery = (_first(brief, "requirements.delivery_mode", "delivery_mode") or "").lower()
    guarantee = (_first(brief, "requirements.processing_guarantee",
                        "processing_guarantee") or "").lower()
    ha_required = delivery in ("guaranteed", "mixed") or guarantee in ("at-least-once", "exactly-once")
    return {
        "delivery_mode": delivery or None,
        "processing_guarantee": guarantee or None,
        "ha_required": ha_required,
        "recommended": (
            "HA redundancy group (active/standby) per site; DR via cross-site replication"
            if ha_required else
            "single broker acceptable; HA optional"
        ),
    }


# ── integration map (per-backend-system strategy — the highest-fan-out scope) ─
#
# Integration is the scope that fails most: one strategy decision PER backend
# system (8 in the supply-chain engagement) means ~6 sequential LLM turns — each
# a grounding/fetch/reason round-trip exposed to the gateway — and the scope
# rarely survives all of them before a stall, so the artifact never lands. But
# each system's strategy is decidable from the brief: its supported protocols +
# role + Micro-Integration availability. Computing the whole map here collapses
# those turns: the worker writes integration-map.yaml from these rows in one
# turn instead of deriving each system live.


# Brief protocol strings ("REST, AMQP") → canonical Solace transport tokens.
# JDBC / "S3 API" etc. are storage/DB protocols, not Solace transports — they're
# intentionally NOT mapped, so they fall through to the REST/role default.
_PROTO_KEYS = ("websocket", "kafka", "amqp", "mqtt", "jms", "rest", "smf")


def _parse_protocols(raw: Any) -> list[str]:
    """Canonical transport tokens present in a brief protocol string, in
    the order they're recognised (deduped)."""
    text = str(raw or "").lower()
    toks = [t.strip() for t in re.split(r"[,/|]", text)]
    found: list[str] = []
    for t in toks:
        for key in _PROTO_KEYS:
            if key in t and key not in found:
                found.append(key)
    return found


def _integration_strategy(role: str, protos: list[str]) -> tuple[Optional[str], str]:
    """(recommended_protocol, mechanism) for one system. Priority order is
    purpose-fit, validated to reproduce the engagement's hand-made decisions:
    Kafka bridge → WebSocket push (client-facing consumers) → JMS (transactional)
    → MQTT (devices) → AMQP (only when REST absent) → REST by role."""
    r = (role or "").lower()
    P = set(protos)
    consumer_like = r in ("consumer", "both")
    if "kafka" in P:
        return "Kafka", "Solace PubSub+ Connector for Kafka (Kafka↔Solace bridge)"
    if "websocket" in P and consumer_like:
        return "WebSocket", "WebSocket push (Solace → client) for real-time delivery"
    if "jms" in P:
        return "JMS 2.0", "Solace JMS API (transactional / bi-directional)"
    if "mqtt" in P:
        return "MQTT 3.1.1", "MQTT publish/subscribe (QoS-mapped to Solace)"
    if "amqp" in P and "rest" not in P:
        return "AMQP 1.0", "AMQP 1.0 messaging"
    if "rest" in P:
        if r == "consumer":
            return "REST", "REST Delivery Point (Solace → system push)"
        if r == "both":
            return "REST", "REST Delivery Point + REST producer (bi-directional)"
        return "REST", "REST messaging (system → Solace via REST producer / inbound RDP)"
    return None, "no recognised Solace transport in brief protocols — worker must decide"


_DIRECTION = {
    "producer": "inbound (system → Solace)",
    "consumer": "outbound (Solace → system)",
    "both": "bidirectional",
}


def integration_map(brief: dict) -> dict:
    """Per-system integration strategy for every backend in the brief landscape."""
    systems = _first(brief, "landscape.systems", "systems") or []
    rows: list[dict] = []
    unresolved: list[str] = []
    for s in systems if isinstance(systems, list) else []:
        if not isinstance(s, dict):
            continue
        name = s.get("name") or "(unnamed)"
        role = s.get("role")
        protos = _parse_protocols(s.get("protocol"))
        proto, mechanism = _integration_strategy(role, protos)
        mi = s.get("mi_availability") if isinstance(s.get("mi_availability"), dict) else {}
        mi_direct = mi.get("direct")
        mi_indirect = mi.get("indirect_via")
        rows.append({
            "system": name,
            "role": role,
            "available_protocols": protos,
            "recommended_protocol": proto,
            "mechanism": mechanism,
            "direction": _DIRECTION.get((role or "").lower(), "unknown"),
            "mi_direct": mi_direct,
            "mi_indirect_via": mi_indirect,
        })
        # Flag systems that need a human call: no recognised transport, or no
        # Micro-Integration path at all (neither direct nor an indirect bridge).
        if proto is None or (mi_direct is False and not mi_indirect):
            unresolved.append(name)
    return {
        "system_count": len(rows),
        "systems": rows,
        "unresolved": unresolved,
        "note": ("Per-system strategy derived deterministically from brief "
                 "protocol + role + Micro-Integration availability. Worker: write "
                 "integration-map.yaml from these rows in ONE turn; only ask the "
                 "user about systems in 'unresolved'."),
    }


# ── dispatch + kickoff rendering ─────────────────────────────────────────────


def compute_scope_rules(scope: str, brief: dict) -> Optional[dict]:
    """Deterministic decision inputs for a decidable scope, else None."""
    if scope == "broker-select":
        return {"sizing": broker_sizing(brief)}
    if scope == "mesh-design":
        return {"mesh": mesh_topology(brief)}
    if scope == "ha-dr":
        return {"hadr": hadr_baseline(brief)}
    if scope == "integration":
        return {"integration": integration_map(brief)}
    return None


def render_rules_block(scope: str, rules: dict) -> str:
    """A short authoritative block for the WORKER MODE kickoff so the worker uses
    these exact computed values rather than re-deriving (or hallucinating) them."""
    import json
    return (
        "COMPUTED (authoritative — use these exact values; do NOT recompute):\n"
        + json.dumps(rules, indent=2, default=str)
    )
