"""Commander ↔ individual integration + the unit's own map.

Two features, one rule of honesty: the commander dossier now encompasses the
linked individual's details (``commander.person_id`` bridges the two), and the
unit dossier shows a map of the UNIT'S OWN location — its own coordinates and
its deployments' — never the commander's personal location. ``service.unit_geo``
serves unit-owned rows only, and these tests hold that distinction in place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.military import dbm, service
from app.military import specs as mil_specs

ROOT = Path(__file__).resolve().parent.parent
MIL_JS = (ROOT / "app/static/js/views/military.js").read_text(encoding="utf-8")
REC_JS = (ROOT / "app/static/js/views/record.js").read_text(encoding="utf-8")
GEO_JS = (ROOT / "app/static/js/lib/geopin.js").read_text(encoding="utf-8")
API_PY = (ROOT / "app/military/api.py").read_text(encoding="utf-8")
SVC_PY = (ROOT / "app/military/service.py").read_text(encoding="utf-8")
SPEC_PY = (ROOT / "app/military/specs.py").read_text(encoding="utf-8")

HDRS = {"X-Military-Role": "admin"}

NEW_KEYS = [
    "mil.cmd.appointment", "mil.cmd.commissioned", "mil.cmd.current",
    "mil.cmd.empty", "mil.cmd.since", "mil.cmd.title", "mil.cmd.unit",
    "mil.ind.birth", "mil.ind.death", "mil.ind.find", "mil.ind.link",
    "mil.ind.linkHint", "mil.ind.linked", "mil.ind.nationality",
    "mil.ind.notLinked", "mil.ind.open", "mil.ind.position",
    "mil.ind.positions", "mil.ind.relationships", "mil.ind.tab",
    "mil.map.addLocation", "mil.map.deployments", "mil.map.empty",
    "mil.map.emptyHint", "mil.map.noCoords", "mil.map.notCommander",
    "mil.map.ownCaption", "mil.map.ownPin", "mil.map.source", "mil.map.tab",
]


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the unified registry database at a throwaway file (per test)."""
    from app import db
    db_path = tmp_path / "registry.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(dbm, "_initialised", False)
    conn = db.connect()
    try:
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def client(tmp_db):
    from app.server.api import app as full_app
    with TestClient(full_app) as tc:
        yield tc


def _rec(resp) -> dict:
    body = resp.json()
    return body.get("record") or body


def _err(resp) -> dict:
    body = resp.json()
    return body.get("error") or (body.get("detail") or {}).get("error") or {}


def _make_person(tmp_db, name="QA Individual", lat=None, lon=None) -> int:
    from app import db
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO person (code, name_ar, name_en, latitude, longitude) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"QA-P-{abs(hash((name, lat, lon))) % 100000}", name, name, lat, lon))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------- backend


def test_link_and_own_geo_columns_exist(tmp_db):
    dbm.ensure()
    from app import db
    conn = db.connect()
    try:
        for table, cols in {
            "commander": {"person_id"},
            "military_unit": {"latitude", "longitude", "geometry_source"},
            "operational_deployment": {"latitude", "longitude", "geometry_source"},
        }.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert cols <= have, f"{table} missing {cols - have}"
    finally:
        conn.close()


def test_both_spec_layers_carry_the_new_fields():
    meta = mil_specs._build_specs()
    unit_keys = {f.key for f in meta["unit"].fields}
    dep_keys = {f.key for f in meta["deployment"].fields}
    cmd_keys = {f.key for f in meta["commander"].fields}
    assert {"latitude", "longitude", "geometry_source"} <= unit_keys
    assert {"latitude", "longitude", "geometry_source"} <= dep_keys
    assert "person_id" in cmd_keys
    svc = service.ENTITY_SPECS
    for ent, cols in (("unit", {"latitude", "longitude", "geometry_source"}),
                      ("deployment", {"latitude", "longitude", "geometry_source"}),
                      ("commander", {"person_id"})):
        names = {f["name"] for f in svc[ent]["fields"]}
        assert cols <= names, f"{ent} service spec missing {cols - names}"
    # the coordinate pair is a float with honest bounds in the service layer
    unit_fields = {f["name"]: f for f in svc["unit"]["fields"]}
    assert unit_fields["latitude"]["min"] == -90.0
    assert unit_fields["longitude"]["max"] == 180.0


def test_unit_coords_roundtrip_and_bounds(client):
    created = client.post("/api/unit", json={"name": "Geo Unit"}, headers=HDRS)
    assert created.status_code in (200, 201)
    uid = _rec(created)["id"]
    upd = client.patch(f"/api/unit/{uid}", json={
        "latitude": 36.2021, "longitude": 37.1343,
        "geometry_source": "map pick"}, headers=HDRS)
    assert upd.status_code == 200
    got = _rec(client.get(f"/api/unit/{uid}"))
    assert abs(got["latitude"] - 36.2021) < 1e-9
    assert abs(got["longitude"] - 37.1343) < 1e-9
    assert got["geometry_source"] == "map pick"

    for payload, field in (({"latitude": 91}, "latitude"),
                           ({"latitude": -90.5}, "latitude"),
                           ({"longitude": 181}, "longitude"),
                           ({"longitude": "abc"}, "longitude")):
        bad = client.patch(f"/api/unit/{uid}", json=payload, headers=HDRS)
        assert bad.status_code == 422, payload
        assert _err(bad).get("field") == field, payload


