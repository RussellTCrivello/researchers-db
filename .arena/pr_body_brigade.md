## Brigade command interfaces — organised around Forces / Deployment / Training / Command

Everything requested in the latest directive, on top of the fresh comprehensive dataset.

### Organisation: the four command domains
- The military workspace is now organised as a **two-tier navigation**: top-level domain tabs **Forces / Deployment / Training / Command**, with each domain's data tables, trees and tools beneath it.
  - **Forces** — units, regions, divisions, classifications, armament, holdings + the force tree, region tree and force summary
  - **Deployment** — deployments and missions
  - **Training** — trainings
  - **Command** — commanders, command appointments and notes
  - (Naming series and the audit log remain reachable as administration items.)
- A **command hub** for each domain (`#/military/forces` etc.): KPI cards per data table (from the `/quality` totals), a management grid (Manage / New / tree shortcuts per table), and the domain's action list (low-readiness units, upcoming deployments, upcoming trainings, recent activity).

### Manage everything: add, edit, delete — and now import
- Every data table already had full CRUD + dossier; this round adds **CSV import on every table** (`POST /{entity}s/import.csv`, staff+).
  - Rows run through the **full rule engine** — validation, business rules, automatic naming counters, audit entries all apply exactly as on manual creation.
  - **Create-only** or **create-or-update** modes (upsert matches by `id` then `docname`).
  - **Per-row report**: every row gets a line number and status (created / updated / error with an exact reason); invalid rows never block the valid ones.
  - The UI shows the same panel on every list: file picker, mode selector, a summary chip and the full error table. Import and export form a round trip (headers = field names).
- Export was already per-list; import/export now form a complete data-management loop on all 12 entities.

### Advanced filtering and view modes for every function and data table
- Every list keeps the advanced filtering set (search, sortable columns, choice-facet filters, server pagination, deep-linkable filters) and now adds **Table / Cards view modes** — persisted per entity in `localStorage` — plus the existing **Tree view** for hierarchy entities (units, regions).

### Full control over numbering
- The naming series admin (preview, partitions, per-option next values, audited admin counter adjustment) gains a **counter history** log (`GET /api/military/naming/history`) with a history panel: every rebase shows actor, timestamp, old → new value. Numbering is now fully observable and controllable end to end.

### "Show more" options
- Dossier related-record panels now page inline ("show more" appends the next page) alongside the existing see-all links and list "load more".

### Defect found and fixed (live smoke)
Smoke-testing the import over HTTP surfaced a real robustness defect: **DB constraint failures (duplicate unique values, bad foreign keys) escaped the error mapper and returned HTTP 500 — one duplicate row aborted an entire import.** `create`/`update` now translate `IntegrityError` into clean `409 duplicate` / `422 constraint` errors; imports report them per row and keep going. Four regression tests cover this class (duplicate create, duplicate update, duplicate rows inside an import, FK violation).

### Verification (reported results, not substitutes for your testing)
- **233/233 tests pass** (134 registry + 99 military; 17 new this round incl. the 4 constraint regressions). `ruff` clean; `node --check` clean; locales at parity (1,176 EN/AR keys).
- **Live smoke 13/13** against the running app on :8000: the previously-500ing duplicate-import scenario now returns per-row errors, plus import/export round trip, naming history, hub data sources, and all new wiring served on the wire.
- **Browser click-throughs (hash-route navigation, forms, import panel, view toggles, tree expansion) could not be executed — no browser automation is possible in this sandbox** (Playwright cannot be installed; network-blocked). Everything above is verified at the HTTP/API and source level. The router and each view are wired per the contracts that passed in earlier browser-verified arcs (routes matched before the entity-list catch-all; `node --check` clean), but the interactive surfaces deserve your click-through on the live preview.

All demo data remains fictional and labelled; no real or classified content. The registry is intact and healthy.
