# Configuration — every setting, every layer, every method

*The complete reference for configuring a SIRAJ instance: what each setting does, where it is
enforced, who it applies to, and every supported way to read or change it.*

Configuration in SIRAJ is deliberately **not** a bag of key/value pairs that some screens read and
others ignore. Every value the application honours is declared once in a typed registry, enforced in
one place, exposed through one API, rendered by one screen, and audited like any other change to the
registry's data. This document is the map of that system, front to back.

---

## 1 · The four layers, and which one wins

A running instance is configured at four levels. They are resolved in this order, and each one is
owned by a different person:

| Layer | Lives in | Changed by | Wins over | Typical use |
|---|---|---|---|---|
| **Deployment** | environment variables (`SIRAJ_HOST`, `SIRAJ_PORT`, `SIRAJ_DATA_DIR`, `SIRAJ_DB`, `SIRAJ_API_TOKEN`, `SIRAJ_SEED_DEMO`) | the operator, before start-up | everything below | where the app listens, which file is the database, whether a token is required |
| **Instance configuration** | `setting` table in the database; served by `/api/meta` and `/api/settings` | an administrator, in **Settings**, or through the API | the shipped defaults | policy: validation rules, import/export ceilings, audit retention |
| **Personal preferences** | `localStorage` in one browser | the person using that browser | instance configuration *(for the eight settings marked `personal`)* | theme, density, rows per page, where forms open, pop-up width, inline create, the two search thresholds (the visitor's language and actor name are browser state, not settings — §6) |
| **Per-request / per-action** | query parameters and request bodies (`?include_deleted=`, `{"hard": true}`, export `columns`) | the caller | all of the above for that one request | a one-off export, a one-off hard delete |

Two consequences worth stating plainly:

* **A personal preference never changes the instance.** Pressing *"Use for me only"* writes
  `localStorage`; nothing is sent to the server, nobody else is affected.
* **The shipped default is not a stored value.** The `setting` table stores *overrides*. A key with
  no row reports its declared default, so `/api/settings` always answers with a complete
  configuration and an upgrade that improves a default also improves existing installations.

---

## 2 · The registry: one declaration, four readers

`app/settings.py` is the single source of truth. Each setting is a frozen dataclass:

```python
Spec("display.page_size", "display", "int", "25",
     "Rows per page", "عدد الصفوف في الصفحة",
     help_en="How many records a list loads at a time …",
     help_ar="عدد السجلات التي تُحمَّل في المرة الواحدة …",
     minimum=5, maximum=500, personal=True,
     effect="core.js pageSize() → views/list.js")
```

| Field | Meaning |
|---|---|
| `key` | the dotted name, also the `setting.key` and the change-log `entity_code` |
| `group` | one of the eight groups the screen renders (`display`, `entry`, `search`, `transfer`, `quality`, `audit`, `maintenance`, `map`) |
| `kind` | `bool` · `int` · `decimal` · `enum` · `text` — decides validation, the control on screen, and the JSON type |
| `default` | the shipped value, always stored as a canonical string (`"true"`, `"25"`) |
| `values` | for `enum`: the allowed set. The first entry is the recommended one |
| `minimum` / `maximum` | for `int` and `decimal`: inclusive bounds, enforced on write *and* advertised to the screen |
| `personal` | may one browser override it? (sixteen of the twenty-seven can) |
| `effect` | **the code path that honours it** — an entry without one is a lie in a settings screen, and a test refuses it |
| `requires` | `restart` when the value is only read at boot |

Everything else is derived from that declaration:

1. **`GET /api/settings/schema`** returns the registry itself (no database access — safe to cache).
2. **`GET /api/settings`** returns the registry *plus* the value in force, where it came from, and when
   it was last changed.
3. **`PUT /api/settings`** validates through the same objects; an unknown key or a value outside its
   declared type/range is refused before anything is written.
4. **The Settings screen** renders itself: one control per `kind`, the help text in the active
   language, the default, the source badge, a reset button, and the `effect` line so an administrator
   can see what they are about to change.
5. **Consumers** call `settings.get(conn, "key")`, which returns the typed value or the declared
   default. No consumer parses strings or knows a default.

Three invariants are pinned by tests (`tests/test_registry.py`):

* every declared key has a non-empty `effect` (nothing decorative);
* every key appears in `/api/settings`, `/api/settings/schema` and the screen;
* `int` values are inside `minimum…maximum` and `enum` values are inside `values`, at all times.

---

## 3 · Every setting, in full

### 3.1 Display & appearance (`display.*`)

| Key | Type | Default | Range / values | Scope | Read by |
|---|---|---|---|---|---|
| `display.theme` | enum | `light` | `light` · `dark` · `system` | instance **or personal** | `app.js` → `applyAppearance()` → `<html data-theme>` |
| `display.density` | enum | `comfortable` | `comfortable` · `compact` | instance **or personal** | `core.js` → `list.js` table class + CSS |
| `display.page_size` | int | `25` | 5 – 500 | instance **or personal** | `core.js pageSize()` → `views/list.js` |
| `display.default_language` | enum | `ar` | `ar` · `en` (any active locale code) | instance | `app.js boot()` → first paint |

**`display.theme`.** `light` and `dark` set `data-theme` on `<html>`; the whole palette is CSS
variables, so every screen, table, dialog and report follows. `system` follows the operating system
and *keeps* following it — a `matchMedia` listener re-applies the theme when the OS switches at
sunset, without a reload. The topbar toggle writes a personal value (it never changes the instance),
and clearing the personal preference returns the browser to the instance theme.

**`display.density`.** `compact` adds `.density-compact` to `<body>`, which tightens table cell
padding and card padding — about a third more rows on a 1080-p screen. It is a display-only change:
no data is affected, and exports are identical either way.

**`display.page_size`.** The number of rows a list loads per page, and the increment "Load more" uses.
It is capped at 500 on purpose: a page size of 10 000 turns a list into an accidental export and
makes the sticky header useless. Consumers of the whole table should use **Export**, which has its own
ceiling (`export.max_rows`).

**`display.default_language`.** What a **first** visit opens in. A visitor who has chosen a language
(the topbar toggle) stores it in `localStorage` and that choice always wins. Only codes that exist in
the `locale` table and have a bundle in `static/js/locales/` are meaningful; see §9.

---

### 3.2 Data entry (`ui.*`)

| Key | Type | Default | Range / values | Scope | Read by |
|---|---|---|---|---|---|
| `ui.form_mode` | enum | `page` | `page` · `dialog` · `auto` | instance **or personal** | `core.js formMode()` → `views/record.js openFormDialog()` |
| `ui.form_dialog_size` | enum | `xl` | `wide` · `xl` | instance **or personal** | `core.js formDialogSize()` → `modal({size})` |
| `ui.inline_create` | bool | `true` | — | instance **or personal** | `components/fields.js` → `combobox({allowCreate})` |

**`ui.form_mode`.** One decision for every create/edit surface in the product: full page, pop-up
window over the list/dossier, or automatic (pop-up from 960 px wide, page below). Full behaviour
contract in [PHASE6.md](PHASE6.md). Nothing else in the application needs to know about it — the form
shell renders both surfaces.

**`ui.form_dialog_size`.** `xl` (the two-column form layout, recommended for the nine-section person
form) or `wide` (a narrower single-column feel, better on a 13-inch laptop).

**`ui.inline_create`.** On, every related-record field offers *"create new …"* so a researcher never
has to leave a form to add a missing place, institution or source. Off, the vocabulary is **closed**:
only existing records can be linked, and the button disappears. Choose *off* when the controlled
vocabularies are curated by data stewards and ad-hoc records are a quality problem.

---

### 3.3 Search & filtering (`search.*`)

| Key | Type | Default | Range | Scope | Read by |
|---|---|---|---|---|---|
| `search.min_chars` | int | `2` | 1 – 5 | instance **or personal** | search view → `/api/search` |
| `search.results_limit` | int | `20` | 5 – 100 | instance **or personal** | search view → `/api/search?limit=` |

`search.min_chars` is a cost control: full-text search over the whole registry is fast, but a
one-character query matches most of the corpus and is never useful. Below the threshold the interface
tells the user how many characters it needs instead of firing the request. `search.results_limit` is
how many hits the panel shows per group before offering "more".

---

### 3.4 Import & export (`import.*`, `export.*`)

| Key | Type | Default | Range / values | Scope | Read by |
|---|---|---|---|---|---|
| `import.max_rows` | int | `20000` | 100 – 500 000 | instance | `POST /api/import/commit` → 422 |
| `import.default_mode` | enum | `create` | `create` · `update` · `upsert` | instance | import commit default + wizard |
| `export.max_rows` | int | `50000` | 1 000 – 500 000 | instance | `transfer.export_bytes()` ceiling |

**`import.max_rows`.** Checked **before a single row is written**: a staged file with more rows than
the ceiling is refused with the measured count and the configured ceiling. This is the difference
between a bad file and a stalled registry — a 400 000-row commit holds a write transaction for
minutes and blocks every other writer.

**`import.default_mode`.** What the wizard starts with. `create` never touches an existing record;
`update` only touches matched ones; `upsert` does both. The mode is also recorded per job
(`import_job`), so a reviewed import can be explained later.

**`export.max_rows`.** The hard ceiling for one export. Above it the export **fails loudly** with the
row count and the setting name — it never writes a silently shortened file. Raise it for an archival
extraction, lower it on a shared server; either way the reason a file is refused is visible.

---

### 3.5 Validation & data quality (`validation.*`)

| Key | Type | Default | Range | Scope | Read by |
|---|---|---|---|---|---|
| `validation.require_source_on_publish` | bool | `true` | — | instance | `repo.create_record()` / `update_record()` → 422 |
| `validation.min_completeness` | int | `0` | 0 – 100 | instance | `repo._quality_gate()` → 422 |
| `validation.require_reason_for_delete` | bool | `false` | — | instance | `repo.soft_delete()` / `hard_delete()` / `merge_records()` → 422 |

These are the *policy* settings: they decide what the registry refuses, and every one of them is
enforced server-side, so the API and the browser obey the same rules.

**`validation.require_source_on_publish`** (on by default). A record cannot move to a
`published`/`verified` status while it has no citation and no primary source. The check runs on
creation and on update, against the state the record is *about to have* — so a draft can be
backfilled freely, and the refusal happens exactly at the moment a claim becomes public. The error
names the record, the status and the setting, and tells the caller what to do:

```
422  Cannot set Person to 'published': it has no source. Attach a citation
     (POST /api/person/{id}/citations) or set its primary source first —
     validation.require_source_on_publish is on.
```

**`validation.min_completeness`** (`0` = off). Above zero, publishing a record whose derived
completeness is below the floor is refused, with the current percentage and the required one in the
message. Completeness is the same figure the dossier ring and the KPI strip show, so the number a
curator sees is the number that blocks them.

**`validation.require_reason_for_delete`** (off by default). Deletes, hard deletes and merges must
carry a reason; the reason is written to the audit trail with the actor. Turn it on wherever "why did
this record disappear?" is a question that gets asked.

---

### 3.6 Audit & retention (`audit.*`)

| Key | Type | Default | Range | Scope | Read by |
|---|---|---|---|---|---|
| `audit.retention_days` | int | `0` | 0 – 36 500 | instance | `POST /api/maintenance/prune` |

`0` means **keep the audit trail forever** — the safe answer, and the default. Above zero,
`POST /api/maintenance/prune` removes change-log rows older than that, and the endpoint refuses to run
while the setting is 0, so an audit trail can never be lost by clicking a button. The prune itself is
auditable: it writes a change-log entry naming the retention period used and the number of rows
removed. `{"days": N, "dry_run": true}` previews the count without deleting anything.

---

### 3.7 Maintenance & backups (`maintenance.*`)

| Key | Type | Default | Scope | Read by |
|---|---|---|---|---|
| `maintenance.backup_includes_files` | bool | `true` | instance | `GET /api/maintenance/backup` default |
| `maintenance.vacuum_after_import` | bool | `false` | instance | `POST /api/import/commit` |

**`maintenance.backup_includes_files`.** A backup ZIP normally contains the database **and**
`uploads/` (media images, attachments) plus a manifest — a restore is then one artefact, not a
database plus a folder someone forgot. Turn it off only when images live elsewhere or the archive size
matters more than completeness. `?include_files=false` overrides it for a single request.

**`maintenance.vacuum_after_import`.** Runs `VACUUM` once a commit finishes. Slower, but it keeps the
file from ballooning on import-heavy days (SQLite does not return freed pages to the filesystem by
itself).

---

### 3.8 Map & geography (`map.*`)

| Key | Type | Default | Range / values | Scope | Read by |
|---|---|---|---|---|---|
| `map.provider` | enum | `local` | `local` · `osm` · `esri-street` · `carto-light` · `carto-dark` · `esri-imagery` · `esri-hybrid` · `opentopomap` | instance **or personal** | `providers.get()` → `views/geomap.js applyProvider()` |
| `map.center_lat` | decimal | `33.3152` | −90 … 90 | instance **or personal** | `core.js mapDefault()` → geomap initial view |
| `map.center_lon` | decimal | `44.3661` | −180 … 180 | instance **or personal** | `core.js mapDefault()` → geomap initial view |
| `map.zoom` | int | `5` | 1 – 18 | instance **or personal** | `core.js mapDefault()` → geomap initial view |
| `map.max_points` | int | `4000` | 100 – 20 000 | instance | `mapdata.features(limit)` via `GET /api/map/features` |
| `map.cluster` | bool | `true` | — | instance **or personal** | `geomap.js` cluster source (MapLibre supercluster) |
| `map.units` | enum | `metric` | `metric` · `imperial` | instance **or personal** | `spatial.format_distance()` → measure panel |
| `map.show_labels` | bool | `true` | — | instance **or personal** | `geomap.js labelLayer()` |
| `map.overlays` | text | `place_hierarchy` | comma-separated: `relationships`, `place_hierarchy` | instance **or personal** | `api.map_overlays()` → overlay layers |

**`map.provider`.** Eight base maps in four families: **offline** (`local`, the Natural
Earth pack, no network), **standard** (`osm`, `esri-street`, `carto-light`, `carto-dark`),
**aerial** (`esri-imagery`, `esri-hybrid`) and **terrain** (`opentopomap`). Each online
provider carries its attribution, licence and usage terms, and the workspace shows them on
the map — the hybrid shows both of its layers' attributions. A tile failure is announced
with a one-click switch back to the local pack; it never leaves a blank canvas. The
enumeration is validated against this list, so a key written by hand cannot name a provider
that does not exist.

**`map.max_points`.** A budget for **one response**, not one layer: the server counts each
layer first and shares the budget in proportion to what each holds, then reports how much
every layer left out. Raise it on a workstation with a fast GPU; lower it on a shared
server with thin clients. See [MAP.md](MAP.md) §7.

**`map.center_*` / `map.zoom`.** Where the map opens the **first** time. A viewport the
person has moved is stored per browser (`siraj.map_view`) and always wins — this setting
is an initial value, not a lock. The decimals are validated like any other: `95` is
refused with `above_maximum`, `abc` with `not_a_number`, and `"33,3152"` is accepted as
`33.3152`.

**`map.overlays`.** `place_hierarchy` (47 paths on this dataset) is on by default;
`relationships` (1 817 arcs over one country) is deliberately not — it is one click away
in the Layers menu and its weight falls away with zoom instead of disappearing silently.

---

## 4 · The four ways to change a setting

### 4.1 The screen — **Settings** (`#/settings`)

The only route an administrator needs. It is generated from the registry, so it can never be out of
step with the backend:

* **Seven group cards** (Display, Data entry, Search, Import & export, Validation, Audit, Maintenance),
  each headed by *"N settings"* and a **Reset this group** button that appears only when something in
  that group is overridden.
* **One row per key**: the translated label, the dotted key, the explanation, the `effect` line
  ("used by …"), and the control for its type — a toggle (a real switch, keyboard-operable), a select
  for enums (values translated), or a number input with its declared range beside it.
* **A source badge** on every row: `shipped default` or `instance override`, with the default value
  spelled out and a **Reset** button when the two differ.
* **A pending-change bar** that appears the moment a value differs from what is stored: it counts the
  changes, names the keys, explains that nothing is written until you save, and sits sticky at the top.
* **Save** writes **only the changed keys**, in one validated request. A refusal is shown per key, the
  offending row is marked, and *nothing* is applied (see §5).
* **Use for me only** on the eight settings that allow it: stores the value shown as a personal
  preference in this browser and applies it immediately, without touching the instance.
* **Download configuration** saves the whole configuration as JSON (§10).

### 4.2 HTTP API

```bash
# everything, with metadata
curl -s http://127.0.0.1:8000/api/settings | jq '.fields[] | {key, value, source}'

# the registry alone (no database access, cacheable)
curl -s http://127.0.0.1:8000/api/settings/schema | jq '.groups'

# one value, flat map (the shape the browser consumes)
curl -s http://127.0.0.1:8000/api/settings | jq '.settings["display.page_size"]'

# change one or more (X-Actor is recorded in the audit trail)
curl -s -X PUT http://127.0.0.1:8000/api/settings \
     -H 'Content-Type: application/json' -H 'X-Actor: admin' \
     -d '{"display.page_size": 50, "export.max_rows": 100000}'

# back to the declared defaults: one key, one group, or everything
curl -s -X POST http://127.0.0.1:8000/api/settings/reset \
     -H 'Content-Type: application/json' -d '{"keys": ["display.page_size"]}'
curl -s -X POST http://127.0.0.1:8000/api/settings/reset \
     -H 'Content-Type: application/json' -d '{"group": "transfer"}'
curl -s -X POST http://127.0.0.1:8000/api/settings/reset \
     -H 'Content-Type: application/json' -d '{}'
```

`GET /api/settings` returns:

```json
{ "ok": true,
  "settings": { "display.page_size": "25", "ui.form_mode": "auto", "…": "…" },
  "fields": [ { "key": "display.page_size", "group": "display", "kind": "int",
                "value": "25", "default": "25", "minimum": 5, "maximum": 500,
                "values": [], "personal": true, "requires": "",
                "label_en": "Rows per page", "label_ar": "عدد الصفوف في الصفحة",
                "help_en": "…", "help_ar": "…",
                "effect": "core.js pageSize() → views/list.js",
                "source": "default", "updated_at": null, "is_default": true } ],
  "groups": [ { "key": "display", "label_en": "Display & appearance",
                "label_ar": "العرض والمظهر", "icon": "sliders" } ],
  "overrides": 1, "schema_version": 1 }
```

`PUT` answers `{"ok": true, "changed": [{"key","old","new"}], "settings": {…}}`, or `422` with
`{"ok": false, "error": "invalid settings", "problems": [ … ], "applied": []}`.

`POST /api/settings/reset` answers `{"ok": true, "reset": [...], "changed": [...], "unknown": [...],
"settings": {…}}` — `reset` lists the rows that were dropped, `changed` only those whose *value*
actually moved. Resetting a key that already holds its default drops the row and writes **no**
change-log entry, so a "reset everything" cannot bury the real history under rows saying `25 → 25`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/settings` | values in force + registry metadata + source of each value |
| `GET` | `/api/settings/schema` | the registry alone (groups, types, bounds, bilingual help, effect) |
| `PUT` | `/api/settings` | validated, audited write of one or more keys |
| `POST` | `/api/settings/reset` | drop overrides (`keys`, `group` or all) — audited |
| `GET` | `/api/meta` | the same values (flat strings) plus `settings_schema`, for the first paint |

### 4.3 SQL — the table itself

```sql
-- what is overridden (rows are overrides; absence means "the default")
SELECT key, value, updated_at FROM setting ORDER BY key;

-- change one, by hand, with the same canonical form the API writes
INSERT INTO setting (key, value, updated_at)
     VALUES ('display.page_size', '50', strftime('%Y-%m-%dT%H:%M:%SZ','now'))
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;

-- return to the declared default
DELETE FROM setting WHERE key = 'display.page_size';
```

The table always carries **one row per declared key**: `settings.ensure()` re-seeds a missing row at
start-up, and a reset re-seeds the ones it dropped. A row whose value equals the declared default is
reported as *shipped default*, not an override — `overrides` in `/api/settings` counts only values
that actually differ. Rows for keys the registry does not declare cannot be read by any code path and
are removed by migration `009`.

Writing SQL directly skips validation and the audit trail, so it is a recovery tool, not the normal
path: a value that does not validate is ignored at read time (the declared default is used instead),
and the admin who did it left no trace. Prefer the API.

### 4.4 CLI and maintenance endpoints

| Command / endpoint | Effect on configuration |
|---|---|
| `python3 -m app.cli init` | creates the database and writes the declared defaults for every key |
| `python3 -m app.cli migrate` | applies migrations `002`–`009`: `007` seeds the form-surface keys, `008` seeds the registry keys with `INSERT OR IGNORE` (existing choices preserved), `009` deletes rows the registry does not declare |
| `POST /api/maintenance/reindex` · `/vacuum` | rebuild the search index · compact the file |
| `GET /api/maintenance/backup` | a ZIP of the database **and** `uploads/` — the settings are rows in that database |
| `GET /api/maintenance/export-all` | a JSON dump of every table, `setting` included |
| `POST /api/maintenance/prune` | honours `audit.retention_days` |

---

## 5 · Validation: what a refusal looks like

`PUT /api/settings` is **all-or-nothing**. If any key in the payload is invalid, nothing is written and
the response names every problem:

```json
{ "ok": false, "error": "invalid settings", "applied": [],
  "problems": [
    { "key": "display.page_size", "value": 9999, "reason": "above_maximum",
      "kind": "int", "minimum": 5, "maximum": 500,
      "message": "'display.page_size' must be at most 500" },
    { "key": "display.theme", "value": "neon", "reason": "not_allowed",
      "kind": "enum", "values": ["light","dark","system"],
      "message": "'display.theme' must be one of: light, dark, system" },
    { "key": "made.up.key", "value": "x", "reason": "unknown_key",
      "message": "'made.up.key' is not a known setting" }
  ] }
```

| `reason` | Meaning | What to do |
|---|---|---|
| `not_bool` | value is not `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` | send a boolean |
| `not_integer` | value is not a whole number | send a number |
| `below_minimum` / `above_maximum` | outside the declared range | read `minimum`/`maximum` from the problem or the schema |
| `not_allowed` | not one of the enum's values | use one of `values` |
| `unknown_key` | the key is not declared in the registry | check `/api/settings/schema` |
| `not_an_object` | the body was not a JSON object | send `{ "key": "value" }` |

**Every accepted change is audited**, one `change_log` row per key:

```
entity_type = "setting"   entity_code = "display.page_size"
field_key   = "display.page_size"   action = "update"
old_value   = "25"   new_value = "50"   actor = "admin"   reason = "settings"
```

so `GET /api/changelog?entity_type=setting` is the configuration history, and the same rows feed
`/api/maintenance/export-all` and the backup.

---

## 6 · Personal preferences (one browser, one person)

Exactly the eight settings the registry marks `personal` can be overridden per browser. They are
stored in `localStorage` and never sent to the server:

| Preference (screen label) | `localStorage` key | Instance key it overrides | Allowed values |
|---|---|---|---|
| Theme | `siraj.theme` | `display.theme` | `light` · `dark` · `system` |
| Density | `siraj.density` | `display.density` | `comfortable` · `compact` |
| Rows per page | `siraj.page_size` | `display.page_size` | 5 – 500 |
| Where forms open | `siraj.form_mode` | `ui.form_mode` | `page` · `dialog` · `auto` |
| Pop-up width | `siraj.form_dialog_size` | `ui.form_dialog_size` | `wide` · `xl` |
| Inline create | `siraj.inline_create` | `ui.inline_create` | `true` · `false` |
| Search: minimum characters | `siraj.search_min_chars` | `search.min_chars` | 1 – 5 |
| Search: hits per group | `siraj.search_results_limit` | `search.results_limit` | 5 – 100 |
| *(not a setting)* Language | `siraj.lang` | — (it *wins over* `display.default_language`) | an active locale code |
| *(not a setting)* Actor — who you are | `siraj.actor` | — (sent as `X-Actor`) | a username from the `app_user` table |

Two rows are marked *not a setting* on purpose. `siraj.lang` and `siraj.actor` are properties of the
person using the browser (which language they want, who they are), not policy someone chose on their
behalf — so they are never offered as "use for me only", and `display.default_language` stays a pure
instance decision: what a *first* visit opens in. The topbar toggle writes `siraj.lang`, which always
wins.

How the resolution works (`core.js`):

```js
A.pref("theme")                       // the stored personal value, or "default"
A.setPref("theme", "dark")            // store it (fires `siraj:pref`); "default" clears it
A.resolvePref("theme", "display.theme", "light")   // personal → instance → fallback
A.theme(); A.density(); A.pageSize()  // typed helpers built on that rule
A.applyAppearance()                   // paint theme + density now
```

**Every consumer reads the same three levels.** That is a rule with teeth: the settings screen only
offers *Use for me only* on a key whose consumer resolves `personal → instance → fallback`. The six
older consumers are `A.pref/resolvePref` in `core.js`; `search.min_chars`, `search.results_limit`
(`views/reports.js`), `ui.inline_create` (`components/fields.js`) and `ui.form_mode`
(`formMode()` in `core.js`) resolve the same way, so a personal choice is never offered and then
ignored.

`applyAppearance()` sets `<html data-theme>` and `<body class="density-compact">`, and re-applies the
theme when the operating system flips between light and dark while `system` is selected. It runs at
boot (after `/api/meta` arrives, so the first paint is already correct) and again after every change.

Clearing a preference is the same as never having set it — `A.setPref(name, "default")` removes the
key. That is what "return to the instance setting" means everywhere in the interface.

---

## 7 · What is *not* a setting (and where it lives)

Configuration-like things that deliberately have their own screens, because they are data:

| Thing | Where | Why not `setting` |
|---|---|---|
| Numbering (prefix, padding, next value) | **Numbering** (`#/numbering`), `sequence` table, `/api/sequences` | one row per entity, with its own preview and audit; see §8 |
| Users, roles, activation | **Settings → Users**, `app_user`, `/api/users` | rows with identity, not scalar values |
| Interface languages | **Settings → Locales**, `locale` table, `static/js/locales/*.json` | see §9 |
| Controlled vocabularies (countries, statuses, types) | **Vocabularies** (`#/vocabularies`), `lookup` / `lookup_domain` | thousands of rows, editable per domain |
| Field visibility, saved views | **Display** menus, `saved_view` | per-user data, not instance policy |
| Deployment (host, port, data dir, token) | environment variables | must be known before the database is opened; see §12 |

---

## 8 · Numbering — the other configuration surface, in full

`sequence` decides how identification numbers are built:

| Column | Meaning | Example |
|---|---|---|
| `entity_type` | one row per entity | `person` |
| `prefix` | the leading letters | `PER` |
| `padding` | zero-padding width | `4` → `PER-0042` |
| `next_value` | the next integer to hand out | `7235` |

* **Read:** `GET /api/sequences` → every entity's rule and next value.
* **Change:** `PUT /api/sequences/{entity}` with `{prefix, padding, next_value}`; validation refuses a
  padding outside 1–10 and a `next_value` that would re-issue an existing code.
* **Preview:** `GET /api/{entity}/next-code` → `{code: "PER-7235"}` — the same number a save will use,
  because `peek_next_code` skips codes that already exist.
* **Hand-supplied codes:** when a client sends its own `code`, `db.sync_sequence()` pushes
  `next_value` past it, so the next automatic number cannot collide. (This is what used to make
  "Save + New" answer `409` on the second record; see [PHASE6.md](PHASE6.md) §6.1.)
* **Padding changes affect only future codes** — existing identifiers are never rewritten, because
  they are cited in publications.

---

## 9 · Languages and locales

Adding a third interface language is configuration, not code:

1. insert a row in `locale` (`code`, `name_en`, `name_native`, `dir`, `is_active`, `is_default`,
   `sort_order`), or add it through `POST /api/users`-style admin tooling;
2. add `app/static/js/locales/<code>.json` and one entry in `locales/index.json`;
3. it appears in the topbar toggle, and `display.default_language` may now name it.

The bundles are served per request (`/api/locales/{code}/messages`) and every key is authored in both
`en.json` and `ar.json` — a test fails if the two ever drift apart (`set(ar) == set(en)`). Field
labels, help text, validation messages and the settings registry itself are all bilingual data, not
hardcoded strings.

---

## 10 · Configuration lifecycle: backup, export, restore, upgrade

**Backup.** `GET /api/maintenance/backup` produces a ZIP with a consistent SQLite snapshot (online
backup API), `uploads/`, and a manifest. The configuration is inside that snapshot — restoring the
database restores the settings and their audit trail. `python3 -m app.cli backup -o backups/x.zip`
does the same from the command line.

**Export a configuration alone.** *Settings → Download configuration* writes:

```json
{ "exported_at": "2026-11-02T16:40:00Z",
  "settings": { "display.page_size": "25", "…": "…" },
  "overrides": 1 }
```

**Restore a configuration.** Send that object back to `PUT /api/settings` (keys not present are left
alone), or reset first and then send it for an exact reproduction:

```bash
curl -s -X POST localhost:8000/api/settings/reset -d '{}' -H 'Content-Type: application/json'
curl -s -X PUT  localhost:8000/api/settings -H 'Content-Type: application/json' \
     -d "$(jq -c '.settings' siraj-settings.json)"
```

**Upgrades.** Three mechanisms, in order of authority:

1. `settings.ensure(conn)` runs at start-up and inserts a default row for any declared key the
   database is missing — a new build's new key appears without a migration.
2. Migration `008` seeds the same keys for databases that are migrated rather than started, and `009`
   removes any row the registry no longer declares (a replaced key that an older screen kept writing).
3. A **changed default** is not forced on an installation that never overrode it — because absence
   means "default", the new default simply applies. An explicit override is never silently rewritten.

---

## 11 · Adding a setting (the five-minute version)

1. **Declare it** in `app/settings.py`:

   ```python
   Spec("search.snippet_chars", "search", "int", "240",
        "Search snippet length", "طول مقتطف البحث",
        help_en="Characters of context shown around a hit.",
        help_ar="عدد الأحرف المعروضة حول نتيجة البحث.",
        minimum=60, maximum=600, personal=True,
        effect="views/reports.js renderResults()"),
   ```

2. **Read it** where it matters: `settings_mod.get(conn, "search.snippet_chars")` on the server, or
   `A.setting("search.snippet_chars", 240)` in the browser.
3. **Seed it** for existing databases: one `INSERT OR IGNORE` line in a new migration.
4. **Nothing else.** The settings screen, `/api/settings`, `/api/settings/schema`, `/api/meta`,
   validation, reset and the audit trail all pick it up from the declaration.
5. **Test it**: the registry tests assert the new key has an `effect`, bilingual labels, a valid
   default, and that a bad value is refused.

Deprecating a key is the reverse: remove the `Spec`, delete the row in a migration, and remove the
consumer. Because consumers call `settings.get()` with a declared key, a stale row can never be read
by accident.

---

## 12 · Deployment configuration (environment variables)

Read at start-up, before the database is opened — these are *not* stored in the registry, so they
cannot be changed from the interface (by design: the process is already listening).

| Variable | Default | Effect |
|---|---|---|
| `SIRAJ_HOST` | `127.0.0.1` on Windows, `0.0.0.0` elsewhere | bind address |
| `SIRAJ_PORT` | `8000` | port |
| `SIRAJ_DATA_DIR` | `app/data` | where the database, `uploads/` and `staging/` live (a portable folder) |
| `SIRAJ_DB` | `$SIRAJ_DATA_DIR/registry.db` | explicit database path |
| `SIRAJ_API_TOKEN` | *(empty)* | when set, every `/api` request must carry `Authorization: Bearer <token>` |
| `SIRAJ_SEED_DEMO` | `1` | `0` starts an empty registry without demo records |

---

## 13 · Security notes

* **Configuration is not authentication.** Anyone who can reach `/api/settings` can change policy.
  Put the instance behind an authenticating proxy (or set `SIRAJ_API_TOKEN`) before exposing it, and
  bind to `127.0.0.1` when only the local machine should reach it.
* **The actor is claimed, not proven.** `X-Actor` is recorded in the audit trail; it is only as
  trustworthy as the proxy in front of it. That is why every settings change is logged with the
  *old* value as well as the new one — a wrong actor cannot hide a change.
* **Deleting a row is a change.** `DELETE FROM setting` returns a key to its declared default and
  bypasses the audit trail; do it through `POST /api/settings/reset` instead.
* **Validation is server-side.** Hiding a control in the browser is not enforcement; every gate in
  §3 is checked in `repo`/`api`, and the interface only reflects it.

---

## 14 · Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A form still opens full-page although the mode is *Pop-up* | the browser has a personal override from an earlier session | Settings → *Data entry* → the row shows *Personal: …*; press the same button again after choosing the instance value, or clear `siraj.form_mode` |
| Values changed but nothing behaves differently | a *personal* preference is winning, or the value was written with SQL and the page is stale | reload; check the source badge on the row; `GET /api/settings \| jq '.fields[] \| select(.key=="…")'` |
| `422 invalid settings` with `unknown_key` | a typo, or a key from a newer build | compare with `/api/settings/schema` |
| An export is refused with a row count | `export.max_rows` is lower than the selection | narrow the filter, export in parts, or raise the ceiling |
| Publishing a record is refused | `validation.require_source_on_publish` / `min_completeness` | attach a citation or a primary source, or reset the policy |
| A delete is refused for a missing reason | `validation.require_reason_for_delete` | pass `?reason=…` (the interface asks for one) |
| Every save is refused with "at most 500" | `display.page_size` was typed into the wrong field | each refusal names the key and the bound |
| The audit trail suddenly shrank | `audit.retention_days` was set and `/api/maintenance/prune` was run | the prune is itself in the change log — restore from the last backup for the removed rows |
| A first visit opens in the wrong language | `display.default_language` names a locale with no bundle | check the `locale` table and `static/js/locales/index.json` |
| Settings screen shows *keys* but no values | the database is open read-only or the file was replaced | check the path in *Settings → Where this lives* |

---

## 15 · How configuration is verified

| Harness | What it proves |
|---|---|
| `pytest` | every key has a type, a default, a group, bilingual labels **and a consumer**; enum/int values are inside their declared bounds; `PUT` is all-or-nothing and reports `above_maximum` / `not_allowed` / `not_integer` / `unknown_key`; reset restores the default *and* writes a change-log row; the publish gate and the delete-reason gate actually block |
| `verify_all.py` | the routes `/api/settings`, `/api/settings/schema` and `/api/settings/reset` are exercised; a bad value is refused with a reason; the audit trail records a configuration change |
| `ui_smoke.py` | the settings route renders; a pristine form never claims to be dirty; a real edit asks before Escape drops it |
| `ui_full.py` | the screen renders every group and key, controls know their type, Save is disabled until something changes, the pending bar appears, a save round-trips, a refused value shows its reason and applies nothing, reset restores the default, and a personal theme/density applies at once and clears cleanly |
| `audit.py` | the underlying data invariants that the policies protect (counts, integrity, referential health) |

Run them all with:

```bash
python3 scripts/check.py --api --ui --full --geo --audit
```

---

## 16 · Quick index

| Key | Default | One line |
|---|---|---|
| `audit.retention_days` | `0` | prune audit rows older than N days; 0 keeps everything |
| `display.default_language` | `ar` | language of a first visit |
| `display.density` | `comfortable` | table row density (personal too) |
| `display.page_size` | `25` | rows per page (personal too) |
| `display.theme` | `light` | light / dark / follow the system (personal too) |
| `export.max_rows` | `50000` | hard ceiling for one export |
| `import.default_mode` | `create` | create / update / upsert to start the wizard with |
| `import.max_rows` | `20000` | refuse a commit larger than this, before writing |
| `maintenance.backup_includes_files` | `true` | include `uploads/` in the backup ZIP |
| `maintenance.vacuum_after_import` | `false` | compact the database after each import commit |
| `map.center_lat` | `33.3152` | latitude the map opens at the first time |
| `map.center_lon` | `44.3661` | longitude the map opens at the first time |
| `map.cluster` | `true` | group nearby markers (personal too) |
| `map.max_points` | `4000` | feature budget for one map response |
| `map.overlays` | `place_hierarchy` | overlays drawn over the base map (personal too) |
| `map.provider` | `local` | base map: offline pack, OSM or CARTO (personal too) |
| `map.show_labels` | `true` | labels above zoom 7 (personal too) |
| `map.units` | `metric` | metric or imperial distances (personal too) |
| `map.zoom` | `5` | zoom the map opens at the first time |
| `search.min_chars` | `2` | characters required before a search runs |
| `search.results_limit` | `20` | hits shown per group in the search panel |
| `ui.form_dialog_size` | `xl` | width of a pop-up form (personal too) |
| `ui.form_mode` | `page` | where create/edit opens: page / dialog / auto (personal too) |
| `ui.inline_create` | `true` | allow creating missing related records from a field |
| `validation.min_completeness` | `0` | completeness floor for publishing (0 = off) |
| `validation.require_reason_for_delete` | `false` | deletes and merges must carry a reason |
| `validation.require_source_on_publish` | `true` | published records must have a citation or source |

**Related reading:** [PHASE6.md](PHASE6.md) (the data-entry surface setting in depth),
[UI_GUIDE.md](UI_GUIDE.md) (how the screen behaves), [API.md](API.md) (every endpoint),
[OPERATIONS.md](OPERATIONS.md) (deployment, backup, security), [VERIFICATION.md](VERIFICATION.md)
(the evidence).
