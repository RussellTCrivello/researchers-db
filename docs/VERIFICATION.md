# Verification report

*How the claim "every interface function works" is backed by executed tests rather than assertion.*

Everything below is reproducible on a clean checkout against the running server on
`http://127.0.0.1:8000`. Numbers in this document are the numbers the commands printed.

| Harness | What it proves | Checks | Runtime |
|---|---|---|---|
| `pytest tests -q` | data model, repository, reports, import/export, numbering, i18n, place hygiene, graph API, merge audit trail, the settings registry (types, bounds, refusal, reset, audit, one source for defaults), security basics, and every image reference resolving | **110 passed** | ~5 s |
| `tests/verify_all.py` | every HTTP route (all **101** are enumerated from the OpenAPI schema at runtime and none may go unexercised — including the 15 geographic routes and the two CRCE routes), both success and failure paths, the date-and-time model in depth, the configuration API end to end, the **geographic surface** (features, groups, overlays, dossiers, coordinates, antimeridian, basemap, gazetteer, georeferencing preview), the **compass-rose standard** ([CRCE.md](CRCE.md)), plus cleanup that restores the data | **407 / 407** | ~83 s |
| `tests/ui_smoke.py` | fast browser pass: routes, four data views, filters, forms, RTL, the dirty-draft guard | **51 / 51** | ~28 s |
| `tests/ui_full.py` | **every screen and every interactive control** in a real Chromium — including panning, zooming, node dragging, the date-time picker, the page/dialog form surfaces and the whole settings screen — with console-error gating | **200 / 200** | ~3.6 min |
| `tests/ui_geo.py` | the **geographic workspace** in a real Chromium with a real WebGL canvas: the **25 acceptance criteria** of the map phase, each mapped to the check that proves it in [MAP.md](MAP.md) §12 — plus provider-failure recovery, attribution, keyboard access and a no-write assertion, against the running server and the live registry | **98 / 98** | ~88 s |
| `tests/evidence_ui.py` | evidence as claims attached to fields and relationships, the drawer's metadata, and the diagram's verification grammar | **37 / 37** | ~30 s |
| `tests/query_ui.py` | the typed query language in the browser: tokens, chips, refusal of nonsense, and the round trip back into a filter | **14 / 14** | ~10 s |
| `tests/atlas_ui.py` | [the atlas](ATLAS.md): selection without navigation, the panel as the reading surface, drill-in with a reversible trail, three arrangements, in-place filters, path finding, keyboard access, AR/EN and disposed listeners | **54 / 54** | ~37 s |
| `tests/crce_ui.py` | [the compass-rose standard](CRCE.md): the published standard, symbol exclusivity, a place's encoding, a person's inheritance, an unlocated record, three relationship states, aliases and 404s, the Position tab in both languages, the atlas rosettes and panel tile, the geographic legend | **93 / 93** | ~17 s |
| `tests/structures_ui.py` | [the six structures](STRUCTURES.md): one model behind six arrangements, the selection panel, the crumb trail, the folding that declares itself, the cost the footer prints, AR/EN | **62 / 62** | ~40 s |
| `tests/desk_ui.py` | [the map desk](MAP.md) — the registry worked as a place: a real WebGL canvas over the offline pack, marks that are records, the pop-up card that never navigates, the four-tab rail, the neighbourhood panel that walks between records, the same records as a table, search and Enter, the trail, layer chips, base-map switching, the record with no coordinates, Arabic mirroring, and a disposed map with no console error | **87 / 87** | ~50 s |
| `tests/audit.py` | [the fundamental audit](AUDIT.md): data integrity, filter/sort truth tables checked against independent counts, concurrency, durability, latency budgets | **162 / 162** | ~46 s |

**1 375 executed assertions in total**, all green.

```bash
python3 scripts/check.py --api --ui --full --geo --audit --evidence --query --atlas --crce --structures --desk
                                                          # everything, one command
```

