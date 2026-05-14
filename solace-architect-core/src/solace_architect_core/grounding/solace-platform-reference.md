# Solace Platform Reference

## Purpose of this document

This is the in-scope coverage map for Solace Architect. It defines what Solace Architect is accountable to know about and reason over when generating blueprints, validating designs, or answering architecture questions. It is structured around the three-layer Solace Platform model plus cross-cutting concerns that span layers.

It is not a tutorial, not a complete technical reference, and not a substitute for Solace's own documentation. Each entry names the capability, gives a one-line scope statement, and points to the canonical source in `solace-canonical-sources.md`. When skills need depth, they go to the canonical source, not to this document.

This is a living document. When a real architecture problem touches a Solace capability not yet captured here, the gap should be flagged and this document updated.

## The three-layer model

Solace Platform is officially structured into three layers:

1. **Event Mesh** — the messaging backbone. Event brokers, topics, queues, delivery semantics, and the federation that connects them.
2. **Application Services** — what runs on top of the mesh. Micro-Integrations for connecting enterprise systems, Solace Agent Mesh for AI agent orchestration, and developer tools and APIs for native event-driven applications.
3. **Platform Services** — the design, governance, and operations tooling around the platform. Event Portal, Insights, Schema Registry, Cloud Console.

This structure is from `docs.solace.com/Get-Started/solace-platform.htm`. Solace Architect's technical domain skills should mirror this structure rather than invent an alternative.

---

## Layer 1: Event Mesh

### Event Brokers

Solace event brokers are middleware that mediate event message communication between producers and consumers. They are available in three deployment forms:

1. **Solace Cloud event broker services** — fully managed SaaS brokers in Solace Cloud.
2. **Solace Software Event Brokers** — self-managed software brokers deployable in Docker, Podman, Kubernetes, on bare metal, or VMs.
3. **Solace Appliance Event Brokers** — hardware appliances for high-throughput, low-latency, regulated environments.

Brokers of all three types can participate in a single event mesh. Solace event brokers can also coexist with non-Solace event brokers (Kafka is named in Solace docs as a supported third-party event broker type within an EDA).

### Message VPNs

A message VPN (Virtual Private Network) is a virtual partition within a Solace event broker that provides network-level separation for messaging. Each message VPN is an isolated messaging domain with its own:

1. **Client usernames, client profiles, and ACL profiles** — authentication and authorization are scoped per VPN.
2. **Queues, topic endpoints, and subscriptions** — messaging objects are VPN-local.
3. **REST delivery points** — webhook-style outbound delivery configured per VPN.
4. **Replication** — DR replication operates at the VPN level. The active VPN handles traffic; the standby VPN on the backup broker takes over on failover.
5. **DMR participation** — a message VPN can participate in DMR. Replication mates appear as a single node to DMR, with data channels active only on the active VPN.

Message VPNs are the unit of multi-tenancy on a single broker. Multiple applications or teams can share a broker with full isolation. VPN-level quotas control maximum connections, subscriptions, spool usage, and egress/ingress rates.

Every client connection is to a specific message VPN. Broker-level HA (primary/backup/monitoring) fails over all VPNs on the broker together — VPN-level failover granularity is not supported.

Solace Cloud event broker services include a default message VPN. Self-managed brokers can host multiple VPNs on a single broker instance.

### Smart Topic Architecture

Topics are hierarchical strings (`a/b/c/.../n`) attached to messages as metadata, used for both event description and routing. Solace topics support:

1. Hierarchical levels with variables substitutable from event properties.
2. Wildcard subscriptions: `*` matches a single level; `>` matches one or more trailing levels.
3. Negative subscriptions (Guaranteed messaging only): `!` prefix to exclude topics from a larger subscription set.
4. Routing decisions made by the broker without deserializing or interpreting the payload.
5. Per-subscription policies for priority, replay eligibility, replication, and access control.

#### Topic structure best practices

The recommended event topic taxonomy is `Domain/Noun/Verb/Version/Properties...`:

1. **Domain.** Identifies the organizational owner. Form: `dataSystem/applicationDomain` (e.g., `operations/flights`, `finance/payroll`). Optionally prefixed with organization name for multi-vendor or merger-aware systems.
2. **Noun.** The object being acted on (e.g., `customer`, `order`, `flight`).
3. **Verb.** The action or state change in past tense (e.g., `created`, `boarding`, `paid`).
4. **Version.** `v1`, `v2`, etc. — required for blue/green and canary deployments and to distinguish breaking schema changes.
5. **Properties.** Ordered least-specific to most-specific by cardinality. Common types: `ID`, `Locality`, `Category`, `HandlingInstruction` (advanced).

Hard limits: 250 characters max, 128 levels max. Naming convention: camelCase or PascalCase preferred over snake_case (efficiency).

#### Topic anti-patterns to flag in validation

Solace's own documentation names these anti-patterns explicitly. The validation skill should detect them:

1. **Using message properties for filtering** (e.g., JMS selectors). Filtering, routing, and governance must live in topics.
2. **Including tracing data** (TraceID, SpanID) in topic hierarchy. Use Distributed Tracing instead.
3. **Including environment names** (`dev`, `qa`, `prod`) in topics. Couples application code to environment, breaks Event Portal promotion.
4. **Spaces, special characters, or `*`/`>`/`!`** in published topics. Breaks subscription matching.

### Endpoints: Queues and Topic Endpoints

Endpoints are broker-managed objects that persist messages for Guaranteed messaging consumers. Two types:

