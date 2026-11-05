"""
SIRAJ · put places on the map, from the local gazetteer.

A registry accumulates places entered as text ("Mosul", "Karbala · North") with no
coordinates, or with coordinates that came from somewhere nobody can now name. This
module reconciles the registry's places against the **local** gazetteer shipped in the
basemap pack (Natural Earth populated places, 1 251 cities, public domain, Arabic and
Latin names) and proposes coordinates that can be defended:

  * a name that matches exactly one gazetteer city is used directly;
  * a name that matches several cities is resolved by the record's own country — and
    only when that leaves exactly one candidate;
  * anything still ambiguous is **reported and left alone**. Guessing a coordinate is
    worse than admitting one is missing, because a wrong dot on a map is a claim.

`plan()` is pure and returns every proposal with its reason; `apply()` writes them and
records both the old and the new value in `change_log`, exactly like an edit made in the
interface. Nothing is written unless `--apply` is given.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from app import db
from app.geo import basemap, spatial

# "Mosul · North" and friends: the qualifier is a disambiguation suffix, not a name
SUFFIX = re.compile(r"\s*·.*$")
# a move further than this is a correction, nearer than this is a re-centring
CORRECTION_METRES = 25_000


@dataclass
class Proposal:
    place_id: int
    code: str
    name: str
    old_lat: float | None
    old_lon: float | None
    new_lat: float
    new_lon: float
    reason: str          # fill | correct | reproject
    distance_m: float
    gazetteer: str

    def as_row(self) -> str:
        old = "—" if self.old_lat is None else f"{self.old_lat:.5f}, {self.old_lon:.5f}"
        return (f"{self.code}  {self.name[:34]:34}  {old:>22}  →  "
                f"{self.new_lat:.5f}, {self.new_lon:.5f}  ({self.reason}, "
                f"{spatial.format_distance(self.distance_m)})")


@dataclass
class Plan:
    proposals: list[Proposal] = field(default_factory=list)
    within: list[dict] = field(default_factory=list)        # already right: no action
    conflicts: list[dict] = field(default_factory=list)     # name vs. country disagree
    ambiguous: list[dict] = field(default_factory=list)     # several cities share the name
    unmatched: list[dict] = field(default_factory=list)     # not in the gazetteer
    scanned: int = 0

    def __len__(self) -> int:
        return len(self.proposals)


def _country_code(conn: sqlite3.Connection, country_id) -> str | None:
    if not country_id:
        return None
    row = conn.execute("SELECT code FROM lookup WHERE id=?", (country_id,)).fetchone()
    return row["code"] if row else None


def _lookup_id(conn: sqlite3.Connection, domain: str, code: str) -> int | None:
    row = conn.execute("SELECT id FROM lookup WHERE domain=? AND code=?",
                       (domain, code)).fetchone()
    return row["id"] if row else None


def _candidates(name: str) -> list[dict]:
    """Every gazetteer city whose Latin or Arabic name is exactly this name."""
    target = SUFFIX.sub("", name or "").strip().lower()
    if not target or not basemap.available():
        return []
    out = []
    for place in basemap._gazetteer():
        latin = (place.get("name_en") or "").strip().lower()
        arabic = (place.get("name_ar") or "").strip()
        if latin == target or (arabic and arabic == name.strip()):
            out.append(place)
    return out


def plan(conn: sqlite3.Connection) -> Plan:
    """Propose coordinates only where the record's *own* name and country agree.

    A name alone is not evidence: "Zurich" is a real city in Switzerland, so a record
    whose name is Zurich but whose country is Morocco is not a record with a bad
    coordinate — it is a record whose two fields contradict each other, and that is a
    finding for a human, not something to overwrite. So the rule is:

      * name matches a gazetteer city **and** the record's country is that city's
        country  → the coordinate is proposed (fill if absent, correct if it is more
        than 25 km away);
      * name matches but the country disagrees → reported as a conflict, untouched;
      * several cities in that country share the name → reported, untouched;
      * no match → reported as unmatched (the gazetteer covers 1 251 cities, not every
        village in the world).
    """
    rows = conn.execute(
        "SELECT id, code, name_en, name_ar, latitude, longitude, country_id "
        "FROM place WHERE deleted_at IS NULL ORDER BY id").fetchall()
    result = Plan(scanned=len(rows))
    for row in rows:
        name = row["name_en"] or row["name_ar"] or ""
        candidates = _candidates(name)
        if not candidates and row["name_ar"]:
            candidates = _candidates(row["name_ar"])
        if not candidates:
            result.unmatched.append({"code": row["code"], "name": name})
            continue
        cc = _country_code(conn, row["country_id"])
        if cc:
            in_country = [c for c in candidates if (c.get("iso_a2") or "").upper() == cc.upper()]
            if not in_country:
                result.conflicts.append({
                    "code": row["code"], "name": name, "country": cc,
                    "gazetteer": [f"{c['name_en']} ({c.get('iso_a2') or '??'})"
                                  for c in candidates[:4]],
                })
                continue
            candidates = in_country
        if len(candidates) > 1:
            result.ambiguous.append({
                "code": row["code"], "name": name,
                "candidates": [f"{c['name_en']} ({c.get('iso_a2')})" for c in candidates[:5]],
            })
            continue
        city = candidates[0]
        new_lat, new_lon = round(float(city["lat"]), 6), round(float(city["lon"]), 6)
        if row["latitude"] is None or row["longitude"] is None:
            reason, distance = "fill", 0.0
        else:
            distance = spatial.haversine(row["latitude"], row["longitude"], new_lat, new_lon)
            if distance <= CORRECTION_METRES:
                result.within.append({
                    "code": row["code"], "name": name, "city": city["name_en"],
                    "distance_m": round(distance, 1)})
                continue
            reason = "correct"
        result.proposals.append(Proposal(
            place_id=row["id"], code=row["code"], name=name,
            old_lat=row["latitude"], old_lon=row["longitude"],
            new_lat=new_lat, new_lon=new_lon, reason=reason,
            distance_m=round(distance, 1), gazetteer=city["name_en"]))
    return result


def apply_plan(conn: sqlite3.Connection, proposals: list[Proposal],
               actor: str = "maintenance") -> int:
    rough = _lookup_id(conn, "geo_precision", "approximate")
    # How the point was obtained is part of the point: a gazetteer match is not a
    # survey, and a city point is not a street address.
    method = _lookup_id(conn, "geocoding_method", "gazetteer")
    written = 0
    for p in proposals:
        if p.reason == "fill" and rough:
            conn.execute("UPDATE place SET latitude=?, longitude=?, geo_precision=?, "
                         "geocoding_method=COALESCE(geocoding_method, ?), "
                         "updated_at=?, updated_by=? WHERE id=?",
                         (p.new_lat, p.new_lon, rough, method, db.now(), actor, p.place_id))
        else:
            conn.execute("UPDATE place SET latitude=?, longitude=?, "
                         "geocoding_method=COALESCE(geocoding_method, ?), "
                         "updated_at=?, updated_by=? WHERE id=?",
                         (p.new_lat, p.new_lon, method, db.now(), actor, p.place_id))
        for key, old, new in (("latitude", p.old_lat, p.new_lat),
                              ("longitude", p.old_lon, p.new_lon)):
            db.log_change(conn, entity_type="place", entity_id=p.place_id,
                          entity_code=p.code, action="update", field_key=key,
                          field_label=key.capitalize(), old_value=old, new_value=new,
                          actor=actor, reason=f"geocoded from the local gazetteer ({p.reason})")
        written += 1
    conn.commit()
    return written
