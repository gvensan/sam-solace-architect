#!/usr/bin/env bash
# sa-plugins-uninstall.sh — uninstall Solace Architect (SA) from a SAM project.
#
# What this script does:
#   1. Removes SA agent + entrypoint configs from <sam-dir>/configs/
#   2. pip-uninstalls every SA plugin + (by default) solace-architect-core
#   3. Clears <sam-dir>/sa_logs/ if present
#
# What this script does NOT touch:
#   • Engagement data under SA_STORAGE_ROOT (your projects are safe)
#   • The SAM project's stock state .db files (platform.db, orchestrator.db, etc.)
#   • The SAM project directory itself
#   • Stock SAM agents (BuiltInTools, sam-mermaid, find-my-ip, etc.)
#
# Usage:
#   ./sa-plugins-uninstall.sh <sam-dir>             # explicit path
#   SAM_DIR=/path/to/sam ./sa-plugins-uninstall.sh
#   ./sa-plugins-uninstall.sh                       # falls back to ./sam if neither set
#
# Flags:
#   --dry-run        # show what would be done, don't actually do it
#   --yes / -y       # skip all confirmation prompts
#   --keep-core      # don't pip-uninstall solace-architect-core (the shared library)
#   -h / --help      # show this help block
#
# To restore SA after a cleanup:
#   ./sa-plugins-install.sh <sam-dir>

set -euo pipefail
shopt -s nullglob

# ── arg parsing ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sam_dir=""
DRY_RUN=false
ASSUME_YES=false
KEEP_CORE=false

usage() { sed -n '2,/^set -e/p' "$0" | sed 's/^# \{0,1\}//' | sed '$d'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)    DRY_RUN=true; shift ;;
    --yes|-y)     ASSUME_YES=true; shift ;;
    --keep-core)  KEEP_CORE=true; shift ;;
    -h|--help)    usage 0 ;;
    -*)           echo "Unknown flag: $1" >&2; usage 1 ;;
    *)            sam_dir="$1"; shift ;;
  esac
done

sam_dir="${sam_dir:-${SAM_DIR:-$SCRIPT_DIR/sam}}"
sam_dir="$(cd "$sam_dir" 2>/dev/null && pwd || echo "$sam_dir")"

