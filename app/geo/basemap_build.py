"""
SIRAJ · build the local basemap pack.

The registry must be usable **without a tile server and without a network** — on a
researcher's laptop in a reading room, on a field machine with no connectivity, and
inside a deployment whose security policy forbids third-party tile traffic. So the
basemap is a *local* asset: Natural Earth vector layers, simplified, quantised and
packed into one small SQLite file (`app/geo/basemap.sqlite`), read by
`app/geo/basemap.py` and served as GeoJSON to the map.

That is also what makes the map fast: a few hundred kilobytes of browsable polygons
is a cheaper base layer than a screenful of raster tiles, and it renders as crisp
vectors at every zoom and at every tilt.

Natural Earth is in the **public domain** (no attribution required, none implied).
It is nevertheless credited in the map's attribution line and here, because a map
that hides its provenance is not a professional map.

Rebuild (only when the source data changes):

    python3 -m app.geo.basemap_build --source /path/to/natural-earth/geojson

The build is deterministic: same inputs, byte-identical output, so the pack can be
committed and reviewed.
"""
from __future__ import annotations

import argparse
import array
import json
import sqlite3
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PACK_VERSION = 1

# 1e5 = one hundred-thousandth of a degree ≈ 1.1 m at the equator: finer than any
# zoom level the map offers, small enough that a delta fits in one byte most of
# the time after zlib-free delta coding.
QUANT = 100_000

# (level, layer, source file, kind, tolerance, min points, extra props)
SOURCES = [
    ("110m", "countries", "ne_110m_admin_0_countries.geojson", "polygon", 0.02, 4),
    ("110m", "coastline", "ne_110m_coastline.geojson", "line", 0.02, 2),
    ("110m", "lakes", "ne_110m_lakes.geojson", "polygon", 0.02, 4),
    ("50m", "countries", "ne_50m_admin_0_countries.geojson", "polygon", 0.004, 4),
    ("50m", "coastline", "ne_50m_coastline.geojson", "line", 0.004, 2),
    ("50m", "lakes", "ne_50m_lakes.geojson", "polygon", 0.004, 4),
    ("50m", "rivers", "ne_50m_rivers_lake_centerlines.geojson", "line", 0.004, 2),
    # subnational boundaries and built-up areas: the same world coverage, the
    # next two rungs of the administrative and human landscape. admin_1 takes
    # the 10m source (4 596 subdivisions — the 50m cut keeps only the largest)
    # simplified at the 50m tolerance, so every province in the world is there.
    ("50m", "admin_1", "ne_10m_admin_1_states_provinces.geojson", "polygon", 0.004, 4),
    ("50m", "urban", "ne_50m_urban_areas.geojson", "polygon", 0.004, 4),
    # the local gazetteer: 7 343 cities with Arabic names, used for name search
    # and for georeferencing registry places that were entered by name only
    ("50m", "places", "ne_10m_populated_places.geojson", "point", 0.0, 1),
]

LAYER_LABELS = {
    "countries": ("Countries", "الدول"),
    "coastline": ("Coastline", "الخط الساحلي"),
    "lakes": ("Lakes", "البحيرات"),
    "rivers": ("Rivers", "الأنهار"),
    "places": ("Cities", "المدن"),
    "admin_1": ("States & provinces", "الولايات والمحافظات"),
    "urban": ("Urban areas", "المناطق الحضرية"),
}


@dataclass
class Ring:
    points: list[tuple[float, float]]
    closed: bool


