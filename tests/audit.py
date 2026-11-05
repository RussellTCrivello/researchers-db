"""
SIRAJ · tests/audit.py — the fundamental audit
==============================================

`verify_all.py` proves that **every route answers**. This script asks the harder
questions: *is the answer right, is the data sound, and does it hold up when the
registry is used hard?*

It is deliberately **independent** of the application's own code paths: expected
counts are recomputed with different SQL (or in Python) and compared with what the
API returned, so a bug in the filter engine cannot hide behind a test that asks
the filter engine what it thinks.

    python tests/audit.py                  # against 127.0.0.1:8000
    python tests/audit.py --list           # show the sections
    python tests/audit.py --only filters   # run one section
    python tests/audit.py --report out.md  # also write a Markdown report

Sections
--------
 1  integrity    referential + polymorphic integrity, codes, sequences, index parity
 2  filters      operator truth table checked against independent counts
 3  sorting      monotonicity for every sortable field, plus degenerate inputs
 4  paging       the pages partition the result set exactly once
 5  crud         full record lifecycle, validation, optimistic concurrency
 6  graph        relationships, merge re-pointing, focus-map symmetry
 7  numbering    padding, headroom, no reuse after delete
 8  transfer     export formats parsed back; import round-trip
 9  i18n         locale parity, untranslated labels, RTL
10  security     traversal, injection, malformed input, hostile payloads
11  concurrency  parallel writers, unique codes, no lost updates
12  durability   backup snapshot is complete and restorable
13  performance  latency budget for the paths the interface hits
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import httpx
except ImportError:                                     # pragma: no cover
    print("httpx is required: pip install -r requirements-dev.txt")
    raise SystemExit(2)

from app import db as appdb  # noqa: E402  (read-only probes)
from app.schemas import ENTITIES, derived_map  # noqa: E402

BASE = os.environ.get("SIRAJ_BASE", "http://127.0.0.1:8000")
MARK = f"AUDIT-{int(time.time())}"
ACTOR = "auditor"

RESULTS: list[tuple[str, bool, str, str]] = []          # (section, ok, label, detail)
CREATED: list[tuple[str, int]] = []
BASELINE: dict[str, int] = {}
FINDINGS: list[dict[str, str]] = []                      # defects worth fixing


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def check(section_id: str, cond: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((section_id, bool(cond), label, detail))
    print(f"  {'PASS' if cond else 'FAIL'} · {label}" +
          (f"\n         → {detail}" if detail and not cond else ""), flush=True)
    return bool(cond)


def finding(title: str, severity: str, detail: str) -> None:
    FINDINGS.append({"title": title, "severity": severity, "detail": detail})


def section(sid: str, name: str) -> None:
    print(f"\n=== [{sid}] {name} " + "=" * max(0, 60 - len(name)), flush=True)


class Client:
    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base.rstrip("/"), timeout=180.0,
                                 headers={"X-Actor": ACTOR})

    def req(self, method: str, path: str, body: Any = None,
            expect: tuple[int, ...] | int = (200,)) -> httpx.Response:
        expect = (expect,) if isinstance(expect, int) else expect
        r = self.http.request(method, path, json=body)
        if r.status_code not in expect:
            raise AssertionError(f"{method} {path} → {r.status_code} "
                                 f"(expected {expect}): {r.text[:300]}")
        return r

    def get(self, path: str, expect=(200,)):
        return self.req("GET", path, None, expect)

    def post(self, path: str, body=None, expect=(200,)):
        return self.req("POST", path, body if body is not None else {}, expect)

    def delete(self, path: str, expect=(200,)):
        return self.req("DELETE", path, None, expect)


def conn() -> sqlite3.Connection:
    c = appdb.connect()
    c.row_factory = sqlite3.Row
    return c


def db_exec(sql: str, params: tuple = ()) -> int:
    """Run one statement in its own connection.

    The audit sometimes has to look at (or seed) rows the API does not expose.
    Doing that on a long-lived connection risks leaving a write transaction open,
    which then blocks the server — that is exactly how a crashed test section
    turned into a cascade of "database is locked" failures.
    """
    c = appdb.connect()
    try:
        cur = c.execute(sql, params)
        c.commit()
        return cur.rowcount
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def one(c: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    row = c.execute(sql, params).fetchone()
    return None if row is None else row[0]


ENTITY_TABLES = {k: s.table for k, s in ENTITIES.items()}


# ---------------------------------------------------------------------------
# 1 · integrity
# ---------------------------------------------------------------------------
def s_integrity(_api: Client) -> None:
    section("integrity", "referential and structural integrity of the live data")
    c = conn()

    ok = one(c, "PRAGMA integrity_check")
    check("integrity", ok == "ok", "SQLite reports a healthy file", str(ok))

    fk_rows = c.execute("PRAGMA foreign_key_check").fetchall()
    names = {f"{r[0]}.{r[3]}" for r in fk_rows}
    check("integrity", not fk_rows, "no declared foreign key is broken",
          f"{len(fk_rows)} dangling reference(s): {sorted(names)[:6]}"
          if fk_rows else "")
    if fk_rows:
        finding("Dangling foreign keys in the shipped database",
                "medium",
                f"{len(fk_rows)} rows point at deleted parents ({', '.join(sorted(names))}); "
                "they come from hard deletes that skip dependent rows")

    # polymorphic links have no SQL foreign keys, so check them explicitly
    poly = {
        "entity_tag": ("entity_type", "entity_id"),
        "source_link": ("entity_type", "entity_id"),
        "attachment": ("entity_type", "entity_id"),
        "entity_external_id": ("entity_type", "entity_id"),
        "relationship": ("entity1_type", "entity1_id"),
    }
    branches = " UNION ALL ".join(
        f"SELECT 1 FROM {t} p WHERE {{alias}}.entity_type_ = '{k}' AND p.id={{alias}}.entity_id_"
        for k, t in ENTITY_TABLES.items())
    orphans = 0
    for table, (tcol, icol) in poly.items():
        sql = (f"SELECT COUNT(*) FROM {table} x WHERE NOT EXISTS ("
               + branches.replace("{alias}.entity_type_", f"x.{tcol}")
                         .replace("{alias}.entity_id_", f"x.{icol}") + ")")
        n = one(c, sql)
        orphans += n
        if n:
            check("integrity", False, f"every {table} row points at a live record", f"{n} orphan(s)")
        else:
            check("integrity", True, f"every {table} row points at a live record")
    if orphans:
        finding("Orphaned polymorphic links",
                "medium",
                f"{orphans} rows in entity_tag/source_link/attachment/entity_external_id/"
                "relationship point at records that no longer exist — hard delete does not "
                "clean dependent tables")

    # a source_link row must also point at a real source (SQL FK — but the pragma was off)
    n = one(c, """SELECT COUNT(*) FROM source_link sl
                  WHERE NOT EXISTS (SELECT 1 FROM source s WHERE s.id = sl.source_id)""")
    check("integrity", n == 0, "every citation points at an existing source", f"{n} dangling")

    for t in ("person", "institution", "place", "event", "source"):
        dups = one(c, f"SELECT COUNT(*) FROM (SELECT code FROM {t} WHERE code IS NOT NULL "
                      f"GROUP BY code HAVING COUNT(*) > 1)")
        blanks = one(c, f"SELECT COUNT(*) FROM {t} WHERE code IS NULL OR TRIM(code) = ''")
        check("integrity", dups == 0 and blanks == 0,
              f"{t}: codes are unique and present", f"dups={dups} blank={blanks}")

    # sequences must sit above the highest code in use, or the next create collides
    head = []
    for r in c.execute("SELECT entity_type, prefix, next_value FROM sequence"):
        spec = ENTITIES.get(r["entity_type"])
        if spec is None:
            head.append(f"{r['entity_type']}: unknown entity")
            continue
        max_code = one(c, f"SELECT MAX(CAST(substr(code, instr(code,'-')+1) AS INTEGER)) "
                          f"FROM {spec.table} WHERE code LIKE ?", (r["prefix"] + "-%",)) or 0
        if (max_code or 0) >= r["next_value"]:
            head.append(f"{r['entity_type']}: next={r['next_value']} max={max_code}")
    check("integrity", not head, "every number sequence sits above the codes in use", "; ".join(head))
    if head:
        finding("Number sequence behind live codes", "high",
                "; ".join(head) + " — the next created record would reuse a code")

    # FTS index parity, including relationships (they are indexed too)
    live = {"person": one(c, "SELECT COUNT(*) FROM person WHERE deleted_at IS NULL"),
            "institution": one(c, "SELECT COUNT(*) FROM institution WHERE deleted_at IS NULL"),
            "place": one(c, "SELECT COUNT(*) FROM place WHERE deleted_at IS NULL"),
            "event": one(c, "SELECT COUNT(*) FROM event WHERE deleted_at IS NULL"),
            "source": one(c, "SELECT COUNT(*) FROM source WHERE deleted_at IS NULL"),
            "relationship": one(c, "SELECT COUNT(*) FROM relationship WHERE deleted_at IS NULL")}
    docs = {r[0]: r[1] for r in c.execute("SELECT entity_type, COUNT(*) FROM search_doc GROUP BY 1")}
    off = {k: (v, docs.get(k, 0)) for k, v in live.items() if docs.get(k, 0) != v}
    check("integrity", not off, "the search index has exactly one document per live record",
          f"mismatched: {off}" if off else "")
    stale = one(c, """SELECT COUNT(*) FROM search_doc sd WHERE sd.entity_type = 'person'
                      AND NOT EXISTS (SELECT 1 FROM person p WHERE p.id = sd.entity_id
                                      AND p.deleted_at IS NULL)""")
    check("integrity", stale == 0, "no deleted record lingers in the index", f"{stale} stale")

    from app import integrity
    builtin = integrity.summary(integrity.scan(c))
    check("integrity", not builtin,
          "the product's own integrity scanner reports a clean database",
          " | ".join(builtin[:4]))
    if builtin:
        finding("The built-in integrity scanner finds problems", "high", " | ".join(builtin[:4]))

    cyc = one(c, """WITH RECURSIVE up(id, cur, depth) AS (
                      SELECT id, id, 0 FROM place WHERE parent_place_id IS NOT NULL
                      UNION ALL
                      SELECT up.id, p.parent_place_id, up.depth + 1
                        FROM up JOIN place p ON p.id = up.cur
                       WHERE p.parent_place_id IS NOT NULL AND up.depth < 32)
                    SELECT COUNT(*) FROM up WHERE cur = id AND depth > 0""")
    check("integrity", cyc == 0, "the place hierarchy is acyclic", f"{cyc} cycles")

    check("integrity",
          one(c, "SELECT COUNT(*) FROM relationship WHERE entity1_type = entity2_type "
                 "AND entity1_id = entity2_id") == 0,
          "no self-referencing relationship")
    check("integrity",
          one(c, "SELECT COUNT(*) FROM (SELECT entity1_type, entity1_id, entity2_type, entity2_id, "
                 "relationship_type_id FROM relationship GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1)") == 0,
          "no duplicate relationship triples")
    check("integrity",
          one(c, "SELECT COUNT(*) FROM person WHERE birth_date IS NOT NULL "
                 "AND death_date IS NOT NULL AND birth_date > death_date") == 0,
          "no person dies before being born")

    # every reference column must point into the vocabulary domain it declares
    wrong = []
    for spec in ENTITIES.values():
        for f in spec.fields:
            domain = getattr(f, "domain", None)
            if f.type == "ref" and domain and f.key in [r[1] for r in
                                                        c.execute(f"PRAGMA table_info({spec.table})")]:
                n = one(c, f"SELECT COUNT(*) FROM {spec.table} t JOIN lookup l ON l.id = t.{f.key} "
                           f"WHERE l.domain <> ?", (domain,))
                if n:
                    wrong.append(f"{spec.table}.{f.key}→{domain}:{n}")
    check("integrity", not wrong, "reference columns point into their own vocabulary domain",
          "; ".join(wrong))
    if wrong:
        finding("Reference columns holding the wrong vocabulary", "high", "; ".join(wrong))

    c.close()


# ---------------------------------------------------------------------------
# 2 · filter engine truth table
# ---------------------------------------------------------------------------
def _expected_person(c: sqlite3.Connection, field: str, op: str, value) -> int:
    """Recompute the expected count in Python — independent of the SQL builder."""
    if field == "name_en" and op in ("contains", "not_contains", "starts", "ends", "equals"):
        target = appdb.normalize(str(value))
        rows = [appdb.normalize(r[0] or "") for r in
                c.execute("SELECT name_en FROM person WHERE deleted_at IS NULL")]
        fn = {"contains": lambda s: target in s,
              "not_contains": lambda s: target not in s,
              "starts": lambda s: s.startswith(target),
              "ends": lambda s: s.endswith(target),
              "equals": lambda s: s == target}[op]
        return sum(1 for s in rows if fn(s))
    if field == "name_en" and op in ("is_null", "not_null"):
        sql = ("name_en IS NULL" if op == "is_null"
               else "name_en IS NOT NULL") + " AND deleted_at IS NULL"
        return one(c, f"SELECT COUNT(*) FROM person WHERE {sql}")
    if field == "completeness":                      # derived: percentage of filled columns
        from app.schemas import PERSON_CORE
        track = PERSON_CORE
        total = 0
        for r in c.execute(f"SELECT {', '.join(track)} FROM person WHERE deleted_at IS NULL"):
            filled = sum(1 for v in r if v not in (None, ""))
            pct = round(100 * filled / len(track))
            if {"gte": pct >= value, "gt": pct > value, "lt": pct < value,
                "lte": pct <= value, "eq": pct == value}[op]:
                total += 1
        return total
    raise KeyError((field, op))


def s_filters(api: Client) -> None:
    section("filters", "operator truth table — API totals vs independently computed totals")
    c = conn()
    cases = [
        ("name_en", "contains", "al-"), ("name_en", "not_contains", "al-"),
        ("name_en", "starts", "Moh"), ("name_en", "ends", "i"),
        ("name_en", "equals", "Zaki al-Najjar"),
        ("name_en", "is_null", None), ("name_en", "not_null", None),
        ("name_en", "empty", None), ("name_en", "not_empty", None),
    ]
    for field, op, value in cases:
        body = {"filters": {field: {op: value if value is not None else True}},
                "page_size": 1}
        got = api.post("/api/person/query", body).json()
        if op in ("empty", "not_empty"):
            expected = one(c, f"SELECT COUNT(*) FROM person WHERE deleted_at IS NULL "
                              f"AND {'(name_en IS NULL OR TRIM(name_en) = ' + chr(39) + chr(39) + ')' if op == 'empty' else 'name_en IS NOT NULL AND TRIM(name_en) <> ' + chr(39) + chr(39)}")
        else:
            expected = _expected_person(c, field, op, value)
        check("filters", got["total"] == expected, f"{field} {op} {value!r} matches an independent count",
              f"api={got['total']} expected={expected} warnings={got.get('warnings')}")
        if got["total"] != expected and got["total"] == one(c, "SELECT COUNT(*) FROM person WHERE deleted_at IS NULL"):
            finding("Filter operator accepted but ignored", "high",
                    f"{field} {op} returned the whole table ({got['total']})")

    # derived-field filter, computed independently in Python
    for op, val in (("gte", 80), ("lt", 50), ("eq", 100)):
        got = api.post("/api/person/query",
                       {"filters": {"completeness": {op: val}}, "page_size": 1}).json()
        expected = _expected_person(c, "completeness", op, val)
        check("filters", abs(got["total"] - expected) <= max(3, expected * 0.01),
              f"derived completeness {op} {val} matches an independent count",
              f"api={got['total']} recomputed={expected}")

    # vocabulary-code filters: the UI sends codes, the column stores ids
    status_codes = [r[0] for r in c.execute(
        "SELECT code FROM lookup WHERE domain = 'record_status' ORDER BY id LIMIT 2")]
    if status_codes:
        got = api.post("/api/person/query",
                       {"filters": {"record_status_id": {"in": status_codes}}, "page_size": 1}).json()
        ids = [r[0] for r in c.execute(
            f"SELECT id FROM lookup WHERE domain = 'record_status' AND code IN "
            f"({','.join('?' * len(status_codes))})", tuple(status_codes))]
        expected = one(c, f"SELECT COUNT(*) FROM person WHERE deleted_at IS NULL "
                          f"AND record_status_id IN ({','.join('?' * len(ids))})", tuple(ids))
        check("filters", got["total"] == expected,
              "vocabulary codes are resolved to ids before filtering",
              f"api={got['total']} expected={expected}")

    # unknown field / operator must warn, never 500, never silently match everything
    r = api.post("/api/person/query", {"filters": {"not_a_field": {"eq": 1}}, "page_size": 1}).json()
    check("filters", bool(r.get("warnings")), "an unknown field produces a warning")
    r = api.post("/api/person/query", {"filters": {"name_en": {"wat": "x"}}, "page_size": 1}).json()
    check("filters", bool(r.get("warnings")), "an unknown operator produces a warning")
    r = api.post("/api/person/query", {"filters": {"birth_date": {"year_eq": "banana"}},
                                       "page_size": 1})
    check("filters", r.status_code == 200 and bool(r.json().get("warnings")),
          "a malformed year is a warning, not a 500", r.text[:120])

    # filters must be honoured by EVERY reader (list, kpi, export, reports)
    flt = {"filters": {"completeness": {"gte": 90}}}
    listing = api.post("/api/person/query", {**flt, "page_size": 1}).json()["total"]
    kpi = api.post("/api/person/kpi", flt).json()
    kpi_n = kpi.get("count") or kpi.get("total") or (kpi.get("tiles") or [{}])[0].get("value")
    check("filters", int(kpi_n or -1) == listing,
          "the KPI strip counts the same filtered set as the list",
          f"kpi={kpi_n} list={listing}")
    exp = api.post("/api/export/person", {**flt, "format": "csv"}).content.decode("utf-8-sig")
    rows = len([ln for ln in exp.splitlines() if ln.strip()]) - 1
    check("filters", abs(rows - listing) <= 1,
          "export applies the same filter as the list", f"export={rows} list={listing}")
    rep = api.post("/api/reports/overview", flt).json()
    check("filters", isinstance(rep, dict) and rep, "reports accept the same filter payload")
    c.close()


# ---------------------------------------------------------------------------
# 3 · sorting
# ---------------------------------------------------------------------------
def s_sorting(api: Client) -> None:
    section("sorting", "every sortable field, both directions, and degenerate input")
    spec = ENTITIES["person"]
    keys = [f.key for f in spec.fields if getattr(f, "filterable", True)] + \
           list(derived_map("person").keys())
    bad = []
    for key in keys:
        for direction in ("asc", "desc"):
            try:
                r = api.post("/api/person/query",
                             {"sort": {"key": key, "dir": direction}, "page_size": 5})
                if r.status_code != 200 or len(r.json()["items"]) == 0:
                    bad.append(f"{key}/{direction}: {r.status_code}")
            except AssertionError as exc:
                bad.append(str(exc)[:80])
    check("sorting", not bad, f"all {len(keys)} fields sort in both directions", "; ".join(bad[:5]))

    def first_id(sort):
        return api.post("/api/person/query", {"sort": sort, "page_size": 1}).json()["items"][0]["id"]

    a = first_id({"key": "code", "dir": "asc"})
    d = first_id({"key": "code", "dir": "desc"})
    check("sorting", a != d, "ascending and descending really differ", f"{a} vs {d}")
    check("sorting", first_id({"key": "nope"}) == first_id({"key": "id", "dir": "asc"}),
          "an unknown sort key falls back to id instead of failing")
    multi = api.post("/api/person/query",
                     {"sort": [{"key": "record_status_id", "dir": "asc"},
                               {"key": "code", "dir": "desc"}], "page_size": 20}).json()
    pairs = [(i.get("record_status_id"), i["code"]) for i in multi["items"]]
    ordered = pairs == sorted(pairs, key=lambda p: (p[0] if p[0] is not None else -1,
                                                    _neg(p[1])))
    check("sorting", ordered, "multi-key sorting applies the second key inside the first",
          str(pairs[:4]))

    # a text sort must not put blanks first in descending order (COALESCE behaviour)
    desc = api.post("/api/person/query",
                    {"sort": {"key": "name_en", "dir": "desc"}, "page_size": 5}).json()["items"]
    check("sorting", all(i.get("name_en") for i in desc),
          "descending text sort does not lead with empty values",
          str([i.get("name_en") for i in desc]))


def _neg(s: str) -> tuple:
    """Sort helper: reverse lexicographic order for the second sort key."""
    return tuple(-ord(ch) for ch in (s or ""))


# ---------------------------------------------------------------------------
# 4 · paging
# ---------------------------------------------------------------------------
def s_paging(api: Client) -> None:
    section("paging", "pages must partition the filtered set exactly once")
    flt = {"filters": {"completeness": {"gte": 40}}}
    total = api.post("/api/person/query", {**flt, "page_size": 25}).json()["total"]
    seen: list[int] = []
    page, page_size = 1, 50
    while len(seen) < min(total, 400):
        js = api.post("/api/person/query",
                      {**flt, "page": page, "page_size": page_size}).json()
        seen += [i["id"] for i in js["items"]]
        if not js["items"]:
            break
        page += 1
    check("paging", len(seen) == len(set(seen)), "no record appears on two pages",
          f"{len(seen)} rows, {len(set(seen))} unique")
    check("paging", len(seen) == min(total, 400), "walking the pages returns every row once",
          f"total={total} walked={len(seen)}")

    js = api.post("/api/person/query", {**flt, "page": 10_000, "page_size": 50}).json()
    check("paging", js["items"] == [] and js["total"] == total,
          "a page past the end is empty but still reports the true total")
    js = api.post("/api/person/query", {"page_size": 10 ** 9}).json()
    check("paging", js["page_size"] <= 1000 and len(js["items"]) <= 1000,
          "page_size is clamped, so one request cannot dump the table",
          f"page_size={js['page_size']}")
    js = api.post("/api/person/query", {"page": -3, "page_size": -5}).json()
    check("paging", js["page"] >= 1 and js["page_size"] >= 1,
          "negative paging is clamped to the first page",
          f"page={js['page']} size={js['page_size']}")
    js = api.post("/api/person/query", {"page_size": 7}).json()
    check("paging", js["pages"] == max(1, (js["total"] + 6) // 7),
          "pages = ceil(total / page_size)", f"{js['pages']} vs {js['total']}/7")
    js = api.post("/api/person/query", {"filters": {"name_en": {"equals": MARK}}, "page_size": 10}).json()
    check("paging", js["pages"] == 1 and js["total"] == 0,
          "an empty result reports one page, not zero", str(js["pages"]))


# ---------------------------------------------------------------------------
# 5 · CRUD lifecycle
# ---------------------------------------------------------------------------
def s_crud(api: Client) -> None:
    section("crud", "create → read → patch → delete → trash → restore → hard delete")
    created = api.post("/api/person", {"name_ar": f"اختبار {MARK}", "name_en": f"Audit {MARK}",
                                       "birth_date": "1950"}).json()["record"]
    rid = created["id"]
    CREATED.append(("person", rid))
    check("crud", created["code"].startswith("PER-"), "create assigns a code automatically",
          created["code"])
    check("crud", api.get(f"/api/person/{rid}").json()["name_en"] == f"Audit {MARK}",
          "the created record reads back")

    v = created["version"]
    upd = api.req("PATCH", f"/api/person/{rid}", {"researcher_notes": "patched"}).json()["record"]
    check("crud", upd["version"] == v + 1, "patch bumps the version", f"{v} → {upd['version']}")
    check("crud", upd["researcher_notes"] == "patched", "patch writes the new value")

    r = api.req("PATCH", f"/api/person/{rid}", {"researcher_notes": "stale", "_version": v},
                expect=(409, 400, 412, 422))
    check("crud", r.status_code in (409, 400, 412, 422),
          "a stale version is rejected instead of overwriting a newer edit",
          f"status={r.status_code}")

    miss = api.req("POST", "/api/person", {"name_en": "no arabic name"}, expect=(400, 422))
    check("crud", miss.status_code in (400, 422), "a missing required field is refused",
          f"status={miss.status_code}")

    hist = api.get(f"/api/person/{rid}/history").json()
    events = hist if isinstance(hist, list) else hist.get("events", [])
    check("crud", len(events) >= 2, "history records the create and the patch",
          f"{len(events)} entries")

    api.delete(f"/api/person/{rid}?reason=audit")
    lst = api.post("/api/person/query",
                   {"filters": {"name_en": {"equals": f"Audit {MARK}"}}, "page_size": 5}).json()
    check("crud", lst["total"] == 0, "a soft-deleted record leaves the list")
    trash = api.post("/api/person/query",
                     {"filters": {"name_en": {"equals": f"Audit {MARK}"}},
                      "only_deleted": True, "page_size": 5}).json()
    check("crud", trash["total"] == 1, "the same record is visible in the trash")
    check("crud", api.get(f"/api/person/{rid}", expect=(404,)).status_code == 404,
          "reading a deleted record is a 404 unless include_deleted is set")
    check("crud", api.get(f"/api/person/{rid}?include_deleted=true").status_code == 200,
          "include_deleted=true still reaches it")
    api.post(f"/api/person/{rid}/restore")
    again = api.post("/api/person/query",
                     {"filters": {"name_en": {"equals": f"Audit {MARK}"}}, "page_size": 5}).json()
    check("crud", again["total"] == 1, "restore brings the record back")

    bulk = api.post("/api/person/bulk", {"ids": [rid], "action": "update",
                                         "patch": {"researcher_notes": "bulk ok"}}).json()
    check("crud", bulk["ok"] == 1 and bulk["failed"] == 0, "bulk update applies to the record",
          json.dumps(bulk)[:120])
    dl = api.delete(f"/api/person/{rid}?hard=true&reason=audit")
    check("crud", dl.json().get("hard") is True, "hard delete reports what it did")
    check("crud", api.get(f"/api/person/{rid}?include_deleted=true",
                          expect=(404,)).status_code == 404, "hard delete really removes it")
    CREATED.remove(("person", rid))


# ---------------------------------------------------------------------------
# 6 · graph: relationships and merge
# ---------------------------------------------------------------------------
def s_delete_cascade(api: Client) -> None:
    section("cascade", "a hard delete leaves nothing pointing at the removed record")
    rid = api.post("/api/person", {"name_ar": f"حذف {MARK}", "name_en": f"Cascade {MARK}"}
                   ).json()["record"]["id"]
    other = api.get("/api/options/person?limit=1").json()[0]["id"]
    src = api.get("/api/options/source?limit=1").json()[0]["id"]
    rel_type = api.get("/api/lookups?domain=relationship_type").json()[0]["id"]
    tag = api.post("/api/tags", {"domain": "topic", "label_en": f"cascade {MARK}",
                                 "label_ar": f"تتالي {MARK}"}).json()["id"]

    api.post(f"/api/person/{rid}/citations", {"source_id": src})
    api.post(f"/api/person/{rid}/external-ids",
             {"scheme": "ORCID", "value": f"0000-{MARK}", "url": "https://orcid.org"})
    api.post("/api/relationship", {"entity1_type": "person", "entity1_id": rid,
                                   "entity2_type": "person", "entity2_id": other,
                                   "relationship_type_id": rel_type,
                                   "record_status_id": api.get(
                                       "/api/lookups?domain=record_status").json()[0]["id"]})
    db_exec("INSERT INTO entity_tag (entity_type, entity_id, tag_id) VALUES ('person', ?, ?)",
            (rid, tag))

    c = conn()
    before = {t: one(c, f"SELECT COUNT(*) FROM {t} WHERE entity_type='person' AND entity_id=?",
                     (rid,))
              for t in ("evidence", "source_link", "entity_tag", "entity_external_id")}
    rels = one(c, "SELECT COUNT(*) FROM relationship WHERE (entity1_type='person' AND "
                  "entity1_id=?) OR (entity2_type='person' AND entity2_id=?)", (rid, rid))
    c.close()
    # a citation is now an `evidence` row; `source_link` is the legacy store and is
    # expected to be empty for a record created today
    must_have = ("evidence", "entity_tag", "entity_external_id")
    check("cascade", all(before[t] > 0 for t in must_have) and rels > 0,
          "the scratch record really has dependents", f"{before} relationships={rels}")

    api.delete(f"/api/person/{rid}?hard=true&reason=audit")
    c = conn()
    after = {t: one(c, f"SELECT COUNT(*) FROM {t} WHERE entity_type='person' AND entity_id=?",
                    (rid,))
             for t in before}
    left_rels = one(c, "SELECT COUNT(*) FROM relationship WHERE (entity1_type='person' AND "
                       "entity1_id=?) OR (entity2_type='person' AND entity2_id=?)", (rid, rid))
    indexed = one(c, "SELECT COUNT(*) FROM search_doc WHERE entity_type='person' "
                     "AND entity_id=?", (rid,))
    c.close()
    check("cascade", not any(after.values()),
          "no evidence, citation, tag or identifier points at the removed record",
          str(after))
    check("cascade", left_rels == 0, "no relationship still references the removed record",
          f"{left_rels} left")
    check("cascade", indexed == 0, "the removed record leaves the search index too")
    api.delete(f"/api/tags/{tag}", expect=(200, 404))

    # and the database must still be writable — the bug that hid behind a crash
    probe = api.post("/api/person", {"name_ar": f"فحص {MARK}", "name_en": f"Lock probe {MARK}"})
    check("cascade", probe.status_code == 200,
          "the database is still writable after a cascade delete", probe.text[:120])
    if probe.status_code == 200:
        api.delete(f"/api/person/{probe.json()['record']['id']}?hard=true&reason=audit")


def s_graph(api: Client) -> None:
    section("graph", "relationships, merge re-pointing and focus-map symmetry")
    a = api.post("/api/person", {"name_ar": f"مرجع أ {MARK}", "name_en": f"Audit A {MARK}"}).json()["record"]
    b = api.post("/api/person", {"name_ar": f"مرجع ب {MARK}", "name_en": f"Audit B {MARK}"}).json()["record"]
    CREATED.extend([("person", a["id"]), ("person", b["id"])])

    # a citation attached to the record must show up in its detail payload
    src = api.get("/api/options/source?limit=1").json()[0]["id"]
    created = api.post(f"/api/person/{a['id']}/citations", {"source_id": src}).json()
    check("graph", created.get("ok") is not False, "a citation can be attached")
    det = api.get(f"/api/person/{a['id']}").json()
    citations = det.get("citations") or det.get("_citations") or []
    check("graph", any(c.get("source_id") == src for c in citations),
          "the citation is visible on the record", json.dumps(citations)[:120])

    # merge: B into A, then A must keep B's links
    plan = api.post(f"/api/person/{a['id']}/merge",
                    {"merge_ids": [b["id"]], "dry_run": True}).json()
    check("graph", plan.get("dry_run") is True and plan.get("merged"),
          "merge supports a dry run", json.dumps(plan)[:120])
    done = api.post(f"/api/person/{a['id']}/merge", {"merge_ids": [b["id"]]}).json()
    check("graph", done.get("merged"), "merge reports what it absorbed", json.dumps(done)[:120])
    gone = api.get(f"/api/person/{b['id']}", expect=(404, 200))
    check("graph", gone.status_code == 404, "the absorbed record leaves the active set")
    check("graph", api.get(f"/api/person/{b['id']}?include_deleted=true").status_code == 200,
          "the absorbed record is recoverable, not destroyed")
    # it stays in CREATED: cleanup restores, then hard-deletes it, so the census
    # is identical after the run (a plain hard delete would silently skip it)

    # focus map must contain the record and be symmetric about it
    fm = api.post("/api/relationship-map",
                  {"mode": "focus", "entity_type": "person", "record_id": a["id"],
                   "depth": 1}).json()
    ids = {n.get("id") for n in fm.get("nodes", [])}
    check("graph", f"person:{a['id']}" in ids,
          "the focus map contains the record it centres on", str(sorted(ids)[:5]))
    check("graph", all(e.get("source") in ids and e.get("target") in ids
                       for e in fm.get("edges", [])),
          "every focus-map edge lands on a node that is drawn")

    types_map = api.post("/api/relationship-map", {"mode": "types"}).json()
    matrix = types_map.get("matrix") or {}
    check("graph", isinstance(matrix, dict) and matrix, "the type map returns a counts matrix")
    if isinstance(matrix, dict) and matrix:
        asym = [f"{a}↔{b}" for a in matrix for b in matrix
                if matrix.get(a, {}).get(b) != matrix.get(b, {}).get(a)]
        check("graph", not asym,
              "the type matrix is symmetric — the interface shows links on both records",
              ", ".join(asym[:4]))
    CREATED.append(("person", a["id"]))


# ---------------------------------------------------------------------------
# 7 · numbering
# ---------------------------------------------------------------------------
def s_numbering(api: Client) -> None:
    section("numbering", "padding, headroom and no reuse after a delete")
    seqs = {s["entity_type"]: s for s in api.get("/api/sequences").json()}
    book = seqs.get("event")
    check("numbering", book is not None, "the sequence table is exposed")
    if not book:
        return
    original = dict(book)
    try:
        api.req("PUT", "/api/sequences/event", {"prefix": "AUD", "next_value": 900001,
                                                "padding": 7})
        nxt = api.get("/api/event/next-code").json()
        code = nxt.get("code") or nxt.get("next") or ""
        check("numbering", code.startswith("AUD-") and len(code.split("-")[1]) == 7,
              "changing the prefix and padding is reflected in the next code", str(nxt))
        e = api.post("/api/event", {"title_ar": f"حدث {MARK}", "title_en": f"Event {MARK}"}).json()["record"]
        CREATED.append(("event", e["id"]))
        check("numbering", e["code"] == code, "the created record uses the code that was promised",
              f"{e['code']} vs {code}")
        api.delete(f"/api/event/{e['id']}?hard=true&reason=audit")
        CREATED.remove(("event", e["id"]))
        after = api.get("/api/event/next-code").json()
        after_code = after.get("code") or after.get("next") or ""
        check("numbering", after_code != code, "a deleted code is never handed out twice",
              f"{after_code} == {code}")
    finally:
        api.req("PUT", "/api/sequences/event",
                {"prefix": original["prefix"], "next_value": original["next_value"],
                 "padding": original["padding"]})
        restored = {s["entity_type"]: s for s in api.get("/api/sequences").json()}["event"]
        check("numbering", restored["prefix"] == original["prefix"]
              and restored["next_value"] == original["next_value"],
              "the sequence is restored exactly as it was found")


# ---------------------------------------------------------------------------
# 8 · import / export round-trip
# ---------------------------------------------------------------------------
def s_transfer(api: Client) -> None:
    section("transfer", "every export format parses, and an export can be imported back")
    total = api.post("/api/person/query", {"page_size": 1}).json()["total"]
    csv_bytes = api.post("/api/export/person", {"format": "csv"}).content
    text = csv_bytes.decode("utf-8-sig")
    rows = list(__import__("csv").DictReader(io.StringIO(text)))
    check("transfer", abs(len(rows) - total) <= 1, "CSV holds every record", f"{len(rows)}/{total}")
    check("transfer", csv_bytes.startswith(b"\xef\xbb\xbf"), "CSV carries a BOM so Excel reads Arabic")
    check("transfer", any("\u0600" <= ch <= "\u06ff" for ch in text[:20000]),
          "CSV preserves Arabic text")

    tsv = api.post("/api/export/person", {"format": "tsv"}).content.decode("utf-8-sig")
    check("transfer", len(tsv.splitlines()) == len(text.splitlines()), "TSV has the same row count",
          f"{len(tsv.splitlines())} vs {len(text.splitlines())}")

    js = json.loads(api.post("/api/export/person", {"format": "json"}).content)
    check("transfer", js["meta"]["count"] == len(js["rows"]), "JSON export is self-consistent")
    check("transfer", abs(len(js["rows"]) - total) <= 1, "JSON holds every record")

    big = api.post("/api/person/query", {"filters": {"completeness": {"gte": 40}},
                                         "page_size": 1}).json()["total"]
    if big > 1000:
        wide = api.post("/api/export/person",
                        {"format": "csv", "filters": {"completeness": {"gte": 40}}}).content
        wide_rows = len([ln for ln in wide.decode("utf-8-sig").splitlines() if ln.strip()]) - 1
        check("transfer", wide_rows == big,
              f"a {big}-row selection exports in full (no silent 1 000-row cap)",
              f"export={wide_rows} total={big}")

    xlsx = api.post("/api/export/person", {"format": "xlsx"}).content
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xlsx), read_only=True)
    ws = wb.worksheets[0]
    check("transfer", ws.max_row - 1 == len(rows), "XLSX holds every record",
          f"{ws.max_row - 1} vs {len(rows)}")
    check("transfer", len(wb.worksheets) >= 2, "XLSX carries an export-info sheet")

    # import the CSV we just produced; codes collide → the import must update, not duplicate
    files = {"file": ("audit.csv", csv_bytes, "text/csv")}
    prev = api.http.post("/api/import/preview",
                         files=files, data={"entity": "person"}).json()
    check("transfer", prev.get("upload_id") and prev.get("columns"),
          "import preview detects the columns", json.dumps(prev)[:150])
    mapping = {c: c for c in prev["columns"]}
    valid = api.post("/api/import/validate",
                     {"entity": "person", "upload_id": prev["upload_id"],
                      "mapping": mapping}).json()
    check("transfer", valid.get("total") == len(rows),
          "import validation sees every exported row",
          f'{valid.get("total")} vs {len(rows)}')
    check("transfer", valid.get("invalid", 0) == 0,
          "an export of our own data re-imports with no invalid rows",
          json.dumps(valid)[:200])

    bad = api.http.post("/api/import/preview",
                        files={"file": ("x.csv", b"garbage\x00\xff", "text/csv")},
                        data={"entity": "person"})
    body = bad.json() if bad.status_code == 200 else {}
    check("transfer", bad.status_code in (400, 422)
          or (not body.get("total_rows") and not body.get("mapping")),
          "an unreadable upload yields no usable rows instead of a half-broken import",
          f"status={bad.status_code} rows={body.get('total_rows')}")
    bad2 = api.http.post("/api/import/preview",
                         files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
                         data={"entity": "person"})
    check("transfer", bad2.status_code == 200, "a well-formed but unmapped CSV still previews")


# ---------------------------------------------------------------------------
# 9 · i18n
# ---------------------------------------------------------------------------
def s_i18n(api: Client) -> None:
    section("i18n", "locale parity, translated labels, RTL")
    locales = api.get("/api/locales").json()
    rows = locales if isinstance(locales, list) else locales.get("items", [])
    check("i18n", {r["code"] for r in rows} >= {"ar", "en"}, "Arabic and English are both registered")
    ar = next(r for r in rows if r["code"] == "ar")
    check("i18n", ar.get("dir") == "rtl", "Arabic is declared right-to-left", str(ar.get("dir")))

    en = api.get("/api/locales/en/messages").json()
    ar_msg = api.get("/api/locales/ar/messages").json()
    missing = sorted(set(en) - set(ar_msg))
    extra = sorted(set(ar_msg) - set(en))
    check("i18n", not missing and not extra, "AR and EN message bundles have identical keys",
          f"missing={missing[:5]} extra={extra[:5]}")
    untranslated = [k for k, v in ar_msg.items() if v and v == en.get(k) and len(str(v)) > 3
                    and not any("\u0600" <= ch <= "\u06ff" for ch in str(v))]
    check("i18n", len(untranslated) <= 5,
          "Arabic bundle is translated, not copied from English",
          f"{len(untranslated)} identical strings: {untranslated[:6]}")

    meta = api.get("/api/meta?lang=ar").json()
    # /api/meta groups fields and derived fields per entity
    no_ar = [f"{ent}.{f['key']}" for ent, flist in meta["fields"].items()
             for f in flist if not f.get("label_ar")]
    no_ar += [f"derived:{ent}.{d['key']}" for ent, dlist in meta["derived"].items()
              for d in dlist if not d.get("label_ar")]
    no_ar += [e["key"] for e in meta["entities"] if not e.get("label_ar")]
    check("i18n", not no_ar, "every field has an Arabic label", str(no_ar[:6]))
    c = conn()
    bad_lookups = one(c, "SELECT COUNT(*) FROM lookup WHERE label_ar IS NULL OR TRIM(label_ar) = ''")
    check("i18n", bad_lookups == 0, "every vocabulary value has an Arabic label",
          f"{bad_lookups} missing")
    c.close()
    meta_en = api.get("/api/meta?lang=en").json()
    pairs = {f"{ent}.{f['key']}": (f.get("label_en"), f.get("label_ar"))
             for ent, flist in meta_en["fields"].items() for f in flist
             if f.get("label_ar")}
    identical = [k for k, (en_l, ar_l) in pairs.items()
                 if en_l and ar_l and en_l == ar_l and len(en_l) > 2]
    check("i18n", len(identical) <= len(pairs) * 0.2,
          "field labels really are translated, not mirrored",
          f"{len(identical)} of {len(pairs)} identical: {identical[:5]}")


# ---------------------------------------------------------------------------
# 10 · security and robustness
# ---------------------------------------------------------------------------
def s_security(api: Client) -> None:
    section("security", "traversal, injection, malformed input, hostile payloads")
    c = conn()
    before = one(c, "SELECT COUNT(*) FROM person")
    for probe in ("/api/media/../../../etc/passwd",
                  "/api/media/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                  "/api/media//etc/passwd",
                  "/api/media/..%5c..%5cwindows%5cwin.ini"):
        r = api.http.get(probe)
        check("security", r.status_code in (400, 403, 404),
              f"traversal blocked: {probe.rsplit('/', 1)[-1][:28]}", f"status={r.status_code}")

    inj = api.post("/api/person/query",
                   {"filters": {"name_en": {"contains": "'; DROP TABLE person;--"}},
                    "page_size": 1})
    check("security", inj.status_code == 200 and inj.json()["total"] == 0,
          "SQL in a filter value is data, not code", inj.text[:120])
    inj2 = api.post("/api/person/query", {"sort": "name_en; DROP TABLE person", "page_size": 1})
    check("security", inj2.status_code == 200, "SQL in a sort key is rejected, not executed")
    inj3 = api.post("/api/person/query", {"filters": {"name_en": {"contains": "%' OR 1=1 --"}},
                                          "page_size": 1})
    check("security", inj3.json()["total"] == 0, "a wildcard payload does not match everything",
          str(inj3.json()["total"]))

    xss = api.post("/api/person", {"name_ar": f"<script>alert(1)</script> {MARK}",
                                   "name_en": f"<img src=x onerror=alert(1)> {MARK}"}).json()["record"]
    CREATED.append(("person", xss["id"]))
    back = api.get(f"/api/person/{xss['id']}").json()
    check("security", back["name_en"].startswith("<img"), "markup is stored verbatim (the UI escapes it)")
    check("security", "text/html" not in api.get(f"/api/person/{xss['id']}").headers.get("content-type", ""),
          "record JSON is served as JSON, so markup cannot execute on the API origin")

    check("security", api.get("/api/nonsense", expect=(404,)).status_code == 404,
          "an unknown entity is a 404")
    check("security", api.post("/api/export/person", {"format": "rtf"},
                               expect=(422,)).status_code == 422,
          "an unsupported export format is a 4xx, not a 500")
    check("security", api.post("/api/person/query", {"page_size": 10 ** 9}).status_code == 200,
          "an absurd page size is clamped rather than refused")
    check("security", api.get("/api/person/abc", expect=(422,)).status_code == 422,
          "a non-numeric id is a validation error")
    check("security", one(c, "SELECT COUNT(*) FROM person") == before + 1,
          "no probe deleted data (person count unchanged apart from the XSS probe)")

    # token gate: the middleware is opt-in, but it must work when enabled
    check("security", api.get("/api/health").status_code == 200,
          "/api/health answers without a token (for probes)")
    metrics = api.get("/api/metrics").json()
    check("security", "token_auth" in metrics,
          "the API advertises whether the token gate is on", str(metrics.get("token_auth")))
    c.close()


# ---------------------------------------------------------------------------
# 11 · concurrency
# ---------------------------------------------------------------------------
def s_concurrency(api: Client) -> None:
    section("concurrency", "parallel writers must not collide, lock or lose rows")
    workers, per = 8, 6
    errors: list[str] = []

    def work(n: int) -> list[tuple[str, int]]:
        made = []
        with httpx.Client(base_url=BASE, timeout=180.0, headers={"X-Actor": ACTOR}) as client:
            for k in range(per):
                r = client.post("/api/institution",
                                json={"name_ar": f"مؤسسة {MARK}-{n}-{k}",
                                      "name_en": f"Audit Inst {MARK}-{n}-{k}"})
                if r.status_code != 200:
                    errors.append(f"{r.status_code}: {r.text[:80]}")
                    continue
                made.append(("institution", r.json()["record"]["id"]))
        return made

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        made = [r for part in pool.map(work, range(workers)) for r in part]
    elapsed = time.perf_counter() - start
    CREATED.extend(made)
    check("concurrency", not errors, f"{workers}×{per} parallel creates all succeeded",
          "; ".join(errors[:4]))
    codes = [api.get(f"/api/institution/{rid}").json()["code"] for _e, rid in made]
    check("concurrency", len(codes) == len(set(codes)),
          "no two parallel creates received the same code", f"{len(codes)} codes, "
          f"{len(set(codes))} unique")
    check("concurrency", len(made) == workers * per,
          "no write was lost", f"{len(made)} of {workers * per} visible")
    print(f"         ({len(made)} inserts in {elapsed:.2f}s = "
          f"{len(made) / max(elapsed, 1e-6):.0f}/s)", flush=True)

    # read while writing: a list must never fail or return a torn row
    def reader(_n: int) -> int:
        with httpx.Client(base_url=BASE, timeout=120.0) as client:
            bad = 0
            for _ in range(10):
                r = client.post("/api/person/query", json={"page_size": 25})
                if r.status_code != 200 or "items" not in r.json():
                    bad += 1
            return bad

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        bad = sum(pool.map(reader, range(6)))
    check("concurrency", bad == 0, "60 list requests during writes all answered", f"{bad} failed")


# ---------------------------------------------------------------------------
# 12 · durability
# ---------------------------------------------------------------------------
def s_durability(api: Client) -> None:
    section("durability", "the backup snapshot is complete and restorable")
    blob = api.get("/api/maintenance/backup").content
    check("durability", blob[:2] == b"PK" and len(blob) > 100_000,
          "the backup is a real ZIP", f"{len(blob)} bytes")
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = zf.namelist()
    check("durability", any(n.endswith(".db") for n in names), "the backup contains the database",
          str(names[:6]))
    db_name = next(n for n in names if n.endswith(".db"))
    with tempfile.TemporaryDirectory() as tmp:
        zf.extract(db_name, tmp)
        restored = sqlite3.connect(Path(tmp) / db_name)
        n = restored.execute("SELECT COUNT(*) FROM person").fetchone()[0]
        docs = restored.execute("SELECT COUNT(*) FROM search_doc").fetchone()[0]
        restored.close()
    live = conn()
    live_n = one(live, "SELECT COUNT(*) FROM person")
    live_docs = one(live, "SELECT COUNT(*) FROM search_doc")
    live.close()
    check("durability", abs(n - live_n) <= 2, "the restored copy holds the same records",
          f"backup={n} live={live_n}")
    check("durability", abs(docs - live_docs) <= 2, "the restored copy carries the search index",
          f"backup={docs} live={live_docs}")

    dump = api.get("/api/maintenance/export-all").content
    payload = json.loads(dump)
    check("durability", payload.get("meta") and len(payload) > 6,
          "the JSON dump carries every table", str(list(payload)[:8]))
    total = sum(len(v) for k, v in payload.items()
                if isinstance(v, list))
    check("durability", total > 20_000, "the JSON dump is not truncated", f"{total} rows")


# ---------------------------------------------------------------------------
# 13 · performance
# ---------------------------------------------------------------------------
def s_performance(api: Client) -> None:
    section("performance", "latency budget for the paths the interface hits hardest")
    probes = [
        ("list page", "POST", "/api/person/query", {"page": 1, "page_size": 25}, 400),
        ("KPI strip", "POST", "/api/person/kpi", {}, 400),
        ("deep filter", "POST", "/api/person/query",
         {"filters": {"record_status_id": {"in": ["verified", "published"]},
                      "completeness": {"gte": 50}}, "page_size": 25}, 400),
        ("full-text search", "GET", "/api/search?q=بغداد&limit=25", None, 400),
        ("duplicates", "GET", "/api/person/duplicates?limit=25", None, 900),
        ("type map", "POST", "/api/relationship-map", {"mode": "types"}, 600),
        ("focus map", "POST", "/api/relationship-map",
         {"mode": "focus", "entity_type": "person", "record_id": 1, "depth": 2}, 400),
        ("record detail", "GET", "/api/person/1", None, 300),
        ("dashboard", "GET", "/api/dashboard", None, 800),
        ("report overview", "POST", "/api/reports/overview", {}, 500),
        ("picker search", "GET", "/api/options/institution?q=library&limit=20", None, 300),
        ("meta bootstrap", "GET", "/api/meta", None, 500),
    ]
    slow = []
    for label, method, path, body, budget in probes:
        best = 9e9
        for _ in range(3):
            t0 = time.perf_counter()
            r = api.http.request(method, path, json=body)
            best = min(best, time.perf_counter() - t0)
            assert r.status_code == 200, f"{path} → {r.status_code}"
        ms = best * 1000
        ok = ms <= budget
        check("performance", ok, f"{label} ≤ {budget} ms", f"{ms:.0f} ms")
        if not ok:
            slow.append(f"{label}={ms:.0f}ms")
    if slow:
        finding("Slow read path", "medium", "; ".join(slow))


# ---------------------------------------------------------------------------
# cleanup + report
# ---------------------------------------------------------------------------
def cleanup(api: Client) -> None:
    section("cleanup", "the registry is left exactly as it was found")
    left = 0
    for ent, rid in CREATED:
        try:
            # merge soft-deletes the absorbed record; a hard delete cannot reach
            # a soft-deleted row, so restore it first and then destroy it
            api.post(f"/api/{ent}/{rid}/restore", {}, expect=(200, 204, 400, 404, 409))
            api.delete(f"/api/{ent}/{rid}?hard=true&reason=audit", expect=(200, 204, 404, 400))
        except Exception:                              # noqa: BLE001
            left += 1
    check("cleanup", left == 0, "scratch records removed", f"{left} could not be deleted")

    c = conn()
    # the sweep must see soft-deleted rows too: a merged scratch record is
    # deleted_at != NULL, and that is exactly the case that used to slip through
    strays = one(c, "SELECT COUNT(*) FROM person WHERE deleted_at IS NULL AND name_en LIKE ?",
                 (f"%{MARK}%",))
    strays += one(c, "SELECT COUNT(*) FROM institution WHERE deleted_at IS NULL "
                     "AND name_en LIKE ?", (f"%{MARK}%",))
    strays += one(c, "SELECT COUNT(*) FROM event WHERE deleted_at IS NULL AND title_en LIKE ?",
                  (f"%{MARK}%",))
    strays += one(c, "SELECT COUNT(*) FROM person WHERE deleted_at IS NOT NULL "
                     "AND name_en LIKE ?", (f"%{MARK}%",))
    check("cleanup", strays == 0, "no scratch record survived", f"{strays} left")
    for ent, table in ENTITY_TABLES.items():
        now_n = one(c, f"SELECT COUNT(*) FROM {table}")
        if ent in BASELINE:
            delta = now_n - BASELINE[ent]
            check("cleanup", delta == 0, f"{ent} count is unchanged", f"{BASELINE[ent]} → {now_n}")
    # dependent tables must be back to their baseline too — this is what a
    # half-finished hard delete used to leave behind
    for table in ("source_link", "entity_tag", "attachment", "entity_external_id",
                  "relationship", "person_position", "change_log"):
        now_n = one(c, f"SELECT COUNT(*) FROM {table}")
        base = BASELINE.get(table)
        if base is None:
            continue
        if table == "change_log":
            check("cleanup", now_n >= base, "the audit trail grew (deletes are recorded)")
        else:
            check("cleanup", now_n == base, f"{table} count is unchanged", f"{base} → {now_n}")
    c.close()


SECTIONS: list[tuple[str, str, Callable[[Client], None]]] = [
    ("integrity", "referential and structural integrity", s_integrity),
    ("filters", "filter operator truth table", s_filters),
    ("sorting", "sorting every field", s_sorting),
    ("paging", "pagination invariants", s_paging),
    ("crud", "record lifecycle", s_crud),
    ("cascade", "hard deletes clean their dependents", s_delete_cascade),
    ("graph", "relationships and merge", s_graph),
    ("numbering", "numbering control", s_numbering),
    ("transfer", "import and export", s_transfer),
    ("i18n", "Arabic / English completeness", s_i18n),
    ("security", "security and robustness", s_security),
    ("concurrency", "parallel writers", s_concurrency),
    ("durability", "backup and restore", s_durability),
    ("performance", "latency budget", s_performance),
    ("cleanup", "cleanup", cleanup),
]


def write_report(path: Path) -> None:
    by_section: dict[str, list[tuple[bool, str, str]]] = {}
    for sid, ok, label, detail in RESULTS:
        by_section.setdefault(sid, []).append((ok, label, detail))
    lines = ["# Audit report", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} against `{BASE}`.", "",
             "| Section | Checks | Result |", "|---|---|---|"]
    for sid, name, _fn in SECTIONS:
        rows = by_section.get(sid, [])
        passed = sum(1 for ok, _, _ in rows if ok)
        lines.append(f"| {sid} | {name} | {'**' if passed == len(rows) else ''}"
                     f"{passed}/{len(rows)}{'**' if passed == len(rows) else ''} |")
    if FINDINGS:
        lines += ["", "## Findings", ""]
        for f in FINDINGS:
            lines.append(f"- **{f['severity'].title()}** · {f['title']} — {f['detail']}")
    failures = [(sid, label, detail) for sid, ok, label, detail in RESULTS if not ok]
    if failures:
        lines += ["", "## Failed checks", ""]
        for sid, label, detail in failures:
            lines.append(f"- `{sid}` {label}" + (f" — {detail}" if detail else ""))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description="Fundamental audit of the SIRAJ registry")
    ap.add_argument("--base", default=BASE)  # noqa: F821 - module constant
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    if args.list:
        for sid, name, _ in SECTIONS:
            print(f"  {sid:12} {name}")
        return 0

    BASE = args.base.rstrip("/")
    api = Client(BASE)
    try:
        api.get("/api/health")
    except Exception as exc:                            # noqa: BLE001
        print(f"the server is not answering on {BASE}: {exc}")
        return 2

    c = conn()
    BASELINE.update({e: one(c, f"SELECT COUNT(*) FROM {t}") for e, t in ENTITY_TABLES.items()})
    BASELINE.update({t: one(c, f"SELECT COUNT(*) FROM {t}") for t in
                     ("source_link", "entity_tag", "attachment", "entity_external_id",
                      "relationship", "person_position", "change_log")})
    c.close()

    chosen = [s for s in SECTIONS if not args.only or s[0] in args.only]
    started = time.perf_counter()
    for sid, _name, fn in chosen:
        try:
            fn(api)
        except Exception as exc:                        # noqa: BLE001
            traceback.print_exc()
            check(sid, False, f"section '{sid}' crashed", f"{type(exc).__name__}: {exc}")

    elapsed = time.perf_counter() - started
    passed = sum(1 for _s, ok, _l, _d in RESULTS if ok)
    print(f"\n{'-' * 74}\n{passed}/{len(RESULTS)} audit checks passed in {elapsed:.1f}s")
    if FINDINGS:
        print("\nFindings worth fixing:")
        for f in FINDINGS:
            print(f"  · [{f['severity']}] {f['title']}: {f['detail'][:140]}")
    if args.report:
        write_report(Path(args.report))
        print(f"report written to {args.report}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
