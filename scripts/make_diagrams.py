"""
SIRAJ · scripts/make_diagrams.py — generate the relationship diagrams
=====================================================================

Builds a set of self-contained SVG diagrams from the *live* database and writes
them to ``docs/diagrams/``.  Everything is plain SVG (no fonts to install, no
JS, prints and zooms perfectly) and every number in the pictures is read from
the data, so re-running the script after an import refreshs the diagrams.

    python scripts/make_diagrams.py            # all diagrams
    python scripts/make_diagrams.py --list     # what it can build
    python scripts/make_diagrams.py ego        # just one

Diagrams
--------
entity-model      the data model: six entities, their join tables, reference
                  tables, cardinalities and live row counts
type-graph        how the entity *types* connect in this database (weighted)
matrix            the same information as an adjacency heat matrix
place-hierarchy   a real slice of the place tree (country → city → district)
ego               a real person's neighbourhood (1 and 2 steps)
derived-lineage   which tables each derived ("ƒ") field is computed from
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, reports  # noqa: E402

OUT = ROOT / "docs" / "diagrams"

# ---------------------------------------------------------------------------
# palette & primitives
# ---------------------------------------------------------------------------
INK = "#16202b"
INK_2 = "#3d4a57"
MUTED = "#6b7785"
LINE = "#c9d3dd"
BG = "#ffffff"

TYPE_COLOR = {
    "person": "#2f6f4f",
    "institution": "#1f5d8b",
    "place": "#8a5a1f",
    "event": "#7b3f8f",
    "source": "#8b3a3a",
    "relationship": "#4b5563",
    "lookup": "#0f766e",
    "system": "#6b7280",
    "join": "#9a6b1f",
}

FONT = "font-family=\"'Segoe UI','Noto Sans Arabic',system-ui,-apple-system,sans-serif\""


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def svg_open(w: int, h: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" role="img" aria-label="{esc(title)}">',
        f'<title>{esc(title)}</title>',
        f'<rect width="{w}" height="{h}" fill="{BG}"/>',
        "<style>"
        "text{font-family:'Segoe UI','Noto Sans Arabic',system-ui,-apple-system,sans-serif;"
        "font-variant-numeric:tabular-nums}"
        f".t{{fill:{INK};font-size:14px}}"
        f".s{{fill:{MUTED};font-size:11.5px}}"
        f".b{{fill:{INK_2};font-size:12.5px}}"
        f".h{{font-size:20px;font-weight:800;fill:{INK}}}"
        "</style>",
    ]


def svg_close(parts: list[str]) -> str:
    parts.append("</svg>")
    return "\n".join(parts)


def text(x, y, s, cls="t", anchor="start", weight=None, size=None, fill=None, rtl=False,
         style=None):
    attrs = [f'x="{x:g}"', f'y="{y:g}"', f'class="{cls}"']
    if anchor != "start":
        attrs.append(f'text-anchor="{anchor}"')
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if size:
        attrs.append(f'font-size="{size}"')
    if fill:
        attrs.append(f'fill="{fill}"')
    if rtl and not style:
        style = "direction:rtl;unicode-bidi:plaintext"
    if style:
        attrs.append(f'style="{style}"')
    return f"<text {' '.join(attrs)}>{esc(s)}</text>"


def box(x, y, w, h, title, subtitle=None, color=INK, count=None, radius=12, dashed=False,
        fill_opacity=0.10, tag=None):
    out = []
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
               f'fill="{color}" fill-opacity="{fill_opacity}" stroke="{color}" '
               f'stroke-width="2"{dash}/>')
    ty = y + (24 if subtitle else h / 2 + 5)
    out.append(text(x + 14, ty, title, cls="t", weight=800, size=15, fill=color))
    if subtitle:
        out.append(text(x + 14, y + 42, subtitle, cls="s"))
    if count is not None:
        out.append(text(x + w - 14, y + h - 14, f"{count:,}", cls="s", anchor="end",
                        weight=700, fill=color, size=12.5))
    if tag:
        out.append(text(x + w - 14, y + 22, tag, cls="s", anchor="end", size=10.5))
    return out


def _bezier(x1, y1, cx, cy, x2, y2, t):
    return ((1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t ** 2 * x2,
            (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t ** 2 * y2)


def _inside(pt, rects, pad_x=18.0, pad_y=10.0) -> bool:
    """True when a point is inside — or too close to — any of the given cards.

    ``pad_x`` is generous because a label is centred on its anchor: half the text
    would still touch a card the anchor only just cleared."""
    x, y = pt
    for rx, ry, rw, rh in rects:
        if rx - pad_x <= x <= rx + rw + pad_x and ry - pad_y <= y <= ry + rh + pad_y:
            return True
    return False


def arrow(x1, y1, x2, y2, color=LINE, width=1.8, dashed=False, label=None,
          label_pos=0.5, curve=0.0, label_dy=-6, title=None, avoid=None, taken=None):
    """A quadratic bezier with an arrow head; `curve` bends it sideways.

    ``avoid`` is a list of ``(x, y, w, h)`` card rectangles and ``taken`` a list of
    label anchors already used: the label slides along the curve until it lands on
    empty space, which is what keeps the weights from colliding with cards and
    with each other.
    """
    dx, dy = x2 - x1, y2 - y1
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    nx, ny = -dy, dx
    norm = math.hypot(nx, ny) or 1
    cx, cy = mx + nx / norm * curve, my + ny / norm * curve
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    tip = f"<title>{esc(title)}</title>" if title else ""
    out = [f'<path d="M{x1:g} {y1:g} Q{cx:g} {cy:g} {x2:g} {y2:g}" fill="none" '
           f'stroke="{color}" stroke-width="{width}" stroke-opacity=".75"{dash} '
           f'marker-end="url(#arrow-{color.strip("#")})">{tip}</path>']
    if label:
        candidates = [label_pos, 0.5, 0.38, 0.62, 0.30, 0.70, 0.24, 0.76,
                      0.18, 0.82, 0.14, 0.88, 0.10, 0.92]
        chosen = None
        for t in candidates:
            pt = _bezier(x1, y1, cx, cy, x2, y2, t)
            if avoid and _inside(pt, avoid):
                continue
            if taken and any(math.hypot(pt[0] - tx, pt[1] - ty) < 48 for tx, ty in taken):
                continue
            chosen = (t, pt)
            break
        if chosen is None:
            best = None
            for t in candidates:
                pt = _bezier(x1, y1, cx, cy, x2, y2, t)
                if avoid and _inside(pt, avoid):
                    continue
                gap = min((math.hypot(pt[0] - tx, pt[1] - ty) for tx, ty in taken), default=1e9)
                if best is None or gap > best[0]:
                    best = (gap, t, pt)
            chosen = (best[1], best[2]) if best else \
                (label_pos, _bezier(x1, y1, cx, cy, x2, y2, label_pos))
        t, (lx, ly) = chosen
        if taken is not None:
            taken.append((lx, ly))
        out.append(f'<text x="{lx:g}" y="{ly + label_dy:g}" class="s" text-anchor="middle" '
                   f'fill="{INK_2}" font-weight="700" style="paint-order:stroke;stroke:#fff;'
                   f'stroke-width:4px;stroke-linejoin:round">{esc(label)}</text>')
    return out


def defs_markers(colors) -> str:
    out = ["<defs>"]
    for c in colors:
        out.append(
            f'<marker id="arrow-{c.strip("#")}" viewBox="0 0 10 10" refX="8.5" refY="5" '
            f'markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" '
            f'orient="auto-start-reverse">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{c}"/></marker>')
    out.append("</defs>")
    return "".join(out)


def header(parts, title, subtitle, w):
    parts.append(text(36, 46, title, cls="h"))
    parts.append(text(36, 70, subtitle, cls="s"))
    parts.append(f'<line x1="36" y1="88" x2="{w - 36}" y2="88" stroke="{LINE}"/>')


# ---------------------------------------------------------------------------
# data helpers
# ---------------------------------------------------------------------------
def counts(conn) -> dict[str, int]:
    out = {}
    for t in ("person", "institution", "place", "event", "source", "relationship",
              "person_position", "source_link", "entity_tag", "entity_external_id",
              "attachment", "saved_view", "lookup", "tag", "change_log", "search_doc",
              "app_user", "sequence", "locale"):
        try:
            out[t] = int(conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"])
        except Exception:                              # table may be absent
            out[t] = 0
    return out


# ---------------------------------------------------------------------------
# 1 · entity model
# ---------------------------------------------------------------------------
def diagram_entity_model(conn, c) -> str:
    """Entity model: one card per record type, the join tables underneath it,
    and a shared reference-data band.  No long crossing arrows — the parent is
    stated on every child card, which keeps the picture readable."""
    W = 1420
    parts = svg_open(W, 1000, "SIRAJ entity model")
    header(parts, "SIRAJ — how the entities connect",
           "Six record types, the join tables that hold their many-to-many links, and the "
           "reference data every field points at.  Counts are live.", W)

    _cols = 6
    bw, gap = 210, 20
    x0 = 36

    def card(x, y, w, h, title, sub, color, count, tag, kids=(), dashed=False):
        out = box(x, y, w, h, title, sub, color=color, count=count, tag=tag,
                  dashed=dashed, fill_opacity=0.09)
        for i, kid in enumerate(kids):
            ky = y + 74 + i * 17
            out.append(text(x + 14, ky, "· " + kid, cls="s", size=10.8))
        return out

    # ---- entity cards -------------------------------------------------
    ey = 112
    eh = 136
    ents = [
        ("person", "PERSON", "40 fields · 17 ƒ · الأشخاص",
         ["positions → institution", "citations ↔ source", "tags · external ids"]),
        ("institution", "INSTITUTION", "36 fields · 9 ƒ · المؤسسات",
         ["place_id → place", "persons → person", "positions → person"]),
        ("place", "PLACE", "29 fields · 9 ƒ · الأماكن",
         ["parent_place_id → place", "country_id → lookup", "birthplace of persons"]),
        ("event", "EVENT", "22 fields · 5 ƒ · الأحداث",
         ["place_id → place", "participants → person", "citations ↔ source"]),
        ("source", "SOURCE", "26 fields · 6 ƒ · المصادر",
         ["citations → any record", "reliability → lookup", "attached to any record"]),
        ("relationship", "RELATIONSHIP", "25 fields · 6 ƒ · العلاقات",
         ["entity1 → any record", "entity2 → any record", "source_id → source"]),
    ]
    pos = {}
    for i, (key, en, sub, kids) in enumerate(ents):
        x = x0 + i * (bw + gap)
        pos[key] = (x, ey)
        parts += card(x, ey, bw, eh, en, sub, TYPE_COLOR[key], c[key], "records", kids)

    # ---- join tables, aligned under their owning entity ---------------
    jy = ey + eh + 78
    parts.append(text(36, jy - 16, "Join & child tables — where the many-to-many links live "
                                   "(the arrow points at the record type they belong to)",
                      cls="b", weight=700))
    owner_of = {"person_position": 0, "source_link": 0, "entity_tag": 0,
                "entity_external_id": 0, "attachment": 3, "saved_view": 5}
    joins = [
        ("person_position", "POSITIONS", "person → institution · dates · title", "person_position"),
        ("source_link", "CITATIONS", "source ↔ any record · per field", "source_link"),
        ("entity_tag", "TAGS", "tag ↔ any record", "entity_tag"),
        ("entity_external_id", "EXTERNAL IDS", "VIAF · Wikidata · ISNI · GND", "entity_external_id"),
        ("attachment", "ATTACHMENTS", "files under uploads/", "attachment"),
        ("saved_view", "SAVED VIEWS", "filters + columns + sort", "saved_view"),
    ]
    jh = 104
    for i, (_table, en, desc, key) in enumerate(joins):
        x = x0 + i * (bw + gap)
        parts += box(x, jy, bw, jh, en, desc, color=TYPE_COLOR["join"],
                     count=c[key], tag="rows", dashed=True)
        ox, oy = pos[list(pos)[owner_of[key]]]
        parts += arrow(x + bw - 30, jy, ox + bw - 30, oy + eh,
                       color=TYPE_COLOR["join"], width=1.3, dashed=True,
                       curve=(x - ox) * 0.06)

    # ---- reference data band ------------------------------------------
    ry = jy + jh + 74
    parts.append(text(36, ry - 16, "Reference data — every select field stores an id here; "
                                   "labels are bilingual and colour-coded", cls="b", weight=700))
    refs = [
        ("lookup", "LOOKUP", "21 domains · 271 values"),
        ("tag", "TAG", "free tag vocabulary"),
        ("app_user", "APP_USER", "viewer · researcher · reviewer · admin"),
        ("sequence", "SEQUENCE", "prefix · padding · template · reset"),
        ("change_log", "CHANGE_LOG", "field-level audit trail"),
        ("search_doc", "SEARCH (FTS5)", "Arabic-normalised index"),
    ]
    rh = 74
    for i, (table, en, desc) in enumerate(refs):
        x = x0 + i * (bw + gap)
        parts += box(x, ry, bw, rh, en, desc, color=TYPE_COLOR["lookup"],
                     count=c.get(table, 0), tag="rows", fill_opacity=0.07)
    band_y = ry + rh + 14
    parts.append(f'<path d="M{x0 + 6} {band_y} H{W - x0 - 6}" stroke="{TYPE_COLOR["lookup"]}" '
                 f'stroke-width="1.2" stroke-dasharray="3 4" stroke-opacity=".7"/>')
    parts.append(text(x0 + 6, band_y + 20,
                      "↑ every entity card points into this band through its select fields "
                      "(status, classification, country, source type, reliability …)",
                      cls="s"))

    # ---- reading guide -------------------------------------------------
    ly = ry + rh + 52
    parts.append(f'<rect x="36" y="{ly}" width="{W - 72}" height="150" rx="14" fill="#f7f9fb" '
                 f'stroke="{LINE}"/>')
    parts.append(text(52, ly + 28, "Reading the diagram", cls="b", weight=700))
    guide = [
        ("entity card", "one table, its row count, and the links it owns on the third line"),
        ("dashed box", "a join/child table: it exists because of the entity above it"),
        ("arrow", "the child table's foreign key → the parent record type"),
        ("ƒ", "a derived field: computed by SQL from these tables, never stored"),
    ]
    for i, (k, v) in enumerate(guide):
        yy = ly + 54 + i * 24
        parts.append(text(60, yy, k, cls="s", weight=700))
        parts.append(text(190, yy, v, cls="s"))

    # ---- the shape of the graph ---------------------------------------
    dy = ly + 172
    parts.append(f'<rect x="36" y="{dy}" width="{W - 72}" height="170" rx="14" fill="#fff" '
                 f'stroke="{LINE}"/>')
    parts.append(text(52, dy + 30, "The shape of the graph", cls="b", weight=700))
    lines = [
        "Every record is bilingual and typed by a code (PERSON-0001). Relationships are rows, "
        "not ID lists, so each one carries its own dates, source and authentication level.",
        "52 derived fields (“ƒ”) are computed with SQL over these tables — counts, names, years, "
        "durations, completeness — and can be used in columns, filters, sorts, exports and reports.",
        f"Any record can cite any source ({c['source_link']:,} citations), carry any tag "
        f"({c['entity_tag']:,}), hold any number of positions ({c['person_position']:,}) and "
        f"external identifiers ({c['entity_external_id']:,}).",
        f"Soft deletes keep deleted_at on every entity table; change_log holds "
        f"{c['change_log']:,} field-level entries and the FTS index {c['search_doc']:,} documents.",
    ]
    for i, ln in enumerate(lines):
        parts.append(text(52, dy + 58 + i * 28, ln, cls="s", size=12.2))

    return svg_close(parts)


# ---------------------------------------------------------------------------
# 2 · type graph
# ---------------------------------------------------------------------------
def diagram_type_graph(conn, c) -> str:
    data = reports.relationship_map(conn, {"mode": "types", "include_structural": True})
    W, H = 1300, 800
    parts = svg_open(W, H, "SIRAJ relationship type graph")
    colors = list(TYPE_COLOR.values())
    parts.append(defs_markers(colors))
    header(parts, "How the entity types connect — live weights",
           f"{data['totals']['relationships']:,} typed relationships and "
           f"{data['totals']['structural_links']:,} structural links across "
           f"{data['totals']['records']:,} records.", W)

    cx, cy = W / 2, 415
    R = 330
    nodes = data["nodes"]
    # fixed, readable arrangement: person left, institution right, place bottom,
    # event top-left, source top-right, relationship centre
    # person · relationship · institution share one row so the three heaviest
    # corridors are straight lines with room above them for their weights
    place_at = {
        "person": (-1.34, -0.06),
        "institution": (1.34, -0.06),
        "relationship": (0.0, -0.06),
        "place": (0.0, 1.14),
        "event": (-0.88, -1.04),
        "source": (0.88, -1.04),
    }
    coords = {}
    for n in nodes:
        dx, dy = place_at.get(n["type"], (0, 0))
        coords[n["type"]] = (cx + dx * R * 0.80, cy + dy * R * 0.60)

    # Aggregate per ordered pair *and* per kind of link: a typed relationship and a
    # structural link between the same two types share one arrow with a combined
    # count, which keeps six cards and their labels readable.
    pairs: dict[tuple[str, str], dict[str, int]] = {}
    for e in data["edges"]:
        key = (e["source"], e["target"])
        slot = pairs.setdefault(key, {"typed": 0, "structural": 0})
        slot["typed" if e["kind"] == "relationship" else "structural"] += e["count"]
    max_w = max((v["typed"] + v["structural"] for v in pairs.values()), default=1)

    def edge_point(a, b):
        """Trim the arrow so it starts/ends on the card border, not the centre."""
        ax, ay = coords[a]
        bx, by = coords[b]
        hw, hh = (per_box[a][0] / 2 + 6, 40)
        dx, dy = bx - ax, by - ay
        if dx == 0:
            return ax, ay + math.copysign(hh, dy), bx, by - math.copysign(hh, dy)
        t = min(hw / abs(dx), (hh / abs(dy)) if dy else 1e9)
        return ax + dx * t, ay + dy * t, bx - dx * t, by - dy * t

    per_box = {n["type"]: (190, 78) for n in nodes}
    cards = [(coords[t][0] - per_box[t][0] / 2, coords[t][1] - 34, per_box[t][0], 68)
             for t in coords]
    taken: list[tuple[float, float]] = []
    for (a, b), v in sorted(pairs.items(), key=lambda kv: -(kv[1]["typed"] + kv[1]["structural"])):
        if a not in coords or b not in coords:
            continue
        total = v["typed"] + v["structural"]
        w = 1 + 7 * math.sqrt(total / max_w)
        color = TYPE_COLOR.get(a, LINE)
        tip = (f"{total:,} links: {v['typed']:,} typed relationships, "
               f"{v['structural']:,} structural")
        if a == b:
            x, y = coords[a]
            hw = per_box[a][0] / 2
            r = 26
            cx0, cy0 = x + hw + r + 10, y - 4
            parts.append(f'<circle cx="{cx0:g}" cy="{cy0:g}" r="{r}" fill="none" stroke="{color}" '
                         f'stroke-width="{w:.1f}" stroke-opacity=".55"><title>{esc(tip)}</title></circle>')
            parts.append(f'<text x="{cx0 + r + 8:g}" y="{cy0 + 4:g}" class="s" fill="{INK_2}" '
                         f'text-anchor="start" font-weight="700" style="paint-order:stroke;'
                         f'stroke:#fff;stroke-width:4px">{esc(f"{total:,}")}</text>')
            # the loop label occupies space too, so other weights keep clear of it
            taken.append((cx0 + r + 40, cy0 + 4))
            continue
        x1, y1, x2, y2 = edge_point(a, b)
        bend = 0.0
        if {a, b} == {"person", "place"}:
            bend = -70          # keeps this corridor clear of the relationship lines
        elif "relationship" not in (a, b) and abs(y1 - y2) < 150 and abs(x1 - x2) > 200:
            bend = -150 if (y1 + y2) / 2 < cy else 150
        elif v["structural"] and not v["typed"]:
            bend = 22
        # labels slide along their own curve until they land on free space, so a
        # weight never sits on a card or on another weight
        label_pos = 0.34 if "relationship" in (a, b) else 0.5
        # a short corridor between two cards on the same row cannot hold a label
        # next to the line — lift it clear of the cards instead
        short_row = abs(y1 - y2) < 60 and abs(x1 - x2) < 260
        parts += arrow(x1, y1, x2, y2, color=color, width=w,
                       dashed=bool(v["structural"] and not v["typed"]),
                       label=f"{total:,}", label_pos=label_pos, curve=bend,
                       label_dy=-30 if short_row else -7,
                       title=tip, avoid=cards, taken=taken)

    for n in nodes:
        x, y = coords[n["type"]]
        color = TYPE_COLOR[n["type"]]
        w = 190 if n["type"] != "relationship" else 210
        parts.append(f'<rect x="{x - w / 2:g}" y="{y - 34:g}" width="{w}" height="68" rx="14" '
                     f'fill="{color}" fill-opacity=".12" stroke="{color}" stroke-width="2.4"/>')
        parts.append(text(x, y - 8, n["label_en"].upper(), cls="t", anchor="middle", weight=800,
                          size=13.5, fill=color))
        parts.append(text(x, y + 13, n["label_ar"], cls="s", anchor="middle", rtl=True))
        parts.append(text(x, y + 30, f"{n['count']:,} records", cls="s", anchor="middle",
                          weight=700))

    # legend
    ly = 700
    parts.append(text(36, ly, "Edge labels = number of links.  Solid = rows in the relationship "
                              "table.  Dashed = structural links (affiliation, positions, "
                              "birthplace, venue, place hierarchy, citations).", cls="s"))
    parts.append(text(36, ly + 24, "Self-loops (person → person, place → place, source → source) "
                                   "are drawn above their node.", cls="s"))
    return svg_close(parts)


# ---------------------------------------------------------------------------
# 3 · matrix
# ---------------------------------------------------------------------------
def diagram_matrix(conn, c) -> str:
    data = reports.relationship_map(conn, {"mode": "types", "include_structural": False})
    order = data["matrix_order"]
    m = data["matrix"]
    cell = 96
    left, top = 210, 130
    W = left + cell * len(order) + 60
    H = top + cell * len(order) + 130
    parts = svg_open(W, H, "SIRAJ connection matrix")
    header(parts, "Connection matrix — who points at whom",
           "Each cell counts stored relationship rows from the row's entity type to the "
           "column's entity type.", W)
    for j, b in enumerate(order):
        parts.append(text(left + j * cell + cell / 2, top - 14, b.upper(), cls="s",
                          anchor="middle", weight=700, fill=TYPE_COLOR[b]))
    for i, a in enumerate(order):
        parts.append(text(left - 16, top + i * cell + cell / 2 + 4, a.upper(), cls="s",
                          anchor="end", weight=700, fill=TYPE_COLOR[a]))
        for j, b in enumerate(order):
            v = m[a][b]
            inten = 0 if not v else min(1, math.log10(v + 1) / 3.2)
            x, y = left + j * cell, top + i * cell
            fill = f'rgba(31,93,139,{0.05 + inten * 0.55:.3f})' if v else "#f7f9fb"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell - 4}" height="{cell - 4}" rx="8" '
                         f'fill="{fill}" stroke="{LINE}"/>')
            parts.append(text(x + cell / 2 - 2, y + cell / 2 + 5, f"{v:,}" if v else "·",
                              cls="b" if v else "s", anchor="middle",
                              fill="#ffffff" if inten > 0.62 else (INK if v else MUTED),
                              weight=700 if v else 400))
    parts.append(text(left, H - 56, "Diagonal = links inside the same entity type "
                                    "(person → person, place → place).", cls="s"))
    return svg_close(parts)


# ---------------------------------------------------------------------------
# 4 · place hierarchy
# ---------------------------------------------------------------------------
def diagram_place_hierarchy(conn, c) -> str:
    rows = conn.execute("""
        SELECT p.id, p.name_en, p.name_ar, p.parent_place_id, p.place_type_id,
               (SELECT COUNT(*) FROM place ch WHERE ch.parent_place_id = p.id) AS children,
               (SELECT COUNT(*) FROM person pe WHERE pe.birthplace_id = p.id) AS persons,
               (SELECT COUNT(*) FROM institution i WHERE i.place_id = p.id) AS institutions
        FROM place p WHERE p.deleted_at IS NULL""").fetchall()
    roots = [r for r in rows if not r["parent_place_id"]]
    kids_of: dict[int | None, list] = {}
    for r in rows:
        kids_of.setdefault(r["parent_place_id"], []).append(r)

    def depth(r, d=0):
        kids = kids_of.get(r["id"], [])
        return d if not kids else max(depth(k, d + 1) for k in kids)

    def weight(r):
        """How much of the registry actually hangs off this branch."""
        return (r["persons"] + r["institutions"]
                + sum(weight(k) for k in kids_of.get(r["id"], [])))

    # pick the deepest branch, preferring one that is rich in links and free of
    # duplicate-suffixed placeholders — the diagram should show a real, tidy slice
    def duplicates(r):
        return sum(1 for k in kids_of.get(r["id"], [])
                   if k["name_en"] and "(" in k["name_en"])

    roots.sort(key=lambda r: (-depth(r), duplicates(r), -weight(r), r["id"]))
    root = roots[0] if roots else None
    W, H = 1220, 760
    parts = svg_open(W, H, "SIRAJ place hierarchy")
    parts.append(defs_markers([TYPE_COLOR["place"]]))
    header(parts, "Place hierarchy — one real branch of the tree",
           "places are hierarchical (parent_place_id): country → city → district. "
           "Persons and institutions hang off the same tree.", W)
    if not root:
        parts.append(text(60, 300, "No places in this database yet.", cls="t"))
        return svg_close(parts)

    def fit(value, width, size, bold=False):
        """Trim a label to the space its card actually leaves."""
        text_value = value or ""
        per_char = size * (0.56 if bold else 0.5)
        limit = max(4, int(width / per_char))
        if len(text_value) <= limit:
            return text_value
        return text_value[:limit - 1].rstrip() + "…"

    def draw(node, x, y, width, level):
        col = TYPE_COLOR["place"]
        h = 84
        parts.append(f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{h}" rx="12" '
                     f'fill="{col}" fill-opacity="{max(0.05, 0.17 - level * 0.04):.2f}" '
                     f'stroke="{col}" stroke-width="1.8"/>')
        # line 1 — English name on the left, child count on the right; both are
        # trimmed to the space the other one leaves so they can never collide
        children_label = f"{node['children']} children" if node["children"] else ""
        name_room = width - 24 - (len(children_label) * 5.9 + 10 if children_label else 0)
        parts.append(text(x + 12, y + 26, fit(node["name_en"], max(60, name_room), 12.6, True),
                          cls="b", weight=700))
        if children_label:
            parts.append(text(x + width - 12, y + 26, children_label, cls="s",
                              anchor="end", size=10.8))
        # line 2 — Arabic name; with direction:rtl the *start* anchor is the right
        # edge, so it must be left alone (anchoring "end" pushes it out of the card)
        parts.append(text(x + width - 12, y + 48, fit(node["name_ar"], width - 24, 11.4),
                          cls="s", size=11.4,
                          style="direction:rtl;unicode-bidi:plaintext"))
        # line 3 — how many records point at this place, across the full width
        parts.append(text(x + 12, y + 70, fit(f"{node['persons']} people · "
                                             f"{node['institutions']} institutions",
                                             width - 24, 10.8), cls="s", size=10.8))
        kids = sorted(kids_of.get(node["id"], []),
                      key=lambda k: -(k["persons"] + k["institutions"]))[:5]
        if not kids:
            return
        gap = 18
        kw = (width - gap * (len(kids) - 1)) / len(kids)
        for i, kid in enumerate(kids):
            kx = x + i * (kw + gap)
            ky = y + h + 46
            parts.extend(arrow(x + width / 2, y + h, kx + kw / 2, ky, color=col, width=1.4))
            draw(kid, kx, ky, kw, level + 1)

    draw(root, 60, 130, W - 120, 0)
    parts.append(text(60, H - 40, "Each box: English name, Arabic name, how many persons and "
                                  "institutions point at that place, and its child count. "
                                  "At most five busiest children per node are drawn.", cls="s"))
    return svg_close(parts)


# ---------------------------------------------------------------------------
# 5 · ego network
# ---------------------------------------------------------------------------
def diagram_ego(conn, c) -> str:
    row = conn.execute("""
        SELECT p.id, COALESCE(NULLIF(p.name_en,''), p.name_ar, p.code) AS name
        FROM person p
        WHERE p.deleted_at IS NULL
        ORDER BY (SELECT COUNT(*) FROM relationship r WHERE r.deleted_at IS NULL AND
                  ((r.entity1_type='person' AND r.entity1_id=p.id) OR
                   (r.entity2_type='person' AND r.entity2_id=p.id))) DESC, p.id
        LIMIT 1""").fetchone()
    if not row:
        W, H = 900, 400
        parts = svg_open(W, H, "SIRAJ ego network")
        parts.append(text(40, 120, "No relationships in this database yet.", cls="t"))
        return svg_close(parts)

    pid, name = row["id"], row["name"]
    rels = conn.execute("""
        SELECT r.entity1_type AS t1, r.entity1_id AS i1, r.entity2_type AS t2, r.entity2_id AS i2,
               COALESCE(l.label_en, r.entity1_type) AS type_en,
               COALESCE(l.label_ar, l.label_en, r.entity1_type) AS type_ar
        FROM relationship r LEFT JOIN lookup l ON l.id = r.relationship_type_id
        WHERE r.deleted_at IS NULL
          AND ((r.entity1_type='person' AND r.entity1_id=?) OR
               (r.entity2_type='person' AND r.entity2_id=?))
        LIMIT 22""", (pid, pid)).fetchall()

    def title(t, i):
        from app.schemas import ENTITIES, REF_TITLE_SQL
        table = ENTITIES[t].table
        expr = REF_TITLE_SQL.get(t, "code")
        rr = conn.execute(f"SELECT {expr} AS t FROM {table} WHERE id=?", (i,)).fetchone()
        return (rr["t"] if rr else f"{t} #{i}") or f"{t} #{i}"

    W, H = 1240, 780
    parts = svg_open(W, H, "SIRAJ ego network")
    parts.append(defs_markers(list(TYPE_COLOR.values())))
    header(parts, f"The neighbourhood of one person — {name}",
           "Every edge is a stored relationship row; the stamp is its type. "
           "This is the same picture the app draws on the record page.", W)
    cx, cy, R = W / 2, 430, 250
    n = max(1, len(rels))
    for idx, r in enumerate(rels):
        other_t = r["t2"] if (r["t1"], r["i1"]) == ("person", pid) else r["t1"]
        other_i = r["i2"] if (r["t1"], r["i1"]) == ("person", pid) else r["i1"]
        ang = -math.pi / 2 + idx * 2 * math.pi / n
        x, y = cx + math.cos(ang) * R * 1.14, cy + math.sin(ang) * R * 0.86
        color = TYPE_COLOR.get(other_t, LINE)
        parts += arrow(cx, cy, x, y, color=color, width=1.6,
                       label=r["type_en"][:20].title(), label_pos=0.66, label_dy=-6)
        shape = {"person": "circle", "institution": "rect", "place": "diamond",
                 "event": "hex", "source": "book"}.get(other_t, "circle")
        if shape == "circle":
            g = f'<circle cx="{x:g}" cy="{y:g}" r="15" fill="{color}" fill-opacity=".2" stroke="{color}" stroke-width="2"/>'
        elif shape == "diamond":
            g = (f'<polygon points="{x:g},{y - 17:g} {x + 16:g},{y:g} {x:g},{y + 17:g} '
                 f'{x - 16:g},{y:g}" fill="{color}" fill-opacity=".2" stroke="{color}" stroke-width="2"/>')
        elif shape == "hex":
            g = (f'<polygon points="{x - 16:g},{y:g} {x - 8:g},{y - 15:g} {x + 8:g},{y - 15:g} '
                 f'{x + 16:g},{y:g} {x + 8:g},{y + 15:g} {x - 8:g},{y + 15:g}" '
                 f'fill="{color}" fill-opacity=".2" stroke="{color}" stroke-width="2"/>')
        elif shape == "book":
            g = (f'<rect x="{x - 13:g}" y="{y - 15:g}" width="26" height="30" rx="4" '
                 f'fill="{color}" fill-opacity=".2" stroke="{color}" stroke-width="2"/>')
        else:
            g = (f'<rect x="{x - 16:g}" y="{y - 12:g}" width="32" height="24" rx="5" '
                 f'fill="{color}" fill-opacity=".2" stroke="{color}" stroke-width="2"/>')
        parts.append(g)
        right = x >= cx
        parts.append(text(x + (20 if right else -20), y + 5, title(other_t, other_i)[:26],
                          cls="s", anchor="start" if right else "end", weight=600))
        parts.append(text(x + (20 if right else -20), y + 20, other_t, cls="s",
                          anchor="start" if right else "end", fill=color, size=10.5))
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="30" fill="{TYPE_COLOR["person"]}" '
                 f'fill-opacity=".9" stroke="{TYPE_COLOR["person"]}" stroke-width="3"/>')
    parts.append(text(cx, cy + 52, name[:30], cls="t", anchor="middle", weight=800))
    parts.append(text(cx, cy + 70, "ego — PERSON", cls="s", anchor="middle"))
    return svg_close(parts)


# ---------------------------------------------------------------------------
# 6 · derived-field lineage
# ---------------------------------------------------------------------------
def diagram_derived_lineage(conn, c) -> str:
    """Derived-field lineage as a readable table instead of a hairball.

    For every entity: which calculated fields it exposes, and which tables the
    SQL reads to produce them.  Heights are computed from the content, so the
    diagram never overflows when fields are added.
    """
    from app.schemas import DERIVED_FIELDS

    SOURCES = {
        "person": ["relationship", "person_position", "source_link", "entity_tag", "lookup"],
        "institution": ["relationship", "person_position", "source_link", "lookup"],
        "place": ["person", "institution", "event", "place", "lookup"],
        "event": ["relationship", "source_link", "lookup"],
        "source": ["source_link", "attachment", "lookup"],
        "relationship": ["lookup", "change_log"],
    }
    order = [k for k in ("person", "institution", "place", "event", "source", "relationship")
             if DERIVED_FIELDS.get(k)]

    W = 1420
    left_x, left_w = 36, 200
    mid_x, mid_w = 252, 800
    right_x = 1072
    chip_h, chip_gap = 24, 8
    row_pad = 22

    # measure: how many chip columns fit, then how tall each row must be
    chip_cols = 3
    chip_w = (mid_w - (chip_cols - 1) * 8) / chip_cols
    rows = []
    for key in order:
        fields = DERIVED_FIELDS[key]
        labels = [(f.get("label_en") if isinstance(f, dict) else getattr(f, "label_en", str(f)))
                  for f in fields]
        n_lines = math.ceil(len(labels) / chip_cols)
        srcs = SOURCES.get(key, ["lookup"])
        h = max(row_pad + n_lines * (chip_h + chip_gap) + 12, len(srcs) * 28 + 16)
        rows.append((key, labels, srcs, h))

    H = 112 + sum(r[3] for r in rows) + 40 + 70
    parts = svg_open(W, H, "SIRAJ derived-field lineage")
    header(parts, "Where the calculated fields come from (ƒ)",
           "Every derived field is a SQL expression over the tables named on its right; nothing "
           "is stored, which is why all of them can be filtered, sorted, exported and charted.", W)

    for name, x, _w in (("ENTITY", left_x, left_w), ("DERIVED FIELD (ƒ)", mid_x, mid_w),
                        ("COMPUTED FROM", right_x, W - right_x - 36)):
        parts.append(text(x, 116, name, cls="s", weight=800, fill=INK_2))
    parts.append(f'<line x1="36" y1="126" x2="{W - 36}" y2="126" stroke="{LINE}"/>')

    y = 140
    for key, labels, sources, h in rows:
        color = TYPE_COLOR[key]
        parts.append(f'<rect x="{left_x}" y="{y}" width="{left_w}" height="{h - 12}" rx="12" '
                     f'fill="{color}" fill-opacity=".10" stroke="{color}" stroke-width="1.8"/>')
        parts.append(text(left_x + 14, y + 26, key.upper(), cls="t", weight=800, size=14,
                          fill=color))
        parts.append(text(left_x + 14, y + 46, f"{len(labels)} fields", cls="s"))
        parts.append(text(left_x + 14, y + 64, f"{c[key]:,} records", cls="s"))

        for i, lbl in enumerate(labels):
            col = i % chip_cols
            line = i // chip_cols
            cx = mid_x + col * (chip_w + 8)
            cy = y + 4 + line * (chip_h + chip_gap)
            parts.append(f'<rect x="{cx:g}" y="{cy:g}" width="{chip_w:g}" height="{chip_h}" '
                         f'rx="7" fill="{color}" fill-opacity=".07" stroke="{color}" '
                         f'stroke-opacity=".45"/>')
            parts.append(text(cx + 9, cy + 16, "ƒ " + lbl[:40], cls="s", size=11.4, fill=INK_2))

        sy = y + 10
        for src in sources:
            parts.append(f'<rect x="{right_x}" y="{sy}" width="{W - right_x - 36}" height="24" '
                         f'rx="7" fill="{TYPE_COLOR.get(src, TYPE_COLOR["join"])}" '
                         f'fill-opacity=".12" stroke="{TYPE_COLOR.get(src, TYPE_COLOR["join"])}" '
                         f'stroke-opacity=".5"/>')
            parts.append(text(right_x + 10, sy + 16, src, cls="s", size=11.4, weight=700,
                              fill=TYPE_COLOR.get(src, TYPE_COLOR["join"])))
            sy += 28
        y += h

    parts.append(text(36, H - 30, "Derived fields are published by /api/meta together with their "
                                  "SQL expression, so a client can show the formula and an auditor "
                                  "can check it without reading the code.", cls="s"))
    return svg_close(parts)


BUILDERS = {
    "entity-model": diagram_entity_model,
    "type-graph": diagram_type_graph,
    "matrix": diagram_matrix,
    "place-hierarchy": diagram_place_hierarchy,
    "ego": diagram_ego,
    "derived-lineage": diagram_derived_lineage,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="generate the relationship diagrams")
    ap.add_argument("names", nargs="*", help="diagram names (default: all)")
    ap.add_argument("--list", action="store_true", help="list the diagrams and exit")
    args = ap.parse_args(argv)
    if args.list:
        print("\n".join(sorted(BUILDERS)))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    c = counts(conn)
    names = args.names or list(BUILDERS)
    for name in names:
        if name not in BUILDERS:
            print(f"unknown diagram: {name}", file=sys.stderr)
            return 2
        svg = BUILDERS[name](conn, c)
        path = OUT / f"{name}.svg"
        path.write_text(svg, encoding="utf-8")
        print(f"[diagrams] {path.relative_to(ROOT)}  ({len(svg) / 1024:.1f} KB)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
