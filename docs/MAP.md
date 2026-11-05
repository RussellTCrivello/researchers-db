# SIRAJ · the geographic workspace

A map that draws the registry, not a picture of a map. Every marker is a record in
`person`, `place`, `institution` or `event`; every line is a stored relationship or a
stored parent-child place; every number on screen came from a query that also says what
it left out. Nothing is generated for display and nothing is written from the map.

```
app/geo/basemap.sqlite        the offline basemap pack (Natural Earth, public domain)
app/geo/basemap_build.py      builds that pack from downloaded GeoJSON
app/geo/basemap.py            reads it: layers, viewport queries, gazetteer, country_at
app/geo/spatial.py            coordinate parsing/formatting, haversine, CRS, bbox, DMS
app/geo/mapdata.py            "what is a record's position" — features, groups, overlays,
                              detail, search, reverse, spatial queries
app/geo/georef.py             registry ↔ gazetteer reconciliation (the geocode-places CLI)
app/geo/providers.py          base-map providers with attribution, licence and terms
app/server/map_api.py         the HTTP surface (/api/map/*, /api/geo/*)
app/static/js/views/geomap.js the three-zone workspace (MapLibre GL, bundled)
app/static/vendor/maplibre-*  MapLibre GL JS 4.7.1 + CSS + licence, served locally
```

---

## 1 · Where a record is

A record's position is never guessed. `mapdata.JOINS` is the single place that decides
it, and it is a join, not a heuristic:

| layer | position comes from | anchor shown in the inspector |
|---|---|---|
| `place` | the place's own `latitude` / `longitude` | "own position" |
| `person` | `place.latitude/longitude` of `person.birthplace_id` | "birthplace" |
| `institution` | `place.latitude/longitude` of `institution.place_id` | "location" |
| `event` | `place.latitude/longitude` of `event.place_id` | "place" |

A record with no coordinates, or whose place has none, is **not drawn** — there is no
fallback to a country centroid and no placeholder at (0, 0). `GET /api/map/layers`
reports both numbers per layer, and the workspace shows the located/total pair in the
filter panel, because "750 of 1 118 places are on this map" is a fact about the data
that a researcher needs.

```json
{"entity_type": "place", "total": 1118, "located": 750}
```

`python3 -m app.cli geocode-places` proposes coordinates for the rest from the bundled
gazetteer; it writes only when the record's **name and its own country** agree with the
city it matched (see §8).

---

## 2 · The base map

Eight providers are declared in `app/geo/providers.py`, arranged in four **families** so
that the choice is a decision about cartography rather than a list of brand names. Each
carries its style object, its attribution in both languages, its licence, a terms URL and a
usage note, because a base map shown without its terms is a licence breach waiting to
happen.

| family | id | what it is | network | attribution | licence |
|---|---|---|---|---|---|
| **offline** | `local` (default) | vector, from the bundled pack | **no** | Basemap: Natural Earth (public domain) | public domain |
| **standard** | `osm` | OpenStreetMap standard tiles | yes | © OpenStreetMap contributors | ODbL 1.0 |
| | `esri-street` | Esri World Street Map | yes | © Esri, HERE, Garmin, USGS, © OpenStreetMap contributors | Esri Terms · ODbL |
| | `carto-light` | CARTO Positron | yes | © OpenStreetMap contributors · © CARTO | ODbL / CARTO terms |
| | `carto-dark` | CARTO Dark Matter | yes | © OpenStreetMap contributors · © CARTO | ODbL / CARTO terms |
| **aerial** | `esri-imagery` | satellite and aerial photographs | yes | Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community | Esri Terms |
| | `esri-hybrid` | the same imagery **plus** a boundaries-and-places layer | yes | imagery attribution · labels © Esri | Esri Terms |
| **terrain** | `opentopomap` | contours, relief, hydrography | yes | © OpenStreetMap contributors · SRTM · © OpenTopoMap (CC-BY-SA) | CC-BY-SA 3.0 · ODbL |

