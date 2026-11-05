/* ============================================================================
   SIRAJ · lib/maplib.js — one geographic runtime for Desk and Geo
   ----------------------------------------------------------------------------
   Every map workspace (desk, geographic map) shares this layer:

     streets   · vectormap sync, area frame, dim-outside, layer toggles
     hud       · basemap chips, area pill, vertical tools, IO popover
     measure   · distance (+ optional area)
     createAt  · right-click / pick-to-add → A.composeEntity in a host
     io        · GeoJSON export/import + offline-pack download

   Views supply the MapLibre map, a host element, prefs, and callbacks.
   They do not re-implement the same verbs.
   ========================================================================== */
(function (A) {
  "use strict";

  const R_EARTH = 6371008.8;
  const DEFAULT_LAYERS = {
    roads: true, water: true, green: true, labels: true,
    area: true, dimOutside: true, pins: true
  };

  function haversine(aLat, aLon, bLat, bLon) {
    const toR = d => (d * Math.PI) / 180;
    const dLat = toR(bLat - aLat), dLon = toR(bLon - aLon);
    const h = Math.sin(dLat / 2) ** 2
      + Math.cos(toR(aLat)) * Math.cos(toR(bLat)) * Math.sin(dLon / 2) ** 2;
    return 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function polygonArea(points) {
    if (!points || points.length < 3) return 0;
    const pts = points.map(p => [p.lon, p.lat]);
    if (pts[0][0] !== pts[pts.length - 1][0] || pts[0][1] !== pts[pts.length - 1][1]) {
      pts.push(pts[0]);
    }
    let total = 0;
    const toR = d => (d * Math.PI) / 180;
    for (let i = 0; i < pts.length - 1; i++) {
      total += toR(pts[i + 1][0] - pts[i][0])
        * (2 + Math.sin(toR(pts[i][1])) + Math.sin(toR(pts[i + 1][1])));
    }
    return Math.abs((total * R_EARTH * R_EARTH) / 2);
  }

  function areaKm2(bbox) {
    if (!bbox) return null;
    const mid = (bbox.s + bbox.n) / 2;
    const w = haversine(mid, bbox.w, mid, bbox.e) / 1000;
    const h = haversine(bbox.s, bbox.w, bbox.n, bbox.w) / 1000;
    return w * h;
  }

  function fmtLen(m) {
    return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
  }

  function fmtArea(sqm) {
    if (sqm >= 1e6) return `${(sqm / 1e6).toFixed(2)} km²`;
    if (sqm >= 1e4) return `${(sqm / 1e4).toFixed(2)} ha`;
    return `${Math.round(sqm)} m²`;
  }

  /**
   * @param {object} opts
   * @param {maplibregl.Map} opts.map
   * @param {HTMLElement} opts.host          map container for HUD overlays
   * @param {object} [opts.conf]             /api/map/config payload
   * @param {object} [opts.prefs]            persisted maplib prefs
   * @param {function} [opts.onPrefs]        (patch) => void
   * @param {function} [opts.onStyleChange]  ({ provider }) after setStyle
   * @param {function} [opts.onFitPoints]
   * @param {function} [opts.onPointsRefresh]
   * @param {function} [opts.getPointCount]
   * @param {function} [opts.composerHost]   () => element for create-at
   * @param {function} [opts.onPlaceSaved]   (rec, {lat,lon}) => void
   * @param {function} [opts.onPinsVisibility] (visible:boolean) => void
   * @param {string} [opts.pickingClass]     CSS class on workspace while pick-add
   * @param {Element} [opts.pickingRoot]
   * @param {boolean} [opts.hud=true]
   * @param {boolean} [opts.autoBoot=true]
   */
  A.maplib = function createMapLib(opts) {
    opts = opts || {};
    const { t, esc, api, toast } = A;
    const map = opts.map;
    const host = opts.host;
    if (!map || !host) throw new Error("maplib needs map and host");

    const conf = opts.conf || {};
    const pack = conf.offline_pack || {};
    const prefs = Object.assign({}, opts.prefs || {});
    const state = {
      basemapMode: prefs.basemapMode || "vector",
      hybridOpacity: Number(prefs.hybridOpacity) || 0.72,
      streetLayers: Object.assign({}, DEFAULT_LAYERS, prefs.streetLayers || {}),
      streetsOn: prefs.streets !== false,
      pickAdd: false,
      creatingAt: null,
      measure: { mode: "off", points: [] },
      streetsFitted: false,
      destroyed: false
    };

    const save = (patch) => {
      Object.assign(prefs, patch);
      if (opts.onPrefs) opts.onPrefs(patch);
    };

    /* ----------------------------------------------------------- streets --- */
    function setLayerVis(id, on) {
      try {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
      } catch (e) { /* style swap */ }
    }

    function applyLayerVisibility() {
      const L = state.streetLayers;
      setLayerVis("vm-roads-major", !!L.roads);
      setLayerVis("vm-roads-minor", !!L.roads);
      setLayerVis("vm-water-fill", !!L.water);
      setLayerVis("vm-water-line", !!L.water);
      setLayerVis("vm-green-fill", !!L.green);
      setLayerVis("vm-places-dot", !!L.labels);
      setLayerVis("ml-area-line", !!L.area);
      setLayerVis("ml-dim-fill", !!L.dimOutside);
      if (opts.onPinsVisibility) opts.onPinsVisibility(L.pins !== false);
    }

    function applyHybridOpacity() {
      const mode = state.basemapMode;
      const op = mode === "hybrid" ? (Number(state.hybridOpacity) || 0.72) : 1;
      const paint = (id, prop, v) => {
        try { if (map.getLayer(id)) map.setPaintProperty(id, prop, v); } catch (e) { /* */ }
      };
      const roadOp = mode === "hybrid" ? 0.55 + 0.45 * op : 1;
      paint("vm-roads-major", "line-opacity", roadOp);
      paint("vm-roads-minor", "line-opacity", roadOp * 0.85);
      paint("vm-water-fill", "fill-opacity", mode === "hybrid" ? 0.35 + 0.35 * op : 0.7);
      paint("vm-green-fill", "fill-opacity", mode === "hybrid" ? 0.3 + 0.25 * op : 0.55);
    }

    function clearAreaChrome() {
      ["ml-dim-fill", "ml-area-line"].forEach(id => {
        try { if (map.getLayer(id)) map.removeLayer(id); } catch (e) { /* */ }
      });
      ["ml-dim", "ml-area"].forEach(id => {
        try { if (map.getSource(id)) map.removeSource(id); } catch (e) { /* */ }
      });
    }

    function drawAreaChrome(bbox) {
      if (!bbox) return;
      const { w, s, e, n } = bbox;
      if (![w, s, e, n].every(Number.isFinite)) return;
      const ring = [[w, s], [e, s], [e, n], [w, n], [w, s]];
      const upsert = (sid, data, layers) => {
        if (map.getSource(sid)) map.getSource(sid).setData(data);
        else {
          map.addSource(sid, { type: "geojson", data });
          layers.forEach(l => { if (!map.getLayer(l.id)) map.addLayer(l); });
        }
      };
      upsert("ml-dim", {
        type: "FeatureCollection",
        features: [{
          type: "Feature", properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [
              [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]],
              ring.slice().reverse()
            ]
          }
        }]
      }, [{
        id: "ml-dim-fill", type: "fill", source: "ml-dim",
        paint: { "fill-color": "#0a0f15", "fill-opacity": 0.45 }
      }]);
      upsert("ml-area", {
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: ring } }]
      }, [{
        id: "ml-area-line", type: "line", source: "ml-area",
        paint: { "line-color": "#cfe94a", "line-width": 2, "line-dasharray": [2, 2], "line-opacity": 0.9 }
      }]);
      applyLayerVisibility();
    }

    async function syncStreets(o) {
      if (state.destroyed || !A.applyVectormapLayers) return;
      const mode = state.basemapMode || "vector";
      const want = state.streetsOn && (mode === "vector" || mode === "hybrid" || mode === "raster" || mode === "overlay");
      host.classList.toggle("is-light-map", want && mode !== "overlay");
      if (!want) {
        A.removeVectormapLayers(map);
        clearAreaChrome();
        return;
      }
      try {
        const inflated = await A.loadVectormap();
        if (state.destroyed) return;
        const fit = !!(o && o.fit) || ((mode === "vector" || mode === "raster") && !state.streetsFitted);
        const before = (o && o.beforeId) || null;
        A.applyVectormapLayers(map, inflated, { fit, beforeId: before });
        if (fit) state.streetsFitted = true;
        applyLayerVisibility();
        applyHybridOpacity();
        drawAreaChrome(inflated.bbox || pack.working_area);
        refreshHud();
      } catch (e) { /* pack optional */ }
    }

    function workingBbox() {
      return (pack.vectormap && pack.vectormap.bbox) || pack.working_area || null;
    }

    function fitArea() {
      const bbox = workingBbox();
      if (!bbox) { toast(t("geo.noWorkingArea"), "warn"); return; }
      map.fitBounds([[bbox.w, bbox.s], [bbox.e, bbox.n]], { padding: 48, duration: 900 });
    }

    function findProvider(idOrKind) {
      const list = conf.providers || [];
      return list.find(p => p.id === idOrKind)
        || list.find(p => p.kind === idOrKind)
        || null;
    }

    function setBasemap(mode) {
      if (mode === "raster" && !(pack.tilepack && pack.tilepack.available)) {
        toast(t("geo.rasterUnavailable"), "warn", 3200);
        return;
      }
      state.basemapMode = mode;
      state.streetsOn = mode !== "off";
      save({ basemapMode: mode, streets: state.streetsOn });

      let provider = null;
      if (mode === "hybrid") provider = findProvider("local");
      else if (mode === "vector" || mode === "raster") {
        provider = findProvider("streets-offline") || findProvider("vector-streets");
      }
      if (provider && opts.onStyleChange) {
        opts.onStyleChange({
          provider,
          after: () => syncStreets({ fit: mode !== "hybrid" })
        });
      } else {
        syncStreets({ fit: mode !== "hybrid" });
      }
      refreshHud();
    }

    /* ----------------------------------------------------------- measure --- */
    function ensureMeasureLayers() {
      if (map.getSource("ml-measure")) return;
      map.addSource("ml-measure", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "ml-measure-line", type: "line", source: "ml-measure",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#cfe94a", "line-width": 2, "line-dasharray": [2, 1] }
      });
      map.addLayer({
        id: "ml-measure-fill", type: "fill", source: "ml-measure",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#cfe94a", "fill-opacity": 0.12 }
      });
      map.addLayer({
        id: "ml-measure-pts", type: "circle", source: "ml-measure",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 4, "circle-color": "#cfe94a",
          "circle-stroke-width": 1, "circle-stroke-color": "#0a0f15"
        }
      });
    }

    function measureGeoJSON() {
      const pts = state.measure.points;
      const features = pts.map(p => ({
        type: "Feature", properties: {},
        geometry: { type: "Point", coordinates: [p.lon, p.lat] }
      }));
      if (pts.length >= 2) {
        features.push({
          type: "Feature", properties: {},
          geometry: { type: "LineString", coordinates: pts.map(p => [p.lon, p.lat]) }
        });
      }
      if (state.measure.mode === "area" && pts.length >= 3) {
        const ring = pts.map(p => [p.lon, p.lat]);
        ring.push(ring[0]);
        features.push({
          type: "Feature", properties: {},
          geometry: { type: "Polygon", coordinates: [ring] }
        });
      }
      return { type: "FeatureCollection", features };
    }

    function redrawMeasure() {
      const src = map.getSource("ml-measure");
      if (!src) return;
      src.setData(measureGeoJSON());
      const pts = state.measure.points;
      let len = 0;
      for (let i = 1; i < pts.length; i++) {
        len += haversine(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon);
      }
      const area = state.measure.mode === "area" ? polygonArea(pts) : 0;
      const out = host.querySelector("[data-ml-measure-out]");
      if (out) {
        out.textContent = state.measure.mode === "area" && pts.length >= 3
          ? `${fmtLen(len)} · ${fmtArea(area)}`
          : fmtLen(len);
      }
      if (opts.onMeasure) opts.onMeasure({ length: len, area, mode: state.measure.mode, points: pts });
    }

    function setMeasure(mode) {
      state.measure.mode = mode || "off";
      state.measure.points = [];
      const on = state.measure.mode !== "off";
      const panel = host.querySelector("[data-ml-measure]");
      const btn = host.querySelector('[data-ml-act="measure"]');
      if (btn) {
        btn.setAttribute("aria-pressed", String(on));
        btn.classList.toggle("is-on", on);
      }
      if (panel) {
        panel.hidden = !on;
        if (on) {
          panel.innerHTML = `
            <strong>${esc(t(state.measure.mode === "area" ? "geo.measureArea" : "geo.measureDistance"))}</strong>
            <div class="muted small">${esc(t("geo.measureHint"))}</div>
            <div data-ml-measure-out dir="ltr">—</div>
            <div class="ml-io-row" style="margin-top:8px">
              <button type="button" data-ml-measure-mode="distance">${esc(t("geo.measureDistance"))}</button>
              <button type="button" data-ml-measure-mode="area">${esc(t("geo.measureArea"))}</button>
              <button type="button" data-ml-measure-clear>${esc(t("geo.measureClear"))}</button>
            </div>`;
          panel.querySelectorAll("[data-ml-measure-mode]").forEach(b => {
            b.onclick = () => setMeasure(b.getAttribute("data-ml-measure-mode"));
          });
          panel.querySelector("[data-ml-measure-clear]").onclick = () => {
            state.measure.points = [];
            redrawMeasure();
          };
        }
      }
      if (on) ensureMeasureLayers();
      redrawMeasure();
      map.getCanvas().style.cursor = on || state.pickAdd ? "crosshair" : "";
    }

    /* ---------------------------------------------------------- create-at --- */
    function setStreetsOn(on) {
      state.streetsOn = !!on;
      save({ streets: state.streetsOn });
      if (state.streetsOn && state.basemapMode === "off") state.basemapMode = "overlay";
      if (!state.streetsOn) {
        A.removeVectormapLayers(map);
        clearAreaChrome();
        host.classList.remove("is-light-map");
        refreshHud();
        return;
      }
      syncStreets({ fit: false });
    }

    function setPickAdd(on, silent) {
      state.pickAdd = !!on;
      const btn = host.querySelector('[data-ml-act="add"]');
      if (btn) btn.classList.toggle("is-on", state.pickAdd);
      const root = opts.pickingRoot || host.closest("[data-desk], .geo-workspace, [data-geo]") || host;
      const cls = opts.pickingClass || "is-picking-add";
      root.classList.toggle(cls, state.pickAdd);
      map.getCanvas().style.cursor = state.pickAdd || state.measure.mode !== "off" ? "crosshair" : "";
      if (!silent) toast(state.pickAdd ? t("geo.pickAddHint") : t("geo.pickAddOff"), "ok", 2200);
    }

    function openCreateAt(lat, lon) {
      state.creatingAt = { lat, lon };
      setPickAdd(false, true);
      const slot = opts.composerHost ? opts.composerHost({ lat, lon }) : null;
      if (!slot || !A.composeEntity) {
        toast(t("geo.noComposerHost") || t("geo.addAtHint"), "warn");
        return;
      }
      A.composeEntity({
        host: slot,
        entity: "place",
        at: { lat, lon, precision: "exact", method: "map_pick" },
        onCancel: () => {
          state.creatingAt = null;
          if (opts.onCreateCancel) opts.onCreateCancel({ lat, lon });
        },
        onSaved: async (rec) => {
          state.creatingAt = null;
          if (opts.onPointsRefresh) await opts.onPointsRefresh();
          if (opts.onPlaceSaved) await opts.onPlaceSaved(rec, { lat, lon });
          toast(t("geo.placeCreated"), "ok", 2800);
        }
      });
      slot.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    /* --------------------------------------------------------------- HUD --- */
    function refreshHud() {
      const frame = host.querySelector("[data-ml-frame]");
      if (!frame) return;
      const bbox = workingBbox();
      const areaTxt = frame.querySelector("[data-ml-area-txt]");
      const areaPill = frame.querySelector("[data-ml-area-pill]");
      if (areaPill && areaTxt && bbox) {
        const km = areaKm2(bbox);
        areaTxt.textContent = km
          ? `${t("geo.gazaArea")} · ${km.toFixed(1)} ${t("geo.km2")}`
          : t("geo.gazaArea");
        areaPill.hidden = false;
      }
      const count = frame.querySelector("[data-ml-count]");
      if (count && opts.getPointCount) {
        count.textContent = `${A.fmtNum(opts.getPointCount())} ${t("desk.points")}`;
      }
      const hybrid = frame.querySelector("[data-ml-hybrid]");
      if (hybrid) hybrid.hidden = state.basemapMode !== "hybrid";
      frame.querySelectorAll("[data-ml-basemap]").forEach(b => {
        b.setAttribute("aria-pressed", String(b.getAttribute("data-ml-basemap") === state.basemapMode));
      });
      const tileAvail = !!(pack.tilepack && pack.tilepack.available);
      frame.querySelectorAll('[data-ml-basemap="raster"]').forEach(rasterBtn => {
        rasterBtn.disabled = !tileAvail && state.basemapMode !== "raster";
        rasterBtn.title = tileAvail ? t("geo.basemapRaster") : t("geo.rasterUnavailable");
      });
      const attrib = frame.querySelector("[data-ml-attrib]");
      if (attrib) {
        attrib.textContent = state.basemapMode === "raster" && pack.tilepack && pack.tilepack.attribution
          ? pack.tilepack.attribution
          : "© OpenStreetMap contributors";
      }
    }

    function updateScale() {
      const y = map.getContainer().clientHeight / 2;
      const left = map.unproject([40, y]);
      const right = map.unproject([140, y]);
      const d = haversine(left.lat, left.lng, right.lat, right.lng);
      const txt = host.querySelector("[data-ml-scale-txt]");
      if (txt) txt.textContent = fmtLen(d);
    }

    function mountHud() {
      if (opts.hud === false || host.querySelector("[data-ml-frame]")) return;
      const tileAvail = !!(pack.tilepack && pack.tilepack.available);
      host.insertAdjacentHTML("beforeend", `
        <div class="ml-frame" data-ml-frame>
          <div class="ml-hud">
            <span class="ml-hud-title"><i class="ml-live-dot" aria-hidden="true"></i> ${esc(t("geo.mapRegion"))}</span>
            <div class="ml-basemap-switch" role="group" aria-label="${esc(t("geo.basemap"))}">
              <button type="button" data-ml-basemap="vector" aria-pressed="true">
                <span class="ml-bm-thumb is-vector" aria-hidden="true"></span>${esc(t("geo.basemapVector"))}</button>
              <button type="button" data-ml-basemap="raster" aria-pressed="false"
                ${tileAvail ? "" : "disabled"} title="${esc(tileAvail ? t("geo.basemapRaster") : t("geo.rasterUnavailable"))}">
                <span class="ml-bm-thumb is-raster" aria-hidden="true"></span>${esc(t("geo.basemapRaster"))}</button>
              <button type="button" data-ml-basemap="hybrid" aria-pressed="false">
                <span class="ml-bm-thumb is-hybrid" aria-hidden="true"></span>${esc(t("geo.basemapHybrid"))}</button>
            </div>
            <label class="ml-hybrid-slider" data-ml-hybrid hidden>
              ${esc(t("geo.opacity"))}
              <input type="range" min="15" max="100" value="${Math.round(state.hybridOpacity * 100)}" data-ml-opacity>
            </label>
            <span class="ml-area-pill" data-ml-area-pill hidden>
              <span data-ml-area-txt></span>
              <button type="button" class="ml-chip" data-ml-fit-area>${esc(t("geo.returnToArea"))}</button>
            </span>
            <span class="ml-count-pill" data-ml-count></span>
            <span class="ml-coords-pill" data-ml-coords dir="ltr">—</span>
          </div>
          <div class="ml-tools" role="toolbar" aria-label="${esc(t("desk.tools"))}">
            <button type="button" data-ml-act="in" title="${esc(t("geo.zoomIn") || "+")}">+</button>
            <button type="button" data-ml-act="out" title="${esc(t("geo.zoomOut") || "−")}">−</button>
            <button type="button" data-ml-act="fit" title="${esc(t("desk.fitPoints"))}">⤢</button>
            <button type="button" data-ml-act="area" title="${esc(t("geo.fitWorkingArea"))}">▣</button>
            <div class="ml-tools-sep"></div>
            <button type="button" data-ml-act="add" title="${esc(t("geo.addAtHint"))}">⌖</button>
            <button type="button" data-ml-act="measure" title="${esc(t("geo.measure"))}" aria-pressed="false">⌀</button>
            <button type="button" data-ml-act="layers" title="${esc(t("geo.layers"))}" aria-expanded="false">☰</button>
            <button type="button" data-ml-act="io" title="${esc(t("geo.dataIO"))}" aria-expanded="false">⇅</button>
          </div>
          <div class="ml-popover" data-ml-layers hidden>
            <div class="ml-popover-head">${esc(t("geo.layers"))}
              <button type="button" class="icon-btn" data-ml-close-layers aria-label="${esc(t("common.close"))}">×</button></div>
            <div class="ml-popover-sec">
              <div class="ml-popover-heading">${esc(t("geo.basemap"))}</div>
              <div class="ml-bm-grid">
                <button type="button" data-ml-basemap="vector">${esc(t("geo.basemapVectorShort"))}</button>
                <button type="button" data-ml-basemap="raster">${esc(t("geo.basemapRasterShort"))}</button>
                <button type="button" data-ml-basemap="hybrid">${esc(t("geo.basemapHybridShort"))}</button>
              </div>
            </div>
            <div class="ml-popover-sec">
              <div class="ml-popover-heading">${esc(t("geo.mapLayers"))}</div>
              ${[
                ["roads", "geo.layerRoads"], ["water", "geo.layerWater"], ["green", "geo.layerGreen"],
                ["labels", "geo.layerLabels"], ["area", "geo.layerArea"], ["dimOutside", "geo.layerDim"],
                ["pins", "geo.layerPins"]
              ].map(([k, key]) => `
                <label class="ml-switch"><span>${esc(t(key))}</span>
                  <input type="checkbox" data-ml-layer="${k}" ${state.streetLayers[k] !== false ? "checked" : ""}></label>`).join("")}
            </div>
          </div>
          <div class="ml-popover" data-ml-io hidden>
            <div class="ml-popover-head">${esc(t("geo.dataIO"))}
              <button type="button" class="icon-btn" data-ml-close-io aria-label="${esc(t("common.close"))}">×</button></div>
            <p class="muted small" style="margin:0 0 8px">${esc(t("geo.dataIOHint"))}</p>
            <div class="ml-io-row">
              <button type="button" class="primary" data-ml-export>${esc(t("geo.exportGeoJSON"))}</button>
              <button type="button" data-ml-import>${esc(t("geo.importGeoJSON"))}</button>
              <a class="btn sm" href="/api/geo/offline-pack.zip" download="siraj-offline-map.zip">${esc(t("geo.downloadPack"))}</a>
            </div>
            <input type="file" accept=".json,.geojson,application/geo+json,application/json" data-ml-file hidden>
          </div>
          <div class="ml-measure" data-ml-measure hidden></div>
          <div class="ml-scale"><i data-ml-scale-bar></i><span data-ml-scale-txt>—</span></div>
          <div class="ml-attrib" data-ml-attrib>© OpenStreetMap contributors</div>
        </div>`);

      const frame = host.querySelector("[data-ml-frame]");
      frame.querySelectorAll("[data-ml-basemap]").forEach(b => {
        b.onclick = () => setBasemap(b.getAttribute("data-ml-basemap"));
      });
      const opacity = frame.querySelector("[data-ml-opacity]");
      if (opacity) {
        opacity.oninput = () => {
          state.hybridOpacity = Number(opacity.value) / 100;
          applyHybridOpacity();
          save({ hybridOpacity: state.hybridOpacity });
        };
      }
      frame.querySelector("[data-ml-fit-area]").onclick = fitArea;
      frame.querySelectorAll("[data-ml-layer]").forEach(inp => {
        inp.onchange = () => {
          state.streetLayers[inp.getAttribute("data-ml-layer")] = inp.checked;
          applyLayerVisibility();
          save({ streetLayers: Object.assign({}, state.streetLayers) });
        };
      });

      const layersPop = frame.querySelector("[data-ml-layers]");
      const ioPop = frame.querySelector("[data-ml-io]");
      const closePops = () => {
        layersPop.hidden = true;
        ioPop.hidden = true;
        frame.querySelector('[data-ml-act="layers"]').setAttribute("aria-expanded", "false");
        frame.querySelector('[data-ml-act="io"]').setAttribute("aria-expanded", "false");
      };
      frame.querySelector("[data-ml-close-layers]").onclick = closePops;
      frame.querySelector("[data-ml-close-io]").onclick = closePops;

      frame.querySelectorAll("[data-ml-act]").forEach(btn => {
        btn.onclick = () => {
          const act = btn.getAttribute("data-ml-act");
          if (act === "in") map.zoomIn({ duration: 280 });
          else if (act === "out") map.zoomOut({ duration: 280 });
          else if (act === "fit") { if (opts.onFitPoints) opts.onFitPoints(); }
          else if (act === "area") fitArea();
          else if (act === "add") setPickAdd(!state.pickAdd);
          else if (act === "measure") {
            setMeasure(state.measure.mode === "off" ? "distance" : "off");
          } else if (act === "layers") {
            const open = layersPop.hidden;
            closePops();
            layersPop.hidden = !open;
            btn.setAttribute("aria-expanded", String(open));
          } else if (act === "io") {
            const open = ioPop.hidden;
            closePops();
            ioPop.hidden = !open;
            btn.setAttribute("aria-expanded", String(open));
          }
        };
      });

      frame.querySelector("[data-ml-export]").onclick = async () => {
        try {
          const b = map.getBounds();
          const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(",");
          const fc = await api.get(`/api/map/export.geojson?bbox=${bbox}&limit=5000`);
          const blob = new Blob([JSON.stringify(fc, null, 2)], { type: "application/geo+json" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = "siraj-map-export.geojson";
          a.click();
          URL.revokeObjectURL(a.href);
          toast(t("geo.exported", { n: (fc.features || []).length }), "ok");
        } catch (err) { toast(err.message || String(err), "err"); }
      };
      const file = frame.querySelector("[data-ml-file]");
      frame.querySelector("[data-ml-import]").onclick = () => file.click();
      file.onchange = async () => {
        const f = file.files && file.files[0];
        if (!f) return;
        try {
          const geojson = JSON.parse(await f.text());
          const res = await api.post("/api/map/import.geojson", {
            geojson, reason: "maplib GeoJSON import"
          });
          toast(t("geo.imported", { n: res.created, skip: res.skipped }), "ok", 4000);
          if (opts.onPointsRefresh) await opts.onPointsRefresh();
          closePops();
        } catch (err) { toast(err.message || String(err), "err"); }
        file.value = "";
      };

      refreshHud();
      updateScale();
    }

    /* ----------------------------------------------------------- events --- */
    function onMove() { updateScale(); }
    function onMouseMove(ev) {
      const el = host.querySelector("[data-ml-coords]");
      if (el) el.textContent = `${ev.lngLat.lat.toFixed(5)}, ${ev.lngLat.lng.toFixed(5)}`;
    }
    function onClick(ev) {
      if (state.pickAdd) {
        openCreateAt(ev.lngLat.lat, ev.lngLat.lng);
        return true; /* consumed */
      }
      if (state.measure.mode !== "off") {
        state.measure.points.push({ lat: ev.lngLat.lat, lon: ev.lngLat.lng });
        redrawMeasure();
        return true;
      }
      return false;
    }
    function onContextMenu(ev) {
      ev.preventDefault();
      const ll = map.unproject([ev.offsetX, ev.offsetY]);
      openCreateAt(ll.lat, ll.lng);
    }

    map.on("move", onMove);
    map.on("mousemove", onMouseMove);
    map.getCanvas().addEventListener("contextmenu", onContextMenu);

    if (opts.hud !== false) mountHud();

    function boot() {
      if (pack.vectormap && pack.vectormap.available && opts.autoBoot !== false) {
        setBasemap(state.basemapMode);
      }
    }
    if (map.isStyleLoaded && map.isStyleLoaded()) boot();
    else map.once("load", boot);

    return {
      state,
      syncStreets,
      setBasemap,
      setStreetsOn,
      setMeasure,
      setPickAdd,
      openCreateAt,
      fitArea,
      refreshHud,
      applyLayerVisibility,
      /** @returns {boolean} true if the click was consumed by pick/measure */
      handleClick: onClick,
      isBusy: () => state.pickAdd || state.measure.mode !== "off" || !!state.creatingAt,
      destroy() {
        state.destroyed = true;
        map.off("move", onMove);
        map.off("mousemove", onMouseMove);
        try { map.getCanvas().removeEventListener("contextmenu", onContextMenu); } catch (e) { /* */ }
        A.removeVectormapLayers(map);
        clearAreaChrome();
        const frame = host.querySelector("[data-ml-frame]");
        if (frame) frame.remove();
      }
    };
  };
})(window.App || (window.App = {}));
