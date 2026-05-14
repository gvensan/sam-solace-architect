"""CI-only nightly URL health check.

Run with: pytest -m canonical_urls
Skipped in normal test runs (no network expected).
"""

import pytest


@pytest.mark.canonical_urls
def test_check_canonical_urls_runs_and_returns_data():
    """Smoke test of the check_canonical_urls tool (no network in Phase 1 skeleton)."""
    import asyncio
    from solace_architect_core.tools.grounding_tools import check_canonical_urls

    r = asyncio.run(check_canonical_urls())
    assert r.ok
    assert "url_count" in r.data
    assert "urls" in r.data
    assert r.data["url_count"] > 0, "canonical-sources.md should contain at least one URL"


@pytest.mark.canonical_urls
def test_every_url_in_canonical_sources_is_https_or_http():
    """All URLs from canonical-sources.md must be well-formed."""
    import asyncio
    from solace_architect_core.tools.grounding_tools import check_canonical_urls

    r = asyncio.run(check_canonical_urls())
    for url in r.data["urls"]:
        assert url.startswith(("http://", "https://")), f"bad URL form: {url!r}"


@pytest.mark.canonical_urls
def test_canonical_urls_are_in_allowlist_domains():
    """Sanity: most canonical URLs should be solace.com / docs.solace.com."""
    from urllib.parse import urlparse
    import asyncio
    from solace_architect_core.tools.grounding_tools import check_canonical_urls

    r = asyncio.run(check_canonical_urls())
    hosts = [urlparse(u).hostname for u in r.data["urls"]]
    solace_hosts = sum(1 for h in hosts if h and "solace" in h.lower())
    assert solace_hosts > len(hosts) * 0.5, \
        f"<=50% of canonical URLs are solace.com — recheck list (got {solace_hosts}/{len(hosts)})"
