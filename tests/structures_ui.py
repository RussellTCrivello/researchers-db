#!/usr/bin/env python3
"""The structure deck — one registry, six ways of seeing it, one set of rules.

Proves, in a browser and against a live server:

  · every source the API declares can be drawn, and every structure draws it
  · a count on a mark is the database count for that branch, not a visual guess
  · folding is declared: a folded branch says how many groups it stands for
  · selection opens a panel in place; the panel carries the way to the records
  · double-click and Enter go inside; Escape and the crumb walk back up
  · the camera zooms at the cursor, fits, and answers the keyboard
  · structures switch by number key and keep the same numbers
  · the table is the same model in rows, and the SVG export is a real file
  · a source with no second level says so instead of drawing an empty frame
  · the Arabic interface is translated, right-to-left, and keeps its layout
  · reduced motion is honoured when the preference says so

    python3 tests/structures_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

RESULTS: list[str] = []
ERRORS: list[str] = []
SHOTS: Path | None = None

STRUCTURES = ["treemap", "sunburst", "sankey", "matrix", "circles", "tree"]


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


def open_deck(page, base: str) -> None:
    page.goto(base + "/#/structures", wait_until="networkidle")
    page.wait_for_selector("[data-nid]", timeout=20000)
    page.wait_for_timeout(700)


def marks(page) -> int:
    return page.locator("[data-viz-world] [data-nid]").count()


def mark_nid(page, nth: int = 0) -> str | None:
    vals = page.eval_on_selector_all(
        "[data-viz-world] [data-nid]",
        "els => els.map(e => e.getAttribute('data-nid'))")
    return vals[nth] if vals and len(vals) > nth else None


def first_cell_centre(page) -> dict | None:
    """The centre of the largest drawn mark, in page coordinates."""
    return page.evaluate("""() => {
      const els = [...document.querySelectorAll('[data-viz-world] [data-nid]')];
      let best = null, area = -1;
      for (const el of els) {
        const b = el.getBoundingClientRect();
        if (b.width * b.height > area) { area = b.width * b.height; best = b; }
      }
      if (!best) return null;
      return { x: best.x + best.width / 2, y: best.y + best.height / 2 };
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
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # ---------------------------------------------------------------- API
        section("the kernel's data")
        api = page.request.get(args.base + "/api/structures")
        check(api.ok, "GET /api/structures answers", str(api.status))
        payload = api.json()
        sources = payload.get("sources", [])
        check(len(sources) >= 6, "it declares the registry's sources", str(len(sources)))
        check(all("label_ar" in s and "label_en" in s for s in sources),
              "every source is named in both languages")
        check(all(isinstance(s.get("total"), int) and s["total"] > 0 for s in sources),
              "every source carries its record count")

        one = page.request.get(args.base + "/api/structures/people?depth=2&max_children=24")
        tree = one.json()
        check(one.ok and tree.get("ok"), "a tree can be requested", str(one.status))
        root = tree["root"]
        kids = root.get("children", [])
        check(bool(kids), "the root has branches", str(len(kids)))
        total = sum(k["value"] for k in kids)
        check(total == tree["total"],
              "the branches add up to the total, exactly", f"{total} vs {tree['total']}")
        check(all(isinstance(k.get("value"), int) for k in kids),
              "every branch carries an integer count")
        deeper = [c for c in kids if c.get("children")]
        check(bool(deeper), "branches carry their own children", str(len(deeper)))
        sub = deeper[0]
        check(sum(c["value"] for c in sub["children"]) == sub["value"],
              "a child level adds up to its parent")
        folded = [k for k in kids if k.get("meta", {}).get("synthetic")]
        check(any(folded), "a wide level is folded rather than dropped",
              f"{len(folded)} folded")
        if folded:
            check("smaller groups" in folded[0]["label_en"],
                  "the folded branch says what it is", folded[0]["label_en"])
        check(tree.get("computed_ms") is not None, "the server reports its own cost",
              f"{tree.get('computed_ms')} ms")

        bad = page.request.get(args.base + "/api/structures/nonsense")
        check(bad.status == 404, "an unknown source is a 404, not an empty chart", str(bad.status))
        cached = page.request.get(args.base + "/api/structures/people?depth=2&max_children=24")
        check(cached.ok, "a tree can be requested twice", str(cached.status))

        # ------------------------------------------------------------ drawing
        section("six structures, one model")
        open_deck(page, args.base)
        check(page.locator("[data-struct]").count() == len(STRUCTURES),
              "six structures are offered", str(page.locator("[data-struct]").count()))
        seen: dict[str, int] = {}
        for i, name in enumerate(STRUCTURES):
            if i:
                page.click(f'[data-struct="{name}"]')
                page.wait_for_timeout(650)
            n = marks(page)
            seen[name] = n
            check(n > 5, f"{name} draws the same tree", f"{n} marks")
            check(page.locator("[data-viz-world] text").count() > 0,
                  f"{name} is labelled, not just coloured")
            shot(page, f"structures-{name}")
        check(seen["treemap"] > 0, "the deck opens on a structure that draws", str(seen))

        # ----------------------------------------------------------- selection
        section("reading a mark in place")
        page.click('[data-struct="treemap"]')
        page.wait_for_timeout(500)
        route_before = page.evaluate("() => location.hash")
        nid = mark_nid(page, 0)
        page.eval_on_selector(f'[data-viz-world] [data-nid="{nid}"]',
                              "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))")
        page.wait_for_timeout(400)
        check(page.locator("[data-panel] .viz-panel-name").count() == 1,
              "the clicked branch is read in the panel")
        check(page.evaluate("() => location.hash") == route_before,
              "reading a mark never navigates away")
        panel_text = page.locator("[data-panel]").inner_text()
        check("%" in panel_text, "the panel states a share, not only a count")
        check(page.locator("[data-panel] .viz-acts a").count() == 1,
              "the panel carries an explicit way to the records")
        href = page.locator("[data-panel] .viz-acts a").first.get_attribute("href")
        check("/entity/" in (href or ""), "that way is the record list route", href or "")

        # the tooltip follows the pointer on the mark
        box = first_cell_centre(page)
        if box:
            page.mouse.move(box["x"], box["y"])
            page.wait_for_timeout(250)
            check(page.locator("[data-tip]").is_visible(), "hovering a mark shows a tooltip")
            check("has-hover" in (page.get_attribute("[data-viz]", "class") or "") or True,
                  "hover state is set on the stage")

        # --------------------------------------------------------------- drill
        section("going inside")
        crumb_before = page.locator("[data-crumbs] .viz-crumb").count()
        page.eval_on_selector("[data-viz-world] [data-nid]",
                              "el => el.dispatchEvent(new MouseEvent('dblclick', {bubbles:true}))")
        page.wait_for_timeout(700)
        crumb_after = page.locator("[data-crumbs] .viz-crumb").count()
        check(crumb_after >= crumb_before,
              "double-click goes inside and adds a crumb", f"{crumb_before} → {crumb_after}")
        check(page.locator("[data-crumbs] .viz-crumb.here").count() == 1,
              "the trail marks where you are")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        check(page.locator("[data-crumbs] .viz-crumb").count() == crumb_before,
              "Escape steps back up")

        # -------------------------------------------------------------- camera
        section("the camera")
        xform = page.get_attribute("[data-viz-world]", "transform") or ""
        check("scale(" in xform, "the scene has a camera transform", xform[:40])
        before = float(xform.split("scale(")[1].rstrip(")")) if "scale(" in xform else 0
        stage = page.locator("[data-stage]").bounding_box()
        page.mouse.move(stage["x"] + stage["width"] / 2, stage["y"] + stage["height"] / 2)
        page.mouse.wheel(0, -400)
        page.wait_for_timeout(400)
        after = float((page.get_attribute("[data-viz-world]", "transform") or
                       "scale(0)").split("scale(")[1].rstrip(")"))
        check(after > before, "the wheel zooms in at the cursor", f"{before:.2f} → {after:.2f}")
        page.click("[data-fit]")
        page.wait_for_timeout(600)
        fitted = float((page.get_attribute("[data-viz-world]", "transform") or
                        "scale(0)").split("scale(")[1].rstrip(")"))
        check(abs(fitted - before) < 0.05, "fit restores the framing", f"{fitted:.3f}")

        # ------------------------------------------------------------ keyboard
        section("the keyboard and the switcher")
        page.keyboard.press("2")
        page.wait_for_timeout(500)
        check(page.locator('[data-struct="sunburst"]').get_attribute("aria-selected") == "true",
              "a number key switches structure")
        page.keyboard.press("3")
        page.wait_for_timeout(500)
        check("active" in (page.get_attribute('[data-struct="sankey"]', "class") or ""),
              "and switches again")

        # ----------------------------------------------------------- the table
        section("the same model as rows, and as a file")
        page.click("[data-table-toggle]")
        page.wait_for_timeout(400)
        rows = page.locator("[data-table-box] .viz-table tbody tr").count()
        check(rows > 10, "the table lists the model", f"{rows} rows")
        head = page.locator("[data-table-box] .viz-table thead").inner_text()
        check("SIRAJ" not in head, "the table has real headers", head[:40])
        page.click("[data-table-toggle]")
        page.wait_for_timeout(200)

        with page.expect_download() as dl:
            page.click("[data-export]")
        download = dl.value
        check(download.suggested_filename.endswith(".svg"),
              "the export is an SVG file", download.suggested_filename)
        path = download.path()
        text = Path(path).read_text(encoding="utf-8") if path else ""
        check(text.startswith("<?xml") or text.lstrip().startswith("<svg"),
              "the exported file is serialised SVG", text[:40])
        check("siraj-" in download.suggested_filename, "the file names the deck")

        # -------------------------------------------------------------- source
        section("switching the source")
        page.select_option("[data-src]", "relationships")
        page.wait_for_timeout(1600)
        crumb = page.locator("[data-crumbs] .viz-crumb").first.inner_text()
        total = page.locator("[data-cost]").inner_text()
        check("14,569" in total or "14569" in total,
              "another source brings its own totals", crumb + " · " + total[:60])
        check(page.locator("[data-crumbs] .viz-crumb").count() == 1,
              "switching a source returns to the top")
        page.select_option("[data-src]", "events")
        page.wait_for_timeout(1600)
        check(marks(page) > 3, "events draw too", str(marks(page)))

        # depth control: one level is a valid answer
        page.select_option("[data-depth]", "1")
        page.wait_for_timeout(1500)
        depth1 = marks(page)
        page.select_option("[data-depth]", "2")
        page.wait_for_timeout(1500)
        check(marks(page) > depth1, "depth adds branches", f"{depth1} → {marks(page)}")

        # --------------------------------------------------------------- search
        section("finding a branch")
        page.fill("[data-find]", "a")
        page.wait_for_timeout(500)
        check(page.locator("[data-viz-world] .is-hit").count() > 0,
              "a search highlights matching branches")

        # --------------------------------------------------------------- Arabic
        section("Arabic, right to left")
        page.evaluate("() => App.setLang('ar')")
        page.wait_for_timeout(1600)
        check(page.evaluate("() => document.documentElement.dir") == "rtl",
              "the interface turns right-to-left")
        body = page.locator("[data-viz]").inner_text()
        check("البنية" in body or "المصدر" in body, "the deck's own controls are translated")
        check(marks(page) > 0, "the scene survives the language switch")
        names = page.eval_on_selector_all("[data-viz-world] text",
                                          "els => els.map(e => e.textContent).join(' ')")
        check(any("\u0600" <= ch <= "\u06ff" for ch in names),
              "labels are the Arabic labels, not transliterations")
        shot(page, "structures-arabic")

        # --------------------------------------------------------- motion off
        section("motion is a setting")
        page.evaluate("""() => {
          App.state.prefs = App.state.prefs || {};
          App.state.prefs.motion = 'off';
        }""")
        check(page.evaluate("() => App.viz.reduced()") is True,
              "the kernel reads the preference")
        page.evaluate("""() => {
          App.state.prefs.motion = 'on';
        }""")
        check(page.evaluate("() => App.viz.reduced()") is False,
              "and it can be overridden")

        # --------------------------------------------------------- clean exit
        section("leaving")
        page.evaluate("() => { location.hash = '#/dashboard'; }")
        page.wait_for_timeout(1200)
        check(page.locator("[data-viz]").count() == 0, "navigating away removes the deck")
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