1. **Queues** — durable message stores that decouple producers from consumers. Support multiple topic subscriptions per queue. Two consumer binding modes:
   - **Exclusive queue** — one consumer owns the queue at a time. Guarantees strict message ordering. If the consumer disconnects, another can bind and take over.
   - **Non-exclusive queue** — multiple consumers bind concurrently. Broker distributes messages round-robin across consumers. Enables horizontal scaling but does not guarantee per-message ordering across consumers.

2. **Topic endpoints** — similar to queues but bound to exactly one topic subscription. Used when a single subscription defines the message stream. Less common than queues in practice.

#### Partitioned queues

Partitioned queues combine the ordering guarantees of exclusive queues with the scaling benefits of non-exclusive queues. Messages with the same partition key always route to the same consumer, preserving per-key ordering while allowing different keys to be processed in parallel by different consumers.

- **Partition key** — set by the publisher in the message header. Common keys: customer ID, order ID, file path, device ID.
- **Rebalancing** — when consumers join or leave, the broker rebalances partitions across active consumers.
- **Use case** — per-entity ordering at scale: "all events for the same customer in order, different customers in parallel."

#### Dead Message Queue (DMQ)

A DMQ is a special queue where the broker moves messages that cannot be successfully consumed. Messages land in the DMQ when:

1. **Max redelivery exceeded** — the message was nacked or not acknowledged more than the configured max redelivery count.
2. **TTL expired** — the message's time-to-live elapsed before it was consumed.
3. **Max message size exceeded** — the message exceeds the queue's max message size.

Each queue can designate a DMQ. Without a DMQ, messages that exceed redelivery or TTL limits are silently discarded. Production queues should always have a DMQ configured with alerting on depth > 0.

#### Queue configuration parameters

Key per-queue settings that affect architectural decisions:

- **Max spool usage** — maximum message spool quota for the queue (MB). Prevents one queue from consuming all broker spool.
- **Max redelivery count** — how many times a nacked message is redelivered before moving to DMQ.
- **Max TTL** — time-to-live for messages on the queue.
- **Reject-on-max-spool** — whether the broker rejects new messages when the queue reaches its spool limit, or discards oldest messages.
- **Access type** — exclusive or non-exclusive.
- **Partition count and rebalance delay** — for partitioned queues.

### Message Replay

Message replay allows consumers to replay previously consumed Guaranteed messages from a queue or topic endpoint. Two replay modes:

1. **Time-based replay** — replay all messages from a specific timestamp forward. Useful for recovery scenarios, reprocessing after a bug fix, or onboarding new consumers.
2. **Replication-group-message-ID-based replay** — replay from a specific message ID. More precise than time-based.

Replay requires replay log to be enabled on the broker. Messages are retained in the replay log according to the configured retention policy (time-based or spool-based). Replay does not remove messages from the original queue; it re-delivers copies.

Not all consumers need replay. It is a design decision per endpoint based on recovery requirements.

### Message Delivery Modes

Solace event brokers support two delivery modes:

1. **Direct messaging** — high-rate, low-latency, no persistence, no acknowledgment, lossy under congestion. Subscriptions bind to clients directly.
2. **Guaranteed messaging** — persistent, acknowledged, lossless once acknowledged by the broker. Subscriptions bind to endpoints, not clients.

Transactions are a separate feature applied within Guaranteed messaging.

### Transactions

Solace supports two transaction models for Guaranteed messaging:

1. **Local transactions** — group multiple Guaranteed messages into a single atomic commit within one session. All messages in the transaction are published (or consumed) as a unit; either all succeed or all roll back.
2. **XA transactions** — distributed transactions across Solace and external resource managers (databases, JMS providers). Coordinated by an external transaction manager using the XA two-phase commit protocol.

Local-transaction messages do not generate trace messages for Distributed Tracing. Use case: financial flows, order processing, and other scenarios requiring atomic multi-queue operations.

### Message Eliding

A Direct messaging feature where the broker discards older undelivered messages when a consumer cannot keep up, delivering only the latest message per topic. This ensures slow consumers always receive the most recent value rather than queuing stale data.

Use cases: market data tickers, IoT sensor telemetry, status dashboards where the latest value wins. Not applicable to Guaranteed messaging.

### Solace Cache / CacheInstance

Last-value caching for Direct messaging topics. A CacheInstance stores the most recent message published on each topic matching its configured topic subscriptions. Late-joining subscribers request the last cached message rather than waiting for the next publish.

Configured per CacheInstance with topic subscriptions that define which topics are cached. Use cases: market data last-value lookup, device status caches, reference data distribution.

### Shared Subscriptions

A load-balancing mechanism for Direct messaging. Multiple consumers share a subscription and the broker distributes messages across them, enabling horizontal scaling for Direct messaging workloads.

Semantics differ across protocols: MQTT uses `$share` groups, SMF uses shared subscriptions. Provides consumer scaling for Direct messaging similar to how non-exclusive queues scale Guaranteed messaging.

### Message Priority

Messages carry a priority level (0-255 in the native SMF API, mapped to 0-9 for JMS clients, where 0 is lowest) as a message header property. The broker delivers higher-priority messages before lower-priority messages within a queue.

Use cases: control messages before data messages, premium customers before standard. Priority is per-message, not per-topic — set by the publisher in the message header.

### Message VPN Bridges

Bridges connect message VPNs on the same or different brokers. A bridge forwards messages matching configured subscriptions from one VPN to another, enabling controlled cross-VPN event sharing.

Use cases: cross-team event sharing, staged environments, VPN consolidation. Distinct from DMR — bridges are point-to-point VPN connections, DMR is mesh-level routing.

### REST Delivery Points (RDPs)

A REST delivery point is a broker-managed outbound webhook mechanism. It delivers Guaranteed messages from a queue to an external HTTP/HTTPS endpoint. RDPs are the mechanism by which Broker Integrated Micro-Integrations (e.g., Amazon S3 Producer, Google Cloud Storage Producer, AWS Lambda Producer) deliver messages to external services.

