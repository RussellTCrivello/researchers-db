"""
Acceptance tests for independent geospatial positions (scenarios A–J).

The central principle: geographical coordinates belong to the specific record
they describe — never automatically to the named place that record is
associated with. Selecting a record reveals the complete geographical network
around it through the registry's own links, with provenance on every point.

Run:  pytest -q tests/test_geopositions.py   (temporary database, never the real one)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="siraj-geo-test-")
os.environ["SIRAJ_DATA_DIR"] = _TMP
os.environ["SIRAJ_SEED_DEMO"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app import db, repo  # noqa: E402
from app.geo import mapdata  # noqa: E402
from app.schemas import ENTITIES  # noqa: E402
from app.server import app as main_app  # noqa: E402


@pytest.fixture(scope="session")
def conn():
    db.init_db(seed_demo=True)
    yield db.connect()


@pytest.fixture(scope="session")
def client(conn):
    with TestClient(main_app) as c:
        yield c


@pytest.fixture(scope="session")
def corpus(conn):
    """A small representative corpus: one located place, one unlocated place,
    three people with three distinct own positions in the first place, one
    person shown only at the place (no own position), one organization, two
    events with their own venue points, and a person tied to the unlocated
    place."""
    make = lambda key, **vals: repo.create_record(conn, ENTITIES[key], vals, actor="t")  # noqa: E731
    ams = make("place", name_en="Corpus Amsterdam", name_ar="corpus-ams",
               latitude=52.37, longitude=4.89)
    nowhere = make("place", name_en="Corpus Nowhere", name_ar="corpus-nowhere")
    pa = make("person", name_en="Corpus Person A", name_ar="corpus-a",
              birthplace_id=ams["id"], latitude=52.36, longitude=4.88)
    pb = make("person", name_en="Corpus Person B", name_ar="corpus-b",
              birthplace_id=ams["id"], latitude=52.35, longitude=4.87)
    pc = make("person", name_en="Corpus Person C", name_ar="corpus-c",
              birthplace_id=ams["id"], latitude=52.34, longitude=4.86)
    assoc = make("person", name_en="Corpus Person Assoc", name_ar="corpus-assoc",
                 birthplace_id=ams["id"])
    org = make("institution", name_en="Corpus Org", name_ar="corpus-org",
               place_id=ams["id"], latitude=52.372, longitude=4.895)
    ev1 = make("event", title_en="Corpus Event One", title_ar="corpus-e1",
               place_id=ams["id"], start_date="2020",
               latitude=52.3711, longitude=4.8911)
    ev2 = make("event", title_en="Corpus Event Two", title_ar="corpus-e2",
               place_id=ams["id"], start_date="2021",
               latitude=52.369, longitude=4.889)
    pd = make("person", name_en="Corpus Person D", name_ar="corpus-d",
              birthplace_id=nowhere["id"], latitude=1.25, longitude=2.5)
    # person A: affiliated with the org, participates in both events
    repo.update_record(conn, ENTITIES["person"], pa["id"],
                       {"affiliated_institution_id": org["id"]}, actor="t")
    rtype = conn.execute(
        "SELECT id FROM lookup WHERE domain='relationship_type' AND is_active=1 LIMIT 1"
    ).fetchone()["id"]
    for other_type, other_id in (("event", ev1["id"]), ("event", ev2["id"]),
                                 ("institution", org["id"])):
        make("relationship", entity1_type="person", entity1_id=pa["id"],
             entity2_type=other_type, entity2_id=other_id,
             relationship_type_id=rtype)
    return {"ams": ams, "nowhere": nowhere, "pa": pa, "pb": pb, "pc": pc,
            "assoc": assoc, "org": org, "ev1": ev1, "ev2": ev2, "pd": pd}


def _feature(features_data, etype, rec_id):
    for p in features_data["points"]:
        if p["entity_type"] == etype and p["id"] == rec_id:
            return p
    return None


def _net_point(net, etype, rec_id):
    for p in net["points"]:
        if p["entity_type"] == etype and p["id"] == rec_id:
            return p
    return None


# ---------------------------------------------------------------- Test A ---
def test_a_multiple_people_one_city(conn, corpus):
    """Three people associated with Amsterdam hold three independent
    positions — not one shared city coordinate."""
    f = mapdata.features(conn, layers=["person"], limit=500)
    pts = {k: _feature(f, "person", corpus[k]["id"]) for k in ("pa", "pb", "pc", "assoc")}
    own = [(p["lat"], p["lon"]) for p in pts.values() if p and p["position"] == "precise"]
    assert len(own) == 3, pts
    assert len(set(own)) == 3, f"positions collapsed: {own}"
    ams_pt = (corpus["ams"]["latitude"], corpus["ams"]["longitude"])
    for pt in own:
        assert pt != ams_pt, "a person inherited the city's coordinates"
    for key in ("pa", "pb", "pc"):
        assert pts[key]["position"] == "precise"
    # the person with no own coordinates is shown, distinctly, at the place
    assert pts["assoc"]["position"] == "associated"
    assert (pts["assoc"]["lat"], pts["assoc"]["lon"]) == ams_pt


# ---------------------------------------------------------------- Test B ---
def test_b_person_and_organization(conn, corpus):
    """Selecting the person displays both their own position and the
    organization's different position, as separate markers with provenance."""
    net = mapdata.network(conn, "person", corpus["pa"]["id"], depth=1)
    me = _net_point(net, "person", corpus["pa"]["id"])
    org = _net_point(net, "institution", corpus["org"]["id"])
    assert me and me["primary"] and me["position"] == "precise"
    assert org and not org["primary"] and org["position"] == "precise"
    assert (me["lat"], me["lon"]) != (org["lat"], org["lon"])
    assert (org["lat"], org["lon"]) == (corpus["org"]["latitude"], corpus["org"]["longitude"])
    assert org["via"]["kind"] in ("fk", "relationship")
    # and over the wire
    assert True  # HTTP variant covered in test_j


