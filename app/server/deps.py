"""Shared FastAPI dependencies (one home, so routers can be separate modules)."""
from __future__ import annotations

from typing import Any

from .. import db


def conn_dep() -> Any:
    """One SQLite connection per request, closed no matter how the request ends."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def actor_of(x_actor: str | None, actor: str | None) -> str:
    """Who is making this request — the header wins, then the payload, then the default."""
    return (x_actor or actor or "researcher").strip() or "researcher"
