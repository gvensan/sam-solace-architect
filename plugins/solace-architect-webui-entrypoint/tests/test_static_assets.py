"""Static asset bundle contract.

The plugin ships a dashboard SPA + intake form. These tests assert the
expected files are physically present in the wheel-shipped layout.
"""

from pathlib import Path


PKG_ROOT = Path(__file__).parent.parent / "src" / "solace_architect_webui_entrypoint"


def test_webui_directory_exists():
    assert (PKG_ROOT / "webui").is_dir()


def test_required_static_files_present():
    webui = PKG_ROOT / "webui"
    required = [
        webui / "index.html",
        webui / "intake" / "index.html",
        webui / "assets" / "styles.css",
        webui / "assets" / "app.js",
    ]
    for p in required:
        assert p.exists(), f"missing static asset: {p.relative_to(PKG_ROOT)}"


def test_dashboard_shell_has_route_aware_nav():
    """Three-pane shell: chat lives in the right panel, NOT in the left sidebar's view nav."""
    html = (PKG_ROOT / "webui" / "index.html").read_text()
    expected_views = ("overview", "timeline", "decisions", "open-items",
                      "artifacts", "stats", "export")
    for v in expected_views:
        assert f'data-view="{v}"' in html, f"missing nav link for view {v!r}"
    # chat is the right-panel surface now — it must NOT be a sidebar nav target
    assert 'data-view="chat"' not in html, "chat should be the right-panel surface, not a sidebar view"


def test_dashboard_shell_has_three_pane_layout():
    """Header has sidebar + chat toggles; layout has sidebar, content, resize handle, chat panel."""
    html = (PKG_ROOT / "webui" / "index.html").read_text()
    for required in ("sidebar-toggle", "chat-toggle", "chat-panel",
                     "chat-resize-handle", "sidebar-backdrop"):
        assert f'id="{required}"' in html, f"missing element id={required!r}"


def test_styles_define_responsive_breakpoints():
    """Chat should collapse to modal below 900px; sidebar to overlay below 768px."""
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 768px)" in css


def test_app_js_persists_layout_state_in_localstorage():
    """Sidebar / chat / chat-width are persisted across reloads."""
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    for key in ("solace-architect-sidebar", "solace-architect-chat",
                "solace-architect-chat-width", "solace-architect-theme"):
        assert key in js, f"missing localStorage key {key!r}"


def test_intake_form_has_required_action_buttons():
    """V1-ported intake has Save draft, Download Markdown/YAML, Submit to architect."""
    html = (PKG_ROOT / "webui" / "intake" / "index.html").read_text()
    assert "saveDraft()" in html
    assert "downloadMD()" in html
    assert "downloadYAML()" in html
    assert "submitToServer()" in html
    assert 'id="btn-submit"' in html


def test_intake_form_calls_v2_submit_endpoint():
    """Submit must POST to V2's /api/intake/submit, not V1's /api/submit."""
    html = (PKG_ROOT / "webui" / "intake" / "index.html").read_text()
    assert "/api/intake/submit" in html, "V2 submit endpoint missing"
    assert "/api/submit'" not in html, "V1 endpoint /api/submit should have been replaced"


def test_intake_form_redirects_to_project_overview_on_success():
    """After submit, the form should route to /projects/{engagement_id}/overview."""
    html = (PKG_ROOT / "webui" / "intake" / "index.html").read_text()
    assert "/projects/" in html
    assert "engagement_id" in html


def test_intake_form_embeds_integration_catalog():
    """V1 form bundles the Integration Hub catalog for offline autocomplete."""
    html = (PKG_ROOT / "webui" / "intake" / "index.html").read_text()
    assert "const CATALOG = " in html
    assert "Amazon S3" in html      # any well-known integration entry
    assert "indirect_paths" in html


def test_dashboard_styles_have_dark_mode_palette():
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    assert '[data-theme="dark"]' in css
    assert "--primary:" in css and "--accent:" in css


# ---------- Visualizer decoupled ----------
# The visualizer was extracted to a standalone repo so it can be run as its
# own process against any broker. The entrypoint no longer serves /visualizer
# routes or ships webui/visualizer/ assets. Assertions below guard against
# accidental re-introduction.


def test_visualizer_bundle_not_shipped():
    """Visualizer was decoupled; bundle must not ship in the wheel."""
    assert not (PKG_ROOT / "webui" / "visualizer").exists(), (
        "webui/visualizer/ should not exist — the visualizer is now a standalone repo. "
        "Delete the directory if it has reappeared."
    )


def test_sidebar_has_no_visualizer_link():
    """Dashboard sidebar must not link to the (removed) embedded visualizer."""
    html = (PKG_ROOT / "webui" / "index.html").read_text()
    assert "visualizer-link" not in html, "index.html still references the removed visualizer link"
    assert "live-nav" not in html, "index.html still has the Diagnostics → Live View section"
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    assert "visualizer-link" not in js, "app.js still wires the removed visualizer link"
    assert "/visualizer" not in js, "app.js still references /visualizer URLs"


def test_chat_send_button_supports_stop_mode():
    """The chat send button must support a STOP mode that POSTs to
    /api/chat/cancel while a task is in flight. Locks in the wiring so
    nobody silently removes the cancel handler.
    """
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    # The toggle helper exists and toggles a `stop-mode` class.
    assert "_setChatInflight" in js, "STOP-mode helper _setChatInflight missing"
    assert "stop-mode" in js, "stop-mode class application missing in app.js"
    # The cancel endpoint is targeted.
    assert "/api/chat/cancel" in js, "STOP button doesn't POST /api/chat/cancel"
    # The CSS styles the STOP variant distinctly.
    assert ".chat-form button.stop-mode" in css, "STOP-mode CSS variant missing"


