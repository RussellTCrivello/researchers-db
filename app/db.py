"""
Core database helpers: connections, initialisation, numbering, full-text
indexing, normalisation and the audit trail.

The project deliberately uses a single SQLite file (WAL mode) so that the whole
registry can be copied, backed up or shipped as one artefact.  Because every
write goes through the helpers below, swapping SQLite for PostgreSQL later only
requires replacing this module (the SQL used elsewhere is standard).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SIRAJ_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("SIRAJ_DB", DATA_DIR / "registry.db"))
UPLOAD_DIR = DATA_DIR / "uploads"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def adopt_legacy_data_dir(data_dir: Path, legacy_dir: Path) -> str:
    """Bring a registry home from a pre-fix data folder. Nothing is deleted.

    An off-by-one in the launcher wrote the registry to ``app/app/data`` while
    ``db.py`` itself defaulted to ``app/data``, so a machine can end up with its
    real registry stranded in the legacy folder (or, after an empty install,
    with a fresh demo database next to it).  Rules:

    - items found in ``legacy_dir`` move over one by one, so a partially
      occupied target (e.g. an ``uploads`` folder) never blocks the registry;
      folders present on both sides are merged recursively;
    - an item that already exists at the target is never overwritten;
    - if both folders hold a ``registry.db`` nothing is moved at all — the
      caller warns and the human decides which one wins.

    Returns ``"moved"``, ``"both"`` or ``"none"``.
    """
    data_dir = Path(data_dir)
    legacy_dir = Path(legacy_dir)
    if data_dir == legacy_dir or not legacy_dir.is_dir():
        return "none"
    if (legacy_dir / "registry.db").exists() and (data_dir / "registry.db").exists():
        return "both"

    def _adopt(src: Path, dst: Path) -> bool:
        moved_any = False
        for item in sorted(src.iterdir()):
            target = dst / item.name
            if target.exists():
                if item.is_dir() and target.is_dir():
                    moved_any |= _adopt(item, target)
                continue
            try:
                dst.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(target))
                moved_any = True
            except OSError as exc:  # locked file, permissions — warn, never delete
                print(f"[siraj] WARNING: could not move {item} to {target}: {exc}")
        return moved_any

    return "moved" if _adopt(legacy_dir, data_dir) else "none"


_adopt_status = adopt_legacy_data_dir(DATA_DIR, BASE_DIR / "app" / "data")
if _adopt_status == "moved":
    print(f"[siraj] registry adopted into {DATA_DIR}")
elif _adopt_status == "both":
    print(f"[siraj] WARNING: a second registry exists at {BASE_DIR / 'app' / 'data'}; "
          f"using the one in {DATA_DIR}")

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# cross-platform filesystem helpers
# ---------------------------------------------------------------------------
def safe_unlink(path: Path, retries: int = 5, delay: float = 0.12) -> bool:
    """Delete a file, tolerating Windows' "file is in use" races.

    On Windows an open handle (antivirus scanner, an HTTP response still
    streaming, a backup snapshot being closed) makes ``unlink`` raise
    ``PermissionError`` for a few milliseconds; retrying is the portable fix.
    """
    import time

    path = Path(path)
    for attempt in range(retries):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except (PermissionError, OSError):
            if attempt == retries - 1:
                return False
            time.sleep(delay * (attempt + 1))
    return False


def atomic_write(path: Path, data: bytes) -> Path:
    """Write a file so that readers never observe a half-written document."""
    import os
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)          # atomic on NTFS, APFS and ext4
    finally:
        safe_unlink(Path(tmp))
    return path


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------
def now() -> str:
    """UTC timestamp, ISO-8601 with Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may run async endpoints on the event loop
    # thread while the generator dependency was resolved in a worker thread.
    # Each request still owns exactly one connection, so this is safe.
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    _register_functions(conn)
    return conn


def _register_functions(conn: sqlite3.Connection) -> None:
    """SQL helpers used by the filter builder (Arabic-aware LIKE, year extraction)."""
    from .schemas import to_timestamp, year_of

    conn.create_function("norm", 1, lambda v: normalize(v) if v is not None else "",
                         deterministic=True)
    conn.create_function("year_of", 1, year_of, deterministic=True)
    # one timeline for every accepted date form, so ranges and sorting work
    # whether the value is "1912", "1912-04-12" or "1912-04-12T14:30"
    conn.create_function("ts_of", 1, to_timestamp, deterministic=True)


