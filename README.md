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

## Getting started (fresh clone)

The fast path — one script does the whole bootstrap:

```bash
git clone https://github.com/gvensan/sam-solace-architect.git
cd sam-solace-architect
./test-harness/bootstrap.sh
```

`bootstrap.sh` verifies prerequisites, clones the **plugins** subrepo into `./plugins/` (it lives in a separate git repo — see below), editable-installs `solace-architect-core` + all 12 plugins, runs `sam init` against `./sam/`, registers every plugin as a SAM component, and seeds `sam/.env`. The script is idempotent — re-run it any time to refresh installs after upstream changes.

After it finishes, you still need to:
1. Edit `sam/.env` and fill in `LLM_SERVICE_API_KEY` + your broker credentials (the file is pre-seeded with sensible localhost defaults).
2. Have a Solace broker reachable. Local Docker option:
   ```bash
   docker run -d --name=solace-pubsubplus \
     -p 8008:8008 -p 8080:8080 -p 55555:55555 \
     --shm-size=1g --env username_admin_globalaccesslevel=admin \
     --env username_admin_password=admin \
     solace/solace-pubsub-standard:latest
   ```
3. Start the mesh:
   ```bash
   cd sam && sam run
   ```
4. Browse to `http://localhost:9080`. The first signup becomes admin.

### Prerequisites the script checks for you

| Tool | Version | What for |
|---|---|---|
| Python | 3.11+ | All plugins + core. |
| `pip` | — | Editable installs. |
| `sam` CLI | — | `pip install solace-agent-mesh`. The script warns if missing and skips the SAM-project step. |
| Node.js + npm | optional | Only needed if you want to *edit* the visualizer (`visualizer-src/`); the built bundle ships pre-built so running needs no Node. |
| `uvx` | optional | `pip install uv` — needed by `SAEventPortalAgent` (launches the EP Designer MCP server via stdio). |
| `weasyprint` + native libs | optional | For Blueprint PDF export. HTML works without it. |
| `mmdc` (`npm i -g @mermaid-js/mermaid-cli`) | optional | For pre-rendered Mermaid diagrams in PDFs. |

### Manual path (if you'd rather understand each step)

The plugins live in a separate git repo (`sam-solace-architect-agents`) so they can be contributed independently to the [Solace community plugins registry](https://github.com/solacecommunity/solace-agent-mesh-plugins). The monorepo's `.gitignore` excludes `plugins/`, so a fresh clone has an empty `plugins/` directory until you populate it:

```bash
# 1. Clone the plugins subrepo
git clone https://github.com/gvensan/sam-solace-architect-agents.git plugins

# 2. Install the shared core library
pip install -e ./solace-architect-core/

# 3. Install all 11 plugins, editable
for p in orchestrator discovery domain \
         reviewer-architect reviewer-developer reviewer-ops reviewer-security \
         validation event-portal blueprint \
         webui-entrypoint; do
  pip install -e "./plugins/solace-architect-${p}/"
done

# 4. Bootstrap a SAM project
mkdir -p sam && cd sam
sam init .                              # creates configs/, shared_config.yaml
for p in orchestrator discovery domain \
         reviewer-architect reviewer-developer reviewer-ops reviewer-security \
         validation event-portal blueprint \
         webui-entrypoint; do
  sam plugin add "solace-architect-${p}" --plugin "solace-architect-${p}"
done

# 5. Configure + run
cp ../test-harness/.env.example .env    # then edit broker + LLM credentials
sam run
```

See [`plugins/solace-architect-webui-entrypoint/README.md`](plugins/solace-architect-webui-entrypoint/README.md) for env var reference, auth modes, and troubleshooting.

## Maintenance scripts

Two helper scripts live at the repo root for managing SA in a SAM project. Both default to `./sam` if you don't pass a path, and both respect the `SAM_DIR` env var.

### `sa-plugins-install.sh` — refresh plugins from GitHub

Re-installs every SA plugin from the upstream `sam-solace-architect-agents` GitHub repo and re-registers each as a SAM component in `<sam-dir>/configs/`. Run any time you push plugin changes upstream and want to pick them up locally.

```bash
./sa-plugins-install.sh                         # uses ./sam
./sa-plugins-install.sh sam                     # explicit
./sa-plugins-install.sh /path/to/other-sam      # any SAM project
SAM_DIR=~/work/sam-prod ./sa-plugins-install.sh

./sa-plugins-install.sh --help
```

The script validates the target is a real SAM project (has a `configs/` directory) before doing anything, then walks the plugin list in dependency order (orchestrator first, entrypoint last). Per-plugin `pip install --force-reinstall` output streams live; the summary at the end lists what succeeded and what failed. Exit code is non-zero only if any plugin failed.

### `sa-plugins-uninstall.sh` — uninstall SA from a SAM project

Removes SA configs from `<sam-dir>/configs/`, pip-uninstalls every SA package (including `solace-architect-core` unless `--keep-core`), and clears `<sam-dir>/sa_logs/`.

```bash
./sa-plugins-uninstall.sh                        # interactive — prompts for confirm
./sa-plugins-uninstall.sh --dry-run              # preview only, no changes
./sa-plugins-uninstall.sh --yes                  # skip confirmation
./sa-plugins-uninstall.sh --keep-core            # leave solace-architect-core installed
./sa-plugins-uninstall.sh /path/to/other-sam --yes

./sa-plugins-uninstall.sh --help
```

**Never touched:** engagement data under `SA_STORAGE_ROOT` (your projects), the SAM project's stock state .db files, the SAM directory itself, or stock SAM agents (BuiltInTools, sam-mermaid, find-my-ip, etc.). To restore SA after a cleanup, run `./sa-plugins-install.sh`.

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
