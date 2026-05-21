"""solace-architect-domain plugin — Solace platform domain expert — 9 design scopes (topic, broker, SAM, protocol, mesh, HA/DR, migration, integration, Event Portal)."""

from solace_architect_core.logging_setup import attach_plugin_file_handler

# Opt-in per-plugin log file (writes ${SA_LOG_DIR}/<package>.log when SA_LOG_DIR is set).
attach_plugin_file_handler(__name__)

__version__ = "0.1.0"
