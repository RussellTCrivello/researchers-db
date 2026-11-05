/* ============================================================================
   SIRAJ · views/map.js — the atlas: one graph you can work inside
   ----------------------------------------------------------------------------
   The diagram used to be a poster: click a node and you were thrown out of it
   onto a record page, and the picture you had built was gone.  This is the
   opposite.  Nothing here navigates.  Selecting anything — a node, an edge, a
   row in a side list — opens a panel beside the diagram, and the diagram stays
   exactly where it is.

   Four ideas hold the workspace together:

     · **Selection, not navigation.** The panel describes what you picked: its
       editorial state, its verification, the facts that matter for its type,
       how much evidence stands behind it, and what it touches. A single
       explicit button goes to the record — for the people who want the form.

     · **Drilling in, not away.** "Explore from here" re-centres the whole
       diagram on the record you picked, in place, and pushes a step on the
       trail at the top. Every step is reversible; Alt+← walks back.

     · **Three structures over one neighbourhood** — an orbit (the galaxy: the
       chosen record at the centre, its neighbours in rings by distance), a
       force layout (for dense clusters), and a matrix (for reading the pattern
       rather than the shape). Same records, same selection, same panel.

     · **Filters that reshape the picture.** Entity types, relationship types,
       evidence-only, hide-ended. Applied in the browser, so the graph answers
       immediately instead of reloading.

   All inline SVG, no libraries: crisp at any zoom, printable, offline.
   ========================================================================== */
