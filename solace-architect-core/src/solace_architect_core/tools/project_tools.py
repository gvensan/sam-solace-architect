"""Project (engagement) registry tools (v2spec §3.3).

Stored under the reserved ``__system__`` engagement so it survives across SAM sessions.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .._storage import read_yaml, safe_read_yaml, write_yaml
from .._user_context import (
    get_current_user,
    resolve_user_id as _resolve_user_id,
    scoped_user as _scoped_user,
)
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
    tool_context: Any = None,
) -> ToolResult:
    """List projects owned by the current user.

    Anonymous users see the legacy global registry; authenticated users see only
    projects where ``owner`` matches their ID. ``user_id`` auto-resolves from
    ``tool_context`` when not passed explicitly.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        # safe_read_yaml: read-only, hit by the projects sidebar in the
        # dashboard. A corrupt registry should show an empty list (+ log)
        # rather than 500-ing — every project create/update/archive flow
        # still uses raising read_yaml below to avoid silent overwrite.
        data = safe_read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
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
    """Create a new project seeded from another's discovery brief + intake.

    Use case: 'I want to revise inputs without losing the original audit trail,
    or fill in fields a newer intake form added.' We copy the three discovery
    inputs (brief.yaml, intake.json, intake.md). Decisions / findings / phase
    outputs from the source are NOT copied — those belong to the source's
    history. The clone is intended to be opened in the intake editor next so
    the user can fill gaps before re-running Discovery.

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

    # Read the source's discovery inputs (under whichever user owns it).
    # Temporarily impersonate the source's owner to read across namespaces.
    from .._user_context import current_user as _cu, ANONYMOUS_USER
    source_owner_id = source.get("owner") or "anonymous"
    if source_owner_id != owner:
        ctx_token = _cu.set({**ANONYMOUS_USER, "id": source_owner_id, "is_admin": True})
        try:
            brief_text = _read_artifact(source_project_id, "discovery/discovery-brief.yaml")
            intake_json = _read_artifact(source_project_id, "discovery/intake.json")
            intake_md = _read_artifact(source_project_id, "discovery/intake.md")
        finally:
            _cu.reset(ctx_token)
    else:
        brief_text = _read_artifact(source_project_id, "discovery/discovery-brief.yaml")
        intake_json = _read_artifact(source_project_id, "discovery/intake.json")
        intake_md = _read_artifact(source_project_id, "discovery/intake.md")

    # Create the clone under the current user
    base = new_name or (source["name"] + " (copy)")
    new = await create_project(name=base, owner=owner,
                                description=f"Cloned from {source['name']}")
    if not new.ok:
        return new
    new_id = new.data["id"]

    # Seed discovery inputs on the new project (under the current user's namespace).
    # All three are best-effort; the intake editor only strictly needs intake.json
    # to re-hydrate, but copying all three keeps downstream tools' assumptions intact.
    #
    # Bug fix (2026-05-22): the source's discovery inputs carry the SOURCE name in
    # project.name. If we copy them verbatim, the intake editor re-hydrates the
    # source's name into the form; submitting then renames the clone back via
    # update_project_metadata in intake_submit, stripping the " (copy)" suffix
    # the user typed in the Clone dialog. Rewrite the embedded project.name in
    # both intake.json and intake.md (and the discovery brief) so the clone's
    # name is consistent everywhere.
    intake_json = _rewrite_project_name_in_intake_json(intake_json, base)
    intake_md = _rewrite_project_name_in_intake_md(intake_md, base)
    brief_text = _rewrite_project_name_in_brief(brief_text, base)

    from .artifact_tools import write_artifact
    if brief_text:
        await write_artifact(new_id, "discovery/discovery-brief.yaml", brief_text)
    if intake_json:
        await write_artifact(new_id, "discovery/intake.json", intake_json)
    if intake_md:
        await write_artifact(new_id, "discovery/intake.md", intake_md)

    return ToolResult(ok=True, data={
        "source": source_project_id, "clone": new.data,
        "brief_seeded": bool(brief_text),
        "intake_seeded": bool(intake_json),
    })


def _rewrite_project_name_in_intake_json(text: Optional[str], new_name: str) -> Optional[str]:
    """Best-effort overwrite of project.name (V1 nested) or project_name (V2 flat)
    in the cloned intake.json. Returns the original text on parse failure.
    """
    if not text:
        return text
    import json
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(obj, dict):
        if isinstance(obj.get("project"), dict):
            obj["project"]["name"] = new_name
        # Flat (V2) shape uses top-level project_name; both shapes are accepted by
        # the form's loadData() so cover both rather than guessing which is present.
        if "project_name" in obj:
            obj["project_name"] = new_name
    try:
        return json.dumps(obj, indent=2, sort_keys=False)
    except (TypeError, ValueError):
        return text


def _rewrite_project_name_in_brief(text: Optional[str], new_name: str) -> Optional[str]:
    """Overwrite project_name in the discovery brief YAML (V2 flat shape)."""
    if not text:
        return text
    import yaml
    try:
        obj = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return text
    if isinstance(obj, dict) and "project_name" in obj:
        obj["project_name"] = new_name
        try:
            return yaml.safe_dump(obj, default_flow_style=False, sort_keys=False)
        except yaml.YAMLError:
            return text
    return text


def _rewrite_project_name_in_intake_md(text: Optional[str], new_name: str) -> Optional[str]:
    """Patch the "**Project name:** <old>" line in the cloned intake.md.

    The Markdown is authored by ``_intake_to_markdown`` with a stable format, so
    a targeted line-rewrite is safe. If the marker isn't found (older format /
    user-edited file), return the original text.
    """
    if not text:
        return text
    import re as _re
    pattern = _re.compile(r"^(\*\*Project name:\*\*)\s*.*$", _re.MULTILINE)
    new_text, count = pattern.subn(rf"\1 {new_name}", text, count=1)
    return new_text if count else text


def _read_artifact(project_id: str, name: str) -> Optional[str]:
    try:
        from .._storage import read_text
        return read_text(project_id, name)
    except FileNotFoundError:
        return None


# Kept under the old name for any external callers that imported it; new
# code should use _read_artifact() with an explicit name.
def _read_brief(project_id: str) -> Optional[str]:
    return _read_artifact(project_id, "discovery/discovery-brief.yaml")


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


async def unarchive_project(project_id: str) -> ToolResult:
    """Restore an archived project to active status.

    Mirror of ``archive_project``: same owner check, opposite status flip.
    No mid-flight guard needed — an archived project has no steps in flight.
    """
    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    owner = _current_owner()
    project = next((p for p in data["projects"] if p["id"] == project_id), None)
    if not project:
        return ToolResult(ok=False, error=f"project {project_id} not found")
    if owner != "anonymous" and project.get("owner") != owner and not get_current_user().get("is_admin"):
        return ToolResult(ok=False, error="forbidden: project belongs to another user")
    project["status"] = "active"
    project["last_active_at"] = _now()
    write_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, data)
    return ToolResult(ok=True, data=project)


async def delete_project(project_id: str) -> ToolResult:
    """Permanently delete a project: remove its registry entry AND wipe its
    on-disk engagement directory (artifacts, meta, telemetry — everything).

    Irreversible. The frontend gates this behind a type-to-confirm dialog;
    the lifecycle/api adapter additionally refuses mid-flight projects.

    Owner enforcement: only the owner (or an admin) can delete. The active-
    project marker is cleared if the deleted project was active.
    """
    import shutil
    from .._storage import _engagement_root

    data = read_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, default={"projects": []})
    owner = _current_owner()
    project = next((p for p in data["projects"] if p["id"] == project_id), None)
    if not project:
        return ToolResult(ok=False, error=f"project {project_id} not found")
    if owner != "anonymous" and project.get("owner") != owner and not get_current_user().get("is_admin"):
        return ToolResult(ok=False, error="forbidden: project belongs to another user")

    # Wipe the engagement directory under the owner's namespace. We resolve
    # against the OWNER's namespace, not the caller's — an admin deleting
    # another user's project still needs to hit the right directory.
    from .._user_context import current_user as _cu, ANONYMOUS_USER
    owner_id = project.get("owner") or "anonymous"
    if owner_id != owner:
        ctx_token = _cu.set({**ANONYMOUS_USER, "id": owner_id, "is_admin": True})
        try:
            eng_root = _engagement_root(project_id)
        finally:
            _cu.reset(ctx_token)
    else:
        eng_root = _engagement_root(project_id)

    artifacts_removed = False
    try:
        if eng_root.exists():
            shutil.rmtree(eng_root)
            artifacts_removed = True
    except Exception as exc:
        # Registry drop is the source-of-truth: even if filesystem cleanup
        # fails, dropping the entry hides the project from every list. We
        # surface the error so the caller (and ops) know cleanup was partial.
        import logging as _logging
        _logging.getLogger(__name__).exception(
            "delete_project: filesystem cleanup failed for %s at %s: %s",
            project_id, eng_root, exc,
        )

    # Drop from registry
    data["projects"] = [p for p in data["projects"] if p["id"] != project_id]
    write_yaml(_SYSTEM_ENGAGEMENT, _PROJECTS_ARTIFACT, data)

    # Clear active-project marker if it pointed at the just-deleted project.
    if _ACTIVE_PROJECT.get("id") == project_id:
        _ACTIVE_PROJECT["id"] = ""

    return ToolResult(ok=True, data={
        "id": project_id,
        "artifacts_removed": artifacts_removed,
    })


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
