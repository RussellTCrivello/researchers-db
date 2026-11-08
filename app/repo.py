"""
Repository layer — every read and write of business data goes through here.

Responsibilities
  * validation + coercion via app.schemas
  * numbering (auto codes) and optimistic locking (version)
  * field-level audit trail (change_log) with reason / source / actor
  * soft delete / restore / hard delete
  * full-text index maintenance
  * rich detail views (labels, children, relationships, citations, history)
  * the advanced filter engine used by lists, exports and reports
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime as dt
from typing import Any, Iterable, Sequence

from . import db
from . import settings as settings_registry
from .schemas import ENTITIES, EntitySpec, coerce, derived_map, load_lookup_map, resolve_ref, to_timestamp


class RepoError(Exception):
    status = 400


class NotFound(RepoError):
    status = 404


class ValidationError(RepoError):
    status = 422


class Conflict(RepoError):
    status = 409


# ---------------------------------------------------------------------------
# filters
# ---------------------------------------------------------------------------
OPS_SQL = {
    "eq": "= ?",
    "ne": "<> ?",
    "gt": "> ?",
    "gte": ">= ?",
    "lt": "< ?",
    "lte": "<= ?",
}

TEXT_OPS = {
    "contains": lambda v: ("norm({col}) LIKE ?", [f"%{db.normalize(v)}%"]),
    "not_contains": lambda v: ("norm({col}) NOT LIKE ?", [f"%{db.normalize(v)}%"]),
    "starts": lambda v: ("norm({col}) LIKE ?", [f"{db.normalize(v)}%"]),
    "ends": lambda v: ("norm({col}) LIKE ?", [f"%{db.normalize(v)}"]),
    "equals": lambda v: ("norm({col}) = ?", [db.normalize(v)]),
}


def _field_col(spec: EntitySpec, key: str) -> str:
    if key in ("id", "code", "created_at", "updated_at", "deleted_at"):
        return key
    if key in derived_map(spec.key):
        return key                       # kept verbatim; resolved to SQL below
    f = spec.field(key)
    if f is None:
        raise ValidationError(f"Unknown or non-filterable field '{key}'")
    return f.key


def column_expr(spec: EntitySpec, key: str, alias: str = "t") -> tuple[str, Any]:
    """SQL expression for a plain field *or* a derived (related-table) field."""
    d = derived_map(spec.key).get(key)
    if d is not None:
        return d.sql.replace("t.", f"{alias}."), d
    return f"{alias}.{key}", spec.field(key)


def _cmp_expr(qualified: str, f: Any) -> str:
    """Comparison/sort expression for a field.

    Some vocabulary selects live in TEXT-affinity columns (e.g. ``birth_precision``)
    while their value is a lookup *id*.  SQLite would then compare '194' with 194
    and match nothing, so id-valued selects are compared as integers.  Selects that
    store a code, and everything else, are left untouched.
    """
    if f is not None and getattr(f, "type", None) == "select" and getattr(f, "store", "id") == "id":
        return f"CAST({qualified} AS INTEGER)"
    if f is not None and getattr(f, "type", None) == "fk":
        return f"CAST({qualified} AS INTEGER)"
    return qualified


def _coerce_filter_value(value: Any, ftype: str | None) -> Any:
    """Coerce JSON values (always strings from the browser) to the SQL type.

    Without this, ``relationships_count >= "1"`` silently matches nothing,
    because SQLite compares integers to text without implicit casting.
    """
    if value is None or ftype is None:
        return value
    if isinstance(value, bool):
        return int(value)
    if ftype in ("int", "float", "select", "fk", "bool"):
        text = str(value).strip()
        if text == "":
            return value
        if ftype == "bool" and text.lower() in ("true", "false", "yes", "no"):
            return 1 if text.lower() in ("true", "yes") else 0
        try:
            num = float(text)
        except ValueError:
            return value
        if ftype in ("int", "select", "fk", "bool"):
            return int(num) if num.is_integer() else value
        return num
    return value


# filled once per process: domain -> {code/label: id}, so filters can speak in codes
_LOOKUP_CACHE: dict[str, dict[str, int]] = {}


def _lookup_index(conn: sqlite3.Connection, domain: str) -> dict[str, int]:
    """code / label_en / label_ar / normalised label → id for one vocabulary."""
    if domain not in _LOOKUP_CACHE:
        index: dict[str, int] = {}
        for r in conn.execute(
                "SELECT id, code, label_en, label_ar FROM lookup WHERE domain=?", (domain,)):
            for key in (r["code"], r["label_en"], r["label_ar"]):
                if not key:
                    continue
                index.setdefault(str(key).strip().lower(), r["id"])
                index.setdefault(db.normalize(key), r["id"])
        _LOOKUP_CACHE[domain] = index
    return _LOOKUP_CACHE[domain]


def _resolve_select_value(conn: sqlite3.Connection, field: Any, value: Any) -> Any:
    """Turn a vocabulary *code* or *label* into the numeric id stored in the row.

    The UI always sends ids, but scripts, saved views and hand-written filters read
    better with codes (``record_status_id: "verified"``).  Without this a code would
    simply match nothing — a silent empty result is the worst possible behaviour.
    """
    if conn is None or value is None or field is None:
        return value
    if getattr(field, "type", None) != "select":
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return value
    if text.lstrip("-").isdigit():
        return int(text)
    domain = getattr(field, "domain", None)
    if not domain:
        return value
    index = _lookup_index(conn, domain)
    return index.get(text.lower()) or index.get(db.normalize(text)) or value


FILTER_OP_ALIASES = {
    "eq": "eq", "=": "eq", "is": "eq",
    "ne": "ne", "neq": "ne", "!=": "ne", "<>": "ne",
    "gt": "gt", ">": "gt", "gte": "gte", ">=": "gte",
    "lt": "lt", "<": "lt", "lte": "lte", "<=": "lte",
    "in": "in", "not_in": "not_in",
    "contains": "contains", "not_contains": "not_contains",
    "startswith": "starts", "startswiths": "starts", "start": "starts", "starts": "starts",
    "endswith": "ends", "end": "ends", "ends": "ends",
    "equals": "equals", "is_exactly": "equals",
    "between": "between", "not_between": "not_between",
    "is_null": "is_null", "not_null": "not_null",
    "empty": "empty", "not_empty": "not_empty",
    "year_eq": "year_eq", "year_gte": "year_gte", "year_lte": "year_lte",
    "on": "on", "on_day": "on", "before": "before", "until": "before",
    "after": "after", "since": "after",
}

# Keys that are *payload* structure rather than filter fields.  A saved view, an
# export body and a list request all share one shape, and ``filters`` may legally
# carry a full payload inside it (``{"filters": {"where": [...]}}``), so the
# compact-form translator must skip these instead of inventing a clause for them.
_NON_FILTER_KEYS = {
    # browsing state
    "page", "page_size", "pagesize", "sort", "order", "q", "logic", "columns", "all",
    "include_deleted", "only_deleted", "view", "layout",
    # filter payload structure (a full payload may be nested inside "filters")
    "filters", "where", "tag_ids", "status_ids", "only_ids", "has_relationship_type",
}
# NOTE: never add a *field name* here — `title`, `lang` and `format` are real
# columns in this schema, and treating them as structure silently drops the
# filter (that mistake made every source look like a scratch record).


def normalize_filters(payload: dict) -> dict:
    """Accept the compact ``{"filters": {field: value | {op: value}}}`` form.

    The UI posts the explicit clause list (``where: [{field, op, value}]``), but
    scripts, exports and saved views are far easier to write as a plain mapping.
    Both are accepted everywhere (list, KPI, reports, export): the mapping is
    translated into clauses here, so there is exactly one filter engine — and an
    unknown field still produces a warning instead of being silently ignored.
    """
    if not isinstance(payload, dict):
        return payload
    filters = payload.get("filters")
    if not isinstance(filters, dict) or not filters:
        return payload
    payload = dict(payload)
    # structural keys given *inside* "filters" are lifted to the top level, so a
    # body written as {"filters": {"where": [...], "q": "..."}} behaves exactly
    # like {"where": [...], "q": "..."}
    for key in ("where", "q", "sort", "order", "logic", "tag_ids", "status_ids",
                "only_ids", "has_relationship_type", "include_deleted", "only_deleted"):
        if key in filters and key not in payload:
            payload[key] = filters[key]
    clauses = list(payload.get("where") or [])
    for field, spec in filters.items():
        if field in _NON_FILTER_KEYS:
            continue
        if isinstance(spec, dict):
            for op, val in spec.items():
                clauses.append({"field": field,
                                "op": FILTER_OP_ALIASES.get(str(op).lower(), str(op)),
                                "value": val})
        else:
            clauses.append({"field": field, "op": "eq", "value": spec})
    payload["where"] = clauses
    return payload


def build_where(spec: EntitySpec, payload: dict,
                conn: sqlite3.Connection | None = None) -> tuple[str, list[Any], list[str]]:
    """Translate the JSON filter payload into a SQL WHERE clause.

    Returns (sql, params, warnings).  Unknown fields become warnings rather than
    errors so that stale saved views never break a page.
    """
    payload = normalize_filters(payload or {})
    where: list[str] = []
    params: list[Any] = []
    warnings: list[str] = []

    # Soft-delete flags only exist on registry tables; entities without the
    # capability (soft_delete=False) must not filter on a column they lack.
    if getattr(spec, "soft_delete", True):
        if payload.get("only_deleted"):
            where.append("t.deleted_at IS NOT NULL")
        elif not payload.get("include_deleted"):
            where.append("t.deleted_at IS NULL")

    if payload.get("status_ids"):
        ids = [int(i) for i in payload["status_ids"] if str(i).lstrip("-").isdigit()]
        if ids:
            where.append(f"t.record_status_id IN ({','.join('?' * len(ids))})")
            params += ids

    if payload.get("only_ids"):
        ids = [int(i) for i in payload["only_ids"] if str(i).isdigit()]
        if ids:
            where.append(f"t.id IN ({','.join('?' * len(ids))})")
            params += ids

    for clause in payload.get("where") or []:
        if not isinstance(clause, dict):
            continue
        key = clause.get("field") or clause.get("key")
        op = str(clause.get("op") or clause.get("operator") or "eq").lower().strip()
        op = FILTER_OP_ALIASES.get(op, op)      # one canonical spelling, everywhere
        val = clause.get("value")
        if not key:
            continue
        try:
            col = _field_col(spec, key)
        except ValidationError as exc:
            warnings.append(str(exc))
            continue
        f = spec.field(key)
        if key in derived_map(spec.key):
            qualified, d = column_expr(spec, key)
            ftype = d.type
            f = None
        else:
            qualified = f"t.{col}"
            ftype = f.type if f else None

        cmp = _cmp_expr(qualified, f)

        if op == "is_null":
            where.append(f"{qualified} IS NULL")
            continue
        if op == "not_null":
            where.append(f"{qualified} IS NOT NULL")
            continue
        if op in ("empty", "not_empty"):
            # "empty" means absent *or* blank after trimming — what a researcher
            # means by "no value", not merely SQL NULL
            blank = (f"({qualified} IS NULL OR TRIM(CAST({qualified} AS TEXT)) = '')")
            where.append(blank if op == "empty" else f"NOT {blank}")
            continue
        if op in ("in", "not_in"):
            values = val if isinstance(val, (list, tuple)) else [val]
            values = [_resolve_select_value(conn, f, v) if f is not None else v for v in values]
            values = [_coerce_filter_value(v, ftype) for v in values if v not in (None, "")]
            if not values:
                continue
            marks = ",".join("?" * len(values))
            where.append(f"{cmp} {'IN' if op == 'in' else 'NOT IN'} ({marks})")
            params += values
            continue
        if op in ("between", "not_between"):
            if not isinstance(val, (list, tuple)) or len(val) != 2:
                continue
            lo, hi = val
            if (f and f.type == "date") or (key in derived_map(spec.key)):
                if f and f.type == "date":
                    # a moment-aware range: 1947-03-01 … 1947-06-30 18:00
                    expr = f"ts_of({qualified})"
                    lo_stamp, hi_stamp = to_timestamp(lo), to_timestamp(hi)
                    if lo_stamp:
                        where.append(f"{expr} >= ?")
                        params.append(lo_stamp)
                    if hi_stamp:
                        if to_timestamp(hi) and str(hi).strip().count("-") == 2 \
                                and len(str(hi).strip()) <= 10:
                            # a bare date is inclusive of the whole day
                            where.append(f"{expr} < ?")
                            params.append(hi_stamp[:10] + " 23:59:59.999")
                        else:
                            where.append(f"{expr} <= ?")
                            params.append(hi_stamp)
                    continue
                expr = qualified if key in derived_map(spec.key) else f"year_of({qualified})"
                if str(lo).isdigit():
                    where.append(f"{expr} >= ?"); params.append(int(lo))
                if str(hi).isdigit():
                    where.append(f"{expr} <= ?"); params.append(int(hi))
            else:
                lo = _coerce_filter_value(lo, ftype)
                hi = _coerce_filter_value(hi, ftype)
                where.append(f"{cmp} {'>=' if op == 'between' else '<'} ?")
                params.append(lo)
                if op == "between":
                    where.append(f"{cmp} <= ?"); params.append(hi)
            continue
        if op in ("on", "before", "after"):
            # moment-aware comparison: "on 12 March 1947", "before 1950-04",
            # "after 1950-04-12 09:30".  Partial values expand downwards, so
            # "after 1950" means after the *start* of 1950.
            if val in (None, ""):
                continue
            stamp = to_timestamp(val)
            if not stamp:
                warnings.append(f"'{key}' expects a date for '{op}', got {val!r}")
                continue
            expr = f"ts_of({qualified})"
            if op == "on":
                where.append(f"substr({expr}, 1, 10) = ?")
                params.append(stamp[:10])
            elif op == "before":
                where.append(f"{expr} < ?")
                params.append(stamp)
            else:
                where.append(f"{expr} >= ?")
                params.append(stamp)
            continue
        if op in ("year_eq", "year_gte", "year_lte"):
            if val in (None, ""):
                continue
            try:
                year = int(str(val).strip()[:4])
            except ValueError:
                warnings.append(f"'{key}' expects a year for '{op}', got {val!r}")
                continue
            expr = f"year_of({qualified})"
            where.append(f"{expr} " + {"year_eq": "=", "year_gte": ">=", "year_lte": "<="}[op] + " ?")
            params.append(year)
            continue
        if op in TEXT_OPS:
            sql, ps = TEXT_OPS[op](val if val is not None else "")
            where.append(sql.format(col=qualified))
            params += ps
            continue
        if op in OPS_SQL:
            if val in (None, ""):
                continue
            where.append(f"{cmp} {OPS_SQL[op]}")
            params.append(_coerce_filter_value(_resolve_select_value(conn, f, val), ftype))
            continue
        warnings.append(f"Unsupported operator '{op}' on '{key}'")

    # tags (specialisation / expertise)
    tag_ids = payload.get("tag_ids") or []
    if tag_ids:
        ids = [int(i) for i in tag_ids if str(i).isdigit()]
        if ids:
            marks = ",".join("?" * len(ids))
            where.append(
                f"t.id IN (SELECT entity_id FROM entity_tag "
                f"WHERE entity_type=? AND tag_id IN ({marks}))")
            params.append(spec.key)
            params += ids

    if payload.get("has_relationship_type"):
        rt = int(payload["has_relationship_type"])
        where.append(
            "t.id IN (SELECT entity1_id FROM relationship WHERE entity1_type=? "
            "AND relationship_type_id=? AND deleted_at IS NULL "
            "UNION SELECT entity2_id FROM relationship WHERE entity2_type=? "
            "AND relationship_type_id=? AND deleted_at IS NULL)")
        params += [spec.key, rt, spec.key, rt]

    logic = " OR " if str(payload.get("logic", "and")).lower() == "or" else " AND "
    clause = (logic.join(f"({w})" for w in where)) if where else "1=1"

    # free text search via the FTS index (Arabic-normalised); entities that do
    # not live in search_doc (full_text_index=False) fall back to a LIKE scan of
    # their own text fields, so quick search works on every table alike
    q = (payload.get("q") or "").strip()
    if q and getattr(spec, "full_text_index", True):
        match = db.fts_query(q)
        if match:
            clause += (" AND " if clause != "1=1" else "") + (
                f"t.id IN (SELECT entity_id FROM search_doc "
                f"WHERE search_doc MATCH ? AND entity_type='{spec.key}')")
            params.append(match)
    elif q:
        likes = [f"norm(t.{f.key}) LIKE ?" for f in spec.fields
                 if (f.type in ("text", "textarea") and not f.system)
                 or f.key == "code"]
        if likes:
            group = "(" + " OR ".join(likes) + ")"
            clause = group if clause == "1=1" else clause + " AND " + group
            params += [f"%{db.normalize(q)}%"] * len(likes)
    return clause, params, warnings


def _sort_clause(spec: EntitySpec, payload: dict) -> str:
    """Build an ``ORDER BY`` from any of the three sort shapes the UI sends.

    ``{"sort": "name_en", "order": "asc"}`` · ``{"sort": {"key": "completeness",
    "dir": "desc"}}`` · ``{"sort": [{"key": "code", "dir": "asc"}, …]}``

    Unknown keys fall back to ``id`` instead of raising, so a stale saved view
    never breaks a list. Every clause ends in ``t.id`` to make pages stable.
    """
    allowed = {f.key for f in spec.fields} | {"id", "code"} | set(derived_map(spec.key))
    default_order = str(payload.get("order", spec.default_order)).lower()

    requests: list[tuple[str, str]] = []
    raw = payload.get("sort") or spec.default_sort
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    for item in items:
        if isinstance(item, dict):
            key = item.get("key") or item.get("field") or ""
            direction = str(item.get("dir") or item.get("order") or default_order)
        elif isinstance(item, str):
            key, direction = item, default_order
        else:
            continue
        direction = "ASC" if direction.lower() == "asc" else "DESC"
        if key in allowed:
            requests.append((key, direction))
    if not requests:
        requests = [("id", "ASC")]

    parts: list[str] = []
    for key, direction in requests:
        if key == "id":
            parts.append(f"t.id {direction}")
        elif key in derived_map(spec.key):
            parts.append(f"({column_expr(spec, key)[0]}) {direction}")
        else:
            fld = spec.field(key)
            if fld and fld.type == "date":
                # the whole moment, not just the year: 12 March sorts before 3 April
                parts.append(f"ts_of(t.{key}) {direction}")
            else:
                parts.append(f"{_cmp_expr('t.' + key, fld)} {direction}")
    if "t.id" not in parts[-1]:
        parts.append(f"t.id {requests[0][1]}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# key figures (KPI strip on list pages)
# ---------------------------------------------------------------------------
KPI_COUNTS = ("relationships_count", "positions_count", "citations_count",
              "persons_count", "institutions_count", "participants_count",
              "primary_for_count", "children_count", "persons_born_count")


def kpi_summary(conn: sqlite3.Connection, spec: EntitySpec, payload: dict) -> dict:
    """Headline figures for the current (filtered) selection.

    Used by the KPI strip above every list: how many records match, how complete
    they are on average, how many need work, how fresh they are, and what the
    totals of the related-table counts add up to for this selection.
    """
    where, params, warnings = build_where(spec, payload, conn)
    derived = derived_map(spec.key)
    sums = [k for k in KPI_COUNTS if k in derived]
    sum_sql = "".join(f', SUM("d_{k}") AS "s_{k}"' for k in sums)
    # the derived aliases live on the inner query, so aggregate over it directly
    agg_cols = ['COUNT(*) AS n']
    if "completeness" in derived:
        agg_cols += ['AVG("d_completeness") AS avg_completeness',
                     'SUM(CASE WHEN "d_completeness" < 50 THEN 1 ELSE 0 END) AS low_completeness']
    sum_sql = "".join(f', SUM("d_{k}") AS "s_{k}"' for k in sums)
    agg_cols.append(f"SUM(CASE WHEN julianday('now') - julianday("
                    f"{getattr(spec, 'freshness_col', 'updated_at')}) <= 30 "
                    f"THEN 1 ELSE 0 END) AS recent")
    row = conn.execute(
        f'SELECT {", ".join(agg_cols)}{sum_sql} '
        f'FROM (SELECT *{_derived_select(spec)} FROM {spec.table} t WHERE {where}) q',
        params).fetchone()
    data = dict(row)
    tiles = [{"key": "records", "value": data["n"] or 0, "unit": "records",
              "label_en": f"{spec.plural_en} in this view", "label_ar": f"{spec.plural_ar} في هذا العرض"}]
    if data.get("avg_completeness") is not None:
        tiles.append({"key": "avg_completeness",
                      "value": round(data["avg_completeness"] or 0), "unit": "%",
                      "label_en": "Average completeness", "label_ar": "متوسط الاكتمال"})
        tiles.append({"key": "low_completeness", "value": data["low_completeness"] or 0,
                      "unit": "records", "tone": "warn",
                      "label_en": "Below 50% completeness", "label_ar": "أقل من 50% اكتمالاً"})
    tiles.append({"key": "recent", "value": data["recent"] or 0, "unit": "records",
                  "label_en": "Updated in the last 30 days", "label_ar": "حُدِّثت في آخر 30 يوماً"})
    for k in sums:
        d = derived[k]
        tiles.append({"key": k, "value": data.get("s_" + k) or 0, "unit": d.unit or "",
                      "derived": True,
                      "label_en": f"{d.label_en} (total)", "label_ar": f"{d.label_ar} (الإجمالي)"})
    return {"entity": spec.key, "tiles": tiles, "warnings": warnings}


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------
def list_records(conn: sqlite3.Connection, spec: EntitySpec, payload: dict,
                 max_page_size: int = 1000) -> dict:
    """One page of records.

    ``max_page_size`` is the guard for *interface* paging (a browser must not be
    able to ask for a million rows in one request).  Bulk readers — export, the
    report builders — pass a larger ceiling, because silently truncating an
    export is data loss.
    """
    where, params, warnings = build_where(spec, payload, conn)
    page = max(1, int(payload.get("page", 1) or 1))
    page_size = int(payload.get("page_size", 25) or 25)
    page_size = max(1, min(page_size, max(1, int(max_page_size))))
    total = conn.execute(
        f"SELECT COUNT(*) c FROM {spec.table} t WHERE {where}", params).fetchone()["c"]
    derived_cols = _derived_select(spec)
    rows = conn.execute(
        f"SELECT t.*{derived_cols} FROM {spec.table} t WHERE {where} "
        f"ORDER BY {_sort_clause(spec, payload)} LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size]).fetchall()
    lookups = load_lookup_map(conn)
    items = [_decorate(conn, spec, dict(r), lookups) for r in rows]
    out = {
        "items": items, "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "warnings": warnings,
        "columns": [f.key for f in spec.fields if f.in_list],
    }
    # a typed query reports how it was read, so the interface can echo the query
    # back and say which parts it could not honour
    if payload.get("_query"):
        out["_query"] = dict(payload["_query"], warnings=list(warnings))
    return out


def _derived_select(spec: EntitySpec, alias: str = "t") -> str:
    parts = [f", ({d.sql.replace('t.', alias + '.')}) AS \"d_{d.key}\"" for d in derived_map(spec.key).values()]
    return "".join(parts)


def _decorate(conn, spec: EntitySpec, row: dict, lookups: dict | None = None) -> dict:
    lookups = lookups if lookups is not None else load_lookup_map(conn)
    row["_labels"] = {}
    row["_refs"] = {}
    for f in spec.fields:
        val = row.get(f.key)
        if val in (None, ""):
            continue
        # vocabulary/fk values are ids, except select fields that store their code.
        # Some legacy/seeded rows keep the id in a TEXT column: accept numeric strings.
        if (not isinstance(val, int) and f.type in ("select", "fk")
                and f.store != "code" and str(val).strip().isdigit()):
            val = int(str(val).strip())
            row[f.key] = val
        if not isinstance(val, int) and not (f.type == "select" and f.store == "code"):
            continue
        if f.type == "select" and f.store == "code" and isinstance(val, str):
            lk = next((cand for cand in lookups.values()
                       if cand["domain"] == f.domain and cand["code"] == val), None)
            if lk:
                row["_labels"][f.key] = {
                    "en": lk["label_en"], "ar": lk["label_ar"], "color": lk["color"],
                    "code": lk["code"], "domain": lk["domain"],
                }
        elif f.type == "select" and val in lookups:
            lk = lookups[val]
            row["_labels"][f.key] = {
                "en": lk["label_en"], "ar": lk["label_ar"],
                "color": lk["color"], "code": lk["code"], "domain": lk["domain"],
            }
        elif f.type == "fk":
            ref = resolve_ref(conn, f.ref or "", val)
            if ref:
                row["_refs"][f.key] = ref
    # collect derived columns (selected as d_<key>) into their own namespace
    derived = {}
    dmap = derived_map(spec.key)
    for key in list(row.keys()):
        if key.startswith("d_") and key[2:] in dmap:
            derived[key[2:]] = row.pop(key)
    row["_derived"] = derived
    row["_title"] = spec.title(row)
    return row


def get_record(conn: sqlite3.Connection, spec: EntitySpec, rec_id: int,
               include_deleted: bool = False) -> dict:
    row = conn.execute(
        f"SELECT t.*{_derived_select(spec)} FROM {spec.table} t WHERE t.id=?",
        (rec_id,)).fetchone()
    if row is None or (row["deleted_at"] and not include_deleted):
        raise NotFound(f"{spec.label_en} #{rec_id} not found")
    rec = _decorate(conn, spec, dict(row))
    rec["tags"] = get_tags(conn, spec.key, rec_id)
    if spec.has_positions:
        rec["positions"] = get_positions(conn, rec_id)
    rec["relationships"] = get_relationships(conn, spec.key, rec_id)
    rec["citations"] = get_source_links(conn, spec.key, rec_id)
    rec["evidence"] = rec["citations"]            # one list, two names
    rec["evidence_summary"] = evidence_summary(conn, spec.key, rec_id)
    rec["attachments"] = get_attachments(conn, spec.key, rec_id)
    rec["history"] = get_history(conn, spec.key, rec_id, limit=100)
    return rec


def get_tags(conn, entity_type: str, entity_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT t.* FROM tag t JOIN entity_tag et ON et.tag_id = t.id
           WHERE et.entity_type=? AND et.entity_id=? ORDER BY t.domain, t.sort_order, t.id""",
        (entity_type, entity_id)).fetchall()
    return [dict(r) for r in rows]


