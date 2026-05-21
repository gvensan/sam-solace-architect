#!/usr/bin/env bash
# sa-plugins-refresh.sh — uninstall + reinstall every SA plugin in one shot,
# no prompts. Convenience wrapper around sa-plugins-uninstall.sh + sa-plugins-install.sh.
#
# Use this when:
#   - You've just run ./scripts/publish-plugins.sh and want SAM's venv to
#     pick up the new published state from plugins-origin.
#   - You bumped a plugin's pyproject.toml dependency pin (pip-install -e
#     doesn't always re-resolve transitive deps).
#   - You hit "stale install" weirdness during development and want a
#     clean rebuild without typing two commands and confirming a prompt.
#
# Usage:
#   ./sa-plugins-refresh.sh <sam-dir>                          # refresh all
#   ./sa-plugins-refresh.sh <sam-dir> --plugin <name>          # refresh one
#   ./sa-plugins-refresh.sh <sam-dir> --plugin <a> --plugin <b>  # refresh several
#   SAM_DIR=/path/to/sam ./sa-plugins-refresh.sh
#   ./sa-plugins-refresh.sh                                    # falls back to ./sam
#
# Flags (forwarded as-is to both child scripts):
#   --plugin <name>     Refresh a single plugin (repeatable). Same name rules
#                       as the install/uninstall scripts (full
#                       "solace-architect-*" name, not the bare suffix).
#                       In targeted mode, core is preserved automatically.
#   -h / --help         Show this help block.
#
# Behavior:
#   - Uninstall step uses --yes (no confirmation prompt) so the script is
#     fully non-interactive.
#   - When refreshing all plugins, solace-architect-core is also
#     uninstalled and reinstalled (the install step does that automatically
#     via its preflight check).
#   - When --plugin is used, solace-architect-core is NEVER touched (per
#     the uninstall script's targeted-mode rules — shared library used by
#     the remaining plugins).
#   - SAM must be RESTARTED after this script completes for changes to take
#     effect — the script prints the restart command at the end.
#
# Exits non-zero on the first failed step so you can chain it safely in CI
# or wrapper scripts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNINSTALL="$SCRIPT_DIR/sa-plugins-uninstall.sh"
INSTALL="$SCRIPT_DIR/sa-plugins-install.sh"

usage() { sed -n '2,/^set -e/p' "$0" | sed 's/^# \{0,1\}//' | sed '$d'; exit "${1:-0}"; }

# ── arg parsing — mirror sa-plugins-install.sh ─────────────────────────────
sam_dir=""
selected_plugins=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)     usage 0 ;;
    --plugin)      [[ -n "${2:-}" ]] || { echo "--plugin requires a name" >&2; usage 1; }
                   selected_plugins+=( "$2" ); shift 2 ;;
    --plugin=*)    selected_plugins+=( "${1#*=}" ); shift ;;
    -*)            echo "Unknown flag: $1" >&2; usage 1 ;;
    *)             sam_dir="$1"; shift ;;
  esac
done

sam_dir="${sam_dir:-${SAM_DIR:-$SCRIPT_DIR/sam}}"

# ── pretty printers — match install/uninstall style ─────────────────────────
HR='═══════════════════════════════════════════════════════════════════'
header()  { printf "\n%s\n  %s\n%s\n\n" "$HR" "$1" "$HR"; }
ok()      { printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail()    { printf "  \033[31m✗\033[0m %s\n" "$1"; }

# ── preflight ───────────────────────────────────────────────────────────────
header "Solace Architect — full plugin refresh"
echo "  SAM project:     $sam_dir"
echo "  Uninstall helper: $UNINSTALL"
echo "  Install helper:   $INSTALL"
if [[ ${#selected_plugins[@]} -gt 0 ]]; then
  echo "  Plugins:         ${#selected_plugins[@]} (selected via --plugin; core preserved)"
  for p in "${selected_plugins[@]}"; do echo "    - $p"; done
else
  echo "  Plugins:         all (full mesh; core will be uninstalled + reinstalled)"
fi

[[ -x "$UNINSTALL" ]] || { fail "$UNINSTALL is missing or not executable"; exit 1; }
[[ -x "$INSTALL"   ]] || { fail "$INSTALL is missing or not executable";   exit 1; }

# ── build common --plugin args once so we forward identically to both ──────
# macOS ships Bash 3.2 which treats "${arr[@]}" of an empty array as an
# "unbound variable" error under `set -u`. We guard every empty-array
# expansion with the ${var+default} trick so the script works on both
# Bash 3.x (macOS default) and Bash 4+/5+ (Linux, Homebrew Bash).
plugin_args=()
if [[ ${#selected_plugins[@]} -gt 0 ]]; then
  for p in "${selected_plugins[@]}"; do
    plugin_args+=( --plugin "$p" )
  done
fi

# ── step 1: uninstall (always with --yes for non-interactive run) ──────────
header "Step 1 of 2 — uninstall"
"$UNINSTALL" "$sam_dir" --yes ${plugin_args[@]+"${plugin_args[@]}"}
echo
ok "uninstall complete"

# ── step 2: install (already non-interactive by design) ────────────────────
header "Step 2 of 2 — install"
"$INSTALL" "$sam_dir" ${plugin_args[@]+"${plugin_args[@]}"}
echo
ok "install complete"

# ── done ────────────────────────────────────────────────────────────────────
header "Refresh complete"
printf "  Restart SAM to pick up the new code:\n"
printf "    cd %s && sam run\n\n" "$sam_dir"
