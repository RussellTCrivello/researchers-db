/* ============================================================================
   SIRAJ · lib/geopin.js — one pin language for every map surface
   ----------------------------------------------------------------------------
   The field-atlas bubble (black disc · coloured ring · tip · pill label) is the
   only marker vocabulary. Every view — geographic map, map desk, list maps,
   inspect pane, coordinate picker, legends and record lists — draws through
   this module so the symbol and the method never diverge again.

     element(opts)   → DOM pin for MapLibre HTML Markers
     marker(map, ll) → Marker already on the map
     chipHtml(opts)  → inline HTML for lists / legends (same disc + initial)
     chip(opts)      → DOM node of that chip
   ========================================================================== */
(function (A) {
  "use strict";

  const RING = {
    person: "#b8e000",
    institution: "#5ec8f0",
    place: "#7dcea0",
    event: "#d4a5e8",
    selection: "#c6ff00",
    temp: "#ff6b5a",
    default: "#b8e000"
  };

  function esc(s) {
    return A.esc ? A.esc(s) : String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function initialOf(label) {
    const s = String(label || "").trim();
    if (!s) return "·";
    const m = s.match(/[\p{L}\p{N}]/u);
    return m ? m[0] : s.charAt(0);
  }

  function ringFor(etype, opts) {
    if (opts && opts.selected) return RING.selection;
    if (opts && opts.temp) return RING.temp;
    return RING[etype] || RING.default;
  }

  function faceHtml(o, initial) {
    if (o.thumb) return `<img class="geo-pin-thumb" src="${esc(o.thumb)}" alt="">`;
    if (o.html) return `<span class="geo-pin-face-html">${o.html}</span>`;
    return `<span class="geo-pin-initial" dir="auto">${esc(initial)}</span>`;
  }

  /**
   * Full bubble pin (map marker).
   * @param {object} opts
   * @param {string} [opts.etype]
   * @param {string} [opts.label]
   * @param {string} [opts.initial]
   * @param {string} [opts.thumb]
   * @param {string} [opts.html]
   * @param {boolean} [opts.selected]
   * @param {boolean} [opts.temp]
   * @param {boolean} [opts.showLabel]
   * @param {string}  [opts.size]  "sm" | "md" | "lg"
   * @param {string}  [opts.tag]   element tag, default "div" (use "button" for desk)
   */
  function element(opts) {
    const o = opts || {};
    const size = o.size || (o.selected ? "lg" : "md");
    const ring = ringFor(o.etype, o);
    const label = o.label || "";
    const initial = o.initial || initialOf(label);
    const tag = o.tag || "div";
    const el = document.createElement(tag);
    if (tag === "button") el.type = "button";
    el.className = `geo-pin geo-pin-${size}` +
      (o.selected ? " is-selected" : "") +
      (o.temp ? " is-temp" : "") +
      (o.etype ? ` geo-pin-${o.etype}` : "");
    el.style.setProperty("--pin-ring", ring);
    el.innerHTML =
      `<div class="geo-pin-bubble" aria-hidden="true">` +
        `<div class="geo-pin-disc">${faceHtml(o, initial)}</div>` +
        `<div class="geo-pin-tip"></div>` +
      `</div>` +
      (o.showLabel !== false && label
        ? `<div class="geo-pin-label" dir="auto">${esc(label)}</div>`
        : "");
    if (label) el.title = label;
    return el;
  }

  /**
   * Compact disc for lists and legends — same ring + initial, no tip/pill.
   * Returns an HTML string safe for template insertion.
   */
  function chipHtml(opts) {
    const o = opts || {};
    const ring = ringFor(o.etype, o);
    const label = o.label || "";
    const initial = o.initial || initialOf(label);
    const size = o.size || "sm";
    return `<span class="geo-pin-chip geo-pin-chip-${size}` +
      (o.etype ? ` geo-pin-${o.etype}` : "") +
      `" style="--pin-ring:${ring}" title="${esc(label)}" aria-hidden="true">` +
      `<span class="geo-pin-chip-disc">${faceHtml(o, initial)}</span></span>`;
  }

  function chip(opts) {
    const wrap = document.createElement("span");
    wrap.innerHTML = chipHtml(opts);
    return wrap.firstElementChild;
  }

  function marker(map, lngLat, opts) {
    if (!window.maplibregl || !map) return null;
    const o = opts || {};
    const el = element(o);
    const m = new window.maplibregl.Marker({
      element: el,
      anchor: "bottom",
      offset: [0, 0],
      draggable: !!o.draggable,
      pitchAlignment: "viewport",
      rotationAlignment: "viewport"
    }).setLngLat(lngLat).addTo(map);
    m._sirajPin = el;
    return m;
  }

  /** Boot style for secondary maps (list / inspect / forms): the user's default
   *  map view.  A raster choice (standard / aerial / terrain) boots that
   *  provider's own style; an offline choice boots the quiet graphical
   *  background, over which the caller paints the street pack. */
  function secondaryStyle(providerId, configDoc) {
    const id = providerId || "local";
    const catalog = (configDoc && configDoc.providers) || [];
    const entry = catalog.find(p => p.id === id);
    const graphical = catalog.find(p => p.id === "local");
    const boot = (entry && !String(entry.kind || "").startsWith("vector"))
      ? entry : (graphical || null);
    if (boot && boot.style) {
      if (A.tilecache && A.tilecache.wrapStyle) {
        A.tilecache.installProtocol();
        return A.tilecache.wrapStyle(boot);
      }
      return boot.style;
    }
    const raw = {
      id: "osm",
      kind: "raster",
      style: {
        version: 8,
        name: "SIRAJ secondary",
        sources: {
          base: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            maxzoom: 19,
            attribution: "© OpenStreetMap contributors"
          }
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#e8eef4" } },
          { id: "base", type: "raster", source: "base" }
        ]
      }
    };
    if (A.tilecache && A.tilecache.wrapStyle) {
      A.tilecache.installProtocol();
      return A.tilecache.wrapStyle(raw);
    }
    return raw.style;
  }

  A.geopin = {
    element, marker, chipHtml, chip, initialOf, RING, secondaryStyle
  };
})(window.App || (window.App = {}));
