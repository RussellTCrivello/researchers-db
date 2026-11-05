# The atlas — the relationship map as a place you work in

*How the diagram is built, why it never sends you away, and what it refuses to claim.*

---

## 1. The problem with a diagram that opens pages

Most registry products ship a "network view" that is really a picture of an index:
you click a circle, the browser navigates to a record page, and the diagram you
were reading is gone. The reading you were doing — *who is next to whom, and how
well is that known* — is interrupted by a page load, and the trail of thought is
lost. The atlas exists because that interruption is the whole value of the view.

So the rule is simple and absolute:

> **Nothing in the atlas navigates.** A selection changes the panel. The trail
> changes the centre. A filter changes the drawing. Navigation is a deliberate
> act, offered once, in the panel, as a labelled shortcut.

Everything below follows from that.

---

## 2. Three columns, one workspace

```
┌──────────────┬─────────────────────────────────┬──────────────────────┐
│ rail         │ stage                           │ panel                │
│              │                                 │                      │
│ arrangement  │  ◉ orbit / ✦ force / ▦ matrix   │  type · title · code │
│ record types │  ┌───────────────────────────┐  │  status · verification│
│ relationships│  │      the scene            │  │  documentation        │
│ show only    │  │  (pan · zoom · drag)      │  │  resolved facts       │
│ legend       │  └───────────────────────────┘  │  counts · neighbours  │
│ counts       │  trail: overview › A › B        │  evidence             │
└──────────────┴─────────────────────────────────┴──────────────────────┘
```

**The rail** is what you can change: the arrangement, which types and
relationship types are drawn, and two refinements that matter to a historian —
*only relationships that cite a source*, and *hide relationships that have
ended*. It also states, in words, what the line styles mean, because a legend
that requires interaction is not a legend.

**The stage** is the drawing. It is measured from the column it is given and
drawn at scale 1, so text stays crisp and the orbit is round rather than a
letterbox. Pan, wheel-zoom, double-click-zoom, node dragging and keyboard
arrows all work on the same camera.

**The panel** is the answer to "what did I just click?". It is a column, not an
overlay, so opening it never covers the diagram the selection came from. It is
deliberately one request: `GET /api/graph/node/{type}/{id}` resolves a record
into readable facts (a name in its original script, a transliteration, dates,
a place, an institution — not raw foreign keys), keeps record status,
verification and documentation as three separate claims, and states how complete
the record is *as a note about completeness, never about truth*.

---

## 3. Reading the same neighbourhood three ways

The same nodes and edges are drawn three ways, because different questions need
different structures:

| Arrangement | What it shows | When to use it |
|---|---|---|
| **Orbit** | hop distance from the centre; the ring is fixed, the sector is fixed by type then name | reading one record's immediate world — the default |
| **Force** | a deterministic spring settle (fixed iterations, seeded by type) | dense neighbourhoods where the orbit's rings hide clusters |
| **Matrix** | rows and columns are the same records; a shaded cell is a stored relationship | asking "which of these are *not* connected", which a hairball cannot answer |

All three are deterministic: the same data always settles into the same shape.
A diagram that reorganises itself on every visit cannot be learned, and a
researcher who cannot recognise yesterday's picture cannot compare it with
today's.

At the whole-registry level the atlas opens on the **overview**: one node per
record type, sized by how many records it holds, joined by the stored
relationships between types — plus the same table, type against type, so the
shape of the registry can be read as a picture and as numbers. Clicking a type
opens a real neighbourhood inside the same workspace.

---

## 3b. Names are the reading, so names are placed

A network diagram lives or dies on its labels. At 14 relationships they turn
into a paragraph if they are sprayed around their glyphs, so placement is a
three-stage process:

1. **Estimate.** Candidate slots — right, left, above, below, and the four
   diagonals — are tested against glyph boxes and already-placed names, using
   script-aware text metrics (Arabic runs are measured differently from Latin).
   The biggest claim goes first: the centre, then the best-connected.
2. **Measure.** Once the scene is in the DOM the real boxes are measured and the
   weakest name in any collision is nudged outward along its own bearing. This
   is what makes it work in Arabic, where an estimate is always approximate.
3. **Give way, visibly.** A name that still cannot be placed legibly is dimmed
   rather than moved into the glyphs — and comes back to full strength on hover,
   focus or selection. The centre's name never gives way: it is the anchor of
   the reading.

The orbit uses two bands per ring for the same reason: one circle puts every
name in the same annulus, where they can only overlap. And a label is drawn on
an *edge* only when that edge is being read — a found path, or the edge you
selected — because naming thirteen relationships at once is not information.

## 4. Drilling in without leaving

Selecting a record offers three moves, all of them in place:

