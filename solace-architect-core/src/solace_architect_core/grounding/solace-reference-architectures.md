# Solace reference architectures

## Purpose

This document holds worked examples of how Solace components compose to solve real architectural problems. Each pattern names the problem, the architectural shape, the Solace components used, key design decisions, known variations, and pattern-specific antipatterns.

It complements the other two grounding documents but does a different job. The platform reference says *what exists and how it's organized*. The canonical sources index says *where to read*. This document says *how the pieces compose to solve a real problem*. Skills generating blueprints, validating designs, or matching a user's situation to a known shape will reach for this document. Discovery skills can use the patterns to surface industry-specific question paths.

This is a living document. Three to start. More will be added as skill development surfaces patterns worth capturing. When a real engagement encounters a pattern not yet here, that's a signal to add it rather than reason from analogy.

### Source rules for this document

The platform reference and canonical sources index are grounded in `docs.solace.com`, `solacelabs.github.io`, and the SolaceLabs GitHub organization. This document is allowed to additionally draw on `solace.com` solution pages, blog posts, white papers, and case studies for *narrative framing* — what verticals Solace serves, what business problems they solve, which customers run them.

Capability claims, configuration details, and technical specifics within each pattern still ground in `docs.solace.com` and the SAM project documentation. Marketing pages provide the *story*; the technical pages provide the *truth*. Where the two conflict, technical documentation wins.

Each pattern's Sources section names which specific URLs were used. Pattern claims that cannot be cited from a Solace source are marked explicitly as architectural inference rather than presented as fact.

### Verification convention

Each pattern carries a "Pattern grounding last verified" date immediately after its title. This date reflects when the pattern's most-relied-on technical sources were last re-fetched against live Solace documentation. Marketing sources (used for narrative framing) carry a wider tolerance because the framing they support is less time-sensitive than capability claims.

When using a pattern for an external deliverable, check the verification date. If the technical sources are within the working refresh window (90 days for stable platform pages, 30 days for SAM project pages), the pattern can be relied on with the standard citation discipline. If the sources are outside that window, re-fetch the relevant URLs before using the pattern in output that will be presented as authoritative.

---

## Pattern catalog

1. **Multi-system AI assistant** — Solace Agent Mesh as the orchestration layer for an enterprise AI assistant that draws on multiple backend systems. Vertical: retail banking (working example), broadly applicable.
2. **Real-time market data distribution** — event mesh as the backbone for distributing market data and order flow across global trading hubs. Vertical: capital markets.
3. **Hybrid IT/OT manufacturing event mesh** — federated event mesh from plant floor to cloud, integrating operational technology with enterprise systems. Vertical: discrete and process manufacturing.

These three were chosen to span the platform's range. Pattern 1 is SAM-centric. Pattern 2 is event-mesh-only with no agents — a deliberate choice to demonstrate that the toolkit's first-class support extends beyond agentic AI. Pattern 3 sits between, with SAM as an optional extension on top of a fundamentally event-mesh problem.

---

## Pattern 1: Multi-system AI assistant

**Pattern grounding last verified: 2026-04-29.** SAM architecture and Topic best practices sources re-fetched on this date; SAM platform overview and Gateways/OrchestratorAgent component pages remain on original-build verification. Re-verify SAM project sources within 30 days for external deliverables.

### Problem

An enterprise wants to expose a conversational interface (web chat, Slack, Teams, mobile app, voice) that can answer end-user questions by drawing on multiple backend systems of record. The questions span domains the systems cover separately: account balances, ticket status, FAQ knowledge base, order history, transaction queries.

The hard part is not the language understanding. The hard part is the orchestration — routing each question to the right backend, maintaining authorization scope across system boundaries, handling failures gracefully, returning a coherent response, and operating reliably at production scale across hybrid infrastructure.

A monolithic chatbot wired directly to each backend creates tight coupling, fragile failure modes, and a single point of authorization. It also doesn't compose: adding a new backend means reworking the assistant.

### Architectural pattern

Solace Agent Mesh provides the orchestration substrate. The shape:

