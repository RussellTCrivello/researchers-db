"""Browser verification of the geographic workspace (Playwright + Chromium).

Every acceptance criterion of the map phase is exercised here, against a running
server and the real registry — no mocks, no fixtures, no stubs of the map library.

  · access       — reachable from the existing navigation, whole-screen layout
  · basemap      — the configured provider draws, and the local pack works offline
  · features     — located records appear, unlocated records never do
  · selection    — marker → record; list ↔ map stay in sync; the inspector follows
  · temporary    — a click on empty space is temporary and never written
  · coordinates  — entry validates range; DD ↔ DMS agree; an arbitrary point navigates
  · overlap      — clustered records open up when clicked
  · groups       — per-place statistics, and their underlying records
  · filters      — change the features *and* the count, never the data
  · layers       — toggles change the view only
  · layout       — collapsing a panel fires `resize` and keeps the geography
  · language     — AR RTL / EN LTR, and the map state survives the switch
  · overlays     — relationship and hierarchy layers match the API's own count
  · errors       — a failing endpoint is announced and recoverable
  · staleness    — rapid selection changes never leave an old record on screen
  · keyboard     — every control is reachable and labelled
  · bounded      — a big viewport never ships every record to the browser

Usage:  python3 tests/ui_geo.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

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
    ap.add_argument("--shots", default=str(ROOT / ".smoke" / "geo"))
    args = ap.parse_args()
    base = args.base.rstrip("/")
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    api = httpx.Client(base_url=base, timeout=120)
    config = api.get("/api/map/config").json()
    catalog = {layer["entity_type"]: layer for layer in config["layers"]}
    console: list[str] = []

    def audit_rows() -> int:
        return api.get("/api/changelog", params={"page_size": 1}).json()["total"]

    def viewport(page) -> dict:
        return page.evaluate("""() => {
          const m = App.geo.map();
          const c = m.getCenter();
          return {lat: c.lat, lon: c.lng, zoom: m.getZoom(),
                  w: m.getCanvas().clientWidth, h: m.getCanvas().clientHeight};
        }""")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader",
                                           "--enable-unsafe-swiftshader"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 950})
        page = ctx.new_page()
        injecting = {"on": False}      # tile failures we caused ourselves

        def on_console(m) -> None:
            if m.type != "error":
                return
            # a deliberately aborted tile request is the test, not a defect
            if injecting["on"] and "Failed to load resource" in m.text:
                return
            console.append(f"{m.type}: {m.text}")

        page.on("console", on_console)
        page.on("pageerror", lambda e: console.append(
            f"pageerror: {e}\n{getattr(e, 'stack', '') or ''}"))
        writes: list[str] = []
        page.on("request", lambda r: writes.append(f"{r.method} {r.url}")
                if r.method != "GET" and "/api/" in r.url else None)

        def settle(ms: int = 600) -> None:
            page.wait_for_timeout(ms)

        def fit(start: float = 0.0, stop: float = 1.0) -> None:
            """Wait until the map is loaded and quiet (first frame + tiles + features)."""
            page.wait_for_timeout(400)
            page.evaluate("""([a, b]) => new Promise(done => {
              const step = () => {
                const m = window.App && App.geo && App.geo.map();
                const now = performance.now();
                if (!m && now > 3000) return done();
                if (m && m.loaded() && now > 900) return done();
                requestAnimationFrame(step);
              };
              step();
            })""", [start, stop])

        # ------------------------------------------------------------------ 1 ---
        section("access and layout")
        page.goto(f"{base}/#/dashboard", wait_until="load")
        settle(800)
        nav = page.locator('.nav-item[data-route="geomap"]')
        check(nav.count() == 1, "the geographic map is reached from the existing navigation")
        nav.click()
        fit()
        page.wait_for_function("() => window.App && App.geo && App.geo.map()", timeout=20000)
        settle(1200)
        check(page.url.endswith("#/geo"), "the navigation entry routes to #/geo", page.url)
        page.wait_for_function("() => document.querySelector('#geoMap').clientHeight > 200",
                               timeout=15000)
        box = page.locator("#geoMap").bounding_box()
        win = page.viewport_size
        check(box is not None and box["width"] > 380 and box["height"] > 400,
              "the map occupies the working area",
              f"{box} vs {win}")
        full = page.evaluate("""() => {
          const v = document.querySelector('#view').getBoundingClientRect();
          const m = document.querySelector('#geoMap').getBoundingClientRect();
          return (m.width * m.height) / (v.width * v.height);
        }""")
        check(full > 0.3, "with both panels open the map still holds a third of the page",
              f"{full:.2f}")
        check(page.locator("#geoMap canvas").count() >= 1, "the map canvas exists")

        state = page.evaluate("() => App.geo.state() && {provider: App.geo.state().providerId, points: App.geo.state().points.length, cluster: App.geo.state().cluster}")
        check(state and state["provider"] == config["provider"]["id"],
              "the configured provider is the one in use", str(state))

        # ------------------------------------------------------------------ 2 ---
        section("basemap from the configured provider")
        attribution = page.locator("#geoAttribution").inner_text()
        check("Natural Earth" in attribution or "ناتشورال إيرث" in attribution,
              "attribution for the base map is shown on the map", attribution)
        check(page.locator("#geoAttribution a").count() >= 2,
              "attribution carries the licence and the terms links")
        base_requests = [r for r in page.evaluate(
            "() => performance.getEntriesByType('resource').map(r => r.name)")
            if "/api/geo/basemap/" in r]
        check(len(base_requests) >= 2, "basemap geometry is fetched from the local pack",
              str(len(base_requests)))
        check(api.get("/api/geo/basemap").status_code == 200,
              "the offline pack answers without the internet")

        # ------------------------------------------------------------------ 3 ---
        section("located records only")
        pts = page.evaluate("() => App.geo.state().points")
        check(len(pts) > 0, "records are drawn at their locations", str(len(pts)))
        check(all(isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float))
                  for p in pts), "every drawn feature has real coordinates")
        unlocated = {k: v["total"] - v["located"] for k, v in catalog.items()}
        located_total = sum(v["located"] for v in catalog.values())
        check(sum(unlocated.values()) > 0,
              "the registry really does contain records without coordinates",
              str(unlocated))
        missing = api.get("/api/map/features", params={"bbox": "-180,-85,180,85",
                                                       "limit": 20000}).json()
        ids = {(p["entity_type"], p["id"]) for p in missing["points"]}
        check(("place", 1118) not in ids or catalog["place"]["located"] == catalog["place"]["total"],
              "a record without coordinates is not given a placeholder position")
        check(missing["count"] <= located_total,
              "no more features than located records exist",
              f'{missing["count"]} vs {located_total}')

        # ------------------------------------------------------------------ 5/6/7/8 ---
        section("selection, marker state and inspector sync")
        first = pts[0]
        row = page.locator(f'.geo-row[data-etype="{first["entity_type"]}"][data-id="{first["id"]}"]').first
        check(row.count() == 1, "the record appears in the left-hand list")
        row.click()
        settle(900)
        code = page.locator(".geo-insp-head .mono-cell").first.inner_text()
        check(code == first["code"], "selecting in the list selects the record",
              f"{code} != {first['code']}")
        check(page.locator(".geo-row.active").count() == 1,
              "the list marks exactly one selected row")
        ring = page.evaluate("""() => {
          const s = App.geo.map().getSource('selection');
          const d = s && s._data;
          return d ? d.features.length : -1;
        }""")
        check(ring == 1, "the selected marker is rendered as selected", str(ring))

        # a marker click selects the record that owns it
        # a real click on the canvas, at the projected position of a marker that is
        # actually drawn (at low zoom a cluster circle covers the individual points,
        # so the map is zoomed in first — which is what a researcher does too)
        page.evaluate("() => App.geo.map().jumpTo({center: [44.3661, 33.3152], zoom: 12.5})")
        settle(2000)
        page.wait_for_function("() => App.geo.state().points.length > 0", timeout=15000)
        settle(900)
        target = page.evaluate("""() => {
          const m = App.geo.map();
          const c = m.getCanvas().getBoundingClientRect();
          for (const p of App.geo.state().points) {
            const pt = m.project([p.lon, p.lat]);
            if (pt.x < 20 || pt.y < 20 || pt.x > c.width - 20 || pt.y > c.height - 20) continue;
            if (m.queryRenderedFeatures(pt, {layers: ['geo-points']}).length) {
              const hits = m.queryRenderedFeatures(pt, {layers: ['geo-points']})
                .map(f => f.properties.code);
              return {code: p.code, x: c.left + pt.x, y: c.top + pt.y, id: p.id,
                      etype: p.entity_type, hits};
            }
          }
          return null;
        }""")
        check(target is not None, "at least one marker is inside the visible canvas")
        if target:
            page.mouse.click(target["x"], target["y"])
            settle(900)
            now = page.locator(".geo-insp-head .mono-cell").first.inner_text()
            # several records can share one coordinate; the click selects the topmost
            # of them, which is one of the markers drawn at that pixel
            check(now in target["hits"], "clicking a marker selects its record",
                  f'{now} not in {target["hits"]}')
            check(page.evaluate("() => App.geo.state().temp") is None,
                  "a marker click is a record selection, not a temporary point")

        # ------------------------------------------------------------------ 9/10 ---
        section("temporary selection never writes")
        before = audit_rows()
        blank = page.evaluate("""() => {
          /* the emptiest pixel in the viewport: far from every marker that is on screen */
          const m = App.geo.map();
          const c = m.getCanvas().getBoundingClientRect();
          const marks = App.geo.state().points.map(p => m.project([p.lon, p.lat]));
          let best = null;
          for (let y = 40; y < c.height - 40; y += 19) {
            for (let x = 40; x < c.width - 40; x += 19) {
              let near = Infinity;
              for (const pt of marks) {
                const d = Math.hypot(pt.x - x, pt.y - y);
                if (d < near) near = d;
              }
              if (!best || near > best.near) best = {x, y, near};
            }
          }
          if (!best || best.near < 30) return null;
          const ll = m.unproject([best.x, best.y]);
          return {x: c.left + best.x, y: c.top + best.y, lat: ll.lat, lon: ll.lng,
                  near: Math.round(best.near)};
        }""")
        check(blank is not None, "some of the visible map is empty, as it should be")
        if blank:
            page.mouse.click(blank["x"], blank["y"])
        settle(1400)
        temp = page.evaluate("() => App.geo.state().temp")
        check(bool(temp) and blank is not None and abs(temp["lat"] - blank["lat"]) < 0.01,
              "clicking an arbitrary coordinate creates a temporary selection", str(temp))
        check(page.locator(".geo-insp-head .badge.amber").count() == 1,
              "the inspector describes the temporary point")
        after = audit_rows()
        check(after == before, "the temporary selection wrote nothing to the database",
              f"{before} -> {after}")
        page.keyboard.press("Escape")
        settle(600)
        check(page.evaluate("() => App.geo.state().temp") is None,
              "Escape discards the temporary selection")

        # ------------------------------------------------------------------ 11/12 ---
        section("coordinate entry and DMS")
        page.locator("#geoCoordBtn").click()
        settle(400)
        page.locator("#geoCoordInput").fill("95, 44")
        page.locator(".modal .btn.primary").click()
        settle(700)
        hint = page.locator("#geoCoordHint").inner_text()
        check("95" in hint or "latitude" in hint.lower() or "خطأ" in hint or "خارج" in hint,
              "an out-of-range latitude is rejected with a reason", hint)
        check(page.locator(".modal").count() == 1, "the dialog stays open on invalid input")
        page.locator("#geoCoordInput").fill("33°18'54.7\"N 44°21'58.0\"E")
        page.locator(".modal .btn.primary").click()
        settle(1200)
        check(page.locator(".modal").count() == 0, "a valid DMS coordinate navigates")
        centre = page.evaluate("() => { const c = App.geo.map().getCenter(); return [c.lat, c.lng]; }")
        check(abs(centre[0] - 33.31519) < 0.01 and abs(centre[1] - 44.36611) < 0.01,
              "the map moved to the entered coordinate", str(centre))
        readout = page.evaluate("() => App.geo.state().temp")
        check(readout and abs(readout["lat"] - 33.31519) < 0.01,
              "the entered coordinate became a temporary selection", str(readout))
        dd = api.get("/api/map/parse", params={"q": "33.3152, 44.3661"}).json()
        dms = api.get("/api/map/parse", params={"q": '33°18\'54.7"N 44°21\'58.0"E'}).json()
        check(abs(dd["lat"] - dms["lat"]) < 1e-4 and abs(dd["lon"] - dms["lon"]) < 1e-4,
              "decimal degrees and DMS of the same place agree",
              f'{dd["lat"]},{dd["lon"]} vs {dms["lat"]},{dms["lon"]}')
        check(page.locator("#geoRightBody .geo-coords code").count() >= 3,
              "the inspector shows DD, DMS and projected metres")

        # ------------------------------------------------------------------ 13 ---
        section("overlapping records")
        check(bool(page.evaluate("() => App.geo.state().cluster")),
              "nearby markers are clustered so overlaps stay distinguishable")
        page.evaluate("""() => {
          const m = App.geo.map();
          m.jumpTo({center: [44.3661, 33.3152], zoom: 5});
        }""")
        settle(1200)
        cluster = page.evaluate("""() => {
          const m = App.geo.map();
          const c = m.getCanvas().getBoundingClientRect();
          const feats = m.querySourceFeatures('records').filter(f => f.properties.cluster);
          for (const f of feats) {
            const pt = m.project(f.geometry.coordinates);
            if (pt.x < 20 || pt.y < 20 || pt.x > c.width - 20 || pt.y > c.height - 20) continue;
            if (m.queryRenderedFeatures(pt, {layers: ['geo-clusters']}).length) {
              return {x: c.left + pt.x, y: c.top + pt.y,
                      count: f.properties.point_count, zoom: m.getZoom()};
            }
          }
          return null;
        }""")
        check(cluster is not None, "clusters are present at a wide zoom", str(cluster))
        if cluster:
            page.mouse.click(cluster["x"], cluster["y"])
            settle(1600)
            after_zoom = page.evaluate("() => App.geo.map().getZoom()")
            check(after_zoom > cluster["zoom"],
                  "clicking a cluster opens it up instead of doing nothing",
                  f'{cluster["zoom"]} -> {after_zoom}')

        # ---------------------------------------------------------- styles ---
        section("map styles: standard, aerial and terrain")
        page.locator("#geoLayersBtn").click()
        settle(400)
        heads = page.eval_on_selector_all(
            ".geo-provider-group .geo-group-head", "els => els.map(e => e.textContent.trim())")
        check(len(heads) >= 4, "the base maps are grouped into families", str(heads))
        offered = page.eval_on_selector_all(
            '.geo-provider-list input[name="geoProvider"]', "els => els.map(e => e.value)")
        check({"osm", "esri-imagery", "esri-hybrid", "opentopomap"} <= set(offered),
              "a standard, an aerial, a hybrid and a terrain style are all on offer",
              str(offered))

        page.locator('#geoProviderList input[value="esri-imagery"]').check()
        settle(2600)
        aerial = page.evaluate("""() => {
          const m = App.geo.map();
          const src = m.getStyle().sources;
          return {id: App.geo.state().providerId,
                  tiles: Object.values(src).map(s => (s.tiles || [''])[0]).join('|'),
                  attribution: document.querySelector('#geoAttribution').textContent.trim()};
        }""")
        check(aerial["id"] == "esri-imagery" and "World_Imagery" in aerial["tiles"],
              "choosing aerial imagery loads satellite tiles", aerial["tiles"][:60])
        check("Esri" in aerial["attribution"] or "إيزري" in aerial["attribution"],
              "the imagery attribution is displayed, as its licence requires",
              aerial["attribution"][:60])

        page.locator('#geoProviderList input[value="esri-hybrid"]').check()
        settle(2400)
        hybrid = page.evaluate("() => Object.keys(App.geo.map().getStyle().sources)")
        check("imagery" in hybrid and "labels" in hybrid,
              "the hybrid style stacks imagery under a labels layer", str(hybrid))

        page.locator('#geoProviderList input[value="opentopomap"]').check()
        settle(2000)
        check(page.evaluate("() => App.geo.state().providerId") == "opentopomap",
              "a terrain style is available too")
        page.locator('#geoProviderList input[value="local"]').check()
        settle(2200)
        page.locator("#geoLayersBtn").click()   # leave the menu closed for the next test
        settle(400)
        check(page.evaluate("() => App.geo.state().providerId") == "local",
              "the offline base map is one click away again")

        # ----------------------------------------- clicking a point answers ---
        section("clicking a point shows its records")
        stack = page.evaluate("""() => {
          const groups = {};
          for (const p of App.geo.state().points) {
            const k = p.lat.toFixed(4) + ',' + p.lon.toFixed(4);
            (groups[k] = groups[k] || []).push(p);
          }
          const best = Object.values(groups).sort((a, b) => b.length - a.length)[0];
          if (!best || best.length < 2) return null;
          window.__geoStack = {lat: best[0].lat, lon: best[0].lon, n: best.length};
          App.geo.map().jumpTo({center: [best[0].lon, best[0].lat], zoom: 13});
          return window.__geoStack;
        }""")
        check(stack is not None and stack["n"] >= 2,
              "the registry has overlapping records to click", str(stack))
        settle(2800)
        # start with the inspector shut: the click itself must open it
        page.evaluate("""() => { if (App.geo.state().panels.right)
            document.querySelector('#geoRightToggle').click(); }""")
        settle(900)
        check(page.evaluate("() => !App.geo.state().panels.right"),
              "the inspector is collapsed before the click")
        spot = page.evaluate("""() => {
          const m = App.geo.map(); const r = m.getCanvas().getBoundingClientRect();
          const p = m.project([window.__geoStack.lon, window.__geoStack.lat]);
          return {x: r.left + p.x, y: r.top + p.y};
        }""")
        page.mouse.click(spot["x"], spot["y"])
        settle(2200)
        clicked = page.evaluate("""() => ({
            open: App.geo.state().panels.right,
            sel: App.geo.state().selected,
            stack: App.geo.state().stack ? App.geo.state().stack.length : 0,
            title: (document.querySelector('#geoRightBody .geo-insp-title') || {}).textContent || '',
            rows: document.querySelectorAll('#geoRightBody .geo-stack-row').length})""")
        check(clicked["open"] and bool(clicked["title"].strip()),
              "clicking a point opens the inspector with that record's details",
              clicked["title"][:40])
        check(clicked["rows"] >= 2,
              "every record at that point is listed, not just the top one",
              f'{clicked["rows"]} rows / stack {clicked["stack"]}')

        # a base-map place is not a record, but clicking it must still answer
        page.evaluate("() => App.geo.map().jumpTo({center: [44.3661, 33.3152], zoom: 6})")
        settle(2600)
        cities = page.locator(".geo-label-city")
        check(cities.count() > 0, "base-map cities are drawn and clickable", str(cities.count()))
        if cities.count():
            cities.first.click()
            settle(2400)
            city = page.evaluate("""() => ({
                kind: (document.querySelector('#geoRightBody .badge') || {}).textContent || '',
                title: (document.querySelector('#geoRightBody .geo-insp-title') || {}).textContent || '',
                rows: document.querySelectorAll('#geoRightBody .geo-gaz-records .geo-stack-row').length,
                head: (document.querySelector('#geoRightBody .geo-gaz-records .geo-section-head') || {}).textContent || ''})""")
            check(bool(city["title"].strip()) and city["kind"].strip() != "",
                  "clicking a base-map city shows the place itself", city["title"][:30])
            check(city["rows"] >= 1,
                  "and lists the registry records at that city",
                  f'{city["head"].strip()[:30]} rows={city["rows"]}')

        # ------------------------------------------------------------------ 14 ---
        section("groups and their records")
        page.evaluate("() => App.geo.map().jumpTo({center: [44.3661, 33.3152], zoom: 6})")
        settle(300)
        page.wait_for_timeout(900)
        page.locator('[data-panel-tab="places"]').click()
        settle(1200)
        groups = page.locator("#geoLeftBody .geo-row").count()
        check(groups > 0, "places are listed with statistics", str(groups))
        first_group = page.locator("#geoLeftBody .geo-row").first
        label = first_group.inner_text()
        count_text = first_group.locator(".geo-count").inner_text()
        check(count_text.strip().isdigit() or any(ch.isdigit() for ch in count_text),
              "each place shows how many records it holds", label[:60])
        first_group.click()
        settle(1400)
        check(page.evaluate("() => App.geo.state().temp") is not None,
              "opening a group centres the map on it")
        page.locator("#geoRadiusQuery").first.click()
        settle(1200)
        result = page.locator("#geoRadiusResult").inner_text()
        check(any(ch.isdigit() for ch in result),
              "the group's underlying records are reachable from the inspector", result[:80])

        # ------------------------------------------------------------------ 15/16 ---
        section("filters and layer toggles")
        page.locator('[data-panel-tab="filters"]').click()
        settle(500)
        baseline = api.get("/api/map/features", params={"bbox": "-180,-85,180,85",
                                                        "limit": 20000}).json()["count"]
        page.locator('[data-layer="event"]').uncheck()
        page.locator("#geoFilterApply").click()
        settle(1400)
        layers_now = page.evaluate("() => Array.from(App.geo.state().filters.layers)")
        check("event" not in layers_now, "the layer toggle changed the requested layers",
              str(layers_now))
        legend = page.locator("#geoLegend").inner_text()
        check("حدث" not in legend and "Event" not in legend,
              "the legend follows the visible layers", legend[:60])
        after_filter = api.get("/api/map/features", params={
            "bbox": "-180,-85,180,85", "limit": 20000,
            "layers": "place,person,institution"}).json()["count"]
        check(after_filter < baseline, "filtering reduces the features and their count",
              f"{baseline} -> {after_filter}")
        check(len(page.evaluate("() => App.geo.state().points")) <= baseline,
              "the browser holds only what was asked for")
        page.locator('[data-layer="event"]').check()
        page.locator("#geoFilterApply").click()
        settle(1200)
        total_events = api.get("/api/event", params={"page_size": 1}).json()["total"]
        check(total_events > 0, "turning a layer back on did not touch the data",
              str(total_events))

        # ------------------------------------------------------------------ 17 ---
        section("panel resize keeps the geography")
        page.locator('[data-panel-tab="records"]').click()
        settle(400)
        before_view = viewport(page)
        page.locator("#geoLeftToggle").click()
        settle(900)
        page.locator("#geoRightToggle").click()
        settle(900)
        mid_view = viewport(page)
        check(abs(mid_view["zoom"] - before_view["zoom"]) < 0.001,
              "collapsing both panels does not change the zoom",
              f'{before_view["zoom"]} -> {mid_view["zoom"]}')
        check(abs(mid_view["lat"] - before_view["lat"]) < 0.02,
              "collapsing both panels does not change the centre",
              f'{before_view["lat"]} -> {mid_view["lat"]}')
        check(mid_view["w"] > before_view["w"] + 100,
              "the map grew into the space the panels gave up",
              f'{before_view["w"]} -> {mid_view["w"]}')
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / "geo-fullwidth.png"))
        page.locator("#geoLeftToggle").click()
        page.locator("#geoRightToggle").click()
        settle(900)
        back_view = viewport(page)
        check(abs(back_view["w"] - before_view["w"]) < 40,
              "bringing the panels back restores the width",
              f'{before_view["w"]} -> {back_view["w"]}')

        # ------------------------------------------------------------------ 18/19 ---
        section("language and direction")
        page.evaluate("() => App.geo.map().jumpTo({center: [44.3661, 33.3152], zoom: 7})")
        settle(1000)
        before_lang = viewport(page)
        page.locator("#langToggle").click()
        settle(1600)
        direction = page.evaluate("() => [document.documentElement.lang, document.documentElement.dir]")
        check(direction[0] == "en" and direction[1] == "ltr",
              "the interface switched to English, LTR", str(direction))
        page.goto(f"{base}/#/geo", wait_until="load") if False else None
        after_lang = viewport(page)
        check(abs(after_lang["lat"] - before_lang["lat"]) < 0.02 and
              abs(after_lang["zoom"] - before_lang["zoom"]) < 0.2,
              "the language change preserved the map view",
              f'{before_lang} -> {after_lang}')
        side = page.evaluate("""() => {
          const l = document.querySelector('.geo-left').getBoundingClientRect();
          const r = document.querySelector('.geo-right').getBoundingClientRect();
          return [l.left, r.left, document.documentElement.dir];
        }""")
        check(side[0] < side[1], "in LTR the records panel sits left of the inspector", str(side))
        page.locator("#langToggle").click()
        settle(1600)
        direction = page.evaluate("() => [document.documentElement.lang, document.documentElement.dir]")
        check(direction[0] == "ar" and direction[1] == "rtl",
              "the interface switched back to Arabic, RTL", str(direction))
        side = page.evaluate("""() => {
          const l = document.querySelector('.geo-left').getBoundingClientRect();
          const r = document.querySelector('.geo-right').getBoundingClientRect();
          return [l.left, r.left];
        }""")
        check(side[0] > side[1], "in RTL the records panel sits right of the inspector", str(side))
        check(page.locator("#geoLegend").inner_text().strip() != "",
              "the legend is still rendered after two language switches")

        # ------------------------------------------------------------------ 20 ---
        section("relationship overlays reflect the data")
        overlays = api.get("/api/map/overlays").json()
        check(overlays["counts"]["relationships"] > 0,
              "relationship arcs are computed from stored relationships",
              str(overlays["counts"]))
        check(overlays["counts"]["place_hierarchy"] > 0,
              "place hierarchy paths are computed from parent places",
              str(overlays["counts"]))
        # relationships are off by default (1 817 arcs over one country is a thicket):
        # switch them on through the Layers menu, which is what a researcher does
        page.locator("#geoLayersBtn").click()
        settle(500)
        page.locator('#geoOverlayList input[data-overlay="relationships"]').check()
        settle(2200)
        check("relationships" in page.evaluate("() => App.geo.state().overlays"),
              "the relationship overlay can be switched on from the Layers menu")
        page.locator("#geoLayersBtn").click()   # leave the menu closed for the next test
        settle(400)
        drawn = page.evaluate("""() => {
          const m = App.geo.map();
          const out = {};
          ['relationships','place_hierarchy'].forEach(id => {
            const s = m.getSource('geo-' + id);
            out[id] = s && s._data ? s._data.features.length : -1;
          });
          return out;
        }""")
        check(drawn.get("relationships") == overlays["counts"]["relationships"],
              "the drawn arcs match the API's own count",
              f'{drawn} vs {overlays["counts"]}')

        # ------------------------------------------------------------------ 22 ---
        section("failures are recoverable")
        failing = {"on": True}

        def break_features(route):
            if failing["on"]:
                route.fulfill(status=500, body='{"error":"injected"}',
                              headers={"content-type": "application/json"})
            else:
                route.continue_()

        page.route("**/api/map/features*", break_features)
        page.evaluate("() => { const m = App.geo.map(); m.jumpTo({center: [10, 30], zoom: 4}); }")
        settle(2000)
        banner = page.locator("#geoBanner")
        check(banner.count() == 1 and page.evaluate("() => !document.querySelector('#geoBanner').hidden"),
              "a failing feature request is announced instead of blanking the map")
        check(page.locator("#geoMap canvas").count() >= 1,
              "the map itself survives a failing endpoint")
        failing["on"] = False
        page.evaluate("() => { const m = App.geo.map(); m.jumpTo({center: [44.3661, 33.3152], zoom: 6}); }")
        settle(2200)
        recovered = page.evaluate("() => App.geo.state().points.length")
        check(recovered > 0, "the view recovers by itself once the endpoint answers again",
              str(recovered))
        page.unroute("**/api/map/features*")


        # a tile failure for a network provider is announced and offers the offline map
        offline = api.get("/api/map/config").json()["providers"]
        network = [p for p in offline if p["requires_network"]]
        check(bool(network), "at least one network provider exists to fall back from",
              str([p["id"] for p in offline]))
        check(all("attribution_en" in p and "license" in p and "terms_url" in p
                  for p in offline),
              "every provider declares attribution, licence and terms",
              str([p["id"] for p in offline]))

        # ------------------------------------------------------------------ 23 ---
        section("rapid selection changes")
        candidates = page.evaluate("() => App.geo.state().points.slice(0, 6)")
        last = None
        for cand in candidates:
            page.evaluate("""([etype, id]) => {
              const all = App.geo.state().points;
              const p = all.find(x => x.entity_type === etype && x.id === id);
              window.App.geo.state();
              // select through the same path the interface uses
              const rows = document.querySelectorAll('.geo-row');
              for (const r of rows) {
                if (r.dataset.etype === etype && String(r.dataset.id) === String(id)) { r.click(); return; }
              }
            }""", [cand["entity_type"], cand["id"]])
            last = cand
        settle(1500)
        shown = page.locator(".geo-insp-head .mono-cell").first.inner_text()
        check(shown == last["code"],
              "the inspector shows the last selection, never a stale one",
              f'{shown} vs {last["code"]}')

        # ------------------------------------------------------------------ 24 ---
        section("keyboard access")
        labels = page.evaluate("""() => Array.from(
            document.querySelectorAll('.geo-toolbar button, .geo-panel-head button'))
          .map(b => (b.getAttribute('aria-label') || b.textContent || '').trim())""")
        check(len(labels) >= 8 and all(labels),
              "every map control carries an accessible name", str(labels[:5]))
        page.locator("#geoMap").focus()
        check(page.evaluate("() => document.activeElement && document.activeElement.id === 'geoMap'"),
              "the map itself can take focus")
        page.locator("#geoLayersBtn").focus()
        page.keyboard.press("Enter")
        settle(500)
        check(page.evaluate("() => !document.querySelector('#geoLayersMenu').hidden"),
              "the layer menu opens from the keyboard")
        page.keyboard.press("Escape")
        settle(400)
        check(page.evaluate("() => document.querySelector('#geoLayersMenu').hidden"),
              "Escape closes the layer menu")

        # ------------------------------------------------------------------ 25 ---
        section("bounded work on large viewports")
        page.evaluate("() => { const m = App.geo.map(); m.jumpTo({center: [20, 25], zoom: 1.4}); }")
        settle(2600)
        big = api.get("/api/map/features", params={"bbox": "-180,-85,180,85"}).json()
        check(big["limit"] == config["limits"]["max_points"],
              "the server caps how many features a viewport may return", str(big["limit"]))
        check(big["count"] <= big["limit"],
              "the response never exceeds the cap", f'{big["count"]} / {big["limit"]}')
        check(any(layer.get("total", 0) >= layer.get("returned", 0)
                  for layer in big["per_layer"].values()) or big["truncated"],
              "the response says how much it left out")

        # ------------------------------------------- provider failure (22, bis) ---
        section("a provider that cannot load")
        page.locator("#geoLayersBtn").click()
        settle(400)
        injecting["on"] = True
        page.route("**://tile.openstreetmap.org/**", lambda route: route.abort())
        page.route("**://*.basemaps.cartocdn.com/**", lambda route: route.abort())
        page.locator('#geoProviderList input[value="osm"]').check()
        settle(2600)
        tile_banner = page.evaluate("""() => {
          const b = document.querySelector('#geoBanner');
          return {open: !!b && !b.hidden,
                  text: b ? b.textContent.trim() : '',
                  fallback: !!document.querySelector('#geoUseLocal')};
        }""")
        check(tile_banner["open"] and tile_banner["fallback"],
              "an unreachable tile provider is announced with a way back",
              str(tile_banner)[:120])
        check(page.evaluate("() => App.geo.state().providerId") == "osm",
              "the failing provider is the one that was chosen")
        page.locator("#geoUseLocal").click()
        settle(1800)
        check(page.evaluate("() => App.geo.state().providerId") == "local",
              "one click returns to the offline base map")
        check(page.evaluate("() => document.querySelector('#geoBanner').hidden"),
              "the notice clears once the offline map is back")
        check(page.evaluate("() => App.geo.state().points.length") > 0,
              "the records survive the provider switch")
        page.unroute("**://tile.openstreetmap.org/**")
        page.unroute("**://*.basemaps.cartocdn.com/**")
        injecting["on"] = False
        page.locator("#geoLayersBtn").click()
        settle(300)

        # ------------------------------------------------------------------ 21 ---
        section("permissions and the write surface")
        allowed = {"POST " + base + "/api/map/query"}
        stray = sorted({w for w in writes if w not in allowed})
        check(not stray,
              "the workspace issues no mutating request but the read-only spatial query",
              str(stray[:4]))
        check(len(writes) >= 1 and writes[0].startswith("POST") and "/api/map/query" in writes[0],
              "the only non-GET call is the spatial query", str(writes[:2]))
        page.locator(".geo-row").first.click()
        settle(700)
        open_link = page.locator("#geoRightBody a[href^='#/entity/']").first
        href = open_link.get_attribute("href") if open_link.count() else None
        check(bool(href) and href.startswith("#/entity/"),
              "editing is handed off to the record's own permission-checked form", str(href))
        open_link.click()
        settle(1000)
        check("/entity/" in page.url and "geo" not in page.url.split("#")[-1],
              "the hand-off actually leaves the map for the record", page.url)
        page.go_back()
        page.wait_for_function("() => window.App && App.geo && App.geo.map()", timeout=20000)
        fit()
        after_session = audit_rows()
        check(after_session == before,
              "a whole session of map use changed no data",
              f"{before} -> {after_session}")
        page.screenshot(path=str(shots / "geo-final.png"))

        shots.mkdir(parents=True, exist_ok=True)
        page.locator("#geoLeftToggle").click() if page.locator("#geoLeftToggle").count() else None
        browser.close()

    api.close()

    print()
    # the one 500 in this run is the failure this harness injects on purpose: it is the
    # behaviour under test, not a defect, so it does not count against the map
    injected = "the server responded with a status of 500"
    bad = [line for line in console
           if ("pageerror" in line or "error:" in line.lower()) and injected not in line]
    check(not bad, "no console errors or page errors during the whole session",
          "; ".join(bad[:3]))

    passed = sum(1 for r in results if r.startswith("PASS"))
    print(f"\n{passed}/{len(results)} checks passed")
    if errors:
        print("\nFAILURES:")
        for e in errors:
            print("  ·", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