The audit is not a second opinion on the same questions: it recomputes expected values with
different SQL or in Python, so a defect in the filter engine cannot hide behind a test that asks the
filter engine what it thinks. It found seven defects — an export that silently truncated at 1 000
rows, an export that ignored its own filter, four filter operators that returned the whole table,
hard deletes that orphaned citations and tags, an asymmetric relationship matrix, and the absence of
any way to ask the product whether its data was sound. All are fixed and covered by regression
tests; [AUDIT.md](AUDIT.md) documents each one with the measured before/after.

---

## 1 · API surface — `tests/verify_all.py`

The harness reads the **OpenAPI schema** at runtime (`app.openapi()["paths"]`, which is the only
honest inventory: walking `app.routes` misses every route added by `include_router()`) and fails if
**any** route is never exercised. It currently proves **87 route entries over 74 paths**, of which 15
are geographic. It covers, for each of the six entities: list/query
(clause filters *and* the compact `{field: {op: value}}` form), CRUD, bulk actions, merge, restore,
duplicates, attachments upload + download, tags, saved views, KPI, timeline, import validate + commit,
export in four formats, reports (ten), relationship map (types and focus), maintenance, users and
settings.

Two design rules make it safe to run against the live registry:

* scratch rows are found with **exact-marker `contains` filters** — never with full-text search, which
  once matched hundreds of legitimate records;
* every row it creates is **restored and then hard-deleted** at the end (a merge soft-deletes its
  absorbed record, and a hard delete cannot reach a soft-deleted row — that gap used to leave one row
  behind per run), and the harness asserts the dataset is unchanged (28 538 records before and after,
  verified across repeated runs).

## 2 · Interface surface — `tests/ui_full.py`

It walks the application the way a demanding reviewer would:

* **shell** — sidebar, entity nav, language toggle (AR↔EN and back, direction flips), actor switch
  persisted to `localStorage`, global search, unknown entity type refused without an API call;
* **all 13 routes** plus one list per entity, a record dossier, the edit form and the new-record form;
* **lists** — quick search, sortable headers with the active sort marked, page size, pagination,
  load-more, filter dock (clause *and* derived field), chips, clearing, saved views, column chooser
  with presets, card-layout builder, duplicates panel, export panel, bulk selection bar, deleted-records
  lens, and the four view modes (table / cards / gallery / rows);
* **records** — completeness ring, derived KPI strip, every tab, edit-form round trip (value persists,
  `version` increments for optimistic locking), combobox search, inline-create pop-up;
* **CRUD through the browser** — create a record in the form, find it in the list, soft-delete it with
  the bulk bar, restore it, then hard-delete it in cleanup;
* **reports** — the index and all ten reports contain data;
* **import wizard** — template download, real file upload, column mapping, **dry-run validation**
  (never commits), restart;
* **export studio** — live XLSX and CSV downloads;
* **relationship map** — overview SVG, relationship matrix, legend, structural-links toggle, SVG
  download, focus mode with depth 1→2, entity switch, and click-through from a node to its record;
* **admin** — vocabularies (domain switch + search), numbering (preview + save), settings (save),
  change log (filter + paging), maintenance (reindex, vacuum, backup ZIP, JSON dump);
* **data-entry surface** — the Settings card (active mode marked, three modes, scope switch, width,
  trial button), page mode really rendering a page, dialog mode opening over a *live* list without
  re-painting it, focus inside the dialog and `aria-labelledby` set, Escape on a clean form returning
  to the list, Escape on a dirty form offering "Discard changes?" (declining keeps the draft), Save
  landing on the dossier, Save + New reusing the surface with a cleared form, editing over a visible
  dossier, the trial button returning to `#/settings`, and the automatic breakpoint (1440 px → dialog,
  700 px → page);
* **responsive** — 880 px: no horizontal overflow, sidebar opens as an overlay.

The last gate is **console hygiene**: any `console.error` or uncaught page exception fails the run. It
is checked section by section, so a failure names the screen that caused it.

