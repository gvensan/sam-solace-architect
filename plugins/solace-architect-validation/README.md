# solace-architect-validation

**SAM agent plugin** — `SAValidationAgent`. The gating step between Review and Blueprint. Decides whether the engagement is ready to assemble — DONE / DONE_WITH_CONCERNS / BLOCKED.

## What it checks

6-criterion validation rubric, all evidence-traced into the report:

1. **Requirement coverage** — every requirement from the discovery brief is mapped to at least one decision or artifact; gaps surface as blocking open-items.
2. **Antipattern scan** — matches the design against the grounding corpus of known Solace antipatterns (e.g. one-queue-per-consumer, schema versions baked into topics, broker-as-store, etc.).
3. **Consistency** — taxonomy ↔ ACL profile ↔ protocol-choice alignment, naming consistency across scopes, decision/finding cross-references resolve.
4. **Deferred findings** — every review finding has been applied, deferred (with justification), or dismissed; nothing left dangling.
5. **Terminology compliance** — uses the canonical Solace + Solace Architect terms (see `solace_architect_core/grounding/jargon-list.json`).
6. **Schema sanity** — every YAML artifact parses, required fields present, no orphan references.

## Output

- `validation/validation-report.md` — narrative organized by criterion with a per-artifact notation column (80-char limit).
- `validation/validation-report.yaml` — machine-readable: requirements traceability matrix, antipattern matches, consistency issues, schema warnings.
- `step_status` for `step="validation"` — DONE (proceed), DONE_WITH_CONCERNS (proceed but flag), or BLOCKED (Blueprint cannot run).

Uses `trace_requirements` from `solace_architect_core.tools.validation_tools` to build the matrix.

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
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-validation
sam plugin add sa_validation --plugin solace-architect-validation
```

## License

Apache 2.0.
