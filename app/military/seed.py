"""Military Organization — fictional sample dataset (design record §12.4).

EVERY name, place, unit, operation and person below is FICTIONAL and exists
only to demonstrate the data model.  Nothing here depicts a real military
organization.  The sample is written strictly against the business rules so
it doubles as a living example for the Appendix C verification checklist.
"""
from __future__ import annotations

from typing import Any

from . import rules
from .dbm import now_iso

FICTIONAL_DISCLAIMER = (
    "ALL sample data is FICTIONAL. Every unit, commander, place, deployment and "
    "operation shown here is invented for demonstration purposes and does not "
    "depict any real military organization."
)

_MARK = "sample_loaded"


def _date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


# The fictional demo world's country — a vocabulary entry like any other, so
# country fields link to the supplementary table exactly as real countries do.
FICTIONAL_COUNTRY = {
    "code": "XX",
    "label_en": "Republic of Aldervale (fictional)",
    "label_ar": "جمهورية ألدرفال (خيالية)",
}


def ensure_country_vocab(conn) -> str:
    """Ensure the fictional country exists in the ``country`` vocabulary and
    map legacy free-text country values onto its code.  Idempotent."""
    row = conn.execute("SELECT id FROM lookup WHERE domain='country' AND code=?",
                       (FICTIONAL_COUNTRY["code"],)).fetchone()
    if not conn.execute("SELECT 1 FROM lookup_domain WHERE domain='country'").fetchone():
        conn.execute(
            "INSERT INTO lookup_domain (domain, label_en, label_ar, sort_order,"
            " is_system) VALUES ('country', 'Country', 'البلد', 50, 1)")
    if not row:
        conn.execute(
            "INSERT INTO lookup (domain, code, label_en, label_ar, sort_order,"
            " color, meta, is_active, is_system, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,0,?,?)",
            ("country", FICTIONAL_COUNTRY["code"], FICTIONAL_COUNTRY["label_en"],
             FICTIONAL_COUNTRY["label_ar"], 9999, "slate",
             '{"fictional": true, "iso2": "XX"}', 1,
             now_iso(), now_iso()))
    # rows written before the fields linked to the vocabulary kept free text
    for table, col in (("region", "country"), ("armament", "origin_country")):
        conn.execute(
            f"UPDATE {table} SET {col}=? WHERE {col} IN (?, ?)",
            (FICTIONAL_COUNTRY["code"], FICTIONAL_COUNTRY["label_en"],
             "Aldervale (fictional)"))
    return FICTIONAL_COUNTRY["code"]


def ensure_leadership_vocab(conn) -> str:
    """Seed the leadership quality/level vocabularies — bilingual, idempotent.

    Qualities and levels are data (lookup rows), owner-reviewable like every
    other vocabulary; assessment rows store their codes.
    """
    from . import vocab as v
    for domain, (en, ar, sort_order) in (
        (v.LEADERSHIP_QUALITY_DOMAIN,
         ("Leadership Quality", "الصفة القيادية", 80)),
        (v.LEADERSHIP_LEVEL_DOMAIN,
         ("Leadership Level", "مستوى القيادة", 81)),
    ):
        if not conn.execute(
                "SELECT 1 FROM lookup_domain WHERE domain=?", (domain,)).fetchone():
            conn.execute(
                "INSERT INTO lookup_domain (domain, label_en, label_ar,"
                " sort_order, is_system) VALUES (?, ?, ?, ?, 1)",
                (domain, en, ar, sort_order))
    now = now_iso()
    for i, (code, label_ar) in enumerate(v.LEADERSHIP_QUALITIES):
        if not conn.execute(
                "SELECT 1 FROM lookup WHERE domain=? AND code=?",
                (v.LEADERSHIP_QUALITY_DOMAIN, code)).fetchone():
            conn.execute(
                "INSERT INTO lookup (domain, code, label_en, label_ar,"
                " sort_order, color, is_active, is_system, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,1,0,?,?)",
                (v.LEADERSHIP_QUALITY_DOMAIN, code, code, label_ar,
                 10 + i * 10, "slate", now, now))
    for code, label_ar, color, sort_order in v.LEADERSHIP_LEVELS:
        if not conn.execute(
                "SELECT 1 FROM lookup WHERE domain=? AND code=?",
                (v.LEADERSHIP_LEVEL_DOMAIN, code)).fetchone():
            conn.execute(
                "INSERT INTO lookup (domain, code, label_en, label_ar,"
                " sort_order, color, is_active, is_system, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,1,0,?,?)",
                (v.LEADERSHIP_LEVEL_DOMAIN, code, code, label_ar,
                 sort_order, color, now, now))
    return v.LEADERSHIP_QUALITY_DOMAIN


