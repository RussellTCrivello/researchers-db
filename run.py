#!/usr/bin/env python3
"""SIRAJ · سِراج — single entry point for Windows, macOS and Linux.

    python run.py                 start the web application (http://127.0.0.1:8000)
    python run.py --host 0.0.0.0 --port 8080
    python run.py init --demo     create/upgrade the database with demo records
    python run.py stats           print record counts
    python run.py --help          everything else (same commands as `python -m app.cli`)

The script exists so that Windows users never have to deal with virtualenv
activation paths, `set VAR=...` syntax or `python -m` module paths: a single
command works everywhere, and it configures UTF-8 output before anything else
is imported.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.server.launcher import configure_environment  # noqa: E402

configure_environment()

SERVER_FLAGS = {"--host", "--port", "--log-level", "--demo"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("Server options: --host, --port, --log-level, --demo")
        return 0
    looks_like_server = (not argv) or argv[0].startswith("-") or argv[0] in ("serve", "run")
    if looks_like_server:
        import argparse

        from app.server.launcher import serve

        parser = argparse.ArgumentParser(prog="run.py", add_help=False)
        parser.add_argument("--host", default=None)
        parser.add_argument("--port", type=int, default=None)
        parser.add_argument("--log-level", default="info")
        args, _rest = parser.parse_known_args([a for a in argv if a != "serve" and a != "run"])
        serve(args.host, args.port, args.log_level)
        return 0
    from app.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
