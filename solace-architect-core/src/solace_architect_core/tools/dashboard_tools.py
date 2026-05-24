"""Dashboard computation tools (v2spec §3.4).

Pure read-side; never mutates state. Implements STATUS_RANK dedup and
effective-skipped logic.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .._storage import list_artifacts as _list_artifacts, safe_read_yaml as read_yaml
from .artifact_tools import ToolResult
from .session_tools import read_session_state
from .workflow_tools import get_engagement_plan


# V1 STATUS_RANK (higher = takes precedence on dedup)
_STATUS_RANK = {
    "complete": 6, "in-progress": 5, "partial": 4,
    "interrupted": 3, "skipped": 2, "blocked": 1,
}


def _dedup_step_states(states: list[dict]) -> dict[str, dict]:
    """Apply STATUS_RANK precedence + newest-started tiebreak."""
    best: dict[str, dict] = {}
    for s in states:
        name = s["step"]
        if name not in best:
            best[name] = s
            continue
        cur = best[name]
        cur_rank = _STATUS_RANK.get(cur.get("status", ""), 0)
        new_rank = _STATUS_RANK.get(s.get("status", ""), 0)
        if new_rank > cur_rank:
            best[name] = s
        elif new_rank == cur_rank and s.get("started_at", "") > cur.get("started_at", ""):
            best[name] = s
    return best


def _phase_of(step: dict) -> str:
    agent = step.get("agent") or ""
    scope = step.get("scope") or ""
    if step["step"] == "discovery":
        return "discovery"
    if "Reviewer" in agent:
        return "review"
    if agent == "SAValidationAgent":
        return "validation"
    if agent == "SABlueprintAgent":
        return "blueprint"
    if agent == "SAEventPortalAgent":
        return "event-portal"
    if scope:
        return "design"
    return "other"


async def compute_overview_stats(engagement_id: str) -> ToolResult:
    """Tile data for the Overview view."""
    brief = read_yaml(engagement_id, "discovery/discovery-brief.yaml") or {}
    session = (await read_session_state(engagement_id)).data
    decisions = read_yaml(engagement_id, "meta/decisions.yaml", default={"decisions": []})["decisions"]
    findings = read_yaml(engagement_id, "meta/findings.yaml", default={"findings": []})["findings"]
    open_items = read_yaml(engagement_id, "meta/open-items.yaml", default={"open_items": []})["open_items"]

    plan = (await get_engagement_plan(brief)).data
    completed = set(session.get("completed_steps", []))

    # Effective-skipped: intake-gated steps count as skipped, not pending
    skips = [s for s in plan if not s["included"]]
    completes = [s for s in plan if s["step"] in completed]
    skill_total = len([s for s in plan if s["agent"] != "SAOrchestratorAgent"])

    # Phase progress (X/Y per phase)
    phase_counts: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for s in plan:
        if s["agent"] == "SAOrchestratorAgent":
            continue
        phase = _phase_of(s)
        done, total = phase_counts[phase]
        total += 1
        if s["step"] in completed:
            done += 1
        elif not s["included"]:
            done += 1  # skipped counts as "done" for the phase progress bar
        phase_counts[phase] = (done, total)

    # Connected systems (from discovery brief)
    systems = brief.get("systems", []) or []
    producers = sum(1 for s in systems if isinstance(s, dict) and "producer" in (s.get("role", "") or "").lower())
    consumers = sum(1 for s in systems if isinstance(s, dict) and "consumer" in (s.get("role", "") or "").lower())

    # Recommended next step
    runnable = [s for s in plan if s["included"] and s["step"] not in completed]
    recommended_next = runnable[0]["step"] if runnable else None

    # Per-design-scope status array for the design-in-progress dashboard
    # panel. Pulls scope_progress from meta/engagement-status.yaml and
    # joins with the plan so each scope row has {scope, status, ?reason}.
    # Status taxonomy (FE renders ● ◐ ◯ ⊘):
    #   - done    — scope is in scope_progress.done[]
    #   - next    — scope == scope_progress.next (about to dispatch)
    #   - pending — included by intake but not yet started
    #   - skipped — intake-gated out (skip_reason from the plan entry)
    status_doc = read_yaml(engagement_id, "meta/engagement-status.yaml", default={"steps": {}}) or {"steps": {}}
    sp = ((status_doc.get("steps") or {}).get("design") or {}).get("scope_progress") or {}
    sp_done = set(sp.get("done") or [])
    sp_next = sp.get("next")
    design_scopes = []
    for s in plan:
        # Domain-owned design steps are the multi-scope rows in skill-routing;
        # the orchestrator's wrappers / reviewer / validation / EP / blueprint
        # have different shapes and aren't part of Design's scope list.
        if s.get("agent") != "SADomainAgent":
            continue
        scope_id = s.get("scope") or s.get("step")
        if not scope_id:
            continue
        if not s["included"]:
            design_scopes.append({
                "scope": scope_id,
                "status": "skipped",
                "skip_reason": s.get("skip_reason") or "",
            })
        elif scope_id in sp_done:
            design_scopes.append({"scope": scope_id, "status": "done"})
        elif sp_next and scope_id == sp_next:
            design_scopes.append({"scope": scope_id, "status": "next"})
        else:
            design_scopes.append({"scope": scope_id, "status": "pending"})

    # Per-reviewer / per-section / per-stage status arrays for the
    # review / blueprint / event-portal in-progress dashboard panels.
    # Derived from on-disk artifact presence (the only source of truth
    # for these phases today — agents don't track sub-step state
    # separately). When the agent hasn't yet written the canonical
    # artifact for a sub-step, that sub-step is "pending"; presence
    # means "done". Sub-step ids match the FE's _CHECKLIST_LABELS map.
    artifacts = _list_artifacts(engagement_id)
    artifacts_for_checklists = set(artifacts)

    def _checklist_from_artifacts(item_paths):
        out = []
        for item_id, art_path in item_paths:
            out.append({
                "id": item_id,
                "status": "done" if art_path in artifacts_for_checklists else "pending",
            })
        return out

    review_reviewers = _checklist_from_artifacts([
        ("architect",  "reviews/architect-review.md"),
        ("developer",  "reviews/developer-review.md"),
        ("ops",        "reviews/ops-review.md"),
        ("security",   "reviews/security-review.md"),
    ])

    # Event Portal: 3-stage pipeline (plan → live provisioning → AsyncAPI).
    # "asyncapi" stage is "done" when at least one spec exists under the
    # asyncapi/ subdirectory (one per provisioned application).
    ep_asyncapi_done = any(a.startswith("event-portal/asyncapi/") for a in artifacts_for_checklists)
    event_portal_stages = [
        {"id": "plan",        "status": "done" if "event-portal/plan.yaml" in artifacts_for_checklists else "pending"},
        {"id": "provisioned", "status": "done" if "event-portal/provisioned.yaml" in artifacts_for_checklists else "pending"},
        {"id": "asyncapi",    "status": "done" if ep_asyncapi_done else "pending"},
    ]

    blueprint_sections = _checklist_from_artifacts([
        ("architecture-overview",   "blueprint/architecture-overview.md"),
        ("architecture-decisions",  "blueprint/architecture-decisions.md"),
        ("architecture-components", "blueprint/architecture-components.md"),
        ("architecture",            "blueprint/architecture.md"),
        ("runbook-deploy",          "blueprint/runbook-deploy.md"),
        ("runbook-failures",        "blueprint/runbook-failures.md"),
        ("runbook-dr",              "blueprint/runbook-dr.md"),
        ("runbook",                 "blueprint/runbook.md"),
        ("pack-blueprint",          "blueprint/packs/blueprint.md"),
        ("pack-executive",          "blueprint/packs/executive.md"),
        ("pack-admin-ops",          "blueprint/packs/admin-ops.md"),
        ("pack-developer",          "blueprint/packs/developer.md"),
        ("pack-security",           "blueprint/packs/security.md"),
        ("engagement-package",      "exports/engagement-package.zip"),
    ])

    # ARTIFACTS tile counts workflow-PRODUCED deliverables, not system
    # bookkeeping or user inputs. Without this filter, a freshly-restarted
    # engagement showed 8-9 "artifacts" — but those were all empty meta/*
    # containers + the user's submitted intake. The user reasonably expected
    # the tile to track "what the workflow has produced so far". Filter out:
    #   * meta/*              — internal state (decisions.yaml, session.yaml, etc.)
    #   * discovery/intake.*  — user-submitted form, an INPUT not output
    # Keep everything else: the discovery brief/summary/report, design/*,
    # reviews/*, validation/*, event-portal/*, blueprint/*, exports/*.
    def _is_workflow_artifact(path: str) -> bool:
        if path.startswith("meta/"):
            return False
        if path.startswith("discovery/intake."):
            return False
        return True
    workflow_artifacts = [a for a in artifacts if _is_workflow_artifact(a)]

    return ToolResult(ok=True, data={
        "skills_completed": len(completes),
        "skills_total": skill_total,
        "skills_skipped": len(skips),
        "connected_systems": len(systems),
        "producers": producers,
        "consumers": consumers,
        "artifacts_count": len(workflow_artifacts),
        "decisions_count": len(decisions),
        "review_findings_count": len(findings),
        "open_items_blocking": sum(1 for q in open_items if q.get("severity") == "blocking" and q.get("status") == "open"),
        "open_items_advisory": sum(1 for q in open_items if q.get("severity") == "advisory" and q.get("status") == "open"),
        "execution_time_seconds": sum(t.get("execution_sec", 0) for t in session.get("timing_data", {}).values()),
        "user_wait_seconds": sum(t.get("user_wait_sec", 0) for t in session.get("timing_data", {}).values()),
        # Intake-time pace preference (auto | interactive). Surfaces here
        # so the Progress CTA can render ONE primary button matching the
        # user's stated preference instead of asking them to pick the
        # pace again. Defaults to "interactive" when missing — safer
        # default since the agent always confirms decisions.
        "execution_mode": (session.get("execution_mode") or "interactive"),
        "ep_provisioning_status": _ep_status(brief, completed),
        "phase_progress": {k: f"{v[0]}/{v[1]}" for k, v in phase_counts.items()},
        "recommended_next_step": recommended_next,
        "skip_reasons": [{"step": s["step"], "reason": s["skip_reason"]} for s in skips],
        "design_scopes": design_scopes,
        "review_reviewers": review_reviewers,
        "event_portal_stages": event_portal_stages,
        "blueprint_sections": blueprint_sections,
    })


def _ep_status(brief: dict, completed: set) -> str:
    if not (brief.get("preferences") or {}).get("provision_event_portal"):
        return "not-requested"
    if "event-portal" in completed:
        return "live"
    return "pending"


async def compute_timeline(engagement_id: str) -> ToolResult:
    """Per-skill execution + user-wait time for the Timeline view."""
    session = (await read_session_state(engagement_id)).data
    timing = session.get("timing_data", {})
    entries = []
    for step, t in timing.items():
        entries.append({
            "skill": step,
            "execution_seconds": t.get("execution_sec", 0),
            "user_wait_seconds": t.get("user_wait_sec", 0),
            "wall_seconds": t.get("wall_sec", 0),
        })
    entries.sort(key=lambda e: e["wall_seconds"], reverse=True)
    return ToolResult(ok=True, data=entries)


async def compute_stats_summary(engagement_id: str) -> ToolResult:
    """Stats view summary."""
    timeline_res = await compute_timeline(engagement_id)
    entries = timeline_res.data

    total_wall = sum(e["wall_seconds"] for e in entries)
    total_exec = sum(e["execution_seconds"] for e in entries)
    total_wait = sum(e["user_wait_seconds"] for e in entries)
    steps_executed = len(entries)
    questions_asked = 0  # Phase 1: not tracked separately yet

    top_skills = []
    if total_exec > 0:
        top_skills = [
            {"skill": e["skill"], "seconds": e["execution_seconds"],
             "pct": round(100 * e["execution_seconds"] / total_exec, 1)}
            for e in sorted(entries, key=lambda x: x["execution_seconds"], reverse=True)[:5]
        ]

    insights: dict[str, Any] = {}
    if entries:
        slowest = max(entries, key=lambda e: e["execution_seconds"])
        fastest = min(entries, key=lambda e: e["execution_seconds"])
        insights = {
            "slowest_skill": slowest["skill"],
            "fastest_skill": fastest["skill"],
            "avg_per_skill_seconds": total_exec // steps_executed if steps_executed else 0,
        }

    return ToolResult(ok=True, data={
        "wall_time_seconds": total_wall,
        "execution_seconds": total_exec,
        "user_wait_seconds": total_wait,
        "steps_executed": steps_executed,
        "questions_asked": questions_asked,
        "top_skills_by_execution_time": top_skills,
        "phase_breakdown": [],   # Phase 1: skip; v2spec §3.4 has the full shape
        "insights": insights,
    })


async def compute_active_step(engagement_id: str) -> ToolResult:
    """For the live status bar."""
    session = (await read_session_state(engagement_id)).data
    active = session.get("active_step")
    if not active:
        return ToolResult(ok=True, data={
            "active_agent": None, "active_scope": None, "active_phase": "idle",
            "started_at": None, "elapsed_seconds": None, "user_waiting": False,
        })
    return ToolResult(ok=True, data={
        "active_agent": active.get("agent"),
        "active_scope": active.get("scope"),
        "active_phase": active.get("phase", "unknown"),
        "started_at": active.get("started_at"),
        "elapsed_seconds": active.get("elapsed_seconds"),
        "user_waiting": active.get("user_waiting", False),
    })