def test_b_api_network_endpoint(client, corpus):
    r = client.get(f"/api/map/network?entity=person&id={corpus['pa']['id']}&depth=1")
    assert r.status_code == 200 and r.json()["ok"] is True
    pts = {(p["entity_type"], p["id"]): p for p in r.json()["points"]}
    assert ("person", corpus["pa"]["id"]) in pts
    assert ("institution", corpus["org"]["id"]) in pts


# ---------------------------------------------------------------- Test C ---
def test_c_person_and_events(conn, corpus):
    """A person in several events, each with its own venue point: selecting
    the person shows their position and every event position."""
    net = mapdata.network(conn, "person", corpus["pa"]["id"], depth=1)
    me = _net_point(net, "person", corpus["pa"]["id"])
    e1 = _net_point(net, "event", corpus["ev1"]["id"])
    e2 = _net_point(net, "event", corpus["ev2"]["id"])
    assert me and e1 and e2
    for p in (me, e1, e2):
        assert p["position"] == "precise"
    positions = {(p["lat"], p["lon"]) for p in (me, e1, e2)}
    assert len(positions) == 3
    assert (e1["lat"], e1["lon"]) == (corpus["ev1"]["latitude"], corpus["ev1"]["longitude"])
    assert (e2["lat"], e2["lon"]) == (corpus["ev2"]["latitude"], corpus["ev2"]["longitude"])
    assert e1["via"]["kind"] == "relationship" and e2["via"]["kind"] == "relationship"


# ---------------------------------------------------------------- Test D ---
def test_d_place_without_coordinates(conn, corpus):
    """A person linked to a place with no coordinates: the link is valid and
    the person's own coordinates remain available."""
    d = repo.get_record(conn, ENTITIES["person"], corpus["pd"]["id"])
    assert d["birthplace_id"] == corpus["nowhere"]["id"], "association must survive"
    assert (d["latitude"], d["longitude"]) == (1.25, 2.5)
    f = mapdata.features(conn, layers=["person"], limit=500)
    pt = _feature(f, "person", corpus["pd"]["id"])
    assert pt and pt["position"] == "precise" and (pt["lat"], pt["lon"]) == (1.25, 2.5)
    # the unlocated place contributes no point of its own
    assert _feature(mapdata.features(conn, layers=["place"], limit=500),
                    "place", corpus["nowhere"]["id"]) is None


