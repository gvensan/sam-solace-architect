# Solace naming conventions

Extracted from V1's preamble generator. Every agent's system prompt references this document. Together with `jargon-list.json`, it enforces consistent terminology across all artifacts.

## Component names (Solace platform)

| Use this | Not this | Notes |
|----------|----------|-------|
| Event broker / event broker service | "broker" alone, "queue server" | Solace deployment unit |
| Software Event Broker | "software broker", "PubSub+ software" | Self-managed Linux-based broker |
| Appliance Event Broker | "appliance", "PubSub+ appliance" | Hardware Solace appliance |
| Cloud event broker service | "cloud broker" | Solace Cloud managed offering |
| Solace Agent Mesh (SAM) | — | The agentic mesh; spell out on first use, then "SAM" |
| Entrypoint | "Gateway" *(legacy V1 term — SAM renamed)* | The HTTP-facing component of SAM |
| Micro-Integration | "connector", "adapter" | Solace's term for source/target/processor integrations |
| Direct messaging | "QoS 0", "fire-and-forget" | Solace direct messaging |
| Guaranteed messaging | "QoS 1/2", "persistent" | Solace guaranteed messaging with spool |
| Smart Topic | "topic name", "subject" | Hierarchical topic with semantic structure |
| Dynamic Message Routing (DMR) | "broker mesh", "cluster" | Solace's mesh routing |
| Event Portal | "design tool", "schema registry" | Solace's design + governance tool |
| Distributed Tracing | "tracing", "logs" | Solace's tracing capability |

## Agent / tool naming (this V2 codebase)

- **Agent class names** — `SA` prefix + PascalCase (`SAOrchestratorAgent`, `SADomainAgent`).
- **Plugin directory names** — kebab-case (`solace-architect-orchestrator`).
- **Python package names** — snake_case matching the plugin dir (`solace_architect_orchestrator`).
- **A2A topic segments** — kebab-case, sa-prefixed (`sa-orchestrator`).
- **Plugin metadata `type` field** — `"agent"` or `"gateway"` (the metadata enum kept the legacy value; the user-facing resource type is "entrypoint"). See v2spec Decision 74.
- **Skill IDs** — short, snake_case, NOT SA-prefixed (`manage_engagement`, `topic_design`).
- **Tool function names** — snake_case verbs (`record_decision`, `parse_intake_document`).
- **YAML field names** — snake_case.
- **Config file names** — kebab-case (`skill-routing.yaml`).

## Topic taxonomy (when designing customer architectures)

Pattern: `domain/noun/verb/version/{property1}/{property2}/.../{propertyN}`

- **Domain** — lowercase, hyphen-separated (`retail-banking`, `market-data`)
- **Noun** — singular, lowercase (`order`, `customer`, `position`)
- **Verb** — past tense for events (`placed`, `updated`, `cancelled`); present tense for commands (`place`, `cancel`)
- **Version** — major version only, prefixed `v` (`v1`, `v2`)
- **Properties** — domain-specific, hyphen-separated; consistent ordering across topics in the same domain

Example: `retail-banking/transaction/posted/v1/acct-12345/USD/credit`

## Document voice

- Senior architect writing design documentation.
- Short sentences. No AI vocabulary. No vendor pitch.
- Jargon glossed on first use (see `jargon-list.json`).
- Decisions close with user impact, not feature description.
- Questions framed in outcome terms.

## Forbidden terms (block on write_artifact)

- "connector" → use **Micro-Integration**
- "QoS" / "QoS levels" → use **Direct messaging** / **Guaranteed messaging**
- "orchestrator agent" (two words) → use **SAOrchestratorAgent**
- "adapter" (for Solace integrations) → use **Micro-Integration**
- "PubSub+" as a standalone product name → use the specific product name
- "gateway" as a SAM resource type → use **entrypoint** (note: the metadata enum value stays `"gateway"` — see v2spec Decision 74)
