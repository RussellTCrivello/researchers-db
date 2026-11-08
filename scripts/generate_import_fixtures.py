"""Generate realistic import-test fixtures (CSV + XLSX) for every importable entity.

Run with the app's virtualenv:

    .venv/bin/python scripts/generate_import_fixtures.py [--out import-test-data]

The output directory (default ``import-test-data/``) is gitignored: it is bulk test
data, meant to be generated locally and imported into a scratch instance.

Design contract (matches ``app/transfer.py``):

* Headers per file are one of: English labels, Arabic labels, bilingual
  "English / العربية", or raw field keys — all four map through
  ``suggest_mapping``/``header_index``.
* Every file has >= 100 rows with a mix of complete, partial and sparse
  records; incomplete data means genuinely EMPTY cells (None in xlsx,
  empty strings in csv), which import as NULLs.
* Select fields carry values the importers accept: lookup codes/labels for
  registry entities (from a freshly seeded reference database) and the
  static option choices for military entities.
* Reference fields chain within a file (parent places/regions/units) and
  across files by name (import the files in the ``ORDER`` sequence of
  ``tests/test_import_fixtures.py``), plus a few deliberately unresolvable
  references so the error report can be tested.
* A handful of rows per file omit a required name — expected row errors.
* ``trait`` rows carry real ``leadership_quality`` / ``leadership_level``
  vocabulary codes and every non-error row keeps at least one basis field
  (``assessed_by`` / ``evidence_note`` / ``source``) — the basis rule is
  satisfied by construction.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SIRAJ_DATA_DIR", str(ROOT / ".fixture-seed"))

RNG = random.Random(20261105)

OUT_ENT = "import-test-data"

# ---------------------------------------------------------------- value pools

FIRST_EN = ["Kareem", "Nadia", "Omar", "Layla", "Tariq", "Salma", "Yusuf", "Dina",
            "Hassan", "Mona", "Zaid", "Rania", "Faisal", "Hala", "Adel", "Sabra",
            "Marwan", "Iman", "Khaled", "Farah", "Sami", "Yara", "Bilal", "Lina",
            "Rami", "Sawsan", "Nabil", "Aida", "Jihad", "Maha"]
LAST_EN = ["Al-Mansour", "Haddad", "Baraka", "Said", "Khalil", "Nasser", "Rahim",
           "Aziz", "Farouk", "Habib", "Saleh", "Toufic", "Zoghbi", "Najjar",
           "Qasim", "Rashid", "Sabri", "Talhouni", "Yassin", "Zaydani",
           "D'Amato", "O'Neill", "García", "Müller", "Østergaard", "Šimić"]
FIRST_AR = ["كريم", "نادية", "عمر", "ليلى", "طارق", "سلمى", "يوسف", "دينا",
            "حسن", "منى", "زيد", "رانيا", "فيصل", "هالة", "عادل", "صبرة"]
LAST_AR = ["المنصور", "حداد", "بركة", "سعيد", "خليل", "نصر", "رحيم", "عزيز",
           "فاروق", "حبيب", "صالح", "توفيق", "زغبي", "نجار", "قاسم", "رشيد"]

REGION_BASE = ["Northern Command", "Eastern Reach", "Southern Shield", "Western Vale",
               "Central Plateau", "Coastal Guard", "Highland Belt", "Riverlands",
               "Desert March", "Frontier Corridor"]
DIV_BASE = ["Mechanized", "Armored", "Infantry", "Airborne", "Artillery",
            "Engineering", "Signals", "Logistics", "Medical", "Special Operations"]
BRIGADE_BASE = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th",
                "11th", "12th", "14th", "17th", "21st", "33rd", "42nd", "55th", "77th", "91st"]
CLASS_BASE = ["Regional Rapid Response", "Strategic Reserve", "Territorial Guard",
              "Peacekeeping Formation", "Training Command", "Joint Support Group",
              "Mountain Warfare Unit", "Riverine Force", "Cyber Defence Group",
              "Unmanned Systems Squadron"]
ARMAMENT_BASE = ["Main Battle Tank", "Armored Personnel Carrier", "Self-Propelled Howitzer",
                 "Multiple Rocket Launcher", "Towed Artillery Piece", "Air Defense Battery",
                 "Reconnaissance Vehicle", "Utility Truck", "Engineering Vehicle",
                 "Command Post Vehicle", "Unmanned Aerial Vehicle", "Radar Station"]
EXERCISE = ["IRON FALCON", "STEADY HORIZON", "NIGHT MARKET", "COPPER SHIELD",
            "SILVER LANCE", "DEEP CURRENT", "AMBER WATCH", "PALE SUNRISE"]
PLACE_BASE = ["Al-Jabal", "Wadi Rum", "Bir Anas", "Ras Al-Nur", "Ain Sabil",
              "Tell Al-Hawa", "Khan Al-Sharif", "Mina Al-Janub", "Qalat Suri",
              "Sahil Al-Barid"]
INSTITUTION_BASE = ["Institute for Strategic Studies", "Center for Historical Memory",
                    "Bureau of Cartographic Affairs", "Academy of Defense Analysis",
                    "Foundation for Civil Records", "Observatory of Trade Routes",
                    "Council for Linguistic Heritage", "Museum of Field History",
                    "Institute of Applied Toponymy", "Archive of Public Letters"]
EVENT_BASE = ["Border demarcation signed", "Ceasefire announced", "Corridor opened",
              "Dam inaugurated", "Summit convened", "Rail link completed",
              "Evacuation concluded", "Treaty ratified", "Flood response launched",
              "Heritage site inscribed"]
TOPIC_EN = ["logistics", "readiness", "rotation", "procurement", "training cadence",
            "border posture", "reserve activation", "signal discipline"]
NOTE_SNIPPETS = [
    "Inspected the eastern motor pool; three vehicles awaiting scheduled maintenance.",
    "Supply convoy arrived two days early; ammunition tally reconciled with the depot ledger.",
    "Trainees completed the navigation module with notable improvement over last cycle.",
    "Communications check with the sector net revealed intermittent relay faults at dusk.",
    "Quarterly readiness review recommends refresher drills for the reserve cadre.",
    "المناورة الجوية تمت وفق الخطة، مع ملاحظة تأخر الدعم اللوجستي ساعتين.",
    "تم تدقيق سجلات العتاد؛ ثلاث سجلات تحتاج تصحيح الكميات.",
    "تمرين الملاحة الليلي أظهر تحسناً ملحوظاً في الأداء الجماعي.",
    "Coordination with the civil authority proceeded without incident.",
    "Zażółć gęślą jaźń — diacritic-stress row: ą, č, ě, ł, ń, ř, š, ž, ø, æ.",
]
LONG_TEXT = (
    "Readiness narrative: the formation completed its quarterly training cycle across "
    "three phases — individual skills, collective drills, and a joint field exercise. "
    "Outcomes exceeded the previous cycle on mobility and communications, while sustainment "
    "timelines remain the binding constraint. التقييم الفصلي يشير إلى تحسن ملحوظ في الجاهزية. "
    "Follow-up actions are tracked in the operations ledger."
)


def en_name(i):
    return f"{FIRST_EN[i % len(FIRST_EN)]} {LAST_EN[(i * 7) % len(LAST_EN)]}"


def ar_name(i):
    return f"{FIRST_AR[i % len(FIRST_AR)]} {LAST_AR[(i * 5) % len(LAST_AR)]}"


def date_val(i, style):
    y = 1948 + (i * 3) % 76
    if style == "year":
        return str(y)
    if style == "month":
        return f"{y}-{1 + (i * 5) % 12:02d}"
    return f"{y}-{1 + (i * 5) % 12:02d}-{1 + (i * 11) % 28:02d}"


def long_val(i):
    return f"[{i:03d}] {LONG_TEXT}"


def notes_val(i):
    return f"[{i:03d}] {NOTE_SNIPPETS[i % len(NOTE_SNIPPETS)]}"


def url_val(i):
    return f"https://archive.example.org/{i % 7}/record-{i:04d}"


# ------------------------------------------------------ spec-driven field help

def load_specs():
    from app.military import service as mil_service
    from app.military.specs import _build_specs
    from app.schemas import ENTITIES

    reg = {k: ENTITIES[k] for k in ENTITIES}
    mil = mil_service.ENTITY_SPECS
    return reg, mil, _build_specs()


def field_info(spec, mil_flag):
    """Yield (key, type, required, ref_target, options_source, default) per field."""
    out = []
    if mil_flag:
        from app.military.specs import FIELD_AR
        for f in spec["fields"]:
            out.append({
                "key": f["name"], "type": f.get("type", "text"),
                "required": bool(f.get("required")), "ref": f.get("entity"),
                "choices": f.get("options") if f.get("type") == "choice" else None,
                "domain": f.get("domain"),      # lookup-backed selects (quality/level)
                "default": f.get("default"),
                "label_en": f.get("label") or label_en_of(f["name"]),
                "label_ar": FIELD_AR.get(f["name"], ""),
            })
    else:
        for f in spec.fields:
            if f.key == "tags" or f.key.startswith("_") or getattr(f, "system", False):
                continue
            out.append({
                "key": f.key, "type": f.type, "required": bool(f.required),
                "ref": getattr(f, "ref", None) if f.type in ("fk", "ref") else None,
                "choices": None,
                "domain": getattr(f, "domain", None),
                "default": getattr(f, "default", None),
                "label_en": getattr(f, "label_en", "") or label_en_of(f.key),
                "label_ar": getattr(f, "label_ar", "") or "",
            })
    return out


def harvest_lookup_codes():
    """Real lookup codes+labels from a freshly seeded reference DB."""
    from app import db as app_db
    app_db.init_db()
    from app.military import dbm
    dbm.ensure()                     # military migrations + vocab (leadership)
    db = sqlite3.connect(str(app_db.DB_PATH))
    rows = db.execute("SELECT domain, code, label_en FROM lookup").fetchall()
    db.close()
    by_dom: dict[str, list[str]] = {}
    for dom, code, lab in rows:
        by_dom.setdefault(dom, [])
        vals = by_dom[dom]
        if code not in vals:
            vals.append(code)
        if lab and lab not in vals:
            vals.append(lab)
    return by_dom


def mil_choice(source, entity):
    from app.military import options
    try:
        return [c["code"] for c in options.options(source, entity)["choices"]]
    except Exception:
        return []


# ------------------------------------------------------------- field value gen

FK_NAME_POOLS = {
    # ref entity -> label that exactly one row in the corresponding file carries
    "place": lambda i: f"{PLACE_BASE[i % len(PLACE_BASE)]} #{i}",
    "person": lambda i: en_name(i),
    "institution": lambda i: f"{INSTITUTION_BASE[i % len(INSTITUTION_BASE)]} #{i}",
    "region": lambda i: f"{REGION_BASE[i % len(REGION_BASE)]} {i}",
    "division": lambda i: f"{1 + i % 18} {DIV_BASE[i % len(DIV_BASE)]} Division {i}",
    "commander": lambda i: en_name(i + 3),
    "classification": lambda i: f"{CLASS_BASE[i % len(CLASS_BASE)]} {i}",
    "unit": lambda i: f"{BRIGADE_BASE[i % len(BRIGADE_BASE)]} {DIV_BASE[(i * 3) % len(DIV_BASE)]} Brigade {i}",
    "armament": lambda i: f"{ARMAMENT_BASE[i % len(ARMAMENT_BASE)]} Mk {1 + i % 6} #{i}",
    "deployment": lambda i: f"Deployment {chr(65 + i % 26)}-{100 + i % 80} #{i}",
    "mission": lambda i: f"Mission {EXERCISE[i % len(EXERCISE)]}-{1 + i % 20} #{i}",
    "training": lambda i: f"Exercise {EXERCISE[i % len(EXERCISE)]} #{i}",
}

MIL_ENTITIES = ("region", "division", "unit", "deployment", "mission", "holding",
                "training", "assignment", "note", "armament", "classification",
                "commander", "trait")


def value_for(key, ftype, i, ref, choices, domain, lookup, entity):
    """A value for one cell; '' means deliberately empty (a real blank)."""
    if domain == "record_status" or key == "record_status_id":
        return ""      # default status applies; 'verified'/'published' are workflow-blocked
    if ftype == "url":
        return url_val(i) if i % 5 else ""
    if ftype in ("int", "integer", "number"):
        return (i * 13) % 5000 if i % 7 else ""
    if ftype in ("float", "decimal", "real"):
        k = key.lower()
        if "lat" in k:
            return f"{(i * 3.7) % 60 - 20:.5f}" if i % 4 else ""
        if "lon" in k:
            return f"{(i * 7.3) % 180 - 85:.5f}" if i % 4 else ""
        return f"{(i * 13) % 5000 / 3:.3f}" if i % 5 else ""
    if ftype == "bool":
        return "yes" if i % 3 else "no"
    if ftype == "textarea":
        return long_val(i) if i % 4 == 0 else notes_val(i)
    if ftype == "date":
        if entity in MIL_ENTITIES:
            return date_val(i, "day")      # military service wants ISO YYYY-MM-DD
        return date_val(i, ["year", "month", "day"][i % 3])
    if ref:
        if i % 9 == 0:
            return ""                      # blank reference
        if i % 47 == 0:
            return f"UNRESOLVED REF {i}"   # deliberate error row
        pool = FK_NAME_POOLS.get(ref)
        return pool(i) if pool else ""     # unknown target: leave empty
    if choices:                            # military choice fields
        return choices[i % len(choices)] if i % 8 else ""
    if ftype == "select" and domain:       # registry lookup fields
        vals = lookup.get(domain, [])
        return vals[i % len(vals)] if vals and i % 6 else ("" if vals else "")
    if ftype == "datetime":
        return f"{date_val(i, 'day')} {8 + i % 10:02d}:00" if i % 3 else ""
    k = key.lower()
    if key in lookup or (k.endswith("country") and "country" in lookup):
        vals = lookup.get(key) or lookup["country"]
        return vals[i % len(vals)] if vals and i % 6 else ""
    if "lang" in k:
        return ["ar", "en", "fr", "tr", "ru"][i % 5] if i % 4 else ""
    if "name_ar" in k or k.endswith("_ar") or "arabic" in k:
        return ar_name(i) if i % 6 else ""
    if "note" in k or "summary" in k or "description" in k or "comment" in k:
        return notes_val(i) if i % 3 else ""
    if "email" in k:
        return f"user{i % 40}@example.org" if i % 5 else ""
    return f"{FIRST_EN[i % len(FIRST_EN)]} {LAST_EN[(i * 3) % len(LAST_EN)]} ({i})" if i % 4 else ""


def name_value(entity, key, i, rows_of_file):
    """Distinct in-file names; also the fk anchor other files reference."""
    if entity == "person":
        return ar_name(i) if key == "name_ar" else en_name(i)
    if entity in ("place", "institution"):
        return FK_NAME_POOLS[entity](i) if key in ("name_en", "name") else ar_name(i + 2)
    if entity == "commander":
        return en_name(i + 3) if key == "full_name" else ar_name(i + 3)
    if entity == "note":
        return notes_val(i)
    if entity in FK_NAME_POOLS:
        return FK_NAME_POOLS[entity](i)
    return f"{entity}-{i:03d}"


HEADER_STYLES = {"place": "ar", "commander": "ar", "unit": "both", "event": "key"}


def headers_for(fields, entity):
    style = HEADER_STYLES.get(entity, "en")
    out = []
    for f in fields:
        key = f["key"]
        en = f.get("label_en") or label_en_of(key)
        ar = f.get("label_ar") or label_ar_of(key)
        if style == "en":
            out.append(en)
        elif style == "ar":
            out.append(ar or en)
        elif style == "both":
            out.append(f"{en} / {ar or en}")
        else:
            out.append(key)
    return out


def label_en_of(key):
    return key.replace("_", " ").title().replace("Id", "ID").replace("Url", "URL")


def label_ar_of(key):
    from app.military.specs import FIELD_AR
    return FIELD_AR.get(key) or FIELD_AR.get(key.replace("_id", "")) or key


# ------------------------------------------------------------------ row build

N_ROWS = 120


def build_rows(entity, fields, mil_flag, lookup):
    rows = []
    for i in range(N_ROWS):
        r = {}
        for j, f in enumerate(fields):
            key, ftype, ref = f["key"], f["type"], f["ref"]
            # name-ish columns anchor the row and other files' references
            if key in ("name", "name_en", "name_ar", "full_name", "title",
                       "exercise_name", "holding_name", "docname", "note_text"):
                if key == "docname":
                    r[key] = docname_for(entity, i)
                    continue
                r[key] = name_value(entity, key, i, rows)
                continue
            if key == "code":
                # military business codes come from the file; registry codes auto-generate
                r[key] = docname_for(entity, i) if entity in MIL_ENTITIES else ""
                continue
            # profiles: complete (0-41), partial (42-87), sparse (88-119)
            args = (key, ftype, i, ref, f["choices"], f["domain"], lookup, entity)
            if i < 42:
                r[key] = value_for(*args)
            elif i < 88:
                r[key] = value_for(*args)
            else:
                r[key] = value_for(*args) if j % 5 == 0 else ""
        # intra-file chains: self-references point at another row in this file
        for f in fields:
            if f["ref"] == entity and f["key"] in r:
                r[f["key"]] = "" if (i == 0 or i % 5 == 0) else FK_NAME_POOLS[entity](i - 1)
        # coordinates come as a pair — never leave exactly one side blank
        for f in fields:
            if f["key"] in ("latitude", "longitude"):
                r[f["key"]] = value_for(f["key"], f["type"], i, f["ref"], f["choices"],
                                        f["domain"], lookup, entity)
        # required fields always carry a value (except the deliberate error rows)
        for f in fields:
            if f["required"] and f["key"] != "code" and not r.get(f["key"]) and i < 114:
                t = f["type"]
                if t in ("int", "integer", "number"):
                    r[f["key"]] = (i % 20) + 1
                elif t in ("float", "decimal", "real"):
                    r[f["key"]] = "1.5"
                elif t == "date":
                    r[f["key"]] = date_val(i, "day")
                elif f["choices"]:
                    r[f["key"]] = f["choices"][0]
                elif f["domain"] and lookup.get(f["domain"]):
                    r[f["key"]] = lookup[f["domain"]][0]
                elif f["ref"] and f["ref"] in FK_NAME_POOLS:
                    r[f["key"]] = FK_NAME_POOLS[f["ref"]](i)
                elif t == "url":
                    r[f["key"]] = url_val(i)
                else:
                    r[f["key"]] = f"Required {i}"
        # the trait basis rule: at least one of assessed_by / evidence_note /
        # source — guaranteed for every non-error row (the last six rows keep
        # their blanks: they are the deliberate error rows)
        if entity == "trait" and i < 114 and not any(
                r.get(k) for k in ("assessed_by", "evidence_note", "source")):
            r["assessed_by"] = f"Assessment Board {chr(65 + i % 6)}"
        # domain consistency: training duration matches its date range;
        # a completed deployment always carries an end date
        if entity == "training" and r.get("start_date"):
            dur = int(r.get("duration_days") or 1)
            try:
                st = dt.date.fromisoformat(str(r["start_date"])[:10])
                r["end_date"] = str(st + dt.timedelta(days=max(0, dur - 1)))
            except ValueError:
                r["end_date"] = r["start_date"]
        if entity == "deployment" and r.get("status") == "Completed" and not r.get("end_date"):
            r["end_date"] = r.get("start_date") or date_val(i, "day")
        if entity == "training" and "participant_count" in r:
            r["participant_count"] = 1 + i % 25
        if entity == "unit" and "direct_personnel" in r:
            r["direct_personnel"] = 50 + (i * 7) % 450

        # expected-error rows: missing the required name
        if i >= 114:
            for k in ("name", "name_en", "full_name", "exercise_name", "note_text"):
                if k in r:
                    r[k] = ""
        rows.append(r)
    return rows


def docname_for(entity, i):
    tag = {"region": "REG", "division": "DIV", "unit": "UNIT", "deployment": "DEP",
           "mission": "MIS", "holding": "HLD", "training": "TRN", "assignment": "ASG",
           "note": "NOTE", "armament": "ARM", "classification": "CLS",
           "commander": "CMD"}.get(entity, "REC")
    return f"{tag}-{i + 200:05d}"


# ------------------------------------------------------------------- writers

def write_csv(path, headers, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, lineterminator="\r\n")
        w.writerow(headers)
        for r in rows:
            w.writerow([r.get(f["key"], "") for f in fields])


def write_xlsx(path, headers, rows, fields):
    import datetime as _dt

    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        out = []
        for f in fields:
            v = r.get(f["key"], "")
            if v == "":
                out.append(None)                 # genuinely empty cell
            elif f["type"] == "date" and f["key"] not in ("docname",) and len(str(v)) == 10 and "-" in str(v):
                try:
                    out.append(_dt.datetime.strptime(str(v), "%Y-%m-%d"))
                except ValueError:
                    out.append(v)
            elif f["type"] in ("int", "integer", "number") and isinstance(v, int):
                out.append(v)
            else:
                out.append(v)
        ws.append(out)
    ws.freeze_panes = "A2"
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, min(34, len(h) + 4))
    wb.save(path)


README = """# Import test fixtures

