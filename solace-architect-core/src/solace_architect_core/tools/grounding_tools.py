"""Grounding tools (v2spec §5.2).

Local file reads + Integration Hub catalog query + runtime web fetch (allowlisted).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import solace_architect_core

from ._arg_coercion import coerce_args
from .artifact_tools import ToolResult


# Topic → (filename, optional section heading) mapping
_TOPIC_MAP: dict[str, tuple[str, Optional[str]]] = {
    "topic-architecture": ("solace-platform-reference.md", "Smart Topic Architecture"),
    "topics": ("solace-platform-reference.md", "Smart Topic Architecture"),
    "topic-design": ("solace-platform-reference.md", "Smart Topic Architecture"),  # SADomainAgent scope-name alias
    "dmr": ("solace-platform-reference.md", "Dynamic Message Routing"),
    "mesh": ("solace-platform-reference.md", "Dynamic Message Routing"),
    "mesh-design": ("solace-platform-reference.md", "Dynamic Message Routing"),  # SADomainAgent scope-name alias
    "micro-integrations": ("solace-platform-reference.md", "Micro-Integrations"),
    "integrations": ("solace-platform-reference.md", "Micro-Integrations"),
    "integration": ("solace-platform-reference.md", "Micro-Integrations"),  # SADomainAgent scope-name alias
    "sam": ("solace-platform-reference.md", "Solace Agent Mesh"),
    "agent-mesh": ("solace-platform-reference.md", "Solace Agent Mesh"),
    "sam-design": ("solace-platform-reference.md", "Solace Agent Mesh"),  # SADomainAgent scope-name alias
    "event-portal": ("solace-platform-reference.md", "Event Portal"),
    "security": ("solace-platform-reference.md", "Security and access control"),
    "ha-dr": ("solace-platform-reference.md", "HA and DR"),
    "protocols": ("solace-platform-reference.md", "Protocols"),
    "protocol-select": ("solace-platform-reference.md", "Protocols"),  # SADomainAgent scope-name alias
    "antipatterns": ("antipatterns.md", None),
    "reference-architectures": ("solace-reference-architectures.md", None),
    "naming-conventions": ("naming-conventions.md", None),
    "canonical-sources": ("solace-canonical-sources.md", None),
}

# Known-but-uncurated scopes — load_grounding short-circuits these to a
# directive "use fetch_canonical_source(URL)" error instead of logging a
# runtime gap every call. When the curated grounding is added, move the
# topic into _TOPIC_MAP and remove its entry here.
_KNOWN_FALLBACK_TOPICS: dict[str, str] = {
    "broker-select": "https://docs.solace.com/Solace-Cloud/event-broker-services.htm",
    "migration": "https://docs.solace.com/Messaging/Migration/migrating.htm",
}


def _grounding_dir() -> Path:
    """Return the path to the package's grounding/ directory.

    Uses ``__file__`` rather than ``importlib.resources.files`` because the latter
    returns a ``MultiplexedPath`` whose ``str()`` is the wrapped repr, not the
    underlying filesystem path — silently breaking every consumer that converts
    it to ``pathlib.Path``.
    """
    return Path(solace_architect_core.__file__).parent / "grounding"


def _extract_section(md_text: str, heading: str) -> str:
    """Extract a section from Markdown by H1/H2 heading text (case-insensitive)."""
    lines = md_text.splitlines()
    start = -1
    start_level = 0
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", ln)
        if m and heading.lower() in m.group(2).lower():
            start = i
            start_level = len(m.group(1))
            break
    if start < 0:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[i])
        if m and len(m.group(1)) <= start_level:
            end = i
            break
    return "\n".join(lines[start:end])


async def load_grounding(topic: str) -> ToolResult:
    """Extract a section of a grounding document by topic key.

    Two paths when ``topic`` isn't in ``_TOPIC_MAP``:

    1. **Known-fallback topics** (`_KNOWN_FALLBACK_TOPICS`) — scopes /
       categories we know have no curated grounding by design. Skip the
       runtime gap log (we already know it's a gap; logging every call
       is noise) and return a directive error pointing the LLM at the
       canonical docs.solace.com URL to use via ``fetch_canonical_source``.
    2. **Genuinely unmapped, unknown topic** — log to
       ``__system__/meta/grounding-gaps.jsonl`` and return the error
       listing available topics. These misses are signal worth keeping.
    """
    if topic not in _TOPIC_MAP:
        # Promoted grounding: a prior topic-driven fetch_canonical_source landed
        # this doc in the system store. Serve it directly — this is the round-trip
        # the agent would otherwise spend on a fetch tool call (and its consuming
        # turn). Survives across projects, so the second project never re-fetches.
        promoted = _promoted_grounding_get(topic)
        if promoted is not None:
            return ToolResult(ok=True, data=promoted)
        if topic in _KNOWN_FALLBACK_TOPICS:
            url = _KNOWN_FALLBACK_TOPICS[topic]
            return ToolResult(
                ok=False,
                error=(
                    f"no curated grounding for {topic!r}. "
                    f"Call fetch_canonical_source({url!r}) for live Solace docs on this topic."
                ),
            )
        available = sorted(_TOPIC_MAP)
        await record_grounding_gap(topic=topic, reason="topic not in topic-map", agent="load_grounding")
        return ToolResult(ok=False, error=f"unknown topic {topic!r}; available: {available}")

    filename, heading = _TOPIC_MAP[topic]
    path = _grounding_dir() / filename
    if not path.exists():
        await record_grounding_gap(topic=topic, reason=f"grounding file missing: {filename}", agent="load_grounding")
        return ToolResult(ok=False, error=f"grounding file not found: {filename}")

    text = path.read_text(encoding="utf-8")
    if heading:
        extracted = _extract_section(text, heading)
        if not extracted:
            await record_grounding_gap(topic=topic, reason=f"heading {heading!r} not found in {filename}", agent="load_grounding")
            return ToolResult(ok=False, error=f"heading {heading!r} not found in {filename}")
        return ToolResult(ok=True, data=extracted)
    return ToolResult(ok=True, data=text)


async def load_jargon_list() -> ToolResult:
    """Load grounding/jargon-list.json (used to gloss EDA/Solace terms on first use)."""
    path = _grounding_dir() / "jargon-list.json"
    if not path.exists():
        return ToolResult(ok=False, error="grounding/jargon-list.json not found")
    return ToolResult(ok=True, data=json.loads(path.read_text(encoding="utf-8")))


async def load_preamble() -> ToolResult:
    """Load grounding/agent-preamble.md — the shared accuracy / voice / naming / working-style
    discipline that every agent is bound by. Called once per agent session and prepended to
    the role-specific system prompt. Single source of truth (Decision 83); editing this file
    propagates the change to all agents without touching any agent's config.yaml."""
    path = _grounding_dir() / "agent-preamble.md"
    if not path.exists():
        await record_grounding_gap(topic="agent-preamble", reason="agent-preamble.md missing", agent="load_preamble")
        return ToolResult(ok=False, error="grounding/agent-preamble.md not found")
    return ToolResult(ok=True, data=path.read_text(encoding="utf-8"))


