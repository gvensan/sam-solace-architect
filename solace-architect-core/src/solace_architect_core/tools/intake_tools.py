"""Intake tools (v2spec §5.3).

YAML-only parse + preview + export + source-context import + Markdown rendering.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any, Optional

import yaml

from .._routing import evaluate_when
from .._storage import read_yaml, write_yaml
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
from .artifact_tools import ToolResult


_REQUIRED_FIELDS = ("project_name", "project_type", "systems", "requirements")


def _missing_or_placeholder(brief: dict, path: str) -> bool:
    """Check if a dotted field path is missing or contains a placeholder."""
    parts = path.split(".")
    cur: Any = brief
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return True
        cur = cur[p]
    if cur is None:
        return True
    if isinstance(cur, str) and (not cur.strip() or cur.strip().lower() in ("tbd", "todo", "?", "...")):
        return True
    if isinstance(cur, (list, dict)) and len(cur) == 0:
        return True
    return False


async def parse_intake_document(file_path: str, engagement_id: str = "") -> ToolResult:
    """Parse a YAML intake file. Returns parsed brief + list of open_items."""
    path = Path(file_path)
    if not path.exists():
        return ToolResult(ok=False, error=f"file not found: {file_path}")
    try:
        brief = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return ToolResult(ok=False, error=f"YAML parse error: {e}")

    if not isinstance(brief, dict):
        return ToolResult(ok=False, error="intake YAML must be a mapping at the top level")

    open_items = []
    # Required fields → blocking open-items
    for field in _REQUIRED_FIELDS:
        if _missing_or_placeholder(brief, field):
            open_items.append({
                "severity": "blocking",
                "source": "intake",
                "description": f"Required intake field missing or unspecified: {field}",
            })

    # Optional fields → advisory open-items
    for field in ("regulatory", "timeline", "team", "growth", "goals"):
        if _missing_or_placeholder(brief, field):
            open_items.append({
                "severity": "advisory",
                "source": "intake",
                "description": f"Optional intake field unspecified: {field}",
            })

    return ToolResult(ok=True, data={"parsed_brief": brief, "open_items": open_items})


def _load_routing_steps() -> list:
    text = (resources.files("solace_architect_core.configs") / "skill-routing.yaml").read_text()
    routing = yaml.safe_load(text)
    return routing.get("routing", routing.get("steps", []))


async def compute_intake_preview(partial_intake: dict) -> ToolResult:
    """Live skill-routing preview: which steps would fire for this intake state."""
    steps = _load_routing_steps()
    included, skipped = [], []
    for step in steps:
        trigger = step.get("trigger", "always")
        if trigger == "always":
            included.append({"step": step.get("step") or step.get("name"),
                             "agent": step.get("agent"), "scope": step.get("scope")})
        else:
            ok = evaluate_when(partial_intake, step.get("when"))
            entry = {"step": step.get("step") or step.get("name"),
                     "agent": step.get("agent"), "scope": step.get("scope")}
            if ok:
                included.append(entry)
            else:
                entry["skip_reason"] = step.get("skip_reason", "conditional matcher rejected")
                skipped.append(entry)
    return ToolResult(ok=True, data={
        "included_steps": included,
        "skipped_steps": skipped,
        "estimated_minutes": _estimate_duration(included),
    })


def _estimate_duration(included: list) -> int:
    """Phase 1 heuristic: 3 min per design step, 2 min for discovery/review/validation, 1 for blueprint."""
    minutes = 0
    for step in included:
        scope = step.get("scope")
        if scope:
            minutes += 3
        elif step["agent"] in ("SADiscoveryAgent", "SAValidationAgent"):
            minutes += 2
        elif "Reviewer" in (step["agent"] or ""):
            minutes += 2
        else:
            minutes += 1
    return minutes


async def integration_hub_autocomplete(query: str) -> ToolResult:
    """Thin wrapper around query_integration_hub returning up to 10 matches."""
    from .grounding_tools import query_integration_hub
    res = await query_integration_hub(query)
    if not res.ok:
        return res
    return ToolResult(ok=True, data=res.data[:10])


async def render_intake_markdown(intake_dict: dict) -> ToolResult:
    """Render the intake state as diff-friendly Markdown."""
    lines = [f"# Intake — {intake_dict.get('project_name', 'Untitled')}", ""]

    def render_section(title: str, content: Any, level: int = 2):
        lines.append("#" * level + " " + title)
        if isinstance(content, dict):
            for k, v in content.items():
                if isinstance(v, (dict, list)):
                    render_section(k.replace("_", " ").title(), v, level + 1)
                else:
                    lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    lines.append("- " + ", ".join(f"**{k}**: {v}" for k, v in item.items()))
                else:
                    lines.append(f"- {item}")
        else:
            lines.append(str(content))
        lines.append("")

    for top_key, top_val in intake_dict.items():
        if top_key == "project_name":
            continue
        render_section(top_key.replace("_", " ").title(), top_val)

    return ToolResult(ok=True, data="\n".join(lines))


async def export_intake_from_project(
    source_engagement_id: str, include_decisions: bool = True, include_open_items: bool = False,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Reconstruct a YAML intake from a completed project (handoff / replay / regression).

    ``user_id`` auto-resolves from ``tool_context``.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        brief = read_yaml(source_engagement_id, "discovery/discovery-brief.yaml")
        if not brief:
            return ToolResult(ok=False, error=f"no discovery-brief.yaml found in {source_engagement_id}")

        export = dict(brief)
        if include_decisions:
            decisions = read_yaml(source_engagement_id, "meta/decisions.yaml", default={"decisions": []})
            if decisions["decisions"]:
                export["_exported_decisions"] = decisions["decisions"]
        if include_open_items:
            items = read_yaml(source_engagement_id, "meta/open-items.yaml", default={"open_items": []})
            if items["open_items"]:
                export["_exported_open_items"] = items["open_items"]

    yaml_text = yaml.safe_dump(export, default_flow_style=False, sort_keys=False)
    return ToolResult(ok=True, data={"yaml": yaml_text, "filename": f"{source_engagement_id}-intake.yaml"})


async def import_source_context(
    source_project_id: str, sections: list[str], user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Copy selected sections from a source project's brief.

    ``user_id`` auto-resolves from ``tool_context``.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        brief = read_yaml(source_project_id, "discovery/discovery-brief.yaml")
    if not brief:
        return ToolResult(ok=False, error=f"no discovery-brief.yaml in {source_project_id}")

    out = {}
    for path in sections:
        cur: Any = brief
        parts = path.split(".")
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                cur = None
                break
        if cur is not None:
            # Reconstruct nested dict
            d = out
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            d[parts[-1]] = cur
    return ToolResult(ok=True, data=out)