(function () {
  "use strict";

  const A = window.App;
  const { t, esc, fmtNum, icon } = A;
  const num = fmtNum;

  const TYPE_STYLE = {
    person:      { color: "#2f6f4f", shape: "circle",  r: 24 },
    institution: { color: "#1f5d8b", shape: "rect",    r: 23 },
    place:       { color: "#8a5a1f", shape: "diamond", r: 23 },
    event:       { color: "#7b3f8f", shape: "hex",     r: 22 },
    source:      { color: "#8b3a3a", shape: "book",    r: 21 },
    relationship:{ color: "#4b5563", shape: "circle",  r: 18 }
  };
  const TYPE_ORDER = ["person", "institution", "place", "event", "source"];

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const easeOutCubic = (p) => 1 - Math.pow(1 - p, 3);

  /* ------------------------------------------------------------- language --- */
  const lang = () => (A.state.lang === "ar" ? "ar" : "en");
  const pick = (en, ar) => (lang() === "ar" ? (ar || en) : (en || ar)) || "";

  function shortLabel(text, max) {
    const s = String(text || "");
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  }

  /** Shorten a name until it fits a reserved width, so it stays in its cell. */
  function fitLabel(text, size, maxW) {
    let s = String(text || "");
    if (textWidth(s, size) <= maxW) return s;
    while (s.length > 1 && textWidth(s + "…", size) > maxW) s = s.slice(0, -1);
    return s + "…";
  }

  function compactNum(v) {
    const n = Number(v) || 0;
    if (n < 1000) return String(n);
    const k = n / 1000;
    return (k < 10 ? k.toFixed(1) : Math.round(k)) + "k";
  }

  /* --------------------------------------------------------------- glyphs --- */
  function radiusFor(style, degree) {
    /* a glyph's size reads its degree — but a registry-wide count of 14 000
       must not draw a circle the width of the canvas, so growth is
       logarithmic and capped: size stays comparable, never absurd. */
    const d = Math.max(1, degree || 1);
    const grow = 1 + 0.40 * Math.min(Math.log2(d), 6.2);
    return style.r * Math.min(grow, 3.1);
  }

  /** Drawn size of a glyph. A full roster uses a smaller cap so a gap can exist. */
  function glyphRadius(n, focusId, count) {
    const style = TYPE_STYLE[n.type] || TYPE_STYLE.person;
    const focus = n.id === focusId;
    let r = focus ? 34 : radiusFor(style, n.degree);
    /* one size for a full roster, so the gap between records stays even */
    if (count > 60 && !focus) return 14;
    return r;
  }

  function glyph(style, x, y, r, cls) {
    const c = style.color;
    const paint = `fill="${c}" fill-opacity=".14" stroke="${c}" stroke-width="2"`;
    switch (style.shape) {
      case "rect":
        return `<rect class="${cls}" x="${x - r}" y="${y - r * 0.78}" width="${r * 2}"
                 height="${r * 1.56}" rx="7" ${paint}/>`;
      case "diamond":
        return `<polygon class="${cls}" points="${x},${y - r * 1.08} ${x + r * 1.02},${y} ${x},${y + r * 1.08} ${x - r * 1.02},${y}" ${paint}/>`;
      case "hex":
        return `<polygon class="${cls}" points="${x - r},${y} ${x - r / 2},${y - r * 0.86} ${x + r / 2},${y - r * 0.86}
                 ${x + r},${y} ${x + r / 2},${y + r * 0.86} ${x - r / 2},${y + r * 0.86}" ${paint}/>`;
      case "book":
        return `<path class="${cls}" d="M${x - r} ${y - r * 0.8} h${r * 0.9} a${r * 0.2} ${r * 0.2} 0 0 1 ${r * 0.2} ${r * 0.2}
                 v${r * 1.5} h-${r * 1.1} z M${x + r} ${y - r * 0.8} h-${r * 0.9}
                 a${r * 0.2} ${r * 0.2} 0 0 0 -${r * 0.2} ${r * 0.2} v${r * 1.5} h${r * 1.1} z"
                 ${paint} stroke-linejoin="round"/>`;
      default:
        return `<circle class="${cls}" cx="${x}" cy="${y}" r="${r}" ${paint}/>`;
    }
  }

  /* The reserved CRCE mark for a category, drawn inside a node's own local
     space. The geometry is the server's — this only scales it and tints it for
     the light stage, so a person on the stage and a person on the record page
     are unmistakably the same mark. */
  const CRCE_CATEGORY = { person: "person", institution: "organization", place: "place" };

  function rosette(category, r, colour) {
    const sym = A.crce && A.crce.symbol ? A.crce.symbol(category) : null;
    if (!sym) return null;
    const k = (r * 1.95) / 100;                     // the mark's 100-unit box
    const polar = (rad, deg) => {
      const a = (deg * Math.PI) / 180;
      return [rad * Math.sin(a), -rad * Math.cos(a)];
    };
    const parts = [];
    (sym.geometry || []).forEach(p => {
      if (p.min_size && r * 2 < p.min_size) return;
      const op = p.role === "ink" ? 0.95 : (p.role === "accent" ? 0.9 : 0.42);
      const stroke = `stroke="${colour}" stroke-opacity="${op}"`;
      if (p.op === "ring") {
        parts.push(`<circle cx="${(p.cx - 50) * k}" cy="${(p.cy - 50) * k}" r="${p.r * k}" ` +
                   `fill="none" ${stroke} stroke-width="${Math.max(1, p.width * k * 1.5)}"/>`);
      } else if (p.op === "dot") {
        parts.push(`<circle cx="${(p.cx - 50) * k}" cy="${(p.cy - 50) * k}" ` +
                   `r="${Math.max(0.9, p.r * k)}" fill="${colour}" fill-opacity="${op}"/>`);
      } else if (p.op === "line") {
        parts.push(`<line x1="${(p.x1 - 50) * k}" y1="${(p.y1 - 50) * k}" ` +
                   `x2="${(p.x2 - 50) * k}" y2="${(p.y2 - 50) * k}" ${stroke} ` +
                   `stroke-width="${Math.max(1, p.width * k * 1.4)}" stroke-linecap="round"/>`);
      } else if (p.op === "arc") {
        const [x1, y1] = polar(p.r, p.a1), [x2, y2] = polar(p.r, p.a2);
        const large = (((p.a2 - p.a1) % 360) + 360) % 360 > 180 ? 1 : 0;
        parts.push(`<path d="M${(x1 * k).toFixed(2)} ${(y1 * k).toFixed(2)} ` +
                   `A${(p.r * k).toFixed(2)} ${(p.r * k).toFixed(2)} 0 ${large} 1 ` +
                   `${(x2 * k).toFixed(2)} ${(y2 * k).toFixed(2)}" fill="none" ${stroke} ` +
                   `stroke-width="${Math.max(1, p.width * k * 1.4)}"/>`);
      } else if (p.op === "poly") {
        const pts = p.points.map(([x, y]) => `${((x - 50) * k).toFixed(2)},${((y - 50) * k).toFixed(2)}`).join(" ");
        parts.push(`<polygon points="${pts}" fill="${p.fill ? colour : "none"}" ` +
                   `fill-opacity="${op}" ${stroke} stroke-width="${Math.max(0.8, p.width * k * 1.2)}" ` +
                   `stroke-linejoin="round"/>`);
      } else if (p.op === "text") {
        parts.push(`<text x="${(p.x - 50) * k}" y="${(p.y - 50) * k}" fill="${colour}" ` +
                   `fill-opacity=".85" font-size="${(p.size * k * 1.6).toFixed(1)}" ` +
                   `text-anchor="${p.anchor || "middle"}" dominant-baseline="middle">${p.text}</text>`);
      }
    });
    return `<g class="atlas-rosette" aria-hidden="true">${parts.join("")}</g>`;
  }

  /* ======================================================================
     structures — the same neighbourhood, seen three ways
     ====================================================================== */
  /** BFS hop distance from the focus, used to ring the orbit. */
  function hopDepths(nodes, edges, focusId) {
    const adj = {};
    nodes.forEach(n => { adj[n.id] = new Set(); });
    edges.forEach(e => {
      if (adj[e.source] && adj[e.target]) {
        adj[e.source].add(e.target);
        adj[e.target].add(e.source);
      }
    });
    const depth = { [focusId]: 0 };
    let frontier = [focusId];
    while (frontier.length) {
      const next = [];
      frontier.forEach(id => {
        (adj[id] || new Set()).forEach(other => {
          if (depth[other] === undefined) { depth[other] = depth[id] + 1; next.push(other); }
        });
      });
      frontier = next;
    }
    nodes.forEach(n => { if (depth[n.id] === undefined) depth[n.id] = 9; });
    return depth;
  }

  /**
   * Orbit — the galaxy view.
   *
   * The focus sits at the centre. Everything one hop away sits on the first
   * ring, two hops on the second, and the ring is divided into sectors by
   * entity type so like is next to like: people with people, institutions with
   * institutions. Within a sector a node's place is fixed by its id, so the
   * same neighbourhood always draws the same way — a diagram you can learn.
   */
  function orbitLayout(nodes, edges, focusId, W, H) {
    const depth = hopDepths(nodes, edges, focusId);
    const cx = W / 2, cy = H / 2;
    const rings = {};
    nodes.forEach(n => {
      const d = Math.min(2, depth[n.id] || 0);
      (rings[d] = rings[d] || []).push(n);
    });
    (rings[0] || []).forEach(n => { n.x = cx; n.y = cy; n.hop = 0; });

    /* the ring is an ellipse, so a wide stage is used across and a tall one
       down: the neighbourhood fills the frame instead of huddling in it */
    const rx = Math.max(130, W / 2 - 118);
    const ry = Math.max(96, H / 2 - 76);
    [1, 2].forEach(ring => {
      const list = rings[ring] || [];
      if (!list.length) return;
      const ordered = list.slice().sort((a, b) => {
        const ta = TYPE_ORDER.indexOf(a.type), tb = TYPE_ORDER.indexOf(b.type);
        if (ta !== tb) return ta - tb;
        return String(a.label || "").localeCompare(String(b.label || ""));
      });
      /* two bands per ring: a crowded orbit read as a single circle puts every
         name in the same annulus, where they can only overlap */
      const bands = ring === 1 ? [0.58, 0.80] : [0.90, 1.0];
      const step = (Math.PI * 2) / Math.max(ordered.length, 1);
      ordered.forEach((n, i) => {
        const k = bands[i % bands.length];
        const ang = -Math.PI / 2 + i * step;
        n.x = cx + Math.cos(ang) * rx * k;
        n.y = cy + Math.sin(ang) * ry * k;
        n.hop = ring;
      });
    });
    // a light relaxation so long labels on a crowded ring do not overlap
    const all = nodes.slice();
    for (let step = 0; step < 60; step++) {
      for (let i = 0; i < all.length; i++) {
        for (let j = i + 1; j < all.length; j++) {
          const a = all[i], b = all[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          const d = Math.hypot(dx, dy) || 0.01;
          const gap = 46 + 0.35 * ((a.r || 20) + (b.r || 20));
          if (d < gap) {
            const push = (gap - d) / 2 * 0.45;
            dx /= d; dy /= d;
            a.x -= dx * push * 6; a.y -= dy * push * 6;
            b.x += dx * push * 6; b.y += dy * push * 6;
          }
        }
      }
    }
    // keep the focus exactly at the centre
    nodes.forEach(n => {
      if (n.id === focusId) { n.x = cx; n.y = cy; }
      n.x = clamp(n.x, 74, W - 74);
      n.y = clamp(n.y, 52, H - 52);
    });
    return { depth, rings: [{ rx: rx * 0.62, ry: ry * 0.62 }, { rx, ry }] };
  }

  /**
   * Force — a deterministic spring layout for dense neighbourhoods.
   *
   * Fixed iteration count, seeded on a circle by type: the same data always
   * settles into the same shape. No animation, no jitter, no "it looked
   * different yesterday".
   */
  /**
   * Push glyphs apart until a clear gap remains between them.
   * The focus, when there is one, stays where it was put.
   */
  function separateNodes(nodes, gap, fixedId) {
    const held = (id) => fixedId != null &&
      (typeof fixedId.has === "function" ? fixedId.has(id) : id === fixedId);
    const rounds = nodes.length > 80 ? 28 : 16;
    for (let step = 0; step < rounds; step++) {
      let moved = false;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          const d = Math.hypot(dx, dy) || 0.01;
          const need = (a.r || 16) + (b.r || 16) + gap;
          if (d >= need) continue;
          moved = true;
          const push = (need - d) * 0.5;
          dx /= d; dy /= d;
          const aFixed = held(a.id), bFixed = held(b.id);
          if (aFixed && bFixed) continue;
          if (aFixed) { b.x += dx * push * 2; b.y += dy * push * 2; }
          else if (bFixed) { a.x -= dx * push * 2; a.y -= dy * push * 2; }
          else {
            a.x -= dx * push; a.y -= dy * push;
            b.x += dx * push; b.y += dy * push;
          }
        }
      }
      if (!moved) break;
    }
  }

  /**
   * A full roster, read as one diagram: each record type is its own band,
   * and inside a band every record is a glyph with its name beside it.
   * The gap is fixed and small. The frame grows taller instead of closing
   * that gap to squeeze everyone into one screen.
   */
  function layoutRoster(nodes, W) {
    const R = 14;
    const nameW = 156;
    const gapN = 10;
    const gapX = 18;
    const gapY = 16;
    const padX = 28, padY = 22;
    const lane = 40;
    const rtl = lang() === "ar";
    const chipW = R * 2 + gapN + nameW;
    const rowH = R * 2 + gapY;
    const innerW = Math.max(chipW, W - padX * 2);
    const cols = Math.max(1, Math.floor((innerW + gapX) / (chipW + gapX)));
    const rowSpan = cols * chipW + Math.max(0, cols - 1) * gapX;
    const xStart = padX + Math.max(0, (innerW - rowSpan) / 2);
    const glyphInChip = rtl ? (nameW + gapN + R) : R;

    const byType = {};
    nodes.forEach(n => {
      n.r = R;
      n.rosterLabel = true;
      n.vx = 0; n.vy = 0;
      (byType[n.type] = byType[n.type] || []).push(n);
    });
    const order = TYPE_ORDER.filter(t => byType[t])
      .concat(Object.keys(byType).filter(t => TYPE_ORDER.indexOf(t) < 0));

    let y = padY;
    const bands = [];
    order.forEach((t, ti) => {
      const list = byType[t];
      list.sort((a, b) => String(a.label || "").localeCompare(
        String(b.label || ""), undefined, { sensitivity: "base" }));
      const rows = Math.ceil(list.length / cols);
      const head = 26;
      const top = y + head;
      const body = rows * rowH - gapY;
      bands.push({
        type: t,
        x: padX - 6,
        y: y,
        w: innerW + 12,
        h: head + body + 14
      });
      list.forEach((n, i) => {
        const col = i % cols, row = Math.floor(i / cols);
        /* the first name of a row sits at the start of the line */
        const slot = rtl ? (cols - 1 - col) : col;
        n.x = xStart + glyphInChip + slot * (chipW + gapX);
        n.y = top + R + row * rowH;
        n.rosterRtl = rtl;
      });
      y += head + body + 14 + (ti < order.length - 1 ? lane : 0);
    });
    return { w: Math.max(W, padX * 2 + rowSpan), h: y + padY, bands };
  }

  function forceLayout(nodes, edges, focusId, W, H) {
    const cx = W / 2, cy = H / 2;
    const n = Math.max(1, nodes.length);
    nodes.forEach(nd => { nd.r = glyphRadius(nd, focusId, n); });
    const crowded = n > 36;

    if (crowded) {
      const laid = layoutRoster(nodes, W);
      return {
        depth: hopDepths(nodes, edges, focusId),
        rings: [],
        w: laid.w, h: laid.h, bands: laid.bands
      };
    }
    {
      nodes.forEach((node, i) => {
        const ang = -Math.PI / 2 + (i * 2 * Math.PI) / n;
        const ring = Math.min(W, H) * (0.22 + 0.20 * (i % 3) / 3);
        node.x = cx + Math.cos(ang) * ring * 1.35;
        node.y = cy + Math.sin(ang) * ring;
        node.vx = 0; node.vy = 0;
      });
    }

    const index = {};
    nodes.forEach(nd => { index[nd.id] = nd; });
    const links = edges.map(e => [index[e.source], index[e.target]]).filter(p => p[0] && p[1]);
    const ideal = crowded
      ? 64
      : Math.sqrt((W * H) / n) * 0.72;
    const home = nodes.map(nd => ({ x: nd.x, y: nd.y }));
    const steps = crowded ? 48 : 280;

    for (let step = 0; step < steps; step++) {
      const cool = 1 - step / steps;
      if (!crowded) {
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            let dx = b.x - a.x, dy = b.y - a.y;
            const d2 = dx * dx + dy * dy || 0.01;
            if (d2 > ideal * ideal * 16) continue;
            const d = Math.sqrt(d2);
            const f = (ideal * ideal) / d * 0.018;
            dx /= d; dy /= d;
            a.vx -= dx * f; a.vy -= dy * f;
            b.vx += dx * f; b.vy += dy * f;
          }
        }
      }
      const spring = crowded ? 0.0016 : 0.012;
      links.forEach(([a, b]) => {
        let dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.hypot(dx, dy) || 0.01;
        const pull = Math.max(-1.4, Math.min(1.4, (d - ideal) * spring));
        dx /= d; dy /= d;
        if (a.id !== focusId) { a.vx += dx * pull; a.vy += dy * pull; }
        if (b.id !== focusId) { b.vx -= dx * pull; b.vy -= dy * pull; }
      });
      const hold = crowded ? 0.08 : 0;
      nodes.forEach((nd, i) => {
        if (nd.id === focusId) { nd.vx = nd.vy = 0; nd.x = cx; nd.y = cy; return; }
        if (!crowded) {
          nd.vx += (cx - nd.x) * 0.0014 * cool;
          nd.vy += (cy - nd.y) * 0.0014 * cool;
        } else {
          nd.vx += (home[i].x - nd.x) * hold;
          nd.vy += (home[i].y - nd.y) * hold;
        }
        const limit = crowded ? 3 : 22;
        nd.x += clamp(nd.vx, -limit, limit) * (crowded ? 1 : cool);
        nd.y += clamp(nd.vy, -limit, limit) * (crowded ? 1 : cool);
        nd.vx *= 0.7; nd.vy *= 0.7;
        if (!crowded) {
          nd.x = clamp(nd.x, 82, W - 82);
          nd.y = clamp(nd.y, 60, H - 60);
        }
      });
    }
    /* a small, even gap, then keep everyone inside the frame */
    separateNodes(nodes, 16, focusId);
    nodes.forEach(nd => {
      if (nd.id === focusId) { nd.x = cx; nd.y = cy; return; }
      nd.x = clamp(nd.x, 70, W - 70);
      nd.y = clamp(nd.y, 52, H - 52);
    });
    if (focusId) separateNodes(nodes, 14, focusId);
    return { depth: hopDepths(nodes, edges, focusId), rings: [] };
  }

  /* ======================================================================
     the scene
     ====================================================================== */
  function edgeGeometry(a, b, curved) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    // stop at the glyph edge so the arrowhead is visible, not buried
    const padA = (a.r || 22) + 2, padB = (b.r || 22) + 8;
    const x1 = a.x + (dx / len) * padA, y1 = a.y + (dy / len) * padA;
    const x2 = b.x - (dx / len) * padB, y2 = b.y - (dy / len) * padB;
    if (!curved) return { d: `M${x1} ${y1} L${x2} ${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
    // a gentle bow, always the same side, so reciprocal edges stay distinct
    const nx = -(y2 - y1), ny = (x2 - x1);
    const bow = Math.min(46, Math.hypot(x2 - x1, y2 - y1) * 0.13);
    const cx = (x1 + x2) / 2 + (nx / len) * bow;
    const cy = (y1 + y2) / 2 + (ny / len) * bow;
    return { d: `M${x1} ${y1} Q${cx} ${cy} ${x2} ${y2}`, mx: cx, my: cy };
  }

  /* Labels are placed, not sprayed: a short greedy pass over candidate slots
     (right, left, above, below, and the four diagonals) keeps names legible on
     a crowded orbit instead of stacking them on top of one another. */
  function textWidth(text, size) {
    let w = 0;
    for (const ch of String(text)) {
      if (/[\u0600-\u06FF]/.test(ch)) w += size * 0.52;
      else if (/[ilj.,'\u2019|]/.test(ch)) w += size * 0.30;
      else if (/[MWmw@]/.test(ch)) w += size * 0.92;
      else w += size * 0.56;
    }
    return w;
  }
  function boxesClash(a, b, pad) {
    return !(a.x2 + pad < b.x1 || b.x2 + pad < a.x1 ||
             a.y2 + pad < b.y1 || b.y2 + pad < a.y1);
  }
  function placeLabel(n, text, blocked) {
    const size = n.isFocus ? 13.5 : 12;
    const w = textWidth(text, size);
    const h = size * 1.3;
    const gap = n.r + 10;
    const slots = [
      [gap, 4, "start"], [-gap, 4, "end"],
      [0, -(n.r + 13), "middle"], [0, n.r + 18, "middle"],
      [gap * 0.72, -(n.r * 0.72) - 3, "start"], [-gap * 0.72, -(n.r * 0.72) - 3, "end"],
      [gap * 0.72, n.r * 0.72 + 5, "start"], [-gap * 0.72, n.r * 0.72 + 5, "end"]
    ];
    for (const [ax, ay, anchorKind] of slots) {
      const cx = n.x + ax, cy = n.y + ay;
      const x1 = anchorKind === "start" ? cx : (anchorKind === "end" ? cx - w : cx - w / 2);
      const box = { x1, x2: x1 + w, y1: cy - h * 0.78, y2: cy + h * 0.28 };
      if (box.x1 < 4 || box.x2 > W - 4 || box.y1 < 2 || box.y2 > H - 2) continue;
      if (blocked.some(b => boxesClash(box, b, 3))) continue;
      blocked.push(box);
      return { x: cx, y: cy, anchor: anchorKind, dim: false };
    }
    /* nowhere free: keep it, but quietly, so hover and the tooltip carry it */
    return { x: n.x + gap, y: n.y + 4, anchor: "start", dim: true };
  }

  function buildScene(opts) {
    const { nodes, edges, focusId, layout, selection, path, W, H } = opts;
    const index = {};
    nodes.forEach(n => { index[n.id] = n; });
    const curved = layout === "orbit";
    const rings = opts.rings || [];

    const ringSvg = (layout === "orbit" && rings.length)
      ? rings.map(r => `<ellipse class="atlas-ring" cx="${W / 2}" cy="${H / 2}"
            rx="${r.rx}" ry="${r.ry}"/>`).join("")
      : "";

    /* ---- preparation: glyph sizes first, then the names ------------------
       Labels are not decoration: they are the reading. So the scene is
       prepared in two moves — size the glyphs, settle where every name goes —
       and only then draw the lines and the glyphs. A drag later moves one
       unit: the glyph and its name share a transform, and every line that
       touches that glyph is redrawn onto the same centre. */

    /* pass one: size the glyphs — everything that follows depends on it */
    const crowd = nodes.length > 60;
    nodes.forEach(n => {
      n.isFocus = n.id === focusId;
      n.r = glyphRadius(n, focusId, nodes.length);
    });
    const loud = new Set();
    if (crowd) {
      nodes.slice().sort((a, b) => (b.degree || 0) - (a.degree || 0) || (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0))
        .slice(0, 24).forEach(n => loud.add(n.id));
      nodes.forEach(n => { if (n.pinned || n.isFocus) loud.add(n.id); });
    }

    const blocked = nodes.map(n => ({ x1: n.x - n.r - 2, x2: n.x + n.r + 2,
                                      y1: n.y - n.r - 2, y2: n.y + n.r + 2 }));
    /* the zoom controls and the find box float over the top of the stage;
       a label underneath them would be a label nobody can read */
    blocked.push({ x1: 0, x2: W, y1: 0, y2: 54 });

    const order = nodes.slice().sort((a, b) =>
      (b.isFocus ? 1 : 0) - (a.isFocus ? 1 : 0) || (b.degree || 0) - (a.degree || 0));
    order.forEach(n => {
      n.quietLabel = crowd && !n.rosterLabel && !loud.has(n.id);
      n.labelText = shortLabel(n.label, n.isFocus ? 52 : (n.rosterLabel ? 28 : (crowd ? 34 : 42)));
      /* A reserved mark fills its disc: the count cannot sit inside it without
         covering the geometry that carries the standard's meaning, so for the
         three covered categories the count joins the name and is placed,
         measured and collision-tested with it. */
      if (CRCE_CATEGORY[n.type] && (n.degree || 0) > 0) {
        n.labelText += " · " + compactNum(n.degree);
      }
      if (n.isFocus) {
        /* the centre keeps its name — the one label a reader looks for first,
           so everything else steers around it. Long names wrap to two lines,
           and the block sits below the glyph (above it only if something is
           already there). */
        let fw = textWidth(n.labelText, 13.5);
        if (fw > W * 0.32) {
          const words = String(n.labelText).split(/\s+/);
          let a = "", b = "";
          words.forEach(w => {
            if (!b && textWidth(a + " " + w, 13.5) < W * 0.28) a = (a ? a + " " : "") + w;
            else b = (b ? b + " " : "") + w;
          });
          if (a && b) {
            n.labelText = a + "\u2028" + b;
            fw = Math.max(textWidth(a, 13.5), textWidth(b, 13.5));
          }
        }
        const lines = n.labelText.split("\u2028").length;
        const lh = 15 * (lines - 1) + 24;
        const below = { x1: n.x - fw / 2, x2: n.x + fw / 2,
                        y1: n.y + n.r + 2, y2: n.y + n.r + lh + 2 };
        const above = { x1: n.x - fw / 2, x2: n.x + fw / 2,
                        y1: n.y - n.r - lh - 2, y2: n.y - n.r - 2 };
        const busy = (box) => blocked.some(b => boxesClash(box, b, 2));
        const dir = busy(below) && !busy(above) ? -1 : 1;
        const box = dir < 0 ? above : below;
        n.focusLabel = { x: n.x, y: dir < 0 ? n.y - n.r - lh + 4 : n.y + n.r + 18 };
        blocked.push(box);
      } else if (n.rosterLabel) {
        n.labelText = fitLabel(n.labelText, 15.5, 148);
        /* Arabic grows leftward from the anchor, so the name sits just
           before the glyph; English grows rightward, just after it. */
        const gap = n.r + 10;
        n.place = n.rosterRtl
          ? { x: n.x - gap, y: n.y + 5, anchor: "start", dim: false }
          : { x: n.x + gap, y: n.y + 5, anchor: "start", dim: false };
        n.labelDir = n.rosterRtl ? "rtl" : "ltr";
      } else if (n.quietLabel) {
        n.place = { x: n.x + n.r + 8, y: n.y + 4, anchor: "start", dim: false };
      } else {
        n.place = placeLabel(n, n.labelText, blocked);
      }
    });

    const edgeSvg = edges.map(e => {
      const a = index[e.source], b = index[e.target];
      if (!a || !b) return "";
      const g = edgeGrammar(e);
      const geo = edgeGeometry(a, b, curved);
      const label = pick(e.label_en, e.label_ar);
      const tip = `${label} — ${pick(e.verification_en, e.verification_ar) || e.verification}` +
        (e.ended ? " · " + t("atlas.ended") : "") +
        (e.evidence_count ? ` · ${e.evidence_count} ${t("atlas.evidence")}` : "");
      const onPath = path && path.edges && path.edges.has(String(e.id));
      /* The name is in the drawing always, and shown only while this
         relationship is the one being read. */
      return `<g class="rm-edge${onPath ? " on-path" : ""}" data-edge="${esc(e.id)}"
                 role="button" tabindex="0" aria-label="${esc(tip)}">
        <path data-s="${esc(a.id)}" data-t="${esc(b.id)}" data-shape="${curved ? "curve" : "line"}"
              d="${geo.d}" stroke="transparent" stroke-width="16" fill="none"/>
        <path class="rm-edge-line" d="${geo.d}" fill="none"
              stroke="${g.colour}" stroke-opacity="${g.opacity}"
              stroke-width="1.7" pointer-events="none"
              ${g.dash ? `stroke-dasharray="${g.dash}"` : ""}${g.marker}/>
        <text class="atlas-edge-label" x="${geo.mx}" y="${geo.my - 5}"
            text-anchor="middle" direction="auto">${esc(shortLabel(label, 28))}</text>
        <title>${esc(tip)}</title>
      </g>`;
    }).join("");

    const nodeSvg = nodes.map(n => {
      const style = TYPE_STYLE[n.type] || TYPE_STYLE.person;
      const isFocus = n.isFocus;
      const r = n.r;
      const label = n.labelText;
      const place = n.place || { x: n.x, y: (n.focusLabel || {}).y || n.y + r + 20,
                                anchor: "middle", dim: false };
      /* name coordinates are local to the node, so the glyph and the name
         are one object: translating the group carries both */
      const lx = place.x - n.x, ly = place.y - n.y, anchor = isFocus ? "middle" : place.anchor;
      const isSel = selection && selection.kind === "node" && selection.id === n.id;
      const onPath = path && path.nodes && path.nodes.has(n.id);
      return `<g class="map-node atlas-node${isFocus ? " is-focus" : ""}${isSel ? " is-selected" : ""}${onPath ? " on-path" : ""}"
                 transform="translate(${n.x} ${n.y})"
                 data-nid="${esc(n.id)}" data-type="${esc(n.type)}" data-record="${n.record_id}"
                 data-x="${n.x}" data-y="${n.y}" data-r="${r}" data-label="${esc(n.label || "")}"
                 data-weight="${n.degree || 0}"
                 role="button" tabindex="0"
                 aria-label="${esc(n.label)} — ${esc(A.label(n.type))}">
        <g class="atlas-body">
          <circle class="atlas-halo" r="${r + 12}"/>
          ${(() => {
            const cat = CRCE_CATEGORY[n.type];
            const mark = cat ? rosette(cat, r, style.color) : null;
            return mark || glyph(style, 0, 0, r, "atlas-glyph");
          })()}
          ${(n.degree || 0) > 0 && !CRCE_CATEGORY[n.type] && r >= 16
            ? `<text class="atlas-count" y="4" text-anchor="middle">${compactNum(n.degree)}</text>`
            : ""}
          <circle class="node-hit" r="${r + 6}" fill="transparent"/>
        </g>
        <text class="map-label atlas-label${n.quietLabel ? " is-quiet" : ""}${place.dim ? " is-dim" : ""}" x="${lx}" y="${ly}"
              text-anchor="${anchor}" direction="${n.labelDir || "auto"}"
              style="font-weight:${isFocus ? 700 : 600}">${label.split("\u2028").map((line, i) =>
                i ? `<tspan x="${lx}" dy="15">${esc(line)}</tspan>` : esc(line)).join("")}</text>
        <title>${esc(n.label)} — ${esc(A.label(n.type))} · ${num(n.degree || 0)}</title>
      </g>`;
    }).join("");

    const bands = opts.bands || [];
    const bandSvg = bands.map(b => {
      const style = TYPE_STYLE[b.type] || TYPE_STYLE.person;
      return `<g class="atlas-band" pointer-events="none">
        <rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="12"
              fill="${style.color}" fill-opacity=".045" stroke="${style.color}" stroke-opacity=".16"/>
        <text class="atlas-band-label" x="${lang() === "ar" ? b.x + b.w - 14 : b.x + 14}" y="${b.y + 18}"
              fill="${style.color}" text-anchor="start"
              direction="${lang() === "ar" ? "rtl" : "ltr"}">${esc(A.label(b.type))}</text>
      </g>`;
    }).join("");

    return `<svg viewBox="0 0 ${W} ${H}" class="relmap atlas-svg${nodes.length > 60 ? " is-roster" : ""}" role="img" tabindex="0"
              aria-label="${esc(t("map.focusTitle"))}">
      <defs>
        <marker id="relmap-arrow" viewBox="0 0 10 10" refX="8" refY="5"
                markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0L10 5 0 10z" fill="#789088"/>
        </marker>
        <radialGradient id="atlas-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#c9a227" stop-opacity=".10"/>
          <stop offset="100%" stop-color="#c9a227" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <rect class="rm-hit" x="0" y="0" width="${W}" height="${H}" fill="transparent"/>
      <circle class="atlas-glow" cx="${W / 2}" cy="${H / 2}" r="${Math.min(W, H) * 0.46}"
              fill="url(#atlas-glow)" pointer-events="none"/>
      <g class="rm-cam">
        <g class="atlas-rings">${ringSvg}</g>
        <g class="atlas-bands">${bandSvg}</g>
        <g class="atlas-stage" pointer-events="none">
          <circle class="atlas-stage-fill" cx="0" cy="0" r="0"/>
          <circle class="atlas-stage-ring" cx="0" cy="0" r="0"/>
        </g>
        <g class="relmap-edges">${edgeSvg}</g>
        <g class="relmap-nodes">${nodeSvg}</g>
      </g>
    </svg>`;
  }

  /** The matrix: rows and columns are records, a cell is the evidence between them. */
  function matrixView(nodes, edges, focusId, selection) {
    const limit = 34;
    const list = nodes.slice().sort((a, b) => {
      if (a.id === focusId) return -1;
      if (b.id === focusId) return 1;
      return (b.degree || 0) - (a.degree || 0) ||
        String(a.label).localeCompare(String(b.label));
    }).slice(0, limit);
    const keep = new Set(list.map(n => n.id));
    const cell = {};
    edges.forEach(e => {
      if (!keep.has(e.source) || !keep.has(e.target)) return;
      const key = `${e.source}|${e.target}`;
      (cell[key] = cell[key] || []).push(e);
    });
    const head = list.map((n, i) =>
      `<th scope="col" title="${esc(n.label)}"><span class="mx-idx">${i + 1}</span></th>`).join("");
    const rows = list.map((a, i) => {
      const cells = list.map(b => {
        const hits = cell[`${a.id}|${b.id}`] || [];
        if (!hits.length) return `<td class="mx-cell empty"></td>`;
        const strongest = hits.slice().sort((x, y) =>
          (y.evidence_count || 0) - (x.evidence_count || 0))[0];
        const contradicted = hits.some(h => h.contradicted);
        const strength = Math.min(1, 0.28 + 0.22 * hits.length +
          (strongest.evidence_count || 0) * 0.12);
        const sel = selection && selection.kind === "edge" &&
          hits.some(h => String(h.id) === String(selection.id));
        const title = hits.map(h =>
          `${pick(h.label_en, h.label_ar)} — ${pick(h.verification_en, h.verification_ar)}`
          + (h.ended ? " · " + t("atlas.ended") : "")).join("\n");
        return `<td class="mx-cell${contradicted ? " contradicts" : ""}${sel ? " selected" : ""}"
                    data-edge="${esc(strongest.id)}" data-n="${hits.length}" title="${esc(title)}"
                    style="--mx:${strength.toFixed(2)}"><span>${hits.length > 1 ? hits.length : ""}</span></td>`;
      }).join("");
      return `<tr><th scope="row" title="${esc(a.label)}">
          <span class="mx-idx">${i + 1}</span>
          <span class="mx-name" data-nid="${esc(a.id)}">${esc(shortLabel(a.label, 26))}</span></th>${cells}</tr>`;
    }).join("");
    return `<div class="atlas-matrix">
      <div class="table-wrap"><table class="mx-table">
        <thead><tr><th class="mx-corner"></th>${head}</tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="mx-note small muted">${esc(t("atlas.matrixNote"))}</p>
    </div>`;
  }

  /* ------------------------------------------------------------------ edges --- */
  function edgeGrammar(e) {
    const dash = A.verifDash ? A.verifDash(e.verification) : VERIF_DASH(e.verification);
    return {
      dash,
      opacity: e.ended ? 0.30 : (e.contradicted ? 0.9 : 0.62),
      marker: e.directed === false ? "" : ' marker-end="url(#relmap-arrow)"',
      colour: e.contradicted ? "#b4503f" : (e.ended ? "#8b8f96" : "#789088")
    };
  }

  function VERIF_DASH(code) {
    const c = String(code || "unverified");
    if (["corroborated", "primary_document", "institutionally_confirmed"].includes(c)) return "";
    if (["single_source", "self_declared"].includes(c)) return "7 5";
    return "2 5";
  }

  /* ======================================================================
     the canvas — pan · zoom · drag · fly-to · hover · keyboard
     (unchanged mechanics: one transform, one rAF, no reflow while dragging)
     ====================================================================== */
  const MIN_K = 0.25, MAX_K = 6;

  function attachCanvas(svg, host, hooks) {
    hooks = hooks || {};
    const g = svg.querySelector(".rm-cam");
    const vb = svg.viewBox.baseVal;
    const W = vb.width || 1040, H = vb.height || 620;
    const cam = { x: 0, y: 0, k: 1 };
    const pos = {};
    const edges = [];
    let raf = null, animating = null, panning = null, dragging = null, inertia = null, glideRaf = null;
    let panLast = { x: 0, y: 0, x0: 0, y0: 0 };

    svg.querySelectorAll(".map-node").forEach(a => {
      pos[a.dataset.nid] = { x: Number(a.dataset.x) || 0, y: Number(a.dataset.y) || 0 };
    });
    svg.querySelectorAll(".rm-edge").forEach(g => {
      const hit = g.querySelector("[data-s]");
      if (!hit) return;
      edges.push({
        g, hit,
        line: g.querySelector(".rm-edge-line"),
        label: g.querySelector(".atlas-edge-label"),
        s: hit.dataset.s, t: hit.dataset.t, shape: hit.dataset.shape
      });
    });

    function schedule() {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = null;
        g.setAttribute("transform",
          `translate(${cam.x.toFixed(2)} ${cam.y.toFixed(2)}) scale(${cam.k.toFixed(4)})`);
        if (hooks.onCam) hooks.onCam(cam);
      });
    }

    function toDiagram(clientX, clientY) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return { x: 0, y: 0 };
      const pt = svg.createSVGPoint();
      pt.x = clientX; pt.y = clientY;
      const p = pt.matrixTransform(ctm.inverse());
      return { x: (p.x - cam.x) / cam.k, y: (p.y - cam.y) / cam.k };
    }

    function animateTo(target, ms) {
      if (animating) cancelAnimationFrame(animating.raf);
      const from = { x: cam.x, y: cam.y, k: cam.k };
      const to = {
        x: target.x != null ? target.x : cam.x,
        y: target.y != null ? target.y : cam.y,
        k: clamp(target.k != null ? target.k : cam.k, MIN_K, MAX_K)
      };
      const t0 = performance.now(), dur = ms || 340;
      animating = { raf: 0 };
      const step = (now) => {
        const p = clamp((now - t0) / dur, 0, 1), e = easeOutCubic(p);
        cam.x = from.x + (to.x - from.x) * e;
        cam.y = from.y + (to.y - from.y) * e;
        cam.k = from.k + (to.k - from.k) * e;
        schedule();
        if (p < 1) animating.raf = requestAnimationFrame(step);
        else animating = null;
      };
      animating.raf = requestAnimationFrame(step);
    }

    function contentBox() {
      try {
        const b = g.getBBox();
        if (!b.width || !b.height) return { x: 0, y: 0, w: W, h: H };
        return { x: b.x, y: b.y, w: b.width, h: b.height };
      } catch (e) { return { x: 0, y: 0, w: W, h: H }; }
    }

    function clampPan() {
      const b = contentBox();
      const keepX = (W / cam.k) * 0.28, keepY = (H / cam.k) * 0.28;
      const minTx = -cam.k * (b.x + b.w - keepX);
      const maxTx = W - cam.k * (b.x + keepX);
      const minTy = -cam.k * (b.y + b.h - keepY);
      const maxTy = H - cam.k * (b.y + keepY);
      cam.x = minTx <= maxTx ? clamp(cam.x, minTx, maxTx) : (minTx + maxTx) / 2;
      cam.y = minTy <= maxTy ? clamp(cam.y, minTy, maxTy) : (minTy + maxTy) / 2;
    }

    function fit(ms) {
      const b = contentBox(), pad = 30;
      const k = clamp(Math.min((W - pad * 2) / Math.max(1, b.w),
                               (H - pad * 2) / Math.max(1, b.h)), MIN_K, MAX_K);
      animateTo({ x: (W - b.w * k) / 2 - b.x * k, y: (H - b.h * k) / 2 - b.y * k, k }, ms);
    }

    function zoomBy(factor, cx, cy, ms) {
      const px = cx == null ? W / 2 : cx, py = cy == null ? H / 2 : cy;
      const k2 = clamp(cam.k * factor, MIN_K, MAX_K);
      const r = k2 / cam.k;
      animateTo({ k: k2, x: px - (px - cam.x) * r, y: py - (py - cam.y) * r }, ms || 200);
    }

    function nodeOrigin(node) {
      const tr = node && node.getAttribute("transform") || "";
      const m = /translate\(\s*([-\d.]+)[\s,]+([-\d.]+)\s*\)/.exec(tr);
      if (m) return { x: Number(m[1]), y: Number(m[2]) };
      return {
        x: Number(node && node.dataset.x) || 0,
        y: Number(node && node.dataset.y) || 0
      };
    }

    function placeNode(node, x, y) {
      node.setAttribute("transform", `translate(${x} ${y})`);
      node.dataset.x = x;
      node.dataset.y = y;
      if (node.dataset.nid && pos[node.dataset.nid]) {
        pos[node.dataset.nid].x = x;
        pos[node.dataset.nid].y = y;
      }
    }

    function flyTo(nid, k) {
      const node = svg.querySelector(`.map-node[data-nid="${CSS.escape(String(nid))}"]`);
      const p = node ? nodeOrigin(node) : pos[nid];
      if (!p) return false;
      const kk = clamp(k || Math.max(cam.k, 1.8), MIN_K, MAX_K);
      animateTo({ k: kk, x: W / 2 - p.x * kk, y: H / 2 - p.y * kk });
      return true;
    }

    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const anchor = toDiagram(ev.clientX, ev.clientY);
      const screenX = anchor.x * cam.k + cam.x;
      const screenY = anchor.y * cam.k + cam.y;
      const unit = ev.deltaMode === 1 ? 18 : (ev.deltaMode === 2 ? 320 : 1);
      const factor = Math.exp(-ev.deltaY * unit * (ev.ctrlKey ? 0.0045 : 0.0017));
      cam.k = clamp(cam.k * factor, MIN_K, MAX_K);
      cam.x = screenX - anchor.x * cam.k;
      cam.y = screenY - anchor.y * cam.k;
      schedule();
    }, { passive: false });

    svg.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      if (glideRaf) { cancelAnimationFrame(glideRaf); glideRaf = null; }
      const node = ev.target.closest && ev.target.closest(".map-node");
      if (node && !ev.ctrlKey && !ev.metaKey) { dragging = startNodeDrag(ev, node); return; }
      /* A link is part of the relationship, not empty canvas. Grabbing it
         moves both ends together; a click that does not travel still opens
         the record, because we never capture the pointer. */
      const edge = ev.target.closest && ev.target.closest(".rm-edge");
      if (edge && !ev.ctrlKey && !ev.metaKey) { dragging = startLinkDrag(ev, edge); return; }
      if (animating) { cancelAnimationFrame(animating.raf); animating = null; }
      if (inertia) { cancelAnimationFrame(inertia); inertia = null; }
      svg.setPointerCapture(ev.pointerId);
      panning = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, camX: cam.x, camY: cam.y,
                  last: performance.now(), vx: 0, vy: 0 };
      panLast = { x: ev.clientX, y: ev.clientY, x0: ev.clientX, y0: ev.clientY };
      svg.classList.add("is-panning");
    });

    svg.addEventListener("pointermove", (ev) => {
      if (panning) {
        const ctm = svg.getScreenCTM();
        const scale = ctm ? ctm.a : 1;
        const dx = (ev.clientX - panning.x) / (scale || 1);
        const dy = (ev.clientY - panning.y) / (scale || 1);
        const now = performance.now();
        const dt = Math.max(1, now - panning.last);
        panning.vx = dx / dt * 16; panning.vy = dy / dt * 16;
        panning.last = now;
        panLast.x = ev.clientX; panLast.y = ev.clientY;
        cam.x = panning.camX + dx;
        cam.y = panning.camY + dy;
        clampPan();
        schedule();
        return;
      }
      if (dragging) moveNode(ev);
    });

    function endPointer() {
      if (panning) {
        const vx = panning.vx, vy = panning.vy;
        panning = null;
        svg.classList.remove("is-panning");
        if (Math.abs(panLast.x - panLast.x0) + Math.abs(panLast.y - panLast.y0) > 3) {
          svg.__suppressClick = true;
          setTimeout(() => { svg.__suppressClick = false; }, 320);
        }
        if (Math.hypot(vx, vy) > 1.2) {
          let vX = vx, vY = vy;
          const step = () => {
            vX *= 0.90; vY *= 0.90;
            cam.x += vX; cam.y += vY;
            clampPan();
            schedule();
            if (Math.abs(vX) + Math.abs(vY) > 0.25) inertia = requestAnimationFrame(step);
            else inertia = null;
          };
          inertia = requestAnimationFrame(step);
        }
      }
      if (dragging) { finishNodeDrag(); dragging = null; }
    }
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("pointerleave", (ev) => {
      if (panning && !svg.hasPointerCapture(ev.pointerId)) endPointer();
    });

    function startNodeDrag(ev, node) {
      const p = toDiagram(ev.clientX, ev.clientY);
      const off = nodeOrigin(node);
      /* the selection and the records gathered around it travel as one group */
      const pack = [];
      if (node.classList.contains("is-selected")) {
        svg.querySelectorAll(".map-node.is-near").forEach(other => {
          const o = nodeOrigin(other);
          pack.push({ node: other, id: other.dataset.nid, offX: o.x, offY: o.y });
        });
      }
      return { kind: "node", node, id: node.dataset.nid, startX: p.x, startY: p.y,
               offX: off.x, offY: off.y, moved: false, pack };
    }
    function startLinkDrag(ev, edge) {
      const hit = edge.querySelector("[data-s]");
      if (!hit) return null;
      const p = toDiagram(ev.clientX, ev.clientY);
      const ends = [];
      const seen = new Set();
      [hit.dataset.s, hit.dataset.t].forEach(id => {
        if (!id || seen.has(id)) return;
        seen.add(id);
        const node = svg.querySelector(`.map-node[data-nid="${CSS.escape(String(id))}"]`);
        if (!node) return;
        const off = nodeOrigin(node);
        ends.push({ node, id, offX: off.x, offY: off.y });
      });
      if (!ends.length) return null;
      return { kind: "link", edge, ends, startX: p.x, startY: p.y, moved: false };
    }
    function moveNode(ev) {
      if (!dragging) return;
      const p = toDiagram(ev.clientX, ev.clientY);
      const dx = p.x - dragging.startX, dy = p.y - dragging.startY;
      if (!dragging.moved && Math.hypot(dx, dy) * cam.k < 3) return;
      dragging.moved = true;
      svg.classList.add("is-dragging");
      const moved = new Set();
      if (dragging.kind === "link") {
        /* the relationship travels as one piece: both shapes, both names,
           and the link between them keep the distance they already had */
        dragging.ends.forEach(end => {
          placeNode(end.node, end.offX + dx, end.offY + dy);
          moved.add(end.id);
        });
      } else {
        placeNode(dragging.node, dragging.offX + dx, dragging.offY + dy);
        moved.add(dragging.id);
        (dragging.pack || []).forEach(end => {
          placeNode(end.node, end.offX + dx, end.offY + dy);
          moved.add(end.id);
        });
      }
      moved.forEach(id => rerouteEdges(id));
    }
    function finishNodeDrag() {
      if (dragging && dragging.moved) {
        svg.__suppressClick = true;
        setTimeout(() => { svg.__suppressClick = false; }, 320);
        if (dragging.node) dragging.node.dataset.dragged = "1";
        if (dragging.edge) dragging.edge.dataset.dragged = "1";
      }
      svg.classList.remove("is-dragging");
      dragging = null;
    }

    function nodeCenter(id) {
      const node = svg.querySelector(`.map-node[data-nid="${CSS.escape(String(id))}"]`);
      if (!node) {
        const home = pos[id] || { x: 0, y: 0 };
        return { x: home.x, y: home.y, r: 22 };
      }
      const o = nodeOrigin(node);
      o.r = Number(node.dataset.r) || 22;
      return o;
    }
    function paintEdge(e) {
      const geo = edgeGeometry(nodeCenter(e.s), nodeCenter(e.t), e.shape === "curve");
      if (e.hit) e.hit.setAttribute("d", geo.d);
      if (e.line) e.line.setAttribute("d", geo.d);
      if (e.label) {
        e.label.setAttribute("x", geo.mx);
        e.label.setAttribute("y", geo.my - 5);
      }
    }
    function rerouteEdges(id) {
      edges.forEach(e => {
        if (e.s !== id && e.t !== id) return;
        paintEdge(e);
      });
    }
    function rerouteAll() { edges.forEach(paintEdge); }

    /* Move several records together. Used when a selection draws its
       neighbours in, and again when that selection is let go. */
    function glide(points, ms) {
      if (glideRaf) { cancelAnimationFrame(glideRaf); glideRaf = null; }
      const items = [];
      (points || []).forEach(p => {
        const node = svg.querySelector(`.map-node[data-nid="${CSS.escape(String(p.id))}"]`);
        if (!node) return;
        const o = nodeOrigin(node);
        if (Math.hypot(o.x - p.x, o.y - p.y) < 0.5) { placeNode(node, p.x, p.y); return; }
        items.push({ node, x0: o.x, y0: o.y, x1: p.x, y1: p.y });
      });
      const dur = ms == null ? 540 : ms;
      if (!items.length || dur <= 0) { rerouteAll(); return; }
      const t0 = performance.now();
      const step = (now) => {
        if (!svg.isConnected) { glideRaf = null; return; }
        const p = Math.min(1, (now - t0) / dur);
        const e = easeOutCubic(p);
        items.forEach(it => {
          placeNode(it.node, it.x0 + (it.x1 - it.x0) * e, it.y0 + (it.y1 - it.y0) * e);
        });
        rerouteAll();
        if (p < 1) glideRaf = requestAnimationFrame(step);
        else glideRaf = null;
      };
      glideRaf = requestAnimationFrame(step);
    }

    svg.addEventListener("dblclick", (ev) => {
      if (ev.target.closest(".map-node")) return;
      const p = toDiagram(ev.clientX, ev.clientY);
      zoomBy(ev.shiftKey ? 0.6 : 1.7, p.x * cam.k + cam.x, p.y * cam.k + cam.y, 260);
    });

    svg.addEventListener("keydown", (ev) => {
      const step = 60 / cam.k;
      const keys = {
        "+": () => zoomBy(1.25), "=": () => zoomBy(1.25), "-": () => zoomBy(0.8), "_": () => zoomBy(0.8),
        "0": () => fit(), "f": () => fit(), "F": () => fit(),
        "ArrowLeft": () => { cam.x += step; schedule(); },
        "ArrowRight": () => { cam.x -= step; schedule(); },
        "ArrowUp": () => { cam.y += step; schedule(); },
        "ArrowDown": () => { cam.y -= step; schedule(); }
      };
      const fn = keys[ev.key];
      if (!fn) return;
      ev.preventDefault();
      fn();
    });

    function clearHover() {
      if (svg.__hoverId === null) return;
      svg.__hoverId = null;
      svg.classList.remove("has-hover");
      svg.querySelectorAll(".hot").forEach(el => el.classList.remove("hot"));
      svg.querySelectorAll(".is-hovered").forEach(el => el.classList.remove("is-hovered"));
    }
    function neighboursOf(id) {
      const set = new Set([id]);
      edges.forEach(e => {
        if (e.s === id) set.add(e.t);
        if (e.t === id) set.add(e.s);
      });
      return set;
    }
    svg.addEventListener("pointerleave", clearHover);
    svg.addEventListener("pointermove", (ev) => {
      if (panning || dragging) { clearHover(); return; }
      const node = ev.target.closest && ev.target.closest(".map-node");
      const nid = node ? node.dataset.nid : null;
      if (nid === svg.__hoverId) return;
      svg.__hoverId = nid;
      svg.classList.toggle("has-hover", !!nid);
      const keep = nid ? neighboursOf(nid) : null;
      svg.querySelectorAll(".map-node").forEach(a => {
        a.classList.toggle("hot", !!keep && keep.has(a.dataset.nid));
        a.classList.toggle("is-hovered", a.dataset.nid === nid);
      });
      edges.forEach(e => {
        const on = !!nid && (e.s === nid || e.t === nid);
        if (e.g) e.g.classList.toggle("hot", on);
        if (e.hit) e.hit.classList.toggle("hot", on);
      });
    });

    /* a roster is already fitted to its frame; scaling it would close the gaps */
    if (!svg.classList.contains("is-roster")) fit(0);
    svg.style.opacity = "1";

    return { cam, W, H, pos, fit, zoomBy, flyTo, animateTo, schedule, glide };
  }

  /** Labels are placed by estimate, then corrected by measurement.
   *
   *  Text metrics differ by script and by font, so the greedy slot search above
   *  can still leave two names on top of each other. Once the scene is in the
   *  DOM we can measure the real boxes: the weakest name in each collision is
   *  nudged outward along its own bearing, twice, and only then allowed to
   *  recede — so what you read on the stage is what is actually legible.
   */
  function refineLabels(svg) {
    /* the roster reserves a cell for every name; nudging them breaks the row */
    if (svg.classList.contains("is-roster")) return;
    const nodes = Array.from(svg.querySelectorAll(".map-node"));
    if (nodes.length < 2) return;
    const glyphs = nodes.map(n => {
      const hit = n.querySelector(".node-hit");
      return hit ? { node: n, box: hit.getBoundingClientRect() } : null;
    }).filter(Boolean);
    const labels = nodes.map(n => {
      const t = n.querySelector("text.atlas-label");
      return t ? { node: n, text: t, box: t.getBoundingClientRect() } : null;
    }).filter(Boolean);
    if (labels.length < 2) return;
    const ctm = svg.getScreenCTM();
    const scale = ctm ? (Math.hypot(ctm.a, ctm.b) || 1) : 1;
    const hits = (a, b) => !(a.right < b.left || b.right < a.left ||
                             a.bottom < b.top || b.bottom < a.top);
    /* the focus keeps its place; among the rest, deeper nodes give way */
    const weight = (l) => l.node.classList.contains("is-focus") ? 99 : (l.node.dataset.weight | 0);
    labels.sort((a, b) => weight(b) - weight(a));
    for (let round = 0; round < 7; round++) {
      labels.forEach((lab, i) => {
        if (lab.node.classList.contains("is-focus")) return;
        const clash = labels.slice(0, i).some(other => hits(lab.box, other.box)) ||
                      glyphs.some(g => g.node !== lab.node && hits(lab.box, g.box));
        if (!clash) return;
        /* step away from the centre of the diagram, in diagram units */
        /* the name is stored in the node's own coordinates, origin on the glyph */
        const x = Number(lab.text.getAttribute("x")) || 0;
        const y = Number(lab.text.getAttribute("y")) || 0;
        const len = Math.hypot(x, y) || 1;
        const step = 17 / scale;
        lab.text.setAttribute("x", (x + (x / len) * step).toFixed(1));
        lab.text.setAttribute("y", (y + (y / len) * step * 0.75).toFixed(1));
        lab.text.querySelectorAll("tspan").forEach(tp => tp.setAttribute("x", lab.text.getAttribute("x")));
        lab.box = lab.text.getBoundingClientRect();
      });
    }
    labels.forEach(lab => {
      const clash = labels.some(other => other !== lab && hits(lab.box, other.box)) ||
                    glyphs.some(g => g.node !== lab.node && hits(lab.box, g.box));
      if (lab.node.classList.contains("is-focus")) { lab.text.classList.remove("is-dim"); return; }
      lab.text.classList.toggle("is-dim", clash);
    });
  }

  /* ======================================================================
     the side panel — the answer to "what did I just click?"
     ====================================================================== */
  function factRow(f) {
    const value = lang() === "ar" ? (f.value_ar || f.value) : f.value;
    if (f.ref) {
      return `<dt>${esc(lang() === "ar" ? f.label_ar : f.label_en)}</dt>
        <dd><a href="${esc(f.ref.href)}" dir="auto">${esc(value)}</a>
            <span class="mono-cell small muted">${esc(f.ref.code)}</span></dd>`;
    }
    return `<dt>${esc(lang() === "ar" ? f.label_ar : f.label_en)}</dt>
      <dd dir="auto">${esc(String(value ?? "—"))}</dd>`;
  }

  function stateChip(label, value) {
    if (!value) return "";
    return `<span class="ap-chip" style="--chip:${esc(value.color || "gray")}">
      <b>${esc(label)}</b>${esc(lang() === "ar" ? value.ar : value.en)}</span>`;
  }

  function nodePanel(d) {
    const counts = (d.counts && d.counts.evidence) || {};
    const disputed = counts.disputed;
    const neighbours = (d.neighbours || []).map(n => `
      <button type="button" class="ap-neighbour" data-nid="${esc(n.id)}" data-rel="${n.relationship_id}">
        <span class="apn-type sw-${esc(n.type)}" aria-hidden="true"></span>
        <span class="apn-body">
          <span class="apn-name" dir="auto">${esc(shortLabel(n.label, 34))}</span>
          <span class="apn-rel">${esc(lang() === "ar" ? n.rel_ar : n.rel_en)}
            ${n.symmetric ? "↔" : (n.outgoing ? "→" : "←")}
            <span class="apn-verif">${esc(lang() === "ar" ? n.verification_ar : n.verification_en)}</span>
            ${n.ended ? `<span class="apn-ended">${esc(t("atlas.ended"))}</span>` : ""}
          </span>
        </span>
        ${n.evidence_count ? `<span class="apn-ev" title="${esc(t("atlas.evidence"))}">${n.evidence_count}</span>` : ""}
      </button>`).join("");

    return `
      <div class="ap-head">
        <span class="ap-type sw-${esc(d.type)}">${esc(lang() === "ar" ? d.label_ar : d.label_en)}</span>
        <button class="icon-btn ap-close" data-ap-close aria-label="${esc(t("common.close"))}">×</button>
      </div>
      <h2 class="ap-title" dir="auto">${esc(d.title)}</h2>
      <div class="ap-sub">
        <span class="mono-cell">${esc(d.code || "")}</span>
        ${d.completeness != null ? `<span class="ap-complete" title="${esc(t("atlas.completenessNote"))}">
          ${d.completeness}%</span>` : ""}
      </div>
      <div class="ap-actions">
        <a class="btn sm primary" href="${esc(d.href)}" data-ap-open>
          ${esc(t("atlas.openRecord"))} ↗</a>
        <button class="btn sm" data-ap-explore>${esc(t("atlas.explore"))}</button>
        <button class="btn sm" data-ap-path>${esc(t("atlas.findPath"))}</button>
        <button type="button" class="btn sm" data-ap-rel
                data-type="${esc(d.type)}" data-id="${d.id}"
                data-title="${esc(d.title || d.code || "")}">${esc(t("atlas.addRelationship"))}</button>
        <a class="btn sm" href="#/geo">${esc(t("atlas.showOnMap"))}</a>
      </div>
      <div class="ap-composer" data-ap-composer hidden></div>
      <div class="ap-chips">
        ${stateChip(t("atlas.status"), d.state && d.state.record_status)}
        ${stateChip(t("atlas.verification"), d.state && d.state.authentication)}
        ${stateChip(t("atlas.documentation"), d.state && d.state.documentation)}
      </div>
      ${disputed ? `<div class="ap-disputed">⚠ ${esc(t("atlas.disputedNote"))}</div>` : ""}
      <div class="ap-position" data-ap-position hidden></div>
      ${d.facts && d.facts.length ? `<dl class="ap-facts">${d.facts.map(factRow).join("")}</dl>` : ""}
      <div class="ap-stats">
        <div><b>${num(d.counts.relationships)}</b><span>${esc(t("atlas.relationshipsCount"))}</span></div>
        <div><b>${num(counts.total || 0)}</b><span>${esc(t("atlas.evidence"))}</span></div>
        <div><b>${num(counts.sources || 0)}</b><span>${esc(t("atlas.sources"))}</span></div>
      </div>
      ${neighbours ? `<h3 class="ap-h">${esc(t("atlas.touches"))}</h3>
        <div class="ap-neighbours">${neighbours}</div>` : ""}
      <h3 class="ap-h">${esc(t("atlas.evidenceForRecord"))}</h3>
      <div class="ap-evidence">
        ${A.evidence.list(d.evidence, { removable: false,
          empty: t("atlas.noEvidenceRecord") })}
      </div>
      <p class="ap-note">${esc(t("atlas.safetyNote"))}</p>`;
  }

  function edgePanel(doc) {
    const dates = [doc.start_date, doc.end_date].filter(Boolean);
    const dateLine = dates.length
      ? `${doc.start_date || "…"} → ${doc.end_date || t("atlas.openEnded")}`
      : t("atlas.noDates");
    return `
      <div class="ap-head">
        <span class="ap-type sw-edge">${esc(t("atlas.relationship"))}</span>
        <button class="icon-btn ap-close" data-ap-close aria-label="${esc(t("common.close"))}">×</button>
      </div>
      <h2 class="ap-title" dir="auto">${esc(pick(doc.type_en, doc.type_ar))}</h2>
      <div class="ap-sub"><span class="mono-cell">#${doc.id}</span>
        ${doc.disputed ? `<span class="badge red">⚠ ${esc(t("atlas.contested"))}</span>` : ""}</div>
      <div class="ap-ends">
        <button class="ap-end" data-nid="${esc(doc.entity1_type)}:${doc.entity1_id}" dir="auto">
          ${esc(doc.entity1_name || t("atlas.record"))}</button>
        <span class="ap-arrow">${doc.direction === "symmetric" ? "↔" : "→"}</span>
        <button class="ap-end" data-nid="${esc(doc.entity2_type)}:${doc.entity2_id}" dir="auto">
          ${esc(doc.entity2_name || t("atlas.record"))}</button>
      </div>
      <div class="ap-actions">
        <a class="btn sm primary" href="#/entity/relationship/${doc.id}" data-ap-open>
          ${esc(t("atlas.openRecord"))} ↗</a>
      </div>
      <dl class="ap-facts">
        <dt>${esc(t("atlas.direction"))}</dt>
        <dd>${esc(doc.direction === "symmetric"
          ? t("atlas.symmetric")
          : t("atlas.directed"))}</dd>
        <dt>${esc(t("atlas.dates"))}</dt><dd dir="ltr">${esc(dateLine)}</dd>
        <dt>${esc(t("atlas.verificationLabel"))}</dt>
        <dd>${esc(pick(doc.auth_en, doc.auth_ar))}</dd>
        ${doc.last_review_date ? `<dt>${esc(t("atlas.lastReview"))}</dt>
          <dd>${esc(doc.last_review_date)}</dd>` : ""}
        ${doc.description ? `<dt>${esc(t("atlas.description"))}</dt>
          <dd dir="auto">${esc(doc.description)}</dd>` : ""}
      </dl>
      <h3 class="ap-h">${esc(t("atlas.evidenceForRelationship"))}</h3>
      <div class="ap-evidence">
        ${A.evidence.list(doc.evidence, { removable: false,
          empty: t("atlas.noEvidenceRelationship") })}
      </div>
      <p class="ap-note">${esc(t("atlas.safetyNoteRow"))}</p>`;
  }

  /* ======================================================================
     the view
     ====================================================================== */
  const st = {
    mode: "types", entity: "person", recordId: null, depth: 1,
    showStructural: true, layout: "orbit",
    data: null, view: { nodes: [], edges: [] }, canvas: null,
    selection: null, panel: null, trail: [], path: null,
    filters: { types: null, rels: null, evidenceOnly: false, hideEnded: false },
    /* the full people-and-organizations graph: which types, two searches,
       and an explicit multi-selection that stays on the map */
    net: {
      types: ["person", "institution"],
      qPerson: "", qOrg: "", qOther: "",
      pins: [], layout: "force", seen: false
    },
    options: [], loading: false,
    /* when armed, the next node click fills the in-panel relationship composer */
    pickForRel: null
  };

  const els = {};
  /* The scene is measured in pixels, not in an assumed 16:10 frame: the
     drawing then fills the column it is given, at scale 1, so text stays
     crisp and the orbit uses the vertical room the panel opened up. */
  let W = 1120, H = 660;

  function measureStage() {
    if (!els.canvas || !els.canvas.clientWidth) return false;
    const cw = Math.round(els.canvas.clientWidth - 16);
    if (cw < 240) return false;
    /* the frame is as tall as the window allows, within limits, so the orbit
       is round-ish rather than a letterbox, and text is drawn at scale 1 */
    const avail = window.innerHeight || 900;
    const roster = st.mode === "network";
    const ch = Math.round(Math.min(
      Math.max(cw * (roster ? 0.78 : 0.56), roster ? 560 : 400),
      avail * (roster ? 0.82 : 0.66)));
    if (cw === W && ch === H) return false;
    W = cw; H = ch;
    return true;
  }

  function optionFor(entity, rec) {
    return { id: rec.id, label: A.dispTitle(rec, entity) || rec.code };
  }

  async function loadRecordOptions(entity, mustInclude) {
    try {
      const res = await A.api.post(`/api/${entity}/query`,
        { page_size: 60, sort: { key: "relationships_count", dir: "desc" } });
      st.options = (res.items || []).map(r => optionFor(entity, r));
    } catch (e) { st.options = []; }
    if (mustInclude && !st.options.some(o => String(o.id) === String(mustInclude))) {
      try {
        const rec = await A.api.get(`/api/${entity}/${mustInclude}`);
        st.options.unshift(optionFor(entity, rec));
      } catch (e) { /* a missing record leaves the list as it was */ }
    }
  }

  /* ------------------------------------------------------------- filtering --- */
  function applyFilters(data) {
    const f = st.filters;
    let nodes = (data.nodes || []).slice();
    let edges = (data.edges || []).slice();
    if (f.types && f.types.size) {
      nodes = nodes.filter(n => f.types.has(n.type) || n.id === data.focus);
    }
    if (f.rels && f.rels.size) {
      edges = edges.filter(e => f.rels.has(e.type) || e.kind === "structural");
    }
    if (f.evidenceOnly) edges = edges.filter(e => (e.evidence_count || 0) > 0);
    if (f.hideEnded) edges = edges.filter(e => !e.ended);
    if (data.mode === "network") {
      /* the roster is the records themselves, including those with no link yet */
      const ids = new Set(nodes.map(n => n.id));
      edges = edges.filter(e => ids.has(e.source) && ids.has(e.target));
      return { nodes, edges };
    }
    // keep only nodes that still have a visible edge (plus the focus)
    const keep = new Set([data.focus]);
    edges.forEach(e => { keep.add(e.source); keep.add(e.target); });
    nodes = nodes.filter(n => keep.has(n.id));
    edges = edges.filter(e => keep.has(e.source) && keep.has(e.target));
    return { nodes, edges };
  }

  function relTypes(data) {
    const map = {};
    (data.edges || []).forEach(e => {
      if (e.kind !== "relationship") return;
      const key = e.type || "other";
      map[key] = map[key] || { code: key, en: e.label_en, ar: e.label_ar, n: 0 };
      map[key].n++;
    });
    return Object.values(map).sort((a, b) => b.n - a.n);
  }

  /* ------------------------------------------------------------------ load --- */
  async function load() {
    const params = st.mode === "types"
      ? { mode: "types", include_structural: st.showStructural }
      : st.mode === "network"
        ? { mode: "network", types: st.net.types.slice(),
            q_person: st.net.qPerson, q_institution: st.net.qOrg, q: st.net.qOther,
            pins: st.net.pins.map(p => `${p.type}:${p.id}`), limit: 320 }
        : { mode: "focus", entity_type: st.entity, record_id: st.recordId, depth: st.depth };
    st.loading = true;
    try {
      const data = await A.api.post("/api/relationship-map", params);
      st.data = data;
    } catch (err) {
      st.data = { nodes: [], edges: [], error: err.message };
    }
    st.loading = false;
    compute();
  }

  function compute() {
    measureStage();
    if (st.mode === "types") { renderOverview(); return; }
    const filtered = applyFilters(st.data || {});
    const focusId = st.mode === "network"
      ? null
      : ((st.data && st.data.focus) || `${st.entity}:${st.recordId}`);
    const nodes = filtered.nodes.map(n => {
      const copy = Object.assign({}, n);
      if (copy.name_en || copy.name_ar) copy.label = pick(copy.name_en, copy.name_ar) || copy.label;
      return copy;
    });
    const laid = st.layout === "force"
      ? forceLayout(nodes, filtered.edges, focusId, W, H)
      : orbitLayout(nodes, filtered.edges, focusId, W, H);
    if (laid && laid.w) { W = laid.w; H = laid.h; }
    nodes.forEach(n => { n.hx = n.x; n.hy = n.y; });
    st.view = { nodes, edges: filtered.edges, focusId, bands: laid && laid.bands };
    paint();
  }

  /* ----------------------------------------------------------------- paint --- */
  function paint() {
    const stage = els.canvas;
    if (!stage) return;
    if (st.mode === "types") return;
    const { nodes, edges, focusId } = st.view;
    if (!nodes.length) {
      const empty = st.mode === "network" ? t("map.networkEmpty") : t("map.noConnections");
      stage.innerHTML = `<div class="atlas-empty">${esc(empty)}</div>`;
      renderRail();
      return;
    }
    if (st.layout === "matrix") {
      stage.innerHTML = matrixView(nodes, edges, focusId, st.selection);
      wireMatrix();
      renderRail();
      return;
    }
    const note = (st.mode === "network" && st.data && st.data.truncated)
      ? `<p class="atlas-net-note">${esc(t("map.truncated", {
          n: num(st.data.shown || nodes.length),
          total: num(st.data.total_in_types || nodes.length)
        }))}</p>` : "";
    stage.innerHTML = note + buildScene({
      nodes, edges, focusId, layout: st.layout, selection: st.selection,
      path: st.path, W, H, bands: st.view.bands
    });
    mountCanvas();
    renderRail();
  }

  function mountCanvas() {
    const stage = els.canvas;
    const svg = stage.querySelector("svg.relmap");
    if (!svg) return;
    refineLabels(svg);
    svg.querySelectorAll(".map-node").forEach(node => {
      const select = (ev) => {
        if (ev) ev.preventDefault();
        if (node.dataset.dragged === "1") { node.dataset.dragged = ""; return; }
        if (svg.__suppressClick) { svg.__suppressClick = false; return; }
        selectNode(node.dataset.nid);
      };
      node.addEventListener("click", select);
      node.addEventListener("keydown", ev => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(ev); }
      });
    });
    svg.querySelectorAll(".rm-edge").forEach(g => {
      const open = (ev) => {
        if (ev) { ev.preventDefault(); ev.stopPropagation(); }
        if (g.dataset.dragged === "1") { g.dataset.dragged = ""; return; }
        if (svg.__suppressClick) { svg.__suppressClick = false; return; }
        selectEdge(g.dataset.edge);
      };
      g.addEventListener("click", open);
      g.addEventListener("keydown", ev => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(ev); }
      });
    });
    stage.appendChild(canvasHud());
    st.canvas = attachCanvas(svg, stage, {
      onCam: (cam) => {
        const z = stage.querySelector("[data-zoom]");
        if (z) z.textContent = Math.round(cam.k * 100) + "%";
      }
    });
    wireHud();
    applySelectionClasses();
    if (st.selection) stageSelection();
  }

  function wireHud() {
    const hud = els.canvas.querySelector(".map-hud");
    if (!hud) return;
    const q = (s) => hud.querySelector(s);
    if (q("[data-zin]")) q("[data-zin]").onclick = () => st.canvas.zoomBy(1.3);
    if (q("[data-zout]")) q("[data-zout]").onclick = () => st.canvas.zoomBy(0.77);
    if (q("[data-zfit]")) q("[data-zfit]").onclick = () => st.canvas.fit();
    if (q("[data-zfull]")) q("[data-zfull]").onclick = () => toggleFullscreen();
    const search = q("[data-map-search]");
    const hits = q("[data-map-hits]");
    if (!search) return;
    search.oninput = () => {
      const needle = A.normText(search.value.trim());
      const all = Array.from(els.canvas.querySelectorAll(".map-node"));
      all.forEach(a => a.classList.remove("hit"));
      if (!needle) { hits.textContent = ""; hits.hidden = true; return; }
      let n = 0, first = null;
      all.forEach(a => {
        if (A.normText(a.dataset.label || "").includes(needle)) {
          a.classList.add("hit"); n++; if (!first) first = a;
        }
      });
      hits.hidden = false;
      hits.textContent = n ? String(n) : t("map.noHits");
      hits.classList.toggle("none", !n);
      if (first) st.canvas.flyTo(first.dataset.nid, Math.max(st.canvas.cam.k, 1.4));
    };
    search.onkeydown = (ev) => {
      if (ev.key === "Enter") {
        const hit = els.canvas.querySelector(".map-node.hit");
        if (hit) { ev.preventDefault(); selectNode(hit.dataset.nid); }
      }
      if (ev.key === "Escape") { search.value = ""; search.oninput(); }
    };
  }

  function wireMatrix() {
    els.canvas.querySelectorAll(".mx-cell[data-edge]").forEach(cell => {
      cell.onclick = () => selectEdge(cell.dataset.edge);
      cell.onkeydown = (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectEdge(cell.dataset.edge); }
      };
      cell.tabIndex = 0;
      cell.setAttribute("role", "button");
    });
    els.canvas.querySelectorAll(".mx-name[data-nid]").forEach(el => {
      el.onclick = () => selectNode(el.dataset.nid);
    });
  }

  /* -------------------------------------------------------------- selection --- */

  /**
   * A click gathers the records that touch it onto a ring, and opens a
   * clearing around that ring so the relationship can be read on its own.
   * Everyone else keeps a home to return to. Positions are written onto the
   * node objects; the canvas glides the drawing across.
   */
  function arrangeSelection(nodes, edges, selection) {
    nodes.forEach(n => {
      if (n.hx == null) { n.hx = n.x; n.hy = n.y; }
      n.x = n.hx; n.y = n.hy;
      n.focusRole = "far";
    });
    if (!selection) return null;

    const pushOut = (n, cx, cy, minR) => {
      let dx = n.x - cx, dy = n.y - cy;
      const d = Math.hypot(dx, dy) || 0.01;
      if (d >= minR) return;
      n.x = cx + (dx / d) * (minR + 10);
      n.y = cy + (dy / d) * (minR + 10);
    };

    if (selection.kind === "edge") {
      const e = edges.find(x => String(x.id) === String(selection.id));
      if (!e) return null;
      const a = nodes.find(n => n.id === e.source);
      const b = nodes.find(n => n.id === e.target);
      if (!a || !b) return null;
      const mx = (a.hx + b.hx) / 2, my = (a.hy + b.hy) / 2;
      const ang = Math.atan2(b.hy - a.hy, b.hx - a.hx);
      const gap = Math.max(150, (a.r || 16) + (b.r || 16) + 96);
      a.x = mx - Math.cos(ang) * gap / 2; a.y = my - Math.sin(ang) * gap / 2;
      b.x = mx + Math.cos(ang) * gap / 2; b.y = my + Math.sin(ang) * gap / 2;
      a.focusRole = "near"; b.focusRole = "near";
      const clearR = gap / 2 + 108;
      nodes.forEach(n => { if (n !== a && n !== b) pushOut(n, mx, my, clearR); });
      separateNodes(nodes, 14, new Set([a.id, b.id]));
      return { cx: mx, cy: my, disc: clearR - 28, ring: gap / 2 };
    }

    const focus = nodes.find(n => n.id === selection.id);
    if (!focus) return null;
    focus.focusRole = "focus";
    const ids = new Set();
    edges.forEach(e => {
      if (e.source === focus.id) ids.add(e.target);
      if (e.target === focus.id) ids.add(e.source);
    });
    ids.delete(focus.id);
    const near = nodes.filter(n => ids.has(n.id));
    near.forEach(n => { n.focusRole = "near"; });
    near.sort((p, q) =>
      Math.atan2(p.hy - focus.hy, p.hx - focus.hx) -
      Math.atan2(q.hy - focus.hy, q.hx - focus.hx));
    const count = near.length;
    const ideal = count
      ? Math.max(108, Math.min(220, (count * 128) / (2 * Math.PI)))
      : 0;
    /* the floating tools cover the top of the drawing; the ring also has to
       fit across the frame, with room for a name on either side */
    const ring = ideal
      ? Math.min(ideal, Math.max(92, W / 2 - 56))
      : 0;
    const chrome = ring + 176;
    focus.x = W / 2;
    focus.y = clamp(Math.max(focus.hy, chrome), chrome, Math.max(chrome, H - ring - 48));
    if (count === 1) {
      const ang = Math.atan2(near[0].hy - focus.hy, near[0].hx - focus.hx);
      near[0].x = focus.x + Math.cos(ang) * ring;
      near[0].y = focus.y + Math.sin(ang) * ring;
    } else if (count === 2) {
      const ang = Math.atan2(near[0].hy - near[1].hy, near[0].hx - near[1].hx);
      near[0].x = focus.x + Math.cos(ang) * ring;
      near[0].y = focus.y + Math.sin(ang) * ring;
      near[1].x = focus.x - Math.cos(ang) * ring;
      near[1].y = focus.y - Math.sin(ang) * ring;
    } else {
      const base = count
        ? Math.atan2(near[0].hy - focus.hy, near[0].hx - focus.hx)
        : -Math.PI / 2;
      near.forEach((n, i) => {
        const ang = base + (i * 2 * Math.PI) / count;
        n.x = focus.x + Math.cos(ang) * ring;
        n.y = focus.y + Math.sin(ang) * ring;
      });
    }
    const clearR = (ring || 86) + 132;
    nodes.forEach(n => { if (n.focusRole === "far") pushOut(n, focus.x, focus.y, clearR); });
    const fixed = new Set([focus.id].concat(near.map(n => n.id)));
    separateNodes(nodes, 16, fixed);
    return { cx: focus.x, cy: focus.y, disc: (ring || 64) + 52, ring: ring || 0 };
  }

  /** Point each gathered name outward, and give it back its place when the ring closes. */
  function presentClusterLabels(svg, nodes, stage) {
    const byId = Object.create(null);
    nodes.forEach(n => { byId[n.id] = n; });
    const origin = stage || null;
    svg.querySelectorAll(".map-node").forEach(g => {
      const text = g.querySelector("text.atlas-label");
      if (!text) return;
      if (text.dataset.lx == null) {
        text.dataset.lx = text.getAttribute("x") || "0";
        text.dataset.ly = text.getAttribute("y") || "0";
        text.dataset.anchor = text.getAttribute("text-anchor") || "start";
        text.dataset.dir = text.getAttribute("direction") || "auto";
        text.dataset.short = text.innerHTML;
      }
      const n = byId[g.dataset.nid];
      const role = n && n.focusRole;
      const gathered = origin && (role === "focus" || role === "near");
      if (!gathered) {
        text.setAttribute("x", text.dataset.lx);
        text.setAttribute("y", text.dataset.ly);
        text.setAttribute("text-anchor", text.dataset.anchor);
        text.setAttribute("direction", text.dataset.dir);
        text.innerHTML = text.dataset.short;
        return;
      }
      const full = fitLabel(g.dataset.label || "", 15.5, role === "focus" ? 220 : 150);
      text.textContent = full;
      if (role === "focus") {
        text.setAttribute("x", "0");
        text.setAttribute("y", String((n.r || 16) + 26));
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("direction", lang() === "ar" ? "rtl" : "ltr");
        return;
      }
      const dx = n.x - origin.cx, dy = n.y - origin.cy;
      const gap = (n.r || 14) + 12;
      const roomRight = W - (n.x + gap);
      const roomLeft = n.x - gap;
      const growRight = dx >= 0 && roomRight >= 96;
      const growLeft = dx < 0 && roomLeft >= 96;
      if (growRight || growLeft) {
        text.setAttribute("x", String(growRight ? gap : -gap));
        text.setAttribute("y", "5");
        text.setAttribute("text-anchor", "start");
        text.setAttribute("direction", growRight ? "ltr" : "rtl");
      } else {
        /* not enough margin beside the glyph: the name sits just outside the ring */
        const below = dy >= 0;
        text.setAttribute("x", "0");
        text.setAttribute("y", String(below ? gap + 8 : -(gap - 2)));
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("direction", lang() === "ar" ? "rtl" : "ltr");
      }
    });
  }

  function placeStage(svg, stage) {
    const fill = svg.querySelector(".atlas-stage-fill");
    const ring = svg.querySelector(".atlas-stage-ring");
    if (!fill || !ring) return;
    if (!stage) {
      fill.setAttribute("r", "0");
      ring.setAttribute("r", "0");
      return;
    }
    fill.setAttribute("cx", stage.cx);
    fill.setAttribute("cy", stage.cy);
    fill.setAttribute("r", stage.disc);
    ring.setAttribute("cx", stage.cx);
    ring.setAttribute("cy", stage.cy);
    ring.setAttribute("r", stage.ring || 0);
  }

  function liftSelection(svg) {
    const nodes = svg.querySelector(".relmap-nodes");
    const edges = svg.querySelector(".relmap-edges");
    if (edges) svg.querySelectorAll(".rm-edge.is-linked").forEach(el => edges.appendChild(el));
    if (nodes) {
      svg.querySelectorAll(".map-node.is-near").forEach(el => nodes.appendChild(el));
      svg.querySelectorAll(".map-node.is-selected").forEach(el => nodes.appendChild(el));
    }
  }

  /**
   * Apply the gathering to the live drawing. A fresh frame (the panel just
   * changed the width) is already at home, so this is also what plays the
   * approach after a rebuild.
   */
  function stageSelection() {
    const view = st.view;
    const svg = els.canvas && els.canvas.querySelector("svg.relmap");
    if (!view || !view.nodes || !svg || st.layout === "matrix") return;
    const stage = arrangeSelection(view.nodes, view.edges, st.selection);
    applySelectionClasses();
    presentClusterLabels(svg, view.nodes, stage);
    placeStage(svg, stage);
    liftSelection(svg);
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (stage) {
      const box = svg.getBoundingClientRect();
      const scale = box.height / (H || box.height || 1);
      const pageY = box.top + window.scrollY + stage.cy * scale;
      const top = Math.max(0, pageY - window.innerHeight * 0.46);
      window.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
    }
    if (!st.canvas || !st.canvas.glide) return;
    st.canvas.glide(view.nodes.map(n => ({ id: n.id, x: n.x, y: n.y })), reduce ? 0 : 560);
  }

  function applySelectionClasses() {
    const svg = els.canvas.querySelector("svg.relmap");
    if (!svg) return;
    svg.classList.toggle("has-selection", !!st.selection);
    const nearIds = neighboursOfSelection();
    svg.querySelectorAll(".map-node").forEach(el => {
      const isSel = st.selection && st.selection.kind === "node" &&
        el.dataset.nid === st.selection.id;
      el.classList.toggle("is-selected", !!isSel);
      el.classList.toggle("is-near", !isSel && nearIds.has(el.dataset.nid));
    });
    svg.querySelectorAll(".rm-edge").forEach(el => {
      const hit = el.querySelector("[data-s]");
      const on = st.selection && st.selection.kind === "edge" &&
        el.dataset.edge === String(st.selection.id);
      const linked = !!on || (st.selection && st.selection.kind === "node" && hit &&
        (hit.dataset.s === st.selection.id || hit.dataset.t === st.selection.id));
      el.classList.toggle("is-selected", !!on);
      el.classList.toggle("is-linked", !!linked);
    });
  }

  function neighboursOfSelection() {
    const set = new Set();
    if (!st.selection || !st.view) return set;
    if (st.selection.kind === "node") {
      st.view.edges.forEach(e => {
        if (e.source === st.selection.id || e.target === st.selection.id) {
          set.add(e.source); set.add(e.target);
        }
      });
      set.delete(st.selection.id);
    } else if (st.selection.kind === "edge") {
      const e = st.view.edges.find(x => String(x.id) === String(st.selection.id));
      if (e) { set.add(e.source); set.add(e.target); }
    }
    return set;
  }

  async function selectNode(nid) {
    if (!nid) return;
    const [type, id] = String(nid).split(":");
    /* The overview draws one bubble per record type; a bubble is a whole
       category, not a row, so it drills into the type instead of asking the
       graph for a record that does not exist (`.../person/undefined`). */
    if (!id || id === "undefined" || id === type) { openNeighbourhood(type); return; }

    /* Pick mode: fill the open composer; do not tear down the panel. */
    if (typeof st.pickForRel === "function") {
      const node = (st.view.nodes || []).find(n => n.id === nid);
      const title = node
        ? (pick(node.name_en, node.name_ar) || node.label || "")
        : "";
      st.pickForRel({ type, id: Number(id), title: title || nid });
      st.pickForRel = null;
      clearPickCue();
      A.toast(t("atlas.pickFilled"), "ok", 2200);
      return;
    }

    st.selection = { kind: "node", id: nid };
    applySelectionClasses();
    /* the panel's first open changes the frame, and the rebuild plays the
       gathering itself; a later click animates inside the frame we have */
    const reflow = els.panel && els.panel.hidden;
    if (!reflow) stageSelection();
    if (!reflow && st.canvas && st.layout !== "matrix") {
      const svg = els.canvas.querySelector("svg.relmap");
      if (svg && !svg.classList.contains("is-roster")) {
        st.canvas.flyTo(nid, Math.max(st.canvas.cam.k, 1.05));
      }
    }
    openPanel(`<div class="ap-loading">${esc(t("common.loading"))}</div>`);
    try {
      const dossier = await A.api.get(`/api/graph/node/${encodeURIComponent(type)}/${encodeURIComponent(id)}`);
      st.panel = { kind: "node", data: dossier };
      openPanel(nodePanel(dossier), dossier);
    } catch (err) {
      openPanel(`<div class="notice err">${esc(err.message)}</div>`);
    }
  }

  async function selectEdge(relId) {
    if (!relId) return;
    /* a structural link (affiliation, position) is not a relationship row */
    if (!/^\d+$/.test(String(relId))) {
      const e = ((st.data && st.data.edges) || []).find(x => String(x.id) === String(relId));
      st.selection = { kind: "edge", id: String(relId) };
      applySelectionClasses();
      stageSelection();
      const name = e ? pick(e.label_en, e.label_ar) : String(relId);
      openPanel(`
        <div class="ap-head">
          <span class="ap-type sw-edge">${esc(t("atlas.relationship"))}</span>
          <button class="icon-btn ap-close" data-ap-close aria-label="${esc(t("common.close"))}">×</button>
        </div>
        <h2 class="ap-title" dir="auto">${esc(name)}</h2>
        <p class="ap-note">${esc(t("map.structuralLink"))}</p>`);
      return;
    }
    st.selection = { kind: "edge", id: String(relId) };
    applySelectionClasses();
    const reflow = els.panel && els.panel.hidden;
    if (!reflow) stageSelection();
    openPanel(`<div class="ap-loading">${esc(t("common.loading"))}</div>`);
    try {
      const doc = await A.api.get(`/api/relationship/${relId}/evidence`);
      st.panel = { kind: "edge", data: doc };
      openPanel(edgePanel(doc), doc);
    } catch (err) {
      openPanel(`<div class="notice err">${esc(err.message)}</div>`);
    }
  }

  function openPanel(html, data) {
    const panel = els.panel;
    if (!panel) return;
    panel.innerHTML = html;
    panel.hidden = false;
    els.atlas.classList.add("has-panel");
    /* the canvas just lost a column: give the scene its new frame back */
    requestAnimationFrame(() => { if (measureStage()) compute(); });
    panel.querySelectorAll("[data-ap-close]").forEach(b => { b.onclick = closePanel; });
    panel.querySelectorAll("[data-ap-explore]").forEach(b => {
      b.onclick = () => explore(els.selectedId || (st.selection && st.selection.id));
    });
    panel.querySelectorAll("[data-ap-path]").forEach(b => {
      b.onclick = () => pathDialog(st.selection && st.selection.id);
    });
    panel.querySelectorAll("[data-ap-rel]").forEach(b => {
      b.onclick = () => openRelationshipComposer(panel, {
        type: b.dataset.type, id: Number(b.dataset.id), title: b.dataset.title || ""
      });
    });
    panel.querySelectorAll(".ap-neighbour, .ap-end").forEach(b => {
      b.onclick = () => selectNode(b.dataset.nid);
    });
    if (data && data.href) els.selectedId = data.id || (st.selection && st.selection.id);
    /* the standard's line on this record's position: the reserved mark, what the
       point is, and how sure the registry is — one small request, in place */
    fillPosition(panel, st.selection);
    panel.scrollTop = 0;
  }

  /**
   * Workspace rule: actions that belong to the atlas stay *in* the atlas.
   * The relationship composer mounts in the side panel — never navigates to a
   * record form, never opens the global dialog surface over the diagram.
   */
  function openRelationshipComposer(panel, source) {
    const slot = panel.querySelector("[data-ap-composer]");
    if (!slot || !A.composeRelationship) return;
    st.pickForRel = null;
    const composer = A.composeRelationship({
      host: slot,
      source,
      onCancel: () => { st.pickForRel = null; clearPickCue(); },
      onPickRequest: (setTarget) => {
        st.pickForRel = setTarget || null;
        setPickCue(!!setTarget);
        if (setTarget) A.toast(t("atlas.pickOnMapHint"), "ok", 3200);
      },
      onSaved: async (rec) => {
        st.pickForRel = null;
        clearPickCue();
        /* stay on this node; refresh the graph so the new edge appears */
        const nid = `${source.type}:${source.id}`;
        await load();
        await selectNode(nid);
        if (rec && rec.id) setTimeout(() => selectEdge(rec.id), 160);
      }
    });
    slot.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return composer;
  }

  function setPickCue(on) {
    if (els.atlas) els.atlas.classList.toggle("is-picking-rel", !!on);
  }
  function clearPickCue() { setPickCue(false); }

  /** The CRCE line inside a node panel: mark · role · precision · bearing. */
  function fillPosition(panel, selection) {
    const host = panel.querySelector("[data-ap-position]");
    if (!host || !selection || selection.kind !== "node") return;
    const [type, id] = String(selection.id).split(":");
    if (!["person", "institution", "place"].includes(type)) return;
    A.api.get(`/api/crce/dossier/${type}/${id}`).then(d => {
      if (!host.isConnected || !d) return;
      const ar = lang() === "ar";
      const pick = (en, ary) => (ar ? (ary || en) : en);
      const c = d.coordinates;
      const o = d.orientation;
      const mark = document.createElement("span");
      mark.className = "crce-tile-mark";
      host.innerHTML = "";
      host.append(mark);
      A.crce.attach(mark, d, { size: 46 });
      const text = document.createElement("div");
      text.className = "crce-tile-name";
      text.innerHTML = c
        ? `<span class="crce-tile-role">${esc(pick(c.role.en, c.role.ar))}</span>
           <span class="small muted">
             ${esc(pick((c.precision || {}).label_en, (c.precision || {}).label_ar) ||
                   pick("unrecorded", "غير مسجّلة"))}
             ${o ? `· ${esc(pick(o.phrase_en, o.phrase_ar))}` : ""}</span>`
        : `<span class="crce-tile-role">${esc(t("crce.notCovered"))}</span>
           <span class="small muted">${esc(pick("no georeferenced place", "لا مكان مُسنَد جغرافياً"))}</span>`;
      host.append(text);
      host.hidden = false;
      host.classList.add("crce-tile");
    }).catch(() => { /* the panel is complete without it */ });
  }

  function closePanel() {
    if (!els.panel) return;
    st.pickForRel = null;
    clearPickCue();
    els.panel.hidden = true;
    els.panel.innerHTML = "";
    els.atlas.classList.remove("has-panel");
    requestAnimationFrame(() => { if (measureStage()) compute(); });
    st.selection = null;
    st.panel = null;
    applySelectionClasses();
    stageSelection();
  }

  /* ------------------------------------------------------------------ trail --- */
  function currentFocus() {
    return `${st.entity}:${st.recordId}`;
  }

  function pushTrail(type, id, label) {
    const node = { type, id: Number(id), label, key: `${type}:${id}` };
    const last = st.trail[st.trail.length - 1];
    if (last && last.key === node.key) return;
    st.trail.push(node);
    if (st.trail.length > 24) st.trail.shift();
    renderTrail();
  }

  function explore(nid, fromTrail) {
    if (!nid) return;
    const [type, id] = String(nid).split(":");
    if (!type || !id) return;
    const label = (st.panel && st.panel.kind === "node" && st.panel.data &&
                   st.panel.data.id === nid) ? st.panel.data.title : null;
    st.entity = type;
    st.recordId = Number(id);
    st.selection = null;
    st.path = null;
    closePanel();
    syncToolbarSelects();
    if (!fromTrail) {
      const node = st.view.nodes.find(n => n.id === nid);
      pushTrail(type, id, label || (node && node.label) || `${type} #${id}`);
    }
    load().then(() => {
      /* the panel comes with you: you drilled into a record, so its details
         should be the first thing on the new stage, not a second click */
      if (!fromTrail) selectNode(nid);
    });
  }

  function trailBack() {
    if (st.trail.length < 2) return;
    st.trail.pop();
    const prev = st.trail[st.trail.length - 1];
    if (!prev) return;
    st.entity = prev.type;
    st.recordId = prev.id;
    st.selection = null; st.path = null;
    closePanel();
    syncToolbarSelects();
    renderTrail();
    load();
  }

  function renderTrail() {
    const host = els.trail;
    if (!host) return;
    /* the overview is the top of the atlas: no trail, no crumbs, one way in */
    if (st.mode === "types" || st.mode === "network") {
      const label = st.mode === "network" ? t("map.network") : t("atlas.overview");
      host.innerHTML = `<span class="atlas-back" aria-hidden="true">←</span>
        <div class="atlas-crumbs"><button class="atlas-crumb current" aria-current="step"
          >${esc(label)}</button></div>`;
      return;
    }
    const items = st.trail.map((step, i) => {
      const last = i === st.trail.length - 1;
      return `<button class="atlas-crumb${last ? " current" : ""}" data-trail="${i}"
                ${last ? 'aria-current="step"' : ""}>
                ${esc(shortLabel(step.label || `${step.type} #${step.id}`, 28))}</button>`;
    }).join(`<span class="atlas-crumb-sep">›</span>`);
    host.innerHTML = `<button class="atlas-back" data-trail-back title="${esc(t("atlas.back"))}"
                        ${st.trail.length < 2 ? "disabled" : ""}>←</button>
                      <div class="atlas-crumbs">${items ||
                        `<span class="muted small">${esc(t("atlas.start"))}</span>`}</div>`;
    host.querySelector("[data-trail-back]").onclick = trailBack;
    host.querySelectorAll("[data-trail]").forEach(b => {
      b.onclick = () => {
        const i = Number(b.dataset.trail);
        if (i >= st.trail.length - 1) return;
        const step = st.trail[i];
        st.trail = st.trail.slice(0, i + 1);
        st.entity = step.type; st.recordId = step.id;
        st.selection = null; st.path = null;
        closePanel(); syncToolbarSelects(); renderTrail(); load();
      };
    });
  }

  /* ------------------------------------------------------------------- rail --- */
  function renderOverviewRail(rail) {
    const data = st.data || {};
    const totals = data.totals || {};
    const types = (data.nodes || []).slice().sort((a, b) => (b.count || 0) - (a.count || 0));
    rail.innerHTML = `
      <section class="atl-sec">
        <h3>${esc(t("atlas.types"))}</h3>
        <div class="atl-chips">
          ${types.map(n => {
            const isRecord = drillable(n.type);
            return `<button class="atl-chip on${isRecord ? "" : " is-count"}"
                ${isRecord ? `data-type-focus="${esc(n.type)}"` : ""}
                style="--chip:${(TYPE_STYLE[n.type] || {}).color}"><i></i>
                ${esc(pick(n.label_en, n.label_ar))}<b>${num(n.count || 0)}</b></button>`;
          }).join("")}
        </div>
      </section>
      <section class="atl-sec">
        <h3>${esc(t("atlas.showing"))}</h3>
        <div class="atl-foot">
          <span>${t("map.recordsTotal")}: <b>${num(totals.records || 0)}</b></span>
          <span>${t("map.relationshipsTotal")}: <b>${num(totals.relationships || 0)}</b></span>
          <span>${t("map.structuralTotal")}: <b>${num(totals.structural_links || 0)}</b></span>
          <span>${t("map.typesTotal")}: <b>${num(totals.distinct_types || types.length)}</b></span>
        </div>
      </section>
      <section class="atl-sec">
        <p class="small muted">${esc(t("atlas.overviewHint"))}</p>
      </section>`;
    rail.querySelectorAll("[data-type-focus]").forEach(b => {
      b.onclick = () => openNeighbourhood(b.dataset.typeFocus);
    });
  }

  function renderRail() {
    const rail = els.rail;
    if (!rail) return;
    if (st.mode === "types") { renderOverviewRail(rail); return; }
    const data = st.data || {};
    const counts = {};
    (data.nodes || []).forEach(n => { counts[n.type] = (counts[n.type] || 0) + 1; });
    const types = TYPE_ORDER.filter(tp => counts[tp]);
    const rels = relTypes(data);
    const activeTypes = st.filters.types;
    const activeRels = st.filters.rels;
    const total = (data.nodes || []).length;
    const shownNodes = st.view.nodes ? st.view.nodes.length : 0;
    const shownEdges = st.view.edges ? st.view.edges.length : 0;

    rail.innerHTML = `
      <section class="atl-sec">
        <h3>${esc(t("atlas.layout"))}</h3>
        <div class="atl-layouts" role="tablist">
          ${[["orbit", t("atlas.orbit"), "◉"], ["force", t("atlas.force"), "✦"],
             ["matrix", t("atlas.matrix"), "▦"]].map(([key, label, mark]) => `
            <button role="tab" data-layout="${key}" class="${st.layout === key ? "active" : ""}"
              aria-selected="${st.layout === key}"><i>${mark}</i>${esc(label)}</button>`).join("")}
        </div>
      </section>
      <section class="atl-sec">
        <h3>${esc(t("atlas.types"))}</h3>
        <div class="atl-chips">
          ${types.map(tp => `<button class="atl-chip${!activeTypes || activeTypes.has(tp) ? " on" : ""}"
              data-type="${tp}" style="--chip:${(TYPE_STYLE[tp] || {}).color}">
              <i></i>${esc(A.pluralOf(tp))}<b>${counts[tp]}</b></button>`).join("")}
        </div>
      </section>
      ${rels.length ? `<section class="atl-sec">
        <h3>${esc(t("atlas.relationships"))}</h3>
        <div class="atl-rels">
          ${rels.slice(0, 12).map(r => `<button class="atl-rel${!activeRels || activeRels.has(r.code) ? " on" : ""}"
              data-rel="${esc(r.code)}">
              <span dir="auto">${esc(pick(r.en, r.ar))}</span><b>${r.n}</b></button>`).join("")}
        </div>
      </section>` : ""}
      <section class="atl-sec">
        <h3>${esc(t("atlas.refine"))}</h3>
        <label class="atl-check"><input type="checkbox" data-f-evidence
          ${st.filters.evidenceOnly ? "checked" : ""}><span>${esc(t("atlas.withEvidence"))}</span></label>
        <label class="atl-check"><input type="checkbox" data-f-ended
          ${st.filters.hideEnded ? "checked" : ""}><span>${esc(t("atlas.hideEnded"))}</span></label>
      </section>
      <div class="atl-foot">
        <span>${esc(t("atlas.showing"))}</span>
        <b>${num(shownNodes)} / ${num(total)}</b>
        <span>${esc(t("atlas.nodesShort"))}</span>
        <b>${num(shownEdges)}</b>
        <span>${esc(t("atlas.linksShort"))}</span>
      </div>
      <div class="atl-legend">
        ${["corroborated", "single_source", "unverified"].map(v => `
          <span class="atl-verif"><i class="v-${v}"></i>${esc(verifLabel(v))}</span>`).join("")}
      </div>`;

    rail.querySelectorAll("[data-layout]").forEach(b => {
      b.onclick = () => {
        st.layout = b.dataset.layout;
        if (st.mode === "network") st.net.layout = st.layout;
        compute();
      };
    });
    rail.querySelectorAll("[data-type]").forEach(b => {
      b.onclick = () => {
        const set = st.filters.types ? new Set(st.filters.types) : new Set(types);
        if (set.has(b.dataset.type)) set.delete(b.dataset.type); else set.add(b.dataset.type);
        st.filters.types = set.size === types.length ? null : set;
        compute();
      };
    });
    rail.querySelectorAll("[data-rel]").forEach(b => {
      b.onclick = () => {
        const all = rels.map(r => r.code);
        const set = st.filters.rels ? new Set(st.filters.rels) : new Set(all);
        if (set.has(b.dataset.rel)) set.delete(b.dataset.rel); else set.add(b.dataset.rel);
        st.filters.rels = set.size === all.length ? null : set;
        compute();
      };
    });
    const fe = rail.querySelector("[data-f-evidence]");
    if (fe) fe.onchange = () => { st.filters.evidenceOnly = fe.checked; compute(); };
    const fend = rail.querySelector("[data-f-ended]");
    if (fend) fend.onchange = () => { st.filters.hideEnded = fend.checked; compute(); };
  }

  function verifLabel(code) {
    const map = {
      corroborated: t("atlas.corroborated"),
      single_source: t("atlas.singleSource"),
      unverified: t("atlas.unverifiedValue")
    };
    return map[code] || code;
  }

  /* ------------------------------------------------------------------ overview --- */
  /** The overview's second reading: how many relationships join each pair of
   *  record types.  Rows and columns are types, not records — this is the shape
   *  of the whole registry, and it is the same matrix the report publishes. */
  /** Which types have rows of their own to stand a neighbourhood around.
   *  Relationships are records here too, but they are read from the edge they
   *  are, so the counting node in the overview is not a way in. */
  function drillable(type) {
    return type !== "relationship" &&
      (A.state.meta.entities || []).some(e => e.key === type);
  }

  function typeMatrix(data) {
    const m = data.matrix || {};
    const order = (data.matrix_order || Object.keys(m)).filter(k => k !== "relationship");
    if (!order.length) return "";
    const label = (tp) => A.pluralOf(tp);
    const max = Math.max(1, ...order.flatMap(a => order.map(b => (m[a] || {})[b] || 0)));
    const head = order.map((tp, i) => `<th scope="col" title="${esc(label(tp))}">${i + 1}</th>`).join("");
    const body = order.map((a, i) => `<tr>
        <th scope="row"><span class="mx-idx">${i + 1}</span>
          <span class="mx-name${drillable(a) ? "" : " is-count"}"
            ${drillable(a) ? `data-type-focus="${esc(a)}"` : ""}>${esc(label(a))}</span></th>
        ${order.map(b => {
          const v = (m[a] || {})[b] || 0;
          return v
            ? `<td class="mx-cell" style="--mx:${(v / max).toFixed(3)}" title="${esc(label(a))} → ${esc(label(b))}: ${num(v)}"><span>${v > 999 ? Math.round(v / 100) / 10 + "k" : v}</span></td>`
            : `<td class="mx-cell empty"></td>`;
        }).join("")}
      </tr>`).join("");
    return `<div class="atlas-matrix">
      <table class="matrix mx-table">
        <caption class="mx-note small muted">${esc(t("atlas.typeMatrixNote"))}</caption>
        <thead><tr><th class="mx-corner"></th>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table></div>`;
  }

  /** From the overview into a real neighbourhood — still inside the diagram.
   *  The type you pick opens around its best-connected record, which is the
   *  most useful place to start reading a type. */
  async function openNeighbourhood(type) {
    if (!type) return;
    /* "relationships" is a counting node in the overview, not a record type:
       it has no rows of its own to open */
    if (!drillable(type)) {
      A.toast(t("atlas.overviewHint"), "warn");
      return;
    }
    let recordId = null;
    try {
      const res = await A.api.post(`/api/${type}/query`,
        { page_size: 1, sort: { key: "relationships_count", dir: "desc" } });
      const first = (res.items || [])[0];
      if (first) recordId = first.id;
    } catch (e) { /* an empty type simply has nothing to open */ }
    if (!recordId) { A.toast(t("map.noConnections"), "warn"); return; }
    st.mode = "focus";
    st.entity = type;
    st.recordId = recordId;
    st.selection = null;
    st.path = null;
    st.trail = [];
    closePanel();
    /* the record picker still lists the old type's records: reload it for the
       type we just opened into, so the toolbar describes the same view */
    await loadRecordOptions(type, recordId);
    syncModeUi();
    syncToolbarSelects();
    const chosen = st.options.find(o => String(o.id) === String(recordId));
    pushTrail(type, recordId, (chosen && chosen.label) || A.pluralOf(type));
    await load();
    selectNode(`${type}:${recordId}`);
  }

  function renderOverview() {
    const data = st.data || {};
    const totals = data.totals || {};
    const host = els.canvas;
    /* the overview shares the page with the type matrix, so it draws in a
       shorter frame instead of pushing the matrix off the screen */
    const ovH = Math.round(Math.min(H, Math.max(360, W * 0.40)));
    const nodes = (data.nodes || []).map((n, i) => {
      const ang = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, data.nodes.length);
      const rx = Math.max(110, W * 0.30), ry = Math.max(80, ovH * 0.30);
      return Object.assign({}, n, {
        x: W / 2 + Math.cos(ang) * rx, y: ovH / 2 + Math.sin(ang) * ry,
        degree: n.count || 0, record_id: n.type, label: pick(n.label_en, n.label_ar)
      });
    });
    const edges = (data.edges || []).filter(e => st.showStructural || e.kind === "relationship")
      .map(e => Object.assign({}, e, { id: e.id || `${e.source}-${e.target}`,
        directed: true, verification: "corroborated", ended: false, evidence_count: 0 }));
    host.innerHTML = buildScene({
      nodes, edges, focusId: null, layout: "orbit", selection: null, path: null,
      W, H: ovH
    }) + typeMatrix(data) + `<div class="map-legend">
        ${(data.nodes || []).map(n => `<span class="map-legend-item">
          <i class="swatch" style="background:${(TYPE_STYLE[n.type] || {}).color}"></i>
          ${esc(pick(n.label_en, n.label_ar))}<b>${num(n.count || 0)}</b></span>`).join("")}
      </div>
      <div class="map-stats">
        <span>${t("map.recordsTotal")}: <b>${num(totals.records || 0)}</b></span>
        <span>${t("map.relationshipsTotal")}: <b>${num(totals.relationships || 0)}</b></span>
        <span>${t("map.structuralTotal")}: <b>${num(totals.structural_links || 0)}</b></span>
      </div>`;
    mountCanvas();
    host.querySelectorAll("[data-type-focus]").forEach(b => {
      b.onclick = () => openNeighbourhood(b.dataset.typeFocus);
    });
    renderTrail();
    renderRail();
  }

  /* ------------------------------------------------------------------ hud --- */
  function canvasHud() {
    const wrap = document.createElement("div");
    wrap.className = "map-hud";
    wrap.innerHTML = `
      <div class="hud-group">
        <button class="hud-btn" data-zin title="+">+</button>
        <button class="hud-btn" data-zout title="−">−</button>
        <span class="hud-zoom" data-zoom>100%</span>
        <button class="hud-btn" data-zfit title="${esc(t("map.fit"))}">⤢</button>
        <button class="hud-btn" data-zfull title="${esc(t("map.fullscreen"))}">⛶</button>
      </div>
      <div class="hud-group">
        <input type="search" class="hud-search" data-map-search
               placeholder="${esc(t("map.searchNodes"))}" aria-label="${esc(t("map.searchNodes"))}">
        <span class="hud-hits" data-map-hits hidden></span>
      </div>
      <div class="hud-hint keys">${esc(t("map.hints"))}</div>`;
    return wrap;
  }

  function toggleFullscreen() {
    const card = els.atlas.closest(".map-card") || els.atlas;
    const on = card.classList.toggle("is-fullscreen");
    document.body.classList.toggle("map-fullscreen", on);
    setTimeout(() => { if (st.canvas) st.canvas.fit(220); }, 80);
  }

  /* ------------------------------------------------------------- path finder --- */
  function pathDialog(fromId) {
    if (!fromId) return;
    const [ftype, fid] = String(fromId).split(":");
    const body = `<div class="ap-pathdialog">
      <p class="small muted">${esc(t("atlas.pathNote"))}</p>
      <label class="field"><span>${esc(t("atlas.recordType"))}</span>
        <select data-path-type>
          ${A.state.meta.entities.map(e => `<option value="${e.key}">${esc(lang() === "ar" ? e.plural_ar : e.plural_en)}</option>`).join("")}
        </select></label>
      <label class="field"><span>${esc(t("atlas.find"))}</span>
        <input data-path-q autocomplete="off" placeholder="${esc(t("atlas.typeName"))}"></label>
      <div class="ap-pathhits" data-path-hits></div>
    </div>`;
    const m = A.modal({ title: t("atlas.pathTitle"), body, size: "slim",
                        buttons: [{ label: t("common.cancel") }] });
    const typeSel = m.body.querySelector("[data-path-type]");
    const input = m.body.querySelector("[data-path-q]");
    const hitsHost = m.body.querySelector("[data-path-hits]");
    let timer = null;
    const search = async () => {
      const q = input.value.trim();
      if (!q) { hitsHost.innerHTML = ""; return; }
      try {
        const res = await A.api.post(`/api/${typeSel.value}/query`, { q, page_size: 8 });
        hitsHost.innerHTML = (res.items || []).map(r => `
          <button class="ap-pathhit" data-pick="${typeSel.value}:${r.id}">
            <span dir="auto">${esc(A.dispTitle(r, typeSel.value) || r.code)}</span>
            <span class="mono-cell small muted">${esc(r.code || "")}</span></button>`).join("")
          || `<div class="muted small">${esc(t("search.noResults"))}</div>`;
        hitsHost.querySelectorAll("[data-pick]").forEach(b => {
          b.onclick = async () => {
            m.close();
            await runPath(fromId, b.dataset.pick);
          };
        });
      } catch (err) { A.toast(err.message, "err"); }
    };
    input.oninput = () => { clearTimeout(timer); timer = setTimeout(search, 250); };
    typeSel.onchange = search;
    setTimeout(() => input.focus(), 60);
  }

  async function runPath(fromId, toId) {
    const [ft, fi] = String(fromId).split(":");
    const [tt, ti] = String(toId).split(":");
    try {
      const res = await A.api.post("/api/graph/path", {
        from_type: ft, from_id: Number(fi), to_type: tt, to_id: Number(ti), max_depth: 6
      });
      if (!res.found) {
        A.toast(res.exhausted
          ? t("atlas.noChain")
          : t("atlas.notConnected"), "warn", 6000);
        return;
      }
      st.path = {
        nodes: new Set(res.nodes.map(n => n.id)),
        edges: new Set(res.edges.map(e => String(e.id))),
        chain: res
      };
      compute();
      pathPanel(res, fromId, toId);
    } catch (err) { A.toast(err.message, "err"); }
  }

  function pathPanel(res, fromId, toId) {
    const steps = res.nodes.map((n, i) => {
      const edge = res.edges[i];
      return `<button class="ap-step" data-nid="${esc(n.id)}">
          <span class="ap-step-i">${i + 1}</span>
          <span class="ap-step-body"><span dir="auto">${esc(shortLabel(n.label, 30))}</span>
          ${edge ? `<em>${esc(pick(edge.label_en, edge.label_ar))} ·
            ${esc(edge.verification)}</em>` : ""}</span></button>`;
    }).join("");
    openPanel(`
      <div class="ap-head">
        <span class="ap-type sw-path">${esc(t("atlas.pathTitle"))}</span>
        <button class="icon-btn ap-close" data-ap-close aria-label="${esc(t("common.close"))}">×</button>
      </div>
      <h2 class="ap-title">${esc(t("atlas.chainOf", { n: res.length }))}</h2>
      <div class="ap-steps">${steps}</div>
      <div class="ap-actions">
        <button class="btn sm" data-ap-clearpath>${esc(t("atlas.pathClear"))}</button>
      </div>
      <p class="ap-note">${esc(t("atlas.pathSafety"))}</p>`);
    els.panel.querySelectorAll(".ap-step").forEach(b => {
      b.onclick = () => selectNode(b.dataset.nid);
    });
    els.panel.querySelectorAll("[data-ap-clearpath]").forEach(b => {
      b.onclick = () => { clearPath(); };
    });
  }

  function clearPath() {
    st.path = null;
    closePanel();
    compute();
  }

  /* ------------------------------------------------- people & organizations --- */
  function renderNetChips(box) {
    const host = box.querySelector("[data-net-chips]");
    if (!host) return;
    if (!st.net.pins.length) { host.innerHTML = ""; return; }
    host.innerHTML = st.net.pins.map(p => `
      <span class="net-chip"><em>${esc(A.pluralOf(p.type))}</em>
        <span dir="auto">${esc(p.label)}</span>
        <button type="button" data-net-drop="${esc(p.type)}:${p.id}"
                aria-label="${esc(t("map.remove"))}">×</button></span>`).join("")
      + `<button type="button" class="btn sm" data-net-clear>${esc(t("map.clearChosen"))}</button>`;
    host.querySelectorAll("[data-net-drop]").forEach(b => {
      b.onclick = () => {
        const [type, id] = b.dataset.netDrop.split(":");
        st.net.pins = st.net.pins.filter(p => !(p.type === type && String(p.id) === String(id)));
        renderNetChips(box);
        load();
      };
    });
    const clear = host.querySelector("[data-net-clear]");
    if (clear) clear.onclick = () => { st.net.pins = []; renderNetChips(box); load(); };
  }

  function wireNetwork(root) {
    const box = root.querySelector("[data-only-network]");
    if (!box) return;
    let timer = null;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        st.filters.types = null;
        st.filters.rels = null;
        load();
      }, 260);
    };
    const other = box.querySelector("[data-net-other]");
    const syncOther = () => {
      if (other) other.hidden = !st.net.types.some(tp => tp !== "person" && tp !== "institution");
    };
    box.querySelectorAll("[data-net-type]").forEach(input => {
      input.onchange = () => {
        const set = new Set(st.net.types);
        if (input.checked) set.add(input.dataset.netType);
        else set.delete(input.dataset.netType);
        st.net.types = ["person", "institution", "place", "event", "source"].filter(tp => set.has(tp));
        syncOther();
        schedule();
      };
    });
    const qKey = { person: "qPerson", institution: "qOrg", other: "qOther" };
    box.querySelectorAll("[data-net-q]").forEach(input => {
      input.oninput = () => {
        const key = qKey[input.dataset.netQ];
        if (key) st.net[key] = input.value.trim();
        schedule();
      };
    });
    renderNetChips(box);
    const find = box.querySelector("[data-net-find]");
    const hits = box.querySelector("[data-net-hits]");
    let findTimer = null;
    find.oninput = () => {
      clearTimeout(findTimer);
      const q = find.value.trim();
      if (!q) { hits.hidden = true; hits.innerHTML = ""; return; }
      findTimer = setTimeout(async () => {
        const types = st.net.types.length ? st.net.types.slice() : ["person", "institution"];
        const rows = [];
        await Promise.all(types.map(async (tp) => {
          try {
            const res = await A.api.post(`/api/${tp}/query`,
              { q, page_size: 6, sort: { key: "relationships_count", dir: "desc" } });
            (res.items || []).forEach(r => rows.push({
              type: tp, id: r.id, label: A.dispTitle(r, tp) || r.code || ("#" + r.id)
            }));
          } catch (e) { /* a type that fails to search does not blank the others */ }
        }));
        const have = new Set(st.net.pins.map(p => p.type + ":" + p.id));
        const fresh = rows.filter(r => !have.has(r.type + ":" + r.id));
        hits.innerHTML = fresh.length
          ? fresh.map(r => `<button type="button" class="focus-hit" data-type="${esc(r.type)}" data-id="${r.id}">
              <b>${esc(A.pluralOf(r.type))}</b> <span dir="auto">${esc(r.label)}</span></button>`).join("")
          : `<div class="focus-hit none">${esc(t("map.noHits"))}</div>`;
        hits.hidden = false;
        hits.querySelectorAll(".focus-hit[data-id]").forEach(b => {
          b.onclick = () => {
            const label = (b.querySelector("span") || {}).textContent || "";
            const pin = { type: b.dataset.type, id: Number(b.dataset.id), label };
            if (!st.net.pins.some(p => p.type === pin.type && p.id === pin.id)) st.net.pins.push(pin);
            find.value = "";
            hits.hidden = true;
            renderNetChips(box);
            load();
          };
        });
      }, 220);
    };
    find.onkeydown = (ev) => {
      if (ev.key === "Escape") { find.value = ""; hits.hidden = true; }
      if (ev.key === "Enter") {
        const first = hits.querySelector(".focus-hit[data-id]");
        if (first) first.click();
      }
    };
  }

  /* ------------------------------------------------------------------ toolbar --- */
  /** Keep the toolbar honest about where the atlas is: after a drill-in from
   *  the overview the mode segment and the record controls must follow. */
  function syncModeUi() {
    if (!els.root) return;
    els.root.querySelectorAll("[data-mode]").forEach(b =>
      b.classList.toggle("active", b.dataset.mode === st.mode));
    const focusBox = els.root.querySelector("[data-only-focus]");
    if (focusBox) focusBox.hidden = st.mode !== "focus";
    const netBox = els.root.querySelector("[data-only-network]");
    if (netBox) netBox.hidden = st.mode !== "network";
  }

  function syncToolbarSelects() {
    if (els.entitySel) els.entitySel.value = st.entity;
    if (els.depthSel) els.depthSel.value = String(st.depth);
    if (els.recSel) {
      const has = st.options.some(o => String(o.id) === String(st.recordId));
      if (!has && st.recordId != null) {
        st.options.unshift({ id: st.recordId, label: `#${st.recordId}` });
      }
      els.recSel.innerHTML = st.options.map(o =>
        `<option value="${o.id}" ${String(o.id) === String(st.recordId) ? "selected" : ""}>
          ${esc(shortLabel(o.label, 44))}</option>`).join("");
      els.recSel.value = String(st.recordId);
    }
  }

  async function applyParams(params) {
    const wanted = /^(\w+)[:/](\d+)$/.exec((params && params.focus) || "");
    if (wanted) {
      if ((A.state.meta.entities || []).some(e => e.key === wanted[1])) st.entity = wanted[1];
      st.recordId = Number(wanted[2]);
      st.mode = "focus";
      if (!st.trail.length) pushTrail(st.entity, st.recordId, `${st.entity} #${st.recordId}`);
    }
    if (params && params.mode === "focus") st.mode = "focus";
    if (params && params.mode === "types") st.mode = "types";
    if (params && ["orbit", "force", "matrix"].includes(params.layout)) st.layout = params.layout;
    await loadRecordOptions(st.entity, st.recordId);
  }

  /* ======================================================================
     the view entry point
     ====================================================================== */
  A.views.map = async function (root, params) {
    A.crumbs([{ label: t("map.title") }]);
    /* the reserved marks are geometry from the standard: fetched once, cached,
       and a failure here must not cost the reader the whole diagram */
    try { await A.crce.standard(); } catch (e) { /* the generic glyphs will do */ }
    st.trail = [];
    st.selection = null;
    st.path = null;
    await applyParams(params);
    if (st.mode === "focus" && !st.recordId && st.options.length) st.recordId = st.options[0].id;
    if (!st.trail.length && st.recordId) {
      const node = st.options.find(o => String(o.id) === String(st.recordId));
      pushTrail(st.entity, st.recordId, node ? node.label : `${st.entity} #${st.recordId}`);
    }

    root.innerHTML = `
      <div class="page-head">
        <div class="titles">
          <h1>${esc(t("map.title"))}</h1>
          <div class="sub">${esc(t("atlas.subtitle"))}</div>
        </div>
        <div class="actions">
          <button class="btn" data-map-print>${icon("download")} ${esc(t("map.saveSvg"))}</button>
        </div>
      </div>
      <div class="card tight map-card atlas-card">
        <div class="map-toolbar">
          <div class="seg" role="tablist">
            <button class="seg-btn ${st.mode === "types" ? "active" : ""}" data-mode="types">
              ${esc(t("map.overview"))}</button>
            <button class="seg-btn ${st.mode === "network" ? "active" : ""}" data-mode="network">
              ${esc(t("map.network"))}</button>
            <button class="seg-btn ${st.mode === "focus" ? "active" : ""}" data-mode="focus">
              ${esc(t("map.focus"))}</button>
          </div>
          <div class="field inline net-filters" data-only-network ${st.mode === "network" ? "" : "hidden"}>
            <fieldset class="net-types">
              <legend>${esc(t("map.shownTypes"))}</legend>
              ${["person", "institution", "place", "event", "source"].map(tp => `
                <label><input type="checkbox" data-net-type="${tp}"
                  ${st.net.types.includes(tp) ? "checked" : ""}>
                  <span>${esc(A.pluralOf(tp))}</span></label>`).join("")}
            </fieldset>
            <label class="net-search"><span>${esc(t("map.searchPeople"))}</span>
              <input type="search" data-net-q="person" value="${esc(st.net.qPerson)}"
                     placeholder="${esc(t("map.peoplePh"))}" aria-label="${esc(t("map.searchPeople"))}"
                     autocomplete="off"></label>
            <label class="net-search"><span>${esc(t("map.searchOrgs"))}</span>
              <input type="search" data-net-q="institution" value="${esc(st.net.qOrg)}"
                     placeholder="${esc(t("map.orgsPh"))}" aria-label="${esc(t("map.searchOrgs"))}"
                     autocomplete="off"></label>
            <label class="net-search" data-net-other ${st.net.types.some(tp => tp !== "person" && tp !== "institution") ? "" : "hidden"}>
              <span>${esc(t("map.searchOther"))}</span>
              <input type="search" data-net-q="other" value="${esc(st.net.qOther)}"
                     placeholder="${esc(t("map.otherPh"))}" aria-label="${esc(t("map.searchOther"))}"
                     autocomplete="off"></label>
            <div class="net-pick">
              <label class="net-search"><span>${esc(t("map.addRecords"))}</span>
                <input type="search" data-net-find value=""
                       placeholder="${esc(t("map.addPh"))}" aria-label="${esc(t("map.addRecords"))}"
                       autocomplete="off"></label>
              <div class="focus-hits" data-net-hits hidden></div>
              <div class="net-chips" data-net-chips></div>
            </div>
            <p class="net-hint">${esc(t("map.networkHint"))}</p>
          </div>
          <div class="field inline" data-only-focus ${st.mode === "focus" ? "" : "hidden"}>
            <select data-focus-entity>
              ${A.state.meta.entities.map(e =>
                `<option value="${e.key}" ${st.entity === e.key ? "selected" : ""}>${esc(lang() === "ar" ? e.plural_ar : e.plural_en)}</option>`).join("")}
            </select>
            <select data-focus-record></select>
            <select data-focus-depth>
              <option value="1" ${st.depth === 1 ? "selected" : ""}>${esc(t("map.depth1"))}</option>
              <option value="2" ${st.depth === 2 ? "selected" : ""}>${esc(t("map.depth2"))}</option>
            </select>
            <span class="focus-find">
              <input type="search" data-focus-search placeholder="${esc(t("map.findRecord"))}"
                     aria-label="${esc(t("map.findRecord"))}" autocomplete="off">
              <div class="focus-hits" data-focus-hits hidden></div>
            </span>
          </div>
        </div>
        <div class="atlas" data-atlas>
          <aside class="atlas-rail" data-atlas-rail aria-label="${esc(t("atlas.filters"))}"></aside>
          <div class="atlas-main">
            <div class="atlas-trailbar" data-atlas-trail></div>
            <div class="atlas-canvas" data-atlas-canvas></div>
          </div>
          <aside class="atlas-panel" data-atlas-panel hidden
                 aria-label="${esc(t("atlas.panel"))}"></aside>
        </div>
      </div>`;

    els.atlas = root.querySelector("[data-atlas]");
    els.rail = root.querySelector("[data-atlas-rail]");
    els.canvas = root.querySelector("[data-atlas-canvas]");
    els.panel = root.querySelector("[data-atlas-panel]");
    els.trail = root.querySelector("[data-atlas-trail]");
    els.root = root;
    els.entitySel = root.querySelector("[data-focus-entity]");
    els.recSel = root.querySelector("[data-focus-record]");
    els.depthSel = root.querySelector("[data-focus-depth]");
    A.hydrateIcons(root);

    root.querySelectorAll("[data-mode]").forEach(b => {
      b.onclick = () => {
        st.mode = b.dataset.mode;
        if (st.mode === "network" && !st.net.seen) {
          st.layout = st.net.layout || "force";
          st.net.seen = true;
        }
        syncModeUi();
        st.selection = null; st.path = null;
        /* the focus view needs a record to be about: if the atlas was opened on
           the overview, adopt the first one rather than drawing nothing */
        if (st.mode === "focus" && !st.recordId && st.options.length) {
          st.recordId = st.options[0].id;
          st.trail = [];
          pushTrail(st.entity, st.recordId, st.options[0].label);
        }
        if (st.mode === "focus") syncToolbarSelects();
        closePanel();
        renderTrail();
        load();
      };
    });
    wireNetwork(root);
    els.entitySel.onchange = async () => {
      st.entity = els.entitySel.value;
      await loadRecordOptions(st.entity);
      st.recordId = st.options.length ? st.options[0].id : null;
      syncToolbarSelects();
      st.trail = [];
      if (st.recordId) pushTrail(st.entity, st.recordId,
        (st.options.find(o => o.id === st.recordId) || {}).label);
      closePanel();
      load();
    };
    els.recSel.onchange = () => {
      st.recordId = Number(els.recSel.value);
      st.path = null;
      pushTrail(st.entity, st.recordId,
        (st.options.find(o => String(o.id) === String(st.recordId)) || {}).label);
      closePanel();
      load();
    };
    els.depthSel.onchange = () => { st.depth = Number(els.depthSel.value); load(); };

    const find = root.querySelector("[data-focus-search]");
    const hits = root.querySelector("[data-focus-hits]");
    let findTimer = null;
    find.oninput = () => {
      clearTimeout(findTimer);
      const q = find.value.trim();
      if (!q) { hits.hidden = true; hits.innerHTML = ""; return; }
      findTimer = setTimeout(async () => {
        let rows = [];
        try {
          const res = await A.api.post(`/api/${st.entity}/query`,
            { q, page_size: 8, sort: { key: "relationships_count", dir: "desc" } });
          rows = res.items || [];
        } catch (e) { rows = []; }
        hits.innerHTML = rows.length
          ? rows.map(r => {
              const o = optionFor(st.entity, r);
              return `<button type="button" class="focus-hit" data-id="${o.id}">${esc(o.label)}</button>`;
            }).join("")
          : `<div class="focus-hit none">${esc(t("map.noHits"))}</div>`;
        hits.hidden = false;
        hits.querySelectorAll(".focus-hit[data-id]").forEach(b => {
          b.onclick = () => {
            const id = Number(b.dataset.id);
            const row = rows.find(r => r.id === id);
            if (row && !st.options.some(o => String(o.id) === String(id))) {
              st.options.unshift(optionFor(st.entity, row));
            }
            st.recordId = id;
            syncToolbarSelects();
            pushTrail(st.entity, id, row ? optionFor(st.entity, row).label : null);
            find.value = ""; hits.hidden = true;
            closePanel();
            load();
          };
        });
      }, 220);
    };
    find.onkeydown = (ev) => {
      if (ev.key === "Escape") { find.value = ""; hits.hidden = true; }
      if (ev.key === "Enter") {
        const first = hits.querySelector(".focus-hit[data-id]");
        if (first) first.click();
      }
    };

    root.querySelector("[data-map-print]").onclick = () => {
      const svg = root.querySelector("svg.relmap");
      if (!svg) return;
      const blob = new Blob(
        ['<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" ' +
         'style="background:#fff;font-family:system-ui"><style>' +
         '.map-label{font-size:12px;fill:#334}.atlas-count{font-size:12px;font-weight:700;fill:#123}' +
         '</style>' + svg.innerHTML + "</svg>"], { type: "image/svg+xml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `siraj-atlas-${st.entity}-${st.recordId}.svg`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    };

    /* keyboard: Esc closes, Alt+← walks the trail, / finds a node */
    st._keys = (ev) => {
      if (ev.key === "Escape") {
        if (st.selection || (els.panel && !els.panel.hidden)) { closePanel(); ev.preventDefault(); }
        else if (st.path) { clearPath(); ev.preventDefault(); }
      }
      if (ev.altKey && ev.key === "ArrowLeft") { trailBack(); ev.preventDefault(); }
    };
    document.addEventListener("keydown", st._keys);

    /* "/" belongs to the diagram while the diagram is on screen: the global
       shortcut would otherwise send the caret to the registry search box. */
    st._slash = (ev) => {
      if (ev.key !== "/" || ev.defaultPrevented) return;
      const el = document.activeElement;
      const tag = el && el.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (el && el.isContentEditable)) return;
      const box = els.canvas && els.canvas.querySelector("[data-map-search]");
      if (!box) return;
      ev.preventDefault();
      ev.stopPropagation();
      box.focus();
      if (box.select) box.select();
    };
    document.addEventListener("keydown", st._slash, true);

    let resizeTimer = null;
    st._resize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (!els.canvas || !els.canvas.isConnected) return;
        if (measureStage()) compute();
      }, 220);
    };
    window.addEventListener("resize", st._resize);

    syncToolbarSelects();
    renderTrail();
    await load();
  };

  A.views.map.__dispose = () => {
    if (st._keys) document.removeEventListener("keydown", st._keys);
    if (st._slash) document.removeEventListener("keydown", st._slash, true);
    if (st._resize) window.removeEventListener("resize", st._resize);
    st._resize = null;
    st._keys = null;
    st._slash = null;
  };
})();
