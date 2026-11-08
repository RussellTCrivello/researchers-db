"""Unit dossier + emblem (military unit profile) — backend and source contracts.

The dossier is the workspace's flagship profile: emblem upload, identity,
structure, operations, logistics, training, the command roster and notes.
These tests pin the data contract (unit image fields, shared-record write
path) and the shipped front-end pieces (hero + tabs + /api/media wiring,
bilingual locale keys).
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


# ---------------------------------------------------------------- backend


def test_unit_image_fields_in_both_spec_sources(tmp_db):
    """Meta form fields and service validation carry the emblem columns."""
    meta = mil_specs._build_specs()["unit"]
    keys = {f.key: f for f in meta.fields}
    assert keys["image_url"].type == "url"
    assert keys["image_alt"].type == "text"
    names = {f["name"] for f in service.ENTITY_SPECS["unit"]["fields"]}
    assert {"image_url", "image_alt"} <= names


def test_emblem_round_trip_through_shared_record_api(client):
    """PUT /api/unit/{id} with the emblem fields — the dossier's upload path."""
    r = client.post("/api/unit", json={"name": "Emblem Probe Brigade"},
                    headers={"X-Military-Role": "admin"})
    assert r.status_code == 200, r.text
    uid = r.json()["record"]["id"]

    r = client.put(f"/api/unit/{uid}",
                   json={"image_url": "/api/media/emblem.svg",
                         "image_alt": "Probe emblem"},
                   headers={"X-Military-Role": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["record"]["image_url"] == "/api/media/emblem.svg"

    rec = client.get(f"/api/unit/{uid}").json()
    rec = rec.get("record") or rec
    assert rec["image_url"] == "/api/media/emblem.svg"
    assert rec["image_alt"] == "Probe emblem"

    # clearing the emblem works like every other optional field
    r = client.put(f"/api/unit/{uid}", json={"image_url": None, "image_alt": None},
                   headers={"X-Military-Role": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["record"]["image_url"] in (None, "")


def test_media_endpoint_accepts_images_and_rejects_junk(client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    r = client.post("/api/media", files={"file": ("probe.png", png, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("/api/media/")
    r = client.post("/api/media",
                    files={"file": ("probe.exe", b"MZ...", "application/octet-stream")})
    assert r.status_code in (400, 415, 422)


# ------------------------------------------------------------ front-end


def test_dossier_hero_tabs_and_emblem_wiring_shipped():
    js = MIL_JS
    for needle in (
        'id="milPortrait"',          # hero emblem portrait
        'id="emblemFile"',           # emblem upload input
        "/api/media",                # shared media endpoint
        "X-Military-Role",           # role header on the emblem write
        "force-summary",             # hero stats rollup
        'key: "overview"',           # tab strip mirrors the person profile
        'key: "structure"',          # subordinate units
        'key: "operations"',         # deployments + missions
        'key: "logistics"',          # weaponry & holdings
        'key: "training"',           # training records
        'key: "command"',            # past + current commanders
        'key: "notes"',              # notes
        'key: "history"',            # audit
        "mil.doss.changeEmblem",
        "mil.doss.commanders",
    ):
        assert needle in js, f"dossier wiring missing: {needle}"


def test_dossier_locales_are_complete_bilingual_and_sorted():
    en = json.loads((ROOT / "app/static/js/locales/en.json").read_text(encoding="utf-8"))
    ar = json.loads((ROOT / "app/static/js/locales/ar.json").read_text(encoding="utf-8"))
    assert list(en) == sorted(en)
    assert list(ar) == sorted(ar)
    assert set(en) == set(ar)
    for key in ("mil.doss.changeEmblem", "mil.doss.colCommander", "mil.doss.colEnd",
                "mil.doss.colLocation", "mil.doss.colRole", "mil.doss.colType",
                "mil.doss.commanders", "mil.doss.current", "mil.doss.emblem",
                "mil.doss.logistics", "mil.doss.operations", "mil.doss.past",
                "mil.doss.structure", "mil.doss.weaponry"):
        assert en.get(key), f"missing EN key {key}"
        assert ar.get(key), f"missing AR key {key}"
