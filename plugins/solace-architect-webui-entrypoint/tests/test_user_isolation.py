"""Per-user storage isolation (Phase B).

Two authenticated users must not see each other's projects. Storage is
namespaced under ``users/<user_id>/<engagement_id>/...`` whenever a non-
anonymous user is on the ContextVar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from solace_architect_core._user_context import current_user, ANONYMOUS_USER
from solace_architect_core.tools import project_tools


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


def _as_user(user_id: str, username: str):
    """Push a user onto the ContextVar; return the token so the caller can reset."""
    return current_user.set({"id": user_id, "username": username, "is_admin": False})


@pytest.mark.asyncio
async def test_two_users_cannot_see_each_others_projects():
    # User A creates one project
    token_a = _as_user("user-a", "alice")
    try:
        a = (await project_tools.create_project(name="alice's project")).data
        assert a.get("id"), "user A should have received an engagement id"
        a_list = (await project_tools.list_projects()).data
        assert any(p["id"] == a["id"] for p in a_list)
    finally:
        current_user.reset(token_a)

    # User B creates one project, sees only their own
    token_b = _as_user("user-b", "bob")
    try:
        b = (await project_tools.create_project(name="bob's project")).data
        assert b.get("id"), "user B should have received an engagement id"
        b_list = (await project_tools.list_projects()).data
        ids = {p["id"] for p in b_list}
        assert b["id"] in ids,           "user B must see their own project"
        assert a["id"] not in ids,       "user B must NOT see user A's project"
    finally:
        current_user.reset(token_b)

    # User A still sees only their own
    token_a2 = _as_user("user-a", "alice")
    try:
        a_list2 = (await project_tools.list_projects()).data
        ids = {p["id"] for p in a_list2}
        assert a["id"] in ids
        assert b["id"] not in ids
    finally:
        current_user.reset(token_a2)


@pytest.mark.asyncio
async def test_anonymous_namespace_is_separate_from_authenticated(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts2"))

    # Anonymous user — falls in shared/global namespace per _storage._user_namespace
    anon_proj = (await project_tools.create_project(name="anon-test", owner="anonymous")).data
    assert anon_proj.get("id")

    # Authenticated user should NOT see the anonymous project
    token = _as_user("user-c", "carol")
    try:
        listing = (await project_tools.list_projects()).data
        ids = {p["id"] for p in listing}
        assert anon_proj["id"] not in ids
    finally:
        current_user.reset(token)


@pytest.mark.asyncio
async def test_user_namespace_appears_in_storage_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts3"))

    token = _as_user("user-d", "dave")
    try:
        d = (await project_tools.create_project(name="dave's project")).data
    finally:
        current_user.reset(token)

    # Files for user D should live under .../users/user-d/<engagement_id>/...
    root = tmp_path / "artifacts3"
    user_dir = root / "users" / "user-d"
    assert user_dir.exists(), f"expected per-user dir at {user_dir} — got tree: {list(root.rglob('*'))}"
    assert any(p.name == d["id"] for p in user_dir.iterdir()), \
        f"expected engagement dir {d['id']} under {user_dir}"
