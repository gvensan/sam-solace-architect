# Solace canonical sources

**Index last reviewed: 2026-04-29.** The next scheduled review is 90 days from this date for stable platform URLs and 30 days for SAM project URLs at `solacelabs.github.io`. Individual URLs may have been re-fetched more recently than the index review; the platform reference's verification log records per-URL verification dates for the entries that anchor it.

## Purpose

This is the URL-by-topic retrieval index for Solace Architect. When a skill or contributor needs to ground a claim, generate a recommendation, or check a detail, this document points to the authoritative source.

It is a fetch-target list, not a coverage map. The coverage map is `solace-platform-reference.md`, which says *what's in scope* and how it fits together. This document says *where to read* for each piece of that surface.

Three rules govern how this index is used:

1. The URLs listed here are the canonical sources for their respective topics. When a skill needs depth, it fetches from these URLs rather than reasoning from analogy or prior training data.
2. Marketing pages (any URL on `solace.com/solutions`, `solace.com/products`, `solace.com/blog`, `solace.com/use-cases`) are acceptable for narrative framing of *use cases and reference architectures only*. Capability claims, configuration details, and technical specifics must come from `docs.solace.com`, `solacelabs.github.io`, or `github.com/SolaceLabs`.
3. Source recency matters. A URL that was correct six months ago may not be correct today. Skills citing a URL for an external deliverable should re-fetch within the working refresh window (90 days for stable platform pages, 30 days for SAM project pages) or flag the citation as unverified.

URLs were collected during the construction of `solace-platform-reference.md`. The reference document's verification log records which were directly fetched and when. If any URL in this index returns a 404, the page has likely moved — search `docs.solace.com` for the page name and update this index.

---

## Top-level entry points

- Solace Platform overview: `https://docs.solace.com/Get-Started/solace-platform.htm`
- Feature index: `https://docs.solace.com/Get-Started/feature-index.htm`
- What is event-driven integration?: `https://docs.solace.com/Get-Started/event-mesh-basics.htm`
- Next steps after getting started: `https://docs.solace.com/Get-Started/Next-steps.htm`
- Solace docs root: `https://docs.solace.com`
- Ask Solly AI (docs Q&A): `https://docschat.solace.com`
- Solace Cloud landing: `https://docs.solace.com/Cloud/cloud-lp.htm`
- Solace Software Broker landing: `https://docs.solace.com/Software-Broker/software-lp.htm`
- Kubernetes Operator: `https://docs.solace.com/Software-Broker/sw-broker-kubernetes-operator.htm`
- Solace Appliance landing: `https://docs.solace.com/Appliance/appliance-lp.htm`

---

## Layer 1: Event Mesh

### Event broker fundamentals

- What are event brokers?: `https://docs.solace.com/Get-Started/what-are-event-brokers.htm`
- Try a broker: `https://docs.solace.com/Get-Started/Getting-Started-Try-Broker.htm`
- Configuring and managing event brokers: `https://docs.solace.com/Admin/config-manage-brokers-lp.htm`
- Configuring event broker services: `https://docs.solace.com/Cloud/manage-event-broker-services.htm`

### Topics

- Understanding topics: `https://docs.solace.com/Get-Started/what-are-topics.htm`
- Topic architecture best practices: `https://docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm`
- Topic case studies: `https://docs.solace.com/Messaging/topic-use-cases.htm`
- SMF topic syntax: `https://docs.solace.com/Messaging/SMF-Topics.htm`
- Wildcards in topic subscriptions: `https://docs.solace.com/Messaging/Wildcard-Charaters-Topic-Subs.htm`

### Message VPNs

- Message VPN overview: `https://docs.solace.com/Features/VPN/message-vpns.htm`
- Configuring message VPNs: `https://docs.solace.com/Admin/Configuring-Message-VPNs.htm`

### Endpoints