# ── pretty printers ─────────────────────────────────────────────────────────
HR='═══════════════════════════════════════════════════════════════════'
hr='───────────────────────────────────────────────────────────────────'
header()  { printf "\n%s\n  %s\n%s\n\n" "$HR" "$1" "$HR"; }
section() { printf "\n%s\n" "$1"; }
ok()      { printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail()    { printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn()    { printf "  \033[33m!\033[0m %s\n" "$1"; }
step()    { printf "\n→ %s\n" "$1"; }
note()    { printf "  %s\n" "$1"; }

# ── preflight ───────────────────────────────────────────────────────────────
header "Solace Architect — cleanup"
echo "  SAM project: $sam_dir"
$DRY_RUN  && echo "  Mode:        dry-run (no changes will be made)"
$ASSUME_YES && echo "  Mode:        --yes (no confirmations)"
$KEEP_CORE && echo "  Mode:        --keep-core (solace-architect-core preserved)"

if [[ ! -d "$sam_dir" ]]; then
  printf "\n"; fail "SAM directory does not exist: $sam_dir"
  echo "  Pass it as the first argument or set SAM_DIR."
  exit 1
fi

# Locate the venv's pip (tries common locations: $sam_dir/../.venv then $sam_dir/.venv)
VENV_PIP=""
for candidate in "$sam_dir/../.venv/bin/pip" "$sam_dir/.venv/bin/pip"; do
  if [[ -x "$candidate" ]]; then
    VENV_PIP="$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
    break
  fi
done
if [[ -z "$VENV_PIP" ]]; then
  printf "\n"; fail "Could not find a venv pip near $sam_dir"
  echo "  Looked in: $sam_dir/../.venv/bin/pip and $sam_dir/.venv/bin/pip"
  echo "  If your venv is elsewhere, activate it and rerun, or set PATH so 'pip' resolves correctly."
  VENV_PIP="$(command -v pip || true)"
  [[ -n "$VENV_PIP" ]] || { echo "  No pip in PATH either."; exit 1; }
  warn "Falling back to pip in PATH: $VENV_PIP"
fi
echo "  pip:         $VENV_PIP"

# ── plugin list ─────────────────────────────────────────────────────────────
# NOTE: keep in sync with the PLUGINS list in ../sa-plugins-install.sh
SA_PLUGINS=(
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

# ── discovery — what's actually present ────────────────────────────────────
header "Discovering SA footprint"

agent_configs=( "$sam_dir"/configs/agents/solace-architect-*.yaml )
gateway_configs=( "$sam_dir"/configs/gateways/solace-architect-*.yaml )

installed_plugins=()
for p in "${SA_PLUGINS[@]}"; do
  "$VENV_PIP" show "$p" >/dev/null 2>&1 && installed_plugins+=( "$p" )
done

core_installed=false
$KEEP_CORE || {
  "$VENV_PIP" show solace-architect-core >/dev/null 2>&1 && core_installed=true
}

sa_logs_dir="$sam_dir/sa_logs"
sa_logs_count=0
sa_logs_size="0"
if [[ -d "$sa_logs_dir" ]]; then
  sa_logs_count=$(find "$sa_logs_dir" -maxdepth 1 -type f | wc -l | tr -d ' ')
  sa_logs_size=$(du -sh "$sa_logs_dir" 2>/dev/null | awk '{print $1}')
fi

echo "  Agent configs in configs/agents/:        ${#agent_configs[@]}"
echo "  Entrypoint configs in configs/gateways/: ${#gateway_configs[@]}"
echo "  SA plugin packages installed:            ${#installed_plugins[@]}"
echo "  solace-architect-core installed:         $(if $core_installed; then echo "yes (will be removed)"; elif $KEEP_CORE; then echo "preserved (--keep-core)"; else echo "no"; fi)"
echo "  Per-agent logs at sa_logs/:              $sa_logs_count files ($sa_logs_size)"

total_actions=$(( ${#agent_configs[@]} + ${#gateway_configs[@]} + ${#installed_plugins[@]} ))
$core_installed && total_actions=$(( total_actions + 1 ))
[[ $sa_logs_count -gt 0 ]] && total_actions=$(( total_actions + 1 ))

if [[ $total_actions -eq 0 ]]; then
  printf "\n"; ok "Nothing to do — SA is not present in $sam_dir"
  exit 0
fi

# ── confirm ────────────────────────────────────────────────────────────────
if ! $ASSUME_YES; then
  printf "\n  Proceed with cleanup? [y/N] "
  read -r reply
  [[ "$reply" =~ ^[Yy]$ ]] || { printf "\n  Aborted.\n"; exit 0; }
fi

# ── action 1: remove agent configs ──────────────────────────────────────────
if [[ ${#agent_configs[@]} -gt 0 ]]; then
  step "Removing ${#agent_configs[@]} SA agent config(s)"
  for f in "${agent_configs[@]}"; do
    name=$(basename "$f")
    if $DRY_RUN; then
      note "[dry-run] rm $f"
    else
      rm -- "$f"
    fi
    ok "$name"
  done
fi

# ── action 2: remove entrypoint configs ─────────────────────────────────────
if [[ ${#gateway_configs[@]} -gt 0 ]]; then
  step "Removing ${#gateway_configs[@]} SA entrypoint config(s)"
  for f in "${gateway_configs[@]}"; do
    name=$(basename "$f")
    if $DRY_RUN; then
      note "[dry-run] rm $f"
    else
      rm -- "$f"
    fi
    ok "$name"
  done
fi

# ── action 3: uninstall plugin packages ─────────────────────────────────────
if [[ ${#installed_plugins[@]} -gt 0 ]]; then
  step "Uninstalling ${#installed_plugins[@]} SA plugin package(s)"
  if $DRY_RUN; then
    for p in "${installed_plugins[@]}"; do note "[dry-run] pip uninstall -y $p"; done
  else
    # Single batch call — pip prints its own progress
    "$VENV_PIP" uninstall -y "${installed_plugins[@]}"
  fi
  for p in "${installed_plugins[@]}"; do ok "$p"; done
fi

# ── action 4: uninstall solace-architect-core ───────────────────────────────
if $core_installed; then
  step "Uninstalling solace-architect-core"
  if $DRY_RUN; then
    note "[dry-run] pip uninstall -y solace-architect-core"
  else
    "$VENV_PIP" uninstall -y solace-architect-core
  fi
  ok "solace-architect-core"
fi

# ── action 5: clear sa_logs/ ────────────────────────────────────────────────
if [[ $sa_logs_count -gt 0 ]]; then
  step "Clearing $sa_logs_dir ($sa_logs_count files, $sa_logs_size)"
  if $DRY_RUN; then
    note "[dry-run] rm -rf $sa_logs_dir"
  else
    rm -rf -- "$sa_logs_dir"
  fi
  ok "sa_logs/ removed"
fi

# ── summary ─────────────────────────────────────────────────────────────────
header "Summary"

[[ ${#agent_configs[@]}    -gt 0 ]] && ok "${#agent_configs[@]} agent config(s) removed"
[[ ${#gateway_configs[@]}  -gt 0 ]] && ok "${#gateway_configs[@]} entrypoint config(s) removed"
[[ ${#installed_plugins[@]} -gt 0 ]] && ok "${#installed_plugins[@]} plugin package(s) uninstalled"
$core_installed && ok "solace-architect-core uninstalled"
[[ $sa_logs_count -gt 0 ]] && ok "sa_logs/ cleared"

cat <<EOF

  Not touched (intentional):
    • Engagement data under SA_STORAGE_ROOT (your projects are safe)
    • SAM project state (configs/shared_config.yaml, .env, *.db, etc.)
    • Stock SAM agents (BuiltInTools, sam-mermaid, find-my-ip, etc.)

  To bring SA back:
    $SCRIPT_DIR/sa-plugins-install.sh "$sam_dir"

EOF
