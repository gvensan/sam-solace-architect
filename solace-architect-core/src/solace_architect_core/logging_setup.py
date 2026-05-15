"""Opt-in per-plugin log file handler for Solace Architect plugins.

Solace Architect runs inside SAM's process, so its plugins are bound by the
process-wide logging config (SAM honors ``LOGGING_CONFIG_PATH`` and routes all
records into a single ``sam.log``). When operators want per-plugin log files
without editing SAM's structured logging config, each SA plugin's app module
calls :func:`attach_plugin_file_handler` at import time. The function is a
no-op unless ``SA_LOG_DIR`` is set, so other deployments of these plugins
inherit no surprise behavior.

Env vars:
    SA_LOG_DIR     Directory for per-plugin log files. Unset disables the
                   handler entirely.
    SA_LOG_LEVEL   Level applied to every SA plugin logger that opts in.
                   Defaults to ``INFO``.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 10
_FORMAT = "%(asctime)s | %(levelname)-5s | %(threadName)s | %(name)s | %(message)s"

_attached: set[str] = set()


def attach_plugin_file_handler(
    logger_name: str,
    *,
    filename: str | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    propagate: bool = True,
) -> None:
    """Attach a rotating file handler to ``logger_name`` when SA_LOG_DIR is set.

    Idempotent across re-imports — calling twice with the same ``logger_name``
    in the same process is a no-op. Records still propagate to the root logger
    by default, so they continue to appear in SAM's combined ``sam.log``.
    """
    log_dir = os.environ.get("SA_LOG_DIR")
    if not log_dir or logger_name in _attached:
        return

    target = Path(log_dir).expanduser() / (filename or f"{logger_name}.log")
    target.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        target,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))

    plugin_log = logging.getLogger(logger_name)
    plugin_log.addHandler(handler)
    plugin_log.setLevel(os.environ.get("SA_LOG_LEVEL", "INFO"))
    plugin_log.propagate = propagate

    _attached.add(logger_name)
