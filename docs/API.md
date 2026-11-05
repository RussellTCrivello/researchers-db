# HTTP API

Base URL `http://localhost:8000`. All payloads are JSON unless noted.
Send the acting user in the header `X-Actor: <username>` (defaults to `researcher`);
it is recorded in the audit trail.

Interactive documentation: **http://localhost:8000/docs** (OpenAPI) and `/redoc`.

**Optional token auth.** Set `SIRAJ_API_TOKEN=<token>` before starting the server and every
`/api/*` call must then send `Authorization: Bearer <token>` (the static shell and `/api/health`
stay open so the app can load and report its state). Leave the variable unset for local use —
`GET /api/metrics` reports whether auth is active.

## Conventions

* Success: `200` + body. Domain errors: `404` (missing), `409` (conflict/duplicate/stale version),
  `422` (validation), `413` (file too large).
* Errors look like `{"error": "…", "type": "ValidationError"}`. Validation errors on create/update
  may return a map of `field → message`.
* Entity endpoints are generic: replace `{entity}` with `person | place | institution | event |
  relationship | source`.

## Meta

| Method | Path | Purpose |
|---|---|---|
GET | `/api/health` | liveness, DB path, schema version
GET | `/api/meta` | entities + fields + **derived fields** + vocabularies + locales + users + settings + sequences + `view_modes` (drives the whole UI)
GET | `/api/lookups?domain=` | vocabulary values (flat when `domain` is given)
GET | `/api/lookup-domains` | the help tables themselves, with counts
POST/PUT/DELETE | `/api/lookups[/{id}]` | manage vocabulary values (system values are deactivated, not deleted)
GET | `/api/tags?domain=` · POST `/api/tags` · DELETE `/api/tags/{id}` | specialisations / expertise (`used` = how many records carry the tag; deleting a tag also clears its links)
GET | `/api/options/{entity}?q=&limit=&ids=` | picker options for the searchable drop-downs: `{id, code, label, label_ar, hint, image, type}`; `ids=1,2,3` rehydrates selected values, `q` searches code + both labels (Arabic-normalised)
GET | `/api/locales` · `/api/locales/{code}/messages` | UI languages and bundles

## Records (generic)

| Method | Path | Notes |
|---|---|---|
POST | `/api/{entity}/query` | list with the full filter engine (body below)
GET | `/api/{entity}?q=&page=&page_size=&sort=&order=&include_deleted=` | simple listing
GET | `/api/{entity}/next-code` | preview of the next identification number
POST | `/api/{entity}/kpi` | headline figures for a selection: `{tiles:[{key, value, unit, label_en, label_ar, derived?, tone?}]}` — records in view, average completeness, below-50 % count, recently updated, related-table totals
GET | `/api/{entity}/duplicates?limit=&offset=` | duplicate candidates: `{entity, groups:[{key, count, records[{id, code, title, updated_at, completeness, deleted_at}]}], total}` — names colliding after Arabic normalisation, paged, one SQL statement (835 person groups in ~190 ms)
POST | `/api/{entity}/{id}/merge` | `{merge_ids, reason, dry_run}` → plan/result: `fields_filled`, `merged`, `links_moved`, `relationships_moved`, `duplicate_links_removed`, `self_links_removed`, `keep`. A duplicate link is the *same pair with the same type*; every re-pointed or dropped link is written to the change log
POST | `/api/{entity}` | create (validation + numbering + audit)
GET | `/api/{entity}/{id}?include_deleted=` | full record: labels, refs, tags, positions, relationships, citations, attachments, history
PUT / PATCH | `/api/{entity}/{id}` | update (field-level diff → audit). Send `_version` for optimistic locking
DELETE | `/api/{entity}/{id}?reason=&hard=` | soft delete (default) or hard delete (admin). A hard delete also removes every dependent row — relationships (plus their index documents), tags, citations, identifiers, attachments, positions — nulls typed references elsewhere, and returns `dependents_removed`
POST | `/api/{entity}/{id}/restore` | undo a soft delete
POST | `/api/{entity}/bulk` | `{ids:[…], action:"delete|restore|status|update", patch:{…}, reason:"…"}`
GET | `/api/{entity}/{id}/history` | change log for one record
POST | `/api/{entity}/{id}/citations` | `{source_id, note?, field_key?}`
DELETE | `/api/citations/{link_id}` | remove a citation
GET/POST | `/api/{entity}/{id}/external-ids` · DELETE `/api/external-ids/{id}` | VIAF / Wikidata / ORCID / legacy numbers
POST | `/api/{entity}/{id}/attachments` (multipart: `file`, `kind`, `note`) | upload
GET | `/api/attachments/{id}/download` · DELETE `/api/attachments/{id}` | download / delete

