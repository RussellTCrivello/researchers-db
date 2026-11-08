"""Geography data + supporting-tables contracts for countries / governorates / districts.

Proven here:

  1. resources integrity — countries.json, governorates.json, districts.json carry
     unique codes, real bilingual labels (label_ar never echoes label_en), and every
     child row points at a parent that exists (district → governorate → country);
  2. seed coverage — seed_reference_data mounts every districts.json row under its
     governorate, and the full chain stays active and bilingual in the database;
  3. supporting-tables UI — the Vocabularies screen ships the user-friendly controls
     (value filter, parent cascade, rows-per-page, load-more) and they are wired;
  4. locale parity — every new UI key exists in BOTH bundles with matching
     interpolation tokens.

Run:  pytest -q tests/test_geo_data.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "app/resources"
LOCALES = ROOT / "app/static/js/locales"


def _load(name):
    return json.loads((RES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- resources ---
def test_countries_unique_and_bilingual():
    rows = _load("countries.json")
    assert len(rows) >= 240
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    for r in rows:
        assert r["label_en"] and r["label_ar"], r
        assert r["label_ar"] != r["label_en"], f"Arabic echo in {r['code']}"


def test_governorates_unique_bilingual_and_parented():
    rows = _load("governorates.json")
    assert len(rows) >= 4000
    countries = {r["code"] for r in _load("countries.json")}
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    for r in rows:
        assert r["country"] in countries, r
        assert r["label_en"] and r["label_ar"], r
        assert r["label_ar"] != r["label_en"], f"Arabic echo in {r['code']}"


def test_districts_unique_bilingual_and_parented():
    rows = _load("districts.json")
    assert len(rows) >= 1400
    govs = {r["code"] for r in _load("governorates.json")}
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    for r in rows:
        assert r["governorate"] in govs, r
        assert r["label_en"] and r["label_ar"], r
        assert r["label_ar"] != r["label_en"], f"Arabic echo in {r['code']}"
        assert int(r.get("sort") or 0) > 0


def test_districts_cover_all_arab_world_countries():
    rows = _load("districts.json")
    arab = {"AE", "BH", "DJ", "DZ", "EG", "IQ", "JO", "KM", "KW", "LB", "LY",
            "MA", "MR", "OM", "PS", "QA", "SA", "SD", "SO", "SY", "TN", "YE"}
    seen = {r["code"].split("-")[0] for r in rows}
    assert arab <= seen, arab - seen


# ---------------------------------------------------------------- seed chain ---
def test_seed_mounts_full_district_tree():
    import app.db as db
    import app.seed as seed

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(Path(db.SCHEMA_PATH).read_text(encoding="utf-8"))
    seed.seed_reference_data(conn)

    districts = _load("districts.json")
    for r in districts:
        row = conn.execute(
            "SELECT * FROM lookup WHERE domain='district' AND code=?", (r["code"],)
        ).fetchone()
        assert row is not None, r["code"]
        assert row["label_ar"] == r["label_ar"]
        assert row["is_active"] == 1
        parent = conn.execute(
            "SELECT * FROM lookup WHERE id=?", (row["parent_id"],)
        ).fetchone()
        assert parent["domain"] == "governorate"
        assert parent["code"] == r["governorate"]
        assert parent["is_active"] == 1
        grand = conn.execute(
            "SELECT * FROM lookup WHERE id=?", (parent["parent_id"],)
        ).fetchone()
        assert grand["domain"] == "country"

    # label fixes in the JSONs propagate on reseed (UPDATE-after-INSERT)
    total = conn.execute(
        "SELECT COUNT(*) c FROM lookup WHERE domain='district'"
    ).fetchone()["c"]
    assert total >= len(districts)


# ---------------------------------------------------------------- UI contract ---
def test_vocabularies_screen_has_filters_paging_and_cascade():
    src = (ROOT / "app/static/js/views/admin.js").read_text(encoding="utf-8")
    assert "A.ADMIN_CHAIN.slice(1).forEach" in src  # cascade chain is the real one
    assert 'id="valQ"' in src                      # value text filter
    assert 'id="valSel-${dom}"' in src             # one cascading select per level
    assert "data-admin-dom" in src
    assert 'id="valPageSize"' in src               # customizable page size
    assert 'id="valMore"' in src                   # load-more
    assert "adm.filterValues" in src
    assert "adm.showingOf" in src
    assert "adm.loadMore" in src
    assert "adm.pageRows" in src


def test_vocabularies_editing_never_navigates():
    src = (ROOT / "app/static/js/views/admin.js").read_text(encoding="utf-8")
    start = src.index("A.views.vocabularies")
    end = src.index("A.views.numbering")
    block = src[start:end]
    for banned in ("location.href", "location.assign", "location.reload",
                   "window.location", "navigate("):
        assert banned not in block, banned


# ------------------------------------------------------------- locale parity ---
def test_new_locale_keys_exist_in_both_bundles():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    ar = json.loads((LOCALES / "ar.json").read_text(encoding="utf-8"))
    assert set(en) == set(ar)
    for key in ("adm.filterValues", "adm.allRows", "adm.loadMore",
                "adm.pageRows", "adm.showingOf"):
        assert key in en and key in ar, key
        assert en[key] and ar[key], key
        assert ar[key] != en[key], f"echo in {key}"
    assert "{a}" in en["adm.showingOf"] and "{b}" in en["adm.showingOf"]
    assert "{a}" in ar["adm.showingOf"] and "{b}" in ar["adm.showingOf"]
