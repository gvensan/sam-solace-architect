#!/usr/bin/env bash
# refresh-plugin.sh — re-install a Solace Architect plugin from GitHub
# and refresh its SAM-project config.
#
# Pip caches already-installed package versions, so `sam plugin install`
# / `pip install` no-op when the version string hasn't changed even if
# the upstream source moved forward. This script wraps the force-reinstall
# incantation AND re-runs `sam plugin add` so the local
# configs/gateways/<plugin>.yaml stays in sync with the wheel's config.
#
# Pass the plugin name exactly as it appears as a subdirectory in the
# plugins repo (e.g. solace-architect-webui-entrypoint). The same name
# is used as the SAM component name.
#
# Usage:
#   ./refresh-plugin.sh <plugin> [--ref <branch-or-sha>] [--skip-add]
#
# Examples:
#   ./refresh-plugin.sh solace-architect-webui-entrypoint
#   ./refresh-plugin.sh solace-architect-discovery --ref develop
#   ./refresh-plugin.sh solace-architect-webui-entrypoint --skip-add
#
# Environment:
#   SA_PLUGINS_REPO  Override the upstream git URL (default: this repo).

set -euo pipefail

REPO_URL="${SA_PLUGINS_REPO:-https://github.com/gvensan/sam-solace-architect-agents.git}"

# Prefer the venv tooling that update.sh discovered. When run directly
# (without update.sh), fall back to PATH — but warn loudly if PATH resolves
# to pyenv shims, because those can silently route installs to a different
# Python than the user expects.
PIP="${SA_VENV_PIP:-$(command -v pip || true)}"
PY="${SA_VENV_PY:-$(command -v python || true)}"
SAM_BIN="${SA_VENV_BIN:+$SA_VENV_BIN/sam}"
[ -n "${SAM_BIN:-}" ] && [ ! -x "$SAM_BIN" ] && SAM_BIN=""
SAM_BIN="${SAM_BIN:-$(command -v sam || true)}"

if [ -z "$PIP" ] || [ -z "$PY" ]; then
  echo "✗ pip or python not found on PATH and no SA_VENV_PIP/SA_VENV_PY env vars set" >&2
  exit 1
fi

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

[ $# -ge 1 ] || usage 1
case "$1" in -h|--help) usage 0 ;; esac

plugin="$1"; shift

ref=""
skip_add="0"
while [ $# -gt 0 ]; do
  case "$1" in
    --ref)       ref="$2"; shift 2 ;;
    --skip-add)  skip_add="1"; shift ;;
    -h|--help)   usage 0 ;;
    *)           echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

url="git+${REPO_URL}"
[ -n "$ref" ] && url="${url}@${ref}"
url="${url}#subdirectory=${plugin}"

echo "→ refreshing ${plugin}"
echo "  source: ${url}"

# Sanity check: every SA plugin's __init__.py imports from solace_architect_core.
# If core isn't in the active environment, `sam plugin add` later in this
# script would fail with the confusing "Plugin module not found" message. Fail
# fast here with a clear hint instead. The webui-entrypoint is an exception —
# its __init__.py is lazy — but we keep the check uniform for clarity.
# Probe a known submodule, not just the namespace. An empty leftover dir in
# site-packages would make `import solace_architect_core` succeed but
# `solace_architect_core.logging_setup` (which every plugin imports) fail.
core_probe='import solace_architect_core, sys
ok = solace_architect_core.__file__ is not None
try:
    import solace_architect_core.logging_setup
except Exception:
    ok = False
sys.exit(0 if ok else 1)'
if ! "$PY" -c "$core_probe" >/dev/null 2>&1; then
  echo >&2
  echo "✗ solace-architect-core is missing or corrupted in the active Python." >&2
  echo "  (Either not installed, or only an empty namespace-package directory exists.)" >&2
  echo "  Every Solace Architect plugin imports it at module load; without it" >&2
  echo "  'sam plugin add' would fail with 'Plugin module not found'." >&2
  echo >&2
  echo "  Fix from the monorepo root:" >&2
  echo "    pip install -e ./solace-architect-core/" >&2
  echo "  Or use the wrapper (recommended — handles cleanup of corrupted state):" >&2
  echo "    ./update.sh" >&2
  echo >&2
  exit 2
fi

# Clear pip's wheel cache for this package so a same-version commit on the
# same ref actually re-downloads. Failures here are non-fatal (cache might
# not exist, or pip might be too old to support `cache remove`).
"$PIP" cache remove "${plugin//-/_}*" >/dev/null 2>&1 || true

"$PIP" install --force-reinstall --no-deps "$url"

if [ "$skip_add" = "0" ]; then
  # `sam plugin add` writes <cwd>/configs/<kind>/<plugin>.yaml. If we run it
  # from anywhere other than a SAM project directory, it silently drops the
  # config in the wrong place. Refuse with a clear hint instead of failing
  # mysteriously later. A SAM project has at least a configs/ directory at
  # its root (created by `sam init`).
  if [ ! -d "configs" ]; then
    echo >&2
    echo "✗ Current directory does not look like a SAM project (no ./configs/)." >&2
    echo "  'sam plugin add' would drop ${plugin}.yaml under \$PWD/configs/<kind>/, not under your SAM project." >&2
    echo "  Either:" >&2
    echo "    cd /path/to/your-sam-project && $(dirname "$0")/$(basename "$0") ${plugin}" >&2
    echo "    # or skip the component registration step:" >&2
    echo "    $0 ${plugin} --skip-add" >&2
    echo >&2
    echo "  (The pip install above already succeeded; the package is in the venv.)" >&2
    exit 2
  fi
  if [ -z "$SAM_BIN" ]; then
    echo >&2
    echo "✗ 'sam' CLI not found (neither in \$SA_VENV_BIN nor on PATH)." >&2
    echo "  Install with: $PIP install solace-agent-mesh" >&2
    exit 3
  fi
  echo "→ re-registering '${plugin}' as a SAM component in $(pwd)/configs/"
  "$SAM_BIN" plugin add "$plugin" --plugin "$plugin"
fi

# Sanity check: show where the package landed + mtime of a key file
module_name="${plugin//-/_}"
loc=$("$PY" -c "import importlib, pathlib; m = importlib.import_module('${module_name}'); print(pathlib.Path(m.__file__).parent)" 2>/dev/null || echo "")
if [ -n "$loc" ]; then
  echo "✓ installed at: $loc"
  for f in component.py app.py; do
    [ -f "$loc/$f" ] && ls -l "$loc/$f"
  done
fi

echo
echo "Restart your SAM run to pick up the new code:"
echo "  sam run"
