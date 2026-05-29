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


# Bodies whose stripped text clears the content quality gate (A2): a real doc
# page is well over the min-length floor and carries no error/login marker.
_SERVICE_CLASSES_BODY = (
    "<html><body><h1>Service classes doc</h1>"
    "<p>Solace event broker services are offered in several service classes that "
    "determine connection scaling, sustained message throughput, spool size, and "
    "high availability. Choose a class from your expected client connection count "
    "and sustained message rate; Developer, Enterprise, and Mega map to increasing "
    "capacity envelopes.</p></body></html>"
)
_BROKER_CLASSES_BODY = (
    "<p>Event broker service classes define the capacity envelope for a Solace "
    "Cloud messaging service: maximum client connections, sustained and peak "
    "message rates, queue and spool limits, and whether the service runs as a "
    "high-availability triplet. Pick the smallest class that meets your sizing "
    "inputs and scale up as throughput grows.</p>"
)


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
    with _mock_urlopen(monkeypatch, _SERVICE_CLASSES_BODY) as calls:
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
    with _mock_urlopen(monkeypatch, _BROKER_CLASSES_BODY):
        r = asyncio.run(gt.fetch_canonical_source(topic))
    assert r.ok
    # The topic-driven fetch should have promoted the content into the store…
    promoted = gt._promoted_grounding_get(topic)
    assert promoted and "Event broker service classes" in promoted
    # …so load_grounding now serves it locally instead of recording a gap.
    lg = asyncio.run(gt.load_grounding(topic))
    assert lg.ok and "Event broker service classes" in lg.data


# --- fetched-content quality gate (A2) -------------------------------------

def test_fetch_rejects_soft_404_and_does_not_poison_cache(monkeypatch):
    url = "https://docs.solace.com/missing.htm"
    body = (
        "<html><body><h1>Page not found</h1>"
        "<p>The page you requested could not be found. It may have been moved or "
        "removed. Please check the URL and try again, or return to the Solace "
        "documentation home to search for the topic you were looking for. If you "
        "believe this is an error, contact your administrator for assistance.</p>"
        "</body></html>"
    )
    with _mock_urlopen(monkeypatch, body):
        r = asyncio.run(gt.fetch_canonical_source(url))
    assert not r.ok and "rejected" in r.error
    # A rejected fetch must NOT be persisted — a future run/project re-fetches.
    gt._FETCH_CACHE.clear()
    assert gt._disk_cache_get(url) is None


def test_fetch_rejects_near_empty_content(monkeypatch):
    url = "https://docs.solace.com/empty.htm"
    with _mock_urlopen(monkeypatch, "<html><body>   </body></html>"):
        r = asyncio.run(gt.fetch_canonical_source(url))
    assert not r.ok and "too short" in r.error


def test_fetch_revalidates_poisoned_disk_entry(monkeypatch):
    # A doc cached BEFORE the quality gate existed (here: a soft-404 stub) must
    # not be served from disk — the read-path re-gate drops it and a fresh,
    # gated network fetch replaces it.
    url = "https://docs.solace.com/Cloud/poisoned.htm"
    gt._disk_cache_put(url, "Page not found")  # pre-patch garbage on disk
    with _mock_urlopen(monkeypatch, _SERVICE_CLASSES_BODY) as calls:
        r = asyncio.run(gt.fetch_canonical_source(url))
    assert r.ok and "Service classes doc" in r.data["content"]
    assert calls["n"] == 1, "poisoned disk entry was served instead of re-fetching"
    # …and the disk entry has been overwritten with the good content.
    assert "Service classes doc" in gt._disk_cache_get(url).data["content"]


def test_load_grounding_rejects_poisoned_promoted_entry():
    # A promoted entry that fails the quality gate must not be served as
    # grounding; load_grounding falls through to the unknown-topic gap path.
    topic = "totally-unknown-topic"
    gt._promote_grounding(topic, "https://docs.solace.com/x.htm", "Access denied")
    r = asyncio.run(gt.load_grounding(topic))
    assert not r.ok and "unknown topic" in r.error


def test_read_grounding_file_reflects_edit_changing_size(tmp_path, monkeypatch):
    # Cache invalidation keys on (mtime_ns, size); a content edit that changes
    # size must be reflected even if the coarse second-mtime were unchanged.
    monkeypatch.setattr(gt, "_grounding_dir", lambda: tmp_path)
    f = tmp_path / "probe.md"
    f.write_text("alpha", encoding="utf-8")
    assert gt._read_grounding_file("probe.md") == "alpha"  # populates cache
    f.write_text("alpha-beta-gamma", encoding="utf-8")     # size changes
    assert gt._read_grounding_file("probe.md") == "alpha-beta-gamma"


# --- exact-heading-first section extraction (A3) ---------------------------

def test_extract_section_prefers_exact_heading_over_substring():
    md = (
        "# Event Portal Designer\nwrong section\n\n"
        "# Event Portal\nright section\n\n"
        "# Next\ntail\n"
    )
    out = gt._extract_section(md, "Event Portal")
    assert "right section" in out and "wrong section" not in out


def test_extract_section_substring_fallback_when_no_exact():
    md = "# Smart Topic Architecture\nbody text\n\n# Other\nx\n"
    out = gt._extract_section(md, "Topic Architecture")  # substring only
    assert "body text" in out


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