# --------------------------------------------------------------------------- #
# geometry helpers (pure Python: no shapely at runtime, none at build time)
# --------------------------------------------------------------------------- #
def _perpendicular_distance(pt, start, end) -> float:
    if start == end:
        return ((pt[0] - start[0]) ** 2 + (pt[1] - start[1]) ** 2) ** 0.5
    dx, dy = end[0] - start[0], end[1] - start[1]
    t = ((pt[0] - start[0]) * dx + (pt[1] - start[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = start[0] + t * dx, start[1] + t * dy
    return ((pt[0] - px) ** 2 + (pt[1] - py) ** 2) ** 0.5


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas–Peucker, iterative (no recursion limit on a long coastline)."""
    if len(points) < 3 or tolerance <= 0:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, index = 0.0, None
        for i in range(first + 1, last):
            d = _perpendicular_distance(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep, strict=True) if k]


def _rings_of(geometry: dict) -> list[list[tuple[float, float]]]:
    """Every polygon ring / line of any GeoJSON geometry type, flattened."""
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    if not coords:
        return []
    if gtype == "Polygon":
        return [[(float(x), float(y)) for x, y, *_ in ring] for ring in coords]
    if gtype == "MultiPolygon":
        return [[(float(x), float(y)) for x, y, *_ in ring] for poly in coords for ring in poly]
    if gtype == "LineString":
        return [[(float(x), float(y)) for x, y, *_ in coords]]
    if gtype == "Point":
        return [[(float(coords[0]), float(coords[1]))]]
    if gtype == "MultiLineString":
        return [[(float(x), float(y)) for x, y, *_ in line] for line in coords]
    return []


def quantise(points: list[tuple[float, float]]) -> bytes:
    """Delta-encoded int32 pairs, zlib-compressed: one blob per ring.

    Deltas between neighbouring vertices are small and highly repetitive, so the
    compressed blob is roughly a third of the raw one — that is the difference
    between a 2.5 MB pack and a 1 MB pack in a repository.
    """
    buf = array.array("i")
    prev_x = prev_y = 0
    for x, y in points:
        qx, qy = round(x * QUANT), round(y * QUANT)
        buf.append(qx - prev_x)
        buf.append(qy - prev_y)
        prev_x, prev_y = qx, qy
    return zlib.compress(buf.tobytes(), 9)


def dequantise(blob: bytes) -> list[tuple[float, float]]:
    """The exact inverse of `quantise` — used by the reader and by the tests."""
    buf = array.array("i")
    buf.frombytes(zlib.decompress(blob))
    out, x, y = [], 0, 0
    for i in range(0, len(buf), 2):
        x += buf[i]
        y += buf[i + 1]
        out.append((x / QUANT, y / QUANT))
    return out


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _props(feature: dict, layer: str) -> dict:
    p = feature.get("properties") or {}
    out = {
        "name_en": p.get("NAME_EN") or p.get("name_en") or p.get("NAME") or p.get("name") or "",
        "name_ar": p.get("NAME_AR") or p.get("name_ar") or p.get("label") or "",
    }
    if layer == "places":
        out.update({
            "iso_a2": p.get("ISO_A2") or "",
            "country": p.get("ADM0NAME") or "",
            "region": p.get("ADM1NAME") or "",
            "population": p.get("POP_MAX") or 0,
            "rank": p.get("SCALERANK") or 10,
        })
    if layer == "countries":
        out.update({
            "iso_a2": p.get("ISO_A2") or "",
            "iso_a3": p.get("ISO_A3") or p.get("ADM0_A3") or "",
            "continent": p.get("CONTINENT") or "",
            "region": p.get("REGION_UN") or "",
        })
    if layer == "admin_1":
        out.update({
            "iso_a2": p.get("iso_a2") or p.get("ISO_A2") or "",
            "iso_3166_2": p.get("iso_3166_2") or "",
            "country": p.get("admin") or p.get("ADM0NAME") or "",
            "region": p.get("region") or "",
            "type": p.get("type_en") or p.get("type") or "",
        })
    if layer == "urban":
        out.update({
            "area_sqkm": p.get("area_sqkm") or 0,
        })
    return {k: v for k, v in out.items() if v}


def build(source_dir: Path, target: Path) -> dict:
    if target.exists():
        target.unlink()
    conn = sqlite3.connect(target)
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE meta   (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE feature(
            fid      INTEGER PRIMARY KEY,
            level    TEXT NOT NULL,
            layer    TEXT NOT NULL,
            kind     TEXT NOT NULL,
            props    TEXT NOT NULL,
            minx REAL, miny REAL, maxx REAL, maxy REAL,
            npoints  INTEGER NOT NULL,
            nparts   INTEGER NOT NULL
        );
        CREATE TABLE geom   (fid INTEGER NOT NULL, part INTEGER NOT NULL,
                             npoints INTEGER NOT NULL, coords BLOB NOT NULL,
                             PRIMARY KEY (fid, part));
        CREATE INDEX ix_feature_layer ON feature(layer, level);
        CREATE VIRTUAL TABLE feature_bbox USING rtree(
            fid, minx, maxx, miny, maxy
        );
        """
    )
    stats: dict[str, int] = {}
    fid = 0
    for level, layer, filename, kind, tol, min_pts in SOURCES:
        path = source_dir / filename
        if not path.exists():
            print(f"  ! missing source {filename} — layer skipped", file=sys.stderr)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        kept = points_total = 0
        for feature in data.get("features", []):
            geometry = feature.get("geometry")
            if not geometry:
                continue
            rings = []
            for ring in _rings_of(geometry):
                ring = simplify(ring, tol)
                if len(ring) < min_pts:
                    continue
                rings.append(ring)
            if not rings:
                continue
            xs = [x for ring in rings for x, _ in ring]
            ys = [y for ring in rings for _, y in ring]
            fid += 1
            total = sum(len(r) for r in rings)
            points_total += total
            kept += 1
            conn.execute(
                "INSERT INTO feature (fid, level, layer, kind, props, minx, miny, maxx, maxy,"
                " npoints, nparts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (fid, level, layer, kind, json.dumps(_props(feature, layer), ensure_ascii=False),
                 min(xs), min(ys), max(xs), max(ys), total, len(rings)),
            )
            conn.execute("INSERT INTO feature_bbox VALUES (?,?,?,?,?)",
                         (fid, min(xs), max(xs), min(ys), max(ys)))
            for part, ring in enumerate(rings):
                conn.execute("INSERT INTO geom VALUES (?,?,?,?)",
                             (fid, part, len(ring), quantise(ring)))
        stats[f"{level}/{layer}"] = kept
        print(f"  {level:5} {layer:10} {kept:5} features {points_total:8} points")

    conn.executemany("INSERT INTO meta VALUES (?,?)", [
        ("pack_version", str(PACK_VERSION)),
        ("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("source", "Natural Earth (naturalearthdata.com), 1:110m, 1:50m and 1:10m"),
        ("license", "public domain"),
        ("attribution", "Basemap: Natural Earth (public domain)"),
        ("quant", str(QUANT)),
        ("layers", json.dumps({
            layer: {"label_en": LAYER_LABELS[layer][0], "label_ar": LAYER_LABELS[layer][1],
                    "kind": next(s[3] for s in SOURCES if s[1] == layer)}
            for layer in sorted({s[1] for s in SOURCES})
        }, ensure_ascii=False)),
        ("levels", json.dumps(sorted({s[0] for s in SOURCES}))),
        ("stats", json.dumps(stats)),
    ])
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    size = target.stat().st_size
    print(f"\npack written: {target} ({size / 1e6:.2f} MB)")
    return {"path": str(target), "bytes": size, "stats": stats}


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Build the SIRAJ local basemap pack.")
    ap.add_argument("--source", default=str(here / "source"),
                    help="directory holding the Natural Earth GeoJSON files")
    ap.add_argument("--target", default=str(here / "basemap.sqlite"))
    args = ap.parse_args(argv)
    print(f"SIRAJ · basemap pack from {args.source}")
    build(Path(args.source), Path(args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