async def query_integration_hub(backend_system: str) -> ToolResult:
    """Search integration-hub-catalog.md for matches against ``backend_system``."""
    path = _grounding_dir() / "integration-hub-catalog.md"
    if not path.exists():
        return ToolResult(ok=False, error="grounding/integration-hub-catalog.md not found")
    text = path.read_text(encoding="utf-8")

    # Simple match: case-insensitive substring of the system name in each row.
    needle = backend_system.lower()
    matches = []
    for ln in text.splitlines():
        if needle in ln.lower() and "|" in ln:
            cells = [c.strip() for c in ln.split("|")]
            if len(cells) >= 3:
                matches.append({"raw_row": ln, "cells": cells})
    return ToolResult(ok=True, data=matches)


# Allowlisted domains for fetch_canonical_source
_ALLOWED_HOSTS = {"docs.solace.com", "solace.com", "www.solace.com"}

# In-process cache for fetch_canonical_source (keyed by resolved URL). Solace
# docs are stable within a run, so re-fetching the same URL across decisions /
# scopes — and the occasional duplicate call within one turn — is wasted network
# latency, and slow remote calls lengthen the LLM turn (raising stream-drop
# risk). Successes are cached for an hour; failures only briefly, so a duplicate
# call dedups (incl. a repeated 404) while a transient error still retries soon.
_FETCH_CACHE: dict[str, tuple[float, "ToolResult"]] = {}
_FETCH_TTL_OK = 3600.0
_FETCH_TTL_ERR = 120.0
_FETCH_CACHE_MAX = 256

