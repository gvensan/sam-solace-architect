"""HTTP route handlers for /login, /signup, /api/auth/*."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from aiohttp import web

from . import db, passwords, ratelimit, sessions
from .db import AuthState
from .middleware import SESSION_COOKIE


log = logging.getLogger(__name__)


def _webui_dir() -> Path:
    """Return the webui static-asset directory (one level up from auth/)."""
    return Path(__file__).resolve().parent.parent / "webui"


def _no_cache_json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _set_session_cookie(resp: web.Response, token: str, max_age_seconds: int, secure: bool) -> None:
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=max_age_seconds, httponly=True,
        samesite="Lax", secure=secure, path="/",
    )


def _clear_session_cookie(resp: web.Response) -> None:
    resp.del_cookie(SESSION_COOKIE, path="/")


# ---------- HTML pages ----------

async def login_page(request: web.Request) -> web.Response:
    return web.FileResponse(_webui_dir() / "login" / "index.html",
                            headers={"Cache-Control": "no-store"})


async def signup_page(request: web.Request) -> web.Response:
    state: AuthState = request.app["auth_state"]
    # If signup is disabled AND we already have a user, refuse access.
    if not state.enable_signup and db.has_any_user(state):
        return web.HTTPForbidden(reason="signup disabled by operator")
    return web.FileResponse(_webui_dir() / "signup" / "index.html",
                            headers={"Cache-Control": "no-store"})


# ---------- JSON APIs ----------

async def api_signup(request: web.Request) -> web.Response:
    state: AuthState = request.app["auth_state"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _no_cache_json({"error": "invalid JSON body"}, status=400)

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    email = (body.get("email") or "").strip() or None
    display_name = (body.get("display_name") or "").strip() or None

    if not username:
        return _no_cache_json({"error": "username is required"}, status=400)
    if " " in username or "@" in username:
        return _no_cache_json({"error": "username must not contain spaces or '@'"}, status=400)

    ok, err = passwords.validate_password_strength(password)
    if not ok:
        return _no_cache_json({"error": err}, status=400)

    first_user = not db.has_any_user(state)

    # Reject signup if disabled and not the bootstrap case
    if not state.enable_signup and not first_user:
        return _no_cache_json({"error": "signup is disabled"}, status=403)

    try:
        password_hash = passwords.hash_password(password)
        user = db.create_user(
            state, username=username, password_hash=password_hash,
            email=email, display_name=display_name,
            is_admin=first_user,        # first user becomes admin
        )
    except sqlite3.IntegrityError as e:
        msg = "username or email already in use"
        return _no_cache_json({"error": msg}, status=409)
    except ValueError as e:
        return _no_cache_json({"error": str(e)}, status=400)

    # Auto-login on successful signup
    token, expires = sessions.create_session(
        state, user["id"],
        user_agent=request.headers.get("User-Agent"),
        ip_address=_client_ip(request),
    )
    db.touch_last_login(state, user["id"])

    resp = _no_cache_json({
        "user": db.user_to_claims(user),
        "is_first_user": first_user,
        "redirect": "/",
    })
    _set_session_cookie(resp, token, state.session_ttl_seconds, secure=_is_https(request))
    return resp


async def api_login(request: web.Request) -> web.Response:
    state: AuthState = request.app["auth_state"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _no_cache_json({"error": "invalid JSON body"}, status=400)

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return _no_cache_json({"error": "username and password required"}, status=400)

    if ratelimit.is_locked_out(state, username):
        return _no_cache_json(
            {"error": "too many failed attempts; try again in a few minutes"},
            status=429,
        )

    ip = _client_ip(request)
    user = db.get_user_by_username(state, username)
    if not user or not user.get("is_active"):
        ratelimit.record_attempt(state, username=username, succeeded=False, ip_address=ip)
        return _no_cache_json({"error": "invalid credentials"}, status=401)

    if not passwords.verify_password(user["password_hash"], password):
        ratelimit.record_attempt(state, username=username, succeeded=False, ip_address=ip)
        return _no_cache_json({"error": "invalid credentials"}, status=401)

    # Success path — opportunistically refresh hash if defaults changed
    if passwords.needs_rehash(user["password_hash"]):
        try:
            db.update_password_hash(state, user["id"], passwords.hash_password(password))
        except Exception:
            log.exception("Failed to upgrade password hash for user %s", user["id"])

    ratelimit.record_attempt(state, username=username, succeeded=True, ip_address=ip)
    ratelimit.clear_failed_attempts(state, username)

    token, expires = sessions.create_session(
        state, user["id"],
        user_agent=request.headers.get("User-Agent"),
        ip_address=ip,
    )
    db.touch_last_login(state, user["id"])

    redirect = (request.query.get("next") or body.get("next") or "/")
    resp = _no_cache_json({"user": db.user_to_claims(user), "redirect": redirect})
    _set_session_cookie(resp, token, state.session_ttl_seconds, secure=_is_https(request))
    return resp


async def api_logout(request: web.Request) -> web.Response:
    state: AuthState = request.app["auth_state"]
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sessions.revoke_session(state, token)
    resp = _no_cache_json({"ok": True})
    _clear_session_cookie(resp)
    return resp


async def api_me(request: web.Request) -> web.Response:
    """Current-user info. Always 200; payload tells whether authenticated."""
    state: AuthState = request.app["auth_state"]
    token = request.cookies.get(SESSION_COOKIE)
    user_row = sessions.validate_session(state, token) if token else None
    return _no_cache_json({
        "authenticated": bool(user_row),
        "user": db.user_to_claims(user_row) if user_row else None,
        "require_auth": state.require_auth,
        "enable_signup": state.enable_signup,
        "first_run": not db.has_any_user(state),
    })


async def api_change_password(request: web.Request) -> web.Response:
    state: AuthState = request.app["auth_state"]
    token = request.cookies.get(SESSION_COOKIE)
    user_row = sessions.validate_session(state, token) if token else None
    if not user_row:
        return _no_cache_json({"error": "unauthenticated"}, status=401)

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _no_cache_json({"error": "invalid JSON body"}, status=400)

    old = body.get("old_password") or ""
    new = body.get("new_password") or ""

    if not passwords.verify_password(user_row["password_hash"], old):
        return _no_cache_json({"error": "current password incorrect"}, status=401)

    try:
        new_hash = passwords.hash_password(new)
    except ValueError as e:
        return _no_cache_json({"error": str(e)}, status=400)

    db.update_password_hash(state, user_row["id"], new_hash)
    # Force re-login everywhere after password change
    sessions.revoke_all_sessions_for_user(state, user_row["id"])
    resp = _no_cache_json({"ok": True, "redirect": "/login"})
    _clear_session_cookie(resp)
    return resp


# ---------- helpers ----------

def _is_https(request: web.Request) -> bool:
    # Behind a reverse proxy with TLS termination, look at X-Forwarded-Proto.
    proto = request.headers.get("X-Forwarded-Proto", "").lower()
    if proto == "https":
        return True
    return request.scheme == "https"


def _client_ip(request: web.Request) -> str | None:
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.remote if request else None)
    )


# ---------- registration ----------

def add_auth_routes(app: web.Application, auth_state: AuthState) -> None:
    """Register auth pages + APIs on the aiohttp Application."""
    app.router.add_get("/login", login_page)
    app.router.add_get("/login/", login_page)
    app.router.add_get("/signup", signup_page)
    app.router.add_get("/signup/", signup_page)

    app.router.add_post("/api/auth/login", api_login)
    app.router.add_post("/api/auth/signup", api_signup)
    app.router.add_post("/api/auth/logout", api_logout)
    app.router.add_get("/api/auth/me", api_me)
    app.router.add_post("/api/auth/change-password", api_change_password)

    log.info("Auth routes registered (signup=%s, require_auth=%s)",
             auth_state.enable_signup, auth_state.require_auth)
