# Solace Antipattern Library

Extracted from reference architectures and Solace documentation. Every validation
skill and technical domain skill should check output against these patterns.

## Topic design antipatterns

### Environment names in topics
**What's wrong:** Encoding `dev`, `qa`, `prod` in topic strings (e.g., `prod/orders/created/v1`).
**What to do instead:** Use environment-separated brokers, message VPNs, or namespaces.
**Source:** Topic Architecture Best Practices (`docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm`), Pattern 1 antipatterns.

### Encoding tracing or audit IDs in topics
**What's wrong:** Putting correlation IDs, trace IDs, or audit trail identifiers in topic strings.
**What to do instead:** Use message properties or Distributed Tracing. Topics are routing instruments, not metadata carriers.
**Source:** Topic Architecture Best Practices, Pattern 2 antipatterns.

### Overly broad wildcard subscriptions across DMR
**What's wrong:** Subscribing to `marketdata/>` or similar broad wildcards when connected via DMR external links. Subscriptions propagate across links, pulling all matching data across the WAN.
**What to do instead:** Use fine-grained subscriptions that filter by instrument, asset class, or region. Each wildcard is a real bandwidth cost across DMR external links.
**Source:** Pattern 2 key design decisions (subscription hygiene).

### Misplaced multi-level wildcard (`>`)
**What's wrong:** Writing subscriptions like `airport/>/v1` or `airport/{noun}/>/v1/>` where `>` is not by itself at the last level of the subscription. Per the Solace docs ("Wildcard Characters in Topic Subscriptions"), a `>` that appears anywhere other than by itself at the last level is **treated as the literal `>` character rather than a wildcard**. The subscription is accepted by the broker but it matches a literal `>` at that position rather than expanding multi-level — so the subscription silently matches nothing or the wrong topics. Examples observed in agent output:
- `airport/{noun}/>/v1/>` — both `>` characters demoted to literals
- `airport/>/v1/>` — both `>` characters demoted to literals
- `>/passenger/v1` — first `>` demoted to a literal
- `animals/domestic>` — `>` is not by itself at the level (demoted to a literal)

**What to do instead:** Restructure so the wildcard portion is at the end of the topic. If the design needs both a flexible middle and a fixed trailing pattern, either:
1. **Re-order the taxonomy** so the variable parts come last (`airport/v1/passenger/>` instead of `airport/passenger/>/v1`).
2. **Use multiple narrower subscriptions** (one per known middle value).
3. **Use `*` for middle levels** — `*` matches a single level anywhere in the subscription: `airport/*/passengerUpdate/v1/>` works, `airport/>/v1/>` does not.
**Source:** docs.solace.com → `Messaging/Wildcard-Charaters-Topic-Subs.htm` (verified 2026-05-22).

### MQTT wildcards (`+`, `#`) used in Solace subscriptions
**What's wrong:** Writing Solace subscriptions with MQTT wildcard syntax — `+` for single-level or `#` for multi-level — e.g. `usEast/supplyChain/shipment/+/v1/>` or `usEast/supplyChain/#`. `+` and `#` are **MQTT** topic-filter wildcards, NOT Solace SMF wildcards. Solace uses `*` (single-level) and `>` (multi-level). A Solace broker does **not** treat `+` or `#` as wildcards: `+` is not a reserved character, so it is accepted as a **literal** `+` in that level and the subscription silently matches (almost) nothing; `#` collides with Solace reserved prefixes (`#share`, `#noexport`, `#P2P`). The hybrid form (`+` together with a Solace `>`) is a tell-tale sign of MQTT/SMF confusion. This is especially dangerous in interactive question cards and recommendations, which are generated free-form and bypass the artifact antipattern check.
**What to do instead:** Use Solace syntax everywhere — `*` for a single level, `>` (last position only) for multi-level. `usEast/supplyChain/shipment/*/v1/>` (not `…/+/v1/>`); `usEast/supplyChain/>` (not `usEast/supplyChain/#`). MQTT clients still publish/subscribe over MQTT, but the broker's internal topic strings and any SMF subscription you document use `*`/`>`.
**Source:** docs.solace.com → `Messaging/Wildcard-Charaters-Topic-Subs.htm` and `Messaging/SMF-Topics.htm` (verified 2026-05-22); MQTT wildcard syntax per the OASIS MQTT spec.

