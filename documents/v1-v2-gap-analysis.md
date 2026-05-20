# V1 → V2 Gap Analysis

**Source V1:** `/Users/girivenkatesan/gitsolace/solace-architect` (Bun/Node skill-based toolkit, ~22 `solace-*` skill directories).
**Target V2:** `documents/v2spec.md` (SAM-based agentic system, 10 agents + 1 entrypoint).

**Audit date:** 2026-05-13. **Status as of:** end of edit pass applying all 🔴 critical and 🟠 important gaps.

**Status legend:**
- ✅ **Applied** — gap is now covered in v2spec.md (with section reference)
- 🔶 **Partial** — partially covered; advisory residual
- ⏸ **Deferred** — not in v2spec; queued as advisory or out-of-scope

---

## 1. Skill / agent coverage

| V1 capability | V2 spec status | Severity | Detail |
|---|---|---|---|
| `/solace-ep-provision` skill | ✅ Applied — §4.10 SAEPProvisioningAgent (new 10th agent), §5.6 `ep_designer_mcp_tools.py`, §7.1 MCP install requirement, §7.3 `test_ep_provisioning.py` | 🔴 critical | Side-effect-isolated separate agent; opt-in via `intake.preferences.provision_event_portal`; reuse-by-content-match; per-application AsyncAPI export; "never silently skip" contract |
| `/solace-executive` skill | ✅ Applied — §4.9a Executive pack ROI calculator full spec; §5.5a `report-packs.yaml` Executive pack filters | 🟠 important | 6-section ROI framework now explicit; auto-fill rules baked in |
| `/solace-diagrams` skill | 🔶 Partial — covered by SABlueprintAgent's `generate_diagrams` skill but split-rule logic (per-region splits, `*-detail.md` companion files) not explicit | 🟡 advisory | See "Advisory residuals" below |
| `/solace-help`, `/solace-projects` | ✅ Covered — orchestrator + §3.3 project_tools | — | — |

## 2. Custom tools — generators, parsers, validators, exporters

| V1 tool | V2 spec status | Severity | Detail |
|---|---|---|---|
| `scripts/build-intake-docx.py` (DOCX intake) | ✅ Dropped per Decision 16 | — | HTML form supersedes |
| `scripts/build-intake-html.py` — form + autocomplete + live preview | ✅ Applied — §5.3 `compute_intake_preview`, `integration_hub_autocomplete`; §6.1 intake-form integration | 🟠 important | Live preview matches what orchestrator will execute (single source of truth via `skill-routing.yaml`) |
| `scripts/parse-intake-docx.py` | ✅ Dropped with DOCX | — | — |
| `scripts/skill-routing.yaml` — conditional inclusion config | ✅ Applied — §5.1 `configs/skill-routing.yaml` with full operator vocabulary | 🔴 critical | Operators: equals, in, not_in, contains_any, contains_all, not_empty, empty, matches, gt/lt/gte/lte; AND across `when` clauses; `any_of` block for OR |
| `scripts/url-health-check.ts` | ✅ Applied — §5.2 `check_canonical_urls` (CI-only) | 🟠 important | Nightly CI; exits non-zero on broken URLs |
| `scripts/gen-skill-docs.ts` + multi-host generation | ✅ Out of scope | — | V2 is single SAM deployment |
| `scripts/jargon-list.json` | ✅ Applied — `grounding/jargon-list.json` + §5.2 `load_jargon_list` | 🟠 important | Every agent system prompt loads this for gloss-on-first-use |
| `scripts/detect-bump.ts`, `dev-skill.ts`, `discover-skills.ts` | ✅ Out of scope | — | V1 multi-host build tooling |

## 3. Grounding / reference data

