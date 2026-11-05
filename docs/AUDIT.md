# The fundamental audit

*What an audit is: not "does the endpoint answer", but "is the answer right, is the data sound,
and does the registry survive being used hard?"*

`tests/verify_all.py` proves that every route responds. `tests/audit.py` asks the harder questions,
and it is deliberately **independent of the code it tests**: expected values are recomputed with
different SQL or in plain Python, so a bug in the filter engine cannot hide behind a test that asks
the filter engine what it thinks.

```bash
python3 tests/audit.py                      # 162 checks, ~60 s, against 127.0.0.1:8000
python3 tests/audit.py --list               # the sections
python3 tests/audit.py --only filters       # one section
python3 tests/audit.py --report docs/audit-report.md
python3 scripts/check.py --audit            # inside the normal pre-flight
```

| Section | Checks | Result |
|---|---|---|
| integrity — referential and structural integrity | 20 | 20/20 |
| filters — operator truth table vs independent counts | 16 | 16/16 |
| sorting — every field, both directions, degenerate input | 5 | 5/5 |
| paging — pages partition the result set | 7 | 7/7 |
| crud — full record lifecycle | 12 | 12/12 |
| cascade — a hard delete leaves nothing behind | 5 | 5/5 |
| graph — relationships, merge, focus map | 12 | 12/12 |
| numbering — padding, headroom, no reuse | 6 | 6/6 |
| transfer — export formats, import round-trip | 14 | 14/14 |
| i18n — AR/EN parity, translated labels, RTL | 9 | 9/9 |
| security — traversal, injection, hostile payloads | 16 | 16/16 |
| concurrency — 8 parallel writers | 5 | 5/5 |
| durability — backup snapshot restores | 6 | 6/6 |
| performance — latency budget | 12 | 12/12 |
| cleanup — the registry is left exactly as found | 17 | 17/17 |
| **total** | **162** | **162/162** |

---

## 1 · What the audit found

Seven real defects. Each one is now covered by a regression test, most of them in
`tests/test_registry.py` so they fail in three seconds rather than a minute.

### 1.1 Export silently truncated at 1 000 rows — *data loss, high*

The list endpoint clamps `page_size` to 1 000 so a browser cannot pull the whole table in one
request. The export path reused `list_records()`, so it inherited the clamp: a filtered selection of
6 795 persons produced a **1 000-row file with no warning**, and the file looked complete.

```text
before   export rows 1000   matching records 6795
after    export rows 6795   matching records 6795
```

The export now pages internally (`EXPORT_PAGE = 1 000`) until the reported total is reached, and
`MAX_ROWS = 50 000` is a *hard ceiling that fails loudly* — a shortened export is worse than none.
`list_records()` grew an explicit `max_page_size` argument so the UI guard and the bulk reader can
each have their own limit.

### 1.2 The export endpoint threw away the filter it was given — *data loss, high*

`POST /api/export/{entity}` did `payload.get("filters")` and passed only that inner mapping
downstream. A body written as `{"format": "xlsx", "filters": {"completeness": {"gte": 90}}}` exported
**every record** while the screen showed 1 780 — the classic "the file doesn't match what I see".

The whole body is now forwarded (minus the output options), and `normalize_filters()` learned that
structural keys (`where`, `q`, `sort`, `page_ids`, …) may appear *inside* `filters`, so both shapes —
nested and flat — behave identically.

### 1.3 Filter operators that were advertised but did nothing — *silently wrong results, high*

`FILTER_OP_ALIASES` mapped `startswith`, `start`, `empty` and `not_empty` onto canonical operators
that `build_where()` never implemented. A user picking "starts with" got **the whole table back**
plus a warning nobody reads. `year_eq`/`year_gte`/`year_lte` with a non-numeric value raised
`int("banana")` → HTTP 500 → the connection reset.

```text
before   name_en startswith "Ahmad" → 6 825 rows (all)   warning: Unsupported operator
after    name_en startswith "Ahmad" → 110 rows
before   name_en empty              → 6 825 rows (all)
after    name_en empty              → 344 rows (NULL or blank, trimmed)
before   birth_date year_eq "banana"→ 500 Internal Server Error
after    birth_date year_eq "banana"→ 200 + warning, no crash
```

The alias table is now the single source of truth: `tests/test_registry.py` iterates **every** alias
and asserts that it filters without a warning, so an operator cannot be advertised before it exists.

### 1.4 Hard delete left orphans in five tables — *data corruption, high*

`hard_delete()` ran `PRAGMA foreign_keys = OFF` and deleted the row. Everything the registry stores
polymorphically — `relationship`, `entity_tag`, `source_link`, `attachment`,
`entity_external_id` — kept pointing at a record that no longer existed. The shipped database
carried **11 such rows** (and `PRAGMA foreign_key_check` reported 9), left behind by earlier
verification runs: citations and tags attached to nothing.

A hard delete is now explicit and reports its blast radius:

```json
{"ok": true, "id": 7127, "hard": true,
 "dependents_removed": {"source_link": 1, "entity_external_id": 1,
                        "relationship_index": 2}}
```

Typed references are nulled (`person.affiliated_institution_id`, `place.parent_place_id`,
`event.place_id`, `primary_source_id`, …), relationships are removed *and* dropped from the search
index, and the test asserts that not one of the five tables still mentions the record.

### 1.5 A filter-key blacklist swallowed real columns — *self-inflicted, caught by the harness*

