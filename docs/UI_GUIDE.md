# Interface guide — views, fields and the "no dead ends" data-entry flow

*SIRAJ · سِراج — phase 2 (UI / field refinement).* Everything described here is generated
from the metadata in `app/schemas.py`, so **it applies to every entity, every field, and any
field you add later** — including fields computed from related tables.

---

## 1. Any field that points at another table is a searchable drop-down

| Where | Behaviour |
|---|---|
| Record form (`/entity/{e}/new`, `/edit`) | `fk` fields and large vocabularies render as a combobox (`A.combobox`): type to search, ↑/↓ + Enter to pick, ✕ to clear |
| Relationship dialog | other-entity picker, relationship type, source — all comboboxes |
| Link-source dialog | source combobox |
| Position rows | institution combobox |
| Filter builder | value editor for `select`/`fk` fields (multi-value `in`/`not_in` uses chips) |
| Source / primary-source fields | combobox with inline create |

Search is Arabic-aware: matching uses the same normalisation as the database
(`أ إ آ ٱ → ا`, `ى → ي`, `ة → ه`, diacritics and tatweel removed, whitespace collapsed), so
`احمد` finds `أحمد` and `تجربه` finds `تجربة`. Codes and English labels are searched too.

**Recent choices** are remembered per field scope in `localStorage` and offered first, so
repeating a value during a cataloguing session takes two keystrokes.

### Creating a missing record without leaving the form

Every `fk` combobox shows **“＋ Add — …”** at the bottom of the list (pre-filled with the text
you typed). It opens `A.quickCreate`: a compact pop-up containing only the *required* fields of
the target entity plus the few fields that are usually known at that moment. Nested creation is
allowed (one level deep for institutions → places), then it stops to avoid infinite recursion.

On save the new record is created through the normal `POST /api/{entity}` path — so numbering,
validation, audit trail and FTS indexing all apply — and the new item is selected in the
originating field immediately. Nothing is lost and no window is opened twice.

---

## 2. A fixed frame, a scrolling data area

Long lists are the normal case in a registry, so the list screen is built as a *frame* rather than a
very tall page:

```
┌ page head (title, actions) ─────────────────────────────┐  scrolls away
├ KPI strip ──────────────────────────────────────────────┤  scrolls away
├ .list-shell  (height fitted to the viewport in JS) ─────┤
│  toolbar: search · view switch · columns · saved views   │  always visible
│  filter dock (collapsible)                              │  always visible
│  ── .list-scroll ── the ONLY scrolling region ──        │
│     sticky <thead>                                      │  pinned while scrolling
│     rows …                                              │
│  ───────────────────────────────────────────────────────│
│  pager: page size · shown/total · Load more             │  always visible
└─────────────────────────────────────────────────────────┘
```

* `fitShell()` measures the space actually left above the footer (`innerHeight − shell top − footer −
  page padding`) and sets the shell height, so the frame fits any window height, browser zoom or
  wrapped page-head — no "almost fits" gap and no double scrollbar.
* Only `.list-scroll` scrolls (`scroll-behavior: smooth`, `overscroll-behavior: contain`, stable
  scrollbar gutter). The toolbar, filter dock, table header and pager never move.
* On screens ≤ 900 px the page itself scrolls and the toolbar/pager become `position: sticky`, which
  is the natural phone behaviour; printing un-fixes everything and lets the table flow across pages.
* *Collapse filters* in the toolbar hides the dock and returns its height to the data area; the
  choice survives navigation.

### Pages and "Load more" together

Both affordances are always present and never conflict:

* the pager offers explicit page numbers plus a page-size selector (10–100);
* **Load more** appends the next page to the rows already on screen (10 → 20 → 24 in the demo data),
  shows a thin progress bar of `shown / total`, and disappears once everything is loaded;
* scrolling near the bottom auto-loads the next chunk (debounced, 160 px threshold), so a mouse wheel
  alone can browse the whole table;
