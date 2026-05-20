#!/usr/bin/env bash
# bootstrap.sh — one-command setup for a fresh Solace Architect V2 checkout.
#
# Assumes you've cloned the monorepo:
#   git clone https://github.com/gvensan/sam-solace-architect.git
#   cd sam-solace-architect
#
# Walks you from "freshly cloned" to "sam run ready":
#   1. Verifies prerequisites (python, pip, sam, optionally node/uvx)
#   2. Clones the plugins subrepo into ./plugins/ if missing
#   3. Editable-installs solace-architect-core/ and every plugin
#   4. Initialises a SAM project at ./sam/ (idempotent)
#   5. Registers all 11 plugins with that SAM project
#   6. Drops a starter sam/.env from test-harness/.env.example (idempotent)
#
# Re-runnable: every step checks before it acts, so re-running after a partial
# failure or to refresh a plugin install is safe.
#
# Usage:
#   ./test-harness/bootstrap.sh                  # do everything
#   ./test-harness/bootstrap.sh --skip-clone     # plugins/ already populated
#   ./test-harness/bootstrap.sh --skip-sam       # don't touch sam/
#   ./test-harness/bootstrap.sh --help
#
# Environment:
#   SA_PLUGINS_REPO  Override the plugins git URL
#                    (default: https://github.com/gvensan/sam-solace-architect-agents.git)

set -euo pipefail

PLUGINS_REPO="${SA_PLUGINS_REPO:-https://github.com/gvensan/sam-solace-architect-agents.git}"
SKIP_CLONE="0"
SKIP_SAM="0"

# All 11 plugins, in install order (entrypoint last so its config.yaml is the
# last thing dropped into sam/configs/gateways/ — purely cosmetic).
PLUGINS=(
  solace-architect-orchestrator
  solace-architect-discovery
  solace-architect-domain
  solace-architect-reviewer-architect
  solace-architect-reviewer-developer
  solace-architect-reviewer-ops
  solace-architect-reviewer-security
  solace-architect-validation
  solace-architect-event-portal
  solace-architect-blueprint
  solace-architect-webui-entrypoint
)

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-clone) SKIP_CLONE="1"; shift ;;
    --skip-sam)   SKIP_SAM="1"; shift ;;
    -h|--help)    usage 0 ;;
    *)            echo "unknown arg: $1" >&2; usage 1 ;;
  esac
done

# Anchor at the monorepo root (one above test-harness/).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

say()   { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }
die()   { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()    { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
say "Checking prerequisites"

command -v python3 >/dev/null  || die "python3 not found"
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  die "python 3.11+ required (you have $PYV)"
fi
ok "python $PYV"

command -v pip >/dev/null || die "pip not found"
ok "pip $(pip --version | awk '{print $2}')"

if ! command -v sam >/dev/null; then
  warn "sam CLI not found. Install with: pip install solace-agent-mesh"
  warn "Continuing — you can install it later. The sam-init step will skip."
  SKIP_SAM="1"
else
  ok "sam $(sam --version 2>&1 | head -1 || echo present)"
fi

if command -v node >/dev/null; then
  ok "node $(node --version) — visualizer rebuilds available via 'make visualizer-build'"
else
  warn "node not found — visualizer ships pre-built so this is fine for running, only needed if you'll edit visualizer-src/"
fi

if command -v uvx >/dev/null; then
  ok "uvx present — Event Portal MCP agent can launch"
else
  warn "uvx not found — needed by SAEventPortalAgent. Install: pip install uv"
fi

# ---------------------------------------------------------------------------
# 2. Plugins subrepo
# ---------------------------------------------------------------------------
if [ "$SKIP_CLONE" = "0" ]; then
  say "Ensuring plugins/ is populated"
  if [ ! -d "plugins/.git" ] && [ ! -f "plugins/solace-architect-orchestrator/pyproject.toml" ]; then
    if [ -d "plugins" ] && [ "$(ls -A plugins 2>/dev/null)" ]; then
      warn "plugins/ exists but isn't a git checkout and isn't empty — leaving it alone"
    else
      mkdir -p plugins
      git clone "$PLUGINS_REPO" plugins
      ok "cloned $PLUGINS_REPO → plugins/"
    fi
  else
    ok "plugins/ already populated"
  fi
fi

# Sanity: every expected plugin source exists.
for p in "${PLUGINS[@]}"; do
  if [ ! -f "plugins/$p/pyproject.toml" ]; then
    die "missing plugins/$p/ — re-clone the plugins repo or pass --skip-clone deliberately"
  fi
done
ok "all 11 plugin sources present"

# ---------------------------------------------------------------------------
# 3. Editable installs
# ---------------------------------------------------------------------------
say "Installing solace-architect-core (editable)"
pip install -e ./solace-architect-core/ -q
ok "core installed"

say "Installing all 11 plugins (editable)"
for p in "${PLUGINS[@]}"; do
  printf '  → %s\n' "$p"
  pip install -e "./plugins/$p/" -q
done
ok "all plugins installed"

# ---------------------------------------------------------------------------
# 4. SAM project
# ---------------------------------------------------------------------------
if [ "$SKIP_SAM" = "0" ]; then
  say "Bootstrapping sam/ project"

  if [ ! -d "sam" ]; then
    mkdir sam
  fi

  if [ ! -d "sam/configs" ]; then
    (cd sam && sam init . </dev/null) || die "sam init failed"
    ok "sam init done"
  else
    ok "sam/ already initialised"
  fi

  say "Registering plugins with sam/"
  cd sam
  for p in "${PLUGINS[@]}"; do
    # sam plugin add is idempotent-ish — it'll overwrite an existing yaml,
    # which is what we want when source has moved forward.
    sam plugin add "$p" --plugin "$p" >/dev/null 2>&1 \
      && printf '  → %s\n' "$p" \
      || warn "  failed to register $p (check logs)"
  done
  cd ..
  ok "all plugins registered"

  if [ ! -f "sam/.env" ]; then
    if [ -f "test-harness/.env.example" ]; then
      cp test-harness/.env.example sam/.env
      ok "seeded sam/.env from test-harness/.env.example"
    fi
  else
    ok "sam/.env already exists (left alone)"
  fi
fi

# ---------------------------------------------------------------------------
# 5. Next steps
# ---------------------------------------------------------------------------
cat <<'EOF'

────────────────────────────────────────────────────────────────────────────
✓ Bootstrap complete

What's left for you:
  1. Edit sam/.env — fill in:
     • LLM_SERVICE_API_KEY      (your model provider's key)
     • LLM_SERVICE_GENERAL_MODEL_NAME  (default: anthropic/claude-sonnet-4-20250514)
     • SOLACE_BROKER_URL / VPN / USERNAME / PASSWORD if not localhost defaults

  2. Make sure a Solace broker is reachable. For local dev:
     docker run -d --name=solace-pubsubplus \
       -p 8008:8008 -p 8080:8080 -p 55555:55555 \
       --shm-size=1g --env username_admin_globalaccesslevel=admin \
       --env username_admin_password=admin solace/solace-pubsub-standard:latest

  3. Start the mesh:
     cd sam && sam run

  4. Open http://localhost:9080  (or whatever WEBUI_PORT you set)
     First signup becomes admin.

If anything in sam/configs/gateways/ or sam/configs/agents/ drifts from
plugin source, re-run:    ./sa-plugins-install.sh    (or this script again)
────────────────────────────────────────────────────────────────────────────
EOF
