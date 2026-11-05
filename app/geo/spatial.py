"""
SIRAJ · geospatial maths.

Everything the map needs to be *correct* rather than merely pretty, in one module
with no dependencies beyond the standard library:

  * coordinate parsing — decimal degrees, degrees/minutes/seconds, hemisphere
    letters before or after the number, Arabic-Indic digits, separators of every
    shape a researcher's spreadsheet produces;
  * coordinate formatting — DD and DMS, in the reader's language;
  * validation — latitude ±90, longitude ±180 (inclusive), NaN/∞ refused;
  * the antimeridian — windows that cross 180° are split, never silently inverted;
  * distances and bearings — haversine (metres) and great-circle bearing;
  * polygon measurement — spherical excess, the area a geodesist would report;
  * point-in-polygon — ray casting with matplotlib-free winding on the raw rings;
  * CRS awareness — WGS 84 (EPSG:4326), CRS84 (lon/lat order) and Web Mercator
    (EPSG:3857) conversions, because the map renders in 3857 while every record
    stores 4326;
  * grid clustering and nearest-point search for a map that must stay readable at
    world scale.
"""
from __future__ import annotations

import math
import re

EARTH_RADIUS_M = 6_371_008.8
WGS84 = "EPSG:4326"
CRS84 = "OGC:CRS84"
WEB_MERCATOR = "EPSG:3857"

CRS_CATALOG = {
    WGS84: {
        "label_en": "WGS 84 — latitude, longitude (degrees)",
        "label_ar": "WGS 84 — خط العرض، خط الطول (بالدرجات)",
        "axis": "lat,lon", "unit": "degree", "kind": "geographic",
    },
    CRS84: {
        "label_en": "OGC:CRS84 — longitude, latitude (degrees)",
        "label_ar": "OGC:CRS84 — خط الطول، خط العرض (بالدرجات)",
        "axis": "lon,lat", "unit": "degree", "kind": "geographic",
    },
    WEB_MERCATOR: {
        "label_en": "Web Mercator — metres (the map display projection)",
        "label_ar": "مِركاتور الويب — بالأمتار (إسقاط عرض الخريطة)",
        "axis": "x,y", "unit": "metre", "kind": "projected",
        "note": "Used for drawing only. Records are always stored in WGS 84.",
        "note_ar": "يُستخدم للعرض فقط. السجلات محفوظة دائماً بنظام WGS 84.",
    },
}

# Arabic-Indic and extended Arabic-Indic digits, so a value copied out of an Arabic
# document parses exactly like the Latin one.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUM = r"[-+]?\d+(?:[.,]\d+)?"


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def valid_lat(value) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and -90.0 <= v <= 90.0


def valid_lon(value) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and -180.0 <= v <= 180.0


def validate_pair(lat, lon) -> dict:
    """`{"ok": True, "lat": …, "lon": …}` or `{"ok": False, "problems": [...]}`.

    Both ends or nothing: a marker needs a position, not half of one.
    """
    problems = []
    if not valid_lat(lat):
        problems.append({"field": "lat", "reason": "out_of_range",
                         "message": "latitude must be a number between -90 and 90"})
    if not valid_lon(lon):
        problems.append({"field": "lon", "reason": "out_of_range",
                         "message": "longitude must be a number between -180 and 180"})
    if problems:
        return {"ok": False, "problems": problems}
    return {"ok": True, "lat": round(float(lat), 7), "lon": round(float(lon), 7)}


def normalize_lon(lon: float) -> float:
    """Fold any longitude into [-180, 180). Callers never have to think about 540°."""
    return ((float(lon) + 180.0) % 360.0) - 180.0