1. The user-facing channel (web, Slack, Teams, mobile, voice) connects to a SAM **Gateway** that handles authentication, translates the inbound request into the A2A protocol, and routes it onto the event mesh.
2. An **OrchestratorAgent** receives the request, analyses it, and breaks it into sub-tasks dispatched to specialised agents. The agent registry (populated by AgentCard discovery) tells the orchestrator which agents are available.
3. **Domain agents** each own one backend domain. A balance agent talks to the core banking system. A ticket agent talks to the service-management system. A knowledge agent searches the FAQ corpus or vector store. Each agent's tools are filtered by user permission scopes propagated through the A2A request.
4. **Micro-Integrations** connect the domain agents (or in some cases the broker directly) to the actual systems of record — Oracle Financials, ServiceNow, Salesforce, mainframe systems exposed through their respective Micro-Integrations.
5. Agent-to-agent delegation handles cross-domain questions (e.g. "what's my balance and do I have any pending tickets") via the orchestrator's task plan, with permission scopes propagated through the delegation chain.
6. Status updates flow back to the originating gateway over the A2A status topic; the gateway formats them for the channel and streams them to the user.

The event mesh is the integration plane. No agent or gateway needs to know where another agent runs or what backend any given agent talks to.

### Solace components used

1. **Solace event broker** (Cloud, Software, or Appliance — the choice depends on regulatory and latency requirements, see Variations below). Provides the A2A messaging fabric.
2. **Solace Agent Mesh** (open source or Enterprise). Orchestrator, Gateways (HTTP SSE for web, REST for programmatic, Slack and Teams plugin gateways for those channels, custom Gateway for voice or proprietary frontends), Agents, A2A protocol, Agent Cards, peer delegation.
3. **Micro-Integrations** to backend systems. Cloud-managed where the system has a managed Micro-Integration available. Self-managed where customisation or self-hosting is required.
4. **Solace Schema Registry** for the event schemas that flow between agents and backends, with versioning support for safe evolution.
5. **Distributed Tracing** for end-to-end observability of a user's request as it crosses gateways, agents, and Micro-Integrations.
6. **Solace Insights** for operational monitoring of the broker and the agent mesh.
7. Optional: **Event Portal** for designing the agent-to-system event topology and governing schemas.

### Key design decisions

1. **Single OrchestratorAgent versus multiple.** A single orchestrator simplifies reasoning about end-to-end flows. Multiple orchestrators (SAM supports this) make sense when domains are sufficiently distinct — for example, separating customer-facing queries from internal-employee queries — and the orchestration logic differs.
2. **Agent granularity.** Coarse-grained agents (one agent per backend system) are easier to reason about and align with team ownership. Fine-grained agents (one agent per capability) compose better but multiply the agent count and discovery traffic. Start coarse; split when justified.
3. **Authorisation propagation.** Permission scopes set at the gateway must propagate through the orchestrator and through any peer delegation. The pluggable AuthorizationService is where the org's identity model meets SAM. Skills generating this pattern should always check that the auth model is concretely defined before assuming the gateway scope-extraction step works.
4. **Channel multiplexing.** Multiple gateway types can front the same agent mesh. The same balance agent serves web, Slack, and voice without modification. The gateways differ only in their protocol translation and channel-specific formatting.
5. **Memory and session management.** SAM agents support session continuity through ADK's session management. Whether sessions are scoped per-channel, per-user, or per-conversation thread is a design choice with downstream consequences for context length, billing, and privacy.
6. **Backend access pattern.** An agent can call its backend directly through a custom Python tool, or it can publish a request event onto the mesh that a Micro-Integration handles. The latter is more decoupled and more observable; the former is simpler. The decoupled pattern scales better when multiple agents need the same backend.

### Known variations

1. **SAM Enterprise vs open source.** Enterprise adds production capabilities (enhanced security controls, advanced monitoring, support, scale). For regulated workloads (banking, healthcare, government), Enterprise is typically required.
2. **Internal-only versus customer-facing.** Internal assistants relax some security constraints and can call internal-only systems directly. Customer-facing assistants typically require additional gateways for rate limiting, abuse prevention, and customer authentication, often via existing IAM (OIDC, SAML).
3. **Voice channel.** The Speech Integration component adds voice support; the gateway shape stays the same but voice-specific formatting and latency considerations apply.
4. **Remote A2A agents.** When parts of the agent ecosystem live in different infrastructure (e.g. a vendor-supplied agent), Proxies bridge A2A-over-HTTPS to A2A-over-Solace and the remote agent appears as a native mesh participant.

### Antipatterns to flag

