#!/usr/bin/env bash
# sa-plugins-install.sh — refresh every Solace Architect plugin in a SAM project.
#
# Re-installs each plugin from GitHub via `plugins/refresh-plugin.sh`, then
# re-registers it as a SAM component in <sam-dir>/configs/. Run this any time
# you want to pick up upstream plugin changes.
#
# Usage:
#   ./sa-plugins-install.sh <sam-dir>        # explicit path
#   SAM_DIR=/path/to/sam ./sa-plugins-install.sh
#   ./sa-plugins-install.sh                  # falls back to ./sam if neither set
#
# Examples:
#   ./sa-plugins-install.sh sam
#   ./sa-plugins-install.sh /Users/me/some-other-sam-project
#   SAM_DIR=~/work/sam-prod ./sa-plugins-install.sh

set -euo pipefail

# ── resolve paths ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFRESH_SCRIPT="$SCRIPT_DIR/plugins/refresh-plugin.sh"

usage() { sed -n '2,/^set -e/p' "$0" | sed 's/^# \{0,1\}//' | sed '$d'; exit "${1:-0}"; }

# ── arg parsing ─────────────────────────────────────────────────────────────
sam_dir=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    -*)        echo "Unknown flag: $1" >&2; usage 1 ;;
    *)         sam_dir="$1"; shift ;;
  esac
done

# SAM dir: arg → env → default
sam_dir="${sam_dir:-${SAM_DIR:-$SCRIPT_DIR/sam}}"
sam_dir="$(cd "$sam_dir" 2>/dev/null && pwd || echo "$sam_dir")"

