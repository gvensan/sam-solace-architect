"""aiohttp middleware: cookie → current_user contextvar.

Runs on every request, reads the ``sa-session`` cookie, looks up the session,
populates ``solace_architect_core._user_context.current_user`` for the rest
of the handler chain.

Unauthenticated requests are handled by route policy:
- HTML routes that require auth → redirect to /login (302)
- /api/* routes that require auth → JSON 401
- /login, /signup, /api/auth/{login,signup}, /assets/* → always allowed

When AuthState.require_auth=False (dev bypass), everyone is "anonymous".
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from aiohttp import web

from solace_architect_core._user_context import ANONYMOUS_USER, current_user

from .db import AuthState, user_to_claims
from .sessions import validate_session


log = logging.getLogger(__name__)


SESSION_COOKIE = "sa-session"

# Paths that never require auth (in addition to the auth pages themselves)
_PUBLIC_PREFIXES = (
    "/login", "/signup",
    "/api/auth/login", "/api/auth/signup", "/api/auth/me",   # /me returns 200 anon / 200 user
    "/assets/",
    "/favicon",
    "/health", "/ready",                                      # probes — no auth
)


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES)


def install_middleware(app: web.Application, auth_state: AuthState) -> None:
    """Attach the auth middleware. Must be installed BEFORE route handlers run."""
    app["auth_state"] = auth_state

    @web.middleware
    async def auth_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        state: AuthState = request.app["auth_state"]
        path = request.path

        # Dev bypass — everyone is anonymous, no auth ever required
        if not state.require_auth:
            token = current_user.set(dict(ANONYMOUS_USER))
            try:
                return await handler(request)
            finally:
                current_user.reset(token)

        # Validate session cookie if present
        session_token = request.cookies.get(SESSION_COOKIE)
        user_row = validate_session(state, session_token) if session_token else None
        claims = user_to_claims(user_row) if user_row else None

        # Set contextvar for the duration of this request
        ctx_token = current_user.set(claims if claims else dict(ANONYMOUS_USER))
        try:
            # Public paths skip the auth gate
            if _is_public(path) or claims:
                return await handler(request)

            # Authenticated request required, no valid session
            if path.startswith("/api/"):
                return web.json_response(
                    {"error": "unauthenticated", "login_url": "/login"},
                    status=401, headers={"Cache-Control": "no-store"},
                )

            # HTML route — bounce to login, preserving the original destination
            redirect_to = path
            if request.query_string:
                redirect_to += "?" + request.query_string
            return web.HTTPFound(location=f"/login?next={redirect_to}")

        finally:
            current_user.reset(ctx_token)

    app.middlewares.append(auth_middleware)
    log.info("Auth middleware installed (require_auth=%s)", auth_state.require_auth)
