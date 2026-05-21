"""Defensive guard around MCPTool._get_declaration.

When SAM hands an agent a tool list, ADK iterates each tool to build the
LLM request's function-declaration block. For MCP-backed tools (the
``solace-event-portal-designer-mcp`` server's catalog, for example), ADK
calls ``MCPTool._get_declaration()`` which runs the upstream MCP tool's
JSON Schema through ``_to_gemini_schema``.

If the MCP server returns a tool whose schema has unexpected shapes —
None values inside nested objects, missing ``type`` discriminators on
union members, malformed ``$ref`` targets — ``_to_gemini_schema``
raises ``TypeError: 'NoneType' object is not subscriptable`` (or
similar). That error propagates out of ``_get_declaration`` and aborts
the **entire LLM request preparation**, not just the one bad tool.

User-visible symptom: every chat to the agent that owns the broken MCP
tool fails with the generic "An unexpected error occurred…" bubble.
The agent never gets a chance to answer anything — even questions that
wouldn't have needed MCP tools at all.

This guard wraps ``MCPTool._get_declaration`` so a single bad MCP tool
degrades gracefully — that tool gets omitted from the LLM request, a
WARNING lands in sam.log naming the offender, and the rest of the
agent's toolset (including non-MCP tools and well-formed MCP tools)
continues to work.

Install per-agent from ``lifecycle.init()``::

    from solace_architect_core._mcp_schema_guard import install
    install()

The first call patches; subsequent calls (from sibling agents in the
same process) are no-ops via a sentinel attribute on ``MCPTool``.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


_SENTINEL_ATTR = "_sa_mcp_schema_guarded"


def install() -> None:
    """Idempotently install the MCPTool._get_declaration guard."""
    try:
        from google.adk.tools.mcp_tool.mcp_tool import MCPTool
    except ImportError:
        # google-adk's MCP support not present in this environment —
        # nothing to guard. Stay silent rather than warn; this is a
        # legitimate state for environments without MCP plugins.
        return

    if getattr(MCPTool, _SENTINEL_ATTR, False):
        return    # already patched in this process

    original = MCPTool._get_declaration

    def _safe_get_declaration(self):
        try:
            return original(self)
        except (TypeError, AttributeError, KeyError, ValueError) as exc:
            # Identify the offending tool as best we can. The MCPTool
            # instance exposes the upstream MCP tool spec under attrs
            # that differ across google-adk versions; probe a few common
            # locations so the warning is useful regardless of version.
            tool_name = (
                getattr(self, "name", None)
                or getattr(getattr(self, "_mcp_tool", None), "name", None)
                or "<unknown MCP tool>"
            )
            log.warning(
                "[mcp_schema_guard] Skipping MCP tool %r — its schema crashed "
                "_get_declaration with %s: %s. The agent will run without this "
                "tool in its LLM-visible tool list; other tools are unaffected. "
                "Root cause is typically a None value or missing type field in "
                "the MCP server's tool schema — check the MCP server's tool "
                "registration, or upgrade google-adk.",
                tool_name, type(exc).__name__, exc,
            )
            # Return None — ADK's append_tools loop tolerates None and
            # simply skips the tool. The agent loses access to this one
            # MCP capability but every other tool keeps working.
            return None

    MCPTool._get_declaration = _safe_get_declaration
    setattr(MCPTool, _SENTINEL_ATTR, True)
    log.info("[mcp_schema_guard] Installed defensive _get_declaration wrapper on MCPTool")


__all__ = ["install"]