def load_sample(conn, force: bool = False, actor: str = "sample-loader") -> dict[str, Any]:
    """Load the fictional dataset through the real service layer (idempotent)."""
    from . import service  # late import: service imports seed only via api

    marker = conn.execute(
        "SELECT value FROM mil_meta WHERE key = ?", (_MARK,)).fetchone()
    if marker and not force:
        return {"skipped": True, "fictional": True, "disclaimer": FICTIONAL_DISCLAIMER,
                "message": "sample data already loaded; pass force=true to reset"}
    if marker and force:
        clear_sample(conn, actor, keep_marker=True)

    ensure_country_vocab(conn)

    counts: dict[str, int] = {}

    def add(entity: str, **payload: Any) -> dict[str, Any]:
        rec = service.create(conn, entity, payload, actor)
        counts[entity] = counts.get(entity, 0) + 1
        return rec

    # --- regions (self-tree) ------------------------------------------------
    theater = add("region", name="Northern Territorial Command", region_type="Theater",
                  country="Republic of Aldervale (fictional)",
                  description="Fictional theatre-level command area.")
    district = add("region", name="District Aldervale", region_type="Region",
                   parent_id=theater["id"], country="Republic of Aldervale (fictional)")
    sector = add("region", name="Sector Brena", region_type="Zone",
                 parent_id=district["id"], country="Republic of Aldervale (fictional)")
    add("region", name="Coastal Watch Zone", region_type="Area",
        parent_id=theater["id"], country="Republic of Aldervale (fictional)")

    # --- divisions + classifications ---------------------------------------
    mech = add("division", name="3rd Mechanized Division", region_id=district["id"],
               division_type="Mechanized", formation_date=_date(1998, 4, 12),
               headquarters="Fort Kessamar (fictional)")
    support = add("division", name="8th Support Division", region_id=district["id"],
                  division_type="Support", formation_date=_date(2003, 9, 1),
                  headquarters="Camp Derrowan (fictional)")
    line_cls = add("classification", name="Line Infantry — Tier Alpha",
                   category="Combat", readiness_tier="High",
                   description="Front-line infantry classification (fictional).")
    support_cls = add("classification", name="Support — Tier Bravo",
                      category="Support", readiness_tier="Medium",
                      description="Logistics and support classification (fictional).")
    reserve_cls = add("classification", name="Reserve — Tier Charlie",
                      category="Reserve", readiness_tier="Low",
                      description="Reserve formation classification (fictional).")

    # --- commanders (fictional people) -------------------------------------
    vossen = add("commander", full_name="Brig. Gen. Mara Vossen (fictional)",
                 rank_title="Brigadier General", branch="Army",
                 commission_date=_date(1996, 7, 1), status="Active",
                 biography="FICTIONAL officer biography for demonstration only.")
    kalvere = add("commander", full_name="Col. Idris Kalvere (fictional)",
                  rank_title="Colonel", branch="Army",
                  commission_date=_date(1999, 3, 15), status="Active")
    rendane = add("commander", full_name="Lt. Col. Sela Rendane (fictional)",
                  rank_title="Lieutenant Colonel", branch="Army",
                  commission_date=_date(2004, 6, 20), status="Reserve")
    add("commander", full_name="Maj. Oren Talvik (fictional)",
        rank_title="Major", branch="Army",
        commission_date=_date(2010, 1, 10), status="Retired")

    # --- assessed leadership qualities (the demo leadership layer) ----------
    # What sets a leader apart: qualities WITH a basis, on the flagship
    # commander so the profile fan and level chips render in the sample world.
    add("trait", commander_id=vossen["id"], quality="Strategic Vision",
        level="Exceptional", assessed_by="Higher Headquarters (fictional)",
        assessed_at=_date(2024, 5, 12),
        evidence_note="FICTIONAL evidence: authored the territorial defence "
                      "concept later adopted theatre-wide.",
        source="Annual Assessment Board (fictional)")
    add("trait", commander_id=vossen["id"], quality="Leadership Under Fire",
        level="Outstanding", assessed_by="After-Action Review (fictional)",
        assessed_at=_date(2025, 2, 8),
        evidence_note="FICTIONAL evidence: held the brigade together through "
                      "the Brena floods of the sample storyline.",
        source="After-action review (fictional)")
    add("trait", commander_id=vossen["id"], quality="Logistics Mastery",
        level="Proficient", assessed_by="Inspectorate General (fictional)",
        assessed_at=_date(2025, 9, 30),
        evidence_note="FICTIONAL evidence: reorganised the supply chain so no "
                      "company went unfed during the sample deployment.")
    add("trait", commander_id=kalvere["id"], quality="Discipline",
        level="Outstanding", assessed_by="Board of Officers (fictional)",
        assessed_at=_date(2025, 6, 14),
        evidence_note="FICTIONAL evidence: the cleanest inspection record in "
                      "the sample division for three running years.",
        source="Annual Assessment Board (fictional)")

    # --- unit tree (military force tree) -----------------------------------
    brigade = add("unit", name="12th Territorial Brigade", code="12-TB",
                  echelon="Brigade", classification_id=line_cls["id"],
                  division_id=mech["id"], region_id=district["id"],
                  commander_id=vossen["id"], role="Territorial Defence",
                  status="Active", direct_personnel=120,
                  formation_date=_date(2001, 5, 6),
                  headquarters="Fort Kessamar (fictional)")
    alpha = add("unit", name="1st Infantry Battalion", code="1-IB",
                echelon="Battalion", parent_id=brigade["id"],
                classification_id=line_cls["id"], division_id=mech["id"],
                region_id=district["id"], commander_id=kalvere["id"],
                role="Line Infantry", status="Active", direct_personnel=85,
                headquarters="Outpost Rennick (fictional)")
    bravo = add("unit", name="2nd Support Battalion", code="2-SB",
                echelon="Battalion", parent_id=brigade["id"],
                classification_id=support_cls["id"], division_id=support["id"],
                region_id=sector["id"], role="Logistics",
                status="Training", direct_personnel=60,
                headquarters="Camp Derrowan (fictional)")
    add("unit", name="A Company (Rifle)", code="A-CO", echelon="Company",
        parent_id=alpha["id"], classification_id=line_cls["id"],
        division_id=mech["id"], region_id=district["id"], role="Rifle Company",
        status="Active", direct_personnel=30)
    add("unit", name="B Company (Rifle)", code="B-CO", echelon="Company",
        parent_id=alpha["id"], classification_id=line_cls["id"],
        division_id=mech["id"], region_id=district["id"], role="Rifle Company",
        status="Standby", direct_personnel=28)
    add("unit", name="3rd Reserve Battalion", code="3-RB", echelon="Battalion",
        parent_id=brigade["id"], classification_id=reserve_cls["id"],
        division_id=support["id"], region_id=theater["id"], role="Reserve",
        status="Reserve", direct_personnel=45)

    # --- deployments (dates coherent; one current per unit) -----------------
    dep_active = add("deployment", name="Operation Glass Meadow (fictional)",
                     unit_id=brigade["id"], deployment_type="Operational",
                     start_date=_date(2026, 2, 1), status="Active",
                     is_current=True, location="Sector Brena (fictional)",
                     area_of_operations="Brena river line (fictional)",
                     notes="FICTIONAL operation for demonstration only.")
    dep_done = add("deployment", name="Operation Quiet Ledger (fictional)",
                   unit_id=brigade["id"], deployment_type="Humanitarian",
                   start_date=_date(2024, 6, 3), end_date=_date(2024, 9, 12),
                   status="Completed", is_current=False,
                   location="Coastal Watch Zone (fictional)")
    add("deployment", name="Winter Shield Exercise (fictional)",
        unit_id=alpha["id"], deployment_type="Training",
        start_date=_date(2026, 12, 1), status="Planned",
        location="District Aldervale (fictional)")
    add("deployment", name="Operation Pale Harbor (fictional)",
        unit_id=bravo["id"], deployment_type="Peacekeeping",
        start_date=_date(2025, 3, 1), end_date=_date(2025, 8, 30),
        status="Suspended", is_current=False,
        location="Coastal Watch Zone (fictional)")

    # --- missions (deployment link = same unit or ancestor) -----------------
    add("mission", name="Meadow Sweep Alpha (fictional)", unit_id=brigade["id"],
        mission_type="Reconnaissance", deployment_id=dep_active["id"],
        start_date=_date(2026, 3, 2), end_date=_date(2026, 3, 14),
        status="Executed", area="Brena north bend (fictional)",
        description="FICTIONAL mission record for demonstration only.")
    add("mission", name="Meadow Sweep Bravo (fictional)", unit_id=alpha["id"],
        mission_type="Reconnaissance", deployment_id=dep_active["id"],
        start_date=_date(2026, 4, 4), status="Ongoing",
        area="Brena south bend (fictional)")
    add("mission", name="Ledger Relief Columns (fictional)", unit_id=brigade["id"],
        mission_type="Humanitarian", deployment_id=dep_done["id"],
        start_date=_date(2024, 7, 1), end_date=_date(2024, 7, 21),
        status="Executed", area="Coastal Watch Zone (fictional)")
    add("mission", name="Derrowan Supply Drill (fictional)", unit_id=bravo["id"],
        mission_type="Logistics", start_date=_date(2026, 11, 20),
        status="Planned", area="Camp Derrowan (fictional)")

    # --- armament + unit holdings (UNIQUE unit+armament, quantity > 0) ------
    rifle = add("armament", name="MK-4 Service Rifle (fictional)",
                category="Weapons", specification="5.56 mm, fictional pattern",
                origin_country="Republic of Aldervale (fictional)")
    apc = add("armament", name="GV-7 Armored Carrier (fictional)",
              category="Vehicles", specification="8x8 wheeled carrier (fictional)",
              origin_country="Republic of Aldervale (fictional)")
    mortar = add("armament", name="TR-120 Mortar System (fictional)",
                 category="Artillery", specification="120 mm mortar (fictional)",
                 origin_country="Republic of Aldervale (fictional)")
    radio = add("armament", name="FR-9 Field Radio (fictional)",
                category="Communications", specification="Encrypted VHF set (fictional)",
                origin_country="Republic of Aldervale (fictional)")

    add("holding", unit_id=brigade["id"], armament_id=rifle["id"], quantity=240,
        condition="Serviceable", acquisition_year=2019)
    add("holding", unit_id=brigade["id"], armament_id=apc["id"], quantity=12,
        condition="Serviceable", acquisition_year=2021)
    add("holding", unit_id=alpha["id"], armament_id=rifle["id"], quantity=85,
        condition="Serviceable", acquisition_year=2018)
    add("holding", unit_id=alpha["id"], armament_id=mortar["id"], quantity=6,
        condition="Limited", acquisition_year=2012,
        notes="Two tubes awaiting refit (fictional).")
    add("holding", unit_id=bravo["id"], armament_id=radio["id"], quantity=30,
        condition="Serviceable", acquisition_year=2022)
    add("holding", unit_id=bravo["id"], armament_id=apc["id"], quantity=8,
        condition="In Refit", acquisition_year=2016)

    # --- training (participants <= subtree personnel; duration = dates) ----
    add("training", exercise_name="Glass Meadow Rehearsal (fictional)",
        unit_id=brigade["id"], training_type="Exercise",
        start_date=_date(2026, 1, 12), end_date=_date(2026, 1, 16),
        duration_days=5, participant_count=250,
        lead_trainer="Col. Idris Kalvere (fictional)", assessment="Satisfactory",
        location="District Aldervale (fictional)")
    add("training", exercise_name="Rifle Craft Certification (fictional)",
        unit_id=alpha["id"], training_type="Certification",
        start_date=_date(2026, 5, 4), end_date=_date(2026, 5, 8),
        duration_days=5, participant_count=60,
        lead_trainer="Maj. Oren Talvik (fictional)", assessment="Excellent",
        location="Outpost Rennick (fictional)")
    add("training", exercise_name="Reserve Call-Up Drill (fictional)",
        unit_id=brigade["id"], training_type="Drill",
        start_date=_date(2026, 11, 15), end_date=_date(2026, 11, 15),
        duration_days=1, participant_count=45,
        assessment="Needs Improvement", location="Fort Kessamar (fictional)")

    # --- command appointments (history + exactly one current CO) -----------
    add("assignment", unit_id=brigade["id"], commander_id=rendane["id"],
        role="Commanding Officer", assigned_date=_date(2015, 2, 1),
        relieved_date=_date(2021, 8, 31), is_current=False,
        notes="Historic appointment (fictional).")
    add("assignment", unit_id=brigade["id"], commander_id=vossen["id"],
        role="Commanding Officer", assigned_date=_date(2021, 9, 1),
        is_current=True, notes="Current appointment (fictional).")
    add("assignment", unit_id=brigade["id"], commander_id=kalvere["id"],
        role="Chief of Staff", assigned_date=_date(2022, 1, 10),
        is_current=True)
    add("assignment", unit_id=alpha["id"], commander_id=kalvere["id"],
        role="Commanding Officer", assigned_date=_date(2023, 3, 1),
        is_current=True)

    # --- notes (polymorphic, allowlisted targets) --------------------------
    add("note", entity_type="unit", target_id=brigade["id"],
        note_text="FICTIONAL readiness note: annual evaluation scheduled for December.",
        author="sample-loader", note_at=_date(2026, 10, 2))
    add("note", entity_type="deployment", target_id=dep_active["id"],
        note_text="FICTIONAL operational note: supply corridor review pending.",
        author="sample-loader", note_at=_date(2026, 3, 1))
    add("note", entity_type="commander", target_id=vossen["id"],
        note_text="FICTIONAL personnel note: service biography refreshed for demo.",
        author="sample-loader", note_at=_date(2026, 9, 18))

    conn.execute("INSERT INTO mil_meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (_MARK, now_iso()))
    return {"loaded": True, "fictional": True, "disclaimer": FICTIONAL_DISCLAIMER,
            "counts": counts}


def clear_sample(conn, actor: str = "sample-loader",
                 keep_marker: bool = False) -> dict[str, Any]:
    """Remove all sample records (records only — the audit trail is append-only)."""
    tables = [
        "note", "commander_trait", "command_assignment", "training",
        "unit_armament", "mission",
        "operational_deployment", "military_unit", "commander", "classification",
        "division", "region", "armament",
    ]
    removed = 0
    for table in tables:
        removed += conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        if table in ("military_unit", "region"):
            # self-referencing trees: delete leaves first (rows nobody parents)
            # so parent_id constraints hold row-by-row even under immediate FK
            # enforcement — PRAGMA defer_foreign_keys proved unreliable here
            # (interleaved SELECTs can reset it mid-loop)
            while conn.execute(
                f"DELETE FROM {table} WHERE id NOT IN "
                f"(SELECT parent_id FROM {table} WHERE parent_id IS NOT NULL)"
            ).rowcount:
                pass
        else:
            conn.execute(f"DELETE FROM {table}")
    if not keep_marker:
        conn.execute("DELETE FROM mil_meta WHERE key = ?", (_MARK,))
    conn.execute(
        "INSERT INTO audit_log (actor, action, entity, record_id, docname, summary, "
        "old_json, new_json, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (actor, "clear-sample", "sample", None, None,
         f"cleared {removed} record(s) (audit trail preserved)",
         None, None, now_iso()))
    return {"cleared": True, "removed_records": removed,
            "fictional": True, "disclaimer": FICTIONAL_DISCLAIMER}