# --------------------------------------------------------------------------- #
# parsing and formatting
# --------------------------------------------------------------------------- #
def _hemisphere(token: str) -> str | None:
    token = token.strip().upper()
    if not token:
        return None
    first = token[0]
    return first if first in "NSEW" else None


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def parse_dms(text: str) -> float | None:
    """One coordinate value: `33.3152`, `33°18'54.7"N`, `N 33 18 54.7`, `44 21.98 E`."""
    if text is None:
        return None
    raw = str(text).translate(_DIGITS).strip().replace("،", ",")
    if not raw:
        return None
    sign = -1.0 if raw.lstrip().startswith(("-", "−")) or raw.lstrip().upper().startswith("S") \
        or raw.lstrip().upper().startswith("W") else 1.0
    body = raw.upper().replace("−", "-")
    for h in "NSEW":
        body = body.replace(h, " ")
    body = re.sub(r"[°º˚D:]+", " ", body)
    body = re.sub(r"['’′M]+", " ", body)
    body = re.sub(r'["”″S]+', " ", body)
    body = body.replace("-", " ").replace("+", " ")
    parts = [p for p in re.split(r"[\s,]+", body) if p]
    if not parts or len(parts) > 3:
        return None
    try:
        values = [_to_float(p) for p in parts]
    except ValueError:
        return None
    if any(v < 0 for v in values):
        return None
    degrees = values[0]
    minutes = values[1] if len(values) > 1 else 0.0
    seconds = values[2] if len(values) > 2 else 0.0
    if minutes >= 60 or seconds >= 60:
        return None
    return sign * (degrees + minutes / 60.0 + seconds / 3600.0)


PAIR_PATTERNS = (
    # 33.3152, 44.3661  |  33.3152 44.3661  |  33.3152; 44.3661
    re.compile(rf"^\s*({_NUM})\s*[,;/ ]\s*({_NUM})\s*$"),
    # 33°18'54.7"N 44°21'58.0"E  |  N33 18 54.7 E44 21 58
    re.compile(r"^\s*(.*?)\s*[,;]?\s*([NSEWnsew].*?[EWew])\s*$"),
)


def _clean(text: str) -> str:
    """Normalise the digits and separators people actually paste."""
    out = str(text).translate(_DIGITS)
    for bad, good in (("\u066b", "."), ("\u066c", ""), ("\u060c", ","),
                      ("\u061b", ","), ("\u2212", "-"), ("\u2013", "-"),
                      ("\u00a0", " ")):
        out = out.replace(bad, good)
    return out.strip()


def _hemi_kind(raw: str, index: int) -> str:
    """`prefix` (N33 …), `suffix` (…54.7N) or `none` for one hemisphere letter."""
    before = raw[index - 1] if index else " "
    after = raw[index + 1] if index + 1 < len(raw) else " "
    before_digit = before.isdigit() or before in ".,'\u2032\u2033\""
    after_digit = after.isdigit() or after == "+" or after == "-"
    if before_digit and not after_digit:
        return "suffix"
    if after_digit and not before_digit:
        return "prefix"
    return "prefix" if before in " ,;:/" else "suffix"


def _split_halves(raw: str) -> tuple[str, str] | None:
    """Where does the latitude end and the longitude begin?

    The answer is decided by the hemisphere letters when there are two of them,
    because that is the only unambiguous signal — `N33 18 54.7 E44 21 58` and
    `33 18 54.7N 44 21 58E` are the same position written two ways.
    """
    letters = [(i, ch.upper()) for i, ch in enumerate(raw) if ch.upper() in "NSEW"]
    if len(letters) >= 2:
        (i1, _), (i2, _) = letters[0], letters[1]
        first_kind = _hemi_kind(raw, i1)
        second_kind = _hemi_kind(raw, i2)
        if first_kind == "suffix" and second_kind == "prefix":
            cut = i2
        elif first_kind == "prefix" and second_kind == "suffix":
            cut = i1 + 1
        elif first_kind == "suffix":
            cut = i1 + 1
        else:
            cut = i2
        return raw[:cut], raw[cut:]
    if "," in raw or ";" in raw:
        a, b = re.split(r"\s*[;,]\s*", raw, maxsplit=1)
        return a, b
    parts = [p for p in re.split(r"\s+", raw) if p]
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 6:
        return " ".join(parts[:3]), " ".join(parts[3:])
    return None


