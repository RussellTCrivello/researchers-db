"""
SIRAJ · Research Registry — HTTP API + static application shell.

Run:  python run.py            (recommended, works on Windows/macOS/Linux)
      uvicorn app.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import sqlite3
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import db, graph, querylang, repo, reports, stats, transfer
from .. import settings as settings_mod
from ..military import router as military_router
from ..military import service as mil_service
from ..military.specs import MIL_SPECS, is_mil, mil_entity_meta, mil_options, mil_query_shim
from ..schemas import ENTITIES, ENTITY_TYPES, derived_meta, entity_meta, fields_meta
from .crce_api import router as crce_router
from .deps import actor_of, conn_dep
from .map_api import router as map_router
from .structures_api import router as structures_router

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"
STAGING = db.DATA_DIR / "staging"
STAGING.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown hook (modern replacement for the deprecated on_event)."""
    db.init_db(seed_demo=False)
    # make sure a database exists with reference data (demo only if explicitly asked)
    if os.environ.get("SIRAJ_SEED_DEMO", "0") == "1":
        db.init_db(seed_demo=True)
    # every declared setting gets a row, so an older database gains the keys a
    # newer build declares — without a migration per key
    _boot = db.connect()
    try:
        settings_mod.ensure(_boot)
    finally:
        _boot.close()
    yield


app = FastAPI(title="SIRAJ · Research Registry", version="1.1.0",
              description="Bilingual registry of persons, places, institutions, "
                          "relationships, sources and events.",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# The geographic workspace lives in its own module and is mounted *first*: the map has
# two-segment paths (/api/map/features, /api/geo/basemap) that the generic
# /api/{entity}/{rec_id} route would otherwise swallow.
app.include_router(map_router)
app.include_router(crce_router)
app.include_router(structures_router)
# The Military Organization module (Brigade Information Management System)
# shares the unified registry.db (military schema via migration 015, additive)
# and the shell interface at #/military.  Registered here like the other
# feature modules; SIRAJ routes and registry data are untouched.
app.include_router(military_router)


def content_disposition(filename: str) -> str:
    """``Content-Disposition`` that survives Arabic file names in any browser.

    RFC 6266/5987: an ASCII fallback for legacy clients plus the UTF-8 form,
    which is what Chrome/Edge/Firefox on Windows actually use.  Control
    characters and the characters Windows forbids in filenames are stripped.
    """
    from urllib.parse import quote

    cleaned = "".join(ch for ch in (filename or "download")
                      if ch.isprintable() and ch not in '\\/:*?"<>|').strip() or "download"
    ascii_name = cleaned.encode("ascii", "ignore").decode("ascii") or "download"
    return (f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(cleaned, safe='')}")


@app.exception_handler(transfer.UnsupportedFormat)
async def format_error_handler(_request, exc: transfer.UnsupportedFormat):
    """An unknown export format is a client error, not a server fault."""
    return JSONResponse(status_code=422, content={"error": str(exc),
                                                  "type": "ValidationError",
                                                  "formats": list(transfer.EXPORT_FORMATS)})


@app.exception_handler(repo.RepoError)
async def repo_error_handler(_request, exc: repo.RepoError):
    return JSONResponse(status_code=exc.status, content={"error": str(exc),
                                                        "type": type(exc).__name__})


def spec_of(entity: str) -> Any:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise HTTPException(404, f"Unknown entity type '{entity}'")
    return spec


def spec_of_any(entity: str) -> Any:
    """Registry *or* military entity — one query/export/meta contract for both."""
    if entity in MIL_SPECS:
        return MIL_SPECS[entity]
    return spec_of(entity)


def _mil_role(x_military_role: str | None) -> str:
    role = (x_military_role or "").strip().lower()
    # mirrors app.military.api._role_of: an unknown/absent role defaults to admin
    return role if role in ("viewer", "staff", "admin") else "admin"


def _mil_write_guard(x_military_role: str | None) -> str:
    role = _mil_role(x_military_role)
    if role not in ("staff", "admin"):
        raise HTTPException(403, {"ok": False, "error": {
            "code": "forbidden", "message": "staff role or above required"}})
    return role


def _mil_write(conn, fn, *args):
    """Run a military-service write, commit it and map its errors to HTTP."""
    try:
        out = fn(conn, *args)
        conn.commit()
        return out
    except (mil_service.ServiceError, mil_service.rules.RuleViolation) as exc:
        conn.rollback()
        raise HTTPException(getattr(exc, "status", 422), {"ok": False, "error": {
            "code": getattr(exc, "code", "error"),
            "message": getattr(exc, "message", str(exc)),
            "field": getattr(exc, "field", None)}}) from exc


# ===========================================================================
# meta / bootstrap
# ===========================================================================
_STARTED_AT = db.now()
API_TOKEN = os.environ.get("SIRAJ_API_TOKEN", "")


@app.middleware("http")
async def optional_token_auth(request, call_next):
    """Opt-in bearer-token gate: set SIRAJ_API_TOKEN to require a token on /api.

    Disabled by default so the app runs in a trusted network / behind an
    authenticating reverse proxy.  /api/health stays open for probes.
    """
    if API_TOKEN and request.url.path.startswith("/api") and request.url.path != "/api/health":
        supplied = (request.headers.get("authorization") or "").replace("Bearer ", "").strip() \
            or request.headers.get("x-api-key", "")
        if supplied != API_TOKEN:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)


@app.get("/api/metrics")
def metrics(conn=Depends(conn_dep)):
    counts = {}
    for key, spec in ENTITIES.items():
        counts[key] = conn.execute(
            f"SELECT COUNT(*) c FROM {spec.table} WHERE deleted_at IS NULL").fetchone()["c"]
    return {
        "started_at": _STARTED_AT, "now": db.now(),
        "records": counts,
        "trash": sum(conn.execute(f"SELECT COUNT(*) c FROM {s.table} WHERE deleted_at IS NOT NULL")
                     .fetchone()["c"] for s in ENTITIES.values()),
        "change_log": conn.execute("SELECT COUNT(*) c FROM change_log").fetchone()["c"],
        "index_documents": conn.execute("SELECT COUNT(*) c FROM search_doc").fetchone()["c"],
        "db_size_bytes": db.DB_PATH.stat().st_size if db.DB_PATH.exists() else 0,
        "token_auth": bool(API_TOKEN),
    }


@app.get("/api/health")
def health(conn=Depends(conn_dep)):
    return {"ok": True, "time": db.now(),
            "db": str(db.DB_PATH), "entities": len(ENTITIES),
            "schema_version": (conn.execute(
                "SELECT value FROM app_meta WHERE key='schema_version'").fetchone() or ["?"])[0]}


@app.get("/api/meta")
def meta(conn=Depends(conn_dep), lang: str = "en"):
    lookups = repo.lookup_options(conn)
    domains = [dict(r) for r in conn.execute(
        "SELECT d.*, (SELECT COUNT(*) FROM lookup l WHERE l.domain=d.domain AND l.is_active=1) n "
        "FROM lookup_domain d ORDER BY d.sort_order")]
    locales = [dict(r) for r in conn.execute("SELECT * FROM locale ORDER BY sort_order")]
    users = [dict(r) for r in conn.execute(
        "SELECT id, username, display_name, email, role, is_active FROM app_user ORDER BY id")]
    # the *effective* instance configuration: a key with no override row reports its
    # declared default, so a client never has to know the defaults itself
    instance_settings = settings_mod.as_strings(conn)
    sequences = [dict(r) for r in conn.execute("SELECT * FROM sequence ORDER BY entity_type")]
    stats_db = {
        "size_bytes": db.DB_PATH.stat().st_size if db.DB_PATH.exists() else 0,
        "path": str(db.DB_PATH),
    }
    return {
        "app": {"name": "SIRAJ", "version": "1.0.0", "schema_version": "1.0.0"},
        "entities": entity_meta(lang) + mil_entity_meta(),
        "fields": {**{k: fields_meta(v) for k, v in ENTITIES.items()},
                   **{k: fields_meta(v) for k, v in MIL_SPECS.items()}},
        "derived": {**{k: derived_meta(k) for k in ENTITIES},
                    **{k: [] for k in MIL_SPECS}},
        "view_modes": ["table", "cards", "gallery", "list"],
        "lookups": lookups,
        "lookup_domains": domains,
        "locales": locales,
        "users": users,
        "settings": instance_settings,
        "settings_schema": settings_mod.schema(),
        "sequences": sequences,
        "reports": [{"key": k} for k in list(reports.REPORTS) + ["custom"]],
        "operators": ["eq", "ne", "contains", "not_contains", "starts", "ends", "in",
                      "not_in", "between", "gt", "gte", "lt", "lte", "is_null", "not_null",
                      "year_eq", "year_gte", "year_lte"],
        "db": stats_db,
        "time": db.now(),
    }


@app.get("/api/lookups")
def lookups(domain: str | None = None, include_inactive: bool = False,
            conn=Depends(conn_dep)):
    """Grouped by domain; when a domain is requested the values are returned flat."""
    data = repo.lookup_options(conn, domain, include_inactive)
    if domain:
        return data.get(domain, [])
    return data


