"""File-backed SSE replay buffer.

Persists per-session replay deques to disk so a gateway restart (or a
user closing the tab and returning much later, after the in-memory
session has been GC'd) can still replay the last N events to a
reconnecting client.

Design intent:

- **Snapshot, not append-only.** Each persistence pass writes the
  current deque snapshot to a single JSON file. The deque is already
  bounded (``replay_buffer_size``), so the file is bounded too — no
  rotation logic needed.
- **Snapshot on terminal events only.** Writing on every SSE frame
  would dominate latency under burst. Terminal events
  (``FinalResponse``, ``Error``, ``Task``) are the moments where the
  user's view-state matters most for resume; they're also infrequent
  enough that disk I/O is invisible.
- **Best-effort.** Any I/O failure is logged and swallowed. The SSE
  delivery path never raises on persistence errors.
- **Lives under ``__system__/sse_replay/``.** Reuses the storage root
  the rest of the gateway/core code already uses (``SA_STORAGE_ROOT``).
  Per-session files so a single corrupt write only loses one session's
  replay history.

The persistence is OPTIONAL. If the directory isn't writable or the
storage root isn't configured, the gateway logs once and degrades
silently to memory-only behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple


log = logging.getLogger(__name__)


_SAFE_SID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def _replay_dir() -> Path:
    """Resolve the directory where per-session snapshots live."""
    root = Path(os.environ.get("SA_STORAGE_ROOT", "./sa-artifacts")).resolve()
    return root / "__system__" / "sse_replay"


def _safe_path(session_id: str) -> Path | None:
    """Resolve the per-session snapshot path, rejecting unsafe ids.

    Session ids are gateway-generated (``chat-<eid>-<tab_id>``) so they
    should always be safe — but we belt-and-braces against any caller
    that smuggles a ``..`` or ``/`` through, since these strings end up
    in filesystem paths.
    """
    if not session_id or not _SAFE_SID_RE.match(session_id):
        return None
    return _replay_dir() / f"{session_id}.json"


def write_snapshot(session_id: str, replay: Iterable[Tuple[int, dict]]) -> bool:
    """Write a snapshot of the session's replay deque to disk.

    Returns True on success, False on any failure (and logs at WARNING).
    The replay iterable is materialised into a list of ``[ev_id, event]``
    pairs and dumped as a single JSON object so a half-written file is
    detected on load (json.loads fails) rather than silently parsed.

    Atomic-rename pattern: write to ``<file>.tmp`` then rename. Prevents
    a concurrent reader from seeing a truncated file mid-write.
    """
    path = _safe_path(session_id)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "session_id": session_id,
            "events": [[ev_id, event] for ev_id, event in replay],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot, default=str), encoding="utf-8")
        tmp.replace(path)
        return True
    except (OSError, TypeError, ValueError) as e:
        # OSError: disk full / permission / I/O. TypeError / ValueError:
        # json.dumps choked on a non-serializable value in the event
        # payload. Either way, persistence is best-effort.
        log.warning(
            "SSE replay snapshot write failed for session=%s path=%s: %s",
            session_id, path, e,
        )
        return False


def load_snapshot(session_id: str) -> List[Tuple[int, dict]]:
    """Load a previously persisted snapshot, or [] if none / corrupt.

    Returns the events in their stored order, which preserves the
    monotonic id sequence the SSE stream uses for Last-Event-Id replay.
    """
    path = _safe_path(session_id)
    if path is None or not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw)
        events = obj.get("events") or []
        out: List[Tuple[int, dict]] = []
        for row in events:
            if (
                isinstance(row, list)
                and len(row) == 2
                and isinstance(row[0], int)
                and isinstance(row[1], dict)
            ):
                out.append((row[0], row[1]))
        return out
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.warning(
            "SSE replay snapshot load failed for session=%s path=%s: %s — "
            "falling back to memory-only replay",
            session_id, path, e,
        )
        return []


DEFAULT_SNAPSHOT_TTL_SECONDS = 48 * 3600        # 48 hours of replayable history
DEFAULT_CLEANUP_INTERVAL_SECONDS = 3600         # rotate hourly


def cleanup_stale_snapshots(max_age_seconds: int = DEFAULT_SNAPSHOT_TTL_SECONDS) -> int:
    """Delete snapshot files older than ``max_age_seconds`` (default 48 hours).

    Called once on gateway startup AND on each tick of the periodic
    rotation task. Prevents unbounded growth of the snapshot directory
    from sessions that are never re-opened (the deque only persists;
    nothing else cleans up the file). Returns the number of files
    removed.

    Best-effort: any error during enumerate/unlink is logged at DEBUG
    and the function continues. A failure here must never block startup
    or the rotation loop.

    Live sessions are safe: every terminal-event snapshot rewrites the
    file (atomic rename), refreshing its mtime. Only files that haven't
    been touched in the TTL window are candidates for deletion.
    """
    import time
    base = _replay_dir()
    if not base.exists():
        return 0
    removed = 0
    cutoff = time.time() - max_age_seconds
    try:
        for entry in base.iterdir():
            if not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError as e:
                log.debug("SSE snapshot cleanup: skip %s (%s)", entry, e)
    except OSError as e:
        log.debug("SSE snapshot cleanup: dir read failed for %s (%s)", base, e)
    if removed:
        log.info("SSE snapshot cleanup: removed %d stale file(s) older than %ds", removed, max_age_seconds)
    return removed


async def run_periodic_cleanup(
    max_age_seconds: int = DEFAULT_SNAPSHOT_TTL_SECONDS,
    interval_seconds: int = DEFAULT_CLEANUP_INTERVAL_SECONDS,
) -> None:
    """Async loop that rotates stale snapshots every ``interval_seconds``.

    Designed to be scheduled with ``asyncio.create_task(...)`` on the
    gateway's HTTP loop and held as a task handle so ``_stop_listener``
    can cancel cleanly on shutdown. Loop body is wrapped in a broad
    try/except so a single cleanup failure (e.g. transient I/O error)
    doesn't kill the rotation for the rest of the process lifetime.

    Honours ``CancelledError`` and exits promptly when the gateway is
    shutting down — no need to time the loop around the interval.
    """
    log.info(
        "SSE snapshot rotation: every %ds, retaining %dh of history (TTL=%ds)",
        interval_seconds, max_age_seconds // 3600, max_age_seconds,
    )
    import asyncio
    try:
        while True:
            try:
                cleanup_stale_snapshots(max_age_seconds)
            except Exception:        # noqa: BLE001 — never let one bad tick stop the loop
                log.exception("SSE snapshot rotation: cleanup tick failed; continuing")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("SSE snapshot rotation: stopping (gateway shutdown)")
        raise


def is_terminal_event(event: dict) -> bool:
    """Should this event trigger a snapshot? Terminal events only.

    The contract matches the existing SSE write loop: any event marked
    ``final``, or whose ``type`` is ``FinalResponse`` / ``Error`` / a
    plain ``Task`` final, is a snapshot trigger.
    """
    if not isinstance(event, dict):
        return False
    if event.get("final") is True:
        return True
    t = event.get("type")
    return t in ("FinalResponse", "Error", "Task")
