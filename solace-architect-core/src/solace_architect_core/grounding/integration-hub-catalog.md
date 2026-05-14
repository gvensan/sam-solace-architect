# Integration Hub Catalog

Snapshot of available Micro-Integrations, integration guides, and agents from the [Solace Integration Hub](https://solace.com/integration-hub/). Skills use this catalog to match user-identified backend systems against available Micro-Integrations without requiring a live fetch.

**Last refreshed:** 2026-04-29

---

## How skills use this catalog

1. During `/solace-discovery`: when the user names a backend system, check this catalog for a matching Micro-Integration. If found, note it in the discovery brief.
2. During `/solace-integration`: use this catalog as the starting inventory. For each backend, classify as "cataloged MI available," "custom MI needed," or "integration guide available."
3. During `/solace-validate`: verify that every backend in the architecture has either a cataloged Micro-Integration or a documented custom one.

If a system is not in this catalog, it does not mean no Micro-Integration exists — the catalog may be stale. Direct the user to check `solace.com/integration-hub` for the latest availability.

---

## Cloud platform integrations

### Amazon Web Services (AWS)

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Amazon S3 | Source | Cloud-Managed, Self-Managed | File/object events into Solace |
| Amazon S3 Producer | Target | Broker Integrated | Events from Solace to S3 via REST delivery points |
| Amazon SQS | Source, Target | Broker Integrated, Cloud-Managed, Self-Managed | Bridges Solace and SQS queues |
| Amazon SNS | Target | Broker Integrated, Cloud-Managed, Self-Managed | Publish events to SNS topics |
| Amazon Kinesis Data Streams | Source, Target | Self-Managed | Kinesis clients as event mesh participants |
| Amazon MSK | Source, Target | Broker Integrated | Managed Kafka via integrated Kafka bridge |
| AWS Lambda Producer | Target | Broker Integrated | Trigger Lambda functions from broker events |

### Google Cloud Platform (GCP)

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Google Pub/Sub | Source, Target | Cloud-Managed, Self-Managed | Bridge between Solace and GCP Pub/Sub |
| Google Cloud Storage Producer | Target | Broker Integrated | Events to GCS via REST delivery points |
| Google Cloud Functions Producer | Target | Broker Integrated | Trigger Cloud Functions from broker events |
| Google Cloud Run Producer | Target | Broker Integrated | Trigger Cloud Run from broker events |
| Google Cloud Bigtable | Target | Community | Via GCP Cloud Functions |

### Microsoft Azure

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Azure Event Hubs Producer | Target | Broker Integrated | Events to Azure Event Hubs |
| Azure Service Bus | Source, Target | Self-Managed | Bridge between Solace and Azure Service Bus |
| Azure Functions Consumer | Source | Broker Integrated | Consume events via Azure Functions |
| Azure Functions Producer | Target | Broker Integrated | Trigger Azure Functions from broker events |
| Azure Data Lake Storage (Gen 2) | Target | Broker Integrated | Store events in ADLS via REST delivery points |

---

## Database and data storage

### Change Data Capture (CDC)

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| PostgreSQL CDC | Source | Cloud-Managed, Self-Managed | Event-enable PostgreSQL databases |
| MySQL CDC | Source | Cloud-Managed, Self-Managed | Event-enable MySQL databases |
| Oracle CDC | Source | Self-Managed | Event-enable Oracle databases |
| IBM DB2 CDC | Source | Self-Managed | Event-enable DB2 databases |
| MongoDB CDC | Source | Self-Managed | Event-enable MongoDB via change streams |
| Debezium (CDC): MySQL | Source | Self-Managed | MySQL CDC via Debezium |

### General database

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Databases (JPA) | Source, Target | Self-Managed | 2-way integration via Java Persistence API; supports many RDBMS |
| Couchbase | Source, Target | Self-Managed | 2-way integration via database change protocol (DCP) |
| Snowflake | Target | Cloud-Managed, Self-Managed | Via Snowpipe Streaming API or Snowpipe API with stages |
| Oracle Advanced Queuing (AQ) | Source, Target | Self-Managed | Bridge with Oracle AQ |
| Oracle Golden Gate | Source | Self-Managed | CDC via Oracle GoldenGate |
| Gluesync | Source | Community | Multi-source streaming: SQL Server, PostgreSQL, MariaDB, MySQL, MongoDB, Couchbase |
| Qdrant (Beta) | Target | Cloud-Managed | Vector database for AI/RAG workloads |

---

## Messaging and eventing

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Apache Kafka (Integrated) | Source, Target | Broker Integrated | Built-in Kafka bridge in broker 10.6.1+ |
| Aiven Managed Apache Kafka | Source, Target | Broker Integrated | Aiven-hosted Kafka via integrated bridge |
| Confluent | Source, Target | Broker Integrated | Confluent Platform via integrated Kafka bridge |
| Kafka Connect Source | Source | Self-Managed | Solace as Kafka Connect source connector |
| Kafka Connect Sink | Target | Self-Managed | Solace as Kafka Connect sink connector |
| IBM MQ | Source, Target | Self-Managed | Bridge between Solace and IBM MQ |
| JMS | Source, Target | Self-Managed | Generic JMS integration |
| TIBCO EMS | Source, Target | Self-Managed | Bridge between Solace and TIBCO EMS |
| NATS | Source, Target | Self-Managed | Bridge between Solace and NATS |
| MQTT | Source, Target | Self-Managed | Bridge with external MQTT brokers |
| Google Pub/Sub | Source, Target | Cloud-Managed, Self-Managed | (also listed under GCP) |

---

## Integration platforms

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Apigee | Source, Target | Cloud-Managed, Self-Managed | API management integration |
| Boomi Integration | Source, Target | Self-Managed | Boomi iPaaS connector (Dell Technologies) |
| MuleSoft Anypoint Platform | Source, Target | Self-Managed | Certified MuleSoft connector; available in Anypoint Exchange |
| SAP Integration Suite | Source, Target | Self-Managed | SAP IS connects to Solace queues and topics |

---

## Analytics and stream processing

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Apache Spark | Source, Target | Self-Managed | Via Spark DataSource V2 API |
| Apama Producer | Source | Community | Software AG Apama CEP integration |

---

## IoT and industrial

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| OPC UA | Source, Target | Self-Managed | Industrial OPC UA protocol bridge |
| MQTT | Source, Target | Self-Managed | (also listed under messaging) |

---

## Files and storage

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| File Events | Source, Target | Self-Managed | Turn file data into events or events into files |
| SFTP | Source, Target | Self-Managed | SFTP file transfer integration |

---

## CRM and SaaS

| Micro-Integration | Direction | Platform | Notes |
|---|---|---|---|
| Salesforce | Source, Target | Self-Managed | 2-way via Salesforce Pub/Sub gRPC API |

---

## AI and agents

| Asset | Type | Platform | Notes |
|---|---|---|---|
| Solace AI Connector (SAC) | Open-source framework | Self-Managed | Python-based; connects Solace brokers to AI models and services. Runtime for SAM agents and gateways. |
| Standalone LLM Agent (Beta) | Agent | Self-Managed | Pre-built LLM agent |
| Standalone RAG Agent (Beta) | Agent | Self-Managed | Pre-built RAG agent |

---

## Developer tools

| Asset | Type | Notes |
|---|---|---|
| Solace Messaging APIs | SDK | Client libraries for Java, JavaScript, Python, Go, C, C#, iOS, and more |

---

## Platform types explained

| Platform | Meaning |
|---|---|
| **Broker Integrated** | Built into the event broker itself (e.g., Kafka bridge, REST delivery points). No separate runtime needed. |
| **Cloud-Managed** | Deployed and managed within Solace Cloud console. Click-to-create. |
| **Self-Managed** | User deploys and manages the Micro-Integration runtime (typically Spring Boot or SAC-based). |
| **Community** | Community-contributed; not officially supported by Solace. |

---

## Common indirect paths

Some systems do not have a direct Solace Micro-Integration but can reach the event
broker through an intermediate system that does. Check these paths before concluding
a custom Micro-Integration is needed.

| Source System | Intermediate System | Cataloged MI Used | Path Description |
|---|---|---|---|
| Google Cloud Storage (GCS) | Google Pub/Sub | Google Pub/Sub Source MI | GCS natively sends object change notifications to Pub/Sub. The Google Pub/Sub Source MI ingests those events into Solace. No custom code needed. |
| AWS CloudWatch | Amazon SNS / Amazon SQS | Amazon SQS Source MI | CloudWatch alarms publish to SNS, which fans out to SQS. The Amazon SQS Source MI ingests from SQS into Solace. |
| Webhook-capable systems | Solace REST ingest | (none — broker-native REST) | Systems that emit webhooks can POST directly to the broker's REST messaging endpoint. No Micro-Integration needed if REST delivery points are configured. |
| Azure Blob Storage | Azure Event Grid / Azure Service Bus | Azure Service Bus Source MI | Blob Storage emits events to Event Grid, which routes to Service Bus. The Azure Service Bus Source MI ingests into Solace. |

**How to use this table:** When `/solace-discovery` or `/solace-integration` finds a
backend with no direct MI, check whether that backend natively publishes events to one
of the intermediate systems listed above. If it does, the cataloged MI for the intermediate
system provides the inbound path. Only classify as "custom needed" after confirming no
indirect path exists.

---

## Update discipline

This catalog is a point-in-time snapshot. Solace adds new Micro-Integrations regularly. To keep it current:

1. Run `bun run url:check` monthly to verify Integration Hub is reachable.
2. Before any `/solace-integration` engagement, check `solace.com/integration-hub` for new entries.
3. When a skill finds a system not in this catalog but a Micro-Integration exists, add it here and note the date.
4. When a Micro-Integration is retired or renamed, update this catalog.
