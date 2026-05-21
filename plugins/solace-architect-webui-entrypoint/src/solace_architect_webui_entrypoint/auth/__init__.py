"""Local user/password authentication for the WebUI entrypoint.

SQLite-backed, single-file. See module-level docs in ``db.py`` for the schema.

Public surface:
- ``ensure_initialized(db_path)`` — create the DB + tables on first run.
- ``install_middleware(app, auth_state)`` — wire authn into an aiohttp Application.
- ``add_auth_routes(app, auth_state)`` — register /login, /signup, /api/auth/* handlers.
"""

from .db import AuthState, ensure_initialized
from .middleware import install_middleware
from .routes import add_auth_routes

__all__ = ["AuthState", "ensure_initialized", "install_middleware", "add_auth_routes"]
