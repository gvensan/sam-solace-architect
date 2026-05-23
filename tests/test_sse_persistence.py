"""Smoke tests for the SSE replay persistence + rotation helpers."""

from __future__ import annotations

import asyncio
import json
import os
import time

import pytest


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Point SA_STORAGE_ROOT at a fresh tmp dir so each test sees a clean state."""
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    yield tmp_path


def test_write_then_load_roundtrip(isolated_storage):
    from solace_architect_webui_entrypoint._sse_persistence import (
        load_snapshot, write_snapshot,
    )
    events = [(1, {"type": "TaskStatusUpdateEvent"}), (2, {"type": "FinalResponse"})]
    assert write_snapshot("chat-eng-1-tab", events)
    loaded = load_snapshot("chat-eng-1-tab")
    assert loaded == events


def test_unsafe_session_id_rejected(isolated_storage):
    from solace_architect_webui_entrypoint._sse_persistence import (
        load_snapshot, write_snapshot,
    )
    for bad in ("../escape", "/abs/path", "chat with space", "with;semi"):
        assert write_snapshot(bad, [(1, {})]) is False
        assert load_snapshot(bad) == []


def test_corrupt_snapshot_returns_empty(isolated_storage):
    from solace_architect_webui_entrypoint._sse_persistence import (
        _replay_dir, load_snapshot,
    )
    _replay_dir().mkdir(parents=True)
    (_replay_dir() / "chat-bad.json").write_text("{not valid json")
    assert load_snapshot("chat-bad") == []


def test_load_validates_row_shape(isolated_storage):
    """Rows that aren't [int, dict] pairs must be skipped, not crash callers."""
    from solace_architect_webui_entrypoint._sse_persistence import (
        _replay_dir, load_snapshot,
    )
    _replay_dir().mkdir(parents=True)
    (_replay_dir() / "chat-mixed.json").write_text(json.dumps({
        "session_id": "chat-mixed",
        "events": [
            [1, {"good": True}],
            ["not-int", {}],            # bad — id is not int
            [2, "not-a-dict"],           # bad — payload is not dict
            [3, {"also_good": True}],
        ],
    }))
    loaded = load_snapshot("chat-mixed")
    assert loaded == [(1, {"good": True}), (3, {"also_good": True})]


def test_is_terminal_event():
    from solace_architect_webui_entrypoint._sse_persistence import is_terminal_event
    assert is_terminal_event({"type": "FinalResponse"}) is True
    assert is_terminal_event({"type": "Error"}) is True
    assert is_terminal_event({"type": "Task"}) is True
    assert is_terminal_event({"final": True}) is True
    assert is_terminal_event({"type": "TaskStatusUpdateEvent"}) is False
    assert is_terminal_event({}) is False
    assert is_terminal_event(None) is False        # type: ignore[arg-type]


def test_cleanup_removes_stale(isolated_storage):
    """Files older than ttl get removed; fresh ones stay."""
    from solace_architect_webui_entrypoint._sse_persistence import (
        _replay_dir, cleanup_stale_snapshots, write_snapshot,
    )
    write_snapshot("chat-fresh", [(1, {})])
    write_snapshot("chat-stale", [(1, {})])
    # Backdate the stale file 25 hours ago
    stale = _replay_dir() / "chat-stale.json"
    long_ago = time.time() - 25 * 3600
    os.utime(stale, (long_ago, long_ago))
    removed = cleanup_stale_snapshots(max_age_seconds=24 * 3600)
    assert removed == 1
    assert (_replay_dir() / "chat-fresh.json").exists()
    assert not stale.exists()


def test_cleanup_handles_missing_dir(isolated_storage):
    """Cleanup must never raise even when the directory doesn't exist yet."""
    from solace_architect_webui_entrypoint._sse_persistence import cleanup_stale_snapshots
    assert cleanup_stale_snapshots() == 0


@pytest.mark.asyncio
async def test_periodic_cleanup_is_cancelable(isolated_storage):
    """run_periodic_cleanup must wake up from sleep on CancelledError."""
    from solace_architect_webui_entrypoint._sse_persistence import run_periodic_cleanup
    task = asyncio.create_task(
        run_periodic_cleanup(max_age_seconds=3600, interval_seconds=3600),
    )
    # Yield to let the task enter its sleep
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_periodic_cleanup_actually_runs_cleanup(isolated_storage, monkeypatch):
    """A single tick of the periodic loop should remove stale files."""
    from solace_architect_webui_entrypoint._sse_persistence import (
        _replay_dir, run_periodic_cleanup, write_snapshot,
    )
    write_snapshot("chat-old", [(1, {})])
    old = _replay_dir() / "chat-old.json"
    long_ago = time.time() - 25 * 3600
    os.utime(old, (long_ago, long_ago))
    # Make the loop sleep for ~forever so we just see the first tick
    task = asyncio.create_task(
        run_periodic_cleanup(max_age_seconds=24 * 3600, interval_seconds=3600),
    )
    # Give the body one cycle, then cancel
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert not old.exists(), "First-tick cleanup didn't run before sleep"