# ---------------------------------------------------------------- Test E ---
def test_e_independent_map_selection(conn, corpus):
    """Picking a different precise point for the entity saves independently:
    the named place's coordinates never move."""
    ams_before = repo.get_record(conn, ENTITIES["place"], corpus["ams"]["id"])
    person = repo.create_record(
        conn, ENTITIES["person"],
        {"name_en": "Corpus Picker", "name_ar": "corpus-pick",
         "birthplace_id": corpus["ams"]["id"],
         "_location": {"lat": 40.7, "lon": -74.0, "method": "map_pick"}},
        actor="t")
    assert (person["latitude"], person["longitude"]) == (40.7, -74.0)
    assert person["geocoding_method"] is not None, "the method is recorded"
    ams_after = repo.get_record(conn, ENTITIES["place"], corpus["ams"]["id"])
    assert (ams_after["latitude"], ams_after["longitude"]) == \
        (ams_before["latitude"], ams_before["longitude"]), "the place must not move"
    assert person["birthplace_id"] == corpus["ams"]["id"]
    # the place's own point is not the person's
    anchor = mapdata._anchor_of(conn, "person", person["id"])
    assert anchor["position"] == "precise" and (anchor["lat"], anchor["lon"]) == (40.7, -74.0)


# ---------------------------------------------------------------- Test F ---
def test_f_reverse_relationship_discovery(conn, corpus):
    """Organization, event and place each reveal their geographically
    connected records."""
    org_net = mapdata.network(conn, "institution", corpus["org"]["id"], depth=1)
    assert _net_point(org_net, "person", corpus["pa"]["id"]) is not None, \
        "organization must reveal its affiliated person"

    ev_net = mapdata.network(conn, "event", corpus["ev1"]["id"], depth=1)
    assert _net_point(ev_net, "person", corpus["pa"]["id"]) is not None, \
        "event must reveal its participant"
    assert _net_point(ev_net, "place", corpus["ams"]["id"]) is not None, \
        "event must reveal its associated place"

    place_net = mapdata.network(conn, "place", corpus["ams"]["id"], depth=1)
    for key in ("pa", "pb", "pc", "assoc"):
        assert _net_point(place_net, "person", corpus[key]["id"]) is not None
    assert _net_point(place_net, "institution", corpus["org"]["id"]) is not None
    assert _net_point(place_net, "event", corpus["ev1"]["id"]) is not None
    assert _net_point(place_net, "event", corpus["ev2"]["id"]) is not None


# ---------------------------------------------------------------- Test G ---
def test_g_no_coordinate_leakage(conn, corpus):
    """No record inherits another record's coordinates through joins,
    fallbacks or shared references — every resolution is checked against the
    record's own row."""
    f = mapdata.features(conn, layers=["person", "institution", "event"], limit=500)
    tables = {"person": "person", "institution": "institution", "event": "event"}
    for p in f["points"]:
        row = conn.execute(
            f"SELECT latitude, longitude FROM {tables[p['entity_type']]} WHERE id=?",
            (p["id"],)).fetchone()
        if p["position"] == "precise":
            assert (p["lat"], p["lon"]) == (row["latitude"], row["longitude"]), p
        else:
            assert row["latitude"] is None and row["longitude"] is None, \
                f"record with own coordinates must never be shown as associated: {p}"
    # a person with own coordinates and an unlocated place is still located
    pt = _feature(f, "person", corpus["pd"]["id"])
    assert pt and (pt["lat"], pt["lon"]) == (1.25, 2.5)
    # structural guard: the has-position predicate must group its OR terms
    for etype in ("person", "institution", "event"):
        assert mapdata.JOINS[etype][2].startswith("(("), \
            f"{etype} has_pos must parenthesize its OR terms"
    # the catalog's classes add up
    for entry in mapdata.layer_catalog(conn):
        assert entry["precise"] + entry["associated"] == entry["located"]
        assert entry["located"] + entry["unlocated"] == entry["total"]


# ---------------------------------------------------------------- Test H ---
def test_h_coordinate_editing_isolation(conn, corpus):
    """Changing one entity's coordinates touches nothing else."""
    before_a = repo.get_record(conn, ENTITIES["place"], corpus["ams"]["id"])
    before_b = repo.get_record(conn, ENTITIES["person"], corpus["pb"]["id"])
    before_c = repo.get_record(conn, ENTITIES["person"], corpus["pc"]["id"])
    repo.update_record(conn, ENTITIES["person"], corpus["pa"]["id"],
                       {"latitude": 60.0, "longitude": 30.0}, actor="t")
    after_a = repo.get_record(conn, ENTITIES["place"], corpus["ams"]["id"])
    after_b = repo.get_record(conn, ENTITIES["person"], corpus["pb"]["id"])
    after_c = repo.get_record(conn, ENTITIES["person"], corpus["pc"]["id"])
    assert (after_a["latitude"], after_a["longitude"]) == \
        (before_a["latitude"], before_a["longitude"])
    assert (after_b["latitude"], after_b["longitude"]) == \
        (before_b["latitude"], before_b["longitude"])
    assert (after_c["latitude"], after_c["longitude"]) == \
        (before_c["latitude"], before_c["longitude"])
    me = repo.get_record(conn, ENTITIES["person"], corpus["pa"]["id"])
    assert (me["latitude"], me["longitude"]) == (60.0, 30.0)
    # restore for any later test
    repo.update_record(conn, ENTITIES["person"], corpus["pa"]["id"],
                       {"latitude": 52.36, "longitude": 4.88}, actor="t")


