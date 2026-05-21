"""solace-architect-event-portal plugin — SAEventPortalAgent.

Wraps the ``solace-event-portal-designer-mcp`` MCP server (stdio,
launched via ``uvx``) and exposes its tools to SAM as a discoverable
peer agent. Handles application domains, applications, events,
schemas, and AsyncAPI exports against a live Solace Cloud tenant.

Token + region setup lives in README.md.
"""

from solace_architect_core.logging_setup import attach_plugin_file_handler

# Opt-in per-plugin log file (writes ${SA_LOG_DIR}/<package>.log when SA_LOG_DIR is set).
attach_plugin_file_handler(__name__)

__version__ = "0.1.0"