- Topic endpoints and queues: `https://docs.solace.com/Get-Started/topic-endpoints-queues.htm`
- Configuring queues: `https://docs.solace.com/Messaging/Guaranteed-Msg/Configuring-Queues.htm`
- Partitioned queues: `https://docs.solace.com/Messaging/Guaranteed-Msg/Partitioned-Queues.htm`
- Dead message queues: `https://docs.solace.com/Messaging/Guaranteed-Msg/Configuring-DTEs.htm`
- Message replay: `https://docs.solace.com/Features/Message-Replay/Message-Replay.htm`
- REST delivery points: `https://docs.solace.com/API/REST/REST-Delivery-Points.htm`
- Solace Cache: `https://docs.solace.com/Features/Cache/cache-lp.htm`
- Message eliding: `https://docs.solace.com/Messaging/Direct-Msg/Direct-Msg-Eliding.htm`
- Shared subscriptions: `https://docs.solace.com/Messaging/Direct-Msg/Direct-Msg-Shared-Subscriptions.htm`
- Message priority: `https://docs.solace.com/Messaging/Guaranteed-Msg/Message-Priority.htm`
- Transactions: `https://docs.solace.com/Features/Transactions/Transactions-Overview.htm`
- Message VPN bridges: `https://docs.solace.com/Features/VPN/VPN-Bridges.htm`

### Delivery modes

- Message delivery modes overview: `https://docs.solace.com/Get-Started/message-delivery-modes.htm`
- Direct messaging: `https://docs.solace.com/Messaging/Direct-Msg/Direct-Messages.htm`
- Guaranteed messaging: `https://docs.solace.com/Messaging/Guaranteed-Msg/Guaranteed-Messages.htm`
- Subscription exception configuration (negative subscriptions): `https://docs.solace.com/Messaging/Guaranteed-Msg/System-Level-Subscription-Exception-Config.htm`

### Multi-broker mesh and DMR

- DMR overview: `https://docs.solace.com/Features/DMR/DMR-Overview.htm`
- Multi-site DMR configuration example: `https://docs.solace.com/Features/DMR/DMR-Examples-Multi-Site-Config.htm`
- DMR product page (positioning, datasheets): `https://solace.com/products/event-broker/dynamic-message-routing/`

### High availability and disaster recovery

- DR replication landing: `https://docs.solace.com/Features/DR-Replication/`
- Replication with DMR overview: `https://docs.solace.com/Features/DR-Replication/Replication-DMR-Overview.htm`
- Configuring replication with DMR: `https://docs.solace.com/Features/DR-Replication/Replication-with-DMR.htm`

### Distributed tracing

- Overview: `https://docs.solace.com/Features/Distributed-Tracing/Distributed-Tracing-Overview.htm`
- Solace OpenTelemetry Receiver: `https://docs.solace.com/Features/Distributed-Tracing/Distributed-Tracing-Receiver.htm`
- Setup: `https://docs.solace.com/Features/Distributed-Tracing/Distributed-Tracing-Setup-Overview.htm`
- Context propagation: `https://docs.solace.com/Features/Distributed-Tracing/Distributed-Tracing-Context-Propagation.htm`
- Enabling for Solace Cloud: `https://docs.solace.com/Cloud/enable-dt-for-cloud.htm`
- Codelab demo: `https://codelabs.solace.dev/codelabs/dt-otel/index.html`

---

## Layer 2: Application Services

### Micro-Integrations

- Overview: `https://docs.solace.com/Micro-Integrations/Micro-Integrations.htm`
- Solace Cloud Micro-Integrations (managed): `https://docs.solace.com/Micro-Integrations/Managed/managed-micro-integrations-overview.htm`
- Creating a Micro-Integration: `https://docs.solace.com/Micro-Integrations/Managed/create-micro-integration.htm`
- Self-managed Micro-Integrations: `https://docs.solace.com/Micro-Integrations/Self-Managed/self-managed-micro-integrations.htm`
- Integration Hub (catalog): `https://solace.com/integration-hub/`
- Integration Hub catalog snapshot: `solace-grounding/integration-hub-catalog.md` (local, refreshed monthly)
- Integration guides: `https://docs.solace.com/API/Integration-Guides.htm`
- Connectors documentation page: `https://docs.solace.com/API/Connectors/Connectors.htm`
- Solace Integration Guides (community): `https://solacelabs.github.io/solace-integration-guides/`