| V1 grounding doc | V2 spec status | Severity | Detail |
|---|---|---|---|
| `solace-platform-reference.md` | ✅ §1 tree | — | — |
| `solace-canonical-sources.md` | ✅ §1 tree | — | — |
| `solace-reference-architectures.md` | ✅ §1 tree | — | — |
| `antipatterns.md` | ✅ §1 tree | — | — |
| `integration-hub-catalog.md` | ✅ §1 tree | — | — |
| `claude-instructions.md` | ⏸ Deferred | 🟡 advisory | Decide: port forward as agent-host instructions, or note superseded by agent system prompts |
| `gaps.md` runtime gap tracker | ✅ Applied — `grounding/gaps.md` + §5.2 `record_grounding_gap` | 🟠 important | Called whenever `load_grounding` or `fetch_canonical_source` fails |
| `MAINTENANCE.md` refresh manifest | ⏸ Deferred | 🟡 advisory | Operational doc — for maintainer team, not runtime |
| `tracker/*.md` dev-phase tracking | ✅ Out of scope | — | — |

## 4. Dashboard / WebUI features

| V1 feature | V2 spec status | Severity | Detail |
|---|---|---|---|
| **Live status bar** | ✅ Applied — §3.4 `compute_active_step`, §6.1 sticky banner with 2s poll | 🟠 important | — |
| **10s polling with scroll/TOC preservation** | 🔶 Partial — §6.1 mentions polling discipline but UI-state preservation light | 🟡 advisory | Frontend implementation detail; may be left to implementor |
| **Right-hand "On this page" TOC** | 🔶 Partial — §6.1 notes for Overview/Artifacts/Export only, not universal | 🟡 advisory | Could generalize to all 6 views |
| **STATUS_RANK precedence dedup** | ✅ Applied — §3.4 `compute_overview_stats` spec | 🟠 important | complete > in-progress > partial > interrupted > skipped > blocked; newest-`started_at` wins on tie |
| **Skip-reason map** | ✅ Applied — `compute_overview_stats.skip_reasons` output | 🟡 advisory→covered | Reasons sourced from `skill-routing.yaml.skip_reason` |
| **Effective-skipped logic** | ✅ Applied — §3.4 spec explicit | 🟠 important | Intake-gated steps count as skipped, not pending |
| **Theme toggle (dark/light) with Mermaid re-theming** | 🔶 Partial — toggle in §6.1; Mermaid re-theming not specced | 🟡 advisory | — |
| **Full ROI calculator** (5 sliders, combined scenario, auto-fill rules) | ✅ Applied — §4.9a full spec; §7.3 `test_roi_calculator.py` | 🟠 important | 4 auto-fill rules: V1=90%×C1, V2=80%×C2, V4=100%×C4, V6=95%×C3 |
| **"Copy raw source" buttons per artifact** | ⏸ Deferred | 🟡 advisory | Trivial frontend port |
| **Cross-reference links** (xref, skillLink, artRefLink) | ✅ Applied — §5.5b anchor schema | 🟠 important | `#grp-{group}`, `#art-{path-slug}`, `#decision-{D}`, `#finding-{F}`, `#open-item-{Q}`, `#diagram-{name}` |
| **Recommended-next-step inference** | ✅ Applied — `compute_overview_stats.recommended_next_step` | 🟡 advisory→covered | Derived from skill-routing + completed_steps + open_items |

## 5. Intake / export formats

