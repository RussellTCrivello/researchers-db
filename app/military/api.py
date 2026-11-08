"""Military Organization — HTTP API (mounted inside the SIRAJ FastAPI app).

Roles are enforced server-side on every request (design record §8.9):
``X-Military-Role: viewer | staff | admin`` — default ``admin`` so first-run
tooling works; deployments gate the header upstream.  The SIRAJ auth
middleware already covers ``/api/*`` when a registry token is configured.

Route order matters: specific paths (``naming/*``, ``audit/*``, ``sample``,
trees) are registered before the generic ``/{entity}[/{record_id}]`` CRUD so
they are never shadowed by it.
"""
from __future__ import annotations

from typing import Any, Iterator

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from . import naming, seed, service
from .rules import RuleViolation
from .service import ENTITY_SPECS, ServiceError
from .vocab import ENTITY_TYPES, VOCAB_FIELDS

router = APIRouter(prefix="/api/military")

_ROLES = ("viewer", "staff", "admin")

# URL slugs: plural forms are the documented contract (design record §12.1);
# singular forms are accepted as aliases.  Internal keys stay singular.
_ENTITY_ALIASES: dict[str, str] = {}
for _key in ENTITY_SPECS:
    _ENTITY_ALIASES[_key] = _key
    _ENTITY_ALIASES[_key + "s"] = _key


def _role_of(request: Request) -> str:
    role = (request.headers.get("X-Military-Role") or "").strip().lower()
    return role if role in _ROLES else "admin"


def _actor_of(request: Request) -> str:
    # mirror app/server/deps.actor_of: X-Actor header, else neutral default
    actor = (request.headers.get("X-Actor") or "").strip()
    return actor or "military-user"


def _conn() -> Iterator[Any]:
    with service.transaction() as conn:
        yield conn


def _require_role(request: Request, *allowed: str) -> str:
    role = _role_of(request)
    if role not in allowed:
        raise HTTPException(
            status_code=403,
            detail={"ok": False, "error": {"code": "forbidden",
                                          "message": f"role {role!r} may not perform this action"}},
        )
    return role


def _wrap_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ServiceError):
        return HTTPException(status_code=exc.status,
                             detail={"ok": False, "error": exc.payload()})
    if isinstance(exc, RuleViolation):
        status = 409 if exc.code in ("appointment_overlap", "one_current_deployment",
                                     "one_current_appointment", "delete_blocked") else 422
        return HTTPException(status_code=status,
                             detail={"ok": False, "error": exc.payload()})
    if isinstance(exc, naming.NamingError):
        return HTTPException(status_code=422,
                             detail={"ok": False, "error": {"code": "naming_error",
                                                            "message": str(exc)}})
    return HTTPException(status_code=500,
                         detail={"ok": False, "error": {"code": "internal",
                                                        "message": str(exc)}})


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ServiceError, RuleViolation, naming.NamingError) as exc:
        raise _wrap_error(exc) from exc


def _check_entity(slug: str) -> str:
    entity = _ENTITY_ALIASES.get(slug)
    if entity is None:
        raise HTTPException(status_code=404, detail={"ok": False,
                                                     "error": {"code": "unknown_entity",
                                                               "message": f"unknown entity {slug!r}"}})
    return entity


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404,
                         detail={"ok": False, "error": {"code": "not_found",
                                                        "message": f"{what} not found"}})


# ---------------------------------------------------------------------------
# meta: drives the schema-generated interface
# ---------------------------------------------------------------------------
@router.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "ok": True,
        "entities": {
            key: {
                **service.entity_labels(key),
                "table": spec["table"],
                "tree": bool(spec.get("tree")),
                "fields": [service.field_labels(key, f) for f in spec["fields"]],
            }
            for key, spec in ENTITY_SPECS.items()
        },
        "vocabularies": VOCAB_FIELDS,
        "entity_types": ENTITY_TYPES,
        "roles": _ROLES,
    }


# ---------------------------------------------------------------------------
# workspace dashboard
# ---------------------------------------------------------------------------
@router.get("/summary")
def get_summary(conn=Depends(_conn)) -> dict[str, Any]:
    return {"ok": True, **_call(service.summary, conn)}


# ---------------------------------------------------------------------------
# trees + force summary + holdings
# ---------------------------------------------------------------------------
@router.get("/units/tree")
def units_tree(conn=Depends(_conn)) -> dict[str, Any]:
    return {"ok": True, "tree": _call(service.tree, conn, "unit")}


