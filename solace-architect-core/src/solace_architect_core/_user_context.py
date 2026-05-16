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

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


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


@contextmanager
def scoped_user(user_id: str | None) -> Iterator[None]:
    """Temporarily bind ``current_user`` to ``user_id`` for storage namespacing.

    Agents run in a separate process from the WebUI, so the request-bound
    ContextVar isn't populated. Tools accept an optional ``user_id`` arg the
    caller (LLM) lifts from the [Active engagement: ..., user_id=<uuid>]
    message header, and we set it here so ``_user_namespace()`` resolves the
    user-scoped path the WebUI wrote under.

    No-op when ``user_id`` is falsy or equals ``"anonymous"`` — preserves the
    legacy unscoped layout for tests, CLI, and dev bypass.
    """
    if not user_id or user_id == "anonymous":
        yield
        return
    token = current_user.set({
        "id": user_id, "name": user_id, "email": None,
        "groups": [], "source": "agent_header", "is_admin": False,
    })
    try:
        yield
    finally:
        current_user.reset(token)
