"""Structure deck — military module sources (self-contained module).

Proves the advanced, module-specific viewing feature: the structure deck's
source registry now carries the military modules beside the registry
dimension chains — single-module hierarchies (units, regions) and
cross-module compositions (regions×units, units×operations) — plus the
categorical order-of-battle chain.  Every count is a real database count,
the free-code vocabularies group by their own values, and the tree view's
primary-filter bar reads the same fields the rows carry.

Run:  pytest -q tests/test_structures_modules.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.military import dbm

ROOT = Path(__file__).resolve().parents[1]


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


def _post(client, path, payload):
    r = client.post(path, json=payload,
                    headers={"X-Military-Role": "admin"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["record"]["id"]


def _unit(client, name, **kw):
    payload = {"name": name, "direct_personnel": 10}
    payload.update(kw)
    return _post(client, "/api/military/units", payload)


def _region(client, name, **kw):
    return _post(client, "/api/military/regions", {"name": name, **kw})


# --------------------------------------------------------------------------- #
# the source registry
# --------------------------------------------------------------------------- #
def test_module_sources_listed_with_family_and_levels(client):
    r = client.get("/api/structures")
    assert r.status_code == 200
    sources = r.json()["sources"]
    by_id = {s["id"]: s for s in sources}

    for sid in ("units", "regions", "regions-units", "units-ops", "forces"):
        assert sid in by_id, f"module source {sid} missing"
        assert by_id[sid]["family"] == "modules"

    assert by_id["units"]["kind"] == "hierarchy"
    assert by_id["regions"]["kind"] == "hierarchy"
    assert by_id["regions-units"]["kind"] == "composite"
    assert by_id["units-ops"]["kind"] == "composite"
    assert by_id["forces"]["kind"] == "chain"

    # structural sources declare their levels, bilingual, {en, ar} dicts
    levels = by_id["units-ops"]["chain"]
    assert [lv["en"] for lv in levels] == ["Unit", "Deployment", "Mission", "Training"]
    assert all(set(lv) == {"en", "ar"} and lv["ar"] for lv in levels)

    # the registry chains keep their translated dimension labels
    assert by_id["people"]["family"] == "registry"
    first = by_id["people"]["chain"][0]
    assert isinstance(first, dict) and first.get("en") and first.get("ar")


# --------------------------------------------------------------------------- #
# single-module hierarchy: units
# --------------------------------------------------------------------------- #
def test_units_hierarchy_nests_and_counts_exactly(client):
    u1 = _unit(client, "Alpha Brigade", echelon="Brigade", status="Active")
    u2 = _unit(client, "Bravo Battalion", parent_id=u1, echelon="Battalion",
               status="Active")
    _unit(client, "Charlie Company", parent_id=u1, echelon="Company",
          status="Reserve")
    u4 = _unit(client, "Delta Platoon", parent_id=u2, echelon="Platoon",
               status="Active")

    r = client.get("/api/structures/units")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["total"] == 4

    top = {c["label_en"]: c for c in d["root"]["children"]}
    assert set(top) == {"Alpha Brigade"}
    alpha = top["Alpha Brigade"]
    assert alpha["value"] == 4  # self + subtree
    assert alpha["meta"]["record"] is True and alpha["meta"]["entity"] == "unit"

    kids = {c["label_en"]: c for c in alpha["children"]}
    assert kids["Bravo Battalion"]["value"] == 2      # self + Delta
    assert kids["Charlie Company"]["value"] == 1
    grand = {c["label_en"]: c for c in kids["Bravo Battalion"]["children"]}
    assert set(grand) == {"Delta Platoon"}
    assert grand["Delta Platoon"]["meta"]["record_id"] == u4


def test_units_hierarchy_truncates_by_depth_but_keeps_values(client):
    u1 = _unit(client, "Root Unit")
    u2 = _unit(client, "Child Unit", parent_id=u1)
    _unit(client, "Grandchild Unit", parent_id=u2)

    d = client.get("/api/structures/units", params={"depth": 1}).json()
    top = d["root"]["children"]
    assert len(top) == 1
    assert top[0]["label_en"] == "Root Unit"
    assert top[0]["value"] == 3          # the count below survives the cut
    assert not top[0].get("children")    # depth 1 stops here


def test_units_hierarchy_folds_wide_levels_exactly(client):
    parent = _unit(client, "Wide Brigade")
    for i in range(12):
        _unit(client, f"Battalion {i}", parent_id=parent)
    d = client.get("/api/structures/units", params={"max_children": 5}).json()
    node = d["root"]["children"][0]
    kids = node["children"]
    folded = [c for c in kids if c.get("meta", {}).get("synthetic")]
    real = [c for c in kids if not c.get("meta", {}).get("synthetic")]
    assert len(real) == 5 and len(folded) == 1
    assert folded[0]["meta"]["count"] == 7
    assert sum(c["value"] for c in real) + folded[0]["value"] == 12


# --------------------------------------------------------------------------- #
# single-module hierarchy: regions
# --------------------------------------------------------------------------- #
def test_regions_hierarchy(client):
    r1 = _region(client, "Theater North", region_type="Theater")
    _region(client, "Zone One", parent_id=r1, region_type="Zone")
    d = client.get("/api/structures/regions").json()
    assert d["total"] == 2
    top = {c["label_en"]: c for c in d["root"]["children"]}
    assert top["Theater North"]["value"] == 2
    assert top["Theater North"]["children"][0]["label_en"] == "Zone One"


# --------------------------------------------------------------------------- #
# cross-module compositions
# --------------------------------------------------------------------------- #
def test_regions_units_cross_module_nesting(client):
    r1 = _region(client, "Theater North", region_type="Theater")
    r2 = _region(client, "Zone One", parent_id=r1, region_type="Zone")
    u1 = _unit(client, "Garrison Brigade", region_id=r2, echelon="Brigade")
    _unit(client, "Garrison Battalion", parent_id=u1, region_id=r2,
          echelon="Battalion")
    _unit(client, "Wandering Unit")  # no region — not in this composition

    d = client.get("/api/structures/regions-units").json()
    assert d["total"] == 4  # 2 regions + 2 linked units

    def find(node, label):
        if node.get("label_en") == label:
            return node
        for c in node.get("children", []):
            hit = find(c, label)
            if hit:
                return hit
        return None

    root = d["root"]
    zone = find(root, "Zone One")
    assert zone is not None
    names = {c["label_en"] for c in zone["children"]}
    assert "Garrison Brigade" in names
    brigade = find(zone, "Garrison Brigade")
    assert brigade is not None
    assert brigade["children"][0]["label_en"] == "Garrison Battalion"
    assert find(root, "Wandering Unit") is None


def test_units_ops_composite(client):
    u1 = _unit(client, "Ops Brigade", echelon="Brigade")
    dep = _post(client, "/api/military/deployments",
                {"name": "Shield Drill", "unit_id": u1,
                 "start_date": "2026-01-01", "end_date": "2026-02-01",
                 "status": "Planned"})
    _post(client, "/api/military/missions",
          {"name": "Watch Post", "unit_id": u1, "deployment_id": dep,
           "mission_type": "Reconnaissance", "start_date": "2026-01-02",
           "status": "Planned"})

    d = client.get("/api/structures/units-ops").json()
    assert d["total"] == 3  # 1 unit + 1 deployment + 1 mission

    def find(node, label):
        if node.get("label_en") == label:
            return node
        for c in node.get("children", []):
            hit = find(c, label)
            if hit:
                return hit
        return None

    brigade = find(d["root"], "Ops Brigade")
    assert brigade is not None
    assert brigade["value"] == 3
    names = {c["label_en"] for c in brigade["children"]}
    assert names == {"Shield Drill", "Watch Post"}


# --------------------------------------------------------------------------- #
# the categorical chain over free-code vocabularies
# --------------------------------------------------------------------------- #
def test_forces_chain_groups_free_codes_not_not_recorded(client):
    _unit(client, "A Bde", echelon="Brigade", status="Active")
    _unit(client, "B Bde", echelon="Brigade", status="Standby")
    _unit(client, "C Co", echelon="Company", status="Active")

    d = client.get("/api/structures/forces").json()
    assert d["total"] == 3
    top = {c["label_en"]: c["value"] for c in d["root"]["children"]}
    # the free-code vocabulary groups by its own values — nothing is dumped
    # into "not recorded", which is the bug this source guards against
    assert top == {"Brigade": 2, "Company": 1}

    a = next(c for c in d["root"]["children"] if c["label_en"] == "Brigade")
    statuses = {c["label_en"]: c["value"] for c in a["children"]}
    assert statuses == {"Active": 1, "Standby": 1}


def test_forces_chain_with_leaves_lists_units(client):
    u1 = _unit(client, "Leaf Unit", echelon="Squadron", status="Active")
    d = client.get("/api/structures/forces", params={"leaves": 1}).json()
    records = []

    def walk(n):
        for c in n.get("children", []):
            (records.append(c) if c.get("meta", {}).get("record") else walk(c))
    walk(d["root"])
    assert any(r.get("meta", {}).get("record_id") == u1 for r in records)


# --------------------------------------------------------------------------- #
# the tree view's primary-filter data contract
# --------------------------------------------------------------------------- #
def test_tree_rows_carry_the_primary_filter_fields(client):
    r1 = _region(client, "Filter Region", region_type="Zone")
    u1 = _unit(client, "Filter Unit", echelon="Brigade", status="Reserve",
               role="Line Infantry", region_id=r1)

    d = client.get("/api/military/units/tree").json()
    row = None
    for n in d["tree"]:
        if n["id"] == u1:
            row = n
    assert row is not None
    for key in ("echelon", "status", "role", "region_id", "code", "docname"):
        assert key in row, f"tree row missing {key}"

    d2 = client.get("/api/military/regions/tree").json()
    rrow = next(n for n in d2["tree"] if n["id"] == r1)
    for key in ("region_type", "country", "docname"):
        assert key in rrow, f"region tree row missing {key}"


# --------------------------------------------------------------------------- #
# deck + tree wiring, and locale parity
# --------------------------------------------------------------------------- #
def test_deck_groups_sources_and_reads_the_deep_link():
    js = (ROOT / "app/static/js/views/structures.js").read_text(encoding="utf-8")
    assert "optgroup" in js
    assert "viz.groupRegistry" in js
    assert "viz.groupModules" in js
    assert "params.source" in js


def test_tree_filter_bar_wiring():
    js = (ROOT / "app/static/js/views/military.js").read_text(encoding="utf-8")
    assert "data-tree-sel" in js
    assert "mil.tree.showing" in js
    assert "mil.tree.all" in js
    assert "#/structures?source=units" in js


def test_locale_parity_with_the_new_keys():
    en = json.loads((ROOT / "app/static/js/locales/en.json").read_text(encoding="utf-8"))
    ar = json.loads((ROOT / "app/static/js/locales/ar.json").read_text(encoding="utf-8"))
    assert sorted(en) == sorted(ar)
    for key in ("mil.tree.all", "mil.tree.showing", "mil.nav.structure",
                "viz.groupRegistry", "viz.groupModules"):
        assert en[key] and ar[key], key
    # both files stay byte-exact sorted
    for data in (en, ar):
        assert list(data) == sorted(data)