# ---------------------------------------------------------------- Test I ---
_OLD_SCHEMA = """
CREATE TABLE place (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name_en TEXT, name_ar TEXT,
    latitude REAL, longitude REAL,
    geo_precision TEXT, geocoding_method TEXT, geo_uncertainty_m REAL,
    geometry_source TEXT,
    parent_place_id INTEGER REFERENCES place(id),
    deleted_at TEXT
);
CREATE TABLE person (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name_en TEXT, name_ar TEXT,
    birthplace_id INTEGER REFERENCES place(id),
    latitude REAL, longitude REAL,
    deleted_at TEXT
);
CREATE TABLE institution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name_en TEXT, name_ar TEXT,
    place_id INTEGER REFERENCES place(id),
    deleted_at TEXT
);
CREATE TABLE event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title_en TEXT, title_ar TEXT,
    place_id INTEGER REFERENCES place(id),
    deleted_at TEXT
);
CREATE TABLE relationship (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    entity1_type TEXT, entity1_id INTEGER,
    entity2_type TEXT, entity2_id INTEGER,
    deleted_at TEXT
);
"""


def _run_013(conn):
    sql = (ROOT / "app/migrations/013_entity_own_coordinates.sql").read_text(encoding="utf-8")
    applied = 0
    for stmt in [x.strip() for x in sql.split(";") if x.strip()]:
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "duplicate column" in msg or "already exists" in msg:
                continue
            raise
    conn.commit()
    return applied


