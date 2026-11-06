"""
SIRAJ · permanent tile downloads for offline viewing.

The browse cache remembers tiles the map has already seen and evicts them when
it grows large; that is memory, not storage. This module is the store that
*keeps*: a researcher marks a region and the map types they need, the engine
pulls those tiles once from the provider's public tile service, and every later
view — with no network — draws from the store.

Design rules:

* **One job is one provider over one box and zoom range.**  A "download all map
  types" request creates one job per chosen provider; each pauses, resumes and
  fails on its own, so a flaky network never loses the finished ones.
* **Resumable.**  Tiles already stored are skipped; pause and resume walk the
  same deterministic order (zoom, x, y).
* **Polite.**  A configurable delay between fetches and a hard cap on tiles per
  job (`map.download_*` settings).  Providers whose published terms forbid bulk
  retrieval (OpenStreetMap's tile usage policy) are refused with the reason
  rather than quietly scraped — the offline vector and street packs already
  cover those map types with no third party at all.
* **Registry-free.**  The store lives at ``app/data/map_downloads.sqlite``
  (git-ignored, personal).  It holds cartography only, never research records.

Serving is a two-line change in the tile endpoint: this store is consulted
before the browse cache, so downloaded tiles answer offline under the very URLs
the map already uses.
"""
from __future__ import annotations

import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from . import browse_cache, providers

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "map_downloads.sqlite"

TILE_TABLE = """
CREATE TABLE IF NOT EXISTS tile (
  provider TEXT NOT NULL,
  src      TEXT NOT NULL DEFAULT 'base',
  z INTEGER NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,
  data  BLOB NOT NULL,
  ctype TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (provider, src, z, x, y)
) WITHOUT ROWID
"""