def test_styles_centers_progress_label():
    """`progress-label` must be center-aligned so multi-word labels like
    'Event Portal' don't left-align inside the centered tile."""
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    # The exact selector + property; brittle on purpose so reformatting
    # doesn't accidentally drop the rule.
    assert ".progress-label" in css
    assert "text-align: center" in css


def test_ep_prov_tile_maps_not_requested_to_na():
    """The EP Prov dashboard tile must render 'N/A' instead of the raw
    'not-requested' enum value (which reads as opaque dashboard noise)."""
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    assert '"not-requested"' in js
    assert '"N/A"' in js
    # And the EP Prov tile uses the mapped variable, not the raw one.
    assert "epProvDisplay" in js, "EP Prov display mapping not wired"


def test_form_card_submits_capture_task_id_for_stop():
    """submitAnswer + submitQuickReply must call _setChatInflight with the
    task_id from the dispatch response. Without this the STOP button stays
    invisible while the agent is processing a form-card reply — the same
    bug user reported on 2026-05-21.
    """
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    # Both helpers must read task_id from the response and arm STOP.
    # Brittle on signature, but that's the load-bearing contract.
    assert "async function submitQuickReply" in js
    assert "async function submitAnswer" in js
    # Both should reference data.task_id after a successful POST. We can't
    # easily verify "inside this specific function" without an AST, so we
    # at least require both _setChatInflight call AND the data.task_id
    # pattern to appear in the file. The submit-handler test already
    # covers the chatForm path; this guards the form-card paths.
    assert js.count("_setChatInflight(data.task_id)") >= 3, (
        "Expected ≥3 _setChatInflight(data.task_id) callsites "
        "(chatForm submit + submitAnswer + submitQuickReply); "
        "STOP button visibility breaks if any go missing."
    )


def test_progress_cta_has_exec_hint_renderer():
    """In-progress cards must include the _phaseExecHint() output below the
    body. Locks in the one-line phase-progress hint feature so a refactor
    can't silently drop it (the user'd lose the "scope 4/9 · updated 2m
    ago" current-state cue).
    """
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    # The helper exists.
    assert "function _phaseExecHint" in js
    assert "function _relTime" in js
    # All 6 in-progress branches inject the hint.
    for phase in ("discovery", "design", "review", "validation",
                  "event-portal", "blueprint"):
        marker = f'_phaseExecHint({{ phase: "{phase}"'
        assert marker in js, f"_phaseExecHint not wired for phase={phase}"
    # CSS class is styled (subtle muted monospace).
    assert ".cta-exec-hint" in css


def test_progress_cta_buttons_disabled_during_inflight():
    """While a chat task is in flight, the Start/Continue/View buttons in
    the green progress-CTA box must be disabled to prevent duplicate
    kickoffs or mid-action navigation. The mechanism: _setChatInflight
    toggles body[data-inflight="1"] and a CSS rule gates the buttons.
    Restart links (cta-link-danger) intentionally stay clickable — escape
    hatch always available.
    """
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    assert "document.body.dataset.inflight" in js, (
        "_setChatInflight must toggle the body data-attribute"
    )
    assert 'body[data-inflight="1"] .progress-cta-actions-row' in css, (
        "CSS rule gating progress-CTA buttons during in-flight is missing"
    )
    assert "pointer-events: none" in css, (
        "Disabled state must prevent click events, not just dim visually"
    )


def test_sse_arms_stop_button_for_any_task_status_update():
    """STOP-button visibility must be derived from the SSE stream, not
    only from dispatch sites. Otherwise orchestrator-initiated tasks
    (peer delegations, auto-advance, anything self-dispatched by the
    agent without a user click) silently keep SEND visible while the
    agent works — the bug user reported on 2026-05-21.

    The contract: TaskStatusUpdateEvent SSE handlers call
    _setChatInflight(ev.data.task_id) when the id differs from the
    current. Lives in BOTH the live-SSE path AND the long-poll
    fallback so behavior is identical regardless of transport.
    """
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    # Both handlers must reference ev.data.task_id and arm STOP.
    assert js.count("ev.data?.task_id || null") >= 2, (
        "Expected ev.data.task_id read in both live-SSE and long-poll "
        "TaskStatusUpdateEvent branches"
    )
    # And both must call _setChatInflight conditional on the id changing.
    assert js.count("_setChatInflight(liveTaskId)") >= 2, (
        "SSE-driven STOP arming missing from one of the two handlers"
    )


def test_tool_call_pill_supports_3_line_clamp_and_expand():
    """Tool-call pills must clamp to 3 lines by default and toggle via
    click. Prevents the wall-of-text behavior the user reported
    (peer_SADomainAgent(task_description='...lots of text...') dumping
    the entire prompt body into the chat panel).
    """
    js = (PKG_ROOT / "webui" / "assets" / "app.js").read_text()
    css = (PKG_ROOT / "webui" / "assets" / "styles.css").read_text()
    # CSS: clamp to 3 lines on .tool-call-args, removable via .expanded
    assert ".activity-pill.tool-call .tool-call-args" in css
    assert "-webkit-line-clamp: 3" in css
    assert ".activity-pill.tool-call.expanded" in css
    # JS: delegated click handler on chatLog toggles .expanded
    assert 'pill.classList.toggle("expanded")' in js
    # Selection-in-progress guard so text-selection isn't interrupted
    assert "sel.toString().length" in js
