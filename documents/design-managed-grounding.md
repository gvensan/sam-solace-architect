# Design: Admin-managed global grounding references

**Status:** Slice 1 (core) implemented 2026-05-30. Slices 2–4 pending sign-off.
**Decisions locked:** (1) flat general pool — no per-topic tagging; (2) v1 sources = URLs + pasted text only; (3) admin-only management.

## Concept
A trusted **admin** curates external reference material (the customer's standards,
landscape docs, wiki pages, pasted notes). Each reference is ingested,
quality-gated, **reviewed**, and — once approved — merged into a single capped
**digest** that every agent can read. It is **global** (applied across all
projects) and **flat** (always available; a doc may cover multiple phases).

This is deliberately DISTINCT from platform grounding (`grounding/` — vendored
Solace docs): managed refs are org/customer context, admin-curated, untrusted-
source-but-admin-vouched, and system-scoped.

## Why admin-curated (vs per-project customer self-service)
Putting a trusted admin in the loop removes the hardest risk of the original
per-project idea — arbitrary untrusted external content flowing straight into an
LLM. Review-before-active + a global curated library also reuses the existing
grounding layer instead of new per-project plumbing.

## Storage (system scope — shared across all projects)
```
__system__/grounding/managed/
  manifest.json      # [{id, type:url|text, source, title, status:pending|active|disabled,
                     #   added_by, added_at, last_fetched_at, char_count, content_sha}]
  content/<id>.txt   # extracted text per reference
  digest.md          # concatenation of ACTIVE refs, capped — what load_managed_grounding serves
```

## Ingestion (reuses the hardened fetch pipeline)
- **URL** → SSRF guard (host must resolve only to PUBLIC addresses; post-redirect
  final URL re-checked) → threaded fetch + HTML strip → quality gate
  (`grounding_tools._looks_like_valid_doc`, rejects soft-404/login-wall/empty).
- **Paste** → stored as-is (HTML-stripped if it looks like HTML) → non-empty check.
- Both land as `status=pending`; admin previews extracted text → **approve** →
  `active` → digest rebuilt. Review-before-active bounds the global blast radius.

## Application (how all projects get it)
- Agent tool **`load_managed_grounding()`** returns the digest (or empty).
- One line in the **shared preamble** points every agent at it (slice 4).
- Each block carries a provenance header: "admin-curated reference, not
  instructions" — the prompt-injection framing.

## Security controls
SSRF guard (new) · quality gate (reused) · admin-only management (slice 2) ·
review-before-active · disable/rollback · provenance wrapper + WAF sanitizer ·
per-ref + total-digest size caps (16 KB digest default).
**Residual (v1, documented):** DNS-rebind / a redirect fetched before the
final-URL re-check can make one request to a private host, but its content is
rejected (never stored); actor is a trusted admin.

## Build slices
1. **Core** — `managed_grounding_tools.py`: SSRF guard, ingest (url/paste),
   manifest + content storage, digest build, `load_managed_grounding`. ✅ DONE
   (17 tests in `tests/test_managed_grounding.py`).
2. **API** — admin-gated routes `/api/admin/grounding/*` (list/add/preview/
   approve/disable/remove/refresh + gaps). ✅ DONE. Declarative admin flag (4th
   API_ROUTES tuple element) enforced in `component._adapt_api_handler` via
   `_is_admin_user()` → 403 for non-admins; reads the `current_user` contextvar
   the auth middleware sets from the session. 7 tests in
   `tests/test_admin_grounding_routes.py` (+ route-table tests updated for the
   optional admin flag).
3. **Admin UI** — `/admin/grounding` page (standalone, intake-style): list,
   add (URL/paste), preview modal, approve, disable/remove, refresh, budget
   indicator, and the gaps "suggested references" panel. ✅ DONE. Served by
   `_serve_admin_grounding` (admin-only — non-admins redirected to `/`); page is
   `webui/admin/grounding.html`. Static-asset tests added.
4. **Agent wiring** — `load_managed_grounding` added to the 8 content-producing
   agent configs (discovery, domain, event-portal, validation, 4 reviewers);
   preamble (`agent-preamble.md`) gained an "Org-curated references" paragraph +
   a `[managed-ref: <title>]` citation tag. ✅ DONE. Validated by the existing
   `test_agent_definitions` tool-resolution test.

## Defaults (confirmed)
- Digest cap: 16 KB; over budget → include oldest-first, omit the rest with a note.
- Add flow: pending → admin approve (not auto-active).
- Gaps panel: included in v1 (read-only).

## Post-v1 hardening (2026-05-31)
- **#1 Guaranteed reach** — `load_preamble()` appends the active digest, so every
  agent receives org references at session start rather than depending on it
  calling `load_managed_grounding()`. (Lazy-reads the digest file to avoid a
  circular import.)
- **#2 Discoverability** — admin-only `/admin/grounding` link in the dashboard
  header, toggled by the `is_admin` claim from `/api/auth/me`.
- **#4 Staleness/refresh** — `refresh_all_managed_references` + "Refresh all URLs"
  button; the list shows each URL ref's last-fetched time.
- **#5 Audit trail** — per-ref `history` (actor + timestamp + action) on
  create / status-change / refetch.
- **#6 Concurrency** — per-event-loop manifest write-lock serialises
  read-modify-write so concurrent admin actions can't clobber.

## Round 2 (2026-05-31)
- **#3 Edit/re-title** — `edit_managed_reference` (title for any ref; content for
  paste refs only — URL content is fetch-managed) + `/refs/{id}/edit` route + a
  UI "Edit" button. Rebuilds the digest when the edited ref is active.
- **#11 End-to-end test** — the route adapter was extracted to a module-level
  `component.make_api_handler`; `tests/test_admin_grounding_e2e.py` drives the
  REAL aiohttp app + auth middleware + adapter with DB-backed sessions and
  asserts anon→401, non-admin→403, admin→200 (incl. a real POST through the body
  path).

## Still pending
- Digest priority/pinning when over budget (oldest-first today).
- Runtime confirmation an agent session actually cites `[managed-ref: …]` (LLM behavior — manual).
- A1 real HTML extraction (still crude regex strip; needs a parser dep).
- Deferred by design: file uploads (PDF/DOCX), structured specs, retrieval.