Components of an RDP:

1. **REST delivery point** — the container object. Configured per message VPN.
2. **Queue binding** — binds a queue to the RDP. Messages arriving on the queue are delivered via the RDP.
3. **REST consumer** — the HTTP endpoint configuration (URL, authentication, TLS settings).

RDP behavior:

- Messages are delivered as HTTP POST requests to the configured endpoint.
- The broker expects an HTTP 2xx response as acknowledgment. Non-2xx responses trigger retry.
- Built-in retry with configurable backoff (including exponential backoff).
- Messages that exhaust retries follow the queue's DMQ configuration.
- Multiple REST consumers can be configured for load distribution.
- TLS is supported and recommended for production.

RDPs are distinct from REST messaging (where clients publish/subscribe via REST). RDPs are broker-initiated outbound delivery; REST messaging is client-initiated inbound/outbound.

### Multi-broker mesh and Dynamic Message Routing (DMR)

DMR is the underlying technology for an event mesh. It is a self-learning routing mechanism that automatically distributes subscriptions and events between brokers, so applications and devices can share information as if connected to the same broker.

DMR supports two primary use cases:

1. **Horizontal scaling via DMR cluster.** Brokers in the same cluster connect through *internal links*, forming a "full mesh" where every node connects to every other node. Each node is aware of all others, enabling seamless event routing across the cluster.
2. **Multi-site scaling via external links.** Brokers across sites or clouds connect via *external links*. Full mesh is not required; selective links allow controlled subscription propagation and data flow between clusters (e.g., for data sovereignty).

Each node advertises its DMR neighbors and replication mates, allowing all nodes to build an accurate internal model of the network. DMR supports both Direct and Guaranteed messaging across links. DMR works alongside replication for disaster recovery — replication groups appear to DMR as a single node, with data channels active only on the active VPN.

In Solace Cloud, DMR is enabled automatically for service classes other than Developer. Broker Manager includes a Click-to-Connect wizard for DMR mesh setup.

### High Availability and Disaster Recovery

#### HA within a site

Solace HA uses a **three-node redundancy group**: primary, backup, and monitoring.

1. **Primary broker** — handles all client connections and message traffic.
2. **Backup broker** — maintains synchronized state via a **mate link** to the primary. Ready to take over on failover.
3. **Monitoring broker** — provides quorum for failover decisions. Prevents split-brain when network partitions occur between primary and backup.

HA operates at the broker level. All message VPNs on a broker fail over together. VPN-level failover granularity is not supported.

**Config-Sync** keeps configuration consistent across the primary and backup brokers. When configuration changes are made on the active broker, Config-Sync propagates them to the standby. This ensures the standby broker is ready to serve clients with identical configuration after failover.

**Client reconnection:** Solace messaging APIs support automatic reconnect to the backup broker on failover. Applications using the Solace API do not need custom failover logic — the API handles reconnection, session recovery, and message redelivery.

For **Solace Cloud event broker services**, HA is enabled by default for Enterprise and higher service classes. The three-node model is managed by Solace. Developer class does not include HA.

#### DR across sites

DR uses **replication** to copy messages from a primary site to a DR site:

1. **Replication groups** — pairs of message VPNs (one active, one standby) across sites.
2. **Replication modes** — synchronous (zero RPO, higher latency) or asynchronous (near-zero RPO, lower latency).
3. **DMR interaction** — replication mates appear to DMR as a single node. The active VPN handles DMR data channels. On failover, the standby VPN takes over DMR participation.
4. **Active/standby** is the standard DR topology. Solace does not natively support active/active DR with automatic conflict resolution.

#### DMR link configuration

DMR links come in two forms:

1. **Internal links** — within a DMR cluster. Form a full mesh automatically. Carry both Direct and Guaranteed messages.
2. **External links** — between DMR clusters. Configured selectively. Support **compressed** and **uncompressed** modes — compressed links reduce bandwidth for WAN transport at the cost of CPU.

Guaranteed messaging across DMR external links requires explicit queue-to-queue bridging configuration. Direct messaging propagates automatically via subscription propagation. This distinction is architecturally significant: Guaranteed cross-site delivery requires more configuration than Direct.

### Distributed Tracing

OpenTelemetry-compliant tracing of message lifecycle across brokers and applications. Generates spans on receive, enqueue, send, acknowledge, delete, and DMQ-move events. Trace messages flow to a Solace OpenTelemetry Receiver (a plugin for the OpenTelemetry Collector), which forwards to backends including Jaeger, DataDog, Splunk, Prometheus, Zipkin, and DynaTrace.

Requires a product key for production. Demo mode (7 days) available without a product key.

Behaves correctly across DMR links, Message VPN bridges, and partitioned queues. Local-transaction messages do not generate trace messages.

---

## Layer 2: Application Services

### Micro-Integrations

Micro-Integrations are small, lightweight, event-driven integration modules that connect enterprise technologies (legacy and SaaS applications, messaging services, databases, filesystems, AI agents) to Solace event brokers. They establish data movement between an event distribution layer and external source or target systems, with optional message transformation, data enrichment, validation, or header modification.

Solace offers two Micro-Integration deployment models:

1. **Micro-Integrations in Solace Cloud** — fully managed by Solace, available through the Solace Cloud Console. Three direction types: source (external → broker), target (broker → external), and processor (broker → transformation → broker).
2. **Self-Managed Micro-Integrations** — deployed in customer infrastructure. Built on Spring Framework. Available as executable packages or pre-built container images for Docker, Podman, or Kubernetes. Source and target directions only.

The **Integration Hub** at `solace.com/integration-hub` is the canonical catalog. It organizes assets across several axes:

