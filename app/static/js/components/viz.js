/* ============================================================================
   SIRAJ · components/viz.js — the display kernel
   ----------------------------------------------------------------------------
   Ported from the reference console's kernel, and rebuilt for this registry:
   nothing in this file knows what a person, an institution or a relationship is.
   A structure takes a *node contract* and an *adapter*:

       Node    { id, label_en, label_ar, value?, children?: Node[], meta? }
       Adapter { id, label, value, children, color, group, note, href }

   Everything else — the model, the level of detail, the geometry, the camera,
   the interaction, the animation, the table fallback, the SVG export — is
   written against that contract only. Swapping the registry's taxonomy for a
   file tree is a change of adapter, not of renderer.

   The pieces, in order:

     Viz.adapter()   accessor set with sane defaults
     Viz.build()     model: aggregates, folds the tail, enforces a node budget
     Viz.scale*      linear / sqrt scales
     Viz.squarify    squarified treemap rectangles (Bruls/Huizing/van Wijk)
     Viz.arcPath     radial partition arcs, including full rings
     Viz.ribbon      chord ribbons · Viz.sankeyLink  layered flows
     Viz.pack        squarified circle packing
     Viz.Viewport    the camera: wheel-at-cursor, momentum, pinch, marquee, keys
     Viz.Interact    hover / click / shift-click / dblclick / keyboard / tooltip
     Viz.tween       keyed interpolation between two layouts, motion-aware
     Viz.toTable     the same model as an accessible table
     Viz.toSvg       a standalone SVG, styles inlined
     Viz.Navigator   the minimap
   ========================================================================== */
