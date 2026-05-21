"""Session token management.

Tokens are 256-bit base64url random strings stored in the ``sessions`` table.
Validation checks expiry; expired tokens are purged opportunistically.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import AuthState


log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def create_session(
    state: AuthState, user_id: str,
    *, user_agent: Optional[str] = None, ip_address: Optional[str] = None,
) -> tuple[str, datetime]:
    """Issue a new session token. Returns (token, expires_at)."""
    token = secrets.token_urlsafe(32)        # 256 bits
    now = _now()
    expires = now + timedelta(seconds=state.session_ttl_seconds)
    conn = state.connect()
    try:
        conn.execute(
            """INSERT INTO sessions(token, user_id, created_at, expires_at,
                                     user_agent, ip_address)
               VALUES(?, ?, ?, ?, ?, ?)""",
            (token, user_id, _iso(now), _iso(expires), user_agent, ip_address),
        )
    finally:
        conn.close()
    return token, expires


def validate_session(state: AuthState, token: str) -> Optional[dict]:
    """Look up a session by token, validate expiry, return the user row or None."""
    if not token:
        return None
    conn = state.connect()
    try:
        row = conn.execute(
            """SELECT u.* FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.token = ? AND u.is_active = 1
               AND s.expires_at > ?""",
            (token, _iso(_now())),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def revoke_session(state: AuthState, token: str) -> None:
    """Delete a session by token (logout)."""
    conn = state.connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    finally:
        conn.close()


def revoke_all_sessions_for_user(state: AuthState, user_id: str) -> None:
    """Used after password change. Forces re-login everywhere."""
    conn = state.connect()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    finally:
        conn.close()


def purge_expired(state: AuthState) -> int:
    """Best-effort cleanup of expired sessions. Returns the row count deleted."""
    conn = state.connect()
    try:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_iso(_now()),))
        return cur.rowcount or 0
    finally:
        conn.close()
