"""Persistent fetch cache + grounding promotion (grounding_tools).

The in-process fetch cache dies with the agent process and is per-process;
docs.solace.com pages are stable for days. These tests pin the persistent disk
layer (system-scoped, survives restart, shared cross-project) and the
promotion path that lets ``load_grounding(topic)`` serve a previously fetched
doc locally — removing the fetch round-trip entirely next time.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager

import pytest

import solace_architect_core.tools.grounding_tools as gt


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """Point all __system__ writes at a temp root and reset the in-process cache."""
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("SA_FETCH_CACHE_TTL_S", "86400")
    gt._FETCH_CACHE.clear()
    yield
    gt._FETCH_CACHE.clear()


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


@contextmanager
def _mock_urlopen(monkeypatch, body: str):
    """Replace urlopen with a counter so we can assert network hits."""
    calls = {"n": 0}
    def fake(req, timeout=30):
        calls["n"] += 1
        return _FakeResp(body.encode("utf-8"))
    monkeypatch.setattr(gt.urllib.request, "urlopen", fake)
    yield calls


# --- disk-cache layer ------------------------------------------------------

def test_disk_cache_put_then_get_roundtrip():
    url = "https://docs.solace.com/x.htm"
    assert gt._disk_cache_get(url) is None  # cold
    gt._disk_cache_put(url, "hello world")
    hit = gt._disk_cache_get(url)
    assert hit is not None and hit.ok
    assert hit.data["content"] == "hello world"
    assert hit.data["cache"] == "disk"


def test_disk_cache_respects_ttl(monkeypatch):
    url = "https://docs.solace.com/y.htm"
    gt._disk_cache_put(url, "stale-ish")
    # Force the entry to look old by shrinking the TTL to ~0.
    monkeypatch.setenv("SA_FETCH_CACHE_TTL_S", "0.001")
    time.sleep(0.005)
    assert gt._disk_cache_get(url) is None


def test_disk_layer_disabled_when_ttl_zero(monkeypatch):
    url = "https://docs.solace.com/z.htm"
    gt._disk_cache_put(url, "content")
    monkeypatch.setenv("SA_FETCH_CACHE_TTL_S", "0")
    assert gt._disk_cache_get(url) is None  # disabled → never serves


# --- fetch_canonical_source end-to-end (network mocked) --------------------

def test_fetch_persists_and_second_run_skips_network(monkeypatch):
    url = "https://docs.solace.com/Cloud/service-classes.htm"
    with _mock_urlopen(monkeypatch, "<html><body>Service classes doc</body></html>") as calls:
        r1 = asyncio.run(gt.fetch_canonical_source(url))
        assert r1.ok and "Service classes doc" in r1.data["content"]
        assert calls["n"] == 1
        # Simulate a fresh process: drop the in-process cache. The disk layer
        # must serve the second call without another network hit.
        gt._FETCH_CACHE.clear()
        r2 = asyncio.run(gt.fetch_canonical_source(url))
        assert r2.ok and r2.data.get("cache") == "disk"
        assert calls["n"] == 1, "second run re-hit the network despite a warm disk cache"


# --- grounding promotion ---------------------------------------------------

def test_topic_fetch_promotes_and_load_grounding_serves_it(monkeypatch):
    # 'feature index' resolves to a docs.solace.com URL via canonical-sources.md
    # and isn't in the curated topic-map, so it exercises the promotion path.
    topic = "feature index"
    with _mock_urlopen(monkeypatch, "<p>Event broker service classes</p>"):
        r = asyncio.run(gt.fetch_canonical_source(topic))
    assert r.ok
    # The topic-driven fetch should have promoted the content into the store…
    promoted = gt._promoted_grounding_get(topic)
    assert promoted and "Event broker service classes" in promoted
    # …so load_grounding now serves it locally instead of recording a gap.
    lg = asyncio.run(gt.load_grounding(topic))
    assert lg.ok and "Event broker service classes" in lg.data


def test_load_grounding_unpromoted_fallback_still_directs_to_fetch():
    # Without a promoted entry, a known-fallback topic returns the fetch
    # directive (unchanged behaviour) rather than a false hit.
    r = asyncio.run(gt.load_grounding("broker-select"))
    assert not r.ok and "fetch_canonical_source" in r.error


def test_topic_slug_is_storage_safe():
    assert gt._topic_slug("Broker Select / v2") == "broker-select-v2"
    assert gt._topic_slug("  ") == "topic"


# ── grounding pre-injection pack (token lever) ───────────────────────────────

def test_grounding_pack_returns_curated_section_for_a_scope():
    # topic-design maps to a curated section in solace-platform-reference.md.
    pack = gt.grounding_pack_for_scope("topic-design")
    assert pack and isinstance(pack, str) and len(pack) > 0


def test_grounding_pack_empty_for_fetch_only_scope():
    # broker-select / migration have no curated section (fetch-based) → "".
    assert gt.grounding_pack_for_scope("broker-select") == ""
    assert gt.grounding_pack_for_scope("migration") == ""
    assert gt.grounding_pack_for_scope("nonsense-scope") == ""


def test_grounding_pack_caps_excerpt_and_keeps_escape_hatch():
    pack = gt.grounding_pack_for_scope("topic-design", max_chars=200)
    assert len(pack) <= 400  # cap + the short "excerpt — call …" suffix
    assert "excerpt" in pack and "load_grounding" in pack  # full-text escape hatch
