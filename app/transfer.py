"""
Import / export engine.

Import is a 4-step, fully reversible pipeline:
  1. template   GET  /api/import/template/{entity}?format=xlsx&lang=ar
  2. upload     POST /api/import/preview          -> columns, sample, suggested mapping
  3. validate   POST /api/import/validate         -> per-row report, nothing written
  4. commit     POST /api/import/commit           -> writes inside savepoints, logs job

Every step is idempotent and every committed batch leaves an `import_job` row
plus a change_log entry per created/updated record.

Export supports CSV (with BOM so Excel shows Arabic correctly), TSV, JSON and
XLSX (right-to-left sheets, frozen headers, auto filter, styled header row),
with column selection, bilingual headers and the same filter payload used by
the list screens — so "export what I see" is exact.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import uuid
from datetime import date, datetime
from typing import Any, Iterable

from . import db, repo
from . import settings as settings_registry
from .db import normalize
from .schemas import ENTITIES, EntitySpec, coerce, derived_map

MAX_ROWS = 50_000          # hard ceiling; above it the export fails loudly
EXPORT_PAGE = 1_000         # rows read per internal page
ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "cp1252", "latin-1")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def decode_bytes(raw: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def norm_key(value: Any) -> str:
    return re.sub(r"[\s_\-\u00a0]+", " ", normalize(value)).strip()


def parse_numbool(v):
    return v


def coerce_excel_date(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        d = value.date() if isinstance(value, datetime) else value
        return d.isoformat()
    if isinstance(value, str):
        s = value.strip()
        # dd/mm/yyyy or dd-mm-yyyy -> ISO (Middle-East data is usually day-first)
        m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$", s)
        if m and int(m.group(1)) <= 31 and int(m.group(2)) <= 12:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})[T ].*$", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return s
    return value


def build_resolvers(conn: sqlite3.Connection) -> dict:
    """Lookup-domain and FK resolvers (id | code | English label | Arabic label)."""
    lookup_index: dict[str, dict[str, int]] = {}
    for r in conn.execute("SELECT id, domain, code, label_en, label_ar FROM lookup"):
        idx = lookup_index.setdefault(r["domain"], {})
        for key in (r["code"], r["label_en"], r["label_ar"]):
            if key:
                idx.setdefault(norm_key(key), r["id"])
        idx[str(r["id"])] = r["id"]
    ref_index: dict[str, dict[str, int]] = {}
    for key, spec in ENTITIES.items():
        idx = ref_index.setdefault(key, {})
        name_cols = {"person": ("name_en", "name_ar"), "place": ("name_en", "name_ar"),
                     "institution": ("name_en", "name_ar"), "source": ("title", "title_ar"),
                     "event": ("title_en", "title_ar"), "relationship": ()}.get(key, ())
        cols = ", ".join(("id", "code") + name_cols)
        for r in conn.execute(f"SELECT {cols} FROM {spec.table} WHERE deleted_at IS NULL"):
            d = dict(r)
            idx[str(d["id"])] = d["id"]
            for c in ("code",) + name_cols:
                if d.get(c):
                    idx.setdefault(norm_key(d[c]), d["id"])
    return {"lookup": lookup_index, "ref": ref_index}


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------
ALIASES = {
    "id": "id", "identification number": "code", "id number": "code",
    "الرقم التعريفي": "code", "رقم التعريف": "code", "code": "code",
}


def header_for(field, lang: str) -> str:
    if lang == "ar":
        return field.label_ar
    if lang == "both":
        return f"{field.label_en} / {field.label_ar}"
    return field.label_en


def template_bytes(conn, spec: EntitySpec, fmt: str = "xlsx", lang: str = "en",
                   example: bool = True) -> tuple[bytes, str, str]:
    fields = [f for f in spec.fields if not f.system and f.type != "tags"]
    headers = [header_for(f, lang) for f in fields]
    keys = [f.key for f in fields]
    example_row = [_example_value(conn, f) for f in fields] if example else []
    lookup_sheet = _lookup_reference(conn, spec)

    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=delim, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        w.writerow(headers)
        if example_row:
            w.writerow(example_row)
        data = buf.getvalue().encode("utf-8-sig")
        mime = "text/tab-separated-values" if fmt == "tsv" else "text/csv"
        return data, f"{spec.key}-import-template.{fmt}", mime
    if fmt == "json":
        payload = {"entity": spec.key,
                   "columns": [{"key": k, "header": h, "type": f.type,
                                "domain": f.domain, "ref": f.ref}
                               for k, h, f in zip(keys, headers, fields, strict=False)],
                   "help": lookup_sheet,
                   "rows": [dict(zip(keys, example_row, strict=False))] if example_row else []}
        return (json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                f"{spec.key}-import-template.json", "application/json")
    # xlsx
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = safe_sheet_title(spec.plural_ar if lang == "ar" else spec.plural_en)
    if lang == "ar":
        ws.sheet_view.rightToLeft = True
    ws.append(headers)
    if example_row:
        ws.append(example_row)
    head_fill = PatternFill("solid", fgColor="1E3A5F")
    for c, field in enumerate(fields, start=1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = max(14, min(40, len(headers[c - 1]) + 4))
        if field.help_en:
            cell.comment = None
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(fields))}{ws.max_row}"
    # reference sheet
    ws2 = wb.create_sheet(safe_sheet_title("Reference — مرجع"))
    ws2.append(["Field", "Type", "Allowed values (code — English — Arabic)"])
    for c in range(1, 4):
        ws2.cell(row=1, column=c).font = Font(bold=True)
    for f in fields:
        if f.type == "select" and f.domain:
            vals = conn.execute(
                "SELECT code, label_en, label_ar FROM lookup WHERE domain=? AND is_active=1 "
                "ORDER BY sort_order", (f.domain,)).fetchall()
            ws2.append([f.key, f"select:{f.domain}",
                        " | ".join(f"{v['code']} — {v['label_en']} — {v['label_ar']}" for v in vals)])
        elif f.type == "fk":
            ws2.append([f.key, f"ref:{f.ref}", "Use the record identification number (code), e.g. PER-0001"])
        else:
            ws2.append([f.key, f.type, f.help_en or ""])
    ws2.column_dimensions["A"].width = 26
    ws2.column_dimensions["B"].width = 22
    ws2.column_dimensions["C"].width = 110
    out = io.BytesIO()
    wb.save(out)
    return (out.getvalue(), f"{spec.key}-import-template.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def safe_sheet_title(title: str, fallback: str = "Sheet") -> str:
    """Excel forbids backslash, slash, star, question mark, colon and brackets."""
    clean = re.sub(r'[\\/*?\[\]:]', "-", str(title or fallback)).strip() or fallback
    return clean[:31]


def _example_value(conn, f) -> Any:
    if f.type == "select" and f.domain:
        row = conn.execute("SELECT code FROM lookup WHERE domain=? AND is_active=1 "
                           "ORDER BY sort_order LIMIT 1 OFFSET 1", (f.domain,)).fetchone()
        return row["code"] if row else ""
    if f.type == "date":
        return "1950"
    if f.type in ("int", "float"):
        return 0
    if f.type == "url":
        return "https://example.org"
    if f.type == "bool":
        return "no"
    return f"EXAMPLE — {f.label_en}" if f.key != "code" else ""


def _lookup_reference(conn, spec: EntitySpec) -> dict:
    out = {}
    for f in spec.fields:
        if f.type == "select" and f.domain:
            out[f.key] = [dict(r) for r in conn.execute(
                "SELECT code, label_en, label_ar FROM lookup WHERE domain=? AND is_active=1 "
                "ORDER BY sort_order", (f.domain,))]
    return out


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def parse_tabular(raw: bytes, filename: str) -> tuple[list[str], list[dict], str]:
    """Return (columns, rows, detected_format)."""
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip() if h is not None else "" for h in next(it)]
        except StopIteration:
            return [], [], "xlsx"
        rows = []
        for r in it:
            if r is None or all(v is None or str(v).strip() == "" for v in r):
                continue
            rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
            if len(rows) >= MAX_ROWS:
                break
        return [h for h in header if h], rows, "xlsx"
    if lower.endswith(".xls"):
        raise ValueError("Legacy .xls is not supported — save the file as .xlsx and retry.")
    if lower.endswith(".json"):
        data = json.loads(decode_bytes(raw)[0])
        if isinstance(data, dict):
            rows = data.get("rows") or data.get("data") or []
        else:
            rows = data
        columns = []
        for r in rows[:50]:
            for k in r:
                if k not in columns:
                    columns.append(k)
        return columns, rows, "json"
    # csv / tsv / txt
    text, _enc = decode_bytes(raw)
    sample = text[:8192]
    delim = "\t" if (lower.endswith(".tsv") or sample.count("\t") > sample.count(",")) else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows_raw = [r for r in reader]
    if not rows_raw:
        return [], [], "csv"
    header = [h.strip() for h in rows_raw[0]]
    rows = []
    for r in rows_raw[1:]:
        if not any(str(v).strip() for v in r):
            continue
        rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
        if len(rows) >= MAX_ROWS:
            break
    return [h for h in header if h], rows, "csv"


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------
def header_index(spec: EntitySpec) -> dict[str, str]:
    idx: dict[str, str] = {}
    for f in spec.fields:
        for key in (f.label_en, f.label_ar, f.key):
            if key:
                idx[norm_key(key)] = f.key
    for alias, key in ALIASES.items():
        idx.setdefault(norm_key(alias), key)
    return idx


def suggest_mapping(spec: EntitySpec, columns: Iterable[str]) -> dict[str, str]:
    idx = header_index(spec)
    out = {}
    for col in columns:
        key = None
        nk = norm_key(col)
        # a bilingual header ("Name in Arabic / الاسم بالعربية") is two chances
        # to match: try each side exactly before falling back to substrings
        sides = [norm_key(side) for side in re.split(r"[/\u060d]", col)]
        for side in [x for x in sides if x] or [nk]:
            key = idx.get(side)
            if key:
                break
        if key is None and len(nk) > 2:
            best = None
            for cand, fk in idx.items():
                if cand and len(cand) > 2 and (cand in nk or nk in cand):
                    if best is None or len(cand) > best[0]:
                        best = (len(cand), fk)      # the most specific label wins
            key = best[1] if best else None
        if key:
            out[col] = key
    return out


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------
def _resolve_value(conn, spec: EntitySpec, field, value, resolvers, errors: list,
                   row_no: int, auto_create_fk: bool = False) -> Any:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if field.type == "date":
        value = coerce_excel_date(value)
    if field.type == "select":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        raw = str(value).strip()
        if raw.isdigit():
            return int(raw)
        idx = resolvers["lookup"].get(field.domain or "", {})
        found = idx.get(norm_key(raw))
        if found is None:
            errors.append({"row": row_no, "field": field.key,
                           "message": f"Unknown value '{raw}' for {field.label_en} "
                                      f"(allowed: {field.domain})"})
            return None
        return found
    if field.type == "fk":
        raw = str(value).strip()
        if raw.isdigit():
            return int(raw)
        idx = resolvers["ref"].get(field.ref or "", {})
        found = idx.get(norm_key(raw))
        if found is None and raw.endswith("]") and "[" in raw:
            # The resolved export format is "Label [CODE]" (see export_bytes);
            # accept that composite back so an exported file imports cleanly.
            bracketed = raw[raw.rfind("[") + 1:-1].strip()
            found = idx.get(norm_key(bracketed))
        if found is None:
            errors.append({"row": row_no, "field": field.key,
                           "message": f"Unknown reference '{raw}' for {field.label_en} "
                                      f"(use the identification number, e.g. "
                                      f"{ENTITIES[field.ref].code_prefix if field.ref in ENTITIES else 'XXX'}-0001)"})
            return None
        return found
    if field.type in ("int", "float"):
        try:
            return field.type == "int" and int(float(value)) or float(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, str):
        return value.strip()
    return value


def _register_written(resolvers: dict, spec: EntitySpec, conn: sqlite3.Connection,
                      code: str | None, values: dict) -> None:
    """A row just wrote a record; later rows in the same batch may reference it.

    A parent place above its neighbourhood is the ordinary shape of a real file,
    so same-batch references must resolve as if the parent had always existed.
    """
    if not code:
        return
    row = conn.execute(f"SELECT id FROM {spec.table} WHERE code=?", (code,)).fetchone()
    if not row:
        return
    idx = resolvers["ref"].setdefault(spec.key, {})
    rid = row["id"]
    idx[str(rid)] = rid
    idx.setdefault(norm_key(code), rid)
    for nkey in ("name_en", "name_ar", "title", "title_ar"):
        if values.get(nkey):
            idx.setdefault(norm_key(str(values[nkey])), rid)


def process_rows(conn: sqlite3.Connection, spec: EntitySpec, rows: list[dict],
                 mapping: dict[str, str], mode: str = "create",
                 actor: str = "researcher", dry_run: bool = True,
                 default_status: str | None = None,
                 match_on: list[str] | None = None,
                 reason: str | None = None) -> dict:
    """Validate (and optionally write) rows.  Returns a detailed report."""
    resolvers = build_resolvers(conn)
    known = {f.key for f in spec.fields}
    default_status_id = repo._lookup_id(conn, "record_status", default_status or "in_review")
    match_on = [m for m in (match_on or ["code"]) if m in known | {"id"}]
    mapping = {h: k for h, k in mapping.items() if k in known | {"id"} or k.startswith("_")}
    unknown_targets = sorted({k for k in mapping.values() if k not in known and k != "id"})

    report = {
        "entity": spec.key, "mode": mode, "dry_run": dry_run,
        "total": len(rows), "created": 0, "updated": 0, "skipped": 0, "failed": 0,
        "errors": [], "warnings": [], "unknown_targets": unknown_targets,
        "rows": [], "mapping": mapping,
    }
    if not mapping:
        report["errors"].append({"row": 0, "field": None,
                                 "message": "No column is mapped to a field — nothing to import."})
        return report

    seen_codes: dict[str, int] = {}
    for i, raw_row in enumerate(rows, start=2):   # row 1 = header
        row_errors: list[dict] = []
        values: dict[str, Any] = {}
        for header, field_key in mapping.items():
            if field_key == "id":
                continue
            field = spec.field(field_key)
            if field is None:
                continue
            raw_val = raw_row.get(header)
            val = _resolve_value(conn, spec, field, raw_val, resolvers, row_errors, i)
            if val is not None:
                coerced, err = coerce(spec, field.key, val)
                if err:
                    row_errors.append({"row": i, "field": field.key, "message": err})
                else:
                    values[field.key] = coerced
        code = values.get("code") or (raw_row.get(mapping and list(mapping)[0]) if False else None)
        if not code and "code" in mapping:
            code = str(raw_row.get([h for h, k in mapping.items() if k == "code"][0]) or "").strip() or None

        existing = None
        if code:
            if norm_key(code) in seen_codes:
                row_errors.append({"row": i, "field": "code",
                                   "message": f"Duplicate identification number '{code}' inside the file"})
            seen_codes[norm_key(code)] = i
            existing = conn.execute(f"SELECT * FROM {spec.table} WHERE code=?", (code,)).fetchone()
        elif mode in ("upsert", "update_only", "update") and match_on != ["code"]:
            clause = " AND ".join(f"{m}=?" for m in match_on if m in values)
            params = [values[m] for m in match_on if m in values]
            if clause:
                existing = conn.execute(
                    f"SELECT * FROM {spec.table} WHERE {clause}", params).fetchone()

        if mode == "create" and existing:
            row_errors.append({"row": i, "field": "code",
                               "message": f"Record {code} already exists (mode = create). "
                                          f"Use upsert to update it."})
        if mode in ("update_only", "update") and not existing:
            row_errors.append({"row": i, "field": "code",
                               "message": f"Record {code or '(no code)'} not found — skipped in update_only mode"})

        status = "failed" if row_errors else ("updated" if existing else "created")
        report["rows"].append({
            "row": i, "code": code, "status": status,
            "errors": row_errors, "values_preview": {k: values[k] for k in list(values)[:8]},
        })
        report["errors"].extend(row_errors)
        if row_errors:
            report["failed"] += 1
            continue

        if dry_run:
            report[status if status in ("created", "updated") else "skipped"] += 1
            continue

        # -- write inside a savepoint so one bad row cannot poison the batch
        conn.execute("SAVEPOINT imp_row")
        try:
            if existing:
                payload = dict(values)
                payload.pop("code", None)
                repo.update_record(conn, spec, existing["id"], payload, actor=actor,
                                   reason=reason or "bulk import", commit=False)
                report["updated"] += 1
            else:
                payload = dict(values)
                if default_status_id and not payload.get("record_status_id"):
                    payload["record_status_id"] = default_status_id
                if code:
                    payload["code"] = code
                repo.create_record(conn, spec, payload, actor=actor,
                                   reason=reason or "bulk import", commit=False)
                report["created"] += 1
            conn.execute("RELEASE SAVEPOINT imp_row")
            _register_written(resolvers, spec, conn, code, values)
        except (repo.RepoError, sqlite3.Error) as exc:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT imp_row")
                conn.execute("RELEASE SAVEPOINT imp_row")
            except sqlite3.Error:
                conn.rollback()
            report["failed"] += 1
            report["rows"][-1]["status"] = "failed"
            report["rows"][-1]["errors"].append({"row": i, "field": None, "message": str(exc)})
            report["errors"].append({"row": i, "field": None, "message": str(exc)})

    report["rows"] = report["rows"][:500]
    report["errors"] = report["errors"][:500]
    if not dry_run:
        conn.commit()
    return report


def record_job(conn, spec: EntitySpec, filename: str, fmt: str, mode: str,
               dry_run: bool, report: dict, actor: str, mapping: dict) -> str:
    job_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO import_job (id, entity_type, filename, format, mode, dry_run, status,
              total_rows, created_rows, updated_rows, skipped_rows, failed_rows, mapping, report,
              actor, finished_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, spec.key, filename, fmt, mode, 1 if dry_run else 0,
         "dry_run" if dry_run else ("partial" if report["failed"] else "completed"),
         report["total"], report["created"], report["updated"], report["skipped"],
         report["failed"], db.json_dump(mapping),
         db.json_dump({"errors": report["errors"][:200],
                       "warnings": report["warnings"]}), actor, db.now()))
    conn.commit()
    return job_id


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
SENSITIVE = {"created_by", "updated_by"}
CITATION_STYLE = {"apa", "mla", "chicago", "plain"}


EXPORT_FORMATS = ("csv", "tsv", "xlsx", "json")


class UnsupportedFormat(ValueError):
    """Raised for an export format the registry does not produce."""

    def __init__(self, fmt: str) -> None:
        self.fmt = fmt
        super().__init__(f"Unsupported export format '{fmt}' "
                         f"(choose from {', '.join(EXPORT_FORMATS)})")


def _export_rows(conn, spec: EntitySpec, payload: dict, columns: list[str],
                 lang: str, resolve: bool = True) -> tuple[list[dict], list[str]]:
    """Every row that matches the filter — paged internally, never truncated.

    The list endpoint clamps ``page_size`` to 1 000 so a browser cannot pull the
    whole table in one request; an export must respect the *filter* but not that
    guard, otherwise a filtered export silently loses rows beyond the first
    thousand.  Rows are read in pages of 1 000 until the reported total is
    reached, with ``MAX_ROWS`` as a hard ceiling that fails loudly instead of
    dropping data.
    """
    # the ceiling is configuration, not a constant: an archivist exporting a whole
    # table and an operator protecting the server want different answers
    ceiling = settings_registry.get(conn, "export.max_rows", MAX_ROWS) or MAX_ROWS
    payload = dict(payload or {})
    payload["page"] = 1
    payload["page_size"] = EXPORT_PAGE
    headers = _export_headers(spec, columns, lang)
    out_rows: list[dict] = []
    page = 1
    while True:
        payload["page"] = page
        data = repo.list_records(conn, spec, payload, max_page_size=EXPORT_PAGE)
        if data["total"] > ceiling:
            raise repo.ValidationError(
                f"This selection has {data['total']:,} rows; the export ceiling is "
                f"{ceiling:,} (export.max_rows). Narrow the filters, export in parts, or "
                f"raise the setting — the file was not written, because a silently "
                f"shortened export is worse than none.")
        for item in data["items"]:
            out_rows.append(_export_row(spec, item, columns, headers, lang, resolve))
        if page >= data["pages"] or not data["items"]:
            break
        page += 1
    return out_rows, headers


def _export_row(spec: EntitySpec, item: dict, columns: list[str], headers: list[str],
                lang: str, resolve: bool) -> dict:
    """One row of the sheet, with vocabulary codes and references made readable."""
    dmap = derived_map(spec.key)
    row = {}
    for col, header in zip(columns, headers, strict=False):
        f = spec.field(col)
        if f is None and col in dmap:
            row[header] = (item.get("_derived") or {}).get(col)
            continue
        val = item.get(col)
        if resolve and f and f.type == "select" and col in item.get("_labels", {}):
            lab = item["_labels"][col]
            val = lab["ar"] if lang == "ar" else f'{lab["en"]} ({lab["code"]})'
            if lang == "both":
                val = f'{lab["en"]} / {lab["ar"]}'
        elif resolve and f and f.type == "fk" and col in item.get("_refs", {}):
            ref = item["_refs"][col]
            val = f'{ref.get("label") or ""} [{ref.get("code") or ""}]'.strip()
        row[header] = val
    return row


def _export_headers(spec: EntitySpec, columns: list[str], lang: str) -> list[str]:
    dmap = derived_map(spec.key)
    headers = []
    for col in columns:
        f = spec.field(col)
        if f is None and col in dmap:
            d = dmap[col]
            headers.append(d.label_ar if lang == "ar" else
                           (f"{d.label_en} / {d.label_ar}" if lang == "both" else d.label_en))
        elif f is None:
            headers.append(col)
        elif lang == "ar":
            headers.append(f.label_ar or f.label_en)
        elif lang == "both":
            headers.append(f"{f.label_en} / {f.label_ar}")
        else:
            headers.append(f.label_en)
    return headers


def export_bytes(conn, spec: EntitySpec, payload: dict, fmt: str,
                 columns: list[str] | None = None, lang: str = "en",
                 resolve: bool = True, title: str | None = None) -> tuple[bytes, str, str]:
    columns = columns or [f.key for f in spec.fields if f.in_list]
    allowed = {f.key for f in spec.fields} | set(derived_map(spec.key))
    columns = [c for c in columns if c in allowed]
    if not columns:
        columns = [f.key for f in spec.fields if f.in_list]
    rows, headers = _export_rows(conn, spec, payload, columns, lang, resolve)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    # localised, human-readable file name (Arabic is sent to the browser with an
    # RFC 5987 header, so it displays correctly on Windows and everywhere else)
    base = (f"{spec.plural_ar}-{stamp}" if lang == "ar"
            else f"{spec.plural_en.replace(' ', '-').lower()}-{stamp}")

    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=headers, delimiter=delim,
                           quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({h: ("" if r.get(h) is None else r.get(h)) for h in headers})
        return (buf.getvalue().encode("utf-8-sig"), f"{base}.{fmt}",
                "text/tab-separated-values" if fmt == "tsv" else "text/csv; charset=utf-8")

    if fmt == "json":
        meta = {"entity": spec.key, "exported_at": db.now(), "count": len(rows),
                "columns": headers, "filters": payload}
        data = {"meta": meta, "rows": rows}
        return (json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                f"{base}.json", "application/json")

    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = safe_sheet_title(title or spec.plural_en)
        if lang == "ar":
            ws.sheet_view.rightToLeft = True
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h) if r.get(h) is not None else "" for h in headers])
        fill = PatternFill("solid", fgColor="1E3A5F")
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            width = max(12, min(45, max(
                [len(str(headers[c - 1]))] + [len(str(r.get(headers[c - 1], ""))) for r in rows[:200]]) + 3))
            ws.column_dimensions[get_column_letter(c)].width = width
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(max(1, len(headers)))}{ws.max_row}"
        meta = wb.create_sheet(safe_sheet_title("Export info — بيانات التصدير"))
        for row in [("Entity", spec.plural_en), ("Records", len(rows)),
                    ("Exported at (UTC)", db.now()), ("Language", lang),
                    ("Filters", json.dumps(payload, ensure_ascii=False)[:3000])]:
            meta.append(list(row))
        meta.column_dimensions["A"].width = 24
        meta.column_dimensions["B"].width = 100
        buf = io.BytesIO()
        wb.save(buf)
        return (buf.getvalue(), f"{base}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    raise UnsupportedFormat(fmt)


def citation(spec: EntitySpec, item: dict, style: str = "apa") -> str:
    """Build a human-readable citation line for a record."""
    t = spec.title(item)
    code = item.get("code") or ""
    year = (str(item.get("publication_date"))[:4] if item.get("publication_date")
            else str(item.get("birth_date") or "")[:4])
    publisher = item.get("publisher") or item.get("affiliated_institution_id") or ""
    if style == "mla":
        return f'{t}. {publisher}, {year}. Registry record {code}.'
    if style == "chicago":
        return f'{t}. {publisher}, {year}. ({code}).'
    if style == "plain":
        return f"{t} — {code} — {year}"
    return f'{t}. ({year}). {publisher}. [{code}]'
