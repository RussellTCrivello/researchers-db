# Phase 5 — the map you can navigate, the filters you already know, and real dates

Three requests, three answers:

1. an **interactive relationship map** — pan, zoom, navigate, "the most advanced interaction set";
2. **form-parity filtering** — the filter panel must offer the *same inputs* the data was entered with;
3. **full date-and-time fields** — "if possible".

Everything below was verified by running it, not by looking at it. The numbers at the end are the
executed totals.

---

## 1 · The relationship map is a canvas, not a picture

`app/static/js/views/map.js` keeps its deterministic layouts (nothing jitters between two visits) and
wraps them in a camera. The whole diagram lives in one `<g class="rm-cam">`; every gesture writes that
single `transform` inside a `requestAnimationFrame`.

| Interaction | Implementation | Why it matters |
|---|---|---|
| **Drag to pan** | pointer events + `setPointerCapture`, one transform per frame | works on touch and mouse, never selects text, never scrolls the page |
| **Inertial pan** | velocity sampled over the last 16 ms, decayed at 0.90 per frame | the diagram feels physical instead of sticky |
| **Wheel / trackpad zoom** | `Math.exp(-deltaY · 0.0017)`, anchored at the pointer through the live CTM | the node under the cursor stays under the cursor — measured drift **< 0.5 px**, in LTR *and* RTL |
| **Double-click** | zoom in at that point; `Shift`+double-click zooms out | the gesture everybody tries first |
| **Drag a node** | the node stores a translate offset; every attached edge is re-pathed live | a dense neighbourhood can be untangled by hand |
| **Hover a node** | its neighbourhood stays opaque, everything else drops to 28 % | a 300-node subgraph explains itself without a legend |
| **Finder** | normalised type-ahead (Arabic-normalised via `A.normText`), matches are ringed, counter shown, `Enter` opens, `Esc` clears | finding one person among 6 825 |
| **Fit · ± · full screen** | `getBBox()`-based fit, animated `easeOutCubic`; full screen makes the card take the viewport | the ⤢ button always recovers a lost diagram |
| **Keyboard** | `+` `−` `0`/`F` and arrow keys on the focused SVG | the map is reachable without a mouse |
| **Pan clamping** | at least a quarter of the viewport must still show content | the diagram can never be thrown off-screen |

Two bugs were found and fixed *by testing the interaction*, not by reading the code:

* **a pan that ended on a node navigated to that record** — the click fired after the drag. A gesture
  that moved more than 3 px now sets a 320 ms suppression flag, so a pan never navigates. (Verified:
  drag from empty canvas → stays on `#/map`.)
* **`clampPan()` inverted the camera on the RTL/zoomed path** — the clamp was derived in screen space
  while the camera lives in world coordinates, so one drag pushed the graph out of the viewport
  entirely. Rewritten as two inequalities per axis in world units; verified at 196 % zoom in Arabic.

Print/export is unchanged: *Save as SVG* still writes a standalone file (the camera is not baked in —
the exported file is the whole graph, which is what a paper needs).

---

## 2 · Filtering with the controls you entered the data with

The filter panel used to have its own, poorer value editor: a text input. It now builds **the same
component the record form builds** — `A.control()` in the new `app/static/js/components/fields.js`,
which the form (`views/record.js`), inline creation (`components/forms.js`) and the filter dock
(`views/list.js`) all share. One component, one behaviour, three places.

| Field type in a filter clause | Control |
|---|---|
| `fk` | searchable drop-down with **inline create** (the phase-2 combobox) |
| `select` (large vocabulary) | searchable drop-down |
| `select` (small vocabulary) | plain select — and **multi-select chips** for `in` / `not_in` |
| `date` | the date/time control, `on` · `before` · `after` · `between` (two pickers, `→`) · `year_eq/gte/lte` |
| `text` / `int` / `bool` | the typed input |
| any | `empty` / `not_empty` (added: "has a value" is a real research question) |

Plus **`Choose a field`** — a grouped, searchable field picker (`A.fieldPicker`) using the form's own
groups (`Identity`, `Career`, `Timing`, `Record keeping`, …), an icon per type, a `ƒ` badge for derived
(related-table) fields and a `date + time` badge where a time is asked for. A clause is added by name
instead of scrolling a 90-item `<select>`.

Three interface defects were found by screenshotting the result and fixed:

* the value editor was blank for `empty`/`not_empty` clauses — now it declares itself empty on purpose;
* a `between` clause emitted `undefined` until both bounds were touched — the two bounds now share one
  buffer;
* the dock header and the two-picker row collided at 1440 px — the header wraps, and a clause that
  holds a date control spans two grid columns (`.filter-row:has(.date-control)`), collapsing to one on
  narrow screens.

---

## 3 · Dates and times — the decision, and why

The request was conditional: *"if possible"*. It is possible, **without** converting the registry to
timestamps — and converting would have been the wrong answer:

* the data contains `1950` (a year), `c. 1850` (circa), `1850s` (a decade), `1850?` (uncertain).
  A timestamp column cannot hold those without inventing a day and a month the source never gave;
* a timestamp type would silently promote every historical year to 1 January.

So a time is an **optional suffix on the existing text date**, and precision is preserved end to end:

