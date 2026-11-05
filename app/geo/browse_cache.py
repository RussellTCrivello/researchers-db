"""
SIRAJ · browse-cache — durable compressed tile store for areas the user viewed.

Cartography only: never opens registry.db. Tiles the map actually requests are
fetched once from the declared provider, stored gzip-compressed in a dedicated
SQLite file beside the offline packs, and served thereafter with no upstream
round-trip. That is what makes a previously browsed window paint offline.

Layout of each row:
    provider | source | z | x | y | content_type | encoding | bytes | touched

`encoding` is ``gzip`` when the blob is compressed, else ``raw`` (already-small
WebP / JPEG). Lookup is O(1) on the primary key.
"""
from __future__ import annotations

import gzip
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import providers

CACHE_DIR = Path(__file__).resolve().parent / "offline_map"
CACHE_DB = CACHE_DIR / "browse_cache.sqlite"

# Soft ceiling so a long session cannot fill the disk unnoticed.
MAX_ROWS = 40_000
MAX_BYTES = 800 * 1024 * 1024  # 800 MiB

_UA = "SIRAJ-ResearchRegistry/1.0 (browse-cache; +local-offline)"


def _env_db() -> Path:
    raw = os.environ.get("SIRAJ_BROWSE_CACHE", "").strip()
    return Path(raw).resolve() if raw else CACHE_DB


def _connect() -> sqlite3.Connection:
    path = _env_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tiles (
            provider TEXT NOT NULL,
            source   TEXT NOT NULL,
            z        INTEGER NOT NULL,
            x        INTEGER NOT NULL,
            y        INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            encoding TEXT NOT NULL,
            body     BLOB NOT NULL,
            nbytes   INTEGER NOT NULL,
            touched  REAL NOT NULL,
            PRIMARY KEY (provider, source, z, x, y)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS tiles_touched ON tiles(touched)"
    )
    return conn


def stats() -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(nbytes),0), COALESCE(MIN(touched),0), "
            "COALESCE(MAX(touched),0) FROM tiles"
        ).fetchone()
        providers_n = conn.execute(
            "SELECT COUNT(DISTINCT provider) FROM tiles"
        ).fetchone()[0]
        return {
            "path": str(_env_db()),
            "entries": int(row[0] or 0),
            "bytes": int(row[1] or 0),
            "providers": int(providers_n or 0),
            "oldest": float(row[2] or 0),
            "newest": float(row[3] or 0),
            "max_rows": MAX_ROWS,
            "max_bytes": MAX_BYTES,
        }
    finally:
        conn.close()


def clear() -> dict[str, Any]:
    conn = _connect()
    try:
        before = conn.execute("SELECT COUNT(*), COALESCE(SUM(nbytes),0) FROM tiles").fetchone()
        conn.execute("DELETE FROM tiles")
        conn.commit()
        return {"removed": int(before[0] or 0), "freed_bytes": int(before[1] or 0)}
    finally:
        conn.close()


def _evict_if_needed(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(nbytes),0) FROM tiles"
    ).fetchone()
    n, total = int(row[0] or 0), int(row[1] or 0)
    if n <= MAX_ROWS and total <= MAX_BYTES:
        return
    # Drop oldest 10% (or enough to get under the byte ceiling).
    drop = max(n - int(MAX_ROWS * 0.9), 500 if total > MAX_BYTES else 0)
    if drop <= 0:
        return
    conn.execute(
        "DELETE FROM tiles WHERE rowid IN ("
        "  SELECT rowid FROM tiles ORDER BY touched ASC LIMIT ?"
        ")",
        (drop,),
    )
    conn.commit()


def get(provider: str, source: str, z: int, x: int, y: int) -> tuple[bytes, str] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT body, content_type, encoding FROM tiles "
            "WHERE provider=? AND source=? AND z=? AND x=? AND y=?",
            (provider, source, z, x, y),
        ).fetchone()
        if not row:
            return None
        body, ctype, encoding = row
        conn.execute(
            "UPDATE tiles SET touched=? WHERE provider=? AND source=? AND z=? AND x=? AND y=?",
            (time.time(), provider, source, z, x, y),
        )
        conn.commit()
        raw = gzip.decompress(body) if encoding == "gzip" else body
        return bytes(raw), str(ctype)
    finally:
        conn.close()


def put(provider: str, source: str, z: int, x: int, y: int,
        body: bytes, content_type: str) -> None:
    # Prefer gzip for PNG/JSON-ish payloads; leave JPEG/WebP as-is when gzip
    # does not shrink them enough to be worth the CPU.
    encoding = "raw"
    stored = body
    if content_type.startswith("image/png") or content_type.startswith("image/jpeg") \
            or content_type.startswith("application/"):
        gz = gzip.compress(body, compresslevel=6)
        if len(gz) < len(body) * 0.92:
            stored, encoding = gz, "gzip"
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO tiles "
            "(provider, source, z, x, y, content_type, encoding, body, nbytes, touched) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (provider, source, z, x, y, content_type, encoding, stored, len(stored), time.time()),
        )
        conn.commit()
        _evict_if_needed(conn)
    finally:
        conn.close()


def _template_for(provider_id: str, source: str) -> tuple[str, dict[str, Any]] | None:
    prov = providers.PROVIDERS.get(provider_id)
    if not prov:
        return None
    style = prov.get("style") or {}
    sources = style.get("sources") or {}
    src = sources.get(source) or sources.get("base") or sources.get("imagery")
    if not src:
        # first raster source
        for s in sources.values():
            if isinstance(s, dict) and s.get("type") == "raster" and s.get("tiles"):
                src = s
                break
    if not src or not src.get("tiles"):
        # fall back to top-level tiles list
        tiles = prov.get("tiles") or []
        if not tiles:
            return None
        return tiles[0], prov
    return src["tiles"][0], prov


def resolve_upstream(provider_id: str, source: str, z: int, x: int, y: int) -> str | None:
    got = _template_for(provider_id, source)
    if not got:
        return None
    tmpl, _prov = got
    # CARTO retina placeholder → standard tile
    url = tmpl.replace("{r}", "")
    return url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))


def fetch_upstream(url: str, timeout: float = 20.0) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type") or "image/png"
        return data, ctype.split(";")[0].strip()


def get_or_fetch(provider: str, source: str, z: int, x: int, y: int) -> tuple[bytes, str, str]:
    """
    Return ``(body, content_type, origin)`` where origin is ``cache`` or ``network``.
    """
    hit = get(provider, source, z, x, y)
    if hit:
        return hit[0], hit[1], "cache"
    url = resolve_upstream(provider, source, z, x, y)
    if not url:
        raise LookupError(f"unknown provider/source: {provider}/{source}")
    try:
        body, ctype = fetch_upstream(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(str(exc)) from exc
    try:
        put(provider, source, z, x, y, body, ctype)
    except Exception:
        pass  # serving the tile matters more than persisting it
    return body, ctype, "network"