### Write payload

```json
{
  "name_ar": "أحمد بن سالم الحسيني",
  "name_en": "Ahmad b. Salim al-Husayni",
  "birth_date": "1912",
  "nationality_id": "IQ",
  "classification_id": "historian",
  "affiliated_institution_id": "INS-0004",
  "tags": ["Modern Iraqi history"],
  "positions": [{"title_ar":"مدرس","title_en":"Teacher","institution_id":4,
                 "start_date":"1940","end_date":"1955"}],
  "_reason": "added from the 1968 staff list",
  "_source_id": 3,
  "_version": 1
}
```
Vocabulary fields accept the id, the code or a label (English or Arabic); foreign keys accept the id
or the record code. `_reason` and `_source_id` are written to the audit trail.

### Filter engine (`/query`)

```json
{
  "q": "الموصل",                                   // Arabic-normalised full-text (prefix match)
  "where": [
    {"field": "birth_date", "op": "between", "value": [1880, 1950]},
    {"field": "nationality_id", "op": "in", "value": [1, 3]},
    {"field": "death_date", "op": "is_null"},
    {"field": "name_ar", "op": "contains", "value": "الحسيني"},
    {"field": "affiliated_institution_id", "op": "eq", "value": 4}
  ],
  "logic": "and",                  // "or" to union the clauses
  "tag_ids": [1, 4],
  "status_ids": [3, 4],
  "include_deleted": false,
  "sort": "birth_date", "order": "asc",
  "page": 1, "page_size": 25
}
```

Operators: `eq ne gt gte lt lte in not_in between contains not_contains starts ends equals
is_null not_null year_eq year_gte year_lte on before after`.
Text operators are Arabic-normalised (`norm(col) LIKE ?`); date operators run through `ts_of()`,
which expands whatever precision the record holds downwards, so
`{"field":"birth_date","op":"year_gte","value":1950}` works on `c. 1952` **and**
`{"field":"event.start_date","op":"after","value":"1950-05-12 12:00"}` compares real moments:
a bare year, a month, a day and a timestamp all sort and compare on the same timeline.
Unknown fields/operators never break a page: they are returned in `warnings` (so saved views do not
rot).

### Fields derived from related tables

Any key listed in `meta.derived[entity]` may be used in `where`, `sort` and `columns`:

```json
{"where": [{"field": "relationships_count", "op": "gte", "value": 2}],
 "sort": "completeness", "order": "desc"}
```

Available per entity (see `meta.derived` for the exact list and the SQL of each): counts of
relationships, positions, citations, source links, participants, children, institutions and
persons-born; institution/country/place names reached through a foreign key; `birth_year`,
`death_year`, `age_at_death`, `duration_years`, `year`; and `completeness` (percentage).
`/api/meta` exposes each derived field's `expr` so an auditor can see how a number was produced.

Values coming from the browser are always strings, so numeric/vocabulary comparisons are coerced
to the column's SQL type before the query runs — `"value": "1"` and `"value": 1` behave
identically, including for vocabulary ids stored in TEXT columns (e.g. `birth_precision`).

Response: `{items, total, page, pages, page_size, columns, warnings}`; each item carries
`_title`, `_labels` (vocabulary labels + colour), `_refs` (resolved foreign keys) and `_derived`
(the computed values of that record).

## Search

`GET /api/search?q=&entity=&limit=` → grouped hits across entities with a snippet:
```json
{"q":"الموصل","total":3,"groups":[
  {"entity":"place","label_en":"Places","items":[{"id":2,"code":"PLC-0002","title":"الموصل","snippet":"…"}]}]}
```

### Filters in two shapes

`/query` (and every endpoint that accepts `where`) takes either explicit clauses:

```json
{"where":[{"field":"record_status_id","op":"eq","value":"verified"}],"logic":"and"}
```