JOB_TABLE = """
CREATE TABLE IF NOT EXISTS job (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name     TEXT NOT NULL,
  provider TEXT NOT NULL,
  src      TEXT NOT NULL DEFAULT 'base',
  minzoom  INTEGER NOT NULL,
  maxzoom  INTEGER NOT NULL,
  west REAL NOT NULL, south REAL NOT NULL, east REAL NOT NULL, north REAL NOT NULL,
  status   TEXT NOT NULL DEFAULT 'queued',
  total    INTEGER NOT NULL DEFAULT 0,
  done     INTEGER NOT NULL DEFAULT 0,
  skipped  INTEGER NOT NULL DEFAULT 0,
  failed   INTEGER NOT NULL DEFAULT 0,
  error    TEXT NOT NULL DEFAULT '',
  delay_ms INTEGER NOT NULL DEFAULT 250,
  max_tiles INTEGER NOT NULL DEFAULT 25000,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

GIVE_UP_AFTER = 25          # consecutive fetch failures → the network is gone


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.execute(TILE_TABLE)
    conn.execute(JOB_TABLE)
    return conn


def available() -> bool:
    return DB_PATH.is_file()


def stats() -> dict[str, Any]:
    conn = _connect()
    try:
        tiles = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(data)), 0) AS b "
                             "FROM tile").fetchone()
        by_provider = [dict(r) for r in conn.execute(
            "SELECT provider, COUNT(*) AS tiles, SUM(LENGTH(data)) AS bytes "
            "FROM tile GROUP BY provider ORDER BY provider")]
        jobs = conn.execute("SELECT status, COUNT(*) AS n FROM job GROUP BY status").fetchall()
        return {
            "tiles": tiles["n"],
            "bytes": tiles["b"],
            "by_provider": by_provider,
            "jobs": {r["status"]: r["n"] for r in jobs},
            "path": str(DB_PATH),
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# tile maths — how many, and in which order
# --------------------------------------------------------------------------- #
def tiles_in(west: float, south: float, east: float, north: float,
             zmin: int, zmax: int) -> Iterator[tuple[int, int, int]]:
    """Every slippy tile covering the box at the given zooms, zoom-major."""
    import math

    def ty(lat: float, z: int) -> int:
        lat = max(-85.0511287798066, min(85.0511287798066, lat))
        siny = math.sin(math.radians(lat))
        yy = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi))
        return max(0, min(2 ** z - 1, int(yy * 2 ** z)))

    def tx(lon: float, z: int) -> int:
        return max(0, min(2 ** z - 1, int((lon + 180.0) / 360.0 * 2 ** z)))

    for z in range(zmin, zmax + 1):
        for x in range(tx(west, z), tx(east, z) + 1):
            for y in range(ty(north, z), ty(south, z) + 1):
                yield (z, x, y)


def count_tiles(west: float, south: float, east: float, north: float,
                zmin: int, zmax: int) -> int:
    return sum(1 for _ in tiles_in(west, south, east, north, zmin, zmax))


# --------------------------------------------------------------------------- #
# stored tiles — what the serve path consults first
# --------------------------------------------------------------------------- #
def get_tile(provider: str, src: str, z: int, x: int, y: int) -> tuple[bytes, str] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data, ctype FROM tile WHERE provider=? AND src=? AND z=? AND x=? AND y=?",
            (provider, src or "base", z, x, y)).fetchone()
        return (row["data"], row["ctype"]) if row else None
    finally:
        conn.close()


def put_tile(conn: sqlite3.Connection, provider: str, src: str,
             z: int, x: int, y: int, data: bytes, ctype: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tile (provider, src, z, x, y, data, ctype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (provider, src or "base", z, x, y, data, ctype or ""))
    conn.commit()


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #
def _job_public(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["bbox"] = {"w": d.pop("west"), "s": d.pop("south"),
                 "e": d.pop("east"), "n": d.pop("north")}
    return d


def list_jobs() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        return [_job_public(r) for r in conn.execute(
            "SELECT * FROM job ORDER BY id DESC LIMIT 100")]
    finally:
        conn.close()


def get_job(job_id: int) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
        return _job_public(row) if row else None
    finally:
        conn.close()


def create_job(name: str, provider_id: str, west: float, south: float,
               east: float, north: float, minzoom: int, maxzoom: int,
               src: str = "base", delay_ms: int = 250, max_tiles: int = 25000) -> dict[str, Any]:
    prov = providers.PROVIDERS.get(provider_id)
    if prov is None:
        raise LookupError(f"unknown provider: {provider_id}")
    if prov.get("kind", "").startswith("vector"):
        raise ValueError("this map type ships with the application — "
                         "the offline packs already store it permanently")
    if not prov.get("downloadable", False):
        raise ValueError(prov.get("download_note_en")
                         or "the provider's terms do not permit bulk retrieval")
    if minzoom < 0 or maxzoom > 22 or minzoom > maxzoom:
        raise ValueError("invalid zoom range")
    total = count_tiles(west, south, east, north, minzoom, maxzoom)
    if total > max_tiles:
        raise ValueError(f"the request covers {total} tiles — the cap is {max_tiles}")
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO job (name, provider, src, minzoom, maxzoom, west, south, "
            "east, north, status, total, delay_ms, max_tiles) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
            (name or provider_id, provider_id, src or "base", minzoom, maxzoom,
             west, south, east, north, total, delay_ms, max_tiles))
        conn.commit()
        job_id = cur.lastrowid
    finally:
        conn.close()
    ensure_worker()
    _queue.put(job_id)
    return get_job(job_id)  # type: ignore[return-value]


def _set_status(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn = _connect()
    try:
        conn.execute(f"UPDATE job SET {cols}, updated_at=datetime('now') WHERE id=?",
                     (*fields.values(), job_id))
        conn.commit()
    finally:
        conn.close()


def pause_job(job_id: int) -> dict[str, Any] | None:
    job = get_job(job_id)
    if job and job["status"] in ("queued", "running"):
        _set_status(job_id, status="paused")
    return get_job(job_id)


def resume_job(job_id: int) -> dict[str, Any] | None:
    job = get_job(job_id)
    if job and job["status"] in ("paused", "failed"):
        _set_status(job_id, status="queued", error="")
        ensure_worker()
        _queue.put(job_id)
    return get_job(job_id)


def cancel_job(job_id: int) -> dict[str, Any] | None:
    job = get_job(job_id)
    if job and job["status"] not in ("done", "canceled"):
        _set_status(job_id, status="canceled")
    return get_job(job_id)


def delete_job(job_id: int, purge: bool = False) -> int:
    job = get_job(job_id)
    if not job:
        return 0
    if job["status"] in ("queued", "running"):
        _set_status(job_id, status="canceled")
    conn = _connect()
    try:
        if purge:
            conn.execute("DELETE FROM tile WHERE provider=? AND src=?",
                         (job["provider"], job["src"]))
        conn.execute("DELETE FROM job WHERE id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()
    return 1


# --------------------------------------------------------------------------- #
# the worker — one polite fetcher thread
# --------------------------------------------------------------------------- #
_queue: queue.Queue[int] = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_work, name="map-downloads", daemon=True)
        _worker.start()


def _work() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run_job(job_id)
        except Exception as exc:                       # never kill the worker
            _set_status(job_id, status="failed", error=str(exc)[:300])
        finally:
            _queue.task_done()


def _run_job(job_id: int) -> None:
    job = get_job(job_id)
    if not job or job["status"] not in ("queued", "running"):
        return
    _set_status(job_id, status="running", error="")
    conn = _connect()
    try:
        consecutive = 0
        for z, x, y in tiles_in(job["bbox"]["w"], job["bbox"]["s"],
                                job["bbox"]["e"], job["bbox"]["n"],
                                job["minzoom"], job["maxzoom"]):
            fresh = get_job(job_id)
            if not fresh or fresh["status"] in ("paused", "canceled"):
                return
            have = conn.execute(
                "SELECT 1 FROM tile WHERE provider=? AND src=? AND z=? AND x=? AND y=?",
                (job["provider"], job["src"], z, x, y)).fetchone()
            if have:
                _set_status(job_id, skipped=fresh["skipped"] + 1)
                continue
            try:
                url = browse_cache.resolve_upstream(job["provider"], job["src"], z, x, y)
                if not url:
                    raise LookupError("the provider has no tile template")
                data, ctype = browse_cache.fetch_upstream(url)
                put_tile(conn, job["provider"], job["src"], z, x, y, data, ctype)
                consecutive = 0
                fresh = get_job(job_id)
                _set_status(job_id, done=(fresh["done"] if fresh else 0) + 1)
            except Exception as exc:
                consecutive += 1
                fresh = get_job(job_id)
                _set_status(job_id, failed=(fresh["failed"] if fresh else 0) + 1,
                            error=str(exc)[:300])
                if consecutive >= GIVE_UP_AFTER:
                    _set_status(job_id, status="failed",
                                error=f"no answer after {consecutive} tiles: {exc}"[:300])
                    return
            if job["delay_ms"] > 0:
                time.sleep(job["delay_ms"] / 1000.0)
        fresh = get_job(job_id)
        if fresh and fresh["done"] == 0 and fresh["failed"] > 0:
            _set_status(job_id, status="failed",
                        error=fresh["error"] or "every tile failed")
        else:
            _set_status(job_id, status="done")
    finally:
        conn.close()