### Topic exceeds broker hard limits
**What's wrong:** Generating topics that exceed Solace's hard limits — more than **250 characters** total, or more than **128 levels**. These are broker-enforced, not advisory.
**What to do instead:** Keep topics compact. Long property tails should be shortened (use IDs, not human-readable names) or moved out of the topic and into the payload. Reviewers should flag any generated example or schema that approaches the limits.
**Source:** docs.solace.com → `Messaging/Topic-Architecture-Best-Practices.htm` (verified 2026-05-22): "A topic is limited to a maximum of 250 characters and 128 topic levels."

### Reserved characters in published topics
**What's wrong:** Publishing on topics that contain `*`, `>`, or `!`, or contain spaces / non-alphanumeric characters. The wildcard and negation characters have subscription semantics and must not appear in produced topics. Spaces and most special characters are simply unsupported in topic strings.
**What to do instead:** Use camelCase or PascalCase. Restrict topic characters to alphanumerics, `-`, `_`, and `/` (the level separator). Move any free-text values into the message payload.
**Source:** docs.solace.com → `Messaging/Topic-Architecture-Best-Practices.htm` (verified 2026-05-22) and `Messaging/Wildcard-Charaters-Topic-Subs.htm`.

### Stale telemetry queued through Guaranteed messaging
**What's wrong:** Sending high-rate telemetry (sensor readings, market ticks, position updates) through a Guaranteed queue without bounding TTL or using a last-value queue. Slow consumers cause queue depth to grow; the broker accumulates stale data that has no business value.
**What to do instead:** For last-value-wins flows, use **Direct messaging with message eliding** (consumer-pace-limited Direct delivery) or **Last-Value Queues** (queue max-spool-usage = 0, broker keeps only the most recent message) or **Solace Cache** (external last-value cache). Reserve Guaranteed queues for flows where every message matters.
**Source:** docs.solace.com → `Messaging/Direct-Msg/Direct-Messages.htm` (eliding) and `Features/Replay/Replay-Cache-Compare.htm` (verified 2026-05-22).

### Plant/line/machine ID in topic root instead of properties
**What's wrong:** Structuring topics as `plant01/line03/machine07/temperature/read/v1` instead of using the recommended taxonomy.
**What to do instead:** Topic root should be `Domain/Noun/Verb/Version`. Plant, line, and machine are properties ordered least-specific to most-specific: `manufacturing/temperature/read/v1/plant01/line03/machine07`.
**Source:** Topic Architecture Best Practices, Pattern 3 antipatterns.

## SAM antipatterns

### Agents skipping the orchestrator
**What's wrong:** Domain agents calling each other directly without OrchestratorAgent awareness for cross-domain tasks.
**What to do instead:** Use peer delegation through `PeerAgentTool`, which the OrchestratorAgent tracks. Direct agent-to-agent calls defeat workflow management and observability.
**Source:** Pattern 1 antipatterns.

### Hardcoded backend credentials in agent YAML
**What's wrong:** Embedding database passwords, API keys, or service account credentials directly in SAM agent configuration files.
**What to do instead:** Use the AuthorizationService and Micro-Integration credential management. Agent YAML should be safe to store in version control.
**Source:** Pattern 1 antipatterns.

### Environment names in SAM namespace
**What's wrong:** Using `{namespace}` values like `prod-banking` or `dev-assistant` that encode the deployment environment.
**What to do instead:** Use environment-separated deployments. The namespace identifies the logical domain, not the environment.
**Source:** Pattern 1 antipatterns.

### Synchronous request/response thinking for agent calls
**What's wrong:** Treating SAM agent invocations as blocking RPC calls. Designing architectures that assume synchronous responses from agents.
**What to do instead:** SAM is asynchronous and event-driven by design. Design for eventual responses, status updates, and failure handling that doesn't block the caller.
**Source:** Pattern 1 antipatterns.

### Using "Gateway" in user-facing Solace Architect output
**What's wrong:** Emitting the literal word "Gateway" in user-visible SA output (chat replies, generated documents, blueprints) when referring to the HTTP-facing SAM resource type. The project has renamed this concept to **Entrypoint** at the user-facing layer (see `naming-conventions.md`, Decision 74 in v2spec). "Gateway" remains the upstream SAM term and is the legitimate value in code identifiers, config keys (`type: gateway`), and Solace's own public documentation — but it should not appear in prose the user sees.
**What to do instead:** Use **Entrypoint** in user-facing prose. The plugin metadata enum and YAML config keys keep `gateway` literally — do not rename those. When citing the upstream SAM docs verbatim, the upstream wording can stand, but flag the dual-vocabulary explicitly so the user is not confused.
**Source:** Project-internal terminology decision (V2 spec Decision 74); cross-referenced in `naming-conventions.md` under the forbidden-terms list.

