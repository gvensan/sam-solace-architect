"""SQLite schema and connection management for the local user DB.

Schema:
- users(id, username UNIQUE, email UNIQUE, display_name, password_hash, ...)
- sessions(token, user_id, created_at, expires_at, user_agent, ip_address)
- login_attempts(username, ip_address, attempted_at, succeeded)

DB path defaults to ``<SA_STORAGE_ROOT>/__system__/users.db``, configurable via
``WEBUI_USERS_DB``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE,
    display_name    TEXT,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_admin        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    token           TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    user_agent      TEXT,
    ip_address      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    username        TEXT NOT NULL,
    ip_address      TEXT,
    attempted_at    TEXT NOT NULL,
    succeeded       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_user_time
    ON login_attempts(username, attempted_at);
"""


@dataclass
class AuthState:
    """Shared auth state attached to the aiohttp Application."""
    db_path: Path
    enable_signup: bool
    require_auth: bool
    csrf_secret: str
    session_ttl_seconds: int
    rate_limit_max_failures: int
    rate_limit_window_seconds: int

    # Connection pool — SQLite is single-writer; we open per-request connections.
    _lock: threading.Lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        """Open a connection with sensible defaults. Caller is responsible for closing."""
        conn = sqlite3.connect(str(self.db_path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_initialized(
    db_path: Path,
    *,
    enable_signup: bool = True,
    require_auth: bool = True,
    csrf_secret: Optional[str] = None,
    session_ttl_seconds: int = 7 * 24 * 3600,
    rate_limit_max_failures: int = 5,
    rate_limit_window_seconds: int = 5 * 60,
) -> AuthState:
    """Create the DB file + tables if missing. Returns shared AuthState."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.executescript(SCHEMA)
        log.info("Auth DB initialized at %s", db_path)
    finally:
        conn.close()

    return AuthState(
        db_path=db_path,
        enable_signup=enable_signup,
        require_auth=require_auth,
        csrf_secret=csrf_secret or uuid.uuid4().hex,
        session_ttl_seconds=session_ttl_seconds,
        rate_limit_max_failures=rate_limit_max_failures,
        rate_limit_window_seconds=rate_limit_window_seconds,
    )


# ---------- user helpers ----------

def has_any_user(state: AuthState) -> bool:
    """First-user bootstrap detection: is the users table empty?"""
    conn = state.connect()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return row["n"] > 0
    finally:
        conn.close()


def create_user(
    state: AuthState, *, username: str, password_hash: str,
    email: Optional[str] = None, display_name: Optional[str] = None,
    is_admin: bool = False,
) -> dict:
    """Insert a user; returns its row as a dict. Raises sqlite3.IntegrityError on dup."""
    user_id = str(uuid.uuid4())
    conn = state.connect()
    try:
        conn.execute(
            """INSERT INTO users(id, username, email, display_name, password_hash,
                                  created_at, is_active, is_admin)
               VALUES(?, ?, ?, ?, ?, ?, 1, ?)""",
            (user_id, username, email, display_name, password_hash,
             _now_iso(), 1 if is_admin else 0),
        )
        return get_user_by_id(state, user_id)
    finally:
        conn.close()


def get_user_by_id(state: AuthState, user_id: str) -> Optional[dict]:
    conn = state.connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_username(state: AuthState, username: str) -> Optional[dict]:
    conn = state.connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE",
                           (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_password_hash(state: AuthState, user_id: str, new_hash: str) -> None:
    conn = state.connect()
    try:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
    finally:
        conn.close()


def touch_last_login(state: AuthState, user_id: str) -> None:
    conn = state.connect()
    try:
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (_now_iso(), user_id))
    finally:
        conn.close()


def user_to_claims(user: dict) -> dict:
    """Convert a DB row to the claims-dict shape that downstream agents see."""
    return {
        "id":       user["id"],
        "name":     user.get("display_name") or user["username"],
        "email":    user.get("email"),
        "groups":   [],
        "source":   "webui",
        "is_admin": bool(user.get("is_admin", 0)),
    }
