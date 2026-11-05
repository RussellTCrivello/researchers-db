"""
SIRAJ · the CRCE API.

Two routes, because the standard has two faces: the catalogue (what the marks
mean, and the rules that keep them honest) and one entity's dossier (the answer
for a single record, in the published field order).

    GET /api/crce/standard                 the standard as data
    GET /api/crce/dossier/{type}/{id}      one entity's CRCE record

`type` accepts the registry's own entity keys plus `organization`, which is how
the standard names institutions; both resolve to the same category, so a client
can speak either vocabulary without translating.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import crce
from ..schemas import ENTITIES
from .deps import conn_dep

router = APIRouter()

# the standard's vocabulary → the registry's tables
_ALIASES = {"organization": "institution", "organisation": "institution",
            "people": "person", "location": "place"}


@router.get("/api/crce/standard")
def crce_standard():
    """The four reserved marks, their geometry, and the rules of the standard."""
    return {"ok": True, **crce.catalogue()}


@router.get("/api/crce/dossier/{etype}/{rid}")
def crce_dossier(etype: str, rid: int, conn=Depends(conn_dep)):
    """One entity's coordinates, orientation and reserved mark, in one answer."""
    kind = _ALIASES.get(etype, etype)
    if kind not in ENTITIES:
        raise HTTPException(404, f"unknown entity type: {etype}")
    try:
        data = crce.dossier(conn, kind, rid)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc
    return {"ok": True, **data}