### Custom gateway when a standard one fits
**What's wrong:** Building a custom Gateway implementation when an existing Gateway type (HTTP SSE, REST, Slack, Teams) covers the channel.
**What to do instead:** Use the framework's built-in Gateways. Custom Gateways are appropriate only when the channel itself is novel, not for small protocol variations.
**Source:** Pattern 1 antipatterns.

## Mesh topology antipatterns

### Single global broker for the whole enterprise
**What's wrong:** Running one broker instance for all applications, sites, and environments.
**What to do instead:** Federate with DMR. Place brokers at scaling boundaries (per site, per region, per business domain). Single-broker topologies don't survive WAN partitions and concentrate risk.
**Source:** Pattern 3 antipatterns.

### Plant-floor systems calling cloud APIs synchronously
**What's wrong:** OT systems making direct synchronous REST/gRPC calls to cloud services for control or data submission.
**What to do instead:** Decouple via the event mesh. Publish events to the local edge broker. The mesh handles WAN transport, buffering during disconnection, and retry.
**Source:** Pattern 3 antipatterns.

### Treating the cloud apex as system of record for plant data
**What's wrong:** Designing the cloud as the authoritative source for plant-floor events.
**What to do instead:** The plant floor is the system of record for plant events. The cloud is a derived view. Architectures that invert this lose data when cloud connectivity drops and fail audits.
**Source:** Pattern 3 antipatterns.

### Symmetric high-volume bidirectional flows over DMR external links
**What's wrong:** Designing symmetric high-volume bidirectional flows with Guaranteed messaging over DMR external links without explicit per-direction traffic class design.
**What to do instead:** Make each direction's traffic class explicit. Asymmetric flows (e.g., US-to-Europe market data, Europe-to-US order routing) are the norm. Symmetric high-volume bidirectional is a design smell that warrants review of whether each direction truly requires external-link transport.
**Source:** Pattern 2 antipatterns.

## Delivery mode antipatterns

### Mixing Direct and Guaranteed on the same critical path
**What's wrong:** A subscriber bound to a queue (Guaranteed messaging) downstream of a Direct messaging publisher, expecting persistence.
**What to do instead:** Each leg's delivery mode must be designed explicitly. A queue subscription does not retroactively add persistence to an upstream Direct publisher. Design the full path: if the consumer needs Guaranteed, the publisher must also use Guaranteed on that topic.
**Source:** Pattern 2 antipatterns.

### Treating the mesh as request/response for fan-out data
**What's wrong:** Designing per-subscriber heartbeats, acknowledgments, or round trips for high-volume fan-out data like market data or telemetry.
**What to do instead:** Fan-out data is one-to-many by nature. Use Direct messaging with topic-based subscriptions. Per-subscriber interactions collapse under volume.
**Source:** Pattern 2 antipatterns.

## General integration antipatterns

### Bidirectional Kafka bridge on the same topic
**What's wrong:** Bridging events from Solace to Kafka and from Kafka back to Solace on the same topic or subject.
**What to do instead:** Pick one direction of authority per topic. Bidirectional bridging without explicit loop-prevention design produces infinite message loops.
**Source:** Pattern 3 antipatterns.

### Custom client library when a Solace API exists
**What's wrong:** Building a custom messaging client library when Solace publishes an API for that language (11 supported language APIs).
**What to do instead:** Use the published Solace API. The official APIs are tested at the volumes enterprise deployments demand. Custom clients introduce risk that compounds at scale.
**Source:** Pattern 2 antipatterns.

### Skipping Schema Registry for "simple" OT data
**What's wrong:** Assuming sensor/telemetry data is too simple to need schema management.
**What to do instead:** OT data evolves as sensors are added, replaced, or recalibrated. Without versioning discipline in Solace Schema Registry, downstream consumers break silently when event shapes change.
**Source:** Pattern 3 antipatterns.