def get_positions(conn, person_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT pp.*, i.name_en AS institution_en, i.name_ar AS institution_ar
           FROM person_position pp LEFT JOIN institution i ON i.id = pp.institution_id
           WHERE pp.person_id=? ORDER BY pp.sort_order, pp.id""", (person_id,)).fetchall()
    return [dict(r) for r in rows]


def get_relationships(conn, entity_type: str, entity_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT r.*, rt.label_en AS type_en, rt.label_ar AS type_ar,
                  rt.code AS type_code, rs.label_en AS status_en, rs.label_ar AS status_ar
           FROM relationship r
           LEFT JOIN lookup rt ON rt.id = r.relationship_type_id
           LEFT JOIN lookup rs ON rs.id = r.record_status_id
           WHERE r.deleted_at IS NULL
             AND ((r.entity1_type=? AND r.entity1_id=?) OR (r.entity2_type=? AND r.entity2_id=?))
           ORDER BY r.id DESC""",
        (entity_type, entity_id, entity_type, entity_id)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["outgoing"] = (d["entity1_type"] == entity_type and d["entity1_id"] == entity_id)
        other_type = d["entity2_type"] if d["outgoing"] else d["entity1_type"]
        other_id = d["entity2_id"] if d["outgoing"] else d["entity1_id"]
        d["other_type"], d["other_id"] = other_type, other_id
        d["other_name"] = (d["entity2_name"] if d["outgoing"] else d["entity1_name"]) or ""
        d["other_ref"] = resolve_ref(conn, other_type, other_id)
        ev = get_evidence(conn, relationship_id=d["id"])
        d["evidence"] = ev
        d["evidence_counts"] = {
            "supports": sum(1 for e in ev if e["support_type"] == "supports"),
            "contradicts": sum(1 for e in ev if e["support_type"] == "contradicts"),
            "contextualizes": sum(1 for e in ev if e["support_type"] == "contextualizes"),
        }
        d["disputed"] = d["evidence_counts"]["contradicts"] > 0
        out.append(d)
    return out


EVIDENCE_SELECT = """
    SELECT e.*, s.code AS source_code, s.title, s.title_ar, s.url, s.publisher,
           s.publication_date, s.access_date, s.archive_reference, s.isbn_issn,
           s.supported_information, s.verification_notes,
           lr.code AS reliability_code, lr.label_en AS reliability_en,
           lr.label_ar AS reliability_ar,
           lv.code AS verification_code, lv.label_en AS verification_en,
           lv.label_ar AS verification_ar,
           st.label_en AS source_type_en, st.label_ar AS source_type_ar
    FROM evidence e
    JOIN source s ON s.id = e.source_id
    LEFT JOIN lookup lr ON lr.id = s.reliability_id
    LEFT JOIN lookup lv ON lv.id = e.verification_id
    LEFT JOIN lookup st ON st.id = s.source_type_id
"""


def get_evidence(conn, entity_type: str | None = None, entity_id: int | None = None,
                 relationship_id: int | None = None) -> list[dict]:
    """Every claim a source makes about one target, richest first.

    A source's *reliability* is an assessment of the source; a claim's
    *verification* is an assessment of that claim. They are returned side by side
    and never merged, because a reliable source can still be wrong about one
    thing and an unreliable one can be right.
    """
    if relationship_id is not None:
        where, params = "e.relationship_id = ?", (int(relationship_id),)
    elif entity_type is not None and entity_id is not None:
        where, params = "e.entity_type = ? AND e.entity_id = ?", (entity_type, int(entity_id))
    else:
        raise ValueError("get_evidence needs either (entity_type, entity_id) or relationship_id")
    rows = conn.execute(
        EVIDENCE_SELECT + f" WHERE {where} ORDER BY "
        "CASE e.support_type WHEN 'contradicts' THEN 0 WHEN 'supports' THEN 1 ELSE 2 END, "
        "s.id", params).fetchall()
    return [dict(r) for r in rows]


def get_source_links(conn, entity_type: str, entity_id: int) -> list[dict]:
    """The citation list of a record — now the evidence list.

    Kept under its old name because every caller (record dossier, export,
    reports, the map) reads it here; the shape is a superset of what it was.
    """
    return get_evidence(conn, entity_type=entity_type, entity_id=entity_id)


def get_relationship_evidence(conn, relationship_id: int) -> dict:
    """Evidence for a relationship claim, plus its own verification state."""
    rel = conn.execute(
        """SELECT r.*, l.code AS type_code, l.label_en AS type_en, l.label_ar AS type_ar,
                  la.code AS auth_code, la.label_en AS auth_en, la.label_ar AS auth_ar
           FROM relationship r
           LEFT JOIN lookup l ON l.id = r.relationship_type_id
           LEFT JOIN lookup la ON la.id = r.authentication_id
           WHERE r.id = ?""", (int(relationship_id),)).fetchone()
    if rel is None:
        raise NotFound(f"Relationship #{relationship_id} not found")
    out = dict(rel)
    out["evidence"] = get_evidence(conn, relationship_id=relationship_id)
    counts = {"supports": 0, "contradicts": 0, "contextualizes": 0}
    for ev in out["evidence"]:
        counts[ev["support_type"]] = counts.get(ev["support_type"], 0) + 1
    # the same three names the /api/evidence endpoint uses, so a client that can
    # read one payload can read the other without a special case
    out["count"] = len(out["evidence"])
    out["counts"] = counts
    out["evidence_counts"] = counts
    out["disputed"] = counts["contradicts"] > 0
    return out


def _evidence_target(conn: sqlite3.Connection, row: dict) -> dict | None:
    """Where an evidence row points — the record the claim is about.

    Claims are made *about* people, places, institutions, events and whole
    relationships; a claims view that cannot say which is a bibliography,
    not an argument map.
    """
    if row.get("relationship_id"):
        rid = int(row["relationship_id"])
        rel = conn.execute(
            "SELECT entity1_type, entity1_id, entity2_type, entity2_id "
            "FROM relationship WHERE id = ?", (rid,)).fetchone()
        label = None
        if rel:
            a = resolve_ref(conn, rel["entity1_type"], rel["entity1_id"])
            b = resolve_ref(conn, rel["entity2_type"], rel["entity2_id"])
            arrow = "\u2192"
            label = f"{a['label'] if a else '?'} {arrow} {b['label'] if b else '?'}"
        return {"type": "relationship", "id": rid, "label": label or f"#{rid}"}
    etype, eid = row.get("entity_type"), row.get("entity_id")
    if etype and eid:
        ref = resolve_ref(conn, etype, int(eid))
        return {"type": etype, "id": int(eid),
                "label": (ref or {}).get("label") or f"#{int(eid)}"}
    return None


def get_claims_by_source(conn: sqlite3.Connection, source_id: int) -> list[dict]:
    """Every claim this one source makes, richest first.

    The mirror image of get_evidence: that asks 'what supports this record?',
    this asks 'what does this source say, and about what?'. A contradiction
    sits beside the supports, never instead of them — one source can well
    support one record and contradict another.
    """
    rows = conn.execute(
        EVIDENCE_SELECT + " WHERE e.source_id = ? ORDER BY "
        "CASE e.support_type WHEN 'contradicts' THEN 0 WHEN 'supports' THEN 1 ELSE 2 END, "
        "e.id", (int(source_id),)).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        row["target"] = _evidence_target(conn, row)
        out.append(row)
    return out


def evidence_summary(conn, entity_type: str, entity_id: int) -> dict:
    """Counts used by the diagram and the map: what backs this record, and is it contested."""
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN support_type='contradicts' THEN 1 ELSE 0 END) AS contradicts,
                  SUM(CASE WHEN support_type='supports' THEN 1 ELSE 0 END) AS supports,
                  SUM(CASE WHEN field_key IS NOT NULL THEN 1 ELSE 0 END) AS field_level,
                  COUNT(DISTINCT source_id) AS sources
           FROM evidence WHERE entity_type=? AND entity_id=?""",
        (entity_type, int(entity_id))).fetchone()
    d = dict(row or {})
    d = {k: int(v or 0) for k, v in d.items()}
    d["disputed"] = d.get("contradicts", 0) > 0
    return d


def get_attachments(conn, entity_type: str, entity_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM attachment WHERE entity_type=? AND entity_id=? ORDER BY id DESC",
        (entity_type, entity_id)).fetchall()
    return [dict(r) for r in rows]


def get_history(conn, entity_type: str, entity_id: int, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """SELECT cl.*, s.title AS source_title FROM change_log cl
           LEFT JOIN source s ON s.id = cl.source_id
           WHERE cl.entity_type=? AND cl.entity_id=?
           ORDER BY cl.id DESC LIMIT ?""",
        (entity_type, entity_id, limit)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------
def resolve_lookup_value(conn: sqlite3.Connection, domain: str, value: Any) -> int | None:
    """Accept a numeric id, a vocabulary code, or an English/Arabic label."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    raw = str(value).strip()
    if raw.isdigit():
        return int(raw)
    target = db.normalize(raw)
    for row in conn.execute(
            "SELECT id, code, label_en, label_ar FROM lookup WHERE domain=?", (domain,)):
        if any(db.normalize(candidate) == target for candidate in
               (row["code"], row["label_en"], row["label_ar"]) if candidate):
            return row["id"]
    return None


