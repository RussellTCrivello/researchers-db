"""Military Organization — database module (unified with the registry).

The military tables live in the **same database as the registry**
(``registry.db``): one database, one connection layer, one migration ledger.
The schema arrives as migration ``015_military_org.sql`` (additive,
idempotent) during ``db.init_db``; :func:`ensure` applies the same migration
text lazily for callers that use the module before boot, so importing this
module never touches disk.

A separate file was deliberately rejected: the final structure is one
unified database *and* one unified application.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .. import db
from ..db import BASE_DIR

MIGRATION_FILE = BASE_DIR / "migrations" / "015_military_org.sql"

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
    """Apply the military migration to a connection (idempotent)."""
    conn.executescript(MIGRATION_FILE.read_text(encoding="utf-8"))
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


def _ensure_link_geo_columns(conn: sqlite3.Connection) -> None:
    """Idempotent 018: commander↔person link and own-coordinate columns."""
    if not _military_present(conn):
        return
    _add_missing_columns(conn, "commander", [("person_id", "INTEGER")])
    _add_missing_columns(conn, "military_unit", [
        ("latitude", "REAL"), ("longitude", "REAL"), ("geometry_source", "TEXT")])
    _add_missing_columns(conn, "operational_deployment", [
        ("latitude", "REAL"), ("longitude", "REAL"), ("geometry_source", "TEXT")])


TRAIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS commander_trait (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    commander_id  INTEGER NOT NULL REFERENCES commander(id) ON DELETE RESTRICT,
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
CREATE INDEX IF NOT EXISTS ix_trait_commander ON commander_trait(commander_id);
CREATE INDEX IF NOT EXISTS ix_trait_quality ON commander_trait(quality);
"""


def _ensure_trait_table(conn: sqlite3.Connection) -> None:
    """Idempotent 019: the leadership-quality table + its vocabularies."""
    if not _military_present(conn):
        return
    conn.executescript(TRAIT_TABLE_SQL)
    from . import seed
    seed.ensure_leadership_vocab(conn)


def ensure() -> None:
    """Make sure the military tables exist — once per process, lazily."""
    global _initialised
    if _initialised:
        return
    with _lock:
        if _initialised:
            return
        conn = connect()
        try:
            if not _military_present(conn):
                init_db(conn)
            _ensure_emblem_columns(conn)   # pre-017 databases gain the columns
            _ensure_link_geo_columns(conn)  # pre-018 databases gain the columns
            _ensure_trait_table(conn)       # pre-019 databases gain the table
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
