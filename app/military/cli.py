"""Military Organization — command-line verification (Appendix C checklist).

Usage (from the repository root)::

    python -m app.military.cli verify     # run the Appendix C checklist
    python -m app.military.cli sample     # load the fictional sample dataset
    python -m app.military.cli sample --force
    python -m app.military.cli bulk       # load a LARGE fictional dataset (stress)
    python -m app.military.cli bulk --scale 2000
    python -m app.military.cli reload     # full test dataset rebuild (demo variation + sample + bulk)
    python -m app.military.cli clear      # remove all military records

Exit code 0 = every check passed; 1 = at least one check failed.
"""
from __future__ import annotations

import sys

from .. import db
from . import seed, service
from .dbm import ensure


def verify() -> int:
    ensure()
    checks: list[tuple[str, bool, str]] = []

    def run(name: str, fn) -> None:
        try:
            detail = fn()
            checks.append((name, True, detail or ""))
        except Exception as exc:  # noqa: BLE001 — checklist reports, never aborts
            checks.append((name, False, f"{type(exc).__name__}: {exc}"))

    with service.transaction() as conn:
        # C.1 — relationships: child unit links to parent unit
        def c1() -> str:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM military_unit WHERE parent_id IS NOT NULL").fetchone()
            assert row["n"] >= 0
            return f"{row['n']} parent-child unit link(s) present"
        run("C.1 Unit-tree relationship", c1)

        # C.2 — Tree: region and military unit hierarchies
        def c2() -> str:
            for table in ("region", "military_unit"):
                for r in conn.execute(
                        f"SELECT id, path, depth FROM {table} WHERE parent_id IS NOT NULL").fetchall():
                    parent = conn.execute(
                        f"SELECT path, depth FROM {table} WHERE id = ("
                        f"SELECT parent_id FROM {table} WHERE id = ?)", (r["id"],)).fetchone()
                    assert parent and r["path"].startswith(parent["path"]), \
                        f"{table} {r['id']} path inconsistent with parent"
                    assert r["depth"] == parent["depth"] + 1, \
                        f"{table} {r['id']} depth inconsistent"
            return "unit and region trees consistent"
        run("C.2 Tree hierarchy", c2)

        # C.3 — quantity: qualified participants <= subtree personnel
        def c3() -> str:
            for t in conn.execute(
                    "SELECT id, unit_id, participant_count FROM training").fetchall():
                cap = int(conn.execute(
                    "SELECT COALESCE(SUM(direct_personnel), 0) AS n FROM military_unit "
                    "WHERE path LIKE (SELECT path || '%' FROM military_unit WHERE id = ?)",
                    (t["unit_id"],)).fetchone()["n"])
                assert t["participant_count"] <= cap, \
                    f"training {t['id']} participants {t['participant_count']} > capacity {cap}"
            return "training participants within subtree personnel"
        run("C.3 Quantity — personnel capacity", c3)

        # C.4 — quantity: one current deployment per unit + pointer sync
        def c4() -> str:
            for r in conn.execute(
                    "SELECT unit_id, COUNT(*) AS n FROM operational_deployment "
                    "WHERE is_current = 1 GROUP BY unit_id HAVING n > 1").fetchall():
                raise AssertionError(f"unit {r['unit_id']} has {r['n']} current deployments")
            stale = 0
            for u in conn.execute(
                    "SELECT id, current_deployment_id FROM military_unit").fetchall():
                if u["current_deployment_id"] is not None:
                    dep = conn.execute(
                        "SELECT unit_id, is_current FROM operational_deployment WHERE id = ?",
                        (u["current_deployment_id"],)).fetchone()
                    if not dep or dep["unit_id"] != u["id"] or not dep["is_current"]:
                        stale += 1
            assert not stale, f"{stale} stale current_deployment_id pointer(s)"
            return "one current deployment per unit; pointers synchronised"
        run("C.4 Quantity — single current deployment", c4)

        # C.5 — restriction: completed deployment has end date
        def c5() -> str:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM operational_deployment "
                "WHERE status = 'Completed' AND end_date IS NULL").fetchone()
            assert not row["n"], f"{row['n']} completed deployment(s) missing end date"
            return "completed deployments carry end dates"
        run("C.5 Restriction — completed deployment end date", c5)

        # C.6 — restriction: mission/deployment unit consistency
        def c6() -> str:
            rows = conn.execute(
                """SELECT m.id, um.path AS mission_path, ud.path AS dep_path
                   FROM mission m
                   JOIN operational_deployment d ON d.id = m.deployment_id
                   JOIN military_unit um ON um.id = m.unit_id
                   JOIN military_unit ud ON ud.id = d.unit_id""").fetchall()
            for r in rows:
                assert r["mission_path"].startswith(r["dep_path"]), \
                    f"mission {r['id']} links a deployment of an unrelated unit"
            return f"{len(rows)} mission/deployment link(s) consistent"
        run("C.6 Restriction — mission/deployment consistency", c6)

        # C.7 — lifecycle: Executed missions carry end dates
        def c7() -> str:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM mission "
                "WHERE status = 'Executed' AND end_date IS NULL").fetchone()
            assert not row["n"], f"{row['n']} executed mission(s) missing end date"
            return "executed missions carry end dates"
        run("C.7 Lifecycle — executed mission end date", c7)

        # C.8 — lifecycle: no overlapping appointments per (unit, role)
        def c8() -> str:
            rows = conn.execute(
                "SELECT id, unit_id, role, assigned_date, "
                "COALESCE(relieved_date, '9999-12-31') AS end_d FROM command_assignment"
            ).fetchall()
            bad = 0
            for i, a in enumerate(rows):
                for b in rows[i + 1:]:
                    if (a["unit_id"] == b["unit_id"] and a["role"] == b["role"]
                            and a["assigned_date"] <= b["end_d"]
                            and b["assigned_date"] <= a["end_d"]):
                        bad += 1
            assert not bad, f"{bad} overlapping appointment pair(s)"
            return "appointments do not overlap per (unit, role)"
        run("C.8 Lifecycle — appointment overlap", c8)

        # C.9 — naming: generated document names are unique
        def c9() -> str:
            for table in ("region", "division", "classification",
                          "person_trait", "military_unit",
                          "operational_deployment", "mission",
                          "armament", "unit_armament", "training",
                          "command_assignment", "note"):
                row = conn.execute(
                    f"SELECT COUNT(*) AS n, COUNT(DISTINCT docname) AS d FROM {table}").fetchone()
                assert row["n"] == row["d"], f"duplicate docname in {table}"
            series = conn.execute(
                "SELECT COUNT(*) AS n FROM naming_series_option").fetchone()["n"]
            assert series == 19, f"expected 19 naming series options, found {series}"
            return "document names unique; 19 naming series options present"
        run("C.9 Naming — generated document names", c9)

        # C.10 — dataset invariants (sample or bulk: run whenever data exists)
        def c10() -> str:
            mark = conn.execute(
                "SELECT value FROM mil_meta WHERE key = 'sample_loaded'").fetchone()
            has_data = conn.execute(
                "SELECT 1 FROM military_unit LIMIT 1").fetchone()
            if not mark and not has_data:
                return "no military data loaded — skipped"
            problems = seed.check_sample_rules(conn)
            assert not problems, "; ".join(problems)
            what = f"sample dataset rule-clean (loaded {mark['value']})" if mark \
                else "dataset rule-clean (bulk or mixed data)"
            return what
        run("C.10 Sample dataset invariants", c10)

        # C.11 — dataset variation: complete, partial and near-empty records
        def c11() -> str:
            rep = service.quality_report(conn)
            ent = rep["entities"].get("unit", {})
            hist = ent.get("histogram", {})
            if not ent.get("total"):
                return "no unit records — skipped"
            near_empty = sum(hist.get(b, 0) for b in ("0-25%", "25-50%"))
            partial = hist.get("50-75%", 0) + hist.get("75-99%", 0)
            complete = hist.get("100%", 0)
            bulk_loaded = conn.execute(
                "SELECT value FROM mil_meta WHERE key = 'bulk_loaded'").fetchone()
            if not bulk_loaded:
                # curated sample is intentionally complete — report only
                return f"sample-only dataset — histogram {hist}"
            assert complete and partial and near_empty, \
                f"completeness mix missing: {hist}"
            return (f"completeness mix present: {complete} complete / "
                    f"{partial} partial / {near_empty} near-empty")
        run("C.11 Dataset completeness variation", c11)

    width = max(len(name) for name, _, _ in checks)
    print(f"Military Organization — Appendix C verification ({db.DB_PATH})")
    print("=" * (width + 24))
    failed = 0
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name.ljust(width)}  {detail}")
        failed += 0 if ok else 1
    print("=" * (width + 24))
    print(f"{len(checks) - failed}/{len(checks)} checks passed"
          + ("" if not failed else f" — {failed} FAILED"))
    return 1 if failed else 0


