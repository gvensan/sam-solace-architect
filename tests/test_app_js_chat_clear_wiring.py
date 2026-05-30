"""Static guard: chat clears on phase restart, and a manual "Clear chat" button exists.

Background — why this test is text-level rather than DOM/integration:
The bug it locks down (chat history not clearing on Restart Discovery / Restart
Design / Restart <phase>) had two distinct root causes:
  1. Server-side cascade wiped the SSE replay buffer, but the visible chat is
     rehydrated from browser localStorage on next load — the wipe wasn't
     end-to-end.
  2. The Discovery and Design restart modals didn't even tell the user the
     chat would be cleared (only the generic per-phase modal did), so the
     intent was hidden.

Both fixes live entirely in app.js (no Python entrypoint test would catch
silent removal of these JS lines), and we have no JS test harness in this
repo — so a grep-level guard is the cheapest way to keep the wiring honest.

Locks down:
  * The `_clearEngagementChatLocal(eid)` helper is defined.
  * Each of the three restart-success paths (Discovery, Design, generic phase)
    calls that helper before closing the modal.
  * The chat-panel "Clear chat" button (`id="chat-clear"`) is declared in HTML
    and its click handler is wired in app.js.
"""

from __future__ import annotations

from pathlib import Path


_WEBUI = (Path(__file__).resolve().parents[1]
          / "plugins" / "solace-architect-webui-entrypoint"
          / "src" / "solace_architect_webui_entrypoint" / "webui")
_APP_JS = _WEBUI / "assets" / "app.js"
_INDEX = _WEBUI / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_clear_engagement_chat_local_helper_defined():
    src = _read(_APP_JS)
    assert "function _clearEngagementChatLocal(eid)" in src
    # The helper has to actually remove the engagement-keyed localStorage
    # entry; without this line, the call sites would be silent no-ops.
    assert "localStorage.removeItem(`solace-architect-chat-log:chat-${eid}`)" in src


def test_every_restart_success_path_clears_chat():
    """Discovery / Design / generic-phase restart success blocks must each
    call _clearEngagementChatLocal(eid) before closeModal — otherwise the
    server-side SSE wipe is cosmetic (UI rehydrates from localStorage)."""
    src = _read(_APP_JS)
    # Exactly three sites cascade-wipe phase hints on restart success
    # (Discovery, Design, generic phase). Each one must be followed by the
    # chat-local clear before closeModal(). Use the cascade line as the
    # anchor — it's unique-per-handler and stable.
    anchors = [
        # Discovery restart cascade
        '["discovery", "design", "review", "validation", "event-portal", "blueprint"]',
        # Design restart cascade
        '["design", "review", "validation", "event-portal", "blueprint"]',
        # Generic-phase restart cascade (uses copy.cascadeSteps)
        "copy.cascadeSteps.forEach(step => _clearPhaseHint(eid, step))",
    ]
    for anchor in anchors:
        idx = src.find(anchor)
        assert idx >= 0, f"restart-cascade anchor missing: {anchor!r}"
        # Look only at the ~600 chars after the cascade line — that's the
        # success block, before the catch-and-restore. Both _clearEngagementChatLocal
        # and closeModal must appear, in that order.
        window = src[idx : idx + 600]
        assert "_clearEngagementChatLocal(eid)" in window, \
            f"_clearEngagementChatLocal(eid) missing after cascade anchor: {anchor!r}"
        clear_at = window.find("_clearEngagementChatLocal(eid)")
        close_at = window.find("closeModal()")
        assert 0 <= clear_at < close_at, \
            f"_clearEngagementChatLocal must run BEFORE closeModal in cascade: {anchor!r}"


def test_clear_chat_button_rendered_and_wired():
    """The chat-panel "Clear chat" affordance — distinct from "New session"
    (which preserves persisted log) and from Restart-on-a-phase (which wipes
    project state). Must be in HTML and have its click handler wired."""
    assert 'id="chat-clear"' in _read(_INDEX)
    src = _read(_APP_JS)
    assert 'getElementById("chat-clear")' in src
    # The handler must call the engagement-local clear; otherwise the
    # button is decorative.
    handler_idx = src.find('getElementById("chat-clear")')
    assert "_clearEngagementChatLocal(eid)" in src[handler_idx : handler_idx + 1500]


def test_discovery_and_design_modal_copy_mentions_chat_clear():
    """Consistency: the generic phase modal already tells users that chat is
    cleared on restart. Discovery and Design must say the same — otherwise
    a user typing the project id to confirm a Discovery/Design restart has
    no warning that their chat scroll-back is about to disappear."""
    src = _read(_APP_JS)
    # Anchor on the modal opener function bodies, then check each window.
    for opener in ("openRestartDiscoveryModal(eid)", "openRestartDesignModal(eid)"):
        idx = src.find("function " + opener)
        assert idx >= 0, f"opener not found: {opener}"
        # Each opener body is well under 3 KB.
        window = src[idx : idx + 3000]
        assert "Chat history for this engagement" in window, \
            f"{opener}: copy must mention chat history clearing"
