# solace-architect-orchestrator

**SAM agent plugin** — `SAOrchestratorAgent`, the central coordinator for Solace Architect engagements.

## Role

Sequences the full lifecycle by dispatching A2A tasks to the right peer agent and routing results back to the user:

```
Intake → Discovery → Design → Review (4-way fan-out) → Validation → Blueprint → Provisioning (opt-in)
```

Owns:
- **Workflow state** — knows which step the engagement is on, what comes next, what to skip per the intake preferences.
- **Execution mode** — Interactive (decision-by-decision) vs Auto (proceed with defaults, only stop on blocking decisions).
- **Review fan-out** — dispatches the 4 reviewer agents (architect / developer / ops / security) in parallel and aggregates findings.
- **Finding resolution** — collects user decisions (apply / defer / dismiss) and propagates them back to the design agents.
- **Open-item gating** — won't advance past Validation while blocking open-items remain.
- **Completion Status Protocol** — emits `step_status` records so the WebUI progress banner can render the timeline.

The orchestrator carries the `engagement_id` + `user_id` context on every peer dispatch, so downstream agents read/write the right user-scoped namespace without re-resolving.

## Required env vars

Inherited from the SAM install — same as the rest of the SA family:

| Variable | Purpose |
|---|---|
| `NAMESPACE` | A2A topic namespace. |
| `SOLACE_BROKER_URL` / `_USERNAME` / `_PASSWORD` / `_VPN` | Broker client credentials. |
| `LLM_SERVICE_GENERAL_MODEL_NAME` / `_ENDPOINT` / `_API_KEY` | LiteLLM model spec. |
| `SA_STORAGE_ROOT` | Engagement artifact root. |

See `../../test-harness/.env.example`.

## Install (development)

```bash
pip install -e ../../solace-architect-core/
pip install -e .
```

## Install (end users)

```bash
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-orchestrator
sam plugin add sa_orchestrator --plugin solace-architect-orchestrator
```

## License

Apache 2.0.
