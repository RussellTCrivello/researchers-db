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


def _ensure_emblem_columns(conn: sqlite3.Connection) -> None:
    """Idempotent 017: the unit emblem columns (the lazy path runs no ledger)."""
    if not _military_present(conn):
        return
    have = {r["name"] for r in conn.execute("PRAGMA table_info(military_unit)")}
    for name in ("image_url", "image_alt"):
        if name not in have:
            conn.execute(f"ALTER TABLE military_unit ADD COLUMN {name} TEXT")


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