| V1 capability | V2 spec status | Severity | Detail |
|---|---|---|---|
| DOCX intake | ✅ Dropped per Decision 16 | — | — |
| Markdown intake template (`/solace-intake --template` Markdown option) | ⏸ Deferred | 🟡 advisory | HTML + YAML now cover offline use; Markdown could be added |
| `/solace-intake --export` (generate YAML FROM a completed project) | ⏸ Deferred | 🟠 important *(was)* | Useful for replay/handoff; not added in this pass — see "Advisory residuals" |
| Intake "Source context import" (copy from another project's brief) | ⏸ Deferred | 🟡 advisory | Would extend SADiscoveryAgent interview |
| `feedback.yaml` per project + IMPROVEMENTS.md loop | ⏸ Deferred | 🟡 advisory | Phase-2 candidate |
| `scripts/report-packs.yaml` (audience-pack filters) | ✅ Applied — `configs/report-packs.yaml` §5.5a; §7.3 `test_report_packs_isolation.py` | 🔴 critical | Per-pack `dirs`/`files`/`globs`/`top_sections`/`decision_skills`/`finding_skills`/`include_roi_calculator` |

## 6. CLI commands

| V1 command | V2 spec status | Severity |
|---|---|---|
| `bun run build` / `gen:skill-docs` | ✅ N/A — V2 not template-based | — |
| `bun run skill:check` | ✅ Replaced by `test_agent_definitions.py` | — |
| `bun run url:check` | ✅ Applied — §5.2 `check_canonical_urls` | 🟠 important |
| `bun run dashboard` / `intake` | ✅ Covered by WebUI entrypoint routes | — |
| `./setup` / `./uninstall` | ✅ Replaced by `sam init` + `sam run` | — |

## 7. MCP servers / external integrations

| V1 integration | V2 spec status | Severity | Detail |
|---|---|---|---|
| **Solace Event Portal Designer MCP** | ✅ Applied — §4.10 SAEPProvisioningAgent + §5.6 wrappers + §7.1 install requirement | 🔴 critical | Optional dep, only required when EP provisioning is opted in |
| **WebFetch for runtime grounding** | ✅ Applied — §5.2 `fetch_canonical_source` with docs.solace.com allowlist | 🟠 important | — |

## 8. Testing infrastructure

| V1 test | V2 spec status | Severity |
|---|---|---|
| `skill-terminology.test.ts` | ✅ §7.3 `test_terminology.py` | — |
| `skill-structure.test.ts` | ✅ §7.3 `test_agent_definitions.py` | — |
| `skill-token-budget.test.ts` | ✅ §7.3 `test_token_budgets.py` (40K per agent, 200K total) | 🟠 important |
| `report-packs.test.ts` (isolation) | ✅ §7.3 `test_report_packs_isolation.py` | 🟠 important |
| `ep-provision-gating.test.ts` | ✅ §7.3 `test_ep_provisioning.py` | 🔴 critical (paired with EP gap) |
| `test/fixtures/scenarios.ts` (3 patterns) | ✅ §7.4 three fixtures (bank chat, market data, hybrid IT/OT) | 🟠 important |

## 9. Cross-cutting: logging, error handling, retry, telemetry, observability

| V1 cross-cutting concern | V2 spec status | Severity | Detail |
|---|---|---|---|
| **Per-skill timing instrumentation** | ✅ Applied — §5.1 `record_step_timing` (wall_sec / execution_sec / user_wait_sec / per_question / per_substep) | 🟠 important | Sole input for compute_timeline + compute_stats_summary |
| **Confusion Protocol** | ✅ Applied — §4.1 system prompt item 10 | 🟠 important | Recursively in SADomainAgent + reviewers |
| **Context-Health soft directive** | ✅ Applied — §4.1 system prompt item 11 | 🟡 advisory→covered | — |
| **Completion Status Protocol** | ✅ Applied — §4.1 system prompt item 9 + §5.1 `handle_step_failure` mapping | 🟠 important | DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT |
| **Artifact Validation hook** | 🔶 Partial — §3.1 `write_artifact` runs scans but sub-checks not enumerated as structured outputs | 🟡 advisory | — |
| **Resume / Restart / Review semantics** | ✅ Applied — §4.1 system prompt item 8b | 🟠 important | — |
| **Project warnings on misuse** | ⏸ Deferred | 🟡 advisory | E.g., warn if non-discovery skill invoked without an active project |
| **Path-traversal guard** | ✅ Applied — §6.1 spec + §7.3 `test_path_traversal.py` | 🟠 important | `safe_artifact_path(engagement_id, name)` helper |
| **No-cache headers on /api/\*** | ✅ Applied — §6.1 + Decision 52 | 🟡 advisory→covered | `Cache-Control: no-store` |

## 10. Other / cross-cutting

| V1 concept | V2 spec status | Severity |
|---|---|---|
| `feedback.yaml` → `IMPROVEMENTS.md` loop | ⏸ Deferred | 🟡 advisory |
| `projects/<slug>/feedback.yaml` | ⏸ Deferred | 🟡 advisory |
| CHECKPOINT_MODE = continuous | ✅ N/A | — |
| Project status display ("Recommended next") | ✅ Applied — `compute_overview_stats.recommended_next_step` | 🟡 advisory→covered |
| Project compare / archive subcommands | 🔶 Partial — archive applied (§3.3); compare not | 🟡 advisory |

---

## Deliberate divergences (V2 design choice, not a gap)

1. **Context threading** — V1: skills passively read shared state. V2: SAOrchestratorAgent actively curates per-task payloads with `relevant_decisions` and `artifacts_to_read` (§4.1, Decision 2).
2. **D-numbering** — V1: D1 resets per skill invocation. V2: D1, D2, … global across the engagement (§3.2). Downstream tooling that grepped V1's per-skill D-numbers will need updating.
3. **Finding-to-open-item bridging** — V1: deferred findings stay in `decisions.yaml` with `action: deferred`. V2: deferred findings also create an `open-item` with source="review-deferred" (§3.2). Cleaner separation of "what was decided" from "what's still open."

---

## Advisory residuals

### Tier A — applied in follow-up pass (3 items)

1. ✅ **`/solace-intake --export` mode** — Decision 53; new `export_intake_from_project` tool + REST endpoint `/engagements/{id}/intake/export`
2. ✅ **`/solace-diagrams` split-rule logic** — Decision 55; split rules now explicit per diagram type, plus `*-detail.md` companion files
3. ✅ **Intake "Source context import"** — Decision 54; new `import_source_context` tool + SADiscoveryAgent interview offers it as the first step if other projects exist

### Tier B — applied in follow-up pass (4 items)

4. ✅ **Theme-toggle Mermaid re-theming** — Decision 56; Mermaid re-initializes with new theme vars on toggle
5. ✅ **"Copy raw source" buttons per artifact** — Decision 57; every preview shows a Copy button
6. ✅ **Universal "On this page" TOC** — Decision 58; right-hand TOC now on all 6 dashboard views
7. ✅ **Structured write_artifact validation outputs** — Decision 59; separate violation lists per check

### Tier C — review pass outcomes

| # | Item | Outcome |
|---|---|---|
| 8 | `solace-grounding/claude-instructions.md` | ✅ **Decision recorded** — Decision 60: superseded by per-agent system prompts (§4.1–4.10) |
| 9 | `MAINTENANCE.md` operational doc | ✅ **Decision recorded** — Decision 61: Phase 2 deliverable outside v2spec.md |
| 10 | 10s polling UI-state preservation detail | ⏸ **Already covered** — §6.1 refresh discipline references V1's algorithm; frontend implementation concern |
| 11 | Markdown intake template option | ✅ **Applied** — Decision 62: `render_intake_markdown` tool + `GET /api/intake/download-markdown` route |
| 12 | `feedback.yaml` per project + IMPROVEMENTS.md loop | ✅ **Half-applied** — Decision 63: schema + `record_feedback`/`read_feedback` tools + `POST /api/feedback` route; cross-project aggregation pipeline explicitly deferred to Phase 2 |
| 13 | Project warnings on misuse | ✅ **Applied** — Decision 64: SAOrchestratorAgent system prompt item 12 (warn on no-active-project, missing brief, overwrite, gated-off step) |
| 14 | Project compare command | ⏸ **Deferred** — Decision 65: niche power-user feature; revisit if real users ask |

---

## Summary

**🔴 Critical gaps:** 3 found, all applied.
**🟠 Important gaps:** ~15 found, all applied.
**🟡 Advisory gaps:** 14 found, **10 applied or recorded** (7 Tier A+B + 3 Tier C), 4 explicitly deferred or already-covered.

v2spec.md is **~2510 lines** after Tier A + B + C (up from 1160 baseline, +1350 lines). The V2 spec now covers everything V1 does as a runtime capability, plus all advisory polish that users would notice. Genuinely deferred items: project-compare command, full feedback aggregation pipeline, 10s polling micro-detail. All other V1 capabilities are spec'd.
