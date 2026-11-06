"""
SIRAJ · render the world raster tilepack.

The application stores every map it shows. The online providers cover the world
when there is a network; when there is not, the offline stores must still cover
the world. This module renders the raster map type — the `.tilepack` behind
`/api/geo/tiles/{z}/{x}/{y}.webp` — from the shipped vector packs:

    z0–z6      the entire world from the Natural Earth basemap pack
    z7–z15     the working area, street by street, from the OSM street pack

Every tile is drawn twice the target size and downscaled (two-sample
antialiasing), labelled in English (the bilingual names live in the vector
modes, which draw labels in the interface language), and encoded as WebP.
The output is deterministic for a given source pack and font.

Build:

    python3 -m app.geo.tilepack_build [--max-world-zoom 6] [--detail-max-zoom 15]

Natural Earth is public domain; the street extract is © OpenStreetMap
contributors (ODbL). Both are credited in the pack's attribution line.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import struct
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.geo import basemap
from app.geo.offline_pack import GAZA_BOUNDS, PACK_DIR, TILEPACK_NAME, vectormap_gz_path, vectormap_path

TILE = 256
SSAA = 2
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/tmp/fonts/fonts/Open_Sans/OpenSans-Regular.ttf",
)

# palette — parchment land, quiet water, warm borders: the street-map family
# the vector modes draw with (vectormap.js #f4f1ea / #a8c8e0 / #c5ddb0)
COL_SEA = (226, 236, 244)
COL_LAND = (247, 244, 238)
COL_URBAN = (232, 224, 212)
COL_LAKE = (185, 212, 234)
COL_RIVER = (140, 178, 208)
COL_COAST = (150, 172, 190)
COL_BORDER = (198, 182, 156)
COL_GREEN = (197, 221, 176)
COL_WATER = (168, 200, 224)
COL_ROAD_MAJOR = (201, 160, 106)
COL_ROAD_MINOR = (184, 176, 164)
COL_DOT = (90, 70, 50)
COL_TEXT = (74, 64, 52)
COL_HALO = (255, 252, 244)

MAGIC = b"TILEPACK"
HEADER_SIZE = 24
ENTRY_SIZE = 20

# --------------------------------------------------------------------------- #
# slippy-map projection
# --------------------------------------------------------------------------- #
def lonlat_to_px(lon: float, lat: float, zoom: float) -> tuple[float, float]:
    scale = TILE * (2.0 ** zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat = max(-85.0511287798066, min(85.0511287798066, lat))
    siny = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * scale
    return x, y


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(west, south, east, north) of one tile."""
    n = 2.0 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    def lat_of(yy: float) -> float:
        t = math.pi * (1 - 2 * yy / n)
        return math.degrees(math.atan(math.sinh(t)))
    return west, lat_of(y + 1), east, lat_of(y)


def tiles_covering(w: float, s: float, e: float, n: float, z: int) -> list[tuple[int, int, int]]:
    """Every tile in a lon/lat box at zoom z."""
    def ty(lat: float) -> int:
        lat = max(-85.0511287798066, min(85.0511287798066, lat))
        siny = math.sin(math.radians(lat))
        yy = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi))
        return max(0, min(2 ** z - 1, int(yy * 2 ** z)))
    def tx(lon: float) -> int:
        return max(0, min(2 ** z - 1, int((lon + 180.0) / 360.0 * 2 ** z)))
    out = []
    for x in range(tx(w), tx(e) + 1):
        for y in range(ty(n), ty(s) + 1):
            out.append((z, x, y))
    return out


# --------------------------------------------------------------------------- #
# geometry: unpack the vectormap's delta format, clip, draw
# --------------------------------------------------------------------------- #
def unpack(p: list[int]) -> list[tuple[float, float]]:
    out = []
    la = lg = 0
    for i in range(0, len(p) - 1, 2):
        la += p[i]
        lg += p[i + 1]
        out.append((lg / 1e5, la / 1e5))
    return out


def _ring_bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _geojson_rings(geom: dict) -> tuple[str, list[list[tuple[float, float]]]]:
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        return "polygon", [[(float(x), float(y)) for x, y, *_ in ring] for ring in coords]
    if gtype == "MultiPolygon":
        return "polygon", [[(float(x), float(y)) for x, y, *_ in ring]
                           for poly in coords for ring in poly]
    if gtype == "LineString":
        return "line", [[(float(x), float(y)) for x, y, *_ in coords]]
    if gtype == "MultiLineString":
        return "line", [[(float(x), float(y)) for x, y, *_ in line] for line in coords]
    if gtype == "Point":
        return "point", [[(float(coords[0]), float(coords[1]))]]
    return "none", []


