"""Pytest bootstrap — collecting any test module must never touch real data.

Both suites document "uses a temporary database, never the real one".  The
registry suite enforces this at module import (``SIRAJ_DATA_DIR``), but the
first collected test module wins: whichever imports ``app.db`` first freezes
the data directory.  Setting the guard here, before any test module is
imported, makes the guarantee independent of collection order.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("SIRAJ_DATA_DIR", tempfile.mkdtemp(prefix="siraj-test-"))
os.environ.setdefault("SIRAJ_SEED_DEMO", "1")