Generated by `scripts/generate_import_fixtures.py` — regenerate with:

    .venv/bin/python scripts/generate_import_fixtures.py

Every entity has a CSV and an XLSX file with 120 rows: roughly 35% complete
records, 40% partial (some fields blank), 25% sparse (most fields blank).
Blank cells are **empty** — they import as NULL / fall back to field defaults.
Rows near the end of each file omit the required name on purpose: they produce
row-level errors in the import report (error-handling test data).
A few reference cells read `UNRESOLVED REF ...` — also expected errors.

## Suggested import order (references resolve by name against earlier files)

1. `place` (parents chain inside the file)
2. `institution`, `source` (person references them below)
3. `person` (birth places reference the place file; affiliations the institution file)
4. `event`, `relationship`
5. `region` (parents chain inside the file)
6. `division` (references regions), `classification`, `commander`, `armament`
7. `unit` (references regions/divisions/classifications/commanders; parents chain inside)
8. `deployment`, `mission`, `holding`, `training`, `assignment`, `note`

Importing out of order is fine to do on purpose: unresolved references show up
as row errors in the report, which is exactly what the fixtures are for.

Headers vary on purpose — English labels, Arabic labels, bilingual
`English / العربية`, and raw keys — all four map through the import mapper.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / OUT_ENT))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    lookup = harvest_lookup_codes()

    reg, mil, meta_mil = load_specs()
    entities = [(k, v, False) for k, v in reg.items()] + [(k, v, True) for k, v in mil.items()]
    manifest = []
    for key, spec, mil_flag in sorted(entities):
        fields = field_info(spec, mil_flag)
        if mil_flag:
            meta_labels = {f.key: f for f in meta_mil[key].fields}
            for f in fields:
                mf = meta_labels.get(f["key"])
                if mf is not None:
                    f["label_en"] = mf.label_en
                    f["label_ar"] = mf.label_ar
        if not fields:
            continue
        rows = build_rows(key, fields, mil_flag, lookup)
        headers = headers_for(fields, key)
        base = out / f"{key}"
        write_csv(base.with_suffix(".csv"), headers, rows, fields)
        write_xlsx(base.with_suffix(".xlsx"), headers, rows, fields)
        manifest.append((key, len(rows), sum(1 for r in rows if all(v == "" for v in r.values()))))
        print(f"wrote {key}: {len(rows)} rows x {len(fields)} fields")
    (out / "README.md").write_text(README, encoding="utf-8")
    print(f"\n{len(manifest)} entities x 2 formats -> {out}")


if __name__ == "__main__":
    main()
