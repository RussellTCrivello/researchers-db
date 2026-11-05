#!/usr/bin/env python3
"""Local pre-flight check: syntax, imports, tests and asset wiring.

    python scripts/check.py               # quick checks + pytest (110 tests)
    python scripts/check.py --ui          # + browser smoke test (51 checks)
    python scripts/check.py --api         # + full API verification (407 checks, 100 routes)
    python scripts/check.py --audit       # + the fundamental data/behaviour audit (162 checks)
    python scripts/check.py --geo         # + the geographic workspace in a browser (98 checks)
    python scripts/check.py --evidence    # + evidence as claims and the diagram grammar (36 checks)
    python scripts/check.py --query       # + the typed query language in the browser (14 checks)
    python scripts/check.py --atlas       # + the relationship atlas in a browser (54 checks)
    python scripts/check.py --crce        # + the compass-rose coordinate standard (93 checks)
    python scripts/check.py --structures  # + the structure deck in a browser (62 checks)
    python scripts/check.py --desk        # + the map desk — the registry as a place (87 checks)
    python scripts/check.py --ui --api --full --geo --audit
                          # + exhaustive UI walk (198 checks); --geo implies --ui
"""
from __future__ import annotations

import argparse
import compileall
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui", action="store_true", help="also run the Playwright smoke test")
    ap.add_argument("--api", action="store_true", help="also verify every API endpoint")
    ap.add_argument("--full", action="store_true",
                    help="also run the exhaustive interface walk (needs --ui)")
    ap.add_argument("--audit", action="store_true",
                    help="also run tests/audit.py (integrity, filters, merge, concurrency)")
    ap.add_argument("--geo", action="store_true",
                    help="also run tests/ui_geo.py (the geographic workspace; implies --ui)")
    ap.add_argument("--evidence", action="store_true",
                    help="also run tests/evidence_ui.py (evidence cards, diagram grammar)")
    ap.add_argument("--query", action="store_true",
                    help="also run tests/query_ui.py (the typed query language)")
    ap.add_argument("--atlas", action="store_true",
                    help="also run tests/atlas_ui.py (the relationship atlas)")
    ap.add_argument("--crce", action="store_true",
                    help="also run tests/crce_ui.py (the compass-rose standard)")
    ap.add_argument("--structures", action="store_true",
                    help="also run tests/structures_ui.py (the six structures)")
    ap.add_argument("--desk", action="store_true",
                    help="also run tests/desk_ui.py (the map desk)")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    ok = True

    ok &= step("python version", sys.version_info >= (3, 10), sys.version.split()[0])
    ok &= step("byte-compile app/ and tests/",
               compileall.compile_dir(str(ROOT / "app"), quiet=1, force=True)
               and compileall.compile_dir(str(ROOT / "tests"), quiet=1, force=True))

    import importlib
    for module in ("app", "app.db", "app.schemas", "app.repo", "app.transfer",
                   "app.reports", "app.stats", "app.integrity", "app.cli", "app.server",
                   "app.server.launcher", "app.geo", "app.geo.basemap", "app.geo.spatial",
                   "app.geo.mapdata", "app.geo.providers", "app.geo.georef",
                   "app.server.map_api", "app.graph", "app.querylang", "app.settings"):
        try:
            importlib.import_module(module)
            ok &= step(f"import {module}", True)
        except Exception as exc:                      # noqa: BLE001
            ok &= step(f"import {module}", False, str(exc))

    pack = _basemap_pack()
    ok &= step("offline basemap pack", pack, "" if pack else
               "app/geo/basemap.sqlite missing or unreadable — run python3 -m app.geo.basemap_build")

    deps = _deps()
    ok &= step("runtime dependencies", deps, "" if deps else "fastapi/uvicorn/openpyxl missing")

    lint = subprocess.run([sys.executable, "-m", "ruff", "check", "app", "tests", "scripts"],
                          cwd=ROOT, capture_output=True, text=True)
    ok &= step("ruff lint", lint.returncode == 0, (lint.stdout or "").strip().splitlines()[-1]
               if lint.returncode else "")
    js = _js_syntax()
    ok &= step("javascript syntax (node --check)", js, "" if js else "node missing or a file failed")

    pytest = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=ROOT)
    ok &= step("pytest", pytest.returncode == 0)

    if args.api:
        api = subprocess.run([sys.executable, "tests/verify_all.py"], cwd=ROOT)
        ok &= step("API verification", api.returncode == 0)

    if args.audit:
        audit = subprocess.run([sys.executable, "tests/audit.py"], cwd=ROOT)
        ok &= step("fundamental audit", audit.returncode == 0)

    if args.ui or args.geo:
        ui = subprocess.run([sys.executable, "tests/ui_smoke.py"], cwd=ROOT)
        ok &= step("browser smoke test", ui.returncode == 0)
        if args.full:
            full = subprocess.run([sys.executable, "tests/ui_full.py"], cwd=ROOT)
            ok &= step("exhaustive interface walk", full.returncode == 0)
    if args.geo:
        geo = subprocess.run([sys.executable, "tests/ui_geo.py"], cwd=ROOT)
        ok &= step("geographic workspace", geo.returncode == 0)
    if args.evidence:
        ev = subprocess.run([sys.executable, "tests/evidence_ui.py"], cwd=ROOT)
        ok &= step("evidence and diagram grammar", ev.returncode == 0)
    if args.query:
        qy = subprocess.run([sys.executable, "tests/query_ui.py"], cwd=ROOT)
        ok &= step("typed query language", qy.returncode == 0)
    if args.atlas:
        at = subprocess.run([sys.executable, "tests/atlas_ui.py"], cwd=ROOT)
        ok &= step("relationship atlas", at.returncode == 0)
    if args.structures:
        st = subprocess.run([sys.executable, "tests/structures_ui.py"], cwd=ROOT)
        ok &= step("structure deck", st.returncode == 0)
    if args.desk:
        dk = subprocess.run([sys.executable, "tests/desk_ui.py"], cwd=ROOT)
        ok &= step("map desk", dk.returncode == 0)
    if args.crce:
        cr = subprocess.run([sys.executable, "tests/crce_ui.py"], cwd=ROOT)
        ok &= step("compass-rose standard (CRCE)", cr.returncode == 0)

    print("\nRESULT:", "all checks passed" if ok else "problems found")
    return 0 if ok else 1


def _js_syntax() -> bool:
    """`node --check` every browser module when node is available."""
    import shutil

    node = shutil.which("node")
    if not node:
        return True                                    # optional tool
    files = sorted((ROOT / "app" / "static" / "js").rglob("*.js"))
    for f in files:
        res = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stderr[:400])
            return False
    return True


def _basemap_pack() -> bool:
    """The shipped Natural Earth pack must be present and answer a query."""
    path = ROOT / "app" / "geo" / "basemap.sqlite"
    if not path.exists():
        return False
    try:
        from app.geo import basemap
        return bool(basemap.info()["available"])
    except Exception:                                 # noqa: BLE001
        return False


def _deps() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:                                 # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())