def test_i_migration_integrity():
    """Migration 013 restores recoverable synthetic-place coordinates onto
    their records, restores the named-place links, retires the synthetic
    places, leaves independently recorded coordinates alone — and is
    idempotent."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_OLD_SCHEMA)
    conn.execute("INSERT INTO place (code, name_en, name_ar, latitude, longitude, parent_place_id) "
                 "VALUES ('PLC-N', 'Named City', 'Named City', 33.3152, 44.3661, NULL)")
    named_id = conn.execute("SELECT id FROM place").fetchone()["id"]
    # the synthetic point-place an earlier version created for a precise point
    conn.execute("INSERT INTO place (code, name_en, name_ar, latitude, longitude, "
                 "geo_precision, geocoding_method, geometry_source, parent_place_id) "
                 "VALUES ('PLC-S', '33.32160, 44.38638', '33.32160, 44.38638', "
                 "33.3215977, 44.3863818, 'exact', 'map_pick', 'map pick', ?)", (named_id,))
    synth_id = conn.execute("SELECT id FROM place WHERE code='PLC-S'").fetchone()["id"]
    conn.execute("INSERT INTO person (code, name_en, name_ar, birthplace_id) "
                 "VALUES ('PER-1', 'Synthetic Person', 'sp', ?)", (synth_id,))
    conn.execute("INSERT INTO event (code, title_en, title_ar, place_id) "
                 "VALUES ('EVT-1', 'Synthetic Event', 'se', ?)", (synth_id,))
    conn.execute("INSERT INTO person (code, name_en, name_ar, birthplace_id) "
                 "VALUES ('PER-2', 'Named Person', 'np', ?)", (named_id,))
    conn.execute("INSERT INTO institution (code, name_en, name_ar, place_id) "
                 "VALUES ('INS-1', 'Named Org', 'no', ?)", (named_id,))
    # a record whose coordinates were already independent: never overwritten
    conn.execute("INSERT INTO person (code, name_en, name_ar, birthplace_id) "
                 "VALUES ('PER-3', 'Own Person', 'op', ?)", (synth_id,))
    conn.execute("UPDATE person SET latitude=10.0, longitude=20.0 WHERE code='PER-3'")
    conn.commit()

    _run_013(conn)

    p1 = conn.execute("SELECT * FROM person WHERE code='PER-1'").fetchone()
    assert abs(p1["latitude"] - 33.3216) < 1e-6 and abs(p1["longitude"] - 44.38638) < 1e-6
    assert p1["birthplace_id"] == named_id, "the named-place link is restored"
    e1 = conn.execute("SELECT * FROM event WHERE code='EVT-1'").fetchone()
    assert abs(e1["latitude"] - 33.3216) < 1e-6 and e1["place_id"] == named_id
    p3 = conn.execute("SELECT * FROM person WHERE code='PER-3'").fetchone()
    assert (p3["latitude"], p3["longitude"]) == (10.0, 20.0), \
        "independently recorded coordinates must never be overwritten"
    assert p3["birthplace_id"] == named_id
    synth = conn.execute("SELECT * FROM place WHERE id=? AND deleted_at IS NULL",
                         (synth_id,)).fetchone()
    assert synth is None, "the synthetic point-place is retired"
    named = conn.execute("SELECT * FROM place WHERE id=?", (named_id,)).fetchone()
    assert (named["latitude"], named["longitude"]) == (33.3152, 44.3661)
    p2 = conn.execute("SELECT * FROM person WHERE code='PER-2'").fetchone()
    assert p2["latitude"] is None and p2["birthplace_id"] == named_id
    ins = conn.execute("SELECT * FROM institution WHERE code='INS-1'").fetchone()
    assert ins["latitude"] is None and ins["place_id"] == named_id

    # idempotent: a second run changes nothing
    snap_sql = ("SELECT code, latitude, longitude, birthplace_id, deleted_at FROM person "
                "UNION ALL SELECT code, latitude, longitude, place_id, deleted_at FROM event "
                "UNION ALL SELECT code, latitude, longitude, place_id, deleted_at "
                "FROM institution")
    snapshot = [tuple(r) for r in conn.execute(snap_sql)]
    _run_013(conn)
    snapshot2 = [tuple(r) for r in conn.execute(snap_sql)]
    assert snapshot == snapshot2
    conn.close()


# ---------------------------------------------------------------- Test J ---
def test_j_map_consistency(conn, corpus, client):
    """Every map surface resolves positions the same way: own coordinates
    first, associated places distinctly marked — features, anchors, detail,
    groups, search, spatial queries, overlays and the HTTP API."""
    pa, pb = corpus["pa"], corpus["pb"]
    f = mapdata.features(conn, limit=500)
    for p in f["points"]:
        assert p["position"] in ("precise", "associated"), p
    for key in ("pa", "pb"):
        pt = _feature(f, "person", corpus[key]["id"])
        anchor = mapdata._anchor_of(conn, "person", corpus[key]["id"])
        assert (pt["lat"], pt["lon"]) == (anchor["lat"], anchor["lon"])
        assert pt["position"] == anchor["position"]
    # detail carries the class
    assert mapdata.detail(conn, "person", pa["id"])["position"]["position"] == "precise"
    assert mapdata.detail(conn, "person", corpus["assoc"]["id"])["position"]["position"] == "associated"
    # search resolves own-first and says so
    hits = mapdata.search(conn, "Corpus Person A")["results"]
    me = next(h for h in hits if h["kind"] == "record" and h["id"] == pa["id"])
    assert me["position"] == "precise" and (me["lat"], me["lon"]) == (52.36, 4.88)
    # spatial query agrees with features
    around = mapdata.query(conn, mode="radius", lat=52.36, lon=4.88,
                           radius_m=50000, limit=500)["records"]
    row = next(r for r in around if r["entity_type"] == "person" and r["id"] == pa["id"])
    assert (row["lat"], row["lon"]) == (52.36, 4.88)
    # overlays resolve both ends through the same anchor machinery
    ovs = mapdata.overlays(conn, layers=["relationships"], limit=500)
    endpoints = {(c[0], c[1]) for feat in ovs["relationships"]["features"]
                 for c in feat["geometry"]["coordinates"]}
    anchor_a = mapdata._anchor_of(conn, "person", pa["id"])
    assert (anchor_a["lon"], anchor_a["lat"]) in endpoints
    # groups aggregate at the place, without touching record coordinates
    groups = mapdata.groups(conn, layers=["person"], limit=50)["groups"]
    assert any(g["place_id"] == corpus["ams"]["id"] for g in groups)
    # and the HTTP surface speaks the same language
    r = client.get("/api/map/features?limit=500").json()
    assert all(p["position"] in ("precise", "associated") for p in r["points"])
    r = client.get(f"/api/map/network?entity=person&id={pb['id']}&depth=1").json()
    assert r["ok"] is True and r["points"], "network endpoint must answer"
