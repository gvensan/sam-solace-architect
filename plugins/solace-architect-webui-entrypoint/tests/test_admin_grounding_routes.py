"""Admin-only managed-grounding routes (slice 2).

Covers: the route table declares the admin surface admin-required; the
_is_admin_user() gate reflects the per-request current_user contextvar; and the
handler functions wire through to managed_grounding_tools against file storage.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from solace_architect_core._user_context import current_user, ANONYMOUS_USER
from solace_architect_core.tools import grounding_tools
from solace_architect_webui_entrypoint.routes import api


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


@contextmanager
def _as(user):
    token = current_user.set(user)
    try:
        yield
    finally:
        current_user.reset(token)


_ADMIN = {"id": "u1", "name": "Giri", "email": None, "groups": [],
          "source": "webui", "is_admin": True}
_USER = {**_ADMIN, "is_admin": False, "name": "Reg"}


def _run(coro):
    return asyncio.run(coro)


# --- route table contract --------------------------------------------------

def test_admin_grounding_routes_registered_and_flagged_admin():
    admin_paths = {r[1]: r for r in api.API_ROUTES if r[1].startswith("/api/admin/grounding")}
    assert "/api/admin/grounding/refs" in admin_paths
    assert "/api/admin/grounding/gaps" in admin_paths
    # EVERY admin-grounding route must carry the admin_required flag (no silent gap).
    for path, route in admin_paths.items():
        assert len(route) > 3 and route[3] is True, f"{path} is not admin-gated"


# --- the gate predicate ----------------------------------------------------

def test_is_admin_user_reflects_contextvar():
    with _as(_ADMIN):
        assert api._is_admin_user() is True
    with _as(_USER):
        assert api._is_admin_user() is False
    with _as(dict(ANONYMOUS_USER)):
        assert api._is_admin_user() is False


def test_admin_actor_prefers_name():
    with _as(_ADMIN):
        assert api._admin_actor() == "Giri"


# --- handlers wire through to the core ------------------------------------

def test_add_list_activate_flow_through_handlers():
    with _as(_ADMIN):
        added = _run(api.admin_grounding_add(
            ref_type="text", source="Org standard: domain/object/verb/version.", title="Std"))
        assert "id" in added and added["status"] == "pending"
        assert added["added_by"] == "Giri"          # _admin_actor flowed through

        listed = _run(api.admin_grounding_list())
        assert listed["count"] == 1 and listed["digest_cap"] > 0

        activated = _run(api.admin_grounding_set_status(ref_id=added["id"], status="active"))
        assert activated["digest"]["active"] == 1

        removed = _run(api.admin_grounding_remove(ref_id=added["id"]))
        assert removed["removed"] == added["id"]


def test_add_rejects_bad_type():
    with _as(_ADMIN):
        res = _run(api.admin_grounding_add(ref_type="pdf", source="x"))
        assert "error" in res


def test_refresh_all_handler_safe_when_no_url_refs():
    with _as(_ADMIN):
        res = _run(api.admin_grounding_refresh_all())
    assert res["refreshed"] == 0 and res["failed"] == 0


def test_gaps_handler_aggregates_ledger_by_topic():
    # Seed the runtime grounding-gaps ledger, then read it back via the handler.
    _run(grounding_tools.record_grounding_gap(topic="vpn-design", reason="not in topic-map", agent="load_grounding"))
    _run(grounding_tools.record_grounding_gap(topic="vpn-design", reason="not in topic-map", agent="load_grounding"))
    _run(grounding_tools.record_grounding_gap(topic="insights", reason="missing", agent="load_grounding"))
    with _as(_ADMIN):
        res = _run(api.admin_grounding_gaps())
    topics = {g["topic"]: g for g in res["gaps"]}
    assert topics["vpn-design"]["count"] == 2 and topics["insights"]["count"] == 1
    assert res["gaps"][0]["topic"] == "vpn-design"   # most-requested first
