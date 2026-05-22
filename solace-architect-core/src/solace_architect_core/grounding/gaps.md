# Grounding Document Gaps

When a skill can't find what it needs in the grounding documents, record the gap here. This helps prioritize grounding document updates.

Format:
```
- **Topic:** What was needed
  - Skill: /skill-name
  - Workaround: What the skill did instead
  - Date: YYYY-MM-DD
```

---

## Known gaps

### Platform Services (Layer 3) — highest impact

- **Solace Insights monitoring strategy:** Checked as present/absent but never designed. No skill specifies which of the 50+ pre-built monitors to enable, alert threshold values, custom monitors, log forwarding configuration, or integration with external observability platforms (Datadog, Grafana, etc.).
  - Skill: /solace-ops-review
  - Workaround: Ops review asks "Are Solace Insights configured?" and mentions Datadog export
  - Priority: High — monitoring is a production readiness requirement
  - Date: 2026-05-03

- **Event Mesh Visualizer:** Not mentioned anywhere in grounding docs or skills.
  - Skill: none
  - Workaround: None
  - Priority: Low
  - Date: 2026-05-03

### Application Services (Layer 2)

- **SDKPerf:** Official Solace performance testing tool not referenced. No skill recommends performance baseline testing or load validation methodology.
  - Skill: /solace-ops-review, /solace-validate
  - Workaround: None
  - Priority: Medium
  - Date: 2026-05-03

- **Kafka Connect (PubSub+ Connector) configuration:** Listed in Integration Hub catalog but no specific configuration guidance for Source/Sink connectors.
  - Skill: /solace-integration, /solace-migration
  - Workaround: Generic MI guidance applied
  - Priority: Medium
  - Date: 2026-05-03

### Event Mesh (Layer 1)

- **Sizing and capacity planning in skills:** ✓ RESOLVED (2026-05-22). Both halves shipped: broker-select computes a defensible `sizing:` block from the brief; ops-review extends rubric item 3 with 4 sub-checks AND emits `reviews/capacity-baselines.yaml` (throughput / latency / spool_alerts / connection_alerts) using the same sizing-block numbers.
  - Skill: /solace-broker-select (extended 2026-05-21) + /solace-ops-review (extended 2026-05-22)
  - Workaround → Done: SADomainAgent's broker-select scope prompt now has a "Per-scope methodology — broker-select" section that walks the agent through (1) computing connection count + peak event rate + avg message size + retention from the brief (intake form collects these as `requirements.retention_hours / event_rate_per_sec / avg_message_size_kb / admin_connections`; agent asks via `ask_user_question` only when still missing, never invents), (2) calculating spool size as msg_rate × size × retention, (3) classifying throughput qualitatively + citing the canonical service-class-comparison URL for tier verification, (4) recording the rationale via `record_decision`. The `broker-recommendation.yaml` now requires an explicit `sizing:` block with inputs/computed/recommendation sub-keys. SAOpsReviewerAgent's rubric item 3 now reads that sizing block, applies 4 sub-checks (throughput baseline, latency targets, spool/queue-depth alerts, connection-count alerts) using the same numbers as source of truth, and emits `reviews/capacity-baselines.yaml` as a machine-readable artifact for the ops side.
  - Priority: High
  - Phase: 3 done for both broker-select and ops-review
  - Date: 2026-04-29 (raised) / 2026-05-03 (updated) / 2026-05-21 (broker-select extended) / 2026-05-22 (ops-review extended)

- **Message VPN design guidance:** Platform reference documents VPNs thoroughly but no skill provides VPN design — how many VPNs, naming conventions, when to use multiple VPNs vs. multiple brokers, quota sizing per VPN, isolation boundaries.
  - Skill: /solace-broker-select, /solace-security-review
  - Workaround: None — VPN is assumed as a single default
  - Priority: High
  - Date: 2026-05-03

