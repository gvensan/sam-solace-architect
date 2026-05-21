# solace-architect-reviewer-ops

**SAM agent plugin** — `SAOpsReviewerAgent`. One of four reviewers in the Review phase; the Orchestrator fans out to all four in parallel after Design completes.

## Lens

Operations-perspective review against a 5-criterion rubric:

1. **Monitoring** — what metrics + dashboards reveal that the system is healthy or degrading? Are SLOs explicit?
2. **Failure modes** — which broker / network / consumer failures are accounted for? What happens to in-flight messages during failover?
3. **Capacity planning** — message rate, fan-out, queue depth limits — what does the design assume, and where does it break?
4. **Operational procedures** — runbooks for queue backlog, message redelivery, DLQ inspection, schema-version mismatch, broker rolling restart.
5. **Alerting** — what fires a page vs a ticket vs a log entry? Are the alerts noisy or actionable?

## Output

- `reviews/ops-review.md` — narrative with **Strengths**, **Concerns**, and **Out-of-scope** sections.
- Findings recorded via `record_finding` with severity (critical / important / advisory) and a recommendation.

The Orchestrator aggregates all 4 reviewers' findings into the Review Findings table; user decisions (apply / defer / dismiss) flow back to the Design agents.

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
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-reviewer-ops
sam plugin add sa_reviewer_ops --plugin solace-architect-reviewer-ops
```

## License

Apache 2.0.
