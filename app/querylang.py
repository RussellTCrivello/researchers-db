"""A typed query string — the same filters, written as text.

The registry's filter engine is precise but only speakable through a builder: the
state of a view lives in nested JSON, which cannot be pasted into an e-mail, put
in a URL, or read back six months later.  This module compiles a compact, human
query language into exactly that payload, and back again.

    status:published tag:"early cinema" birth:1880..1900 -country:EG
    type:institution founded:>1920 sort:-founded
    "ابن سينا" OR "Avicenna"

Grammar
-------
=====================  ==========================================================
``word``               full-text term (Arabic-normalised by the engine)
``-"two words"``       exclude a term from the full-text search
``field:value``        equality; vocabulary codes *and* labels are accepted
``field:>n``           ``>`` ``>=`` ``<`` ``<=`` comparison
``field:a..b``         inclusive range (years, dates, numbers)
``field:a|b``          any of a list
``-field:value``       negation (``not_in`` / ``ne``, whichever the field allows)
``field:null``         the field is empty (absent or blank)
``field:notnull``      the field has a value
``tag:name``           specialisation / expertise tag
``status:code``        editorial status
``sort:field``         order ascending; ``sort:-field`` descending
``limit:n`` · ``page:n``
``OR`` (or ``أو``)     joins the surrounding clauses with OR instead of AND
=====================  ==========================================================

Everything else is AND.  The parser never invents a field: an unknown field is
reported as a warning and dropped, which is the same contract the filter engine
already honours, so a stale saved query never breaks a page.
"""
from __future__ import annotations

import re
import shlex
from typing import Any

from .schemas import EntitySpec, derived_map

# words a researcher is likely to type instead of the column name
FIELD_ALIASES = {
    "status": "record_status_id",
    "record_status": "record_status_id",
    "auth": "authentication_id",
    "verification": "authentication_id",
    "doc": "documentation_id",
    "documentation": "documentation_id",
    "country": "country_id",
    "type": "place_type_id",          # only honoured where the field exists
    "kind": "institution_type_id",
    "class": "classification_id",
    "source": "primary_source_id",
    "reviewed": "last_review_date",
    # a researcher writes "birth", not "birth_date"
    "birth": "birth_date",
    "born": "birth_date",
    "death": "death_date",
    "died": "death_date",
    "founded": "founded_date",
    "closed": "closed_date",
    "start": "start_date",
    "end": "end_date",
    "published": "publication_date",
    "nationality": "nationality_id",
    "position": "current_position",
}

OR_WORDS = {"or", "أو", "||"}
EMPTY_WORDS = {"null", "empty", "∅"}
NOT_EMPTY_WORDS = {"notnull", "exists", "has"}

_COMPARATOR = re.compile(r"^(>=|<=|>|<|=)\s*(.+)$")
_RANGE = re.compile(r"^(.+?)\.\.(.+)$")
_QUOTED = re.compile(r'"([^"]*)"')


class QueryError(ValueError):
    """A query that cannot be compiled at all (the caller turns this into a 422)."""


def _split_terms(text: str) -> list[str]:
    """Split on whitespace but keep quoted phrases whole, quotes included."""
    try:
        return shlex.split(text, posix=True)
    except ValueError as exc:                     # unbalanced quote
        raise QueryError(f"Unbalanced quote in the query: {exc}") from None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def known_fields(spec: EntitySpec) -> set[str]:
    keys = {f.key for f in spec.fields}
    keys |= {"id", "code", "created_at", "updated_at", "deleted_at"}
    keys |= set(derived_map(spec.key))
    keys |= set(FIELD_ALIASES)
    return keys