(function (A) {
  "use strict";

  const Viz = {
    version: 1,
    perf: { last: null, layouts: [] },
    /** record one layout pass; the deck reads this back — nobody fakes it */
    note(structure, ms, meta) {
      const rec = Object.assign({ structure, ms, at: Date.now() }, meta || {});
      this.perf.last = rec;
      this.perf.layouts.push(rec);
      if (this.perf.layouts.length > 40) this.perf.layouts.shift();
      return rec;
    },
    /** motion is a setting, not a decoration: honour it everywhere */
    reduced() {
      try {
        if (A.state && A.state.prefs && A.state.prefs.motion === "off") return true;
        if (A.state && A.state.prefs && A.state.prefs.motion === "on") return false;
        return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
      } catch (e) { return false; }
    },
  };

  /* ------------------------------------------------------------- adapter --- */
  const PALETTE = ["#1f6f5c", "#a3591b", "#31527d", "#7b3f78", "#8a6d1f",
                   "#2f6b8f", "#7a4b2a", "#4c6b2f", "#6b4f7a", "#8f3f3f",
                   "#3f6f6f", "#5a5f8a"];

  const adapter = {
    identity() {
      return {
        id: (n) => n.id,
        label: (n) => (A.state.lang === "ar"
          ? (n.label_ar || n.label_en || String(n.id))
          : (n.label_en || n.label_ar || String(n.id))),
        value: (n) => (typeof n.value === "number" ? n.value : 0),
        children: (n) => (Array.isArray(n.children) && n.children.length ? n.children : null),
        color: (n) => (n.meta && n.meta.color) || null,
        group: (n) => (n.meta && n.meta.group) || null,
        note: (n) => (n.meta && n.meta.note) || null,
        href: (n) => (n.meta && n.meta.href) || null,
        key: (n) => String(n.id),
      };
    },
    make(partial) { return Object.assign(this.identity(), partial || {}); },
  };

  /* --------------------------------------------------------------- model --- */
  /**
   * Turn a node tree into a display model.
   *
   * The budget is the interesting part: a taxonomy with hundreds of branches and
   * thousands of leaves cannot be drawn node for node at any useful size, so the
   * model folds. Below the root, children under `minShare` of their parent become
   * one synthetic "n smaller groups" node; if the tree is still over `maxNodes`
   * the smallest subtrees are collapsed into that bucket, cheapest first. Every
   * fold is counted so the legend can say how much of the picture is an aggregate
   * instead of pretending it is not.
   */
  Viz.build = function build(root, opts) {
    const o = opts || {};
    const A_ = o.A || adapter.identity();
    const maxNodes = o.maxNodes || 900;
    const minShare = o.minShare == null ? 0.02 : o.minShare;
    const rootBreadth = o.rootBreadth || 72;
    const depth = o.depth || 3;
    const t0 = performance.now();
    const byId = new Map();
    let merged = 0;

    /* A record (and a record it is linked to) keeps its own count. Summing the
       people attached to an event would turn "1 event" into "4", and the picture
       would no longer add up to the registry. */
    const individual = (n) => {
      const m = n && n.meta;
      return !!(m && (m.record || m.link) && !m.synthetic);
    };

    const measure = (n, d) => {
      const kids = A_.children(n);
      const own = A_.value(n);
      const one = individual(n);
      if (!kids || d >= depth) {
        const v = own > 0 ? own : (kids ? kids.reduce((s, k) => s + Math.max(0, A_.value(k)), 0) : 0);
        n.__v = one ? (own > 0 ? own : 1) : v;
        n.__leaf = true;
        return n.__v;
      }
      let sum = 0;
      for (const k of kids) sum += Math.max(0, measure(k, d + 1));
      n.__v = one ? (own > 0 ? own : 1) : (sum || own);
      n.__leaf = false;
      return n.__v;
    };
    measure(root, 0);

    const fold = (n, d) => {
      const kids = A_.children(n);
      if (!kids || d + 1 > depth) { n.__kids = null; n.__leaf = true; return n; }
      const total = n.__v || 1;
      let kept = kids;
      let restSum = 0, restCount = 0;
      if (d === 0 && kids.length > rootBreadth) {
        const sorted = kids.slice().sort((a, b) => b.__v - a.__v);
        kept = sorted.slice(0, rootBreadth);
        for (const k of sorted.slice(rootBreadth)) { restSum += k.__v; restCount++; }
      } else if (kids.length > 4) {
        const out = [];
        for (const k of kids) {
          /* individual records are the point of the last level — a person is
             1/400 of a nationality and must not disappear into "smaller groups" */
          if (!individual(k) && k.__v / total < minShare) { restSum += k.__v; restCount++; }
          else out.push(k);
        }
        if (out.length) kept = out;
      }
      const out = [];
      for (const k of kept) out.push(fold(k, d + 1));
      if (restCount) {
        merged += restCount;
        out.push({
          id: `${A_.id(n)}::rest`, label_en: `${restCount} smaller groups`,
          label_ar: `${restCount} مجموعة أصغر`, value: restSum, __v: restSum,
          __leaf: true, __synthetic: true, meta: { synthetic: true, count: restCount },
        });
      }
      n.__kids = out;
      n.__leaf = !out.length;
      return n;
    };
    fold(root, 0);

    const flatten = (n, d, parent, out) => {
      out.push({ node: n, depth: d, parent });
      if (d < depth && n.__kids) for (const k of n.__kids) flatten(k, d + 1, n, out);
      return out;
    };
    const subtreeCount = (n, d) => {
      let k = 1;
      if (d < depth && n.__kids) for (const c of n.__kids) k += subtreeCount(c, d + 1);
      return k;
    };
    let rows = flatten(root, 0, null, []);
    if (rows.length > maxNodes) {
      /* Collapse from the deepest level upward, cheapest first, with exact
         arithmetic over the subtree that leaves: counting one removal as one node
         undercounts, and re-flattening after every removal is quadratic. */
      for (let d = depth; d >= 1; d--) {
        rows = flatten(root, 0, null, []);
        if (rows.length <= maxNodes) break;
        const order = rows.filter(r => r.depth === d && r.parent && !individual(r.node))
          .sort((a, b) => (a.node.__v || 0) - (b.node.__v || 0));
        if (!order.length) continue;
        let count = rows.length;
        for (const victim of order) {
          if (count <= maxNodes) break;
          const p = victim.parent;
          if (!p || !p.__kids || p.__kids.indexOf(victim.node) < 0) continue;
          const bucketId = `${A_.id(p)}::rest`;
          const existing = p.__kids.find(k => A_.id(k) === bucketId);
          p.__kids = p.__kids.filter(k => k !== victim.node);
          const gone = subtreeCount(victim.node, d);
          if (existing) {
            existing.__v += victim.node.__v;
            existing.value = existing.__v;
            existing.meta.count = (existing.meta.count || 1) + (victim.node.meta && victim.node.meta.count || 1);
            count -= gone;
          } else {
            p.__kids.push({
              id: bucketId, label_en: "smaller groups", label_ar: "مجموعات أصغر",
              value: victim.node.__v, __v: victim.node.__v, __leaf: true, __synthetic: true,
              meta: { synthetic: true, count: (victim.node.meta && victim.node.meta.count) || 1 },
            });
            count -= gone - 1;
          }
        }
      }
      rows = flatten(root, 0, null, []);
    }

    const flat = [];
    const walk = (n, d, parent, path) => {
      n.__d = d; n.__p = parent; n.__path = path;
      byId.set(A_.id(n), n);
      flat.push(n);
      if (d < depth && n.__kids && n.__kids.length) {
        for (const k of n.__kids) walk(k, d + 1, n, path.concat(A_.label(n)));
      }
    };
    walk(root, 0, null, []);
    for (const n of flat) {
      if (n.__synthetic) {
        n.label_en = n.label_en || `${n.meta.count || 0} smaller groups`;
        n.label_ar = n.label_ar || `${n.meta.count || 0} مجموعة أصغر`;
        n.value = n.__v;
      }
    }

    const topAncestor = (n) => { let cur = n; while (cur && cur.__p && cur.__p !== root) cur = cur.__p; return cur || root; };
    const colorFor = (n) => {
      const seed = String(A_.id(topAncestor(n)));
      let hash = 0;
      for (let i = 0; i < seed.length; i++) hash = (Math.imul(hash, 31) + seed.charCodeAt(i)) | 0;
      return PALETTE[Math.abs(hash) % PALETTE.length];
    };

    const leaves = flat.filter(n => n.__leaf);
    const model = {
      root, A: A_, flat, leaves, byId,
      total: root.__v || 0,
      maxDepth: flat.reduce((m, n) => Math.max(m, n.__d), 0),
      merged, depth, metric: o.metric || null,
      ms: performance.now() - t0,
      colorOf: (n) => A_.color(n) || colorFor(n),
      groupOf: (n) => A_.group(n) || A_.id(topAncestor(n)),
      pathOf: (n) => (n.__path || []).concat([A_.label(n)]),
    };
    return model;
  };

  /* -------------------------------------------------------------- scales --- */
  const scaleLinear = (d0, d1, r0, r1) => {
    const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
    const f = (v) => r0 + (v - d0) * k;
    f.invert = (r) => (k === 0 ? d0 : d0 + (r - r0) / k);
    return f;
  };
  const scaleSqrt = (d0, d1, r0, r1) => {
    const a = Math.sqrt(Math.max(0, d0)), b = Math.sqrt(Math.max(0, d1));
    const k = b === a ? 0 : (r1 - r0) / (b - a);
    return (v) => r0 + (Math.sqrt(Math.max(0, v)) - a) * k;
  };

  /* ------------------------------------------------------------ geometry --- */
  /** Squarified treemap: worst-ratio first, row by row. */
  Viz.squarify = function squarify(items, x, y, w, h) {
    const out = [];
    const total = items.reduce((s, it) => s + Math.max(0, it.value), 0) || 1;
    const scaled = items.map(it => Object.assign({}, it, { __a: (Math.max(0, it.value) / total) * w * h }));
    let rect = { x, y, w, h };
    let i = 0;
    const worst = (row, side) => {
      const s = row.reduce((a, b) => a + b.__a, 0);
      let max = -Infinity, min = Infinity;
      for (const r of row) { max = Math.max(max, r.__a); min = Math.min(min, r.__a); }
      const s2 = s * s, side2 = side * side;
      return Math.max((side2 * max) / s2, s2 / (side2 * min));
    };
    while (i < scaled.length) {
      const side = Math.min(rect.w, rect.h);
      const row = [scaled[i]];
      let j = i + 1;
      while (j < scaled.length) {
        const next = row.concat(scaled[j]);
        if (worst(next, side) > worst(row, side)) break;
        row.push(scaled[j]); j++;
      }
      const rowSum = row.reduce((a, b) => a + b.__a, 0);
      if (rect.w >= rect.h) {
        const rw = rowSum / rect.h;
        let yy = rect.y;
        for (const r of row) {
          const rh = (r.__a / rowSum) * rect.h;
          out.push({ item: r, x: rect.x, y: yy, w: rw, h: rh });
          yy += rh;
        }
        rect = { x: rect.x + rw, y: rect.y, w: rect.w - rw, h: rect.h };
      } else {
        const rh = rowSum / rect.w;
        let xx = rect.x;
        for (const r of row) {
          const rw = (r.__a / rowSum) * rect.w;
          out.push({ item: r, x: xx, y: rect.y, w: rw, h: rh });
          xx += rw;
        }
        rect = { x: rect.x, y: rect.y + rh, w: rect.w, h: rect.h - rh };
      }
      i = j;
    }
    return out;
  };

  /** An annular sector. A full ring is two concentric circles under even-odd —
   *  built from two half-arcs it draws a blob whose centre is not the centre. */
  Viz.arcPath = function arcPath(cx, cy, r0, r1, a0, a1) {
    const TAU = Math.PI * 2;
    const span = a1 - a0;
    const p = (r, a) => `${cx + r * Math.cos(a)} ${cy + r * Math.sin(a)}`;
    if (span >= TAU - 1e-6) {
      return `M${cx + r1} ${cy}A${r1} ${r1} 0 1 0 ${cx - r1} ${cy}A${r1} ${r1} 0 1 0 ${cx + r1} ${cy}`
        + `M${cx + r0} ${cy}A${r0} ${r0} 0 1 0 ${cx - r0} ${cy}A${r0} ${r0} 0 1 0 ${cx + r0} ${cy}Z`;
    }
    const large = span > Math.PI ? 1 : 0;
    return `M${p(r1, a0)}A${r1} ${r1} 0 ${large} 1 ${p(r1, a1)}`
      + `L${p(r0, a1)}A${r0} ${r0} 0 ${large} 0 ${p(r0, a0)}Z`;
  };

  Viz.ribbonPath = function ribbonPath(cx, cy, r, a0, a1, b0, b1) {
    const p = (rad, a) => `${cx + rad * Math.cos(a)} ${cy + rad * Math.sin(a)}`;
    return `M${p(r, a0)}A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${p(r, a1)}`
      + `Q${cx} ${cy} ${p(r, b1)}A${r} ${r} 0 ${b1 - b0 > Math.PI ? 1 : 0} 0 ${p(r, b0)}`
      + `Q${cx} ${cy} ${p(r, a0)}Z`;
  };

  Viz.sankeyLink = function sankeyLink(x0, y0a, y0b, x1, y1a, y1b) {
    const mx = (x0 + x1) / 2;
    return `M${x0} ${y0a}C${mx} ${y0a} ${mx} ${y1a} ${x1} ${y1a}`
      + `L${x1} ${y1b}C${mx} ${y1b} ${mx} ${y0b} ${x0} ${y0b}Z`;
  };

  /** Circle packing by squarified allocation: n log n, never overlapping, and the
   *  inscribed circle is the largest that fits — which is all a pack needs. */
  Viz.pack = function pack(items, x, y, w, h) {
    const total = items.reduce((s, it) => s + Math.max(0, it.value), 0);
    if (!total) return [];
    return Viz.squarify(items, x, y, w, h).map(r => ({
      item: r.item,
      x: r.x + r.w / 2, y: r.y + r.h / 2,
      r: Math.max(1, (Math.min(r.w, r.h) / 2) * 0.94),
      rect: r,
    }));
  };

  /* -------------------------------------------------------------- camera --- */
  /* ══════════════════════════════════════════════════════════════════════════
     Viz.Viewport — one camera for every structure.

     It owns three numbers (k, x, y) and the whole vocabulary of navigation:
     wheel zoom at the cursor, drag pan with momentum, pinch, marquee zoom, fit,
     zoom-to-bounds, animated centre, keyboard, and a back-stack. Structures never
     implement their own; an SVG structure attaches a <g> and a pan costs one
     attribute write.

        world → screen:  sx = wx * k + x     screen → world:  wx = (sx - x) / k
     ══════════════════════════════════════════════════════════════════════════ */
  Viz.Viewport = class Viewport {
    constructor(surface, opts) {
      const o = opts || {};
      this.surface = surface;
      this.onChange = o.onChange || (() => {});
      this.min = o.min == null ? 0.3 : o.min;
      this.max = o.max == null ? 16 : o.max;
      this.pad = o.pad == null ? 16 : o.pad;
      this.world = o.world || { w: 1000, h: 700 };
      this.keyboard = o.keyboard !== false;
      this.dblclick = o.dblclick !== false;
      this.history = [];
      this.histMax = o.history || 32;
      this.k = 1; this.x = 0; this.y = 0;
      this.bounds = { x: 0, y: 0, w: this.world.w, h: this.world.h };
      this.layer = null;
      this._raf = 0;
      this._drag = null;
      this.bind();
    }
    setState(s) {
      const next = s || {};
      if (next.k != null) this.k = Math.min(this.max, Math.max(this.min, next.k));
      if (next.x != null) this.x = next.x;
      if (next.y != null) this.y = next.y;
      this.apply();
      return this;
    }
    mark() { return { k: this.k, x: this.x, y: this.y }; }
    push() {
      this.history.push(this.mark());
      if (this.history.length > this.histMax) this.history.shift();
      return this;
    }
    back({ animate = true } = {}) {
      const prev = this.history.pop();
      if (!prev) return false;
      this.set({ ...prev, animate });
      return true;
    }
    toWorld(clientX, clientY) {
      const r = this.surface.getBoundingClientRect();
      return { x: ((clientX - r.left) - this.x) / this.k, y: ((clientY - r.top) - this.y) / this.k };
    }
    toScreen(wx, wy) { return { x: wx * this.k + this.x, y: wy * this.k + this.y }; }
    attach(layer) { this.layer = layer; this.apply(); return this; }
    apply() {
      if (this.layer) {
        this.layer.setAttribute("transform",
          `translate(${this.x.toFixed(2)} ${this.y.toFixed(2)}) scale(${this.k.toFixed(4)})`);
      }
      this.onChange(this.mark());
      return this;
    }
    stop() {
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = 0;
      return this;
    }
    /** animate k/x/y with an ease-out cubic; the duration collapses to 0 when
     *  motion is off, so every call site can animate unconditionally */
    set({ k = this.k, x = this.x, y = this.y, animate = true, duration = 320 } = {}) {
      this.stop();
      const k1 = Math.min(this.max, Math.max(this.min, k));
      /* a view that has just been replaced has a zero-sized surface; a camera
         asked to frame nothing must keep its last good frame, not write NaN */
      if (![k1, x, y].every(Number.isFinite)) return this;
      if (!animate || Viz.reduced() || duration <= 0) {
        this.k = k1; this.x = x; this.y = y;
        return this.apply();
      }
      const from = { k: this.k, x: this.x, y: this.y };
      const t0 = performance.now();
      const step = () => {
        const p = Math.min(1, (performance.now() - t0) / duration);
        const e = 1 - Math.pow(1 - p, 3);
        this.k = from.k + (k1 - from.k) * e;
        this.x = from.x + (x - from.x) * e;
        this.y = from.y + (y - from.y) * e;
        this.apply();
        if (p < 1) this._raf = requestAnimationFrame(step);
        else this._raf = 0;
      };
      this._raf = requestAnimationFrame(step);
      return this;
    }
    setBounds(b) { this.bounds = b; return this; }
    fit(bbox, { animate = false, minK = 0 } = {}) {
      const b = bbox || this.bounds;
      const r = this.surface.getBoundingClientRect();
      if (!isFinite(b.w) || !isFinite(b.h) || b.w <= 0 || b.h <= 0) return this;
      if (r.width < 2 || r.height < 2) return this;
      const w = Math.max(40, r.width), h = Math.max(40, r.height);
      let k = Math.min((w - this.pad * 2) / Math.max(1, b.w), (h - this.pad * 2) / Math.max(1, b.h));
      /* below the floor, keep the scale readable and centre on the middle of
         the scene: a scene fitted at 12 % is not a view of anything, and the
         middle is where an outline's root sits */
      if (minK && k < minK) k = Math.min(this.max, minK);
      const x = (w - b.w * k) / 2 - b.x * k;
      const y = (h - b.h * k) / 2 - b.y * k;
      return this.set({ k, x, y, animate });
    }
    zoomTo(bbox, { animate = true, air = 1.35 } = {}) {
      const r = this.surface.getBoundingClientRect();
      const k = Math.min((r.width - this.pad) / Math.max(1, bbox.w),
                         (r.height - this.pad) / Math.max(1, bbox.h)) * air;
      const kk = Math.min(this.max, Math.max(this.min, k));
      const cx = bbox.x + bbox.w / 2, cy = bbox.y + bbox.h / 2;
      return this.set({ k: kk, x: r.width / 2 - cx * kk, y: r.height / 2 - cy * kk, animate });
    }
    centerOn(wx, wy, k, { animate = true } = {}) {
      const r = this.surface.getBoundingClientRect();
      const kk = Math.min(this.max, Math.max(this.min, k == null ? this.k : k));
      return this.set({ k: kk, x: r.width / 2 - wx * kk, y: r.height / 2 - wy * kk, animate });
    }
    zoomAt(factor, px, py) {
      if (!isFinite(factor) || factor <= 0) return this;
      const r = this.surface.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return this;
      const cx = px == null ? r.width / 2 : px - r.left;
      const cy = py == null ? r.height / 2 : py - r.top;
      const k1 = Math.min(this.max, Math.max(this.min, this.k * factor));
      const ratio = k1 / this.k;
      this.stop();
      this.k = k1;
      this.x = cx - (cx - this.x) * ratio;
      this.y = cy - (cy - this.y) * ratio;
      return this.apply();
    }
    zoomBy(factor) { return this.zoomAt(factor); }
    panBy(dx, dy) { this.stop(); this.x += dx; this.y += dy; return this.apply(); }
    reset() { return this.fit(null, { animate: true }); }

    bind() {
      const s = this.surface;
      const wheel = (ev) => {
        if (ev.ctrlKey || ev.metaKey || Math.abs(ev.deltaY) > 0) {
          ev.preventDefault();
          const factor = Math.pow(1.0016, -ev.deltaY * (ev.deltaMode === 1 ? 16 : 1));
          this.zoomAt(factor, ev.clientX, ev.clientY);
        }
      };
      s.addEventListener("wheel", wheel, { passive: false });

      s.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0) return;
        if (ev.target.closest && ev.target.closest("[data-nid]")) return;   // marks own their gestures
        this.stop();
        this.push();
        this._drag = { id: ev.pointerId, x: ev.clientX, y: ev.clientY,
                       cx: this.x, cy: this.y, moved: false, t: performance.now(),
                       vx: 0, vy: 0, lx: ev.clientX, ly: ev.clientY };
        s.setPointerCapture(ev.pointerId);
        s.classList.add("is-panning");
      });
      s.addEventListener("pointermove", (ev) => {
        const d = this._drag;
        if (!d || d.id !== ev.pointerId) return;
        const dx = ev.clientX - d.x, dy = ev.clientY - d.y;
        if (!d.moved && Math.hypot(dx, dy) > 3) d.moved = true;
        if (!d.moved) return;
        this.x = d.cx + dx; this.y = d.cy + dy;
        d.vx = ev.clientX - d.lx; d.vy = ev.clientY - d.ly;
        d.lx = ev.clientX; d.ly = ev.clientY;
        this.apply();
      });
      const end = (ev) => {
        const d = this._drag;
        if (!d || d.id !== ev.pointerId) return;
        this._drag = null;
        try { s.releasePointerCapture(ev.pointerId); } catch (e) { /* already gone */ }
        s.classList.remove("is-panning");
        if (d.moved && !Viz.reduced()) {
          /* a little momentum: the scene keeps the velocity of the hand for a
             moment, which is what makes a map feel like a surface */
          let vx = d.vx, vy = d.vy;
          const glide = () => {
            vx *= 0.92; vy *= 0.92;
            if (Math.abs(vx) < 0.4 && Math.abs(vy) < 0.4) return;
            this.x += vx; this.y += vy;
            this.apply();
            this._raf = requestAnimationFrame(glide);
          };
          if (Math.abs(vx) + Math.abs(vy) > 2) this._raf = requestAnimationFrame(glide);
        }
      };
      s.addEventListener("pointerup", end);
      s.addEventListener("pointercancel", end);

      if (this.dblclick) {
        s.addEventListener("dblclick", (ev) => {
          if (ev.target.closest && ev.target.closest("[data-nid]")) return;
          this.zoomAt(ev.shiftKey ? 0.6 : 1.7, ev.clientX, ev.clientY);
        });
      }

      if (this.keyboard) {
        s.addEventListener("keydown", (ev) => {
          const step = 48 / this.k;
          const keys = {
            "+": () => this.zoomAt(1.25), "=": () => this.zoomAt(1.25),
            "-": () => this.zoomAt(0.8), "_": () => this.zoomAt(0.8),
            "0": () => this.fit(null, { animate: true }),
            f: () => this.fit(null, { animate: true }),
            F: () => this.fit(null, { animate: true }),
            ArrowLeft: () => this.panBy(step, 0),
            ArrowRight: () => this.panBy(-step, 0),
            ArrowUp: () => this.panBy(0, step),
            ArrowDown: () => this.panBy(0, -step),
          };
          const fn = keys[ev.key];
          if (!fn) return;
          ev.preventDefault();
          fn();
        });
      }
    }
    destroy() { this.stop(); this.layer = null; }
  };

  /* ---------------------------------------------------------- interaction --- */
  /**
   * The interaction kernel: one implementation of hover, selection, drill and
   * keyboard for every structure. A structure only writes `data-nid` on its
   * marks; this class turns that into behaviour.
   */
  Viz.Interact = class Interact {
    constructor(host, opts) {
      const o = opts || {};
      this.host = host;
      this.onHover = o.onHover || (() => {});
      this.onSelect = o.onSelect || (() => {});
      this.onDrill = o.onDrill || (() => {});
      this.tip = o.tip || null;
      this.selectedId = null;
      this.bind();
    }
    markOf(target) {
      const el = target && target.closest ? target.closest("[data-nid]") : null;
      return el ? el.getAttribute("data-nid") : null;
    }
    setSelected(id) {
      this.selectedId = id == null ? null : String(id);
      for (const el of this.host.querySelectorAll("[data-nid]")) {
        el.classList.toggle("is-selected", el.getAttribute("data-nid") === this.selectedId);
      }
      return this;
    }
    bind() {
      const host = this.host;
      const over = (ev) => {
        const id = this.markOf(ev.target);
        if (id === this._last) return;
        this._last = id;
        host.classList.toggle("has-hover", !!id);
        this.onHover(id, ev);
      };
      host.addEventListener("pointermove", over);
      host.addEventListener("pointerleave", () => {
        this._last = null;
        host.classList.remove("has-hover");
        this.onHover(null, null);
      });
      host.addEventListener("click", (ev) => {
        const id = this.markOf(ev.target);
        if (!id) return;
        const el = ev.target.closest("[data-nid]");
        if (ev.shiftKey) this.onSelect(id, { additive: true, el });
        else if (ev.altKey) this.onDrill(id, { el });
        else if (ev.detail >= 2) this.onDrill(id, { el });
        else this.onSelect(id, { additive: false, el });
      });
      host.addEventListener("dblclick", (ev) => {
        const id = this.markOf(ev.target);
        if (!id) return;
        ev.preventDefault();
        this.onDrill(id, { el: ev.target.closest("[data-nid]") });
      });
      host.addEventListener("keydown", (ev) => {
        if (!ev.target.closest || !ev.target.closest("[data-nid]")) return;
        const el = ev.target.closest("[data-nid]");
        const id = el.getAttribute("data-nid");
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); this.onSelect(id, { el }); }
        else if (ev.key === "ArrowRight" || ev.key === "ArrowDown") {
          const all = [...host.querySelectorAll("[data-nid]")];
          const i = all.indexOf(el);
          if (i >= 0 && all[i + 1]) { ev.preventDefault(); all[i + 1].focus(); }
        } else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") {
          const all = [...host.querySelectorAll("[data-nid]")];
          const i = all.indexOf(el);
          if (i > 0) { ev.preventDefault(); all[i - 1].focus(); }
        }
      });
    }
    destroy() { /* listeners live on the host, which the view replaces */ }
  };

  /* ------------------------------------------------------------- animation --- */
  /** Keyed interpolation between two layouts: elements that keep their `data-nid`
   *  move to the new geometry instead of being redrawn. */
  Viz.tween = function tween({ duration = 240, onDone, nodes = [] } = {}) {
    const els = nodes.filter(n => n && n.el && n.from && n.to);
    if (!els.length || Viz.reduced() || duration <= 0) {
      for (const n of els) n.apply(n.to);
      if (onDone) onDone();
      return { cancel() {} };
    }
    const t0 = performance.now();
    let raf = 0;
    const step = () => {
      const p = Math.min(1, (performance.now() - t0) / duration);
      const e = 1 - Math.pow(1 - p, 3);
      for (const n of els) {
        const mix = {};
        for (const key of Object.keys(n.to)) {
          const a = n.from[key], b = n.to[key];
          mix[key] = typeof b === "number" && typeof a === "number" ? a + (b - a) * e : (p < 1 ? a : b);
        }
        n.apply(mix);
      }
      if (p < 1) raf = requestAnimationFrame(step);
      else if (onDone) onDone();
    };
    raf = requestAnimationFrame(step);
    return { cancel() { cancelAnimationFrame(raf); } };
  };

  /** One entry animation, named so a structure can stagger with it. */
  Viz.stagger = function stagger(els, { step = 18, limit = 900 } = {}) {
    if (Viz.reduced()) return;
    els.slice(0, limit).forEach((el, i) => {
      el.style.animationDelay = `${Math.min(600, i * step)}ms`;
      el.classList.add("viz-in");
    });
  };

  /* ------------------------------------------------------------ fallbacks --- */
  Viz.toTable = function toTable(model, { metric, max = 300 } = {}) {
    const rows = model.flat.slice(0, max);
    const head = `<tr><th>${A.esc(A.t("viz.node"))}</th><th>${A.esc(A.t("viz.path"))}</th>` +
      `<th class="num">${A.esc(metric || A.t("viz.value"))}</th><th class="num">${A.esc(A.t("viz.share"))}</th></tr>`;
    const body = rows.map(n => `<tr><td>${A.esc(model.A.label(n))}</td>` +
      `<td class="muted">${A.esc(model.pathOf(n).slice(-3).join(" › "))}</td>` +
      `<td class="num">${A.fmtNum(Math.round(n.__v))}</td>` +
      `<td class="num">${model.total ? ((n.__v / model.total) * 100).toFixed(1) + "%" : "—"}</td></tr>`).join("");
    return `<table class="viz-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  };

  Viz.toSvg = function toSvg(svgEl, { background = "#ffffff" } = {}) {
    const clone = svgEl.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const css = [...document.styleSheets].flatMap(sheet => {
      try { return [...sheet.cssRules].map(r => r.cssText); } catch (e) { return []; }
    }).filter(t => /viz-|topo-|\.lbl/.test(t)).join("\n");
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = css + `text{font-family:system-ui,sans-serif}`;
    clone.insertBefore(style, clone.firstChild);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", "100%"); rect.setAttribute("height", "100%");
    rect.setAttribute("fill", background);
    clone.insertBefore(rect, clone.firstChild);
    return new XMLSerializer().serializeToString(clone);
  };

  /* --------------------------------------------------------------- helpers --- */
  Viz.esc = (s) => A.esc(s);
  Viz.alpha = function alpha(hex, a) {
    const h = String(hex).replace("#", "");
    const full = h.length === 3 ? h.split("").map(c => c + c).join("") : h;
    const n = parseInt(full, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  Viz.fit = function fit(text, px, size) {
    const s = String(text || "");
    const per = (size || 11) * 0.56;
    const max = Math.max(3, Math.floor((px || 40) / per));
    if (s.length <= max) return s;
    const rtl = /[\u0590-\u08FF]/.test(s.trim().charAt(0));
    /* truncate where the reader is not: the end of an Arabic name is its
       beginning, so the ellipsis goes first */
    return rtl ? "…" + s.slice(-(max - 1)) : s.slice(0, max - 1) + "…";
  };
  Viz.dirSign = () => (document.documentElement.dir === "rtl" ? -1 : 1);

  A.viz = {
    Viz, adapter,
    build: Viz.build,
    scaleLinear, scaleSqrt,
    squarify: Viz.squarify, arcPath: Viz.arcPath, ribbonPath: Viz.ribbonPath,
    sankeyLink: Viz.sankeyLink, pack: Viz.pack,
    Viewport: Viz.Viewport, Interact: Viz.Interact,
    tween: Viz.tween, stagger: Viz.stagger,
    toTable: Viz.toTable, toSvg: Viz.toSvg,
    alpha: Viz.alpha, fit: Viz.fit, reduced: () => Viz.reduced(),
    note: (s, ms, m) => Viz.note(s, ms, m),
    PALETTE,
  };
})(window.App);
