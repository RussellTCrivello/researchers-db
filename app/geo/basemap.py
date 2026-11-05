"""
SIRAJ · read the local basemap pack.

`basemap.sqlite` (built by `app.geo.basemap_build`) holds the Natural Earth layers
as quantised, compressed rings plus an r-tree over their bounding boxes. This module
is the only place that knows that encoding; everyone else asks for GeoJSON.

Two detail levels are packed — 1:110m for the world view and 1:50m once the user is
looking at a region — and the reader picks one from the zoom. That is the whole point
of the pack: the map never has to render 90 000 vertices to draw a country, and never
has to fetch a tile to draw a coastline.
"""
from __future__ import annotations

import functools
import json
import sqlite3
from pathlib import Path

from app.geo.basemap_build import dequantise

PACK = Path(__file__).resolve().parent / "basemap.sqlite"

# below this zoom the world fits in a few hundred pixels: 1:110m is plenty
DETAIL_ZOOM = 4.0


def available() -> bool:
    return PACK.exists()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{PACK}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def info() -> dict:
    """What the pack contains, and the terms it is used under."""
    if not available():
        return {"available": False, "error": "the local basemap pack was not built"}
    conn = _connect()
    try:
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        layers = json.loads(meta.get("layers", "{}"))
        stats = json.loads(meta.get("stats", "{}"))
        counts = {r["layer"]: r["n"] for r in conn.execute(
            "SELECT layer, COUNT(*) AS n FROM feature GROUP BY layer")}
    finally:
        conn.close()
    for key, descriptor in layers.items():
        descriptor["features"] = counts.get(key, 0)
        descriptor["levels"] = sorted({k.split("/")[0] for k in stats if k.endswith("/" + key)})
    return {
        "available": True,
        "path": str(PACK),
        "bytes": PACK.stat().st_size,
        "layers": layers,
        "source": meta.get("source"),
        "license": meta.get("license"),
        "attribution": meta.get("attribution"),
        "generated_at": meta.get("generated_at"),
        "detail_zoom": DETAIL_ZOOM,
        "vertices": sum(int(v) for v in json.loads(meta.get("stats", "{}")).values()) or None,
    }


def level_for_zoom(zoom: float) -> str:
    return "110m" if float(zoom) < DETAIL_ZOOM else "50m"


@functools.lru_cache(maxsize=4096)
def _rings(fid: int) -> tuple[tuple[tuple[float, float], ...], ...]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT part, coords FROM geom WHERE fid=? ORDER BY part", (fid,)).fetchall()
    finally:
        conn.close()
    return tuple(tuple(dequantise(r["coords"])) for r in rows)


def _ring(raw) -> list:
    """A ring as GeoJSON wants it: closed for polygons, plain for lines."""
    pts = [list(p) for p in raw]
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def geometry(fid: int, kind: str) -> dict:
    rings = _rings(fid)
    if kind == "point":
        x, y = rings[0][0]
        return {"type": "Point", "coordinates": [x, y]}
    if kind == "polygon":
        # a hole is packed as its own ring; the outer ring is the largest one
        if len(rings) == 1:
            return {"type": "Polygon", "coordinates": [_ring(rings[0])]}
        return {"type": "MultiPolygon", "coordinates": [[_ring(r)] for r in rings]}
    if len(rings) == 1:
        return {"type": "LineString", "coordinates": [list(p) for p in rings[0]]}
    return {"type": "MultiLineString", "coordinates": [[list(p) for p in r] for r in rings]}


def features(layer: str, zoom: float = 0.0, bbox: tuple | None = None,
             limit: int = 400, offset: int = 0) -> dict:
    """One layer as a GeoJSON FeatureCollection.

    `bbox` is (min_lon, min_lat, max_lon, max_lat) and is **not** allowed to wrap:
    callers split an antimeridian-crossing window into two boxes
    (`app.geo.spatial.split_bbox`) and ask twice. Asking twice is cheap; a silently
    wrong answer is not.
    """
    if not available():
        raise FileNotFoundError("the local basemap pack was not built")
    level = level_for_zoom(zoom)
    conn = _connect()
    try:
        sql = ("SELECT f.fid, f.kind, f.props FROM feature f "
               "JOIN feature_bbox b ON b.fid = f.fid WHERE f.layer=? AND f.level=?")
        args: list = [layer, level]
        if bbox:
            minx, miny, maxx, maxy = bbox
            sql += " AND b.minx <= ? AND b.maxx >= ? AND b.miny <= ? AND b.maxy >= ?"
            args += [maxx, minx, maxy, miny]
        total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
        sql += " ORDER BY f.npoints DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        rows = conn.execute(sql, args).fetchall()
        out = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": r["fid"],
                 "properties": json.loads(r["props"]),
                 "geometry": geometry(r["fid"], r["kind"])}
                for r in rows
            ],
        }
    finally:
        conn.close()
    return {"ok": True, "layer": layer, "level": level, "total": total,
            "returned": len(out["features"]), "collection": out,
            "attribution": "Natural Earth (public domain)"}


