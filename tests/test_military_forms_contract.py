"""Military forms contract — the shared record form and the military service
must speak the same value grammar.

The unified list/record engine renders military entities from ``/api/meta`` and
submits through the generic ``/api/{entity}`` routes.  Two contracts were
mismatched and every save failed with 422 while the form looked fine:

* the shared date control emits the precision the researcher entered —
  ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``, optionally with ``THH:MM`` — and the
  service demanded a full ISO date;
* choice values arrive from dropdowns as canonical codes but a typed or
  imported value may differ only in case.

Run:  pytest -q tests/test_military_forms_contract.py
"""
from __future__ import annotations

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


def _create(client, path, payload):
    """POST like the shared form does (generic route, _-meta keys included)."""
    body = {"_reason": None, "_source_id": None, **payload}
    r = client.post(path, json=body, headers={"X-Military-Role": "admin"})
    assert r.status_code in (200, 201), r.text
    return r.json()["record"]


def _region_id(client):
    rec = _create(client, "/api/region", {"name": "Northern Command"})
    return rec["id"]


def test_precision_dates_match_the_shared_date_control(client):
    """Year / month / full / minute precision all save; the form emits these."""
    region = _region_id(client)
    for formation in ("1948", "1948-05", "1948-05-01", "1948-05-01T14:30"):
        rec = _create(client, "/api/division",
                      {"name": f"Div {formation}", "region_id": region,
                       "formation_date": formation})
        assert rec["formation_date"] == formation
        rec = _create(client, "/api/unit",
                      {"name": f"Unit {formation}", "formation_date": formation})
        assert rec["formation_date"] == formation


def test_bad_dates_still_rejected(client):
    region = _region_id(client)
    for bad in ("01/02/1948", "1948-13", "1948-02-30", "yesterday"):
        r = client.post("/api/division", json={"name": "X", "region_id": region,
                                               "formation_date": bad},
                        headers={"X-Military-Role": "admin"})
        assert r.status_code == 422, bad
        assert r.json()["detail"]["error"]["code"] == "invalid_date"


def test_choice_values_normalise_case(client):
    region = _region_id(client)
    rec = _create(client, "/api/division",
                  {"name": "Case Probe", "region_id": region,
                   "division_type": "mechanized"})
    assert rec["division_type"] == "Mechanized"      # stored canonical
    r = client.post("/api/division", json={"name": "X", "region_id": region,
                                           "division_type": "Bogus"},
                    headers={"X-Military-Role": "admin"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "invalid_choice"


def test_every_rendered_field_is_known_to_the_service(client):
    """No rendered, editable meta field may be unknown to the service.

    The field metadata (military/specs.py) and the validating field list
    (service.ENTITY_SPECS) are separate sources; a field rendered by one and
    missing from the other made every save fail with `unknown_field` even for
    null values (unit.current_deployment_id).  This contract is the guard.
    """
    from app.military import service as mil_service
    meta = client.get("/api/meta").json()
    fields = {e["key"]: meta["fields"][e["key"]] for e in meta["entities"]
              if e["key"] in mil_service.ENTITY_SPECS}
    assert set(fields) == set(mil_service.ENTITY_SPECS)
    for key, rows in fields.items():
        known = {f["name"] for f in mil_service.ENTITY_SPECS[key]["fields"]}
        rendered = {f["key"] for f in rows
                    if not f.get("read_only") and not f.get("system")}
        assert rendered <= known, (
            f"{key}: meta renders {sorted(rendered - known)} the service rejects")


def test_generic_form_payload_round_trip(client):
    """The exact shape the shared record form collects (form._collect)."""
    region = _region_id(client)
    rec = _create(client, "/api/unit", {
        "code": "BDE-7",
        "name": "7th Mechanized Brigade",
        "echelon": "Brigade",
        "parent_id": None,
        "classification_id": None,
        "role": "armored reserve",
        "status": "Active",
        "commander_id": None,
        "direct_personnel": 1200,
        "division_id": None,
        "region_id": region,
        "formation_date": "1976",
        "headquarters": "North Camp",
        "notes": None,
    })
    assert rec["name"] == "7th Mechanized Brigade"
    assert rec["direct_personnel"] == 1200
    assert rec["role"] == "armored reserve"          # free text passes through
