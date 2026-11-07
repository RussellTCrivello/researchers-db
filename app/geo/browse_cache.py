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
import hashlib
import io
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

# Identify the app per the tile providers' usage policies (OSM asks for a
# valid User-Agent with contact info and rejects anonymous scrapers).
_UA = "SIRAJ-ResearchRegistry/1.0 (+https://github.com/RussellTCrivello/researchers-db)"

# Bodies that are policy/error cards, not cartography. Some tile servers answer
# a blocked client with the SAME "access blocked" PNG for every z/x/y — with
# HTTP 200, so it renders in clients as a wall of block cards. The cache must
# recognise these and neither remember nor replay them. Seeded with the card
# seen in the field (OSM, 2026-11); _looks_like_error_card grows the set on its
# own whenever a provider swaps in a new card design.
_DENIED_TILE_SHA256: set[str] = {
    # OpenStreetMap "403 · Access blocked — App is not following the tile
    # usage policy" (256×256 white card, identical for every tile).
    "109722facb0459991ce2c9983b3ae40232e84be7273aaa454071b50049e3d88b",
}
_PURGED = False


def _looks_like_error_card(data: bytes) -> bool:
    """True for a text-on-white card pretending to be a tile.

    A real map tile is cartography: coloured fills, imagery, linework. Error
    cards are white pages with dark text. The structural test: a tile-sized
    raster whose corners and centre are near-pure-white AND that carries a
    meaningful share of near-black ink. Validated against the OSM block card
    (matches), 40 real imagery tiles, ocean-blank tiles and synthetic cards.
    """
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.size not in ((256, 256), (512, 512)):
            return False
        rgb = im.convert("RGB")
        w, h = im.size
        for x, y in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3),
                     (w // 2, h // 2), (w // 2, 8)):
            r, g, b = rgb.getpixel((x, y))
            if r < 245 or g < 245 or b < 245:
                return False
        ink = 0
        step = 16
        total = max(1, (h // step) * (w // step))
        for y in range(0, h, step):
            for x in range(0, w, step):
                r, g, b = rgb.getpixel((x, y))
                if r < 60 and g < 60 and b < 60:
                    ink += 1
        return ink >= max(4, total // 50)
    except Exception:
        return False


def is_error_tile(data: bytes) -> bool:
    """True when a fetched 'tile' is really a policy/error card."""
    if not data:
        return True
    digest = hashlib.sha256(data).hexdigest()
    if digest in _DENIED_TILE_SHA256:
        return True
    if _looks_like_error_card(data):
        _DENIED_TILE_SHA256.add(digest)
        _drop_cached_body(digest)
        return True
    return False


def _drop_cached_body(digest: str) -> None:
    """Forget every remembered tile whose body hashes to `digest`."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT provider, source, z, x, y, body, encoding FROM tiles").fetchall()
        for r in rows:
            raw = gzip.decompress(r["body"]) if r["encoding"] == "gzip" else r["body"]
            if hashlib.sha256(raw).hexdigest() == digest:
                conn.execute(
                    "DELETE FROM tiles WHERE provider=? AND source=? AND z=? AND x=? AND y=?",
                    (r["provider"], r["source"], r["z"], r["x"], r["y"]))
        conn.commit()
    finally:
        conn.close()


def purge_error_tiles() -> int:
    """Sweep the remembered tiles and drop any known policy/error cards.

    Runs once per process (lazily, on first tile traffic). Hash-only, so the
    sweep costs one pass over the cache.
    """
    global _PURGED
    _PURGED = True
    conn = _connect()
    try:
        rows = conn.execute("SELECT provider, source, z, x, y, body, encoding FROM tiles").fetchall()
        removed = 0
        for r in rows:
            raw = gzip.decompress(r["body"]) if r["encoding"] == "gzip" else r["body"]
            if hashlib.sha256(raw).hexdigest() in _DENIED_TILE_SHA256:
                conn.execute(
                    "DELETE FROM tiles WHERE provider=? AND source=? AND z=? AND x=? AND y=?",
                    (r["provider"], r["source"], r["z"], r["x"], r["y"]))
                removed += 1
        if removed:
            conn.commit()
        return removed
    finally:
        conn.close()


def _persist_allowed(provider_id: str) -> bool:
    """May this provider's tiles be stored beyond the moment of display?

    `downloadable=False` in the catalogue means the provider's terms forbid
    keeping tiles (OSM: "no offline scraping"; the bundled packs for the
    offline kinds). Such tiles are served through but never written down.
    """
    prov = providers.PROVIDERS.get(provider_id) or {}
    return prov.get("downloadable") is not False


def _env_db() -> Path:
    raw = os.environ.get("SIRAJ_BROWSE_CACHE", "").strip()
    return Path(raw).resolve() if raw else CACHE_DB


def _connect() -> sqlite3.Connection:
    path = _env_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
    if is_error_tile(body):
        # A policy/error card is not cartography: never remember it.
        return
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
    if not _PURGED:
        purge_error_tiles()
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
    if is_error_tile(body):
        # The provider answered with a policy/error card instead of a tile
        # (some do this with HTTP 200 so the card renders in clients). Report
        # it as unavailable so the map falls back to its quiet bed — the card
        # is neither shown nor remembered.
        raise ConnectionError("the provider returned a policy/error card instead of a tile")
    if _persist_allowed(provider):
        try:
            put(provider, source, z, x, y, body, ctype)
        except Exception:
            pass  # serving the tile matters more than persisting it
    return body, ctype, "network"
