"""Military Organization — bulk fictional dataset (stress & soak loader).

Generates a LARGE, deterministic, rule-clean fictional dataset through the
real service layer so that every rule, index, counter and read model is
exercised at volume.  EVERY generated name is invented and tagged
``(fictional)`` — nothing here depicts any real military organization.

Used by ``python -m app.military.cli bulk [--scale N]`` to surface defects
under load; also handy to fill a demonstration instance with meaningful
volume.  Deterministic: the same scale always produces the same dataset.
"""
from __future__ import annotations

import random
from typing import Any

from . import seed, service
from .dbm import now_iso

FICTIONAL_TAG = " (fictional)"

_PLACES = ["Kessamar", "Derrowan", "Rennick", "Brena", "Aldervale", "Talvik",
           "Vossen", "Kalvere", "Mareth", "Ostrand", "Selvik", "Hadrin",
           "Yverath", "Kolmari", "Dravnik", "Esterholt", "Ravensk", "Bielvik"]
_ADJ = ["Northern", "Southern", "Eastern", "Western", "Upper", "Lower",
        "Highland", "Coastal", "Frontier", "Central", "River", "Border"]


def _name(rng: random.Random, kind: str, idx: int) -> str:
    return f"{kind} {rng.choice(_ADJ)} {rng.choice(_PLACES)}-{idx}{FICTIONAL_TAG}"


def _date(rng: random.Random, y0: int, y1: int) -> str:
    return f"{rng.randint(y0, y1):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"


def _end_after(rng: random.Random, start: str, max_days: int = 730) -> str:
    """A valid end date: 0..max_days after `start`, never past 2026-12-31."""
    from datetime import date as _d
    s = _d.fromisoformat(start)
    e = _d.fromordinal(min(s.toordinal() + rng.randint(0, max_days),
                           _d(2026, 12, 31).toordinal()))
    return e.isoformat()


