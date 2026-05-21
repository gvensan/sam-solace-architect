# solace-architect-blueprint

**SAM agent plugin** — `SABlueprintAgent`. The last assembly step before opt-in Provisioning. Turns every prior phase's artifacts into a finished blueprint plus five audience-targeted HTML/PDF reports and a single zipped engagement bundle.

## What it produces

| Path | Contents |
|---|---|
| `blueprint/architecture.md` | Architecture narrative — recommended design, decision rationale, cross-references to Discovery/Design/Review artifacts. Written one section per turn to stay under the per-call size budget. |
| `blueprint/runbook.md` | Ops runbook — startup/shutdown, capacity tuning, backlog handling, DR cutover, schema-version rollout. Multi-section, also paced one section per turn. |
| `blueprint/diagrams/*.mermaid` | Final architecture, topology, mesh, HA/DR, and integration diagrams. Pre-rendered to SVG via `mmdc` for PDF output (HTML stays Mermaid for runtime zoom). |
| `blueprint/packs/<audience>.{html,pdf}` | One file per audience pack — Blueprint / Executive / Admin & Ops / Security / Developers. HTML is self-contained (CSS + JS inline, fonts from CDN). PDF via WeasyPrint. |
| `exports/engagement-package.zip` | Single archive of everything above plus all Discovery / Design / Review / Validation artifacts — what you hand to the customer. |

## Audience packs

Each pack is a filtered view over the same underlying decisions + findings + artifacts. Filters live in `solace_architect_core/configs/report-packs.yaml`:

| Pack | Lens | Distinctive content |
|---|---|---|
| **Blueprint** | Comprehensive engineering deliverable | All decisions, all findings, all artifacts |
| **Executive** | Business case + ROI | Interactive ROI calculator (5 sensitivity sliders + combined scenario card, Excel export via SheetJS) |
| **Admin & Ops** | Provisioning + monitoring + runbooks | Operational depth, no business case |
| **Security** | Auth, ACLs, encryption, audit, PII | Compliance posture front-and-center |
| **Developers** | Topics, schemas, protocols, client patterns | Build-correct-clients focus |

The HTML renderer (in `src/solace_architect_blueprint/report_generator/`) is a full V1-parity port: page header + stats strip, sticky toolbar (theme/print/download), sidebar TOC nested by phase bucket, auto-narrative (architect-voice summary built from decisions + findings + status), per-artifact sections with markdown→HTML or mermaid→SVG bodies, plus the ROI calculator on the Executive pack.

## Pacing + size budget

Section-by-section writes — one section per turn, ~1500 words / 8KB per `write_artifact` call. Splits long sections (architecture, runbook) into ordered sub-files plus a short TOC stub so a tool-call JSON truncation can't blow up the whole document.

## Required env vars

| Variable | Purpose |
|---|---|
| `NAMESPACE` | A2A topic namespace. |
| `SOLACE_BROKER_URL` / `_USERNAME` / `_PASSWORD` / `_VPN` | Broker client credentials. |
| `LLM_SERVICE_GENERAL_MODEL_NAME` / `_ENDPOINT` / `_API_KEY` | LiteLLM model spec. |
| `SA_STORAGE_ROOT` | Engagement artifact root. |

Optional system dependencies (for full output):
- `weasyprint` (Python) + its native dependencies (cairo, pango, gdk-pixbuf) — PDF rendering. HTML still produced if missing.
- `mmdc` (`@mermaid-js/mermaid-cli`, via npm) — SVG pre-render for PDF diagrams. PDF falls back to text-only diagrams if missing.

## Install (development)

```bash
pip install -e ../../solace-architect-core/
pip install -e .
```

## Install (end users)

```bash
sam plugin install git+https://github.com/solacecommunity/solace-agent-mesh-plugins.git#subdirectory=solace-architect-blueprint
sam plugin add sa_blueprint --plugin solace-architect-blueprint
```

## License

Apache 2.0.
