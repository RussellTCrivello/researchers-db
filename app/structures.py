"""The registry's own trees, as data.

Every screen that draws a structure needs the same three things: a *tree*, a
number on each node, and a name in both languages. This module produces exactly
that, from the registry itself, with no chart library and no hand-written query
per view:

    people        nationality → classification → record status
    institutions  type → country → governance
    places        country → place type → precision
    relationships relationship type → declared direction → verification
    sources       source type → reliability → record status
    events        event type → country of the place → documentation
    evidence      support type → verification → review flag

Each source is one row in ``SOURCES``: an entity, a chain of dimension fields
that already exist in ``app/schemas.py``, and the two labels. The dimension
resolution below understands three kinds of field — a vocabulary reference
(``select`` fields store a lookup id), a foreign key to another record
(``fk``), and a plain flag (``bool``) — so adding a source is adding a row, not
writing SQL.

Two rules keep the numbers honest:

* **Every child count is computed, never inferred.** A node's value is the
  number of records that reach it under its ancestors, taken from the same
  filtered query that produced the branch.
* **A tail is folded, not dropped.** With more than ``MAX_CHILDREN`` branches a
  node keeps the most populated ones and folds the rest into one node that
  carries their exact sum and their count, so the picture can always be added
  back up to the registry's own total.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from .schemas import ENTITIES

#: How many branches a node shows before the tail is folded into one aggregate.
MAX_CHILDREN = 24
#: The deepest chain any source may declare; the kernel draws 3 levels well.
MAX_DEPTH = 4
#: How many individual records a deepest branch may list before the rest is folded.
MAX_LEAVES = 48

NOT_RECORDED = ("not recorded", "غير مسجّل")
NOT_RECORDED_KEY = "__none__"

SOURCES: list[dict[str, Any]] = [
    {
        "id": "people",
        "entity": "person",
        "label_en": "People",
        "label_ar": "الأشخاص",
        "note_en": "Where the registry's people are anchored: nationality, then what "
                   "they are classified as, then how far the record has been taken. "
                   "With leaves on, each deepest branch lists the people themselves.",
        "note_ar": "كيف يتوزّع الأشخاص: الجنسية، ثم التصنيف، ثم حالة السجل. "
                   "ومع إظهار السجلات يظهر كل شخص في أعمق فرع.",
        "chain": ["nationality_id", "classification_id", "record_status_id"],
    },
    {
        "id": "institutions",
        "entity": "institution",
        "label_en": "Institutions",
        "label_ar": "المؤسسات",
        "note_en": "Type, then the country of the recorded seat, then the governance "
                   "system on file. With leaves on, each deepest branch lists the "
                   "institutions themselves.",
        "note_ar": "النوع، ثم بلد المقر المسجّل، ثم نظام الحكامة المسجّل. "
                   "ومع إظهار السجلات تظهر كل مؤسسة في أعمق فرع.",
        "chain": ["institution_type_id", "country_id", "governance_id"],
    },
    {
        "id": "places",
        "entity": "place",
        "label_en": "Places",
        "label_ar": "الأماكن",
        "note_en": "Country, then place type, then the precision of the point on file — "
                   "the same precision the compass-rose standard reports.",
        "note_ar": "البلد، ثم نوع المكان، ثم دقة النقطة المسجّلة — الدقة نفسها التي "
                   "يعرضها معيار الوردة الملاحية.",
        "chain": ["country_id", "place_type_id", "geo_precision"],
    },
    {
        "id": "relationships",
        "entity": "relationship",
        "label_en": "Relationships",
        "label_ar": "العلاقات",
        "note_en": "Relationship type, then whether a direction is declared, then how the "
                   "connection was verified.",
        "note_ar": "نوع العلاقة، ثم هل الاتجاه معلن، ثم كيفية التحقق من العلاقة.",
        "chain": ["relationship_type_id", "direction", "authentication_id"],
    },
    {
        "id": "sources",
        "entity": "source",
        "label_en": "Sources",
        "label_ar": "المصادر",
        "note_en": "Source type, then the reliability recorded for it, then its status. "
                   "Reliability and verification are separate claims and stay separate.",
        "note_ar": "نوع المصدر، ثم موثوقيته المسجّلة، ثم حالته. الموثوقية والتحقق "
                   "ادّعاءان منفصلان ويبقيان كذلك.",
        "chain": ["source_type_id", "reliability_id", "record_status_id"],
    },
    {
        "id": "events",
        "entity": "event",
        "label_en": "Events",
        "label_ar": "الأحداث",
        "note_en": "Event type, then the place it happened at, then the documentation "
                   "level on file. With records on, each event opens onto the people "
                   "and organizations linked to it.",
        "note_ar": "نوع الحدث، ثم المكان الذي وقع فيه، ثم مستوى التوثيق المسجّل. "
                   "ومع إظهار السجلات ينفتح كل حدث على الأشخاص والمؤسسات المرتبطة به.",
        "chain": ["event_type_id", "place_id", "documentation_id"],
    },
]


def sources(conn: sqlite3.Connection) -> list[dict]:
    """The source registry, with the live total for each source."""
    out = []
    for src in SOURCES:
        spec = ENTITIES[src["entity"]]
        total = conn.execute(
            f"SELECT COUNT(*) FROM {spec.table} WHERE deleted_at IS NULL").fetchone()[0]
        out.append({
            "id": src["id"], "entity": src["entity"],
            "label_en": src["label_en"], "label_ar": src["label_ar"],
            "note_en": src["note_en"], "note_ar": src["note_ar"],
            "total": total,
            "chain": [_dimension(spec, key)["label"] for key in src["chain"]],
        })
    return out


# --------------------------------------------------------------------------- #
# dimensions
# --------------------------------------------------------------------------- #
class Unsupported(RuntimeError):
    """A chain names a field the registry does not have, or cannot group by."""


def _dimension(spec, key: str) -> dict:
    """Resolve one chain field into the SQL it takes to group by it.

    Returns ``{key, label, join, key_sql, en_sql, ar_sql, order_sql}``. The joins
    are written once per level and reused by every query underneath it, which is
    what keeps a three-level tree to a couple of hundred small statements rather
    than a query per cell.
    """
    field = spec.field(key)
    if field is None:
        raise Unsupported(f"{spec.key}.{key} is not a field of this entity")
    label = {"en": field.label_en, "ar": field.label_ar}
    col = f"t.{field.key}"

    if field.type == "select":
        alias = f"d_{field.key}"
        # Vocabulary fields either store the lookup id or the vocabulary code.
        # Joining on the wrong side silently dumps every row into "not recorded".
        if field.store == "code":
            domain = (field.domain or "").replace("'", "''")
            join = (f"LEFT JOIN lookup {alias} ON {alias}.domain = '{domain}' "
                    f"AND {alias}.code = {col}")
        else:
            join = f"LEFT JOIN lookup {alias} ON {alias}.id = {col}"
        return {
            "key": key, "label": label, "field": field,
            "join": join,
            "key_sql": f"COALESCE({alias}.code, '{NOT_RECORDED_KEY}')",
            "en_sql": f"COALESCE({alias}.label_en, '{NOT_RECORDED[0]}')",
            "ar_sql": f"COALESCE({alias}.label_ar, '{NOT_RECORDED[1]}')",
        }
    if field.type == "fk":
        ref = ENTITIES.get(field.ref or "")
        if ref is None:
            raise Unsupported(f"{spec.key}.{key} points at an unknown entity")
        alias = f"d_{field.key}"
        name_en, name_ar = ref.name_fields
        return {
            "key": key, "label": label, "field": field,
            "join": f"LEFT JOIN {ref.table} {alias} "
                    f"ON {alias}.id = {col} AND {alias}.deleted_at IS NULL",
            "key_sql": f"COALESCE({alias}.id, -1)",
            "en_sql": f"COALESCE({alias}.{name_en}, {alias}.code, '{NOT_RECORDED[0]}')",
            "ar_sql": f"COALESCE({alias}.{name_ar}, {alias}.{name_en}, "
                      f"{alias}.code, '{NOT_RECORDED[1]}')",
        }
    if field.type == "bool":
        return {
            "key": key, "label": label, "field": field, "join": "",
            "key_sql": f"CASE WHEN {col} = 1 THEN 1 ELSE 0 END",
            "en_sql": f"CASE WHEN {col} = 1 THEN 'yes' ELSE 'no' END",
            "ar_sql": f"CASE WHEN {col} = 1 THEN 'نعم' ELSE 'لا' END",
        }
    if field.type == "date":
        # a year is the only honest bucket a partial date offers
        return {
            "key": key, "label": label, "field": field, "join": "",
            "key_sql": f"COALESCE(substr({col}, 1, 4), '{NOT_RECORDED_KEY}')",
            "en_sql": f"COALESCE(substr({col}, 1, 4), '{NOT_RECORDED[0]}')",
            "ar_sql": f"COALESCE(substr({col}, 1, 4), '{NOT_RECORDED[1]}')",
        }
    raise Unsupported(f"{spec.key}.{key} cannot be grouped ({field.type})")


# --------------------------------------------------------------------------- #
# links hanging off a record leaf
# --------------------------------------------------------------------------- #
_LINK_TYPES = ("person", "institution", "place", "event", "source")


def _attach_links(conn: sqlite3.Connection, root: dict, entity: str) -> int:
    """Hang the other end of each relationship under the record it belongs to.

    An event's leaf then opens onto the people and organizations at it, and a
    person's leaf opens onto the events and organizations they are tied to.
    The record's own count is left alone — a link is not another record of the
    same kind, and the client keeps a record's value instead of summing these.
    """
    nodes: list[dict] = []

    def walk(n: dict) -> None:
        meta = n.get("meta") or {}
        if meta.get("record") and meta.get("record_id") and not meta.get("synthetic"):
            nodes.append(n)
        for child in n.get("children") or []:
            walk(child)

    walk(root)
    if not nodes:
        return 0
    by_id = {int(n["meta"]["record_id"]): n for n in nodes}
    ids = list(by_id)
    found = 0
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        marks = ",".join("?" * len(chunk))
        sql = (
            "SELECT r.entity1_type AS t1, r.entity1_id AS i1, r.entity1_name AS n1, "
            "r.entity2_type AS t2, r.entity2_id AS i2, r.entity2_name AS n2, "
            "COALESCE(rt.label_en, '') AS type_en, COALESCE(rt.label_ar, '') AS type_ar "
            "FROM relationship r "
            "LEFT JOIN lookup rt ON rt.id = r.relationship_type_id "
            "WHERE r.deleted_at IS NULL AND ("
            f"(r.entity1_type = ? AND r.entity1_id IN ({marks})) OR "
            f"(r.entity2_type = ? AND r.entity2_id IN ({marks})))"
        )
        params: list[Any] = [entity, *chunk, entity, *chunk]
        for row in conn.execute(sql, params):
            sides = []
            if row["t1"] == entity and int(row["i1"]) in by_id:
                sides.append((int(row["i1"]), row["t2"], int(row["i2"]), row["n2"]))
            if row["t2"] == entity and int(row["i2"]) in by_id:
                sides.append((int(row["i2"]), row["t1"], int(row["i1"]), row["n1"]))
            for owner, other_t, other_i, other_n in sides:
                if other_t not in _LINK_TYPES:
                    continue
                if other_t == entity and other_i == owner:
                    continue
                node = by_id[owner]
                child_id = f"{node['id']}/link={other_t}:{other_i}"
                children = node.setdefault("children", [])
                if any(c.get("id") == child_id for c in children):
                    continue
                label = other_n or f"{other_t} #{other_i}"
                depth = int((node.get("meta") or {}).get("depth") or 0) + 1
                children.append({
                    "id": child_id,
                    "label_en": label,
                    "label_ar": label,
                    "value": 1,
                    "meta": {
                        "dimension": "link",
                        "raw": f"{other_t}:{other_i}",
                        "depth": depth,
                        "record": True,
                        "link": True,
                        "entity": other_t,
                        "record_id": other_i,
                        "link_en": row["type_en"],
                        "link_ar": row["type_ar"],
                    },
                })
                found += 1
    return found


# --------------------------------------------------------------------------- #
# the tree
# --------------------------------------------------------------------------- #
def build(conn: sqlite3.Connection, source_id: str, depth: int = 3,
          max_children: int = MAX_CHILDREN, include_leaves: bool = False,
          max_leaves: int = MAX_LEAVES) -> dict:
    """One source's tree, with an exact count on every node.

    When ``include_leaves`` is true, every deepest dimension branch also lists
    the underlying records (capped by ``max_leaves``) so the tree can drill to
    a specific person, institution, place, event, source or relationship.
    """
    t0 = time.perf_counter()
    src = next((s for s in SOURCES if s["id"] == source_id), None)
    if src is None:
        raise KeyError(source_id)
    spec = ENTITIES[src["entity"]]
    depth = max(1, min(MAX_DEPTH, int(depth)))
    max_leaves = max(1, min(120, int(max_leaves)))
    chain = [_dimension(spec, key) for key in src["chain"][:depth]]
    name_fields = list(spec.name_fields or ())
    name_en = name_fields[0] if name_fields else "code"
    name_ar = name_fields[1] if len(name_fields) > 1 else name_en

    where = ["t.deleted_at IS NULL"]

    def table_sql(level: int) -> str:
        """The FROM clause for ``level``: the entity plus every join above it."""
        t = f"{spec.table} t"
        joins = [d["join"] for d in chain[:level + 1] if d["join"]]
        return " ".join([t] + joins)

    def rows_at(level: int, conditions: list[str], params: list[Any]) -> list[dict]:
        dim = chain[level]
        sql = (f"SELECT {dim['key_sql']} AS k, {dim['en_sql']} AS en, {dim['ar_sql']} AS ar, "
               f"COUNT(*) AS n FROM {table_sql(level)} WHERE "
               + " AND ".join(where + conditions)
               + " GROUP BY 1, 2, 3 ORDER BY n DESC")
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def attach_leaves(node: dict, conditions: list[str], params: list[Any],
                      level: int) -> None:
        """List the actual records that reach this deepest dimension node."""
        from_sql = table_sql(max(0, level - 1)) if chain else f"{spec.table} t"
        # When the chain is empty we still need the entity table; when it is not,
        # the joins of the deepest dimension already bound the group.
        if chain and level >= 1:
            from_sql = table_sql(level - 1)
        sql = (
            f"SELECT t.id AS rid, t.code AS code, "
            f"COALESCE(NULLIF(t.{name_en}, ''), NULLIF(t.{name_ar}, ''), t.code) AS en, "
            f"COALESCE(NULLIF(t.{name_ar}, ''), NULLIF(t.{name_en}, ''), t.code) AS ar "
            f"FROM {from_sql} WHERE " + " AND ".join(where + conditions)
            + " ORDER BY en COLLATE NOCASE LIMIT ?"
        )
        rows = [dict(r) for r in conn.execute(sql, params + [max_leaves + 1]).fetchall()]
        kept = rows[:max_leaves]
        children = []
        for row in kept:
            rid = int(row["rid"])
            children.append({
                "id": f"{node['id']}/record={rid}",
                "label_en": row["en"] or row["code"] or f"#{rid}",
                "label_ar": row["ar"] or row["en"] or row["code"] or f"#{rid}",
                "value": 1,
                "meta": {
                    "dimension": "record", "raw": str(rid), "depth": level + 1,
                    "record": True, "entity": src["entity"], "record_id": rid,
                    "code": row["code"],
                },
            })
        overflow = rows[max_leaves:]
        if overflow or (node.get("value") or 0) > len(kept):
            # Prefer the node's own count when the query was capped.
            folded = max(0, int(node.get("value") or 0) - len(kept))
            if folded > 0:
                children.append({
                    "id": f"{node['id']}/record=~rest",
                    "label_en": f"{folded} more records",
                    "label_ar": f"{folded} سجلًا إضافيًا",
                    "value": folded,
                    "meta": {
                        "dimension": "record", "synthetic": True, "count": folded,
                        "folded": folded, "depth": level + 1, "record": True,
                        "entity": src["entity"],
                    },
                })
        node["children"] = children
        node["meta"] = {
            **(node.get("meta") or {}),
            "has_records": True,
            "leaf_count": len(kept),
            "of": node.get("value"),
        }

    def add_children(node: dict, level: int, conditions: list[str],
                     params: list[Any]) -> None:
        if level >= len(chain):
            if include_leaves:
                attach_leaves(node, conditions, params, level)
            return
        dim = chain[level]
        rows = rows_at(level, conditions, params)
        total = sum(r["n"] for r in rows)
        node["value"] = total
        # Breadth belongs to the top. The first split is one query per branch and
        # is what the picture is read from, so it is given room; deeper levels are
        # one query per branch *per parent* and are kept narrow. Without this the
        # cost of a three-level tree grows as n³ and the first level is starved.
        budget = (min(60, max_children * 2) if level == 0
                  else max(5, max_children // (level + 1)))
        kept = rows[:budget]
        children = []
        for row in kept:
            key = str(row["k"])
            child = {
                "id": f"{node['id']}/{dim['key']}={key}",
                "label_en": row["en"], "label_ar": row["ar"] or row["en"],
                "value": row["n"],
                "meta": {"dimension": dim["key"], "raw": key, "depth": level + 1,
                         "collected": len(rows), "of": total},
            }
            next_conditions = conditions + [f"{dim['key_sql']} = ?"]
            next_params = params + [row["k"]]
            if level + 1 >= len(chain) and include_leaves:
                # Deepest taxonomy bucket: list the records that fall in it.
                attach_leaves(child, next_conditions, next_params, level + 1)
            else:
                add_children(child, level + 1, next_conditions, next_params)
            children.append(child)
        rest = rows[len(kept):]
        if rest:
            remainder = sum(r["n"] for r in rest)
            children.append({
                "id": f"{node['id']}/{dim['key']}=~rest",
                "label_en": f"{len(rest)} smaller groups",
                "label_ar": f"{len(rest)} مجموعة أصغر",
                "value": remainder,
                "meta": {"dimension": dim["key"], "synthetic": True,
                         "count": len(rest), "folded": remainder,
                         "depth": level + 1, "collected": len(rows), "of": total},
            })
        node["children"] = children
        node["meta"] = {**(node.get("meta") or {}), "collected": len(rows), "of": total}

    # each level adds one bound condition to the ones above it, so a child's count
    # is always "records that reach this node", computed by the database
    root = {"id": src["id"], "label_en": src["label_en"], "label_ar": src["label_ar"],
            "value": 0, "meta": {"dimension": None, "depth": 0}}
    add_children(root, 0, [], [])

    linked = 0
    if include_leaves:
        linked = _attach_links(conn, root, src["entity"])

    chain_meta = [{"key": d["key"], "label_en": d["label"]["en"],
                   "label_ar": d["label"]["ar"]} for d in chain]
    if include_leaves:
        chain_meta.append({
            "key": "record",
            "label_en": "Record",
            "label_ar": "السجل",
        })
        chain_meta.append({
            "key": "link",
            "label_en": "Linked record",
            "label_ar": "سجل مرتبط",
        })

    return {
        "ok": True,
        "source": {
            "id": src["id"], "entity": src["entity"],
            "label_en": src["label_en"], "label_ar": src["label_ar"],
            "note_en": src["note_en"], "note_ar": src["note_ar"],
        },
        "chain": chain_meta,
        "depth": depth,
        "max_children": max_children,
        "include_leaves": include_leaves,
        "include_links": bool(include_leaves),
        "linked": linked,
        "max_leaves": max_leaves,
        "root": root,
        "total": root["value"],
        "computed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