# Persistent (cross-process, cross-project) fetch cache. The in-process cache
# above dies with the agent process and is per-process; the docs.solace.com
# pages it serves are stable for days. So we ALSO persist successful fetches to
# the system-scoped store (``__system__`` — shared across users/projects, see
# _storage._SHARED_ENGAGEMENTS), keyed by a hash of the resolved URL. A run
# next day, or in a different project, that needs the same doc reads it from
# disk instead of re-pulling — faster, and one fewer flaky external dependency.
#
# Disk entries use WALL-CLOCK time (not monotonic — which resets per process)
# and store only SUCCESSES: persisting a failure would let a transient
# docs.solace.com blip poison the cache for a whole day. TTL is operator-tunable
# via SA_FETCH_CACHE_TTL_S (default 24h); set 0 to disable the disk layer.
_FETCH_DISK_DIR = "meta/fetch-cache"
_PROMOTED_DIR = "meta/promoted-grounding"


def _fetch_disk_ttl() -> float:
    """Disk-cache TTL in seconds (env-overridable; 0 disables the disk layer)."""
    try:
        return float(os.environ.get("SA_FETCH_CACHE_TTL_S", "86400"))
    except (TypeError, ValueError):
        return 86400.0


def _url_cache_key(url: str) -> str:
    """A storage-safe filename for a URL (sha1 hex matches the artifact-name
    allowlist; the raw URL has ``://``, ``?`` etc. that ``safe_artifact_path``
    rejects). The url is also stored inside the payload for debuggability."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _disk_cache_get(url: str) -> "Optional[ToolResult]":
    """Return a fresh persisted fetch for ``url`` or None. Never raises."""
    ttl = _fetch_disk_ttl()
    if ttl <= 0:
        return None
    try:
        from .._storage import read_text
        raw = read_text("__system__", f"{_FETCH_DISK_DIR}/{_url_cache_key(url)}.json")
        rec = json.loads(raw)
        if (time.time() - float(rec.get("fetched_at", 0))) >= ttl:
            return None  # stale — caller will re-fetch and overwrite
        return ToolResult(ok=True, data={"url": rec["url"], "content": rec["content"],
                                         "cache": "disk"})
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return None


def _disk_cache_put(url: str, content: str) -> None:
    """Persist a successful fetch (best-effort; failures are swallowed)."""
    if _fetch_disk_ttl() <= 0:
        return
    try:
        from .._storage import write_text
        rec = {"url": url, "content": content, "fetched_at": time.time(),
               "fetched_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        write_text("__system__", f"{_FETCH_DISK_DIR}/{_url_cache_key(url)}.json",
                   json.dumps(rec, separators=(",", ":")))
    except OSError:
        pass


def _topic_slug(topic: str) -> str:
    """Normalise a topic to a storage-safe slug for the promoted-grounding store."""
    return re.sub(r"[^a-z0-9_-]+", "-", topic.strip().lower()).strip("-") or "topic"


def _promote_grounding(topic: str, url: str, content: str) -> None:
    """Promote a topic-driven fetch into the promoted-grounding store so a future
    ``load_grounding(topic)`` serves it locally — closing the grounding gap and,
    crucially, removing the fetch round-trip entirely next time. Best-effort."""
    if _fetch_disk_ttl() <= 0 or not content:
        return
    try:
        from .._storage import write_text
        rec = {"topic": topic, "url": url, "content": content, "fetched_at": time.time(),
               "fetched_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        write_text("__system__", f"{_PROMOTED_DIR}/{_topic_slug(topic)}.json",
                   json.dumps(rec, separators=(",", ":")))
    except OSError:
        pass


def _promoted_grounding_get(topic: str) -> Optional[str]:
    """Return promoted grounding content for ``topic`` if present and fresh."""
    ttl = _fetch_disk_ttl()
    if ttl <= 0:
        return None
    try:
        from .._storage import read_text
        raw = read_text("__system__", f"{_PROMOTED_DIR}/{_topic_slug(topic)}.json")
        rec = json.loads(raw)
        if (time.time() - float(rec.get("fetched_at", 0))) >= ttl:
            return None
        return rec.get("content") or None
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return None


def grounding_pack_for_scope(scope: str, max_chars: int = 4000) -> str:
    """A compact grounding excerpt for a design scope, for PRE-INJECTION into the
    worker kickoff so the worker usually needn't spend a ``load_grounding`` round
    trip (the request turn + the consume turn — the slow, stall-prone part).

    Sync (no LLM, no tool call) so the kickoff builder can call it directly.
    Returns "" when the scope has no curated grounding (the worker then loads /
    fetches as before). This is REFERENCE material, not a deliverable artifact —
    so an excerpt cap is fine, and the kickoff still PERMITS load_grounding /
    fetch_canonical_source for the full text. It therefore never presents partial
    content as complete-authoritative (unlike the artifact bundle, which must
    not be truncated-then-trusted)."""
    entry = _TOPIC_MAP.get(scope)
    if not entry:
        return ""  # broker-select / migration / unknown → fetch-based, no curated section
    filename, heading = entry
    try:
        path = _grounding_dir() / filename
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    section = (_extract_section(text, heading) if heading else text) or ""
    section = section.strip()
    if not section:
        return ""
    if len(section) > max_chars:
        section = section[:max_chars].rstrip() + \
            "\n…(excerpt — call load_grounding/fetch_canonical_source for the full reference)"
    return section


@coerce_args
async def fetch_canonical_source(url_or_topic: str, timeout: int = 30) -> ToolResult:
    """Fetch a docs.solace.com / solace.com URL at runtime (allowlisted).

    @coerce_args coerces ``timeout`` from string ("30") to int — ADK passes all
    tool args as strings, and ``urllib.request.urlopen(timeout=…)`` rejects
    strings with ``TypeError: 'str' object cannot be interpreted as an integer``.
    Observed crash 2026-05-23 08:34:40 mid broker-select scope.
    """
    # Belt-and-suspenders: @coerce_args normally makes ``timeout`` an int, but ADK has
    # slipped a string through twice (observed 2026-05-26) — coerce defensively here so a
    # str never reaches urllib's socket.settimeout (which raises TypeError on str).
    if not isinstance(timeout, int):
        try:
            timeout = int(str(timeout).strip() or 30)
        except (TypeError, ValueError):
            timeout = 30
    url = url_or_topic
    # Remember whether this call came in as a TOPIC (vs a raw URL) — only
    # topic-driven fetches get promoted into the grounding store on success.
    topic_in = None if url_or_topic.startswith(("http://", "https://")) else url_or_topic
    # If it doesn't look like a URL, look up in canonical-sources.md by header text.
    if not url.startswith(("http://", "https://")):
        path = _grounding_dir() / "solace-canonical-sources.md"
        if not path.exists():
            return ToolResult(ok=False, error="solace-canonical-sources.md missing")
        text = path.read_text(encoding="utf-8")
        # Find first URL on a line that mentions the topic text
        for ln in text.splitlines():
            if url_or_topic.lower() in ln.lower():
                m = re.search(r"https?://[\w.\-/?=&#%+]+", ln)
                if m:
                    url = m.group(0)
                    break
        if not url.startswith(("http://", "https://")):
            await record_grounding_gap(topic=url_or_topic, reason="no URL found for topic in canonical-sources.md", agent="fetch_canonical_source")
            return ToolResult(ok=False, error=f"no canonical URL for topic {url_or_topic!r}")

    # Enforce allowlist
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host not in _ALLOWED_HOSTS:
        return ToolResult(ok=False, error=f"host {host!r} not in allowlist {_ALLOWED_HOSTS}")

    # Serve from cache when fresh (keyed by resolved URL). monotonic clock so a
    # wall-clock adjustment can't wedge the TTL.
    now = time.monotonic()
    hit = _FETCH_CACHE.get(url)
    if hit is not None:
        ts, cached = hit
        if now - ts < (_FETCH_TTL_OK if cached.ok else _FETCH_TTL_ERR):
            return cached

    # Persistent disk layer (successes only): survives restarts and is shared
    # across users/projects, so the same stable doc is pulled from the network
    # at most once per TTL window regardless of how many runs need it.
    disk = _disk_cache_get(url)
    if disk is not None:
        _FETCH_CACHE[url] = (now, disk)  # warm the in-process layer
        if topic_in:
            _promote_grounding(topic_in, url, (disk.data or {}).get("content", ""))
        return disk

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "solace-architect-core/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # Strip HTML to text crudely (Phase 1 — replace with a proper parser later)
        text = re.sub(r"<script.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        content = text[:50000]
        result = ToolResult(ok=True, data={"url": url, "content": content})
        # Persist for cross-process / cross-project reuse, and promote a
        # topic-driven fetch so load_grounding can serve it locally next time.
        _disk_cache_put(url, content)
        if topic_in:
            _promote_grounding(topic_in, url, content)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        await record_grounding_gap(topic=url_or_topic, reason=f"fetch failed: {e}", agent="fetch_canonical_source")
        result = ToolResult(ok=False, error=f"fetch failed: {e}")

    # Cache the outcome (success or failure) in-process. Clear wholesale on
    # overflow — the URL space is tiny (allowlisted docs), so a simple cap beats
    # LRU bookkeeping. (Failures are NOT persisted to disk — see _disk_cache_put.)
    if len(_FETCH_CACHE) >= _FETCH_CACHE_MAX:
        _FETCH_CACHE.clear()
    _FETCH_CACHE[url] = (now, result)
    return result


async def record_grounding_gap(*, topic: str, reason: str, agent: str, suggested_fix: Optional[str] = None) -> ToolResult:
    """Append a gap entry to ``__system__/meta/grounding-gaps.jsonl``.

    The curated knowledge-gap inventory lives in
    ``grounding/gaps.md`` (read-only at runtime, hand-edited by humans
    as part of product planning). Runtime gaps that agents detect get
    appended to the system-scoped JSONL ledger instead — separate
    concerns, separate storage. Cross-engagement because gaps are about
    the project's grounding library, not any one engagement.
    """
    from .._storage import append_jsonl
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = {
        "recorded_at": ts,
        "topic": topic,
        "agent": agent,
        "reason": reason,
    }
    if suggested_fix:
        row["suggested_fix"] = suggested_fix
    try:
        append_jsonl("__system__", "meta/grounding-gaps.jsonl", row)
        return ToolResult(ok=True, data={"recorded_at": ts, "topic": topic})
    except OSError as e:
        return ToolResult(ok=False, error=f"could not record grounding gap: {e}")


async def check_canonical_urls() -> ToolResult:
    """CI-only: HEAD/GET every URL in solace-canonical-sources.md. Phase 1: skeleton."""
    path = _grounding_dir() / "solace-canonical-sources.md"
    if not path.exists():
        return ToolResult(ok=False, error="solace-canonical-sources.md missing")
    text = path.read_text(encoding="utf-8")
    urls = sorted(set(re.findall(r"https?://[\w.\-/?=&#%+]+", text)))
    return ToolResult(ok=True, data={"url_count": len(urls), "urls": urls,
                                     "note": "Phase 1 skeleton — actual HEAD/GET probe in Phase 6 hardening"})
