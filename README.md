# SIRAJ · سِراج — bilingual research registry

A complete, production-shaped registry for **persons, institutions, places, events, relationships and
sources**, built for historical and biographical research in Arabic and English.

It is a working application, not a mock-up: real database, real audit trail, real import/export,
real reports — and **1 427 executed checks**: 110 unit tests, 407 API assertions, 748 browser
assertions across ten Playwright harnesses that gate on console errors, and a 162-check audit of
the data itself.

![status](https://img.shields.io/badge/checks-109%20unit%20·%20404%20API%20·%20609%20browser-1d7a52) ![lang](https://img.shields.io/badge/languages-AR%20·%20EN-c9a227) ![db](https://img.shields.io/badge/storage-SQLite%20WAL%20%2B%20FTS5-17395c)

---

## Quick start

**Windows (primary target)** — double-click `start.bat` (or run `start.ps1` in PowerShell). It creates
`.venv`, installs the requirements, initialises the database on first run and opens the browser.

**macOS / Linux**

```bash
cd researchers-db
python -m pip install -r requirements.txt
python run.py                        # http://localhost:8000  (init + serve in one step)
```

Any platform, explicitly:

```bash
python run.py --host 0.0.0.0 --port 8000 --log-level info
python -m app.cli init --demo          # optional: (re)build the database with synthetic demo records
python -m app.cli bulk --profile large # optional: append ~20 000 linked records for volume testing
```

The interface opens in Arabic (RTL) and switches to English with one click.

> **Demo data notice**: everything except the vocabulary (countries, classifications, statuses) is
> **synthetic** — invented names and links created to exercise the interface, never a historical
> claim. A first run seeds 103 demo records (24 persons, 12 institutions, 20 places, 33 relationships,
> 8 sources, 6 events); the reference dataset used for volume and verification (§*Verification*)
> holds **28 538 records** built with `python -m app.cli bulk --profile large`. Start an empty
> registry with `SIRAJ_SEED_DEMO=0 python -m app.cli init`.

---

## What is inside

| Area | Delivered |
|---|---|
| **Six entities** | persons, institutions, places (self-hierarchising), events, relationships, sources — all with bilingual fields, vocabularies, sources, notes and full metadata |
| **Record operations** | create, read, update, delete (soft + hard), restore, bulk status/delete/restore, duplicate & required-field validation, optimistic locking (`version` → 409) |
| **Related-field inputs** | every field pointing at another table (and every large vocabulary) is a **searchable drop-down** with Arabic-aware search, recent choices and **inline creation of the missing record** in a pop-up — no lost form state, numbering/validation/audit still apply |
| **Fields from related tables** | 52 declared derived fields (relationship/position/citation counts, institution & country names, birth/death years, age, durations, completeness) usable in **columns, filters, sort, export, saved views, card layouts and report pivots** |
| **Display options** | four data views (table · cards · gallery · rows) per entity, a **card layout builder** (image / title / subtitle / badge / facts / KPI figures) with live preview, per-user column visibility for *any* field including derived ones, saved views, density control |
| **Record panel beside the list** | pick a person, institution or place and the screen splits in two: the data keeps one half, the other becomes a three-tab panel — **Details** (the whole dossier: fields, positions, events, sources, files, change log — all editable in place), **Relationships** (the connections visualised as an interactive ego-network — hover spotlights a branch, click a node to open that record, zoom/pan tools, labelled edges, legend — plus every link listed), and **Map** (the record's coordinates in DD and DMS on the offline base map, marker, copy/recentre, links into the geographic workspace and the atlas); by default the data view owns the whole screen, `Esc` gives it back |
| **Fixed chrome & progressive loading** | filter dock, column headers, saved-view bar and pagination stay pinned while only the data area scrolls (measured, height-fitted, smooth); pages **and** *Load more* / auto-load-on-scroll coexist; one-tap *Collapse filters* returns the space to the table |
| **Imagery** | image upload (`/api/media`) with alt text on persons, institutions, places and events; portraits and gallery views; graceful placeholders when an image is missing |
| **Duplicates & merge** | Arabic-normalised duplicate detection, review panel, dry-run merge plan, field filling, link/relationship migration, recoverable archive, full audit entry |
| **Deep filters** | per-field operator builder (18 operators), AND/OR logic, multi-value `in`, date ranges by year, null checks, tag filters, full-text `q`, sortable columns, saved views, include-deleted mode |
| **Arabic-aware search** | FTS5 with normalisation for diacritics, hamza forms, taa marbuta and the definite article; `موصل` finds `الموصل` and vice versa |
| **Numbering control** | per-entity rules (prefix, separator, suffix, padding, template, yearly/monthly reset), next-value preview, never-reused codes, legacy identifiers kept separately |
| **Import** | 4-step pipeline, XLSX/CSV/TSV/JSON, UTF-8 **and CP1256** detection, bilingual header auto-mapping, value resolution by code/EN/AR label, dry run with per-row errors, create/upsert/update-only, per-row savepoints, job log |
| **Export** | XLSX (RTL sheets, styled, auto-filter), CSV with BOM (Excel + Arabic), TSV, JSON — column selection, AR/EN/both labels, always respecting current filters |
| **Reports** | 9 production reports (overview, data quality, institutions, geography, network, chronology, sources, review progress, indicators) + ad-hoc pivot builder; every report printable and exportable |
| **Control panel** | KPI cards per entity, status/authentication distributions, 12-month editorial activity, top countries, relationship types, sourcing coverage, recent changes |
| **Administration** | vocabularies (21 domains / 271 values, add-in-place), numbering, users & roles, languages, backups, re-index, vacuum, global change log |
| **Configuration system** | every setting declared once in a typed registry (27 keys, 8 groups) with bilingual labels, bounds and the code path that honours it; a screen generated from it, `GET/PUT /api/settings` + `/api/settings/schema` + `POST /api/settings/reset`; **validated** (a bad value is refused with a reason, never silently scrubbed), **all-or-nothing**, **audited** per key, **scoped** (instance policy vs. one browser), **reversible**; plus policy gates that actually refuse — publishing without a source, deleting without a reason, imports/exports over a ceiling |
| **Geographic workspace** | a real map over the registry, `#/geo`: **eight base maps in four families** — offline vector, standard street maps, **aerial imagery** (plain and hybrid) and terrain — each with the attribution its licence requires; markers are records at their stored coordinates (750 places + geolocated persons, institutions and events), **a click on a point always answers**: its dossier opens by itself, a point hiding other records lists them all, and a printed base-map city shows the registry records within 25 km of it, list ↔ map ↔ inspector kept in sync, click empty ground for a **temporary** point that never writes, groups that open their records, live filtering with a matching count, layer toggles that change the *view* only, measurement, DMS ↔ decimal entry with range validation, geocoding search and coordinate navigation, five CRSs, antimeridian-safe queries, relationship and place-hierarchy overlays drawn from the stored rows, **offline base map** (2.54 MB Natural Earth pack, no network) with OSM/CARTO providers one click away and their attribution shown, plus a three-zone analytical mode whose panels collapse independently |
| **Military Organization (BIMS)** | a first-class **Brigade Command workspace inside the shell** (`#/military`, see [`docs/MILITARY_ORG.md`](docs/MILITARY_ORG.md)): twelve entities from regions and a military-unit force tree to deployments, missions, armament holdings, training and command appointments; a server-enforced business-rule catalogue (tree integrity, date chronology, one current deployment per unit with synchronised pointers, appointment overlap, training capacity against **computed** subtree personnel, restricted deletes); an automatic naming-series engine (19 catalogued series with year/category partitions and audited counter control); an append-only audit trail; role enforcement (viewer/staff/admin); a **fictional** sample dataset and an Appendix C CLI verifier — sharing the application's navigation, locales (EN/AR), themes and design language, with its own database so the registry is never touched |
| **Bilingual UI** | complete AR/EN bundles with RTL/LTR, light/dark themes, responsive layout, print stylesheets; adding a language = one JSON file + one DB row |
| **Audit trail** | field-level change log with transaction id, actor, reason, source, reviewer, old/new values, per record and globally |
| **Infrastructure** | schema + versioned migrations, connection-level SQL helpers, reindexing, **backups that include every uploaded file**, JSON full dump, optional bearer-token API auth (`SIRAJ_API_TOKEN`), `/api/metrics`, CLI, pytest suite, Playwright UI smoke test |

## A look at the interface

| | |
|---|---|
| ![list](docs/screenshots/list-kpi-strip.png) | ![cards](docs/screenshots/cards-with-imagery.png) |
| **List + KPI strip** — figures for the current selection, `ƒ` marks related-table totals | **Cards** — portraits when an image exists, initials band when not |
| ![filters](docs/screenshots/filter-form-parity.png) | ![form](docs/screenshots/record-form-comboboxes.png) |
| **Filters with form controls** — the same drop-downs, chips and date pickers as data entry | **Form** — every relation is a searchable drop-down with inline creation |
| ![map](docs/screenshots/map-canvas-en.png) | ![dates](docs/screenshots/record-form-date-time.png) |
| **Relationship map** — pan, zoom, drag nodes, hover a neighbourhood, find a node | **Date & time** — enter a year, a day or a moment; the precision you typed is what is stored |

| ![sticky frame](docs/screenshots/list-sticky-frame-ar.png) | ![load more](docs/screenshots/list-load-more-ar.png) |
|---|---|
| **Fixed frame** — header, filters and pager pinned; only the data area scrolls | **Load more** — appends the next page, keeps the pager usable, shows `shown / total` |

| ![geo map](docs/screenshots/geomap-en.png) | ![geo map arabic](docs/screenshots/geomap-ar.png) |
|---|---|
| **Geographic workspace** — the registry on a map: records at their coordinates, clusters, layers, legend, scale and live readout | **The same view in Arabic** — RTL panels, translated legend and attribution |
| ![aerial](docs/screenshots/geomap-aerial.png) | ![styles](docs/screenshots/geomap-styles-menu.png) |
|---|---|
| **Aerial imagery** — satellite photographs with a labels layer over them, registry markers on top, both attributions shown | **Base map families** — offline, standard, aerial and terrain, each with a swatch of what it looks like |
| ![point records](docs/screenshots/geomap-point-records.png) | ![city records](docs/screenshots/geomap-city-records.png) |
|---|---|
| **A click on a point** — the dossier, plus every one of the 35 records stacked at that spot | **A printed city** — marked as cartography rather than a record, with the 18 registry records inside 25 km |

| ![measure](docs/screenshots/geomap-measure.png) | ![collapsed](docs/screenshots/geomap-collapsed.png) |
|---|---|
| **Measure** — great-circle distance in metres or kilometres as you drag | **Both panels collapsed** — the map takes the whole area and `resize` is fired |

| ![settings](docs/screenshots/settings-registry-en.png) | ![settings ar](docs/screenshots/settings-registry-ar.png) |
| **Settings** — generated from the registry: group cards, type-aware controls, defaults and source badges, the code path each value affects | **The same screen in Arabic** — RTL throughout, translated labels, help and enum values |
| ![surface setting](docs/screenshots/setting-form-surface.png) | ![dialog form](docs/screenshots/form-dialog-ar.png) |
|---|---|
| **Where a form opens** — one setting: full page, pop-up window, or automatic | **The same form as a dialog** — over its list, sticky footer, RTL and AR included |

More screens in `docs/screenshots/` (gallery view, card-layout builder, record dossier, filters in
English, the form as a dialog in English, mobile layout).
The demo images are AI-generated placeholders attached to three demo persons and one institution —
replace them with real, rights-cleared material.

## Project layout

```
researchers-db/
├─ app/
│  ├─ schema.sql            current schema (fresh installs)
│  ├─ migrations/           versioned, applied once, recorded in schema_migration
│  ├─ db.py                 connections, normalisation, numbering, audit, FTS
│  ├─ schemas.py            ← single source of truth: entities, fields, labels, validation
│  ├─ repo.py               read/write layer, filter engine, detail assembly
│  ├─ transfer.py           import pipeline + export engine
│  ├─ reports.py            9 reports + pivot + report export
│  ├─ stats.py              dashboard aggregates
│  ├─ seed.py               vocabularies, locales, users, sequences, demo data
│  ├─ server/
│  │  ├─ __init__.py        re-exports the ASGI app (`app.server:app`)
│  │  ├─ api.py             FastAPI routes, lifespan, static + media streaming
│  │  └─ launcher.py        UTF-8 console/env setup, data-dir resolution, serve()
│  ├─ military/             Military Organization (BIMS) — self-contained module
│  │  ├─ dbm.py             own SQLite file (military.db), schema, connection rules
│  │  ├─ vocab.py           controlled vocabularies + state-transition tables
│  │  ├─ naming.py          naming-series engine (19 options, partitions, counters)
│  │  ├─ rules.py           business rule catalogue (tree, dates, pointers, caps)
│  │  ├─ service.py         transactional CRUD, sync, audit, bilingual labels
│  │  ├─ api.py             /api/military router (roles enforced server-side)
│  │  ├─ seed.py            fictional sample dataset (labelled fictional)
│  │  └─ cli.py             python -m app.military.cli verify (Appendix C)
│  ├─ cli.py                init / serve / migrate / backup / stats / export / user
│  ├─ data/                 registry.db, uploads/, staging/  (git-ignored)
│  └─ static/
│     ├─ index.html         the single shell (3 CSS layers + 7 JS blocks)
│     ├─ css/               base.css · components.css · views.css
│     └─ js/                core.js, app.js
│        ├─ components/     forms.js   (combobox, inline-create, shared inputs)
│        ├─ views/          list · record · dashboard · reports · admin
│        └─ locales/        index.json (language manifest) + en.json + ar.json
├─ docs/                    DESIGN_REVIEW · DATA_MODEL · IMPORT_EXPORT · API · OPERATIONS · UI_GUIDE · I18N · GRAPH · ATLAS · CRCE · SETTINGS · VERIFICATION · AUDIT · PHASE5 · PHASE6 · MILITARY_ORG
├─ samples/                 import examples + run_samples.py
├─ tests/                   pytest suite (110) · verify_all.py (407 API, 101 routes) · audit.py (162
│                           integrity & behaviour) · ui_smoke.py (51) · ui_full.py (200)
│                           · ui_geo.py (98) · evidence_ui.py (37) · query_ui.py (14)
│                           · atlas_ui.py (54: the relationship atlas)
│                           · crce_ui.py (93: the compass-rose coordinate standard)
├─ scripts/check.py         one-shot verification: --api --ui --full --geo --audit --evidence --atlas --crce
├─ .github/workflows/ci.yml Windows + Ubuntu × Python 3.10/3.12, plus a Playwright job
├─ run.py · start.bat · start.ps1 · run.sh
└─ requirements.txt · requirements-dev.txt · .editorconfig · .gitattributes
```

**Run entry points.** `run.py` is the only launcher: `python run.py` initialises on first use and
serves; `start.bat` / `start.ps1` are the Windows shortcuts (virtualenv + install + browser);
`run.sh` is the POSIX equivalent. All of them end in the same `app.server.launcher.serve()`.

**One source of truth.** `app/schemas.py` declares every entity and field once; the API metadata
endpoint ships that to the browser, which then generates forms, table columns, filter operators,
import mappers, export column pickers and report dimensions from it. Adding a field is a one-line
change in that file plus one migration.

## Everyday tasks

```bash
python -m app.cli stats                       # record counts
python -m app.cli backup -o backups/nov.zip   # consistent snapshot
python -m app.cli export person out.xlsx --lang ar
python -m app.cli reindex                     # rebuild search index
python -m app.cli user reviewer reviewer      # add an acting user
python -m pytest -q                           # run the test suite (110 tests)
python tests/verify_all.py                    # exercise all 101 API routes (407 checks)
python tests/audit.py                         # the fundamental audit (162 checks)
python -m app.cli check-integrity             # is the data structurally sound?
python tests/ui_full.py                       # walk every UI control (200 checks)
python tests/evidence_ui.py                   # evidence cards + relationship diagram (37 checks)
python tests/atlas_ui.py                      # the relationship atlas (54 checks)
python tests/crce_ui.py                       # the compass-rose standard, CRCE (93 checks)
python tests/structures_ui.py                 # the six structures, in a browser (62 checks)
python tests/desk_ui.py                       # the map desk, in a browser (87 checks)
python samples/run_samples.py                 # import every sample file through the API
```

## Documentation

| Document | Contents |
|---|---|
[`docs/DESIGN_REVIEW.md`](docs/DESIGN_REVIEW.md) | **the review you asked for**: 21 concrete issues in the original schema, what was changed and why, field-by-field mapping, phase-2 roadmap (Arabic summary at the top) |
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | tables, relations, conventions, vocabularies, indexes, PostgreSQL migration path |
[`docs/IMPORT_EXPORT.md`](docs/IMPORT_EXPORT.md) | the four-step import, encoding rules, value resolution, match modes, export options, sample files |
[`docs/API.md`](docs/API.md) | every endpoint with payloads and curl examples (also `/docs` OpenAPI) |
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) | install (Windows first), backup/restore, migrations, roles & security checklist, troubleshooting |
[`docs/I18N.md`](docs/I18N.md) | how the locale system works and how to add a third language |
[`docs/MAP.md`](docs/MAP.md) | **the geographic workspace**: what each feature is made of, the coordinate model, providers and their licences, the offline basemap, the API, the three-zone layout, and the acceptance criteria with the check that proves each one |
[`docs/UI_GUIDE.md`](docs/UI_GUIDE.md) | every screen and control, including the **map desk** (`#/desk`): the map, the detail rail, the pop-up card, the neighbourhood panel, the table view, the keyboard and the preferences it keeps |
[`docs/GRAPH.md`](docs/GRAPH.md) | the relationship graph: typed vs. structural links, the two map endpoints, the in-app explorer and the generated figures |
[`docs/CRCE.md`](docs/CRCE.md) | **the compass-rose coordinate encoding**: the standard as data, the four reserved marks, the dossier field order, the inheritance model, the honest reference point, the three relationship states, what the standard refuses to cover, and every surface it appears on |
[`docs/VERIFICATION.md`](docs/VERIFICATION.md) | **the evidence**: what each harness proves, the nine defects verification found and fixed, and how to reproduce |
[`docs/MILITARY_ORG.md`](docs/MILITARY_ORG.md) | **the Military Organization (BIMS)**: the twelve entities and their data dictionary, the server-enforced rule catalogue, the naming-series grammar and catalogue, the API, the Brigade Command interface, the fictional sample dataset, the Appendix C verifier and the glossary |
[`docs/SETTINGS.md`](docs/SETTINGS.md) | **the configuration manual**: the four layers (deployment / instance / personal / per-request) and which wins, every key with its type, default, bounds, consumer and precedence, all four ways to read or write one (screen, API, SQL, CLI), validation reasons, reset and audit, backup/restore of a configuration, how to add a key in five minutes, security notes and a troubleshooting table |
[`docs/PHASE6.md`](docs/PHASE6.md) | the data-entry surface setting: page or pop-up window, instance default vs. personal override, the dialog behaviour contract, and the three defects building it exposed |

## Known limits (documented, not hidden)

* **No authentication in v1** — acting user comes from `X-Actor`; put it behind an authenticating
  proxy and add role checks before public exposure (see `docs/OPERATIONS.md` §Security).
* SQLite is the storage engine: excellent to ~10⁵–10⁶ rows, single-writer. The SQL is portable and
  `app/repo.py` isolates it for a PostgreSQL move.
* Arabic search is normalised prefix matching, not morphological analysis.
* Two content languages (AR/EN) by design; a full *n*-language model for *record content* needs the
  translation table described in the review. The *interface*, by contrast, is already
  language-agnostic: every string lives in `app/static/js/locales/<code>.json` and the language list
  is data in `locales/index.json`, so a new UI language is a file plus one manifest line
  (see `docs/I18N.md`).
