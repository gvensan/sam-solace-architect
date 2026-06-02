"""Dashboard + API route handlers.

Each route is a plain async function returning a JSON-serializable dict. The
plugin's lifecycle.py adapts them to whatever HTTP framework SAM exposes
(FastAPI, Starlette, or a custom router).

All routes apply ``Cache-Control: no-store`` per v2spec Decision 52.
"""

from __future__ import annotations

from typing import Any, Optional

from datetime import datetime, timezone

from solace_architect_core.tools import (
    artifact_tools, decision_tools, project_tools,
    dashboard_tools, intake_tools, blueprint_tools,
    telemetry_tools, lifecycle_tools, session_tools,
    workflow_tools, grounding_tools, managed_grounding_tools,
)
from solace_architect_core._storage import (
    read_jsonl, read_yaml, safe_artifact_path, write_text, write_yaml,
)
from solace_architect_core._user_context import get_current_user
from solace_architect_core.orchestrator import design_state as _design_state
from solace_architect_core.orchestrator import prose as _prose
from solace_architect_core.orchestrator import rules as _rules
from solace_architect_core.orchestrator import validation_rules as _validation_rules
from solace_architect_core.orchestrator import context_pack as _context_pack
from solace_architect_core.orchestrator import event_portal_model as _event_portal_model
from solace_architect_core.orchestrator import blueprint_render as _blueprint_render

import asyncio
import logging as _logging
import os
import re
from pathlib import Path

# Module logger for Design-orchestration diagnostics (which kickoff was built /
# what action was decided). Lands in sa_logs/solace_architect_webui_entrypoint.log.
_log = _logging.getLogger(__name__)

# Per-engagement lock serialising /design/advance. The orchestrator's
# single-writer invariant is otherwise only by convention: a plain
# load→modify→save has no atomic claim, so two overlapping calls (multiple tabs,
# a drop-resume racing a finalize, a double-click) could both load the same
# state, both decide "dispatch", and double-dispatch a scope. One entrypoint
# process handles all HTTP, so an asyncio.Lock is sufficient; a multi-process
# deployment would additionally need a compare-and-swap on design-state's version.
_DESIGN_ADVANCE_LOCKS: dict = {}


def _design_advance_lock(engagement_id: str) -> "asyncio.Lock":
    lk = _DESIGN_ADVANCE_LOCKS.get(engagement_id)
    if lk is None:
        lk = _DESIGN_ADVANCE_LOCKS[engagement_id] = asyncio.Lock()
    return lk


async def _clear_step_telemetry(engagement_id: str, step: str) -> dict:
    """Drop everything that ties timing/tokens to ``step`` for this engagement.

    A clean restart needs to remove not just artifacts but the metrics that
    reference them, otherwise the Stats view keeps showing pre-restart values.
    Two stores to touch (per the lifecycle/telemetry design):

      * ``meta/session.yaml`` — ``timing_data[step]`` written by
        ``lifecycle_tools.set_step_status`` on DONE.
      * ``meta/telemetry/llm-calls.jsonl`` — append-only ledger written by
        ``record_llm_call_telemetry``. Filtered + rewritten in place.

    Returns a small summary the caller can include in its response.
    """
    cleared_timing = False
    try:
        session = read_yaml(engagement_id, "meta/session.yaml", default={}) or {}
        timing = dict(session.get("timing_data", {}) or {})
        if step in timing:
            del timing[step]
            session["timing_data"] = timing
            write_yaml(engagement_id, "meta/session.yaml", session)
            cleared_timing = True
    except Exception:
        pass

    removed_telemetry_rows = 0
    try:
        rows = read_jsonl(engagement_id, "meta/telemetry/llm-calls.jsonl")
        kept = [r for r in rows if r.get("step_id") != step]
        removed_telemetry_rows = len(rows) - len(kept)
        if removed_telemetry_rows > 0:
            # Rewrite the whole file. read_jsonl tolerates a missing file, so
            # write_text restores it cleanly if no rows remained.
            content = "\n".join(__import__("json").dumps(r, sort_keys=False) for r in kept)
            if content:
                content += "\n"
            write_text(engagement_id, "meta/telemetry/llm-calls.jsonl", content)
    except Exception:
        pass

    return {"timing_cleared": cleared_timing, "telemetry_rows_removed": removed_telemetry_rows}


_VALID_GROUP_BY_ENGAGEMENT = {"agent", "step", "model", "day"}
_VALID_GROUP_BY_USER = {"agent", "step", "model", "day", "project"}


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ----- Project lifecycle -----

async def list_engagements(include_archived: Any = False) -> Any:
    # Query params arrive as strings via the aiohttp adapter — accept the
    # usual truthy spellings so /api/projects?include_archived=1 (or =true)
    # both flip the filter off.
    if isinstance(include_archived, str):
        include_archived = include_archived.lower() in ("1", "true", "yes", "on")
    return (await project_tools.list_projects(include_archived=bool(include_archived))).data


async def create_engagement(name: str, owner: str = "anonymous") -> Any:
    return (await project_tools.create_project(name=name, owner=owner)).data


# Step statuses that mean "an agent is mid-flight or waiting on the user".
# archive / clone refuse with 409 when ANY step is in one of these states —
# otherwise the action races the agent: archive can hide a project the user
# is actively driving, clone makes a copy of mid-flight state that doesn't
# reflect the source's in-progress decisions.
_ACTIVE_STATES = {"NEEDS_CONTEXT", "IN_PROGRESS"}


async def _active_step(engagement_id: str) -> Optional[str]:
    """Return the id of any step currently in NEEDS_CONTEXT or IN_PROGRESS, else None."""
    try:
        status = (await lifecycle_tools.get_engagement_status(engagement_id)).data or {}
        steps = status.get("steps") or {}
        for step_id, info in steps.items():
            if (info or {}).get("status") in _ACTIVE_STATES:
                return step_id
    except Exception:
        # If we can't read state, fall through and let the caller proceed — the
        # guard is defensive, not a hard correctness gate.
        return None
    return None


async def archive_engagement(project_id: str) -> Any:
    active = await _active_step(project_id)
    if active:
        return {
            "error": "engagement is mid-flight",
            "active_step": active,
            "status_code": 409,
            "hint": (
                f"Step '{active}' is currently waiting on you or running. "
                "Either answer the agent's pending question, restart that step, "
                "or wait for it to settle before archiving."
            ),
        }
    return (await project_tools.archive_project(project_id)).data


async def unarchive_engagement(project_id: str) -> Any:
    return (await project_tools.unarchive_project(project_id)).data


async def delete_engagement(project_id: str) -> Any:
    # Mid-flight guard mirrors archive — refuses to wipe state out from under
    # a running agent. Type-to-confirm in the UI guards against fat-fingers.
    active = await _active_step(project_id)
    if active:
        return {
            "error": "engagement is mid-flight",
            "active_step": active,
            "status_code": 409,
            "hint": (
                f"Step '{active}' is currently waiting on you or running. "
                "Either answer the agent's pending question, restart that step, "
                "or wait for it to settle before deleting."
            ),
        }
    return (await project_tools.delete_project(project_id)).data


async def update_engagement(project_id: str, name: str | None = None,
                            description: str | None = None) -> Any:
    # Metadata-only update (name / description). Safe during active flight —
    # the agent doesn't read project name / description from lifecycle.
    return (await project_tools.update_project_metadata(
        project_id, name=name, description=description)).data


async def clone_engagement(source_project_id: str, new_name: str | None = None) -> Any:
    active = await _active_step(source_project_id)
    if active:
        return {
            "error": "source engagement is mid-flight",
            "active_step": active,
            "status_code": 409,
            "hint": (
                f"Step '{active}' is currently waiting on you or running. "
                "Clone copies artifacts but not in-progress decisions — wait "
                "for the source to settle or restart the step before cloning."
            ),
        }
    return (await project_tools.clone_project(
        source_project_id, new_name=new_name)).data


# ----- Dashboard data -----

async def dashboard_overview(engagement_id: str) -> Any:
    return (await dashboard_tools.compute_overview_stats(engagement_id)).data


async def dashboard_timeline(engagement_id: str) -> Any:
    return (await dashboard_tools.compute_timeline(engagement_id)).data


async def dashboard_stats(engagement_id: str) -> Any:
    return (await dashboard_tools.compute_stats_summary(engagement_id)).data


async def dashboard_active_step(engagement_id: str) -> Any:
    return (await dashboard_tools.compute_active_step(engagement_id)).data


async def list_decisions(engagement_id: str) -> Any:
    return (await decision_tools.read_decisions(engagement_id)).data


async def list_findings(engagement_id: str, status: str | None = None) -> Any:
    return (await decision_tools.read_findings(engagement_id, status=status)).data


async def list_open_items(engagement_id: str, status: str | None = None,
                          severity: str | None = None) -> Any:
    return (await decision_tools.read_open_items(engagement_id, status=status, severity=severity)).data


async def resolve_open_item(engagement_id: str, item_id: str, resolution_note: str | None = None) -> Any:
    return (await decision_tools.update_open_item_status(
        engagement_id, item_id=item_id, new_status="resolved",
        resolution_note=resolution_note)).data


async def get_artifact(engagement_id: str, name: str) -> Any:
    return (await artifact_tools.read_artifact(engagement_id, name)).data


async def list_engagement_artifacts(engagement_id: str, category: str | None = None) -> Any:
    return (await artifact_tools.list_artifacts(engagement_id, category=category)).data


# ----- Lifecycle / step status -----

async def get_engagement_lifecycle(engagement_id: str) -> Any:
    """Return persisted Completion Statuses per step.

    Shape: ``{"steps": {step_id: {status, updated_at, agent, note}}}``.
    Missing steps are treated as NOT_STARTED by the caller.
    """
    return (await lifecycle_tools.get_engagement_status(engagement_id)).data


async def mark_step_done(engagement_id: str, step: str, status: str = "DONE",
                        note: str = "Manual override via dashboard") -> Any:
    """Manual user override for setting a step's lifecycle status.

    Safety net for the regression mode where an agent declares completion
    in chat but never calls set_step_status. Without this route the user
    is stranded: dashboard keeps showing the in-progress CTA forever.

    Restricted to the documented status set; ``DONE`` / ``DONE_WITH_CONCERNS``
    advance to the next phase, ``BLOCKED`` halts it, ``NOT_STARTED`` rewinds.
    """
    allowed = {"DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NOT_STARTED"}
    if status not in allowed:
        return {"error": f"status must be one of {sorted(allowed)}", "got": status}
    if status == "NOT_STARTED":
        # NOT_STARTED is the way to undo a premature mark-done; clear_step_status
        # is the right tool, not set_step_status(NOT_STARTED).
        return (await lifecycle_tools.clear_step_status(engagement_id, step)).data
    return (await lifecycle_tools.set_step_status(
        engagement_id, step=step, status=status,
        agent="user-override", note=note,
    )).data


# source_agent → lifecycle phase. Used by restart paths to drop decisions
# tied to phases being wiped. SAOrchestratorAgent decisions are cross-cutting
# (flow / auto-advance / phase-routing choices, not phase-output decisions)
# so they are NOT mapped to any single phase and survive any restart.
_AGENT_TO_PHASE = {
    "SADiscoveryAgent": "discovery",
    "SADomainAgent": "design",
    "SAArchitectReviewerAgent": "review",
    "SADeveloperReviewerAgent": "review",
    "SAOpsReviewerAgent": "review",
    "SASecurityReviewerAgent": "review",
    "SAValidationAgent": "validation",
    "SAEventPortalAgent": "event-portal",
    "SABlueprintAgent": "blueprint",
}


async def _drop_decisions_for_phases(engagement_id: str, phases: set[str]) -> int:
    """Remove every decision whose source_agent maps into ``phases``.

    Returns the number of decisions removed. Orchestrator and any
    unmapped-agent decisions are preserved.
    """
    try:
        data = read_yaml(engagement_id, "meta/decisions.yaml", default={"decisions": []})
    except Exception:
        return 0
    decisions = (data or {}).get("decisions", []) or []
    if not decisions:
        return 0
    kept = [
        d for d in decisions
        if _AGENT_TO_PHASE.get(d.get("source_agent", "")) not in phases
    ]
    dropped = len(decisions) - len(kept)
    if dropped:
        write_yaml(engagement_id, "meta/decisions.yaml", {"decisions": kept})
    return dropped


