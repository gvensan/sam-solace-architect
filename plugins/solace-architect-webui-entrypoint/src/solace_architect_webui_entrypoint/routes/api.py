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
    telemetry_tools, lifecycle_tools,
)
from solace_architect_core._storage import (
    read_jsonl, read_yaml, safe_artifact_path, write_text, write_yaml,
)


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

async def list_engagements(include_archived: bool = False) -> Any:
    return (await project_tools.list_projects(include_archived=include_archived)).data


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


# Folders SADomainAgent writes into. The CURRENT layout is a single top-level
# ``design/`` directory whose files are named per scope (design/topic-taxonomy.yaml,
# design/broker-recommendation.yaml, design/integration/integration-map.yaml,
# etc.). The LEGACY layout used a top-level folder per scope (topic-design/...,
# broker-select/..., integration/...). Both are listed so that engagements
# created at any point in the project's history get fully wiped on Restart.
# _unlink_category() is recursive (rglob) so subdirectories under design/ are
# also cleaned. Empty legacy folders are no-ops; missing folders are no-ops.
_DESIGN_FOLDERS = (
    "design",                  # current single-folder layout (rglob handles subdirs)
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

    # Clear the design step status + telemetry. (Domain-sourced open-items
    # are superseded inside _reset_downstream's cascade below — keeping the
    # logic in one place.)
    await lifecycle_tools.clear_step_status(engagement_id, "design")
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

    # Unlink reviews/*.md narrative artifacts.
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
        await _clear_step_telemetry(engagement_id, "event-portal")

    if "blueprint" in to_wipe:
        removed.extend(await _unlink_category(engagement_id, "blueprint"))
        removed.extend(await _unlink_category(engagement_id, "exports"))
        await lifecycle_tools.clear_step_status(engagement_id, "blueprint")
        await _clear_step_telemetry(engagement_id, "blueprint")

    return {
        "cascaded_steps": list(to_wipe),
        "cascaded_artifacts": removed,
        "cascaded_findings_cleared": findings_cleared,
        "cascaded_open_items_superseded": superseded,
        "cascaded_decisions_cleared": decisions_cleared,
        "cascaded_telemetry_rows_cleared": telemetry_rows_cleared,
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
    # opt-in phase today is Event Portal provisioning.
    prefs = flat.get("preferences") or {}
    if not prefs.get("provision_event_portal"):
        await lifecycle_tools.set_step_status(
            eid, step="event-portal", status="SKIPPED",
            agent="WebUI-intake",
            note="Opt-out at intake (preferences.provision_event_portal=false).",
        )

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
    lines.append(f"**Schemas:** {landscape.get('schemas') or ''}")
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


# Route table — consumed by lifecycle.py to register with the SAM HTTP runtime.
API_ROUTES = [
    # Project lifecycle
    ("GET",  "/api/projects",                                list_engagements),
    ("POST", "/api/projects",                                create_engagement),
    ("POST", "/api/projects/{project_id}/archive",            archive_engagement),
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
]
