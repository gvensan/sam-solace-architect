# solace-architect-core

Shared library for the [Solace Architect V2 plugin family](https://github.com/solacecommunity/solace-agent-mesh-plugins). Every `solace-architect-*` SAM plugin declares this package as a dependency.

**Status:** scaffolding — Phase 0 of the [build plan](../documents/v2-build-plan.md). No working code yet.

## What's in here

- **`tools/`** — shared Python tools used across agents (artifact, decision, session, workflow, grounding, intake, validation, blueprint, project, dashboard, EP MCP wrappers). See [v2spec §3 + §5](../documents/v2spec.md).
- **`schemas/`** — Pydantic/dataclass models for the shared YAML schemas (open-items, projects, feedback, provisioned, decisions, findings).
- **`grounding/`** — vendored grounding docs (read-only reference + `jargon-list.json`) plus the writable `gaps.md` runtime gap tracker.
- **`configs/`** — default `branding.yaml`, `skill-routing.yaml`, `report-packs.yaml`. Consumers override via env vars or local overlays.

## Install (during development)

```bash
pip install -e .
```

## License

Apache 2.0.