or the compact mapping form, which is translated before the query runs:

```json
{"filters":{"record_status_id":"verified","completeness":{"gte":50},"name_ar":{"contains":"محمد"}}}
```

Sample the same field as a **code or a label** (`"verified"`, `"Verified"`) — the repository resolves
it to the vocabulary id for `select` fields, so a hand-written filter never silently returns nothing.
Every operator in the alias table is implemented and tested (the audit iterates the whole table):

| Family | Operators |
|---|---|
| comparison | `eq`/`=`/`is` · `ne`/`!=`/`<>` · `gt` `gte` `lt` `lte` (and `>` `>=` `<` `<=`) |
| membership | `in` · `not_in` · `between` · `not_between` |
| text (Arabic-normalised) | `contains` · `not_contains` · `starts`/`startswith` · `ends`/`endswith` · `equals` |
| presence | `is_null` · `not_null` · `empty` (null *or* blank after trimming) · `not_empty` |
| dates | `year_eq` · `year_gte` · `year_lte` (the year inside a value of any precision) |
| moments | `on`/`on_day` (the whole calendar day, times included) · `before`/`until` · `after`/`since` · `between` (moment-aware) |

Date semantics — the one rule worth remembering:

* a date is stored exactly as precisely as it is known (`1950`, `1950-05`, `1950-05-12`,
  `1950-05-12T21:45`, and the legacy research forms `c. 1850`, `1850s`, `1850?`);
* every comparison goes through `ts_of()`, which fills the gaps downwards
  (`1950` → `1950-01-01 00:00:00`), so mixed precisions compare correctly;
* `between` with a bare day upper bound includes that whole day
  (`1947-01-01 … 1947-12-31` includes 31 December 23:59), a time-bearing bound is an exact `<=`;
* a value that cannot be a date is a `warnings` entry and the clause is skipped — never a 500.

An unknown field or operator returns a `warnings` entry rather than an error, so a stale saved view
degrades instead of breaking the page. Structural keys (`where`, `q`, `sort`, `logic`, `tag_ids`,
`status_ids`, `only_ids`) may appear at the top level *or* inside `filters` — both are equivalent.
Field names are never treated as structure: `title`, `lang` and `format` are real columns here.

## Queries as text

A saved filter is a JSON document, which cannot be pasted into an e-mail or read
back next year. The same filters can be written as a query string and compiled by
the server into the payload the engine already understands.

| Method | Path | Notes |
|---|---|---|
POST | `/api/query/parse` | `{entity, query}` → `{echo, payload, warnings, unknown}`. Compiles without running anything; an unclosed quote is `422` |
GET | `/api/query/parse?entity=person&q=…` | the same, for a link |
POST | `/api/query/render` | the inverse: `{entity, payload}` → `{query, unsupported}` — used to write the current filters back out as text |
POST | `/api/{entity}/query` with `"query"` | runs the query; the response carries `_query: {echo, warnings}`. Explicit body keys still win (page, page_size), so a client can pin paging |

```
status:published birth:1900..1930 tag:"early cinema" -country:EG sort:-birth_date limit:20
"ابن سينا" OR "Avicenna"
```

| written | means |
|---|---|
| `word` | full-text term (Arabic-normalised) |
| `field:value` | equality; vocabulary **codes and labels** are accepted |
| `field:>n` `>=` `<` `<=` | comparison |
| `field:a..b` | inclusive range |
| `field:a\|b` | any of a list |
| `-field:value` | negation |
| `field:null` / `notnull` | empty / present |
| `tag:name` · `status:code` | specialisation · editorial status |
| `sort:field` · `sort:-field` | ordering |
| `limit:n` · `page:n` | paging |
| `OR` (or `أو`) | joins field filters with OR instead of AND |

Two rules keep it honest: an **unknown field is reported and dropped** (same
contract as the filter engine, so a stale saved query never breaks a page), and
**`OR` between bare words is refused with an explanation** rather than quietly
returning the wrong rows.

In the interface the query bar sits beside the search box; applying a query clears
the builder's clauses (two spellings of one filter must never disagree), the bar
echoes how the query was read, and the address bar carries `?q=…` so a view can be
sent to a colleague.

## Reports

