#!/usr/bin/env python3
"""The split data view — one record's panel beside the list it came from.

Proves, in a browser and against a live server:

  · the data view owns the whole stage until a record is selected
  · selecting a record splits the page in two — data · panel — and closing
    gives the whole page back
  · the panel carries exactly three tabs: Details, Relationships, Map
  · Details is the whole dossier: field groups, positions, events, sources,
    files and the change log, each keeping its add / upload actions
  · Relationships visualises the record's connections as an interactive
    ego-network — hover spotlights a branch, clicking a node opens that
    record — and lists every link with navigation options
  · Map shows the record's geographic coordinates (DD and DMS) on an
    offline base map with a marker, copy / recentre controls and links
    into the full geographic workspace and the relationship atlas
  · records without coordinates say so, with the hint that fixes it
  · prev / next / arrow keys walk the list selection without leaving the page
  · institutions and places get the same panel; bulk selection never opens it
  · the Arabic interface is translated and right-to-left

    python3 tests/inspect_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import sync_playwright

RESULTS: list[str] = []
ERRORS: list[str] = []
SHOTS: Path | None = None
BASE = "http://127.0.0.1:8000"


def check(cond: bool, label: str, detail: str = "") -> bool:
    line = f"{'PASS' if cond else 'FAIL'} · {label}" + (f"   [{detail}]" if detail else "")
    print(line, flush=True)
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


def api(path: str) -> dict:
    r = httpx.get(BASE + path, timeout=30)
    r.raise_for_status()
    return r.json()


def post(path: str, payload: dict) -> dict:
    r = httpx.post(BASE + path, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def tab_labels(page) -> list[str]:
    out = []
    for text in page.locator("[data-inspect-tabs] button").all_inner_texts():
        out.append(re.sub(r"\d+$", "", text.strip()).strip())
    return out


def wait_panel(page) -> None:
    """The panel body carries the ready mark on every tab, hidden or not."""
    page.wait_for_selector("[data-inspect-ready]", state="attached", timeout=15000)


def pick_person() -> dict:
    """The person with the richest relationship neighbourhood we can find."""
    rows = post("/api/person/query", {"page_size": 60, "sort": "id", "order": "asc"})["items"]
    best, best_score = None, -1
    for row in rows:
        rec = api(f"/api/person/{row['id']}")
        score = 10 * len(rec.get("relationships") or []) + (5 if rec.get("birthplace_id") else 0)
        if score > best_score:
            best, best_score = rec, score
    return best or api(f"/api/person/{rows[0]['id']}")


def pick_place_with_coords() -> dict:
    rows = post("/api/place/query", {"page_size": 60, "sort": "id", "order": "asc"})["items"]
    for row in rows:
        if row.get("latitude") is not None and row.get("longitude") is not None:
            return api(f"/api/place/{row['id']}")
    return api(f"/api/place/{rows[0]['id']}")


def make_scratch_place() -> dict | None:
    """A place with no coordinates — the unlocated state needs one to exist."""
    stamp = uuid4().hex[:6].upper()
    res = httpx.post(BASE + "/api/place", timeout=30,
                     headers={"X-Actor": "inspect_ui"},
                     json={"code": f"SCRATCH-UNLOC-{stamp}",
                           "name_ar": "مكان مؤقت للاختبار",
                           "name_en": f"SCRATCH unlocated {stamp}"})
    if res.status_code >= 400:
        return None
    return res.json().get("record")


def drop_scratch_place(rid: int) -> None:
    try:
        httpx.delete(f"{BASE}/api/place/{rid}", timeout=30,
                     headers={"X-Actor": "inspect_ui"},
                     params={"reason": "scratch cleanup", "hard": "true"})
    except httpx.HTTPError:
        pass


def main() -> int:
    global BASE, SHOTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", type=Path, default=None)
    args = ap.parse_args()
    BASE = args.base
    SHOTS = args.shots

    person = pick_person()
    pid = person["id"]
    place = pick_place_with_coords()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: ERRORS.append(f"console[{m.type}]: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: ERRORS.append(f"pageerror: {e}"))
        page.on("response", lambda r: ERRORS.append(f"resource[{r.status}] {r.url}")
                if r.status >= 400 else None)
        # the main flow runs in English; the last section switches to Arabic
        page.add_init_script("try { localStorage.setItem('siraj.lang', 'en'); } catch (e) {}")

        # ------------------------------------------------------------- default ---
        section("the data view owns the page until a record is picked")
        page.goto(BASE + "/#/entity/person", wait_until="networkidle")
        page.wait_for_selector("table.data tbody tr", timeout=20000)
        check(page.locator("[data-inspect]").count() == 0,
              "no panel is open by default")
        check(page.locator(".list-stage.split").count() == 0,
              "the stage is not split by default")
        full = page.evaluate("""() => {
          const st = document.querySelector('.list-stage').getBoundingClientRect();
          const sc = document.querySelector('.list-scroll').getBoundingClientRect();
          return [st.width, sc.width]; }""")
        check(abs(full[0] - full[1]) < 6, "the data view fills the whole stage",
              f"stage {full[0]:.0f} vs data {full[1]:.0f}")

        # -------------------------------------------------------------- split ---
        section("selecting a record splits the page in two")
        page.fill("[data-list-q]", person.get("code") or "")
        page.wait_for_timeout(1000)
        page.locator("table.data tbody tr").first.click()
        wait_panel(page)
        page.wait_for_timeout(900)
        check(page.locator(".list-stage.split").count() == 1,
              "the stage splits when a record is selected")
        halves = page.evaluate("""() => {
          const sc = document.querySelector('.list-scroll').getBoundingClientRect();
          const pn = document.querySelector('[data-inspect]').getBoundingClientRect();
          return [sc.width, pn.width]; }""")
        ratio = halves[1] / (halves[0] + halves[1])
        check(0.38 <= ratio <= 0.62, "the two halves are balanced",
              f"panel share {ratio:.0%}")
        check(page.locator(".list-scroll tr.inspected").count() == 1,
              "the selected row is marked in the table")
        check(page.locator(".inspect-id h3").count() == 1,
              "the panel names the record")
        check(tab_labels(page) == ["Details", "Relationships", "Map"],
              "the panel has exactly the three tabs", " · ".join(tab_labels(page)))
        check(page.locator('[data-inspect-tab="details"].active').count() == 1,
              "Details is the default tab")
        shot(page, "inspect-split")

        # ------------------------------------------------------------- details ---
        section("the Details tab is the whole dossier")
        titles = [s.strip().upper()
                  for s in page.locator("[data-inspect-body] .inspect-section-title").all_inner_texts()]
        for want in ("Positions", "Events", "Sources", "Files", "Log"):
            check(want.upper() in titles, f"the dossier holds a '{want}' section")
        check(page.locator("[data-inspect-body] .inspect-stats div").count() >= 1,
              "derived figures are shown")
        check(page.locator("[data-inspect-body] [data-add-pos]").count() == 1,
              "positions keep their add action")
        check(page.locator("[data-inspect-body] [data-add-event]").count() == 1,
              "events keep their add action")
        check(page.locator("[data-inspect-body] [data-att-file]").count() == 1,
              "files keep their upload action")
        href = page.locator("[data-inspect-full]").get_attribute("href")
        check(href == f"#/entity/person/{pid}", "the full page is one click away", href)

        # -------------------------------------------------------- relationships ---
        section("the Relationships tab visualises the connections")
        page.locator('[data-inspect-tab="relationships"]').click()
        page.wait_for_timeout(700)
        nodes = page.locator(".rel-graph .rel-node").count()
        edges = page.locator(".rel-graph .rel-edge").count()
        rels = person.get("relationships") or []
        want_edges = len(rels)
        neighbours = len({(r["other_type"], r["other_id"]) for r in rels})
        check(nodes >= 2 or want_edges == 0, "the ego-network draws the record and its neighbours",
              f"{nodes} nodes")
        check(edges == neighbours, "every connection is drawn",
              f"{edges} drawn / {neighbours} neighbouring records")
        check(page.locator(".rel-graph .rel-node.centre").count() == 1,
              "the selected record sits at the centre")
        check(page.locator(".rel-legend span").count() >= 2,
              "the legend names the record types")
        if nodes > 1:
            page.locator(".rel-graph .rel-node").nth(1).hover()
            page.wait_for_timeout(300)
            check(page.locator(".rel-graph .rel-edge.hot").count() >= 1,
                  "hovering a node spotlights its connections")
        rows = page.locator("[data-inspect-body] table.data tbody tr").count()
        check(rows == want_edges, "the table lists every stored relationship",
              f"{rows} rows")
        atlas = page.locator("[data-inspect-body] a[href^='#/map?focus=']").first
        check(atlas.count() == 1 and atlas.get_attribute("href") == f"#/map?focus=person:{pid}",
              "the atlas link carries the record")
        zoom_before = page.get_attribute(".rel-graph svg", "viewBox")
        page.locator('[data-rel-zoom="in"]').click()
        page.wait_for_timeout(200)
        zoom_after = page.get_attribute(".rel-graph svg", "viewBox")
        check(zoom_before != zoom_after, "the zoom tools reshape the view")
        page.locator('[data-rel-zoom="reset"]').click()
        if nodes > 1:
            page.locator(".rel-graph .rel-node").nth(1).click()
            page.wait_for_timeout(1200)
            hash_now = page.evaluate("() => location.hash")
            check(bool(re.match(r"#/entity/\w+/\d+$", hash_now)) and not hash_now.endswith(f"/person/{pid}"),
                  "clicking a node opens that record", hash_now)
            page.goto(BASE + "/#/entity/person")
            wait_panel(page)
            page.wait_for_timeout(600)
        shot(page, "inspect-relationships")

        # ----------------------------------------------------------------- map ---
        section("the Map tab shows the coordinates")
        page.locator('[data-inspect-tab="map"]').click()
        page.wait_for_timeout(2200)
        wrap = page.locator("[data-inspect-map-wrap]")
        check(not wrap.get_attribute("hidden"), "the map pane opens with the tab")
        check(page.locator("[data-inspect-body]").get_attribute("hidden") is not None,
              "the text body stands down for the map")
        cap = page.locator("[data-inspect-caption]").inner_text()
        dd = page.evaluate("""() => {
          const m = document.querySelector('[data-inspect-caption] b');
          return m ? m.textContent.trim() : ''; }""")
        check("," in dd and all(ch.isdigit() or ch in ".,- " for ch in dd),
              "decimal degrees are displayed", dd)
        check("°" in cap, "the coordinates are also given in DMS", cap[:60].replace("\n", " "))
        check(page.locator(".inspect-map .geo-pin").count() == 1,
              "a marker pins the anchor place")
        geo_link = page.locator("[data-inspect-map-bar] a[href^='#/geo?sel=']").first
        check(geo_link.count() == 1 and geo_link.get_attribute("href") == f"#/geo?sel=person:{pid}",
              "the geographic workspace link carries the record")
        page.locator("[data-map-copy]").click()
        page.wait_for_timeout(500)
        check(page.locator("#toasts .toast").count() >= 1,
              "copying the coordinates confirms itself")
        check(page.locator("[data-map-recentre]").count() == 1,
              "the map can be recentred")
        shot(page, "inspect-map")

        # -------------------------------------------------- records without geo ---
        section("a record without coordinates says so")
        scratch = make_scratch_place()
        if scratch:
            try:
                page.goto(BASE + "/#/entity/place")
                page.wait_for_selector("table.data tbody tr", timeout=15000)
                page.fill("[data-list-q]", scratch.get("code") or "")
                page.wait_for_timeout(1000)
                page.locator("table.data tbody tr").first.click()
                wait_panel(page)
                page.locator('[data-inspect-tab="map"]').click()
                page.wait_for_timeout(600)
                check(page.locator(".inspect-map-empty").count() == 1,
                      "the unlocated state is explicit")
                body = page.locator(".inspect-map-empty").inner_text()
                check("coordinates" in body.lower() or "place" in body.lower(),
                      "the hint explains how to fix it", body[:70].replace("\n", " "))
            finally:
                # close the panel before the record disappears under it
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                drop_scratch_place(scratch["id"])
        else:
            check(False, "a scratch unlocated place can be created")

        # ----------------------------------------------------------- navigation ---
        section("panel navigation never loses the list")
        page.goto(BASE + "/#/entity/person")
        page.wait_for_selector("table.data tbody tr", timeout=15000)
        page.fill("[data-list-q]", "")
        page.wait_for_timeout(1000)
        page.locator("table.data tbody tr").first.click()
        wait_panel(page)
        page.wait_for_timeout(700)
        page.locator("[data-inspect-next]").click()
        page.wait_for_timeout(1100)
        idx = page.locator("[data-inspect-index]").inner_text()
        check("2" in idx, "next walks the selection", idx)
        page.locator("[data-inspect-prev]").click()
        page.wait_for_timeout(1100)
        check("1" in page.locator("[data-inspect-index]").inner_text(), "prev walks back")
        page.eval_on_selector(".list-scroll", "el => el.focus()")
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(1100)
        check("2" in page.locator("[data-inspect-index]").inner_text(),
              "the arrow keys do what the buttons do")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        check(page.locator("[data-inspect]").count() == 0,
              "Escape closes the panel")
        check(page.locator(".list-stage.split").count() == 0,
              "closing gives the whole page back to the data")

        # --------------------------------------------- other entities · bulk ---
        section("institutions and places split the same way")
        for entity in ("institution", "place"):
            page.goto(BASE + f"/#/entity/{entity}")
            page.wait_for_selector("[data-table-host] .toolbar", timeout=20000)
            page.fill("[data-list-q]", "")
            page.wait_for_timeout(1000)
            page.wait_for_selector("table.data tbody tr", timeout=20000)
            page.locator("table.data tbody tr").first.click()
            wait_panel(page)
            page.wait_for_timeout(700)
            check(page.locator(".list-stage.split").count() == 1,
                  f"{entity} selection splits the page")
            check(len(tab_labels(page)) == 3, f"{entity} gets the three tabs")
        page.goto(BASE + "/#/entity/place")
        page.wait_for_selector("table.data tbody tr", timeout=15000)
        page.fill("[data-list-q]", place.get("code") or "")
        page.wait_for_timeout(1000)
        page.locator("table.data tbody tr").first.click()
        wait_panel(page)
        page.locator('[data-inspect-tab="map"]').click()
        page.wait_for_timeout(1800)
        cap = page.locator("[data-inspect-caption]").inner_text().replace("\n", " ")
        want_dd = f"{float(place['latitude']):.5f}, {float(place['longitude']):.5f}"
        check(want_dd in cap, "a place maps at its own coordinates",
              f"{want_dd} in {cap[:48]}")
        shot(page, "inspect-place-map")

        page.goto(BASE + "/#/entity/person")
        page.wait_for_selector("table.data tbody tr", timeout=15000)
        page.locator("[data-pick]").first.check()
        page.wait_for_timeout(700)
        check(page.locator("[data-inspect]").count() == 0,
              "bulk selection never opens the panel")

        # ---------------------------------------------------------------- RTL ---
        section("the Arabic interface keeps the layout")
        page.locator("#langToggle").click()
        page.wait_for_timeout(1500)
        page.locator("table.data tbody tr").first.click()
        wait_panel(page)
        page.wait_for_timeout(900)
        check(page.evaluate("() => document.documentElement.dir") == "rtl",
              "the interface is right-to-left")
        labels = tab_labels(page)
        check(labels == ["التفاصيل", "العلاقات", "الخريطة"],
              "the tabs are translated", " · ".join(labels))
        sides = page.evaluate("""() => {
          const sc = document.querySelector('.list-scroll').getBoundingClientRect();
          const pn = document.querySelector('[data-inspect]').getBoundingClientRect();
          return [sc.x, pn.x]; }""")
        check(sides[1] < sides[0], "in RTL the panel mirrors to the other half",
              f"panel x {sides[1]:.0f} vs data x {sides[0]:.0f}")
        shot(page, "inspect-arabic")

        browser.close()

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