async def _wipe_engagement_decisions(engagement_id: str) -> int:
    """Remove EVERY decision for this engagement, including orchestrator-authored.

    Mirrors :func:`_wipe_engagement_telemetry` for decisions.yaml. The
    phase-targeted :func:`_drop_decisions_for_phases` deliberately preserves
    SAOrchestratorAgent rows as cross-cutting flow choices, but the same
    issue that bit telemetry hits here: with SAOrchestratorAgent as the
    default chat agent, design/EP decisions get recorded under the
    orchestrator and survive a Discovery restart. User reports it as
    "Restart Discovery left 16 decisions behind."

    Used ONLY by reset_discovery (full clean-slate). Phase restarts
    (Design / Review / Validation / EP / Blueprint) should not wipe
    orchestrator decisions — those flow choices apply across phases.
    """
    try:
        existing = read_yaml(engagement_id, "meta/decisions.yaml", default={"decisions": []})
    except Exception as exc:
        # I3 fix: log the failure so a permissions/lock error is visible in
        # sam.log even when the response reports decisions_cleared=0. The
        # alternative — silent swallow — masks a corrupt-or-locked file
        # behind a misleading "success" payload.
        import logging as _logging
        _logging.getLogger(__name__).exception(
            "_wipe_engagement_decisions: read failed for %s/meta/decisions.yaml: %s",
            engagement_id, exc,
        )
        return 0
    n = len((existing or {}).get("decisions", []) or [])
    if n == 0:
        return 0
    write_yaml(engagement_id, "meta/decisions.yaml", {"decisions": []})
    return n


async def _wipe_engagement_telemetry(engagement_id: str) -> int:
    """Remove EVERY telemetry row for this engagement, including orchestrator.

    Used by full-engagement restarts (reset_discovery in particular) where the
    user expectation is "clean slate, no token history survives." The
    phase-targeted :func:`_drop_telemetry_for_phases` deliberately preserves
    SAOrchestratorAgent rows as cross-cutting flow, but when SAOrchestratorAgent
    is also the user-facing chat default, ~86% of an engagement's tokens land
    under that agent and the user reports "tokens didn't reset" (see
    2026-05-21 regression).

    This helper is intentionally distinct from the phase-targeted one — phase
    restarts (Design / Review / Validation / EP / Blueprint) should NOT wipe
    orchestrator history; only a full Discovery restart should.
    """
    path = "meta/telemetry/llm-calls.jsonl"
    try:
        rows = read_jsonl(engagement_id, path)
    except Exception:
        return 0
    if not rows:
        return 0
    # Rewrite empty — keeps the file path consistent so the next agent run
    # appends cleanly instead of triggering "file missing" creates.
    import json as _json
    _ = _json  # silence linters in case some platform yells about unused
    write_text(engagement_id, path, "")
    return len(rows)


async def _drop_telemetry_for_phases(engagement_id: str, phases: set[str]) -> int:
    """Remove every llm-calls.jsonl row whose agent maps into ``phases``.

    Mirrors :func:`_drop_decisions_for_phases` so a restart wipes the
    token-usage rows for the same phases it wipes decisions for.
    Orchestrator-authored rows (cross-cutting flow routing) are preserved,
    matching the decisions policy.

    The existing per-step ``_clear_step_telemetry`` filter keys off
    ``step_id``, which is ``None`` for almost every row in practice
    (only orchestrator-routed calls tag a step) — so without this
    agent-based filter, restarts effectively never reset the token tile.
    """
    path = "meta/telemetry/llm-calls.jsonl"
    try:
        rows = read_jsonl(engagement_id, path)
    except Exception:
        return 0
    if not rows:
        return 0
    kept = [
        r for r in rows
        if _AGENT_TO_PHASE.get(r.get("agent", "")) not in phases
    ]
    dropped = len(rows) - len(kept)
    if dropped:
        import json as _json
        content = "\n".join(_json.dumps(r, sort_keys=False) for r in kept)
        if content:
            content += "\n"
        write_text(engagement_id, path, content)
    return dropped


async def reset_discovery(engagement_id: str) -> Any:
    """Hard-reset the discovery step.

    Removes:
      - discovery/discovery-brief.yaml
      - discovery/discovery-summary.md
      - discovery/discovery-report.md (the stakeholder-ready narrative)
      - the discovery entry in meta/engagement-status.yaml
      - every decision in meta/decisions.yaml authored by SADiscoveryAgent,
        plus all decisions authored by downstream phases via cascade.
        Orchestrator-authored decisions (flow choices) are preserved.
      - every telemetry row for this engagement — both phase-attributed rows
        (per _drop_telemetry_for_phases) AND SAOrchestratorAgent rows. The
        orchestrator's rows are normally preserved as cross-cutting flow,
        but when the SAOrchestratorAgent-as-default work landed, ALL user
        chat during Discovery gets attributed to the orchestrator. A user
        restarting Discovery expects a clean slate, not 86% of tokens
        preserved (see 2026-05-21 user-report).
    Marks open-items with source='discovery' as 'superseded' (we don't
    hard-delete in case a prior agent turn referenced an item id).
    Leaves discovery/intake.json and discovery/intake.md alone — those
    are the user's submitted form, the source-of-truth for any new
    Discovery run.
    """
    removed = []
    for name in (
        "discovery/discovery-brief.yaml",
        "discovery/discovery-summary.md",
        "discovery/discovery-report.md",
    ):
        try:
            path = safe_artifact_path(engagement_id, name)
            if path.exists():
                path.unlink()
                removed.append(name)
        except Exception:
            # Don't let one missing/locked file block the rest of the reset.
            pass

    # Clear status entry
    await lifecycle_tools.clear_step_status(engagement_id, "discovery")

    # Clear the resume checkpoint so a fresh Discovery run doesn't skip
    # sub-work based on stale "we already did X" hints from the prior run.
    await session_tools.clear_checkpoint(engagement_id, "discovery")

    # Drop the metrics tied to this step — timing_data + per-step telemetry rows.
    # Without this, Stats keeps showing pre-restart numbers (see issue d).
    telemetry_cleared = await _clear_step_telemetry(engagement_id, "discovery")

    # Supersede discovery-sourced open-items
    items_res = await decision_tools.read_open_items(engagement_id, source="discovery")
    superseded = 0
    if items_res.ok and items_res.data:
        for item in items_res.data:
            if item.get("status") == "open":
                await decision_tools.update_open_item_status(
                    engagement_id, item_id=item["id"], new_status="superseded",
                    resolution_note="Superseded by Discovery restart",
                )
                superseded += 1

    # Wipe EVERY decision for this engagement — orchestrator included.
    # Same rationale as telemetry below: with SAOrchestratorAgent as the
    # default chat agent, even design/EP decisions get authored by the
    # orchestrator and survive a phase-targeted drop. User-visible symptom
    # is "Restart Discovery left 16 decisions behind." See
    # _wipe_engagement_decisions for the design rationale.
    decisions_cleared = await _wipe_engagement_decisions(engagement_id)

    # Wipe EVERY telemetry row for this engagement — orchestrator included.
    # Discovery restart means "clean slate"; the phase-targeted wipe preserved
    # SAOrchestratorAgent rows (cross-cutting flow), but when the user runs
    # Discovery through the orchestrator chat default, ~86% of tokens land
    # there and the user-visible tile never resets. See _wipe_engagement_telemetry
    # for the design rationale.
    telemetry_rows_cleared = await _wipe_engagement_telemetry(engagement_id)

    # Cascade-wipe every downstream phase (design through blueprint) — they
    # all derive from Discovery, so re-running with stale design/review/etc
    # would leave the engagement in a contradictory state.
    cascade = await _reset_downstream(engagement_id, after_step="discovery")
    removed.extend(cascade.get("cascaded_artifacts", []))
    superseded += cascade.get("cascaded_open_items_superseded", 0)
    decisions_cleared += cascade.get("cascaded_decisions_cleared", 0)
    telemetry_rows_cleared += cascade.get("cascaded_telemetry_rows_cleared", 0)

    return {
        "removed_artifacts": removed,
        "open_items_superseded": superseded,
        "findings_cleared": cascade.get("cascaded_findings_cleared", 0),
        "decisions_cleared": decisions_cleared,
        "telemetry_rows_cleared": telemetry_rows_cleared,
        "cascaded_steps": cascade.get("cascaded_steps", []),
        **telemetry_cleared,
    }


# Folders SADomainAgent writes into. The ACTUAL on-disk layout is FLAT, one
# top-level folder per scope (topic-design/topic-taxonomy.yaml,
# broker-select/broker-recommendation.yaml, integration/integration-map.yaml,
# etc.) — verified on disk. The leading "design" entry is a defensive sweep for
# any historical ``design/``-prefixed data; it's a harmless no-op when absent.
# _unlink_category() is recursive (rglob) so subdirectories are also cleaned;
# missing folders are no-ops.
_DESIGN_FOLDERS = (
    "design",                  # defensive: sweep any legacy design/-prefixed data
    "topic-design", "broker-select", "protocol-select", "integration",
    "mesh-design", "ha-dr", "sam-design", "event-portal", "migration",
)
# Backwards-compatibility alias for any external caller that imported the
# old name. Will be removed once nothing references it.
_DESIGN_SCOPE_FOLDERS = _DESIGN_FOLDERS


async def reset_design(engagement_id: str) -> Any:
    """Hard-reset the design step AND any review state derived from it.

    Removes every artifact under the nine SADomainAgent scope folders
    (topic-design/, broker-select/, ..., migration/), clears the design
    entry in meta/engagement-status.yaml, and ALSO cascades the wipe to
    Review state — because Review's findings, narratives, and step
    status are all derived from the design artifacts. Without this
    cascade, Restart Design would leave the user with stale findings
    pointing at deleted artifacts.

    Cascade includes:
      - findings.yaml: emptied (findings reference deleted artifacts).
      - reviews/*.md: per-reviewer narratives + review-summary.md unlinked.
      - review step status: cleared.
      - review-deferred open-items: superseded.

    Open-items with source='domain' are marked as superseded.

    Decisions authored by SADomainAgent in meta/decisions.yaml are
    dropped (a fresh design pass starts with a clean ledger). Decisions
    from downstream phases are dropped by the cascade. Orchestrator
    decisions (cross-cutting flow choices) are preserved.
    """
    removed = []
    # list_artifacts(engagement_id, category=<scope>) returns names like
    # "<scope>/foo.yaml"; iterate each and delete via safe_artifact_path.
    for scope in _DESIGN_FOLDERS:
        try:
            res = await artifact_tools.list_artifacts(engagement_id, category=scope)
            if not res.ok or not res.data:
                continue
            for name in res.data:
                try:
                    path = safe_artifact_path(engagement_id, name)
                    if path.exists():
                        path.unlink()
                        removed.append(name)
                except Exception:
                    pass
        except Exception:
            pass

    # Also delete the orchestrator's design-state (the deterministic engine's
    # source of truth). Without this it survives the wipe and the next Start
    # would SKIP the (now artifact-less) completed scopes instead of starting
    # fresh — so Restart wouldn't reliably mean "from scratch". Log loudly on
    # any failure: a silent skip here is the bug that lets a stale state file
    # outlive a Restart and convince the engine the work is already done.
    try:
        _dsp = safe_artifact_path(engagement_id, "meta/design-state.yaml")
        if _dsp.exists():
            _dsp.unlink()
            removed.append("meta/design-state.yaml")
    except Exception as _e:
        _log.error(
            "[reset_design] failed to delete meta/design-state.yaml for eid=%s: %r — "
            "the engine's source of truth may now be out of sync with disk; "
            "the load-time reconcile (reconcile_with_artifacts) will repair it on "
            "next advance, but please investigate the root cause", engagement_id, _e)

    # Clear the design step status + telemetry. (clear_step_status removes the
    # whole design step entry, incl. scope_progress. Domain-sourced open-items
    # are superseded inside _reset_downstream's cascade below.)
    await lifecycle_tools.clear_step_status(engagement_id, "design")
    await session_tools.clear_checkpoint(engagement_id, "design")
    telemetry_cleared = await _clear_step_telemetry(engagement_id, "design")

    # Supersede domain-sourced open-items.
    items_res = await decision_tools.read_open_items(engagement_id, source="domain")
    superseded = 0
    if items_res.ok and items_res.data:
        for item in items_res.data:
            if item.get("status") == "open":
                await decision_tools.update_open_item_status(
                    engagement_id, item_id=item["id"], new_status="superseded",
                    resolution_note="Superseded by Design restart",
                )
                superseded += 1

    # Drop design-authored decisions + telemetry rows before cascading.
    decisions_cleared = await _drop_decisions_for_phases(engagement_id, {"design"})
    telemetry_rows_cleared = await _drop_telemetry_for_phases(engagement_id, {"design"})

    # Cascade-wipe every phase downstream of design — review, validation,
    # event-portal, blueprint — since they all derive from the design
    # artifacts we just deleted. Without this, a re-run of Design would
    # leave the engagement with stale findings, validation reports, and
    # blueprint packages pointing at deleted artifacts.
    cascade = await _reset_downstream(engagement_id, after_step="design")
    removed.extend(cascade.get("cascaded_artifacts", []))
    superseded += cascade.get("cascaded_open_items_superseded", 0)
    decisions_cleared += cascade.get("cascaded_decisions_cleared", 0)
    telemetry_rows_cleared += cascade.get("cascaded_telemetry_rows_cleared", 0)

    return {
        "removed_artifacts": removed,
        "open_items_superseded": superseded,
        "findings_cleared": cascade.get("cascaded_findings_cleared", 0),
        "decisions_cleared": decisions_cleared,
        "telemetry_rows_cleared": telemetry_rows_cleared,
        "review_step_cleared": True,
        "cascaded_steps": cascade.get("cascaded_steps", []),
        **telemetry_cleared,
    }


