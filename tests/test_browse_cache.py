"""
Guards on the tile browse-cache: policy/error cards are not cartography.

The 2026-11 integration check found the coordinate-entry map covered in
OpenStreetMap "403 · Access blocked" tiles: the provider answers a blocked
client with the same text-on-white PNG for every z/x/y — with HTTP 200, so it
renders in clients and the cache remembered hundreds of copies of it. These
tests pin the defences: the error-card detector, the never-cache/never-serve
rule, the terms rule (providers that forbid keeping tiles are served through
but not persisted), and the sweep that forgets cards already stored.

Run:  pytest -q tests/test_browse_cache.py   (temporary cache file, never the real one)
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="siraj-browse-cache-test-")
os.environ["SIRAJ_BROWSE_CACHE"] = str(Path(_TMP) / "cache.sqlite")

from app.geo import browse_cache, providers  # noqa: E402

# The card seen in the field: OSM's "Access blocked" tile (256×256 PNG).
_OSM_BLOCK_SHA = "109722facb0459991ce2c9983b3ae40232e84be7273aaa454071b50049e3d88b"


def _png(draw) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    draw(im)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _card_png() -> bytes:
    """A text-on-white error card: white corners and centre, dark ink rows."""
    def draw(im):
        for y in range(40, 220, 24):
            for x in range(20, 236):
                im.putpixel((x, y), (0, 0, 0))
    return _png(draw)


def _map_tile_png() -> bytes:
    """A cartography-looking tile: coloured surface, non-white corners."""
    def draw(im):
        for y in range(256):
            for x in range(0, 256, 64):
                im.putpixel((x, y), (170, 211, 223))
    return _png(draw)


@pytest.fixture()
def cache_env(monkeypatch):
    """Fresh cache file per test; skip the lazy one-time sweep."""
    path = Path(_TMP) / f"cache-{os.urandom(4).hex()}.sqlite"
    monkeypatch.setenv("SIRAJ_BROWSE_CACHE", str(path))
    monkeypatch.setattr(browse_cache, "_PURGED", True)
    yield path
    if path.exists():
        path.unlink()


def test_seeded_block_card_is_refused():
    assert _OSM_BLOCK_SHA in browse_cache._DENIED_TILE_SHA256
    # the denylist is hash-based: body bytes do not matter once the hash is known
    assert browse_cache.is_error_tile(b"anything-else") is False
    assert browse_cache.is_error_tile(b"") is True  # nothing is not a tile


def test_error_card_detector_catches_new_cards_and_spares_map_tiles():
    card = _card_png()
    assert browse_cache.is_error_tile(card) is True
    # detection is remembered, so the same card is refused from now on
    assert browse_cache.is_error_tile(card) is True
    tile = _map_tile_png()
    assert browse_cache.is_error_tile(tile) is False


def test_error_cards_are_never_served_or_remembered(cache_env, monkeypatch):
    card = _card_png()
    monkeypatch.setattr(browse_cache, "fetch_upstream",
                        lambda url, timeout=20.0: (card, "image/png"))
    with pytest.raises(ConnectionError):
        browse_cache.get_or_fetch("esri-imagery", "base", 5, 16, 11)
    assert browse_cache.get("esri-imagery", "base", 5, 16, 11) is None


def test_terms_forbid_persisting_but_still_serve(cache_env, monkeypatch):
    tile = _map_tile_png()
    monkeypatch.setattr(browse_cache, "fetch_upstream",
                        lambda url, timeout=20.0: (tile, "image/png"))
    # OSM's terms forbid keeping tiles (downloadable=False): served, not stored
    assert providers.PROVIDERS["osm"].get("downloadable") is False
    body, ctype, origin = browse_cache.get_or_fetch("osm", "base", 7, 65, 44)
    assert body == tile and origin == "network"
    assert browse_cache.get("osm", "base", 7, 65, 44) is None, "policy tiles must not be persisted"
    # a provider whose terms allow caching is remembered as before
    body, ctype, origin = browse_cache.get_or_fetch("esri-imagery", "base", 7, 65, 44)
    assert browse_cache.get("esri-imagery", "base", 7, 65, 44) is not None


def test_purge_forgets_cards_already_stored(cache_env):
    card = _card_png()
    digest = hashlib.sha256(card).hexdigest()
    browse_cache._DENIED_TILE_SHA256.add(digest)  # what detection does in production
    conn = browse_cache._connect()
    conn.execute(
        "INSERT INTO tiles (provider, source, z, x, y, content_type, encoding, body, nbytes, touched) "
        "VALUES ('osm','base',9,282,306,'image/png','raw',?,?,?)",
        (card, len(card), 0.0))
    conn.commit()
    conn.close()
    removed = browse_cache.purge_error_tiles()
    assert removed == 1
    assert browse_cache.get("osm", "base", 9, 282, 306) is None
