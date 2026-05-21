"""Telemetry tools — per-engagement LLM token usage capture and query (Decision 84).

Two-tier persistence story for tracking what each agent spent in tokens, on which
engagement, on which day. Both tiers respect the per-user storage isolation from
Decision 79: artifacts land under ``users/<user_id>/<engagement_id>/...`` when
authenticated, unscoped otherwise.

Tier 2 (this module): append-only JSONL ledger at
``meta/telemetry/llm-calls.jsonl`` — one row per LLM round-trip with engagement,
agent, step, model, and token counts. Tier 1 (per-step aggregates rolled into
``meta/timeline.yaml``) is deferred until the workflow stepping is in place.

The ``record_token_usage`` writer is normally invoked from each agent's
``after_model_callback`` (see ``solace_architect_core.agent_callbacks``); the
``read_token_usage`` reader powers the dashboard's Telemetry view and CLI
inspection.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from .._storage import append_jsonl, read_jsonl
from .._user_context import scoped_user as _scoped_user
from .artifact_tools import ToolResult


LEDGER_PATH = "meta/telemetry/llm-calls.jsonl"

GroupBy = Literal["agent", "step", "model", "day"]
UserGroupBy = Literal["agent", "step", "model", "day", "project"]


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def record_token_usage(
    engagement_id: str,
    *,
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    step_id: Optional[str] = None,
    sam_task_id: Optional[str] = None,
    source: str = "agent",
    ts: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ToolResult:
    """Append one LLM round-trip's token bill to the engagement's telemetry ledger.

    Designed to be called from a SAM ``after_model_callback`` — every LLM
    response produces one row. Counts are recorded as-is; aggregation happens at
    read time.

    Args:
        engagement_id: Engagement this call belongs to.
        agent: Agent class name (e.g. ``"SADiscoveryAgent"``).
        model: Model identifier from the LLM response (e.g. ``"claude-sonnet-4-6"``).
        input_tokens: Prompt token count.
        output_tokens: Completion token count.
        cached_input_tokens: Prompt-cache hits (free or discounted by the
            provider; tracked separately so reporting can show effective spend).
        step_id: Workflow step identifier when known (orchestrator-routed
            invocations); ``None`` for ad-hoc agent turns.
        sam_task_id: SAM A2A task ID for cross-reference with SAM's own task
            logger.
        source: Where the LLM call originated within the agent process (e.g.
            ``"agent"`` for the main body, ``"tool"`` for a tool-delegated call).
            Mirrors SAM's ``token_usage_by_source`` split.
        ts: Override timestamp (ISO 8601 UTC). Defaults to now.
        user_id: When provided, the ledger is written under
            ``users/<user_id>/<engagement_id>/...`` to match the per-user
            storage isolation every other write path uses. Without it
            (or with ``"anonymous"``) the write falls back to the legacy
            unscoped layout — necessary for tests and CLI but in the
            running WebUI it would hide the data from the dashboard.
    """
    row = {
        "ts": ts or _utc_now_iso(),
        "engagement_id": engagement_id,
        "agent": agent,
        "step_id": step_id,
        "sam_task_id": sam_task_id,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cached_input_tokens": int(cached_input_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
        "source": source,
    }
    try:
        with _scoped_user(user_id):
            append_jsonl(engagement_id, LEDGER_PATH, row)
        return ToolResult(ok=True, data=row)
    except (OSError, ValueError) as e:
        return ToolResult(ok=False, error=f"could not append telemetry: {e}")


def _row_in_range(row: dict, since: Optional[datetime], until: Optional[datetime]) -> bool:
    if since is None and until is None:
        return True
    ts = row.get("ts")
    if not isinstance(ts, str):
        return False
    try:
        # Accept both 'Z' suffix and explicit offsets.
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    if since is not None and dt < since:
        return False
    if until is not None and dt >= until:
        return False
    return True


def _group_key(row: dict, group_by: str) -> str:
    if group_by == "day":
        ts = row.get("ts", "")
        return ts[:10] if isinstance(ts, str) else "<unknown>"
    if group_by == "step":
        val = row.get("step_id")
    elif group_by == "project":
        val = row.get("_project_id") or row.get("engagement_id")
    else:
        val = row.get(group_by)
    if val is None or val == "":
        return f"<no-{group_by}>"
    return str(val)


def _aggregate(rows: list[dict], group_by: str,
               since: Optional[datetime], until: Optional[datetime],
               extra_labels: Optional[dict[str, str]] = None) -> tuple[list[dict], dict]:
    """Filter ``rows`` by date range and aggregate by ``group_by``.

    ``extra_labels`` lets callers attach a human-readable name to a group key
    (e.g. project_id → project name); merged into each output row as
    ``label``.
    """
    extra_labels = extra_labels or {}
    filtered = [r for r in rows if _row_in_range(r, since, until)]

    agg: dict[str, dict[str, int]] = defaultdict(lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cached_input_tokens": 0, "total_tokens": 0, "calls": 0,
    })
    totals = {
        "input_tokens": 0, "output_tokens": 0,
        "cached_input_tokens": 0, "total_tokens": 0, "calls": 0,
    }
    for r in filtered:
        key = _group_key(r, group_by)
        bucket = agg[key]
        for field in ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens"):
            val = int(r.get(field, 0) or 0)
            bucket[field] += val
            totals[field] += val
        bucket["calls"] += 1
        totals["calls"] += 1

    out_rows: list[dict[str, Any]] = []
    for k, v in agg.items():
        row = {"key": k, **v}
        if k in extra_labels:
            row["label"] = extra_labels[k]
        out_rows.append(row)
    out_rows.sort(key=lambda x: x["total_tokens"], reverse=True)
    return out_rows, totals


async def read_token_usage(
    engagement_id: str,
    *,
    group_by: GroupBy = "agent",
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> ToolResult:
    """Read + aggregate the engagement's telemetry ledger.

    Returns ``data`` shape::

        {
          "rows": [{"key": "...", "input_tokens": N, "output_tokens": N,
                    "cached_input_tokens": N, "total_tokens": N, "calls": N}, ...],
          "totals": {"input_tokens": N, "output_tokens": N,
                     "cached_input_tokens": N, "total_tokens": N, "calls": N},
          "group_by": "...",
          "engagement_id": "...",
          "row_count_raw": N
        }

    Args:
        engagement_id: Engagement to query.
        group_by: One of ``agent``, ``step``, ``model``, ``day``.
        since: Inclusive lower bound on timestamp; ``None`` for unbounded.
        until: Exclusive upper bound; ``None`` for unbounded.
    """
    raw = read_jsonl(engagement_id, LEDGER_PATH)
    rows, totals = _aggregate(raw, group_by, since, until)
    return ToolResult(ok=True, data={
        "rows": rows,
        "totals": totals,
        "group_by": group_by,
        "engagement_id": engagement_id,
        "row_count_raw": sum(r["calls"] for r in rows),
    })


async def read_user_token_usage(
    *,
    group_by: UserGroupBy = "project",
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> ToolResult:
    """Aggregate token usage across all projects owned by the current user.

    Uses the per-user storage isolation (Decision 79) — ``list_projects`` and
    ``read_jsonl`` both already route through the ``current_user`` contextvar,
    so this function automatically scopes to the caller. Anonymous users see
    the legacy global registry.

    The ``project`` ``group_by`` keys are engagement IDs; each output row
    carries a ``label`` field with the project's human-readable name.
    """
    from .project_tools import list_projects

    projects_result = await list_projects(include_archived=True)
    if not projects_result.ok:
        return ToolResult(ok=False, error=f"could not list projects: {projects_result.error}")

    projects = projects_result.data or []
    project_labels: dict[str, str] = {}
    combined: list[dict] = []
    for p in projects:
        pid = p.get("id")
        if not pid:
            continue
        project_labels[pid] = p.get("name") or pid
        ledger = read_jsonl(pid, LEDGER_PATH)
        for row in ledger:
            row = dict(row)
            row["_project_id"] = pid
            combined.append(row)

    rows, totals = _aggregate(
        combined, group_by, since, until,
        extra_labels=project_labels if group_by == "project" else None,
    )
    return ToolResult(ok=True, data={
        "rows": rows,
        "totals": totals,
        "group_by": group_by,
        "row_count_raw": sum(r["calls"] for r in rows),
        "project_count": len(projects),
    })