| Method | Path |
|---|---|
GET | `/api/reports` — catalogue
GET/POST | `/api/reports/{key}` — `overview quality institutions geography network timeline sources workflow indicators custom`
GET | `/api/reports/{key}/export?format=xlsx|csv|json&params={json}`

Report envelope: `{key, title_en, title_ar, description_*, generated_at, params, summary[],
sections[{id,type,title_*,columns[],rows[]}]}` where `type ∈ table|bar|pie|timeline|matrix`.

Custom pivot body:
```json
{"params":{"entity":"person","group_by":"nationality_id","metric":"count","chart":"pie",
           "filters":{"where":[{"field":"birth_date","op":"year_gte","value":1900}]}}}
```

## Relationship graph

| Method | Path | Notes |
|---|---|---|
POST/GET | `/api/relationship-map` | `{"mode":"types","include_structural":true}` → `{nodes, edges, matrix, matrix_order, matrix_undirected, relationship_types, totals}`; `{"mode":"focus","entity_type","record_id","depth":1|2,"limit":5..120}` → `{nodes, edges, focus, depth}`. Edge `kind ∈ relationship \| structural`. See [`GRAPH.md`](GRAPH.md) |
GET | `/api/graph/node/{entity_type}/{record_id}` | The dossier behind one node of the atlas: `{type, id, record_id, code, title, label_en, label_ar, href, state{record_status, authentication, documentation}, facts[], counts{relationships, by_type, evidence}, neighbours[≤12], evidence[], completeness}`. `404` for an unknown type or id. This is what the side panel renders — it is deliberately one request, so a selection never costs a page. |
POST | `/api/graph/path` | `{from_type, from_id, to_type, to_id, max_depth≤8}` → `{ok, found, length, nodes[], edges[], exhausted, searched}`. Breadth-first over stored relationships only; every edge carries its own verification and dates so a chain can be read without inventing certainty. `404` if an endpoint does not exist, `422` for a malformed body. |

**Why the graph has two more endpoints than the diagram strictly needs.** The
diagram could have shipped every panel from data it already held, but it would
then have been a picture of the data rather than a reading of it: the dossier
resolves fields into readable facts, keeps status, verification and
documentation apart, and states how complete a record is. The path finder
answers the one question a picture cannot — *are these two people connected at
all, and by what* — and says how much of the graph it searched before saying no.

## CRCE — the compass-rose coordinate encoding

One encoding for every spatial reference, served as data so that every surface
draws the same thing. See [`CRCE.md`](CRCE.md).

| Method | Path | Notes |
|---|---|---|
GET | `/api/crce/standard` | The standard: `{standard{id, version, name_en, name_ar, summary_*, storage_crs, box, reserved[], uncovered[]}, symbols{category{id, category, label_en, label_ar, means_*, exclusive, geometry[]}}, categories{record_kind → category}, roles{code{en, ar}}, rules[{code, en, ar}]}`. The four reserved marks are `crce-person`, `crce-organization`, `crce-place`, `crce-relationship`; `event` and `source` are declared uncovered. |
GET | `/api/crce/dossier/{entity_type}/{record_id}` | One record's full CRCE dossier in the published field order: `{standard, entity{name_*, code, category, symbol, covered_by_standard, href}, status, coordinates{primary{lat,lon,axis,unit,crs}, formats{decimal_degrees, dms, crs84, web_mercator, geohash_note_*}, precision, uncertainty_m, method, source, role{code,en,ar}, place, inherited}, orientation{bearing_deg, code, en, ar, distance_m, phrase_*, reference{kind, conceptual, label_*, lat, lon}}, relative{inside, parent}, rose{symbol, state, needle, rotation_deg, rings, ticks, letters, exclusive}, relations[], notes[{code, level, en, ar}], ends[] and ends_coincident for relationships}`. Aliases: `organization`/`organisation` → institution, `people` → person, `location` → place. `404` for an unknown category or a missing record — a dossier is never assembled from guesses. Uncovered kinds answer with `symbol: null` and a `not_covered` note. |

**Why a dossier instead of formatted strings.** The point of the standard is
that *every* surface — the record page, the atlas node, the geographic marker,
the exported SVG — draws the same geometry from the same numbers. Formatting
server-side would have made the standard a set of strings; the dossier returns
the roles, precisons, notes and reference points as data, and
`app/static/js/components/crce.js` is the single interpreter.

