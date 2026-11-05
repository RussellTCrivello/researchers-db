#!/usr/bin/env bash
# SIRAJ - siraj - POSIX launcher (macOS / Linux).
# Windows users: use run.py, start.bat or start.ps1 instead.
set -euo pipefail
cd "$(dirname "$0")"

PY_BIN="${PYTHON:-python3}"
if [ ! -x ".venv/bin/python" ]; then
  echo "[SIRAJ] creating virtual environment in .venv ..."
  "$PY_BIN" -m venv .venv
fi

if ! .venv/bin/python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "[SIRAJ] installing dependencies ..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python run.py "$@"
