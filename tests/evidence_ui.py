#!/usr/bin/env python3
"""Evidence and the relationship diagram, exercised in a real browser.

What this proves — the parts of the research-architecture blueprint that are
visual rather than merely stored:

  · a record's evidence is shown as claims, not as a bibliography: what the
    source says, where in it, how it bears on the claim, how reliable the source
    is, and how well the claim itself is verified (two separate assessments)
  · a contradiction is displayed beside the support and the record is flagged
    contested — never silently resolved
  · evidence can be added from the interface, and withdrawn without touching the
    source record
  · the relationship diagram encodes verification in the line (solid / long dash
    / dotted), draws an arrow only for a directed relationship, fades a
    relationship that has ended, and opens the relationship's own record with
    its evidence when an edge is clicked or focused and pressed with Enter

Run against a live server:

    python3 tests/evidence_ui.py [--base http://127.0.0.1:8000] [--shots DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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


def cleanup(api: httpx.Client, pid: int, created: list[int]) -> None:
    """Withdraw anything this run attached, whether it passed or crashed."""
    for eid in created:
        try:
            api.delete(f"/api/citations/{eid}")
        except Exception:                              # noqa: BLE001
            pass
    try:
        left = api.get("/api/evidence", params={"entity_type": "person",
                                                "entity_id": pid}).json()
        for row in left.get("evidence", []):
            if (row.get("supported_claim") or "").startswith("Harness claim") or \
                    (row.get("reviewer") == "harness"):
                api.delete(f"/api/citations/{row['id']}")
    except Exception:                                  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default=".smoke/evidence")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    api = httpx.Client(base_url=base, timeout=120)
    console: list[str] = []

    def source_with_evidence() -> int:
        rows = api.get("/api/source", params={"page_size": 50}).json()["items"]
        return rows[0]["id"]

    src = source_with_evidence()
    # a person that starts with exactly one supporting claim and nothing else
    person = None
    for item in api.get("/api/person", params={"page_size": 30}).json()["items"]:
        doc = api.get("/api/evidence", params={"entity_type": "person",
                                               "entity_id": item["id"]}).json()
        if doc["count"] == 1 and doc["counts"]["supports"] == 1:
            person = item
            break
    if person is None:
        person = api.get("/api/person", params={"page_size": 1}).json()["items"][0]
    pid = person["id"]
    print(f"using person #{pid} ({person.get('code')}) and source #{src}")

    created: list[int] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader",
                                           "--enable-unsafe-swiftshader"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 950})
        page = ctx.new_page()
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))

        def settle(ms: int = 700) -> None:
            page.wait_for_timeout(ms)

        # ------------------------------------------------ the evidence card ---
        section("a record's evidence, as claims")
        page.goto(f"{base}/#/entity/person/{pid}", wait_until="load")
        settle(2200)
        page.locator('[data-tab="citations"]').click()
        settle(900)
        check(page.locator(".ev-card").count() >= 1,
              "the record shows its evidence as cards",
              str(page.locator(".ev-card").count()))
        first = page.locator(".ev-card").first
        check(first.locator(".ev-badge").count() == 1,
              "each card states how the source bears on the claim",
              first.locator(".ev-badge").first.inner_text().strip())
        meta = page.eval_on_selector_all(".ev-card .ev-meta > span",
                                         "els => els.map(e => e.textContent.trim())")
        check(any("reliab" in m.lower() or "موثوق" in m for m in meta),
              "the source's reliability is shown", str(meta[:4]))
        check(any("verif" in m.lower() or "تحقق" in m for m in meta),
              "the claim's own verification is shown beside it", str(meta[:6]))
        check(page.locator(".ev-card .ev-meta-none, .ev-card .ev-meta-v").count() >= 1,
              "an unassessed claim says so, rather than looking like a silent omission")
        check(page.locator(".ev-card .ev-title").count() >= 1,
              "the source is one click away, not just a code")
        page.screenshot(path=str(shots / "evidence-record.png"))

        # ---------------------------------------------- a contradiction ---
        section("contradictory evidence stays visible")
        before = api.get("/api/evidence", params={"entity_type": "person",
                                                  "entity_id": pid}).json()
        r = api.post("/api/evidence", json={
            "source_id": src, "entity_type": "person", "entity_id": pid,
            "supported_claim": "A second source dates this differently.",
            "support_type": "contradicts", "page_or_timestamp": "f. 12v",
            "verification": "single_source", "reviewer": "harness"})
        check(r.status_code == 200, "a contradiction can be recorded", str(r.status_code))
        if r.json().get("evidence_id"):
            created.append(r.json()["evidence_id"])
        page.reload(wait_until="load")
        settle(2000)
        page.locator('[data-tab="citations"]').click()
        settle(900)
        kinds = page.eval_on_selector_all(".ev-card", "els => els.map(e => e.className)")
        check(any("ev-contradicts" in k for k in kinds),
              "the contradiction is drawn distinctly", str(kinds[:3]))
        check(page.locator(".ev-card").first.get_attribute("class").find("contradicts") >= 0,
              "and it comes first, because disagreement matters most")
        check(page.locator(".notice.warn").count() >= 1,
              "the record is flagged as contested, not silently resolved")
        check(page.locator(".ev-card").count() == before["count"] + 1,
              "the supporting claim was kept alongside it",
              f'{before["count"]} → {page.locator(".ev-card").count()}')
        page.screenshot(path=str(shots / "evidence-contested.png"))

        # -------------------------------------------- adding from the UI ---
        section("linking a source from the interface")
        page.locator("#addCite").click()
        settle(900)
        check(page.locator(".modal").count() == 1, "the evidence dialog opens")
        if page.locator(".modal").count():
            dialog = page.locator(".modal")
            check(dialog.locator("#evClaim").count() == 1 and
                  dialog.locator("#evSupport").count() == 1 and
                  dialog.locator("#evVerif").count() == 1,
                  "it asks for the claim, its support type and its verification")
            options = page.eval_on_selector("#evSupport",
                                            "e => Array.from(e.options).map(o => o.value)")
            check(options == ["supports", "contradicts", "contextualizes"],
                  "the support types come from the controlled list", str(options))
            # choose the source through the combobox the same way a person would
            dialog.locator("#evSrcHost input").fill("")
            dialog.locator("#evSrcHost input").type("a", delay=40)
            settle(1600)
            opts = dialog.locator("#evSrcHost .combo-row")
            check(opts.count() >= 1, "the source field searches the source registry",
                  str(opts.count()))
            if opts.count():
                opts.first.click()
                dialog.locator("#evClaim").fill("Harness claim: the record is supported here.")
                dialog.locator("#evPage").fill("p. 7")
                dialog.locator("#evSupport").select_option("contextualizes")
                dialog.locator(".modal-foot button.primary").click()
                settle(1500)
                doc = api.get("/api/evidence", params={"entity_type": "person",
                                                       "entity_id": pid}).json()
                check(doc["counts"]["contextualizes"] >= 1,
                      "the link is stored with the chosen support type",
                      str(doc["counts"]))
                added = [e["id"] for e in doc["evidence"] if e["support_type"] == "contextualizes"]
                created.extend(added)
                check(any((e.get("supported_claim") or "").startswith("Harness claim")
                          for e in doc["evidence"]),
                      "the claim text is kept, not just the source id")
            else:
                check(False, "the source could be chosen from the dialog")
                page.keyboard.press("Escape")

        # ------------------------------------------- the diagram grammar ---
        section("the relationship diagram's visual grammar")
        page.goto(f"{base}/#/map", wait_until="load")
        settle(2200)
        page.locator('[data-mode="focus"]').click()
        settle(2400)
        check(page.locator(".rm-edge").count() > 0,
              "the record-centred diagram draws relationship edges",
              str(page.locator(".rm-edge").count()))

        # verification → line style, and direction → arrowhead
        dashes = page.eval_on_selector_all(".rm-edge-line",
                                           "els => els.map(e => e.getAttribute('stroke-dasharray'))")
        marks = page.eval_on_selector_all(".rm-edge-line",
                                          "els => els.map(e => e.getAttribute('marker-end'))")
        check(len([d for d in dashes if d]) >= 1,
              "verification is encoded in the line style",
              str(sorted({str(d) for d in dashes})))
        check(any(m for m in marks),
              "a directed relationship gets an arrowhead", str(sorted({str(m) for m in marks})))

        # Ask the API which record actually has an ended relationship, then open
        # the diagram on it through the deep link — the same path a record page
        # uses, which must not fall back to "whichever record sorts first".
        ended_id = None
        for cand in api.get("/api/person", params={"page_size": 12}).json()["items"]:
            doc = api.get("/api/relationship-map", params={"params": json.dumps(
                {"mode": "focus", "entity_type": "person",
                 "record_id": cand["id"], "depth": 1})}).json()
            if any(e.get("ended") for e in doc.get("edges", [])):
                ended_id = cand["id"]
                break
        if ended_id:
            page.goto(f"{base}/#/map?focus=person:{ended_id}", wait_until="load")
            settle(3000)
            check(page.eval_on_selector('[data-focus-record]', "e => e.value") == str(ended_id),
                  "a record page opens the diagram on that record",
                  f'asked {ended_id}, showing ' +
                  page.eval_on_selector('[data-focus-record]', "e => e.value"))
            opac = page.eval_on_selector_all(".rm-edge-line",
                                             "els => els.map(e => e.getAttribute('stroke-opacity'))")
            check(any(float(o) < 0.4 for o in opac),
                  "a relationship that has ended is drawn faded",
                  f"record {ended_id} · {sorted(set(opac))}")
            check(len(set(opac)) > 1,
                  "and an open one is not: the faded state is per edge, not global",
                  str(sorted(set(opac))))
        else:
            check(False, "a record with an ended relationship was available to check")

        # ---------------------------------- reaching any record ---
        section("the diagram addresses the same records as the registry")
        page.goto(f"{base}/#/map?focus=person:{pid}", wait_until="load")
        settle(2600)
        top = {str(r["id"]) for r in api.post("/api/person/query", json={
            "page_size": 60,
            "sort": {"key": "relationships_count", "dir": "desc"}}).json()["items"]}
        shown = page.eval_on_selector('[data-focus-record]', "e => e.value")
        check(shown == str(pid),
              "a record page opens the diagram on exactly that record",
              f"asked {pid}, picker {shown}" +
              ("" if str(pid) in top else " (not in the default list, added on request)"))
        # search for someone who is certainly not the record on screen
        other = None
        for item in api.get("/api/person", params={"page_size": 40}).json()["items"]:
            if item["id"] != pid and (item.get("name_en") or ""):
                other = item
                break
        page.fill("[data-focus-search]", other["name_en"])
        settle(2000)
        check(page.locator(".focus-hit").count() >= 1,
              "typing in the diagram finds a record",
              f'{other["name_en"]} -> {page.locator(".focus-hit").count()} hit(s)')
        hit_id = page.locator(".focus-hit").first.get_attribute("data-id")
        page.locator(".focus-hit").first.click()
        settle(2600)
        chosen = page.eval_on_selector('[data-focus-record]', "e => e.value")
        check(chosen == hit_id,
              "and choosing it redraws the diagram around that record",
              f'hit {hit_id} -> picker {chosen}')

        # ------------------------------------------ clicking an edge ---
        section("an edge opens its own record and evidence")
        # an edge may sit under a node or outside the fitted view, so take the
        # first one that actually occupies space on screen
        # Prefer an edge whose relationship carries evidence, so the panel's list is
        # proven with a non-empty one rather than 0-vs-0.  A perfectly vertical or
        # horizontal edge has a zero-width (or zero-height) box, which a driver will
        # not click; a person clicks the 14px hit stroke, so click its midpoint.
        with_ev = []
        for rel_id in page.eval_on_selector_all(".rm-edge",
                                               "els => els.map(e => e.dataset.edge)"):
            if api.get(f"/api/relationship/{rel_id}/evidence").json().get("evidence"):
                with_ev.append(str(rel_id))
        points = page.evaluate(
            "() => Array.from(document.querySelectorAll('.rm-edge')).map(g => {"
            " const l = g.querySelector('.rm-edge-line');"
            " const b = l.getBoundingClientRect();"
            " const svg = l.ownerSVGElement.getBoundingClientRect();"
            " const x = b.x + b.width / 2, y = b.y + b.height / 2;"
            " const inside = x > svg.x + 2 && x < svg.right - 2 &&"
            "                y > svg.y + 2 && y < svg.bottom - 2;"
            " return {id: g.dataset.edge, x, y, len: Math.max(b.width, b.height), inside}; })")
        order = ([p for p in points if p["id"] in with_ev] +
                 [p for p in points if p["id"] not in with_ev])
        usable = [p for p in order if p["len"] > 8 and p["inside"]]
        check(bool(usable), "an edge is drawn where it can be clicked",
              f"{len(usable)} of {len(points)} edge(s) on screen")

        # the atlas answers in its side panel: the reader stays on the diagram
        opened = None
        for point in usable:
            page.mouse.click(point["x"], point["y"])
            settle(1200)
            if page.locator(".atlas-panel .ap-type").count():
                opened = point
                break
            settle(200)
        check(opened is not None, "clicking an edge opens the relationship, in place",
              str(opened))
        panel = page.locator(".atlas-panel")
        check(panel.count() == 1 and page.locator(".modal").count() == 0
              and "#/map" in page.url,
              "and it opens as a panel, not a dialog over the diagram", page.url)
        if panel.count():
            body = panel.inner_text()
            check(panel.locator(".ap-facts dt").count() >= 3,
                  "it shows direction, dates and verification",
                  str(panel.locator(".ap-facts dt").count()))
            check(bool(body.strip()), "the panel has content")
            rel_link = panel.locator("a[href^='#/entity/relationship/']")
            check(rel_link.count() == 1,
                  "with a shortcut into the full record",
                  rel_link.first.get_attribute("href") or "")
            # the evidence shown must match the API's own count for that edge
            href = rel_link.first.get_attribute("href") or ""
            rel_id = href.rsplit("/", 1)[-1]
            expected = api.get(f"/api/relationship/{rel_id}/evidence").json()["evidence"]
            cards = page.locator(".atlas-panel .ev-card").count()
            check(expected and cards == len(expected),
                  "and the evidence for that relationship, exactly as stored",
                  f"{cards} cards vs {len(expected)} stored")
            page.screenshot(path=str(shots / "edge-record.png"))
            page.keyboard.press("Escape")
            settle(500)

        if opened is not None:
            idx = page.evaluate(
                "(id) => Array.from(document.querySelectorAll('.rm-edge'))"
                ".findIndex(g => g.dataset.edge === String(id))", opened["id"])
        else:
            idx = 0
        page.keyboard.press("Escape")
        settle(400)
        page.locator(".rm-edge").nth(idx).focus()
        page.keyboard.press("Enter")
        settle(1500)
        check(page.locator(".atlas-panel .ap-type").count() == 1,
              "an edge opens from the keyboard", f"edge #{idx}")
        page.keyboard.press("Escape")

        # ------------------------------------------------------- cleanup ---
        section("cleanup")
        cleanup(api, pid, created)
        after = api.get("/api/evidence", params={"entity_type": "person", "entity_id": pid}).json()
        check(after["count"] == 1,
              "the harness left the record as it found it", str(after["count"]))
        check(not after["disputed"], "and un-contested")

        browser.close()
    api.close()

    bad = [c for c in console if "error" in c.lower()]
    check(not bad, "no console errors or page errors during the whole session",
          "; ".join(bad[:3]))

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
