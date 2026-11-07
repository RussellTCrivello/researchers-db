/* ============================================================================
   SIRAJ · views/desk.js — the map desk
   ----------------------------------------------------------------------------
   The registry read as a place, and worked in the same way a table is worked in:
   a list on one side, the map in the middle, the record's neighbourhood on the
   other side, and a toolbar that does the same things a list toolbar does —
   filter, search, select, edit, add, undo.

   Why a desk and not "a map page": a map that answers only "where" sends you
   back to the list to answer "which", and back again to answer "who with". Here
   the three questions are answered at once, in place, without navigating:

     rail  ·  index of what is on the map, or the selected record in full
     map   ·  the reserved CRCE marks, the clusters, the pop-up card
     net   ·  the selected record's own neighbourhood and a globe-level overview

   Everything it shows comes from the registry: `/api/map/features` for what is
   in the window, `/api/map/feature/{type}/{id}` for the position dossier,
   `/api/graph/node/{type}/{id}` for identity, facts, counts and neighbours.
   Nothing is invented, and no count is estimated from pixels.
   ========================================================================== */
(function (A) {
  "use strict";
  const { t, api, esc, fmtNum, toast } = A;
  const D = {
    conf: null, map: null, ready: false,
    points: [], byId: new Map(), truncated: false, perLayer: {},
    sel: null, detail: null, node: null, tab: "overview",
    history: [], at: -1, hover: null,
    labels: true, grid: false, netOpen: true,
    mini: null, miniPts: [], markers: [], popup: null,
    raf: 0, loading: false,
    pickForRel: null,
    maplib: null, /* shared geographic runtime — see lib/maplib.js */
    /* field filters, on top of the layer chips. The same object feeds the rail
       and `/api/map/features`, so the list and the marks cannot disagree. */
    filters: {
      query: "", logic: "and", where: [], auth: "", doc: "",
      relType: "", tagIds: [], warnings: []
    },
    filterEl: null,
  };
  let pointsToken = 0;
  const PREFS = "siraj.desk.v1";
  const CAT = { person: "person", institution: "institution", place: "place", event: "event", source: "source" };
  const PILL_ZOOM = 11.2;

  const lang = () => A.state.lang;
  const L = (en, ar) => (lang() === "ar" ? ar : en);
  const label = (row, en, ar) => (lang() === "ar" ? (row[ar] || row[en]) : (row[en] || row[ar])) || "";

  function prefs() {
    try { return JSON.parse(localStorage.getItem(PREFS) || "{}") || {}; } catch (e) { return {}; }
  }
  function savePrefs(patch) {
    try {
      const next = Object.assign(prefs(), patch);
      localStorage.setItem(PREFS, JSON.stringify(next));
    } catch (e) { /* private mode: the view simply forgets */ }
  }

  /* ------------------------------------------------------------- numbers --- */
  function dd(v, axis) {
    const n = Number(v);
    if (!isFinite(n)) return "—";
    const hemi = axis === "lat" ? (n >= 0 ? "N" : "S") : (n >= 0 ? "E" : "W");
    return `${Math.abs(n).toFixed(5)}° ${hemi}`;
  }
  function dms(v, axis) {
    const n = Math.abs(Number(v));
    if (!isFinite(n)) return "—";
    const d = Math.floor(n), m = Math.floor((n - d) * 60), s = ((n - d) * 60 - m) * 60;
    const hemi = axis === "lat" ? (Number(v) >= 0 ? "N" : "S") : (Number(v) >= 0 ? "E" : "W");
    return `${d}° ${String(m).padStart(2, "0")}′ ${s.toFixed(1)}″ ${hemi}`;
  }
  const typeLabel = (etype) => {
    const e = ((A.state.meta || {}).entities || []).find(x => x.key === etype);
    return e ? (lang() === "ar" ? e.plural_ar : e.plural_en) : etype;
  };
  const typeOne = (etype) => {
    const e = ((A.state.meta || {}).entities || []).find(x => x.key === etype);
    return e ? (lang() === "ar" ? e.label_ar : e.label_en) : etype;
  };
  const markOf = (etype) => ({
    person: "person", institution: "organization", place: "place", relationship: "relationship",
  }[etype] || null);

  /* ══════════════════════════════════════════════════════════════ loading ══ */
  async function loadPoints() {
    if (!D.map) return;
    const b = D.map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
      .map(n => n.toFixed(4)).join(",");
    const zoom = D.map.getZoom().toFixed(2);
    const layers = [...D.layers].join(",");
    const filters = A.mapFilters
      ? encodeURIComponent(JSON.stringify(A.mapFilters.toPayload(D.filters)))
      : "";
    const token = ++pointsToken;
    D.loading = true;
    try {
      const res = await api.get(`/api/map/features?bbox=${bbox}&zoom=${zoom}`
        + `&layers=${encodeURIComponent(layers)}&limit=900`
        + (filters ? `&filters=${filters}` : ""));
      if (token !== pointsToken) return;
      D.points = res.points || [];
      D.perLayer = res.per_layer || {};
      D.truncated = !!res.truncated;
      D.filters.warnings = res.warnings || [];
      D.byId = new Map(D.points.map(p => [`${p.entity_type}:${p.id}`, p]));
      drawMarkers();
      /* a refresh of the window must not throw away what the reader is reading */
      if (D.sel && D.node) renderRail(); else indexRail();
      if (D.grid) drawGrid();
      if (D.maplib) D.maplib.refreshHud();
    } catch (err) {
      toast(err.message || String(err), "err");
    } finally {
      D.loading = false;
      mapChips();
    }
  }

  async function loadOverview() {
    /* the overview map needs a whole-country picture, not the current window, so
       it asks once for a wide box and keeps it; it is decoration for orientation,
       never the source of a count */
    try {
      const res = await api.get("/api/map/features?bbox=-180,-60,180,80&zoom=1.5&limit=700");
      D.miniPts = (res.points || []).slice(0, 700);
      drawMini();
    } catch (e) { /* an empty overview is better than a broken desk */ }
  }

  /* ══════════════════════════════════════════════════════════════ the map ══ */
  async function bootMap(host) {
    if (!window.maplibregl) {
      host.innerHTML = `<div class="desk-fatal">${esc(t("geo.libraryMissing"))}</div>`;
      return;
    }
    if (A.crce && A.crce.standard) { try { await A.crce.standard(); } catch (e) { /* plain dots */ } }
    const conf = D.conf;
    const provider = conf.providers.find(p => p.id === conf.provider.id) || conf.providers[0];
    const pre = prefs();
    const start = {
      lon: Number(pre.lon || conf.initial.lon), lat: Number(pre.lat || conf.initial.lat),
      zoom: Number(pre.zoom || conf.initial.zoom),
    };
    const map = new window.maplibregl.Map({
      container: host, style: provider.style,
      center: [start.lon, start.lat], zoom: start.zoom,
      maxZoom: 19, minZoom: 1, attributionControl: false, dragRotate: true, keyboard: true,
    });
    D.map = map;
    window.__deskMap = map;
    D.provider = provider;
    map.addControl(new window.maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-left");
    map.addControl(new window.maplibregl.NavigationControl({ showCompass: true, visualizePitch: false }),
                   "top-right");

    map.on("load", () => {
      D.ready = true;
      baseKey = "";
      ensureBasemap();
      if (D.maplib) D.maplib.syncStreets();
      loadPoints();
      mapChips();
    });
    let timer = 0;
    map.on("moveend", () => {
      ensureBasemap();
      drawMini();
      mapChips();
      clearTimeout(timer);
      timer = setTimeout(loadPoints, 220);
    });
    map.on("zoom", () => { mapChips(); });
    map.on("move", () => { positionPopup(); });
    map.on("click", (ev) => {
      if (D.maplib && D.maplib.handleClick(ev)) return;
      closePopup();
    });
    map.on("mousemove", (ev) => {
      if (D.maplib && D.maplib.isBusy()) {
        map.getCanvas().style.cursor = "crosshair";
        return;
      }
      const el = ev.originalEvent && ev.originalEvent.target;
      if (el && el.closest && el.closest("[data-desk-mark]")) map.getCanvas().style.cursor = "pointer";
      else map.getCanvas().style.cursor = "";
    });
  }


  /** Attach the shared maplib runtime once the MapLibre map exists. */
  function attachMapLib(mapHost) {
    if (!A.maplib || !D.map || !mapHost) return;
    if (D.maplib) { try { D.maplib.destroy(); } catch (e) { /* */ } }
    D.maplib = A.maplib({
      map: D.map,
      host: mapHost,
      conf: D.conf,
      prefs: prefs(),
      onPrefs: (patch) => savePrefs(patch),
      getPointCount: () => D.points.length,
      onFitPoints: () => document.querySelector("[data-desk-fit]")?.click(),
      onPointsRefresh: () => loadPoints(),
      pickingRoot: document.querySelector("[data-desk]"),
      composerHost: () => {
        if (!D.node) {
          const rail = document.querySelector("[data-desk-rail]");
          if (rail && !rail.querySelector("[data-desk-composer]")) indexRail();
        }
        return ensureComposerSlot();
      },
      onPlaceSaved: async (rec) => {
        loadPoints();
        if (rec && rec.type && rec.id) await select(rec.type, rec.id, { fly: true, force: true });
      },
      onPinsVisibility: (visible) => {
        document.querySelectorAll("[data-desk-mark]").forEach(el => {
          el.style.display = visible ? "" : "none";
        });
      },
      onStyleChange: ({ provider, after }) => {
        if (!provider) { if (after) after(); return; }
        D.provider = provider;
        baseKey = "";
        D.map.setStyle(provider.style);
        D.map.once("styledata", () => {
          ensureBasemap();
          if (after) after();
          drawMarkers();
        });
        D.map.once("idle", () => { ensureBasemap(); drawMarkers(); });
      }
    });
  }

  /* ------------------------------------------------------------- basemap --- */
  /* The local provider carries no tiles — that is the point of it, and the reason
     the registry works with no network. Its geometry (countries, coastlines, lakes,
     rivers, cities) is served from `app/geo/basemap.sqlite` for the current window,
     drawn underneath everything the registry says. Two decimals of a degree is
     about a kilometre at the equator: enough for a window, and it stops a one-pixel
     pan from refetching five layers. */
  const BASE_STYLE = {
    countries: [
      { id: "dk-base-countries", type: "fill", source: "dk-base-countries",
        paint: { "fill-color": "#f7f6f2", "fill-opacity": 1 } },
      { id: "dk-base-countries-line", type: "line", source: "dk-base-countries",
        paint: { "line-color": "#cfd3cf", "line-width": 0.8 } },
    ],
    lakes: [{ id: "dk-base-lakes", type: "fill", source: "dk-base-lakes",
              paint: { "fill-color": "#cfe1ee" } }],
    coastline: [{ id: "dk-base-coastline", type: "line", source: "dk-base-coastline",
                  paint: { "line-color": "#a9b6c0", "line-width": 1 } }],
    rivers: [{ id: "dk-base-rivers", type: "line", source: "dk-base-rivers",
               paint: { "line-color": "#c2d9ea", "line-width": 0.9 } }],
    places: [{ id: "dk-base-places", type: "circle", source: "dk-base-places",
               paint: { "circle-radius": ["interpolate", ["linear"], ["get", "population"],
                         0, 1.6, 200000, 2.6, 5000000, 3.8],
                        "circle-color": "#6b7d8d", "circle-opacity": 0.8,
                        "circle-stroke-color": "#ffffff", "circle-stroke-width": 0.8 } }],
  };
  let baseKey = "";

  function isLocal() {
    const k = D.provider && D.provider.kind;
    return k === "vector-local" || k === "hybrid-streets";
  }

  async function ensureBasemap() {
    const map = D.map;
    if (!map || !D.ready || !map.isStyleLoaded || !map.isStyleLoaded()) return;
    if (!isLocal()) {
      for (const layer of Object.keys(BASE_STYLE)) {
        for (const l of BASE_STYLE[layer]) {
          if (map.getLayer(l.id)) map.removeLayer(l.id);
          if (map.getSource(l.source)) map.removeSource(l.source);
        }
      }
      baseKey = "";
      return;
    }
    const z = map.getZoom();
    const b = map.getBounds();
    const bbox = `${b.getWest().toFixed(2)},${b.getSouth().toFixed(2)},`
      + `${b.getEast().toFixed(2)},${b.getNorth().toFixed(2)}`;
    const key = `${z.toFixed(2)}|${bbox}`;
    if (key === baseKey) return;
    baseKey = key;
    for (const layer of Object.keys(BASE_STYLE)) {
      try {
        const res = await api.get(`/api/geo/basemap/${layer}?zoom=${z.toFixed(2)}`
          + `&bbox=${bbox}&limit=900`);
        const fc = res.collection;
        if (!fc || !D.map) continue;
        if (D.map.getSource("dk-base-" + layer)) {
          D.map.getSource("dk-base-" + layer).setData(fc);
        } else {
          D.map.addSource("dk-base-" + layer, { type: "geojson", data: fc });
          BASE_STYLE[layer].forEach(l => { if (!D.map.getLayer(l.id)) D.map.addLayer(l); });
        }
        /* keep the basemap under everything, whatever order it arrived in */
        const under = D.map.getLayer("dk-base-countries") ? "dk-base-countries" : undefined;
        void under;
      } catch (e) { /* a missing basemap layer is a blank area, never an error */ }
    }
  }

  /* --------------------------------------------------------------- chips --- */
  async function mapChips() {
    const box = document.querySelector("[data-desk-chipbar]");
    if (!box || !D.map) return;
    const c = D.map.getCenter();
    const z = D.map.getZoom();
    const shown = D.points.length;
    const total = Object.values(D.perLayer).reduce((s, v) => s + (v.total || 0), 0);
    box.innerHTML = `
      <span class="desk-chip is-mono" data-chip-coords title="${esc(t("desk.copyCoords"))}">
        ${c.lat.toFixed(5)}, ${c.lng.toFixed(5)}</span>
      <span class="desk-chip" title="${esc(t("desk.zoomLevel"))}">z ${z.toFixed(2)}</span>
      <span class="desk-chip" data-chip-count title="${esc(t("desk.inWindow"))}">
        ${fmtNum(shown)}${D.truncated || total > shown ? ` / ${fmtNum(total)}` : ""} ${esc(t("desk.points"))}</span>
      <span class="desk-chip is-region" data-chip-region>${
        D.region ? esc(D.region) : esc(t("desk.locating"))}</span>
      ${D.truncated ? `<span class="desk-chip is-warn">${esc(t("desk.tooMany"))}</span>` : ""}
      <button class="desk-chip is-action" data-chip-copy>⧉ ${esc(t("desk.copyCoords"))}</button>`;
    box.querySelector("[data-chip-copy]").onclick = () => {
      const text = `${c.lat.toFixed(6)}, ${c.lng.toFixed(6)}`;
      if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {});
      toast(`${text} — ${t("desk.copied")}`, "ok");
    };
    if (!D.region || D.regionAt < Date.now() - 60000) {
      D.regionAt = Date.now();
      try {
        const r = await api.get(`/api/map/reverse?lat=${c.lat.toFixed(5)}&lon=${c.lng.toFixed(5)}`);
        D.region = label(r || {}, "name_en", "name_ar") || label(r || {}, "country_en", "country_ar")
          || L("open water", "مياه مفتوحة");
      } catch (e) { D.region = "—"; }
      const chip = document.querySelector("[data-chip-region]");
      if (chip) chip.textContent = D.region;
    }
  }

  /* -------------------------------------------------------------- markers ---
     Same bubble-pin vocabulary as the geographic map (A.geopin). */
  function markerEl(kind, data) {
    const name = label(data, "label_en", "label_ar") || data.code || "";
    const selected = !!(D.sel && D.sel.type === data.entity_type && D.sel.id === data.id);
    const el = (A.geopin && A.geopin.element)
      ? A.geopin.element({
          tag: "button",
          etype: data.entity_type,
          label: name,
          size: kind === "speck" ? "sm" : "md",
          selected,
          showLabel: false
        })
      : (() => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "geo-pin geo-pin-md";
          b.textContent = name.slice(0, 1);
          return b;
        })();
    el.classList.add("desk-mark", `is-${kind}`);
    el.setAttribute("data-desk-mark", `${data.entity_type}:${data.id}`);
    el.setAttribute("aria-label", `${name} — ${typeOne(data.entity_type)}`);
    /* pill slot kept for desk's zoom-dependent name reveal */
    if (!el.querySelector(".geo-pin-label") && !el.querySelector(".dm-pill")) {
      const pill = document.createElement("div");
      pill.className = "geo-pin-label dm-pill";
      pill.hidden = true;
      el.appendChild(pill);
    } else {
      const pill = el.querySelector(".geo-pin-label");
      if (pill) { pill.classList.add("dm-pill"); pill.hidden = true; }
    }
    return el;
  }

  function clusterEl(cell) {
    const el = (A.geopin && A.geopin.element)
      ? A.geopin.element({
          tag: "button",
          etype: "place",
          label: "",
          initial: String(cell.count > 99 ? "99+" : cell.count),
          size: "md",
          showLabel: false
        })
      : document.createElement("button");
    el.type = "button";
    el.classList.add("desk-mark", "is-cluster");
    el.setAttribute("data-desk-cluster", "1");
    const face = el.querySelector(".geo-pin-initial");
    if (face) {
      face.classList.add("dm-count");
      face.textContent = fmtNum(cell.count);
    }
    return el;
  }

  function drawMarkers() {
    if (!D.map) return;
    for (const m of D.markers) m.remove();
    D.markers = [];
    if (!D.points.length) return;
    const iconZoom = D.map.getZoom() >= 9.5;

    /* Clustering is done in screen space, at the pixel size a mark is drawn at:
       two records that land under the same finger are the same mark, and saying
       so is better than stacking them invisibly. */
    const cell = D.map.getZoom() >= PILL_ZOOM ? 26 : 46;
    const seen = new Map();
    for (const p of D.points) {
      const pt = D.map.project([p.lon, p.lat]);
      const key = `${Math.round(pt.x / cell)}:${Math.round(pt.y / cell)}`;
      const hit = seen.get(key);
      if (hit) {
        hit.count++;
        hit.items.push(p);
        hit.lon += p.lon; hit.lat += p.lat;
      } else {
        seen.set(key, { x: pt.x, y: pt.y, count: 1, items: [p], lon: p.lon, lat: p.lat });
      }
    }

    /* A group's anchor is the mean of its members, and two means can land on top
       of each other. Groups are separated in screen space and then unprojected —
       a group is an aggregate, so nudging its disc tells no lie, while a single
       record is never moved from its coordinate. */
    const clusters = [...seen.values()].filter(c => c.count > 1);
    for (const c of clusters) {
      const p = D.map.project([c.lon / c.count, c.lat / c.count]);
      c.px = p.x; c.py = p.y;
    }
    for (let pass = 0; pass < 6; pass++) {
      let moved = false;
      for (let i = 0; i < clusters.length; i++) {
        for (let j = i + 1; j < clusters.length; j++) {
          const a = clusters[i], bb = clusters[j];
          const dx = bb.px - a.px, dy = bb.py - a.py;
          const dist = Math.hypot(dx, dy) || 0.01;
          const want = cell * 0.95;
          if (dist >= want) continue;
          const push = (want - dist) / 2;
          const ux = dx / dist, uy = dy / dist;
          a.px -= ux * push; a.py -= uy * push;
          bb.px += ux * push; bb.py += uy * push;
          moved = true;
        }
      }
      if (!moved) break;
    }
    for (const c of clusters) {
      const ll = D.map.unproject([c.px, c.py]);
      c.lon = ll.lng * c.count;
      c.lat = ll.lat * c.count;
    }

    for (const c of seen.values()) {
      if (c.count > 1) {
        const el = clusterEl(c);
        el.querySelector(".dm-count").textContent = fmtNum(c.count);
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (D.map.getZoom() > 15.5) return;
          D.map.easeTo({ center: [c.lon / c.count, c.lat / c.count],
                         zoom: Math.min(D.map.getZoom() + 1.8, 17), duration: 520 });
        });
        const marker = new window.maplibregl.Marker({ element: el, anchor: "bottom" })
          .setLngLat([c.lon / c.count, c.lat / c.count]).addTo(D.map);
        D.markers.push(marker);
        continue;
      }
      const p = c.items[0];
      const el = markerEl(iconZoom ? "point" : "speck", p);
      if (D.sel && D.sel.type === p.entity_type && D.sel.id === p.id) {
        el.classList.add("is-selected");
        el.style.setProperty("--pin-ring", (A.geopin && A.geopin.RING.selection) || "#c6ff00");
      }
      const pill = el.querySelector(".dm-pill") || el.querySelector(".geo-pin-label");
      const name = label(p, "label_en", "label_ar") || p.code;
      if (pill) pill.textContent = name;
      const showPill = D.labels && D.map.getZoom() >= PILL_ZOOM;
      el.classList.toggle("with-pill", showPill);
      if (pill) pill.hidden = !showPill && !el.classList.contains("is-selected");
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        select(p.entity_type, p.id, { fly: false, fromMarker: true });
      });
      el.addEventListener("pointerenter", () => { D.hover = p; el.classList.add("is-hover"); });
      el.addEventListener("pointerleave", () => { D.hover = null; el.classList.remove("is-hover"); });
      const marker = new window.maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([p.lon, p.lat]).addTo(D.map);
      D.markers.push(marker);
      if (el.classList.contains("is-selected")) {
        el.classList.add("with-pill");
        if (pill) pill.hidden = false;
        D.selectedMarker = marker;
      }
    }
  }

  function refreshSelectionMarks() {
    for (const m of D.markers) {
      const el = m.getElement();
      const key = el.getAttribute("data-desk-mark");
      if (!key) continue;
      const on = D.sel && key === `${D.sel.type}:${D.sel.id}`;
      el.classList.toggle("is-selected", !!on);
      const etype = key.split(":")[0];
      el.style.setProperty("--pin-ring",
        on ? ((A.geopin && A.geopin.RING.selection) || "#c6ff00")
           : ((A.geopin && A.geopin.RING[etype]) || "#b8e000"));
      if (on) {
        el.classList.add("with-pill");
        const pill = el.querySelector(".dm-pill") || el.querySelector(".geo-pin-label");
        if (pill) pill.hidden = false;
      }
    }
  }

  /* ══════════════════════════════════════════════════════════ the record ══ */
  async function select(type, id, opts) {
    const o = opts || {};
    if (!type || id == null) return closeSelection();
    /* Pick mode fills the open composer; the dossier under it stays put. */
    if (typeof D.pickForRel === "function" && !o.force) {
      const pt = D.byId.get(`${type}:${id}`);
      const title = pt
        ? (label(pt, "label_en", "label_ar") || pt.code)
        : (D.node && D.node.type === type && D.node.record_id === id
          ? (D.node.title || D.node.code) : "");
      D.pickForRel({ type, id: Number(id), title: title || `${type}:${id}` });
      D.pickForRel = null;
      setPickCue(false);
      toast(t("atlas.pickFilled"), "ok", 2200);
      return;
    }
    const key = `${type}:${id}`;
    if (D.sel && `${D.sel.type}:${D.sel.id}` === key && !o.force) return;
    D.sel = { type, id };
    if (o.push !== false) pushHistory({ type, id });
    refreshSelectionMarks();
    renderRailLoading();
    try {
      const [detail, node] = await Promise.all([
        api.get(`/api/map/feature/${type}/${id}`).catch(() => null),
        api.get(`/api/graph/node/${type}/${id}`).catch(() => null),
      ]);
      D.detail = detail;
      D.node = node;
      renderRail();
      renderNetwork();
      openPopup();
      if (o.fly !== false && D.detail && D.detail.position) {
        D.map.easeTo({ center: [D.detail.position.lon, D.detail.position.lat],
                       zoom: Math.max(D.map.getZoom(), 11), duration: A.viz && A.viz.reduced() ? 0 : 620 });
      }
      highlightNeighbourhood();
    } catch (err) {
      toast(err.message || String(err), "err");
      renderRailError(err);
    }
  }

  function closeSelection() {
    D.sel = null; D.detail = null; D.node = null;
    D.pickForRel = null;
    setPickCue(false);
    closePopup();
    refreshSelectionMarks();
    indexRail();
    renderNetwork();
    highlightNeighbourhood();
  }

  function setPickCue(on) {
    document.querySelector("[data-desk]")?.classList.toggle("is-picking-rel", !!on);
  }

  /** Shared host for workspace composers: selected dossier rail, else the index. */
  function ensureComposerSlot() {
    const rail = document.querySelector("[data-desk-rail]");
    if (!rail) return null;
    let slot = rail.querySelector("[data-desk-composer]");
    if (slot) return slot;
    slot = document.createElement("div");
    slot.className = "desk-composer";
    slot.dataset.deskComposer = "1";
    const tabs = rail.querySelector(".desk-tabs");
    const layers = rail.querySelector(".desk-layers");
    if (tabs) rail.insertBefore(slot, tabs);
    else if (layers) rail.insertBefore(slot, layers.nextSibling);
    else rail.prepend(slot);
    return slot;
  }

  function pushHistory(entry) {
    D.history = D.history.slice(0, D.at + 1);
    const last = D.history[D.history.length - 1];
    if (last && last.type === entry.type && last.id === entry.id) return;
    D.history.push(entry);
    if (D.history.length > 40) D.history.shift();
    D.at = D.history.length - 1;
    paintHistory();
  }

  function paintHistory() {
    const back = document.querySelector("[data-desk-back]");
    const fwd = document.querySelector("[data-desk-forward]");
    if (back) back.disabled = D.at <= 0;
    if (fwd) fwd.disabled = D.at >= D.history.length - 1;
  }

  function stepHistory(delta) {
    const next = D.at + delta;
    if (next < 0 || next >= D.history.length) return;
    D.at = next;
    const e = D.history[D.at];
    paintHistory();
    select(e.type, e.id, { push: false, fly: true });
  }

  function highlightNeighbourhood() {
    const ids = new Set();
    if (D.node && D.node.neighbours) {
      for (const n of D.node.neighbours) ids.add(`${n.type}:${n.record_id}`);
    }
    for (const m of D.markers) {
      const el = m.getElement();
      const key = el.getAttribute("data-desk-mark");
      if (!key) continue;
      el.classList.toggle("is-near", ids.has(key));
    }
    const host = document.querySelector("[data-desk-map]");
    if (host) host.classList.toggle("has-selection", !!D.sel);
  }

  /* --------------------------------------------------------------- rail --- */
  /** The advanced-filter dock survives a rail redraw, so a map move cannot
   *  throw away the query the reader is typing. */
  function placeFilters(rail) {
    const slot = rail && rail.querySelector("[data-map-filters-slot]");
    if (!slot || !A.mapFilters) return;
    if (!D.filterEl) {
      D.filterEl = document.createElement("div");
      D.filterEl._mf = A.mapFilters.mount(D.filterEl, {
        state: D.filters,
        onApply: () => loadPoints()
      });
    }
    slot.replaceWith(D.filterEl);
    if (D.filterEl._mf) D.filterEl._mf.setWarnings(D.filters.warnings || []);
  }

  function filterBadge() {
    const n = A.mapFilters ? A.mapFilters.activeCount(D.filters) : 0;
    if (!n) return "";
    return `<button type="button" class="desk-chip is-on" data-desk-show-filters title="${esc(t("mf.title"))}">${esc(t("mf.active"))} ${fmtNum(n)}</button>`;
  }

  function renderRailLoading() {
    const rail = document.querySelector("[data-desk-rail]");
    if (!rail) return;
    rail.innerHTML = `<div class="desk-rail-pad"><div class="skeleton" style="width:60%"></div>
      <div class="skeleton" style="width:90%;margin-top:10px"></div>
      <div class="skeleton" style="width:75%;margin-top:10px"></div></div>`;
  }

  function renderRailError(err) {
    const rail = document.querySelector("[data-desk-rail]");
    if (!rail) return;
    rail.innerHTML = `<div class="desk-rail-pad"><div class="notice err">${esc(err.message || String(err))}</div>
      <button class="btn sm" data-desk-close>${esc(t("desk.close"))}</button></div>`;
    rail.querySelector("[data-desk-close]").onclick = closeSelection;
  }

  function indexRail() {
    const rail = document.querySelector("[data-desk-rail]");
    if (!rail) return;
    if (D.filterEl && D.filterEl.parentNode) D.filterEl.remove();
    const rows = D.points.slice(0, 120);
    const chips = Object.entries(D.perLayer).map(([k, v]) =>
      `<button class="desk-chip ${D.layers.has(k) ? "is-on" : ""}" data-layer="${esc(k)}"
        title="${esc(t("desk.filterLayer"))}">${esc(typeOne(k))}
        <b>${fmtNum(v.total || 0)}</b></button>`).join("");
    rail.innerHTML = `
      <div class="desk-rail-head">
        <div>
          <div class="desk-kicker">${esc(t("desk.onTheMap"))}</div>
          <h2 class="desk-title">${esc(t("desk.index"))}</h2>
        </div>
        <span class="desk-head-side">${filterBadge()}<span class="desk-count">${fmtNum(D.points.length)}</span></span>
      </div>
      <div class="desk-layers">${chips || `<span class="muted small">${esc(t("desk.noPoints"))}</span>`}</div>
      <div data-map-filters-slot></div>
      <div class="desk-composer" data-desk-composer hidden></div>
      ${D.truncated ? `<div class="notice small">${esc(t("desk.tooMany"))}</div>` : ""}
      <div class="desk-list" role="list">
        ${rows.map(p => `
          <button class="desk-row" role="listitem" data-pick="${esc(p.entity_type)}:${p.id}">
            <span class="dr-mark">${markImg(p.entity_type)}</span>
            <span class="dr-main">
              <span class="dr-name">${esc(label(p, "label_en", "label_ar") || p.code)}</span>
              <span class="dr-meta">${esc(typeOne(p.entity_type))} · ${esc(p.code || "")}
                ${p.anchor_en ? ` · ${esc(label(p, "anchor_en", "anchor_ar"))}` : ""}</span>
            </span>
            <span class="dr-coord mono-cell">${Number(p.lat).toFixed(3)}, ${Number(p.lon).toFixed(3)}</span>
          </button>`).join("") || `<div class="desk-empty">${esc(t("desk.noPoints"))}</div>`}
      </div>
      <div class="desk-rail-foot muted small">${esc(t("desk.indexFoot"))}</div>`;
    placeFilters(rail);
    const showFilters = rail.querySelector("[data-desk-show-filters]");
    if (showFilters) showFilters.onclick = () => {
      const box = rail.querySelector("[data-mf-query]");
      if (box) box.focus();
    };
    rail.querySelectorAll("[data-layer]").forEach(b => {
      b.onclick = () => {
        const k = b.getAttribute("data-layer");
        if (D.layers.has(k)) D.layers.delete(k); else D.layers.add(k);
        if (!D.layers.size) D.layers.add("place");
        b.classList.toggle("is-on");
        drawLegend();
        loadPoints();
      };
    });
    rail.querySelectorAll("[data-pick]").forEach(b => {
      b.onclick = () => {
        const [ty, id] = b.getAttribute("data-pick").split(":");
        select(ty, Number(id), { fly: true });
      };
    });
  }

  function markImg(etype) {
    const cat = markOf(etype);
    const url = cat && A.crce && A.crce.iconDataUrl ? A.crce.iconDataUrl(cat, 22) : null;
    return url ? `<img src="${url}" alt="" draggable="false">` : `<span class="dm-dot"></span>`;
  }

  function renderRail() {
    const rail = document.querySelector("[data-desk-rail]");
    if (!rail || !D.node) return;
    if (D.filterEl && D.filterEl.parentNode) D.filterEl.remove();
    const n = D.node;
    const d = D.detail || {};
    const pos = d.position || null;
    const counts = n.counts || {};
    const state = n.state || {};
    const chips = ["record_status", "authentication", "documentation"]
      .map(k => state[k]).filter(Boolean)
      .map(s => `<span class="desk-state is-${esc(s.color || "slate")}" title="${esc(label(s, "en", "ar"))}">
        ${esc(label(s, "en", "ar"))}</span>`).join("");
    const tabs = [
      ["overview", t("desk.overview"), null],
      ["relations", t("desk.relations"), (n.neighbours || []).length],
      ["place", t("desk.place"), pos ? 1 : 0],
      ["data", t("desk.data"), (n.facts || []).length],
    ];
    rail.innerHTML = `
      <div class="desk-rail-head">
        <div class="desk-id">
          <span class="desk-id-mark">${markImg(n.type)}</span>
          <div>
            <div class="desk-kicker">${esc(typeOne(n.type))} · ${esc(n.code || "")}</div>
            <h2 class="desk-title" data-desk-title>${esc(n.title || n.code)}</h2>
          </div>
        </div>
        <button class="icon-btn" data-desk-close title="${esc(t("desk.close"))}"
                aria-label="${esc(t("desk.close"))}">✕</button>
      </div>
      ${filterBadge() ? `<div class="desk-layers">${filterBadge()}</div>` : ""}
      <div class="desk-state-row">${chips}
        <span class="desk-complete" title="${esc(t("desk.completeness"))}">
          <i style="width:${Math.round(n.completeness || 0)}%"></i></span>
        <span class="desk-complete-n">${Math.round(n.completeness || 0)}%</span>
      </div>
      <div class="desk-stats">
        <div class="desk-stat"><b>${fmtNum(((counts.by_type || {}).person) || 0)}</b>
          <span>${esc(typeOne("person"))}</span></div>
        <div class="desk-stat"><b>${fmtNum(((counts.by_type || {}).institution) || 0)}</b>
          <span>${esc(typeOne("institution"))}</span></div>
        <div class="desk-stat"><b>${fmtNum(((counts.by_type || {}).place) || 0)}</b>
          <span>${esc(typeOne("place"))}</span></div>
        <div class="desk-stat"><b>${fmtNum(counts.relationships || 0)}</b>
          <span>${esc(t("desk.connections"))}</span></div>
      </div>
      <div class="desk-acts">
        <a class="btn sm primary" href="#/entity/${esc(n.type)}/${n.record_id}/edit"
           data-desk-edit>${esc(t("desk.edit"))}</a>
        <button type="button" class="btn sm" data-desk-rel>+ ${esc(t("desk.addRelation"))}</button>
        <button class="btn sm" data-desk-here ${pos ? "" : "disabled"}>${esc(t("desk.onMap"))}</button>
        <button class="btn sm danger" data-desk-delete>${esc(t("desk.delete"))}</button>
      </div>
      <div class="desk-composer" data-desk-composer hidden></div>
      ${pos ? `<div class="desk-loc">
        <div class="desk-loc-head">
          <span class="desk-kicker">${esc(t("desk.location"))}</span>
          <span class="desk-anchor">${esc(label(pos, "anchor_en", "anchor_ar") || t("desk.ownPosition"))}</span>
        </div>
        <div class="desk-loc-name">${esc(pos.label_en || pos.label_ar || "")}</div>
        <div class="desk-loc-coords mono-cell">
          <span>${dd(pos.lat, "lat")}</span><span>${dd(pos.lon, "lon")}</span></div>
        <div class="desk-loc-dms muted small">
          <span>${dms(pos.lat, "lat")}</span><span>${dms(pos.lon, "lon")}</span></div>
        <button class="btn sm" data-desk-net-go>${esc(t("desk.showInNetwork"))}</button>
      </div>` : `<div class="notice small">${esc(L(
        (d.reason && d.reason.message_en) || "This record has no coordinates.",
        (d.reason && d.reason.message_ar) || "هذا السجل بلا إحداثيات."))}</div>`}
      <div class="desk-tabs" role="tablist">
        ${tabs.map(([k, text, count]) => `<button class="desk-tab${D.tab === k ? " active" : ""}"
           role="tab" aria-selected="${D.tab === k}" data-tab="${k}">${esc(text)}${
           count != null ? ` <b>${fmtNum(count)}</b>` : ""}</button>`).join("")}
      </div>
      <div class="desk-tab-body" data-tab-body>${tabBody()}</div>
      <div class="desk-rail-foot muted small">${esc(t("desk.railFoot"))}</div>`;
    wireRail();
  }

  function tabBody() {
    const n = D.node, d = D.detail || {};
    if (!n) return "";
    if (D.tab === "relations") {
      const list = (n.neighbours || []);
      if (!list.length) return `<div class="desk-empty">${esc(t("desk.noRelations"))}</div>`;
      const groups = new Map();
      for (const r of list) {
        const k = r.type;
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(r);
      }
      return [...groups.entries()].map(([k, rows]) => `
        <div class="desk-group">
          <div class="desk-group-head">${esc(typeLabel(k))} <b>${rows.length}</b></div>
          ${rows.map(r => `<button class="desk-rel" data-goto="${esc(r.type)}:${r.record_id}">
            <span class="drr-type">${esc(label(r, "rel_en", "rel_ar"))}</span>
            <span class="drr-name">${esc(r.label || "")}</span>
            <span class="drr-flag is-${esc(r.verification || "unverified")}"
                  title="${esc(label(r, "verification_en", "verification_ar"))}"></span>
            <span class="drr-dir">${r.symmetric ? "⇄" : (r.outgoing ? "→" : "←")}</span>
          </button>`).join("")}
        </div>`).join("");
    }
    if (D.tab === "place") {
      const pos = d.position;
      if (!pos) return `<div class="desk-empty">${esc(t("desk.noPosition"))}</div>`;
      /* each CRS states its own axes in its own unit: 4326 is lat,lon in degrees,
         3857 is x,y in metres, and neither may be printed as the other */
      const crsText = (v) => {
        if (v == null) return "—";
        if (typeof v !== "object") return String(v);
        if (v.lat != null && v.lon != null) return `${Number(v.lat).toFixed(6)}, ${Number(v.lon).toFixed(6)}°`;
        if (v.x != null && v.y != null) return `${Number(v.x).toFixed(2)}, ${Number(v.y).toFixed(2)} m`;
        return Object.entries(v).filter(([k2]) => k2 !== "crs")
          .map(([k2, x]) => `${k2} ${x}`).join(" · ");
      };
      const crs = Object.entries(pos.crs || {}).map(([k, v]) =>
        `<div class="desk-kv"><span>${esc(k)}${v && v.unit ? ` <i class="muted">${esc(v.unit)}</i>` : ""}</span>
         <b class="mono-cell">${esc(crsText(v))}</b></div>`).join("");
      return `
        <div class="desk-kv-list">
          <div class="desk-kv"><span>${esc(t("desk.anchor"))}</span><b>${esc(label(pos, "anchor_en", "anchor_ar") || t("desk.ownPosition"))}</b></div>
          <div class="desk-kv"><span>${esc(t("desk.dd"))}</span><b class="mono-cell">${pos.lat.toFixed(6)}, ${pos.lon.toFixed(6)}</b></div>
          <div class="desk-kv"><span>${esc(t("desk.dms"))}</span>
            <b class="mono-cell dms-pair"><span>${dms(pos.lat, "lat")}</span><span>${dms(pos.lon, "lon")}</span></b></div>
          <div class="desk-kv"><span>${esc(t("desk.country"))}</span><b>${
            esc((lang() === "ar" ? (pos.country_ar || (pos.country_polygon || {}).name_ar)
                                 : (pos.country_en || (pos.country_polygon || {}).name_en)) || "—")}</b></div>
          ${crs}
        </div>
        <div class="notice small">${esc(t("desk.positionCaveat"))}</div>`;
    }
    if (D.tab === "data") {
      const facts = n.facts || [];
      if (!facts.length) return `<div class="desk-empty">${esc(t("desk.noFacts"))}</div>`;
      return `<div class="desk-kv-list">${facts.map(f => `
        <div class="desk-kv"><span>${esc(label(f, "label_en", "label_ar"))}</span>
        <b>${esc(f.value == null || f.value === "" ? "—" : String(f.value))}</b></div>`).join("")}</div>`;
    }
    /* overview */
    const facts = (n.facts || []).slice(0, 5);
    const ev = (n.counts && n.counts.evidence) || {};
    return `
      ${facts.length ? `<div class="desk-kv-list">${facts.map(f => `
        <div class="desk-kv"><span>${esc(label(f, "label_en", "label_ar"))}</span>
        <b>${esc(f.value == null || f.value === "" ? "—" : String(f.value))}</b></div>`).join("")}</div>` : ""}
      <div class="desk-evidence">
        <div class="desk-kicker">${esc(t("desk.evidence"))}</div>
        <div class="desk-evidence-row">
          <span>${esc(t("desk.sources"))} <b>${fmtNum(ev.sources || 0)}</b></span>
          <span>${esc(t("desk.supports"))} <b>${fmtNum(ev.supports || 0)}</b></span>
          <span>${esc(t("desk.contradicts"))} <b class="${ev.contradicts ? "warn" : ""}">${fmtNum(ev.contradicts || 0)}</b></span>
          ${ev.disputed ? `<span class="warn">⚑ ${esc(t("desk.disputed"))}</span>` : ""}
        </div>
      </div>
      <a class="btn sm" href="${esc(n.href || "#/entity/" + n.type + "/" + n.record_id)}">
        ${esc(t("desk.openRecord"))}</a>`;
  }

  function wireRail() {
    const rail = document.querySelector("[data-desk-rail]");
    if (!rail) return;
    rail.querySelector("[data-desk-close]").onclick = closeSelection;
    const showFilters = rail.querySelector("[data-desk-show-filters]");
    if (showFilters) showFilters.onclick = () => closeSelection();
    rail.querySelectorAll("[data-tab]").forEach(b => {
      b.onclick = () => { D.tab = b.getAttribute("data-tab"); renderRail(); };
    });
    rail.querySelectorAll("[data-goto]").forEach(b => {
      b.onclick = () => {
        const [ty, id] = b.getAttribute("data-goto").split(":");
        select(ty, Number(id), { fly: true });
      };
    });
    const here = rail.querySelector("[data-desk-here]");
    if (here) here.onclick = () => {
      const pos = D.detail && D.detail.position;
      if (pos) D.map.easeTo({ center: [pos.lon, pos.lat], zoom: Math.max(D.map.getZoom(), 13), duration: 520 });
    };
    const net = rail.querySelector("[data-desk-net-go]");
    if (net) net.onclick = () => {
      const pos = D.detail && D.detail.position;
      if (!pos) return;
      D.netOpen = true;
      document.querySelector("[data-desk]").classList.add("net-open");
      D.map.easeTo({ center: [pos.lon, pos.lat], zoom: 12.5, duration: 520 });
      openPopup();
    };
    const del = rail.querySelector("[data-desk-delete]");
    if (del) del.onclick = async () => {
      const n = D.node;
      const yes = await A.confirmDialog({
        title: t("desk.delete"),
        message: t("desk.deleteConfirm", { name: n.title || n.code }),
        confirmLabel: t("desk.delete"),
      });
      if (!yes) return;
      try {
        await api.del(`/api/${n.type}/${n.record_id}?reason=desk`);
        toast(t("desk.deleted"), "ok");
        closeSelection();
        loadPoints();
      } catch (err) { toast(err.message || String(err), "err"); }
    };
    const relBtn = rail.querySelector("[data-desk-rel]");
    if (relBtn) relBtn.onclick = () => openDeskRelationshipComposer();
  }

  /**
   * Workspace rule for the desk: create a relationship *in* the rail, over the
   * map that is already open. Never navigate to the record form, never raise
   * the global dialog surface over the desk.
   */
  function openDeskRelationshipComposer() {
    const n = D.node;
    if (!n) {
      toast(t("desk.pickFirst"), "warn", 2800);
      return;
    }
    const slot = ensureComposerSlot();
    if (!slot || !A.composeRelationship) return;
    D.pickForRel = null;
    setPickCue(false);
    A.composeRelationship({
      host: slot,
      source: { type: n.type, id: n.record_id, title: n.title || n.code || "" },
      onPickRequest: (setTarget) => {
        D.pickForRel = setTarget || null;
        setPickCue(!!setTarget);
        if (setTarget) toast(t("desk.pickOnMapHint"), "ok", 3200);
      },
      onCancel: () => {
        D.pickForRel = null;
        setPickCue(false);
      },
      onSaved: async () => {
        D.pickForRel = null;
        setPickCue(false);
        /* refresh the open dossier and its neighbourhood without leaving */
        if (D.sel) await select(D.sel.type, D.sel.id, { fly: false, force: true });
        loadPoints();
      }
    });
    slot.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /** Same rule for new entities: compose in the rail; stay on the desk. */
  function openDeskEntityComposer() {
    const slot = ensureComposerSlot();
    if (!slot || !A.composeEntity) return;
    A.composeEntity({
      host: slot,
      entity: (D.node && D.node.type !== "relationship") ? D.node.type : "person",
      onCancel: () => {},
      onSaved: async (rec) => {
        loadPoints();
        if (rec && rec.type && rec.id) await select(rec.type, rec.id, { fly: true, force: true });
      }
    });
    slot.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /* ══════════════════════════════════════════════════════════════ pop-up ══ */
  function openPopup() {
    closePopup();
    if (!D.node || !D.detail || !D.detail.position) return;
    const n = D.node, d = D.detail, pos = d.position;
    const el = document.createElement("div");
    el.className = "desk-pop";
    el.setAttribute("data-desk-pop", "1");
    const rels = (n.neighbours || []).slice(0, 3);
    const image = n.image
      ? `<img class="dp-img" src="${esc(n.image)}" alt="">`
      : `<div class="dp-img is-empty">${markImg(n.type)}</div>`;
    el.innerHTML = `
      <button class="dp-close" data-pop-close aria-label="${esc(t("desk.close"))}">✕</button>
      ${image}
      <div class="dp-body">
        <div class="dp-head">
          <span class="dp-type"><i class="dp-dot is-${esc(n.type)}"></i>${esc(typeOne(n.type))}</span>
          <span class="dp-code">${esc(n.code || "")}</span>
        </div>
        <h3 class="dp-title" data-pop-title>${esc(n.title || n.code)}</h3>
        <div class="dp-sub mono-cell">${esc(n.code || "")}</div>
        <div class="dp-tags">
          <span class="dp-tag">${esc(t("desk.anchor"))}: ${esc(label(pos, "anchor_en", "anchor_ar") || "—")}</span>
          <span class="dp-tag dp-coords">${esc(dd(pos.lat, "lat"))} · ${esc(dd(pos.lon, "lon"))}</span>
          ${pos.country_polygon ? `<span class="dp-tag">${esc(pos.country_polygon.name_en || pos.country_polygon.name_ar || "")}</span>` : ""}
        </div>
        <p class="dp-desc">${esc(L(
          (d.reason && d.reason.message_en) || "",
          (d.reason && d.reason.message_ar) || "") ||
          (n.facts && n.facts[0] && String(n.facts[0].value || "")) || "")}</p>
        ${rels.length ? `<div class="dp-rels">${rels.map(r => `
          <button class="dp-rel" data-pop-goto="${esc(r.type)}:${r.record_id}">
            <i class="dp-dot is-${esc(r.type)}"></i>${esc(r.label || "")}</button>`).join("")}</div>` : ""}
        <div class="dp-acts">
          <a class="btn sm" href="#/entity/${esc(n.type)}/${n.record_id}/edit">${esc(t("desk.editPos"))}</a>
          <button class="btn sm primary" data-pop-net>${esc(t("desk.showInNetwork"))}</button>
        </div>
        <div class="dp-foot muted small">${esc(t("desk.popFoot"))}</div>
      </div>`;
    const marker = new window.maplibregl.Marker({ element: el, anchor: "bottom", offset: [0, -26] })
      .setLngLat([pos.lon, pos.lat]).addTo(D.map);
    D.popup = marker;
    el.addEventListener("click", (ev) => ev.stopPropagation());
    el.querySelector("[data-pop-close]").onclick = closePopup;
    el.querySelectorAll("[data-pop-goto]").forEach(b => {
      b.onclick = () => {
        const [ty, id] = b.getAttribute("data-pop-goto").split(":");
        select(ty, Number(id), { fly: true });
      };
    });
    const net = el.querySelector("[data-pop-net]");
    if (net) net.onclick = () => {
      D.netOpen = true;
      document.querySelector("[data-desk]").classList.add("net-open");
      renderNetwork();
    };
  }
  function positionPopup() { /* markers follow their coordinate; nothing to do */ }
  function closePopup() {
    if (D.popup) { D.popup.remove(); D.popup = null; }
  }

  /* ═════════════════════════════════════════════════════════════ network ══ */
  /* ── where the window is busiest ───────────────────────────────────────── */
  function renderHubs(groups) {
    const host = document.querySelector("[data-desk-net]");
    const svg = host && host.querySelector("[data-net-svg]");
    if (!svg) return;
    const rows = (groups || []).slice(0, 6);
    if (!rows.length) return;
    /* the panel is laid out in the reading direction: in Arabic the name starts at
       the right edge, and a name that runs off its own row is not a name */
    const rtl = document.documentElement.dir === "rtl";
    const dotX = rtl ? 296 : 22;
    const nameX = rtl ? 284 : 34;
    const nameAnchor = rtl ? "end" : "start";
    const countX = rtl ? 20 : 304;
    const countAnchor = rtl ? "start" : "end";
    svg.innerHTML = rows.map((g, i) => {
      const y = 26 + i * 32;
      const label = lang() === "ar" ? (g.label_ar || g.label_en) : (g.label_en || g.label_ar);
      return `<g class="dh-row" data-net-goto="place:${g.place_id}" tabindex="0" role="button"
                 aria-label="${esc(label || "")}">
        <rect x="8" y="${y - 15}" width="304" height="28" rx="6" class="dh-bg"></rect>
        <circle cx="${dotX}" cy="${y}" r="4" class="dh-dot is-place"></circle>
        <text x="${nameX}" y="${y + 4}" text-anchor="${nameAnchor}" class="dh-name">${
          esc(String(label || "").slice(0, 22))}</text>
        <text x="${countX}" y="${y + 4}" text-anchor="${countAnchor}" class="dh-count">${
          fmtNum(g.count || 0)}</text>
      </g>`;
    }).join("") + `<text x="160" y="238" text-anchor="middle" class="dn-empty">${
      esc(t("desk.hubsNote"))}</text>`;
    svg.querySelectorAll("[data-net-goto]").forEach(g => {
      const go = () => {
        const [ty, id] = g.getAttribute("data-net-goto").split(":");
        select(ty, Number(id), { fly: true });
      };
      g.addEventListener("click", go);
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
    });
  }

  const hubCache = new Map();
  let hubSeq = 0;
  function loadHubs() {
    if (!D.map || D.node) return;
    const b = D.map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
      .map(n => n.toFixed(1)).join(",");
    if (hubCache.has(bbox)) return renderHubs(hubCache.get(bbox));
    const seq = ++hubSeq;
    api.get(`/api/map/groups?bbox=${bbox}&zoom=${D.map.getZoom().toFixed(2)}&limit=8`)
      .then(res => {
        if (seq !== hubSeq) return;               /* a later window has taken over */
        hubCache.set(bbox, res.groups || []);
        if (!D.node) renderHubs(res.groups || []);
      })
      .catch(() => {});
  }

  function renderNetwork() {
    const host = document.querySelector("[data-desk-net]");
    if (!host) return;
    const svg = host.querySelector("[data-net-svg]");
    const head = host.querySelector("[data-net-head]");
    if (!svg) return;
    const n = D.node;
    const W = 320, H = 300, cx = W / 2, cy = H / 2;
    if (!n) {
      if (head) head.innerHTML = `<span>${esc(t("desk.network"))}</span>`;
      /* nothing selected is not nothing to say: the window's densest places are the
         record-independent thing this panel knows, so it offers them as a way in */
      svg.innerHTML = `<text x="${cx}" y="${cy - 46}" text-anchor="middle" class="dn-empty">${
        esc(t("desk.netEmpty"))}</text>`;
      loadHubs();
      return;
    }
    const rows = (n.neighbours || []).slice(0, 12);
    if (head) {
      head.innerHTML = `<span>${esc(t("desk.network"))}</span>
        <b>${fmtNum(rows.length)} / ${fmtNum((n.counts || {}).relationships || 0)}</b>`;
    }
    const R = 74;   /* room for the labels, which are part of the drawing */
    const parts = [];
    const byType = new Map();
    rows.forEach((r, i) => {
      if (!byType.has(r.type)) byType.set(r.type, []);
      byType.get(r.type).push({ r, i });
    });
    /* sector per neighbour type: a neighbourhood is read by what it is made of */
    const types = [...byType.keys()];
    let a0 = -Math.PI / 2;
    const total = rows.length || 1;
    for (const ty of types) {
      const group = byType.get(ty);
      const span = (group.length / total) * Math.PI * 2;
      group.forEach((item, k) => {
        const a = a0 + span * ((k + 0.5) / group.length);
        const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
        const rel = item.r;
        parts.push(`<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"
            class="dn-edge is-${esc(ty)}" data-edge="${esc(ty)}:${rel.record_id}"></line>`);
        parts.push(`<g class="dn-node is-${esc(ty)}" data-net-goto="${esc(ty)}:${rel.record_id}"
            tabindex="0" role="button" aria-label="${esc(rel.label || "")}">
            <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7"></circle>
            <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="15" class="dn-hit"></circle>
            <text x="${Math.max(52, Math.min(W - 52, cx + (R + 26) * Math.cos(a))).toFixed(1)}"
                  y="${(cy + (R + 26) * Math.sin(a) + 3).toFixed(1)}"
                  text-anchor="middle">${
              esc(String(rel.label || "").slice(0, 13))}</text>
            <title>${esc((rel.label || "") + " — " + (label(rel, "rel_en", "rel_ar") || ""))}</title>
          </g>`);
      });
      a0 += span;
    }
    /* a label pinned to the edge must not be clipped by the panel: shrink to fit */
    const centreMark = A.crce && A.crce.iconDataUrl && markOf(n.type)
      ? A.crce.iconDataUrl(markOf(n.type), 46) : null;
    svg.innerHTML = `<g class="dn-edges">${parts.join("")}</g>
      <g class="dn-centre">
        ${centreMark ? `<image href="${centreMark}" x="${cx - 19}" y="${cy - 19}" width="38" height="38"></image>`
                     : `<circle cx="${cx}" cy="${cy}" r="10" class="dn-hub"></circle>`}
        <text x="${cx}" y="${cy + 34}" text-anchor="middle" class="dn-centre-label">${
          esc(String(n.title || "").slice(0, 22))}</text>
      </g>`;
    svg.querySelectorAll("[data-net-goto]").forEach(g => {
      const go = () => {
        const [ty, id] = g.getAttribute("data-net-goto").split(":");
        select(ty, Number(id), { fly: true });
      };
      g.addEventListener("click", go);
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
      g.addEventListener("pointerenter", () => {
        svg.querySelectorAll(`[data-edge="${g.getAttribute("data-net-goto")}"]`)
          .forEach(e => e.classList.add("is-hot"));
      });
      g.addEventListener("pointerleave", () => {
        svg.querySelectorAll(".dn-edge.is-hot").forEach(e => e.classList.remove("is-hot"));
      });
    });
  }

  /* ------------------------------------------------------------- minimap --- */
  function drawLegend() {
    const box = document.querySelector("[data-desk-legend]");
    if (!box) return;
    const cats = ["person", "institution", "place", "event"];
    box.innerHTML = cats.map(c => {
      const url = A.crce && A.crce.iconDataUrl && markOf(c) ? A.crce.iconDataUrl(markOf(c), 20) : null;
      return `<span class="dl-item${D.layers.has(c) ? "" : " is-off"}">
        ${url ? `<img src="${url}" alt="">` : `<i class="dp-dot is-${esc(c)}"></i>`}
        ${esc(typeOne(c))}</span>`;
    }).join("") + `<span class="dl-item is-note">${esc(t("desk.legendNote"))}</span>`;
  }

  function drawMini() {
    const box = document.querySelector("[data-desk-mini]");
    if (!box || !D.map) return;
    const svg = box.querySelector("svg");
    if (!svg) return;
    const W = 100, H = 60;
    const project = (lon, lat) => [((lon + 180) / 360) * W, ((90 - lat) / 180) * H];
    const dots = D.miniPts.map(p => {
      const [x, y] = project(p.lon, p.lat);
      return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="0.5" class="dm-mini-dot is-${esc(p.entity_type)}"></circle>`;
    }).join("");
    const b = D.map.getBounds();
    const [x1, y1] = project(b.getWest(), b.getNorth());
    const [x2, y2] = project(b.getEast(), b.getSouth());
    const z = D.map.getZoom();
    const pct = Math.max(1, Math.min(100, Math.round((z / 19) * 100)));
    svg.innerHTML = `<rect x="0" y="0" width="${W}" height="${H}" class="dm-mini-bg"></rect>${dots}
      <rect x="${Math.max(0, x1).toFixed(2)}" y="${Math.max(0, y1).toFixed(2)}"
            width="${Math.max(0.6, Math.min(W, x2) - Math.max(0, x1)).toFixed(2)}"
            height="${Math.max(0.6, Math.min(H, y2) - Math.max(0, y1)).toFixed(2)}"
            class="dm-mini-win"></rect>`;
    const pctEl = box.querySelector("[data-mini-pct]");
    if (pctEl) pctEl.textContent = `${pct}%`;
  }

  /* ══════════════════════════════════════════════════════════════ the grid ══ */
  function drawGrid() {
    const host = document.querySelector("[data-desk-grid]");
    if (!host) return;
    const rows = D.points.slice(0, 400);
    host.innerHTML = `
      <table class="desk-grid">
        <thead><tr>
          <th>${esc(t("desk.title"))}</th><th>${esc(t("desk.type"))}</th>
          <th>${esc(t("desk.code"))}</th><th>${esc(t("desk.anchor"))}</th>
          <th class="num">${esc(t("desk.lat"))}</th><th class="num">${esc(t("desk.lon"))}</th>
          <th></th>
        </tr></thead>
        <tbody>
        ${rows.map(p => `<tr data-grid="${esc(p.entity_type)}:${p.id}"
            class="${D.sel && D.sel.type === p.entity_type && D.sel.id === p.id ? "is-selected" : ""}">
          <td class="dg-name">${esc(label(p, "label_en", "label_ar") || p.code)}</td>
          <td>${esc(typeOne(p.entity_type))}</td>
          <td class="mono-cell">${esc(p.code || "")}</td>
          <td>${esc(label(p, "anchor_en", "anchor_ar") || "—")}</td>
          <td class="num mono-cell">${Number(p.lat).toFixed(4)}</td>
          <td class="num mono-cell">${Number(p.lon).toFixed(4)}</td>
          <td><button class="btn xs" data-fly="${esc(p.entity_type)}:${p.id}">${
            esc(t("desk.onMap"))}</button></td>
        </tr>`).join("")}
        </tbody>
      </table>
      <div class="desk-grid-foot muted small">${esc(t("desk.gridFoot", { n: rows.length }))}</div>`;
    host.querySelectorAll("[data-grid]").forEach(tr => {
      tr.onclick = () => {
        const [ty, id] = tr.getAttribute("data-grid").split(":");
        select(ty, Number(id), { fly: true });
        host.querySelectorAll("tr.is-selected").forEach(x => x.classList.remove("is-selected"));
        tr.classList.add("is-selected");
      };
    });
    host.querySelectorAll("[data-fly]").forEach(b => {
      b.onclick = (ev) => {
        ev.stopPropagation();
        const [ty, id] = b.getAttribute("data-fly").split(":");
        setGrid(false);
        select(ty, Number(id), { fly: true });
      };
    });
  }

  function setGrid(on) {
    D.grid = !!on;
    const desk = document.querySelector("[data-desk]");
    if (desk) desk.classList.toggle("is-grid", D.grid);
    document.querySelectorAll("[data-view]").forEach(b => {
      b.classList.toggle("active", (b.getAttribute("data-view") === "grid") === D.grid);
      b.setAttribute("aria-pressed", String((b.getAttribute("data-view") === "grid") === D.grid));
    });
    const wrap = document.querySelector("[data-desk-grid]");
    if (wrap) wrap.hidden = !D.grid;   /* the table is a panel over the map, not a route */
    if (D.grid) drawGrid();
    if (D.map) setTimeout(() => D.map.resize(), 60);
    savePrefs({ grid: D.grid });
  }

  /* ══════════════════════════════════════════════════════════════ toolbar ══ */
  function wireToolbar(root) {
    root.querySelectorAll("[data-desk-back]").forEach(b => b.onclick = () => stepHistory(-1));
    root.querySelectorAll("[data-desk-forward]").forEach(b => b.onclick = () => stepHistory(1));
    root.querySelectorAll("[data-desk-undo]").forEach(b => b.onclick = () => {
      if (D.history.length > 1) { D.history.pop(); D.at = D.history.length - 1; stepHistory(0); paintHistory(); }
      else closeSelection();
    });
    root.querySelectorAll("[data-view]").forEach(b => {
      b.onclick = () => setGrid(b.getAttribute("data-view") === "grid");
    });
    const search = root.querySelector("[data-desk-search]");
    if (search) {
      let timer = 0;
      search.addEventListener("input", () => {
        clearTimeout(timer);
        const q = search.value.trim();
        const box = root.querySelector("[data-desk-suggest]");
        if (!q) { box.hidden = true; box.innerHTML = ""; return; }
        timer = setTimeout(async () => {
          try {
            const res = await api.get(`/api/search?q=${encodeURIComponent(q)}&limit=8`);
            /* the search answers grouped by entity, with the group's own label */
            const rows = [];
            for (const g of (res.groups || [])) {
              for (const item of (g.items || [])) rows.push({ entity: g.entity, ...item });
            }
            box.innerHTML = rows.slice(0, 8).map(r => `<button class="ds-item"
              data-suggest="${esc(r.entity)}:${r.id}">
              <span>${esc(r.title || r.code)}</span>
              <em>${esc(typeOne(r.entity))} · ${esc(r.code || "")}</em></button>`).join("")
              || `<div class="ds-empty">${esc(t("desk.noMatch"))}</div>`;
            box.hidden = false;
            box.querySelectorAll("[data-suggest]").forEach(b2 => {
              b2.onclick = () => {
                const [ty, id] = b2.getAttribute("data-suggest").split(":");
                box.hidden = true;
                search.value = "";
                select(ty, Number(id), { fly: true });
              };
            });
          } catch (e) { box.hidden = true; }
        }, 220);
      });
      search.addEventListener("keydown", (ev) => {
        const box = root.querySelector("[data-desk-suggest]");
        const first = box.querySelector("[data-suggest]");
        if (ev.key === "Enter" && first) { ev.preventDefault(); first.click(); }
        if (ev.key === "Escape") { box.hidden = true; search.blur(); }
      });
    }
    root.querySelector("[data-desk-fit]").onclick = () => {
      /* a menu item that does something puts the menu away; leaving it open over
         the map is how a control ends up covering the thing it acted on */
      const menu = root.querySelector("[data-tools]");
      if (menu) menu.hidden = true;
      const pts = D.points;
      if (!pts.length) return;
      const lons = pts.map(p => p.lon), lats = pts.map(p => p.lat);
      D.map.fitBounds([[Math.min(...lons), Math.min(...lats)],
                       [Math.max(...lons), Math.max(...lats)]], { padding: 60, duration: 600 });
    };
    root.querySelector("[data-desk-labels]").onclick = (ev) => {
      D.labels = !D.labels;
      ev.currentTarget.classList.toggle("is-on", D.labels);
      drawMarkers();
      savePrefs({ labels: D.labels });
    };
    root.querySelector("[data-desk-net-toggle]").onclick = (ev) => {
      D.netOpen = !D.netOpen;
      root.querySelector("[data-desk]").classList.toggle("net-open", D.netOpen);
      ev.currentTarget.classList.toggle("is-on", D.netOpen);
      if (D.map) setTimeout(() => D.map.resize(), 60);
      savePrefs({ net: D.netOpen });
    };
    root.querySelectorAll("[data-provider]").forEach(b => {
      b.onclick = () => {
        const id = b.getAttribute("data-provider");
        const p = D.conf.providers.find(x => x.id === id);
        if (!p) return;
        D.provider = p;
        baseKey = "";
        D.map.setStyle(p.style);
        D.map.once("styledata", () => { ensureBasemap(); if (D.maplib) D.maplib.syncStreets(); drawMarkers(); });
        D.map.once("idle", () => { ensureBasemap(); if (D.maplib) D.maplib.syncStreets(); drawMarkers(); });
        root.querySelectorAll("[data-provider]").forEach(x => x.classList.toggle("active", x === b));
        savePrefs({ provider: id });
        setGrid(D.grid);
      };
    });
    const addRel = root.querySelector("[data-desk-add-rel]");
    if (addRel) addRel.onclick = () => openDeskRelationshipComposer();
    const addEnt = root.querySelector("[data-desk-add-entity]");
    if (addEnt) addEnt.onclick = () => openDeskEntityComposer();
    const addAt = root.querySelector("[data-desk-add-at]");
    if (addAt) addAt.onclick = () => {
      if (!D.maplib) return;
      D.maplib.setPickAdd(!D.maplib.state.pickAdd);
      addAt.classList.toggle("is-on", D.maplib.state.pickAdd);
    };
    const fitArea = root.querySelector("[data-desk-fit-area]");
    if (fitArea) fitArea.onclick = () => {
      if (D.maplib) D.maplib.fitArea();
      else toast(t("geo.noWorkingArea"), "warn");
    };
    const streetsToggle = root.querySelector("[data-desk-streets]");
    if (streetsToggle) streetsToggle.onclick = (ev) => {
      if (!D.maplib) return;
      const on = !D.maplib.state.streetsOn;
      D.maplib.setStreetsOn(on);
      ev.currentTarget.classList.toggle("active", on);
    };
    const mini = root.querySelector("[data-desk-mini]");
    if (mini) {
      mini.querySelector("svg").addEventListener("click", (ev) => {
        const r = ev.currentTarget.getBoundingClientRect();
        const x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
        D.map.easeTo({ center: [x * 360 - 180, 90 - y * 180], duration: 400 });
      });
      const fit = mini.querySelector("[data-mini-fit]");
      if (fit) fit.onclick = (ev) => { ev.stopPropagation(); root.querySelector("[data-desk-fit]").click(); };
    }
  }

  /* ══════════════════════════════════════════════════════════════ the view ══ */
  A.views = A.views || {};
  A.views.desk = async function view(root, params) {
    const pre = prefs();
    D.labels = pre.labels !== false;
    D.grid = !!pre.grid;
    D.netOpen = pre.net !== false;
    D.sel = null; D.detail = null; D.node = null; D.tab = "overview";
    D.history = []; D.at = -1; D.markers = []; D.miniPts = [];
    D.layers = new Set((params && params.layers ? String(params.layers).split(",") : null)
      || ["person", "institution", "place", "event"]);
    D.filterEl = null;

    root.innerHTML = `<div class="desk-loading"><div class="skeleton" style="width:30%"></div>
      <div class="skeleton" style="width:70%;margin-top:10px"></div></div>`;
    try {
      D.conf = await api.get("/api/map/config");
    } catch (err) {
      root.innerHTML = `<div class="card"><h2>${esc(t("desk.title"))}</h2>
        <div class="notice err">${esc(err.message || String(err))}</div></div>`;
      return;
    }
    const defaultView = (A.mapDefault && A.mapDefault().provider) || D.conf.provider.id;
    const provider = D.conf.providers.find(p => p.id === (pre.provider || defaultView)) || D.conf.provider;

    root.innerHTML = `
      <div class="desk${D.netOpen ? " net-open" : ""}${D.grid ? " is-grid" : ""}" data-desk>
        <div class="desk-bar">
          <div class="desk-bar-group">
            <button class="icon-btn" data-desk-forward title="${esc(t("desk.forward"))}"
              aria-label="${esc(t("desk.forward"))}" disabled>→</button>
            <button class="icon-btn" data-desk-back title="${esc(t("desk.back"))}"
              aria-label="${esc(t("desk.back"))}" disabled>←</button>
            <button class="icon-btn" data-desk-undo title="${esc(t("desk.undo"))}"
              aria-label="${esc(t("desk.undo"))}">↺</button>
          </div>
          <div class="desk-bar-group desk-menu-wrap">
            <button class="btn sm" data-tools-toggle>▾ ${esc(t("desk.tools"))}</button>
            <div class="desk-menu" data-tools hidden>
              <div class="dm-group">${esc(t("desk.baseMap"))}</div>
              ${D.conf.providers.map(p => `<button class="dm-item${p.id === provider.id ? " active" : ""}"
                data-provider="${esc(p.id)}">${esc(lang() === "ar" ? (p.label_ar || p.label_en) : p.label_en)}</button>`).join("")}
              <div class="dm-group">${esc(t("desk.display"))}</div>
              <button class="dm-item${D.labels ? " active" : ""}" data-desk-labels>${esc(t("desk.showLabels"))}</button>
              <button class="dm-item${D.netOpen ? " active" : ""}" data-desk-net-toggle>${esc(t("desk.networkPanel"))}</button>
              <button class="dm-item${(pre.streets !== false && (pre.basemapMode || "vector") !== "off") ? " active" : ""}" data-desk-streets>${esc(t("geo.streetsOverlay"))}</button>
              <button class="dm-item" data-desk-fit>${esc(t("desk.fitPoints"))}</button>
              <button class="dm-item" data-desk-fit-area>${esc(t("geo.fitWorkingArea"))}</button>
            </div>
          </div>
          <div class="desk-seg" role="group" aria-label="${esc(t("desk.view"))}">
            <button class="desk-seg-btn${D.grid ? "" : " active"}" data-view="map"
              aria-pressed="${!D.grid}">${esc(t("desk.map"))}</button>
            <button class="desk-seg-btn${D.grid ? " active" : ""}" data-view="grid"
              aria-pressed="${D.grid}">${esc(t("desk.grid"))}</button>
          </div>
          <div class="desk-bar-group desk-grow">
            <div class="desk-search-wrap">
              <span class="ds-ico">⌕</span>
              <input class="desk-search" data-desk-search type="search" autocomplete="off"
                     placeholder="${esc(t("desk.searchPlaceholder"))}"
                     aria-label="${esc(t("desk.search"))}">
              <div class="desk-suggest" data-desk-suggest hidden></div>
            </div>
          </div>
          <div class="desk-bar-group">
            <button type="button" class="btn sm" data-desk-add-at title="${esc(t("geo.addAtHint"))}">⌖ ${esc(t("geo.addPlace"))}</button>
            <button type="button" class="btn sm" data-desk-add-rel>+ ${esc(t("desk.addRelation"))}</button>
            <button type="button" class="btn sm primary" data-desk-add-entity>+ ${esc(t("desk.addEntity"))}</button>
          </div>
        </div>

        <div class="desk-body">
          <aside class="desk-rail" data-desk-rail aria-live="polite"></aside>
          <div class="desk-centre">
            <div class="desk-map" data-desk-map>
              <div class="desk-chipbar" data-desk-chipbar></div>
              <div class="desk-gridwrap" data-desk-grid hidden></div>
            </div>
            <div class="desk-mini" data-desk-mini>
              <div class="dm-mini-head"><span>${esc(t("desk.overview"))}</span>
                <b data-mini-pct>—</b>
                <button class="icon-btn" data-mini-fit title="${esc(t("desk.fitPoints"))}">⤢</button></div>
              <svg viewBox="0 0 100 60" preserveAspectRatio="none" role="img"
                   aria-label="${esc(t("desk.overview"))}"></svg>
            </div>
          </div>
          <aside class="desk-net" data-desk-net>
            <div class="desk-net-head" data-net-head></div>
            <svg class="desk-net-svg" data-net-svg viewBox="0 0 320 300" role="img"
                 aria-label="${esc(t("desk.network"))}"></svg>
            <div class="desk-net-foot muted small">${esc(t("desk.netFoot"))}</div>
          </aside>
        </div>
      </div>`;

    const mapHost = root.querySelector("[data-desk-map]");
    mapHost.insertAdjacentHTML("beforeend",
      `<div class="desk-legend" data-desk-legend aria-label="${esc(t("desk.legend"))}"></div>`);
    /* the map is created before the chip bar exists in some layouts; the chip
       painter is defensive, and every later call re-reads the DOM */
    await bootMap(mapHost);
    attachMapLib(mapHost);
    if (D.ready && D.maplib) D.maplib.syncStreets();
    wireToolbar(root);
    if (D.grid) setGrid(true);
    indexRail();
    drawLegend();
    renderNetwork();
    setGrid(D.grid);
    loadOverview();

    const tools = root.querySelector("[data-tools]");
    const toolBtn = root.querySelector("[data-tools-toggle]");
    toolBtn.onclick = (ev) => {
      ev.stopPropagation();
      tools.hidden = !tools.hidden;
    };
    document.addEventListener("click", (ev) => {
      if (!tools.hidden && !ev.target.closest("[data-tools]") && ev.target !== toolBtn) tools.hidden = true;
    });

    /* keyboard: the same verbs as the mouse, and a way out of everything */
    const onKey = (ev) => {
      const typing = ev.target && /input|select|textarea/i.test(ev.target.tagName || "");
      if (ev.key === "Escape") {
        if (D.pickForRel) {
          D.pickForRel = null; setPickCue(false);
          const slot = root.querySelector("[data-desk-composer]");
          if (slot && !slot.hidden) {
            const cancel = slot.querySelector("[data-rc-cancel], [data-ec-cancel]");
            if (cancel) cancel.click();
          }
          return;
        }
        const slot = root.querySelector("[data-desk-composer]");
        if (slot && !slot.hidden && slot.querySelector(".rel-composer-head, .ent-composer, [data-rc-cancel], [data-ec-cancel]")) {
          const cancel = slot.querySelector("[data-rc-cancel], [data-ec-cancel]");
          if (cancel) { cancel.click(); return; }
        }
        if (D.popup) { closePopup(); return; }
        const toolsEl = root.querySelector("[data-tools]");
        if (toolsEl && !toolsEl.hidden) { toolsEl.hidden = true; return; }
        if (D.sel) { closeSelection(); return; }
      }
      if (typing) return;
      if (ev.key === "/") { ev.preventDefault(); root.querySelector("[data-desk-search]").focus(); return; }
      if (ev.key === "g") { setGrid(!D.grid); return; }
      if (ev.key === "m") { setGrid(false); return; }
      if (ev.key === "f") { root.querySelector("[data-desk-fit]").click(); return; }
      if (ev.key === "e" && D.node) {
        A.go(`/entity/${D.node.type}/${D.node.record_id}/edit`); return;
      }
      if (ev.key === "r") { openDeskRelationshipComposer(); return; }
      if (ev.key === "n") { openDeskEntityComposer(); return; }
      if (ev.key === "[" || ev.key === "]") {
        const i = D.points.findIndex(p => D.sel && p.entity_type === D.sel.type && p.id === D.sel.id);
        const next = D.points[(i + (ev.key === "]" ? 1 : -1) + D.points.length) % D.points.length];
        if (next) select(next.entity_type, next.id, { fly: true });
      }
    };
    document.addEventListener("keydown", onKey);

    D.map.on("moveend", () => savePrefs({
      lat: D.map.getCenter().lat, lon: D.map.getCenter().lng, zoom: D.map.getZoom(),
    }));

    view.__dispose = () => {
      document.removeEventListener("keydown", onKey);
      closePopup();
      for (const m of D.markers) { try { m.remove(); } catch (e) { /* gone with the DOM */ } }
      D.markers = [];
      if (D.map) { try { D.map.remove(); } catch (e) { /* already disposed */ } }
      D.map = null; D.ready = false;
      if (window.__deskMap) window.__deskMap = null;
    };
  };
})(window.App);
