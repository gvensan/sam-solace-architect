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


def resolve_user_id(user_id: str | None, tool_context: Any = None) -> str | None:
    """Pick the user_id to scope storage with, in this order of preference:

    1. Explicit ``user_id`` arg — kept for back-compat with the legacy LLM-
       extracts-the-header path and tests that pass it directly.
    2. ``tool_context.state["a2a_context"]["user_id"]`` — SAM populates this
       from the A2A task's user_identity, so the LLM no longer has to
       remember to lift it from the [Active engagement: ...] header.
    3. ``None`` — preserves the unscoped layout for anonymous / dev-bypass.

    The ``tool_context`` arg is duck-typed (kept as ``Any``) to avoid
    importing google.adk into the core; SAM excludes parameters named
    ``tool_context`` from the LLM-visible schema and auto-injects them
    (see solace_agent_mesh.agent.tools.dynamic_tool._get_schema_from_signature).
    """
    if user_id and user_id != "anonymous":
        return user_id
    if tool_context is None:
        return user_id
    try:
        a2a_ctx = tool_context.state.get("a2a_context") or {}
        uid = a2a_ctx.get("user_id")
        if uid and uid != "anonymous":
            return uid
    except (AttributeError, TypeError):
        pass
    return user_id


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