## Structures — the display kernel's data

Two read-only routes feed the structure deck (`#/structures`, six structures over
one model). Counts are database counts, computed level by level; a level is
folded into a declared aggregate rather than truncated.

| method | path | notes |
|---|---|---|
GET | `/api/structures` | `{ok, sources[{id, entity, label_en, label_ar, note_en, note_ar, total, chain[{en, ar}]}], max_depth, max_children}`. Six sources: `people`, `institutions`, `places`, `relationships`, `sources`, `events`.
GET | `/api/structures/{source}?depth=3&max_children=24` | `{ok, source, chain[{key,label_en,label_ar}], depth, max_children, root{id,label_en,label_ar,value,children[],meta}, total, computed_ms, cached}`. `depth` 1–4, `max_children` 3–40. Children of a node always add up to that node; a folded branch is `meta.synthetic` with `count` and `folded`. Unknown source → `404`; an ungroupable field → `422` with the reason. Short-lived server cache: `cached` says when it was used.

## Evidence — one source, many claims

A citation is not a bibliography entry. It says *this* source says *this* about *that*,
so it can sit on an entity, on one of its fields, or on a relationship row.

| Method | Path | Notes |
|---|---|---|
GET | `/api/evidence?entity_type=&entity_id=` | every claim attached to a record → `{evidence, count, counts:{supports,contradicts,contextualizes}, disputed, support_types}`. Contradictions are listed **first** |
GET | `/api/evidence?relationship_id=` | the same, for a relationship row. Asking for both targets → `422`; asking for none → `422` |
GET | `/api/evidence/support-types` | the controlled list (`supports` · `contradicts` · `contextualizes`) with both labels — never hard-code the three words |
POST | `/api/evidence` | `{source_id, entity_type, entity_id \| relationship_id, field_key?, supported_claim?, page_or_timestamp?, support_type?, verification?, reviewer?, review_date?, note?}` → `{ok, evidence_id, created}`. Exactly one target: two targets, no target, an unknown support type, or a source that does not exist → `422`/`404`. Re-posting the identical claim is **not** an error: `created:false` and the existing row is returned |
GET | `/api/relationship/{rel_id}/evidence` | the relationship with its evidence: `{…type_en, entity1_id, …, count, counts, disputed, evidence}` |
DELETE | `/api/citations/{id}` | withdraws one claim (legacy path name; the row is an evidence row). The source itself is untouched |

Each evidence row carries **two independent assessments**:

```json
{"support_type": "contradicts", "supported_claim": "dated to 1991, not 1987",
 "page_or_timestamp": "f. 12v", "field_key": "death_date",
 "verification_code": "single_source", "verification_en": "Single source",
 "reliability_code": "high",          "reliability_en": "High",
 "reviewer": "reviewer", "review_date": "2026-11-02", "source_id": 3208}
```

`reliability_*` describes **the source**; `verification_*` describes **this claim**. A record-level
`GET /api/{entity}/{id}` still exposes the same rows as `citations`, so the older screens keep
working, and `disputed` is true whenever a contradiction is present — a disagreement is kept,
never overwritten.

## Dashboard, audit, admin

