"""File-based artifact storage for Phase 1.

This is a local backing store used in test-harness mode. In production deployment
under SAM, the same interface will be implemented against SAM's ArtifactService.

Layout under ``SA_STORAGE_ROOT`` (default: ./artifacts):

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


_LOCK = threading.RLock()


def storage_root() -> Path:
    """Resolve the root directory for engagement artifacts."""
    return Path(os.environ.get("SA_STORAGE_ROOT", "./artifacts")).resolve()


def safe_artifact_path(engagement_id: str, artifact_name: str) -> Path:
    """Validate + resolve an artifact path within an engagement's namespace.

    Rejects: paths containing ``..``, absolute paths, paths escaping the engagement
    namespace after normalization. Mirrors v2spec §6.1 path-traversal guard.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]+(/[a-zA-Z0-9_\-.]+)+$", artifact_name):
        raise ValueError(f"artifact_name must match 'category/filename' pattern: {artifact_name!r}")
    if ".." in artifact_name.split("/"):
        raise ValueError(f"artifact_name contains path traversal: {artifact_name!r}")

    root = storage_root() / engagement_id
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


def read_yaml(engagement_id: str, artifact_name: str, default: Any = None) -> Any:
    """Read a YAML artifact. Returns ``default`` if file doesn't exist."""
    try:
        return yaml.safe_load(read_text(engagement_id, artifact_name)) or default
    except FileNotFoundError:
        return default


def write_yaml(engagement_id: str, artifact_name: str, data: Any) -> Path:
    """Write a YAML artifact (canonical serialization)."""
    return write_text(engagement_id, artifact_name,
                      yaml.safe_dump(data, default_flow_style=False, sort_keys=False))


def list_artifacts(engagement_id: str, category: str | None = None) -> list[str]:
    """List artifact paths (relative to engagement) under ``category`` or all."""
    root = storage_root() / engagement_id
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
