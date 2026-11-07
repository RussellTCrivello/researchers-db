"""
SIRAJ · offline street / tile packs (cartography only — never touches registry.db).

Ships with the Gaza vectormap (compressed OpenStreetMap streets, places, water,
green). Optionally serves a `.tilepack` raster pack if the operator drops one
beside it. None of this reads or writes the research registry.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

PACK_DIR = Path(__file__).resolve().parent / "offline_map"
VECTORMAP_NAME = "gaza.vectormap.json"
VECTORMAP_GZ_NAME = "gaza.vectormap.json.gz"
WORLD_VECTORMAP_NAME = "world.vectormap.json"
WORLD_VECTORMAP_GZ_NAME = "world.vectormap.json.gz"
TILEPACK_NAME = "world.tilepack"
LEGACY_TILEPACK_NAME = "gaza.tilepack"

# Built-in working area (matches the shipped Gaza pack).
GAZA_BOUNDS = {
    "s": 31.199587,
    "w": 34.208336,
    "n": 31.610411,
    "e": 34.581528,
}

MAGIC = b"TILEPACK"
HEADER_SIZE = 24
ENTRY_SIZE = 20


def _env_path(key: str, default: Path) -> Path:
    raw = os.environ.get(key, "").strip()
    return Path(raw).resolve() if raw else default


def vectormap_path() -> Path:
    """The street-detail pack (the working area's OSM extract)."""
    return _env_path("SIRAJ_VECTORMAP_FILE", PACK_DIR / VECTORMAP_NAME)


def vectormap_gz_path() -> Path:
    p = vectormap_path()
    gz = p.with_suffix(p.suffix + ".gz") if p.suffix == ".json" else p.parent / VECTORMAP_GZ_NAME
    preferred = PACK_DIR / VECTORMAP_GZ_NAME
    if preferred.is_file():
        return preferred
    return gz


def world_vectormap_gz_path() -> Path:
    return PACK_DIR / WORLD_VECTORMAP_GZ_NAME


def world_vectormap_path() -> Path:
    return PACK_DIR / WORLD_VECTORMAP_NAME


def tilepack_path() -> Path:
    """The world raster pack; a legacy working-area pack still loads."""
    env = _env_path("SIRAJ_TILEPACK_FILE", Path())
    if env != Path() and env.is_file():
        return env
    world = PACK_DIR / TILEPACK_NAME
    if world.is_file():
        return world
    return PACK_DIR / LEGACY_TILEPACK_NAME


def _pack_bytes(raw: Path, gz: Path) -> tuple[bytes, Path] | None:
    if gz.is_file():
        with gzip.open(gz, "rb") as f:
            return f.read(), gz
    if raw.is_file():
        return raw.read_bytes(), raw
    return None


def _read_vectormap_bytes() -> list[tuple[bytes, Path]]:
    """Every vectormap pack that ships: the world base first, then the street
    detail of the working area. One pack alone is fine; both are merged."""
    out: list[tuple[bytes, Path]] = []
    world = _pack_bytes(world_vectormap_path(), world_vectormap_gz_path())
    if world:
        out.append(world)
    detail = _pack_bytes(vectormap_path(), vectormap_gz_path())
    if detail:
        out.append(detail)
    return out


FAMILIES = ("roads", "rail", "water", "waterLines", "green", "places", "areas", "urban")


def _merge_packs(packs: list[dict]) -> dict:
    """World base first, street detail after — one payload, both coverages.

    The bbox is the union of the packs' bboxes so the map can fit whatever
    arrived; when only the working-area pack exists, the bbox is its own.
    """
    if len(packs) == 1:
        return dict(packs[0])
    merged: dict[str, Any] = {"v": 2, "detail": "world + street detail"}
    bbox = None
    for key in ("created", "source"):
        vals = [str(p.get(key) or "") for p in packs if p.get(key)]
        merged[key] = " · ".join(dict.fromkeys(vals))
    for fam in FAMILIES:
        merged[fam] = [item for p in packs for item in (p.get(fam) or [])]
    for p in packs:
        b = p.get("bbox") or {}
        if not b:
            continue
        bbox = dict(b) if bbox is None else {
            "w": min(bbox.get("w", 180.0), b.get("w", 180.0)),
            "s": min(bbox.get("s", 90.0), b.get("s", 90.0)),
            "e": max(bbox.get("e", -180.0), b.get("e", -180.0)),
            "n": max(bbox.get("n", -90.0), b.get("n", -90.0)),
        }
    if bbox:
        merged["bbox"] = bbox
    return merged


@lru_cache(maxsize=1)
def _vectormap_cache(stamp: str) -> dict[str, Any] | None:
    packs_bytes = _read_vectormap_bytes()
    if not packs_bytes:
        return None
    parsed_list = [json.loads(data.decode("utf-8")) for data, _ in packs_bytes]
    parsed = _merge_packs(parsed_list)
    data = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    paths = ", ".join(str(p) for _, p in packs_bytes)
    digest = hashlib.sha256(data).hexdigest()[:16]
    gzipped = gzip.compress(data, compresslevel=9)
    stats = {
        "roads": len(parsed.get("roads") or []),
        "rail": len(parsed.get("rail") or []),
        "water": len(parsed.get("water") or []) + len(parsed.get("waterLines") or []),
        "green": len(parsed.get("green") or []) + len(parsed.get("urban") or []),
        "places": len(parsed.get("places") or []),
        "areas": len(parsed.get("areas") or []),
    }
    stats["labels"] = stats["places"] + stats["areas"]
    return {
        "path": paths,
        "stamp": stamp,
        "raw": data,
        "gzip": gzipped,
        "hash": digest,
        "etag": f'"vm-{digest}"',
        "parsed": parsed,
        "info": {
            "available": True,
            "version": parsed.get("v") or 1,
            "hash": digest,
            "size": len(data),
            "gzipSize": len(gzipped),
            "bbox": parsed.get("bbox") or GAZA_BOUNDS,
            "created": parsed.get("created") or "",
            "detail": parsed.get("detail") or "medium",
            "source": parsed.get("source") or "© OpenStreetMap contributors",
            "stats": stats,
            "name_en": "World street map (offline)",
            "name_ar": "خريطة شوارع العالم (دون اتصال)",
        },
    }


def _vectormap_stamp() -> str:
    parts = []
    for p in (world_vectormap_gz_path(), world_vectormap_path(),
              vectormap_gz_path(), vectormap_path()):
        if p.is_file():
            st = p.stat()
            parts.append(f"{p}:{st.st_mtime_ns}:{st.st_size}")
    return ";".join(parts)


def vectormap_info() -> dict[str, Any]:
    stamp = _vectormap_stamp()
    if not stamp:
        return {
            "available": False,
            "version": 0,
            "hash": "",
            "size": 0,
            "gzipSize": 0,
            "bbox": GAZA_BOUNDS,
            "name_en": "World street map (offline)",
            "name_ar": "خريطة شوارع العالم (دون اتصال)",
        }
    entry = _vectormap_cache(stamp)
    return dict(entry["info"]) if entry else {
        "available": False, "bbox": GAZA_BOUNDS,
    }


def vectormap_payload(prefer_gzip: bool = True) -> dict[str, Any] | None:
    stamp = _vectormap_stamp()
    if not stamp:
        return None
    entry = _vectormap_cache(stamp)
    if not entry:
        return None
    return {
        "etag": entry["etag"],
        "hash": entry["hash"],
        "body": entry["gzip"] if prefer_gzip else entry["raw"],
        "gzip": prefer_gzip,
        "raw_size": len(entry["raw"]),
        "gzip_size": len(entry["gzip"]),
    }


# --------------------------------------------------------------------------- #
# optional .tilepack (raster WebP) — cartography only
# --------------------------------------------------------------------------- #
_tile_cache: dict[str, Any] | None = None


def _close_tilepack() -> None:
    global _tile_cache
    if _tile_cache and _tile_cache.get("fd") is not None:
        try:
            os.close(_tile_cache["fd"])
        except OSError:
            pass
    _tile_cache = None


def load_tilepack() -> dict[str, Any] | None:
    global _tile_cache
    path = tilepack_path()
    try:
        st = path.stat()
    except OSError:
        _close_tilepack()
        return None
    if _tile_cache and _tile_cache.get("mtime") == st.st_mtime and _tile_cache.get("size") == st.st_size:
        return _tile_cache
    _close_tilepack()
    try:
        fd = os.open(path, os.O_RDONLY)
        header = os.read(fd, HEADER_SIZE)
        if len(header) < HEADER_SIZE or header[:8] != MAGIC:
            os.close(fd)
            return None
        version, meta_bytes, tile_count, _reserved = struct.unpack_from("<IIII", header, 8)
        if version != 1 or meta_bytes > 1_000_000:
            os.close(fd)
            return None
        meta_buf = os.read(fd, meta_bytes)
        meta = json.loads(meta_buf.decode("utf-8"))
        index_bytes = tile_count * ENTRY_SIZE
        index_buf = os.read(fd, index_bytes)
        data_offset = HEADER_SIZE + meta_bytes + index_bytes
        index: dict[str, tuple[int, int]] = {}
        for i in range(tile_count):
            b = i * ENTRY_SIZE
            z, x, y, offset, length = struct.unpack_from("<IIIII", index_buf, b)
            index[f"{z}/{x}/{y}"] = (offset, length)
        _tile_cache = {
            "fd": fd, "mtime": st.st_mtime, "size": st.st_size,
            "meta": meta, "data_offset": data_offset, "index": index,
            "path": str(path),
            "stamp": f"{st.st_size:x}-{int(st.st_mtime):x}",
        }
        return _tile_cache
    except Exception:
        _close_tilepack()
        return None


def tilepack_info() -> dict[str, Any]:
    pack = load_tilepack()
    if not pack:
        return {
            "available": False,
            "bbox": GAZA_BOUNDS,
            "name_en": "World loaded map (raster)",
            "name_ar": "الخريطة المحمّلة للعالم (نقطية)",
            "hint_en": "Run python3 -m app.geo.tilepack_build to render the world raster tilepack.",
            "hint_ar": "شغّل python3 -m app.geo.tilepack_build لبناء حزمة البلاطات النقطية العالمية.",
        }
    meta = pack["meta"]
    bounds = meta.get("bounds") or {}
    return {
        "available": True,
        "name": meta.get("name") or "World offline tiles",
        "name_en": "World loaded map (raster)",
        "name_ar": "الخريطة المحمّلة للعالم (نقطية)",
        "format": meta.get("format") or "webp",
        "minzoom": meta.get("minzoom", 11),
        "maxzoom": meta.get("maxzoom", 17),
        "tileSize": meta.get("tileSize") or 256,
        "bounds": bounds,
        "bbox": {
            "s": bounds.get("s", GAZA_BOUNDS["s"]),
            "w": bounds.get("w", GAZA_BOUNDS["w"]),
            "n": bounds.get("n", GAZA_BOUNDS["n"]),
            "e": bounds.get("e", GAZA_BOUNDS["e"]),
        },
        "attribution": meta.get("attribution")
            or "© OpenStreetMap contributors; basemap © European Commission / Eurostat GISCO",
        "rows": len(pack["index"]),
        "stamp": pack["stamp"],
    }


def read_tile(z: int, x: int, y: int) -> bytes | None:
    pack = load_tilepack()
    if not pack:
        return None
    entry = pack["index"].get(f"{z}/{x}/{y}")
    if not entry:
        return None
    offset, length = entry
    try:
        os.lseek(pack["fd"], pack["data_offset"] + offset, os.SEEK_SET)
        data = os.read(pack["fd"], length)
        return data if len(data) == length else None
    except OSError:
        return None


def catalog_extra() -> dict[str, Any]:
    """Snippet merged into /api/map/config — no registry access."""
    return {
        "vectormap": vectormap_info(),
        "tilepack": tilepack_info(),
        "working_area": GAZA_BOUNDS,
    }
