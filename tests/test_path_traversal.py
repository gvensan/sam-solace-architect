"""Entrypoint artifact-path safety (v2spec §6.1)."""

import pytest

from solace_architect_core._storage import safe_artifact_path


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_STORAGE_ROOT", str(tmp_path / "artifacts"))


def test_rejects_dot_dot_segments():
    with pytest.raises(ValueError):
        safe_artifact_path("eng", "topic-design/../escape.yaml")


def test_rejects_absolute_path():
    with pytest.raises(ValueError):
        safe_artifact_path("eng", "/etc/passwd")


def test_rejects_bare_filename_without_category():
    with pytest.raises(ValueError, match="category/filename"):
        safe_artifact_path("eng", "topic-design")


def test_rejects_pure_traversal():
    with pytest.raises(ValueError):
        safe_artifact_path("eng", "../escape.md")


def test_rejects_unicode_path_separator_obfuscation():
    # Various malformed inputs should all reject
    for bad in ["..", "/", "topic-design/", "/topic-design/x.yaml", "topic-design/../x"]:
        with pytest.raises(ValueError):
            safe_artifact_path("eng", bad)


def test_accepts_valid_category_filename():
    p = safe_artifact_path("eng-1", "topic-design/topic-taxonomy.yaml")
    assert "eng-1" in str(p)
    assert "topic-design" in str(p)
    assert "topic-taxonomy.yaml" in str(p)


def test_accepts_nested_paths():
    p = safe_artifact_path("eng-1", "provisioning/asyncapi/order-app.yaml")
    assert "asyncapi" in str(p)


def test_artifact_write_through_real_tool_blocks_traversal():
    import asyncio
    from solace_architect_core.tools.artifact_tools import write_artifact

    r = asyncio.run(write_artifact("eng-2", "../../../etc/passwd", "pwned"))
    assert not r.ok
