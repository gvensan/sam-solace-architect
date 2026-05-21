"""File-based artifact storage for Phase 1.

This is a local backing store used in test-harness mode. In production deployment
under SAM, the same interface will be implemented against SAM's ArtifactService.

Layout under ``SA_STORAGE_ROOT``:
  - When run under SAM, the WebUI entrypoint sets ``SA_STORAGE_ROOT`` to its
    configured ``artifact_service.base_path`` at startup, so SA's state and
    SAM's filesystem artifact bytes share one root.
  - When used directly (tests, scripts) without that bootstrap, the fallback
    is ``./sa-artifacts`` relative to the current working directory.

    <engagement_id>/
        meta/
            decisions.yaml
            findings.yaml
            open-items.yaml
            feedback.yaml
        discovery/
        topic-design/
        ...etc
"""

from __future__ import annotations

import os
import re
import threading
import yaml
from pathlib import Path
from typing import Any

from ._user_context import get_current_user


_LOCK = threading.RLock()

# Engagements with these IDs are treated as shared infrastructure and are NOT
# namespaced under any user. Used for cross-user system state (e.g., the
# global users.db belongs to the auth plugin, not to any individual user).
_SHARED_ENGAGEMENTS = frozenset({"__system__"})


def storage_root() -> Path:
    """Resolve the root directory for engagement artifacts."""
    return Path(os.environ.get("SA_STORAGE_ROOT", "./sa-artifacts")).resolve()


def _user_namespace() -> str | None:
    """Return the current user's storage namespace, or None for anonymous/bypass.

    Anonymous users keep the legacy layout (storage_root/<engagement_id>/...) so
    dev mode (WEBUI_REQUIRE_AUTH=false) and the test-harness need no changes.
    """
    user_id = get_current_user().get("id")
    if not user_id or user_id == "anonymous":
        return None
    if not re.match(r"^[a-zA-Z0-9_\-]+$", user_id):
        # Defensive: never let a malformed user_id punch through to the filesystem
        raise ValueError(f"unsafe user_id for storage namespacing: {user_id!r}")
    return user_id


def _engagement_root(engagement_id: str) -> Path:
    """Resolve the parent directory for an engagement, respecting user namespacing."""
    if engagement_id in _SHARED_ENGAGEMENTS:
        return storage_root() / engagement_id
    user_ns = _user_namespace()
    if user_ns is None:
        return storage_root() / engagement_id
    return storage_root() / "users" / user_ns / engagement_id