@router.get("/regions/tree")
def regions_tree(conn=Depends(_conn)) -> dict[str, Any]:
    return {"ok": True, "tree": _call(service.tree, conn, "region")}


@router.get("/units/{unit_id}/force-summary")
def unit_force_summary(unit_id: int, conn=Depends(_conn)) -> dict[str, Any]:
    data = _call(service.force_summary, conn, unit_id)
    if data is None:
        raise _not_found(f"unit {unit_id}")
    return {"ok": True, **data}


@router.get("/commanders/{commander_id}/leader-record")
def leader_record_route(commander_id: int, conn=Depends(_conn)) -> dict[str, Any]:
    """The leader's command record — database counts over their appointments.

    Derived facts only (units commanded, echelon reached, personnel, deployments
    covered, years of service); the qualitative side lives in the assessed
    traits, each with its basis.
    """
    data = _call(service.leader_record, conn, commander_id)
    if data is None:
        raise _not_found(f"commander {commander_id}")
    return {"ok": True, **data}


@router.get("/units/{unit_id}/geo")
def unit_geo_route(unit_id: int, conn=Depends(_conn)) -> dict[str, Any]:
    """The unit's own location for its dossier map — unit + deployment rows only.

    The response intentionally never contains commander or person data: the map
    must show the unit's own specific location, not the commander's location.
    """
    data = _call(service.unit_geo, conn, unit_id)
    if data is None:
        raise _not_found(f"unit {unit_id}")
    return {"ok": True, **data}


@router.get("/armaments/{armament_id}/holdings")
def armament_holdings(armament_id: int, conn=Depends(_conn)) -> dict[str, Any]:
    data = _call(service.armament_holdings, conn, armament_id)
    if data is None:
        raise _not_found(f"armament {armament_id}")
    return {"ok": True, **data}


# ---------------------------------------------------------------------------
# naming series administration (admin only, audited)
# ---------------------------------------------------------------------------
@router.get("/naming/status")
def naming_status(conn=Depends(_conn)) -> dict[str, Any]:
    return {"ok": True, "series": _call(naming.status, conn)}


@router.get("/naming/history")
def naming_history(limit: int = Query(50, ge=1, le=200),
                   conn=Depends(_conn)) -> dict[str, Any]:
    """Counter adjustment history (full numbering control, read-only)."""
    rows = conn.execute(
        "SELECT l.id, l.option_id, o.label, l.partition, l.old_value, "
        "l.new_value, l.actor, l.at FROM naming_adjustment_log l "
        "JOIN naming_series_option o ON o.id = l.option_id "
        "ORDER BY l.id DESC LIMIT ?", (limit,)).fetchall()
    return {"ok": True, "records": [dict(r) for r in rows]}


@router.post("/naming/preview")
def naming_preview(payload: dict[str, Any] = Body(...),
                   conn=Depends(_conn)) -> dict[str, Any]:
    entity = payload.get("entity")
    if entity not in ENTITY_SPECS:
        raise HTTPException(status_code=422,
                            detail={"ok": False, "error": {"code": "unknown_entity",
                                                           "message": f"unknown entity {entity!r}"}})
    spec = ENTITY_SPECS[entity]
    context: dict[str, Any] = {}
    if payload.get("year"):
        context["year"] = payload["year"]
    for f in spec["fields"]:
        if f["type"] == "choice" and f.get("options"):
            context[f["name"]] = payload.get(f["name"])
    result = _call(naming.preview, conn, spec["naming_entity"], context,
                   payload.get("label"))
    return {"ok": True, **result}