- **Topic Endpoints:** No guidance on when to use topic endpoints vs. queues. Platform reference defines them but no skill recommends or designs them.
  - Skill: /solace-topic-design
  - Workaround: All durable subscriptions default to queues
  - Priority: Medium
  - Date: 2026-05-03

- **Transactions (XA, local):** Platform reference now documents transaction types. No skill asks about transactional requirements or designs transaction boundaries.
  - Skill: /solace-discovery, /solace-architect-review
  - Workaround: Grounding available; skill extension needed (Phase 5)
  - Priority: Medium
  - Date: 2026-05-03

- **Queue configuration parameters:** No per-queue sizing recommendations — max spool, max redelivery, max TTL, reject-on-max-spool, partition count. Broker provisioning artifact is generic.
  - Skill: /solace-blueprint
  - Workaround: Default values assumed
  - Priority: Medium
  - Date: 2026-05-03

- **Priority messaging:** Platform reference now documents message priority (0-9). No skill asks about or designs priority-based message flows.
  - Skill: /solace-topic-design, /solace-protocol-select
  - Workaround: Grounding available; skill extension needed (Phase 5)
  - Priority: Low
  - Date: 2026-05-03

- **Message VPN Bridges:** Platform reference now documents bridge topology. No skill designs bridge topology between VPNs.
  - Skill: /solace-mesh-design
  - Workaround: Grounding available; skill extension needed (Phase 5)
  - Priority: Low
  - Date: 2026-05-03

- **Distributed Tracing / OpenTelemetry strategy:** Checklist item only — no tracing design. Which spans to capture, which backends to forward to, OpenTelemetry Collector with Solace receiver, context propagation patterns.
  - Skill: /solace-ops-review
  - Workaround: "Is Distributed Tracing configured?" question
  - Priority: Medium
  - Date: 2026-05-03

### Operational

- **Performance tuning:** No guidance on connection pooling, session management, publisher flow control, consumer prefetch, batching strategies.
  - Skill: /solace-ops-review, /solace-dev-review
  - Workaround: None
  - Priority: High
  - Phase: 3 (ops-review) and 4 (dev-review)
  - Date: 2026-05-03

- **Backup / restore:** Not addressed by any skill. No mention of broker configuration backup, spool backup, or disaster recovery procedures beyond replication.
  - Skill: /solace-ha-dr, /solace-ops-review
  - Workaround: DR replication covers data loss; configuration backup is missing
  - Priority: Medium
  - Date: 2026-05-03

- **Network architecture:** No skill addresses load balancer configuration, DNS failover, firewall rules for broker ports, or NAT traversal for DMR links.
  - Skill: /solace-mesh-design, /solace-ha-dr
  - Workaround: None
  - Priority: Medium
  - Date: 2026-05-03

- **Kubernetes Operator:** Platform reference expanded with Operator details, Helm chart config, and canonical URLs. No skill references the Operator for deployment design.
  - Skill: /solace-broker-select
  - Workaround: Grounding available; skill extension needed (Phase 3)
  - Priority: Medium
  - Date: 2026-05-03

- **Upgrade / patching procedures:** Asked about but no specific Solace upgrade path guidance (rolling upgrades, version compatibility, K8s Operator upgrade flows).
  - Skill: /solace-ops-review
  - Workaround: Generic "how are upgrades performed?" question
  - Priority: Medium
  - Date: 2026-05-03

### Integration Patterns

- **Request-reply topology:** Platform reference now documents request-reply patterns. No skill designs reply-to topics, temporary topics, correlation IDs, timeout handling.
  - Skill: /solace-protocol-select, /solace-topic-design
  - Workaround: Grounding available; skill extension needed (Phase 5)
  - Priority: Medium
  - Date: 2026-05-03

- **Event sourcing / CQRS:** Platform reference now documents event sourcing and CQRS patterns. No skill asks about or designs these patterns.
  - Skill: /solace-discovery, /solace-topic-design
  - Workaround: Grounding available; skill extension needed (Phase 5)
  - Priority: Low
  - Date: 2026-05-03

