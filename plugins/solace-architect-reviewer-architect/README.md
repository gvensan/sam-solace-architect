# solace-architect-reviewer-architect

**SAM agent plugin** — `SAArchitectReviewerAgent`. One of four reviewers in the Review phase; the Orchestrator fans out to all four in parallel after Design completes.

## Lens

Architecture-perspective review against a 5-criterion rubric:

1. **Component fit** — does each chosen Solace component (PubSub+, DMR, Event Portal, MI) actually solve the requirement, or is it being misused?
2. **Simpler alternatives** — was a heavier choice picked where a simpler one (e.g. single broker vs DMR mesh) would do?
3. **Trade-off framing** — are the recorded decisions honest about what was given up, or do they only list upsides?
4. **Pattern alignment** — does the design follow the reference architecture picked in Discovery, or did it drift?
5. **Cross-cutting concerns** — naming consistency, taxonomy coherence, integration boundary clarity.

## Output

- `reviews/architect-review.md` — narrative with **Strengths**, **Concerns**, and **Out-of-scope** sections.
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
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-reviewer-architect
sam plugin add sa_reviewer_architect --plugin solace-architect-reviewer-architect
```

## License

Apache 2.0.
