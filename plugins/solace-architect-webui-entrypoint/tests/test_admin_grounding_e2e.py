"""End-to-end admin gate (#11): a real aiohttp app + the real auth middleware +
the real route adapter, driven over actual HTTP with DB-backed sessions.

Verifies the full security boundary, not just the predicate:
  anonymous            → 401 (middleware: unauthenticated)
  authenticated, !admin → 403 (adapter admin gate)
  authenticated, admin  → 200 + real payload, and POST flows through the adapter
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from solace_architect_webui_entrypoint.auth import db
from solace_architect_webui_entrypoint.auth.middleware import install_middleware, SESSION_COOKIE
from solace_architect_webui_entrypoint.auth.sessions import create_session
from solace_architect_webui_entrypoint.component import make_api_handler
from solace_architect_webui_entrypoint.routes.api import API_ROUTES


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


def _build(tmp_path):
    state = db.ensure_initialized(tmp_path / "users.db", require_auth=True)
    admin = db.create_user(state, username="admin", password_hash="x", is_admin=True)
    user = db.create_user(state, username="reg", password_hash="x", is_admin=False)
    admin_token, _ = create_session(state, admin["id"])
    user_token, _ = create_session(state, user["id"])
    app = web.Application()
    install_middleware(app, state)
    # Register the REAL admin-grounding routes with the REAL adapter.
    for route in API_ROUTES:
        if route[1].startswith("/api/admin/grounding"):
            method, path, handler = route[0], route[1], route[2]
            admin_required = route[3] if len(route) > 3 else False
            app.router.add_route(method, path, make_api_handler(handler, admin_required))
    return app, admin_token, user_token


def test_admin_gate_end_to_end(tmp_path):
    app, admin_token, user_token = _build(tmp_path)
    refs = "/api/admin/grounding/refs"

    async def run():
        async with TestClient(TestServer(app)) as client:
            # anonymous → 401 from the middleware
            assert (await client.get(refs)).status == 401

            # authenticated non-admin → 403 from the adapter gate
            r = await client.get(refs, cookies={SESSION_COOKIE: user_token})
            assert r.status == 403

            # admin → 200 + real payload
            r = await client.get(refs, cookies={SESSION_COOKIE: admin_token})
            assert r.status == 200
            data = await r.json()
            assert "refs" in data and "digest_cap" in data

            # admin POST (body flows through the adapter into the handler)
            r = await client.post(refs, cookies={SESSION_COOKIE: admin_token},
                                  json={"ref_type": "text",
                                        "source": "An org standard reference body.",
                                        "title": "Std"})
            assert r.status == 200
            added = await r.json()
            assert added["status"] == "pending" and added["added_by"] == "admin"

            # non-admin POST → 403 (write path is gated too)
            r = await client.post(refs, cookies={SESSION_COOKIE: user_token},
                                  json={"ref_type": "text", "source": "x"})
            assert r.status == 403

    asyncio.run(run())
