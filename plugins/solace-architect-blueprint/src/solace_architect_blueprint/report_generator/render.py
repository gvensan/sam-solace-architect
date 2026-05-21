"""V2 audience-pack renderer — full port of V1's HTML report generator.

Layout, sections, and visual language match V1 exactly. The Python file
assembles the HTML server-side; the resulting file is self-contained
(CSS inline from templates/report.css; JS inline from templates/report.js;
mermaid/marked loaded from CDN at view time for HTML, pre-rendered to SVG
via mmdc for PDF).

Per-pack differentiation (artifact/section/decision/finding filters)
matches solace_architect_core/configs/report-packs.yaml.

Phase 3a sections shipped here:
  - Page header with stats strip
  - Sticky top toolbar (theme/print/download)
  - Sidebar TOC (nested by phase group)
  - Scope & Inputs cards (parsed from discovery-brief.yaml)
  - Auto-narrative summary
  - Decisions / Findings / Open Items tables
  - Connected Systems table
  - Per-artifact sections with header (title/path/desc/copy) + body
    rendered as proper HTML (markdown→HTML; mermaid→SVG-or-raw; yaml→code)

Phase 3b sections (ROI Framework with interactive sliders + sensitivity
combined card) ship from the same render path; the executive pack is the
only one that includes them.
"""

from __future__ import annotations

import html as _html
import json as _json
import os
import re
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    import markdown as _markdown
except ImportError:  # pragma: no cover — declared in pyproject deps
    _markdown = None  # type: ignore[assignment]

from solace_architect_core._storage import read_text, read_yaml, safe_artifact_path
from solace_architect_core.tools.artifact_tools import ToolResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Phase grouping — maps the first path segment of an artifact filename
# (after any leading zero-prefix like "12-blueprint/") to a human-readable
# group label. Mirrors V1's GROUP_LABELS but with V2's scope names.
_GROUP_LABELS = {
    "discovery": "Discovery",
    "topic-design": "Topic Design",
    "broker-select": "Broker Selection",
    "sam-design": "SAM Design",
    "protocol-select": "Protocol Selection",
    "mesh-design": "Mesh Design",
    "ha-dr": "High Availability / Disaster Recovery",
    "integration": "Integration",
    "migration": "Migration",
    "event-portal": "Event Portal",
    "reviews": "Reviews",
    "validation": "Validation",
    "blueprint": "Technical Blueprint",
    "executive": "Business Case",
    "diagrams": "Diagrams",
    "exports": "Exports",
}


# Lifecycle-step order — used to sort phase groups in the sidebar TOC.
_PHASE_ORDER = [
    "discovery", "topic-design", "broker-select", "protocol-select",
    "sam-design", "mesh-design", "ha-dr", "integration", "migration",
    "event-portal", "reviews", "validation", "blueprint", "executive",
    "diagrams", "exports",
]


# Map source_agent to a short label for the decisions/findings tables.
_AGENT_LABELS = {
    "SADiscoveryAgent": "discovery",
    "SADomainAgent": "design",
    "SAOrchestratorAgent": "orchestrator",
    "SAArchitectReviewerAgent": "architect-review",
    "SADeveloperReviewerAgent": "developer-review",
    "SAOpsReviewerAgent": "ops-review",
    "SASecurityReviewerAgent": "security-review",
    "SAValidationAgent": "validation",
    "SABlueprintAgent": "blueprint",
    "SAEventPortalAgent": "event-portal",
}


# Map source_agent to reviewer short-name for finding_skills filter.
_REVIEWER_SHORT = {
    "SAArchitectReviewerAgent": "architect",
    "SADeveloperReviewerAgent": "developer",
    "SAOpsReviewerAgent": "ops",
    "SASecurityReviewerAgent": "security",
}