1. *Asset type:* Micro-Integrations, Integration Guides, Agents (AI), Accelerators (professional services).
2. *Technology category:* Analytics & Stream Processing, Application & App Platform, Artificial Intelligence, Database & Data Storage, Integration (incl. iPaaS), Messaging/Eventing, IoT.
3. *Support tier:* Solace Support Available (paid option), Solace Support Included, Community, Partner.
4. *Deployment style:* Self-Managed (Spring Boot), Cloud-Managed (Spring Boot, available in PubSub+ Cloud), iPaaS (Boomi, Mulesoft, SAP IS), Broker Integrated (Kafka bridge, REST-based endpoints), External Embedded, Other (JMS API, Spark, etc.).

The Kafka bridge is a Broker Integrated capability rather than a Micro-Integration in the Spring Boot sense.

### Solace Agent Mesh (SAM)

SAM is an event-driven agentic AI framework that orchestrates autonomous AI agents and lets them interact with each other, with other AI assets, and with applications and data sources across the enterprise. Open source on GitHub at `github.com/SolaceLabs/solace-agent-mesh`. Also offered as **Solace Agent Mesh Enterprise** with additional production capabilities.

#### SAM technology stack

SAM integrates three primary technologies:

1. **Solace Event Broker** — the messaging fabric. All component-to-component communication flows over the broker as A2A (Agent-to-Agent) protocol messages on hierarchical topics.
2. **Solace AI Connector (SAC)** — the runtime environment that hosts and manages the lifecycle of all SAM components (Agent Hosts, Gateways, etc.).
3. **Google Agent Development Kit (ADK)** — provides the core logic for individual agents, including LLM interaction, tool execution, session management, and artifact handling.

#### Architectural principles

1. **Event-driven.** All component interactions are asynchronous and broker-mediated. No direct dependencies.
2. **Component decoupling.** Components communicate via A2A protocol over the event mesh; they do not need to know each other's location, language, or implementation.
3. **Horizontal scalability.** Agent Hosts and Gateways scale horizontally. Broker provides fault tolerance and guaranteed delivery.

#### A2A protocol

The Agent-to-Agent protocol is based on **JSON-RPC 2.0** and defines the message formats for all inter-component interactions. Routing uses a hierarchical topic structure:

| Purpose | Topic pattern |
|---|---|
| Agent discovery | `{namespace}/a2a/v1/discovery/agentcards` |
| Task requests | `{namespace}/a2a/v1/agent/request/{target_agent_name}` |
| Status updates | `{namespace}/a2a/v1/gateway/status/{gateway_id}/{task_id}` |
| Final responses | `{namespace}/a2a/v1/gateway/response/{gateway_id}/{task_id}` |
| Peer delegation status | `{namespace}/a2a/v1/agent/status/{delegating_agent_name}/{sub_task_id}` |
| Peer delegation response | `{namespace}/a2a/v1/agent/response/{delegating_agent_name}/{sub_task_id}` |

#### SAM components

Per the current open source documentation:

1. **Agents.** Specialized processing units built on ADK. Configured via YAML. Each agent has an Agent Card (id, description, defaultInputModes, defaultOutputModes, skills) published to the discovery topic on startup. Agents support three tool sources: **built-in tools**, **custom Python tools**, and **MCP (Model Context Protocol) tools**. Agent lifecycle: Discovery → Active → Execution → Cleanup.
2. **Agent Hosts.** SAC applications (`SamAgentApp`) that host individual ADK agents. Manage ADK Runner and `LlmAgent` lifecycles, A2A protocol translation, scope-based tool filtering, and ADK services (ArtifactService, MemoryService).
3. **OrchestratorAgent.** A specialized agent that acts as central coordinator for complex workflows. Handles request analysis and action planning, task creation and distribution, workflow management, and response formatting. Multiple orchestrators can be deployed for different workflows or domains.
4. **Workflows.** Patterns the orchestrator uses (dynamic and prescriptive).
5. **Gateways.** SAC applications that bridge external systems to the agent mesh. Translate external protocols (HTTP, WebSockets, Slack RTM, etc.) to A2A and back. Handle authentication and authorization via a pluggable AuthorizationService that retrieves user permission scopes. Manage external user sessions and map them to A2A task lifecycles. Built on the **Gateway Development Kit (GDK)**, which provides `BaseGatewayApp` and `BaseGatewayComponent` classes that abstract common gateway logic.
6. **Proxies.** Protocol bridges for **Remote A2A agents** — agents running on separate infrastructure that communicate via A2A over HTTPS rather than over the Solace event mesh. Proxies handle authentication, artifact flow, and discovery, making remote agents appear as native mesh agents.
7. **Platform Service.** Supporting platform capabilities for the framework.
8. **Plugins.** Extensibility mechanism, including plugin gateways and plugin agents from Solace or community.
9. **Projects.** Organizational unit for SAM deployments.
10. **Agent Mesh CLI (`sam`).** Command-line tool. Examples: `sam add agent my-agent [--gui]`, `sam add gateway my-interface`.
11. **Built-in Tools.** Including artifact management, data analysis, web scraping, peer-to-peer delegation.
12. **Prompt Library.** Managed prompts.
13. **Speech Integration.** Voice interface support.

#### Available gateway types in current open source release

1. *Core gateways:* HTTP SSE, REST, Webhook.
2. *Plugin gateways:* Event Mesh Gateway, Slack Gateway, Microsoft Teams Gateway (Enterprise), and custom gateways via the plugin framework.

#### Key architectural flows

