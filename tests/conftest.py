"""Shared pytest fixtures for the Solace Architect test suite."""

import pytest

# TODO(Phase 1+): add fakes for SAM ArtifactService, SessionService,
# fakes for the EP Designer MCP, and helpers for loading the three
# reference-architecture fixtures.


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "canonical_urls: CI-only URL health-check (nightly)")
    config.addinivalue_line("markers", "slow: requires sam run + LLM API key")
