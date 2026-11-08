"""Military Organization — bulk fictional dataset (stress & soak loader).

Generates a LARGE, deterministic, rule-clean fictional dataset through the
real service layer so that every rule, index, counter and read model is
exercised at volume.  EVERY generated name is invented and tagged
``(fictional)`` — nothing here depicts any real military organization.

Record completeness varies deliberately (design goal: exercise every UI and
pipeline state):

* **full**    — every optional field filled
* **partial** — some optional fields filled
* **minimal** — only required/essential fields

Rule-relevant and structural fields (tree links, chronology, current-pointer
flags) are always set correctly regardless of profile, so the dataset stays
rule-clean while optional metadata varies.  Deterministic: the same scale
always produces the same dataset.

Used by ``python -m app.military.cli bulk [--scale N]``.
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

_KEEP = {"full": 1.0, "partial": 0.5, "minimal": 0.0}


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


def _profile(rng: random.Random) -> str:
    r = rng.random()
    return "full" if r < 0.38 else ("partial" if r < 0.72 else "minimal")


def _vary(rng: random.Random, optional: dict[str, Any],
          counters: dict[str, int]) -> dict[str, Any]:
    """Apply a completeness profile to the optional-field dict."""
    profile = _profile(rng)
    counters[profile] = counters.get(profile, 0) + 1
    keep = _KEEP[profile]
    return {k: v for k, v in optional.items()
            if v is not None and rng.random() < keep}


def load_bulk(conn, scale: int = 7000, actor: str = "bulk-loader") -> dict[str, Any]:
    """Load ~`scale` fictional records in dependency order (rule-clean)."""
    if scale < 200:
        scale = 200
    seed.ensure_country_vocab(conn)   # country fields link to the vocabulary
    rng = random.Random(20261107)
    counts: dict[str, int] = {}
    profiles: dict[str, int] = {}

    def add(entity: str, optional: dict[str, Any] | None = None,
            **payload: Any) -> dict[str, Any]:
        if optional is not None:
            payload.update(_vary(rng, optional, profiles))
        rec = service.create(conn, entity, payload, actor)
        counts[entity] = counts.get(entity, 0) + 1
        return rec

    # ---- region tree (depth 4) ----------------------------------------
    regions: list[dict[str, Any]] = []
    theaters = [add("region",
                    {"region_type": "Theater",
                     "country": "Republic of Aldervale (fictional)",
                     "description": "Top-level fictional theatre command."},
                    name=f"{_name(rng, 'Theater', i)}")
                for i in range(max(3, scale // 600))]
    for i in range(max(8, scale // 120)):
        parent = rng.choice(theaters)
        district = add("region",
                       {"region_type": "Region",
                        "country": "Republic of Aldervale (fictional)",
                        "description": "Fictional territorial district."},
                       name=_name(rng, "District", i), parent_id=parent["id"])
        regions.append(district)
        for j in range(2):
            sector = add("region",
                         {"region_type": "Zone",
                          "country": "Republic of Aldervale (fictional)",
                          "description": "Fictional operational sector."},
                         name=_name(rng, "Sector", i * 10 + j),
                         parent_id=district["id"])
            regions.append(sector)
            if j == 0 and rng.random() < 0.5:
                regions.append(add("region",
                                   {"region_type": "Area",
                                    "country": "Republic of Aldervale (fictional)",
                                    "description": "Fictional sub-area."},
                                   name=_name(rng, "Area", i * 100 + j),
                                   parent_id=sector["id"]))

    # ---- divisions + classifications -----------------------------------
    divisions = [add("division",
                     {"division_type": rng.choice(
                         ["Mechanized", "Armored", "Infantry", "Artillery",
                          "Support", "Airborne"]),
                      "formation_date": _date(rng, 1990, 2015),
                      "headquarters": _name(rng, "Camp", i),
                      "description": "Fictional divisional formation."},
                     name=_name(rng, "Division", i),
                     region_id=rng.choice(regions)["id"])
                 for i in range(max(10, scale // 350))]
    classifications = [add("classification",
                           {"category": rng.choice(["Combat", "Support",
                                                    "Reserve", "Training"]),
                            "readiness_tier": rng.choice(["High", "Medium", "Low"]),
                            "description": "Fictional readiness classification."},
                           name=f"{rng.choice(_ADJ)} {rng.choice(['Line', 'Support', 'Reserve', 'Training'])} Class-{i}{FICTIONAL_TAG}")
                       for i in range(max(12, scale // 300))]

    # ---- commanders -----------------------------------------------------
    ranks = ["General", "Brigadier General", "Colonel", "Lieutenant Colonel",
             "Major", "Captain", "Lieutenant"]
    # registry individuals to link commanders to (a commander is a person
    # first); when the bulk loader runs alone the link is simply omitted
    person_ids = [r["id"] for r in
                  conn.execute("SELECT id FROM person ORDER BY id").fetchall()]
    commanders = [add("commander",
                      {"person_id": rng.choice(person_ids) if person_ids else None,
                       "rank_title": rng.choice(ranks),
                       "branch": rng.choice(["Army", "Air Force", "Navy", "Joint"]),
                       "commission_date": _date(rng, 1992, 2018),
                       "status": rng.choices(["Active", "Reserve", "Retired"],
                                             weights=[7, 2, 1])[0],
                       "biography": "FICTIONAL biography — invented career "
                                    "record for demonstration purposes."},
                      full_name=f"{rng.choice(ranks)} {rng.choice(_PLACES)} {i}{FICTIONAL_TAG}")
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
        u = add("unit",
                {"code": f"{rng.choice(_ADJ)[:2].upper()}-{i}",
                 "classification_id": rng.choice(classifications)["id"],
                 "division_id": rng.choice(divisions)["id"],
                 "region_id": rng.choice(regions)["id"],
                 "commander_id": rng.choice(commanders)["id"],
                 "role": rng.choice(["Line Infantry", "Logistics", "Reconnaissance",
                                     "Territorial Defence", "Training", "Support"]),
                 "status": rng.choices(
                     ["Active", "Training", "Standby", "Mobilized", "Attached",
                      "Reserve", "Reorganizing", "Stand-down", "Disbanded"],
                     weights=[5, 1, 1, 1, 1, 1, 1, 1, 1])[0],
                 "direct_personnel": rng.randint(8, 140),
                 "formation_date": _date(rng, 1995, 2020),
                 "headquarters": _name(rng, "Outpost", i),
                 "latitude": round(rng.uniform(33.5, 37.5), 5),
                 "longitude": round(rng.uniform(35.5, 41.5), 5),
                 "geometry_source": rng.choice(
                     ["map pick", "typed coordinates", "grid reference"]),
                 "image_url": f"https://archive.example.org/emblems/unit-{i}.svg",
                 "image_alt": f"Emblem of fictional unit {i} (bulk-generated)",
                 "notes": "FICTIONAL unit record (bulk-generated)."},
                name=_name(rng, echelons[depth], i),
                echelon=echelons[depth],
                parent_id=parent["id"] if parent else None)
        u["depth"] = depth
        units.append(u)
        if depth < len(echelons) - 1:
            can_parent.append(u)

    # ---- armament + holdings -------------------------------------------
    armaments = [add("armament",
                     {"category": rng.choice(["Weapons", "Vehicles", "Artillery",
                                              "Aircraft", "Communications",
                                              "Support"]),
                      "specification": "FICTIONAL generic specification data.",
                      "origin_country": "Republic of Aldervale (fictional)",
                      "description": "FICTIONAL armament catalogue entry."},
                     name=_name(rng, rng.choice(
                         ["Rifle", "Carrier", "Mortar", "Radio", "Launcher",
                          "Vehicle", "Sensor"]), i))
                 for i in range(max(24, scale // 90))]
    held: set[tuple[int, int]] = set()
    for _i in range(max(200, int(scale * 0.24))):
        unit = rng.choice(units)
        arm = rng.choice(armaments)
        if (unit["id"], arm["id"]) in held:
            continue
        held.add((unit["id"], arm["id"]))
        add("holding",
            {"condition": rng.choices(["Serviceable", "Limited",
                                       "Unserviceable", "In Refit"],
                                      weights=[7, 2, 1, 1])[0],
             "acquisition_year": rng.randint(2005, 2025),
             "notes": "FICTIONAL holdings entry."},
            unit_id=unit["id"], armament_id=arm["id"], quantity=rng.randint(1, 300))

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
        start = _date(rng, 2015, 2026)
        optional: dict[str, Any] = {
            "deployment_type": rng.choice(["Operational", "Training",
                                           "Humanitarian", "Peacekeeping",
                                           "Reserve"]),
            "location": _name(rng, "Zone", i),
            "latitude": round(rng.uniform(33.5, 37.5), 5),
            "longitude": round(rng.uniform(35.5, 41.5), 5),
            "geometry_source": rng.choice(
                ["map pick", "typed coordinates", "grid reference"]),
            "area_of_operations": _name(rng, "Corridor", i),
            "notes": "FICTIONAL deployment record."}
        payload = dict(name=_name(rng, "Operation", i),
                       unit_id=unit["id"], start_date=start,
                       status=status,
                       is_current=want_current and status in ("Planned", "Active"))
        if status == "Completed":
            payload["end_date"] = _end_after(rng, start)   # rule: completed_needs_end
        deployments.append(add("deployment", optional, **payload))

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
        start = _date(rng, 2016, 2026)
        optional: dict[str, Any] = {
            "mission_type": rng.choice(["Combat", "Reconnaissance", "Logistics",
                                        "Training", "Humanitarian",
                                        "Peacekeeping"]),
            "deployment_id": dep["id"],
            "status": status,
            "area": _name(rng, "Sector", i),
            "description": "FICTIONAL mission description.",
            "notes": "FICTIONAL mission record."}
        payload = dict(name=_name(rng, "Mission", i),
                       unit_id=unit["id"], start_date=start)
        if status == "Executed":
            payload["end_date"] = _end_after(rng, start, 365)  # executed_needs_end
        add("mission", optional, **payload)

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
        add("training",
            {"training_type": rng.choice(["Exercise", "Course", "Certification",
                                          "Drill", "Joint Exercise"]),
             "lead_trainer": _name(rng, "Instructor", i),
             "assessment": rng.choice(["Excellent", "Satisfactory",
                                       "Needs Improvement", "Unsatisfactory"]),
             "location": _name(rng, "Range", i),
             "notes": "FICTIONAL training record."},
            exercise_name=_name(rng, "Exercise", i), unit_id=unit["id"],
            start_date=start, end_date=e.isoformat(),
            duration_days=(e - s).days + 1,
            participant_count=rng.randint(0, cap))

    # ---- assessed leadership qualities (basis kept — rule-clean) ----------
    # Assessed qualities set leaders apart.  The basis trio is rule-required
    # (basis_required), so `assessed_by` travels in the payload — never the
    # optional dict — while level / date / source / evidence vary by the
    # completeness profile like every other entity.
    from .vocab import LEADERSHIP_QUALITIES
    quals = [code for code, _labels in LEADERSHIP_QUALITIES]
    assessors = ["Board of Officers", "Inspectorate General",
                 "After-Action Review", "Staff College", "Higher Headquarters"]
    for i, c in enumerate(commanders):
        for q in (quals[i % len(quals)], quals[(i + 5) % len(quals)]):
            optional: dict[str, Any] = {
                "level": rng.choice(["Exceptional", "Outstanding",
                                     "Proficient", "Developing"]),
                "assessed_at": _date(rng, 2015, 2025),
                "source": _name(rng, "Board", i),
                "evidence_note": "FICTIONAL assessment evidence."}
            add("trait", optional,
                commander_id=c["id"], quality=q,
                assessed_by=assessors[i % len(assessors)])

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
        payload: dict[str, Any] = {
            "unit_id": unit["id"], "commander_id": rng.choice(commanders)["id"],
            "role": role,
            "assigned_date": f"{start_year:04d}-{rng.randint(1, 12):02d}-01",
            "is_current": False}
        if rng.random() < 0.4:
            payload["relieved_date"] = \
                f"{min(start_year + rng.randint(1, 4), 2026):04d}-12-31"
        else:
            payload["is_current"] = rng.random() < 0.3
        payload.update(_vary(rng, {"notes": "FICTIONAL appointment record."},
                             profiles))
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
        add("note",
            {"note_at": _date(rng, 2020, 2026)},
            entity_type=etype, target_id=tid,
            note_text=f"Bulk-generated FICTIONAL note {i}: routine demonstration record.",
            author="bulk-loader")

    conn.execute("INSERT INTO mil_meta (key, value) VALUES ('bulk_loaded', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (now_iso(),))
    return {"loaded": True, "fictional": True,
            "disclaimer": seed.FICTIONAL_DISCLAIMER,
            "scale": scale, "counts": counts,
            "profiles": profiles,
            "total": sum(counts.values())}
