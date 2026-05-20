# Contributable plugin checklist

This is the **template** for taking any Solace Architect plugin from scaffold to PR-ready against `solacecommunity/solace-agent-mesh-plugins`. Captured from the `solace-architect-webui-entrypoint` pilot.

## SAM entrypoint plugin contract (verified against `cli-entrypoint`)

A SAM **entrypoint** plugin must provide:

1. **`pyproject.toml`** with:
   - `[tool.<package_name>.metadata] type = "gateway"` *(legacy metadata enum — the user-facing resource type is "entrypoint")*
   - dependencies on `solace-agent-mesh`, `solace-architect-core`, and any HTTP framework
2. **`config.yaml`** in the SAM `apps:` block format:
   ```yaml
   log: …
   shared_config:
     - broker_connection: &broker_connection { … }
     - services: { artifact_service: &default_artifact_service { … } }
   apps:
     - name: <plugin>_app
       app_module: <package>.app
       broker: { <<: *broker_connection }
       app_config:
         namespace: ${NAMESPACE}
         adapter_config: { … }      # plugin-specific
         default_agent_name: …
         authorization_service: { type: ${AUTH_TYPE, none} }
         …
   ```
3. **`src/<package>/app.py`** — module-level `info` dict + `BaseGatewayApp` subclass:
   ```python
   info = {"class_name": "MyPluginApp", "description": "…"}
   class MyPluginApp(BaseGatewayApp):
       SPECIFIC_APP_SCHEMA_PARAMS = [{"name": "adapter_config", …}, …]
       def __init__(self, app_info, **kwargs): super().__init__(app_info=app_info, **kwargs)
       def _get_gateway_component_class(self): return MyPluginComponent
   ```
4. **`src/<package>/component.py`** — `BaseGatewayComponent` subclass implementing the 7 hooks:
   - `_extract_initial_claims(external_event_data)` — return user claims dict
   - `_start_listener()` — start your transport (HTTP server, WebSocket, REPL, …)
   - `_stop_listener()` — clean shutdown
   - `_translate_external_input(external_event)` → `(target_agent, [A2APart], context)`
   - `_send_update_to_external(context, event, is_final)`
   - `_send_final_response_to_external(context, task)`
   - `_send_error_to_external(context, error)`

## SAM agent plugin contract (TODO — verify against an existing agent plugin)

The 10 agent plugins likely follow a different but parallel pattern. Verify against `tavily/` or another agent plugin in the community repo before refactoring.

Expected structure (extrapolated from `tavily/pyproject.toml` + community convention):
- `[tool.<package>.metadata] type = "agent"`
- `config.yaml` with a single agent definition under an `apps:` block
- `src/<package>/app.py` exporting the `Agent` class
- System prompt in `config.yaml.app_config.system_prompt`
- Tools wired in `config.yaml.app_config.tools`

## Per-plugin checklist

For each plugin in `plugins/`, complete every box before opening a PR.

### 1. Code structure
- [ ] `pyproject.toml` — name + version + `[tool.<package>.metadata] type` + dependencies on `solace-architect-core` and `solace-agent-mesh`
- [ ] `pyproject.toml` — `[project.optional-dependencies] test = [...]` for test extras
- [ ] `pyproject.toml` — `force-include` adds `config.yaml` + `README.md` + `pyproject.toml` to the wheel (does NOT duplicate the src package — that breaks editable installs)
- [ ] `config.yaml` — SAM `apps:` block (matches `cli-entrypoint` / `tavily` shape)
- [ ] `src/<package>/app.py` — exports `info` dict + `App` class inheriting the right `Base*App`
- [ ] `src/<package>/component.py` (entrypoints only) — `Component` class inheriting `BaseGatewayComponent` with 7 hooks
- [ ] System prompt fully ported from V1 (for agent plugins) — check token budget stays under 40K

### 2. Tests
- [ ] `tests/` directory with at least 3 test files (module/discovery, lifecycle/handlers, static-shipping if applicable)
- [ ] `pytest.ini` with `asyncio_mode = auto`
- [ ] Tests pass: `cd plugins/<name> && pytest -v` returns green
- [ ] Tests that depend on SAM use `pytest.importorskip("solace_agent_mesh…")` so they pass on bare CI

