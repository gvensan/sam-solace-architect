"""Engagement workflow tools (v2spec §5.1).

Config-driven via ``configs/skill-routing.yaml``.
"""

from __future__ import annotations

import json
import time
from importlib import resources
from typing import Any, Optional

import yaml

from .._routing import evaluate_when
from .._storage import read_yaml, safe_read_yaml, write_yaml
from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult
from .session_tools import read_session_state, update_session_state


def _load_routing_config() -> dict:
    """Load the default skill-routing.yaml from the package."""
    text = (resources.files("solace_architect_core.configs") / "skill-routing.yaml").read_text()
    return yaml.safe_load(text)


def _read_intake_json(engagement_id: str) -> dict:
    """Best-effort read of ``discovery/intake.json``; returns {} on any failure.

    intake.json is the raw user submission; discovery-brief.yaml is the
    normalized digest the Discovery agent writes. ``preferences.*`` (e.g.
    ``provision_event_portal``) is captured at intake-submit and lives in
    intake.json, but the Discovery agent doesn't currently propagate it
    into the brief — so routing rules that match against ``preferences.*``
    would see a missing field and silently skip steps. Used by
    ``effective_brief`` to fill that gap.
    """
    from .._storage import safe_artifact_path
    try:
        path = safe_artifact_path(engagement_id, "discovery/intake.json")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def effective_brief(engagement_id: str, brief: Optional[dict] = None) -> dict:
    """Brief merged with intake.preferences.

    The Discovery agent writes ``discovery/discovery-brief.yaml`` without
    propagating ``preferences.*`` from intake. The routing engine's
    conditional rules ('when' clauses) reference ``preferences.*`` —
    without this merge they read an empty dict and falsely mark
    opt-in phases as skipped (observed 2026-05-24: a hotel-reservation
    engagement with ``provision_event_portal: true`` in intake.json had
    Event Portal struck-through on the dashboard because the brief
    didn't carry the preference).

    Merge order: brief.preferences wins over intake.preferences for any
    keys both sets. Intake is the fallback, not the override. Discovery
    is free to refine a preference if it learns something; we don't
    silently overwrite that with the raw intake value.
    """
    if brief is None:
        brief = read_yaml(engagement_id, "discovery/discovery-brief.yaml") or {}
    intake = _read_intake_json(engagement_id)
    intake_prefs = (intake.get("preferences") or {})
    brief_prefs = (brief.get("preferences") or {})
    if not intake_prefs:
        return brief
    merged = {**intake_prefs, **brief_prefs}
    out = {**brief, "preferences": merged}
    return out


# ---------- get_engagement_plan ----------

@coerce_args
async def get_engagement_plan(discovery_brief: dict) -> ToolResult:
    """Build the ordered execution plan from the routing config + discovery brief."""
    routing = _load_routing_config()
    steps = routing.get("routing", routing.get("steps", []))   # tolerate both keys

    plan = []
    for step in steps:
        trigger = step.get("trigger", "always")
        if trigger == "always":
            included = True
            skip_reason = None
        else:
            included = evaluate_when(discovery_brief, step.get("when"))
            skip_reason = None if included else step.get("skip_reason", "conditional matcher rejected")

        plan.append({
            "step": step.get("step") or step.get("name"),
            "agent": step.get("agent"),
            "scope": step.get("scope"),
            "dependencies": step.get("dependencies", []),
            "trigger": trigger,
            "included": included,
            "skip_reason": skip_reason,
            "dispatch": step.get("dispatch", "sequential"),
        })

    return ToolResult(ok=True, data=plan)


# ---------- get_next_step ----------

@coerce_args
async def get_next_step(engagement_id: str, discovery_brief: Optional[dict] = None) -> ToolResult:
    """Return the next runnable step or {'status': 'engagement_complete' | 'blocked'}."""
    session = (await read_session_state(engagement_id)).data
    completed = set(session.get("completed_steps", []))

    if discovery_brief is None:
        # safe_read_yaml: get_next_step is hit on every dashboard "what's
        # next?" poll. A corrupt brief should yield "no plan" gracefully,
        # not a 500 — the user can re-import or rewrite the brief from the
        # UI. Brief writers (Discovery agent) hit write_artifact which now
        # validates YAML before persisting, so future briefs can't land
        # corrupt in the first place.
        brief_res = safe_read_yaml(engagement_id, "discovery/discovery-brief.yaml")
        discovery_brief = brief_res or {}
    # Merge intake.preferences so routing rules that reference
    # preferences.* see the user's intake-time choices even when the
    # Discovery agent didn't propagate them into the brief.
    discovery_brief = effective_brief(engagement_id, discovery_brief)

    plan_res = await get_engagement_plan(discovery_brief)
    plan = plan_res.data

    # Filter out skipped steps
    runnable = [s for s in plan if s["included"]]

    for step in runnable:
        if step["step"] in completed:
            continue
        deps = step["dependencies"]
        unmet = [d for d in deps if d not in completed and not _is_meta_dep(d, completed, runnable)]
        if not unmet:
            return ToolResult(ok=True, data={"status": "ready", "step": step})

    if all(s["step"] in completed for s in runnable):
        return ToolResult(ok=True, data={"status": "engagement_complete"})
    return ToolResult(ok=True, data={"status": "blocked", "completed": sorted(completed)})


