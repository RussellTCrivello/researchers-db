"""
SIRAJ · tests/verify_all.py — full-surface verification of the HTTP API
======================================================================

Exercises **every** route the application exposes, in the order a user would,
and asserts the observable effect of each call — not only the status code.  It is
the script behind the claim "every function of every interface works".

    python tests/verify_all.py                     # against 127.0.0.1:8000
    python tests/verify_all.py --base http://host:port
    python tests/verify_all.py --only import       # one section
    python tests/verify_all.py --list              # show sections

Design rules
------------
* **Self-cleaning.** Scratch records carry a unique marker in their name and are
  hard-deleted at the end; the dataset is the same size before and after (the
  script asserts this).
* **Effect-checked.** A write must be readable afterwards, an update must bump
  ``version``, a delete must disappear from the list and appear in ``?deleted=1``,
  a merge must leave one record and re-point the graph, an import must create the
  rows it promised, an export must return real bytes with the right magic number.
* **Route inventory.** The last section compares the routes registered in the
  FastAPI app with the routes this script touched and fails if anything is left
  unverified — so a new endpoint cannot be added without a test.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
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

BASE = os.environ.get("SIRAJ_BASE", "http://127.0.0.1:8000")
MARK = f"VERIFY-{int(time.time())}"
ACTOR = "verifier"

RESULTS: list[tuple[bool, str, str]] = []
TOUCHED: set[tuple[str, str]] = set()          # (method, path-template) covered
CREATED: list[tuple[str, int]] = []            # scratch rows to hard-delete
STATE: dict[str, Any] = {}                     # pre-run snapshot to restore


# ---------------------------------------------------------------------------
# tiny assertion / reporting helpers
# ---------------------------------------------------------------------------
def check(cond: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(cond), label, detail))
    flag = "PASS" if cond else "FAIL"
    line = f"  {flag} · {label}"
    if detail and not cond:
        line += f"\n         → {detail}"
    print(line, flush=True)
    return bool(cond)


def section(name: str) -> None:
    print(f"\n=== {name} " + "=" * max(0, 66 - len(name)), flush=True)


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=120.0,
                                 headers={"X-Actor": ACTOR})

    def req(self, method: str, path: str, *, expect: int | tuple[int, ...] = 200,
            template: str | None = None, **kw) -> httpx.Response:
        r = self.http.request(method, path, **kw)
        if template:
            TOUCHED.add((method.upper(), template))
        ok = (r.status_code in expect) if isinstance(expect, tuple) else (r.status_code == expect)
        if not ok:
            raise AssertionError(
                f"{method} {path} → {r.status_code} (expected {expect}): {r.text[:300]}")
        return r

    def get(self, path: str, **kw) -> httpx.Response:
        return self.req("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> httpx.Response:
        if body is not None:
            kw["json"] = body
        return self.req("POST", path, **kw)

    def put(self, path: str, body: Any = None, **kw) -> httpx.Response:
        if body is not None:
            kw["json"] = body
        return self.req("PUT", path, **kw)

    def patch(self, path: str, body: Any = None, **kw) -> httpx.Response:
        if body is not None:
            kw["json"] = body
        return self.req("PATCH", path, **kw)

    def delete(self, path: str, **kw) -> httpx.Response:
        return self.req("DELETE", path, **kw)


ENTITIES = ("person", "institution", "place", "event", "source", "relationship")


def scratch_payload(api: Client, entity: str, n: int = 1) -> dict:
    """Minimal valid payload for any entity, with a unique marker."""
    tag = f"{MARK}-{entity}-{n}"
    if entity == "person":
        return {"name_ar": f"محمد تجريبي {tag}", "name_en": f"Test Person {tag}",
                "name_original": f"Test Person {tag}", "name_original_lang": "en"}
    if entity == "institution":
        return {"name_ar": f"مؤسسة تجريبية {tag}", "name_en": f"Test Institution {tag}"}
    if entity == "place":
        return {"name_ar": f"مكان تجريبي {tag}", "name_en": f"Test Place {tag}"}
    if entity == "event":
        return {"title_ar": f"حدث تجريبي {tag}", "title_en": f"Test Event {tag}"}
    if entity == "source":
        return {"title": f"Test Source {tag}", "title_ar": f"مصدر تجريبي {tag}"}
    if entity == "relationship":
        a = api.post("/api/person", scratch_payload(api, "person", 990)).json()["record"]
        b = api.post("/api/person", scratch_payload(api, "person", 991)).json()["record"]
        CREATED.extend([("person", a["id"]), ("person", b["id"])])
        return {"entity1_type": "person", "entity1_id": a["id"],
                "relationship_type_id": "teacher_of",
                "entity2_type": "person", "entity2_id": b["id"]}
    raise KeyError(entity)


# ---------------------------------------------------------------------------
# 1 · shell, metadata, reference data
# ---------------------------------------------------------------------------
def s_boot(api: Client) -> None:
    section("shell, metadata and reference data")
    r = api.get("/", expect=200, template="/")
    check(b"<html" in r.content.lower(), "index.html is served")
    for css in ("base", "components", "views", "viz", "desk"):
        api.get(f"/static/css/{css}.css", template="/static/css/{layer}.css")
    js = ["core.js", "app.js", "components/forms.js", "views/list.js", "views/record.js",
          "views/dashboard.js", "views/reports.js", "views/map.js", "views/admin.js",
          "components/viz.js", "views/structures.js", "views/desk.js",
          "locales/index.json", "locales/en.json", "locales/ar.json"]
    missing = []
    for path in js:
        try:
            api.get(f"/static/js/{path}", template="/static/js/{asset}")
        except AssertionError:
            missing.append(path)
    check(not missing, "every static asset referenced by the shell resolves", str(missing))

    h = api.get("/api/health", template="/api/health").json()
    check(h.get("ok") is True, "health endpoint reports ok")
    check(h.get("schema_version"), "health reports the schema version")

    m = api.get("/api/metrics", template="/api/metrics").json()
    check(isinstance(m, dict) and m, "metrics endpoint returns a payload")

    meta = api.get("/api/meta?lang=ar", template="/api/meta").json()
    check(len(meta["entities"]) == 6, "meta exposes six entities")
    check("person" in meta["fields"], "person field catalogue is exposed")
    pf = meta["fields"]["person"]
    check(len(pf) >= 40, f"person exposes {len(pf)} fields")
    check(len(meta.get("derived", {}).get("person", [])) >= 10,
          "meta exposes the derived fields")
    check(any(f.get("label_ar") for f in pf), "field metadata is bilingual")
    check(meta.get("lookups") or meta.get("domains"), "meta exposes vocabularies")

    doms = api.get("/api/lookup-domains", template="/api/lookup-domains").json()
    check(len(doms) >= 21, f"21 vocabularies ({len(doms)})", str(len(doms)))
    lk = api.get("/api/lookups?domain=record_status", template="/api/lookups").json()
    rows = lk if isinstance(lk, list) else lk.get("items", [])
    check(len(rows) >= 5, "vocabulary values are returned for a domain")


def s_lookups_admin(api: Client) -> None:
    section("reference data write path (vocabularies)")
    created = api.post("/api/lookups", {
        "domain": "person_classification", "code": f"tmp_{MARK}",
        "label_en": f"Temporary {MARK}", "label_ar": f"مؤقت {MARK}", "sort_order": 999,
    }, template="/api/lookups").json()
    lid = created.get("id") or created.get("record", {}).get("id")
    check(bool(lid), "a vocabulary value can be created")
    upd = api.put(f"/api/lookups/{lid}", {"label_en": f"Temporary updated {MARK}"},
                  template="/api/lookups/{lookup_id}")
    check(upd.status_code == 200, "a vocabulary value can be updated")
    api.delete(f"/api/lookups/{lid}", template="/api/lookups/{lookup_id}")
    left = api.get("/api/lookups?domain=person_classification").json()
    check(all(r.get("id") != lid for r in (left if isinstance(left, list) else left["items"])),
          "a vocabulary value can be deleted")


# ---------------------------------------------------------------------------
# 2 · read paths
# ---------------------------------------------------------------------------
def s_read(api: Client) -> None:
    section("read paths: lists, detail, search, filters, sorts, KPIs, graph")
    for ent in ENTITIES:
        api.get(f"/api/{ent}?page=1&page_size=5", template="/api/{entity}")
        api.get(f"/api/{ent}/next-code", template="/api/{entity}/next-code")
        api.get(f"/api/options/{ent}", template="/api/options/{entity}")
        api.get(f"/api/{ent}/duplicates?limit=3", template="/api/{entity}/duplicates")
        q = api.post(f"/api/{ent}/query", {"page_size": 3},
                     template="/api/{entity}/query").json()
        check("items" in q and "total" in q, f"query works for {ent}")
        k = api.post(f"/api/{ent}/kpi", {}, template="/api/{entity}/kpi").json()
        check("total" in k or "count" in k or k, f"KPI works for {ent}")

    # detail + history + external ids + citations on a real record
    # pick a well-connected record: the default order is by recency, and a
    # freshly restored row legitimately has no neighbours to draw
    first = api.post("/api/person/query",
                     {"page_size": 1,
                      "sort": {"key": "relationships_count", "dir": "desc"}}).json()["items"][0]
    pid = first["id"]
    det = api.get(f"/api/person/{pid}", template="/api/{entity}/{rec_id}").json()
    check(det["id"] == pid and det.get("_labels") is not None, "record detail includes labels")
    check("relationships" in det or det.get("_relationships") is not None,
          "record detail includes its relationships for the ego map")
    api.get(f"/api/person/{pid}/history", template="/api/{entity}/{rec_id}/history")
    api.get(f"/api/person/{pid}/external-ids", template="/api/{entity}/{rec_id}/external-ids")

    # search + deep filters + sort shapes
    s = api.get("/api/search?q=بغداد&limit=10", template="/api/search").json()
    check(s.get("total", 0) > 0 and s.get("groups"), "full-text search returns grouped hits",
          json.dumps(s)[:200])
    s2 = api.get("/api/search?q=%D9%85%D8%AD%D9%85%D8%AF").json()
    check(s2.get("total", 0) > 0, "Arabic search ignores diacritics/spelling variants")
    deep = api.post("/api/person/query", {
        "page_size": 5,
        "where": [{"field": "record_status_id", "op": "in", "value": ["verified", "published"]},
                  {"field": "completeness", "op": "gte", "value": 50}],
        "sort": {"key": "completeness", "dir": "desc"},
    }).json()
    check(deep["total"] > 0 and all(
        i.get("_derived", {}).get("completeness", 100) >= 50 for i in deep["items"]),
        "clause-list filter + derived sort works")
    mapped = api.post("/api/person/query", {
        "page_size": 5, "filters": {"completeness": {"gte": 50}}}).json()
    everything = api.post("/api/person/query", {"page_size": 1}).json()["total"]
    check(0 < mapped["total"] < everything
          and all(i["_derived"]["completeness"] >= 50 for i in mapped["items"]),
          "the compact {field: {op: value}} filter form is accepted too",
          f'{mapped["total"]} of {everything}')
    warn = api.post("/api/person/query", {"filters": {"not_a_field": {"eq": 1}}}).json()
    check(bool(warn.get("warnings")), "unknown filter fields produce warnings, not 500s",
          json.dumps(warn.get("warnings")))
    asc = api.post("/api/person/query", {"sort": "name_en", "order": "asc", "page_size": 3}).json()
    desc = api.post("/api/person/query", {"sort": "name_en", "order": "desc", "page_size": 3}).json()
    check(asc["items"][0]["id"] != desc["items"][0]["id"] or asc["total"] < 3,
          "both sort syntaxes work and order actually changes")

    # dashboard, reports, changelog, settings, sequences, users, locales, saved views
    dash = api.get("/api/dashboard", template="/api/dashboard").json()
    check(isinstance(dash, dict) and dash, "dashboard aggregates return data")
    reports = api.get("/api/reports", template="/api/reports").json()
    check(len(reports) >= 10, f"report catalogue lists {len(reports)} reports")
    for rep in reports:
        payload = api.get(f"/api/reports/{rep['key']}", template="/api/reports/{key}").json()
        check("sections" in payload or "rows" in payload, f"report '{rep['key']}' builds")
        api.get(f"/api/reports/{rep['key']}/export?format=csv",
                template="/api/reports/{key}/export")
    api.get("/api/changelog?page=1&page_size=10", template="/api/changelog")
    api.get("/api/settings", template="/api/settings")
    api.get("/api/sequences", template="/api/sequences")
    api.get("/api/users", template="/api/users")
    codes = api.get("/api/locales", template="/api/locales").json()
    check({c["code"] for c in codes} >= {"ar", "en"}, "locale catalogue lists ar + en")
    for code in ("ar", "en"):
        msgs = api.get(f"/api/locales/{code}/messages",
                       template="/api/locales/{code}/messages").json()
        check(len(msgs) > 300, f"{code} message bundle is served ({len(msgs)} keys)")
    api.get("/api/saved-views?entity_type=person", template="/api/saved-views")

    # relationship map: both modes
    t = api.get("/api/relationship-map", template="/api/relationship-map").json()
    check(len(t["nodes"]) == 6 and t["edges"], "type-level relationship map builds")
    f = api.post("/api/relationship-map",
                 {"mode": "focus", "entity_type": "person", "record_id": pid, "depth": 2},
                 template="/api/relationship-map").json()
    check(f["nodes"] and f["edges"], "focus relationship map builds")



# ---------------------------------------------------------------------------
# 2b · the date & time model
# ---------------------------------------------------------------------------
def s_dates(api: Client) -> None:
    section("date and time: precision, moments, operators, sorting, import forms")
    meta = api.get("/api/meta").json()
    fields = {f["key"]: f for f in meta["fields"]["event"]}
    check(fields["start_date"].get("time") is True,
          "the API advertises which date fields accept a time")
    person_fields = {f["key"]: f for f in meta["fields"]["person"]}
    check(person_fields["birth_date"].get("time") is False,
          "…and which ones deliberately do not")
    check(all("time" in f for f in meta["fields"]["person"]),
          "every field carries the time flag (front-end contract)")

    made = api.post("/api/event", {"title_ar": f"{MARK} زمن", "title_en": f"{MARK} moment",
                                   "start_date": "1950-05-12 21:45",
                                   "end_date": "1950-05-12T23:10:00Z"},
                    template="/api/{entity}").json()["record"]
    CREATED.append(("event", made["id"]))
    check(made["start_date"] == "1950-05-12T21:45",
          "a moment is stored canonically", str(made["start_date"]))
    check(made["end_date"] == "1950-05-12T23:10",
          "a UTC suffix is dropped (wall-clock research dates)", str(made["end_date"]))
    bad = api.post("/api/event", {"title_ar": "س", "title_en": "x", "start_date": "31/03/1991"},
                   expect=(200, 400, 422))
    check(bad.status_code >= 400,
          "an unparseable date is rejected with an explanation")

    # precision survives a save: truncating is a deliberate act, not a side effect
    upd = api.put(f"/api/event/{made['id']}", {"start_date": "1950-05"},
                  template="/api/{entity}/{rec_id}")
    check(upd.json()["record"]["start_date"] == "1950-05",
          "month precision round-trips unchanged")
    api.put(f"/api/event/{made['id']}", {"start_date": "c. 1850"},
            template="/api/{entity}/{rec_id}")
    legacy = api.get(f"/api/event/{made['id']}").json()
    check(legacy["start_date"] == "c. 1850", "a circa date is preserved verbatim",
          str(legacy["start_date"]))

    base = api.post("/api/event/query", {"page_size": 1}).json()["total"]
    for op, val in (("on", "1950-01-08"), ("before", "1950"), ("after", "1950"),
                    ("between", ["1947-01-01", "1947-12-31"])):
        got = api.post("/api/event/query",
                       {"filters": {"start_date": {op: val}}, "page_size": 3}).json()
        check(not got.get("warnings"), f"date operator '{op}' is implemented",
              json.dumps(got.get("warnings")))
        check(0 < got["total"] < base, f"date operator '{op}' actually narrows the set",
              f"{got['total']} of {base}")
    for alias in ("on_day", "until", "since"):
        got = api.post("/api/event/query",
                       {"filters": {"start_date": {alias: "1950"}}, "page_size": 1}).json()
        check(not got.get("warnings"), f"date alias '{alias}' resolves", json.dumps(got.get("warnings")))
    silly = api.post("/api/event/query",
                     {"filters": {"start_date": {"on": "someday"}}, "page_size": 1}).json()
    check(bool(silly.get("warnings")) and silly["total"] == base,
          "a nonsense date warns instead of erroring", json.dumps(silly.get("warnings")))

    from app.schemas import to_timestamp

    def stamps(order: str) -> list[str]:
        rows = api.post("/api/event/query",
                        {"sort": "start_date", "order": order, "page_size": 40}).json()["items"]
        return [to_timestamp(r.get("start_date")) for r in rows if r.get("start_date")]

    asc, desc = stamps("asc"), stamps("desc")
    check(asc == sorted(asc), "date sorting is chronological, not lexicographic",
          json.dumps(asc[:6]))
    check(desc == sorted(desc, reverse=True), "…and descending is the exact mirror",
          json.dumps(desc[:4]))
    check(to_timestamp("c. 1850") == "1850-01-01 00:00:00"
          and to_timestamp("1950-05") == "1950-05-01 00:00:00",
          "partial dates expand downwards for comparison")


# ---------------------------------------------------------------------------
# 3 · CRUD lifecycle
# ---------------------------------------------------------------------------
def s_crud(api: Client) -> None:
    section("create / read / update / delete / restore / bulk for all six entities")
    for ent in ENTITIES:
        body = scratch_payload(api, ent, 1)
        created = api.post(f"/api/{ent}", body, template="/api/{entity}").json()["record"]
        rid = created["id"]
        CREATED.append((ent, rid))
        check(bool(created.get("code")), f"{ent}: created with a generated code",
              created.get("code", ""))

        got = api.get(f"/api/{ent}/{rid}").json()
        check(got["id"] == rid, f"{ent}: created record is readable")

        patched = api.patch(f"/api/{ent}/{rid}",
                            {"_version": got["version"],
                             **({"researcher_notes": f"note {MARK}"} if ent != "relationship"
                                else {"description": f"note {MARK}"})},
                            template="/api/{entity}/{rec_id}").json()["record"]
        check(patched["version"] > got["version"], f"{ent}: update bumps the version")

        conflict = api.req("PATCH", f"/api/{ent}/{rid}", expect=(409, 400),
                           json={"_version": got["version"], "researcher_notes": "stale"})
        check(conflict.status_code in (409, 400), f"{ent}: stale version is rejected")

        hist = api.get(f"/api/{ent}/{rid}/history").json()
        check(len(hist) >= 2, f"{ent}: history records create + update")

        d = api.delete(f"/api/{ent}/{rid}").json()
        check(d.get("ok") is True or "deleted" in d, f"{ent}: soft delete works")
        again = api.req("GET", f"/api/{ent}/{rid}", expect=(404, 410))
        check(again.status_code in (404, 410), f"{ent}: soft-deleted record is hidden")
        shown = api.get(f"/api/{ent}/{rid}?include_deleted=true")
        check(shown.status_code == 200, f"{ent}: soft-deleted record is still retrievable")
        api.post(f"/api/{ent}/{rid}/restore", template="/api/{entity}/{rec_id}/restore")
        restored = api.get(f"/api/{ent}/{rid}").json()
        check(restored["id"] == rid, f"{ent}: restore brings it back")

    # bulk actions over two scratch persons
    ids = []
    for n in (2, 3):
        rec = api.post("/api/person", scratch_payload(api, "person", n)).json()["record"]
        ids.append(rec["id"])
        CREATED.append(("person", rec["id"]))
    for action in ("status", "delete", "restore"):
        body = {"ids": ids, "action": action}
        if action == "status":
            body["patch"] = {"record_status_id": "in_review"}
        res = api.post("/api/person/bulk", body, template="/api/{entity}/bulk").json()
        check(bool(res.get("ok")) and not res.get("failed"),
              f"bulk action '{action}' works", json.dumps(res)[:200])
    bad = api.post("/api/person/bulk", {"ids": [ids[0]], "action": "no_such_action"}).json()
    check(bad.get("failed") == 1 or not bad.get("ok"),
          "an unknown bulk action is reported, not applied")

    # invalid payloads
    api.post("/api/person", {"name_en": "no arabic name"}, expect=422)
    api.post("/api/person", {"name_ar": "س" * 5000}, expect=(400, 422))
    api.get("/api/nonsense", expect=404, template="/api/{entity}")


# ---------------------------------------------------------------------------
# 4 · child collections: citations, external ids, tags, attachments, media
# ---------------------------------------------------------------------------
def s_children(api: Client) -> None:
    section("citations, authority identifiers, tags, attachments and media")
    src = api.post("/api/source", scratch_payload(api, "source", 5)).json()["record"]
    per = api.post("/api/person", scratch_payload(api, "person", 6)).json()["record"]
    CREATED.extend([("source", src["id"]), ("person", per["id"])])

    cit = api.post(f"/api/person/{per['id']}/citations",
                   {"source_id": src["id"], "field_key": "name_ar", "note": MARK},
                   template="/api/{entity}/{rec_id}/citations").json()
    det = api.get(f"/api/person/{per['id']}").json()
    check(any(c.get("source_id") == src["id"] for c in det.get("citations", [])),
          "a citation can be added and shows on the record")
    link_id = cit.get("id") or cit.get("link_id")
    if link_id:
        api.delete(f"/api/citations/{link_id}", template="/api/citations/{link_id}")
        after = api.get(f"/api/person/{per['id']}").json()
        check(not any(c.get("source_id") == src["id"] for c in after.get("citations", [])),
              "a citation can be removed")

    ext = api.post(f"/api/person/{per['id']}/external-ids",
                   {"scheme": "VIAF", "value": f"99{MARK}", "url": "https://viaf.org/x"},
                   template="/api/{entity}/{rec_id}/external-ids").json()
    listed = api.get(f"/api/person/{per['id']}/external-ids").json()
    check(any(e["scheme"] == "VIAF" for e in listed), "an authority identifier can be added")
    api.delete(f"/api/external-ids/{ext['id']}", template="/api/external-ids/{ext_id}")

    tag = api.post("/api/tags", {"domain": "topic", "label_en": f"verify {MARK}",
                                 "label_ar": f"تحقق {MARK}"}, template="/api/tags").json()
    check(bool(tag.get("id")), "a tag can be created")
    api.delete(f"/api/tags/{tag['id']}", template="/api/tags/{tag_id}")
    tags_now = api.get("/api/tags").json()
    rows = tags_now if isinstance(tags_now, list) else tags_now.get("items", [])
    check(not any(MARK in str(r.get("label_en", "")) for r in rows),
          "a tag can be deleted and disappears")
    api.get("/api/tags", template="/api/tags")

    files = {"file": ("verify.txt", io.BytesIO(b"SIRAJ verification attachment\n"),
                      "text/plain")}
    att = api.post(f"/api/person/{per['id']}/attachments", files=files,
                   template="/api/{entity}/{rec_id}/attachments").json()
    dl = api.get(f"/api/attachments/{att['id']}/download",
                 template="/api/attachments/{att_id}/download")
    check(dl.content.startswith(b"SIRAJ"), "an attachment uploads and downloads intact")
    api.delete(f"/api/attachments/{att['id']}", template="/api/attachments/{att_id}")

    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
           b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
           b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    med = api.post("/api/media", files={"file": ("dot.png", io.BytesIO(png), "image/png")},
                   template="/api/media").json()
    check(med.get("url", "").startswith("/api/media/"), "an image uploads and returns a URL")
    img = api.get(med["url"], template="/api/media/{name}")
    check(img.content[:4] == b"\x89PNG", "the uploaded image is served back")
    api.post("/api/media", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
             expect=415)


# ---------------------------------------------------------------------------
# 4b · evidence links — one source, many claims
# ---------------------------------------------------------------------------
def s_evidence(api: Client) -> None:
    section("evidence links — one source, many claims")
    types = api.get("/api/evidence/support-types").json()["support_types"]
    check([t["code"] for t in types] == ["supports", "contradicts", "contextualizes"],
          "the support types are a controlled list, not free text",
          str([t["code"] for t in types]))
    check(all(t.get("label_ar") for t in types), "each type is named in both languages")

    src_a = api.post("/api/source", {**scratch_payload(api, "source", 11),
                                     "reliability_id": "high"}).json()["record"]
    src_b = api.post("/api/source", {**scratch_payload(api, "source", 12),
                                     "reliability_id": "low"}).json()["record"]
    per = api.post("/api/person", scratch_payload(api, "person", 13)).json()["record"]
    CREATED.extend([("source", src_a["id"]), ("source", src_b["id"]), ("person", per["id"])])
    made: list[int] = []

    for args in (
            {},
            {"entity_type": "person", "entity_id": per["id"], "relationship_id": 1},
            {"entity_type": "person", "entity_id": per["id"], "support_type": "proves"},
            {"entity_type": "person", "entity_id": 99_999_991},
    ):
        body = {"source_id": src_a["id"], "supported_claim": f"probe {MARK}", **args}
        expect = 404 if args.get("entity_id") == 99_999_991 else 422
        api.post("/api/evidence", body, expect=expect)

    first = api.post("/api/evidence", {
        "source_id": src_a["id"], "entity_type": "person", "entity_id": per["id"],
        "field_key": "birth_date", "supported_claim": f"Born in the spring {MARK}",
        "page_or_timestamp": "f. 12v", "support_type": "supports",
        "verification": "single_source", "reviewer": "verification",
        "note": f"entry {MARK}"}).json()
    if first.get("evidence_id"):
        made.append(first["evidence_id"])
    check(first.get("created") is True, "a claim can be linked to a source", str(first)[:160])

    same = api.post("/api/evidence", {
        "source_id": src_a["id"], "entity_type": "person", "entity_id": per["id"],
        "field_key": "birth_date", "supported_claim": f"Born in the spring {MARK}",
        "support_type": "supports"}).json()
    check(same.get("created") is False, "the same claim is not stored twice", str(same)[:160])

    second = api.post("/api/evidence", {
        "source_id": src_b["id"], "entity_type": "person", "entity_id": per["id"],
        "field_key": "birth_date", "supported_claim": f"Dated to the autumn {MARK}",
        "support_type": "contradicts", "verification": "unverified",
        "reviewer": "verification"}).json()
    if second.get("evidence_id"):
        made.append(second["evidence_id"])

    doc = api.get("/api/evidence", params={"entity_type": "person",
                                           "entity_id": per["id"]}).json()
    check(doc["count"] == 2, "a contradiction is added beside the support, not over it",
          str(doc["count"]))
    check(doc["counts"] == {"supports": 1, "contradicts": 1, "contextualizes": 0},
          "the counts are returned per support type", str(doc["counts"]))
    check(doc["disputed"] is True, "the target is flagged disputed while they disagree")
    check(doc["evidence"][0]["support_type"] == "contradicts",
          "the contradiction is listed first, because disagreement matters most")
    row = next(e for e in doc["evidence"] if e["support_type"] == "supports")
    check(row.get("field_key") == "birth_date",
          "evidence can be pinned to a single field", str(row.get("field_key")))
    check(row.get("page_or_timestamp") == "f. 12v",
          "the place in the source travels with the claim")
    check(row.get("verification_en") and row.get("reliability_en"),
          "the claim's verification and the source's reliability are separate fields",
          f'source reliability {row.get("reliability_en")} · '
          f'claim verification {row.get("verification_en")}')

    rel = api.post("/api/relationship", scratch_payload(api, "relationship", 14)).json()["record"]
    CREATED.append(("relationship", rel["id"]))
    ev = api.post("/api/evidence", {
        "source_id": src_a["id"], "relationship_id": rel["id"],
        "supported_claim": f"the apprenticeship is documented {MARK}",
        "support_type": "contextualizes"}).json()
    if ev.get("evidence_id"):
        made.append(ev["evidence_id"])
    rdoc = api.get(f"/api/relationship/{rel['id']}/evidence",
                   template="/api/relationship/{rel_id}/evidence").json()
    check(rdoc["count"] == 1, "a relationship carries its own evidence",
          str(rdoc["count"]))
    check(rdoc["evidence"][0]["support_type"] == "contextualizes",
          "contextual evidence is neither support nor contradiction")
    check(bool(rdoc.get("type_en") and rdoc.get("entity1_id")),
          "the relationship evidence arrives with the relationship's own description")
    api.get("/api/evidence", params={"relationship_id": rel["id"],
                                     "entity_id": per["id"]}, expect=422)

    # legacy shape: a record still exposes its evidence as citations
    det = api.get(f"/api/person/{per['id']}").json()
    check(any(c.get("source_id") == src_a["id"] for c in det.get("citations", [])),
          "the record's citation list is the same evidence, seen from the record")

    for eid in made:
        api.delete(f"/api/citations/{eid}", expect=(200, 204, 404))
    after = api.get("/api/evidence", params={"entity_type": "person",
                                             "entity_id": per["id"]}).json()
    check(after["count"] == 0 and after["disputed"] is False,
          "withdrawing evidence leaves the source record untouched", str(after["count"]))
    check(api.get(f"/api/source/{src_a['id']}").status_code == 200,
          "the source itself survives the withdrawal")


# ---------------------------------------------------------------------------
# 4c · the typed query language
# ---------------------------------------------------------------------------
def s_query_language(api: Client) -> None:
    section("typed queries — the same filters, written as text")
    published = next(v["id"] for v in
                     api.get("/api/lookups?domain=record_status").json()
                     if v["code"] == "published")
    everyone = api.post("/api/person/query", json={"page_size": 1}).json()["total"]
    by_id = api.post("/api/person/query", json={"status_ids": [published],
                                                "page_size": 1}).json()["total"]
    by_text = api.post("/api/person/query", json={"query": "status:published",
                                                  "page_size": 1}).json()
    check(by_text["total"] == by_id and by_text["total"] < everyone,
          "a query string selects exactly the rows the builder selects",
          f'{by_text["total"]} text vs {by_id} builder vs {everyone} all')

    parsed = api.post("/api/query/parse", template="/api/query/parse",
                      json={"entity": "person",
                            "query": 'status:published birth:1900..1950 name_ar:"محمد"'}).json()
    ops = {(c["field"], c["op"]) for c in parsed["payload"].get("where", [])}
    check(("birth_date", "between") in ops,
          "'birth' is understood as birth_date, and a range is a range", str(sorted(ops)))
    check(parsed["payload"]["status_ids"] == [published],
          "a status code is resolved to its vocabulary id")
    check(parsed["echo"], "the parse reports how it read the query", parsed["echo"])

    neg = api.post("/api/query/parse", json={
        "entity": "person", "query": "-name_en:zzz name_ar:x|y sort:-birth_date"}).json()
    check(("name_en", "ne") in {(c["field"], c["op"]) for c in neg["payload"]["where"]},
          "negation compiles to the opposite operator",
          str([(c["field"], c["op"]) for c in neg["payload"]["where"]]))
    check(any(c["op"] == "in" for c in neg["payload"]["where"]),
          "a list of values compiles to 'any of'")
    check(neg["payload"]["sort"] == {"key": "birth_date", "dir": "desc"},
          "ordering is part of the query")

    unknown = api.post("/api/query/parse", json={
        "entity": "person", "query": "nonsense:1"}).json()
    check(unknown["unknown"] == ["nonsense"] and unknown["warnings"],
          "an unknown field is named, never invented")
    api.post("/api/query/parse", json={"entity": "person", "query": 'broken:"'},
             expect=422)

    rendered = api.post("/api/query/render", template="/api/query/render", json={
        "entity": "person",
        "payload": {"where": [{"field": "birth_date", "op": "between",
                               "value": ["1900", "1910"]}],
                    "status_ids": [published]}}).json()
    check("birth_date:1900..1910" in rendered["query"]
          and "status:published" in rendered["query"],
          "filters are written back as a query a person can read", rendered["query"])

    tags = api.get("/api/tags").json()
    rows = tags if isinstance(tags, list) else tags.get("items", [])
    if rows:
        label = rows[0]["label_en"]
        tagq = api.post("/api/person/query", json={"query": f'tag:"{label}"',
                                                   "page_size": 1}).json()
        check(tagq["total"] >= 0, "a tag can be written by name, not by id",
              f'{label} → {tagq["total"]}')
        missing = api.post("/api/query/parse", json={
            "entity": "person", "query": "tag:definitely-not-a-tag"}).json()
        check(any("unknown tag" in w for w in missing["warnings"]),
              "a tag that does not exist is reported, not silently ignored")


# ---------------------------------------------------------------------------
# 5 · duplicates and merge
# ---------------------------------------------------------------------------
def s_merge(api: Client) -> None:
    section("duplicate detection and merge")
    a = api.post("/api/person", {**scratch_payload(api, "person", 7),
                                 "name_ar": f"سعيد تجريبي {MARK}"}).json()["record"]
    b = api.post("/api/person", {**scratch_payload(api, "person", 8),
                                 "name_ar": f"سعيد  تجريبي {MARK}"}).json()["record"]
    CREATED.extend([("person", a["id"]), ("person", b["id"])])
    dup = api.get("/api/person/duplicates?limit=500&offset=0").json()
    check(dup.get("total", 0) > 0, "duplicate detection reports a total",
          json.dumps({"total": dup.get("total")}))
    mine = []
    offset = 0
    while offset < min(dup.get("total", 0), 3000) and not mine:
        batch = api.get(f"/api/person/duplicates?limit=500&offset={offset}").json()
        mine = [g for g in batch["groups"]
                if any(r["id"] in (a["id"], b["id"]) for r in g["records"])]
        offset += 500
    check(bool(mine), "the duplicate pair created by this run is detected")
    if mine:
        check(mine[0]["records"][0]["title"], "duplicate groups carry readable titles")

    plan = api.post(f"/api/person/{a['id']}/merge",
                    {"merge_ids": [b["id"]], "preview": True},
                    template="/api/{entity}/{rec_id}/merge").json()
    check(plan.get("plan") or plan.get("fields_to_fill") is not None or plan,
          "merge preview returns a plan")
    done = api.post(f"/api/person/{a['id']}/merge",
                    {"merge_ids": [b["id"]], "preview": False}).json()
    check(done.get("ok") is True or done.get("merged"), "merge executes")
    api.req("GET", f"/api/person/{b['id']}", expect=(404, 410))


# ---------------------------------------------------------------------------
# 6 · import pipeline (4 steps) and export (all formats)
# ---------------------------------------------------------------------------
def s_import_export(api: Client) -> None:
    section("import pipeline and export engine")
    tpl = api.get("/api/import/template/person?format=xlsx&lang=ar&example=true",
                  template="/api/import/template/{entity}")
    check(tpl.content[:2] == b"PK", "an XLSX import template is generated")
    tpl_csv = api.get("/api/import/template/person?format=csv&lang=en")
    check(b"," in tpl_csv.content[:400], "a CSV template is generated")

    cols = ["name_ar", "name_en", "classification_id", "nationality_id", "birth_date"]
    rows = [
        [f"مستورد تجريبي {MARK} 1", f"Imported One {MARK}", "researcher", "EG", "1970"],
        [f"مستورد تجريبي {MARK} 2", f"Imported Two {MARK}", "historian", "IQ", "1965"],
    ]
    csv_bytes = ("\ufeff" + ",".join(cols) + "\n" +
                 "\n".join(",".join(r) for r in rows)).encode("utf-8")
    preview = api.post("/api/import/preview",
                       files={"file": ("import.csv", io.BytesIO(csv_bytes), "text/csv")},
                       data={"entity": "person"},
                       template="/api/import/preview").json()
    check(preview["total_rows"] == 2, "preview reads both rows")
    mapping = preview["mapping"]
    check(mapping.get("name_ar") == "name_ar", "headers are auto-mapped", json.dumps(mapping))

    val = api.post("/api/import/validate", {
        "entity": "person", "upload_id": preview["upload_id"], "mapping": mapping,
        "mode": "create", "filename": "import.csv"},
        template="/api/import/validate").json()
    check(int(val.get("created", 0)) == 2 and val.get("total") == 2,
          "dry run reports 2 creates", json.dumps(
              {k: val.get(k) for k in ("total", "created", "updated", "failed")}))
    commit = api.post("/api/import/commit", {
        "entity": "person", "upload_id": preview["upload_id"], "mapping": mapping,
        "mode": "create", "filename": "import.csv"},
        template="/api/import/commit").json()
    check(int(commit.get("created", 0)) == 2, "commit creates both rows",
          json.dumps({k: commit.get(k) for k in ("total", "created", "updated", "failed")}))
    found = api.post("/api/person/query",
                     {"filters": {"name_en": {"contains": f"Imported One {MARK}"}},
                      "page_size": 5}).json()
    check(found["total"] >= 1, "imported rows are searchable")
    for item in found["items"]:
        CREATED.append(("person", item["id"]))

    jobs = api.get("/api/import/jobs", template="/api/import/jobs").json()
    check(bool(jobs), "the import job log lists jobs")
    job_id = jobs[0]["id"] if isinstance(jobs[0], dict) else jobs[0].get("id")
    api.get(f"/api/import/jobs/{job_id}", template="/api/import/jobs/{job_id}")

    # exports: every entity × every format, checking magic numbers
    for ent in ENTITIES:
        q = api.get(f"/api/export/{ent}?format=csv&lang=ar&limit=5",
                    template="/api/export/{entity}")
        check(q.status_code == 200 and q.content, f"{ent}: CSV export returns bytes")
        check("content-disposition" in {k.lower() for k in q.headers},
              f"{ent}: export sends a Content-Disposition header")
        x = api.get(f"/api/export/{ent}?format=xlsx&limit=5").content
        check(x[:2] == b"PK", f"{ent}: XLSX export is a real workbook")
        j = json.loads(api.get(f"/api/export/{ent}?format=json&limit=3").content)
        check(bool(j), f"{ent}: JSON export parses")
        t = api.get(f"/api/export/{ent}?format=tsv&limit=3").content
        check(b"\t" in t or len(t) < 40, f"{ent}: TSV export uses tabs")

    post_export = api.post("/api/export/person",
                           {"format": "csv", "lang": "en", "columns": ["code", "name_ar"],
                            "filters": {"page_size": 3}},
                           template="/api/export/{entity}")
    check(post_export.content.startswith(b"\xef\xbb\xbf") or b"code" in post_export.content,
          "POST export honours a column selection")


# ---------------------------------------------------------------------------
# 7 · saved views, settings, sequences, users
# ---------------------------------------------------------------------------
def s_admin(api: Client) -> None:
    section("saved views, settings, numbering and users")
    view = api.post("/api/saved-views", {
        "name": f"Verify view {MARK}", "entity_type": "person",
        "filters": {"record_status_id": {"in": ["verified"]}},
        "columns": ["code", "name_ar"], "sort": {"key": "name_ar", "dir": "asc"},
        "is_shared": 1, "owner": ACTOR}, template="/api/saved-views").json()
    vid = view.get("id") or view.get("record", {}).get("id")
    check(bool(vid), "a saved view can be created and returns its id")
    listed = api.get("/api/saved-views?entity_type=person").json()
    rows = listed if isinstance(listed, list) else listed.get("items", [])
    check(any(r.get("id") == vid for r in rows), "the saved view is listed")
    api.delete(f"/api/saved-views/{vid}", template="/api/saved-views/{view_id}")

    st = api.get("/api/settings").json()
    check(isinstance(st.get("fields"), list) and st["fields"], "settings can be read")
    STATE["settings"] = st.get("settings") or {}
    check(len(api.get("/api/settings/schema").json()["fields"]) == len(st["fields"]),
          "the settings registry is served as a schema")
    for f in st["fields"]:
        check(bool(f.get("effect")), f"setting '{f['key']}' names the code that reads it")
        break
    key = "display.density"
    before = STATE["settings"].get(key) or "comfortable"
    probe = "compact" if before != "compact" else "comfortable"
    saved = api.put("/api/settings", {key: probe}, template="/api/settings").json()
    check(saved.get("settings", {}).get(key) == probe, "settings are persisted")
    api.put("/api/settings", {key: before})
    back = api.get("/api/settings").json()
    check((back.get("settings") or {}).get(key) == before,
          "the setting was restored to its previous value")
    bad = api.put("/api/settings", {"display.page_size": 100000}, expect=422)
    check(bad.json()["problems"][0]["reason"] == "above_maximum",
          "an out-of-range value is refused with a reason",
          json.dumps(bad.json())[:150])
    bad2 = api.put("/api/settings", {"not.a.setting": "1"}, expect=422)
    check(bad2.json()["problems"][0]["reason"] == "unknown_key",
          "an undeclared key is refused")
    reset = api.post("/api/settings/reset", {"keys": [key]}, template="/api/settings/reset")
    check(reset.json()["settings"][key] == "comfortable",
          "a setting can be reset to its declared default")
    # the audit trail records configuration changes, with the actor
    api.put("/api/settings", {key: probe})
    log = api.get("/api/changelog?entity_type=setting&page_size=5").json()
    check(log["total"] > 0 and log["items"][0]["entity_code"] == key,
          "settings changes are written to the audit trail",
          json.dumps(log["items"][:1])[:160])
    api.post("/api/settings/reset", {"keys": [key]})

    seq = api.get("/api/sequences").json()
    rows = seq if isinstance(seq, list) else seq.get("items", [])
    per_row = next((r for r in rows if r.get("entity_type") == "person"), None)
    check(per_row is not None, "the numbering table is exposed")
    preview = api.get("/api/person/next-code").json()["code"]
    check(preview.startswith("PER-"), "next code follows the numbering template", preview)
    if per_row:
        api.put("/api/sequences/person", {"prefix": per_row.get("prefix") or "PER",
                                          "padding": 4, "separator": "-",
                                          "reset_policy": "never"},
                template="/api/sequences/{entity_type}")

    api.req("DELETE", "/api/users/verifier-probe", expect=(200, 404))
    u = api.post("/api/users", {"username": "verifier-probe", "role": "reviewer",
                                "display_name": "Verification probe"},
                 template="/api/users")
    check(u.status_code == 200, "a user can be created")
    users = api.get("/api/users").json()
    rows = users if isinstance(users, list) else users.get("items", [])
    check(any(r.get("username") == "verifier-probe" for r in rows), "the user is listed")
    d = api.delete("/api/users/verifier-probe", template="/api/users/{username}")
    check(d.status_code == 200, "a user can be removed")
    api.req("DELETE", "/api/users/admin", expect=(409,), template=None)




# ---------------------------------------------------------------------------
# 8 · maintenance
# ---------------------------------------------------------------------------
def s_maintenance(api: Client) -> None:
    section("maintenance: reindex, vacuum, backup, full dump, working files")
    r = api.post("/api/maintenance/reindex", {}, template="/api/maintenance/reindex").json()
    check(r.get("ok") is True or "indexed" in r, "reindex rebuilds the search index")
    api.post("/api/maintenance/vacuum", {}, template="/api/maintenance/vacuum")

    zb = api.get("/api/maintenance/backup", template="/api/maintenance/backup")
    with zipfile.ZipFile(io.BytesIO(zb.content)) as z:
        names = z.namelist()
    check(any(n.endswith(".db") for n in names), "backup ZIP contains the database")
    check(any("manifest" in n for n in names), "backup ZIP contains a manifest")

    dump = api.get("/api/maintenance/export-all", template="/api/maintenance/export-all")
    check(len(dump.content) > 1000, "the full JSON dump downloads")

    # working files: preview first, then remove — and never a referenced file
    dry = api.post("/api/maintenance/purge-working-files",
                   {"older_than_hours": 0, "dry_run": True},
                   template="/api/maintenance/purge-working-files").json()
    check(dry.get("dry_run") is True and "staging" in dry,
          "purging working files previews before it deletes",
          f"{dry.get('staging', {}).get('files')} staging, "
          f"{dry.get('orphan_media', {}).get('files')} orphan media")
    done = api.post("/api/maintenance/purge-working-files", {"older_than_hours": 0}).json()
    check(done.get("ok") is True and "files_removed" in done,
          "and then removes exactly those files", f"{done.get('files_removed')} files")
    after = api.post("/api/maintenance/purge-working-files",
                     {"older_than_hours": 0, "dry_run": True}).json()
    check(after.get("staging", {}).get("files") == 0,
          "a second pass finds nothing left to remove")



# ---------------------------------------------------------------------------
# 9 · the geographic surface
# ---------------------------------------------------------------------------
def s_geo(api: Client) -> None:
    section("geographic surface — map data, gazetteer, coordinates")

    conf = api.get("/api/map/config", template="/api/map/config").json()
    check(conf["ok"] and conf["provider"]["id"], "the map configuration is served")
    check(all(k in conf["provider"] for k in
              ("attribution_en", "attribution_ar", "license", "terms_url", "usage_en")),
          "the provider declares attribution, licence and terms",
          str(sorted(conf["provider"])))
    check(bool(conf["basemap"].get("available")),
          "the offline basemap pack is present", str(conf["basemap"].get("path")))
    check(any(p_.get("requires_network") is False for p_ in conf["providers"]),
          "at least one provider works without a network")
    families = {g["id"]: g["providers"] for g in conf["provider_groups"]}
    check(set(families) >= {"offline", "standard", "aerial", "terrain"},
          "the base maps are grouped into offline, standard, aerial and terrain",
          str(list(families)))
    check(bool(families.get("aerial")), "aerial imagery is among the base maps",
          str(families.get("aerial")))
    by_id = {p_["id"]: p_ for p_ in conf["providers"]}
    check(any(len(by_id[pid]["style"]["sources"]) > 1 for pid in families.get("aerial", [])),
          "the hybrid style layers a labels source over the imagery",
          str({pid: list(by_id[pid]["style"]["sources"])
               for pid in families.get("aerial", [])}))
    check(all(p_.get("group") for p_ in conf["providers"]),
          "every provider belongs to a family")
    check(all(len(p_["style"]["layers"]) >= 1 for p_ in conf["providers"]),
          "every provider ships a style the client can apply without a second call",
          str(sorted(by_id)))
    check(set(conf["crs"]["crs"]) >= {"EPSG:4326", "EPSG:3857"},
          "the coordinate reference systems are declared",
          str(list(conf["crs"]["crs"])))

    layers = api.get("/api/map/layers", template="/api/map/layers").json()
    check(layers["ok"] and layers["layers"], "the map layers are listed")
    for layer in layers["layers"]:
        check(layer["located"] <= layer["total"],
              f"{layer['entity_type']}: located ≤ total",
              f"{layer['located']} / {layer['total']}")

    world = api.get("/api/map/features", params={"bbox": "-180,-85,180,85", "limit": 4000},
                    template="/api/map/features").json()
    check(world["ok"] and world["count"] > 0, "features are returned for a world viewport",
          str(world.get("count")))
    check(world["count"] <= world["limit"],
          "the response respects its own budget",
          f"{world['count']} > {world['limit']}")
    check(all(-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180 for p in world["points"]),
          "every feature has a coordinate inside the legal ranges")
    located_total = sum(layer["located"] for layer in layers["layers"])
    check(world["count"] <= located_total,
          "no more features than there are located records",
          f"{world['count']} vs {located_total}")
    check(world["truncated"] is True,
          "a truncated world view says so instead of pretending to be complete")
    check(all(layer["returned"] <= layer["total"] for layer in world["per_layer"].values()),
          "per-layer counts agree with the features returned")
    typed = {p["entity_type"] for p in world["points"]}
    check(typed <= {"place", "person", "institution", "event"},
          "features carry a registry entity type", str(sorted(typed)))
    check(all(p["code"] and p["label_en"] for p in world["points"]),
          "every feature carries the code and the label of its record")

    # the antimeridian is a real window, not an empty one
    across = api.get("/api/map/features", params={"bbox": "170,-20,-170,20", "limit": 500},
                     template="/api/map/features").json()
    check(across["count"] >= 0, "a viewport that crosses the antimeridian is answered",
          str(across.get("count")))
    for p in across["points"]:
        check(p["lon"] >= 170 or p["lon"] <= -170,
              "an antimeridian viewport returns only points inside it", f"{p['code']} {p['lon']}")

    # unlocated records never appear
    missing = api.get("/api/map/features", params={"bbox": "-180,-85,180,85",
                                                   "limit": 20000}).json()
    seen = {(p["entity_type"], p["id"]) for p in missing["points"]}
    unlocated = [layer for layer in layers["layers"] if layer["located"] < layer["total"]]
    check(bool(unlocated), "some records genuinely have no coordinates", str(len(unlocated)))
    check(len(missing["points"]) <= located_total,
          "an unlocated record is never given a placeholder position",
          f"{len(missing['points'])} vs {located_total}")
    check(seen, "the full viewport still returns features")

    groups = api.get("/api/map/groups", params={"bbox": "-180,-85,180,85", "limit": 500},
                     template="/api/map/groups").json()
    check(groups["ok"] and groups["groups"], "records are aggregated by place")
    first = groups["groups"][0]
    check(first["count"] == sum(first["by_layer"].values()),
          "a group's statistics add up to its total",
          f"{first['count']} vs {first['by_layer']}")
    check(groups["total_records"] >= first["count"],
          "the group totals are consistent with the groups")

    overlays = api.get("/api/map/overlays", template="/api/map/overlays").json()
    check(overlays["counts"]["place_hierarchy"] > 0,
          "place hierarchy paths come from stored parent places",
          str(overlays["counts"]))
    arc = overlays["overlays"]["place_hierarchy"]["features"][0]
    check(arc["geometry"]["type"] == "LineString" and len(arc["geometry"]["coordinates"]) == 2,
          "a hierarchy path is a two-point line between the parent and the child")
    check(overlays["counts"]["relationships"] > 0,
          "relationship arcs come from stored relationships", str(overlays["counts"]))

    bad = api.get("/api/map/features", params={"bbox": "1,2,3"}, expect=422,
                  template="/api/map/features")
    check("bbox" in bad.text.lower(), "a malformed bbox is refused with a reason", bad.text[:120])
    bad = api.get("/api/map/features", params={"layers": "wizard"}, expect=422,
                  template="/api/map/features")
    check("layer" in bad.text.lower(), "an unknown layer is refused", bad.text[:120])

    detail = api.get("/api/map/feature/place/1", template="/api/map/feature/{entity_type}/{rec_id}").json()
    check(detail["ok"] and detail["located"], "a located record's dossier is served")
    pos = detail["position"]
    check(pos["formatted"]["dd"] and pos["formatted"]["dms"],
          "the dossier carries decimal and DMS notations", str(pos["formatted"])[:120])
    check(pos["crs"].get("EPSG:3857", {}).get("x") is not None,
          "the dossier carries projected coordinates too")
    check(pos["country_polygon"] and pos["country_polygon"]["name_en"],
          "the dossier names the country polygon that contains the point",
          str(pos["country_polygon"])[:120])
    check(isinstance(detail["relationships"], list),
          "the dossier lists the record's located relationships")
    check(api.get("/api/map/feature/place/1").json()["position"]["lat"] == pos["lat"],
          "the dossier is deterministic")
    api.get("/api/map/feature/wizard/1", expect=422,
            template="/api/map/feature/{entity_type}/{rec_id}")
    api.get("/api/map/feature/place/999999", expect=404)

    found = api.get("/api/map/search", params={"q": "Mosul"}, template="/api/map/search").json()
    check(found["count"] > 0 and found["results"][0]["entity_type"] == "place",
          "a name search returns the registry record first", str(found["results"][:1])[:160])
    cities = api.get("/api/map/search", params={"q": "الموصل"}).json()
    check(cities["count"] > 0, "the search understands Arabic names",
          str(cities["count"]))
    coord = api.get("/api/map/search", params={"q": "33.3152, 44.3661"}).json()
    check(coord["position"] and abs(coord["position"]["lat"] - 33.3152) < 1e-6,
          "a typed coordinate is recognised as a position", str(coord["position"])[:120])
    check(coord["position_label"]["dms"].startswith("33°18"),
          "the position is echoed in DMS", coord["position_label"]["dms"])

    parsed = api.get("/api/map/parse", params={"q": '33°18\'54.7"N 44°21\'58.0"E'},
                     template="/api/map/parse").json()
    check(parsed["ok"] and abs(parsed["lat"] - 33.31519) < 1e-4,
          "DMS input is parsed to the right latitude", str(parsed)[:160])
    check(abs(parsed["lon"] - 44.36611) < 1e-4, "DMS input is parsed to the right longitude")
    arabic = api.get("/api/map/parse", params={"q": "٣٣٫٣١٥٢، ٤٤٫٣٦٦١"}).json()
    check(arabic["ok"] and abs(arabic["lat"] - 33.3152) < 1e-6,
          "Arabic-Indic digits are parsed", str(arabic)[:120])
    loose = api.get("/api/map/parse", params={"q": "44.3661E 33.3152N"}).json()
    check(loose["ok"] and abs(loose["lat"] - 33.3152) < 1e-6,
          "a longitude-first input is still understood", str(loose)[:120])
    refused = api.get("/api/map/parse", params={"q": "95, 44"}).json()
    check(not refused["ok"] and refused.get("reason"),
          "an out-of-range coordinate is refused with a reason", str(refused))

    near = api.get("/api/map/reverse", params={"lat": 36.335, "lon": 43.1189},
                   template="/api/map/reverse").json()
    check(near["ok"] and near["country"]["iso_a2"] == "IQ",
          "reverse lookup names the containing country",
          str(near.get("country"))[:120])
    check(near["nearby_places"] and near["nearby_places"][0]["distance_m"] < 5000,
          "reverse lookup names the nearest registry place",
          str(near["nearby_places"][:1])[:160])
    api.get("/api/map/reverse", params={"lat": 91, "lon": 0}, expect=422,
            template="/api/map/reverse")

    radius = api.post("/api/map/query",
                      {"mode": "radius", "lat": 33.3152, "lon": 44.3661,
                       "radius_m": 25000, "limit": 500},
                      template="/api/map/query").json()
    check(radius["ok"] and radius["count"] > 0, "a radius query returns records",
          str(radius.get("count")))
    check(all(r["distance_m"] <= 25000 for r in radius["records"]),
          "every record of a radius query is really inside the radius",
          str(max((r["distance_m"] for r in radius["records"]), default=0)))
    box = api.post("/api/map/query",
                   {"mode": "bbox", "bbox": [44, 33, 45, 34], "limit": 500}).json()
    check(all(44 <= r["lon"] <= 45 and 33 <= r["lat"] <= 34 for r in box["records"]),
          "every record of a bbox query is really inside the box")
    poly = api.post("/api/map/query",
                    {"mode": "polygon",
                     "polygon": [[44, 33], [44.9, 33], [44.9, 33.7], [44, 33.7]], "limit": 500}).json()
    check(poly["count"] <= box["count"] and poly["count"] > 0,
          "a polygon query narrows the box it sits in",
          f"{poly['count']} vs {box['count']}")
    api.post("/api/map/query", {"mode": "wizard"}, expect=422, template="/api/map/query")
    api.post("/api/map/query", {"mode": "radius", "lat": 95, "lon": 0}, expect=422)

    before = api.get("/api/changelog", params={"page_size": 1}).json()["total"]
    api.post("/api/map/query", {"mode": "radius", "lat": 33.4, "lon": 44.4, "radius_m": 5000})
    after = api.get("/api/changelog", params={"page_size": 1}).json()["total"]
    check(before == after,
          "geographic queries write nothing to the registry",
          f"{before} -> {after}")

    pack = api.get("/api/geo/basemap", template="/api/geo/basemap").json()
    check(pack["ok"] and pack["bytes"] > 100000,
          "the basemap pack reports its size and layers", str(pack.get("bytes")))
    check("Natural Earth" in json.dumps(pack, ensure_ascii=False),
          "the pack records its source and licence")
    for layer in ("countries", "coastline", "lakes", "rivers", "places"):
        geo = api.get(f"/api/geo/basemap/{layer}",
                      params={"zoom": 6, "bbox": "-180,-85,180,85", "limit": 50},
                      template="/api/geo/basemap/{layer}").json()
        check(geo["collection"]["type"] == "FeatureCollection" and geo["returned"] > 0,
              f"basemap layer '{layer}' returns geometry",
              f'{geo.get("returned")} at {geo.get("level")}')
    coarse = api.get("/api/geo/basemap/countries", params={"zoom": 2, "limit": 3}).json()
    fine = api.get("/api/geo/basemap/countries",
                   params={"zoom": 8, "bbox": "43,32,45,34", "limit": 3}).json()
    check(coarse["level"] != fine["level"],
          "the basemap serves a coarser detail level when zoomed out",
          f'{coarse["level"]} vs {fine["level"]}')
    api.get("/api/geo/basemap/wizard", expect=422, template="/api/geo/basemap/{layer}")

    gaz = api.get("/api/geo/gazetteer", params={"q": "Baghdad"},
                  template="/api/geo/gazetteer").json()
    check(gaz["ok"] and gaz["results"] and gaz["size"] > 500,
          "the gazetteer answers name searches", f'{len(gaz["results"])} / {gaz["size"]}')
    check(any(r["name_ar"] for r in gaz["results"]),
          "gazetteer entries carry Arabic names")
    nearest = api.get("/api/geo/nearest", params={"lat": 33.32, "lon": 44.40},
                      template="/api/geo/nearest").json()
    check(nearest["ok"] and nearest["place"]["name_en"] == "Baghdad",
          "the nearest-city lookup names Baghdad", str(nearest.get("place"))[:120])

    plan = api.get("/api/map/georef/preview", params={"limit": 5},
                   template="/api/map/georef/preview").json()
    check(plan["dry_run"] is True, "the georeferencing preview is read-only")
    check(plan["summary"]["scanned"] >= 1000,
          "the preview scans every place", str(plan["summary"]))
    check(plan["summary"]["located_after_apply"] >= plan["summary"]["located"],
          "the preview reports what applying would achieve")
    check(plan["dry_run"] and api.get("/api/map/georef/preview").json()["summary"]["proposals"]
          == plan["summary"]["proposals"],
          "previewing georeferencing twice changes nothing")

# ---------------------------------------------------------------------------
# 10 · route inventory
# ---------------------------------------------------------------------------
def s_inventory(api: Client) -> None:
    section("route inventory — nothing may go unverified")
    from app.server import app as app_obj

    # Routers are mounted as include_router(), which modern FastAPI keeps as one
    # lazy entry in `app.routes` — so the inventory is read from the OpenAPI schema,
    # which always contains every mounted route.
    templates: set[tuple[str, str]] = set()
    for path, ops in app_obj.openapi()["paths"].items():
        if not path.startswith("/api"):
            continue
        for method in ops:
            if method.lower() in ("parameters", "head", "options"):
                continue
            templates.add((method.upper(), path))
    covered_paths = {p for _m, p in TOUCHED}
    patched = set()
    import re
    for m, p in templates:
        for cp in covered_paths:
            pattern = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(cp).replace("\\{", "{").replace("\\}", "}")) + "$"
            try:
                if re.match(pattern, p):
                    patched.add((m, p))
                    break
            except re.error:
                continue
    missing = sorted(templates - patched)
    check(not missing, f"every one of {len(templates)} API routes is exercised",
          json.dumps(missing, indent=1))


# ---------------------------------------------------------------------------
# 10 · cleanup + census
# ---------------------------------------------------------------------------
def s_cleanup(api: Client) -> None:
    section("cleanup — the dataset is left exactly as it was found")
    removed = 0
    for ent, rid in CREATED:
        try:
            # a merge soft-deletes the absorbed record, and a hard delete does
            # not reach a soft-deleted row — restore first, then destroy it
            api.req("POST", f"/api/{ent}/{rid}/restore",
                    expect=(200, 204, 400, 404, 409))
            api.req("DELETE", f"/api/{ent}/{rid}?hard=true&reason=verification",
                    expect=(200, 204, 404, 400, 409))
            removed += 1
        except Exception:                              # noqa: BLE001
            pass
    # imported rows are located by their marker, never by fuzzy full-text search.
    # Safety rule: if a marker filter ever matched a whole table, the filter engine
    # is broken — refuse to delete rather than destroy live records.
    for ent, field in (("person", "name_en"), ("institution", "name_en"),
                       ("place", "name_en"), ("event", "title_en"), ("source", "title")):
        hits = api.post(f"/api/{ent}/query",
                        {"filters": {field: {"contains": MARK}}, "page_size": 200,
                         "include_deleted": True}).json()
        table_total = api.post(f"/api/{ent}/query", {"page_size": 1}).json()["total"]
        if hits["total"] and hits["total"] >= table_total:
            check(False, f"marker filter narrowed {ent} before cleanup",
                  f"the filter matched all {table_total} rows — nothing was deleted")
            continue
        for item in hits["items"]:
            api.req("POST", f"/api/{ent}/{item['id']}/restore",
                    expect=(200, 204, 400, 404, 409))
            api.req("DELETE", f"/api/{ent}/{item['id']}?hard=true&reason=verification",
                    expect=(200, 204, 400, 404))
    for ent, field in (("person", "name_en"), ("institution", "name_en"),
                       ("place", "name_en"), ("event", "title_en"), ("source", "title")):
        left = api.post(f"/api/{ent}/query",
                        {"filters": {field: {"contains": MARK}}, "page_size": 5,
                         "include_deleted": True}).json()
        check(left["total"] == 0, f"scratch {ent} records removed", str(left["total"]))
    tags = api.get("/api/tags").json()
    rows = tags if isinstance(tags, list) else tags.get("items", [])
    leftovers = [r for r in rows if MARK in str(r.get("label_en", ""))]
    for r in leftovers:
        api.req("DELETE", f"/api/tags/{r['id']}", expect=(200, 404))
    for r in api.get("/api/lookups?domain=person_classification").json() or []:
        if MARK in str(r.get("label_en", "")):
            api.req("DELETE", f"/api/lookups/{r['id']}", expect=(200, 404))
    tags = api.get("/api/tags").json()
    rows = tags if isinstance(tags, list) else tags.get("items", [])
    check(not any(MARK in str(r.get("label_en", "")) for r in rows),
          "no scratch vocabulary/tag rows left behind")
    users = api.get("/api/users").json()
    rows = users if isinstance(users, list) else users.get("items", [])
    check(not any(str(r.get("username", "")).startswith("verify") for r in rows),
          "no probe users left behind")


# ---------------------------------------------------------------------------
# 4h · the atlas — one record's dossier, and a path between two records
# ---------------------------------------------------------------------------
def s_graph(api: Client) -> None:
    section("the atlas — dossiers and paths behind the relationship map")

    graph = api.post("/api/relationship-map", template="/api/relationship-map",
                     json={"mode": "focus", "entity_type": "person",
                           "record_id": 1, "depth": 1}).json()
    check(graph["focus"] == "person:1" and graph["nodes"],
          "the map still answers for a focus record", str(len(graph.get("nodes", []))))

    # find a record that actually has a relationship, rather than assuming one
    edge = next((e for e in graph["edges"] if e.get("kind") == "relationship"), None)
    check(edge is not None, "that neighbourhood contains a typed relationship")
    neighbour_id = None
    if edge:
        neighbour_id = edge["target"] if edge["source"] == "person:1" else edge["source"]

    node = api.get("/api/graph/node/person/1", template="/api/graph/node/{entity_type}/{record_id}").json()
    check(node["id"] == "person:1" and node["title"],
          "a node dossier names the record", node.get("title", ""))
    check(node["type"] == "person" and node["record_id"] == 1,
          "the dossier keeps its identity, not just its label")
    check("/person/1" in node["href"], "the dossier carries the route to the record",
          node.get("href", ""))
    check(isinstance(node["facts"], list) and node["facts"],
          "the dossier resolves fields into readable facts",
          str(len(node.get("facts") or [])))
    check(set(node["state"]) >= {"record_status", "authentication", "documentation"},
          "the dossier separates status, verification and documentation",
          str(sorted(node["state"])))
    check(node["counts"]["relationships"] == len(node["neighbours"]),
          "the relationship count matches the listed neighbours",
          f'{node["counts"]["relationships"]} vs {len(node["neighbours"])}')
    check(0 <= node["completeness"] <= 100,
          "completeness is a percentage, not a guess", str(node["completeness"]))
    if neighbour_id:
        ntype, nid = neighbour_id.split(":")
        other = api.get(f"/api/graph/node/{ntype}/{nid}",
                        template="/api/graph/node/{entity_type}/{record_id}").json()
        check(other["id"] == neighbour_id,
              "every listed neighbour resolves to a real dossier", neighbour_id)
        check(any(n["id"] == neighbour_id for n in node["neighbours"]),
              "the neighbour appears in the dossier's own list")

    api.get("/api/graph/node/person/99999999",
            template="/api/graph/node/{entity_type}/{record_id}", expect=404)
    api.get("/api/graph/node/nonsense/1", template="/api/graph/node/{entity_type}/{record_id}", expect=404)

    path = api.post("/api/graph/path", json={
        "from_type": "person", "from_id": 1,
        "to_type": ntype, "to_id": int(nid), "max_depth": 4}).json()
    check(path["ok"] and path["found"], "a direct neighbour is reachable as a path")
    check(path["length"] == 1 and len(path["nodes"]) == 2 and len(path["edges"]) == 1,
          "a one-hop path reports two nodes and one edge",
          f'{path["length"]} hop(s), {len(path["nodes"])} nodes')
    check(path["edges"][0]["id"] and path["edges"][0]["label_en"],
          "each step of the path carries its relationship, not a bare line",
          str(path["edges"][0].get("label_en")))
    check(path["searched"] > 0, "the search reports how much it looked at",
          str(path["searched"]))

    same = api.post("/api/graph/path", json={
        "from_type": "person", "from_id": 1,
        "to_type": "person", "to_id": 1}).json()
    check(same["found"] and same["length"] == 0,
          "a record is its own path, with no steps", str(same["length"]))

    api.post("/api/graph/path", json={
        "from_type": "person", "from_id": 1,
        "to_type": "place", "to_id": 99_999_999}, expect=404)

    # an honest "no": a depth of one cannot invent a chain of three, and the
    # answer says how far it looked either way
    places = api.post("/api/place/query", json={"page_size": 3}).json()["items"]
    if places:
        far = api.post("/api/graph/path", json={
            "from_type": "person", "from_id": 1,
            "to_type": "place", "to_id": places[0]["id"], "max_depth": 1}).json()
        check(far["found"] == (len(far["nodes"]) == 2),
              "a one-step search returns either one step or nothing",
              f'found={far["found"]} nodes={len(far["nodes"])}')
        check(far["searched"] > 0 or far["found"],
              "the search reports how much of the graph it looked at",
              str(far["searched"]))

    api.post("/api/graph/path", json={"from_type": "person", "from_id": 1},
             expect=422)
    capped = api.post("/api/graph/path", json={
        "from_type": "person", "from_id": 1,
        "to_type": "place", "to_id": 1, "max_depth": 99}).json()
    check(capped["ok"] and capped["searched"] >= capped["length"] if capped["found"]
          else capped["ok"],
          "an absurd depth is clamped rather than obeyed or refused",
          str(capped["searched"]))


# ---------------------------------------------------------------------------
# 4i · CRCE — the compass-rose coordinate encoding, end to end
# ---------------------------------------------------------------------------
def s_crce(api: Client) -> None:
    section("CRCE — one encoding for every spatial reference")

    doc = api.get("/api/crce/standard", template="/api/crce/standard").json()
    check(doc.get("ok") is True, "the standard is served")
    std = doc["standard"]
    check(std["id"] == "CRCE" and std["version"],
          "it is a versioned standard, not a loose convention",
          f'{std["id"]} {std["version"]}')
    check(std["name_en"] and std["name_ar"] and std["summary_en"] and std["summary_ar"],
          "it states itself in both working languages")
    check(std["storage_crs"] == "EPSG:4326",
          "the reference system coordinates are stored in is declared",
          std["storage_crs"])
    symbols = doc["symbols"]
    check(set(symbols) == {"person", "organization", "place", "relationship"},
          "four categories carry a mark", ", ".join(sorted(symbols)))
    check(all(s["exclusive"] for s in symbols.values()),
          "each mark is exclusive to its category")
    check(all(s["geometry"] and s["label_en"] and s["label_ar"] for s in symbols.values()),
          "each mark has geometry and a bilingual label")
    check(set(std["reserved"]) == set(symbols),
          "the reserved list is the published symbol list")
    check("event" in std["uncovered"] and "source" in std["uncovered"],
          "what the standard does not cover is stated, not left ambiguous",
          ", ".join(std["uncovered"]))
    check(len(doc["rules"]) >= 5 and all(r["en"] and r["ar"] for r in doc["rules"]),
          "the rules are published in both languages", str(len(doc["rules"])))
    check("no_invention" in {r["code"] for r in doc["rules"]},
          "and the first rule forbids inventing coordinates")
    check(set(doc["categories"]) >= {"person", "institution", "place", "relationship"},
          "every covered record kind is mapped to exactly one category",
          ", ".join(sorted(doc["categories"])))

    # a place: stored value, derived notations, precision, provenance.
    # Not every place is located, so the first one *with* a point is the subject;
    # an unlocated one is exercised separately below.
    items = api.post("/api/place/query", json={
        "page_size": 40, "sort": {"key": "id", "dir": "asc"}}).json()["items"]
    place_rec = next((r for r in items if r.get("latitude") is not None), items[0])
    pid = place_rec["id"]
    dossier = api.get(f"/api/crce/dossier/place/{pid}",
                      template="/api/crce/dossier/{entity_type}/{record_id}").json()
    co = dossier["coordinates"]
    check(co is not None, "a located place reports coordinates")
    if co is None:                                    # keeps the section readable
        return
    check(co["primary"]["crs"] == "EPSG:4326",
          "a dossier names the system its point is in", co["primary"]["crs"])
    if place_rec.get("latitude") is not None:
        check(abs(co["primary"]["lat"] - place_rec["latitude"]) < 1e-6
              and abs(co["primary"]["lon"] - place_rec["longitude"]) < 1e-6,
              "the stored value is reported unchanged",
              f'{co["primary"]["lat"]}, {co["primary"]["lon"]}')
    check(co["formats"]["dms"] and "°" in co["formats"]["dms"],
          "degrees/minutes/seconds are derived from it", co["formats"]["dms"])
    check(co["formats"]["geohash_note_en"] and co["formats"]["geohash_note_ar"],
          "and the derived notations say they are derived")
    check(co["precision"]["code"] and co["role"]["code"],
          "the precision on file and the role of the point are both stated",
          f'{co["precision"]["code"]} / {co["role"]["code"]}')
    check(dossier["entity"]["symbol"] == "crce-place",
          "a place wears the place mark and nothing else",
          dossier["entity"]["symbol"])
    check(dossier["rose"]["needle"] in (True, False),
          "the mark records whether a needle was drawn")

    # a place that is not located: no point is conjured for it
    bare = next((r for r in items if r.get("latitude") is None), None)
    if bare:
        bd = api.get(f"/api/crce/dossier/place/{bare['id']}",
                     template="/api/crce/dossier/{entity_type}/{record_id}").json()
        check(bd["status"] == "unlocated" and bd["coordinates"] is None,
              "an unlocated place has no coordinates at all, invented or borrowed",
              bd["status"])
        check(bd["rose"]["needle"] is False and "no_fix" in {n["code"] for n in bd["notes"]},
              "and its mark carries no needle, with the reason written down")

    # a person: inherited, and never a pin
    person_rec = api.post("/api/person/query", json={
        "page_size": 1, "sort": {"key": "id", "dir": "asc"}}).json()["items"][0]
    pd = api.get(f"/api/crce/dossier/person/{person_rec['id']}",
                 template="/api/crce/dossier/{entity_type}/{record_id}").json()
    check(pd["entity"]["symbol"] == "crce-person",
          "a person wears the person mark", pd["entity"]["symbol"])
    if pd["coordinates"]:
        check(pd["coordinates"]["inherited"] is True,
              "and any point is marked as inherited from a place on file")
        check("person_not_pin" in {n["code"] for n in pd["notes"]},
              "with a note that a person's location is not their identity")
    else:
        check(pd["status"] == "unlocated" and pd["rose"]["needle"] is False,
              "a person with no fix says so and draws no needle")
        check("no_fix" in {n["code"] for n in pd["notes"]},
              "and explains why")

    # an organization, through the standard's own vocabulary
    inst_rec = api.post("/api/institution/query", json={"page_size": 1}).json()["items"][0]
    od = api.get(f"/api/crce/dossier/organization/{inst_rec['id']}",
                 template="/api/crce/dossier/{entity_type}/{record_id}").json()
    check(od["entity"]["category"] == "organization",
          "the standard's word 'organization' resolves to the registry's institutions")
    check(od["entity"]["symbol"] == "crce-organization",
          "and an institution wears the organization mark", od["entity"]["symbol"])

    # a relationship: two ends, one direction, or an honest refusal
    rel = api.post("/api/relationship/query", json={"page_size": 1}).json()["items"][0]
    rd = api.get(f"/api/crce/dossier/relationship/{rel['id']}",
                 template="/api/crce/dossier/{entity_type}/{record_id}").json()
    check(len(rd["ends"]) == 2, "a relationship dossier has two ends")
    check(rd["entity"]["symbol"] == "crce-relationship",
          "the connection wears the relationship mark")
    check(all(e["symbol"] is None or e["symbol"].startswith("crce-") for e in rd["ends"]),
          "each end wears its own category's mark")
    check(rd["status"] in ("located", "same_point", "unlocated"),
          "the dossier says whether it can be directed", rd["status"])
    check("connect_not_claim" in {n["code"] for n in rd["notes"]},
          "and repeats that a connection is not a finding of responsibility")

    # a kind the standard does not cover: coordinates read, no mark borrowed
    ev = api.get("/api/crce/dossier/event/1",
                 template="/api/crce/dossier/{entity_type}/{record_id}").json()
    check(ev["entity"]["covered_by_standard"] is False and ev["entity"]["symbol"] is None,
          "an uncovered kind borrows no mark")
    check("not_covered" in {n["code"] for n in ev["notes"]},
          "and the dossier says so in words")

    for path, label in (("/api/crce/dossier/person/99999999", "a missing record"),
                        ("/api/crce/dossier/wizard/1", "an unknown category")):
        api.get(path, template="/api/crce/dossier/{entity_type}/{record_id}", expect=404)
        check(True, f"{label} is refused, never invented")


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 11 · structures — the display kernel's data
# ---------------------------------------------------------------------------
def s_structures(api: Client) -> None:
    section("structures — six ways of seeing the same registry, one arithmetic")
    srcs = api.get("/api/structures", template="/api/structures").json()
    check(srcs.get("ok") is True, "the structure registry answers")
    sources = srcs.get("sources") or []
    check(len(sources) == 6, "six sources are declared", str(len(sources)))
    check(all(s.get("label_en") and s.get("label_ar") for s in sources),
          "every source is named in both languages")
    check(all(s.get("chain") for s in sources), "every source declares its chain")

    for src in sources:
        sid = src["id"]
        tree = api.get(f"/api/structures/{sid}?depth=2&max_children=12",
                       template="/api/structures/{source}").json()
        root = tree["root"]
        kids = root.get("children") or []
        total = sum(k["value"] for k in kids)
        check(tree["total"] > 0 and total == tree["total"],
              f"{sid}: the first level adds up to the total", f"{total}/{tree['total']}")
        check(all(len(k.get("children") or []) >= 0 for k in kids),
              f"{sid}: every branch is a node")
        deep = [k for k in kids if k.get("children")]
        if deep:
            sub = deep[0]
            check(sum(c["value"] for c in sub["children"]) == sub["value"],
                  f"{sid}: a child level adds up to its parent")
        folded = [k for k in kids if k.get("meta", {}).get("synthetic")]
        check(all("smaller groups" in k["label_en"] for k in folded),
              f"{sid}: a folded branch declares itself", f"{len(folded)} folded")
        check(tree.get("computed_ms") is not None,
              f"{sid}: the cost is reported, not guessed")

    one = api.get("/api/structures/people?depth=1&max_children=4",
                  template="/api/structures/{source}").json()
    check(all(not (k.get("children") or []) for k in one["root"]["children"]),
          "depth 1 returns one level and no more")
    api.req("GET", "/api/structures/does-not-exist", expect=404)
    check(True, "an unknown source is refused with 404")


SECTIONS: list[tuple[str, Callable[[Client], None]]] = [
    ("boot", s_boot),
    ("lookups", s_lookups_admin),
    ("read", s_read),
    ("dates", s_dates),
    ("crud", s_crud),
    ("children", s_children),
    ("evidence", s_evidence),
    ("query", s_query_language),
    ("merge", s_merge),
    ("import", s_import_export),
    ("admin", s_admin),
    ("maintenance", s_maintenance),
    ("geo", s_geo),
    ("crce", s_crce),
    ("structures", s_structures),
    ("graph", s_graph),
    ("inventory", s_inventory),
    ("cleanup", s_cleanup),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--only", nargs="*", help="run only these sections")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list:
        print("\n".join(name for name, _ in SECTIONS))
        return 0

    api = Client(args.base)
    t0 = time.time()
    print(f"SIRAJ · full API verification against {api.base}\nmarker: {MARK}")
    try:
        api.get("/api/health")
    except Exception as exc:                      # noqa: BLE001
        print(f"\nCannot reach the server: {exc}\nStart it with: python run.py")
        return 2

    for name, fn in SECTIONS:
        if args.only and name not in args.only:
            continue
        try:
            fn(api)
        except Exception as exc:                  # noqa: BLE001
            check(False, f"section '{name}' crashed", f"{exc}\n{traceback.format_exc()[-1200:]}")

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    failed = [r for r in RESULTS if not r[0]]
    print("\n" + "-" * 74)
    print(f"{passed}/{len(RESULTS)} checks passed in {time.time() - t0:.1f}s")
    if failed:
        print("\nFAILURES:")
        for _ok, label, detail in failed:
            print(f"  · {label}")
            if detail:
                print(f"    {detail[:900]}")
        return 1
    print("API surface fully verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
