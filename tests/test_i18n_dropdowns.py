"""Dropdown translation verification — every dropdown speaks the interface language.

Three contracts, proven here:

  1. free-code vocabulary values (the military choice lists) carry a label in
     EVERY locale bundle — mil.value.<field>.<value> or mil.value.<value> — and
     the Arabic label is a real translation, not the English value echoed back;
  2. lookup vocabularies (registry + country) are fully bilingual: every row of
     every domain a select field can show has a non-empty label_en AND label_ar,
     and every such domain is served by /api/meta;
  3. every dropdown render site resolves labels through the shared helpers
     (A.optLabel / A.optChoices) or the locale bundles — no site may render a
     raw option value as its own label.

Run:  pytest -q tests/test_i18n_dropdowns.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.military import dbm, service
from app.schemas import ENTITIES

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "app/static/js/locales"
JS = ROOT / "app/static/js"


def _bundles():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    ar = json.loads((LOCALES / "ar.json").read_text(encoding="utf-8"))
    return en, ar


def _free_code_values():
    """(field_key, value) for every free-code choice option in the military specs."""
    for spec in service.ENTITY_SPECS.values():
        for f in spec["fields"]:
            if f.get("type") == "choice" and f.get("options"):
                for o in f["options"]:
                    yield f["name"], str(o)


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """A throwaway unified database, reference vocabularies included."""
    from app import db
    from app import seed as reg_seed
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


# --------------------------------------------------------------------------- #
# 1 · free-code vocabulary values
# --------------------------------------------------------------------------- #
class TestFreeCodeOptionTranslations:
    def test_every_option_value_is_translated_in_every_locale(self):
        en, ar = _bundles()
        seen = set()
        for field, value in _free_code_values():
            seen.add(value)
            for lang_name, bundle in (("en", en), ("ar", ar)):
                label = bundle.get(f"mil.value.{field}.{value}") \
                    or bundle.get(f"mil.value.{value}")
                assert label and label.strip(), \
                    f"{lang_name}: no label for {field}={value!r}"
        assert len(seen) >= 60, "the option inventory collapsed"

    def test_arabic_labels_are_translations_not_echoes(self):
        _en, ar = _bundles()
        echoed = []
        for _field, value in _free_code_values():
            label = ar.get(f"mil.value.{value}") or value
            if label.strip() == value:
                echoed.append(value)
        assert not echoed, f"Arabic label is the English value: {sorted(set(echoed))}"

    def test_locale_files_stay_sorted_with_full_parity(self):
        en, ar = _bundles()
        assert sorted(en) == sorted(ar)
        for bundle in (en, ar):
            assert list(bundle) == sorted(bundle), "locale file lost its sort order"


# --------------------------------------------------------------------------- #
# 2 · lookup vocabularies
# --------------------------------------------------------------------------- #
class TestLookupVocabularyTranslations:
    def _select_domains(self):
        domains = set()
        for spec in ENTITIES.values():
            for f in spec.fields:
                if f.type == "select" and f.domain:
                    domains.add(f.domain)
        for spec in service.ENTITY_SPECS.values():
            for f in spec["fields"]:
                if f.get("type") == "select" and f.get("domain"):
                    domains.add(f["domain"])
        return domains

    def test_every_select_domain_is_served_by_meta(self, client):
        meta = client.get("/api/meta").json()
        lookups = meta.get("lookups") or {}
        for domain in sorted(self._select_domains()):
            assert domain in lookups, f"meta does not serve lookup domain {domain!r}"

    def test_every_lookup_row_is_bilingual(self, client):
        meta = client.get("/api/meta").json()
        lookups = meta.get("lookups") or {}
        bad = []
        for domain, rows in lookups.items():
            for r in rows:
                if not (r.get("label_en") or "").strip() \
                        or not (r.get("label_ar") or "").strip():
                    bad.append((domain, r.get("code")))
        assert not bad, f"lookup rows missing a bilingual label: {bad[:10]}"


# --------------------------------------------------------------------------- #
# 3 · system dropdowns + render wiring
# --------------------------------------------------------------------------- #
class TestSystemDropdownKeys:
    def test_enum_dropdown_keys_exist_in_both_locales(self):
        en, ar = _bundles()
        want = (
            [f"rep.value.metric.{v}" for v in ("count", "sum", "avg", "min", "max")] +
            [f"rep.value.chart.{v}" for v in ("bar", "pie", "table", "timeline")] +
            [f"exp.format.{v}" for v in ("xlsx", "csv", "tsv", "json")] +
            ["exp.lang.both"] +
            [f"fields.precision.{v}" for v in ("year", "month", "day", "minute")] +
            [f"mil.role.{v}" for v in ("admin", "staff", "viewer")]
        )
        for key in want:
            assert en.get(key) and ar.get(key), key


class TestRenderWiring:
    def _read(self, *parts):
        return (JS.joinpath(*parts)).read_text(encoding="utf-8")

    def test_core_exposes_the_option_label_helpers(self):
        core = self._read("core.js")
        assert "function optLabel" in core
        assert "function optChoices" in core
        assert "optLabel, optChoices" in core
        assert "mil.value." in core

    def test_forms_resolve_free_code_options_through_the_helpers(self):
        rec = self._read("views", "record.js")
        assert "A.optChoices(f.options, f.key)" in rec
        fields = self._read("components", "fields.js")
        assert "A.optChoices(field.options, field.key)" in fields
        forms = self._read("components", "forms.js")
        assert forms.count("A.optChoices(f.options, f.key)") == 2

    def test_tree_and_chips_translate_values(self):
        mil = self._read("views", "military.js")
        assert "A.optLabel(o, f.key)" in mil        # tree filter options
        assert "A.optLabel(v)" in mil               # status chips
        assert "A.optLabel(n.region_type" in mil    # region badge

    def test_system_dropdowns_ride_the_locale_bundles(self):
        rep = self._read("views", "reports.js")
        assert 't("rep.value.metric."' in rep
        assert 't("rep.value.chart."' in rep
        lst = self._read("views", "list.js")
        assert 't("exp.format."' in lst
        assert 't("exp.lang.both")' in lst
        adm = self._read("views", "admin.js")
        assert 't("exp.lang.both")' in adm

    def test_no_renderer_gives_the_arabic_label_a_raw_english_value(self):
        """The original bug: option mappings resolved label_en but echoed the
        raw value into label_ar.  A symmetric pair (label_en: x, label_ar: x)
        is the codebase's convention for pre-localised or user-entered text;
        an ASYMMETRIC one — a resolved label_en beside a bare-variable
        label_ar — is always the echo bug."""
        pair = re.compile(
            r"label_en:\s*(?P<en>.+?)\s*,\s*label_ar:\s*(?P<ar>[a-zA-Z_$][\w$]*)\s*[,}]")
        offenders = []
        for path in JS.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            for m in pair.finditer(text):
                en_expr = m.group("en").strip()
                if re.fullmatch(r"[a-zA-Z_$][\w$]*", en_expr) and en_expr == m.group("ar"):
                    continue  # symmetric passthrough — pre-localised text
                line = text[:m.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
        assert not offenders, f"asymmetric label_ar echo remains: {offenders}"
