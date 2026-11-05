#!/usr/bin/env python3
"""The typed query: a filter a person can read, paste and send to a colleague.

Proves, in a browser and against a live server:

  · the query bar compiles a string into the same rows the filter builder returns
  · the address bar carries the query, so a view can be shared and restored
  · the interface shows how the query was read, and says what it could not honour
  · the current filters can be written back out as a query (both directions)
  · a bad or unknown field never silently returns the whole table

    python3 tests/query_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from playwright.sync_api import sync_playwright

RESULTS: list[str] = []
ERRORS: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> bool:
    line = f"{'PASS' if cond else 'FAIL'} · {label}" + (f"   [{detail}]" if detail else "")
    print(line)
    RESULTS.append(line)
    if not cond:
        ERRORS.append(label + (f" — {detail}" if detail else ""))
    return bool(cond)


def section(name: str) -> None:
    print(f"\n=== {name} " + "=" * max(4, 66 - len(name)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default=".smoke/query")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    api = httpx.Client(base_url=base, timeout=120)
    console: list[str] = []

    def total(kind: str, body: dict) -> int:
        return api.post(f"/api/{kind}/query", json=body).json()["total"]

    published = next(v["id"] for v in
                     api.get("/api/lookups?domain=record_status").json()
                     if v["code"] == "published")
    everyone = total("person", {"page_size": 1})
    published_total = total("person", {"status_ids": [published], "page_size": 1})
    print(f"people: {everyone} · published: {published_total}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader",
                                           "--enable-unsafe-swiftshader"])
        page = browser.new_context(viewport={"width": 1500, "height": 950}).new_page()
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))

        section("the query bar is a filter you can read")
        page.goto(f"{base}/#/entity/person", wait_until="load")
        page.wait_for_timeout(2600)
        check(page.locator("[data-query]").count() == 1,
              "the list offers a query bar beside the search box")
        page.click("[data-query]")
        page.keyboard.type("status:published", delay=20)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        rows = page.inner_text("[data-list-footer]")
        check(f"{published_total:,}".replace(",", "") in rows.replace(",", "")
              or str(published_total) in rows.replace(",", ""),
              "the query narrows the list to the same rows the builder returns",
              rows.split("\n")[0][:60])
        echo = page.locator("[data-query-echo]").inner_text()
        check("status:published" in echo, "the interface shows how it read the query",
              echo.replace("\n", " ")[:80])
        page.screenshot(path=str(shots / "query-applied.png"))

        section("the view is a place you can send someone")
        check("q=status%3Apublished" in page.evaluate("() => location.hash"),
              "the address bar carries the query", page.evaluate("() => location.hash"))
        page.goto(f"{base}/#/entity/person?q={quote('status:published')}",
                  wait_until="load")
        page.wait_for_timeout(2600)
        check(page.eval_on_selector("[data-query]", "e => e.value") == "status:published",
              "opening that address restores the same view")
        restored = page.inner_text("[data-list-footer]").replace(",", "")
        check(str(published_total) in restored,
              "and the same rows, not the whole table", restored.split("\n")[0][:60])

        section("a query that cannot be honoured says so")
        page.click("[data-query]")
        page.keyboard.press("Control+a")
        page.keyboard.type("nonsense:1", delay=20)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2200)
        note = page.locator("[data-query-echo]").inner_text()
        check("nonsense" in note and ("ignored" in note or "unknown" in note),
              "an unknown field is reported in the interface", note.replace("\n", " ")[:90])
        rows_after = page.inner_text("[data-list-footer]").replace(",", "")
        check(str(everyone) in rows_after,
              "and it is dropped rather than silently filtering everything out",
              rows_after.split("\n")[0][:60])

        section("the filters can be written back out as a query")
        page.click("[data-query-clear]")
        page.wait_for_timeout(1800)
        page.fill("[data-list-q]", "الحسيني")
        page.wait_for_timeout(1600)
        page.click("[data-query-copy]")
        page.wait_for_timeout(2200)
        copied = page.eval_on_selector("[data-query]", "e => e.value")
        check("الحسيني" in copied, "the current filters became a query string", copied)
        check("q=" in page.evaluate("() => location.hash"),
              "and the address bar followed", page.evaluate("() => location.hash")[:60])
        page.screenshot(path=str(shots / "query-roundtrip.png"))

        section("the same query through the API")
        parsed = api.post("/api/query/parse", json={
            "entity": "person", "query": "status:published birth:1900..1950"}).json()
        check(parsed["payload"].get("status_ids") == [published],
              "the parser resolves a status code to its vocabulary id",
              str(parsed["payload"].get("status_ids")))
        rendered = api.post("/api/query/render", json={
            "entity": "person", "payload": {"status_ids": [published]}}).json()
        check("status:published" in rendered["query"],
              "and the renderer writes the code back, not the id", rendered["query"])
        via_text = api.post("/api/person/query", json={
            "query": "status:published", "page_size": 1}).json()
        check(via_text["total"] == published_total and via_text["_query"]["echo"],
              "the list endpoint accepts the query string directly",
              f'{via_text["total"]} rows')

        browser.close()
    api.close()
    bad = [c for c in console if "error" in c.lower()]
    check(not bad, "no console errors during the whole session", "; ".join(bad[:3]))

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