def _payload_values(conn: sqlite3.Connection, spec: EntitySpec,
                    data: dict) -> tuple[dict, dict[str, str]]:
    """Coerce an incoming payload; returns (values, errors)."""
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, raw in (data or {}).items():
        if key.startswith("_"):
            continue
        f = spec.field(key)
        if f is None or f.read_only or f.system:
            continue
        val, err = coerce(spec, key, raw)
        if f.type == "select" and not err and val not in (None, ""):
            resolved = resolve_lookup_value(conn, f.domain or "", val)
            if resolved is None:
                errors[key] = (f"{f.label_en}: unknown value '{val}' "
                               f"(expected an id, a code or a label from '{f.domain}')")
                continue
            if f.store == "code":
                code_row = conn.execute("SELECT code FROM lookup WHERE id=?", (resolved,)).fetchone()
                val = code_row["code"] if code_row else val
            else:
                val = resolved
        if err:
            errors[key] = err
        else:
            values[key] = val
    # required check on create is done by caller
    return values, errors


def _assert_required(spec: EntitySpec, values: dict, partial: bool = False) -> None:
    missing = []
    for f in spec.fields:
        if f.required and not f.system and f.type != "tags":
            if f.key == "code":
                continue
            if partial and f.key not in values:
                continue
            if values.get(f.key) in (None, ""):
                missing.append(f.label_en)
    if missing:
        raise ValidationError("Missing required field(s): " + ", ".join(missing))


