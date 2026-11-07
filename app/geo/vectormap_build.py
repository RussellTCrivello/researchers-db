"""
SIRAJ · build the world street-pack vectormap.

The offline street map used to cover the Gaza working area only. The registry is
used everywhere, so the cartography must cover everywhere: this module converts
Natural Earth vector layers (public domain) into the vectormap v2 delta format
that `app/static/js/lib/vectormap.js` inflates, and writes
`app/geo/offline_map/world.vectormap.json(.gz)`.

The result is the *world base* of the street map: country borders, coastlines,
rivers, lakes, urban areas, cities and country labels. The OSM street detail for
the working area (`gaza.vectormap.json.gz`) stays where it is; the server merges
the two packs, detail over base, so one map shows the world and the streets
where street data exists.

Rebuild (only when the source data changes):

    python3 -m app.geo.vectormap_build --source /path/to/natural-earth/geojson

Natural Earth is in the **public domain** (no attribution required, none
implied). It is credited in the map's attribution line and here regardless.
"""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent / "offline_map"
WORLD_NAME = "world.vectormap.json"

# Mercator's habitable limits: coordinates are clamped so every ring renders
# cleanly in web mercator and nothing wraps over the poles.
LAT_CLAMP = 85.0511287798066

SOURCES = {
    "countries": "ne_50m_admin_0_countries.geojson",
    "coastline": "ne_50m_coastline.geojson",
    "lakes": "ne_50m_lakes.geojson",
    "rivers": "ne_50m_rivers_lake_centerlines.geojson",
    "urban": "ne_50m_urban_areas.geojson",
    "places": "ne_10m_populated_places.geojson",
}


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def _rings_of(geometry: dict) -> list[list[tuple[float, float]]]:
    """Every polygon ring / line of any GeoJSON geometry type, flattened."""
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    if not coords:
        return []
    if gtype == "Polygon":
        return [[(float(x), float(y)) for x, y, *_ in ring] for ring in coords]
    if gtype == "MultiPolygon":
        return [[(float(x), float(y)) for x, y, *_ in ring]
                for poly in coords for ring in poly]
    if gtype == "LineString":
        return [[(float(x), float(y)) for x, y, *_ in coords]]
    if gtype == "MultiLineString":
        return [[(float(x), float(y)) for x, y, *_ in line] for line in coords]
    return []


def _pack_line(points: list[tuple[float, float]]) -> list[int]:
    """Delta-encoded int pairs at 1e5 — the wire format vectormap.js unpacks."""
    out: list[int] = []
    prev_lat = prev_lon = 0
    for lon, lat in points:
        lat = max(-LAT_CLAMP, min(LAT_CLAMP, lat))
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        if not out:
            out.extend([ilat, ilon])
        else:
            out.extend([ilat - prev_lat, ilon - prev_lon])
        prev_lat, prev_lon = ilat, ilon
    return out


def _simplify(points: list[tuple[float, float]], tolerance: float
              ) -> list[tuple[float, float]]:
    """Douglas–Peucker — the world base renders at every zoom, so the lines
    carry only the vertices that keep their shape."""
    if len(points) < 3 or tolerance <= 0:
        return points

    def perp(pt, a, b):
        if a == b:
            return ((pt[0] - a[0]) ** 2 + (pt[1] - a[1]) ** 2) ** 0.5
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy)
                         / (dx * dx + dy * dy)))
        px, py = a[0] + t * dx, a[1] + t * dy
        return ((pt[0] - px) ** 2 + (pt[1] - py) ** 2) ** 0.5

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, index = 0.0, None
        for i in range(first + 1, last):
            d = perp(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep, strict=True) if k]


# --------------------------------------------------------------------------- #
# layer conversion
# --------------------------------------------------------------------------- #
def _names(props: dict) -> tuple[str, str]:
    ne = (props.get("NAME") or props.get("name") or props.get("NAMEASCII")
          or props.get("name_en") or props.get("NAME_EN") or "")
    n = (props.get("NAME_AR") or props.get("name_ar") or ne)
    return n, ne


def _label_anchor(props: dict, ring: list[tuple[float, float]]
                  ) -> tuple[float, float]:
    lat = props.get("LABEL_Y") or props.get("latitude")
    lon = props.get("LABEL_X") or props.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lon), float(lat)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _place_rank(props: dict) -> int:
    """SCALERANK 0 is a world city, 10 a dot: invert to the pack's 1..6 rank
    where 6 draws the largest circle."""
    try:
        s = int(props.get("SCALERANK") or props.get("scalerank") or 10)
    except (TypeError, ValueError):
        s = 10
    return max(1, min(6, 7 - s))