def get_conn() -> Iterable[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def json_load(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# initialisation
# ---------------------------------------------------------------------------
MIGRATIONS_DIR = BASE_DIR / "migrations"


# The audit trail is a ledger: rows may be added, and old rows may be pruned by
# an explicit retention policy, but a written entry cannot be rewritten and a
# recent one cannot disappear.  These live as triggers rather than code so that
# the guarantee holds for any writer — the API, a script, or sqlite3 on the file.
AUDIT_GUARDS = (
    """CREATE TRIGGER IF NOT EXISTS change_log_content_immutable
       BEFORE UPDATE ON change_log
       FOR EACH ROW
       WHEN OLD.entity_type IS NOT NEW.entity_type
         OR OLD.entity_id   IS NOT NEW.entity_id
         OR OLD.entity_code IS NOT NEW.entity_code
         OR OLD.action      IS NOT NEW.action
         OR OLD.field_key   IS NOT NEW.field_key
         OR OLD.old_value   IS NOT NEW.old_value
         OR OLD.new_value   IS NOT NEW.new_value
         OR OLD.actor       IS NOT NEW.actor
         OR OLD.notes       IS NOT NEW.notes
         OR OLD.changed_at  IS NOT NEW.changed_at
         OR OLD.tx_id       IS NOT NEW.tx_id
       BEGIN
         SELECT RAISE(ABORT, 'change_log is append-only: an audit entry cannot be rewritten');
       END""",
    """CREATE TRIGGER IF NOT EXISTS change_log_recent_delete_guard
       BEFORE DELETE ON change_log
       FOR EACH ROW
       WHEN OLD.changed_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-30 days')
       BEGIN
         SELECT RAISE(ABORT, 'change_log is append-only: recent audit entries cannot be deleted');
       END""",
)


def ensure_audit_guards(conn: sqlite3.Connection) -> None:
    """Install the append-only guarantees on `change_log` (idempotent)."""
    for statement in AUDIT_GUARDS:
        conn.execute(statement)


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every .sql file in app/migrations that has not been applied yet.

    Each file runs once, is recorded with its checksum, and is allowed to fail
    on "duplicate column" / "already exists" errors so that a database created
    from the current schema.sql can adopt the migration history safely.
    """
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migration (
        filename    TEXT PRIMARY KEY,
        checksum    TEXT,
        applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        ok          INTEGER NOT NULL DEFAULT 1,
        note        TEXT)""")
    applied = {r["filename"] for r in conn.execute("SELECT filename FROM schema_migration")}
    done = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        ok, note = 1, None
        # PRAGMA statements (e.g. 020's foreign_keys toggle) only take effect
        # on an idle connection, so the runner commits around them.
        pragma_start = re.compile(r"(?is)^(?:--[^\n]*\n|/\*.*?\*/|\s)*pragma\b")
        for statement in split_sql_statements(sql):
            is_pragma = pragma_start.match(statement) is not None
            if is_pragma:
                conn.commit()
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    note = f"skipped: {exc}"
                    continue
                ok, note = 0, str(exc)
                raise
            if is_pragma:
                conn.commit()
        conn.execute(
            "INSERT OR REPLACE INTO schema_migration (filename, checksum, ok, note) "
            "VALUES (?,?,?,?)", (path.name, checksum, ok, note))
        done.append(path.name)
    ensure_audit_guards(conn)
    conn.commit()
    return done


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into complete statements.

    Unlike a naive ``split(";")`` this respects semicolons inside ``--``
    comments and string literals: sqlite3's own parser decides where each
    statement ends (via :func:`sqlite3.complete_statement`), and comment-only
    fragments are dropped.
    """
    statements: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines(keepends=True):
        buf.append(line)
        candidate = "".join(buf)
        if sqlite3.complete_statement(candidate):
            stripped = "\n".join(
                ln for ln in candidate.splitlines()
                if not ln.strip().startswith("--")).strip()
            if stripped:
                statements.append(candidate.strip())
            buf = []
    tail = "\n".join(ln for ln in "".join(buf).splitlines()
                     if not ln.strip().startswith("--")).strip()
    if tail:
        statements.append(tail)
    return statements


def init_db(seed_demo: bool = False) -> None:
    from . import seed  # local import to avoid a cycle

    fresh = not DB_PATH.exists()
    conn = connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        applied = run_migrations(conn)
        if applied:
            print(f"[siraj] applied migrations: {', '.join(applied)}")
        seed.seed_reference_data(conn)          # idempotent (INSERT OR IGNORE)
        if seed_demo:
            seed.seed_demo(conn)                # idempotent (skips if data exists)
        conn.commit()
    finally:
        conn.close()
    if fresh:
        print(f"[siraj] created database at {DB_PATH}")


# ---------------------------------------------------------------------------
# Arabic / Latin normalisation for search
# ---------------------------------------------------------------------------
_AR_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_AR_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ا": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
    "ﻻ": "لا", "ﻷ": "لا",
})


def normalize(text: Any) -> str:
    """Fold Arabic variants and strip Latin accents so that search is forgiving."""
    if text is None:
        return ""
    s = str(text)
    s = unicodedata.normalize("NFKC", s)
    s = _AR_DIACRITICS.sub("", s)
    s = s.translate(_AR_FOLD)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[’'`´ـ]", "", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip().lower()
    # Fold the Arabic definite article per token so "الموصل" and "موصل" match.
    return " ".join(_strip_article(tok) for tok in s.split(" "))


def _strip_article(token: str) -> str:
    """Drop a leading definite article from Arabic tokens of a useful length."""
    if len(token) > 5 and token.startswith("ال"):
        return token[2:]
    return token


def fts_query(q: str) -> str:
    """Turn a user query into a safe FTS5 prefix query on normalised tokens."""
    tokens = [t for t in normalize(q).replace("-", " ").split() if t]
    if not tokens:
        return ""
    out = []
    for t in tokens:
        t = t.replace('"', "")
        out.append(f'"{t}"*')
    return " AND ".join(out)


# ---------------------------------------------------------------------------
# numbering
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE = "{prefix}{sep}{number}{suffix}"


def ensure_sequence(conn: sqlite3.Connection, entity_type: str, prefix: str = "") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sequence (entity_type, prefix, padding, next_value)
           VALUES (?,?,?,1)""",
        (entity_type, prefix, 4),
    )


