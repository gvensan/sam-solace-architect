"""Project (engagement) registry tools (v2spec §3.3).

Stored under the reserved ``__system__`` engagement so it survives across SAM sessions.
"""

from __future__ import annotations

import re
from typing import Optional

from .._storage import read_yaml, write_yaml
from ..schemas import ProjectEntry, _now
from .artifact_tools import ToolResult


_SYSTEM_ENGAGEMENT = "__system__"
_PROJECTS_ARTIFACT = "meta/projects.yaml"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return re.sub(r"-+", "-", s).strip("-") or "untitled"


async def list_projects(include_archived: bool = False) -> ToolResult:
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    projects = data["projects"]
    if not include_archived:
        projects = [p for p in projects if p.get("status") != "archived"]
    return ToolResult(ok=True, data=projects)


async def create_project(*, name: str, owner: str = "anonymous", description: Optional[str] = None) -> ToolResult:
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})

    base_id = _slug(name)
    project_id = base_id
    n = 2
    existing_ids = {p["id"] for p in data["projects"]}
    while project_id in existing_ids:
        project_id = f"{base_id}-{n}"
        n += 1

    entry = ProjectEntry(id=project_id, name=name, owner=owner, description=description)
    data["projects"].append(entry.to_dict())
    write_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, data)

    # Initialize per-engagement metadata artifacts
    write_yaml(project_id, "meta/decisions.yaml", {"decisions": []})
    write_yaml(project_id, "meta/findings.yaml", {"findings": []})
    write_yaml(project_id, "meta/open-items.yaml", {"open_items": []})
    write_yaml(project_id, "meta/feedback.yaml", {"feedback": []})

    return ToolResult(ok=True, data=entry.to_dict())


async def archive_project(project_id: str) -> ToolResult:
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    project = next((p for p in data["projects"] if p["id"] == project_id), None)
    if not project:
        return ToolResult(ok=False, error=f"project {project_id} not found")
    project["status"] = "archived"
    project["last_active_at"] = _now()
    write_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, data)
    return ToolResult(ok=True, data=project)


# In-memory active-project marker (Phase 2+: SAM session-state-backed)
_ACTIVE_PROJECT: dict[str, str] = {"id": ""}


async def switch_active_project(project_id: str) -> ToolResult:
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    project = next((p for p in data["projects"] if p["id"] == project_id), None)
    if not project:
        return ToolResult(ok=False, error=f"project {project_id} not found")
    project["last_active_at"] = _now()
    write_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, data)
    _ACTIVE_PROJECT["id"] = project_id
    return ToolResult(ok=True, data=project)


def get_active_project_id() -> str:
    """Return the currently-active engagement_id (or empty string)."""
    return _ACTIVE_PROJECT["id"]