PUBLISHED_STATUS_CODES = ("published", "verified")


def _status_code(conn: sqlite3.Connection, status_id: Any) -> str | None:
    if status_id in (None, ""):
        return None
    row = conn.execute("SELECT code FROM lookup WHERE id=?", (status_id,)).fetchone()
    return row["code"] if row else None


def _has_source(conn: sqlite3.Connection, spec: EntitySpec, values: dict,
                rec_id: int | None = None) -> bool:
    """A record is sourced when it names a primary source or carries a citation."""
    if values.get("primary_source_id"):
        return True
    if values.get("citations") or values.get("source_links"):
        return True
    if rec_id is None:
        return False
    # citations were moved into `evidence` (one source, many claims), so a record
    # is sourced when *either* store backs it; the gate must not go blind
    for table in ("evidence", "source_link"):
        if conn.execute(f"SELECT 1 FROM {table} WHERE entity_type=? AND entity_id=? LIMIT 1",
                        (spec.key, rec_id)).fetchone() is not None:
            return True
    return False


def _quality_gate(conn: sqlite3.Connection, spec: EntitySpec, values: dict,
                  rec_id: int | None = None) -> None:
    """The configurable data-quality policy, enforced on the way *in*.

    Two rules, both instance settings rather than code:
      · ``validation.require_source_on_publish`` — a record cannot enter a
        published/verified status without a citation or a primary source;
      · ``validation.min_completeness`` — publishing below the floor is refused,
        and the missing fields are named in the error.
    A record already published stays editable; the gate is about *transitions*.
    """
    status = _status_code(conn, values.get("record_status_id"))
    if status not in PUBLISHED_STATUS_CODES:
        return
    if settings_registry.get(conn, "validation.require_source_on_publish") \
            and not _has_source(conn, spec, values, rec_id):
        raise ValidationError(
            f"Cannot set {spec.label_en} to '{status}': it has no source. Attach a citation "
            f"(POST /api/{spec.key}/{{id}}/citations) or set its primary source first — "
            f"validation.require_source_on_publish is on.")
    floor = settings_registry.get(conn, "validation.min_completeness")
    if floor and rec_id is not None:
        pct = _completeness(conn, spec, {"id": rec_id})
        if pct is not None and pct < floor:
            raise ValidationError(
                f"Cannot set {spec.label_en} #{rec_id} to '{status}': completeness is "
                f"{pct}% and validation.min_completeness requires {floor}%.")


def _require_reason(conn: sqlite3.Connection, reason: str | None, what: str) -> None:
    if settings_registry.get(conn, "validation.require_reason_for_delete") \
            and not (reason or "").strip():
        raise ValidationError(
            f"A reason is required to {what} — validation.require_reason_for_delete is on.")


def _unique_code(conn, spec: EntitySpec, code: str, exclude_id: int | None = None) -> None:
    row = conn.execute(f"SELECT id FROM {spec.table} WHERE code=? AND id IS NOT ?",
                       (code, exclude_id or -1)).fetchone()
    if row:
        raise Conflict(f"Identification number '{code}' is already in use")


# A location is a coordinate pair. These foreign keys are the place that pair
# is stored on; a name in that place's label is not a position.
_LOCATION_FK = {"person": "birthplace_id", "institution": "place_id", "event": "place_id"}
_PARTICIPANT_TYPES = ("had_participant", "participated_in")


def _coordinate_pair(lat, lon) -> dict | None:
    """Both ends, or nothing. A single number is not a location."""
    from .geo import spatial
    has_lat = lat is not None and lat != ""
    has_lon = lon is not None and lon != ""
    if not has_lat and not has_lon:
        return None
    if has_lat != has_lon:
        raise ValidationError(
            "A location needs both latitude and longitude. "
            "Type the pair, or pick the point on the map — a place name is not a coordinate.")
    check = spatial.validate_pair(lat, lon)
    if not check["ok"]:
        raise ValidationError(check["problems"][0]["message"])
    return check


def _same_point(a_lat, a_lon, b_lat, b_lon) -> bool:
    return abs(float(a_lat) - float(b_lat)) < 1e-5 and abs(float(a_lon) - float(b_lon)) < 1e-5


def _method_id(conn, code: str) -> int | None:
    return (_lookup_id(conn, "geocoding_method", code)
            or _lookup_id(conn, "geocoding_method", "manual"))


def _read_location(data: dict | None) -> dict | None:
    """The explicit point on a write, if the caller sent one.

    A name, a label or a search string is refused: those do not locate anything.
    """
    loc = (data or {}).get("_location")
    if not isinstance(loc, dict):
        return None
    lat = loc.get("lat", loc.get("latitude"))
    lon = loc.get("lon", loc.get("lng", loc.get("longitude")))
    named = any(str(loc.get(k) or "").strip() for k in ("name", "label", "q", "place_name"))
    if (lat is None or lat == "") and (lon is None or lon == ""):
        if named:
            raise ValidationError(
                "A place name is not a location. Type exact coordinates or pick a point on the map.")
        return None
    check = _coordinate_pair(lat, lon)
    method = str(loc.get("method") or "coordinate_entry")
    if method not in ("map_pick", "coordinate_entry", "manual"):
        method = "coordinate_entry"
    return {"lat": check["lat"], "lon": check["lon"], "method": method}