def parse_for(spec: EntitySpec, text: str) -> dict[str, Any]:
    """Compile a query string into a ``/query`` payload.

    Returns ``{payload, warnings, echo, unknown}``: ``payload`` can be posted to
    ``POST /api/{entity}/query`` unchanged, ``echo`` is the canonical spelling of
    what was understood (so a user can see how their query was read).
    """
    text = (text or "").strip()
    out: dict[str, Any] = {"where": [], "q": "", "logic": "and"}
    warnings: list[str] = []
    unknown: list[str] = []
    echo: list[str] = []
    words: list[str] = []
    excluded: list[str] = []
    known = known_fields(spec)

    for raw in _split_terms(text):
        if raw.lower() in OR_WORDS:
            out["logic"] = "or"
            echo.append("OR")
            continue
        if raw.startswith("-") and len(raw) > 1:
            body = raw[1:]
            if ":" in body:
                key, _, value = body.partition(":")
                clause = _clause(spec, key, value, known, warnings, unknown)
                if clause is not None:
                    clause["op"] = _negate(clause["op"])
                    out["where"].append(clause)
                    echo.append(f"-{key}:{value}")
                continue
            excluded.append(_unquote(body))
            echo.append(f'-"{_unquote(body)}"')
            continue
        if ":" in raw and not raw.startswith('"'):
            key, _, value = raw.partition(":")
            lower = key.lower()
            if lower == "sort":
                desc = value.startswith("-")
                out["sort"] = {"key": value.lstrip("-+"), "dir": "desc" if desc else "asc"}
                echo.append(f"sort:{value}")
                continue
            if lower in ("limit", "page", "page_size"):
                try:
                    out["page_size" if lower != "page" else "page"] = int(value)
                except ValueError:
                    warnings.append(f"{key}: expected a number, got {value!r}")
                echo.append(f"{key}:{value}")
                continue
            if lower == "tag" or lower == "tags":
                out.setdefault("tag_labels", []).append(_unquote(value))
                echo.append(f"tag:{value}")
                continue
            if lower == "status":
                out.setdefault("status_codes", []).append(_unquote(value))
                echo.append(f"status:{value}")
                continue
            if lower in ("q", "search"):
                words.append(_unquote(value))
                echo.append(f'"{_unquote(value)}"')
                continue
            clause = _clause(spec, key, value, known, warnings, unknown)
            if clause is not None:
                out["where"].append(clause)
                echo.append(f"{key}:{value}")
            continue
        words.append(_unquote(raw))
        echo.append(f'"{_unquote(raw)}"' if " " in _unquote(raw) else _unquote(raw))

    for word in words:
        out["q"] = (out["q"] + " " + word).strip()
    if excluded:
        out["exclude_q"] = excluded
    if not out["where"]:
        out.pop("where")
    elif out["logic"] == "or" and len(out["where"]) < 2 and not out.get("q"):
        out["logic"] = "and"
    if out["logic"] == "or" and not out.get("where"):
        # "status:published OR status:verified" collapses into one multi-value list,
        # which is exactly what OR means there; bare words have no OR in the engine
        if not (out.get("status_codes") or out.get("tag_labels")):
            warnings.append("OR applies to field filters; free-text terms were combined "
                            "into a single search")
        out["logic"] = "and"
    return {"payload": out, "warnings": warnings, "unknown": unknown,
            "echo": " ".join(echo), "entity": spec.key}


