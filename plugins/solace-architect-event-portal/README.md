# solace-architect-event-portal

`SAEventPortalAgent` — a SAM agent that wraps the upstream
[`solace-event-portal-designer-mcp`](https://pypi.org/project/solace-event-portal-designer-mcp/)
MCP server. Lets you list, create, update, and export Event Portal
objects (application domains, applications, events, schemas, schema
versions, AsyncAPI specs) against a Solace Cloud tenant through natural
language. Discoverable as a peer in the SAM mesh.

This is the single EP-touching agent in the engagement lifecycle —
serves both ad-hoc EP queries and the live-provisioning lifecycle phase.

---

## Install

Pick whichever fits your workflow.

```bash
# From the cloned repo (editable):
pip install -e plugins/solace-architect-event-portal/

# Or from a wheel:
pip install solace-architect-event-portal
```

The plugin's only runtime dependency is `solace-architect-core` —
everything else (the upstream MCP server itself) is launched on demand
via `uvx` and doesn't need to be in your virtualenv.

---

## Prerequisite: `uvx` on `$PATH`

The agent launches the MCP server as a subprocess:

```
uvx --from solace-event-portal-designer-mcp solace-ep-designer-mcp
```

`uvx` ships with [`uv`](https://docs.astral.sh/uv/getting-started/installation/).
Install once per machine:

```bash
pip install uv
# or: brew install uv  (macOS)
# or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```bash
uvx --version
```

The first `sam run` will pull `solace-event-portal-designer-mcp` into
`uvx`'s cache; subsequent runs reuse it.

---

## Sync the agent config into SAM

SAM loads agents from `sam/configs/agents/`, not from the plugin's
source tree. Copy (or symlink) the plugin's `config.yaml` once:

```bash
cp plugins/solace-architect-event-portal/config.yaml \
   sam/configs/agents/solace-architect-event-portal.yaml
```

The plugin's `config.yaml` is the authoritative source; treat
`sam/configs/agents/solace-architect-event-portal.yaml` as a synced
copy. Re-`cp` whenever the plugin updates.

---

## Required environment variables

Export these in your shell (or add to your `.env`):

```bash
# REQUIRED — your Solace Cloud API token with at least
# "Event Portal > Designer > Read" (and Write if you plan to create).
# Get one from Solace Cloud Console → API Tokens.
export SOLACE_API_TOKEN="your-solace-api-token-here"
```

The standard SAM env vars (`NAMESPACE`, `SOLACE_BROKER_*`,
`LLM_SERVICE_*`, `SA_STORAGE_ROOT`) should already be set for the rest
of your SA project — this plugin shares them.

### Optional: region override

By default the MCP server talks to the US region (`https://api.solace.cloud`).
For other regions set:

```bash
# Pick ONE of these:
export SOLACE_API_BASE_URL="https://api.solacecloud.com.au"   # Australia
export SOLACE_API_BASE_URL="https://api.solacecloud.eu"       # Europe
export SOLACE_API_BASE_URL="https://api.solacecloud.sg"       # Singapore
```

Leave unset for US.

---

## Run

If you're already running the full SA mesh, just restart SAM after
syncing the config:

```bash
cd sam/
sam run
```

You should see in the log:

```
Initializing ADK Agent 'SAEventPortalAgent' …
[SA telemetry] after_model_callback chained for agent 'SAEventPortalAgent'
SAEventPortalAgent lifecycle.init() — plugin package imported, telemetry patch installed
```

To run JUST this agent (e.g. for testing):

```bash
sam run sam/configs/agents/solace-architect-event-portal.yaml
```

---

## Use

Two modes, branched on the first user message.

### Direct mode (ad-hoc EP queries)

Pick `SAEventPortalAgent` in the WebUI's chat agent dropdown and ask:

- _"List all application domains in my Event Portal."_
- _"Show me events in the OrderManagement domain."_
- _"Export AsyncAPI for application X version Y."_
- _"Which applications publish the OrderCreated event?"_

The orchestrator can also delegate EP queries to this agent
automatically since it's discoverable in the mesh.

### Lifecycle mode (engagement-driven)

Start the message with `Phase: event-portal` (the WebUI's Progress
page does this when you click **Start Event Portal →** after
Validation completes). The agent will:

1. Read `event-portal/event-portal-model.yaml` produced by the Design
   phase
2. Dry-run a provisioning plan against your live tenant
3. Ask for confirmation (Interactive mode) or proceed (Auto mode)
4. Create domains → schemas → events → applications, reusing where
   content already matches
5. Export AsyncAPI for each application
6. Write `event-portal/plan.yaml`, `provisioned.yaml`,
   `provisioning-report.md`, and `asyncapi/*.yaml`
7. Mark `step="event-portal"` DONE / DONE_WITH_CONCERNS / BLOCKED

---

## Token security

`SOLACE_API_TOKEN` is read at agent boot from the shell environment.
Don't commit it. The plugin's `config.yaml` uses SAM's `${...}` env
substitution — the value never lands on disk in the repo.

The MCP subprocess receives the token through its own
`environment_variables` block; SAM passes it as part of the stdio
launch, not as a CLI arg, so it doesn't show in `ps`.

---

## Lifecycle role

`SAEventPortalAgent` is the single EP-touching agent in the engagement
lifecycle. It runs as a conditional step between Validation and
Blueprint, gated by `preferences.provision_event_portal` in the intake.
The prior `SAEPProvisioningAgent` plugin and its stub
`ep_designer_mcp_tools.py` wrappers were removed when this agent
absorbed the live-provisioning workflow.