async def reset_review(engagement_id: str) -> Any:
    """Restart the Review phase: wipe review + everything downstream.

    Cascade order: review → validation → event-portal → blueprint. Every
    artifact, step status, telemetry row, source-tagged open-item, and
    phase-authored decision in those phases is dropped. Orchestrator-
    authored decisions (cross-cutting flow choices) are preserved.
    Triggered from the Progress page's "Restart" link on the Review tile.
    """
    cascade = await _reset_downstream(engagement_id, after_step="design")
    return {
        "removed_artifacts": cascade.get("cascaded_artifacts", []),
        "open_items_superseded": cascade.get("cascaded_open_items_superseded", 0),
        "findings_cleared": cascade.get("cascaded_findings_cleared", 0),
        "decisions_cleared": cascade.get("cascaded_decisions_cleared", 0),
        "telemetry_rows_cleared": cascade.get("cascaded_telemetry_rows_cleared", 0),
        "cascaded_steps": cascade.get("cascaded_steps", []),
    }


async def reset_validation(engagement_id: str) -> Any:
    """Restart the Validation phase: wipe validation + downstream."""
    cascade = await _reset_downstream(engagement_id, after_step="review")
    return {
        "removed_artifacts": cascade.get("cascaded_artifacts", []),
        "open_items_superseded": cascade.get("cascaded_open_items_superseded", 0),
        "decisions_cleared": cascade.get("cascaded_decisions_cleared", 0),
        "telemetry_rows_cleared": cascade.get("cascaded_telemetry_rows_cleared", 0),
        "cascaded_steps": cascade.get("cascaded_steps", []),
    }


async def reset_event_portal(engagement_id: str) -> Any:
    """Restart the Event Portal phase: wipe event-portal + blueprint.

    NB: This wipes the provisioning outputs (plan/provisioned/asyncapi) AND
    the design-time event-portal-model.yaml. The model is a Design output,
    not a phase output — restarting EP probably shouldn't delete it. We
    rely on _reset_downstream's special handling to leave it intact.
    """
    cascade = await _reset_downstream(engagement_id, after_step="validation")
    return {
        "removed_artifacts": cascade.get("cascaded_artifacts", []),
        "open_items_superseded": cascade.get("cascaded_open_items_superseded", 0),
        "decisions_cleared": cascade.get("cascaded_decisions_cleared", 0),
        "telemetry_rows_cleared": cascade.get("cascaded_telemetry_rows_cleared", 0),
        "cascaded_steps": cascade.get("cascaded_steps", []),
    }


async def reset_blueprint(engagement_id: str) -> Any:
    """Restart the Blueprint phase: wipe blueprint output only (terminal step)."""
    cascade = await _reset_downstream(engagement_id, after_step="event-portal")
    return {
        "removed_artifacts": cascade.get("cascaded_artifacts", []),
        "open_items_superseded": cascade.get("cascaded_open_items_superseded", 0),
        "decisions_cleared": cascade.get("cascaded_decisions_cleared", 0),
        "telemetry_rows_cleared": cascade.get("cascaded_telemetry_rows_cleared", 0),
        "cascaded_steps": cascade.get("cascaded_steps", []),
    }


async def _reset_review_state(engagement_id: str) -> dict:
    """Clear findings + reviews/*.md artifacts. Returns counts for the response.

    Called by reset_design (cascade) and reset_review (direct). Keeps the
    wipe atomic and consistent across both entry points.
    """
    # Empty findings.yaml in place (preserves user-namespacing).
    findings_cleared = 0
    try:
        existing = read_yaml(engagement_id, "meta/findings.yaml", default={"findings": []})
        findings_cleared = len((existing or {}).get("findings", []) or [])
        write_yaml(engagement_id, "meta/findings.yaml", {"findings": []})
    except Exception:
        pass

    # Unlink everything under reviews/ — narrative .md files (per-reviewer
    # + summary) AND machine-readable artifacts like capacity-baselines.yaml.
    # No extension filter; the whole category gets cleared.
    removed = []
    try:
        res = await artifact_tools.list_artifacts(engagement_id, category="reviews")
        if res.ok and res.data:
            for name in res.data:
                try:
                    path = safe_artifact_path(engagement_id, name)
                    if path.exists():
                        path.unlink()
                        removed.append(name)
                except Exception:
                    pass
    except Exception:
        pass

    return {
        "findings_cleared": findings_cleared,
        "removed_review_artifacts": removed,
    }


async def _unlink_category(engagement_id: str, category: str) -> list:
    """Unlink every artifact under one folder. Returns names removed."""
    removed = []
    try:
        res = await artifact_tools.list_artifacts(engagement_id, category=category)
        if res.ok and res.data:
            for name in res.data:
                try:
                    path = safe_artifact_path(engagement_id, name)
                    if path.exists():
                        path.unlink()
                        removed.append(name)
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def _clear_engagement_chat_history(engagement_id: str) -> int:
    """Delete the engagement's SSE replay buffer files (the per-session chat
    history persisted under ``__system__/sse_replay/``).

    Restart wipes derived state (artifacts, findings, decisions, telemetry); the
    chat thread would otherwise reference findings/artifacts that no longer
    exist, which is confusing. Per-engagement only — other engagements' chats
    are untouched. Returns the count removed.

    Anchored regex prevents the prefix-collision trap: ``supply-chain-tracking``
    must NOT match files whose engagement is ``supply-chain-tracking-copy``. The
    session-id format is ``chat-<eid>-<tab_id>`` and tab_ids are single
    hyphen-free segments, so ``[^-]+\\.json$`` distinguishes them safely.
    """
    removed = 0
    try:
        root = Path(os.environ.get("SA_STORAGE_ROOT", "./sa-artifacts")).resolve()
        replay_dir = root / "__system__" / "sse_replay"
        if not replay_dir.exists():
            return 0
        pat = re.compile(rf"^chat-{re.escape(engagement_id)}-[^-]+\.json$")
        for p in replay_dir.iterdir():
            if p.is_file() and pat.match(p.name):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
    except Exception:
        pass
    return removed


async def _reset_downstream(engagement_id: str, *, after_step: str) -> dict:
    """Cascade-wipe every lifecycle phase strictly AFTER ``after_step``.

    Used by reset_discovery (after_step="discovery" → wipe design through
    blueprint) and reset_design (after_step="design" → wipe review
    through blueprint). Keeps lifecycle re-runs from acting on stale
    downstream state.

    Cascade order matches the lifecycle:
      discovery → design → review → validation → event-portal → blueprint

    Each step's wipe removes its artifacts, clears its step status, drops
    its telemetry, and supersedes its source-attributed open-items.
    """
    order = ("discovery", "design", "review", "validation", "event-portal", "blueprint")
    if after_step not in order:
        return {}
    start_idx = order.index(after_step) + 1
    to_wipe = order[start_idx:]

    removed = []
    findings_cleared = 0
    superseded = 0
    # Drop every decision + telemetry row authored by an agent that owns one
    # of the cascaded phases — single pass for each file so we rewrite once.
    decisions_cleared = await _drop_decisions_for_phases(engagement_id, set(to_wipe))
    telemetry_rows_cleared = await _drop_telemetry_for_phases(engagement_id, set(to_wipe))
    # Chat history (the engagement's SSE replay files) references state we're
    # about to wipe — clear it so the thread doesn't stale-reference removed
    # findings/artifacts. Per-engagement only; other engagements untouched.
    chat_files_removed = _clear_engagement_chat_history(engagement_id)

    if "design" in to_wipe:
        for scope in _DESIGN_FOLDERS:
            removed.extend(await _unlink_category(engagement_id, scope))
        items_res = await decision_tools.read_open_items(engagement_id, source="domain")
        if items_res.ok and items_res.data:
            for item in items_res.data:
                if item.get("status") == "open":
                    await decision_tools.update_open_item_status(
                        engagement_id, item_id=item["id"], new_status="superseded",
                        resolution_note=f"Superseded by {after_step.capitalize()} restart (cascade)",
                    )
                    superseded += 1
        await lifecycle_tools.clear_step_status(engagement_id, "design")
        await session_tools.clear_checkpoint(engagement_id, "design")
        await _clear_step_telemetry(engagement_id, "design")

    if "review" in to_wipe:
        review_cleared = await _reset_review_state(engagement_id)
        removed.extend(review_cleared["removed_review_artifacts"])
        findings_cleared += review_cleared["findings_cleared"]
        items_res = await decision_tools.read_open_items(engagement_id, source="review-deferred")
        if items_res.ok and items_res.data:
            for item in items_res.data:
                if item.get("status") == "open":
                    await decision_tools.update_open_item_status(
                        engagement_id, item_id=item["id"], new_status="superseded",
                        resolution_note=f"Superseded by {after_step.capitalize()} restart (cascade)",
                    )
                    superseded += 1
        await lifecycle_tools.clear_step_status(engagement_id, "review")
        await session_tools.clear_checkpoint(engagement_id, "review")
        await _clear_step_telemetry(engagement_id, "review")

    if "validation" in to_wipe:
        removed.extend(await _unlink_category(engagement_id, "validation"))
        items_res = await decision_tools.read_open_items(engagement_id, source="validation")
        if items_res.ok and items_res.data:
            for item in items_res.data:
                if item.get("status") == "open":
                    await decision_tools.update_open_item_status(
                        engagement_id, item_id=item["id"], new_status="superseded",
                        resolution_note=f"Superseded by {after_step.capitalize()} restart (cascade)",
                    )
                    superseded += 1
        await lifecycle_tools.clear_step_status(engagement_id, "validation")
        await session_tools.clear_checkpoint(engagement_id, "validation")
        await _clear_step_telemetry(engagement_id, "validation")

    if "event-portal" in to_wipe:
        # SAEventPortalAgent writes event-portal/* — plan.yaml,
        # provisioned.yaml, provisioning-report.md, asyncapi/*.yaml.
        # The design-phase event-portal-model.yaml IS also under this
        # path, but it's an INPUT to the MCP agent (produced by Design),
        # so the wipe shouldn't remove it. _unlink_category("event-portal")
        # would clobber it. Be selective: only wipe MCP-produced files.
        for art in (await artifact_tools.list_artifacts(engagement_id, category="event-portal")).data or []:
            # Keep design-phase outputs; drop only MCP/provisioning files.
            if art.endswith("event-portal-model.yaml"):
                continue
            try:
                p = safe_artifact_path(engagement_id, art)
                if p.exists():
                    p.unlink()
                    removed.append(art)
            except Exception:
                pass
        items_res = await decision_tools.read_open_items(engagement_id, source="event-portal")
        if items_res.ok and items_res.data:
            for item in items_res.data:
                if item.get("status") == "open":
                    await decision_tools.update_open_item_status(
                        engagement_id, item_id=item["id"], new_status="superseded",
                        resolution_note=f"Superseded by {after_step.capitalize()} restart (cascade)",
                    )
                    superseded += 1
        await lifecycle_tools.clear_step_status(engagement_id, "event-portal")
        await session_tools.clear_checkpoint(engagement_id, "event-portal")
        await _clear_step_telemetry(engagement_id, "event-portal")

    if "blueprint" in to_wipe:
        removed.extend(await _unlink_category(engagement_id, "blueprint"))
        removed.extend(await _unlink_category(engagement_id, "exports"))
        await lifecycle_tools.clear_step_status(engagement_id, "blueprint")
        await session_tools.clear_checkpoint(engagement_id, "blueprint")
        await _clear_step_telemetry(engagement_id, "blueprint")

    return {
        "cascaded_steps": list(to_wipe),
        "cascaded_artifacts": removed,
        "cascaded_findings_cleared": findings_cleared,
        "cascaded_open_items_superseded": superseded,
        "cascaded_decisions_cleared": decisions_cleared,
        "cascaded_telemetry_rows_cleared": telemetry_rows_cleared,
        "cascaded_chat_files_removed": chat_files_removed,
    }


# ----- Intake -----

async def intake_preview(**partial_intake) -> Any:
    """Body is the form-state dict; the adapter spreads keys → we re-pack here.

    Accepts both flat (V2) and nested (V1) shapes; normalizes before evaluating.
    """
    flat = _normalize_intake_shape(partial_intake)
    return (await intake_tools.compute_intake_preview(flat)).data


async def intake_download_yaml(**intake_dict) -> Any:
    import yaml
    return {"yaml": yaml.safe_dump(intake_dict, default_flow_style=False, sort_keys=False)}


async def intake_download_markdown(**intake_dict) -> Any:
    return {"markdown": (await intake_tools.render_intake_markdown(intake_dict)).data}


