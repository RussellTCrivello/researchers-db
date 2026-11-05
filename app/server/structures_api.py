"""Structure sources over HTTP — the trees the display kernel draws.

Two routes, both read-only:

    GET /api/structures              the source registry (id, labels, chain, total)
    GET /api/structures/{source}     one source's tree, with a count on every node

Everything the browser needs to build a model is in the payload: the chain that
produced it, the totals, and whether a branch is an aggregate of smaller ones.
The kernel is source-agnostic, so a new source is a row in
:mod:`app.structures` — not a route, and not a chart.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import structures as structures_mod
from .deps import conn_dep

router = APIRouter()

#: A tree costs ~20–450 ms to compute from the live registry, and the same tree is
#: requested again on every structure switch. One small cache, keyed by exactly
#: the parameters that change the answer, with a short life: a written record
#: shows up in the picture within half a minute, and nothing is served from a
#: cache that could not be explained.
_CACHE: dict[tuple, tuple[float, dict]] = {}
_TTL = 30.0


@router.get("/api/structures")
def structure_sources(conn=Depends(conn_dep)):
    return {"ok": True, "sources": structures_mod.sources(conn),
            "max_depth": structures_mod.MAX_DEPTH,
            "max_children": structures_mod.MAX_CHILDREN}


@router.get("/api/structures/{source}")
def structure_tree(source: str,
                   depth: int = Query(3, ge=1, le=structures_mod.MAX_DEPTH),
                   max_children: int = Query(structures_mod.MAX_CHILDREN, ge=3, le=40),
                   leaves: bool = Query(False, description="List individual records under the deepest branches"),
                   max_leaves: int = Query(structures_mod.MAX_LEAVES, ge=1, le=120),
                   conn=Depends(conn_dep)):
    key = (source, depth, max_children, bool(leaves), int(max_leaves))
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return {**hit[1], "cached": True}
    try:
        payload = structures_mod.build(
            conn, source, depth=depth, max_children=max_children,
            include_leaves=bool(leaves), max_leaves=max_leaves)
    except KeyError:
        raise HTTPException(404, f"unknown structure source '{source}'") from None
    except structures_mod.Unsupported as exc:
        raise HTTPException(422, str(exc)) from None
    payload["cached"] = False
    _CACHE[key] = (now, payload)
    if len(_CACHE) > 24:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:8]:
            _CACHE.pop(k, None)
    return payload