* changing filters, sorting or page size resets to page 1 — a partial append never mixes two
  different result sets.

## 3. Displaying any field — including fields derived from related tables

Fields come in two kinds, unified in `A.registry(entity)`:

* **stored fields** — the columns of the table;
* **derived fields** (`ƒ`) — SQL expressions computed at read time from other tables:
  counts of relationships / positions / citations, institution and country names reached
  through a foreign key, birth/death years, age at death, duration of a relationship,
  and percentage completeness. They are declared in `DERIVED_FIELDS` (`app/schemas.py`) and
  are valid everywhere a stored field is: **columns, filters, sort, export, saved views and reports.**

Where they can be used:

| Surface | Derived field support |
|---|---|
| Column chooser | full list, grouped, `ƒ` badge, presets (default / all / derived-only), custom ordering |
| Filter builder | separate “Related-table filter” opt-group; numeric operators (`≥`, `≤`, between) |
| Sorting | click any `ƒ` column header |
| Card / gallery / row layouts | facts and KPI figures can be derived values |
| Export | checkbox list includes derived columns; values are computed, not exported as SQL |
| Reports / pivot | the pivot group-by list has a “Related tables” group |
| Record page | a dedicated **ƒ Related tables** tab lists every derived field with its formula |

### Key figures above every list

`POST /api/{entity}/kpi` returns headline tiles for the **current selection** — records in this
view, average completeness, records below 50 % completeness, records touched in the last 30 days,
and the totals of the related-table counts (relationships, positions, citations…) marked `ƒ`. The
strip reacts to filters, search and the recycle-bin switch, so the numbers always describe what is
on screen rather than the whole table.

### Views

Four data views, one click apart, persisted per entity (`siraj.view.<entity>`):

* **Table** — sticky header, sortable columns, bulk selection (delete / restore / set status / merge).
* **Cards** — image or initials, code + status badge, title/subtitle, fact lines, KPI figures.
* **Gallery** — square media, compact captions; for catalogues of portraits, buildings, sites.
* **Rows** — dense avatar rows, best for scanning long lists.

The **card layout builder** (`Layout`) decides *what a card is made of*: image field, title
field, subtitle field, badge field, up to four fact lines and up to four KPI figures, with a live
preview. Layout settings are stored per entity per browser, so the same data can be browsed as
portraits by one person and as institutional profiles by another.

### Imagery

`person`, `institution`, `place` and `event` carry `image_url` + `image_alt`. The form offers
both a URL box and an **Upload image** button (`POST /api/media` → `/api/media/<file>`), which
stores the file next to the database and fills the URL. Alt text is used for accessibility and
as a caption. Cards degrade gracefully: no image → initials band (people) or a compact
placeholder strip (entities).

---

## 4. Saved views

A saved view captures the *whole browsing state*: filters, free text, sort, visible columns and
the view/layout choice. Stored in `saved_view`, served by `/api/saved-views`, and re-appliable in
one click — the standard way to give a team a shared “connected researchers”, “ministries founded
before 1950”, or “records awaiting review” screen.

---

## 5. Duplicates and merging

`GET /api/{entity}/duplicates` groups live records whose names collide **after Arabic
normalisation**, so `تجربة الدمج` and `تجربه الدمج` are surfaced together. Each group shows codes,
titles, completeness and last-updated timestamps; the UI can merge a group directly.

`POST /api/{entity}/{id}/merge` with `{merge_ids, reason, dry_run}`:

1. keeps the chosen primary record;
2. fills its empty fields from the duplicates (`fields_filled` in the plan);
3. moves source links, tags, external identifiers, attachments, positions, citations and
   relationships;
4. soft-deletes the duplicates (recoverable from the recycle bin) and writes the whole operation
   into the audit trail with its `tx_id`;
5. `dry_run: true` returns exactly what *would* happen, for a reviewer to approve.

