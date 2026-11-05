"""SIRAJ web application package.

``app.server.api`` holds the FastAPI application (``app``); ``app.server.launcher``
starts it identically on Windows, macOS and Linux.
"""
from .api import app  # noqa: F401  (re-exported for `uvicorn app.server:app`)

__all__ = ["app"]