1. **User task processing.** Client → Gateway authenticates and translates to A2A → broker routes to target agent's request topic → Agent Host processes via ADK → status updates flow back to gateway's status topic → final response flows to gateway → client.
2. **Agent-to-agent delegation.** Agent uses `PeerAgentTool` to delegate to another agent, propagating user permission scopes to maintain security context. Delegated agent enforces scopes on its own toolset.
3. **Agent discovery.** Each Agent Host periodically publishes an `AgentCard` (JSON describing capabilities) to the discovery topic. Gateways and other Agent Hosts subscribe and update their local AgentRegistry.

### Developer Tools and Messaging APIs

Solace publishes messaging APIs for the following languages, designed as the base messaging layer for client applications communicating over Solace:

1. C
2. C# / .NET (managed wrapper for the C API)
3. Go
4. iOS (native wrapper of the C API)
5. Java
6. Java RTO (low-latency JNI wrapper for the C API)
7. JCSMP (classic object-oriented Java API)
8. JavaScript
9. JMS
10. Node.js
11. Python

#### SEMP (Solace Element Management Protocol)

SEMP v2 is the RESTful management API for broker administration and monitoring. Two sub-APIs:

1. **SEMP Config API** — create, read, update, delete broker configuration objects (message VPNs, queues, client profiles, ACL profiles, REST delivery points, etc.). Used for infrastructure-as-code, CI/CD automation, and programmatic provisioning.
2. **SEMP Monitor API** — read-only access to broker statistics, client connections, queue depths, spool usage, and operational state. Used for custom monitoring dashboards, alerting integrations, and operational scripts.

SEMP is available on all broker types (Cloud, Software, Appliance). Solace Cloud exposes SEMP endpoints for each event broker service. Access is controlled by SEMP authentication (username/password or OAuth) and can be restricted by management ACLs.

**SDKPerf** is the official Solace performance testing tool for benchmarking message throughput, latency, and broker capacity under load.

### Protocols

Solace event brokers support open protocols natively. The protocols, formally documented in the Feature Support and Supported Environments references, include SMF (Solace Message Format, the native protocol), MQTT, AMQP, JMS, REST messaging, and WebSocket.

---

## Layer 3: Platform Services

### Solace Event Portal

Cloud-based event management for designing, discovering, sharing, managing, and governing assets in an event-driven architecture. Tools per the current landing page:

1. **Designer** — create and update objects used to design the EDA (events, schemas, applications, application domains).
2. **Catalog** — search the organization's library of applications, events, and other objects.
3. **Runtime Event Manager** — model the EDA using objects from Designer and from imported broker state.
4. **KPI Dashboard** — view event use metrics.
5. **Event Broker Connections** — connect Event Portal to operational brokers to push configurations and discover runtime data.
6. **AI Design Assistant** — generate example application domains with events and applications.

Event Portal also offers a REST API and supports Kafka discovery alongside Solace broker discovery. Per the topic best practices documentation, Event Portal conforms to industry-accepted infrastructure-as-code methodologies for promoting artifacts across development environments.

### Solace Insights

Operational health monitoring for event broker services and event meshes. Three dashboard tiers:

1. **Account-level.** High-level dashboard summarizing the account (Workspace), available to all users when subscribed.
2. **Service-level.** Per-broker-service dashboard available in Cluster Manager's Monitoring tab.
3. **Advanced Monitoring.** Solace Insights dashboards for Datadog, accessed via a Datadog account provided with the subscription. Requires Insights Advanced Manager, Editor, or Viewer roles.

Backed by Datadog as the metrics and log storage layer. Includes 50+ pre-built monitors (log-based, metric-based, status-based) representing Solace-curated best practices. Supports email notifications, log retention up to 30 days (90 on request), and forwarding metrics and logs to customer-owned Datadog or other observability platforms.

Insights also supports self-managed Solace Software Event Brokers (Docker, Podman, Kubernetes) and Solace Appliance Event Brokers (Controlled Availability).

### Solace Schema Registry

Datastore for sharing standard event schemas across event-driven and API architectures. Decouples data structure from client applications, supports schema evolution rules (validity, version compatibility), and provides serialization and deserialization (SERDES) for messages.

Concepts:

1. **Artifacts** — items stored in the registry (event schemas), with metadata, versions, and group IDs for organizational separation.
2. **Schema governor** — the role responsible for defining valid schemas via the web console.
3. **Configuration rules** — optional rules (validity, version compatibility) that gate schema uploads.

Deployment: standalone container (Docker 20.10+, Podman 3.0+) or HA pair via Kubernetes (1.21+) and Helm (3.8+). Authentication via Basic or OIDC. Web console plus REST API. Audit logs integrate with Datadog.

### Solace Cloud Console

The "single pane of glass" for Solace Platform. Web-based unified administration covering event broker services, Event Portal, Insights, Micro-Integrations, and related platform services.

---

## Cross-cutting concerns

These concerns are not exclusive to one layer; they shape every architectural decision Solace Architect generates.

### Deployment topologies

1. Solace Cloud (event broker services in Solace-managed cloud).
2. Solace Software Event Broker on Docker, Podman, Kubernetes, bare metal, VMs.
3. Solace Appliance Event Brokers in datacenter or co-location.
4. Hybrid cloud, multi-cloud, on-premises, and edge deployments federated through DMR.
5. HA configurations within a site; DR replication across sites and regions, interoperating with DMR.
6. DMR cluster (full-mesh internal links) for horizontal scaling within a site or cloud region.
7. DMR external links between clusters for multi-site scaling and selective propagation.

**Solace PubSub+ Kubernetes Operator:** For Kubernetes deployments of Software Event Brokers, the Kubernetes Operator automates broker lifecycle management including deployment, scaling, HA configuration, and upgrades. The Operator manages broker pods as StatefulSets, persistent volumes for message spool, and ConfigMaps for broker configuration. It supports rolling upgrades, automated HA configuration, and integration with Kubernetes-native monitoring. Helm charts are the primary installation mechanism.