async def intake_autocomplete(query: str) -> Any:
    return (await intake_tools.integration_hub_autocomplete(query)).data


async def intake_parse_yaml(yaml_text: str) -> Any:
    """Parse uploaded YAML text and return the structured intake (for form hydration)."""
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(yaml_text)
        r = await intake_tools.parse_intake_document(path)
        return r.data if r.ok else {"error": r.error}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def intake_parse_markdown(markdown_text: str) -> Any:
    """Parse an intake Markdown document (as produced by _intake_to_markdown
    or the frontend's downloadMD) back into a structured intake dict.

    The Markdown structure is predictable — we author it ourselves with
    fixed section headers, ``**Key:** Value`` lines, and tables for
    systems/events. This parser is intentionally permissive: missing
    sections are fine, extra prose between headers is tolerated, and any
    line that can't be matched is skipped silently. The output shape
    matches the V1-nested layout intake.json uses, so callers can pass
    the result straight to the form's loadData().
    """
    import re

    out: dict[str, Any] = {
        "project": {},
        "landscape": {"systems": [], "events": [], "protocols_in_use": []},
        "domain": {},
        "requirements": {},
        "scale": {},
        "goals": {},
        "preferences": {},
    }

    # Section → bucket mapping. Keys are section number (1/4/5/6) or the
    # name SADomainAgent emits in downloadMD. Each section accumulates
    # ``**Key:** Value`` lines into the named bucket.
    section_keys = {
        "1. project": ("project", _project_key_normalize),
        "2. system landscape": ("landscape", _landscape_key_normalize),
        "3. domain details": ("domain", None),
        "4. requirements": ("requirements", _identity_key),
        "5. goals": ("goals", _identity_key),
        "6. preferences": ("preferences", _identity_key),
    }

    current_section: Optional[tuple[str, Any]] = None
    current_domain_subsection: Optional[str] = None
    in_table: Optional[str] = None   # "systems" | "events" | None
    table_columns: list[str] = []

    lines = markdown_text.splitlines()
    for raw in lines:
        line = raw.rstrip()

        # H2 — section boundary
        m_h2 = re.match(r"^##\s+(.+?)\s*$", line)
        if m_h2:
            title = m_h2.group(1).strip().lower()
            current_section = section_keys.get(title)
            current_domain_subsection = None
            in_table = None
            continue

        # H3 — sub-section: systems / events / domain-subgroup
        m_h3 = re.match(r"^###\s+(.+?)\s*$", line)
        if m_h3:
            sub_title = m_h3.group(1).strip().lower()
            if sub_title == "systems":
                in_table = "systems"
                table_columns = []
                continue
            if sub_title == "events":
                in_table = "events"
                table_columns = []
                continue
            if current_section and current_section[0] == "domain":
                current_domain_subsection = m_h3.group(1).strip()
                out["domain"].setdefault(current_domain_subsection, {})
            in_table = in_table  # leave as-is for plain H3 inside other sections
            continue

        # Table parsing for landscape.systems / landscape.events
        if in_table and line.startswith("|"):
            # Skip separator rows like |---|---|
            if re.match(r"^\|\s*-+\s*(\|\s*-+\s*)+\|?\s*$", line):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            # First non-separator row is the header
            if not table_columns:
                table_columns = [c.lower().replace(" ", "_") for c in cells]
                continue
            row: dict[str, str] = {}
            for i, val in enumerate(cells):
                if i < len(table_columns) and val:
                    row[table_columns[i]] = val
            if not row:
                continue
            if in_table == "systems":
                out["landscape"]["systems"].append(row)
            elif in_table == "events":
                # Map "payload_size" stays as-is; matches the form schema.
                out["landscape"]["events"].append(row)
            continue

        # Empty line: leave in_table state alone — we haven't seen a
        # non-table line yet, so the table may still be coming. H2/H3
        # boundaries reset in_table explicitly above; that's the right
        # cue. Skip blank lines without disturbing state.
        if not line.strip():
            continue

        # ``**Key:** Value`` extraction within the current section
        m_kv = re.match(r"^\*\*([^*:]+?):\*\*\s*(.*)$", line)
        if m_kv and current_section:
            key = m_kv.group(1).strip()
            val = m_kv.group(2).strip()
            bucket_name, key_norm = current_section
            if bucket_name == "domain" and current_domain_subsection:
                out["domain"][current_domain_subsection][key] = val
                continue
            if bucket_name == "landscape":
                # Landscape "**Protocols in use:** A, B, C" → list
                norm_key = key_norm(key) if key_norm else key
                if norm_key == "protocols_in_use":
                    out["landscape"]["protocols_in_use"] = [
                        v.strip() for v in val.split(",") if v.strip()
                    ]
                else:
                    out["landscape"][norm_key] = val
                continue
            if bucket_name == "project":
                norm_key = key_norm(key) if key_norm else key
                out["project"][norm_key] = val
                continue
            # requirements / goals / preferences — preserve original key
            out[bucket_name][key] = val
            continue

    # Strip empty containers so the form's loadData doesn't render empty rows.
    if not out["landscape"]["systems"]:
        del out["landscape"]["systems"]
    if not out["landscape"]["events"]:
        del out["landscape"]["events"]
    if not out["landscape"]["protocols_in_use"]:
        del out["landscape"]["protocols_in_use"]
    for k in ("project", "domain", "requirements", "scale", "goals", "preferences"):
        if not out[k]:
            del out[k]
    if not out["landscape"]:
        del out["landscape"]

    return {"parsed_brief": out, "open_items": []}


def _project_key_normalize(key: str) -> str:
    """Translate the human label back to the form's field name."""
    return {
        "project name": "name",
        "project type": "type",
    }.get(key.lower(), key.lower().replace(" ", "_"))


def _landscape_key_normalize(key: str) -> str:
    return {
        "existing messaging": "existing_messaging",
        "protocols in use": "protocols_in_use",
        "aggregate volumes": "volumes",
        "schemas": "schemas",
        "vertical": "vertical",
    }.get(key.lower(), key.lower().replace(" ", "_"))


def _identity_key(key: str) -> str:
    return key


async def _persist_intake_artifacts(eid: str, intake: dict, flat: dict) -> list:
    """Write the three discovery artifacts + raise blocking open-items for
    missing required fields. Shared between create and update paths so the
    on-disk shape stays identical regardless of how intake_submit was called.
    """
    import json, yaml

    # 1) Raw form payload — lossless, round-trippable. Use the ORIGINAL
    # (un-normalized) intake so the form can re-hydrate byte-perfect.
    await artifact_tools.write_artifact(
        eid, "discovery/intake.json",
        json.dumps(intake, indent=2, sort_keys=False),
    )
    # 2) Discovery brief — the normalized view that downstream agents read.
    brief_yaml = yaml.safe_dump(flat, default_flow_style=False, sort_keys=False)
    await artifact_tools.write_artifact(eid, "discovery/discovery-brief.yaml", brief_yaml)
    # 3) Human-readable Markdown — mirrors the structure of the form's
    # downloadMD() so what the user previewed offline matches what's stored.
    md_content = _intake_to_markdown(intake)
    await artifact_tools.write_artifact(eid, "discovery/intake.md", md_content)

    # Emit open-items for missing required fields (post-normalization).
    open_items = []
    for required in ("project_name", "project_type", "systems", "requirements"):
        if not flat.get(required):
            open_items.append({"severity": "blocking", "source": "intake",
                               "description": f"Required field missing: {required}"})
            await decision_tools.record_open_item(
                eid, severity="blocking", source="intake",
                description=f"Required intake field missing or unspecified: {required}",
                source_agent="WebUI-intake",
            )

    # Opt-out phases marked SKIPPED at intake so the dashboard knows they're
    # not applicable rather than sitting in NOT_STARTED limbo. The only
    # opt-in phase today is Event Portal provisioning. This block runs on
    # EVERY intake submit (including edits), so it must keep the lifecycle
    # status in sync with the current preference — without an inverse
    # branch, an edit that flips opt-out → opt-in would leave the prior
    # SKIPPED status stuck, and the dashboard would keep striking through
    # the Event Portal tile despite the user having opted in.
    prefs = flat.get("preferences") or {}
    ep_optin = bool(prefs.get("provision_event_portal"))
    current_status = (
        (await lifecycle_tools.get_engagement_status(eid)).data or {}
    ).get("steps", {}).get("event-portal", {}).get("status", "NOT_STARTED")
    if ep_optin:
        # Opt-in: undo a prior intake-time SKIPPED so the phase enters the
        # normal lifecycle. Leave DONE / IN_PROGRESS / NEEDS_CONTEXT / BLOCKED
        # alone — flipping opt-in on after the phase already ran shouldn't
        # erase completion info.
        if current_status == "SKIPPED":
            await lifecycle_tools.set_step_status(
                eid, step="event-portal", status="NOT_STARTED",
                agent="WebUI-intake",
                note="Opt-in at intake edit (preferences.provision_event_portal=true).",
            )
    else:
        # Opt-out: write SKIPPED unless the phase already has a non-trivial
        # status (don't overwrite DONE or in-progress states).
        if current_status in ("NOT_STARTED", "SKIPPED"):
            await lifecycle_tools.set_step_status(
                eid, step="event-portal", status="SKIPPED",
                agent="WebUI-intake",
                note="Opt-out at intake (preferences.provision_event_portal=false).",
            )

    # Propagate the user's intake-time execution_mode choice into the live
    # session. Without this, session.yaml defaults to "interactive" no
    # matter what the user picked in the form, and every phase kickoff
    # has to manually flip to Auto. Re-submit honours the form's current
    # value (the user can revise their mode preference by editing intake).
    mode = (prefs.get("execution_mode") or "interactive").strip().lower()
    if mode not in ("auto", "interactive"):
        mode = "interactive"
    try:
        await session_tools.update_session_state(eid, {"execution_mode": mode})
    except Exception:
        # Session update is best-effort; intake submission itself
        # already succeeded and shouldn't fail on a follow-up bookkeeping
        # write. Errors surface via sam.log.
        pass

    return open_items


async def intake_submit(**intake) -> Any:
    """Create a NEW engagement, OR re-submit an existing one (edit-mode).

    Edit-mode semantics — if the payload includes ``engagement_id``, treat as
    UPDATE: cascade-wipe every downstream phase (`_reset_downstream(after_step
    ="intake")` clears discovery → ... → blueprint so design / review /
    validation / event-portal / blueprint don't sit on stale inputs), then
    re-write the three discovery artifacts on top of the existing engagement.
    Phase-authored decisions in meta/decisions.yaml are dropped (same default
    as Restart Discovery); orchestrator decisions survive. This fixes the
    surprise where editing intake to fix a typo would otherwise create a
    second engagement.

    Otherwise (no engagement_id) — current behavior: create a new project
    and write the artifacts fresh.

    Persists THREE artifacts in both paths:
      - ``discovery/intake.json``  — lossless raw form payload (re-hydratable
                                     into the form)
      - ``discovery/discovery-brief.yaml`` — normalized YAML view for agents
      - ``discovery/intake.md`` — human-readable Markdown for handoff /
        printing / sharing

    Returns: ``{engagement_id, project, open_items, mode: "create"|"update"}``.

    Accepts both V2 flat shape (project_name, project_type, systems,
    requirements, …) and V1-style nested shape (project: {name, type},
    landscape: {systems, vertical}, …).
    """
    flat = _normalize_intake_shape(intake)

    # ---- Update path: engagement_id present in payload ----
    existing_eid = intake.get("engagement_id") or flat.get("engagement_id")
    if existing_eid:
        # Strip engagement_id from what we persist so re-hydration doesn't
        # confuse the form (the id is in the URL, not in the form fields).
        intake = {k: v for k, v in intake.items() if k != "engagement_id"}
        flat.pop("engagement_id", None)

        # Confirm the engagement exists under the caller's user namespace.
        try:
            projects = (await project_tools.list_projects(include_archived=True)).data or []
        except Exception:
            projects = []
        if not any(p.get("id") == existing_eid for p in projects):
            return {
                "error": "engagement not found under your namespace",
                "engagement_id": existing_eid,
                "status_code": 404,
            }
        # Refuse to overwrite a mid-flight engagement (same guard as archive /
        # clone). Users with a NEEDS_CONTEXT step should answer the pending
        # question or Restart first, not silently wipe their state.
        active = await _active_step(existing_eid)
        if active:
            return {
                "error": "engagement is mid-flight",
                "engagement_id": existing_eid,
                "active_step": active,
                "status_code": 409,
                "hint": (
                    f"Step '{active}' is currently running or waiting on you. "
                    "Either answer the agent's pending question, restart that step, "
                    "or wait for it to settle before re-submitting the intake."
                ),
            }

        # Cascade-wipe Discovery onward — same path as the Restart Discovery
        # button: removes discovery-brief / discovery-summary, clears the
        # discovery step status, supersedes discovery-sourced open-items, and
        # cascades to design / review / validation / event-portal / blueprint.
        # The freshly-written intake.json + discovery-brief.yaml + intake.md
        # land on top of the cleared state below.
        cascade = await reset_discovery(existing_eid)
        # Optionally rename the project if the form's name changed.
        new_name = flat.get("project_name")
        if new_name:
            try:
                await project_tools.update_project_metadata(existing_eid, name=new_name)
            except Exception:
                pass

        open_items = await _persist_intake_artifacts(existing_eid, intake, flat)
        proj = next((p for p in projects if p.get("id") == existing_eid), None) or {"id": existing_eid}
        return {
            "engagement_id": existing_eid,
            "project": proj,
            "open_items": open_items,
            "mode": "update",
            "cascaded": cascade,
        }

    # ---- Create path: no engagement_id ----
    name = flat.get("project_name") or "untitled"
    p = await project_tools.create_project(name=name)
    eid = p.data["id"]
    open_items = await _persist_intake_artifacts(eid, intake, flat)
    return {"engagement_id": eid, "project": p.data, "open_items": open_items, "mode": "create"}