While fixing 1.2 the audit added `title`, `lang` and `format` to `_NON_FILTER_KEYS` (they are export
options). `title` is also a real column of `source`, so filtering sources by title silently matched
everything — and `verify_all.py`'s cleanup, which locates its own scratch rows by title, then deleted
200 legitimate source records before it noticed the census was wrong.

Two lessons, both now enforced in code:

* `_NON_FILTER_KEYS` holds **structure only** — never a field name — with a comment saying so;
* `verify_all.py` refuses to delete anything when a marker filter matches a whole table:

```python
if hits["total"] and hits["total"] >= table_total:
    check(False, f"marker filter narrowed {ent} before cleanup",
          f"the filter matched all {table_total} rows — nothing was deleted")
```

The 200 sources (and 332 citations, 376 relationship links, 229 primary-source links) were restored
row-for-row from the pre-run snapshot and verified against it; the census is back to the documented
28 538 records with zero structural problems.

### 1.6 The relationship matrix was asymmetric — *misleading diagram*

`relationship_map(mode="types")` counted stored direction. Because relationships are written from
one side, the heat map proudly reported `institutions → persons: 0` next to
`persons → institutions: 18 139`. The detail page shows every link on both records, so the matrix is
filled symmetrically (`matrix_undirected: true`), and the audit asserts symmetry cell by cell.

### 1.7 No way to ask the product "is my data sound?" — *missing capability*

Integrity was only checked by tests. It is now part of the product:

```bash
python3 -m app.cli check-integrity           # report only
python3 -m app.cli check-integrity --fix     # repair what is safe to repair
```

`app/integrity.py` measures broken foreign keys, orphaned polymorphic links, dangling citations,
duplicate/blank codes, place cycles, impossible dates, index parity, stale index documents,
sequences that fell behind the codes in use, and attachments whose file has vanished. `--fix`
deletes only what cannot be a judgement call (links to records that no longer exist, stale index
documents) and lifts sequences; duplicate codes, cycles and impossible dates are reported and left
for a human. CI runs the report on every push.

---

## 2 · What the audit confirms

Beyond the defects, these are measured facts about the running registry, not claims:

* **Integrity** — 0 broken foreign keys, 0 orphaned links in any of the five polymorphic tables,
  0 duplicate or blank codes, 0 cycles in the place hierarchy, 0 self- or duplicate relationships,
  0 people who die before being born, 0 reference columns pointing into the wrong vocabulary domain.
* **Search index parity** — exactly one document per live record across all six indexed types
  (28 538 documents), and no document for a deleted record.
* **Numbering** — every sequence sits above the highest code in use; changing prefix/padding is
  reflected in the *next* code; a deleted code is never handed out twice; the sequence is restored
  to its original state at the end of the check.
* **Paging** — walking pages of a 1 780-row selection returns every row exactly once, a page past
  the end is empty but still reports the true total, `page_size` is clamped to 1 000, negative
  paging lands on the first page, and `pages = ceil(total / page_size)` (never 0).
* **Filters** — 16 operator/field combinations match an independently computed count, including the
  derived `completeness` percentage recomputed in Python, and vocabulary *codes* resolved to ids.
* **Cross-reader agreement** — list, KPI strip, export and reports return the same numbers for the
  same filter payload.
* **Merge** — dry run reports the plan, the absorbed record leaves the active set but stays
  recoverable, and the graph is re-pointed without duplicate relationships.
* **Transfer** — CSV (UTF-8 BOM, Arabic preserved), TSV, JSON and XLSX all hold every record and agree
  about the row count; XLSX carries an export-info sheet; our own export re-imports with 0 invalid
  rows.
* **i18n** — AR and EN message bundles have identical key sets, every field, derived field, entity
  and vocabulary value has an Arabic label, Arabic is declared `rtl`, and labels are genuinely
  translated rather than mirrored.
* **Security** — four path-traversal probes blocked, SQL in filter values and sort keys treated as
  data, wildcard payloads do not match everything, an unsupported export format is a 4xx not a 500,
  a non-numeric id is a 422, and the opt-in token gate is advertised by `/api/metrics`.
* **Concurrency** — 48 parallel creates from 8 workers, all unique codes, none lost, ~32 inserts/s,
  with 60 list requests served during the writes without a single failure.
* **Durability** — the backup ZIP restores to a database with the same record count *and* the same
  search index; the full JSON dump carries 28 k+ rows.
* **Performance** — every path the interface hits hardest stays inside its budget: list 160 ms,
  KPI 47 ms, deep filter 62 ms, full-text search 15 ms, duplicates 267 ms, type map 50 ms,
  focus map 10 ms, record detail 12 ms, dashboard 182 ms, 1 000-row XLSX export 463 ms.

---

## 3 · The complete picture

| Harness | What it proves | Checks | Runtime |
|---|---|---|---|
| `pytest tests -q` | data model, repository, reports, import/export, numbering, i18n, place hygiene, graph API, **regressions from this audit** | **82** | ~3 s |
| `tests/verify_all.py` | every HTTP route, success and failure paths, self-cleaning | **207** | ~77 s |
| `tests/audit.py` | this document: integrity, truth tables, concurrency, durability, performance | **162** | ~65 s |
| `tests/ui_smoke.py` | fast browser pass: routes, views, filters, forms, RTL | **46** | ~30 s |
| `tests/ui_full.py` | every screen and interactive control in Chromium, console-gated | **142** | ~2.5 min |

**616 executed assertions, all green.** One command runs everything:

```bash
python3 scripts/check.py --api --ui --full --geo --audit
```
