"""YAML safety tests — defensive read + write-time validation.

Cover the regression from 2026-05-21 where an LLM-emitted discovery-brief
contained an unquoted colon inside a string value (``driver: Modernize
ops. Key goals: …``). YAML parsed the second colon as a new mapping key,
the file landed on disk malformed, and the dashboard's overview endpoint
crashed with HTTP 500 every ~10s.

Two fixes verified here:
  1. ``safe_read_yaml`` returns ``default`` (and logs) on parse error
     instead of raising — so a single corrupt artifact degrades one tile
     gracefully rather than killing the whole dashboard.
  2. ``write_artifact`` now parses YAML content before persisting and
     refuses malformed input with a precise error pointing the agent at
     the most-likely fix (quote-the-string).
"""

from __future__ import annotations

import pytest

from solace_architect_core._storage import safe_read_yaml, read_yaml, write_text
from solace_architect_core.tools import artifact_tools


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


# ---------- safe_read_yaml ----------

def test_safe_read_yaml_returns_default_on_missing_file():
    """Missing file is not a parse error — same as read_yaml's behavior."""
    assert safe_read_yaml("eng-x", "meta/nope.yaml", default={"k": "v"}) == {"k": "v"}


def test_safe_read_yaml_returns_default_on_corrupt_yaml(caplog):
    """The 2026-05-21 regression: unquoted colon inside a string value."""
    write_text(
        "eng-corrupt",
        "discovery/discovery-brief.yaml",
        "project:\n  driver: Modernize ops. Key goals: more text.\n",
    )
    # read_yaml raises on this (legacy behavior — agent tools want to know).
    import yaml as _yaml
    with pytest.raises(_yaml.YAMLError):
        read_yaml("eng-corrupt", "discovery/discovery-brief.yaml")

    # safe_read_yaml swallows it and returns default — what the dashboard wants.
    import logging
    with caplog.at_level(logging.WARNING):
        result = safe_read_yaml(
            "eng-corrupt", "discovery/discovery-brief.yaml",
            default={"safe": True},
        )
    assert result == {"safe": True}
    assert any("malformed" in rec.message for rec in caplog.records), (
        "expected a warning log naming the malformed artifact"
    )


def test_safe_read_yaml_returns_parsed_content_on_valid_yaml():
    """Happy path — same as read_yaml when the file is well-formed."""
    write_text("eng-ok", "meta/decisions.yaml", "decisions:\n  - id: D1\n")
    result = safe_read_yaml("eng-ok", "meta/decisions.yaml", default={"decisions": []})
    assert result == {"decisions": [{"id": "D1"}]}


# ---------- write_artifact YAML validation ----------

@pytest.mark.asyncio
async def test_write_artifact_rejects_malformed_yaml():
    """The regression at the source: write_artifact must refuse a YAML file
    whose content doesn't parse, with a clear error pointing at the line."""
    bad_brief = (
        "project:\n"
        "  name: airline-passenger-monitor\n"
        "  driver: Modernize ops. Key goals: reduce delays.\n"
    )
    r = await artifact_tools.write_artifact(
        "eng-bad", "discovery/discovery-brief.yaml", bad_brief,
    )
    assert not r.ok
    assert r.error == "pre-write validation failed"
    yaml_check = r.error_detail["yaml_check"]
    assert not yaml_check["ok"]
    # The error message must guide the agent toward the fix.
    msg = yaml_check["violations"][0]["detail"]
    assert "unquoted colon" in msg or "mapping key" in msg or "YAML parse failed" in msg
    assert "double quotes" in msg, "should suggest quoting the value"


@pytest.mark.asyncio
async def test_write_artifact_accepts_well_formed_yaml():
    """Happy path — valid YAML lands on disk."""
    good_brief = (
        "project:\n"
        "  name: airline-passenger-monitor\n"
        '  driver: "Modernize ops. Key goals: reduce delays."\n'
    )
    r = await artifact_tools.write_artifact(
        "eng-good", "discovery/discovery-brief.yaml", good_brief,
    )
    assert r.ok, r.error_detail


@pytest.mark.asyncio
async def test_write_artifact_skips_yaml_check_for_non_yaml_files():
    """A .md file with `key:` in it must NOT be rejected — that's not a YAML."""
    md = "# Discovery\n\nKey goals: reduce delays.\n"
    r = await artifact_tools.write_artifact(
        "eng-md", "discovery/discovery-report.md", md,
    )
    assert r.ok, r.error_detail


@pytest.mark.asyncio
async def test_write_artifact_does_not_persist_when_yaml_invalid():
    """Belt-and-braces: refused writes must not leave a file on disk."""
    from solace_architect_core._storage import safe_artifact_path
    bad = "project: { name: x, broken: }\n"  # incomplete flow mapping
    r = await artifact_tools.write_artifact(
        "eng-no-persist", "meta/whatever.yaml", bad,
    )
    if r.ok:
        pytest.skip("PyYAML accepts this; not a useful regression target")
    path = safe_artifact_path("eng-no-persist", "meta/whatever.yaml")
    assert not path.exists(), "file must not be written when validation fails"
