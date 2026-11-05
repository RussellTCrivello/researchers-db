#!/usr/bin/env python3
"""CRCE — Compass-Rose Coordinate Encoding, proved against a live registry.

The standard is one encoding for every spatial reference in the registry. This
suite asks the running application, and the browser, whether that is true:

  · the standard is published, versioned and bilingual, with four reserved
    symbols and an explicit list of what it does *not* cover
  · each symbol belongs to exactly one category and is used for nothing else
  · a place reports its stored coordinates, its reference system, its derived
    notations, its precision, and how the point was obtained
  · a person is never a pin: the point is inherited, the role is a birthplace,
    and the record says so in words the reader can act on
  · a record with no fix says "no fix" — no coordinate is invented, no needle
    is drawn, and the mark is rendered upright and empty of direction
  · a relationship carries a bearing between two real points, or states why it
    cannot; coincident ends are not given an azimuth
  · the record page has a Position tab that renders the whole published field
    order, in Arabic and in English, with the reserved mark
  · the atlas draws the standard inside its nodes, and the panel surfaces the
    record's position in place
  · the geographic map reserves a layer for the covered categories

    python3 tests/crce_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

RESULTS: list[str] = []
ERRORS: list[str] = []
SHOTS: Path | None = None


def check(cond: bool, label: str, detail: str = "") -> bool:
    line = f"{'PASS' if cond else 'FAIL'} · {label}" + (f"   [{detail}]" if detail else "")
    print(line)
    RESULTS.append(line)
    if not cond:
        ERRORS.append(label + (f" — {detail}" if detail else ""))
    return bool(cond)


def section(name: str) -> None:
    print(f"\n=== {name} " + "=" * max(4, 66 - len(name)))


def shot(page, name: str) -> None:
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def dossiers() -> dict:
    """One representative record per category, chosen from the live registry."""
    import sqlite3
    db = Path(__file__).resolve().parents[1] / "app" / "data" / "registry.db"
    con = sqlite3.connect(db)

    def first(sql: str):
        row = con.execute(sql).fetchone()
        return row[0] if row else None

    return {
        "person": first("SELECT id FROM person WHERE deleted_at IS NULL "
                        "AND birthplace_id IS NOT NULL AND name_en IS NOT NULL "
                        "ORDER BY id LIMIT 1") or 1,
        "unlocated": first("SELECT id FROM person WHERE deleted_at IS NULL "
                           "AND birthplace_id IS NULL AND affiliated_country_id IS NULL "
                           "LIMIT 1"),
        "place": first("SELECT id FROM place WHERE deleted_at IS NULL "
                       "AND latitude IS NOT NULL ORDER BY id LIMIT 1"),
        "institution": first("SELECT id FROM institution WHERE deleted_at IS NULL "
                             "ORDER BY id LIMIT 1"),
        "relationship": first("SELECT id FROM relationship WHERE deleted_at IS NULL "
                              "ORDER BY id LIMIT 1"),
        "relationship_local": first(
            "SELECT r.id FROM relationship r "
            "JOIN institution a ON a.id = r.entity1_id AND r.entity1_type = 'institution' "
            "JOIN institution b ON b.id = r.entity2_id AND r.entity2_type = 'institution' "
            "WHERE r.deleted_at IS NULL ORDER BY r.id LIMIT 1"),
    }


def main(argv: list[str] | None = None) -> int:
    global SHOTS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default="", help="write screenshots here")
    ap.add_argument("--width", type=int, default=1500)
    ap.add_argument("--height", type=int, default=1000)
    args = ap.parse_args(argv)
    if args.shots:
        SHOTS = Path(args.shots).resolve()
    base = args.base.rstrip("/")
    ids = dossiers()
    http = httpx.Client(base_url=base, timeout=30)

    # ------------------------------------------------------------------ #
    section("the standard is published")
    # ------------------------------------------------------------------ #
    std = http.get("/api/crce/standard")
    check(std.status_code == 200, "GET /api/crce/standard answers", str(std.status_code))
    doc = std.json()
    standard = doc.get("standard") or {}
    check(standard.get("id") == "CRCE", "it names itself CRCE", str(standard.get("id")))
    check(bool(standard.get("version")), "the standard carries a version",
          str(standard.get("version")))
    check(bool(standard.get("name_en")) and bool(standard.get("name_ar")),
          "it is named in both languages",
          f"{standard.get('name_en')} / {standard.get('name_ar')}")
    check(standard.get("storage_crs") in ("EPSG:4326", "CRS84"),
          "it declares the reference system coordinates are stored in",
          str(standard.get("storage_crs")))
    syms = {s["id"]: s for s in (doc.get("symbols") or {}).values()}
    check(set(syms) == {"crce-person", "crce-organization", "crce-place",
                        "crce-relationship"},
          "four symbols are published, one per covered category", ", ".join(sorted(syms)))
    check(all(s.get("exclusive") for s in syms.values()),
          "each symbol is declared exclusive to its category")
    check(all(len(s.get("geometry") or []) >= 8 for s in syms.values()),
          "each symbol is drawn from real geometry, not a placeholder",
          ", ".join(f"{k}:{len(v['geometry'])}" for k, v in syms.items()))
    check(all(s.get("label_en") and s.get("label_ar") and s.get("means_en")
              and s.get("means_ar") for s in syms.values()),
          "each symbol says what it means, in both languages")
    cats = [s["category"] for s in syms.values()]
    check(len(cats) == len(set(cats)), "no two symbols share a category", ", ".join(cats))
    check(set(standard.get("reserved") or []) == set(cats),
          "the reserved list matches the published symbols")
    uncovered = standard.get("uncovered") or []
    check("event" in uncovered and "source" in uncovered,
          "the standard states what it does not cover", ", ".join(uncovered))
    rules = {r["code"]: r for r in doc.get("rules") or []}
    for code, label in (
            ("no_invention", "coordinates are never invented or interpolated"),
            ("preserve_original", "the original values and reference system are preserved"),
            ("person_not_pin", "a person is not reduced to a point on the ground"),
            ("direction_needs_two", "a direction needs two real points"),
            ("exclusive_symbols", "each category keeps its own symbol")):
        check(code in rules and rules[code].get("en") and rules[code].get("ar"),
              f"the standard states its rule: {label}", code)
    roles = doc.get("roles") or {}
    check({"site", "birthplace", "seat"} <= set(roles),
          "the roles a coordinate may play are a closed, published list",
          ", ".join(sorted(roles)))
    ops = {p["op"] for s in syms.values() for p in s["geometry"]}
    check({"ring", "line", "dot"} <= ops,
          "the marks are built from cartographic primitives — rings, lines, dots",
          ", ".join(sorted(ops)))

    # ------------------------------------------------------------------ #
    section("a place: coordinates, system, precision, provenance")
    # ------------------------------------------------------------------ #
    pid = ids["place"]
    place = http.get(f"/api/crce/dossier/place/{pid}").json()
    rec = http.get(f"/api/place/{pid}").json()
    co = place["coordinates"]
    f = co["formats"]
    check(co["primary"]["crs"] == "EPSG:4326", "the point states its reference system",
          co["primary"]["crs"])
    check(abs(co["primary"]["lat"] - rec["latitude"]) < 1e-6
          and abs(co["primary"]["lon"] - rec["longitude"]) < 1e-6,
          "the standard reports the stored value unchanged — nothing is re-projected",
          f'{co["primary"]["lat"]}, {co["primary"]["lon"]}')
    check(bool(f.get("dms")) and "°" in f["dms"], "degrees/minutes/seconds are derived",
          f.get("dms"))
    check(bool(f.get("crs84")) and abs(f["crs84"]["lon"] - rec["longitude"]) < 1e-6,
          "the CRS84 (lon, lat) form is derived from the same value")
    check(bool(f.get("web_mercator")) and f["web_mercator"]["unit"] == "metre",
          "the projected form is derived and its unit named",
          str((f.get("web_mercator") or {}).get("crs")))
    check(f.get("geohash_note_en") and f.get("geohash_note_ar"),
          "the derived notations are labelled as derived, in both languages")
    check(co["precision"]["code"] in ("exact", "approx", "approximate", "centroid",
                                      "unknown", "uncertain"),
          "the precision on file is reported, not assumed",
          str(co["precision"].get("code")))
    check(co["role"]["code"] == "site", "a place's own coordinate is its own site",
          co["role"]["code"])
    check("source" in co and "method" in co,
          "how the point was obtained and supplied by whom are both reported")
    check(place["entity"]["symbol"] == "crce-place",
          "a place uses the place symbol and no other", place["entity"]["symbol"])
    check(place["rose"]["state"] == "located" and place["rose"]["needle"] is True,
          "a located point gets a needle")
    check(place["rose"]["ticks"] == 16 and place["rose"]["letters"] == ["N", "E", "S", "W"],
          "a place bears the graduated rose with its cardinal letters",
          f'{place["rose"]["ticks"]} ticks')
    inside = (place.get("relative") or {}).get("inside")
    check(bool(inside) and inside.get("name_en"),
          "the containing country is derived from the offline basemap",
          (inside or {}).get("name_en")) if inside else check(
        True, "no containing country claimed when the basemap has none")

    # ------------------------------------------------------------------ #
    section("a person is not a pin")
    # ------------------------------------------------------------------ #
    per = http.get(f"/api/crce/dossier/person/{ids['person']}").json()
    co = per["coordinates"]
    check(per["entity"]["symbol"] == "crce-person",
          "a person uses the person symbol, never the place's", per["entity"]["symbol"])
    check(co["inherited"] is True,
          "the point is reported as inherited, not measured for the person")
    check(co["role"]["code"] in ("birthplace", "seat", "site", "event_place"),
          "the role the coordinate plays is named", co["role"]["code"])
    codes = [n["code"] for n in per["notes"]]
    check("person_not_pin" in codes,
          "the record says in words that a person's location is not their identity",
          ", ".join(codes))
    check("inherited" in codes, "and that the point belongs to the place on file")
    check(per["rose"]["ticks"] == 0,
          "a person's mark is not a compass for the world: it has no graduations",
          str(per["rose"]["ticks"]))
    lo, hi = per["coordinates"]["primary"]["lat"], per["coordinates"]["primary"]["lon"]
    check(-90 <= lo <= 90 and -180 <= hi <= 180,
          "the reported point is a legal geographic pair", f"{lo}, {hi}")
    o = per.get("orientation") or {}
    check(bool(o) and 0 <= o["bearing_deg"] < 360,
          "the bearing is an azimuth in [0, 360)", str(o.get("bearing_deg")))
    check(bool(o) and bool(o.get("en")) and bool(o.get("ar")),
          "the sixteen-point name is given in both languages",
          f'{o.get("en")} / {o.get("ar")}')
    check(bool(o) and (o.get("reference") or {}).get("label_en"),
          "the reference the bearing is measured from is named")
    check(not (o.get("reference") or {}).get("conceptual", False)
          or "conceptual_reference" in codes,
          "a conceptual reference is flagged as conceptual, in the data and in words")

    # ------------------------------------------------------------------ #
    section("no fix means no fix")
    # ------------------------------------------------------------------ #
    if ids["unlocated"]:
        un = http.get(f"/api/crce/dossier/person/{ids['unlocated']}").json()
        check(un["status"] == "unlocated", "a record with no georeferenced place says so",
              un["status"])
        check(un["coordinates"] is None,
              "and carries no coordinates at all — none are inferred",
              str(un["coordinates"])[:40])
        check(un["orientation"] is None, "no bearing is invented for it")
        check(un["rose"]["state"] == "unlocated" and un["rose"]["needle"] is False,
              "the mark is drawn upright and without a needle")
        check("no_fix" in [n["code"] for n in un["notes"]],
              "and the reader is told why", ", ".join(n["code"] for n in un["notes"]))
    else:
        check(False, "the registry offered a person with no fix to test")

    # ------------------------------------------------------------------ #
    section("relationships carry direction, or say they cannot")
    # ------------------------------------------------------------------ #
    rel = http.get(f"/api/crce/dossier/relationship/{ids['relationship']}").json()
    check(len(rel.get("ends") or []) == 2, "a relationship has exactly two ends")
    symbols = {e["symbol"] for e in rel["ends"]}
    check(symbols <= set(syms), "each end is drawn with its own category's symbol",
          ", ".join(sorted(s for s in symbols if s)))
    check(rel["entity"]["symbol"] == "crce-relationship",
          "the connection itself uses the relationship symbol")
    check(rel["status"] in ("located", "same_point", "unlocated"),
          "the connection states whether it has a direction", rel["status"])
    check("connect_not_claim" in [n["code"] for n in rel["notes"]],
          "and repeats the safety rule: a connection is not a finding")
    if ids["relationship_local"]:
        local = http.get(
            f"/api/crce/dossier/relationship/{ids['relationship_local']}").json()
        if local.get("ends_coincident"):
            check(local["orientation"] is None,
                  "two ends at the same recorded point get no azimuth",
                  str(local["orientation"]))
            check(local["status"] == "same_point",
                  "and the status names the coincidence", local["status"])
            check("coincident_ends" in [n["code"] for n in local["notes"]],
                  "with a note that explains why no needle is drawn")
        else:
            check(bool(local.get("orientation")),
                  "an ordinary pair of ends gets a bearing")

    # ------------------------------------------------------------------ #
    section("aliases, coverage and honest errors")
    # ------------------------------------------------------------------ #
    org = http.get(f"/api/crce/dossier/organization/{ids['institution']}")
    check(org.status_code == 200, "the standard's own vocabulary resolves to the registry",
          str(org.status_code))
    orgd = org.json()
    check(orgd["entity"]["symbol"] == "crce-organization",
          "an institution uses the organization symbol", orgd["entity"]["symbol"])
    check(orgd["entity"]["category"] == "organization",
          "and is reported as an organization, not a person or a place")
    check(http.get(f"/api/crce/dossier/people/{ids['person']}").status_code == 200,
          "the singular of a category is accepted as an alias")
    for bad, label in (("/api/crce/dossier/person/99999999", "a missing record"),
                       ("/api/crce/dossier/wizard/1", "a category the standard does not cover")):
        r = http.get(bad)
        check(r.status_code == 404, f"{label} is a 404, never a made-up dossier",
              str(r.status_code))
    ev = http.get("/api/crce/dossier/event/1")
    check(ev.status_code == 200,
          "an uncovered kind still gets its coordinates read the same way",
          str(ev.status_code))
    evd = ev.json()
    check(evd["entity"]["symbol"] is None and evd["entity"]["covered_by_standard"] is False,
          "but it borrows no mark: the reserved symbols stay reserved",
          str(evd["entity"]["symbol"]))
    check(evd["rose"]["symbol"] is None,
          "and the rose is left empty rather than filled with another category's mark")
    check("not_covered" in [n["code"] for n in evd["notes"]],
          "the reader is told why there is no mark")

    # ------------------------------------------------------------------ #
    console: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(str(e)))

        section("the record page: a Position tab that publishes the standard")
        page.goto(f"{base}/#/entity/person/{ids['person']}")
        page.wait_for_selector(".tabs", timeout=25000)
        page.evaluate("() => App.setLang('en')")
        page.wait_for_timeout(900)
        tab = page.locator("[data-tab='position']")
        check(tab.count() == 1, "every record carries a Position tab")
        tab.click()
        page.wait_for_selector(".crce-panel", timeout=15000)
        page.wait_for_timeout(600)
        check(page.locator(".crce-panel").count() == 1, "the tab renders the dossier")
        check(page.locator(".crce-head svg").count() >= 1,
              "with the category's reserved mark")
        heads = [h.inner_text().strip().lower() for h in page.locator(".crce-h").all()]
        order = ["entity definition", "coordinate encoding", "orientation",
                 "relative position", "compass rose representation",
                 "relationship mapping"]
        got = [h for h in heads if h in order]
        check(got == order,
              "in the published order: definition → encoding → rose → relations",
              " → ".join(got))
        check(page.locator(".crce-facts dt").count() >= 6,
              "the coordinate block lists real rows, not a paragraph",
              str(page.locator(".crce-facts dt").count()))
        check(page.locator(".crce-notes li").count() >= 2,
              "the accuracy notes are shown with the point",
              str(page.locator(".crce-notes li").count()))
        check(page.locator(".crce-rel").count() >= 1,
              "relationships are mapped beside the position")
        body = page.locator(".crce-panel").inner_text()
        check("EPSG:4326" in body, "the reference system is written on the page")
        check("°" in body, "degrees appear in the notations")
        check(page.locator(".crce-facts .mono-cell").count() >= 2,
              "the numbers on the page are values, not prose",
              str(page.locator(".crce-facts .mono-cell").count()))
        check(bool(page.evaluate(
            "() => !!document.querySelector('.crce-panel')?.innerText.match(/[0-9,]+ km/)"))
            or "km" not in body,
            "distances are written as kilometres with grouping, not raw metres")
        shot(page, "crce-record-en")

        page.goto(f"{base}/#/entity/place/{ids['place']}")
        page.wait_for_selector(".tabs", timeout=25000)
        page.locator("[data-tab='position']").click()
        page.wait_for_selector(".crce-panel", timeout=15000)
        page.wait_for_timeout(500)
        pbody = page.locator(".crce-panel").inner_text()
        check("N" in pbody and "E" in pbody,
              "a place's dossier carries the cardinal notation of its point")
        check(page.locator(".crce-mark svg").count() >= 1, "and its mark")
        shot(page, "crce-record-place")

        page.evaluate("() => App.setLang('ar')")
        page.wait_for_timeout(1200)
        page.locator("[data-tab='position']").click()
        page.wait_for_selector(".crce-panel", timeout=15000)
        page.wait_for_timeout(600)
        check(page.evaluate("() => document.documentElement.dir") == "rtl",
              "the dossier survives the switch to Arabic")
        check("تعريف الكيان" in page.locator(".crce-panel").inner_text(),
              "and its headings are translated, not left in English",
              page.locator(".crce-h").first.inner_text())
        check(page.locator(".crce-panel svg").count() >= 1,
              "the mark is drawn the same way in both languages")
        shot(page, "crce-record-ar")
        page.evaluate("() => App.setLang('en')")
        page.wait_for_timeout(600)

        section("the atlas draws the standard inside its nodes")
        page.goto(f"{base}/#/map")
        page.wait_for_selector("svg.relmap .map-node", timeout=25000)
        page.wait_for_timeout(1400)
        rosettes = page.locator("svg.relmap .atlas-rosette").count()
        check(rosettes >= 3, "the covered categories are drawn as compass roses",
              str(rosettes))
        labels = page.eval_on_selector_all(
            "svg.relmap .atlas-label", "els => els.map(e => e.textContent || '')")
        check(any("·" in t for t in labels),
              "the count rides in the label, not inside the reserved mark",
              "; ".join(labels[:3]))
        check(page.locator("svg.relmap .atlas-count").count() >= 1,
              "uncovered categories keep their plain count")
        before = page.url
        page.locator("svg.relmap .map-node[data-type='person'] .node-hit").first.click(
            force=True)
        page.wait_for_timeout(2600)
        check(page.url == before, "a bubble drills into its type without navigating",
              page.url)
        check(page.locator("svg.relmap .map-node").count() > 1,
              "and the diagram comes back as a neighbourhood")
        page.locator("svg.relmap .map-node[data-type='person'] .node-hit").first.click(
            force=True)
        page.wait_for_selector(".atlas-panel .ap-title", timeout=12000)
        page.wait_for_timeout(1200)
        check(page.locator(".atlas-panel .crce-tile").count() == 1,
              "the panel surfaces the record's position in place")
        check(page.locator(".atlas-panel .crce-tile svg").count() >= 1,
              "with the reserved mark beside it")
        tile = page.locator(".atlas-panel .crce-tile").inner_text()
        check(bool(tile.strip()), "and a line a reader can act on", tile.replace("\n", " · "))
        shot(page, "crce-atlas")

        section("the geographic map reserves a layer for the standard")
        page.goto(f"{base}/#/geo")
        page.wait_for_timeout(5000)
        check(page.locator("canvas.maplibregl-canvas").count() >= 1, "the map is up")
        marks = page.locator(".geo-crce-legend svg").count()
        check(marks >= 3, "the legend shows the reserved mark per covered category",
              str(marks))
        shot(page, "crce-geo")

        page.goto("about:blank")
        browser.close()

    check(not [c for c in console if "error" in c.lower()],
          "no console or page errors during the session", "; ".join(console[:3]))

    passed = sum(1 for r in RESULTS if r.startswith("PASS"))
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    if ERRORS:
        print("\nFAILURES:")
        for e in ERRORS:
            print("  ·", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
