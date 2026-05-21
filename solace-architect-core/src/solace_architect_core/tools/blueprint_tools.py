"""Blueprint + audience-pack rendering dispatcher (v2spec §5.5).

This module is the dispatcher. The actual HTML templates, CSS, and ROI calculator JS
live inside the ``solace-architect-blueprint`` plugin's ``report_generator/`` directory.

Phase 1: implements check_diagram_availability + assemble_zip. render_audience_pack
remains a thin dispatcher that the blueprint plugin's lifecycle.py wires up to its
local renderer at plugin load time.
"""

from __future__ import annotations

import io
import os
import zipfile
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .._storage import list_artifacts, read_text, safe_artifact_path, storage_root
from .._user_context import resolve_user_id as _resolve_user_id, scoped_user as _scoped_user
from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


# Diagram → required artifact (path glob) mapping
_DIAGRAM_REQUIREMENTS: dict[str, list[str]] = {
    "data-flow": ["integration/integration-map.yaml", "topic-design/topic-taxonomy.yaml"],
    "broker-topology": ["broker-select/broker-recommendation.yaml"],
    "topic-hierarchy": ["topic-design/topic-taxonomy.yaml"],
    "queue-subscriptions": ["topic-design/topic-taxonomy.yaml"],
    "protocol-stack": ["protocol-select/protocol-map.yaml"],
    "security-boundaries": ["reviews/security-review.yaml"],
    "failure-modes": ["reviews/ops-review.yaml"],
    "dlq-flow": ["topic-design/topic-taxonomy.yaml"],
    "sam-agent-topology": ["sam-design/sam-topology.yaml"],
    "auth-scope-flow": ["sam-design/sam-topology.yaml"],
    "dmr-topology": ["mesh-design/dmr-topology.yaml"],
    "ha-failover": ["ha-dr/ha-dr-design.yaml"],
    "dr-failover": ["ha-dr/ha-dr-design.yaml"],
    "mi-connectivity": ["integration/integration-map.yaml"],
    "migration-coexistence": ["migration/migration-plan.yaml"],
}


