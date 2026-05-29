# LLM Gateway Requests — `lite-llm.mymaas.net`

Hand-off note for the MaaS / gateway team. Three asks, ranked by impact, each
with the concrete evidence from Solace Architect's telemetry and logs. None
require application changes on our side — they are gateway/upstream capabilities.

**Deployment under test:** model alias `openai/vertex-claude-4-5-sonnet`, served
via `https://lite-llm.mymaas.net` (OpenAI-compatible `/chat/completions`),
backed by Claude 4.5 Sonnet on Vertex.

---

## 1. Enable / forward prompt caching (highest impact)

**Ask:** Does the proxy forward Anthropic `cache_control` markers through to the
Vertex Claude backend, and is prompt caching enabled on that deployment? If the
OpenAI-format hop strips them, can caching be enabled proxy-side (e.g. LiteLLM
`cache_control_injection_points`) for this model?

**Why it matters (evidence):**
- The client (SAM) **already sends** `cache_control: {type: ephemeral}` on the
  system prompt and the last tool (5-minute strategy, default) and orders tools
  deterministically to keep the cache prefix stable.
- Yet telemetry shows **`cached_input_tokens = 0` across 470 LLM calls** in a
  single engagement — caching is never taking effect.
- Cost/latency profile of that engagement: **13.9M input tokens vs 187K output
  (~74:1)**, **~30K input tokens/call average** (max ~69K). The work is almost
  entirely *prefill* of the same system prompt + grounding + brief, re-sent
  uncached on every call.
- Likely cause: the `openai/`-format request path doesn't carry Anthropic
  `cache_control` to the backend (OpenAI's schema has no such field).

**Expected benefit:** a 60–80% cache hit on the stable prefix would cut prefill
latency and input cost by roughly that proportion, and **shorten time-on-wire**,
which directly reduces the ReadTimeout exposure in ask #3.

---

## 2. Reviewer concurrency — per-key cap or per-reviewer keys

**Ask:** Either raise the per-key concurrency cap to ~6, or issue per-agent API
keys, so the four review agents can run concurrently.

**Why it matters (evidence):**
- The orchestrator currently dispatches the 4 reviewers **strictly serially**
  because a prior parallel fan-out returned **all 4 BLOCKED** — the proxy's
  per-key concurrency cap rejected the burst.
- All agents share one `LLM_SERVICE_API_KEY`, so 4 concurrent reviewer streams
  collide on that cap.
- Impact: review wall-clock is **~10–20 min serial**; with concurrency it drops
  to roughly one reviewer's duration (~3–5 min).

---

## 3. Mid-stream `ReadTimeout` reliability

**Ask:** Investigate gateway/upstream stream stability — intermittent mid-stream
stalls that surface as `httpx.ReadTimeout`.

**Why it matters (evidence):**
- This session alone, ReadTimeouts failed whole phases: **Discovery**,
  **Validation** (also hit the per-task LLM-call cap while retrying), and
  **Event Portal provisioning** all terminated with `Exception: ReadTimeout`.
- Client-side mitigations already in place (request `timeout=30`,
  `num_retries=3`, stream-drop re-dispatch, fast-path kickoffs) **cannot beat a
  gateway that drops the stream** — they only reduce the blast radius.

---

## Note (separate, same provider family?)

The Codex CLI against `chatgpt.com/backend-api/codex` returned **`402 Payment
Required: {"code":"deactivated_workspace"}`**. Unrelated to the items above, but
flagging in case it's the same billing/workspace administration.
