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
