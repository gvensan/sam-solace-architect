# Default configs

Shipped with `solace-architect-core`. Consumers (the 11 plugins) read these defaults but can override via env vars or local overlays.

**Phase 0:** empty. **Phase 1:** populate.

Files to add in Phase 1:
- `branding.yaml` — colors, fonts, logo, version label (v2spec §5.5)
- `skill-routing.yaml` — conditional design-scope inclusion (v2spec §5.1, ~80 lines)
- `report-packs.yaml` — per-audience filter rules (v2spec §5.5a, ~170 lines)