def _place_row(conn, place_id: int):
    return conn.execute(
        "SELECT id, latitude, longitude FROM place WHERE id=? AND deleted_at IS NULL",
        (int(place_id),)).fetchone()


def _apply_precise_location(conn, spec: EntitySpec, data: dict, values: dict,
                            before: dict | None, actor: str, reason: str | None) -> None:
    """Store a location only as a validated coordinate pair.

    On a place, the pair is the place's own latitude and longitude. On a
    person, institution or event, the pair is the record's own position,
    written to the record's own columns. It is never written onto the linked
    place and never synthesized into a coordinate-named place: linking is
    association, not assignment. Several records associated with one named
    place keep several distinct points, and none of them moves the place.
    """
    if spec.key == "place":
        lat = values["latitude"] if "latitude" in values else (before or {}).get("latitude")
        lon = values["longitude"] if "longitude" in values else (before or {}).get("longitude")
        point = _read_location(data)
        if point:
            lat, lon = point["lat"], point["lon"]
            values["latitude"] = lat
            values["longitude"] = lon
            values["geo_precision"] = values.get("geo_precision") or _lookup_id(conn, "geo_precision", "exact")
            values["geocoding_method"] = (values.get("geocoding_method")
                                           or _method_id(conn, point["method"]))
            if not values.get("geometry_source"):
                values["geometry_source"] = ("map pick" if point["method"] == "map_pick"
                                             else "typed coordinates")
        pair = _coordinate_pair(lat, lon)
        if pair and not values.get("geo_precision"):
            fresh = before is None or not _same_point(
                (before or {}).get("latitude") if (before or {}).get("latitude") is not None else pair["lat"],
                (before or {}).get("longitude") if (before or {}).get("longitude") is not None else pair["lon"],
                pair["lat"], pair["lon"])
            if fresh or (before or {}).get("latitude") is None:
                values["geo_precision"] = _lookup_id(conn, "geo_precision", "exact")
                if not values.get("geocoding_method"):
                    values["geocoding_method"] = _method_id(
                        conn, point["method"] if point else "coordinate_entry")
                if not values.get("geometry_source"):
                    values["geometry_source"] = ("map pick" if point and point["method"] == "map_pick"
                                                 else "typed coordinates")
        return

    # Person, institution or event: the explicit point belongs to THIS record.
    # A name passed as a location is still refused — a name alone registers
    # nothing — but the point, when given, is the record's own.
    point = _read_location(data)
    if point:
        values["latitude"] = point["lat"]
        values["longitude"] = point["lon"]
        values["geo_precision"] = (values.get("geo_precision")
                                   or _lookup_id(conn, "geo_precision", "exact"))
        values["geocoding_method"] = (values.get("geocoding_method")
                                      or _method_id(conn, point["method"]))
        if not values.get("geometry_source"):
            values["geometry_source"] = ("map pick" if point["method"] == "map_pick"
                                         else "typed coordinates")
    # Both ends or nothing — the same rule the place branch enforces. Typed
    # field values go through it too, so no coordinate write can leave half a
    # pair behind (a write that touches neither axis leaves legacy rows alone).
    if point or "latitude" in values or "longitude" in values:
        lat = values["latitude"] if "latitude" in values else (before or {}).get("latitude")
        lon = values["longitude"] if "longitude" in values else (before or {}).get("longitude")
        _coordinate_pair(lat, lon)
    # Linking a place is an association: the place is not required to carry
    # coordinates, and its coordinates are never copied onto this record.
    fk = _LOCATION_FK.get(spec.key)
    if fk and fk in values and values.get(fk) not in (None, ""):
        if _place_row(conn, int(values[fk])) is None:
            raise ValidationError("The linked place does not exist.")


def _sync_event_participants(conn, spec: EntitySpec, rec_id: int, data: dict,
                             actor: str, reason: str | None) -> None:
    """People and organizations on an event, stored as real relationships.

    Only the participant link types are rewritten. Every other relationship on
    the event is left where it is.
    """
    if spec.key != "event" or "_participants" not in (data or {}):
        return
    raw = data.get("_participants")
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ValidationError("Participants must be a list of people and organizations.")
    wanted: list[tuple[str, int]] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("Each participant needs a type and a record id.")
        etype = str(item.get("entity_type") or item.get("type") or "").strip()
        eid = item.get("entity_id", item.get("id"))
        if etype not in ("person", "institution"):
            raise ValidationError("Event participants are people or organizations.")
        try:
            eid = int(eid)
        except (TypeError, ValueError):
            raise ValidationError("Each participant needs a record id.") from None
        other = ENTITIES[etype]
        if conn.execute(f"SELECT 1 FROM {other.table} WHERE id=? AND deleted_at IS NULL",
                        (eid,)).fetchone() is None:
            raise ValidationError(f"{other.label_en} #{eid} was not found.")
        key = (etype, eid)
        if key not in seen:
            seen.add(key)
            wanted.append(key)

    type_ids = [i for i in (_lookup_id(conn, "relationship_type", c) for c in _PARTICIPANT_TYPES) if i]
    if not type_ids:
        raise ValidationError("The participant relationship type is not in the vocabulary.")
    marks = ",".join("?" * len(type_ids))
    rows = conn.execute(
        "SELECT id, entity1_type, entity1_id, entity2_type, entity2_id, relationship_type_id "
        f"FROM relationship WHERE deleted_at IS NULL AND relationship_type_id IN ({marks}) "
        "AND ((entity1_type='event' AND entity1_id=?) OR (entity2_type='event' AND entity2_id=?))",
        (*type_ids, rec_id, rec_id)).fetchall()
    still = set(wanted)
    for row in rows:
        if row["entity1_type"] == "event" and int(row["entity1_id"]) == rec_id:
            other = (row["entity2_type"], int(row["entity2_id"]))
        else:
            other = (row["entity1_type"], int(row["entity1_id"]))
        if other[0] not in ("person", "institution"):
            continue
        if other in still:
            still.discard(other)
            continue
        ts = db.now()
        conn.execute(
            "UPDATE relationship SET deleted_at=?, updated_at=?, updated_by=?, version=version+1 "
            "WHERE id=?", (ts, ts, actor, row["id"]))
        db.log_change(conn, entity_type="relationship", entity_id=row["id"], action="delete",
                      actor=actor, reason=reason or "participant removed",
                      notes="removed from the event")
        db.drop_from_index(conn, "relationship", row["id"])

    event = conn.execute("SELECT title_en, title_ar, code FROM event WHERE id=?", (rec_id,)).fetchone()
    event_name = (event["title_en"] or event["title_ar"] or event["code"]) if event else f"#{rec_id}"
    for etype, eid in still:
        other = ENTITIES[etype]
        row = conn.execute(f"SELECT * FROM {other.table} WHERE id=?", (eid,)).fetchone()
        other_name = other.title(dict(row)) if row else f"#{eid}"
        create_record(conn, ENTITIES["relationship"], {
            "entity1_type": "event",
            "entity1_id": rec_id,
            "entity1_name": event_name,
            "entity2_type": etype,
            "entity2_id": eid,
            "entity2_name": other_name,
            "relationship_type_id": "had_participant",
            "direction": "directed",
            "description": "Participant of the event.",
        }, actor=actor, reason=reason or "participant linked", commit=False)


def create_record(conn: sqlite3.Connection, spec: EntitySpec, data: dict,
                  actor: str = "researcher", reason: str | None = None,
                  source_id: int | None = None, commit: bool = True) -> dict:
    values, errors = _payload_values(conn, spec, data)
    # the status of a new record defaults to "draft" so the API never requires it
    if not values.get("record_status_id"):
        values["record_status_id"] = _lookup_id(conn, "record_status", "draft")
    if errors:
        raise ValidationError(errors)
    _apply_precise_location(conn, spec, data or {}, values, None, actor, reason)
    _assert_required(spec, values)
    _quality_gate(conn, spec, values)
    supplied_code = (data or {}).get("code")
    code = supplied_code or db.next_code(conn, spec.key)
    if supplied_code:
        db.sync_sequence(conn, spec.key, supplied_code)
    if errors:
        raise ValidationError(errors)
    _unique_code(conn, spec, code)
    ts = db.now()
    values["code"] = code
    values["created_at"] = ts
    values["updated_at"] = ts
    values["created_by"] = actor
    values["updated_by"] = actor
    values["version"] = 1
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    try:
        cur = conn.execute(f"INSERT INTO {spec.table} ({cols}) VALUES ({marks})",
                           list(values.values()))
    except sqlite3.IntegrityError as exc:
        msg = str(exc)
        if "UNIQUE" in msg.upper():
            raise Conflict("This combination already exists (unique constraint): "
                           + msg.split(":")[-1].strip()) from exc
        raise ValidationError(f"Database rejected the record: {msg}") from exc
    rec_id = int(cur.lastrowid)
    db.log_change(conn, entity_type=spec.key, entity_id=rec_id, action="create",
                  actor=actor, entity_code=code, reason=reason, source_id=source_id,
                  notes="record created")
    for f in spec.fields:
        if f.type == "select" and values.get(f.key):
            pass
    _set_tags(conn, spec, rec_id, (data or {}).get("tags"))
    if spec.has_positions and (data or {}).get("positions"):
        _replace_positions(conn, rec_id, data["positions"])
    _sync_event_participants(conn, spec, rec_id, data or {}, actor, reason)
    _index_record(conn, spec, rec_id)
    if commit:
        conn.commit()
    return get_record(conn, spec, rec_id)