---

## 6. Keyboard and ergonomics

| Keys | Action |
|---|---|
| `/` | focus global search |
| ⌘/Ctrl + S | save the form |
| ↑ / ↓ + Enter | navigate and pick in a combobox |
| Esc | close a combobox / modal |

The record form has a sticky action bar with **Save**, **Save + new** (rapid cataloguing),
**Cancel** and an unsaved-changes indicator; navigating away with unsaved input asks for
confirmation. Validation marks the first offending field and scrolls to it.

---

## 7. Bilingual and RTL

Every interface string comes from `app/static/js/locales/{ar,en}.json` (384 keys each, kept in
lock-step by a test); record *content* is bilingual in the database itself. The language toggle shows the
language it would switch *to*, cycles through the languages declared in `locales/index.json`, re-renders the current view in place and flips
`dir` from the manifest. Adding a language is a new JSON bundle plus one manifest line — no component
changes (see `docs/I18N.md`). Titles shown in lists and page headers follow the active
language (`displayTitle`): Arabic names in Arabic, English/original names in English, falling back
to `code` so a row is never blank. Numerals and codes stay Latin in both languages so counts,
years and identifiers match the exported files exactly.

---

## 8 · The relationship map (`#/map`)

The map answers one question well: *how are these records connected, and how much?*

* **Entity types** — the six types as a radial graph sized by record count, with weighted edges
  (solid = rows in `relationship`, dashed = structural links such as affiliation, birthplace, venue
  and citations). The legend, the totals strip and the full **connection matrix** sit underneath,
  followed by the relationship vocabulary actually in use with counts.
* **Around one record** — choose an entity, a record and a depth (1 or 2). The record sits at the
  centre, its neighbourhood on a ring, sorted by type then degree so like sits with like. Node size
  encodes degree; the centre node is emphasised.
* **Every node is a link** — a type node opens its list, a record node opens its dossier.

### 8.1 · The canvas: navigating a diagram too big for one screen

The diagram is not a static picture that happens to be clickable. It is a camera over an infinite
canvas, and every gesture a person expects from a map works:

| Gesture | What happens |
|---|---|
| drag the empty background | pans; releasing mid-throw keeps the momentum and coasts, then settles |
| mouse wheel / trackpad pinch | zooms **at the pointer** — the node under the cursor does not drift (measured: < 0.5 px) |
| double-click | zooms in at that point; `Shift`+double-click zooms out |
| drag a node | moves it out of the way; the edges attached to it follow live |
| hover a node | its neighbourhood stays lit and everything else fades to 28 %, so a dense graph explains itself |
| finder box | type part of a label: matching nodes are ringed, the count appears, `Enter` opens the first, `Esc` clears |
| `+` `−` `⤢` `⛶` | zoom in, zoom out, fit the whole graph, full screen |
| keyboard | `+`/`−` zoom, `0` or `F` fit, arrow keys nudge the camera |
| `Save as SVG` | exports the live graph as a standalone file with the styles inlined |

Every one of those writes a single `transform` attribute inside a `requestAnimationFrame`, so a
depth-2 neighbourhood (hundreds of nodes) pans and zooms without re-rendering the diagram. Panning is
clamped so a quarter of the viewport always still shows content — the graph can never be lost, and
`⤢` always brings it back. `Esc` leaves full screen. The identical interaction is verified in both
English (LTR) and Arabic (RTL) — the coordinate maths goes through the live screen CTM, so the two
directions behave the same.

The figures in `docs/diagrams/` are generated from the same data by
`python3 scripts/make_diagrams.py`; see [`GRAPH.md`](GRAPH.md).

---

## 8.2 · Filtering with the same controls as the form

The filter panel does not invent its own inputs. Every clause's value editor is the *same* control the
record form uses, so a filter speaks the vocabulary the data was entered in:

