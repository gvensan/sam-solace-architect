"""Admin CLI for managing local users.

Usage:
    python -m solace_architect_webui_entrypoint.admin reset-password <username>
    python -m solace_architect_webui_entrypoint.admin list-users
    python -m solace_architect_webui_entrypoint.admin make-admin <username>
    python -m solace_architect_webui_entrypoint.admin disable-user <username>

DB path resolves the same way as the running entrypoint:
    $WEBUI_USERS_DB, or $SA_STORAGE_ROOT/__system__/users.db.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .auth import db
from .auth.passwords import hash_password, validate_password_strength


def _db_path() -> Path:
    storage_root = Path(os.environ.get("SA_STORAGE_ROOT", "/tmp/sa-artifacts"))
    return Path(os.environ.get("WEBUI_USERS_DB", str(storage_root / "__system__" / "users.db")))


def _state() -> db.AuthState:
    return db.ensure_initialized(_db_path())


def cmd_list_users(_args: argparse.Namespace) -> int:
    state = _state()
    conn = state.connect()
    try:
        rows = conn.execute(
            "SELECT username, email, display_name, is_admin, is_active, "
            "created_at, last_login_at FROM users ORDER BY username"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("(no users)")
        return 0
    for r in rows:
        flags = []
        if r["is_admin"]: flags.append("admin")
        if not r["is_active"]: flags.append("disabled")
        print(f"  {r['username']:20s}  {r['email'] or '-':30s}  "
              f"{r['display_name'] or '-':25s}  [{', '.join(flags) or 'user'}]")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    state = _state()
    user = db.get_user_by_username(state, args.username)
    if not user:
        print(f"error: user {args.username!r} not found", file=sys.stderr)
        return 2

    pw1 = getpass.getpass("New password: ")
    pw2 = getpass.getpass("Confirm:       ")
    if pw1 != pw2:
        print("error: passwords don't match", file=sys.stderr)
        return 2
    ok, err = validate_password_strength(pw1)
    if not ok:
        print(f"error: {err}", file=sys.stderr)
        return 2

    db.update_password_hash(state, user["id"], hash_password(pw1))

    # Revoke every existing session for safety
    conn = state.connect()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    finally:
        conn.close()

    print(f"ok: password reset for {args.username}, all sessions revoked")
    return 0


def cmd_make_admin(args: argparse.Namespace) -> int:
    state = _state()
    user = db.get_user_by_username(state, args.username)
    if not user:
        print(f"error: user {args.username!r} not found", file=sys.stderr)
        return 2
    conn = state.connect()
    try:
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (user["id"],))
    finally:
        conn.close()
    print(f"ok: {args.username} is now an admin")
    return 0


def cmd_disable_user(args: argparse.Namespace) -> int:
    state = _state()
    user = db.get_user_by_username(state, args.username)
    if not user:
        print(f"error: user {args.username!r} not found", file=sys.stderr)
        return 2
    conn = state.connect()
    try:
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (user["id"],))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    finally:
        conn.close()
    print(f"ok: {args.username} disabled, sessions revoked")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="solace_architect_webui_entrypoint.admin")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    subparsers.add_parser("list-users").set_defaults(func=cmd_list_users)

    p = subparsers.add_parser("reset-password")
    p.add_argument("username")
    p.set_defaults(func=cmd_reset_password)

    p = subparsers.add_parser("make-admin")
    p.add_argument("username")
    p.set_defaults(func=cmd_make_admin)

    p = subparsers.add_parser("disable-user")
    p.add_argument("username")
    p.set_defaults(func=cmd_disable_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
