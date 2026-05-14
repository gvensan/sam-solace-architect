# sam-solace-architect

Solace Architect V2 — a family of [Solace Agent Mesh (SAM)](https://github.com/SolaceLabs/solace-agent-mesh) plugins that guide architects from a business problem to a deployable event-driven architecture blueprint on Solace.

**This repo is the development monorepo.** Plugins are distributed individually via the [Solace community plugins registry](https://github.com/solacecommunity/solace-agent-mesh-plugins); the shared library is distributed via PyPI.

## Layout

```
sam-solace-architect/
├── documents/                           # The spec, gap analysis, build plan
├── solace-architect-core/               # Shared PyPI library (tools, schemas, grounding, configs)
├── plugins/                             # 11 SAM plugin sources (10 agents + 1 entrypoint)
│   ├── solace-architect-orchestrator/
│   ├── solace-architect-discovery/
│   ├── solace-architect-domain/
│   ├── solace-architect-reviewer-architect/
│   ├── solace-architect-reviewer-developer/
│   ├── solace-architect-reviewer-ops/
│   ├── solace-architect-reviewer-security/
│   ├── solace-architect-validation/
│   ├── solace-architect-blueprint/
│   ├── solace-architect-provisioning/   # opt-in
│   └── solace-architect-webui-entrypoint/
├── test-harness/                        # Local SAM project for end-to-end testing (not distributed)
└── tests/                               # Cross-plugin integration tests
```

## Documents

| File | Purpose |
|------|---------|
| [`documents/v2spec.md`](documents/v2spec.md) | Complete design spec (single source of truth) |
| [`documents/v1-v2-gap-analysis.md`](documents/v1-v2-gap-analysis.md) | V1 → V2 feature parity audit |
| [`documents/v2-build-plan.md`](documents/v2-build-plan.md) | Phased build plan (Phase 0 → Phase 7) |

## Quick start (development)

```bash
# 1. Install the shared core library
pip install -e ./solace-architect-core/

# 2. Install plugins (editable, for live code-iteration)
for p in orchestrator discovery domain reviewer-architect reviewer-developer \
         reviewer-ops reviewer-security validation blueprint webui-entrypoint; do
  pip install -e "./plugins/solace-architect-${p}/"
done

# 3. Run from the test harness
cd test-harness/
cp .env.example .env  # then edit
sam run
```

## Contribution flow

Each plugin is independently versionable and contributable:

1. Edit a plugin under `plugins/<name>/`
2. Bump its `version` in `pyproject.toml`
3. Test locally via `test-harness/` (editable install reflects changes immediately)
4. Open a PR to [`solacecommunity/solace-agent-mesh-plugins`](https://github.com/solacecommunity/solace-agent-mesh-plugins) with the plugin's folder

`solace-architect-core` releases independently to PyPI.

## Status

**Phase 0 — Scaffolding complete.** Phases 1–6 in progress per [`documents/v2-build-plan.md`](documents/v2-build-plan.md).

## License

Apache 2.0.