def _is_meta_dep(dep: str, completed: set, runnable: list) -> bool:
    """Handle meta-dependencies like '>=1 design step'."""
    if dep.startswith(">=1 design step") or dep.startswith(">=1 design skill"):
        design_steps = {s["step"] for s in runnable if s.get("scope") and s["agent"] == "SADomainAgent"}
        return bool(design_steps & completed)
    return False


# ---------- record_step_complete / record_step_timing ----------

@coerce_args
async def record_step_complete(
    engagement_id: str, step_name: str, timing_data: Optional[dict] = None,
) -> ToolResult:
    session = (await read_session_state(engagement_id)).data
    completed = list(session.get("completed_steps", []))
    if step_name not in completed:
        completed.append(step_name)
    timing = dict(session.get("timing_data", {}))
    if timing_data:
        timing[step_name] = timing_data
    await update_session_state(engagement_id, {
        "completed_steps": completed,
        "active_step": None,
        "timing_data": timing,
    })
    return ToolResult(ok=True, data={"step": step_name, "completed_count": len(completed)})


@coerce_args
async def record_step_timing(
    engagement_id: str, step_name: str, *,
    wall_sec: int, execution_sec: int, user_wait_sec: int = 0,
    per_question_wait: Optional[list] = None,
    per_substep: Optional[list] = None,
) -> ToolResult:
    """Capture per-step timing (sole input source for compute_timeline/compute_stats_summary)."""
    session = (await read_session_state(engagement_id)).data
    timing = dict(session.get("timing_data", {}))
    timing[step_name] = {
        "wall_sec": wall_sec,
        "execution_sec": execution_sec,
        "user_wait_sec": user_wait_sec,
        "per_question_wait": per_question_wait or [],
        "per_substep": per_substep or [],
        "recorded_at": time.time(),
    }
    await update_session_state(engagement_id, {"timing_data": timing})
    return ToolResult(ok=True, data=timing[step_name])


# ---------- handle_step_failure (Completion Status Protocol-aware) ----------

# Per-engagement retry counters (in-memory; Phase 2+ persists in session)
_RETRIES: dict[tuple[str, str], int] = {}


async def handle_step_failure(
    engagement_id: str, *, step_name: str, status: str,
    error_type: str = "", error_message: str = "", recommendation: str = "",
) -> ToolResult:
    """Map a downstream agent's Completion Status to an orchestrator action.

    Returns one of: 'retry', 'retry_with_summary', 'skip', 'abort', 'surface_to_user'.
    """
    if status == "BLOCKED":
        return ToolResult(ok=True, data={
            "action": "surface_to_user",
            "reason": "step is BLOCKED — surface to user; preconditions not met",
            "error_type": error_type, "error_message": error_message,
            "recommendation": recommendation,
        })
    if status == "NEEDS_CONTEXT":
        return ToolResult(ok=True, data={
            "action": "surface_to_user",
            "reason": "step NEEDS_CONTEXT — ask the user for the missing information",
            "error_type": error_type, "error_message": error_message,
            "recommendation": recommendation,
        })
    if status == "DONE_WITH_CONCERNS":
        return ToolResult(ok=True, data={
            "action": "continue",
            "reason": "step completed with concerns — log and proceed",
            "concerns": error_message,
        })

    # DONE with error or unrecognized — apply retry ladder
    key = (engagement_id, step_name)
    attempts = _RETRIES.get(key, 0) + 1
    _RETRIES[key] = attempts

    if attempts == 1:
        action = "retry"
    elif attempts == 2:
        action = "retry_with_summary"
    elif attempts >= 3:
        action = "skip"
    else:
        action = "abort"
    return ToolResult(ok=True, data={
        "action": action, "attempts": attempts,
        "error_type": error_type, "error_message": error_message,
    })