### Deploying SAM without the event mesh foundation
**What's wrong:** Starting with SAM agents before establishing the underlying event mesh topology, topic taxonomy, and broker infrastructure.
**What to do instead:** The event mesh is the foundation. SAM is an extension. Build the mesh first, validate connectivity and delivery modes, then add the agent layer on top.
**Source:** Pattern 3 key design decisions (where SAM enters).

### Custom Micro-Integration when a cataloged path exists
**What's wrong:** Designing a custom Micro-Integration (Cloud Function, Lambda, Spring Boot app) for a backend system when a cataloged Micro-Integration already covers the path — either directly or through a well-known intermediate system. Example: building a custom GCS-to-Solace Cloud Function bridge when GCS natively sends events to Google Pub/Sub, and a Google Pub/Sub Source Micro-Integration exists in the Integration Hub.
**What to do instead:** Before designing any custom Micro-Integration, check the Integration Hub catalog for both direct and indirect paths. Many cloud services natively publish events to an intermediate system (Pub/Sub, SNS/SQS, Event Grid/Service Bus) that already has a cataloged Source Micro-Integration. Use the cataloged path. It is tested, maintained, and operationally simpler than custom code.
**Source:** Integration Hub catalog, "Common indirect paths" section.

### Cataloged Micro-Integration selected without behavioral fitness check
**What's wrong:** Matching a backend system to a cataloged Micro-Integration by name and direction, then treating the integration as solved without verifying that the MI's actual behavior satisfies the stated requirement. Example: selecting the Amazon S3 Producer MI for a file sync use case because it targets S3. The MI writes message payloads (notification metadata) as S3 objects via REST delivery points. It does not transfer file content. The catalog match ("Amazon S3" + "Target") is correct, but the behavior does not deliver file sync.
**What to do instead:** After matching a backend to a cataloged MI, state explicitly what the MI does with messages it processes: what it reads, writes, transforms, or delivers. Compare that behavior to the discovery brief's requirements for that integration point. If the MI's behavior does not satisfy the requirement, the MI is not the right integration even though it names the correct backend system. Either a different MI, a custom service, or additional components are needed. A catalog match is necessary but not sufficient.
**Source:** Audit finding, generalized. Applies to any MI selection where catalog name match does not imply behavioral fit.

## Operational antipatterns

### Queue depth explosion from slow consumers
**What's wrong:** Guaranteed messaging consumers that fall behind their production rate cause queue depth to grow unbounded. Broker message spool fills, triggering reject mode where new publishes are rejected across the entire message VPN.
**What to do instead:** Set max message spool quota per queue. Configure queue depth alerts in Solace Insights (warning at 50%, critical at 80%). Design horizontal consumer scaling (non-exclusive queues or partitioned queues) before production load. Monitor queue depth as a first-class operational metric.
**Source:** Operational best practice. Spool exhaustion is the most common production incident with Guaranteed messaging.

### Missing DMQ on production queues
**What's wrong:** Queues without a configured dead message queue (DMQ) silently discard messages that exceed max redelivery count or TTL. No alert, no recovery path. The message is gone.
**What to do instead:** Configure a DMQ for every production queue. Set a Solace Insights alert on DMQ depth > 0. Document a runbook for DMQ review: inspect failed messages, fix root cause, re-publish to original topic. DMQ is the safety net for poison messages.
**Source:** Operational best practice.

### Oversized messages without claim check pattern
**What's wrong:** Publishing messages with payloads near or above the broker's max message size (configurable, default 10 MB). Large payloads consume spool disproportionately and increase end-to-end latency.
**What to do instead:** Use the claim check pattern: store the large payload in external storage (S3, GCS, blob store), publish a lightweight notification message with a reference (URL, key) to the stored object. Consumers retrieve the payload from storage using the reference. Keep broker messages small (< 1 MB for best throughput).
**Source:** Architectural best practice. Applies to file transfer, media processing, and large document workflows.

### Direct messaging chosen where Guaranteed is required
**What's wrong:** Choosing Direct messaging for cost or simplicity when the use case requires lossless delivery. Direct messaging drops messages when there are no matching subscribers, when consumers are slow, or during brief disconnections. No spool, no retry, no recovery.
**What to do instead:** Use Guaranteed messaging when the business requires every message to arrive. Direct messaging is appropriate only when message loss is acceptable (telemetry sampling, real-time display updates, market data where the next tick replaces the previous). The delivery mode decision should trace to a stated business requirement, not a cost optimization.