### Solace Agent Mesh

#### Platform-level

- SAM platform overview (`docs.solace.com`): `https://docs.solace.com/Agentic-AI/agent-mesh.htm`

#### Project documentation root (`solacelabs.github.io`)

- Project root: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started`
- What is Agent Mesh?: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started/introduction`
- Try Agent Mesh: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started/try-agent-mesh`
- Architecture overview: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started/architecture`
- Vibe coding: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/vibe_coding`

#### Components

- Components index: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/`
- Agents: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/agents`
- OrchestratorAgent: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/orchestrator`
- Workflows: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/workflows`
- Proxies: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/proxies`
- Gateways: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/gateways`
- Platform Service: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/platform-service`
- Plugins: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/plugins`
- Projects: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/projects`
- Agent Mesh CLI: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/cli`
- Built-in tools: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/builtin-tools/`
- Data analysis tools: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/builtin-tools/data-analysis-tools`
- Prompt library: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/prompts`
- Speech integration: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/speech`

#### Lifecycle (install, develop, deploy)

- Installing and configuring: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/installing-and-configuring/`
- Developing landing: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/developing/`
- Creating custom agents: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/developing/create-agents`
- Creating custom gateways: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/developing/create-gateways`
- Creating Python tools: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/developing/creating-python-tools`
- MCP integration tutorial: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/developing/tutorials/mcp-integration`
- Deploying: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/deploying/`
- Migrations (platform service split): `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/migrations/platform-service-split`
- Enterprise edition: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/enterprise/`

#### Source repositories

- Main repo: `https://github.com/SolaceLabs/solace-agent-mesh`
- Core plugins repo: `https://github.com/SolaceLabs/solace-agent-mesh-core-plugins`
- Event Mesh Gateway plugin: `https://github.com/SolaceLabs/solace-agent-mesh-core-plugins/tree/main/sam-event-mesh-gateway`

### Developer tools and APIs

- Developer landing: `https://docs.solace.com/API/developer-lp.htm`
- Component maps (how applications interact with brokers): `https://docs.solace.com/API/Component-Maps.htm`
- Messaging API developer guide: `https://docs.solace.com/API/API-Developer-Guide/Developer-Guide-Home.htm`
- Tutorials: `https://docs.solace.com/API/Developer-Tutorials.htm`
- Messaging APIs index (all languages): `https://docs.solace.com/API/Messaging-APIs/Solace-APIs-Overview.htm`
- Feature support matrix: `https://docs.solace.com/API/API-Developer-Guide/Feature-Support-PubSub-Messaging-APIs.htm`
- Supported environments: `https://docs.solace.com/API/API-Developer-Guide/Supported-Environments.htm`
- Protocol metadata and payload encoding: `https://docs.solace.com/API/Protocol-Metadata-Payload-Encoding.htm`
- SEMP (management API): `https://docs.solace.com/Admin/SEMP/Using-SEMP.htm`
- SDKPerf (performance testing): `https://docs.solace.com/API/SDKPerf/SDKPerf.htm`
- Solace Cloud REST API reference: `https://api.solace.dev/cloud/reference`
- Codelabs: `https://docs.solace.com/API/solace-codelabs.htm`
- Service class limits and plans: `https://docs.solace.com/Cloud/cloud-service-class-comparison.htm`
- Software Event Broker system requirements: `https://docs.solace.com/Software-Broker/sw-broker-sys-reqs.htm`

---

## Layer 3: Platform Services

### Event Portal