def _intake_to_markdown(intake: dict) -> str:
    """Render the raw V1-nested intake payload as a Markdown document.

    Mirrors the client-side downloadMD() in webui/intake/index.html so the
    server-stored discovery/intake.md and the user-downloaded
    solace-intake.md are identical in structure. Accepts both V1 nested
    and V2 flat shapes — for flat input, we re-nest into the V1 layout
    just for the rendering pass (doesn't mutate the caller's data).
    """
    import datetime as _dt

    if not isinstance(intake, dict):
        intake = {}

    # If the payload is flat (V2), re-nest into V1 layout for rendering.
    if "project" not in intake and ("project_name" in intake or "systems" in intake):
        nested = {
            "project": {"name": intake.get("project_name"), "type": intake.get("project_type")},
            "landscape": {
                "vertical": intake.get("vertical"),
                "systems": intake.get("systems") or [],
                "existing_messaging": intake.get("existing_messaging"),
                "protocols_in_use": intake.get("protocols") or [],
                "events": intake.get("events") or [],
                "volumes": intake.get("aggregate_volumes"),
                "schemas": intake.get("schemas"),
            },
            "domain": intake.get("domain") or {},
            "requirements": intake.get("requirements") or {},
            "scale": intake.get("scale") or {},
            "goals": intake.get("goals") or {},
            "preferences": intake.get("preferences") or {},
        }
    else:
        nested = intake

    project = nested.get("project") or {}
    landscape = nested.get("landscape") or {}
    domain = nested.get("domain") or {}
    requirements = nested.get("requirements") or {}
    goals = nested.get("goals") or {}
    preferences = nested.get("preferences") or {}

    lines: list[str] = []
    lines.append("# Solace Architect — Intake")
    lines.append("")
    lines.append(f"> Generated {_dt.date.today().isoformat()}")
    lines.append("")

    lines.append("## 1. Project")
    lines.append("")
    lines.append(f"**Project name:** {project.get('name') or ''}")
    lines.append("")
    lines.append(f"**Project type:** {project.get('type') or ''}")
    lines.append("")

    lines.append("## 2. System landscape")
    lines.append("")
    lines.append("### Systems")
    lines.append("")
    lines.append("| Name | Role | Protocol | Owner |")
    lines.append("|---|---|---|---|")
    for s in (landscape.get("systems") or []):
        if not isinstance(s, dict):
            continue
        lines.append(
            f"| {s.get('name', '')} | {s.get('role', '')} | "
            f"{s.get('protocol', '')} | {s.get('owner', '')} |"
        )
    lines.append("")
    lines.append("### Events")
    lines.append("")
    lines.append("| Name | Rate | Delivery | Payload | Payload size |")
    lines.append("|---|---|---|---|---|")
    for e in (landscape.get("events") or []):
        if not isinstance(e, dict):
            continue
        lines.append(
            f"| {e.get('name', '')} | {e.get('rate', '')} | "
            f"{e.get('delivery', '')} | {e.get('payload', '')} | "
            f"{e.get('payload_size', '')} |"
        )
    lines.append("")
    lines.append(f"**Existing messaging:** {landscape.get('existing_messaging') or ''}")
    lines.append("")
    protocols_in_use = landscape.get("protocols_in_use") or landscape.get("protocols") or []
    lines.append(f"**Protocols in use:** {', '.join(protocols_in_use) if isinstance(protocols_in_use, list) else protocols_in_use}")
    lines.append("")
    lines.append(f"**Aggregate volumes:** {landscape.get('volumes') or landscape.get('aggregate_volumes') or ''}")
    lines.append("")
    # Schemas — supports both legacy string form ("Avro in Confluent")
    # and the new structured form (5 sub-fields feeding the Dev Reviewer
    # rubric: definitions_present / registry / compatibility_policy /
    # serdes_integration / notes). Render whichever shape the brief
    # carries so existing YAML uploads keep working.
    _schemas = landscape.get("schemas")
    if isinstance(_schemas, dict):
        lines.append("**Schemas:**")
        _registry_labels = {
            "solace_schema_registry": "Solace Schema Registry",
            "confluent": "Confluent Schema Registry",
            "apicurio": "Apicurio Registry",
            "aws_glue": "AWS Glue Schema Registry",
            "other": "Other", "none": "None — schemas live in code only",
            "unknown": "Unknown",
        }
        if _schemas.get("definitions_present"):
            lines.append(f"- Definitions present: {_schemas['definitions_present']}")
        if _schemas.get("registry"):
            lines.append(f"- Registry: {_registry_labels.get(_schemas['registry'], _schemas['registry'])}")
        if _schemas.get("compatibility_policy"):
            lines.append(f"- Compatibility policy: {_schemas['compatibility_policy']}")
        if _schemas.get("serdes_integration"):
            lines.append(f"- SERDES integration: {_schemas['serdes_integration']}")
        if _schemas.get("notes"):
            lines.append(f"- Notes: {_schemas['notes']}")
    else:
        lines.append(f"**Schemas:** {_schemas or ''}")
    lines.append("")
    lines.append(f"**Vertical:** {landscape.get('vertical') or ''}")
    lines.append("")

    if domain:
        lines.append("## 3. Domain details")
        lines.append("")
        for k, group in domain.items():
            if not isinstance(group, dict):
                continue
            lines.append(f"### {k}")
            lines.append("")
            for fk, fv in group.items():
                lines.append(f"**{fk}:** {fv}")
                lines.append("")

    lines.append("## 4. Requirements")
    lines.append("")
    for k, v in requirements.items():
        lines.append(f"**{k}:** {v}")
        lines.append("")

    lines.append("## 5. Goals")
    lines.append("")
    for k, v in goals.items():
        lines.append(f"**{k}:** {v}")
        lines.append("")

    lines.append("## 6. Preferences")
    lines.append("")
    for k, v in preferences.items():
        lines.append(f"**{k}:** {v}")
        lines.append("")

    return "\n".join(lines)


def _normalize_intake_shape(intake: dict) -> dict:
    """Accept V1 nested {project, landscape, requirements, goals} OR V2 flat shape.

    Returns a flat dict that downstream tools (compute_intake_preview,
    get_engagement_plan, etc.) can consume directly.
    """
    if not isinstance(intake, dict):
        return {}

    # If already flat (V2 shape), nothing to do.
    if "project_name" in intake or "systems" in intake:
        return intake

    # V1 nested shape — flatten.
    flat: dict = {}
    project = intake.get("project") or {}
    flat["project_name"] = project.get("name")
    flat["project_type"] = project.get("type")

    landscape = intake.get("landscape") or {}
    flat["vertical"] = landscape.get("vertical")
    flat["systems"] = landscape.get("systems") or []
    flat["existing_messaging"] = landscape.get("existing_messaging")
    flat["protocols"] = landscape.get("protocols") or []
    flat["events"] = landscape.get("events") or []
    flat["aggregate_volumes"] = landscape.get("aggregate_volumes")
    flat["schemas"] = landscape.get("schemas")

    flat["requirements"] = intake.get("requirements") or {}
    flat["scale"] = intake.get("scale") or {}
    flat["goals"] = intake.get("goals") or {}
    flat["preferences"] = intake.get("preferences") or {}

    # Strip None values so downstream tools don't trip on them.
    return {k: v for k, v in flat.items() if v not in (None, "", [], {})}


async def intake_load(engagement_id: str) -> Any:
    """Re-hydrate a saved intake. Returns the raw JSON if present, else {}."""
    import json
    res = await artifact_tools.read_artifact(engagement_id, "discovery/intake.json")
    if not res.ok:
        return {"intake": None, "error": "no saved intake for this engagement"}
    try:
        return {"intake": json.loads(res.data)}
    except (json.JSONDecodeError, ValueError) as e:
        return {"intake": None, "error": f"intake.json malformed: {e}"}


# ----- Exports -----

async def exports_availability(engagement_id: str) -> Any:
    r = await blueprint_tools.check_diagram_availability(engagement_id)
    if not r.ok:
        return {"error": r.error or "diagram availability check failed"}
    return r.data


async def exports_render(engagement_id: str, audience: str, format: str = "html",
                          force: bool = False) -> Any:
    # ``force`` bypasses render_audience_pack's freshness cache — surfaced
    # in the UI as a per-card "Regenerate" checkbox.
    r = await blueprint_tools.render_audience_pack(
        engagement_id, audience, format, force=bool(force),
    )
    if not r.ok:
        # Surface the underlying error to the frontend instead of returning
        # null .data — the WebUI's __renderPack click handler crashes when
        # it gets null. Common errors: "no renderer registered" (plugin
        # didn't load) and "WeasyPrint not installed" (PDF format request
        # without the PDF dep).
        return {"error": r.error or "render failed", "paths": [], "urls": []}
    # Augment the renderer's response with browser-fetchable URLs. The
    # renderer returns absolute filesystem paths (under safe_artifact_path);
    # the WebUI's /exports/raw/<filename> route serves those files with the
    # correct Content-Type. Without this, window.open(filesystem-path) hits
    # 404 because the browser can't fetch arbitrary disk paths.
    data = dict(r.data or {})
    urls: list[str] = []
    for p in data.get("paths", []) or []:
        # Each path ends with "exports/<filename>" — take the filename.
        filename = p.rsplit("/exports/", 1)[-1] if "/exports/" in p else p.rsplit("/", 1)[-1]
        urls.append(f"/api/engagements/{engagement_id}/exports/raw/{filename}")
    data["urls"] = urls
    return data


async def exports_zip(engagement_id: str) -> Any:
    r = await blueprint_tools.assemble_zip(engagement_id)
    if not r.ok:
        return {"error": r.error or "zip assembly failed", "zip_url": None}
    data = dict(r.data or {})
    # Same path-to-URL translation as exports_render.
    zip_path = data.get("zip_path") or ""
    if zip_path:
        filename = zip_path.rsplit("/exports/", 1)[-1] if "/exports/" in zip_path else zip_path.rsplit("/", 1)[-1]
        data["zip_url"] = f"/api/engagements/{engagement_id}/exports/raw/{filename}"
    return data


# ----- Feedback -----

async def engagement_token_usage(engagement_id: str, group_by: str = "agent",
                                  since: str | None = None, until: str | None = None) -> Any:
    """Per-engagement token telemetry, grouped + filtered."""
    if group_by not in _VALID_GROUP_BY_ENGAGEMENT:
        return {"error": f"invalid group_by; expected one of {sorted(_VALID_GROUP_BY_ENGAGEMENT)}"}
    r = await telemetry_tools.read_token_usage(
        engagement_id,
        group_by=group_by,  # type: ignore[arg-type]
        since=_parse_iso(since),
        until=_parse_iso(until),
    )
    return r.data if r.ok else {"error": r.error}


async def user_token_usage(group_by: str = "project",
                            since: str | None = None, until: str | None = None) -> Any:
    """Cross-engagement token telemetry for the current user."""
    if group_by not in _VALID_GROUP_BY_USER:
        return {"error": f"invalid group_by; expected one of {sorted(_VALID_GROUP_BY_USER)}"}
    r = await telemetry_tools.read_user_token_usage(
        group_by=group_by,  # type: ignore[arg-type]
        since=_parse_iso(since),
        until=_parse_iso(until),
    )
    return r.data if r.ok else {"error": r.error}


async def submit_feedback(engagement_id: str, scope: str, rating: int,
                          category: str, note: str) -> Any:
    return (await decision_tools.record_feedback(
        engagement_id, scope=scope, rating=rating, category=category, note=note)).data


# ----- Design orchestrator (deterministic Design engine) -----
#
# The server-side "brain" for the rebuilt Design phase. It owns design_state
# (the single writer), decides what runs next, and hands the frontend a thin
# action to execute. The frontend is a dumb executor: it dispatches the scope
# the orchestrator names, reports the outcome, and asks again. This collapses
# the old auto-advance / dedup / fresh-session / escalation machinery into one
# deterministic, testable place — and the orchestrator NEVER trusts a self-
# report for "done": it checks the scope's structured artifact on disk.