def parse_pair(text: str) -> dict:
    """Parse a position written in any of the shapes people actually type.

    `33.3152, 44.3661` · `33°18′54.7″N 44°21′58.0″E` · `N33 18 54.7 E44 21 58` ·
    `44.3661E 33.3152N` · `٣٣٫٣١٥٢، ٤٤٫٣٦٦١` · `-33.8688 151.2093`.
    Returns `{"ok": bool, …}`; never raises, because it runs on every keystroke.
    """
    if text is None or not str(text).strip():
        return {"ok": False, "reason": "empty", "message": "no coordinate given"}
    raw = _clean(text)
    if not raw:
        return {"ok": False, "reason": "empty", "message": "no coordinate given"}
    halves = _split_halves(raw)
    if not halves:
        if re.fullmatch(rf"\s*{_NUM}\s*", raw):
            return {"ok": False, "reason": "incomplete",
                    "message": "a position needs two values (latitude and longitude)"}
        return {"ok": False, "reason": "unparseable",
                "message": "could not read a latitude and longitude from that text"}
    first, second = halves
    lat_text, lon_text = first, second
    # a hemisphere letter decides which half is which, so `44.3661E 33.3152N` is not
    # silently read as lat=44 (which is a valid latitude, and therefore a silent lie)
    if re.search(r"[EWew]", first) and re.search(r"[NSns]", second):
        lat_text, lon_text = second, first
    lat, lon = parse_dms(lat_text), parse_dms(lon_text)
    return _finish(lat, lon)


def _finish(lat, lon) -> dict:
    if lat is None or lon is None:
        return {"ok": False, "reason": "unparseable",
                "message": "could not read a latitude and longitude from that text"}
    check = validate_pair(lat, lon)
    if not check["ok"]:
        return {"ok": False, "reason": "out_of_range",
                "problems": check["problems"],
                "message": check["problems"][0]["message"]}
    return {"ok": True, "lat": round(lat, 7), "lon": round(normalize_lon(lon), 7)}


def format_dd(value: float, decimals: int = 6) -> str:
    return f"{float(value):.{decimals}f}"


