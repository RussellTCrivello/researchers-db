"""The unit's split view — details, relationships and the unit's OWN map.

Selecting a military unit splits the screen exactly like selecting a person:
one side carries the record, its relationships and a map. The hard
distinction — the map shows the unit's own location and never the leader's —
is enforced here at every layer: the org panel may name the commander as a
relationship, but the geography payload and the map model carry only
unit-owned coordinates.

The translation guard in this file is the standing rule made executable:
every text the interface shows exists in BOTH locales.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.military import dbm, seed, service

ROOT = Path(__file__).resolve().parent.parent
LIST_JS = (ROOT / "app/static/js/views/list.js").read_text(encoding="utf-8")
REC_JS = (ROOT / "app/static/js/views/record.js").read_text(encoding="utf-8")
EN = json.loads((ROOT / "app/static/js/locales/en.json").read_text(encoding="utf-8"))
AR = json.loads((ROOT / "app/static/js/locales/ar.json").read_text(encoding="utf-8"))

HDRS = {"X-Military-Role": "admin"}

MIL_ENTITIES = [
    "unit", "region", "division", "commander", "deployment", "mission",
    "training", "assignment", "holding", "armament", "classification", "note",
    "trait",
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


def _sample_unit_id(client):
    """The flagship sample unit (the brigade) and its record."""
    got = client.get("/api/military/units", params={"limit": 100}, headers=HDRS)
    rows = got.json().get("records") or got.json().get("rows") or []
    for r in rows:
        if "12th Territorial Brigade" in (r.get("name") or ""):
            return r["id"]
    raise AssertionError("sample brigade not found")


# --------------------------------------------------------------- server side
class TestUnitDetailPayload:
    """The shared detail reads names, not ids — and carries the org links."""

    def test_unit_detail_resolves_refs_and_org(self, client, tmp_db):
        with service.transaction() as conn:
            seed.load_sample(conn)
        uid = _sample_unit_id(client)
        rec = client.get(f"/api/unit/{uid}").json()

        # the registry convention: resolved reference names + label namespace
        refs = rec.get("_refs") or {}
        assert refs.get("commander_id"), f"commander_id unresolved: {refs}"
        assert "Vossen" in json.dumps(refs["commander_id"], ensure_ascii=False)
        assert "_labels" in rec

        # the relationships half: organisation links served with the record
        org = rec.get("org") or {}
        assert org["commander"] and "Vossen" in (org["commander"]["full_name"] or "")
        assert {u["name"] for u in org["subunits"]} >= {"1st Infantry Battalion"}
        assert len(org["deployments"]) >= 2
        assert len(org["missions"]) >= 2
        assert org["division"] and org["region"]
        # the brigade is a root: its chain is empty and it is nobody's subunit
        assert org["parent"] is None

    def test_org_names_the_commander_but_geo_never_carries_his_position(
            self, client, tmp_db):
        """The distinction, enforced: the leader appears as a relationship
        only; the geography payload never substitutes his coordinates."""
        with service.transaction() as conn:
            seed.load_sample(conn)
            # give the commander's linked person a distinctive position
            cmd = conn.execute(
                "SELECT id, person_id FROM commander WHERE person_id IS NOT NULL "
                "ORDER BY id LIMIT 1").fetchone()
            assert cmd and cmd["person_id"]
            conn.execute(
                "UPDATE person SET latitude=12.34567, longitude=76.54321 WHERE id=?",
                (cmd["person_id"],))
            conn.commit()
            uid = conn.execute(
                "SELECT id FROM military_unit WHERE commander_id=?",
                (cmd["id"],)).fetchone()["id"]

        org = client.get(f"/api/unit/{uid}").json().get("org") or {}
        assert org.get("commander"), "org must name the commander"

        geo = client.get(f"/api/military/units/{uid}/geo", headers=HDRS).json()
        blob = json.dumps(geo, ensure_ascii=False)
        assert "12.34567" not in blob and "76.54321" not in blob, \
            "the commander's personal coordinates leaked into the unit geo"
        assert geo["unit"]["own"] is True

    def test_sample_carries_fictional_coordinates(self, client, tmp_db):
        """The demo world can show the split map out of the box."""
        with service.transaction() as conn:
            seed.load_sample(conn)
            units = conn.execute(
                "SELECT COUNT(*) AS n FROM military_unit WHERE latitude IS NOT NULL"
            ).fetchone()["n"]
            deps = conn.execute(
                "SELECT COUNT(*) AS n FROM operational_deployment WHERE latitude IS NOT NULL"
            ).fetchone()["n"]
        assert units >= 6 and deps >= 4


# -------------------------------------------------------------- front-end pins
class TestSplitViewWiring:
    def test_list_inspector_gives_units_the_person_shape(self):
        # an explicit unit tab set — details, relationships, map — before the
        # person fallback, and an org-aware relationship count
        assert re.search(r"const sets = \{\s*unit:", LIST_JS), "no unit tab set"
        assert "orgCount(rec)" in LIST_JS
        assert "inspectUnitRelationsHtml" in LIST_JS
        assert "inspect.tab.relationships" in LIST_JS

    def test_map_model_reads_the_units_own_geo(self):
        # the unit's map model is built from /units/{id}/geo only
        assert "/api/military/units/${rec.id}/geo" in LIST_JS
        model_block = LIST_JS[LIST_JS.index("async function mapModelFor"):]
        unit_block = model_block[:model_block.index("const net = await api.get")]
        assert 'entity === "unit"' in unit_block
        assert "/api/map/network" not in unit_block, \
            "the unit model must not consult the generic network (leader points)"
        assert "model.unitOwn = true" in LIST_JS

    def test_map_caption_states_the_distinction(self):
        assert "inspect.map.unitOwn" in LIST_JS
        assert "inspect.map.unitOwn" in EN and "inspect.map.unitOwn" in AR
        # the empty state carries the distinction too
        assert "inspect.unlocatedHint." in LIST_JS

    def test_person_record_carries_the_full_leadership_layer(self):
        for needle in ("cmdFan", "cmdVocabLabel", "CMD_LEVEL_RANK",
                       "/api/military/traits?commander_id=", "/leader-record",
                       "mil.lead.title", "mil.lead.recordTitle",
                       "mil.lead.basisNote", "mil.lead.noAssessments"):
            assert needle in REC_JS, needle


# ---------------------------------------------------------- translation guard
class TestTranslationCoverage:
    """Every text the interface shows exists in BOTH locales — the standing
    rule ('translate any text, regardless of where it appears') enforced."""

    def test_new_keys_exist_and_are_translated(self):
        new_keys = [
            "ui.primary", "form.groups.main", "form.groups.structure",
            "geo.layer.unit", "geo.layer.deployment",
            "inspect.anchor.unit", "inspect.anchor.deployment",
            "inspect.map.unitOwn",
            "mil.org.title", "mil.org.chain", "mil.org.commander",
            "mil.org.commanderNote", "mil.org.appointments", "mil.org.subunits",
            "mil.org.deployments", "mil.org.missions", "mil.org.parent",
            "mil.org.division", "mil.org.region", "mil.org.none",
        ]
        for k in new_keys:
            assert EN.get(k), k
            assert AR.get(k), k
            assert AR[k] != EN[k], f"untranslated: {k}"

    def test_unlocated_hints_cover_every_military_entity(self):
        for ent in MIL_ENTITIES:
            k = f"inspect.unlocatedHint.{ent}"
            assert EN.get(k), k
            assert AR.get(k), k
            assert AR[k] != EN[k], f"untranslated: {k}"

    def test_every_translated_literal_exists_in_both_locales(self):
        """No raw key may ever reach a user's eye: every t("…") literal in the
        interface scripts resolves in en.json AND ar.json."""
        pat = re.compile(r"""\b(?:A\.)?t\(\s*["']([a-zA-Z0-9_.]+)["']\s*[,)]""")
        missing = {}
        for f in sorted((ROOT / "app/static/js").rglob("*.js")):
            src = f.read_text(encoding="utf-8")
            for m in pat.finditer(src):
                key = m.group(1)
                if key.endswith("."):      # dynamic prefix — covered per suffix
                    continue
                if key not in EN or key not in AR:
                    missing.setdefault(key, set()).add(f.name)
        assert not missing, f"untranslated keys in use: {sorted(missing)}"

    def test_locale_files_stay_parity_and_sorted(self):
        assert set(EN) == set(AR)
        assert list(EN) == sorted(EN, key=lambda k: k.encode("utf-8"))
        assert list(AR) == sorted(AR, key=lambda k: k.encode("utf-8"))