# ── pretty printers ─────────────────────────────────────────────────────────
HR='═══════════════════════════════════════════════════════════════════'
hr='───────────────────────────────────────────────────────────────────'
header()  { printf "\n%s\n  %s\n%s\n\n" "$HR" "$1" "$HR"; }
section() { printf "\n%s\n  %s\n%s\n" "$hr" "$1" "$hr"; }
ok()      { printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail()    { printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn()    { printf "  \033[33m!\033[0m %s\n" "$1"; }

# ── preflight ───────────────────────────────────────────────────────────────
header "Solace Architect — refresh plugins"

echo "  SAM project:     $sam_dir"
echo "  Refresh helper:  $REFRESH_SCRIPT"
echo "  Upstream repo:   ${SA_PLUGINS_REPO:-https://github.com/gvensan/sam-solace-architect-agents.git}"

if [[ ! -d "$sam_dir" ]]; then
  printf "\n"; fail "SAM directory does not exist: $sam_dir"
  echo "  Pass it as the first argument or set SAM_DIR."
  exit 1
fi
if [[ ! -d "$sam_dir/configs" ]]; then
  printf "\n"; fail "$sam_dir doesn't look like a SAM project (no configs/ directory)."
  echo "  Run \`sam init\` in that directory first."
  exit 1
fi
if [[ ! -x "$REFRESH_SCRIPT" ]]; then
  printf "\n"; fail "Cannot find refresh-plugin.sh at $REFRESH_SCRIPT"
  echo "  The plugins/ sibling directory must be present and refresh-plugin.sh executable."
  exit 1
fi

# Discover the venv's pip so we install into the right environment. Mirrors
# the lookup in sa-plugins-uninstall.sh — tries $sam_dir/../.venv first, then $sam_dir/.venv,
# finally falls back to pip on PATH with a warning.
VENV_PIP=""
for candidate in "$sam_dir/../.venv/bin/pip" "$sam_dir/.venv/bin/pip"; do
  if [[ -x "$candidate" ]]; then
    VENV_PIP="$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
    break
  fi
done
if [[ -z "$VENV_PIP" ]]; then
  VENV_PIP="$(command -v pip || true)"
  [[ -n "$VENV_PIP" ]] || { fail "No pip in PATH and no .venv near $sam_dir"; exit 1; }
  warn "No venv found near $sam_dir — falling back to pip in PATH: $VENV_PIP"
else
  echo "  pip:             $VENV_PIP"
fi
VENV_BIN="$(dirname "$VENV_PIP")"
VENV_PY="$VENV_BIN/python"

# CRITICAL: prepend the venv's bin/ to PATH so child processes (refresh-plugin.sh,
# sam, pip) all resolve to the venv's tooling — not whatever the parent shell
# happens to have first (pyenv-shims, system pip, etc.). Without this, pip would
# install plugins to one Python while sam reads from another, producing
# "Plugin module not found" even though pip reports success.
export PATH="$VENV_BIN:$PATH"
# Also export so refresh-plugin.sh and any deeper child can prefer venv binaries
# explicitly if they want.
export SA_VENV_BIN="$VENV_BIN"
export SA_VENV_PIP="$VENV_PIP"
export SA_VENV_PY="$VENV_PY"

# Ensure solace-architect-core is installed BEFORE refreshing any plugin.
# Every agent's __init__.py imports from solace_architect_core, so without
# this preflight `sam plugin add` would fail at the import step with the
# confusing "Plugin module not found" message. This is the most common
# breakage after a fresh venv or `sa-plugins-uninstall.sh` (which removes core unless
# --keep-core was passed).
section "Preflight: solace-architect-core"
CORE_DIR="$SCRIPT_DIR/solace-architect-core"
if [[ ! -d "$CORE_DIR" ]]; then
  fail "Could not find ./solace-architect-core/ at $CORE_DIR"
  echo "  This script assumes the monorepo layout. Install core manually with:"
  echo "    $VENV_PIP install -e /path/to/solace-architect-core/"
  exit 1
fi
# Important: just `import solace_architect_core` is not enough — an empty
# directory in site-packages (left over from a botched pip uninstall, a stale
# editable shim, etc.) makes Python treat it as a namespace package, so the
# import succeeds but `__file__` is None and no submodules exist. We probe a
# known submodule and check __file__ to catch this state.
CORE_CHECK='import solace_architect_core, sys
ok = (solace_architect_core.__file__ is not None)
try:
    import solace_architect_core.logging_setup
except Exception:
    ok = False
sys.exit(0 if ok else 1)'

if "$VENV_PY" -c "$CORE_CHECK" >/dev/null 2>&1; then
  ok "solace-architect-core importable + submodules present — skipping reinstall"
else
  warn "solace-architect-core is missing or corrupted — reinstalling editable from $CORE_DIR"
  # Belt-and-braces cleanup: pip uninstall doesn't always remove an empty
  # directory in site-packages, which can re-trigger the namespace-package
  # corruption we just detected.
  "$VENV_PIP" uninstall -y solace-architect-core >/dev/null 2>&1 || true
  SP_DIR="$("$VENV_PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  rm -rf "$SP_DIR/solace_architect_core"
  "$VENV_PIP" install -e "$CORE_DIR" -q
  if "$VENV_PY" -c "$CORE_CHECK" >/dev/null 2>&1; then
    ok "solace-architect-core installed (editable from $CORE_DIR)"
  else
    fail "core install failed — aborting (plugins would all fail to import)"
    exit 1
  fi
fi

# ── plugin list (in dependency order — orchestrator first, entrypoint last) ─
# NOTE: keep in sync with the SA_PLUGINS list in ../sa-plugins-uninstall.sh
PLUGINS=(
  solace-architect-orchestrator
  solace-architect-discovery
  solace-architect-domain
  solace-architect-reviewer-architect
  solace-architect-reviewer-developer
  solace-architect-reviewer-ops
  solace-architect-reviewer-security
  solace-architect-validation
  solace-architect-blueprint
  solace-architect-event-portal
  solace-architect-webui-entrypoint
)

echo "  Plugins to refresh: ${#PLUGINS[@]}"

# ── refresh loop ────────────────────────────────────────────────────────────
# refresh-plugin.sh expects to be run from inside the SAM project (it uses
# $(pwd)/configs/ for `sam plugin add`).
cd "$sam_dir"

succeeded=()
failed=()
i=0
for plugin in "${PLUGINS[@]}"; do
  i=$((i + 1))
  section "[$i/${#PLUGINS[@]}] $plugin"
  if "$REFRESH_SCRIPT" "$plugin"; then
    succeeded+=( "$plugin" )
  else
    failed+=( "$plugin" )
    fail "$plugin failed"
  fi
done

# ── summary ─────────────────────────────────────────────────────────────────
header "Summary"

if [[ ${#succeeded[@]} -gt 0 ]]; then
  ok "${#succeeded[@]} plugin(s) refreshed"
fi
if [[ ${#failed[@]} -gt 0 ]]; then
  fail "${#failed[@]} plugin(s) failed:"
  for p in "${failed[@]}"; do echo "      - $p"; done
fi

printf "\n  Restart SAM to pick up the new code:\n"
printf "    cd %s && sam run\n\n" "$sam_dir"

[[ ${#failed[@]} -eq 0 ]] || exit 1
