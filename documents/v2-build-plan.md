# Solace Architect V2 — Build Plan

**Source of truth:** `documents/v2spec.md` (2700+ lines). This plan is a tactical roadmap from "spec done" to "plugins contributed upstream."

**Distribution target:** [solacecommunity/solace-agent-mesh-plugins](https://github.com/solacecommunity/solace-agent-mesh-plugins) — 10 agent plugins + 1 entrypoint plugin (SAM's "entrypoint" is the renamed resource type formerly known as "gateway" — see v2spec §8 Decision 74), plus `solace-architect-core` to PyPI.

---

## Phase 0 — Repo scaffolding (1–2 days)

**Goal:** repo structure matches §1; empty plugin folders pass `pip install -e .`.

| Step | Output |
|------|--------|
| 1 | `solace-architect-core/` package with empty `src/solace_architect_core/`, `pyproject.toml`, `README.md` |
| 2 | `plugins/<name>/` for all 11 plugins with skeleton `config.yaml`, `pyproject.toml`, `src/`, `README.md` |
| 3 | `test-harness/` SAM project with `pyproject.toml`, `.env.example`, README |
| 4 | `documents/` already populated (v2spec, gap-analysis, this plan) |
| 5 | `tests/` skeleton with `pytest` runner |
| 6 | Top-level `README.md` describing the monorepo layout and contribution flow |
| 7 | CI skeleton: lint (ruff), type-check (mypy), test (pytest) — runs per-plugin |

**Exit criterion:** `pip install -e ./solace-architect-core/` succeeds; `pip install -e ./plugins/solace-architect-orchestrator/` succeeds (with empty code).

---

## Phase 1 — `solace-architect-core` library (1 week)

**Goal:** every shared tool, schema, grounding doc, and default config in place. No agents yet.

| Order | Build | Why first |
|---|---|---|
| 1 | Vendor grounding docs into `solace-architect-core/src/solace_architect_core/grounding/` | Every agent reads this; can't run without it |
| 2 | Default configs: `branding.yaml`, `skill-routing.yaml`, `report-packs.yaml` | Static enough to build first |
| 3 | Schemas: open-items, projects, feedback, provisioned, decisions, findings (Pydantic or dataclasses) | Used everywhere |
| 4 | Shared tools (§3 + §5) — `artifact_tools`, `decision_tools` (incl. open-items + feedback), `session_tools`, `workflow_tools` (incl. `record_step_timing`), `grounding_tools` (incl. `load_jargon_list`, `fetch_canonical_source`, `record_grounding_gap`), `validation_tools`, `intake_tools` (incl. `compute_intake_preview`, `export_intake_from_project`, `import_source_context`, `render_intake_markdown`), `project_tools`, `dashboard_tools` (incl. `compute_active_step`, STATUS_RANK dedup, effective-skipped) | No LLM calls; pure plumbing; testable in isolation |
| 5 | ~~`ep_designer_mcp_tools` skeleton~~ — superseded by direct MCP integration (`tool_type: mcp`) in `solace-architect-event-portal/config.yaml` after Path A consolidation. No Python wrapper layer in `solace-architect-core`. | — |
| 6 | `blueprint_tools` skeleton — `render_audience_pack` calling into the report-generator (which lives in the blueprint plugin per §10) | The tool dispatches into the plugin's renderer |
| 7 | Unit tests: `test_tools.py`, `test_skill_routing.py` (operator vocabulary), `test_token_budgets.py` skeleton | — |

**Exit criterion:** `pytest tests/test_tools.py tests/test_skill_routing.py` passes. PyPI release readiness check (`python -m build` produces a valid wheel).

---

## Phase 2 — Vertical slice (2 weeks)

**Goal:** prove the agentic flow with one minimal end-to-end path. **Resist building breadth here.**

**The slice:** `orchestrator → discovery → domain (topic-design scope only) → blueprint (Blueprint pack HTML only)`. Skip reviewers, validation, audience packs other than Blueprint, PDF, WebUI.

| Step | Build |
|---|---|
| 1 | `solace-architect-orchestrator` plugin: system prompt (port from V1 `/solace-plan`), Agent Card, tool list, `config.yaml`, `pyproject.toml` declaring `solace-architect-core` dep |
| 2 | `solace-architect-discovery` plugin: system prompt (port from V1 `/solace-discovery`), interview flow with source-context import skipped for slice |
| 3 | `solace-architect-domain` plugin: system prompt restricted to topic-design scope for now |
| 4 | `solace-architect-blueprint` plugin: scaffolded; renders ONLY the Blueprint pack HTML (no PDF, no other packs) |
| 5 | Port V1's HTML report generator INTO `solace-architect-blueprint/src/solace_architect_blueprint/report_generator/` (templates, CSS, JS) — Blueprint pack only |
| 6 | Minimal REST surface in `solace-architect-webui` plugin: just `POST /engagements`, `GET /artifacts/{name}`, `POST /exports/render` |
| 7 | Test-harness wired up; install all 4 agent plugins + webui editable; `sam run` |
| 8 | Bank chat fixture through REST → produces `topic-taxonomy.yaml` + `blueprint.html` |

**Exit criterion:** `curl -X POST http://localhost:8080/api/engagements -d @bank_chat_agent.yaml` produces a valid Blueprint pack HTML. **This is the "are we on the right track?" milestone.** Stop and review with stakeholders before continuing to Phase 3.

---

## Phase 3 — Breadth (2–3 weeks; parallelizable)

**Goal:** all 9 non-opt-in agents and all 5 audience packs.

Sequenced for dependency, but most can parallelize across developers:

| Track | Build | Owner suggestion |
|---|---|---|
| Domain scopes | Remaining 8 design scopes in `solace-architect-domain` (broker-select → protocol-select → mesh-design → ha-dr → migration → integration → event-portal → sam-design) | Solace-expert dev |
| Reviewers | 4 reviewer plugins (architect/developer/ops/security) | Generalist devs; same template across all 4 |
| Validation | `solace-architect-validation` plugin | Solace-expert dev (depends on reviewers being done) |
| Audience packs | Extend `solace-architect-blueprint` to all 5 packs (Executive incl. ROI calculator, Admin & Ops, Security, Developers) | Frontend-leaning dev |
| PDF rendering | WeasyPrint integration in `solace-architect-blueprint` | Same dev as audience packs |
| Zip export | `assemble_zip` tool in core | Generalist |
| Tests | Wire up `test_report_packs_isolation.py`, `test_roi_calculator.py`, `test_path_traversal.py`, `test_canonical_urls.py`, and EP opt-in semantics in `plugins/solace-architect-webui-entrypoint/tests/test_routes.py` | QA / generalist |

**Exit criterion:** Full bank chat fixture runs end-to-end through REST entrypoint, producing all 5 audience packs (HTML + PDF) + zip. All non-EP-provisioning tests pass.

---

## Phase 4 — WebUI (2 weeks; parallel with late Phase 3)

**Goal:** dashboard parity with V1 screenshots, served by `solace-architect-webui`.

| Step | Build |
|---|---|
| 1 | Static shell + chat surface (HTTP SSE) |
| 2 | 6 dashboard views (Overview, Timeline, Decisions, Open Items, Artifacts, Stats, Export) |
| 3 | HTML intake form (Save/Load YAML, Markdown download, live skill-routing preview, Integration Hub autocomplete) |
| 4 | Project switcher sidebar + create-new flow |
| 5 | Live status bar (2s poll), dark-mode toggle (with Mermaid theme re-init), version stamp |
| 6 | In-chat artifact previews (Mermaid SVG inline, collapsible YAML/Markdown blocks) |
| 7 | Copy-raw-source buttons on every artifact preview |
| 8 | Path-traversal guard wired into every artifact endpoint |
| 9 | `Cache-Control: no-store` on `/api/*` |

**Exit criterion:** Architect can run a full engagement from the browser without touching the REST API.

---

## Phase 5 — Provisioning (1 week)

**Goal:** opt-in EP provisioning works against a real Solace Cloud tenant.

| Step | Build |
|---|---|
| 1 | `solace-architect-event-portal` plugin: dual-mode system prompt (direct query + lifecycle phase), opt-in gate, validation gate, MCP tenant probe |
| 2 | EP Designer MCP loaded directly via `tool_type: mcp` (no Python wrapper layer); MCP tools (`getApplicationDomains`, `createApplicationDomain`, `createSchema`, `createSchemaVersion`, `createEvent`, `createEventVersion`, `createApplication`, `createApplicationVersion`, `getAsyncApiForApplicationVersion`, …) auto-discovered from the upstream OpenAPI-driven FastMCP manifest |
| 3 | `provisioned.yaml` state recording + `provisioning-report.md` summary generation |
| 4 | EP opt-in/halt contract covered in `plugins/solace-architect-webui-entrypoint/tests/test_routes.py::test_intake_preview_returns_routing_decision` (opt-in skips when `provision_event_portal=false`) + the agent prompt's pre-flight gates (MCP-unavailable halt, never silently skip) |
| 5 | README documenting EP Designer MCP install + `SOLACE_API_TOKEN` setup |

**Exit criterion:** Bank chat fixture with `preferences.provision_event_portal: true` provisions into a Solace Cloud dev tenant without errors. Three-way contract tests pass.

---

## Phase 6 — Hardening + integration tests (1 week)

| Step | Build |
|---|---|
| 1 | Three reference-architecture fixtures green: bank chat (Pattern 1), market data (Pattern 2), hybrid IT/OT (Pattern 3) |
| 2 | `test_e2e_bank_chat.py`, `test_e2e_market_data.py`, `test_e2e_hybrid_it_ot.py` |
| 3 | Token-budget CI enforced (40K per agent, 200K total) |
| 4 | Forbidden-terminology CI enforced |
| 5 | Audience-pack isolation tests green |
| 6 | Per-plugin READMEs polished |
| 7 | Top-level repo README with install instructions for end users |

**Exit criterion:** All tests in `tests/` pass on a clean CI run. Documentation is end-user-readable.

---

## Phase 7 — Contribute upstream (1–2 weeks, may run in parallel with team review)

| Step | Build |
|---|---|
| 1 | Publish `solace-architect-core` v0.1.0 to PyPI |
| 2 | Open 11 PRs to `solacecommunity/solace-agent-mesh-plugins`, one per plugin folder |
| 3 | Address PR feedback from Solace maintainers |
| 4 | Get accepted plugins listed in `sam plugin catalog` |
| 5 | Announce in Solace Community |

**Exit criterion:** All 11 plugins live in the community registry; anyone can `sam plugin add solace-architect-<name>`.

---

## Dependency map

```
Phase 0 ── Phase 1 (core lib) ──┬── Phase 2 (vertical slice) ──┬── Phase 3 (breadth) ───┐
                                │                                │                         │
                                │                                └── Phase 4 (WebUI) ─────┤
                                │                                                          │
                                └─────────── Phase 5 (provisioning) ──────────────────────┤
                                                                                           │
                                                                                           ├── Phase 6 (hardening)
                                                                                           │
                                                                                           └── Phase 7 (contribute)
```

Phases 3, 4, and 5 can run in parallel once the Phase-2 vertical slice proves the agent contract works.

---

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| **LLM cost during dev** | High | Use cheaper model in dev (Sonnet → Haiku); full Sonnet runs only in nightly CI. Cache LLM responses in fixtures where possible |
| **SAM/A2A learning curve** | Medium | Phase 2 (vertical slice) is the team's "do we understand SAM?" milestone. Keep it small. Iterate fast |
| **V1 report generator port surprises** | Medium | Port early in Phase 2 (not Phase 3). Snapshot-test against V1's actual HTML output. Don't rewrite — adapt minimally |
| **Token budget creep** | Medium | Run `test_token_budgets.py` from Day 1 of Phase 2. Agent prompts can grow fast |
| **EP Designer MCP install friction** | Medium | Phase 5 is the only phase that needs it. Document install carefully. Plugin halts cleanly when MCP unavailable |
| **Multi-architect concurrency edge cases** | Low | Last-write-wins is fine for Phase 1; document soft-warning UX clearly |
| **Community-repo PR acceptance friction** | Medium | Read existing accepted PRs (tavily, send-grid) before opening ours. Match their style. Engage Solace maintainers early |
| **`solace-architect-core` versioning churn** | Low-Medium | Semver discipline from v0.1.0. Plugin pyproject.toml pins major version, accepts minor/patch |

---

## Recommended team

For a 4-person team running the above ~10–12 weeks:

- **1 Solace-expert dev** (Senior architect with EDA depth) — owns Domain scopes, Validation, Provisioning
- **1 backend dev** — owns Core library, Orchestrator, Reviewers, Blueprint backend
- **1 frontend dev** — owns WebUI dashboard, intake form, audience-pack templates (port from V1)
- **1 QA / generalist** — owns test harness, CI, snapshot tests, fixtures, docs

Solo developer: ~6–9 months realistic. Can compress by reducing Phase-3 breadth (skip 1–2 reviewer perspectives initially).

---

## What this plan defers

- Phase 2 of: feedback aggregation pipeline (rollup → IMPROVEMENTS.md), per-engagement OIDC identity, dark-mode per-user persistence, git-push delivery, email/Slack delivery, project-compare command, PDF export of architecture.md beyond audience packs

All are tracked in `documents/v1-v2-gap-analysis.md` and `documents/v2spec.md` §8 (Phase 2 deferrals row).
