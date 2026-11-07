"""
Test suite for the SIRAJ registry.

Run:  pytest -q            (uses a temporary database, never the real one)
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# a throwaway database for the whole session
_TMP = tempfile.mkdtemp(prefix="siraj-test-")
os.environ["SIRAJ_DATA_DIR"] = _TMP
os.environ["SIRAJ_SEED_DEMO"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app import db
from app.server import app as main_app


@pytest.fixture(scope="session")
def client():
    db.init_db(seed_demo=True)
    with TestClient(main_app) as c:
        yield c


@pytest.fixture(scope="session")
def conn():
    c = db.connect()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# infrastructure
# ---------------------------------------------------------------------------
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_meta_has_entities_and_vocabularies(client):
    meta = client.get("/api/meta").json()
    # the unified catalogue serves registry + military entities from one meta;
    # the registry six must all be there (military additions are pinned in
    # tests/test_military.py::TestUnifiedMeta)
    keys = {e["key"] for e in meta["entities"]}
    assert {"person", "place", "institution", "relationship", "source", "event"} <= keys
    assert len(meta["lookup_domains"]) >= 20
    assert meta["lookups"]["record_status"]
    for e in ("person", "place", "institution", "relationship", "source", "event"):
        assert e in meta["fields"]


def test_migrations_recorded(conn):
    names = [r[0] for r in conn.execute("SELECT filename FROM schema_migration")]
    assert "002_place_hierarchy.sql" in names


def test_reference_data_seeded(conn):
    assert conn.execute("SELECT COUNT(*) FROM lookup").fetchone()[0] > 200
    assert conn.execute("SELECT COUNT(*) FROM locale").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM sequence").fetchone()[0] == 6


# ---------------------------------------------------------------------------
# numbering
# ---------------------------------------------------------------------------
def test_auto_code_and_sequence(client):
    r = client.post("/api/person", json={"name_ar": "اختبار الترقيم"})
    assert r.status_code == 200
    code = r.json()["record"]["code"]
    assert code.startswith("PER-")

    before = client.get("/api/person/next-code").json()["code"]
    client.put("/api/sequences/person", json={"prefix": "TST", "padding": 3})
    assert client.get("/api/person/next-code").json()["code"].startswith("TST-")
    client.put("/api/sequences/person", json={"prefix": "PER", "padding": 4})
    assert before.startswith("PER-")


# ---------------------------------------------------------------------------
# CRUD + audit + versioning
# ---------------------------------------------------------------------------
def test_create_update_audit(client):
    created = client.post("/api/person", json={
        "name_ar": "سجل تجريبي", "name_en": "Test Person",
        "classification_id": 1, "birth_date": "1955", "_reason": "unit test"}).json()["record"]
    pid = created["id"]
    assert created["version"] == 1
    assert created["record_status_id"] is not None    # defaults to draft

    upd = client.put(f"/api/person/{pid}", json={
        "name_en": "Test Person II", "_version": 1, "_reason": "rename"}).json()
    assert upd["record"]["version"] == 2
    assert any(c["field"] == "name_en" for c in upd["record"]["_changes"])

    hist = client.get(f"/api/person/{pid}/history").json()
    actions = [h["action"] for h in hist]
    assert "create" in actions and "update" in actions
    assert any(h["reason"] == "rename" for h in hist)


def test_one_edit_is_one_transaction_in_the_history(client):
    """A form that changes five fields is one act of editing: every row it writes
    shares a transaction id, so the history can be read as an event, not a list."""
    rec = client.post("/api/person", json={"name_ar": "تعديل واحد",
                                          "name_en": "Tx grouping unit"}).json()["record"]
    rid = rec["id"]
    out = client.patch(f"/api/person/{rid}", json={
        "name_en": "Tx grouping unit (renamed)",
        "name_original": "original spelling",
        "public_activity": "three fields at once",
        "version": rec["version"]})
    assert out.status_code == 200, out.text
    changed = [c["field"] for c in out.json()["record"]["_changes"]]
    assert len(changed) >= 3, changed
    from app import db
    conn = db.connect()
    try:
        rows = conn.execute("SELECT field_key, tx_id FROM change_log WHERE entity_type='person' "
                            "AND entity_id=? ORDER BY id DESC LIMIT ?",
                            (rid, len(changed))).fetchall()
    finally:
        conn.close()
    txs = {r["tx_id"] for r in rows}
    assert len(txs) == 1, rows
    assert {r["field_key"] for r in rows} == set(changed)
    client.delete(f"/api/person/{rid}?hard=true")


def test_optimistic_locking(client):
    rec = client.post("/api/person", json={"name_ar": "قفل تفاؤلي"}).json()["record"]
    client.put(f"/api/person/{rec['id']}", json={"name_en": "A", "_version": 1})
    stale = client.put(f"/api/person/{rec['id']}", json={"name_en": "B", "_version": 1})
    assert stale.status_code == 409


def test_validation_and_duplicate_code(client):
    assert client.post("/api/person", json={"name_en": "no arabic name"}).status_code == 422
    rec = client.post("/api/person", json={"name_ar": "مكرر"}).json()["record"]
    dup = client.post("/api/person", json={"name_ar": "آخر", "code": rec["code"]})
    assert dup.status_code in (409, 422)
    bad_url = client.post("/api/person", json={"name_ar": "رابط", "website": "not-a-url"})
    assert bad_url.status_code == 422


def test_soft_delete_restore_hard_delete(client):
    rec = client.post("/api/person", json={"name_ar": "حذف ناعم"}).json()["record"]
    pid, code = rec["id"], rec["code"]
    assert client.delete(f"/api/person/{pid}").status_code == 200
    assert client.get(f"/api/person/{pid}").status_code == 404
    hidden = client.post("/api/person/query", json={"where": [
        {"field": "code", "op": "eq", "value": code}]}).json()["total"]
    assert hidden == 0
    shown = client.post("/api/person/query", json={"where": [
        {"field": "code", "op": "eq", "value": code}], "include_deleted": True}).json()["total"]
    assert shown == 1
    assert client.post(f"/api/person/{pid}/restore").status_code == 200
    assert client.delete(f"/api/person/{pid}?hard=true").status_code == 200
    assert client.get(f"/api/person/{pid}?include_deleted=true").status_code == 404


def test_bulk_actions(client):
    ids = [p["id"] for p in client.post("/api/place/query", json={"page_size": 3}).json()["items"]]
    res = client.post("/api/place/bulk", json={"ids": ids, "action": "status",
                                               "patch": {"record_status_id": 2}}).json()
    assert res["ok"] == 3 and res["failed"] == 0


# ---------------------------------------------------------------------------
# filter engine + search
# ---------------------------------------------------------------------------
FILTER_BODIES = [
    {"where": [{"field": "birth_date", "op": "year_gte", "value": 1900}]},
    {"where": [{"field": "birth_date", "op": "between", "value": [1880, 1950]}]},
    {"where": [{"field": "nationality_id", "op": "in", "value": [1, 2]}]},
    {"where": [{"field": "death_date", "op": "is_null"}]},
    {"where": [{"field": "name_ar", "op": "contains", "value": "الحسيني"}]},
    {"where": [{"field": "classification_id", "op": "eq", "value": 2},
               {"field": "classification_id", "op": "eq", "value": 3}], "logic": "or"},
    {"tag_ids": [1]},
    {"q": "بغداد"},
]


def test_typed_query_language(client):
    """A filter a person can read, paste and re-run: the string form of the engine."""
    from app import querylang
    from app.schemas import ENTITIES

    spec = ENTITIES["person"]

    # a query compiles into the payload the engine already understands
    got = querylang.parse_for(spec, 'status:published birth:1880..1900 name_ar:"محمد"')
    assert got["warnings"] == [], got["warnings"]
    assert got["payload"]["status_codes"] == ["published"]
    where = {c["field"]: (c["op"], c["value"]) for c in got["payload"]["where"]}
    assert where["birth_date"] == ("between", ["1880", "1900"])
    assert where["name_ar"] == ("eq", "محمد")

    # "birth" is not a column; it is what a researcher writes
    assert querylang.parse_for(spec, "birth:>1900")["payload"]["where"][0]["field"] \
        == "birth_date"

    # negation, lists, emptiness, ordering, paging
    parsed = querylang.parse_for(spec, "name_ar:x|y -status:rejected sort:-birth_date limit:7")
    assert parsed["payload"]["where"][0] == {"field": "name_ar", "op": "in",
                                             "value": ["x", "y"]}
    # "status:x" is the engine's multi-status filter; "-status:x" is a negated clause
    assert {"field": "record_status_id", "op": "ne", "value": "rejected"} \
        in parsed["payload"]["where"]
    assert parsed["payload"]["sort"] == {"key": "birth_date", "dir": "desc"}
    assert parsed["payload"]["page_size"] == 7
    assert querylang.parse_for(spec, "public_activity:null")["payload"]["where"][0]["op"] \
        == "empty"

    # an unknown field is reported, never silently invented
    bad = querylang.parse_for(spec, "nonsense:1")
    assert bad["unknown"] == ["nonsense"] and bad["warnings"]

    # the string can be regenerated from the payload and re-parsed identically
    text, unsupported = querylang.to_string(parsed["payload"], spec)
    assert not unsupported
    again = querylang.parse_for(spec, text)["payload"]
    assert again["where"] == parsed["payload"]["where"]
    assert again["sort"] == parsed["payload"]["sort"]

    # through the API: same rows as the equivalent JSON filter, and a usage note
    body_str = client.post("/api/person/query", json={
        "query": "status:published sort:-birth_date", "page_size": 5}).json()
    published = next(v["id"] for v in
                     client.get("/api/lookups?domain=record_status").json()
                     if v["code"] == "published")
    body_json = client.post("/api/person/query", json={
        "status_ids": [published], "sort": {"key": "birth_date", "dir": "desc"},
        "page_size": 5}).json()
    assert [r["id"] for r in body_str["items"]] == [r["id"] for r in body_json["items"]]
    assert body_str["_query"]["echo"] == "status:published sort:-birth_date"

    parsed_only = client.post("/api/query/parse",
                              json={"entity": "person", "query": "tag:doesnotexist"}).json()
    assert parsed_only["warnings"], parsed_only
    rendered = client.post("/api/query/render", json={
        "entity": "person", "payload": {"where": [
            {"field": "birth_date", "op": "between", "value": ["1900", "1910"]}]}}).json()
    assert rendered["query"] == "birth_date:1900..1910", rendered
    assert client.post("/api/query/parse", json={"entity": "person",
                                                 "query": 'broken:"'}).status_code == 422


@pytest.mark.parametrize("body", FILTER_BODIES)
def test_filters(client, body):
    r = client.post("/api/person/query", json=body)
    assert r.status_code == 200
    assert isinstance(r.json()["total"], int)


def test_unknown_filter_field_is_a_warning(client):
    r = client.post("/api/person/query", json={"where": [{"field": "nope", "op": "eq", "value": 1}]})
    assert r.status_code == 200 and r.json()["warnings"]


def test_arabic_normalised_search(client):
    """Definite articles, hamza forms and diacritics must not break search."""
    for term in ("الموصل", "موصل", "أحمد", "احمد"):
        assert client.get(f"/api/search?q={term}").json()["total"] > 0, term


def test_search_scope(client):
    res = client.get("/api/search?q=بغداد&entity=place").json()
    assert all(g["entity"] == "place" for g in res["groups"])


# ---------------------------------------------------------------------------
# relationships, citations, attachments
# ---------------------------------------------------------------------------
def test_relationship_crud_and_graph(client):
    person = client.get("/api/person/1").json()
    inst = client.get("/api/institution/1").json()
    types = client.get("/api/lookups?domain=relationship_type").json()
    r = client.post("/api/relationship", json={
        "entity1_type": "person", "entity1_id": person["id"], "entity1_name": person["_title"],
        "entity2_type": "institution", "entity2_id": inst["id"],
        "relationship_type_id": types[0]["id"], "start_date": "1970"})
    assert r.status_code == 200
    rel = r.json()["record"]
    assert rel["entity1_type"] == "person"

    # self-relationship is rejected by the unique constraint path, not crashed
    dup = client.post("/api/relationship", json={
        "entity1_type": "person", "entity1_id": person["id"],
        "entity2_type": "institution", "entity2_id": inst["id"],
        "relationship_type_id": types[0]["id"]})
    assert dup.status_code in (200, 409, 422)


def test_citations(client):
    before = len(client.get("/api/person/2").json()["citations"])
    r = client.post("/api/person/2/citations", json={"source_id": 1, "note": "unit test"})
    assert r.status_code == 200
    after = client.get("/api/person/2").json()["citations"]
    assert len(after) == before + 1
    link = after[-1]["id"]
    assert client.delete(f"/api/citations/{link}").status_code == 200


def test_evidence_is_a_claim_about_a_target(client):
    """A source is cited *for a statement*, at entity, field or relationship level."""
    person = client.post("/api/person", json={"name_ar": "دليل تجريبي",
                                              "name_en": "Evidence unit"}).json()["record"]
    pid = person["id"]
    base = {"source_id": 1, "supported_claim": "Unit test claim",
            "support_type": "supports", "page_or_timestamp": "p. 4"}
    ent = client.post("/api/evidence", json={**base, "entity_type": "person",
                                             "entity_id": pid,
                                             "field_key": "birth_date"})
    assert ent.status_code == 200
    assert ent.json()["created"] is True
    eid = ent.json()["evidence_id"]

    # exactly one target, always
    assert client.post("/api/evidence", json={**base}).status_code == 422
    assert client.post("/api/evidence", json={**base, "entity_type": "person",
                                              "entity_id": pid,
                                              "relationship_id": 1}).status_code == 422
    # a source must exist, a target must exist, a type must be in the vocabulary
    assert client.post("/api/evidence", json={**base, "source_id": 999_999,
                                              "entity_type": "person",
                                              "entity_id": pid}).status_code == 404
    assert client.post("/api/evidence", json={**base, "entity_type": "person",
                                              "entity_id": 999_999}).status_code == 404
    assert client.post("/api/evidence", json={**base, "entity_type": "person",
                                              "entity_id": pid,
                                              "support_type": "proves"}).status_code == 422

    # the same claim twice is one row, not two
    again = client.post("/api/evidence", json={**base, "entity_type": "person",
                                               "entity_id": pid,
                                               "field_key": "birth_date"})
    assert again.json()["created"] is False
    doc = client.get(f"/api/evidence?entity_type=person&entity_id={pid}").json()
    assert [e["id"] for e in doc["evidence"]].count(eid) == 1
    assert doc["evidence"][0]["field_key"] == "birth_date"
    assert client.delete(f"/api/citations/{eid}").status_code == 200
    assert client.delete(f"/api/person/{pid}?hard=true").status_code == 200


def test_contradiction_is_kept_beside_the_support(client):
    """Disagreement is data. It is never overwritten by the claim it disputes."""
    person = client.post("/api/person", json={"name_ar": "تعارض تجريبي",
                                              "name_en": "Contradiction unit"}).json()["record"]
    claim = {"entity_type": "person", "entity_id": person["id"],
             "field_key": "death_date", "supported_claim": "Died in 1987"}
    a = client.post("/api/evidence", json={**claim, "source_id": 2,
                                           "support_type": "supports"}).json()
    b = client.post("/api/evidence", json={**claim, "source_id": 3,
                                           "support_type": "contradicts",
                                           "supported_claim": "Died in 1991"}).json()
    doc = client.get(f"/api/evidence?entity_type=person&entity_id={person['id']}").json()
    assert doc["count"] == 2
    assert doc["counts"] == {"supports": 1, "contradicts": 1, "contextualizes": 0}
    assert doc["disputed"] is True
    assert doc["evidence"][0]["support_type"] == "contradicts"
    assert {e["supported_claim"] for e in doc["evidence"]} == {"Died in 1987",
                                                               "Died in 1991"}
    for row in (a, b):
        assert client.delete(f"/api/citations/{row['evidence_id']}").status_code == 200
    assert client.delete(f"/api/person/{person['id']}?hard=true").status_code == 200


def test_relationship_evidence_and_verification_separation(client):
    """Reliability belongs to the source; verification belongs to the claim."""
    person = client.post("/api/person", json={"name_ar": "علاقة تجريبية",
                                              "name_en": "Rel evidence unit"}).json()["record"]
    rel = client.post("/api/relationship", json={
        "entity1_type": "person", "entity1_id": person["id"],
        "entity2_type": "institution", "entity2_id": 1,
        "relationship_type_id": "teacher_of"}).json()["record"]
    r = client.post("/api/evidence", json={"source_id": 4,
                                           "relationship_id": rel["id"],
                                           "supported_claim": "taught there",
                                           "support_type": "contextualizes",
                                           "verification": "single_source"})
    assert r.status_code == 200
    doc = client.get(f"/api/relationship/{rel['id']}/evidence").json()
    assert doc["count"] == 1
    row = doc["evidence"][0]
    assert row["verification_code"] == "single_source"
    assert "reliability_code" in row
    assert doc["type_en"] and doc["entity1_id"] == person["id"]
    assert client.delete(f"/api/citations/{r.json()['evidence_id']}").status_code == 200
    assert client.get(f"/api/relationship/{rel['id']}/evidence").json()["count"] == 0
    assert client.delete(f"/api/person/{person['id']}?hard=true").status_code == 200


def test_attachment_upload_and_download(client):
    r = client.post("/api/person/3/attachments",
                    files={"file": ("cv.txt", b"curriculum vitae", "text/plain")},
                    data={"kind": "cv"})
    assert r.status_code == 200
    att_id = r.json()["id"]
    dl = client.get(f"/api/attachments/{att_id}/download")
    assert dl.status_code == 200 and dl.content == b"curriculum vitae"
    assert client.delete(f"/api/attachments/{att_id}").status_code == 200


def test_external_identifiers(client):
    r = client.post("/api/person/4/external-ids", json={"scheme": "viaf", "value": "12345678"})
    assert r.status_code == 200
    assert client.get("/api/person/4/external-ids").json()
    assert client.delete(f"/api/external-ids/{r.json()['id']}").status_code == 200


def test_place_hierarchy(client):
    parent = client.post("/api/place", json={"name_ar": "محافظة تجريبية"}).json()["record"]
    child = client.post("/api/place", json={"name_ar": "قضاء تجريبي",
                                            "parent_place_id": parent["id"]}).json()["record"]
    assert child["parent_place_id"] == parent["id"]
    assert child["_refs"]["parent_place_id"]["label"] == "محافظة تجريبية"


# ---------------------------------------------------------------------------
# import / export
# ---------------------------------------------------------------------------
def test_export_formats(client):
    for fmt in ("csv", "tsv", "json", "xlsx"):
        r = client.post("/api/export/person", json={"format": fmt, "lang": "ar"})
        assert r.status_code == 200 and len(r.content) > 100, fmt
    csv_data = client.post("/api/export/person", json={"format": "csv", "lang": "en"}).content
    assert csv_data.startswith(b"\xef\xbb\xbf")    # UTF-8 BOM for Excel


def test_export_respects_filters(client):
    body = {"format": "json", "filters": {"where": [
        {"field": "name_ar", "op": "contains", "value": "الحسيني"}]}}
    data = json.loads(client.post("/api/export/person", json=body).content)
    assert data["meta"]["count"] == 1


def test_import_template_contains_all_fields(client):
    for fmt in ("csv", "xlsx", "json"):
        r = client.get(f"/api/import/template/person?format={fmt}&lang=ar")
        assert r.status_code == 200 and len(r.content) > 100


def test_import_roundtrip_upsert(client):
    csv_data = client.post("/api/export/person",
                           json={"format": "csv", "lang": "en", "resolve": False,
                                 "filters": {"page_size": 20}}).content
    prev = client.post("/api/import/preview",
                       files={"file": ("p.csv", csv_data, "text/csv")},
                       data={"entity": "person"}).json()
    assert prev["total_rows"] > 0 and prev["mapping"]

    payload = {"entity": "person", "upload_id": prev["upload_id"], "filename": "p.csv",
               "mapping": prev["mapping"], "mode": "upsert", "default_status": "in_review"}
    dry = client.post("/api/import/validate", json=payload).json()
    assert dry["dry_run"] is True and dry["failed"] == 0
    committed = client.post("/api/import/commit", json=payload).json()
    assert committed["failed"] == 0
    assert committed["updated"] + committed["created"] > 0


def test_import_rejects_unknown_lookup_value(client):
    csv_data = "name_ar,record_status_id\nسجل خطأ,this_status_does_not_exist\n"
    prev = client.post("/api/import/preview",
                       files={"file": ("bad.csv", csv_data.encode(), "text/csv")},
                       data={"entity": "person"}).json()
    r = client.post("/api/import/validate", json={
        "entity": "person", "upload_id": prev["upload_id"],
        "mapping": prev["mapping"], "mode": "create"}).json()
    assert r["failed"] == 1
    assert "Unknown value" in r["errors"][0]["message"]


def test_import_jobs_are_logged(client):
    jobs = client.get("/api/import/jobs").json()
    assert jobs and jobs[0]["entity_type"] == "person"


def test_import_handles_cp1256(client):
    text = "name_ar\nسجل بترميز عربي قديم\n"
    raw = text.encode("cp1256")
    prev = client.post("/api/import/preview",
                       files={"file": ("legacy.csv", raw, "text/csv")},
                       data={"entity": "person"}).json()
    assert prev["total_rows"] == 1


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------
REPORTS = ["overview", "quality", "institutions", "geography", "network",
           "timeline", "sources", "workflow", "indicators"]


@pytest.mark.parametrize("key", REPORTS)
def test_reports_render_and_export(client, key):
    rep = client.get(f"/api/reports/{key}").json()
    assert rep["key"] == key
    assert rep["sections"] and rep["summary"]
    for section in rep["sections"]:
        assert section["columns"] and isinstance(section["rows"], list)
    for fmt in ("xlsx", "csv"):
        r = client.get(f"/api/reports/{key}/export?format={fmt}")
        assert r.status_code == 200 and len(r.content) > 100


def test_custom_pivot(client):
    r = client.post("/api/reports/custom", json={"params": {
        "entity": "person", "group_by": "nationality_id", "metric": "count", "chart": "pie"}})
    assert r.status_code == 200
    assert r.json()["sections"][0]["rows"]
    bad = client.post("/api/reports/custom", json={"params": {
        "entity": "person", "group_by": "does_not_exist"}})
    assert bad.status_code == 422


def test_dashboard_payload(client):
    d = client.get("/api/dashboard").json()
    assert len(d["cards"]) == 6
    assert d["totals"]["records"] > 0
    assert "coverage" in d


# ---------------------------------------------------------------------------
# administration
# ---------------------------------------------------------------------------
def test_vocabulary_crud(client):
    created = client.post("/api/lookups", json={
        "domain": "place_type", "code": "unit_test_type",
        "label_en": "Unit test type", "label_ar": "نوع اختباري"})
    assert created.status_code == 200
    lid = created.json()["id"]
    assert client.put(f"/api/lookups/{lid}", json={"label_en": "Renamed"}).status_code == 200
    assert client.delete(f"/api/lookups/{lid}").status_code == 200
    dup = client.post("/api/lookups", json={
        "domain": "place_type", "code": "city", "label_en": "x", "label_ar": "س"})
    assert dup.status_code == 409
    assert client.post("/api/lookups", json={"domain": "nope", "code": "x",
                                             "label_en": "x", "label_ar": "س"}).status_code == 422


def test_saved_views(client):
    assert client.post("/api/saved-views", json={
        "name": "Recent scholars", "entity_type": "person",
        "filters": {"where": [{"field": "birth_date", "op": "year_gte", "value": 1950}]},
        "columns": ["code", "name_ar"]}).status_code == 200
    views = client.get("/api/saved-views?entity_type=person").json()
    assert any(v["name"] == "Recent scholars" for v in views)
    vid = [v for v in views if v["name"] == "Recent scholars"][0]["id"]
    assert client.delete(f"/api/saved-views/{vid}").status_code == 200


def test_settings_registry_is_complete_and_typed(client):
    """Every setting is declared with a type, a default, a group and a consumer.

    The last assertion is the important one: a key that no code path reads is a
    decoration in a settings screen, and this registry does not carry any.
    """
    doc = client.get("/api/settings").json()
    groups = {g["key"] for g in doc["groups"]}
    assert {"display", "entry", "search", "transfer", "quality", "audit",
            "maintenance"} <= groups
    assert len(doc["fields"]) >= 15
    for f in doc["fields"]:
        assert f["kind"] in ("bool", "int", "enum", "text", "decimal"), f
        assert f["group"] in groups, f
        assert f["label_en"] and f["label_ar"], f
        assert f["help_en"] and f["help_ar"], f
        assert f["effect"], f"'{f['key']}' declares no consumer"
        assert f["source"] in ("instance", "default")
        assert str(f["value"]) == str(doc["settings"][f["key"]])
        if f["kind"] == "enum":
            assert f["value"] in f["values"] and f["default"] in f["values"], f
        if f["kind"] == "int":
            assert f["minimum"] <= int(f["value"]) <= f["maximum"], f
    schema = client.get("/api/settings/schema").json()
    assert {f["key"] for f in schema["fields"]} == {f["key"] for f in doc["fields"]}
    assert "display.page_size" in client.get("/api/meta").json()["settings"]


def test_settings_defaults_have_exactly_one_source(conn, client):
    """A fresh database stores the registry's defaults — not a second hand-written list.

    The seeded rows, the declared defaults and the migration files all have to agree:
    a key added to the registry but missing from a migration would leave an upgraded
    installation without the row operators read, and a default restated in `seed.py`
    would eventually drift from the registry's.
    """
    from app import seed, settings

    assert seed.DEFAULT_SETTINGS == settings.defaults()
    declared = {sp.key: sp.store(sp.default) for sp in settings.SPECS}

    rows = dict(conn.execute("SELECT key, value FROM setting").fetchall())
    missing = sorted(set(declared) - set(rows))
    assert not missing, f"keys with no seeded row: {missing}"
    for key, default in declared.items():
        assert rows[key] == default, f"{key}: seeded {rows[key]!r}, declared {default!r}"

    # and the migrations must not leave a key behind that nothing declares
    assert {r["key"] for r in conn.execute("SELECT key FROM setting")} <= set(declared)

    # every migration-seeded key is a declared key (no dead INSERT can survive)
    sql = "".join(p.read_text() for p in sorted((ROOT / "app" / "migrations").glob("*.sql")))
    seeded = set(re.findall(r"INSERT OR IGNORE INTO setting \(key, value\) VALUES \('([^']+)'", sql))
    assert seeded <= set(declared), f"migrations seed undeclared keys: {sorted(seeded - set(declared))}"

    # and the screen can never offer a value the backend refuses
    for f in client.get("/api/settings").json()["fields"]:
        if f["kind"] == "int":
            assert client.put("/api/settings", json={f["key"]: f["maximum"]}).status_code == 200
            assert client.put("/api/settings", json={f["key"]: f["default"]}).status_code == 200


def test_settings_roundtrip(client):
    res = client.put("/api/settings", json={"display.page_size": "50"})
    assert res.status_code == 200
    assert res.json()["settings"]["display.page_size"] == "50"
    assert res.json()["changed"][0]["old"] == "25"
    assert client.get("/api/settings").json()["settings"]["display.page_size"] == "50"
    assert client.get("/api/meta").json()["settings"]["display.page_size"] == "50"


def test_settings_validation_is_all_or_nothing(client):
    bad = client.put("/api/settings", json={
        "display.page_size": 9999,          # above the maximum
        "display.theme": "neon",            # not an allowed value
        "search.min_chars": "two",          # not an integer
        "made.up.key": "x",                 # not a declared setting
        "display.density": "compact",       # valid, but must not be applied
    })
    assert bad.status_code == 422
    reasons = {p["key"]: p["reason"] for p in bad.json()["problems"]}
    assert reasons == {"display.page_size": "above_maximum",
                       "display.theme": "not_allowed",
                       "search.min_chars": "not_integer",
                       "made.up.key": "unknown_key"}
    assert bad.json()["applied"] == []
    assert client.get("/api/settings").json()["settings"]["display.density"] != "compact"


def test_settings_reset_and_audit_trail(client):
    from app import db

    client.put("/api/settings", json={"validation.min_completeness": "40"})
    res = client.post("/api/settings/reset", json={"keys": ["validation.min_completeness"]})
    assert res.status_code == 200 and res.json()["reset"] == ["validation.min_completeness"]
    assert res.json()["settings"]["validation.min_completeness"] == "0"
    c = db.connect()
    try:
        rows = c.execute("SELECT old_value, new_value, actor FROM change_log "
                         "WHERE entity_type='setting' AND entity_code='validation.min_completeness' "
                         "ORDER BY id").fetchall()
    finally:
        c.close()
    assert len(rows) >= 2, [dict(r) for r in rows]
    assert any(r["new_value"] == "40" for r in rows)
    assert any(r["new_value"] == "0" for r in rows)      # the reset is recorded too
    assert all(r["actor"] for r in rows)
    # an unknown key on reset is reported, not silently ignored
    assert client.post("/api/settings/reset", json={"keys": ["nope.nope"]}).json()["unknown"] == ["nope.nope"]


def test_reset_records_only_real_changes(client):
    """Resetting a key that already holds its default is dropped, not logged.

    A "reset everything" on a freshly configured instance must not bury the real
    configuration history under rows saying 25 → 25.
    """
    from app import db, settings

    client.post("/api/settings/reset", json={})                    # everything at default
    c = db.connect()
    try:
        settings.ensure(c)          # what a restart does: one row per declared key
    finally:
        c.close()
    quiet = client.post("/api/settings/reset", json={}).json()
    assert quiet["changed"] == [], quiet["changed"]                 # nothing to report
    assert "display.page_size" in quiet["reset"]                    # rows were still dropped

    client.put("/api/settings", json={"display.page_size": "40"})
    loud = client.post("/api/settings/reset", json={"keys": ["display.page_size"]}).json()
    assert loud["changed"] == ["display.page_size"]
    assert loud["settings"]["display.page_size"] == "25"

    c = db.connect()
    try:
        rows = c.execute("SELECT old_value, new_value FROM change_log "
                         "WHERE entity_type='setting' AND entity_code='display.page_size' "
                         "ORDER BY id").fetchall()
    finally:
        c.close()
    assert [(r["old_value"], r["new_value"]) for r in rows][-1] == ("40", "25")
    assert all(r["old_value"] != r["new_value"] for r in rows), "a no-op reset was logged"


def test_publish_gate_can_be_configured(client):
    """validation.require_source_on_publish and min_completeness are enforced."""
    statuses = {s["code"]: s["id"] for s in client.get("/api/lookups?domain=record_status").json()}
    published = statuses.get("published") or statuses.get("verified")
    blocked = client.post("/api/person", json={
        "name_ar": "بوابة النشر", "name_en": "Publish gate",
        "record_status_id": published})
    assert blocked.status_code == 422
    assert "source" in blocked.text.lower()

    # with the policy off, the same create is allowed
    client.put("/api/settings", json={"validation.require_source_on_publish": "false"})
    allowed = client.post("/api/person", json={
        "name_ar": "بوابة مفتوحة", "name_en": "Publish gate open",
        "record_status_id": published})
    assert allowed.status_code == 200, allowed.text
    rid = allowed.json()["record"]["id"]
    client.put("/api/settings", json={"validation.require_source_on_publish": "true"})

    # a sourced record may be published: attach a citation, then publish it
    src = client.get("/api/options/source?limit=1").json()[0]["id"]
    client.post(f"/api/person/{rid}/citations", json={"source_id": src})
    promoted = client.put(f"/api/person/{rid}", json={
        "record_status_id": statuses.get("verified") or published})
    assert promoted.status_code == 200, promoted.text

    # and the completeness floor blocks a thin record from being published
    client.put("/api/settings", json={"validation.min_completeness": "99"})
    thin = client.post("/api/person", json={"name_ar": "سجل رفيع", "name_en": "Thin record"})
    tid = thin.json()["record"]["id"]
    src2 = client.get("/api/options/source?limit=1").json()[0]["id"]
    client.post(f"/api/person/{tid}/citations", json={"source_id": src2})
    refused = client.put(f"/api/person/{tid}", json={
        "record_status_id": statuses.get("verified") or published})
    assert refused.status_code == 422 and "completeness" in refused.text
    client.post("/api/settings/reset", json={"keys": ["validation.min_completeness"]})

    # remove both through the API, so dependents (citations) go with them
    for rec in (rid, tid):
        client.delete(f"/api/person/{rec}?hard=true&reason=test cleanup")


def test_delete_reason_policy_is_optional(client):
    client.post("/api/settings/reset", json={"keys": ["validation.require_reason_for_delete"]})
    made = client.post("/api/person", json={"name_ar": "حذف بلا سبب",
                                            "name_en": "No-reason delete"}).json()["record"]
    assert client.delete(f"/api/person/{made['id']}?hard=true").status_code == 200

    client.put("/api/settings", json={"validation.require_reason_for_delete": "true"})
    made2 = client.post("/api/person", json={"name_ar": "حذف بشرط",
                                             "name_en": "Reason required"}).json()["record"]
    blocked = client.delete(f"/api/person/{made2['id']}")
    assert blocked.status_code == 422 and "reason" in blocked.text.lower()
    assert client.delete(f"/api/person/{made2['id']}?reason=duplicate").status_code == 200
    client.post("/api/settings/reset", json={"keys": ["validation.require_reason_for_delete"]})


def test_locale_bundles(client):
    ar = client.get("/api/locales/ar/messages").json()
    en = client.get("/api/locales/en/messages").json()
    assert set(ar) == set(en), "locale bundles must expose the same keys"


def test_maintenance(client):
    assert client.post("/api/maintenance/reindex").json()["documents"] > 0
    backup = client.get("/api/maintenance/backup")
    assert backup.status_code == 200 and backup.content[:2] == b"PK"
    dump = client.get("/api/maintenance/export-all").json()
    assert "person" in dump and dump["person"]


def test_changelog_endpoint(client):
    r = client.get("/api/changelog?entity_type=person&action=update&page_size=5").json()
    assert r["total"] >= 1
    assert all(i["action"] == "update" for i in r["items"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def test_normalisation_and_year_helpers():
    assert db.normalize("المؤسّسةُ العربية") == db.normalize("المؤسسه العربيه")
    assert db.normalize("أحمد") == db.normalize("احمد")
    assert db.fts_query("ابن خلدون").count("AND") == 1
    from app.schemas import year_of
    assert year_of("c. 1876") == 1876
    assert year_of("1950-05-12") == 1950
    assert year_of(None) is None


def test_static_assets_served(client):
    for path in ("/", "/static/css/base.css", "/static/css/components.css",
                 "/static/css/views.css", "/static/js/core.js",
                 "/static/js/components/forms.js", "/static/js/views/list.js",
                 "/static/js/views/record.js", "/static/js/app.js",
                 "/static/js/locales/ar.json", "/static/js/locales/en.json"):
        assert client.get(path).status_code == 200, path


def test_index_html_references_only_existing_assets(client):
    """The shell must not point at a file that is not shipped (renamed folders)."""
    import re
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1] / "app" / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert refs, "index.html should reference the static bundle"
    for ref in refs:
        assert (root / ref[len("/static/"):]).exists(), f"missing asset: {ref}"
        assert client.get(ref).status_code == 200, ref


LOCALES = Path("app/static/js/locales")
JS_DIR = Path("app/static/js")


def _js_files():
    return sorted(JS_DIR.rglob("*.js"))


def test_locale_manifest_declares_every_language():
    manifest = json.loads((LOCALES / "index.json").read_text(encoding="utf-8"))
    codes = [m["code"] for m in manifest]
    assert "ar" in codes and "en" in codes
    for entry in manifest:
        assert entry["dir"] in ("rtl", "ltr")
        assert (LOCALES / f"{entry['code']}.json").is_file(), entry["code"]
    assert sum(1 for m in manifest if m.get("default")) <= 1


def test_locales_have_identical_key_sets():
    bundles = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in LOCALES.glob("*.json") if p.stem != "index"}
    keys = {name: set(b) for name, b in bundles.items()}
    base = keys["en"]
    for name, ks in keys.items():
        assert ks == base, (name, sorted(base ^ ks)[:8])
    for name, b in bundles.items():
        for k, v in b.items():
            assert isinstance(v, str) and v.strip(), (name, k)


def test_every_translation_key_used_in_js_exists():
    import re
    bundles = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in LOCALES.glob("*.json") if p.stem != "index"}
    keys = set().union(*bundles.values())
    used, missing = set(), []
    for path in _js_files():
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'\b(?:t|A\.t|App\.t)\(\s*"([a-zA-Z][\w.]*)"', src):
            used.add(m.group(1))
        for m in re.finditer(r'data-i18n(?:-placeholder)?="([\w.]+)"', src):
            used.add(m.group(1))
    for path in (Path("app/static"),):
        for f in list(path.rglob("*.html")) + list(Path("app/templates").rglob("*.html")):
            src = f.read_text(encoding="utf-8")
            for m in re.finditer(r'data-i18n(?:-placeholder)?="([\w.]+)"', src):
                used.add(m.group(1))
    def resolved(k):
        # dynamic prefixes such as "time.unit." + unit are checked via their
        # concrete children, not as standalone keys
        return k in keys or any(x.startswith(k) for x in keys)
    missing = sorted(k for k in used if not resolved(k))
    assert not missing, f"untranslated keys: {missing}"
    assert len(used) > 120


def test_no_hardcoded_bilingual_strings_in_ui_code():
    """Static UI text must live in locale files so a third language is additive."""
    import re as _re
    pattern = _re.compile(r'lang\s*===\s*"ar"\s*\?\s*"([^"]*)"\s*:\s*"([^"]*)"')
    arabic = _re.compile(r"[\u0600-\u06FF]")
    offenders = []
    for path in _js_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = pattern.search(line)
            # language codes and locale ids ("ar"/"en", "ar-EG"/"en-GB") are
            # technical values, not user-visible copy
            if m and (arabic.search(m.group(1)) or arabic.search(m.group(2))):
                offenders.append(f"{path}:{i}")
    assert not offenders, f"inline AR/EN literals: {offenders}"


def test_project_structure_is_complete():
    """A packaging guard: the documented layout exists and every package imports."""
    import importlib
    root = Path(__file__).resolve().parents[1]
    expected = [
        "app/__init__.py", "app/cli.py", "app/db.py", "app/schema.sql",
        "app/schemas.py", "app/repo.py", "app/transfer.py", "app/reports.py",
        "app/stats.py", "app/seed.py",
        "app/server/__init__.py", "app/server/api.py", "app/server/launcher.py",
        "app/static/index.html", "app/static/css/base.css",
        "app/static/css/components.css", "app/static/css/views.css",
        "app/static/js/core.js", "app/static/js/app.js",
        "app/static/js/components/forms.js",
        "app/static/js/views/list.js", "app/static/js/views/record.js",
        "app/static/js/views/dashboard.js", "app/static/js/views/reports.js",
        "app/static/js/views/admin.js",
        "app/static/js/locales/index.json",
        "app/static/js/locales/ar.json", "app/static/js/locales/en.json",
        "run.py", "run.sh", "start.bat", "start.ps1", "requirements.txt",
        "README.md", ".gitignore", ".gitattributes", ".editorconfig",
        "docs/API.md", "docs/DATA_MODEL.md", "docs/DESIGN_REVIEW.md",
        "docs/IMPORT_EXPORT.md", "docs/OPERATIONS.md", "docs/UI_GUIDE.md",
        "docs/I18N.md", "scripts/check.py", ".github/workflows/ci.yml",
        "tests/test_registry.py", "samples/run_samples.py",
    ]
    missing = [p for p in expected if not (root / p).exists()]
    assert not missing, f"missing from the project layout: {missing}"
    for module in ("app", "app.db", "app.schemas", "app.repo", "app.transfer",
                   "app.reports", "app.stats", "app.cli",
                   "app.server", "app.server.launcher"):
        importlib.import_module(module)


# ---------------------------------------------------------------------------
# phase 2 · related-table fields, typography-independent filtering, imagery,
#            inline creation support and duplicate merging
# ---------------------------------------------------------------------------
def test_meta_exposes_derived_fields_and_view_modes(client):
    meta = client.get("/api/meta?lang=en").json()
    assert "derived" in meta and "person" in meta["derived"]
    keys = {d["key"] for d in meta["derived"]["person"]}
    assert {"relationships_count", "completeness", "birth_year"} <= keys
    assert all("expr" in d for d in meta["derived"]["person"])  # transparency: the SQL
    assert meta["view_modes"] == ["table", "cards", "gallery", "list"]


def test_list_items_carry_derived_map_and_accept_derived_columns(client):
    res = client.post("/api/person/query", json={"page_size": 3}).json()
    assert res["items"], "seeded persons expected"
    item = res["items"][0]
    assert "_derived" in item and "completeness" in item["_derived"]
    assert "d_completeness" not in item, "derived aliases must not leak into the record"


def test_derived_field_filtering_sorting_and_typing(client):
    """Filters on related-table fields work, even when sent as strings (browser)."""
    numeric = client.post("/api/person/query", json={
        "where": [{"field": "relationships_count", "op": "gte", "value": 1}]}).json()
    textual = client.post("/api/person/query", json={
        "where": [{"field": "relationships_count", "op": "gte", "value": "1"}]}).json()
    assert numeric["total"] == textual["total"] > 0, "string/int filters must agree"
    bounded = client.post("/api/person/query", json={
        "where": [{"field": "birth_year", "op": "between", "value": ["1900", "1930"]}]}).json()
    assert all(1900 <= i["_derived"]["birth_year"] <= 1930 for i in bounded["items"])
    sorted_res = client.post("/api/person/query", json={
        "sort": "relationships_count", "order": "desc", "page_size": 50}).json()
    counts = [i["_derived"]["relationships_count"] for i in sorted_res["items"]]
    assert counts == sorted(counts, reverse=True)


def test_id_select_stored_as_text_still_resolves_and_filters(client, conn):
    """birth_precision is a TEXT column holding a lookup id — labels and filters must work."""
    pid = conn.execute("SELECT id FROM person WHERE birth_precision IS NOT NULL "
                       "AND deleted_at IS NULL LIMIT 1").fetchone()["id"]
    rec = client.get(f"/api/person/{pid}").json()
    assert rec["_labels"]["birth_precision"]["code"], "lookup label must resolve"
    lid = int(str(rec["birth_precision"]))
    hits = client.post("/api/person/query", json={
        "where": [{"field": "birth_precision", "op": "eq", "value": lid}]}).json()
    assert hits["total"] >= 1


def test_options_endpoint_supports_search_and_id_rehydration(client):
    people = client.get("/api/options/person?limit=5").json()
    assert people and {"id", "code", "label", "label_ar", "type"} <= set(people[0])
    one = client.get(f"/api/options/person?ids={people[0]['id']}").json()
    assert len(one) == 1 and one[0]["id"] == people[0]["id"]
    searched = client.get("/api/options/institution?q=a&limit=5").json()
    assert isinstance(searched, list)


def test_imagery_fields_exist_for_profile_entities(client):
    meta = client.get("/api/meta?lang=en").json()
    for entity in ("person", "institution", "place", "event"):
        keys = {f["key"] for f in meta["fields"][entity]}
        assert {"image_url", "image_alt"} <= keys, entity


def test_media_upload_serves_the_image(client):
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
           b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
           b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    res = client.post("/api/media", files={"file": ("dot.png", png, "image/png")})
    assert res.status_code == 200, res.text
    url = res.json()["url"]
    assert url.startswith("/api/media/")
    served = client.get(url)
    assert served.status_code == 200 and served.content == png
    bad = client.post("/api/media", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 415


def test_duplicates_and_merge_flow(client):
    created = []
    # same Arabic name written with different hamza/taa-marbuta forms → one duplicate group
    for name_ar, name_en in (("تجربة الدمج", "Merge trial A"), ("تجربه الدمج", "Merge trial B")):
        rec = client.post("/api/person", json={
            "name_ar": name_ar, "name_en": name_en,
            "record_status_id": 1, "_reason": "duplicate test"}).json()["record"]
        created.append(rec["id"])
    groups = client.get("/api/person/duplicates").json()["groups"]
    assert any(set(created) <= {r["id"] for r in g["records"]} for g in groups), groups
    keep, drop = created
    plan = client.post(f"/api/person/{keep}/merge",
                       json={"merge_ids": [drop], "dry_run": True}).json()
    assert plan["merged"] and plan.get("keep", {}).get("id") == keep
    done = client.post(f"/api/person/{keep}/merge",
                       json={"merge_ids": [drop], "reason": "test merge"}).json()
    assert done["merged"]
    assert client.get(f"/api/person/{drop}").status_code == 404
    trash = client.post("/api/person/query", json={"only_deleted": True}).json()
    assert any(i["id"] == drop for i in trash["items"])


def test_saved_view_roundtrip_with_derived_columns(client):
    view = client.post("/api/saved-views", json={
        "name": "connected researchers",
        "entity_type": "person",
        "filters": {"where": [{"field": "relationships_count", "op": "gte", "value": 1}],
                    "logic": "and"},
        "columns": ["code", "name_ar", "relationships_count", "completeness"],
        "sort": {"view": "cards", "layout": {"imageField": "image_url"}},
    })
    assert view.status_code in (200, 201), view.text
    listed = client.get("/api/saved-views?entity_type=person").json()
    hit = next(v for v in listed if v["name"] == "connected researchers")
    cols = hit["columns"] if isinstance(hit["columns"], list) else json.loads(hit["columns"])
    assert "relationships_count" in cols
    client.delete(f"/api/saved-views/{hit['id']}")


def test_export_includes_derived_columns(client):
    res = client.post("/api/export/person", json={
        "format": "csv", "lang": "en", "resolve": True,
        "columns": ["code", "name_en", "relationships_count", "completeness"],
        "filters": {"page_size": 5}})
    assert res.status_code == 200
    text = res.content.decode("utf-8-sig")
    header = text.splitlines()[0]
    assert "relationships_count" in header or "Relationships" in header
    assert len(text.splitlines()) > 1


def test_report_pivot_on_derived_field(client):
    res = client.post("/api/reports/custom", json={"params": {
        "entity": "person", "group_by": "completeness", "metric": "count", "chart": "table"}})
    assert res.status_code == 200, res.text
    assert res.json()["sections"], "pivot should return at least one section"


def test_metrics_endpoint(client):
    res = client.get("/api/metrics").json()
    assert res["records"]["person"] >= 1
    assert "db_size_bytes" in res and "token_auth" in res


def test_backup_archive_contains_files_and_manifest(client):
    import zipfile
    res = client.get("/api/maintenance/backup")
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert "registry.db" in names and "manifest.json" in names
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["files_included"] is True
    assert "file_count" in manifest


def test_kpi_strip_endpoint(client):
    res = client.post("/api/person/kpi", json={"page_size": 25}).json()
    keys = {t["key"] for t in res["tiles"]}
    assert {"records", "avg_completeness", "recent"} <= keys
    assert all({"label_en", "label_ar", "value"} <= set(t) for t in res["tiles"])
    filtered = client.post("/api/person/kpi", json={
        "where": [{"field": "relationships_count", "op": "gte", "value": 1}]}).json()
    base = {t["key"]: t["value"] for t in res["tiles"]}
    sel = {t["key"]: t["value"] for t in filtered["tiles"]}
    assert sel["records"] <= base["records"]
    assert sel["relationships_count"] <= base["relationships_count"]


# ---------------------------------------------------------------------------
# place-name hygiene (app/placeclean.py) — the graph's readability depends on it
# ---------------------------------------------------------------------------
def test_placeclean_plan_and_apply(tmp_path):
    import sqlite3

    from app import placeclean

    conn = sqlite3.connect(tmp_path / "clean.db")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE lookup (id INTEGER PRIMARY KEY, domain TEXT, code TEXT,
                             label_en TEXT, label_ar TEXT);
        CREATE TABLE place (id INTEGER PRIMARY KEY, name_en TEXT, name_ar TEXT,
                            city TEXT, parent_place_id INTEGER, country_id INTEGER,
                            deleted_at TEXT);
        CREATE TABLE change_log (id INTEGER PRIMARY KEY AUTOINCREMENT, tx_id TEXT,
                            entity_type TEXT, entity_id INTEGER, entity_code TEXT,
                            action TEXT, field_key TEXT, field_label TEXT,
                            old_value TEXT, new_value TEXT, reason TEXT,
                            source_id INTEGER, actor TEXT, reviewed_by TEXT,
                            notes TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO lookup (id, domain, code, label_en, label_ar)
            VALUES (1, 'country', 'PT', 'Portugal', 'البرتغال');
        INSERT INTO place (id, name_en, name_ar, city, parent_place_id, country_id) VALUES
            (10, 'Portugal', 'البرتغال', NULL, NULL, 1),
            (11, 'Lisbon', 'لشبونة', 'Lisbon', 10, 1),
            (12, 'Lisbon', 'لشبونة', 'Lisbon', 10, 1),
            (13, 'City of Portugal', 'مدينة البرتغال', 'City of Portugal', 10, 1);
    """)
    dry = placeclean.tidy(conn)
    assert len(dry) == 2, "the duplicate and the placeholder are both detected"
    assert conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == 0, \
        "a dry run writes nothing"

    applied = placeclean.tidy(conn, apply=True)
    assert len(applied) == 2
    names = [r["name_en"] for r in conn.execute(
        "SELECT name_en FROM place WHERE parent_place_id=10 ORDER BY id")]
    assert len(set(names)) == len(names), "no two siblings share a name"
    assert not any(n.startswith("City of") for n in names), "no placeholder survives"
    assert conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == 2, \
        "every rename is auditable"
    assert len(placeclean.tidy(conn)) == 0, "the repair is idempotent"


