/* Solace Architect — dashboard SPA.
 *
 * Three-pane layout:
 *   - left sidebar (collapsible)
 *   - main content (route-based: /, /projects/:id/:view)
 *   - right chat panel (toggleable, resizable)
 *
 * Persistence (localStorage):
 *   - solace-architect-theme: "light" | "dark"
 *   - solace-architect-sidebar: "open" | "closed"
 *   - solace-architect-chat: "open" | "closed"
 *   - solace-architect-chat-width: pixels (number)
 */

(function () {
  "use strict";

  // ============================================================================
  // Build-time configuration constants
  // ============================================================================
  // REVIEW_FAN_OUT_MODE — controls whether the four reviewer agents
  // (Architect, Developer, Ops, Security) run in PARALLEL or SERIAL.
  //
  // - "parallel" — original design. Orchestrator fires all four
  //   peer_<Reviewer>Agent calls in the same turn; reviewers run
  //   concurrently. Fast (~3-5 min for the whole Review phase) but
  //   creates a 4-call burst that some LLM proxies reject with 403
  //   Forbidden under their per-key concurrency cap (see the
  //   2026-05-22 user-report — 4 parallel calls × 3 LiteLLM retries
  //   = 12 concurrent requests).
  //
  // - "serial" — orchestrator awaits each reviewer in sequence:
  //   Architect → Developer → Ops → Security. Slower (~10-15 min)
  //   but works against any proxy. Default.
  //
  // Flip to "parallel" in code when running against a proxy that can
  // sustain the burst. No UI exposure — this is an operator-side
  // choice baked into the build.
  const REVIEW_FAN_OUT_MODE = "serial";

  // Pre-built kickoff strings for both modes. Same SHAPE — both lead
  // with "Phase: review", both end with the read_findings + write
  // reviews/review-summary.md + set_step_status protocol — only the
  // dispatch verb (Fan out / Run sequentially) differs.
  const _REVIEW_KICKOFF_PARALLEL = (
    "Phase: review\n\n" +
    "Run the Review phase. Fan out to peer_SAArchitectReviewerAgent, " +
    "peer_SADeveloperReviewerAgent, peer_SAOpsReviewerAgent, " +
    "peer_SASecurityReviewerAgent IN THIS TURN (parallel — all four " +
    "called concurrently). After all four return, read_findings, " +
    "write reviews/review-summary.md with severity counts + top " +
    "concerns, then set_step_status(step=\"review\", status=...) per " +
    "the rule (DONE if zero critical, DONE_WITH_CONCERNS if any " +
    "critical/important, BLOCKED if any reviewer returned BLOCKED)."
  );
  const _REVIEW_KICKOFF_SERIAL = (
    "Phase: review\n\n" +
    "Run the Review phase. Call the four reviewer agents SEQUENTIALLY " +
    "(one at a time, waiting for each to complete before dispatching " +
    "the next) in this order: peer_SAArchitectReviewerAgent → " +
    "peer_SADeveloperReviewerAgent → peer_SAOpsReviewerAgent → " +
    "peer_SASecurityReviewerAgent. Do NOT dispatch them in parallel — " +
    "the deployment's LLM proxy has a per-key concurrency cap that " +
    "rejects bursts of 4 with 403. After all four have completed, " +
    "read_findings, write reviews/review-summary.md with severity " +
    "counts + top concerns, then set_step_status(step=\"review\", " +
    "status=...) per the rule (DONE if zero critical, " +
    "DONE_WITH_CONCERNS if any critical/important, BLOCKED if any " +
    "reviewer returned BLOCKED)."
  );
  // Single source of truth for the active kickoff. Both call sites
  // (the manual Start Review button + the in-chat phase-handoff card)
  // reference this constant.
  const REVIEW_KICKOFF_BODY = REVIEW_FAN_OUT_MODE === "parallel"
    ? _REVIEW_KICKOFF_PARALLEL
    : _REVIEW_KICKOFF_SERIAL;

  // ============================================================================
  // Persisted state — read once on boot, write on every change
  // ============================================================================
  const STORE = {
    theme:        () => localStorage.getItem("solace-architect-theme") || "light",
    sidebar:      () => localStorage.getItem("solace-architect-sidebar") || "open",
    chat:         () => localStorage.getItem("solace-architect-chat") || "closed",
    chatWidth:    () => parseInt(localStorage.getItem("solace-architect-chat-width") || "360", 10),
    setTheme:     v => localStorage.setItem("solace-architect-theme", v),
    setSidebar:   v => localStorage.setItem("solace-architect-sidebar", v),
    setChat:      v => localStorage.setItem("solace-architect-chat", v),
    setChatWidth: v => localStorage.setItem("solace-architect-chat-width", String(v)),
  };

  // ============================================================================
  // Theme toggle (with Mermaid re-init)
  // ============================================================================
  const themeBtn = document.getElementById("theme-toggle");
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    STORE.setTheme(theme);
    themeBtn.textContent = theme === "dark" ? "☀" : "☾";
    if (window.mermaid) {
      window.mermaid.initialize({ theme: theme === "dark" ? "dark" : "default" });
      document.querySelectorAll(".mermaid").forEach(el => el.removeAttribute("data-processed"));
      window.mermaid.run && window.mermaid.run();
    }
  }
  themeBtn.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });
  applyTheme(STORE.theme());

  // ============================================================================
  // Sidebar toggle
  // ============================================================================
  const sidebarBtn = document.getElementById("sidebar-toggle");
  const sidebarBackdrop = document.getElementById("sidebar-backdrop");
  function applySidebar(state) {
    document.body.setAttribute("data-sidebar", state);
    STORE.setSidebar(state);
  }
  sidebarBtn.addEventListener("click", () => {
    const next = document.body.getAttribute("data-sidebar") === "open" ? "closed" : "open";
    applySidebar(next);
  });
  sidebarBackdrop.addEventListener("click", () => applySidebar("closed"));
  applySidebar(STORE.sidebar());

  // Rail icons (visible when sidebar is collapsed) — both expand the sidebar.
  // The "+ New project" rail icon is an <a href="/intake/new">, so navigation
  // continues naturally; we just flip the persisted state so users return to
  // an expanded sidebar.
  const railActiveProject = document.getElementById("rail-active-project");
  const railNewProject = document.getElementById("rail-new-project");
  railActiveProject?.addEventListener("click", (e) => {
    e.preventDefault();
    applySidebar("open");
  });
  railNewProject?.addEventListener("click", () => applySidebar("open"));

  // ============================================================================
  // Chat panel toggle
  // ============================================================================
  const chatBtn = document.getElementById("chat-toggle");
  const chatClose = document.getElementById("chat-close");
  function applyChat(state) {
    document.body.setAttribute("data-chat", state);
    STORE.setChat(state);
  }
  chatBtn.addEventListener("click", () => {
    const next = document.body.getAttribute("data-chat") === "open" ? "closed" : "open";
    applyChat(next);
    // When opening the chat panel, auto-scroll to the latest message so
    // the user lands on the most recent activity (no manual scroll for
    // a long history). Deferred two frames so any CSS open-transition
    // has laid out the panel and chatLog has a real scrollHeight to
    // measure against.
    if (next === "open") {
      const log = document.getElementById("chat-log");
      if (log) {
        requestAnimationFrame(() => requestAnimationFrame(() => {
          log.scrollTop = log.scrollHeight;
        }));
      }
    }
  });
  chatClose.addEventListener("click", () => applyChat("closed"));
  applyChat(STORE.chat());

  // Apply persisted chat width
  function applyChatWidth(px) {
    const clamped = Math.max(280, Math.min(720, px));
    document.documentElement.style.setProperty("--chat-width", clamped + "px");
    STORE.setChatWidth(clamped);
  }
  applyChatWidth(STORE.chatWidth());

  // ============================================================================
  // Resize handle (drag between main and chat)
  // ============================================================================
  const resizeHandle = document.getElementById("chat-resize-handle");
  let dragState = null;

  resizeHandle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    dragState = { startX: e.clientX, startWidth: STORE.chatWidth() };
    resizeHandle.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragState) return;
    const delta = dragState.startX - e.clientX;       // dragging left → grow chat
    applyChatWidth(dragState.startWidth + delta);
  });
  document.addEventListener("mouseup", () => {
    if (!dragState) return;
    dragState = null;
    resizeHandle.classList.remove("dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });

  // ============================================================================
  // Keyboard: Esc closes the chat panel when focused inside it
  // ============================================================================
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.getAttribute("data-chat") === "open") {
      // Only close if focus is inside the chat panel (avoid surprising the user)
      const chatPanel = document.getElementById("chat-panel");
      if (chatPanel && chatPanel.contains(document.activeElement)) {
        applyChat("closed");
      }
    }
  });

  // ============================================================================
  // Current user — populate header chip + redirect to /login if anon and required
  // ============================================================================
  let currentUser = null;

  // Single source of truth for "session expired — bounce to login". Preserves
  // the current path as ?return_to= so the user lands back where they were
  // after re-authenticating. Idempotent (safe to call multiple times; only
  // the first call navigates).
  let _redirectingToLogin = false;
  function redirectToLoginPreservingPath() {
    if (_redirectingToLogin) return;
    _redirectingToLogin = true;
    // Login page reads ?next= and posts it back to /api/auth/login as `next`,
    // which the server uses to compute the post-login redirect target.
    const ret = window.location.pathname + window.location.search;
    window.location.href = "/login?next=" + encodeURIComponent(ret);
  }

  async function loadCurrentUser() {
    try {
      const r = await fetch("/api/auth/me");
      const d = await r.json();
      const chip = document.getElementById("user-chip");
      const logoutBtn = document.getElementById("logout-btn");
      const settingsLink = document.getElementById("settings-link");
      if (d.authenticated) {
        chip.textContent = d.user.name;
        chip.title = d.user.email || "";
        chip.classList.add("authenticated");
        logoutBtn?.classList.remove("hidden");
        settingsLink?.classList.remove("hidden");
      } else if (d.require_auth) {
        redirectToLoginPreservingPath();
        return null;
      } else {
        chip.textContent = "anonymous (dev)";
        logoutBtn?.classList.add("hidden");
        settingsLink?.classList.remove("hidden");
      }
      currentUser = d;
      return d;
    } catch (e) {
      console.error("Failed to load /api/auth/me", e);
      return null;
    }
  }

  // Periodic auth check — catches session expiry while the user is sitting
  // on the dashboard. Without this, the first sign that auth has lapsed is
  // a failed chat POST with a generic 'translate failed' error. 60s polls
  // are cheap (one no-store JSON call) and stop the silent-death class of
  // bug where SSE has died but the UI still claims connected.
  function startAuthHeartbeat() {
    setInterval(async () => {
      try {
        const r = await fetch("/api/auth/me", { cache: "no-store" });
        if (!r.ok) return;
        const d = await r.json();
        // Session lapsed (auth required but we're no longer authenticated).
        if (d.require_auth && !d.authenticated) {
          redirectToLoginPreservingPath();
        }
      } catch (_) { /* network blip — try again next tick */ }
    }, 60_000);
  }
  startAuthHeartbeat();

  // Wrap window.fetch to detect 401 on any /api/* call and bounce to login
  // immediately rather than letting the calling code show a cryptic error.
  // Only triggers for same-origin /api/ paths so external fetches (e.g. by
  // future widgets) keep their own error semantics.
  const _nativeFetch = window.fetch.bind(window);
  window.fetch = async function(resource, init) {
    const res = await _nativeFetch(resource, init);
    try {
      const url = typeof resource === "string" ? resource : (resource && resource.url) || "";
      if (res.status === 401 && url.startsWith("/api/")) {
        redirectToLoginPreservingPath();
      }
    } catch (_) { /* defensive — don't let the wrapper mask the response */ }
    return res;
  };

  // Logout button — calls window.__logout (defined later) on click
  document.getElementById("logout-btn")?.addEventListener("click", async () => {
    if (window.__logout) await window.__logout();
  });

  // ============================================================================
  // Project list
  // ============================================================================
  let projects = [];
  let projectSearchTerm = "";
  // Sidebar always loads the full list (archived included) so the "Show
  // archived" toggle is a pure client-side filter — no extra round-trip
  // when the user flips it. Persisted across reloads via localStorage so
  // a user who normally works with archived projects doesn't have to
  // re-enable it every session.
  let showArchived = localStorage.getItem("sa-show-archived") === "1";
  async function loadProjects() {
    const r = await fetch("/api/projects?include_archived=1");
    projects = await r.json();
    renderSidebarProjects();
  }
  function renderSidebarProjects() {
    const list = document.getElementById("project-list");
    const toggle = document.getElementById("show-archived");
    if (toggle) toggle.checked = showArchived;
    const filter = projectSearchTerm.trim().toLowerCase();
    const visible = projects.filter(p => {
      if (!showArchived && p.status === "archived") return false;
      if (filter && !(p.name || "").toLowerCase().includes(filter)) return false;
      return true;
    });
    if (!projects.length) {
      list.innerHTML = '<div class="empty-hint">No projects yet.</div>';
    } else if (!visible.length) {
      list.innerHTML = filter
        ? '<div class="empty-hint">No projects match.</div>'
        : '<div class="empty-hint">No active projects. Enable "Show archived" to see archived ones.</div>';
    } else {
      const active = currentProjectId();
      list.innerHTML = visible.map(p => {
        const isArchived = p.status === "archived";
        const label = isArchived ? `${escapeHtml(p.name)} <span class="archived-tag">archived</span>`
                                 : escapeHtml(p.name);
        return `<div class="project-link-row${isArchived ? " archived" : ""}">
           <a href="/projects/${encodeURIComponent(p.id)}/overview"
              class="project-link${p.id === active ? " active" : ""}"
              data-route>${label}</a>
           <button class="project-action-btn" title="Project actions"
                   data-project-actions="${escapeHtml(p.id)}" aria-label="Project actions">⋯</button>
         </div>`;
      }).join("");
    }
    renderSidebarRail();
  }

  // Wire sidebar search filter
  document.getElementById("project-search")?.addEventListener("input", (e) => {
    projectSearchTerm = e.target.value || "";
    renderSidebarProjects();
  });

  // "Show archived" toggle — pure client-side filter; we already loaded
  // the full list (include_archived=1) when the sidebar booted.
  document.getElementById("show-archived")?.addEventListener("change", (e) => {
    showArchived = !!e.target.checked;
    localStorage.setItem("sa-show-archived", showArchived ? "1" : "0");
    renderSidebarProjects();
  });

  // Delegated handler for the kebab menu (rename / clone / archive)
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-project-actions]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const pid = btn.getAttribute("data-project-actions");
    const proj = projects.find(p => p.id === pid);
    if (!proj) return;
    openProjectActionsModal(proj);
  });

  function renderSidebarRail() {
    const railProj = document.getElementById("rail-active-project");
    if (!railProj) return;
    const activeId = currentProjectId();
    const activeProject = activeId ? projects.find(p => p.id === activeId) : null;
    if (activeProject) {
      const initial = (activeProject.name || "?").trim().charAt(0).toUpperCase() || "?";
      railProj.querySelector(".rail-letter").textContent = initial;
      railProj.title = `${activeProject.name} — click to expand sidebar`;
      railProj.classList.remove("hidden");
    } else {
      railProj.classList.add("hidden");
    }
  }

  // ============================================================================
  // Router — pushState for SPA paths only; /intake/* falls through to browser
  // ============================================================================
  function isSpaPath(href) {
    return href === "/" || href.startsWith("/projects/") || href === "/settings";
  }
  function navigate(path, push = true) {
    if (push) window.history.pushState({}, "", path);
    render();
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    const href = a.getAttribute("href");
    if (!href || href.startsWith("http") || href.startsWith("#")) return;
    if (!isSpaPath(href)) return;     // browser handles /intake/*, /login, etc.
    e.preventDefault();
    navigate(href);
  });
  window.addEventListener("popstate", () => render(false));

  function currentPath() { return window.location.pathname; }
  function currentProjectId() {
    const m = currentPath().match(/^\/projects\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }
  function currentView() {
    const m = currentPath().match(/^\/projects\/[^/]+\/([^/]+)/);
    return m ? m[1] : "overview";
  }

  // ============================================================================
  // Render dispatch
  // ============================================================================

  // Auto-refresh timer for the Progress view. Cleared on every render()
  // and re-armed by VIEWS.overview at the end of its render. Pauses
  // when the tab is hidden so we don't burn cycles in background tabs.
  let progressRefreshTimer = null;
  const PROGRESS_REFRESH_MS = 10000;

  function clearProgressAutoRefresh() {
    if (progressRefreshTimer) {
      clearInterval(progressRefreshTimer);
      progressRefreshTimer = null;
    }
  }

  function armProgressAutoRefresh(eid) {
    clearProgressAutoRefresh();
    progressRefreshTimer = setInterval(() => {
      // Skip the tick while tab is hidden — picks up on visibility return.
      if (document.hidden) return;
      // Skip if we navigated away while the timer was queued.
      if (currentView() !== "overview" || currentProjectId() !== eid) {
        clearProgressAutoRefresh();
        return;
      }
      // Silent re-render — same VIEWS.overview, fetches fresh data.
      const content = document.getElementById("content");
      if (content) VIEWS.overview(content, eid);
      // Also refresh the sticky chat lifecycle bar so it tracks state.
      refreshLifecycleBar();
    }, PROGRESS_REFRESH_MS);
  }

  // Separate lighter-weight refresh timer for the chat lifecycle bar
  // that runs on ANY view (not just Progress) so the bar stays current
  // while the user is on Requirements, Decisions, etc. Slower cadence
  // since it's just one indicator strip.
  let lifecycleBarTimer = null;
  function armLifecycleBarRefresh() {
    if (lifecycleBarTimer) clearInterval(lifecycleBarTimer);
    lifecycleBarTimer = setInterval(() => {
      if (document.hidden) return;
      if (!currentProjectId()) return;
      // Skip if Progress is already polling — its tick covers the bar.
      if (currentView() === "overview" && progressRefreshTimer) return;
      refreshLifecycleBar();
    }, 15000);
  }

  // Catch visibility-return so the user sees fresh state the moment
  // they switch back to the tab, not 10s later.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && progressRefreshTimer) {
      const content = document.getElementById("content");
      const eid = currentProjectId();
      if (content && eid && currentView() === "overview") VIEWS.overview(content, eid);
    }
  });

  async function render() {
    clearProgressAutoRefresh();  // any navigation cancels the timer
    const path = currentPath();
    const content = document.getElementById("content");
    const projectNav = document.getElementById("project-nav");

    renderSidebarProjects();
    // Lifecycle bar reflects current path's project on every render.
    refreshLifecycleBar();
    if (!lifecycleBarTimer) armLifecycleBarRefresh();

    const eid = currentProjectId();
    if (eid) {
      projectNav.classList.remove("hidden");
      projectNav.querySelectorAll(".nav-link").forEach(a => {
        const view = a.dataset.view;
        a.href = `/projects/${encodeURIComponent(eid)}/${view}`;
        a.classList.toggle("active", view === currentView());
      });
    } else {
      projectNav.classList.add("hidden");
    }

    // Chat is no longer project-gated — it targets any agent on the SAM mesh.
    // If a project is active, its id is sent as engagement_id metadata so the
    // agent can scope its work; otherwise the chat is project-free.
    const chatInput = document.getElementById("chat-input");
    const chatSend = document.getElementById("chat-send-btn");
    chatInput.disabled = false;
    if (chatSend) chatSend.disabled = false;
    const agentSelect = document.getElementById("chat-agent-select");
    const agentName = agentSelect?.value || "the selected agent";
    chatInput.placeholder = eid
      ? `Message ${agentName} about ${eid}…`
      : `Message ${agentName}…`;

    // Re-anchor the chat session to the current project context.
    if (typeof syncChatProjectContext === "function") syncChatProjectContext();

    if (path === "/" || path === "") return renderHome(content);
    if (path === "/settings") return renderSettingsView(content);

    if (eid) {
      const view = currentView();
      const fn = VIEWS[view] || VIEWS.overview;
      return fn(content, eid);
    }

    content.innerHTML = `<div class="welcome"><h1>Not found</h1>
      <p>Path <code>${escapeHtml(path)}</code> doesn't match any route.</p>
      <p><a href="/">← back to projects</a></p></div>`;
  }

  async function renderHome(root) {
    if (!projects.length) {
      root.innerHTML = `
        <div class="empty-state">
          <h1>Welcome to Solace Architect</h1>
          <p>You don't have any projects yet. Start by creating one — the intake form
             walks you through discovery, scopes the design work, and shows you
             which agents will run.</p>
          <a href="/intake/new" class="cta-btn">Create your first project →</a>
        </div>`;
      return;
    }
    root.innerHTML = `
      <div class="project-cards-wrap">
        <div class="project-cards-header">
          <h1>Projects</h1>
          <a href="/intake/new" class="cta-btn">+ New project</a>
        </div>
        <div class="project-cards">
          ${projects.map(p => `
            <a class="project-card" href="/projects/${encodeURIComponent(p.id)}/overview" data-route>
              <div class="project-card-name">${escapeHtml(p.name)}</div>
              <div class="project-card-meta">
                <span class="project-card-owner">${escapeHtml(p.owner || "—")}</span>
                <span class="project-card-status status-${p.status || "active"}">${escapeHtml(p.status || "active")}</span>
              </div>
              <div class="project-card-date">Last active ${formatDate(p.last_active_at)}</div>
            </a>
          `).join("")}
        </div>
      </div>`;
  }

  // ============================================================================
  // Per-view renderers
  // ============================================================================
  const VIEWS = {
    overview: async (root, eid) => {
      try {
        const [stats, intakeRes, artifacts, lifecycle, openItems] = await Promise.all([
          fetch(`/api/engagements/${encodeURIComponent(eid)}/overview`).then(r => r.json()),
          fetch(`/api/intake/load/${encodeURIComponent(eid)}`).then(r => r.json()),
          fetch(`/api/engagements/${encodeURIComponent(eid)}/artifacts`).then(r => r.json()).catch(() => []),
          fetch(`/api/engagements/${encodeURIComponent(eid)}/lifecycle`).then(r => r.json()).catch(() => ({ steps: {} })),
          // Fetch ALL open items (not just blocking) — we use the wider
          // set to detect per-source agent activity as a fallback for
          // missing set_step_status calls. Downstream consumers in this
          // render that need blocking-only filter their own subset
          // (e.g. blueprintBlockers below).
          fetch(`/api/engagements/${encodeURIComponent(eid)}/open-items?status=open`).then(r => r.json()).catch(() => []),
        ]);
        const intake = (intakeRes && intakeRes.intake) || {};
        const activeProject = projects.find(p => p.id === eid);
        const statusValue = activeProject?.status || "active";
        const hasIntake = artifacts.some(a => a === "discovery/intake.json");
        const hasDiscoveryBrief = artifacts.some(a => a === "discovery/discovery-brief.yaml");
        const hasDiscoverySummary = artifacts.some(a => a === "discovery/discovery-summary.md");
        const openItemsCount = (stats.open_items_blocking || 0) + (stats.open_items_advisory || 0);

        // Authoritative source: meta/engagement-status.yaml written by the
        // agent at end-of-turn (set_step_status). File-existence alone is
        // too fragile — an empty summary made Discovery look done when the
        // brief was unusable.
        const discoveryStatus = lifecycle?.steps?.discovery?.status || "NOT_STARTED";
        const discoveryNote = lifecycle?.steps?.discovery?.note || "";
        const discoveryDone = discoveryStatus === "DONE" || discoveryStatus === "DONE_WITH_CONCERNS";
        // In-progress when the agent has TOUCHED the step at all. Three
        // independent signals so a missed set_step_status on the agent
        // side doesn't strand the CTA on "Discovery hasn't run yet"
        // while the agent is mid-Q&A:
        //   1. lifecycle status set (the authoritative source when
        //      set_step_status was called).
        //   2. discovery-summary.md present (Discovery's narrative output).
        //   3. any open-item with source="discovery" — agent definitely
        //      ran at least one turn if it recorded a follow-up question.
        // NB: do NOT key off discovery-brief.yaml here — the brief is
        // an INTAKE output (intake_submit writes it), so its presence
        // after a clone or a fresh intake submission would falsely
        // advance the dashboard. Same reason we don't include the
        // top-level openItemsCount: intake-sourced items can land
        // before Discovery touches the engagement. Per-source filter
        // narrows to the agent's own follow-ups.
        const hasDiscoverySourcedItems = Array.isArray(openItems)
          && openItems.some(i => i?.source === "discovery");
        const discoveryInProgress = !discoveryDone && (
          (discoveryStatus !== "NOT_STARTED")
          || hasDiscoverySummary
          || hasDiscoverySourcedItems
        );

        // Same for Design — driven by SADomainAgent's set_step_status calls.
        const designStatus = lifecycle?.steps?.design?.status || "NOT_STARTED";
        const designNote = lifecycle?.steps?.design?.note || "";
        const designDone = designStatus === "DONE" || designStatus === "DONE_WITH_CONCERNS";
        // Any artifact under a Domain scope folder means design is mid-flow.
        const designScopes = ["topic-design","broker-select","protocol-select","integration","mesh-design","ha-dr","sam-design","event-portal","migration"];
        const hasDesignArtifact = artifacts.some(a => designScopes.some(s => a.startsWith(s + "/")));
        const hasDomainSourcedItems = Array.isArray(openItems)
          && openItems.some(i => i?.source === "domain");
        const designInProgress = !designDone && (
          (designStatus !== "NOT_STARTED")
          || hasDesignArtifact
          || hasDomainSourcedItems
        );

        // Same for Review — driven by SAOrchestratorAgent's set_step_status
        // for step="review" after the 4 reviewers return. A review artifact
        // (reviews/*-review.md) means at least one reviewer finished even if
        // the orchestrator hasn't aggregated yet. source="review-deferred"
        // open-items mean at least one reviewer deferred a finding for the
        // user — that also implies Review ran.
        const reviewStatus = lifecycle?.steps?.review?.status || "NOT_STARTED";
        const reviewNote = lifecycle?.steps?.review?.note || "";
        const reviewDone = reviewStatus === "DONE" || reviewStatus === "DONE_WITH_CONCERNS";
        const hasReviewArtifact = artifacts.some(a => a.startsWith("reviews/"));
        const hasReviewDeferredItems = Array.isArray(openItems)
          && openItems.some(i => i?.source === "review-deferred");
        const reviewInProgress = !reviewDone && (
          (reviewStatus !== "NOT_STARTED")
          || hasReviewArtifact
          || hasReviewDeferredItems
        );

        // Validation — SAValidationAgent writes validation/validation-report.{md,yaml}
        // and calls set_step_status(step="validation"). Direct-dispatched.
        // Validation's only artifact lands at the END, so without the
        // IN_PROGRESS at-task-start signal the dashboard wrongly shows
        // "Validation hasn't run yet" for the entire 30+ second run.
        // source="validation" open-items catch the case where the agent
        // recorded a blocking issue mid-run before the final report.
        const validationStatus = lifecycle?.steps?.validation?.status || "NOT_STARTED";
        const validationNote = lifecycle?.steps?.validation?.note || "";
        const validationDone = validationStatus === "DONE" || validationStatus === "DONE_WITH_CONCERNS";
        const hasValidationArtifact = artifacts.some(a => a.startsWith("validation/"));
        const hasValidationSourcedItems = Array.isArray(openItems)
          && openItems.some(i => i?.source === "validation");
        const validationInProgress = !validationDone && (
          (validationStatus !== "NOT_STARTED")
          || hasValidationArtifact
          || hasValidationSourcedItems
        );

        // Event Portal — SAEventPortalAgent (MCP-backed) writes
        // event-portal/* in lifecycle mode. Slots between Validation and
        // Blueprint so the live tenant gets populated against the
        // validated design before the final package is assembled.
        const eventPortalStatus = lifecycle?.steps?.["event-portal"]?.status || "NOT_STARTED";
        const eventPortalNote = lifecycle?.steps?.["event-portal"]?.note || "";
        // SKIPPED counts as "done for advancement purposes" — the CTA chain
        // should hop over it just like a DONE phase. Without this, opt-out
        // engagements (intake.preferences.provision_event_portal=false)
        // would stall at "Start Event Portal" forever because the lifecycle
        // would report event-portal as NOT_STARTED/SKIPPED, never DONE.
        const eventPortalSkipped = eventPortalStatus === "SKIPPED";
        const eventPortalDone = eventPortalStatus === "DONE"
          || eventPortalStatus === "DONE_WITH_CONCERNS"
          || eventPortalSkipped;
        // `event-portal/` ALSO holds the DESIGN-phase model (event-portal-model.yaml
        // + its rendered .md companion). Those are Design outputs, not provisioning
        // artifacts — so they must NOT flip the Event Portal PROVISIONING phase to
        // "in progress". If they did, the CTA would jump straight past Review and
        // Validation to a premature provisioning dispatch the moment Design finished.
        // Only genuine provisioning artifacts (plan/provisioned/report/asyncapi) count.
        const EP_DESIGN_ARTIFACTS = new Set([
          "event-portal/event-portal-model.yaml",
          "event-portal/event-portal.md",
        ]);
        const hasEventPortalArtifact = artifacts.some(
          a => a.startsWith("event-portal/") && !EP_DESIGN_ARTIFACTS.has(a));
        const hasEventPortalSourcedItems = Array.isArray(openItems)
          && openItems.some(i => i?.source === "event-portal");
        const eventPortalInProgress = !eventPortalDone && (
          (eventPortalStatus !== "NOT_STARTED" && eventPortalStatus !== "SKIPPED")
          || hasEventPortalArtifact
          || hasEventPortalSourcedItems
        );

        // Blueprint — SABlueprintAgent writes blueprint/* + exports/engagement-package.zip.
        // Same vulnerability as Validation: blueprint's artifacts all land at the
        // end of the assembly run. Without the at-task-start IN_PROGRESS signal,
        // the dashboard wrongly shows "Blueprint hasn't run yet" for the full
        // assembly window. Blueprint doesn't typically record open-items, so
        // there's no per-source fallback for it — pure lifecycle + artifact.
        const blueprintStatus = lifecycle?.steps?.blueprint?.status || "NOT_STARTED";
        const blueprintNote = lifecycle?.steps?.blueprint?.note || "";
        const blueprintDone = blueprintStatus === "DONE" || blueprintStatus === "DONE_WITH_CONCERNS";
        const hasBlueprintArtifact = artifacts.some(a => a.startsWith("blueprint/") || a.startsWith("exports/"));
        const blueprintInProgress = !blueprintDone && (
          (blueprintStatus !== "NOT_STARTED")
          || hasBlueprintArtifact
        );

        // Active step on the lifecycle banner. Order matches PHASE_NEXT:
        // intake → discovery → design → review → validation → event-portal → blueprint.
        const activeStepId = blueprintDone ? "complete"
          : (blueprintInProgress || eventPortalDone) ? "blueprint"
          : (eventPortalInProgress || validationDone) ? "event-portal"
          : (validationInProgress || reviewDone) ? "validation"
          : (reviewInProgress || designDone) ? "review"
          : (designInProgress || discoveryDone) ? "design"
          : (discoveryInProgress || hasIntake) ? "discovery"
          : "intake";
        const completedSteps = new Set();
        if (hasIntake) completedSteps.add("intake");
        if (discoveryDone) completedSteps.add("discovery");
        if (designDone) completedSteps.add("design");
        if (reviewDone) completedSteps.add("review");
        if (validationDone) completedSteps.add("validation");
        if (eventPortalDone) completedSteps.add("event-portal");
        if (blueprintDone) completedSteps.add("blueprint");

        // Steps the agent has flagged as "waiting for the user" via
        // set_step_status(status="NEEDS_CONTEXT"). Visually distinct from
        // both "active" (running) and "not started" so a glance at the
        // banner tells the user where their attention is needed.
        const needsContextSteps = new Set();
        const _isNeedsCtx = (s) => s?.status === "NEEDS_CONTEXT";
        if (_isNeedsCtx(lifecycle?.steps?.discovery))    needsContextSteps.add("discovery");
        if (_isNeedsCtx(lifecycle?.steps?.design))       needsContextSteps.add("design");
        if (_isNeedsCtx(lifecycle?.steps?.review))       needsContextSteps.add("review");
        if (_isNeedsCtx(lifecycle?.steps?.validation))   needsContextSteps.add("validation");
        if (_isNeedsCtx(lifecycle?.steps?.["event-portal"])) needsContextSteps.add("event-portal");
        if (_isNeedsCtx(lifecycle?.steps?.blueprint))    needsContextSteps.add("blueprint");

        // Steps the routing engine skipped (e.g. event-portal opt-out via
        // preferences.provision_event_portal=false). Rendered muted so the
        // user understands "intentionally skipped" vs "not yet reached".
        // Two sources:
        //   1. stats.skip_reasons — routing-derived (skill-routing.yaml + brief)
        //   2. lifecycle.steps[X].status === "SKIPPED" — explicit write
        //      (e.g. intake_submit writes event-portal SKIPPED on opt-out
        //      so the dashboard knows immediately, even before any agent
        //      run touches the routing layer).
        const skippedSteps = new Set();
        const _bannerStepIds = new Set([
          "discovery", "design", "review", "validation", "event-portal", "blueprint",
        ]);
        for (const sr of (stats.skip_reasons || [])) {
          if (sr?.step && _bannerStepIds.has(sr.step)) skippedSteps.add(sr.step);
        }
        for (const stepId of _bannerStepIds) {
          if (lifecycle?.steps?.[stepId]?.status === "SKIPPED") skippedSteps.add(stepId);
        }

        // Phases that returned BLOCKED — Validation typically, but any
        // agent can mark its step BLOCKED when blocking open-items remain
        // unresolved. The banner renders these with a red border + ⛔ icon
        // and the welcome card refuses to chain advancement past them.
        const blockedSteps = new Set();
        for (const stepId of _bannerStepIds) {
          if (lifecycle?.steps?.[stepId]?.status === "BLOCKED") blockedSteps.add(stepId);
        }

        // Blocking open-items affecting Blueprint — typically recorded by
        // SAValidationAgent with affecting_step="blueprint". When any are
        // open, Start Blueprint must be disabled. Without this gate, the
        // user can bypass validation guardrails on a DONE_WITH_CONCERNS
        // verdict.
        const blueprintBlockers = Array.isArray(openItems)
          ? openItems.filter(i => i?.affecting_step === "blueprint" && i?.status === "open")
          : [];

        // One contextual CTA, always shown — content depends on lifecycle state.
        // lifecycle + stats are forwarded so the in-progress cards can render
        // a one-line execution hint (current scope / open items / "updated Xm ago")
        // below the body. See _phaseExecHint() for what each phase contributes.
        // execution_mode comes from the intake form (auto | interactive),
        // propagated into session.yaml at intake-submit time and surfaced
        // here by compute_overview_stats. Drives single-button CTAs for
        // Design + Event Portal (the only two phases with a mode choice)
        // instead of asking the user to pick the pace again. Cached in
        // localStorage so renderPhaseHandoffCard (called from SSE
        // handlers, no direct access to stats here) can pick it up.
        const executionMode = (stats?.execution_mode === "auto") ? "auto" : "interactive";
        rememberExecutionMode(eid, executionMode);
        const cta = renderProgressCta({
          eid, hasIntake, discoveryStatus, discoveryNote,
          discoveryInProgress, openItemsCount,
          designStatus, designNote, designDone, designInProgress,
          reviewStatus, reviewNote, reviewDone, reviewInProgress,
          validationStatus, validationNote, validationDone, validationInProgress,
          eventPortalStatus, eventPortalNote, eventPortalDone, eventPortalInProgress,
          blueprintStatus, blueprintNote, blueprintDone, blueprintInProgress,
          blueprintBlockers, lifecycle, stats, executionMode,
        });

        root.innerHTML = `
          <h1>Progress</h1>
          ${renderProgressBanner({
            eid,
            active: activeStepId,
            completed: completedSteps,
            needsContext: needsContextSteps,
            skipped: skippedSteps,
            blocked: blockedSteps,
            stats,
          })}
          ${cta}

          <!-- Compact engagement-state tiles. Status is the first tile (Progress only);
               Activities lives on Decisions. -->
          ${renderHeroTiles(stats, { statusValue, includeActivities: false })}
        `;
        wireProgressCtaActions(root, eid, activeStepId);
        // Keep the running scope visible in the (scrollable) design checklist.
        // rAF so layout is settled before we measure rects. Re-runs on every
        // auto-refresh below, so the view tracks the scope as it advances.
        requestAnimationFrame(() => _scrollChecklistToActive(root));
        // Self-refresh every PROGRESS_REFRESH_MS so the banner / CTA /
        // tiles update without a manual reload while the user watches
        // discovery / design / etc complete in chat.
        armProgressAutoRefresh(eid);
      } catch (e) {
        root.innerHTML = `<div class="welcome"><h1>Overview unavailable</h1><p>${escapeHtml(e.message || e)}</p></div>`;
      }
    },

    // Requirements view — the intake-derived content (project metadata,
    // landscape, requirements, goals) that used to be tacked onto the
    // bottom of Overview. Lives under its own sidebar entry so Progress
    // stays focused on engagement state.
    requirements: async (root, eid) => {
      try {
        const intakeRes = await fetch(`/api/intake/load/${encodeURIComponent(eid)}`).then(r => r.json());
        const intake = (intakeRes && intakeRes.intake) || {};
        root.innerHTML = `
          <h1>Requirements</h1>
          <p class="muted" style="margin-top:-4px;margin-bottom:18px;font-size:13px;">
            Submitted intake for this engagement. SADiscoveryAgent enriches this into
            <code>discovery/discovery-brief.yaml</code> as discovery progresses.
          </p>
          ${renderIntakeBrief(intake)}
        `;
      } catch (e) {
        root.innerHTML = `<div class="welcome"><h1>Requirements unavailable</h1><p>${escapeHtml(e.message || e)}</p></div>`;
      }
    },

    timeline: async (root, eid) => {
      const entries = await fetch(`/api/engagements/${encodeURIComponent(eid)}/timeline`).then(r => r.json());
      root.innerHTML = `<h1>Timeline</h1>` +
        (entries.length === 0 ? "<p>No timing data yet.</p>" :
          `<table><thead><tr><th>Skill</th><th>Execution</th><th>User wait</th><th>Wall</th></tr></thead><tbody>` +
          entries.map(e => `<tr><td>${escapeHtml(e.skill)}</td><td>${e.execution_seconds}s</td><td>${e.user_wait_seconds}s</td><td>${e.wall_seconds}s</td></tr>`).join("") +
          `</tbody></table>`);
    },

    decisions: async (root, eid) => {
      const [items, stats] = await Promise.all([
        fetch(`/api/engagements/${encodeURIComponent(eid)}/decisions`).then(r => r.json()),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/overview`).then(r => r.json()),
      ]);
      const skipReasons = stats.skip_reasons || [];

      const decisionsSection = items.length === 0
        ? `<p class="muted">No decisions recorded yet. Decisions are appended by agents as the engagement progresses.</p>`
        : `<table><thead><tr><th>ID</th><th>Context</th><th>Selected</th><th>Rationale</th><th>Source</th></tr></thead><tbody>` +
            items.map(d => `<tr>
              <td><code>${escapeHtml(d.id)}</code></td>
              <td>${escapeHtml(d.context)}</td>
              <td><strong>${escapeHtml(d.selected)}</strong></td>
              <td>${escapeHtml(d.rationale)}</td>
              <td class="muted">${escapeHtml(d.source_agent || "—")}</td>
            </tr>`).join("") +
          `</tbody></table>`;

      const routingSection = skipReasons.length === 0
        ? `<p class="muted">No activities were skipped — every step in <code>skill-routing.yaml</code> applied to this engagement.</p>`
        : `<table><thead><tr><th>Activity</th><th>Skip reason</th></tr></thead><tbody>` +
            skipReasons.map(s => `<tr>
              <td><code>${escapeHtml(s.step)}</code></td>
              <td>${escapeHtml(s.reason)}</td>
            </tr>`).join("") +
          `</tbody></table>`;

      root.innerHTML = `
        <h1>Decisions</h1>

        <!-- Hero tiles: includes the Activities tile (Decisions is the home for execution state) -->
        ${renderHeroTiles(stats, { includeActivities: true })}

        <section class="brief-section">
          <h2>Recorded decisions</h2>
          <p class="brief-section-hint">Architectural choices the agents committed to during the engagement (append-only audit trail).</p>
          ${decisionsSection}
        </section>

        <section class="brief-section">
          <h2>Routing decisions</h2>
          <p class="brief-section-hint">Activities that <code>skill-routing.yaml</code> determined were not applicable to this engagement, based on the intake.</p>
          ${routingSection}
        </section>
      `;
    },

    "open-items": async (root, eid) => {
      const items = await fetch(`/api/engagements/${encodeURIComponent(eid)}/open-items?status=open`).then(r => r.json());
      root.innerHTML = `<h1>Open Items</h1>` +
        (items.length === 0 ? "<p>No open items.</p>" :
          `<table><thead><tr><th>ID</th><th>Severity</th><th>Source</th><th>Description</th><th></th></tr></thead><tbody>` +
          items.map(q => `<tr>
            <td>${escapeHtml(q.id)}</td>
            <td>${escapeHtml(q.severity)}</td>
            <td>${escapeHtml(q.source)}</td>
            <td>${escapeHtml(q.description)}</td>
            <td><button class="copy-btn" data-resolve-item="${escapeHtml(q.id)}" data-desc="${escapeHtml(q.description || "")}">Resolve</button></td>
          </tr>`).join("") +
          `</tbody></table>`);
      root.querySelectorAll("[data-resolve-item]").forEach(btn => {
        btn.addEventListener("click", () =>
          openResolveItemModal(eid, btn.dataset.resolveItem, btn.dataset.desc));
      });
    },

    artifacts: async (root, eid) => {
      const names = await fetch(`/api/engagements/${encodeURIComponent(eid)}/artifacts`).then(r => r.json());

      if (!names.length) {
        root.innerHTML = `<div class="welcome"><h1>Artifacts</h1><p>No artifacts yet. They'll appear here as agents complete their steps.</p></div>`;
        return;
      }

      // Group files by their top-level folder (discovery / meta / design /
      // …). Files with no folder go under "other".
      const groups = {};
      for (const n of names) {
        const slash = n.indexOf("/");
        const cat = slash > 0 ? n.slice(0, slash) : "other";
        (groups[cat] ||= []).push(n);
      }
      const cats = Object.keys(groups).sort();
      const total = names.length;

      // By-category counts for the summary bar chart. Find the max so we
      // can normalise bar widths.
      const counts = cats.map(c => ({ cat: c, n: groups[c].length }));
      const maxN = Math.max(...counts.map(c => c.n));

      root.innerHTML = `
        <div class="artifacts-page">
          <div class="artifacts-main">
            <div class="artifacts-eyebrow">${total} FILE${total === 1 ? "" : "S"}</div>
            <h1>Artifacts</h1>

            <div class="artifacts-summary">
              <div class="artifacts-summary-row">
                <div class="artifacts-count-tile">
                  <div class="artifacts-count-eyebrow">TOTAL</div>
                  <div class="artifacts-count-number">${total}</div>
                  <div class="artifacts-count-label">file${total === 1 ? "" : "s"}</div>
                </div>
                <div class="artifacts-bars">
                  <div class="artifacts-bars-title">By category</div>
                  ${counts.map(c => `
                    <div class="artifacts-bar-row">
                      <div class="artifacts-bar-label">${escapeHtml(c.cat)}</div>
                      <div class="artifacts-bar-track">
                        <div class="artifacts-bar-fill" style="width: ${(c.n / maxN * 100).toFixed(1)}%"></div>
                      </div>
                      <div class="artifacts-bar-count">${c.n}</div>
                    </div>
                  `).join("")}
                </div>
              </div>
            </div>

            <div id="art-view" class="artifacts-viewer">
              <p class="artifacts-viewer-hint">Select a file from the sidebar to view its contents.</p>
            </div>
          </div>

          <aside class="artifacts-rail">
            <div class="artifacts-rail-title">FILES</div>
            ${cats.map(c => `
              <div class="artifacts-rail-group">
                <div class="artifacts-rail-group-title">${escapeHtml(c.toUpperCase())}</div>
                ${groups[c].map(n => {
                  const fname = n.slice(n.indexOf("/") + 1);
                  return `<a href="#" data-art="${escapeHtml(n)}" class="artifacts-rail-link">${escapeHtml(fname)}</a>`;
                }).join("")}
              </div>
            `).join("")}
          </aside>
        </div>
      `;

      root.querySelectorAll("a[data-art]").forEach(a => {
        a.addEventListener("click", async (e) => {
          e.preventDefault();
          // Highlight the active file in the rail.
          root.querySelectorAll(".artifacts-rail-link").forEach(l => l.classList.remove("active"));
          a.classList.add("active");
          const name = a.dataset.art;
          const view = document.getElementById("art-view");
          view.innerHTML = `<p class="artifacts-viewer-hint">Loading ${escapeHtml(name)}…</p>`;
          try {
            const r = await fetch(`/api/engagements/${encodeURIComponent(eid)}/artifacts/${encodeURIComponent(name)}`);
            // Endpoint returns read_artifact's .data wrapped in JSON, so the body is a
            // JSON-encoded string; .json() decodes the escapes back to real newlines/quotes.
            const c = await r.json();
            view.innerHTML = renderArtifactContent(name, typeof c === "string" ? c : JSON.stringify(c, null, 2));
          } catch (err) {
            view.innerHTML = `<p class="artifacts-viewer-hint">Could not load: ${escapeHtml(err.message || err)}</p>`;
          }
        });
      });
    },

    stats: async (root, eid) => {
      // Timeline carries the structured wall/execution/user-wait per step
      // (the recently-shipped timing-instrumentation writes those into
      // session.yaml.timing_data and compute_timeline reads them back).
      // Lifecycle gives us status + note per step. Token usage grouped by
      // agent surfaces "which agent burned the most" without leaving the
      // page. Per-engagement endpoint already includes computed USD cost.
      const [stats, lc, tl, arts, tokAgent] = await Promise.all([
        fetch(`/api/engagements/${encodeURIComponent(eid)}/stats`).then(r => r.json()).catch(() => ({})),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/lifecycle`).then(r => r.json()).catch(() => ({ steps: {} })),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/timeline`).then(r => r.json()).catch(() => []),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/artifacts`).then(r => r.json()).catch(() => []),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/token-usage?group_by=agent`).then(r => r.json()).catch(() => null),
      ]);
      const fmtSec = (s) => {
        s = Math.max(0, Math.floor(s || 0));
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60); const r = s - m * 60;
        if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
        const h = Math.floor(m / 60); const mm = m - h * 60;
        return mm ? `${h}h ${mm}m` : `${h}h`;
      };
      const fmtNum = (n) => (n == null ? "0" : Number(n).toLocaleString());
      // Token counts compress nicely with K/M suffixes; full counts are still
      // in the per-agent table for anyone who needs the digits.
      const fmtTokens = (n) => {
        if (n == null) return "0";
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(n >= 10_000_000 ? 1 : 2) + "M";
        if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + "K";
        return String(n);
      };
      // USD formatting — show cents for small amounts, dollars-only for >$10
      // so the tile stays compact. < $0.01 surfaces as "<$0.01" rather than $0.00
      // so the user knows cost ≠ literally zero.
      const fmtCost = (n) => {
        if (n == null || n === 0) return "$0";
        if (n < 0.01) return "<$0.01";
        if (n < 10) return `$${n.toFixed(2)}`;
        if (n < 1000) return `$${n.toFixed(0)}`;
        return `$${(n / 1000).toFixed(1)}K`;
      };

      // Build a step → timing map from the timeline (structured wall/exec/wait).
      const timeByStep = {};
      for (const e of (Array.isArray(tl) ? tl : [])) {
        timeByStep[e.skill] = e;
      }

      // Per-step rows blend lifecycle (status + note) and timeline (the rich
      // wall/exec/wait breakdown). When timing data is missing for a step
      // (older runs, in-flight steps that haven't finalized yet), fall back
      // to a started→updated delta as the wall time — that at least shows
      // SOMETHING rather than four em-dashes.
      const stepRows = Object.entries(lc?.steps || {}).map(([name, info]) => {
        const t = timeByStep[name] || {};
        let wall = t.wall_seconds;
        if (wall == null && info?.started_at && info?.updated_at) {
          try {
            wall = Math.max(0, Math.floor(
              (new Date(info.updated_at).getTime() - new Date(info.started_at).getTime()) / 1000,
            ));
          } catch {}
        }
        const exec = t.execution_seconds;
        const wait = t.user_wait_seconds;
        const badge = info?.status === "DONE" ? `<span class="status-badge done">Done</span>`
          : info?.status === "DONE_WITH_CONCERNS" ? `<span class="status-badge advisory">Done with concerns</span>`
          : `<span class="status-badge">${escapeHtml(info?.status || "—")}</span>`;
        return `<tr>
          <td><strong>${escapeHtml(name)}</strong></td>
          <td>${badge}</td>
          <td>${wall != null ? fmtSec(wall) : "—"}</td>
          <td>${exec != null ? fmtSec(exec) : "—"}</td>
          <td>${wait != null ? fmtSec(wait) : "—"}</td>
          <td class="muted">${escapeHtml(info?.note || "")}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="6" class="muted">No steps recorded yet. Step timing populates as each agent records DONE.</td></tr>`;

      const tokenTotals = tokAgent?.totals || null;
      const hasTokens = tokenTotals && (tokenTotals.input_tokens || tokenTotals.output_tokens || tokenTotals.calls);
      const totalCost = tokenTotals?.total_cost_usd;
      const totalTokens = tokenTotals?.total_tokens;

      // Per-agent table — top tokens consumer first; helps the user spot
      // which agent is the cost driver without going to Settings → Usage.
      const agentRows = (tokAgent?.rows || []).map(r => `<tr>
        <td><strong>${escapeHtml(r.key)}</strong></td>
        <td>${fmtNum(r.calls)}</td>
        <td>${fmtTokens(r.total_tokens)}</td>
        <td>${fmtTokens(r.input_tokens)}<span class="muted"> · cached ${fmtTokens(r.cached_input_tokens)}</span></td>
        <td>${fmtTokens(r.output_tokens)}</td>
        <td>${fmtCost(r.total_cost_usd)}</td>
      </tr>`).join("");

      root.innerHTML = `<h1>Stats</h1>
        <p class="muted">Time, tokens, and cost for this engagement.</p>

        <div class="stat-tile-row">
          <div class="stat-tile">
            <div class="stat-tile-label">Wall time</div>
            <div class="stat-tile-value">${fmtSec(stats.wall_time_seconds)}</div>
            <div class="stat-tile-sub">Total elapsed across all steps</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">Agent execution</div>
            <div class="stat-tile-value">${fmtSec(stats.execution_seconds)}</div>
            <div class="stat-tile-sub">Wall time minus user wait</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">User wait</div>
            <div class="stat-tile-value">${fmtSec(stats.user_wait_seconds)}</div>
            <div class="stat-tile-sub">Time agents spent in NEEDS_CONTEXT</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">Steps done</div>
            <div class="stat-tile-value">${fmtNum(stats.steps_executed)}</div>
            <div class="stat-tile-sub">Phases marked DONE</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">Artifacts</div>
            <div class="stat-tile-value">${fmtNum((arts || []).length)}</div>
            <div class="stat-tile-sub">Files written to engagement</div>
          </div>
        </div>

        ${hasTokens ? `
        <div class="stat-tile-row">
          <div class="stat-tile">
            <div class="stat-tile-label">LLM tokens</div>
            <div class="stat-tile-value">${fmtTokens(totalTokens)}</div>
            <div class="stat-tile-sub">${fmtNum(tokenTotals.calls)} calls across all agents</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">Cost (USD)</div>
            <div class="stat-tile-value">${fmtCost(totalCost)}</div>
            <div class="stat-tile-sub">Computed from model price registry</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">Input tokens</div>
            <div class="stat-tile-value">${fmtTokens(tokenTotals.input_tokens)}</div>
            <div class="stat-tile-sub">${tokenTotals.cached_input_tokens > 0 ? `cached ${fmtTokens(tokenTotals.cached_input_tokens)}` : "no cached hits"}</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">Output tokens</div>
            <div class="stat-tile-value">${fmtTokens(tokenTotals.output_tokens)}</div>
            <div class="stat-tile-sub">&nbsp;</div>
          </div>
        </div>` : ""}

        <h2>Per-step timing</h2>
        <p class="muted" style="margin-top:-6px">Wall = total elapsed for the step; Execution = agent compute; User wait = time the step sat in NEEDS_CONTEXT.</p>
        <table class="stats-table">
          <thead><tr><th>Step</th><th>Status</th><th>Wall</th><th>Execution</th><th>User wait</th><th>Note</th></tr></thead>
          <tbody>${stepRows}</tbody>
        </table>

        <h2>Token usage by agent</h2>
        ${hasTokens
          ? `<table class="stats-table">
               <thead><tr><th>Agent</th><th>Calls</th><th>Tokens</th><th>Input</th><th>Output</th><th>Cost</th></tr></thead>
               <tbody>${agentRows}</tbody>
             </table>
             <p class="muted" style="margin-top:8px">Cross-engagement breakdown: <a href="/settings#usage">Settings → Usage</a></p>`
          : `<p class="muted">No LLM calls recorded yet for this engagement — start a phase and the table populates as each agent runs.</p>`}
        `;
    },

    export: async (root, eid) => {
      // Audience packs — descriptions are stable copy; readiness is computed
      // from lifecycle so disabled packs show *why* they're disabled.
      const AUDIENCE_PACKS = [
        { id: "blueprint", title: "Blueprint",   icon: "🏗️", desc: "Engineering handoff — architecture, topology, SAM YAMLs, broker provisioning, runbook.",         prereq: "design"    },
        { id: "executive", title: "Executive",   icon: "📊", desc: "Business outcome summary — ROI, risk reduction, strategic value. For CXO and board review.",     prereq: "blueprint" },
        { id: "admin-ops", title: "Admin & Ops", icon: "🔧", desc: "Day-2 operability — runbook, monitoring coverage, escalation, capacity planning, upgrade paths.", prereq: "blueprint" },
        { id: "security",  title: "Security",    icon: "🔒", desc: "Security posture — ACL model, TLS, authn/z, compliance, encryption at rest and in transit.",     prereq: "blueprint" },
        { id: "developers",title: "Developers",  icon: "💻", desc: "Developer experience — SDK choices, topic taxonomy, schema governance, onboarding path.",        prereq: "blueprint" },
      ];

      const lc = await fetch(`/api/engagements/${encodeURIComponent(eid)}/lifecycle`).then(r => r.json()).catch(() => ({ steps: {} }));
      const isDone = (s) => {
        const st = lc?.steps?.[s]?.status;
        return st === "DONE" || st === "DONE_WITH_CONCERNS";
      };

      const cards = AUDIENCE_PACKS.map(p => {
        const ready = isDone(p.prereq);
        const badge = ready
          ? `<span class="status-badge done">Ready</span>`
          : `<span class="status-badge pending">Awaiting ${escapeHtml(p.prereq)}</span>`;
        // The rendered HTML page itself carries Print/PDF + Download HTML
        // buttons in its top toolbar, so the Export page only needs the
        // primary "View HTML" entry point. Keeps the card compact and
        // removes a redundant action. A small "Regenerate from scratch"
        // checkbox lets the user bypass the freshness cache when they
        // suspect the report is stale (or just want to force a refresh).
        const forceId = `force-${p.id}-${eid}`;
        return `<div class="export-card${ready ? "" : " export-card-disabled"}" data-pack="${p.id}">
          <div class="export-card-head">
            <div class="export-card-icon" aria-hidden="true">${p.icon}</div>
            <div class="export-card-title">${escapeHtml(p.title)}</div>
            ${badge}
          </div>
          <p class="export-card-desc">${escapeHtml(p.desc)}</p>
          <div class="export-card-actions">
            <button class="cta-btn export-card-cta"${ready ? "" : " disabled"}
                    ${ready ? `onclick="window.__renderPack(this, '${eid}','${p.id}')"` : ""}>
              ${ready ? "View HTML →" : "Locked"}
            </button>
            ${ready ? `<label class="export-card-force" for="${forceId}" title="Skip the freshness cache and re-render this pack from scratch. Use when the report looks stale.">
              <input type="checkbox" id="${forceId}" class="export-card-force-cb" data-pack="${p.id}">
              <span>Regenerate</span>
            </label>` : ""}
          </div>
        </div>`;
      }).join("");

      root.innerHTML = `<h1>Export</h1>
        <p class="muted">Audience-tailored reports drawn from this engagement's artifacts. Each pack is auto-rendered from the relevant phase outputs; packs without their prerequisite phase complete stay locked until that phase wraps.</p>

        <h2>Audience reports</h2>
        <div class="export-grid">${cards}</div>

        <h2>Full archive</h2>
        <div class="export-archive">
          <div class="export-card-icon" aria-hidden="true">📦</div>
          <div class="export-archive-body">
            <div class="export-card-title">Engagement bundle</div>
            <p class="export-card-desc">Every artifact this engagement has produced — intake, discovery brief, design scopes, decisions, open items, findings, telemetry — packed as a single <code>.zip</code> for offline review or handoff.</p>
            <button class="cta-btn" onclick="window.__downloadZip('${eid}')">Download .zip →</button>
          </div>
        </div>`;
    },
  };

  // Smart per-format renderer for an artifact's content. Used by the
  // Artifacts page viewer.
  //   .md       → marked.js rendered HTML (sanitised via DOMPurify)
  //   .yaml/.yml/.json → monospace block with light syntax coloring (no external lib)
  //   anything else    → preformatted plain text
  function renderArtifactContent(filename, content) {
    const lower = filename.toLowerCase();
    const head = `<h2 class="artifacts-viewer-title">${escapeHtml(filename)}</h2>`;
    let body;
    if (lower.endsWith(".md") && typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      try {
        const html = marked.parse(content, { breaks: true, gfm: true });
        body = `<div class="artifacts-viewer-md">${DOMPurify.sanitize(html)}</div>`;
      } catch {
        body = `<pre class="artifacts-viewer-pre">${escapeHtml(content)}</pre>`;
      }
    } else if (lower.endsWith(".yaml") || lower.endsWith(".yml")) {
      body = `<pre class="artifacts-viewer-pre artifacts-viewer-yaml">${highlightYaml(content)}</pre>`;
    } else if (lower.endsWith(".json")) {
      // Pretty-print if it parses; otherwise show raw.
      let display = content;
      try { display = JSON.stringify(JSON.parse(content), null, 2); } catch {}
      body = `<pre class="artifacts-viewer-pre artifacts-viewer-json">${highlightJson(display)}</pre>`;
    } else {
      body = `<pre class="artifacts-viewer-pre">${escapeHtml(content)}</pre>`;
    }
    return head + body;
  }

  // Minimal YAML tint — keys get accent color, strings stay default,
  // numbers/booleans get a contrast color, comments dim. No tokeniser
  // — just regex over the escaped output, line by line.
  function highlightYaml(content) {
    return content.split("\n").map(line => {
      const esc = escapeHtml(line);
      // Comment lines (whole line)
      if (/^\s*#/.test(esc)) return `<span class="art-yaml-comment">${esc}</span>`;
      // List item marker + key/value
      return esc
        .replace(/(^\s*-?\s*)([A-Za-z_][A-Za-z0-9_-]*)(:)(\s|$)/, (_m, pfx, key, colon, after) =>
          `${pfx}<span class="art-yaml-key">${key}</span><span class="art-yaml-punct">${colon}</span>${after}`)
        .replace(/\b(true|false|null|yes|no)\b/gi, `<span class="art-yaml-bool">$1</span>`)
        .replace(/\b(\d+(?:\.\d+)?)\b/g, `<span class="art-yaml-num">$1</span>`);
    }).join("\n");
  }

  function highlightJson(content) {
    return escapeHtml(content)
      .replace(/(&quot;[^&]*?&quot;)(\s*:)/g, `<span class="art-json-key">$1</span>$2`)
      .replace(/:\s*(&quot;[^&]*?&quot;)/g, `: <span class="art-json-string">$1</span>`)
      .replace(/\b(true|false|null)\b/g, `<span class="art-json-bool">$1</span>`)
      .replace(/:\s*(-?\d+(?:\.\d+)?)/g, `: <span class="art-json-num">$1</span>`);
  }

  // Per-step illustration banners shown above the engagement stat tiles.
  // Each step gets a hand-rolled inline SVG so we don't depend on any
  // external icon set. State drives the styling: completed = checkmark
  // tint, active = accent border + glow, pending = muted.

  function renderProgressBanner({ eid, active, completed, needsContext, skipped, blocked,
                                  stats }) {
    needsContext = needsContext || new Set();
    skipped = skipped || new Set();
    blocked = blocked || new Set();
    // Per-phase step lists (from compute_overview_stats) drive the per-tile dot
    // strips for every multi-step phase, not just Design.
    const phaseStepLists = {
      design: stats?.design_scopes || [],
      review: stats?.review_reviewers || [],
      "event-portal": stats?.event_portal_stages || [],
      blueprint: stats?.blueprint_sections || [],
    };
    // Lifecycle steps shown across the top of the Progress view.
    // Order matches PHASE_NEXT: intake → discovery → design → review →
    // validation → event-portal → blueprint.
    const steps = [
      { id: "intake",       label: "Intake",       svg: "M3 4h18v4H3zM3 12h18v4H3zM3 20h18" },
      { id: "discovery",    label: "Discovery",    svg: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm10 2-5-5" },
      { id: "design",       label: "Design",       svg: "M3 3l6 6v12l6-6V3zM3 3l6 6 6-6" },
      { id: "review",       label: "Review",       svg: "M4 4h16v12H4zM4 4l8 6 8-6M8 20h8" },
      { id: "validation",   label: "Validation",   svg: "M5 12l5 5L20 7" },
      { id: "event-portal", label: "Event Portal", svg: "M4 12a8 8 0 1 0 16 0 8 8 0 0 0-16 0zM12 4v8l5 3" },
      { id: "blueprint",    label: "Blueprint",    svg: "M4 4h16v16H4zM4 9h16M9 4v16" },
    ];
    // Restart is only meaningful for phases that have started (active OR
    // done). NOT_STARTED phases have nothing to clean up. Intake is a UI
    // form, not an agent phase — restart there means editing the form,
    // not running a wipe; we omit it.
    return `
      <div class="progress-banner" role="navigation" aria-label="Engagement lifecycle">
        ${steps.map(s => {
          const isActive = s.id === active;
          const isDone = completed.has(s.id);
          const isBlocked = blocked.has(s.id);
          const isNeedsCtx = needsContext.has(s.id);
          const isSkipped = skipped.has(s.id);
          // Mutually-exclusive primary state, in priority order:
          //   blocked > done > needs-context > active > skipped > pending.
          // BLOCKED is highest priority because it's a hard stop the user
          // must resolve — surfacing it loudly is the whole point.
          // Visual semantics: blocked (red border + ⛔), done (accent-green
          // ✓), needs-context (amber 'Waiting for you'), active (current
          // step), skipped (muted strikethrough), pending (default neutral).
          let primary;
          if (isBlocked) primary = "blocked";
          else if (isDone) primary = "done";
          else if (isNeedsCtx) primary = "needs-context";
          else if (isActive) primary = "active";
          else if (isSkipped) primary = "skipped";
          else primary = "pending";
          const cls = `progress-step ${primary}`;
          // Skipped steps can't be restarted (they never ran); intake never
          // has a Restart (it's a form). Otherwise active/done/needs-context
          // can all be cleaned up via Restart.
          const canRestart = (isActive || isDone || isNeedsCtx) && s.id !== "intake";
          return `
            <div class="${cls.trim()}" data-step="${s.id}">
              <div class="progress-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="${s.svg}"/>
                </svg>
                ${isDone ? `<span class="progress-check" aria-hidden="true">✓</span>` : ""}
              </div>
              <div class="progress-label">${s.label}</div>
              ${(isActive || isDone)
                ? _renderPhaseDotStrip(phaseStepLists[s.id] || [], eid, s.id)
                : ""}
              ${canRestart
                ? `<button type="button" class="progress-restart-btn"
                          data-restart-phase="${s.id}"
                          title="Restart ${s.label} — cascade-wipe and re-run">
                     ↻ Restart
                   </button>`
                : ""}
            </div>`;
        }).join("")}
      </div>`;
  }

  // status → visual state for the per-phase dot strip. done=solid, active
  // (running/next/current)=ring, pending=hollow, skipped=faded. All circles —
  // the state is conveyed by fill/border, not by swapping glyph characters
  // (which render inconsistently across fonts/platforms).
  const _DOT_STATE = {
    done: "done", running: "active", next: "active", current: "active",
    pending: "pending", skipped: "skipped",
  };

  // Sub-progress strip for any multi-step lifecycle tile (Design scopes, Review
  // reviewers, Event Portal stages, Blueprint sections). One CSS-styled circle
  // per step; the dots' fill/ring/hollow states carry the "how far along"
  // signal on their own, so no numeric "N/M" count is shown. `items` is the
  // stats step list ([{id|scope, status}]). Returns "" for phases with fewer
  // than two applicable steps so callers can splice it in unconditionally.
  // Done Design dots deep-link to their artifacts.
  function _renderPhaseDotStrip(items, eid, phase) {
    if (!Array.isArray(items)) return "";
    const applicable = items.filter(it => (it.status || "pending") !== "skipped");
    if (applicable.length < 2) return "";
    const dots = items.map(it => {
      const status = it.status || "pending";
      const state = _DOT_STATE[status] || "pending";
      const id = it.id || it.scope || "";
      const title = `${id.replace(/-/g, " ")} — ${_CHECKLIST_STATUS_LABEL[status] || status}`;
      const href = (phase === "design" && status === "done" && eid && id)
        ? `/projects/${encodeURIComponent(eid)}/artifacts?category=${encodeURIComponent(id)}`
        : null;
      const dot = `<span class="phase-dot ${state}" title="${escapeHtml(title)}" data-step="${escapeHtml(id)}" aria-label="${escapeHtml(title)}"></span>`;
      return href ? `<a href="${href}" data-route>${dot}</a>` : dot;
    }).join("");
    return `
      <div class="phase-dot-strip">
        <span class="phase-dots">${dots}</span>
      </div>`;
  }

  // Phase-tile Restart click handler — delegated from the document so it
  // picks up the buttons regardless of which view re-rendered the banner.
  // Routes to the right modal per phase id.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".progress-restart-btn");
    if (!btn) return;
    e.preventDefault();
    const phaseId = btn.getAttribute("data-restart-phase");
    const eid = currentProjectId();
    if (!eid) return;
    if (phaseId === "discovery") openRestartDiscoveryModal(eid);
    else if (phaseId === "design") openRestartDesignModal(eid);
    else openRestartPhaseModal(phaseId, eid);
  });

  // One contextual CTA on the Progress page, always present, tells the
  // user what to do next based on lifecycle state. Resolves the previous
  // confusion ("I see the banner but what should I do") by giving a
  // single primary action keyed to the current step + status.
  //
  // States covered (in order — the first matching branch wins):
  //   - no intake               → link to /intake
  //   - Design DONE             → Restart Design (Review CTA placeholder)
  //   - Design in progress      → Continue Design in chat
  //   - Discovery DONE          → Start Design (the canonical handoff)
  //   - Discovery in progress   → Continue Discovery in chat
  //   - Intake exists, idle     → Start Discovery
  // Compact "what's happening RIGHT NOW" hint for in-progress cards.
  // One line, muted, monospace — fills the silent gap between the card
  // body and the action buttons. Non-redundant with the phase tiles row
  // (which shows state) and the Stats sidebar (which shows totals): this
  // line answers "where are we INSIDE the current phase, and when was
  // the last sign of life?". Each phase contributes whatever's most
  // useful from what we already have on the dashboard payload.
  function _relTime(iso) {
    if (!iso) return null;
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return null;
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 30)        return "just now";
    if (s < 90)        return "a moment ago";
    if (s < 60 * 60)   return Math.round(s / 60) + "m ago";
    if (s < 86400)     return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }

  // Human labels keyed by sub-step id, per phase. Falls back to raw id
  // when a phase adds a new sub-step this map doesn't know about — better
  // than rendering nothing.
  const _CHECKLIST_LABELS = {
    design: {
      "topic-design":         "Topic taxonomy",
      "broker-select":        "Broker selection",
      "sam-design":           "SAM topology",
      "protocol-select":      "Protocol selection",
      "mesh-design":          "DMR mesh design",
      "ha-dr":                "HA / DR",
      "migration":            "Migration plan",
      "integration":          "Micro-Integration",
      "event-portal-design":  "Event Portal model",
    },
    review: {
      "architect":   "Architecture review",
      "developer":   "Developer review",
      "ops":         "Operations review",
      "security":    "Security review",
    },
    "event-portal": {
      "plan":          "Dry-run plan",
      "provisioned":   "Live provisioning",
      "asyncapi":      "AsyncAPI export",
    },
    blueprint: {
      "architecture-overview":    "Architecture — overview",
      "architecture-decisions":   "Architecture — decisions",
      "architecture-components":  "Architecture — components",
      "architecture":             "Architecture (TOC)",
      "runbook-deploy":           "Runbook — deploy",
      "runbook-failures":         "Runbook — failures",
      "runbook-dr":               "Runbook — DR",
      "runbook":                  "Runbook (TOC)",
      "pack-blueprint":           "Pack — blueprint",
      "pack-executive":           "Pack — executive",
      "pack-admin-ops":           "Pack — admin / ops",
      "pack-developer":           "Pack — developer",
      "pack-security":            "Pack — security",
      "engagement-package":       "Final ZIP export",
    },
  };
  const _CHECKLIST_STATUS_ICON = {
    done:    "●",
    running: "◑",
    next:    "◐",
    pending: "◯",
    skipped: "⊘",
  };
  const _CHECKLIST_STATUS_LABEL = {
    done:    "Done",
    running: "Running",
    next:    "Next",
    pending: "Pending",
    skipped: "Skipped",
  };

  // Generic per-phase checklist. Items: `[{id, status, ?skip_reason}]`.
  // Returns empty string when there's nothing to render so callers can
  // splice the result in unconditionally.
  function _renderPhaseChecklist(phase, items) {
    if (!Array.isArray(items) || !items.length) return "";
    const labels = _CHECKLIST_LABELS[phase] || {};
    const rows = items.map(it => {
      const status = it.status || "pending";
      const icon = _CHECKLIST_STATUS_ICON[status] || "◯";
      const id = it.id || it.scope || "";
      const label = labels[id] || id;
      const statusLabel = _CHECKLIST_STATUS_LABEL[status] || status;
      const reasonAttr = it.skip_reason ? ` title="${escapeHtml(it.skip_reason)}"` : "";
      return `
        <li class="phase-checklist-row phase-checklist-${escapeHtml(status)}"${reasonAttr}>
          <span class="phase-checklist-icon">${icon}</span>
          <span class="phase-checklist-label">${escapeHtml(label)}</span>
          <span class="phase-checklist-id"><code>${escapeHtml(id)}</code></span>
          <span class="phase-checklist-status">${escapeHtml(statusLabel)}</span>
        </li>`;
    }).join("");
    const remaining = items.filter(s => s.status === "next" || s.status === "pending").length;
    const hint = remaining > 0
      ? `<div class="phase-checklist-hint">↓ ${remaining} pending — scroll for more</div>`
      : "";
    return `
      <div class="phase-checklist-wrap">
        <ul class="phase-checklist" role="list">${rows}</ul>
        ${hint}
      </div>`;
  }

  // After the progress card is in the DOM, surface the scope that's actually
  // running. The checklist is a fixed-height scroller (CSS max-height:180px);
  // once several scopes are done the running one drops below the fold (the
  // "↓ N pending — scroll for more" hint). Scroll it into view so a glance at
  // the card always shows the live step — but ONLY when it's off-screen, so we
  // never yank a row the user already has in view. Cosmetic; never throws.
  function _scrollChecklistToActive(root) {
    try {
      const list = (root || document).querySelector("ul.phase-checklist");
      if (!list) return;
      // Preference: the running row; else the next/pending one about to run.
      // Done/skipped rows never need surfacing.
      const active = list.querySelector(".phase-checklist-running")
                  || list.querySelector(".phase-checklist-next")
                  || list.querySelector(".phase-checklist-pending");
      if (!active) return;
      const lr = list.getBoundingClientRect();
      const ar = active.getBoundingClientRect();
      const above = ar.top < lr.top;
      const below = ar.bottom > lr.bottom;
      if (!above && !below) return;  // already visible — leave the scroll alone
      // Row's offset within the (scroll-independent) list content, then center
      // it in the viewport. getBoundingClientRect avoids offsetParent ambiguity.
      const offsetWithinList = (ar.top - lr.top) + list.scrollTop;
      list.scrollTop = Math.max(0, offsetWithinList - (list.clientHeight - ar.height) / 2);
    } catch (_) { /* cosmetic — must never break the render */ }
  }

  function _phaseExecHint({ phase, lifecycle, stats }) {
    const step = lifecycle?.steps?.[phase] || {};
    const pieces = [];

    if (phase === "discovery") {
      const open = (stats?.open_items_blocking || 0) + (stats?.open_items_advisory || 0);
      if (open) pieces.push(`${open} open item${open === 1 ? "" : "s"}`);
    } else if (phase === "design") {
      const sp = step.scope_progress || {};
      const done = (sp.done || []).length;
      const applicable = Array.isArray(sp.applicable) ? sp.applicable.length : 0;
      if (applicable) {
        pieces.push(`${done} of ${applicable} scope${applicable === 1 ? "" : "s"} done`);
      } else if (done) {
        pieces.push(`${done} scope${done === 1 ? "" : "s"} done`);
      }
      if (sp.next) pieces.push(`on ${sp.next}`);
    } else if (phase === "review") {
      // We don't have per-reviewer breakdown in stats; surface decisions
      // accumulated so far + the agent's own note when present.
      const d = stats?.decisions_count || 0;
      if (d) pieces.push(`${d} decision${d === 1 ? "" : "s"} so far`);
    } else if (phase === "validation") {
      const open = (stats?.open_items_blocking || 0);
      if (open) pieces.push(`${open} blocking item${open === 1 ? "" : "s"}`);
    } else if (phase === "event-portal" || phase === "blueprint") {
      // No phase-specific counters; rely on the timestamp + note alone.
    }

    // Short note from the agent (set via set_step_status note=…) — adds
    // qualitative context the counters miss. Truncate so it stays one line.
    if (step.note && step.note.length > 0) {
      const trimmed = step.note.length > 80 ? step.note.slice(0, 77) + "…" : step.note;
      pieces.push(`"${trimmed}"`);
    }

    const age = _relTime(step.updated_at);
    if (age) pieces.push(`updated ${age}`);

    if (!pieces.length) return "";
    return `<p class="cta-exec-hint">→ ${pieces.map(escapeHtml).join(" · ")}</p>`;
  }

  function renderProgressCta({
    eid, hasIntake, discoveryStatus, discoveryNote, discoveryInProgress, openItemsCount,
    designStatus, designNote, designDone, designInProgress,
    reviewStatus, reviewNote, reviewDone, reviewInProgress,
    validationStatus, validationNote, validationDone, validationInProgress,
    eventPortalStatus, eventPortalNote, eventPortalDone, eventPortalInProgress,
    blueprintStatus, blueprintNote, blueprintDone, blueprintInProgress,
    blueprintBlockers, lifecycle, stats, executionMode,
  }) {
    blueprintBlockers = blueprintBlockers || [];
    // Default to interactive (safer — agent confirms decisions) when
    // execution_mode isn't surfaced. Drives Design + Event Portal CTAs
    // to show one primary button matching the intake-time preference
    // and one small text-link override for the opposite mode.
    const prefersAuto = executionMode === "auto";
    if (!hasIntake) {
      return `
        <div class="progress-cta" role="region" aria-label="Intake required">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Get started</div>
            <h2>Submit your intake</h2>
            <p>Discovery can't run without an intake form. Tell us what you're building
            and we'll start asking the right follow-ups.</p>
          </div>
          <div class="progress-cta-actions">
            <a class="cta-btn" href="/intake/edit/${encodeURIComponent(eid)}">Open intake form →</a>
          </div>
        </div>`;
    }

    const discoveryDone = discoveryStatus === "DONE" || discoveryStatus === "DONE_WITH_CONCERNS";

    // Subtle "escape hatch" row — same pattern across every step that has
    // a Restart action. Visually demoted so it doesn't compete with the
    // primary forward CTA, but discoverable and tooltip-explained.
    const restartDiscoveryRow = `
      <div class="progress-cta-secondary-actions">
        <button id="restart-discovery-btn" class="cta-link-danger"
                title="Re-run Discovery from scratch. Cascade-wipes Discovery + every downstream phase (artifacts, step status, telemetry, findings, phase-authored decisions). Orchestrator flow decisions are preserved. Intake form is not touched. Only use this if requirements have materially changed.">
          ↺ Restart Discovery
        </button>
        <span class="secondary-action-hint">— requirements materially changed? wipe Discovery and start fresh</span>
      </div>`;
    const restartDesignRow = `
      <div class="progress-cta-secondary-actions">
        <button id="restart-design-btn" class="cta-link-danger"
                title="Re-run Design from scratch. Wipes every design scope artifact (topic-design, broker-select, …), the design step status, and every downstream phase. Phase-authored decisions are dropped; orchestrator flow decisions are preserved. Only use this if the discovery brief or constraints have changed.">
          ↺ Restart Design
        </button>
        <span class="secondary-action-hint">— discovery brief changed? wipe design output and start fresh</span>
      </div>`;

    // Blueprint DONE — engagement complete (terminal state).
    if (blueprintDone) {
      const badge = blueprintStatus === "DONE_WITH_CONCERNS"
        ? `<span class="status-badge advisory">Done with concerns</span>`
        : `<span class="status-badge done">Done</span>`;
      return `
        <div class="progress-cta done" role="region" aria-label="Blueprint complete">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Engagement complete</div>
            <h2>Blueprint is complete ${badge}</h2>
            ${blueprintNote ? `<p>${escapeHtml(blueprintNote)}</p>` : ""}
            <p>The deliverable package is assembled — architecture narrative,
            ops runbook, diagrams, and 5 audience packs bundled into
            <code>exports/engagement-package.zip</code>. If Event Portal
            provisioning was opted-in at intake, live tenant objects and
            AsyncAPI specs were already created under
            <code>event-portal/</code> in the prior step.</p>
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <a class="cta-btn" href="/projects/${encodeURIComponent(eid)}/artifacts">View artifacts →</a>
          </div>
        </div>`;
    }

    // Blueprint in progress.
    if (blueprintInProgress) {
      const blueprintListHtml = _renderPhaseChecklist("blueprint", stats?.blueprint_sections || []);
      return `
        <div class="progress-cta in-progress" role="region" aria-label="Blueprint in progress">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Blueprint in progress</div>
            <h2>Assembling the engagement package</h2>
            <p>SABlueprintAgent is composing the architecture narrative,
            runbook, diagrams, and 5 audience packs.
            ${blueprintNote ? `<em>${escapeHtml(blueprintNote)}</em>` : ""}</p>
            ${blueprintListHtml}
            ${_phaseExecHint({ phase: "blueprint", lifecycle, stats })}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="continue-in-chat-btn" class="cta-btn">Continue in chat →</button>
          </div>
        </div>`;
    }

    // Event Portal DONE — Blueprint is next.
    if (eventPortalDone) {
      const badge = eventPortalStatus === "DONE_WITH_CONCERNS"
        ? `<span class="status-badge advisory">Done with concerns</span>`
        : `<span class="status-badge done">Done</span>`;
      return `
        <div class="progress-cta done" role="region" aria-label="Event Portal complete">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Event Portal → Blueprint</div>
            <h2>Event Portal provisioning is complete ${badge}</h2>
            ${eventPortalNote ? `<p>${escapeHtml(eventPortalNote)}</p>` : ""}
            <p>The designed application domains, applications, events, schemas,
            and AsyncAPI specs are now live in your Solace Cloud tenant.
            Provisioning records are at <code>event-portal/provisioned.yaml</code>;
            exported AsyncAPI specs are under
            <code>event-portal/asyncapi/</code>. Next step:
            <strong>Blueprint</strong> — assemble the deliverable package.</p>
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="start-blueprint-btn" class="cta-btn">Start Blueprint →</button>
            <a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/artifacts">View event-portal →</a>
          </div>
        </div>`;
    }

    // Event Portal in progress — MCP-backed agent talking to live tenant.
    if (eventPortalInProgress) {
      const epListHtml = _renderPhaseChecklist("event-portal", stats?.event_portal_stages || []);
      return `
        <div class="progress-cta in-progress" role="region" aria-label="Event Portal in progress">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Event Portal in progress</div>
            <h2>Provisioning to Solace Cloud</h2>
            <p>SAEventPortalAgent is creating Event Portal objects via the
            MCP server.
            ${eventPortalNote ? `<em>${escapeHtml(eventPortalNote)}</em>` : ""}</p>
            ${epListHtml}
            ${_phaseExecHint({ phase: "event-portal", lifecycle, stats })}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="continue-in-chat-btn" class="cta-btn">Continue in chat →</button>
          </div>
        </div>`;
    }

    // Validation DONE — Event Portal is next, gated on blocking open-items.
    if (validationDone) {
      const badge = validationStatus === "DONE_WITH_CONCERNS"
        ? `<span class="status-badge advisory">Done with concerns</span>`
        : `<span class="status-badge done">Done</span>`;
      // Gate: SAValidationAgent records blocking open-items. The gate
      // applies to whichever step is next. EP slots in between
      // Validation and Blueprint, so until the Validation prompt is
      // updated to set affecting_step="event-portal" explicitly, we
      // reuse the blueprintBlockers collection (validation may still be
      // tagging items with the old affecting_step="blueprint" value).
      const epBlockers = blueprintBlockers;
      const blockedByOpenItems = epBlockers.length > 0;
      const blockerList = blockedByOpenItems
        ? `<div class="progress-blocker-list">
             <strong>${epBlockers.length} blocking open-item${epBlockers.length === 1 ? "" : "s"} must be resolved first:</strong>
             <ul>${epBlockers.slice(0, 5).map(i => `<li><code>${escapeHtml(i.id || "?")}</code>: ${escapeHtml(i.description || "")}</li>`).join("")}</ul>
             ${epBlockers.length > 5 ? `<small>(…and ${epBlockers.length - 5} more — see Open Items)</small>` : ""}
           </div>`
        : "";
      const epBtnAttrs = blockedByOpenItems
        ? `disabled title="Resolve the blocking open-items below before Event Portal can run."`
        : "";
      return `
        <div class="progress-cta done" role="region" aria-label="Validation complete">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Validation → Event Portal</div>
            <h2>Validation is complete ${badge}</h2>
            ${validationNote ? `<p>${escapeHtml(validationNote)}</p>` : ""}
            <p>The design has been audited against requirement coverage,
            antipatterns, consistency, deferred findings, terminology
            compliance, and schema sanity. Next step:
            <strong>Event Portal</strong> — SAEventPortalAgent provisions
            the designed application domains, applications, events, schemas,
            and AsyncAPI specs live in your Solace Cloud tenant.
            ${prefersAuto
              ? `Your intake set the pace to <strong>auto</strong> — runs all layers to completion (first error halts and reports).`
              : `Your intake set the pace to <strong>interactive</strong> — pauses per layer for your confirmation.`}</p>
            ${blockerList}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            ${prefersAuto
              ? `<button id="start-event-portal-auto-btn" class="cta-btn cta-btn-auto" data-mode="auto" ${epBtnAttrs}
                          title="Auto mode (intake preference): provision all layers without per-layer confirmation; first error halts and reports.">Start Event Portal ⚡</button>
                 <button id="start-event-portal-btn" type="button" class="cta-mode-override" data-mode="interactive" ${epBtnAttrs}
                          title="Override to interactive — pause for confirmation per provisioning layer.">Confirm each layer instead</button>`
              : `<button id="start-event-portal-btn" class="cta-btn" data-mode="interactive" ${epBtnAttrs}>Start Event Portal →</button>
                 <button id="start-event-portal-auto-btn" type="button" class="cta-mode-override" data-mode="auto" ${epBtnAttrs}
                          title="Override to auto — provision all layers without per-layer confirmation.">Run on auto instead ⚡</button>`}
            <a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/artifacts">View validation →</a>
            ${blockedByOpenItems ? `<a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/open-items">View open items →</a>` : ""}
          </div>
        </div>`;
    }

    // Validation in progress.
    if (validationInProgress) {
      return `
        <div class="progress-cta in-progress" role="region" aria-label="Validation in progress">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Validation in progress</div>
            <h2>Auditing the design</h2>
            <p>SAValidationAgent is gating the design — tracing
            requirements, scanning antipatterns, checking consistency,
            schema sanity, and terminology.
            ${validationNote ? `<em>${escapeHtml(validationNote)}</em> ` : ""}
            Click <strong>Continue in chat →</strong> to follow along.</p>
            ${_phaseExecHint({ phase: "validation", lifecycle, stats })}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="continue-in-chat-btn" class="cta-btn">Continue in chat →</button>
          </div>
        </div>`;
    }

    // Review DONE — Validation is next.
    if (reviewDone) {
      const badge = reviewStatus === "DONE_WITH_CONCERNS"
        ? `<span class="status-badge advisory">Done with concerns</span>`
        : `<span class="status-badge done">Done</span>`;
      return `
        <div class="progress-cta done" role="region" aria-label="Review complete">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Review → Validation</div>
            <h2>Review is complete ${badge}</h2>
            ${reviewNote ? `<p>${escapeHtml(reviewNote)}</p>` : ""}
            <p>The four reviewer agents (architect, developer, ops, security)
            have audited the design. Findings appear in the chat as an
            interactive card — click <strong>Apply / Defer / Discuss</strong>
            per finding. Next step: <strong>Validation</strong> —
            SAValidationAgent gates Blueprint by checking requirement
            coverage, antipatterns, consistency, and schema sanity.</p>
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="start-validation-btn" class="cta-btn">Start Validation →</button>
            <a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/artifacts">View reviews →</a>
          </div>
        </div>`;
    }

    // Review in progress — orchestrator is fanning out / aggregating.
    if (reviewInProgress) {
      const reviewListHtml = _renderPhaseChecklist("review", stats?.review_reviewers || []);
      return `
        <div class="progress-cta in-progress" role="region" aria-label="Review in progress">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Review in progress</div>
            <h2>Reviewers are auditing the design</h2>
            <p>SAOrchestratorAgent has dispatched the four reviewer agents in parallel.
            ${reviewNote ? `<em>${escapeHtml(reviewNote)}</em>` : ""}</p>
            ${reviewListHtml}
            ${_phaseExecHint({ phase: "review", lifecycle, stats })}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="continue-in-chat-btn" class="cta-btn">Continue in chat →</button>
          </div>
        </div>`;
    }

    // Design DONE — Review is the next step.
    if (designDone) {
      const badge = designStatus === "DONE_WITH_CONCERNS"
        ? `<span class="status-badge advisory">Done with concerns</span>`
        : `<span class="status-badge done">Done</span>`;
      return `
        <div class="progress-cta done" role="region" aria-label="Design complete">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Design → Review</div>
            <h2>Design is complete ${badge}</h2>
            ${designNote ? `<p>${escapeHtml(designNote)}</p>` : ""}
            <p>Next step: <strong>Review</strong>. SAOrchestratorAgent fans
            out to four reviewer agents (architect, developer, ops, security)
            in parallel; each audits the design against a domain-specific
            rubric and records findings. You'll get a per-finding
            Apply / Defer / Discuss card in chat once they're done.</p>
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="start-review-btn" class="cta-btn">Start Review →</button>
            <a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/artifacts">View design →</a>
          </div>
          ${restartDesignRow}
        </div>`;
    }

    // Design in progress — agent is mid-flow through scopes.
    if (designInProgress) {
      const scopeListHtml = _renderPhaseChecklist("design", stats?.design_scopes || []);
      return `
        <div class="progress-cta in-progress" role="region" aria-label="Design in progress">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Design in progress${prefersAuto ? " · auto ⚡" : ""}</div>
            <h2>${prefersAuto ? "Design is advancing automatically" : "Continue Design in chat"}</h2>
            <p>SADomainAgent is working through the design scopes.
            ${prefersAuto ? "Each scope and file dispatches on its own — open the chat to watch, or take over any time." : ""}
            ${designNote ? `<em>${escapeHtml(designNote)}</em>` : ""}</p>
            ${scopeListHtml}
            ${_phaseExecHint({ phase: "design", lifecycle, stats })}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="continue-in-chat-btn" class="cta-btn"
                    title="Resume from the first pending scope. Keeps the artifacts of completed scopes — does NOT wipe anything.">Continue Design →</button>
          </div>
          ${restartDesignRow}
        </div>`;
    }

    if (discoveryDone) {
      const badge = discoveryStatus === "DONE_WITH_CONCERNS"
        ? `<span class="status-badge advisory">Done with concerns</span>`
        : `<span class="status-badge done">Done</span>`;
      return `
        <div class="progress-cta done" role="region" aria-label="Discovery complete">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Discovery → Design</div>
            <h2>Discovery is complete ${badge}</h2>
            ${discoveryNote ? `<p>${escapeHtml(discoveryNote)}</p>` : ""}
            <p>Next step: <strong>Design</strong>. SADomainAgent will walk
            the nine design scopes (topic taxonomy, broker selection,
            protocols, integration, mesh, HA/DR, SAM, event-portal,
            migration). ${prefersAuto
              ? `Your intake set the pace to <strong>auto</strong> — every decision still surfaces in chat as it's made.`
              : `Your intake set the pace to <strong>interactive</strong> — you'll confirm each decision before it lands.`}</p>
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            ${prefersAuto
              ? `<button id="start-design-auto-btn" class="cta-btn cta-btn-auto" data-mode="auto"
                          title="Auto mode (intake preference): take all recommended options; every decision still appears live in chat.">Start Design ⚡</button>
                 <button id="start-design-btn" type="button" class="cta-mode-override" data-mode="interactive"
                          title="Override to interactive — confirm each decision before it lands.">Confirm each decision instead</button>`
              : `<button id="start-design-btn" class="cta-btn" data-mode="interactive">Start Design →</button>
                 <button id="start-design-auto-btn" type="button" class="cta-mode-override" data-mode="auto"
                          title="Override to auto — take recommended options without per-decision confirmation.">Run on auto instead ⚡</button>`}
            <a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/artifacts">View brief →</a>
          </div>
          ${restartDiscoveryRow}
        </div>`;
    }

    if (discoveryInProgress) {
      return `
        <div class="progress-cta in-progress" role="region" aria-label="Discovery in progress">
          <div class="progress-cta-body">
            <div class="progress-cta-eyebrow">Discovery in progress</div>
            <h2>Continue in chat</h2>
            <p>SADiscoveryAgent is working through the gaps in your intake.
            ${openItemsCount ? `<strong>${openItemsCount}</strong> open item${openItemsCount === 1 ? "" : "s"} recorded so far. ` : ""}
            Click <strong>Continue in chat →</strong> to answer the next
            question — the brief appears here once the agent finishes its
            pass.</p>
            ${_phaseExecHint({ phase: "discovery", lifecycle, stats })}
          </div>
          <div class="progress-cta-actions progress-cta-actions-row">
            <button id="continue-in-chat-btn" class="cta-btn">Continue in chat →</button>
          </div>
          ${restartDiscoveryRow}
        </div>`;
    }

    // Intake exists, discovery hasn't started.
    return `
      <div class="progress-cta" role="region" aria-label="Discovery not yet run">
        <div class="progress-cta-body">
          <div class="progress-cta-eyebrow">Next step</div>
          <h2>Discovery hasn't run yet</h2>
          <p>SADiscoveryAgent will read your intake, pattern-match against the
          reference architectures, and ask only about the gaps. Each question
          comes as an interactive card you click to answer.</p>
        </div>
        <div class="progress-cta-actions">
          <button id="start-discovery-btn" class="cta-btn">Start Discovery →</button>
        </div>
      </div>`;
  }

  // Wire click handlers on whichever progress-CTA buttons exist this render.
  // ``activeStepId`` is the current lifecycle phase (computed by render); used
  // to point the Continue-in-chat button at the right agent so the user's
  // next typed message reaches the agent that OWNS this phase, not whatever
  // agent the sticky-dropdown happens to be on (observed bug 2026-05-23:
  // dropdown stuck on SADiscoveryAgent after Discovery completed, user
  // clicked Continue in chat during Design, their messages kept hitting
  // Discovery which correctly redirected them — but they were stranded).
  const _ACTIVE_STEP_TO_AGENT = {
    discovery: "SADiscoveryAgent",
    design: "SADomainAgent",
    review: "SAOrchestratorAgent",
    validation: "SAValidationAgent",
    "event-portal": "SAEventPortalAgent",
    blueprint: "SABlueprintAgent",
  };
  function wireProgressCtaActions(root, eid, activeStepId) {
    const openChatWith = (text, agent) => {
      applyChat("open");
      // Phase start: point the agent dropdown AT the phase's owning agent so the
      // dropdown reflects the phase the user just started, and their follow-up
      // messages (e.g. answering a worker's question) route to that agent rather
      // than the previous dropdown value. Also set the one-shot dispatch pin so
      // THIS kickoff goes to the target even before the dropdown re-renders.
      if (agent) {
        _selectChatAgent(agent);
        if (text) _pendingDispatchAgent = agent;
      }
      const ci = document.getElementById("chat-input");
      if (ci) {
        if (text) ci.value = text;
        ci.focus();
        if (text) chatForm.requestSubmit?.();
      }
      // Scroll the chat log to the latest message so the user sees the
      // kickoff land + the agent's first response without having to
      // scroll manually. Defer one tick so the kickoff bubble lands
      // first; requestSubmit is sync but the bubble append happens in
      // the submit handler.
      if (chatLog) {
        requestAnimationFrame(() => {
          chatLog.scrollTop = chatLog.scrollHeight;
        });
      }
    };
    // Lock the Start/Continue button on click so the user can't double-submit
    // before the agent has responded (and before lifecycle.steps.<step>.status
    // is written, which is what flips the CTA to "Continue in chat →"). The
    // disabled state survives until the next Progress page re-render, by
    // which point the lifecycle status is set and the CTA naturally swaps.
    const lockOnClick = (btn, startingLabel) => {
      if (!btn) return;
      btn.addEventListener("click", () => {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = startingLabel;
      });
    };
    const startDiscoveryBtn = root.querySelector("#start-discovery-btn");
    const continueBtn = root.querySelector("#continue-in-chat-btn");
    const startDesignBtn = root.querySelector("#start-design-btn");
    const startDesignAutoBtn = root.querySelector("#start-design-auto-btn");
    const startReviewBtn = root.querySelector("#start-review-btn");
    const startValidationBtn = root.querySelector("#start-validation-btn");
    const startEventPortalBtn = root.querySelector("#start-event-portal-btn");
    const startEventPortalAutoBtn = root.querySelector("#start-event-portal-auto-btn");
    const startBlueprintBtn = root.querySelector("#start-blueprint-btn");
    lockOnClick(startDiscoveryBtn, "Starting Discovery…");
    lockOnClick(continueBtn, "Continuing…");
    lockOnClick(startDesignBtn, "Starting Design…");
    lockOnClick(startDesignAutoBtn, "Starting Auto…");
    lockOnClick(startReviewBtn, "Starting Review…");
    lockOnClick(startValidationBtn, "Starting Validation…");
    lockOnClick(startEventPortalBtn, "Starting Event Portal…");
    lockOnClick(startEventPortalAutoBtn, "Starting Auto…");
    lockOnClick(startBlueprintBtn, "Starting Blueprint…");

    // Shared kickoff body for Design; the click handlers prefix
    // "Mode: <mode>" so the Domain agent's prompt branches accordingly.
    // When EITHER design button is clicked, lock both so a fast double-tap
    // can't dispatch both interactive and auto for the same transition.
    const lockBothDesignButtons = () => {
      if (startDesignBtn) startDesignBtn.disabled = true;
      if (startDesignAutoBtn) startDesignAutoBtn.disabled = true;
    };

    startDiscoveryBtn?.addEventListener("click", () =>
      openChatWith(
        "Let's start discovery — please review the intake and ask your first follow-up.",
        "SADiscoveryAgent"));
    continueBtn?.addEventListener("click", () => {
      // Orchestrated Design resume: if this is an in-progress Design on the
      // orchestrated engine (e.g. after a page reload paused the in-memory
      // run), re-enter via the server orchestrator — it loads the saved
      // design-state and dispatches the next pending scope. No classic kickoff.
      const _ceid = currentProjectId?.();
      if (activeStepId === "design" && _ceid && _orchActive(_ceid)) {
        _startOrchestratedDesign(_ceid, recallExecutionMode(_ceid));
        return;
      }
      // Point the dropdown at the agent that OWNS the active phase so the
      // user's next typed message reaches it — not whatever sticky agent
      // the dropdown landed on after the previous phase finished.
      //
      // We pin via `_setUserPickedAgent` (the `sa.chat_agent_pick` key)
      // because that's the TOP of the loadAgents() precedence chain
      // (userPick > phaseAgent > previousChoice > default). The earlier
      // attempt used setStickyAgent (`sa.last_agent.*`) which is NOT in
      // that chain — it's only the FinalResponse-sticky for echo, so the
      // dropdown ignored it on the next render. Without overwriting
      // userPick, a stale pick from an earlier phase (e.g. Discovery)
      // permanently blocks phase-derived advancement.
      const targetAgent = _ACTIVE_STEP_TO_AGENT[activeStepId] || null;
      if (targetAgent) {
        const sel = document.getElementById("chat-agent-select");
        if (sel) {
          const opt = Array.from(sel.options).find(o => o.value === targetAgent);
          if (opt) sel.value = targetAgent;
        }
        if (typeof _setUserPickedAgent === "function") {
          _setUserPickedAgent(targetAgent);
        }
        // Force-re-render the dropdown options NOW (the next 15s poll
        // would otherwise be the only thing that reconciles the picker
        // against the freshly-stored userPick).
        if (typeof loadAgents === "function") {
          loadAgents();
        }
      }
      // Auto-submit "continue" as if the user typed it. The active phase
      // agent's resume-aware re-entry section reads scope_progress / on-
      // disk artifacts and picks up from the next pending unit of work.
      // Effective mode comes from session.execution_mode (intake-time
      // preference) — no Mode: marker injected here, since this CTA is
      // the dashboard's "just continue" affordance, not a phase kickoff.
      openChatWith("continue", targetAgent);
    });
    startDesignBtn?.addEventListener("click", () => {
      lockBothDesignButtons();
      // The server-side orchestrator is the only design engine — it drives scope
      // order, retries and per-scope WORKER-MODE kickoffs.
      _startOrchestratedDesign(eid, "interactive");
    });
    startDesignAutoBtn?.addEventListener("click", () => {
      lockBothDesignButtons();
      setAutoMode(eid, true);
      _startOrchestratedDesign(eid, "auto");
    });
    // Start Review — same kickoff body as the chat-pane phase-handoff card
    // (PHASE_NEXT.design.kickoff). Routes to SAOrchestratorAgent which
    // dispatches the 4 reviewer agents via peer_<AgentName>. The verb
    // (parallel fan-out vs serial sequence) is controlled by the
    // module-level REVIEW_FAN_OUT_MODE constant defined at the top of
    // this file — both call sites read the same prebuilt body via
    // REVIEW_KICKOFF_BODY so flipping the flag updates both at once.
    startReviewBtn?.addEventListener("click", () =>
      openChatWith(primeKickoff("review", "interactive", REVIEW_KICKOFF_BODY), "SAOrchestratorAgent"));

    // Single-agent phases (validation/event-portal/blueprint) — direct
    // dispatch to the phase agent. Routed through primeKickoff so both
    // entry points (Progress CTA + chat phase-handoff card) produce the
    // exact same kickoff string for each transition.
    startValidationBtn?.addEventListener("click", async () => {
      const body = await resolveKickoffBody(PHASE_NEXT.review, eid);
      openChatWith(primeKickoff("validation", "interactive", body), "SAValidationAgent");
    });

    // Event Portal (MCP-backed) — Validation's CTA. Auto vs Interactive
    // matters here because each create_* call touches a live tenant;
    // Interactive (default) pauses per layer for confirmation.
    const EP_KICKOFF_BODY = PHASE_NEXT.validation.kickoff;
    startEventPortalBtn?.addEventListener("click", () =>
      openChatWith(primeKickoff("event-portal", "interactive", EP_KICKOFF_BODY), "SAEventPortalAgent"));
    startEventPortalAutoBtn?.addEventListener("click", () =>
      openChatWith(primeKickoff("event-portal", "auto", EP_KICKOFF_BODY), "SAEventPortalAgent"));

    // Blueprint is now the terminal lifecycle step — kickoff lives in PHASE_NEXT["event-portal"].
    startBlueprintBtn?.addEventListener("click", async () => {
      const body = await resolveKickoffBody(PHASE_NEXT["event-portal"], eid);
      openChatWith(primeKickoff("blueprint", "interactive", body), "SABlueprintAgent");
    });

    root.querySelector("#restart-discovery-btn")?.addEventListener("click", () =>
      openRestartDiscoveryModal(eid));
    root.querySelector("#restart-design-btn")?.addEventListener("click", () =>
      openRestartDesignModal(eid));
  }

  // Restart Discovery — destructive action; uses a typed-id confirmation
  // modal so a stray click can't wipe state.
  function openRestartDiscoveryModal(eid) {
    openModal(`
      <div class="modal-section">
        <h2>Restart Discovery for <code>${escapeHtml(eid)}</code>?</h2>
        <p>This will:</p>
        <ul style="margin: 6px 0 12px 18px; font-size: 13px; line-height: 1.6;">
          <li>delete <code>discovery/*</code> and every downstream phase artifact
              (design, review, validation, event-portal, blueprint)</li>
          <li>clear step status + telemetry for Discovery and every downstream phase</li>
          <li>mark every phase-tagged open-item as <code>superseded</code></li>
          <li>empty <code>meta/findings.yaml</code></li>
          <li>drop every phase-authored decision from <code>meta/decisions.yaml</code>
              (orchestrator flow decisions are preserved)</li>
        </ul>
        <p>Your intake form is <strong>not</strong> touched. External Solace Cloud
        Event Portal objects (if you provisioned any) are <strong>not</strong> deprovisioned —
        only the local artifacts are cleared.</p>
        <p style="margin-top: 12px;">Type the project id <code>${escapeHtml(eid)}</code>
        to confirm:</p>
        <input id="restart-confirm-input" type="text" autocomplete="off"
               style="width: 100%; padding: 8px 10px; font-family: 'Space Mono', monospace;
                      font-size: 13px; border: 1px solid var(--border); border-radius: 4px;
                      margin-top: 6px;">
        <div class="modal-actions" style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px;">
          <button class="cta-btn cta-btn-secondary" data-modal-close>Cancel</button>
          <button id="restart-confirm-btn" class="cta-btn cta-btn-danger" disabled>Restart Discovery</button>
        </div>
      </div>`, { focus: "#restart-confirm-input" });

    const input = document.getElementById("restart-confirm-input");
    const btn = document.getElementById("restart-confirm-btn");
    input?.addEventListener("input", () => {
      btn.disabled = input.value.trim() !== eid;
    });
    btn?.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Restarting…";
      try {
        const res = await fetch(`/api/engagements/${encodeURIComponent(eid)}/discovery`, { method: "DELETE" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        // Backend cascade-wipes the full lifecycle from design through
        // blueprint. Mirror that on the frontend so every downstream
        // phase-handoff card can re-fire cleanly on the next run.
        ["discovery", "design", "review", "validation", "event-portal", "blueprint"]
          .forEach(step => _clearPhaseHint(eid, step));
        setAutoMode(eid, false);
        closeModal();
        // Refresh the view so the lifecycle banner + Progress page reflect
        // the cleared state.
        render();
        // Auto-dispatch the discovery kickoff so a single "Restart" click
        // gets the user back into an active conversation, instead of the
        // two-click "restart → start discovery" dance. Same kickoff body
        // and target as the Start Discovery button (line ~1680). The
        // per-turn override (set inside openChatWith) routes this one
        // message to SADiscoveryAgent without flipping the dropdown.
        //
        // openChatWith is scoped inside wireProgressCtaActions; render()
        // above re-wires it, but we can't grab the closure-local helper
        // from here. Easiest: drive it through the same DOM as a Start
        // Discovery click would. The button only exists after render()
        // has painted the progress-CTA into the page, so defer one tick.
        requestAnimationFrame(() => {
          const startBtn = document.getElementById("start-discovery-btn");
          if (startBtn) startBtn.click();
        });
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Restart Discovery";
        alert(`Restart failed: ${err.message}`);
      }
    });
  }

  // Restart Design — mirrors Restart Discovery. Wipes every artifact
  // under the nine SADomainAgent scope folders, supersedes any
  // domain-source open-items, drops domain-authored decisions, and
  // cascade-wipes every downstream phase (review, validation,
  // event-portal, blueprint). Orchestrator-authored decisions
  // (cross-cutting flow choices) are preserved.
  function openRestartDesignModal(eid) {
    openModal(`
      <div class="modal-section">
        <h2>Restart Design for <code>${escapeHtml(eid)}</code>?</h2>
        <p>This will:</p>
        <ul style="margin: 6px 0 12px 18px; font-size: 13px; line-height: 1.6;">
          <li>delete every artifact under <code>topic-design/</code>,
              <code>broker-select/</code>, <code>protocol-select/</code>,
              <code>integration/</code>, <code>mesh-design/</code>,
              <code>ha-dr/</code>, <code>sam-design/</code>,
              <code>event-portal/</code>, and <code>migration/</code></li>
          <li>mark any open-items recorded by Domain as <code>superseded</code></li>
          <li>clear the Design entry in <code>meta/engagement-status.yaml</code></li>
        </ul>
        <p>Your discovery brief is <strong>not</strong> touched. Phase-authored
        decisions in <code>meta/decisions.yaml</code> are <strong>dropped</strong>
        (a fresh design pass starts with a clean ledger); orchestrator flow
        decisions are preserved. External Solace Cloud Event Portal objects
        (if any) are <strong>not</strong> deprovisioned.</p>
        <p style="margin-top: 12px;">Type the project id <code>${escapeHtml(eid)}</code>
        to confirm:</p>
        <input id="restart-design-confirm-input" type="text" autocomplete="off"
               style="width: 100%; padding: 8px 10px; font-family: 'Space Mono', monospace;
                      font-size: 13px; border: 1px solid var(--border); border-radius: 4px;
                      margin-top: 6px;">
        <div class="modal-actions" style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px;">
          <button class="cta-btn cta-btn-secondary" data-modal-close>Cancel</button>
          <button id="restart-design-confirm-btn" class="cta-btn cta-btn-danger" disabled>Restart Design</button>
        </div>
      </div>`, { focus: "#restart-design-confirm-input" });

    const input = document.getElementById("restart-design-confirm-input");
    const btn = document.getElementById("restart-design-confirm-btn");
    input?.addEventListener("input", () => {
      btn.disabled = input.value.trim() !== eid;
    });
    btn?.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Restarting…";
      try {
        const res = await fetch(`/api/engagements/${encodeURIComponent(eid)}/design`, { method: "DELETE" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        // The backend cascade-wipes EVERY downstream phase (review,
        // validation, event-portal, blueprint). Mirror that on the
        // frontend so a re-run can re-fire every handoff card cleanly.
        ["design", "review", "validation", "event-portal", "blueprint"]
          .forEach(step => _clearPhaseHint(eid, step));
        setAutoMode(eid, false);
        closeModal();
        render();
        // Auto-dispatch the Design kickoff so Restart Design produces an
        // immediately-active conversation (consistent with Restart
        // Discovery's auto-dispatch). One click ↻ Restart Design →
        // wipes + dispatches; user doesn't need a second click.
        requestAnimationFrame(() => {
          document.getElementById("start-design-btn")?.click();
        });
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Restart Design";
        alert(`Restart failed: ${err.message}`);
      }
    });
  }

  // Generic Restart-phase modal — used for Review, Validation, Event Portal,
  // and Blueprint (Discovery + Design have their own dedicated openers above
  // with phase-specific copy). The cascade-downstream order:
  //   review       → wipes review + validation + event-portal + blueprint
  //   validation   → wipes validation + event-portal + blueprint
  //   event-portal → wipes event-portal + blueprint
  //   blueprint    → wipes blueprint only (terminal step)
  //
  // Every restart goes through the same DELETE /api/engagements/{eid}/{phase}
  // endpoint and clears the phase-hint dedup keys for the wiped phases so
  // the in-chat phase-handoff card can re-fire after a fresh re-run.
  const _PHASE_LABELS = {
    "review": "Review",
    "validation": "Validation",
    "event-portal": "Event Portal",
    "blueprint": "Blueprint",
  };
  const _PHASE_RESTART_COPY = {
    "review": {
      bullets: [
        "delete every reviewer narrative under <code>reviews/</code>",
        "empty <code>meta/findings.yaml</code> (a fresh review re-creates them)",
        "supersede review-deferred open-items",
        "clear the Review entry in <code>meta/engagement-status.yaml</code>",
      ],
      cascadeNote: "Validation, Event Portal, and Blueprint outputs are <strong>also wiped</strong> because they derive from the Review findings.",
      cascadeSteps: ["review", "validation", "event-portal", "blueprint"],
    },
    "validation": {
      bullets: [
        "delete <code>validation/validation-report.md</code> and the machine YAML",
        "supersede validation-source open-items",
        "clear the Validation entry in <code>meta/engagement-status.yaml</code>",
      ],
      cascadeNote: "Event Portal and Blueprint outputs are <strong>also wiped</strong> because they depend on Validation passing.",
      cascadeSteps: ["validation", "event-portal", "blueprint"],
    },
    "event-portal": {
      bullets: [
        "delete <code>event-portal/plan.yaml</code>, <code>provisioned.yaml</code>, <code>provisioning-report.md</code>, and <code>asyncapi/</code>",
        "clear the Event Portal entry in <code>meta/engagement-status.yaml</code>",
      ],
      cascadeNote: "Blueprint output is <strong>also wiped</strong>. The design-time <code>event-portal/event-portal-model.yaml</code> is preserved (it's a Design output, not a provisioning output).",
      cascadeSteps: ["event-portal", "blueprint"],
    },
    "blueprint": {
      bullets: [
        "delete <code>blueprint/architecture.md</code>, <code>runbook.md</code>, <code>diagrams/</code>, <code>packs/</code>",
        "delete <code>exports/engagement-package.zip</code>",
        "clear the Blueprint entry in <code>meta/engagement-status.yaml</code>",
      ],
      cascadeNote: "Blueprint is the terminal step — nothing else cascades.",
      cascadeSteps: ["blueprint"],
    },
  };

  function openRestartPhaseModal(phaseId, eid) {
    const label = _PHASE_LABELS[phaseId];
    const copy = _PHASE_RESTART_COPY[phaseId];
    if (!label || !copy) {
      console.warn("openRestartPhaseModal: unknown phase", phaseId);
      return;
    }
    const inputId = `restart-${phaseId}-confirm-input`;
    const btnId = `restart-${phaseId}-confirm-btn`;
    openModal(`
      <div class="modal-section">
        <h2>Restart ${escapeHtml(label)} for <code>${escapeHtml(eid)}</code>?</h2>
        <p>This will:</p>
        <ul style="margin: 6px 0 12px 18px; font-size: 13px; line-height: 1.6;">
          ${copy.bullets.map(b => `<li>${b}</li>`).join("")}
        </ul>
        <p>${copy.cascadeNote}</p>
        <p style="margin-top: 8px;">Earlier phases (intake, discovery, design, and any phases before
        ${escapeHtml(label)}) are <strong>not</strong> touched. Phase-authored decisions
        from ${escapeHtml(label)} and any cascaded phases are <strong>dropped</strong>;
        orchestrator flow decisions are preserved.</p>
        <p style="margin-top: 12px;">Type the project id <code>${escapeHtml(eid)}</code> to confirm:</p>
        <input id="${inputId}" type="text" autocomplete="off"
               style="width: 100%; padding: 8px 10px; font-family: 'Space Mono', monospace;
                      font-size: 13px; border: 1px solid var(--border); border-radius: 4px;
                      margin-top: 6px;">
        <div class="modal-actions" style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px;">
          <button class="cta-btn cta-btn-secondary" data-modal-close>Cancel</button>
          <button id="${btnId}" class="cta-btn cta-btn-danger" disabled>Restart ${escapeHtml(label)}</button>
        </div>
      </div>`, { focus: `#${inputId}` });

    const input = document.getElementById(inputId);
    const btn = document.getElementById(btnId);
    input?.addEventListener("input", () => { btn.disabled = input.value.trim() !== eid; });
    btn?.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Restarting…";
      try {
        const res = await fetch(
          `/api/engagements/${encodeURIComponent(eid)}/${encodeURIComponent(phaseId)}`,
          { method: "DELETE" },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        // Mirror the backend cascade on the frontend — clear hint dedup
        // keys for every wiped phase so their handoff cards re-fire on
        // the next completion.
        copy.cascadeSteps.forEach(step => _clearPhaseHint(eid, step));
        setAutoMode(eid, false);
        closeModal();
        render();
        // Auto-dispatch the kickoff for THIS phase, mirroring Restart
        // Discovery / Restart Design. The Start-button DOM id is
        // predictable: phase id → "start-<phase-id>-btn" (events with a
        // hyphen, like event-portal, also match). Defer one frame so
        // render() has painted the CTA into the page.
        requestAnimationFrame(() => {
          document.getElementById(`start-${phaseId}-btn`)?.click();
        });
      } catch (err) {
        btn.disabled = false;
        btn.textContent = `Restart ${label}`;
        alert(`Restart failed: ${err.message}`);
      }
    });
  }

  // ============================================================================
  // Modal helpers — single shared #modal-root, used for confirm/forms/etc.
  // ============================================================================
  const modalRoot = document.getElementById("modal-root");
  const modalCard = document.getElementById("modal-card");

  function openModal(innerHtml, opts = {}) {
    modalCard.innerHTML = innerHtml;
    modalRoot.classList.remove("hidden");
    modalRoot.setAttribute("aria-hidden", "false");
    if (opts.focus) {
      const target = modalCard.querySelector(opts.focus);
      target?.focus();
    }
  }
  function closeModal() {
    modalRoot.classList.add("hidden");
    modalRoot.setAttribute("aria-hidden", "true");
    modalCard.innerHTML = "";
  }
  modalRoot.addEventListener("click", (e) => {
    if (e.target.closest("[data-modal-close]")) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modalRoot.classList.contains("hidden")) closeModal();
  });

  function openProjectActionsModal(project) {
    const isArchived = project.status === "archived";
    // For archived projects we swap the Archive button for Unarchive, so the
    // dialog stays the user's single point of contact regardless of state.
    const archiveBtnHtml = isArchived
      ? `<button class="modal-btn modal-btn-secondary" data-action="unarchive">Unarchive</button>`
      : `<button class="modal-btn modal-btn-secondary" data-action="archive">Archive</button>`;
    openModal(`
      <h2>Project: ${escapeHtml(project.name)}${isArchived ? ' <span class="archived-tag">archived</span>' : ''}</h2>
      <div class="modal-body">
        <div class="modal-field">
          <label for="proj-rename-name">Rename</label>
          <input id="proj-rename-name" type="text" value="${escapeHtml(project.name)}">
        </div>
        <div class="modal-field">
          <label for="proj-rename-desc">Description (optional)</label>
          <textarea id="proj-rename-desc" rows="2">${escapeHtml(project.description || "")}</textarea>
        </div>
        <div id="proj-action-msg"></div>
      </div>
      <div class="modal-actions">
        <button class="modal-btn modal-btn-secondary" data-action="clone">Clone…</button>
        ${archiveBtnHtml}
        <button class="modal-btn modal-btn-danger" data-action="delete">Delete…</button>
        <button class="modal-btn modal-btn-secondary" data-modal-close>Cancel</button>
        <button class="modal-btn modal-btn-primary" data-action="rename">Save</button>
      </div>
    `, { focus: "#proj-rename-name" });

    modalCard.querySelector('[data-action="rename"]').addEventListener("click", async () => {
      const name = modalCard.querySelector("#proj-rename-name").value.trim();
      const description = modalCard.querySelector("#proj-rename-desc").value.trim();
      const msg = modalCard.querySelector("#proj-action-msg");
      if (!name) { msg.innerHTML = `<div class="modal-error">Name is required.</div>`; return; }
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(project.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, description }),
        });
        if (!r.ok) throw new Error(await r.text());
        await loadProjects();
        closeModal();
      } catch (err) {
        msg.innerHTML = `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });

    modalCard.querySelector('[data-action="clone"]').addEventListener("click", () => {
      openCloneProjectModal(project);
    });

    modalCard.querySelector('[data-action="archive"]')?.addEventListener("click", async () => {
      if (!confirm(`Archive "${project.name}"? It will be hidden from the sidebar — toggle "Show archived" to find it again.`)) return;
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(project.id)}/archive`, { method: "POST" });
        if (!r.ok) throw new Error(await r.text());
        await loadProjects();
        closeModal();
        if (currentProjectId() === project.id) navigate("/");
      } catch (err) {
        modalCard.querySelector("#proj-action-msg").innerHTML =
          `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });

    modalCard.querySelector('[data-action="unarchive"]')?.addEventListener("click", async () => {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(project.id)}/unarchive`, { method: "POST" });
        if (!r.ok) throw new Error(await r.text());
        await loadProjects();
        closeModal();
      } catch (err) {
        modalCard.querySelector("#proj-action-msg").innerHTML =
          `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });

    modalCard.querySelector('[data-action="delete"]').addEventListener("click", () => {
      openDeleteProjectModal(project);
    });
  }

  function openDeleteProjectModal(project) {
    // Type-to-confirm sub-modal. Replaces the existing modal contents so
    // there's a single modal-root in flight at any time — preserves the
    // Escape-to-close behavior wired on modalRoot.
    openModal(`
      <h2>Delete project</h2>
      <div class="modal-body">
        <p>This will <strong>permanently delete</strong> <code>${escapeHtml(project.name)}</code>
           and all its artifacts, decisions, and telemetry. This cannot be undone.</p>
        <div class="modal-field">
          <label for="proj-delete-confirm">
            Type the project name (<code>${escapeHtml(project.name)}</code>) to enable Delete:
          </label>
          <input id="proj-delete-confirm" type="text" autocomplete="off" spellcheck="false">
        </div>
        <div id="proj-delete-msg"></div>
      </div>
      <div class="modal-actions">
        <button class="modal-btn modal-btn-secondary" data-modal-close>Cancel</button>
        <button class="modal-btn modal-btn-danger" data-action="delete-go" disabled>Delete permanently</button>
      </div>
    `, { focus: "#proj-delete-confirm" });

    const input = modalCard.querySelector("#proj-delete-confirm");
    const goBtn = modalCard.querySelector('[data-action="delete-go"]');
    input.addEventListener("input", () => {
      goBtn.disabled = input.value !== project.name;
    });

    goBtn.addEventListener("click", async () => {
      if (input.value !== project.name) return;     // belt-and-braces
      const msg = modalCard.querySelector("#proj-delete-msg");
      goBtn.disabled = true;
      goBtn.textContent = "Deleting…";
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(project.id)}`, {
          method: "DELETE",
        });
        if (!r.ok) throw new Error(await r.text());
        const result = await r.json();
        // 409 mid-flight comes through as a 200 body with {error, status_code: 409}
        // (the adapter doesn't translate to a real 4xx for these handlers).
        // Surface it before assuming success.
        if (result?.error) throw new Error(result.hint || result.error);
        await loadProjects();
        closeModal();
        if (currentProjectId() === project.id) navigate("/");
      } catch (err) {
        goBtn.disabled = false;
        goBtn.textContent = "Delete permanently";
        msg.innerHTML = `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });
  }

  function openCloneProjectModal(source) {
    openModal(`
      <h2>Clone "${escapeHtml(source.name)}"</h2>
      <div class="modal-body">
        <p class="muted">A new project is seeded with the source's intake/brief. Decisions and artifacts don't carry over.</p>
        <div class="modal-field">
          <label for="proj-clone-name">New project name</label>
          <input id="proj-clone-name" type="text" value="${escapeHtml(source.name + " (copy)")}">
        </div>
        <div id="proj-clone-msg"></div>
      </div>
      <div class="modal-actions">
        <button class="modal-btn modal-btn-secondary" data-modal-close>Cancel</button>
        <button class="modal-btn modal-btn-primary" data-action="clone-go">Clone</button>
      </div>
    `, { focus: "#proj-clone-name" });

    modalCard.querySelector('[data-action="clone-go"]').addEventListener("click", async () => {
      const new_name = modalCard.querySelector("#proj-clone-name").value.trim();
      const msg = modalCard.querySelector("#proj-clone-msg");
      if (!new_name) { msg.innerHTML = `<div class="modal-error">Name is required.</div>`; return; }
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(source.id)}/clone`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_name }),
        });
        if (!r.ok) throw new Error(await r.text());
        const result = await r.json();
        // Response shape from clone_project: { source, clone: {id, name, ...},
        // brief_seeded, intake_seeded }. Older callers expected the project
        // directly at the top level — guard against both.
        const newId = result?.clone?.id || result?.id;
        await loadProjects();
        closeModal();
        // Drop the user into the intake editor for the new project so they
        // can fill in gaps / new fields. Falls back to the overview if we
        // somehow couldn't extract an id (defensive).
        if (newId) {
          window.location.href = `/intake/edit/${encodeURIComponent(newId)}`;
        }
      } catch (err) {
        msg.innerHTML = `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });
  }

  function openResolveItemModal(eid, itemId, description) {
    openModal(`
      <h2>Resolve open item</h2>
      <div class="modal-body">
        <p class="muted">${escapeHtml(description || itemId)}</p>
        <div class="modal-field">
          <label for="resolve-note">Resolution note</label>
          <textarea id="resolve-note" rows="3" placeholder="What's the resolution?"></textarea>
        </div>
        <div id="resolve-msg"></div>
      </div>
      <div class="modal-actions">
        <button class="modal-btn modal-btn-secondary" data-modal-close>Cancel</button>
        <button class="modal-btn modal-btn-primary" data-action="resolve-go">Resolve</button>
      </div>
    `, { focus: "#resolve-note" });

    modalCard.querySelector('[data-action="resolve-go"]').addEventListener("click", async () => {
      const note = modalCard.querySelector("#resolve-note").value.trim();
      try {
        const r = await fetch(`/api/engagements/${encodeURIComponent(eid)}/open-items/${encodeURIComponent(itemId)}/resolve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resolution_note: note }),
        });
        if (!r.ok) throw new Error(await r.text());
        closeModal();
        render();
      } catch (err) {
        modalCard.querySelector("#resolve-msg").innerHTML =
          `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });
  }

  // ============================================================================
  // Settings page (SPA route /settings) — two-pane: inner sidebar + content
  // ============================================================================
  const SETTINGS_SECTIONS = [
    { id: "settings", label: "Settings", group: "Sections" },
    { id: "usage",    label: "Usage",    group: "Sections" },
  ];

  function _settingsSectionFromHash() {
    const h = (window.location.hash || "").replace(/^#/, "");
    return SETTINGS_SECTIONS.find(s => s.id === h)?.id || "settings";
  }

  async function renderSettingsView(root) {
    const active = _settingsSectionFromHash();
    root.innerHTML = `
      <div class="settings-page">
        <nav class="settings-nav" aria-label="Settings sections">
          <div class="settings-nav-group">
            <div class="settings-nav-label">Sections</div>
            ${SETTINGS_SECTIONS.map(s => `
              <a class="settings-nav-item ${s.id === active ? "active" : ""}"
                 href="#${s.id}" data-section="${s.id}">${escapeHtml(s.label)}</a>
            `).join("")}
          </div>
        </nav>
        <div class="settings-content" id="settings-content"></div>
      </div>
    `;
    const content = root.querySelector("#settings-content");
    _renderSettingsSection(content, active);

    // Inner-sidebar nav: intercept clicks so we don't reload the page,
    // update the hash, and re-render the right pane.
    root.querySelectorAll(".settings-nav-item").forEach(a => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const id = a.dataset.section;
        if (!id) return;
        history.replaceState({}, "", `/settings#${id}`);
        root.querySelectorAll(".settings-nav-item").forEach(x =>
          x.classList.toggle("active", x.dataset.section === id));
        _renderSettingsSection(content, id);
      });
    });
  }

  function _renderSettingsSection(content, section) {
    if (section === "usage") return _renderUsageSection(content);
    return _renderAccountSection(content);
  }

  function _renderAccountSection(root) {
    const me = currentUser?.user || null;
    const flags = currentUser || {};
    root.innerHTML = `
      <div class="settings-eyebrow">Account</div>
      <h1>Settings</h1>

      <section class="settings-section">
        <h2>Account</h2>
        ${me ? `
          <div class="settings-flag-row"><span class="flag-name">Username</span><span class="flag-value">${escapeHtml(me.username || me.name)}</span></div>
          <div class="settings-flag-row"><span class="flag-name">Email</span><span class="flag-value">${escapeHtml(me.email || "—")}</span></div>
          <div class="settings-flag-row"><span class="flag-name">Role</span><span class="flag-value">${me.is_admin ? "admin" : "user"}</span></div>
          <p style="margin-top:14px"><button id="open-pw-change" class="cta-btn">Change password…</button></p>
        ` : `<p class="muted">Not signed in.</p>`}
      </section>

      <section class="settings-section">
        <h2>Server flags</h2>
        <p class="muted" style="font-size:12px;margin-bottom:8px">Read-only — controlled by environment variables on the server.</p>
        <div class="settings-flag-row">
          <span class="flag-name">WEBUI_REQUIRE_AUTH</span>
          <span class="flag-value ${flags.require_auth ? "on" : "off"}">${flags.require_auth ? "true" : "false"}</span>
        </div>
        <div class="settings-flag-row">
          <span class="flag-name">WEBUI_ENABLE_SIGNUP</span>
          <span class="flag-value ${flags.enable_signup ? "on" : "off"}">${flags.enable_signup ? "true" : "false"}</span>
        </div>
      </section>
    `;
    root.querySelector("#open-pw-change")?.addEventListener("click", openPasswordChangeModal);
  }

  // ---- Usage section -------------------------------------------------------
  // Pulls /api/me/token-usage and renders summary cards + a grouped breakdown.

  const USAGE_RANGES = [
    { id: "7d",  label: "Last 7 days",  days: 7  },
    { id: "30d", label: "Last 30 days", days: 30 },
    { id: "90d", label: "Last 90 days", days: 90 },
    { id: "all", label: "All time",     days: null },
  ];
  const USAGE_GROUPINGS = [
    { id: "project", label: "Project" },
    { id: "agent",   label: "Agent" },
    { id: "model",   label: "Model" },
    { id: "day",     label: "Day" },
    { id: "step",    label: "Step" },
  ];
  // project === "" means "All projects" (cross-engagement rollup via /api/me/token-usage).
  // Otherwise project is an engagement_id; we hit /api/engagements/<eid>/token-usage
  // which doesn't accept group_by=project — _loadUsage transparently swaps to "agent".
  let _usageState = { range: "30d", groupBy: "project", project: "" };
  let _usageProjects = [];

  function _renderUsageSection(root) {
    root.innerHTML = `
      <div class="settings-eyebrow">Telemetry</div>
      <h1>Usage</h1>
      <p class="muted" style="font-size:13px;margin-bottom:4px">
        LLM token usage across your projects, captured per agent on every model call.
      </p>

      <div class="usage-controls">
        <label>Range
          <select id="usage-range">
            ${USAGE_RANGES.map(r => `<option value="${r.id}" ${r.id === _usageState.range ? "selected" : ""}>${escapeHtml(r.label)}</option>`).join("")}
          </select>
        </label>
        <label>Project
          <select id="usage-project">
            <option value="" ${_usageState.project === "" ? "selected" : ""}>All projects</option>
          </select>
        </label>
        <label>Group by
          <select id="usage-group"></select>
        </label>
      </div>

      <div id="usage-body"><p class="usage-empty">Loading…</p></div>
    `;
    const rangeSel = root.querySelector("#usage-range");
    const projectSel = root.querySelector("#usage-project");
    const groupSel = root.querySelector("#usage-group");
    _populateUsageGroupings(groupSel);
    rangeSel.addEventListener("change", () => { _usageState.range = rangeSel.value; _loadUsage(root); });
    projectSel.addEventListener("change", () => {
      _usageState.project = projectSel.value;
      // group_by=project is invalid against the per-engagement endpoint —
      // demote to "agent" so the next fetch doesn't 400. Same demotion lets
      // us hide the Project option from the dropdown while a project is picked.
      if (_usageState.project && _usageState.groupBy === "project") {
        _usageState.groupBy = "agent";
      }
      _populateUsageGroupings(groupSel);
      _loadUsage(root);
    });
    groupSel.addEventListener("change", () => { _usageState.groupBy = groupSel.value; _loadUsage(root); });

    // Populate the Project dropdown asynchronously. The Range / Group by
    // controls stay usable while we wait — first /api/me/token-usage
    // request fires below in _loadUsage().
    _loadUsageProjects(projectSel);
    _loadUsage(root);
  }

  function _populateUsageGroupings(groupSel) {
    const filteredToOne = !!_usageState.project;
    const options = USAGE_GROUPINGS
      .filter(g => !(filteredToOne && g.id === "project"))
      .map(g => `<option value="${g.id}" ${g.id === _usageState.groupBy ? "selected" : ""}>${escapeHtml(g.label)}</option>`);
    groupSel.innerHTML = options.join("");
  }

  async function _loadUsageProjects(projectSel) {
    try {
      const r = await fetch("/api/projects", { headers: { "Accept": "application/json" } });
      if (!r.ok) return;
      const projects = await r.json();
      if (!Array.isArray(projects)) return;
      _usageProjects = projects;
      const opts = ['<option value="">All projects</option>'].concat(
        projects.map(p => {
          const id = p.id || "";
          const name = p.name || id;
          const sel = id === _usageState.project ? " selected" : "";
          return `<option value="${escapeHtml(id)}"${sel}>${escapeHtml(name)}</option>`;
        }),
      );
      projectSel.innerHTML = opts.join("");
    } catch (_err) {
      // Silent: All projects still works; per-project filtering just isn't selectable.
    }
  }

  async function _loadUsage(root) {
    const body = root.querySelector("#usage-body");
    const range = USAGE_RANGES.find(r => r.id === _usageState.range) || USAGE_RANGES[1];
    const since = range.days == null ? null
      : new Date(Date.now() - range.days * 86400 * 1000).toISOString();
    const params = new URLSearchParams({ group_by: _usageState.groupBy });
    if (since) params.set("since", since);
    // Pick endpoint based on project filter — per-engagement when one is picked,
    // otherwise the cross-project rollup.
    const url = _usageState.project
      ? `/api/engagements/${encodeURIComponent(_usageState.project)}/token-usage?${params}`
      : `/api/me/token-usage?${params}`;
    try {
      const r = await fetch(url, { headers: { "Accept": "application/json" } });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.error || `HTTP ${r.status}`);
      }
      const data = await r.json();
      _renderUsageBody(body, data);
    } catch (err) {
      body.innerHTML = `<div class="usage-error">Could not load usage — ${escapeHtml(String(err.message || err))}</div>`;
    }
  }

  function _formatTokens(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(n >= 10_000_000 ? 1 : 2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + "K";
    return String(n);
  }

  function _renderUsageBody(body, data) {
    const totals = data?.totals || { input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, total_tokens: 0, calls: 0, total_cost_usd: 0 };
    const rows = data?.rows || [];
    const projectCount = data?.project_count ?? null;
    const totalCost = Number(totals.total_cost_usd || 0);
    // Format $ with sensible precision: tiny (<$0.01) → 4 decimals so it
    // doesn't read as $0.00; otherwise 2 decimals like normal currency.
    const fmtUsd = (n) => n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
    // Latency: average over only the rows that carry it (timed_calls), so
    // pre-instrumentation rows don't drag the mean to zero. "—" until the
    // duration-capture build has run against this range.
    const timedCalls = Number(totals.timed_calls || 0);
    const avgMs = timedCalls > 0 ? Math.round(Number(totals.duration_ms || 0) / timedCalls) : null;
    const fmtLatency = (ms) => ms == null ? "—" : ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : ms + "ms";
    const rowLatency = (r) => {
      const tc = Number(r.timed_calls || 0);
      return tc > 0 ? fmtLatency(Math.round(Number(r.duration_ms || 0) / tc)) : null;
    };

    const summaryHtml = `
      <div class="usage-summary">
        <div class="usage-card">
          <div class="label">Total tokens</div>
          <div class="value">${_formatTokens(totals.total_tokens)}</div>
          <div class="sub">${totals.calls.toLocaleString()} LLM calls${projectCount !== null ? ` · ${projectCount} project${projectCount === 1 ? "" : "s"}` : ""}</div>
        </div>
        <div class="usage-card">
          <div class="label">Input</div>
          <div class="value">${_formatTokens(totals.input_tokens)}</div>
          <div class="sub">${totals.cached_input_tokens > 0 ? `cached ${_formatTokens(totals.cached_input_tokens)}` : "no cached hits"}</div>
        </div>
        <div class="usage-card">
          <div class="label">Output</div>
          <div class="value">${_formatTokens(totals.output_tokens)}</div>
          <div class="sub">&nbsp;</div>
        </div>
        <div class="usage-card">
          <div class="label">Avg latency</div>
          <div class="value">${fmtLatency(avgMs)}</div>
          <div class="sub">${timedCalls > 0 ? `per call · ${timedCalls.toLocaleString()} timed` : "awaiting instrumented calls"}</div>
        </div>
        <div class="usage-card">
          <div class="label">Est. cost</div>
          <div class="value">${fmtUsd(totalCost)}</div>
          <div class="sub">${totalCost > 0 ? "USD · public-API pricing" : "model price not registered"}</div>
        </div>
      </div>
    `;

    if (!rows.length) {
      body.innerHTML = `
        ${summaryHtml}
        <div class="usage-breakdown">
          <div class="usage-empty">No telemetry recorded yet for the selected range.</div>
        </div>
      `;
      return;
    }

    const maxTotal = Math.max(1, ...rows.map(r => r.total_tokens));
    const breakdownHtml = `
      <div class="usage-breakdown">
        <h3>By ${escapeHtml(USAGE_GROUPINGS.find(g => g.id === _usageState.groupBy)?.label || _usageState.groupBy)}</h3>
        ${rows.map(r => {
          const pct = Math.max(2, Math.round(r.total_tokens / maxTotal * 100));
          const display = r.label ? r.label : r.key;
          return `
            <div class="usage-row">
              <div class="key" title="${escapeHtml(r.key)}">${escapeHtml(display)}</div>
              <div class="bar-wrap"><div class="bar" style="width: ${pct}%"></div></div>
              <div class="total">${_formatTokens(r.total_tokens)}<span class="calls">· ${r.calls}</span>${rowLatency(r) ? `<span class="calls"> · ${rowLatency(r)}/call</span>` : ""}</div>
            </div>
          `;
        }).join("")}
      </div>
    `;
    body.innerHTML = summaryHtml + breakdownHtml;
  }

  function openPasswordChangeModal() {
    openModal(`
      <h2>Change password</h2>
      <div class="modal-body">
        <div class="modal-field">
          <label for="pw-old">Current password</label>
          <input id="pw-old" type="password" autocomplete="current-password">
        </div>
        <div class="modal-field">
          <label for="pw-new">New password</label>
          <input id="pw-new" type="password" autocomplete="new-password">
        </div>
        <div class="modal-field">
          <label for="pw-new2">Confirm new password</label>
          <input id="pw-new2" type="password" autocomplete="new-password">
        </div>
        <div id="pw-msg"></div>
      </div>
      <div class="modal-actions">
        <button class="modal-btn modal-btn-secondary" data-modal-close>Cancel</button>
        <button class="modal-btn modal-btn-primary" data-action="pw-go">Change password</button>
      </div>
    `, { focus: "#pw-old" });

    modalCard.querySelector('[data-action="pw-go"]').addEventListener("click", async () => {
      const old_password = modalCard.querySelector("#pw-old").value;
      const new_password = modalCard.querySelector("#pw-new").value;
      const confirm_pw = modalCard.querySelector("#pw-new2").value;
      const msg = modalCard.querySelector("#pw-msg");
      if (!old_password || !new_password) { msg.innerHTML = `<div class="modal-error">Both fields required.</div>`; return; }
      if (new_password !== confirm_pw) { msg.innerHTML = `<div class="modal-error">New passwords don't match.</div>`; return; }
      try {
        const r = await fetch("/api/auth/change-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ old_password, new_password }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
        msg.innerHTML = `<div class="modal-success">Password updated — signing you out.</div>`;
        setTimeout(() => window.location.href = d.redirect || "/login", 800);
      } catch (err) {
        msg.innerHTML = `<div class="modal-error">${escapeHtml(String(err.message || err))}</div>`;
      }
    });
  }

  // ============================================================================
  // Chat panel — wired to /api/chat/{message,stream/{session_id}}
  // ============================================================================
  let chatSessionId = null;
  let chatEventSource = null;
  const chatLog = document.getElementById("chat-log");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");

  // Single source of truth for scroll-to-bottom. rAF-scheduled so it runs
  // AFTER the browser has laid out the just-mutated DOM — without this,
  // appending a tall card and reading scrollHeight in the same tick gives
  // the pre-layout height and falls short.
  function scrollChatToBottom() {
    if (!chatLog) return;
    requestAnimationFrame(() => {
      chatLog.scrollTop = chatLog.scrollHeight;
    });
  }
  // Auto-scroll on every DOM change inside chatLog. Catches every code path
  // that mutates the panel (streaming tokens, question cards, switch-agent
  // chips, status updates, replay events, error messages) without having to
  // remember a chatLog.scrollTop assignment at each site.
  if (chatLog && typeof MutationObserver !== "undefined") {
    new MutationObserver(scrollChatToBottom).observe(chatLog, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  // Click-to-expand for tool-call pills (3-line clamp by default).
  // Delegated on chatLog so dynamically-added pills get this for free.
  // We bail if the user is mid-selection — clicking to expand should NOT
  // interrupt a text-selection drag (the click event fires AFTER mouseup;
  // a non-empty selection means the user was selecting, not clicking).
  chatLog?.addEventListener("click", (e) => {
    const pill = e.target.closest(".activity-pill.tool-call");
    if (!pill) return;
    const sel = window.getSelection();
    if (sel && sel.toString().length > 0) return;   // selection in progress
    pill.classList.toggle("expanded");
  });

  // Chat history is persisted per project in localStorage. The session id is
  // derived from the active project PLUS a per-tab suffix — two tabs of the
  // same project must NOT share an SSE stream, otherwise both browsers see
  // an interleaved transcript and the agent receives messages from a session
  // it can't disambiguate. sessionStorage is per-tab (unlike localStorage),
  // so a refresh in the same tab keeps the same tab_id (Last-Event-Id replay
  // still works), but a new tab gets a fresh one.
  const TAB_ID_KEY = "solace-architect-tab-id";
  function _tabId() {
    let t = sessionStorage.getItem(TAB_ID_KEY);
    if (!t) {
      // Random 8-char suffix; collision space within one user's tabs is large
      // enough that we don't bother with crypto-strength uniqueness.
      t = ((window.crypto && window.crypto.randomUUID)
            ? window.crypto.randomUUID().slice(0, 8)
            : Math.random().toString(36).slice(2, 10));
      sessionStorage.setItem(TAB_ID_KEY, t);
    }
    return t;
  }
  // History key strips the tab suffix so reopening a tab still finds the
  // prior project's saved log. Two tabs running concurrently could clobber
  // each other's writes — that's an accepted trade-off (per-tab persistence
  // would lose history every tab close); the load-bearing fix is SSE
  // isolation, which the per-tab session_id below delivers.
  const CHAT_HISTORY_KEY = (sid) => {
    const stripped = String(sid || "").replace(/-[a-z0-9]{4,}$/, "");
    return `solace-architect-chat-log:${stripped}`;
  };
  function deriveChatSessionId() {
    return `chat-${currentProjectId() || "global"}-${_tabId()}`;
  }
  function loadChatHistory(sid) {
    try { return JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY(sid)) || "[]"); }
    catch { return []; }
  }
  function saveChatHistory(sid, messages) {
    try { localStorage.setItem(CHAT_HISTORY_KEY(sid), JSON.stringify(messages.slice(-500))); }
    catch { /* quota / private mode — silently skip */ }
  }
  function hasChatHistory(sid) {
    return loadChatHistory(sid).length > 0;
  }

  // Persist (or update) an in-flight streaming agent bubble keyed by
  // msgId so the same entry is replaced as text streams in. Without
  // this, only the FINAL text (from finalizeAgentBubble) lands in
  // localStorage — refresh mid-stream and the partial bubble vanishes,
  // even though it was visible on screen seconds earlier.
  // The {role: "agent", inflight: true} marker tells the rehydrate path
  // it's an in-flight snapshot (rendered identically to a finalized one;
  // if the user resumes, the live SSE replaces this entry on next save).
  function _persistStreamingAgentText(msgId, text) {
    if (!chatSessionId || !msgId || !text) return;
    const log = loadChatHistory(chatSessionId);
    const idx = log.findIndex(m => m.msgId === msgId);
    const entry = { role: "agent", text, ts: Date.now(), msgId, inflight: true };
    if (idx >= 0) log[idx] = entry;
    else log.push(entry);
    saveChatHistory(chatSessionId, log);
  }

  // Debounced wrapper — streaming text updates fire on every chunk
  // (potentially many per second); persist at most every 750ms so we
  // don't thrash localStorage on a fast stream.
  let _streamingPersistTimer = null;
  let _streamingPersistPending = null;       // { msgId, text }
  function _schedulePersistStreamingAgent(msgId, text) {
    _streamingPersistPending = { msgId, text };
    if (_streamingPersistTimer) return;
    _streamingPersistTimer = setTimeout(() => {
      _streamingPersistTimer = null;
      const p = _streamingPersistPending;
      _streamingPersistPending = null;
      if (p) _persistStreamingAgentText(p.msgId, p.text);
    }, 750);
  }
  function _flushStreamingPersist() {
    if (_streamingPersistTimer) {
      clearTimeout(_streamingPersistTimer);
      _streamingPersistTimer = null;
    }
    const p = _streamingPersistPending;
    _streamingPersistPending = null;
    if (p) _persistStreamingAgentText(p.msgId, p.text);
  }

  // Render agent text as sanitized HTML (markdown parsed by marked,
  // sanitized by DOMPurify). User text stays as textContent — we have
  // no reason to render markdown of the user's own input, and it
  // sidesteps any HTML they might paste.
  function renderAgentMarkdown(el, text) {
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      // Libraries didn't load (offline, blocked CDN, etc.) — degrade
      // gracefully to plain text.
      el.textContent = text;
      return;
    }
    try {
      const html = marked.parse(text, { breaks: true, gfm: true });
      el.innerHTML = DOMPurify.sanitize(html);
    } catch (err) {
      el.textContent = text;
    }
  }

  function appendChatMessage(role, text, opts = {}) {
    const empty = chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();
    const div = document.createElement("div");
    div.className = `chat-msg ${role}`;
    if (role === "agent") {
      renderAgentMarkdown(div, text);
    } else {
      div.textContent = text;
    }
    // Tag the message visually when the user routed it to SAM. Badge is
    // appended AFTER the role-based content render because
    // renderAgentMarkdown / textContent both clobber children. CSS
    // positions it at the top-right of the bubble.
    if (opts.routedToSam) {
      div.classList.add("routed-to-sam");
      const badge = document.createElement("span");
      badge.className = "chat-msg-routing-badge";
      badge.textContent = "→ SAM";
      badge.title = "Sent to SAM's stock OrchestratorAgent (bypassed the SA family)";
      div.appendChild(badge);
    }
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    if (!opts.skipPersist && chatSessionId) {
      const log = loadChatHistory(chatSessionId);
      const entry = { role, text, ts: Date.now() };
      if (opts.routedToSam) entry.routedToSam = true;
      log.push(entry);
      saveChatHistory(chatSessionId, log);
      updateLoadHistoryButton?.();
    }
  }

  // Switch the chat panel to the project context derived from the current URL.
  // Auto-rehydrates the previous transcript when localStorage has one for
  // this project — the "Load history" button stays as a manual re-trigger
  // for the case where rehydrate races a stream that's already cleared
  // the panel.
  let chatProjectContext = null;
  function syncChatProjectContext() {
    const nextSid = deriveChatSessionId();
    const proj = currentProjectId() || "global";
    // Preserve the live chat + SSE when the active session already belongs to
    // THIS project — including a timestamped fresh-session id (chat-<proj>-<ts>)
    // from an orchestrated scope boundary or stream-drop recovery. Only reset on
    // a genuine PROJECT switch. Without this, navigating away from Overview and
    // back wiped the in-flight transcript and closed the live stream (the
    // "bland screen" — the chat/progress no longer reflected current state).
    if (chatSessionId === nextSid
        || (chatSessionId && chatSessionId.startsWith(`chat-${proj}-`))) {
      updateLoadHistoryButton();
      return;
    }
    if (chatEventSource) { chatEventSource.close(); chatEventSource = null; }
    chatSessionId = nextSid;
    chatProjectContext = currentProjectId() || null;
    // Default placeholder while the welcome-card fetch is in flight.
    chatLog.innerHTML = `
      <div class="chat-empty">
        <p>Conversational interaction with any agent on the SAM mesh.</p>
        <p class="muted">${chatProjectContext
          ? `Chat is scoped to <code>${escapeHtml(chatProjectContext)}</code>. Loading state…`
          : `No project active — pick one from the sidebar to scope the chat, or talk to any mesh agent directly.`}
        </p>
      </div>`;
    updateLoadHistoryButton();
    // Auto-rehydrate the prior transcript when we have one for this project,
    // and scroll to the latest message. The MutationObserver installed at
    // panel-init time handles scroll automatically as messages render.
    // When no transcript exists yet, fall back to the contextual welcome
    // card so the panel isn't an empty void.
    if (chatProjectContext) {
      if (hasChatHistory(chatSessionId)) {
        loadHistoryForCurrentContext();
      } else {
        hydrateChatWelcomeCard(chatProjectContext, chatSessionId);
      }
    }
  }

  // Replace the chat-empty placeholder with a state-aware welcome card
  // for the active project. Fetches /lifecycle and /overview to figure
  // out the current step + recommended next action, renders a card with
  // a quick-action button, and primes the chat input on click.
  async function hydrateChatWelcomeCard(eid, sid) {
    let lifecycle = { steps: {} };
    let stats = {};
    let artifacts = [];
    try {
      [lifecycle, stats, artifacts] = await Promise.all([
        fetch(`/api/engagements/${encodeURIComponent(eid)}/lifecycle`).then(r => r.json()).catch(() => ({ steps: {} })),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/overview`).then(r => r.json()).catch(() => ({})),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/artifacts`).then(r => r.json()).catch(() => []),
      ]);
    } catch { /* fall through to defaults */ }

    // If the user has navigated/typed/loaded history while the fetch was
    // in flight, don't clobber what they're doing.
    if (chatSessionId !== sid) return;
    if (!chatLog.querySelector(".chat-empty")) return;

    const hasIntake = artifacts.includes("discovery/intake.json");
    const discoveryStatus = lifecycle?.steps?.discovery?.status || "NOT_STARTED";
    const discoveryNote = lifecycle?.steps?.discovery?.note || "";
    const discoveryDone = discoveryStatus === "DONE" || discoveryStatus === "DONE_WITH_CONCERNS";
    const hasDiscoveryBrief = artifacts.includes("discovery/discovery-brief.yaml");
    const openItemsCount = (stats.open_items_blocking || 0) + (stats.open_items_advisory || 0);
    const discoveryInProgress = !discoveryDone && (hasDiscoveryBrief || openItemsCount > 0);
    const designStatus = lifecycle?.steps?.design?.status || "NOT_STARTED";
    const designDone = designStatus === "DONE" || designStatus === "DONE_WITH_CONCERNS";
    // Resume-from-checkpoint: SADomainAgent writes `scope_progress` after
    // each scope completes (record_scope_progress tool). When the user
    // reopens an engagement mid-Design, this lets us offer "Resume from
    // scope N" with the correct next-scope prime instead of restarting
    // Design from scope 1. Persists across SAM restarts because the
    // scope_progress is in meta/engagement-status.yaml on disk.
    const designScopeProgress = lifecycle?.steps?.design?.scope_progress || null;
    const designResumable = !designDone && designScopeProgress
      && designScopeProgress.next
      && Array.isArray(designScopeProgress.done)
      && designScopeProgress.done.length > 0;

    // BLOCKED gate — any phase in BLOCKED status halts CTA advancement.
    // The agent that returned BLOCKED has recorded the underlying open
    // items; the user has to resolve them (Open Items pane → Resolve)
    // before Start Validation / Start Event Portal / Start Blueprint
    // appears again. Find the first blocked phase in canonical order so
    // we can name it in the message.
    const _PHASE_ORDER_FOR_BLOCK_CHECK = ["discovery", "design", "review",
                                          "validation", "event-portal", "blueprint"];
    let blockedPhaseId = null;
    for (const pid of _PHASE_ORDER_FOR_BLOCK_CHECK) {
      if (lifecycle?.steps?.[pid]?.status === "BLOCKED") { blockedPhaseId = pid; break; }
    }
    const blockingOpenItemsCount = stats.open_items_blocking || 0;

    // Lifecycle steps in order — used to find current + next.
    const steps = [
      { id: "intake",     label: "Intake",        done: hasIntake },
      { id: "discovery",  label: "Discovery",     done: discoveryDone },
      { id: "design",     label: "Design",        done: designDone },
      { id: "review",     label: "Review",        done: false },
      { id: "validation", label: "Validation",    done: false },
      { id: "blueprint",  label: "Blueprint",     done: false },
    ];
    const firstUnfinished = steps.find(s => !s.done);
    const lastDone = [...steps].reverse().find(s => s.done);
    const currentLabel = firstUnfinished ? firstUnfinished.label : "Complete";

    // Decide the primary action button per state. `agent` field tells
    // the click handler which agent to switch the chat dropdown to
    // before priming the message — important on the Discovery → Design
    // handoff so the user doesn't have to flip the dropdown manually.
    let action = null;
    // Engagement-complete short-circuit: every applicable phase is in a
    // terminal state (DONE / DONE_WITH_CONCERNS / SKIPPED). Flip the
    // welcome card to a "download the package" finisher rather than
    // continuing to prompt for a next-phase start. Has to come before the
    // BLOCKED check because a phase can land in BLOCKED with the engagement
    // already complete (e.g. a late-recorded blocking open-item against a
    // DONE phase) — but in practice the BLOCKED path is the wrong CTA at
    // that point too; the user wants the package, not the resolve link.
    // Recompute completion across all phases here so we don't fight with
    // the per-phase variables computed above.
    const _phaseIsTerminal = (status) =>
      status === "DONE" || status === "DONE_WITH_CONCERNS" || status === "SKIPPED";
    const _statusOf = (id) => lifecycle?.steps?.[id]?.status || "NOT_STARTED";
    const _engagementComplete =
      hasIntake
      && _phaseIsTerminal(_statusOf("discovery"))
      && _phaseIsTerminal(_statusOf("design"))
      && _phaseIsTerminal(_statusOf("review"))
      && _phaseIsTerminal(_statusOf("validation"))
      && _phaseIsTerminal(_statusOf("event-portal"))
      && _phaseIsTerminal(_statusOf("blueprint"));
    if (_engagementComplete) {
      action = {
        label: "Download engagement package →",
        href: `/api/engagements/${encodeURIComponent(eid)}/exports/zip`,
        secondary: {
          label: "Browse audience packs →",
          href: `/projects/${encodeURIComponent(eid)}/export`,
        },
      };
    } else if (blockedPhaseId) {
      const blockedLabel = _PHASE_LABELS?.[blockedPhaseId]
        || blockedPhaseId.replace(/-/g, " ");
      action = {
        label: `Resolve ${blockingOpenItemsCount || ""} blocking items first →`.replace(/\s+/g, " "),
        href: `/projects/${encodeURIComponent(eid)}/open-items`,
        blockedNote: `${blockedLabel} is BLOCKED — advancement is gated until blocking open items are resolved.`,
      };
    } else if (!hasIntake) {
      action = { label: "Open intake form →", href: `/intake/edit/${encodeURIComponent(eid)}` };
    } else if (!discoveryDone && !discoveryInProgress) {
      action = {
        label: "Start Discovery →",
        agent: "SADiscoveryAgent",
        prime: "Let's start discovery — please review the intake and ask your first follow-up.",
      };
    } else if (discoveryInProgress) {
      // Empty prime made this button look broken — clicking it cleared the
      // input but never sent anything, so users saw "nothing happens".
      // Now it auto-sends a continuation nudge so SADiscoveryAgent picks up
      // wherever it paused (next open gap / next question / next decision).
      action = {
        label: "Continue Discovery →",
        agent: "SADiscoveryAgent",
        prime: "Continue discovery — ask the next question, or finalise the brief if all gaps are resolved.",
      };
    } else if (designResumable) {
      // Resume-from-checkpoint — design is mid-stream with a recorded
      // next scope. Build the per-scope kickoff via the same helper
      // the auto-advance loop uses, so resuming after a SAM restart or
      // browser-close produces the EXACT same agent prompt as a normal
      // mid-engagement scope advance. Two buttons: Resume Interactive
      // (default) and Resume Auto (continue auto-advance loop).
      const next = designScopeProgress.next;
      const done = designScopeProgress.done || [];
      // Prime is unused for design — the click handler routes SADomainAgent
      // through _startOrchestratedDesign (orchestrator rebuilds the real kickoff).
      const resumePrime = "";
      const nicelyNamedNext = String(next).replace(/-/g, " ");
      action = {
        label: `Resume Design — scope ${done.length + 1} (${nicelyNamedNext}) →`,
        agent: "SADomainAgent",
        prime: resumePrime,
        mode: "interactive",
        autoVariant: {
          label: "Resume Auto ⚡",
          agent: "SADomainAgent",
          prime: resumePrime,
          mode: "auto",
          title: `Resume Design in auto mode from scope ${done.length + 1} (${nicelyNamedNext}); will auto-advance through remaining scopes.`,
        },
      };
    } else if (discoveryDone) {
      // Discovery done → next step is Design. Two buttons (interactive / auto).
      // The click handler intercepts agent === "SADomainAgent" and routes to
      // _startOrchestratedDesign, so `prime` is intentionally empty — the
      // orchestrator builds the real per-scope WORKER-MODE kickoff server-side.
      action = {
        label: "Start Design →",
        agent: "SADomainAgent",
        prime: "",
        mode: "interactive",
        autoVariant: {
          label: "Start Auto ⚡",
          agent: "SADomainAgent",
          prime: "",
          mode: "auto",
          title: "Take all recommended options; every decision still appears live in chat as it's made.",
        },
      };
    }

    // Notes shown beneath the state row: blocked-note (when applicable)
    // takes priority and is styled red; otherwise the discovery agent's
    // last note (set_step_status note) is surfaced as a muted line.
    const noteLine = action?.blockedNote
      ? `<p class="welcome-blocked-note">${escapeHtml(action.blockedNote)}</p>`
      : (discoveryNote ? `<p class="welcome-note">${escapeHtml(discoveryNote)}</p>` : "");

    chatLog.innerHTML = `
      <div class="chat-msg agent welcome-card">
        <div class="welcome-eyebrow">${escapeHtml(eid)}</div>
        <div class="welcome-title">Where you are</div>
        <div class="welcome-state-row">
          <div>
            <div class="welcome-state-label">Current step</div>
            <div class="welcome-state-value">${escapeHtml(currentLabel)}</div>
          </div>
          ${lastDone ? `<div>
            <div class="welcome-state-label">Last completed</div>
            <div class="welcome-state-value">${escapeHtml(lastDone.label)}</div>
          </div>` : ""}
          <div>
            <div class="welcome-state-label">Open items</div>
            <div class="welcome-state-value">${(stats.open_items_blocking || 0)} blocking · ${(stats.open_items_advisory || 0)} advisory</div>
          </div>
        </div>
        ${noteLine}
        ${action ? `<div class="welcome-actions">
          ${action.href
            ? `<a class="cta-btn welcome-action" href="${action.href}">${escapeHtml(action.label)}</a>`
            : `<button class="cta-btn welcome-action"
                       data-prime="${escapeHtml(action.prime || "")}"
                       data-agent="${escapeHtml(action.agent || "")}"
                       data-mode="${escapeHtml(action.mode || "interactive")}">${escapeHtml(action.label)}</button>`}
          ${action.autoVariant
            ? `<button class="cta-btn cta-btn-auto welcome-action"
                       data-prime="${escapeHtml(action.autoVariant.prime || "")}"
                       data-agent="${escapeHtml(action.autoVariant.agent || "")}"
                       data-mode="${escapeHtml(action.autoVariant.mode || "auto")}"
                       title="${escapeHtml(action.autoVariant.title || "")}">${escapeHtml(action.autoVariant.label)}</button>`
            : ""}
          ${action.secondary
            ? `<a class="cta-btn cta-btn-secondary welcome-action" href="${action.secondary.href}">${escapeHtml(action.secondary.label)}</a>`
            : ""}
        </div>` : ""}
        ${action && action.prime !== undefined && firstUnfinished && firstUnfinished.id !== "intake"
          ? `<p class="welcome-override">
               <span class="welcome-override-hint">Agent already said this phase is complete?</span>
               <button class="welcome-override-btn" data-override-step="${escapeHtml(firstUnfinished.id)}"
                       data-override-label="${escapeHtml(firstUnfinished.label)}">
                 Mark ${escapeHtml(firstUnfinished.label)} done →
               </button>
             </p>` : ""}
        <p class="welcome-hint">Or just type your question below — the agent has full project context.</p>
      </div>`;

    // Manual phase-advance override — used when an agent has declared
    // completion in chat but never called set_step_status. Without this
    // affordance the user is stranded with the same "Continue X" button
    // forever. POSTs to /api/engagements/{eid}/lifecycle/{step}/mark-done
    // which is gated by a confirm() so it can't be hit accidentally.
    chatLog.querySelectorAll(".welcome-override-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const step = btn.getAttribute("data-override-step");
        const label = btn.getAttribute("data-override-label");
        const ok = window.confirm(
          `Mark ${label} as DONE? This advances the dashboard to the next phase ` +
          `even though the agent didn't record completion itself. Only do this when ` +
          `you've verified the work actually is complete.`
        );
        if (!ok) return;
        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = "Marking…";
        try {
          const resp = await fetch(
            `/api/engagements/${encodeURIComponent(eid)}/lifecycle/${encodeURIComponent(step)}/mark-done`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "include",
              body: JSON.stringify({
                status: "DONE",
                note: `Manual override via dashboard at ${new Date().toISOString()}`,
              }),
            }
          );
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          // Reload the welcome card so the next-phase CTA surfaces.
          // syncChatProjectContext() re-fetches lifecycle and re-renders.
          if (typeof syncChatProjectContext === "function") syncChatProjectContext();
        } catch (e) {
          btn.disabled = false;
          btn.textContent = originalText;
          alert(`Failed to mark ${label} done: ${e.message}. Check sam.log.`);
        }
      });
    });

    chatLog.querySelectorAll(".welcome-action[data-prime]").forEach(btn => {
      btn.addEventListener("click", () => {
        // Disable on first click — same double-submit guard as the
        // Progress CTA and Phase Handoff card. Welcome-card buttons
        // auto-submit a primed message; without the lock a double
        // tap fires two POSTs to /api/chat/message. Also lock the
        // sibling action button (the Interactive/Auto pair) so the
        // user can't accidentally fire both modes for the same phase.
        if (btn.disabled) return;
        chatLog.querySelectorAll(".welcome-action[data-prime]").forEach(b => b.disabled = true);
        const originalLabel = btn.textContent;
        btn.textContent = originalLabel.replace(/[→⚡]\s*$/,"").trim() + "…";
        const rawPrime = btn.getAttribute("data-prime") || "";
        const mode = btn.getAttribute("data-mode") || "interactive";
        // Prepend "Mode: …" only when the target agent actually branches
        // on it. firstUnfinished.id is the TARGET phase the user is
        // about to enter; primeKickoff is a no-op for agents that don't
        // read Mode (Discovery, Review, Validation, Blueprint).
        const prime = primeKickoff(firstUnfinished?.id, mode, rawPrime);
        const agent = btn.getAttribute("data-agent") || "";
        // Design dispatch is owned by the orchestrator (the only design engine).
        // Route BOTH start and resume-from-checkpoint through it so the worker
        // always gets WORKER MODE + the computed map — never a client-side classic
        // kickoff (the prime is ignored for design).
        if (agent === "SADomainAgent") {
          if (mode === "auto") setAutoMode(currentProjectId?.(), true);
          applyChat("open");
          _startOrchestratedDesign(currentProjectId?.(), mode);
          return;
        }
        // Auto mode arms the per-scope dispatch loop so finalizeAgentBubble
        // chains scope-N+1 once scope-N marks done.
        if (mode === "auto") setAutoMode(currentProjectId?.(), true);
        applyChat("open");
        // Switch the chat agent dropdown before priming so the message
        // is dispatched to the right agent (e.g. Discovery → Domain
        // handoff when Discovery is DONE).
        // Auto-select the target agent (dropdown value + persistent pick + re-
        // render) so it reflects the phase being entered AND survives the 15s
        // agent re-poll, routing the user's follow-ups to the right agent.
        if (agent) _selectChatAgent(agent);
        if (chatInput) {
          chatInput.value = prime;
          chatInput.focus();
          if (prime) {
            // Auto-submit primed messages so the user doesn't have to
            // hit Send themselves — this is the "Start Discovery" /
            // "Start Design" handoff flow.
            chatForm.requestSubmit?.();
          }
        }
      });
    });

    // Side-effect: also refresh the sticky lifecycle bar with the data
    // we just fetched (so we don't double-fetch). currentStepHint comes
    // from the active phase's persisted note when present.
    let currentStepHint = "";
    let blocked = false;
    if (firstUnfinished) {
      const stepInfo = lifecycle?.steps?.[firstUnfinished.id];
      if (stepInfo?.note) currentStepHint = String(stepInfo.note);
      if (stepInfo?.status === "BLOCKED") blocked = true;
    }
    updateLifecycleBar({
      eid, lifecycle, hasIntake, discoveryDone, discoveryInProgress,
      currentLabel, lastDoneLabel: lastDone?.label, currentStepHint, blocked,
    });
  }

  // Sticky one-line lifecycle indicator above the chat log. Always
  // visible when a project is active; reflects "Step: <current> · Next:
  // <next>". Refreshed by syncChatProjectContext on project change AND
  // by the Progress page's 10s auto-refresh tick.
  function updateLifecycleBar(state) {
    const bar = document.getElementById("chat-lifecycle-bar");
    if (!bar) return;
    if (!state || !state.eid) {
      bar.classList.add("hidden");
      bar.innerHTML = "";
      bar.setAttribute("aria-hidden", "true");
      return;
    }
    const {
      hasIntake, discoveryDone, discoveryInProgress,
      currentLabel, lastDoneLabel, currentStepHint, blocked,
    } = state;
    // BLOCKED outranks every other state — a phase that returned BLOCKED
    // is a hard stop; the user must resolve the underlying blocking items
    // before any advancement. Render the dot red + non-pulsing so it
    // visually screams "needs your attention" rather than blending into
    // the green in-progress animation.
    const stepClass = blocked ? "blocked"
      : discoveryDone ? "done"
      : discoveryInProgress ? "in-progress"
      : hasIntake ? "ready"
      : "waiting";
    bar.classList.remove("hidden");
    bar.setAttribute("aria-hidden", "false");
    // Two-line layout. Line 1: phase + last completed. Line 2: which
    // step inside the phase is currently running (sourced from the
    // active step's `note`, set by the agent on each set_step_status).
    // When no hint is available we hide line 2 rather than render an
    // empty band.
    bar.innerHTML = `
      <span class="chat-lifecycle-dot ${stepClass}" aria-hidden="true"></span>
      <span class="chat-lifecycle-text">
        <span class="chat-lifecycle-line1">
          <strong>${escapeHtml(currentLabel || "Idle")}</strong>${
            lastDoneLabel ? ` · last: ${escapeHtml(lastDoneLabel)}` : ""
          }
        </span>
        ${currentStepHint
          ? `<span class="chat-lifecycle-line2">${escapeHtml(currentStepHint)}</span>`
          : ""}
      </span>`;
  }

  // Refresh the lifecycle bar from the network. Called by the Progress
  // page's auto-refresh tick so the bar reflects state changes the user
  // wouldn't otherwise see (e.g. while sitting on Requirements / chat).
  async function refreshLifecycleBar() {
    const eid = currentProjectId();
    if (!eid) { updateLifecycleBar(null); return; }
    try {
      const [lifecycle, stats, artifacts] = await Promise.all([
        fetch(`/api/engagements/${encodeURIComponent(eid)}/lifecycle`).then(r => r.json()).catch(() => ({ steps: {} })),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/overview`).then(r => r.json()).catch(() => ({})),
        fetch(`/api/engagements/${encodeURIComponent(eid)}/artifacts`).then(r => r.json()).catch(() => []),
      ]);
      const hasIntake = artifacts.includes("discovery/intake.json");
      const discoveryStatus = lifecycle?.steps?.discovery?.status || "NOT_STARTED";
      const discoveryDone = discoveryStatus === "DONE" || discoveryStatus === "DONE_WITH_CONCERNS";
      const openItemsCount = (stats.open_items_blocking || 0) + (stats.open_items_advisory || 0);
      const hasDiscoveryBrief = artifacts.includes("discovery/discovery-brief.yaml");
      const discoveryInProgress = !discoveryDone && (hasDiscoveryBrief || openItemsCount > 0);
      const designStatus = lifecycle?.steps?.design?.status || "NOT_STARTED";
      const designDone = designStatus === "DONE" || designStatus === "DONE_WITH_CONCERNS";
      const designScopes = ["topic-design","broker-select","protocol-select","integration","mesh-design","ha-dr","sam-design","event-portal","migration"];
      const hasDesignArtifact = artifacts.some(a => designScopes.some(s => a.startsWith(s + "/")));
      const designInProgress = !designDone && (hasDesignArtifact || designStatus === "NEEDS_CONTEXT");
      const steps = [
        { id: "intake", label: "Intake", done: hasIntake },
        { id: "discovery", label: "Discovery", done: discoveryDone },
        { id: "design", label: "Design", done: designDone },
        { id: "review", label: "Review", done: false },
      ];
      const firstUnfinished = steps.find(s => !s.done);
      const lastDone = [...steps].reverse().find(s => s.done);
      // Pass overall "in progress" so the dot animates while any step's mid-flow.
      const anyInProgress = discoveryInProgress || designInProgress;
      // Line-2 hint: which sub-step is currently active. Sources, in order:
      //   1. Latest set_step_status note on the active phase (most reliable).
      //   2. For Design, the scope-progress hint derived from artifacts.
      //   3. The most recent activity-bar text (transient tool-name fallback).
      const activePhaseId = firstUnfinished?.id;
      let currentStepHint = "";
      if (activePhaseId) {
        const stepInfo = lifecycle?.steps?.[activePhaseId];
        if (stepInfo?.note) currentStepHint = String(stepInfo.note);
      }
      // Design-specific: when no explicit note, surface the current scope.
      if (!currentStepHint && designInProgress) {
        const completedScopes = designScopes.filter(s =>
          artifacts.some(a => a.startsWith(s + "/")));
        const nextScope = designScopes.find(s => !completedScopes.includes(s));
        if (nextScope) {
          currentStepHint = `Scope ${completedScopes.length + 1}/${designScopes.length}: ${nextScope.replace(/-/g, " ")}`;
        }
      }
      // Fallback: live activity-bar text while no persisted note yet.
      if (!currentStepHint && chatActivityBar && !chatActivityBar.classList.contains("hidden")) {
        currentStepHint = chatActivityBar.textContent || "";
      }
      // BLOCKED escalation — if the active phase returned BLOCKED, the
      // chat lifecycle dot turns red and stops the pulse animation. The
      // user can't miss it; advancement CTAs in the welcome card refuse
      // until the underlying blocking open-items are resolved.
      const blocked = activePhaseId
        ? (lifecycle?.steps?.[activePhaseId]?.status === "BLOCKED")
        : false;
      updateLifecycleBar({
        eid, hasIntake,
        discoveryDone: discoveryDone || designDone,  // shows "done" tint past discovery
        discoveryInProgress: anyInProgress,
        currentLabel: firstUnfinished?.label || "Complete",
        lastDoneLabel: lastDone?.label,
        currentStepHint,
        blocked,
      });
    } catch { /* swallow; next tick retries */ }
  }

  function updateLoadHistoryButton() {
    const btn = document.getElementById("chat-load-history");
    if (!btn) return;
    btn.disabled = !hasChatHistory(chatSessionId);
    btn.title = btn.disabled
      ? "No saved conversation for this context yet."
      : "Load previous conversation for this project";
  }

  function loadHistoryForCurrentContext() {
    if (!chatSessionId) return;
    // Wipe before render so repeat invocations (auto-load on context
    // switch + manual button click) don't double-render the transcript.
    // Every streamed message persists into localStorage as it arrives, so
    // wiping never loses anything that wasn't already in the saved log.
    chatLog.innerHTML = "";
    const log = loadChatHistory(chatSessionId);
    log.forEach(m => appendChatMessage(m.role, m.text, {
      skipPersist: true,
      routedToSam: !!m.routedToSam,
    }));
    if (!chatEventSource) openSseStream(chatSessionId);
  }
  document.getElementById("chat-load-history")?.addEventListener("click", loadHistoryForCurrentContext);

  // Helper: drop the in-memory ADK session for this engagement and start a
  // brand-new one. On-disk artifacts/decisions/scope_progress are
  // untouched. Used by the chat-header button AND the stream-drop /
  // error-card recovery flows. The new session id encodes the timestamp
  // so the next /api/chat/message POST hits a clean ADK session — SAM's
  // PERSISTENT session_service keys off this id.
  function startFreshChatSession(opts = {}) {
    chatSessionId = `chat-${currentProjectId() || "x"}-${Date.now()}`;
    // Tear down the live SSE stream so the next dispatch opens a fresh one
    // bound to the new session id. Without this, an EventSource left open
    // on the old session continues receiving (now-orphaned) events.
    if (chatEventSource) {
      try { chatEventSource.close(); } catch { /* defensive */ }
      chatEventSource = null;
    }
    // Cancel any in-flight task tracking — the running task (if any)
    // continues server-side, but its FinalResponse can no longer reach
    // this page (SSE stream just closed). Without this, the SEND/STOP
    // button stays armed on a task we'll never hear back from.
    if (typeof _setChatInflight === "function") _setChatInflight("");
    if (typeof _cancelPendingAutoResume === "function") _cancelPendingAutoResume();
    // Reset stream-drop retry counter — fresh session = fresh budget.
    // Also clear the auto-jump-to-fresh-session flag: a MANUAL fresh-session
    // click is a user-driven recovery, so the next error burst should get
    // the full two-step budget again rather than going straight to give-up.
    const _eid = (typeof currentProjectId === "function") ? currentProjectId() : "";
    if (_eid && typeof _setAutoResumeRetries === "function") _setAutoResumeRetries(_eid, 0);
    if (_eid && typeof _resetFreshEscalations === "function") _resetFreshEscalations(_eid);
    if (_eid && typeof _clearDropFingerprint === "function") _clearDropFingerprint(_eid);
    chatLog.innerHTML = "";
    // opts.message may be undefined when invoked as a DOM click handler (the
    // event object lacks .message) — falls back to the default copy.
    appendChatMessage(
      "agent",
      (opts && typeof opts.message === "string" && opts.message) ||
        "Started a fresh chat session. On-disk artifacts, decisions, and scope progress are preserved — pick up wherever you left off.",
    );
  }
  document.getElementById("chat-new-session")?.addEventListener("click", startFreshChatSession);

  // Pull user-visible text out of an A2A event. Walks status.message.parts
  // and any Task-level artifacts; ignores non-text parts (DataPart/FilePart
  // are tool-call internals, surfaced separately via extractDataParts).
  function extractAgentText(ev) {
    const data = ev?.data || {};
    const parts = [];
    const msgParts = data.status?.message?.parts;
    if (Array.isArray(msgParts)) parts.push(...msgParts);
    if (Array.isArray(data.artifacts)) {
      for (const a of data.artifacts) {
        if (Array.isArray(a.parts)) parts.push(...a.parts);
      }
    }
    return parts
      .filter(p => p && (p.kind === "text" || p.type === "text") && (p.text || ""))
      .map(p => p.text)
      .join("\n")
      .trim();
  }

  // Pull SAM data-part signals (tool_invocation_start, tool_result, etc.) out
  // of an A2A event. Discriminator is data.type per solace_agent_mesh.common.data_parts.
  function extractDataParts(ev) {
    const ed = ev?.data || {};
    const parts = [];
    const msgParts = ed.status?.message?.parts;
    if (Array.isArray(msgParts)) parts.push(...msgParts);
    if (Array.isArray(ed.artifacts)) {
      for (const a of ed.artifacts) {
        if (Array.isArray(a.parts)) parts.push(...a.parts);
      }
    }
    return parts
      .filter(p => p && (p.kind === "data" || p.type === "data") && p.data && typeof p.data === "object")
      .map(p => p.data);
  }

  // While the agent is "thinking", we paint:
  //   (a) an "activity stream" — accumulating pills, one per distinct
  //       short status update emitted by the agent ("Loading discovery
  //       framework…", "Checking integration hub…"). Latest pill is
  //       in-progress, earlier ones get a ✓.
  //   (b) a "live bubble" below the pills — only used for long-form
  //       text chunks that are clearly the streaming final answer
  //       (e.g. multi-line markdown the LLM is composing).
  // On FinalResponse, the pills lock in (all ✓), the live bubble is
  // replaced with the final markdown answer, and we persist.
  let pendingAgentMsg = null;     // { el, lastText, pillsContainer, pills: [{el, text}] }

  // While streaming, hide the raw ```question JSON block behind a
  // "preparing form…" placeholder. We can't safely partial-parse the
  // JSON yet; the form materializes on finalizeAgentBubble.
  // Also hides ```switch_agent blocks (deterministic chip emitted by the
  // orchestrator's _peer_agent_switch_hint patch). The chip materializes
  // on finalize via parseSwitchAgentBlocks; until then the JSON would
  // bleed into the streaming bubble as visible noise.
  function maskQuestionBlockDuringStream(text) {
    let masked = text;
    const qIdx = masked.indexOf("```question");
    if (qIdx !== -1) {
      const preamble = masked.slice(0, qIdx).trimEnd();
      masked = preamble + (preamble ? "\n\n" : "") + "📝 Preparing question…";
    }
    const sIdx = masked.indexOf("```switch_agent");
    if (sIdx !== -1) {
      // Strip the switch_agent block silently — no placeholder needed,
      // it's a sidecar suggestion not a form blocking the conversation.
      masked = masked.slice(0, sIdx).trimEnd();
    }
    return masked;
  }

  // Classify a streaming text as either a "status pill" (short, single-
  // line, agent-narrating-what-it's-doing) or "live bubble content" (long
  // or multi-line — the actual answer streaming in).
  function isStatusPill(text) {
    if (!text) return false;
    const t = text.trim();
    if (!t) return false;
    if (t.length > 120) return false;
    if (t.includes("\n")) return false;
    return true;
  }

  // Live agent-activity bar: a sticky one-liner above the chat log that
  // mirrors the latest status text or tool-trace label, so the user can
  // always see what the agent is doing right now without scrolling
  // through the bubble. Cleared (and hidden) by finalizeAgentBubble.
  const chatActivityBar = document.getElementById("chat-activity-bar");
  function setActivityBar(text) {
    if (!chatActivityBar) return;
    if (text) {
      chatActivityBar.textContent = text;
      chatActivityBar.classList.remove("hidden");
    } else {
      chatActivityBar.textContent = "";
      chatActivityBar.classList.add("hidden");
    }
  }

  // Heuristic: does this look like the continuation of the previous
  // pill rather than a fresh status? SAM's resolver sometimes flushes
  // the agent's status text mid-word ("republ" then "ish)"), and each
  // chunk independently passes isStatusPill — surfacing as two pills
  // where the second is meaningless on its own. If `text` starts with
  // a lowercase letter, a closing bracket, or punctuation, treat it
  // as a continuation of the previous pill.
  function _looksLikeContinuation(text) {
    if (!text) return false;
    const first = text.trimStart().charAt(0);
    if (!first) return false;
    // Lowercase letter, closing brace/bracket/paren, or sentence-tail
    // punctuation → continuation of an unfinished prior pill.
    return /[a-z\)\]\}\.\,\;\:\!\?…]/.test(first);
  }

  function appendActivityPill(text) {
    if (!pendingAgentMsg) return;
    // Merge into the previous pill if this fragment looks like a
    // continuation (mid-word buffer flush). Without this the user sees
    // pills like "REST for republ" followed by "ish)" — visually broken.
    const prev = pendingAgentMsg.pills[pendingAgentMsg.pills.length - 1];
    if (prev && _looksLikeContinuation(text)) {
      const span = prev.el.querySelector(".activity-pill-text");
      if (span) {
        prev.text = (prev.text || "") + text;
        span.textContent = prev.text;
      }
      setActivityBar(prev.text);
      chatLog.scrollTop = chatLog.scrollHeight;
      return;
    }
    setActivityBar(text);
    // Mark previous pill as done.
    if (prev) {
      prev.el.classList.remove("in-progress");
      prev.el.classList.add("done");
      const icon = prev.el.querySelector(".activity-pill-icon");
      if (icon) icon.textContent = "✓";
    }
    const pill = document.createElement("div");
    pill.className = "activity-pill in-progress";
    pill.innerHTML = `<span class="activity-pill-icon">⏳</span><span class="activity-pill-text"></span>`;
    pill.querySelector(".activity-pill-text").textContent = text;
    pendingAgentMsg.pillsContainer.appendChild(pill);
    pendingAgentMsg.pills.push({ el: pill, text });
  }

  // Render args dict as `key="value", key2=12`. Per user request the
  // text is no longer truncated — full strings + all keys are surfaced.
  // CSS lets the pill wrap to multiple lines for long arg lists.
  function summarizeToolArgs(args) {
    if (!args || typeof args !== "object") return "()";
    const keys = Object.keys(args);
    if (!keys.length) return "()";
    const fmt = (v) => {
      if (typeof v === "string") return `"${v}"`;
      if (v === null || typeof v !== "object") return String(v);
      if (Array.isArray(v)) return JSON.stringify(v);
      try { return JSON.stringify(v); } catch { return "{…}"; }
    };
    return "(" + keys.map(k => `${k}=${fmt(args[k])}`).join(", ") + ")";
  }

  // Map known tool names to human-readable trace-pill labels, with the
  // most useful arg woven in. Anything not in this map falls back to
  // the raw tool name + summarised arg list (the previous behaviour).
  // Keep labels short — they sit inside a pill row in the chat panel.
  function friendlyToolLabel(name, args) {
    args = args || {};
    // Per user request: never truncate trace text. `trunc` is now a
    // pass-through; pill width is controlled by CSS (wraps to multiple
    // lines for long values).
    const trunc = (s) => s || "";
    switch (name) {
      case "load_preamble":         return "Loading shared guidance";
      case "load_jargon_list":      return "Loading terminology list";
      case "load_grounding":        return `Loading docs — ${trunc(args.topic || "?")}`;
      case "fetch_canonical_source":return `Fetching ${trunc(args.url_or_topic || "?")}`;
      case "query_integration_hub": return `Checking Integration Hub for ${trunc(args.backend_system || "?")}`;
      case "record_grounding_gap":  return `Flagging missing grounding (${trunc(args.topic || "?")})`;
      case "list_projects":         return "Listing projects";
      case "list_artifacts":        return args.category ? `Listing artifacts (${trunc(args.category)})` : "Listing artifacts";
      case "read_artifact":         return `Reading ${trunc(args.artifact_name || "artifact")}`;
      case "write_artifact":        return `Writing ${trunc(args.artifact_name || "artifact")}`;
      case "record_decision":       return `Recording decision — ${trunc(args.context || "")}`;
      case "read_decisions":        return "Reading prior decisions";
      case "record_finding":        return `Recording finding (${trunc(args.severity || "")})`;
      case "read_findings":         return "Reading findings";
      case "update_finding_status": return `Updating finding ${trunc(args.finding_id || "")} → ${trunc(args.new_status || "")}`;
      case "record_open_item":      return `Logging open item (${trunc(args.severity || "")})`;
      case "read_open_items":       return "Reading open items";
      case "update_open_item_status":return `Updating open item ${trunc(args.item_id || "")} → ${trunc(args.new_status || "")}`;
      case "record_feedback":       return "Recording feedback";
      case "read_feedback":         return "Reading feedback";
      case "ask_user_question":     return `Preparing question — ${trunc(args.question_id || args.question || "")}`;
      case "set_step_status":       return `Step ${trunc(args.step || "?")} → ${trunc(args.status || "?")}`;
      case "get_engagement_status": return "Reading step statuses";
      case "clear_step_status":     return `Clearing step status — ${trunc(args.step || "?")}`;
      case "parse_intake_document": return "Parsing intake document";
      case "export_intake_from_project":return "Exporting intake from project";
      case "import_source_context": return "Importing source context";
      default:                      return null;  // null → fall back to raw name + args
    }
  }

  // tool_invocation_start → add an in-progress trace pill.
  function appendToolTrace(d) {
    // Skip framework-internal tools — names that start with `_` are
    // SAM/ADK plumbing (e.g. `_continue_generation` fires when the LLM
    // hits max tokens and SAM auto-continues; `_notify_artifact_save`
    // is internal book-keeping). Surfacing these as user-visible pills
    // is just noise — the user sees "_continue_generation ()" with no
    // context. Real tools (read_artifact, record_decision, etc.) never
    // have an underscore prefix.
    if (d.tool_name && d.tool_name.startsWith("_")) return;
    if (!pendingAgentMsg) openThinkingBubble();
    const prev = pendingAgentMsg.pills[pendingAgentMsg.pills.length - 1];
    if (prev) {
      prev.el.classList.remove("in-progress");
      prev.el.classList.add("done");
      const icon = prev.el.querySelector(".activity-pill-icon");
      if (icon) icon.textContent = "✓";
    }
    const pill = document.createElement("div");
    pill.className = "activity-pill tool-call in-progress";
    pill.innerHTML = `<span class="activity-pill-icon">⏳</span>`
      + `<span class="activity-pill-text">`
      + `<span class="tool-call-name"></span>`
      + `<span class="tool-call-args"></span>`
      + `</span>`;
    const friendly = friendlyToolLabel(d.tool_name, d.tool_args);
    // Mirror into the sticky activity bar so the user sees the current
    // step without scrolling. Both paths feed it.
    setActivityBar(friendly || `${d.tool_name || "(tool)"}…`);
    if (friendly) {
      // Friendly path — single line, no monospace blob of raw args.
      pill.querySelector(".tool-call-name").textContent = friendly;
      pill.querySelector(".tool-call-args").textContent = "";
      pill.classList.add("tool-call-friendly");
    } else {
      // Unknown tool — fall back to raw name + summarised args so we
      // still show something useful for tools we haven't labelled yet.
      pill.querySelector(".tool-call-name").textContent = d.tool_name || "(unknown)";
      pill.querySelector(".tool-call-args").textContent = summarizeToolArgs(d.tool_args);
    }
    pendingAgentMsg.pillsContainer.appendChild(pill);
    const entry = { el: pill, text: d.tool_name || "(unknown)", fnCallId: d.function_call_id };
    pendingAgentMsg.pills.push(entry);
    if (d.function_call_id) pendingAgentMsg.pillByCallId.set(d.function_call_id, entry);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // tool_result → mark the matching pill done (by function_call_id).
  function completeToolTrace(d) {
    if (!pendingAgentMsg) return;
    const entry = d.function_call_id ? pendingAgentMsg.pillByCallId.get(d.function_call_id) : null;
    if (entry) {
      entry.el.classList.remove("in-progress");
      entry.el.classList.add("done");
      const icon = entry.el.querySelector(".activity-pill-icon");
      if (icon) icon.textContent = "✓";
    }
    // Independently of pill matching, look for a step-completion signal so
    // the handoff card can render once this turn finalizes.
    _queuePhaseHandoffFromToolResult(d);
    // Capture ask_user_question schemas from the tool result itself. The
    // prompt asks the agent to echo the schema as a fenced ```question
    // block in its text, but LLMs sometimes truncate the echo to just the
    // trailing characters (observed 2026-05-23: 6-byte trailing `"} ``` `
    // with no chip card rendered). The tool's authoritative result carries
    // the full schema; we stash it as a fallback so finalizeAgentBubble
    // can render the form even when the text echo is missing or partial.
    _captureToolEmittedQuestionSchema(d);
  }

  // Stash ask_user_question schemas from tool_result data parts onto the
  // pending bubble. Indexed by schema.id for dedup against text-echoed
  // ```question blocks (text wins; tool fills the gap).
  function _captureToolEmittedQuestionSchema(d) {
    if (!pendingAgentMsg) return;
    if (d?.tool_name !== "ask_user_question") return;
    const result = d.result_data;
    if (!result || result.ok === false) return;
    const schema = result?.data?.schema;
    if (!schema || typeof schema !== "object") return;
    if (!schema.id || !schema.kind) return;
    pendingAgentMsg.toolEmittedSchemas = pendingAgentMsg.toolEmittedSchemas || [];
    pendingAgentMsg.toolEmittedSchemas.push(schema);
  }

  // Phase-handoff: shared vocabulary used by the in-chat completion card and
  // (downstream) the Progress CTA, so the user sees the same next-action label
  // wherever the system points it out. Keep entries even for phases whose next
  // agent isn't wired yet — we still want to render "complete" cards for them.
  // Target phases whose receiving agent actually branches on `Mode: interactive`
  // vs `Mode: auto`. Only two: Design (SADomainAgent) and Event Portal
  // (SAEventPortalAgent). Every other agent (Review/Validation/Blueprint)
  // expects "Phase: X" as the first line of the kickoff and would misdetect its
  // phase if "Mode: …" is prepended above it. Flip carefully when a new agent
  // learns Mode-branching.
  const TARGETS_WITH_MODE_KICKOFF = new Set(["design", "event-portal"]);

  // Source-phase → target-phase mapping (mirrors the lifecycle order). Used to
  // resolve the target from the phase-handoff card, where the local `step`
  // variable is the SOURCE phase that just completed.
  const PHASE_NEXT_STEP = {
    discovery: "design",
    design: "review",
    review: "validation",
    validation: "event-portal",
    "event-portal": "blueprint",
  };

  function primeKickoff(targetStep, mode, kickoff) {
    if (!kickoff) return "";
    return TARGETS_WITH_MODE_KICKOFF.has(targetStep)
      ? `Mode: ${mode}\n\n${kickoff}`
      : kickoff;
  }

  const PHASE_NEXT = {
    discovery: {
      nextLabel: "Design",
      ctaLabel: "Start Design →",
      agent: "SADomainAgent",
      kickoff: "Discovery is complete. Read the discovery brief, then begin with topic-design (scope 1) and walk through the design scopes in their canonical order. Skip scopes the brief opts out of. Inside each scope, ask me only when there is a blocking decision to make.",
    },
    design: {
      nextLabel: "Review",
      ctaLabel: "Start Review →",
      agent: "SAOrchestratorAgent",
      // Use the same prebuilt body the manual Start Review button does
      // (REVIEW_KICKOFF_BODY — selected by the REVIEW_FAN_OUT_MODE flag
      // at the top of the file). Single source of truth.
      kickoff: REVIEW_KICKOFF_BODY,
      // Reviewers are non-interactive (no per-finding chat questions),
      // so the Auto/Interactive distinction has no semantic effect for
      // this phase — render a single CTA.
      singleAction: true,
    },
    review: {
      nextLabel: "Validation",
      ctaLabel: "Start Validation →",
      agent: "SAValidationAgent",
      kickoff: "Phase: validation\n\nRun the Validation phase. Apply your 6-criterion rubric (requirement coverage, antipattern scan, consistency, deferred findings, terminology compliance, schema sanity). Record blocking open-items with affecting_step=\"blueprint\" so the lifecycle gates correctly. Write validation/validation-report.md and the machine YAML. Call set_step_status(step=\"validation\", ...) per the rule.",
      // Server computes the kickoff with deterministic PRECOMPUTED CHECKS injected
      // (the validation rules engine); `kickoff` above is the offline fallback.
      kickoffUrl: eid => `/api/engagements/${encodeURIComponent(eid)}/validation/kickoff`,
      singleAction: true,
    },
    validation: {
      nextLabel: "Event Portal",
      ctaLabel: "Start Event Portal →",
      agent: "SAEventPortalAgent",
      // Lifecycle-mode kickoff for the MCP-backed EP agent. Reads
      // event-portal/event-portal-model.yaml from Design, dry-runs a plan
      // against the live tenant, optionally confirms per layer, then
      // creates/reuses domains→schemas→events→applications and exports
      // AsyncAPI specs. Auto mode skips per-layer confirmations.
      kickoff: "Phase: event-portal\n\nRun the Event Portal provisioning phase. Pre-flight (opt-in check + read event-portal/event-portal-model.yaml + verify tenant via list_application_domains + validation gate), dry-run plan, then per-layer creation [domains → schemas → events → applications] with reuse-by-content-match. Export AsyncAPI per provisioned application. Call set_step_status(step=\"event-portal\", ...) per the rule.",
      // Two-button CTA so the user can pick Auto (no per-layer prompts)
      // vs Interactive (default, safer for live infrastructure).
    },
    "event-portal": {
      nextLabel: "Blueprint",
      ctaLabel: "Start Blueprint →",
      agent: "SABlueprintAgent",
      kickoff: "Phase: blueprint\n\nAssemble the final blueprint package. Read all design/review/validation/event-portal artifacts. Compose blueprint/architecture.md + blueprint/runbook.md, write available Mermaid diagrams, render 5 audience packs (blueprint/executive/admin-ops/security/developers, both md+pdf), then assemble_zip to produce exports/engagement-package.zip. Call set_step_status(step=\"blueprint\", ...) per the rule.",
      // Server bundles the design artifacts inline + the deterministic section
      // outline so the agent composes without ~20 reads; `kickoff` is the fallback.
      kickoffUrl: eid => `/api/engagements/${encodeURIComponent(eid)}/blueprint/kickoff`,
      singleAction: true,
    },
  };

  // Resolve a transition's kickoff body. When the entry declares a `kickoffUrl`,
  // the server computes the kickoff (e.g. Validation injects deterministic
  // PRECOMPUTED CHECKS from the validation rules engine). Falls back to the
  // static `kickoff` if the call fails — e.g. a server that predates the
  // endpoint (404) or a transient error — so a handoff never dead-ends.
  async function resolveKickoffBody(cfg, eid) {
    if (cfg && cfg.kickoffUrl && eid) {
      try {
        const res = await fetch(cfg.kickoffUrl(eid));
        if (res.ok) {
          const j = await res.json();
          if (j && j.kickoff) return j.kickoff;
        }
      } catch (_) { /* fall through to the static fallback */ }
    }
    return cfg ? cfg.kickoff : "";
  }

  // localStorage dedup so the in-chat handoff card fires only once per
  // (engagement, phase) transition into DONE. Cleared when the phase status
  // moves AWAY from DONE (e.g. user clicked Restart), so a fresh completion
  // re-fires the card.
  function _phaseHintKey(eid) { return `sa.hint.phase_done.${eid}`; }
  function _readPhaseHintSet(eid) {
    if (!eid) return new Set();
    try { return new Set(JSON.parse(localStorage.getItem(_phaseHintKey(eid)) || "[]")); }
    catch { return new Set(); }
  }
  function _writePhaseHintSet(eid, set) {
    if (!eid) return;
    try { localStorage.setItem(_phaseHintKey(eid), JSON.stringify([...set])); } catch {}
  }
  function _markPhaseHintShown(eid, step) {
    const set = _readPhaseHintSet(eid);
    set.add(step);
    _writePhaseHintSet(eid, set);
  }
  function _clearPhaseHint(eid, step) {
    const set = _readPhaseHintSet(eid);
    if (set.delete(step)) _writePhaseHintSet(eid, set);
  }

  // Queue handoff cards seen via SSE tool_result so they render AFTER the
  // agent's final answer (not mid-stream). Drained from finalizeAgentBubble.
  let _pendingPhaseHandoffs = [];

  function _queuePhaseHandoffFromToolResult(d) {
    if (d?.tool_name !== "set_step_status") return;
    const result = d.result_data;
    const data = result?.data || result || {};
    const step = data.step;
    const status = data.status;
    if (!step || !status) return;
    if (status !== "DONE" && status !== "DONE_WITH_CONCERNS") return;
    _pendingPhaseHandoffs.push({ step, status });
  }

  function _drainPendingPhaseHandoffs() {
    while (_pendingPhaseHandoffs.length) {
      const { step, status } = _pendingPhaseHandoffs.shift();
      // Review completion always renders the findings card first; the
      // phase-handoff card (review → validation) only renders when
      // validation has a PHASE_NEXT entry (i.e. validation agent is wired).
      if (step === "review") {
        renderFindingsCard().catch(() => { /* best-effort */ });
      }
      renderPhaseHandoffCard(step, status);
    }
  }

  // Build the findings card shown after Review completes. Fetches the
  // engagement's findings via /api/engagements/<eid>/findings (only
  // status=pending — applied/deferred findings are excluded so the user
  // sees what still needs action). For each finding, render a row with
  // Apply / Defer / Discuss buttons; clicking dispatches a follow-up
  // chat message to SAOrchestratorAgent, which the orchestrator's
  // prompt handles via update_finding_status / peer dispatch.
  async function renderFindingsCard() {
    const eid = currentProjectId?.();
    if (!eid) return;
    // Dedup — if a findings card is already on screen this session,
    // skip. Re-renders can fire if the orchestrator calls
    // set_step_status(step="review") twice (e.g. after a Discuss round
    // that re-runs aggregation). Use a single card per session; pending
    // findings update naturally as the user clicks Apply/Defer.
    if (chatLog.querySelector(".findings-card")) return;
    let findings;
    try {
      findings = await fetch(`/api/engagements/${encodeURIComponent(eid)}/findings?status=pending`)
        .then(r => r.json());
    } catch { return; }
    if (!Array.isArray(findings) || !findings.length) {
      // Review produced no findings — render a tiny "all clear" card.
      const ok = document.createElement("div");
      ok.className = "chat-msg agent findings-card findings-empty";
      ok.innerHTML = `
        <div class="findings-header">✓ Review complete — no findings recorded.</div>
        <p class="muted">All four reviewer agents (architect / developer / ops / security) audited the design and found no issues to address.</p>`;
      chatLog.appendChild(ok);
      chatLog.scrollTop = chatLog.scrollHeight;
      return;
    }

    // Group by severity, then by source agent.
    const bySeverity = { critical: [], important: [], advisory: [] };
    for (const f of findings) {
      const sev = (f.severity || "advisory").toLowerCase();
      if (bySeverity[sev]) bySeverity[sev].push(f);
      else bySeverity.advisory.push(f);
    }

    const card = document.createElement("div");
    card.className = "chat-msg agent findings-card";
    const counts = `${bySeverity.critical.length} critical · ${bySeverity.important.length} important · ${bySeverity.advisory.length} advisory`;
    card.innerHTML = `
      <div class="findings-header">
        <span class="findings-icon">🔍</span>
        <span class="findings-title">Review findings</span>
        <span class="findings-counts">${escapeHtml(counts)}</span>
      </div>
      <p class="muted">For each finding, choose <strong>Apply</strong> (Domain fixes it), <strong>Defer</strong> (converts to an open-item), or <strong>Discuss</strong> (ask the source reviewer a question).</p>
      <div class="findings-list"></div>`;
    const list = card.querySelector(".findings-list");
    const renderGroup = (sev) => {
      const items = bySeverity[sev];
      if (!items.length) return;
      for (const f of items) {
        const row = document.createElement("div");
        row.className = `finding-row severity-${escapeHtml(sev)}`;
        row.dataset.findingId = f.id;
        row.innerHTML = `
          <div class="finding-header">
            <span class="finding-badge severity-${escapeHtml(sev)}">${escapeHtml(sev.toUpperCase())}</span>
            <span class="finding-id">${escapeHtml(f.id || "?")}</span>
            <span class="finding-source">${escapeHtml(f.source_agent || "")}</span>
          </div>
          <div class="finding-body">
            <div class="finding-desc">${escapeHtml(f.description || "")}</div>
            <div class="finding-affected"><strong>Affected:</strong> <code>${escapeHtml(f.affected_artifact || "")}</code></div>
            <div class="finding-rec"><strong>Recommendation:</strong> ${escapeHtml(f.recommendation || "")}</div>
          </div>
          <div class="finding-actions">
            <button type="button" class="cta-btn finding-apply" data-action="Apply">Apply</button>
            <button type="button" class="cta-btn cta-btn-secondary finding-defer" data-action="Defer">Defer</button>
            <button type="button" class="cta-btn cta-btn-secondary finding-discuss" data-action="Discuss">Discuss</button>
          </div>`;
        list.appendChild(row);
      }
    };
    renderGroup("critical");
    renderGroup("important");
    renderGroup("advisory");

    // Wire button clicks — each one dispatches a follow-up chat message
    // to SAOrchestratorAgent. The orchestrator's prompt knows how to
    // handle "Apply finding F<id>" / "Defer finding F<id>" / "Discuss
    // finding F<id>: <question>" inputs (Finding resolution protocol).
    card.querySelectorAll(".finding-row").forEach(row => {
      const fid = row.dataset.findingId;
      row.querySelectorAll("[data-action]").forEach(btn => {
        btn.addEventListener("click", () => {
          if (btn.disabled) return;
          const action = btn.dataset.action;
          // For Discuss, prompt the user for the question inline.
          let kickoff;
          if (action === "Discuss") {
            const q = window.prompt(
              `Discuss finding ${fid} — what's your question for the reviewer?`,
              ""
            );
            if (!q || !q.trim()) return;
            kickoff = `Discuss finding ${fid}: ${q.trim()}`;
          } else {
            kickoff = `${action} finding ${fid}`;
          }
          // Lock just this row's buttons so the user can act on other
          // findings while this one is in flight.
          row.querySelectorAll("[data-action]").forEach(b => b.disabled = true);
          row.classList.add("finding-row-pending");

          // Dispatch via the existing chat path; SAOrchestratorAgent is
          // already the current agent post-Review.
          applyChat("open");
          _selectChatAgent("SAOrchestratorAgent");
          const ci = document.getElementById("chat-input");
          if (ci) {
            ci.value = kickoff;
            chatForm?.requestSubmit?.();
          }
        });
      });
    });

    chatLog.appendChild(card);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // Render the explicit "phase complete → next action" card. Idempotent via
  // _readPhaseHintSet so calling it from both SSE and the lifecycle poller
  // doesn't double up.
  function renderPhaseHandoffCard(step, status) {
    const eid = currentProjectId();
    if (!eid) return;
    if (_readPhaseHintSet(eid).has(step)) return;
    const cfg = PHASE_NEXT[step];
    if (!cfg) return;
    _markPhaseHintShown(eid, step);

    const stepDisplay = step.charAt(0).toUpperCase() + step.slice(1);
    const statusPhrase = status === "DONE_WITH_CONCERNS"
      ? "complete (with concerns)" : "complete";

    const card = document.createElement("div");
    card.className = "chat-msg agent phase-handoff";
    // Honor intake-time execution_mode (auto | interactive) when the
    // phase supports both. Cached by the Overview render via
    // rememberExecutionMode; defaults to interactive when missing.
    const hasModeChoice = cfg.agent && cfg.kickoff && !cfg.singleAction;
    const prefersAutoHandoff = hasModeChoice && recallExecutionMode(eid) === "auto";
    const primaryLabel = prefersAutoHandoff
      ? cfg.ctaLabel.replace(/→\s*$/, "⚡").trim()
      : cfg.ctaLabel;
    const overrideLabel = prefersAutoHandoff
      ? "Confirm each decision instead"
      : "Run on auto instead ⚡";
    const bodyText = hasModeChoice
      ? (prefersAutoHandoff
          ? `Your intake set the pace to <strong>auto</strong>. <strong>${escapeHtml(primaryLabel)}</strong> takes the recommended option for each decision and runs to the end — every decision still surfaces in chat as it's made.`
          : `Your intake set the pace to <strong>interactive</strong>. <strong>${escapeHtml(primaryLabel)}</strong> walks you through every decision before it lands.`)
      : (cfg.agent && cfg.kickoff)
        ? `Ready to move forward? Click <strong>${escapeHtml(cfg.ctaLabel)}</strong> to begin.`
        : escapeHtml(cfg.pendingMessage || `Next phase (${cfg.nextLabel}) isn't wired up yet — check back soon.`);
    card.innerHTML = `
      <div class="phase-handoff-eyebrow">${escapeHtml(step)} → ${escapeHtml(cfg.nextLabel)}</div>
      <h3 class="phase-handoff-title">${escapeHtml(stepDisplay)} is ${statusPhrase}</h3>
      <p class="phase-handoff-body">${bodyText}</p>
      <div class="phase-handoff-actions">
        ${cfg.agent && !hasModeChoice
          ? `<button type="button" class="phase-handoff-cta" data-mode="interactive">${escapeHtml(cfg.ctaLabel)}</button>`
          : ""}
        ${hasModeChoice ? (prefersAutoHandoff
          ? `<button type="button" class="phase-handoff-cta phase-handoff-cta-auto" data-mode="auto" title="Auto mode (intake preference): take all recommended options; each decision still appears in chat as it's made.">${escapeHtml(primaryLabel)}</button>
             <button type="button" class="cta-mode-override" data-mode="interactive" title="Override to interactive — confirm each decision before it lands.">${escapeHtml(overrideLabel)}</button>`
          : `<button type="button" class="phase-handoff-cta" data-mode="interactive">${escapeHtml(primaryLabel)}</button>
             <button type="button" class="cta-mode-override" data-mode="auto" title="Override to auto — take recommended options without per-decision confirmation.">${escapeHtml(overrideLabel)}</button>`) : ""}
        <a class="phase-handoff-secondary" href="/projects/${encodeURIComponent(eid)}/artifacts">View artifacts</a>
      </div>
      <small class="phase-handoff-hint">To redo ${escapeHtml(stepDisplay)} from scratch, use <em>Restart ${escapeHtml(stepDisplay)}</em> on the Progress page (rare; only when requirements have materially changed).</small>
    `;

    // Bind both the primary phase-handoff-cta button AND the
    // cta-mode-override text-link button. Either firing dispatches the
    // matching mode; the disable-on-click guard then covers both
    // shapes so a fast double-tap can't fire interactive AND auto for
    // the same phase transition.
    card.querySelectorAll(".phase-handoff-cta, .cta-mode-override").forEach(btn => {
      btn.addEventListener("click", async () => {
        card.querySelectorAll(".phase-handoff-cta, .cta-mode-override").forEach(b => b.disabled = true);
        const mode = btn.dataset.mode || "interactive";
        btn.textContent = mode === "auto" ? "Starting Auto…" : `${cfg.ctaLabel.replace(/→$/,"").trim()}…`;
        applyChat("open");
        // Auto-select the next phase's agent (dropdown + persistent pick) so it
        // sticks across the agent re-poll and follow-ups route correctly.
        if (cfg.agent) _selectChatAgent(cfg.agent);
        // Auto mode arms the per-scope dispatch loop for the current
        // engagement; the loop chains scope-N+1 once scope-N marks done.
        if (mode === "auto") setAutoMode(currentProjectId?.(), true);
        // Design dispatch is owned by the orchestrator (the only design engine).
        // The Discovery→Design handoff MUST route through it — otherwise it would
        // send the static "begin with topic-design and walk the scopes" kickoff,
        // bypassing WORKER MODE + the orchestrator (the classic self-orchestration
        // that this whole engine replaced).
        if (cfg.agent === "SADomainAgent") {
          _startOrchestratedDesign(currentProjectId?.(), mode);
          return;
        }
        if (cfg.kickoff) {
          // Server-computed kickoff when the entry declares a kickoffUrl
          // (Validation injects deterministic PRECOMPUTED CHECKS); static fallback.
          const body = await resolveKickoffBody(cfg, currentProjectId?.());
          const ci = document.getElementById("chat-input");
          if (ci) {
            // Prepend "Mode: …" only when the target agent actually branches
            // on it (Discovery→Design, Validation→Event Portal). Review,
            // Validation, and Blueprint check for "Phase: X" on line 1 and
            // would misdetect their phase if Mode: were prepended.
            // `step` here is the SOURCE phase that just completed; the
            // helper keys on TARGET, so convert via PHASE_NEXT_STEP.
            ci.value = primeKickoff(PHASE_NEXT_STEP[step] || step, mode, body);
            ci.focus();
            chatForm.requestSubmit?.();
          }
        }
      });
    });

    chatLog.appendChild(card);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // Lightweight poller — fallback for cases where the in-chat SSE trigger
  // misses: agent updated status from a non-chat path, user reloaded the
  // page mid-turn, or the chat panel was closed when DONE fired. Also
  // catches the reverse transition (DONE → anything else, e.g. restart)
  // and clears the dedup flag so the next DONE re-fires the card.
  const _lastLifecycleStatuses = {};
  async function pollLifecycle() {
    const eid = currentProjectId();
    if (!eid) return;
    let lc;
    try {
      lc = await fetch(`/api/engagements/${encodeURIComponent(eid)}/lifecycle`).then(r => r.json());
    } catch (e) { return; }
    const steps = lc?.steps || {};
    const seenSteps = new Set();
    for (const [step, info] of Object.entries(steps)) {
      seenSteps.add(step);
      const status = info?.status || "NOT_STARTED";
      const key = `${eid}/${step}`;
      const prev = _lastLifecycleStatuses[key];
      _lastLifecycleStatuses[key] = status;
      const isDone = status === "DONE" || status === "DONE_WITH_CONCERNS";
      const wasDone = prev === "DONE" || prev === "DONE_WITH_CONCERNS";
      // Transition INTO DONE — render handoff card (idempotent via seen-set).
      if (prev !== undefined && !wasDone && isDone) {
        renderPhaseHandoffCard(step, status);
      }
      // Transition OUT of DONE — clear the dedup flag so the next DONE re-fires,
      // and also clear the sticky agent for this engagement so a fresh
      // restart re-binds the dropdown to the configured default.
      if (wasDone && !isDone) {
        _clearPhaseHint(eid, step);
        clearStickyAgent(eid);
      }
    }
    // If a step disappeared from the lifecycle file (e.g., restart cleared it
    // entirely), also clear the hint and sticky-agent so a fresh completion
    // re-fires and the next engagement opens on the configured default.
    for (const key of Object.keys(_lastLifecycleStatuses)) {
      if (!key.startsWith(`${eid}/`)) continue;
      const step = key.slice(eid.length + 1);
      if (!seenSteps.has(step) && _lastLifecycleStatuses[key]) {
        _clearPhaseHint(eid, step);
        clearStickyAgent(eid);
        delete _lastLifecycleStatuses[key];
      }
    }

    // Drift detector — chat says "complete" but lifecycle still in-progress.
    _detectDriftAndOfferMarkDone(eid, steps);
  }
  setInterval(pollLifecycle, 5000);

  // Phase order — drift detector picks the first non-terminal step as
  // the "active" phase whose chat-says-done claim we check against state.
  const _PHASE_ORDER = ["intake", "discovery", "design", "review",
                        "validation", "event-portal", "blueprint"];
  // Matches typical completion language an agent uses in its final
  // turn-text. Word-boundary anchored to avoid matching inside URLs or
  // tool args. Case-insensitive.
  const _COMPLETION_RE = /\b(complete|completed|done|finished|wrapped up|ready for review|ready for (?:the )?next phase|all set)\b/i;

  function _driftDedupKey(eid, step, msgHash) {
    return `sa.drift_offered.${eid}.${step}.${msgHash}`;
  }
  function _hashStr(s) {
    // Cheap, stable 32-bit hash so we don't re-offer on the same message.
    let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return Math.abs(h).toString(36);
  }

  function _detectDriftAndOfferMarkDone(eid, steps) {
    // Active phase = first non-terminal in canonical order.
    let activeStep = null;
    for (const id of _PHASE_ORDER) {
      const s = steps[id]?.status;
      if (s !== "DONE" && s !== "DONE_WITH_CONCERNS") { activeStep = id; break; }
    }
    if (!activeStep || activeStep === "intake") return;    // intake doesn't go through set_step_status
    // Need a recent agent message + completion language.
    const text = _lastFinalAgentText;
    if (!text || !_COMPLETION_RE.test(text)) return;
    // Wait at least 5s after the message so we don't trigger on
    // mid-stream language ("Discovery is almost complete, one more…").
    if (Date.now() - _lastFinalAgentTs < 5000) return;
    // Don't re-offer for the same (eid, step, message).
    const msgHash = _hashStr(text);
    const dedupKey = _driftDedupKey(eid, activeStep, msgHash);
    try { if (localStorage.getItem(dedupKey)) return; } catch {}
    try { localStorage.setItem(dedupKey, "1"); } catch {}
    _renderDriftBanner(eid, activeStep);
  }

  function _renderDriftBanner(eid, step) {
    if (!chatLog) return;
    // Skip if the banner is already in the chat log for this step
    // (the dedup key handles cross-poll; this handles the single-tick race).
    if (chatLog.querySelector(`.drift-banner[data-drift-step="${CSS.escape(step)}"]`)) return;
    const label = (_PHASE_LABELS && _PHASE_LABELS[step]) || step.replace(/-/g, " ");
    const wrap = document.createElement("div");
    wrap.className = "chat-msg agent drift-banner";
    wrap.setAttribute("data-drift-step", step);
    wrap.innerHTML = `
      <div class="drift-banner-eyebrow">PHASE STATUS DRIFT</div>
      <p>The agent's last message reads like ${escapeHtml(label)} is complete,
      but the lifecycle status hasn't advanced. The next-phase CTA won't
      appear until the lifecycle status moves.</p>
      <p>If you've verified the agent really did finish, you can advance
      manually. Otherwise dismiss this and let the agent continue.</p>
      <div class="drift-banner-actions">
        <button class="cta-btn drift-mark-done-btn"
                data-drift-step="${escapeHtml(step)}">Mark ${escapeHtml(label)} done →</button>
        <button class="cta-btn cta-btn-secondary drift-dismiss-btn">Dismiss</button>
      </div>`;
    chatLog.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;

    wrap.querySelector(".drift-dismiss-btn")?.addEventListener("click", () => wrap.remove());
    wrap.querySelector(".drift-mark-done-btn")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Marking…";
      try {
        const resp = await fetch(
          `/api/engagements/${encodeURIComponent(eid)}/lifecycle/${encodeURIComponent(step)}/mark-done`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({
              status: "DONE",
              note: `Manual override after drift detection at ${new Date().toISOString()}`,
            }),
          }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        // Replace banner with a confirmation line, then trigger render so
        // the next-phase CTA appears.
        wrap.innerHTML = `<div class="drift-banner-eyebrow">PHASE MARKED DONE</div>
          <p>${escapeHtml(label)} is now DONE in the lifecycle store. The
          next-phase CTA should appear momentarily.</p>`;
        if (typeof syncChatProjectContext === "function") syncChatProjectContext();
        if (typeof render === "function") render();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = orig;
        alert(`Mark-done failed: ${err.message}`);
      }
    });
  }

  // Empty-response card: rendered by finalizeAgentBubble when the agent
  // task ended with no actionable content (no text, no form card, no
  // markdown-fallback chips, no phase-handoff). The Continue button
  // submits a "continue" message routed to whichever agent is currently
  // selected in the dropdown — typically the same agent that just went
  // silent, so it picks up from where it stopped.
  function renderAgentEmptyCard() {
    const card = document.createElement("div");
    card.className = "chat-msg agent agent-empty";
    card.innerHTML = `
      <div class="agent-empty-eyebrow">No follow-up received</div>
      <p class="agent-empty-body">
        The agent finished this turn without asking the next question or
        signalling completion. Your last input was processed (decisions
        recorded, artifacts written if applicable), but the agent didn't
        chain to the next step.
      </p>
      <p class="agent-empty-body agent-empty-hint">
        Click <strong>Continue</strong> to nudge the agent forward, or
        type your own follow-up below.
      </p>
      <div class="agent-empty-actions">
        <button type="button" class="agent-empty-cta">Continue ↻</button>
      </div>
    `;
    card.querySelector(".agent-empty-cta").addEventListener("click", () => {
      const btn = card.querySelector(".agent-empty-cta");
      btn.disabled = true;
      btn.textContent = "Continuing…";
      const ci = document.getElementById("chat-input");
      if (ci) {
        ci.value = "Continue — please proceed with the next step.";
        chatForm.requestSubmit?.();
      }
    });
    chatLog.appendChild(card);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // Layer A: paint the placeholder + animated dots as soon as the user submits,
  // before any SSE event arrives. The dots are removed when first text streams in
  // (or, failing that, in finalizeAgentBubble).
  function openThinkingBubble() {
    if (pendingAgentMsg) return;
    setActivityBar("Thinking…");
    _stampSse();  // fresh turn → reset the silence timer baseline
    chatLog.querySelector(".chat-empty")?.remove();
    chatLog.querySelector(".welcome-card")?.remove();
    const wrap = document.createElement("div");
    wrap.className = "chat-msg agent agent-thinking agent-turn";
    const pillsContainer = document.createElement("div");
    pillsContainer.className = "activity-pills";
    const dots = document.createElement("div");
    dots.className = "agent-thinking-dots";
    dots.innerHTML = "<span></span><span></span><span></span>";
    const bubble = document.createElement("div");
    bubble.className = "agent-turn-text";
    wrap.appendChild(pillsContainer);
    wrap.appendChild(dots);
    wrap.appendChild(bubble);
    chatLog.appendChild(wrap);
    pendingAgentMsg = {
      el: wrap, lastText: "", pillsContainer, bubbleEl: bubble,
      dotsEl: dots, pills: [], pillByCallId: new Map(),
      msgId: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    };
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function startOrUpdateAgentBubble(text) {
    if (!text) return;
    chatLog.querySelector(".chat-empty")?.remove();
    chatLog.querySelector(".welcome-card")?.remove();
    const display = maskQuestionBlockDuringStream(text);
    const isPill = isStatusPill(text);

    if (!pendingAgentMsg) {
      // Fallback path — SSE event arrived without a prior submit (reconnect, etc).
      const wrap = document.createElement("div");
      wrap.className = "chat-msg agent agent-thinking agent-turn";
      const pillsContainer = document.createElement("div");
      pillsContainer.className = "activity-pills";
      const bubble = document.createElement("div");
      bubble.className = "agent-turn-text";
      wrap.appendChild(pillsContainer);
      wrap.appendChild(bubble);
      chatLog.appendChild(wrap);
      pendingAgentMsg = {
        el: wrap, lastText: text, pillsContainer, bubbleEl: bubble,
        dotsEl: null, pills: [], pillByCallId: new Map(),
        msgId: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      };
      if (isPill) {
        appendActivityPill(text);
      } else {
        renderAgentMarkdown(bubble, display);
      }
    } else if (text !== pendingAgentMsg.lastText) {
      // First real text — kill the thinking dots.
      if (pendingAgentMsg.dotsEl) {
        pendingAgentMsg.dotsEl.remove();
        pendingAgentMsg.dotsEl = null;
      }
      pendingAgentMsg.lastText = text;
      if (isPill) {
        const last = pendingAgentMsg.pills[pendingAgentMsg.pills.length - 1];
        if (!last || last.text !== text) appendActivityPill(text);
      } else {
        renderAgentMarkdown(pendingAgentMsg.bubbleEl, display);
      }
    }
    // Persist the in-flight bubble's current text so a page refresh
    // mid-stream still recovers what was on screen. Status-pill text
    // is skipped — pills are transient activity markers, not the
    // agent's reply.
    if (!isPill && pendingAgentMsg?.msgId) {
      _schedulePersistStreamingAgent(pendingAgentMsg.msgId, text);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  // Extract ```question { ... } ``` blocks from an agent message; return the
  // text with those blocks stripped, plus the parsed schemas. See
  // solace_architect_core.tools.interaction_tools.ask_user_question — the
  // agent echoes that tool's schema as a fenced block, the frontend renders
  // it as an interactive form card.
  function parseQuestionBlocks(text) {
    if (!text || text.indexOf("```question") === -1) {
      return { cleanText: text, blocks: [] };
    }
    const re = /```question\s*\n([\s\S]*?)\n```/g;
    const blocks = [];
    let cleanText = text;
    let m;
    while ((m = re.exec(text)) !== null) {
      try {
        const schema = JSON.parse(m[1]);
        if (schema && typeof schema === "object" && schema.id && schema.kind) {
          blocks.push(schema);
          cleanText = cleanText.replace(m[0], "").trim();
        }
      } catch (err) {
        // Malformed JSON inside the block — leave it visible so the user sees the error.
      }
    }
    return { cleanText, blocks };
  }

  // Extract ```switch_agent { "to_agent": ..., "reason": ... } ``` blocks.
  // Emitted deterministically by SAOrchestratorAgent's
  // _peer_agent_switch_hint patch on the 2nd+ delegation to the same peer
  // in a session — the chip lets the user one-click switch the chat
  // dropdown to that peer so follow-ups skip the orchestrator hop.
  function parseSwitchAgentBlocks(text) {
    if (!text || text.indexOf("```switch_agent") === -1) {
      return { cleanText: text, suggestions: [] };
    }
    const re = /```switch_agent\s*\n([\s\S]*?)\n```/g;
    const suggestions = [];
    let cleanText = text;
    let m;
    while ((m = re.exec(text)) !== null) {
      try {
        const payload = JSON.parse(m[1]);
        if (payload && typeof payload === "object" && payload.to_agent) {
          suggestions.push(payload);
          cleanText = cleanText.replace(m[0], "").trim();
        }
      } catch (err) {
        // Malformed JSON — strip the block anyway so we don't leak raw
        // JSON into the chat. The orchestrator produces this server-side
        // so any malformation is our bug, not the user's.
        cleanText = cleanText.replace(m[0], "").trim();
      }
    }
    return { cleanText, suggestions };
  }

  // Per-session dismissal storage. We don't want the chip to re-appear
  // after the user dismissed it for this target THIS session — they're
  // telling us they prefer staying on the orchestrator for now. A new
  // browser session (next day, new tab) resets, so the suggestion can
  // surface again if the iteration pattern recurs.
  const _SWITCH_DISMISS_KEY = "sa.switch_agent_dismissed";
  function _getDismissedSwitchTargets() {
    try {
      const raw = sessionStorage.getItem(_SWITCH_DISMISS_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  }
  function _addDismissedSwitchTarget(target) {
    try {
      const cur = _getDismissedSwitchTargets();
      if (!cur.includes(target)) cur.push(target);
      sessionStorage.setItem(_SWITCH_DISMISS_KEY, JSON.stringify(cur));
    } catch { /* private mode — accept loss of dismissal across reload */ }
  }

  // Render a single switch-agent suggestion as a clickable chip-row.
  // Two actions: "Switch to <agent>" (re-targets the chat dropdown,
  // persists via _setUserPickedAgent) and "Dismiss" (sessionStorage).
  function renderSwitchAgentChip(suggestion) {
    const card = document.createElement("div");
    card.className = "chat-msg agent switch-agent-card";
    card.dataset.toAgent = suggestion.to_agent;

    const body = document.createElement("div");
    body.className = "switch-agent-body";
    const icon = document.createElement("span");
    icon.className = "switch-agent-icon";
    icon.textContent = "💡";
    const text = document.createElement("span");
    text.className = "switch-agent-text";
    text.textContent = suggestion.reason || `Switch to ${suggestion.to_agent} for faster follow-ups.`;
    body.appendChild(icon);
    body.appendChild(text);

    const actions = document.createElement("div");
    actions.className = "switch-agent-actions";
    const switchBtn = document.createElement("button");
    switchBtn.className = "switch-agent-btn primary";
    switchBtn.type = "button";
    switchBtn.textContent = `Switch to ${suggestion.to_agent} →`;
    switchBtn.addEventListener("click", () => {
      const select = document.getElementById("chat-agent-select");
      if (!select) return;
      // Verify the target is in the dropdown's option list before flipping —
      // protects against a stale suggestion when the peer has dropped off
      // the mesh between emission and click.
      const options = Array.from(select.options).map(o => o.value);
      if (!options.includes(suggestion.to_agent)) {
        switchBtn.textContent = `${suggestion.to_agent} unavailable`;
        switchBtn.disabled = true;
        return;
      }
      _setUserPickedAgent(suggestion.to_agent);
      select.value = suggestion.to_agent;
      // Fire `change` so the existing dropdown handler refreshes the
      // placeholder and tooltip — we DON'T want it to re-call
      // _setUserPickedAgent (we already did above for clarity), but the
      // handler's clear-on-default logic is a no-op when the target isn't
      // PREFERRED_DEFAULT_AGENT, so dispatching is safe.
      select.dispatchEvent(new Event("change", { bubbles: true }));
      // Collapse the chip into a "switched" confirmation so the user has
      // visible feedback. Subsequent suggestions for the same target are
      // suppressed by the dismissal check, but this card stays visible.
      card.innerHTML = "";
      const done = document.createElement("div");
      done.className = "switch-agent-done";
      done.textContent = `✓ Switched chat to ${suggestion.to_agent}.`;
      card.appendChild(done);
    });
    const dismissBtn = document.createElement("button");
    dismissBtn.className = "switch-agent-btn secondary";
    dismissBtn.type = "button";
    dismissBtn.textContent = "Dismiss";
    dismissBtn.addEventListener("click", () => {
      _addDismissedSwitchTarget(suggestion.to_agent);
      card.remove();
    });
    actions.appendChild(switchBtn);
    actions.appendChild(dismissBtn);

    card.appendChild(body);
    card.appendChild(actions);
    return card;
  }

  // Latest finalized agent message — tracked for the drift detector below.
  // When a phase's lifecycle status hasn't advanced but the agent's last
  // message used completion language, the detector surfaces a "Mark
  // <phase> done" banner so the user isn't stranded.
  let _lastFinalAgentText = "";
  let _lastFinalAgentTs = 0;

  // Strip internal "still working" status mirror from an agent's chat text.
  // Agents mirror their lifecycle status into prose ("Completion Status:
  // NEEDS_CONTEXT — <scope> in progress") and narrate interim chunk writes —
  // but NEEDS_CONTEXT is an internal "I'll continue next turn" signal that
  // already drives the UI via the lifecycle API. Surfacing it in chat leaks
  // orchestration and breaks the seamless feel. We only strip the interim
  // (NEEDS_CONTEXT) status + obvious "continuing next turn" chatter; terminal
  // statuses (DONE / DONE_WITH_CONCERNS / BLOCKED) are user-meaningful and stay.
  function _stripInterimStatusNoise(text) {
    if (!text) return text;
    let out = text;
    // "Completion Status: NEEDS_CONTEXT — …" (with optional heading/bold/em).
    out = out.replace(
      /^[ \t]*#{0,6}[ \t]*\*{0,2}[ \t]*Completion Status:?[ \t]*\*{0,2}[ \t]*[—:\-]?[ \t]*NEEDS_CONTEXT\b.*$/gim,
      "",
    );
    // "<file>.md: first chunk written, continuing next turn." / "section N
    // appended, continuing…" — pure interim progress chatter.
    out = out.replace(
      /^[ \t]*\*{0,2}[^\n]*\b(?:chunk|section|file|part)\b[^\n]*\b(?:written|appended|saved)\b[^\n]*\bcontinu(?:e|ing)\b[^\n]*$/gim,
      "",
    );
    // Collapse blank lines left behind by the removals.
    return out.replace(/\n{3,}/g, "\n\n").trim();
  }

  function finalizeAgentBubble(finalText) {
    const text = (finalText || pendingAgentMsg?.lastText || "").trim();
    if (text) { _lastFinalAgentText = text; _lastFinalAgentTs = Date.now(); }
    // Parse question blocks first, THEN switch_agent blocks from the
    // remaining text. Order matters because a single agent message can
    // (rarely) carry both — they're independent sidecars.
    const qResult = parseQuestionBlocks(text);
    const sResult = parseSwitchAgentBlocks(qResult.cleanText);
    let cleanText = sResult.cleanText;
    const blocks = qResult.blocks;
    // Tool-result fallback: when the agent called ask_user_question but
    // its text echo was missing or truncated (the schema only lives in
    // the tool call args at that point), splice the tool-result schemas
    // in so the form still renders. Dedup by id — text wins, tool fills
    // the gap. Without this, an agent whose final 6 bytes of text are
    // `"}` + closing fence (observed 2026-05-23) shows the user trash
    // text and no actionable form card.
    const _toolSchemas = (pendingAgentMsg?.toolEmittedSchemas) || [];
    let _usedToolFallback = false;
    if (_toolSchemas.length) {
      const knownIds = new Set(blocks.map(b => b.id));
      for (const ts of _toolSchemas) {
        if (!knownIds.has(ts.id)) {
          blocks.push(ts);
          knownIds.add(ts.id);
          _usedToolFallback = true;
          console.debug(
            "[question-fallback] using tool-emitted schema for id=%s (no text echo found)",
            ts.id,
          );
        }
      }
    }
    // When the fallback fired, the agent's text usually contains trailing
    // fence-tail residue from an aborted echo attempt (e.g. `"}\n````).
    // parseQuestionBlocks didn't strip it because the opening ```question
    // never made it into the stream. Detect a SHORT trailing tail that
    // looks like JSON+fence epilogue and drop it before rendering.
    if (_usedToolFallback && cleanText) {
      const tail = cleanText.replace(/\s+$/, "");
      // Match: optional leading prose + trailing run of [", }, whitespace]
      // followed by an isolated ``` (the closing fence of a truncated block).
      // Conservative: only strip when the residue is <= 40 chars; longer
      // text is probably real prose we want to preserve.
      const m = tail.match(/^([\s\S]*?)([\s"\\}\n]{0,30}\n?\s*```\s*)$/);
      if (m && m[2].length <= 40) {
        cleanText = m[1].trim();
      }
    }
    // Drop internal "still working" status chatter so interim chunk turns read
    // as seamless activity (the lifecycle API, not this prose, drives the UI).
    // Track when stripping emptied an otherwise status-only turn so we don't
    // mistake a mid-deliverable pause for an "agent finished, nothing to show"
    // dead-end and render the empty/Continue card over it.
    const _preStripText = cleanText;
    cleanText = _stripInterimStatusNoise(cleanText);
    const _strippedInterimOnly = !!_preStripText && !cleanText;
    // Filter out suggestions the user has already dismissed this session.
    const dismissed = _getDismissedSwitchTargets();
    const switchSuggestions = sResult.suggestions.filter(s =>
      !dismissed.includes(s.to_agent)
    );

    if (pendingAgentMsg) {
      pendingAgentMsg.el.classList.remove("agent-thinking");
      if (pendingAgentMsg.dotsEl) {
        pendingAgentMsg.dotsEl.remove();
        pendingAgentMsg.dotsEl = null;
      }
      // Lock all pills as done (last one still in-progress at this point).
      const lastPill = pendingAgentMsg.pills[pendingAgentMsg.pills.length - 1];
      if (lastPill) {
        lastPill.el.classList.remove("in-progress");
        lastPill.el.classList.add("done");
        const icon = lastPill.el.querySelector(".activity-pill-icon");
        if (icon) icon.textContent = "✓";
      }
      // Collapse the pills container to a one-liner summary if there
      // were any — keeps the chat tidy after the turn finishes.
      if (pendingAgentMsg.pills.length) {
        const n = pendingAgentMsg.pills.length;
        // Capture by reference — pendingAgentMsg is set to null below, so
        // the click handler can't read it later.
        const pillsContainerRef = pendingAgentMsg.pillsContainer;
        const summary = document.createElement("div");
        summary.className = "activity-pills-summary";
        summary.innerHTML = `<span class="activity-pill-icon">✓</span><span>${n} step${n === 1 ? "" : "s"} (click to expand)</span>`;
        summary.addEventListener("click", () => {
          pillsContainerRef.classList.toggle("expanded");
          summary.classList.toggle("expanded");
        });
        pillsContainerRef.classList.add("collapsed");
        pillsContainerRef.parentNode.insertBefore(summary, pillsContainerRef);
      }
      // Render the final answer in the bubble (or remove the whole turn
      // if there's nothing left to show after stripping question blocks).
      if (cleanText) {
        renderAgentMarkdown(pendingAgentMsg.bubbleEl, cleanText);
      } else if (!pendingAgentMsg.pills.length) {
        pendingAgentMsg.el.remove();
      } else {
        pendingAgentMsg.bubbleEl.remove();
      }
      pendingAgentMsg = null;
    } else if (cleanText) {
      // No bubble was opened (no status updates seen) — render the final reply.
      appendChatMessage("agent", cleanText);
    }

    // Render each question schema as an interactive form card after the text.
    for (const schema of blocks) {
      const card = renderQuestionCard(schema);
      chatLog.appendChild(card);
    }
    if (blocks.length) chatLog.scrollTop = chatLog.scrollHeight;

    // Render switch-agent suggestion chips after question cards (a chip
    // is non-blocking; the question card is the user's primary action).
    for (const sugg of switchSuggestions) {
      const chip = renderSwitchAgentChip(sugg);
      chatLog.appendChild(chip);
    }
    if (switchSuggestions.length) chatLog.scrollTop = chatLog.scrollHeight;

    // Safety net: if the agent emitted a markdown-style multiple-choice
    // question instead of a ```question block (LLM sometimes ignores
    // the tool-call rule), try two pattern detectors and offer a
    // clickable chip row + optional note. The user gets the same
    // form-like UX without typing the answer in chat.
    //   1) detectReplyPattern: "Reply: A, B, C" letter-list footers.
    //   2) detectOptionsPattern: "**Option N (Recommended): Title**"
    //      headers + "Which option do you prefer?" tail. Catches the
    //      Domain agent's design-decision shape.
    let renderedChips = false;
    if (!blocks.length && cleanText) {
      const detected = detectReplyPattern(cleanText) || detectOptionsPattern(cleanText);
      if (detected) {
        const chips = renderQuickReplyChips(detected);
        chatLog.appendChild(chips);
        chatLog.scrollTop = chatLog.scrollHeight;
        renderedChips = true;
      }
    }

    // Empty-response handling: when the agent finishes without giving
    // the user anything actionable (no text body, no form card, no
    // quick-reply chips, no phase-handoff queued), render a small
    // "agent finished without a follow-up" card with a Continue button.
    // Without this, the user sees a stuck thinking-dots placeholder
    // and has no signal that the turn ended. Symptom we hit: Domain
    // recorded the user's decision then stopped emitting tool calls,
    // leaving the chat in apparent limbo.
    const producedActionable = cleanText || blocks.length || renderedChips || switchSuggestions.length || _pendingPhaseHandoffs.length;
    // _strippedInterimOnly: the turn's only text was the internal "still working"
    // status mirror we just removed — the agent is mid-deliverable and will
    // continue (auto-advance dispatches; the activity pills show work happened),
    // so it's NOT a stuck dead-end. Suppress the empty/Continue card.
    if (!producedActionable && !_strippedInterimOnly) {
      renderAgentEmptyCard();
    }

    // Persist the final text to history (forms are not persisted — on reload
    // the user sees the cleanText only, which is intentional: the form is
    // single-use; the answer they gave appears as their own message).
    //
    // If the streaming-persist path was active (pendingAgentMsg had a
    // stable msgId), REPLACE that in-flight entry with the cleaned final
    // — don't append a duplicate. Cancel any pending debounced save so
    // we don't immediately overwrite the final with stale streaming text.
    if (text && chatSessionId) {
      _flushStreamingPersist();
      // Drop the trailing debounce — we're about to overwrite anyway.
      _streamingPersistPending = null;
      if (_streamingPersistTimer) {
        clearTimeout(_streamingPersistTimer);
        _streamingPersistTimer = null;
      }
      const log = loadChatHistory(chatSessionId);
      const finalEntry = {
        role: "agent",
        text: cleanText || "[question card]",
        ts: Date.now(),
      };
      const idx = (pendingAgentMsg?.msgId)
        ? log.findIndex(m => m.msgId === pendingAgentMsg.msgId)
        : -1;
      if (idx >= 0) log[idx] = finalEntry;
      else log.push(finalEntry);
      saveChatHistory(chatSessionId, log);
      updateLoadHistoryButton?.();
    }

    // Render any phase-handoff cards queued from set_step_status tool_result
    // events this turn. Deferred to here so they sit AFTER the agent's final
    // text instead of interrupting the stream.
    _drainPendingPhaseHandoffs();

    // Turn is done — hide the sticky activity bar until the next turn opens.
    setActivityBar(null);

    // Re-render the current page if we're on Progress / Overview so the
    // CTA reflects the latest lifecycle status — flips Start Discovery →
    // Continue in chat the moment the agent's first set_step_status lands,
    // closing the "button stays clickable after I clicked it" window.
    try {
      const view = (typeof currentView === "function") ? currentView() : "";
      if (view === "overview" || view === "progress") {
        if (typeof render === "function") render();
      }
    } catch { /* swallow — re-render is best-effort */ }

    // Design dispatch after a turn: the server-side orchestrator decides the
    // next scope and the FE just executes — gated by _orchRunning + the
    // SADomainAgent responder so this only fires during an active Design run.
    // (The classic auto-advance state machine was removed 2026-05-28.)
    const _advEid = currentProjectId?.();
    if (_advEid && _orchRunning && _lastRespondingAgent === "SADomainAgent") {
      _orchestratedAdvance().catch(() => { /* best-effort */ });
    }
  }

  // Normalize the question-card counter. The agent sometimes emits
  // self-defeating values like "Q1 of ~1 for topic-design" — the
  // "of ~1" carries no information (it claims there's exactly one
  // question while we're on it). Detect and trim such patterns; if
  // nothing meaningful remains, return null so the counter is omitted.
  function sanitizeCounter(s) {
    if (!s || typeof s !== "string") return null;
    let t = s.trim();
    if (!t) return null;
    // Strip "of ~0" / "of ~1" / "of 0" / "of 1" — meaningless totals.
    t = t.replace(/\s+of\s+~?\s*[01]\b/i, "").trim();
    // Strip "of ~<m>" when current >= m (e.g., "Q3 of ~2"). Likely an
    // LLM estimation error; better to show just the current index.
    t = t.replace(/Q(\d+)\s+of\s+~?\s*(\d+)/i, (m, cur, tot) =>
      parseInt(cur, 10) >= parseInt(tot, 10) ? `Q${cur}` : m);
    return t || null;
  }

  // Build an interactive form card for one question schema. Submits the
  // user's answer via the same /api/chat/message endpoint as plain text,
  // but with a `data` payload (DataPart) so the agent receives a
  // machine-readable reply.
  function renderQuestionCard(schema) {
    const card = document.createElement("div");
    card.className = `chat-msg agent question-card severity-${schema.severity || "blocking"}`;
    card.dataset.questionId = schema.id;

    // Header: severity badge + optional counter
    const header = document.createElement("div");
    header.className = "question-header";
    const badge = document.createElement("span");
    badge.className = `question-badge ${schema.severity || "blocking"}`;
    badge.textContent = (schema.severity || "blocking").toUpperCase();
    header.appendChild(badge);
    const counterText = sanitizeCounter(schema.counter);
    if (counterText) {
      const counter = document.createElement("span");
      counter.className = "question-counter";
      counter.textContent = counterText;
      header.appendChild(counter);
    }
    card.appendChild(header);

    // Question
    const qEl = document.createElement("div");
    qEl.className = "question-text";
    qEl.textContent = schema.question;
    card.appendChild(qEl);

    // Context (1-2 sentence "why this matters")
    if (schema.context) {
      const ctx = document.createElement("div");
      ctx.className = "question-context";
      ctx.textContent = schema.context;
      card.appendChild(ctx);
    }

    // Recommended callout (single_choice only)
    if (schema.recommended && schema.kind === "single_choice") {
      const rec = (schema.options || []).find(o => o.id === schema.recommended);
      if (rec) {
        const callout = document.createElement("div");
        callout.className = "question-recommended";
        callout.innerHTML = `<strong>★ Recommended:</strong> ${esc(rec.label)}`;
        card.appendChild(callout);
      }
    }

    // Widget per kind
    const form = document.createElement("form");
    form.className = "question-form";
    let getAnswer = () => null;

    // getNote() returns the user-typed caveat string (or null). Defaulted
    // here; renderNoteSection() (below) sets it for kinds that include a
    // note toggle. The note is sent on the DataPart reply alongside the
    // structured answer so the agent can capture caveats verbatim.
    let getNote = () => null;

    if (schema.kind === "yes_no") {
      const wrap = document.createElement("div");
      wrap.className = "question-yesno";
      ["yes", "no"].forEach(v => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "question-yesno-btn";
        btn.dataset.value = v;
        btn.textContent = v === "yes" ? "Yes" : "No";
        btn.addEventListener("click", () => {
          const note = getNote();
          const display = note ? `${btn.textContent} — ${note}` : btn.textContent;
          submitAnswer(schema, v, display, card, note);
        });
        wrap.appendChild(btn);
      });
      form.appendChild(wrap);
    } else if (schema.kind === "single_choice") {
      // Pre-select the recommended option (or the first option if none
      // is recommended). Pre-selecting *something* is better than leaving
      // the form un-submittable, but using the recommended id means a
      // Submit-without-change matches the agent's recommendation rather
      // than always option A.
      const defaultId = schema.recommended || (schema.options?.[0]?.id ?? null);
      (schema.options || []).forEach(opt => {
        const row = document.createElement("label");
        row.className = "question-opt-row";
        if (opt.id === schema.recommended) row.classList.add("recommended");
        const checked = opt.id === defaultId ? "checked" : "";
        row.innerHTML = `
          <input type="radio" name="opt-${schema.id}" value="${esc(opt.id)}" ${checked}>
          <div class="question-opt-body">
            <div class="question-opt-label">${opt.id === schema.recommended ? "★ " : ""}<strong>${esc(opt.label)}</strong></div>
            ${opt.pros ? `<div class="question-opt-pros"><em>Pros:</em> ${esc(opt.pros)}</div>` : ""}
            ${opt.cons ? `<div class="question-opt-cons"><em>Cons:</em> ${esc(opt.cons)}</div>` : ""}
          </div>`;
        form.appendChild(row);
      });
      getAnswer = () => {
        const checked = form.querySelector(`input[name="opt-${schema.id}"]:checked`);
        if (!checked) return null;
        const opt = (schema.options || []).find(o => o.id === checked.value);
        return { id: checked.value, label: opt ? opt.label : checked.value };
      };
    } else if (schema.kind === "multi_choice") {
      (schema.options || []).forEach(opt => {
        const row = document.createElement("label");
        row.className = "question-opt-row";
        row.innerHTML = `
          <input type="checkbox" name="opt-${schema.id}" value="${esc(opt.id)}">
          <div class="question-opt-body"><strong>${esc(opt.label)}</strong></div>`;
        form.appendChild(row);
      });
      getAnswer = () => {
        const checked = Array.from(form.querySelectorAll(`input[name="opt-${schema.id}"]:checked`));
        if (!checked.length) return null;
        const ids = checked.map(c => c.value);
        const labels = ids.map(id => {
          const opt = (schema.options || []).find(o => o.id === id);
          return opt ? opt.label : id;
        });
        return { ids, labels };
      };
    } else if (schema.kind === "free_text") {
      const input = document.createElement("textarea");
      input.className = "question-free-input";
      input.rows = 3;
      if (schema.placeholder) input.placeholder = schema.placeholder;
      form.appendChild(input);
      if (schema.example) {
        const ex = document.createElement("div");
        ex.className = "question-example";
        ex.innerHTML = `<em>Example:</em> <code>${esc(schema.example)}</code>`;
        form.appendChild(ex);
      }
      getAnswer = () => {
        const v = input.value.trim();
        return v ? { text: v } : null;
      };
    }

    // Optional note ("+ Add a note") — applies to all kinds except
    // free_text (where the input itself is already a textarea, so a
    // second note field would be redundant). Hidden behind a toggle so
    // the card stays uncluttered for the common case where the user
    // just picks an option.
    if (schema.kind !== "free_text") {
      getNote = renderNoteSection(form);
    }

    // Submit row (free_text + radio/checkbox need an explicit submit;
    // yes_no submits on click).
    if (schema.kind !== "yes_no") {
      const submitRow = document.createElement("div");
      submitRow.className = "question-submit-row";
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.className = "cta-btn question-submit";
      submit.textContent = "Submit answer";
      submitRow.appendChild(submit);
      form.appendChild(submitRow);
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const answer = getAnswer();
        if (answer === null) return;  // nothing selected
        const note = getNote();
        const baseDisplay = formatAnswerForDisplay(schema, answer);
        const display = note ? `${baseDisplay} — ${note}` : baseDisplay;
        submitAnswer(schema, answer, display, card, note);
      });
    }

    card.appendChild(form);

    // No "type a custom answer" escape hatch — "+ Add a note" already
    // covers the elaboration case (pick the closest option + qualify
    // it), and the chat input below is always available for truly
    // off-script replies. The link was a footgun (no undo on a stray
    // click) and added a redundant code path.

    return card;
  }

  // Detect a "Reply: A, B, C" / "Please reply: A, B, or C" / etc footer
  // in an agent markdown message. Returns either an array of letter
  // labels (single_choice) or {kind:"yes_no"}, or null if no such
  // pattern is found.
  //
  // Why: SADiscoveryAgent sometimes emits a structured question as
  // markdown instead of calling ask_user_question. The chip row gives
  // users a click-not-type affordance regardless of which path the LLM
  // chose.
  // Second safety net for the form-fallback path. The Domain agent
  // sometimes emits a structured question as markdown with bold
  // "**Option 1 (Recommended): Title**" / "**Option 2: Title**" headers
  // and a "Which option do you prefer?" tail. detectReplyPattern's
  // letter-list logic doesn't catch this — the labels are full prose,
  // not single letters. detectOptionsPattern picks up the option
  // headers and produces a richer chip payload with the labels intact.
  function detectOptionsPattern(text) {
    if (!text) return null;
    // Match an option header at line start:
    //   "**Option 1 (Recommended): Title**"
    //   "**Option 2: Title**"
    //   "Option 3: Title"
    //   "**Option 4 — Title**"   (em dash, no parenthetical)
    // The label captures the first prose line; pros/cons / bullets are
    // on subsequent lines and not part of the header.
    const re = /^\s*(?:\*\*)?\s*Option\s+(\d+)(?:\s*[\(—–\-:]\s*([^\)\n*]+?)\s*\)?)?\s*[:—–\-]?\s*([^\*\n]*?)\s*(?:\*\*)?\s*$/gim;
    const opts = [];
    let m;
    while ((m = re.exec(text)) !== null) {
      const num = m[1];
      const tag = (m[2] || "").trim();   // could be "Recommended", or empty
      const tail = (m[3] || "").trim();  // could be the label or empty
      // Heuristic: if tag is non-empty AND not "Recommended"-ish, treat as label
      const isRecTag = /^recommended$|^recommend/i.test(tag);
      const label = tail || (isRecTag ? "" : tag);
      if (!label) continue;
      opts.push({
        id: `option-${num}`,
        num,
        label,
        recommended: isRecTag,
      });
    }
    if (opts.length < 2) return null;

    // Confirm with a question phrase in the tail — guards against false
    // positives where "Option N:" appears in prose without a real ask.
    const tail = text.slice(-500).toLowerCase();
    const hasAsk = /which option|do you prefer|what.?s your preference|please (?:choose|select|pick)|your pick/i.test(tail);
    if (!hasAsk) return null;

    return { kind: "options", options: opts };
  }

  function detectReplyPattern(text) {
    // Look only at the tail of the message — the "Reply:" prompt is
    // always near the end. Limits false positives where the body
    // happens to mention "reply" in unrelated context.
    const tail = text.slice(-500);

    // Word "reply" anywhere (case-insensitive, word-bounded — catches
    // "Reply:", "Please reply:", "**Reply:**", "(Reply A/B/C)", etc.)
    // followed (within the same sentence) by a list of single
    // uppercase letters or yes/no tokens.
    const replyRe = /\b[Rr]eply\b[^.!?\n]{0,80}/g;
    const yesNoRe = /\byes\b[^.!?\n]{0,40}\bno\b|\bno\b[^.!?\n]{0,40}\byes\b/i;
    // letter list — 2-6 single-cap letters separated by , / or whitespace
    const letterListRe = /\b([A-Z])(?:[\s,/]+(?:or\s+)?([A-Z]))(?:[\s,/]+(?:or\s+)?([A-Z]))?(?:[\s,/]+(?:or\s+)?([A-Z]))?(?:[\s,/]+(?:or\s+)?([A-Z]))?(?:[\s,/]+(?:or\s+)?([A-Z]))?\b/;

    let match;
    while ((match = replyRe.exec(tail)) !== null) {
      const span = match[0];

      // yes/no test inside the span
      if (yesNoRe.test(span)) {
        return { kind: "yes_no" };
      }

      // letter list inside the span
      const ll = span.match(letterListRe);
      if (ll) {
        const letters = ll.slice(1).filter(Boolean);
        // De-dup while preserving order
        const seen = new Set();
        const unique = letters.filter(l => (seen.has(l) ? false : (seen.add(l), true)));
        if (unique.length >= 2 && unique.length <= 6) {
          return { kind: "single_choice", letters: unique };
        }
      }
    }
    return null;
  }

  // Render a quick-reply chip row appended after a markdown agent
  // message. Click = submit (chip behaves like yes_no buttons —
  // immediate, with the note included if filled).
  function renderQuickReplyChips(detected) {
    const { kind } = detected;
    const card = document.createElement("div");
    card.className = "chat-msg agent quick-reply-chips";

    const labelEl = document.createElement("div");
    labelEl.className = "quick-reply-label";
    labelEl.textContent = "Quick reply:";
    card.appendChild(labelEl);

    const row = document.createElement("div");
    row.className = "quick-reply-row";

    // Build a list of { value, displayLabel, recommended? } tuples.
    let chips = [];
    if (kind === "yes_no") {
      chips = [
        { value: "yes", displayLabel: "Yes" },
        { value: "no",  displayLabel: "No"  },
      ];
    } else if (kind === "options") {
      chips = detected.options.map(o => ({
        value: o.id,
        displayLabel: o.label,
        recommended: !!o.recommended,
      }));
    } else {
      // letter list (single_choice fallback)
      chips = detected.letters.map(l => ({ value: l, displayLabel: l }));
    }

    let getNote = () => null;

    chips.forEach(c => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "quick-reply-chip";
      if (c.recommended) btn.classList.add("quick-reply-chip-recommended");
      // "options" chips carry prose labels — opt them into the long-label
      // layout (left-aligned, wraps, stacked vertically by the parent).
      if (kind === "options") btn.classList.add("quick-reply-chip-long");
      btn.textContent = c.recommended ? `★ ${c.displayLabel}` : c.displayLabel;
      btn.addEventListener("click", () => {
        const note = getNote();
        const displayText = note ? `${c.displayLabel} — ${note}` : c.displayLabel;
        Array.from(card.querySelectorAll("button, textarea")).forEach(el => el.disabled = true);
        card.classList.add("question-answered");
        submitQuickReply({ kind, value: c.value, displayText, note, cardEl: card });
      });
      row.appendChild(btn);
    });
    card.appendChild(row);

    getNote = renderNoteSection(card);
    return card;
  }

  // Shared error-recovery for the three user-submit paths
  // (text input, form card, quick-reply chip). All three previously left
  // pendingAgentMsg set and the sticky activity bar pinned on submit
  // failure — user saw a "Thinking..." spinner AND an error message.
  // This helper restores clean state so the user can retry.
  function _recoverFromSubmitError(errMsg, cardEl) {
    if (pendingAgentMsg) {
      try { pendingAgentMsg.el.remove(); } catch {}
      pendingAgentMsg = null;
    }
    setActivityBar(null);
    if (cardEl) {
      // Unlock the form / chip card so the user can retry. submitAnswer
      // and submitQuickReply lock these on submit; chatForm has no card.
      Array.from(cardEl.querySelectorAll("input, button, textarea")).forEach(el => el.disabled = false);
      cardEl.classList.remove("question-answered");
    }
    // M5 fix: do NOT unconditionally clear _currentInflightTaskId here.
    // This helper is called from:
    //   * chatForm submit handler — dispatch failed BEFORE _setChatInflight
    //     was called, so _currentInflightTaskId is still whatever the
    //     PRIOR task left it. Clearing it would orphan an actually-running
    //     task and surface SEND when STOP is still semantically correct.
    //   * submitQuickReply / submitAnswer — these dispatch via /api/chat/message
    //     too; their failure mode is identical (prior task may still run).
    // The submit handler's own catch needs to re-enable the button it
    // disabled (C2 fix), but it should NOT change the STOP/SEND mode —
    // that's owned by the task lifecycle (SSE FinalResponse/Error).
    if (chatSend && chatSend.disabled) {
      // Submit handler disabled the button as part of C2; restore so the
      // user can retry. Mode (STOP vs SEND) is unchanged.
      chatSend.disabled = false;
    }
    appendChatMessage("agent", `[error] ${errMsg} — please retry`);
  }

  async function submitQuickReply({ kind, value, displayText, note, cardEl }) {
    if (!chatSessionId) chatSessionId = deriveChatSessionId();
    if (!chatEventSource) openSseStream(chatSessionId);

    appendChatMessage("user", displayText);
    openThinkingBubble();

    const eid = currentProjectId();
    const agent = chatAgentSelect?.value || "";
    const data = { kind: "quick_reply", source_kind: kind, answer: value };
    if (note) data.note = note;
    const body = {
      text: _wrapWorkerAnswer(displayText, agent),
      data,
      session_id: chatSessionId,
    };
    if (agent) body.agent = agent;
    if (eid) body.engagement_id = eid;

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // STOP button visibility — quick-reply chips dispatch a task just
      // like the main chat form does. Capture the task_id so the SEND
      // button flips to STOP for the duration of the agent run, instead
      // of staying on SEND while the agent silently spins.
      try {
        const data = await res.json();
        if (data && data.task_id) _setChatInflight(data.task_id);
      } catch { /* response body missing — leave button in SEND mode */ }
    } catch (err) {
      _recoverFromSubmitError("could not send reply: " + err.message, cardEl);
    }
  }

  // Append a "+ Add a note" toggle + collapsed textarea to the form.
  // Returns a getter that reads the textarea value (trimmed, or null if
  // empty / never expanded). Used by single_choice, yes_no, multi_choice
  // — free_text skips this since its own input already accepts free prose.
  function renderNoteSection(form) {
    const wrap = document.createElement("div");
    wrap.className = "question-note-wrap";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "question-note-toggle";
    toggle.textContent = "+ Add a note (optional)";

    const ta = document.createElement("textarea");
    ta.className = "question-note-input";
    ta.rows = 2;
    ta.placeholder = "Add caveats, edge cases, or rationale the agent should record alongside your answer…";
    ta.style.display = "none";

    toggle.addEventListener("click", () => {
      const isOpen = ta.style.display !== "none";
      ta.style.display = isOpen ? "none" : "";
      toggle.textContent = isOpen ? "+ Add a note (optional)" : "– Hide note";
      if (!isOpen) ta.focus();
    });

    wrap.appendChild(toggle);
    wrap.appendChild(ta);
    form.appendChild(wrap);

    return () => {
      const v = ta.value.trim();
      return v || null;
    };
  }

  function formatAnswerForDisplay(schema, answer) {
    if (schema.kind === "yes_no") return answer === "yes" ? "Yes" : "No";
    if (schema.kind === "single_choice") return answer?.label || answer?.id || "(answer)";
    if (schema.kind === "multi_choice") return (answer?.labels || []).join(", ") || "(none)";
    if (schema.kind === "free_text") return answer?.text || "(empty)";
    return String(answer);
  }

  async function submitAnswer(schema, rawAnswer, displayText, cardEl, note = null) {
    if (!chatSessionId) chatSessionId = deriveChatSessionId();
    if (!chatEventSource) openSseStream(chatSessionId);

    // Lock the card so it can't be submitted twice. We unlock on failure
    // below so the user can retry rather than being stranded.
    const lockedInputs = Array.from(cardEl.querySelectorAll("input, button, textarea"));
    cardEl.classList.add("question-answered");
    lockedInputs.forEach(el => el.disabled = true);

    // Show the chosen answer as a user message.
    appendChatMessage("user", displayText);
    openThinkingBubble();

    const eid = currentProjectId();
    const agent = chatAgentSelect?.value || "";
    const data = { question_id: schema.id, kind: schema.kind, answer: rawAnswer };
    if (note) data.note = note;
    const body = {
      text: _wrapWorkerAnswer(displayText, agent),
      data,
      session_id: chatSessionId,
    };
    if (agent) body.agent = agent;
    if (eid) body.engagement_id = eid;

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // STOP button visibility — form-card answers dispatch a task too;
      // capture task_id so SEND flips to STOP for the duration of the
      // agent run. Without this the user sees the agent doing work
      // ("Reading discovery/discovery-brief.yaml…") but no way to stop it.
      try {
        const data = await res.json();
        if (data && data.task_id) _setChatInflight(data.task_id);
      } catch { /* leave button in SEND mode if response body missing */ }
    } catch (err) {
      _recoverFromSubmitError("could not submit answer: " + err.message, cardEl);
    }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function openSseStream(sessionId) {
    if (chatEventSource) chatEventSource.close();
    _stampSse();  // fresh stream → reset the silence timer
    chatEventSource = new EventSource(`/api/chat/stream/${encodeURIComponent(sessionId)}`);
    chatEventSource.onmessage = (e) => {
      _stampSse();   // any SSE message resets the silence timer
      _pingProgress();   // and the stuck-task watchdog
      try {
        const ev = JSON.parse(e.data);
        if (ev.type === "TaskStatusUpdateEvent") {
          // STOP-button arming from the SSE stream itself. Any in-flight
          // task — whether user-typed, form-card answer, quick-reply chip,
          // an orchestrator-initiated peer delegation, an auto-advance
          // dispatch, or anything else SAM does internally — emits status
          // updates here. Treat the first update for a given task_id as
          // proof of life and arm STOP. The dispatch-site _setChatInflight
          // calls (chatForm submit, submitAnswer, submitQuickReply) still
          // run for immediate visual feedback; this is the safety net for
          // tasks not triggered from a dispatch site we control. Same id
          // re-armings are no-ops (idempotent).
          const liveTaskId = ev.data?.task_id || null;
          if (liveTaskId && liveTaskId !== _currentInflightTaskId) {
            // Post-cancel suppression — if the user just clicked STOP and
            // an unrelated task_id shows up inside the grace window, it's
            // almost certainly an orchestrator auto-continuation we don't
            // want to silently re-arm. Cancel it and skip the inflight
            // adoption so the UI stays in "Stopping…" / SEND, not STOP.
            if (_inCancelGrace() && _suppressAutoSpawnedTask(liveTaskId)) {
              // intentionally swallow — do not arm STOP for this task.
            } else {
              _setChatInflight(liveTaskId);
            }
          }
          // Layer B: tool-call traces from SAM data parts.
          for (const d of extractDataParts(ev)) {
            if (d.type === "tool_invocation_start") appendToolTrace(d);
            else if (d.type === "tool_result") completeToolTrace(d);
            // agent_progress_update / llm_invocation / etc — text channel covers these.
          }
          const text = extractAgentText(ev);
          if (text) startOrUpdateAgentBubble(text);
        } else if (ev.type === "FinalResponse" || ev.type === "Task") {
          // Capture the responding agent so loadAgents() can restore it on
          // page reload — closes the "follow-up went to the wrong agent
          // after page re-init" bug.
          const ag = _extractRespondingAgent(ev) || (chatAgentSelect?.value || null);
          if (ag) setStickyAgent(currentProjectId(), ag);
          const finalText = extractAgentText(ev);
          const finId = ev.data?.id || null;
          // Disguised-error fast-path: SAM's common/error_handlers catches
          // upstream LLM 5xx and returns the human-facing string as a
          // SUCCESSFUL FinalResponse — not an Error event. Without this
          // intercept, the text would render as a normal bubble AND the
          // retry-counter reset below would treat the failure as a
          // success, breaking the escalation ladder. Route the disguised
          // error through _handleStreamDropError instead and skip the
          // success-path reset.
          const agentName = _extractRespondingAgent(ev) || chatAgentSelect?.value || "the agent";
          if (finalText && typeof _isTransientLLMError === "function"
              && _isTransientLLMError(finalText)) {
            _handleStreamDropError(agentName, finalText);
            if (finId && finId === _lastCancelTaskId) _clearStopSafetyTimer();
            _clearChatInflightIfMatches(finId);
          } else {
            _lastRespondingAgent = agentName;
            finalizeAgentBubble(finalText);
            // C1 fix: only restore SEND if THIS task is the one currently
            // tracked. A delayed FinalResponse for an older task must not
            // clobber a newer task's STOP state.
            // If the matching CANCELED final arrives normally, drop the
            // post-cancel safety net so it doesn't fire and print a hint
            // for a stop that worked.
            if (finId && finId === _lastCancelTaskId) _clearStopSafetyTimer();
            _clearChatInflightIfMatches(finId);
            // A successful turn means the stream-drop retry budget refills.
            // Without this reset, three consecutive errors during a multi-
            // scope auto run would lock the auto-resume out for the rest of
            // the engagement.
            const _eid = (typeof currentProjectId === "function") ? currentProjectId() : "";
            if (_eid) {
              _setAutoResumeRetries(_eid, 0);
              // Successful turn clears any pending auto-jump-to-fresh-session
              // state too — the engagement is healthy again, so future error
              // bursts get the full two-step budget (same-session, then fresh)
              // rather than skipping straight to give-up.
              _resetFreshEscalations(_eid);
              _clearDropFingerprint(_eid);    // healthy turn resets the repeat-drop guard
            }
          }
        } else if (ev.type === "Error") {
          const msg = ev.data?.message || ev.data?.error || "(error)";
          const agentName = _extractRespondingAgent(ev) || chatAgentSelect?.value || "the agent";
          // Stream-drop fast-path: render the resume card + (in Auto mode)
          // auto-dispatch with a countdown. Bypasses the generic error
          // categoriser so the user sees an actionable card instead of
          // "An unexpected error occurred" + a wall of guidance.
          // Pass the full data object so the helper can consume the
          // backend-emitted category / auto_retryable fields when present.
          if (_isStreamDropError(ev.data || msg)) {
            _handleStreamDropError(agentName, ev.data || msg);
          } else {
            // Build a rich error card instead of a one-line "[error] …"
            // The user needs (a) what failed, (b) a concrete next step,
            // (c) an option to see technical details.
            const errorCard = _buildErrorCard(msg, agentName, ev.data || {});
            if (pendingAgentMsg) {
              pendingAgentMsg.el.classList.remove("agent-thinking");
              pendingAgentMsg.el.classList.add("agent-error");
              pendingAgentMsg.el.innerHTML = "";
              pendingAgentMsg.el.appendChild(errorCard);
              pendingAgentMsg = null;
            } else {
              const wrap = document.createElement("div");
              wrap.className = "chat-msg agent agent-error";
              wrap.appendChild(errorCard);
              chatLog.appendChild(wrap);
              chatLog.scrollTop = chatLog.scrollHeight;
            }
            // Clear the sticky activity bar — without this it stays pinned
            // on "Thinking…" while the bubble shows the error message.
            setActivityBar(null);
          }
          // Error events don't carry task_id, so we can't precision-match.
          // Conservative: clear inflight unconditionally. The cost of a
          // mismatched clear here is small (user sees SEND when STOP would
          // be more accurate; typing a new message recovers cleanly via
          // the C2-fixed submit-disable). The cost of NOT clearing is
          // worse: the button is stuck on STOP after an error and clicking
          // it returns 404. Pick the lesser evil.
          _setChatInflight("");
        }
      } catch (err) { /* ignore malformed */ }
    };
    // Heartbeat listener — server emits `event: heartbeat\ndata: {}` every
    // 15s. We use it solely to stamp _lastSseEventAt so the 30s stale
    // detector below knows the stream is alive even when the agent itself
    // is quiet (between turns, mid-LLM-composition, etc.). Without this,
    // the detector would force-reconnect on every legitimate idle gap.
    chatEventSource.addEventListener("heartbeat", () => { _stampSse(); });

    chatEventSource.addEventListener("complete", () => {
      // CRITICAL: null the variable, don't just .close(). Every
      // `if (!chatEventSource) openSseStream(...)` check throughout
      // the code is a truthiness check, not a readyState check —
      // leaving a closed-but-non-null reference here means the next
      // turn's submit handler thinks the stream is still open, never
      // calls openSseStream, and every subsequent SSE event from the
      // agent vanishes into the void until the user refreshes. Same
      // pattern as the logout teardown earlier in the file.
      if (chatEventSource) {
        chatEventSource.close();
        chatEventSource = null;
      }
    });
    // Browser auto-reconnects EventSource on transport errors per the
    // retry: 5000 directive the server emits at stream open. While the
    // browser is in CONNECTING state, give the user a transient cue
    // (rather than silent dead air) — and on successful reconnect,
    // the server replays buffered events via Last-Event-Id so we don't
    // need to do anything more here.
    chatEventSource.onerror = () => {
      // readyState: 0 CONNECTING, 1 OPEN, 2 CLOSED. CLOSED means the
      // stream is permanently dead (typically a 4xx); browser won't
      // retry. CONNECTING means it WILL retry per the retry: directive.
      const state = chatEventSource?.readyState;
      if (state === 0) {
        setActivityBar("Reconnecting to agent stream…");
        _sseConsecutiveErrors++;
        // After 3 consecutive failures, give up on SSE entirely and switch
        // to long-poll. Some networks strip SSE traffic (corporate proxies,
        // some VPNs); polling /api/chat/poll/{sid} avoids the problem.
        if (_sseConsecutiveErrors >= 3 && !_longPollActive) {
          _startLongPollFallback(sessionId);
        }
      } else if (state === 2) {
        setActivityBar(null);
        if (chatEventSource) { chatEventSource.close(); chatEventSource = null; }
      }
    };
    chatEventSource.onopen = () => {
      // Clear the reconnect pill if it was showing; subsequent live
      // events will set their own activity-bar text.
      if (chatActivityBar?.textContent?.startsWith("Reconnecting")) setActivityBar(null);
      _sseConsecutiveErrors = 0;  // healthy open clears the long-poll trigger
      // Reconcile-after-reconnect: silently catch the UI up to whatever
      // changed on the server while the stream was down. Last-Event-Id
      // replay handles in-flight chat events; this picks up lifecycle
      // status, decisions, artifacts that may have advanced in the gap.
      // Skips on the very first connection (no gap to catch up from).
      if (_hasReconnectedOnce) _reconcileAfterReconnect();
      _hasReconnectedOnce = true;
    };
  }
  // Set to true after the first successful onopen so we only reconcile
  // on actual reconnects, not the initial open. The lifecycle poll
  // already runs every 5s so the cost of an extra reconcile fetch is
  // small, but explicit gating keeps the network panel clean.
  let _hasReconnectedOnce = false;

  // Long-poll fallback state. Tracks SSE error count so we can switch
  // modes only after 3 consecutive failures (single transient blips
  // are handled by EventSource auto-reconnect). _sseConsecutiveErrors
  // is reset on a successful onopen.
  let _sseConsecutiveErrors = 0;
  let _longPollActive = false;
  let _longPollTimer = null;
  let _longPollLastEventId = 0;
  // Periodically attempt to re-enable SSE — every 60s try opening a
  // fresh EventSource; if it stays connected for >5s, drop the polling.
  let _longPollSseProbeTimer = null;

  function _startLongPollFallback(sessionId) {
    if (_longPollActive) return;
    _longPollActive = true;
    _sseConsecutiveErrors = 0;
    setActivityBar("Streaming blocked — using long-poll fallback");
    // Close the failing EventSource cleanly.
    if (chatEventSource) { try { chatEventSource.close(); } catch {} chatEventSource = null; }
    const tick = async () => {
      if (!_longPollActive) return;
      try {
        const url = `/api/chat/poll/${encodeURIComponent(sessionId)}?since=${_longPollLastEventId}`;
        const resp = await fetch(url, { credentials: "include" });
        if (resp.ok) {
          const body = await resp.json();
          for (const ev of (body.events || [])) {
            _stampSse();
            // Dispatch each replayed payload through the same handler
            // the live SSE stream uses, so the UI updates identically.
            _dispatchSyntheticSseEvent(ev.payload);
            _longPollLastEventId = ev.id;
          }
        }
      } catch { /* network blip; next tick will retry */ }
      _longPollTimer = setTimeout(tick, 2000);
    };
    tick();
    // Try to recover SSE every 60s — corporate proxies sometimes
    // re-establish; if we never check we're stuck on polling forever.
    _longPollSseProbeTimer = setInterval(() => {
      // Probe by opening a transient EventSource; if it stays open
      // for 5s without error, we're back to live streaming.
      const probe = new EventSource(`/api/chat/stream/${encodeURIComponent(sessionId)}`);
      let probeOk = false;
      const probeTimer = setTimeout(() => {
        if (probeOk) {
          _stopLongPollFallback();
          chatEventSource = probe;
          setActivityBar(null);
        } else {
          try { probe.close(); } catch {}
        }
      }, 5000);
      probe.onopen = () => { probeOk = true; };
      probe.onerror = () => { clearTimeout(probeTimer); try { probe.close(); } catch {} };
    }, 60000);
  }

  function _stopLongPollFallback() {
    _longPollActive = false;
    if (_longPollTimer) { clearTimeout(_longPollTimer); _longPollTimer = null; }
    if (_longPollSseProbeTimer) { clearInterval(_longPollSseProbeTimer); _longPollSseProbeTimer = null; }
  }

  // Replay a server-side payload as if it had arrived live on the SSE
  // stream — same shape, same handler. Used by both Last-Event-Id replay
  // (inside the SSE stream) AND the long-poll fallback.
  function _dispatchSyntheticSseEvent(payload) {
    if (!payload) return;
    try {
      const ev = (typeof payload === "string") ? JSON.parse(payload) : payload;
      _pingProgress();   // replay events count as progress for the stuck-task watchdog
      // Reuse the EventSource onmessage logic by synthesising an event-
      // shaped object — easiest to just call the relevant branches inline.
      // (Could be refactored to a named function later if the live SSE
      // handler grows further; for now mirroring is clearer than the
      // alternative of dispatching a MessageEvent.)
      if (ev.type === "TaskStatusUpdateEvent") {
        // Same STOP-arming logic as the live-SSE branch — any in-flight
        // task surfaces here via long-poll when EventSource is dropped.
        const liveTaskId = ev.data?.task_id || null;
        if (liveTaskId && liveTaskId !== _currentInflightTaskId) {
          // Mirror of live-SSE post-cancel suppression.
          if (_inCancelGrace() && _suppressAutoSpawnedTask(liveTaskId)) {
            // intentionally swallow.
          } else {
            _setChatInflight(liveTaskId);
          }
        }
        for (const d of extractDataParts(ev)) {
          if (d.type === "tool_invocation_start") appendToolTrace(d);
          else if (d.type === "tool_result") completeToolTrace(d);
        }
        const text = extractAgentText(ev);
        if (text) startOrUpdateAgentBubble(text);
      } else if (ev.type === "FinalResponse" || ev.type === "Task") {
        // Disguised-error fast-path (mirror of live-SSE branch above).
        // SAM returns upstream LLM 5xx as a successful FinalResponse with
        // the error string as content — route those through the
        // stream-drop handler instead of rendering as a bubble + resetting
        // the retry budget.
        const finalText = extractAgentText(ev);
        const finId = ev.data?.id || null;
        const agentName = _extractRespondingAgent(ev) || chatAgentSelect?.value || "the agent";
        if (finalText && typeof _isTransientLLMError === "function"
            && _isTransientLLMError(finalText)) {
          _handleStreamDropError(agentName, finalText);
          if (finId && finId === _lastCancelTaskId) _clearStopSafetyTimer();
          _clearChatInflightIfMatches(finId);
        } else {
          _lastRespondingAgent = agentName;
          finalizeAgentBubble(finalText);
          // Mirror of live-SSE: only clear if this task matches the in-flight one.
          if (finId && finId === _lastCancelTaskId) _clearStopSafetyTimer();
          _clearChatInflightIfMatches(finId);
          // Mirror of live-SSE: refill the stream-drop retry budget on success.
          const _eid = (typeof currentProjectId === "function") ? currentProjectId() : "";
          if (_eid) {
            _setAutoResumeRetries(_eid, 0);
            _resetFreshEscalations(_eid);
            _clearDropFingerprint(_eid);    // healthy turn resets the repeat-drop guard
          }
        }
      } else if (ev.type === "Error") {
        const msg = ev.data?.message || ev.data?.error || "(error)";
        const agentName = _extractRespondingAgent(ev) || chatAgentSelect?.value || "the agent";
        // Mirror of the live-SSE stream-drop fast-path (passes full data
        // so the helper can prefer the backend-classified category).
        if (_isStreamDropError(ev.data || msg)) {
          _handleStreamDropError(agentName, ev.data || msg);
        } else {
          const errorCard = _buildErrorCard(msg, agentName, ev.data || {});
          const wrap = document.createElement("div");
          wrap.className = "chat-msg agent agent-error";
          wrap.appendChild(errorCard);
          chatLog.appendChild(wrap);
          chatLog.scrollTop = chatLog.scrollHeight;
          setActivityBar(null);
          // Same conservative-clear rationale as the live-SSE Error path.
          _setChatInflight("");
        }
      }
    } catch { /* malformed payload; skip */ }
  }

  // Silent state catch-up after the EventSource reconnects. Re-runs the
  // same fetches as refreshLifecycleBar + pollLifecycle so the dashboard
  // reflects any work the agent did while the stream was down. No UI
  // reload, no flash — the next render() picks up the fresh state.
  async function _reconcileAfterReconnect() {
    const eid = currentProjectId();
    if (!eid) return;
    try {
      // Refresh the sticky lifecycle bar + activity-state derived from it.
      if (typeof refreshLifecycleBar === "function") await refreshLifecycleBar();
      // Re-fire the lifecycle drift / phase-handoff detector with fresh data.
      if (typeof pollLifecycle === "function") await pollLifecycle();
    } catch { /* best-effort; the 5s poll will catch up either way */ }
  }

  const chatAgentSelect = document.getElementById("chat-agent-select");
  // Module-scope reference to the SEND/STOP button. There's a same-name
  // const inside render() at the top of the file — that one shadows this
  // when render() runs, which is fine (both point at the same DOM node).
  // We need the module-scope one for _setChatInflight + the STOP click
  // handler + _recoverFromSubmitError, which all live outside render().
  // Without this, app.js crashed at load with "chatSend is not defined"
  // and the whole dashboard hung on "Loading…".
  const chatSend = document.getElementById("chat-send-btn");

  // Sticky agent selection per engagement. Captured on FinalResponse, restored
  // by loadAgents() on page init. Without this, the dropdown reverts to the
  // gateway-configured default on every page reload, sending follow-up
  // messages to the wrong agent (the "proceed in order" misroute we saw).
  function _lastAgentKey(eid) { return `sa.last_agent.${eid}`; }
  function getStickyAgent(eid) {
    if (!eid) return null;
    try { return localStorage.getItem(_lastAgentKey(eid)) || null; }
    catch { return null; }
  }
  function setStickyAgent(eid, agentName) {
    if (!eid || !agentName) return;
    try { localStorage.setItem(_lastAgentKey(eid), agentName); } catch {}
  }
  function clearStickyAgent(eid) {
    if (!eid) return;
    try { localStorage.removeItem(_lastAgentKey(eid)); } catch {}
  }

  // Categorize SAM's user-facing error messages so we can render a
  // contextual card with concrete next-step guidance. SAM's
  // common/error_handlers.py maps LLM provider errors to one of a few
  // generic strings — those strings have stable prefixes we can match.
  // For each category we emit (a) a short tag, (b) a "what happened"
  // explanation, (c) a "what to try" action list, (d) optional CTA buttons.
  function _categorizeError(msg) {
    const m = (msg || "").toLowerCase();
    if (m.includes("conversation history") && m.includes("too long")) {
      return {
        tag: "Context limit",
        explanation: "The chat session has accumulated too many turns for the model to process.",
        actions: [
          "Click <strong>Start fresh session</strong> below to begin a new chat. Prior artifacts and decisions are preserved on disk.",
          "Or: reload the page — sessions live in memory and are cleared on SAM restart.",
        ],
        cta: { label: "Start fresh chat session", action: "fresh-session" },
      };
    }
    if (m.includes("rate limit")) {
      return {
        tag: "Rate limited",
        explanation: "The LLM provider is throttling requests for this account.",
        actions: ["Wait 30-60 seconds and retry.", "If this persists, check the provider's quota dashboard."],
      };
    }
    if (m.includes("authentication") || m.includes("api key")) {
      return {
        tag: "Auth failed",
        explanation: "The LLM provider rejected the API credentials.",
        actions: [
          "Verify the LLM_SERVICE_API_KEY env var is set correctly.",
          "Confirm the key has access to the configured model in <code>shared_config.yaml</code>.",
        ],
      };
    }
    if (m.includes("unable to connect") || m.includes("api_connection") || m.includes("connection")) {
      return {
        tag: "Connection",
        explanation: "Could not reach the LLM service endpoint.",
        actions: [
          "Check network connectivity from the SAM host.",
          "Verify LLM_SERVICE_ENDPOINT in the SAM env.",
        ],
      };
    }
    if (m.includes("timed out") || m.includes("timeout")) {
      return {
        tag: "Timeout",
        explanation: "The LLM didn't respond within the request budget.",
        actions: ["Retry — transient timeouts are common under load.", "If recurring, the agent's task may be too large for one LLM call."],
      };
    }
    if (m.includes("service is temporarily unavailable") || m.includes("service unavailable")) {
      return {
        tag: "Provider down",
        explanation: "The LLM provider is reporting a service outage.",
        actions: ["Check the provider's status page.", "Retry in a few minutes."],
      };
    }
    if (m.includes("rejected the request") || m.includes("bad request")) {
      // SAM's DEFAULT_BAD_REQUEST_MESSAGE — usually one of:
      // input too long, content policy violation, malformed tool schema.
      return {
        tag: "Request rejected",
        explanation: "The LLM provider rejected the request. Most common causes: context too long, a tool-call schema the model can't fulfil, or a content-policy filter.",
        actions: [
          "Check the SAM log (<code>sam/sam.log</code>) — the underlying provider error is logged there with the full reason.",
          "If the chat session has many prior turns, try <strong>Start fresh session</strong> below.",
          "If this is the first turn of a phase, retry — transient prompt-too-long errors clear on next attempt.",
        ],
        cta: { label: "Start fresh chat session", action: "fresh-session" },
      };
    }
    return {
      tag: "Error",
      explanation: "The agent's turn failed.",
      actions: [
        "Check <code>sam/sam.log</code> for the underlying error.",
        "Retry — many errors are transient.",
      ],
    };
  }

  function _buildErrorCard(msg, agentName, evData) {
    const cat = _categorizeError(msg);
    const card = document.createElement("div");
    card.className = "agent-error-card";
    const detailsId = `err-details-${Date.now()}`;
    const actionsHtml = cat.actions.map(a => `<li>${a}</li>`).join("");
    const ctaHtml = cat.cta
      ? `<button type="button" class="cta-btn cta-btn-secondary agent-error-cta" data-action="${escapeHtml(cat.cta.action)}">${escapeHtml(cat.cta.label)}</button>`
      : "";
    // Server-side correlation id (added in _send_error_to_external). The
    // user can quote this when reporting a bug; operator greps sam.log for
    // the matching `[error_id=…]` log line to pull the full failure stack.
    const errorId = evData?.error_id;
    card.innerHTML = `
      <div class="agent-error-header">
        <span class="agent-error-tag">${escapeHtml(cat.tag)}</span>
        <span class="agent-error-agent">${escapeHtml(agentName)}</span>
        ${errorId
          ? `<span class="agent-error-id" title="Quote this when reporting the issue. Operator can grep sam.log for [error_id=${escapeHtml(errorId)}] to retrieve the full failure context.">ID ${escapeHtml(errorId)}</span>`
          : ""}
      </div>
      <div class="agent-error-body">
        <p class="agent-error-explanation">${escapeHtml(cat.explanation)}</p>
        <p class="agent-error-message-from-llm">${escapeHtml(msg)}</p>
        <details class="agent-error-actions-details">
          <summary>What to try</summary>
          <ul>${actionsHtml}</ul>
        </details>
        <details class="agent-error-tech-details" id="${detailsId}">
          <summary>Technical details</summary>
          <pre>${escapeHtml(JSON.stringify(evData, null, 2))}</pre>
        </details>
      </div>
      <div class="agent-error-actions">
        ${ctaHtml}
        <button type="button" class="cta-btn agent-error-retry" data-action="retry">Retry</button>
      </div>`;

    // Wire CTA buttons. "Retry" re-sends the previous user message; the
    // backend's persistent session may still trip the same error if the
    // root cause is context length — that's why we also surface
    // "Start fresh session" for context-limit and request-rejected cases.
    card.querySelector(".agent-error-retry")?.addEventListener("click", () => {
      const lastUser = [...chatLog.querySelectorAll(".chat-msg.user")].pop();
      const text = lastUser?.textContent?.trim();
      if (!text) return;
      const ci = document.getElementById("chat-input");
      if (ci) { ci.value = text; chatForm?.requestSubmit?.(); }
    });
    card.querySelector(".agent-error-cta")?.addEventListener("click", (e) => {
      const action = e.currentTarget.dataset.action;
      if (action === "fresh-session") startFreshChatSession();
    });
    return card;
  }

  // --- Auto-mode state (per engagement, per design step) -----------------
  // The Design step is dispatched as ONE A2A task per scope so each scope
  // gets its own LLM-call budget (SAM caps at 30 turns per task). In Auto
  // mode the frontend chains the next scope automatically when the prior
  // scope finishes DONE / DONE_WITH_CONCERNS. Pause clears the flag; user
  // can resume by clicking "Continue in chat" which falls back to manual.
  function _autoModeKey(eid) { return `sa.auto_mode.${eid}`; }
  function isAutoModeActive(eid) {
    if (!eid) return false;
    try { return localStorage.getItem(_autoModeKey(eid)) === "1"; }
    catch { return false; }
  }

  // Per-engagement intake-time execution_mode cache. Stamped by the
  // Overview render every poll (10s). Read by renderPhaseHandoffCard
  // (which runs from SSE handlers and doesn't see the Overview's
  // local executionMode variable) to decide which mode is the user's
  // intake preference. Fall back to "interactive" when the cache is
  // empty (engagement loaded mid-session, etc.).
  function _execModeKey(eid) { return `sa.exec_mode.${eid}`; }
  function rememberExecutionMode(eid, mode) {
    if (!eid || (mode !== "auto" && mode !== "interactive")) return;
    try { localStorage.setItem(_execModeKey(eid), mode); } catch {}
  }
  function recallExecutionMode(eid) {
    if (!eid) return "interactive";
    try { return localStorage.getItem(_execModeKey(eid)) === "auto" ? "auto" : "interactive"; }
    catch { return "interactive"; }
  }
  function setAutoMode(eid, active) {
    if (!eid) return;
    try {
      if (active) localStorage.setItem(_autoModeKey(eid), "1");
      else localStorage.removeItem(_autoModeKey(eid));
    } catch {}
  }


  // Returns true when at least one question card is still awaiting the
  // user's answer. Used as a hard gate on every auto-dispatch path
  // (auto-advance, auto-resume, fresh-session escalation, stuck-task
  // watchdog) — countdowns continue to run while the tab is hidden
  // (browsers throttle but don't pause setTimeout), so without this
  // gate switching back to the tab could fire a dispatch on top of an
  // unanswered question and silently pick an option for the user.
  //
  // A card with class `question-answered` (set by the click handlers)
  // is treated as no-longer-pending.
  function _hasPendingQuestionCard() {
    try {
      return !!chatLog?.querySelector?.(".question-card:not(.question-answered)");
    } catch { return false; }
  }

  // ── Stream-drop auto-resume ──────────────────────────────────────────────
  //
  // Observed pattern (2026-05-23): upstream OpenAI streaming connection drops
  // mid-response (MidStreamFallbackError / incomplete chunked read). SAM
  // converts this into a user-facing Error event with messages like
  // "The LLM service is temporarily unavailable" or "An unexpected error
  // occurred". Previously the user saw a scary error card and had to click
  // Continue manually. This block intercepts the error, renders a focused
  // resume card, and (in Auto mode) auto-dispatches a resume kickoff after a
  // brief countdown. Retries are capped to prevent flapping loops.

  const MAX_AUTO_RESUMES = 3;
  // Bounded fresh-session auto-recovery for repeated/persistent drops: jump to
  // a fresh session and resume up to MAX_FRESH_RETRIES times, then stop and let
  // the user decide. The first jump is near-immediate (a brief blip); each
  // later jump waits FRESH_COOLDOWN_SECONDS first, to let an intermittent
  // gateway bad-window pass before spending another call against it.
  const MAX_FRESH_RETRIES = 3;
  const FRESH_COOLDOWN_SECONDS = 150;
  const RESUME_KICKOFF_TEXT = (
    "Continue — the prior turn ended with an upstream LLM stream drop or " +
    "transient unavailability.\n\n" +
    "Pick up where you left off. If this scope's artifact already exists on " +
    "disk, read it first and only do the remaining work (narrative + " +
    "record_scope_progress). Don't redo decisions or rewrite artifacts that " +
    "are already there."
  );

  // Per-agent server endpoint that rebuilds the phase's deterministic kickoff
  // (idempotent, no state mutation) for drop-recovery — pattern A, generalised
  // across phases. On a stream-drop we re-send THIS instead of the generic
  // RESUME_KICKOFF_TEXT, so the agent keeps its deterministic context (Design:
  // WORKER MODE + computed map; Validation: PRECOMPUTED CHECKS; Blueprint:
  // bundled artifacts + outline) rather than re-deriving from scratch. Agents
  // not listed (reviewers, EP) fall back to the generic resume — reviewers
  // re-fetch their pack via get_review_pack on their own first step.
  const _RESUME_KICKOFF_URL = {
    SADomainAgent:    eid => `/api/engagements/${encodeURIComponent(eid)}/design/scope-kickoff`,
    SAValidationAgent: eid => `/api/engagements/${encodeURIComponent(eid)}/validation/kickoff`,
    SABlueprintAgent: eid => `/api/engagements/${encodeURIComponent(eid)}/blueprint/kickoff`,
  };

  // Stream-drop resume dispatcher. Re-sends the phase's deterministic kickoff
  // (via _RESUME_KICKOFF_URL) so the agent keeps its context; the generic resume
  // bypasses that (the worker re-derives from scratch — what made the heavy
  // integration scope never complete). Falls back to generic resume for
  // unlisted agents or if the fetch fails.
  async function _submitResumeKickoff(agentName) {
    let text = RESUME_KICKOFF_TEXT;
    const who = agentName || _lastRespondingAgent || "";
    const urlFn = _RESUME_KICKOFF_URL[who];
    try {
      const eid = currentProjectId?.();
      if (eid && urlFn) {
        const res = await fetch(urlFn(eid));
        if (res.ok) {
          const j = await res.json();
          if (j && j.kickoff) {
            text = j.kickoff;
            console.log(`[design-orchestrator] drop-resume via ${who} kickoff endpoint${j.scope ? ` (scope=${j.scope})` : ""}`);
          } else {
            console.log(`[design-orchestrator] ${who} kickoff: nothing to resume; using generic resume`);
          }
        }
      }
    } catch (e) {
      console.warn("[design-orchestrator] resume kickoff fetch failed; generic resume:", e);
    }
    const ci = document.getElementById("chat-input");
    if (ci) {
      // A stream-drop resume is a SYSTEM action, not a user message — suppress
      // the user bubble so the (often large, map-carrying) kickoff payload
      // doesn't dump into the chat. Mirrors _dispatchOrchestratorScope.
      _suppressNextUserBubble = true;
      ci.value = text;
      chatForm?.requestSubmit?.();
    }
  }

  // Detect any transient LLM-side failure mode where the agent's task
  // crashed mid-work but partial progress (decisions, artifacts) is on
  // disk. Same recovery flow works for all of these — re-dispatch and
  // let the agent resume from on-disk state.
  //
  // Now accepts the full error-event data so we can prefer the gateway-
  // emitted ``category`` / ``auto_retryable`` codes when present (set by
  // the backend's error_classifier). Falls back to substring matching on
  // the message for older paths and any future error sources we haven't
  // wired through the classifier.
  function _isTransientLLMError(msgOrEvData) {
    // Backend-classified path — most reliable
    if (msgOrEvData && typeof msgOrEvData === "object") {
      if (msgOrEvData.auto_retryable === true) return true;
      // Some non-transient categories (context_limit, authentication, etc.)
      // explicitly should NOT trigger auto-resume even if the message looks
      // similar. Respect the backend classification when present.
      if (msgOrEvData.category && msgOrEvData.auto_retryable === false) return false;
      // Fall through to message-based check if no category was assigned.
      msgOrEvData = msgOrEvData.message || msgOrEvData.error || "";
    }
    const m = (msgOrEvData || "").toLowerCase();
    return (
      // Upstream provider dropped the streaming response mid-flight
      m.includes("midstreamfallbackerror")
      || m.includes("incomplete chunked read")
      || m.includes("peer closed connection")
      // SAM's friendly rewrites of the above
      || m.includes("service is temporarily unavailable")
      || m.includes("unexpected error occurred")
      // Model hit its max-output-tokens cap mid-tool-call. ADK reports this
      // as "Last event shouldn't be partial. LLM max output limit may be
      // reached." Observed 2026-05-22 23:40:50, Domain agent.
      || m.includes("last event shouldn't be partial")
      || m.includes("llm max output limit")
      // API-layer transient — observed 2026-05-24: LLM proxy returned an
      // HTML error body instead of JSON. Surfaces as litellm.APIError /
      // OpenAIException strings. Without these patterns, the FE's
      // auto-resume escalation never fires and the user loops forever
      // against a hard-down upstream.
      || m.includes("openaiexception - <html>")
      || m.includes("apiconnectionerror")
      || m.includes("litellm.apierror")
      || m.includes("litellm.apiconnectionerror")
    );
  }
  // Back-compat alias — earlier code (and future PRs being rebased) may
  // still reference the narrower name. Keep as a thin alias rather than
  // a separate function so they can't drift.
  const _isStreamDropError = _isTransientLLMError;
  // (Removed _isSessionFullError — context-limit errors already route
  // through _buildErrorCard's "Context limit" branch which surfaces the
  // fresh-session CTA, so a dedicated helper had no caller. The
  // auto_retryable=false short-circuit in _isTransientLLMError covers
  // the don't-auto-retry case.)

  function _autoResumeKey(eid) { return `sa.resume_retries.${eid}`; }
  // Per-engagement COUNT of consecutive fresh-session auto-jumps for the
  // current run of failures. Incremented on each auto-jump; reset to 0 on the
  // next successful FinalResponse, a manual "Start fresh session", or a manual
  // "Retry once". Caps the auto-recovery at MAX_FRESH_RETRIES — beyond that we
  // stop and hand it to the user (a genuinely degraded upstream).
  function _freshCountKey(eid) { return `sa.fresh_escalations.${eid}`; }
  function _getFreshEscalations(eid) {
    if (!eid) return 0;
    try { return parseInt(localStorage.getItem(_freshCountKey(eid)) || "0", 10) || 0; }
    catch { return 0; }
  }
  function _bumpFreshEscalations(eid) {   // returns the new count
    if (!eid) return 0;
    const n = _getFreshEscalations(eid) + 1;
    try { localStorage.setItem(_freshCountKey(eid), String(n)); } catch {}
    return n;
  }
  function _resetFreshEscalations(eid) {
    if (!eid) return;
    try { localStorage.removeItem(_freshCountKey(eid)); } catch {}
  }
  function _getAutoResumeRetries(eid) {
    if (!eid) return 0;
    try { return parseInt(localStorage.getItem(_autoResumeKey(eid)) || "0", 10) || 0; }
    catch { return 0; }
  }
  function _setAutoResumeRetries(eid, n) {
    if (!eid) return;
    try {
      if (n <= 0) localStorage.removeItem(_autoResumeKey(eid));
      else localStorage.setItem(_autoResumeKey(eid), String(n));
    } catch {}
  }

  // Held at module scope so Pause / Resume now can cancel an in-flight countdown.
  let _pendingAutoResumeTimer = null;
  function _cancelPendingAutoResume() {
    if (_pendingAutoResumeTimer) {
      clearTimeout(_pendingAutoResumeTimer);
      _pendingAutoResumeTimer = null;
    }
  }

  // Real agent names available for pinning. Used to refuse pinning against
  // the placeholder fallback ("the agent") that _extractRespondingAgent can
  // return when the Error event lacks an agent attribution.
  const _PINNABLE_AGENTS = new Set([
    "SAOrchestratorAgent", "SADiscoveryAgent", "SADomainAgent",
    "SAArchitectReviewerAgent", "SADeveloperReviewerAgent",
    "SAOpsReviewerAgent", "SASecurityReviewerAgent",
    "SAValidationAgent", "SAEventPortalAgent", "SABlueprintAgent",
  ]);

  // Exponential backoff for same-session auto-resume retries.
  // Attempt N waits BASE × 2^N seconds: 8s → 16s → 32s (capped at 60s).
  // Hammering an overloaded upstream every 8s makes it worse — exponential
  // gives the provider room to recover. After MAX_AUTO_RESUMES, the
  // fresh-session escalation card takes over with its own 5s countdown.
  const RESUME_BACKOFF_BASE_SECS = 8;
  const RESUME_BACKOFF_CAP_SECS = 60;
  function _backoffSecsForRetry(retries) {
    const v = RESUME_BACKOFF_BASE_SECS * Math.pow(2, retries);
    return Math.min(RESUME_BACKOFF_CAP_SECS, Math.round(v));
  }

  function _renderStreamDropResumeCard(agentName, retries, autoMode) {
    const card = document.createElement("div");
    card.className = "chat-msg agent stream-drop-card";
    const remaining = MAX_AUTO_RESUMES - retries;
    const willAutoResume = autoMode && remaining > 0;
    const backoffSecs = _backoffSecsForRetry(retries);
    // When retries are exhausted (or we're already on the 2nd+ retry of a
    // run that hasn't yet finished a turn) the failure is likely structural
    // (e.g. context-window saturation from a persistent session), not a
    // one-off stream drop. Offer the fresh-session escape hatch.
    const offerFreshSession = retries >= 1;
    const statusLine = willAutoResume
      ? `<p class="stream-drop-countdown">Auto-resuming in <span class="stream-drop-secs">${backoffSecs}</span>s… (attempt ${retries + 1} of ${MAX_AUTO_RESUMES}, exponential backoff)</p>`
      : (autoMode
          ? `<p class="muted">Auto-resume cap reached (${MAX_AUTO_RESUMES} attempts). Click <strong>Resume now</strong> to try once more — or, if this keeps happening, <strong>Start fresh session</strong> usually unsticks it (the in-memory agent session may be saturated).</p>`
          : `<p class="muted">Click <strong>Resume now</strong> to continue${offerFreshSession ? " — or <strong>Start fresh session</strong> if retries aren't getting through" : ""}.</p>`);
    const pauseBtn = willAutoResume
      ? `<button type="button" class="cta-btn cta-btn-secondary stream-drop-pause">Pause Auto</button>`
      : ``;
    const freshBtn = offerFreshSession
      ? `<button type="button" class="cta-btn cta-btn-secondary stream-drop-fresh-session">Start fresh session</button>`
      : ``;
    card.innerHTML = `
      <div class="stream-drop-header">
        <span class="stream-drop-icon">⚠</span>
        <span class="stream-drop-title">Upstream LLM stream dropped</span>
      </div>
      <div class="stream-drop-body">
        <p>${escapeHtml(agentName)} got an incomplete response from the LLM provider mid-turn. This is a provider-side hiccup, not a SAM error.</p>
        <p class="muted">Any artifact ${escapeHtml(agentName)} already wrote in this turn is on disk and will be reused — the resume picks up from there, not from scratch.</p>
        ${statusLine}
      </div>
      <div class="stream-drop-actions">
        ${pauseBtn}
        ${freshBtn}
        <button type="button" class="cta-btn stream-drop-now">Resume now</button>
      </div>
    `;
    return card;
  }

  // Auto-mode escalation card: shown after MAX_AUTO_RESUMES same-session
  // retries are spent AND we haven't yet auto-jumped to a fresh session
  // for this engagement. Counts down then fires startFreshChatSession()
  // + resubmits the RESUME_KICKOFF_TEXT. Cancellable via the Cancel
  // button, which falls through to the normal same-session-cap UI.
  function _renderFreshEscalationCard(agentName, detailHtml) {
    const card = document.createElement("div");
    card.className = "chat-msg agent stream-drop-card";
    const detail = detailHtml || `${escapeHtml(agentName)} hit ${MAX_AUTO_RESUMES} consecutive transient failures in this chat session. Jumping to a fresh session — the in-memory agent state may be saturated; on-disk artifacts and decisions are preserved.`;
    card.innerHTML = `
      <div class="stream-drop-header">
        <span class="stream-drop-icon">⚡</span>
        <span class="stream-drop-title">Recovering automatically — fresh session</span>
      </div>
      <div class="stream-drop-body">
        <p>${detail}</p>
        <p class="stream-drop-countdown">Starting fresh session in <span class="stream-drop-secs">5s</span>…</p>
      </div>
      <div class="stream-drop-actions">
        <button type="button" class="cta-btn cta-btn-secondary stream-drop-pause">Cancel</button>
        <button type="button" class="cta-btn stream-drop-now">Switch now</button>
      </div>`;
    return card;
  }

  // Give-up card: shown when the fresh-session jump ALSO ran out of
  // retries. Indicates a real upstream outage, not a recoverable
  // local issue. Manual Retry button only — no further auto-jumps so
  // we don't loop forever against a dead provider.
  function _renderGiveUpCard(agentName) {
    const card = document.createElement("div");
    card.className = "chat-msg agent stream-drop-card";
    card.innerHTML = `
      <div class="stream-drop-header">
        <span class="stream-drop-icon">⛔</span>
        <span class="stream-drop-title">LLM service appears unavailable</span>
      </div>
      <div class="stream-drop-body">
        <p>Auto-recovery tried a same-session retry budget AND a fresh-session jump for ${escapeHtml(agentName)} — both ran out of retries with the same transient error.</p>
        <p class="muted">This usually means the upstream LLM provider is having issues right now, not a SAM or session problem. Wait a few minutes and click <strong>Retry</strong> below, or open the admin's service-status dashboard.</p>
      </div>
      <div class="stream-drop-actions">
        <button type="button" class="cta-btn stream-drop-now">Retry</button>
      </div>`;
    return card;
  }

  // ── Stop-the-loop guard: stop auto-retrying IDENTICAL drops ──────────────
  // A transient blip is worth retrying; the SAME failure repeating is
  // deterministic (e.g. a turn that always exceeds the upstream's ~60s
  // streaming limit) and retrying the identical work just spins the user in
  // circles. After REPEAT_STOP_THRESHOLD identical drops in a row we stop and
  // surface the real cause instead of running the full retry ladder.
  const REPEAT_STOP_THRESHOLD = 2;

  function _dropFingerprint(errDataOrText) {
    let s = errDataOrText;
    if (s && typeof s === "object") {
      if (s.category) return String(s.category);     // backend-classified — most stable
      s = s.message || s.error || "";
    }
    // Normalize free text so the same failure shape fingerprints identically
    // across attempts (strip task ids / hex / numbers / collapse whitespace).
    return String(s || "transient")
      .toLowerCase()
      .replace(/[0-9a-f]{6,}/g, "")
      .replace(/\d+/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80);
  }
  function _recordDropFingerprint(eid, fp) {
    // Returns how many times this fingerprint has fired in a row (1 = new/changed).
    if (!eid) return 1;
    try {
      const prev = JSON.parse(localStorage.getItem(`sa.drop_fp.${eid}`) || "null");
      const count = (prev && prev.fp === fp) ? (prev.count || 0) + 1 : 1;
      localStorage.setItem(`sa.drop_fp.${eid}`, JSON.stringify({ fp, count }));
      return count;
    } catch { return 1; }
  }
  function _clearDropFingerprint(eid) {
    if (!eid) return;
    try { localStorage.removeItem(`sa.drop_fp.${eid}`); } catch {}
  }

  function _renderRepeatedDropCard(agentName, count) {
    const card = document.createElement("div");
    card.className = "chat-msg agent stream-drop-card";
    card.innerHTML = `
      <div class="stream-drop-header">
        <span class="stream-drop-icon">⛔</span>
        <span class="stream-drop-title">Still failing after an automatic fresh session — your call</span>
      </div>
      <div class="stream-drop-body">
        <p>${escapeHtml(agentName)} kept hitting the <strong>same</strong> error even after auto-recovery already started a fresh session for you. That's not a passing blip — auto-retrying further would just loop, so it's paused for you to decide.</p>
        <p class="muted">Most likely the upstream LLM is genuinely degraded right now, or this turn is too large for it. Wait a moment and <strong>Retry once</strong> if you think the upstream has recovered, break the request into a smaller step, or <strong>Start fresh session</strong> to try one more clean session.</p>
      </div>
      <div class="stream-drop-actions">
        <button type="button" class="cta-btn cta-btn-secondary stream-drop-fresh-session">Start fresh session</button>
        <button type="button" class="cta-btn stream-drop-now">Retry once</button>
      </div>`;
    return card;
  }
  function _showRepeatedDropCard(agentName, count) {
    const card = _renderRepeatedDropCard(agentName, count);
    if (pendingAgentMsg) {
      pendingAgentMsg.el.classList.remove("agent-thinking");
      pendingAgentMsg.el.innerHTML = "";
      pendingAgentMsg.el.appendChild(card);
      pendingAgentMsg = null;
    } else {
      chatLog.appendChild(card);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
    setActivityBar(null);
    _setChatInflight("");
    card.querySelector(".stream-drop-fresh-session")?.addEventListener("click", () => {
      _cancelPendingAutoResume();
      startFreshChatSession();
    });
    card.querySelector(".stream-drop-now")?.addEventListener("click", () => {
      // Manual retry = explicit reset of the loop guard + escalation state.
      const eid = (typeof currentProjectId === "function") ? currentProjectId() : "";
      if (eid) {
        _clearDropFingerprint(eid);
        _setAutoResumeRetries(eid, 0);
        _resetFreshEscalations(eid);
      }
      _submitResumeKickoff(agentName);
      card.remove();
    });
  }

  function _handleStreamDropError(agentName, errData) {
    const eid = (typeof currentProjectId === "function") ? currentProjectId() : "";
    // Stop-the-loop guard: bail to a clear "deterministic failure" card once the
    // SAME error repeats, instead of running the full retry ladder in circles.
    const repeat = _recordDropFingerprint(eid, _dropFingerprint(errData));
    if (repeat >= REPEAT_STOP_THRESHOLD) {
      _cancelPendingAutoResume();
      // Same error twice running = same-session retry won't help (it would
      // just loop). But a FRESH session is the known-good recovery — clean
      // agent state, same on-disk work resumed. So auto-jump to a fresh
      // session ONCE (5s countdown, cancellable) instead of stopping for a
      // manual click. Runs in BOTH auto and interactive mode: it's pure
      // housekeeping — no decision is made on the user's behalf, the same
      // work resumes, artifacts/decisions are preserved. Only fall back to
      // the manual stop card if a fresh session was ALREADY tried this run
      // and the error STILL repeats — that's genuinely deterministic /
      // upstream-down and a human should judge it.
      const freshCount = eid ? _getFreshEscalations(eid) : MAX_FRESH_RETRIES;
      if (freshCount < MAX_FRESH_RETRIES) {
        // First jump is near-immediate (a brief blip); later jumps wait a
        // cooldown so an intermittent gateway bad-window can pass before we
        // spend another call on it. Runs in BOTH auto and interactive mode —
        // pure housekeeping (same on-disk work resumes; nothing decided for
        // the user). After MAX_FRESH_RETRIES consecutive jumps all fail we
        // stop (below) and hand it to the user.
        const countdownSecs = freshCount === 0 ? 5 : FRESH_COOLDOWN_SECONDS;
        const attemptNo = freshCount + 1;
        const detail = freshCount === 0
          ? `${escapeHtml(agentName)} hit the same stream drop twice in a row — retrying the identical turn in this session would just loop. Starting a fresh session automatically and picking up exactly where we left off; on-disk artifacts and decisions are preserved.`
          : `${escapeHtml(agentName)} is still hitting the same upstream stream drop — the LLM gateway looks degraded right now. Letting it recover, then trying another fresh session (attempt ${attemptNo} of ${MAX_FRESH_RETRIES}). On-disk artifacts and decisions are preserved.`;
        return _doFreshEscalation(agentName, eid, detail, countdownSecs);
      }
      return _showRepeatedDropCard(agentName, repeat);
    }
    const retries = _getAutoResumeRetries(eid);
    // Auto-mode applies if EITHER:
    //   (a) the ephemeral auto-mode flag is set (user clicked a "Start … Auto"
    //       CTA earlier and hasn't Paused), OR
    //   (b) the intake preference cached via rememberExecutionMode is "auto".
    // Gating on (a) alone broke the escalation when a user came in via
    // "Continue in chat" / typed-"continue" mid-engagement — those paths
    // don't call setAutoMode, so an auto-intake engagement looked like
    // interactive to this function.
    const ephemeralAuto = (typeof isAutoModeActive === "function") && isAutoModeActive(eid);
    const intakeAuto = (typeof recallExecutionMode === "function") && recallExecutionMode(eid) === "auto";
    const autoMode = ephemeralAuto || intakeAuto;
    const freshCount = _getFreshEscalations(eid);

    // AUTO-MODE ESCALATION LADDER:
    //   - Same-session retries 1..MAX_AUTO_RESUMES → existing card (auto
    //     countdown for resume in this session).
    //   - Same-session retries exhausted AND fresh-jumps < MAX_FRESH_RETRIES →
    //     auto-jump to a fresh session (immediate first, cooldown after).
    //   - Fresh-jump budget spent → give up (upstream genuinely down; manual).
    // Interactive mode skips this ladder entirely — falls through to
    // the existing manual-button card.
    if (autoMode && retries >= MAX_AUTO_RESUMES) {
      if (freshCount < MAX_FRESH_RETRIES) {
        const countdownSecs = freshCount === 0 ? 5 : FRESH_COOLDOWN_SECONDS;
        return _doFreshEscalation(agentName, eid, undefined, countdownSecs);
      }
      return _showGiveUpCard(agentName);
    }
    const willAutoResume = autoMode && retries < MAX_AUTO_RESUMES;
    const card = _renderStreamDropResumeCard(agentName, retries, autoMode);

    // Replace any pending agent bubble or append fresh
    if (pendingAgentMsg) {
      pendingAgentMsg.el.classList.remove("agent-thinking");
      pendingAgentMsg.el.innerHTML = "";
      pendingAgentMsg.el.appendChild(card);
      pendingAgentMsg = null;
    } else {
      chatLog.appendChild(card);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
    setActivityBar(null);
    _setChatInflight("");

    const dispatch = () => {
      _cancelPendingAutoResume();
      // Block auto-resume while a question card is waiting — typing
      // "continue" over an unanswered form card would silently bypass
      // the agent's prompt and submit nothing meaningful.
      if (_hasPendingQuestionCard()) {
        const body = card.querySelector(".stream-drop-body");
        if (body) {
          body.innerHTML = `<p class="muted">Auto-resume paused — a question card is awaiting your answer. Resume manually after you answer.</p>`;
        }
        return;
      }
      _setAutoResumeRetries(eid, retries + 1);
      // Pin the dispatch to the agent that errored — only if it's a real
      // SA agent name (not the "the agent" placeholder fallback).
      if (agentName && _PINNABLE_AGENTS.has(agentName) && window.__setPendingDispatchAgent) {
        window.__setPendingDispatchAgent(agentName);
      }
      _submitResumeKickoff(agentName);
      card.remove();
    };

    card.querySelector(".stream-drop-now")?.addEventListener("click", dispatch);
    card.querySelector(".stream-drop-pause")?.addEventListener("click", () => {
      _cancelPendingAutoResume();
      if (eid && typeof setAutoMode === "function") setAutoMode(eid, false);
      const body = card.querySelector(".stream-drop-body");
      if (body) {
        body.innerHTML = `<p class="muted">Auto mode paused. Click <strong>Resume now</strong> to continue manually.</p>`;
      }
      card.querySelector(".stream-drop-pause")?.remove();
    });
    card.querySelector(".stream-drop-fresh-session")?.addEventListener("click", () => {
      _cancelPendingAutoResume();
      startFreshChatSession();   // also drops the card via chatLog.innerHTML = ""
    });

    if (willAutoResume) {
      let secs = _backoffSecsForRetry(retries);
      const secsEl = card.querySelector(".stream-drop-secs");
      _cancelPendingAutoResume();
      const tick = () => {
        secs--;
        if (secsEl) secsEl.textContent = String(secs);
        if (secs <= 0) dispatch();
        else _pendingAutoResumeTimer = setTimeout(tick, 1000);
      };
      _pendingAutoResumeTimer = setTimeout(tick, 1000);
    }
  }

  // Auto-jump to a fresh session and resume. Renders the escalation card,
  // counts down `countdownSecs` (default 5; longer for cooldown retries),
  // bumps the per-engagement fresh-jump counter, then runs the jump.
  // Cancellable. Capped by MAX_FRESH_RETRIES at the call sites.
  function _doFreshEscalation(agentName, eid, detailHtml, countdownSecs) {
    const card = _renderFreshEscalationCard(agentName, detailHtml);
    if (pendingAgentMsg) {
      pendingAgentMsg.el.classList.remove("agent-thinking");
      pendingAgentMsg.el.innerHTML = "";
      pendingAgentMsg.el.appendChild(card);
      pendingAgentMsg = null;
    } else {
      chatLog.appendChild(card);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
    setActivityBar(null);
    _setChatInflight("");

    const fire = () => {
      _cancelPendingAutoResume();
      // Block the auto-jump while a question card is waiting. (Note:
      // startFreshChatSession clears chatLog wholesale, which would
      // destroy the user's pending question card without them having
      // answered.) Pause silently — the user can hit Switch now manually.
      if (_hasPendingQuestionCard()) {
        const body = card.querySelector(".stream-drop-body");
        if (body) {
          body.innerHTML = `<p class="muted">Fresh-session jump paused — a question card is awaiting your answer. Answer it, then click Switch now if you still want to start fresh.</p>`;
        }
        return;
      }
      // Pin the dispatch to the agent that errored so the resubmit lands
      // on the same agent (the fresh session has no sticky pick yet).
      if (agentName && _PINNABLE_AGENTS.has(agentName) && window.__setPendingDispatchAgent) {
        window.__setPendingDispatchAgent(agentName);
      }
      startFreshChatSession();    // clears chatLog, _autoResumeRetries, AND the fresh-jump counter
      // Bump the counter AFTER startFreshChatSession (which resets it to 0 as
      // part of the manual "fresh start" semantics). The count must PERSIST
      // across the auto-jump so consecutive jumps accumulate toward
      // MAX_FRESH_RETRIES — beyond that the call sites stop auto-jumping and
      // hand it to the user instead of looping against a down upstream.
      _bumpFreshEscalations(eid);
      _submitResumeKickoff(agentName);
    };

    card.querySelector(".stream-drop-now")?.addEventListener("click", fire);
    card.querySelector(".stream-drop-pause")?.addEventListener("click", () => {
      _cancelPendingAutoResume();
      const body = card.querySelector(".stream-drop-body");
      if (body) {
        body.innerHTML = `<p class="muted">Auto-jump cancelled. Click <strong>Switch now</strong> to fresh-session manually, or wait and click <strong>Retry</strong> against the same session.</p>`;
      }
      // Keep "Switch now" as a manual trigger; drop the Cancel button.
      card.querySelector(".stream-drop-pause")?.remove();
    });

    let secs = (countdownSecs && countdownSecs > 0) ? countdownSecs : 5;
    const secsEl = card.querySelector(".stream-drop-secs");
    // Friendly "Mm SSs" for the long cooldown waits; bare seconds otherwise.
    const fmtSecs = (s) => s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
    if (secsEl) secsEl.textContent = fmtSecs(secs);
    _cancelPendingAutoResume();
    const tick = () => {
      secs--;
      if (secsEl) secsEl.textContent = fmtSecs(secs);
      if (secs <= 0) fire();
      else _pendingAutoResumeTimer = setTimeout(tick, 1000);
    };
    _pendingAutoResumeTimer = setTimeout(tick, 1000);
  }

  // Final state when both same-session AND fresh-session budgets are spent.
  // Manual Retry only — no auto-anything, so we don't burn cycles on a
  // genuinely down upstream provider.
  function _showGiveUpCard(agentName) {
    const card = _renderGiveUpCard(agentName);
    if (pendingAgentMsg) {
      pendingAgentMsg.el.classList.remove("agent-thinking");
      pendingAgentMsg.el.innerHTML = "";
      pendingAgentMsg.el.appendChild(card);
      pendingAgentMsg = null;
    } else {
      chatLog.appendChild(card);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
    setActivityBar(null);
    _setChatInflight("");

    card.querySelector(".stream-drop-now")?.addEventListener("click", () => {
      // Treat manual retry as a clean reset of the escalation state —
      // user is explicitly choosing to start over.
      const eid = (typeof currentProjectId === "function") ? currentProjectId() : "";
      if (eid) {
        _setAutoResumeRetries(eid, 0);
        _resetFreshEscalations(eid);
      }
      _submitResumeKickoff(agentName);
      card.remove();
    });
  }

  // Render the "Auto: advancing to <next> in N…" card. Returns the card el
  // so the caller can update / remove it. The card has a "Pause Auto" button
  // that cancels the pending dispatch AND clears the Auto-mode flag so the
  // remaining scopes stay manual.
  // One-shot: set true right before an auto-dispatch requestSubmit so the chat
  // submit handler skips rendering/persisting the kickoff as a user bubble.
  // Reset by the handler after it reads it. Keeps auto-continue invisible.
  let _suppressNextUserBubble = false;

  // True when `text` is one of our machine-generated kickoffs (auto-advance,
  // scope-continue, or stream-drop/fresh-session resume) rather than something
  // the user typed. Matched by distinctive prefixes so every dispatch site is
  // covered without per-site flags. These read as internal orchestration, so
  // the submit handler suppresses their user bubble for a seamless transcript.
  function _isInternalKickoff(text) {
    if (!text) return false;
    const t = String(text).trimStart();
    return t.startsWith("Continue — the prior turn ended")   // RESUME_KICKOFF_TEXT
        || t.startsWith("Mode: auto")                         // primed phase kickoff (primeKickoff prefix)
        || t.includes("WORKER MODE");                         // orchestrated worker kickoff (incl. drop-resume scope-kickoff)
  }

  // ── Design orchestrator executor (the ONLY design engine) ─────────────────
  // The server-side orchestrator (POST /api/engagements/{id}/design/advance)
  // owns scope order, retries, completion, and what runs next. The frontend is
  // a THIN EXECUTOR: after a Design (SADomainAgent) turn finishes, it reports
  // the outcome and dispatches whatever scope the server names. The classic
  // self-orchestration engine (_maybeAutoAdvance + client-built kickoffs) was
  // removed 2026-05-28 — it was unreachable AND its kickoffs bypassed the
  // orchestrator (no WORKER MODE / no computed map). `_orchActive` is retained
  // as a constant `true` so existing call sites read clearly.
  function _orchActive(_eid) { return true; }

  // True only while an orchestrated Design run is live for the current
  // engagement — so the finalize hook only advances Design after a Design turn,
  // never after a Discovery/Review/etc. turn. Set on start, cleared on
  // complete / blocked / retry_exhausted / user pause.
  let _orchRunning = false;
  // The scope the orchestrator last told us to dispatch; reported back as
  // last_scope so the server can record its outcome from the artifact on disk.
  let _orchLastScope = "";
  // Responding agent of the most recently finished turn. Gates the orchestrated
  // advance to Design (SADomainAgent) turns ONLY — so a mid-run interjection to
  // another agent (e.g. the Orchestrator) can't trigger a spurious scope dispatch.
  let _lastRespondingAgent = "";

  async function _orchAdvanceRequest(eid, mode, outcome, extra) {
    const body = Object.assign(
      { mode, last_scope: _orchLastScope || null, outcome: outcome || null },
      extra || {},
    );
    const res = await fetch(`/api/engagements/${encodeURIComponent(eid)}/design/advance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    // A missing route (HTTP 404) means the server wasn't restarted with the
    // orchestrator endpoints; a 5xx is a server error. Surface it rather than
    // letting res.json() throw an opaque parse error that callers swallow.
    if (!res.ok) throw new Error(`HTTP ${res.status} from /design/advance`);
    return res.json();
  }

  // Called from finalizeAgentBubble after a Design turn. Reports the outcome
  // and executes the next action the orchestrator returns.
  async function _orchestratedAdvance() {
    const eid = currentProjectId?.();
    if (!eid || !_orchActive(eid) || !_orchRunning) return;
    // A pending question card means the worker asked the user something —
    // report it so the orchestrator parks the scope; don't dispatch over it.
    const outcome = _hasPendingQuestionCard() ? "question" : null;
    const mode = recallExecutionMode(eid);
    let action;
    try { action = await _orchAdvanceRequest(eid, mode, outcome); }
    catch (e) { console.warn("[design-orchestrator] advance failed:", e); return; }
    _applyOrchestratorAction(eid, action, mode);
  }

  function _applyOrchestratorAction(eid, action, mode) {
    const act = action && action.action;
    if (act === "dispatch") {
      _orchLastScope = action.scope || "";
      if (mode === "auto") _dispatchOrchestratorScope(action);
      else _renderOrchestratorContinueCard(action);   // interactive: user steps between scopes
    } else if (act === "await_user") {
      // Worker asked a question (already rendered as a question card). Nothing
      // to dispatch; answering it finalizes a turn → _orchestratedAdvance again.
      _orchLastScope = action.scope || _orchLastScope;
    } else if (act === "complete") {
      _orchRunning = false;
      _orchLastScope = "";
      appendChatMessage("agent", "✅ Design complete — every applicable scope is done. Review is next.");
      try { if (typeof render === "function") render(); } catch {}
    } else if (act === "retry_exhausted" || act === "blocked") {
      _orchRunning = false;
      _renderOrchestratorStuckCard(action);
    }
    // "in_flight" → no-op (a dispatch is already running)
  }

  // Send the worker kickoff the orchestrator built. Fresh session per scope
  // boundary keeps each scope's context ~constant (the round-12 stall
  // mitigation) — every scope rebuilds state from disk anyway.
  function _dispatchOrchestratorScope(action) {
    const k = action.kickoff || "";
    console.log(`[design-orchestrator] dispatch scope=${action.scope} kickoffLen=${k.length} `
      + `workerMode=${k.includes("WORKER MODE")} computed=${k.includes("COMPUTED (authoritative")}`);
    startFreshChatSession({
      message: `Starting design scope: ${action.scope}. Prior decisions and artifacts are saved on disk.`,
    });
    const ci = document.getElementById("chat-input");
    if (!ci) return;
    if (window.__setPendingDispatchAgent) window.__setPendingDispatchAgent(action.agent || "SADomainAgent");
    _selectChatAgent(action.agent || "SADomainAgent");
    _suppressNextUserBubble = true;
    ci.value = action.kickoff;
    chatForm?.requestSubmit?.();
  }

  function _renderOrchestratorContinueCard(action) {
    const card = document.createElement("div");
    card.className = "auto-advance-card";
    card.innerHTML =
      `<p>Scope <code>${escapeHtml(action.scope)}</code> is ready.</p>` +
      `<button class="orch-continue">Continue → ${escapeHtml(action.scope)}</button>`;
    card.querySelector(".orch-continue")?.addEventListener("click", () => {
      card.remove();
      _dispatchOrchestratorScope(action);
    });
    chatLog.appendChild(card);
  }

  function _renderOrchestratorStuckCard(action) {
    const card = document.createElement("div");
    card.className = "stream-drop-card";
    const why = action.action === "blocked"
      ? `Scope <code>${escapeHtml(action.scope)}</code> is blocked: ${escapeHtml(action.note || "needs input")}.`
      : `Scope <code>${escapeHtml(action.scope)}</code> failed ${action.attempts || ""} attempts.`;
    card.innerHTML =
      `<p>${why}</p>` +
      `<button class="orch-retry">Retry scope</button>`;
    card.querySelector(".orch-retry")?.addEventListener("click", async () => {
      card.remove();
      _orchRunning = true;
      const eid = currentProjectId?.();
      if (!eid) return;
      // Reset the scope's retry budget server-side, else decide_next would
      // immediately re-surface the same exhausted/blocked state.
      try {
        const res = await fetch(`/api/engagements/${encodeURIComponent(eid)}/design/advance`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reset_scope: action.scope }),
        });
        _applyOrchestratorAction(eid, await res.json(), recallExecutionMode(eid));
      } catch { /* best-effort */ }
    });
    chatLog.appendChild(card);
  }

  // Entry point: start (or resume) an orchestrated Design run. Fetches the
  // first scope from the orchestrator and opens the chat with its kickoff.
  async function _startOrchestratedDesign(eid, mode) {
    if (!eid) return;
    rememberExecutionMode(eid, mode);
    _orchRunning = true;
    _orchLastScope = "";
    // Open the chat pane FIRST so the dispatch — or any error message — is
    // visible. (openChatWith is local to the CTA wiring; replicate it with
    // module-scope primitives.)
    applyChat?.("open");
    let action;
    try {
      action = await _orchAdvanceRequest(eid, mode, null);
    } catch (e) {
      _orchRunning = false;
      // VISIBLE failure (was a silent return). The most common cause is the
      // server not being restarted with the /design endpoints yet.
      appendChatMessage(
        "agent",
        `⚠️ Couldn't start the design orchestrator: ${e && e.message ? e.message : "request failed"}. ` +
        `If you just deployed, restart SAM so the /design endpoints are live (a 404 means the ` +
        `running server predates them), then click Start Design again.`,
      );
      console.warn("[design-orchestrator] start failed:", e);
      return;
    }
    // On Start/resume, a scope parked in ANY non-progress state from a prior
    // session — await_user (question not on this screen), in_flight (a dispatch
    // that never finished), retry_exhausted or blocked — must be re-dispatched
    // so the worker actually runs it HERE, rather than dead-ending. Reset its
    // budget and re-advance to get a fresh dispatch. (complete/dispatch fall
    // through unchanged.)
    if (action && action.scope
        && action.action !== "dispatch" && action.action !== "complete") {
      _orchLastScope = action.scope || "";
      try {
        action = await _orchAdvanceRequest(eid, mode, null, { reset_scope: action.scope });
      } catch (e) {
        _orchRunning = false;
        appendChatMessage("agent", `⚠️ Couldn't resume the design scope: ${e && e.message ? e.message : "request failed"}.`);
        return;
      }
    }
    if (action && action.action === "dispatch") {
      _orchLastScope = action.scope || "";
      if (window.__setPendingDispatchAgent) window.__setPendingDispatchAgent(action.agent || "SADomainAgent");
      _selectChatAgent(action.agent || "SADomainAgent");
      _suppressNextUserBubble = true;
      const ci = document.getElementById("chat-input");
      if (ci) { ci.value = action.kickoff; ci.focus(); chatForm?.requestSubmit?.(); }
    } else {
      _applyOrchestratorAction(eid, action, mode);
    }
  }

  // Pull the responding agent's name from a FinalResponse event payload.
  // SAM attaches it to status.message.metadata.agent_name in
  // _publish_text_as_partial_a2a_status_update. Fall back to whatever the
  // dropdown was set to when the message was sent.
  function _extractRespondingAgent(ev) {
    try {
      return ev?.data?.status?.message?.metadata?.agent_name
          || ev?.data?.metadata?.agent_name
          || null;
    } catch { return null; }
  }

  // Per-agent domain hints — surfaced as the option's title attribute so the
  // user gets a tooltip on hover. Stops the most common mistake (sending an
  // off-topic question to a specialised agent — e.g. "what's the weather" to
  // SAEventPortalAgent — and getting a confusing crash or refusal in chat).
  // Keep entries short; tooltips are read-glance, not documentation.
  const AGENT_DOMAIN_HINTS = {
    "SAOrchestratorAgent":
      "Coordinator — routes between phases, fans out to reviewers. Use for general engagement questions.",
    "SADiscoveryAgent":
      "Discovery phase — intake refinement, reference-architecture matching. Use at engagement start.",
    "SADomainAgent":
      "Design phase — 9 architecture scopes (topic, broker, protocol, integration, mesh, HA/DR, SAM, EP model, migration).",
    "SAArchitectReviewerAgent":
      "Architecture-perspective review (5 criteria: component fit, simpler alternatives, trade-offs, pattern alignment, cross-cutting). Non-interactive.",
    "SADeveloperReviewerAgent":
      "Developer-perspective review (topic usability, SDK/API choice, schema governance, error handling, onboarding). Non-interactive.",
    "SAOpsReviewerAgent":
      "Ops-perspective review (monitoring, failure modes, capacity, runbooks, alerting). Non-interactive.",
    "SASecurityReviewerAgent":
      "Security-perspective review (auth, ACLs, TLS, credentials, compliance). Non-interactive.",
    "SAValidationAgent":
      "Validation gate — requirement coverage, antipattern scan, consistency. Decides DONE / DONE_WITH_CONCERNS / BLOCKED.",
    "SAEventPortalAgent":
      "Live Event Portal provisioning via EP Designer MCP — creates domains, schemas, events, applications. Opt-in only.",
    "SABlueprintAgent":
      "Final assembly — architecture narrative, runbook, diagrams, 5 audience packs (HTML+PDF), engagement ZIP. Non-interactive.",
  };
  const _DEFAULT_HINT = "Generic SAM agent. For Solace Architect workflow questions try SAOrchestratorAgent or SADiscoveryAgent.";

  // Phase-derived chat-agent default. The dropdown auto-advances to the
  // agent that owns the engagement's currently-active step, so a free-text
  // reply to a Discovery question routes to SADiscoveryAgent (not the
  // dropdown's stale default). Mirrors dashboard_tools.py `_phase_of`.
  //
  // The 4 reviewers + the 9 design scopes collapse to one agent each:
  //   - All design scopes → SADomainAgent (the user converses with Domain
  //     across the whole Design phase regardless of which scope is active).
  //   - All review scopes → SAOrchestratorAgent (the user converses with
  //     the orchestrator during Review fan-out; reviewers are non-
  //     interactive peers dispatched by the orchestrator).
  // Step ids here MUST match the canonical step names from
  // ``configs/skill-routing.yaml`` (which is what
  // ``compute_overview_stats.recommended_next_step`` returns). Earlier
  // versions of this map used short prefixes (``"topic"``, ``"broker"``)
  // that never resolved because the real step ids include the suffix
  // (``"topic-design"``, ``"broker-select"``) — silently failing the
  // lookup, leaving ``phaseAgent=""``, and letting the dropdown fall
  // through to the prior phase's selection (observed 2026-05-23 with
  // dropdown stuck on SADiscoveryAgent while Design was in progress).
  const _STEP_TO_AGENT = {
    "discovery": "SADiscoveryAgent",
    "topic-design": "SADomainAgent",
    "broker-select": "SADomainAgent",
    "sam-design": "SADomainAgent",
    "protocol-select": "SADomainAgent",
    "mesh-design": "SADomainAgent",
    "ha-dr": "SADomainAgent",
    "migration": "SADomainAgent",
    "integration": "SADomainAgent",
    "event-portal-design": "SADomainAgent",
    "review": "SAOrchestratorAgent",
    "validation": "SAValidationAgent",
    "event-portal": "SAEventPortalAgent",
    "blueprint": "SABlueprintAgent",
  };

  // Ordinal rank of each phase-owning agent in the lifecycle. Used by
  // loadAgents() to detect a STALE userPick — one that points at a
  // phase agent for a phase already BEHIND the current active phase —
  // and drop it so the dropdown re-anchors to the active phase.
  // A pick pointing at a phase AHEAD of the active one (e.g. user pinned
  // SAValidationAgent during Design to look ahead) is preserved.
  const _AGENT_PHASE_ORDER = {
    SADiscoveryAgent: 1,
    SADomainAgent: 2,
    SAOrchestratorAgent: 3,           // Review phase (also the cross-phase default)
    SAValidationAgent: 4,
    SAEventPortalAgent: 5,
    SABlueprintAgent: 6,
  };

  // Preferred default agent — SAOrchestratorAgent. Per user requirement, the
  // dropdown lands on this agent on every fresh page load (and after auth /
  // engagement switches) unless the user has explicitly picked something else
  // (persisted in localStorage). Sticky-from-FinalResponse and the gateway's
  // default_agent_name are now lower-priority fallbacks — used only when
  // SAOrchestratorAgent isn't discoverable OR the user's previous manual pick
  // has gone away from the mesh.
  const PREFERRED_DEFAULT_AGENT = "SAOrchestratorAgent";
  // Routing target for the "Send to SAM" escape hatch — the stock SAM
  // orchestrator that ships outside the SA family. Bypasses the SA
  // workflow for one-off mesh queries (weather, find-my-ip, etc.).
  const SAM_FALLBACK_AGENT = "OrchestratorAgent";
  const _USER_PICK_KEY = "sa.chat_agent_pick";
  function _getUserPickedAgent() {
    try { return localStorage.getItem(_USER_PICK_KEY) || ""; } catch { return ""; }
  }
  function _setUserPickedAgent(name) {
    try {
      if (name) localStorage.setItem(_USER_PICK_KEY, name);
      else localStorage.removeItem(_USER_PICK_KEY);
    } catch { /* ignore — localStorage may be unavailable in private mode */ }
  }

  // Point the chat agent dropdown (and the persistent user pick, so the 15s
  // re-poll doesn't snap it back) AT a specific agent. Called on phase start so
  // the dropdown auto-reflects the phase being started, and the user's
  // follow-up messages route to that agent rather than the previous value.
  function _selectChatAgent(agent) {
    if (!agent) return;
    try {
      const sel = document.getElementById("chat-agent-select");
      if (sel && Array.from(sel.options).some(o => o.value === agent)) {
        sel.value = agent;
      }
      _setUserPickedAgent(agent);
      if (typeof loadAgents === "function") loadAgents();
    } catch { /* best-effort */ }
  }

  // During an active orchestrated Design run, a user message to SADomainAgent is
  // a continuation of the current scope (typically the answer to the worker's
  // blocking question). Re-assert WORKER MODE + scope on the SENT text so the
  // agent stays in worker context even if a stream-drop / fresh-session dropped
  // the prior turns (otherwise it falls back to classic mode, re-reads the
  // checkpoint, and misfires its lane-guard — the "switch to SADomainAgent"
  // confusion). Only the dispatched text is wrapped; the chat bubble still shows
  // the user's original words.
  function _wrapWorkerAnswer(text, agent) {
    const eid = currentProjectId?.();
    if (eid && agent === "SADomainAgent" && _orchActive(eid) && _orchRunning && _orchLastScope
        && !/^\s*(WORKER MODE|Mode:\s*auto)/.test(text || "")) {
      return `WORKER MODE\nScope: ${_orchLastScope}\n\n${text}`;
    }
    return text;
  }

  async function loadAgents() {
    if (!chatAgentSelect) return;
    // Preserve whatever the user picked so the 15s re-poll doesn't snap the
    // selection back to the configured default.
    const previousChoice = chatAgentSelect.value || "";
    try {
      const r = await fetch("/api/agents");
      const d = await r.json();
      const agents = d.agents || [];
      const defaultName = d.default || "";
      if (!agents.length) {
        chatAgentSelect.innerHTML = `<option value="">${escapeHtml(defaultName || "(no agents discovered)")}</option>`;
        return;
      }
      // Discovery returns every agent on the mesh — but the dropdown
      // exposes only the SA family. Non-SA agents (stock OrchestratorAgent,
      // find-my-ip, sam-mermaid, …) are routable via the "Send to SAM"
      // checkbox in the chat form, not via the dropdown. Hiding them from
      // the picker eliminates the misclick trap where users picked
      // "OrchestratorAgent" thinking it was ours.
      const saAgents = agents.filter(a => a.name in AGENT_DOMAIN_HINTS);
      const names = new Set(saAgents.map(a => a.name));

      // Show / hide the "Send to SAM" escape hatch based on whether the
      // stock SAM_FALLBACK_AGENT is actually on this mesh. Offering it
      // when no one's home would silently 404 every dispatch.
      const samAvailable = agents.some(a => a.name === SAM_FALLBACK_AGENT);
      const samWrap = document.getElementById("chat-send-to-sam-wrap");
      if (samWrap) samWrap.classList.toggle("hidden", !samAvailable);

      // Auto-clear a sticky `_userPickedAgent` that points at a non-SA
      // agent (e.g. someone misclicked OrchestratorAgent before the
      // dropdown filtered to SA-only). Without this, the precedence
      // chain below would silently keep falling through, and the
      // dropdown's `desired` couldn't ever land on the stale pick (it's
      // not rendered) so the change would feel surprising. Better to
      // null it out so the precedence cleanly resolves to
      // SAOrchestratorAgent.
      let userPick = _getUserPickedAgent();
      if (userPick && !names.has(userPick)) {
        _setUserPickedAgent("");
        userPick = "";
      }

      // Phase-derived default — derive the agent that owns the engagement's
      // currently-active step from `recommended_next_step` in overview stats.
      // Without this, the dropdown defaulted to SAOrchestratorAgent on every
      // fresh load, so a free-text reply to (e.g.) a Discovery question
      // routed to the orchestrator instead of SADiscoveryAgent — the
      // orchestrator's "Stay in your lane" rule then bounced it. The fetch
      // is best-effort: on unauth / network / no-engagement / API failure,
      // phaseAgent stays empty and the chain falls through to
      // PREFERRED_DEFAULT_AGENT (the original behavior).
      const eid = currentProjectId();
      let phaseAgent = "";
      if (eid) {
        try {
          const sr = await fetch(`/api/engagements/${encodeURIComponent(eid)}/overview`);
          if (sr.ok) {
            const stats = await sr.json();
            const step = stats?.recommended_next_step || "";
            phaseAgent = _STEP_TO_AGENT[step] || "";
          }
        } catch { /* fall through to PREFERRED_DEFAULT_AGENT */ }
      }

      // Self-heal STALE userPick: if it points at a phase agent for a
      // phase BEHIND the current active one (e.g. dropdown pinned to
      // SADiscoveryAgent while Design is in progress), drop it so the
      // dropdown re-anchors to phaseAgent. Picks AHEAD of the active
      // phase are preserved (the user explicitly looked ahead);
      // non-phase agents aren't ranked, so this never clears them.
      if (userPick && phaseAgent) {
        const userPickRank = _AGENT_PHASE_ORDER[userPick] || 0;
        const phaseRank = _AGENT_PHASE_ORDER[phaseAgent] || 0;
        if (userPickRank > 0 && phaseRank > 0 && userPickRank < phaseRank) {
          _setUserPickedAgent("");
          userPick = "";
        }
      }

      // Resolve which agent should end up selected, in this preference order:
      //   1. User's persistent manual pick (localStorage), if still discovered.
      //      Wins over phaseAgent so an explicit override survives phase changes.
      //   2. Phase-derived default — auto-advances with the engagement's
      //      current phase so free-text replies land on the right agent.
      //   3. Previous dropdown value — fallback when phaseAgent can't be
      //      computed (compute_overview_stats not yet available, e.g. brand-
      //      new engagement). Keeps the 15s re-poll from snapping mid-session.
      //   4. SAOrchestratorAgent — final default for engagements with no
      //      phase computed yet.
      //   5. Gateway-configured default_agent_name — last-resort fallback.
      // Sticky-from-FinalResponse (the agent that last replied) is deliberately
      // NOT in this chain — it would override the user's choice every time an
      // orchestrator delegated to a sub-agent. Phase-derived is the correct
      // substitute because Review phase IS the orchestrator (so delegation
      // doesn't change the conversational target).
      const desired = (userPick && names.has(userPick))             ? userPick
                    : (phaseAgent && names.has(phaseAgent))         ? phaseAgent
                    : (previousChoice && names.has(previousChoice)) ? previousChoice
                    : (names.has(PREFERRED_DEFAULT_AGENT))           ? PREFERRED_DEFAULT_AGENT
                    : (names.has(defaultName) ? defaultName : "");

      const renderOption = (a) => {
        const hint = AGENT_DOMAIN_HINTS[a.name] || _DEFAULT_HINT;
        return `<option value="${escapeHtml(a.name)}" title="${escapeHtml(hint)}"${a.name === desired ? " selected" : ""}>${escapeHtml(a.name)}</option>`;
      };
      chatAgentSelect.innerHTML = saAgents.map(renderOption).join("");
      if (desired) chatAgentSelect.value = desired;
      // Stash the natural default (phaseAgent || PREFERRED_DEFAULT_AGENT) on
      // the select element so the change handler can decide whether the
      // user's pick should pin via userPick. Picking the natural default
      // CLEARS userPick so the dropdown resumes auto-advancing with phase;
      // picking anything else SETS userPick to that explicit choice.
      chatAgentSelect.dataset.naturalDefault =
        (phaseAgent && names.has(phaseAgent)) ? phaseAgent : PREFERRED_DEFAULT_AGENT;
      // Mirror the selected option's hint onto the <select> itself so the
      // tooltip is visible even on the closed dropdown (not just per-option
      // when the menu is open).
      const selectedHint = AGENT_DOMAIN_HINTS[chatAgentSelect.value] || _DEFAULT_HINT;
      chatAgentSelect.setAttribute("title", selectedHint);
    } catch (err) {
      chatAgentSelect.innerHTML = `<option value="">(agent discovery failed)</option>`;
    }
  }
  chatAgentSelect?.addEventListener("change", () => {
    // refresh the placeholder to reflect the new agent target
    render();
    // Keep the closed-dropdown tooltip in sync with the picked agent.
    const hint = AGENT_DOMAIN_HINTS[chatAgentSelect.value] || _DEFAULT_HINT;
    chatAgentSelect.setAttribute("title", hint);
    // Persist the user's explicit pick. The native `change` event only fires
    // for user-initiated changes (programmatic `.value = X` assignments don't
    // dispatch it), so this captures exactly the intent we want: "the user
    // chose this on purpose; remember it for next time".
    //
    // Picking the engagement's NATURAL DEFAULT (phaseAgent for the current
    // phase, or SAOrchestratorAgent when no phase is computed) CLEARS the
    // override — so the dropdown resumes auto-advancing as the phase
    // changes. Picking anything else (e.g. SAOrchestratorAgent during
    // Design, where phaseAgent=SADomainAgent) SETS the override.
    const picked = chatAgentSelect.value || "";
    const naturalDefault = chatAgentSelect.dataset.naturalDefault || PREFERRED_DEFAULT_AGENT;
    if (picked && picked !== naturalDefault) {
      _setUserPickedAgent(picked);
    } else {
      _setUserPickedAgent("");
    }
  });
  // Re-poll periodically so newly-joined agents on the mesh appear in the picker
  setInterval(loadAgents, 15000);

  // Enter submits, Shift+Enter inserts a newline (chat-app convention).
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (typeof chatForm.requestSubmit === "function") chatForm.requestSubmit();
      else chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  // One-shot dispatch override — set by openChatWith() when a phase-handoff
  // CTA needs THIS turn to target a specific agent (e.g. SADiscoveryAgent
  // for the discovery kickoff) without flipping the user's dropdown choice.
  // Consumed and cleared on the next submit. Always falls back to the
  // dropdown value if unset.
  let _pendingDispatchAgent = "";
  // Expose for openChatWith (which is scoped inside wireProgressCtaActions).
  // Using a window setter rather than a shared closure keeps openChatWith
  // unchanged in shape — it just writes to this single source of truth.
  window.__setPendingDispatchAgent = (name) => { _pendingDispatchAgent = name || ""; };

  // In-flight task tracking for the STOP button. Set after a successful
  // /api/chat/message dispatch; cleared on a FinalResponse/Error SSE event
  // that matches the same task_id, or after a successful /api/chat/cancel
  // POST. The chat-send button reads this to decide whether it acts as
  // SEND or STOP.
  //
  // Why match on task_id (C1 fix): a delayed FinalResponse for task A
  // arriving after task B has already been dispatched would otherwise clear
  // _currentInflightTaskId while B is still running — making the STOP
  // button silently flip back to SEND and clicking STOP a no-op (the
  // taskId is empty). Always compare before clearing.
  let _currentInflightTaskId = "";

  // ---------------------------------------------------------------------
  // Stuck-task watchdog
  // ---------------------------------------------------------------------
  // ADK's AutoContinue has no cap on consecutive truncations — if the LLM
  // deterministically emits the same broken tool call (max-output-tokens
  // hit mid-call), the task loops internally without emitting any A2A
  // events to the gateway. The FE then thinks the task is still running
  // (STOP button armed) but the user sees nothing.
  //
  // Watchdog: every WATCHDOG_TICK_MS, if a task is in flight AND no
  // progress event has arrived in STUCK_THRESHOLD_MS, surface a banner
  // offering one-click cancel + auto-fresh-session. _lastProgressAt is
  // pinged by every event handler that hears from the agent — status
  // updates, text deltas, tool traces, FinalResponses.
  const STUCK_THRESHOLD_MS = 180000;   // 3 min of agent silence ≈ wedged
  const WATCHDOG_TICK_MS = 15000;
  let _lastProgressAt = 0;
  let _stuckWatchdogInterval = null;
  let _stuckBannerEl = null;

  function _pingProgress() { _lastProgressAt = Date.now(); }

  function _stopStuckWatchdog() {
    if (_stuckWatchdogInterval) {
      clearInterval(_stuckWatchdogInterval);
      _stuckWatchdogInterval = null;
    }
    if (_stuckBannerEl) {
      _stuckBannerEl.remove();
      _stuckBannerEl = null;
    }
  }

  function _startStuckWatchdog() {
    _stopStuckWatchdog();
    _pingProgress();
    _stuckWatchdogInterval = setInterval(() => {
      if (!_currentInflightTaskId) {
        _stopStuckWatchdog();
        return;
      }
      // Don't flag as stuck when the agent is legitimately waiting on
      // the user's answer to a question card — the silence is correct,
      // not a wedge.
      if (_hasPendingQuestionCard()) return;
      const silentMs = Date.now() - _lastProgressAt;
      if (silentMs >= STUCK_THRESHOLD_MS && !_stuckBannerEl) {
        _showStuckBanner(Math.round(silentMs / 1000));
      }
    }, WATCHDOG_TICK_MS);
  }

  function _showStuckBanner(silentSec) {
    const el = document.createElement("div");
    el.className = "chat-msg agent stream-drop-card";
    el.innerHTML = `
      <div class="stream-drop-header">
        <span class="stream-drop-icon">⏱</span>
        <span class="stream-drop-title">Task appears stuck</span>
      </div>
      <div class="stream-drop-body">
        <p>The agent hasn't sent any progress update for <strong>${silentSec}s</strong>. This is usually ADK's auto-continue loop wedged on a truncated tool call — the task is unlikely to recover on its own.</p>
        <p class="muted">Cancel cleanly + start a fresh chat session — on-disk artifacts and decisions are preserved. The agent's resume-aware re-entry picks up from where it left off.</p>
      </div>
      <div class="stream-drop-actions">
        <button type="button" class="cta-btn cta-btn-secondary stuck-wait">Wait — keep going</button>
        <button type="button" class="cta-btn stuck-cancel-fresh">Cancel & start fresh</button>
      </div>`;
    chatLog.appendChild(el);
    chatLog.scrollTop = chatLog.scrollHeight;
    _stuckBannerEl = el;
    el.querySelector(".stuck-wait")?.addEventListener("click", () => {
      // Reset the silence timer so the banner doesn't re-appear immediately.
      _pingProgress();
      if (_stuckBannerEl) {
        _stuckBannerEl.remove();
        _stuckBannerEl = null;
      }
    });
    el.querySelector(".stuck-cancel-fresh")?.addEventListener("click", () => {
      // Trigger the existing STOP-button flow (cancels via /api/chat/cancel
      // and unwinds the inflight state). Then after a short grace, start a
      // fresh chat session and auto-resubmit the standard resume kickoff.
      if (_stuckBannerEl) {
        _stuckBannerEl.remove();
        _stuckBannerEl = null;
      }
      if (chatSend && _currentInflightTaskId) {
        chatSend.click();
      }
      setTimeout(() => {
        startFreshChatSession();
        _submitResumeKickoff();
      }, 1500);
    });
  }

  function _setChatInflight(taskId) {
    _currentInflightTaskId = taskId || "";
    // Hard-disable the composer + agent picker while a task is in flight, so the
    // user can't submit a second turn or retarget the agent mid-flight. The
    // `disabled` attribute (not just pointer-events/dimming) is required —
    // pointer-events:none doesn't block keyboard input on a focused textarea.
    if (chatInput) chatInput.disabled = !!_currentInflightTaskId;
    if (chatAgentSelect) chatAgentSelect.disabled = !!_currentInflightTaskId;
    // Watchdog: start when a task arms inflight, stop when it clears.
    if (_currentInflightTaskId) {
      _startStuckWatchdog();
    } else {
      _stopStuckWatchdog();
    }
    // Body-level data attribute lets CSS gate progress-CTA action buttons
    // (Start Review, View design, etc.) and any other "primary action"
    // surfaces while a task is in flight — without each component knowing
    // about the inflight state individually. See styles.css for the
    // `body[data-inflight="1"] .progress-cta-actions-row …` rule.
    try {
      if (_currentInflightTaskId) document.body.dataset.inflight = "1";
      else delete document.body.dataset.inflight;
    } catch { /* document.body unreachable in some test envs — ignore */ }
    // Lock the chat input + agent dropdown + Send-to-SAM checkbox while a
    // task is in flight so the user can't type-and-Enter a second
    // submission, can't change the target agent mid-flight (which would
    // route the next message to a different agent without their explicit
    // intent), and can't flip the SAM-routing escape hatch on an in-
    // flight turn. `disabled` attribute is the only thing that actually
    // blocks keyboard input on a focused textarea — `pointer-events: none`
    // does NOT. STOP button stays enabled (it has its own toggle below)
    // so the user can always cancel.
    try {
      const inflight = !!_currentInflightTaskId;
      if (chatInput) chatInput.disabled = inflight;
      const _samCb = document.getElementById("chat-send-to-sam");
      if (_samCb) _samCb.disabled = inflight;
      // Dropdown: in-flight always disables. Post-flight (inflight=false),
      // defer to the checkbox state — when "Send to SAM" is ticked, the
      // dropdown stays disabled because routing goes to SAM, not the
      // named agent. Without this, completing a turn while the checkbox
      // is ticked would re-enable the dropdown and break the
      // _syncDropdownToCheckbox contract.
      if (chatAgentSelect) {
        chatAgentSelect.disabled = inflight || !!(_samCb && _samCb.checked);
      }
    } catch { /* defensive — never let a missing element break the toggle */ }
    if (!chatSend) return;
    // Always re-enable the button when we change mode — the submit handler
    // disables it during dispatch (C2 fix), and we want it clickable in
    // BOTH modes (STOP click to cancel, or SEND click for the next turn).
    chatSend.disabled = false;
    if (_currentInflightTaskId) {
      // STOP mode — black-square unicode glyph (■) + "Stop" label so screen
      // readers + a-keyboard users have something semantic. The CSS adds
      // the destructive-action tint.
      chatSend.classList.add("stop-mode");
      chatSend.setAttribute("type", "button");   // prevent form submit on click
      chatSend.setAttribute("title", "Stop the running agent task");
      chatSend.setAttribute("aria-label", "Stop");
      chatSend.innerHTML = "■ Stop";
    } else {
      chatSend.classList.remove("stop-mode");
      chatSend.setAttribute("type", "submit");
      chatSend.removeAttribute("title");
      chatSend.setAttribute("aria-label", "Send");
      chatSend.textContent = "Send";
    }
  }

  // Clear inflight ONLY if the terminating event matches the current
  // in-flight task. Prevents a stale FinalResponse from clobbering a
  // newer task's STOP state. If task_id can't be extracted from the
  // event (e.g. Error event with no task association), the caller can
  // pass null and we conservatively clear — see callers for rationale.
  function _clearChatInflightIfMatches(taskId) {
    if (!_currentInflightTaskId) return;
    if (taskId && taskId !== _currentInflightTaskId) return;
    _setChatInflight("");
  }

  // Post-cancel grace window — set when STOP succeeds. SSE updates that
  // try to adopt a *new* task_id during this window are suppressed: the
  // user said "stop", so an orchestrator auto-continuation that fires a
  // fresh task ~50ms later (observed in sam.log 2026-05-22) should NOT
  // visibly re-arm the chat. Cancel it instead. Window stays tight (5s)
  // so legitimate user-resumed dispatches after STOP aren't blocked.
  let _lastCancelTaskId = "";
  let _lastCancelAt = 0;
  const CANCEL_GRACE_MS = 5000;

  // Tracks the safety-timeout for a stuck "Stopping…" — see STOP handler.
  // Held at module scope so the SSE handler can clear it when the matching
  // CANCELED FinalResponse arrives normally.
  let _stopSafetyTimer = null;
  function _clearStopSafetyTimer() {
    if (_stopSafetyTimer) {
      clearTimeout(_stopSafetyTimer);
      _stopSafetyTimer = null;
    }
  }

  // STOP click handler — independent of form submit. Always reads
  // _currentInflightTaskId at click time so a stale closure can't fire
  // cancel on a wrong task.
  chatSend?.addEventListener("click", async (e) => {
    if (!_currentInflightTaskId) return;   // SEND mode — let the form submit
    e.preventDefault();
    const taskId = _currentInflightTaskId;
    chatSend.disabled = true;
    const prevHTML = chatSend.innerHTML;
    chatSend.innerHTML = "■ Stopping…";
    // Open the grace window IMMEDIATELY (before the network call). The
    // cancel POST can take 50–500 ms; without this, an orchestrator
    // auto-spawned task arriving inside that window slips through the
    // suppression. Cleared on catch-failure below so a failed cancel
    // doesn't leave a phantom grace open.
    const _priorCancelTaskId = _lastCancelTaskId;
    const _priorCancelAt = _lastCancelAt;
    _lastCancelTaskId = taskId;
    _lastCancelAt = Date.now();
    // I1 fix: 10s abort timeout. If /api/chat/cancel hangs (network drop,
    // idle proxy, SAM loop stuck) we'd otherwise leave the button disabled
    // forever and the user would have to reload. With the timeout, the
    // fetch throws AbortError, we hit the catch, restore the previous
    // state, and surface a hint that the cancel didn't take.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch("/api/chat/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        // 404 = task already finalized; treat as a successful stop.
        if (res.status !== 404) throw new Error(`HTTP ${res.status}`);
      }
      // Safety timeout: backend may have canceled cleanly (sam.log shows
      // `Published final CANCELED response`) but the SSE event can drop
      // before reaching the browser (process restarts, broker hiccups,
      // intermediary proxies). Without this net, the button stays on
      // "Stopping…" forever and only a reload recovers. After ~6s, if
      // _currentInflightTaskId is still the cancelled one, force-clear.
      _clearStopSafetyTimer();
      _stopSafetyTimer = setTimeout(() => {
        _stopSafetyTimer = null;
        if (_currentInflightTaskId === taskId) {
          _setChatInflight("");
          try {
            appendChatMessage(
              "agent",
              "[stop] cancel acknowledged but no finalize event arrived — UI restored.",
            );
          } catch { /* never let the safety net itself throw */ }
        }
      }, 6000);
      // We don't reset the button here — wait for the agent's FinalResponse
      // (which will carry state=canceled) or Error SSE to flip the UI back
      // to SEND via _setChatInflight(""). That way the UI matches the
      // actual SAM state instead of guessing.
    } catch (err) {
      clearTimeout(timeoutId);
      // Cancel failed — roll back the grace window so suppression doesn't
      // silently swallow tasks for a stop that never took. Restoring the
      // PRIOR markers (rather than zeroing) preserves any still-active
      // grace from an earlier successful cancel.
      _lastCancelTaskId = _priorCancelTaskId;
      _lastCancelAt = _priorCancelAt;
      chatSend.disabled = false;
      chatSend.innerHTML = prevHTML;
      const reason = err?.name === "AbortError"
        ? "cancel timed out (10s) — the agent may still be running"
        : ("cancel failed: " + (err?.message || err));
      console.error(reason);
      // Surface the failure as a chat message so the user knows to retry
      // or reload — silent disable-recovery hides the problem.
      try { appendChatMessage("agent", "[stop] " + reason); } catch {}
    }
  });

  // Helpers used by the SSE handler.
  function _inCancelGrace() {
    return _lastCancelAt && (Date.now() - _lastCancelAt) < CANCEL_GRACE_MS;
  }
  // Decide what to do with a NEW task_id (one not currently tracked as
  // inflight) that arrives via SSE while the cancel-grace window is open.
  // Returns true → caller must NOT call _setChatInflight(taskId). Two
  // cases trigger suppression:
  //   1. The id matches the just-cancelled task — late TaskStatusUpdate
  //      arriving after the safety timer cleared inflight. We must not
  //      re-arm STOP for a phantom; no need to re-issue cancel.
  //   2. Any other id during the grace window — almost certainly an
  //      orchestrator auto-continuation. Fire-and-forget cancel and
  //      swallow the inflight adoption.
  function _suppressAutoSpawnedTask(taskId) {
    if (!taskId) return false;
    if (taskId === _lastCancelTaskId) return true;     // late update for the cancelled task
    try {
      fetch("/api/chat/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId }),
      }).catch(() => {});
    } catch { /* ignore */ }
    return true;
  }

  // Wire the "Send to SAM" checkbox to gate the dropdown. While ticked,
  // the routing target is fixed to SAM_FALLBACK_AGENT — leaving the
  // dropdown live would be ambiguous about which agent the next message
  // hits. Auto-reset on dispatch (see chatForm submit handler below).
  const sendToSamCheckbox = document.getElementById("chat-send-to-sam");
  function _syncDropdownToCheckbox() {
    if (!chatAgentSelect) return;
    chatAgentSelect.disabled = !!(sendToSamCheckbox && sendToSamCheckbox.checked);
  }
  sendToSamCheckbox?.addEventListener("change", _syncDropdownToCheckbox);

  // Slash-command interceptor. When the user types `/<cmd>` as the first
  // (and typically only) non-whitespace token, we run a FE-side action
  // instead of dispatching to an agent. Anything else — including the
  // word "continue" or "stop" without a leading `/` — falls through to
  // the normal agent dispatch path. Slash commands are explicit so we
  // can never accidentally fire a UI action when the user meant to ask
  // the agent a question.
  function _handleSlashCommand(rawText) {
    const text = rawText.trim();
    if (!text.startsWith("/")) return false;
    const [cmd, ...restArr] = text.slice(1).split(/\s+/);
    const rest = restArr.join(" ").trim();
    const c = (cmd || "").toLowerCase();
    if (c === "new" || c === "fresh") {
      // Start a fresh chat session. On-disk state is preserved.
      startFreshChatSession();
      // If the user passed extra text after /new — e.g. "/new continue" —
      // submit that as the first message of the fresh session so they
      // don't have to re-type it.
      if (rest) {
        const ci = document.getElementById("chat-input");
        if (ci) {
          ci.value = rest;
          chatForm?.requestSubmit?.();
        }
      }
      chatInput.value = "";
      return true;
    }
    if (c === "stop" || c === "cancel") {
      if (_currentInflightTaskId && chatSend) {
        chatSend.click();   // delegates to the existing Stop flow
        chatInput.value = "";
      } else {
        appendChatMessage("agent", "No task is currently in flight — nothing to stop.");
        chatInput.value = "";
      }
      return true;
    }
    if (c === "help" || c === "?") {
      appendChatMessage("agent",
        "**Slash commands** (typed in this chat, processed by the WebUI — not sent to an agent):\n\n" +
        "- `/new` — start a fresh chat session (on-disk artifacts / decisions / scope progress are preserved).\n" +
        "- `/new <message>` — start a fresh session AND submit `<message>` as the first turn.\n" +
        "- `/stop` (or `/cancel`) — cancel the in-flight task (same as clicking the Stop button).\n" +
        "- `/help` — show this list.\n\n" +
        "Anything not starting with `/` is sent to the selected agent as a normal chat message.");
      chatInput.value = "";
      return true;
    }
    // Unknown slash command — let the user know rather than silently
    // forwarding it to the agent (which would just be confused by the
    // leading slash anyway).
    appendChatMessage("agent",
      `Unknown command: \`/${escapeHtml(c)}\`. Type \`/help\` to see the available commands.`);
    chatInput.value = "";
    return true;
  }

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;
    // Slash-command fast-path — runs a WebUI-side action and skips the
    // agent dispatch entirely. Falls through to the normal path when
    // the text doesn't start with `/`.
    if (_handleSlashCommand(text)) return;
    // C2 fix: disable SEND immediately so a double-click during the dispatch
    // round-trip can't fire two POSTs and produce two in-flight tasks the
    // user can't both cancel. The button stays disabled until either:
    //   * _setChatInflight(task_id) sets STOP mode (success path), or
    //   * _recoverFromSubmitError fires (dispatch failure), or
    //   * the dispatch returns without a task_id (re-enables SEND).
    if (chatSend) chatSend.disabled = true;
    const eid = currentProjectId();
    // Three sources of the agent target, in precedence order:
    //   1. _pendingDispatchAgent — one-shot override set by phase-handoff
    //      CTAs (kickoff lands on the right agent without disturbing the
    //      dropdown). Wins over everything else: "Start Discovery"
    //      always goes to SADiscoveryAgent regardless of checkbox state.
    //   2. "Send to SAM" checkbox — explicit per-message escape hatch
    //      to the stock SAM orchestrator. Auto-resets after dispatch.
    //   3. Dropdown value — the user's standing pick from the SA family.
    const pendingAgent = _pendingDispatchAgent || "";
    if (_pendingDispatchAgent) _pendingDispatchAgent = "";
    const sendToSam = !pendingAgent && !!(sendToSamCheckbox && sendToSamCheckbox.checked);
    const agent = pendingAgent
      || (sendToSam ? SAM_FALLBACK_AGENT : (chatAgentSelect?.value || ""));

    // Ensure the per-project sessionId is current and the SSE stream is live.
    if (!chatSessionId) chatSessionId = deriveChatSessionId();
    if (!chatEventSource) openSseStream(chatSessionId);

    // Auto-continue / resume kickoffs are internal orchestration — render a
    // user bubble only when the user actually typed/clicked. The thinking
    // bubble, activity pills, and recovery cards still convey what's underway.
    if (_suppressNextUserBubble || _isInternalKickoff(text)) {
      _suppressNextUserBubble = false;
    } else {
      appendChatMessage("user", text, { routedToSam: sendToSam });
    }
    chatInput.value = "";
    openThinkingBubble();

    // Wrap with worker context for SADomainAgent during an active Design run
    // (keeps the bubble showing the user's original words above).
    const body = { text: _wrapWorkerAnswer(text, agent), session_id: chatSessionId };
    if (agent) body.agent = agent;
    // Engagement context only flows to SA agents. The stock SAM
    // orchestrator has no SA knowledge / engagement-aware tools; sending
    // engagement_id pollutes its A2A header with useless context AND
    // tags any telemetry/logs as if the engagement triggered the work.
    if (eid && !sendToSam) body.engagement_id = eid;

    // One-shot semantic: untick the checkbox + re-enable the dropdown
    // so the NEXT message returns to the SA family. Reset on EVERY
    // dispatch — not just SAM-routed ones — so a phase-CTA kickoff
    // (which uses pendingAgent and ignores the checkbox) doesn't
    // leave the checkbox stuck-ticked for the next user message.
    // Done BEFORE the fetch so even a slow dispatch doesn't leave the
    // UI mis-stated.
    if (sendToSamCheckbox && sendToSamCheckbox.checked) {
      sendToSamCheckbox.checked = false;
      _syncDropdownToCheckbox();
    }

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        // 412 is the server-side phase-dispatch gate (component.py:705-746).
        // The body carries the blockers; render a useful card with a one-
        // click "Supersede & retry" instead of the generic retry hint.
        let errBody = null;
        try { errBody = await res.json(); } catch { /* not JSON */ }
        if (res.status === 412 && errBody?.blockers?.length && eid) {
          _renderBlockedDispatchCard({
            eid,
            step: errBody.step || "",
            blockers: errBody.blockers,
            hint: errBody.hint || "",
            retryBody: body,
          });
          if (chatSend) chatSend.disabled = false;
          return;
        }
        // Other failures fall through to the generic recovery path with
        // the server's error message when available.
        const msg = errBody?.error || `HTTP ${res.status}`;
        throw new Error(msg);
      }
      // Capture the task_id so STOP can cancel it. The backend returns
      // {"session_id", "task_id", "accepted": true} per component.py's
      // _chat_message handler.
      let gotTaskId = false;
      try {
        const data = await res.json();
        if (data && data.task_id) {
          _setChatInflight(data.task_id);   // flips button to STOP mode + clears disabled
          gotTaskId = true;
        }
      } catch { /* response without JSON body */ }
      // If the response had no task_id (legacy server, parse error, etc),
      // re-enable SEND so the user isn't stranded with a permanently
      // disabled button. _setChatInflight handles the success path.
      if (!gotTaskId && chatSend) chatSend.disabled = false;
    } catch (err) {
      _recoverFromSubmitError("could not dispatch: " + err.message);
    }
  });

  // Render a phase-blocked card when the server refuses a Phase: <step>
  // dispatch via 412 because open-items with affecting_step=<step> exist.
  // The card lists the blockers verbatim and offers a one-click
  // "Supersede & retry" — resolves each listed item then re-submits the
  // original chat-message body, so the user doesn't have to walk to the
  // Open Items view and resolve them by hand. "Resolve in Open Items"
  // is the safer alternative when the user wants to triage individually.
  function _renderBlockedDispatchCard({ eid, step, blockers, hint, retryBody }) {
    const items = (blockers || []).map(b => `
      <li class="phase-blocked-item">
        <code>${escapeHtml(b.id || "(no id)")}</code>
        <span>${escapeHtml(b.description || "(no description)")}</span>
      </li>`).join("");
    const card = document.createElement("div");
    card.className = "chat-msg agent stream-drop-card";
    card.innerHTML = `
      <div class="stream-drop-header">
        <span class="stream-drop-icon">⛔</span>
        <span class="stream-drop-title">Cannot dispatch <code>${escapeHtml(step)}</code> — ${blockers.length} blocking open item${blockers.length === 1 ? "" : "s"}</span>
      </div>
      <div class="stream-drop-body">
        <p>${escapeHtml(hint || "Resolve the listed open-items before dispatching this phase.")}</p>
        <ul class="phase-blocked-list">${items}</ul>
      </div>
      <div class="stream-drop-actions">
        <a class="cta-btn cta-btn-secondary" href="/projects/${encodeURIComponent(eid)}/open-items">Resolve in Open Items →</a>
        <button type="button" class="cta-btn phase-blocked-supersede-retry">Supersede &amp; retry</button>
      </div>`;
    chatLog.appendChild(card);
    chatLog.scrollTop = chatLog.scrollHeight;
    card.querySelector(".phase-blocked-supersede-retry")?.addEventListener("click", async () => {
      const btn = card.querySelector(".phase-blocked-supersede-retry");
      if (btn) { btn.disabled = true; btn.textContent = "Superseding…"; }
      try {
        for (const b of blockers) {
          if (!b.id) continue;
          await fetch(`/api/engagements/${encodeURIComponent(eid)}/open-items/${encodeURIComponent(b.id)}/resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resolution_note: `Superseded by user during ${step} retry — prior dispatch refused with 412.` }),
          });
        }
        card.remove();
        // Re-submit the original message body now that the blockers are
        // cleared. _setChatInflight will arm STOP on success.
        const res = await fetch("/api/chat/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(retryBody),
        });
        if (!res.ok) {
          const m = (await res.text()).slice(0, 200);
          _recoverFromSubmitError(`retry still refused: ${m}`);
        } else {
          try {
            const data = await res.json();
            if (data?.task_id) _setChatInflight(data.task_id);
          } catch { /* no body */ }
        }
      } catch (err) {
        if (btn) { btn.disabled = false; btn.textContent = "Supersede & retry"; }
        appendChatMessage("agent", `[error] supersede-and-retry failed: ${err.message}`);
      }
    });
  }

  // ============================================================================
  // Action handlers (inline onclick)
  // ============================================================================
  window.__resolveItem = (eid, itemId, desc) => openResolveItemModal(eid, itemId, desc || "");
  // Render-pack handler. The first arg is the clicked button element so we
  // can show a loading state on the card while the server renders — large
  // engagements with many Mermaid diagrams take 5-30s on first render
  // (server-side mmdc pre-rendering is the slow part). Subsequent renders
  // hit the freshness cache and return in <200ms.
  window.__renderPack = async (btn, eid, audience) => {
    let r, d;
    const card = btn?.closest(".export-card");
    const originalLabel = btn?.textContent;
    // Loading state — disable + show spinner. The card grows a "loading
    // bar" too so the visual feedback is obvious even outside the button.
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-loading");
      btn.innerHTML = `<span class="cta-spinner"></span><span>Rendering…</span>`;
    }
    if (card) card.classList.add("export-card-loading");
    // Read the per-card "Regenerate" checkbox — when checked, bypass the
    // freshness cache and force a full re-render. Unchecked (the default)
    // lets the backend short-circuit if nothing has changed since the
    // previous render.
    const forceCb = card?.querySelector(".export-card-force-cb");
    const force = !!forceCb?.checked;
    try {
      r = await fetch(`/api/engagements/${encodeURIComponent(eid)}/exports/render`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audience, format: "both", force }),
      });
      d = await r.json();
    } catch (e) {
      alert(`Render failed: ${e.message}`);
      _resetExportCard(btn, card, originalLabel);
      return;
    }
    // After a forced regen completes, uncheck the box so the next click
    // uses the cache again — leaving it ticked would burn time on every
    // subsequent open.
    if (force && forceCb) forceCb.checked = false;
    const url = d?.urls?.find(u => u.toLowerCase().endsWith(".html")) || d?.urls?.[0] || null;
    if (!url) {
      const detail = d?.error || "no renderer registered or audience pack not available yet";
      alert(`Couldn't render '${audience}' pack: ${detail}\n\n` +
            `If SAM was just upgraded, restart SAM so the renderer registers at boot.`);
      _resetExportCard(btn, card, originalLabel);
      return;
    }
    // If the server says the report was a cache hit, the user gets a quick
    // open. Otherwise open the freshly-rendered HTML. Either way, restore
    // the button state for the next click (a fresh render or different pack).
    _resetExportCard(btn, card, originalLabel);
    window.open(url, "_blank");
  };

  function _resetExportCard(btn, card, originalLabel) {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("is-loading");
      btn.textContent = originalLabel || "View HTML →";
    }
    if (card) card.classList.remove("export-card-loading");
  }
  // Download a specific audience pack in the requested format ("html" or "pdf").
  // Renders the file first (so it exists on disk), then opens the
  // /exports/raw/<filename> URL — PDFs trigger the browser's native download.
  window.__downloadPack = async (eid, audience, format) => {
    let r, d;
    try {
      r = await fetch(`/api/engagements/${encodeURIComponent(eid)}/exports/render`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audience, format }),
      });
      d = await r.json();
    } catch (e) {
      alert(`Render failed: ${e.message}`);
      return;
    }
    const urls = d?.urls || [];
    // Prefer the URL ending in the requested extension (.pdf or .html).
    const ext = format === "pdf" ? ".pdf" : ".html";
    const url = urls.find(u => u.toLowerCase().endsWith(ext)) || urls[0];
    if (!url) {
      const detail = d?.error || "renderer didn't produce the requested format";
      alert(`Couldn't render '${audience}' as ${format.toUpperCase()}: ${detail}`);
      return;
    }
    // For PDF, force a download via an <a download> click rather than opening.
    if (format === "pdf") {
      const a = document.createElement("a");
      a.href = url; a.download = `${audience}-report.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
    } else {
      window.open(url, "_blank");
    }
  };

  window.__downloadZip = async (eid) => {
    let r, d;
    try {
      r = await fetch(`/api/engagements/${encodeURIComponent(eid)}/exports/zip`);
      d = await r.json();
    } catch (e) {
      alert(`Download failed: ${e.message}`);
      return;
    }
    const url = d?.zip_url || null;
    if (!url) {
      const detail = d?.error || "package not assembled yet — run Blueprint first";
      alert(`Couldn't download package: ${detail}`);
      return;
    }
    window.open(url, "_blank");
  };
  window.__logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  };

  // ============================================================================
  // Live status bar (2s poll)
  // ============================================================================
  async function pollActiveStep() {
    const eid = currentProjectId();
    const bar = document.getElementById("status-bar");
    if (!eid) {
      bar.textContent = "Idle";
      bar.className = "status-bar";
      return;
    }
    try {
      const d = await fetch(`/api/engagements/${encodeURIComponent(eid)}/active-step`).then(r => r.json());
      if (d.active_agent) {
        bar.textContent = `${d.active_agent}${d.active_scope ? "/" + d.active_scope : ""} · ${d.elapsed_seconds || 0}s`;
        bar.className = "status-bar " + (d.user_waiting ? "waiting" : "busy");
      } else {
        bar.textContent = "Idle";
        bar.className = "status-bar";
      }
    } catch (e) { /* swallow */ }
  }
  setInterval(pollActiveStep, 2000);

  // Desync detection — based on SSE-stream inactivity, NOT on the
  // active-step endpoint. Reason: compute_active_step reads
  // session.active_step from meta/session.yaml, which Discovery and Domain
  // don't update. So "Idle" in the status bar is unreliable as a "no task
  // is running" signal — it'd false-positive on every multi-minute turn.
  //
  // SSE inactivity is more truthful: as long as the agent is alive, SSE
  // events flow (status updates, tool traces, tokens, intermediate text).
  // If we see >SSE_SILENCE_MS of quiet WHILE pendingAgentMsg is set, the
  // SSE channel has dropped or the task has hung silently — same UX
  // outcome, render the recovery card with a Reload button.
  let _lastSseEventAt = Date.now();
  // 240s (4 min) accommodates legitimately slow turns — Discovery's
  // brief-write turn ran ~5min today with a 116s LLM-composition quiet
  // gap, Domain's per-scope artifact turns can be similar. Earlier 90s
  // would have false-positived on both. The cost of being too generous:
  // user waits a bit longer before the recovery card appears if SSE
  // actually drops. The cost of being too aggressive: spurious "Reload"
  // prompts in the middle of a healthy turn. Favor too-generous.
  const _SSE_SILENCE_MS = 240000;
  // Soft threshold — when an agent's been quiet for >15s mid-turn but
  // SSE is still healthy, update the activity bar to "Agent is
  // thinking…" so the user sees we're still alive. This kicks in when
  // the LLM is composing a long response between tool calls. Distinct
  // from the 240s desync recovery — that's "SSE actually dropped".
  const _SSE_QUIET_MS = 15000;
  let _quietIndicatorShown = false;
  function _stampSse() {
    _lastSseEventAt = Date.now();
    // Any SSE event clears the "thinking" indicator — pill/tool-call
    // events will set their own activity-bar text. The user shouldn't
    // see "Agent is thinking…" lingering after a pill fires.
    _quietIndicatorShown = false;
  }

  // Mid-tier threshold — when we haven't seen ANY SSE traffic (data OR
  // heartbeat) for >30s, the server emits heartbeats every 15s so two
  // missed heartbeats means the TCP socket is silently dead even if
  // EventSource.readyState still reports OPEN (a known flaky-network
  // failure mode). Force-close + reopen — the EventSource will send
  // Last-Event-Id on reconnect and the server replays whatever we missed.
  const _SSE_STALE_MS = 30000;
  let _lastForceReconnectAt = 0;
  const _FORCE_RECONNECT_COOLDOWN_MS = 60000;  // don't thrash if reconnects fail

  setInterval(() => {
    if (!pendingAgentMsg) return;
    const silentFor = Date.now() - _lastSseEventAt;
    // Soft path: 15s+ quiet → show "Agent is thinking…" in the bar.
    if (silentFor >= _SSE_QUIET_MS && silentFor < _SSE_SILENCE_MS && !_quietIndicatorShown) {
      const ag = chatAgentSelect?.value || "the agent";
      const secs = Math.floor(silentFor / 1000);
      setActivityBar(`${ag} is thinking… (${secs}s)`);
      _quietIndicatorShown = true;
    }
    // Continuous update of the elapsed seconds while we're in the
    // "thinking" window, so the user sees the timer tick.
    if (silentFor >= _SSE_QUIET_MS && silentFor < _SSE_SILENCE_MS && _quietIndicatorShown) {
      const ag = chatAgentSelect?.value || "the agent";
      const secs = Math.floor(silentFor / 1000);
      setActivityBar(`${ag} is thinking… (${secs}s)`);
    }
    // Mid path: 30s+ silent (no data AND no heartbeat) → TCP probably dead
    // despite EventSource thinking it's connected. Force a fresh reconnect;
    // the server's Last-Event-Id replay buffer fills in whatever we missed.
    // Cooldown gate so we don't thrash if reconnects keep failing.
    if (silentFor >= _SSE_STALE_MS && silentFor < _SSE_SILENCE_MS) {
      const sinceReconnect = Date.now() - _lastForceReconnectAt;
      if (sinceReconnect >= _FORCE_RECONNECT_COOLDOWN_MS && chatEventSource && chatSessionId) {
        _lastForceReconnectAt = Date.now();
        setActivityBar("Reconnecting to agent stream…");
        try { chatEventSource.close(); } catch {}
        chatEventSource = null;
        openSseStream(chatSessionId);
      }
    }
    // Hard path: 240s+ quiet → SSE channel is presumed dead, render recovery.
    if (silentFor >= _SSE_SILENCE_MS) {
      _renderSseDesyncRecoveryCard();
    }
  }, 5000);  // check every 5s

  // Renders a one-shot recovery card when we detect SSE-channel desync.
  // Removes the stale thinking placeholder, shows a "result missed" card
  // with a Reload button, and clears pendingAgentMsg so the user can send
  // a fresh message without first having to refresh.
  let _desyncCardShown = false;
  function _renderSseDesyncRecoveryCard() {
    if (_desyncCardShown) return;
    _desyncCardShown = true;
    if (pendingAgentMsg) {
      try { pendingAgentMsg.el.remove(); } catch {}
      pendingAgentMsg = null;
    }
    setActivityBar(null);
    const card = document.createElement("div");
    card.className = "chat-msg agent agent-empty";
    card.innerHTML = `
      <div class="agent-empty-eyebrow">Result not received</div>
      <p class="agent-empty-body">
        The agent finished this turn but the WebUI didn't receive the
        final event — likely an SSE connection drop, a suspended tab,
        or stale cached JavaScript. The agent's work was saved
        (decisions, artifacts, status updates) — only the in-chat
        rendering was lost.
      </p>
      <p class="agent-empty-body agent-empty-hint">
        Click <strong>Reload</strong> to refresh and pick up the latest
        state from the server.
      </p>
      <div class="agent-empty-actions">
        <button type="button" class="agent-empty-cta">Reload ↻</button>
      </div>
    `;
    card.querySelector(".agent-empty-cta").addEventListener("click", () => {
      window.location.reload();
    });
    chatLog.appendChild(card);
    chatLog.scrollTop = chatLog.scrollHeight;
    // Re-arm the one-shot guard once the user navigates away or sends
    // a new message (covered by finalizeAgentBubble running on the next
    // turn) so a future desync still surfaces.
  }
  // Reset the one-shot guard whenever a turn finalizes normally — fresh
  // desyncs in future turns should still raise the card.
  const _origFinalizeForDesync = finalizeAgentBubble;
  finalizeAgentBubble = function (...args) {
    _desyncCardShown = false;
    return _origFinalizeForDesync.apply(this, args);
  };

  // Belt-and-suspenders: detect outright SSE errors and surface the same
  // card. EventSource auto-reconnects on transient drops, but if the
  // browser keeps it CLOSED we'd never get a FinalResponse — same UX
  // failure mode the poller catches, just faster.
  function _armSseErrorHandler() {
    if (!chatEventSource) return;
    chatEventSource.addEventListener("error", () => {
      // readyState 2 = CLOSED. readyState 0 = reconnecting (don't panic).
      setTimeout(() => {
        if (chatEventSource && chatEventSource.readyState === 2) {
          // Null the reference so the next submit's lazy-reopen check
          // actually fires. Without this, every subsequent turn would
          // talk to a closed stream and lose all events.
          chatEventSource = null;
          if (pendingAgentMsg) _renderSseDesyncRecoveryCard();
        }
      }, 2000);
    });
  }
  const _origOpenSse = openSseStream;
  openSseStream = function (sid) {
    _origOpenSse(sid);
    _armSseErrorHandler();
  };

  // ============================================================================
  // Helpers
  // ============================================================================
  // ============================================================================
  // Hero tile row — shared by Overview (without Activities) and Decisions (with it)
  //
  // "Activities" is the V2 name for what was called "Skills" in V1 — each entry
  // in skill-routing.yaml is an engagement activity. SAM's Agent Card still uses
  // the word "skills" for agent-advertised capabilities, but that's a separate
  // concept and stays on the SAM side.
  // ============================================================================
  function renderHeroTiles(stats, opts = {}) {
    const tiles = [];

    if (opts.statusValue) {
      const status = String(opts.statusValue).toLowerCase();
      tiles.push(`<div class="stat-tile stat-tile-status status-tile-${escapeHtml(status)}">
        <div class="stat-tile-label">Status</div>
        <div class="stat-tile-value">${escapeHtml(status)}</div>
      </div>`);
    }

    if (opts.includeActivities) {
      tiles.push(`<div class="stat-tile">
        <div class="stat-tile-label">Activities</div>
        <div class="stat-tile-value">${stats.skills_completed}/${stats.skills_total}</div>
        <div class="stat-tile-meta">${stats.skills_skipped} skipped</div>
      </div>`);
    }
    tiles.push(`<div class="stat-tile">
      <div class="stat-tile-label">Systems</div>
      <div class="stat-tile-value">${stats.connected_systems}</div>
      <div class="stat-tile-meta">${stats.producers} prod · ${stats.consumers} cons</div>
    </div>`);
    tiles.push(`<div class="stat-tile">
      <div class="stat-tile-label">Artifacts</div>
      <div class="stat-tile-value">${stats.artifacts_count}</div>
    </div>`);
    tiles.push(`<div class="stat-tile">
      <div class="stat-tile-label">Decisions</div>
      <div class="stat-tile-value">${stats.decisions_count}</div>
    </div>`);
    tiles.push(`<div class="stat-tile">
      <div class="stat-tile-label">Open items</div>
      <div class="stat-tile-value">${stats.open_items_blocking}/${stats.open_items_advisory}</div>
      <div class="stat-tile-meta">blocking/advisory</div>
    </div>`);
    // EP Prov tile removed: the top lifecycle banner's EVENT PORTAL tile
    // (strikethrough on opt-out / DONE check on success / IN_PROGRESS on
    // active provisioning) already conveys the same state. Keeping both
    // duplicated the information and crowded the stats row.

    return `<div class="tile-row">${tiles.join("")}</div>`;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, c => (
      {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]
    ));
  }
  function formatDate(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  }

  // ============================================================================
  // Intake → readable brief renderer
  //
  // Accepts the intake JSON (V1 nested shape OR V2 flat shape) and renders
  // sections matching the intake form's structure. Skip fields that are empty
  // so the layout doesn't show noise.
  // ============================================================================
  function renderIntakeBrief(intake) {
    if (!intake || typeof intake !== "object" || Object.keys(intake).length === 0) {
      return `<div class="brief-empty">
        <p class="muted">No intake recorded for this engagement yet.</p>
        <p class="muted">Was this project created before intake submission was wired? You can
        <a href="/intake/new">start a new project</a> to capture the design requirements.</p>
      </div>`;
    }

    // Normalize: pull V1-nested OR V2-flat shape into a uniform view object
    const project = intake.project || {
      name: intake.project_name, type: intake.project_type,
    };
    const landscape = intake.landscape || {
      vertical: intake.vertical, systems: intake.systems,
      existing_messaging: intake.existing_messaging,
      protocols: intake.protocols, events: intake.events,
      aggregate_volumes: intake.aggregate_volumes, schemas: intake.schemas,
    };
    const requirements = intake.requirements || {};
    const scale = intake.scale || {};
    const goals = intake.goals || {};
    const preferences = intake.preferences || {};

    return [
      _briefHeader(project, landscape),
      _briefProject(project, landscape),
      _briefSystems(landscape),
      _briefEvents(landscape),
      _briefRequirements(requirements),
      _briefScale(scale, landscape),
      _briefGoals(goals),
      _briefPreferences(preferences),
    ].filter(Boolean).join("\n");
  }

  function _isEmpty(v) {
    return v == null || v === "" ||
      (Array.isArray(v) && v.length === 0) ||
      (typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);
  }

  function _kv(label, value) {
    if (_isEmpty(value)) return "";
    return `<div class="brief-kv"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
  }

  function _briefHeader(project, landscape) {
    if (_isEmpty(project) && _isEmpty(landscape)) return "";
    const name = project.name || "Untitled project";
    const type = project.type || "—";
    const vertical = landscape.vertical;
    return `
      <div class="brief-banner">
        <div>
          <div class="brief-banner-eyebrow">Engagement brief</div>
          <h2 class="brief-banner-title">${escapeHtml(name)}</h2>
        </div>
        <div class="brief-banner-meta">
          <span class="brief-chip">${escapeHtml(type)}</span>
          ${vertical ? `<span class="brief-chip brief-chip-muted">${escapeHtml(vertical)}</span>` : ""}
        </div>
      </div>`;
  }

  function _briefProject(project, landscape) {
    const rows = [
      _kv("Project type", project.type),
      _kv("Industry vertical", landscape.vertical),
    ].filter(Boolean).join("");
    if (!rows) return "";
    return `
      <section class="brief-section">
        <h3>Project</h3>
        <dl class="brief-list">${rows}</dl>
      </section>`;
  }

  function _briefSystems(landscape) {
    const systems = landscape.systems || [];
    const existing = landscape.existing_messaging;
    if (systems.length === 0 && !existing) return "";

    const tableRows = systems.length === 0
      ? `<tr><td colspan="4" class="muted">No systems listed.</td></tr>`
      : systems.map(s => `<tr>
          <td>${escapeHtml(s.name || "—")}</td>
          <td>${escapeHtml(s.role || "—")}</td>
          <td>${escapeHtml(s.protocol || s.owner || "—")}</td>
          <td class="muted">${escapeHtml(s.notes || s.owner || "")}</td>
        </tr>`).join("");

    return `
      <section class="brief-section">
        <h3>System landscape</h3>
        ${systems.length ? `<table class="brief-table">
          <thead><tr><th>Name</th><th>Role</th><th>Protocol</th><th>Notes / Owner</th></tr></thead>
          <tbody>${tableRows}</tbody>
        </table>` : ""}
        ${existing ? `<dl class="brief-list">${_kv("Existing messaging", existing)}</dl>` : ""}
        ${landscape.protocols && landscape.protocols.length ? `
          <dl class="brief-list">${_kv("Protocols in use", (landscape.protocols || []).join(", "))}</dl>` : ""}
      </section>`;
  }

  function _briefEvents(landscape) {
    const events = landscape.events || [];
    const volumes = landscape.aggregate_volumes;
    const schemas = landscape.schemas;
    if (events.length === 0 && !volumes && !schemas) return "";

    const tableRows = events.map(e => `<tr>
      <td>${escapeHtml(e.name || "—")}</td>
      <td>${escapeHtml(e.rate || "—")}</td>
      <td>${escapeHtml(e.delivery || "—")}</td>
      <td>${escapeHtml(e.payload_format || "—")}</td>
      <td class="muted">${escapeHtml(e.payload_size || "")}</td>
    </tr>`).join("");

    return `
      <section class="brief-section">
        <h3>Events</h3>
        ${events.length ? `<table class="brief-table">
          <thead><tr><th>Name</th><th>Rate</th><th>Delivery</th><th>Payload format</th><th>Payload size</th></tr></thead>
          <tbody>${tableRows}</tbody>
        </table>` : ""}
        <dl class="brief-list">
          ${_kv("Aggregate volumes", volumes)}
          ${_kv("Existing schemas / AsyncAPI", schemas)}
        </dl>
      </section>`;
  }

  function _briefRequirements(req) {
    if (_isEmpty(req)) return "";
    const fields = [
      ["Delivery mode", req.delivery_mode],
      ["Ordering", req.ordering],
      ["Processing guarantee", req.processing_guarantee],
      ["Latency tier", req.latency_tier],
      ["Topology", req.topology],
    ];
    const rows = fields.map(([l, v]) => _kv(l, v)).filter(Boolean).join("");
    if (!rows) return "";
    return `
      <section class="brief-section">
        <h3>Requirements</h3>
        <dl class="brief-list brief-list-grid">${rows}</dl>
      </section>`;
  }

  function _briefScale(scale, landscape) {
    const fields = [
      ["Sites / regions",          scale.sites_regions],
      ["IT/OT boundary",           scale.it_ot_boundary],
      ["Growth expectations",      scale.growth_expectations],
      ["Data residency",           scale.data_residency],
      ["Operations team",          scale.operations_team],
      ["Solace / EDA experience",  scale.solace_eda_experience],
      ["Observability",            scale.observability],
      ["CI/CD",                    scale.ci_cd],
    ];
    const rows = fields.map(([l, v]) => _kv(l, v)).filter(Boolean).join("");
    if (!rows) return "";
    return `
      <section class="brief-section">
        <h3>Scale &amp; operations</h3>
        <dl class="brief-list">${rows}</dl>
      </section>`;
  }

  function _briefGoals(goals) {
    if (_isEmpty(goals)) return "";
    const fields = [
      ["Driver",                  goals.driver],
      ["Timeline",                goals.timeline],
      ["Budget constraints",      goals.budget],
      ["Team size",               goals.team_size],
      ["Organizational constraints", goals.organizational_constraints],
    ];
    const rows = fields.map(([l, v]) => _kv(l, v)).filter(Boolean).join("");
    if (!rows) return "";
    return `
      <section class="brief-section">
        <h3>Goals &amp; constraints</h3>
        <dl class="brief-list">${rows}</dl>
      </section>`;
  }

  function _briefPreferences(prefs) {
    if (_isEmpty(prefs)) return "";
    const epProvision = prefs.provision_event_portal === true || prefs.provision_event_portal === "true"
      ? "Yes — provision into the live tenant"
      : "No — design only";
    const executionMode = prefs.execution_mode || "auto";
    return `
      <section class="brief-section">
        <h3>Preferences</h3>
        <dl class="brief-list">
          ${_kv("Execution mode", executionMode)}
          ${_kv("Provision Event Portal", epProvision)}
        </dl>
      </section>`;
  }

  // ============================================================================
  // Boot
  // ============================================================================
  (async function boot() {
    const me = await loadCurrentUser();
    if (me === null) return;        // redirected to /login
    await Promise.all([loadProjects(), loadAgents()]);
    await render();        // render() calls syncChatProjectContext()
  })();
})();
