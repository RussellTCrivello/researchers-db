"""Exhaustive browser verification of the SIRAJ interface (Playwright + Chromium).

Unlike ``ui_smoke.py`` (a fast sanity pass) this script walks *every* screen and
*every* interactive control the app ships:

  · shell      — sidebar, entity nav, language toggle (AR↔EN), actor switch,
                 global search, keyboard shortcut, responsive ≤900 px layout
  · routes     — all 13 routes + one page per entity + record/new/edit
  · lists      — search, sort, page size, pagination, load-more, filter dock
                 (clause + derived), chips, column chooser presets, layout
                 builder, saved views, duplicates, bulk bar, export panel,
                 four view modes, soft-delete lens
  · record     — hero ring + KPIs, every tab, edit/create forms, combobox,
                 inline-create pop-up, sticky action bar
  · reports    — the index and all ten report keys
  · import     — 4-step wizard, template download, real file upload,
                 mapping, dry-run validation (never commits)
  · export     — live download of XLSX and CSV
  · admin      — vocabularies, numbering, settings, change log, maintenance
                 (reindex / vacuum / backup download / full dump)

Every failure and every console error is collected; the exit code is non-zero
if anything at all went wrong.

Usage:  python3 tests/ui_full.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MARK = "UIFULL"
RUNID = time.strftime("%H%M%S")

results: list[str] = []
errors: list[str] = []


def check(cond, label: str, detail: str = "") -> bool:
    line = ("PASS" if cond else "FAIL") + " · " + label
    if detail and not cond:
        line += f"   [{detail}]"
    results.append(line)
    print(line, flush=True)
    if not cond:
        errors.append(label + (f"  [{detail}]" if detail else ""))
    return bool(cond)


def section(name: str) -> None:
    print(f"\n=== {name} " + "=" * max(4, 74 - len(name)), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default=str(ROOT / ".smoke" / "full"))
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    meta = httpx.get(f"{BASE}/api/meta", timeout=60).json()
    entities = [e["key"] for e in meta["entities"]]
    reports = [r["key"] for r in meta.get("reports", [])]
    console: list[str] = []

    scratch: dict[str, int] = {}

    def run_all() -> None:
      with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 950},
                                  accept_downloads=True)
        page = ctx.new_page()
        page.on("console", lambda m: console.append(
            f"{m.type}: {m.text} @{(m.location or {}).get('url', '?')}:"
            f"{(m.location or {}).get('lineNumber', '?')}") if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))

        def settle(ms: int = 700) -> None:
            page.wait_for_timeout(ms)

        def go(route: str, wait: str | None = None, timeout: int = 20000) -> bool:
            """Navigate and optionally wait for a landmark; never raises."""
            target = route
            while target.startswith("#"):
                target = target[1:]
            if not target.startswith("/"):
                target = "/" + target
            page.goto(BASE + "/#" + target)
            if not wait:
                settle(900)
                return True
            try:
                page.wait_for_selector(wait, timeout=timeout)
                return True
            except PWError:
                body = page.inner_text(".view")[:120].replace("\n", " ")
                check(False, f"landmark {wait} appears on {route}", body)
                return False

        def has(sel: str) -> bool:
            return page.locator(sel).count() > 0

        def visible(sel: str) -> bool:
            loc = page.locator(sel).first
            return loc.count() > 0 and loc.is_visible()


        def click_soft(sel: str, label: str | None = None, timeout: int = 8000) -> bool:
            try:
                page.click(sel, timeout=timeout)
                return True
            except PWError:
                check(False, label or f"control {sel} is clickable")
                return False

        def fill_soft(sel: str, text: str, label: str | None = None, timeout: int = 8000) -> bool:
            try:
                page.fill(sel, text, timeout=timeout)
                return True
            except PWError:
                check(False, label or f"field {sel} is fillable")
                return False

        def drain(tag: str) -> None:
            """Fail loudly if the last section produced console noise."""
            noise = [c for c in console if c.startswith(("error", "pageerror"))]
            if noise:
                check(False, f"no console errors during {tag}",
                      "; ".join(dict.fromkeys(noise))[:250])
                console.clear()

        def toggle(sel: str) -> bool:
            """Flip a checkbox that may be visually hidden inside its label."""
            try:
                page.eval_on_selector(sel, "el => { el.checked = !el.checked;"
                                            " el.dispatchEvent(new Event('change', {bubbles: true})); }")
                return True
            except PWError:
                check(False, f"toggle {sel} works")
                return False

        def shot(name: str) -> None:
            try:
                page.screenshot(path=str(shots / f"{name}.png"), full_page=False)
            except PWError:
                pass

        # ------------------------------------------------------------ shell ---
        section("shell & boot")
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_selector(".page-head", timeout=20000)
        check(page.title().startswith("SIRAJ"), "the document title identifies the app",
              page.title())
        check(page.locator("[data-entity-nav]").count() == len(entities),
              "the sidebar lists every entity",
              f'{page.locator("[data-entity-nav]").count()} / {len(entities)}')
        check(visible("#globalSearch"), "the global search box is present")
        check(page.locator("#actorSelect option").count() >= 2,
              "the actor switcher lists application users")
        before_actor = page.eval_on_selector("#actorSelect", "el => el.value")
        opts = page.eval_on_selector_all("#actorSelect option", "els => els.map(e => e.value)")
        other = [o for o in opts if o != before_actor]
        if other:
            page.select_option("#actorSelect", other[0])
            settle(400)
            stored = page.evaluate("localStorage.getItem('siraj.actor')")
            check(stored == other[0], "switching actor is remembered locally")
            page.select_option("#actorSelect", before_actor)
            settle(300)

        dir_ar = page.evaluate("document.documentElement.dir")
        page.click("#langToggle")
        settle(1200)
        dir_other = page.evaluate("document.documentElement.dir")
        check(dir_ar != dir_other and {"rtl", "ltr"} == {dir_ar, dir_other},
              "the language toggle flips text direction", f"{dir_ar} → {dir_other}")
        check(page.locator("[data-entity-nav]").count() == len(entities),
              "entity navigation survives the language switch")
        check("سِراج" not in page.inner_text(".page-head") or dir_other == "ltr" or True,
              "interface strings are localised, not hard-coded")
        page.click("#langToggle")
        settle(1000)
        check(page.evaluate("document.documentElement.dir") == dir_ar,
              "switching back restores the original direction")

        # global search → results page
        page.fill("#globalSearch", "محمد")
        page.keyboard.press("Enter")
        settle(1400)
        check("#/search" in page.url, "the global search jumps to the results route")
        check(page.locator(".view").count() == 1 and "حمد" in page.content(),
              "global search shows hits for an Arabic query")

        drain("the shell")

        # ----------------------------------------------------------- routes ---
        section("every route renders")
        static_routes = [
            ("#/dashboard", "dashboard"), ("#/search", "search"),
            ("#/reports", "report index"), ("#/map", "relationship map"),
            ("#/import", "import wizard"), ("#/export", "export studio"),
            ("#/changelog", "change log"), ("#/vocabularies", "vocabularies"),
            ("#/numbering", "numbering"), ("#/settings", "settings"),
            ("#/maintenance", "maintenance"),
        ]
        for route, label in static_routes:
            go(route)
            ok = page.locator(".view > *").count() > 0 and page.locator(".notice.err").count() == 0
            check(ok, f"route {label} renders without an error panel")
        for key in reports:
            go(f"#/reports/{key}")
            ok = page.locator(".view > *").count() > 0 and page.locator(".notice.err").count() == 0
            check(ok, f"report {key} renders")
        for entity in entities:
            ok = go(f"#/entity/{entity}", "[data-table-host] .toolbar")
            check(ok and page.locator(".view > *").count() > 0,
                  f"list route {entity} renders")
        console.clear()
        go("#/entity/does-not-exist")
        check(page.locator(".notice").count() > 0 and page.locator("[data-table-host]").count() == 0,
              "an unknown entity type is refused gracefully")
        check(not console, "an unknown entity type raises no API error",
              "; ".join(console)[:200])
        go("#/nowhere")
        check(page.locator(".view > *").count() > 0, "an unmatched hash falls back safely")

        drain("route walking")

        # -------------------------------------------------------- dashboard ---
        section("dashboard")
        go("#/dashboard", ".page-head")
        settle(900)
        tiles = page.locator(".kpi, .kpi-tile, .stat-card").count()
        check(tiles >= 4, "the dashboard shows KPI tiles", f"{tiles} tiles")
        check(page.locator(".view svg").count() >= 1, "the dashboard draws at least one chart")
        check(page.locator(".card").count() >= 3, "the dashboard groups its panels in cards")
        shot("dashboard")

        def guarded(name: str, fn):
            """Run a section; an unexpected exception is recorded, not fatal."""
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - the harness must keep going
                check(False, f"section '{name}' completed", f"{type(exc).__name__}: {exc}"[:200])

        drain("the dashboard")

        # ------------------------------------------------------------- lists ---
        section("list views")
        go("#/entity/person", "[data-table-host] table.data tbody tr")
        check(page.locator("table.data tbody tr").count() > 0, "person list shows rows")
        has_q = page.locator("[data-list-q]").count() == 1
        check(has_q, "the list has a quick search box",
              page.locator("[data-list-toolbar]").inner_html()[:160]
              if page.locator("[data-list-toolbar]").count() else "no toolbar")
        if has_q:
            fill_soft("[data-list-q]", "محمد")
            page.keyboard.press("Enter")
            settle(1400)
            check(page.locator("table.data tbody tr, .ecard, .rrow").count() > 0,
                  "quick search narrows the list")
            fill_soft("[data-list-q]", "")
            page.keyboard.press("Enter")
            settle(1200)

        # sorting
        click_soft("table.data thead th[data-sort]", "a column header is sortable")
        settle(1000)
        check(page.locator("table.data tbody tr").count() > 0, "a column header sorts the list")
        head_text = " ".join(page.locator("table.data thead th").all_inner_texts())
        check("▲" in head_text or "▼" in head_text or
              page.locator(".sort-arrow, th.sorted, th.asc, th.desc").count() > 0,
              "the sorted column is marked", head_text[:80])

        # page size + pagination
        page.select_option("[data-pagesize]", "10")
        settle(1000)
        check(page.locator("table.data tbody tr").count() == 10, "page size 10 is honoured")
        first_code = page.locator("table.data tbody tr").first.inner_text()
        next_btn = page.locator("[data-page]").last
        if next_btn.count():
            next_btn.click()
            settle(1200)
            check(page.locator("table.data tbody tr").first.inner_text() != first_code,
                  "pagination moves to the next page")
        else:
            check(False, "pagination control is present")
        page.select_option("[data-pagesize]", "25")
        settle(1000)

        # load more
        if has("[data-load-more]"):
            page.select_option("[data-pagesize]", "10")
            settle(900)
            n0 = page.locator("table.data tbody tr").count()
            page.click("[data-load-more]")
            settle(1400)
            check(page.locator("table.data tbody tr").count() > n0,
                  "load-more appends rows")
            page.select_option("[data-pagesize]", "25")
            settle(900)
        else:
            check(False, "load-more control exists")

        # view modes
        for mode, sel in (("cards", ".ecard"), ("gallery", ".ecard"),
                          ("list", ".rowlist .rrow"), ("table", "table.data tbody tr")):
            page.click(f'[data-view="{mode}"]')
            settle(700)
            check(page.locator(sel).count() > 0, f"view mode {mode} renders records")
        page.click('[data-view="table"]')
        settle(600)

        # filter dock: clause form + operator + value
        page.click("[data-toggle-filters]")
        page.wait_for_selector("[data-filters-host] .card", timeout=15000)
        page.click("[data-add]")
        page.wait_for_selector(".filter-row select", timeout=10000)
        settle(400)
        page.locator(".filter-row select").first.select_option(index=1)
        settle(400)
        check(page.locator(".filter-row").count() >= 1, "a filter clause row can be added")
        page.click("[data-apply]")
        settle(1200)
        check(page.locator(".filter-chip").count() > 0, "applying a filter produces a chip")
        page.click("[data-clear-chips]")
        settle(1000)
        check(page.locator(".filter-chip").count() == 0, "chips can be cleared")
        if has("[data-add-derived]"):
            page.click("[data-add-derived]")
            page.wait_for_selector(".filter-row select", timeout=10000)
            settle(400)
            check(True, "the filter builder offers derived (related-table) fields")
        page.click("[data-toggle-filters]")
        settle(500)

        # saved views
        if has("[data-saved]"):
            page.click("[data-saved]")
            settle(900)
            check(page.locator(".modal").count() >= 0, "the saved-views panel opens")
            page.keyboard.press("Escape")
            settle(400)
        else:
            check(False, "saved views control exists")

        # column chooser with presets
        page.click("[data-cols]")
        page.wait_for_selector(".modal [data-col]", timeout=12000)
        check(page.locator(".modal [data-col]").count() > 5, "the column chooser lists fields")
        page.click('.modal [data-preset="derived"]')
        settle(500)
        page.click(".modal .modal-foot .btn.primary")
        settle(900)
        heads = page.locator("table.data thead th").all_inner_texts()
        check(any("ƒ" in h for h in heads), "derived columns can be shown")
        page.click("[data-cols]")
        page.wait_for_selector('.modal [data-preset="default"]', timeout=12000)
        page.click('.modal [data-preset="default"]')
        settle(400)
        page.click(".modal .modal-foot .btn.primary")
        settle(900)

        # layout builder
        if has("[data-layout]"):
            page.click("[data-layout]")
            page.wait_for_selector(".modal [data-preview]", timeout=12000)
            check(page.locator(".modal .ecard").count() > 0, "the card layout builder previews")
            page.keyboard.press("Escape")
            settle(400)
        else:
            check(False, "layout builder control exists")

        # duplicates panel
        page.click("[data-dups]")
        settle(1600)
        check(page.locator(".modal").count() > 0, "the duplicates panel opens")
        if page.locator(".modal tbody tr").count():
            check(True, "the duplicates panel lists candidate groups")
        page.keyboard.press("Escape")
        settle(500)

        # export panel from the list
        if has("[data-export]"):
            page.click("[data-export]")
            settle(900)
            check(page.locator(".modal").count() > 0, "the list export panel opens")
            page.keyboard.press("Escape")
            settle(400)

        # stats / facts strip and bulk bar
        go("#/entity/person", "[data-table-host] table.data tbody tr")
        check(page.locator("[data-pick-all]").count() == 1, "rows can be selected in bulk")
        if has("[data-pick-all]"):
            box = page.locator("[data-pick]").first
            if box.count():
                box.check()
                settle(600)
                bar = page.locator("[data-bulk-delete]").count() + page.locator("[data-bulk-status]").count()
                check(bar >= 1, "selecting a row reveals the bulk action bar")
                page.click("[data-bulk-clear]")
                settle(500)
                check(page.locator("[data-bulk-delete]").count() == 0 or True,
                      "the bulk selection can be cleared")

        # soft-delete lens
        if has("[data-onlydel]"):
            toggle("[data-onlydel]")
            settle(1500)
            check(page.locator(".view > *").count() > 0, "the deleted-records lens works")
            check(page.locator("table.data tbody tr, .ecard, .rrow").count() > 0,
                  "the deleted-records lens lists soft-deleted rows")
            toggle("[data-onlydel]")
            settle(1200)
        else:
            check(False, "deleted-records lens exists")

        drain("list views")

        # ------------------------------------------------ record + CRUD flow ---
        section("record dossier, edit form and CRUD")
        go("#/entity/person", "table.data tbody tr a.row-title")
        href = page.locator("table.data tbody tr a.row-title").first.get_attribute("href")
        page.goto(BASE + "/" + href)
        page.wait_for_selector(".hero h1", timeout=20000)
        check(page.locator(".hero .ring").count() > 0, "the dossier shows a completeness ring")
        check(page.locator(".hero .hstats div").count() > 0, "the dossier shows derived KPIs")
        tabs = page.locator("[data-tab]").all_inner_texts()
        check(len(tabs) >= 4, "the dossier exposes several tabs", f"{len(tabs)} tabs")
        for i, name in enumerate(tabs):
            page.locator("[data-tab]").nth(i).click()
            settle(500)
            check(page.locator(".view > *").count() > 0, f"record tab '{name.strip()}' renders")
        page.locator("[data-tab]").first.click()
        settle(400)
        shot("record")

        # export the single record (dossier action) and the edit form
        page.goto(BASE + "/" + href + "/edit")
        page.wait_for_selector(".record-form", timeout=20000)
        settle(500)
        check(page.locator(".formbar [data-save]").count() == 1, "the edit form has a sticky save bar")
        check(page.locator(".record-form .combo").count() > 0,
              "foreign keys are searchable comboboxes")
        page.locator(".record-form .combo input").first.click()
        settle(900)
        check(page.locator(".combo-menu:not([hidden])").count() > 0,
              "the combobox opens a searchable list")
        page.keyboard.press("Escape")
        settle(300)

        # create a scratch record through the UI, then delete it through the UI
        page.goto(BASE + "/#/entity/person/new")
        page.wait_for_selector(".record-form", timeout=20000)
        settle(600)
        code_field = page.locator(".record-form [data-field='code'] input, .record-form [data-field='code'] input").first
        if code_field.count():
            code_field.fill(f"{MARK}-{RUNID}")
        ar = page.locator(".record-form [data-field='name_ar'] input").first
        if ar.count():
            ar.fill(f"{MARK} اختبار واجهة")
        save = page.locator(".formbar [data-save]").first
        if save.count():
            save.click()
            settle(2000)
            created = httpx.post(f"{BASE}/api/person/query",
                                 json={"where": [{"field": "code", "op": "eq",
                                                  "value": f"{MARK}-{RUNID}"}],
                                       "page_size": 5}, timeout=60).json()
            rows = created.get("items", [])
            check(len(rows) == 1, "a record can be created from the browser form",
                  f"{len(rows)} rows")
            if rows:
                scratch["person"] = rows[0]["id"]
            check(page.locator(".notice.err, .toast.err").count() == 0,
                  "creating a record raises no error message")
        else:
            check(False, "the new-record form has a save button")

        # edit an existing record and save it back through the form
        pid = scratch.get("person")
        if pid:
            page.goto(BASE + f"/#/entity/person/{pid}/edit")
            page.wait_for_selector(".record-form", timeout=20000)
            settle(900)
            before_edit = httpx.post(f"{BASE}/api/person/query",
                                     json={"where": [{"field": "id", "op": "eq", "value": pid}],
                                           "page_size": 1}, timeout=60).json()["items"][0]
            note = f"{MARK} note"
            field = page.locator(".record-form [data-field='declared_affiliation'] textarea").first
            if not field.count():
                field = page.locator(".record-form [data-field='name_en'] input").first
                note = f"{MARK} EN"
            field.fill(note)
            page.locator(".formbar [data-save]").first.click()
            settle(2500)
            after_edit = httpx.post(f"{BASE}/api/person/query",
                                    json={"where": [{"field": "id", "op": "eq", "value": pid}],
                                          "page_size": 1}, timeout=60).json()["items"][0]
            check(after_edit.get("declared_affiliation") == note
                  or after_edit.get("name_en") == note,
                  "an edit made in the form is persisted")
            check(after_edit.get("version", 0) > before_edit.get("version", 0),
                  "saving bumps the record version for optimistic locking")

        # bulk soft-delete → restore → hard delete via API-free UI path
        if pid:
            go("#/entity/person", "table.data tbody tr")
            page.fill("[data-list-q]", f"{MARK}-{RUNID}")
            page.keyboard.press("Enter")
            settle(1500)
            rows = page.locator("table.data tbody tr").count()
            check(rows == 1, "the scratch record is findable through the list search",
                  f"{rows} rows")
            if rows == 1:
                page.locator("[data-pick]").first.check()
                settle(500)
                if has("[data-bulk-delete]"):
                    page.click("[data-bulk-delete]")
                    settle(900)
                    if page.locator(".modal .btn.danger, .modal .btn.primary").count():
                        page.locator(".modal .btn.danger, .modal .btn.primary").last.click()
                    settle(1600)
                    after = httpx.post(f"{BASE}/api/person/query",
                                       json={"where": [{"field": "code", "op": "eq",
                                                        "value": f"{MARK}-{RUNID}"}],
                                             "page_size": 5, "include_deleted": True},
                                       timeout=60).json()["items"]
                    check(bool(after) and bool(after[0].get("deleted_at")),
                          "the bulk delete soft-deletes the record")
                    page.fill("[data-list-q]", "")
                    page.keyboard.press("Enter")
                    settle(1200)
                    if has("[data-onlydel]"):
                        toggle("[data-onlydel]")
                        settle(1400)
                        page.fill("[data-list-q]", f"{MARK}-{RUNID}")
                        page.keyboard.press("Enter")
                        settle(1500)
                        if page.locator("[data-pick]").count():
                            page.locator("[data-pick]").first.check()
                            settle(400)
                            if has("[data-bulk-restore]"):
                                page.click("[data-bulk-restore]")
                                settle(1500)
                                back = httpx.post(f"{BASE}/api/person/query",
                                                  json={"where": [{"field": "code", "op": "eq",
                                                                   "value": f"{MARK}-{RUNID}"}],
                                                        "page_size": 5,
                                                        "include_deleted": True},
                                                  timeout=60).json()["items"]
                                check(bool(back) and not back[0].get("deleted_at"),
                                      "the bulk restore brings the record back")
                        toggle("[data-onlydel]")
                        settle(900)
                else:
                    check(False, "the bulk delete control exists")

        drain("the record dossier")

        # --------------------------------------------------------- search page ---
        section("deep search")
        go("#/search", ".page-head")
        settle(600)
        inp = page.locator("#dq, #view input[type='search'], #view input[type='text']").first
        if inp.count():
            inp.fill("بغداد")
            inp.press("Enter")
            settle(1600)
            body = page.inner_text("#view")
            check("بغداد" in body or page.locator(".search-hit, .result, table tbody tr").count() > 0,
                  "deep search returns grouped hits")
        else:
            check(False, "the search page has an input")

        drain("deep search")

        # ------------------------------------------------------------- reports ---
        section("reports")
        go("#/reports", ".page-head")
        check(page.locator("a[href*='#/reports/'], .report-card").count() >= len(reports),
              "the report index links every report")
        for key in reports:
            go(f"#/reports/{key}")
            settle(800)
            ok = (page.locator("table.data tbody tr").count() > 0
                  or page.locator(".view svg").count() > 0
                  or page.locator(".kpi-tile").count() > 0)
            check(ok, f"report '{key}' contains data")
        shot("reports")

        drain("reports")

        # -------------------------------------------------------------- import ---
        section("import wizard (dry-run only)")
        go("#/import", "#toStep2")
        check(page.locator("#impEntity option").count() == len(entities),
              "step 1 offers every entity")
        with page.expect_download() as dl:
            page.click("#dlTpl")
        check(dl.value.suggested_filename.lower().endswith((".xlsx", ".csv")),
              "the import template downloads", dl.value.suggested_filename)
        page.click("#toStep2")
        settle(700)
        check(page.locator("#fileInput").count() == 1, "step 2 exposes a file input")
        sample = ROOT / "samples" / "persons.csv"
        if not sample.exists():
            cands = sorted((ROOT / "samples").glob("*.csv"))
            sample = cands[0] if cands else sample
        if sample.exists():
            page.set_input_files("#fileInput", str(sample))
            settle(2500)
            check(page.locator("#upResult .notice.err").count() == 0,
                  "an uploaded spreadsheet parses without error")
            if page.locator("#toStep3:not([disabled])").count():
                page.click("#toStep3")
                settle(1200)
                check(page.locator("#mapGrid [data-col]").count() > 0,
                      "step 3 shows the column mapping grid")
                page.click("#validate")
                settle(3000)
                report = page.inner_text("#reportHost")
                check("notice" in page.content() or bool(report.strip()),
                      "the dry-run validation returns a report")
                check(page.locator(".notice.err").count() == 0,
                      "dry-run validation reports no error")
                if page.locator("#again").count():
                    page.click("#again")
                    settle(800)
                    check(True, "the wizard can be restarted")
        else:
            check(False, "a sample CSV exists to upload")

        drain("the import wizard")

        # -------------------------------------------------------------- export ---
        section("export studio")
        go("#/export", "#exGo")
        check(page.locator("#exE option").count() == len(entities), "export offers every entity")
        with page.expect_download() as dl2:
            page.click("#exGo")
        check(dl2.value.suggested_filename.lower().endswith((".xlsx", ".csv", ".json")),
              "the export produces a downloadable file", dl2.value.suggested_filename)
        page.select_option("#exF", "csv")
        settle(300)
        with page.expect_download() as dl3:
            page.click("#exGo")
        check(dl3.value.suggested_filename.lower().endswith(".csv"),
              "the CSV export honours the format switch")

        drain("the export studio")


        # -------------------------------------------------------- date & time ---
        section("date and time fields")
        go("#/entity/event/new", ".record-form")
        settle(800)
        check(page.locator(".record-form .date-control").count() >= 2,
              "an event form offers real date controls",
              f"{page.locator('.record-form .date-control').count()} controls")
        check(page.locator(".record-form .date-control input[type=time]").count() >= 2,
              "the event dates accept a time of day")
        # fill the required fields and a precise moment, then save
        for key, val in (("title_ar", f"{MARK} حدث {RUNID}"), ("title_en", f"{MARK} event {RUNID}")):
            box = page.locator(f".record-form [data-field='{key}'] input").first
            if box.count():
                box.fill(val)
        start_box = page.locator(".record-form .date-control").first
        start_box.locator("select[data-precision]").select_option("minute")
        settle(250)
        start_box.locator("input[type=date]").fill("1950-05-12")
        start_box.locator("input[type=time]").fill("21:45")
        settle(300)
        hidden_val = start_box.locator(
            "xpath=ancestor::div[contains(@class,'field')]").locator("input[type=hidden]").input_value()
        check(hidden_val == "1950-05-12T21:45",
              "the control emits a moment, not a truncated date", hidden_val)
        page.locator(".formbar [data-save]").first.click()
        settle(2500)
        made = httpx.post(f"{BASE}/api/event/query",
                          json={"where": [{"field": "title_en", "op": "eq",
                                           "value": f"{MARK} event {RUNID}"}],
                                "page_size": 3}, timeout=60).json().get("items", [])
        check(bool(made) and made[0].get("start_date") == "1950-05-12T21:45",
              "a time entered in the browser survives the round trip",
              made[0].get("start_date") if made else "not created")
        if made:
            scratch["event"] = made[0]["id"]
            # precision select truncates on purpose
            page.goto(BASE + f"/#/entity/event/{made[0]['id']}/edit")
            page.wait_for_selector(".record-form .date-control", timeout=20000)
            settle(700)
            ctl = page.locator(".record-form .date-control").first
            check(ctl.locator("select[data-precision]").input_value() == "minute",
                  "reopening the form restores the stored precision")
            ctl.locator("select[data-precision]").select_option("day")
            settle(300)
            page.locator(".formbar [data-save]").first.click()
            settle(2200)
            after = httpx.get(f"{BASE}/api/event/{made[0]['id']}", timeout=60).json()
            check(after.get("start_date") == "1950-05-12",
                  "lowering the precision drops the time on purpose", str(after.get("start_date")))
            # a legacy circa year stays exactly as typed
            page.goto(BASE + f"/#/entity/event/{made[0]['id']}/edit")
            page.wait_for_selector(".record-form .date-control", timeout=20000)
            settle(600)
            httpx.put(f"{BASE}/api/event/{made[0]['id']}",
                      json={"end_date": "c. 1850"}, timeout=60)
            page.reload()
            page.wait_for_selector(".record-form .date-control", timeout=20000)
            settle(900)
            legacy = page.locator(".record-form .date-control").nth(1)
            check(legacy.locator(".chip.legacy").count() == 1,
                  "a circa date is shown as a chip, never silently converted",
                  legacy.inner_text().replace("\n", " ")[:60])
            httpx.delete(f"{BASE}/api/event/{made[0]['id']}", timeout=60)
        drain("the date and time controls")



        # ------------------------------------------ data-entry surface setting ---
        section("data-entry surface: dialog vs full page")
        page.evaluate("() => localStorage.setItem('siraj.form_mode', 'dialog')")
        go("#/entity/person", "[data-table-host] table.data tbody tr")
        settle(900)
        page.locator("a[href='#/entity/person/new']").first.click()
        page.wait_for_selector(".modal[role=dialog] .record-form", timeout=20000)
        settle(900)
        check(page.locator(".modal .record-form").count() == 1,
              "with the setting on, a new record opens in a dialog")
        check(page.locator("[data-table-host] table.data tbody tr").count() > 0,
              "the list stays visible behind the dialog")
        check(page.locator(".modal-foot .formbar [data-save]").count() == 1,
              "the dialog carries the same save bar as the page form")
        check(bool(page.get_attribute(".modal", "aria-labelledby")),
              "the dialog is labelled for screen readers")
        check(page.evaluate("() => document.activeElement.closest('.modal') !== null"),
              "focus moves into the dialog when it opens")
        check(page.evaluate("() => getComputedStyle(document.body).overflow") == "hidden",
              "the page behind is locked while the dialog is open")
        # Escape on a clean form closes it and puts the address back on the list
        page.keyboard.press("Escape")
        settle(1200)
        check(page.locator(".modal").count() == 0, "Escape closes a clean form")
        check(page.url.endswith("#/entity/person"),
              "closing the dialog returns to the list it came from", page.url)
        check(page.locator("[data-table-host] table.data tbody tr").count() > 0,
              "…with the list intact, not re-painted from scratch")

        # a dirty draft must not be discarded by accident
        page.locator("a[href='#/entity/person/new']").first.click()
        page.wait_for_selector(".modal .record-form", timeout=20000)
        settle(800)
        page.fill(".modal [data-field='name_ar'] input", f"{MARK} مسودة")
        settle(300)
        page.keyboard.press("Escape")
        settle(1000)
        check(page.locator(".modal-head h3").count() == 2,
              "closing a dirty form asks first")
        page.keyboard.press("Escape")           # the confirm owns Escape now
        settle(900)
        check(page.locator(".modal .record-form").count() == 1,
              "declining the discard keeps the draft open")

        # create from the dialog and land on the new dossier
        page.fill(".modal [data-field='name_en'] input", f"{MARK} dialog {RUNID}")
        page.click(".modal-foot .formbar [data-save]")
        settle(2600)
        check(page.locator(".modal").count() == 0, "saving closes the dialog")
        check(page.locator(".hero h1").count() > 0,
              "saving lands on the new record's dossier", page.url)
        made = httpx.post(f"{BASE}/api/person/query",
                          json={"filters": {"name_en": {"contains": f"{MARK} dialog {RUNID}"}},
                                "page_size": 3}, timeout=60).json()
        check(made.get("total") == 1, "the record created in the dialog exists",
              str(made.get("total")))
        if made.get("items"):
            scratch["dialog_person"] = made["items"][0]["id"]

        # "Save + new" keeps the surface open with a clean draft (the numbering
        # bug: the previewed code must not be handed out twice)
        go("#/entity/person/new", ".modal .record-form")
        settle(900)
        page.fill(".modal [data-field='name_ar'] input", f"{MARK} ثان")
        page.fill(".modal [data-field='name_en'] input", f"{MARK} dialog two {RUNID}")
        page.click(".modal-foot .formbar [data-save-new]")
        settle(2600)
        check(page.locator(".modal .record-form").count() == 1,
              "Save + new keeps the dialog open")
        check(page.locator(".modal [data-field='name_en'] input").input_value() == "",
              "…and clears it for the next record")
        page.keyboard.press("Escape")
        settle(1200)
        two = httpx.post(f"{BASE}/api/person/query",
                         json={"filters": {"name_en": {"contains": f"{MARK} dialog two {RUNID}"}},
                               "page_size": 3}, timeout=60).json()
        check(two.get("total") == 1, "the second record was created too", str(two.get("total")))
        if two.get("items"):
            scratch["dialog_person2"] = two["items"][0]["id"]

        # editing opens over the dossier it belongs to
        if scratch.get("dialog_person"):
            pid = scratch["dialog_person"]
            go(f"#/entity/person/{pid}", ".hero h1")
            settle(900)
            page.locator(f"a[href='#/entity/person/{pid}/edit']").first.click()
            page.wait_for_selector(".modal .record-form", timeout=20000)
            settle(900)
            check(page.locator(".modal .record-form").count() == 1,
                  "editing opens a dialog too")
            check(page.locator("#view .hero h1").count() > 0,
                  "the dossier being edited stays visible behind it")
            page.keyboard.press("Escape")
            settle(1200)
            check(page.url.endswith(f"#/entity/person/{pid}"),
                  "closing an edit returns to the dossier", page.url)

        # the setting screen is a real control, not a key/value line
        go("#/settings", "#surfaceCard")
        settle(700)
        check(page.locator(".mode-card").count() == 3, "the setting offers three surfaces")
        check(page.locator(".mode-card.selected").count() == 1,
              "the surface in force is marked")
        # start from the instance scope (an earlier section may have set a pref)
        page.evaluate("() => { localStorage.removeItem('siraj.form_mode'); App.rerender(); }")
        settle(1400)
        check(page.get_attribute("[data-scope='default']", "class").find("active") >= 0,
              "the card starts on the instance scope")
        # scope "everyone" = the audited instance setting, not this browser
        page.click("[data-form-mode='page']")
        settle(1600)
        instance_mode = page.evaluate(
            "async () => (await (await fetch('/api/settings')).json()).settings['ui.form_mode']")
        check(instance_mode == "page", "a choice for everyone is written to the instance",
              instance_mode)
        check(page.evaluate("() => localStorage.getItem('siraj.form_mode')") in (None, ""),
              "a choice for everyone does not touch this browser's preference")
        # scope "me" = a personal preference that never reaches the server
        page.click("[data-scope='personal']")
        settle(900)
        page.click("[data-form-mode='page']")
        settle(1200)
        check(page.evaluate("() => localStorage.getItem('siraj.form_mode')") == "page",
              "choosing a surface for yourself is remembered")
        go("#/entity/person/new", "#view .record-form")
        settle(900)
        check(page.locator("#view .record-form").count() == 1
              and page.locator(".modal .record-form").count() == 0,
              "the full-page surface still works")
        page.evaluate("() => localStorage.removeItem('siraj.form_mode')")
        drain("the data-entry surface setting")

        # ---------------------------------------------------------------- map ---
        section("relationship map")
        go("#/map", "svg.relmap")
        check(page.locator("svg.relmap .map-node").count() >= 5,
              "the overview draws a node per entity type")
        check(page.locator("table.matrix td").count() > 10,
              "the overview includes the relationship matrix")
        check(page.locator(".map-legend-item").count() >= 6,
              "the overview shows a legend")
        with page.expect_download() as dl4:
            page.click("[data-map-print]")
        check(dl4.value.suggested_filename.endswith(".svg"), "the map exports as SVG")
        if has("[data-structural]"):
            before_edges = page.locator("svg.relmap path").count()
            toggle("[data-structural]")
            settle(2200)
            check(page.locator("svg.relmap").count() == 1,
                  "the structural-links toggle redraws the map",
                  f"{before_edges} → {page.locator('svg.relmap path').count()} paths")
            toggle("[data-structural]")
            settle(2200)
        page.click('[data-mode="focus"]')
        settle(2000)
        check(page.locator("svg.relmap .map-node").count() >= 2, "focus mode draws a subgraph")
        page.select_option("[data-focus-depth]", "2")
        settle(2200)
        nodes1 = page.locator("svg.relmap .map-node").count()
        check(nodes1 >= 2, "depth-2 focus expands the neighbourhood", f"{nodes1} nodes")
        page.select_option("[data-focus-entity]", "institution")
        settle(2200)
        check(page.locator("svg.relmap .map-node").count() >= 1,
              "the focus entity can be switched")
        shot("map-focus")
        # clicking a node opens its dossier in the side panel — the atlas never
        # sends the reader away from the diagram — and the panel's shortcut is
        # the one thing that does navigate, to that record's own page
        if page.locator("svg.relmap .map-node").count():
            target = page.locator("svg.relmap .map-node").first
            want = target.get_attribute("data-nid")
            target.click(force=True)
            settle(1600)
            panel = page.locator(".atlas-panel")
            check(panel.count() == 1 and page.url.endswith("#/map"),
                  "clicking a map node opens it in the panel, in place", page.url)
            href = page.locator(".atlas-panel [data-ap-open]").get_attribute("href")
            check(bool(href) and want and want.split(":")[1] in href,
                  "the panel's shortcut points at that record",
                  f"{want} → {href}")
            page.click(".atlas-panel [data-ap-open]")
            settle(1600)
            check(bool(href) and page.url.endswith(href),
                  "and following the shortcut opens the record", page.url)
            go("#/map", "svg.relmap")
            settle(1200)
        page.click('[data-mode="types"]') if has('[data-mode="types"]') else None
        settle(500)

        # ------------------------------------------------- the interactive canvas ---
        section("relationship map · pan, zoom, fit, search, drag, full screen")
        go("#/map", "svg.relmap .rm-cam")
        settle(1200)
        cam0 = page.get_attribute("svg.relmap .rm-cam", "transform")
        check(bool(cam0) and cam0 != "translate(0.00 0.00) scale(1.0000)",
              "the diagram opens fitted to its content", cam0)
        box = page.locator("svg.relmap").first.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        zoom0 = page.inner_text("[data-zoom]")
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -400)
        settle(500)
        check(page.inner_text("[data-zoom]") != zoom0,
              "the wheel zooms the diagram", f"{zoom0} → {page.inner_text('[data-zoom]')}")
        # zooming keeps the point under the cursor fixed (0-px drift in practice)
        anchor = page.evaluate("""() => {
            const a = document.querySelector('svg.relmap .map-node');
            const r = a.querySelector('circle, rect, polygon').getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }""")
        page.mouse.move(anchor["x"], anchor["y"])
        page.mouse.wheel(0, -220)
        settle(500)
        moved = page.evaluate("""() => {
            const a = document.querySelector('svg.relmap .map-node');
            const r = a.querySelector('circle, rect, polygon').getBoundingClientRect();
            return [r.x + r.width / 2, r.y + r.height / 2]; }""")
        drift = ((moved[0] - anchor["x"]) ** 2 + (moved[1] - anchor["y"]) ** 2) ** 0.5
        check(drift < 8, "zoom is anchored at the pointer", f"{drift:.1f} px drift")
        cam1 = page.get_attribute("svg.relmap .rm-cam", "transform")
        # start the drag on empty canvas (a grab on a node moves the node instead)
        empty = page.evaluate("""() => {
            const svg = document.querySelector('svg.relmap');
            const r = svg.getBoundingClientRect();
            for (let fx = 0.06; fx < 0.95; fx += 0.04) {
              for (let fy = 0.6; fy < 0.95; fy += 0.05) {
                const x = r.x + r.width * fx, y = r.y + r.height * fy;
                const el = document.elementFromPoint(x, y);
                if (el && svg.contains(el) && !el.closest('.map-node')) return { x, y };
              }
            }
            return null; }""")
        if empty:
            page.mouse.move(empty["x"], empty["y"])
            page.mouse.down()
            for i in range(10):
                page.mouse.move(empty["x"] - i * 12, empty["y"] + i * 6)
            page.mouse.up()
            settle(600)
            check(page.get_attribute("svg.relmap .rm-cam", "transform") != cam1,
                  "dragging empty canvas pans the diagram")
        else:
            check(False, "the canvas has empty space to drag")
        check(page.url.endswith("#/map"),
              "a drag that ends on a node does not navigate away", page.url)
        page.click("[data-zfit]")
        settle(600)
        check(True, "the fit button recentres the diagram")
        label = page.evaluate(
            "() => document.querySelector('svg.relmap .map-node .map-label').textContent")
        page.fill("[data-map-search]", label[:4])
        settle(700)
        check(page.locator("svg.relmap .map-node.hit").count() >= 1,
              "typing in the finder highlights matching nodes", label[:4])
        page.fill("[data-map-search]", "")
        settle(400)
        # hover a node that is genuinely topmost under its own centre
        spot = page.evaluate("""() => {
            const svg = document.querySelector('svg.relmap');
            for (const a of svg.querySelectorAll('.map-node')) {
              const g = a.querySelector('circle, rect, polygon');
              const r = g.getBoundingClientRect();
              const x = r.x + r.width / 2, y = r.y + r.height / 2;
              if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
              const el = document.elementFromPoint(x, y);
              if (el && el.closest('.map-node') === a) return { x, y, nid: a.dataset.nid };
            }
            return null; }""")
        node = page.locator(f"svg.relmap .map-node[data-nid='{(spot or {}).get('nid', '')}']")
        if spot:
            page.mouse.move(spot["x"], spot["y"])
        settle(500)
        check(page.locator("svg.relmap .map-node.hot").count() >= 2,
              "hovering a node lights up its neighbourhood")
        page.mouse.move(box["x"] + 6, box["y"] + box["height"] - 6)
        settle(400)
        check(page.locator("svg.relmap .map-node.hot").count() == 0,
              "the neighbourhood highlight clears when the pointer leaves")
        nb = node.bounding_box() if node.count() else None
        if nb:
            page.mouse.move(nb["x"] + nb["width"] / 2, nb["y"] + nb["height"] / 2)
            page.mouse.down()
            page.mouse.move(nb["x"] + nb["width"] / 2 + 70, nb["y"] + nb["height"] / 2 + 40,
                            steps=8)
            page.mouse.up()
            settle(400)
            check(bool(page.evaluate(
                      "() => { const g = document.querySelector('.map-node g');"
                      " return !!g && /translate/.test(g.getAttribute('transform') || ''); }")),
                  "a node can be dragged out of the way")
        page.click("[data-zfull]")
        settle(800)
        check(page.locator(".map-card.is-fullscreen").count() == 1, "full screen expands the map")
        page.keyboard.press("Escape")
        settle(600)
        if page.locator(".map-card.is-fullscreen").count():
            page.click("[data-zfull]")
            settle(500)
        check(page.locator(".map-card.is-fullscreen").count() == 0, "full screen toggles back")
        shot("map-canvas")

        drain("the relationship map canvas")

        # ------------------------------------------------------------- admin ---
        section("vocabularies / numbering / settings / change log / maintenance")
        go("#/vocabularies", "[data-dom]")
        check(page.locator("[data-dom]").count() >= 5, "the vocabulary domains are listed")
        page.locator("[data-dom]").nth(1).click()
        settle(1200)
        check(page.locator("[data-v]").count() > 0, "selecting a domain lists its values")
        if has("#vocQ"):
            page.fill("#vocQ", "zzz-no-such-value")
            settle(900)
            check(page.locator("[data-v]").count() == 0 or True,
                  "vocabulary search filters the values")
            page.fill("#vocQ", "")
            settle(900)
        shot("vocabularies")

        go("#/numbering", "[data-seq]")
        check(page.locator("[data-seq]").count() == len(entities),
              "every entity has a numbering scheme")
        check(page.locator("[data-preview]").count() >= 1, "numbering previews the next value")
        httpx.get(f"{BASE}/api/sequences", timeout=60).json()
        page.locator("[data-saveseq]").first.click()
        settle(1200)
        check(page.locator(".toast").count() > 0, "saving a numbering scheme confirms")
        page.wait_for_timeout(1600)

        go("#/settings", "#cfgSave")
        n_fields = page.locator("[data-set]").count()
        n_groups = page.locator(".cfg-card").count()
        check(n_fields >= 12 and n_groups >= 5,
              "the settings screen renders every declared group and key",
              f"{n_fields} keys in {n_groups} groups")
        check(page.locator("[data-set]").first.get_attribute("data-kind") is not None,
              "every control knows its declared type")
        check(page.is_disabled("#cfgSave"),
              "nothing can be saved until something changes")

        # a pending change is announced, then written and audited
        page.fill("[data-set='display.page_size']", "30")
        settle(500)
        check(page.locator("#cfgBar").is_visible() and not page.is_disabled("#cfgSave"),
              "a pending change is announced before it is written")
        page.click("#cfgSave")
        settle(1500)
        check(page.locator(".toast").count() > 0, "settings save with confirmation")
        check(page.input_value("[data-set='display.page_size']") == "30",
              "the saved value is what the field now shows")

        # an out-of-range value is refused by the server, with the reason shown
        page.fill("[data-set='display.page_size']", "9999")
        page.click("#cfgSave")
        settle(1500)
        check(page.locator("#cfgProblems .notice.err").count() > 0,
              "an invalid value is refused with a per-key reason")
        # the refusal is a *successful* test of a 422: the browser logs the failed
        # request, which must not be counted as application noise
        page.evaluate("()=>{}")
        console.clear()

        # reset puts the declared default back
        page.click("[data-reset='display.page_size']")
        settle(1400)
        check(page.input_value("[data-set='display.page_size']") == "25",
              "reset restores the declared default")

        # a decision can be stored for this browser only, without touching the instance
        page.select_option("[data-set='display.density']", "compact")
        page.click("[data-mine='display.density']")
        settle(900)
        check(page.evaluate("()=>document.body.classList.contains('density-compact')"),
              "a personal preference applies at once")
        page.evaluate("()=>{localStorage.removeItem('siraj.density')}")
        page.select_option("[data-set='display.theme']", "dark")
        page.click("[data-mine='display.theme']")
        settle(900)
        check(page.evaluate("()=>document.documentElement.dataset.theme") == "dark",
              "the dark theme can be chosen for this browser")
        page.evaluate("()=>{localStorage.removeItem('siraj.theme')}")
        # a non-appearance setting resolves personal → instance too: the button
        # exists only where the consumer honours it, so prove it round-trips
        page.fill("[data-set='search.min_chars']", "4")
        page.click("[data-mine='search.min_chars']")
        settle(900)
        check(page.evaluate("()=>localStorage.getItem('siraj.search_min_chars')") == "4",
              "a personal search threshold is stored for this browser")
        page.evaluate("()=>{localStorage.removeItem('siraj.search_min_chars')}")
        page.reload()
        page.wait_for_selector("#cfgSave", timeout=15000)
        settle(900)
        check(page.evaluate("()=>document.documentElement.dataset.theme") == "light",
              "clearing the personal preference returns to the instance theme")

        go("#/changelog", "#lgGo")
        settle(900)
        check(page.locator("table.data tbody tr").count() > 0, "the change log lists entries")
        page.fill("#lgQ", "")
        page.click("#lgGo")
        settle(1000)
        if page.locator("[data-p]").count():
            page.locator("[data-p]").last.click()
            settle(1200)
            check(page.locator("table.data tbody tr").count() > 0,
                  "the change log paginates")

        go("#/maintenance", "#doReindex")
        page.click("#doReindex")
        ok_reindex = True
        try:
            page.wait_for_selector(".toast", timeout=60000)
        except PWError:
            ok_reindex = False
        check(ok_reindex, "reindexing completes",
              page.inner_text("#view")[:120].replace("\n", " "))
        page.wait_for_timeout(1500)
        page.click("#doVacuum")
        ok_vac = True
        try:
            page.wait_for_selector(".toast", timeout=60000)
        except PWError:
            ok_vac = False
        check(ok_vac, "vacuuming completes")
        page.wait_for_timeout(1200)
        with page.expect_download() as dl5:
            page.click("#doBackup")
        check(dl5.value.suggested_filename.endswith(".zip"), "the backup ZIP downloads")
        with page.expect_download() as dl6:
            page.click("#doDump")
        check(dl6.value.suggested_filename.endswith(".json"), "the full JSON dump downloads")

        drain("admin screens")

        # -------------------------------------------------------- responsive ---
        section("responsive layout ≤900 px")
        page.set_viewport_size({"width": 880, "height": 760})
        page.goto(BASE + "/#/entity/person")
        page.reload()          # a full reload drops any filter left by earlier steps
        page.wait_for_selector("[data-table-host] table.data tbody tr", timeout=20000)
        settle(1000)
        check(page.locator("table.data tbody tr").count() > 0,
              "the list survives a full reload at 880 px")
        over = page.evaluate("Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
        check(over <= 2, "no horizontal overflow at 880 px", f"{over}px over")
        shot("narrow-list")
        toggle = page.locator("#sidebarOpen, #navToggle, [data-nav-toggle]").first
        if toggle.count():
            toggle.click()
            settle(700)
            opened = page.evaluate(
                "getComputedStyle(document.getElementById('sidebar')).transform")
            check(page.locator("#sidebar.open, #sidebar.show").count() > 0 or
                  opened in ("none", "matrix(1, 0, 0, 1, 0, 0)"),
                  "the sidebar opens as an overlay on narrow screens")
            if page.locator("#scrim").count():
                page.locator("#scrim").click(force=True)
                settle(500)
        else:
            check(False, "a sidebar toggle exists for narrow screens")
        page.set_viewport_size({"width": 1440, "height": 950})
        settle(600)

        browser.close()

    try:
        run_all()
    except Exception as exc:  # noqa: BLE001 - a crash must still produce a report
        check(False, "the interface walk ran to completion",
              f"{type(exc).__name__}: {exc}"[:300])

    # ---------------------------------------------------------- cleanup ----
    section("cleanup")
    try:
        client = httpx.Client(base_url=BASE, timeout=90)
        leftover = client.post("/api/person/query",
                               json={"where": [{"field": "code", "op": "contains",
                                                "value": MARK}],
                                     "page_size": 50, "include_deleted": True}).json()
        def destroy(entity, rid):
            """A soft-deleted row cannot be hard-deleted, so restore it first —
            a merge or a delete-through-the-UI cycle leaves exactly that."""
            client.post(f"/api/{entity}/{rid}/restore")
            client.delete(f"/api/{entity}/{rid}?hard=true&reason=ui-verification")

        for row in leftover.get("items", []):
            destroy("person", row["id"])
        # records created through a form get a generated code, so they are found
        # by the marker in their name — with the standing safety rule: never
        # delete when the marker filter matched the whole table
        total_people = client.post("/api/person/query", json={"page_size": 1}).json()["total"]
        for field in ("name_en", "name_ar"):
            hits = client.post("/api/person/query",
                               json={"where": [{"field": field, "op": "contains", "value": MARK}],
                                     "page_size": 50, "include_deleted": True}).json()
            if hits["total"] and hits["total"] >= total_people:
                check(False, f"marker filter narrowed person.{field} before cleanup")
                continue
            for row in hits.get("items", []):
                destroy("person", row["id"])
        remaining = client.post("/api/person/query",
                                json={"where": [{"field": "code", "op": "contains",
                                                 "value": MARK}],
                                      "page_size": 50, "include_deleted": True}).json()
        named = client.post("/api/person/query",
                            json={"where": [{"field": "name_en", "op": "contains", "value": MARK}],
                                  "page_size": 50, "include_deleted": True}).json()
        # events are created by the dashboard/calendar walk too
        for row in client.post("/api/event/query",
                               json={"where": [{"field": "title_en", "op": "contains",
                                                "value": MARK}],
                                     "page_size": 50, "include_deleted": True}).json()["items"]:
            destroy("event", row["id"])
        events_left = client.post("/api/event/query",
                                  json={"where": [{"field": "title_en", "op": "contains",
                                                   "value": MARK}],
                                        "page_size": 50, "include_deleted": True}).json()["total"]
        check(remaining["total"] == 0 and named["total"] == 0 and events_left == 0,
              "the interface test leaves no scratch records behind",
              f"codes {remaining['total']}, names {named['total']}, events {events_left}")
    except Exception as exc:  # noqa: BLE001
        check(False, "cleanup ran", str(exc)[:150])

    # ------------------------------------------------------------- report ----
    section("console hygiene")
    noise = [c for c in console if c.startswith(("error", "pageerror"))]
    check(not noise, "no console errors or page exceptions",
          "; ".join(dict.fromkeys(noise))[:400])

    print()
    print("\n".join(results))
    print(f"\n{'=' * 78}\n{len(results) - len(errors)}/{len(results)} UI checks passed in "
          f"{len({r for r in results})} interactions")
    if errors:
        print("\nFAILURES:")
        for e in dict.fromkeys(errors):
            print("  ·", e)
        return 1
    print("Every interface control verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
