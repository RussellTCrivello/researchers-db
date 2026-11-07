"""SIRAJ · cross-platform launcher (Windows-first).

Why this module exists
----------------------
The application has to behave identically when it is started from
``cmd.exe``/PowerShell on Windows, from a macOS Terminal, or from a shell on a
Linux server.  Three things commonly break in that situation:

1. **Console encodings.**  Windows consoles default to a legacy code page
   (cp1256/cp1252), so printing Arabic record counts or tracebacks raises
   ``UnicodeEncodeError``.  We switch the standard streams to UTF-8 first.
2. **Filesystem encodings.**  Reading/writing data files without an explicit
   encoding uses the *locale* encoding on Windows.  Every module in this
   project passes ``encoding="utf-8"`` explicitly, and this launcher sets
   ``PYTHONUTF8=1`` so third-party libraries inherit the same behaviour.
3. **Signals and reload.**  ``uvicorn`` installs its own signal handlers; a
   single-process, reload-free launch (the SQLite default) works the same on
   all three platforms.

The launcher is deliberately dependency-free apart from ``uvicorn`` so it can
run before/independently of the FastAPI import.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:          # allow `python app/server/launcher.py`
    sys.path.insert(0, str(ROOT))


def configure_environment() -> None:
    """Make the process behave the same on every platform."""
    # UTF-8 for the Python filesystem/locale layer (no-op on POSIX, vital on Windows)
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # keep the SQLite journal beside the database, even on network shares/OneDrive
    os.environ.setdefault("SIRAJ_HOST", "127.0.0.1" if sys.platform == "win32" else "0.0.0.0")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):     # detached/redirected streams
                pass


def default_data_dir() -> Path:
    """Where the database and uploads live when the user did not say otherwise.

    ``app/data`` (inside the project) is the default everywhere, because a
    researcher usually wants the registry next to the application — a portable
    folder they can copy to another machine.  ``SIRAJ_DATA_DIR`` overrides it
    (recommended for a Windows service or a shared server).
    """
    env = os.environ.get("SIRAJ_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # ROOT is the `app` package; the project folder is its parent.
    return (ROOT.parent / "app" / "data").resolve()


def apply_data_dir() -> Path:
    path = default_data_dir()
    # Pre-fix launches wrote `app/app/data` (ROOT was taken for the project
    # root). Bring the registry home once — the folder is only moved when the
    # corrected location has no registry yet, and if another running instance
    # holds the files we simply keep using the old place. Nothing is deleted.
    legacy = (ROOT / "app" / "data").resolve()
    if path != legacy and (legacy / "registry.db").exists() \
            and not (path / "registry.db").exists():
        target_free = not path.exists() or not any(path.iterdir())
        if target_free:
            try:
                if path.exists():
                    path.rmdir()
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy), str(path))
            except OSError:
                path = legacy
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SIRAJ_DATA_DIR", str(path))
    return path


def serve(host: str | None = None, port: int | None = None, log_level: str = "info") -> None:
    configure_environment()
    data_dir = apply_data_dir()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import uvicorn  # imported late so `--help` works without the dependency

    host = host or os.environ.get("SIRAJ_HOST") or ("127.0.0.1" if sys.platform == "win32" else "0.0.0.0")
    port = int(port or os.environ.get("SIRAJ_PORT") or 8000)
    print("SIRAJ · سِراج  —  research registry")
    print(f"  data directory : {data_dir}")
    print(f"  listening on   : http://{host}:{port}")
    print("  stop with Ctrl+C\n")
    uvicorn.run("app.server:app", host=host, port=port, log_level=log_level,
                reload=False, workers=1, access_log=True)


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    serve()
