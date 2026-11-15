"""
Command-line entry point.

    python3 -m app.cli init [--demo]     create / upgrade the database
    python3 -m app.cli serve [--port]    run the web application
    python3 -m app.cli migrate           apply pending migrations only
    python3 -m app.cli reindex           rebuild the full-text index
    python3 -m app.cli geocode-places [--apply]  reconcile place coordinates
    python3 -m app.cli backup [-o FILE]  consistent snapshot (ZIP)
    python3 -m app.cli stats             quick counts
    python3 -m app.cli user add USER ROLE
    python3 -m app.cli export ENTITY OUT [--format xlsx|csv|json]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

from . import db


def cmd_init(args: argparse.Namespace) -> int:
    db.init_db(seed_demo=args.demo)
    print(f"database ready: {db.DB_PATH}")
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    db.init_db(seed_demo=False)
    conn = db.connect()
    applied = [dict(r) for r in conn.execute("SELECT * FROM schema_migration ORDER BY filename")]
    conn.close()
    for row in applied:
        flag = "ok" if row["ok"] else "FAILED"
        print(f"{row['filename']:<34} {row['applied_at']}  {flag}  {row['note'] or ''}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    db.init_db(seed_demo=args.demo if args.demo is not None else False)
    uvicorn.run("app.server:app", host=args.host, port=args.port,
                workers=1, log_level=args.log_level)
    return 0


def cmd_reindex(_args: argparse.Namespace) -> int:
    conn = db.connect()
    n = db.rebuild_index(conn)
    conn.commit()
    conn.close()
    print(f"indexed {n} documents")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    out = Path(args.out or f"siraj-backup-{db.now()[:10]}.zip")
    src = db.connect()
    tmp = db.DATA_DIR / "_backup_tmp.db"
    dest = sqlite3.connect(tmp)
    src.backup(dest)
    dest.close()
    src.close()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp, "registry.db")
        uploads = db.UPLOAD_DIR
        for f in uploads.glob("*"):
            zf.write(f, f"uploads/{f.name}")
        zf.writestr("manifest.json", json.dumps(
            {"created_at": db.now(), "schema_version": "1.0.0"}, indent=2))
    tmp.unlink(missing_ok=True)
    print(f"backup written: {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    from .schemas import ENTITIES

    conn = db.connect()
    total = 0
    for spec in ENTITIES.values():
        n = conn.execute(f"SELECT COUNT(*) FROM {spec.table} WHERE deleted_at IS NULL").fetchone()[0]
        total += n
        print(f"{spec.plural_en:<16} {n:>7}")
    print(f"{'TOTAL':<16} {total:>7}")
    print(f"{'change log':<16} {conn.execute('SELECT COUNT(*) FROM change_log').fetchone()[0]:>7}")
    print(f"{'vocabularies':<16} {conn.execute('SELECT COUNT(*) FROM lookup').fetchone()[0]:>7}")
    print(f"database: {db.DB_PATH} ({db.DB_PATH.stat().st_size / 1024:.0f} KB)")
    conn.close()
    return 0


def cmd_user(args: argparse.Namespace) -> int:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO app_user (username, display_name, role) VALUES (?,?,?)",
                     (args.username, args.username, args.role))
        conn.commit()
        print(f"user created: {args.username} ({args.role})")
    except sqlite3.IntegrityError:
        print(f"user already exists: {args.username}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from . import transfer
    from .schemas import ENTITIES

    if args.entity not in ENTITIES:
        print(f"unknown entity '{args.entity}'", file=sys.stderr)
        return 1
    conn = db.connect()
    data, name, _mime = transfer.export_bytes(
        conn, ENTITIES[args.entity], {"page_size": args.limit}, args.format, None, args.lang)
    conn.close()
    Path(args.out).write_bytes(data)
    print(f"wrote {args.out} ({len(data) / 1024:.0f} KB)")
    return 0


def _utf8_console() -> None:
    """Arabic text must not crash a legacy Windows console (cp1256/cp1252)."""
    import sys
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def cmd_bulk(args) -> int:
    """Append a large synthetic dataset (deterministic for a given seed)."""
    from . import bulk, db

    conn = db.connect()
    counts = bulk.generate(
        conn,
        profile=args.profile,
        persons=args.persons,
        institutions=args.institutions,
        places=args.places,
        sources=args.sources,
        events=args.events,
        rel_per_person=args.relationships_per_person,
        seed=args.seed,
        progress=not args.quiet,
    )
    print()
    print("inserted:")
    for key, val in counts.items():
        print(f"  {key:<22} {val:>9,}")
    print()
    print("dataset now holds:")
    for key, val in bulk.summary(conn).items():
        print(f"  {key:<22} {val:>9,}")
    conn.close()
    return 0


def cmd_tidy_places(args) -> int:
    """Repair placeholder and duplicate place names (dry-run unless --apply)."""
    from . import db, placeclean

    conn = db.connect()
    plan = placeclean.tidy(conn, apply=args.apply, actor=args.actor)
    print(f"scanned {plan.scanned:,} places across {plan.branches:,} branches")
    print(f"renames planned: {len(plan.renames):,}")
    for r in plan.renames[: args.show]:
        print("  " + r.as_row())
    if len(plan.renames) > args.show:
        print(f"  … {len(plan.renames) - args.show:,} more")
    if args.apply:
        print("applied (each rename is in the audit trail)")
        conn.close()
        return 0
    conn.close()
    if plan.renames:
        print("dry run — re-run with --apply to write these changes")
    return 0


def cmd_geocode_places(args) -> int:
    """Reconcile place coordinates with the local gazetteer (dry run by default)."""
    from . import db
    from .geo import georef

    conn = db.connect()
    plan = georef.plan(conn)
    print(f"scanned {plan.scanned:,} places")
    print(f"  already within 25 km of the gazetteer city   {len(plan.within):>6,}")
    print(f"  coordinates to write                         {len(plan.proposals):>6,}")
    print(f"  name / country conflicts (left alone)        {len(plan.conflicts):>6,}")
    print(f"  ambiguous names (left alone)                 {len(plan.ambiguous):>6,}")
    print(f"  not in the gazetteer (left alone)            {len(plan.unmatched):>6,}")
    for prop in plan.proposals[: args.show]:
        print("  " + prop.as_row())
    if len(plan.proposals) > args.show:
        print(f"  … {len(plan.proposals) - args.show:,} more")
    if plan.conflicts and args.show:
        print("\nname / country conflicts (a human must decide, nothing is written):")
        for c in plan.conflicts[: args.show]:
            print(f"  {c['code']}  {c['name']}  → record country {c['country']}, "
                  f"gazetteer has {', '.join(c['gazetteer'])}")
    if args.apply and plan.proposals:
        written = georef.apply_plan(conn, plan.proposals, actor=args.actor)
        print(f"applied {written:,} coordinate updates (audited in change_log)")
    elif plan.proposals:
        print("dry run — re-run with --apply to write these coordinates")
    conn.close()
    return 0


def cmd_check_integrity(args) -> int:
    """Report structural problems in the data; --fix repairs the safe ones."""
    from . import db, integrity

    conn = db.connect()
    problems = integrity.scan(conn)
    lines = integrity.summary(problems)
    counts = integrity_tables(conn)
    print("records: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    if not lines:
        print("no structural problems found")
    else:
        print("problems found:")
        for line in lines:
            print("  " + line)
    behind = problems.get("sequences_behind:detail") or []
    if behind:
        print("  sequences behind the codes in use: " + ", ".join(map(str, behind)))
    if args.fix:
        result = integrity.repair(conn, dry_run=False)
        print("\nrepairs written:")
        for label, n in result["plan"].items():
            if n:
                print(f"  {n:>6}  {label}")
        remaining = result["after"]
        if any(v for k, v in remaining.items()
               if isinstance(v, int) and not k.endswith(":detail")):
            print("\nstill open (needs a human decision):")
            for line in result["problems_after"]:
                print("  " + line)
        else:
            print("\nall structural problems resolved")
    elif lines:
        print("\ndry run — re-run with --fix to repair what is safe to repair")
    conn.close()
    return 0


def integrity_tables(conn) -> dict:
    from .schemas import ENTITIES

    out = {}
    for key, spec in ENTITIES.items():
        out[key] = conn.execute(
            f"SELECT COUNT(*) FROM {spec.table} WHERE deleted_at IS NULL").fetchone()[0]
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="siraj", description="SIRAJ research registry")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create or upgrade the database")
    s.add_argument("--demo", action="store_true", help="load the synthetic demo dataset")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("serve", help="run the web application")
    s.add_argument("--host", default=os.environ.get("SIRAJ_HOST", "0.0.0.0"))
    s.add_argument("--port", type=int, default=int(os.environ.get("SIRAJ_PORT", "8000")))
    s.add_argument("--log-level", default="info")
    s.add_argument("--demo", action="store_true", default=None)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("migrate", help="apply pending migrations")
    s.set_defaults(func=cmd_migrate)
    s = sub.add_parser("reindex", help="rebuild the search index")
    s.set_defaults(func=cmd_reindex)
    s = sub.add_parser("backup", help="write a consistent snapshot ZIP")
    s.add_argument("-o", "--out")
    s.set_defaults(func=cmd_backup)
    s = sub.add_parser("stats", help="print record counts")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("user", help="create an application user")
    s.add_argument("username")
    s.add_argument("role", choices=["viewer", "researcher", "reviewer", "admin"],
                   nargs="?", default="researcher")
    s.set_defaults(func=cmd_user)

    s = sub.add_parser("bulk", help="append a large synthetic dataset (volume testing)")
    s.add_argument("--profile", default="large", choices=["small", "large", "huge"])
    s.add_argument("--persons", type=int)
    s.add_argument("--institutions", type=int)
    s.add_argument("--places", type=int)
    s.add_argument("--sources", type=int)
    s.add_argument("--events", type=int)
    s.add_argument("--relationships-per-person", type=float, dest="relationships_per_person")
    s.add_argument("--seed", type=int, default=20261101,
                   help="same seed → same dataset (default 20261101)")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(func=cmd_bulk)

    s = sub.add_parser("tidy-places",
                       help="repair placeholder / duplicate place names (dry run by default)")
    s.add_argument("--apply", action="store_true", help="write the plan to the database")
    s.add_argument("--actor", default="maintenance", help="name recorded in the audit trail")
    s.add_argument("--show", type=int, default=20, help="how many renames to print")
    s.set_defaults(func=cmd_tidy_places)

    s = sub.add_parser("geocode-places",
                       help="reconcile place coordinates with the local gazetteer "
                            "(dry run by default)")
    s.add_argument("--apply", action="store_true", help="write the coordinates")
    s.add_argument("--actor", default="maintenance", help="name recorded in the audit trail")
    s.add_argument("--show", type=int, default=15, help="how many proposals to print")
    s.set_defaults(func=cmd_geocode_places)

    s = sub.add_parser("check-integrity",
                       help="report structural data problems (dry run by default)")
    s.add_argument("--fix", action="store_true", help="repair the problems that are safe to fix")
    s.set_defaults(func=cmd_check_integrity)

    s = sub.add_parser("export", help="export an entity to a file")
    s.add_argument("entity")
    s.add_argument("out")
    s.add_argument("--format", default="xlsx", choices=["xlsx", "csv", "tsv", "json"])
    s.add_argument("--lang", default="ar", choices=["ar", "en", "both"])
    s.add_argument("--limit", type=int, default=10000)
    s.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
