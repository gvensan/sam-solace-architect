# solace-architect-reviewer-developer

**SAM agent plugin** — `SADeveloperReviewerAgent`. One of four reviewers in the Review phase; the Orchestrator fans out to all four in parallel after Design completes.

## Lens

Developer-perspective review against a 5-criterion rubric:

1. **Topic usability** — can a new developer guess the right topic to publish/subscribe to, or do they have to read the spec every time?
2. **SDK / API choice** — is the protocol + client pattern the right ergonomic fit for the language and skill level of the consuming teams?
3. **Schema governance** — are schemas versioned, namespaced, and discoverable? How does a producer ship a breaking change without breaking everyone?
4. **Error handling** — what does a consumer do when a message is malformed, the broker is unreachable, or the downstream system rejects it?
5. **Onboarding path** — what does the first hour look like for a new team integrating against this design? Sample code, local dev story, copy-pasteable connection snippet?

## Output

- `reviews/developer-review.md` — narrative with **Strengths**, **Concerns**, and **Out-of-scope** sections.
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
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-reviewer-developer
sam plugin add sa_reviewer_developer --plugin solace-architect-reviewer-developer
```

## License

Apache 2.0.