**Standard and aerial are different questions.** A standard map is drawn to be read: it
tells you where the road and the district are. Aerial imagery shows the ground itself —
which is what a survey needs to see a tell, a shoreline that moved, or a site the
cartographer generalised away. The hybrid style puts the names back on top of the
photograph, which is usually the view a researcher actually wants.

The attribution and the licence link are drawn **on the map**, bottom-left, on every
provider, and they are part of the exported screenshots as well. The `local` provider
shows them even though Natural Earth is public domain and asks for nothing. Two providers
that stack sources (the hybrid) show both attributions.

**Offline is the default and the guarantee.** `app/geo/basemap.sqlite` is 2.54 MB and
holds five layers — countries, coastline, lakes, rivers, populated places — at 1:110m and
1:50m detail, quantised to int32 deltas at 1e-5 degrees and zlib-9 compressed, with an rtree
for viewport queries (8 layer·level stores, 4 129 stored features):

```
countries 39 ms world · 9 ms for an Iraq-sized box · country_at() 0–3 ms
```

Rebuild it with `python3 -m app.geo.basemap_build` (needs the Natural Earth GeoJSON in
`--src`; the script documents which six source files). If the pack is missing the API answers
`503` and the interface says so instead of showing an empty canvas.

Providers are switched from the **Layers** menu, grouped under *Offline · Standard maps ·
Aerial imagery · Terrain*, each row with a colour swatch of what it looks like. The choice
is a personal preference (`map.provider`), so one researcher can work over imagery while
the instance default stays offline. Switching never touches the registry: only the style
object handed to MapLibre changes.

`GET /api/map/config` returns the catalogue both flat (`providers`, each with its style)
and arranged by family (`provider_groups`), so the client renders the grouping from the
server's declaration rather than its own hard-coded list.

---

## 3 · The three zones

```
┌──────────────────────────── toolbar ─────────────────────────────┐
│ records │ search │ coordinates │ zoom │ layers │ measure │ inspector │
├──────────────┬───────────────────────────────┬───────────────────┤
│ left panel   │ map                           │ right panel       │
│  Records     │  legend, scale, readout,      │  the selected     │
│  Places      │  attribution, banner,         │  feature, in full │
│  Filters     │  measurement panel            │  or the temporary │
│              │                               │  point            │
└──────────────┴───────────────────────────────┴───────────────────┘
```