def load_bulk(conn, scale: int = 7000, actor: str = "bulk-loader") -> dict[str, Any]:
    """Load ~`scale` fictional records in dependency order (rule-clean)."""
    if scale < 200:
        scale = 200
    rng = random.Random(20261107)
    counts: dict[str, int] = {}

    def add(entity: str, **payload: Any) -> dict[str, Any]:
        rec = service.create(conn, entity, payload, actor)
        counts[entity] = counts.get(entity, 0) + 1
        return rec

    # ---- region tree (depth 4) ----------------------------------------
    regions: list[dict[str, Any]] = []
    theaters = [add("region", name=f"{_name(rng, 'Theater', i)}",
                    region_type="Theater",
                    country="Republic of Aldervale (fictional)")
                for i in range(max(3, scale // 600))]
    for i in range(max(8, scale // 120)):
        parent = rng.choice(theaters)
        district = add("region", name=_name(rng, "District", i),
                       region_type="Region", parent_id=parent["id"],
                       country="Republic of Aldervale (fictional)")
        regions.append(district)
        for j in range(2):
            sector = add("region", name=_name(rng, "Sector", i * 10 + j),
                         region_type="Zone", parent_id=district["id"],
                         country="Republic of Aldervale (fictional)")
            regions.append(sector)
            if j == 0 and rng.random() < 0.5:
                regions.append(add("region", name=_name(rng, "Area", i * 100 + j),
                                   region_type="Area", parent_id=sector["id"],
                                   country="Republic of Aldervale (fictional)"))

    # ---- divisions + classifications -----------------------------------
    divisions = [add("division", name=_name(rng, "Division", i),
                     region_id=rng.choice(regions)["id"],
                     division_type=rng.choice(
                         ["Mechanized", "Armored", "Infantry", "Artillery",
                          "Support", "Airborne"]),
                     formation_date=_date(rng, 1990, 2015),
                     headquarters=_name(rng, "Camp", i))
                 for i in range(max(10, scale // 350))]
    classifications = [add("classification", name=f"{rng.choice(_ADJ)} {rng.choice(['Line', 'Support', 'Reserve', 'Training'])} Class-{i}{FICTIONAL_TAG}",
                           category=rng.choice(["Combat", "Support", "Reserve", "Training"]),
                           readiness_tier=rng.choice(["High", "Medium", "Low"]))
                       for i in range(max(12, scale // 300))]

    # ---- commanders -----------------------------------------------------
    ranks = ["General", "Brigadier General", "Colonel", "Lieutenant Colonel",
             "Major", "Captain", "Lieutenant"]
    commanders = [add("commander",
                      full_name=f"{rng.choice(ranks)} {rng.choice(_PLACES)} {i}{FICTIONAL_TAG}",
                      rank_title=rng.choice(ranks),
                      branch=rng.choice(["Army", "Air Force", "Navy", "Joint"]),
                      commission_date=_date(rng, 1992, 2018),
                      status=rng.choices(["Active", "Reserve", "Retired"],
                                         weights=[7, 2, 1])[0])
                  for i in range(max(60, scale // 32))]

    # ---- unit tree: brigade → battalion → company → platoon → squadron --
    echelons = ["Brigade", "Battalion", "Company", "Platoon", "Squadron", "Detachment"]
    n_units = max(150, int(scale * 0.17))
    units: list[dict[str, Any]] = []
    can_parent: list[dict[str, Any]] = []   # units whose echelon may still have children
    for i in range(n_units):
        if not can_parent or rng.random() < 0.12:
            depth = 0
            parent = None
        else:
            parent = rng.choice(can_parent)
            depth = parent["depth"] + 1
        u = add("unit", name=_name(rng, echelons[depth], i),
                code=f"{rng.choice(_ADJ)[:2].upper()}-{i}",
                echelon=echelons[depth],
                parent_id=parent["id"] if parent else None,
                classification_id=rng.choice(classifications)["id"],
                division_id=rng.choice(divisions)["id"],
                region_id=rng.choice(regions)["id"],
                role=rng.choice(["Line Infantry", "Logistics", "Reconnaissance",
                                 "Territorial Defence", "Training", "Support"]),
                status=rng.choices(
                    ["Active", "Training", "Standby", "Mobilized", "Attached",
                     "Reserve", "Reorganizing", "Stand-down", "Disbanded"],
                    weights=[5, 1, 1, 1, 1, 1, 1, 1, 1])[0],
                direct_personnel=rng.randint(8, 140),
                formation_date=_date(rng, 1995, 2020),
                headquarters=_name(rng, "Outpost", i))
        u["depth"] = depth
        units.append(u)
        if depth < len(echelons) - 1:
            can_parent.append(u)

    # ---- armament + holdings -------------------------------------------
    armaments = [add("armament", name=_name(rng, rng.choice(
        ["Rifle", "Carrier", "Mortar", "Radio", "Launcher", "Vehicle", "Sensor"]), i),
        category=rng.choice(["Weapons", "Vehicles", "Artillery", "Aircraft",
                             "Communications", "Support"]),
        origin_country="Republic of Aldervale (fictional)")
        for i in range(max(24, scale // 90))]
    held: set[tuple[int, int]] = set()
    for _i in range(max(200, int(scale * 0.24))):
        unit = rng.choice(units)
        arm = rng.choice(armaments)
        if (unit["id"], arm["id"]) in held:
            continue
        held.add((unit["id"], arm["id"]))
        add("holding", unit_id=unit["id"], armament_id=arm["id"],
            quantity=rng.randint(1, 300),
            condition=rng.choices(["Serviceable", "Limited", "Unserviceable", "In Refit"],
                                  weights=[7, 2, 1, 1])[0],
            acquisition_year=rng.randint(2005, 2025))

    # ---- deployments (≤1 current per unit) -----------------------------
    deployments: list[dict[str, Any]] = []
    current_done: set[int] = set()
    for i in range(max(120, int(scale * 0.12))):
        unit = rng.choice(units)
        want_current = unit["id"] not in current_done and rng.random() < 0.35
        status = rng.choices(["Planned", "Active", "Completed", "Suspended"],
                             weights=[3, 3, 5, 1])[0]
        if want_current and status in ("Planned", "Active"):
            current_done.add(unit["id"])
        elif want_current:
            status = "Active"
            current_done.add(unit["id"])
        payload = dict(
            name=_name(rng, "Operation", i), unit_id=unit["id"],
            deployment_type=rng.choice(["Operational", "Training", "Humanitarian",
                                        "Peacekeeping", "Reserve"]),
            start_date=_date(rng, 2015, 2026),
            status=status,
            is_current=want_current and status in ("Planned", "Active"),
            location=_name(rng, "Zone", i),
            area_of_operations=_name(rng, "Corridor", i))
        if status == "Completed":
            payload["end_date"] = _end_after(rng, payload["start_date"])
        deployments.append(add("deployment", **payload))

    # ---- missions (unit = deployment's unit or a subordinate of it) -----
    by_id = {u["id"]: u for u in units}
    paths = {u["id"]: u["path"] for u in
             conn.execute("SELECT id, path FROM military_unit").fetchall()}
    for i in range(max(140, int(scale * 0.15))):
        dep = rng.choice(deployments)
        dep_path = paths[dep["unit_id"]]
        subs = [u for u in units if paths[u["id"]].startswith(dep_path)]
        unit = rng.choice(subs) if subs else by_id[dep["unit_id"]]
        status = rng.choices(["Planned", "Ongoing", "Executed", "Cancelled"],
                             weights=[3, 2, 5, 1])[0]
        payload = dict(
            name=_name(rng, "Mission", i), unit_id=unit["id"],
            mission_type=rng.choice(["Combat", "Reconnaissance", "Logistics",
                                     "Training", "Humanitarian", "Peacekeeping"]),
            deployment_id=dep["id"],
            start_date=_date(rng, 2016, 2026),
            status=status,
            area=_name(rng, "Sector", i))
        if status == "Executed":
            payload["end_date"] = _end_after(rng, payload["start_date"], 365)
        add("mission", **payload)

    # ---- training (participants within subtree capacity) ---------------
    from datetime import date as _date_cls

    from .rules import descendant_personnel
    for i in range(max(80, int(scale * 0.09))):
        unit = rng.choice(units)
        cap = descendant_personnel(conn, unit["id"])
        if cap <= 0:
            continue
        start = _date(rng, 2018, 2026)
        s = _date_cls.fromisoformat(start)
        e = s.fromordinal(s.toordinal() + rng.randint(0, 12))
        add("training", exercise_name=_name(rng, "Exercise", i),
            unit_id=unit["id"],
            training_type=rng.choice(["Exercise", "Course", "Certification",
                                      "Drill", "Joint Exercise"]),
            start_date=start, end_date=e.isoformat(),
            duration_days=(e - s).days + 1,
            participant_count=rng.randint(0, cap),
            lead_trainer=_name(rng, "Instructor", i),
            assessment=rng.choice(["Excellent", "Satisfactory",
                                   "Needs Improvement", "Unsatisfactory"]),
            location=_name(rng, "Range", i))

    # ---- command appointments (non-overlapping per unit+role) ---------
    roles = ["Commanding Officer", "Deputy Commander", "Chief of Staff",
             "Acting Commander"]
    made = 0
    target_assignments = max(90, int(scale * 0.10))
    attempts = 0
    while made < target_assignments and attempts < target_assignments * 6:
        attempts += 1
        unit = rng.choice(units)
        role = rng.choice(roles)
        start_year = rng.randint(2012, 2024)
        payload = dict(
            unit_id=unit["id"], commander_id=rng.choice(commanders)["id"],
            role=role,
            assigned_date=f"{start_year:04d}-{rng.randint(1, 12):02d}-01",
            is_current=False)
        if rng.random() < 0.4:
            payload["relieved_date"] = f"{min(start_year + rng.randint(1, 4), 2026):04d}-12-31"
        else:
            payload["is_current"] = rng.random() < 0.3
        try:
            add("assignment", **payload)
            made += 1
        except Exception as exc:  # noqa: BLE001
            from .rules import RuleViolation
            if not isinstance(exc, (RuleViolation, service.ServiceError)):
                raise  # a genuine defect, not a rule doing its job

    # ---- notes ---------------------------------------------------------
    targets = ([("unit", u["id"]) for u in rng.sample(units, min(150, len(units)))] +
               [("deployment", d["id"]) for d in rng.sample(deployments, min(80, len(deployments)))] +
               [("commander", c["id"]) for c in rng.sample(commanders, min(60, len(commanders)))])
    for i, (etype, tid) in enumerate(targets):
        add("note", entity_type=etype, target_id=tid,
            note_text=f"Bulk-generated FICTIONAL note {i}: routine demonstration record.",
            author="bulk-loader", note_at=_date(rng, 2020, 2026))

    conn.execute("INSERT INTO mil_meta (key, value) VALUES ('bulk_loaded', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (now_iso(),))
    return {"loaded": True, "fictional": True,
            "disclaimer": seed.FICTIONAL_DISCLAIMER,
            "scale": scale, "counts": counts,
            "total": sum(counts.values())}