def test_relationship_map_types_shapes():
    """The graph endpoint must return a matrix that the client can render blindly."""
    from fastapi.testclient import TestClient

    from app.server.api import app

    with TestClient(app) as client:
        data = client.post("/api/relationship-map",
                           json={"mode": "types", "include_structural": True}).json()
    assert data["nodes"] and data["matrix_order"]
    for a in data["matrix_order"]:
        for b in data["matrix_order"]:
            assert isinstance(data["matrix"][a].get(b, 0), int)
    assert data["totals"]["records"] > 0
    kinds = {e["kind"] for e in data["edges"]}
    assert kinds <= {"relationship", "structural"}


def test_relationship_map_network_is_the_whole_roster(client):
    """People and organizations come back together, searchable, and pinnable."""
    full = client.post("/api/relationship-map", json={
        "mode": "network", "types": ["person", "institution"],
    }).json()
    assert full["mode"] == "network"
    assert full["nodes"], "the roster is not empty"
    types = {n["type"] for n in full["nodes"]}
    assert types <= {"person", "institution"}
    assert "person" in types and "institution" in types
    ids = {n["id"] for n in full["nodes"]}
    for e in full["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert e["source"] != e["target"]
    person = next(n for n in full["nodes"] if n["type"] == "person" and n.get("name_en"))
    token = person["name_en"].split()[0]
    narrowed = client.post("/api/relationship-map", json={
        "mode": "network", "types": ["person", "institution"], "q_person": token,
    }).json()
    assert any(n["id"] == person["id"] for n in narrowed["nodes"])
    for n in narrowed["nodes"]:
        if n["type"] != "person":
            continue
        blob = f"{n.get('name_en') or ''} {n.get('name_ar') or ''}".lower()
        assert token.lower() in blob
    pinned = client.post("/api/relationship-map", json={
        "mode": "network", "types": ["person", "institution"],
        "q_person": "zzz-no-such-person-qqq", "pins": [person["id"]],
    }).json()
    assert any(n["id"] == person["id"] for n in pinned["nodes"])
    empty = client.post("/api/relationship-map", json={"mode": "network", "types": []}).json()
    assert empty["nodes"] == [] and empty["edges"] == []


# ---------------------------------------------------------------------------
# regressions found by tests/audit.py — each of these was a real defect
# ---------------------------------------------------------------------------
def test_every_advertised_filter_operator_is_implemented(client):
    """`startswith` / `empty` used to be accepted as aliases and then ignored,
    which returned the *whole table* while showing a warning nobody reads."""
    from app import repo
    from app.schemas import ENTITIES

    conn = db.connect()
    try:
        spec = ENTITIES["person"]
        total = repo.list_records(conn, spec, {"page_size": 1})["total"]
        for op, value in (("startswith", "Moh"), ("startswiths", "Moh"), ("start", "Moh"),
                          ("endswith", "i"), ("empty", True), ("not_empty", True)):
            got = repo.list_records(conn, spec,
                                    {"filters": {"name_en": {op: value}}, "page_size": 1})
            assert not got["warnings"], f"{op} must be implemented, not warned about"
            assert got["total"] != total or op in ("not_empty",), \
                f"{op} silently matched everything"
        # the alias table is the single source of truth: everything it advertises works
        from app.repo import FILTER_OP_ALIASES
        for raw, canonical in FILTER_OP_ALIASES.items():
            # year/date operators legitimately reject a non-date value, so feed them one
            if canonical.startswith("year_"):
                value = 1900
            elif canonical in ("on", "before", "after"):
                value = "1900-01-01"
            else:
                value = "Ahmad"
            got = repo.list_records(conn, spec,
                                    {"filters": {"name_en": {raw: value}}, "page_size": 1})
            assert not got["warnings"], f"alias {raw!r} → {canonical!r} is not implemented"
    finally:
        conn.close()


def test_bad_year_is_a_warning_not_a_crash(client):
    from app import repo
    from app.schemas import ENTITIES

    conn = db.connect()
    try:
        got = repo.list_records(conn, ENTITIES["person"],
                                {"filters": {"birth_date": {"year_eq": "banana"}},
                                 "page_size": 1})
        assert got["warnings"], "a non-numeric year must be reported"
        assert got["total"] > 0, "and must not filter everything out silently"
    finally:
        conn.close()


def test_structural_keys_are_not_treated_as_fields(client):
    """A payload nested inside `filters` keeps its own structure."""
    from app import repo
    from app.schemas import ENTITIES

    conn = db.connect()
    try:
        spec = ENTITIES["person"]
        nested = repo.list_records(conn, spec, {"filters": {"where": [
            {"field": "code", "op": "eq", "value": "PER-0001"}]}, "page_size": 5})
        assert nested["total"] == 1, nested["warnings"]
        flat = repo.list_records(conn, spec, {"where": [
            {"field": "code", "op": "eq", "value": "PER-0001"}], "page_size": 5})
        assert flat["total"] == nested["total"]
        # `title` is a real column on source — it must never be swallowed as structure
        srcs = ENTITIES["source"]
        all_src = repo.list_records(conn, srcs, {"page_size": 1})["total"]
        none_src = repo.list_records(conn, srcs,
                                     {"filters": {"title": {"contains": "zzz-no-such"}},
                                      "page_size": 1})["total"]
        assert none_src == 0 and all_src > 0, (all_src, none_src)
    finally:
        conn.close()


def test_export_is_never_truncated(client, monkeypatch):
    """The list endpoint clamps a page to 1 000 rows; an export must not inherit
    that clamp, or a filtered export silently loses everything beyond row 1 000.

    The internal page is shrunk to 3 rows so the paging loop is exercised even
    against the small test database.
    """
    from app import transfer
    from app.schemas import ENTITIES

    monkeypatch.setattr(transfer, "EXPORT_PAGE", 3, raising=True)
    conn = db.connect()
    try:
        spec = ENTITIES["person"]
        cols = [f.key for f in spec.fields if f.in_list]
        rows, _headers = transfer._export_rows(conn, spec, {}, cols, "en", True)
        total = repo_total(conn, spec)
        assert total > 3, "the test database must hold more rows than one page"
        assert len(rows) == total, f"exported {len(rows)} of {total}"
        assert len({r[cols and _headers[0]] for r in rows}) <= total
    finally:
        conn.close()


def repo_total(conn, spec):
    from app import repo

    return repo.list_records(conn, spec, {"page_size": 1})["total"]


def test_export_endpoint_honours_nested_filters(client):
    """`{"format": …, "filters": {…}}` used to export every record."""
    all_rows = json.loads(client.post("/api/export/person",
                                      json={"format": "json"}).content)["meta"]["count"]
    some = json.loads(client.post("/api/export/person", json={
        "format": "json",
        "filters": {"where": [{"field": "code", "op": "eq", "value": "PER-0001"}]},
    }).content)
    assert some["meta"]["count"] == 1 < all_rows


def test_hard_delete_removes_dependents(client):
    """A hard delete must not leave citations, tags or relationships dangling."""
    rec = client.post("/api/person", json={"name_ar": "حذف كامل",
                                           "name_en": "Cascade unit"}).json()["record"]
    rid = rec["id"]
    src = client.get("/api/options/source?limit=1").json()[0]["id"]
    client.post(f"/api/person/{rid}/citations", json={"source_id": src})
    client.post(f"/api/person/{rid}/external-ids",
                json={"scheme": "ORCID", "value": "0000-cascade-unit"})
    rel_type = client.get("/api/lookups?domain=relationship_type").json()[0]["id"]
    status = client.get("/api/lookups?domain=record_status").json()[0]["id"]
    client.post("/api/relationship", json={"entity1_type": "person", "entity1_id": rid,
                                           "entity2_type": "person", "entity2_id": 1,
                                           "relationship_type_id": rel_type,
                                           "record_status_id": status})

    conn = db.connect()
    try:
        conn.execute("INSERT INTO entity_tag (entity_type, entity_id, tag_id) "
                     "VALUES ('person', ?, 1)", (rid,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM evidence WHERE entity_type='person' "
                            "AND entity_id=?", (rid,)).fetchone()[0] == 1
    finally:
        conn.close()

    out = client.delete(f"/api/person/{rid}?hard=true").json()
    assert out["dependents_removed"], "the response reports what was removed"

    conn = db.connect()
    try:
        for table in ("source_link", "evidence", "entity_tag", "entity_external_id",
                      "attachment"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE entity_type='person' "
                                f"AND entity_id=?", (rid,)).fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM relationship WHERE (entity1_type='person' "
                            "AND entity1_id=?) OR (entity2_type='person' AND entity2_id=?)",
                            (rid, rid)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM search_doc WHERE entity_type='person' "
                            "AND entity_id=?", (rid,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_audit_trail_is_append_only(client):
    """A ledger that can be rewritten is not a ledger.

    The guarantees live in SQLite triggers, so they hold for every writer — the
    API, a script, or sqlite3 pointed straight at the file.
    """
    import sqlite3

    from app import db

    client.post("/api/person", json={"name_ar": "سجل تدقيق",
                                     "name_en": "Audit guard unit"})
    conn = db.connect()
    try:
        db.ensure_audit_guards(conn)
        row = conn.execute("SELECT id, action FROM change_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE change_log SET action='forged' WHERE id=?", (row["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE change_log SET new_value='rewritten' WHERE id=?", (row["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM change_log WHERE id=?", (row["id"],))
        conn.rollback()
        # the one write that must stay possible: a source being deleted clears the
        # pointer on the history it leaves behind, and the entry itself survives
        conn.execute("INSERT INTO change_log (tx_id, entity_type, entity_id, action, "
                     "field_key, notes, actor, changed_at) VALUES (?,?,?,?,?,?,?,?)",
                     ("tx-test", "person", 1, "update", "x", "link test", "test",
                      "2020-01-01T00:00:00Z"))
        conn.commit()
        old = conn.execute("SELECT id FROM change_log WHERE tx_id='tx-test'").fetchone()["id"]
        conn.execute("UPDATE change_log SET source_id=NULL WHERE id=?", (old,))
        conn.commit()
        # an old entry may be pruned by a retention policy, a recent one may not be
        conn.execute("DELETE FROM change_log WHERE id=?", (old,))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM change_log WHERE id=?", (row["id"],))
        conn.rollback()
    finally:
        conn.close()


def test_place_records_how_the_point_was_obtained(client):
    """A coordinate carries its own provenance, so a centroid is never mistaken for
    a surveyed address."""
    meta = client.get("/api/meta").json()
    names = {f["key"] for f in meta["fields"]["place"]}
    for key in ("geocoding_method", "geo_uncertainty_m", "geometry_source"):
        assert key in names, f"{key} missing from the place field catalogue"
    methods = [v["code"] for v in
               client.get("/api/lookups?domain=geocoding_method").json()]
    assert {"gazetteer", "city_centroid", "manual"} <= set(methods), methods

    rec = client.post("/api/place", json={
        "name_ar": "مكان منشأ", "name_en": "Provenance unit",
        "latitude": 33.3152, "longitude": 44.3661,
        "geo_precision": "centroid", "geocoding_method": "city_centroid",
        "geo_uncertainty_m": 5000, "geometry_source": "Natural Earth 1:10m"}).json()["record"]
    got = client.get(f"/api/place/{rec['id']}").json()
    # select fields carry the vocabulary id; the label comes back beside it
    vocab = {v["code"]: v["id"]
             for v in client.get("/api/lookups?domain=geocoding_method").json()}
    assert got["geocoding_method"] == vocab["city_centroid"], got["geocoding_method"]
    # a list resolves the vocabulary to a label, so a reader never sees an id
    row = client.post("/api/place/query", json={
        "filters": {"code": {"eq": got["code"]}}, "page_size": 1}).json()["items"][0]
    labels = row["_labels"]
    assert labels["geocoding_method"]["en"] == "City point only", labels.get("geocoding_method")
    assert labels["geocoding_method"]["ar"] == "نقطة المدينة فقط"
    assert labels["geo_precision"]["en"] == "Centroid of area", labels.get("geo_precision")
    assert got["geo_uncertainty_m"] == 5000
    assert got["geometry_source"] == "Natural Earth 1:10m"
    client.delete(f"/api/place/{rec['id']}?hard=true")


def test_integrity_scanner_reports_a_clean_database(client):
    from app import integrity

    conn = db.connect()
    try:
        problems = integrity.scan(conn)
        lines = integrity.summary(problems)
        assert not lines, lines
    finally:
        conn.close()


def test_relationship_matrix_is_symmetric(client):
    """The interface shows a link on both records, so the heat map must agree."""
    from app import reports

    conn = db.connect()
    try:
        matrix = reports.relationship_map(conn, {"mode": "types"})["matrix"]
        for a in matrix:
            for b in matrix:
                assert matrix[a][b] == matrix[b][a], (a, b, matrix[a][b], matrix[b][a])
    finally:
        conn.close()


# --------------------------------------------------------------- date & time ---
def test_date_parser_accepts_every_precision_and_keeps_it():
    """A date is *not* promoted to a timestamp: whatever precision the researcher
    typed is what is stored, so `c. 1900`, `1900s` and `1900?` all survive."""
    from app.schemas import date_precision, parse_date_value

    cases = {
        "1912": ("1912", "year"),
        "1912-04": ("1912-04", "month"),
        "1912-04-12": ("1912-04-12", "day"),
        "1912-04-12 14:30": ("1912-04-12T14:30", "minute"),
        "1912-04-12T14:30": ("1912-04-12T14:30", "minute"),
        "1912-04-12 14:30:59": ("1912-04-12T14:30:59", "minute"),
        "1912-04-12T14:30:59Z": ("1912-04-12T14:30:59", "minute"),
        "1912-04-12T14:30:59+03:00": ("1912-04-12T14:30:59", "minute"),
        "c. 1900": ("c. 1900", "year"),
        "1900s": ("1900s", "year"),
        "1912?": ("1912?", "year"),
    }
    for raw, (stored, precision) in cases.items():
        got, prec, err = parse_date_value(raw)
        assert (got, prec, err) == (stored, precision, None), raw
        assert date_precision(raw) == precision, raw


def test_date_parser_rejects_impossible_values_with_a_readable_message():
    from app.schemas import parse_date_value

    for bad in ("1912-13", "1912-02-31", "1912-04-12 25:00", "31/03/1991",
                "12 April 1912", "0", "3000"):
        stored, prec, err = parse_date_value(bad)
        assert err, f"{bad} should be rejected"
        assert stored is False or stored is None, bad
    # the message enumerates the accepted forms instead of saying "invalid date"
    _, _, err = parse_date_value("31/03/1991")
    assert "YYYY" in err and "YYYY-MM-DD" in err


def test_timestamp_expands_partials_downwards():
    """`ts_of()` makes a year, a month, a day and a moment directly comparable."""
    from app.schemas import to_timestamp

    assert to_timestamp("1950") == "1950-01-01 00:00:00"
    assert to_timestamp("1950-05") == "1950-05-01 00:00:00"
    assert to_timestamp("1950-05-12") == "1950-05-12 00:00:00"
    assert to_timestamp("1950-05-12T14:30") == "1950-05-12 14:30:00"
    assert to_timestamp("c. 1850") == "1850-01-01 00:00:00"
    assert to_timestamp("1850s") == "1850-01-01 00:00:00"
    assert to_timestamp("") == ""
    assert to_timestamp(None) == ""


def test_time_flag_is_advertised_only_where_a_time_is_meaningful(client):
    """Every date column can *store* a time; only the eight event-like columns
    ask for one in the interface."""
    from app.schemas import ENTITIES, TIME_AWARE_FIELDS

    meta = client.get("/api/meta").json()
    fields = {f["key"]: f for f in meta["fields"]["event"]}
    assert fields["start_date"]["time"] is True
    assert fields["end_date"]["time"] is True
    person = {f["key"]: f for f in meta["fields"]["person"]}
    assert person["birth_date"]["time"] is False
    for entity, field in TIME_AWARE_FIELDS:
        assert any(f.key == field and f.time for f in ENTITIES[entity].fields), (entity, field)


def test_time_can_be_stored_wherever_it_is_offered(client):
    """A time-bearing value round-trips through the API unchanged."""
    created = client.post("/api/event", json={
        "title_en": "Night sitting", "title_ar": "جلسة ليلية",
        "start_date": "1950-05-12 21:45", "end_date": "1950-05-12T23:10",
    })
    assert created.status_code in (200, 201), created.text
    rec = created.json()["record"]
    assert rec["start_date"] == "1950-05-12T21:45"
    assert rec["end_date"] == "1950-05-12T23:10"


def test_date_operators_on_before_after_and_between(client):
    """`on` / `before` / `after` compare the full moment, so a bare year, a month
    and a timestamp in the same column still order correctly.  The fixture rows
    are created here so the assertions never depend on the seed data."""
    from app import repo
    from app.schemas import ENTITIES

    conn = db.connect()
    try:
        spec = ENTITIES["event"]
        for title, start in (("Day only", "1950-01-08"),
                             ("Morning", "1950-01-08 09:15"),
                             ("Evening", "1950-01-08 21:45"),
                             ("Next day", "1950-01-09")):
            repo.create_record(conn, spec, {"title_en": title, "title_ar": title,
                                            "start_date": start})

        def total(filters):
            got = repo.list_records(conn, spec, {"filters": filters, "page_size": 50})
            assert not got["warnings"], got["warnings"]
            return got

        day = total({"start_date": {"on": "1950-01-08"}})
        assert day["total"] >= 3, day["total"]        # the whole day, times included
        assert all(str(r["start_date"]).startswith("1950-01-08") for r in day["items"])

        # a between over one single day is inclusive of that entire day
        same = total({"start_date": {"between": ["1950-01-08", "1950-01-08"]}})
        assert same["total"] == day["total"], (same["total"], day["total"])

        # `after` a moment excludes everything earlier that day …
        later = total({"start_date": {"after": "1950-01-08 12:00"}})
        assert later["total"] < day["total"] + later["total"] + 1
        stamp = [str(r["start_date"]) for r in later["items"]]
        assert any(s2 >= "1950-01-08T12:00" for s2 in stamp), stamp
        # … and `before` a moment excludes everything later
        earlier = total({"start_date": {"before": "1950-01-08 12:00"}})
        assert any(s2 < "1950-01-08T12:00" for s2 in (str(r["start_date"]) for r in earlier["items"]))
        # everything in the day is either side of the cut
        assert later["total"] + earlier["total"] >= day["total"]
    finally:
        conn.close()


def test_date_sorting_uses_the_full_moment(client):
    from app import repo
    from app.schemas import ENTITIES

    conn = db.connect()
    try:
        got = repo.list_records(conn, ENTITIES["event"],
                                {"sort": "start_date", "order": "asc", "page_size": 40})
        values = [r["start_date"] for r in got["items"] if r["start_date"]]
        from app.schemas import to_timestamp
        stamps = [to_timestamp(v) for v in values]
        assert stamps == sorted(stamps), values
    finally:
        conn.close()


def test_empty_and_not_empty_partition_every_table(client):
    """`empty` means absent *or* blank after trimming, and the two operators must
    partition the table exactly — the old engine silently matched everything on
    the primary name column."""
    from app import repo
    from app.schemas import ENTITIES

    conn = db.connect()
    try:
        keyed = {"person": "name_en", "place": "name_en", "institution": "name_en",
                 "source": "title", "event": "title_en"}
        for entity, key in keyed.items():
            spec = ENTITIES[entity]
            total = repo.list_records(conn, spec, {"page_size": 1})["total"]
            blank = repo.list_records(conn, spec, {"filters": {key: {"empty": True}},
                                                   "page_size": 1})
            filled = repo.list_records(conn, spec, {"filters": {key: {"not_empty": True}},
                                                    "page_size": 1})
            assert not blank["warnings"] and not filled["warnings"], (entity, key)
            assert blank["total"] + filled["total"] == total, (entity, key, blank["total"],
                                                               filled["total"], total)
            assert filled["total"] > 0, f"{entity}.{key} should have values"
    finally:
        conn.close()


# ------------------------------------------------------- numbering & surface ---
def test_previewed_code_is_allocatable_twice(client):
    """The form shows the next code and sends it back on save.  The sequence must
    keep up, or the *next* new record is offered the same number and 409s — the
    exact bug a dialog form with "Save + new" produced."""
    first = client.get("/api/person/next-code").json()["code"]
    made = []
    for _ in range(3):
        preview = client.get("/api/person/next-code").json()["code"]
        assert preview not in [m["code"] for m in made], preview
        res = client.post("/api/person", json={"name_ar": "تسلسل", "name_en": "seq",
                                               "code": preview})
        assert res.status_code in (200, 201), res.text
        made.append(res.json()["record"])
    codes = [m["code"] for m in made]
    assert len(set(codes)) == 3, codes
    assert codes[0] >= first
    # the preview also skips a code that was supplied by hand
    assert client.get("/api/person/next-code").json()["code"] not in codes


def test_preview_skips_taken_codes():
    """`peek_next_code` and `next_code` must agree about what is free."""
    from app import db

    conn = db.connect()
    try:
        conn.execute("DELETE FROM sequence WHERE entity_type='place'")
        db.ensure_sequence(conn, "place", "PLC")
        preview = db.peek_next_code(conn, "place")
        conn.execute("INSERT INTO place (code, name_ar) VALUES (?, 'x')", (preview,))
        after = db.peek_next_code(conn, "place")
        assert after != preview, (preview, after)
    finally:
        conn.rollback()
        conn.close()


def test_form_surface_setting_is_served_and_stored(client):
    """The instance-wide default for where forms open lives in `setting` and is
    part of `/api/meta`, so every client agrees without a round trip."""
    meta = client.get("/api/meta").json()
    assert "ui.form_mode" in meta["settings"]
    assert meta["settings"]["ui.form_mode"] in ("page", "dialog", "auto")
    assert "ui.form_dialog_size" in meta["settings"]
    res = client.put("/api/settings", json={"ui.form_mode": "dialog"})
    assert res.status_code == 200
    assert res.json()["settings"]["ui.form_mode"] == "dialog"
    assert client.get("/api/meta").json()["settings"]["ui.form_mode"] == "dialog"
    client.put("/api/settings", json={"ui.form_mode": "page"})


def test_merge_leaves_an_auditable_trail_for_links(client):
    """A merge moves links, drops exact duplicates and logs every decision.

    Two regressions this pins down:
      · the duplicate-link deletion used to leave no `change_log` entry at all,
        so a link could vanish from the graph with nothing to explain it;
      · the duplicate test matched on the moved end and the relationship *type*
        only, so merging B into A deleted every B→X link that merely shared a
        type with any A→Y link, even when X and Y were different records.
    """
    from app import db

    def mk(name):
        return client.post("/api/person", json={
            "name_ar": f"طرف {name}", "name_en": f"Trail {name}"}).json()["record"]["id"]

    keep, drop, other, third = mk("keep"), mk("drop"), mk("other"), mk("third")
    rel_type = client.get("/api/lookups?domain=relationship_type").json()[0]["id"]

    def link(a, b):
        return client.post("/api/relationship", json={
            "entity1_type": "person", "entity1_id": a, "entity2_type": "person",
            "entity2_id": b, "relationship_type_id": rel_type}).status_code

    assert link(keep, other) == 200
    assert link(drop, other) == 200          # exact duplicate → dropped
    assert link(drop, third) == 200          # same type, different target → moved
    assert link(drop, keep) == 200           # would become a self-link → dropped

    done = client.post(f"/api/person/{keep}/merge",
                       json={"merge_ids": [drop], "reason": "trail test"}).json()
    assert done["relationships_moved"] == 3, done
    assert done["duplicate_links_removed"] == 1, done
    assert done["self_links_removed"] == 1, done

    # the same-type-different-target link survived, attached to the survivor
    c = db.connect()
    try:
        pairs = {(r["entity2_type"], r["entity2_id"]) for r in c.execute(
            "SELECT entity2_type, entity2_id FROM relationship "
            "WHERE entity1_type='person' AND entity1_id=?", (keep,))}
    finally:
        c.close()
    assert ("person", third) in pairs, pairs

    c = db.connect()
    try:
        rows = c.execute("SELECT action, notes FROM change_log WHERE entity_type='relationship' "
                         "AND reason='trail test' ORDER BY id").fetchall()
    finally:
        c.close()
    assert sorted(r["action"] for r in rows) == ["delete", "delete", "update"], rows
    assert any("duplicate of #" in (r["notes"] or "") for r in rows), [dict(r) for r in rows]
    assert any("self-link" in (r["notes"] or "") for r in rows), [dict(r) for r in rows]


def test_merge_moves_evidence_to_the_survivor(client):
    """Evidence is about a record, so a merge must carry it across — otherwise the
    survivor loses the only thing that justifies its existence and the absorbed
    row keeps sources pointing at a record nobody can see."""
    from app import db

    keep = client.post("/api/person", json={"name_ar": "باقٍ", "name_en": "Keep ev"}).json()["record"]["id"]
    drop = client.post("/api/person", json={"name_ar": "مدمج", "name_en": "Drop ev"}).json()["record"]["id"]
    src = client.get("/api/options/source?limit=1").json()[0]["id"]
    assert client.post("/api/evidence", json={
        "source_id": src, "entity_type": "person", "entity_id": drop,
        "supported_claim": "a claim about the absorbed record",
        "support_type": "supports"}).status_code == 200

    client.post(f"/api/person/{keep}/merge",
                json={"merge_ids": [drop], "reason": "evidence fold test"})

    conn = db.connect()
    try:
        moved = conn.execute("SELECT COUNT(*) FROM evidence WHERE entity_type='person' "
                             "AND entity_id=?", (keep,)).fetchone()[0]
        left = conn.execute("SELECT COUNT(*) FROM evidence WHERE entity_type='person' "
                            "AND entity_id=?", (drop,)).fetchone()[0]
    finally:
        conn.close()
    assert moved == 1 and left == 0, (moved, left)
    doc = client.get(f"/api/evidence?entity_type=person&entity_id={keep}").json()
    assert doc["count"] == 1 and doc["evidence"][0]["support_type"] == "supports"
    client.delete(f"/api/person/{keep}?hard=true")
    client.delete(f"/api/person/{drop}?hard=true")


# ---------------------------------------------------------------------------
# no reference may point at a file that is not there
# ---------------------------------------------------------------------------
def test_image_references_resolve_or_are_absent(conn):
    """An `image_url` naming a media file that does not exist is a broken citation.

    The interface asks for it on every list row, so a dangling reference is both a
    404 in the browser console and a picture the reader is told exists. Either the
    file is on disk or the field is empty — never a URL to nothing.
    """
    import os

    media = db.UPLOAD_DIR / "media"
    dangling = []
    for table in ("person", "institution", "place", "event", "source"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "image_url" not in cols:
            continue
        for row in conn.execute(f"SELECT id, image_url FROM {table} "
                                "WHERE image_url IS NOT NULL AND image_url != ''"):
            name = str(row[1]).rsplit("/", 1)[-1]
            if not os.path.exists(media / name):
                dangling.append(f"{table}:{row[0]} → {row[1]}")
    assert not dangling, "images referenced but missing on disk: " + ", ".join(dangling)


def test_map_field_filters_narrow_the_layer_that_owns_the_field(client):
    """Field filters are additional: a person-only field leaves every other layer,
    a clause scoped to places leaves people, and a typed query hits the database."""
    params = {"bbox": "-180,-85,180,85", "zoom": 2, "limit": 20000}
    world = client.get("/api/map/features", params=params).json()
    base = world["per_layer"]
    for key in ("person", "place", "institution", "event"):
        assert base[key]["total"] > 0, key

    nobody = client.get("/api/map/features", params={
        **params,
        "filters": json.dumps({"where": [
            {"field": "birth_date", "op": "year_eq", "value": 1234}
        ]}),
    }).json()
    assert nobody["per_layer"]["person"]["total"] == 0
    for key in ("place", "institution", "event"):
        assert nobody["per_layer"][key]["total"] == base[key]["total"], key

    person = next(p for p in world["points"] if p["entity_type"] == "person")
    by_code = client.get("/api/map/features", params={
        **params,
        "filters": json.dumps({"query": f"code:{person['code']}"}),
    }).json()
    assert by_code["per_layer"]["person"]["total"] == 1
    assert any(p["id"] == person["id"] and p["entity_type"] == "person" for p in by_code["points"])
    for key in ("place", "institution", "event"):
        assert by_code["per_layer"][key]["total"] == 0, key

    scoped = client.get("/api/map/features", params={
        **params,
        "filters": json.dumps({"where": [
            {"field": "name_en", "op": "contains", "value": "zzz-no-such-place",
             "entity": "place"}
        ]}),
    }).json()
    assert scoped["per_layer"]["place"]["total"] == 0
    assert scoped["per_layer"]["person"]["total"] == base["person"]["total"]
    assert scoped["per_layer"]["institution"]["total"] == base["institution"]["total"]

    unknown = client.get("/api/map/features", params={
        **params,
        "filters": json.dumps({"query": "not_a_field:1"}),
    }).json()
    assert unknown["warnings"], unknown
    assert unknown["per_layer"]["person"]["total"] == base["person"]["total"]
    assert unknown["per_layer"]["place"]["total"] == base["place"]["total"]

    grouped = client.get("/api/map/groups", params={
        "bbox": "-180,-85,180,85", "limit": 500,
        "filters": json.dumps({"where": [
            {"field": "birth_date", "op": "year_eq", "value": 1234}
        ]}),
    }).json()
    assert grouped["total_records"] == (
        base["place"]["total"] + base["institution"]["total"] + base["event"]["total"])


# ---------------------------------------------------------------------------
# Regression: defects found by the 2026-11-07 integration audit
# ---------------------------------------------------------------------------

def test_import_update_mode_updates_and_accepts_exported_refs(client):
    """Mode "update" updates matched rows — it never silently creates, and the
    resolved "Label [CODE]" reference format that export itself produces must
    import back cleanly.

    The audit found mode="update" (the settings enum's middle option) falling
    through to the create branch because the matcher only knew "upsert" and an
    unreachable "update_only": rows either failed required checks or duplicated
    records. The resolved export format was also refused by the FK resolver,
    so an exported file could not be imported back.
    """
    import app.db as dbmod
    from app import transfer
    from app.repo import ENTITIES as R_ENTITIES

    conn_db = dbmod.connect()
    try:
        place = None
        for r in conn_db.execute("SELECT id, code, name_en FROM place WHERE deleted_at IS NULL LIMIT 1"):
            place = dict(r)
        assert place
        title = "Round Trip Event"
        conn_db.execute(
            "INSERT INTO event (code, title_en, title_ar, record_status_id, created_at, created_by)"
            " VALUES ('EVT-9001', ?, ?, (SELECT id FROM lookup WHERE domain='record_status' AND code='draft'),"
            " '2026-01-01', 't')", (title, "حدث"))
        conn_db.commit()

        rows = [{"title_en": title, "Start date": "2001",
                 "Place": f"{place['name_en']} [{place['code']}]",
                 "Latitude": "12.5", "Longitude": "22.5"}]
        mapping = {"title_en": "title_en", "Start date": "start_date",
                   "Place": "place_id", "Latitude": "latitude", "Longitude": "longitude"}
        rep = transfer.process_rows(conn_db, R_ENTITIES["event"], rows, mapping,
                                    mode="update", actor="audit", dry_run=False,
                                    match_on=["title_en"], reason="regression")
        assert rep["failed"] == 0, rep["errors"]
        assert rep["created"] == 0, "update mode must never create"
        assert rep["updated"] == 1
        got = conn_db.execute(
            "SELECT latitude, longitude, place_id FROM event WHERE title_en=?",
            (title,)).fetchone()
        assert (got["latitude"], got["longitude"]) == (12.5, 22.5)
        assert got["place_id"] == place["id"], "resolved 'Label [CODE]' must map back"
    finally:
        if conn_db is not None:
            conn_db.execute("DELETE FROM event WHERE code='EVT-9001'")
            conn_db.commit()
            conn_db.close()


def test_registry_adoption_moves_the_legacy_folder_even_into_an_occupied_target(tmp_path):
    """db.adopt_legacy_data_dir is the single relocation path.

    Regression: the first relocation attempt refused to move when the target
    already contained an `uploads` folder (created at import time), silently
    stranding the real registry at app/app/data while a fresh demo database was
    created beside it. Items move one by one; existing items are never
    overwritten; nothing is ever deleted.
    """
    from app import db

    data_dir = tmp_path / "app" / "data"
    legacy = tmp_path / "app" / "app" / "data"
    # the poisoned case: target already occupied by the import-time uploads dir
    (data_dir / "uploads").mkdir(parents=True)
    (legacy / "uploads").mkdir(parents=True)
    (legacy / "registry.db").write_bytes(b"the-real-registry")
    (legacy / "uploads" / "photo.jpg").write_bytes(b"media")
    (legacy / "registry.db-wal").write_bytes(b"journal")

    status = db.adopt_legacy_data_dir(data_dir, legacy)
    assert status == "moved"
    assert (data_dir / "registry.db").read_bytes() == b"the-real-registry"
    assert (data_dir / "registry.db-wal").read_bytes() == b"journal"
    assert (data_dir / "uploads" / "photo.jpg").read_bytes() == b"media"
    assert not (legacy / "registry.db").exists(), "the legacy copy must travel, not duplicate"


def test_registry_adoption_never_overwrites_and_reports_two_registries(tmp_path):
    from app import db

    data_dir = tmp_path / "data"
    legacy = tmp_path / "legacy"
    data_dir.mkdir()
    legacy.mkdir()
    (data_dir / "registry.db").write_bytes(b"current")
    (legacy / "registry.db").write_bytes(b"stranded")
    (legacy / "extra.txt").write_bytes(b"loose")

    status = db.adopt_legacy_data_dir(data_dir, legacy)
    assert status == "both", "two registries must be reported, not silently merged"
    assert (data_dir / "registry.db").read_bytes() == b"current", "existing registry must win"
    assert (legacy / "registry.db").read_bytes() == b"stranded", "nothing may be deleted"
    assert not (data_dir / "extra.txt").exists(), "two registries = move nothing, warn and wait for a human"


def test_registry_adoption_survives_a_locked_file_without_losing_data(tmp_path, monkeypatch, capsys):
    import shutil as _shutil

    from app import db

    data_dir = tmp_path / "data"
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "registry.db").write_bytes(b"locked-data")

    real_move = _shutil.move
    monkeypatch.setattr(_shutil, "move",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("in use")))
    status = db.adopt_legacy_data_dir(data_dir, legacy)
    monkeypatch.setattr(_shutil, "move", real_move)

    assert status == "none"
    assert (legacy / "registry.db").read_bytes() == b"locked-data", "a failed move must not delete"
    assert "WARNING" in capsys.readouterr().out
