# solace-architect-core

Shared library for the [Solace Architect V2 plugin family](https://github.com/solacecommunity/solace-agent-mesh-plugins). Every `solace-architect-*` SAM plugin declares this package as a dependency — it owns the storage layout, the tool surface, schemas, grounding corpus, branding/report-pack defaults, telemetry callbacks, and the `engagement_id` + `user_id` resolution that makes agent runs reproducible.

## What's in here

### `tools/` — the shared tool surface

Imported by per-plugin `config.yaml` files; each tool auto-resolves `user_id` from the ADK `tool_context` so writes hit the correct `users/<uid>/<engagement>/` namespace.

| Module | What it does |
|---|---|
| `artifact_tools` | `write_artifact`, `read_artifact`, `list_artifacts` — the primary I/O surface. Enforces path-traversal safety + per-artifact size budget. |
| `decision_tools` | `record_decision`, `read_decisions`, `record_finding`, `read_findings`, `record_open_item`, `read_open_items` — design decisions, review findings, blocking/advisory open items. |
| `lifecycle_tools` | `set_step_status`, `get_engagement_status` — per-step DONE / DONE_WITH_CONCERNS / BLOCKED tracking with start/end timing for the timeline view. |
| `project_tools` | Multi-engagement project registry (rename, archive, clone, list) under the reserved `__system__` engagement. |
| `intake_tools` | Intake validation — surfaces missing required fields and optional unspecified ones. |
| `interaction_tools` | `ask_user_question` — structured Q&A primitive that the WebUI renders as clickable option chips with optional note. |
| `grounding_tools` | Read-only access to the bundled `grounding/` corpus + `gaps.md` runtime gap tracker. |
| `blueprint_tools` | `check_diagram_availability`, `render_audience_pack`, `assemble_zip` — Blueprint phase assembly. Cache-aware (`force=True` to regenerate). |
| `validation_tools` | `trace_requirements` — requirements traceability matrix used by SAValidationAgent. |
| `dashboard_tools` | Aggregation tools the WebUI calls for the dashboard panes (overview, decisions, timeline, open items, artifacts). |
| `session_tools` | A2A session metadata helpers (engagement_id + user_id extraction from task headers). |
| `workflow_tools` | Orchestrator coordination helpers (peer dispatch, completion-status routing). |
| `telemetry_tools` | LLM-call ledger writes — append per-call rows to `meta/telemetry/llm-calls.jsonl`. |

### `schemas/`
Dataclass models for the on-disk YAML schemas — decisions, findings, open-items, projects, provisioned objects, feedback, lifecycle status. Each model has a `to_dict()`/`from_dict()` pair.

### `grounding/`
Vendored grounding docs (read-only reference + `jargon-list.json`) that every agent's prompt can quote from, plus the writable `gaps.md` runtime gap tracker. Curated capability-coverage matrix lives at `grounding/gaps.md` and is the source of the `project_grounding_inventory_gaps` backlog.

### `configs/`
Defaults consumers override via env vars or local overlays:
- `branding.yaml` — colors, logos, audience-pack copy.
- `skill-routing.yaml` — agent → skill mapping for routing decisions.
- `report-packs.yaml` — per-pack filters (decisions, findings, top_sections, include_roi_calculator, …).

### Storage layout

All artifacts live under `SA_STORAGE_ROOT` (default `/tmp/sa-artifacts`), namespaced per authenticated user:

```
$SA_STORAGE_ROOT/
└── users/
    └── <user_id>/
        ├── __system__/                  # projects.yaml registry, audit log
        └── <engagement_id>/
            ├── discovery/               # intake.json, intake.md, discovery-brief.yaml
            ├── topic-design/            # topic-taxonomy.yaml, …
            ├── broker-select/
            ├── …                        # one folder per Design scope
            ├── reviews/                 # architect-review.md, developer-review.md, …
            ├── validation/              # validation-report.{md,yaml}
            ├── event-portal/            # event-portal-model.yaml (design output) +
            │                            # plan.yaml, provisioned.yaml, provisioning-report.md,
            │                            # asyncapi/*.yaml — populated when the opt-in
            │                            # event-portal step runs (SAEventPortalAgent)
            ├── blueprint/               # architecture.md, runbook.md, diagrams/, packs/
            ├── exports/                 # engagement-package.zip + rendered HTML/PDF packs
            └── meta/
                ├── engagement-status.yaml
                ├── decisions.yaml
                ├── findings.yaml
                ├── open-items.yaml
                └── telemetry/llm-calls.jsonl
```

### Telemetry + callbacks
`_sam_telemetry_patch.py` monkey-patches both `setup.initialize_adk_agent` and `component.initialize_adk_agent` (both bindings are required) to chain an `after_model_callback` onto every initialised ADK agent. The callback writes one row per LLM round-trip into the engagement's `meta/telemetry/llm-calls.jsonl` ledger — survives restarts and is queryable across SAM sessions. Per-plugin `lifecycle.py` calls `install_telemetry_patch()` from a plain (sync) `def init()` because SAM invokes `init_function` synchronously.

### User-scoping
`_user_context.py` exposes `resolve_user_id(user_id, tool_context)` + `scoped_user(uid)`. Every storage-touching tool calls these so the caller can omit `user_id` and the right namespace is still picked up from the SAM session — without leaking another user's namespace.

## Required env vars

| Variable | Default | Purpose |
|---|---|---|
| `SA_STORAGE_ROOT` | `/tmp/sa-artifacts` | Root for engagement artifacts + per-user namespaces. |
| `LLM_SERVICE_GENERAL_MODEL_NAME` | *(required)* | LiteLLM provider-prefixed model name. Used by every agent. |
| `LLM_SERVICE_ENDPOINT` | *(blank)* | Leave blank for cloud; set for LiteLLM proxies, Azure OpenAI, Ollama. |
| `LLM_SERVICE_API_KEY` | *(required)* | Provider or proxy key. |
| `NAMESPACE` | *(required)* | A2A topic namespace. |
| `SOLACE_BROKER_URL` / `_USERNAME` / `_PASSWORD` / `_VPN` | broker defaults | Client credentials. Never SEMP/admin. |
| `SOLACE_API_TOKEN` | *(unset)* | Solace Cloud token — only needed when `solace-architect-event-portal` is installed and EP provisioning is opted-in via intake. |

## Install (during development)

```bash
pip install -e .
```

The library is used directly by every plugin in `../plugins/`. To verify imports resolve cleanly:

```bash
python -c "from solace_architect_core import tools, schemas; print(dir(tools))"
```

## Tests

```bash
pytest ../tests/             # cross-plugin tests that import this package
```

Per-tool test files live in `../tests/test_tools.py`, `test_path_traversal.py`, `test_canonical_urls.py`, `test_terminology.py`, `test_token_budgets.py`, `test_roi_calculator.py`, `test_skill_routing.py`, `test_report_packs_isolation.py`.

## License

Apache 2.0.