def update_record(conn: sqlite3.Connection, spec: EntitySpec, rec_id: int, data: dict,
                  actor: str = "researcher", reason: str | None = None,
                  source_id: int | None = None,
                  expected_version: int | None = None, commit: bool = True) -> dict:
    current = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (rec_id,)).fetchone()
    if current is None or current["deleted_at"]:
        raise NotFound(f"{spec.label_en} #{rec_id} not found")
    before = dict(current)
    if expected_version is not None and int(expected_version) != int(before["version"]):
        raise Conflict(
            f"Record was modified by someone else (your version {expected_version}, "
            f"current version {before['version']}). Reload and retry.")
    values, errors = _payload_values(conn, spec, data)
    if errors:
        raise ValidationError(errors)
    _apply_precise_location(conn, spec, data or {}, values, before, actor, reason)
    if "code" in (data or {}) and data["code"]:
        _unique_code(conn, spec, str(data["code"]).strip(), exclude_id=rec_id)
        values["code"] = str(data["code"]).strip()
    # policy applies to the state the record is about to have, not to the patch
    _quality_gate(conn, spec, {**before, **values}, rec_id=rec_id)
    values["updated_at"] = db.now()
    values["updated_by"] = actor
    values["version"] = int(before["version"]) + 1
    sets = ", ".join(f"{k}=?" for k in values)
    conn.execute(f"UPDATE {spec.table} SET {sets} WHERE id=?", list(values.values()) + [rec_id])
    # one transaction id for the whole edit: a form that changes five fields is one
    # act of editing, and the history should be able to say so
    tx = uuid.uuid4().hex
    changed = db.diff_and_log(
        conn, entity_type=spec.key, entity_id=rec_id, entity_code=values.get("code", before["code"]),
        before=before, after=values, labels=spec.labels("en"), actor=actor,
        reason=reason, source_id=source_id, tx_id=tx)
    if (data or {}).get("tags") is not None:
        _set_tags(conn, spec, rec_id, data["tags"])
    _sync_event_participants(conn, spec, rec_id, data or {}, actor, reason)
    if spec.has_positions and (data or {}).get("positions") is not None:
        current_positions = get_positions(conn, rec_id) if spec.key == "person" else []
        _replace_positions(conn, rec_id, data["positions"])
        db.log_change(conn, entity_type=spec.key, entity_id=rec_id, action="update",
                      actor=actor, entity_code=values.get("code", before["code"]),
                      field_key="positions", field_label="Previous positions",
                      old_value=f"{len(current_positions)} entries",
                      new_value=f"{len(data['positions'])} entries",
                      reason=reason, source_id=source_id, tx_id=tx)
    _index_record(conn, spec, rec_id)
    if commit:
        conn.commit()
    rec = get_record(conn, spec, rec_id)
    rec["_changes"] = changed
    return rec


def soft_delete(conn, spec: EntitySpec, rec_id: int, actor: str = "researcher",
                reason: str | None = None) -> dict:
    _require_reason(conn, reason, "delete a record")
    row = conn.execute(f"SELECT * FROM {spec.table} WHERE id=? AND deleted_at IS NULL",
                       (rec_id,)).fetchone()
    if row is None:
        raise NotFound(f"{spec.label_en} #{rec_id} not found")
    ts = db.now()
    conn.execute(f"UPDATE {spec.table} SET deleted_at=?, updated_at=?, updated_by=?, "
                 f"version=version+1 WHERE id=?", (ts, ts, actor, rec_id))
    db.log_change(conn, entity_type=spec.key, entity_id=rec_id, action="delete",
                  actor=actor, entity_code=row["code"], reason=reason,
                  notes="soft delete (recoverable)")
    db.drop_from_index(conn, spec.key, rec_id)
    conn.commit()
    return {"ok": True, "id": rec_id, "deleted_at": ts}


def restore(conn, spec: EntitySpec, rec_id: int, actor: str = "researcher") -> dict:
    row = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (rec_id,)).fetchone()
    if row is None:
        raise NotFound(f"{spec.label_en} #{rec_id} not found")
    conn.execute(f"UPDATE {spec.table} SET deleted_at=NULL, updated_at=?, updated_by=?, "
                 f"version=version+1 WHERE id=?", (db.now(), actor, rec_id))
    db.log_change(conn, entity_type=spec.key, entity_id=rec_id, action="restore",
                  actor=actor, entity_code=row["code"])
    _index_record(conn, spec, rec_id)
    conn.commit()
    return {"ok": True, "id": rec_id}


def hard_delete(conn, spec: EntitySpec, rec_id: int, actor: str = "admin",
                reason: str | None = None) -> dict:
    """Remove a record *and* everything that only exists because of it.

    A hard delete used to switch foreign keys off and remove the row, which left
    the polymorphic tables (relationship, entity_tag, source_link, attachment,
    entity_external_id) pointing at nothing — the interface then showed citations
    and tags belonging to a record that no longer existed.  Everything is now
    removed explicitly, and every table that took part is reported back so the
    caller can see the blast radius.
    """
    _require_reason(conn, reason, "destroy a record for good")
    row = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (rec_id,)).fetchone()
    if row is None:
        raise NotFound(f"{spec.label_en} #{rec_id} not found")

    removed: dict[str, int] = {}

    def purge(table: str, where: str, params: tuple) -> None:
        cur = conn.execute(f"DELETE FROM {table} WHERE {where}", params)
        if cur.rowcount:
            removed[table] = removed.get(table, 0) + cur.rowcount

    # 1 · polymorphic dependents (no foreign key can cascade these)
    for table in ("entity_tag", "source_link", "evidence", "attachment",
                  "entity_external_id"):
        purge(table, "entity_type=? AND entity_id=?", (spec.key, rec_id))
    # relationships are indexed too, so their documents must go with them
    rel_ids = [r[0] for r in conn.execute(
        "SELECT id FROM relationship WHERE (entity1_type=? AND entity1_id=?) "
        "OR (entity2_type=? AND entity2_id=?)", (spec.key, rec_id, spec.key, rec_id))]
    purge("relationship", "(entity1_type=? AND entity1_id=?) OR (entity2_type=? AND entity2_id=?)",
          (spec.key, rec_id, spec.key, rec_id))
    for rid in rel_ids:
        db.drop_from_index(conn, "relationship", rid)
    if rel_ids:
        removed["relationship_index"] = len(rel_ids)

    # 2 · typed children
    if spec.key == "person":
        purge("person_position", "person_id=?", (rec_id,))
    if spec.key == "institution":
        conn.execute("UPDATE person SET affiliated_institution_id=NULL "
                     "WHERE affiliated_institution_id=?", (rec_id,))
        conn.execute("UPDATE person_position SET institution_id=NULL WHERE institution_id=?",
                     (rec_id,))
    if spec.key == "place":
        conn.execute("UPDATE place SET parent_place_id=NULL WHERE parent_place_id=?", (rec_id,))
        conn.execute("UPDATE person SET birthplace_id=NULL WHERE birthplace_id=?", (rec_id,))
        conn.execute("UPDATE institution SET place_id=NULL WHERE place_id=?", (rec_id,))
        conn.execute("UPDATE event SET place_id=NULL WHERE place_id=?", (rec_id,))
    if spec.key == "source":
        conn.execute("UPDATE place SET primary_source_id=NULL WHERE primary_source_id=?",
                     (rec_id,))
        conn.execute("UPDATE institution SET primary_source_id=NULL WHERE primary_source_id=?",
                     (rec_id,))
        conn.execute("UPDATE person SET primary_source_id=NULL WHERE primary_source_id=?",
                     (rec_id,))
        conn.execute("UPDATE event SET primary_source_id=NULL WHERE primary_source_id=?", (rec_id,))
        conn.execute("UPDATE relationship SET source_id=NULL WHERE source_id=?", (rec_id,))
        conn.execute("UPDATE change_log SET source_id=NULL WHERE source_id=?", (rec_id,))

    # 3 · the record itself; FK rules clean up anything left (e.g. tag links)
    conn.execute(f"DELETE FROM {spec.table} WHERE id=?", (rec_id,))
    conn.execute("DELETE FROM search_doc WHERE entity_type=? AND entity_id=?",
                 (spec.key, rec_id))
    db.log_change(conn, entity_type=spec.key, entity_id=rec_id, action="delete",
                  actor=actor, entity_code=row["code"], reason=reason,
                  notes="HARD DELETE (record removed permanently)"
                        + (f"; dependents removed: {json.dumps(removed, sort_keys=True)}"
                           if removed else ""))
    conn.commit()
    return {"ok": True, "id": rec_id, "hard": True, "dependents_removed": removed}