def clip_line(pts: list[tuple[float, float]],
              w: float, s: float, e: float, n: float,
              margin: float = 0.5) -> list[list[tuple[float, float]]]:
    """Split a polyline into the parts that touch the (expanded) tile box."""
    w, s, e, n = w - margin, s - margin, e + margin, n + margin
    parts: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []

    def inside(p):
        return w <= p[0] <= e and s <= p[1] <= n

    def intersect(a, b):
        # walk the segment to the box edge (binary chop — enough for drawing)
        lo, hi = 0.0, 1.0
        for _ in range(24):
            mid = (lo + hi) / 2
            p = (a[0] + (b[0] - a[0]) * mid, a[1] + (b[1] - a[1]) * mid)
            if inside(p):
                lo = mid
            else:
                hi = mid
        return (a[0] + (b[0] - a[0]) * hi, a[1] + (b[1] - a[1]) * hi)

    prev = pts[0] if pts else None
    for p in pts[1:]:
        a_in, b_in = inside(prev), inside(p)
        if a_in and b_in:
            if not cur:
                cur.append(prev)
            cur.append(p)
        elif a_in and not b_in:
            cur.append(intersect(prev, p))
            if len(cur) > 1:
                parts.append(cur)
            cur = []
        elif not a_in and b_in:
            cur = [intersect(prev, p), p]
        prev = p
    if len(cur) > 1:
        parts.append(cur)
    return parts


def clip_ring(pts: list[tuple[float, float]],
              w: float, s: float, e: float, n: float) -> list[tuple[float, float]]:
    """Sutherland–Hodgman against the tile box; empty when wholly outside."""

    def clip_edge(poly, keep, cross):
        out = []
        if not poly:
            return out
        for i in range(len(poly)):
            a, b = poly[i - 1], poly[i]
            ka, kb = keep(a), keep(b)
            if kb:
                if not ka:
                    out.append(cross(a, b))
                out.append(b)
            elif ka:
                out.append(cross(a, b))
        return out

    def inter_x(a, b, x):
        t = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
        return (x, a[1] + (b[1] - a[1]) * t)

    def inter_y(a, b, y):
        t = (y - a[1]) / (b[1] - a[1]) if b[1] != a[1] else 0.0
        return (a[0] + (b[0] - a[0]) * t, y)

    poly = pts
    poly = clip_edge(poly, lambda p: p[0] >= w, lambda a, b: inter_x(a, b, w))
    poly = clip_edge(poly, lambda p: p[0] <= e, lambda a, b: inter_x(a, b, e))
    poly = clip_edge(poly, lambda p: p[1] >= s, lambda a, b: inter_y(a, b, s))
    poly = clip_edge(poly, lambda p: p[1] <= n, lambda a, b: inter_y(a, b, n))
    return poly