def build(source_dir: Path, target: Path) -> dict:
    def load(name: str) -> list[dict]:
        path = source_dir / SOURCES[name]
        if not path.exists():
            raise SystemExit(f"missing source: {path}")
        return (json.loads(path.read_text(encoding="utf-8"))
                .get("features") or [])

    pack: dict = {
        "v": 2,
        "bbox": {"w": -180.0, "s": -LAT_CLAMP, "e": 180.0, "n": LAT_CLAMP},
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "source": "Natural Earth (public domain) · world base",
        "detail": "medium",
        "roads": [], "rail": [], "water": [], "waterLines": [],
        "green": [], "places": [], "areas": [], "urban": [],
    }

    # country borders: every ring of every country as a faint admin line —
    # the border mesh a reader expects from a street map's underlay
    borders = 0
    for feature in load("countries"):
        for ring in _rings_of(feature.get("geometry") or {}):
            ring = _simplify(ring, 0.01)
            if len(ring) < 2:
                continue
            pack["roads"].append({"k": "minor", "p": _pack_line(ring)})
            borders += 1
        props = feature.get("properties") or {}
        ring = _rings_of(feature.get("geometry") or {})
        if ring:
            lon, lat = _label_anchor(props, max(ring, key=len))
            n, ne = _names(props)
            if ne:
                pack["areas"].append({"n": n, "ne": ne, "k": "country",
                                      "r": 6, "lat": round(lat, 5),
                                      "lng": round(lon, 5)})
    print(f"  countries: {borders} border rings, {len(pack['areas'])} labels")

    # coastlines and rivers as water lines; lakes and urban areas as fills
    n = 0
    for feature in load("coastline"):
        for ring in _rings_of(feature.get("geometry") or {}):
            ring = _simplify(ring, 0.01)
            if len(ring) < 2:
                continue
            pack["waterLines"].append({"k": "coast", "p": _pack_line(ring)})
            n += 1
    print(f"  coastline: {n} lines")

    n = 0
    for feature in load("rivers"):
        for ring in _rings_of(feature.get("geometry") or {}):
            ring = _simplify(ring, 0.01)
            if len(ring) < 2:
                continue
            pack["waterLines"].append({"k": "river", "p": _pack_line(ring)})
            n += 1
    print(f"  rivers: {n} lines")

    n = 0
    for feature in load("lakes"):
        for ring in _rings_of(feature.get("geometry") or {}):
            ring = _simplify(ring, 0.008)
            if len(ring) < 4:
                continue
            pack["water"].append({"p": _pack_line(ring)})
            n += 1
    print(f"  lakes: {n} rings")

    n = 0
    for feature in load("urban"):
        for ring in _rings_of(feature.get("geometry") or {}):
            ring = _simplify(ring, 0.008)
            if len(ring) < 4:
                continue
            pack["urban"].append({"p": _pack_line(ring)})
            n += 1
    print(f"  urban: {n} rings")

    # the gazetteer: every city in the world, Arabic and English side by side
    n = 0
    for feature in load("places"):
        geom = feature.get("geometry") or {}
        props = feature.get("properties") or {}
        if geom.get("type") != "Point":
            continue
        try:
            lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        name_ar, name_en = _names(props)
        t = "city" if (props.get("SCALERANK") or 10) <= 4 else "town"
        pack["places"].append({
            "n": name_ar, "ne": name_en, "t": t, "k": "city",
            "r": _place_rank(props),
            "lat": round(lat, 5), "lng": round(lon, 5),
        })
        n += 1
    print(f"  places: {n} cities")

    data = json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    gz = target.with_suffix(target.suffix + ".gz")
    gz.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    print(f"vectormap written: {target} ({len(data) / 1e6:.2f} MB, "
          f"{gz.stat().st_size / 1e6:.2f} MB gz)")
    return {"path": str(target), "bytes": len(data), "gz": gz.stat().st_size}


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Build the SIRAJ world vectormap pack.")
    ap.add_argument("--source", default=str(here / "source"),
                    help="directory holding the Natural Earth GeoJSON files")
    ap.add_argument("--target", default=str(PACK_DIR / WORLD_NAME))
    args = ap.parse_args(argv)
    print(f"SIRAJ · world vectormap from {args.source}")
    build(Path(args.source), Path(args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
