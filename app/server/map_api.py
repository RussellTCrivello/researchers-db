"""
SIRAJ · the geographic API.

Everything the map workspace needs, and nothing it could compute wrongly for itself:
features for a viewport, the aggregates behind the "what is here" panel, the overlays
derived from relationships and the place tree, one record's full geographic dossier, a
gazetteer search, reverse lookup, spatial queries and the local basemap layers.

Design rules that hold across every route here:

  * **A feature is a registry record.** `GET /api/map/features` returns
    `{entity_type, id, code}` — the map never invents a point, and selecting one opens
    the record the application already knows how to show.
  * **Bounded work.** Every query takes a viewport and a limit (`map.max_points`), and
    says in the response how many records it left out. No route will happily serialise
    28 000 points into a phone.
  * **Two ways to fail, both honest.** A bad coordinate is `422` with the reason; a map
    subsystem that cannot answer (no basemap pack) is `503` with a message the interface
    can show instead of an empty canvas.
  * **The antimeridian is handled in the query, not in the renderer.** A window that
    crosses 180° is split into two windows before it reaches SQL.
"""
from __future__ import annotations

import json
import math
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import Response

from .. import db
from .. import settings as settings_mod
from ..geo import basemap, browse_cache, georef, mapdata, offline_pack, providers, spatial, tiledownload
from ..schemas import ENTITIES
from .deps import actor_of, conn_dep