# --------------------------------------------------------------------------- #
# one tile
# --------------------------------------------------------------------------- #
class Painter:
    """Shared, per-process state: fonts, source indexes, clip-and-draw."""

    def __init__(self, font_path: str | None, street_pack: dict | None,
                 street_bbox_index: list | None):
        self.font_path = font_path
        self.street = street_pack
        self.street_index = street_bbox_index or []
        self._fonts: dict[int, Any] = {}

    def font(self, px: int) -> Any:
        if px not in self._fonts:
            if self.font_path:
                self._fonts[px] = ImageFont.truetype(self.font_path, px)
            else:
                self._fonts[px] = ImageFont.load_default()
        return self._fonts[px]

    def label(self, draw, lon, lat, text, zoom, px_size, color=COL_TEXT,
              bold=False, halo=COL_HALO, placed=None, anchor="mm"):
        if not text:
            return
        font = self.font(px_size)
        x, y = lonlat_to_px(lon, lat, zoom)
        bbox = draw.textbbox((x, y), text, font=font, anchor=anchor)
        pad = 2
        rect = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
        if placed is not None:
            for other in placed:
                if rect[0] < other[2] and rect[2] > other[0] and \
                   rect[1] < other[3] and rect[3] > other[1]:
                    return
            placed.append(rect)
        draw.text((x, y), text, font=font, fill=color, anchor=anchor,
                  stroke_width=max(1, px_size // 8), stroke_fill=halo)


def _find_font(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for cand in FONT_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return None


def _load_street_pack() -> tuple[dict | None, list]:
    """The working-area street pack, with per-feature bboxes for fast filtering."""
    gz = vectormap_gz_path()
    raw = vectormap_path()
    data = None
    if gz.is_file():
        with gzip.open(gz, "rb") as f:
            data = f.read()
    elif raw.is_file():
        data = raw.read_bytes()
    if not data:
        return None, []
    pack = json.loads(data.decode("utf-8"))
    index = []
    for fam in ("roads", "rail", "water", "waterLines", "green", "urban"):
        for i, item in enumerate(pack.get(fam) or []):
            ring = unpack(item.get("p") or [])
            if len(ring) < 2:
                continue
            index.append((fam, i, _ring_bbox(ring), ring))
    return pack, index


_PAINTER: Painter | None = None


def _init_worker(font_path: str | None):
    global _PAINTER
    _PAINTER = Painter(font_path, *_load_street_pack())


def render_tile(job: tuple[int, int, int, int]) -> tuple[int, int, int, bytes]:
    z, x, y, world_max = job
    painter = _PAINTER
    S = TILE * SSAA
    img = Image.new("RGB", (S, S), COL_SEA)
    draw = ImageDraw.Draw(img)
    west, south, east, north = tile_bounds(z, x, y)
    ox, oy = lonlat_to_px(west, north, z)
    ox *= SSAA
    oy *= SSAA
    zoom_ss = z + math.log2(SSAA)

    def px(lon, lat):
        X, Y = lonlat_to_px(lon, lat, zoom_ss)
        return X - ox, Y - oy

    def draw_poly(rings, fill, outline=None, width=1):
        for ring in rings:
            clip = clip_ring(ring, west - 0.4, south - 0.4, east + 0.4, north + 0.4)
            if len(clip) < 3:
                continue
            draw.polygon([px(lo, la) for lo, la in clip], fill=fill,
                         outline=outline, width=width)

    def draw_lines(rings, color, width):
        for ring in rings:
            for part in clip_line(ring, west, south, east, north, 0.4):
                if len(part) < 2:
                    continue
                draw.line([px(lo, la) for lo, la in part], fill=color,
                          width=max(1, int(round(width * SSAA))), joint="curve")

    def layer(name, bbox_pad=0.4):
        doc = basemap.features(name, zoom=float(z),
                               bbox=(west - bbox_pad, south - bbox_pad,
                                     east + bbox_pad, north + bbox_pad),
                               limit=6000)
        return (doc.get("collection") or {}).get("features") or []

    # ------------------------------------------------------------- land ---
    for f in layer("countries"):
        kind, rings = _geojson_rings(f["geometry"])
        if kind == "polygon":
            draw_poly(rings, COL_LAND)
    for f in layer("urban"):
        kind, rings = _geojson_rings(f["geometry"])
        if kind == "polygon":
            draw_poly(rings, COL_URBAN)
    for f in layer("lakes"):
        kind, rings = _geojson_rings(f["geometry"])
        if kind == "polygon":
            draw_poly(rings, COL_LAKE)

    # --------------------------------------------- hydrography & borders ---
    for f in layer("rivers"):
        kind, rings = _geojson_rings(f["geometry"])
        if kind == "line":
            draw_lines(rings, COL_RIVER, 1.1)
    for f in layer("coastline"):
        kind, rings = _geojson_rings(f["geometry"])
        if kind == "line":
            draw_lines(rings, COL_COAST, 1.2)
    for f in layer("countries"):
        kind, rings = _geojson_rings(f["geometry"])
        if kind == "polygon":
            draw_lines(rings, COL_BORDER, 1.0)

    # ------------------------------------------------- street detail pack ---
    # the working area's own streets: fills under, roads over the basemap
    if painter.street is not None and z >= 7:
        tbox = (west - 0.2, south - 0.2, east + 0.2, north + 0.2)

        def visible(fb):
            return not (fb[2] < tbox[0] or fb[0] > tbox[2] or
                        fb[3] < tbox[1] or fb[1] > tbox[3])

        for fam, _i, fb, ring in painter.street_index:
            if not visible(fb):
                continue
            if fam in ("water", "green", "urban"):
                draw_poly([ring], {"water": COL_WATER, "green": COL_GREEN,
                                   "urban": COL_URBAN}[fam])
            elif fam == "waterLines":
                draw_lines([ring], COL_RIVER, 1.2)
        for fam, _i, fb, ring in painter.street_index:
            if fam not in ("roads", "rail") or not visible(fb):
                continue
            draw_lines([ring], COL_ROAD_MINOR, 1.4)

    # ------------------------------------------------------------ labels ---
    placed: list = []
    if z >= 2:
        for f in layer("countries"):
            props = f["properties"] or {}
            name = props.get("name_en") or ""
            kind, rings = _geojson_rings(f["geometry"])
            if not name or not rings:
                continue
            big = max(rings, key=len)
            lon = sum(p[0] for p in big) / len(big)
            lat = sum(p[1] for p in big) / len(big)
            if not (west <= lon <= east and south <= lat <= north):
                continue
            painter.label(draw, lon, lat, name, zoom_ss,
                          {2: 11, 3: 10}.get(z, 9) * SSAA,
                          bold=True, placed=placed)
    if z >= 2:
        cities = []
        for f in layer("places"):
            props = f["properties"] or {}
            kind, rings = _geojson_rings(f["geometry"])
            if kind != "point" or not rings:
                continue
            lon, lat = rings[0][0]
            if not (west - 0.1 <= lon <= east + 0.1 and south - 0.1 <= lat <= north + 0.1):
                continue
            cities.append((props.get("population") or 0, lon, lat,
                           props.get("name_en") or ""))
        cities.sort(reverse=True)
        max_labels = {2: 8, 3: 12, 4: 16, 5: 22, 6: 28}.get(z, 30)
        shown = 0
        for _pop, lon, lat, name in cities:
            if shown >= max_labels:
                break
            painter.label(draw, lon, lat, name, zoom_ss, 8 * SSAA, placed=placed)
            shown += 1
        for _pop, lon, lat, _name in cities[max_labels:max_labels + 40]:
            X, Y = px(lon, lat)
            draw.ellipse((X - 1.5 * SSAA, Y - 1.5 * SSAA,
                          X + 1.5 * SSAA, Y + 1.5 * SSAA),
                         fill=COL_DOT, outline=COL_HALO, width=1)
    out = img.resize((TILE, TILE), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="WEBP", quality=82, method=4)
    return z, x, y, buf.getvalue()


# --------------------------------------------------------------------------- #
# tilepack writer
# --------------------------------------------------------------------------- #
def write_tilepack(path: Path, tiles: list[tuple[int, int, int, bytes]],
                   meta: dict) -> int:
    tiles = sorted(tiles)
    index = bytearray()
    body = bytearray()
    offset = 0
    for z, x, y, data in tiles:
        index += struct.pack("<IIIII", z, x, y, offset, len(data))
        body += data
        offset += len(data)
    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    header = MAGIC + struct.pack("<IIII", 1, len(meta_bytes), len(tiles), 0)
    blob = header + meta_bytes + bytes(index) + bytes(body)
    path.write_bytes(blob)
    return len(blob)


def build(target: Path, font_path: str | None, max_world_zoom: int,
          detail_max_zoom: int, workers: int) -> dict:
    jobs: list[tuple[int, int, int, int]] = []
    for z in range(0, max_world_zoom + 1):
        for t in tiles_covering(-180.0, -85.0511287798066, 180.0, 85.0511287798066, z):
            jobs.append((*t, max_world_zoom))
    detail_tiles = set()
    for z in range(max_world_zoom + 1, detail_max_zoom + 1):
        for t in tiles_covering(GAZA_BOUNDS["w"], GAZA_BOUNDS["s"],
                                GAZA_BOUNDS["e"], GAZA_BOUNDS["n"], z):
            if t not in detail_tiles:
                detail_tiles.add(t)
                jobs.append((*t, max_world_zoom))
    print(f"rendering {len(jobs)} tiles "
          f"(world z0–{max_world_zoom} + working area z{max_world_zoom + 1}–{detail_max_zoom}) "
          f"on {workers} workers")
    tiles: list[tuple[int, int, int, bytes]] = []
    done = 0
    with Pool(workers, initializer=_init_worker, initargs=(font_path,)) as pool:
        for result in pool.imap_unordered(render_tile, jobs, chunksize=8):
            tiles.append(result)
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(jobs)}")
    meta = {
        "name": "SIRAJ world basemap",
        "bounds": {"w": -180.0, "s": -85.0511287798066,
                   "e": 180.0, "n": 85.0511287798066},
        "format": "webp",
        "minzoom": 0,
        "maxzoom": detail_max_zoom,
        "tileSize": TILE,
        "attribution": "Basemap: Natural Earth (public domain) · "
                       "streets © OpenStreetMap contributors (ODbL)",
    }
    size = write_tilepack(target, tiles, meta)
    print(f"tilepack written: {target} ({size / 1e6:.2f} MB, {len(tiles)} tiles)")
    return {"path": str(target), "bytes": size, "tiles": len(tiles)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the SIRAJ world raster tilepack.")
    ap.add_argument("--target", default=str(PACK_DIR / TILEPACK_NAME))
    ap.add_argument("--font", default=None, help="TTF font for labels")
    ap.add_argument("--max-world-zoom", type=int, default=6)
    ap.add_argument("--detail-max-zoom", type=int, default=15)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if not basemap.available():
        print("basemap pack missing — run python3 -m app.geo.basemap_build first",
              file=sys.stderr)
        return 1
    font = _find_font(args.font)
    if not font:
        print("warning: no TTF font found — labels will be minimal", file=sys.stderr)
    print(f"SIRAJ · world tilepack (font: {font or 'none'})")
    build(Path(args.target), font, args.max_world_zoom, args.detail_max_zoom,
          args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