1. **Including environment names (`dev`, `qa`, `prod`) in agent topics or in the SAM `{namespace}`.** This is the same antipattern Solace's topic best practices document calls out at the broker level; it applies equally to A2A topics. Use environment-separated brokers, message VPNs, or namespaces — not topic-encoded environments.
2. **Letting an agent skip the orchestrator on cross-domain tasks.** Agents calling each other directly without orchestrator awareness defeats workflow management and observability. Use peer delegation through `PeerAgentTool`, which the orchestrator tracks.
3. **Hardcoding backend credentials in agent YAML.** Authentication to backends should flow through the AuthorizationService and Micro-Integration credential management, not be embedded in agent configuration. The SAM agent YAML should be safe to store in version control alongside application code.
4. **Reasoning about agent behaviour in synchronous request/response terms.** SAM is asynchronous and event-driven by design. Treating an agent call as a blocking RPC will produce architectures that don't scale and don't tolerate failure correctly.
5. **Building a custom gateway when an existing gateway type fits.** The framework's value is in the common base; custom gateways are appropriate when the channel itself is novel, not when a small protocol variation could be handled in configuration or in a plugin.

### Sources for this pattern

1. SAM platform overview: `https://docs.solace.com/Agentic-AI/agent-mesh.htm`
2. SAM architecture: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started/architecture`
3. SAM Agents: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/agents`
4. SAM OrchestratorAgent: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/orchestrator`
5. SAM Gateways: `https://solacelabs.github.io/solace-agent-mesh/docs/documentation/components/gateways`
6. SAM AWS Marketplace listing (multi-system chatbots named as a use case): `https://aws.amazon.com/marketplace/pp/prodview-wxwtnzatp5czi`
7. Topic architecture best practices (for the antipatterns): `https://docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm`

---

## Pattern 2: Real-time market data distribution

**Pattern grounding last verified: 2026-04-29.** Topic best practices and DMR overview sources re-fetched on this date. Marketing sources (28Stone white paper, financial services solution briefs) remain on original-build verification — these inform narrative framing rather than capability claims, so the recency tolerance is wider, but should be refreshed within 90 days before any external deliverable that quotes them.

### Problem

A capital markets firm — investment bank, hedge fund, exchange, FX trading platform — needs to distribute market data and order flow across global trading hubs (typically New York, London, Singapore, Tokyo, Hong Kong) with sub-millisecond latency on the hot path, guaranteed delivery on the audit path, and protocol heterogeneity end to end. The firm's traders sit in browsers consuming WebSocket streams. Its backend feed handlers publish over native protocols. Its analytics platforms consume over AMQP or JMS. Its compliance and audit systems require persistent, replayable streams.

The architecture must serve all of those consumers off a single distribution infrastructure, must federate across geographies, and must operate with no degradation during market hours under message volumes that can exceed 100 billion messages per day at peak.

### Architectural pattern

Event mesh is the distribution backbone. No agents involved — this is a pure event-driven integration problem. The shape:

