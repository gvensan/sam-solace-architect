"""Failed-login rate limiting.

Per-username sliding window: N failures within W seconds → temporary lockout
until the oldest failure ages out. Stored in the same SQLite DB as users.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import AuthState


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def record_attempt(
    state: AuthState, *, username: str, succeeded: bool,
    ip_address: str | None = None,
) -> None:
    conn = state.connect()
    try:
        conn.execute(
            """INSERT INTO login_attempts(username, ip_address, attempted_at, succeeded)
               VALUES(?, ?, ?, ?)""",
            (username, ip_address, _iso(_now()), 1 if succeeded else 0),
        )
    finally:
        conn.close()


def is_locked_out(state: AuthState, username: str) -> bool:
    """True if username has had ≥max_failures failed logins in the last window."""
    if state.rate_limit_max_failures <= 0:
        return False
    window_start = _now() - timedelta(seconds=state.rate_limit_window_seconds)
    conn = state.connect()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM login_attempts
               WHERE username = ? COLLATE NOCASE
               AND succeeded = 0
               AND attempted_at > ?""",
            (username, _iso(window_start)),
        ).fetchone()
        return (row["n"] or 0) >= state.rate_limit_max_failures
    finally:
        conn.close()


def clear_failed_attempts(state: AuthState, username: str) -> None:
    """After a successful login, reset the counter for that username."""
    conn = state.connect()
    try:
        conn.execute(
            "DELETE FROM login_attempts WHERE username = ? COLLATE NOCASE AND succeeded = 0",
            (username,),
        )
    finally:
        conn.close()


def purge_old(state: AuthState, *, retain_days: int = 7) -> None:
    """Drop login-attempt rows older than retain_days. Run periodically."""
    cutoff = _now() - timedelta(days=retain_days)
    conn = state.connect()
    try:
        conn.execute("DELETE FROM login_attempts WHERE attempted_at <= ?", (_iso(cutoff),))
    finally:
        conn.close()