- **Saga / Choreography patterns:** Platform reference now documents saga and choreography patterns. No skill designs distributed transaction patterns using Solace topics and Guaranteed messaging.
  - Skill: /solace-discovery, /solace-integration
  - Workaround: Grounding available; skill extension needed (Phase 5)
  - Priority: Low
  - Date: 2026-05-03

## Resolved gaps

- **~~Event Portal integration workflow~~:** New `/solace-event-portal` skill created. 8-step template: application domains, event objects, schema attachments, applications, runtime connections, catalog organization, REST API provisioning. Produces `13-event-portal/` artifacts. All surrounding files updated: dependency map, plan orchestrator, help skill, CLAUDE.md, dashboard, settings, setup script.
  - Resolved: 2026-05-03 (Phase 2)

- **~~Eliding, Solace Cache/CacheInstance, shared subscriptions~~:** Added to platform reference as dedicated sections with descriptions, use cases, and configuration concepts. Canonical URLs added to solace-canonical-sources.md.
  - Resolved: 2026-05-03 (Phase 1)

- **~~Integration patterns (event sourcing, CQRS, saga, fan-out, request-reply)~~:** Added to platform reference as a new "Integration patterns" section with Solace-specific implementation guidance for each pattern.
  - Resolved: 2026-05-03 (Phase 1 — grounding docs; skill extensions pending Phase 5)

- **~~Performance and sizing methodology~~:** Added to platform reference with sizing dimensions, per-service-class limits, spool calculation, and tuning areas. Canonical URLs added for service class limits and SW broker system requirements.
  - Resolved: 2026-05-03 (Phase 1 — grounding docs; skill extensions pending Phase 3)

- **~~Kubernetes Operator expanded~~:** Platform reference expanded with Operator lifecycle, Helm chart configuration, scaling. Canonical URLs added for Operator docs and Helm chart.
  - Resolved: 2026-05-03 (Phase 1 — grounding docs; skill extension pending Phase 3)

- **~~Message VPN Bridges~~:** Added to platform reference with bridge types, use cases, and configuration scope. Canonical URL added.
  - Resolved: 2026-05-03 (Phase 1 — grounding docs; skill extension pending Phase 5)

- **~~Message Priority~~:** Added to platform reference with priority levels (0-9), delivery behavior, and use cases. Canonical URL already present.
  - Resolved: 2026-05-03 (Phase 1 — grounding docs; skill extension pending Phase 5)

- **~~Transactions (XA, local)~~:** Added to platform reference with local and XA transaction types, scope, and limitations. Canonical URL added.
  - Resolved: 2026-05-03 (Phase 1 — grounding docs; skill extension pending Phase 5)

- **~~HA/DR replication deep reference~~:** Added to platform reference. Three-node HA model, Config-Sync, mate links, client reconnection, DMR link types, Guaranteed messaging across DMR.
  - Resolved: 2026-04-30

- **~~Security and authentication deep references~~:** Added to platform reference and canonical sources. OAuth 2.0, Kerberos, LDAP, RADIUS, client certificates, CRL/OCSP, VPN isolation, SEMP security.
  - Resolved: 2026-04-30

- **~~Message VPN architecture~~:** Added to platform reference and canonical sources. Multi-tenancy, isolation, replication scope, DMR participation, per-VPN configuration.
  - Resolved: 2026-04-30

- **~~Partitioned queues, consumer groups, message replay~~:** Added to platform reference and canonical sources. Exclusive/non-exclusive queues, partitioned queues, DMQ configuration, message replay modes.
  - Resolved: 2026-04-30

- **~~REST Delivery Points (RDPs)~~:** Added to platform reference and canonical sources. RDP components, behavior, retry, relationship to Broker Integrated MIs.
  - Resolved: 2026-04-30

