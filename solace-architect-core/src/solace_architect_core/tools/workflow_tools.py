"""Engagement workflow tools (v2spec §5.1).

Config-driven via ``configs/skill-routing.yaml``.
"""

from __future__ import annotations

import time
from importlib import resources
from typing import Any, Optional

import yaml

from .._routing import evaluate_when
from .._storage import read_yaml, write_yaml
from .artifact_tools import ToolResult
from .session_tools import read_session_state, update_session_state


def _load_routing_config() -> dict:
    """Load the default skill-routing.yaml from the package."""
    text = (resources.files("solace_architect_core.configs") / "skill-routing.yaml").read_text()
    return yaml.safe_load(text)


# ---------- get_engagement_plan ----------

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

async def get_next_step(engagement_id: str, discovery_brief: Optional[dict] = None) -> ToolResult:
    """Return the next runnable step or {'status': 'engagement_complete' | 'blocked'}."""
    session = (await read_session_state(engagement_id)).data
    completed = set(session.get("completed_steps", []))

    if discovery_brief is None:
        brief_res = read_yaml(engagement_id, "discovery/discovery-brief.yaml")
        discovery_brief = brief_res or {}

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
