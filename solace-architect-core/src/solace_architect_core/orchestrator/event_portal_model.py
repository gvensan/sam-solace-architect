"""Deterministic Event Portal model derivation.

The EP model (application domains, applications, events) is largely a TRANSFORM
of artifacts the design phase already produced: the topic taxonomy carries the
domain + the noun/verb event vocabulary; the landscape carries the systems that
become applications and their publish/subscribe roles. So we derive a starting
EP model HERE, deterministically, and the SAEventPortalAgent's job collapses to
pushing it via the EP MCP (createApplicationVersion / createEventVersion) and
reconciling — rather than re-deriving the whole model with the LLM (many turns,
and the EP MCP's $ref quirks already make each call fragile).

Pure functions over the parsed taxonomy + brief — unit-testable without storage.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def _dig(d: Any, *path: str) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _norm(s: str) -> str:
    """Normalise an event name for cross-source dedup (kebab/camel/snake → flat)."""
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


# ── domains ───────────────────────────────────────────────────────────────────


def derive_domains(taxonomy: dict, brief: dict) -> list[dict]:
    """Application domains from the taxonomy's domain level; fall back to the
    project name so we always emit at least one domain."""
    vals = _dig(taxonomy, "levels", "domain", "values")
    names: list[str] = []
    if isinstance(vals, list):
        names = [str(v) for v in vals if v]
    elif isinstance(vals, dict):
        names = [str(k) for k in vals]
    if not names:
        proj = _dig(brief, "project", "name") or _dig(brief, "project", "id") or "default"
        names = [str(proj)]
    return [{"name": n, "description": f"Application domain for {n} events."} for n in names]


# ── events ────────────────────────────────────────────────────────────────────


def _pattern_positions(taxonomy: dict) -> dict[str, int]:
    """Map level-name → 0-based position from ``structure.pattern`` (e.g.
    ``{region}/{domain}/{noun}/{verb}/...``). Empty if no pattern."""
    pat = _dig(taxonomy, "structure", "pattern")
    if not isinstance(pat, str):
        return {}
    toks = pat.split("/")
    out: dict[str, int] = {}
    for i, tok in enumerate(toks):
        m = re.match(r"\{(\w+)", tok.strip())
        if m:
            out[m.group(1)] = i
    return out


def derive_events(taxonomy: dict, brief: dict) -> list[dict]:
    """Event catalog from the taxonomy's example topics (parsed by the declared
    pattern positions) unioned with each landscape system's declared events."""
    events: dict[str, dict] = {}   # normalised-name → event

    pos = _pattern_positions(taxonomy)
    ex = _dig(taxonomy, "example_topics")
    if isinstance(ex, list) and "noun" in pos and "verb" in pos:
        for item in ex:
            topic = item.get("topic") if isinstance(item, dict) else (item if isinstance(item, str) else None)
            if not topic:
                continue
            parts = str(topic).split("/")
            if len(parts) <= max(pos["noun"], pos["verb"]):
                continue
            noun, verb = parts[pos["noun"]], parts[pos["verb"]]
            domain = parts[pos["domain"]] if "domain" in pos and len(parts) > pos["domain"] else None
            name = f"{noun}.{verb}"
            events.setdefault(_norm(name), {
                "name": name, "noun": noun, "verb": verb, "domain": domain,
                "version": "v1", "source": "taxonomy"})

    # Union in events declared on landscape systems (e.g. "shipment-status-updated").
    for s in _system_list(brief):
        for ev in (s.get("events") or []):
            if not ev:
                continue
            key = _norm(ev)
            if key not in events:
                events[key] = {"name": str(ev), "version": "v1", "source": "landscape"}
    return list(events.values())


# ── applications ──────────────────────────────────────────────────────────────


def _system_list(brief: dict) -> list[dict]:
    systems = _dig(brief, "landscape", "systems") or _dig(brief, "systems") or []
    return [s for s in systems if isinstance(s, dict)] if isinstance(systems, list) else []


def derive_applications(brief: dict) -> list[dict]:
    """Each landscape system becomes an application; role decides publish vs
    subscribe of its declared events."""
    apps: list[dict] = []
    for s in _system_list(brief):
        role = (s.get("role") or "").lower()
        evs = [str(e) for e in (s.get("events") or []) if e]
        publishes = evs if role in ("producer", "both") else []
        subscribes = evs if role in ("consumer", "both") else []
        apps.append({
            "name": s.get("name") or "(unnamed)",
            "role": role or None,
            "publishes": publishes,
            "subscribes": subscribes,
        })
    return apps


# ── aggregate ────────────────────────────────────────────────────────────────


def derive_event_portal_model(taxonomy: Optional[dict], brief: dict) -> dict:
    """Full starting EP model: domains + applications + event catalog."""
    taxonomy = taxonomy if isinstance(taxonomy, dict) else {}
    domains = derive_domains(taxonomy, brief)
    events = derive_events(taxonomy, brief)
    apps = derive_applications(brief)
    return {
        "domains": domains,
        "applications": apps,
        "events": events,
        "counts": {"domains": len(domains), "applications": len(apps), "events": len(events)},
        "note": ("Starting EP model derived deterministically from topic-taxonomy "
                 "(domain + noun/verb vocabulary) + landscape (apps + pub/sub roles). "
                 "EP agent: push these via the EP MCP and reconcile; do NOT re-derive."),
    }
