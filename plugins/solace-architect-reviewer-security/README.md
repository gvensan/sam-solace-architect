# solace-architect-reviewer-security

**SAM agent plugin** — `SASecurityReviewerAgent`. One of four reviewers in the Review phase; the Orchestrator fans out to all four in parallel after Design completes.

## Lens

Security-perspective review against a 5-criterion rubric:

1. **Authentication** — how do producers and consumers prove identity? Basic / Kerberos / client cert / OAuth — is the choice appropriate for each client class?
2. **ACL profiles** — least-privilege topic + queue ACLs, separation of pub vs sub, and clear identity-to-ACL-profile mapping.
3. **TLS** — is in-flight encryption required end-to-end? Are cert lifecycles + rotation thought through?
4. **Credential management** — where do tokens, passwords, and certs live? How are they rotated, scoped, and audited?
5. **Regulatory compliance** — PCI-DSS, SOC 2, GDPR, HIPAA — explicit posture for the data classifications the design carries.

Outputs a **Compliance Posture** subsection in the review narrative that maps the design's controls to whichever regulatory frame applies.

## Output

- `reviews/security-review.md` — narrative with **Strengths**, **Concerns**, **Compliance Posture**, and **Out-of-scope** sections.
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
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-reviewer-security
sam plugin add sa_reviewer_security --plugin solace-architect-reviewer-security
```

## License

Apache 2.0.