- Landing: `https://docs.solace.com/Cloud/Event-Portal/event-portal-lp.htm`
- Overview: `https://docs.solace.com/Cloud/Event-Portal/event-portal-overview.htm`
- Designer: `https://docs.solace.com/Cloud/Event-Portal/event-portal-designer-tool.htm`
- Catalog: `https://docs.solace.com/Cloud/Event-Portal/event-portal-catalog-tool.htm`
- Runtime Event Manager: `https://docs.solace.com/Cloud/Event-Portal/event-portal-manager-tool.htm`
- KPI Dashboard: `https://docs.solace.com/Cloud/Event-Portal/event-portal-kpi-dashboard.htm`
- Event broker connections: `https://docs.solace.com/Cloud/Event-Portal/event-portal-runtime-connect.htm`
- AI Design Assistant: `https://docs.solace.com/Cloud/Event-Portal/event-portal-designer-ai.htm`
- REST API: `https://docs.solace.com/Cloud/Event-Portal/event-portal-v2-REST-API.htm`
- Object limits: `https://docs.solace.com/Cloud/usage-event-portal.htm`

### Solace Insights

- Landing: `https://docs.solace.com/Cloud/Insights/Insights.htm`
- Account overview dashboard: `https://docs.solace.com/Cloud/Insights/account-overview.htm`
- Service-level dashboards: `https://docs.solace.com/Cloud/Insights/insights-servicelevel.htm`
- Advanced monitoring dashboards: `https://docs.solace.com/Cloud/Insights/Advanced-Monitoring/using-dashboards.htm`
- Metrics reference: `https://docs.solace.com/Cloud/Insights/Advanced-Monitoring/insights-metrics.htm`
- Monitors reference: `https://docs.solace.com/Cloud/Insights/Advanced-Monitoring/insights-monitors.htm`
- Custom monitors: `https://docs.solace.com/Cloud/Insights/Advanced-Monitoring/clone-customization-for-advanced-insights.htm`
- Notifications: `https://docs.solace.com/Cloud/Insights/insights-notifications.htm`
- Insights for self-managed brokers: `https://docs.solace.com/Cloud/Insights/insights-self-serve-broker.htm`
- Forwarding metrics and logs: `https://docs.solace.com/Cloud/Insights/insights_data_forwarding.htm`

### Solace Schema Registry

- Overview: `https://docs.solace.com/Schema-Registry/schema-registry-overview.htm`
- Deploying with Docker or Podman: `https://docs.solace.com/Schema-Registry/deploying-schema-registry-docker.htm`
- Deploying with Kubernetes/Helm: `https://docs.solace.com/Schema-Registry/deploying-schema-registry-helm.htm`
- Web console: `https://docs.solace.com/Schema-Registry/schema-registry-web-console.htm`
- Artifacts: `https://docs.solace.com/Schema-Registry/schema-registry-artifacts.htm`
- Artifact reference: `https://docs.solace.com/Schema-Registry/artifact-reference.htm`
- Configuration reference: `https://docs.solace.com/Schema-Registry/configuration-reference.htm`
- Monitoring: `https://docs.solace.com/Schema-Registry/schema-registry-monitoring.htm`
- SERDES (serialization/deserialization): `https://docs.solace.com/Schema-Registry/schema-registry-serdes.htm`
- REST API documentation: `https://docs.solace.com/API-Developer-Online-Ref-Documentation/schema-registry/index.html`

### Solace Cloud Console

- Console overview: `https://docs.solace.com/Cloud/cloud-console.htm`
- Login URLs: `https://docs.solace.com/Cloud/cloud-login-urls.htm`

---

## Cross-cutting concerns

### Security and access control

