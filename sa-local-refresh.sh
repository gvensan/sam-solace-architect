#!/usr/bin/env bash
#
# sa-local-refresh.sh — reinstall Solace Architect plugins from the LOCAL
# working tree (./plugins/<plugin>), NOT the upstream git repo.
#
# Why this exists:
#   sa-plugins-refresh.sh / refresh-plugin.sh install each plugin with
#       pip install git+${SA_PLUGINS_REPO}#subdirectory=<plugin>
#   i.e. from the published `sam-solace-architect-agents` repo. So local
#   edits don't take effect until they're committed AND pushed there.
#   This script installs straight from ./plugins/<plugin> so your local
#   (even uncommitted) changes go live — no check-in required.
#
#   `solace-architect-core` is already an editable install, so its edits are
#   live without this script; the plugins are not, which is why they need a
#   reinstall after a source change.
#
# Usage:
#   ./sa-local-refresh.sh                          # all SA plugins
#   ./sa-local-refresh.sh event-portal             # one (short or full name)
#   ./sa-local-refresh.sh --plugin discovery --plugin domain
#   ./sa-local-refresh.sh -e event-portal          # editable: future edits go live, no reinstall
#   ./sa-local-refresh.sh --skip-add               # update code only, don't re-run `sam plugin add`
#
# Env overrides (same as refresh-plugin.sh):
#   SA_VENV_PIP / SA_VENV_PY / SA_VENV_BIN
#
# After it finishes, restart SAM to load the new code:
#   cd sam && sam run
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGINS_DIR="$REPO_ROOT/plugins"
SAM_DIR="$REPO_ROOT/sam"

# Canonical plugin list — keep in sync with sa-plugins-install.sh.
ALL_PLUGINS=(
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

# ── venv tooling: prefer repo .venv, then env overrides, then PATH ──────────
_def_pip="$REPO_ROOT/.venv/bin/pip"
_def_py="$REPO_ROOT/.venv/bin/python"
_def_sam="$REPO_ROOT/.venv/bin/sam"
PIP="${SA_VENV_PIP:-$([ -x "$_def_pip" ] && echo "$_def_pip" || command -v pip || true)}"
PY="${SA_VENV_PY:-$([ -x "$_def_py" ] && echo "$_def_py" || command -v python || true)}"
SAM_BIN="${SA_VENV_BIN:+$SA_VENV_BIN/sam}"
[ -n "${SAM_BIN:-}" ] && [ ! -x "$SAM_BIN" ] && SAM_BIN=""
SAM_BIN="${SAM_BIN:-$([ -x "$_def_sam" ] && echo "$_def_sam" || command -v sam || true)}"

[ -n "$PIP" ] && [ -n "$PY" ] || { echo "✗ pip/python not found (set SA_VENV_PIP/SA_VENV_PY)" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^#\{0,1\} \{0,1\}//'; }

# ── parse args ─────────────────────────────────────────────────────────────
normalize() { case "$1" in solace-architect-*) echo "$1" ;; *) echo "solace-architect-$1" ;; esac; }

editable=0
skip_add=0
selected=()
while [ $# -gt 0 ]; do
  case "$1" in
    -e|--editable) editable=1; shift ;;
    --skip-add)    skip_add=1; shift ;;
    --plugin)      selected+=( "$(normalize "$2")" ); shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; usage; exit 1 ;;
    *)             selected+=( "$(normalize "$1")" ); shift ;;
  esac
done
[ ${#selected[@]} -gt 0 ] || selected=( "${ALL_PLUGINS[@]}" )

# ── preflight: core must be importable (editable) ──────────────────────────
if ! "$PY" -c "import solace_architect_core" >/dev/null 2>&1; then
  echo "→ solace_architect_core not importable — installing it editable first"
  "$PIP" install -e "$REPO_ROOT/solace-architect-core" -q
fi

echo "Local refresh from: $PLUGINS_DIR"
echo "  mode:    $([ "$editable" = 1 ] && echo 'editable (-e)' || echo 'force-reinstall')"
echo "  pip:     $PIP"
echo "  plugins: ${#selected[@]}"
echo

# `sam plugin add` writes <cwd>/configs/<kind>/<plugin>.yaml — run it from the
# SAM project dir so configs land in sam/configs/, not the repo root.
[ "$skip_add" = "1" ] || cd "$SAM_DIR"

failed=()
i=0
for plugin in "${selected[@]}"; do
  i=$((i + 1))
  src="$PLUGINS_DIR/$plugin"
  echo "[$i/${#selected[@]}] $plugin"
  if [ ! -f "$src/pyproject.toml" ] && [ ! -f "$src/setup.py" ]; then
    echo "  ✗ no pyproject.toml/setup.py at $src — skipping" >&2
    failed+=( "$plugin" ); continue
  fi
  if [ "$editable" = "1" ]; then
    "$PIP" install -e "$src" --no-deps -q || { failed+=( "$plugin" ); echo "  ✗ pip -e failed" >&2; continue; }
  else
    # Clear wheel cache so a same-version source change actually reinstalls.
    "$PIP" cache remove "${plugin//-/_}*" >/dev/null 2>&1 || true
    "$PIP" install --force-reinstall --no-deps "$src" -q || { failed+=( "$plugin" ); echo "  ✗ pip install failed" >&2; continue; }
  fi
  if [ "$skip_add" = "0" ]; then
    if [ -z "$SAM_BIN" ]; then
      echo "  ⚠ 'sam' CLI not found — code updated, but config not re-registered (use --skip-add to silence)" >&2
    else
      "$SAM_BIN" plugin add "$plugin" --plugin "$plugin" >/dev/null && echo "  ✓ code + config refreshed" || echo "  ⚠ code refreshed; 'sam plugin add' failed" >&2
    fi
  else
    echo "  ✓ code refreshed (config regen skipped)"
  fi
done

echo
echo "── Summary ──"
echo "  attempted: ${#selected[@]}  |  failed: ${#failed[@]}"
if [ ${#failed[@]} -gt 0 ]; then
  echo "  failed:"; for p in "${failed[@]+"${failed[@]}"}"; do echo "    - $p"; done
fi
echo
echo "Restart SAM to load the new code:"
echo "  cd $SAM_DIR && sam run"
