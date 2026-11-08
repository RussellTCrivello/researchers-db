"""Import fixtures (scripts/generate_import_fixtures.py) — generation and E2E import.

The fixtures are bulk test data: every entity file has 120 rows mixing complete,
partial and sparse records with genuinely empty cells, plus a handful of
deliberate error rows (missing required names, unresolvable references).
"""

from __future__ import annotations

import csv
import importlib.util
import io

import pytest
from openpyxl import load_workbook

from app.military.specs import _build_specs
from app.schemas import ENTITIES
from app.transfer import parse_tabular, process_rows, suggest_mapping

SPECS = {**ENTITIES, **_build_specs()}


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Throwaway seeded registry+military database, per test."""
    from app import db, seed
    db_path = tmp_path / "registry.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    conn = db.connect()
    try:
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        db.run_migrations(conn)          # military tables + emblem columns live here
        seed.seed_reference_data(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path

# dependency order — references resolve by name against earlier files
ORDER = ["place", "institution", "person", "region", "division", "commander",
         "trait", "classification", "armament", "unit", "deployment", "mission",
         "holding", "training", "assignment", "note", "event", "relationship",
         "source"]

_gen = None


def _generator():
    global _gen
    if _gen is None:
        spec = importlib.util.spec_from_file_location(
            "gen_fixtures", "scripts/generate_import_fixtures.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _gen = mod
    return _gen


@pytest.fixture(scope="module")
def fixtures_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("import-test-data")
    mod = _generator()
    import sys
    sys.argv = ["generate_import_fixtures.py", "--out", str(out)]
    mod.main()
    return out


def _entities():
    return list(SPECS)


def test_every_entity_has_csv_and_xlsx_with_100_plus_rows(fixtures_dir):
    for ent in _entities():
        for ext in ("csv", "xlsx"):
            p = fixtures_dir / f"{ent}.{ext}"
            assert p.exists(), f"missing {p}"
            cols, rows, fmt = parse_tabular(p.read_bytes(), p.name)
            assert fmt == ext
            assert len(cols) >= 4
            assert len(rows) >= 100, f"{p.name} has {len(rows)} rows"


def test_xlsx_files_have_genuinely_empty_cells(fixtures_dir):
    """'It is crucial that these files include incomplete data' — real blanks."""
    for ent in _entities():
        wb = load_workbook(fixtures_dir / f"{ent}.xlsx", read_only=True)
        ws = wb.worksheets[0]
        blanks = sum(1 for row in ws.iter_rows(min_row=2, values_only=True)
                     for v in row if v is None)
        assert blanks >= 50, f"{ent}.xlsx has only {blanks} empty cells"


def test_csv_files_have_empty_fields(fixtures_dir):
    for ent in _entities():
        text = (fixtures_dir / f"{ent}.csv").read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        empties = sum(1 for row in rows[1:] for v in row if v.strip() == "")
        assert empties >= 50, f"{ent}.csv has only {empties} empty fields"


def test_headers_map_through_the_import_mapper(fixtures_dir):
    """EN, AR, bilingual and raw-key headers all map (no silent drops)."""
    for ent in _entities():
        cols, rows, _ = parse_tabular((fixtures_dir / f"{ent}.csv").read_bytes(),
                                      f"{ent}.csv")
        mapping = suggest_mapping(SPECS[ent], cols)
        mapped = [c for c in cols if mapping.get(c)]
        assert len(mapped) >= max(4, len(cols) - 2), \
            f"{ent}: unmapped {[c for c in cols if not mapping.get(c)]}"


def test_e2e_import_chain_creates_records_and_reports_errors(fixtures_dir, tmp_db):
    from app import db
    conn = db.connect()          # registers year_of/norm custom functions
    imported = {}
    for ent in ORDER:
        p = fixtures_dir / f"{ent}.csv"
        if not p.exists():
            continue
        cols, rows, _ = parse_tabular(p.read_bytes(), p.name)
        mapping = suggest_mapping(SPECS[ent], cols)
        res = process_rows(conn, SPECS[ent], rows, mapping=mapping, mode="create",
                           actor="fixture-test", dry_run=False)
        imported[ent] = res
    # the bulk of every file lands in the database
    for ent in ("place", "person", "institution", "region", "division",
                "commander", "trait", "classification", "armament", "unit",
                "training"):
        assert imported[ent]["created"] >= 100, \
            f"{ent}: only {imported[ent]['created']} created — {imported[ent]['rows'][:1]}"
    # deliberate error rows surface as row-level errors, not silent drops
    for ent in ("commander", "trait", "unit", "training"):
        assert imported[ent]["failed"] >= 5, f"{ent}: expected error rows missing"
    conn.close()


def test_incomplete_rows_store_nulls_and_defaults(tmp_db):
    """Blank cells import as NULL / field defaults — the incomplete-data promise."""
    from app import db
    conn = db.connect()
    spec = SPECS["unit"]
    rows = [{"Unit Name": "Blank Fields Unit", "Code": "BFX-1",
             "Echelon": "", "Status": "", "Direct Personnel": ""}]
    mapping = {"Unit Name": "name", "Code": "code", "Echelon": "echelon",
               "Status": "status", "Direct Personnel": "direct_personnel"}
    res = process_rows(conn, spec, rows, mapping=mapping, mode="create",
                       actor="fixture-test", dry_run=False)
    assert res["created"] == 1, res
    rec = conn.execute("SELECT code, docname, echelon, status, direct_personnel "
                       "FROM military_unit WHERE code='BFX-1'").fetchone()
    assert rec["docname"]                    # system-maintained, auto-issued
    assert rec["echelon"] == "Brigade"       # spec default
    assert rec["status"] == "Active"         # spec default
    assert rec["direct_personnel"] == 0      # spec default
    conn.close()
