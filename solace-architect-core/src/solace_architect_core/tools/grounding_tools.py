"""Grounding tools (v2spec §5.2).

Local file reads + Integration Hub catalog query + runtime web fetch (allowlisted).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import solace_architect_core

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
    """Extract a section of a grounding document by topic key."""
    if topic not in _TOPIC_MAP:
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


async def fetch_canonical_source(url_or_topic: str, timeout: int = 30) -> ToolResult:
    """Fetch a docs.solace.com / solace.com URL at runtime (allowlisted)."""
    url = url_or_topic
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

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "solace-architect-core/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # Strip HTML to text crudely (Phase 1 — replace with a proper parser later)
        text = re.sub(r"<script.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return ToolResult(ok=True, data={"url": url, "content": text[:50000]})
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        await record_grounding_gap(topic=url_or_topic, reason=f"fetch failed: {e}", agent="fetch_canonical_source")
        return ToolResult(ok=False, error=f"fetch failed: {e}")


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
