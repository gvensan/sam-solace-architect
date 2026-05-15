# Solace Architect V2 — Agent Build Specification

**Purpose:** This document specifies every agent, tool, entrypoint, and shared component needed to build Solace Architect V2 as a deployable SAM project. It is written for Claude Code to produce valid, correct, SAM-compliant agents that can be tested end to end against the bank chat agent reference scenario.

**SAM version target:** Align with the current stable release at `solacelabs.github.io/solace-agent-mesh`.

**Delivery:** A SAM project directory that passes `sam run` and processes a bank chat agent engagement from discovery through blueprint.

---

## 1. Repository structure (plugin family)

V2 is distributed as a family of **SAM plugins** that target the [Solace community plugins registry](https://github.com/solacecommunity/solace-agent-mesh-plugins). Each plugin is independently installable via `sam plugin add <name>`. Shared code lives in a separate **PyPI library** (`solace-architect-core`) that every plugin declares as a dependency.

See §10 for the full distribution model rationale and decomposition decisions.

```
sam-solace-architect/                              # this repository (development monorepo + test harness)
├── documents/
│   ├── v2spec.md                                  # This spec
│   ├── v1-v2-gap-analysis.md                      # V1 → V2 audit
│   └── v2-build-plan.md                           # Phased build plan
│
├── solace-architect-core/                         # Shared library — separate PyPI package
│   ├── pyproject.toml                             # Published as `solace-architect-core` on PyPI
│   ├── README.md
│   └── src/solace_architect_core/
│       ├── __init__.py
│       ├── tools/
│       │   ├── artifact_tools.py                  # All shared tools per §3 + §5
│       │   ├── decision_tools.py
│       │   ├── grounding_tools.py
│       │   ├── intake_tools.py
│       │   ├── workflow_tools.py
│       │   ├── validation_tools.py
│       │   ├── blueprint_tools.py
│       │   ├── session_tools.py
│       │   ├── project_tools.py
│       │   ├── dashboard_tools.py
│       │   └── ep_designer_mcp_tools.py
│       ├── schemas/                               # YAML schemas: open-items, projects, feedback, provisioned
│       ├── grounding/                             # Vendored grounding docs (read-only reference)
│       │   ├── agent-preamble.md                  # Shared accuracy / voice / naming discipline, loaded by every agent
│       │   ├── solace-platform-reference.md
│       │   ├── solace-canonical-sources.md
│       │   ├── solace-reference-architectures.md
│       │   ├── antipatterns.md
│       │   ├── integration-hub-catalog.md
│       │   ├── naming-conventions.md
│       │   ├── jargon-list.json
│       │   └── gaps.md                            # Runtime gap tracker (writable)
│       └── configs/                               # Default configs (overridable by consumers)
│           ├── branding.yaml                      # Default Solace branding
│           ├── skill-routing.yaml                 # Conditional design-scope inclusion
│           └── report-packs.yaml                  # Audience-pack filter rules
│
├── plugins/                                       # 11 plugin directories — each mirrors the community-repo layout
│   ├── solace-architect-orchestrator/             # SAOrchestratorAgent plugin
│   │   ├── README.md
│   │   ├── config.yaml                            # SAM agent config
│   │   ├── pyproject.toml                         # [tool.solace_architect_orchestrator.metadata] type = "agent"
│   │   └── src/solace_architect_orchestrator/
│   │       ├── __init__.py
│   │       └── lifecycle.py                       # Plugin-specific init/cleanup
│   │
│   ├── solace-architect-discovery/                # SADiscoveryAgent plugin
│   ├── solace-architect-domain/                   # SADomainAgent plugin (all 9 design scopes)
│   ├── solace-architect-reviewer-architect/       # SAArchitectReviewerAgent plugin
│   ├── solace-architect-reviewer-developer/       # SADeveloperReviewerAgent plugin
│   ├── solace-architect-reviewer-ops/             # SAOpsReviewerAgent plugin
│   ├── solace-architect-reviewer-security/        # SASecurityReviewerAgent plugin
│   ├── solace-architect-validation/               # SAValidationAgent plugin
│   ├── solace-architect-blueprint/                # SABlueprintAgent plugin
│   │   ├── config.yaml
│   │   ├── pyproject.toml                         # Depends on weasyprint + solace-architect-core
│   │   └── src/solace_architect_blueprint/
│   │       ├── lifecycle.py
│   │       └── report_generator/                  # Ported V1 HTML report generator
│   │           ├── templates/                     # 5 audience-pack HTML templates
│   │           ├── static/                        # CSS, fonts, ROI calculator JS
│   │           └── render.py
│   │
│   ├── solace-architect-provisioning/             # SAProvisioningAgent plugin (opt-in)
│   │   ├── config.yaml
│   │   ├── pyproject.toml                         # Documents EP Designer MCP requirement
│   │   └── src/solace_architect_provisioning/
│   │
│   └── solace-architect-webui-entrypoint/                    # WebUI entrypoint plugin (also exposes REST API)
│       ├── config.yaml                            # SAM entrypoint config; [tool.x.metadata] type = "gateway" (legacy metadata field value — SAM has not renamed the metadata key even though the resource type is now called "entrypoint")
│       ├── pyproject.toml
│       └── src/solace_architect_webui_entrypoint/
│           ├── lifecycle.py                       # Entrypoint init: registers routes, mounts static assets
│           ├── webui/                             # Static dashboard + intake form assets
│           │   ├── index.html
│           │   ├── dashboard/                     # 6 SPA views (Overview, Timeline, Decisions, ...)
│           │   ├── intake/                        # HTML intake form
│           │   └── assets/                        # CSS, JS bundles, dark-mode theme
│           └── routes/                            # Python route handlers (chat SSE, dashboard APIs, audience packs)
│
├── test-harness/                                  # Local SAM project for end-to-end testing
│   ├── pyproject.toml                             # Installs all plugins editable (-e ../plugins/<name>)
│   ├── .env.example                               # NAMESPACE, SOLACE_BROKER_*, model API key
│   ├── README.md                                  # `sam run` instructions
│   └── fixtures/
│       ├── bank_chat_agent.yaml                   # Pattern 1 fixture
│       ├── market_data_distribution.yaml          # Pattern 2 fixture
│       └── hybrid_it_ot.yaml                      # Pattern 3 fixture
│
└── tests/                                         # Cross-plugin integration tests
    ├── test_agent_definitions.py                  # YAML validity across all plugin config.yamls
    ├── test_terminology.py                        # Forbidden term scan across all plugins
    ├── test_tools.py                              # Unit tests for solace-architect-core tools
    ├── test_report_packs_isolation.py             # Audience-pack filter rules honored
    ├── test_ep_provisioning.py                    # EP provisioning opt-in/MCP-unavailable contract
    ├── test_token_budgets.py                      # Per-agent prompt size ceilings
    ├── test_roi_calculator.py                     # Auto-fill rules + sensitivity sliders
    ├── test_skill_routing.py                      # Operator vocabulary
    ├── test_path_traversal.py                     # Entrypoint artifact-path safety
    ├── test_canonical_urls.py                     # CI-only URL health check
    └── test_e2e_bank_chat.py                      # End-to-end via test-harness
```

**Two distribution targets:**

1. **`solace-architect-core`** → PyPI (`pip install solace-architect-core`)
2. **Each plugin under `plugins/`** → PR to `solacecommunity/solace-agent-mesh-plugins` (one PR per plugin)

The `test-harness/` directory is **not distributed** — it's a local SAM project that pip-installs the plugins in editable mode for development and end-to-end testing.

---

## 2. Shared configuration

### 2.1 shared_config.yaml

Defines broker connection, LLM model, and shared services. All agent and entrypoint configs reference these via YAML anchors.

```yaml
# Each plugin's config.yaml has its own shared_config block following SAM convention.
# This is the canonical shape.

shared_config:
  - broker_connection: &broker_connection
      # The broker credentials below are a CLIENT USERNAME (pub/sub permissions only).
      # Solace Architect plugins never call SEMP / admin APIs. Broker admin operations
      # (create VPN / queue / ACL profile / etc.) stay in your IaC + Mission Control
      # workflow — out of scope for this toolkit.
      dev_mode: ${SOLACE_DEV_MODE, false}
      broker_url: ${SOLACE_BROKER_URL}
      broker_username: ${SOLACE_BROKER_USERNAME}
      broker_password: ${SOLACE_BROKER_PASSWORD}
      broker_vpn: ${SOLACE_BROKER_VPN}
      temporary_queue: ${USE_TEMPORARY_QUEUES, true}

  - services:
      artifact_service: &default_artifact_service
        type: "filesystem"
        base_path: ${SA_STORAGE_ROOT, /tmp/sa-artifacts}
        artifact_scope: namespace

# Model wiring — SAM/ADK uses the LiteLLM wrapper. Three env vars drive every
# agent's LLM dispatch (no per-agent model selection in Phase 1):
#
#   LLM_SERVICE_GENERAL_MODEL_NAME — LiteLLM provider-prefixed name
#                                    e.g. anthropic/claude-sonnet-4-20250514
#                                         openai/gpt-4o
#                                         gemini/gemini-1.5-pro
#                                         bedrock/anthropic.claude-3-sonnet-...
#                                         ollama/llama3.1
#                                         vertex_ai/claude-sonnet-4@20250514
#                                    OR a custom alias routed through a LiteLLM proxy.
#   LLM_SERVICE_ENDPOINT           — leave blank for cloud providers; set for proxies,
#                                    Azure, Ollama, or self-hosted LLMs.
#   LLM_SERVICE_API_KEY            — provider API key (or proxy key).
#
# Each agent's config.yaml references these via:
#
#   general: &general_model
#     model: ${LLM_SERVICE_GENERAL_MODEL_NAME}
#     api_base: ${LLM_SERVICE_ENDPOINT}
#     api_key: ${LLM_SERVICE_API_KEY}
#
# Then in the app_config: `model: *general_model`. See cli-entrypoint or tavily
# in the community plugins repo for the canonical pattern.

namespace: &namespace ${NAMESPACE}                 # Injected by the installed SAM; no default (misconfig fails loud)

artifact_service_config: &artifact_service_config
  enabled: true

session_service_config: &session_service_config
  enabled: true
```

### 2.2 Namespace and A2A topics

Namespace is **not hardcoded**. The installed SAM injects `${NAMESPACE}` from its install configuration (typically the project `.env` or `sam-cli` config). Misconfigured installs fail loud rather than silently routing on a default value.

SAM's A2A protocol prescribes the topic structure. The ten agents are addressable at:

| Agent | A2A request topic |
|-------|-------------------|
| SAOrchestratorAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-orchestrator` |
| SADiscoveryAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-discovery` |
| SADomainAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-domain` |
| SAArchitectReviewerAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-review-architect` |
| SADeveloperReviewerAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-review-developer` |
| SAOpsReviewerAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-review-ops` |
| SASecurityReviewerAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-review-security` |
| SAValidationAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-validation` |
| SABlueprintAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-blueprint` |
| SAProvisioningAgent | `${NAMESPACE}/a2a/v1/agent/request/sa-provisioning` |

These follow the SAM convention `{namespace}/a2a/v1/agent/request/{agent_name}`. The `sa-` prefix on each agent_name segment keeps Solace Architect agents distinct from any co-resident agents that share the SAM install. Do not modify the topic structure beyond the prefix.

---

## 3. Shared tools

These tools are used by multiple agents. They live in `src/sa_solace_architect/tools/` and are referenced by `component_module` in each agent's YAML config.

### 3.0 Shared baseline tools (loaded by every agent)

To avoid repeating the same four tools in every agent YAML, all ten agents are configured to load the following shared baseline at init. Each agent YAML in §4 omits these from its own `tools:` list — the implementor adds them once to a shared base config that every agent extends:

| Tool | Module | Purpose |
|------|--------|---------|
| `load_preamble` | `grounding_tools` | Loads `grounding/agent-preamble.md` — the shared accuracy / voice / naming / working-style discipline. Called as the agent's first tool action; result is prepended to the role-specific system prompt. Single source of truth (Decision 83) |
| `load_jargon_list` | `grounding_tools` | Loads `grounding/jargon-list.json` so the agent's system prompt can gloss EDA/Solace terms on first use |
| `record_step_timing` | `workflow_tools` | Captures `wall_sec`/`execution_sec`/`user_wait_sec`/per-question/per-substep at the end of each step; sole input source for dashboard timing views |
| `record_grounding_gap` | `grounding_tools` | Called on `load_grounding`/`fetch_canonical_source` error paths so gaps surface in CI grounding maintenance |
| `record_feedback` | `decision_tools` | Lets the agent log a feedback entry when the user expresses dissatisfaction with output quality (Phase 1 collection; Phase 2 aggregates) |
| `record_token_usage` | `telemetry_tools` | Appends one row per LLM round-trip to `meta/telemetry/llm-calls.jsonl` (Decision 84). Normally invoked from each agent's `after_model_callback` via the `record_llm_call_telemetry` helper in `solace_architect_core.agent_callbacks` |
| `read_token_usage` | `telemetry_tools` | Reads and aggregates the engagement's telemetry ledger by `agent`/`step`/`model`/`day`; powers the dashboard Telemetry view and CLI inspection |

Agent-specific tool lists in §4 list **only the tools beyond this baseline**.

### 3.1 artifact_tools.py

Provides read, write, and list operations on the engagement artifact store. All artifact names follow the pattern `{category}/{filename}`.

```python
# Tool: read_artifact
# Used by: All agents
# Signature: async def read_artifact(artifact_name: str, ...) -> ToolResult
# Behavior: Reads a named artifact from the engagement artifact store via ArtifactService.
# Returns the artifact content as a string, or an error if not found.
# artifact_name must match pattern: category/filename (e.g., "topic-design/topic-taxonomy.yaml")

# Tool: write_artifact
# Used by: SADomainAgent, SABlueprintAgent, SAOrchestratorAgent (for applied fixes), SAProvisioningAgent
# Signature: async def write_artifact(artifact_name: str, content: str, ...) -> ToolResult
# Behavior: Writes (overwrites) a named artifact. Runs three independent pre-write checks
#   and returns structured violation lists per check, NOT just a flat error string:
#
#     ToolResult.error_detail = {
#       path_check: {ok: bool, error: str|None},
#       terminology_check: {ok: bool, violations: [{term, line, suggested_replacement}]},
#       naming_check:      {ok: bool, violations: [{convention, line, found, suggested}]},
#       grounding_check:   {ok: bool, violations: [{claim, line, reason}]}
#     }
#
#   Specifically:
#   1. path_check: artifact_name must match category/filename pattern (rejects path traversal)
#   2. terminology_check: forbidden term scan (connector, QoS, orchestrator agent, adapter,
#      PubSub+, entrypoint when external-facing). Per V1's jargon list.
#   3. naming_check: naming conventions from grounding/naming-conventions.md (CamelCase agents,
#      snake_case tools, kebab-case topic segments, etc.)
#   4. grounding_check: ungrounded claims — any Solace capability not attributable to docs
#      (heuristic: capability statements without nearby `[grounding:...]` cite markers)
#
#   If ANY check fails, the tool returns ok=false with the structured violation lists.
#   Does not write. On success, writes via ArtifactService and returns confirmation + timestamp.
#   Agents are expected to surface the structured violations to the user as actionable items
#   (per finding-resolution UX), not as a wall of text.

# Tool: list_artifacts
# Used by: All agents
# Signature: async def list_artifacts(category: str = None, ...) -> ToolResult
# Behavior: Returns a list of all artifact names in the engagement store.
#   If category is provided, filters to that category only.
#   Returns artifact names and last-modified timestamps.
```

**Forbidden terminology list** (embedded in the tool, sourced from V1's `generate-naming-conventions.ts`):

- "connector" (use "Micro-Integration")
- "QoS" or "QoS levels" (use "Direct messaging" and "Guaranteed messaging")
- "orchestrator agent" (two words — use "SAOrchestratorAgent")
- "adapter" when referring to Solace integrations (use "Micro-Integration")
- "PubSub+" as a standalone product name (use the specific product name)
- "gateway" as a SAM resource type (use **"entrypoint"** — SAM renamed this resource type; V1 docs used "Gateway" but the current SAM convention is "entrypoint"). Note: it is fine to use "gateway" in generic English where it does not refer to a SAM resource (rare)

### 3.2 decision_tools.py

Manages the decision log and review findings.

```python
# Tool: record_decision
# Used by: SADiscoveryAgent, SADomainAgent, SAOrchestratorAgent
# Signature: async def record_decision(
#     context: str,           # What was being decided
#     recommendation: str,    # What was recommended
#     selected: str,          # What was selected
#     rationale: str,         # Why
#     ...) -> ToolResult
# Behavior: Appends a D-numbered decision to the decisions artifact.
#   Auto-assigns the next D-number (D1, D2, ...).
#   Records source_agent from tool_context.
#   Records timestamp.
#   Writes to engagement artifact: "meta/decisions.yaml"

# Tool: record_finding
# Used by: SAArchitectReviewerAgent, SADeveloperReviewerAgent, SAOpsReviewerAgent, SASecurityReviewerAgent
# Signature: async def record_finding(
#     severity: str,           # "critical" | "important" | "advisory"
#     description: str,        # What the issue is
#     affected_artifact: str,  # Which artifact has the issue (artifact_name)
#     recommendation: str,     # Recommended fix
#     ...) -> ToolResult
# Behavior: Appends a finding to the findings artifact.
#   Auto-assigns finding ID (F1, F2, ...).
#   Sets initial status to "pending".
#   Records source_agent, timestamp.
#   Writes to: "meta/findings.yaml"

# Tool: read_decisions
# Used by: SAOrchestratorAgent, SABlueprintAgent, SAValidationAgent
# Signature: async def read_decisions(...) -> ToolResult
# Behavior: Returns the full decision log from "meta/decisions.yaml"

# Tool: read_findings
# Used by: SAOrchestratorAgent, SAValidationAgent, SABlueprintAgent
# Signature: async def read_findings(status: str = None, ...) -> ToolResult
# Behavior: Returns findings, optionally filtered by status ("pending", "applied", "deferred")

# Tool: update_finding_status
# Used by: SAOrchestratorAgent
# Signature: async def update_finding_status(
#     finding_id: str,     # e.g., "F3"
#     new_status: str,     # "applied" | "deferred"
#     resolution_note: str = None,
#     ...) -> ToolResult
# Behavior: Updates the status of a finding in "meta/findings.yaml".
#   When new_status="deferred", also creates a corresponding open-item via
#   record_open_item (source="review-deferred", severity="advisory" by default,
#   or "blocking" if the finding severity was "critical").

# Tool: record_open_item
# Used by: SADiscoveryAgent, SAOrchestratorAgent, SAValidationAgent, reviewers (indirect via deferred findings)
# Signature: async def record_open_item(
#     severity: str,           # "blocking" | "advisory"
#     source: str,             # "intake" | "discovery" | "review-deferred" | "validation"
#     description: str,        # What is open
#     affecting_step: str = None,   # Which workflow step it blocks/affects (if any)
#     affected_artifact: str = None,
#     ...) -> ToolResult
# Behavior: Appends a Q-numbered open item to the open-items artifact.
#   Auto-assigns ID (Q1, Q2, ...).
#   Sets initial status="open".
#   Records source_agent, timestamp.
#   Writes to engagement artifact: "meta/open-items.yaml"

# Tool: read_open_items
# Used by: SAOrchestratorAgent, WebUI Entrypoint (Open Items view), SAValidationAgent
# Signature: async def read_open_items(
#     status: str = None,      # filter: "open" | "resolved"
#     severity: str = None,    # filter: "blocking" | "advisory"
#     source: str = None,
#     ...) -> ToolResult
# Behavior: Returns open items, optionally filtered. Used by orchestrator to gate
#   progress on blocking items and by the WebUI dashboard to render the Open Items view.

# Tool: update_open_item_status
# Used by: SAOrchestratorAgent
# Signature: async def update_open_item_status(
#     item_id: str,            # e.g., "Q3"
#     new_status: str,         # "open" | "resolved"
#     resolution_note: str = None,
#     ...) -> ToolResult
# Behavior: Updates the status of an open item in "meta/open-items.yaml"

# Tool: record_feedback
# Used by: SAOrchestratorAgent (when user provides feedback via entrypoint), WebUI Entrypoint (Feedback button)
# Signature: async def record_feedback(
#     scope: str,              # which agent/skill the feedback is about (e.g., "topic-design")
#     rating: int,              # 1-5
#     category: str,            # "accuracy" | "depth" | "voice" | "completeness" | "other"
#     note: str,
#     ...) -> ToolResult
# Behavior: Appends a feedback entry to meta/feedback.yaml in the engagement scope.
#   This is the data layer only — Phase 1 collects feedback per engagement.
#   The cross-project aggregation pipeline (rollup → IMPROVEMENTS.md) is Phase 2.

# Tool: read_feedback
# Used by: WebUI Entrypoint (Feedback view, optional Phase 1)
# Signature: async def read_feedback(scope: str = None, ...) -> ToolResult
# Behavior: Returns feedback entries from meta/feedback.yaml, optionally filtered by scope.
```

**`meta/feedback.yaml` schema:**

```yaml
feedback:
  - id: FB1
    scope: topic-design              # which agent/skill
    rating: 4                        # 1-5
    category: depth                  # accuracy | depth | voice | completeness | other
    note: "Topic taxonomy didn't account for the multi-tenant scenario; had to ask twice"
    recorded_at: 2026-05-13T16:30:00Z
    recorded_by: anonymous           # Phase 1: anonymous; Phase 2: OIDC subject
```

**Phase 2 deliverable (not in v2spec.md):** A CI job that aggregates `meta/feedback.yaml` across all engagements into a repository-level `IMPROVEMENTS.md` for prompt-iteration. Schema is set up in Phase 1 so data starts collecting from Day 1.

**`meta/open-items.yaml` schema:**

```yaml
open_items:
  - id: Q1
    severity: blocking            # blocking | advisory
    source: intake                # intake | discovery | review-deferred | validation
    description: "Latency tier not specified in intake template"
    affecting_step: topic-design  # which workflow step this blocks (null = informational)
    affected_artifact: null
    status: open                  # open | resolved
    source_agent: SADiscoveryAgent
    created_at: 2026-05-13T14:22:00Z
    resolution_note: null
```

SAOrchestratorAgent reads open-items at every workflow transition. **Any blocking item halts progress** and surfaces the item to the user via the entrypoint for resolution. Advisory items accumulate in the Open Items dashboard view and are summarized in the ValidationAgent's final report.

### 3.3 project_tools.py

Entrypoint-level project (engagement) registry. Lives outside any single engagement's artifact namespace — projects.yaml is stored under a reserved `__system__` engagement so it survives across SAM sessions.

```python
# Tool: list_projects
# Used by: WebUI Entrypoint (sidebar), REST Entrypoint (GET /engagements)
# Signature: async def list_projects(include_archived: bool = False, ...) -> ToolResult
# Behavior: Reads meta/projects.yaml from the __system__ engagement scope.
#   Returns: list of {id, name, created_at, last_active_at, status, owner}.

# Tool: create_project
# Used by: WebUI Entrypoint ("New Project"), REST Entrypoint (POST /engagements)
# Signature: async def create_project(name: str, owner: str = None, ...) -> ToolResult
# Behavior: Generates a new engagement_id, registers it in meta/projects.yaml,
#   initializes its artifact namespace with empty meta/decisions.yaml,
#   meta/findings.yaml, and meta/open-items.yaml. Returns the new engagement_id.

# Tool: archive_project
# Used by: WebUI Entrypoint, REST Entrypoint
# Signature: async def archive_project(project_id: str, ...) -> ToolResult
# Behavior: Marks the project as archived in meta/projects.yaml (artifacts retained).
#   Archived projects are hidden from the default WebUI sidebar list.

# Tool: switch_active_project
# Used by: WebUI Entrypoint (sidebar click)
# Signature: async def switch_active_project(project_id: str, ...) -> ToolResult
# Behavior: Updates the session's active engagement_id. No-op if already active.
```

**`meta/projects.yaml` schema (stored under reserved `__system__` engagement):**

```yaml
projects:
  - id: retailco-order-events
    name: "RetailCo Order Events"
    created_at: 2026-05-13T10:00:00Z
    last_active_at: 2026-05-13T14:45:00Z
    status: active                # active | archived
    owner: anonymous              # Phase 1: anonymous; Phase 2: OIDC subject from entrypoint auth
    description: "Retail-banking event mesh PoC, EP provisioning enabled"
```

**Concurrent editing policy:** Phase 1 uses last-write-wins. If two architects open the same project simultaneously, the entrypoint emits a soft warning banner but does not block. Optimistic concurrency control is deferred to Phase 2+.

### 3.4 dashboard_tools.py

Computes the data underlying the Overview, Timeline, and Stats dashboard views from the engagement's existing artifacts. Pure read-side; never mutates state.

```python
# Tool: compute_overview_stats
# Used by: WebUI Entrypoint (Overview view), REST Entrypoint (GET /engagements/{id}/stats/overview)
# Signature: async def compute_overview_stats(engagement_id: str, ...) -> ToolResult
# Output: {
#   skills_completed: int, skills_total: int, skills_skipped: int,
#   connected_systems: int, producers: int, consumers: int,
#   artifacts_count: int,
#   decisions_count: int, review_findings_count: int,
#   open_items_blocking: int, open_items_advisory: int,
#   execution_time_seconds: int, user_wait_seconds: int,
#   ep_provisioning_status: str,                 # "not-requested" | "pending" | "live"
#   phase_progress: {discovery: "1/1", design: "6/10", review: "4/4", ...},
#   recommended_next_step: str,                  # derived from skill-routing + completed_steps + open_items
#   skip_reasons: list of {step, reason}         # human-readable reasons per skipped step
# }
# Logic: Reads session state, decisions/findings/open-items, and skill-routing.yaml.
#
# IMPORTANT — per-skill dedup (STATUS_RANK precedence):
#   When the same step has multiple state entries (e.g. EP-provision retries), apply:
#     Rank order: complete > in-progress > partial > interrupted > skipped > blocked
#     Tiebreak: newest `started_at` wins.
#   Without this, retries inflate counts. Mirror V1's STATUS_RANK semantics.
#
# IMPORTANT — effective-skipped logic:
#   Steps that the user opted out of via intake (e.g. preferences.provision_event_portal=false)
#   are counted as `skipped` with skip_reason from skill-routing.yaml, NOT as `pending`.
#   This matches V1's effective-skipped behavior.

# Tool: compute_active_step
# Used by: WebUI Entrypoint (live status bar on every dashboard view)
# Signature: async def compute_active_step(engagement_id: str, ...) -> ToolResult
# Output: {
#   active_agent: str | None,        # e.g., "SADomainAgent"
#   active_scope: str | None,        # e.g., "topic-design"
#   active_phase: str,               # "discovery" | "design" | "review" | "validation" | "blueprint" | "provisioning" | "idle"
#   started_at: str | None,          # ISO timestamp
#   elapsed_seconds: int | None,
#   user_waiting: bool               # True if blocked on a question / decision / open-item
# }
# Logic: Reads workflow_tools session state. Returns the in-progress step or null if idle.
#        The WebUI status bar polls this endpoint every 2s and renders it as a sticky top banner.

# Tool: compute_timeline
# Used by: WebUI Entrypoint (Timeline view), REST Entrypoint (GET /engagements/{id}/timeline)
# Signature: async def compute_timeline(engagement_id: str, ...) -> ToolResult
# Output: ordered list of {skill, started_at, ended_at, execution_seconds, user_wait_seconds}
# Logic: Reads the workflow session state's timing_data records produced by record_step_complete.

# Tool: compute_stats_summary
# Used by: WebUI Entrypoint (Stats view), REST Entrypoint (GET /engagements/{id}/stats)
# Signature: async def compute_stats_summary(engagement_id: str, ...) -> ToolResult
# Output: {
#   wall_time_seconds, execution_seconds, user_wait_seconds,
#   steps_executed, questions_asked,
#   top_skills_by_execution_time: [{skill, seconds, pct}],
#   phase_breakdown: [{phase, seconds, count}],
#   insights: {slowest_skill, fastest_skill, avg_per_skill_seconds}
# }
```

### 3.5 session_tools.py

Manages engagement-level session state (distinct from artifacts).

```python
# Tool: read_session_state
# Used by: SAOrchestratorAgent
# Signature: async def read_session_state(...) -> ToolResult
# Behavior: Reads the current engagement state from ADK session management.
#   Returns: current_phase, execution_mode, completed_steps, 
#            active_step, timing_data, engagement_id

# Tool: update_session_state
# Used by: SAOrchestratorAgent
# Signature: async def update_session_state(
#     updates: dict,   # Partial update to session state
#     ...) -> ToolResult
# Behavior: Merges updates into session state. 
#   Valid keys: current_phase, execution_mode, completed_steps, 
#               active_step, timing_data
```

---

## 4. Agent specifications

Each agent specification includes: purpose, Agent Card, system prompt summary, tools, grounding documents loaded, artifacts consumed and produced, and task request/response format.

---

### 4.1 SAOrchestratorAgent

**File:** `configs/agents/sa-orchestrator.yaml`

**Purpose:** Central coordinator for the entire architectural engagement. Owns workflow state. Dispatches tasks to other agents. Manages execution mode (auto/interactive). Handles finding resolution loop. **Gates workflow progress on blocking open-items** (see §3.2). Presents AskUserQuestion decision briefs and free-text prompts to the user via the entrypoint.

**Agent Card:**

```yaml
agent_card:
  description: >
    Coordinates Solace Architect engagements. Sequences discovery, design,
    review, validation, and blueprint agents. Manages session state,
    execution mode, and finding resolution. Presents architectural decisions
    to the user and routes responses to the appropriate agent.
  defaultInputModes: ["text/plain", "application/json"]
  defaultOutputModes: ["text/plain", "application/json"]
  skills:
    - id: "manage_engagement"
      name: "Engagement Management"
      description: "Sequences agents for a complete architecture engagement based on discovery output."
    - id: "resolve_findings"
      name: "Finding Resolution"
      description: "Presents review findings to the user with Apply/Defer/Discuss options and routes responses."
    - id: "present_decision"
      name: "Decision Presentation"
      description: "Presents structured architectural decisions (AskUserQuestion format) and records selections."
```

**System prompt core content:**

The system prompt must include:

1. **Identity.** "You are the SAOrchestratorAgent for Solace Architect, a toolkit that guides architects from a business problem to a deployable Solace event-driven architecture blueprint."
2. **Shared preamble.** Loaded once at session start by calling `load_preamble()` (§3.0 baseline tool) — provides the full accuracy/grounding discipline, voice, and naming rules (Decision 83). The role-specific prompt below extends but never restates the preamble.
3. **Role-specific naming.** Any naming behavior that goes beyond the shared preamble (e.g., orchestrator's choice of which agent name to surface in status messages) is specified here.
4. **Voice directive.** Senior architect tone. No AI vocabulary. No vendor pitch. Short sentences. Decisions close with user impact.
5. **Engagement overview.** The phases (Discovery → Design → Review → Validation → Blueprint) and what each phase produces.
6. **Execution mode behavior.** Auto mode: chain agents without confirmation, pause only on Critical findings and validation failures. Interactive mode: present three-option routing after each agent completes (Continue / Skip / Pick different).
7. **AskUserQuestion format.** The structured decision brief format: D-numbered, context paragraph, recommendation callout (blockquote with project-specific rationale), per-option pros/cons with completeness scoring, selectable options.
8. **Finding resolution protocol.** Present each finding with severity, description, affected artifact, and recommendation. Offer Apply/Defer/Discuss. On Apply: dispatch fix to SADomainAgent, update finding status. On Defer: log for SAValidationAgent AND record an open-item via `record_open_item` (source="review-deferred", severity="advisory" or "blocking" mirroring the finding severity). On Discuss: delegate to the source reviewer agent with the user's question, then re-present.

8a. **Open-item gating.** Before dispatching any design step, call `read_open_items(status="open", severity="blocking")`. If any blocking item lists this step in `affecting_step`, do NOT dispatch. Instead, surface the item to the user via the entrypoint as a structured prompt: item ID, source, description, and a Resolve/Defer/Discuss action set. On Resolve: call `update_open_item_status` with status="resolved" and the user's note. Advisory items never gate progress; they appear in the Open Items dashboard view and are summarized in the final validation report.

8b. **Resume / restart / review on engagement load.** When loading an engagement whose session state shows any agent with status `in-progress` or `interrupted`, do NOT auto-resume. Present an AskUserQuestion with three options:
   - **Resume** — restart the in-progress agent with the same task request and accumulated context.
   - **Restart this step** — discard the in-progress state for that step and dispatch fresh.
   - **Review what's been done** — switch to the Decisions / Open Items / Artifacts dashboard views without dispatching anything.
   This matches V1's resume semantics in `progress.yaml`.

9. **Completion Status Protocol.** Every task response from a downstream agent MUST be one of four structured statuses:
   - `DONE` — work completed successfully; artifacts produced.
   - `DONE_WITH_CONCERNS` — completed but the agent flagged advisory open-items or partial outputs.
   - `BLOCKED` — could not proceed; pre-conditions not met or external dependency unavailable.
   - `NEEDS_CONTEXT` — needs additional information from another artifact or the user before continuing.
   Each response includes `STATUS`, `REASON`, `ATTEMPTED` (what the agent tried), and `RECOMMENDATION` (next action). In **auto mode**, the orchestrator halts and surfaces to the user on `BLOCKED` or `NEEDS_CONTEXT`. In **interactive mode**, it surfaces on any non-`DONE` status.

10. **Confusion Protocol.** On high-stakes ambiguity (multiple valid Solace approaches with different trade-offs, missing constraint that materially shifts the recommendation, conflicting signals in the discovery brief), STOP and present the user 2–3 options with explicit pros/cons rather than picking one silently. This applies recursively — also enforced in SADomainAgent and reviewers' system prompts.

11. **Context-Health soft directive.** On long runs (engagement >30 minutes wall time), the orchestrator periodically emits a `[PROGRESS]` summary to the entrypoint: phase, last completed step, current step, open items count, ETA. On detecting a possible loop (same diagnostic emitted ≥3 times, or same failed-fix variants attempted), the orchestrator halts and surfaces to the user.

12. **Project misuse warnings.** Before dispatching any task, validate the project state and warn (don't block) when:
    - A non-discovery step is requested but no active engagement is set: "No active project. Create or switch to one first."
    - The active engagement has no `discovery/discovery-brief.yaml`: "This project hasn't completed discovery yet. Run discovery before design steps."
    - A discovery re-run is requested for an engagement that already has a completed brief: present an AskUserQuestion — "Discovery has already run for this project. Replace the existing brief, import context from a source project, or cancel?"
    - A design scope is invoked that `skill-routing.yaml` would mark as `skipped` for this engagement: "This scope is gated off by [reason]. Override and run anyway, or cancel?"
    Warnings are surfaced via the entrypoint and require user confirmation in interactive mode; in auto mode, warnings are logged as advisory open-items and execution continues unless the warning would overwrite existing artifacts.
13. **Task dispatch format.** How to construct task requests for downstream agents: always include engagement_id, relevant decisions from the decision log (filtered by scope), discovery brief summary, and scope-specific instructions.

**Tools:**

```yaml
tools:
  # Workflow engine (config-driven sequencing via skill-routing.yaml)
  - tool_type: python
    component_module: "sa_solace_architect.tools.workflow_tools"
    function_name: "get_engagement_plan"
    tool_config:
      routing_config_path: "configs/skill-routing.yaml"   # Source of truth for which steps run when

  - tool_type: python
    component_module: "sa_solace_architect.tools.workflow_tools"
    function_name: "get_next_step"

  - tool_type: python
    component_module: "sa_solace_architect.tools.workflow_tools"
    function_name: "record_step_complete"

  - tool_type: python
    component_module: "sa_solace_architect.tools.workflow_tools"
    function_name: "handle_step_failure"

  # Session state
  - tool_type: python
    component_module: "sa_solace_architect.tools.session_tools"
    function_name: "read_session_state"

  - tool_type: python
    component_module: "sa_solace_architect.tools.session_tools"
    function_name: "update_session_state"

  # Decisions and findings
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_decision"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_decisions"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_findings"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "update_finding_status"

  # Open items
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_open_items"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "update_open_item_status"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_open_item"

  # Feedback (Phase 1 data collection; Phase 2 aggregates)
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_feedback"

  # Artifacts (read and list only — orchestrator does not write design artifacts)
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "list_artifacts"

  # Peer delegation (built-in)
  - tool_type: builtin
    tool_name: "PeerAgentTool"
```

**Grounding loaded:** Naming conventions only (baked in system prompt). The orchestrator does not need Solace platform depth — it delegates to agents that do.

**Artifacts consumed:** `meta/decisions.yaml`, `meta/findings.yaml`, `discovery/discovery-brief.yaml`, `discovery/pattern-match.yaml` (to determine which design scopes are relevant).

**Artifacts produced:** `meta/decisions.yaml` (via record_decision), `meta/findings.yaml` (via update_finding_status). Does not produce design or review artifacts directly.

---

### 4.2 SADiscoveryAgent

**File:** `configs/agents/sa-discovery.yaml`

**Purpose:** Conducts the structured interview that captures the business problem, system landscape, constraints, requirements, goals, and stakeholder map. Performs reference architecture pattern matching. Accepts intake input through four channels (see below). Produces the discovery brief that all downstream agents consume. Emits `open-items` for any incomplete or ambiguous inputs.

**Supported intake channels (Phase 1):**

1. **Conversational chat** — SADiscoveryAgent runs the interview live via the WebUI HTTP SSE Entrypoint. AskUserQuestion cards + free-text prompts streamed over SSE.
2. **HTML intake form** — Static, sectioned form served by the WebUI Entrypoint. Mirrors the V1 intake template. Includes **Save as YAML** and **Load from YAML** buttons so users can fill online, download for offline edits, and re-upload later. Submit writes a YAML artifact, triggers `parse_intake_document`, and feeds any `missing_fields` into the open-items log as advisory items.
3. **YAML file upload** — User uploads a completed YAML intake (filled offline or downloaded from the HTML form). Parsed by `parse_intake_document` with the same `missing_fields` handling.
4. **REST JSON** — `POST /engagements` with a body shaped like `tests/fixtures/bank_chat_agent.yaml`. For CI, scripted fixtures, and partner APIs.

DOCX intake is **not supported** in V2. The HTML form supersedes the V1 DOCX workflow.

**Agent Card:**

```yaml
agent_card:
  description: >
    Conducts structured architectural discovery for Solace event-driven
    architecture projects. Elicits system landscape, requirements, constraints,
    and goals. Matches the scenario against known reference architecture patterns.
    Accepts YAML intake documents (uploaded directly or generated from the HTML intake form) for offline requirements gathering.
  defaultInputModes: ["text/plain", "application/json", "file"]
  defaultOutputModes: ["text/plain", "application/json"]
  skills:
    - id: "structured_interview"
      name: "Structured Interview"
      description: "Guides the user through a structured discovery conversation covering systems, requirements, constraints, and goals."
    - id: "pattern_matching"
      name: "Reference Architecture Pattern Matching"
      description: "Matches the described scenario against known Solace reference architecture patterns."
    - id: "intake_import"
      name: "Intake Document Import"
      description: "Parses a completed YAML intake document and extracts structured discovery inputs; emits open-items for missing or ambiguous fields."
```

**System prompt core content:**

1. **Identity and scope.** Discovery agent for Solace Architect. Captures the full problem context before any design work begins.
2. **Shared preamble.** Loaded once at session start via `load_preamble()` (Decision 83). Same as orchestrator.
3. **Voice.** Senior architect conducting a scoping conversation. Questions framed in outcome terms. Short sentences.
4. **Interview structure.** The question flow from V1's `/solace-discovery`:
   - **Source-context import (new — offered first if other projects exist).** Calls `list_projects` and, if any active project shares the customer name, offers an AskUserQuestion: "Import landscape and constraints from [source project]? You'll only need to answer what's changed." If accepted, calls `import_source_context` and proceeds with the imported fields pre-populated — interview only asks about deltas.
   - Project type selection (AskUserQuestion: new build / migration / extension / SAM integration)
   - System landscape (free-text: systems, existing messaging, protocols, events, volume, schemas, vertical)
   - Reference architecture pattern matching (load and compare against three patterns)
   - Vertical-specific questions (banking, capital markets, manufacturing — triggered by vertical)
   - Requirements (mixed AskUserQuestion and free-text: delivery mode, ordering, processing guarantee, latency tier, topology)
   - Scale and operations (free-text: sites, regions, growth, data residency, team, observability, CI/CD)
   - Goals and constraints (free-text: driver, timeline, budget)
   - Execution mode selection (AskUserQuestion: auto / interactive)
5. **AskUserQuestion format.** Same format specification as orchestrator.
6. **Discovery brief output format.** Structured YAML with sections: project_name, project_type, systems (list with name, role, protocol, volume), requirements (delivery_mode, ordering, processing_guarantee, latency_tier, topology), constraints (regulatory, data_residency, budget, timeline), goals, team, pattern_match (matched_pattern, confidence, key_differences), execution_mode.
7. **Pattern matching logic.** Load the three reference architectures from grounding. Compare the user's scenario against each. Report the best match with confidence and key differences from the canonical pattern.

**Tools:**

```yaml
tools:
  # Intake parsing + export + source-context import
  - tool_type: python
    component_module: "sa_solace_architect.tools.intake_tools"
    function_name: "parse_intake_document"

  - tool_type: python
    component_module: "sa_solace_architect.tools.intake_tools"
    function_name: "export_intake_from_project"

  - tool_type: python
    component_module: "sa_solace_architect.tools.intake_tools"
    function_name: "import_source_context"

  # Project list (to detect possible source-context projects)
  - tool_type: python
    component_module: "sa_solace_architect.tools.project_tools"
    function_name: "list_projects"

  # Grounding (for reference architecture pattern matching + runtime canonical-source fetch)
  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "load_grounding"
    tool_config:
      grounding_dir: "grounding"

  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "fetch_canonical_source"

  # Artifacts
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "write_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  # Decisions
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_decision"

  # Open items (intake-source gaps and ambiguous answers)
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_open_item"
```

**Grounding loaded:**
- `solace-reference-architectures.md` — loaded via `load_grounding` tool during pattern matching
- Naming conventions — baked in system prompt

**Artifacts consumed:** YAML intake documents (uploaded by user via WebUI YAML upload, generated by the HTML intake form, or submitted via REST). All parsed by `parse_intake_document`.

**Artifacts produced:**
- `discovery/discovery-brief.yaml` — structured discovery output
- `discovery/pattern-match.yaml` — reference architecture match result

**Task request from orchestrator:** Initial engagement start, YAML intake document path, or REST JSON intake body. No prior artifacts required.

**Task response to orchestrator:** Confirmation of discovery completion. Summary of pattern match and key constraints for orchestrator to determine design scope sequence.

---

### 4.3 SADomainAgent

**File:** `configs/agents/sa-domain.yaml`

**Purpose:** Consolidates Solace technical knowledge across the three platform layers. Handles nine design scopes via task request routing. Each scope produces specific design artifacts grounded in Solace documentation. This is the agent where architectural recommendations are generated.

**Agent Card:**

```yaml
agent_card:
  description: >
    Solace platform domain expert covering Event Mesh, Application Services,
    and Platform Services. Designs topic taxonomies, selects broker types,
    designs SAM agent topologies, selects protocols, designs DMR mesh
    topologies, configures HA/DR, plans migrations, designs Micro-Integration
    strategies, and models Event Portal governance. All recommendations are
    grounded in Solace documentation.
  defaultInputModes: ["text/plain", "application/json"]
  defaultOutputModes: ["text/plain", "application/json"]
  skills:
    - id: "topic_design"
      name: "Topic Taxonomy Design"
      description: "Designs hierarchical topic taxonomy following Domain/Noun/Verb/Version/Properties pattern."
    - id: "broker_select"
      name: "Broker Selection"
      description: "Recommends event broker service, Software Event Broker, or Appliance based on requirements."
    - id: "sam_design"
      name: "SAM Topology Design"
      description: "Designs Solace Agent Mesh topology: agents, Entrypoints, SAOrchestratorAgent, A2A protocol."
    - id: "protocol_select"
      name: "Protocol Selection"
      description: "Assigns SMF, MQTT, AMQP, JMS, REST, or WebSocket per integration point."
    - id: "mesh_design"
      name: "DMR Mesh Design"
      description: "Designs DMR topology for multi-site, multi-cloud, or hybrid deployments."
    - id: "ha_dr"
      name: "HA/DR Design"
      description: "Configures HA redundancy groups and cross-site DR replication."
    - id: "migration"
      name: "Migration Planning"
      description: "Plans phased migration from Kafka, RabbitMQ, TIBCO, or IBM MQ."
    - id: "integration"
      name: "Micro-Integration Strategy"
      description: "Designs Micro-Integration strategy using the Integration Hub catalog."
    - id: "event_portal"
      name: "Event Portal Governance"
      description: "Models Event Portal application domains, event catalog, and schema governance."
```

**System prompt core content:**

1. **Identity.** Domain expert for Solace Architect. Every recommendation must be grounded in Solace documentation.
2. **Shared preamble.** Loaded once at session start via `load_preamble()` (Decision 83) — provides the full grounding discipline and naming rules.
3. **Voice.** Senior architect writing design documentation. Jargon glossed on first use. Questions framed in outcome terms. Decisions close with user impact.
4. **Scope routing.** "You will receive a task request specifying which design scope to activate. Each scope has specific inputs, outputs, and grounding requirements. Use the `load_grounding` tool to load the relevant platform reference sections before generating recommendations."
5. **Per-scope instructions.** Summary-level instructions for each of the nine scopes, covering:
   - What inputs to expect (which artifacts to read, which decisions to reference)
   - What grounding to load (which sections of platform reference, which canonical source topics)
   - What artifact to produce (filename, format, required sections)
   - What decisions to record (which design choices need D-numbered entries)
   - What antipatterns to check against (which categories from antipatterns.md)
6. **Artifact format standards.** All YAML artifacts use consistent structure. Mermaid diagrams use consistent styling. Markdown documents follow the voice directive.
7. **Antipattern checking.** Before writing any artifact, load the relevant antipattern category from `antipatterns.md` via `load_grounding` and verify the design does not match any listed antipattern. If it does, flag it in the artifact and in a decision record.

**Tools:**

```yaml
tools:
  # Grounding document loading + runtime canonical-source fetch
  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "load_grounding"
    tool_config:
      grounding_dir: "grounding"

  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "fetch_canonical_source"

  # Integration Hub catalog query
  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "query_integration_hub"
    tool_config:
      catalog_path: "grounding/integration-hub-catalog.md"

  # Artifacts
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "write_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "list_artifacts"

  # Decisions
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_decision"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_decisions"
```

**Grounding loaded (via tool, per scope):**

| Scope | Grounding sections loaded |
|-------|--------------------------|
| topic-design | Platform ref: Smart Topic Architecture, Topic best practices. Antipatterns: topic category. |
| broker-select | Platform ref: Event Brokers. Canonical sources: broker comparison URLs. |
| sam-design | Platform ref: Solace Agent Mesh (full section). Reference architectures: Pattern 1. Antipatterns: SAM category. |
| protocol-select | Platform ref: Protocols, Developer Tools. Canonical sources: API feature matrix. |
| mesh-design | Platform ref: DMR. Canonical sources: DMR overview, multi-site config. Antipatterns: mesh category. |
| ha-dr | Platform ref: HA and DR. Canonical sources: replication with DMR. |
| migration | Platform ref: Migration and lifecycle. Reference architectures: relevant pattern's migration variation. |
| integration | Platform ref: Micro-Integrations. Integration Hub catalog (via query_integration_hub). |
| event-portal | Platform ref: Event Portal. Canonical sources: Event Portal URLs. |

**Artifacts consumed:** `discovery/discovery-brief.yaml`, `discovery/pattern-match.yaml`, plus any previously completed design artifacts for the current engagement (read via `read_artifact`).

**Artifacts produced (by scope):**

| Scope | Artifact path |
|-------|---------------|
| topic-design | `topic-design/topic-taxonomy.yaml` |
| broker-select | `broker-select/broker-recommendation.yaml` |
| sam-design | `sam-design/sam-topology.yaml`, `sam-design/agent-configs/*.yaml`, `sam-design/entrypoint-configs/*.yaml` |
| protocol-select | `protocol-select/protocol-map.yaml` |
| mesh-design | `mesh-design/dmr-topology.yaml`, `mesh-design/dmr-topology.mermaid` |
| ha-dr | `ha-dr/ha-dr-design.yaml` |
| migration | `migration/migration-plan.yaml` |
| integration | `integration/integration-map.yaml` |
| event-portal | `event-portal/event-portal-model.yaml` |

**Task request from orchestrator:** Must include: `scope` (which design scope to activate), `engagement_id`, `discovery_brief` (summary or instruction to read it), `relevant_decisions` (D-numbered decisions that affect this scope), `artifacts_to_read` (list of artifact names the agent should load for context).

---

### 4.4–4.7 Reviewer Agents

All four reviewer agents share the same structural pattern. They differ in system prompt (review rubric), grounding subset, and the perspective they apply.

**Shared structure:**

```yaml
# Template — instantiated four times with different values
agent_card:
  description: "{REVIEWER_DESCRIPTION}"
  defaultInputModes: ["text/plain", "application/json"]
  defaultOutputModes: ["text/plain", "application/json"]
  skills:
    - id: "{REVIEW_ID}"
      name: "{REVIEW_NAME}"
      description: "{REVIEW_SKILL_DESCRIPTION}"

tools:
  # Artifacts (read-only — reviewers do not modify design artifacts)
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "list_artifacts"

  # Findings
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_finding"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_decisions"

  # Grounding (+ runtime canonical-source fetch)
  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "load_grounding"
    tool_config:
      grounding_dir: "grounding"

  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "fetch_canonical_source"
```

**Note on open-items.** Reviewers do NOT call `record_open_item` directly. They record findings normally. When the orchestrator's finding-resolution loop marks a finding as "deferred", `update_finding_status` automatically creates a corresponding open-item (source="review-deferred", severity mirroring the finding).

**Per-reviewer specifics:**

#### 4.4 SAArchitectReviewerAgent (`sa-review-architect.yaml`)

- **Perspective:** Architectural soundness, trade-off framing, component choices, simpler alternatives, alignment with reference architectures.
- **System prompt rubric:** For each design artifact, evaluate: (1) Does the component choice match the requirements? (2) Are there simpler alternatives that meet the same requirements? (3) Are trade-offs explicitly framed with criteria for choosing? (4) Does the design align with the matched reference architecture pattern? (5) Are cross-cutting concerns (security, observability, governance) addressed?
- **Grounding:** Reference architectures (for pattern alignment checks), platform reference (for component verification), antipatterns (architecture category).
- **Artifacts consumed:** All design artifacts, discovery brief, pattern match, decision log.
- **Artifacts produced:** `reviews/architect-review.yaml` (list of findings with severity, description, affected artifact, recommendation).

#### 4.5 SADeveloperReviewerAgent (`sa-review-developer.yaml`)

- **Perspective:** Developer experience, SDK choices, onboarding friction, topic usability, schema governance, error handling, testing.
- **System prompt rubric:** (1) Are topic names usable by developers (clear hierarchy, reasonable length, no ambiguity)? (2) Are SDK/API choices appropriate for the team's language stack? (3) Is schema governance defined (versioning, registry, evolution rules)? (4) Are error handling paths defined (DLQ, retry, alerting)? (5) Is the developer onboarding path clear (what to install, what to configure, what to test first)?
- **Grounding:** Platform reference (Developer Tools, APIs, Schema Registry), canonical sources (API feature matrix, tutorials).
- **Artifacts consumed:** All design artifacts, discovery brief (team section).
- **Artifacts produced:** `reviews/developer-review.yaml`

#### 4.6 SAOpsReviewerAgent (`sa-review-ops.yaml`)

- **Perspective:** Monitoring, failure modes, capacity planning, day-2 operations, runbook readiness, alerting.
- **System prompt rubric:** (1) Is monitoring defined (which Solace Insights dashboards, what metrics, what thresholds)? (2) Are failure modes enumerated (broker failure, WAN partition, agent failure, message loss)? (3) Is capacity planning addressed (current sizing, growth headroom, scaling triggers)? (4) Are operational procedures defined (deployment, upgrade, rollback, DR failover)? (5) Is alerting configured (who gets paged, for what, escalation path)?
- **Grounding:** Platform reference (Solace Insights, Distributed Tracing, HA/DR), canonical sources (Insights URLs, monitoring dashboards).
- **Artifacts consumed:** All design artifacts, discovery brief (team and ops sections).
- **Artifacts produced:** `reviews/ops-review.yaml`

#### 4.7 SASecurityReviewerAgent (`sa-review-security.yaml`)

- **Perspective:** Authentication, authorization, encryption, ACLs, compliance, audit, credential management.
- **System prompt rubric:** (1) Is authentication defined per integration point (OIDC, SAML, client certificates, API keys)? (2) Are ACL profiles defined (topic-level publish/subscribe permissions per client)? (3) Is TLS configured for all broker connections? (4) Are credentials managed securely (no hardcoded secrets in YAML, credential store, rotation policy)? (5) Is regulatory compliance addressed (PCI-DSS, SOC 2, GDPR, data residency)?
- **Grounding:** Platform reference (Security and access control), canonical sources (ACL, client profile URLs), antipatterns (security category).
- **Artifacts consumed:** All design artifacts, discovery brief (regulatory constraints).
- **Artifacts produced:** `reviews/security-review.yaml`

**Task request from orchestrator (all four reviewers):** Must include: `engagement_id`, `artifacts_to_review` (list of all design artifact names), `discovery_brief_summary` (key constraints and requirements), `relevant_decisions` (all D-numbered decisions). The orchestrator dispatches all four reviewer agents in parallel.

**Task response to orchestrator:** List of findings in structured format (finding_id, severity, description, affected_artifact, recommendation). The orchestrator collects all four responses, merges findings, sorts by severity, and begins the finding resolution loop.

---

### 4.8 SAValidationAgent

**File:** `configs/agents/sa-validation.yaml`

**Purpose:** Runs consistency checks across all design artifacts, detects antipatterns, traces requirements from the discovery brief to design artifacts, and flags deferred review findings.

**Agent Card:**

```yaml
agent_card:
  description: >
    Validates Solace Architect design artifacts for consistency, completeness,
    and antipattern compliance. Traces requirements from discovery to design.
    Flags deferred review findings. Produces a validation report that gates
    blueprint assembly.
  defaultInputModes: ["text/plain", "application/json"]
  defaultOutputModes: ["text/plain", "application/json"]
  skills:
    - id: "consistency_check"
      name: "Consistency Check"
      description: "Verifies cross-artifact consistency (topic references match taxonomy, broker types match selection, etc.)."
    - id: "antipattern_detection"
      name: "Antipattern Detection"
      description: "Scans all design artifacts against the categorized antipattern library."
    - id: "requirement_tracing"
      name: "Requirement Tracing"
      description: "Traces each requirement from discovery brief to at least one design artifact."
    - id: "deferred_finding_check"
      name: "Deferred Finding Check"
      description: "Reports all review findings with status 'deferred' that remain unresolved."
```

**Tools:**

```yaml
tools:
  # Artifacts
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "write_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "list_artifacts"

  # Decisions and findings
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_decisions"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_findings"

  # Open items (validation emits new open-items for unaddressed requirements,
  # and reads existing ones to surface them in the final report)
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_open_items"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_open_item"

  # Grounding
  - tool_type: python
    component_module: "sa_solace_architect.tools.grounding_tools"
    function_name: "load_grounding"
    tool_config:
      grounding_dir: "grounding"

  # Requirement tracing
  - tool_type: python
    component_module: "sa_solace_architect.tools.validation_tools"
    function_name: "trace_requirements"
```

**Open-item production.** When `trace_requirements` flags a requirement as unaddressed, SAValidationAgent calls `record_open_item` with source="validation" and severity="blocking" (an unaddressed requirement should not pass to blueprint). When antipattern detection finds a violation, it records source="validation" severity="advisory" unless the antipattern is in the "critical" category.

**Grounding loaded:** `antipatterns.md` (full library), naming conventions (for terminology compliance scan).

**Artifacts consumed:** All design artifacts, all review artifacts, discovery brief, decision log, findings log.

**Artifacts produced:** `validation/validation-report.yaml` — structured report with: pass/fail status, consistency check results, antipattern matches found, requirement tracing matrix (requirement → artifact), deferred findings list, terminology compliance scan results.

**Task request from orchestrator:** `engagement_id`, instruction to read all artifacts and produce validation report.

---

### 4.9 SABlueprintAgent

**File:** `configs/agents/sa-blueprint.yaml`

**Purpose:** Assembles all design artifacts, applied review findings, and validation results into **five audience-specific report packs** plus a downloadable zip. Generates Mermaid diagrams. Produces the executive ROI framework. Renders each pack to both interactive HTML (via the ported V1 report generator) and static PDF (via WeasyPrint).

**Five audience packs (Phase 1):**

| Pack ID | Audience | Lens |
|---------|----------|------|
| `blueprint` | Architects, platform leads, project owners | Comprehensive engineering deliverable — full architecture, all artifacts |
| `executive` | CXOs, business sponsors, investment committee | Business case, ROI calculator, recommendation in plain language |
| `admin-ops` | Solace admin, SRE, on-call engineer | Provisioning, monitoring, runbooks — full operational depth |
| `security` | Security architect, compliance, infosec, audit | Auth, ACLs, encryption, audit trail, PII handling — full security posture |
| `developers` | Application engineers, SRE writing client code | Topics, schemas, protocols, client patterns — what they need to build correct clients |

Each pack filters the full artifact corpus to its audience's lens and renders to:
- **Interactive HTML** — single self-contained file with inline CSS/JS, branded per `configs/branding.yaml`, sidebar TOC, cross-referenced sections. Executive pack ships with an **interactive ROI calculator** (sliders, live recalculation).
- **PDF** — same content rendered via WeasyPrint. JS-driven elements (ROI sliders) render at their default values; the underlying numbers and tables are preserved.

**Agent Card:**

```yaml
agent_card:
  description: >
    Assembles the final Solace Architect engineering blueprint from all design
    artifacts, applied review findings, and validation results. Generates Mermaid
    diagrams. Renders five audience-specific report packs (Blueprint, Executive,
    Admin & Ops, Security, Developers) to both interactive HTML and static PDF.
    Produces the downloadable zip archive.
  defaultInputModes: ["text/plain", "application/json"]
  defaultOutputModes: ["text/plain", "application/json", "file"]
  skills:
    - id: "assemble_blueprint"
      name: "Blueprint Assembly"
      description: "Composes architecture document, runbook, and configs from all design artifacts."
    - id: "generate_diagrams"
      name: "Diagram Generation"
      description: "Generates up to 15 Mermaid diagram types based on available design artifacts."
    - id: "render_audience_pack"
      name: "Audience Pack Rendering"
      description: "Renders one of five audience-specific report packs (Blueprint, Executive, Admin & Ops, Security, Developers) to HTML and/or PDF."
    - id: "export_engagement"
      name: "Export Engagement"
      description: "Packages all artifacts into a downloadable zip archive."
```

**Tools:**

```yaml
tools:
  # Artifacts
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "write_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "list_artifacts"

  # Decisions and findings
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_decisions"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "read_findings"

  # Diagram availability check
  - tool_type: python
    component_module: "sa_solace_architect.tools.blueprint_tools"
    function_name: "check_diagram_availability"

  # Audience-pack rendering (5 audiences × HTML/PDF)
  - tool_type: python
    component_module: "sa_solace_architect.tools.blueprint_tools"
    function_name: "render_audience_pack"

  # Zip assembly
  - tool_type: python
    component_module: "sa_solace_architect.tools.blueprint_tools"
    function_name: "assemble_zip"
```

**Grounding loaded:** Naming conventions (baked in system prompt). No platform depth needed — SABlueprintAgent assembles, it does not generate new recommendations.

**Diagram types (from V1):**

| Diagram | Required artifacts | Split rule | Detail companion |
|---------|-------------------|-----------|------------------|
| data-flow | integration map OR topic taxonomy | — | — |
| broker-topology | broker recommendation | per-region (one diagram per deployment region) | `broker-topology-detail.md` per region |
| topic-hierarchy | topic taxonomy | — | `topic-hierarchy-detail.md` (full topic table with property semantics) |
| queue-subscriptions | topic taxonomy | per-consumer if >5 consumers | — |
| protocol-stack | protocol map | — | — |
| security-boundaries | security review | — | `security-boundaries-detail.md` (ACL profiles per client) |
| failure-modes | ops review | — | `failure-modes-detail.md` (runbook references per mode) |
| dlq-flow | topic taxonomy | — | — |
| sam-agent-topology | SAM topology | per-entrypoint if >3 entrypoints | — |
| auth-scope-flow | SAM topology | — | — |
| dmr-topology | DMR topology | per-site if >3 sites | `dmr-topology-detail.md` (link bandwidth + routing per site) |
| ha-failover | HA/DR design | — | — |
| dr-failover | HA/DR design (multi-region) | per-region | `dr-failover-detail.md` per region |
| mi-connectivity | integration map | per-backend if >8 backends | — |
| migration-coexistence | migration plan | per-phase | `migration-coexistence-detail.md` per phase |

**Split-rule semantics.** When a split rule applies, `check_diagram_availability` reports one entry per split unit (e.g., `dmr-topology-us-east`, `dmr-topology-eu-west`, `dmr-topology-ap-sg`). Each split renders an independent Mermaid file plus, where indicated, an accompanying `*-detail.md` Markdown companion with tables, link metadata, and cross-references. The companion files are themselves artifacts under `blueprint/diagrams/` and appear in the Artifacts dashboard view. Split thresholds (`>5 consumers`, `>3 sites`, etc.) are heuristics — actual cutoffs are configurable via `configs/diagram-rules.yaml` (Phase 2; defaults inline for Phase 1).

**Artifacts produced:**

Source artifacts (input to audience-pack rendering):
- `blueprint/architecture.md` — complete architecture document
- `blueprint/runbook.md` — operational runbook
- `blueprint/diagrams/*.mermaid` — all available diagram types
- `blueprint/config/agents/*.yaml` — SAM agent configs (copied from sam-design)
- `blueprint/config/entrypoints/*.yaml` — Entrypoint configs
- `blueprint/config/micro-integrations/*.yaml` — MI configs
- `blueprint/config/broker/*.yaml` — broker provisioning parameters
- `executive/executive-summary.md` — CXO-level business case
- `executive/business-architecture.mermaid` — simplified business diagram (max 15 nodes)
- `executive/roi-framework.md` — ROI inputs and formulas (drives the interactive calculator)

Audience-pack outputs (5 packs × 2 formats = 10 files):
- `exports/{audience}.html` — interactive HTML, one per audience (blueprint, executive, admin-ops, security, developers)
- `exports/{audience}.pdf` — WeasyPrint-rendered PDF, one per audience

Final archive:
- `exports/engagement-package.zip` — full zip including all source artifacts, all rendered packs, and a manifest

#### 4.9a Executive pack ROI calculator (full spec)

The Executive audience pack ships with an **interactive HTML ROI calculator** (rendered as static defaults in the PDF). The calculator is loaded into the pack via `include_roi_calculator: true` in `configs/report-packs.yaml`. The full feature set is ported from V1's `dashboard/app.js` (lines ~2387–2478).

**Section structure (mirrors V1):**

1. **Costs** — fillable inputs: C1 license cost, C2 implementation cost, C3 ongoing ops cost, C4 migration cost. Each row shows a `roi-ask` hint and a `roi-ex` example value.
2. **Value drivers** — fillable inputs with auto-fill rules: V1 (revenue uplift) defaults to 90% × C1, V2 (cost avoidance) defaults to 80% × C2, V4 (faster time-to-market) defaults to 100% × C4, V6 (risk reduction) defaults to 95% × C3. Manually entered values override the auto-fill (`roi-overridden` styling — auto-hint dims with strikethrough).
3. **Indicators** — read-only computed cards: total cost, total value, net value, payback months, NPV (3yr), IRR.
4. **Sensitivity analysis** — five sliders, each with a label, hint, value display, and live recalc:
   - License cost variance (−30% to +30%)
   - Value capture rate (40% to 100%)
   - Implementation cost variance (−20% to +50%)
   - Timeline shift (−6 to +12 months)
   - Phased adoption rate (25%, 50%, 75%, 100%)
5. **Combined scenario** — primary card with current ROI under the combined slider settings, plus secondary cards showing delta vs baseline (green if positive, red if negative). Three columns: combined ROI, combined NPV, combined payback.
6. **Export and reset** — "Export inputs as YAML" button writes to `executive/roi-inputs.yaml`. "Reset to defaults" button restores all sliders to neutral and clears overrides.

**Wiring:**
- All inputs and sliders carry stable `id` attributes so the print stylesheet can render their current values in the PDF.
- The JS bundle is self-contained (no external CDN, no jQuery — vanilla JS to match V1).
- Recalculation is debounced at 50ms to keep slider drag smooth.
- The "roi-auto-filled" CSS class (green border, light-green background) marks any input still on its auto-fill value; overriding switches off the class.

`tests/test_roi_calculator.py` asserts: (a) all 5 sensitivity sliders render, (b) the 4 auto-fill rules match V1's percentages exactly, (c) the combined-scenario card recalculates correctly, (d) PDF rendering preserves all numeric values at their default state.

---

### 4.10 SAProvisioningAgent

**File:** `configs/agents/sa-provisioning.yaml`

**Purpose:** Provisions the Event Portal model designed by SADomainAgent's `event-portal` scope into a **live Solace Cloud tenant** via the EP Designer MCP. This is the **only** Solace Architect agent with side-effecting external API calls. Strictly opt-in (intake `preferences.provision_event_portal: true`). Idempotent by content match — never duplicates existing tenant objects.

**Why a separate agent (not a DomainAgent scope):**
- Side-effect isolation: every other Solace Architect agent produces inert artifacts; this one mutates a tenant.
- Different permission model: requires MCP write access and a tenant API token.
- Different opt-in behavior: skipped entirely if the intake gate is off.
- Different failure semantics: partial provisioning may need rollback or replay.

**Agent Card:**

```yaml
agent_card:
  description: >
    Provisions Solace Event Portal application domains, schemas (with versions),
    events (with versions), and applications into a live Solace Cloud tenant via
    the EP Designer MCP. Strictly opt-in (gated by intake.preferences.provision_event_portal).
    Reuse-by-content-match: never duplicates existing tenant objects. Emits AsyncAPI
    specs per provisioned application.
  defaultInputModes: ["text/plain", "application/json"]
  defaultOutputModes: ["text/plain", "application/json", "file"]
  skills:
    - id: "verify_tenant_access"
      name: "Tenant Access Verification"
      description: "Verifies EP Designer MCP availability and tenant API token scope before any write."
    - id: "provision_domains"
      name: "Application Domain Provisioning"
      description: "Creates application domains from the EP model, reusing existing domains by name match."
    - id: "provision_schemas"
      name: "Schema Provisioning"
      description: "Creates schemas + versions, reusing by content hash."
    - id: "provision_events"
      name: "Event Provisioning"
      description: "Creates event objects + versions, binding to schema versions."
    - id: "provision_applications"
      name: "Application Provisioning"
      description: "Creates application objects with publish/subscribe topic bindings."
    - id: "export_asyncapi"
      name: "AsyncAPI Export"
      description: "Exports one AsyncAPI spec per provisioned application."
```

**System prompt core content:**

1. **Identity.** Provisioning agent. Side-effects only happen with explicit user approval.
2. **Opt-in gating.** Refuse to run if `intake.preferences.provision_event_portal != true`. Refuse to run if EP Designer MCP is unavailable or the API token lacks `Designer Read+Write` scope (verified via `verify_tenant_access`).
3. **Reuse-by-content-match.** For every object, first call the MCP list operation; match by name (domains, applications), name+version (schemas, events), or content hash (schema content). Only create when no match.
4. **Per-layer user gating.** Present a confirmation to the user between layers (domains → schemas → events → applications → AsyncAPI export) in interactive mode. In auto mode, proceed unless an error occurs.
5. **Failure semantics.** On MCP error: record what was provisioned, what failed, and the recommended remediation. Do NOT silently skip — that contract is enforced by `test_ep_provision_gating.py`.
6. **State recording.** After every successful create, append to `provisioning/provisioned.yaml` with: layer, object name, EP object ID, content hash, created_at. After every reuse (match), record with `reused: true`.
7. **Naming conventions and grounding discipline.** Same as other agents.

**Tools:**

```yaml
tools:
  # MCP wrappers (verify/list/create per layer)
  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "verify_tenant_access"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "list_application_domains"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "create_application_domain"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "list_schemas"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "create_schema"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "create_schema_version"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "list_events"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "create_event"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "create_event_version"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "list_applications"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "create_application"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "export_application_asyncapi"

  - tool_type: python
    component_module: "sa_solace_architect.tools.ep_designer_mcp_tools"
    function_name: "record_provisioning_state"

  # Artifacts
  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "read_artifact"

  - tool_type: python
    component_module: "sa_solace_architect.tools.artifact_tools"
    function_name: "write_artifact"

  # Decisions and open items
  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_decision"

  - tool_type: python
    component_module: "sa_solace_architect.tools.decision_tools"
    function_name: "record_open_item"
```

**Grounding loaded:** Naming conventions (baked in system prompt). No platform-reference depth needed.

**Environment requirements (per-engagement, opt-in only):**
- `SOLACE_API_TOKEN` — must have `Designer Read+Write` scope
- `SOLACE_API_BASE_URL` — region-specific (default US; EU/AU/SG variants supported)
- EP Designer MCP installed and registered with the SAM runtime

**Artifacts consumed:** `event-portal/event-portal-model.yaml` (from SADomainAgent.event-portal scope), `discovery/discovery-brief.yaml` (for the opt-in gate).

**Artifacts produced:**
- `provisioning/provisioned.yaml` — full state of what was created vs reused
- `provisioning/provisioning-report.md` — human-readable summary (counts, errors, remediation)
- `provisioning/asyncapi/{application_name}.yaml` — one AsyncAPI spec per provisioned application

**`provisioning/provisioned.yaml` schema:**

```yaml
provisioned:
  tenant: prod-us
  base_url: https://api.solace.cloud
  started_at: 2026-05-13T15:00:00Z
  completed_at: 2026-05-13T15:04:32Z
  status: complete                       # complete | partial | failed
  layers:
    application_domains:
      - name: "retail-orders"
        ep_id: "ad-abc123"
        created: true                    # true = created; false = reused
        created_at: 2026-05-13T15:00:14Z
    schemas:
      - name: "OrderPlaced"
        version: "1.0.0"
        ep_id: "sch-def456"
        content_hash: "sha256:..."
        created: true
    events:
      - name: "OrderPlaced"
        version: "1.0.0"
        domain: "retail-orders"
        ep_id: "evt-ghi789"
        created: true
    applications:
      - name: "OrderManagementSystem"
        domain: "retail-orders"
        ep_id: "app-jkl012"
        created: true
        asyncapi_path: "provisioning/asyncapi/OrderManagementSystem.yaml"
errors: []
```

**Workflow position:** Runs *after* SABlueprintAgent and only when `intake.preferences.provision_event_portal == true`. Skipped explicitly (with skip_reason="provisioning not requested in intake") otherwise. The skip is surfaced in the Overview dashboard tile `ep_provisioning_status` ("not-requested" | "pending" | "live").

**Task request from orchestrator:** Must include `engagement_id`, confirmation that `verify_tenant_access` has succeeded, `event_portal_model_path` (artifact name), and the execution mode (auto | interactive).

---

## 5. Custom tool specifications

### 5.1 workflow_tools.py (~350 lines)

```python
# Tool: get_engagement_plan
# Input: discovery_brief (dict) — the parsed discovery brief
# Output: ordered list of steps with: step_name, agent_target, scope (if SADomainAgent),
#         dependencies (list of step_names that must complete first),
#         trigger (str — "always" | "conditional"),
#         when (list of matchers — copied from skill-routing.yaml when trigger=="conditional"),
#         included (bool — evaluated by the matcher against discovery_brief),
#         skip_reason (str — populated only when included==false)
# Logic: Reads configs/skill-routing.yaml. For each step in the routing config:
#        (a) Resolves the trigger: "always" → always included.
#            "conditional" → evaluate every clause in `when` against the discovery brief
#            using the operator vocabulary below (AND across clauses).
#        (b) Records skip_reason from skill-routing.yaml if the matcher rejects.
#        (c) Topologically sorts by dependencies.
#        Returns the ordered plan with included/skipped status and reasons.
```

**`configs/skill-routing.yaml` schema:**

```yaml
# Source of truth for engagement-plan conditional inclusion.
# Consumed by:
#   - workflow_tools.get_engagement_plan (orchestrator runtime)
#   - compute_intake_preview (intake HTML form's live preview pane)
#
# Both must agree on which design scopes will fire for a given intake.

routing:
  - step: discovery
    agent: SADiscoveryAgent
    dependencies: []
    trigger: always

  - step: topic-design
    agent: SADomainAgent
    scope: topic-design
    dependencies: [discovery]
    trigger: always

  - step: broker-select
    agent: SADomainAgent
    scope: broker-select
    dependencies: [discovery]
    trigger: always

  - step: sam-design
    agent: SADomainAgent
    scope: sam-design
    dependencies: [discovery]
    trigger: conditional
    when:
      - field: landscape.systems[*].name
        op: contains_any
        value: [chat, assistant, agent, copilot, AI]
    skip_reason: "No SAM/agent-mesh requirement detected in landscape"

  - step: protocol-select
    agent: SADomainAgent
    scope: protocol-select
    dependencies: [discovery, broker-select]
    trigger: always

  - step: mesh-design
    agent: SADomainAgent
    scope: mesh-design
    dependencies: [discovery, broker-select]
    trigger: conditional
    when:
      - field: requirements.topology
        op: in
        value: [multi-site, multi-region, hybrid-cloud]
    skip_reason: "Single-site topology — DMR mesh not required"

  - step: ha-dr
    agent: SADomainAgent
    scope: ha-dr
    dependencies: [discovery, broker-select]
    trigger: conditional
    when:
      - field: requirements.processing_guarantee
        op: in
        value: [at-least-once, exactly-once]
      - field: requirements.delivery_mode
        op: in
        value: [guaranteed, mixed]
    skip_reason: "Best-effort delivery only — HA/DR not required"

  - step: migration
    agent: SADomainAgent
    scope: migration
    dependencies: [discovery]
    trigger: conditional
    when:
      - field: landscape.existing_messaging
        op: not_empty
    skip_reason: "Greenfield deployment — no migration required"

  - step: integration
    agent: SADomainAgent
    scope: integration
    dependencies: [discovery]
    trigger: always

  - step: event-portal
    agent: SADomainAgent
    scope: event-portal
    dependencies: [discovery]
    trigger: always

  - step: provisioning
    agent: SAProvisioningAgent
    dependencies: [event-portal, blueprint]
    trigger: conditional
    when:
      - field: preferences.provision_event_portal
        op: equals
        value: true
    skip_reason: "Provisioning not requested in intake (preferences.provision_event_portal=false)"

  - step: review
    agent: [SAArchitectReviewerAgent, SADeveloperReviewerAgent, SAOpsReviewerAgent, SASecurityReviewerAgent]
    dependencies: [discovery, ">=1 design step"]
    trigger: always
    dispatch: parallel

  - step: validation
    agent: SAValidationAgent
    dependencies: [discovery, ">=1 design step"]
    trigger: always

  - step: blueprint
    agent: SABlueprintAgent
    dependencies: [">=1 design step"]
    trigger: always
```

**Operator vocabulary:**

| Operator | Semantics | Example |
|----------|-----------|---------|
| `equals` | Strict equality (string, number, bool) | `field: preferences.provision_event_portal, op: equals, value: true` |
| `in` | Value is one of a list | `field: requirements.topology, op: in, value: [multi-site, multi-region]` |
| `not_in` | Value is NOT one of a list | — |
| `contains_any` | Field is a list/string; any of the values appears | `field: landscape.systems[*].name, op: contains_any, value: [chat, agent]` |
| `contains_all` | Field is a list/string; all of the values appear | — |
| `not_empty` | Field is present and not `null`/`""`/`[]`/`{}` | `field: landscape.existing_messaging, op: not_empty` |
| `empty` | Field is missing or null/empty | — |
| `matches` | Regex match (string) | — |
| `gt` / `lt` / `gte` / `lte` | Numeric comparison | — |

**Field paths** use dot notation with `[*]` to project over arrays (JSONPath-lite). Multiple clauses in `when` are AND-ed. Use a sibling key `any_of` for OR semantics:

```yaml
when:
  any_of:
    - field: requirements.topology
      op: in
      value: [multi-site, multi-region]
    - field: requirements.processing_guarantee
      op: equals
      value: exactly-once
```

`configs/skill-routing.yaml` is the **single source of truth** for which steps fire. The intake HTML form's live preview (see `compute_intake_preview` in §5.3) reads the same file, so the preview always agrees with what will actually run.

# Tool: get_next_step
# Input: none (reads session state internally)
# Output: next step to execute, or "engagement_complete" if all steps done
# Logic: Reads completed_steps from session state. Consults the engagement plan.
#        Returns the next step whose dependencies are all in completed_steps.
#        If no step is available and not all steps are done, returns "blocked" with details.

# Tool: record_step_complete
# Input: step_name (str), timing_data (dict — see record_step_timing schema below)
# Output: confirmation
# Logic: Adds step_name to completed_steps in session state. Stores the full timing record
#        produced by record_step_timing. Marks step status as `complete` (subject to
#        compute_overview_stats's STATUS_RANK dedup).

# Tool: record_step_timing
# Used by: Every downstream agent at the end of each step
# Input:
#   step_name (str)
#   wall_sec (int) — total wall-clock duration
#   execution_sec (int) — agent execution time
#   user_wait_sec (int) — time spent blocked on user input (questions, decisions, open items)
#   per_question_wait (list of {question_id, wait_sec})
#   per_substep (list of {substep, execution_sec})
# Output: timing record written to session state's timing_data[step_name]
# Logic: Captures the same granularity as V1's progress.yaml. This is the SOLE input source
#        for dashboard_tools.compute_timeline and compute_stats_summary — without it those
#        dashboards report zero.

# Tool: handle_step_failure
# Input: step_name (str), status (str — Completion Status Protocol: DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT),
#        error_type (str), error_message (str), recommendation (str)
# Output: recommended action: "retry" | "retry_with_summary" | "skip" | "abort" | "surface_to_user"
# Logic:
#   - status=BLOCKED: surface_to_user immediately (don't retry — preconditions not met).
#   - status=NEEDS_CONTEXT: surface_to_user (ask for the missing information).
#   - status=DONE_WITH_CONCERNS: continue to next step but log the concerns.
#   - status=DONE + error (rare): first failure → retry. Second → retry_with_summary.
#                                  Third → skip with user notification.
#   On any failure: log error in session state.
```

### 5.2 grounding_tools.py (~250 lines)

```python
# Tool: load_grounding
# Input: topic (str) — e.g., "topic-architecture", "dmr", "micro-integrations",
#        "sam", "event-portal", "security", "ha-dr", "protocols", "antipatterns",
#        "reference-architectures", "naming-conventions"
# Output: relevant section content as string
# Logic: Reads from grounding/ directory. Each topic maps to a specific file and
#        section heading within that file. Returns the extracted section.
#        If topic not found, returns error listing available topics AND calls
#        record_grounding_gap so the gap surfaces in CI maintenance.

# Tool: load_jargon_list
# Used by: All agent system prompts (loaded once at agent init)
# Input: none
# Output: list of jargon term dicts ({term, definition, first_use_template})
# Logic: Reads grounding/jargon-list.json (68 EDA/Solace terms). Every agent system prompt
#        is instructed to gloss each term on first use per the template. Without this,
#        V2 artifacts read more jargon-heavy than V1's.

# Tool: query_integration_hub
# Input: backend_system (str) — e.g., "Salesforce", "PostgreSQL", "IBM MQ", "SAP"
# Output: matching Micro-Integrations from the catalog with: name, type (source/target/processor),
#         deployment (cloud-managed/self-managed/broker-integrated), support tier
# Logic: Reads integration-hub-catalog.md. Searches for entries matching the backend_system.
#        Returns structured list. If no match, returns empty list with note.
#        Used by the HTML intake form for backend-system autocomplete.

# Tool: fetch_canonical_source
# Used by: SADiscoveryAgent, SADomainAgent, reviewers (when grounding/ is insufficient)
# Input: url_or_topic (str) — a docs.solace.com URL or a topic that maps to one via canonical-sources.md
# Output: page content as text + the URL fetched
# Logic: Resolves topic → URL via canonical-sources.md if needed. Fetches with a 30s timeout.
#        Returns cleaned text (strips nav, header, footer; preserves headings + content).
#        On 4xx/5xx/timeout: returns the error and calls record_grounding_gap.
#        Allowlisted to docs.solace.com and solace.com domains by default.

# Tool: record_grounding_gap
# Used by: All agents (indirectly via load_grounding / fetch_canonical_source error paths)
# Input: topic (str), reason (str), agent (str), suggested_fix (str, optional)
# Output: confirmation
# Logic: Appends to grounding/gaps.md (or meta/grounding-gaps.yaml — see decision table).
#        Provides feedback to the grounding-maintenance CI workflow.

# Tool: check_canonical_urls
# Used by: CI only (NOT loaded by any agent). Invoked from `pytest tests/test_canonical_urls.py`
#          or a standalone CLI: `python -m sa_solace_architect.tools.grounding_tools check-urls`.
# Input: none
# Output: report — {url, status_code, last_checked_at} for every URL in solace-canonical-sources.md
# Logic: Fetches every URL with HEAD then GET fallback. Reports 200/301/302/4xx/5xx/timeout.
#        Exits non-zero if any URL is broken. Designed for nightly CI.
```

### 5.3 intake_tools.py (~200 lines)

```python
# Tool: parse_intake_document
# Used by: SADiscoveryAgent, WebUI Entrypoint (intake form submission), REST Entrypoint
# Input: file_path (str) — path to uploaded YAML intake file
# Output: structured discovery inputs (dict) matching the discovery brief format,
#         plus a list of open_items (each: id, severity, description, affecting_step)
# Logic: Parse YAML, validate against the intake schema. For each required field that is
#        missing or contains a placeholder value, emit an open_item with severity='blocking'.
#        For each optional field that is missing, emit severity='advisory'.
#        For each free-text field that is shorter than a sensible threshold (likely "TBD"),
#        emit severity='advisory'. Returns {parsed_brief, open_items}.
#        Open items are written to meta/open-items.yaml via record_open_item.
#        DOCX is NOT supported in V2 (HTML form supersedes it).

# Tool: compute_intake_preview
# Used by: WebUI Entrypoint (HTML intake form's live preview pane)
# Input: partial_intake (dict) — the in-progress form state
# Output: {
#   included_steps: list of {step, agent, scope, trigger, when_satisfied},
#   skipped_steps: list of {step, skip_reason},
#   estimated_duration: str   # heuristic, e.g. "~25 minutes for design + review"
# }
# Logic: Reads configs/skill-routing.yaml. Evaluates each step's `when` clauses against the
#        partial_intake using the same operator vocabulary as get_engagement_plan.
#        The HTML form re-fires this tool as the user types so they see, in real time, which
#        design scopes will run. This guarantees the form preview matches what the orchestrator
#        will actually execute — single source of truth (skill-routing.yaml).

# Tool: integration_hub_autocomplete
# Used by: WebUI Entrypoint (intake form's "backend system" field)
# Input: query (str) — partial system name
# Output: list of {name, type, deployment, support_tier} matches
# Logic: Thin wrapper over query_integration_hub. Returns first 10 matches for autocomplete UI.

# Tool: render_intake_markdown
# Used by: WebUI Entrypoint ("Save as Markdown" button on intake form)
# Input: intake_dict (dict) — current form state
# Output: Markdown string with section headings matching the YAML structure
# Logic: Walks the intake dict; renders each section as ## heading + table or bullet list.
#        Useful for async collaboration (diff-friendly in git, renders in any reader).

# Tool: export_intake_from_project
# Used by: WebUI Entrypoint ("Export as intake YAML"), REST Entrypoint (GET /engagements/{id}/intake/export)
# Input: source_engagement_id (str), include_decisions (bool, default True),
#        include_open_items (bool, default False)
# Output: a YAML intake document reconstructed from the source engagement's discovery brief,
#         applied review findings, and (optionally) decisions
# Logic: Reads source engagement's discovery/discovery-brief.yaml, meta/decisions.yaml (applied
#        only), and synthesizes a YAML intake equivalent. Useful for:
#          - Handing off a completed engagement as input to a new architect
#          - Regression baselines (replay the same intake against a newer V2 build)
#          - Bootstrapping a follow-on engagement with the same customer
#        Round-trips: feeding the exported YAML back through `parse_intake_document` should
#        produce a discovery brief equivalent to the source (modulo elaborated chat answers).

# Tool: import_source_context
# Used by: SADiscoveryAgent (during interview when starting a new project)
# Input: source_project_id (str), sections (list[str]) — which sections to import
#        (e.g., ["landscape.systems", "constraints.regulatory", "goals.driver"])
# Output: partial discovery brief populated from the source project's brief
# Logic: Reads source project's discovery-brief.yaml. Returns the selected sections so
#        SADiscoveryAgent can pre-populate its interview state and only ask about deltas.
#        Use case: second engagement with the same customer — most of the landscape and
#        constraints carry forward; only project goals and scope differ.
```

**HTML intake form integration:** The form binds three live behaviors to these tools:
- **Backend-system autocomplete** — every "system" row in the systems section calls `integration_hub_autocomplete` on keystroke; the dropdown shows matching catalog entries with deployment type and support tier badges.
- **Live skill-routing preview pane** — a right-side panel calls `compute_intake_preview` whenever the form state changes (debounced 300ms). Shows which design scopes will run and which will be skipped, with reasons. This matches V1's `build-intake-html.py` preview behavior.
- **Save/Load YAML** — round-trip through the entrypoint so the YAML representation stays canonical.

### 5.4 validation_tools.py (~60 lines)

```python
# Tool: trace_requirements
# Input: discovery_brief (dict), artifact_names (list of str)
# Output: requirement tracing matrix — for each requirement in the discovery brief,
#         which artifact(s) address it, or "unaddressed" if none do
# Logic: Reads the discovery brief's requirements section. For each requirement,
#        reads each artifact and checks (via keyword and semantic matching) whether
#        the requirement is addressed. Returns the matrix.
```

### 5.5 blueprint_tools.py (~250 lines)

Replaces V1's single export with audience-pack rendering and zip assembly. Delegates HTML rendering to the ported V1 generator under `sa_solace_architect/report_generator/`; PDF rendering uses WeasyPrint (added to `pyproject.toml`).

```python
# Tool: check_diagram_availability
# Used by: SABlueprintAgent, WebUI Entrypoint (Export view)
# Input: none (reads artifact list internally)
# Output: list of diagram types that can be generated, and list of types that cannot
#         (with the missing artifact for each)
# Logic: Uses the diagram-to-artifact mapping table from §4.9. Calls list_artifacts
#        internally. For each diagram type, checks whether the required artifact exists.

# Tool: render_audience_pack
# Used by: SABlueprintAgent, WebUI Entrypoint, REST Entrypoint
# Input:
#   audience (str): "blueprint" | "executive" | "admin-ops" | "security" | "developers"
#   format (str):   "html" | "pdf" | "both"
#   branding_overrides (dict, optional): per-render overrides on top of configs/branding.yaml
# Output: file path(s) of rendered artifacts, e.g. ["exports/executive.html", "exports/executive.pdf"]
# Logic:
#   1. Load configs/branding.yaml + branding_overrides.
#   2. Load configs/report-packs.yaml. Look up the entry for `audience`.
#   3. Filter the engagement artifact corpus per the audience's filter rules:
#        - dirs:           include all artifacts under these directories
#        - files:          include these specific artifact paths
#        - globs:          include artifacts matching these glob patterns
#        - exclude_dirs/exclude_files/exclude_globs: subtract from inclusion
#        - top_sections:   ordered list of top-level section titles in the rendered output
#        - decision_skills: which agents' decisions appear in the Decisions section
#        - finding_skills:  which reviewers' findings appear in the Findings section
#        - include_roi_calculator: bool (Executive pack only)
#   4. Call into sa_solace_architect.report_generator.render(audience, filtered_artifacts, branding):
#        - Selects the audience-specific template from report_generator/templates/{audience}.html
#        - Renders sections in the order from top_sections
#        - Embeds Mermaid as inline SVG (no external deps)
#        - Stitches with sidebar TOC and cross-reference anchor schema (§5.5a)
#        - For 'executive': injects the full ROI calculator JS bundle
#        - Returns a self-contained HTML string
#   5. Write HTML to exports/{audience}.html.
#   6. If format includes 'pdf': run WeasyPrint on the HTML (with print stylesheet)
#      to produce exports/{audience}.pdf. JS-driven ROI sliders render at their
#      default values in PDF; the static tables and computed totals are preserved.
#   7. Return list of generated file paths.

# Tool: assemble_zip
# Used by: SABlueprintAgent, REST Entrypoint
# Input: include_rendered_packs (bool, default True)
# Output: file path of the generated zip
# Logic: Reads all engagement artifacts. Packages into exports/engagement-package.zip
#        with a V1-compatible directory layout. Includes a manifest.yaml listing
#        every file and its source agent.
```

**`configs/branding.yaml` schema (customer-skinnable):**

```yaml
brand:
  product_name: "Solace Architect"               # Shown in report headers
  version_label: "V2.0.0-alpha"
colors:
  primary: "#093B5F"                             # Navy (V1 default)
  accent: "#00C895"                              # Green (V1 default)
  text: "#1f2937"
  muted: "#5A7A94"
fonts:
  body_family: "Figtree, sans-serif"
  mono_family: "Space Mono, monospace"
  google_fonts_url: "https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap"
logo:
  url: null                                      # Optional override; default = product wordmark
  alt: "Solace Architect"
```

Customers can override `configs/branding.yaml` (and pass per-render overrides via `branding_overrides`) without touching templates or code.

#### 5.5a `configs/report-packs.yaml` — audience-pack filter rules

Single source of truth for what appears in each audience pack. Ported verbatim from V1's `scripts/report-packs.yaml` (167 lines in V1, structurally identical). `render_audience_pack` consumes this; `tests/test_report_packs_isolation.py` asserts the filters are honored.

```yaml
packs:
  - id: blueprint
    label: "Solace Blueprint"
    audience: "Architects, platform leads, project owners"
    description: "Comprehensive engineering deliverable — full architecture, all artifacts."
    include_roi_calculator: false
    dirs:
      - discovery/
      - topic-design/
      - broker-select/
      - protocol-select/
      - sam-design/
      - mesh-design/
      - ha-dr/
      - migration/
      - integration/
      - event-portal/
      - blueprint/
      - validation/
      - reviews/
      - provisioning/
    files: []
    globs:
      - "**/*.mermaid"
    top_sections:
      - "Executive Summary"
      - "Scope & Inputs"
      - "Decisions"
      - "Connected Systems"
      - "Discovery Brief"
      - "Topic Design"
      - "Broker Recommendation"
      - "Protocol Map"
      - "SAM Design"
      - "Mesh Design"
      - "HA/DR Design"
      - "Migration Plan"
      - "Integration Strategy"
      - "Event Portal Model"
      - "Provisioning Report"   # only if provisioning ran
      - "Architecture Document"
      - "Diagrams"
      - "Operations Runbook"
      - "Validation Report"
      - "Reviews"
    decision_skills: [discovery, topic-design, broker-select, protocol-select, sam-design,
                      mesh-design, ha-dr, migration, integration, event-portal, blueprint, provisioning]
    finding_skills: [architect, developer, ops, security]

  - id: executive
    label: "Executive Team"
    audience: "CXO, business sponsors, investment committee"
    description: "Business case, ROI, and recommendation in plain language."
    include_roi_calculator: true
    dirs:
      - executive/
    files:
      - blueprint/architecture.md     # only intro section is excerpted by the template
    globs:
      - "executive/*.mermaid"
    exclude_globs:
      - "**/*-detail.md"
      - "**/wildcard-subscriptions.md"
      - "**/antipattern-report.md"
    top_sections:
      - "The Opportunity"
      - "What the Business Gets"
      - "What the Program Costs"
      - "Risk Posture"
      - "ROI Framework"               # → renders the interactive calculator
      - "Decision Asked of Leadership"
      - "Outcomes 12 Months From Now"
      - "Cross-references"
    decision_skills: [discovery, broker-select]   # high-level only
    finding_skills: []                            # no detailed findings

  - id: admin-ops
    label: "Admin & Ops"
    audience: "Solace admin, SRE, on-call engineer"
    description: "Provisioning, monitoring, runbooks — full operational depth."
    include_roi_calculator: false
    dirs:
      - broker-select/
      - ha-dr/
      - mesh-design/
      - blueprint/                    # runbook, broker config
      - provisioning/                 # if provisioning ran
    files:
      - reviews/ops-review.md
    globs:
      - "blueprint/diagrams/*broker*.mermaid"
      - "blueprint/diagrams/*ha*.mermaid"
      - "blueprint/diagrams/*dr*.mermaid"
      - "blueprint/diagrams/*topology*.mermaid"
    top_sections:
      - "Broker Recommendation"
      - "HA/DR Design"
      - "Mesh Topology"
      - "Operations Runbook"
      - "Provisioning Report"
      - "Ops Review Findings"
    decision_skills: [broker-select, ha-dr, mesh-design, provisioning]
    finding_skills: [ops]

  - id: security
    label: "Security"
    audience: "Security architect, compliance, infosec, audit"
    description: "Auth, ACLs, encryption, audit, PII — full security posture."
    include_roi_calculator: false
    dirs:
      - sam-design/                   # auth-scope flow, agent identity
    files:
      - reviews/security-review.md
      - blueprint/architecture.md     # security sections only — extracted by template
    globs:
      - "**/security-*.md"
      - "blueprint/diagrams/*security*.mermaid"
      - "blueprint/diagrams/*auth*.mermaid"
    top_sections:
      - "Security Posture Summary"
      - "Authentication Model"
      - "ACL Profiles"
      - "Encryption (Transit + Rest)"
      - "Audit and Compliance"
      - "Security Review Findings"
    decision_skills: [sam-design, broker-select]
    finding_skills: [security]

  - id: developers
    label: "Developers"
    audience: "Application engineers, SRE writing client code"
    description: "Topics, schemas, protocols, client patterns — build correct clients."
    include_roi_calculator: false
    dirs:
      - topic-design/
      - protocol-select/
      - integration/
      - event-portal/
    files:
      - reviews/developer-review.md
    globs:
      - "**/*.asyncapi.yaml"
      - "provisioning/asyncapi/*.yaml"
      - "blueprint/diagrams/*topic*.mermaid"
      - "blueprint/diagrams/*protocol*.mermaid"
      - "blueprint/diagrams/*dlq*.mermaid"
    top_sections:
      - "Topic Taxonomy"
      - "Wildcard Subscriptions"
      - "Protocol Map"
      - "Schema Inventory"
      - "Integration Patterns"
      - "AsyncAPI Specs"
      - "Developer Review Findings"
    decision_skills: [topic-design, protocol-select, integration, event-portal]
    finding_skills: [developer]
```

#### 5.5b Cross-reference anchor schema

The report generator emits stable anchors so any pack can link to any artifact, decision, or finding without breaking when filters change.

| Anchor | Target | Example |
|--------|--------|---------|
| `#grp-{skill_group}` | Section header for a skill's artifact group | `#grp-topic-design` |
| `#art-{path-slug}` | A specific artifact section (slug = path with `/` → `-`) | `#art-blueprint-architecture-md` |
| `#decisions` | Top of the Decisions section | — |
| `#decision-{D-number}` | A specific decision row | `#decision-D7` |
| `#findings` | Top of the Findings section | — |
| `#finding-{F-number}` | A specific finding row | `#finding-F12` |
| `#open-items` | Top of the Open Items section | — |
| `#open-item-{Q-number}` | A specific open item | `#open-item-Q3` |
| `#diagram-{name}` | A specific Mermaid diagram | `#diagram-topic-hierarchy` |

Links use `class="xref-link"` (dashed underline, transitions to brand accent on hover — matches V1 styling).

### 5.6 ep_designer_mcp_tools.py (~400 lines)

Thin Python wrappers over the EP Designer MCP server tools. Each function adds: opt-in guard (checks `intake.preferences.provision_event_portal`), reuse-by-content-match logic, structured error mapping (MCP error → `ToolResult` with remediation hints), and `provisioned.yaml` state updates.

```python
# Tool: verify_tenant_access
# Used by: SAProvisioningAgent (always called first)
# Input: none
# Output: {available: bool, token_scope: str, base_url: str, error: str|None}
# Logic: Calls a benign MCP read operation (list_application_domains with limit=1).
#        Verifies the configured SOLACE_API_TOKEN has Designer Read+Write scope.
#        On failure, returns a structured error with remediation hint.

# Tool: list_application_domains / create_application_domain
# Tool: list_schemas / create_schema / create_schema_version
# Tool: list_events / create_event / create_event_version
# Tool: list_applications / create_application
# Tool: export_application_asyncapi
# All: thin MCP wrappers. Each create_* function FIRST calls the matching list_*
#      and matches by:
#        - domains, applications: exact name match
#        - schemas: name + content hash match (uses canonical JSON-stable hash)
#        - events: name + version match, plus schema_version_id consistency
#      Returns {ep_id, created: bool, reused: bool, action_taken: str}.

# Tool: record_provisioning_state
# Used by: SAProvisioningAgent (after every create or reuse decision)
# Input: layer (str), name (str), ep_id (str), created (bool), metadata (dict)
# Output: confirmation
# Logic: Appends to provisioning/provisioned.yaml.
```

**Error handling contract.** If the EP Designer MCP is unavailable, `verify_tenant_access` returns `available: False` and the agent halts before any side-effects. If a create_* call fails partway through provisioning, the agent records what was committed in `provisioned.yaml` with `status: partial`, writes the failing object's remediation hint into `provisioning-report.md`, and records a blocking open-item with source="provisioning". **The agent does NOT silently skip on MCP unavailability** — this contract is enforced by `tests/test_ep_provisioning.py`.

---

## 6. Entrypoint specifications

**Both entrypoint surfaces ship in a single SAM entrypoint plugin: `solace-architect-webui-entrypoint`.** The WebUI (HTTP-SSE chat + dashboard SPA + intake form + audience-pack viewer) and the REST API (programmatic access for CI and partners) share routes, state, auth config, and the path-traversal guard. They are described separately below for clarity but live in one plugin (see §10).

### 6.1 WebUI Entrypoint

**File:** `configs/entrypoints/webui.yaml`

**Type:** HTTP SSE Entrypoint (SAM's built-in pattern), extended with static-asset serving for the dashboard, intake form, and audience-pack reports.

**Purpose:** Single browser surface for the entire engagement experience. Three faces:

1. **Conversational chat** — streaming agent interaction via SSE. AskUserQuestion cards, finding resolution cards, in-chat artifact previews (Mermaid renders inline, YAML/markdown blocks are syntax-highlighted and collapsible).
2. **Dashboard** — six read-only views matching V1 parity (Overview, Timeline, Decisions, Open Items, Artifacts, Stats), plus the Export pack-selection view.
3. **Static surfaces** — HTML intake form, hosted audience-pack reports, and PDF downloads.

All surfaces share a left sidebar with the **project switcher** (list active projects, switch active, create new) and a global version stamp. A **dark-mode toggle** lives in the header.

**Key configuration:**

```yaml
entrypoint_type: http_sse
port: ${WEBUI_PORT:8080}
static_assets_dir: webui/                  # Serves dashboard/, intake/, assets/
report_assets_dir: artifacts/exports/      # Serves hosted audience-pack HTML reports
auth:
  type: ${AUTH_TYPE:none}      # none | oidc — Phase 1 default: none (anonymous)
  oidc_issuer: ${OIDC_ISSUER:}
  oidc_client_id: ${OIDC_CLIENT_ID:}
branding_config: configs/branding.yaml
```

**Conversational routes:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/chat/message` | User message → A2A task request to SAOrchestratorAgent |
| GET | `/api/chat/stream/{session_id}` | SSE stream of status + response events |
| POST | `/api/chat/decision` | User selection on an AskUserQuestion card |
| POST | `/api/chat/finding-action` | User Apply/Defer/Discuss action on a finding |
| POST | `/api/chat/open-item-action` | User Resolve/Defer/Discuss on a blocking open item |
| POST | `/api/feedback` | User submits a feedback entry on any agent/skill output (scope + rating + note) |

**Project switcher routes:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects` | List projects (calls `list_projects` tool) |
| POST | `/api/projects` | Create new project (calls `create_project`) |
| POST | `/api/projects/{id}/switch` | Set active engagement |
| POST | `/api/projects/{id}/archive` | Archive project |

**Intake form routes:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/intake` | Serve the static HTML intake form (sectioned, mirrors V1 template) |
| POST | `/api/intake/submit` | Submit form fields → writes YAML artifact → triggers `parse_intake_document` |
| POST | `/api/intake/upload-yaml` | Upload pre-filled YAML → triggers `parse_intake_document` |
| GET | `/api/intake/download-yaml` | Download current form state as YAML (Save as YAML button) |
| GET | `/api/intake/download-markdown` | Download current form state as Markdown (Save as Markdown button) |
| POST | `/api/intake/load-yaml` | Hydrate the form from an uploaded YAML (Load from YAML button) |
| GET | `/api/intake/export-from-project/{source_id}` | Generate a YAML intake from a completed project (Export as intake button) |

The HTML form is **submit-deferred**: typing into fields stays client-side until Submit, Save, or Load. Save and Load round-trip through the entrypoint so the YAML representation stays canonical.

**Live status bar (sticky top banner on every dashboard view):**

| Element | Behavior |
|---------|----------|
| Active step indicator | Calls `GET /api/dashboard/active-step` every 2s. Shows currently-running `{agent}/{scope}` with elapsed time, or "Idle" if nothing is running. |
| User-waiting indicator | When `user_waiting: true`, badge turns amber and links to the open question/decision/open-item card in the chat surface. |
| Refresh discipline | All other dashboard panels poll their own endpoints every 10s. UI state (scroll position, active TOC entry, expanded artifact panes) is preserved across refreshes — match V1's `pollData` / `pollFingerprint` semantics. |
| Right-hand "On this page" TOC | Auto-built from `[data-toc]` elements and `h2` headings. Active-section tracking on scroll. **Present on every dashboard view** (Overview, Timeline, Decisions, Open Items, Artifacts, Stats, Export). |
| Copy-raw-source buttons | Every rendered artifact preview (Mermaid, YAML, Markdown, JSON) carries a "Copy raw source" button next to its title that copies the underlying source to the clipboard. Implementation: hidden `<textarea>` per artifact + `navigator.clipboard.writeText`. Matches V1's per-artifact copy convention. |

**Dashboard routes (each serves a static SPA shell that hydrates via JSON APIs):**

| View | UI route | Data API | Underlying tool |
|------|----------|----------|----------------|
| Overview | `/dashboard/overview` | `GET /api/dashboard/overview` | `compute_overview_stats` |
| Timeline | `/dashboard/timeline` | `GET /api/dashboard/timeline` | `compute_timeline` |
| Decisions | `/dashboard/decisions` | `GET /api/decisions` | `read_decisions` |
| Open Items | `/dashboard/open-items` | `GET /api/open-items` | `read_open_items` |
| Artifacts | `/dashboard/artifacts` | `GET /api/artifacts` + `GET /api/artifacts/{name}` | `list_artifacts`, `read_artifact` |
| Stats | `/dashboard/stats` | `GET /api/dashboard/stats` | `compute_stats_summary` |
| Export | `/dashboard/export` | `GET /api/exports/availability` | `check_diagram_availability` |
| Status bar (all views) | — | `GET /api/dashboard/active-step` | `compute_active_step` |

The Artifacts view renders a V1-style **filetree** in a right-hand sidebar (grouped by skill category), counts-by-extension tiles, and a "By Skill" horizontal bar chart. Clicking an artifact loads it into the center pane with appropriate rendering (Mermaid → SVG, YAML → highlighted, Markdown → rendered).

**Audience-pack routes (5 packs × HTML + PDF):**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/exports/render` | Render one or more audience packs (calls `render_audience_pack` per audience) |
| GET | `/reports/{engagement_id}/{audience}` | Serve the rendered HTML report (interactive) |
| GET | `/reports/{engagement_id}/{audience}.pdf` | Serve the rendered PDF (static) |
| GET | `/api/exports/zip` | Download the full engagement zip |

`{audience}` is one of `blueprint`, `executive`, `admin-ops`, `security`, `developers`. The HTML reports are interactive (ROI calculator sliders work in the Executive pack); the PDFs are WeasyPrint-rendered and show ROI inputs at their current default values.

**Structured payload contracts (rendered by frontend as interactive cards):**

- `AskUserQuestion` — decision brief: D-number, context paragraph, recommendation blockquote, per-option pros/cons, options array.
- `FindingResolution` — finding ID, severity, description, affected artifact, recommendation, action set [Apply, Defer, Discuss].
- `OpenItemPrompt` — item ID, severity, source, description, action set [Resolve, Defer, Discuss].
- `ArtifactPreview` — artifact name, type (mermaid | yaml | markdown), content, collapse hint.

**Path-traversal guard (required for all artifact endpoints):** `GET /api/artifacts/{name}`, `GET /reports/{engagement_id}/{audience}`, `GET /engagements/{id}/exports/{audience}.{html,pdf}`, and any other route that accepts a user-supplied path component MUST reject:
- Paths containing `..` segments
- Absolute paths (starting with `/`)
- Paths resolving outside the engagement's artifact namespace after normalization
- Symbolic links pointing outside the namespace

Implementation: every entrypoint route that takes a path parameter passes it through a `safe_artifact_path(engagement_id, name)` helper that returns the resolved absolute path within the engagement scope or raises `PathTraversalError` (mapped to HTTP 400). Mirrors V1's `dashboard.ts` guard.

Also: every `/api/*` response MUST include `Cache-Control: no-store` to prevent stale dashboard state (V1's `json()` helper convention).

**Browser support:** modern evergreen — Chrome, Safari, Firefox, Edge (last 2 versions). No IE. Mobile is best-effort; the dashboard is designed for desktop.

**Accessibility:** WCAG 2.1 AA "best effort" for HTML reports and dashboard. Not certified.

**Theme toggle behavior.** Dark-mode toggle lives in the header. On toggle:
1. Set `data-theme="dark"` (or "light") on `<body>` — flips all CSS variables.
2. Persist choice in `localStorage` (`solace-architect-theme`); restore on next page load.
3. **Re-initialize Mermaid** with the new theme variables (`mermaid.initialize({ theme: 'dark', themeVariables: { … } })`) and re-render every visible Mermaid diagram. Otherwise diagrams render with the previous theme's colors and look broken. Matches V1.

Phase 2 deferral: per-user theme persistence via the entrypoint (so theme follows the user across browsers). Phase 1 is per-browser via `localStorage`.

**Version stamp:** Footer shows `SOLACE ARCHITECT V2.0.0-alpha` (sourced from `pyproject.toml`).

### 6.2 REST Entrypoint

**File:** `configs/entrypoints/rest.yaml`

**Type:** REST Entrypoint (SAM's built-in pattern)

**Purpose:** Programmatic invocation for automated testing, CI integration, and partner APIs. Parity with WebUI capabilities for headless use.

**Project lifecycle:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/engagements` | List projects (filter `?include_archived=true`) |
| POST | `/engagements` | Create a new engagement (body may include scripted intake matching `bank_chat_agent.yaml`) |
| POST | `/engagements/{id}/archive` | Archive a project |
| POST | `/engagements/{id}/message` | Send a message to an active engagement |
| GET | `/engagements/{id}/status` | Current engagement status (phase, active_step, execution_mode) |

**Intake:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/engagements/{id}/intake` | Submit YAML intake body (programmatic equivalent of the HTML form) |
| POST | `/engagements/{id}/intake/upload` | Multipart YAML upload |
| GET | `/engagements/{id}/intake/export` | Export the engagement's state as a replayable YAML intake (for handoff / replay / regression baseline) |

**Engagement state:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/engagements/{id}/artifacts` | List all artifacts (optional `?category=` filter) |
| GET | `/engagements/{id}/artifacts/{name}` | Fetch a specific artifact |
| GET | `/engagements/{id}/decisions` | Get the decision log |
| GET | `/engagements/{id}/findings` | Get the findings log (optional `?status=` filter) |
| GET | `/engagements/{id}/open-items` | Get open items (optional `?status=`, `?severity=`, `?source=` filters) |
| POST | `/engagements/{id}/open-items/{item_id}/resolve` | Resolve an open item (body: `{resolution_note}`) |

**Dashboard data:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/engagements/{id}/stats/overview` | Overview tile data (`compute_overview_stats`) |
| GET | `/engagements/{id}/timeline` | Per-skill execution + wait time (`compute_timeline`) |
| GET | `/engagements/{id}/stats` | Stats summary (`compute_stats_summary`) |

**Exports (5 audience packs × HTML + PDF + zip):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/engagements/{id}/exports/availability` | Which packs and diagrams can be generated given current artifacts |
| POST | `/engagements/{id}/exports/render` | Body: `{audience: "blueprint"\|"executive"\|"admin-ops"\|"security"\|"developers", format: "html"\|"pdf"\|"both"}` |
| GET | `/engagements/{id}/exports/{audience}.html` | Fetch rendered HTML report |
| GET | `/engagements/{id}/exports/{audience}.pdf` | Fetch rendered PDF |
| GET | `/engagements/{id}/exports/engagement-package.zip` | Download full zip archive |

---

## 7. Build and test prerequisites

### 7.1 Environment requirements

- Python 3.11+
- SAM CLI (`pip install solace-agent-mesh`)
- Solace event broker (Cloud Developer tier for testing, or local Docker broker) — the broker credentials are a **client username** for pub/sub only; Solace Architect plugins never call SEMP or any broker admin API
- LLM access via the LiteLLM wrapper bundled with SAM/ADK — configured via three env vars: `LLM_SERVICE_GENERAL_MODEL_NAME`, `LLM_SERVICE_ENDPOINT`, `LLM_SERVICE_API_KEY` (see §2.1)
- WeasyPrint and its system deps (for PDF rendering of audience packs):
  `pip install weasyprint` plus platform fonts/libraries per the WeasyPrint install guide
- V1 HTML report generator: ported into `src/sa_solace_architect/report_generator/`.
  This is a one-time port (templates + CSS + ROI calculator JS + stitching pipeline)
  rather than a runtime dependency. Maintained in-tree.

**`pyproject.toml` dependency additions over V1:**
- `weasyprint` (PDF rendering)
- `pyyaml` (already implicit)
- `jinja2` (used by the ported report generator's template engine)

**Optional dependencies (only required when EP provisioning is opted in):**
- **EP Designer MCP server** — install per Solace EP Designer MCP documentation; register with the SAM runtime so SAProvisioningAgent's tools are routable. Without it, SAProvisioningAgent's `verify_tenant_access` returns `available: false` and the agent halts before any side-effects.
- `SOLACE_API_TOKEN` env var with `Designer Read+Write` scope
- `SOLACE_API_BASE_URL` env var (region-specific; defaults to US)

### 7.2 Local development setup (test-harness + plugins)

V2 is distributed as plugins (see §10). Local development uses the `test-harness/` SAM project that installs the plugins in editable mode.

```bash
# 1. Clone this repo
git clone https://github.com/<your-org>/sam-solace-architect.git
cd sam-solace-architect

# 2. Install the shared core library in editable mode
pip install -e ./solace-architect-core/

# 3. Install plugins in editable mode (any subset under active development)
for plugin in orchestrator discovery domain reviewer-architect reviewer-developer \
              reviewer-ops reviewer-security validation blueprint webui; do
  pip install -e "./plugins/solace-architect-${plugin}/"
done
# Provisioning is opt-in; install only if EP Designer MCP is configured:
pip install -e ./plugins/solace-architect-provisioning/

# 4. Initialize the test-harness SAM project
cd test-harness/
cp .env.example .env
# Edit .env: set NAMESPACE, SOLACE_BROKER_*, model API key, optionally SOLACE_API_TOKEN

# 5. Run
sam run                          # Starts every installed plugin
```

**For end-users consuming the published plugins** (after community-repo PRs are merged):

```bash
# One-time: register the community registry (or skip if already added)
sam plugin catalog
# + Add Registry → https://github.com/solacecommunity/solace-agent-mesh-plugins, name "Community"

# Install plugins
sam plugin add solace-architect-webui-entrypoint --plugin solace-architect-webui-entrypoint
sam plugin add solace-architect-orchestrator --plugin solace-architect-orchestrator
sam plugin add solace-architect-discovery --plugin solace-architect-discovery
sam plugin add solace-architect-domain --plugin solace-architect-domain
sam plugin add solace-architect-blueprint --plugin solace-architect-blueprint
# ... add reviewers/validation as desired

# `solace-architect-core` arrives automatically as a Python dependency.

sam run
```

### 7.3 Test sequence

**Phase 1: Unit tests**
```bash
python -m pytest tests/test_agent_definitions.py        # YAML validity
python -m pytest tests/test_terminology.py              # Forbidden term scan
python -m pytest tests/test_tools.py                    # Tool unit tests
python -m pytest tests/test_token_budgets.py            # Per-agent prompt size ceilings
python -m pytest tests/test_report_packs_isolation.py   # Audience-pack content isolation
python -m pytest tests/test_ep_provisioning.py          # EP provisioning opt-in/MCP-unavailable gating
python -m pytest tests/test_roi_calculator.py           # Auto-fill rules, sensitivity sliders, PDF preservation
python -m pytest tests/test_skill_routing.py            # Operator vocabulary + matchers against fixtures
python -m pytest tests/test_path_traversal.py           # Entrypoint artifact-path safety
python -m pytest tests/test_canonical_urls.py           # CI-only: URL health-check
```

**Per-test purpose:**

| Test file | What it asserts |
|-----------|-----------------|
| `test_agent_definitions.py` | All sa-*.yaml configs parse; required fields present; tool references resolve to existing functions |
| `test_terminology.py` | No forbidden terms (`connector`, `QoS`, `orchestrator agent`, etc.) appear in agent system prompts or templates |
| `test_tools.py` | Unit tests for every tool in §3 and §5; uses fakes for SAM ArtifactService/SessionService |
| `test_token_budgets.py` | Each agent's system prompt is ≤40K tokens; total across all agents ≤200K. Mirrors V1's `test/skill-token-budget.test.ts`. Fails CI if a prompt grows beyond budget |
| `test_report_packs_isolation.py` | For each of 5 audience packs: (a) only artifacts whose paths match the pack's filter rules appear; (b) `decision_skills` filter is honored; (c) `finding_skills` filter is honored; (d) Executive pack contains no technical detail leakage (no `topic-taxonomy`, `wildcard-subscriptions`, `antipattern-report`, etc.) |
| `test_ep_provisioning.py` | Three contracts: (a) SAProvisioningAgent refuses to run when `preferences.provision_event_portal != true`, (b) when MCP is unavailable, `verify_tenant_access` returns `available: false` AND the agent halts — does NOT silently skip, (c) opt-in skip is visible in dashboard `skip_reasons` |
| `test_roi_calculator.py` | (a) 5 sensitivity sliders render with correct labels and ranges, (b) auto-fill: V1=90%×C1, V2=80%×C2, V4=100%×C4, V6=95%×C3, (c) combined-scenario card recalculates correctly, (d) PDF rendering preserves all numeric values at default state |
| `test_skill_routing.py` | (a) Every operator (equals/in/contains_any/not_empty/etc.) evaluates correctly against fixture inputs, (b) AND across `when` clauses, (c) OR via `any_of` block, (d) skip_reason is populated when a step is excluded |
| `test_path_traversal.py` | Entrypoint artifact endpoints reject paths that escape the engagement's artifact namespace (`../`, absolute paths, symbolic links). See path-traversal guard requirement below |
| `test_canonical_urls.py` | CI-only nightly job. Fetches every URL in `solace-canonical-sources.md`. Exits non-zero if any URL is broken |

**Phase 2: Smoke test**
```bash
# With SAM running, send a scripted bank chat agent discovery via REST entrypoint:
curl -X POST http://localhost:8080/engagements \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/bank_chat_agent.yaml

# Verify: discovery-brief.yaml and pattern-match.yaml exist in artifacts
# Verify: pattern match identifies Pattern 1 (multi-system AI assistant)
```

**Phase 3: End-to-end**
Run the full bank chat agent scenario through the WebUI Entrypoint:
1. Start engagement → discovery interview → discovery brief produced
2. Orchestrator generates plan → sequences design agents
3. SADomainAgent executes each design scope → design artifacts produced
4. Four reviewer agents run in parallel → findings produced
5. Finding resolution loop → findings applied or deferred
6. SAValidationAgent → validation report produced
7. SABlueprintAgent → blueprint, diagrams, executive summary, export produced

**Pass criteria:** All design artifacts exist, validation report shows pass, no forbidden terminology in any artifact, blueprint is assembled, export package is downloadable.

### 7.4 Reference-architecture test fixtures

Three fixtures matching V1's three reference-architecture patterns (V1's `test/fixtures/scenarios.ts`):

| Fixture | Pattern | Triggers |
|---------|---------|----------|
| `tests/fixtures/bank_chat_agent.yaml` | Pattern 1 — Multi-system AI assistant | `sam-design` (chat system in landscape), `integration` (CRM + DB + KB backends), `ha-dr` (PCI compliance) |
| `tests/fixtures/market_data_distribution.yaml` | Pattern 2 — Real-time market data | `topic-design` (high-fan-out wildcards), `mesh-design` (multi-site DMR), `protocol-select` (MQTT + SMF) |
| `tests/fixtures/hybrid_it_ot.yaml` | Pattern 3 — Hybrid IT/OT manufacturing | `migration` (legacy MQ), `integration` (OT protocols), `event-portal` (governance for shared schemas) |

Each fixture is scripted discovery input that can be replayed without interactive user input. The bank-chat fixture is the canonical smoke test; the other two exercise paths through the workflow that bank-chat doesn't.

`tests/fixtures/bank_chat_agent.yaml` — contains all answers to the discovery interview for the retail banking chat agent scenario from V1's GETTING-STARTED.md:

```yaml
project_name: "retail-banking-chat-agent"
project_type: "sam-integration"
execution_mode: "auto"
systems:
  - name: "Core Banking Platform"
    role: "Account data, balances, transactions"
    protocol: "REST API (Java)"
    volume: "500/sec balance checks"
  - name: "Transaction Database"
    role: "Transaction history"
    protocol: "PostgreSQL"
    volume: "100/sec queries"
  - name: "CRM"
    role: "Customer profiles, support tickets"
    protocol: "Salesforce"
    volume: "50/sec"
  - name: "Knowledge Base"
    role: "FAQ, product info, policies"
    protocol: "Internal wiki"
    volume: "200/sec"
existing_messaging: "IBM MQ for core banking batch jobs"
channels: ["web chat (React)", "mobile app (React Native)", "Slack"]
vertical: "retail banking"
regulatory: "PCI-DSS, SOC 2, data residency (US only)"
audit: "7-year retention for financial transactions"
delivery_mode: "Mixed (Direct + Guaranteed)"
latency_tier: "sub-second"
topology: "single-site (Phase 1), multi-region (Phase 2)"
regions:
  phase_1: "us-east-1"
  phase_2: "eu-west-1 (GDPR)"
team:
  size: 6
  composition: "2 platform engineers, 4 application developers"
  solace_experience: "new to Solace"
  observability: "Datadog"
  cicd: "GitHub Actions"
timeline: "MVP in 4 months"
budget: "cloud-managed preferred"
growth: "3x volume in 2 years"
goals:
  driver: "Customer demand for self-service banking"
  preference: "Solace Cloud subscription"
```

---

## 8. Decisions made (from gap analysis)

These decisions are baked into this specification. They are not open questions.

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | A2A topic architecture | Use SAM defaults with namespace `${NAMESPACE}` (injected by install, no default) | A2A topics are protocol-prescribed; namespace is install-level |
| 2 | Context window management | One task per scope, fresh context, orchestrator curates payload | Mirrors V1's per-skill isolation; avoids context overflow |
| 3 | Agent failure recovery | Surface to user in Phase 1; code-driven retry in Phase 2+ | Need failure data before designing retry strategy |
| 4 | Prompt decomposition approach | Scenario-first (bank chat agent), agent-first sequencing within | Fastest path to working end-to-end chain |
| 5 | Testing strategy | Unit tests Phase 0, integration Phase 2, eval Phase 3 | Matches build phases |
| 6 | WebUI split | Single WebUI Entrypoint hosts chat + dashboard + intake form + audience-pack reports in Phase 1 | V1 already proves the unified surface; no reason to split |
| 7 | Export | 5 audience packs (Blueprint, Executive, Admin & Ops, Security, Developers), each rendered to HTML + PDF, plus zip archive | V1 ships 5 packs; PDF added so stakeholders without browsers can consume |
| 8 | Grounding maintenance | Separate from runtime; CI-driven; gap detection via tool | Proven V1 model with runtime gap recording |
| 9 | Multi-model strategy | Single model at launch, per-agent config from start | Need benchmarks before differentiating |
| 10 | Prompt migration | Bank chat agent path first (12 of 22 templates) | Validates decomposition approach before full coverage |
| 11 | Agent naming | `SA` prefix on every agent class, config filename, and A2A topic segment (`sa-orchestrator`, etc.) | Keeps Solace Architect agents distinct from any co-resident agents sharing the same SAM install |
| 12 | Python package | `sa_solace_architect` (matches agent prefix) | Consistency; avoids ambiguous imports if other Solace tooling is installed |
| 13 | Skill ID naming | Stay short, no SA prefix (e.g. `manage_engagement`) | Skill IDs are agent-internal; prefix would add noise without disambiguating |
| 14 | Namespace handling | `${NAMESPACE}` env var with **no default**; misconfigured SAM install fails loud rather than routing on a fallback value | Prevents silent cross-install bleed |
| 15 | Intake modes (Phase 1) | 4 channels: conversational chat, HTML intake form (with Save/Load YAML), YAML file upload, REST JSON | Covers live, offline, scripted, and CI use cases |
| 16 | DOCX intake | Dropped from V2 | HTML form supersedes the V1 DOCX template; removes a parsing dependency |
| 17 | Open-items concept | New `meta/open-items.yaml` artifact category with severity `blocking`/`advisory` and sources `intake`/`discovery`/`review-deferred`/`validation` | V1 dashboard's "open questions" framing is load-bearing; needs first-class data model |
| 18 | Open-item gating | SAOrchestratorAgent halts dispatch on any `blocking` open item affecting the next step | Prevents downstream agents from designing on top of unanswered questions |
| 19 | Multi-project model | Multi-project from day one, with `meta/projects.yaml` registry stored under reserved `__system__` engagement | V1 already has a project switcher; matching it in Phase 1 avoids retrofit |
| 20 | Concurrent editing | Last-write-wins with soft warning in Phase 1; optimistic concurrency control deferred | Real-time multi-architect editing is unproven need |
| 21 | Authentication model | Anonymous in Phase 1; OIDC-aware identity tagging in Phase 2 | Keeps Phase 1 install simple; tags identity onto projects when it matters |
| 22 | Dashboard scope (Phase 1) | All 6 views: Overview, Timeline, Decisions, Open Items, Artifacts, Stats, plus Export | V1 parity; deferring any of these creates an inferior product |
| 23 | Audience-pack rendering | HTML + PDF for all 5 packs in Phase 1 | V1 already produces HTML for Blueprint; PDF requested for offline/print consumption |
| 24 | HTML generator | Port V1's renderer in-tree as `sa_solace_architect.report_generator` (callable from blueprint_tools) | Fastest, most reliable; preserves V1's visual quality and brand fidelity |
| 25 | PDF rendering | WeasyPrint (Python-native) | No headless browser; runs in same Python process as SAM; trades JS execution (ROI sliders) for install simplicity |
| 26 | Branding | `configs/branding.yaml` for colors, fonts, logo; per-render overrides supported | Lets customers reskin reports without touching templates or code |
| 27 | Version stamp | `V2.0.0-alpha` sourced from `pyproject.toml`, shown in dashboard footer and report headers | Matches V1's stamp convention |
| 28 | Browser support | Modern evergreen (Chrome, Safari, Firefox, Edge — last 2 versions); no IE; mobile best-effort | Dashboard is desktop-focused |
| 29 | Accessibility | WCAG 2.1 AA "best effort" for HTML reports and dashboard; not certified | Reasonable bar without certification cost |
| 30 | Phase 2 deferrals | Git push delivery, email/Slack delivery, dark-mode persistence per user (toggle is Phase 1), per-engagement OIDC identity | Lower-priority polish or integrations |
| 31 | EP Provisioning agent design | Separate SAProvisioningAgent (10th agent), not a SADomainAgent scope | Side-effect isolation: runtime tenant mutations need separate permissions, opt-in gating, and failure semantics from design-only agents |
| 32 | EP Designer MCP integration | Mandatory dependency only when EP provisioning is opted in; agent halts on MCP-unavailable, never silently skips | V1's three-way contract preserved; safer default |
| 33 | Conditional skill routing | `configs/skill-routing.yaml` with operator vocabulary (equals, in, contains_any, not_empty, etc.) | V1's hardcoded dependency_map is too thin; YAML config is shared between orchestrator and intake-form preview |
| 34 | Audience-pack filters | `configs/report-packs.yaml` as single source of truth (dirs, files, globs, top_sections, decision_skills, finding_skills per pack) | Ported verbatim from V1; required for audience-pack isolation tests |
| 35 | Intake form live preview | `compute_intake_preview` tool reads `skill-routing.yaml` and shows which steps will fire as the user types | Matches V1's `build-intake-html.py` preview; guarantees form preview equals orchestrator execution |
| 36 | Runtime grounding fetch | `fetch_canonical_source` tool with docs.solace.com / solace.com allowlist | V1's grounding rule explicitly recommends "the fetch is cheap; the error from stale training data is not" |
| 37 | Jargon-glossing | `grounding/jargon-list.json` (68 terms) loaded by every agent system prompt; gloss on first use | Without it, V2 artifacts read more jargon-heavy than V1 |
| 38 | Per-skill state dedup | `STATUS_RANK` precedence (complete > in-progress > partial > interrupted > skipped > blocked) with newest-`started_at` tiebreak | EP-provision retries would otherwise inflate counts |
| 39 | Effective-skipped logic | Steps gated off by intake (e.g. `preferences.provision_event_portal=false`) count as `skipped` with `skip_reason`, not as `pending` | Matches V1; required for accurate dashboard counts |
| 40 | Live status bar | Sticky top banner on every dashboard view, polls `compute_active_step` every 2s | Matches V1's `updateStatusBar` |
| 41 | Cross-reference anchor schema | Stable anchors (`#grp-{group}`, `#art-{path-slug}`, `#decision-{D}`, `#finding-{F}`, `#open-item-{Q}`, `#diagram-{name}`) | Audience packs need stable cross-references; matches V1's `xref-link` styling |
| 42 | Completion Status Protocol | Every agent task response returns `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` with STATUS/REASON/ATTEMPTED/RECOMMENDATION | V1 contract; required for auto-mode-stop-on-BLOCKED logic |
| 43 | Confusion Protocol | High-stakes ambiguity → STOP and present 2–3 options with pros/cons | Baked into every agent system prompt; matches V1 preamble rule |
| 44 | Timing instrumentation | `record_step_timing` tool with `wall_sec` / `execution_sec` / `user_wait_sec` / `per_question_wait` / `per_substep` | SOLE input for `compute_timeline` and `compute_stats_summary`; without it dashboards report zero |
| 45 | Resume semantics | On engagement load with any `in-progress`/`interrupted` agent, present Resume / Restart-this-step / Review-what's-done | Matches V1's `progress.yaml` resume flow |
| 46 | Path-traversal guard | All entrypoint artifact endpoints pass paths through `safe_artifact_path` helper; reject `..` / absolute / outside-namespace / symlinks | Required for WebUI + REST artifact safety; matches V1's `dashboard.ts` guard |
| 47 | Reference-architecture fixtures | Three fixtures (Pattern 1 bank chat, Pattern 2 market data, Pattern 3 hybrid IT/OT) | Exercises code paths bank-chat fixture alone doesn't (migration, mesh-design, OT integrations) |
| 48 | Token-budget tests | Per-agent system prompt ≤40K tokens, total ≤200K | Prevents silent prompt-size regression; matches V1's `test/skill-token-budget.test.ts` |
| 49 | Audience-pack isolation tests | Per-pack filter rules honored; no technical-detail leakage into Executive pack | Ports V1's `test/report-packs.test.ts` contract |
| 50 | ROI calculator feature set | 5 sensitivity sliders + combined-scenario card + 4 auto-fill rules (V1=90%×C1, V2=80%×C2, V4=100%×C4, V6=95%×C3); vanilla JS, debounced 50ms | Full V1 fidelity; lighter version would feel inferior |
| 51 | Runtime grounding gap tracker | `record_grounding_gap` tool writes to `grounding/gaps.md` when an agent can't find a source | Feeds CI grounding-maintenance workflow; matches V1 model |
| 52 | No-cache headers on /api/* | All `/api/*` entrypoint responses include `Cache-Control: no-store` | Prevents stale dashboard state; trivial port from V1 |
| 53 | Intake export from completed project | `export_intake_from_project` tool + `GET /api/intake/export-from-project/{id}` + `GET /engagements/{id}/intake/export` | Replay, handoff, regression baseline use cases; closes V1's `/solace-intake --export` capability |
| 54 | Source-context import in discovery | `import_source_context` tool; SADiscoveryAgent offers it as the first interview step if other projects exist | Second/third engagement with the same customer reuses landscape + constraints; matches V1's source-import flow |
| 55 | Diagram split-rule logic | Per-region / per-site / per-phase splits with optional `*-detail.md` Markdown companion files | V1's `/solace-diagrams` produces splits for multi-region scenarios; lossy without this |
| 56 | Mermaid theme re-init on toggle | Dark-mode toggle re-initializes Mermaid with new theme vars and re-renders visible diagrams | Otherwise diagrams render with previous theme's colors and look broken |
| 57 | Copy-raw-source buttons | Every artifact preview (Mermaid/YAML/Markdown/JSON) has a Copy button next to its title | Matches V1; trivial frontend feature users will miss if absent |
| 58 | Universal "On this page" TOC | Right-hand TOC present on ALL six dashboard views, not just Overview/Artifacts/Export | Consistent navigation across the dashboard |
| 59 | Structured write_artifact validation outputs | `write_artifact` returns separate violation lists per check (path / terminology / naming / grounding) | Enables surfacing violations as actionable items rather than a flat error string |
| 60 | `claude-instructions.md` grounding doc | **Superseded by Decision 83.** ~~Originally: baked into per-agent system prompts (§4.1–4.10); not ported into V2 grounding/.~~ Replaced by the shared `grounding/agent-preamble.md` + `load_preamble()` tool model. | Per-agent duplication would require editing 10 system prompts to fix a single wording bug. Shared preamble keeps one source of truth without restoring the cross-doc drift the original rationale warned against — `agent-preamble.md` IS the prompt content, not a parallel reference doc. |
| 61 | `MAINTENANCE.md` operational doc | **Phase 2 deliverable** outside v2spec.md; for the maintainer team's grounding-refresh cadence | Not runtime behavior; doesn't belong in the SAM build spec |
| 62 | Markdown intake download | `render_intake_markdown` tool + `GET /api/intake/download-markdown` route | Diff-friendly format for git-based async collaboration; trivial to add alongside YAML download |
| 63 | Feedback collection (Phase 1 data layer) | `meta/feedback.yaml` schema + `record_feedback` / `read_feedback` tools + `POST /api/feedback` route | Data collection from Day 1; cross-project aggregation (→ IMPROVEMENTS.md) explicitly deferred to Phase 2 |
| 64 | Project misuse warnings | SAOrchestratorAgent warns (doesn't block) on: no active project for non-discovery step / project has no discovery brief / discovery re-run would overwrite / step is gated-off | Defensive UX; prevents data loss and user confusion |
| 65 | Tier C residuals deferred | Project-compare command, 10s polling UI-state preservation detail (already noted, frontend concern), full feedback aggregation pipeline | Niche / Phase 2 / implementor concern |
| 66 | Distribution model | Family of SAM plugins (community plugins repo) + one shared PyPI library; NOT a monolithic SAM project | Per-plugin install lets users mix-and-match agents; matches existing community-repo convention (one component per plugin) |
| 67 | Plugin decomposition | 10 agent plugins (one per agent in §4) + 1 entrypoint plugin (WebUI + REST in same plugin) = 11 plugins total | Matches existing community-repo pattern (one component per plugin); reviewers cleanly map to their own plugins |
| 68 | WebUI + REST consolidation | Both entrypoint surfaces in a single `solace-architect-webui-entrypoint` plugin | Shared state, routes, auth, path-traversal guard — splitting into 2 plugins would create coordination overhead with no upside |
| 69 | Shared code packaging | `solace-architect-core` distributed as a PyPI package, NOT as a SAM plugin | SAM plugin types are agent/gateway only; standard Python dependency model is the right primitive for shared tools/configs/grounding |
| 70 | Repo monorepo with test-harness | This repo holds the core library + 11 plugin directories + a `test-harness/` SAM project for end-to-end testing | Editable installs (`pip install -e`) let plugins iterate quickly; test-harness is NOT distributed |
| 71 | Contribution flow | One PR per plugin to `solacecommunity/solace-agent-mesh-plugins/`; `solace-architect-core` releases independently to PyPI | Keeps PR reviews focused; decouples shared-library cadence from plugin cadence |
| 72 | Plugin naming | `solace-architect-<role>` for plugins, `solace_architect_<role>` for Python packages (matches community convention: `tavily`, `send-grid`, etc.) | Distinct from earlier SA-prefix decision for agent class names — plugins use kebab-case dashed names |
| 73 | Configs ownership | Default configs (`branding.yaml`, `skill-routing.yaml`, `report-packs.yaml`) ship inside `solace-architect-core`; consumers override by setting env vars or providing local overrides | Consumers don't have to clone the config files; they extend them |
| 74 | Entrypoint vs gateway terminology | SAM has renamed the resource type from "gateway" to **"entrypoint"** in user-facing docs and naming conventions. Plugin directories use the `*-entrypoint` suffix (matching the existing `cli-entrypoint` plugin). HOWEVER, the `[tool.<name>.metadata] type` field VALUE in `pyproject.toml` is still `"gateway"` — SAM kept the metadata enum unchanged for backward compat. Mirror the cli-entrypoint plugin exactly | Reduces user confusion (docs say "entrypoint" everywhere); avoids breaking SAM's plugin manifest parser by keeping the underlying enum value stable |
| 75 | Authentication strategy | **Local SQLite user/password store** managed by the WebUI entrypoint. Argon2id password hashing (`argon2-cffi`). Sessions are 256-bit random tokens stored server-side; cookies are `HttpOnly`, `SameSite=Lax`, `Secure` when over HTTPS. Failed-login rate limit: 5 failures / 5 minutes / username | Pragmatic for an internal architect tool. No IdP dependency. OIDC remains a future swap-in via `_extract_initial_claims` alone — agent layer stays unchanged. |
| 76 | First-user bootstrap + signup model | **Self-signup ON by default; first user becomes admin.** `WEBUI_ENABLE_SIGNUP=false` disables further signups after rollout. Admin CLI (`python -m solace_architect_webui_entrypoint.admin`) handles password reset, make-admin, disable-user | Lowest onboarding friction; admin-only mode available for tightly-controlled deployments via env flag |
| 77 | Auth bypass / dev mode | **`WEBUI_REQUIRE_AUTH=false`** bypasses auth entirely (every request becomes `anonymous`) | Preserves the Phase 1 development experience; production deployments should leave this unset (default `true`) |
| 78 | User-identity propagation to agents | **`current_user` `contextvars.ContextVar`** in `solace-architect-core/_user_context.py` set by the auth middleware on every request. Downstream tools read it via `get_current_user()`. The same shape (`{id, name, email, groups, source, is_admin}`) flows out through `_extract_initial_claims` to A2A so agents see real identity | Minimizes tool-signature changes; one place to swap auth backends without touching agents |
| 79 | Storage isolation | **Hybrid: per-user filesystem paths + owner-tagged registry.** Engagement artifacts live under `<SA_STORAGE_ROOT>/users/<user_id>/<engagement_id>/...` when an authenticated user is active. `__system__` engagement is shared (unscoped). `meta/projects.yaml` carries an `owner` field; `list_projects` filters by owner. Anonymous / dev-bypass mode keeps the legacy unscoped layout for back-compat. **`SA_STORAGE_ROOT` defaulting:** when unset, the entrypoint sets it (process-wide in `__init__`) to its configured `artifact_service.base_path` so the core library and SAM's filesystem artifact service share one root — no cwd-relative divergence. | Hard filesystem isolation + queryable ownership for future sharing. One change point (`_storage.safe_artifact_path`) cascades to every tool |
| 80 | UI routing model | **Route-based SPA with persistent sidebar.** Server serves the same `index.html` shell for `/`, `/projects/{id}/{view}`. Client-side router (`history.pushState`) handles view switching. `/intake/{new,edit/{id}}` is a separate static page. Bookmarkable URLs; back/forward browser buttons work | Cleaner than hash-routing; URLs are shareable within a team |
| 81 | Edit semantics | **Project name + description editable in-place** via `PATCH /api/projects/{id}` — non-owners blocked unless admin. **Discovery brief is versioned via `POST /api/projects/{id}/clone`** — creates a new project seeded with the source's brief; decisions/findings do NOT carry over. **Decisions, findings, provisioning records are append-only** | Audit integrity (decisions immutable); safe rollback via versioning rather than destructive edits |
| 82 | DB and CSRF settings | `users.db` lives at `${SA_STORAGE_ROOT}/__system__/users.db` (overridable via `WEBUI_USERS_DB`). CSRF secret: `WEBUI_CSRF_SECRET` env var (auto-generated per-startup if unset; set for cross-restart stability) | Plugin-managed state stays inside the artifact-store root; backup story is the same as for engagement artifacts |
| 83 | Shared agent preamble | **The accuracy / grounding / voice / naming / working-style discipline from V1's `claude-instructions.md` lives once at `grounding/agent-preamble.md` and is loaded by every agent via the `load_preamble()` tool** (§3.0 baseline). Each agent's `config.yaml` system prompt carries only role-specific content; the preamble is fetched and prepended at session start. Supersedes Decision 60. | One edit point for shared discipline across 10 agents (vs. 10 copies to keep in sync); saves ~5K tokens per agent in static prompt budget that goes back to role-specific work; mockable in tests. The one risk — an agent forgetting to call `load_preamble()` — is mitigated by a CI test asserting every agent's role prompt issues the call before any other tool action. |
| 84 | Per-engagement LLM token telemetry | **Append-only JSONL ledger at `meta/telemetry/llm-calls.jsonl`** — one row per LLM round-trip with `ts`/`engagement_id`/`agent`/`step_id`/`sam_task_id`/`model`/`input_tokens`/`output_tokens`/`cached_input_tokens`/`total_tokens`/`source`. Written by each agent's `after_model_callback` via the shared `record_llm_call_telemetry` helper (`solace_architect_core.agent_callbacks`), which extracts `usage_metadata` from SAM's `LlmResponse`. Read + aggregated by `read_token_usage(group_by=agent\|step\|model\|day, since, until)`. Cost calculation explicitly out of scope for Phase 1. Tier 1 (per-step roll-up into `meta/timeline.yaml`) deferred until workflow stepping is in place. | SAM's `task_context.record_token_usage` already tracks per-task within a SAM session — but it doesn't survive restarts and isn't queryable per-engagement. Persisting to engagement artifacts (under the Decision 79 per-user namespace) gives audit trail, dashboard view, and cross-session continuity. JSONL chosen over YAML for atomic append safety and cheap streaming reads. |

---

## 9. What Claude Code should deliver

**Distribution targets (see §10):**

- **1 PyPI library** — `solace-architect-core` (shared tools, schemas, grounding, default configs)
- **10 SAM agent plugins** — one per agent in §4
- **1 SAM entrypoint plugin** — `solace-architect-webui-entrypoint` (WebUI + REST)
- **1 local test-harness** — `test-harness/` SAM project for end-to-end development testing (not distributed)

**Per-deliverable detail:**

1. **`solace-architect-core` PyPI package** — every tool from §3 + §5, all YAML schemas, vendored grounding docs (including `jargon-list.json` and `gaps.md`), default `branding.yaml` / `skill-routing.yaml` / `report-packs.yaml`. Type-hinted, async signatures, `ToolResult` returns. Semver-versioned. Published to PyPI.
2. **Ten agent plugins** (one per agent in §4.1–§4.10), each with `config.yaml` (SAM agent config with sa-prefixed agent class, complete system prompt, Agent Card, tool configurations), `pyproject.toml` (depends on `solace-architect-core`), `src/solace_architect_<name>/lifecycle.py`, `README.md`. SAProvisioningAgent plugin is opt-in (gated by intake `preferences.provision_event_portal`) and adds EP Designer MCP as a documented requirement.
3. **All custom Python tools** per sections 3 and 5, with type hints, docstrings, async signatures, and `ToolResult` return types. New modules:
   - `project_tools.py` (project registry: list/create/archive/switch)
   - `dashboard_tools.py` (compute Overview/Timeline/Stats data)
   - Extensions to `decision_tools.py` for open-items (`record_open_item`, `read_open_items`, `update_open_item_status`)
   - Rewritten `blueprint_tools.py` with `render_audience_pack` and `assemble_zip`
4. **One entrypoint plugin** (`solace-architect-webui-entrypoint`) with full route coverage:
   - WebUI surface: chat + 6 dashboard views + project switcher + HTML intake form (Save/Load YAML + Markdown) + audience-pack selection + hosted reports + PDFs + live status bar + dark-mode toggle + version stamp
   - REST surface: project lifecycle + intake + engagement state + dashboard data + 5 audience packs (HTML + PDF) + zip export
   - Shared state, auth, path-traversal guard, `Cache-Control: no-store` on `/api/*`
   - `pyproject.toml` `[tool.<name>.metadata]` declares `type = "gateway"` (the metadata field value is still `"gateway"` — SAM has renamed the resource type to "entrypoint" in docs but kept the metadata field unchanged; mirrors the existing `cli-entrypoint` plugin); declares all required deps (including the ported V1 report generator via `solace-architect-core` dependency)
5. **Ported V1 HTML report generator** under `src/sa_solace_architect/report_generator/`:
   - 5 audience-specific templates
   - Sidebar TOC + cross-reference index
   - Inline Mermaid SVG embedding
   - Interactive ROI calculator (Executive pack)
   - Branded per `configs/branding.yaml`
6. **`configs/branding.yaml`** with sensible Solace defaults; customer-skinnable.
7. **WebUI static assets** under `webui/`:
   - Shell `index.html` with chat surface
   - 6 dashboard SPA views
   - HTML intake form with Save/Load YAML buttons
   - Dark-mode toggle + version stamp
8. **Open-items system end to end**: schema, tools, orchestrator gating logic, dashboard view, REST endpoints, intake-form integration.
9. **Multi-project registry**: `meta/projects.yaml` under reserved `__system__` engagement; sidebar switcher; create-new flow.
10. **Grounding documents** copied from V1 into `grounding/` directory, plus `naming-conventions.md` extracted from V1's preamble generator.
11. **Test suite** per section 7: agent definition validation, terminology compliance, tool unit tests, **audience-pack rendering snapshot tests**, and the bank chat agent fixture.
12. **README.md** with setup instructions, environment variable reference (`NAMESPACE`, `WEBUI_PORT`, `AUTH_TYPE`, `OIDC_*`, model provider keys, WeasyPrint system deps), and test commands.
13. **The system should be runnable** from the `test-harness/` directory: `pip install -e` each plugin, then `sam run` against a Solace Cloud Developer broker and an LLM API key, processing the bank chat agent fixture from discovery through blueprint generation, with all 5 audience packs rendered to HTML and PDF.

13a. **Local test-harness** (`test-harness/`) — a SAM project with `pyproject.toml` referencing every plugin in editable mode, `.env.example` listing required env vars (`NAMESPACE`, `SOLACE_BROKER_*` client credentials, `LLM_SERVICE_GENERAL_MODEL_NAME` / `LLM_SERVICE_ENDPOINT` / `LLM_SERVICE_API_KEY` for LiteLLM, optionally `SOLACE_API_TOKEN` for opt-in EP provisioning), and a `README.md` walking through the setup. Used for end-to-end testing during development. Not distributed.
14. **`configs/skill-routing.yaml`** with the full operator vocabulary and matchers for every conditional step (sam-design, mesh-design, ha-dr, migration, provisioning).
15. **`configs/report-packs.yaml`** ported verbatim from V1's `scripts/report-packs.yaml`, with per-audience filter rules.
16. **`configs/branding.yaml`** with Solace defaults; customer-skinnable.
17. **Grounding additions**: `grounding/jargon-list.json` (68 terms) and `grounding/gaps.md` (runtime gap tracker).
18. **EP Designer MCP integration** under `src/sa_solace_architect/tools/ep_designer_mcp_tools.py`: verify_tenant_access + per-layer list/create + AsyncAPI export + state recording in `provisioning/provisioned.yaml`.
19. **Cross-cutting protocols** baked into agent system prompts: Completion Status, Confusion, Context-Health, Resume/Restart/Review on load, open-item gating, finding resolution.
20. **Dashboard fidelity**: live status bar (2s poll), STATUS_RANK dedup, effective-skipped logic, cross-reference anchor schema, full V1 ROI calculator (5 sliders + combined-scenario + auto-fill rules) in the Executive pack.
21. **Path-traversal guard** on every entrypoint artifact endpoint; `Cache-Control: no-store` on all `/api/*` responses.
22. **Expanded test suite**: token-budget tests, audience-pack isolation tests, EP-provisioning gating tests, ROI calculator tests, skill-routing operator tests, path-traversal tests, CI-only canonical-URL health-check.
23. **Three reference-architecture fixtures**: `bank_chat_agent.yaml` (Pattern 1), `market_data_distribution.yaml` (Pattern 2), `hybrid_it_ot.yaml` (Pattern 3).

---

## 10. Distribution model

V2 is **not a monolithic SAM project**. It is a family of SAM plugins targeting the [Solace community plugins registry](https://github.com/solacecommunity/solace-agent-mesh-plugins) plus one shared PyPI library. Users install just the agents they want via `sam plugin add <name>`.

### 10.1 Component decomposition

**12 distributable units:**

| # | Name | Type | Distribution | Contents |
|---|------|------|--------------|----------|
| 1 | `solace-architect-core` | Python library | PyPI | All shared tools (§3 + §5), schemas, grounding docs, default configs |
| 2 | `solace-architect-orchestrator` | SAM plugin (agent) | Community plugins repo | SAOrchestratorAgent (§4.1) |
| 3 | `solace-architect-discovery` | SAM plugin (agent) | Community plugins repo | SADiscoveryAgent (§4.2) |
| 4 | `solace-architect-domain` | SAM plugin (agent) | Community plugins repo | SADomainAgent + all 9 design scopes (§4.3) |
| 5 | `solace-architect-reviewer-architect` | SAM plugin (agent) | Community plugins repo | §4.4 |
| 6 | `solace-architect-reviewer-developer` | SAM plugin (agent) | Community plugins repo | §4.5 |
| 7 | `solace-architect-reviewer-ops` | SAM plugin (agent) | Community plugins repo | §4.6 |
| 8 | `solace-architect-reviewer-security` | SAM plugin (agent) | Community plugins repo | §4.7 |
| 9 | `solace-architect-validation` | SAM plugin (agent) | Community plugins repo | §4.8 |
| 10 | `solace-architect-blueprint` | SAM plugin (agent) | Community plugins repo | §4.9 + ported V1 report generator + WeasyPrint dep |
| 11 | `solace-architect-provisioning` | SAM plugin (agent) | Community plugins repo | §4.10 + EP Designer MCP dep (opt-in) |
| 12 | `solace-architect-webui-entrypoint` | SAM plugin (gateway) | Community plugins repo | §6 — HTTP-SSE + REST routes, all 6 dashboard views, intake form, audience-pack viewer |

### 10.2 Plugin layout (per-plugin)

Every plugin folder follows the existing community-repo convention (matches `tavily/`, `send-grid/`, `filesystem/`, etc.):

```
solace-architect-<name>/
├── README.md                # Install + usage instructions, env-var reference
├── config.yaml              # SAM component config (agent or gateway)
├── pyproject.toml           # Python package + [tool.<name>.metadata] type = "agent"|"gateway"  ← metadata field VALUE stays "gateway" even though the user-facing resource type is now called "entrypoint"
└── src/solace_architect_<name>/
    ├── __init__.py
    └── lifecycle.py         # Plugin-specific init/cleanup (registers tools with the agent runtime)
```

**`pyproject.toml` requirements per plugin:**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.<plugin_name>.metadata]
type = "agent"            # or "gateway" (NB: metadata field VALUE is still "gateway" — SAM's resource-type docs say "entrypoint" but the metadata enum kept the legacy name; matches the cli-entrypoint plugin)

[project]
name = "solace-architect-<name>"
version = "0.1.0"
description = "..."
requires-python = ">=3.11"
dependencies = [
  "solace-architect-core>=0.1.0",     # all plugins depend on the core library
  # plugin-specific deps (e.g., weasyprint for blueprint, ep-designer-mcp for provisioning)
]

[tool.hatch.build.targets.wheel]
packages = ["src/solace_architect_<name>"]

[tool.hatch.build.targets.wheel.force-include]
"src/solace_architect_<name>" = "solace_architect_<name>/"
"config.yaml" = "solace_architect_<name>/config.yaml"
"README.md" = "solace_architect_<name>/README.md"
"pyproject.toml" = "solace_architect_<name>/pyproject.toml"
```

### 10.3 `solace-architect-core` library (the shared dependency)

Not a SAM plugin — a regular PyPI package. Every plugin's `pyproject.toml` declares `solace-architect-core>=X.Y.Z` as a dependency.

**Owns:**
- All Python tool modules (§3.1–3.5, §5.1–5.6)
- All YAML schemas (open-items, projects, feedback, provisioned, decisions, findings)
- Grounding docs (vendored — read-only reference within the package)
- Default configs (`branding.yaml`, `skill-routing.yaml`, `report-packs.yaml`)

**Versioning:** semver. Plugin updates can pin or accept ranges. Breaking changes to shared tools require a major bump of `solace-architect-core` AND coordinated plugin updates.

**Why a library, not a plugin:** The community plugin registry recognizes only `agent` and `gateway` types (per the existing entries — `tavily`, `send-grid`, `cli-entrypoint`, etc.). A "library" plugin type doesn't exist in SAM's convention. Standard Python dependency model is the right primitive here.

### 10.4 Test harness (local development)

`test-harness/` is a local SAM project used for end-to-end testing during plugin development. Not distributed.

```bash
cd test-harness/
pip install -e ../solace-architect-core/
pip install -e ../plugins/solace-architect-orchestrator/
# ... pip install -e for each plugin under active development
cp .env.example .env
sam run
```

Editable installs mean code changes in `plugins/<name>/src/` or `solace-architect-core/src/` reflect immediately on `sam run` restart.

### 10.5 Install flow (end user)

```bash
# One-time: register the community registry
sam plugin catalog
# + Add Registry → paste https://github.com/solacecommunity/solace-agent-mesh-plugins, name "Community"

# Install plugins (any subset)
sam plugin add solace-architect-webui-entrypoint --plugin solace-architect-webui-entrypoint
sam plugin add solace-architect-orchestrator --plugin solace-architect-orchestrator
sam plugin add solace-architect-discovery --plugin solace-architect-discovery
sam plugin add solace-architect-domain --plugin solace-architect-domain
# ... add reviewer/validation/blueprint as needed

# `solace-architect-core` is pulled in automatically as a Python dep when any plugin is installed.

sam run
```

**Minimum useful install:** orchestrator + discovery + domain + blueprint + webui. Reviewers and validation can be added later. Provisioning is opt-in.

### 10.6 Contribution flow

1. Develop in `plugins/<name>/` locally; iterate using the test-harness.
2. When a plugin is stable: open a PR to `solacecommunity/solace-agent-mesh-plugins/` with that plugin's folder copied into the repo root (one PR per plugin to keep reviews focused).
3. Once accepted, the plugin appears in `sam plugin catalog` for everyone.
4. `solace-architect-core` releases go to PyPI independently and are referenced by plugin pyproject.toml deps.