- **~~SEMP v2 for monitoring and management~~:** Added to platform reference. Config API, Monitor API, authentication, availability across broker types.
  - Resolved: 2026-04-30

- **~~Google ADK canonical URL~~:** URL present in solace-canonical-sources.md.
  - Resolved: 2026-04-30

- **~~Solace AI Connector (SAC) documentation URL~~:** URL present in solace-canonical-sources.md.
  - Resolved: 2026-04-30

- **~~MCP specification URL~~:** URL present in solace-canonical-sources.md.
  - Resolved: 2026-04-30

- **~~ask_user_question options parameter~~:** 2026-05-18 SADiscoveryAgent runtime-flagged: tool consistently returned `'options must be a list'` because ADK's schema extractor downgrades `Optional[list[dict]]` to `STRING`, so the LLM sent options as a JSON-encoded string.
  - Resolved: 2026-05-21 — `_coerce_options` in `interaction_tools.py` parses JSON-string options before validation; regression tests added in `tests/test_interaction_tools.py` (12 tests pin both shapes + the no-recommended-without-single_choice / dup-id / malformed-JSON edges).

---

## Next-up for v2 (queued, one-by-one review)

Order reflects priority × cost-to-fix (grounding already exists for items marked ✓ — just needs prompt extension, not new grounding authoring):

| # | Gap | Owner skill | Grounding present? | Notes |
|---|---|---|---|---|
| 1 | **Solace Insights monitoring strategy** | /solace-ops-review | ✓ (platform-reference) | Extend prompt to recommend specific monitors from the 50+, alert thresholds, Datadog/Grafana forwarding |
| 2 | **Message VPN design guidance** | /solace-broker-select, /solace-security-review | ✓ | Extend prompts with VPN-count guidance, naming conventions, multi-VPN-vs-multi-broker decision |
| 3 | **Performance tuning** | /solace-ops-review, /solace-dev-review | partial | Extend prompts with connection pooling, session mgmt, publisher flow control, consumer prefetch, batching |

Resolved while this table was open: **Sizing and capacity planning** (2026-05-22, both broker-select and ops-review extended).

The same pattern applies to most medium-priority items below — they're "extend the prompt to consult grounding that's already there" rather than "go author new grounding". Tackle one per review session.

## Out of scope (decided 2026-05-22)

The following gaps were explicitly de-scoped. Listed here for audit
trail so they aren't re-discovered and re-added to "Next-up" in a
future review pass. If priorities change, move the relevant entry
back to the active sections above (and add a dated rationale here).

- **Schema Registry design** — won't author a registry-design skill. Dev-reviewer's 5-sub-check rubric stays as-is; we will NOT add Phase 5 (validate fail-fast + design-phase schema authoring).
- **SEMP v2 for infrastructure-as-code** — won't extend prompts to recommend SEMP for CI/CD. Customers wanting IaC drive Solace via their own SEMP / Operator pipelines.
- **Solace Cloud Console workflows** — won't add Console-driven provisioning / team-role guidance. EP Designer MCP + the dashboard cover what the agents need.
- **Kerberos / LDAP / RADIUS authentication** — won't extend security-review with enterprise IdP guidance. OAuth + client-certificate auth already covered.
- **Rate limiting / connection limits** — won't add a per-VPN quota / client-profile rate-limit design strategy.
- **Client profile configuration generation** — won't generate concrete client-profile configs from security-review. Generic recommendation stands.

## Housekeeping (separate from grounding gaps)

- ~~**Stale skill-routing tests** — fixed 2026-05-21.~~ `tests/test_skill_routing.py::test_plan_bank_chat_sam_included_mesh_skipped`, `::test_plan_market_data_mesh_included_sam_skipped`, and `tests/test_tools.py::test_compute_intake_preview_matches_plan_shape` were updated to use the post-Path-A step names (`event-portal` for the opt-in live step, `event-portal-design` for the always-included design scope).