| Accepted input | Stored | Precision |
|---|---|---|
| `1950` | `1950` | year |
| `1950-05` | `1950-05` | month |
| `1950-05-12` | `1950-05-12` | day |
| `1950-05-12 21:45` · `1950-05-12T21:45` · `…:45Z` · `…+03:00` | `1950-05-12T21:45` | minute |
| `c. 1850` · `1850s` · `1850?` | unchanged | year |

Rejected with a message that lists the accepted forms (never guessed): `1912-13`, `1912-02-31`,
`1912-04-12 25:00`, `31/03/1991`, `12 April 1912`, `3000`.

**Where a time is offered.** `TIME_AWARE_FIELDS` (`schemas.py`): `event.start_date/end_date`,
`relationship.start_date/end_date/last_review_date`, `source.publication_date/access_date`. Every other
date column still *accepts* a time through the API or an import — it just does not prompt for one. The
API advertises the difference as `meta.fields[entity][key].time`, so a client never has to hard-code it.

> **A correction to the plan.** The earlier note listed `institution.last_review_date` as time-aware.
> No such column exists: `last_review_date` belongs to `relationship`, where it *is* time-aware
> (`EVT`/`REL` review stamps are moments). The flag now follows the schema instead of a stale list.

**Comparison and sorting.** `ts_of()` (a SQLite function registered next to `norm()` and `year_of()`)
expands missing parts downwards, so `1950 < 1950-03 < 1950-03-14 09:30` holds across mixed precision:

* sorting a date column orders by the full moment, not the leading digits;
* new operators `on`/`on_day`, `before`/`until`, `after`/`since`;
* `between` is moment-aware: a bare-day upper bound includes that whole day (`…–1947-12-31` includes
  31 December 23:59), a time-bearing bound is an exact `<=`;
* an unparseable date is a **warning** and a skipped clause, never a 500.

**In the interface.** One control everywhere (`A.dateControl`): native calendar, an optional time input
(revealed by the clock button in a filter, always visible on a time-aware form field), a `now` button,
and a precision select (`year only` · `month` · `day` · `date + time`).

* lowering the precision truncates **deliberately** — that is the only way a stored component is ever
  lost, and it is an explicit click;
* typing a full date while the select still says "year" **promotes** the select instead of quietly
  discarding the month and the day (this was a real bug caught in a browser probe: entering
  `1950-01-08` in a filter produced `1950`);
* a legacy value shows as a chip (`c. 1850`) and is left exactly as typed — the registry does not
  "fix" a circa date.

**Migration: none needed.** The shipped dataset contained only `YYYY` and `YYYY-MM-DD`, and the parser
accepts the old shapes unchanged. 28 541 records verified intact after the change.

---

## 4 · Evidence

| Suite | Before phase 5 | After |
|---|---|---|
| `python3 -m pytest tests/ -q` | 82 | **90** (8 new: parser table, impossible dates, `ts_of`, the `time` flag, moment round-trip, the three operators, moment sorting, the empty/not_empty partition) |
| `python3 tests/verify_all.py` | 184 | **207** (a whole `dates` section: advertised flags, canonical storage, UTC suffix, rejection, precision round-trip, circa preservation, every operator + alias, nonsense→warning, chronological sort both directions) |
| `python3 tests/ui_full.py` | 142 | **161** (date-and-time section + the canvas: fitted open, wheel zoom, pointer-anchored zoom drift, pan, pan-that-ends-on-a-node does not navigate, fit, finder, hover neighbourhood, node drag, full screen) |
| `python3 tests/audit.py` | 162 | 162 (unchanged, still green) |
| `python3 tests/ui_smoke.py` | 46 | 46 (unchanged, still green) |
| `ruff check .` | clean | clean |

**666 executed assertions, all green.** The dataset is left byte-identical in census
(6 825 persons · 1 118 places · 1 212 institutions · 14 572 relationships · 3 208 sources ·
1 606 events = **28 541**), `check-integrity` reports no structural problems, and the scratch rows the
suites create are hard-deleted through the audited repository path.

New screenshots: `docs/screenshots/map-canvas-en.png`, `map-canvas-ar.png`,
`filter-form-parity.png`, `record-form-date-time.png`.

---

## 5 · What is deliberately *not* done

* **No time zone arithmetic.** Dates are wall-clock values in the researcher's calendar; a `Z` or
  `±hh:mm` suffix is accepted and dropped rather than silently shifted. A registry of Ottoman-era
  documents has no use for a timezone-aware timestamp, and pretending otherwise would corrupt data.
* **No second-level precision.** Minutes are enough for an event; seconds from a source are kept as
  typed but not displayed separately.
* **The map does not persist node positions.** Dragging untangles the current view; a reload returns the
  deterministic layout. Saving layouts per user would be a sensible next step if you want it.
* **The phase-4 `name_en empty/not_empty` gap is now closed and pinned.** It was carried as an open
  bug; re-probing it showed the operators already partition every table exactly (person 344 + 6 481 =
  6 825, place 0 + 1 118, institution 0 + 1 212, source 0 + 3 208), so a regression test now asserts
  `empty + not_empty == total` for five entities rather than leaving the question open.
