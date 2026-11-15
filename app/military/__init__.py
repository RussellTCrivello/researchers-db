"""Military Organization — Brigade Information Management System.

A self-contained module inside researchers-db: its own SQLite database,
its own router and its own interface, integrated into the SIRAJ FastAPI app
without touching the registry or the locale catalogues.

Mounting (in app/server/api.py)::

    from .military import router as military_router
    app.include_router(military_router)

The interface is served by the SIRAJ server at ``/military/``.
"""
from __future__ import annotations

from .api import router

__all__ = ["router"]
