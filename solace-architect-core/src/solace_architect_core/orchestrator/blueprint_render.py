"""Deterministic blueprint assembly.

The blueprint is the final document that gathers every design artifact into one
narrative. Assembly + structured rendering is mechanical (and prose generation
is the worst stall point — same lesson as design's Phase C). So we render the
document SKELETON here — every section's structured content laid out from the
artifacts, deterministically — and leave clearly-marked ``<!-- NARRATIVE -->``
placeholders for the LLM to expand into prose. The blueprint agent then writes
only the genuinely-narrative bits over a complete, correct structural spine,
instead of re-reading ~20 artifacts and re-stating their contents (many turns).

Reuses ``prose.py``'s generic structured→markdown renderer. Pure function over
parsed artifacts + decisions + brief.
"""

from __future__ import annotations

from typing import Any, Optional

from . import prose

# Document section order: (artifact-name, heading). Absent artifacts are skipped.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("topic-design/topic-taxonomy.yaml", "Topic Taxonomy"),
    ("broker-select/broker-recommendation.yaml", "Broker Selection & Sizing"),
    ("protocol-select/protocol-map.yaml", "Protocol Map"),
    ("integration/integration-map.yaml", "Micro-Integration Strategy"),
    ("mesh-design/dmr-topology.yaml", "DMR Mesh Topology"),
    ("ha-dr/ha-dr-design.yaml", "High Availability & Disaster Recovery"),
    ("sam-design/sam-topology.yaml", "Solace Agent Mesh"),
    ("event-portal/event-portal-model.yaml", "Event Portal Model"),
    ("migration/migration-plan.yaml", "Migration Plan"),
)


def _dig(d: Any, *path: str) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _narrative(hint: str) -> str:
    """A placeholder the blueprint agent replaces with prose (and that survives
    untouched if it doesn't — never a broken document)."""
    return f"<!-- NARRATIVE: {hint} -->"


def _render_body(data: Any) -> list[str]:
    """Render one artifact's structured content as markdown sub-sections."""
    lines: list[str] = []
    if not isinstance(data, dict):
        lines.append(prose._fmt_scalar(data))
        return lines
    for k, v in data.items():
        if k in prose._SKIP_KEYS:
            continue
        lines.append(f"### {prose._titleize(k)}")
        lines.append("")
        if prose._is_scalar(v):
            lines.append(prose._fmt_scalar(v))
        elif isinstance(v, dict):
            lines.extend(prose._render_mapping(v, 0))
        elif isinstance(v, list):
            lines.extend(prose._render_list(v, 0))
        lines.append("")
    return lines


def present_sections(parsed_artifacts: dict[str, Any]) -> list[str]:
    """Headings that will render (their artifact exists)."""
    return [title for name, title in _SECTIONS if parsed_artifacts.get(name) is not None]


def render_blueprint(brief: dict,
                     parsed_artifacts: dict[str, Any],
                     decisions: Optional[list] = None) -> str:
    """The full blueprint document skeleton: structured content + narrative slots."""
    proj = _dig(brief, "project", "name") or _dig(brief, "project", "id") or "Solace Architecture"
    out: list[str] = [
        f"# {proj} — Solace Architecture Blueprint",
        "",
        "## Executive Summary",
        "",
        _narrative("2–3 paragraph executive summary: business drivers, the chosen "
                   "architecture in a sentence, and the key trade-offs."),
        "",
    ]
    for name, title in _SECTIONS:
        data = parsed_artifacts.get(name)
        if data is None:
            continue
        out.append(f"## {title}")
        out.append("")
        out.append(_narrative(f"One-paragraph rationale framing {title} in user-outcome terms."))
        out.append("")
        out.extend(_render_body(data))

    if decisions:
        out.append("## Decisions Register")
        out.append("")
        out.extend(prose._render_list(decisions, 0))
        out.append("")

    return "\n".join(out).rstrip() + "\n"
