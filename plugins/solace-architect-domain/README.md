# solace-architect-domain

**SAM agent plugin** — `SADomainAgent`, the Design phase. Walks the engagement through up to nine architecture scopes, each producing its own decisions, artifacts, and diagrams.

## Scopes

| Scope | What it covers | Primary outputs |
|---|---|---|
| `topic-design` | Topic taxonomy, hierarchy, wildcards | `topic-design/topic-taxonomy.yaml`, `topic-design/topic-design.md` |
| `broker-select` | Broker type (Solace PubSub+ Software, Appliance, Cloud), service class, sizing | `broker-select/broker-selection.yaml` + rationale |
| `protocol-select` | SMF / MQTT / AMQP / JMS / REST per client class | `protocol-select/protocol-selection.yaml` |
| `integration` | IBM MQ MI, Kafka bridges, custom microintegrations | `integration/*.yaml` + diagrams |
| `mesh-design` | DMR pattern, hub region, link count | `mesh-design/mesh-design.yaml` + topology mermaid |
| `ha-dr` | HA approach, DR replication mode, DR topology, scope | `ha-dr/ha-dr-design.yaml` + diagrams |
| `sam-design` | SAM client patterns and SDK choices | `sam-design/sam-design.md` |
| `event-portal` | Event Portal application + schema model | `event-portal/event-portal-model.yaml` |
| `migration` | Migration strategy + cutover plan | `migration/migration-plan.md` |

Scope selection comes from the discovery brief; the user can re-enter a scope mid-stream to revise.

## Modes

- **Interactive** — `ask_user_question` for every blocking decision; user picks from chips with an optional note.
- **Auto** — proceed with the agent's recommended default; only stop on blocking decisions where confidence is low.

The frontend hands each scope to the agent as its own A2A task (the "one scope per task" contract) so a long Design phase doesn't blow the LLM-call cap on one turn.

## Required env vars

| Variable | Purpose |
|---|---|
| `NAMESPACE` | A2A topic namespace. |
| `SOLACE_BROKER_URL` / `_USERNAME` / `_PASSWORD` / `_VPN` | Broker client credentials. |
| `LLM_SERVICE_GENERAL_MODEL_NAME` / `_ENDPOINT` / `_API_KEY` | LiteLLM model spec. |
| `SA_STORAGE_ROOT` | Engagement artifact root. |

## Install (development)

```bash
pip install -e ../../solace-architect-core/
pip install -e .
```

## Install (end users)

```bash
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-domain
sam plugin add sa_domain --plugin solace-architect-domain
```

## License

Apache 2.0.
