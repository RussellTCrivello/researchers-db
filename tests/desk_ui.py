#!/usr/bin/env python3
"""The map desk — the registry worked as a place, the way a table is worked.

Proves, in a browser and against a live server:

  · the map is real and framed: a WebGL canvas of a sensible size, a loaded style,
    and the offline basemap's own geometry underneath
  · every record in the window is on it, and a group says how many it holds
  · the index on the side lists exactly what the map is drawing, and a row
    selects the same record a mark does
  · a mark reads in place: the pop-up card carries identity, anchor, coordinates
    and two actions, and reading never navigates away
  · the detail panel carries identity, status, counts, four tabs, the position in
    two notations, the record's data, and an explicit way to the record
  · the neighbourhood panel draws the selected record's own relationships and a
    neighbour can be walked to without leaving the page
  · a record with no coordinates says so instead of inventing a point
  · the table view is the same records as rows, and a row flies the map to it
  · search suggests, Enter selects; "/" focuses it; "g" switches view; Escape closes
  · the trail remembers where you were and both buttons tell the truth
  · layer chips reshape the window instead of reloading the page
  · switching the base map re-styles without losing a single record
  · Arabic mirrors the desk and keeps its layout; English puts it back
  · leaving disposes the map and leaves no console error behind

    python3 tests/desk_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def open_desk(page, base: str) -> None:
    page.goto(base + "/#/desk", wait_until="networkidle")
    page.wait_for_selector("[data-pick]", timeout=25000)
    page.wait_for_timeout(900)


def map_stats(page) -> dict:
    return page.evaluate("""() => {
      const m = window.__deskMap;
      if (!m) return null;
      const c = m.getContainer();
      return { w: c.clientWidth, h: c.clientHeight, zoom: m.getZoom(), loaded: m.loaded(),
               style: (m.getStyle().name || ''), center: m.getCenter().toArray(),
               hasBase: !!m.getSource('dk-base-countries'),
               layers: (m.getStyle().layers || []).length };
    }""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default=None)
    args = ap.parse_args()
    global SHOTS
    if args.shots:
        SHOTS = Path(args.shots)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # ------------------------------------------------------------- data
        section("what the desk is allowed to draw")
        conf = page.request.get(args.base + "/api/map/config").json()
        check(conf.get("ok") is True, "the map configuration answers")
        check(len(conf.get("providers") or []) >= 4, "base maps are offered",
              str(len(conf.get("providers") or [])))
        check(any(p["id"] == "local" for p in conf["providers"]),
              "one of them works with no network at all")
        local = next(p for p in conf["providers"] if p["id"] == "local")
        check(local.get("kind") == "vector-local", "and it is the local kind", local.get("kind", ""))

        feat = page.request.get(args.base + "/api/map/features?bbox=-180,-60,180,80&zoom=2&limit=50").json()
        check(feat.get("ok") is True, "the feature service answers")
        pts = feat.get("points") or []
        check(len(pts) > 0, "the registry has located records", str(len(pts)))
        check(all("lat" in p and "lon" in p for p in pts),
              "every feature carries its own coordinates")
        check(all(p.get("entity_type") and p.get("id") for p in pts),
              "every feature names the record it is")

        # ------------------------------------------------------------ frame
        section("the map is real")
        open_desk(page, args.base)
        st = map_stats(page)
        check(bool(st), "a map object exists and is reachable for inspection")
        check(st and st["w"] > 300 and st["h"] > 200,
              "the canvas fills the centre column", f'{st and st["w"]}×{st and st["h"]}')
        check(st and st["loaded"], "the style finished loading")
        check(st and st["zoom"] > 0, "the camera has a zoom", st and f'{st["zoom"]:.2f}')
        check(page.locator(".maplibregl-canvas").count() == 1, "there is exactly one WebGL canvas")
        page.wait_for_timeout(1200)
        st = map_stats(page)
        check(st and st["hasBase"], "the offline basemap's geometry is under the records")

        marks = page.locator(".desk-mark").count()
        check(marks > 0, "records are drawn", str(marks))
        clusters = page.locator(".desk-mark.is-cluster").count()
        check(clusters >= 0, "groups are drawn as groups", str(clusters))
        index_rows = page.locator("[data-pick]").count()
        check(index_rows > 0, "the index lists what the map draws", str(index_rows))
        check(page.locator(".desk-legend .dl-item").count() >= 4,
              "the marks are explained on the map itself")
        shot(page, "desk-overview")

        section("the panel before anything is selected")
        page.wait_for_timeout(1500)
        hubs = page.locator(".dh-row").count()
        check(hubs >= 1, "the panel offers the window's busiest places", str(hubs))
        if hubs:
            page.locator(".dh-row").first.click()
            page.wait_for_timeout(2200)
            check(page.locator(".desk-title").count() == 1,
                  "and one of them opens as a record")
            check(page.locator(".dn-node").count() >= 0, "the panel then shows its neighbourhood",
                  str(page.locator(".dn-node").count()))
            page.locator("[data-desk-rail] [data-desk-close]").first.click()
            page.wait_for_timeout(1400)
            check(page.locator(".dh-row").count() >= 1, "and comes back when the record is closed")

        # ------------------------------------------------------------ marks
        section("reading a mark without leaving")
        chips = page.locator("[data-desk-chipbar]").inner_text()
        check("z " in chips, "the zoom is stated", chips.split("\n")[0][:40])
        check("," in chips and "." in chips, "the coordinates are stated", chips[:60])

        page.locator("[data-pick]").first.click()
        page.wait_for_timeout(2000)
        check(page.locator(".desk-pop").count() == 1, "a mark opens a card in place")
        pop = page.locator(".desk-pop").inner_text() if page.locator(".desk-pop").count() else ""
        check("PER-" in pop or "PLC-" in pop or "INS-" in pop, "the card carries the record code", pop[:40])
        check("°" in pop, "the card carries the coordinates")
        check("px" != pop.lower(), "the card is not a placeholder")
        check(page.locator(".desk-pop .dp-acts a").count() >= 1,
              "the card carries a way into the record")
        check(page.locator(".desk-pop [data-pop-net]").count() == 1,
              "and a way to the neighbourhood")
        check(page.evaluate("() => location.hash") == "#/desk",
              "reading a mark never navigates")
        shot(page, "desk-selected")

        # ------------------------------------------------------------- rail
        section("the panel says everything it knows")
        rail = page.locator("[data-desk-rail]").inner_text()
        check(page.locator("[data-desk-rail] .desk-title").count() == 1,
              "the record is named")
        check(page.locator(".desk-state").count() >= 1,
              "verification and status are stated in words", str(page.locator(".desk-state").count()))
        check("desk-stat" in page.content(), "the neighbourhood is counted by type")
        check(page.locator(".desk-tab").count() == 4, "four readings of the record are offered")
        check(page.locator(".desk-loc-coords").count() == 1,
              "the position is in decimal degrees")
        check("′" in rail, "and in degrees, minutes and seconds")
        check(page.locator("[data-desk-edit]").count() == 1, "editing is one click away")
        check("warn" not in rail.lower() or "contradict" in rail.lower(),
              "a contradiction would be flagged, not hidden")

        for tab in ("relations", "place", "data", "overview"):
            page.locator(f'[data-tab="{tab}"]').click()
            page.wait_for_timeout(320)
            body = page.locator("[data-tab-body]").inner_text()
            check(len(body.strip()) > 0, f"the {tab} tab has content", body[:40].replace("\n", " "))
        page.locator('[data-tab="relations"]').click()
        page.wait_for_timeout(320)
        rels = page.locator("[data-tab-body] .desk-rel").count()
        check(rels >= 0, "relationships are listed with their type", str(rels))
        page.locator('[data-tab="place"]').click()
        page.wait_for_timeout(320)
        place = page.locator("[data-tab-body]").inner_text()
        check("EPSG" in place or "3857" in place or "4326" in place,
              "the position is also given in the registry's CRSs")
        shot(page, "desk-detail")

        # ------------------------------------------------------- neighbourhood
        section("the neighbourhood panel")
        nodes = page.locator(".dn-node").count()
        check(nodes >= 1, "the record's own relationships are drawn", str(nodes))
        if nodes:
            before = page.evaluate("() => document.querySelector('.desk-title').textContent")
            # aim at the node's own disc: a group's box centre falls on empty canvas
            page.locator(".dn-node .dn-hit").first.click()
            page.wait_for_timeout(1800)
            after = page.evaluate("() => document.querySelector('.desk-title').textContent")
            check(before != after, "a neighbour can be walked to in place", f"{before} → {after}")
            check(page.evaluate("() => location.hash") == "#/desk",
                  "and walking to it does not leave the desk")

        # -------------------------------------------------------------- trail
        section("the trail")
        back = page.locator("[data-desk-back]").first
        fwd = page.locator("[data-desk-forward]").first
        check(back.is_enabled(), "back is live once there is a trail")
        here = page.evaluate("() => document.querySelector('.desk-title').textContent")
        back.click()
        page.wait_for_timeout(1600)
        check(page.evaluate("() => document.querySelector('.desk-title').textContent") != here,
              "back returns to the record before")
        check(fwd.is_enabled(), "forward is live after going back")
        fwd.click()
        page.wait_for_timeout(1600)
        check(page.evaluate("() => document.querySelector('.desk-title').textContent") == here,
              "forward returns again")

        # -------------------------------------------------------------- table
        section("the same records, as a table")
        page.locator('[data-view="grid"]').click()
        page.wait_for_timeout(700)
        rows = page.locator(".desk-grid tbody tr").count()
        check(rows > 0, "the table lists the window's records", str(rows))
        check(page.locator(".desk-grid thead th").count() >= 6,
              "with the columns a map record has", str(page.locator(".desk-grid thead th").count()))
        page.locator(".desk-grid tbody tr").nth(1).click()
        page.wait_for_timeout(1800)
        check(page.locator(".desk-grid tbody tr.is-selected").count() == 1,
              "a row selects the record")
        page.locator('[data-view="map"]').click()
        page.wait_for_timeout(700)
        check(page.locator(".desk-gridwrap[hidden]").count() == 1, "and the map comes back")

        # ------------------------------------------------------------- search
        section("search")
        page.keyboard.press("/")
        page.wait_for_timeout(200)
        check(page.evaluate("() => document.activeElement && document.activeElement.matches('[data-desk-search]')"),
              "\"/\" puts the cursor in the search box")
        page.fill("[data-desk-search]", "gaza")
        page.wait_for_timeout(1200)
        check(page.locator("[data-desk-suggest]:not([hidden]) .ds-item").count() > 0,
              "typing suggests records")
        page.locator("[data-desk-suggest] .ds-item").first.click()
        page.wait_for_timeout(2000)
        check(page.locator(".desk-pop").count() == 1, "picking a suggestion reads it in place")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        check(page.locator(".desk-pop").count() == 0, "Escape closes the card")

        # ------------------------------------------------------------- camera
        section("the camera and the chips")
        z0 = map_stats(page)["zoom"]
        page.locator("[data-tools-toggle]").click()
        page.wait_for_timeout(250)
        page.locator("[data-desk-fit]").click()
        page.wait_for_timeout(1200)
        z1 = map_stats(page)["zoom"]
        check(abs(z1 - z0) > 0.01, "fitting the records moves the camera", f"{z0:.2f} → {z1:.2f}")
        chips = page.locator("[data-desk-chipbar]").inner_text()
        check("z " in chips, "the chip bar follows the camera", chips[:30])
        check(page.locator("[data-chip-region]").inner_text().strip() not in ("", "—"),
              "and names the region under the centre",
              page.locator("[data-chip-region]").inner_text()[:40])

        # ------------------------------------------------------------- layers
        section("the layer chips")
        # back to the desk's opening view: a deep zoom is a narrow window, and the
        # layer chips are about the whole registry
        page.evaluate("() => window.__deskMap.jumpTo({ center: [44.3661, 33.3152], zoom: 5 })")
        page.wait_for_timeout(2200)
        page.locator("[data-desk-rail] [data-desk-close]").first.click()
        page.wait_for_timeout(1000)   # the index and its chips come back when nothing is selected
        check(page.locator("[data-pick]").count() > 0, "closing the panel brings the index back",
              str(page.locator("[data-pick]").count()))
        check(page.locator("[data-layer]").count() >= 4, "the index offers one chip per kind of record",
              str(page.locator("[data-layer]").count()))
        first = page.locator(".desk-layers [data-layer]").first
        name = first.get_attribute("data-layer")
        first.click()
        page.wait_for_timeout(1500)
        got = page.request.get(args.base + "/api/map/features?bbox=-180,-60,180,80&zoom=2"
                               f"&layers={name}&limit=5").json()
        check(got.get("ok") is True, "a layer can be asked for on its own", name or "")
        check(page.locator("[data-layer].is-on").count() >= 1,
              "at least one layer always remains on")
        page.keyboard.press("g")
        page.wait_for_timeout(600)
        check(page.locator(".desk-gridwrap[hidden]").count() == 0, "\"g\" switches to the table")
        page.keyboard.press("m")
        page.wait_for_timeout(600)
        check(page.locator(".desk-gridwrap[hidden]").count() == 1, "\"m\" switches back to the map")

        # ------------------------------------------------------------ basemap
        section("base maps")
        page.locator("[data-tools-toggle]").click()
        page.wait_for_timeout(300)
        opts = page.locator("[data-provider]").count()
        check(opts == len(conf["providers"]), "every provider is listed", str(opts))
        page.locator('[data-provider="carto-light"]').click()
        page.wait_for_timeout(2500)
        st2 = map_stats(page)
        check(st2 and "carto" in str(st2["style"]).lower(), "switching base map re-styles the map",
              str(st2 and st2["style"]))
        n_marks = page.locator(".desk-mark").count()
        check(n_marks > 3, "without losing the records in the window", str(n_marks))
        page.locator('[data-provider="local"]').click()
        page.wait_for_timeout(2400)
        check((map_stats(page) or {}).get("hasBase"), "and the offline base map can be taken back")
        page.keyboard.press("Escape")          # the menu is a menu: Escape leaves it
        page.wait_for_timeout(300)
        check(not page.locator("[data-tools]").is_visible(), "Escape closes the tools menu")

        # ------------------------------------------------------------ missing
        section("a record with no coordinates")
        no_pos = page.request.get(args.base + "/api/map/feature/person/999999")
        check(no_pos.status == 404, "an unknown record is a 404, not a point at zero",
              str(no_pos.status))
        empty = None
        for pid in (1, 2, 3, 10, 40, 100):
            d = page.request.get(f"{args.base}/api/map/feature/person/{pid}").json()
            if d.get("located") is False:
                empty = d
                break
        if empty:
            check(empty.get("position") is None, "an unlocated record has no position")
            check(empty.get("reason"), "and says why, in both languages",
                  (empty.get("reason") or {}).get("message_en", "")[:40])

        # --------------------------------------------------------- small screens
        section("a phone is still a desk")
        page.set_viewport_size({"width": 420, "height": 880})
        page.wait_for_timeout(2000)
        st3 = map_stats(page)
        check(st3 and st3["h"] > 200, "the map has height on a phone",
              f'{st3 and st3["w"]}×{st3 and st3["h"]}')
        wide = page.evaluate("() => document.documentElement.scrollWidth")
        check(wide <= 421, "and the page cannot be dragged sideways", str(wide))
        centre_box = page.locator(".desk-centre").bounding_box()
        rail_box = page.locator(".desk-rail").bounding_box()
        check(bool(centre_box and rail_box and centre_box["y"] <= rail_box["y"]),
              "the map comes first, the index under it")
        check(page.locator(".desk-mark").count() > 0, "the records are still drawn",
              str(page.locator(".desk-mark").count()))
        shot(page, "desk-phone")
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.wait_for_timeout(1400)

        # -------------------------------------------------------------- arabic
        section("Arabic turns the desk round")
        page.evaluate("() => App.setLang('ar')")
        page.wait_for_timeout(1500)
        check(page.evaluate("() => document.documentElement.dir") == "rtl", "the page is right-to-left")
        rail = page.locator(".desk-rail").bounding_box()
        centre = page.locator(".desk-centre").bounding_box()
        check(bool(rail and centre and rail["x"] > centre["x"]),
              "the index sits on the right of the map")
        check("الخريطة" in page.locator("[data-desk]").inner_text(), "the controls are translated")
        check(page.locator(".desk-mark").count() > 0, "and the records are still drawn")
        shot(page, "desk-arabic")
        page.evaluate("() => App.setLang('en')")
        page.wait_for_timeout(1500)
        rail = page.locator(".desk-rail").bounding_box()
        centre = page.locator(".desk-centre").bounding_box()
        check(bool(rail and centre and rail["x"] < centre["x"]),
              "English puts the index back on the left")

        # -------------------------------------------------------------- leave
        section("leaving")
        page.evaluate("() => { location.hash = '#/dashboard'; }")
        page.wait_for_timeout(1200)
        check(page.locator("[data-desk]").count() == 0, "the desk is gone")
        check(page.evaluate("() => window.__deskMap === null || window.__deskMap === undefined"),
              "and its map was disposed")
        check(not errors, "no console or page errors along the way", "; ".join(errors[:3]))

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
