"""Leadership distinction — assessed qualities with a basis, derived record.

The most important thing about leaders is what sets them apart. These
qualities are JUDGMENTS, so the design keeps them honest: every assessment
row carries its basis (who assessed it, when, on what evidence), the
vocabulary is bilingual lookup data, and the command record beside them is
derived from real rows (database counts over the commander's appointments) —
never estimated, never generated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.military import dbm, naming, seed, service, vocab
from app.military import specs as mil_specs

ROOT = Path(__file__).resolve().parent.parent
MIL_JS = (ROOT / "app/static/js/views/military.js").read_text(encoding="utf-8")

HDRS = {"X-Military-Role": "admin"}

NEW_KEYS = [
    "mil.lead.addAssessment", "mil.lead.appointments", "mil.lead.basisNote",
    "mil.lead.deployments", "mil.lead.maxEchelon", "mil.lead.noAssessments",
    "mil.lead.personnel", "mil.lead.recordTitle", "mil.lead.service",
    "mil.lead.title", "mil.lead.unitsCommanded",
]


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
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


# ---------------------------------------------------------------- backend


def test_leadership_vocab_seeded_bilingual(tmp_db):
    dbm.ensure()
    from app import db
    conn = db.connect()
    try:
        seed.ensure_leadership_vocab(conn)   # idempotent second pass
        conn.commit()
        for domain in (vocab.LEADERSHIP_QUALITY_DOMAIN, vocab.LEADERSHIP_LEVEL_DOMAIN):
            dom = conn.execute(
                "SELECT * FROM lookup_domain WHERE domain=?", (domain,)).fetchone()
            assert dom and dom["label_en"] and dom["label_ar"], domain
            rows = conn.execute(
                "SELECT * FROM lookup WHERE domain=? ORDER BY sort_order",
                (domain,)).fetchall()
            assert rows, domain
            for r in rows:
                assert r["code"] and r["label_en"] and r["label_ar"], dict(r)
        quals = conn.execute(
            "SELECT COUNT(*) AS n FROM lookup WHERE domain=?",
            (vocab.LEADERSHIP_QUALITY_DOMAIN,)).fetchone()["n"]
        assert quals == len(vocab.LEADERSHIP_QUALITIES)
        levels = conn.execute(
            "SELECT code, color FROM lookup WHERE domain=? ORDER BY sort_order",
            (vocab.LEADERSHIP_LEVEL_DOMAIN,)).fetchall()
        assert [r["code"] for r in levels] == [c for c, _, _, _ in vocab.LEADERSHIP_LEVELS]
        assert all(r["color"] for r in levels)   # level chips carry colour
    finally:
        conn.close()


def test_trait_in_all_layers():
    assert "trait" in mil_specs._build_specs()
    names = {f["name"] for f in service.ENTITY_SPECS["trait"]["fields"]}
    assert {"commander_id", "quality", "level", "assessed_by",
            "assessed_at", "evidence_note", "source"} <= names
    series = {s[0] for s in naming.SERIES_CATALOG}
    assert "trait" in series
    assert "trait" in vocab.ENTITY_TYPES


def test_assessment_needs_its_basis(client):
    cmd = _rec(client.post("/api/commander", json={"full_name": "Basis Commander"},
                           headers=HDRS))
    bare = client.post("/api/trait", json={
        "commander_id": cmd["id"], "quality": "Decisiveness",
        "level": "Exceptional"}, headers=HDRS)
    assert bare.status_code == 422
    assert _err(bare).get("code") == "basis_required"

    ok = client.post("/api/trait", json={
        "commander_id": cmd["id"], "quality": "Decisiveness",
        "level": "Exceptional", "assessed_by": "Board of Officers",
        "assessed_at": "2026-01-15",
        "evidence_note": "Held the line at the ridge under sustained pressure."}, headers=HDRS)
    assert ok.status_code in (200, 201)
    rec = _rec(ok)
    assert rec["docname"].startswith("MIL-QUAL-")
    got = _rec(client.get(f"/api/trait/{rec['id']}"))
    assert got["quality"] == "Decisiveness"
    assert got["assessed_by"] == "Board of Officers"

    # a judgment cannot be dated in the future
    future = client.post("/api/trait", json={
        "commander_id": cmd["id"], "quality": "Initiative",
        "assessed_by": "Someone", "assessed_at": "2027-01-01"}, headers=HDRS)
    assert future.status_code == 422
    assert _err(future).get("code") == "future_assessment"

    # unknown vocabulary codes are refused, not stored
    bad = client.post("/api/trait", json={
        "commander_id": cmd["id"], "quality": "Telepathy",
        "assessed_by": "Someone"}, headers=HDRS)
    assert bad.status_code == 422

    # the dossier's rel tab lists by commander
    listed = client.get(f"/api/military/traits?commander_id={cmd['id']}")
    assert listed.status_code == 200
    assert any(r["id"] == rec["id"] for r in listed.json()["records"])


def test_leader_record_is_derived_not_estimated(client):
    cmd = _rec(client.post("/api/commander", json={
        "full_name": "Record Commander", "commission_date": "2006-06-01"},
        headers=HDRS))
    unit = _rec(client.post("/api/unit", json={
        "name": "Led Brigade", "direct_personnel": 40, "echelon": "Brigade"},
        headers=HDRS))
    child = _rec(client.post("/api/unit", json={
        "name": "Led Battalion", "parent_id": unit["id"],
        "direct_personnel": 25, "echelon": "Battalion"}, headers=HDRS))
    assert child["parent_id"] == unit["id"]
    asg = client.post("/api/assignment", json={
        "unit_id": unit["id"], "commander_id": cmd["id"],
        "role": "Commanding Officer", "assigned_date": "2020-01-01",
        "is_current": True}, headers=HDRS)
    assert asg.status_code in (200, 201)
    client.post("/api/deployment", json={
        "name": "Led Deployment", "unit_id": unit["id"],
        "start_date": "2021-01-01"}, headers=HDRS)

    got = client.get(f"/api/military/commanders/{cmd['id']}/leader-record")
    assert got.status_code == 200
    d = got.json()
    assert d["appointments"] == 1
    assert d["current_appointment"] is True
    assert d["units_commanded"] == 1
    assert d["max_echelon"] == "Brigade"
    assert d["personnel_under_command"] >= 65   # brigade + its battalion subtree
    assert d["deployments_covered"] == 1
    assert d["years_of_service"] == 2026 - 2006

    missing = client.get("/api/military/commanders/999999/leader-record")
    assert missing.status_code == 404


# ---------------------------------------------------------------- front-end


def test_leadership_wiring_shipped():
    for needle in ("leaderFan", "leaderSection", "mountLeaderRecord",
                   "mil.lead.title", "mil.lead.basisNote", "LEVEL_RANK",
                   'data-add="trait"', "/leader-record",
                   '["traits", "commander_id"]', 'trait: "rel:traits"',
                   "vocabLabel"):
        assert needle in MIL_JS, needle
    assert "basis_required" in (ROOT / "app/military/rules.py").read_text(encoding="utf-8")
    assert "leader_record" in (ROOT / "app/military/service.py").read_text(encoding="utf-8")
    assert 'MIL-QUAL-' in (ROOT / "app/military/naming.py").read_text(encoding="utf-8")


def test_locales_complete_and_sorted():
    en = json.loads((ROOT / "app/static/js/locales/en.json").read_text(encoding="utf-8"))
    ar = json.loads((ROOT / "app/static/js/locales/ar.json").read_text(encoding="utf-8"))
    assert set(en) == set(ar)
    assert list(en) == sorted(en, key=lambda k: k.encode("utf-8"))
    assert list(ar) == sorted(ar, key=lambda k: k.encode("utf-8"))
    for k in NEW_KEYS:
        assert en.get(k), k
        assert ar.get(k), k
