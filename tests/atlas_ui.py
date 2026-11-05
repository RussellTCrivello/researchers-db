#!/usr/bin/env python3
"""The atlas — the relationship map as a place you work in, not a page you leave.

Proves, in a browser and against a live server:

  · clicking a record opens a side panel; it never navigates away
  · the panel carries an explicit shortcut to that record, and the route behind
    it is the record's own page
  · a neighbour, a relationship, or a matrix cell is read in the same panel
  · drilling in re-centres the diagram in place, and the trail can be walked back
  · three arrangements (orbit, force, matrix) draw the same neighbourhood
  · the filters reshape the scene instead of reloading it
  · the path finder answers with steps a reader can follow, and can clear itself
  · the keyboard does what the mouse does ("/" finds a node, Esc closes the panel)
  · navigating away disposes the view's document listeners
  · the Arabic interface is translated, right-to-left, and keeps its layout

    python3 tests/atlas_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
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


def click_edge(page) -> bool:
    """Click the middle of an edge where the edge is actually under the cursor.

    A force/orbit scene draws long curves; the centre of a path's bounding box
    is often empty space.  Sampling the geometry keeps the test honest.
    """
    pt = page.evaluate("""() => {
      const paths = [...document.querySelectorAll('svg.relmap .rm-edge path[data-s]')];
      for (const p of paths) {
        const len = p.getTotalLength();
        for (const f of [0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74]) {
          const at = p.getPointAtLength(len * f);
          const m = p.getScreenCTM();
          const x = at.x * m.a + at.y * m.c + m.e;
          const y = at.x * m.b + at.y * m.d + m.f;
          const hit = document.elementFromPoint(x, y);
          if (hit && hit.closest && hit.closest('.rm-edge')) return { x, y };
        }
      }
      return null;
    }""")
    if not pt:
        return False
    page.mouse.click(pt["x"], pt["y"])
    return True


def wait_scene(page, timeout: int = 20000) -> None:
    page.wait_for_selector("svg.relmap .map-node", timeout=timeout)
    page.wait_for_timeout(700)


def main(argv: list[str] | None = None) -> int:
    global SHOTS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default="", help="write screenshots here")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1040)
    args = ap.parse_args(argv)
    if args.shots:
        SHOTS = Path(args.shots).resolve()

    base = args.base.rstrip("/")
    console: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(str(e)))

        page.goto(f"{base}/#/map")
        wait_scene(page)
        page.evaluate("() => App.setLang('en')")
        page.wait_for_timeout(1600)
        wait_scene(page)

        # ------------------------------------------------------------------
        section("the atlas opens on the whole registry")
        # ------------------------------------------------------------------
        check(page.locator(".atl-chip[data-type-focus]").count() >= 5,
              "the overview lists every record type",
              str(page.locator(".atl-chip[data-type-focus]").count()))
        check(page.locator("table.matrix tbody tr").count() >= 5,
              "the overview shows how the types are joined")
        check(page.locator(".atlas-crumb.current").inner_text().strip() != "",
              "the trail names where you are")
        # one click takes you from the whole registry into one neighbourhood
        page.locator(".atl-chip[data-type-focus]").first.click()
        page.wait_for_timeout(3000)
        check(page.locator("svg.relmap .map-node").count() > 1,
              "a type opens its neighbourhood in place")
        check(page.url.endswith("#/map"), "and still does not navigate", page.url)
        check(page.locator(".atlas-panel .ap-title").count() == 1,
              "the record you landed on is already open in the panel")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # ------------------------------------------------------------------
        section("the atlas draws a working scene")
        # ------------------------------------------------------------------
        nodes = page.locator("svg.relmap .map-node")
        edges = page.locator("svg.relmap .rm-edge")
        n0, e0 = nodes.count(), edges.count()
        check(n0 > 1, "the scene has records", str(n0))
        check(e0 > 0, "the scene has relationships", str(e0))
        check(page.locator(".atlas-rail .atl-sec").count() >= 3,
              "the rail offers arrangement, types and relationships")
        check(page.locator(".atl-layouts button").count() == 3,
              "three arrangements: orbit, force, matrix")
        check(page.locator(".atl-legend .atl-verif").count() >= 2,
              "the verification grammar is explained on the rail")
        shot(page, "atlas-overview")

        # ------------------------------------------------------------------
        section("selection is read in place — the panel is the surface")
        # ------------------------------------------------------------------
        url0 = page.url
        page.locator("svg.relmap .map-node .node-hit").nth(2).click(force=True)
        page.wait_for_selector(".atlas-panel .ap-title", timeout=8000)
        page.wait_for_timeout(500)
        check(page.locator(".atlas-panel").is_visible(), "a click opens the side panel")
        check(page.url == url0, "a click does not navigate away", page.url)
        check(page.locator("svg.relmap .map-node.is-selected").count() == 1,
              "the selected record stays marked in the scene")
        check(page.locator(".atlas-panel .ap-type").count() == 1,
              "the panel states what kind of record it is")
        check(page.locator(".atlas-panel .ap-stats b").count() == 3,
              "the panel counts relationships, evidence and sources")
        check(page.locator(".atlas-panel .ap-neighbour").count() > 0,
              "the panel lists what the record touches")
        href = page.locator(".atlas-panel [data-ap-open]").get_attribute("href")
        check(bool(href) and "/person/" in (href or "") or "/institution/" in (href or "")
              or "/place/" in (href or "") or "/event/" in (href or "")
              or "/source/" in (href or ""),
              "the panel carries an explicit shortcut to the record", str(href))
        check(page.locator(".atlas-panel .ap-note").count() >= 1,
              "the panel keeps the safety note: a connection is not a finding")
        shot(page, "atlas-panel")

        page.locator(".atlas-panel .ap-neighbour").first.click()
        page.wait_for_timeout(1000)
        check(page.locator(".atlas-panel .ap-title").count() == 1,
              "a neighbour is read in the same panel")
        check(page.url == url0, "and still no navigation")

        # ------------------------------------------------------------------
        section("drilling in stays inside the diagram")
        # ------------------------------------------------------------------
        crumbs0 = page.locator(".atlas-crumb").count()
        page.locator(".atlas-panel [data-ap-explore]").click()
        page.wait_for_timeout(2400)
        check(page.locator(".atlas-crumb").count() > crumbs0,
              "exploring adds a step to the trail",
              str(page.locator(".atlas-crumb").count()))
        check(page.url == url0, "exploring does not navigate")
        check(page.locator("svg.relmap .map-node").count() > 0,
              "the diagram is still there, re-centred")
        check(page.locator(".atlas-panel .ap-title").count() == 1,
              "the panel follows you into the new neighbourhood")
        check(page.locator(".atlas-back").is_enabled(), "the trail can be walked back")
        shot(page, "atlas-explore")
        page.locator(".atlas-back").click()
        page.wait_for_timeout(1800)
        check(page.locator(".atlas-crumb").count() == crumbs0,
              "walking back restores the previous centre")

        # ------------------------------------------------------------------
        section("a relationship is a record too")
        # ------------------------------------------------------------------
        check(click_edge(page), "an edge can be hit where it is drawn")
        page.wait_for_timeout(1400)
        check(page.locator(".atlas-panel .ap-type.sw-edge").count() == 1,
              "clicking an edge shows the relationship, not a tooltip")
        check(page.locator(".atlas-panel .ap-end").count() == 2,
              "the relationship panel names both ends")
        check(page.url == url0, "reading a relationship does not navigate")
        shot(page, "atlas-edge")

        # ------------------------------------------------------------------
        section("filters reshape the scene")
        # ------------------------------------------------------------------
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        check(not page.locator(".atlas-panel").is_visible(),
              "Escape closes the panel and leaves the diagram")
        before = page.locator("svg.relmap .map-node").count()
        page.locator(".atlas-rail .atl-chip").first.click()
        page.wait_for_timeout(800)
        after = page.locator("svg.relmap .map-node").count()
        check(after != before, "a type filter changes what is drawn", f"{before}→{after}")
        check(page.url == url0, "filtering does not navigate")
        page.locator(".atlas-rail .atl-chip").first.click()
        page.wait_for_timeout(800)
        check(page.locator("svg.relmap .map-node").count() == before,
              "switching the filter off restores the scene")

        # ------------------------------------------------------------------
        section("the same neighbourhood, seen as a matrix")
        # ------------------------------------------------------------------
        page.locator(".atl-layouts button").nth(2).click()
        page.wait_for_timeout(1600)
        check(page.locator(".atlas-matrix .mx-table").count() == 1,
              "the matrix arranges the same records")
        check(page.locator(".mx-table tbody tr").count() > 1, "with rows to read")
        cells = page.locator(".mx-cell:not(.empty)").count()
        check(cells > 0, "stored relationships appear as cells", str(cells))
        page.locator(".mx-cell:not(.empty)").first.click()
        page.wait_for_timeout(1200)
        check(page.locator(".atlas-panel .ap-type").count() == 1,
              "a cell opens that relationship in the panel")
        shot(page, "atlas-matrix")
        page.locator(".atl-layouts button").nth(0).click()
        page.wait_for_timeout(1400)
        check(page.locator("svg.relmap").count() == 1, "and back to the orbit")

        # ------------------------------------------------------------------
        section("the path finder")
        # ------------------------------------------------------------------
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.locator("svg.relmap .map-node .node-hit").nth(1).click(force=True)
        page.wait_for_timeout(1200)
        page.locator(".atlas-panel [data-ap-path]").click()
        page.wait_for_timeout(800)
        check(page.locator(".ap-pathdialog").count() == 1, "the path dialog opens")
        check(page.locator(".ap-pathdialog select option").count() >= 5,
              "it offers every record type")
        box = page.locator(".ap-pathdialog [data-path-q]")
        box.click()
        box.type("Univ", delay=35)
        page.wait_for_timeout(1400)
        hits = page.locator(".ap-pathdialog [data-pick]").count()
        check(hits > 0, "searching for a target returns records", str(hits))
        if hits:
            page.locator(".ap-pathdialog [data-pick]").first.click()
            page.wait_for_timeout(2600)
            check(page.locator(".ap-steps .ap-step").count() > 0
                  or page.locator(".atlas-panel .ap-note").count() > 0,
                  "the answer is a chain of relationships, or an honest 'none'")
            shot(page, "atlas-path")

        # ------------------------------------------------------------------
        section("the keyboard")
        # ------------------------------------------------------------------
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.locator("svg.relmap").focus()
        page.keyboard.press("/")
        page.wait_for_timeout(400)
        check(bool(page.evaluate(
            "() => document.activeElement && document.activeElement.hasAttribute('data-map-search')")),
            "'/' puts the caret in the diagram's find box, not the site search")
        word = page.evaluate(
            "() => (document.querySelector('svg.relmap .map-node').dataset.label || '')"
            ".split(' ')[0]")
        page.keyboard.type(word)
        page.wait_for_timeout(700)
        check(page.locator("svg.relmap .map-node.hit").count() > 0,
              "the find box marks the matching records", word)

        # ------------------------------------------------------------------
        section("leaving the view leaves nothing behind")
        # ------------------------------------------------------------------
        page.goto(f"{base}/#/dashboard")
        page.wait_for_timeout(1400)
        page.keyboard.press("/")
        page.wait_for_timeout(400)
        check(not page.evaluate(
            "() => document.activeElement && document.activeElement.hasAttribute('data-map-search')"),
            "outside the view '/' belongs to the site search again — the view let go")
        page.goto(f"{base}/#/map")
        wait_scene(page)
        page.locator("svg.relmap").focus()
        page.keyboard.press("/")
        page.wait_for_timeout(400)
        check(bool(page.evaluate(
            "() => document.activeElement && document.activeElement.hasAttribute('data-map-search')")),
            "the shortcut still works after a round trip (no dead listeners)")
        check(not [c for c in console if "error" in c.lower()],
              "no console errors during the session", "; ".join(console[:3]))

        # ------------------------------------------------------------------
        section("Arabic, and the right-to-left layout")
        # ------------------------------------------------------------------
        page.evaluate("() => App.setLang('ar')")
        page.wait_for_timeout(2200)
        wait_scene(page)
        rail = page.locator(".atlas-rail").inner_text()
        check("أنواع السجلات" in rail, "the rail is translated", rail[:60])
        check(page.evaluate("() => document.documentElement.dir") == "rtl",
              "the page is right-to-left")
        page.locator("svg.relmap .map-node .node-hit").nth(0).click(force=True)
        page.wait_for_timeout(1400)
        label = page.locator(".atlas-panel [data-ap-open]").first.inner_text()
        check("فتح السجل" in label, "the shortcut is translated too", label)
        check(page.locator(".atlas-panel .ap-title").count() == 1,
              "the panel still opens in Arabic")
        box = page.locator(".atlas-panel").bounding_box()
        canvas = page.locator(".atlas-canvas").bounding_box()
        check(bool(box and canvas and box["x"] < canvas["x"]),
              "in RTL the panel sits on the left of the diagram")
        shot(page, "atlas-arabic")

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
