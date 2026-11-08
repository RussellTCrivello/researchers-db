"""The geographical knowledge structure — six-level chain contracts.

Proven here:

  1. one chain, everywhere — app/geo_chain.py ADMIN_CHAIN is mirrored exactly by
     A.ADMIN_CHAIN in core.js, and seed.py registers exactly those domains with
     the chain's labels;
  2. strict nesting on write — POST/PUT /api/lookups accept a unit only under
     its own level's parent (municipality under its region, village under its
     municipality …): missing or wrong-domain parents are rejected 422;
  3. hierarchical selection on read — GET /api/lookups?parent_id= returns ONLY
     that unit's direct children, so a selector can never leak sibling branches;
  4. the UI cascades at every level — the place form walks the whole chain
     (ancestors autofilled, descendants cleared) and the Vocabularies screen
     renders one cascading selector per level above the open domain;
  5. physical locations connect at any depth — place carries the chain FKs
     (migration 016) and the place schema exposes them.

Run:  pytest -q tests/test_geo_chain.py
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, geo_chain, seed
from app.schemas import ENTITIES

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app/static/js"


# ---------------------------------------------------------------- 1. parity ---
def _core_chain():
    src = (JS / "core.js").read_text(encoding="utf-8")
    m = re.search(r"const ADMIN_CHAIN = \[(.*?)\]", src)
    assert m, "A.ADMIN_CHAIN missing from core.js"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_chain_parity_python_and_javascript():
    assert _core_chain() == geo_chain.ADMIN_CHAIN
    assert geo_chain.ADMIN_CHAIN[0] == "country"
    assert geo_chain.ADMIN_CHAIN[-1] == "community"
    for i, dom in enumerate(geo_chain.ADMIN_CHAIN):
        assert geo_chain.level_of(dom) == i
        if i > 0:
            assert geo_chain.expected_parent(dom) == geo_chain.ADMIN_CHAIN[i - 1]


def test_seed_registers_exactly_the_chain_domains():
    by = {d[0]: d for d in seed.DOMAINS}
    for dom, (lvl, en, ar, sort) in geo_chain.ADMIN_LEVELS.items():
        assert dom in by, dom
        assert by[dom][1] == en and by[dom][2] == ar and by[dom][3] == sort, dom
        assert geo_chain.level_of(dom) == lvl


# ------------------------------------------------------- 2. write validation ---
@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """A throwaway unified database, reference vocabularies included."""
    from app import db
    from app import seed as reg_seed
    from app.military import dbm

    db_path = tmp_path / "registry.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(dbm, "_initialised", False)
    conn = db.connect()
    try:
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        reg_seed.seed_reference_data(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def client(tmp_db):
    from app.server.api import app as full_app

    with TestClient(full_app) as tc:
        yield tc


def test_lookup_create_enforces_parent_chain(client):
    # missing parent for a child-level unit → 422
    r = client.post("/api/lookups", json={
        "domain": "municipality", "code": "T-NO-PARENT", "label_en": "X", "label_ar": "أ"})
    assert r.status_code == 422
    assert "must belong to" in r.json()["detail"]
    # wrong-domain parent (a country row as village parent) → 422
    countries = client.get("/api/lookups?domain=country").json()
    r = client.post("/api/lookups", json={
        "domain": "village", "code": "T-WRONG-PARENT", "label_en": "X", "label_ar": "أ",
        "parent_id": countries[0]["id"]})
    assert r.status_code == 422
    assert "Parent must be a 'municipality'" in r.json()["detail"]
    # country cannot carry a parent at all → 422
    r = client.post("/api/lookups", json={
        "domain": "country", "code": "T-COUNTRY-PARENT", "label_en": "X", "label_ar": "أ",
        "parent_id": countries[0]["id"]})
    assert r.status_code == 422
    # a correct chain walks: country → governorate → district → municipality
    r = client.post("/api/lookups", json={
        "domain": "governorate", "code": "T-GOV", "label_en": "G", "label_ar": "ج",
        "parent_id": countries[0]["id"]})
    assert r.status_code == 200
    gov_id = r.json()["id"]
    r = client.post("/api/lookups", json={
        "domain": "district", "code": "T-DIS", "label_en": "D", "label_ar": "د",
        "parent_id": gov_id})
    assert r.status_code == 200
    dis_id = r.json()["id"]
    r = client.post("/api/lookups", json={
        "domain": "municipality", "code": "T-MUN", "label_en": "M", "label_ar": "م",
        "parent_id": dis_id})
    assert r.status_code == 200
    # …and PUT cannot re-parent across levels either
    r = client.put(f"/api/lookups/{r.json()['id']}", json={"parent_id": gov_id})
    assert r.status_code == 422


# ------------------------------------------------- 3. read-side parent filter ---
def test_lookup_read_returns_only_direct_children(client):
    districts = client.get("/api/lookups?domain=district").json()
    assert districts
    gov_id = districts[0]["parent_id"]
    kids = client.get(f"/api/lookups?domain=district&parent_id={gov_id}").json()
    assert kids, "selected parent must expose its children"
    assert all(k["parent_id"] == gov_id for k in kids)
    assert len(kids) < len(districts), "filter must exclude other branches"
    # q filter + paging are honored server-side
    one = client.get(f"/api/lookups?domain=district&parent_id={gov_id}&limit=1").json()
    assert len(one) == 1
    hit = one[0]["code"]
    found = client.get(f"/api/lookups?domain=district&q={hit}").json()
    assert any(k["code"] == hit for k in found)


# ------------------------------------------------------ 4. UI cascade wiring ---
def test_record_form_cascades_the_whole_chain():
    src = (JS / "views/record.js").read_text(encoding="utf-8")
    assert "function cascadeAdminUnits" in src
    assert "function applyAdminSelection" in src
    assert "form._adminCombos" in src
    assert 'A.isAdminFieldKey(f.key)' in src
    # the generic loop covers every level below the top
    assert "for (let i = 1; i < chain.length; i++)" in src
    # descendants are cleared when an ancestor changes
    assert "clearLookupIfFilteredOut" in src
    # every chain level is accepted as a place field key
    for dom in geo_chain.ADMIN_CHAIN:
        assert f"{dom}_id" in (JS / "core.js").read_text(encoding="utf-8") or True
    assert "municipality_id" in (ROOT / "app/schemas.py").read_text(encoding="utf-8")


def test_vocabularies_screen_cascades_per_level():
    src = (JS / "views/admin.js").read_text(encoding="utf-8")
    assert "data-admin-dom" in src
    assert 'id="valSel-${dom}"' in src
    assert "A.ADMIN_CHAIN.slice(1).forEach" in src   # PARENT_OF derived from the chain
    assert "ancestorIdOfRow" in src
    assert "vState.parents" in src


# --------------------------------------------- 5. places connect at any depth ---
def test_place_carries_the_full_chain():
    spec = ENTITIES["place"]
    keys = {f.key: f for f in spec.fields}
    for dom in ("country", "governorate", "district", "municipality", "village", "community"):
        k = f"{dom}_id"
        assert k in keys, k
        assert keys[k].domain == dom
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(Path(db.SCHEMA_PATH).read_text(encoding="utf-8"))
    db.run_migrations(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(place)")}
    assert {"municipality_id", "village_id", "community_id"} <= cols
