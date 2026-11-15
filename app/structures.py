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


def _spec(entity: str):
    """Registry *or* military entity spec — one structure contract for both."""
    from .military.specs import MIL_SPECS
    return MIL_SPECS.get(entity) or ENTITIES.get(entity)


def _soft_delete(spec) -> bool:
    """Registry tables are soft-deleted; military tables have no deleted_at."""
    from .military.specs import MIL_SPECS
    return spec.key not in MIL_SPECS


def _label_cols(spec) -> tuple[str, str, str | None]:
    """(name column, alt-label column, code column) for one entity.

    A second name field on a military spec is the document-name, not a
    translation of the first — never show a doc-number as an Arabic label.
    """
    names = list(spec.name_fields or ())
    name = names[0] if names else "code"
    alt = names[1] if (len(names) > 1 and _soft_delete(spec)) else name
    field_keys = {f.key for f in spec.fields}
    code = "docname" if "docname" in field_keys else ("code" if "code" in field_keys else None)
    return name, alt, code

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

    # ---- military modules: hierarchies and structural compositions ----------
    {
        "id": "units",
        "kind": "hierarchy",
        "family": "modules",
        "entity": "unit",
        "parent": "parent_id",
        "label_en": "Units — command hierarchy",
        "label_ar": "الوحدات — التسلسل القيادي",
        "note_en": "The order of battle as a tree: every unit under its parent, "
                   "sized by how many units stand at or below it. Personnel and "
                   "readiness ride each node.",
        "note_ar": "التنظيم القتالي على شكل شجرة: كل وحدة تحت وحدتها الأم، وحجمها "
                   "بحسب عدد الوحدات فيها وتحتها. وتظهر الأفراد والحالة على كل عقدة.",
        "levels": [("unit", "Unit", "الوحدة")],
    },
    {
        "id": "regions",
        "kind": "hierarchy",
        "family": "modules",
        "entity": "region",
        "parent": "parent_id",
        "label_en": "Regions — command areas",
        "label_ar": "المناطق — القيادة الإقليمية",
        "note_en": "Command regions under their parent regions, sized by the number "
                   "of regions at or below, with the units stationed in each subtree.",
        "note_ar": "المناطق القيادية تحت مناطقها الأم، وبحسب عدد المناطق فيها "
                   "وتحتها، مع الوحدات المتمركزة في كل فرع.",
        "levels": [("region", "Region", "المنطقة")],
    },
    {
        "id": "regions-units",
        "kind": "composite",
        "family": "modules",
        "entity": "region",
        "label_en": "Regions × Units — where the forces sit",
        "label_ar": "المناطق × الوحدات — موقع القوات",
        "note_en": "Two modules read together: the region tree, with each region's "
                   "units nested inside it and their own subordination preserved.",
        "note_ar": "وحدتان معًا: شجرة المناطق، وداخل كل منطقة وحداتها مع الحفاظ "
                   "على تسلسلها القيادي.",
        "levels": [("region", "Region", "المنطقة"), ("unit", "Unit", "الوحدة")],
        "layers": [
            {"entity": "region", "parent": "parent_id"},
            {"entity": "unit", "link": "region_id", "parent": "parent_id"},
        ],
    },
    {
        "id": "units-ops",
        "kind": "composite",
        "family": "modules",
        "entity": "unit",
        "label_en": "Units × Operations — what stands under each unit",
        "label_ar": "الوحدات × العمليات — ما تحت كل وحدة",
        "note_en": "The unit tree with the deployments, missions and trainings "
                   "nested under the unit that owns them.",
        "note_ar": "شجرة الوحدات مع نشراتها ومهامها وتدريباتها تحت كل وحدة تملكها.",
        "levels": [("unit", "Unit", "الوحدة"), ("deployment", "Deployment", "النشرة"),
                   ("mission", "Mission", "المهمة"), ("training", "Training", "التدريب")],
        "layers": [
            {"entity": "unit", "parent": "parent_id"},
            {"entity": "deployment", "link": "unit_id"},
            {"entity": "mission", "link": "unit_id"},
            {"entity": "training", "link": "unit_id"},
        ],
    },
    {
        "id": "forces",
        "kind": "chain",
        "family": "modules",
        "entity": "unit",
        "label_en": "Forces — echelon, status, classification",
        "label_ar": "القوات — الإطار، الحالة، التصنيف",
        "note_en": "The order of battle read as categories: echelon, then readiness "
                   "status, then classification. With leaves on, the deepest branch "
                   "lists the units themselves.",
        "note_ar": "التنظيم القتالي كتصنيفات: الإطار، ثم حالة الجاهزية، ثم التصنيف. "
                   "ومع إظهار السجلات تظهر كل وحدة في أعمق فرع.",
        "chain": ["echelon", "status", "classification_id"],
    },
]