| Method | Path | Purpose |
|---|---|---|
GET | `/api/dashboard` | KPI cards, distributions, 12-month activity, coverage, recent changes
GET | `/api/changelog?entity_type=&entity_id=&actor=&action=&date_from=&date_to=&q=&page=` | audit trail
GET | `/api/settings` | the configuration in force: `{settings, fields, groups, overrides, schema_version}` — a flat `settings` map plus, per key, its type, declared default, bounds/allowed values, bilingual label and help, the code path that honours it, its source (`default` \| `instance`) and when it last changed. Also embedded in `/api/meta`
GET | `/api/settings/schema` | the registry alone (`{fields, groups}`), no database access — cacheable, and the authoritative list of keys
PUT | `/api/settings` | validated, audited write of one or more keys: `{"display.page_size": 50}` → `{ok, changed: [{key, old, new}], settings}`. **All-or-nothing**: any unknown key, wrong type or out-of-range value → `422` `{problems: [{key, reason, message, minimum…}]}` and nothing is written. One `change_log` row per key (`entity_type=setting`)
POST | `/api/settings/reset` | drop overrides and return to the declared defaults: `{"keys": [...]}`, `{"group": "transfer"}` or `{}` for everything → `{ok, reset, changed, unknown, settings}`; audited (a reset writes a `change_log` row only where the value actually changed)
GET | `/api/sequences` · PUT `/api/sequences/{entity}` | numbering rules and next value
GET/POST | `/api/users` · DELETE `/api/users/{username}` · GET `/api/locales` | actors and languages (the last administrator cannot be removed → `409`)
GET/POST/DELETE | `/api/saved-views[/{id}]` | filter presets
POST | `/api/maintenance/reindex` · `/vacuum` | rebuild FTS index · compact database
GET | `/api/maintenance/backup?include_files=true` | consistent SQLite snapshot **plus every uploaded file** (`uploads/`) in one ZIP, with a manifest
GET | `/api/metrics` | record counts per entity, recycle-bin size, change-log volume, FTS documents, DB size, `token_auth` flag
POST | `/api/maintenance/prune` | `{"days": N, "dry_run": true}` — trims the change log to `audit.retention_days`; refuses while the setting is `0` (keep everything), and records what it removed
GET | `/api/maintenance/export-all` | full JSON dump of every table

## Media (images for cards and galleries)

| Method | Path | Notes |
|---|---|---|
POST | `/api/media` | multipart `file`; images only (png/jpg/webp/gif/avif/svg), ≤ 12 MB → `{url, filename, size_bytes, mime}`; the returned `url` goes straight into `image_url`
GET | `/api/media/{name}` | serves the stored image with a long cache header

## Saved views

| Method | Path | Notes |
|---|---|---|
GET | `/api/saved-views?entity_type=` | saved browsing state (filters, columns, sort, view/layout)
POST | `/api/saved-views` | `{name, entity_type, filters, columns, sort: {view, layout}}` → `{ok, id, view}` (re-selects the stored row, so the client gets the id it must use for later updates/deletes)
DELETE | `/api/saved-views/{id}` | remove a view

## Import / export

| Method | Path |
|---|---|
GET | `/api/import/template/{entity}?format=xlsx|csv|json&lang=ar|en|both`
POST | `/api/import/preview` (multipart `file` + `entity`)
POST | `/api/import/validate` · `/api/import/commit` (`{entity, upload_id, mapping, mode, default_status}`)
GET | `/api/import/jobs` · `/api/import/jobs/{id}`
GET | `/api/export/{entity}?format=&columns=&lang=&resolve=`
POST | `/api/export/{entity}` — body is the full list payload plus `format`/`columns`/`lang`/`resolve`/`title`

Both export endpoints return **every** matching row: the 1 000-row page guard that protects the
browser does not apply, rows are read in internal pages of 1 000, and `MAX_ROWS = 50 000` is a hard
ceiling that fails with `422` instead of quietly shortening the file. Filters are applied exactly as
the list applies them — `{"format":"xlsx","filters":{…}}` and `{"format":"xlsx","where":[…]}` both
work, and `tests/audit.py` asserts the exported row count equals the list total.

## Geographic surface

