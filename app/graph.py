"""The graph as a service: what a node is, and how two nodes are connected.

The map view stopped being a picture of the schema the moment it became a place
to work.  Two questions it must answer *without leaving the diagram*:

  1. **What is this node?** — a dossier: identity, editorial state, verification,
     the facts that matter for its type, how much evidence stands behind it, and
     which records it touches.  Enough to decide what to do next, with a link to
     the full record for anyone who wants the whole form.

  2. **How are these two connected?** — the shortest chain of stored
     relationships between any two records.  "Is this person linked to that
     institution, and through whom?" is the question a relationship diagram
     exists to answer; a picture alone cannot, because the chain may be five
     hops away and invisible at the current focus.

Both are read-only.  Neither invents a connection: a path is a sequence of rows
in the `relationship` table, and every hop carries the relationship's own id, its
type in both languages, its direction, its verification and how many sources
speak to it.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from . import repo
from .schemas import ENTITIES, REF_TITLE_SQL

# Fields worth showing in a side panel, per entity: the ones a reader actually
# uses to recognise a record and judge whether to trust it.  A dossier is not a
# second form — it is the ten things that matter, in the order they are asked.
PANEL_FIELDS: dict[str, tuple[str, ...]] = {
    "person": ("name_original", "name_transliteration", "birth_date", "death_date",
               "nationality_id", "birthplace_text", "classification_id",
               "current_position", "public_activity"),
    "institution": ("institution_type_id", "subcategory_id", "founded_date",
                    "closed_date", "country_id", "city", "place_id", "governance_id"),
    "place": ("place_type_id", "country_id", "governorate_id", "city", "district_id",
              "latitude", "longitude", "geo_precision", "geocoding_method",
              "parent_place_id"),
    "event": ("event_type_id", "start_date", "end_date", "place_id"),
    "source": ("source_type_id", "publisher", "publication_date", "reliability_id",
               "url", "archive_reference"),
    "relationship": ("entity1_name", "entity2_name", "start_date", "end_date"),
}

STATE_FIELDS = ("record_status_id", "authentication_id", "documentation_id",
                "primary_source_id")


class NotFound(LookupError):
    """The node asked for does not exist (deleted rows count as absent)."""


def _title(conn, etype: str, rid: int) -> str | None:
    expr = REF_TITLE_SQL.get(etype, "code")
    table = ENTITIES[etype].table
    row = conn.execute(f"SELECT {expr} AS t FROM {table} WHERE id=?", (rid,)).fetchone()
    return row["t"] if row else None


def _label(conn, domain: str, value: Any) -> dict | None:
    """A vocabulary value as `{code, en, ar, color}`, or None when unset."""
    if value in (None, ""):
        return None
    row = None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        row = conn.execute(
            "SELECT code, label_en, label_ar, color FROM lookup WHERE id=?",
            (int(value),)).fetchone()
    if row is None and isinstance(value, str):
        row = conn.execute(
            "SELECT code, label_en, label_ar, color FROM lookup WHERE domain=? AND code=?",
            (domain, value)).fetchone()
    if row is None:
        return None
    return {"code": row["code"], "en": row["label_en"], "ar": row["label_ar"],
            "color": row["color"]}


def _ref(conn, etype: str, rid: Any) -> dict | None:
    """A foreign record as a clickable stub: `{type, id, code, label}`."""
    if rid in (None, ""):
        return None
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    table = ENTITIES[etype].table
    expr = REF_TITLE_SQL.get(etype, "code")
    row = conn.execute(
        f"SELECT id, code, {expr} AS label FROM {table} "
        f"WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
    if row is None:
        return None
    return {"type": etype, "id": row["id"], "code": row["code"],
            "label": row["label"] or row["code"], "href": f"#/entity/{etype}/{row['id']}"}


def _fact(conn, spec, key: str, value: Any) -> dict | None:
    """One row of the panel's fact list, already resolved for display."""
    field = spec.field(key)
    if field is None or value in (None, ""):
        return None
    out = {"key": key, "label_en": field.label_en, "label_ar": field.label_ar,
           "type": field.type, "value": value}
    if field.type in ("select", "fk") and field.domain:
        lab = _label(conn, field.domain, value)
        if lab:
            out["value"] = lab["en"]
            out["value_ar"] = lab["ar"]
            out["color"] = lab.get("color")
    if field.type == "fk" and field.ref:
        ref = _ref(conn, field.ref, value)
        if ref:
            out["ref"] = ref
            out["value"] = ref["label"]
    return out


