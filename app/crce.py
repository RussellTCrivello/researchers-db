"""
SIRAJ · CRCE — Compass-Rose Coordinate Encoding
===============================================

One standard for every spatial reference in the registry, and one reserved
symbol for each kind of thing that can have one.

The rule this module exists to enforce is subtraction, not addition: a
coordinate is a *claim*, and a claim has a source, a precision, an owner and a
limit. So every dossier answers the same seven questions in the same order —
who is this, where is the point, in which reference system, in which direction
from what, how sure are we, what does it relate to, and what must the reader be
told before they believe it.

Design decisions that are deliberately not negotiable
-----------------------------------------------------
* **Nothing is invented.** A record with no georeferenced place has *no*
  coordinates; it gets an upright, bearing-less rose and a written reason. No
  centroid is filled in, no country is substituted for a place.
* **The original is preserved.** Coordinates are stored in WGS 84 and reported
  in WGS 84 first; conversions (CRS84, Web Mercator, DMS) are labelled as
  derived. Nothing is re-projected in place.
* **A person is not a pin.** A person's point is the *birthplace on file*, and
  the dossier says so in words; an institution's point is its *recorded seat*,
  which is not a claim about where it operates.
* **Direction needs two points.** A bearing is only computed when there is a
  real reference point (an enclosing place, or the registry centre, which is
  labelled conceptual). Otherwise the rose is drawn without a needle.
* **Symbols are exclusive.** One mark for people, one for organisations, one
  for places, one for relationships — and nothing else may borrow them. Events
  and sources are not covered by CRCE and keep their own generic marks.
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from app.geo import basemap, spatial
from app.schemas import ENTITIES

STANDARD: dict[str, Any] = {
    "id": "CRCE",
    "version": "1.0",
    "name_en": "Compass-Rose Coordinate Encoding",
    "name_ar": "ترميز الإحداثيات بالوردة الملاحية",
    "summary_en": ("Every spatial reference in the registry is described the same way, "
                   "and every kind of entity carries its own reserved compass-rose mark."),
    "summary_ar": ("كل مرجع مكاني في السجل يوصف بالطريقة نفسها، ولكل نوع من الكيانات "
                   "علامة وردة ملاحية محفوظة له وحده."),
    "box": 100,
    "storage_crs": "EPSG:4326",
    "reserved": ["person", "organization", "place", "relationship"],
    "uncovered": ["event", "source"],
}

# --------------------------------------------------------------------------- #
# the four reserved marks
# --------------------------------------------------------------------------- #
# Geometry is described once, here, as primitives in a 100 × 100 box centred on
# (50, 50). Two thin renderers interpret them — SVG for the interface, canvas for
# the map icons — so the marks that appear in a record, on the map and in a
# downloaded figure are provably the same drawing.
#
# primitive kinds:
#   ring   cx cy r width role [dash]
#   arc    cx cy r a1 a2 width role
#   line   x1 y1 x2 y2 width role
#   poly   points closed fill width role
#   dot    cx cy r role
#
# roles: ink (white), dim (light grey), accent (the bearing needle)

_WHITE, _GREY, _ACCENT = "ink", "dim", "accent"


def _ring(r: float, width: float, role: str = "ink") -> dict:
    return {"op": "ring", "cx": 50, "cy": 50, "r": r, "width": width, "role": role}


def _dot(r: float, role: str = "ink", cx: float = 50, cy: float = 50) -> dict:
    return {"op": "dot", "cx": cx, "cy": cy, "r": r, "role": role}


def _line(x1, y1, x2, y2, width=1.6, role="ink") -> dict:
    return {"op": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "width": width, "role": role}


def _polar(r: float, deg: float) -> tuple[float, float]:
    """Point at `r` from the centre, `deg` clockwise from north."""
    a = math.radians(deg)
    return 50 + r * math.sin(a), 50 - r * math.cos(a)


def _poly(points, closed=True, fill=False, width=1.5, role="ink") -> dict:
    return {"op": "poly", "points": [[round(x, 2), round(y, 2)] for x, y in points],
            "closed": closed, "fill": fill, "width": width, "role": role}


def _point(deg: float, outer: float, half: float, width: float = 1.1) -> list[dict]:
    """One compass point as a two-tone lozenge: lit on one side, shaded on the other.

    The lit/shaded split is what makes a rose read as a solid object rather than a
    starburst, and it survives being drawn at 16 px.
    """
    tip = _polar(outer, deg)
    left = _polar(outer * 0.30, deg - half)
    right = _polar(outer * 0.30, deg + half)
    centre = (50.0, 50.0)
    return [
        _poly([tip, right, centre], True, True, width, "ink"),
        _poly([tip, left, centre], True, True, width, "dim"),
    ]


def _ticks(radius: float, length: float, width: float, count: int = 16,
           role: str = "dim") -> list[dict]:
    out = []
    for i in range(count):
        deg = i * (360 / count)
        x1, y1 = _polar(radius, deg)
        x2, y2 = _polar(radius + length, deg)
        out.append(_line(round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2),
                         width, role))
    return out


def _letters(radius: float, size: float = 8.6) -> list[dict]:
    """N/E/S/W, drawn only when the mark is big enough to read them."""
    return [
        {"op": "text", "x": 50, "y": 50 - radius, "text": "N", "size": size,
         "anchor": "middle", "role": "ink", "min_size": 56},
        {"op": "text", "x": 50 + radius, "y": 50 + size * 0.36, "text": "E", "size": size,
         "anchor": "middle", "role": "dim", "min_size": 56},
        {"op": "text", "x": 50, "y": 50 + radius + size * 0.2, "text": "S", "size": size,
         "anchor": "middle", "role": "dim", "min_size": 56},
        {"op": "text", "x": 50 - radius, "y": 50 + size * 0.36, "text": "W", "size": size,
         "anchor": "middle", "role": "dim", "min_size": 56},
    ]


def _place_mark() -> dict:
    """PLACES — the navigational rose: eight-point star, ticked rings, solid fix.

    A place is the anchor of the whole system, so its mark is the full
    instrument: two graduated rings and a fixed centre. Nothing about it moves.
    """
    g: list[dict] = [
        _ring(46, 2.0, "ink"),
        _ring(38.5, 1.0, "dim"),
        *_ticks(40.0, 4.0, 1.4, 16),
    ]
    for i in range(4):                       # long cardinal points
        g += _point(i * 90, 30, 9)
    for i in range(4):                       # short intercardinal points
        g += _point(45 + i * 90, 19, 7)
    g += [_dot(4.6), *_letters(33.5, 8.6)]
    return {
        "id": "crce-place", "category": "place",
        "label_en": "Place", "label_ar": "مكان",
        "means_en": "A site with a georeferenced fix: the full instrument, graduated "
                    "and fixed.",
        "means_ar": "موقع له إسناد جغرافي: الآلة الكاملة، مدرّجة وثابتة.",
        "exclusive": True, "geometry": g,
    }


def _person_mark() -> dict:
    """PEOPLE — the waypoint rose: a broken ring, a hollow self, one long heading.

    A person is not a fixed monument. The ring is open to the north, the centre is
    an open circle rather than a solid fix, the north needle runs long and the
    south needle is cut short, and three graduation dots mark a track. This
    silhouette appears nowhere else in the registry.
    """
    g: list[dict] = [
        {"op": "arc", "cx": 50, "cy": 50, "r": 46, "a1": 26, "a2": 334,
         "width": 2.0, "role": "ink"},
        _line(*_polar(34, 0), *_polar(20, 0), 2.6, "ink"),          # long heading
        _line(*_polar(14, 180), *_polar(4, 180), 2.2, "dim"),        # cut-short tail
        _line(*_polar(22, 90), *_polar(9, 90), 1.8, "dim"),
        _line(*_polar(22, 270), *_polar(9, 270), 1.8, "dim"),
    ]
    for i in range(4):                                               # intercardinal ticks
        deg = 45 + i * 90
        g.append(_line(*_polar(20, deg), *_polar(9, deg), 1.4, "dim"))
    g += [
        {"op": "arc", "cx": 50, "cy": 50, "r": 30, "a1": 118, "a2": 242,
         "width": 1.4, "role": "dim"},
        {"op": "arc", "cx": 50, "cy": 50, "r": 26, "a1": 8, "a2": 44,
         "width": 1.2, "role": "dim"},
        _dot(2.6, "ink", 61.5, 38.5), _dot(2.6, "ink", 65.5, 45.5),
        _dot(2.6, "ink", 69.5, 52.5),                                # the track
        {"op": "ring", "cx": 50, "cy": 50, "r": 7.5, "width": 2.6, "role": "ink"},
        _dot(2.4),
    ]
    return {
        "id": "crce-person", "category": "person",
        "label_en": "Person", "label_ar": "شخص",
        "means_en": "A person: an open ring, a hollow self, one long heading, a track. "
                    "Not a fixed monument.",
        "means_ar": "شخص: حلقة مفتوحة، ذات مجوّفة، اتجاه طويل واحد، ومسار نقاط. ليس معلماً ثابتاً.",
        "exclusive": True, "geometry": g,
    }


def _organization_mark() -> dict:
    """ORGANISATIONS — the chambered rose: four chambers, a diamond core.

    A body is a structure, not a point: the cardinal rays stop short of four
    square chambers, the centre is a diamond (a seat, a plan) inside a second
    ring, and the diagonal rays are short, because authority rarely reaches the
    corners.
    """
    g: list[dict] = [_ring(46, 2.0, "ink"), _ring(40, 1.0, "dim")]
    for i in range(4):                                               # diagonal spokes
        deg = 45 + i * 90
        g.append(_line(*_polar(30, deg), *_polar(11, deg), 1.5, "dim"))
    for i in range(4):                                               # four chambers
        deg = i * 90
        cx_, cy_ = _polar(31.5, deg)
        a = math.radians(deg)
        half_w, half_h = 5.6, 7.2
        pts = [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]
        rot = [(cx_ + x * math.cos(a) - y * math.sin(a),
                cy_ + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
        g.append(_poly(rot, closed=True, fill=False, width=1.9, role="ink"))
    g += [
        _poly([(50, 35), (65, 50), (50, 65), (35, 50)], True, False, 2.2, "ink"),
        _poly([(50, 43), (57, 50), (50, 57), (43, 50)], True, True, 1.0, "ink"),
        _dot(1.9, "dim"),
        *_letters(34.5, 8.0),
    ]
    return {
        "id": "crce-organization", "category": "organization",
        "label_en": "Organization", "label_ar": "مؤسسة",
        "means_en": "An organisation: four chambers around a diamond seat — a structure, "
                    "not a point.",
        "means_ar": "مؤسسة: أربع غرف حول مقعد ماسي — بنية، لا نقطة.",
        "exclusive": True, "geometry": g,
    }


def _relationship_mark() -> dict:
    """RELATIONSHIPS — the transit rose: a ringed core, a double-diamond needle.

    A connection has direction and no fixed centre: the core is a ring, the
    principal needle is a double-ended diamond, the transverse axis is short, and
    a swept arc with an arrowhead carries the sense of travel.
    """
    g: list[dict] = [_ring(46, 1.8, "ink"), _ring(36, 1.0, "dim")]
    # double-ended principal needle
    g += [
        _poly([(50, 6), (55.5, 20), (50, 26), (44.5, 20)], True, True, 1.2, "ink"),
        _poly([(50, 94), (55.5, 80), (50, 74), (44.5, 80)], True, True, 1.2, "ink"),
        _line(50, 24, 50, 76, 1.8, "ink"),
        _line(26, 50, 74, 50, 1.6, "dim"),
        _poly([(74, 50), (66, 54), (66, 46)], True, True, 1.0, "ink"),
        _poly([(26, 50), (34, 54), (34, 46)], True, True, 1.0, "dim"),
        {"op": "arc", "cx": 50, "cy": 50, "r": 29, "a1": 34, "a2": 112,
         "width": 1.8, "role": "accent"},
        {"op": "ring", "cx": 50, "cy": 50, "r": 9, "width": 2.6, "role": "ink"},
        _dot(2.2, "ink"),
    ]
    for i in range(4):
        deg = 45 + i * 90
        x, y = _polar(32, deg)
        g.append(_dot(2.2, "dim", round(x, 2), round(y, 2)))
    return {
        "id": "crce-relationship", "category": "relationship",
        "label_en": "Relationship", "label_ar": "علاقة",
        "means_en": "A relationship: a ringed core and a double-ended needle — direction "
                    "without a fixed centre.",
        "means_ar": "علاقة: قلب حلقي وإبرة ذات طرفين — اتجاه بلا مركز ثابت.",
        "exclusive": True, "geometry": g,
    }


SYMBOLS: dict[str, dict] = {
    "person": _person_mark(),
    "organization": _organization_mark(),
    "place": _place_mark(),
    "relationship": _relationship_mark(),
}

# A record kind maps to the one category whose symbol it may use. Anything not
# listed here is *not covered* by CRCE and must not borrow one of the four.
CATEGORY_OF: dict[str, str] = {
    "person": "person",
    "institution": "organization",
    "place": "place",
    "relationship": "relationship",
}

# The role a coordinate plays, and the sentence that keeps it honest.
ROLE_TEXT: dict[str, tuple[str, str]] = {
    "site": ("own site", "الموقع الخاص"),
    "birthplace": ("birthplace on file", "مكان الميلاد المسجّل"),
    "seat": ("recorded seat", "المقر المسجّل"),
    "event_place": ("place of the event", "مكان الحدث"),
}


def catalogue() -> dict:
    """The standard as data: symbols, reserved meanings, and the rules."""
    return {
        "standard": STANDARD,
        "symbols": SYMBOLS,
        "categories": CATEGORY_OF,
        "roles": {k: {"en": v[0], "ar": v[1]} for k, v in ROLE_TEXT.items()},
        "rules": [
            {"code": "no_invention",
             "en": "Coordinates are never invented, inferred or interpolated. A record "
                   "without a georeferenced place has no fix, and says so.",
             "ar": "لا تُخترع الإحداثيات ولا تُستنبط ولا تُستكمل. السجل الذي لا مكان مُسنَد "
                   "له لا إحداثيات له، ويُعلن ذلك."},
            {"code": "preserve_original",
             "en": "The stored reference system is reported first and preserved; every "
                   "other notation is labelled as derived.",
             "ar": "يُذكر نظام الإسناد المخزّن أولاً ويُحفظ؛ وكل تدوين آخر يُوسم بأنه مشتق."},
            {"code": "person_not_pin",
             "en": "A person's point is a place on file concerning them, never a claim "
                   "about where the person is.",
             "ar": "نقطة الشخص مكان مسجّل يخصه، وليست حكماً على موقعه."},
            {"code": "seat_not_operations",
             "en": "An organisation's point is its recorded seat, not proof of where it "
                   "operates.",
             "ar": "نقطة المؤسسة مقرّها المسجّل، وليست دليلاً على أماكن عملها."},
            {"code": "direction_needs_two",
             "en": "A bearing is drawn only when a real reference point exists, and the "
                   "reference is named.",
             "ar": "لا يُرسم اتجاه إلا بوجود نقطة مرجعية حقيقية، وتُسمّى تلك المرجعية."},
            {"code": "exclusive_symbols",
             "en": "Each of the four marks belongs to one category only. Events and "
                   "sources are not covered by CRCE and use no rose.",
             "ar": "كل علامة من الأربع لنوع واحد فقط. الأحداث والمصادر خارج هذا الترميز "
                   "ولا تستخدم وردة."},
            {"code": "not_covered",
             "en": "A record kind the standard does not cover keeps its coordinates readable "
                   "and borrows no mark. The dossier says so, instead of leaving an empty "
                   "space where a rose would be.",
             "ar": "النوع غير المشمول بالمعيار تبقى إحداثياته مقروءة ولا يرتدي أي علامة. "
                   "يُعلن التقرير ذلك بدل ترك فراغ حيث تُرسم الوردة."},
        ],
    }


# --------------------------------------------------------------------------- #
# direction
# --------------------------------------------------------------------------- #
POINTS_16 = [
    ("N", "شمال"), ("NNE", "شمال-شمال شرق"), ("NE", "شمال شرق"), ("ENE", "شرق-شمال شرق"),
    ("E", "شرق"), ("ESE", "شرق-جنوب شرق"), ("SE", "جنوب شرق"), ("SSE", "جنوب-جنوب شرق"),
    ("S", "جنوب"), ("SSW", "جنوب-جنوب غرب"), ("SW", "جنوب غرب"), ("WSW", "غرب-جنوب غرب"),
    ("W", "غرب"), ("WNW", "غرب-شمال غرب"), ("NW", "شمال غرب"), ("NNW", "شمال-شمال غرب"),
]


def point_name(deg: float) -> dict:
    """A bearing as a 16-point compass name, in both languages."""
    d = float(deg) % 360.0
    idx = int((d + 11.25) // 22.5) % 16
    code, ar = POINTS_16[idx]
    return {"deg": round(d, 1), "code": code, "en": code, "ar": ar}


#: Below this the two points are the same point on the ground: a vector of zero
#: length has no azimuth, and printing "0° N" would invent one.
SAME_POINT_M = 1.0
SAME_POINT_EN = "same recorded point — no direction between them"
SAME_POINT_AR = "النقطة المسجّلة نفسها — لا اتجاه بينهما"


def _distance_text(metres: float, name_en: str, name_ar: str) -> tuple[str, str]:
    km = metres / 1000.0
    if km < 1:
        en = f"{round(metres)} m {name_en}"
        ar = f"{round(metres)} م {name_ar}"
    elif km < 10:
        en = f"{km:.1f} km {name_en}"
        ar = f"{km:.1f} كم {name_ar}"
    else:
        en = f"{round(km):,} km {name_en}"
        ar = f"{round(km):,} كم {name_ar}"
    return en, ar


# --------------------------------------------------------------------------- #
# anchors
# --------------------------------------------------------------------------- #
_PRECISION_STATUS = {
    "exact": ("verified", "مُتحقَّق"),
    "approximate": ("approximate", "تقريبي"),
    "centroid": ("approximate", "تقريبي"),
    "uncertain": ("uncertain", "غير مؤكد"),
}


def _precision(code: str | None) -> dict:
    status, status_ar = _PRECISION_STATUS.get(code or "", ("unrecorded", "غير مسجّل"))
    return {"code": code, "status": status, "status_ar": status_ar}


def _method_text(conn: sqlite3.Connection, value) -> str | None:
    """The geocoding method is stored as a lookup id. The dossier prints the label."""
    if value in (None, ""):
        return None
    row = None
    try:
        vid = int(value)
    except (TypeError, ValueError):
        vid = None
    if vid is not None:
        row = conn.execute(
            "SELECT label_en, label_ar FROM lookup WHERE id=? AND domain='geocoding_method'",
            (vid,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT label_en, label_ar FROM lookup WHERE domain='geocoding_method' AND code=?",
            (str(value),)).fetchone()
    if row is None:
        return str(value)
    return f"{row['label_en']} · {row['label_ar']}"


def _precision_of(conn: sqlite3.Connection, code_id) -> dict:
    """geo_precision is a lookup id; turn it into a status the reader can weigh."""
    if not code_id:
        return {"code": None, "status": "unrecorded", "status_ar": "غير مسجّل",
                "label_en": None, "label_ar": None}
    row = conn.execute("SELECT code, label_en, label_ar FROM lookup WHERE id = ?",
                       (code_id,)).fetchone()
    if not row:
        return {"code": None, "status": "unrecorded", "status_ar": "غير مسجّل",
                "label_en": None, "label_ar": None}
    status, status_ar = _PRECISION_STATUS.get(row["code"], ("recorded", "مسجّل"))
    return {"code": row["code"], "status": status, "status_ar": status_ar,
            "label_en": row["label_en"], "label_ar": row["label_ar"]}


def _anchor(conn: sqlite3.Connection, etype: str, rid: int) -> dict | None:
    """The point this record may claim, and the role that point plays."""
    if etype == "place":
        row = conn.execute(
            "SELECT latitude, longitude, geo_precision, geo_uncertainty_m, "
            "geocoding_method, geometry_source, parent_place_id, country_id, "
            "name_en, name_ar, code "
            "FROM place WHERE id = ? AND deleted_at IS NULL", (rid,)).fetchone()
        if not row or row["latitude"] is None:
            return None
        return {
            "lat": float(row["latitude"]), "lon": float(row["longitude"]),
            "role": "site", "place_id": rid, "place_code": row["code"],
            "place_en": row["name_en"], "place_ar": row["name_ar"],
            "precision": _precision_of(conn, row["geo_precision"]),
            "uncertainty_m": row["geo_uncertainty_m"],
            "method": _method_text(conn, row["geocoding_method"]),
            "source": row["geometry_source"], "inherited": False,
            "parent_place_id": row["parent_place_id"], "country_id": row["country_id"],
        }

    col, role = {
        "person": ("birthplace_id", "birthplace"),
        "institution": ("place_id", "seat"),
        "event": ("place_id", "event_place"),
    }.get(etype, (None, None))
    if not col:
        return None
    ref = conn.execute(f"SELECT {col} FROM {ENTITIES[etype].table} WHERE id = ? AND deleted_at IS NULL",
                       (rid,)).fetchone()
    if not ref or ref[0] is None:
        return None
    place = conn.execute(
        "SELECT id, code, name_en, name_ar, latitude, longitude, geo_precision, "
        "geo_uncertainty_m, geocoding_method, geometry_source, parent_place_id, country_id "
        "FROM place WHERE id = ? AND deleted_at IS NULL", (ref[0],)).fetchone()
    if not place or place["latitude"] is None:
        # the place exists; the point does not. Still a real reference, no fix.
        return None
    return {
        "lat": float(place["latitude"]), "lon": float(place["longitude"]),
        "role": role, "place_id": place["id"], "place_code": place["code"],
        "place_en": place["name_en"], "place_ar": place["name_ar"],
        "precision": _precision_of(conn, place["geo_precision"]),
        "uncertainty_m": place["geo_uncertainty_m"],
        "method": _method_text(conn, place["geocoding_method"]),
        "source": place["geometry_source"], "inherited": True,
        "parent_place_id": place["parent_place_id"], "country_id": place["country_id"],
    }


def _registry_centre(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT AVG(latitude) AS lat, AVG(longitude) AS lon, COUNT(*) AS n "
        "FROM place WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
        "AND deleted_at IS NULL").fetchone()
    if not row or not row["n"]:
        return None
    return {"lat": float(row["lat"]), "lon": float(row["lon"]), "n": row["n"]}


def _enclosing(conn: sqlite3.Connection, place_id: int | None, start_inclusive: bool) -> dict | None:
    """Walk up the place hierarchy for the first ancestor that has a point."""
    seen, current, depth = set(), place_id, 0
    while current and current not in seen and depth < 6:
        seen.add(current)
        row = conn.execute(
            "SELECT id, code, name_en, name_ar, latitude, longitude, parent_place_id, "
            "       (SELECT label_en FROM lookup l WHERE l.id = p.place_type_id) AS type_en "
            "FROM place p WHERE p.id = ? AND p.deleted_at IS NULL", (current,)).fetchone()
        if not row:
            return None
        if (start_inclusive or depth > 0) and row["latitude"] is not None:
            return {"place_id": row["id"], "code": row["code"],
                    "name_en": row["name_en"], "name_ar": row["name_ar"],
                    "type_en": row["type_en"],
                    "lat": float(row["latitude"]), "lon": float(row["longitude"])}
        current = row["parent_place_id"]
        depth += 1
    return None


def _reference_point(conn: sqlite3.Connection, anchor: dict | None,
                     etype: str, rid: int) -> dict | None:
    """What the bearing is measured *from* — named, and never invented.

    Preference order: the enclosing place of the point itself, then the registry
    centre, which is explicitly labelled conceptual because it is an artefact of
    this database rather than a feature of the world.
    """
    if etype == "place":
        enc = _enclosing(conn, anchor["place_id"] if anchor else rid, start_inclusive=False)
        if enc:
            return {**enc, "kind": "enclosing_place", "conceptual": False,
                    "label_en": f"enclosing place — {enc['name_en']}",
                    "label_ar": f"المكان المحيط — {enc['name_ar'] or enc['name_en']}"}
    elif anchor:
        enc = _enclosing(conn, anchor["place_id"], start_inclusive=False)
        if enc:
            return {**enc, "kind": "enclosing_place", "conceptual": False,
                    "label_en": f"enclosing place — {enc['name_en']}",
                    "label_ar": f"المكان المحيط — {enc['name_ar'] or enc['name_en']}"}
    centre = _registry_centre(conn)
    if centre:
        return {**centre, "kind": "registry_centre", "conceptual": True,
                "label_en": "centre of the registry's own points (a database artefact, "
                            "not a place in the world)",
                "label_ar": "مركز نقاط السجل نفسه (نتيجة قاعدة بيانات، لا موضع في العالم)"}
    return None


# --------------------------------------------------------------------------- #
# the dossier
# --------------------------------------------------------------------------- #
def _title(conn: sqlite3.Connection, etype: str, rid: int) -> dict | None:
    spec = ENTITIES.get(etype)
    if spec is None:
        return None
    cols = {f.key for f in spec.fields}
    # A record is not always catalogued in both languages: many carry only an
    # original-language name, some only a transliteration. Reading one column
    # and falling back to the code would print "PER-4336" where a person's
    # name exists, so each language falls through every name it can use and
    # the code is only the last resort — as it is on the record page.
    en_chain = [c for c in ("name_en", "title_en", "title", "name_original",
                            "name_transliteration", "name_ar", "title_ar") if c in cols]
    ar_chain = [c for c in ("name_ar", "title_ar", "name_original",
                            "name_transliteration", "name_en", "title_en", "title") if c in cols]
    if not en_chain:
        return None
    en = f"COALESCE({', '.join(en_chain)})"
    ar = f"COALESCE({', '.join(ar_chain or en_chain)})"
    row = conn.execute(
        f"SELECT id, code, {en} AS name_en, {ar} AS name_ar "
        f"FROM {spec.table} WHERE id = ? AND deleted_at IS NULL", (rid,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "code": row["code"],
            "name_en": row["name_en"] or row["code"],
            "name_ar": row["name_ar"] or row["name_en"] or row["code"]}


def _notes(etype: str, anchor: dict | None, ref: dict | None,
           precision: dict, category: str | None = None) -> list[dict]:
    notes: list[dict] = []
    if category is None:
        # An uncovered kind still gets the coordinate work — a date and a place
        # are read the same way — but it borrows no mark, and the reader is told
        # why the rose is missing instead of being left to wonder.
        notes.append({
            "code": "not_covered", "level": "info",
            "en": "This record kind is not covered by the standard, so it carries no "
                  "reserved mark. Its coordinates are still reported and preserved; it "
                  "simply may not wear a symbol that belongs to people, organizations "
                  "or places.",
            "ar": "هذا النوع من السجلات غير مشمول بالمعيار، فلا يحمل علامة محفوظة. تبقى "
                  "إحداثياته معروضة ومحفوظة، لكنه لا يجوز أن يرتدي علامة تخصّ الأشخاص أو "
                  "المؤسسات أو الأماكن."})
    if anchor is None:
        notes.append({
            "code": "no_fix", "level": "warn",
            "en": "No coordinates. No georeferenced place is recorded for this record, "
                  "so the rose is drawn upright and without a bearing — nothing has been "
                  "filled in to make it look located.",
            "ar": "لا إحداثيات. لا يوجد مكان مُسنَد جغرافياً لهذا السجل، لذلك تُرسم الوردة "
                  "معتدلة وبلا اتجاه — ولم يُستكمل شيء لتبدو محددة الموقع."})
        return notes
    if anchor["inherited"]:
        role_en, role_ar = ROLE_TEXT[anchor["role"]]
        notes.append({
            "code": "inherited", "level": "info",
            "en": f"The point is inherited from the {role_en} "
                  f"({anchor['place_en'] or anchor['place_code']}); it describes that "
                  f"place, not a position measured for this record.",
            "ar": f"النقطة مستعارة من {role_ar} ({anchor['place_ar'] or anchor['place_en']}); "
                  f"وهي تصف ذلك المكان، لا موضعاً قيس لهذا السجل."})
    if etype == "person":
        notes.append({
            "code": "person_not_pin", "level": "info",
            "en": "A person's location is not their identity. This is the birthplace on "
                  "file, and it says nothing about where the person lived, worked or is now.",
            "ar": "موقع الشخص ليس هويته. هذه نقطة مكان الميلاد المسجّل، ولا تقول شيئاً عن "
                  "مكان إقامته أو عمله أو وجوده الآن."})
    if etype == "institution":
        notes.append({
            "code": "seat_not_operations", "level": "info",
            "en": "This is the recorded seat. An organisation may act far from it, and a "
                  "seat is not evidence of where its work is done.",
            "ar": "هذا هو المقر المسجّل. قد تعمل المؤسسة بعيداً عنه، والمقر ليس دليلاً على "
                  "مواضع عملها."})
    if precision.get("status") in ("approximate", "uncertain", "unrecorded"):
        notes.append({
            "code": "precision", "level": "warn" if precision["status"] != "unrecorded" else "info",
            "en": f"The precision on file is “{precision.get('label_en') or 'unrecorded'}”. "
                  "Read the point as an area of doubt, not a street address.",
            "ar": f"الدقة المسجّلة هي «{precision.get('label_ar') or 'غير مسجّلة'}». "
                  "اقرأ النقطة كمساحة شك، لا كعنوان شارع."})
    if anchor.get("uncertainty_m"):
        notes.append({
            "code": "uncertainty", "level": "info",
            "en": f"Recorded radius of doubt: about {round(anchor['uncertainty_m'])} m.",
            "ar": f"نصف قطر الشك المسجّل: نحو {round(anchor['uncertainty_m'])} م."})
    if ref and ref.get("conceptual"):
        notes.append({
            "code": "conceptual_reference", "level": "info",
            "en": "The bearing is measured from the centre of the registry's own points. "
                  "That reference is conceptual: it exists in this database, not on the ground.",
            "ar": "الاتجاه مقيس من مركز نقاط السجل نفسه. هذه المرجعية تصورية: توجد في قاعدة "
                  "البيانات، لا على الأرض."})
    if not anchor.get("source"):
        notes.append({
            "code": "no_source", "level": "warn",
            "en": "No source is recorded for where this coordinate came from. The point is "
                  "usable, and its provenance is not yet documented.",
            "ar": "لا مصدر مسجّل لمصدر هذه الإحداثيات. النقطة قابلة للاستخدام، لكن مصدرها "
                  "غير موثّق بعد."})
    return notes


def _formats(lat: float, lon: float) -> dict:
    pos = spatial.format_position(lat, lon)
    return {
        "decimal_degrees": {"value": f"{lat:.6f}, {lon:.6f}", "axis": "lat,lon",
                            "unit": "degree", "crs": "EPSG:4326"},
        "dms": pos.get("dms"),
        "dm": pos.get("dm"),
        "crs84": spatial.convert(lat, lon, spatial.CRS84),
        "web_mercator": spatial.convert(lat, lon, spatial.WEB_MERCATOR),
        "geohash_note_en": "Coordinates are stored and reported in WGS 84; other notations "
                           "above are derived from it and marked as such.",
        "geohash_note_ar": "تُخزَّن الإحداثيات وتُذكر بنظام WGS 84؛ والتدوينات الأخرى أعلاه "
                           "مشتقة منه وموسومة بذلك.",
    }


def _relations(conn: sqlite3.Connection, etype: str, rid: int,
               anchor: dict | None, limit: int = 10) -> list[dict]:
    """Other anchored records this one is joined to, with the direction between them."""
    rows = conn.execute(
        "SELECT r.id, r.entity1_type AS t1, r.entity1_id AS i1, "
        "       r.entity2_type AS t2, r.entity2_id AS i2, "
        "       l.label_en, l.label_ar "
        "FROM relationship r LEFT JOIN lookup l ON l.id = r.relationship_type_id "
        "WHERE r.deleted_at IS NULL AND (r.entity1_type = ? AND r.entity1_id = ? "
        "   OR r.entity2_type = ? AND r.entity2_id = ?) "
        "ORDER BY r.id LIMIT 60", (etype, rid, etype, rid)).fetchall()
    out: list[dict] = []
    for row in rows:
        other_type = row["t2"] if (row["t1"] == etype and row["i1"] == rid) else row["t1"]
        other_id = row["i2"] if (row["t1"] == etype and row["i1"] == rid) else row["i1"]
        outgoing = row["t1"] == etype and row["i1"] == rid
        other_anchor = _anchor(conn, other_type, other_id) if other_type in CATEGORY_OF \
            or other_type in ("event", "source") else None
        title = _title(conn, other_type, other_id)
        item: dict[str, Any] = {
            "relationship_id": row["id"],
            "type": other_type, "id": other_id,
            "label_en": row["label_en"], "label_ar": row["label_ar"],
            "outgoing": outgoing,
            "name_en": title["name_en"] if title else None,
            "name_ar": title["name_ar"] if title else None,
            "code": title["code"] if title else None,
            "symbol": SYMBOLS[CATEGORY_OF[other_type]]["id"] if other_type in CATEGORY_OF else None,
            "located": bool(other_anchor),
        }
        if anchor and other_anchor:
            d = spatial.haversine(anchor["lat"], anchor["lon"],
                                  other_anchor["lat"], other_anchor["lon"])
            item["distance_m"] = round(d, 1)
            if d < SAME_POINT_M:
                item["same_point"] = True
                item["phrase_en"], item["phrase_ar"] = SAME_POINT_EN, SAME_POINT_AR
            else:
                b = spatial.bearing(anchor["lat"], anchor["lon"],
                                    other_anchor["lat"], other_anchor["lon"])
                name = point_name(b)
                item["bearing_deg"] = name["deg"]
                item["direction"] = name
                item["phrase_en"], item["phrase_ar"] = _distance_text(
                    d, name["en"], name["ar"])
        out.append(item)
        if len([o for o in out if o["located"]]) >= limit:
            break
    return out


def dossier(conn: sqlite3.Connection, etype: str, rid: int) -> dict:
    """The full CRCE record for one entity, in the published field order."""
    if etype not in ENTITIES:
        raise KeyError(etype)
    # a relationship has no name of its own: its title is the pair it joins, so
    # it is built from the row rather than looked up like a named record
    if etype == "relationship":
        return _relationship_dossier(conn, rid, _title(conn, etype, rid))

    title = _title(conn, etype, rid)
    if title is None:
        raise KeyError("record not found")
    category = CATEGORY_OF.get(etype)

    anchor = _anchor(conn, etype, rid)
    precision = anchor["precision"] if anchor else {"code": None, "status": "unrecorded",
                                                    "status_ar": "غير مسجّل",
                                                    "label_en": None, "label_ar": None}
    ref = _reference_point(conn, anchor, etype, rid) if anchor else None

    position = None
    direction = None
    if anchor:
        position = {
            "primary": {"lat": round(anchor["lat"], 7), "lon": round(anchor["lon"], 7),
                        "axis": "lat,lon", "unit": "degree", "crs": STANDARD["storage_crs"]},
            "formats": _formats(anchor["lat"], anchor["lon"]),
            "precision": precision,
            "uncertainty_m": anchor["uncertainty_m"],
            "method": anchor["method"],
            "source": anchor["source"],
            "role": {"code": anchor["role"], "en": ROLE_TEXT[anchor["role"]][0],
                     "ar": ROLE_TEXT[anchor["role"]][1]},
            "place": {"id": anchor["place_id"], "code": anchor["place_code"],
                      "name_en": anchor["place_en"], "name_ar": anchor["place_ar"],
                      "href": f"#/entity/place/{anchor['place_id']}"},
            "inherited": anchor["inherited"],
        }
        if ref:
            b = spatial.bearing(ref["lat"], ref["lon"], anchor["lat"], anchor["lon"])
            d = spatial.haversine(ref["lat"], ref["lon"], anchor["lat"], anchor["lon"])
            name = point_name(b)
            phrase_en, phrase_ar = _distance_text(d, name["en"], name["ar"])
            direction = {
                "bearing_deg": name["deg"], "code": name["code"],
                "en": name["en"], "ar": name["ar"],
                "distance_m": round(d, 1),
                "phrase_en": phrase_en, "phrase_ar": phrase_ar,
                "reference": {
                    "kind": ref["kind"], "conceptual": ref["conceptual"],
                    "label_en": ref["label_en"], "label_ar": ref["label_ar"],
                    "place_id": ref.get("place_id"), "name_en": ref.get("name_en"),
                    "name_ar": ref.get("name_ar"),
                    "lat": round(ref["lat"], 7), "lon": round(ref["lon"], 7),
                },
            }

    inside = None
    if anchor:
        country = basemap.country_at(anchor["lat"], anchor["lon"])
        inside = country and {
            "name_en": country.get("name_en"), "name_ar": country.get("name_ar"),
            "code": country.get("code"),
            "method_en": "point-in-polygon against the offline basemap",
            "method_ar": "احتواء النقطة في مضلع باستخدام خريطة الأساس المحلية"}

    parent = None
    if anchor and anchor.get("parent_place_id"):
        prow = conn.execute("SELECT id, code, name_en, name_ar FROM place WHERE id = ?",
                            (anchor["parent_place_id"],)).fetchone()
        if prow:
            parent = {"id": prow["id"], "code": prow["code"],
                      "name_en": prow["name_en"], "name_ar": prow["name_ar"],
                      "href": f"#/entity/place/{prow['id']}"}

    symbol = SYMBOLS[category] if category else None
    rose = {
        "symbol": symbol["id"] if symbol else None,
        "category": category,
        "state": "located" if anchor else "unlocated",
        "rotation_deg": direction["bearing_deg"] if direction else 0,
        "needle": bool(direction),
        "emphasis": "bearing" if direction else "none",
        "rings": 2 if symbol else 0,
        "ticks": 16 if category == "place" else 0,
        "letters": ["N", "E", "S", "W"] if category in ("place", "organization") else [],
        "exclusive": bool(symbol and symbol["exclusive"]),
    }

    return {
        "standard": {"id": STANDARD["id"], "version": STANDARD["version"]},
        "entity": {
            "name_en": title["name_en"], "name_ar": title["name_ar"],
            "code": title["code"], "id": title["id"], "type": etype,
            "category": category,
            "category_label_en": symbol["label_en"] if symbol else None,
            "category_label_ar": symbol["label_ar"] if symbol else None,
            "href": f"#/entity/{etype}/{title['id']}",
            "symbol": symbol["id"] if symbol else None,
            "covered_by_standard": category is not None,
        },
        "status": precision["status"] if anchor else "unlocated",
        "status_ar": precision["status_ar"] if anchor else "بلا إحداثيات",
        "coordinates": position,
        "orientation": direction,
        "relative": {"inside": inside, "parent": parent},
        "rose": rose,
        "relations": _relations(conn, etype, rid, anchor),
        "notes": _notes(etype, anchor, ref, precision, CATEGORY_OF.get(etype)),
    }


def _relationship_dossier(conn: sqlite3.Connection, rid: int, title: dict | None) -> dict:
    """A connection has two ends, so it has a direction — or it honestly does not."""
    row = conn.execute(
        "SELECT r.id, r.code, r.entity1_type AS t1, r.entity1_id AS i1, "
        "       r.entity2_type AS t2, r.entity2_id AS i2, r.direction, "
        "       l.label_en, l.label_ar "
        "FROM relationship r LEFT JOIN lookup l ON l.id = r.relationship_type_id "
        "WHERE r.id = ? AND r.deleted_at IS NULL", (rid,)).fetchone()
    if not row:
        raise KeyError("record not found")
    ends = []
    for t, i in ((row["t1"], row["i1"]), (row["t2"], row["i2"])):
        ttl = _title(conn, t, i)
        anchor = _anchor(conn, t, i)
        cat = CATEGORY_OF.get(t)
        ends.append({
            "type": t, "id": i,
            "name_en": ttl["name_en"] if ttl else None,
            "name_ar": ttl["name_ar"] if ttl else None,
            "code": ttl["code"] if ttl else None,
            "href": f"#/entity/{t}/{i}",
            "symbol": SYMBOLS[cat]["id"] if cat else None,
            "located": bool(anchor),
            "lat": round(anchor["lat"], 7) if anchor else None,
            "lon": round(anchor["lon"], 7) if anchor else None,
            "role": {"code": anchor["role"],
                     "en": ROLE_TEXT[anchor["role"]][0],
                     "ar": ROLE_TEXT[anchor["role"]][1]} if anchor else None,
        })
    bearing = distance = None
    coincident = False
    if ends[0]["located"] and ends[1]["located"]:
        distance = spatial.haversine(ends[0]["lat"], ends[0]["lon"],
                                     ends[1]["lat"], ends[1]["lon"])
        if distance < SAME_POINT_M:
            coincident = True
        else:
            b = spatial.bearing(ends[0]["lat"], ends[0]["lon"],
                                ends[1]["lat"], ends[1]["lon"])
            name = point_name(b)
            phrase_en, phrase_ar = _distance_text(distance, name["en"], name["ar"])
            bearing = {"bearing_deg": name["deg"], "code": name["code"], "en": name["en"],
                       "ar": name["ar"], "distance_m": round(distance, 1),
                       "phrase_en": phrase_en, "phrase_ar": phrase_ar}

    notes = [{
        "code": "connect_not_claim", "level": "info",
        "en": "A connection is not a finding of responsibility. This row records what the "
              "sources say about two records, and how well.",
        "ar": "العلاقة ليست حكماً بالمسؤولية. يسجّل هذا الصف ما تقوله المصادر عن سجلين، ومدى قوته."}]
    if coincident:
        notes.append({
            "code": "coincident_ends", "level": "info",
            "en": "Both ends resolve to the same recorded point (both inherit the same "
                  "anchor), so no bearing is drawn. A zero-length vector has no azimuth.",
            "ar": "ينتهي الطرفان إلى النقطة المسجّلة نفسها (كلاهما موروث من المرجع ذاته)، "
                  "فلا يُرسم اتجاه. المتجه الصفري بلا زاوية سمت."})
    if not (ends[0]["located"] and ends[1]["located"]):
        notes.append({
            "code": "direction_unknown", "level": "warn",
            "en": "At least one end has no fix, so no bearing is drawn. The rose is shown "
                  "without a needle rather than with an invented one.",
            "ar": "أحد الطرفين على الأقل بلا إحداثيات، فلا يُرسم اتجاه. تُعرض الوردة بلا إبرة "
                  "بدل اختراع اتجاه."})

    if not title:
        title = {
            "code": row["code"],
            "name_en": f"{row['label_en']}: {ends[0]['name_en']} → {ends[1]['name_en']}",
            "name_ar": f"{row['label_ar']}: {ends[0]['name_ar']} ← {ends[1]['name_ar']}",
        }
    return {
        "standard": {"id": STANDARD["id"], "version": STANDARD["version"]},
        "entity": {
            "name_en": title["name_en"], "name_ar": title["name_ar"],
            "code": title["code"], "id": rid, "type": "relationship",
            "category": "relationship", "category_label_en": SYMBOLS["relationship"]["label_en"],
            "category_label_ar": SYMBOLS["relationship"]["label_ar"],
            "href": f"#/entity/relationship/{rid}",
            "symbol": SYMBOLS["relationship"]["id"], "covered_by_standard": True,
            "relationship_type_en": row["label_en"], "relationship_type_ar": row["label_ar"],
            "declared_direction": row["direction"],
        },
        "status": ("same_point" if coincident else ("located" if bearing else "unlocated")),
        "status_ar": ("النقطة نفسها" if coincident
                      else ("محدّد" if bearing else "بلا إحداثيات")),
        "ends_coincident": coincident,
        "ends": ends,
        "coordinates": None,
        "orientation": bearing,
        "relative": {"from": ends[0], "to": ends[1]},
        "rose": {
            "symbol": SYMBOLS["relationship"]["id"], "category": "relationship",
            "state": ("same_point" if coincident
                      else ("located" if bearing else "unlocated")),
            "rotation_deg": bearing["bearing_deg"] if bearing else 0,
            "needle": bool(bearing), "emphasis": "bearing" if bearing else "none",
            "rings": 2, "ticks": 0, "letters": [], "exclusive": True,
        },
        "relations": [],
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# SVG, for export and for the documentation figures
# --------------------------------------------------------------------------- #
_ROLE_COLOUR = {"ink": "#ffffff", "dim": "#b9c0c7", "accent": "#e3c05a"}


def svg(category: str, size: int = 64, *, badge: bool = True,
        rotation: float = 0.0, background: str = "#33383d") -> str:
    """One mark as standalone SVG — used in exports, figures and documentation."""
    sym = SYMBOLS.get(category)
    if sym is None:
        raise KeyError(category)
    inner = size * 0.80
    pad = (size - inner) / 2
    parts: list[str] = []
    for p in sym["geometry"]:
        if p.get("min_size") and size < p["min_size"]:
            continue
        colour = _ROLE_COLOUR[p["role"]]
        if p["op"] == "ring":
            parts.append(f'<circle cx="{p["cx"]}" cy="{p["cy"]}" r="{p["r"]}" fill="none" '
                         f'stroke="{colour}" stroke-width="{p["width"]}"/>')
        elif p["op"] == "dot":
            parts.append(f'<circle cx="{p["cx"]}" cy="{p["cy"]}" r="{p["r"]}" fill="{colour}"/>')
        elif p["op"] == "line":
            parts.append(f'<line x1="{p["x1"]}" y1="{p["y1"]}" x2="{p["x2"]}" y2="{p["y2"]}" '
                         f'stroke="{colour}" stroke-width="{p["width"]}" stroke-linecap="round"/>')
        elif p["op"] == "arc":
            a1, a2 = math.radians(p["a1"]), math.radians(p["a2"])
            x1, y1 = p["cx"] + p["r"] * math.sin(a1), p["cy"] - p["r"] * math.cos(a1)
            x2, y2 = p["cx"] + p["r"] * math.sin(a2), p["cy"] - p["r"] * math.cos(a2)
            large = 1 if (p["a2"] - p["a1"]) % 360 > 180 else 0
            parts.append(f'<path d="M{x1:.2f} {y1:.2f} A{p["r"]} {p["r"]} 0 {large} 1 '
                         f'{x2:.2f} {y2:.2f}" fill="none" stroke="{colour}" '
                         f'stroke-width="{p["width"]}"/>')
        elif p["op"] == "poly":
            d = " ".join(f"{x},{y}" for x, y in p["points"])
            tag = "polygon" if p["closed"] else "polyline"
            fill = colour if p["fill"] else "none"
            parts.append(f'<{tag} points="{d}" fill="{fill}" stroke="{colour}" '
                         f'stroke-width="{p["width"]}" stroke-linejoin="round"/>')
        elif p["op"] == "text":
            parts.append(f'<text x="{p["x"]}" y="{p["y"]}" fill="{colour}" '
                         f'font-size="{p["size"]}" font-family="system-ui,sans-serif" '
                         f'text-anchor="{p.get("anchor", "middle")}">{p["text"]}</text>')
    body = (f'<g transform="translate({pad:.2f} {pad:.2f}) '
            f'translate({inner / 2:.2f} {inner / 2:.2f}) rotate({rotation:.1f}) '
            f'translate({-inner / 2:.2f} {-inner / 2:.2f}) scale({inner / 100:.4f})">'
            + "".join(parts) + "</g>")
    disc = (f'<circle cx="{size / 2}" cy="{size / 2}" r="{size / 2 - 0.5}" fill="{background}"/>'
            if badge else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}" role="img" aria-label="{sym["label_en"]}">'
            f'{disc}{body}</svg>')


def sprite(size: int = 64) -> str:
    """The four reserved marks as one SVG sheet, for documentation and download."""
    cells = []
    for i, cat in enumerate(("person", "organization", "place", "relationship")):
        cells.append(f'<g transform="translate({i * (size + 16)} 0)">{svg(cat, size)[svg(cat, size).index(">") + 1:-6]}</g>')
    width = 4 * (size + 16) - 16
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{size}" '
            f'viewBox="0 0 {width} {size}" role="img" '
            f'aria-label="CRCE reserved marks">{"".join(cells)}</svg>')