async def check_diagram_availability(
    engagement_id: str,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Which diagrams can be generated given current artifacts.

    ``user_id`` auto-resolves from ``tool_context`` so authenticated
    users get the right ``users/<uid>/<engagement>/`` namespace.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        existing = set(list_artifacts(engagement_id))
    available = []
    missing = []
    for diagram, requirements in _DIAGRAM_REQUIREMENTS.items():
        if any(req in existing for req in requirements):
            available.append(diagram)
        else:
            missing.append({"diagram": diagram, "missing_one_of": requirements})
    return ToolResult(ok=True, data={"available": available, "missing": missing})


def _load_report_packs() -> dict:
    text = (resources.files("solace_architect_core.configs") / "report-packs.yaml").read_text()
    data = yaml.safe_load(text)
    return data


def _matches_glob(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


def filter_artifacts_for_pack(engagement_id: str, audience: str) -> list[str]:
    """Apply the audience pack's filter rules from report-packs.yaml."""
    packs = _load_report_packs().get("packs", [])
    pack = next((p for p in packs if p.get("id") == audience), None)
    if not pack:
        return []
    existing = list_artifacts(engagement_id)

    included = set()
    for d in pack.get("dirs", []):
        for name in existing:
            if name.startswith(d.rstrip("/") + "/"):
                included.add(name)
    for f in pack.get("files", []):
        if f in existing:
            included.add(f)
    for g in pack.get("globs", []):
        for name in existing:
            if _matches_glob(name, g):
                included.add(name)

    for d in pack.get("exclude_dirs", []) or []:
        included = {n for n in included if not n.startswith(d.rstrip("/") + "/")}
    for f in pack.get("exclude_files", []) or []:
        included.discard(f)
    for g in pack.get("exclude_globs", []) or []:
        included = {n for n in included if not _matches_glob(n, g)}

    return sorted(included)


# Pluggable renderer — set by the blueprint plugin's lifecycle.py at load time.
_RENDERER: Optional[Callable] = None


def register_renderer(fn: Callable) -> None:
    """Register the HTML renderer (called by solace-architect-blueprint plugin)."""
    global _RENDERER
    _RENDERER = fn


def _pack_outputs(engagement_id: str, audience: str, format: str) -> list[Path]:
    """Resolve the on-disk paths a render would produce for this format."""
    targets: list[Path] = []
    if format in ("html", "both"):
        targets.append(safe_artifact_path(engagement_id, f"exports/{audience}.html"))
    if format in ("pdf", "both"):
        targets.append(safe_artifact_path(engagement_id, f"exports/{audience}.pdf"))
    return targets


def _max_source_mtime(engagement_id: str, artifacts: list[str]) -> float:
    """Latest mtime across the pack's source artifacts + report-packs.yaml.

    Used to decide whether a previously-rendered output is still fresh.
    Returns 0.0 if no source has a readable mtime (fallback = always render).
    """
    latest = 0.0
    for art in artifacts:
        try:
            path = safe_artifact_path(engagement_id, art)
            if path.exists():
                latest = max(latest, path.stat().st_mtime)
        except (ValueError, OSError):
            continue
    # Pack config itself — packed inside solace_architect_core; if it
    # changes, the cached file should be invalidated too.
    try:
        cfg_path = Path(str(resources.files("solace_architect_core.configs") / "report-packs.yaml"))
        if cfg_path.exists():
            latest = max(latest, cfg_path.stat().st_mtime)
    except Exception:
        pass
    return latest


@coerce_args
async def render_audience_pack(
    engagement_id: str, audience: str, format: str = "html",
    branding_overrides: Optional[dict] = None,
    force: bool = False,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Render an audience pack via the registered renderer.

    ``user_id`` auto-resolves from ``tool_context``. Both the artifact
    filtering (which reads the engagement's namespace) and the
    downstream renderer write under that namespace.

    Freshness cache: if every requested output file already exists AND
    is newer than the latest source artifact + the report-packs.yaml
    config, skip the renderer entirely and return the existing paths.
    Pass ``force=True`` (or set the SA_REPORTS_FORCE_RENDER env var) to
    bypass the cache — useful when the renderer's code changed but no
    engagement artifact did. Rendering a single pack with Mermaid
    pre-rendering can take 5-30s; the cache short-circuit avoids that
    when nothing's changed.
    """
    if _RENDERER is None:
        return ToolResult(ok=False, error=(
            "no renderer registered — install solace-architect-blueprint plugin "
            "or call blueprint_tools.register_renderer() during plugin init"
        ))
    if audience not in ("blueprint", "executive", "admin-ops", "security", "developers"):
        return ToolResult(ok=False, error=f"unknown audience: {audience!r}")
    if format not in ("html", "pdf", "both"):
        return ToolResult(ok=False, error=f"unknown format: {format!r}")

    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        artifacts = filter_artifacts_for_pack(engagement_id, audience)

        # Freshness cache check.
        force_env = bool(os.environ.get("SA_REPORTS_FORCE_RENDER"))
        if not force and not force_env:
            targets = _pack_outputs(engagement_id, audience, format)
            if targets and all(t.exists() for t in targets):
                latest_source = _max_source_mtime(engagement_id, artifacts)
                oldest_output = min(t.stat().st_mtime for t in targets)
                if oldest_output >= latest_source:
                    return ToolResult(ok=True, data={
                        "paths": [str(t) for t in targets],
                        "audience": audience,
                        "format": format,
                        "cache_hit": True,
                    })

        return await _RENDERER(
            engagement_id=engagement_id, audience=audience, format=format,
            artifacts=artifacts, branding_overrides=branding_overrides or {},
        )


async def assemble_zip(
    engagement_id: str, include_rendered_packs: bool = True,
    user_id: Optional[str] = None,
    tool_context: Any = None,
) -> ToolResult:
    """Package the engagement into a zip with V1-compatible layout + manifest.

    ``user_id`` auto-resolves from ``tool_context`` so the zip is read
    AND written under the same ``users/<uid>/<engagement>/`` namespace.
    """
    with _scoped_user(_resolve_user_id(user_id, tool_context)):
        # Resolve the engagement root via safe_artifact_path of a known-shape
        # path (the regex requires "<category>/<filename>"). The "exports/.zip"
        # target itself is a valid shape — use its parent's parent.
        try:
            engagement_root = safe_artifact_path(engagement_id, "exports/_probe").parent.parent
        except (ValueError, OSError) as e:
            return ToolResult(ok=False, error=f"invalid engagement: {e}")
        if not engagement_root.exists():
            return ToolResult(ok=False, error=f"engagement {engagement_id} not found")

        artifacts = list_artifacts(engagement_id)
        if not include_rendered_packs:
            artifacts = [a for a in artifacts if not a.startswith("exports/")]

        buffer = io.BytesIO()
        manifest = []
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for art in artifacts:
                try:
                    path = safe_artifact_path(engagement_id, art)
                except (ValueError, OSError):
                    continue
                if not path.exists():
                    continue
                # Binary-safe read so PDFs / ZIPs / images inside the engagement
                # don't blow up the UTF-8 decoder. read_text crashes on rendered
                # exports (audience-pack PDFs, the engagement-package zip from a
                # prior run, etc.) — read_bytes works for all file types.
                data = path.read_bytes()
                zf.writestr(f"{engagement_id}/{art}", data)
                manifest.append({"path": art, "size": len(data)})
            zf.writestr(f"{engagement_id}/manifest.yaml",
                        yaml.safe_dump({"engagement_id": engagement_id, "files": manifest},
                                       default_flow_style=False, sort_keys=False))

        out_path = safe_artifact_path(engagement_id, "exports/engagement-package.zip")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(buffer.getvalue())

    return ToolResult(ok=True, data={
        "zip_path": str(out_path),
        "files": len(manifest),
        "bytes": len(buffer.getvalue()),
    })