@app.get("/api/lookup-domains")
def lookup_domains(conn=Depends(conn_dep)):
    return [dict(r) for r in conn.execute(
        """SELECT d.*, (SELECT COUNT(*) FROM lookup l WHERE l.domain=d.domain) n
           FROM lookup_domain d ORDER BY d.sort_order""")]


@app.post("/api/lookups")
def lookup_create(payload: dict = Body(...), conn=Depends(conn_dep),
                  x_actor: str | None = Header(None)):
    required = ("domain", "code", "label_en", "label_ar")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(422, f"Missing: {', '.join(missing)}")
    if not conn.execute("SELECT 1 FROM lookup_domain WHERE domain=?",
                        (payload["domain"],)).fetchone():
        raise HTTPException(422, f"Unknown vocabulary domain '{payload['domain']}'")
    try:
        cur = conn.execute(
            """INSERT INTO lookup (domain, code, label_en, label_ar, description_en, description_ar,
                  parent_id, sort_order, color, meta, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (payload["domain"], payload["code"], payload["label_en"], payload["label_ar"],
             payload.get("description_en"), payload.get("description_ar"),
             payload.get("parent_id"), int(payload.get("sort_order") or 100),
             payload.get("color") or "gray", db.json_dump(payload.get("meta")),
             1 if payload.get("is_active", True) else 0))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This code already exists in the vocabulary")
    db.log_change(conn, entity_type="lookup", entity_id=cur.lastrowid, action="create",
                  actor=actor_of(x_actor, None), field_key=payload["domain"],
                  new_value=f'{payload["code"]} = {payload["label_en"]}')
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@app.put("/api/lookups/{lookup_id}")
def lookup_update(lookup_id: int, payload: dict = Body(...), conn=Depends(conn_dep),
                  x_actor: str | None = Header(None)):
    row = conn.execute("SELECT * FROM lookup WHERE id=?", (lookup_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Vocabulary value not found")
    before = dict(row)
    fields = [k for k in ("label_en", "label_ar", "description_en", "description_ar",
                          "sort_order", "color", "is_active", "parent_id") if k in payload]
    if fields:
        conn.execute(f"UPDATE lookup SET {', '.join(f'{k}=?' for k in fields)}, "
                     f"updated_at=? WHERE id=?",
                     [payload[k] for k in fields] + [db.now(), lookup_id])
        db.diff_and_log(conn, entity_type="lookup", entity_id=lookup_id,
                        entity_code=before["code"], before=before,
                        after={k: payload[k] for k in fields},
                        actor=actor_of(x_actor, None))
    conn.commit()
    return {"ok": True}


@app.delete("/api/lookups/{lookup_id}")
def lookup_delete(lookup_id: int, conn=Depends(conn_dep), x_actor: str | None = Header(None)):
    row = conn.execute("SELECT * FROM lookup WHERE id=?", (lookup_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Vocabulary value not found")
    if row["is_system"]:
        # system vocabularies are deactivated, never deleted (they are referenced)
        conn.execute("UPDATE lookup SET is_active=0, updated_at=? WHERE id=?", (db.now(), lookup_id))
        conn.commit()
        return {"ok": True, "deactivated": True}
    conn.execute("DELETE FROM lookup WHERE id=?", (lookup_id,))
    db.log_change(conn, entity_type="lookup", entity_id=lookup_id, action="delete",
                  actor=actor_of(x_actor, None), old_value=row["label_en"])
    conn.commit()
    return {"ok": True}


@app.get("/api/options/{entity}")
def options(entity: str, q: str | None = None, limit: int = 50, ids: str | None = None,
            country_id: int | None = None, place_types: str | None = None,
            conn=Depends(conn_dep)):
    """Picker payload: id, code, bilingual label and a secondary hint line.

    Used by the searchable comboboxes; `ids` rehydrates the current selection even
    when it falls outside the first page of results. For places, `country_id` and
    comma-separated `place_types` (e.g. ``district,neighbourhood``) narrow the list.
    """
    if is_mil(entity):
        spec = MIL_SPECS[entity]
        wanted = [int(i) for i in (ids or "").split(",") if i.strip().isdigit()][:200]
        return mil_options(conn, spec, q, limit,
                           ids=wanted or None)
    spec = spec_of(entity)
    if ids:
        wanted = [int(i) for i in ids.split(",") if i.strip().isdigit()][:200]
        if not wanted:
            return []
        rows = conn.execute(
            f"SELECT t.* FROM {spec.table} t WHERE t.id IN ({','.join('?' * len(wanted))})"
            f" AND t.deleted_at IS NULL", wanted).fetchall()
        by_id = {r["id"]: r for r in rows}
        return [picker_item(conn, spec, by_id[i]) for i in wanted if i in by_id]
    types = [c.strip() for c in (place_types or "").split(",") if c.strip()] or None
    base = repo.ref_options(conn, entity, q, limit,
                            country_id=country_id, place_types=types)
    out = []
    for item in base:
        row = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (item["id"],)).fetchone()
        if row is not None:
            out.append(picker_item(conn, spec, row))
    return out


def picker_item(conn, spec, row) -> dict:
    d = dict(row)
    hint_parts = []
    if spec.key == "person":
        if d.get("birth_date"):
            hint_parts.append(str(d["birth_date"]))
        if d.get("classification_id"):
            lk = conn.execute("SELECT label_en, label_ar FROM lookup WHERE id=?",
                              (d["classification_id"],)).fetchone()
            if lk:
                hint_parts.append(f"{lk['label_en']} / {lk['label_ar']}")
        label_ar = d.get("name_ar")
    elif spec.key in ("institution", "place"):
        if d.get("country_id"):
            lk = conn.execute("SELECT label_en FROM lookup WHERE id=?",
                              (d["country_id"],)).fetchone()
            if lk:
                hint_parts.append(lk["label_en"])
        if d.get("city"):
            hint_parts.append(str(d["city"]))
        label_ar = d.get("name_ar")
    elif spec.key == "source":
        if d.get("publication_date"):
            hint_parts.append(str(d["publication_date"]))
        if d.get("publisher"):
            hint_parts.append(str(d["publisher"]))
        label_ar = d.get("title_ar")
    else:
        label_ar = (d.get("title_ar") or d.get("name_ar") or d.get("name")
                    or d.get("full_name") or d.get("exercise_name"))
    return {
        "id": d["id"], "code": d.get("code") or d.get("docname"), "label": spec.title(d),
        "label_ar": label_ar, "hint": " · ".join(hint_parts),
        "image": d.get("image_url"), "type": spec.key,
    }


# ===========================================================================
# search
# ===========================================================================
@app.get("/api/search")
def search(q: str, entity: str | None = None, limit: int = 20, conn=Depends(conn_dep)):
    match = db.fts_query(q)
    if not match:
        return {"q": q, "groups": [], "total": 0}
    types = [entity] if entity else ENTITY_TYPES
    groups, total = [], 0
    for key in types:
        spec = ENTITIES[key]
        rows = conn.execute(
            f"""SELECT * FROM {spec.table} WHERE deleted_at IS NULL AND id IN
                (SELECT entity_id FROM search_doc WHERE search_doc MATCH ? AND entity_type=?)
                LIMIT ?""", (match, key, limit)).fetchall()
        if not rows:
            continue
        total += len(rows)
        groups.append({
            "entity": key, "label_en": spec.plural_en, "label_ar": spec.plural_ar,
            "icon": spec.icon,
            "items": [{"id": r["id"], "code": r["code"], "title": spec.title(dict(r)),
                       "snippet": _snippet(dict(r), spec)} for r in rows],
        })
    return {"q": q, "groups": groups, "total": total}


def _snippet(row: dict, spec) -> str:
    for f in spec.fields:
        if f.type in ("textarea", "text") and row.get(f.key) and f.key not in spec.name_fields:
            return str(row[f.key])[:160]
    return ""


# ===========================================================================
# dashboard / reports
# ===========================================================================
@app.get("/api/dashboard")
def dashboard(conn=Depends(conn_dep)):
    return stats.dashboard(conn)


@app.get("/api/reports")
def report_list(conn=Depends(conn_dep)):
    return [
        {"key": "overview", "label_en": "Registry overview", "label_ar": "نظرة عامة",
         "icon": "grid"},
        {"key": "quality", "label_en": "Data quality audit", "label_ar": "جودة البيانات",
         "icon": "check"},
        {"key": "institutions", "label_en": "Institutional network", "label_ar": "الشبكة المؤسسية",
         "icon": "building"},
        {"key": "geography", "label_en": "Geographic distribution", "label_ar": "التوزيع الجغرافي",
         "icon": "map-pin"},
        {"key": "network", "label_en": "Relationship network", "label_ar": "شبكة العلاقات",
         "icon": "share"},
        {"key": "timeline", "label_en": "Chronology", "label_ar": "التقرير الزمني", "icon": "clock"},
        {"key": "sources", "label_en": "Sources & evidence", "label_ar": "المصادر والأدلة",
         "icon": "book"},
        {"key": "workflow", "label_en": "Review progress", "label_ar": "سير المراجعة",
         "icon": "check-circle"},
        {"key": "indicators", "label_en": "Indicator report", "label_ar": "المؤشرات",
         "icon": "activity"},
        {"key": "custom", "label_en": "Custom pivot", "label_ar": "تقرير مخصص", "icon": "sliders"},
    ]


# ===========================================================================
# relationship graph  (declared before /api/reports/{key} so it is not shadowed)
# ===========================================================================
@app.get("/api/relationship-map")
def relationship_map_get(params: str | None = None, conn=Depends(conn_dep)):
    parsed = json.loads(params) if params else {}
    return reports.relationship_map(conn, parsed)


@app.post("/api/relationship-map")
def relationship_map_post(payload: dict = Body(default={}), conn=Depends(conn_dep)):
    return reports.relationship_map(conn, payload or {})


# ---- the graph as a service: a node's dossier, and the path between two nodes ----
@app.get("/api/graph/node/{entity_type}/{record_id}")
def graph_node(entity_type: str, record_id: int, conn=Depends(conn_dep)):
    """Everything the diagram's side panel needs to describe one selected node."""
    try:
        return graph.node_dossier(conn, entity_type, record_id)
    except graph.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@app.post("/api/graph/path")
def graph_path(payload: dict = Body(...), conn=Depends(conn_dep)):
    """The shortest chain of stored relationships between two records."""
    def pair(prefix: str) -> tuple[str, int]:
        t = str(payload.get(f"{prefix}_type") or "")
        i = payload.get(f"{prefix}_id")
        if not t or i in (None, ""):
            raise HTTPException(422, f"{prefix}_type and {prefix}_id are required")
        try:
            return (t, int(i))
        except (TypeError, ValueError):
            raise HTTPException(422, f"{prefix}_id must be an integer") from None

    start, end = pair("from"), pair("to")
    depth = max(1, min(8, int(payload.get("max_depth") or 5)))
    try:
        result = graph.shortest_path(conn, start, end, max_depth=depth)
    except graph.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    return {"ok": True, **result}


@app.get("/api/reports/{key}")
def report_get(key: str, params: str | None = None, conn=Depends(conn_dep)):
    parsed = json.loads(params) if params else {}
    return reports.build(conn, key, parsed)


@app.post("/api/reports/{key}")
def report_post(key: str, payload: dict = Body(default={}), conn=Depends(conn_dep)):
    return reports.build(conn, key, payload.get("params", payload) or {})


@app.get("/api/reports/{key}/export")
def report_export(key: str, format: str = "xlsx", params: str | None = None,
                  conn=Depends(conn_dep)):
    parsed = json.loads(params) if params else {}
    report = reports.build(conn, key, parsed)
    if format in ("xlsx", "xls"):
        data, name = reports.report_xlsx(report)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format in ("csv", "tsv"):
        data, name = reports.report_csv(report)
        mime = "text/csv; charset=utf-8"
    elif format == "json":
        data = json.dumps(report, ensure_ascii=False, indent=2).encode()
        name, mime = f"report-{key}.json", "application/json"
    else:
        raise HTTPException(400, "format must be xlsx, csv or json")
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": content_disposition(name)})


# ===========================================================================
# change log (global)
# ===========================================================================
@app.get("/api/changelog")
def changelog(entity_type: str | None = None, entity_id: int | None = None,
              actor: str | None = None, action: str | None = None,
              date_from: str | None = None, date_to: str | None = None,
              q: str | None = None, page: int = 1, page_size: int = 50,
              conn=Depends(conn_dep)):
    where, params = ["1=1"], []
    if entity_type:
        where.append("cl.entity_type=?"); params.append(entity_type)
    if entity_id:
        where.append("cl.entity_id=?"); params.append(entity_id)
    if actor:
        where.append("cl.actor=?"); params.append(actor)
    if action:
        where.append("cl.action=?"); params.append(action)
    if date_from:
        where.append("cl.changed_at >= ?"); params.append(date_from)
    if date_to:
        where.append("cl.changed_at <= ?"); params.append(date_to + "T23:59:59Z")
    if q:
        where.append("(norm(cl.field_key) LIKE ? OR norm(cl.old_value) LIKE ? OR "
                     "norm(cl.new_value) LIKE ? OR norm(cl.notes) LIKE ? OR norm(cl.reason) LIKE ?)")
        n = f"%{db.normalize(q)}%"
        params += [n, n, n, n, n]
    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) c FROM change_log cl WHERE {clause}",
                         params).fetchone()["c"]
    rows = conn.execute(
        f"""SELECT cl.*, s.title AS source_title FROM change_log cl
            LEFT JOIN source s ON s.id=cl.source_id
            WHERE {clause} ORDER BY cl.id DESC LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size]).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "page": page,
            "pages": max(1, (total + page_size - 1) // page_size)}


# ===========================================================================
# settings / sequences / users / locales
# ===========================================================================
@app.get("/api/settings")
def settings_get(conn=Depends(conn_dep)):
    """The whole configuration: every declared key, its value, and where it came from.

    `settings` is the flat `{key: value}` map clients have always used (effective
    values, canonical strings); `fields` adds the registry metadata — type,
    allowed values, default, an explanation in both languages, the code path that
    honours it, and whether the current value is an instance override or the
    shipped default.
    """
    doc = settings_mod.as_document(conn)
    return {
        "ok": True,
        "settings": {f["key"]: f["value"] for f in doc["fields"]},
        "fields": doc["fields"],
        "groups": doc["groups"],
        "overrides": doc["overrides"],
        "schema_version": 1,
    }


@app.get("/api/settings/schema")
def settings_schema():
    """The registry itself — no database access, so it is safe to cache."""
    return settings_mod.schema()


@app.put("/api/settings")
def settings_put(payload: dict = Body(...), conn=Depends(conn_dep),
                 x_actor: str | None = Header(None)):
    """Write configuration.  Validated against the registry; audited per key.

    An unknown key or a value outside its declared type/range is refused with
    `422` and a per-key reason — the request is all-or-nothing, so a typo cannot
    leave half a change behind.
    """
    res = settings_mod.save(conn, payload, actor=actor_of(x_actor, None),
                            reason="settings")
    if res["problems"]:
        return JSONResponse(status_code=422, content={
            "ok": False, "error": "invalid settings", "problems": res["problems"],
            "applied": [c["key"] for c in res["changed"]]})
    return {"ok": True, "changed": res["changed"],
            "settings": {k: str(v) for k, v in res["settings"].items()}}


@app.post("/api/settings/reset")
def settings_reset(payload: dict = Body(default={}), conn=Depends(conn_dep),
                   x_actor: str | None = Header(None)):
    """Drop overrides so the declared defaults apply again.

    `{"keys": ["display.page_size"]}`, `{"group": "transfer"}`, or an empty body
    for the whole configuration.  Audited, like any other change.
    """
    res = settings_mod.reset(conn, keys_to_reset=payload.get("keys"),
                             group=payload.get("group"),
                             actor=actor_of(x_actor, None))
    return {"ok": True, "reset": res["reset"], "changed": res["changed"],
            "unknown": res["unknown"],
            "settings": settings_mod.as_strings(conn)}


@app.get("/api/sequences")
def sequences_get(conn=Depends(conn_dep)):
    out = []
    for r in conn.execute("SELECT * FROM sequence ORDER BY entity_type"):
        d = dict(r)
        d["preview"] = db.format_code(
            {"prefix": d["prefix"], "separator": d["separator"], "suffix": d["suffix"],
             "padding": d["padding"], "template": d["template"]}, d["next_value"])
        d["in_use"] = conn.execute(
            f"SELECT COUNT(*) c FROM {ENTITIES[d['entity_type']].table}").fetchone()["c"] \
            if d["entity_type"] in ENTITIES else 0
        out.append(d)
    return out


@app.put("/api/sequences/{entity_type}")
def sequences_put(entity_type: str, payload: dict = Body(...), conn=Depends(conn_dep),
                  x_actor: str | None = Header(None)):
    spec_of(entity_type)
    db.ensure_sequence(conn, entity_type, ENTITIES[entity_type].code_prefix)
    allowed = {k: payload[k] for k in
               ("prefix", "separator", "suffix", "padding", "next_value", "template",
                "reset_policy") if k in payload}
    if allowed:
        conn.execute(f"UPDATE sequence SET {', '.join(f'{k}=?' for k in allowed)}, "
                     f"updated_at=?, updated_by=? WHERE entity_type=?",
                     list(allowed.values()) + [db.now(), actor_of(x_actor, None), entity_type])
    db.log_change(conn, entity_type="sequence", entity_id=None, action="update",
                  actor=actor_of(x_actor, None), field_key=entity_type,
                  new_value=json.dumps(allowed, ensure_ascii=False))
    conn.commit()
    return {"ok": True, "next_preview": db.peek_next_code(conn, entity_type)}


@app.get("/api/users")
def users_get(conn=Depends(conn_dep)):
    return [dict(r) for r in conn.execute("SELECT * FROM app_user ORDER BY id")]


@app.post("/api/users")
def users_post(payload: dict = Body(...), conn=Depends(conn_dep)):
    if not payload.get("username"):
        raise HTTPException(422, "username is required")
    try:
        cur = conn.execute(
            "INSERT INTO app_user (username, display_name, email, role, is_active) VALUES (?,?,?,?,?)",
            (payload["username"], payload.get("display_name") or payload["username"],
             payload.get("email"), payload.get("role", "researcher"),
             1 if payload.get("is_active", True) else 0))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@app.delete("/api/users/{username}")
def users_delete(username: str, conn=Depends(conn_dep)):
    """Remove an application user; the last administrator cannot be removed.

    History is kept: ``change_log`` stores the actor *name*, not a foreign key, so
    removing an account never rewrites the audit trail.
    """
    row = conn.execute("SELECT * FROM app_user WHERE username=?", (username,)).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    if row["role"] == "admin":
        others = conn.execute("SELECT COUNT(*) c FROM app_user WHERE role='admin' AND username<>?",
                              (username,)).fetchone()["c"]
        if not others:
            raise HTTPException(409, "The last administrator cannot be removed")
    conn.execute("DELETE FROM app_user WHERE username=?", (username,))
    conn.commit()
    return {"ok": True, "username": username}


@app.get("/api/locales")
def locales_get(conn=Depends(conn_dep)):
    return [dict(r) for r in conn.execute("SELECT * FROM locale ORDER BY sort_order")]


@app.get("/api/locales/{code}/messages")
def locale_messages(code: str):
    path = STATIC / "js" / "locales" / f"{code}.json"
    if not path.exists():
        raise HTTPException(404, f"No message bundle for '{code}'")
    return json.loads(path.read_text(encoding="utf-8"))


# ===========================================================================
# saved views
# ===========================================================================
@app.get("/api/saved-views")
def saved_views(entity_type: str | None = None, conn=Depends(conn_dep)):
    sql = "SELECT * FROM saved_view"
    params: list[Any] = []
    if entity_type:
        sql += " WHERE entity_type=?"
        params.append(entity_type)
    sql += " ORDER BY id"
    return [{**dict(r), "filters": db.json_load(r["filters"], {}),
             "columns": db.json_load(r["columns"], [])}
            for r in conn.execute(sql, params)]


@app.post("/api/saved-views")
def saved_views_post(payload: dict = Body(...), conn=Depends(conn_dep),
                     x_actor: str | None = Header(None)):
    if not payload.get("name") or not payload.get("entity_type"):
        raise HTTPException(422, "name and entity_type are required")
    spec_of_any(payload["entity_type"])
    conn.execute(
        """INSERT INTO saved_view (name, entity_type, filters, columns, sort, is_shared, owner)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(name, entity_type) DO UPDATE SET filters=excluded.filters,
             columns=excluded.columns, sort=excluded.sort""",
        (payload["name"], payload["entity_type"], db.json_dump(payload.get("filters") or {}),
         db.json_dump(payload.get("columns")), db.json_dump(payload.get("sort")),
         1 if payload.get("is_shared", True) else 0, actor_of(x_actor, None)))
    conn.commit()
    # re-select so the client gets the id it needs for later updates and deletes
    row = conn.execute("SELECT * FROM saved_view WHERE name=? AND entity_type=?",
                       (payload["name"], payload["entity_type"])).fetchone()
    view = ({**dict(row), "filters": db.json_load(row["filters"], {}),
             "columns": db.json_load(row["columns"], [])} if row else None)
    return {"ok": True, "id": row["id"] if row else None, "view": view}


@app.delete("/api/saved-views/{view_id}")
def saved_views_delete(view_id: int, conn=Depends(conn_dep)):
    conn.execute("DELETE FROM saved_view WHERE id=?", (view_id,))
    conn.commit()
    return {"ok": True}


# ===========================================================================
# import
# ===========================================================================
@app.get("/api/import/template/{entity}")
def import_template(entity: str, format: str = "xlsx", lang: str = "en",
                    example: bool = True, conn=Depends(conn_dep)):
    spec = spec_of_any(entity)   # registry *or* military — one import system
    data, name, mime = transfer.template_bytes(conn, spec, format, lang, example)
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": content_disposition(name)})


@app.post("/api/import/preview")
async def import_preview(entity: str = Form(...), file: UploadFile = File(...),
                         conn=Depends(conn_dep)):
    spec = spec_of_any(entity)
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "The uploaded file is empty")
    try:
        columns, rows, fmt = transfer.parse_tabular(raw, file.filename or "")
    except Exception as exc:  # noqa: BLE001 - report parse problems to the user
        raise HTTPException(422, f"Could not read the file: {exc}")
    upload_id = uuid.uuid4().hex
    ext = Path(file.filename or "upload").suffix or f".{fmt}"
    db.atomic_write(STAGING / f"{upload_id}{ext}", raw)
    mapping = transfer.suggest_mapping(spec, columns)
    sample = rows[:8]
    unmapped = [c for c in columns if c not in mapping]
    required = [f.key for f in spec.fields if f.required and f.key != "code"]
    mapped_keys = set(mapping.values())
    return {
        "upload_id": upload_id, "filename": file.filename, "format": fmt,
        "total_rows": len(rows), "columns": columns, "sample": sample,
        "mapping": mapping, "unmapped_columns": unmapped,
        "missing_required": [k for k in required if k not in mapped_keys],
        "lookups": transfer._lookup_reference(conn, spec),
        "fields": fields_meta(spec),
        "encodings_tried": list(transfer.ENCODINGS),
    }


def _staged_rows(upload_id: str, entity: str) -> tuple[list[str], list[dict], str]:
    matches = list(STAGING.glob(f"{upload_id}.*"))
    if not matches:
        raise HTTPException(404, "Upload not found or expired — please upload the file again.")
    path = matches[0]
    return transfer.parse_tabular(path.read_bytes(), path.name)


@app.post("/api/import/validate")
def import_validate(payload: dict = Body(...), conn=Depends(conn_dep),
                    x_actor: str | None = Header(None)):
    entity = payload.get("entity")
    spec = spec_of_any(entity)
    upload_id = payload.get("upload_id")
    if upload_id:
        _cols, rows, fmt = _staged_rows(upload_id, entity)
        filename = payload.get("filename") or f"{upload_id}.{fmt}"
    else:
        raise HTTPException(422, "upload_id is required (upload the file first)")
    report = transfer.process_rows(
        conn, spec, rows, payload.get("mapping") or {}, mode=payload.get("mode", "create"),
        actor=actor_of(x_actor, payload.get("actor")), dry_run=True,
        default_status=payload.get("default_status"),
        match_on=payload.get("match_on"), reason=payload.get("reason"))
    report["upload_id"] = upload_id
    report["job_id"] = transfer.record_job(conn, spec, filename, fmt,
                                           payload.get("mode", "create"), True,
                                           report, actor_of(x_actor, payload.get("actor")),
                                           payload.get("mapping") or {})
    return report


@app.post("/api/import/commit")
def import_commit(payload: dict = Body(...), conn=Depends(conn_dep),
                  x_actor: str | None = Header(None)):
    entity = payload.get("entity")
    spec = spec_of_any(entity)
    upload_id = payload.get("upload_id")
    if not upload_id:
        raise HTTPException(422, "upload_id is required")
    _cols, rows, fmt = _staged_rows(upload_id, entity)
    # the row ceiling is an instance setting: refuse *before* writing anything
    ceiling = settings_mod.get(conn, "import.max_rows")
    if ceiling and len(rows) > ceiling:
        raise repo.ValidationError(
            f"This file has {len(rows):,} rows; import.max_rows is {ceiling:,}. "
            f"Split the file, or raise the setting in Settings → Import & export.")
    default_mode = payload.get("mode") or settings_mod.get(conn, "import.default_mode")
    report = transfer.process_rows(
        conn, spec, rows, payload.get("mapping") or {}, mode=default_mode,
        actor=actor_of(x_actor, payload.get("actor")), dry_run=False,
        default_status=payload.get("default_status"),
        match_on=payload.get("match_on"), reason=payload.get("reason") or "import")
    report["upload_id"] = upload_id
    report["job_id"] = transfer.record_job(conn, spec, payload.get("filename") or upload_id,
                                           fmt, default_mode, False, report,
                                           actor_of(x_actor, payload.get("actor")),
                                           payload.get("mapping") or {})
    if settings_mod.get(conn, "maintenance.vacuum_after_import"):
        conn.commit()
        conn.execute("VACUUM")
        report["vacuumed"] = True
    return report


@app.get("/api/import/jobs")
def import_jobs(limit: int = 25, conn=Depends(conn_dep)):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM import_job ORDER BY started_at DESC LIMIT ?", (limit,))]


@app.get("/api/import/jobs/{job_id}")
def import_job_get(job_id: str, conn=Depends(conn_dep)):
    row = conn.execute("SELECT * FROM import_job WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Import job not found")
    d = dict(row)
    d["report"] = db.json_load(d["report"], {})
    d["mapping"] = db.json_load(d["mapping"], {})
    return d


# ===========================================================================
# export
# ===========================================================================
def _export_response(conn, entity: str, payload: dict, fmt: str, columns, lang,
                    resolve: bool, title=None):
    spec = spec_of_any(entity)
    data, name, mime = transfer.export_bytes(conn, spec, payload, fmt, columns, lang,
                                             resolve, title)
    db.log_change(conn, entity_type=spec.key, entity_id=None, action="update",
                  actor=payload.get("actor") or "researcher", field_key="__export__",
                  new_value=f"{fmt} · {len(data)} bytes",
                  notes=json.dumps({k: payload.get(k) for k in
                                    ("q", "where", "sort", "order")}, ensure_ascii=False)[:500])
    conn.commit()
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": content_disposition(name)})


@app.get("/api/export/{entity}")
def export_get(entity: str, format: str = "csv", columns: str | None = None,
               lang: str = "en", resolve: bool = True, q: str | None = None,
               sort: str | None = None, order: str = "desc", page_size: int = 10000,
               conn=Depends(conn_dep)):
    payload = {"q": q, "sort": sort, "order": order, "page_size": page_size}
    cols = [c for c in (columns or "").split(",") if c] or None
    return _export_response(conn, entity, payload, format, cols, lang, resolve)


@app.post("/api/export/{entity}")
def export_post(entity: str, payload: dict = Body(default={}), conn=Depends(conn_dep)):
    """Export the current selection.

    The whole body is forwarded as the filter payload (minus the output options):
    the browser sends ``{"format": "xlsx", "filters": {...}, "where": [...],
    "q": "...", "sort": ...}`` and unwrapping ``filters`` here used to drop the
    nested form on the floor — the export then contained *every* record while the
    screen showed a filtered list.
    """
    fmt = payload.get("format", "xlsx")
    body = {k: v for k, v in payload.items()
            if k not in ("format", "columns", "lang", "resolve", "title", "actor")}
    return _export_response(conn, entity, body, fmt, payload.get("columns"),
                            payload.get("lang", "en"), payload.get("resolve", True),
                            payload.get("title"))


# ===========================================================================
# media (portraits / entity imagery)
# ===========================================================================
MEDIA_DIR = db.UPLOAD_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif", "image/svg+xml"}


@app.post("/api/media")
async def media_upload(file: UploadFile = File(...)):
    """Store an image and return a stable URL usable by any ``*_url`` field."""
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "The uploaded file is empty")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "Image is larger than 12 MB")
    ext = (Path(file.filename or "").suffix or ".png").lower()
    mime = (file.content_type or mimetypes.guess_type("x" + ext)[0] or "").lower()
    if mime not in IMAGE_MIME and ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg"}:
        raise HTTPException(415, "Only image files can be uploaded as media")
    name = f"{uuid.uuid4().hex}{ext}"
    db.atomic_write(MEDIA_DIR / name, raw)
    return {"ok": True, "url": f"/api/media/{name}", "filename": file.filename,
            "size_bytes": len(raw), "mime": mime}


@app.get("/api/media/{name}")
def media_serve(name: str):
    safe = Path(name).name
    path = MEDIA_DIR / safe
    if not path.exists():
        raise HTTPException(404, "Media not found")
    return FileResponse(path, media_type=mimetypes.guess_type(safe)[0] or "application/octet-stream",
                        headers={"Cache-Control": "public, max-age=604800"})


# ===========================================================================
# attachments
# ===========================================================================
@app.post("/api/{entity}/{rec_id}/attachments")
async def attachment_upload(entity: str, rec_id: int, file: UploadFile = File(...),
                            kind: str = Form("other"), note: str = Form(""),
                            conn=Depends(conn_dep), x_actor: str | None = Header(None)):
    spec = spec_of(entity)
    repo.get_record(conn, spec, rec_id)
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 25 MB")
    stored = f"{uuid.uuid4().hex}{Path(file.filename or '').suffix}"
    db.atomic_write(db.UPLOAD_DIR / stored, raw)
    cur = conn.execute(
        """INSERT INTO attachment (entity_type, entity_id, filename, stored_name, mime,
              size_bytes, kind, note, uploaded_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (spec.key, rec_id, file.filename or stored, stored,
         file.content_type or mimetypes.guess_type(stored)[0], len(raw), kind, note,
         actor_of(x_actor, None)))
    db.log_change(conn, entity_type=spec.key, entity_id=rec_id, action="update",
                  actor=actor_of(x_actor, None), field_key="attachment",
                  new_value=file.filename or stored)
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@app.get("/api/attachments/{att_id}/download")
def attachment_download(att_id: int, conn=Depends(conn_dep)):
    row = conn.execute("SELECT * FROM attachment WHERE id=?", (att_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Attachment not found")
    path = db.UPLOAD_DIR / row["stored_name"]
    if not path.exists():
        raise HTTPException(404, "File missing on disk")
    return FileResponse(path, filename=row["filename"],
                        media_type=row["mime"] or "application/octet-stream")


@app.delete("/api/attachments/{att_id}")
def attachment_delete(att_id: int, conn=Depends(conn_dep)):
    row = conn.execute("SELECT * FROM attachment WHERE id=?", (att_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Attachment not found")
    conn.execute("DELETE FROM attachment WHERE id=?", (att_id,))
    db.safe_unlink(db.UPLOAD_DIR / row["stored_name"])
    conn.commit()
    return {"ok": True}


# ===========================================================================
# tags (specialisations / expertise / keywords)
# ===========================================================================
@app.get("/api/tags")
def tags_get(domain: str | None = None, conn=Depends(conn_dep)):
    sql = """SELECT t.*, (SELECT COUNT(*) FROM entity_tag et WHERE et.tag_id=t.id) used
             FROM tag t"""
    params: list[Any] = []
    if domain:
        sql += " WHERE t.domain=?"
        params.append(domain)
    sql += " ORDER BY t.domain, t.sort_order, t.id"
    return [dict(r) for r in conn.execute(sql, params)]


@app.post("/api/tags")
def tags_post(payload: dict = Body(...), conn=Depends(conn_dep)):
    if not payload.get("label_en") or not payload.get("domain"):
        raise HTTPException(422, "domain and label_en are required")
    try:
        cur = conn.execute(
            "INSERT INTO tag (domain, label_en, label_ar, sort_order) VALUES (?,?,?,?)",
            (payload["domain"], payload["label_en"], payload.get("label_ar"),
             int(payload.get("sort_order") or 100)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This tag already exists in that domain")
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@app.delete("/api/tags/{tag_id}")
def tags_delete(tag_id: int, conn=Depends(conn_dep)):
    """Remove a tag and every link that points at it (declared before the generic
    ``/api/{entity}/{rec_id}`` route, or ``tags`` would be read as an entity)."""
    row = conn.execute("SELECT * FROM tag WHERE id=?", (tag_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Tag not found")
    conn.execute("DELETE FROM entity_tag WHERE tag_id=?", (tag_id,))
    conn.execute("DELETE FROM tag WHERE id=?", (tag_id,))
    conn.commit()
    return {"ok": True, "id": tag_id}


# ---- citation / evidence routes must precede the generic /api/{entity}/{id} ----
@app.delete("/api/citations/{link_id}")
def citation_remove(link_id: int, conn=Depends(conn_dep),
                    x_actor: str | None = Header(None)):
    return repo.remove_source_link(conn, link_id, actor_of(x_actor, None))


# ===========================================================================
# evidence links — one source, many claims (entity, field, or relationship)
# ===========================================================================
@app.get("/api/evidence")
def evidence_list(entity_type: str | None = None, entity_id: int | None = None,
                  relationship_id: int | None = None, source_id: int | None = None,
                  conn=Depends(conn_dep)):
    """Every claim a source makes about a target — or, mirrored, every claim
    one source makes at all.

    `?relationship_id=` and `?entity_type=&entity_id=` are the two addressable
    targets; `?source_id=` turns the question around: what does this source
    say, and about which records? Asking for a target *and* a source at once
    is refused rather than guessed at.
    """
    if source_id is not None:
        if relationship_id is not None or entity_id is not None:
            raise HTTPException(422, "Ask for one question: source_id, or a target")
        rows = repo.get_claims_by_source(conn, source_id)
    else:
        if relationship_id is not None and entity_id is not None:
            raise HTTPException(422, "Ask for one target: relationship_id or entity_type+entity_id")
        if relationship_id is None and entity_id is None:
            raise HTTPException(422, "source_id, relationship_id, or entity_type with entity_id, is required")
        try:
            rows = repo.get_evidence(conn, entity_type=entity_type, entity_id=entity_id,
                                     relationship_id=relationship_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    counts = {"supports": 0, "contradicts": 0, "contextualizes": 0}
    for ev in rows:
        counts[ev["support_type"]] = counts.get(ev["support_type"], 0) + 1
    return {"ok": True, "evidence": rows, "count": len(rows), "counts": counts,
            "disputed": counts["contradicts"] > 0,
            "support_types": list(repo.SUPPORT_TYPES)}


@app.get("/api/evidence/support-types")
def evidence_support_types(conn=Depends(conn_dep)):
    """The controlled list, so a client never hard-codes the three words."""
    rows = conn.execute(
        """SELECT code, label_en, label_ar, sort_order FROM lookup
           WHERE domain='evidence_support_type' AND is_active=1 ORDER BY sort_order""").fetchall()
    return {"ok": True, "support_types": [dict(r) for r in rows]}


@app.post("/api/evidence")
def evidence_add(payload: dict = Body(...), conn=Depends(conn_dep),
                 x_actor: str | None = Header(None)):
    """Attach a source to a claim. A contradiction is a separate row, never an overwrite."""
    if not payload.get("source_id"):
        raise HTTPException(422, "source_id is required")
    rel = payload.get("relationship_id")
    ent = payload.get("entity_id")
    if rel is None and ent is None:
        raise HTTPException(422, "Evidence needs exactly one target: relationship_id, "
                                 "or entity_type with entity_id")
    if rel is not None and ent is not None:
        raise HTTPException(422, "Evidence needs exactly one target, not both")
    try:
        return repo.add_evidence(
            conn, int(payload["source_id"]),
            entity_type=payload.get("entity_type"), entity_id=ent,
            relationship_id=int(rel) if rel is not None else None,
            field_key=payload.get("field_key"),
            supported_claim=payload.get("supported_claim"),
            page_or_timestamp=payload.get("page_or_timestamp"),
            support_type=str(payload.get("support_type") or "supports"),
            verification=payload.get("verification") or payload.get("verification_status"),
            reviewer=payload.get("reviewer"), review_date=payload.get("review_date"),
            note=payload.get("note") or payload.get("notes"),
            actor=actor_of(x_actor, None))
    except repo.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except repo.ValidationError as exc:
        raise HTTPException(422, str(exc)) from None


@app.get("/api/relationship/{rel_id}/evidence")
def relationship_evidence(rel_id: int, conn=Depends(conn_dep)):
    """A relationship row with its evidence list, counts and dispute flag."""
    try:
        return {"ok": True, **repo.get_relationship_evidence(conn, rel_id)}
    except repo.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


# ===========================================================================
# external / authority identifiers  (VIAF, Wikidata, ORCID, legacy numbers)
# ===========================================================================
@app.get("/api/{entity}/{rec_id}/external-ids")
def external_ids_get(entity: str, rec_id: int, conn=Depends(conn_dep)):
    spec_of(entity)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM entity_external_id WHERE entity_type=? AND entity_id=? ORDER BY id",
        (entity, rec_id))]


@app.post("/api/{entity}/{rec_id}/external-ids")
def external_ids_post(entity: str, rec_id: int, payload: dict = Body(...),
                      conn=Depends(conn_dep), x_actor: str | None = Header(None)):
    spec_of(entity)
    repo.get_record(conn, ENTITIES[entity], rec_id)
    if not payload.get("scheme") or not payload.get("value"):
        raise HTTPException(422, "scheme and value are required")
    try:
        cur = conn.execute(
            """INSERT INTO entity_external_id (entity_type, entity_id, scheme, value, url, note)
               VALUES (?,?,?,?,?,?)""",
            (entity, rec_id, payload["scheme"], payload["value"],
             payload.get("url"), payload.get("note")))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This identifier already exists for the record")
    db.log_change(conn, entity_type=entity, entity_id=rec_id, action="update",
                  actor=actor_of(x_actor, None), field_key="external_id",
                  new_value=f'{payload["scheme"]}:{payload["value"]}')
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@app.delete("/api/external-ids/{ext_id}")
def external_ids_delete(ext_id: int, conn=Depends(conn_dep),
                        x_actor: str | None = Header(None)):
    row = conn.execute("SELECT * FROM entity_external_id WHERE id=?", (ext_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Identifier not found")
    conn.execute("DELETE FROM entity_external_id WHERE id=?", (ext_id,))
    db.log_change(conn, entity_type=row["entity_type"], entity_id=row["entity_id"],
                  action="update", actor=actor_of(x_actor, None), field_key="external_id",
                  old_value=f'{row["scheme"]}:{row["value"]}')
    conn.commit()
    return {"ok": True}


# ===========================================================================
# duplicate detection & merge  (must precede /api/{entity}/{id})
# ===========================================================================
@app.post("/api/{entity}/kpi")
def entity_kpi(entity: str, payload: dict = Body(default={}), conn=Depends(conn_dep)):
    """Headline figures for the current selection (the KPI strip above a list)."""
    spec = spec_of_any(entity)
    return repo.kpi_summary(conn, spec, payload or {})


@app.get("/api/{entity}/duplicates")
def duplicates(entity: str, limit: int = 50, offset: int = 0, conn=Depends(conn_dep)):
    if is_mil(entity):
        spec = MIL_SPECS[entity]
        title_col = spec.name_fields[0]
        rows = conn.execute(
            f"SELECT {title_col} AS label, COUNT(*) AS n FROM {spec.table} "
            f"WHERE {title_col} IS NOT NULL AND {title_col} != '' "
            f"GROUP BY {title_col} HAVING COUNT(*) > 1 "
            f"ORDER BY n DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        groups = [{"label": r["label"], "count": r["n"]} for r in rows]
        return {"entity": entity, "groups": groups, "total": len(groups)}
    spec = spec_of(entity)
    groups, total = repo.duplicate_groups(conn, spec, limit=limit, offset=offset)
    return {"entity": entity, "groups": groups, "total": total}


@app.post("/api/{entity}/{rec_id}/merge")
def merge(entity: str, rec_id: int, payload: dict = Body(...),
          conn=Depends(conn_dep), x_actor: str | None = Header(None)):
    spec = spec_of(entity)
    ids = payload.get("merge_ids") or payload.get("ids") or []
    if not ids:
        raise HTTPException(422, "merge_ids is required")
    return repo.merge_records(conn, spec, rec_id, ids,
                              actor=actor_of(x_actor, None),
                              reason=payload.get("reason"),
                              dry_run=bool(payload.get("dry_run")))


# ---- maintenance routes must precede the generic /api/{entity}/{id} routes ----
# ===========================================================================
# maintenance
# ===========================================================================
@app.post("/api/maintenance/reindex")
def maintenance_reindex(conn=Depends(conn_dep)):
    n = db.rebuild_index(conn)
    conn.commit()
    return {"ok": True, "documents": n}


@app.post("/api/maintenance/vacuum")
def maintenance_vacuum(conn=Depends(conn_dep)):
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    return {"ok": True, "size_bytes": db.DB_PATH.stat().st_size}


# ---------------------------------------------------------------------------
# clear all data — the production reset.  Static/reference/configuration data
# (lookups, vocabulary, users, settings, numbering series, saved views, search
# configuration, archive metadata) stays intact, and so do the append-only
# audit ledgers (change_log is DB-enforced append-only; audit_log and
# naming_adjustment_log follow the same accountability contract — an audit
# trail can never be lost by clicking a button; retention pruning governs it).
# Every *record* goes.  The destructive step is preceded by an archive-aside
# copy, so nothing a person ever entered is lost — it leaves the working
# database, not the world.
# ---------------------------------------------------------------------------
CLEAR_CONFIRM_PHRASE = "CLEAR ALL DATA"

CLEAR_PRESERVE = {
    "schema_migration", "lookup", "lookup_domain", "locale", "app_user",
    "setting", "sequence", "naming_series_option", "saved_view", "app_meta",
    "mil_meta", "search_doc_config", "sqlite_sequence", "backup", "session",
    "change_log", "audit_log", "naming_adjustment_log",
}


@app.post("/api/maintenance/clear-data")
def maintenance_clear_data(payload: dict = Body(default={}), conn=Depends(conn_dep),
                           x_actor: str | None = Header(None)):
    """Wipe every record from the working database; keep static data intact.

    Requires ``{"confirm": "CLEAR ALL DATA"}`` — the exact phrase — so the
    action can never fire from a stray click.  Before anything is deleted the
    live database is copied to ``data/<name>-archive-<stamp>-preclear.db`` and
    ``data/uploads`` is moved aside as ``uploads-<stamp>`` (renamed, never
    deleted), then numbering counters are reset and the database is compacted.
    """
    phrase = str(payload.get("confirm") or "").strip()
    if phrase != CLEAR_CONFIRM_PHRASE:
        raise repo.ValidationError(
            'This removes every record from the database (static/reference data is '
            'kept). Type "CLEAR ALL DATA" to confirm.')
    actor = actor_of(x_actor, None) or "researcher"
    stamp = time.strftime("%Y%m%d-%H%M%S")

    # 1) archive-aside: copy the live db and move uploads out of the way
    def _unique(path):
        p, n = path, 2
        while p.exists():
            p = path.with_name(f"{path.name}-{n}")
            n += 1
        return p

    archive = _unique(db.DB_PATH.with_name(f"{db.DB_PATH.stem}-archive-{stamp}-preclear.db"))
    conn.commit()
    dst = sqlite3.connect(archive)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    uploads_as = None
    if db.UPLOAD_DIR.exists() and any(db.UPLOAD_DIR.iterdir()):
        uploads_as = _unique(db.UPLOAD_DIR.with_name(f"{db.UPLOAD_DIR.name}-{stamp}"))
        db.UPLOAD_DIR.rename(uploads_as)
    db.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 2) wipe every table that is not static/reference/configuration.
    # The wipe is order-independent: enforcement is switched off for the
    # transaction (a no-op inside one, so it must precede the first DELETE).
    # Because every non-preserved table ends empty, no dangling reference can
    # survive — the database is consistent again the moment the wipe commits.
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    cleared: dict[str, int] = {}
    for t in sorted(tables):
        # FTS5 shadow tables are emptied through `search_doc` itself, never
        # directly (deleting from a shadow corrupts the index)
        if t in CLEAR_PRESERVE or t.startswith("search_doc_"):
            continue
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if n:
            conn.execute(f"DELETE FROM {t}")
        cleared[t] = n

    # 3) reset the automatic numbering machinery; the series definitions stay
    conn.execute("UPDATE sequence SET next_value = 1")
    conn.execute("DELETE FROM mil_meta WHERE key = 'bulk_loaded'")   # kv flag: absent = off

    conn.commit()
    db.log_change(conn, entity_type="setting", entity_id=None,
                  entity_code="maintenance.clear_data", action="bulk", actor=actor,
                  reason="clear all data",
                  new_value=str(sum(cleared.values())),
                  notes=f"archived as {archive.name}"
                        + (f"; uploads moved to {uploads_as.name}" if uploads_as else ""))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.execute("PRAGMA foreign_keys = ON")
    return {"ok": True, "archive": archive.name,
            "uploads_archived_as": uploads_as.name if uploads_as else None,
            "cleared": cleared, "cleared_rows": sum(cleared.values()),
            "preserved": sorted(CLEAR_PRESERVE)}


@app.post("/api/maintenance/prune")
def maintenance_prune(payload: dict = Body(default={}), conn=Depends(conn_dep),
                      x_actor: str | None = Header(None)):
    """Delete audit rows older than ``audit.retention_days``.

    The safe default is 0 — keep everything — and the endpoint refuses to run while
    the setting is 0, so an audit trail can never be lost by clicking a button.
    ``{"days": N, "dry_run": true}`` previews the count without deleting.
    """
    configured = settings_mod.get(conn, "audit.retention_days")
    days = int(payload.get("days") or configured or 0)
    if days <= 0:
        raise repo.ValidationError(
            "Nothing to prune: audit.retention_days is 0, which keeps the audit trail "
            "forever. Set a retention period first (Settings → Audit & retention).")
    cutoff = f"-{days} days"
    counted = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE changed_at < datetime('now', ?)",
        (cutoff,)).fetchone()[0]
    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "would_remove": counted, "days": days}
    conn.execute("DELETE FROM change_log WHERE changed_at < datetime('now', ?)", (cutoff,))
    conn.commit()
    db.log_change(conn, entity_type="setting", entity_id=None, entity_code="audit.retention_days",
                  action="update", actor=actor_of(x_actor, None), reason="retention prune",
                  new_value=str(counted), notes=f"pruned {counted} audit row(s) older than {days}d")
    conn.commit()
    return {"ok": True, "removed": counted, "days": days}


@app.post("/api/maintenance/purge-working-files")
def maintenance_purge_working_files(payload: dict = Body(default={})):
    """Remove import staging files and uploaded files nothing points at.

    Two kinds of file accumulate without anybody deciding to keep them:

    * **staging** — the import wizard writes every upload to
      ``data/staging/<id>.<ext>`` and only deletes it when the wizard finishes.
      An abandoned wizard leaves the file behind for ever.
    * **media** — a file in ``data/uploads/media`` whose row in ``attachment``
      is gone (a deleted record, a hard delete, a cleaned-up test) is unreachable
      from anywhere in the interface.

    ``{"older_than_hours": 24, "dry_run": true}`` previews; the age guard means a
    running wizard is never pulled out from under the person using it. Nothing
    that is referenced by a row is ever removed — the reference test is a query,
    not a guess.
    """
    hours = max(0, int(payload.get("older_than_hours", 24)))
    dry = bool(payload.get("dry_run"))
    cutoff = time.time() - hours * 3600
    staging_files, staging_bytes = [], 0
    for path in STAGING.iterdir():
        try:
            if not path.is_file() or path.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        staging_files.append(path)
        staging_bytes += path.stat().st_size

    boot = db.connect()
    try:
        live = {row[0] for row in boot.execute("SELECT stored_name FROM attachment")}
    finally:
        boot.close()
    media_dir = db.DATA_DIR / "uploads" / "media"
    orphan_files, orphan_bytes = [], 0
    if media_dir.is_dir():
        for path in media_dir.iterdir():
            if not path.is_file() or path.name in live:
                continue
            try:
                if path.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            orphan_files.append(path)
            orphan_bytes += path.stat().st_size

    result = {
        "ok": True, "dry_run": dry, "older_than_hours": hours,
        "staging": {"files": len(staging_files), "bytes": staging_bytes},
        "orphan_media": {"files": len(orphan_files), "bytes": orphan_bytes},
        "bytes_reclaimable": staging_bytes + orphan_bytes,
    }
    if dry:
        return result
    removed = 0
    for path in staging_files + orphan_files:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    result["files_removed"] = removed
    result["bytes_freed"] = staging_bytes + orphan_bytes
    return result


@app.get("/api/maintenance/backup")
def maintenance_backup(include_files: bool | None = None, conn=Depends(conn_dep)):
    """One archive with a consistent DB snapshot plus every uploaded file.

    ``include_files`` defaults to the instance setting
    ``maintenance.backup_includes_files`` (true unless an operator turned it off);
    passing ``?include_files=false`` makes a database-only archive on demand.
    """
    if include_files is None:
        include_files = bool(settings_mod.get(conn, "maintenance.backup_includes_files"))
    stamp = db.now().replace(":", "").replace("-", "")[0:15]
    buf = io.BytesIO()
    file_count, file_bytes = 0, 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        snapshot = db.DATA_DIR / f"_backup_{stamp}.db"
        dest = sqlite3.connect(snapshot)
        conn.backup(dest)
        dest.close()
        zf.write(snapshot, "registry.db")
        if include_files and db.UPLOAD_DIR.exists():
            for path in sorted(db.UPLOAD_DIR.rglob("*")):
                if not path.is_file():
                    continue
                arc = Path("uploads") / path.relative_to(db.UPLOAD_DIR)
                zf.write(path, arc.as_posix())
                file_count += 1
                file_bytes += path.stat().st_size
        zf.writestr("manifest.json", json.dumps({
            "created_at": db.now(), "schema_version": "1.0.0",
            "files_included": include_files, "file_count": file_count,
            "file_bytes": file_bytes,
            "note": "Consistent SQLite snapshot created with the online backup API; "
                    "uploads/ holds attachments and media images."},
            ensure_ascii=False, indent=2))
        db.safe_unlink(snapshot)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      content_disposition(f"siraj-backup-{stamp}.zip")})


@app.get("/api/maintenance/export-all")
def maintenance_export_all(conn=Depends(conn_dep)):
    """Full JSON dump of every table (portable archive / migration seed)."""
    out: dict[str, Any] = {"meta": {"exported_at": db.now(), "version": "1.0.0"}}
    for table in ("lookup_domain", "lookup", "locale", "app_user", "setting", "sequence",
                  "source", "place", "institution", "person", "person_position", "event",
                  "relationship", "tag", "entity_tag", "source_link", "saved_view"):
        out[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    data = json.dumps(out, ensure_ascii=False, indent=2).encode()
    return Response(content=data, media_type="application/json",
                    headers={"Content-Disposition":
                             content_disposition("siraj-full-dump.json")})


# ===========================================================================
# generic entity CRUD  (declared AFTER the specific routes above)
# ===========================================================================
@app.post("/api/{entity}/query")
def entity_query(entity: str, payload: dict = Body(default={}), conn=Depends(conn_dep)):
    """List records. `query` may carry the typed query string instead of JSON filters.

    A visible, text form of a filter has three uses the builder cannot serve: it
    survives in a URL, it can be sent to a colleague, and it can be re-read a year
    later.  Explicit body keys still win over the string, so a client can pin a
    page or a page size while the user edits the query.
    """
    spec = spec_of_any(entity)
    payload = dict(payload or {})
    if isinstance(payload.get("query"), str) and payload["query"].strip():
        if is_mil(entity):
            raise HTTPException(422, "typed queries are not supported for military entities")
        compiled = querylang.parse_for(spec, payload["query"])
        resolved, extra = querylang.resolve(conn, spec, compiled["payload"])
        merged = dict(resolved)
        merged.update({k: v for k, v in payload.items() if k != "query"})
        merged["_query"] = {"echo": compiled["echo"],
                            "warnings": compiled["warnings"] + extra,
                            "unknown": compiled["unknown"]}
        return repo.list_records(conn, spec, merged)
    out = repo.list_records(conn, spec, payload)
    if is_mil(entity):
        for item in out.get("items", []):
            mil_query_shim(item, spec)
    return out


@app.post("/api/query/parse")
def query_parse(payload: dict = Body(...), conn=Depends(conn_dep)):
    """Compile a query string without running it — what the query bar shows."""
    spec = spec_of(str(payload.get("entity") or "person"))
    try:
        compiled = querylang.parse_for(spec, str(payload.get("query") or ""))
    except querylang.QueryError as exc:
        raise HTTPException(422, str(exc)) from None
    resolved, extra = querylang.resolve(conn, spec, compiled["payload"])
    return {"ok": True, "entity": spec.key, "echo": compiled["echo"],
            "payload": resolved, "warnings": compiled["warnings"] + extra,
            "unknown": compiled["unknown"]}


@app.get("/api/query/parse")
def query_parse_get(entity: str = "person", q: str = "", conn=Depends(conn_dep)):
    return query_parse({"entity": entity, "query": q}, conn=conn)


@app.post("/api/query/render")
def query_render(payload: dict = Body(...), conn=Depends(conn_dep)):
    """The inverse: a filter payload written back as a query string."""
    spec = spec_of(str(payload.get("entity") or "person"))
    filters = dict(payload.get("payload") or payload.get("filters") or {})
    filters = repo.normalize_filters(filters)
    # the engine speaks ids; a query a person reads speaks codes and names
    if filters.get("status_ids"):
        marks = ",".join("?" * len(filters["status_ids"]))
        codes = [r["code"] for r in conn.execute(
            f"SELECT code FROM lookup WHERE domain='record_status' AND id IN ({marks})",
            list(filters["status_ids"]))]
        filters["status_codes"] = codes
    if filters.get("tag_ids"):
        marks = ",".join("?" * len(filters["tag_ids"]))
        labels = [r["label_en"] or r["label_ar"] for r in conn.execute(
            f"SELECT label_en, label_ar FROM tag WHERE id IN ({marks})",
            list(filters["tag_ids"]))]
        filters["tag_labels"] = [x for x in labels if x]
    text, unsupported = querylang.to_string(filters, spec)
    return {"ok": True, "entity": spec.key, "query": text, "unsupported": unsupported}


@app.get("/api/{entity}")
def entity_list(entity: str, q: str | None = None, page: int = 1, page_size: int = 25,
                sort: str | None = None, order: str = "desc",
                include_deleted: bool = False, conn=Depends(conn_dep)):
    spec = spec_of(entity)
    return repo.list_records(conn, spec, {
        "q": q, "page": page, "page_size": page_size, "sort": sort, "order": order,
        "include_deleted": include_deleted})


@app.get("/api/{entity}/next-code")
def entity_next_code(entity: str, conn=Depends(conn_dep)):
    if is_mil(entity):
        from ..military import naming
        from ..military.naming import NamingError
        try:
            preview = naming.preview(conn, entity, {})
            return {"entity": entity, "code": preview["next_value"]}
        except NamingError:
            return {"entity": entity, "code": ""}
    spec_of(entity)
    return {"entity": entity, "code": db.peek_next_code(conn, entity)}


@app.post("/api/{entity}")
def entity_create(entity: str, payload: dict = Body(...), conn=Depends(conn_dep),
                  x_actor: str | None = Header(None),
                  x_military_role: str | None = Header(None)):
    if is_mil(entity):
        _mil_write_guard(x_military_role)
        # meta keys (_reason, _source_id, actor ...) are registry conveniences —
        # the military service validates its fields strictly, so drop them here
        payload = {k: v for k, v in payload.items() if not k.startswith("_") and k != "actor"}
        rec = _mil_write(conn, mil_service.create, entity, payload,
                         actor_of(x_actor, None) or "researcher")
        return {"ok": True, "record": mil_query_shim(rec, MIL_SPECS[entity])}
    spec = spec_of(entity)
    rec = repo.create_record(conn, spec, payload, actor_of(x_actor, payload.get("actor")),
                             payload.get("_reason"), payload.get("_source_id"))
    return {"ok": True, "record": rec}


@app.get("/api/{entity}/{rec_id}")
def entity_get(entity: str, rec_id: int, include_deleted: bool = False,
               conn=Depends(conn_dep)):
    if is_mil(entity):
        rec = mil_service.get_record(conn, entity, rec_id)
        if rec is None:
            raise HTTPException(404, f"{entity} {rec_id} not found")
        return mil_query_shim(rec, MIL_SPECS[entity])
    return repo.get_record(conn, spec_of(entity), rec_id, include_deleted)


@app.put("/api/{entity}/{rec_id}")
@app.patch("/api/{entity}/{rec_id}")
def entity_update(entity: str, rec_id: int, payload: dict = Body(...),
                  conn=Depends(conn_dep), x_actor: str | None = Header(None),
                  x_military_role: str | None = Header(None)):
    if is_mil(entity):
        _mil_write_guard(x_military_role)
        payload = {k: v for k, v in payload.items() if not k.startswith("_") and k != "actor"}
        rec = _mil_write(conn, mil_service.update, entity, rec_id, payload,
                         actor_of(x_actor, None) or "researcher")
        return {"ok": True, "record": mil_query_shim(rec, MIL_SPECS[entity])}
    spec = spec_of(entity)
    rec = repo.update_record(
        conn, spec, rec_id, payload, actor_of(x_actor, payload.get("actor")),
        payload.get("_reason"), payload.get("_source_id"),
        payload.get("_version") if payload.get("_version") is not None else None)
    return {"ok": True, "record": rec}


@app.delete("/api/{entity}/{rec_id}")
def entity_delete(entity: str, rec_id: int, hard: bool = False, reason: str | None = None,
                  conn=Depends(conn_dep), x_actor: str | None = Header(None),
                  x_military_role: str | None = Header(None)):
    if is_mil(entity):
        _mil_write_guard(x_military_role)
        _mil_write(conn, mil_service.delete, entity, rec_id,
                   actor_of(x_actor, None) or "researcher")
        return {"ok": True, "deleted": rec_id}
    spec = spec_of(entity)
    if hard:
        return repo.hard_delete(conn, spec, rec_id, actor_of(x_actor, None), reason)
    return repo.soft_delete(conn, spec, rec_id, actor_of(x_actor, None), reason)


@app.post("/api/{entity}/{rec_id}/restore")
def entity_restore(entity: str, rec_id: int, conn=Depends(conn_dep),
                   x_actor: str | None = Header(None)):
    if is_mil(entity):
        raise HTTPException(422, "military records are deleted outright; nothing to restore")
    return repo.restore(conn, spec_of(entity), rec_id, actor_of(x_actor, None))


@app.post("/api/{entity}/bulk")
def entity_bulk(entity: str, payload: dict = Body(...), conn=Depends(conn_dep),
                x_actor: str | None = Header(None),
                x_military_role: str | None = Header(None)):
    if is_mil(entity):
        _mil_write_guard(x_military_role)
        ids = payload.get("ids") or []
        action = payload.get("action")
        actor = actor_of(x_actor, None) or "researcher"
        if not ids:
            raise HTTPException(422, "ids is required")
        ok = failed = 0
        for rid in ids:
            try:
                if action == "delete":
                    mil_service.delete(conn, entity, int(rid), actor)
                elif action == "status" and payload.get("patch") is not None:
                    mil_service.update(conn, entity, int(rid),
                                       dict(payload["patch"]), actor)
                else:
                    raise HTTPException(422, f"unsupported bulk action '{action}'")
                ok += 1
            except Exception:  # noqa: BLE001 - per-row isolation, like the importer
                failed += 1
        conn.commit()
        return {"ok": ok, "failed": failed}
    spec = spec_of(entity)
    ids = payload.get("ids") or []
    action = payload.get("action")
    if not ids:
        raise HTTPException(422, "ids is required")
    return repo.bulk_action(conn, spec, ids, action, payload.get("patch"),
                            actor_of(x_actor, None), payload.get("reason"))


@app.get("/api/{entity}/{rec_id}/history")
def entity_history(entity: str, rec_id: int, conn=Depends(conn_dep)):
    return repo.get_history(conn, spec_of(entity).key, rec_id)


@app.post("/api/{entity}/{rec_id}/citations")
def citation_add(entity: str, rec_id: int, payload: dict = Body(...),
                 conn=Depends(conn_dep), x_actor: str | None = Header(None)):
    spec = spec_of(entity)
    if not payload.get("source_id"):
        raise HTTPException(422, "source_id is required")
    repo.get_record(conn, spec, rec_id)
    try:
        return repo.add_source_link(conn, spec.key, rec_id, int(payload["source_id"]),
                                    payload.get("note"), payload.get("field_key"),
                                    actor_of(x_actor, None),
                                    supported_claim=payload.get("supported_claim"),
                                    page_or_timestamp=payload.get("page_or_timestamp"),
                                    support_type=str(payload.get("support_type") or "supports"),
                                    verification=payload.get("verification"),
                                    reviewer=payload.get("reviewer"),
                                    review_date=payload.get("review_date"))
    except repo.ValidationError as exc:
        raise HTTPException(422, str(exc)) from None


# ===========================================================================
# static application
# ===========================================================================
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
