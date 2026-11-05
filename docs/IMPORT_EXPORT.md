# Import & export

## 1. Import — the four-step pipeline

```
GET  /api/import/template/{entity}?format=xlsx&lang=ar   ── ① template
POST /api/import/preview            (file upload)        ── ② parse + auto-map
POST /api/import/validate           (dry run)            ── ③ validate, nothing written
POST /api/import/commit             (real run)           ── ④ write inside savepoints
```

The UI wraps this in a wizard at **Data operations → Import**; every step is also usable directly
against the API, and `GET /api/import/jobs` lists every batch ever run.

### ① Templates
`GET /api/import/template/{entity}?format=xlsx|csv|json&lang=ar|en|both`

* every writable field of the entity, in the requested language;
* one example row (values are illustrative, not valid references — useful to see the expected shape);
* an XLSX **Reference** sheet listing every allowed value per vocabulary field
  (`code — English — Arabic`) and the expected form of foreign keys (`PER-0001`);
* bilingual headers in `both` mode (`Name in Arabic / الاسم بالعربية`).

### ② Parsing and auto-mapping
* Formats: **XLSX/XLSM**, **CSV**, **TSV**, **JSON**. Legacy `.xls` is rejected with a clear message
  (save as `.xlsx`).
* Encodings tried in order: UTF-8-BOM → UTF-8 → **CP1256** (Windows Arabic) → CP1252 → Latin-1.
  This is what makes files exported from old Arabic Windows software work.
* Delimiter detected with `csv.Sniffer` (`, ; \t |`), XLSX reads the first worksheet, fully blank rows
  are skipped, hard cap `MAX_ROWS = 50 000`.
* Header auto-mapping matches the English label, the Arabic label or the internal key
  (case/space/underscore-insensitive), then falls back to substring matching.
  Unmatched columns are reported as `unmapped_columns` and are simply ignored.
* `missing_required` lists required fields that no column was mapped to — fix the file or the mapping
  before continuing.

### ③ Validation (dry run)
Nothing is written. You get:

| Key | Meaning |
|---|---|
`total` | rows read |
`created` / `updated` / `skipped` | what *would* happen |
`failed` | rows with at least one error |
`errors[]` | `{row, field, message}` — row numbers refer to the file (row 1 = header) |
`rows[]` | per-row status and a preview of the coerced values |
`unknown_targets` | mapping targets that are not fields of the entity |

Checks: required fields, max length, URL shape (`http(s)://`, `mailto:`, `/path`), integer/float,
coordinate ranges, historical-date shape (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`,
`c. YYYY`, `YYYYs`, `YYYY?`),
vocabulary values, foreign-key references, and duplicate codes inside the file.

### ④ Commit
* each row runs inside a **savepoint** — a failing row is rolled back alone and the batch continues;
* every created/updated record goes through the normal repository layer, so it gets an audit entry
  with its reason (`bulk import`), a search-index update and a version increment;
* an `import_job` row stores counts, resolved mapping, the first 200 errors and the actor;
* the report is identical in shape to the dry run, so a UI can diff the two.

### Value resolution rules

| Field type | Accepted in the cell |
|---|---|
Select (vocabulary) | the numeric id, the **code** (`verified`), the **English label**, or the **Arabic label** (normalised: hamza/taa-marbuta/diacritics-insensitive) |
Foreign key | the numeric id, the record **code** (`INS-0004`), or the record name (English or Arabic) |
Date | `1950`, `1950-05`, `1950-05-12`, `c. 1950`, `1950s`, Excel date cells, `12/05/1950` (day-first, converted to ISO) |
Boolean | `1/0`, `true/false`, `yes/no`, `y/n`, `نعم/لا` |
Number | `1`, `2.5`; `latitude` must be −90…90, `longitude` −180…180 |
Text | trimmed; empty cell → `NULL` |

### Match modes

| Mode | Behaviour |
|---|---|
`create` | every row must have a new code; existing codes are reported as errors |
`upsert` | by `code` (default) or by `match_on` fields; updates what exists, creates what does not |
`update_only` | only existing records are touched; unknown codes are reported and skipped |

> Imports never renumber existing records and never overwrite a `code`.

### Recipe — round-tripping safely
```
POST /api/export/person   {"format":"csv","lang":"en","resolve":false}   → file
upload the file back     mode = upsert                                   → 0 created, N updated
edit the file, re-upload mode = upsert                                   → only differences are logged
```
Because `resolve:false` exports the raw ids/codes, the file round-trips losslessly.

## 2. Export

`POST /api/export/{entity}` with a body:

```json
{
  "format": "xlsx",                 // xlsx | csv | tsv | json
  "columns": ["code","name_ar","birth_date","nationality_id"],
  "lang": "ar",                     // ar | en | both   (header + label language)
  "resolve": true,                  // codes → readable labels
  "filters": { "q": "بغداد",
               "where": [{"field":"classification_id","op":"eq","value":3}],
               "logic": "and", "sort": "birth_date", "order": "asc" },
  "title": "Researchers in Baghdad"
}
```

* **CSV** is UTF-8 **with BOM** so Excel renders Arabic correctly; `\r\n` line endings.
* **XLSX** gets styled frozen headers, auto-filter, right-to-left sheet direction when `lang=ar`,
  sensible column widths, and an *Export info* sheet recording timestamp, record count and filters.
* **JSON** returns `{meta:{entity, exported_at, count, columns, filters}, rows:[…]}` — ideal for
  downstream pipelines.
* Exports respect the **current filters and sort**, so "export what I see" is exact.
* Every export is written to the change log (`field_key = __export__`) with the format and filter
  summary — useful for audit.
* Limit: 10 000 rows per export by default (`page_size`), 50 000 hard cap. For larger dumps use
  `/api/maintenance/export-all` or the SQLite backup.

Command-line equivalents:
```bash
curl -s -X POST localhost:8000/api/export/person \
     -H 'Content-Type: application/json' \
     -d '{"format":"xlsx","lang":"ar"}' -o persons.xlsx
curl -s localhost:8000/api/reports/quality/export?format=xlsx -o quality.xlsx
```

## 3. Sample files

`samples/` contains ready-to-import examples:

| File | Demonstrates |
|---|---|
`samples/persons-import.csv` | bilingual headers, Arabic values, `PER-` style FKs, `c. 1950` dates |
`persons-import-bilingual.csv` | same content with `EN / AR` headers |
`places-import.csv` | hierarchy via parent codes, coordinate precision |
`sources-import.json` | JSON row array with vocabulary codes |
`run_samples.sh` | uploads each sample through the API and prints the report |