(Note: Detailed sizing tables, broker SKU selection, and production HA topology templates have not been pulled into this reference. Skills addressing those depths should consult Solace Admin and Cloud documentation directly.)

### Security and access control

#### Authentication

Solace brokers support multiple client authentication methods:

1. **Client username/password** — basic authentication per message VPN. Simplest model.
2. **Client certificate authentication** — mutual TLS. Clients present X.509 certificates. Broker validates against a trusted CA chain. Supports CRL (Certificate Revocation List) and OCSP (Online Certificate Status Protocol) for revocation checking.
3. **OAuth 2.0** — token-based authentication. Clients present JWT or opaque tokens. Broker validates tokens against a configured authorization server (JWKS endpoint or introspection endpoint). Supports token scope extraction for authorization decisions.
4. **Kerberos** — GSSAPI/SPNEGO authentication for enterprise environments with existing Kerberos infrastructure.
5. **LDAP** — broker delegates authentication to an LDAP directory server.
6. **RADIUS** — remote authentication against a RADIUS server.

Authentication is configured per message VPN. Different VPNs can use different authentication methods.

#### Authorization

1. **Client profiles** — control connection-level properties: max connections, max subscriptions, Guaranteed messaging permissions (publish, subscribe, consume, or combinations), max ingress/egress rates, and connection throttling.
2. **ACL profiles** — control topic-level publish and subscribe permissions. Support wildcards and **substitution expressions** for dynamic, per-client entitlements (e.g., `${clientUsername}` in topic patterns).
3. **Message VPN isolation** — each VPN is a fully isolated messaging domain. Clients in one VPN cannot access queues, topics, or subscriptions in another VPN. VPN isolation is a security boundary.

#### Encryption

1. **In transit** — TLS on all client-to-broker connections. Configurable per message VPN. Cipher suite selection available.
2. **At rest** — message spool encryption for Software Event Brokers (configurable). Solace Cloud manages encryption transparently.
3. **SEMP security** — SEMP management API access controlled by management username/password or OAuth. Management ACLs restrict which SEMP operations each administrator can perform.

#### SAM-specific security

1. **AuthorizationService** — pluggable component on SAM Gateways that retrieves user permission scopes. Scopes propagate through agent delegation chains via PeerAgentTool.
2. **Schema Registry authentication** via Basic or OIDC.
3. **Distributed Tracing** requires production keys for production use; demo mode is time-limited.

### Observability

Three Solace-native observability primitives, each with different scope:

1. **Solace Insights** — broker and mesh operational health, monitors, dashboards, alerting (Layer 3).
2. **Distributed Tracing** — message lifecycle tracing via OpenTelemetry (Layer 1 capability).
3. **Schema Registry audit logs** — schema operation history (Layer 3).

Skills generating observability blueprints should select the right primitive(s) for the question being asked, not default to one.

### Performance and sizing

Throughput, latency, capacity planning, and broker sizing are first-class architectural concerns.

**Sizing methodology:**
1. **Connection count** — sum all producer, consumer, MI, and management connections per broker
2. **Message rate** — peak events/second from discovery, factored by message size
3. **Spool calculation** — message size x retention period x message rate for Guaranteed messaging queues
4. **Service class mapping** — Developer (dev/test), Enterprise (production), Enterprise Kilo (high-scale production). Verify current service class names at `docs.solace.com/Cloud/cloud-service-class-comparison.htm`.

**Performance tuning areas:**
- Publisher flow control — broker backpressure when spool or queue limits are reached
- Consumer prefetch — number of messages pre-delivered to consumers before acknowledgment
- Connection pooling — session reuse patterns per SDK
- Batching — grouping multiple small messages for throughput efficiency

SDKPerf is the official Solace performance testing tool for establishing throughput and latency baselines.

