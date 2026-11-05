"""
Structural integrity checks and repairs.

The registry stores a graph in one SQLite file, and some of that graph cannot be
expressed as a foreign key: ``relationship``, ``entity_tag``, ``source_link``,
``attachment`` and ``entity_external_id`` all point at *any* entity type through a
``(entity_type, entity_id)`` pair.  SQLite therefore cannot protect them, and a
half-finished delete or a hand-edited database can leave them dangling.

This module is the product's own answer to "is the data sound?":

    python3 -m app.cli check-integrity           # report only
    python3 -m app.cli check-integrity --fix     # repair what is safe to repair

``scan()`` is used by the test-suite as well, so the audit and the built-in tool
can never drift apart.  Everything it reports is *measured*, never assumed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from . import db
from .schemas import ENTITIES, derived_map  # noqa: F401  (derived_map re-exported for callers)

POLYMORPHIC = {
    "entity_tag": ("entity_type", "entity_id"),
    "source_link": ("entity_type", "entity_id"),
    "attachment": ("entity_type", "entity_id"),
    "entity_external_id": ("entity_type", "entity_id"),
}
ENTITY_TABLES = {k: s.table for k, s in ENTITIES.items()}


def _branches(alias: str, type_col: str, id_col: str) -> str:
    return " UNION ALL ".join(
        f"SELECT 1 FROM {t} p WHERE {alias}.{type_col}='{k}' AND p.id={alias}.{id_col}"
        for k, t in ENTITY_TABLES.items())


def _orphan_sql(table: str, type_col: str, id_col: str) -> str:
    return (f"SELECT COUNT(*) FROM {table} x WHERE NOT EXISTS ("
            + _branches("x", type_col, id_col) + ")")


def scan(conn: sqlite3.Connection) -> dict[str, Any]:
    """Measure every class of structural problem. Pure read-only."""
    def one(sql: str, params: tuple = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0])

    problems: dict[str, int] = {}

    problems["broken_foreign_keys"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    for table, (tcol, icol) in POLYMORPHIC.items():
        problems[f"orphan_links:{table}"] = one(_orphan_sql(table, tcol, icol))
    problems["orphan_links:relationship"] = one(
        "SELECT COUNT(*) FROM relationship r WHERE NOT EXISTS ("
        + _branches("r", "entity1_type", "entity1_id") + ") OR NOT EXISTS ("
        + _branches("r", "entity2_type", "entity2_id") + ")")
    # an evidence row is orphaned only when *its own* target is gone: entity-level
    # rows point at a record, relationship-level rows point at a relationship, and
    # a row that points at neither is malformed
    problems["orphan_links:evidence"] = one(
        "SELECT COUNT(*) FROM evidence e WHERE "
        "(e.relationship_id IS NULL AND e.entity_id IS NULL) OR "
        "(e.relationship_id IS NULL AND NOT EXISTS (" + _branches("e", "entity_type", "entity_id") + ")) OR "
        "(e.relationship_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM relationship r WHERE r.id = e.relationship_id))")
    problems["dangling_citations"] = one(
        "SELECT COUNT(*) FROM source_link sl WHERE NOT EXISTS "
        "(SELECT 1 FROM source s WHERE s.id = sl.source_id)")
    problems["self_relationships"] = one(
        "SELECT COUNT(*) FROM relationship WHERE entity1_type = entity2_type "
        "AND entity1_id = entity2_id")
    problems["duplicate_relationship_triples"] = one(
        "SELECT COUNT(*) FROM (SELECT entity1_type, entity1_id, entity2_type, entity2_id, "
        "relationship_type_id FROM relationship GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1)")

    dup_codes = 0
    blank_codes = 0
    for table in ENTITY_TABLES.values():
        dup_codes += one(f"SELECT COUNT(*) FROM (SELECT code FROM {table} "
                         f"WHERE code IS NOT NULL GROUP BY code HAVING COUNT(*) > 1)")
        blank_codes += one(f"SELECT COUNT(*) FROM {table} "
                           f"WHERE code IS NULL OR TRIM(code) = ''")
    problems["duplicate_codes"] = dup_codes
    problems["blank_codes"] = blank_codes

    problems["place_cycles"] = one("""
        WITH RECURSIVE up(id, cur, depth) AS (
            SELECT id, id, 0 FROM place WHERE parent_place_id IS NOT NULL
            UNION ALL
            SELECT up.id, p.parent_place_id, up.depth + 1
              FROM up JOIN place p ON p.id = up.cur
             WHERE p.parent_place_id IS NOT NULL AND up.depth < 32)
        SELECT COUNT(*) FROM up WHERE cur = id AND depth > 0""")
    problems["birth_after_death"] = one(
        "SELECT COUNT(*) FROM person WHERE birth_date IS NOT NULL AND death_date IS NOT NULL "
        "AND birth_date > death_date")

    # the search index must hold exactly one document per live record
    index_gap = 0
    for key, table in ENTITY_TABLES.items():
        live = one(f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NULL")
        docs = one("SELECT COUNT(*) FROM search_doc WHERE entity_type = ?", (key,))
        index_gap += abs(live - docs)
    live_rel = one("SELECT COUNT(*) FROM relationship WHERE deleted_at IS NULL")
    docs_rel = one("SELECT COUNT(*) FROM search_doc WHERE entity_type = 'relationship'")
    problems["index_gap"] = index_gap + abs(live_rel - docs_rel)
    problems["stale_index_documents"] = one("""
        SELECT COUNT(*) FROM search_doc sd WHERE sd.entity_type <> 'relationship'
          AND NOT EXISTS (SELECT 1 FROM person p WHERE sd.entity_type='person'
                          AND p.id=sd.entity_id AND p.deleted_at IS NULL
                          UNION ALL SELECT 1 FROM institution p WHERE sd.entity_type='institution'
                          AND p.id=sd.entity_id AND p.deleted_at IS NULL
                          UNION ALL SELECT 1 FROM place p WHERE sd.entity_type='place'
                          AND p.id=sd.entity_id AND p.deleted_at IS NULL
                          UNION ALL SELECT 1 FROM event p WHERE sd.entity_type='event'
                          AND p.id=sd.entity_id AND p.deleted_at IS NULL
                          UNION ALL SELECT 1 FROM source p WHERE sd.entity_type='source'
                          AND p.id=sd.entity_id AND p.deleted_at IS NULL)""")

    # a number sequence that sits at or below a live code will hand out a duplicate
    behind = []
    for r in conn.execute("SELECT entity_type, prefix, next_value FROM sequence"):
        spec = ENTITIES.get(r["entity_type"])
        if spec is None:
            behind.append(f"{r['entity_type']}:unknown")
            continue
        top = conn.execute(
            f"SELECT MAX(CAST(substr(code, instr(code,'-') + 1) AS INTEGER)) FROM {spec.table} "
            f"WHERE code LIKE ?", (r["prefix"] + "-%",)).fetchone()[0] or 0
        if top >= r["next_value"]:
            behind.append(r["entity_type"])
    problems["sequences_behind"] = len(behind)
    problems["sequences_behind:detail"] = behind            # type: ignore[assignment]

    # attachments whose file has vanished are broken links in the interface
    up = Path(db.UPLOAD_DIR)
    files = {p.name for p in up.rglob("*") if p.is_file()} if up.exists() else set()
    rows = conn.execute("SELECT id, stored_name FROM attachment").fetchall()
    problems["attachment_rows"] = len(rows)
    problems["attachments_missing_file"] = sum(
        1 for r in rows if r["stored_name"] and r["stored_name"] not in files)
    return problems


def summary(problems: dict[str, Any]) -> list[str]:
    """Human-readable lines for the problems that are actually non-zero."""
    labels = {
        "broken_foreign_keys": "broken foreign keys",
        "dangling_citations": "citations pointing at a deleted source",
        "self_relationships": "self-referencing relationships",
        "duplicate_relationship_triples": "duplicate relationship triples",
        "duplicate_codes": "duplicate record codes",
        "blank_codes": "records without a code",
        "place_cycles": "cycles in the place hierarchy",
        "birth_after_death": "people who die before they are born",
        "index_gap": "search-index documents out of step with the data",
        "stale_index_documents": "index documents for deleted records",
        "sequences_behind": "numbering sequences behind the codes in use",
        "attachments_missing_file": "attachment rows whose file is gone",
        "orphan_links:evidence": "evidence pointing at a record that is gone",
    }
    out = []
    for key, value in problems.items():
        if key.endswith(":detail") or not isinstance(value, int):
            continue
        if not value:
            continue
        label = labels.get(key, key.replace("orphan_links:", "orphaned ").replace("_", " "))
        out.append(f"{value:>6}  {label}")
    return out


def repair(conn: sqlite3.Connection, dry_run: bool = True) -> dict[str, Any]:
    """Fix the problems that can be fixed without guessing.

    Deleted: linked rows that point at records which no longer exist, plus index
    documents for records that are gone.  Bumped: numbering sequences that fell
    behind the codes in use.  Never touched: duplicate codes, hierarchy cycles and
    impossible dates — those need a human decision, so they are reported only.
    """
    before = scan(conn)

    jobs: list[tuple[str, str, str]] = []          # (label, WHERE clause, table)
    for table, (tcol, icol) in POLYMORPHIC.items():
        jobs.append((f"delete orphan {table}", _orphan_where(table, tcol, icol), table))
    jobs.append(("delete orphan relationship",
                 "NOT EXISTS (" + _branches("relationship", "entity1_type", "entity1_id") + ")"
                 " OR NOT EXISTS (" + _branches("relationship", "entity2_type", "entity2_id") + ")",
                 "relationship"))
    jobs.append(("delete dangling citation",
                 "NOT EXISTS (SELECT 1 FROM source s WHERE s.id = source_link.source_id)",
                 "source_link"))
    stale = ("entity_type <> 'relationship' AND NOT EXISTS ("
             "SELECT 1 FROM person p WHERE search_doc.entity_type='person' "
             "AND p.id=search_doc.entity_id AND p.deleted_at IS NULL"
             " UNION ALL SELECT 1 FROM institution p WHERE search_doc.entity_type='institution' "
             "AND p.id=search_doc.entity_id AND p.deleted_at IS NULL"
             " UNION ALL SELECT 1 FROM place p WHERE search_doc.entity_type='place' "
             "AND p.id=search_doc.entity_id AND p.deleted_at IS NULL"
             " UNION ALL SELECT 1 FROM event p WHERE search_doc.entity_type='event' "
             "AND p.id=search_doc.entity_id AND p.deleted_at IS NULL"
             " UNION ALL SELECT 1 FROM source p WHERE search_doc.entity_type='source' "
             "AND p.id=search_doc.entity_id AND p.deleted_at IS NULL)")
    jobs.append(("delete stale index document", stale, "search_doc"))
    jobs.append(("delete orphan relationship index document",
                 "entity_type = 'relationship' AND NOT EXISTS (SELECT 1 FROM relationship r "
                 "WHERE r.id = search_doc.entity_id AND r.deleted_at IS NULL)", "search_doc"))

    plan: dict[str, int] = {}
    for label, where, table in jobs:
        n = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])
        if n and not dry_run:
            conn.execute(f"DELETE FROM {table} WHERE {where}")
        plan[label] = plan.get(label, 0) + n

    bumps: dict[str, int] = {}
    for r in conn.execute("SELECT entity_type, prefix, next_value FROM sequence"):
        spec = ENTITIES.get(r["entity_type"])
        if spec is None:
            continue
        top = conn.execute(
            f"SELECT MAX(CAST(substr(code, instr(code,'-') + 1) AS INTEGER)) FROM {spec.table} "
            f"WHERE code LIKE ?", (r["prefix"] + "-%",)).fetchone()[0] or 0
        if top >= r["next_value"]:
            bumps[r["entity_type"]] = top + 1
    for entity_type, next_value in bumps.items():
        if not dry_run:
            conn.execute("UPDATE sequence SET next_value=? WHERE entity_type=?",
                         (next_value, entity_type))
    plan["raise sequence"] = len(bumps)

    if not dry_run:
        conn.commit()
    after = scan(conn)
    return {"dry_run": dry_run, "plan": plan, "before": before, "after": after,
            "problems_before": summary(before), "problems_after": summary(after)}


def _orphan_where(table: str, type_col: str, id_col: str) -> str:
    return "NOT EXISTS (" + _branches(table, type_col, id_col) + ")"