def test_unit_geo_serves_own_location_only(client, tmp_db):
    """The unit's own coordinates and its deployments — never the commander's."""
    unit = _rec(client.post("/api/unit", json={
        "name": "Geo Parent", "latitude": 36.2, "longitude": 37.1}, headers=HDRS))
    uid = unit["id"]
    located = _rec(client.post("/api/deployment", json={
        "name": "Located Deployment", "unit_id": uid,
        "start_date": "2026-01-01", "location": "North sector",
        "latitude": 35.0, "longitude": 38.0}, headers=HDRS))
    unnamed = _rec(client.post("/api/deployment", json={
        "name": "Text-only Deployment", "unit_id": uid,
        "start_date": "2025-01-01", "location": "South sector"}, headers=HDRS))

    # a commander firmly attached to this unit — with a person at ANOTHER place
    pid = _make_person(tmp_db, "Geo Ghost Commander", lat=24.0, lon=45.0)
    cmd = _rec(client.post("/api/commander", json={
        "full_name": "Geo Ghost Commander", "person_id": pid}, headers=HDRS))
    asg = client.post("/api/assignment", json={
        "unit_id": uid, "commander_id": cmd["id"], "role": "Commanding Officer",
        "assigned_date": "2026-01-01", "is_current": True}, headers=HDRS)
    assert asg.status_code in (200, 201)

    geo = client.get(f"/api/military/units/{uid}/geo")
    assert geo.status_code == 200
    data = geo.json()
    assert set(data.keys()) == {"ok", "unit", "deployments", "region"}
    assert data["unit"]["own"] is True
    assert data["unit"]["lat"] == 36.2 and data["unit"]["lon"] == 37.1

    deps = {d["id"]: d for d in data["deployments"]}
    assert deps[located["id"]]["lat"] == 35.0
    assert deps[unnamed["id"]]["lat"] is None
    assert deps[unnamed["id"]]["location"] == "South sector"

    # THE distinction: no point in this payload may be the commander's location
    points = [(data["unit"]["lat"], data["unit"]["lon"])]
    points += [(d["lat"], d["lon"]) for d in data["deployments"]]
    assert (24.0, 45.0) not in points
    assert "Geo Ghost Commander" not in json.dumps(data)


def test_commander_person_link_roundtrip(client, tmp_db):
    pid = _make_person(tmp_db, "Linked Individual")
    created = client.post("/api/commander", json={
        "full_name": "Linked Commander", "person_id": pid}, headers=HDRS)
    assert created.status_code in (200, 201)
    cid = _rec(created)["id"]
    assert _rec(client.get(f"/api/commander/{cid}"))["person_id"] == pid

    listed = client.get(f"/api/military/commanders?person_id={pid}")
    assert listed.status_code == 200
    assert any(r["id"] == cid for r in listed.json()["records"])

    # the dossier's link flow: a partial PATCH moves the link
    pid2 = _make_person(tmp_db, "Better Match")
    upd = client.patch(f"/api/commander/{cid}", json={"person_id": pid2}, headers=HDRS)
    assert upd.status_code == 200
    assert _rec(client.get(f"/api/commander/{cid}"))["person_id"] == pid2

    cleared = client.patch(f"/api/commander/{cid}", json={"person_id": None}, headers=HDRS)
    assert cleared.status_code == 200
    assert _rec(client.get(f"/api/commander/{cid}"))["person_id"] in (None, "")


# ---------------------------------------------------------------- front-end


def test_unit_map_and_individual_wiring_shipped():
    for needle in ("milMapShell", "paintIndividualTab", "disposeDossierMap",
                   "mil.map.ownCaption", "mil.map.notCommander",
                   "mil.ind.linkHint", "data-indlink", "#/entity/person/",
                   "person_id", "A.geopin.marker", "/geo"):
        assert needle in MIL_JS, needle
    for needle in ("commandServiceCard", "/api/military/commanders?person_id=",
                   "mil.cmd.title", "#/military/units/"):
        assert needle in REC_JS, needle
    assert 'unit: "#e8a13c"' in GEO_JS
    assert 'deployment: "#9d7bd8"' in GEO_JS
    # the honesty rule is pinned at both ends of the wire
    assert "not the commander's location" in API_PY
    assert "must never stand in for the unit's" in SVC_PY
    assert '_ref("person_id", "person"' in SPEC_PY
    assert '_f("person_id", "ref"' in SVC_PY


def test_locales_complete_and_sorted():
    en = json.loads((ROOT / "app/static/js/locales/en.json").read_text(encoding="utf-8"))
    ar = json.loads((ROOT / "app/static/js/locales/ar.json").read_text(encoding="utf-8"))
    assert set(en) == set(ar)
    assert list(en) == sorted(en, key=lambda k: k.encode("utf-8"))
    assert list(ar) == sorted(ar, key=lambda k: k.encode("utf-8"))
    for k in NEW_KEYS:
        assert en.get(k), k
        assert ar.get(k), k
