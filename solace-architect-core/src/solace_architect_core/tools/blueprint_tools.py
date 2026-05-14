"""Blueprint + audience-pack rendering dispatcher (v2spec §5.5).

This module is the dispatcher. The actual HTML templates, CSS, and ROI calculator JS
live inside the ``solace-architect-blueprint`` plugin's ``report_generator/`` directory.

Phase 1: implements check_diagram_availability + assemble_zip. render_audience_pack
remains a thin dispatcher that the blueprint plugin's lifecycle.py wires up to its
local renderer at plugin load time.
"""

from __future__ import annotations

import io
import zipfile
from importlib import resources
from pathlib import Path
from typing import Callable, Optional

import yaml

from .._storage import list_artifacts, read_text, safe_artifact_path, storage_root
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


async def check_diagram_availability(engagement_id: str) -> ToolResult:
    """Which diagrams can be generated given current artifacts."""
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


async def render_audience_pack(
    engagement_id: str, audience: str, format: str = "html",
    branding_overrides: Optional[dict] = None,
) -> ToolResult:
    """Render an audience pack via the registered renderer."""
    if _RENDERER is None:
        return ToolResult(ok=False, error=(
            "no renderer registered — install solace-architect-blueprint plugin "
            "or call blueprint_tools.register_renderer() during plugin init"
        ))
    if audience not in ("blueprint", "executive", "admin-ops", "security", "developers"):
        return ToolResult(ok=False, error=f"unknown audience: {audience!r}")
    if format not in ("html", "pdf", "both"):
        return ToolResult(ok=False, error=f"unknown format: {format!r}")

    artifacts = filter_artifacts_for_pack(engagement_id, audience)
    return await _RENDERER(
        engagement_id=engagement_id, audience=audience, format=format,
        artifacts=artifacts, branding_overrides=branding_overrides or {},
    )


async def assemble_zip(engagement_id: str, include_rendered_packs: bool = True) -> ToolResult:
    """Package the engagement into a zip with V1-compatible layout + manifest."""
    root = storage_root() / engagement_id
    if not root.exists():
        return ToolResult(ok=False, error=f"engagement {engagement_id} not found")

    artifacts = list_artifacts(engagement_id)
    if not include_rendered_packs:
        artifacts = [a for a in artifacts if not a.startswith("exports/")]

    buffer = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for art in artifacts:
            content = read_text(engagement_id, art)
            zf.writestr(f"{engagement_id}/{art}", content)
            manifest.append({"path": art, "size": len(content.encode("utf-8"))})
        zf.writestr(f"{engagement_id}/manifest.yaml",
                    yaml.safe_dump({"engagement_id": engagement_id, "files": manifest},
                                   default_flow_style=False, sort_keys=False))

    # Write the zip into the engagement's exports/ namespace too
    out_path = safe_artifact_path(engagement_id, "exports/engagement-package.zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buffer.getvalue())

    return ToolResult(ok=True, data={
        "zip_path": str(out_path),
        "files": len(manifest),
        "bytes": len(buffer.getvalue()),
    })
