"""Artifact tools (v2spec §3.1).

Phase 1 implementation against the local file-based store (see ``_storage.py``).
The same interface will be re-implemented against SAM's ArtifactService.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .._storage import (
    list_artifacts as _list_artifacts,
    read_text as _read_text,
    safe_artifact_path,
    write_text as _write_text,
)
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user


# Forbidden terms (v2spec §3.1 forbidden-term list, normalized to lowercase)
_FORBIDDEN_TERMS = [
    ("connector", "use 'Micro-Integration'"),
    ("qos", "use 'Direct messaging' or 'Guaranteed messaging'"),
    ("orchestrator agent", "use 'SAOrchestratorAgent'"),
]


@dataclass
class ValidationResult:
    """Result of a single pre-write check."""
    ok: bool
    violations: list[dict]  # [{line, found, suggested}, ...]
    error: str | None = None


@dataclass
class ToolResult:
    """Standardized tool return shape."""
    ok: bool
    data: Any = None
    error: str | None = None
    error_detail: dict | None = None  # structured violation lists per check (write_artifact)


# ---------- read_artifact ----------

async def read_artifact(engagement_id: str, artifact_name: str,
                        user_id: str | None = None,
                        tool_context: Any = None) -> ToolResult:
    """Read an artifact via the storage layer.

    ``user_id`` may be passed explicitly; otherwise it is auto-resolved from
    ``tool_context.state["a2a_context"]["user_id"]`` (SAM excludes
    ``tool_context`` from the LLM-visible schema and injects it). See
    ``_user_context.resolve_user_id``.

    Returns ToolResult(ok=True, data=content) or ToolResult(ok=False, error=...).
    """
    try:
        with _scoped_user(_resolve_user_id(user_id, tool_context)):
            content = _read_text(engagement_id, artifact_name)
        return ToolResult(ok=True, data=content)
    except FileNotFoundError:
        return ToolResult(ok=False, error=f"artifact not found: {artifact_name}")
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))


# ---------- write_artifact ----------

def _check_terminology(content: str) -> ValidationResult:
    violations = []
    lower = content.lower()
    for term, suggestion in _FORBIDDEN_TERMS:
        idx = lower.find(term)
        while idx >= 0:
            line_no = content[:idx].count("\n") + 1
            violations.append({"line": line_no, "found": term, "suggested": suggestion})
            idx = lower.find(term, idx + 1)
    return ValidationResult(ok=not violations, violations=violations)


def _check_path(engagement_id: str, artifact_name: str) -> ValidationResult:
    try:
        safe_artifact_path(engagement_id, artifact_name)
        return ValidationResult(ok=True, violations=[])
    except ValueError as e:
        return ValidationResult(ok=False, violations=[], error=str(e))


def _check_naming(content: str) -> ValidationResult:
    """Phase 1: trivial; Phase 2+ scans for naming-convention violations."""
    return ValidationResult(ok=True, violations=[])


def _check_grounding(content: str) -> ValidationResult:
    """Phase 1: trivial; Phase 2+ scans for ungrounded Solace capability claims."""
    return ValidationResult(ok=True, violations=[])


async def write_artifact(engagement_id: str, artifact_name: str, content: str,
                         user_id: str | None = None,
                         tool_context: Any = None) -> ToolResult:
    """Write an artifact with structured pre-write validation (v2spec §3.1).

    ``user_id`` auto-resolves from ``tool_context`` when not passed explicitly.

    On failure, ``error_detail`` carries per-check violation lists so the agent can
    surface them as actionable items rather than a flat error string.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        path_check = _check_path(engagement_id, artifact_name)
        if not path_check.ok:
            return ToolResult(ok=False, error=path_check.error or "invalid artifact path",
                              error_detail={"path_check": {"ok": False, "error": path_check.error}})

        terminology_check = _check_terminology(content)
        naming_check = _check_naming(content)
        grounding_check = _check_grounding(content)

        if not (terminology_check.ok and naming_check.ok and grounding_check.ok):
            return ToolResult(
                ok=False,
                error="pre-write validation failed",
                error_detail={
                    "path_check": {"ok": True, "error": None},
                    "terminology_check": {"ok": terminology_check.ok, "violations": terminology_check.violations},
                    "naming_check": {"ok": naming_check.ok, "violations": naming_check.violations},
                    "grounding_check": {"ok": grounding_check.ok, "violations": grounding_check.violations},
                },
            )

        _write_text(engagement_id, artifact_name, content)
    return ToolResult(ok=True, data={"artifact_name": artifact_name, "bytes": len(content)})


# ---------- list_artifacts ----------

async def list_artifacts(engagement_id: str, category: str | None = None,
                         user_id: str | None = None,
                         tool_context: Any = None) -> ToolResult:
    """List artifacts under ``category`` or all artifacts for the engagement.

    ``user_id`` auto-resolves from ``tool_context`` when not passed explicitly.
    """
    try:
        with _scoped_user(_resolve_user_id(user_id, tool_context)):
            names = _list_artifacts(engagement_id, category=category)
        return ToolResult(ok=True, data=names)
    except Exception as e:  # pragma: no cover
        return ToolResult(ok=False, error=str(e))
