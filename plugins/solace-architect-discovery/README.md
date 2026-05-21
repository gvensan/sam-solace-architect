# solace-architect-discovery

**SAM agent plugin** — `SADiscoveryAgent`, the first lifecycle step. Refines the intake into a working discovery brief, raises blocking open-items, and picks the reference-architecture pattern that the Design phase will start from.

## Role

Reads the intake submitted from the WebUI (`discovery/intake.json` + `discovery/discovery-brief.yaml`) and:

1. **Refines the brief** — fills gaps via structured `ask_user_question` prompts (option chips + optional note). The WebUI renders these as clickable forms; the user's answer + note both come back in one round-trip.
2. **Verifies Integration Hub catalog hits** — confirms catalog match for declared source/target systems; flags unrecognized connectors as advisory items.
3. **Classifies open-items** — blocking (need answer before Design) vs advisory (can defer).
4. **Picks a reference-architecture pattern** — matches the brief against the grounding corpus and records the choice with rationale.
5. **Writes** `discovery/discovery-brief.yaml` (normalized), `discovery/discovery-summary.md`, and `discovery/discovery-report.md`.

Surfaces `step="discovery"` status (DONE / DONE_WITH_CONCERNS / BLOCKED) so the Orchestrator knows whether to advance.

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
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-discovery
sam plugin add sa_discovery --plugin solace-architect-discovery
```

## License

Apache 2.0.