The map is a view over the registry: every feature it draws is a record, and every
query is read-only. Full design notes in [MAP.md](MAP.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/map/config` | providers (with attribution, licence and terms), CRS catalogue, initial view, limits, layer catalogue, basemap inventory |
| GET | `/api/map/layers` | the mappable layers with `located` / `total` counts |
| GET | `/api/map/features?bbox=&zoom=&layers=&filters=&limit=` | points for one viewport — bounded, counted, never invented |
| GET | `/api/map/groups?bbox=&zoom=&layers=&filters=&limit=` | per-place aggregates: how many records, of which kinds |
| GET | `/api/map/overlays?layers=` | GeoJSON arcs from relationships and from the place tree |
| GET | `/api/map/feature/{type}/{id}` | one record's geographic dossier (DD, DMS, EPSG:3857, anchor, containing country polygon, located relationships, sources) |
| GET | `/api/map/search?q=` | one box for a name **or** a coordinate |
| GET | `/api/map/reverse?lat=&lon=` | containing country, nearest registry places, nearest records |
| GET | `/api/map/parse?q=` | parse a typed coordinate (any common notation) for live validation |
| POST | `/api/map/query` | spatial query: `bbox`, `radius` or `polygon` — identifies records, writes nothing |
| GET | `/api/map/georef/preview` | the georeferencing plan, read-only (`geocode-places` is the only writer) |
| GET | `/api/geo/basemap` | the offline basemap pack and the terms it is used under |
| GET | `/api/geo/basemap/{layer}?zoom=&bbox=&limit=` | one basemap layer as GeoJSON at a detail level chosen from the zoom |
| GET | `/api/geo/gazetteer?q=&country=` | offline city search (English and Arabic names) |
| GET | `/api/geo/nearest?lat=&lon=` | the nearest gazetteer city to a point |

```bash
# what is in this window, bounded to the configured budget
curl -s 'localhost:8000/api/map/features?bbox=38,29,48,38&zoom=6'
# a radius query around a coordinate
curl -s -X POST localhost:8000/api/map/query -H 'Content-Type: application/json' \
     -d '{"mode":"radius","lat":33.3152,"lon":44.3661,"radius_m":25000,"limit":100}'
# a DMS coordinate, validated before it is used
curl -s 'localhost:8000/api/map/parse?q=33%C2%B018%2754.7%22N%2044%C2%B021%2758.0%22E'
```

Failure modes are explicit: `422` for a malformed bbox, an unknown layer, an
out-of-range coordinate or a bad polygon; `404` for a record that does not exist;
`503` when the local basemap pack has not been built.

## Configuration, step by step

```bash
# 1. what is configurable, and what it is set to right now
curl -s localhost:8000/api/settings \
  | jq '{overrides, keys: [.fields[] | {key, value, source}]}'

# 2. one value, the flat map the browser reads
curl -s localhost:8000/api/settings | jq -r '.settings["ui.form_mode"]'

# 3. change something — validated and audited
curl -s -X PUT localhost:8000/api/settings \
     -H 'Content-Type: application/json' -H 'X-Actor: admin' \
     -d '{"validation.min_completeness": 40}'
# → {"ok":true,"changed":[{"key":"validation.min_completeness","old":"0","new":"40"}],"settings":{…}}

# 4. a refusal changes nothing
curl -s -o /dev/null -w '%{http_code}\n' -X PUT localhost:8000/api/settings \
     -H 'Content-Type: application/json' -d '{"display.page_size": 9999}'
# → 422   {"problems":[{"key":"display.page_size","reason":"above_maximum","maximum":500,…}]}

# 5. back to the shipped policy, and the audit trail that proves it happened
curl -s -X POST localhost:8000/api/settings/reset \
     -H 'Content-Type: application/json' -d '{"group":"quality"}'
curl -s 'localhost:8000/api/changelog?entity_type=setting&page_size=5' | jq '.rows[0]'
```

Full reference — every key, its consumer, the four layers of configuration and every way to change
them: [`SETTINGS.md`](SETTINGS.md).

## Examples

```bash
# create, read, update with audit reason
curl -s -X POST localhost:8000/api/person -H 'Content-Type: application/json' \
  -H 'X-Actor: reviewer' -d '{"name_ar":"سجل جديد","classification_id":"researcher"}'
curl -s localhost:8000/api/person/25
curl -s -X PUT localhost:8000/api/person/25 -H 'Content-Type: application/json' \
  -d '{"name_en":"New","_version":1,"_reason":"translation added"}'

# deep query: historians born between 1880 and 1930 affiliated with institution 1
curl -s -X POST localhost:8000/api/person/query -H 'Content-Type: application/json' -d '{
 "where":[{"field":"classification_id","op":"eq","value":"historian"},
          {"field":"birth_date","op":"between","value":[1880,1930]},
          {"field":"affiliated_institution_id","op":"eq","value":1}]}'

# import a file in three calls
curl -s -F entity=person -F file=@samples/persons-import.csv localhost:8000/api/import/preview
curl -s -X POST localhost:8000/api/import/validate -H 'Content-Type: application/json' \
  -d '{"entity":"person","upload_id":"…","mapping":{…},"mode":"upsert"}'
curl -s -X POST localhost:8000/api/import/commit  -H 'Content-Type: application/json' \
  -d '{"entity":"person","upload_id":"…","mapping":{…},"mode":"upsert"}'
```
