"""solace-architect-blueprint plugin — Final blueprint assembly + 5-audience-pack rendering (HTML + PDF via WeasyPrint) + zip export. Ships the ported V1 HTML report generator."""

from solace_architect_core.logging_setup import attach_plugin_file_handler

# Opt-in per-plugin log file (writes ${SA_LOG_DIR}/<package>.log when SA_LOG_DIR is set).
attach_plugin_file_handler(__name__)

__version__ = "0.1.0"