(Note: Specific performance numbers, sizing tables, and capacity calculation methods have not been included in this reference. Performance claims that go to external audiences require verification before publication, per the project's accuracy discipline.)

### Migration and lifecycle

1. Greenfield deployment versus migration from non-Solace platforms (Solace publishes professional services for legacy broker transitions).
2. Schema evolution via Schema Registry.
3. Broker version upgrades (Solace publishes upgrade services).
4. Event versioning via topic version field (`v1`, `v2`) supporting blue/green and canary deployments.
5. Capacity expansion and decommissioning.
6. Deployment model transitions (e.g., software broker to event broker service).
7. Remote A2A agent integration as a path for gradually migrating existing agents into a SAM mesh.

### Governance

Primarily delivered through Event Portal: event modeling, schema management, catalog, runtime configuration handoff between integration teams and developers, KPI tracking, and runtime discovery. ACLs at the broker level provide enforcement. Topic taxonomy itself is a governance instrument — domain prefixes establish event ownership across business units.

### Integration patterns

These application-level patterns are commonly implemented on the Solace platform:

1. **Request-reply** — publisher sends a request message with a reply-to topic (typically a temporary topic). Consumer processes the request and publishes the response to the reply-to topic. Correlation IDs in message properties (not in topic hierarchy) link requests to responses. REST protocol supports direct request-reply natively.

2. **Event sourcing** — Guaranteed messaging with message replay provides the foundation. Events are published to versioned topics, persisted in broker spool, and replayable from any point in the replay window. Not a native Solace feature but a pattern well-supported by the platform's delivery guarantees and replay capability.

3. **CQRS** — separate topic namespaces for command and query paths. Command events flow through Guaranteed messaging to the write model. Query events (potentially using Direct messaging for read-model updates) fan out to multiple read models via wildcard subscriptions.

4. **Saga / Choreography** — distributed coordination via compensating events on topics. Each service publishes success/failure events. Compensating actions subscribe to failure topics. DMQ handles poison messages in saga steps. Choreography uses topic subscriptions for coordination without a central orchestrator.

5. **Fan-out** — single publish, multiple subscribers. Direct messaging for high-rate fan-out (market data). Guaranteed messaging with multiple queue subscriptions for reliable fan-out. Wildcard subscriptions enable dynamic fan-out without publisher changes.

---

## Naming and terminology

These conventions are non-negotiable and apply to all output Solace Architect generates.

1. **Micro-Integration** (capital M, hyphenated) for Solace's catalog of integration modules. Not "connector," not "integration module," not "adapter."
2. **Solace Agent Mesh** (full name) or **SAM** (acronym). Both acceptable.
3. **Event broker service** for Solace Cloud-managed brokers. **Solace Software Event Broker** and **Solace Appliance Event Broker** for the self-managed forms.
4. **Direct messaging** and **Guaranteed messaging** for the two delivery modes.
5. **Smart topics** for the hierarchical-topic concept.
6. **DMR** (Dynamic Message Routing) for the mesh routing technology. **DMR cluster** for the horizontal-scaling pattern. **External links** for cross-cluster connections.
7. **A2A protocol** (Agent-to-Agent) for SAM's inter-component protocol.
8. **OrchestratorAgent** for the SAM orchestration component (one word, capital O).
9. **Agent Card** for the SAM agent's published capability profile.
10. **Event Portal**, **Solace Insights**, **Solace Schema Registry**, **Solace Cloud Console** as proper names.

### Note on "GDK" — terminology to verify with Giri

The current SAM open source documentation (`solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started/architecture`, version 1.19.0) explicitly references the **Gateway Development Kit (GDK)** as a real, named concept providing `BaseGatewayApp` and `BaseGatewayComponent` classes. This contradicts the project memory that "GDK" was internal shorthand mistakenly used as a public product name. Either the documentation has caught up to the term, the term has formally entered the product, or the original concern was about a different incident. Worth confirming with Giri before any external-facing content references GDK so we use the term correctly (or avoid it intentionally).

### Gateway versus Entrypoint — open question

The Solace Agent Mesh open source documentation at `solacelabs.github.io/solace-agent-mesh` (verified at versions 1.18.x and 1.19.x during the build of this reference) uses **Gateways** as the user-facing term throughout — components are named "HTTP SSE Gateway," "REST Gateway," "Event Mesh Gateway," and so on. The descriptive phrase "entry points" appears within the Gateway documentation, but "Gateway" remains the official component name in the current published docs.

Project notes indicate a Gateway → Entrypoint terminology transition is in progress, with user-facing prose moving to "entrypoint" while code identifiers, config keys, and named features retain "gateway." This transition is not visible in the published documentation as of the build of this reference.

**Direction for skills:** Match the surface being read. When generating content that will live inside the SAM project, defer to project-level naming guidance from Giri. When generating content that references the public docs as they currently stand, use "Gateway." Flag this for explicit confirmation before publishing externally-visible content that depends on the distinction.

---

## Scope rules

1. **In scope:** anything documented at `docs.solace.com`, `solacelabs.github.io/solace-agent-mesh`, `github.com/SolaceLabs`, or `solace.com/integration-hub`. Reference architectures and integration guides published by Solace are in scope.
2. **Out of scope:** capabilities or behaviors borrowed from non-Solace platforms (Kafka, Confluent, RabbitMQ, MuleSoft, Tibco, AWS messaging services, etc.) unless a Solace source explicitly addresses the integration or comparison.
3. **Living document:** when a real architecture problem touches Solace ground not yet covered here, surface the gap and update this document rather than silently filling it in from elsewhere.
4. **Verification status:** items marked with parenthetical notes ("not directly verified during the build of this reference") are confirmed as real Solace capabilities but their depth has not been pulled into this document. Skills needing depth must consult the canonical source rather than reasoning from analogy.

---

## Verification log

This log tracks when each canonical source was last verified against live Solace documentation. Each entry carries a verification date. When a date reads "pending re-verification," the entry was confirmed at the original build of this reference but has not been re-checked under the current source-recency discipline; treat the underlying claims as needing a re-fetch before relying on them in external deliverables.

Working refresh window: 90 days for stable platform pages, tighter (30 days) for SAM project pages where versions move fast.

### Anchor pages — verified 2026-04-29

These five pages were re-verified during the introduction of source-recency dating and serve as the project's most-grounded anchors. Their content matches the corresponding sections of this reference unless noted otherwise.

1. `docs.solace.com/Get-Started/solace-platform.htm` — three-layer model. **Verified: 2026-04-29.** Source page last updated 2026-04-23. Content matches.
2. `docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm` — topic taxonomy and anti-patterns. **Verified: 2026-04-29.** Source page last updated 2026-04-16. Content matches.
3. `docs.solace.com/Micro-Integrations/Micro-Integrations.htm` — Micro-Integration overview. **Verified: 2026-04-29.** Source page last updated 2026-02-19. **Finding:** the current page describes only source and target direction types for Solace Cloud Micro-Integrations; this reference document claims a third "processor" direction. The discrepancy needs investigation against `docs.solace.com/Micro-Integrations/Managed/managed-micro-integrations-overview.htm` before the claim is relied on. Treat the three-direction-type claim as **Unverified** pending that check.
4. `solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started/architecture` — SAM architecture overview. **Verified: 2026-04-29.** Source page version is now 1.19.1 (this reference previously cited v1.19.0). Content matches; the reference body's v1.19.0 citation should be read as v1.19.1.
5. `docs.solace.com/Features/DMR/DMR-Overview.htm` — DMR overview. **Verified: 2026-04-29.** Source page last updated 2026-04-23. Content matches the DMR section of this reference.

### Pages confirmed at original build, pending re-verification

These pages were directly fetched and reviewed during the original build of this reference. Their content informed the body of this document but has not been re-checked under the current source-recency discipline. Skills relying on these for external deliverables should re-fetch.

1. `docs.solace.com/Get-Started/feature-index.htm` — feature catalog. **Verified: original build, pending re-verification.**
2. `docs.solace.com/Get-Started/what-are-event-brokers.htm` — broker fundamentals. **Verified: original build, pending re-verification.**
3. `docs.solace.com/Get-Started/what-are-topics.htm` — topic architecture basics. **Verified: original build, pending re-verification.**
4. `docs.solace.com/Get-Started/message-delivery-modes.htm` — Direct and Guaranteed messaging. **Verified: original build, pending re-verification.**
5. `docs.solace.com/Agentic-AI/agent-mesh.htm` — SAM platform-level overview. **Verified: original build, pending re-verification.**
6. `docs.solace.com/Cloud/Event-Portal/event-portal-lp.htm` — Event Portal capabilities. **Verified: original build, pending re-verification.**
7. `docs.solace.com/Cloud/Insights/Insights.htm` — Insights capabilities. **Verified: original build, pending re-verification.**
8. `docs.solace.com/Features/Distributed-Tracing/Distributed-Tracing-Overview.htm` — Distributed Tracing. **Verified: original build, pending re-verification.**
9. `docs.solace.com/Schema-Registry/schema-registry-overview.htm` — Schema Registry. **Verified: original build, pending re-verification.**
10. `docs.solace.com/API/developer-lp.htm` — developer tools landing. **Verified: original build, pending re-verification.**
11. `docs.solace.com/API/Messaging-APIs/Solace-APIs-Overview.htm` — messaging APIs. **Verified: original build, pending re-verification.**
12. `solacelabs.github.io/solace-agent-mesh/docs/documentation/components/gateways` — SAM Gateways (cited at v1.19.1 at original build). **Verified: original build, pending re-verification.**
13. `solacelabs.github.io/solace-agent-mesh/docs/documentation/components/agents` — SAM Agents (cited at v1.18.35 at original build). **Verified: original build, pending re-verification.**
14. `solacelabs.github.io/solace-agent-mesh/docs/documentation/components/orchestrator` — SAM OrchestratorAgent (cited at v1.18.29 at original build). **Verified: original build, pending re-verification.**
15. Search results for `solace.com/integration-hub` content. **Verified: original build, pending re-verification.**

### Sections added from canonical source URLs — 2026-05-03

These sections were added based on canonical source URLs. Content was written from documented Solace capabilities at the listed URLs. Not yet independently re-verified against live pages.

1. `docs.solace.com/Features/Transactions/Transactions-Overview.htm` — Transactions (local, XA). **Added: 2026-05-03, pending re-verification.**
2. `docs.solace.com/Messaging/Direct-Msg/Direct-Msg-Eliding.htm` — Message Eliding. **Added: 2026-05-03, pending re-verification.**
3. `docs.solace.com/Features/Cache/cache-lp.htm` — Solace Cache / CacheInstance. **Added: 2026-05-03, pending re-verification.**
4. `docs.solace.com/Messaging/Direct-Msg/Direct-Msg-Shared-Subscriptions.htm` — Shared Subscriptions. **Added: 2026-05-03, pending re-verification.**
5. `docs.solace.com/Messaging/Guaranteed-Msg/Message-Priority.htm` — Message Priority. **Added: 2026-05-03, pending re-verification.**
6. `docs.solace.com/Features/VPN/VPN-Bridges.htm` — Message VPN Bridges. **Added: 2026-05-03, pending re-verification.**
7. `docs.solace.com/Cloud/cloud-service-class-comparison.htm` — Performance and sizing (service classes). **Added: 2026-05-03, pending re-verification.**
8. `docs.solace.com/Software-Broker/sw-broker-sys-reqs.htm` — Performance and sizing (SW broker requirements). **Added: 2026-05-03, pending re-verification.**
9. `docs.solace.com/Software-Broker/sw-broker-kubernetes-operator.htm` — Kubernetes Operator (expanded). **Added: 2026-05-03, pending re-verification.**
10. Integration patterns section — written from first principles grounded in platform primitives (Message Replay, Guaranteed messaging, topics). **Added: 2026-05-03. Architectural inference, not from a single source page.**

### Pages explicitly not fetched, should be added in subsequent revisions

1. SAM Workflows, Proxies, Platform Service, Plugins, Projects component pages.
2. Event Portal Designer, Runtime Event Manager, and KPI Dashboard detail pages.
3. Self-Managed and Cloud-Managed Micro-Integration deep-dive pages (specifically `Managed/managed-micro-integrations-overview.htm`, needed to resolve the direction-types finding above).

### Maintenance discipline

When a section of this reference is re-verified against live docs, update the entry's date to the verification date. When source pages have changed in ways that affect this reference's claims, update both the relevant section body and the verification log entry. Stale grounding is silent grounding failure.

---

## Version note

A Solace Agent Mesh component-page version drift is visible in the current docs. As of 2026-04-29, the architecture page is at v1.19.1 (re-verified). Gateways, Agents, and OrchestratorAgent component pages were captured at v1.19.1, v1.18.35, and v1.18.29 at the original build of this reference and have not been re-verified since.

This drift is normal for a fast-moving project. Skill content drawn from these pages should record which version was the source, and a periodic refresh discipline is needed — particularly for SAM, where the 30-day refresh window applies rather than the 90-day default for stable platform pages.