"""Decisions, findings, open-items, feedback tools (v2spec §3.2)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from .._storage import next_id, read_yaml, write_yaml
from ..schemas import (
    DecisionEntry,
    FindingEntry,
    FeedbackEntry,
    OpenItemEntry,
)
from .artifact_tools import ToolResult


# ---------- Decisions ----------

async def record_decision(
    engagement_id: str, *, context: str, recommendation: str, selected: str,
    rationale: str, source_agent: str,
) -> ToolResult:
    """Append a D-numbered decision to meta/decisions.yaml."""
    data = read_yaml(engagement_id, "meta/decisions.yaml", default={"decisions": []})
    existing_ids = [d["id"] for d in data["decisions"]]
    entry = DecisionEntry(
        id=next_id(existing_ids, "D"),
        context=context, recommendation=recommendation,
        selected=selected, rationale=rationale, source_agent=source_agent,
    )
    data["decisions"].append(entry.to_dict())
    write_yaml(engagement_id, "meta/decisions.yaml", data)
    return ToolResult(ok=True, data=entry.to_dict())


async def read_decisions(engagement_id: str) -> ToolResult:
    data = read_yaml(engagement_id, "meta/decisions.yaml", default={"decisions": []})
    return ToolResult(ok=True, data=data["decisions"])


# ---------- Findings ----------

async def record_finding(
    engagement_id: str, *, severity: str, description: str,
    affected_artifact: str, recommendation: str, source_agent: str,
) -> ToolResult:
    data = read_yaml(engagement_id, "meta/findings.yaml", default={"findings": []})
    existing_ids = [f["id"] for f in data["findings"]]
    entry = FindingEntry(
        id=next_id(existing_ids, "F"),
        severity=severity, description=description,
        affected_artifact=affected_artifact, recommendation=recommendation,
        source_agent=source_agent,
    )
    data["findings"].append(entry.to_dict())
    write_yaml(engagement_id, "meta/findings.yaml", data)
    return ToolResult(ok=True, data=entry.to_dict())


async def read_findings(engagement_id: str, status: Optional[str] = None) -> ToolResult:
    data = read_yaml(engagement_id, "meta/findings.yaml", default={"findings": []})
    findings = data["findings"]
    if status:
        findings = [f for f in findings if f.get("status") == status]
    return ToolResult(ok=True, data=findings)


async def update_finding_status(
    engagement_id: str, *, finding_id: str, new_status: str,
    resolution_note: Optional[str] = None, source_agent: str = "",
) -> ToolResult:
    """Update finding status. On 'deferred', also creates a corresponding open-item."""
    data = read_yaml(engagement_id, "meta/findings.yaml", default={"findings": []})
    finding = next((f for f in data["findings"] if f["id"] == finding_id), None)
    if not finding:
        return ToolResult(ok=False, error=f"finding {finding_id} not found")

    finding["status"] = new_status
    if resolution_note:
        finding["resolution_note"] = resolution_note
    write_yaml(engagement_id, "meta/findings.yaml", data)

    open_item = None
    if new_status == "deferred":
        # Mirror finding severity into open-item severity:
        # critical → blocking; everything else → advisory.
        open_severity = "blocking" if finding["severity"] == "critical" else "advisory"
        result = await record_open_item(
            engagement_id,
            severity=open_severity,
            source="review-deferred",
            description=f"Deferred finding {finding_id}: {finding['description']}",
            affected_artifact=finding.get("affected_artifact"),
            source_agent=source_agent or finding.get("source_agent", ""),
        )
        open_item = result.data

    return ToolResult(ok=True, data={"finding": finding, "open_item": open_item})


# ---------- Open items ----------

async def record_open_item(
    engagement_id: str, *, severity: str, source: str, description: str,
    affecting_step: Optional[str] = None, affected_artifact: Optional[str] = None,
    source_agent: str = "",
) -> ToolResult:
    data = read_yaml(engagement_id, "meta/open-items.yaml", default={"open_items": []})
    existing_ids = [q["id"] for q in data["open_items"]]
    entry = OpenItemEntry(
        id=next_id(existing_ids, "Q"),
        severity=severity, source=source, description=description,
        affecting_step=affecting_step, affected_artifact=affected_artifact,
        source_agent=source_agent,
    )
    data["open_items"].append(entry.to_dict())
    write_yaml(engagement_id, "meta/open-items.yaml", data)
    return ToolResult(ok=True, data=entry.to_dict())


async def read_open_items(
    engagement_id: str, status: Optional[str] = None,
    severity: Optional[str] = None, source: Optional[str] = None,
) -> ToolResult:
    data = read_yaml(engagement_id, "meta/open-items.yaml", default={"open_items": []})
    items = data["open_items"]
    if status:
        items = [q for q in items if q.get("status") == status]
    if severity:
        items = [q for q in items if q.get("severity") == severity]
    if source:
        items = [q for q in items if q.get("source") == source]
    return ToolResult(ok=True, data=items)


async def update_open_item_status(
    engagement_id: str, *, item_id: str, new_status: str,
    resolution_note: Optional[str] = None,
) -> ToolResult:
    data = read_yaml(engagement_id, "meta/open-items.yaml", default={"open_items": []})
    item = next((q for q in data["open_items"] if q["id"] == item_id), None)
    if not item:
        return ToolResult(ok=False, error=f"open item {item_id} not found")
    item["status"] = new_status
    if resolution_note:
        item["resolution_note"] = resolution_note
    write_yaml(engagement_id, "meta/open-items.yaml", data)
    return ToolResult(ok=True, data=item)


# ---------- Feedback ----------

async def record_feedback(
    engagement_id: str, *, scope: str, rating: int, category: str, note: str,
    recorded_by: str = "anonymous",
) -> ToolResult:
    if not 1 <= rating <= 5:
        return ToolResult(ok=False, error="rating must be 1-5")
    data = read_yaml(engagement_id, "meta/feedback.yaml", default={"feedback": []})
    existing_ids = [fb["id"] for fb in data["feedback"]]
    entry = FeedbackEntry(
        id=next_id(existing_ids, "FB"),
        scope=scope, rating=rating, category=category, note=note,
        recorded_by=recorded_by,
    )
    data["feedback"].append(entry.to_dict())
    write_yaml(engagement_id, "meta/feedback.yaml", data)
    return ToolResult(ok=True, data=entry.to_dict())


async def read_feedback(engagement_id: str, scope: Optional[str] = None) -> ToolResult:
    data = read_yaml(engagement_id, "meta/feedback.yaml", default={"feedback": []})
    items = data["feedback"]
    if scope:
        items = [fb for fb in items if fb.get("scope") == scope]
    return ToolResult(ok=True, data=items)