def format_code(row: sqlite3.Row | dict, number: int) -> str:
    get = row.get if isinstance(row, dict) else (lambda k, d=None: row[k])
    prefix = (get("prefix") or "") + ""
    sep = (get("separator") if get("separator") is not None else "-")
    suffix = (get("suffix") or "") + ""
    padding = int(get("padding") or 4)
    template = get("template") or DEFAULT_TEMPLATE
    body = f"{number:0{padding}d}"
    return (template
            .replace("{prefix}", prefix)
            .replace("{sep}", sep)
            .replace("{number}", body)
            .replace("{suffix}", suffix)
            .strip())


def peek_next_code(conn: sqlite3.Connection, entity_type: str) -> str:
    """The code a new record *would* get — without allocating it.

    It must agree with `next_code()`, which skips codes that already exist
    (manual inserts, imports, a record created with an explicit code).  A
    preview that offers a taken code makes the form fail on save with a 409.
    """
    row = conn.execute("SELECT * FROM sequence WHERE entity_type=?", (entity_type,)).fetchone()
    if row is None:
        return ""
    number = int(row["next_value"])
    table = ENTITY_TABLES.get(entity_type)
    if table:
        for _ in range(10_000):
            if not conn.execute(f"SELECT 1 FROM {table} WHERE code=?",
                                (format_code(row, number),)).fetchone():
                break
            number += 1
    return format_code(row, number)


_CODE_TAIL = re.compile(r"(\d+)(?!.*\d)")


def sync_sequence(conn: sqlite3.Connection, entity_type: str, code: str | None) -> None:
    """Keep the numbering sequence ahead of a code that was supplied by hand.

    Without this, a client that previews a code and then sends it back (the
    interface does exactly that) leaves the sequence standing still, and the
    *next* record is offered the same number — a 409 on save.
    """
    if not code:
        return
    row = conn.execute("SELECT * FROM sequence WHERE entity_type=?", (entity_type,)).fetchone()
    if row is None:
        return
    match = _CODE_TAIL.search(str(code))
    if not match:
        return
    number = int(match.group(1))
    if number >= int(row["next_value"]):
        conn.execute("UPDATE sequence SET next_value=? WHERE entity_type=?",
                     (number + 1, entity_type))


def next_code(conn: sqlite3.Connection, entity_type: str) -> str:
    """Allocate the next code for an entity type (call inside the write txn)."""
    ensure_sequence(conn, entity_type)
    row = conn.execute("SELECT * FROM sequence WHERE entity_type=?", (entity_type,)).fetchone()
    _maybe_reset(conn, row)
    row = conn.execute("SELECT * FROM sequence WHERE entity_type=?", (entity_type,)).fetchone()
    number = int(row["next_value"])
    # skip codes that already exist (manual inserts / imports)
    table = ENTITY_TABLES.get(entity_type)
    candidate = format_code(row, number)
    if table:
        while conn.execute(f"SELECT 1 FROM {table} WHERE code=?", (candidate,)).fetchone():
            number += 1
            candidate = format_code(row, number)
    conn.execute("UPDATE sequence SET next_value=? WHERE entity_type=?", (number + 1, entity_type))
    return candidate


