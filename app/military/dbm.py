"""Military Organization — database module (unified with the registry).

The military tables live in the **same database as the registry**
(``registry.db``): one database, one connection layer, one migration ledger.
The schema arrives through the migration ledger (``015_military_org.sql``
and later files, including ``020_person_category.sql``) during
``db.init_db``; :func:`ensure` runs the same ledger lazily for callers that
use the module before boot, so importing this module never touches disk.

A separate file was deliberately rejected: the final structure is one
unified database *and* one unified application.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .. import db

_lock = threading.Lock()
_initialised = False


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    """One connection per call, the registry's house rules (WAL, FK, timeouts)."""
    return db.connect()


def _military_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'military_unit'"
    ).fetchone()
    return row is not None


def init_db(conn: sqlite3.Connection) -> None:
    """Bring a connection up to the current schema (idempotent).

    The migration ledger does the real work (002..020 — including 020's fold
    of the commander table into categorized persons); the _ensure_* helpers
    remain as backups for pre-ledger databases.
    """
    db.run_migrations(conn)
    _ensure_emblem_columns(conn)
    _ensure_link_geo_columns(conn)
    _ensure_trait_table(conn)


def _add_missing_columns(conn: sqlite3.Connection, table: str,
                         columns: list[tuple[str, str]]) -> None:
    """Idempotent ALTERs for a lazily-created table (the lazy path runs no ledger)."""
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns:
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _ensure_emblem_columns(conn: sqlite3.Connection) -> None:
    """Idempotent 017: the unit emblem columns (the lazy path runs no ledger)."""
    if not _military_present(conn):
        return
    _add_missing_columns(conn, "military_unit",
                         [("image_url", "TEXT"), ("image_alt", "TEXT")])


def _ensure_person_columns(conn: sqlite3.Connection) -> None:
    """Idempotent 020: category + military attributes on person."""
    _add_missing_columns(conn, "person", [
        ("category", "TEXT"), ("rank_title", "TEXT"), ("branch", "TEXT"),
        ("commission_date", "TEXT"), ("service_status", "TEXT"),
        ("military_biography", "TEXT")])


def _ensure_link_geo_columns(conn: sqlite3.Connection) -> None:
    """Idempotent 018/020: person category columns and own-coordinate columns."""
    if not _military_present(conn):
        return
    _ensure_person_columns(conn)
    _add_missing_columns(conn, "military_unit", [
        ("latitude", "REAL"), ("longitude", "REAL"), ("geometry_source", "TEXT")])
    _add_missing_columns(conn, "operational_deployment", [
        ("latitude", "REAL"), ("longitude", "REAL"), ("geometry_source", "TEXT")])


TRAIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS person_trait (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    person_id     INTEGER NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
    quality       TEXT NOT NULL,
    level         TEXT,
    assessed_by   TEXT,
    assessed_at   TEXT,
    evidence_note TEXT,
    source        TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    modified_at   TEXT,
    modified_by   TEXT
);
CREATE INDEX IF NOT EXISTS ix_trait_person ON person_trait(person_id);
CREATE INDEX IF NOT EXISTS ix_trait_quality ON person_trait(quality);
"""


def _ensure_trait_table(conn: sqlite3.Connection) -> None:
    """Idempotent 019/020: the person-quality table + its vocabularies."""
    if not _military_present(conn):
        return
    conn.executescript(TRAIT_TABLE_SQL)
    from . import seed
    seed.ensure_leadership_vocab(conn)


def ensure() -> None:
    """Make sure the military schema is current — once per process, lazily."""
    global _initialised
    if _initialised:
        return
    with _lock:
        if _initialised:
            return
        conn = connect()
        try:
            init_db(conn)                 # the ledger converges every world
            conn.commit()
        finally:
            conn.close()
        _initialised = True


def ready() -> bool:
    """True when the current database already carries the military tables."""
    if not Path(db.DB_PATH).exists():
        return False
    conn = connect()
    try:
        return _military_present(conn)
    finally:
        conn.close()