# Per-scope structured artifact whose existence === "scope complete". FLAT
# per-scope layout (verified on disk; the `design/`-prefixed layout in some
# older comments was never the real shape).
_SCOPE_PRIMARY_ARTIFACT = {
    "topic-design": "topic-design/topic-taxonomy.yaml",
    "broker-select": "broker-select/broker-recommendation.yaml",
    "protocol-select": "protocol-select/protocol-map.yaml",
    "integration": "integration/integration-map.yaml",
    "mesh-design": "mesh-design/dmr-topology.yaml",
    "ha-dr": "ha-dr/ha-dr-design.yaml",
    "sam-design": "sam-design/sam-topology.yaml",
    "event-portal": "event-portal/event-portal-model.yaml",
    "migration": "migration/migration-plan.yaml",
}


async def _applicable_design_scopes(engagement_id: str) -> list:
    """Ordered design scopes that apply to this engagement.

    Derived from the routing plan (``get_engagement_plan``) filtered to
    SADomainAgent scopes that are ``included`` — so it respects the exact
    when-clause applicability already used everywhere else, rather than
    re-deriving it.
    """
    brief = workflow_tools.effective_brief(engagement_id)
    plan = (await workflow_tools.get_engagement_plan(brief)).data or []
    return [
        p["scope"] for p in plan
        if p.get("agent") == "SADomainAgent" and p.get("scope") and p.get("included")
    ]


def _scope_artifact_exists(engagement_id: str, scope: str) -> bool:
    rel = _SCOPE_PRIMARY_ARTIFACT.get(scope)
    if not rel:
        return False
    try:
        return safe_artifact_path(engagement_id, rel).exists()
    except Exception:
        return False


# Per-scope human-readable companion (rendered deterministically from the YAML).
_SCOPE_PROSE_ARTIFACT = {s: f"{s}/{s}.md" for s in _SCOPE_PRIMARY_ARTIFACT}

# Scopes whose COMPUTED block is the COMPLETE structured output (not just inputs):
# the worker can write the artifact straight from it with no grounding/derivation.
# This collapses the scope to ONE tool call in ONE turn — the minimum exposure to
# a flaky gateway (these are the heaviest/most-failure-prone scopes). broker-select
# / mesh-design / ha-dr are NOT here: their COMPUTED block carries inputs, and the
# worker still does design + grounding on top.
_FULLY_DECIDED_SCOPES = frozenset({"integration", "event-portal"})


def _ensure_scope_prose(engagement_id: str, scope: str) -> None:
    """Phase C: render the scope's .md companion from its structured YAML when
    the YAML exists and the .md does not. Deterministic, no LLM. Never clobbers
    an existing .md (e.g. one a worker authored under the classic engine), and
    never raises — missing prose must not block advancement."""
    struct_rel = _SCOPE_PRIMARY_ARTIFACT.get(scope)
    prose_rel = _SCOPE_PROSE_ARTIFACT.get(scope)
    if not struct_rel or not prose_rel:
        return
    try:
        if safe_artifact_path(engagement_id, prose_rel).exists():
            return
        data = read_yaml(engagement_id, struct_rel, default=None)
        if not data:
            return
        write_text(engagement_id, prose_rel, _prose.render_scope_markdown(scope, data))
    except Exception:
        return


def _ensure_event_portal_artifact(engagement_id: str) -> None:
    """Event-portal is fully decided: the orchestrator derives the COMPLETE model
    (domains/applications/events) from the taxonomy + brief. Write it to SA storage
    deterministically rather than relying on the worker to echo a ~14KB block back
    out — large models get emitted as a SAM native artifact block, which saves into
    the ADK artifact-service layout (not SA's ``users/<uid>/<eid>/...`` path), so
    ``_scope_artifact_exists`` never sees it and the scope retries until exhausted.

    Idempotent (never clobbers an existing model), best-effort (a missing taxonomy
    or derivation failure must not crash advance — the worker path still exists)."""
    rel = _SCOPE_PRIMARY_ARTIFACT["event-portal"]
    try:
        if safe_artifact_path(engagement_id, rel).exists():
            return
        tax = read_yaml(engagement_id, "topic-design/topic-taxonomy.yaml", default=None)
        if not tax:
            return
        model = _event_portal_model.derive_event_portal_model(
            tax, workflow_tools.effective_brief(engagement_id) or {})
        if not model or not (
            model.get("domains") or model.get("events") or model.get("applications")
        ):
            return
        write_yaml(engagement_id, rel, model)
    except Exception:
        return


def _build_scope_context(engagement_id: str) -> str:
    """Pre-gather the context a worker would otherwise spend round-trips reading
    every session — the discovery brief + a COMPACT decisions list — and embed
    it in the kickoff. This removes the read_artifact(brief)/read_decisions
    round-trips (3-4 LLM calls before any real work), which both wastes tokens
    (re-prefilled each call on an uncached gateway) AND adds stall exposure. Read
    deterministically/synchronously (no LLM, no tool round-trip); size-capped.
    """
    import yaml as _yaml
    blocks = []
    try:
        brief = workflow_tools.effective_brief(engagement_id) or {}
        if brief:
            y = _yaml.safe_dump(brief, sort_keys=False, default_flow_style=False)
            blocks.append(
                "## Discovery brief (PROVIDED — do NOT read discovery-brief.yaml)\n"
                "```yaml\n" + y[:6000] + "\n```"
            )
    except Exception:
        pass
    try:
        decs = (read_yaml(engagement_id, "meta/decisions.yaml", default={}) or {}).get("decisions") or []
        if decs:
            # Compact: id + what was decided + what was chosen. Drop the long
            # rationale prose (the worker needs consistency, not the full text).
            lines = [
                f"- [{d.get('id', '?')}] {str(d.get('context', '')).strip()} → {str(d.get('selected', '')).strip()}"
                for d in decs
            ][:80]
            blocks.append(
                "## Decisions so far (PROVIDED — do NOT call read_decisions)\n"
                + "\n".join(lines)[:5000]
            )
    except Exception:
        pass
    if not blocks:
        return ""
    return "\n\n--- CONTEXT (provided so you don't re-read it) ---\n" + "\n\n".join(blocks)


def _build_worker_kickoff(engagement_id: str, scope: str, done: list, mode: str) -> str:
    """The message the frontend sends to SADomainAgent in WORKER MODE.

    Carries the engagement header + the single scope to produce + a pre-gathered
    context bundle (brief + decisions) so the worker skips the re-read
    round-trips. Pairs with the WORKER MODE section of the domain prompt, which
    constrains the agent to one scope and forbids self-orchestration.
    """
    uid = (get_current_user() or {}).get("id") or "anonymous"
    done_str = ", ".join(done) if done else "(none yet)"
    # Phase B: for decidable scopes, inject the deterministic computed values so
    # the worker uses them verbatim instead of doing (or hallucinating) the math.
    rules_block = ""
    try:
        computed = _rules.compute_scope_rules(scope, workflow_tools.effective_brief(engagement_id))
        if computed:
            rules_block = "\n\n" + _rules.render_rules_block(scope, computed)
    except Exception:
        rules_block = ""
    # Event-portal scope: derive the EP model (domains/apps/events) from the
    # taxonomy + landscape so the worker writes event-portal-model.yaml in one
    # turn. Done here (not in compute_scope_rules, which is brief-only) because
    # it needs the topic-taxonomy artifact.
    if scope == "event-portal":
        try:
            tax = read_yaml(engagement_id, "topic-design/topic-taxonomy.yaml", default=None)
            model = _event_portal_model.derive_event_portal_model(
                tax, workflow_tools.effective_brief(engagement_id) or {})
            rules_block += "\n\n" + _rules.render_rules_block(
                "event-portal", {"event_portal_model": model})
        except Exception:
            pass
    context_block = ""
    try:
        context_block = _build_scope_context(engagement_id)
    except Exception:
        context_block = ""

    # Pre-injection (token lever): for non-fast-path scopes, embed a compact
    # grounding excerpt so the worker usually skips the load_grounding round-trips
    # (the request turn + the consuming turn — the slow, stall-prone part). It's
    # REFERENCE only and the worker may still load/fetch the full text, so this
    # never presents partial content as complete-authoritative. Fast-path scopes
    # already say "no grounding" (the COMPUTED block is the whole answer).
    grounding_block = ""
    if scope not in _FULLY_DECIDED_SCOPES:
        try:
            gp = grounding_tools.grounding_pack_for_scope(scope)
            if gp:
                grounding_block = (
                    "\n\n--- GROUNDING (reference for this scope, PROVIDED so you "
                    "usually don't need load_grounding; call it only if a topic you "
                    "need isn't covered here) ---\n" + gp
                )
        except Exception:
            grounding_block = ""

    header = (
        f"[Active engagement: engagement_id={engagement_id}, user_id={uid}]\n"
        f"WORKER MODE\n"
        f"Scope: {scope}\n"
        f"Scopes already complete: {done_str}\n"
        f"Mode: {mode}\n\n"
    )
    # FAST PATH — a fully-decided scope (integration / event-portal) whose COMPUTED
    # block IS the complete output: collapse to ONE write_artifact, no grounding /
    # lookups. Fewer tool calls = fewer turns = the least exposure to a flaky
    # gateway (these are the heaviest, most drop-prone scopes).
    if scope in _FULLY_DECIDED_SCOPES and rules_block:
        artifact = _SCOPE_PRIMARY_ARTIFACT.get(scope, f"{scope}/{scope}.yaml")
        body = (
            f"FAST PATH — this scope is FULLY DECIDED by the COMPUTED block below. "
            f"Do NOT call load_grounding, fetch_canonical_source, read_decisions, or "
            f"any other tool first. In ONE turn make a SINGLE write_artifact call to "
            f"`{artifact}`, transcribing the COMPUTED values into YAML (you may add "
            f"brief rationale fields, but do NOT re-derive, re-decide, or look "
            f"anything up). Then END the turn. Do NOT call record_scope_progress or "
            f"set_step_status — the orchestrator owns progress. Do NOT pick or start "
            f"the next scope."
        )
    else:
        body = (
            f"Produce ONLY the `{scope}` scope: its structured YAML artifact. The "
            f"discovery brief and prior decisions are PROVIDED below — do NOT read "
            f"discovery-brief.yaml or call read_decisions, and do NOT resume-check "
            f"your scope's artifact (the orchestrator manages that). Go straight to "
            f"the work, using grounding (load_grounding) only for the scope topic. If "
            f"a blocking decision needs the user, ask exactly ONE question via "
            f"ask_user_question and stop. Do NOT pick, mention, or start the next "
            f"scope. Do NOT call record_scope_progress or set_step_status — the "
            f"orchestrator owns progress. End the turn once the artifact is written "
            f"or you have asked your one question."
        )
    kickoff = header + body + f"{rules_block}{context_block}{grounding_block}"
    # Diagnostic: confirm the worker kickoff carries WORKER MODE + the computed
    # rules/EP block (the integration_map / event_portal_model fix). If a scope
    # keeps failing, this line proves whether the map actually reached the worker.
    _log.info(
        "[design-orchestrator] built WORKER kickoff scope=%s mode=%s len=%d "
        "rules_block=%s context_block=%s grounding=%s fast_path=%s",
        scope, mode, len(kickoff), bool(rules_block), bool(context_block),
        bool(grounding_block), bool(scope in _FULLY_DECIDED_SCOPES and rules_block),
    )
    return kickoff


# Base Validation kickoff — kept identical to the FE's prior static string so the
# only behavioural change is the appended PRECOMPUTED CHECKS block.
_VALIDATION_KICKOFF_BASE = (
    "Phase: validation\n\n"
    "Run the Validation phase. Apply your rubric (requirement coverage, antipattern "
    "scan, consistency, deferred findings, terminology compliance, schema sanity, "
    "subscription syntax). Record blocking open-items with affecting_step=\"blueprint\" "
    "so the lifecycle gates correctly. Write validation/validation-report.md and the "
    "machine YAML. Call set_step_status(step=\"validation\", ...) per the rule."
)