@router.put("/naming/counter")
def naming_counter(request: Request, payload: dict[str, Any] = Body(...),
                   conn=Depends(_conn)) -> dict[str, Any]:
    _require_role(request, "admin")
    result = _call(naming.adjust_counter, conn, int(payload["option_id"]),
                   str(payload.get("partition") or ""), int(payload["new_value"]),
                   _actor_of(request))
    service._audit(conn, _actor_of(request), "naming-adjust", "naming",
                   int(payload["option_id"]), payload.get("label"), None,
                   {"partition": result["partition"], "current_value": result["current_value"]})
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# audit trail (admin only)
# ---------------------------------------------------------------------------
@router.get("/audit/log")
def audit_log(request: Request, limit: int = Query(50, ge=1, le=500),
              entity: str | None = None, conn=Depends(_conn)) -> dict[str, Any]:
    _require_role(request, "admin")
    where, args = "", []
    if entity:
        where, args = " WHERE entity = ?", [entity]
    rows = conn.execute(
        f"SELECT * FROM audit_log{where} ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    return {"ok": True, "records": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# sample data (fictional) — admin only
# ---------------------------------------------------------------------------
@router.post("/sample")
def load_sample(request: Request, payload: dict[str, Any] = Body(default={}),
                conn=Depends(_conn)) -> dict[str, Any]:
    _require_role(request, "admin")
    result = _call(seed.load_sample, conn, bool(payload.get("force")),
                   _actor_of(request))
    return {"ok": True, **result}


@router.delete("/sample")
def clear_sample(request: Request, conn=Depends(_conn)) -> dict[str, Any]:
    _require_role(request, "admin")
    result = _call(seed.clear_sample, conn, _actor_of(request))
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# data quality + CSV export (specific paths, before the generic CRUD routes)
# ---------------------------------------------------------------------------
@router.get("/quality")
def quality(conn=Depends(_conn)) -> dict[str, Any]:
    return {"ok": True, **_call(service.quality_report, conn)}


@router.get("/{entity}/export.csv")
def export_csv(entity: str, request: Request,
               q: str | None = None, sort: str = "id", direction: str = "asc",
               conn=Depends(_conn)) -> dict[str, Any]:
    entity = _check_entity(entity)
    spec = ENTITY_SPECS[entity]
    field_names = {f["name"] for f in spec["fields"]}
    filters = {k: v for k, v in request.query_params.items()
               if k in field_names and v != ""}
    result = _call(service.export_csv, conn, entity, q=q, filters=filters,
                   sort=sort, direction=direction)
    return {"ok": True, **result}


@router.post("/{entity}/import.csv")
def import_csv_route(request: Request, entity: str,
                     payload: dict[str, Any] = Body(...),
                     conn=Depends(_conn)) -> dict[str, Any]:
    _require_role(request, "staff")
    entity = _check_entity(entity)
    result = _call(service.import_csv, conn, entity,
                   str(payload.get("csv") or ""),
                   str(payload.get("mode") or "create"),
                   _actor_of(request))
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# generic CRUD over the twelve entities (registered last on purpose)
# ---------------------------------------------------------------------------
@router.get("/{entity}")
def list_entity(entity: str, request: Request,
                q: str | None = None, sort: str = "id", direction: str = "asc",
                limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                conn=Depends(_conn)) -> dict[str, Any]:
    entity = _check_entity(entity)
    spec = ENTITY_SPECS[entity]
    field_names = {f["name"] for f in spec["fields"]}
    filters = {k: v for k, v in request.query_params.items()
               if k in field_names and v != ""}
    data = _call(service.list_records, conn, entity, q=q, filters=filters,
                 sort=sort, direction=direction, limit=limit, offset=offset)
    return {"ok": True, **data}


@router.get("/{entity}/{record_id}")
def get_entity(entity: str, record_id: int, conn=Depends(_conn)) -> dict[str, Any]:
    entity = _check_entity(entity)
    record = _call(service.get_record, conn, entity, record_id)
    if record is None:
        raise _not_found(f"{entity} {record_id}")
    return {"ok": True, "record": record}


@router.post("/{entity}", status_code=201)
def create_entity(entity: str, request: Request,
                  payload: dict[str, Any] = Body(...),
                  conn=Depends(_conn)) -> dict[str, Any]:
    entity = _check_entity(entity)
    _require_role(request, "staff", "admin")
    record = _call(service.create, conn, entity, payload, _actor_of(request))
    return {"ok": True, "record": record}


@router.patch("/{entity}/{record_id}")
def update_entity(entity: str, record_id: int, request: Request,
                  payload: dict[str, Any] = Body(...),
                  conn=Depends(_conn)) -> dict[str, Any]:
    entity = _check_entity(entity)
    _require_role(request, "staff", "admin")
    record = _call(service.update, conn, entity, record_id, payload, _actor_of(request))
    return {"ok": True, "record": record}


@router.delete("/{entity}/{record_id}")
def delete_entity(entity: str, record_id: int, request: Request,
                  conn=Depends(_conn)) -> dict[str, Any]:
    entity = _check_entity(entity)
    _require_role(request, "admin")
    _call(service.delete, conn, entity, record_id, _actor_of(request))
    return {"ok": True}