* Each panel collapses independently; with both closed the map fills the workspace and
  `map.resize()` (MapLibre's own method) is called on the next two animation frames — the
  geographic view is preserved exactly, only the canvas grows. Verified by
  `tests/ui_geo.py` ("the map grew into the space the panels gave up").
* The layout is remembered per browser (`siraj.map_panels`) and can be forced from a
  link: `#/geo?panels=0,1`.
* On phones the panels become drawers over the map (`.geo-panel` is absolutely
  positioned under 760 px), which is what the requirement's "drawers/bottom sheets"
  means in practice.
* `#/geo?sel=person:123` opens a record selected — the same URL the inspector's
  "Open record" link and the list rows use.

The map is deliberately given the whole working area: `calc(100vh - 118px)`, with the
toolbar and panels sized in single pixels so nothing jumps when a scrollbar appears.

---

## 4 · What the controls do

| control | behaviour |
|---|---|
| search box | one box for both kinds of question: a **coordinate** (the map flies there and drops a temporary point) or a **name** — registry records first, then the bundled gazetteer, then countries. Server-side `/api/map/search`. |
| coordinates | `/api/map/parse` accepts decimal degrees, DMS, hemisphere prefixes/suffixes, Arabic-Indic digits, `;` or `,` separators. Out-of-range values are refused with the reason and the dialog stays open. |
| zoom / rotate | zoom in/out by one level; the compass resets bearing *and* pitch (drag with the right button, or two fingers, to tilt). |
| layers | provider choice, overlay toggles, clustering, labels. Changing layers never touches data. |
| measure | distance (great-circle, point by point) or area (spherical excess). Units follow `map.units` (metric/imperial); vertices are listed; `✕` clears. |
| inspector | for a record: DD, DMS and EPSG:3857 metres, the anchor the position was inherited from, the country **polygon** that contains the point (from the local pack, not a geocoder), the record's own country field for comparison, its located relationships with distances, its sources. For a temporary point: the containing country, the nearest gazetteer city, and a 25 km spatial query. |
| readout | live lat/lon under the cursor, in DD+DMS or in projected metres — click the CRS chip to switch. |
| legend | per-layer counts *for what is currently drawn*, so the legend and the map can never disagree. |

---

## 5 · Selection, and the one thing the map cannot do

**A click on a point always answers with information.** That is the whole contract of the
map: a marker that does nothing when clicked is a dead control.

Selecting a marker (or a row, or a search hit, or a relationship in the inspector)
fetches `/api/map/feature/{type}/{id}`, draws a ring on the selection source and renders
the inspector — opening it if it was collapsed, because rendering an answer into a hidden
panel reads as "clicking does nothing". Rapid changes are guarded by a token: a slow
response for an older click is dropped, so the inspector never shows a record you did not
ask for last.

Three click targets, three answers:

| you clicked | what you get |
|---|---|
| **a record marker** | that record's dossier: code, status, coordinates (DD, DMS, EPSG:3857), anchor, precision, country, its relationships and sources, and a link into the record's own form |
| **a marker that hides others** | the *same* dossier plus **"Records at this point"** — every record drawn under the cursor, each row clickable, because a dozen people born in one town is the normal case and silently picking one of them hides the other eleven |
| **a printed base-map city** | the place itself — name, coordinates, population — under the heading *Base map place*, marked **"not a registry record"**, followed by the registry records within 25 km of it |

The middle row matters: MapLibre's `queryRenderedFeatures` returns *all* features under a
pixel, in top-to-bottom order. The map keeps that whole list instead of its first element,
de-duplicates it by `type:id`, and shows the stack as a list where the chosen record is
highlighted. Choosing a sibling keeps the stack — you can walk a town's records one by one
without losing your place.

A base-map city is cartography, not a record, and the inspector says exactly that. It is
clickable anyway (its label too), because the honest answer to "what is this dot" is not
"nothing".

A click on **empty space** (no marker, no base-map city) is a *temporary* position. It is drawn differently (red, not
gold), labelled "Temporary point / نقطة مؤقتة", never written anywhere, and discarded on
Escape or as soon as a record is selected. There is no endpoint that would accept it:
the only writing routes in the application are the record forms.

---

## 6 · Spatial queries

`POST /api/map/query` is read-only and takes one of three geometries:

```jsonc
{"mode": "bbox",    "bbox": [44, 33, 45, 34], "layers": ["place"], "limit": 300}
{"mode": "radius",  "lat": 33.3152, "lon": 44.3661, "radius_m": 25000}
{"mode": "polygon", "polygon": [[44,33],[44.8,33],[44.8,33.6],[44,33.6]]}
```

Radius queries are answered exactly by haversine over the bbox pre-filter (no
approximation is reported as if it were exact); polygons use ray casting with an
antimeridian-aware longitude wrap. Results carry `distance_m` and the same marker
contract as `/api/map/features`, so they can be selected like anything else.

The viewport itself may cross the antimeridian: `spatial.split_bbox` turns
`(170, -10, -170, 10)` into two windows before SQL ever sees it.

---

## 7 · Bounded work

`map.max_points` (default 4 000, 100–20 000, instance-level) is a budget for a **whole
response**, not per layer. The server counts each layer first and gives it a share of the
budget in proportion to what it holds — at least one feature, so no layer disappears
silently — then reports, for every layer, how much it left out:

```json
{"count": 4000, "limit": 4000, "truncated": true,
 "per_layer": {"place": {"total": 750, "returned": 358, "truncated": true},
               "person": {"total": 4805, "returned": 2296, "truncated": true}, …}}
```

The browser therefore never receives the 8 373 located records of the whole world at
once, and the interface can say "truncated — zoom in" instead of implying it drew
everything. Basemap layers are asked for a viewport too, and re-asked with a
two-decimal (≈1 km) bbox, so a one-pixel pan does not re-fetch four layers.

---

## 8 · Georeferencing what has no coordinates

`app/geo/georef.py` reconciles the registry against the bundled gazetteer, and its rule
is deliberately conservative:

1. the record's **name** matches a city in the pack, **and**
2. the record's **own `country_id`** is that city's country.

Only then is a coordinate proposed. Within 25 km of the gazetteer point the record is
reported as `within` and nothing is written; further away it is a `correct`ion; with no
coordinate at all it is a `fill`. A name that matches a city in *another* country is a
`conflict` — a finding for a human, never an overwrite (the seed data contains
`Jerusalem (PS)` against a gazetteer entry in `IL`, and it must stay that way until
someone decides). Several same-named cities in the right country are `ambiguous`;
everything else is `unmatched`, because the pack holds 1 251 cities, not every village on
earth.

```bash
python3 -m app.cli geocode-places            # dry run: what would change, and why
python3 -m app.cli geocode-places --apply    # write, with two audited change_log rows each
GET /api/map/georef/preview                  # the same plan, read-only, for the interface
```

Applied on this dataset: 443 coordinates written, located places 719 → 750, 17 conflicts
and 642 unmatched left for a researcher to decide.

---

## 9 · Configuration

Nine keys in the `map` group, all in `app/settings.py` and all readable from the settings
screen:

| key | default | scope | effect |
|---|---|---|---|
| `map.provider` | `local` | personal | base map in use (`applyProvider`) |
| `map.center_lat` / `map.center_lon` | 33.3152 / 44.3661 | instance | where the map opens the first time |
| `map.zoom` | 5 | instance | first zoom level (1–18) |
| `map.max_points` | 4000 | instance | the per-response feature budget (§7) |
| `map.cluster` | true | personal | group nearby markers |
| `map.units` | metric | personal | distances and areas in the inspector and the measure tool |
| `map.show_labels` | true | personal | labels above zoom 7, gazetteer city names below 10 |
| `map.overlays` | `place_hierarchy` | personal | which overlays are drawn |

The viewport itself (centre, zoom, bearing, pitch) is not a *setting* — it is per-browser
state in `siraj.map_view`, restored on return. Relationship arcs are off by default
deliberately: 1 817 arcs over one country is a thicket, not information, and the toggle
is one click away in the Layers menu.

---

## 10 · Failure is a state, not a blank screen

| what fails | what the researcher sees |
|---|---|
| `/api/map/features` | a banner with the message; the map and the previous features stay; the next successful pan clears it |
| a network provider's tiles | "the tiles for this provider could not be loaded" **with a button that switches to the offline base map** |
| the basemap pack is missing | `503` with the command that rebuilds it |
| the MapLibre bundle is missing | "the map library did not load; the rest of the application is unaffected" |
| a style swap is in flight | every drawing handler checks a `ready` flag, so no half-initialised style is queried |

---

## 11 · RTL, LTR and localisation

The workspace is built from logical properties (`inset-inline-start`, `border-inline-end`,
`margin-inline-start`), so `dir="rtl"` moves the panels, the legend, the readout and the
attribution without a second stylesheet. Language is a preference; switching it re-renders
the view and **keeps the viewport** (`siraj.map_view`), the selection and the panel
layout. All 79 new strings live in `app/static/js/locales/{en,ar}.json` (578 keys, parity
enforced by `tests/audit.py`); adding a third language needs a locale file and nothing
else.

---

## 12 · Testing

```bash
python3 -m pytest -q                     # 101 tests, incl. the geo unit tests
python3 tests/verify_all.py              # every API route, incl. all 15 map routes
python3 tests/ui_geo.py                  # 98 browser checks, one per acceptance criterion
python3 tests/ui_full.py                 # 198 interface checks (regression)
```

`tests/ui_geo.py` is the acceptance list made executable: navigation access, provider
attribution, located-only features, marker → record selection, list ↔ map sync, temporary
points that write nothing (checked by comparing the change-log row count before and
after), coordinate validation, DD ↔ DMS agreement, cluster opening, group statistics,
filters changing features *and* counts, layer toggles touching only the view, panel
collapse preserving the viewport, AR RTL / EN LTR with the view preserved, overlays
matching the API's own counts, an injected 500 recovering, rapid selection changes,
keyboard access, and the response budget.

Two sections were added after the first release of the workspace, because a map is only
useful if a click on it answers a question:

* **map styles** — the families in the menu, that choosing aerial actually requests
  satellite tiles (`World_Imagery` in the style's own sources), that its attribution
  appears on screen, that the hybrid stacks two sources, that a terrain style exists, and
  that the offline pack is one click away again;
* **clicking a point shows its records** — the inspector is collapsed first, so the click
  itself must open it; the dossier title must be filled; a marker hiding several records
  must list **all** of them; and a base-map city must show the place plus the count and
  rows of the records inside 25 km of it.

### The acceptance criteria, one line each

The phase's 25 acceptance criteria, each with the executed check that proves it. Run
`python3 tests/ui_geo.py`; the label in the third column is what prints green.

| # | Criterion | Proving check |
|---|---|---|
| 1 | reached from the existing navigation | *the geographic map is reached from the existing navigation* · *the navigation entry routes to #/geo* |
| 2 | tiles/vectors from the configured provider | *the configured provider is the one in use* · *basemap geometry is fetched from the local pack* · *the offline pack answers without the internet* · *the base maps are grouped into families* · *a standard, an aerial, a hybrid and a terrain style are all on offer* · *choosing aerial imagery loads satellite tiles* · *the imagery attribution is displayed, as its licence requires* · *the hybrid style stacks imagery under a labels layer* · *a terrain style is available too* · *the offline base map is one click away again* |
| 3 | records shown at their locations | *records are drawn at their locations* |
| 4 | no placeholder for records without coordinates | *no more features than located records exist* · *the registry really does contain records without coordinates* |
| 5 | marker click selects the record | *clicking a marker selects its record* · *a marker click is a record selection, not a temporary point* · *clicking a point opens the inspector with that record's details* · *the inspector is collapsed before the click* · *every record at that point is listed, not just the top one* · *clicking a base-map city shows the place itself* · *and lists the registry records at that city* |
| 6 | the selected marker is rendered correctly | *the selected marker is rendered as selected* |
| 7 | selection synced with the inspector | *the inspector shows the last selection, never a stale one* · *the inspector shows DD, DMS and projected metres* |
| 8 | left list ↔ map stay in sync | *the record appears in the left-hand list* · *selecting in the list selects the record* · *the list marks exactly one selected row* |
| 9 | clicking an arbitrary coordinate creates a temporary selection | *some of the visible map is empty, as it should be* · *clicking an arbitrary coordinate creates a temporary selection* · *the inspector describes the temporary point* |
| 10 | the temporary selection never writes | *the temporary selection wrote nothing to the database* (change-log row count before/after) · *Escape discards the temporary selection* · *a whole session of map use changed no data* |
| 11 | coordinate entry validates ranges | *an out-of-range latitude is rejected with a reason* · *the dialog stays open on invalid input* |
| 12 | DD ↔ DMS conversions are accurate | *a valid DMS coordinate navigates* · *decimal degrees and DMS of the same place agree* |
| 13 | overlapping records distinguishable | *nearby markers are clustered so overlaps stay distinguishable* |
| 14 | groups/clusters show statistics and open their records | *clusters are present at a wide zoom* · *clicking a cluster opens it up instead of doing nothing* · *places are listed with statistics* · *each place shows how many records it holds* · *opening a group centres the map on it* · *the group's underlying records are reachable from the inspector* |
| 15 | filters update features **and** the count | *filtering reduces the features and their count* · *the browser holds only what was asked for* |
| 16 | layer toggles change the view only | *the layer toggle changed the requested layers* · *the legend follows the visible layers* · *turning a layer back on did not touch the data* |
| 17 | resizing a panel preserves the geographic view | *collapsing both panels does not change the zoom* · *… does not change the centre* · *the map grew into the space the panels gave up* · *bringing the panels back restores the width* |
| 18 | AR RTL / EN LTR correct | *the interface switched to English, LTR* · *in LTR the records panel sits left of the inspector* · *the interface switched back to Arabic, RTL* · *in RTL the records panel sits right of the inspector* |
| 19 | language change preserves map state | *the language change preserved the map view* · *the legend is still rendered after two language switches* |
| 20 | relationship layers reflect actual relationships | *relationship arcs are computed from stored relationships* · *place hierarchy paths are computed from parent places* · *the drawn arcs match the API's own count* |
| 21 | map actions respect permissions | *editing is handed off to the record's own permission-checked form* · *the hand-off actually leaves the map for the record* · *the workspace issues no mutating request but the read-only spatial query* · *the only non-GET call is the spatial query* |
| 22 | API errors and tile failures are recoverable | *a failing feature request is announced instead of blanking the map* · *the map itself survives a failing endpoint* · *the view recovers by itself once the endpoint answers again* · *an unreachable tile provider is announced with a way back* · *one click returns to the offline base map* · *the notice clears once the offline map is back* |
| 23 | rapid selection changes never show stale content | *the inspector shows the last selection, never a stale one* |
| 24 | keyboard-accessible controls | *every map control carries an accessible name* · *the map itself can take focus* · *the layer menu opens from the keyboard* · *Escape closes the layer menu* |
| 25 | large datasets usable without loading every record | *the server caps how many features a viewport may return* · *the response never exceeds the cap* · *the response says how much it left out* · *the browser holds only what was asked for* |

Criterion 21 deserves a word: the map has **no privileged action of its own**. Everything that
could change a record — status, coordinates, relations — is an `<a href="#/entity/…">` into the
record's existing form, which is the only surface with validation, permissions and audit. The
harness proves this positively (the inspector's control is a link to that form) and negatively
(the whole session issues exactly one non-GET call, `POST /api/map/query`, which is a read).

Screenshots: `docs/screenshots/geomap-{en,ar,measure,collapsed}.png`.

---

## 13 · The other view of the same records: the relationship diagram

The geographic map answers *where*. It cannot answer *who with, when, on what evidence*, and
it would be dishonest to cram those onto one diagram. So the registry has two views of one
dataset, and they address the same rows:

* **`#/geo`** — places as markers (see §1–§12);
* **`#/map`** — People, Institutions and Places as typed nodes; every Relationships row as a
  labelled edge; and every Services row as evidence you can open.

### 13.1 · They are the same records, and the interface says so

| from | to | how |
|---|---|---|
| a person, institution or place record | the diagram, centred on **that** record | *Open in the relationship diagram* (hero toolbar) → `#/map?focus=person:1` |
| the diagram's record picker | any record in the registry | the picker lists the 60 most-connected records; the search box beside it queries the same `/api/{entity}/query` the list view uses and adds the match to the picker |
| an edge's panel | the relationship's own record | *Open the full record* → `#/entity/relationship/{id}` |

A deep link is honoured exactly: if the requested record is not among the first 60, it is
fetched and placed first rather than silently replaced by whichever record sorts first. The
harness asserts that (`a record page opens the diagram on exactly that record`), because a
control that quietly shows a different record is worse than no control.

### 13.2 · Visual grammar, and what it refuses to encode

| what | how it is drawn | why |
|---|---|---|
| entity type | **shape + fill + text label** | colour alone excludes colour-blind readers and dies in print |
| relationship type | the edge's own label, from the vocabulary's `label_en` / `label_ar` | a line with no name is decoration |
| direction | an arrowhead, **only** when the relationship type is directional | a symmetric relationship with an arrow invents a hierarchy |
| verification of the relationship | **line style + written status in the panel and the edge's tooltip**: solid = corroborated / primary document / institutionally confirmed · long dash = single source / self-declared · dotted = unverified | a dashed line that nobody can decode is not a legend, it is a rumour |
| source reliability | shown **beside** verification in the evidence cards and the edge panel — never merged into the line style | a confident source can be wrong about one claim; a shaky one can be right |
| a relationship that has ended | drawn at 30% opacity (`.30`) when `end_date` is set, `.9` when a contradiction exists, `.62` otherwise | the past is context, not the present |
| amount of money | **nothing** | the registry has no amounts, currencies or valuation dates; width-by-money would invent them |
| a change record | **nothing** — `change_log` never becomes a node or an edge | the audit trail is a ledger, not a social network |
| selection | opens the record's panel with its evidence, and keeps the record's own page one click away | selection must reveal, not detour |

### 13.3 · Selecting an edge

Clicking an edge (or focusing it and pressing <kbd>Enter</kbd>) opens a panel written from the
*relationship's* own data, not from the layout:

type in both languages · both endpoints, each linking to its record · direction · start and end
dates with their precision · verification, in words · last review · description · **its evidence
cards** · a link into the full record · and the standing safety note:

> A connection is not a finding of responsibility. Relationships are documented associations,
> not allegations of wrongdoing.

Endpoints are rendered in neutral ink on purpose: styling a node by how many relationships it has
is guilt by association, and the diagram refuses to do it.

### 13.4 · Implementation notes worth keeping

* The edge `<g>` carries a transparent 14-unit stroke as its hit area. Its `pointerdown` must
  **return before** the canvas's `setPointerCapture`, or the derived `click` retargets to the
  `<svg>` and the edge never hears it. This is the single most expensive bug in this file.
* A perfectly vertical or horizontal edge has a zero-width (or zero-height) bounding box. Humans
  click its stroke; automated drivers refuse to click a zero-area element. `tests/evidence_ui.py`
  therefore clicks the midpoint of the drawn line, not the element's centre.

### 13.5 · How it is proven

`python3 scripts/check.py --evidence` runs `tests/evidence_ui.py` (36 checks): evidence cards
carry claim, page, support type, source reliability and claim verification · a contradiction is
drawn distinctly, listed first and flags the record contested · a source can be attached from
the dialog through the combobox · line styles vary per verification · arrows appear only for
directed relationships · an ended relationship fades while its open neighbours do not · an edge
opens its record with the same number of evidence cards the API stores · the same works from the
keyboard · a record page opens the diagram on that record · the finder reaches the registry · and
the session ends with no console error.

---

## 14 · The map speaks the registry's coordinate standard

Every marker on this map is a spatial reference, so every marker is drawn through
[CRCE](CRCE.md) — the same encoding the record page and the atlas use. There is no second
visual language for geography.

| what | how |
|---|---|
| the marks | A MapLibre symbol layer `geo-crce` (`minzoom 6.5`) draws `crce-person`, `crce-organization` and `crce-place` over the plain dots already on the canvas. Below zoom 6.5 the dots stay: at that scale a rose is 3 pixels of noise, and pretending otherwise is not legibility |
| which categories | people, institutions and places only. Events and sources are outside the standard and keep their dots — they never wear a mark that belongs to another category |
| hit testing | the click query asks for `geo-points` **and** `geo-crce`, so selecting a rose selects its record exactly like selecting a dot |
| the legend | each covered category is legended with its own mark, drawn from the API's geometry (`A.crce.svgString`), not with a coloured square |
| the icons | `A.crce.registerMapIcons(map, 44)` rasterises the published geometry through `iconImage()` per category, so the canvas icons and the DOM marks cannot drift apart |
| the position itself | clicking a marker opens the record's inspector as before; the record page's **Position** tab and the atlas panel both surface the full dossier (`/api/crce/dossier/{type}/{id}`) |

The rule behind the layer is the standard's own: a record kind that has no reserved mark does not
get one here either, and an unlocated record has no marker to draw in the first place — the map
already refuses to plot what the registry does not know.

Proven by `tests/crce_ui.py` (`the legend shows the reserved mark per covered category`) and by
`tests/ui_geo.py`, which still asserts that every marker corresponds to a located record.

---

## 15 · The desk: the map worked like a table

`#/map` is the geographic workspace, a document you inspect. `#/desk` is the same records in the
shape of a working surface: a map you operate, an index you scan, a panel you read, a table you
sort — one selection shared by all four, and a view toggle that never changes which records are in
front of you.

| zone | what it is made of | where the data comes from |
|---|---|---|
| the map | MapLibre GL JS, one WebGL canvas, the offline vector pack by default | `GET /api/map/features?bbox=&zoom=&layers=` |
| the legend | one chip per layer, with the layer's own reserved mark | `A.crce` + the desk's active layers |
| the chip bar | centre, zoom, records in window (`/ total` when truncated), region under the centre | the camera, plus `/api/geo/reverse` |
| the pop-up card | identity, status, anchor, coordinates in both notations, description, related chips, two actions | `GET /api/map/feature/{type}/{id}` |
| the detail rail | counters, four actions, position card, four tabs (overview, relationships, location, data) | `GET /api/graph/node/{type}/{id}` + the map feature |
| the neighbourhood panel | the selected record's relationships as a hub; with nothing selected, the window's busiest places | `/api/graph/node/…`, `GET /api/map/groups` |
| the table | the same features as rows, with a *fly to* per row | the desk's own point set |
| the minimap | the window's extent and the records in it, with the share of the world on screen | the same points |

**Rules the desk inherits from the rest of the geographic workspace, and keeps.**

* *A point is a record.* Nothing is drawn that the registry does not know, and the pop-up and the
  rail are two readings of the same `{entity_type, id}`.
* *Bounded work.* The window is queried with a limit; when the answer is truncated the chip bar
  says `n / N` instead of pretending completeness.
* *A record without a position is not a point at 0, 0.* The rail prints the server's reason.
* *A city-level coordinate is never presented as a street address* — the position card carries the
  anchor and the caveat, and the *Location* tab prints the point in EPSG:4326, OGC:CRS84 and
  EPSG:3857, each with its own axis order and unit.
* *Selection stays in place.* Choosing a record — from the index, the marks, the table, the
  neighbourhood or a search suggestion — opens the card and fills the rail. There is one explicit
  way out, `Open the record`, and it is a button, not a side effect.
* *Arabic mirrors the desk, not the geometry.* The rail moves to the right, the panel to the left,
  and every numeric fact (coordinates, EPSG values, DMS) is isolated left-to-right inside the
  right-to-left page.

The map-side capabilities of the reference relationship-map project are all reachable from this one
surface: highlight-not-filter layer chips, a minimap, focus-on-a-point, related-entity chips, the
neighbourhood to the graph's own limit, the `n / N` count, edit and relate shortcuts, saved
preferences, keyboard shortcuts with a `/` finder, and an explicit way from any mark to its record.

Proven by `tests/desk_ui.py` — 87 checks in a real browser, against a live server, ending with the
assertion that the map was disposed and no console error was raised along the way.
