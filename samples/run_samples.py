#!/usr/bin/env python3
"""
SIRAJ · samples/run_samples.py — end-to-end import/export fixture run.

Builds a throwaway registry (never ``app/data/registry.db``), seeds the
reference data, then pushes every sample file through the same pipeline the
import wizard uses — parse → auto-map → validate → commit — and exports the
entities back out.  The report is printed per file; the exit code is 0 only
when every sample passed with zero failed rows.

    python3 samples/run_samples.py            # fixture database in a temp dir
    python3 samples/run_samples.py --keep     # leave the fixture DB for inspection

The samples deliberately run in dependency order: places create the parent
codes that persons reference, sources create the codes the person rows cite as
primary sources, and ``persons-import-bilingual.csv`` re-imports the same
records through ``upsert`` — the same content with bilingual ``EN / AR`` headers.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# the fixture database must exist before app.db is imported: it reads SIRAJ_DB once
_tmpdir = None   # kept alive for --keep


def _prepare(db_path: Path | None) -> Path:
    global _tmpdir
    if db_path is None:
        _tmpdir = tempfile.TemporaryDirectory(prefix="siraj-samples-")
        db_path = Path(_tmpdir.name) / "registry.db"
    import os
    os.environ["SIRAJ_DB"] = str(db_path)
    return db_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the import/export samples end to end.")
    ap.add_argument("--db", type=Path, default=None,
                    help="fixture database path (default: a fresh temp file)")
    ap.add_argument("--keep", action="store_true",
                    help="keep the fixture database and print its path")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    db_path = _prepare(args.db)

    from app import db, transfer  # noqa: E402
    from app.schemas import ENTITIES  # noqa: E402

    db.init_db(seed_demo=False)          # schema + migrations + reference data
    conn = db.connect()
    try:

        plan = [
            ("places-import.csv", "place", "create"),
            ("sources-import.json", "source", "create"),
            ("persons-import.csv", "person", "create"),
            ("persons-import-bilingual.csv", "person", "upsert"),
        ]
        failures = 0
        print(f"SIRAJ · sample fixture run → {db_path}\n")
        for filename, entity, mode in plan:
            path = HERE / filename
            spec = ENTITIES[entity]
            cols, rows, fmt = transfer.parse_tabular(path.read_bytes(), path.name)
            mapping = transfer.suggest_mapping(spec, cols)
            report = transfer.process_rows(conn, spec, rows, mapping,
                                           mode=mode, actor="samples",
                                           dry_run=False, reason="sample import")
            conn.commit()
            failed = report.get("failed", 0)
            failures += failed
            unmapped = report.get("unmapped_columns") or []
            print(f"  {filename:<32} {fmt:<5} {mode:<7} "
                  f"rows={report.get('total', 0)} "
                  f"created={report.get('created', 0)} "
                  f"updated={report.get('updated', 0)} "
                  f"skipped={report.get('skipped', 0)} "
                  f"failed={failed}"
                  + (f"  unmapped={unmapped}" if unmapped else ""))
            for err in (report.get("errors") or [])[:5]:
                print(f"      row {err.get('row')} · {err.get('field')}: {err.get('message')}")

        print("\n  export round-trip:")
        for entity in ("place", "source", "person"):
            spec = ENTITIES[entity]
            for fmt in ("csv", "xlsx"):
                data, name, mime = transfer.export_bytes(
                    conn, spec, {"page_size": 1000}, fmt, None, "en", True,
                    f"samples {entity}")
                print(f"    {entity:<7} {fmt:<5} {len(data):>8} bytes  ({name})")

        print(f"\n{'OK' if failures == 0 else 'FAILURES'} — "
              f"{failures} failed row(s) across the sample set")
        return 0 if failures == 0 else 1
    finally:
        conn.close()
        if args.keep and _tmpdir is not None:
            print(f"fixture kept at {db_path}")
            _tmpdir._finalizer.detach()      # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())
