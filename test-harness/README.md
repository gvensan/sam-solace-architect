# Test harness

Local SAM project for end-to-end testing the Solace Architect plugin family. **Not distributed.**

## Setup

```bash
# 1. Install core library
pip install -e ../solace-architect-core/

# 2. Install plugins editable
for p in orchestrator discovery domain reviewer-architect reviewer-developer \
         reviewer-ops reviewer-security validation blueprint webui-entrypoint; do
  pip install -e "../plugins/solace-architect-${p}/"
done

# 3. Optional: provisioning plugin (requires EP Designer MCP)
# pip install -e ../plugins/solace-architect-ep-provisioning/

# 4. Configure env
cp .env.example .env
# Edit .env: NAMESPACE, SOLACE_BROKER_*, model API key

# 5. Run
sam run
```

## End-to-end smoke test

```bash
curl -X POST http://localhost:8080/api/engagements \
  -H "Content-Type: application/json" \
  -d @fixtures/bank_chat_agent.yaml
```

## Fixtures

- `fixtures/bank_chat_agent.yaml` — Pattern 1: multi-system AI assistant (retail banking)
- `fixtures/market_data_distribution.yaml` — Pattern 2: real-time market data (multi-site DMR)
- `fixtures/hybrid_it_ot.yaml` — Pattern 3: hybrid IT/OT manufacturing (migration + OT)
