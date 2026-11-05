# Structures — one registry, six ways of seeing it

*How the display kernel works, what each structure is for, and the arithmetic it
refuses to fake.*

---

## 1. Why a display kernel instead of six charts

Every product eventually grows a "charts" page: a bar chart written against the
person table, a donut written against the place table, a treemap written against
whatever was in the sprint. They disagree within a month. The bar chart counts
soft-deleted rows, the donut counts something else, and none of them can be
compared, because each one owns its own arithmetic.

The structure deck inverts that. There is **one model**, produced by the server
from a declared chain of dimensions, and **one kernel** that draws any node tree.
A structure is therefore a *reading* of the model, not a new source of truth:

```
registry.db ──▶ app/structures.py ──▶ {id,label,value,children,meta}
                    (SQL, exact counts)          │
                                                 ▼
                                   components/viz.js  (model · geometry ·
                                                       camera · interaction)
                                                 │
        ┌──────────┬──────────┬──────────┬────────┴─┬──────────┐
     treemap     rings      flow      matrix      discs      tree
        └──────────┴──────────┴──────────┴──────────┴──────────┘
                              one panel · one legend · one camera · one table
```

Consequences worth stating plainly:

* switching structure never changes a number — only its shape;
* adding a source is a row in `app/structures.py`, not a new page;
* adding a language is a locale file, because every label comes from the API or
  from `locales/*.json`;
* the table, the tooltip, the panel and the exported SVG all read the same
  model, so they cannot drift apart.

---

## 2. The sources

| id | entity | chain (breadth at each level) |
|----|--------|-------------------------------|
| `people` | person | nationality → occupation/classification → record status |
| `institutions` | institution | institution type → country → governance |
| `places` | place | country → place type → coordinate precision |
| `relationships` | relationship | relationship type → direction → authentication |
| `sources` | source | source type → reliability → record status |
| `events` | event | event type → place → documentation level |

Each source is **declared**, not discovered: a chain is a list of field keys, and
`app/structures.py` refuses a field it cannot group honestly (`Unsupported`)
rather than guessing. A chain is also capped at three levels, because a fourth
level of a taxonomy of this size is a list with a picture next to it.

Values that are absent are not silently dropped: they appear as
`not recorded` / `غير مسجّل`, because "we do not know" is a category the registry
is entitled to report.

### The arithmetic

Counts are database counts, computed level by level, where **each level adds one
bound condition to the level above it**:

```sql
SELECT d.key, COUNT(*) FROM person t
  LEFT JOIN lookup d ON d.id = t.nationality_id
 WHERE t.deleted_at IS NULL
 GROUP BY 1 ORDER BY 2 DESC
```

so a child's number always means *records that reach this node*, and the
children of a node always add up to that node. `tests/verify_all.py` checks the
sum at every level for every source, against the live database.

### Breadth and folding

A three-level tree grows as *n³* queries, so breadth is budgeted:

* **level 1** gets `2 × max_children` (capped at 60) — it is one query per
  branch, and it is what the picture is read from;
* **deeper levels** get `max(5, max_children ÷ (level + 1))` — each is one query
  per branch *per parent*.

Whatever does not fit is **folded into a declared aggregate**, never dropped:

```json
{"label_en": "10 smaller groups", "value": 998,
 "meta": {"synthetic": true, "count": 10, "folded": 998}}
```

The legend says how many branches were folded, the mark says it again in its own
label, and the panel repeats it when the mark is read. A picture that quietly
hides 40 % of a level is worse than no picture.

The client folds a second time only for the node budget (900 marks), using the
same declaration. Folding is always *additive*: the value of a folded node is
the exact sum of what went into it.

### Cost, stated

`GET /api/structures/{source}` returns `computed_ms`; the model returns its own
build time; the deck prints both, with the node and leaf counts, in the footer:

```
⛁ server 118.09 ms   ◈ model 5.4 ms   ▤ 662 marks / 613 leaves
records in view 6,825   measured, not estimated
```

There is no spinner that lies and no "instant" that is not. A 30-second server
cache keeps a fresh tree from being recomputed on every structure switch, and it
says `cached` when it is used.

---

## 3. The node contract

```ts
Node = {
  id: string,            // stable, path-shaped: "people/nationality_id=IQ/..."
  label_en: string,
  label_ar: string,
  value: number,         // exact record count
  children?: Node[],
  meta?: { dimension, raw, depth, collected, of, synthetic?, count? }
}
```

The kernel in `app/static/js/components/viz.js` knows nothing about people or
institutions. It takes an **adapter** — `id`, `label`, `value`, `children`,
`color`, `group` — and the registry's adapter is the only thing that knows that
`label_ar` exists. A file tree, a query result or a taxonomy from another table
is a change of adapter, not of renderer.

---

## 4. The six structures

| structure | question it answers | geometry |
|-----------|--------------------|----------|
| **Treemap** | *what is the size of things, at two levels at once?* | squarified rectangles (Bruls/Huizing/van Wijk), children nested inside parents |
| **Rings** | *how does the whole divide, and then divide again?* | radial partition; three rings, one per level, hub = the branch in view |
| **Flow** | *where do the records go?* | layered flows, three columns, one shared scale |
| **Matrix** | *which combinations actually occur?* | cross-tab: level 1 × level 2, cell = matching records |
| **Discs** | *what is the hierarchy, as containment?* | circle packing, children packed inside their parent |
| **Tree** | *what is the shape of the taxonomy?* | an outline you open and close, node-link with béziers |

Rules that hold across all six:

* **a mark is a node** — hovering, clicking, double-clicking and the keyboard do
  the same thing in every structure;
