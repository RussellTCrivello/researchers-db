"""Military Organization — database module.

A self-contained SQLite file (``military.db``) inside the project's data
directory, deliberately separate from the SIRAJ registry: the two systems
share a house, not a table space.  The schema implements the twelve entities
of the design record (§7) with generated surrogate keys plus generated
document names from the naming series (Appendix B).

Initialisation is lazy and idempotent: the file is created on first use, so
importing this module never touches disk and SIRAJ boots exactly as before.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..db import DATA_DIR

MIL_DB_PATH = Path(os.environ.get("SIRAJ_MILITARY_DB", DATA_DIR / "military.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mil_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS region (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    docname      TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    region_type  TEXT NOT NULL DEFAULT 'Region',
    parent_id    INTEGER REFERENCES region(id) ON DELETE RESTRICT,
    country      TEXT,
    description  TEXT,
    path         TEXT NOT NULL DEFAULT '',
    depth        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    modified_at  TEXT,
    modified_by  TEXT
);

CREATE TABLE IF NOT EXISTS division (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    docname        TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    region_id      INTEGER NOT NULL REFERENCES region(id) ON DELETE RESTRICT,
    division_type  TEXT,
    formation_date TEXT,
    headquarters   TEXT,
    description    TEXT,
    created_at     TEXT NOT NULL,
    created_by     TEXT NOT NULL,
    modified_at    TEXT,
    modified_by    TEXT
);

CREATE TABLE IF NOT EXISTS classification (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    docname        TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL UNIQUE,
    category       TEXT,
    readiness_tier TEXT,
    description    TEXT,
    created_at     TEXT NOT NULL,
    created_by     TEXT NOT NULL,
    modified_at    TEXT,
    modified_by    TEXT
);

CREATE TABLE IF NOT EXISTS commander (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    docname          TEXT NOT NULL UNIQUE,
    full_name        TEXT NOT NULL,
    rank_title       TEXT,
    branch           TEXT,
    commission_date  TEXT,
    status           TEXT NOT NULL DEFAULT 'Active',
    biography        TEXT,
    created_at       TEXT NOT NULL,
    created_by       TEXT NOT NULL,
    modified_at      TEXT,
    modified_by      TEXT
);

CREATE TABLE IF NOT EXISTS military_unit (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    docname               TEXT NOT NULL UNIQUE,
    code                  TEXT UNIQUE,
    name                  TEXT NOT NULL,
    echelon               TEXT NOT NULL DEFAULT 'Brigade',
    parent_id             INTEGER REFERENCES military_unit(id) ON DELETE RESTRICT,
    classification_id     INTEGER REFERENCES classification(id) ON DELETE RESTRICT,
    role                  TEXT,
    status                TEXT NOT NULL DEFAULT 'Active',
    commander_id          INTEGER REFERENCES commander(id) ON DELETE RESTRICT,
    current_deployment_id INTEGER,
    direct_personnel      INTEGER NOT NULL DEFAULT 0 CHECK (direct_personnel >= 0),
    division_id           INTEGER REFERENCES division(id) ON DELETE RESTRICT,
    region_id             INTEGER REFERENCES region(id) ON DELETE RESTRICT,
    formation_date        TEXT,
    headquarters          TEXT,
    notes                 TEXT,
    path                  TEXT NOT NULL DEFAULT '',
    depth                 INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    created_by            TEXT NOT NULL,
    modified_at           TEXT,
    modified_by           TEXT
);

CREATE TABLE IF NOT EXISTS operational_deployment (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    docname             TEXT NOT NULL UNIQUE,
    unit_id             INTEGER NOT NULL REFERENCES military_unit(id) ON DELETE RESTRICT,
    name                TEXT NOT NULL,
    deployment_type     TEXT,
    start_date          TEXT NOT NULL,
    end_date            TEXT,
    status              TEXT NOT NULL DEFAULT 'Planned',
    is_current          INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    location            TEXT,
    area_of_operations  TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL,
    created_by          TEXT NOT NULL,
    modified_at         TEXT,
    modified_by         TEXT
);

CREATE TABLE IF NOT EXISTS mission (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    unit_id       INTEGER NOT NULL REFERENCES military_unit(id) ON DELETE RESTRICT,
    name          TEXT NOT NULL,
    mission_type  TEXT,
    deployment_id INTEGER REFERENCES operational_deployment(id) ON DELETE RESTRICT,
    start_date    TEXT NOT NULL,
    end_date      TEXT,
    status        TEXT NOT NULL DEFAULT 'Planned',
    area          TEXT,
    description   TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    modified_at   TEXT,
    modified_by   TEXT
);

CREATE TABLE IF NOT EXISTS armament (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    docname         TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    category        TEXT,
    specification   TEXT,
    origin_country  TEXT,
    description     TEXT,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    modified_at     TEXT,
    modified_by     TEXT
);

CREATE TABLE IF NOT EXISTS unit_armament (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    docname          TEXT NOT NULL UNIQUE,
    unit_id          INTEGER NOT NULL REFERENCES military_unit(id) ON DELETE RESTRICT,
    armament_id      INTEGER NOT NULL REFERENCES armament(id) ON DELETE RESTRICT,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    condition        TEXT NOT NULL DEFAULT 'Serviceable',
    acquisition_year INTEGER,
    notes            TEXT,
    created_at       TEXT NOT NULL,
    created_by       TEXT NOT NULL,
    modified_at      TEXT,
    modified_by      TEXT,
    UNIQUE (unit_id, armament_id)
);

CREATE TABLE IF NOT EXISTS training (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    docname           TEXT NOT NULL UNIQUE,
    unit_id           INTEGER NOT NULL REFERENCES military_unit(id) ON DELETE RESTRICT,
    exercise_name     TEXT NOT NULL,
    training_type     TEXT,
    start_date        TEXT NOT NULL,
    end_date          TEXT NOT NULL,
    duration_days     INTEGER NOT NULL CHECK (duration_days >= 1),
    participant_count INTEGER NOT NULL CHECK (participant_count >= 0),
    lead_trainer      TEXT,
    assessment        TEXT,
    location          TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL,
    created_by        TEXT NOT NULL,
    modified_at       TEXT,
    modified_by       TEXT
);

CREATE TABLE IF NOT EXISTS command_assignment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    unit_id       INTEGER NOT NULL REFERENCES military_unit(id) ON DELETE RESTRICT,
    commander_id  INTEGER NOT NULL REFERENCES commander(id) ON DELETE RESTRICT,
    role          TEXT NOT NULL DEFAULT 'Commanding Officer',
    assigned_date TEXT NOT NULL,
    relieved_date TEXT,
    is_current    INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    notes         TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    modified_at   TEXT,
    modified_by   TEXT
);

CREATE TABLE IF NOT EXISTS note (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    docname     TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    note_text   TEXT NOT NULL,
    author      TEXT NOT NULL,
    note_at     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    modified_at TEXT,
    modified_by TEXT
);

-- naming series (Appendix B): options are data; counters are per partition
CREATE TABLE IF NOT EXISTS naming_series_option (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity       TEXT NOT NULL,
    label        TEXT NOT NULL UNIQUE,
    prefix       TEXT NOT NULL,
    year_token   INTEGER NOT NULL DEFAULT 0,
    segment_field TEXT,
    width        INTEGER NOT NULL DEFAULT 5,
    is_default   INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS naming_counter (
    option_id     INTEGER NOT NULL REFERENCES naming_series_option(id) ON DELETE CASCADE,
    partition     TEXT NOT NULL DEFAULT '',
    current_value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (option_id, partition)
);

CREATE TABLE IF NOT EXISTS naming_adjustment_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    option_id  INTEGER NOT NULL,
    partition  TEXT NOT NULL,
    old_value  INTEGER NOT NULL,
    new_value  INTEGER NOT NULL,
    actor      TEXT NOT NULL,
    at         TEXT NOT NULL
);

-- append-only audit trail (§12.3)
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    record_id INTEGER,
    docname   TEXT,
    summary   TEXT,
    old_json  TEXT,
    new_json  TEXT,
    at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_region_parent     ON region(parent_id);
CREATE INDEX IF NOT EXISTS idx_region_path       ON region(path);
CREATE INDEX IF NOT EXISTS idx_unit_parent       ON military_unit(parent_id);
CREATE INDEX IF NOT EXISTS idx_unit_path         ON military_unit(path);
CREATE INDEX IF NOT EXISTS idx_unit_status       ON military_unit(status);
CREATE INDEX IF NOT EXISTS idx_deployment_unit   ON operational_deployment(unit_id);
CREATE INDEX IF NOT EXISTS idx_deployment_dates  ON operational_deployment(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_mission_unit      ON mission(unit_id);
CREATE INDEX IF NOT EXISTS idx_mission_deploy    ON mission(deployment_id);
CREATE INDEX IF NOT EXISTS idx_holding_unit      ON unit_armament(unit_id);
CREATE INDEX IF NOT EXISTS idx_holding_arm       ON unit_armament(armament_id);
CREATE INDEX IF NOT EXISTS idx_training_unit     ON training(unit_id);
CREATE INDEX IF NOT EXISTS idx_assignment_unit   ON command_assignment(unit_id);
CREATE INDEX IF NOT EXISTS idx_assignment_cmd    ON command_assignment(commander_id);
CREATE INDEX IF NOT EXISTS idx_note_target       ON note(entity_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_at          ON audit_log(at);
"""

_lock = threading.Lock()
_initialised = False


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    """One connection per call, same house rules as the SIRAJ registry."""
    MIL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MIL_DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def ensure() -> None:
    """Create the schema once per process, lazily."""
    global _initialised
    if _initialised:
        return
    with _lock:
        if _initialised:
            return
        conn = connect()
        try:
            init_db(conn)
            conn.commit()
        finally:
            conn.close()
        _initialised = True


def ready() -> bool:
    """True when the military database file already exists (used by `verify`)."""
    return MIL_DB_PATH.exists()