def node_dossier(conn, etype: str, rid: int) -> dict:
    """Everything the side panel needs, in one round trip."""
    if etype not in ENTITIES:
        raise NotFound(f"Unknown entity type '{etype}'")
    spec = ENTITIES[etype]
    row = conn.execute(
        f"SELECT t.* FROM {spec.table} t WHERE t.id=? AND t.deleted_at IS NULL",
        (int(rid),)).fetchone()
    if row is None:
        raise NotFound(f"{spec.label_en} #{rid} not found")
    rec = dict(row)

    title_expr = REF_TITLE_SQL.get(etype, "code")
    title_row = conn.execute(
        f"SELECT {title_expr} AS t FROM {spec.table} WHERE id=?", (int(rid),)).fetchone()
    title = (title_row["t"] if title_row else None) or rec.get("code") or f"#{rid}"

    facts = [f for f in (_fact(conn, spec, k, rec.get(k)) for k in PANEL_FIELDS.get(etype, ()))
             if f]
    state = {k.replace("_id", ""): _label(conn, d, rec.get(k)) for k, d in
             (("record_status_id", "record_status"),
              ("authentication_id", "authentication_level"),
              ("documentation_id", "documentation_level"))}

    rel_count = conn.execute(
        """SELECT COUNT(*) c FROM relationship WHERE deleted_at IS NULL
             AND ((entity1_type=? AND entity1_id=?) OR (entity2_type=? AND entity2_id=?))""",
        (etype, rid, etype, rid)).fetchone()["c"]
    evidence = repo.evidence_summary(conn, etype, rid)

    degree: dict[str, int] = {}
    for r in conn.execute(
            """SELECT CASE WHEN entity1_type=? THEN entity2_type ELSE entity1_type END AS other,
                      COUNT(*) AS n
                 FROM relationship WHERE deleted_at IS NULL
                   AND ((entity1_type=? AND entity1_id=?) OR (entity2_type=? AND entity2_id=?))
                 GROUP BY other""", (etype, etype, rid, etype, rid)):
        degree[r["other"]] = int(r["n"])

    neighbours = []
    for r in conn.execute(
            """SELECT r.id, r.entity1_type, r.entity1_id, r.entity2_type, r.entity2_id,
                      r.direction, r.start_date, r.end_date,
                      COALESCE(l.label_en, 'Relationship') AS label_en,
                      COALESCE(l.label_ar, l.label_en, 'علاقة') AS label_ar,
                      COALESCE(la.code, 'unverified') AS auth_code,
                      COALESCE(la.label_en, 'Unverified') AS auth_en,
                      COALESCE(la.label_ar, la.label_en, 'غير موثق') AS auth_ar,
                      (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id) AS ev
                 FROM relationship r
                 LEFT JOIN lookup l ON l.id = r.relationship_type_id
                 LEFT JOIN lookup la ON la.id = r.authentication_id
                WHERE r.deleted_at IS NULL
                  AND ((r.entity1_type=? AND r.entity1_id=?) OR (r.entity2_type=? AND r.entity2_id=?))
                ORDER BY (r.end_date IS NULL) DESC, ev DESC, r.id DESC
                LIMIT 12""", (etype, rid, etype, rid)):
        outgoing = (r["entity1_type"], r["entity1_id"]) == (etype, rid)
        other_type = r["entity2_type"] if outgoing else r["entity1_type"]
        other_id = r["entity2_id"] if outgoing else r["entity1_id"]
        neighbours.append({
            "relationship_id": r["id"],
            "type": other_type, "record_id": other_id,
            "id": f"{other_type}:{other_id}",
            "label": _title(conn, other_type, other_id) or f"{other_type} #{other_id}",
            "rel_en": r["label_en"], "rel_ar": r["label_ar"],
            "outgoing": outgoing,
            "symmetric": (r["direction"] or "directed") == "symmetric",
            "verification": r["auth_code"], "verification_en": r["auth_en"],
            "verification_ar": r["auth_ar"],
            "start_date": r["start_date"], "end_date": r["end_date"],
            "ended": bool(r["end_date"]),
            "evidence_count": int(r["ev"] or 0),
            "href": f"#/entity/{other_type}/{other_id}",
        })

    return {
        "type": etype, "id": f"{etype}:{rid}", "record_id": int(rid),
        "code": rec.get("code"), "title": title,
        "label_en": spec.label_en, "label_ar": spec.label_ar,
        "href": f"#/entity/{etype}/{rid}",
        "image": rec.get("image_url"),
        "state": state,
        "facts": facts,
        "counts": {"relationships": int(rel_count), "by_type": degree,
                   "evidence": evidence},
        "neighbours": neighbours,
        "evidence": repo.get_evidence(conn, entity_type=etype, entity_id=int(rid)),
        "completeness": _completeness(conn, spec, rec),
    }