* **labels are placed, not sprayed** — a label is drawn only where it fits, is
  measured before it is placed, and truncates with the ellipsis on the correct
  side for the script (`…سوريا` for Arabic, `Egyp…` for English);
* **nothing is redrawn that can be moved** — the camera animates between
  framings, and entries are staggered rather than popped;
* **what is left out is written down** — folded branches, "12 of 49 shown" in the
  flow heads, "559 branches closed" in the outline.

### Treemap

Two levels are drawn: the branch (level 1) and, where the rectangle is large
enough to be honest about it, its children (level 2). A rectangle smaller than
54 world units is not labelled, because a label that does not fit is not a label.

### Rings

The hub is the branch in view, with its own name and count. Ring 1 is the level
below it, ring 2 the level below that. A full ring is drawn as two circles under
even-odd fill — built from two half-arcs it becomes a blob whose centre is not
the centre.

Labels sit *outside* the ring and are placed largest-first, each reserving
circumference in proportion to its own length. A curved caption inside a 3 %-wide
arc is not a caption; it is a smudge.

### Flow

Three columns: the branch, its largest twelve children, and the two largest
children of each of those. The scale is **shared and taken from the whole**, so a
column that omits its tail shows the omission instead of hiding it. The third
column is ordered *by parent*, never by size across parents: ranking the whole
pool would interleave siblings and cross the ribbons, and a crossing flow diagram
is a diagram of nothing. The heads print `12 / 49` and `24 shown`.

### Matrix

Rows are the ten largest children of the branch in view; columns are the fourteen
largest grandchildren, keyed by `dimension=raw` so the same value reached through
different parents lands in one column. A cell holds the exact number of records
at that combination, printed when the cell can hold it, and shaded by intensity
(scaled by a power curve, not linearly — a 1-record cell would otherwise be
invisible next to a 300-record one). Row totals are printed at the end of each
row, so nothing has to be summed by eye.

### Discs

Children are packed as discs that cannot overlap; each disc contains its own
children, packed again inside it. Area is proportional to value within a level.
It is the structure to use when the question is *containment*, not comparison.

### Tree

An outline, not a plate of spaghetti: branches open when they are clicked, closed
branches say how many are behind them, and the camera refuses to fit the whole
outline if fitting it would shrink the labels below legibility — it keeps a
readable scale and centres on the root instead, with the minimap for orientation.

---

## 5. Reading, not navigating

Selection opens the panel on the side of the picture. The panel carries:

* the branch's dimension and value, its share of the whole and of its parent;
* the bar, so proportion is visible without arithmetic;
* its path, its parent's total, and how many branches were collected;
* the largest children, each clickable;
* **three actions** — *Go inside*, *Up a level*, and *Search these records*,
  which opens the record list filtered by this value. That is the only way out
  of the picture, it is labelled, and it is a deliberate act.

The camera: wheel zooms at the cursor, drag pans with a little momentum, pinch on
touch, double-click zooms, `fit` restores the framing, minimap shows where you
are. The keyboard: `1`–`6` structures, `Enter` opens the selection, `Escape`
clears then steps up, `+` `−` `0` zoom and fit, `/` finds a branch.

---

## 6. Motion, language and export

**Motion is a setting.** `Viz.reduced()` reads `prefers-reduced-motion`, and the
per-user preference overrides it in both directions. Every animation is
duration-collapsed to zero when motion is off — not skipped at the call site, so
no path can forget.

**Direction is a coordinate system.** Charts are laid out left-to-right in both
languages: the `dir` of the page governs the page, not the geometry. Label
anchors therefore mean the same thing in Arabic and English, and Arabic runs
still shape and order right-to-left inside their own line.

**Export.** `Download SVG` serialises the live scene with the deck's styles
inlined, on a white ground. `CSV` in the table writes node, path, value and
share, UTF-8 with a BOM so Excel opens it correctly. The table itself is the same
model as rows — it is what a screen reader reads, and it is not hidden behind a
"view data" affordance nobody clicks.

---

## 7. Endpoints

| method | path | returns |
|--------|------|---------|
| `GET` | `/api/structures` | `{ok, sources[], max_depth, max_children}` |
| `GET` | `/api/structures/{source}` | `{ok, source, chain[], depth, max_children, root, total, computed_ms, cached}` |

Query parameters: `depth` (1–4, default 3), `max_children` (3–40, default 24).
An unknown source is `404`; a field that cannot be grouped is `422` with the
reason, never an empty chart.

Route: `#/structures`. View: `app/static/js/views/structures.js`. Kernel:
`app/static/js/components/viz.js`. Styles: `app/static/css/viz.css`.

---

## 8. How it is proven

```
python3 tests/structures_ui.py         # 62 checks, in a browser
python3 tests/verify_all.py            # + 26 checks, against the API and the SQL
```

`verify_all.py` proves the arithmetic: for every source, the first level adds up
to the declared total and a child level adds up to its parent, folded branches
declare themselves, cost is reported, `depth=1` returns one level, an unknown
source is a `404`.

`structures_ui.py` proves the behaviour: every structure draws, every mark is
labelled, clicking reads without navigating, the panel carries the route to the
records, double-click drills and `Escape` walks back, the wheel zooms at the
cursor and `fit` restores it, number keys switch structure, the table lists the
model and the export is a real SVG file, another source and another depth draw,
search highlights, Arabic turns the interface round while the geometry stays put,
reduced motion is honoured, and leaving disposes the camera without a console
error.

Screenshots of the six structures are produced by `--shots DIR`.
