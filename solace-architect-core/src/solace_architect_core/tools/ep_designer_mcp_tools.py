"""Event Portal Designer MCP wrappers (v2spec §5.6).

Phase 1: skeletons that return structured "not connected" responses, so SAProvisioningAgent
can be wired up end-to-end and tested for the opt-in/halt contract. Phase 5 replaces these
with real MCP calls.

OPT-IN ONLY — agent guards on intake.preferences.provision_event_portal before invoking.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

from .._storage import read_yaml, write_yaml
from ..schemas import ProvisionedObjectEntry
from .artifact_tools import ToolResult


def _mcp_available() -> bool:
    """Phase 1 stub: returns True iff SOLACE_API_TOKEN is set."""
    return bool(os.environ.get("SOLACE_API_TOKEN"))


def _base_url() -> str:
    return os.environ.get("SOLACE_API_BASE_URL", "https://api.solace.cloud")


# ---------- verify_tenant_access ----------

async def verify_tenant_access() -> ToolResult:
    """Always called first. v2spec §5.6 — NEVER silently skip on unavailability."""
    if not _mcp_available():
        return ToolResult(ok=True, data={
            "available": False,
            "token_scope": None,
            "base_url": _base_url(),
            "error": "SOLACE_API_TOKEN not set or EP Designer MCP not registered",
            "remediation": (
                "Set SOLACE_API_TOKEN (Designer Read+Write scope) and ensure the EP "
                "Designer MCP server is installed and registered with the SAM runtime."
            ),
        })
    # Phase 5: real probe via MCP list_application_domains(limit=1)
    return ToolResult(ok=True, data={
        "available": True,
        "token_scope": "Designer Read+Write",   # Phase 5: read from MCP probe response
        "base_url": _base_url(),
        "error": None,
    })


# ---------- helpers for content-match reuse ----------

def _hash_content(content) -> str:
    import json as _json
    canonical = _json.dumps(content, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------- list_* / create_* skeletons ----------

_NOT_IMPL = ToolResult(ok=False, error="Phase 5: not yet implemented — MCP call would go here")


async def list_application_domains() -> ToolResult: return _NOT_IMPL
async def create_application_domain(name: str, description: str = "") -> ToolResult: return _NOT_IMPL
async def list_schemas(domain: str | None = None) -> ToolResult: return _NOT_IMPL
async def create_schema(name: str, domain: str, content: dict) -> ToolResult: return _NOT_IMPL
async def create_schema_version(schema_id: str, version: str, content: dict) -> ToolResult: return _NOT_IMPL
async def list_events(domain: str | None = None) -> ToolResult: return _NOT_IMPL
async def create_event(name: str, domain: str, schema_version_id: str) -> ToolResult: return _NOT_IMPL
async def create_event_version(event_id: str, version: str, schema_version_id: str) -> ToolResult: return _NOT_IMPL
async def list_applications(domain: str | None = None) -> ToolResult: return _NOT_IMPL
async def create_application(name: str, domain: str, pub: list, sub: list) -> ToolResult: return _NOT_IMPL
async def export_application_asyncapi(application_id: str) -> ToolResult: return _NOT_IMPL


# ---------- record_provisioning_state ----------

async def record_provisioning_state(
    engagement_id: str, *, layer: str, name: str, ep_id: str, created: bool,
    metadata: Optional[dict] = None,
) -> ToolResult:
    """Append a row to provisioning/provisioned.yaml."""
    data = read_yaml(engagement_id, "provisioning/provisioned.yaml",
                     default={"provisioned": {"layers": {}, "errors": [], "status": "in-progress"}})
    layers = data["provisioned"].setdefault("layers", {})
    layers.setdefault(layer, []).append(
        ProvisionedObjectEntry(layer=layer, name=name, ep_id=ep_id, created=created,
                               metadata=metadata or {}).to_dict()
    )
    write_yaml(engagement_id, "provisioning/provisioned.yaml", data)
    return ToolResult(ok=True, data={"layer": layer, "name": name, "ep_id": ep_id, "created": created})
