/* ============================================================================
   CRCE — Compass-Rose Coordinate Encoding, in the browser
   ----------------------------------------------------------------------------
   The marks are not drawn here by hand: the geometry arrives from the server
   (`GET /api/crce/standard`, `GET /api/crce/dossier/...`) as primitives in a
   100 × 100 box, and this file is one interpreter for that description. So the
   rose on a record, the rose in a downloaded figure and the rose on the map are
   provably the same drawing, and a change to a mark is a change in one place.

   Three renderers, one source:
     · svgString()   — markup for panels, exports and documentation
     · attach()      — an SVG element inside a card, with the bearing needle
     · iconImage()   — a canvas image for MapLibre, for map markers
   ========================================================================== */
(function (A) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const BOX = 100;
  const COLOUR = { ink: "#ffffff", dim: "#b9c0c7", accent: "#e3c05a" };
  const BG = "#33383d";
  /* Map badges: saturated mid-tones that hold against both pale vector tiles and
     dark satellite imagery — darker than the soft halo, lighter than pure ink. */
  const MAP_BG = {
    person: "#2f6f4f",
    organization: "#1f5d8b",
    place: "#8a5a1f",
    event: "#7b3f8f"
  };

  const state = { standard: null, loading: null };

  /* ------------------------------------------------------------- data --- */
  async function standard() {
    if (state.standard) return state.standard;
    if (!state.loading) {
      state.loading = A.api.get("/api/crce/standard")
        .then(d => (state.standard = d))
        .catch(err => { state.loading = null; throw err; });
    }
    return state.loading;
  }

  function symbol(idOrCategory) {
    const std = state.standard;
    if (!std) return null;
    const syms = std.symbols || {};
    if (syms[idOrCategory]) return syms[idOrCategory];
    return Object.values(syms).find(s => s.id === idOrCategory) || null;
  }

  /* --------------------------------------------------------- primitives --- */
  function polar(r, deg) {
    const a = (deg * Math.PI) / 180;
    return [50 + r * Math.sin(a), 50 - r * Math.cos(a)];
  }

  function arcPath(p) {
    const [x1, y1] = polar(p.r, p.a1);
    const [x2, y2] = polar(p.r, p.a2);
    const large = (((p.a2 - p.a1) % 360) + 360) % 360 > 180 ? 1 : 0;
    return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${p.r} ${p.r} 0 ${large} 1 ` +
           `${x2.toFixed(2)} ${y2.toFixed(2)}`;
  }

  function each(geometry, size, fn) {
    (geometry || []).forEach(p => {
      if (p.min_size && size < p.min_size) return;
      fn(p, COLOUR[p.role] || COLOUR.ink);
    });
  }

  /* ------------------------------------------------------------ needle ---
     The mark is a symbol, not an instrument reading: its ring, its letters and
     its graduations must stay upright, or a rose on a map would read north-east
     while north is still north. So the bearing is a separate needle drawn over
     the mark — an accent ray from the centre to the rim, with a head. */
  function needleMarkup(rotation, size) {
    const inner = size * 0.8;
    const pad = (size - inner) / 2;
    const k = inner / BOX;
    const a = ((Number(rotation) || 0) * Math.PI) / 180;
    const x2 = 50 + 46 * Math.sin(a), y2 = 50 - 46 * Math.cos(a);
    const ax = 50 + 36 * Math.sin(a), ay = 50 - 36 * Math.cos(a);
    const side = a + Math.PI / 2;
    const hx = 4.6 * Math.sin(side), hy = -4.6 * Math.cos(side);
    return `<g class="crce-needle" transform="translate(${pad.toFixed(2)} ${pad.toFixed(2)}) scale(${k.toFixed(4)})">`
      + `<line x1="50" y1="50" x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}" `
      + `stroke="${COLOUR.accent}" stroke-width="2.6" stroke-linecap="round" stroke-opacity=".95"/>`
      + `<polygon points="${x2.toFixed(2)},${y2.toFixed(2)} ${(ax + hx).toFixed(2)},${(ay + hy).toFixed(2)} `
      + `${(ax - hx).toFixed(2)},${(ay - hy).toFixed(2)}" fill="${COLOUR.accent}" fill-opacity=".95"/>`
      + `<circle cx="50" cy="50" r="2.6" fill="${COLOUR.accent}"/></g>`;
  }

  /* ------------------------------------------------------------ svg --- */
  function svgString(idOrCategory, size, opts) {
    const sym = symbol(idOrCategory);
    if (!sym) return "";
    const s = size || 64;
    const o = opts || {};
    const inner = s * 0.8;
    const pad = (s - inner) / 2;
    const parts = [];
    each(sym.geometry, s, (p, colour) => {
      if (p.op === "ring") {
        parts.push(`<circle cx="${p.cx}" cy="${p.cy}" r="${p.r}" fill="none" ` +
                   `stroke="${colour}" stroke-width="${p.width}"/>`);
      } else if (p.op === "dot") {
        parts.push(`<circle cx="${p.cx}" cy="${p.cy}" r="${p.r}" fill="${colour}"/>`);
      } else if (p.op === "line") {
        parts.push(`<line x1="${p.x1}" y1="${p.y1}" x2="${p.x2}" y2="${p.y2}" ` +
                   `stroke="${colour}" stroke-width="${p.width}" stroke-linecap="round"/>`);
      } else if (p.op === "arc") {
        parts.push(`<path d="${arcPath(p)}" fill="none" stroke="${colour}" ` +
                   `stroke-width="${p.width}" stroke-linecap="round"/>`);
      } else if (p.op === "poly") {
        const pts = p.points.map(([x, y]) => `${x},${y}`).join(" ");
        const tag = p.closed ? "polygon" : "polyline";
        parts.push(`<${tag} points="${pts}" fill="${p.fill ? colour : "none"}" ` +
                   `stroke="${colour}" stroke-width="${p.width}" stroke-linejoin="round"/>`);
      } else if (p.op === "text") {
        parts.push(`<text x="${p.x}" y="${p.y}" fill="${colour}" font-size="${p.size}" ` +
                   `font-family="system-ui,sans-serif" text-anchor="${p.anchor || "middle"}" ` +
                   `letter-spacing=".5">${p.text}</text>`);
      }
    });
    const body =
      `<g transform="translate(${pad.toFixed(2)} ${pad.toFixed(2)}) scale(${(inner / BOX).toFixed(4)})">` +
      parts.join("") + `</g>` +
      (o.needle === false ? "" : needleMarkup(o.rotation || 0, s));
    const disc = o.badge === false ? "" :
      `<circle cx="${s / 2}" cy="${s / 2}" r="${s / 2 - 0.5}" fill="${o.background || BG}"/>`;
    return `<svg xmlns="${NS}" width="${s}" height="${s}" viewBox="0 0 ${s} ${s}" ` +
           `class="crce-svg${o.needle === false ? " is-static" : ""}" ` +
           `role="img" aria-label="${A.esc(sym.label_en)}">${disc}${body}</svg>`;
  }

  function attach(host, dossier, opts) {
    if (!host) return;
    const rose = (dossier && dossier.rose) || {};
    const size = (opts && opts.size) || 84;
    const symId = rose.symbol || (dossier && dossier.entity && dossier.entity.symbol);
    if (!symId) {
      host.innerHTML = `<div class="crce-none">${A.esc(A.t("crce.notCovered"))}</div>`;
      return;
    }
    host.innerHTML = svgString(symId, size, {
      rotation: rose.rotation_deg || 0,
      needle: rose.needle !== false,
      badge: (opts && opts.badge) !== false
    });
    host.classList.toggle("is-unlocated", rose.state === "unlocated");
  }

  /* ----------------------------------------------------------- canvas --- */
  function iconImage(idOrCategory, size, opts) {
    const sym = symbol(idOrCategory);
    if (!sym) return null;
    const s = size || 40;
    const o = opts || {};
    const canvas = document.createElement("canvas");
    const dpr = 2;
    canvas.width = canvas.height = s * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    if (o.badge !== false) {
      const cx = s / 2, cy = s / 2;
      /* drop shadow baked into the atlas image — MapLibre won't CSS-shadow symbols */
      ctx.fillStyle = "rgba(8,14,22,.35)";
      ctx.beginPath();
      ctx.arc(cx + 0.8, cy + 1.2, s / 2 - 0.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = o.background || BG;
      ctx.beginPath();
      ctx.arc(cx, cy, s / 2 - 1, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.78)";
      ctx.lineWidth = 1.6;
      ctx.stroke();
      ctx.strokeStyle = "rgba(0,0,0,.22)";
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.arc(cx, cy, s / 2 - 2.4, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.save();
    const inner = s * 0.8;
    ctx.translate((s - inner) / 2, (s - inner) / 2);
    ctx.scale(inner / BOX, inner / BOX);
    each(sym.geometry, s, (p, colour) => {
      ctx.strokeStyle = colour;
      ctx.fillStyle = colour;
      ctx.lineWidth = p.width || 1.5;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      if (p.op === "ring") {
        ctx.beginPath();
        ctx.arc(p.cx, p.cy, p.r, 0, Math.PI * 2);
        ctx.stroke();
      } else if (p.op === "dot") {
        ctx.beginPath();
        ctx.arc(p.cx, p.cy, p.r * 1.15, 0, Math.PI * 2);
        ctx.fill();
      } else if (p.op === "line") {
        ctx.beginPath();
        ctx.moveTo(p.x1, p.y1);
        ctx.lineTo(p.x2, p.y2);
        ctx.stroke();
      } else if (p.op === "arc") {
        ctx.beginPath();
        ctx.arc(p.cx, p.cy, p.r, ((p.a1 - 90) * Math.PI) / 180, ((p.a2 - 90) * Math.PI) / 180);
        ctx.stroke();
      } else if (p.op === "poly") {
        ctx.beginPath();
        p.points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        if (p.closed) ctx.closePath();
        if (p.fill) ctx.fill();
        if (p.width) ctx.stroke();
      } else if (p.op === "text") {
        ctx.font = `600 ${p.size}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(p.text, p.x, p.y);
      }
    });
    ctx.restore();
    if (o.needle !== false && o.rotation) {
      const inner2 = s * 0.8, pad2 = (s - inner2) / 2, k2 = inner2 / BOX;
      const a = ((Number(o.rotation) || 0) * Math.PI) / 180;
      ctx.save();
      ctx.translate(pad2, pad2);
      ctx.scale(k2, k2);
      ctx.strokeStyle = COLOUR.accent;
      ctx.fillStyle = COLOUR.accent;
      ctx.lineWidth = 2.6;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(50, 50);
      ctx.lineTo(50 + 46 * Math.sin(a), 50 - 46 * Math.cos(a));
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(50 + 46 * Math.sin(a), 50 - 46 * Math.cos(a), 3.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    /* The canvas is drawn at device resolution so the mark is crisp; report the
       size the canvas actually has. The first version reported the CSS size and
       returned a `{canvas, width, height}` wrapper, which MapLibre rejected with
       "mismatched image size" — swallowed by a try/catch, so the marks silently
       never reached the map. */
    return {
      canvas, width: canvas.width, height: canvas.height, size: s,
      data: (() => {
        try { return ctx.getImageData(0, 0, canvas.width, canvas.height).data; }
        catch (e) { return null; }
      })()
    };
  }

  function iconDataUrl(idOrCategory, size) {
    const made = iconImage(idOrCategory, size, { badge: true });
    return made ? made.canvas.toDataURL("image/png") : null;
  }

  /** Register the reserved marks with a MapLibre map, once. */
  /**
   * Register the three reserved marks as map images.
   *
   * `map.addImage` throws while the style is still loading, and the first version
   * caught that exception and said nothing — which is why the marks existed on the
   * record page and never once appeared on the map. The rule now: wait for the
   * style, add at a known pixel ratio, and *report* whether every image is really
   * there. Callers that get `false` must not draw a symbol layer that refers to a
   * missing image.
   */
  /**
   * Events are outside the four reserved CRCE marks — they must not borrow them.
   * Companion glyph: same disc language, diamond (instant) + clock arc (duration).
   * A soft outer rim echoes the CRCE ring so the atlas reads as one system.
   */
  function eventIconImage(size) {
    const s = size || 44;
    const dpr = 2;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = s * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.scale(dpr, dpr);
    const cx = s / 2, cy = s / 2;
    /* soft bloom under the disc — MapLibre has no CSS shadow on symbols */
    const bloom = ctx.createRadialGradient(cx, cy, s * 0.28, cx, cy, s / 2);
    bloom.addColorStop(0, "rgba(123,63,143,.55)");
    bloom.addColorStop(1, "rgba(123,63,143,0)");
    ctx.fillStyle = bloom;
    ctx.beginPath();
    ctx.arc(cx, cy, s / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = MAP_BG.event;
    ctx.beginPath();
    ctx.arc(cx, cy, s / 2 - 1.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,.55)";
    ctx.lineWidth = 1;
    ctx.stroke();
    /* outer graduation ticks — kinship with the rose */
    ctx.strokeStyle = "rgba(237,217,247,.55)";
    ctx.lineWidth = 1.2;
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2 - Math.PI / 2;
      const r0 = s * 0.38, r1 = s * 0.44;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
      ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
      ctx.stroke();
    }
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(Math.PI / 4);
    const r = s * 0.15;
    ctx.fillStyle = "rgba(237,217,247,.18)";
    ctx.fillRect(-r, -r, r * 2, r * 2);
    ctx.strokeStyle = "#edd9f7";
    ctx.lineWidth = 2;
    ctx.strokeRect(-r, -r, r * 2, r * 2);
    ctx.restore();
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = COLOUR.accent;
    ctx.lineWidth = 2.2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(0, 0, s * 0.27, -Math.PI * 0.2, Math.PI * 0.95);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, -s * 0.27, 2.4, 0, Math.PI * 2);
    ctx.fillStyle = COLOUR.accent;
    ctx.fill();
    ctx.restore();
    return {
      canvas, width: canvas.width, height: canvas.height, size: s,
      data: (() => {
        try { return ctx.getImageData(0, 0, canvas.width, canvas.height).data; }
        catch (e) { return null; }
      })()
    };
  }

  function addMapImage(map, id, made) {
    if (!made || !map.addImage) return false;
    if (map.hasImage && map.hasImage(id)) {
      try { map.removeImage(id); } catch (e) { /* keep going */ }
    }
    const asset = made.data
      ? { width: made.width, height: made.height, data: made.data }
      : made.canvas;
    try {
      map.addImage(id, asset, { pixelRatio: 2 });
      return !!(map.hasImage && map.hasImage(id));
    } catch (err) {
      return false;
    }
  }

  async function registerMapIcons(map, size) {
    await standard();
    const reserved = ((state.standard && state.standard.standard) || {}).reserved || [];
    const wanted = reserved.map(cat => `crce-${cat}`).concat(["siraj-event"]);
    const have = () => wanted.every(id => map.hasImage && map.hasImage(id));
    const styleReady = () => !map.isStyleLoaded || map.isStyleLoaded();
    if (!styleReady()) {
      await new Promise(resolve => {
        let done = false;
        const finish = () => { if (!done) { done = true; map.off("styledata", finish); resolve(); } };
        map.on("styledata", finish);
        setTimeout(finish, 4000);          // a style that never loads must not hang the call
      });
    }
    for (const cat of reserved) {
      const id = `crce-${cat}`;
      const made = iconImage(cat, size || 48, {
        badge: true, needle: false,
        background: MAP_BG[cat] || BG
      });
      if (!addMapImage(map, id, made)) {
        await new Promise(r => setTimeout(r, 80));
        addMapImage(map, id, made);
      }
    }
    /* uncovered companion — never named crce-* */
    if (!addMapImage(map, "siraj-event", eventIconImage(size || 48))) {
      await new Promise(r => setTimeout(r, 80));
      addMapImage(map, "siraj-event", eventIconImage(size || 48));
    }
    return have();
  }

  /** The layer expression that picks the mark for each record type. */
  function iconExpression() {
    return ["match", ["get", "etype"],
      "person", "crce-person",
      "institution", "crce-organization",
      "place", "crce-place",
      "event", "siraj-event",
      "crce-place"];
  }

  /* ------------------------------------------------------ the dossier ---
     The published field order, rendered: entity → coordinates → orientation →
     relative position → the mark → relations → what the reader must know.
     Everything is labelled; nothing is inferred for display. */
  /* distances read the way the rest of the interface writes numbers: metres up
     close, one decimal under 100 km, then whole kilometres with grouping */
  function kmText(metres) {
    const m = Number(metres);
    if (!isFinite(m)) return "—";
    if (m < 1000) return `${Math.round(m)} m`;
    const km = m / 1000;
    return km < 100
      ? `${km.toFixed(1)} km`
      : `${Number(km.toFixed(0)).toLocaleString("en-US")} km`;
  }

  function row(label, value, cls) {
    if (value === null || value === undefined || value === "") return "";
    return `<dt>${A.esc(label)}</dt><dd class="${cls || ""}">${value}</dd>`;
  }

  function panel(d) {
    const ar = A.state.lang === "ar";
    const pick = (en, ary) => (ar ? (ary || en) : en);
    const ent = d.entity || {};
    const c = d.coordinates;
    const o = d.orientation;
    const std = d.standard || {};
    const rose = d.rose || {};
    const sym = symbol(rose.symbol);

    const status = `<span class="crce-status s-${A.esc(d.status || "unlocated")}">
        ${A.esc(pick(d.status, d.status_ar))}</span>`;

    /* entity */
    const head = `
      <div class="crce-head">
        <div class="crce-mark" data-crce-mark></div>
        <div class="crce-id">
          <div class="crce-kicker">${A.esc(pick("Entity definition", "تعريف الكيان"))}
            <span class="mono-cell">${A.esc(std.id || "CRCE")} ${A.esc(std.version || "")}</span></div>
          <h3 dir="auto">${A.esc(pick(ent.name_en, ent.name_ar))}</h3>
          <div class="crce-sub">
            <span class="mono-cell">${A.esc(ent.code || "")}</span>
            <span>${A.esc(pick(ent.category_label_en, ent.category_label_ar))}</span>
            ${status}
          </div>
        </div>
      </div>`;

    /* coordinates */
    let coords = `<div class="notice">${A.esc(pick(
      "No coordinates. No georeferenced place is recorded, so no mark is filled in.",
      "لا إحداثيات. لا مكان مُسنَد جغرافياً، فلا تُستكمل أي علامة."))}</div>`;
    if (c) {
      const f = c.formats || {};
      const crs = (f.web_mercator || {});
      const crs84 = (f.crs84 || {});
      coords = `<dl class="crce-facts">
        ${row(pick("Primary coordinates", "الإحداثيات الأساسية"),
              `<span class="mono-cell" dir="ltr">${A.esc(f.decimal_degrees ? f.decimal_degrees.value : "")}</span>`)}
        ${row(pick("Coordinate reference system", "نظام الإسناد"),
              `<span class="mono-cell">${A.esc((f.decimal_degrees || {}).crs || "EPSG:4326")}</span>
               <span class="muted small">${A.esc(pick("stored; nothing is re-projected in place",
                                                      "مخزّن؛ ولا يُعاد إسقاط أي شيء مكانه"))}</span>`)}
        ${row(pick("Degrees, minutes, seconds", "الدرجات والدقائق والثواني"),
              `<span class="mono-cell" dir="ltr">${A.esc(f.dms || "")}</span>`)}
        ${row(pick("Derived notations", "تدوينات مشتقة"),
              `<span class="mono-cell" dir="ltr">CRS84 ${A.esc(crs84.lon)}, ${A.esc(crs84.lat)}</span>
               <span class="mono-cell small" dir="ltr">Web Mercator ${A.esc(crs.x)}, ${A.esc(crs.y)}</span>`)}
        ${row(pick("What the point is", "ما هي هذه النقطة"),
              `<b>${A.esc(pick(c.role && c.role.en, c.role && c.role.ar))}</b>
               ${c.inherited ? `<span class="muted small">${A.esc(pick("inherited from a place",
                                                                        "مستعارة من مكان"))}</span>` : ""}`)}
        ${row(pick("Precision on file", "الدقة المسجّلة"),
              `<span class="crce-prec p-${A.esc((c.precision || {}).status)}">
                 ${A.esc(pick((c.precision || {}).label_en, (c.precision || {}).label_ar) ||
                         pick("unrecorded", "غير مسجّلة"))}</span>
               ${c.uncertainty_m ? `<span class="muted small">± ${Math.round(c.uncertainty_m)} m</span>` : ""}`)}
        ${c.place ? row(pick("Place on file", "المكان المسجّل"),
              `<a href="${A.esc(c.place.href)}">${A.esc(pick(c.place.name_en, c.place.name_ar))}</a>
               <span class="mono-cell small">${A.esc(c.place.code || "")}</span>`) : ""}
        ${row(pick("How it was obtained", "كيف حُصل عليه"),
              A.esc(c.method || pick("not recorded", "غير مسجّل")))}
        ${row(pick("Supplied by", "مصدر البيانات"), A.esc(c.source || pick("not recorded", "غير مسجّل")))}
      </dl>`;
    }

    /* orientation */
    let orient = `<div class="notice">${A.esc(pick(
      "No bearing. Direction needs a real reference point and this record has none, "
      + "so the mark is drawn upright and without a needle.",
      "لا اتجاه. الاتجاه يحتاج نقطة مرجعية حقيقية ولا توجد لهذا السجل، لذلك تُرسم العلامة "
      + "معتدلة وبلا إبرة."))}</div>`;
    if (d.ends_coincident) {
      orient = `<div class="notice">${A.esc(pick(
        "Both ends resolve to the same recorded point, so there is no bearing to draw: "
        + "a zero-length vector has no azimuth. The distance and each end's fix are still shown.",
        "ينتهي الطرفان إلى النقطة المسجّلة نفسها، فلا يوجد اتجاه يُرسم: المتجه الصفري بلا "
        + "زاوية سمت. تبقى المسافة وإحداثيات كل طرف معروضة."))}</div>`;
    }
    if (o) {
      orient = `<dl class="crce-facts">
        ${row(pick("Bearing / azimuth", "الاتجاه / السمت"),
              `<b class="mono-cell" dir="ltr">${A.esc(o.bearing_deg)}°</b>
               <span class="crce-point">${A.esc(pick(o.en, o.ar))}</span>`)}
        ${row(pick("Great-circle distance", "المسافة على الدائرة العظمى"),
              `<span class="mono-cell" dir="ltr">${A.esc(kmText(o.distance_m))}</span>`)}
        ${row(pick("Measured from", "مقيساً من"),
              `${A.esc(pick(o.reference.label_en, o.reference.label_ar))}
               ${o.reference.conceptual
                 ? `<span class="badge amber">${A.esc(pick("conceptual reference", "مرجعية تصورية"))}</span>`
                 : ""}`)}
        ${row(pick("In one phrase", "بعبارة واحدة"),
              `<em>${A.esc(pick(o.phrase_en, o.phrase_ar))}</em>`)}
      </dl>`;
    }

    /* relative position */
    const rel = d.relative || {};
    const inside = rel.inside;
    const relative = (inside || rel.parent) ? `<dl class="crce-facts">
        ${inside ? row(pick("Falls inside", "يقع داخل"),
            `${A.esc(pick(inside.name_en, inside.name_ar))}
             <span class="muted small">${A.esc(pick(inside.method_en, inside.method_ar))}</span>`) : ""}
        ${rel.parent ? row(pick("Within", "ضمن"),
            `<a href="${A.esc(rel.parent.href)}">${A.esc(pick(rel.parent.name_en, rel.parent.name_ar))}</a>`) : ""}
      </dl>` : "";

    /* the mark itself */
    const legend = sym ? `<div class="crce-legend">
        <div class="crce-legend-row"><b>${A.esc(pick(sym.label_en, sym.label_ar))}</b>
          <span>${A.esc(pick(sym.means_en, sym.means_ar))}</span></div>
        <div class="crce-legend-row small muted">
          <span>${A.esc(pick("reserved for this category alone",
                             "محفوظة لهذا النوع وحده"))}</span>
          <span>${A.esc(pick("rings", "حلقات"))}: ${rose.rings || 0} ·
                ${A.esc(pick("graduations", "تدريجات"))}: ${rose.ticks || 0} ·
                ${A.esc(pick("needle", "إبرة"))}: ${rose.needle ? "✓" : "—"}</span>
        </div>
      </div>` : "";

    /* relations, with their own direction */
    const rels = (d.relations || []).length ? `
      <h4 class="crce-h">${A.esc(pick("Relationship mapping", "تعيين العلاقات"))}</h4>
      <div class="crce-rels">
        ${d.relations.map(r => `
          <a class="crce-rel${r.located ? "" : " no-fix"}" href="#/entity/${A.esc(r.type)}/${r.id}">
            <span class="crce-rel-mark">${r.symbol ? svgString(r.symbol, 22) : ""}</span>
            <span class="crce-rel-body">
              <span class="crce-rel-name" dir="auto">${A.esc(pick(r.name_en, r.name_ar))}</span>
              <span class="crce-rel-type">${A.esc(pick(r.label_en, r.label_ar))}
                ${r.outgoing ? "→" : "←"}</span>
            </span>
            <span class="crce-rel-dir">${r.same_point
              ? `<span class="muted">${A.esc(pick(r.phrase_en, r.phrase_ar))}</span>`
              : r.phrase_en
                ? `<b dir="ltr">${A.esc(r.bearing_deg)}°</b>
                   <span>${A.esc(pick(r.phrase_en, r.phrase_ar))}</span>`
                : `<span class="muted">${A.esc(pick("no fix", "بلا إحداثيات"))}</span>`}</span>
          </a>`).join("")}
      </div>` : "";

    /* what the reader must know */
    const notes = (d.notes || []).length ? `
      <h4 class="crce-h">${A.esc(pick("Notes on accuracy", "ملاحظات على الدقة"))}</h4>
      <ul class="crce-notes">
        ${d.notes.map(n => `<li class="lvl-${A.esc(n.level)}">
          <span class="crce-note-code">${A.esc(n.code.replace(/_/g, " "))}</span>
          <span dir="auto">${A.esc(pick(n.en, n.ar))}</span></li>`).join("")}
      </ul>` : "";

    const sections = [
      ["Entity definition", "تعريف الكيان", head],
      ["Coordinate encoding", "ترميز الإحداثيات", coords],
      ["Orientation", "التوجيه", orient],
      ["Relative position", "الموقع النسبي", relative],
      ["Compass rose representation", "تمثيل الوردة الملاحية", legend],
      relationsBlock(rels)
    ].filter(x => x[2]);

    return `<div class="crce-panel" dir="${ar ? "rtl" : "ltr"}">
      ${sections.map(([en, ary, html]) => `
        <section class="crce-sec">
          <h4 class="crce-h">${A.esc(ar ? ary : en)}</h4>
          ${html}
        </section>`).join("")}
      ${notes ? `<section class="crce-sec">${notes}</section>` : ""}
    </div>`;
  }

  function relationsBlock(html) { return ["", "", html]; }

  A.crce = {
    panel, standard, symbol, svgString, attach, iconImage, iconDataUrl,
    registerMapIcons, iconExpression, eventIconImage, eventIconDataUrl: (size) => {
      const made = eventIconImage(size || 40);
      return made ? made.canvas.toDataURL("image/png") : null;
    },
    mapBackground: (cat) => MAP_BG[cat] || BG,
    kmText, COLOUR, BG, MAP_BG
  };
})(window.App);