def _clause(spec: EntitySpec, key: str, value: str, known: set[str],
            warnings: list[str], unknown: list[str]) -> dict[str, Any] | None:
    field = FIELD_ALIASES.get(key.lower(), key)
    if field not in known:
        # "birth" is a prefix of "birth_date"; accept the obvious extension rather
        # than making the user learn the column names
        for candidate in (f"{field}_date", f"{field}_id", f"{field}_precision"):
            if candidate in known:
                field = candidate
                break
    if field not in known or (spec.field(field) is None and field not in derived_map(spec.key)
                              and field not in ("id", "code", "created_at", "updated_at")):
        unknown.append(field)
        warnings.append(f"unknown field '{field}' — ignored")
        return None
    value = value.strip()
    if value.lower() in EMPTY_WORDS:
        return {"field": field, "op": "empty", "value": None}
    if value.lower() in NOT_EMPTY_WORDS:
        return {"field": field, "op": "not_empty", "value": None}
    cmp = _COMPARATOR.match(value)
    if cmp:
        op = {"=": "eq", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[cmp.group(1)]
        return {"field": field, "op": op, "value": _unquote(cmp.group(2))}
    span = _RANGE.match(value)
    if span and not value.startswith(".."):
        return {"field": field, "op": "between",
                "value": [_unquote(span.group(1)), _unquote(span.group(2))]}
    if "|" in value:
        return {"field": field, "op": "in",
                "value": [_unquote(v) for v in value.split("|") if v.strip()]}
    return {"field": field, "op": "eq", "value": _unquote(value)}


def _negate(op: str) -> str:
    return {"eq": "ne", "in": "not_in", "contains": "not_contains",
            "empty": "not_empty", "not_empty": "empty",
            "gt": "lte", "gte": "lt", "lt": "gte", "lte": "gt"}.get(op, op)


def resolve(conn, spec: EntitySpec, payload: dict) -> tuple[dict, list[str]]:
    """Turn the parser's symbolic lists into the ids the filter engine expects.

    Codes and names are what a person types; ids are what the database uses.
    Anything that cannot be resolved is reported, never guessed — a query for a
    tag that does not exist must return an explanation, not every record.
    """
    from . import db

    payload = dict(payload)
    warnings: list[str] = []
    codes = payload.pop("status_codes", None)
    if codes:
        ids = []
        for code in codes:
            row = conn.execute(
                "SELECT id FROM lookup WHERE domain='record_status' AND "
                "(code=? OR lower(label_en)=lower(?) OR label_ar=?)",
                (code, code, code)).fetchone()
            if row:
                ids.append(row[0])
            else:
                warnings.append(f"unknown status '{code}'")
        if ids:
            payload["status_ids"] = ids
    labels = payload.pop("tag_labels", None)
    if labels:
        ids = []
        for label in labels:
            norm = db.normalize(label)
            row = conn.execute(
                "SELECT id FROM tag WHERE norm(COALESCE(label_en,'')) LIKE ? "
                "OR norm(COALESCE(label_ar,'')) LIKE ? ORDER BY id LIMIT 1",
                (f"%{norm}%", f"%{norm}%")).fetchone()
            if row:
                ids.append(row[0])
            else:
                warnings.append(f"unknown tag '{label}'")
        if ids:
            payload["tag_ids"] = ids
    excluded = payload.pop("exclude_q", None)
    if excluded:
        warnings.append("excluded words are not supported by the search engine: "
                        + ", ".join(excluded))
    return payload, warnings


def to_string(payload: dict, spec: EntitySpec) -> tuple[str, list[str]]:
    """Render a filter payload back into a query string.

    Used to keep the query bar and the filter builder showing the same thing.  A
    clause the language cannot spell is reported, never quietly dropped.
    """
    parts: list[str] = []
    unsupported: list[str] = []
    q = (payload.get("q") or "").strip()
    if q:
        parts.append(q if " " not in q else f'"{q}"')
    for phrase in payload.get("exclude_q") or []:
        parts.append(f'-"{phrase}"')
    for clause in payload.get("where") or []:
        field = str(clause.get("field", ""))
        op = str(clause.get("op", "eq"))
        value = clause.get("value")
        text = _render(field, op, value)
        if text is None:
            unsupported.append(f"{field} {op}")
        else:
            parts.append(text)
    if payload.get("tag_labels"):
        parts += [f"tag:{t}" for t in payload["tag_labels"]]
    if payload.get("status_codes"):
        parts += [f"status:{c}" for c in payload["status_codes"]]
    if (payload.get("logic") or "and").lower() == "or" and len(parts) > 1:
        parts = [" OR ".join(parts)]
    sort = payload.get("sort")
    if isinstance(sort, dict) and sort.get("key"):
        parts.append(f"sort:{'-' if sort.get('dir') == 'desc' else ''}{sort['key']}")
    return " ".join(parts), unsupported


def _render(field: str, op: str, value: Any) -> str | None:
    def one(v: Any) -> str:
        s = "" if v is None else str(v)
        return f'"{s}"' if (not s or any(ch in s for ch in ' \t"|')) else s

    if op in ("eq", "contains", "equals", "starts"):
        return f"{field}:{one(value)}"
    if op == "ne":
        return f"-{field}:{one(value)}"
    if op == "not_contains":
        return f"-{field}:{one(value)}"
    if op in ("gt", "gte", "lt", "lte"):
        sign = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        return f"{field}:{sign}{one(value)}"
    if op == "between" and isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{field}:{one(value[0])}..{one(value[1])}"
    if op == "in" and isinstance(value, (list, tuple)):
        return f"{field}:{'|'.join(one(v) for v in value)}"
    if op == "not_in" and isinstance(value, (list, tuple)):
        return f"-{field}:{'|'.join(one(v) for v in value)}"
    if op == "empty":
        return f"{field}:null"
    if op == "not_empty":
        return f"{field}:notnull"
    if op == "is_null":
        return f"{field}:null"
    if op == "not_null":
        return f"{field}:notnull"
    return None


def _quoted_terms(text: str) -> list[str]:
    return _QUOTED.findall(text or "")