* a searchable drop-down (with inline create) for every foreign key — `Birthplace = Baghdad`;
* vocabulary selects for every `select` field, and multi-select chips for `in` / `not_in`;
* the date/time control for every date field, with `on` · `before` · `after` · `between`
  (two controls side by side) · `year_eq` · `year_gte` · `year_lte`;
* `empty` / `not_empty` for the fields where "has a value" is itself the question.

`Choose a field` opens a **grouped, searchable field picker** — the same groups and labels as the form
(`Identity`, `Career`, `Timing`, `Record keeping`, …), with an icon per type and a badge marking
date-with-time fields and derived (related-table) fields. A clause can therefore be added by name
instead of scrolling a 90-item list.

---

## 9 · Dates and times in the interface

Every date field is the same control (`components/fields.js` → `A.dateControl`), and it never invents
precision:

* a **date** input (native calendar), plus a **time** input on the fields where a time is meaningful
  (`event.start_date/end_date`, `relationship.start_date/end_date/last_review_date`,
  `source.publication_date/access_date`) — the `now` button fills both in one click;
* a **precision** select — `year only` · `month` · `day` · `date + time`. Lowering it truncates the
  stored value **on purpose**; raising it never invents a component the researcher did not type;
* typing a full date while the select still says "year" promotes the select instead of silently
  throwing the month and day away;
* a legacy value (`c. 1850`, `1850s`, `1850?`) appears as a chip next to the control and is left
  exactly as it was — the registry does not "fix" a circa date.

The same control is what the filter panel uses (§4), so a filter is described with the vocabulary the
data was entered with: `Start date · on · 1950-01-08`, `between 1947-01-01 → 1947-12-31`,
`Event type ∈ {…}` (multi-select chips), `Birthplace = Baghdad` (searchable drop-down with inline
create) — no bare text boxes.

---

---

## 10 · Where a form opens: page or pop-up window

One setting decides where every create/edit form appears. It lives in **Settings → Data-entry
surface** (`#/settings`), and it changes the *frame*, never the form: the same sections, the same
controls, the same validation.

| Setting | Effect |
|---|---|
| **Full page** | `#/entity/person/new` is its own screen (the phase-1..5 behaviour). |
| **Pop-up window** | The form opens over the list it belongs to (new) or over the dossier being edited (edit). |
| **Automatic** | Pop-up on viewports ≥ 960 px, full page below. |

Two levels: an **instance default** in the `setting` table (`ui.form_mode`, `ui.form_dialog_size`,
served to the first paint through `/api/meta` and written through `PUT /api/settings`) and a
**personal override** in this browser. The settings card shows which one is in force, what the other
is set to, and offers **"Open a form"** so the choice can be tried before it is kept.

What the dialog gives you that the page did not:

* the list (or the dossier) stays visible behind the form — a new record is entered next to its neighbours;
* **Save · Save + New · Cancel** sit in a sticky footer that stays put while the body scrolls, next to
  the dirty indicator;
* the head shows the title and `CODE · v3`; the page behind keeps its breadcrumbs;
* Escape, the × and a backdrop click all run the same **"Discard changes?"** guard; declining keeps the
  draft exactly as typed;
* focus moves into the form, Tab cycles inside it, and closing puts the cursor back on the button that
  opened it;
* the address bar stays honest — closing swaps the hash back, so a reload shows the page behind and
  Back leaves the page instead of reopening the dialog;
* **Save + New** stays on the same surface with a cleared form.

Not everything moves. The **import wizard**, **bulk edit**, **settings** and the **saved-view editor**
stay full pages: they are multi-step tasks with their own progress and failure paths, not a record
being entered. Inline create pop-ups, the duplicates/merge panel and every confirmation already used
the same dialog primitive, so they behave identically in both modes.

Full write-up: [PHASE6.md](PHASE6.md).

---

---

## 11 · The structure deck (`#/structures`)

Six readings of the same registry — treemap, rings, flow, matrix, discs, tree — over one model,
one camera, one selection panel and one table. The numbers do not change when the shape does.

