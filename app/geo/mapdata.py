"""
SIRAJ · the registry, as geography.

Every marker on the map is a **registry record**, never a loose point. This module is
the only place that decides what a record's position *is*, and it does so by following
the schema's own references:

    place        → its own latitude/longitude
    person       → the coordinates of its birthplace place
    institution  → the coordinates of its place
    event        → the coordinates of its place

A record whose reference is missing, or whose place has no coordinates, has **no
position** — it is counted in `unlocated` and never drawn at a made-up place. That is
the difference between a map of data and a map of guesses.

Filtering is not re-implemented here: `repo.build_where` turns the interface's filter
payload into a WHERE clause for the entity's own table, and this module *composes* that
clause with the geographic join. So a filter means exactly what it means in the list
view, a saved view can be replayed on the map, and there is one filter engine in the
product rather than two that drift apart.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app import repo
from app.geo import basemap, spatial
from app.schemas import ENTITIES

# entity type → (from clause, position columns, "has a position" predicate, anchor label)
JOINS = {
    "place": (
        "{t} t",
        "t.latitude AS lat, t.longitude AS lon",
        "t.latitude IS NOT NULL AND t.longitude IS NOT NULL",
        None,
    ),
    "person": (
        "{t} t JOIN place gp ON gp.id = t.birthplace_id",
        "gp.latitude AS lat, gp.longitude AS lon",
        "gp.latitude IS NOT NULL AND gp.longitude IS NOT NULL",
        ("birthplace", "مكان الميلاد"),
    ),
    "institution": (
        "{t} t JOIN place gp ON gp.id = t.place_id",
        "gp.latitude AS lat, gp.longitude AS lon",
        "gp.latitude IS NOT NULL AND gp.longitude IS NOT NULL",
        ("location", "الموقع"),
    ),
    "event": (
        "{t} t JOIN place gp ON gp.id = t.place_id",
        "gp.latitude AS lat, gp.longitude AS lon",
        "gp.latitude IS NOT NULL AND gp.longitude IS NOT NULL",
        ("place", "المكان"),
    ),
}

MAPPED_LAYERS = tuple(JOINS)

# which column carries the human label for each layer
LABELS = {
    "place": ("t.name_en", "t.name_ar"),
    "person": ("t.name_en", "t.name_ar"),
    "institution": ("t.name_en", "t.name_ar"),
    "event": ("t.title_en", "t.title_ar"),
}


def layer_catalog(conn: sqlite3.Connection) -> list[dict]:
    """Every mappable layer, with how many records are located and how many are not.

    The numbers matter to the interface: a layer that shows 719 places out of 1 118 is
    telling the researcher something about the data, not about the map.
    """
    out = []
    for etype in MAPPED_LAYERS:
        spec = ENTITIES[etype]
        from_clause, _, has_pos, anchor = JOINS[etype]
        located = conn.execute(
            f"SELECT COUNT(*) c FROM {from_clause.format(t=spec.table)} "
            f"WHERE t.deleted_at IS NULL AND {has_pos}"
        ).fetchone()["c"]
        total = conn.execute(
            f"SELECT COUNT(*) c FROM {spec.table} t WHERE t.deleted_at IS NULL"
        ).fetchone()["c"]
        out.append({
            "entity_type": etype,
            "label_en": spec.label_en, "label_ar": spec.label_ar,
            "located": located, "total": total, "unlocated": total - located,
            "anchor": anchor[0] if anchor else "own position",
            "anchor_ar": anchor[1] if anchor else "الموقع الخاص",
            "icon": spec.icon or "map-pin",
        })
    return out


def _bbox_sql(bbox: tuple) -> tuple[str, list]:
    """SQL for a window, split at the antimeridian when it wraps."""
    boxes = spatial.split_bbox(spatial.clamp_bbox(bbox))
    if len(boxes) == 1:
        minx, miny, maxx, maxy = boxes[0]
        return "!lat BETWEEN ? AND ? AND !lon BETWEEN ? AND ?", [miny, maxy, minx, maxx]
    clauses, params = [], []
    for minx, miny, maxx, maxy in boxes:
        clauses.append("(!lat BETWEEN ? AND ? AND !lon BETWEEN ? AND ?)")
        params += [miny, maxy, minx, maxx]
    return "(" + " OR ".join(clauses) + ")", params


def _layer_payload(conn: sqlite3.Connection, spec, filters: dict) -> tuple[dict, list[str]]:
    """The filter payload for one layer.

    The map shows several kinds of record at once, and they do not share a schema.
    A typed query (``birth:1950..1980``) and a field clause are compiled with the
    same engine the list uses, then kept only where that layer actually has the
    field. A layer that lacks the field is left exactly as the layer chips set it:
    the new filters sit on top of the old ones, they do not replace them.

    Tags are the same idea. People and institutions carry them; places and events
    do not, so a tag must not wipe those layers.
    """
    src = dict(filters or {})
    query = src.pop("query", None)
    clauses: list[dict] = []
    for clause in list(src.get("where") or []):
        if not isinstance(clause, dict):
            continue
        scope = str(clause.get("entity") or clause.get("layer") or "").strip()
        if scope and scope != spec.key:
            continue
        clauses.append({k: v for k, v in clause.items()
                        if k not in ("entity", "layer", "derived")})
    src["where"] = clauses
    warnings: list[str] = []
    if isinstance(query, str) and query.strip():
        from app import querylang
        compiled = None
        try:
            compiled = querylang.parse_for(spec, query.strip())
        except querylang.QueryError as exc:
            warnings.append(str(exc))
        if compiled is not None:
            resolved, extra = querylang.resolve(conn, spec, compiled["payload"])
            for item in list(compiled["warnings"]) + list(extra):
                if item not in warnings:
                    warnings.append(item)
            extra_q = (resolved.get("q") or "").strip()
            if extra_q:
                src["q"] = (str(src.get("q") or "").strip() + " " + extra_q).strip()
            src["where"] = list(src["where"]) + list(resolved.get("where") or [])
            if resolved.get("status_ids"):
                if src.get("status_ids"):
                    both = [i for i in src["status_ids"] if i in set(resolved["status_ids"])]
                    src["status_ids"] = both or [-1]
                else:
                    src["status_ids"] = list(resolved["status_ids"])
            if resolved.get("tag_ids"):
                if src.get("tag_ids"):
                    both = [i for i in src["tag_ids"] if i in set(resolved["tag_ids"])]
                    src["tag_ids"] = both or [-1]
                else:
                    src["tag_ids"] = list(resolved["tag_ids"])
            if str(resolved.get("logic") or "") == "or" and not src.get("logic"):
                src["logic"] = "or"
    if src.get("tag_ids") and not getattr(spec, "tags", ()):
        src.pop("tag_ids", None)
    for stray in ("warnings", "auth", "doc", "relType", "tagIds"):
        src.pop(stray, None)
    return src, warnings


def _publish_warnings(layer_warnings: dict[str, list[str]]) -> list[str]:
    """Keep a warning that every requested layer reported, and any other once.

    ``birth:1950`` is unknown on a place and meaningful on a person. Reporting it
    four times would teach the reader that the filter failed. Reporting it only
    when *no* layer understood it tells them the truth.
    """
    if not layer_warnings:
        return []
    unknown_marks = ("unknown field", "Unknown or non-filterable field")
    buckets: dict[str, int] = {}
    others: list[str] = []
    for warns in layer_warnings.values():
        seen: set[str] = set()
        for item in warns:
            if item in seen:
                continue
            seen.add(item)
            if any(mark in item for mark in unknown_marks):
                buckets[item] = buckets.get(item, 0) + 1
            elif item not in others:
                others.append(item)
    published = list(others)
    width = len(layer_warnings)
    for item, count in buckets.items():
        if count >= width:
            published.append(item)
    return published


def features(conn: sqlite3.Connection, *, bbox: tuple | None = None, zoom: float = 0,
             layers: list[str] | None = None, filters: dict | None = None,
             limit: int = 4000, include_unlocated: bool = False) -> dict:
    """Points for the current window — bounded, filtered and counted.

    Never returns the whole corpus. `limit` is a **budget for the whole response**, not
    per layer: each layer is counted first, then gets a share of the budget in proportion
    to what it holds (at least one feature, so no layer silently disappears). The
    response then says how many records each layer left out, so the interface can say
    "showing 4 000 of 8 300 — zoom in" instead of implying completeness.
    """
    wanted = [name for name in (layers or MAPPED_LAYERS) if name in JOINS]
    filters = filters or {}
    limit = max(1, min(int(limit or 4000), 20000))
    points: list[dict] = []
    per_layer: dict[str, dict] = {}
    truncated = False
    bbox_clause, bbox_params = (None, [])
    if bbox:
        bbox_clause, bbox_params = _bbox_sql(bbox)

    # ---- pass 1: what is actually in this window, per layer -------------------
    counted: list[tuple[str, int, str, list]] = []
    warning_sets: dict[str, list[str]] = {}
    for etype in wanted:
        spec = ENTITIES[etype]
        layer_filters, layer_warnings = _layer_payload(conn, spec, filters)
        where, params, where_warnings = repo.build_where(
            spec, {**layer_filters, "entity": etype}, conn)
        warning_sets[etype] = layer_warnings + where_warnings
        _from_clause, _pos_cols, has_pos, _anchor = JOINS[etype]
        label_en, label_ar = LABELS[etype]
        clause = f"{where} AND {has_pos}"
        args = list(params)
        if bbox_clause:
            clause += " AND " + bbox_clause.replace("!lat", "gp.latitude" if etype != "place" else "t.latitude") \
                                       .replace("!lon", "gp.longitude" if etype != "place" else "t.longitude")
            args += bbox_params
        total = conn.execute(
            f"SELECT COUNT(*) c FROM {JOINS[etype][0].format(t=spec.table)} WHERE {clause}",
            args).fetchone()["c"]
        counted.append((etype, total, clause, args))

    # ---- the budget, divided by what each layer holds -------------------------
    grand = sum(total for _e, total, _c, _a in counted)
    quotas: dict[str, int] = {}
    if grand <= limit:
        quotas = {etype: total for etype, total, _c, _a in counted}
    else:
        remainders: list[tuple[float, str]] = []
        for etype, total, _c, _a in counted:
            exact = limit * total / grand
            share = max(1 if total else 0, int(exact))
            quotas[etype] = min(share, total)
            remainders.append((exact - int(exact), etype))
        # hand the rounding leftovers to the layers that were cut the most
        for _frac, etype in sorted(remainders, reverse=True):
            if sum(quotas.values()) >= limit:
                break
            total = next(t for e, t, _c, _a in counted if e == etype)
            if quotas[etype] < total:
                quotas[etype] += 1

    status = {r["id"]: r["code"] for r in conn.execute(
        "SELECT id, code FROM lookup WHERE domain='record_status'")}
    for etype, total, clause, args in counted:
        spec = ENTITIES[etype]
        from_clause, pos_cols, _has_pos, anchor = JOINS[etype]
        label_en, label_ar = LABELS[etype]
        rows = conn.execute(
            f"SELECT t.id, t.code, {label_en} AS label_en, {label_ar} AS label_ar, "
            f"t.record_status_id, {pos_cols} FROM {from_clause.format(t=spec.table)} "
            f"WHERE {clause} ORDER BY t.id LIMIT ?", args + [max(0, quotas.get(etype, 0))]).fetchall()
        for r in rows:
            points.append({
                "entity_type": etype, "id": r["id"], "code": r["code"],
                "label_en": r["label_en"] or r["label_ar"] or r["code"],
                "label_ar": r["label_ar"] or r["label_en"] or r["code"],
                "lat": round(float(r["lat"]), 7), "lon": round(float(r["lon"]), 7),
                "status": status.get(r["record_status_id"]),
                "anchor_en": anchor[0] if anchor else None,
                "anchor_ar": anchor[1] if anchor else None,
            })
        per_layer[etype] = {"total": total, "returned": len(rows),
                            "truncated": total > len(rows)}
        truncated = truncated or total > len(rows)

    return {
        "points": points,
        "count": len(points),
        "truncated": truncated,
        "limit": limit,
        "per_layer": per_layer,
        "warnings": _publish_warnings(warning_sets),
        "bbox": list(bbox) if bbox else None,
        "bounds": spatial.bbox_of_points([(p["lon"], p["lat"]) for p in points]),
    }


def _anchor_of(conn: sqlite3.Connection, etype: str, rec_id: int) -> dict | None:
    """The position of one record, and the place it was inherited from."""
    if etype not in JOINS:
        return None
    spec = ENTITIES[etype]
    from_clause, pos_cols, has_pos, anchor = JOINS[etype]
    # a place is its own anchor; everything else inherits one through `gp`
    pl = "t" if etype == "place" else "gp"
    row = conn.execute(
        f"SELECT t.id, t.code, {pos_cols}, {pl}.id AS place_id, {pl}.name_en AS place_en, "
        f"{pl}.name_ar AS place_ar, {pl}.geo_precision, {pl}.country_id "
        f"FROM {from_clause.format(t=spec.table)} "
        f"WHERE t.id = ? AND t.deleted_at IS NULL AND {has_pos}", (rec_id,)).fetchone()
    if not row:
        return None
    country = conn.execute("SELECT label_en, label_ar, code FROM lookup WHERE id=?",
                           (row["country_id"],)).fetchone() if row["country_id"] else None
    return {
        "lat": round(float(row["lat"]), 7), "lon": round(float(row["lon"]), 7),
        "place_id": row["place_id"], "place_en": row["place_en"], "place_ar": row["place_ar"],
        "precision": row["geo_precision"],
        "anchor_en": anchor[0] if anchor else "own position",
        "anchor_ar": anchor[1] if anchor else "الموقع الخاص",
        "country_en": country["label_en"] if country else None,
        "country_ar": country["label_ar"] if country else None,
    }


def detail(conn: sqlite3.Connection, etype: str, rec_id: int) -> dict:
    """Everything the inspector shows for one selected feature.

    Coordinates in both notations and in every CRS the registry reports, the place the
    position was inherited from, the country the point falls in (from the local
    basemap, not a geocoding service), and the record's own located relationships.
    """
    spec = ENTITIES.get(etype)
    if spec is None:
        raise KeyError(etype)
    record = repo.get_record(conn, spec, rec_id)
    if not record:
        raise LookupError("record not found")
    anchor = _anchor_of(conn, etype, rec_id)
    payload: dict[str, Any] = {
        "entity_type": etype, "id": rec_id, "code": record.get("code"),
        "label_en": record.get("name_en") or record.get("title_en") or record.get("code"),
        "label_ar": record.get("name_ar") or record.get("title_ar") or record.get("code"),
        "status": record.get("status") or record.get("record_status"),
        "located": anchor is not None,
        "position": None,
        "relationships": [],
        "sources": [],
    }
    if anchor is None:
        payload["reason"] = {"code": "no_coordinates",
                             "message_en": "This record has no coordinates: its place is not "
                                           "georeferenced, or it has no place at all.",
                             "message_ar": "هذا السجل بلا إحداثيات: مكانه غير مُسنَد جغرافياً، "
                                           "أو لا يوجد مكان مرتبط به."}
        return payload
    payload["position"] = {
        **anchor,
        "formatted": spatial.format_position(anchor["lat"], anchor["lon"]),
        "crs": {code: spatial.convert(anchor["lat"], anchor["lon"], code)
                for code in spatial.CRS_CATALOG},
        "country_polygon": basemap.country_at(anchor["lat"], anchor["lon"]),
    }
    payload["relationships"] = _located_relationships(conn, etype, rec_id)
    # evidence, not a bibliography: each row says what the source claims about this
    # record and whether it supports or contradicts it
    from .. import repo as _repo
    payload["evidence"] = _repo.get_evidence(conn, entity_type=etype, entity_id=rec_id)[:8]
    payload["evidence_summary"] = _repo.evidence_summary(conn, etype, rec_id)
    payload["sources"] = [{"id": e["source_id"], "code": e.get("source_code"),
                           "title": e.get("title"), "title_ar": e.get("title_ar"),
                           "support_type": e.get("support_type")}
                          for e in payload["evidence"]]
    return payload


def _located_relationships(conn: sqlite3.Connection, etype: str, rec_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT r.id, r.code, l.label_en, l.label_ar, r.entity1_type, r.entity1_id, "
        "r.entity2_type, r.entity2_id FROM relationship r "
        "LEFT JOIN lookup l ON l.id = r.relationship_type_id "
        "WHERE r.deleted_at IS NULL AND ((r.entity1_type=? AND r.entity1_id=?) "
        "OR (r.entity2_type=? AND r.entity2_id=?)) LIMIT 40",
        (etype, rec_id, etype, rec_id)).fetchall()
    here = _anchor_of(conn, etype, rec_id)
    out = []
    for r in rows:
        other_type = r["entity2_type"] if r["entity1_type"] == etype and r["entity1_id"] == rec_id \
            else r["entity1_type"]
        other_id = r["entity2_id"] if r["entity1_type"] == etype and r["entity1_id"] == rec_id \
            else r["entity1_id"]
        if other_type not in JOINS:
            continue
        anchor = _anchor_of(conn, other_type, other_id)
        if not anchor:
            continue
        other = ENTITIES[other_type]
        row = conn.execute(f"SELECT code, {'title_en' if other_type == 'event' else 'name_en'} e, "
                           f"{'title_ar' if other_type == 'event' else 'name_ar'} a "
                           f"FROM {other.table} WHERE id=?", (other_id,)).fetchone()
        out.append({
            "relationship_id": r["id"], "code": r["code"],
            "type_en": r["label_en"], "type_ar": r["label_ar"],
            "entity_type": other_type, "id": other_id,
            "label_en": row["e"], "label_ar": row["a"],
            "lat": anchor["lat"], "lon": anchor["lon"],
            "distance_m": round(spatial.haversine(
                here["lat"], here["lon"], anchor["lat"], anchor["lon"]), 1) if here else None,
        })
    return out


# --------------------------------------------------------------------------- #
# statistical groups ("N records at this place")
# --------------------------------------------------------------------------- #
def groups(conn: sqlite3.Connection, *, bbox: tuple | None = None, zoom: float = 0,
           layers: list[str] | None = None, filters: dict | None = None,
           limit: int = 50) -> dict:
    """Aggregate by place: the "what is here" panel, and the naive-marker fix."""
    wanted = [name for name in (layers or MAPPED_LAYERS) if name in JOINS]
    filters = filters or {}
    rows: dict[int, dict] = {}
    bbox_clause, bbox_params = (None, [])
    if bbox:
        bbox_clause, bbox_params = _bbox_sql(bbox)
    warning_sets: dict[str, list[str]] = {}
    for etype in wanted:
        spec = ENTITIES[etype]
        layer_filters, layer_warnings = _layer_payload(conn, spec, filters)
        where, params, where_warnings = repo.build_where(
            spec, {**layer_filters, "entity": etype}, conn)
        warning_sets[etype] = layer_warnings + where_warnings
        from_clause, pos_cols, has_pos, _ = JOINS[etype]
        clause = f"{where} AND {has_pos}"
        args = list(params)
        if bbox_clause:
            prefix = "t." if etype == "place" else "gp."
            clause += " AND " + bbox_clause.replace("!lat", prefix + "latitude") \
                                            .replace("!lon", prefix + "longitude")
            args += bbox_params
        pl = "t" if etype == "place" else "gp"
        for r in conn.execute(
                f"SELECT {pl}.id AS pid, {pl}.name_en, {pl}.name_ar, {pos_cols}, COUNT(*) c "
                f"FROM {from_clause.format(t=spec.table)} "
                f"WHERE {clause} GROUP BY {pl}.id", args):
            g = rows.setdefault(r["pid"], {
                "place_id": r["pid"], "label_en": r["name_en"], "label_ar": r["name_ar"],
                "lat": round(float(r["lat"]), 7), "lon": round(float(r["lon"]), 7),
                "count": 0, "by_layer": {},
            })
            g["count"] += r["c"]
            g["by_layer"][etype] = g["by_layer"].get(etype, 0) + r["c"]
    ordered = sorted(rows.values(), key=lambda g: g["count"], reverse=True)[:limit]
    return {"groups": ordered, "count": len(ordered),
            "total_records": sum(g["count"] for g in rows.values()),
            "distinct_places": len(rows),
            "warnings": _publish_warnings(warning_sets)}


# --------------------------------------------------------------------------- #
# vector overlays derived from the registry itself
# --------------------------------------------------------------------------- #
def overlays(conn: sqlite3.Connection, *, layers: list[str] | None = None,
             limit: int = 3000) -> dict:
    """Relationship arcs and place-hierarchy paths, as GeoJSON.

    Both are computed from the registry: an arc exists because a `relationship` row
    exists, and a path exists because a place names its parent. Nothing is decorative.
    """
    wanted = layers or ["relationships", "place_hierarchy"]
    out: dict[str, dict] = {}

    if "relationships" in wanted:
        rows = conn.execute(
            "SELECT r.id, r.code, r.entity1_type, r.entity1_id, r.entity2_type, r.entity2_id, "
            "l.label_en, l.label_ar FROM relationship r "
            "LEFT JOIN lookup l ON l.id = r.relationship_type_id "
            "WHERE r.deleted_at IS NULL LIMIT ?", (limit,)).fetchall()
        feats = []
        for r in rows:
            a = _anchor_of(conn, r["entity1_type"], r["entity1_id"])
            b = _anchor_of(conn, r["entity2_type"], r["entity2_id"])
            if not a or not b:
                continue
            feats.append({
                "type": "Feature", "id": r["id"],
                "properties": {
                    "kind": "relationship", "relationship_id": r["id"], "code": r["code"],
                    "type_en": r["label_en"], "type_ar": r["label_ar"],
                    "from": f"{r['entity1_type']}:{r['entity1_id']}",
                    "to": f"{r['entity2_type']}:{r['entity2_id']}",
                    "distance_m": round(spatial.haversine(a["lat"], a["lon"],
                                                          b["lat"], b["lon"]), 1),
                },
                "geometry": {"type": "LineString",
                             "coordinates": [[a["lon"], a["lat"]], [b["lon"], b["lat"]]]},
            })
        out["relationships"] = {"type": "FeatureCollection", "features": feats,
                                "count": len(feats)}

    if "place_hierarchy" in wanted:
        rows = conn.execute(
            "SELECT c.id, c.code, c.name_en, c.name_ar, p.id pid, p.name_en pname_en, "
            "p.name_ar pname_ar FROM place c JOIN place p ON p.id = c.parent_place_id "
            "WHERE c.deleted_at IS NULL AND p.deleted_at IS NULL "
            "AND c.latitude IS NOT NULL AND p.latitude IS NOT NULL LIMIT ?", (limit,)).fetchall()
        feats = []
        for r in rows:
            parent = _anchor_of(conn, "place", r["pid"])
            child = _anchor_of(conn, "place", r["id"])
            if not parent or not child:
                continue
            feats.append({
                "type": "Feature",
                "properties": {"kind": "hierarchy", "child": r["code"],
                               "parent_id": r["pid"], "child_en": r["name_en"],
                               "child_ar": r["name_ar"], "parent_en": r["pname_en"],
                               "parent_ar": r["pname_ar"]},
                "geometry": {"type": "LineString",
                             "coordinates": [[parent["lon"], parent["lat"]],
                                             [child["lon"], child["lat"]]]},
            })
        out["place_hierarchy"] = {"type": "FeatureCollection", "features": feats,
                                  "count": len(feats)}
    return out


# --------------------------------------------------------------------------- #
# spatial queries
# --------------------------------------------------------------------------- #
def query(conn: sqlite3.Connection, *, mode: str, lat: float | None = None,
          lon: float | None = None, radius_m: float = 25000.0,
          bbox: tuple | None = None, polygon: list | None = None,
          layers: list[str] | None = None, filters: dict | None = None,
          limit: int = 500) -> dict:
    """Which records are *here* — inside a window, a radius, or a drawn polygon.

    The heavy predicates (bbox) run in SQL; the exact ones (radius, polygon) run in
    Python over the candidates, which is both correct and fast enough for a bounded
    candidate set.
    """
    data = features(conn, bbox=bbox, layers=layers, filters=filters, limit=limit)
    points = data["points"]
    if mode == "radius":
        if lat is None or lon is None:
            raise ValueError("radius queries need a centre")
        for p in points:
            p["distance_m"] = round(spatial.haversine(lat, lon, p["lat"], p["lon"]), 1)
        points = [p for p in points if p["distance_m"] <= radius_m]
        points.sort(key=lambda p: p["distance_m"])
    elif mode == "polygon":
        if not polygon or len(polygon) < 3:
            raise ValueError("a polygon query needs at least three points")
        ring = [(float(c[0]), float(c[1])) for c in polygon]
        points = [p for p in points if spatial.point_in_ring(p["lat"], p["lon"], ring)]
    return {
        "mode": mode, "count": len(points),
        "records": points[:limit],
        "truncated": data["truncated"] or len(points) > limit,
        "centre": {"lat": lat, "lon": lon} if lat is not None else None,
        "radius_m": radius_m if mode == "radius" else None,
        "area_m2": round(spatial.polygon_area(polygon), 1) if mode == "polygon" else None,
    }


# --------------------------------------------------------------------------- #
# gazetteer search: names from the registry, countries from the basemap
# --------------------------------------------------------------------------- #
def search(conn: sqlite3.Connection, text: str, limit: int = 12) -> dict:
    """One search box for everything on the map.

    A coordinate is a position. A name is a registry record (a place first, because a
    place is the thing that *has* a position) or a country from the basemap. Neither
    result is invented: every hit carries the record it came from.
    """
    text = (text or "").strip()
    if not text:
        return {"query": text, "position": None, "results": [], "count": 0}
    parsed = spatial.parse_pair(text)
    if parsed["ok"]:
        return {"query": text, "position": parsed, "results": [], "count": 0,
                "position_label": spatial.format_position(parsed["lat"], parsed["lon"])}
    like = f"%{text}%"
    out = []
    for etype in MAPPED_LAYERS:
        spec = ENTITIES[etype]
        # the label columns are qualified with the record alias: the place join in
        # `from_clause` carries its own name_en/name_ar, so a bare column is ambiguous
        label_en, label_ar = LABELS[etype]
        from_clause, pos_cols, has_pos, _ = JOINS[etype]
        for r in conn.execute(
                f"SELECT t.id, t.code, {label_en} le, {label_ar} la, {pos_cols} "
                f"FROM {from_clause.format(t=spec.table)} "
                f"WHERE t.deleted_at IS NULL AND {has_pos} "
                f"AND (t.code LIKE ? OR {label_en} LIKE ? OR {label_ar} LIKE ?) "
                f"ORDER BY t.id LIMIT ?", (like, like, like, limit)):
            out.append({"kind": "record", "entity_type": etype, "id": r["id"],
                        "code": r["code"], "label_en": r["le"], "label_ar": r["la"],
                        "lat": round(float(r["lat"]), 7), "lon": round(float(r["lon"]), 7),
                        "layer_en": spec.label_en, "layer_ar": spec.label_ar})
        if len(out) >= limit:
            break
    if len(out) < limit and basemap.available():
        hits = basemap.features("countries", zoom=2, limit=4000)
        for feat in hits["collection"]["features"]:
            props = feat["properties"]
            if text.lower() in (props.get("name_en", "") + " " + props.get("name_ar", "")).lower() \
                    or text.upper() == props.get("iso_a2", ""):
                ring = feat["geometry"]["coordinates"][0][0]
                out.append({"kind": "country", "iso_a2": props.get("iso_a2"),
                            "label_en": props.get("name_en"), "label_ar": props.get("name_ar"),
                            "lat": round(sum(p[1] for p in ring) / len(ring), 5),
                            "lon": round(sum(p[0] for p in ring) / len(ring), 5),
                            "layer_en": "Country", "layer_ar": "دولة"})
        out = out[:limit]
    return {"query": text, "position": None, "results": out[:limit], "count": len(out[:limit])}


def reverse(conn: sqlite3.Connection, lat: float, lon: float) -> dict:
    """What is at this point? Containing country, nearest registry places, nearest records."""
    check = spatial.validate_pair(lat, lon)
    if not check["ok"]:
        raise ValueError(check["problems"][0]["message"])
    country = basemap.country_at(lat, lon)
    gazetteer = basemap.nearest_place(lat, lon)
    rows = conn.execute(
        "SELECT id, code, name_en, name_ar, latitude, longitude, geo_precision, "
        "country_id, region, city, district, place_type_id "
        "FROM place WHERE deleted_at IS NULL AND latitude IS NOT NULL LIMIT 4000").fetchall()
    nearby = spatial.nearest(
        [{"entity_type": "place", "id": r["id"], "code": r["code"],
          "label_en": r["name_en"], "label_ar": r["name_ar"],
          "lat": r["latitude"], "lon": r["longitude"], "precision": r["geo_precision"],
          "country_id": r["country_id"], "region": r["region"], "city": r["city"],
          "district": r["district"], "place_type_id": r["place_type_id"]}
         for r in rows], lat, lon, limit=5)
    country_lookup = None
    iso = (country or {}).get("iso_a2")
    if iso:
        row = conn.execute(
            "SELECT id, code, label_en, label_ar FROM lookup "
            "WHERE domain='country' AND code=? AND is_active=1",
            (iso,)).fetchone()
        if row:
            country_lookup = dict(row)
    return {"ok": True, "position": {"lat": lat, "lon": lon,
                                     "formatted": spatial.format_position(lat, lon)},
            "country": country, "country_lookup": country_lookup,
            "gazetteer": gazetteer, "nearby_places": nearby,
            "distance_to_nearest_m": nearby[0]["distance_m"] if nearby else None}