The settings screen gets its own sequence because it is generated from the backend registry rather
than hand-written: the walk proves that every group and every declared key is rendered, that each
control knows its own type (`data-kind`), that **Save stays disabled until something differs**, that
the pending-change bar appears and names the keys, that a save round-trips to the database, that a
refused value shows its reason under the offending row and applies nothing, that reset restores the
declared default, and that a personal theme, density or search threshold applies immediately and
clears cleanly.

## 3 · Defects this verification found and fixed

The harnesses were not written to confirm existing behaviour; they were written to break it. They
found eighteen real defects — all of them in shipped, previously "green" code:

| # | Symptom a user would have seen | Cause | Fix |
|---|---|---|---|
| 1 | Pressing **Save** on a new record did nothing — the page reloaded and the draft vanished | the editor is a `<form>`; the save buttons defaulted to `type="submit"`, so the native submit reloaded the page and aborted the in-flight `POST` | `type="button"` on the action bar, plus `submit` is always `preventDefault()`ed (`views/record.js`) |
| 2 | **New records could never be saved**: validation demanded a record status that the form left blank | `record_status_id` is required, but nothing preselected it; the server quietly defaulted to *draft* | the form now preselects the workflow default *draft* (`views/record.js`) |
| 3 | **Every confirmation was a no-op** — delete, bulk delete, merge, discard-changes all silently cancelled | `confirmDialog()` resolved *after* closing; `close()` fired `onClose` first, which resolved `false`, and the later `true` was ignored | the answer is captured before the dialog closes (`core.js`) |
| 4 | Navigating away mid-load printed `TypeError: Cannot set properties of null` and could paint a stale screen over the new one | async views wrote into a container that a later render had already replaced | each render is stamped with a token; `App.fresh(root)` guards and `isConnected` checks protect every async paint (`app.js`, `reports.js`, `map.js`, `admin.js`) |
| 5 | `#/entity/does-not-exist` silently rendered an empty list view and fired 404s | the router did not validate the entity segment | unknown entity types are refused with a localised notice and no API traffic (`app.js`, two new locale keys) |
| 6 | The place tree read `City of Mauritania` five times over, and dozens of branches had same-named siblings, so maps and "group by place" reports were unreadable | the dataset generator re-drew a city name when a country's real pool was exhausted | the generator now guarantees a unique, real name per branch (`app/bulk.py`), and `python3 -m app.cli tidy-places` repairs existing data with an audited rename per record (`app/placeclean.py`; 1 322 renames applied to the shipped dataset — 846 places, 706 institutions, 616 events — leaving 0 placeholders in all three tables) |

| 7 | **Save + New failed with `409 Conflict`** on the second record; a previewed code could only be used once | `peek_next_code` read a sequence that `create_record` never advanced when the client supplied a code | `db.sync_sequence()` pushes the counter past any supplied code, `peek_next_code` skips codes that exist, `create_record` syncs (`db.py`, `repo.py`) |
| 8 | **A merge could silently delete the wrong links** — a valid `B → Z` link vanished because the survivor happened to have an `A → Y` link of the same type — with no audit entry | the duplicate test compared one side plus the relationship type, and the deletion was unlogged | the test compares both ends and the type, would-be self-links are dropped explicitly, and every move/drop is written to `change_log` (`repo.merge_records`) |
| 9 | **The duplicates panel merged two real records on a single click** (the first "Merge" button took focus, so a stray Enter did it) | the dialog focused the first focusable control, and "Merge now" acted immediately | the dialog parks the cursor on its heading (`modal()` resolves `focus` across the whole dialog) and "Merge now" previews the effect and asks first (`views/list.js`) |