def _render_validation_findings_block(result: dict) -> str:
    """Render the deterministic validation findings, split into AUTHORITATIVE
    (mechanical lenses — record verbatim) and CANDIDATE (judgment lenses — confirm
    against the artifact before recording blocking). The split prevents the agent
    from self-blocking the pipeline on a deterministic false positive: a candidate
    it verifies as wrong is dismissed with a rationale, not recorded blocking."""
    findings = result.get("findings") or []
    counts = result.get("counts") or {}
    if not findings:
        return (
            "\n\n--- PRECOMPUTED CHECKS (authoritative) ---\n"
            "All deterministic lenses PASSED — no subscription-syntax, schema-sanity, "
            "terminology, integration-coverage, or mesh-consistency issues. Do NOT re-run "
            "these lenses. Spend your turns ONLY on: antipattern interpretation, "
            "deferred-finding triage, full requirement tracing (trace_requirements), and "
            "the report narrative."
        )
    authoritative = [f for f in findings if not f.get("confirm")]
    candidates = [f for f in findings if f.get("confirm")]

    def _fmt(f: dict) -> str:
        return f"- [{f.get('severity')}] {f.get('lens')} @ {f.get('artifact')}: {f.get('detail')}"

    lines = [
        f"\n\n--- PRECOMPUTED CHECKS ({counts.get('blocking', 0)} blocking, "
        f"{counts.get('advisory', 0)} advisory) ---",
    ]
    if authoritative:
        lines.append(
            "AUTHORITATIVE (mechanical lenses — record these as open-items VERBATIM; "
            "do NOT re-derive or second-guess them):")
        lines += [_fmt(f) for f in authoritative]
    if candidates:
        lines.append(
            "CANDIDATES (confirm before recording — these lenses can be wrong, e.g. a "
            "system covered under an alias the matcher missed). For EACH: check the named "
            "artifact. If the gap is real, record it as a blocking open-item. If it is a "
            "FALSE POSITIVE, do NOT record it blocking — note the dismissal with a "
            "one-line rationale in the report. NEVER block the pipeline on a finding you "
            "have verified is wrong.")
        lines += [_fmt(f) for f in candidates]
    lines.append(
        "Then spend your turns ONLY on the judgment lenses the rules can't compute: "
        "antipattern interpretation, deferred-finding triage, full requirement tracing "
        "(trace_requirements), and writing the report narrative."
    )
    return "\n".join(lines)


def _build_validation_kickoff(engagement_id: str) -> str:
    """Validation kickoff = the base instruction + a PRECOMPUTED CHECKS block from
    the deterministic validation engine. Fail-soft to the bare instruction.

    The deterministic checks parse FULL artifact content read straight from
    storage — NOT the size-capped context bundle. (Truncated YAML mis-parses,
    which the schema-sanity lens would report as a BLOCKING "did not parse"
    finding on an artifact that is actually valid on disk — a server-induced
    false positive that would gate the workflow. Validation is one synchronous
    pass, so reading full content here costs no LLM round-trips.)"""
    try:
        import yaml as _yaml
        brief = workflow_tools.effective_brief(engagement_id) or {}
        texts: dict = {}
        parsed: dict = {}
        for name in _context_pack.DESIGN_ARTIFACTS:
            try:
                raw = read_text(engagement_id, name)
            except FileNotFoundError:
                continue  # absent scope — not a schema concern
            except Exception:
                continue
            texts[name] = raw
            try:
                parsed[name] = _yaml.safe_load(raw)
            except Exception:
                parsed[name] = None  # genuine parse failure on FULL content = real blocker
        forbidden = [t for t, _sug in artifact_tools._FORBIDDEN_TERMS]
        result = _validation_rules.run_validation_rules(
            brief=brief, parsed_artifacts=parsed,
            artifact_texts=texts, forbidden_terms=forbidden,
        )
        return _VALIDATION_KICKOFF_BASE + _render_validation_findings_block(result)
    except Exception:
        return _VALIDATION_KICKOFF_BASE


_BLUEPRINT_KICKOFF_BASE = (
    "Phase: blueprint\n\n"
    "Assemble the final blueprint package. Compose blueprint/architecture.md + "
    "blueprint/runbook.md, write available Mermaid diagrams, render 5 audience "
    "packs (blueprint/executive/admin-ops/security/developers, both md+pdf), then "
    "assemble_zip to produce exports/engagement-package.zip. Call "
    "set_step_status(step=\"blueprint\", ...) per the rule."
)


def _build_blueprint_kickoff(engagement_id: str) -> str:
    """Blueprint kickoff = base instruction + the deterministic section outline +
    the design artifacts that fit inlined IN FULL, with any oversized artifact
    routed to read_artifact. Fail-soft to the bare base.

    CRITICAL: only artifacts inlined IN FULL are marked authoritative. An
    artifact larger than the per-artifact cap is NOT inlined (a truncated body
    presented as authoritative would silently drop content from the final
    customer-facing blueprint); instead the agent is told to read it in full.
    This keeps the kickoff bounded AND complete."""
    try:
        cap = 8000
        bundle = _context_pack.build_artifact_bundle(engagement_id, max_chars_each=cap)
        present = bundle.get("present", [])
        if not present:
            return _BLUEPRINT_KICKOFF_BASE
        truncated = set(bundle.get("truncated", []))
        artifacts = bundle.get("artifacts", {})
        full_names = [n for n in present if n not in truncated]
        outline = _blueprint_render.present_sections({n: True for n in present})

        block = ["\n\n--- DESIGN ARTIFACTS ---"]
        if outline:
            block.append("Section order (use exactly this; Executive Summary first, "
                         "Decisions Register last):")
            block.append("  " + " → ".join(outline))
        if full_names:
            block.append("\nPROVIDED IN FULL below — compose directly from these; do "
                         "NOT re-read them with read_artifact:")
            for n in full_names:
                block.append(f"\n### {n}\n{artifacts.get(n, '')}")
        if truncated:
            block.append("\nTOO LARGE TO INLINE — you MUST call read_artifact on EACH "
                         "of these and use the FULL content (do not skip, do not rely "
                         "on any partial copy):")
            for n in sorted(truncated):
                block.append(f"- {n}")
        if bundle.get("missing"):
            block.append(f"\n(not produced: {', '.join(bundle['missing'])})")
        return _BLUEPRINT_KICKOFF_BASE + "\n".join(block)
    except Exception:
        return _BLUEPRINT_KICKOFF_BASE


def _sync_dashboard_scope_progress(engagement_id: str, st: dict) -> None:
    """Mirror the orchestrator's design-state into engagement-status.yaml's
    ``scope_progress`` so the dashboard strip (which reads scope_progress)
    reflects the orchestrator's TRUTH: accurate done[], the active scope, and a
    per-scope status map. The orchestrator is the single authoritative writer —
    this OVERWRITES any stale scope_progress a worker wrote despite WORKER MODE
    (the cause of the dashboard/orchestrator divergence). Best-effort; never
    breaks advancement. Runs AFTER set_step_status (which merges), so the design
    step status it just wrote is preserved."""
    try:
        scopes = st.get("scopes", [])
        terminal = _design_state._TERMINAL_ADVANCE
        done = [s["name"] for s in scopes if s.get("status") in terminal]
        nxt = _design_state.next_scope(st)
        active = next((s for s in scopes if s.get("name") == nxt), None) if nxt else None
        sp = {
            "current": (active["name"] if active else (done[-1] if done else None)),
            "next": nxt,
            "done": done,
            "status": (active.get("status") if active else "done"),
            # Full per-scope status map so the FE can render in-progress / blocked
            # distinctly, not just done/next/pending.
            "scope_states": {s["name"]: s.get("status") for s in scopes},
            "updated_at": st.get("updated_at"),
            "note": (active.get("note", "") if active else ""),
        }
        data = read_yaml(engagement_id, "meta/engagement-status.yaml", default={"steps": {}}) or {"steps": {}}
        data.setdefault("steps", {}).setdefault("design", {})
        data["steps"]["design"]["scope_progress"] = sp
        write_yaml(engagement_id, "meta/engagement-status.yaml", data)
    except Exception:
        pass


async def validation_kickoff_view(engagement_id: str) -> Any:
    """GET — the Validation kickoff with the deterministic PRECOMPUTED CHECKS block
    injected, so SAValidationAgent records those findings verbatim instead of
    re-deriving the mechanical lenses. The FE fetches this instead of using a
    static string (falls back to the static string if this call fails)."""
    return {"kickoff": _build_validation_kickoff(engagement_id)}


async def blueprint_kickoff_view(engagement_id: str) -> Any:
    """GET — the Blueprint kickoff with the design artifacts bundled inline (one
    payload vs ~20 reads) + the deterministic section outline, so SABlueprintAgent
    composes from provided content instead of re-reading everything. FE fetches
    this; falls back to the static string if it fails."""
    return {"kickoff": _build_blueprint_kickoff(engagement_id)}


async def design_scope_kickoff(engagement_id: str) -> Any:
    """GET — rebuild the WORKER kickoff for the currently-RUNNING design scope,
    WITHOUT mutating state (no attempt burned).

    Used by stream-drop recovery: a transient gateway drop should re-send the
    SAME map-carrying kickoff (WORKER MODE + computed rules / EP model) so the
    worker keeps the deterministic context, instead of the generic resume that
    bypasses the orchestrator and makes the worker re-derive from scratch."""
    st = _design_state.load_state(engagement_id)
    if st is None:
        return {"scope": None}
    running = None
    done: list = []
    for s in (st.get("scopes") or []):
        status = s.get("status")
        if status == _design_state.RUNNING and running is None:
            running = s.get("name")
        if status in _design_state._TERMINAL_ADVANCE:
            done.append(s.get("name"))
    if not running:
        _log.info("[design-orchestrator] scope-kickoff eid=%s — no RUNNING scope", engagement_id)
        return {"scope": None}
    kickoff = _build_worker_kickoff(engagement_id, running, done, st.get("mode", "auto"))
    _log.info("[design-orchestrator] scope-kickoff eid=%s scope=%s (drop-resume; no attempt burned)",
              engagement_id, running)
    return {"scope": running, "kickoff": kickoff}


async def design_state_view(engagement_id: str) -> Any:
    """GET — the orchestrator's current design state + the next action, for the
    frontend to render progress and know what to do."""
    st = _design_state.load_state(engagement_id)
    if st is None:
        return {
            "exists": False,
            "applicable": await _applicable_design_scopes(engagement_id),
        }
    return {
        "exists": True,
        "state": st,
        "action": _design_state.decide_next(st),
        "metrics": _design_state.metrics(st),
    }


async def design_advance(
    engagement_id: str,
    mode: str = "auto",
    last_scope: Optional[str] = None,
    outcome: Optional[str] = None,
    note: Optional[str] = None,
    reset_scope: Optional[str] = None,
) -> Any:
    """POST — serialized per engagement so the scope-transition claim is atomic
    (see _design_advance_lock). Delegates to the implementation under the lock."""
    async with _design_advance_lock(engagement_id):
        return await _design_advance_impl(
            engagement_id, mode=mode, last_scope=last_scope,
            outcome=outcome, note=note, reset_scope=reset_scope,
        )


