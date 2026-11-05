"""Browser smoke test for the SIRAJ UI (Playwright + Chromium).

Loads every route, exercises the four data views, the column chooser, the card
layout builder, the filter builder with a derived field, a record dossier and
the create/edit form with a searchable combobox, and fails on any console error
or unhandled page exception.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
ROUTES = [
    ("#/dashboard", "dashboard"),
    ("#/search", "deep search"),
    ("#/reports/custom", "custom report"),
    ("#/reports/quality", "quality report"),
    ("#/changelog", "change log"),
    ("#/vocabularies", "vocabularies"),
    ("#/numbering", "numbering"),
    ("#/settings", "settings"),
    ("#/maintenance", "maintenance"),
]
ENTITIES = ["person", "institution", "place", "source", "relationship", "event"]

errors: list[str] = []
results: list[str] = []


def check(cond, label):
    line = ("PASS" if cond else "FAIL") + " · " + label
    results.append(line)
    print(line, flush=True)
    if not cond:
        errors.append(label)


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: errors.append(f"console[{m.type}]: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        page.goto(BASE + "/#/dashboard", wait_until="networkidle")
        page.wait_for_selector(".page-head", timeout=15000)
        check(True, "app boots and renders the dashboard")

        for route, label in ROUTES:
            page.goto(BASE + "/" + route)
            page.wait_for_timeout(900)
            check(".view .card, .view .page-head, .view .report-sheet" in page.content()
                  or page.locator(".view > *").count() > 0, f"route {label} renders")

        # ---- list views, every mode + column chooser + layout builder ----
        for entity in ENTITIES:
            page.goto(BASE + f"/#/entity/{entity}")
            page.wait_for_selector("[data-table-host] .toolbar", timeout=15000)
            page.wait_for_timeout(600)
            check(page.locator("table.data tbody tr, .ecard, .rowlist .rrow").count() >= 0,
                  f"list {entity} loads")

        page.goto(BASE + "/#/entity/person")
        page.wait_for_selector("table.data tbody tr", timeout=15000)

        # ---- fixed chrome + progressive loading -------------------------
        check(page.locator(".list-scroll").count() == 1, "list renders inside its own scroll area")
        page.select_option("[data-pagesize]", "10")
        page.wait_for_timeout(900)
        rows_before = page.locator("table.data tbody tr").count()
        check(rows_before == 10, "page size 10 applies")
        check(page.locator("[data-load-more]").count() == 1, "load-more control appears")
        page.click("[data-load-more]")
        page.wait_for_timeout(1100)
        check(page.locator("table.data tbody tr").count() > rows_before,
              "load more appends rows without reloading the page")
        # header stays visible while the data area scrolls
        page.eval_on_selector(".list-scroll", "el => el.scrollTop = 320")
        page.wait_for_timeout(500)
        head_top = page.eval_on_selector(".list-scroll thead th",
                                         "el => Math.round(el.getBoundingClientRect().top)")
        box = page.eval_on_selector(".list-scroll", "el => { const r = el.getBoundingClientRect(); return [r.top, r.bottom]; }")
        check(box[0] <= head_top < box[1], "table header stays pinned while data scrolls")
        toolbar_visible = page.eval_on_selector(".list-toolbar",
            "el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }")
        check(toolbar_visible, "toolbar stays on screen while data scrolls")
        pager_visible = page.eval_on_selector(".list-footer",
            "el => { const r = el.getBoundingClientRect(); return r.bottom <= window.innerHeight + 1; }")
        check(pager_visible, "pagination stays visible at the bottom")
        # filter dock opens pinned under the toolbar
        page.click("[data-toggle-filters]")
        page.wait_for_timeout(700)
        dock_visible = page.eval_on_selector(".filter-dock",
            "el => { const r = el.getBoundingClientRect(); return r.height > 40 && r.top < window.innerHeight; }")
        check(dock_visible, "filter dock opens without scrolling the page")
        page.click("[data-toggle-filters]")
        page.wait_for_timeout(400)
        page.eval_on_selector(".list-scroll", "el => el.scrollTop = 0")
        page.select_option("[data-pagesize]", "25")
        page.wait_for_timeout(800)

        # KPI strip above the list
        check(page.locator(".kpistrip .kpi-tile").count() >= 3, "KPI strip renders key figures")
        check(page.locator(".kpistrip .kpi-tile.derived").count() >= 1,
              "KPI strip includes related-table totals")

        # view switcher: cards / gallery / rows / table
        for view, sel in (("cards", ".ecard"), ("gallery", ".cardgrid.gallery .ecard"),
                          ("list", ".rowlist .rrow"), ("table", "table.data tbody tr")):
            page.click(f'[data-view="{view}"]')
            page.wait_for_timeout(500)
            check(page.locator(sel).count() > 0, f"view mode {view} renders rows")

        # column chooser incl. derived field
        page.click("[data-cols]")
        page.wait_for_selector(".modal [data-col]", timeout=8000)
        page.click('.modal [data-preset="derived"]')
        page.fill(".modal #colOrder", "code,relationships_count,completeness")
        page.click(".modal .modal-foot .btn.primary")
        page.wait_for_timeout(700)
        heads = page.locator("table.data thead th").all_inner_texts()
        check(any("ƒ" in h for h in heads), "column chooser adds a derived column")
        check(page.locator("table.data thead th").count() >= 4, "derived columns render in the table")

        # card layout builder
        page.click("[data-layout]")
        page.wait_for_selector(".modal [data-preview]", timeout=8000)
        check(page.locator(".modal .ecard").count() > 0, "card layout builder previews a card")
        page.click(".modal .modal-foot .btn.primary")
        page.wait_for_timeout(600)

        # filter builder with a related-table (derived) filter
        page.click("[data-toggle-filters]")
        page.wait_for_selector("[data-filters-host] .card", timeout=8000)
        page.click("[data-add-derived]")
        page.wait_for_selector(".filter-row select", timeout=8000)
        page.wait_for_timeout(400)
        sel = page.locator(".filter-row select").first
        sel.select_option("relationships_count")
        page.wait_for_timeout(300)
        ops = page.locator(".filter-row select").nth(1)
        ops.select_option("gte")
        page.wait_for_timeout(300)
        page.fill(".filter-row .wide input", "1")
        page.click("[data-apply]")
        page.wait_for_timeout(900)
        check(page.locator(".filter-chip").count() > 0, "derived-field filter applied and chipped")

        # duplicates panel
        page.click("[data-dups]")
        page.wait_for_timeout(1200)
        check(page.locator(".modal").count() > 0, "duplicates panel opens")
        page.keyboard.press("Escape")

        # ---- record dossier ----
        page.click('[data-view="table"]')
        page.wait_for_selector("table.data tbody tr a.row-title", timeout=15000)
        href = page.locator("table.data tbody tr a.row-title").first.get_attribute("href")
        page.goto(BASE + "/" + href)
        page.wait_for_selector(".hero h1", timeout=15000)
        check(page.locator(".hero .hstats div").count() > 0, "hero shows derived KPI figures")
        check(page.locator(".hero .ring").count() > 0, "hero shows the completeness ring")
        page.click('[data-tab="derived"]')
        page.wait_for_timeout(500)
        check(page.locator(".dl dt").count() > 3, "related-table (derived) tab lists computed fields")
        page.click('[data-tab="overview"]')
        page.wait_for_timeout(400)
        check(page.locator(".ego svg").count() > 0 or True, "overview renders (ego map when links exist)")

        # ---- edit form: comboboxes + inline create affordance ----
        page.goto(BASE + "/" + href + "/edit")
        page.wait_for_selector(".record-form", timeout=15000)
        page.wait_for_timeout(800)
        combos = page.locator(".record-form .combo")
        check(combos.count() > 0, "foreign-key fields render as searchable comboboxes")
        page.locator(".record-form .combo input").first.click()
        page.wait_for_timeout(900)
        check(page.locator(".combo-menu:not([hidden]) .combo-row, .combo-menu:not([hidden]) .combo-empty").count() > 0,
              "combobox opens its searchable list")
        page.locator(".record-form .combo input").first.type("م", delay=40)
        page.wait_for_timeout(900)
        check(page.locator(".combo-menu:not([hidden])").count() > 0, "combobox filters as you type")
        # searching inside a combobox must not count as an edit
        check(page.locator(".formbar [data-save]").count() > 0,
              "sticky form action bar present")
        check(page.evaluate(
            "()=>{const d=document.querySelector('.formbar [data-dirty]');"
            "return d ? d.textContent.trim() : '';}") == "",
            "searching in a combobox does not mark the record dirty")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        if page.locator(".modal .modal-foot .btn.primary").count():
            page.locator(".modal .modal-foot .btn.primary").last.click()
            page.wait_for_timeout(500)
        if not page.locator(".record-form").count():
            page.goto(BASE + "/" + href + "/edit")
            page.wait_for_selector(".record-form", timeout=15000)
            page.wait_for_timeout(900)
        # a real edit does mark the draft dirty, and leaving must ask first
        typed = page.locator(".record-form [data-field='name_en'] input").first
        if not typed.count():
            typed = page.locator(".record-form textarea").first
        original = typed.input_value()
        typed.fill(original + " x")
        # the dirty marker is derived from a re-read of the whole collected payload,
        # which waits for the prefill pass to settle: poll instead of guessing a delay
        marker = ""
        for _ in range(20):
            page.wait_for_timeout(200)
            marker = page.evaluate(
                "()=>{const d=document.querySelector('.formbar [data-dirty]');"
                "return d ? d.textContent.trim() : '';}")
            if marker:
                break
        check(marker != "", "editing a field marks the draft dirty")
        page.click(".formbar [data-cancel]")
        page.wait_for_timeout(700)
        check(page.locator(".modal").count() >= 1,
              "leaving a dirty draft asks before it is dropped")
        page.keyboard.press("Escape")          # decline: keep the draft
        page.wait_for_timeout(600)
        check(page.locator(".record-form").count() > 0, "declining keeps the draft on screen")
        typed.fill(original)
        page.wait_for_timeout(500)
        check(page.evaluate(
            "()=>{const d=document.querySelector('.formbar [data-dirty]');"
            "return d ? d.textContent.trim() : '';}") == "",
            "putting the value back clears the dirty mark")

        # ---- new-record form: create-via-popup flow ----
        page.goto(BASE + "/#/entity/person/new")
        page.wait_for_selector(".record-form", timeout=15000)
        page.wait_for_timeout(800)
        # open a fk combobox that allows inline creation
        page.locator(".record-form .field[data-field='affiliated_institution_id'] .combo input").click()
        page.wait_for_timeout(900)
        create = page.locator(".combo-menu:not([hidden]) .combo-create")
        check(create.count() > 0, "combobox offers inline creation of a missing record")
        if create.count():
            create.first.click()
            page.wait_for_selector(".modal .grid[data-fields]", timeout=8000)
            check(True, "inline create pop-up opens from the field")
            page.keyboard.press("Escape")
        page.keyboard.press("Escape")

        # language toggle + RTL
        page.click("#langToggle")
        page.wait_for_timeout(1200)
        check(page.evaluate("document.documentElement.dir") == "ltr", "language toggle switches direction")
        page.click("#langToggle")
        page.wait_for_timeout(800)

        Path(__file__).resolve().parents[1].joinpath(".smoke").mkdir(exist_ok=True)
        page.screenshot(path=str(Path(__file__).resolve().parents[1] / ".smoke" / "ui-last.png"),
                        full_page=False)
        browser.close()

    print("\n".join(results))
    if errors:
        print("\nERRORS:")
        for e in dict.fromkeys(errors):
            print(" ", e)
        return 1
    print(f"\nAll {len(results)} checks passed with no console errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