### 3. CI
- [ ] `.github/workflows/plugin-<name>.yml` exists with:
  - Path-scoped triggers (`paths: ['plugins/<name>/**', 'solace-architect-core/**']`)
  - Test job (matrix on Python 3.11 / 3.12)
  - Build job that produces a wheel artifact

### 4. README
Compare against `tavily/README.md` and `cli-entrypoint/README.md`. Required sections:
- [ ] One-line description + CI badge
- [ ] **What it does** — concrete capability list
- [ ] **Install** — both registry path and editable dev path
- [ ] **Configure** — env vars table with defaults
- [ ] **Run** — minimum `sam run` example
- [ ] **Example** — one curl / interaction snippet
- [ ] **Testing** — how to run the plugin's tests
- [ ] **Troubleshooting** — at least 5 known issues
- [ ] **License + Related plugins** — links to siblings

### 5. Wheel build
- [ ] `python -m build` from the plugin dir succeeds
- [ ] Inspect `dist/*.whl` with `unzip -l` — confirm every file under `src/<package>/` plus `config.yaml`, `README.md`, `pyproject.toml` is shipped
- [ ] Wheel size is sane (typically 30–200 KB for an agent plugin; up to ~500 KB for the WebUI entrypoint with its static assets)

### 6. End-to-end verification (requires SAM + broker + LLM key)
- [ ] `sam run plugins/<name>/config.yaml` starts cleanly
- [ ] The plugin's agent / entrypoint appears in `sam agent list` (or equivalent)
- [ ] Triggering the agent through whatever surface (WebUI / curl / chat) produces a non-error response
- [ ] For agents: bank chat fixture (`test-harness/fixtures/bank_chat_agent.yaml`) flows through and produces the expected artifact(s)

### 7. Documentation cross-references
- [ ] `documents/v2spec.md` — plugin is mentioned in §1 (project tree), §4 (agent specs), §10 (distribution model)
- [ ] `documents/v2-build-plan.md` — phase column updated if work shifted phases

### 8. Pre-PR sanity
- [ ] No `TODO` or `FIXME` markers in shipped files (move to issue tracker)
- [ ] No hardcoded paths to `/Users/<your-name>/…`
- [ ] License header in source files matches community convention
- [ ] `python -m pytest` from repo root still passes (other plugins not broken)

## PR workflow (against `solacecommunity/solace-agent-mesh-plugins`)

1. Fork the community repo if you haven't already
2. Create a branch named `add-<plugin>` from `main`
3. Copy your plugin folder (`plugins/<name>/`) into the fork's root
4. Update the community repo's `README.md` "Available Plugins" table — add your plugin's row
5. `git push` and open a PR with:
   - Title: `Add <plugin> — <one-line summary>`
   - Body: link to your plugin's README + screenshot / asciicast if relevant
   - Confirm against this checklist
6. Address review feedback, iterate, merge

## Order of plugin contributions (recommended)

Don't open 11 PRs at once. Sequence:

1. **`solace-architect-webui-entrypoint`** (this pilot — proves the SAM contract works)
2. **`solace-architect-orchestrator`** (the conductor — once this works, others become testable)
3. **`solace-architect-discovery`** + **`solace-architect-domain`** (vertical slice)
4. **`solace-architect-blueprint`** (output side of the vertical slice)
5. **4 reviewer plugins** (open as a batch — same template)
6. **`solace-architect-validation`**
7. **`solace-architect-ep-provisioning`** (opt-in; needs EP MCP — last)

Each PR depends on the previous ones being installable, so wait for merges (or use a `--plugin-source path` workaround for parallel review).

## What's intentionally NOT in this checklist

- **Type hints / mypy** — community repo doesn't require strict typing; do it if it helps you
- **100% test coverage** — aim for the contract surface, not coverage metrics
- **i18n** — Phase 2+ concern
- **Telemetry** — covered by SAM's runtime instrumentation
