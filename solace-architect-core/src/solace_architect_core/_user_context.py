"""Cross-plugin user-identity propagation.

Entrypoint plugins set ``current_user`` per request; tools read it without
needing to know which entrypoint authenticated the user.

Shape (matches what ``_extract_initial_claims`` returns from any entrypoint):

    {
        "id":      str,                  # stable identifier; "anonymous" when auth bypassed
        "name":    str | None,
        "email":   str | None,
        "groups":  list[str],
        "source":  str,                  # "webui" | "cli" | "rest" | …
        "is_admin": bool,                # webui-only; defaults False
    }
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


ANONYMOUS_USER: dict[str, Any] = {
    "id": "anonymous",
    "name": "anonymous",
    "email": None,
    "groups": [],
    "source": "unknown",
    "is_admin": False,
}

current_user: ContextVar[dict[str, Any]] = ContextVar("current_user", default=ANONYMOUS_USER)


def get_current_user() -> dict[str, Any]:
    """Read the current request's user claims, falling back to anonymous."""
    return current_user.get()