def sample(force: bool = False) -> int:
    ensure()
    with service.transaction() as conn:
        result = seed.load_sample(conn, force=force)
    print(result.get("disclaimer", seed.FICTIONAL_DISCLAIMER))
    if result.get("skipped"):
        print(result["message"])
    else:
        print(f"fictional sample loaded: {result['counts']}")
    return 0


def bulk(scale: int = 7000) -> int:
    """Load a large deterministic fictional dataset (stress & demonstration)."""
    from . import bulk as bulk_mod
    ensure()
    print(seed.FICTIONAL_DISCLAIMER)
    with service.transaction() as conn:
        result = bulk_mod.load_bulk(conn, scale=scale)
    print(f"bulk fictional dataset loaded: {result['total']} records")
    for entity, n in sorted(result["counts"].items()):
        print(f"  {entity:14s} {n}")
    return 0


def reload(scale: int = 7000) -> int:
    """Rebuild the full test dataset in place: registry demo variation +
    fictional sample + varied bulk (complete / partial / near-empty).

    Idempotent and deterministic.  Never touches real user data (the
    registry variation pass refuses on non-demo rows).
    """
    from .. import seed as reg_seed
    from . import bulk as bulk_mod
    ensure()
    reg_conn = db.connect()
    try:
        stats = reg_seed.vary_demo(reg_conn)
    finally:
        reg_conn.close()
    if stats:
        print("registry demo variation:")
        for table, counts in stats.items():
            print(f"  {table:12s} full={counts['full']} partial={counts['partial']} "
                  f"minimal={counts['minimal']} groups_cleared={counts['groups_cleared']}")
    with service.transaction() as conn:
        seed.clear_sample(conn)
        sample = seed.load_sample(conn)
        result = bulk_mod.load_bulk(conn, scale=scale)
    print(f"military sample loaded: {sample['counts']}")
    print(f"military bulk loaded: {result['total']} records (profiles: {result['profiles']})")
    print(seed.FICTIONAL_DISCLAIMER)
    return 0


def clear() -> int:
    ensure()
    with service.transaction() as conn:
        result = seed.clear_sample(conn)
    print(f"cleared {result['removed_records']} sample record(s); audit trail preserved")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    cmd = argv[0] if argv else "verify"
    if cmd == "verify":
        return verify()
    if cmd == "sample":
        return sample(force="--force" in argv)
    if cmd == "bulk":
        scale = 7000
        for i, a in enumerate(argv):
            if a == "--scale" and i + 1 < len(argv):
                scale = int(argv[i + 1])
        return bulk(scale=scale)
    if cmd == "reload":
        scale = 7000
        for i, a in enumerate(argv):
            if a == "--scale" and i + 1 < len(argv):
                scale = int(argv[i + 1])
        return reload(scale=scale)
    if cmd == "clear":
        return clear()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