def sources(conn: sqlite3.Connection) -> list[dict]:
    """The source registry, with the live total for each source."""
    out = []
    for src in SOURCES:
        spec = _spec(src["entity"])
        where = " WHERE deleted_at IS NULL" if _soft_delete(spec) else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM {spec.table}{where}").fetchone()[0]
        if src.get("levels"):
            chain = [{"en": en, "ar": ar} for (_k, en, ar) in src["levels"]]
        else:
            chain = [_dimension(spec, key)["label"] for key in src["chain"]]
        out.append({
            "id": src["id"], "entity": src["entity"],
            "family": src.get("family", "registry"),
            "kind": src.get("kind", "chain"),
            "label_en": src["label_en"], "label_ar": src["label_ar"],
            "note_en": src["note_en"], "note_ar": src["note_ar"],
            "total": total,
            "chain": chain,
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
            if not field.domain:
                # a free-code vocabulary (options on the field itself): the value
                # IS the label, group by it as it stands
                return {
                    "key": key, "label": label, "field": field, "join": "",
                    "key_sql": f"COALESCE({col}, '{NOT_RECORDED_KEY}')",
                    "en_sql": f"COALESCE({col}, '{NOT_RECORDED[0]}')",
                    "ar_sql": f"COALESCE({col}, '{NOT_RECORDED[1]}')",
                }
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
        ref = _spec(field.ref or "")
        if ref is None:
            raise Unsupported(f"{spec.key}.{key} points at an unknown entity")
        alias = f"d_{field.key}"
        name_en, name_ar, code_col = _label_cols(ref)
        soft = f" AND {alias}.deleted_at IS NULL" if _soft_delete(ref) else ""
        fallback = (f"{alias}.{code_col}" if code_col else f"{alias}.id")
        return {
            "key": key, "label": label, "field": field,
            "join": f"LEFT JOIN {ref.table} {alias} ON {alias}.id = {col}{soft}",
            "key_sql": f"COALESCE({alias}.id, -1)",
            "en_sql": f"COALESCE({alias}.{name_en}, {fallback}, '{NOT_RECORDED[0]}')",
            "ar_sql": f"COALESCE({alias}.{name_ar}, {alias}.{name_en}, "
                      f"{fallback}, '{NOT_RECORDED[1]}')",
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
    if src.get("kind", "chain") != "chain":
        # hierarchies and cross-module compositions: parent-linked trees, built
        # under the very same payload contract the kernel draws
        return _build_structural(conn, src, t0,
                                 depth=depth, max_children=max_children)
    spec = _spec(src["entity"])
    depth = max(1, min(MAX_DEPTH, int(depth)))
    max_leaves = max(1, min(120, int(max_leaves)))
    chain = [_dimension(spec, key) for key in src["chain"][:depth]]
    name_en, name_ar, code_col = _label_cols(spec)

    where = ["t.deleted_at IS NULL"] if _soft_delete(spec) else []

    def table_sql(level: int) -> str:
        """The FROM clause for ``level``: the entity plus every join above it."""
        t = f"{spec.table} t"
        joins = [d["join"] for d in chain[:level + 1] if d["join"]]
        return " ".join([t] + joins)

    def rows_at(level: int, conditions: list[str], params: list[Any]) -> list[dict]:
        dim = chain[level]
        cond = where + conditions
        cond_sql = (" WHERE " + " AND ".join(cond)) if cond else ""
        sql = (f"SELECT {dim['key_sql']} AS k, {dim['en_sql']} AS en, {dim['ar_sql']} AS ar, "
               f"COUNT(*) AS n FROM {table_sql(level)}{cond_sql}"
               f" GROUP BY 1, 2, 3 ORDER BY n DESC")
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def attach_leaves(node: dict, conditions: list[str], params: list[Any],
                      level: int) -> None:
        """List the actual records that reach this deepest dimension node."""
        from_sql = table_sql(max(0, level - 1)) if chain else f"{spec.table} t"
        # When the chain is empty we still need the entity table; when it is not,
        # the joins of the deepest dimension already bound the group.
        if chain and level >= 1:
            from_sql = table_sql(level - 1)
        cond = where + conditions
        cond_sql = (" WHERE " + " AND ".join(cond)) if cond else ""
        code_sql = f"t.{code_col}" if code_col else "NULL"
        sql = (
            f"SELECT t.id AS rid, {code_sql} AS code, "
            f"COALESCE(NULLIF(t.{name_en}, ''), NULLIF(t.{name_ar}, ''), {code_sql}) AS en, "
            f"COALESCE(NULLIF(t.{name_ar}, ''), NULLIF(t.{name_en}, ''), {code_sql}) AS ar "
            f"FROM {from_sql}{cond_sql}"
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


# --------------------------------------------------------------------------- #
# structural sources: hierarchies and cross-module compositions
# --------------------------------------------------------------------------- #
def _load_layer(conn, spec, extra_cols: list[str | None]):
    """All rows of one entity, keyed by id, with its label/code columns."""
    name_en, name_ar, code_col = _label_cols(spec)
    cols = ["id", name_en]
    if name_ar != name_en:
        cols.append(name_ar)
    if code_col and code_col not in cols:
        cols.append(code_col)
    for c in extra_cols:
        if c and c not in cols:
            cols.append(c)
    where = " WHERE deleted_at IS NULL" if _soft_delete(spec) else ""
    sql = f"SELECT {', '.join('t.' + c for c in cols)} FROM {spec.table} t{where}"
    rows = {int(r["id"]): dict(r) for r in conn.execute(sql).fetchall()}
    return rows, name_en, name_ar, code_col


def _struct_node(spec, row: dict, name_en: str, name_ar: str,
                 code_col: str | None, value: int, depth: int) -> dict:
    """One node of a structural model — a record the kernel can open."""
    code = row.get(code_col) if code_col else None
    fallback = code or f"#{row['id']}"
    meta = {
        "dimension": spec.key, "raw": str(row["id"]), "depth": depth,
        "record": True, "record_id": int(row["id"]), "entity": spec.key,
        "code": code,
    }
    return {
        "id": f"{spec.key}={row['id']}",
        "label_en": row.get(name_en) or row.get(name_ar) or fallback,
        "label_ar": row.get(name_ar) or row.get(name_en) or fallback,
        "value": value,
        "meta": meta,
    }


def _fold_nodes(nodes: list[dict], budget: int, parent_id: str) -> list[dict]:
    """Keep the biggest branches, fold the rest — with their exact sum."""
    if len(nodes) <= budget:
        return nodes
    nodes = sorted(nodes, key=lambda n: n["value"], reverse=True)
    kept, rest = nodes[:budget], nodes[budget:]
    folded = sum(n["value"] for n in rest)
    kept.append({
        "id": f"{parent_id}/rest",
        "label_en": f"{len(rest)} smaller groups",
        "label_ar": f"{len(rest)} مجموعة أصغر",
        "value": folded,
        "meta": {"dimension": "rest", "synthetic": True,
                 "count": len(rest), "folded": folded},
    })
    return kept


def _attach_group(spec, rows: list[dict], lay: dict, depth: int,
                  max_children: int) -> tuple[list[dict], int]:
    """Records attached under a structural node: flat, or nested by their own
    parent when the layer carries one (units keep their subordination)."""
    name_en, name_ar, code_col = _label_cols(spec)
    parent_col = lay.get("parent")

    def assemble(row: dict, d: int) -> tuple[dict, int]:
        kids = []
        total = 1
        if parent_col:
            children = [r for r in rows
                        if r.get(parent_col) and int(r[parent_col]) == int(row["id"])]
            for c in sorted(children, key=lambda r: r["id"]):
                node, t = assemble(c, d + 1)
                kids.append(node)
                total += t
        node = _struct_node(spec, row, name_en, name_ar, code_col, total, d)
        node["children"] = _fold_nodes(kids, max_children, node["id"])
        return node, total

    if not parent_col:
        nodes = []
        total = 0
        for r in sorted(rows, key=lambda r: r["id"]):
            node, t = assemble(r, depth)
            nodes.append(node)
            total += t
        return _fold_nodes(nodes, max_children, f"{spec.key}@{depth}"), total

    in_group = {int(r["id"]) for r in rows}
    tops = [r for r in rows
            if not (r.get(parent_col) and int(r[parent_col]) in in_group)]
    nodes, total = [], 0
    for r in sorted(tops, key=lambda r: r["id"]):
        node, t = assemble(r, depth)
        nodes.append(node)
        total += t
    return _fold_nodes(nodes, max_children, f"{spec.key}@{depth}"), total


def _build_structural(conn, src: dict, t0: float, depth: int = 3,
                      max_children: int = MAX_CHILDREN) -> dict:
    """A parent-linked hierarchy, possibly composed across modules.

    Layer 0 is the hierarchy (``parent`` column).  Further layers attach their
    records under the layer-0 node their ``link`` column points at; a layer that
    also carries ``parent`` keeps its own subordination inside each group.
    Every node is a real record with an exact record count at or below it, and
    wide levels fold their tail exactly like the dimension chains do.
    """
    depth = max(1, min(MAX_DEPTH, int(depth)))
    max_children = max(3, min(40, int(max_children)))
    layers = src.get("layers") or [{"entity": src["entity"], "parent": src.get("parent")}]
    main = layers[0]
    spec0 = _spec(main["entity"])
    rows0, n_en, n_ar, code0 = _load_layer(conn, spec0, [main.get("parent")])
    parent_col = main.get("parent")

    children_map: dict[int, list[int]] = {rid: [] for rid in rows0}
    tops: list[int] = []
    for rid, row in rows0.items():
        p = row.get(parent_col) if parent_col else None
        if p is not None and int(p) in rows0:
            children_map[int(p)].append(rid)
        else:
            tops.append(rid)

    attached = []
    for lay in layers[1:]:
        spec_l = _spec(lay["entity"])
        rows_l, l_en, l_ar, l_code = _load_layer(
            conn, spec_l, [lay.get("link"), lay.get("parent")])
        by_link: dict[int, list[dict]] = {}
        for r in rows_l.values():
            link = r.get(lay.get("link"))
            by_link.setdefault(int(link) if link is not None else 0, []).append(r)
        attached.append((spec_l, by_link, lay))

    def assemble(rid: int, d: int) -> tuple[dict, int]:
        kids: list[dict] = []
        total = 1  # the record itself
        for k in sorted(children_map[rid]):
            node, t = assemble(k, d + 1)
            total += t
            if d + 1 <= depth:
                kids.append(node)
        for spec_l, by_link, lay in attached:
            group = by_link.get(rid, [])
            if not group:
                continue
            nodes, t = _attach_group(spec_l, group, lay,
                                     min(depth, d + 1), max_children)
            if d + 1 <= depth:
                kids.extend(nodes)
            total += t
        node = _struct_node(spec0, rows0[rid], n_en, n_ar, code0, total, d)
        node["children"] = _fold_nodes(kids, max_children, node["id"])
        return node, total

    top_nodes, grand = [], 0
    for rid in sorted(tops):
        node, t = assemble(rid, 1)
        top_nodes.append(node)
        grand += t
    root = {"id": src["id"], "label_en": src["label_en"], "label_ar": src["label_ar"],
            "value": grand, "meta": {"dimension": None, "depth": 0}}
    root["children"] = _fold_nodes(top_nodes, max_children * 2, src["id"])

    chain_meta = [{"key": k, "label_en": en, "label_ar": ar}
                  for (k, en, ar) in src.get("levels", [])]
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
        "include_leaves": False,
        "include_links": False,
        "linked": 0,
        "max_leaves": MAX_LEAVES,
        "root": root,
        "total": grand,
        "computed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
