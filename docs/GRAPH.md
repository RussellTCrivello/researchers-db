# The relationship graph

SIRAJ stores connectivity three ways, and the interface can explore all three:

| Layer | What it means | Where it lives |
|---|---|---|
| **Typed relationships** | a person *taught* a person, an institution *employed* another — directional, dated, sourced | `relationship` (14 572 rows) |
| **Structural links** | foreign keys that create a bond without a relationship row: affiliation, birthplace, venue, parent place, citation | columns on `person`, `institution`, `place`, `event`, `source_link` |
| **Derived fields** | counts and names computed with SQL over both layers (`relationships_count`, `positions_count`, `completeness`) | `app/schemas.py` → 52 derived fields |

Anything that can be said about connectivity is an aggregate over those three, never a stored copy.

---

## 1 · The API

Two endpoints, both declared **before** `/api/reports/{key}` so the report router cannot swallow them:

```
GET  /api/relationship-map?params=<url-encoded json>
POST /api/relationship-map          {"mode": "types" | "focus", ...}
```

### `mode: "types"` — the macrograph

```json
{ "mode": "types", "include_structural": true }
```

Returns:

| key | meaning |
|---|---|
| `nodes` | one entry per entity type: `{type, label_en, label_ar, count}` |
| `edges` | `{source, target, kind, count, label_en, label_ar}` with `kind ∈ relationship \| structural` |
| `matrix` | `matrix[a][b]` = number of links from type *a* to type *b* |
| `matrix_order` | the row/column order, so the client never guesses |
| `relationship_types` | the vocabulary actually used, with counts |
| `totals` | `records`, `relationships`, `structural_links`, `distinct_types` |

Live numbers from the shipped dataset: 14 569 typed relationships, 29 097 structural links, 28 538
records. The heaviest corridors are person↔institution (18 139), person→person (6 023),
person→place (6 464 including birthplaces and positions) and person→institution relationships
(4 481 of those 18 139 are typed links).

### `mode: "focus"` — the micrograph around one record

```json
{ "mode": "focus", "entity_type": "person", "record_id": 12, "depth": 2, "limit": 60 }
```

Returns `nodes` (`{id, record_id, type, label, degree}`), `edges` (`{source, target, label_en, label_ar}`),
`focus` (the centre id) and `depth`. Depth 1 is the direct neighbourhood; depth 2 adds the neighbours
of neighbours, capped by `limit` (5–120, default 60).

Both modes are cheap: the type aggregate is three `GROUP BY` queries, and focus mode walks an
indexed adjacency (`ix_rel_e1`, `ix_rel_e2`).

---

## 2 · In the interface — `/map`

`app/static/js/views/map.js` renders the same data two ways, and the state lives in `A.views.map`:

* **Entity types** — a radial graph of the six types sized by record count, with weighted edges
  (solid = typed relationship, dashed = structural). Below it: the legend, the totals strip, the
  full **connection matrix** (log-scaled heat cells with tooltips) and the list of relationship
  types actually in use with their counts.
* **Around one record** — pick an entity, a record and a depth; the record sits at the centre and
  its neighbourhood is laid out on a ring, sorted by type then degree so like sits with like.

Every node is a link: clicking a type opens its list, clicking a record opens its dossier
(`#/entity/<type>/<id>`). **Save as SVG** serialises the live SVG to a standalone file with the
fonts and label styles inlined, so the figure can go straight into a paper.

### 2.1 · The canvas — navigating a diagram too big for one screen

Both modes share one camera (`attachCanvas` in `views/map.js`). The whole diagram lives inside a
single `<g class="rm-cam">`, and every gesture writes one `transform` inside a
`requestAnimationFrame`, so panning and zooming never re-layout the graph:

| Gesture | Effect |
|---|---|
| drag the background | pan (the drag must start outside a node, so node drags stay node drags) |
| wheel / pinch | zoom anchored at the pointer — the point under the cursor does not drift |
| drag a node | move it; its edges follow, and the layout is remembered for the session |
| hover a node | its neighbourhood is highlighted, the rest dims |
| `+` / `−` / fit | zoom by a step, or fit the whole graph into the viewport |
| **Find a node** | type a name or code; the camera flies to it and selects it |
| full screen | the canvas takes the whole window, `Esc` returns |
| click a node | navigate to the record (a pan that *ends* on a node does not navigate) |

The camera is state, not DOM probing: `attachCanvas()` returns `{cam, W, H, pos, fit, zoomBy,
flyTo, animateTo, schedule, reset, getNode}`, which is what the browser harness drives. Movements are
eased (`animateTo`), so a fly-to reads as a movement rather than a jump.

## 3 · Generated figures — `docs/diagrams/`

`python3 scripts/make_diagrams.py` reads the live database and writes six standalone SVGs (no
JavaScript, no external fonts, embeddable anywhere):

| File | Shows |
|---|---|
| `entity-model.svg` | the six record types, the join tables that hold their many-to-many links, and the reference band every select field points at |
| `type-graph.svg` | the live type graph with weights — the same numbers the app's map shows |
| `matrix.svg` | the connection matrix as a figure, for print |
| `place-hierarchy.svg` | one real branch of the place tree (country → city → district) with the record counts hanging off it |
| `ego.svg` | the ego network of the most connected person in the dataset |
| `derived-lineage.svg` | which tables each of the 52 derived fields is computed from |

The script is deterministic and re-runs in under a second; it is the artefact that keeps the
documentation honest as the dataset grows. Two things it handles explicitly, because both are easy
to get wrong in SVG:

* **Arabic labels** — right-to-left text must not be anchored at the left edge, and must be trimmed
  to the space its card leaves, or it grows out of the box;
* **edge labels** — every weight slides along its own curve until it lands on empty space, so a
  number never sits on a card or on another number.

## 4 · Why not a generic graph library?

The map has to answer one question well — *how are these entities connected, and how much?* — in
both languages and inside a sandboxed, dependency-free page. Six nodes and a matrix do that without
a 300 KB force-layout bundle, and the layout is stable between reloads. A force-directed library
remains the right choice if the graph ever needs to show hundreds of records at once; the API
already returns everything such a view would need.

---

## 5 · Place-name hygiene (part of the graph's readability)

The place tree is the only self-referencing hierarchy in the registry, so its readability drives
every map and filter that groups by place. `python3 -m app.cli tidy-places` scans it and reports:

* placeholder names (`City of <country>`) → replaced with a real city of that country;
* siblings sharing a name → qualified deterministically (`Dammam · North`, `Faro · East`, …);
* every change is written to `change_log` with the old and new value, so the repair is auditable
  like any other edit.

It is a **dry run by default**; `--apply` writes the plan. The generator now produces unique,
real names in the first place, so a fresh dataset reports `renames planned: 0`.