router = APIRouter()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _layers(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    wanted = [p.strip() for p in raw.split(",") if p.strip()]
    bad = [p for p in wanted if p not in mapdata.JOINS]
    if bad:
        raise HTTPException(422, f"unknown map layer(s): {', '.join(bad)}; "
                                 f"known layers are {', '.join(mapdata.MAPPED_LAYERS)}")
    return wanted or None


def _bbox(raw: str | None) -> tuple | None:
    if not raw:
        return None
    box = spatial.parse_bbox(raw)
    if box is None:
        raise HTTPException(422, "bbox must be four numbers: min_lon,min_lat,max_lon,max_lat")
    return box


def _filters(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(422, "filters must be JSON") from None
    if not isinstance(parsed, dict):
        raise HTTPException(422, "filters must be a JSON object")
    return parsed


def _settings(conn) -> dict[str, Any]:
    return {key: settings_mod.get(conn, key) for key in (
        "map.provider", "map.center_lat", "map.center_lon", "map.zoom",
        "map.max_points", "map.cluster", "map.units", "map.show_labels", "map.overlays",
        "map.download_max_zoom", "map.download_max_tiles", "map.download_delay_ms")}


# --------------------------------------------------------------------------- #
# configuration and catalogues
# --------------------------------------------------------------------------- #
@router.get("/api/map/config")
def map_config(conn=Depends(conn_dep)):
    """Everything the workspace must know before it draws: providers, CRS, limits.

    The provider list carries attribution, licence and usage terms, because the one
    thing an interface must never do is show a base map without saying whose it is.
    """
    conf = _settings(conn)
    provider = providers.get(conf["map.provider"])
    base = basemap.info()
    return {
        "ok": True,
        "provider": {**{k: v for k, v in provider.items() if k != "style"},
                     "style": provider["style"]},
        # every provider carries its style object: switching base map must never need
        # a second round trip, and the interface must be able to show attribution for a
        # provider it has not switched to yet
        "providers": [dict(entry, style=providers.get(entry["id"])["style"])
                      for entry in providers.catalog()],
        # the same catalogue arranged by family (offline / standard / aerial / terrain),
        # so the Layers menu can present "aerial" as a choice rather than one more radio
        "provider_groups": [{"id": g["id"], "providers": [p_["id"] for p_ in g["providers"]]}
                            for g in providers.grouped()],
        "crs": spatial.crs_catalog(),
        "initial": {"lat": float(conf["map.center_lat"]),
                    "lon": float(conf["map.center_lon"]),
                    "zoom": int(conf["map.zoom"]), "bearing": 0, "pitch": 0},
        "limits": {"max_points": int(conf["map.max_points"]),
                   "cluster": bool(conf["map.cluster"]),
                   "radius_max_m": 5_000_000},
        "units": conf["map.units"],
        "labels": bool(conf["map.show_labels"]),
        "overlays": [o for o in str(conf["map.overlays"]).split(",") if o],
        "basemap": base,
        "gazetteer": basemap.gazetteer_size(),
        "layers": mapdata.layer_catalog(conn),
        "entities": [{"key": e, "label_en": ENTITIES[e].label_en,
                      "label_ar": ENTITIES[e].label_ar} for e in mapdata.MAPPED_LAYERS],
        "basemap_layers": [{"id": lid, **{k: v for k, v in desc.items() if k != "features"},
                            "features": desc.get("features")}
                           for lid, desc in (base.get("layers") or {}).items()],
        # street-level offline packs (vectormap / optional tilepack) — cartography only
        "offline_pack": offline_pack.catalog_extra(),
    }


@router.get("/api/map/layers")
def map_layers(conn=Depends(conn_dep)):
    """The mappable layers with their located / unlocated counts."""
    return {"ok": True, "layers": mapdata.layer_catalog(conn),
            "mapped": list(mapdata.MAPPED_LAYERS)}


# --------------------------------------------------------------------------- #
# features for a viewport
# --------------------------------------------------------------------------- #
@router.get("/api/map/features")
def map_features(bbox: str | None = None, zoom: float = Query(5, ge=0, le=24),
                 layers: str | None = None, filters: str | None = None,
                 limit: int | None = Query(None, ge=1, le=20000),
                 conn=Depends(conn_dep)):
    """Points for one viewport — bounded, filtered, counted, and never invented.

    `limit` defaults to the configured `map.max_points`; the response reports
    `per_layer` totals and `truncated`, so the interface can say "showing 4 000 of 8 300
    — zoom in" rather than implying that what is on screen is everything.
    """
    conf = _settings(conn)
    data = mapdata.features(conn, bbox=_bbox(bbox), zoom=zoom, layers=_layers(layers),
                            filters=_filters(filters),
                            limit=limit or int(conf["map.max_points"]))
    data.update({"ok": True, "zoom": zoom, "limit": limit or int(conf["map.max_points"]),
                 "cluster": bool(conf["map.cluster"])})
    return data


@router.get("/api/map/groups")
def map_groups(bbox: str | None = None, zoom: float = Query(5, ge=0, le=24),
               layers: str | None = None, filters: str | None = None,
               limit: int = Query(50, ge=1, le=500), conn=Depends(conn_dep)):
    """Aggregates by place: which points carry how many records, and of what kind."""
    data = mapdata.groups(conn, bbox=_bbox(bbox), zoom=zoom, layers=_layers(layers),
                          filters=_filters(filters), limit=limit)
    return {"ok": True, **data}


@router.get("/api/map/overlays")
def map_overlays(layers: str | None = None,
                 limit: int = Query(3000, ge=1, le=20000), conn=Depends(conn_dep)):
    """Vector overlays computed from the registry: relationship arcs, place tree."""
    wanted = [p.strip() for p in (layers or "relationships,place_hierarchy").split(",")
              if p.strip()]
    known = {"relationships", "place_hierarchy"}
    bad = [w for w in wanted if w not in known]
    if bad:
        raise HTTPException(422, f"unknown overlay(s): {', '.join(bad)}; "
                                 f"known overlays are {', '.join(sorted(known))}")
    data = mapdata.overlays(conn, layers=wanted, limit=limit)
    return {"ok": True, "overlays": data,
            "counts": {k: v["count"] for k, v in data.items()}}


# --------------------------------------------------------------------------- #
# one feature, in full
# --------------------------------------------------------------------------- #
@router.get("/api/map/feature/{entity_type}/{rec_id}")
def map_feature(entity_type: str, rec_id: int, conn=Depends(conn_dep)):
    """The inspector payload for one selected feature.

    Coordinates in DD and DMS, in three CRSs, the place the position was inherited
    from, the country polygon the point falls in, and the record's own located
    relationships — everything a researcher needs to *judge* a position, and nothing
    that duplicates the record view.
    """
    if entity_type not in ENTITIES:
        raise HTTPException(422, f"unknown entity type '{entity_type}'")
    try:
        payload = mapdata.detail(conn, entity_type, rec_id)
    except LookupError:
        raise HTTPException(404, f"{entity_type} #{rec_id} not found") from None
    return {"ok": True, **payload}


@router.get("/api/map/search")
def map_search(q: str = Query("", max_length=200),
               limit: int = Query(12, ge=1, le=50), conn=Depends(conn_dep)):
    """One box for a name or a coordinate.

    A coordinate is a position (so the map flies there and drops a temporary marker);
    a name is a registry record or a gazetteer city. Names come from the registry first
    — because the registry is what the map is *about*.
    """
    result = mapdata.search(conn, q, limit=limit)
    cities = basemap.find_places(q, limit=5) if q and not result.get("position") else []
    return {"ok": True, "query": q, "position": result.get("position"),
            "position_label": result.get("position_label"),
            "results": result["results"], "cities": cities, "count": result["count"]}


@router.get("/api/map/reverse")
def map_reverse(lat: float, lon: float, conn=Depends(conn_dep)):
    """What is at this position: the containing country, the nearest places."""
    try:
        return {"ok": True, **mapdata.reverse(conn, lat, lon)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/api/map/parse")
def map_parse(q: str = Query(..., min_length=1, max_length=200)):
    """Parse a typed coordinate, for live validation in the coordinate box."""
    parsed = spatial.parse_pair(q)
    if not parsed["ok"]:
        return {"ok": False, "reason": parsed.get("reason"), "message": parsed.get("message")}
    return {"ok": True, **parsed,
            "formatted": spatial.format_position(parsed["lat"], parsed["lon"]),
            "crs": {code: spatial.convert(parsed["lat"], parsed["lon"], code)
                    for code in spatial.CRS_CATALOG}}


# --------------------------------------------------------------------------- #
# spatial queries
# --------------------------------------------------------------------------- #
@router.post("/api/map/query")
def map_query(payload: dict = Body(...), conn=Depends(conn_dep),
              x_actor: str | None = Header(None)):
    """Which registry records are inside this window / radius / drawn polygon.

    Reads only: a spatial query identifies records, it never creates one. The one action
    that writes anything on the map is the record form itself.
    """
    mode = str(payload.get("mode") or "bbox").lower()
    if mode not in ("bbox", "radius", "polygon"):
        raise HTTPException(422, "mode must be bbox, radius or polygon")
    limit = max(1, min(int(payload.get("limit") or 500), 5000))
    kwargs: dict[str, Any] = {
        "mode": mode, "layers": payload.get("layers"), "filters": payload.get("filters"),
        "limit": limit,
    }
    if mode == "bbox":
        box = payload.get("bbox")
        if isinstance(box, str):
            box = spatial.parse_bbox(box)
        if not box or len(box) != 4:
            raise HTTPException(422, "bbox queries need [min_lon, min_lat, max_lon, max_lat]")
        kwargs["bbox"] = tuple(float(v) for v in box)
    elif mode == "radius":
        lat, lon = payload.get("lat"), payload.get("lon")
        check = spatial.validate_pair(lat, lon)
        if not check["ok"]:
            raise HTTPException(422, check["problems"][0]["message"])
        radius = float(payload.get("radius_m") or 25000)
        if radius <= 0 or radius > 5_000_000:
            raise HTTPException(422, "radius_m must be between 1 and 5 000 000 metres")
        kwargs.update({"lat": check["lat"], "lon": check["lon"], "radius_m": radius,
                       "bbox": (spatial.normalize_lon(check["lon"] - 1), -90, 180, 90)
                       if radius > 2_000_000 else _radius_bbox(check["lat"], check["lon"], radius)})
    else:
        polygon = payload.get("polygon") or []
        if len(polygon) < 3:
            raise HTTPException(422, "a polygon query needs at least three points")
        lats = [float(p[1]) for p in polygon]
        lons = [float(p[0]) for p in polygon]
        kwargs.update({"polygon": polygon,
                       "bbox": (min(lons), min(lats), max(lons), max(lats))})
    try:
        result = mapdata.query(conn, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    result["actor"] = actor_of(x_actor, None)
    return {"ok": True, **result}


def _radius_bbox(lat: float, lon: float, radius_m: float) -> tuple:
    """A square that certainly contains the circle — the cheap pre-filter."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.01, abs(math.cos(math.radians(lat)))))
    return (spatial.normalize_lon(lon - dlon), max(-90.0, lat - dlat),
            spatial.normalize_lon(lon + dlon), min(90.0, lat + dlat))


# --------------------------------------------------------------------------- #
# the local basemap
# --------------------------------------------------------------------------- #
@router.get("/api/geo/basemap")
def geo_basemap():
    """What the shipped basemap pack contains, and the terms it is used under."""
    info = basemap.info()
    if not info.get("available"):
        raise HTTPException(503, "the local basemap pack is not built; run "
                                 "python3 -m app.geo.basemap_build")
    return {"ok": True, **info}


@router.get("/api/geo/basemap/{layer}")
def geo_basemap_layer(layer: str, zoom: float = Query(3, ge=0, le=22),
                      bbox: str | None = None,
                      limit: int = Query(400, ge=1, le=5000)):
    """One basemap layer as GeoJSON for a viewport and a detail level."""
    if not basemap.available():
        raise HTTPException(503, "the local basemap pack is not built")
    known = set((basemap.info().get("layers") or {}).keys())
    if layer not in known:
        raise HTTPException(422, f"unknown basemap layer '{layer}'; known: {', '.join(sorted(known))}")
    try:
        return basemap.features(layer, zoom=zoom, bbox=_bbox(bbox), limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("/api/map/georef/preview")
def map_georef_preview(limit: int = Query(200, ge=1, le=2000), conn=Depends(conn_dep)):
    """A read-only preview of what `geocode-places` *would* do.

    Nothing here writes: the command line (`python3 -m app.cli geocode-places --apply`)
    is the only way to apply a proposal, and it audits every write. Exposing the plan
    lets a researcher see the conflicts *before* running anything.
    """
    plan = georef.plan(conn)
    located = conn.execute(
        "SELECT COUNT(*) FROM place WHERE deleted_at IS NULL AND latitude IS NOT NULL"
    ).fetchone()[0]
    return {"ok": True, "dry_run": True,
            "summary": {"scanned": plan.scanned, "proposals": len(plan.proposals),
                        "within": len(plan.within), "conflicts": len(plan.conflicts),
                        "ambiguous": len(plan.ambiguous), "unmatched": len(plan.unmatched),
                        "located": located,
                        "located_after_apply": located + sum(
                            1 for p in plan.proposals if p.old_lat is None)},
            "proposals": [dict(p.__dict__) for p in plan.proposals[:limit]],
            "conflicts": plan.conflicts[:limit],
            "ambiguous": plan.ambiguous[:limit],
            "note": "Read-only. Run `python3 -m app.cli geocode-places --apply` to write, "
                    "which audits every coordinate it changes."}


@router.get("/api/geo/gazetteer")
def geo_gazetteer(q: str = Query("", max_length=200), country: str | None = None,
                  limit: int = Query(8, ge=1, le=50)):
    """The bundled city gazetteer: offline name → position, with Arabic names."""
    return {"ok": True, "query": q, "size": basemap.gazetteer_size(),
            "results": basemap.find_places(q, limit=limit, country=country)}


@router.get("/api/geo/nearest")
def geo_nearest(lat: float, lon: float):
    """The nearest gazetteer city to a point — names an otherwise anonymous coordinate."""
    check = spatial.validate_pair(lat, lon)
    if not check["ok"]:
        raise HTTPException(422, check["problems"][0]["message"])
    place = basemap.nearest_place(check["lat"], check["lon"])
    return {"ok": True, "position": spatial.format_position(check["lat"], check["lon"]),
            "place": place, "db": str(db.DB_PATH)}


# --------------------------------------------------------------------------- #
# offline street packs (cartography only — never touches registry.db)
# --------------------------------------------------------------------------- #
@router.get("/api/geo/vectormap/info")
def geo_vectormap_info():
    """Metadata for the bundled Gaza street vector pack."""
    return {"ok": True, **offline_pack.vectormap_info()}


@router.get("/api/geo/vectormap")
def geo_vectormap(request_accept: str | None = Header(None, alias="Accept-Encoding")):
    """The compressed offline street map JSON (gzip when the client accepts it)."""
    prefer = bool(request_accept and "gzip" in request_accept.lower())
    payload = offline_pack.vectormap_payload(prefer_gzip=prefer)
    if not payload:
        raise HTTPException(404, "offline vectormap pack is not installed")
    headers = {
        "ETag": payload["etag"],
        "X-Vectormap-Hash": payload["hash"],
        "Cache-Control": "public, max-age=3600",
        "Vary": "Accept-Encoding",
    }
    if payload["gzip"]:
        headers["Content-Encoding"] = "gzip"
        return Response(content=payload["body"], media_type="application/json", headers=headers)
    return Response(content=payload["body"], media_type="application/json", headers=headers)


@router.get("/api/geo/tiles/info")
def geo_tiles_info():
    """Optional raster `.tilepack` metadata (available only if the file is present)."""
    return {"ok": True, **offline_pack.tilepack_info()}


@router.get("/api/geo/tiles/{z}/{x}/{y}.webp")
def geo_tile(z: int, x: int, y: int):
    """One WebP tile from the optional offline tilepack."""
    if z < 0 or z > 22 or x < 0 or y < 0:
        raise HTTPException(422, "invalid tile coordinates")
    data = offline_pack.read_tile(z, x, y)
    if data is None:
        raise HTTPException(404, "tile not in pack")
    return Response(content=data, media_type="image/webp",
                    headers={"Cache-Control": "public, max-age=86400"})


# --------------------------------------------------------------------------- #
# browse-cache — auto-persist every tile the map actually requested
# --------------------------------------------------------------------------- #
@router.get("/api/geo/browse-cache/stats")
def browse_cache_stats():
    """How much cartography has been remembered for offline reuse."""
    return {"ok": True, "stats": browse_cache.stats()}


@router.delete("/api/geo/browse-cache")
def browse_cache_clear():
    """Forget every remembered tile (cartography only — never touches registry.db)."""
    return {"ok": True, **browse_cache.clear()}


@router.get("/api/geo/browse-cache/{provider_id}/{z}/{x}/{y}")
def browse_cache_tile(provider_id: str, z: int, x: int, y: int,
                      src: str = Query("base", alias="src")):
    """
    Serve one raster tile, remembering it.

    First hit for a (provider, source, z, x, y) fetches upstream once, stores a
    gzip-compressed copy in ``browse_cache.sqlite``, and returns the bytes. Later
    hits — including with no network — are answered from that store. Only tiles
    the map has already asked for are kept; there is no bulk scraper here.
    """
    if z < 0 or z > 22 or x < 0 or y < 0:
        raise HTTPException(422, "invalid tile coordinates")
    if provider_id not in providers.PROVIDERS:
        raise HTTPException(404, f"unknown provider: {provider_id}")
    stored = tiledownload.get_tile(provider_id, src or "base", z, x, y)
    if stored is not None:
        body, ctype = stored
        return Response(
            content=body,
            media_type=ctype or "image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-SIRAJ-Tile-Origin": "download",
            },
        )
    try:
        body, ctype, origin = browse_cache.get_or_fetch(provider_id, src or "base", z, x, y)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ConnectionError as exc:
        # Offline and not yet cached: honest 503 so the client can fall back to IDB.
        raise HTTPException(503, f"tile unavailable offline: {exc}") from exc
    return Response(
        content=body,
        media_type=ctype or "image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-SIRAJ-Tile-Origin": origin,
        },
    )


# --------------------------------------------------------------------------- #
# permanent downloads — store a region's tiles for offline viewing
# --------------------------------------------------------------------------- #
@router.get("/api/geo/downloads")
def download_index(conn=Depends(conn_dep)):
    """Every download job, the store's size, and the policy that governs it."""
    conf = _settings(conn)
    return {
        "ok": True,
        "jobs": tiledownload.list_jobs(),
        "stats": tiledownload.stats(),
        "caps": {
            "max_zoom": int(conf["map.download_max_zoom"]),
            "max_tiles": int(conf["map.download_max_tiles"]),
            "delay_ms": int(conf["map.download_delay_ms"]),
        },
        "providers": [{
            "id": p_["id"], "kind": p_["kind"], "group": p_["group"],
            "label_en": p_["label_en"], "label_ar": p_["label_ar"],
            "downloadable": p_.get("downloadable", False),
            "download_note_en": p_.get("download_note_en", ""),
            "download_note_ar": p_.get("download_note_ar", ""),
            "terms_url": p_.get("terms_url", ""),
        } for p_ in providers.catalog()],
    }


@router.post("/api/geo/downloads")
def download_create(payload: dict = Body(...), conn=Depends(conn_dep)):
    """Start one permanent download per requested map type.

    The body names providers (``providers: [...]``, or ``"all"`` for every type
    the terms permit), a ``bbox`` and a zoom range. Providers whose published
    terms forbid bulk retrieval are refused with that reason, out loud.
    """
    conf = _settings(conn)
    bbox = payload.get("bbox")
    if isinstance(bbox, str):
        box = _bbox(bbox)
    elif isinstance(bbox, dict):
        try:
            box = (float(bbox["w"]), float(bbox["s"]), float(bbox["e"]), float(bbox["n"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "bbox must carry w, s, e, n") from None
    else:
        raise HTTPException(422, "bbox is required")
    if box[0] >= box[2] or box[1] >= box[3]:
        raise HTTPException(422, "bbox is empty")
    try:
        minzoom = int(payload.get("minzoom", 0))
        maxzoom = int(payload.get("maxzoom", 12))
    except (TypeError, ValueError):
        raise HTTPException(422, "zooms must be integers") from None
    cap_zoom = int(conf["map.download_max_zoom"])
    cap_tiles = int(conf["map.download_max_tiles"])
    if minzoom < 0 or maxzoom < minzoom:
        raise HTTPException(422, "invalid zoom range")
    if maxzoom > cap_zoom:
        raise HTTPException(422, f"maxzoom exceeds map.download_max_zoom ({cap_zoom})")
    asked = payload.get("providers") or []
    if asked == "all" or asked == ["all"]:
        asked = [p_["id"] for p_ in providers.catalog() if p_.get("downloadable")]
    if not isinstance(asked, list) or not asked:
        raise HTTPException(422, "providers must be a non-empty list")
    name = str(payload.get("name") or "").strip()[:120]
    delay = int(conf["map.download_delay_ms"])
    results = []
    for pid in asked:
        prov = providers.PROVIDERS.get(pid)
        if prov is None:
            results.append({"provider": pid, "ok": False, "reason": "unknown provider"})
            continue
        try:
            job = tiledownload.create_job(
                name or f"{pid} · {box[0]:.2f},{box[1]:.2f}",
                pid, box[0], box[1], box[2], box[3], minzoom, maxzoom,
                src=str(payload.get("src") or "base"),
                delay_ms=delay, max_tiles=cap_tiles)
            results.append({"provider": pid, "ok": True, "job_id": job["id"],
                            "total": job["total"]})
        except (LookupError, ValueError) as exc:
            results.append({"provider": pid, "ok": False, "reason": str(exc)})
    return {"ok": True, "results": results, "jobs": tiledownload.list_jobs()}


@router.get("/api/geo/downloads/{job_id}")
def download_get(job_id: int):
    job = tiledownload.get_job(job_id)
    if not job:
        raise HTTPException(404, "no such download job")
    return {"ok": True, "job": job}


@router.post("/api/geo/downloads/{job_id}/{action}")
def download_action(job_id: int, action: str):
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(404, f"unknown action: {action}")
    job = {"pause": tiledownload.pause_job, "resume": tiledownload.resume_job,
           "cancel": tiledownload.cancel_job}[action](job_id)
    if not job:
        raise HTTPException(404, "no such download job")
    return {"ok": True, "job": job}


@router.delete("/api/geo/downloads/{job_id}")
def download_delete(job_id: int, purge: bool = False):
    if not tiledownload.delete_job(job_id, purge=purge):
        raise HTTPException(404, "no such download job")
    return {"ok": True, "purged": bool(purge), "stats": tiledownload.stats()}


@router.get("/api/geo/offline-pack.zip")
def geo_offline_pack_zip():
    """Download the bundled cartography pack as a zip (never includes registry.db)."""
    import io
    import zipfile
    from pathlib import Path

    buf = io.BytesIO()
    written = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        pack_files = ("world.vectormap.json.gz", "world.vectormap.json",
                      "gaza.vectormap.json.gz", "gaza.vectormap.json",
                      "world.tilepack", "README.md")
        for name in pack_files:
            path = offline_pack.PACK_DIR / name
            if path.is_file():
                zf.write(path, arcname=f"offline_map/{name}")
                written += 1
        basemap_path = Path(offline_pack.PACK_DIR).parent / "basemap.sqlite"
        if basemap_path.is_file():
            zf.write(basemap_path, arcname="offline_map/basemap.sqlite")
            written += 1
        meta = {
            "format": "siraj-offline-map",
            "version": 2,
            "basemap": basemap.info(),
            "vectormap": offline_pack.vectormap_info(),
            "tilepack": offline_pack.tilepack_info(),
            "note": "Cartography only. Does not contain registry.db or research records. "
                    "Covers the whole world: vector basemap (basemap.sqlite), street map "
                    "(world.vectormap.json) and raster tiles (world.tilepack).",
        }
        zf.writestr("offline_map/manifest.json", json.dumps(meta, ensure_ascii=False, indent=2))
    if written == 0:
        raise HTTPException(404, "no offline pack files are installed")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="siraj-offline-map.zip"'},
    )


@router.get("/api/map/export.geojson")
def map_export_geojson(bbox: str | None = None, layers: str | None = None,
                       limit: int = Query(5000, ge=1, le=20000),
                       conn=Depends(conn_dep)):
    """Export located registry points as GeoJSON — read-only, never mutates the DB."""
    data = mapdata.features(conn, bbox=_bbox(bbox), zoom=14, layers=_layers(layers),
                            filters={}, limit=limit)
    features = []
    for p in data.get("points") or []:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
            "properties": {
                "entity_type": p.get("entity_type"),
                "id": p.get("id"),
                "code": p.get("code"),
                "label_en": p.get("label_en"),
                "label_ar": p.get("label_ar"),
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "source": "SIRAJ registry export",
            "count": len(features),
            "truncated": bool(data.get("truncated")),
            "note": "Read-only snapshot. Importing re-creates places additively.",
        },
    }


@router.post("/api/map/import.geojson")
def map_import_geojson(payload: dict = Body(...),
                       x_actor: str | None = Header(None, alias="X-Actor"),
                       conn=Depends(conn_dep)):
    """Additively create *place* records from GeoJSON Point features.

    Never deletes or updates existing rows. Skips features that are not Points.
    Uses the normal audited create path so the change log stays complete.
    """
    from .. import repo

    actor = actor_of(x_actor, payload.get("actor") if isinstance(payload, dict) else None)
    fc = payload.get("geojson") or payload
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        raise HTTPException(422, "body must be a GeoJSON FeatureCollection "
                                 "(or {geojson: FeatureCollection})")
    features = fc.get("features") or []
    if len(features) > 2000:
        raise HTTPException(422, "import limited to 2000 features per request")
    spec = ENTITIES["place"]
    created, skipped = [], 0
    for feat in features:
        if not isinstance(feat, dict) or feat.get("type") != "Feature":
            skipped += 1
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point" or not isinstance(geom.get("coordinates"), (list, tuple)):
            skipped += 1
            continue
        try:
            lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        except (TypeError, ValueError, IndexError):
            skipped += 1
            continue
        check = spatial.validate_pair(lat, lon)
        if not check["ok"]:
            skipped += 1
            continue
        props = feat.get("properties") or {}
        name_ar = (props.get("name_ar") or props.get("name") or props.get("label_ar")
                   or props.get("label") or "").strip()
        name_en = (props.get("name_en") or props.get("label_en") or "").strip()
        if not name_ar and name_en:
            name_ar = name_en
        if not name_ar:
            name_ar = f"Imported {lat:.5f}, {lon:.5f}"
        try:
            rec = repo.create_record(
                conn, spec,
                {
                    "name_ar": name_ar,
                    "name_en": name_en or None,
                    "latitude": check["lat"],
                    "longitude": check["lon"],
                    "geo_precision": "approx",
                    "geocoding_method": "import",
                },
                actor=actor,
                reason=payload.get("reason") or "imported from GeoJSON on the map",
            )
            created.append({"id": rec["id"], "code": rec.get("code"), "title": rec.get("_title")})
        except Exception:
            skipped += 1
    return {"ok": True, "created": len(created), "skipped": skipped, "records": created[:50],
            "note": "Additive only — existing registry rows were not modified or deleted."}
