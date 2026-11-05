"""Place-name hygiene: make every branch of the place tree readable and unique.

Two problems show up in real registries (and used to be produced by the synthetic
generator): placeholder names such as ``City of Mauritania`` and sibling places
that share a name, which makes the tree impossible to read and the duplicates
report noisy.

``tidy(conn, apply=False)`` is pure: it returns a plan.  ``apply=True`` writes the
plan, updates ``place.city`` to match the new English name and appends a
field-level ``change_log`` entry for every rename, so the repair is auditable
exactly like an edit made in the interface.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

PLACEHOLDER = re.compile(r"^City of (?P<country>.+?)(?: \((?P<suffix>[^)]+)\))?$")
# the same placeholder sentence, embedded in the name of a record that points at
# a place ("National Library of City of Indonesia (North) — branch C")
EMBEDDED_EN = re.compile(r"City of [^—,;]+?\s*(?=—|,|;|$)")
EMBEDDED_AR = re.compile(r"مدينة [^—,;]+?\s*(?=—|,|;|$)")
SUFFIXES = [("North", "الشمالية"), ("South", "الجنوبية"),
            ("East", "الشرقية"), ("West", "الغربية")]


@dataclass
class Rename:
    record_id: int
    old_en: str
    new_en: str
    new_ar: str | None
    reason: str
    entity_type: str = "place"

    def as_row(self) -> str:
        return (f"{self.entity_type} #{self.record_id}  {self.old_en!r} → "
                f"{self.new_en!r}  ({self.reason})")


@dataclass
class Plan:
    renames: list[Rename] = field(default_factory=list)
    branches: int = 0
    scanned: int = 0

    def __len__(self) -> int:
        return len(self.renames)


# records whose *name* was built from a place name; they keep the old placeholder
# until the place is renamed, so they are repaired in the same pass
NAME_LINKED = (("institution", "place_id", "name_en", "name_ar"),
               ("event", "place_id", "title_en", "title_ar"))


def _city_pools(conn: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """Country code → the real city list the generator knows about."""
    try:
        from .bulk import CITY_BY_COUNTRY
    except Exception:                                    # pragma: no cover
        return {}
    return CITY_BY_COUNTRY


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _country_codes(conn: sqlite3.Connection) -> dict[str, str]:
    """country label (lower-case, English or Arabic) → ISO code."""
    out: dict[str, str] = {}
    try:
        rows = conn.execute(
            "SELECT code, label_en, label_ar FROM lookup "
            "WHERE domain = (SELECT domain FROM lookup WHERE code='JO' LIMIT 1)").fetchall()
    except sqlite3.Error:                                # pragma: no cover
        rows = conn.execute("SELECT code, label_en, label_ar FROM lookup").fetchall()
    for r in rows:
        code = r["code"] if isinstance(r, sqlite3.Row) else r[0]
        for label in (r["label_en"], r["label_ar"]) if isinstance(r, sqlite3.Row) else (r[1], r[2]):
            if label:
                out[str(label).strip().lower()] = code
    return out


def tidy(conn: sqlite3.Connection, apply: bool = False, actor: str = "maintenance") -> Plan:
    conn.row_factory = sqlite3.Row
    places = conn.execute(
        "SELECT id, name_en, name_ar, city, parent_place_id, country_id "
        "FROM place WHERE deleted_at IS NULL ORDER BY parent_place_id, id").fetchall()
    pools = _city_pools(conn)
    by_country_id: dict[int, str] = {}
    for p in places:
        if p["country_id"] and p["country_id"] not in by_country_id:
            by_country_id[p["country_id"]] = None
    for cid in list(by_country_id):
        row = conn.execute("SELECT code FROM lookup WHERE id=?", (cid,)).fetchone()
        if row:
            by_country_id[cid] = row["code"]

    plan = Plan(scanned=len(places))
    # group siblings so a name can be de-duplicated inside its own branch only
    siblings: dict[int | None, list[sqlite3.Row]] = {}
    for p in places:
        siblings.setdefault(p["parent_place_id"], []).append(p)

    for parent_id, group in siblings.items():
        if parent_id is None:
            continue
        plan.branches += 1
        used: set[str] = set()
        renamed_names: set[str] = set()
        for p in group:
            name_en = (p["name_en"] or "").strip()
            name_ar = (p["name_ar"] or "").strip()
            code = by_country_id.get(p["country_id"]) or ""
            pool = pools.get(code) or []
            match = PLACEHOLDER.match(name_en)
            if match and pool:
                # a placeholder: replace it with a real city of the same country
                # (comparison is case-insensitive — `used` is always lower-cased)
                pick = next(((a, e) for a, e in pool if e.lower() not in used), None)
                if pick:
                    plan.renames.append(Rename(p["id"], name_en, pick[1], pick[0],
                                               "placeholder replaced with a real city"))
                    used.add(pick[1].lower())
                    renamed_names.add(pick[1].lower())
                    continue
            key = name_en.lower()
            if not name_en or key not in used:
                used.add(key)
                continue
            # a genuine duplicate inside the branch: qualify it deterministically,
            # falling back to a numeral when the compass points are exhausted
            candidates = [(f"{name_en} · {en_suffix}", f"{name_ar} {ar_suffix}")
                          for en_suffix, ar_suffix in SUFFIXES]
            candidates += [(f"{name_en} · {n}", f"{name_ar} {n}") for n in range(2, 40)]
            for candidate, candidate_ar in candidates:
                if candidate.lower() in used:
                    continue
                plan.renames.append(Rename(p["id"], name_en, candidate,
                                           candidate_ar if name_ar else None,
                                           "duplicate name inside the same branch"))
                used.add(candidate.lower())
                renamed_names.add(candidate.lower())
                break

    # ---------------------------------------------------------------- 2 · names
    # A record whose title embeds the old placeholder is re-pointed at the place it
    # is actually linked to.  Without this the tree reads well but the institution
    # list still says "National Library of City of Indonesia".
    for table, fk, col_en, col_ar in NAME_LINKED:
        if not _has_table(conn, table):
            continue
        rows = conn.execute(
            f"""SELECT r.id, r.{col_en} AS name_en, r.{col_ar} AS name_ar,
                       p.name_en AS p_en, p.name_ar AS p_ar
                FROM {table} r JOIN place p ON p.id = r.{fk}
                WHERE r.deleted_at IS NULL
                  AND (r.{col_en} LIKE '%City of%' OR r.{col_ar} LIKE '%مدينة %')""").fetchall()
        for r in rows:
            # keep a single space between the new name and any following clause
            new_en = EMBEDDED_EN.sub(lambda m: (r["p_en"] or "").strip() + " ",
                                     r["name_en"] or "").strip()
            new_ar = EMBEDDED_AR.sub(lambda m: (r["p_ar"] or "").strip() + " ",
                                     r["name_ar"] or "").strip()
            new_en = re.sub(r"\s{2,}", " ", new_en).replace(" ,", ",").replace(" ;", ";")
            new_ar = re.sub(r"\s{2,}", " ", new_ar)
            if new_en and new_en != r["name_en"]:
                plan.renames.append(Rename(r["id"], r["name_en"], new_en, new_ar,
                                           "name re-pointed at the linked place",
                                           entity_type=table))
                if apply:
                    conn.execute(f"UPDATE {table} SET {col_en}=?, "
                                 f"{col_ar}=COALESCE(?, {col_ar}) WHERE id=?",
                                 (new_en, new_ar or None, r["id"]))

    if apply and plan.renames:
        tx = conn.execute("SELECT lower(hex(randomblob(8)))").fetchone()[0]
        for r in plan.renames:
            if r.entity_type == "place":
                conn.execute("UPDATE place SET name_en=?, name_ar=COALESCE(?, name_ar), "
                             "city=CASE WHEN city=? THEN ? ELSE city END WHERE id=?",
                             (r.new_en, r.new_ar, r.old_en, r.new_en, r.record_id))
            conn.execute(
                "INSERT INTO change_log (tx_id, entity_type, entity_id, action, field_key,"
                " field_label, old_value, new_value, reason, actor)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tx, r.entity_type, r.record_id, "update", "name_en", "Name (English)",
                 r.old_en, r.new_en, f"place-name tidy: {r.reason}", actor))
        conn.commit()
    return plan