- Client profiles and usernames: `https://docs.solace.com/Cloud/client-profiles.htm`
- Granting clients access (ACLs and substitution expressions): `https://docs.solace.com/Security/Granting-Clients-Access.htm`
- Client authentication overview: `https://docs.solace.com/Security/Client-Authentication.htm`
- Client certificate authentication: `https://docs.solace.com/Security/Client-Cert-Auth.htm`
- OAuth authentication: `https://docs.solace.com/Security/OAuth-Authentication.htm`
- Kerberos authentication: `https://docs.solace.com/Security/Kerberos-Authentication.htm`
- LDAP authentication: `https://docs.solace.com/Security/LDAP.htm`
- RADIUS authentication: `https://docs.solace.com/Security/RADIUS-Authentication.htm`
- TLS/SSL configuration: `https://docs.solace.com/Security/TLS-SSL-Config.htm`
- SEMP access control: `https://docs.solace.com/Admin/SEMP/SEMP-API-Archit.htm`

### Operations

- Syslog forwarding: `https://docs.solace.com/Cloud/cloud-syslog-forwarding.htm`
- Product keys: `https://docs.solace.com/Admin/Product-Key.htm`
- System event reference: `https://docs.solace.com/Admin-Ref/Solace-PubSub-Event-Reference/event_ref_boiler.html`
- Kubernetes Operator (also listed in top-level entry points): `https://docs.solace.com/Software-Broker/sw-broker-kubernetes-operator.htm`
- Kubernetes Operator Helm chart: `https://docs.solace.com/Software-Broker/sw-broker-install-kubernetes-operator.htm`

### Releases

- Solace Cloud release notes: `https://docs.solace.com/Release-Notes/PubSub-Cloud-Release-Notes.htm`
- Documentation set version: `https://docs.solace.com/Resources/Documentation-Set.htm`

### Custom message headers

- Creating custom header fields: `https://docs.solace.com/API/API-Developer-Guide/Creating-Custom-Header-Fields.htm`

---

## Marketing and positioning sources

These URLs are acceptable for narrative framing of use cases and reference architectures only. They are not authoritative sources for capability claims, configuration details, or technical specifics.

- Solace products: `https://solace.com/products/`
- Solace solutions: `https://solace.com/solutions/`
- Solace blog: `https://solace.com/blog/`
- Event Broker product page: `https://solace.com/products/event-broker/`
- DMR product page: `https://solace.com/products/event-broker/dynamic-message-routing/`
- DMR datasheet: `https://solace.com/resources/datasheets/dynamic-message-routing-datasheet`
- Microservices solutions: `https://solace.com/solutions/initiative/microservices/`
- Solace developer portal: `https://www.solace.dev/`

---

## External standards and dependencies

References outside Solace that the platform's architecture depends on. Skills generating SAM-related content will reference these regularly.

### Standards

- OpenTelemetry specification: `https://opentelemetry.io/docs/reference/specification/`
- OpenTelemetry Collector (open source): `https://github.com/open-telemetry/opentelemetry-collector-contrib`
- JSON-RPC 2.0 specification: `https://www.jsonrpc.org/specification`

### Frameworks SAM depends on

- Google Agent Development Kit (ADK): `https://google.github.io/adk-docs/` — the canonical Google source for the ADK SAM uses for agent logic.
- Solace AI Connector (SAC): `https://solacelabs.github.io/solace-ai-connector/` — SAC is the runtime SAM uses to host agents and gateways.
- Model Context Protocol (MCP): `https://modelcontextprotocol.io/` �� the protocol SAM agents use to integrate with external tool servers.

---

## External project references

### Solace Architect

- Repository: `https://github.com/solacecommunity/solace-architect`

---

## Update discipline

This index is part of the project's grounding infrastructure. Three rules for keeping it useful:

1. **When skills find a URL not in this index, add it.** New URLs encountered during real skill development should land here, not stay in scattered notes.
2. **When a URL 404s, fix it.** Solace docs occasionally restructure paths. Search `docs.solace.com` for the page name and update the entry rather than leaving a dead link.
3. **When a topic in this index gains real depth in skill content, that's a signal to fetch the URL into the platform reference document.** This index is a pointer; the platform reference is the curated map. Both should grow together.