1. **Backend feed handlers** publish market data to event brokers using SMF (Solace's native Solace Message Format), the lowest-latency protocol. Different feed sources publish under different topic prefixes within a hierarchical taxonomy that encodes asset class, instrument, and exchange.
2. **Trading hubs** in NY, London, Singapore are each anchored by an HA event broker cluster (DMR cluster — full mesh of internal links — for horizontal scaling within the hub).
3. **DMR external links** federate the per-hub clusters into a single global event mesh. Subscriptions propagate dynamically: when a London trader subscribes to a US equity, the subscription is learned and the relevant data flows from the NY cluster across the DMR external link.
4. **Trader UIs** in the browser consume relevant slices of the data over WebSocket, subscribing to fine-grained topics that filter by symbol, asset class, region, or whatever the rich topic hierarchy enables.
5. **Analytics applications** consume over AMQP, JMS, or REST, depending on the application's native messaging support.
6. **Order flow** travels the same mesh in the reverse direction from trader UIs and execution algorithms to order management systems.
7. **Audit and compliance** subscribe to Guaranteed messaging endpoints with persistent storage and replay capability, separate from the Direct messaging fast path serving traders.
8. **Replication** between active and standby brokers in each hub provides DR. Replication groups appear to DMR as a single node, simplifying the routing model.

### Solace components used

1. **Solace event brokers** — typically Solace Appliance Event Brokers in colocated datacentre deployments where ultra-low-latency matters most, or Solace Software Event Brokers on dedicated hardware where flexibility matters more. Solace Cloud event broker services are used for less latency-sensitive consumers (analytics, compliance, secondary data centres).
2. **DMR** — clusters within hubs, external links between hubs.
3. **Replication** — for DR within and across regions, interoperating with DMR.
4. **Topic architecture** — the rich hierarchy is the routing instrument. A canonical topic for an FX rate update might look like `marketdata/fx/spot/v1/{currencyPair}/{venue}/{publisher}`; trader subscriptions are filtered to taste.
5. **Direct messaging** for the latency-sensitive trader path. **Guaranteed messaging** for the order-flow audit path and for any consumer that must survive a disconnect.
6. **Open protocols** — SMF for backend, WebSocket for browser, AMQP and JMS for analytics. The broker handles protocol mediation; clients use what fits their stack.
7. **Solace Insights** for operational monitoring across the global mesh.
8. **Distributed Tracing** for slower-path investigations (root-cause analysis on order rejections, audit reconciliation). Direct-messaging fast path typically does not enable tracing — the overhead is incompatible with the latency budget.

### Key design decisions

1. **Direct versus Guaranteed per data class.** Market data fan-out to trader UIs is overwhelmingly Direct. Order submissions, fills, and audit streams are Guaranteed. The decision is per-topic, not per-broker.
2. **Per-hub topology versus single global cluster.** Single global cluster is simpler but cannot meet latency requirements for traders distant from the cluster. Per-hub clusters federated by DMR external links is the standard pattern at scale.
3. **Topic hierarchy is the integration contract.** Every consumer agrees on the topic taxonomy. Changes are managed through Schema Registry and Event Portal. Versioning (`v1`, `v2`) is mandatory for non-breaking evolution.
4. **Subscription hygiene.** Traders subscribing to overly broad wildcards (e.g. `marketdata/>`) create unnecessary inter-hub traffic. The subscription propagation model means traders' wildcards are real bandwidth costs across DMR external links. Skills generating this pattern should flag overly broad subscriptions during validation.
5. **Failure and degradation behaviour.** Direct messaging is lossy under congestion. Whether that's acceptable depends on the data class: for tick data, marginally lossy is acceptable; for order acknowledgments, never. Mixed-mode designs are normal.
6. **Where Kafka fits.** Many capital markets firms have existing Kafka deployments for downstream analytics and data lake feeds. The Solace-Kafka bridge (Broker Integrated, not a Spring Boot Micro-Integration) connects the two without forcing a migration.

### Known variations

1. **Pre-trade versus post-trade.** Pre-trade flows (market data, quotes, orders) are latency-dominated. Post-trade flows (settlement, reconciliation, regulatory reporting) are correctness-dominated. Same mesh, different topics, different QoS settings.
2. **FX versus equities versus fixed income.** Topic taxonomies differ. The architectural pattern is the same.
3. **Cloud-only versus hybrid.** Some firms operate fully in cloud (with appropriate compliance approval); others remain on-prem for regulatory reasons; most are hybrid. The mesh extends across the boundary either way.
4. **Internal distribution versus external distribution.** Distributing market data to internal traders is one shape. Distributing to external clients (e.g. a sell-side firm distributing to buy-side clients) adds entitlements, contracts, and external-facing gateways with their own authentication models.

### Antipatterns to flag

1. **Treating the mesh as a request/response system.** Hot-path market data is one-to-many fan-out. Designs that make trader UIs send heartbeats for every subscription, or that introduce per-subscriber broker round trips, will collapse under volume.
2. **Encoding tracing data in topics.** This is the same antipattern Solace's topic best practices document calls out generally; it shows up especially in capital markets where compliance pressure tempts teams to put audit IDs in topic strings. Use Distributed Tracing instead.
3. **Mixing Direct and Guaranteed messaging on the same critical path without explicit design.** A subscriber bound to a queue (Guaranteed) downstream of a Direct publisher does not magically get persistence. Each leg's QoS must be designed.
4. **Using DMR external links for high-volume bidirectional flows when guaranteed delivery semantics are required.** External links handle this correctly, but the design should be explicit about which direction carries which class of traffic. Asymmetric flows (US-to-Europe market data, Europe-to-US order routing) are the norm; symmetric high-volume bidirectional is a smell.
5. **Building a custom client library when a published Solace API for the language already exists.** The 11 supported language APIs are battle-tested at the volumes capital markets demands. Custom clients introduce risk that compounds at scale.

### Sources for this pattern

1. Solace homepage (statements about top investment banks and FX trading banks): `https://solace.com/`
2. Financial Services solutions hub: `https://solace.com/resources/financial-services`
3. Modernise post-trade processing solution brief: `https://solace.com/resources/financial-services/modernize-and-future-proof-post-trade-processing-with-an-event-mesh-solutionbrief`
4. 28Stone reference trading platform white paper: `https://solace.com/resources/financial-services/wp-download-28stone-white-paper-leveraging-pubsub-platform-for-real-time-trading-systems`
5. Topic architecture best practices: `https://docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm`
6. DMR overview: `https://docs.solace.com/Features/DMR/DMR-Overview.htm`
7. Message delivery modes: `https://docs.solace.com/Get-Started/message-delivery-modes.htm`
8. Replication with DMR: `https://docs.solace.com/Features/DR-Replication/Replication-with-DMR.htm`

---

## Pattern 3: Hybrid IT/OT manufacturing event mesh

**Pattern grounding last verified: 2026-04-29.** Topic best practices, Micro-Integrations overview, and DMR overview sources re-fetched on this date. **Finding from re-verification:** the current Micro-Integrations overview page describes only source and target direction types for Solace Cloud Micro-Integrations; this pattern's Solace components section may need adjustment if the deeper Managed Micro-Integrations page does not confirm the third "processor" direction. Manufacturing solution briefs and case studies remain on original-build verification.

### Problem

A discrete or process manufacturer wants to integrate plant floor systems with enterprise IT and cloud analytics. The plant floor is heterogeneous: machines from multiple vendors (Siemens, Honeywell, Rockwell), running multiple protocols (Modbus, OPC UA, MQTT, DDS), generating sensor and equipment data through IoT gateways (Siemens SIMATIC, Dell Edge Gateway, Bosch Rexroth) and historians (OSIsoft PI System). Plant-side applications include MES, SCM, and PPM. Enterprise IT runs ERP, CRM, master data, and data warehouses. Analytics, ML training, and predictive maintenance live in the cloud (AWS, Azure, GCP, or vendor IoT platforms like Siemens MindSphere).

The hard part is that the plant floor cannot tolerate cloud round-trip latencies for control loops, the cloud cannot tolerate plant-floor protocol heterogeneity, and the enterprise IT layer needs both plant data (for operational visibility) and cloud analytics output (for decision support).

### Architectural pattern

A hybrid event mesh that extends from plant floor to cloud, with brokers placed at each scaling boundary. The shape:

1. **Edge brokers** in each plant ingest data from machines, sensors, IoT gateways, and historians. The edge brokers can be co-located with plant systems, deployed onto the IoT gateways themselves where supported, or run on plant-floor servers.
2. **Self-Managed Micro-Integrations** event-enable systems that are not natively event-driven: historians, MES databases, SCADA systems via OPC UA bridges. Where Solace publishes a Micro-Integration for the system (PI System, SAP MII, etc.), it's used directly; where not, custom Micro-Integrations or partner-built integrations fill the gap.
3. **Plant brokers federate via DMR cluster** within a plant for horizontal capacity, and via DMR external links between plants and to regional aggregation brokers.
4. **Regional or HQ brokers** receive curated streams from multiple plants, integrate with enterprise IT systems (ERP, CRM, master data) via Cloud-Managed Micro-Integrations or self-managed Micro-Integrations, and forward analytics-ready data to cloud.
5. **Cloud brokers** (Solace Cloud event broker services) feed cloud-native analytics, ML training, and data lakes. The Kafka bridge (Broker Integrated) handles the common case of cloud analytics teams running on Kafka.
6. **Bidirectional flow** carries control data, configuration changes, and predictive-maintenance recommendations back from cloud to plant. Topic taxonomy distinguishes telemetry (plant→cloud) from commands (cloud→plant), and ACLs enforce that distinction at every hop.
7. **Optional SAM extension** on top: AI agents in the cloud can analyse aggregated telemetry, generate predictive maintenance recommendations, and route them back via the mesh to plant operators or to scheduling systems. The mesh provides the agents their data; the agents provide the mesh new events.

### Solace components used

1. **Solace Software Event Brokers** at the edge (in plant), sized for plant volume. **Solace Cloud event broker services** at the cloud apex. **Solace Appliance Event Brokers** at high-volume regional aggregation sites if performance demands warrant.
2. **DMR** — clusters within plants and within regions, external links between plants, regions, and cloud.
3. **Smart Topic Architecture** — a hierarchy that encodes plant, line, machine, sensor, and event type. Example shape: `manufacturing/{plantId}/{lineId}/{machineId}/{sensorOrEvent}/{verb}/v1/{properties}`. The taxonomy lets each consumer subscribe at the right granularity (one machine, one line, one plant, fleet-wide).
4. **Micro-Integrations** — self-managed at the edge for OT system event-enablement, cloud-managed for ERP and SaaS integration, partner-built where vendor-specific (e.g. Siemens, Rockwell connectors).
5. **Solace Schema Registry** — schemas evolve as machines are added, replaced, or upgraded. Schema Registry's versioning rules are essential for managing this evolution without breaking downstream consumers.
6. **Event Portal** — for designing the topic taxonomy across plants, governing schema ownership across OT and IT teams, and managing runtime configuration handoff between plant integration teams and enterprise developers.
7. **Solace Insights** — operational monitoring of brokers across the federation. Particularly important for plant operations where mesh issues directly affect production.
8. **Distributed Tracing** — for diagnosing data-flow issues across the OT-to-IT-to-cloud path.
9. **Optional Solace Agent Mesh** — for predictive maintenance, anomaly investigation agents, fleet-wide pattern detection.

### Key design decisions

1. **Where to terminate OT protocols.** OPC UA, Modbus, DDS, and SCADA protocols typically don't extend beyond the plant. The Micro-Integration or edge gateway terminates them and re-publishes onto the broker as standardised events. The boundary is the plant edge broker.
2. **Edge versus regional aggregation.** Tiny plants can connect directly to a regional broker. Larger plants benefit from local edge brokers for resilience (continued local operation if WAN fails) and bandwidth (filtering and aggregation before WAN transmission).
3. **Filtering at the edge versus at the apex.** Filtering at the edge saves WAN bandwidth and cloud ingestion cost. Filtering at the apex preserves more data for ad-hoc analysis. The trade-off is volume-dependent and changes as cloud storage costs change.
4. **Telemetry versus command separation.** Telemetry (plant→cloud) and commands (cloud→plant) should travel under distinct topic prefixes. ACL profiles should enforce that command topics can only be published by authorised systems. Cross-direction wildcards are an antipattern.
5. **Resilience to WAN partition.** Plant operations must continue when the WAN to regional or cloud is degraded. This means edge brokers must be operationally complete on their own — sufficient capacity, persistence, and HA for plant-local needs without depending on the cloud apex.
6. **Where SAM enters.** SAM is an extension, not a foundation. The event mesh layer is justified independently. SAM is added when there's a real need for autonomous reasoning over the data (predictive maintenance recommendations, fleet-wide anomaly investigation, conversational operator interfaces). Deploying SAM without first having the event mesh in place inverts the architecture.

### Known variations

1. **Single-plant versus multi-plant.** A small manufacturer with one plant may not need DMR external links; a global manufacturer with dozens of plants depends on them.
2. **Greenfield versus brownfield.** Greenfield deployments can adopt the topic taxonomy from day one. Brownfield deployments inherit existing systems and existing event flows; the integration approach is incremental — Solace Integration Guides cover specific brownfield cases (SAP, IBM MQ, OSIsoft PI).
3. **Vendor IoT platform integration.** Plants already invested in Siemens MindSphere or equivalents typically keep them and connect to the mesh rather than replace them. Custom or partner Micro-Integrations bridge.
4. **Edge AI and anomaly detection.** Some firms run lightweight ML at the edge for anomaly detection or quality control. The mesh delivers training data to the cloud and trained models or rules back to the edge. SAM is one way to operate this loop; classical pipelines are another.

### Antipatterns to flag

1. **A single global broker for the whole enterprise.** Single-broker topologies don't survive WAN partitions and concentrate risk. Federate.
2. **Plant-floor systems calling cloud APIs synchronously.** The latency, availability, and security implications are wrong. Decouple via the mesh.
3. **Encoding plant ID, line ID, or machine ID in topic root rather than as properties.** Topic root should be `Domain/Noun/Verb/Version`. Plant/line/machine are properties — least-specific to most-specific. Putting them in the root makes cross-plant subscriptions awkward and breaks the published best-practice taxonomy.
4. **Skipping Schema Registry on the assumption that events from OT are simple.** OT data evolves: sensors get added, replaced, recalibrated. Without versioning discipline, downstream consumers break silently when events change shape.
5. **Bridging Kafka and the event mesh in both directions for the same topic.** Pick one direction of authority per topic. Bidirectional bridging without explicit design produces loops.
6. **Treating the cloud apex as the system of record.** The plant floor is the system of record for plant events. The cloud is a derived view. Architectures that invert this assumption tend to fail audits and to lose data when cloud goes down.

### Sources for this pattern

1. Solace digital manufacturing transformation blog: `https://solace.com/blog/digital-manufacturing-transformation/`
2. Manufacturing solutions hub: `https://solace.com/resources/manufacturing/hybrid-iot-event-mesh-for-digital-manufacturing-transformation-video`
3. Manufacturing event mesh datasheet: `https://solace.com/resources/datasheets/event-mesh-for-manufacturing-digital-transformation-datasheet`
4. Smart factories white paper: `https://solace.com/resources/white-papers/wp-download-event-driven-architecture-smart-factories-manufacturing`
5. IoT EDA resources hub: `https://solace.com/resources/internet-of-things-iot-event-driven`
6. Topic architecture best practices: `https://docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm`
7. Micro-Integrations overview: `https://docs.solace.com/Micro-Integrations/Micro-Integrations.htm`
8. DMR overview: `https://docs.solace.com/Features/DMR/DMR-Overview.htm`

---

## Adding a new pattern

When adding a new reference architecture, follow the structure used by the three above. Each entry should answer:

1. **Problem** — what business problem is being solved, what makes it hard. One paragraph minimum, two if the problem itself benefits from elaboration. No solution language yet.
2. **Architectural pattern** — the high-level shape, in numbered steps that describe the data and control flow.
3. **Solace components used** — a numbered list naming the components, with the role each one plays in this pattern. Cross-reference the platform reference document by component name.
4. **Key design decisions** — the trade-offs that have to be made for this pattern. Each decision frames the alternatives and the criteria for choosing.
5. **Known variations** — how the pattern adapts to common context shifts (vertical, scale, regulatory, greenfield-versus-brownfield).
6. **Antipatterns to flag** — pattern-specific mistakes the validation skill should detect. These should be concrete and pattern-specific, not generic Solace antipatterns (those live in `solace-platform-reference.md`).
7. **Sources** — every URL the pattern was grounded in. Distinguish technical sources (`docs.solace.com`, `solacelabs.github.io`) from solution sources (`solace.com`).

A new pattern earns its place in this document if at least one of these is true: a real engagement has surfaced it, a published Solace reference architecture exists for it, or a skill has reasoned about it from first principles and the inferences would benefit from being captured for reuse.

Patterns that are minor variations of an existing one should be added as a Variation under the existing pattern, not as a new entry. The document grows by capturing distinct shapes, not by enumerating every parameterisation.

---

## Limitations and verification status

The three patterns above are *worked examples*, not Solace-published reference architectures. Solace publishes white papers, solution briefs, and customer case studies that describe how these patterns appear in practice; the patterns here synthesise those sources into a structured form skills can reason over.

Specific limitations:

1. **Pattern 1 (multi-system AI assistant)** is grounded in SAM documentation and Solace's own statements that multi-system chatbots are a SAM use case. The bank chat agent specifically is a working example for this project rather than a Solace-published reference. Skills generating this pattern for an external audience should ground variant claims in the SAM project documentation rather than in this document alone.

2. **Pattern 2 (real-time market data distribution)** is grounded in publicly documented capabilities and in Solace's published customer references (28Stone trading platform, RBC Capital Markets, "6 of top 10 investment banks"). Specific latency numbers, throughput numbers, and capacity figures are intentionally not included; these vary by deployment and require verification before any external use.

3. **Pattern 3 (hybrid IT/OT manufacturing event mesh)** is grounded in Solace's manufacturing solution content and in the published customer references (Bosch, Groupe Renault, Heineken). Specific Micro-Integration availability for specific OT systems should be confirmed against the Integration Hub at the time of skill generation; the Micro-Integration catalog evolves.

When skill development surfaces gaps in these patterns — claims that don't ground, design decisions that don't generalise, antipatterns that miss real failures — the document should be updated rather than worked around.