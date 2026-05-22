"""CI drift test — every SA agent plugin's lifecycle.init must install the
telemetry monkey-patch.

The patch (``solace_architect_core._sam_telemetry_patch.install``) wraps
SAM's ``after_model_callback`` chain so every LLM round-trip lands in
``meta/telemetry/llm-calls.jsonl`` and surfaces on the Usage dashboard.
The install is idempotent across plugins — multiple calls are safe — but
ONE missing call means that agent's token usage silently disappears from
the dashboard. No exception, no error log.

This test reads each agent's ``lifecycle.py`` with AST (no SAM imports
needed, no plugin side effects) and asserts:
  1. The module defines a top-level ``init`` function.
  2. It imports ``install`` from ``solace_architect_core._sam_telemetry_patch``.
  3. The imported symbol is actually called inside ``init`` (under
     whatever alias the agent chose).

Gateway-only plugins (webui-entrypoint today) don't run LLMs and are
skipped via a small allowlist. A floor on the discovered-agent count
catches the failure mode where someone accidentally removes ``init`` from
an agent's lifecycle.py — the AST-skip alone would silently pass.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
TELEMETRY_MODULE = "solace_architect_core._sam_telemetry_patch"
INSTALL_NAME = "install"

# Plugins that legitimately do NOT run LLMs and therefore have no
# telemetry to wire. Today only the WebUI gateway plugin — it serves
# HTTP/SSE and dispatches to agents but isn't itself an agent.
GATEWAY_PLUGINS = {"solace-architect-webui-entrypoint"}

# Minimum agent-plugin count we expect to discover. If the project drops
# below this, something has been removed or the discovery glob has
# regressed — the floor surfaces both. Adjust when an agent is genuinely
# retired (then update the count + the comment to explain which).
MIN_AGENT_PLUGINS = 10  # blueprint, discovery, domain, event-portal,
                       # orchestrator, validation + 4 reviewers


def _discover_agent_lifecycles() -> list[tuple[str, Path]]:
    """Return (plugin_name, lifecycle.py path) for every agent plugin."""
    out: list[tuple[str, Path]] = []
    for plugin_dir in sorted(PLUGINS_ROOT.glob("solace-architect-*")):
        if plugin_dir.name in GATEWAY_PLUGINS:
            continue
        candidates = list(plugin_dir.glob("src/*/lifecycle.py"))
        if not candidates:
            continue
        # Each agent has exactly one lifecycle.py; if more appear later
        # the test loop covers all of them.
        for lifecycle in candidates:
            out.append((plugin_dir.name, lifecycle))
    return out


_LIFECYCLES = _discover_agent_lifecycles()


def test_discovered_at_least_min_agents():
    """Floor check — catches the case where the glob silently skips
    plugins or someone deletes lifecycle.py from an agent.
    """
    assert len(_LIFECYCLES) >= MIN_AGENT_PLUGINS, (
        f"Expected ≥{MIN_AGENT_PLUGINS} agent lifecycle.py files, "
        f"discovered {len(_LIFECYCLES)}. Either an agent was removed "
        f"(update MIN_AGENT_PLUGINS + the comment in this test) or the "
        f"discovery glob has regressed. Discovered: "
        f"{[name for name, _ in _LIFECYCLES]}"
    )


@pytest.mark.parametrize(
    "plugin_name,lifecycle_path",
    _LIFECYCLES,
    ids=[name for name, _ in _LIFECYCLES],
)
def test_plugin_installs_telemetry_patch(plugin_name: str, lifecycle_path: Path):
    """Each agent's lifecycle.init must import + call the telemetry
    install. Without it, this agent's LLM calls silently never reach
    meta/telemetry/llm-calls.jsonl.
    """
    tree = ast.parse(lifecycle_path.read_text(encoding="utf-8"))

    init_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "init":
            init_node = node
            break
    assert init_node is not None, (
        f"{plugin_name}/lifecycle.py has no top-level `def init`. SAM's "
        "agent_init_function hook needs one as the trigger for plugin-boot work."
    )

    # Walk the WHOLE module (some plugins import inside init to defer
    # core loading until SAM actually starts the agent) and look for
    # `from solace_architect_core._sam_telemetry_patch import install [as <alias>]`.
    install_alias: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == TELEMETRY_MODULE:
            for alias in node.names:
                if alias.name == INSTALL_NAME:
                    install_alias = alias.asname or alias.name
                    break
        if install_alias is not None:
            break
    assert install_alias is not None, (
        f"{plugin_name}/lifecycle.py does not import `{INSTALL_NAME}` from "
        f"`{TELEMETRY_MODULE}`. Without the import the patch never installs "
        "and this agent's token usage vanishes from the Usage dashboard."
    )

    # Confirm the imported symbol is actually CALLED inside init —
    # the import alone does nothing.
    called = False
    for node in ast.walk(init_node):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == install_alias:
            called = True
            break
        # Also accept the attribute form `_sam_telemetry_patch.install()`
        if isinstance(f, ast.Attribute) and f.attr == INSTALL_NAME:
            called = True
            break
    assert called, (
        f"{plugin_name}/lifecycle.py imports `{INSTALL_NAME}` (as "
        f"`{install_alias}`) but never calls it inside `init`. The import "
        "alone does nothing — telemetry won't be wired for this agent."
    )
