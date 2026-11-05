# Operations

## Install & run

### Windows (primary target)

```bat
start.bat            :: double-click, or from cmd
powershell -File start.ps1   :: PowerShell variant (same behaviour)
```

Both scripts create `.venv` on first run, install `requirements.txt`, initialise the database when
`app\data\registry.db` is missing, start the server and open the browser. To run it by hand:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py --host 127.0.0.1 --port 8000
```

Notes that matter on Windows: the console is switched to UTF-8 (`PYTHONUTF8=1` + stream
reconfiguration in `app/server/launcher.py`), so Arabic labels and file names print correctly in
`cmd`; all file writes go through `db.atomic_write()` (mkstemp + `os.replace`) and all deletes through
`db.safe_unlink()` (retries on the transient `PermissionError` Windows raises while a file is still
mapped), so imports, uploads and backups do not fail on a locked file. Export downloads send
`Content-Disposition` with an RFC 5987 `filename*=UTF-8''…` value, which Excel and Edge/Chrome on
Windows honour (a transliterated ASCII `filename=` fallback is always included).

### macOS / Linux

```bash
python3 -m pip install -r requirements.txt
python3 run.py                          # init on first run, then serve on 0.0.0.0:8000
./run.sh                                # same, with the venv handled for you
```

Or with uvicorn directly (what a production service would use):
```bash
SIRAJ_DATA_DIR=/var/lib/siraj uvicorn app.server:app --host 0.0.0.0 --port 8000 --workers 1
```
> The ASGI target is `app.server:app` (the routes live in `app/server/api.py`); the former
> `app.main:app` module no longer exists.
> Keep **one worker** with SQLite (WAL already allows many concurrent readers). Use PostgreSQL before
> running multiple workers.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
`SIRAJ_DATA_DIR` | `app/data` | where `registry.db`, `uploads/` and `staging/` live (keep it on local disk, not a network share) |
`SIRAJ_HOST` | `127.0.0.1` on Windows, `0.0.0.0` elsewhere | bind address used by `run.py` / `start.*` |
`SIRAJ_PORT` | `8000` | bind port |
`SIRAJ_DB` | `$SIRAJ_DATA_DIR/registry.db` | explicit database path |
`SIRAJ_SEED_DEMO` | `1` | seed the synthetic demo dataset on first start (`0` for an empty registry) |
`SIRAJ_API_TOKEN` | unset | when set, every `/api/*` request must send `Authorization: Bearer <token>`; the static shell and `/api/health` stay public |

## Configuration

Two kinds of configuration, and it matters which is which:

| | Where | How it changes | Needs a restart? |
|---|---|---|---|
| **Deployment** | environment variables (`SIRAJ_HOST`, `SIRAJ_PORT`, `SIRAJ_DATA_DIR`, `SIRAJ_DB`, `SIRAJ_API_TOKEN`, `SIRAJ_SEED_DEMO`) | edit the start script or the service unit | yes — the process has already bound its port and opened its file |
| **Instance behaviour** | the `setting` table, edited in **Settings** (`#/settings`) | every change is validated, audited and effective immediately | no |

Everything a normal administrator wants to change — validation policy, import/export ceilings, search
thresholds, audit retention, backup contents, where forms open — is in the second row and needs no
downtime. The complete reference, including every key, its default, the code path that honours it and
the four ways to change it, is [`SETTINGS.md`](SETTINGS.md).

The three operational settings worth knowing before you tune anything:

```bash
# what is configured, and what is still the shipped default
curl -s localhost:8000/api/settings | jq '{overrides, fields: [.fields[] | {key, value, source}]}'

# change a policy (validated; an invalid value changes nothing and says why)
curl -s -X PUT localhost:8000/api/settings -H 'Content-Type: application/json' \
     -H 'X-Actor: admin' -d '{"validation.require_reason_for_delete": true}'

# back to the shipped defaults — one key, one group, or everything
curl -s -X POST localhost:8000/api/settings/reset -H 'Content-Type: application/json' \
     -d '{"group": "quality"}'
```

* `validation.require_source_on_publish` (on by default) is the gate that keeps uncited claims out of
  the published corpus; it is enforced in `repo`, so imports and the API obey it too.
* `export.max_rows` / `import.max_rows` are the ceilings that keep one request from holding a write
  transaction for minutes. Raise them deliberately, not by accident.
* `audit.retention_days` is `0` (**keep the audit trail forever**) unless someone changes it. Only
  when it is above zero does `POST /api/maintenance/prune` delete anything, and it records what it
  removed.

Every change is in the audit trail, one row per key, with the old and the new value:

```bash
curl -s 'localhost:8000/api/changelog?entity_type=setting&page_size=20' | jq '.items[] | {at: .changed_at, key: .entity_code, old: .old_value, new: .new_value, actor}'
```

If the interface and the database ever disagree, the registry is the authority:
`GET /api/settings/schema` lists exactly the keys that exist, and `python3 -m app.cli init` (or any
restart) re-inserts a default row for any declared key that is missing.

## The offline basemap

The geographic workspace draws its base map from `app/geo/basemap.sqlite`, a 2.54 MB pack
of Natural Earth geometry: five layers (countries, coastline, lakes, rivers and
1 251 populated places) at 1:110m and 1:50m detail built into the repository. Nothing about it needs the internet, a
tile server or a licence key — which is the only way a map can be guaranteed on a laptop
in an archive with no network.

```bash
# what the running application sees
curl -s localhost:8000/api/geo/basemap | jq '{available, bytes, layers: (.layers|keys)}'

# rebuild it from Natural Earth GeoJSON (only needed if you change the source data)
python3 -m app.geo.basemap_build --src /path/to/ne_geojson
```

Online providers (OpenStreetMap, CARTO light/dark) are available from the Layers menu and
are **opt-in per person** (`map.provider`); each carries the attribution and the usage
terms its licence requires, and the workspace shows them on the map. A tile failure is a
banner with a button that switches back to the offline base map — it never leaves a blank
canvas.

Coordinates in the registry can be reconciled with the bundled gazetteer:

```bash
python3 -m app.cli geocode-places                 # dry run: proposals, conflicts, nothing written
python3 -m app.cli geocode-places --apply         # write, two audited change_log rows per place
python3 -m app.cli geocode-places --show 20       # the first 20 proposals in full
```

A proposal is made only when the place's **name and its own country** agree with the city
it matched — see [MAP.md](MAP.md) §8. Conflicts and unmatched names are reported, never
"fixed".

## Backup & restore

```bash
# consistent snapshot while the app is running (SQLite online backup API)
curl -s localhost:8000/api/maintenance/backup -o siraj-$(date +%F).zip
# or from the CLI
python3 -m app.cli backup --out /backups/siraj-$(date +%F).zip

# restore
unzip -o siraj-2026-11-01.zip -d app/data && mv app/data/registry.db app/data/registry.db
```
`GET /api/maintenance/backup` now includes **every uploaded file** (attachments and media images)
under `uploads/` inside the same ZIP, with a manifest recording counts and bytes, so a backup is a
single artefact: `unzip` restores the database *and* its files, and the same works for the CLI
(`python3 -m app.cli backup`). The JSON dump (`/api/maintenance/export-all`) remains a portable
alternative for data only.

Recommended cadence: nightly `backup` + weekly off-site copy; keep 30 days. Test a restore quarterly.

## Migrations

`app/schema.sql` is the current schema for fresh installations; `app/migrations/*.sql` are applied in
filename order on start-up and recorded in `schema_migration` (filename, checksum, timestamp, status).
Migrations are allowed to no-op on already-existing columns, so a database created from the current
`schema.sql` can adopt the history safely.

Add a migration:
```bash
cat > app/migrations/006_my_change.sql <<'SQL'
ALTER TABLE person ADD COLUMN pronoun TEXT;
SQL
python3 -m app.cli migrate        # or restart the service
```

## Housekeeping commands

```bash
python3 -m app.cli check-integrity         # structural health report (read-only)
python3 -m app.cli check-integrity --fix   # repair the problems that are safe to repair
python3 -m app.cli reindex                 # rebuild the FTS index (after a manual SQL edit)
python3 -m app.cli tidy-places             # dry run: placeholder / duplicate place names
python3 -m app.cli tidy-places --apply     # write the plan (each rename is audited)
python3 -m app.cli bulk --profile large    # append a large synthetic dataset (volume testing)
python3 -m app.cli stats                   # record counts per table
```

Retention and compaction, the two commands driven by settings:

```bash
# how much audit history is older than audit.retention_days? (deletes nothing)
curl -s -X POST localhost:8000/api/maintenance/prune -H 'Content-Type: application/json' \
     -d '{"dry_run": true}'
# actually trim it; the operation is itself written to the change log
curl -s -X POST localhost:8000/api/maintenance/prune
# compact the file after a heavy import (or set maintenance.vacuum_after_import)
curl -s -X POST localhost:8000/api/maintenance/vacuum
```

`tidy-places` repairs the place hierarchy, which drives every map and every "group by place" report.
It works on three layers in a single pass:

1. **places** — placeholder names such as `City of Mauritania` are replaced by a real city of the
   same country, and siblings that share a name are qualified deterministically (`Dammam · North`);
2. **records that embed a place in their own name** — the same placeholder is stripped from
   `institution.name_en/name_ar` and `event.title_en/title_ar` (the part before the `—` or `,`),
   so a list never shows `National Library of City of Iraq — branch C`;
3. **the search index** — the command finishes by re-indexing the renamed records.

Every rename is written to `change_log` with the old and new value and an `entity_type`
(`place` / `institution` / `event`), so the whole pass is auditable and reversible record by record.
It is idempotent — a clean database reports `renames planned: 0`. The shipped dataset needed
1 322 renames (846 places, 706 institutions, 616 events) and now has none.

### Checking data integrity

`check-integrity` answers the question a registry must always be able to answer: *is the data sound?*
It measures broken foreign keys, orphaned links in the five polymorphic tables (`relationship`,
`entity_tag`, `source_link`, `attachment`, `entity_external_id`), citations pointing at a deleted
source, duplicate or blank codes, cycles in the place hierarchy, people who die before they are born,
search-index parity, numbering sequences that have fallen behind the codes in use, and attachment rows
whose file has vanished. It is what `tests/audit.py` uses, so the tool and the test can never drift.

`--fix` deletes only what cannot be a judgement call — links to records that no longer exist and
index documents for deleted records — and lifts sequences that fell behind. Duplicate codes,
hierarchy cycles and impossible dates are reported and left for a human, because guessing there would
be worse than reporting.

### What a delete removes

A *soft* delete only stamps `deleted_at`, so the record is recoverable from the trash. A *hard* delete
(`DELETE /api/{entity}/{id}?hard=true`) removes the record **and everything that exists only because
of it**: relationships (both sides, plus their index documents), tags, citations, identifiers,
attachments and positions; typed references elsewhere are nulled rather than left dangling. The
response reports the blast radius in `dependents_removed`, and the audit trail keeps the record's code.

## Adding a vocabulary value (no deployment)

Administration → Vocabularies → *Add value*, or:
```bash
curl -s -X POST localhost:8000/api/lookups -H 'Content-Type: application/json' \
  -d '{"domain":"place_type","code":"madrasa","label_en":"Madrasa","label_ar":"مدرسة دينية","color":"teal"}'
```

## Adding an interface language

1. copy `app/static/js/locales/en.json` to `app/static/js/locales/{code}.json` and translate the values
   (keys must stay identical — the test suite asserts AR and EN have the same key set);
2. insert a row in `locale` (`code`, `name_en`, `name_native`, `dir`, `is_active`);
3. optionally translate field/vocabulary labels — they live in the database (`lookup.label_*`,
   `app/schemas.py` for field labels), so a full third content language needs the translation table
   described in `docs/DESIGN_REVIEW.md` §2.17.

French and Turkish bundles are pre-registered as inactive to demonstrate the mechanism.

## Numbering rules

Administration → Numbering. Fields: prefix, separator, suffix, padding, next value, reset policy
(`never | yearly | monthly`), template (`{prefix}{sep}{number}{suffix}`).
Rules: codes are unique, never reused, and are **not** rewritten when the rule changes — only future
records are affected. Put historical/legacy identifiers in `entity_external_id`, not in `code`.

## Roles and security

The schema has four roles (`viewer`, `researcher`, `reviewer`, `admin`) in `app_user`, and every write
is attributed to the `X-Actor` header. **v1 does not authenticate requests** — it is designed for a
trusted network or a single-tenant deployment. Before exposing it publicly:

1. put it behind an authenticating reverse proxy (OIDC, SAML, mTLS) and have the proxy set `X-Actor`;
2. add role checks in `app/server/api.py` (a single dependency is enough — all writes go through
   `repo.create_record` / `repo.update_record` / `repo.soft_delete`);
3. enable HTTPS, restrict CORS (`allow_origins` is currently `*` for development);
4. decide a sensitive-data policy for living persons (birthplace, contact, image) and enforce
   column-level hiding for the `viewer` role;
5. keep `/api/maintenance/*` and hard delete admin-only;
6. review the audit trail requirements of your institution (retention, exports, right-to-erasure) —
   soft delete + `change_log` already support a defensible answer.

## Performance

| Data volume | Advice |
|---|---|
| < 100 k records | SQLite as shipped is fine. `VACUUM` monthly, `reindex` after large imports. |
| 100 k – 1 M | PostgreSQL + the same schema; keep FTS in OpenSearch with an Arabic analyser. |
| Read-heavy public site | Add a read replica / cache `/api/dashboard` and report payloads (they are pure functions of the database). |

The list endpoint is paginated and indexed; exports are capped by `export.max_rows`
(50 000 by default) and imports by `import.max_rows` (20 000) — both changeable in **Settings**.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
`database is locked` | a long write transaction or a second worker; keep `--workers 1` on SQLite |
Arabic search finds nothing | run `POST /api/maintenance/reindex` (the index is maintained on every write, but a manual `sqlite3` edit bypasses it) |
Import says "Unknown value" | the cell does not match a vocabulary code/label; open the template's *Reference* sheet |
`409 version conflict` | another user saved first — reload the record (the UI shows a message) |
XLSX export fails in Excel | sheets are RTL and styled; if a third-party tool complains, export CSV instead |
Uploads missing after moving servers | `uploads/` lives beside the database — move both, or restore the backup ZIP which carries both |
Every API call returns 401 | `SIRAJ_API_TOKEN` is set: send `Authorization: Bearer <token>` (shell and `/api/health` stay public) |
Images do not appear on cards | `image_url` must be a public URL or an uploaded `/api/media/…` path; check `uploads/media/` |

## Verification

```bash
python3 scripts/check.py --api --ui --full --geo --audit
#  = byte-compile + imports + pytest (101) + every API route (280)
#    + browser smoke (51) + exhaustive interface walk (198) + the fundamental audit (162)
#    + the geographic workspace (84)

python3 -m pytest -q            # 101 tests: schema, CRUD, audit, filters, search,
                               # derived fields, media, duplicates/merge, backup,
                               # relationships, import/export, reports, admin,
                               # place-name hygiene, the graph endpoint,
                               # locale parity + "no hardcoded UI strings", layout,
                               # the settings registry (types, bounds, refusal,
                               # reset, audit, one source for defaults)
python3 tests/verify_all.py     # 213 API checks; enumerates the route table and fails
                                # on any route the harness never exercised
python3 tests/ui_smoke.py       # 49 browser checks against a running server
python3 tests/ui_full.py        # 195 browser checks — every screen and control
                                # (pip install playwright && playwright install chromium)
python3 samples/run_samples.py  # end-to-end import/export fixture run
```

`tests/verify_all.py` and `tests/ui_full.py` clean up after themselves: scratch records are located
with exact-marker filters (never full-text search), then hard-deleted, so the dataset is identical
before and after a run. Run them against a demo database, not production.

The browser smoke test needs a live server on `127.0.0.1:8000`; it drives every route, the four
data views, the column chooser and card-layout builder, a derived-field filter, the duplicates
panel, a record dossier, the edit form's combobox and the inline-create pop-up, the language
toggle, and the fixed-chrome contract (pinned header/toolbar/pager, *Load more* appending rows,
filter dock opening without scrolling) — failing on any console error or page exception.
Screenshots are written to `.smoke/`.