# --------------------------------------------------------------------------- #
# point-in-polygon: "which country is 33.31, 44.37 in?" without a geocoder
# --------------------------------------------------------------------------- #
def _in_ring(lon: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


@functools.lru_cache(maxsize=1)
def _country_index() -> tuple:
    """Bounding box per country at 1:50m, so a point test starts with a few candidates."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT f.fid, f.props, b.minx, b.maxx, b.miny, b.maxy FROM feature f "
            "JOIN feature_bbox b ON b.fid = f.fid "
            "WHERE f.layer='countries' AND f.level='50m'").fetchall()
    finally:
        conn.close()
    return tuple((r["fid"], json.loads(r["props"]), r["minx"], r["maxx"], r["miny"], r["maxy"])
                 for r in rows)


# --------------------------------------------------------------------------- #
# local gazetteer: city search and reverse lookup, with no external geocoder
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=1)
def _gazetteer() -> tuple:
    if not available():
        return ()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT f.fid, f.props FROM feature f WHERE f.layer='places' AND f.level='50m'"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        props = json.loads(r["props"])
        pt = _rings(r["fid"])[0][0]
        out.append({"id": r["fid"], "lat": pt[1], "lon": pt[0], **props})
    return tuple(out)


def gazetteer_size() -> int:
    return len(_gazetteer())


def find_places(text: str, limit: int = 8, country: str | None = None) -> list[dict]:
    """Cities whose Latin or Arabic name matches — the "where is Mosul?" box.

    Diacritics and the Arabic definite article are ignored, so `الموصل` and `موصل`
    find the same city, exactly as the registry's own search does.
    """
    if not text:
        return []
    q = text.strip().lower()
    q_ar = q.replace("ال", "", 1) if q.startswith("ال") else q
    hits = []
    for place in _gazetteer():
        if country and (place.get("iso_a2") or "").lower() != country.lower():
            continue
        name = (place.get("name_en") or "").lower()
        name_ar = (place.get("name_ar") or "")
        score = 0
        if name == q:
            score = 100
        elif name.startswith(q):
            score = 80
        elif q in name:
            score = 60
        if name_ar:
            ar_clean = name_ar.replace("ال", "", 1) if name_ar.startswith("ال") else name_ar
            if q in name_ar or q_ar in ar_clean:
                score = max(score, 90)
        if score:
            hits.append({**place, "score": score})
    hits.sort(key=lambda p: (-p["score"], -(p.get("population") or 0)))
    return hits[:limit]


def nearest_place(lat: float, lon: float) -> dict | None:
    """The closest gazetteer city to a point — used to name an empty coordinate."""
    best, best_d = None, None
    for place in _gazetteer():
        d = (place["lat"] - lat) ** 2 + (place["lon"] - lon) ** 2
        if best_d is None or d < best_d:
            best, best_d = place, d
    if best is None:
        return None
    from app.geo import spatial
    return {**best, "distance_m": round(
        spatial.haversine(lat, lon, best["lat"], best["lon"]), 1)}


def country_at(lat: float, lon: float) -> dict | None:
    """The country polygon containing a point, or None over the sea."""
    if not available():
        return None
    for fid, props, minx, maxx, miny, maxy in _country_index():
        if not (minx <= lon <= maxx and miny <= lat <= maxy):
            continue
        geom = geometry(fid, "polygon")
        rings = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        hits = 0
        for poly in rings:
            outer = poly[0]
            if _in_ring(lon, lat, outer) and not any(
                    _in_ring(lon, lat, hole) for hole in poly[1:]):
                hits += 1
        if hits:
            return {**props, "fid": fid}
    return None