def check_sample_rules(conn) -> list[str]:
    """Re-verify the sample against the core invariants (used by `verify`)."""
    problems: list[str] = []
    # one current deployment per unit + pointer sync
    rows = conn.execute(
        "SELECT unit_id, COUNT(*) AS n FROM operational_deployment "
        "WHERE is_current = 1 GROUP BY unit_id HAVING n > 1").fetchall()
    for r in rows:
        problems.append(f"unit {r['unit_id']} has {r['n']} current deployments")
    for u in conn.execute("SELECT id, current_deployment_id FROM military_unit").fetchall():
        if u["current_deployment_id"] is not None:
            dep = conn.execute(
                "SELECT unit_id, is_current FROM operational_deployment WHERE id = ?",
                (u["current_deployment_id"],)).fetchone()
            if not dep or dep["unit_id"] != u["id"] or not dep["is_current"]:
                problems.append(f"unit {u['id']} current_deployment_id pointer is stale")
    # training capacity
    for t in conn.execute("SELECT id, unit_id, participant_count FROM training").fetchall():
        cap = rules.descendant_personnel(conn, t["unit_id"])
        if t["participant_count"] > cap:
            problems.append(f"training {t['id']} exceeds subtree personnel capacity ({cap})")
    # dates
    for table, cols in (("operational_deployment", ("start_date", "end_date")),
                        ("mission", ("start_date", "end_date")),
                        ("command_assignment", ("assigned_date", "relieved_date"))):
        for r in conn.execute(f"SELECT id, * FROM {table}").fetchall():
            s, e = r[cols[0]], r[cols[1]]
            if s and e and e < s:
                problems.append(f"{table} {r['id']} has end before start")
    return problems
