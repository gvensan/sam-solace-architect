#!/usr/bin/env bash
# smoke-preflight.sh — confirm this session's changes are actually live in
# the venv before starting a manual validation run.
#
# Each check is one bash line; the exit code is non-zero on any failure so
# you can chain this into CI later. Pairs with smoke-checklist.md.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV_PY="${SA_VENV_PY:-./.venv/bin/python}"
if [ ! -x "$VENV_PY" ]; then
  echo "✗ No venv python at $VENV_PY — activate the venv or set SA_VENV_PY"
  exit 1
fi

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; FAILED=1; }
sect() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

FAILED=0

sect "Core changes"

$VENV_PY -c "from solace_architect_core.tools._arg_coercion import coerce_args; print(coerce_args)" >/dev/null 2>&1 \
  && ok "coerce_args importable from solace_architect_core.tools._arg_coercion" \
  || fail "coerce_args not in venv — pip install -e ./solace-architect-core/"

# Decorated tools — each one should have @coerce_args applied
for fn in record_scope_progress render_audience_pack record_step_timing trace_requirements \
          compute_intake_preview render_intake_markdown import_source_context \
          ask_user_question update_session_state \
          get_engagement_plan get_next_step record_step_complete; do
  out=$($VENV_PY -c "
import inspect
from solace_architect_core.tools import _arg_coercion
mods = ['artifact_tools','blueprint_tools','dashboard_tools','decision_tools','grounding_tools',
        'intake_tools','interaction_tools','lifecycle_tools','project_tools','session_tools',
        'telemetry_tools','validation_tools','workflow_tools']
for m in mods:
    mod = __import__('solace_architect_core.tools.' + m, fromlist=[m])
    if hasattr(mod, '$fn'):
        f = getattr(mod, '$fn')
        # Decorated functions have a __wrapped__ attribute (functools.wraps).
        is_decorated = hasattr(f, '__wrapped__')
        print('YES' if is_decorated else 'NO')
        break
else:
    print('MISSING')
" 2>/dev/null)
  if [ "$out" = "YES" ]; then ok "@coerce_args on $fn"
  elif [ "$out" = "NO" ]; then fail "$fn found but NOT decorated"
  else fail "$fn not found in any tools module"; fi
done

sect "Entrypoint plugin changes"

# SSE handler — Last-Event-Id support
$VENV_PY -c "
import inspect
from solace_architect_webui_entrypoint.component import SolaceArchitectWebuiComponent as C
src = inspect.getsource(C._sse_chat_stream)
assert 'Last-Event-Id' in src, 'no Last-Event-Id'
assert '_sse_replay' in src, 'no replay buffer'
assert 'retry: 5000' in src, 'no retry directive'
print('OK')
" 2>/dev/null \
  && ok "SSE handler has Last-Event-Id + replay + retry directive" \
  || fail "SSE robustness (A1+A2) not live — reinstall webui-entrypoint editable"

# Heartbeat as named event (A3 depends on this)
$VENV_PY -c "
import inspect
from solace_architect_webui_entrypoint.component import SolaceArchitectWebuiComponent as C
src = inspect.getsource(C._sse_heartbeat)
assert 'event: heartbeat' in src, 'heartbeat still a comment line'
print('OK')
" 2>/dev/null \
  && ok "SSE heartbeat emits named 'heartbeat' event (JS-visible)" \
  || fail "Heartbeat is still a comment line — client stale detector won't work"

# Long-poll fallback route
$VENV_PY -c "
import inspect
from solace_architect_webui_entrypoint.component import SolaceArchitectWebuiComponent as C
assert callable(getattr(C, '_chat_poll', None)), 'no _chat_poll method'
print('OK')
" 2>/dev/null \
  && ok "Long-poll fallback method _chat_poll registered" \
  || fail "/api/chat/poll/{sid} not wired"

# Mark-done recovery route
$VENV_PY -c "
from solace_architect_webui_entrypoint.routes.api import mark_step_done, API_ROUTES
assert callable(mark_step_done), 'mark_step_done missing'
assert any('mark-done' in path for _, path, _ in API_ROUTES), 'route not registered'
print('OK')
" 2>/dev/null \
  && ok "Manual mark-done override route registered" \
  || fail "mark-done route missing — UI safety net + drift banner won't work"

# Per-phase restart routes (review/validation/event-portal/blueprint)
$VENV_PY -c "
from solace_architect_webui_entrypoint.routes.api import (
    reset_discovery, reset_design, reset_review, reset_validation,
    reset_event_portal, reset_blueprint, API_ROUTES,
)
expected = {'discovery','design','review','validation','event-portal','blueprint'}
present = {path.rsplit('/',1)[-1] for m, path, _ in API_ROUTES
           if m == 'DELETE' and '/lifecycle/' not in path}
missing = expected - present
assert not missing, f'missing: {missing}'
print('OK')
" 2>/dev/null \
  && ok "All 6 phase restart routes registered (DELETE /api/engagements/{eid}/{phase})" \
  || fail "Some restart routes missing"

sect "Static-asset (browser-side) changes"

JSPATH="plugins/solace-architect-webui-entrypoint/src/solace_architect_webui_entrypoint/webui/assets/app.js"

for marker in \
    "_buildAutoAdvanceKickoff" \
    "_renderDriftBanner" \
    "_startLongPollFallback" \
    "_dispatchSyntheticSseEvent" \
    "_reconcileAfterReconnect" \
    "designResumable" \
    "_SSE_STALE_MS" \
    "primeKickoff" \
    "agent-error-id" \
    "drift-banner"; do
  if grep -q "$marker" "$JSPATH"; then ok "app.js has $marker"
  else fail "app.js missing $marker — hard-refresh the browser after reinstall"; fi
done

CSSPATH="plugins/solace-architect-webui-entrypoint/src/solace_architect_webui_entrypoint/webui/assets/styles.css"
for marker in "drift-banner" "agent-error-id" "progress-restart-btn" "chat-lifecycle-line2"; do
  if grep -q "$marker" "$CSSPATH"; then ok "styles.css has .$marker"
  else fail "styles.css missing .$marker — hard-refresh after reinstall"; fi
done

sect "Runtime state"

if [ -d "sam/sa_logs" ] || [ -d "sam/logs" ]; then
  ok "SAM log directory exists"
else
  fail "No sam/sa_logs or sam/logs — start SAM first to create it"
fi

if [ -d "sam/configs/agents" ]; then
  AGENT_COUNT=$(ls sam/configs/agents/solace-architect-*.yaml 2>/dev/null | wc -l | tr -d ' ')
  if [ "$AGENT_COUNT" -ge 8 ]; then
    ok "SAM project has $AGENT_COUNT SA agent configs registered"
  else
    fail "Only $AGENT_COUNT SA agents registered — run ./sa-plugins-install.sh"
  fi
else
  fail "No sam/configs/agents — run ./test-harness/bootstrap.sh first"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  printf '\033[1;32m▸ All preflight checks passed.\033[0m Run through test-harness/smoke-checklist.md next.\n'
  exit 0
else
  printf '\033[1;31m▸ Preflight has failures.\033[0m Fix the ✗ items above before starting validation.\n'
  exit 1
fi