* **The toolbar** switches structure (`1`–`6`), source, depth, and toggles the legend, the table and
  the SVG export; the find box marks matching branches and frames the first one.
* **A mark is a node.** Hover gives a tooltip with the value, its share and its ancestry; a click
  reads it in the panel; a double-click (or `Enter`) goes inside; `Escape` clears, then steps up.
  The crumb trail at the top is the way back, and every crumb is clickable.
* **The panel** gives the dimension, the exact count, the share of the whole and of the parent, the
  path, the collected branches, the largest children (clickable) and three actions: *Go inside*,
  *Up a level*, and *Search these records* — the one deliberate way out of the picture.
* **The camera** zooms at the cursor, pans with momentum, pinches, double-clicks, and `fit` restores
  the framing; the minimap shows where you are.
* **Folding is declared.** A branch that aggregates smaller ones says so in its own label, in the
  legend, and again when it is read.
* **The cost is printed** in the footer: server time, model time, marks, leaves and the record count
  in view — measured, never estimated.
* **Arabic** turns the page around; the geometry does not flip, because a coordinate system is not a
  paragraph. Labels truncate on the correct side for the script.
* **Motion is a setting**, honoured from the preference and from `prefers-reduced-motion`.

Full write-up: [STRUCTURES.md](STRUCTURES.md).

## 12 · The map desk (`#/desk`)

The registry worked as a place, in the same way a list is worked as a table. Three panels, one
selection, and a view toggle that never changes which records you are looking at.

**The map.** A real MapLibre canvas with eight base maps — the default one is drawn from
`app/geo/basemap.sqlite`, so the desk works with no network at all; the others are OSM,
Esri Street, Esri Imagery, Esri Hybrid, CARTO Light, CARTO Dark and OpenTopoMap. Every point is a
registry record: it carries `entity_type`, `id` and `code`, and nothing on the map is invented.
Points are grouped into discs at low zoom, separated in screen space so no two discs sit on top of
each other, and reduced to specks when the window holds too many to read. The legend along the top
left names the four kinds and greys out the ones you have switched off; a dashed entry reminds you
that a group carries the mark of what is most common in it.

**The chip bar** under the map states the centre in decimal degrees (one click copies it), the
zoom, how many records are in the window (`of N` when the window is truncated) and the name of the
region under the centre, read from the local basemap. It follows the camera, not the other way
round.

**Reading a mark never navigates.** A click opens a pop-up card anchored to the mark — avatar,
name, code, status, anchor, coordinates in both notations, description, the related records as
chips, and two actions: *Open the record* and *Show in the neighbourhood*. The selected mark wears
the accent ring and its name. `Escape` closes the card and keeps the desk where it is.

**The detail rail** (right in Arabic, left in English) carries the avatar and type, the status
chips, four counters (incoming, places, institutions, people), the four actions — *Edit record*,
*Add relationship*, *On the map*, *Delete* — a position card with the anchor, decimal degrees, DMS
and the country from the local polygons, a *Show in the neighbourhood* button, and four tabs:
*Overview* (the first facts plus the evidence counts), *Relationships* (grouped by type, each row
showing the relationship, the record, the verification flag and the direction), *Location* (anchor,
DD, DMS, country, and the same point in EPSG:4326, OGC:CRS84 and EPSG:3857, each in its own unit)
and *Data* (every fact). A record with no coordinates says so, with the server's reason, instead of
drawing a point at 0, 0. The footer states where the panel's data came from.

**The neighbourhood panel** draws the selected record's own relationships as a hub with labelled
nodes on accent edges, headed `n / N` — what is drawn of what exists. A node is a button: click it
(or `Enter` on it) and the desk selects that record in place. With nothing selected, the panel
offers the **busiest places in the window** instead of an apology: the same aggregates the map is
built from, and every row is a way into the records.

