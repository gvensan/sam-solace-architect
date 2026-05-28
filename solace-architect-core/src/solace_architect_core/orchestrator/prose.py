"""Deterministic prose rendering for design scopes (Phase C).

Workers emit ONLY the structured YAML artifact — the durable, downstream-
consumed source of truth. The human-readable per-scope markdown companion is
rendered HERE, by code, from that YAML: no LLM, no extra turn, no stream that
can stall mid-generation (the prose write was the classic engine's worst stall
point). Rich narrative is a blueprint-assembly concern; this produces a
faithful, readable structured summary that always succeeds.

Pure functions only — `render_scope_markdown(scope, data) -> str`, no I/O.
"""

from __future__ import annotations

from typing import Any

SCOPE_TITLES = {
    "topic-design": "Topic Taxonomy",
    "broker-select": "Broker Selection",
    "protocol-select": "Protocol Map",
    "integration": "Micro-Integration Strategy",
    "mesh-design": "DMR Mesh Topology",
    "ha-dr": "HA / DR Design",
    "sam-design": "Solace Agent Mesh Topology",
    "event-portal": "Event Portal Model",
    "migration": "Migration Plan",
}

# Structural/meta keys carried in every artifact — not worth rendering as prose.
_SKIP_KEYS = {"schema_version", "engagement_id", "scope"}


def _titleize(key: str) -> str:
    return str(key).replace("_", " ").replace("-", " ").strip().capitalize()


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _fmt_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if v is None:
        return "—"
    return str(v)


def _render_list(items: list, indent: int) -> list:
    pad = "  " * indent
    lines: list = []
    if all(_is_scalar(it) for it in items):
        lines.extend(f"{pad}- {_fmt_scalar(it)}" for it in items)
        return lines
    for it in items:
        if isinstance(it, dict):
            # Lead each record with a recognizable name field when present.
            lead = it.get("name") or it.get("id") or it.get("title")
            if lead is not None:
                lines.append(f"{pad}- **{_fmt_scalar(lead)}**")
                rest = {k: v for k, v in it.items() if k not in ("name", "id", "title")}
                lines.extend(_render_mapping(rest, indent + 1))
            else:
                lines.extend(_render_mapping(it, indent + 1))
        elif isinstance(it, list):
            lines.extend(_render_list(it, indent + 1))
        else:
            lines.append(f"{pad}- {_fmt_scalar(it)}")
    return lines


def _render_mapping(d: dict, indent: int) -> list:
    pad = "  " * indent
    lines: list = []
    for k, v in d.items():
        kt = _titleize(k)
        if _is_scalar(v):
            lines.append(f"{pad}- **{kt}**: {_fmt_scalar(v)}")
        elif isinstance(v, dict):
            lines.append(f"{pad}- **{kt}**:")
            lines.extend(_render_mapping(v, indent + 1))
        elif isinstance(v, list):
            lines.append(f"{pad}- **{kt}**:")
            lines.extend(_render_list(v, indent + 1))
    return lines


def render_scope_markdown(scope: str, data: Any) -> str:
    """Render a readable markdown summary of a scope's structured artifact."""
    title = SCOPE_TITLES.get(scope, _titleize(scope))
    out = [
        f"# {title}",
        "",
        f"_Rendered from the `{scope}` structured artifact — the source of truth. "
        f"Edit the YAML, not this file._",
        "",
    ]
    if not isinstance(data, dict):
        out.append(_fmt_scalar(data))
        return "\n".join(out).rstrip() + "\n"
    for k, v in data.items():
        if k in _SKIP_KEYS:
            continue
        out.append(f"## {_titleize(k)}")
        out.append("")
        if _is_scalar(v):
            out.append(_fmt_scalar(v))
        elif isinstance(v, dict):
            out.extend(_render_mapping(v, 0))
        elif isinstance(v, list):
            out.extend(_render_list(v, 0))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