def _completeness(conn, spec, rec: dict) -> int | None:
    """Share of the record's key fields that are filled in — completeness, not truth."""
    keys = [k for k in PANEL_FIELDS.get(spec.key, ()) if not k.endswith("_id")] or []
    if not keys:
        return None
    filled = sum(1 for k in keys if rec.get(k) not in (None, ""))
    return round(100 * filled / len(keys))


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def shortest_path(conn, start: tuple[str, int], end: tuple[str, int],
                  max_depth: int = 5, max_expansions: int = 4000) -> dict:
    """The shortest chain of stored relationships between two records.

    Breadth-first, so the first chain found is a shortest one.  The search is
    bounded twice — by depth and by how many nodes it will expand — because a
    registry with fourteen thousand relationships can otherwise turn "are these
    connected?" into a full table scan.  When the budget runs out the answer is
    `exhausted: true`, never a silent "not connected".
    """
    for node in (start, end):
        if node[0] not in ENTITIES:
            raise NotFound(f"Unknown entity type '{node[0]}'")
        row = conn.execute(
            f"SELECT 1 FROM {ENTITIES[node[0]].table} WHERE id=? AND deleted_at IS NULL",
            (int(node[1]),)).fetchone()
        if row is None:
            raise NotFound(f"{node[0]} #{node[1]} not found")

    def neighbours(node: tuple[str, int]):
        t, i = node
        rows = conn.execute(
            """SELECT r.id, r.entity1_type, r.entity1_id, r.entity2_type, r.entity2_id,
                      r.direction, r.start_date, r.end_date,
                      COALESCE(l.label_en, 'Relationship') AS label_en,
                      COALESCE(l.label_ar, l.label_en, 'علاقة') AS label_ar,
                      COALESCE(la.code, 'unverified') AS auth_code,
                      (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id) AS ev
                 FROM relationship r
                 LEFT JOIN lookup l ON l.id = r.relationship_type_id
                 LEFT JOIN lookup la ON la.id = r.authentication_id
                WHERE r.deleted_at IS NULL
                  AND ((r.entity1_type=? AND r.entity1_id=?)
                       OR (r.entity2_type=? AND r.entity2_id=?))
                LIMIT 400""", (t, i, t, i)).fetchall()
        for r in rows:
            a = (r["entity1_type"], int(r["entity1_id"]))
            b = (r["entity2_type"], int(r["entity2_id"]))
            other = b if a == node else a
            yield other, {
                "id": r["id"], "label_en": r["label_en"], "label_ar": r["label_ar"],
                "verification": r["auth_code"], "direction": r["direction"],
                "start_date": r["start_date"], "end_date": r["end_date"],
                "evidence_count": int(r["ev"] or 0),
                "from": f"{a[0]}:{a[1]}", "to": f"{b[0]}:{b[1]}",
            }

    start = (start[0], int(start[1]))
    end = (end[0], int(end[1]))
    if start == end:
        return {"found": True, "length": 0, "nodes": [_node_stub(conn, *start)],
                "edges": [], "exhausted": False}

    prev: dict[tuple[str, int], tuple[tuple[str, int], dict]] = {}
    seen = {start}
    queue = deque([(start, 0)])
    expansions = 0
    exhausted = False
    found = False

    while queue and not found:
        node, depth = queue.popleft()
        if depth >= max_depth:
            exhausted = exhausted or bool(queue)
            continue
        for other, edge in neighbours(node):
            if other in seen:
                continue
            if expansions >= max_expansions:
                exhausted = True
                queue.clear()
                break
            expansions += 1
            seen.add(other)
            prev[other] = (node, edge)
            if other == end:
                found = True
                break
            queue.append((other, depth + 1))

    if not found:
        return {"found": False, "length": None, "nodes": [], "edges": [],
                "exhausted": exhausted, "searched": len(seen)}

    chain_edges = []
    cursor = end
    while cursor != start:
        parent, edge = prev[cursor]
        chain_edges.append(edge)
        cursor = parent
    chain_edges.reverse()
    node_ids = [start]
    for e in chain_edges:
        tail = e["to"] if e["from"] == f"{node_ids[-1][0]}:{node_ids[-1][1]}" else e["from"]
        t, i = tail.split(":", 1)
        node_ids.append((t, int(i)))

    return {
        "found": True, "length": len(chain_edges),
        "nodes": [_node_stub(conn, *n) for n in node_ids],
        "edges": chain_edges,
        "exhausted": False, "searched": len(seen),
    }


def _node_stub(conn, etype: str, rid: int) -> dict:
    spec = ENTITIES[etype]
    row = conn.execute(f"SELECT code FROM {spec.table} WHERE id=?", (rid,)).fetchone()
    return {"id": f"{etype}:{rid}", "type": etype, "record_id": int(rid),
            "code": row["code"] if row else None,
            "label": _title(conn, etype, rid) or f"{etype} #{rid}",
            "label_en": spec.label_en, "label_ar": spec.label_ar}
