"""Mirror of SAEventPortalAgent's system_prompt from config.yaml.

The authoritative prompt is the ``instruction:`` field of the SAM
``apps[0].app_config`` block in ``config.yaml`` — that's what the agent
process loads at runtime. This module mirrors the same text for test
inspection (per the project's Decision 85 — keep a Python mirror of every
agent prompt so contributors don't have to dive into YAML) and as a
documentation artifact for contributors reading the plugin's source.

If the two diverge, the runtime YAML wins. Keep them in sync.
"""

from __future__ import annotations


SYSTEM_PROMPT = """\
You are SAEventPortalAgent — the live Event Portal Designer
interface for Solace Architect. You wrap the upstream
solace-event-portal-designer-mcp MCP server and use its tools to
list, create, update, and export application domains,
applications, events, schemas, and AsyncAPI specs against a
live Solace Cloud tenant.

See config.yaml for the full prompt (workflow, narration rules,
per-turn invariant, Completion Status protocol).
"""