def format_dms(value: float, latitude: bool = True, decimals: int = 1) -> str:
    """`33°18′54.7″N` — always with a hemisphere, always with a real degree sign."""
    value = float(value)
    hemisphere = ("N" if value >= 0 else "S") if latitude else ("E" if value >= 0 else "W")
    total = abs(value)
    degrees = int(total)
    minutes_float = (total - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    if round(seconds, decimals) >= 60:
        seconds = 0.0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        degrees += 1
    return f"{degrees}°{minutes:02d}′{seconds:0{3 + decimals}.{decimals}f}″{hemisphere}"


def format_position(lat: float, lon: float, decimals: int = 6) -> dict:
    """Both notations, so the interface never has to choose for the reader."""
    return {
        "dd": f"{format_dd(lat, decimals)}, {format_dd(lon, decimals)}",
        "dms": f"{format_dms(lat, True)} {format_dms(lon, False)}",
        "lat_dd": float(f"{lat:.7f}"),
        "lon_dd": float(f"{lon:.7f}"),
        "lat_dms": format_dms(lat, True),
        "lon_dms": format_dms(lon, False),
    }


# --------------------------------------------------------------------------- #
# bounding boxes and the antimeridian
# --------------------------------------------------------------------------- #
def parse_bbox(text: str) -> tuple | None:
    """`min_lon,min_lat,max_lon,max_lat` (the order every map library uses)."""
    if not text:
        return None
    parts = [p for p in re.split(r"[,\s]+", str(text).strip()) if p]
    if len(parts) != 4:
        return None
    try:
        minx, miny, maxx, maxy = (float(p) for p in parts)
    except ValueError:
        return None
    if not (valid_lat(miny) and valid_lat(maxy)):
        return None
    return (minx, miny, maxx, maxy)


def clamp_bbox(bbox: tuple) -> tuple:
    minx, miny, maxx, maxy = bbox
    miny, maxy = max(-90.0, min(90.0, miny)), max(-90.0, min(90.0, maxy))
    if miny > maxy:
        miny, maxy = maxy, miny
    return (minx, miny, maxx, maxy)


def crosses_antimeridian(bbox: tuple) -> bool:
    return bbox[2] < bbox[0]


def split_bbox(bbox: tuple) -> list[tuple]:
    """A window that crosses 180° becomes two windows. This is *the* fix for
    markers vanishing when the user pans across the Pacific."""
    minx, miny, maxx, maxy = bbox
    if not crosses_antimeridian(bbox):
        return [(minx, miny, maxx, maxy)]
    return [(minx, miny, 180.0, maxy), (-180.0, miny, maxx, maxy)]


def bbox_of_points(points) -> tuple | None:
    pts = [(float(p[0]), float(p[1])) for p in points]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_contains(bbox: tuple, lat: float, lon: float) -> bool:
    for minx, miny, maxx, maxy in split_bbox(bbox):
        if minx <= lon <= maxx and miny <= lat <= maxy:
            return True
    return False


def expand_bbox(bbox: tuple, factor: float = 0.5) -> tuple:
    minx, miny, maxx, maxy = bbox
    dx, dy = (maxx - minx) * factor / 2, (maxy - miny) * factor / 2
    return (minx - dx, max(-90.0, miny - dy), maxx + dx, min(90.0, maxy + dy))


# --------------------------------------------------------------------------- #
# distance, bearing, area
# --------------------------------------------------------------------------- #
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres — the number a geographer would quote."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(normalize_lon(lon2 - lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in degrees from north (0–360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(normalize_lon(lon2 - lon1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple:
    """The point `distance_m` away along `bearing_deg` — used to draw halos and to
    place a point dropped from a bearing/distance, and by the tests."""
    d = distance_m / EARTH_RADIUS_M
    p1, l1 = math.radians(lat), math.radians(lon)
    t = math.radians(bearing_deg)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(t))
    l2 = l1 + math.atan2(math.sin(t) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return (math.degrees(p2), normalize_lon(math.degrees(l2)))


def path_length(points) -> float:
    """Length of a polyline in metres (sum of great-circle legs)."""
    total = 0.0
    pts = list(points)
    for (lat1, lon1), (lat2, lon2) in zip(pts, pts[1:], strict=False):
        total += haversine(lat1, lon1, lat2, lon2)
    return total


def polygon_area(points) -> float:
    """Spherical area in square metres (Chamberlain & Duquette, on a sphere).

    A planar shoelace would be wrong by percent-level for anything the size of a
    province, and this is a research registry: a reported area has to be defensible.
    """
    pts = [(float(p[1]), float(p[0])) for p in points]      # (lon, lat)
    if len(pts) < 3:
        return 0.0
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(pts, pts[1:], strict=False):
        total += math.radians(lon2 - lon1) * (
            2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2.0)


# --------------------------------------------------------------------------- #
# point in polygon
# --------------------------------------------------------------------------- #
def point_in_ring(lat: float, lon: float, ring) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        x_i, y_i = ring[i][0], ring[i][1]
        x_j, y_j = ring[j][0], ring[j][1]
        if ((y_i > lat) != (y_j > lat)) and \
                (lon < (x_j - x_i) * (lat - y_i) / ((y_j - y_i) or 1e-12) + x_i):
            inside = not inside
        j = i
    return inside


def point_in_geometry(lat: float, lon: float, geometry: dict) -> bool:
    """GeoJSON Point-in-Polygon(-MultiPolygon), holes respected, antimeridian-safe."""
    if not geometry:
        return False
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        polygons = [coords]
    elif gtype == "MultiPolygon":
        polygons = coords
    else:
        return False
    lon = normalize_lon(lon)
    for poly in polygons:
        if not poly:
            continue
        outer = [(normalize_lon(p[0]), p[1]) for p in poly[0]]
        test_lon = lon
        span = max(p[0] for p in outer) - min(p[0] for p in outer)
        if span > 180:                                  # ring crosses the antimeridian
            test_lon = lon % 360 if lon < 0 else lon
            outer = [(p[0] % 360, p[1]) for p in outer]
        if point_in_ring(lat, test_lon, outer) and not any(
                point_in_ring(lat, test_lon, [(normalize_lon(q[0]), q[1]) for q in hole])
                for hole in poly[1:]):
            return True
    return False


# --------------------------------------------------------------------------- #
# CRS
# --------------------------------------------------------------------------- #
def to_mercator(lat: float, lon: float) -> tuple:
    """WGS 84 → Web Mercator metres (the projection the map draws in)."""
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = EARTH_RADIUS_M * math.radians(normalize_lon(lon))
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return (x, y)


def from_mercator(x: float, y: float) -> tuple:
    lon = math.degrees(float(x) / EARTH_RADIUS_M)
    lat = math.degrees(2 * math.atan(math.exp(float(y) / EARTH_RADIUS_M)) - math.pi / 2)
    return (lat, normalize_lon(lon))


def crs_catalog() -> dict:
    return {"crs": CRS_CATALOG, "default": WGS84,
            "storage": WGS84, "display": WEB_MERCATOR}


def convert(lat: float, lon: float, target: str) -> dict:
    """Coordinates in another CRS, for export, citation and interoperability."""
    if target == WEB_MERCATOR:
        x, y = to_mercator(lat, lon)
        return {"crs": WEB_MERCATOR, "x": round(x, 3), "y": round(y, 3), "unit": "metre"}
    if target == CRS84:
        return {"crs": CRS84, "lon": round(float(lon), 7), "lat": round(float(lat), 7),
                "unit": "degree"}
    return {"crs": WGS84, "lat": round(float(lat), 7), "lon": round(float(lon), 7),
            "unit": "degree"}


# --------------------------------------------------------------------------- #
# clustering and proximity
# --------------------------------------------------------------------------- #
def cluster(points, cell: float) -> list[dict]:
    """Grid clustering in degrees.

    The map clusters in WebGL for what it draws; this is the server-side version used
    for the statistics panel and for the "N records here" count on a stacked marker,
    where a single SQL `GROUP BY` on a quantised cell is cheaper than shipping the
    points to the browser.
    """
    buckets: dict[tuple, dict] = {}
    for p in points:
        lat, lon = float(p["lat"]), float(p["lon"])
        key = (round(lat / cell), round(lon / cell))
        b = buckets.setdefault(key, {"count": 0, "lat_sum": 0.0, "lon_sum": 0.0,
                                     "types": {}, "ids": []})
        b["count"] += 1
        b["lat_sum"] += lat
        b["lon_sum"] += lon
        et = p.get("entity_type") or "place"
        b["types"][et] = b["types"].get(et, 0) + 1
        if len(b["ids"]) < 50:
            b["ids"].append({"entity_type": et, "id": p.get("id")})
    out = []
    for b in buckets.values():
        out.append({"count": b["count"],
                    "lat": round(b["lat_sum"] / b["count"], 6),
                    "lon": round(b["lon_sum"] / b["count"], 6),
                    "types": b["types"], "sample": b["ids"]})
    out.sort(key=lambda c: c["count"], reverse=True)
    return out


def nearest(points, lat: float, lon: float, limit: int = 5) -> list[dict]:
    scored = []
    for p in points:
        d = haversine(lat, lon, p["lat"], p["lon"])
        scored.append({**p, "distance_m": round(d, 1)})
    scored.sort(key=lambda p: p["distance_m"])
    return scored[:limit]


def format_distance(metres: float, units: str = "metric") -> str:
    """Human-scale distance, because "43722 m" is not an answer anyone reads."""
    if units == "imperial":
        feet = metres * 3.280839895
        if feet >= 5280:
            return f"{feet / 5280:,.2f} mi"
        return f"{feet:,.0f} ft"
    if metres >= 1000:
        return f"{metres / 1000:,.2f} km"
    return f"{metres:,.0f} m"


def format_area(square_metres: float, units: str = "metric") -> str:
    if units == "imperial":
        acres = square_metres / 4046.8564224
        if acres >= 640:
            return f"{acres / 640:,.2f} mi²"
        return f"{acres:,.2f} ac"
    if square_metres >= 1_000_000:
        return f"{square_metres / 1_000_000:,.2f} km²"
    if square_metres >= 10_000:
        return f"{square_metres / 10_000:,.2f} ha"
    return f"{square_metres:,.0f} m²"
