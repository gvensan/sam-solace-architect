# sam-solace-architect

Solace Architect V2 — a family of [Solace Agent Mesh (SAM)](https://github.com/SolaceLabs/solace-agent-mesh) plugins that walk an architect from a business problem to a deployable event-driven architecture blueprint on Solace.

**This repo is the development monorepo.** Plugins are distributed individually via the [Solace community plugins registry](https://github.com/solacecommunity/solace-agent-mesh-plugins); the shared library `solace-architect-core` is published to PyPI.

## Layout

```
sam-solace-architect/
├── documents/                           # Spec, gap analysis, build plan, plugin-contribution checklist
├── solace-architect-core/               # Shared PyPI library — tools, schemas, grounding, configs, callbacks
├── plugins/                             # 11 SAM plugin sources (10 agents + 1 entrypoint)
│   ├── solace-architect-orchestrator/        # SAOrchestratorAgent — sequences the lifecycle
│   ├── solace-architect-discovery/           # SADiscoveryAgent — intake + reference-architecture matching
│   ├── solace-architect-domain/              # SADomainAgent — 9-scope architecture design
│   ├── solace-architect-reviewer-architect/  # SAArchitectReviewerAgent
│   ├── solace-architect-reviewer-developer/  # SADeveloperReviewerAgent
│   ├── solace-architect-reviewer-ops/        # SAOpsReviewerAgent
│   ├── solace-architect-reviewer-security/   # SASecurityReviewerAgent
│   ├── solace-architect-validation/          # SAValidationAgent — requirement tracing + antipattern scan
│   ├── solace-architect-event-portal/        # SAEventPortalAgent — opt-in live Event Portal provisioning (MCP-backed)
│   ├── solace-architect-blueprint/           # SABlueprintAgent — narrative + runbook + 5 audience packs
│   └── solace-architect-webui-entrypoint/    # Dashboard + REST + intake form + auth
├── sam/                                 # Local SAM project for development (configs/, .env)
├── test-harness/                        # End-to-end test fixtures (not distributed)
└── tests/                               # Cross-plugin integration tests
```

## Lifecycle phases

Engagement state flows top-to-bottom; each phase produces YAML/Markdown/Mermaid artifacts under `users/<uid>/<engagement>/<scope>/`.

| Phase | Owner | Output |
|---|---|---|
| Intake | WebUI entrypoint | `discovery/intake.json` (lossless) + `discovery/intake.md` + `discovery/discovery-brief.yaml` (normalized) |
| Discovery | `SADiscoveryAgent` | refines brief, surfaces blocking open-items, picks reference-architecture pattern |
| Design | `SADomainAgent` | 9 scopes — topic-design, broker-select, protocol-select, integration, mesh-design, ha-dr, sam-design, event-portal model, migration |
| Review | 4 reviewers (orchestrator fan-out) | one `reviews/<role>-review.md` per role + findings recorded with severity |
| Validation | `SAValidationAgent` | requirements traceability matrix + antipattern scan; gates the next step with DONE / DONE_WITH_CONCERNS / BLOCKED |
| Event Portal *(opt-in)* | `SAEventPortalAgent` | live Event Portal objects (domains → schemas → events → applications) + AsyncAPI exports via the EP Designer MCP server. Runs only when `preferences.provision_event_portal: true` and `SOLACE_API_TOKEN` is set. |
| Blueprint | `SABlueprintAgent` | architecture narrative, ops runbook, mermaid diagrams, 5 audience packs (Blueprint, Executive, Admin & Ops, Security, Developers), engagement ZIP |

Each agent's `config.yaml` carries the full prompt and tool list; consult per-plugin READMEs for the rubrics, scopes, and outputs they own.

## Documents

| File | Purpose |
|------|---------|
| [`documents/v2spec.md`](documents/v2spec.md) | Complete design spec — single source of truth for agent contracts, schemas, and lifecycle. |
| [`documents/v1-v2-gap-analysis.md`](documents/v1-v2-gap-analysis.md) | V1 → V2 feature parity audit. |
| [`documents/v2-build-plan.md`](documents/v2-build-plan.md) | Phased build plan. |
| [`documents/contributable-plugin-checklist.md`](documents/contributable-plugin-checklist.md) | Pre-PR checklist for community-plugins releases. |

## Quick start (development)

```bash
# 1. Install the shared core library
pip install -e ./solace-architect-core/

# 2. Install all 10 agent plugins + the entrypoint, editable
for p in orchestrator discovery domain \
         reviewer-architect reviewer-developer reviewer-ops reviewer-security \
         validation event-portal blueprint \
         webui-entrypoint; do
  pip install -e "./plugins/solace-architect-${p}/"
done

# 3. Configure + run the local mesh
cd sam/
cp ../test-harness/.env.example .env   # then edit broker + LLM credentials
sam run
```

Browse to `http://localhost:9080`, sign up (first signup = admin), and start an engagement from the dashboard's intake form. See [`plugins/solace-architect-webui-entrypoint/README.md`](plugins/solace-architect-webui-entrypoint/README.md) for env var reference, auth modes, and troubleshooting.

## Required env vars (summary)

The entrypoint and agents share one set of env vars — full reference is in [`plugins/solace-architect-webui-entrypoint/README.md`](plugins/solace-architect-webui-entrypoint/README.md#configure).

| Variable | Used by | Purpose |
|---|---|---|
| `NAMESPACE` | all | A2A topic namespace. Fails loud if unset. |
| `SOLACE_BROKER_URL` / `_USERNAME` / `_PASSWORD` / `_VPN` | all | Broker client credentials (never SEMP/admin). |
| `LLM_SERVICE_GENERAL_MODEL_NAME` / `_ENDPOINT` / `_API_KEY` | all agents | LiteLLM-compatible model spec. |
| `SA_STORAGE_ROOT` | core | Engagement artifact root (defaults to `/tmp/sa-artifacts`). |
| `SOLACE_API_TOKEN` | event-portal *(opt-in)* | Solace Cloud token with Designer Read+Write scope. |
| `WEBUI_PORT` / `_HOST` / `_REQUIRE_AUTH` / `_ENTRYPOINT_ID` | entrypoint | HTTP listener + auth toggle. |

## Contribution flow

Each plugin is independently versionable and contributable.

1. Edit a plugin under `plugins/<name>/`.
2. Bump its `version` in `pyproject.toml`.
3. Run the cross-plugin test suite (`pytest tests/`) and the plugin's own tests.
4. Open a PR to [`solacecommunity/solace-agent-mesh-plugins`](https://github.com/solacecommunity/solace-agent-mesh-plugins) with the plugin's folder.

`solace-architect-core` releases independently to PyPI. The pre-PR checklist lives in [`documents/contributable-plugin-checklist.md`](documents/contributable-plugin-checklist.md).

## Status

The full V2 lifecycle is wired end-to-end: Intake → Discovery → Design → Review (4-way fan-out) → Validation → opt-in Event Portal provisioning (MCP-backed) → Blueprint (HTML + PDF audience packs with ROI calculator + Mermaid pre-rendering). The remaining backlog tracks per-feature polish; consult [`documents/v2-build-plan.md`](documents/v2-build-plan.md) for the canonical phase list.

## License

Apache 2.0.