def safe_artifact_path(engagement_id: str, artifact_name: str) -> Path:
    """Validate + resolve an artifact path within an engagement's namespace.

    User-scoped: paths become ``<storage_root>/users/<user_id>/<engagement_id>/<artifact>``
    when an authenticated user is active. ``__system__`` engagement is shared
    (unscoped). Anonymous/dev-bypass mode also stays unscoped for back-compat.

    Rejects: ``..`` segments, absolute paths, paths escaping the engagement namespace.
    Mirrors v2spec §6.1 path-traversal guard.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]+(/[a-zA-Z0-9_\-.]+)+$", artifact_name):
        raise ValueError(f"artifact_name must match 'category/filename' pattern: {artifact_name!r}")
    if ".." in artifact_name.split("/"):
        raise ValueError(f"artifact_name contains path traversal: {artifact_name!r}")

    root = _engagement_root(engagement_id)
    resolved = (root / artifact_name).resolve()
    if not str(resolved).startswith(str(root.resolve()) + os.sep):
        raise ValueError(f"artifact_name escapes engagement namespace: {artifact_name!r}")
    return resolved


def read_text(engagement_id: str, artifact_name: str) -> str:
    """Read an artifact as text. Raises FileNotFoundError if absent."""
    path = safe_artifact_path(engagement_id, artifact_name)
    return path.read_text(encoding="utf-8")


def write_text(engagement_id: str, artifact_name: str, content: str) -> Path:
    """Write an artifact (creates parent dirs)."""
    path = safe_artifact_path(engagement_id, artifact_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        path.write_text(content, encoding="utf-8")
    return path


def append_jsonl(engagement_id: str, artifact_name: str, row: dict) -> Path:
    """Append a single JSON object as a line to a JSONL artifact (creates parent dirs).

    Concurrency-safe under the module ``_LOCK``. Used by telemetry writers where
    every LLM call appends one row and a full read-modify-write would race.
    """
    import json as _json
    path = safe_artifact_path(engagement_id, artifact_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _json.dumps(row, separators=(",", ":"), sort_keys=False) + "\n"
    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    return path


def read_jsonl(engagement_id: str, artifact_name: str) -> list[dict]:
    """Read a JSONL artifact, returning a list of parsed objects. Empty list if missing."""
    import json as _json
    try:
        text = read_text(engagement_id, artifact_name)
    except FileNotFoundError:
        return []
    rows = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(_json.loads(ln))
        except _json.JSONDecodeError:
            continue
    return rows


def read_yaml(engagement_id: str, artifact_name: str, default: Any = None) -> Any:
    """Read a YAML artifact. Returns ``default`` if file doesn't exist.

    NOTE: This raises ``yaml.YAMLError`` on a malformed file. For request-path
    code (HTTP handlers, dashboard endpoints) where a corrupt artifact must
    NOT crash the response, prefer :func:`safe_read_yaml` instead — it logs
    the parse failure and returns ``default`` so a single bad file degrades
    one feature gracefully rather than taking down the whole endpoint.
    """
    try:
        return yaml.safe_load(read_text(engagement_id, artifact_name)) or default
    except FileNotFoundError:
        return default


_LOG = __import__("logging").getLogger(__name__)


def safe_read_yaml(engagement_id: str, artifact_name: str, default: Any = None) -> Any:
    """Read a YAML artifact, tolerating parse errors.

    Same contract as :func:`read_yaml`, but additionally catches
    ``yaml.YAMLError`` (raised for malformed files) and returns ``default``
    after logging the failure.

    Use this from request-path code where a single corrupt artifact must
    not surface as an HTTP 500 — e.g. the dashboard's overview endpoint
    polls multiple engagements and one bad brief shouldn't break the
    whole dashboard. The original :func:`read_yaml` still raises, which
    is the right behavior inside agent tools (an agent that wrote a
    corrupt YAML wants to know about it so it can retry).
    """
    import yaml as _yaml  # local rebind avoids shadowing the module attr
    try:
        return _yaml.safe_load(read_text(engagement_id, artifact_name)) or default
    except FileNotFoundError:
        return default
    except _yaml.YAMLError as exc:
        _LOG.warning(
            "safe_read_yaml: %s/%s is malformed (%s: %s); returning default.",
            engagement_id, artifact_name, type(exc).__name__,
            str(exc).split("\n")[0],
        )
        return default


def write_yaml(engagement_id: str, artifact_name: str, data: Any) -> Path:
    """Write a YAML artifact (canonical serialization)."""
    return write_text(engagement_id, artifact_name,
                      yaml.safe_dump(data, default_flow_style=False, sort_keys=False))


def list_artifacts(engagement_id: str, category: str | None = None) -> list[str]:
    """List artifact paths (relative to engagement) under ``category`` or all."""
    root = _engagement_root(engagement_id)
    if not root.exists():
        return []
    if category:
        scan_root = root / category
        if not scan_root.exists():
            return []
        return sorted(
            str(p.relative_to(root))
            for p in scan_root.rglob("*")
            if p.is_file()
        )
    return sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file()
    )


def next_id(existing_ids: list[str], prefix: str) -> str:
    """Compute the next sequential ID (e.g., D1, D2, …). Tolerates gaps."""
    nums = []
    for s in existing_ids:
        m = re.match(rf"^{prefix}(\d+)$", s)
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}{(max(nums) + 1) if nums else 1}"