**The table view** (`g`, or the Map/Table toggle) is the same records as rows — mark, code, name,
type, status, anchor and coordinates — with a *fly to* button per row that closes the table and
frames the record. Writing in the search box never loses the table.

**Trail, toolbar and keyboard.** Back and forward step through the records you have read, and undo
closes the selection; the Tools menu holds the base maps, labels, the neighbourhood panel and
*fit the window's records* — and closes when you use it. `/` puts the cursor in the search box,
`Enter` picks the first suggestion, `g` and `m` switch views, `+`/`-` zoom, `Escape` closes the
card, then the menu, then the selection. Preferences (base map, labels, layers, panel, view) are
kept in `siraj.desk.v1`.

**Arabic** mirrors the desk — rail right, panel left — and every coordinate is isolated
left-to-right inside the right-to-left page: a latitude printed as a longitude is a wrong fact, not
a cosmetic bug.

**Small screens.** Below 1080 px the desk is one column with the map first — a reader who opens it on
a phone came for the map — and both panels become scrollable blocks under it (72 vh for the index,
60 vh for the neighbourhood), because an index of 600 records must not turn the page into a scrollbar
the length of the registry. The legend steps aside below 720 px: the layer chips in the index already
say what is on, and the chip bar needs the room.

**Motion** is honoured from `prefers-reduced-motion`; the map still moves on command, it simply does
not glide.

**One shell fix this surface forced.** At ≤900 px the sidebar used to be translated off-canvas
instead of not rendered, so its width was still counted by the document; in Arabic that pushed the
page to the far edge with a band of nothing on the reading side, and the top bar's controls overflowed
to the left of the origin on a 420 px screen. The drawer is `display:none` until it opens, the top bar
wraps its actions under the search, and `html { overflow-x: clip }` refuses any stray wide child.

## 13 · Verifying the interface

```bash
python3 -m pytest tests/ -q          # 94 API/database tests
python3 tests/verify_all.py          # 207 API checks (every route + the date model)
python3 tests/ui_smoke.py            # 46 browser checks (needs `playwright install chromium`)
python3 tests/ui_full.py             # 185 browser checks — every screen and control
python3 tests/structures_ui.py       # 62 browser checks — the six structures
python3 tests/desk_ui.py             # 87 browser checks — the map desk
```

Screens of every surface live in `docs/screenshots/`; the exhaustive walk also writes its own
screenshots to `.smoke/full/`.

The smoke test is a fast pass: every route, all four views, the column chooser with a derived
column, the layout builder, a derived-field filter, the duplicates panel, a record dossier (hero
KPIs, completeness ring, related-tables tab), the edit form's combobox and the inline create
pop-up, and the language toggle.

`ui_full.py` goes further and is the harness that gates releases: it walks **every** route and
control — shell (language toggle both ways, actor switch, global search), all thirteen routes, each
entity list (search, sort, page size, paging, load-more, filter dock with derived fields, chips,
saved views, column presets, layout builder, duplicates, export panel, bulk bar, recycle-bin lens,
four view modes), a record dossier (every tab) and the edit form, a full **create → find →
soft-delete → restore** cycle driven through the browser, all ten reports, the four-step import
wizard (including a real upload and a dry-run validation that never commits), live XLSX/CSV
downloads, the relationship map (both modes, depth, SVG download, click-through, plus the canvas:
fitted open, pointer-anchored zoom, pan, node drag, finder, hover neighbourhood and full screen), the
date-and-time control (enter a moment, reopen it, lower the precision, check a circa date survives),
the admin screens (vocabularies, numbering, settings, change log, reindex/vacuum/backup/dump), the
data-entry surface setting (page mode, dialog mode, Escape and the dirty guard, Save + New, editing
over a dossier, the trial button, and the automatic breakpoint at 1440 px and 700 px) and the 880 px
layout. It fails on any console error or uncaught exception, section by section.