| 10 | The settings screen showed `True`/`False` for every toggle and the browser compared Python strings | settings were serialised with `str(value)` | `settings.as_strings()` produces one canonical form (`true`/`false`), used by `/api/settings`, `/api/settings/schema` and `/api/meta` |
| 11 | Any value could be written under any key — a typo, an out-of-range number or a value for a key that no code reads — with nothing to show for it afterwards | the route was a blind upsert of `str(value)` | the typed registry refuses unknown keys, wrong types and out-of-range values with a per-key reason, **all-or-nothing**, and writes one audited `change_log` row per key |
| 12 | A form nobody had touched offered to discard changes; a dirty form could also lose them silently when the route changed | "dirty" was set by any input event (including typing a search string inside a combobox), and the router guard awaited a confirmation that a later render never closed, stacking dialogs | dirty is a comparison against the loaded values with a baseline captured after the prefills settle (`views/record.js`), and the guard tracks its pending prompt so at most one exists (`app.js`) |
| 13 | Three settings — inline creation and the two search thresholds — offered *use for me only*, then ignored the personal choice | the consumer read the instance value directly | every consumer resolves personal → instance → fallback (`components/fields.js`, `views/reports.js`), and the screen only offers the button where that is true |
| 14 | "Reset everything" wrote 18 audit rows saying `25 → 25` and left `SELECT * FROM setting` empty | reset logged unconditionally and deleted without re-seeding | reset logs only real changes, and leaves one default row per declared key so the table stays readable (`settings.reset`) |
| 15 | A legacy key (`ui.autosave_drafts`) survived in the table although nothing reads it, because the old screen wrote back every key it had ever seen | undeclared rows were never pruned | migration `009` removes rows that the registry does not declare, and a pytest case fails if a migration ever seeds an undeclared key again |
| 16 | The form's "unsaved changes" marker never appeared in the dialog surface, so a form with changes looked untouched | the marker lived in the action bar, which the dialog *moves* into its footer, and it was looked up with `form.querySelector` | the marker is resolved against the nearest `.modal` (or the document) when it is painted, and re-resolved if it is detached (`views/record.js`) |
| 17 | A place opened on the map returned **500** from `/api/map/feature/place/{id}` — the inspector never filled | the dossier builder picked `title_en`, but `source` carries `title`/`title_ar`, so the column did not exist | the builder uses the declared column names per entity and the geo section of `verify_all` now opens a dossier for every entity type (`app/geo/mapdata.py`) |
| 18 | Searching the map for a city returned **500** — `q=Baghdad` failed instead of finding Baghdad | the search joined the name columns ambiguously, so SQLite refused the query | the join is qualified per table, and the geo section asserts a gazetteer hit by name (`app/geo/mapdata.py`) |

Each of these is now covered by an assertion in `tests/ui_full.py` (7, 8 and 11–15 by pytest cases as
well), so they cannot silently return. Defects 17 and 18 are the map's own: both were caught by the
geographic section of `tests/verify_all.py` on its first run, before the interface ever saw them.

Two failures the harnesses produced were **not** product defects, and are recorded here so nobody
re-learns them: the map's *"editing a field marks the draft dirty"* failure was a real defect (#16),
while *"the layer menu opens from the keyboard"* was the harness leaving the menu open from the
previous section — a state leak in the test, fixed by closing the menu at the end of the section that
opens it rather than by touching the product. A test that fails is a claim about the product only
until you have read it.

## 4 · Data volume

The registry is verified against a deliberately large, coherent dataset, not the 103-record demo:

| Table | Rows | | Table | Rows |
|---|---|---|---|---|
| person | 7 024 (6 825 active, 199 soft-deleted) | | relationship | 14 569 |
| institution | 1 212 | | source | 3 208 |
| place | 1 118 | | event | 1 606 |
| person_position | 9 346 | | source_link | 4 078 |
| entity_tag | 8 050 | | change_log | 21 840 |
| search_doc | 28 538 | | **total records** | **28 538** |
| setting | 27 (one row per declared key) | | | |

The database is ~85 MB (it grows with the change log, which is the point). List queries stay in the tens of milliseconds, the duplicates scan runs as a
single windowed SQL statement (835 person groups in ~190 ms), and the relationship map aggregates
18 139 relationship↔institution links without a perceptible delay.