async def _design_advance_impl(
    engagement_id: str,
    mode: str = "auto",
    last_scope: Optional[str] = None,
    outcome: Optional[str] = None,
    note: Optional[str] = None,
    reset_scope: Optional[str] = None,
) -> Any:
    """POST — the orchestration step. Reconcile state with artifacts on disk,
    record the just-finished scope's outcome, and return the next action.

    Body:
      mode:        "auto" | "interactive" (only used when state is first created)
      last_scope:  scope that just ran (omit on the very first call)
      outcome:     "question" | "failed" | null  (null → infer from artifact)
      note:        optional human-readable note
      reset_scope: clear this scope's status + retry budget (the "retry scope"
                   affordance after retry_exhausted / blocked)
    """
    applicable = await _applicable_design_scopes(engagement_id)
    if not applicable:
        return {"action": "complete", "reason": "no applicable design scopes"}

    st = _design_state.load_state(engagement_id)
    if st is None:
        st = _design_state.init_state(
            applicable, mode=mode if mode in ("auto", "interactive") else "auto"
        )

    # Manual retry: clear a previously exhausted/blocked scope's budget so
    # decide_next will dispatch it again instead of immediately re-surfacing.
    if reset_scope and _design_state.scope_status(st, reset_scope) is not None:
        _design_state.reset_scope(st, reset_scope)

    # Event-portal is fully decided — materialise its derived model in SA storage
    # so the reconcile below detects it as done (the worker's native artifact-block
    # save never lands in SA's path; see _ensure_event_portal_artifact).
    if "event-portal" in applicable:
        _ensure_event_portal_artifact(engagement_id)

    # Reconcile (DOWN): any scope marked done whose primary artifact is missing
    # gets demoted back to pending. Prevents the engine from short-circuiting to
    # action=complete on a state-vs-artifact desync (e.g., a partial reset that
    # cleared scope files but left meta/design-state.yaml, or a clone that
    # copied state without artifacts). Without this, Start Design would lie
    # ("all done") despite zero work having happened.
    _st, _demoted = _design_state.reconcile_with_artifacts(
        st, lambda sc: _scope_artifact_exists(engagement_id, sc))
    if _demoted:
        _log.warning(
            "[design-orchestrator] reconciled stale design-state for eid=%s — "
            "demoted scopes %s back to pending (state claimed done but no "
            "artifact on disk)", engagement_id, _demoted)

    # Reconcile (UP): any scope whose structured artifact already exists is DONE.
    # This is how the orchestrator learns "done" — from the durable artifact,
    # never a self-report — and it heals an engagement that ran partway under
    # the classic engine.
    for scope in applicable:
        if (
            _design_state.scope_status(st, scope) not in _design_state._TERMINAL_ADVANCE
            and _scope_artifact_exists(engagement_id, scope)
        ):
            _design_state.complete_scope(st, scope)

    # Apply the just-finished scope's outcome (only if the artifact reconcile
    # above didn't already complete it). A pending question parks the scope for
    # the user; anything else that finished WITHOUT producing the artifact (an
    # explicit "failed", a stall, or just an empty turn) counts as a failed
    # attempt so the retry budget governs it — never an infinite in_flight wait.
    if last_scope and _design_state.scope_status(st, last_scope) is not None:
        cur = _design_state.scope_status(st, last_scope)
        if cur not in _design_state._TERMINAL_ADVANCE:
            if outcome == "question":
                _design_state.needs_input(st, last_scope, note=note or "awaiting user answer")
            else:
                _design_state.fail_scope(st, last_scope, note=note or "scope did not complete")

    _design_state.save_state(engagement_id, st)

    # Phase C: ensure each completed scope has its deterministic prose companion
    # (workers write only the structured YAML now). Idempotent + best-effort.
    for scope in applicable:
        if _design_state.scope_status(st, scope) in _design_state._TERMINAL_ADVANCE:
            _ensure_scope_prose(engagement_id, scope)

    action = _design_state.decide_next(st)
    # Diagnostic: what the orchestrator decided this call, and why we got here.
    _log.info(
        "[design-orchestrator] advance eid=%s last_scope=%s outcome=%s reset=%s "
        "→ action=%s scope=%s attempts=%s",
        engagement_id, last_scope, outcome, reset_scope,
        action.get("action"), action.get("scope"), action.get("attempts"),
    )

    if action.get("action") == "dispatch":
        scope = action["scope"]
        _design_state.begin_scope(st, scope)          # claim the attempt + RUNNING
        _design_state.save_state(engagement_id, st)
        action["agent"] = "SADomainAgent"
        action["kickoff"] = _build_worker_kickoff(
            engagement_id, scope, action.get("done", []), st.get("mode", "auto")
        )

    # Best-effort mirror to the lifecycle banner so the dashboard Design tile is
    # truthful (design_state stays the source of truth). set_step_status merges,
    # so this never clobbers scope sub-state.
    _act = action.get("action")
    _scope = action.get("scope", "")
    _sync = {
        "complete": ("DONE", "All design scopes complete"),
        "blocked": ("BLOCKED", action.get("note") or f"{_scope} blocked"),
        "retry_exhausted": ("NEEDS_CONTEXT",
                            f"{_scope} failed after {action.get('attempts')} attempts"),
        "dispatch": ("IN_PROGRESS", f"Design scope: {_scope}"),
        "await_user": ("IN_PROGRESS", f"Design scope: {_scope} — awaiting your answer"),
        "in_flight": ("IN_PROGRESS", f"Design scope: {_scope}"),
    }.get(_act)
    if _sync:
        await lifecycle_tools.set_step_status(
            engagement_id, step="design", status=_sync[0], note=_sync[1],
            agent="DesignOrchestrator",
        )

    # Mirror design-state → scope_progress so the dashboard reflects the
    # orchestrator's truth (accurate done[], active scope, per-scope statuses),
    # overriding any stale worker-written scope_progress.
    _sync_dashboard_scope_progress(engagement_id, st)

    return action


# Route table — consumed by lifecycle.py to register with the SAM HTTP runtime.
# ---------------------------------------------------------------------------
# Admin: managed global grounding references (admin-only).
#
# These routes are declared with a trailing ``True`` admin flag in API_ROUTES;
# component._adapt_api_handler enforces it via _is_admin_user() and returns 403
# for non-admins. The gate is DECLARATIVE (one flag per route) rather than a
# per-handler check, so a new admin route can't accidentally ship ungated.
# The agent read path (load_managed_grounding) is intentionally NOT here — it is
# an agent tool, and only ever serves already-approved content.
# ---------------------------------------------------------------------------

def _is_admin_user() -> bool:
    """True when the current request's authenticated user is an admin.

    Reads the per-request ``current_user`` contextvar the auth middleware sets
    from the validated session cookie. Anonymous / dev-bypass users are never
    admin, so the managed-grounding admin surface requires auth enabled + an
    admin account (see `python -m ...admin make-admin <user>`)."""
    return bool((get_current_user() or {}).get("is_admin"))


def _admin_actor() -> str:
    u = get_current_user() or {}
    return u.get("name") or u.get("id") or "admin"


async def admin_grounding_list(status: Optional[str] = None, **_) -> Any:
    res = await managed_grounding_tools.list_managed_references(status or None)
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_add(ref_type: Optional[str] = None, source: Optional[str] = None,
                              title: Optional[str] = None, **_) -> Any:
    res = await managed_grounding_tools.add_managed_reference(
        ref_type or "", source or "", title=title, added_by=_admin_actor())
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_get(ref_id: str = "", **_) -> Any:
    res = await managed_grounding_tools.get_managed_reference(ref_id)
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_set_status(ref_id: str = "", status: Optional[str] = None, **_) -> Any:
    res = await managed_grounding_tools.set_managed_reference_status(
        ref_id, status or "", actor=_admin_actor())
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_refresh(ref_id: str = "", **_) -> Any:
    res = await managed_grounding_tools.refresh_managed_reference(ref_id, actor=_admin_actor())
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_edit(ref_id: str = "", title: Optional[str] = None,
                               content: Optional[str] = None, **_) -> Any:
    res = await managed_grounding_tools.edit_managed_reference(
        ref_id, title=title, content=content, actor=_admin_actor())
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_refresh_all(**_) -> Any:
    res = await managed_grounding_tools.refresh_all_managed_references(actor=_admin_actor())
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_remove(ref_id: str = "", **_) -> Any:
    res = await managed_grounding_tools.remove_managed_reference(ref_id)
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_platform_list(**_) -> Any:
    """List the vendored platform-grounding files (read-only). The admin UI
    shows these alongside admin-curated managed refs so an admin can see
    what's already covered before deciding whether to add a managed ref."""
    res = grounding_tools.list_platform_grounding()
    return res.data if res.ok else {"error": res.error}


async def admin_grounding_gaps(**_) -> Any:
    """Surface the runtime grounding-gaps ledger as 'suggested references to add',
    aggregated by topic (most-requested first)."""
    try:
        rows = read_jsonl("__system__", "meta/grounding-gaps.jsonl")
    except (FileNotFoundError, OSError):
        rows = []
    agg: dict = {}
    for r in rows:
        topic = r.get("topic") or "(unknown)"
        e = agg.setdefault(topic, {"topic": topic, "count": 0,
                                   "last_reason": None, "last_agent": None, "last_seen": None})
        e["count"] += 1
        e["last_reason"] = r.get("reason")
        e["last_agent"] = r.get("agent")
        e["last_seen"] = r.get("recorded_at")
    suggestions = sorted(agg.values(), key=lambda e: e["count"], reverse=True)
    return {"gaps": suggestions, "count": len(suggestions)}


API_ROUTES = [
    # Project lifecycle
    ("GET",  "/api/projects",                                list_engagements),
    ("POST", "/api/projects",                                create_engagement),
    ("POST", "/api/projects/{project_id}/archive",            archive_engagement),
    ("POST", "/api/projects/{project_id}/unarchive",          unarchive_engagement),
    ("DELETE","/api/projects/{project_id}",                   delete_engagement),
    ("PATCH","/api/projects/{project_id}",                    update_engagement),
    ("POST", "/api/projects/{source_project_id}/clone",       clone_engagement),
    # Dashboard data
    ("GET",  "/api/engagements/{engagement_id}/overview",     dashboard_overview),
    ("GET",  "/api/engagements/{engagement_id}/timeline",     dashboard_timeline),
    ("GET",  "/api/engagements/{engagement_id}/stats",        dashboard_stats),
    ("GET",  "/api/engagements/{engagement_id}/active-step",  dashboard_active_step),
    ("GET",  "/api/engagements/{engagement_id}/decisions",    list_decisions),
    ("GET",  "/api/engagements/{engagement_id}/findings",     list_findings),
    ("GET",  "/api/engagements/{engagement_id}/open-items",   list_open_items),
    ("POST", "/api/engagements/{engagement_id}/open-items/{item_id}/resolve", resolve_open_item),
    ("GET",  "/api/engagements/{engagement_id}/artifacts",    list_engagement_artifacts),
    ("GET",  "/api/engagements/{engagement_id}/artifacts/{name}", get_artifact),
    ("GET",  "/api/engagements/{engagement_id}/lifecycle",    get_engagement_lifecycle),
    # Design orchestrator (deterministic Design engine): the FE reads /design/state
    # to render progress and POSTs /design/advance after each scope to get the
    # next action (dispatch/await_user/retry_exhausted/blocked/complete).
    ("GET",  "/api/engagements/{engagement_id}/design/state",  design_state_view),
    ("POST", "/api/engagements/{engagement_id}/design/advance", design_advance),
    # Validation: deterministic PRECOMPUTED CHECKS injected into the kickoff so the
    # agent records mechanical-lens findings verbatim instead of re-deriving them.
    ("GET",  "/api/engagements/{engagement_id}/validation/kickoff", validation_kickoff_view),
    # Blueprint: design artifacts bundled inline + deterministic section outline.
    ("GET",  "/api/engagements/{engagement_id}/blueprint/kickoff", blueprint_kickoff_view),
    # Stream-drop recovery: rebuild the running scope's WORKER kickoff (map +
    # WORKER MODE) without mutating state, so a transient drop re-sends it.
    ("GET",  "/api/engagements/{engagement_id}/design/scope-kickoff", design_scope_kickoff),
    # Manual override — user-driven mark-done when an agent regressed and
    # didn't call set_step_status itself. Body: {"status": "DONE", "note": "…"}.
    ("POST", "/api/engagements/{engagement_id}/lifecycle/{step}/mark-done", mark_step_done),
    ("DELETE","/api/engagements/{engagement_id}/discovery",   reset_discovery),
    ("DELETE","/api/engagements/{engagement_id}/design",      reset_design),
    ("DELETE","/api/engagements/{engagement_id}/review",      reset_review),
    ("DELETE","/api/engagements/{engagement_id}/validation",  reset_validation),
    ("DELETE","/api/engagements/{engagement_id}/event-portal", reset_event_portal),
    ("DELETE","/api/engagements/{engagement_id}/blueprint",   reset_blueprint),
    # Intake
    ("POST", "/api/intake/preview",                           intake_preview),
    ("GET",  "/api/intake/download-yaml",                     intake_download_yaml),
    ("GET",  "/api/intake/download-markdown",                 intake_download_markdown),
    ("GET",  "/api/intake/autocomplete",                      intake_autocomplete),
    ("POST", "/api/intake/parse-yaml",                        intake_parse_yaml),
    ("POST", "/api/intake/parse-markdown",                    intake_parse_markdown),
    ("POST", "/api/intake/submit",                            intake_submit),
    ("GET",  "/api/intake/load/{engagement_id}",              intake_load),
    # Exports
    ("GET",  "/api/engagements/{engagement_id}/exports/availability", exports_availability),
    ("POST", "/api/engagements/{engagement_id}/exports/render", exports_render),
    ("GET",  "/api/engagements/{engagement_id}/exports/zip",  exports_zip),
    # Feedback
    ("POST", "/api/engagements/{engagement_id}/feedback",     submit_feedback),
    # Token telemetry (Decision 84)
    ("GET",  "/api/engagements/{engagement_id}/token-usage",  engagement_token_usage),
    ("GET",  "/api/me/token-usage",                           user_token_usage),
    # Admin: managed global grounding references (admin-only — 4th tuple element
    # is the admin-required flag enforced in component._adapt_api_handler).
    ("GET",    "/api/admin/grounding/refs",                   admin_grounding_list,       True),
    ("POST",   "/api/admin/grounding/refs",                   admin_grounding_add,        True),
    ("POST",   "/api/admin/grounding/refresh-all",            admin_grounding_refresh_all, True),
    ("GET",    "/api/admin/grounding/gaps",                   admin_grounding_gaps,       True),
    ("GET",    "/api/admin/grounding/platform",               admin_grounding_platform_list, True),
    ("GET",    "/api/admin/grounding/refs/{ref_id}",          admin_grounding_get,        True),
    ("POST",   "/api/admin/grounding/refs/{ref_id}/status",   admin_grounding_set_status, True),
    ("POST",   "/api/admin/grounding/refs/{ref_id}/edit",     admin_grounding_edit,       True),
    ("POST",   "/api/admin/grounding/refs/{ref_id}/refresh",  admin_grounding_refresh,    True),
    ("DELETE", "/api/admin/grounding/refs/{ref_id}",          admin_grounding_remove,     True),
]
