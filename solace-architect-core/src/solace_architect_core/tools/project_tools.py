"""Project (engagement) registry tools (v2spec §3.3).

Stored under the reserved ``__system__`` engagement so it survives across SAM sessions.
"""

from __future__ import annotations

import re
from typing import Optional

from .._storage import read_yaml, write_yaml
from .._user_context import get_current_user, scoped_user as _scoped_user
from ..schemas import ProjectEntry, _now
from .artifact_tools import ToolResult


_SYSTEM_ENGAGEMENT = "__system__"
_PROJECTS_ARTIFACT = "meta/projects.yaml"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return re.sub(r"-+", "-", s).strip("-") or "untitled"


def _current_owner() -> str:
    """Resolve owner from the current user. Anonymous users share the 'anonymous' bucket."""
    return get_current_user().get("id") or "anonymous"


async def list_projects(
    include_archived: bool = False, user_id: Optional[str] = None,
) -> ToolResult:
    """List projects owned by the current user.

    Anonymous users see the legacy global registry; authenticated users see only
    projects where ``owner`` matches their ID.

    ``user_id`` (optional) lets agent-side callers identify the authenticated
    user — lift it from the [Active engagement: ..., user_id=<uuid>] message
    header. Without it, owner falls back to the empty ContextVar and the
    listing returns the unfiltered global view, which is wrong for an agent
    running on behalf of a specific browser user.
    """
    with _scoped_user(user_id):
        data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
        owner = _current_owner()
    projects = data["projects"]
    if owner != "anonymous":
        projects = [p for p in projects if p.get("owner") == owner]
    if not include_archived:
        projects = [p for p in projects if p.get("status") != "archived"]
    return ToolResult(ok=True, data=projects)


async def create_project(*, name: str, owner: Optional[str] = None,
                          description: Optional[str] = None) -> ToolResult:
    """Create a project. owner defaults to the authenticated user (or 'anonymous')."""
    if owner is None:
        owner = _current_owner()

    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})

    base_id = _slug(name)
    project_id = base_id
    n = 2
    # Uniqueness scoped to this owner — different owners can share project names
    existing_ids = {p["id"] for p in data["projects"] if p.get("owner") == owner}
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


async def update_project_metadata(
    project_id: str, *, name: Optional[str] = None, description: Optional[str] = None,
) -> ToolResult:
    """Edit a project's mutable metadata. Owner enforced — non-admins can only edit their own.

    Only ``name`` and ``description`` are editable. The id, owner, status, and
    timestamps are managed by the system.
    """
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    owner = _current_owner()
    is_admin = bool(get_current_user().get("is_admin"))
    project = next((p for p in data["projects"] if p["id"] == project_id), None)
    if not project:
        return ToolResult(ok=False, error=f"project {project_id} not found")
    if owner != "anonymous" and project.get("owner") != owner and not is_admin:
        return ToolResult(ok=False, error="forbidden: project belongs to another user")

    if name is not None:
        if not name.strip():
            return ToolResult(ok=False, error="name cannot be empty")
        project["name"] = name.strip()
    if description is not None:
        project["description"] = description.strip() or None
    project["last_active_at"] = _now()
    write_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, data)
    return ToolResult(ok=True, data=project)


async def clone_project(
    source_project_id: str, *, new_name: Optional[str] = None,
) -> ToolResult:
    """Create a new project seeded from another's discovery brief.

    Use case: 'I want to revise inputs without losing the original audit trail.'
    Decisions/findings/provisioning state from the source are NOT copied — those
    belong to the source's history. Only the discovery brief carries over.

    Owner enforcement: clone target gets the current user as owner regardless
    of the source's owner. Reading the source requires read access (own project,
    or admin).
    """
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    owner = _current_owner()
    is_admin = bool(get_current_user().get("is_admin"))
    source = next((p for p in data["projects"] if p["id"] == source_project_id), None)
    if not source:
        return ToolResult(ok=False, error=f"source project {source_project_id} not found")
    if owner != "anonymous" and source.get("owner") != owner and not is_admin:
        return ToolResult(ok=False, error="forbidden: source project belongs to another user")

    # Read the source's discovery brief (under whichever user owns it).
    # Temporarily impersonate the source's owner to read across namespaces.
    from .._user_context import current_user as _cu, ANONYMOUS_USER
    source_owner_id = source.get("owner") or "anonymous"
    if source_owner_id != owner:
        ctx_token = _cu.set({**ANONYMOUS_USER, "id": source_owner_id, "is_admin": True})
        try:
            brief_text = _read_brief(source_project_id)
        finally:
            _cu.reset(ctx_token)
    else:
        brief_text = _read_brief(source_project_id)

    # Create the clone under the current user
    base = new_name or (source["name"] + " (copy)")
    new = await create_project(name=base, owner=owner,
                                description=f"Cloned from {source['name']}")
    if not new.ok:
        return new
    new_id = new.data["id"]

    # Seed the brief on the new project (under the current user's namespace)
    if brief_text:
        from .artifact_tools import write_artifact
        await write_artifact(new_id, "discovery/discovery-brief.yaml", brief_text)

    return ToolResult(ok=True, data={
        "source": source_project_id, "clone": new.data,
        "brief_seeded": bool(brief_text),
    })


def _read_brief(project_id: str) -> Optional[str]:
    try:
        from .._storage import read_text
        return read_text(project_id, "discovery/discovery-brief.yaml")
    except FileNotFoundError:
        return None


async def archive_project(project_id: str) -> ToolResult:
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    owner = _current_owner()
    project = next((p for p in data["projects"] if p["id"] == project_id), None)
    if not project:
        return ToolResult(ok=False, error=f"project {project_id} not found")
    if owner != "anonymous" and project.get("owner") != owner and not get_current_user().get("is_admin"):
        return ToolResult(ok=False, error="forbidden: project belongs to another user")
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