def bulk_action(conn, spec: EntitySpec, ids: Sequence[int], action: str,
                patch: dict | None = None, actor: str = "researcher",
                reason: str | None = None) -> dict:
    results = {"ok": 0, "failed": 0, "errors": []}
    for rid in ids:
        try:
            if action == "delete":
                soft_delete(conn, spec, int(rid), actor, reason)
            elif action == "restore":
                restore(conn, spec, int(rid), actor)
            elif action == "update":
                update_record(conn, spec, int(rid), patch or {}, actor, reason)
            elif action == "status":
                update_record(conn, spec, int(rid),
                              {"record_status_id": (patch or {}).get("record_status_id")},
                              actor, reason, expected_version=None)
            else:
                raise ValidationError(f"Unknown bulk action '{action}'")
            results["ok"] += 1
        except RepoError as exc:
            results["failed"] += 1
            results["errors"].append({"id": rid, "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# children
# ---------------------------------------------------------------------------
def _replace_positions(conn, person_id: int, positions: Iterable[dict]) -> None:
    conn.execute("DELETE FROM person_position WHERE person_id=?", (person_id,))
    for i, p in enumerate(positions or []):
        if not isinstance(p, dict):
            continue
        conn.execute(
            """INSERT INTO person_position (person_id, title_ar, title_en, institution_id,
                 institution_text, country_id, place_id, start_date, end_date,
                 start_precision, end_precision, is_current, sort_order, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (person_id, p.get("title_ar"), p.get("title_en"), _int(p.get("institution_id")),
             p.get("institution_text"), _int(p.get("country_id")), _int(p.get("place_id")),
             p.get("start_date"), p.get("end_date"), _int(p.get("start_precision")),
             _int(p.get("end_precision")), 1 if p.get("is_current") else 0,
             int(p.get("sort_order") or (i + 1) * 10), p.get("notes"), db.now(), db.now()))


def _set_tags(conn, spec: EntitySpec, rec_id: int, tags) -> None:
    if tags is None:
        return
    conn.execute("DELETE FROM entity_tag WHERE entity_type=? AND entity_id=?",
                 (spec.key, rec_id))
    for t in tags:
        tid = None
        if isinstance(t, dict):
            label_en = t.get("label_en") or t.get("label")
            domain = t.get("domain") or (spec.tags[0] if spec.tags else "keyword")
            if t.get("id"):
                tid = int(t["id"])
            elif label_en:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO tag (domain, label_en, label_ar) VALUES (?,?,?)",
                    (domain, label_en, t.get("label_ar")))
                tid = cur.lastrowid or conn.execute(
                    "SELECT id FROM tag WHERE domain=? AND label_en=?",
                    (domain, label_en)).fetchone()["id"]
        elif isinstance(t, int) or (isinstance(t, str) and str(t).isdigit()):
            tid = int(t)
        elif isinstance(t, str) and t.strip():
            domain = spec.tags[0] if spec.tags else "keyword"
            cur = conn.execute(
                "INSERT OR IGNORE INTO tag (domain, label_en) VALUES (?,?)", (domain, t.strip()))
            tid = cur.lastrowid or conn.execute(
                "SELECT id FROM tag WHERE domain=? AND label_en=?",
                (domain, t.strip())).fetchone()["id"]
        if tid:
            conn.execute("INSERT OR IGNORE INTO entity_tag VALUES (?,?,?)",
                         (spec.key, rec_id, tid))


SUPPORT_TYPES = ("supports", "contradicts", "contextualizes")


def _auth_id(conn, code: str | None) -> int | None:
    """Resolve an authentication_level code to its lookup id (None stays None)."""
    if not code:
        return None
    row = conn.execute(
        "SELECT id FROM lookup WHERE domain='authentication_level' AND code=?",
        (str(code),)).fetchone()
    if row is None:
        raise ValidationError(f"Unknown verification level '{code}'")
    return int(row["id"])


def _source_exists(conn, source_id: int) -> None:
    if conn.execute("SELECT 1 FROM source WHERE id=? AND deleted_at IS NULL",
                    (int(source_id),)).fetchone() is None:
        raise NotFound(f"Source #{source_id} not found")


def add_evidence(conn, source_id: int, *, entity_type: str | None = None,
                 entity_id: int | None = None, relationship_id: int | None = None,
                 field_key: str | None = None, supported_claim: str | None = None,
                 page_or_timestamp: str | None = None, support_type: str = "supports",
                 verification: str | None = None, reviewer: str | None = None,
                 review_date: str | None = None, note: str | None = None,
                 actor: str = "researcher") -> dict:
    """Link a source to one claim — about an entity, a field of one, or a relationship.

    Contradictory evidence is first-class: adding a `contradicts` row beside a
    `supports` row is how disagreement is recorded. Nothing is overwritten.
    """
    support = str(support_type or "supports").lower()
    if support not in SUPPORT_TYPES:
        raise ValidationError(f"support_type must be one of {', '.join(SUPPORT_TYPES)}")
    if (relationship_id is None) == (entity_id is None):
        raise ValidationError(
            "Evidence needs exactly one target: relationship_id, or entity_type with entity_id")
    _source_exists(conn, source_id)

    verification_id = _auth_id(conn, verification)
    if reviewer and not review_date:
        review_date = dt.utcnow().isoformat(timespec="seconds") + "Z"

    if relationship_id is not None:
        rel = conn.execute("SELECT id, entity1_type, entity1_id, entity2_type, entity2_id "
                           "FROM relationship WHERE id=?", (int(relationship_id),)).fetchone()
        if rel is None:
            raise NotFound(f"Relationship #{relationship_id} not found")
        cur = conn.execute(
            """INSERT OR IGNORE INTO evidence
                 (source_id, relationship_id, field_key, supported_claim, page_or_timestamp,
                  support_type, verification_id, reviewer, review_date, notes,
                  created_by, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(source_id), int(relationship_id), field_key, supported_claim,
             page_or_timestamp, support, verification_id, reviewer, review_date, note,
             actor, actor))
        db.log_change(conn, entity_type="relationship", entity_id=int(relationship_id),
                      action="update", actor=actor, field_key="evidence",
                      field_label="Evidence link",
                      new_value=f"source #{source_id} ({support})", notes=note)
        target = {"relationship_id": int(relationship_id)}
    else:
        spec = ENTITIES.get(entity_type)
        if spec is None:
            raise ValidationError(f"Unknown entity type '{entity_type}'")
        if conn.execute(f"SELECT 1 FROM {spec.table} WHERE id=?",
                        (int(entity_id),)).fetchone() is None:
            raise NotFound(f"{spec.label_en} #{entity_id} not found")
        cur = conn.execute(
            """INSERT OR IGNORE INTO evidence
                 (source_id, entity_type, entity_id, field_key, supported_claim,
                  page_or_timestamp, support_type, verification_id, reviewer, review_date,
                  notes, created_by, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(source_id), spec.key, int(entity_id), field_key, supported_claim,
             page_or_timestamp, support, verification_id, reviewer, review_date, note,
             actor, actor))
        db.log_change(conn, entity_type=spec.key, entity_id=int(entity_id),
                      action="update", actor=actor, field_key="evidence",
                      field_label="Evidence link",
                      new_value=f"source #{source_id} ({support})", notes=note)
        target = {"entity_type": spec.key, "entity_id": int(entity_id)}

    conn.commit()
    listed = get_evidence(conn, **target)
    added = next((e for e in listed if e["source_id"] == int(source_id)
                  and e["support_type"] == support
                  and (e.get("field_key") or "") == (field_key or "")), None)
    return {"ok": True, "evidence_id": added["id"] if added else None,
            "created": bool(cur.rowcount), "evidence": added}


def add_source_link(conn, entity_type: str, entity_id: int, source_id: int,
                    note: str | None = None, field_key: str | None = None,
                    actor: str = "researcher", **extra) -> dict:
    """Backwards-compatible wrapper — a plain supporting citation."""
    out = add_evidence(conn, source_id, entity_type=entity_type, entity_id=entity_id,
                       field_key=field_key, note=note, actor=actor, **extra)
    return {"ok": True, **out}


def remove_source_link(conn, link_id: int, actor: str = "researcher") -> dict:
    """Withdraw one evidence link. The source record itself is never touched."""
    row = conn.execute("SELECT * FROM evidence WHERE id=?", (link_id,)).fetchone()
    if not row:
        raise NotFound("Evidence link not found")
    conn.execute("DELETE FROM evidence WHERE id=?", (link_id,))
    if row["relationship_id"] is not None:
        db.log_change(conn, entity_type="relationship", entity_id=row["relationship_id"],
                      action="update", actor=actor, field_key="evidence",
                      field_label="Evidence link", old_value=f"source #{row['source_id']}",
                      notes="evidence withdrawn")
    else:
        db.log_change(conn, entity_type=row["entity_type"], entity_id=row["entity_id"],
                      action="update", actor=actor, field_key="evidence",
                      field_label="Evidence link", old_value=f"source #{row['source_id']}",
                      notes="evidence withdrawn")
    conn.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------
def _index_record(conn, spec: EntitySpec, rec_id: int) -> None:
    row = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (rec_id,)).fetchone()
    if row is None:
        return
    d = dict(row)
    if d.get("deleted_at"):
        db.drop_from_index(conn, spec.key, rec_id)
        return
    body = [d.get(f.key) for f in spec.fields
            if f.multisearch and f.type in ("text", "textarea", "url")]
    body += [v["en"] for v in _decorate(conn, spec, dict(d)).get("_labels", {}).values()]
    body += [r["label"] for r in _decorate(conn, spec, dict(d)).get("_refs", {}).values()]
    if spec.has_positions and spec.key == "person":
        body += [p["title_en"] or p["title_ar"] for p in get_positions(conn, rec_id)]
    db.reindex(conn, spec.key, rec_id, spec.title(d), body, d.get("code"))


# ---------------------------------------------------------------------------
# options for pickers / filters
# ---------------------------------------------------------------------------
def lookup_options(conn, domain: str | None = None, include_inactive: bool = False,
                   parent_id: int | None = None, q: str | None = None,
                   limit: int | None = None, offset: int = 0) -> dict:
    """Lookup rows grouped by domain (flat when `domain` is given).

    Hierarchical selection contract: pass `parent_id` to receive ONLY the direct
    children of that unit — the server enforces the cascade, callers cannot see
    siblings of other branches.  `q` filters code/labels; `limit`/`offset` page.
    """
    sql = "SELECT * FROM lookup WHERE 1=1"
    params: list[Any] = []
    if domain:
        sql += " AND domain=?"
        params.append(domain)
    if parent_id is not None:
        sql += " AND parent_id=?"
        params.append(int(parent_id))
    if q:
        sql += (" AND (lower(code) LIKE ? OR lower(label_en) LIKE ? OR lower(label_ar) LIKE ?)")
        like = f"%{q.lower()}%"
        params.extend([like, like, like])
    if not include_inactive:
        sql += " AND is_active=1"
    sql += " ORDER BY domain, sort_order, id"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    rows = conn.execute(sql, params).fetchall()
    out: dict[str, list] = {}
    for r in rows:
        d = dict(r)
        d["meta"] = db.json_load(d.get("meta"), {})
        out.setdefault(d["domain"], []).append(d)
    return out


def ref_options(conn, entity: str, q: str | None = None, limit: int = 50,
                country_id: int | None = None,
                place_types: Sequence[str] | None = None) -> list[dict]:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise ValidationError(f"Unknown entity '{entity}'")
    sql = f"SELECT id, code, * FROM {spec.table} WHERE deleted_at IS NULL"
    params: list[Any] = []
    if entity == "place" and country_id:
        sql += " AND country_id=?"
        params.append(int(country_id))
    if entity == "place" and place_types:
        codes = [c for c in place_types if c]
        if codes:
            marks = ",".join("?" * len(codes))
            sql += (f" AND place_type_id IN (SELECT id FROM lookup "
                    f"WHERE domain='place_type' AND code IN ({marks}))")
            params.extend(codes)
    if q:
        sql += " AND id IN (SELECT entity_id FROM search_doc WHERE search_doc MATCH ? AND entity_type=?)"
        params += [db.fts_query(q), spec.key]
    sql += " ORDER BY id LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    return [{"id": r["id"], "code": r["code"], "label": spec.title(dict(r))} for r in rows]


def _lookup_id(conn, domain: str, code: str) -> int | None:
    row = conn.execute("SELECT id FROM lookup WHERE domain=? AND code=?", (domain, code)).fetchone()
    return row["id"] if row else None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# duplicate detection and merging
# ---------------------------------------------------------------------------
NAME_COLUMNS = {
    "person": ("name_ar", "name_en"),
    "institution": ("name_ar", "name_en"),
    "place": ("name_ar", "name_en"),
    "source": ("title", "title_ar"),
    "event": ("title_ar", "title_en"),
    "relationship": ("entity1_name", "entity2_name"),
}


def duplicate_groups(conn: sqlite3.Connection, spec: EntitySpec, limit: int = 50,
                     offset: int = 0) -> tuple[list[dict], int]:
    """Groups of live records whose normalised name collides — paged, in SQL.

    Grouping happens in the database: ``norm()`` folds Arabic orthography (see
    ``app/db.py``), ``GROUP BY … HAVING COUNT(*) > 1`` finds the collisions and a
    single ``COUNT(*)`` over that grouping returns the total.  The Python version
    this replaced read every row and rebuilt the index in memory (460 ms+ for
    persons); this is ~190 ms and stays flat as the table grows.

    Returns ``(groups, total)`` where a group is
    ``{key, count, records:[{id, code, title, updated_at, completeness, deleted_at}]}``.
    """
    cols = NAME_COLUMNS.get(spec.key, ())
    if not cols:
        return ([], 0)
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))
    name_expr = "COALESCE(" + ", ".join(f"t.{c}" for c in cols) + ")"
    base = (f"FROM {spec.table} t WHERE t.deleted_at IS NULL "
            f"AND {name_expr} IS NOT NULL AND TRIM({name_expr}) <> ''")

    keyed = f"SELECT norm({name_expr}) AS nkey, COUNT(*) AS members {base} GROUP BY 1"
    total = conn.execute(f"SELECT COUNT(*) c FROM ({keyed} HAVING members > 1)").fetchone()["c"]
    if not total:
        return ([], 0)
    page = conn.execute(
        f"SELECT nkey, members FROM ({keyed} HAVING members > 1) ORDER BY nkey LIMIT ? OFFSET ?",
        (limit, offset)).fetchall()
    keys = [r["nkey"] for r in page if r["nkey"]]
    if not keys:
        return ([], total)
    marks = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT t.* {base} AND norm({name_expr}) IN ({marks}) ORDER BY norm({name_expr}), t.id",
        keys).fetchall()
    buckets: dict[str, list[dict]] = {k: [] for k in keys}
    for r in rows:
        d = dict(r)
        key = db.normalize(next((d.get(c) for c in cols if d.get(c)), "") or "")
        if key not in buckets:
            continue
        buckets[key].append({
            "id": d["id"], "code": d["code"], "title": spec.title(d),
            "updated_at": d.get("updated_at"),
            "completeness": _completeness(conn, spec, d),
            "deleted_at": d.get("deleted_at"),
        })
    groups = [{"key": k, "count": len(v), "records": v} for k, v in buckets.items() if v]
    groups.sort(key=lambda g: (-g["count"], g["key"]))
    return (groups, total)


def _completeness(conn, spec: EntitySpec, row: dict) -> int | None:
    """Completeness of one record when the entity derives it, else ``None``."""
    d = derived_map(spec.key).get("completeness")
    if d is None:
        return None
    try:
        got = conn.execute(f"SELECT ({d.sql}) AS c FROM {spec.table} t WHERE t.id=?",
                           (row["id"],)).fetchone()
    except sqlite3.Error:
        return None
    return got["c"] if got else None


def find_duplicates(conn: sqlite3.Connection, spec: EntitySpec, limit: int = 50) -> list[dict]:
    """Backwards-compatible list-only wrapper around :func:`duplicate_groups`."""
    return duplicate_groups(conn, spec, limit=limit)[0]


MERGE_TABLES = ("source_link", "evidence", "entity_tag", "entity_external_id",
                "attachment")


def merge_records(conn: sqlite3.Connection, spec: EntitySpec, keep_id: int,
                  merge_ids: Sequence[int], actor: str = "reviewer",
                  reason: str | None = None, dry_run: bool = False) -> dict:
    """Merge duplicates into `keep_id`: move links, fill empty fields, soft-delete.

    The merged records are *kept* (soft-deleted, recoverable) and every step is
    written to the audit trail, so a merge is reviewable and reversible.
    """
    _require_reason(conn, reason, "merge records")
    keep = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (keep_id,)).fetchone()
    if keep is None or keep["deleted_at"]:
        raise NotFound(f"{spec.label_en} #{keep_id} not found")
    merge_ids = [int(i) for i in merge_ids if int(i) != keep_id]
    if not merge_ids:
        raise ValidationError("Nothing to merge")

    plan = {"keep": {"id": keep_id, "code": keep["code"], "title": spec.title(dict(keep))},
            "merged": [], "fields_filled": [], "links_moved": 0,
            "relationships_moved": 0, "duplicate_links_removed": 0,
            "self_links_removed": 0,
            "children_moved": 0, "dry_run": dry_run}
    tx_id = None if dry_run else db.now()

    values_to_set: dict[str, Any] = {}
    for mid in merge_ids:
        other = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (mid,)).fetchone()
        if other is None:
            continue
        o = dict(other)
        plan["merged"].append({"id": mid, "code": o.get("code"), "title": spec.title(o)})

        # 1. fill gaps in the surviving record (never overwrite existing values)
        for f in spec.writable_fields:
            if f.type == "tags":
                continue
            if (keep[f.key] in (None, "")) and o.get(f.key) not in (None, ""):
                values_to_set[f.key] = o[f.key]
                plan["fields_filled"].append(f.key)

        if dry_run:
            continue

        # 2. re-point the graph at the surviving record
        for etype_col, eid_col in (("entity1_type", "entity1_id"), ("entity2_type", "entity2_id")):
            otype_col, oid_col = (("entity2_type", "entity2_id") if etype_col == "entity1_type"
                                  else ("entity1_type", "entity1_id"))
            rows = conn.execute(
                f"SELECT id, code, {otype_col} AS otype, {oid_col} AS oid, relationship_type_id "
                f"FROM relationship WHERE {etype_col}=? AND {eid_col}=?", (spec.key, mid)).fetchall()
            for r in rows:
                plan["relationships_moved"] += 1
                if r["otype"] == spec.key and r["oid"] == keep_id:
                    # this link pointed at the survivor from the absorbed side;
                    # re-pointing it would make a record its own relation
                    conn.execute("DELETE FROM relationship WHERE id=?", (r["id"],))
                    db.log_change(conn, entity_type="relationship", entity_id=r["id"],
                                  entity_code=r["code"], action="delete", actor=actor,
                                  reason=reason or "duplicate merge",
                                  notes=(f"would have become a self-link when merging "
                                         f"{spec.key} #{mid} into #{keep_id}"))
                    plan["self_links_removed"] += 1
                    continue
                # a duplicate is the *same pair* with the same type — matching on
                # the moved end and the type alone used to delete perfectly valid
                # links that merely shared a type with an unrelated survivor link
                clash = conn.execute(
                    f"SELECT id FROM relationship WHERE {etype_col}=? AND {eid_col}=? "
                    f"AND {otype_col}=? AND {oid_col}=? AND relationship_type_id=? AND id<>?",
                    (spec.key, keep_id, r["otype"], r["oid"],
                     r["relationship_type_id"], r["id"])).fetchone()
                if clash:
                    conn.execute("DELETE FROM relationship WHERE id=?", (r["id"],))
                    db.log_change(conn, entity_type="relationship", entity_id=r["id"],
                                  entity_code=r["code"], action="delete", actor=actor,
                                  reason=reason or "duplicate merge",
                                  notes=(f"duplicate of #{clash['id']} — dropped while merging "
                                         f"{spec.key} #{mid} into #{keep_id}"))
                    plan["duplicate_links_removed"] += 1
                else:
                    conn.execute(f"UPDATE relationship SET {eid_col}=? WHERE id=?",
                                 (keep_id, r["id"]))
                    db.log_change(conn, entity_type="relationship", entity_id=r["id"],
                                  entity_code=r["code"], action="update", actor=actor,
                                  reason=reason or "duplicate merge",
                                  notes=(f"re-pointed while merging {spec.key} #{mid} "
                                         f"into #{keep_id}"))

        # 3. move many-to-many children
        for table in MERGE_TABLES:
            conn.execute(f"UPDATE OR IGNORE {table} SET entity_id=? "
                         f"WHERE entity_type=? AND entity_id=?", (keep_id, spec.key, mid))
            plan["links_moved"] += 1

        # 4. person positions and place hierarchy
        if spec.key == "person":
            conn.execute("UPDATE person_position SET person_id=? WHERE person_id=?",
                         (keep_id, mid))
            plan["children_moved"] += 1
        if spec.key == "place":
            conn.execute("UPDATE place SET parent_place_id=? WHERE parent_place_id=?",
                         (keep_id, mid))
            conn.execute("UPDATE person SET birthplace_id=? WHERE birthplace_id=?",
                         (keep_id, mid))
            conn.execute("UPDATE institution SET place_id=? WHERE place_id=?",
                         (keep_id, mid))
        if spec.key == "institution":
            conn.execute("UPDATE person SET affiliated_institution_id=? "
                         "WHERE affiliated_institution_id=?", (keep_id, mid))
            conn.execute("UPDATE person_position SET institution_id=? "
                         "WHERE institution_id=?", (keep_id, mid))

        # 5. retire the duplicate (recoverable)
        conn.execute(f"UPDATE {spec.table} SET deleted_at=?, updated_at=?, updated_by=?, "
                     f"version=version+1 WHERE id=?", (db.now(), db.now(), actor, mid))
        db.log_change(conn, entity_type=spec.key, entity_id=mid, action="delete", actor=actor,
                      entity_code=o.get("code"),
                      notes=f"merged into {keep['code']} (#{keep_id})",
                      reason=reason or "duplicate merge")
        db.drop_from_index(conn, spec.key, mid)

    if dry_run:
        plan["fields_filled"] = sorted(set(plan["fields_filled"]))
        return plan

    if values_to_set:
        values_to_set["updated_at"] = db.now()
        values_to_set["updated_by"] = actor
        values_to_set["version"] = int(keep["version"]) + 1
        sets = ", ".join(f"{k}=?" for k in values_to_set)
        conn.execute(f"UPDATE {spec.table} SET {sets} WHERE id=?",
                     list(values_to_set.values()) + [keep_id])
        db.diff_and_log(conn, entity_type=spec.key, entity_id=keep_id,
                        entity_code=keep["code"], before=dict(keep), after=values_to_set,
                        labels=spec.labels("en"), actor=actor,
                        reason=reason or f"merged {len(merge_ids)} duplicate record(s)")
    else:
        db.log_change(conn, entity_type=spec.key, entity_id=keep_id, action="update",
                      actor=actor, entity_code=keep["code"],
                      reason=reason or "duplicate merge",
                      notes=f"absorbed {len(plan['merged'])} record(s)")
    db.log_change(conn, entity_type=spec.key, entity_id=keep_id, action="update", actor=actor,
                  entity_code=keep["code"], field_key="__merge__",
                  new_value=", ".join(m["code"] or str(m["id"]) for m in plan["merged"]),
                  notes="merge completed", tx_id=tx_id)
    _index_record(conn, spec, keep_id)
    conn.commit()
    plan["fields_filled"] = sorted(set(plan["fields_filled"]))
    plan["keep"]["record"] = get_record(conn, spec, keep_id)
    return plan