* **Explore from here** — re-centres the atlas on that record. A trail bar
  records where you have been (`overview › Dalal b. Abd Allah al-Sadi ›
  Heritage Foundation of Johannesburg`); every crumb is clickable, and
  `Alt+←` walks back. The panel follows you in, because you drilled in *about*
  that record.
* **Find a path…** — asks the one question a picture cannot answer: are these
  two records connected at all, and by what? The answer is a chain of stored
  relationships with each step's own verification, or an honest "not connected
  within the search limit". A chain is a route through the records, not a
  statement about anyone in it, and the panel says so.
* **Open the record** — the single, explicit shortcut out, to
  `#/entity/{type}/{id}`.

---

## 5. What the diagram refuses to do

These are deliberate omissions, not gaps:

* **No guilt by association.** A stored relationship is not a finding of
  responsibility. Edges are uniform in width by default — money-weighted
  thickness would make an allegation look like a fact — and selecting a node
  emphasises its neighbourhood without dimming the rest into suspicion. The
  panel carries the sentence: *a connection is not a finding of responsibility*.
* **Verification is not reliability.** The line style carries verification
  (solid *corroborated*, dashed *single source*, dotted *unverified*); source
  reliability is a property of the citation, shown in the evidence list. A
  single high-quality source and a single poor one look the same on the line and
  differ in the citation, which is where the difference belongs.
* **Contradiction stays visible.** A record whose sources disagree is marked,
  its panel keeps the contradiction, and nothing resolves it silently.
* **Ended relationships stay drawn**, in a distinct treatment, until the reader
  hides them — a partnership that ended in 1934 is evidence about 1934.

---

## 6. Keyboard, direction and disposal

* `/` puts the caret in the diagram's own find box (and gives it back to the
  site search when the atlas is not on screen).
* `Esc` closes the panel; `Alt+←` walks the trail; `Enter` opens whatever has
  focus, node or edge.
* Everything is mirrored right-to-left: the rail moves to the right, the panel
  to the left, glyph labels flip their anchors, and Arabic labels are measured
  with Arabic metrics when the label placer decides where a name fits.
* Leaving the view disposes its document listeners and its resize handler
  (`A.views.map.__dispose`, called by the router), so a round trip through the
  atlas leaves nothing behind — asserted in the tests rather than assumed.

---

## 7. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/relationship-map` | the nodes and edges of a focus neighbourhood or the type overview |
| `GET` | `/api/graph/node/{type}/{id}` | one record's dossier: state, resolved facts, counts, neighbours, evidence, completeness |
| `POST` | `/api/graph/path` | shortest chain of stored relationships between two records, with its steps |

Full payload shapes are in [`API.md`](API.md) §Relationship graph.

---

## 7.1 · The node *is* the standard

A node in the atlas is not a coloured circle with a badge on it. For the three
covered categories the node **is** its CRCE mark — the person rosette, the
organization rosette, the place rose — drawn from the same server geometry the
record page draws, at whatever radius the layout gives it
(`A.crce.svgString(category, r)`). The atlas therefore inherits the standard's
guarantees without restating them: a person cannot be drawn with a place's
mark, an institution cannot borrow the person's, and an uncovered kind keeps the
plain glyph it had.

Two consequences shape the drawing:

* **The count cannot sit inside the mark.** A reserved mark fills its disc, so
  the relationship count that used to print at the node's centre now rides in
  the label (`Persons · 6.8k`), measured and collision-tested with the name it
  joins. Nothing covers the geometry that carries meaning.
* **The panel surfaces the position.** A selected record shows a CRCE tile —
  its mark, the role of its point, the precision on file and the phrase
  (`recorded seat · Uncertain · 3,937 km ENE`) — fetched from
  `/api/crce/dossier/{type}/{id}` and rendered in place, so reading a record's
  spatial standing never leaves the diagram either.

An overview bubble stands for a whole *type*, not one record: clicking it opens
that type's neighbourhood (`openNeighbourhood`) rather than asking the graph for
a record that does not exist. The full standard is in [`CRCE.md`](CRCE.md).

---

## 8. How it is proven

`tests/atlas_ui.py` (54 checks, real browser, console errors fatal) walks the
whole contract: the overview, one click into a neighbourhood, selection without
navigation, the panel's shortcut, neighbour and matrix-cell selection, drill-in
and trail-back, the three arrangements, filters that reshape rather than reload,
the path finder, the keyboard, listener disposal, and the Arabic right-to-left
layout. `tests/verify_all.py` covers the two endpoints at the HTTP level,
including the 404s and the clamp; `tests/ui_full.py` and `tests/evidence_ui.py`
cover the atlas inside the wider application (a node opens in the panel, an edge
opens its relationship with exactly the evidence the API reports).
