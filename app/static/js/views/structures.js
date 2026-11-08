/* ============================================================================
   SIRAJ · views/structures.js — the structure deck
   ----------------------------------------------------------------------------
   One registry, six ways of seeing it, one set of rules.

   The page is a *host*, not a chart: it asks /api/structures for a taxonomy and
   hands the tree to the kernel in components/viz.js, which knows nothing about
   people or institutions. Every structure below is a pure function of that
   model, so the same node can be read as a rectangle, an arc, a flow, a cell, a
   disc or a node — and the numbers behind all six are the same numbers.

   Rules this view keeps, because the registry does:
     · every count is a database count, never a visual estimate; a folded branch
       says so and the legend repeats it
     · selection opens a panel beside the picture (never a navigation away) and
       the panel carries an explicit way to reach the records
     · camera, keyboard and motion are shared, so nothing has to be relearned
       from one structure to the next
     · the table is not a fallback nobody uses — it is the same model, readable
       by a screen reader and exportable
   ========================================================================== */
(function (A) {
  "use strict";
  const { t, esc, fmtNum } = A;
  const api = (u) => A.api.get(u);
  const V = A.viz;

  const STRUCTS = ["treemap", "sunburst", "sankey", "matrix", "circles", "tree"];
  const PREFS_KEY = "siraj.structures.v1";
  const NOT_RECORDED = "not recorded";

  const S = {
    ready: false, sources: [], payload: null, model: null, index: null,
    source: "people", structure: "treemap", focus: "root", depth: 3,
    maxChildren: 24, labels: true, values: true, legend: true, table: false,
    /* leaves on: deepest branches list the actual people / institutions / … */
    leaves: true,
    hover: null, selected: null, query: "", minimap: true,
    open: new Set(), openTouched: false,
    viewport: null, interact: null, busy: false,
  };

  function prefs() {
    try { return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        structure: S.structure, source: S.source, depth: S.depth,
        maxChildren: S.maxChildren, labels: S.labels, values: S.values,
        legend: S.legend, minimap: S.minimap, leaves: S.leaves,
      }));
    } catch (e) { /* private mode: preferences simply do not persist */ }
  }

  function modelDepth() {
    /* records sit one level under the taxonomy; their links sit one level under that */
    let d = S.depth;
    if (S.leaves && S.payload && S.payload.include_leaves) d += 1;
    if (S.payload && S.payload.include_links) d += 1;
    return d;
  }

  const kids = (n) => (n && Array.isArray(n.__kids) ? n.__kids : []);
  const val = (n) => (n && n.__v ? n.__v : 0);
  const named = (n) => (A.state.lang === "ar" ? (n.label_ar || n.label_en) : (n.label_en || n.label_ar)) || "—";
  const pct = (v, total) => (total ? (v / total) * 100 : 0);
  const pctText = (v, total) => (total ? (pct(v, total) >= 10 ? pct(v, total).toFixed(0) : pct(v, total).toFixed(1)) + "%" : "—");
  const short = (n) => (n.label_en || "").length;

  /* ═══════════════════════════════════════════════════════════ geometry ═══ */
  /* Every function takes (model, focus) and returns
       { w, h, parts[] , labels[] , heads[] }
     A part is a drawable with a node attached: { n, tag, attrs, cls }. */

  const W = 1000, H = 640;

  function treemap(model, focus) {
    const parts = [], labels = [];
    const cells = kids(focus);
    if (!cells.length) return { w: W, h: H, parts, labels };
    const rows = V.squarify(cells.map(n => ({ value: val(n), node: n })), 0, 0, W, H);
    for (const r of rows) {
      const n = r.item.node, col = model.colorOf(n);
      parts.push({ n, tag: "rect", cls: "topo-cell d1", attrs: {
        x: r.x + 1, y: r.y + 1, width: Math.max(0, r.w - 2), height: Math.max(0, r.h - 2),
        rx: 3, fill: col, "fill-opacity": 0.9 } });
      const sub = kids(n);
      if (sub.length && r.w > 42 && r.h > 30) {
        const inner = V.squarify(sub.map(k => ({ value: val(k), node: k })),
                                 r.x + 2, r.y + 2, r.w - 4, r.h - 4);
        for (const q of inner) {
          parts.push({ n: q.item.node, tag: "rect", cls: "topo-cell d2", attrs: {
            x: q.x + 0.5, y: q.y + 0.5, width: Math.max(0, q.w - 1), height: Math.max(0, q.h - 1),
            rx: 2, fill: col, "fill-opacity": 0.34 } });
          if (q.w > 62 && q.h > 17) {
            labels.push({ x: q.x + 5, y: q.y + 13, text: V.fit(named(q.item.node), q.w - 10, 10.5),
                          size: 10.5, cls: "lbl lbl-d2" });
          }
        }
      }
      if (r.w > 54 && r.h > 17) {
        const ty = r.y + Math.min(15, Math.max(11, r.h / 2));
        labels.push({ x: r.x + 6, y: ty, text: V.fit(named(n), r.w - 12, 12.5),
                      size: 12.5, cls: "lbl lbl-d1" });
        if (S.values && r.w > 58 && r.h > 32) {
          labels.push({ x: r.x + 6, y: ty + 15, text: fmtNum(val(n)) + " · " + pctText(val(n), val(focus)),
                        size: 10.5, cls: "lbl lbl-v" });
        }
      }
    }
    return { w: W, h: H, parts, labels };
  }

  function sunburst(model, focus) {
    const parts = [], labels = [];
    const total = val(focus) || 1;
    /* the rings live inside a positive box: a camera that has to guess where
       negative coordinates went will always frame the picture badly */
    const cx = W / 2, cy = H / 2, r0 = 108, step = 100;
    const TAU = Math.PI * 2;
    const ringOne = [];

    const level = (nodes, depth, a0, a1) => {
      const R0 = r0 + step * (depth - 1), R1 = R0 + step - 3;
      const span = a1 - a0;
      let a = a0;
      for (const n of nodes) {
        const share = val(n) / total;
        const b = a + span * share;
        parts.push({
          n, tag: "path", cls: "topo-arc d" + depth,
          attrs: { d: V.arcPath(cx, cy, R0, R1, a, Math.max(a, b - 0.004)),
                   fill: model.colorOf(n),
                   "fill-opacity": depth === 1 ? 0.92 : 0.42 + 0.16 * depth },
        });
        if (depth === 1) ringOne.push({ n, mid: (a + b) / 2, span: b - a, r: R1 });
        const sub = kids(n);
        if (sub.length && depth < 3) level(sub, depth + 1, a, b);
        a = b;
      }
    };
    if (kids(focus).length) level(kids(focus), 1, -Math.PI / 2, -Math.PI / 2 + TAU);

    /* Labels sit outside the rings and are placed largest-first with an angular
       reservation, because a curved caption inside a 3 %-wide arc is not a
       caption — it is a smudge. What does not fit keeps its colour and its
       hover; the table carries every name. */
    if (S.labels) {
      const placed = [];
      const cand = ringOne.slice().sort((x, y) => val(y.n) - val(x.n));
      for (const c of cand) {
        if (placed.length >= 12) break;
        /* room is claimed by the label, not by the arc: a long name needs a
           wider angle than a short one, so the reservation is measured in
           pixels of circumference */
        const need = (named(c.n).length * 6.2 + 16) / (c.r + 8);
        if (placed.some(p => {
          const d = Math.abs(((p.mid - c.mid + Math.PI * 3) % (Math.PI * 2)) - Math.PI);
          return d < Math.max(0.09, need, (named(p.n).length * 6.2 + 16) / (p.r + 8));
        })) continue;
        placed.push(c);
        const flip = Math.cos(c.mid) < 0;
        const rr = c.r + 7;
        labels.push({
          x: cx + rr * Math.cos(c.mid) + (flip ? -3 : 3),
          y: cy + rr * Math.sin(c.mid) + 3.5,
          text: V.fit(named(c.n), 128, 10.5), size: 10.5,
          anchor: flip ? "end" : "start", cls: "lbl lbl-arc",
        });
      }
    }

    /* the hub is the focus itself: one ring of text, never a floating caption */
    labels.push({ x: cx, y: cy - 6, text: V.fit(named(focus), 170, 15), size: 15, anchor: "middle", cls: "hub-name" });
    labels.push({ x: cx, y: cy + 16, text: fmtNum(val(focus)) + " · " + t("viz.records"), size: 11.5,
                  anchor: "middle", cls: "hub-value" });
    return { w: W, h: H, parts, labels };
  }

  function sankey(model, focus) {
    const parts = [], labels = [], heads = [];
    const total = val(focus) || 1;
    const MAX1 = 12, MAX2 = 2;          // a flow diagram is read, not enumerated

    const l1 = kids(focus).slice().sort((a, b) => val(b) - val(a));
    const kept1 = l1.slice(0, MAX1);
    const levels = [[focus], kept1, []];
    /* the third column is ordered by parent, never by size across parents:
       ranking the whole pool would interleave siblings and cross the ribbons,
       and a crossing flow diagram is a diagram of nothing */
    for (const n of kept1) {
      levels[2].push(...kids(n).slice().sort((a, b) => val(b) - val(a)).slice(0, MAX2));
    }

    const nodesW = 15, gap = 8, padT = 30, padB = 18;
    const colX = (i) => 34 + i * ((W - 96) / 2);
    const usable = H - padT - padB;
    const pos = new Map();

    for (let li = 0; li < levels.length; li++) {
      const list = levels[li];
      const nGaps = Math.max(0, list.length - 1);
      /* one scale for all three columns, taken from the whole: a column that
         omits its tail then shows the omission instead of hiding it */
      const scale = (usable - gap * nGaps) / total;
      const sumH = list.reduce((s, n) => s + Math.max(1.5, val(n) * scale), 0) + gap * nGaps;
      let y = padT + Math.max(0, (usable - sumH) / 2);
      for (const n of list) {
        const hh = Math.max(1.5, val(n) * scale);
        pos.set(n, { x: colX(li), y, h: hh });
        parts.push({ n, tag: "rect", cls: "sk-node", attrs: {
          x: colX(li), y, width: nodesW, height: hh, rx: 2,
          fill: li === 0 ? model.colorOf(focus) : model.colorOf(n),
          "fill-opacity": li === 0 ? 1 : 0.95 } });
        if (S.labels && hh > 9) {
          labels.push({ x: colX(li) + nodesW + 6, y: y + Math.min(hh / 2 + 4, hh), size: 10.5,
                        anchor: "start", text: V.fit(named(n), 150, 10.5), cls: "lbl lbl-sk" });
        }
        y += hh + gap;
      }
    }

    /* flows: a child's height sits inside its parent's band, so a band is never
       wider than the thing it comes from */
    const cursor = new Map();
    for (let li = 1; li < levels.length; li++) {
      for (const n of levels[li]) {
        const p = n.__p;
        if (!pos.has(p) || !pos.has(n)) continue;
        const pp = pos.get(p), np = pos.get(n);
        const ph = (val(n) / (val(p) || 1)) * pp.h;
        const off = cursor.get(p) || 0;
        cursor.set(p, off + ph);
        parts.push({
          n, tag: "path", cls: "sk-flow",
          attrs: { d: V.sankeyLink(pp.x + nodesW, pp.y + off, pp.y + off + ph,
                                   np.x, np.y, np.y + np.h),
                   fill: model.colorOf(n), "fill-opacity": 0.24 },
        });
      }
    }

    /* what was left out is stated, in words, at the top of the picture */
    const chain = (S.payload && S.payload.chain) || [];
    const nameAt = (k) => { const c = chain[k]; return c ? (A.state.lang === "ar" ? c.label_ar : c.label_en) : ""; };
    heads.push({ x: colX(0) + 20, y: 12, text: V.fit(named(focus), 150, 11) });
    heads.push({ x: colX(1) + 20, y: 12,
      text: `${nameAt(0)} — ${kept1.length} / ${l1.length}` });
    heads.push({ x: colX(2) + 20, y: 12,
      text: `${nameAt(1)} — ${levels[2].length} ${t("viz.shown")}` });
    return { w: W, h: H, parts, labels, heads };
  }


  function matrix(model, focus) {
    const parts = [], labels = [], heads = [];
    const rowsAll = kids(focus).slice().sort((a, b) => val(b) - val(a));
    const rows = rowsAll.slice(0, 10);
    const colMap = new Map();
    for (const r of rowsAll) {
      for (const c of kids(r)) {
        const key = `${(c.meta && c.meta.dimension) || "?"}=${(c.meta && c.meta.raw) || c.id}`;
        const hit = colMap.get(key);
        if (hit) { hit.v += val(c); hit.n = hit.n || c; }
        else colMap.set(key, { v: val(c), n: c, key });
      }
    }
    const cols = [...colMap.values()].sort((a, b) => b.v - a.v).slice(0, 14);
    const left = 176, top = 204, cw = (W - left - 60) / Math.max(1, cols.length);
    const ch = Math.min(40, (H - top - 26) / Math.max(1, rows.length));
    const max = Math.max(1, ...cols.map(c => c.v));

    for (let ri = 0; ri < rows.length; ri++) {
      const r = rows[ri];
      labels.push({ x: left - 10, y: top + ri * ch + ch / 2 + 4, text: V.fit(named(r), left - 30, 11),
                    size: 11, anchor: "end", cls: "lbl lbl-row" });
      let acc = 0;
      for (let ci = 0; ci < cols.length; ci++) {
        const col = cols[ci];
        const hit = kids(r).find(c => `${(c.meta && c.meta.dimension) || "?"}=${(c.meta && c.meta.raw) || c.id}` === col.key);
        const v = hit ? val(hit) : 0;
        acc += v;
        parts.push({
          n: hit || null, tag: "rect", cls: "mx-cell" + (v ? "" : " is-zero"),
          attrs: { x: left + ci * cw + 1, y: top + ri * ch + 1, width: cw - 2, height: ch - 2, rx: 2,
                   fill: v ? model.colorOf(r) : "transparent",
                   "fill-opacity": v ? 0.18 + 0.78 * Math.pow(v / max, 0.6) : 0 },
        });
        if (S.values && v && cw > 34 && ch > 20) {
          labels.push({ x: left + ci * cw + cw / 2, y: top + ri * ch + ch / 2 + 3.5,
                        text: String(v), size: 9.5, anchor: "middle", cls: "lbl lbl-cell" });
        }
      }
      labels.push({ x: W - 12, y: top + ri * ch + ch / 2 + 4, text: fmtNum(acc), size: 10,
                    anchor: "end", cls: "lbl lbl-total" });
    }
    for (let ci = 0; ci < cols.length; ci++) {
      const x = left + ci * cw + cw / 2;
      /* written upward, one vertical strip per column: a diagonal header in a
          54-pixel column lands on the first row sooner or later */
      labels.push({ x, y: top - 18, text: V.fit(named(cols[ci].n), top - 32, 10), size: 10,
                    anchor: "start", rotate: -90, cls: "lbl lbl-col" });
    }
    heads.push({ x: 12, y: top - 168, text: t("viz.matrixCols") });
    heads.push({ x: W - 12, y: H - 6, text: t("viz.matrixRows"), anchor: "end" });
    return { w: W, h: H, parts, labels, heads };
  }

  function circles(model, focus) {
    const parts = [], labels = [];
    const items = kids(focus).map(n => ({ value: val(n), node: n }));
    if (!items.length) return { w: W, h: H, parts, labels };
    const placed = V.pack(items, 8, 8, W - 16, H - 16);
    for (const p of placed) {
      const n = p.item.node, col = model.colorOf(n);
      parts.push({ n, tag: "circle", cls: "ci-disc", attrs: {
        cx: p.x, cy: p.y, r: p.r, fill: col, "fill-opacity": 0.22,
        stroke: col, "stroke-width": 1.2 } });
      if (S.labels && p.r > 18) {
        labels.push({ x: p.x, y: p.y - (p.r > 30 ? 3 : 1), text: V.fit(named(n), p.r * 1.7, Math.min(15, p.r / 3)),
                      size: Math.min(15, p.r / 3), anchor: "middle", cls: "lbl lbl-ci" });
      }
      if (S.values && p.r > 30) {
        labels.push({ x: p.x, y: p.y + 13, text: fmtNum(val(n)), size: 10.5, anchor: "middle", cls: "lbl lbl-v" });
      }
      /* second ring: the children, placed inside their parent's disc */
      const sub = kids(n);
      if (sub.length && p.r > 26) {
        const box = p.r * 1.32;
        const inner = V.pack(sub.map(k => ({ value: val(k), node: k })),
                             p.x - box / 2, p.y - box / 2, box, box);
        for (const q of inner) {
          if (q.r < 2.5) continue;
          const qcol = model.colorOf(q.item.node);
          parts.push({ n: q.item.node, tag: "circle", cls: "ci-sub", attrs: {
            cx: q.x, cy: q.y, r: q.r * 0.92, fill: qcol, "fill-opacity": 0.5,
            stroke: qcol, "stroke-width": 0.6 } });
          if (S.labels && q.r > 22) {
            labels.push({ x: q.x, y: q.y + 3.5, text: V.fit(named(q.item.node), q.r * 1.6, 9.5),
                          size: 9.5, anchor: "middle", cls: "lbl lbl-ci2" });
          }
        }
      }
    }
    return { w: W, h: H, parts, labels };
  }

  function tree(model, focus) {
    const parts = [], labels = [], heads = [];
    /* the outline has to be able to reach a person, then the records linked to them */
    const depthMax = Math.max(1, modelDepth());
    const nodeW = 188, nodeH = 22, gapY = 5, stepX = 228;
    let leafY = 0;
    let hidden = 0;

    /* An outline, not a plate of spaghetti: a branch opens when it is asked to.
       What is closed says how much is behind it, so nothing is silently absent. */
    const isOpen = (n) => n === focus || S.open.has(n.id);
    const visit = (n, d) => {
      const all = kids(n);
      const cs = d < depthMax && isOpen(n) ? all : [];
      if (!cs.length && all.length) hidden += all.length;
      const rec = { n, d, x: 24 + d * stepX, c: [] };
      if (!cs.length) { rec.y = leafY; leafY += nodeH + gapY; }
      else {
        for (const c of cs) rec.c.push(visit(c, d + 1));
        rec.y = (rec.c[0].y + rec.c[rec.c.length - 1].y) / 2;
      }
      nodes.push(rec);
      return rec;
    };
    const nodes = [];
    /* Open the largest path all the way to individual records, and a few of its
       siblings at the top, so the first frame is the people and organizations
       themselves — not only the headings they sit under. */
    if (!S.openTouched) {
      S.open = new Set();
      let cur = focus;
      let step = 0;
      while (cur && step < 8) {
        const cs = kids(cur).filter(n => !(n.meta && n.meta.synthetic));
        if (!cs.length) break;
        const ranked = cs.slice().sort((a, b) => val(b) - val(a));
        const breadth = step === 0 ? 4 : 1;
        ranked.slice(0, breadth).forEach(n => { if (kids(n).length) S.open.add(n.id); });
        const next = ranked[0];
        if (!kids(next).length) break;
        if (next.meta && next.meta.record) break;
        cur = next;
        step++;
      }
    }
    visit(focus, 0);
    const totalH = Math.max(240, leafY + 24);
    for (const rec of nodes) {
      const p = nodes.find(x => x.c.indexOf(rec) >= 0);
      if (p) {
        parts.push({ n: rec.n, tag: "path", cls: "tr-edge", attrs: {
          d: `M${p.x + nodeW} ${p.y + nodeH / 2}C${p.x + nodeW + 46} ${p.y + nodeH / 2} ${rec.x - 46} ${rec.y + nodeH / 2} ${rec.x} ${rec.y + nodeH / 2}`,
          fill: "none", stroke: model.colorOf(rec.n), "stroke-opacity": 0.55 } });
      }
      const col = model.colorOf(rec.n);
      const hasKids = kids(rec.n).length > 0;
      const isRec = !!(rec.n.meta && rec.n.meta.record && !rec.n.meta.synthetic);
      parts.push({ n: rec.n, tag: "rect", cls: "tr-node" + (hasKids ? " has-kids" : "") + (isRec ? " is-record" : ""), attrs: {
        x: rec.x, y: rec.y, width: nodeW, height: nodeH, rx: 4,
        fill: rec.n === focus ? col : A.viz.alpha(col, isRec ? 0.34 : 0.14),
        stroke: col, "stroke-width": isRec || rec.n === focus ? 1.6 : 1 } });
      if (hasKids) {
        labels.push({ x: rec.x + 7, y: rec.y + 14, text: isOpen(rec.n) ? "▾" : "▸",
                      size: 10, cls: "lbl lbl-tr-caret" });
      }
      labels.push({ x: rec.x + (hasKids ? 20 : 8), y: rec.y + 14, text: V.fit(named(rec.n), nodeW - 74, 10.5),
                    size: 10.5, cls: "lbl lbl-tr" });
      labels.push({ x: rec.x + nodeW - 7, y: rec.y + 14, text: fmtNum(val(rec.n)), size: 9.5,
                    anchor: "end", cls: "lbl lbl-tr-v" });
    }
    if (hidden) heads.push({ x: 24, y: 10, text: t("viz.treeClosed", { n: fmtNum(hidden) }) });
    return { w: 24 + depthMax * stepX + nodeW + 40, h: totalH, parts, labels, heads };
  }


  const GEO = { treemap, sunburst, sankey, matrix, circles, tree };

  /* ═════════════════════════════════════════════════════════════ painting ═══ */
  function attr(a) {
    let s = "";
    for (const k in a) {
      if (a[k] == null) continue;
      s += ` ${k}="${String(a[k]).replace(/"/g, "&quot;")}"`;
    }
    return s;
  }

  function paint(geo) {
    const world = document.querySelector("[data-viz-world]");
    if (!world) return;
    const idx = S.index;
    const shape = (p) => {
      const i = p.n ? idx.get(p.n) : null;
      const a = Object.assign({}, p.attrs);
      if (p.tag === "rect") { a.tabindex = i == null ? null : "0"; }
      return `<${p.tag}${attr(a)}${i == null ? "" : ` data-nid="${i}" role="img"`} class="${p.cls || ""}"></${p.tag}>`;
    };
    const text = (l) => {
      const tr = l.rotate != null ? ` transform="rotate(${l.rotate} ${l.x} ${l.y})"` : "";
      const anchor = l.anchor ? ` text-anchor="${l.anchor}"` : "";
      const bl = l.baseline ? ` dominant-baseline="${l.baseline}"` : "";
      return `<text x="${l.x.toFixed(1)}" y="${l.y.toFixed(1)}"${anchor}${bl}${tr} `
        + `class="${l.cls || "lbl"}"${l.size ? ` font-size="${l.size}"` : ""}>${esc(l.text)}</text>`;
    };
    world.innerHTML = geo.parts.map(shape).join("") + geo.labels.map(text).join("");
    const pass = geo.parts.filter(p => p.n).length;
    if (pass) V.stagger([...world.querySelectorAll("[data-nid]")], { step: 4, limit: 700 });
    if (S.viewport) {
      const bbox = { x: 0, y: 0, w: geo.w, h: geo.h };
      S.viewport.setBounds(bbox);
    }
  }

  function heads(geo) {
    const host = document.querySelector("[data-viz-heads]");
    if (!host) return;
    const list = (geo.heads || []).filter(h => h && h.text);
    host.innerHTML = list.length
      ? `<div class="viz-heads-row">${list.map(h => `<span>${esc(h.text)}</span>`).join("")}</div>`
      : "";
  }

  /* ═══════════════════════════════════════════════════════════ the shell ═══ */
  function srcOptions() {
    /* grouped picker: registry dimension chains first, then the military
       module structures (single-module hierarchies and cross-module
       compositions) — every source stays one selectable row */
    const groups = { registry: [], modules: [] };
    S.sources.forEach(function (s) { (groups[s.family] || groups.registry).push(s); });
    const opt = s => `<option value="${esc(s.id)}"\n              ${s.id === S.source ? "selected" : ""}>${esc(A.state.lang === "ar" ? s.label_ar : s.label_en)} · ${fmtNum(s.total)}</option>`;
    const grp = (key, label) => groups[key].length
      ? `<optgroup label="${esc(label)}">${groups[key].map(opt).join("")}</optgroup>` : "";
    return grp("registry", t("viz.groupRegistry")) + grp("modules", t("viz.groupModules"));
  }

  function shell() {
    return `
    <style>${""}</style>
    <div class="viz-deck" data-viz>
      <div class="viz-bar">
        <div class="viz-tabs" role="tablist" aria-label="${esc(t("viz.structure"))}">
          ${STRUCTS.map((id, i) => `<button class="viz-tab${id === S.structure ? " active" : ""}"
             role="tab" aria-selected="${id === S.structure}" data-struct="${id}"
             title="${esc(t("viz." + id))} (${i + 1})">
             <span class="viz-tab-n">${i + 1}</span>${esc(t("viz." + id))}</button>`).join("")}
        </div>
        <div class="viz-tools">
          <label class="viz-pick"><span>${esc(t("viz.source"))}</span>
            <select data-src>${srcOptions()}</select>
          </label>
          <label class="viz-pick"><span>${esc(t("viz.depth"))}</span>
            <select data-depth>${[1, 2, 3].map(d => `<option value="${d}" ${d === S.depth ? "selected" : ""}>${d}</option>`).join("")}</select>
          </label>
          <label class="viz-check" title="${esc(t("viz.leavesHint"))}">
            <input type="checkbox" data-leaves ${S.leaves ? "checked" : ""}>
            <span>${esc(t("viz.leaves"))}</span>
          </label>
          <input type="search" class="viz-find" data-find value="${esc(S.query)}"
                 placeholder="${esc(t("viz.find"))}" aria-label="${esc(t("viz.find"))}">
          <button class="icon-btn" data-fit title="${esc(t("viz.fit"))}" aria-label="${esc(t("viz.fit"))}">⤢</button>
          <button class="icon-btn" data-back title="${esc(t("viz.back"))}" aria-label="${esc(t("viz.back"))}">↩</button>
          <button class="icon-btn${S.legend ? " is-on" : ""}" data-legend title="${esc(t("viz.legend"))}">▦</button>
          <button class="icon-btn${S.table ? " is-on" : ""}" data-table-toggle title="${esc(t("viz.table"))}">☰</button>
          <button class="icon-btn" data-export title="${esc(t("viz.exportSvg"))}">↓</button>
        </div>
      </div>

      <div class="viz-crumbs" data-crumbs></div>

      <div class="viz-body">
        <div class="viz-stage" data-stage tabindex="0" role="application"
             aria-label="${esc(t("viz.canvas"))}">
          <svg class="viz-svg" data-viz-svg xmlns="http://www.w3.org/2000/svg" dir="ltr">
            <g data-viz-world></g>
          </svg>
          <div class="viz-heads" data-viz-heads></div>
          <div class="viz-tip" data-tip hidden></div>
          <div class="viz-mini" data-mini hidden>
            <svg viewBox="0 0 1000 640" preserveAspectRatio="xMidYMid meet" data-mini-svg></svg>
            <div class="viz-mini-win" data-mini-win></div>
          </div>
          <div class="viz-empty" data-empty hidden></div>
        </div>

        <aside class="viz-panel" data-panel aria-live="polite"></aside>
      </div>

      <div class="viz-foot">
        <div class="viz-legend" data-legend-box></div>
        <div class="viz-cost" data-cost></div>
      </div>
      <div class="viz-tablebox" data-table-box ${S.table ? "" : "hidden"}></div>
    </div>`;
  }

  /* ══════════════════════════════════════════════════════════════ render ═══ */
  function modelOf() {
    if (!S.payload) return null;
    let model;
    try {
      model = V.build(S.payload.root, { depth: modelDepth(), maxNodes: 4000, rootBreadth: 90, minShare: 0.004 });
    } catch (err) {
      console.error(err);
      return null;
    }
    S.model = model;
    S.index = new Map(model.flat.map((n, i) => [n, i]));
    return model;
  }

  function focusNode() {
    if (!S.model) return null;
    if (S.focus === "root") return S.model.root;
    return S.model.byId.get(S.focus) || S.model.root;
  }

  function draw() {
    const model = S.model, focus = focusNode();
    if (!model || !focus) return;
    const geo = GEO[S.structure](model, focus);
    paint(geo);
    heads(geo);
    /* an outline can be taller than any screen; fitting it whole would shrink
       every label to a smear, so it starts readable and offers the minimap */
    if (S.viewport) {
      const reveal = S.structure === "tree" && !S.openTouched;
      S.viewport.fit({ x: 0, y: 0, w: geo.w, h: geo.h },
                     { animate: !reveal, minK: S.structure === "tree" ? 0.9 : 0 });
      if (reveal) revealRecords();
    }
    crumbs();
    legend();
    cost(geo);
    panel();
    mini();
    const empty = document.querySelector("[data-empty]");
    if (empty) {
      const none = !geo.parts.length;
      empty.hidden = !none;
      if (none) empty.innerHTML = `<div class="notice">${esc(t("viz.noChildren"))}</div>`;
    }
    if (S.table) table();
  }

  function crumbs() {
    const host = document.querySelector("[data-crumbs]");
    if (!host) return;
    const focus = focusNode();
    if (!focus) { host.innerHTML = ""; return; }
    const path = [];
    let cur = focus;
    while (cur) { path.unshift(cur); cur = cur.__p; }
    const chain = S.payload.chain || [];
    const dimName = (n) => {
      const m = n.meta || {};
      const c = chain[m.depth - 1];
      return c ? (A.state.lang === "ar" ? c.label_ar : c.label_en) : "";
    };
    host.innerHTML = path.map((n, i) => {
      const last = i === path.length - 1;
      const label = i === 0 ? named(n) : `${dimName(n)}: ${named(n)}`;
      return (i ? `<span class="viz-sep" aria-hidden="true">›</span>` : "")
        + `<button class="viz-crumb${last ? " here" : ""}" data-crumb="${esc(S.index.get(n))}"
             ${last ? 'aria-current="page"' : ""}>${esc(V.fit(label, 220, 12))}</button>`;
    }).join("") + `<span class="viz-crumb-note">${fmtNum(val(focus))} · ${pctText(val(focus), modelTotal())}</span>`;
  }

  const modelTotal = () => (S.model ? S.model.total : 0);

  function legend() {
    const box = document.querySelector("[data-legend-box]");
    if (!box) return;
    box.hidden = !S.legend;
    if (!S.legend || !S.model) { box.innerHTML = ""; return; }
    const focus = focusNode();
    const list = kids(focus).slice(0, 8);
    box.innerHTML = list.map(n => `<button class="viz-chip" data-goto="${esc(S.index.get(n))}">
        <i style="background:${S.model.colorOf(n)}"></i>
        <span>${esc(V.fit(named(n), 130, 11))}</span><b>${fmtNum(val(n))}</b></button>`).join("")
      + (S.model.merged ? `<span class="viz-chip is-soft">${esc(t("viz.folded", { n: S.model.merged }))}</span>` : "")
      + `<span class="viz-chip is-soft">${esc(t("viz.legendHint"))}</span>`;
  }

  function cost(geo) {
    const box = document.querySelector("[data-cost]");
    if (!box) return;
    const p = S.payload || {};
    const shown = S.model ? S.model.flat.length : 0;
    const leaves = S.model ? S.model.leaves.length : 0;
    box.innerHTML = `
      <span title="${esc(t("viz.costServer"))}">⛁ ${esc(t("viz.costServer"))} <b>${p.computed_ms == null ? "—" : p.computed_ms + " ms"}</b>${p.cached ? " · cached" : ""}</span>
      <span title="${esc(t("viz.costModel"))}">◈ ${esc(t("viz.costModel"))} <b>${S.model ? S.model.ms.toFixed(1) + " ms" : "—"}</b></span>
      <span>▤ ${esc(t("viz.costNodes"))} <b>${fmtNum(shown)}</b> / ${esc(t("viz.costLeaves"))} <b>${fmtNum(leaves)}</b></span>
      <span>${esc(t("viz.costRecords"))} <b>${fmtNum(val(focusNode() || { __v: 0 }))}</b></span>
      ${S.model && S.model.merged ? `<span class="warn">⚑ ${esc(t("viz.costFolded", { n: S.model.merged }))}</span>` : ""}
      <span class="muted">${esc(t("viz.costNote"))}</span>`;
  }

  function panel() {
    const host = document.querySelector("[data-panel]");
    if (!host) return;
    const node = S.selected != null ? S.model && S.model.flat[S.selected] : null;
    if (!node) {
      const focus = focusNode();
      host.innerHTML = `<div class="viz-panel-empty">
        <h3>${esc(t("viz.selection"))}</h3>
        <p class="muted small">${esc(t("viz.selectHint"))}</p>
        ${focus ? `<div class="viz-panel-focus">
          <div class="muted small">${esc(t("viz.focusNow"))}</div>
          <div class="viz-panel-name">${esc(named(focus))}</div>
          <div class="viz-panel-big">${fmtNum(val(focus))}</div>
          <div class="muted small">${esc(t("viz.records"))} · ${pctText(val(focus), modelTotal())}</div>
        </div>` : ""}
        <ul class="viz-keys">
          <li><kbd>1</kbd>–<kbd>6</kbd> ${esc(t("viz.keyStruct"))}</li>
          <li><kbd>⏎</kbd> ${esc(t("viz.keyEnter"))}</li>
          <li><kbd>esc</kbd> ${esc(t("viz.keyEsc"))}</li>
          <li><kbd>+</kbd> <kbd>−</kbd> <kbd>0</kbd> ${esc(t("viz.keyZoom"))}</li>
        </ul></div>`;
      return;
    }
    const m = node.meta || {};
    const chain = S.payload.chain || [];
    const dim = chain[m.depth - 1];
    const parent = node.__p;
    const sub = kids(node).slice(0, 9);
    const share = pctText(val(node), modelTotal());
    const ofParent = parent ? pctText(val(node), val(parent)) : "—";
    const entity = S.payload.source.entity;
    const isRecord = !!(m.record && m.record_id);
    const q = m.raw && m.raw !== NOT_RECORDED ? m.raw : named(node);
    const recordHref = isRecord
      ? `#/entity/${esc(m.entity || entity)}/${m.record_id}`
      : `#/entity/${esc(entity)}?q=${encodeURIComponent(q)}`;
    host.innerHTML = `
      <div class="viz-panel-head">
        <div class="viz-panel-kicker">${esc(dim ? (A.state.lang === "ar" ? dim.label_ar : dim.label_en) : named(focusNode()))}</div>
        <h3 class="viz-panel-name">${esc(named(node))}</h3>
        <div class="viz-panel-big">${isRecord ? esc(m.code || ("#" + m.record_id)) : fmtNum(val(node))}</div>
        <div class="viz-panel-sub muted small">${isRecord
          ? esc(m.link
            ? ((A.state.lang === "ar" ? (m.link_ar || m.link_en) : (m.link_en || m.link_ar)) || t("viz.linked"))
            : t("viz.recordLeaf"))
          : `${esc(t("viz.records"))} · ${share} ${esc(t("viz.ofAll"))} · ${ofParent} ${esc(t("viz.ofParent"))}`}</div>
      </div>
      <div class="viz-bar-split" role="img" aria-label="${esc(share)}">
        <i style="width:${Math.max(1, Math.min(100, pct(val(node), modelTotal())))}%;background:${S.model.colorOf(node)}"></i>
      </div>
      ${m.synthetic ? `<div class="notice small">⚑ ${esc(t("viz.foldedNote", { n: m.count || 0 }))}</div>` : ""}
      <dl class="viz-meta">
        ${dim ? `<dt>${esc(A.state.lang === "ar" ? dim.label_ar : dim.label_en)}</dt><dd>${esc(m.raw === "~rest" ? "—" : (m.raw || "—"))}</dd>` : ""}
        <dt>${esc(t("viz.path"))}</dt><dd class="small muted">${esc(S.model.pathOf(node).join(" › ") || "—")}</dd>
        ${!isRecord ? `<dt>${esc(t("viz.branchOf"))}</dt><dd>${fmtNum(m.of != null ? m.of : val(parent || node))}</dd>
        <dt>${esc(t("viz.branches"))}</dt><dd>${fmtNum(m.collected != null ? m.collected : kids(node).length)}</dd>` : ""}
      </dl>
      ${sub.length ? `<div class="viz-sub-list">
        <div class="muted small">${esc(t("viz.children"))}</div>
        ${sub.map(n => `<button class="viz-sub" data-goto="${esc(S.index.get(n))}">
            <span>${esc(V.fit(named(n), 150, 11.5))}</span>
            <i><b style="width:${Math.max(1, pct(val(n), val(node)))}%"></b></i>
            <em>${fmtNum(val(n))}</em></button>`).join("")}
      </div>` : ""}
      <div data-viz-detail></div>
      <div class="viz-acts">
        ${isRecord
          ? `<a class="btn sm primary" href="${recordHref}">${esc(t("viz.openRecord"))}</a>
             <a class="btn sm" href="#/map?focus=${esc(m.entity || entity)}:${m.record_id}">${esc(t("viz.showOnAtlas"))}</a>`
          : `<button class="btn sm primary" data-drill="${esc(S.selected)}">${esc(t("viz.focusHere"))}</button>
             <button class="btn sm" data-up>${esc(t("viz.up"))}</button>
             <a class="btn sm" href="${recordHref}"
                title="${esc(t("viz.openRecordsHint"))}">${esc(t("viz.openRecords"))}</a>`}
      </div>
      <div class="muted small viz-panel-foot">${esc(t("viz.panelFoot"))}</div>`;
    if (isRecord && m.record_id && !m.synthetic) fillDetail(host, m.entity || entity, m.record_id);
  }

  const DETAIL_KEYS = {
    person: ["name_ar", "name_en", "birth_date", "death_date", "current_position", "birthplace_text"],
    institution: ["name_ar", "name_en", "abbreviation", "city", "founded_date", "website"],
    place: ["name_ar", "name_en", "governorate_id", "city", "latitude", "longitude"],
    event: ["title_ar", "title_en", "start_date", "end_date", "description"],
    source: ["title", "title_ar", "publisher", "publication_date"],
    relationship: ["entity1_name", "entity2_name", "start_date", "end_date", "description"],
  };
  let detailSeq = 0;

  function detailValue(rec, key) {
    const lab = rec._labels && rec._labels[key];
    if (lab) return A.state.lang === "ar" ? (lab.ar || lab.en) : (lab.en || lab.ar);
    const ref = rec._refs && rec._refs[key];
    if (ref && ref.label) return ref.label;
    const v = rec[key];
    if (v == null || v === "") return "";
    return String(v);
  }

  function detailHtml(rec, entityName, coords) {
    const fields = A.fieldsOf(entityName) || [];
    const rows = [];
    for (const key of (DETAIL_KEYS[entityName] || [])) {
      const shown = detailValue(rec, key);
      if (!shown) continue;
      const f = fields.find(x => x.key === key);
      const label = f && A.fieldLabelSafe ? A.fieldLabelSafe(f) : key;
      const dir = (key === "latitude" || key === "longitude") ? ' dir="ltr"' : "";
      rows.push(`<dt>${esc(label)}</dt><dd${dir}>${esc(shown)}</dd>`);
    }
    const rels = (rec.relationships || []).filter(r => r.other_type && r.other_id);
    const people = rels.filter(r => r.other_type === "person" || r.other_type === "institution");
    const rest = rels.filter(r => r.other_type !== "person" && r.other_type !== "institution");
    const linkRow = (r) => `<a class="viz-sub" href="#/entity/${esc(r.other_type)}/${r.other_id}">
        <span>${esc(A.truncate ? A.truncate(r.other_name || A.label(r.other_type), 42) : (r.other_name || ""))}</span>
        <em>${esc(A.state.lang === "ar" ? (r.type_ar || r.type_en || "") : (r.type_en || r.type_ar || ""))}</em></a>`;
    const coordBlock = coords
      ? `<div class="viz-coord" dir="ltr">${esc(t("viz.coords"))}: ${Number(coords.lat).toFixed(5)}, ${Number(coords.lon).toFixed(5)}</div>`
      : "";
    return `<dl class="viz-meta">${rows.join("")}</dl>
      ${coordBlock}
      <div class="viz-sub-list">
        <div class="muted small">${esc(t("viz.linked"))}</div>
        ${people.concat(rest).slice(0, 12).map(linkRow).join("")
          || `<div class="muted small">${esc(t("viz.noLinks"))}</div>`}
      </div>`;
  }

  async function fillDetail(host, entityName, id) {
    const box = host.querySelector("[data-viz-detail]");
    if (!box) return;
    const seq = ++detailSeq;
    const key = entityName + ":" + id;
    if (S.detail && S.detail.key === key) {
      box.innerHTML = S.detail.html;
      return;
    }
    box.innerHTML = `<div class="muted small">${esc(t("common.loading"))}</div>`;
    try {
      const rec = await api(`/api/${entityName}/${id}`);
      if (seq !== detailSeq) return;
      let coords = null;
      if (entityName === "place" && rec.latitude != null && rec.longitude != null) {
        coords = { lat: rec.latitude, lon: rec.longitude };
      } else {
        const pid = rec.birthplace_id || rec.place_id;
        if (pid) {
          try {
            const place = await api(`/api/place/${pid}`);
            if (seq !== detailSeq) return;
            if (place.latitude != null && place.longitude != null) {
              coords = { lat: place.latitude, lon: place.longitude };
            }
          } catch (e) { /* the record still renders without a point */ }
        }
      }
      const html = detailHtml(rec, entityName, coords);
      S.detail = { key, html };
      const live = host.querySelector("[data-viz-detail]");
      if (live && seq === detailSeq) live.innerHTML = html;
    } catch (err) {
      if (seq !== detailSeq) return;
      const live = host.querySelector("[data-viz-detail]");
      if (live) live.innerHTML = `<div class="notice err small">${esc(err.message || String(err))}</div>`;
    }
  }

  function revealRecords() {
    if (S.structure !== "tree" || S.openTouched || !S.viewport || !S.model) return;
    const world = document.querySelector("[data-viz-world]");
    if (!world) return;
    const hit = [...world.querySelectorAll("[data-nid]")].find(el => {
      const n = S.model.flat[Number(el.getAttribute("data-nid"))];
      return n && n.meta && n.meta.record && !n.meta.synthetic && !n.meta.link;
    });
    if (!hit || !hit.getBBox) return;
    const b = hit.getBBox();
    if (!b.width) return;
    /* keep the group the record belongs to in frame, not only the record itself */
    S.viewport.zoomTo({ x: Math.max(0, b.x - 280), y: Math.max(0, b.y - 48), w: b.width + 340, h: 300 },
                      { animate: false });
  }

  function table() {
    const box = document.querySelector("[data-table-box]");
    if (!box) return;
    box.hidden = !S.table;
    if (!S.table || !S.model) return;
    box.innerHTML = `<div class="viz-table-wrap">${V.toTable(S.model, { metric: named(focusNode()) })}</div>
      <div class="btn-row"><button class="btn sm" data-export-csv>⤓ CSV</button>
      <span class="muted small">${esc(t("viz.tableNote"))}</span></div>`;
  }

  function mini() {
    const box = document.querySelector("[data-mini]");
    if (!box) return;
    box.hidden = !S.minimap;
    if (!S.minimap) return;
    const world = document.querySelector("[data-viz-world]");
    const mini = document.querySelector("[data-mini-svg]");
    if (world && mini) mini.innerHTML = world.innerHTML;
    syncMini();
  }

  function syncMini() {
    const win = document.querySelector("[data-mini-win]");
    const stage = document.querySelector("[data-stage]");
    if (!win || !stage || !S.viewport) return;
    const r = stage.getBoundingClientRect();
    const b = S.viewport.bounds;
    const vw = r.width / S.viewport.k, vh = r.height / S.viewport.k;
    const vx = (0 - S.viewport.x) / S.viewport.k, vy = (0 - S.viewport.y) / S.viewport.k;
    const sx = 100 / Math.max(1, b.w), sy = 100 / Math.max(1, b.h);
    const s = Math.min(sx, sy / (640 / 1000));
    win.style.left = `${(vx - b.x) * sx}%`;
    win.style.top = `${(vy - b.y) * sy}%`;
    win.style.width = `${Math.min(100, vw * sx)}%`;
    win.style.height = `${Math.min(100, vh * sy)}%`;
    void s;
  }

  /* ═════════════════════════════════════════════════════════ interaction ═══ */
  function tooltipFor(i, ev) {
    const tip = document.querySelector("[data-tip]");
    if (!tip) return;
    if (i == null || !S.model) { tip.hidden = true; return; }
    const n = S.model.flat[Number(i)];
    if (!n) { tip.hidden = true; return; }
    const stage = document.querySelector("[data-stage]");
    const r = stage.getBoundingClientRect();
    tip.innerHTML = `<b>${esc(named(n))}</b><span>${fmtNum(val(n))} · ${pctText(val(n), modelTotal())}</span>
      <em>${esc(S.model.pathOf(n).slice(0, -1).slice(-2).join(" › ") || t("viz.root"))}</em>`;
    tip.hidden = false;
    const x = Math.min(r.width - tip.offsetWidth - 8, Math.max(8, ev.clientX - r.left + 14));
    const y = Math.min(r.height - tip.offsetHeight - 8, Math.max(8, ev.clientY - r.top + 14));
    tip.style.transform = `translate(${x}px, ${y}px)`;
  }

  function highlight(i) {
    const world = document.querySelector("[data-viz-world]");
    if (!world || !S.model) return;
    const node = i == null ? null : S.model.flat[Number(i)];
    const hot = new Set();
    if (node) {
      let cur = node;
      while (cur) { hot.add(S.index.get(cur)); cur = cur.__p; }
      for (const k of kids(node)) hot.add(S.index.get(k));
    }
    world.classList.toggle("has-hot", !!node);
    for (const el of world.querySelectorAll("[data-nid]")) {
      const idx = Number(el.getAttribute("data-nid"));
      const isDesc = node && isDescendantOf(S.model.flat[idx], node);
      el.classList.toggle("is-hot", hot.has(idx));
      el.classList.toggle("is-far", !!node && !hot.has(idx) && !isDesc);
    }
  }

  function isDescendantOf(n, of) {
    let cur = n;
    while (cur) { if (cur === of) return true; cur = cur.__p; }
    return false;
  }

  function select(i) {
    S.selected = i == null ? null : Number(i);
    panel();
    const world = document.querySelector("[data-viz-world]");
    if (world) {
      for (const el of world.querySelectorAll("[data-nid]")) {
        el.classList.toggle("is-selected", Number(el.getAttribute("data-nid")) === S.selected);
      }
    }
  }

  function drill(i) {
    if (i == null) return false;
    const node = S.model && S.model.flat[Number(i)];
    if (!node || node === focusNode()) return false;
    /* a record has nothing under it to redraw — its details are the panel */
    if (!kids(node).length) { select(i); return false; }
    S.focus = node === S.model.root ? "root" : node.id;
    S.selected = Number(i);
    draw();
    return true;
  }

  function up() {
    const focus = focusNode();
    if (!focus || focus === S.model.root) return false;
    S.focus = focus.__p && focus.__p !== S.model.root ? focus.__p.id : "root";
    S.selected = null;
    draw();
    return true;
  }

  function setStructure(id) {
    if (STRUCTS.indexOf(id) < 0 || id === S.structure) return;
    S.structure = id;
    document.querySelectorAll("[data-struct]").forEach(b => {
      const on = b.getAttribute("data-struct") === id;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    draw();
    savePrefs();
  }

  function find(q) {
    S.query = q || "";
    const world = document.querySelector("[data-viz-world]");
    if (!world || !S.model) return;
    const needle = S.query.trim().toLowerCase();
    let first = null;
    for (const el of world.querySelectorAll("[data-nid]")) {
      const n = S.model.flat[Number(el.getAttribute("data-nid"))];
      const hit = !!needle && n && (String(n.label_en || "").toLowerCase().includes(needle)
        || String(n.label_ar || "").toLowerCase().includes(needle));
      el.classList.toggle("is-hit", hit);
      if (hit && first == null) first = el;
    }
    if (first && needle) {
      const bbox = first.getBBox ? first.getBBox() : null;
      if (bbox && bbox.width) S.viewport.zoomTo(bbox, { animate: true });
    }
  }

  /* ══════════════════════════════════════════════════════════════ loading ═══ */
  async function loadSources() {
    const res = await api("/api/structures");
    S.sources = res.sources || [];
    /* deep link: #/structures?source=units opens right on a module */
    const deep = A.state && A.state.route && A.state.route.params &&
      A.state.route.params.source;
    if (deep && S.sources.some(s => s.id === deep)) S.source = deep;
    if (!S.sources.some(s => s.id === S.source)) S.source = S.sources.length ? S.sources[0].id : "people";
  }

  async function loadSource(id) {
    S.source = id;
    S.busy = true;
    const stage = document.querySelector("[data-stage]");
    if (stage) stage.classList.add("is-busy");
    try {
      const payload = await api(`/api/structures/${encodeURIComponent(id)}?depth=${S.depth}&max_children=${S.maxChildren}`
        + (S.leaves ? "&leaves=1" : "&leaves=0"));
      S.payload = payload;
      S.focus = "root";
      S.open = new Set();
      S.openTouched = false;
      S.selected = null;
      modelOf();
      draw();
      savePrefs();
    } catch (err) {
      console.error(err);
      A.toast(err.message || String(err), "err");
      const box = document.querySelector("[data-empty]");
      if (box) { box.hidden = false; box.innerHTML = `<div class="notice err">${esc(err.message || String(err))}</div>`; }
    } finally {
      S.busy = false;
      if (stage) stage.classList.remove("is-busy");
    }
  }

  function download(name, text, type) {
    const blob = new Blob([text], { type: type || "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1200);
  }

  function exportSvg() {
    const svg = document.querySelector("[data-viz-svg]");
    if (!svg) return;
    download(`siraj-${S.source}-${S.structure}.svg`,
             V.toSvg(svg, { background: "#ffffff" }), "image/svg+xml");
    A.toast(t("viz.exported"), "ok");
  }

  function exportCsv() {
    if (!S.model) return;
    const rows = [["node", "path", "value", "share"]].concat(
      S.model.flat.map(n => [named(n), S.model.pathOf(n).join(" / "),
        Math.round(n.__v), pctText(n.__v, modelTotal())]));
    const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    download(`siraj-${S.source}-${S.structure}.csv`, "\ufeff" + csv, "text/csv;charset=utf-8");
  }

  /* ══════════════════════════════════════════════════════════════ the view ═══ */
  async function view(host, params) {
    const p = prefs();
    S.structure = STRUCTS.indexOf(p.structure) >= 0 ? p.structure : "treemap";
    S.source = p.source || "people";
    S.depth = Math.min(3, Math.max(1, Number(p.depth) || 2));
    S.maxChildren = Math.min(40, Math.max(3, Number(p.maxChildren) || 24));
    S.leaves = p.leaves !== false;
    S.labels = p.labels !== false;
    S.values = p.values !== false;
    S.legend = p.legend !== false;
    S.minimap = p.minimap !== false;
    S.table = false;
    S.focus = "root";
    S.selected = null;

    host.innerHTML = `<div class="card"><div class="skeleton" style="width:30%"></div>
      <div class="skeleton" style="width:70%;margin-top:10px"></div></div>`;
    try {
      await loadSources();
    } catch (err) {
      host.innerHTML = `<div class="card"><h2>${esc(t("viz.title"))}</h2>
        <div class="notice err">${esc(err.message || String(err))}</div></div>`;
      return;
    }

    host.innerHTML = `<div class="view-head">
        <div><h1>${esc(t("viz.title"))}</h1><p class="muted">${esc(t("viz.subtitle"))}</p></div>
        <div class="view-head-actions"><a class="btn sm" href="#/dashboard">${esc(t("nav.dashboard"))}</a></div>
      </div>` + shell();

    /* one camera per deck: the previous one is retired with the page, or its
       animation frame keeps writing into a group that no longer exists */
    if (S.viewport) S.viewport.destroy();
    const stage = host.querySelector("[data-stage]");
    const layer = host.querySelector("[data-viz-world]");
    S.viewport = new V.Viewport(stage, {
      min: 0.25, max: 24, pad: 24,
      world: { w: W, h: H },
      onChange: () => syncMini(),
    }).attach(layer);

    S.interact = new V.Interact(stage, {
      onHover: (id, ev) => {
        S.hover = id;
        highlight(id);
        if (ev) tooltipFor(id, ev); else tooltipFor(null, { clientX: 0, clientY: 0 });
      },
      onSelect: (id) => {
        const n = id == null ? null : S.model && S.model.flat[Number(id)];
        /* an outline opens where it is clicked; everything else selects */
        if (S.structure === "tree" && n && kids(n).length) {
          S.openTouched = true;
          if (S.open.has(n.id)) S.open.delete(n.id); else S.open.add(n.id);
          select(id);
          draw();
          return;
        }
        select(id);
      },
      onDrill: (id) => drill(id),
    });

    /* ---- toolbar wiring ---- */
    stage.addEventListener("pointerleave", () => tooltipFor(null, { clientX: 0, clientY: 0 }));
    host.querySelectorAll("[data-struct]").forEach(b => {
      b.addEventListener("click", () => setStructure(b.getAttribute("data-struct")));
    });
    host.querySelector("[data-src]").addEventListener("change", (ev) => loadSource(ev.target.value));
    host.querySelector("[data-depth]").addEventListener("change", (ev) => {
      S.depth = Number(ev.target.value); savePrefs(); loadSource(S.source);
    });
    const leavesEl = host.querySelector("[data-leaves]");
    if (leavesEl) leavesEl.addEventListener("change", (ev) => {
      S.leaves = !!ev.target.checked; savePrefs(); loadSource(S.source);
    });
    const findEl = host.querySelector("[data-find]");
    findEl.addEventListener("input", (ev) => find(ev.target.value));
    host.querySelector("[data-fit]").addEventListener("click", () => {
      const geo = GEO[S.structure](S.model, focusNode());
      S.viewport.fit({ x: 0, y: 0, w: geo.w, h: geo.h }, { animate: true });
    });
    host.querySelector("[data-back]").addEventListener("click", () => { if (!up()) A.toast(t("viz.atRoot")); });
    host.querySelector("[data-legend]").addEventListener("click", (ev) => {
      S.legend = !S.legend;
      ev.currentTarget.classList.toggle("is-on", S.legend);
      legend(); savePrefs();
    });
    host.querySelector("[data-table-toggle]").addEventListener("click", (ev) => {
      S.table = !S.table;
      ev.currentTarget.classList.toggle("is-on", S.table);
      table();
    });
    host.querySelector("[data-export]").addEventListener("click", exportSvg);

    /* delegated controls inside the panel, legend and crumbs */
    host.addEventListener("click", (ev) => {
      const goto = ev.target.closest("[data-goto]");
      if (goto) { select(goto.getAttribute("data-goto")); return; }
      const d = ev.target.closest("[data-drill]");
      if (d) { drill(d.getAttribute("data-drill")); return; }
      if (ev.target.closest("[data-up]")) { up(); return; }
      const c = ev.target.closest("[data-crumb]");
      if (c) {
        const node = S.model.flat[Number(c.getAttribute("data-crumb"))];
        S.focus = node === S.model.root ? "root" : node.id;
        S.selected = null;
        draw();
        return;
      }
      if (ev.target.closest("[data-export-csv]")) exportCsv();
    });

    /* keyboard: structures by number, escape up, slash to find */
    const onKey = (ev) => {
      const typing = ev.target && /input|select|textarea/i.test(ev.target.tagName || "");
      if (ev.key === "Escape") {
        if (S.selected != null) { select(null); ev.preventDefault(); }
        else if (up()) ev.preventDefault();
        return;
      }
      if (typing) return;
      const n = Number(ev.key);
      if (n >= 1 && n <= STRUCTS.length) { setStructure(STRUCTS[n - 1]); ev.preventDefault(); return; }
      if (ev.key === "/") { ev.preventDefault(); findEl.focus(); findEl.select(); return; }
      if (ev.key === "Enter" && S.selected != null) { ev.preventDefault(); drill(S.selected); }
    };
    document.addEventListener("keydown", onKey);
    view.__dispose = () => {
      document.removeEventListener("keydown", onKey);
      if (S.viewport) S.viewport.destroy();
    };

    await loadSource(S.source);
  }

  A.views = A.views || {};
  A.views.structures = view;
})(window.App);