def _maybe_reset(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    policy = row["reset_policy"]
    if policy == "never":
        return
    today = now()
    stamp = today[:7] if policy == "monthly" else today[:4]
    if row["last_reset"] != stamp:
        conn.execute(
            "UPDATE sequence SET next_value=1, last_reset=? WHERE entity_type=?",
            (stamp, row["entity_type"]),
        )


ENTITY_TABLES = {
    "person": "person",
    "place": "place",
    "institution": "institution",
    "event": "event",
    "relationship": "relationship",
    "source": "source",
}


# ---------------------------------------------------------------------------
# audit trail
# ---------------------------------------------------------------------------
def log_change(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int | None,
    action: str,
    actor: str | None = None,
    entity_code: str | None = None,
    field_key: str | None = None,
    field_label: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: str | None = None,
    source_id: int | None = None,
    reviewed_by: str | None = None,
    notes: str | None = None,
    tx_id: str | None = None,
) -> str:
    tx_id = tx_id or uuid.uuid4().hex
    conn.execute(
        """INSERT INTO change_log (tx_id, entity_type, entity_id, entity_code, action,
              field_key, field_label, old_value, new_value, reason, source_id,
              actor, reviewed_by, notes, changed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tx_id, entity_type, entity_id, entity_code, action, field_key, field_label,
         None if old_value is None else str(old_value),
         None if new_value is None else str(new_value),
         reason, source_id, actor, reviewed_by, notes, now()),
    )
    return tx_id


def diff_and_log(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    entity_code: str | None,
    before: dict[str, Any],
    after: dict[str, Any],
    labels: dict[str, str] | None = None,
    actor: str | None = None,
    reason: str | None = None,
    source_id: int | None = None,
    tx_id: str | None = None,
) -> list[dict[str, Any]]:
    """Write one change_log row per changed field; returns the diff list."""
    labels = labels or {}
    changed = []
    for key, new in after.items():
        old = before.get(key)
        if isinstance(old, (int, float)) or isinstance(new, (int, float)):
            same = (old == new) or (old is None and new in (None, ""))
        else:
            same = (old or None) == (new or None)
        if not same:
            changed.append({"field": key, "old": old, "new": new})
            log_change(
                conn, entity_type=entity_type, entity_id=entity_id, action="update",
                actor=actor, entity_code=entity_code, field_key=key,
                field_label=labels.get(key, key), old_value=old, new_value=new,
                reason=reason, source_id=source_id, tx_id=tx_id,
            )
    return changed


# ---------------------------------------------------------------------------
# full-text index maintenance
# ---------------------------------------------------------------------------
def reindex(conn: sqlite3.Connection, entity_type: str, entity_id: int,
            title: str, body_parts: Sequence[Any], code: str | None = None) -> None:
    conn.execute(
        "DELETE FROM search_doc WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id),
    )
    body = " · ".join(str(p) for p in body_parts if p)
    title = title or ""
    conn.execute(
        """INSERT INTO search_doc (entity_type, entity_id, code, title, body, norm)
           VALUES (?,?,?,?,?,?)""",
        (entity_type, entity_id, code or "", title, body,
         " ".join([normalize(title), normalize(body), normalize(code)])),
    )


def drop_from_index(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> None:
    conn.execute(
        "DELETE FROM search_doc WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id),
    )


def rebuild_index(conn: sqlite3.Connection) -> int:
    from .schemas import ENTITIES  # local import (schemas imports nothing from db)

    conn.execute("DELETE FROM search_doc")
    total = 0
    for key, spec in ENTITIES.items():
        docs = spec.build_index_rows(conn)
        payload = []
        for d in docs:
            body = " · ".join(str(p) for p in d["body"] if p)
            title = d["title"] or ""
            code = d.get("code") or ""
            payload.append((key, d["id"], code, title, body,
                            " ".join([normalize(title), normalize(body), normalize(code)])))
        if payload:
            conn.executemany(
                """INSERT INTO search_doc (entity_type, entity_id, code, title, body, norm)
                   VALUES (?,?,?,?,?,?)""", payload)
            total += len(payload)
    return total