*Census note.* The phase-5 checkpoint read 28 541 records and 14 572 relationships. Three relationship
rows are gone: `REL-8593` and `REL-12595` were exact duplicate links dropped by a merge (see
[PHASE6.md](PHASE6.md) §6.3 and §7), and `REL-3547` is an older gap with no change-log entry, from
before link changes were logged. No entity rows are missing: every other count, including the 199
soft-deleted persons and the 7 024 person rows, is identical to the checkpoint, and
`check-integrity` reports no structural problems.

## 5 · Reproducing this report

| 19 | Making a citation stopped satisfying the publish gate: a record could be "verified" with its sources invisible to the check, or be refused although it was sourced | `validation.require_source_on_publish` looked only at the legacy `source_link` table, but citations are now written to `evidence` | the gate accepts either store, and a pytest case publishes a record that carries only an evidence row (`app/repo.py`) |
| 20 | Merging two people left the survivor with none of the sources that justified the merge, and left evidence pointing at the absorbed record | `MERGE_TABLES` did not include the new `evidence` table | `evidence` is in the merge set, `UPDATE OR IGNORE` keeps the uniqueness rule, and `test_merge_moves_evidence_to_the_survivor` asserts the rows moved and the counts add up (`app/repo.py`) |
| 21 | The integrity scanner reported **5 184 orphaned evidence rows** in a perfectly healthy database | the generic polymorphic rule checked `entity_type/entity_id`, but relationship-level evidence carries `relationship_id` and leaves the entity columns null | `evidence` has its own rule — entity rows against the entity tables, relationship rows against `relationship`, and a row with neither target is called malformed (`app/integrity.py`) |
| 22 | Adding an English string broke the Arabic bundle: the app showed *[object Object]* wherever `map.*` was read | the locale files are **flat dotted keys**, and the edit created a nested `map` object | both bundles are flat again, parity is asserted key by key, and the "every string used in JS exists in both bundles" test catches the next attempt (`app/static/js/locales/*.json`) |
| 23 | Clicking an edge on the relationship diagram did nothing at all | `svg.setPointerCapture()` on `pointerdown` retargets the derived `click` to the `<svg>`, so the edge's handler never ran — panning worked perfectly, which is why it looked like a rendering bug | `pointerdown` returns early when the target is inside `.rm-edge`; the same guard is needed by any future clickable SVG furniture (`app/static/js/views/map.js`) |
| 24 | A focused record could not be opened in the diagram unless it happened to be among the 60 most-connected records, and the picker silently showed a different record instead | the focus control listed one server page and had no way to address anything else | a record page links with `#/map?focus=entity:id`, the requested record is fetched and placed first when it is outside the page, and a search box finds any record in the registry (`app/static/js/views/map.js`, `views/record.js`) |
| 25 | The browser test could not click a perfectly vertical relationship edge | a straight vertical (or horizontal) line has a zero-width bounding box, so an automated driver reports the element as invisible and refuses to act | the harness clicks the midpoint of the drawn line rather than the element's centre — which is what a person does with the 14-unit hit stroke (`tests/evidence_ui.py`) |

```bash
python3 run.py --host 0.0.0.0 --port 8000 &      # or start.bat on Windows
python3 -m pytest tests -q                        # 110
python3 tests/verify_all.py                       # 368
python3 tests/ui_smoke.py                         # 51
python3 tests/ui_full.py                          # 200   (writes .smoke/full/*.png)
python3 tests/ui_geo.py                           # 98    (writes .smoke/geo/*.png)
python3 tests/evidence_ui.py                      # 37    (evidence + diagram grammar)
python3 tests/query_ui.py                         # 14    (the typed query language)
python3 tests/atlas_ui.py                         # 54    (the atlas)
python3 tests/crce_ui.py                          # 91    (the compass-rose standard)
python3 tests/audit.py                            # 162   (the fundamental audit)
python3 -m app.cli check-integrity                # no structural problems
```

`tests/ui_full.py --shots DIR` redirects its screenshots; `--base URL` points it at another instance.