# Pack labels (overridden by report-packs.yaml when present).
_PACK_LABELS = {
    "blueprint": ("Solace Blueprint", "Comprehensive engineering deliverable — full architecture, all artifacts."),
    "executive": ("Executive Team", "Business case, ROI, and recommendation in plain language."),
    "admin-ops": ("Admin & Ops", "Provisioning, monitoring, runbooks — full operational depth."),
    "security": ("Security", "Auth, ACLs, encryption, audit, PII — full security posture."),
    "developers": ("Developers", "Topics, schemas, protocols, client patterns — build correct clients."),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def esc(s: Any) -> str:
    """HTML-escape, treating None and non-strings as ''."""
    if s is None:
        return ""
    return _html.escape(str(s), quote=True)


def _anchor_for_artifact(name: str) -> str:
    """Stable anchor id for an artifact section. Mirrors V1's artId."""
    s = name.lower().replace("/", "-")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return "art-" + s


def _group_for_artifact(name: str) -> str:
    """First path segment → group key. Strips any leading numeric prefix."""
    first = name.split("/", 1)[0]
    return re.sub(r"^\d+-", "", first) or "diagrams"


def _group_label(key: str) -> str:
    return _GROUP_LABELS.get(key, key.replace("-", " ").title())


def _load_templates() -> tuple[str, str]:
    """Load the bundled CSS and JS as strings."""
    pkg = resources.files("solace_architect_blueprint") / "report_generator" / "templates"
    css = (pkg / "report.css").read_text(encoding="utf-8")
    js = (pkg / "report.js").read_text(encoding="utf-8")
    # Strip the outer <script>...</script> from report.js — we re-wrap below.
    js = re.sub(r"^\s*<script>\s*", "", js)
    js = re.sub(r"\s*<\\?/script>\s*$", "", js)
    return css, js


def _load_branding(overrides: dict | None = None) -> dict:
    text = (resources.files("solace_architect_core.configs") / "branding.yaml").read_text()
    branding = yaml.safe_load(text)
    if overrides:
        for k, v in overrides.items():
            if isinstance(branding.get(k), dict) and isinstance(v, dict):
                branding[k].update(v)
            else:
                branding[k] = v
    return branding


def _load_packs() -> dict:
    text = (resources.files("solace_architect_core.configs") / "report-packs.yaml").read_text()
    return yaml.safe_load(text) or {"packs": []}


def _pack_by_id(audience: str) -> dict:
    packs = _load_packs().get("packs", []) or []
    for p in packs:
        if p.get("id") == audience:
            return p
    # Fallback — empty filters = include everything (blueprint behaviour).
    return {"id": audience, "label": _PACK_LABELS.get(audience, (audience.title(), ""))[0]}


def _fmt_time(seconds: int | float | None) -> str:
    if not seconds:
        return "0s"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def _load_decisions(engagement_id: str) -> list[dict]:
    try:
        d = read_yaml(engagement_id, "meta/decisions.yaml", default={"decisions": []})
        return list(d.get("decisions") or [])
    except Exception:
        return []


def _load_findings(engagement_id: str) -> list[dict]:
    try:
        d = read_yaml(engagement_id, "meta/findings.yaml", default={"findings": []})
        return list(d.get("findings") or [])
    except Exception:
        return []


def _load_open_items(engagement_id: str) -> list[dict]:
    try:
        d = read_yaml(engagement_id, "meta/open-items.yaml", default={"open_items": []})
        return list(d.get("open_items") or [])
    except Exception:
        return []


def _load_brief(engagement_id: str) -> dict:
    try:
        return read_yaml(engagement_id, "discovery/discovery-brief.yaml", default={}) or {}
    except Exception:
        return {}


def _load_status(engagement_id: str) -> dict:
    try:
        return read_yaml(engagement_id, "meta/engagement-status.yaml", default={"steps": {}}) or {}
    except Exception:
        return {}


def _extract_project_name(brief: dict, engagement_id: str) -> str:
    """Project display name — from brief if present, else engagement_id."""
    pn = brief.get("project_name")
    if pn:
        return str(pn)
    project = brief.get("project")
    if isinstance(project, dict):
        n = project.get("name") or project.get("display_name")
        if n:
            return str(n)
    return engagement_id


# ---------------------------------------------------------------------------
# Pack filtering
# ---------------------------------------------------------------------------


def _filter_decisions(decisions: list[dict], pack: dict) -> list[dict]:
    skills = pack.get("decision_skills")
    if skills is None:  # omitted → show all
        return decisions
    if not skills:  # empty list → hide
        return []
    return [d for d in decisions if _agent_to_skill(d.get("source_agent", "")) in set(skills)
            or d.get("source_agent", "") in set(skills)]


def _filter_findings(findings: list[dict], pack: dict) -> list[dict]:
    skills = pack.get("finding_skills")
    if skills is None:
        return findings
    if not skills:
        return []
    targets = set(skills)
    return [f for f in findings
            if _REVIEWER_SHORT.get(f.get("source_agent", ""), "") in targets
            or f.get("source_agent", "") in targets]


def _pack_includes_section(pack: dict, section: str) -> bool:
    tops = pack.get("top_sections")
    if tops is None:
        return True
    # Map V1's section names to ours for back-compat.
    aliases = {
        "summary": ("summary", "executive summary"),
        "scope": ("scope", "scope & inputs"),
        "decisions": ("decisions",),
        "findings": ("findings", "review findings"),
        "open-items": ("open-items", "open items"),
        "connected-systems": ("connected-systems", "connected systems"),
        "artifacts": ("artifacts",),
        "roi": ("roi", "roi framework"),
    }
    candidates = aliases.get(section, (section,))
    normalised_tops = [t.strip().lower() for t in tops]
    return any(c.lower() in normalised_tops for c in candidates)


def _agent_to_skill(agent: str) -> str:
    return _AGENT_LABELS.get(agent, agent)


# ---------------------------------------------------------------------------
# Discovery brief parsing
# ---------------------------------------------------------------------------


def _systems_from_brief(brief: dict) -> list[dict]:
    """Flatten the brief's systems list to [{name, role, description}]."""
    out: list[dict] = []
    systems = brief.get("systems") or brief.get("landscape", {}).get("systems") or []
    if not isinstance(systems, list):
        return out
    for s in systems:
        if not isinstance(s, dict):
            continue
        out.append({
            "name": s.get("name") or s.get("system") or "",
            "role": s.get("role") or "",
            "description": s.get("description") or s.get("desc") or "",
        })
    return [x for x in out if x["name"]]


def _inputs_from_brief(brief: dict) -> dict:
    """Pull headline inputs (messaging, protocols, event types, requirements, goals)."""
    out: dict[str, Any] = {
        "messaging": "", "protocols": "", "ref_arch": "",
        "event_types": [], "requirements": {}, "goals": {},
    }
    landscape = brief.get("landscape") or {}
    if isinstance(landscape, dict):
        out["messaging"] = landscape.get("existing_messaging") or landscape.get("messaging") or ""
        out["protocols"] = landscape.get("protocols") or ""
        out["ref_arch"] = landscape.get("reference_architecture") or landscape.get("ref_arch") or ""
        ev = landscape.get("event_types") or []
        if isinstance(ev, list):
            out["event_types"] = [str(x) for x in ev]
    reqs = brief.get("requirements") or {}
    if isinstance(reqs, dict):
        # Pretty-print common keys with title-case labels.
        labels = {
            "delivery_mode": "Delivery guarantee", "ordering": "Ordering",
            "latency_tier": "Latency target", "scale": "Scale",
            "topology": "Topology", "processing_guarantee": "Processing guarantee",
            "regulatory": "Regulatory", "data_residency": "Data residency",
            "audit": "Audit",
        }
        for k, v in reqs.items():
            label = labels.get(k, k.replace("_", " ").title())
            if v not in (None, "", [], {}):
                out["requirements"][label] = ", ".join(v) if isinstance(v, list) else str(v)
    goals = brief.get("goals") or {}
    if isinstance(goals, dict):
        labels = {
            "project_type": "Project type", "driver": "Driver",
            "timeline": "Timeline", "budget": "Budget",
            "team": "Team", "constraints": "Constraints",
        }
        for k, v in goals.items():
            label = labels.get(k, k.replace("_", " ").title())
            if v not in (None, "", [], {}):
                out["goals"][label] = ", ".join(v) if isinstance(v, list) else str(v)
    return out


def _discovery_summary(brief: dict) -> str:
    return (brief.get("summary")
            or brief.get("description")
            or brief.get("discovery_summary")
            or "")


# ---------------------------------------------------------------------------
# Mermaid pre-render
# ---------------------------------------------------------------------------


_MMDC_BIN = shutil.which("mmdc") or shutil.which("npx")


def _mermaid_to_svg(diagram: str, *, name_hint: str = "") -> Optional[str]:
    """Render a mermaid diagram to SVG via mermaid-cli. None on any failure."""
    if not _MMDC_BIN:
        return None
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        src = td_path / "diagram.mmd"
        out = td_path / "diagram.svg"
        src.write_text(diagram, encoding="utf-8")
        # mmdc: -i input -o output. If mmdc isn't directly on PATH, try `npx`.
        cmd = (
            [_MMDC_BIN, "-i", str(src), "-o", str(out), "-q"]
            if _MMDC_BIN.endswith("mmdc")
            else [_MMDC_BIN, "-y", "@mermaid-js/mermaid-cli", "-i", str(src), "-o", str(out), "-q"]
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        except (subprocess.SubprocessError, OSError):
            return None
        if not out.exists():
            return None
        svg = out.read_text(encoding="utf-8")
        # Strip XML prolog so the SVG drops cleanly into HTML.
        svg = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg)
        return svg


# ---------------------------------------------------------------------------
# Artifact rendering
# ---------------------------------------------------------------------------


def _markdown_to_html(text: str) -> str:
    if _markdown is None:
        return f"<pre>{esc(text)}</pre>"
    md = _markdown.Markdown(extensions=[
        "extra",          # tables, fenced code, attr_list, footnotes, ...
        "sane_lists",
        "smarty",
        "toc",
        "nl2br",
    ])
    return md.convert(text)


def _render_artifact_body(name: str, content: str) -> str:
    if name.endswith((".mermaid", ".mmd")):
        svg = _mermaid_to_svg(content, name_hint=name)
        if svg:
            return f'<div class="mermaid mermaid-rendered">{svg}</div>'
        # Fallback: raw mermaid + load mermaid.js at runtime (HTML-only).
        return f'<div class="mermaid">{esc(content)}</div>'
    if name.endswith((".yaml", ".yml")):
        return f'<pre><code class="language-yaml">{esc(content)}</code></pre>'
    if name.endswith(".json"):
        return f'<pre><code class="language-json">{esc(content)}</code></pre>'
    if name.endswith(".md"):
        return _markdown_to_html(content)
    return f"<pre>{esc(content)}</pre>"


_COPY_SEQ = 0


def _artifact_header(name: str, raw_text: str, description: str = "") -> str:
    global _COPY_SEQ
    _COPY_SEQ += 1
    copy_id = f"rpt-copy-{_COPY_SEQ}"
    title = name.rsplit("/", 1)[-1]
    return (
        '<div class="report-artifact-header">'
        '<div class="report-artifact-text">'
        f'<h4 class="report-artifact-title">{esc(title)}</h4>'
        f'<code class="report-artifact-path">{esc(name)}</code>'
        + (f'<p class="report-artifact-desc">{esc(description)}</p>' if description else "")
        + "</div>"
        f'<button class="report-copy-btn" type="button" data-copy-target="{copy_id}" title="Copy raw source to clipboard">'
        '<span class="report-copy-label">Copy</span></button>'
        f'<textarea id="{copy_id}" class="report-copy-raw" readonly aria-hidden="true">{esc(raw_text)}</textarea>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _stat_row(items: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="stat-item"><div class="stat-label">{esc(lbl)}</div>'
        f'<div class="stat-value">{esc(val)}</div></div>'
        for lbl, val in items if val not in (None, "")
    )
    return f'<div class="stat-row">{cells}</div>'


def _page_header(label: str, project_name: str, subtitle: str, stats: list[tuple[str, str]]) -> str:
    return (
        '<div class="page-header">'
        f'<p class="eyebrow">{esc(label)}</p>'
        f'<h1>{esc(project_name)}</h1>'
        + (f'<p class="subtitle">{esc(subtitle)}</p>' if subtitle else "")
        + _stat_row(stats)
        + "</div>"
    )


def _summary_section(stats: dict, systems_count: int, decisions_count: int,
                     findings_count: int, open_count: int,
                     skills_done: int = 0, skills_total: int = 0) -> str:
    """Top-of-report stats strip + discovery summary.

    Mirrors V1's stat-row (app.js:3001-3007). Each numeric stat xrefs
    into the relevant anchor when the section is rendered, so the strip
    doubles as a fast jump-bar.
    """
    skills_val = (f"{skills_done} of {skills_total}"
                  if skills_total and skills_done != skills_total
                  else (str(skills_done) if skills_done else ""))
    items: list[tuple[str, str, str | None]] = [
        ("Completed skills", skills_val, None),
        ("Artifacts", f"{stats.get('artifacts') or 0} files", None),
        ("Systems", str(systems_count) if systems_count else "", "connected-systems"),
        ("Decisions", str(decisions_count) if decisions_count else "", "decisions"),
        ("Review findings", str(findings_count) if findings_count else "", "findings"),
        ("Open items", str(open_count) if open_count else "", "open-items"),
    ]
    inner: list[str] = []
    for lbl, val, anchor in items:
        if not val:
            continue
        cell = (
            f'<div class="stat-label">{esc(lbl)}</div>'
            f'<div style="font-size:18px;font-weight:700;color:#093B5F">{esc(val)}</div>'
        )
        if anchor:
            inner.append(
                f'<div class="stat-item">'
                f'<a href="#{anchor}" class="xref-link" style="text-decoration:none">{cell}</a>'
                f'</div>'
            )
        else:
            inner.append(f'<div class="stat-item">{cell}</div>')
    return (
        '<h2 id="exec-summary">Summary</h2>'
        + (f'<p>{esc(stats.get("subtitle", ""))}</p>' if stats.get("subtitle") else "")
        + f'<div class="stat-row" style="margin-bottom:24px">{"".join(inner)}</div>'
    )


def _role_class(role: str) -> str:
    r = role.lower()
    if "both" in r or ("producer" in r and "consumer" in r):
        return "role-both"
    if "producer" in r:
        return "role-producer"
    return "role-consumer"


def _scope_section(systems: list[dict], inputs: dict) -> str:
    if not systems and not (inputs.get("messaging") or inputs.get("protocols") or inputs["event_types"]
                            or inputs["requirements"] or inputs["goals"]):
        return ""
    cards: list[str] = []

    # Systems card (wide)
    if systems:
        items = "".join(
            '<div class="scope-system">'
            f'<span class="scope-sys-name">{esc(s["name"])}</span>'
            + (f'<span class="scope-sys-role {_role_class(s["role"])}">{esc(s["role"])}</span>' if s["role"] else "")
            + "</div>"
            for s in systems
        )
        cards.append(
            '<div class="scope-card scope-card-wide">'
            '<div class="scope-card-header"><span class="scope-icon">&#9881;</span>Connected Systems'
            f'<span class="scope-count">{len(systems)} systems</span></div>'
            f'<div class="scope-card-body"><div class="scope-systems-grid">{items}</div></div>'
            "</div>"
        )

    # Current landscape card
    if inputs["messaging"] or inputs["protocols"] or inputs["ref_arch"]:
        body = ""
        if inputs["messaging"]:
            body += f'<div class="scope-field"><span class="scope-field-label">Existing messaging</span><span class="scope-field-value">{esc(inputs["messaging"])}</span></div>'
        if inputs["protocols"]:
            body += f'<div class="scope-field"><span class="scope-field-label">Protocols</span><span class="scope-field-value">{esc(inputs["protocols"])}</span></div>'
        if inputs["ref_arch"]:
            body += f'<div class="scope-field"><span class="scope-field-label">Reference architecture</span><span class="scope-field-value">{esc(inputs["ref_arch"])}</span></div>'
        cards.append(
            '<div class="scope-card scope-landscape">'
            '<div class="scope-card-header"><span class="scope-icon">&#9783;</span>Current Landscape</div>'
            f'<div class="scope-card-body">{body}</div></div>'
        )

    # Event types card
    if inputs["event_types"]:
        items = "".join(
            f'<div class="scope-event"><span class="scope-event-name">{esc(e)}</span></div>'
            for e in inputs["event_types"]
        )
        cards.append(
            '<div class="scope-card scope-events">'
            '<div class="scope-card-header"><span class="scope-icon">&#9889;</span>Event Types'
            f'<span class="scope-count">{len(inputs["event_types"])} types</span></div>'
            f'<div class="scope-card-body"><div class="scope-events-grid">{items}</div></div>'
            "</div>"
        )

    # Requirements
    if inputs["requirements"]:
        body = "".join(
            f'<div class="scope-field"><span class="scope-field-label">{esc(k)}</span>'
            f'<span class="scope-field-value">{esc(v)}</span></div>'
            for k, v in inputs["requirements"].items()
        )
        cards.append(
            '<div class="scope-card scope-requirements">'
            '<div class="scope-card-header"><span class="scope-icon">&#9745;</span>Requirements</div>'
            f'<div class="scope-card-body">{body}</div></div>'
        )

    # Goals / constraints
    if inputs["goals"]:
        body = "".join(
            f'<div class="scope-field"><span class="scope-field-label">{esc(k)}</span>'
            f'<span class="scope-field-value">{esc(v)}</span></div>'
            for k, v in inputs["goals"].items()
        )
        cards.append(
            '<div class="scope-card scope-goals">'
            '<div class="scope-card-header"><span class="scope-icon">&#9873;</span>Goals &amp; Constraints</div>'
            f'<div class="scope-card-body">{body}</div></div>'
        )

    return (
        '<h2 id="scope-inputs" style="margin-top:28px">Scope &amp; Inputs</h2>'
        '<p style="color:#5A7A94;font-size:13px;margin-bottom:12px">'
        'Key inputs from discovery that drive downstream architecture decisions.</p>'
        + f'<div class="scope-grid">{"".join(cards)}</div>'
    )


def _xref(text: str, anchor: str) -> str:
    """Anchor-link to a section by id. Mirrors V1's xref helper."""
    return f'<a href="#{anchor}" class="xref-link">{esc(text)}</a>'


def _xref_html(html: str, anchor: str) -> str:
    """Same as _xref but trusts pre-rendered HTML in the link body."""
    return f'<a href="#{anchor}" class="xref-link">{html}</a>'


def _decision_link(value: str) -> str:
    """Xref a decision label to the Decisions table (mirrors V1 decLink)."""
    if not value:
        return ""
    return _xref(value, "decisions")


def _decision_lookup(decisions: list[dict]) -> dict:
    """Build a {decision-id: selected-value} lookup. Matches V1's `dec()`.

    V1 keyed decisions by ``id`` or legacy ``decision`` field; V2 uses
    just ``id``. The selected value falls back across selected →
    recommendation → "" so the narrative remains populated even when an
    older record only had one of the fields.
    """
    out: dict[str, str] = {}
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        did = d.get("id") or d.get("decision") or ""
        if did:
            out[did] = (d.get("selected") or d.get("label")
                        or d.get("value") or d.get("choice")
                        or d.get("recommendation") or "")
    return out


def _auto_narrative(decisions: list[dict], findings: list[dict],
                    status: dict, artifacts_grouped: dict[str, list[str]]) -> str:
    """Architect-voice narrative built from the pack-filtered decisions.

    Ported from V1 (app.js:3031-3143). The structure is fixed; sub-
    sections appear only when the relevant decisions exist. Liberally
    sprinkles xref-links into Decisions / Findings / per-group anchors,
    which is the only place those links originate in V2 today.

    Sections (each conditional):
      - Recommended Architecture: Platform / Topology / Topic / Delivery /
        Mesh / HA/DR
      - Protocol Stack (table)
      - Integration (bullet list)
      - Review Outcomes (paragraph + counts)
      - Engagement Summary (table by step, with xrefs into phase groups)
    """
    dec_map = _decision_lookup(decisions)

    def dec(name: str) -> str:
        return dec_map.get(name, "")

    def has(name: str) -> bool:
        return bool(dec_map.get(name))

    broker_type = dec("broker-type")
    service_class = dec("service-class-prod")
    topology = dec("topology")
    topic_structure = dec("topic-structure")
    topic_count = dec("topic-count")
    queue_count = dec("queue-count")
    delivery_mode = dec("delivery-mode-split")
    dmr_pattern = dec("dmr-pattern")
    hub_region = dec("hub-region")
    link_count = dec("link-count")
    ha_approach = dec("ha-approach")
    dr_mode = dec("dr-replication-mode")
    dr_topology = dec("dr-topology")
    dr_scope = dec("dr-scope")
    custom_mi = dec("custom-mi-count")

    # Protocols are recorded with ids ending in -protocol (one per
    # client class). Display name = id minus suffix, dashes → spaces.
    protocols = []
    for d in decisions or []:
        did = d.get("id") or d.get("decision") or ""
        if did.endswith("-protocol"):
            name = did[:-len("-protocol")].replace("-", " ")
            val = (d.get("selected") or d.get("label") or d.get("value")
                   or d.get("choice") or d.get("recommendation") or "")
            if val:
                protocols.append((name, val))

    # Finding counts for the Review Outcomes paragraph.
    important = sum(1 for f in (findings or [])
                    if (f.get("severity") or "").lower() == "important")
    advisory = sum(1 for f in (findings or [])
                   if (f.get("severity") or "").lower() == "advisory")
    applied = sum(1 for f in (findings or [])
                  if (f.get("status") or "").lower() == "applied")

    parts: list[str] = ['<h3>Recommended Architecture</h3>']

    if broker_type or topology:
        platform_bits = []
        if broker_type:
            platform_bits.append(_decision_link(broker_type))
        if service_class:
            platform_bits.append(_decision_link(f"{service_class} service class"))
        chunk = "<p><strong>Platform:</strong> "
        chunk += ", ".join(b for b in platform_bits if b) + ". "
        if topology:
            chunk += _decision_link(topology) + ". "
        chunk += "</p>"
        parts.append(chunk)

    if topic_structure or topic_count:
        chunk = "<p><strong>Topic design:</strong> "
        if topic_structure:
            chunk += f"<code>{_decision_link(topic_structure)}</code>. "
        if topic_count:
            chunk += _decision_link(topic_count) + ". "
        if queue_count:
            chunk += _decision_link(queue_count) + ". "
        chunk += "</p>"
        parts.append(chunk)

    if delivery_mode:
        parts.append(f"<p><strong>Delivery modes:</strong> {_decision_link(delivery_mode)}</p>")

    if dmr_pattern or link_count:
        chunk = "<p><strong>Event mesh:</strong> "
        if dmr_pattern:
            chunk += _decision_link(dmr_pattern) + ". "
        if hub_region:
            chunk += "Hub: " + _decision_link(hub_region) + ". "
        if link_count:
            chunk += _decision_link(link_count) + ". "
        chunk += "</p>"
        parts.append(chunk)

    if ha_approach or dr_mode:
        chunk = "<p><strong>HA/DR:</strong> "
        if ha_approach:
            chunk += _decision_link(ha_approach) + ". "
        if dr_topology:
            chunk += _decision_link(dr_topology) + ". "
        if dr_mode:
            chunk += _decision_link(dr_mode) + ". "
        if dr_scope:
            chunk += _decision_link(dr_scope) + ". "
        chunk += "</p>"
        parts.append(chunk)

    if protocols:
        parts.append('<h3>Protocol Stack</h3>'
                     '<table><thead><tr><th>Connection</th><th>Protocol</th></tr>'
                     '</thead><tbody>')
        for name, val in protocols:
            parts.append(
                '<tr>'
                f'<td style="font-weight:600;text-transform:capitalize">{esc(name)}</td>'
                f'<td>{_decision_link(val)}</td>'
                '</tr>'
            )
        parts.append('</tbody></table>')

    if has("ibm-mq-mi") or custom_mi:
        parts.append('<h3>Integration</h3><ul>')
        if has("ibm-mq-mi"):
            parts.append(f'<li>{_decision_link(dec("ibm-mq-mi"))}</li>')
        if custom_mi:
            parts.append(f'<li>{_decision_link(custom_mi)}</li>')
        parts.append('</ul>')

    if findings:
        unique_sources = sorted({f.get("source_agent") or "" for f in findings})
        source_links = ", ".join(
            _xref(_REVIEWER_SHORT.get(s, _agent_to_skill(s)) or s, f"grp-{_GROUP_LABELS_INV.get(s, 'reviews')}")
            for s in unique_sources if s
        )
        parts.append('<h3>Review Outcomes</h3>')
        parts.append(
            "<p>"
            f'{_xref(f"{len(findings)} findings", "findings")} across '
            f'{len(unique_sources)} reviews ({source_links}): '
            f'{important} important, {advisory} advisory. '
            f'{applied} of {len(findings)} applied to the architecture.</p>'
        )

    # Engagement Summary table — one row per lifecycle step we've seen
    # in engagement-status.yaml. Each step links to its phase group in
    # the artifacts section (when artifacts exist for that group).
    steps = (status or {}).get("steps") or {}
    if steps:
        parts.append(
            '<h3>Engagement Summary</h3>'
            '<table><thead><tr><th>Step</th><th>Status</th>'
            '<th>Execution</th><th>Artifacts</th></tr></thead><tbody>'
        )
        for step_id, step_info in steps.items():
            if not isinstance(step_info, dict):
                continue
            label = _STEP_LABELS.get(step_id, step_id.replace("-", " ").title())
            grp_key = _STEP_TO_GROUP.get(step_id, step_id)
            grp_artifacts = artifacts_grouped.get(grp_key, [])
            name_html = (
                f'<span style="font-weight:600">{esc(label)}</span>'
            )
            if grp_artifacts:
                name_html = _xref_html(name_html, f"grp-{grp_key}")
            status_val = step_info.get("status", "NOT_STARTED")
            status_cell = (
                f'<span style="color:#00C895;font-weight:600">Complete</span>'
                if status_val == "DONE"
                else (f'<span style="color:#EA580C;font-weight:600">Done with concerns</span>'
                      if status_val == "DONE_WITH_CONCERNS"
                      else esc(status_val))
            )
            timing = step_info.get("timing") or {}
            exec_sec = timing.get("execution_sec")
            exec_cell = _fmt_time(exec_sec) if exec_sec else "—"
            art_count = len(grp_artifacts)
            art_cell = (
                _xref(f"{art_count} files", f"grp-{grp_key}")
                if art_count else "0 files"
            )
            parts.append(
                f'<tr><td>{name_html}</td><td>{status_cell}</td>'
                f'<td>{exec_cell}</td><td>{art_cell}</td></tr>'
            )
        parts.append('</tbody></table>')

    return "".join(parts)


# Reverse map: source_agent → phase-group key (for review xrefs).
_GROUP_LABELS_INV = {
    "SAArchitectReviewerAgent": "reviews",
    "SADeveloperReviewerAgent": "reviews",
    "SAOpsReviewerAgent": "reviews",
    "SASecurityReviewerAgent": "reviews",
    "SADiscoveryAgent": "discovery",
    "SADomainAgent": "topic-design",
    "SAValidationAgent": "validation",
    "SABlueprintAgent": "blueprint",
    "SAEventPortalAgent": "event-portal",
}

# Lifecycle step → human label (engagement summary table).
_STEP_LABELS = {
    "intake": "Intake",
    "discovery": "Discovery",
    "design": "Design",
    "review": "Review",
    "validation": "Validation",
    "event-portal": "Event Portal",
    "blueprint": "Blueprint",
}

# Step → artifact group key. Multi-scope agents (Design) map to
# topic-design as the canonical entry point.
_STEP_TO_GROUP = {
    "intake": "discovery",
    "discovery": "discovery",
    "design": "topic-design",
    "review": "reviews",
    "validation": "validation",
    "event-portal": "event-portal",
    "blueprint": "blueprint",
}

# Phase bucket → ordered list of group keys (mirrors V1's PHASE_MAP, inverted).
# Drives TOC nesting under headings: Discovery / Design / Reviews / Finalize.
_PHASE_BUCKETS: list[tuple[str, list[str]]] = [
    ("Discovery", ["discovery"]),
    ("Design", ["topic-design", "broker-select", "sam-design", "protocol-select",
                "mesh-design", "ha-dr", "integration", "migration", "event-portal"]),
    ("Reviews", ["reviews"]),
    ("Finalize", ["validation", "blueprint", "executive", "diagrams"]),
]


def _group_phase_bucket(grp_key: str) -> str:
    for bucket, groups in _PHASE_BUCKETS:
        if grp_key in groups:
            return bucket
    return "Other"


def _decisions_section(decisions: list[dict]) -> str:
    if not decisions:
        rows = '<tr><td colspan="4" style="color:#9ca3af;text-align:center">No decisions recorded</td></tr>'
    else:
        rows = "".join(
            "<tr>"
            f'<td>{esc(d.get("id"))}</td>'
            f'<td>{esc(_agent_to_skill(d.get("source_agent", "")))}</td>'
            f'<td>{esc(d.get("selected") or d.get("recommendation") or "")}</td>'
            f'<td>{esc(d.get("rationale") or d.get("context") or "")}</td>'
            "</tr>"
            for d in decisions
        )
    return (
        '<h2 id="decisions">Decisions</h2>'
        '<table><thead><tr><th>ID</th><th>Source</th><th>Selected</th><th>Rationale</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _findings_section(findings: list[dict]) -> str:
    if not findings:
        return ""
    rows = "".join(
        "<tr>"
        f'<td>{esc(f.get("id"))}</td>'
        f'<td><span class="badge badge-{esc(f.get("severity", "advisory"))}">{esc(f.get("severity", "advisory"))}</span></td>'
        f'<td>{esc(_REVIEWER_SHORT.get(f.get("source_agent", ""), f.get("source_agent", "")))}</td>'
        f'<td>{esc(f.get("description", ""))}</td>'
        f'<td>{esc(f.get("affected_artifact", ""))}</td>'
        f'<td><span class="badge badge-{esc(f.get("status", "pending"))}">{esc(f.get("status", "pending"))}</span></td>'
        "</tr>"
        for f in findings
    )
    return (
        '<h2 id="findings">Review Findings</h2>'
        '<table><thead><tr><th>ID</th><th>Severity</th><th>Source</th><th>Description</th><th>Affected</th><th>Status</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _open_items_section(items: list[dict]) -> str:
    if not items:
        return ""
    sev_color = {"blocking": "#DC2626", "advisory": "#00C895"}
    by_sev: dict[str, int] = {}
    for i in items:
        s = (i.get("severity") or "advisory").lower()
        by_sev[s] = by_sev.get(s, 0) + 1
    sev_badges = "".join(
        f'<span style="display:inline-block;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;'
        f'font-family:\'Space Mono\',monospace;text-transform:uppercase;'
        f'background:{sev_color.get(s, "#5A7A94")}15;color:{sev_color.get(s, "#5A7A94")};'
        f'border:1px solid {sev_color.get(s, "#5A7A94")}30">{by_sev[s]} {s}</span>'
        for s in ("blocking", "advisory") if by_sev.get(s)
    )
    open_count = sum(1 for i in items if (i.get("status") or "open").lower() == "open")
    rows = "".join(
        '<tr>'
        f'<td style="font-weight:700;color:#093B5F;white-space:nowrap">{esc(i.get("id"))}</td>'
        f'<td><span class="badge badge-{esc((i.get("severity") or "advisory").lower())}">'
        f'{esc((i.get("severity") or "advisory").lower())}</span></td>'
        f'<td>{esc(i.get("description"))}</td>'
        f'<td style="font-size:12px">{esc(i.get("source"))}</td>'
        f'<td style="font-size:12px;color:#4B5563">{esc(i.get("resolution_note") or "")}</td>'
        f'<td><span class="badge badge-{esc((i.get("status") or "open").lower())}">'
        f'{esc((i.get("status") or "open").lower())}</span></td>'
        "</tr>"
        for i in items
    )
    return (
        '<h2 id="open-items">Open Items</h2>'
        f'<p style="margin-bottom:16px">{open_count} of {len(items)} items remain open.</p>'
        f'<div style="display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap">{sev_badges}</div>'
        '<table><thead><tr><th style="width:60px">ID</th><th style="width:80px">Severity</th>'
        '<th>Description</th><th style="width:120px">Source</th>'
        '<th>Resolution</th><th style="width:80px">Status</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _connected_systems_section(systems: list[dict]) -> str:
    if not systems:
        return ""
    rows = "".join(
        "<tr>"
        f'<td style="font-weight:600;color:#093B5F;white-space:nowrap">{esc(s["name"])}</td>'
        f'<td style="font-size:12px;font-family:\'Space Mono\',monospace;color:#5A7A94">{esc(s["role"])}</td>'
        f'<td style="font-size:13px">{esc(s["description"])}</td>'
        "</tr>"
        for s in systems
    )
    return (
        f'<h2 id="connected-systems">Connected Systems ({len(systems)})</h2>'
        '<table class="systems-table">'
        '<thead><tr><th>System</th><th>Role</th><th>Description</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


# ---------------------------------------------------------------------------
# Artifacts section + TOC
# ---------------------------------------------------------------------------


def _sort_artifacts_by_phase(artifacts: list[str]) -> list[str]:
    def _key(name: str) -> tuple[int, str]:
        grp = _group_for_artifact(name)
        try:
            idx = _PHASE_ORDER.index(grp)
        except ValueError:
            idx = len(_PHASE_ORDER)
        return (idx, name)
    return sorted(artifacts, key=_key)


def _artifact_short_label(name: str) -> str:
    """Filename → human label (mirrors V1's artLabel: strip ext, title-case,
    upper-case known acronyms, suffix '(diagram)' for mermaid)."""
    base = name.rsplit("/", 1)[-1]
    stem, _, ext = base.rpartition(".")
    stem = stem or base
    label = re.sub(r"[-_]", " ", stem).title()
    label = re.sub(r"\b(Dmr|Ha|Dr|Mi|Dlq|Roi|Api|Acl|Sam|Smf|Mqtt|Ep)\b",
                   lambda m: m.group(0).upper(), label)
    if ext in ("mermaid", "mmd"):
        label += " (diagram)"
    return label


def _build_toc(pack: dict, sections_meta: dict, artifacts_grouped: dict[str, list[str]]) -> str:
    """Sidebar TOC: Overview block + per-phase nested artifact groups.

    Mirrors V1's tocHtml builder (app.js:2595-2633):
      - Overview header → Summary / Scope / Decisions / Findings / Open
        Items / Connected Systems / ROI links
      - Per phase bucket (Discovery / Design / Reviews / Finalize / Other):
        - Group as ``.toc-skill`` link; artifacts as ``.toc-art`` children
        - When a phase has exactly one group with ≤1 visible artifact,
          collapse to a single link (V1 isSingle branch)
    """
    lines: list[str] = ['<div class="toc-phase">Overview</div>']
    if sections_meta.get("summary"):
        lines.append('<a href="#exec-summary">Summary</a>')
    if sections_meta.get("scope"):
        lines.append('<a href="#scope-inputs">Scope &amp; Inputs</a>')
    if sections_meta.get("decisions"):
        lines.append('<a href="#decisions">Decisions</a>')
    if sections_meta.get("findings"):
        lines.append('<a href="#findings">Findings</a>')
    if sections_meta.get("open_items"):
        lines.append('<a href="#open-items">Open Items</a>')
    if sections_meta.get("connected_systems"):
        lines.append('<a href="#connected-systems">Connected Systems</a>')
    if sections_meta.get("roi"):
        lines.append('<a href="#roi-framework">ROI Framework</a>')

    if not artifacts_grouped:
        return "\n".join(lines)

    # Bucket groups by phase. Preserve _PHASE_ORDER inside each bucket.
    buckets: dict[str, list[str]] = {}
    for grp_key in artifacts_grouped.keys():
        buckets.setdefault(_group_phase_bucket(grp_key), []).append(grp_key)

    for bucket_name, _bucket_keys in _PHASE_BUCKETS + [("Other", [])]:
        p_groups = buckets.get(bucket_name, [])
        if not p_groups:
            continue
        lines.append(f'<div class="toc-phase">{esc(bucket_name)}</div>')
        is_single = len(p_groups) == 1
        for g in p_groups:
            group_arts = artifacts_grouped.get(g, [])
            # V1 collapsed huge artifact lists to .md only to keep the TOC
            # navigable; mirror that — but only for groups >20 files.
            show_arts = (group_arts if len(group_arts) <= 20
                         else [a for a in group_arts if a.endswith(".md")])

            if is_single and len(show_arts) <= 1:
                anchor = (f'#{_anchor_for_artifact(show_arts[0])}'
                          if show_arts else f'#grp-{g}')
                label = (_artifact_short_label(show_arts[0]) if show_arts
                         else _group_label(g))
                lines.append(f'<a href="{anchor}">{esc(label)}</a>')
            elif is_single:
                for a in show_arts:
                    lines.append(
                        f'<a href="#{_anchor_for_artifact(a)}">'
                        f'{esc(_artifact_short_label(a))}</a>'
                    )
            else:
                lines.append(
                    f'<a href="#grp-{g}" class="toc-skill">'
                    f'{esc(_group_label(g))}</a>'
                )
                if len(show_arts) > 1:
                    for a in show_arts:
                        lines.append(
                            f'<a href="#{_anchor_for_artifact(a)}" class="toc-art">'
                            f'{esc(_artifact_short_label(a))}</a>'
                        )
    return "\n".join(lines)


def _artifact_default_description(name: str) -> str:
    """V1's artifactDefaultDescription (app.js:1440-1465) — generic
    one-liner per (group, extension). Used when no explicit description
    is recorded for the artifact.
    """
    grp = _group_for_artifact(name)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    skill_human = _group_label(grp)
    if ext in ("mermaid", "mmd"):
        return f"Mermaid diagram from the {skill_human} step."
    if ext in ("yaml", "yml"):
        return f"Configuration produced by the {skill_human} step."
    if ext == "md":
        return f"Document produced by the {skill_human} step."
    return f"Artifact produced by the {skill_human} step."


def _artifact_descriptions(brief: dict, status: dict) -> dict[str, str]:
    """Build a {artifact-path → description} map.

    Priority: any explicit description stored on a step's ``artifacts``
    array (V1 schema, optional in V2) wins; otherwise falls back to a
    generic per-group default. We always populate a default so per-
    artifact headers carry context instead of rendering blank.
    """
    out: dict[str, str] = {}
    for step_info in (status or {}).get("steps", {}).values():
        if not isinstance(step_info, dict):
            continue
        for entry in step_info.get("artifacts") or []:
            if not isinstance(entry, dict):
                continue
            path = (entry.get("path") or "").lstrip("/")
            if path.startswith("artifacts/"):
                path = path[len("artifacts/"):]
            desc = entry.get("description")
            if path and desc:
                out[path] = desc
    return out


def _render_artifacts_block(engagement_id: str, artifacts: list[str],
                            descriptions: dict[str, str]) -> tuple[str, dict[str, list[str]]]:
    """Render the per-artifact sections + return the phase-grouped map for TOC."""
    if not artifacts:
        return "", {}
    sorted_arts = _sort_artifacts_by_phase(artifacts)
    grouped: dict[str, list[str]] = {}
    for f in sorted_arts:
        grouped.setdefault(_group_for_artifact(f), []).append(f)

    chunks: list[str] = []
    for idx, (grp_key, files) in enumerate(grouped.items()):
        # Page-break before every group except the first — keeps each
        # phase on its own printed page (mirrors V1's grp-break behavior).
        break_cls = " grp-break" if idx > 0 else ""
        chunks.append(
            f'<div class="grp-section{break_cls}" id="grp-{grp_key}">'
            f'<div class="grp-marker">{esc(_group_label(grp_key))}</div>'
        )
        for f in files:
            try:
                content = read_text(engagement_id, f)
            except (FileNotFoundError, ValueError):
                continue
            anchor = _anchor_for_artifact(f)
            desc = descriptions.get(f) or _artifact_default_description(f)
            header = _artifact_header(f, content, desc)
            body = _render_artifact_body(f, content)
            chunks.append(f'<div id="{anchor}" class="art-section">{header}{body}</div>')
        chunks.append("</div>")
    return "<h2>Artifacts</h2>" + "".join(chunks), grouped


# ---------------------------------------------------------------------------
# ROI Framework — Phase 3b (Executive pack only)
# ---------------------------------------------------------------------------


# Auto-fill rules for the Value column (V1=90% of C1, V2=80% of C2, …).
# Match V1's AUTO_V exactly so the JS engine's per-row data-attrs work.
_ROI_AUTO_V = {
    "V1": ("C1", 90, "Auto: 90% of C1 (downtime eliminated)"),
    "V2": ("C2", 80, "Auto: 80% of C2 (FTEs redirected)"),
    "V4": ("C4", 100, "Auto: 100% of C4 (compliance replaced)"),
    "V6": ("C3", 95, "Auto: 95% of C3 (transactions recovered)"),
}


def _parse_roi_md(text: str) -> tuple[dict[str, list[dict]], list[dict], dict[str, dict]]:
    """Parse roi-framework.md into (rows, indicators, guides).

    Ports V1's inline parser (app.js:2317-2353). The markdown structure
    is fixed by SAExecutiveAgent — section headers contain literal
    "Section 1:", "Section 2:", etc.; rows are pipe-tables whose first
    column matches ``^[CPV]\\d``; per-row guides are ``**C1 …**``
    paragraphs followed by free-form ask text and ``*Example: …*`` lines.
    """
    rows: dict[str, list[dict]] = {"c": [], "p": [], "v": []}
    indicators: list[dict] = []
    guides: dict[str, dict] = {}

    section = ""
    lines = text.split("\n")
    for li, line in enumerate(lines):
        if "Section 1:" in line: section = "c"
        elif "Section 2:" in line: section = "p"
        elif "Section 3:" in line: section = "v"
        elif "Section 4:" in line: section = ""
        elif "Section 6:" in line: section = "ind"

        # Section 6 — architecture indicators (3-column table).
        if section == "ind" and line.startswith("| "):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 3 and not re.match(r"^-+$", cols[0]) and cols[0] != "Indicator":
                indicators.append({"label": cols[0], "value": cols[1], "impact": cols[2]})

        # Per-row guide: paragraph beginning **C1 …**, optionally
        # followed by free-form ask text and an *Example: …* line.
        guide_match = re.match(r"^\*\*([CPV]\d)\s", line)
        if guide_match:
            gid = guide_match.group(1)
            ask_parts: list[str] = []
            cleaned = re.sub(r"^\*\*[CPV]\d\s.*?\.\*\*\s*", "", line)
            if cleaned:
                ask_parts.append(cleaned)
            for j in range(li + 1, len(lines)):
                nl = lines[j]
                if (nl.startswith("*Example:") or nl.startswith("**")
                        or nl.startswith("| ") or nl.startswith("##")
                        or not nl.strip()):
                    break
                ask_parts.append(nl)
            ex = ""
            for j in range(li + 1, min(li + 8, len(lines))):
                m = re.match(r"^\*Example:\s*(.+)\*$", lines[j])
                if m:
                    ex = m.group(1)
                    break
            guides[gid] = {"ask": re.sub(r"\s+", " ", " ".join(ask_parts)).strip(), "ex": ex}

        # C/P/V row tables.
        if not section or section == "ind" or not line.startswith("| "):
            continue
        cols = [c.strip() for c in line.split("|") if c.strip()]
        if len(cols) < 3 or not re.match(r"^[CPV]\d", cols[0]):
            continue
        rows[section].append({
            "id": cols[0],
            "label": cols[1],
            "basis": cols[-1],
        })

    return rows, indicators, guides


def _roi_example_amount(ex: str) -> str:
    """Extract the numeric example amount from a guide's *Example* string.

    Mirrors V1's exampleAmount (app.js:2356-2364). First tries an
    ``= $1,234`` / ``→ $1,234`` pattern (the "computed result" of a
    worked example); falls back to the LAST `$N` figure in the string.
    """
    if not ex:
        return ""
    m = re.search(r"[=→]\s*\$?([\d,]+)", ex)
    if m:
        try:
            return str(int(m.group(1).replace(",", "")))
        except ValueError:
            return ""
    matches = re.findall(r"\$[\d,]+", ex)
    if not matches:
        return ""
    try:
        return str(int(matches[-1].replace("$", "").replace(",", "")))
    except ValueError:
        return ""


def _roi_input_row(r: dict, group: str, guides: dict[str, dict]) -> str:
    """One input row for a Step 1/2/3 table. Mirrors V1's roiInput().

    Emits the exact DOM shape the JS engine (templates/report.js) binds
    to: ``data-group`` + ``data-id`` for live sums, ``data-auto-from``
    + ``data-auto-pct`` for cross-column auto-fill on V1/V2/V4/V6.
    """
    guide = guides.get(r["id"], {})
    auto_rule = _ROI_AUTO_V.get(r["id"])
    auto_attr = ""
    auto_hint = ""
    val_attr = ""

    if auto_rule:
        from_id, pct, label = auto_rule
        auto_attr = f' data-auto-from="{from_id}" data-auto-pct="{pct}"'
        auto_hint = (
            f'<div class="roi-auto-hint" data-hint-for="{esc(r["id"])}">'
            f'<span class="roi-auto-tag">auto-filled</span> {esc(label)}. '
            f'Edit to override; double-click to restore.</div>'
        )
    else:
        prefill = _roi_example_amount(guide.get("ex", ""))
        if prefill:
            val_attr = f' value="{prefill}"'

    aria = f"{r['id']} {r['label']}"
    ex_line = (f'<br><span class="roi-ex">Example: {esc(guide["ex"])}</span>'
               if guide.get("ex") else "")
    return (
        '<tr>'
        f'<td style="font-weight:700;color:#093B5F;vertical-align:top;padding-top:12px">{esc(r["id"])}</td>'
        '<td style="vertical-align:top;padding-top:12px">'
        f'<div>{esc(r["label"])}</div>{auto_hint}'
        f'<div class="roi-guide"><span class="roi-ask">{esc(guide.get("ask", ""))}</span>{ex_line}</div>'
        '</td>'
        '<td style="vertical-align:top;padding-top:10px">'
        f'<input type="number" class="roi-input" aria-label="{esc(aria)}" '
        f'data-group="{esc(group)}" data-id="{esc(r["id"])}"{auto_attr}{val_attr} '
        'min="0" step="1000" placeholder="0">'
        '</td>'
        f'<td style="font-size:12px;color:#5A7A94;vertical-align:top;padding-top:12px">'
        f'{_xref(esc(r["basis"]), "decisions")}</td>'
        '</tr>'
    )


def _roi_sum_row(label: str, group: str) -> str:
    return (
        f'<tr class="roi-total"><td></td>'
        f'<td><strong>{esc(label)}</strong></td>'
        f'<td><strong class="roi-sum" data-sum="{esc(group)}">$0</strong></td>'
        '<td></td></tr>'
    )


def _roi_section(engagement_id: str, artifacts: list[str], systems_count: int) -> str:
    """Full ROI calculator port from V1 (app.js:2387-2485).

    Reads ``executive/roi-framework.md`` (the standard path the Executive
    Summary pass writes), parses tables + guides, emits Foundation grid
    + Step 1-3 input tables + Step 4 results grid + Step 5 sensitivity
    sliders + Combined Scenario card + Step 6 Excel-export button. The
    interactive logic (live sums, auto-fill, sensitivity math, xlsx
    export) lives in templates/report.js — Python only emits the DOM
    shape the JS binds to.
    """
    roi_md = next((a for a in artifacts if a.endswith("roi-framework.md")), None)
    if not roi_md:
        return (
            '<h2 id="roi-framework">ROI Framework</h2>'
            '<p class="roi-intro">No ROI framework artifact found for this engagement. '
            'The Executive pack normally includes an interactive ROI calculator driven by '
            '<code>executive/roi-framework.md</code> — once that artifact is produced by the '
            'Executive Summary pass, it will render here with editable inputs and sensitivity '
            'scenarios.</p>'
        )
    try:
        roi_text = read_text(engagement_id, roi_md)
    except (FileNotFoundError, ValueError):
        return ""

    rows, indicators, guides = _parse_roi_md(roi_text)

    # Foundation: architecture indicators. The "systems connected"
    # indicator gets xrefed to the connected-systems anchor when systems
    # exist; everything else points at decisions.
    ind_cards: list[str] = []
    for ind in indicators:
        is_systems = (re.search(r"systems?\s*connected", ind["label"], re.IGNORECASE)
                      is not None) and systems_count > 0
        anchor = "connected-systems" if is_systems else "decisions"
        val_html = f'<a href="#{anchor}" class="xref-link">{esc(ind["value"])}</a>'
        lbl_html = (f'<a href="#connected-systems" class="xref-link">{esc(ind["label"])}</a>'
                    if is_systems else esc(ind["label"]))
        ind_cards.append(
            '<div class="roi-ind-card">'
            f'<div class="roi-ind-value">{val_html}</div>'
            f'<div class="roi-ind-label">{lbl_html}</div>'
            f'<div class="roi-ind-impact">{esc(ind["impact"])}</div>'
            '</div>'
        )

    # Systems count for the Step-5 phased-adoption slider. Fall back
    # to whatever Section 6 reports if the brief had none.
    sys_ind = next((i for i in indicators
                    if re.search(r"systems?\s*connected", i["label"], re.IGNORECASE)), None)
    sys_count_for_slider = systems_count or (int(sys_ind["value"]) if sys_ind and sys_ind["value"].isdigit() else 12)

    cost_rows = "".join(_roi_input_row(r, "c", guides) for r in rows["c"])
    plat_rows = "".join(_roi_input_row(r, "p", guides) for r in rows["p"])
    val_rows = "".join(_roi_input_row(r, "v", guides) for r in rows["v"])

    return f"""\
<h2 id="roi-framework">ROI Framework</h2>
<h3 style="margin-top:0">ROI Discussion Guide</h3>
<p class="roi-intro">This guide walks you through building a business case in five steps. Architecture-derived values are pre-filled from your design. Fill in your organization's cost data to calculate ROI automatically.</p>

<div class="roi-step-header"><span class="roi-step-num">Foundation</span><span class="roi-step-title">Architecture Indicators</span></div>
<p class="roi-step-desc">These values are derived from the architecture design. They anchor all cost and value estimates below.</p>
<div class="roi-ind-grid">
{"".join(ind_cards)}
</div>

<div class="roi-step-header"><span class="roi-step-num">Step 1</span><span class="roi-step-title">Cost of Current State (Annual)</span></div>
<p class="roi-step-desc">Estimate what your organization spends today due to the limitations of your current integration approach. Each row tells you <strong>what to measure</strong>, <strong>who to ask</strong>, and gives a <strong>worked example</strong>.</p>
<table><thead><tr><th style="width:40px">#</th><th>Category</th><th style="width:150px">Estimate ($)</th><th style="width:200px">Architecture Basis</th></tr></thead><tbody>
{cost_rows}
{_roi_sum_row("Total current state cost", "c")}
</tbody></table>

<div class="roi-step-header"><span class="roi-step-num">Step 2</span><span class="roi-step-title">Cost of New Platform (Annual)</span></div>
<p class="roi-step-desc">Estimate what the new platform will cost to license, implement, and operate. Contact Solace sales for licensing quotes; use your project manager for implementation scope.</p>
<table><thead><tr><th style="width:40px">#</th><th>Category</th><th style="width:150px">Estimate ($)</th><th style="width:200px">Architecture Basis</th></tr></thead><tbody>
{plat_rows}
{_roi_sum_row("Total new platform cost", "p")}
</tbody></table>

<div class="roi-step-header"><span class="roi-step-num">Step 3</span><span class="roi-step-title">Value Delivered (Annual)</span></div>
<p class="roi-step-desc">Values marked <span style="font-family:Space Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.8px;background:#e6f7f1;color:#00866a;padding:1px 6px;border-radius:3px;font-weight:700">auto-filled</span> are computed from your Step 1 inputs using architecture-derived ratios. Edit any field to override with your own estimate. V3 and V5 require manual input.</p>
<table><thead><tr><th style="width:40px">#</th><th>Category</th><th style="width:150px">Estimate ($)</th><th style="width:200px">Architecture Basis</th></tr></thead><tbody>
{val_rows}
{_roi_sum_row("Total annual value", "v")}
</tbody></table>

<div class="roi-step-header"><span class="roi-step-num">Step 4</span><span class="roi-step-title">Results</span></div>
<p class="roi-step-desc">These metrics are calculated automatically from your inputs above. They update live as you change any value.</p>
<div class="roi-results-grid">
<div class="roi-res-card roi-res-primary"><div class="roi-res-label">Net Annual Benefit</div><div class="roi-res-value" id="roi-net">$0</div><div class="roi-res-detail">Value delivered minus platform cost</div></div>
<div class="roi-res-card"><div class="roi-res-label">Implementation Cost</div><div class="roi-res-value" id="roi-impl">$0</div><div class="roi-res-detail">P2 one-time cost (amortized over 3 years in platform total)</div></div>
<div class="roi-res-card"><div class="roi-res-label">Payback Period</div><div class="roi-res-value" id="roi-payback">--</div><div class="roi-res-detail">Months until implementation cost recovered</div></div>
<div class="roi-res-card"><div class="roi-res-label">3-Year Net Value</div><div class="roi-res-value" id="roi-3yr">$0</div><div class="roi-res-detail">(Net benefit x 3) minus implementation</div></div>
<div class="roi-res-card"><div class="roi-res-label">5-Year Net Value</div><div class="roi-res-value" id="roi-5yr">$0</div><div class="roi-res-detail">(Net benefit x 5) minus impl minus upgrade</div></div>
<div class="roi-res-card"><div class="roi-res-label">ROI Percentage</div><div class="roi-res-value" id="roi-pct">--</div><div class="roi-res-detail">Net benefit / platform cost x 100</div></div>
</div>

<div class="roi-step-header"><span class="roi-step-num">Step 5</span><span class="roi-step-title">What-If Scenarios</span><button class="roi-reset-btn" id="sens-reset-btn" title="Reset all scenarios to defaults">Reset All</button></div>
<p class="roi-step-desc">Each card shows the isolated impact of a single variable change. The <strong>Combined Scenario</strong> card at the bottom compounds all active adjustments together for a realistic view.</p>
<div class="roi-sens-grid">
<div class="roi-sens-card">
<div class="roi-sens-label">Platform licensing change</div>
<div class="roi-sens-hint">What if annual licensing costs more or less than quoted? Adjusts P1 by the selected percentage.</div>
<div class="roi-sens-control"><input type="range" class="roi-slider" id="sens-license" aria-label="Platform licensing change percentage" min="-50" max="50" value="0" step="5"><span class="roi-sens-val" id="sens-license-val">0%</span></div>
<div class="roi-sens-result">Adjusted net benefit: <strong id="sens-license-net">--</strong></div>
<div class="roi-sens-result">Payback shift: <strong id="sens-license-pay">--</strong></div>
</div>
<div class="roi-sens-card">
<div class="roi-sens-label">Value delivered change</div>
<div class="roi-sens-hint">What if realized savings are higher or lower than estimated? Scales total annual value (V1-V6) up or down.</div>
<div class="roi-sens-control"><input type="range" class="roi-slider" id="sens-value" aria-label="Value delivered change percentage" min="-50" max="50" value="0" step="5"><span class="roi-sens-val" id="sens-value-val">0%</span></div>
<div class="roi-sens-result">Adjusted net benefit: <strong id="sens-value-net">--</strong></div>
<div class="roi-sens-result">Payback shift: <strong id="sens-value-pay">--</strong></div>
</div>
<div class="roi-sens-card">
<div class="roi-sens-label">Implementation cost overrun</div>
<div class="roi-sens-hint">What if the build takes more budget than planned? Increases the one-time implementation cost (P2), extending payback.</div>
<div class="roi-sens-control"><input type="range" class="roi-slider" id="sens-impl" aria-label="Implementation cost overrun percentage" min="0" max="100" value="0" step="5"><span class="roi-sens-val" id="sens-impl-val">0%</span></div>
<div class="roi-sens-result">Adjusted payback: <strong id="sens-impl-pay">--</strong></div>
<div class="roi-sens-result">Adjusted 3-yr value: <strong id="sens-impl-3yr">--</strong></div>
</div>
<div class="roi-sens-card">
<div class="roi-sens-label">Timeline delay</div>
<div class="roi-sens-hint">What if the project ships late? Each month adds burn-rate cost and delays when value starts accruing.</div>
<div class="roi-sens-control"><input type="range" class="roi-slider" id="sens-timeline" aria-label="Timeline delay in months" min="0" max="12" value="0" step="1"><span class="roi-sens-val" id="sens-timeline-val">0 mo</span></div>
<div class="roi-sens-result">Added impl cost: <strong id="sens-timeline-cost">--</strong></div>
<div class="roi-sens-result">Delayed value start: <strong id="sens-timeline-delay">--</strong></div>
</div>
<div class="roi-sens-card">
<div class="roi-sens-label">Phased adoption (year 1 systems)</div>
<div class="roi-sens-hint">What if you launch in phases — e.g., hot-path systems first, then the rest later? Fewer of the <a href="#connected-systems" class="xref-link">{sys_count_for_slider} connected systems</a> live in year 1 means less value realized but also less integration work. Shows year 1 ROI for a partial rollout.</div>
<div class="roi-sens-control"><input type="range" class="roi-slider" id="sens-phase" aria-label="Year 1 system count" min="1" max="{sys_count_for_slider}" value="{sys_count_for_slider}" step="1"><span class="roi-sens-val" id="sens-phase-val">{sys_count_for_slider}</span></div>
<div class="roi-sens-result">Year 1 net benefit: <strong id="sens-phase-net">--</strong></div>
<div class="roi-sens-result">Year 1 payback: <strong id="sens-phase-pay">--</strong></div>
</div>
</div>
<div class="roi-combined-card">
<div class="roi-combined-header"><span class="roi-combined-icon">&#x2194;</span> Combined Scenario</div>
<div class="roi-combined-desc">Compounded impact of all active adjustments above</div>
<div class="roi-combined-grid">
<div class="roi-combined-item roi-combined-primary"><div class="roi-combined-label">Net Annual Benefit</div><div class="roi-combined-value" id="sens-combined-net">--</div><div class="roi-combined-delta" id="sens-combined-net-delta"></div></div>
<div class="roi-combined-item"><div class="roi-combined-label">Implementation Cost</div><div class="roi-combined-value" id="sens-combined-impl">--</div><div class="roi-combined-delta" id="sens-combined-impl-delta"></div></div>
<div class="roi-combined-item"><div class="roi-combined-label">Payback Period</div><div class="roi-combined-value" id="sens-combined-pay">--</div><div class="roi-combined-delta" id="sens-combined-pay-delta"></div></div>
<div class="roi-combined-item"><div class="roi-combined-label">3-Year Net Value</div><div class="roi-combined-value" id="sens-combined-3yr">--</div><div class="roi-combined-delta" id="sens-combined-3yr-delta"></div></div>
<div class="roi-combined-item"><div class="roi-combined-label">5-Year Net Value</div><div class="roi-combined-value" id="sens-combined-5yr">--</div><div class="roi-combined-delta" id="sens-combined-5yr-delta"></div></div>
<div class="roi-combined-item"><div class="roi-combined-label">ROI Percentage</div><div class="roi-combined-value" id="sens-combined-pct">--</div><div class="roi-combined-delta" id="sens-combined-pct-delta"></div></div>
</div>
</div>

<div class="roi-step-header"><span class="roi-step-num">Step 6</span><span class="roi-step-title">Download</span></div>
<p class="roi-step-desc">Export your completed analysis as an Excel workbook with formulas for all calculated fields.</p>
<div style="display:flex;gap:12px;align-items:center;margin-top:8px">
<button class="roi-export-btn" id="roi-excel-btn">Download as Excel (.xlsx)</button>
<span style="font-size:12px;color:#5A7A94">Includes formulas, sensitivity scenarios, and architecture indicators</span>
</div>
"""


# ---------------------------------------------------------------------------
# Top toolbar
# ---------------------------------------------------------------------------


def _toolbar(pack_label: str) -> str:
    return (
        '<div class="dl-bar">'
        f'<a href="#" class="dl-title" onclick="window.scrollTo({{top:0,behavior:\'smooth\'}});return false">{esc(pack_label)}</a>'
        '<div class="dl-actions">'
        '<button class="dl-theme-toggle" id="themeToggle" title="Toggle dark/light theme">&#9790;</button>'
        '<button class="dl-print" onclick="window.print()">Print / PDF</button>'
        '<button class="dl-btn" id="dlBtn">Download HTML</button>'
        '</div></div>'
        '<div class="float-nav">'
        '<button class="float-btn" onclick="window.scrollTo({top:0,behavior:\'smooth\'})" title="Go to top">&#x25B2;</button>'
        '<button class="float-btn" onclick="window.scrollTo({top:document.body.scrollHeight,behavior:\'smooth\'})" title="Go to bottom">&#x25BC;</button>'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Main HTML renderer
# ---------------------------------------------------------------------------


def render_audience_pack_html(*, engagement_id: str, audience: str, artifacts: list[str],
                              branding: dict, project_name: str | None = None) -> str:
    """Render the audience pack as a self-contained HTML string."""
    pack = _pack_by_id(audience)
    pack_label = pack.get("label") or _PACK_LABELS.get(audience, (audience.title(),))[0]
    pack_subtitle = pack.get("description") or _PACK_LABELS.get(audience, ("", ""))[1]

    decisions = _filter_decisions(_load_decisions(engagement_id), pack)
    findings = _filter_findings(_load_findings(engagement_id), pack)
    open_items = _load_open_items(engagement_id)
    brief = _load_brief(engagement_id)
    status = _load_status(engagement_id)
    project = project_name or _extract_project_name(brief, engagement_id)

    systems = _systems_from_brief(brief)
    inputs = _inputs_from_brief(brief)
    discovery_summary = _discovery_summary(brief)

    # Compute per-step timings from engagement-status.
    total_exec = 0
    for step in (status.get("steps") or {}).values():
        # In the future, set_step_status will populate timing fields.
        # For now, fall back to 0.
        if isinstance(step, dict):
            total_exec += int(step.get("timing", {}).get("execution_sec") or 0)

    stats_row: list[tuple[str, str]] = [
        ("Pack", pack_label),
        ("Artifacts", str(len(artifacts))),
        ("Decisions", str(len(decisions))),
        ("Findings", str(len(findings))),
        ("Open items", str(sum(1 for i in open_items if (i.get("status") or "open").lower() == "open"))),
        ("Execution", _fmt_time(total_exec)),
    ]

    page_header = _page_header(pack_label.upper(), project, discovery_summary, stats_row)

    # Section flags drive both rendering and the TOC.
    sections_meta = {
        "summary": _pack_includes_section(pack, "summary"),
        "scope": _pack_includes_section(pack, "scope") and (bool(systems) or bool(inputs["goals"]) or bool(inputs["requirements"])),
        "decisions": _pack_includes_section(pack, "decisions") and bool(decisions),
        "findings": _pack_includes_section(pack, "findings") and bool(findings),
        "open_items": _pack_includes_section(pack, "open-items") and bool(open_items),
        "connected_systems": _pack_includes_section(pack, "connected-systems") and bool(systems),
        "roi": pack.get("include_roi_calculator") or _pack_includes_section(pack, "roi"),
        "artifacts": _pack_includes_section(pack, "artifacts"),
    }

    # Render the artifacts block FIRST so we can pass artifacts_grouped
    # into _auto_narrative (its Engagement Summary xrefs into phase groups).
    artifacts_html = ""
    artifacts_grouped: dict[str, list[str]] = {}
    if sections_meta["artifacts"]:
        artifacts_html, artifacts_grouped = _render_artifacts_block(
            engagement_id, artifacts, _artifact_descriptions(brief, status),
        )

    steps_dict = (status or {}).get("steps") or {}
    skills_done = sum(1 for s in steps_dict.values()
                      if isinstance(s, dict) and s.get("status") == "DONE")
    skills_total = sum(1 for s in steps_dict.values() if isinstance(s, dict))
    open_count = sum(1 for i in open_items
                     if (i.get("status") or "open").lower() == "open")

    body_parts: list[str] = []
    if sections_meta["summary"]:
        body_parts.append(_summary_section(
            {"artifacts": len(artifacts), "subtitle": discovery_summary},
            len(systems), len(decisions), len(findings), open_count,
            skills_done=skills_done, skills_total=skills_total,
        ))
    if sections_meta["scope"]:
        body_parts.append(_scope_section(systems, inputs))
    # Auto-narrative sits between Scope and Decisions: architect-voice
    # summary of the design + per-step engagement rollup.
    if sections_meta["summary"] and (decisions or findings or steps_dict):
        body_parts.append(_auto_narrative(decisions, findings, status, artifacts_grouped))
    if sections_meta["decisions"]:
        body_parts.append(_decisions_section(decisions))
    if sections_meta["findings"]:
        body_parts.append(_findings_section(findings))
    if sections_meta["open_items"]:
        body_parts.append(_open_items_section(open_items))
    if sections_meta["connected_systems"]:
        body_parts.append(_connected_systems_section(systems))
    if sections_meta["roi"]:
        body_parts.append(_roi_section(engagement_id, artifacts, len(systems)))

    toc_html = _build_toc(pack, sections_meta, artifacts_grouped)
    css, js = _load_templates()

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{esc(project)} — {esc(pack_label)}</title>
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body style="padding-top:48px" data-engagement="{esc(engagement_id)}" data-pack="{esc(audience)}">
{_toolbar(pack_label)}
{page_header}
<div class="layout">
  <nav class="sidebar">
    <div class="toc-title">On this page</div>
    {toc_html}
  </nav>
  <article class="content">
    {''.join(body_parts)}
    {artifacts_html}
  </article>
</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<script>{js}</script>
<script>
  // Theme persistence — localStorage-backed; defaults to light.
  (function(){{
    var key='solace-architect-report-theme';
    try{{
      var saved=localStorage.getItem(key);
      if(saved==='dark')document.body.classList.add('dark');
    }}catch(e){{}}
    var btn=document.getElementById('themeToggle');
    if(btn){{
      btn.textContent=document.body.classList.contains('dark')?'\\u2600':'\\u263E';
      btn.addEventListener('click',function(){{
        document.body.classList.toggle('dark');
        var dark=document.body.classList.contains('dark');
        btn.textContent=dark?'\\u2600':'\\u263E';
        try{{localStorage.setItem(key,dark?'dark':'light');}}catch(e){{}}
      }});
    }}
    // Copy-to-clipboard for per-artifact headers.
    document.body.addEventListener('click',function(e){{
      var b=e.target.closest('.report-copy-btn');
      if(!b)return;
      var id=b.getAttribute('data-copy-target');
      var ta=document.getElementById(id);
      if(!ta)return;
      ta.select();
      try{{document.execCommand('copy');}}catch(e){{}}
      b.classList.add('is-copied');
      var lbl=b.querySelector('.report-copy-label');
      var prev=lbl.textContent;
      lbl.textContent='Copied';
      setTimeout(function(){{b.classList.remove('is-copied');lbl.textContent=prev;}},1500);
    }});
    // Download-HTML button — clones the current document and triggers a save.
    var dl=document.getElementById('dlBtn');
    if(dl){{
      dl.addEventListener('click',function(){{
        var blob=new Blob(['<!doctype html>'+document.documentElement.outerHTML],{{type:'text/html'}});
        var a=document.createElement('a');
        a.href=URL.createObjectURL(blob);
        a.download='{esc(audience)}-report.html';
        document.body.appendChild(a);a.click();a.remove();
      }});
    }}
  }})();
</script>
</body>
</html>"""


def render_audience_pack_pdf(html_content: str, output_path: Path) -> Path:
    """Render HTML to PDF via WeasyPrint with print-optimized CSS."""
    try:
        from weasyprint import HTML
    except ImportError:
        raise RuntimeError(
            "weasyprint not installed — `pip install weasyprint` (plus its system deps) "
            "to enable PDF rendering"
        )
    HTML(string=html_content).write_pdf(str(output_path))
    return output_path


async def render(*, engagement_id: str, audience: str, format: str, artifacts: list[str],
                 branding_overrides: dict | None = None) -> ToolResult:
    """Async entry point — registered with blueprint_tools at plugin load."""
    branding = _load_branding(branding_overrides)
    brief = _load_brief(engagement_id)
    project_name = _extract_project_name(brief, engagement_id)

    html_content = render_audience_pack_html(
        engagement_id=engagement_id, audience=audience, artifacts=artifacts,
        branding=branding, project_name=project_name,
    )

    written: list[str] = []
    html_path = safe_artifact_path(engagement_id, f"exports/{audience}.html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_content, encoding="utf-8")
    written.append(str(html_path))

    if format in ("pdf", "both"):
        try:
            pdf_path = safe_artifact_path(engagement_id, f"exports/{audience}.pdf")
            render_audience_pack_pdf(html_content, pdf_path)
            written.append(str(pdf_path))
        except RuntimeError as e:
            return ToolResult(ok=False, error=str(e), data={"html_only": written})

    return ToolResult(ok=True, data={"paths": written, "audience": audience, "format": format})
