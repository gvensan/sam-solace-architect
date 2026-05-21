# Smoke-test checklist — post-session validation

After restarting SAM with the new code, walk through this checklist on a real engagement.
Each item maps to a specific change we shipped this session — green ticks confirm the
change reached the live environment.

## Pre-flight (do this first)

Run from the monorepo root:

```bash
./test-harness/smoke-preflight.sh
```

The script confirms (a) the venv has the latest editable installs, (b) the
new entry points (`coerce_args`, `/api/chat/poll/{sid}`, `/api/engagements/{eid}/lifecycle/{step}/mark-done`)
are wired, (c) sam.log exists and is writable. If anything is red, fix it
before starting the engagement.

## Manual walk-through

Start a new engagement (or open an existing one) and verify each row:

| What to check | Where | Expected | If it fails |
|---|---|---|---|
| **SSE heartbeat reaches browser** | DevTools → Network → `/api/chat/stream/...` → EventStream tab | A `heartbeat` event every ~15s while idle | Server isn't running new code; reinstall entrypoint editable + restart SAM |
| **EventSource auto-reconnects with Last-Event-Id** | DevTools → Network. Pause a chat turn mid-stream by toggling offline ☑/☐ in DevTools | After re-enabling, browser sends `Last-Event-Id: <N>` on the new EventSource request | A1+A2 not live; check `_sse_replay` is initialised in component.py |
| **Force-reconnect after 30s silence** | Set Chrome → DevTools → Network → "Slow 3G" or block the stream URL temporarily for 35s during an agent turn | Activity bar shows "Reconnecting to agent stream…"; new EventSource opens | A3 not live; grep for `_SSE_STALE_MS` in app.js |
| **Reconcile-after-reconnect** | After a forced reconnect, lifecycle bar reflects whatever the agent did during the gap (no manual refresh) | Bar updates within ~1s of `onopen` | A4 not live; check `_reconcileAfterReconnect` exists |
| **Long-poll fallback (corp-proxy sim)** | Block `/api/chat/stream/*` in DevTools (right-click → Block request URL) and send a chat message | After 3 SSE errors, activity bar shows "Streaming blocked — using long-poll fallback"; events still arrive via `/api/chat/poll/*` every 2s | A5 not live; check `_startLongPollFallback` exists |
| **Full thinking-trace text (no `…`)** | During any tool-heavy agent turn (Design scope, Blueprint pack render) | Activity pills show full tool name + all args, wrapping to multiple lines if needed | Bug in `friendlyToolLabel` or `summarizeToolArgs`; the `trunc` should be a pass-through |
| **Two-line chat header** | Open any engagement | Line 1 = `<Phase> · last: <X>`; Line 2 = `<step note or scope hint>` (italic muted) | `currentStepHint` not being computed; check `refreshLifecycleBar` |
| **Scope corruption fixed** | Run Design phase in auto mode for 3+ scopes; check chat for auto-advance message | "Scopes already completed: topic-design, broker-select, protocol-select" (NOT `[, ", t, o, ...]`) | `@coerce_args` didn't take effect on `record_scope_progress`; reinstall core editable |
| **Restart phase button on each tile** | Open Progress page | Every active/done phase tile (not Intake) shows `↻ Restart` text-link in footer | renderProgressBanner change didn't reach the browser; hard-refresh |
| **Restart modal cascades correctly** | Click `↻ Restart` on Design → confirm by typing project id | Wipes design/* + reviews/* + validation/* + event-portal/* + blueprint/* artifacts; lifecycle status cleared; CTA returns to Start Design | Check `/api/engagements/{eid}/design` DELETE response in DevTools |
| **Resume-from-checkpoint** | Stop an engagement mid-Design (e.g. after scope 3); restart SAM; reopen the engagement | Welcome card shows `Resume Design — scope 4 (integration) →` with the next scope name, not generic "Start Design" | `designResumable` branch isn't firing; check `lifecycle.steps.design.scope_progress` is populated |
| **Drift detection auto-banner** | Manually crash an agent mid-turn (or wait for the case where chat says "complete" but lifecycle stays in-progress) | Amber drift banner appears in chat within 5-10s with "Mark X done →" button | `_detectDriftAndOfferMarkDone` not running; check `pollLifecycle` |
| **Error correlation ID** | Trigger any error (kill an agent process, hit rate limit) | Chat error card header shows `ID a3f9b21c8d` (10-char hex) | server-side `_send_error_to_external` not stamping; check sam.log for `[error_id=…]` |
| **Error ID grep works** | Copy an error ID from the bubble | `grep "error_id=<id>" sam/sa_logs/*.log` returns the full failure context with stack | Logs in different location; check `WEBUI_LOG_DIR` env or sam.log path |

## What to report back

If anything in the table fails, send me:
- The exact item (row number / what failed)
- Browser console output (DevTools → Console)
- Relevant sam.log lines (`tail -100 sam/sa_logs/*.log`)
- Any error IDs from the chat panel

I'll dig in with concrete evidence rather than guessing.

## Quick wins to look out for

These shouldn't need explicit verification — they'll just feel different:

- Mid-turn "Reconnecting…" pill appears briefly instead of dead silence on flaky links
- "RESULT NOT RECEIVED" card fires *less often* — most drops get caught by the 30s force-reconnect now
- Pill labels read like "Reading topic-design/topic-taxonomy.yaml" instead of "Reading topic-de…"
- Restart Discovery / Restart Design feel snappier (cascade is the same, but no need to bounce to chat first)
