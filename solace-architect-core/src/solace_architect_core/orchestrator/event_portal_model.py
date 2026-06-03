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


# Trailing-parenthetical pattern. Catches the "supplier-edi-messages (will be
# migrated to Solace JMS or REST)" shape — a description fragment carried into
# the event/system NAME field by intake. Carries through to EP Designer where
# it becomes part of the published event name + schema name + graph label.
# Normalize at model-build time so downstream artifacts stay clean even when
# upstream data is dirty; the stripped description is preserved as a
# ``description`` field so the annotation isn't lost.
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _clean_event_name(name: str) -> tuple[str, Optional[str]]:
    """Strip a trailing parenthetical annotation from an event/system name.

    Returns ``(clean_name, stripped_description_or_None)``. Whitespace-trimmed.
    Idempotent: a name without a trailing parenthetical returns unchanged with
    a None description. Only the LAST trailing parenthetical is stripped — an
    inner ``foo (bar) baz`` is intentionally left alone (it isn't the bug we
    saw, and stripping it would change semantics).
    """
    s = str(name or "").strip()
    if not s:
        return s, None
    m = _TRAILING_PAREN_RE.search(s)
    if not m:
        return s, None
    return s[:m.start()].strip(), m.group(0).strip(" ()").strip() or None


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
    # Names are normalized: trailing parentheticals (description fragments that
    # intake sometimes lets through) are stripped from the name and preserved as
    # a description on the event row.
    for s in _system_list(brief):
        for ev in (s.get("events") or []):
            if not ev:
                continue
            clean, desc = _clean_event_name(ev)
            if not clean:
                continue
            key = _norm(clean)
            if key not in events:
                row: dict = {"name": clean, "version": "v1", "source": "landscape"}
                if desc:
                    row["description"] = desc
                events[key] = row
            elif desc and not events[key].get("description"):
                # An earlier taxonomy-derived row may have no description; let
                # the landscape's annotation backfill it.
                events[key]["description"] = desc
    return list(events.values())


# ── applications ──────────────────────────────────────────────────────────────


def _system_list(brief: dict) -> list[dict]:
    systems = _dig(brief, "landscape", "systems") or _dig(brief, "systems") or []
    return [s for s in systems if isinstance(s, dict)] if isinstance(systems, list) else []


def derive_applications(brief: dict) -> list[dict]:
    """Each landscape system becomes an application; role decides publish vs
    subscribe of its declared events.

    Names are normalized — both the application's own name and every event in
    publishes/subscribes — so an EP graph that derived from a dirty intake
    still gets canonical (no-parenthetical) names. The stripped description
    is preserved on the app row as ``description`` for downstream consumers
    that want to surface it (e.g. an EP Designer description field).
    """
    apps: list[dict] = []
    for s in _system_list(brief):
        role = (s.get("role") or "").lower()
        evs = [c for c in
               ((_clean_event_name(e)[0] for e in (s.get("events") or [])))
               if c]
        publishes = evs if role in ("producer", "both") else []
        subscribes = evs if role in ("consumer", "both") else []
        app_name, app_desc = _clean_event_name(s.get("name") or "(unnamed)")
        row: dict = {
            "name": app_name,
            "role": role or None,
            "publishes": publishes,
            "subscribes": subscribes,
        }
        if app_desc:
            row["description"] = app_desc
        apps.append(row)
    return apps


# ── schemas ──────────────────────────────────────────────────────────────────


def derive_schemas(events: list[dict]) -> list[dict]:
    """One JSON-schema PLACEHOLDER per event payload (1:1 with the event).

    The design phase can't know the real field set, so each schema is a stub
    (``type: object`` + an inferred id property) the EP agent/user fills in. But
    without it the EP model has no schema layer at all — so provisioning creates
    no schemas and binds no event to a schema version. Emitting a stub gives
    provisioning a schema to create and an event→schema binding to declare; the
    ``placeholder`` flag marks it for replacement with the real payload.
    """
    schemas: list[dict] = []
    for ev in events:
        name = ev.get("name") or "event"
        noun = ev.get("noun")
        id_prop = f"{noun}Id" if noun else "id"
        schemas.append({
            "name": f"{name}.schema",
            "schema_type": "jsonSchema",
            "content_type": "application/json",
            "version": ev.get("version", "v1"),
            "event": name,
            "placeholder": True,
            "content": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": f"{name} payload",
                "type": "object",
                "properties": {
                    id_prop: {"type": "string",
                              "description": f"Identifier of the {noun or 'entity'}."},
                    "eventTime": {"type": "string", "format": "date-time"},
                },
                "required": [id_prop],
            },
            "note": ("PLACEHOLDER schema — replace properties with the real payload "
                     "before provisioning."),
        })
    return schemas


# ── aggregate ────────────────────────────────────────────────────────────────


def derive_event_portal_model(taxonomy: Optional[dict], brief: dict) -> dict:
    """Full starting EP model: domains + schemas + applications + event catalog."""
    taxonomy = taxonomy if isinstance(taxonomy, dict) else {}
    domains = derive_domains(taxonomy, brief)
    events = derive_events(taxonomy, brief)
    schemas = derive_schemas(events)
    # Bind each event to its (1:1) schema so provisioning can declare the
    # event→schema-version relationship.
    schema_by_event = {s["event"]: s["name"] for s in schemas}
    for ev in events:
        ev["schema"] = schema_by_event.get(ev.get("name"))
    apps = derive_applications(brief)

    # Surface "consumer-with-no-subscriptions" data-completeness gaps.
    # Discovery sometimes asks for the system list + role but forgets to elicit
    # the per-consumer event subscriptions, leaving the EP model with
    # floating consumer apps (zero edges in the EP Designer graph). They still
    # provision OK as standalone apps, but the user sees a disconnected graph
    # and reasonably calls it "messed up". List them here so validation /
    # provisioning can record open items and the user can see what's missing.
    gaps: list[dict] = []
    for app in apps:
        role = (app.get("role") or "")
        if role in ("consumer", "both") and not app.get("subscribes"):
            gaps.append({
                "kind": "consumer_without_subscriptions",
                "application": app["name"],
                "severity": "advisory",
                "detail": (f"Application {app['name']!r} is a {role} but the brief "
                           "declares no subscribed events. The EP graph will show it "
                           "as a floating node with no edges. Update the brief's "
                           "landscape.systems[].events for this system and re-run "
                           "Design + Event Portal."),
            })

    note = ("Starting EP model derived deterministically from topic-taxonomy "
            "(domain + noun/verb vocabulary) + landscape (apps + pub/sub roles). "
            "Schemas are PLACEHOLDER stubs (one per event) — replace payloads "
            "with the real fields. EP agent: push these via the EP MCP and "
            "reconcile; do NOT re-derive.")
    if gaps:
        _names = ", ".join(g["application"] for g in gaps)
        note += (f" ⚠ {len(gaps)} consumer(s) without subscriptions ({_names}) — "
                 "the EP graph will show them as floating nodes; see model.gaps.")

    return {
        "domains": domains,
        "schemas": schemas,
        "applications": apps,
        "events": events,
        "counts": {"domains": len(domains), "schemas": len(schemas),
                   "applications": len(apps), "events": len(events)},
        "gaps": gaps,
        "note": note,
    }
