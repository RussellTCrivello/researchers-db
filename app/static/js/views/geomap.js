/* ============================================================================
   SIRAJ · views/geomap.js — the geographic workspace
   ----------------------------------------------------------------------------
   A real map, not a picture of one:

     • MapLibre GL (served from /static/vendor, so the map never depends on a CDN)
     • the base layer is the **local** Natural Earth pack by default — country
       polygons, coastlines, lakes and rivers, no network, no third party — with
       OpenStreetMap / CARTO available as configured providers, each carrying the
       attribution and terms its licence requires
     • every marker is a registry record; clicking one opens its geographic
       dossier in the right-hand inspector and can hand over to the record view
     • three zones (records + filters · map · inspector), each side collapsible,
       and the map is told to resize whenever the layout changes
     • distance and area measurement, coordinate entry and validation, DD and
       DMS readouts, CRS awareness, antimeridian-safe viewports, bounded queries
       that say how much they left out

   The workspace keeps its own state small and honest: the viewport and panel
   layout are preferences (localStorage), the provider and limits are settings
   (database), and the map only ever draws what the API returned.
   ========================================================================== */
(function () {
  "use strict";

  const A = window.App;
  const { t, esc, fmtNum, icon, api, toast } = A;

  const R_EARTH = 6371008.8;
  const PANELS_KEY = "map_panels";
  const VIEW_KEY = "map_view";
  const SEL_KEY = "map_selection";

  const LAYER_STYLE = {
    place:       { color: "#8a5a1f", ring: "#f6e7cd", label: "geo.layer.place" },
    person:      { color: "#2f6f4f", ring: "#dff0e6", label: "geo.layer.person" },
    institution: { color: "#1f5d8b", ring: "#dcebf7", label: "geo.layer.institution" },
    event:       { color: "#7b3f8f", ring: "#efe0f5", label: "geo.layer.event" }
  };

  /* one live map per page: navigating away must not leave a WebGL context behind */
  let liveMap = null;
  let mapState = null;

  /**
   * Tear the map down. The router calls this whenever it renders a different view, and
   * the view itself calls it on re-entry. A WebGL context and its event handlers are
   * not garbage-collected while a canvas is attached, and a stale instance must never
   * answer a request that belongs to a newer one.
   */
  A.geoDispose = function geoDispose() {
    if (mapState && typeof mapState._disposePins === "function") {
      try { mapState._disposePins(); } catch (e) { /* */ }
    }
    if (liveMap) {
      try { liveMap.remove(); } catch (e) { /* already removed */ }
      liveMap = null;
    }
    mapState = null;
  };

  /* A documented test seam: the running map and its state. The browser harness uses it
     for the assertions that are about the *map*, not about the DOM (viewport preserved
     across a panel collapse, the selection source, the cluster flag). */
  A.geo = {
    map: () => liveMap,
    state: () => mapState
  };

  /* ---------------------------------------------------------------- maths --- */
  function toRad(d) { return (d * Math.PI) / 180; }

  function haversine(aLat, aLon, bLat, bLon) {
    const dLat = toRad(bLat - aLat);
    let dLon = bLon - aLon;
    while (dLon > 180) dLon -= 360;
    while (dLon < -180) dLon += 360;
    const dLonR = toRad(dLon);
    const h = Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLonR / 2) ** 2;
    return 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function dms(value, isLat, decimals) {
    const d = decimals === undefined ? 1 : decimals;
    const hemi = isLat ? (value >= 0 ? "N" : "S") : (value >= 0 ? "E" : "W");
    let total = Math.abs(value);
    let deg = Math.floor(total);
    let minFloat = (total - deg) * 60;
    let min = Math.floor(minFloat);
    let sec = (minFloat - min) * 60;
    if (Number(sec.toFixed(d)) >= 60) { sec = 0; min += 1; }
    if (min >= 60) { min = 0; deg += 1; }
    return `${deg}°${String(min).padStart(2, "0")}′${sec.toFixed(d).padStart(d ? 3 + d : 2, "0")}″${hemi}`;
  }

  function fmtDistance(metres, units) {
    if (units === "imperial") {
      const feet = metres * 3.280839895;
      return feet >= 5280 ? `${(feet / 5280).toLocaleString(undefined, { maximumFractionDigits: 2 })} mi`
        : `${Math.round(feet).toLocaleString()} ft`;
    }
    return metres >= 1000
      ? `${(metres / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} km`
      : `${Math.round(metres).toLocaleString()} m`;
  }

  function fmtArea(sqm, units) {
    if (units === "imperial") {
      const acres = sqm / 4046.8564224;
      return acres >= 640
        ? `${(acres / 640).toLocaleString(undefined, { maximumFractionDigits: 2 })} mi²`
        : `${acres.toLocaleString(undefined, { maximumFractionDigits: 2 })} ac`;
    }
    if (sqm >= 1e6) return `${(sqm / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 })} km²`;
    if (sqm >= 1e4) return `${(sqm / 1e4).toLocaleString(undefined, { maximumFractionDigits: 2 })} ha`;
    return `${Math.round(sqm).toLocaleString()} m²`;
  }

  function prefNumber(name, settingName, fallback) {
    const raw = A.pref(name, "default");
    const value = raw === "default" ? A.setting(settingName, String(fallback)) : raw;
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  /* the current map preference, resolved personal → instance → fallback */
  function mapPref(prefName, settingName, fallback) {
    return A.resolvePref ? A.resolvePref(prefName, settingName, fallback)
      : A.setting(settingName, fallback);
  }

  function readSavedView() {
    try {
      const raw = localStorage.getItem("siraj." + VIEW_KEY);
      if (!raw) return null;
      const v = JSON.parse(raw);
      if (typeof v.lat === "number" && typeof v.lon === "number" && typeof v.zoom === "number") return v;
    } catch (e) { /* a corrupt preference must never break the map */ }
    return null;
  }

  function saveView(map) {
    const c = map.getCenter();
    try {
      localStorage.setItem("siraj." + VIEW_KEY, JSON.stringify({
        lat: Number(c.lat.toFixed(6)), lon: Number(c.lng.toFixed(6)),
        zoom: Number(map.getZoom().toFixed(2)), bearing: Number(map.getBearing().toFixed(1)),
        pitch: Number(map.getPitch().toFixed(1))
      }));
    } catch (e) { /* private mode: the map still works, it just forgets */ }
  }

  function readPanels() {
    const raw = A.pref(PANELS_KEY, "default");
    if (raw === "default" || raw === "") {
      return { left: window.innerWidth > 900, right: window.innerWidth > 1100 };
    }
    const [l, r] = String(raw).split(",");
    return { left: l !== "0", right: r !== "0" };
  }

  function savePanels(panels) {
    A.setPref(PANELS_KEY, `${panels.left ? 1 : 0},${panels.right ? 1 : 0}`);
  }

  /* ------------------------------------------------------------- geometry --- */
  function geojson(points) {
    return {
      type: "FeatureCollection",
      features: points.map(p => ({
        type: "Feature",
        properties: {
          etype: p.entity_type, id: p.id, code: p.code,
          label: A.state.lang === "ar" ? (p.label_ar || p.label_en) : (p.label_en || p.label_ar),
          lat: p.lat, lon: p.lon, status: p.status || "",
          position: p.position || "precise",
          anchor: A.state.lang === "ar" ? (p.anchor_ar || "") : (p.anchor_en || "")
        },
        geometry: { type: "Point", coordinates: [p.lon, p.lat] }
      }))
    };
  }

  /* ========================================================================== */
  A.views.geomap = async function (root) {
    A.geoDispose();
    A.crumbs([{ label: t("nav.geomap") }]);

    const [conf, layersDoc] = await Promise.all([
      api.get("/api/map/config"), api.get("/api/map/layers")
    ]);
    const saved = readSavedView();
    const initial = saved || conf.initial;

    const state = {
      conf, layers: layersDoc.layers, points: [], perLayer: {}, truncated: false,
      total: 0, selected: null, selectedDoc: null, stack: null, gazetteer: null,
      temp: null, groups: [], groupsMode: "records",
      filters: {
        q: "", status: "", layers: new Set(conf.layers.map(l => l.entity_type)),
        query: "", logic: "and", where: [], auth: "", doc: "",
        relType: "", tagIds: [], warnings: []
      },
      panels: readPanels(),
      measure: { mode: "off", points: [] },
      pickAdd: false,
      streetsOverlay: A.pref("map_streets_overlay", false) === true
        || A.pref("map_streets_overlay", "false") === "true",
      maplib: null,
      providerId: mapPref("map_provider", "map.provider", conf.provider.id),
      units: mapPref("map_units", "map.units", conf.units),
      cluster: String(mapPref("map_cluster", "map.cluster", String(conf.limits.cluster))) === "true",
      labels: String(mapPref("map_labels", "map.show_labels", String(conf.labels))) === "true",
      overlays: String(mapPref("map_overlays", "map.overlays", conf.overlays.join(","))).split(","),
      busy: 0, warn: null, crs: "EPSG:4326", at: { lat: initial.lat, lon: initial.lon }
    };
    mapState = state;
    let geoAdvEl = null;

    /* ------------------------------------------------------------- shell --- */
    root.innerHTML = `
      <div class="geo-workspace${state.panels.left ? "" : " left-off"}${state.panels.right ? "" : " right-off"}"
           id="geoWorkspace">
        <div class="geo-toolbar no-print">
          <button class="btn ghost sm" id="geoLeftToggle" aria-pressed="${state.panels.left}"
                  title="${esc(t("geo.toggleLeft"))}">${icon("panel-left")}<span class="hide-sm">${esc(t("geo.records"))}</span></button>
          <div class="geo-search">
            <span class="geo-search-ico">${icon("search")}</span>
            <input id="geoSearch" type="search" autocomplete="off"
                   placeholder="${esc(t("geo.searchPlaceholder"))}"
                   aria-label="${esc(t("geo.search"))}">
            <div class="geo-search-results" id="geoSearchResults" hidden></div>
          </div>
          <button class="btn ghost sm" id="geoCoordBtn" title="${esc(t("geo.enterCoords"))}">
            ${icon("crosshair")}<span class="hide-sm">${esc(t("geo.coords"))}</span></button>
          <span class="spacer"></span>
          <div class="geo-zoom" role="group" aria-label="${esc(t("geo.zoom"))}">
            <button class="btn ghost sm" id="geoZoomIn" aria-label="${esc(t("geo.zoomIn"))}" title="${esc(t("geo.zoomIn"))}">+</button>
            <button class="btn ghost sm" id="geoZoomOut" aria-label="${esc(t("geo.zoomOut"))}" title="${esc(t("geo.zoomOut"))}">−</button>
            <button class="btn ghost sm" id="geoRotate" aria-label="${esc(t("geo.resetNorth"))}" title="${esc(t("geo.resetNorth"))}">${icon("compass")}</button>
          </div>
          <div class="geo-menu-wrap">
            <button class="btn ghost sm" id="geoLayersBtn" aria-expanded="false"
                    title="${esc(t("geo.layers"))}">${icon("layers")}<span class="hide-sm">${esc(t("geo.layers"))}</span></button>
            <div class="geo-menu" id="geoLayersMenu" hidden>
              <div class="geo-menu-head">${esc(t("geo.basemap"))}</div>
              <div id="geoProviderList" class="geo-provider-list"></div>
              <div class="geo-menu-head">${esc(t("geo.mapLayers"))}</div>
              <div id="geoOverlayList"></div>
            </div>
          </div>
          <div class="geo-menu-wrap">
            <button class="btn ghost sm" id="geoDownloadBtn" aria-expanded="false"
                    title="${esc(t("mapdl.title"))}">${icon("download")}<span class="hide-sm">${esc(t("mapdl.short"))}</span></button>
            <div class="geo-menu geo-download-menu" id="geoDownloadMenu" hidden>
              <div class="geo-menu-head">${esc(t("mapdl.title"))}</div>
              <div id="geoDownloadBody"></div>
            </div>
          </div>
          <div class="geo-menu-wrap">
            <button class="btn ghost sm" id="geoMeasureBtn" aria-expanded="false"
                    title="${esc(t("geo.measure"))}">${icon("ruler")}<span class="hide-sm">${esc(t("geo.measure"))}</span></button>
            <div class="geo-menu" id="geoMeasureMenu" hidden>
              <button class="geo-menu-item" data-measure="distance">${esc(t("geo.measureDistance"))}</button>
              <button class="geo-menu-item" data-measure="area">${esc(t("geo.measureArea"))}</button>
              <button class="geo-menu-item" data-measure="off">${esc(t("geo.measureOff"))}</button>
            </div>
          </div>
          <button class="btn ghost sm" id="geoFitArea" title="${esc(t("geo.fitWorkingArea"))}">
            ${icon("maximize")}<span class="hide-sm">${esc(t("geo.fitArea"))}</span></button>
          <button class="btn ghost sm" id="geoAddAt" title="${esc(t("geo.addAtHint"))}">
            ${icon("plus")}<span class="hide-sm">${esc(t("geo.addPlace"))}</span></button>
          <button class="btn ghost sm" id="geoRightToggle" aria-pressed="${state.panels.right}"
                  title="${esc(t("geo.toggleRight"))}">${icon("panel-right")}<span class="hide-sm">${esc(t("geo.inspector"))}</span></button>
        </div>

        <div class="geo-body">
          <aside class="geo-panel geo-left" id="geoLeft" aria-label="${esc(t("geo.records"))}">
            <div class="geo-panel-head">
              <div class="geo-tabs" role="tablist">
                <button class="geo-tab active" data-panel-tab="records" role="tab"
                        aria-selected="true">${esc(t("geo.tabRecords"))}</button>
                <button class="geo-tab" data-panel-tab="places" role="tab"
                        aria-selected="false">${esc(t("geo.tabPlaces"))}</button>
                <button class="geo-tab" data-panel-tab="filters" role="tab"
                        aria-selected="false">${esc(t("geo.tabFilters"))}</button>
              </div>
              <button class="icon-btn geo-panel-close" data-close="left"
                      aria-label="${esc(t("common.close"))}">✕</button>
            </div>
            <div class="geo-panel-body" id="geoLeftBody"></div>
          </aside>

          <div class="geo-map-wrap">
            <div id="geoMap" class="geo-map" tabindex="0"
                 aria-label="${esc(t("geo.mapRegion"))}" role="application"></div>
            <div class="geo-readout" id="geoReadout" dir="ltr">
              <span id="geoReadoutPos">—</span>
              <button class="geo-crs" id="geoCrsBtn" title="${esc(t("geo.crsHint"))}">${state.crs}</button>
              <span class="geo-zoom-readout" id="geoZoomReadout">z${fmtNum(initial.zoom)}</span>
            </div>
            <div class="geo-legend" id="geoLegend"></div>
            <div class="geo-attribution" id="geoAttribution" dir="auto"></div>
            <div class="geo-banner" id="geoBanner" hidden></div>
            <div class="geo-measure-panel" id="geoMeasurePanel" hidden></div>
            <div class="geo-scale" id="geoScale"></div>
          </div>

          <aside class="geo-panel geo-right" id="geoRight" aria-label="${esc(t("geo.inspector"))}">
            <div class="geo-panel-head">
              <strong>${esc(t("geo.inspector"))}</strong>
              <span class="spacer"></span>
              <button class="icon-btn geo-panel-close" data-close="right"
                      aria-label="${esc(t("common.close"))}">✕</button>
            </div>
            <div class="geo-panel-body" id="geoRightBody"></div>
          </aside>
        </div>
      </div>`;

    A.hydrateIcons ? A.hydrateIcons(root) : null;

    const dom = {
      workspace: root.querySelector("#geoWorkspace"),
      map: root.querySelector("#geoMap"),
      left: root.querySelector("#geoLeft"),
      leftBody: root.querySelector("#geoLeftBody"),
      right: root.querySelector("#geoRight"),
      rightBody: root.querySelector("#geoRightBody"),
      search: root.querySelector("#geoSearch"),
      searchResults: root.querySelector("#geoSearchResults"),
      readout: root.querySelector("#geoReadout"),
      readoutPos: root.querySelector("#geoReadoutPos"),
      zoomReadout: root.querySelector("#geoZoomReadout"),
      legend: root.querySelector("#geoLegend"),
      attribution: root.querySelector("#geoAttribution"),
      banner: root.querySelector("#geoBanner"),
      measurePanel: root.querySelector("#geoMeasurePanel"),
      scale: root.querySelector("#geoScale"),
      layersMenu: root.querySelector("#geoLayersMenu"),
      measureMenu: root.querySelector("#geoMeasureMenu")
    };

    /* ------------------------------------------------------------- the map --- */
    const provider = (state.conf.providers.find(p => p.id === state.providerId) || state.conf.providers[0]);
    state.provider = provider;

    if (!window.maplibregl) {
      dom.map.innerHTML = `<div class="geo-fatal">${esc(t("geo.libraryMissing"))}</div>`;
      return;
    }

    /* the reserved marks travel with the standard; a failure here leaves the
       coloured dots in place rather than costing the reader the map */
    if (A.crce && A.crce.standard) { try { await A.crce.standard(); } catch (e) { /* dots */ } }

    /* Raster styles go through the browse-cache protocol so every viewed tile
       is remembered for offline replay. Local vector styles stay untouched. */
    if (A.tilecache && A.tilecache.installProtocol) A.tilecache.installProtocol();
    const bootStyle = (A.tilecache && A.tilecache.wrapStyle)
      ? A.tilecache.wrapStyle(provider) : provider.style;

    const map = new window.maplibregl.Map({
      container: dom.map,
      style: bootStyle,
      center: [initial.lon, initial.lat],
      zoom: initial.zoom,
      bearing: initial.bearing || 0,
      pitch: initial.pitch || 0,
      maxZoom: 19,
      minZoom: 1,
      attributionControl: false,
      dragRotate: true,
      keyboard: true
    });
    liveMap = map;
    state.map = map;
    /* one handle for the harnesses and for anyone debugging in the console:
       MapLibre layer state is otherwise invisible from outside the module */
    if (typeof window !== "undefined") window.__geoMap = map;
    /* MapLibre fires `move` and `resize` while it is still building the style, so
       nothing that touches sources or layers may run before `load`. One flag, checked
       by every handler that draws — the alternative is a shower of console errors. */
    let ready = false;

    /* the two-finger / right-drag rotation and the pitch the requirement asks for */
    map.addControl(new window.maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }),
      "bottom-left");

    /* --------------------------------------------------- basemap + layers --- */
    const LOCAL_SOURCES = ["countries", "admin_1", "urban", "lakes", "coastline", "rivers", "places"];

    function wantBasemap() {
      const k = state.provider.kind;
      return k === "vector-local" || k === "hybrid-streets";
    }
    function streetsBeforeId() {
      return map.getLayer("geo-clusters") ? "geo-clusters"
        : (map.getLayer("geo-points") ? "geo-points" : null);
    }

    async function syncStreets(opts) {
      if (!ready || !state.maplib) return;
      const pack = state.conf.offline_pack || {};
      const avail = !!(pack.vectormap && pack.vectormap.available);
      const kind = state.provider && state.provider.kind;
      const asBasemap = kind === "vector-streets" || kind === "hybrid-streets";
      const want = asBasemap || (avail && state.streetsOverlay);
      state.maplib.state.streetsOn = !!want;
      if (asBasemap) state.maplib.state.basemapMode = kind === "hybrid-streets" ? "hybrid" : "vector";
      else if (want) state.maplib.state.basemapMode = "overlay";
      await state.maplib.syncStreets(Object.assign({
        fit: asBasemap && !(opts && opts.fit === false),
        beforeId: streetsBeforeId()
      }, opts || {}));
    }

    function attachMapLib() {
      if (!A.maplib || state.maplib) return;
      const host = root.querySelector("#geoMap")
        || root.querySelector("[data-geo-map]")
        || map.getContainer();
      state.maplib = A.maplib({
        map,
        host,
        conf: state.conf,
        hud: false,
        autoBoot: false,
        prefs: {
          basemapMode: state.provider.kind === "hybrid-streets" ? "hybrid"
            : (state.provider.kind === "vector-streets" ? "vector" : "overlay"),
          streets: !!(state.streetsOverlay
            || state.provider.kind === "vector-streets"
            || state.provider.kind === "hybrid-streets")
        },
        pickingRoot: root,
        composerHost: (at) => {
          ensureRight();
          const lat = at && at.lat != null ? at.lat : (state.at && state.at.lat);
          const lon = at && at.lon != null ? at.lon : (state.at && state.at.lon);
          state.creatingAt = { lat, lon };
          dropTemp(lat, lon);
          let slot = dom.rightBody.querySelector("[data-geo-composer]");
          if (!slot) {
            slot = document.createElement("div");
            slot.className = "geo-composer";
            slot.dataset.geoComposer = "1";
            dom.rightBody.appendChild(slot);
          }
          return slot;
        },
        onCreateCancel: () => { state.creatingAt = null; },
        onPlaceSaved: async (rec, at) => {
          state.creatingAt = null;
          clearTemp();
          await loadFeatures();
          if (rec && rec.type && rec.id) {
            selectFeature({
              entity_type: rec.type, id: rec.id,
              lat: at.lat, lon: at.lon
            }, { fly: true });
          }
        },
        onPointsRefresh: () => loadFeatures(),
        onMeasure: ({ length, area, mode, points }) => {
          if (!dom.measurePanel) return;
          state.measure.mode = mode;
          state.measure.points = (points || []).slice();
          if (mode === "off") { dom.measurePanel.hidden = true; return; }
          dom.measurePanel.hidden = false;
          dom.measurePanel.innerHTML = `
            <div class="geo-measure-head">
              <strong>${esc(t(mode === "area" ? "geo.measureArea" : "geo.measureDistance"))}</strong>
              <button class="icon-btn" id="geoMeasureClear" aria-label="${esc(t("geo.measureClear"))}">✕</button>
            </div>
            <div class="geo-measure-body" dir="ltr">
              <div>${esc(fmtDistance(length, state.units))}</div>
              ${mode === "area" && points.length >= 3
                ? `<div>${esc(fmtArea(area, state.units))}</div>` : ""}
              <div class="small muted">${points.length}</div>
            </div>
            <div class="small muted">${esc(t("geo.measureHint"))}</div>`;
          const clr = dom.measurePanel.querySelector("#geoMeasureClear");
          if (clr) clr.onclick = () => { if (state.maplib) state.maplib.setMeasure(mode); };
        },
        onStyleChange: ({ provider, after }) => {
          if (!provider) { if (after) after(); return; }
          state.provider = provider;
          map.setStyle(provider.style);
          map.once("styledata", () => {
            addOverlayLayers();
            addBasemapLayers();
            if (after) after();
          });
        }
      });
    }

    const RECORD_LAYER_IDS = [
      "geo-clusters", "geo-cluster-ring", "geo-crce-clusters",
      "geo-bloom", "geo-halo", "geo-points", "geo-crce",
      "geo-selection-ring", "geo-selection-pulse", "geo-temp-ring"
    ];
    const RECORD_SOURCE_IDS = ["records", "selection", "temp"];

    function clearRecordLayers() {
      stopSelectionPulse();
      RECORD_LAYER_IDS.forEach(id => {
        if (map.getLayer(id)) map.removeLayer(id);
      });
      RECORD_SOURCE_IDS.forEach(id => {
        if (map.getSource(id)) map.removeSource(id);
      });
    }

    const etypeColor = [
      "match", ["get", "etype"],
      "place", LAYER_STYLE.place.color,
      "person", LAYER_STYLE.person.color,
      "institution", LAYER_STYLE.institution.color,
      "event", LAYER_STYLE.event.color, "#44505a"
    ];
    /* majority category inside a cluster — drives ring tint + glyph choice */
    const clusterMajor = [
      "case",
      ["all",
        [">=", ["get", "n_person"], ["get", "n_institution"]],
        [">=", ["get", "n_person"], ["get", "n_place"]],
        [">=", ["get", "n_person"], ["get", "n_event"]]], "person",
      ["all",
        [">=", ["get", "n_institution"], ["get", "n_place"]],
        [">=", ["get", "n_institution"], ["get", "n_event"]]], "institution",
      [">=", ["get", "n_place"], ["get", "n_event"]], "place",
      "event"
    ];
    const clusterColor = [
      "match", clusterMajor,
      "person", LAYER_STYLE.person.color,
      "institution", LAYER_STYLE.institution.color,
      "place", LAYER_STYLE.place.color,
      "event", LAYER_STYLE.event.color, "#33383d"
    ];

    function addOverlayLayers() {
      /* record markers: one clustered source. Bounded by the API, so the browser
         never receives more than `map.max_points` features. */
      if (!map.getSource("records")) {
        map.addSource("records", {
          type: "geojson", data: geojson([]),
          cluster: state.cluster, clusterRadius: 52, clusterMaxZoom: 9,
          clusterProperties: {
            n_person: ["+", ["case", ["==", ["get", "etype"], "person"], 1, 0]],
            n_institution: ["+", ["case", ["==", ["get", "etype"], "institution"], 1, 0]],
            n_place: ["+", ["case", ["==", ["get", "etype"], "place"], 1, 0]],
            n_event: ["+", ["case", ["==", ["get", "etype"], "event"], 1, 0]]
          }
        });
      }
      if (!map.getSource("selection")) {
        map.addSource("selection", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      }
      if (!map.getSource("temp")) {
        map.addSource("temp", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      }
      if (!map.getLayer("geo-clusters")) {
        /* Atmosphere disc — soft tint by majority category, land stays readable. */
        map.addLayer({
          id: "geo-clusters", type: "circle", source: "records",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": clusterColor,
            "circle-opacity": 0.32,
            "circle-radius": ["step", ["get", "point_count"], 18, 10, 22, 50, 26, 200, 32],
            "circle-blur": 0.4
          }
        });
        map.addLayer({
          id: "geo-cluster-ring", type: "circle", source: "records",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "rgba(0,0,0,0)",
            "circle-radius": ["step", ["get", "point_count"], 13, 10, 16, 50, 19, 200, 23],
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 2,
            "circle-stroke-opacity": 0.95
          }
        });
        /* Far bloom — atmospheric colour so marks announce presence before geometry reads. */
        map.addLayer({
          id: "geo-bloom", type: "circle", source: "records",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-color": etypeColor,
            "circle-opacity": ["interpolate", ["linear"], ["zoom"], 3, 0.14, 8, 0.2, 14, 0.12],
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 11, 8, 16, 14, 22],
            "circle-blur": 0.85
          }
        });
        /* Near halo — tighter disc under the glyph. */
        map.addLayer({
          id: "geo-halo", type: "circle", source: "records",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-color": etypeColor,
            "circle-opacity": ["interpolate", ["linear"], ["zoom"], 3, 0.22, 8, 0.32, 14, 0.26],
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 6, 8, 9, 14, 13],
            "circle-blur": 0.35
          }
        });
        /* Fallback pin (always present): crisp disc. Dimmed once glyphs load.
           An "associated" point stands at a linked place, not at the record's
           own position — it renders dimmer with a wider ring, so nobody reads
           the place's coordinates as the record's. */
        map.addLayer({
          id: "geo-points", type: "circle", source: "records",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 3.2, 8, 5.2, 14, 7],
            "circle-color": etypeColor,
            "circle-stroke-color": "#fff",
            "circle-stroke-width": ["case", ["==", ["get", "position"], "associated"], 2.4, 1.5],
            "circle-opacity": ["case", ["==", ["get", "position"], "associated"], 0.5, 0.95]
          }
        });
        map.addLayer({
          id: "geo-selection-ring", type: "circle", source: "selection",
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 14, 12, 20],
            "circle-color": "rgba(201,162,39,0.16)",
            "circle-stroke-color": "#c9a227",
            "circle-stroke-width": 2.4,
            "circle-pitch-alignment": "map"
          }
        });
        map.addLayer({
          id: "geo-selection-pulse", type: "circle", source: "selection",
          paint: {
            "circle-radius": 18,
            "circle-color": "rgba(201,162,39,0)",
            "circle-stroke-color": "#c9a227",
            "circle-stroke-width": 1.6,
            "circle-stroke-opacity": 0.55,
            "circle-pitch-alignment": "map"
          }
        });
        map.addLayer({
          id: "geo-temp-ring", type: "circle", source: "temp",
          paint: { "circle-radius": 13, "circle-color": "rgba(179,38,30,0.14)",
                   "circle-stroke-color": "#b3261e", "circle-stroke-width": 2 }
        });
      }
      ensureCrceLayers();
      addOverlays();
    }


    /* ─────────────────────── reserved + companion marks on the map ─────────
       Glyphs are registered once the style is ready. Until then the halo+disc
       stack is a complete map. When glyphs arrive, discs step back so the mark
       becomes the reading. A symbol layer that points at a missing image draws
       nothing — so we only add those layers after registration reports true. */
    let crceTried = 0;
    function ensureCrceLayers() {
      if (!ready || !A.crce || !A.crce.registerMapIcons) return;
      if (map.getLayer("geo-crce") && map.getLayer("geo-crce-clusters")) return;
      if (crceTried > 4) return;
      crceTried++;
      A.crce.registerMapIcons(map, 48).then(ok => {
        if (!ready || !liveMap) return;
        if (!ok) {
          ["geo-crce", "geo-crce-clusters"].forEach(id => {
            if (map.getLayer(id)) map.removeLayer(id);
          });
          if (map.getLayer("geo-points")) {
            map.setPaintProperty("geo-points", "circle-opacity", 0.95);
          }
          return;
        }
        if (!map.getLayer("geo-crce")) {
          map.addLayer({
            id: "geo-crce", type: "symbol", source: "records",
            minzoom: 2.5,
            filter: ["all",
              ["!", ["has", "point_count"]],
              ["in", ["get", "etype"],
                ["literal", ["person", "institution", "place", "event"]]]],
            layout: {
              "icon-image": A.crce.iconExpression(),
              "icon-size": ["interpolate", ["linear"], ["zoom"],
                3, 0.55, 6, 0.82, 10, 1.05, 14, 1.25],
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
              "icon-anchor": "center",
              "icon-padding": 2
            },
            paint: {
              "icon-opacity": ["interpolate", ["linear"], ["zoom"], 2.5, 0.92, 6, 1]
            }
          }, map.getLayer("geo-selection-ring") ? "geo-selection-ring" : undefined);
        }
        if (!map.getLayer("geo-crce-clusters")) {
          map.addLayer({
            id: "geo-crce-clusters", type: "symbol", source: "records",
            filter: ["has", "point_count"],
            layout: {
              "icon-image": ["match", clusterMajor,
                "person", "crce-person",
                "institution", "crce-organization",
                "place", "crce-place",
                "event", "siraj-event",
                "crce-place"],
              "icon-size": ["interpolate", ["linear"], ["get", "point_count"],
                1, 0.62, 25, 0.78, 200, 0.95, 1500, 1.1],
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
              "icon-anchor": "center"
            }
          }, map.getLayer("geo-selection-ring") ? "geo-selection-ring" : undefined);
        }
        /* Glyphs carry the reading — discs become quiet anchors under them. */
        if (map.getLayer("geo-points")) {
          map.setPaintProperty("geo-points", "circle-opacity", 0.2);
          map.setPaintProperty("geo-points", "circle-radius",
            ["interpolate", ["linear"], ["zoom"], 3, 2, 8, 2.6, 14, 3.2]);
          map.setPaintProperty("geo-points", "circle-stroke-width", 0.8);
        }
        renderLabels();
        renderLegend();
      }).catch(() => { /* halo + disc remain a complete map */ });
    }

    function addOverlays() {
      if (!ready) return;
      /* relationship arcs and the place tree, straight from the API */
      const wanted = state.overlays.filter(Boolean);
      if (!wanted.length) {
        ["relationships", "place_hierarchy"].forEach(id => {
          if (map.getLayer("geo-" + id)) map.removeLayer("geo-" + id);
          if (map.getSource("geo-" + id)) map.removeSource("geo-" + id);
        });
        return;
      }
      api.get(`/api/map/overlays?layers=${encodeURIComponent(wanted.join(","))}`).then(data => {
        if (!liveMap || mapState !== state) return;
        /* arcs are a regional overlay: they are information when the whole country fits
           on screen and clutter when you are looking at one street, so their weight
           falls away with zoom instead of being switched off behind your back */
        const paint = {
          relationships: {
            "line-color": "#4b5563",
            "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.9, 12, 0.4],
            "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.45, 9, 0.22, 13, 0.1]
          },
          place_hierarchy: {
            "line-color": "#8a5a1f",
            "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 12, 0.6],
            "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.6, 13, 0.25],
            "line-dasharray": [1, 1.4]
          }
        };
        Object.entries(data.overlays).forEach(([id, fc]) => {
          if (!map.getSource("geo-" + id)) {
            map.addSource("geo-" + id, { type: "geojson", data: fc });
          } else {
            map.getSource("geo-" + id).setData(fc);
          }
          if (!map.getLayer("geo-" + id)) {
            /* below the markers, above the basemap */
            const firstMarker = map.getLayer("geo-clusters") ? "geo-clusters" : undefined;
            map.addLayer({ id: "geo-" + id, type: "line", source: "geo-" + id,
                           paint: paint[id] || {} }, firstMarker);
          }
        });
      }).catch(() => { /* an overlay is optional: its absence must not break the map */ });
    }

    let basemapKey = "";
    function addBasemapLayers() {
      if (!ready) return;
      if (!wantBasemap()) {
        LOCAL_SOURCES.forEach(id => {
          if (map.getLayer("base-" + id)) map.removeLayer("base-" + id);
          if (map.getSource("base-" + id)) map.removeSource("base-" + id);
        });
        return;
      }
      const zoom = map.getZoom();
      const b = map.getBounds();
      /* two decimals is ~1 km at the equator: enough for a basemap window, and it stops
         a one-pixel pan from re-fetching four layers */
      const bbox = `${b.getWest().toFixed(2)},${b.getSouth().toFixed(2)},` +
                   `${b.getEast().toFixed(2)},${b.getNorth().toFixed(2)}`;
      const key = `${zoom.toFixed(2)}|${bbox}`;
      if (key === basemapKey) return;
      basemapKey = key;
      const style = {
        countries: [
          { id: "base-countries", type: "fill", source: "base-countries",
            paint: { "fill-color": "#f6f8fb", "fill-opacity": 0.95 } },
          { id: "base-countries-line", type: "line", source: "base-countries",
            paint: { "line-color": "#b9c6d2", "line-width": 0.8 } }
        ],
        admin_1: [{ id: "base-admin_1", type: "line", source: "base-admin_1", minzoom: 4,
                    paint: { "line-color": "#c9b896", "line-width": 0.7,
                             "line-dasharray": [2, 2] } }],
        urban: [{ id: "base-urban", type: "fill", source: "base-urban",
                  paint: { "fill-color": "#e8e0d4", "fill-opacity": 0.85 } }],
        lakes: [{ id: "base-lakes", type: "fill", source: "base-lakes",
                  paint: { "fill-color": "#cfe3f2" } }],
        coastline: [{ id: "base-coastline", type: "line", source: "base-coastline",
                      paint: { "line-color": "#8fa3b5", "line-width": 0.9 } }],
        rivers: [{ id: "base-rivers", type: "line", source: "base-rivers",
                   paint: { "line-color": "#bcd7ea", "line-width": 0.8 } }],
        places: [{ id: "base-places", type: "circle", source: "base-places",
                   paint: { "circle-radius": 2.4, "circle-color": "#65798c",
                            "circle-opacity": 0.75,
                            "circle-stroke-color": "#ffffff", "circle-stroke-width": 0.6 } }]
      };
      LOCAL_SOURCES.forEach(layer => {
        const url = `/api/geo/basemap/${layer}?zoom=${zoom.toFixed(2)}&bbox=${bbox}&limit=800`;
        fetch(url).then(r => (r.ok ? r.json() : null)).then(doc => {
          if (!doc || !liveMap || mapState !== state) return;
          const fc = doc.collection;
          if (layer === "places") {
            state.baseCities = (fc.features || []).map(f => ({
              lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1],
              name_en: f.properties.name_en, name_ar: f.properties.name_ar,
              population: f.properties.population || 0
            })).filter(c => c.name_en || c.name_ar);
            renderLabels();
          }
          if (!map.getSource("base-" + layer)) {
            map.addSource("base-" + layer, { type: "geojson", data: fc });
            /* basemap goes underneath everything the registry draws */
            style[layer].forEach(l => { if (!map.getLayer(l.id)) map.addLayer(l); });
            const marker = map.getLayer("geo-clusters") ? "geo-clusters" : undefined;
            style[layer].forEach(l => { if (map.getLayer(l.id)) map.moveLayer(l.id, marker); });
          } else {
            map.getSource("base-" + layer).setData(fc);
          }
        }).catch(() => { /* a missing basemap layer is a blank area, not an error */ });
      });
    }

    function applyProvider(id, { remember = true } = {}) {
      const next = state.conf.providers.find(p => p.id === id) || state.conf.providers[0];
      state.provider = next;
      state.providerId = next.id;
      if (remember) A.setPref("map_provider", next.id);
      const nextStyle = (A.tilecache && A.tilecache.wrapStyle)
        ? A.tilecache.wrapStyle(next) : next.style;
      map.setStyle(nextStyle);
      renderAttribution();
      dom.banner.hidden = true;
      state.warn = null;
      map.once("styledata", () => {
        crceTried = 0;                 // a new style has no images in it
        addOverlayLayers();
        addBasemapLayers();
        syncStreets({ fit: state.provider.kind === "vector-streets" });
        pushFeatures();
        renderPins();
      });
    }

    /* --------------------------------------------------------- attribution --- */
    function renderAttribution() {
      const p = state.provider;
      const lang = A.state.lang;
      const text = lang === "ar" ? p.attribution_ar : p.attribution_en;
      const usage = lang === "ar" ? p.usage_ar : p.usage_en;
      dom.attribution.innerHTML =
        `<a href="${esc(p.attribution_url)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>
         <span class="geo-attr-sep">·</span>
         <a href="${esc(p.terms_url)}" target="_blank" rel="noopener noreferrer"
            title="${esc(usage)}">${esc(p.license)}</a>`;
    }

    /* --------------------------------------------------------------- data --- */
    function currentBbox() {
      const b = map.getBounds();
      return `${b.getWest().toFixed(5)},${b.getSouth().toFixed(5)},${b.getEast().toFixed(5)},${b.getNorth().toFixed(5)}`;
    }

    function filtersJson() {
      if (A.mapFilters) return A.mapFilters.toPayload(state.filters);
      const out = {};
      if (state.filters.q) out.q = state.filters.q;
      if (state.filters.status) out.status_ids = [Number(state.filters.status)];
      return out;
    }

    function advCount() {
      return A.mapFilters ? A.mapFilters.activeCount(state.filters) : 0;
    }

    /** Read the classic text / status / layer controls, then reload. The field
     *  filters already live on `state.filters` and travel in the same request. */
    function applyGeoFilters() {
      const qEl = dom.leftBody.querySelector("#geoFilterQ");
      const stEl = dom.leftBody.querySelector("#geoFilterStatus");
      if (qEl) state.filters.q = qEl.value.trim();
      if (stEl) state.filters.status = stEl.value;
      const boxes = dom.leftBody.querySelectorAll("[data-layer]");
      if (boxes.length) {
        state.filters.layers = new Set(Array.from(boxes).filter(el => el.checked).map(el => el.dataset.layer));
      }
      loadFeatures(true);
    }

    let fetchToken = 0;
    let lastRequest = "";
    async function loadFeatures(force = false) {
      const layersParam = Array.from(state.filters.layers).join(",");
      /* the same window asked for twice (resize + moveend both fire on a layout change)
         is answered from the copy already on screen */
      const signature = `${currentBbox()}|${map.getZoom().toFixed(2)}|${layersParam}` +
        `|${JSON.stringify(filtersJson())}`;
      if (!force && signature === lastRequest) return;
      lastRequest = signature;
      const token = ++fetchToken;
      state.busy += 1;
      try {
        const [data, groups] = await Promise.all([
          api.get(`/api/map/features?bbox=${currentBbox()}&zoom=${map.getZoom().toFixed(2)}` +
                  `&layers=${encodeURIComponent(layersParam)}` +
                  `&filters=${encodeURIComponent(JSON.stringify(filtersJson()))}`),
          api.get(`/api/map/groups?bbox=${currentBbox()}&zoom=${map.getZoom().toFixed(2)}` +
                  `&layers=${encodeURIComponent(layersParam)}` +
                  `&filters=${encodeURIComponent(JSON.stringify(filtersJson()))}&limit=80`)
        ]);
        /* a slow response must never overwrite a newer one */
        if (token !== fetchToken || mapState !== state) return;
        state.points = data.points;
        state.perLayer = data.per_layer || {};
        state.truncated = data.truncated;
        state.filters.warnings = data.warnings || [];
        state.total = Object.values(state.perLayer).reduce((a, l) => a + (l.total || 0), 0);
        state.groups = groups.groups || [];
        state.groupStats = groups;
        pushFeatures();
        renderLeft();
        if (geoAdvEl && geoAdvEl._mf) geoAdvEl._mf.setWarnings(state.filters.warnings || []);
        renderLegend();
        /* cluster pies + bubble pins need a pass after the source updates */
        requestAnimationFrame(() => {
          if (liveMap && mapState === state) {
            renderLabels();
            renderPins();
          }
        });
        updateScale();
      } catch (err) {
        if (token === fetchToken) {
          state.warn = err.message || t("geo.loadFailed");
          showBanner(state.warn, true);
        }
      } finally {
        state.busy -= 1;
      }
    }

    function pushFeatures() {
      if (!ready) return;
      const src = map.getSource("records");
      if (src) src.setData(geojson(state.points));
    }

    /* ------------------------------------------------------------- banners --- */
    function showBanner(message, fallbackOffered) {
      dom.banner.hidden = false;
      dom.banner.innerHTML = `<span>${esc(message)}</span>
        ${fallbackOffered ? `<button class="btn sm" id="geoUseLocal">${esc(t("geo.useOfflineBasemap"))}</button>` : ""}
        <button class="icon-btn" id="geoBannerClose" aria-label="${esc(t("common.close"))}">✕</button>`;
      const local = dom.banner.querySelector("#geoUseLocal");
      if (local) local.onclick = () => applyProvider("local");
      dom.banner.querySelector("#geoBannerClose").onclick = () => { dom.banner.hidden = true; };
    }

    /* tile / network failures: a recoverable state, never a dead canvas */
    map.on("error", (e) => {
      const msg = String((e && e.error && e.error.message) || e || "");
      if (!/Failed to fetch|NetworkError|tile|ajax|load/i.test(msg)) return;
      if (!state.provider.requires_network) return;
      if (state.warn) return;                      // one banner, not a storm of them
      state.warn = t("geo.tilesUnavailable", { provider: state.provider.label_en });
      showBanner(state.warn, true);
    });

    /* ---------------------------------------------------------- interaction --- */
    map.on("load", () => {
      ready = true;
      addOverlayLayers();
      addBasemapLayers();
      attachMapLib();
      syncStreets({ fit: state.provider.kind === "vector-streets" });
      renderAttribution();
      loadFeatures();
      /* warm the CRCE standard so legend / list marks paint without a second pass */
      if (A.crce && A.crce.standard) {
        A.crce.standard().then(() => {
          if (liveMap && mapState === state) {
            renderLegend();
            if (leftTab === "records") renderLeft();
          }
        }).catch(() => {});
      }
      /* restore a selection from a previous visit (or from a link) */
      const params2 = (A.state.route && A.state.route.params) || {};
      const remembered = params2.sel || A.pref(SEL_KEY, "default");
      if (remembered && remembered !== "default" && remembered.includes(":")) {
        const [etype, id] = remembered.split(":");
        selectFeature({ entity_type: etype, id: Number(id) }, { fly: false, open: false });
      } else {
        renderRight();
      }
    });

    /* Right-click create-at is owned by A.maplib (attached on load). */

    let moveTimer = null;
    map.on("move", () => {
      dom.zoomReadout.textContent = "z" + map.getZoom().toFixed(1);
      if (!ready) return;
      updateScale();
    });
    map.on("moveend", () => {
      saveView(map);
      addBasemapLayers();
      clearTimeout(moveTimer);
      moveTimer = setTimeout(loadFeatures, 240);
      renderLabels();
    });
    map.on("zoomend", () => renderLabels());
    map.on("rotate", () => renderLabels());
    map.on("pitch", () => renderLabels());

    map.on("mousemove", (e) => {
      const { lat, lng } = e.lngLat;
      state.at = { lat, lon: lng };
      dom.readoutPos.textContent = state.crs === "EPSG:3857"
        ? `${(lng * 20037508.34 / 180).toFixed(0)} , ` +
          `${(Math.log(Math.tan((90 + lat) * Math.PI / 360)) * R_EARTH).toFixed(0)} m`
        : `${lat.toFixed(5)}, ${lng.toFixed(5)}   ${dms(lat, true)} ${dms(lng, false)}`;
    });
    map.on("mouseout", () => { dom.readoutPos.textContent = "—"; });

    /* click on a marker, a cluster, or nothing at all */
    map.on("click", (e) => {
      if (state.maplib && state.maplib.handleClick(e)) return;
      const clusterLayers = ["geo-clusters", "geo-cluster-ring", "geo-crce-clusters"]
        .filter(id => map.getLayer(id));
      const clusterHit = clusterLayers.length
        ? map.queryRenderedFeatures(e.point, { layers: clusterLayers }) : [];
      if (clusterHit.length) {
        const f = clusterHit[0];
        openCluster(f);
        return;
      }
      const pointHit = map.queryRenderedFeatures(e.point,
        { layers: ["geo-bloom", "geo-halo", "geo-points", "geo-crce"].filter(id => map.getLayer(id)) });
      if (pointHit.length) {
        /* Every record drawn under the cursor, not only the topmost one: overlapping
           records are common (a dozen people born in the same town), and a click that
           silently picks one of them hides the other eleven. */
        const seen = new Set();
        const stack = [];
        for (const f of pointHit) {
          const pr = f.properties || {};
          const key = `${pr.etype}:${pr.id}`;
          if (seen.has(key)) continue;
          seen.add(key);
          stack.push({ entity_type: pr.etype, id: Number(pr.id), code: pr.code,
                       label: pr.label, status: pr.status,
                       lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] });
        }
        const top = stack[0];
        selectFeature({ entity_type: top.entity_type, id: top.id,
                        lat: e.lngLat.lat, lon: e.lngLat.lng }, { stack });
        return;
      }
      /* a printed base-map place — a gazetteer city rather than a registry record */
      const cityHit = map.queryRenderedFeatures(e.point, { layers: ["base-places"] });
      if (cityHit.length) {
        openGazetteer(cityHit[0].geometry.coordinates[1],
                      cityHit[0].geometry.coordinates[0], cityHit[0].properties || {});
        return;
      }
      /* a click on empty space is a *temporary* position: it is never stored */
      dropTemp(e.lngLat.lat, e.lngLat.lng);
    });

    /**
     * Open a cluster: zoom until it splits, and say what is inside it while doing so.
     * A click that does nothing is the classic map failure, so even the last level —
     * where the markers can no longer be separated — leaves an explanation on screen.
     */
    function openCluster(feature) {
      const src = map.getSource("records");
      const count = feature.properties.point_count || 0;
      if (!src || !src.getClusterExpansionZoom) return;
      const done = (zoom) => {
        if (!Number.isFinite(zoom)) return;
        map.easeTo({ center: feature.geometry.coordinates,
                     zoom: Math.min(zoom + 0.2, 18), duration: 500 });
      };
      try {
        const res = src.getClusterExpansionZoom(feature.properties.cluster_id);
        if (res && typeof res.then === "function") res.then(done).catch(() => {});
        else done(res);
      } catch (e) {
        /* a cluster at the last zoom level has no expansion: drop a temporary point so
           the researcher still learns how many records are there */
        if (count) dropTemp(feature.geometry.coordinates[1], feature.geometry.coordinates[0]);
      }
    }

    map.on("mousemove", (e) => {
      if (state.maplib && state.maplib.isBusy()) {
        map.getCanvas().style.cursor = "crosshair"; return;
      }
      const hit = map.queryRenderedFeatures(e.point,
        { layers: ["geo-points", "geo-clusters", "base-places"] });
      map.getCanvas().style.cursor = hit.length ? "pointer" : "";
    });

    function selectionGeoJSON(lat, lon) {
      return { type: "FeatureCollection", features: lat == null ? [] : [{
        type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon, lat] }
      }] };
    }

    let selectionPulseRaf = 0;
    function stopSelectionPulse() {
      if (selectionPulseRaf) {
        cancelAnimationFrame(selectionPulseRaf);
        selectionPulseRaf = 0;
      }
    }
    function startSelectionPulse() {
      stopSelectionPulse();
      if (!map.getLayer("geo-selection-pulse")) return;
      const t0 = performance.now();
      const tick = (now) => {
        if (!ready || !liveMap || !map.getLayer("geo-selection-pulse")) {
          selectionPulseRaf = 0;
          return;
        }
        const phase = ((now - t0) % 1800) / 1800;
        const r = 14 + phase * 18;
        const opacity = 0.55 * (1 - phase);
        try {
          map.setPaintProperty("geo-selection-pulse", "circle-radius", r);
          map.setPaintProperty("geo-selection-pulse", "circle-stroke-opacity", opacity);
        } catch (e) { /* style mid-swap */ }
        selectionPulseRaf = requestAnimationFrame(tick);
      };
      selectionPulseRaf = requestAnimationFrame(tick);
    }

    let selectionPin = null;
    let recordPins = [];

    function clearSelectionPin() {
      if (selectionPin) {
        try { selectionPin.remove(); } catch (e) { /* */ }
        selectionPin = null;
      }
    }

    function clearRecordPins() {
      recordPins.forEach(m => { try { m.remove(); } catch (e) { /* */ } });
      recordPins = [];
    }

    state._disposePins = function () {
      clearSelectionPin();
      clearRecordPins();
      stopSelectionPulse();
    };

    function placeSelectionPin(lat, lon, meta) {
      clearSelectionPin();
      if (lat == null || !A.geopin) return;
      const m = meta || {};
      const label = m.label || "";
      const etype = m.etype || (state.selected && state.selected.entity_type) || "place";
      /* Reference design: initial letter on black disc, coloured ring, pill label. */
      selectionPin = A.geopin.marker(map, [lon, lat], {
        etype, label, selected: true, size: "lg",
        showLabel: !!label,
        thumb: m.thumb || undefined,
        initial: m.initial || undefined
      });
      if (selectionPin && selectionPin.getElement()) {
        selectionPin.getElement().onclick = (ev) => {
          ev.stopPropagation();
          if (state.selected) selectFeature(state.selected, { fly: true });
        };
      }
    }

    function markSelection(lat, lon, meta) {
      if (!ready) return;
      const src = map.getSource("selection");
      if (src) src.setData(selectionGeoJSON(lat, lon));
      if (lat == null) {
        stopSelectionPulse();
        clearSelectionPin();
      } else {
        startSelectionPulse();
        placeSelectionPin(lat, lon, meta);
      }
    }

    /** HTML bubble pins for every unclustered record in view — always visible. */
    function renderPins() {
      if (!ready || !A.geopin) return;
      clearRecordPins();
      const zoom = map.getZoom();
      /* Clusters own the far overview; bubble pins take over from reading zoom. */
      if (state.cluster && zoom < 9.05) return;
      const selectedKey = state.selected
        ? `${state.selected.entity_type}:${state.selected.id}` : "";
      const budget = 180;
      const candidates = state.points.slice(0, budget);
      for (const p of candidates) {
        const key = `${p.entity_type}:${p.id}`;
        if (key === selectedKey) continue;   /* selection pin already draws this one */
        const label = A.state.lang === "ar"
          ? (p.label_ar || p.label_en) : (p.label_en || p.label_ar);
        const m = A.geopin.marker(map, [p.lon, p.lat], {
          etype: p.entity_type,
          label,
          size: zoom >= 13 ? "md" : "sm",
          showLabel: state.labels && zoom >= 12
        });
        if (!m) continue;
        const el = m.getElement();
        if (el) {
          el.onclick = (ev) => {
            ev.stopPropagation();
            selectFeature(p, { fly: false });
          };
        }
        recordPins.push(m);
      }
    }

    function dropTemp(lat, lon) {
      ensureRight();
      state.temp = { lat, lon };
      const src = ready ? map.getSource("temp") : null;
      if (src) src.setData(selectionGeoJSON(lat, lon));
      markSelection(null, null);
      state.selected = null;
      renderRight({ temp: state.temp });
      renderLeft();
      /* what is here? the local basemap and the nearest registry place answer */
      api.get(`/api/map/reverse?lat=${lat}&lon=${lon}`).then(doc => {
        if (mapState !== state || !state.temp) return;
        state.temp.info = doc;
        /* never tear down an open place composer for a reverse-lookup refresh */
        if (state.creatingAt) return;
        renderRight({ temp: state.temp });
      }).catch(() => { /* the panel keeps the raw coordinate */ });
    }

    /**
     * A base-map place is not a registry record — it is a printed name on the ground.
     * Clicking it must still answer the question "what is here?", so the inspector shows
     * the place itself and the registry records within reach of it, and says plainly
     * that the city is cartography, not a record.
     */
    function openGazetteer(lat, lon, props) {
      clearTemp();
      state.selected = null;
      state.selectedDoc = null;
      state.stack = null;
      const city = {
        lat, lon,
        name_en: props.name_en || props.name || "",
        name_ar: props.name_ar || "",
        population: Number(props.population || 0)
      };
      state.gazetteer = city;
      markSelection(lat, lon, {
        etype: "place",
        label: A.state.lang === "ar" ? (city.name_ar || city.name_en) : (city.name_en || city.name_ar)
      });
      ensureRight();
      renderRight({ gazetteer: city });
      api.post("/api/map/query", {
        mode: "radius", lat, lon, radius_m: 25000, limit: 60,
        layers: Array.from(state.filters.layers)
      }).then(res => {
        if (mapState !== state || state.gazetteer !== city) return;
        city.records = res;
        renderRight({ gazetteer: city });
      }).catch(err => {
        if (mapState !== state || state.gazetteer !== city) return;
        city.error = err.message;
        renderRight({ gazetteer: city });
      });
    }

    function clearTemp() {
      state.temp = null;
      try {
        const src = ready ? map.getSource("temp") : null;
        if (src) src.setData(selectionGeoJSON(null));
      } catch (e) { /* the style is being replaced; nothing to clear */ }
    }

    /** Workspace-native place create — delegated to shared maplib. */
    function openCreateAt(lat, lon) {
      if (state.maplib) state.maplib.openCreateAt(lat, lon);
    }

    /**
     * A click on the map always *shows* something. If the inspector was collapsed, the
     * answer would otherwise be rendered into a panel nobody can see — which reads as
     * "clicking does nothing". So a deliberate selection opens the panel that carries it.
     */
    function ensureRight() {
      if (state.panels.right) return false;
      state.panels.right = true;
      applyPanels();
      return true;
    }

    async function selectFeature(feature, { fly = false, stack = null, open = true } = {}) {
      if (!feature || !feature.id) return;
      clearTemp();
      state.gazetteer = null;
      state.stack = stack && stack.length > 1 ? stack : null;
      if (open) ensureRight();
      state.selected = { entity_type: feature.entity_type, id: feature.id };
      A.setPref(SEL_KEY, `${feature.entity_type}:${feature.id}`);
      try {
        const doc = await api.get(`/api/map/feature/${feature.entity_type}/${feature.id}`);
        if (mapState !== state) return;
        if (state.selected && (state.selected.id !== feature.id ||
                               state.selected.entity_type !== feature.entity_type)) return;
        state.selectedDoc = doc;
        const pos = doc.position && doc.position.formatted
          ? { lat: doc.position.lat, lon: doc.position.lon }
          : (feature.lat != null ? { lat: feature.lat, lon: feature.lon } : null);
        if (pos) {
          const label = A.state.lang === "ar"
            ? (doc.label_ar || doc.label_en || feature.label)
            : (doc.label_en || doc.label_ar || feature.label);
          markSelection(pos.lat, pos.lon, {
            etype: feature.entity_type || doc.entity_type,
            label: label || doc.code || "",
            initial: undefined
          });
          if (fly) map.easeTo({
            center: [pos.lon, pos.lat],
            zoom: Math.max(map.getZoom(), 13),
            duration: 700
          });
        }
        renderRight({ doc });
        renderLeft();
        renderPins();
      } catch (err) {
        /* a remembered selection that no longer exists in this database (a fresh
           install, a deleted record) is forgotten here — otherwise every future map
           open re-requests a record that will never answer (the stale `place:9`
           404 on a fresh install) */
        if (err && err.status === 404 && state.selected &&
            state.selected.id === feature.id &&
            state.selected.entity_type === feature.entity_type) {
          state.selected = null;
          state.selectedDoc = null;
          A.setPref(SEL_KEY, "default");
          renderRight();
        }
        toast(err.message, "err", 5000);
      }
    }

    /* measuring geometry + panel: owned by A.maplib (see attachMapLib onMeasure) */

    /* --------------------------------------------------------------- scale --- */
    function updateScale() {
      if (!ready) return;
      const y = map.getContainer().clientHeight / 2;
      const left = map.unproject([60, y]);
      const right = map.unproject([160, y]);
      const d = haversine(left.lat, left.lng, right.lat, right.lng);
      dom.scale.innerHTML = `<span class="geo-scale-bar"></span>
        <span>${esc(fmtDistance(d, state.units))}</span>`;
    }

    /* ------------------------------------------------------------- labels --- */
    let labels = [];
    /** 1 204 → 1.2k: a count that fits inside a 19-pixel ring. */
    function compactCount(v) {
      const n = Number(v) || 0;
      if (n < 1000) return String(n);
      const k = n / 1000;
      return (k < 10 ? k.toFixed(1) : String(Math.round(k))) + "k";
    }

    function renderLabels() {
      if (!ready) return;
      labels.forEach(l => l.remove());
      labels = [];
      if (!state.labels) return;
      const zoom = map.getZoom();
      const seen = [];
      const threshold = 64;
      /* offline orientation: the bundled gazetteer names the cities around you, so an
         untouched base map is never a blank field of grey */
      if (zoom <= 10 && (state.baseCities || []).length) {
        const cities = state.baseCities.slice()
          .sort((a, b) => (b.population || 0) - (a.population || 0))
          .slice(0, 26);
        for (const c of cities) {
          const pt = map.project([c.lon, c.lat]);
          if (pt.x < -40 || pt.y < -20 || pt.x > dom.map.clientWidth + 40 ||
              pt.y > dom.map.clientHeight + 20) continue;
          if (seen.some(s => Math.abs(s.x - pt.x) < threshold && Math.abs(s.y - pt.y) < threshold)) continue;
          seen.push(pt);
          const el = document.createElement("div");
          el.className = "geo-label geo-label-city";
          el.textContent = A.state.lang === "ar" ? (c.name_ar || c.name_en) : (c.name_en || c.name_ar);
          el.dir = "auto";
          el.title = t("geo.cityHint");
          el.onclick = (ev) => { ev.stopPropagation(); openGazetteer(c.lat, c.lon, c); };
          labels.push(new window.maplibregl.Marker({ element: el, anchor: "left", offset: [6, 0] })
            .setLngLat([c.lon, c.lat]).addTo(map));
        }
      }
      /* While the map is being read as groups rather than records, the count in
         each ring is the important number. It is drawn in the DOM because the
         shipped styles carry no glyph endpoint, and a text layer without one is a
         console error on every frame — the tiles are raster and must stay offline. */
      if (zoom < 9.05 && state.cluster) {
        const seenC = [];
        for (const f of map.querySourceFeatures("records")) {
          const props = f.properties || {};
          if (props.point_count == null || !f.geometry) continue;
          const [lon, lat] = f.geometry.coordinates;
          const pt = map.project([lon, lat]);
          if (pt.x < 0 || pt.y < 0 || pt.x > dom.map.clientWidth || pt.y > dom.map.clientHeight) continue;
          if (seenC.some(c => Math.abs(c.x - pt.x) < 30 && Math.abs(c.y - pt.y) < 30)) continue;
          seenC.push(pt);
          const parts = [
            ["person", Number(props.n_person) || 0],
            ["institution", Number(props.n_institution) || 0],
            ["place", Number(props.n_place) || 0],
            ["event", Number(props.n_event) || 0]
          ];
          const major = parts.reduce((a, b) => (b[1] > a[1] ? b : a), ["event", -1])[0];
          const total = parts.reduce((s, p) => s + p[1], 0) || 1;
          let ang = -Math.PI / 2;
          const arcs = parts.filter(p => p[1] > 0).map(([etype, n]) => {
            const sweep = (n / total) * Math.PI * 2;
            const a0 = ang, a1 = ang + sweep;
            ang = a1;
            const r = 15, cx = 18, cy = 18;
            const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
            const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
            const large = sweep > Math.PI ? 1 : 0;
            const color = (LAYER_STYLE[etype] || {}).color || "#666";
            return `<path d="M${cx} ${cy} L${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} Z" fill="${color}"/>`;
          }).join("");
          const el = document.createElement("div");
          el.className = "geo-cluster-mark";
          el.dataset.major = major;
          el.innerHTML =
            `<svg class="geo-cluster-pie" width="36" height="36" viewBox="0 0 36 36" aria-hidden="true">` +
            `<circle cx="18" cy="18" r="17" fill="rgba(18,24,32,.55)"/>` +
            arcs +
            `<circle cx="18" cy="18" r="9.5" fill="rgba(18,24,32,.9)" stroke="rgba(255,255,255,.85)" stroke-width="1.2"/>` +
            `</svg>` +
            `<span class="geo-cluster-count" data-major="${major}">${compactCount(props.point_count)}</span>`;
          labels.push(new window.maplibregl.Marker({ element: el, anchor: "center", offset: [0, 0] })
            .setLngLat([lon, lat]).addTo(map));
        }
      }
      /* Record name labels are now carried by the bubble pins themselves. */
      renderPins();
    }

    /* ---------------------------------------------------------- left panel --- */
    let leftTab = "records";

    function statusOptions() {
      const opts = ((A.state.meta && A.state.meta.lookups && A.state.meta.lookups.record_status) || []);
      return opts;
    }

    function renderLeft() {
      if (!state.panels.left) return;
      /* detach before the panel is rewritten, so a redraw cannot drop the
         field query the reader is in the middle of */
      if (geoAdvEl && geoAdvEl.parentNode) geoAdvEl.remove();
      if (leftTab === "records") {
        const rows = state.points;
        const extra = advCount();
        dom.leftBody.innerHTML = `
          <div class="geo-list-meta">
            <span>${fmtNum(state.points.length)} ${esc(t("geo.recordsShown"))}</span>
            ${extra ? `<span class="badge">${esc(t("mf.active"))} ${fmtNum(extra)}</span>` : ""}
            ${state.truncated ? `<span class="badge amber">${esc(t("geo.truncated"))}</span>` : ""}
          </div>
          ${rows.length ? `<ul class="geo-list">${rows.slice(0, 400).map(p => {
            const label = A.state.lang === "ar" ? (p.label_ar || p.label_en) : (p.label_en || p.label_ar);
            const mark = A.geopin
              ? A.geopin.chipHtml({ etype: p.entity_type, label, size: "sm" })
              : `<span class="geo-dot" style="background:${(LAYER_STYLE[p.entity_type] || {}).color || "#666"}"></span>`;
            return `
            <li class="geo-row${state.selected && state.selected.id === p.id &&
                                   state.selected.entity_type === p.entity_type ? " active" : ""}"
                data-etype="${esc(p.entity_type)}" data-id="${p.id}">
              <span class="geo-row-mark">${mark}</span>
              <span class="geo-row-main">
                <span class="geo-row-title" dir="auto">${esc(label)}</span>
                <span class="geo-row-sub" dir="ltr">${esc(p.code)} · ${esc(t("geo.layer." + p.entity_type))}</span>
              </span>
            </li>`;
          }).join("")}</ul>`
            : `<p class="muted small">${esc(t("geo.noRecords"))}</p>`}`;
        dom.leftBody.querySelectorAll(".geo-row").forEach(row => {
          row.onclick = () => selectFeature({ entity_type: row.dataset.etype, id: Number(row.dataset.id) },
                                            { fly: true });
        });
      } else if (leftTab === "places") {
        const groups = state.groups || [];
        const extraPlaces = advCount();
        dom.leftBody.innerHTML = `
          <div class="geo-list-meta">
            <span>${fmtNum(groups.length)} ${esc(t("geo.placesShown"))}</span>
            <span class="muted">${fmtNum((state.groupStats && state.groupStats.total_records) || 0)} ${esc(t("geo.recordsShown"))}</span>
            ${extraPlaces ? `<span class="badge">${esc(t("mf.active"))} ${fmtNum(extraPlaces)}</span>` : ""}
          </div>
          ${groups.length ? `<ul class="geo-list">${groups.map(g => `
            <li class="geo-row" data-place="${g.place_id}" data-lat="${g.lat}" data-lon="${g.lon}">
              <span class="geo-count">${fmtNum(g.count)}</span>
              <span class="geo-row-main">
                <span class="geo-row-title" dir="auto">${esc(A.state.lang === "ar" ? (g.label_ar || g.label_en) : (g.label_en || g.label_ar))}</span>
                <span class="geo-row-sub">${Object.entries(g.by_layer).map(([k, v]) =>
                  `${esc(t("geo.layer." + k))} ${fmtNum(v)}`).join(" · ")}</span>
              </span>
            </li>`).join("")}</ul>`
            : `<p class="muted small">${esc(t("geo.noRecords"))}</p>`}`;
        dom.leftBody.querySelectorAll(".geo-row").forEach(row => {
          row.onclick = () => {
            map.easeTo({ center: [Number(row.dataset.lon), Number(row.dataset.lat)],
                         zoom: Math.max(map.getZoom(), 9), duration: 700 });
            dropTemp(Number(row.dataset.lat), Number(row.dataset.lon));
          };
        });
      } else {
        const statuses = statusOptions();
        dom.leftBody.innerHTML = `
          <div class="geo-filter">
            <label class="geo-filter-label" for="geoFilterQ">${esc(t("geo.filterText"))}</label>
            <input id="geoFilterQ" type="search" value="${esc(state.filters.q)}" dir="auto">
            <label class="geo-filter-label" for="geoFilterStatus">${esc(t("geo.filterStatus"))}</label>
            <select id="geoFilterStatus" class="ghost-select">
              <option value="">${esc(t("geo.anyStatus"))}</option>
              ${statuses.map(s => `<option value="${s.id}" ${String(state.filters.status) === String(s.id) ? "selected" : ""}>${esc(A.state.lang === "ar" ? (s.label_ar || s.label_en) : (s.label_en || s.label_ar))}</option>`).join("")}
            </select>
            <div class="geo-filter-label">${esc(t("geo.filterLayers"))}</div>
            ${state.layers.map(l => {
              const name = A.state.lang === "ar" ? l.label_ar : l.label_en;
              const chip = A.geopin
                ? A.geopin.chipHtml({ etype: l.entity_type, label: name, size: "sm" })
                : `<span class="geo-dot" style="background:${(LAYER_STYLE[l.entity_type] || {}).color}"></span>`;
              return `
              <label class="geo-check">
                <input type="checkbox" data-layer="${esc(l.entity_type)}"
                       ${state.filters.layers.has(l.entity_type) ? "checked" : ""}>
                ${chip}
                ${esc(name)}
                <span class="muted small">${fmtNum(l.located)}/${fmtNum(l.total)}</span>
              </label>`;
            }).join("")}
            <div data-map-filters-slot></div>
            <button class="btn sm" id="geoFilterApply">${esc(t("geo.applyFilters"))}</button>
            <div class="small muted">${esc(t("geo.unlocatedNote"))}</div>
          </div>`;
        const slot = dom.leftBody.querySelector("[data-map-filters-slot]");
        if (slot && A.mapFilters) {
          if (!geoAdvEl) {
            geoAdvEl = document.createElement("div");
            geoAdvEl._mf = A.mapFilters.mount(geoAdvEl, {
              state: state.filters,
              onApply: () => applyGeoFilters()
            });
          }
          slot.replaceWith(geoAdvEl);
          if (geoAdvEl._mf) geoAdvEl._mf.setWarnings(state.filters.warnings || []);
        }
        dom.leftBody.querySelector("#geoFilterApply").onclick = () => applyGeoFilters();
      }
    }

    /* --------------------------------------------------------- right panel --- */
    function coordBlock(lat, lon, extra) {
      const dd = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
      const dmsText = `${dms(lat, true)} ${dms(lon, false)}`;
      const merc = `${(lon * 20037508.34 / 180).toFixed(1)}, ` +
        `${(Math.log(Math.tan((90 + lat) * Math.PI / 360)) * R_EARTH).toFixed(1)}`;
      return `
        <div class="geo-coords" dir="ltr">
          <div class="geo-coord-row"><span class="geo-coord-k">${esc(t("geo.decimal"))}</span>
            <code>${esc(dd)}</code></div>
          <div class="geo-coord-row"><span class="geo-coord-k">${esc(t("geo.dms"))}</span>
            <code>${esc(dmsText)}</code></div>
          <div class="geo-coord-row"><span class="geo-coord-k">EPSG:3857</span>
            <code>${esc(merc)} m</code></div>
        </div>${extra || ""}`;
    }

    function renderRight(opts) {
      if (!state.panels.right) return;
      const lang = A.state.lang;
      if (opts && opts.gazetteer) {
        renderGazetteer(opts.gazetteer);
        return;
      }
      if (opts && opts.temp) {
        const tp = opts.temp;
        const info = tp.info || {};
        const country = info.country ? (lang === "ar" ? info.country.name_ar : info.country.name_en) : null;
        const nearby = (info.nearby_places || [])[0];
        dom.rightBody.innerHTML = `
          <div class="geo-inspector">
            <div class="geo-insp-head">
              <span class="badge amber">${esc(t("geo.tempPoint"))}</span>
              <strong>${esc(t("geo.noRecord"))}</strong>
            </div>
            <p class="small muted">${esc(t("geo.tempHint"))}</p>
            ${coordBlock(tp.lat, tp.lon)}
            ${country ? `<div class="geo-kv"><span>${esc(t("geo.country"))}</span><b dir="auto">${esc(country)}</b></div>` : ""}
            ${nearby ? `<div class="geo-kv"><span>${esc(t("geo.nearestPlace"))}</span>
              <b dir="auto">${esc(lang === "ar" ? (nearby.label_ar || nearby.label_en) : (nearby.label_en || nearby.label_ar))}
              · ${esc(fmtDistance(nearby.distance_m, state.units))}</b></div>` : ""}
            <div class="geo-actions">
              <button class="btn sm primary" id="geoCreatePlace">${esc(t("geo.createPlaceHere"))}</button>
              <button class="btn sm" id="geoRadiusQuery">${esc(t("geo.queryRadius"))}</button>
              <button class="btn ghost sm" id="geoCopyTemp">${esc(t("geo.copyCoords"))}</button>
            </div>
            <div class="geo-composer" data-geo-composer hidden></div>
            <div id="geoRadiusResult"></div>
          </div>`;
        const copy = dom.rightBody.querySelector("#geoCopyTemp");
        copy.onclick = () => copyText(`${tp.lat.toFixed(6)}, ${tp.lon.toFixed(6)}`);
        dom.rightBody.querySelector("#geoRadiusQuery").onclick = () => radiusQuery(tp.lat, tp.lon);
        dom.rightBody.querySelector("#geoCreatePlace").onclick = () => openCreateAt(tp.lat, tp.lon);
        return;
      }
      if (!state.selectedDoc) {
        dom.rightBody.innerHTML = `<div class="geo-empty">
            <p class="muted small">${esc(t("geo.selectHint"))}</p>
          </div>`;
        return;
      }
      const doc = state.selectedDoc;
      const label = lang === "ar" ? (doc.label_ar || doc.label_en) : (doc.label_en || doc.label_ar);
      const pos = doc.position;
      const country = pos && pos.country_polygon
        ? (lang === "ar" ? pos.country_polygon.name_ar : pos.country_polygon.name_en) : null;
      /* an associated point is shown at its place — name the association, never
         present the place's coordinates as the record's own position */
      const assocPos = !!(pos && pos.position === "associated");
      const anchorText = !pos ? "" : assocPos
        ? ((lang === "ar" ? pos.anchor_ar : pos.anchor_en) + ": " +
           (lang === "ar" ? (pos.place_ar || pos.place_en) : (pos.place_en || pos.place_ar)))
        : t("geo.ownPosition");
      dom.rightBody.innerHTML = `
        <div class="geo-inspector">
          <div class="geo-insp-head">
            <span class="badge">${esc(t("geo.layer." + doc.entity_type))}</span>
            <span class="mono-cell">${esc(doc.code)}</span>
            ${doc.status ? A.badge(doc.status, "gray") : ""}
          </div>
          <h3 class="geo-insp-title" dir="auto">${esc(label)}</h3>
          ${pos ? `
            ${coordBlock(pos.lat, pos.lon, `
              <div class="geo-kv"><span>${esc(t("geo.anchor"))}</span>
                <b dir="auto">${esc(anchorText)}</b></div>
              ${assocPos ? `<div class="notice small">${esc(t("geo.associatedPoint"))}</div>` : ""}
              ${pos.precision ? `<div class="geo-kv"><span>${esc(t("geo.precision"))}</span><b>${esc(pos.precision)}</b></div>` : ""}
              ${country ? `<div class="geo-kv"><span>${esc(t("geo.country"))}</span><b dir="auto">${esc(country)}</b></div>` : ""}
              ${pos.country_en ? `<div class="geo-kv"><span>${esc(t("geo.recordCountry"))}</span><b dir="auto">${esc(lang === "ar" ? pos.country_ar : pos.country_en)}</b></div>` : ""}
            `)}` : `
            <div class="notice warn small">${esc(lang === "ar" ? (doc.reason && doc.reason.message_ar) : (doc.reason && doc.reason.message_en)) || esc(t("geo.noPosition"))}</div>`}
          <div class="geo-actions">
            <a class="btn sm primary" href="#/entity/${esc(doc.entity_type)}/${doc.id}">${esc(t("geo.openRecord"))}</a>
            <a class="btn sm" href="#/map?focus=${esc(doc.entity_type)}:${doc.id}">${esc(t("geo.showOnAtlas"))}</a>
            <button class="btn ghost sm" id="geoSaveCoords" ${pos ? "" : "disabled"}>${esc(t("geo.copyCoords"))}</button>
            ${pos ? `<button class="btn ghost sm" id="geoCentreOn">${esc(t("geo.centreOn"))}</button>` : ""}
            ${pos ? `<a class="btn ghost sm" href="https://www.openstreetmap.org/?mlat=${pos.lat}&amp;mlon=${pos.lon}#map=17/${pos.lat}/${pos.lon}"
                        target="_blank" rel="noopener noreferrer">OSM ↗</a>` : ""}
          </div>
          ${state.stack ? `
            <div class="geo-section geo-stack">
              <div class="geo-section-head">${esc(t("geo.recordsAtPoint"))}
                <b>${fmtNum(state.stack.length)}</b></div>
              ${state.stack.map(r => {
                const on = r.entity_type === doc.entity_type && r.id === doc.id;
                return `<button class="geo-stack-row${on ? " active" : ""}"
                                data-etype="${esc(r.entity_type)}" data-id="${r.id}">
                  <span class="badge">${esc(t("geo.layer." + r.entity_type))}</span>
                  <span dir="auto">${esc(r.label || r.code || "")}</span>
                  ${r.code ? `<span class="small muted" dir="ltr">${esc(r.code)}</span>` : ""}
                </button>`;
              }).join("")}
            </div>` : ""}
          ${doc.relationships && doc.relationships.length ? `
            <div class="geo-section">
              <div class="geo-section-head">${esc(t("geo.relationships"))} (${fmtNum(doc.relationships.length)})</div>
              ${doc.relationships.slice(0, 12).map(r => `
                <button class="geo-rel" data-etype="${esc(r.entity_type)}" data-id="${r.id}">
                  <span dir="auto">${esc(lang === "ar" ? (r.label_ar || r.label_en) : (r.label_en || r.label_ar))}</span>
                  <span class="small muted" dir="ltr">${esc(fmtDistance(r.distance_m || 0, state.units))}</span>
                </button>`).join("")}
            </div>` : ""}
          ${doc.evidence && doc.evidence.length ? `
            <div class="geo-section">
              <div class="geo-section-head">${esc(t("geo.sources"))}</div>
              ${A.evidence.list(doc.evidence, { removable: false })}
            </div>` : ""}
        </div>`;
      const copyBtn = dom.rightBody.querySelector("#geoSaveCoords");
      if (copyBtn && pos) copyBtn.onclick = () => copyText(`${pos.lat.toFixed(6)}, ${pos.lon.toFixed(6)}`);
      const centre = dom.rightBody.querySelector("#geoCentreOn");
      if (centre && pos) centre.onclick = () => map.easeTo({ center: [pos.lon, pos.lat], duration: 600 });
      dom.rightBody.querySelectorAll(".geo-rel").forEach(btn => {
        btn.onclick = () => selectFeature({ entity_type: btn.dataset.etype, id: Number(btn.dataset.id) },
                                          { fly: true });
      });
      /* the stack rows keep the stack: choosing a sibling must not lose the others */
      dom.rightBody.querySelectorAll(".geo-stack-row").forEach(btn => {
        btn.onclick = () => selectFeature(
          { entity_type: btn.dataset.etype, id: Number(btn.dataset.id) },
          { stack: state.stack });
      });
    }

    /**
     * The inspector for a base-map place: its own details, then the registry records
     * that are actually there. The list is the answer to the click, so it is rendered
     * first and counted, and each row is a way into the record's own dossier.
     */
    function renderGazetteer(g) {
      const lang = A.state.lang;
      const name = lang === "ar" ? (g.name_ar || g.name_en) : (g.name_en || g.name_ar);
      const res = g.records || null;
      const rows = (res && res.records) || [];
      dom.rightBody.innerHTML = `
        <div class="geo-inspector">
          <div class="geo-insp-head">
            <span class="badge blue">${esc(t("geo.basePlace"))}</span>
            <span class="small muted">${esc(t("geo.notARecord"))}</span>
          </div>
          <h3 class="geo-insp-title" dir="auto">${esc(name || "—")}</h3>
          ${coordBlock(g.lat, g.lon)}
          ${g.population ? `<div class="geo-kv"><span>${esc(t("geo.population"))}</span>
            <b>${fmtNum(g.population)}</b></div>` : ""}
          <p class="small muted">${esc(t("geo.cityHint"))}</p>
          <div class="geo-actions">
            <button class="btn sm" id="geoCityRadius">${esc(t("geo.queryRadius"))}</button>
            <button class="btn ghost sm" id="geoCityCopy">${esc(t("geo.copyCoords"))}</button>
          </div>
          <div class="geo-section geo-gaz-records">
            <div class="geo-section-head">
              ${esc(t("geo.recordsHere"))}
              ${res ? `<b>${fmtNum(res.count)}</b>` : `<span class="small muted">…</span>`}
            </div>
            ${g.error ? `<div class="small err">${esc(g.error)}</div>` : ""}
            ${rows.length ? rows.map(r => `
              <button class="geo-rel geo-stack-row" data-etype="${esc(r.entity_type)}"
                      data-id="${r.id}">
                <span class="badge">${esc(t("geo.layer." + r.entity_type))}</span>
                <span dir="auto">${esc(lang === "ar" ? (r.label_ar || r.label_en)
                                                      : (r.label_en || r.label_ar))}</span>
                <span class="small muted" dir="ltr">${esc(fmtDistance(r.distance_m || 0, state.units))}</span>
              </button>`).join("")
              : (res ? `<div class="small muted">${esc(t("geo.noRecordsHere"))}</div>` : "")}
            ${res && res.count > rows.length
              ? `<div class="small muted">${esc(t("geo.showingFirst", { n: rows.length, total: res.count }))}</div>`
              : ""}
          </div>
        </div>`;
      dom.rightBody.querySelectorAll(".geo-stack-row").forEach(btn => {
        btn.onclick = () => selectFeature(
          { entity_type: btn.dataset.etype, id: Number(btn.dataset.id) }, { fly: true });
      });
      const copy = dom.rightBody.querySelector("#geoCityCopy");
      if (copy) copy.onclick = () => copyText(`${g.lat.toFixed(6)}, ${g.lon.toFixed(6)}`);
      const rad = dom.rightBody.querySelector("#geoCityRadius");
      if (rad) rad.onclick = () => radiusQuery(g.lat, g.lon);
    }

    function radiusQuery(lat, lon) {
      const box = dom.rightBody.querySelector("#geoRadiusResult");
      box.innerHTML = `<div class="small muted">…</div>`;
      api.post("/api/map/query", {
        mode: "radius", lat, lon, radius_m: 25000, limit: 50,
        layers: Array.from(state.filters.layers)
      }).then(res => {
        box.innerHTML = `<div class="geo-kv"><span>${esc(t("geo.within25km"))}</span>
            <b>${fmtNum(res.count)}</b></div>
          ${(res.records || []).slice(0, 8).map(r => `
            <button class="geo-rel" data-etype="${esc(r.entity_type)}" data-id="${r.id}">
              <span dir="auto">${esc(A.state.lang === "ar" ? (r.label_ar || r.label_en) : (r.label_en || r.label_ar))}</span>
              <span class="small muted" dir="ltr">${esc(fmtDistance(r.distance_m || 0, state.units))}</span>
            </button>`).join("")}`;
        box.querySelectorAll(".geo-rel").forEach(btn => {
          btn.onclick = () => selectFeature({ entity_type: btn.dataset.etype, id: Number(btn.dataset.id) },
                                            { fly: true });
        });
      }).catch(err => { box.innerHTML = `<div class="small err">${esc(err.message)}</div>`; });
    }

    function copyText(text) {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => toast(t("geo.copied"), "ok", 1800))
          .catch(() => toast(text, "ok", 4000));
      } else {
        toast(text, "ok", 4000);
      }
    }

    /* --------------------------------------------------------------- legend --- */
    function renderLegend() {
      const counts = {};
      state.points.forEach(p => { counts[p.entity_type] = (counts[p.entity_type] || 0) + 1; });
      dom.legend.innerHTML = state.layers.filter(l => state.filters.layers.has(l.entity_type)).map(l => {
        const name = A.state.lang === "ar" ? l.label_ar : l.label_en;
        const mark = A.geopin
          ? A.geopin.chipHtml({ etype: l.entity_type, label: name, size: "md" })
          : `<span class="geo-dot" style="background:${(LAYER_STYLE[l.entity_type] || {}).color}"></span>`;
        return `<span class="geo-legend-item">
          ${mark}
          ${esc(name)}
          <b>${fmtNum(counts[l.entity_type] || 0)}</b>
        </span>`;
      }).join("");
    }

    /* ------------------------------------------------------------ controls --- */
    const ws = dom.workspace;

    function applyPanels() {
      ws.classList.toggle("left-off", !state.panels.left);
      ws.classList.toggle("right-off", !state.panels.right);
      root.querySelector("#geoLeftToggle").setAttribute("aria-pressed", String(state.panels.left));
      root.querySelector("#geoRightToggle").setAttribute("aria-pressed", String(state.panels.right));
      savePanels(state.panels);
      /* the requirement: recalculate the viewport and let the library resize */
      requestAnimationFrame(() => {
        map.resize();
        renderLabels();
        updateScale();
      });
      setTimeout(() => { map.resize(); renderLabels(); }, 260);
      if (state.panels.left) { dom.leftBody.innerHTML = ""; renderLeft(); }
      if (state.panels.right) renderRight(state.temp ? { temp: state.temp } : undefined);
    }

    root.querySelector("#geoLeftToggle").onclick = () => {
      state.panels.left = !state.panels.left; applyPanels();
    };
    root.querySelector("#geoRightToggle").onclick = () => {
      state.panels.right = !state.panels.right; applyPanels();
    };
    root.querySelectorAll("[data-close]").forEach(btn => {
      btn.onclick = () => {
        state.panels[btn.dataset.close] = false;
        applyPanels();
      };
    });
    root.querySelectorAll("[data-panel-tab]").forEach(btn => {
      btn.onclick = () => {
        leftTab = btn.dataset.panelTab;
        root.querySelectorAll("[data-panel-tab]").forEach(b => {
          const on = b === btn;
          b.classList.toggle("active", on);
          b.setAttribute("aria-selected", String(on));
        });
        dom.leftBody.innerHTML = "";
        renderLeft();
        if (leftTab === "places") {
          api.get(`/api/map/groups?bbox=${currentBbox()}&zoom=${map.getZoom().toFixed(2)}` +
                  `&layers=${Array.from(state.filters.layers).join(",")}&limit=80`)
            .then(doc => { if (mapState !== state) return; state.groups = doc.groups; renderLeft(); })
            .catch(() => {});
        }
      };
    });

    root.querySelector("#geoZoomIn").onclick = () => map.zoomIn({ duration: 260 });
    root.querySelector("#geoZoomOut").onclick = () => map.zoomOut({ duration: 260 });
    root.querySelector("#geoRotate").onclick = () =>
      map.easeTo({ bearing: 0, pitch: 0, duration: 400 });

    /* layer menu: providers, overlays, clustering, labels */
    const layersBtn = root.querySelector("#geoLayersBtn");
    layersBtn.onclick = () => {
      dom.layersMenu.hidden = !dom.layersMenu.hidden;
      layersBtn.setAttribute("aria-expanded", String(!dom.layersMenu.hidden));
      renderLayerMenu();
    };

    const dlBtn = root.querySelector("#geoDownloadBtn");
    const dlMenu = root.querySelector("#geoDownloadMenu");
    dlBtn.onclick = () => {
      dlMenu.hidden = !dlMenu.hidden;
      dlBtn.setAttribute("aria-expanded", String(!dlMenu.hidden));
      if (dlMenu.hidden) {
        if (state._dlTimer) { clearInterval(state._dlTimer); state._dlTimer = null; }
      } else {
        loadDownloads();
        state._dlTimer = setInterval(() => {
          if (!dlMenu.hidden) loadDownloads(); else {
            clearInterval(state._dlTimer); state._dlTimer = null;
          }
        }, 2500);
      }
    };

    /* ------------------------------------------------- map downloads ------- */
    /* A region's tiles, of any map type whose terms allow it, pulled once and
       kept for good — the app's own store answers every later view offline. */
    function estimateTiles(w, s2, e, n, zmin, zmax) {
      const ty = (lat, z) => {
        lat = Math.max(-85.0511, Math.min(85.0511, lat));
        const siny = Math.sin(lat * Math.PI / 180);
        return Math.max(0, Math.min(2 ** z - 1,
          Math.floor((0.5 - Math.log((1 + siny) / (1 - siny)) / (4 * Math.PI)) * 2 ** z)));
      };
      const tx = (lon, z) => Math.max(0, Math.min(2 ** z - 1,
        Math.floor((lon + 180) / 360 * 2 ** z)));
      let total = 0;
      for (let z = zmin; z <= zmax; z++) {
        total += (tx(e, z) - tx(w, z) + 1) * (ty(s2, z) - ty(n, z) + 1);
      }
      return total;
    }

    function dlBbox() {
      const area = (root.querySelector("#dlArea") || {}).value || "viewport";
      if (area === "world") return { w: -180, s: -85, e: 180, n: 85 };
      if (area === "working") {
        const wa = (state.conf.offline_pack || {}).working_area
          || { w: 34.2, s: 31.2, e: 34.6, n: 31.6 };
        return { w: wa.w, s: wa.s, e: wa.e, n: wa.n };
      }
      const b = map.getBounds();
      return { w: b.getWest(), s: b.getSouth(), e: b.getEast(), n: b.getNorth() };
    }

    function fmtN(v) {
      try { return new Intl.NumberFormat(A.state.lang === "ar" ? "ar" : "en").format(v); }
      catch (e) { return String(v); }
    }

    async function loadDownloads() {
      const body = root.querySelector("#geoDownloadBody");
      if (!body) return;
      let doc = null;
      try { doc = await api.get("/api/geo/downloads"); } catch (e) { /* offline box */ }
      const lang = A.state.lang;
      const caps = (doc && doc.caps) || { max_zoom: 15, max_tiles: 25000, delay_ms: 250 };
      const provs = (doc && doc.providers) || [];
      const jobs = (doc && doc.jobs) || [];
      const stats = (doc && doc.stats) || { tiles: 0, bytes: 0 };
      const sel = body.querySelector("#dlArea");
      const keptArea = sel ? sel.value : "viewport";
      const zminEl = body.querySelector("#dlZMin");
      const zmaxEl = body.querySelector("#dlZMax");
      const keptZMin = zminEl ? zminEl.value : "0";
      const keptZMax = zmaxEl ? zmaxEl.value : "12";
      const keptChecked = new Set(Array.from(
        body.querySelectorAll("input[data-dl-prov]:checked")).map(el => el.value));

      const groups = ["offline", "standard", "aerial", "terrain"];
      const provBox = groups.map(g => {
        const members = provs.filter(p => p.group === g);
        if (!members.length) return "";
        return `<div class="dl-group">${members.map(p => {
          const label = lang === "ar" ? p.label_ar : p.label_en;
          const note = lang === "ar" ? p.download_note_ar : p.download_note_en;
          const ok = p.downloadable;
          return `<label class="geo-check${ok ? "" : " dl-off"}">
              <input type="checkbox" data-dl-prov="${esc(p.id)}" value="${esc(p.id)}"
                     ${ok && keptChecked.has(p.id) ? "checked" : ""} ${ok ? "" : "disabled"}>
              <span dir="auto">${esc(label)}</span>
              ${ok ? "" : `<span class="badge gray">${esc(t("mapdl.notAllowed"))}</span>`}
              ${note ? `<span class="small muted dl-note" dir="auto">${esc(note)}</span>` : ""}
            </label>`;
        }).join("")}</div>`;
      }).join("");

      const jobRows = jobs.map(j => {
        const p = provs.find(x => x.id === j.provider) || { label_en: j.provider, label_ar: j.provider };
        const label = lang === "ar" ? p.label_ar : p.label_en;
        const pct = j.total ? Math.round(((j.done + j.skipped) / j.total) * 100) : 0;
        const cls = j.status === "done" ? "green" : (j.status === "failed" || j.status === "canceled")
          ? "red" : (j.status === "paused" ? "amber" : "blue");
        const acts = [];
        if (["queued", "running"].includes(j.status))
          acts.push(`<button class="btn ghost sm" data-dl-act="pause" data-id="${j.id}">${esc(t("mapdl.pause"))}</button>`,
                    `<button class="btn ghost sm" data-dl-act="cancel" data-id="${j.id}">${esc(t("mapdl.cancel"))}</button>`);
        if (["paused", "failed"].includes(j.status))
          acts.push(`<button class="btn ghost sm" data-dl-act="resume" data-id="${j.id}">${esc(t("mapdl.resume"))}</button>`);
        acts.push(`<button class="btn ghost sm danger" data-dl-act="delete" data-id="${j.id}">${esc(t("mapdl.delete"))}</button>`);
        return `<div class="dl-job">
            <div class="dl-job-top">
              <b dir="auto">${esc(label)}</b>
              <span class="badge ${cls}">${esc(t("mapdl." + j.status))}</span>
            </div>
            <div class="dl-job-meta small muted" dir="auto">${esc(j.name)}</div>
            <div class="dl-progress"><span style="width:${pct}%"></span></div>
            <div class="dl-job-meta small muted">${fmtN(j.done + j.skipped)} / ${fmtN(j.total)} · z${j.minzoom}–${j.maxzoom}${j.error ? ` · <span class="err">${esc(j.error)}</span>` : ""}</div>
            <div class="btn-row">${acts.join("")}</div>
          </div>`;
      }).join("");

      body.innerHTML = `
        <div class="small muted dl-hint">${esc(t("mapdl.needNetwork"))}</div>
        <div class="dl-field"><label>${esc(t("mapdl.area"))}</label>
          <select class="ghost-select" id="dlArea">
            <option value="viewport" ${keptArea === "viewport" ? "selected" : ""}>${esc(t("mapdl.areaView"))}</option>
            <option value="working" ${keptArea === "working" ? "selected" : ""}>${esc(t("mapdl.areaWorking"))}</option>
            <option value="world" ${keptArea === "world" ? "selected" : ""}>${esc(t("mapdl.areaWorld"))}</option>
          </select></div>
        <div class="dl-field dl-zooms"><label>${esc(t("mapdl.zooms"))}</label>
          <input type="number" id="dlZMin" min="0" max="${caps.max_zoom}" value="${esc(keptZMin)}">
          <span>–</span>
          <input type="number" id="dlZMax" min="0" max="${caps.max_zoom}" value="${esc(keptZMax)}"></div>
        <div class="dl-field"><label>${esc(t("mapdl.types"))}</label>
          <button class="btn ghost sm" id="dlAll">${esc(t("mapdl.selectAll"))}</button>
          ${provBox}</div>
        <div class="dl-field"><label>${esc(t("mapdl.estimate"))}</label>
          <b id="dlEstimate">…</b>
          <span class="small muted">${esc(t("mapdl.stored"))}: ${fmtN(stats.tiles)} · ${fmtN(Math.round((stats.bytes || 0) / 1e6))} MB</span></div>
        <div class="btn-row">
          <button class="btn primary" id="dlStart">${icon("download")} ${esc(t("mapdl.start"))}</button>
          <a class="btn ghost" href="/api/geo/offline-pack.zip">${esc(t("mapdl.downloadZip"))}</a>
        </div>
        <div class="small muted">${esc(t("mapdl.bundledHint"))}</div>
        <div class="geo-menu-head">${esc(t("mapdl.jobs"))}</div>
        <div class="dl-jobs">${jobRows || `<div class="small muted">${esc(t("mapdl.noJobs"))}</div>`}</div>`;

      const refreshEstimate = () => {
        const box = dlBbox();
        const zmin = Math.max(0, Math.min(caps.max_zoom, Number((root.querySelector("#dlZMin") || {}).value) || 0));
        const zmax = Math.max(zmin, Math.min(caps.max_zoom, Number((root.querySelector("#dlZMax") || {}).value) || 0));
        const n = estimateTiles(box.w, box.s, box.e, box.n, zmin, zmax);
        const el = root.querySelector("#dlEstimate");
        if (el) {
          el.textContent = fmtN(n);
          el.className = n > caps.max_tiles ? "err" : "";
        }
      };
      ["#dlArea", "#dlZMin", "#dlZMax"].forEach(q => {
        const el = root.querySelector(q);
        if (el) el.oninput = refreshEstimate;
      });
      refreshEstimate();
      const allBtn = root.querySelector("#dlAll");
      if (allBtn) allBtn.onclick = () => {
        body.querySelectorAll("input[data-dl-prov]:not(:disabled)")
          .forEach(cb => { cb.checked = true; });
      };
      body.querySelectorAll("[data-dl-act]").forEach(btn => {
        btn.onclick = async () => {
          const id = btn.dataset.id;
          const act = btn.dataset.dlAct;
          try {
            if (act === "delete") {
              await api.del(`/api/geo/downloads/${id}?purge=false`);
            } else {
              await api.post(`/api/geo/downloads/${id}/${act}`);
            }
          } catch (e) { /* the list below will show the truth */ }
          loadDownloads();
        };
      });
      const startBtn = root.querySelector("#dlStart");
      if (startBtn) startBtn.onclick = async () => {
        const ids = Array.from(body.querySelectorAll("input[data-dl-prov]:checked"))
          .map(el => el.value);
        if (!ids.length) return;
        const box = dlBbox();
        const zmin = Math.max(0, Math.min(caps.max_zoom, Number((root.querySelector("#dlZMin") || {}).value) || 0));
        const zmax = Math.max(zmin, Math.min(caps.max_zoom, Number((root.querySelector("#dlZMax") || {}).value) || 0));
        startBtn.disabled = true;
        try {
          const res = await api.post("/api/geo/downloads", {
            providers: ids, bbox: box, minzoom: zmin, maxzoom: zmax
          });
          const refused = (res.results || []).filter(r => !r.ok);
          if (refused.length) {
            console.warn("map downloads refused:", refused);
          }
        } catch (e) { console.warn("map download start:", e); }
        startBtn.disabled = false;
        loadDownloads();
      };
    }

    function renderLayerMenu() {
      const lang = A.state.lang;
      const list = root.querySelector("#geoProviderList");
      const byId = {};
      state.conf.providers.forEach(p => { byId[p.id] = p; });
      /* families first (offline · standard · aerial · terrain), so "aerial" is a choice
         a researcher makes rather than the fifth radio button they have to decode */
      const groups = (state.conf.provider_groups || [{ id: "all", providers: Object.keys(byId) }]);
      const option = p => `
        <label class="geo-check geo-provider">
          <input type="radio" name="geoProvider" value="${esc(p.id)}"
                 ${p.id === state.providerId ? "checked" : ""}>
          <span class="geo-swatch" style="background:${esc(p.swatch || "#ccc")}"
                aria-hidden="true"></span>
          <span>
            <b>${esc(lang === "ar" ? p.label_ar : p.label_en)}</b>
            ${p.requires_network ? `<span class="badge gray">${esc(t("geo.online"))}</span>`
                                 : `<span class="badge green">${esc(t("geo.offline"))}</span>`}
            <span class="small muted geo-provider-hint" dir="auto">${esc(lang === "ar" ? p.hint_ar : p.hint_en)}</span>
          </span>
        </label>`;
      list.innerHTML = groups.map(g => {
        const members = (g.providers || []).map(id => byId[id]).filter(Boolean);
        if (!members.length) return "";
        return `<div class="geo-provider-group">
            <div class="geo-group-head">${esc(t("geo.group." + g.id))}</div>
            ${members.map(option).join("")}
          </div>`;
      }).join("");
      list.querySelectorAll("input[name=geoProvider]").forEach(radio => {
        radio.onchange = () => applyProvider(radio.value);
      });
      const overlays = root.querySelector("#geoOverlayList");
      overlays.innerHTML = `
        <label class="geo-check"><input type="checkbox" data-overlay="relationships"
          ${state.overlays.includes("relationships") ? "checked" : ""}> ${esc(t("geo.overlayRelationships"))}</label>
        <label class="geo-check"><input type="checkbox" data-overlay="place_hierarchy"
          ${state.overlays.includes("place_hierarchy") ? "checked" : ""}> ${esc(t("geo.overlayHierarchy"))}</label>
        <label class="geo-check"><input type="checkbox" data-opt="cluster"
          ${state.cluster ? "checked" : ""}> ${esc(t("geo.clusterSetting"))}</label>
        <label class="geo-check"><input type="checkbox" data-opt="labels"
          ${state.labels ? "checked" : ""}> ${esc(t("geo.labelsSetting"))}</label>`;
      overlays.querySelectorAll("[data-overlay]").forEach(cb => {
        cb.onchange = () => {
          state.overlays = Array.from(overlays.querySelectorAll("[data-overlay]:checked"))
            .map(el => el.dataset.overlay);
          A.setPref("map_overlays", state.overlays.join(","));
          addOverlays();
        };
      });
      overlays.querySelectorAll("[data-opt]").forEach(cb => {
        cb.onchange = () => {
          if (cb.dataset.opt === "cluster") {
            state.cluster = cb.checked;
            A.setPref("map_cluster", String(cb.checked));
            /* Tear down every record layer (including glyphs) before the source —
               leaving geo-crce attached made addImage/source swaps fail silently. */
            clearRecordLayers();
            crceTried = 0;
            addOverlayLayers();
            pushFeatures();
            if (state.selectedDoc && state.selectedDoc.position) {
              const d = state.selectedDoc;
              markSelection(d.position.lat, d.position.lon, {
                etype: d.entity_type,
                label: A.state.lang === "ar" ? (d.label_ar || d.label_en) : (d.label_en || d.label_ar)
              });
            }
            renderPins();
          } else {
            state.labels = cb.checked;
            A.setPref("map_labels", String(cb.checked));
            renderLabels();
            renderPins();
          }
        };
      });
      /* offline browse-cache status */
      const cacheHost = document.createElement("div");
      cacheHost.className = "geo-cache-stat";
      cacheHost.id = "geoCacheStat";
      overlays.appendChild(cacheHost);
      const paintCache = () => {
        if (!A.tilecache) {
          cacheHost.textContent = "";
          return;
        }
        A.tilecache.refreshStats().then(s => {
          if (!liveMap || mapState !== state) return;
          const loc = s.local || {};
          const rem = s.remote || {};
          const fmt = n => (Number(n) || 0).toLocaleString();
          const mb = b => ((Number(b) || 0) / (1024 * 1024)).toFixed(1);
          cacheHost.innerHTML =
            `<span>${esc(t("geo.cacheLocal"))}: <b>${fmt(loc.entries)}</b></span>` +
            (rem.entries != null
              ? `<span>${esc(t("geo.cacheDisk"))}: <b>${fmt(rem.entries)}</b> (${mb(rem.bytes)} MB)</span>`
              : "") +
            `<button type="button" class="btn ghost sm" id="geoCacheClear">${esc(t("geo.cacheClear"))}</button>`;
          const btn = cacheHost.querySelector("#geoCacheClear");
          if (btn) btn.onclick = async () => {
            await A.tilecache.clearAll();
            toast(t("geo.cacheCleared"), "ok");
            paintCache();
          };
        });
      };
      paintCache();
    }

    const fitAreaBtn = root.querySelector("#geoFitArea");
    if (fitAreaBtn) {
      fitAreaBtn.onclick = () => {
        const pack = state.conf.offline_pack || {};
        const b = (pack.vectormap && pack.vectormap.bbox)
          || (pack.working_area)
          || null;
        if (!b) { toast(t("geo.noWorkingArea"), "warn"); return; }
        map.fitBounds([[b.w, b.s], [b.e, b.n]], { padding: 48, duration: 900 });
        syncStreets();
      };
    }
    const addAtBtn = root.querySelector("#geoAddAt");
    if (addAtBtn) {
      addAtBtn.onclick = () => {
        if (!state.maplib) return;
        state.maplib.setPickAdd(!state.maplib.state.pickAdd);
        addAtBtn.classList.toggle("active", state.maplib.state.pickAdd);
      };
    }

    /* measurement menu */
    const measureBtn = root.querySelector("#geoMeasureBtn");
    measureBtn.onclick = () => {
      dom.measureMenu.hidden = !dom.measureMenu.hidden;
      measureBtn.setAttribute("aria-expanded", String(!dom.measureMenu.hidden));
    };
    dom.measureMenu.querySelectorAll("[data-measure]").forEach(btn => {
      btn.onclick = () => {
        const mode = btn.dataset.measure;
        dom.measureMenu.hidden = true;
        if (state.maplib) state.maplib.setMeasure(mode);
        else {
          state.measure.mode = mode;
          state.measure.points = [];
        }
        measureBtn.classList.toggle("active", mode !== "off");
        map.getCanvas().style.cursor = mode === "off" ? "" : "crosshair";
      };
    });

    /* coordinate entry */
    root.querySelector("#geoCoordBtn").onclick = () => {
      A.modal({
        title: t("geo.enterCoords"),
        body: `<div class="geo-coord-form">
            <label for="geoCoordInput">${esc(t("geo.coordsLabel"))}</label>
            <input id="geoCoordInput" dir="ltr" placeholder="33.3152, 44.3661  ·  ${esc(dms(33.3152, true))} ${esc(dms(44.3661, false))}">
            <div class="small muted" id="geoCoordHint">${esc(t("geo.coordsHint"))}</div>
          </div>`,
        focus: "#geoCoordInput",
        buttons: [
          { label: t("common.cancel"), onClick: (close) => close() },
          { label: t("geo.goThere"), cls: "primary", onClick: async (close, body) => {
            const input = body.querySelector("#geoCoordInput");
            const hint = body.querySelector("#geoCoordHint");
            try {
              const res = await api.get(`/api/map/parse?q=${encodeURIComponent(input.value)}`);
              if (!res.ok) {
                hint.textContent = res.message || t("geo.invalidCoord");
                hint.className = "small err";
                return;
              }
              close();
              map.easeTo({ center: [res.lon, res.lat], zoom: Math.max(map.getZoom(), 10), duration: 900 });
              dropTemp(res.lat, res.lon);
            } catch (err) {
              hint.textContent = err.message;
              hint.className = "small err";
            }
          } }
        ]
      });
    };

    /* search: a name or a coordinate, both answered by the server */
    let searchTimer = null;
    dom.search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const q = dom.search.value.trim();
      if (!q) { dom.searchResults.hidden = true; return; }
      searchTimer = setTimeout(async () => {
        try {
          const res = await api.get(`/api/map/search?q=${encodeURIComponent(q)}`);
          if (mapState !== state) return;
          const rows = [];
          if (res.position) {
            rows.push(`<button class="geo-sr" data-coord="1" data-lat="${res.position.lat}" data-lon="${res.position.lon}">
              <span class="geo-sr-title" dir="ltr">${esc(res.position_label.dms)}</span>
              <span class="geo-sr-sub">${esc(t("geo.position"))}</span></button>`);
          }
          (res.results || []).forEach(r => {
            rows.push(`<button class="geo-sr" data-etype="${esc(r.entity_type)}" data-id="${r.id}"
                data-lat="${r.lat}" data-lon="${r.lon}">
              <span class="geo-sr-title" dir="auto">${esc(A.state.lang === "ar" ? (r.label_ar || r.label_en) : (r.label_en || r.label_ar))}</span>
              <span class="geo-sr-sub" dir="ltr">${esc(r.code)} · ${esc(A.state.lang === "ar" ? r.layer_ar : r.layer_en)}</span></button>`);
          });
          (res.cities || []).forEach(c => {
            rows.push(`<button class="geo-sr" data-city="1" data-lat="${c.lat}" data-lon="${c.lon}">
              <span class="geo-sr-title" dir="auto">${esc(A.state.lang === "ar" ? (c.name_ar || c.name_en) : c.name_en)}</span>
              <span class="geo-sr-sub">${esc(t("geo.city"))} · ${esc(c.country || c.iso_a2 || "")}</span></button>`);
          });
          dom.searchResults.innerHTML = rows.length ? rows.join("")
            : `<div class="geo-sr-empty small muted">${esc(t("geo.nothingFound"))}</div>`;
          dom.searchResults.hidden = false;
          dom.searchResults.querySelectorAll(".geo-sr").forEach(btn => {
            btn.onclick = () => {
              dom.searchResults.hidden = true;
              const lat = Number(btn.dataset.lat), lon = Number(btn.dataset.lon);
              map.easeTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 9), duration: 800 });
              if (btn.dataset.etype) {
                selectFeature({ entity_type: btn.dataset.etype, id: Number(btn.dataset.id) });
              } else {
                dropTemp(lat, lon);
              }
            };
          });
        } catch (e) { dom.searchResults.hidden = true; }
      }, 220);
    });

    root.querySelector("#geoCrsBtn").onclick = () => {
      state.crs = state.crs === "EPSG:4326" ? "EPSG:3857" : "EPSG:4326";
      root.querySelector("#geoCrsBtn").textContent = state.crs;
      dom.readoutPos.textContent = "—";
    };

    /* a record saved through an in-place form refreshes the map's features
       where it stands — never a rebuild around the reader */
    document.addEventListener("siraj:record-saved", onRecSaved);
    function onRecSaved(e) {
      if (!root.isConnected || mapState !== state) {
        document.removeEventListener("siraj:record-saved", onRecSaved);
        return;
      }
      e.detail.handled = true;
      loadFeatures();
    }

    document.addEventListener("keydown", onKey);
    function onKey(e) {
      /* a listener from a view that has since been left must not touch the map */
      if (!root.isConnected || mapState !== state) {
        document.removeEventListener("keydown", onKey);
        return;
      }
      if (e.key === "Escape") {
        const openMenu = !dom.layersMenu.hidden || !dom.searchResults.hidden || !dom.measureMenu.hidden;
        if (openMenu) {
          dom.layersMenu.hidden = true;
          dom.measureMenu.hidden = true;
          dom.searchResults.hidden = true;
        } else if (state.temp) {
          clearTemp();
          renderRight();
        }
      }
    }

    /* fit the workspace as soon as it is laid out */
    requestAnimationFrame(() => { map.resize(); updateScale(); });
    window.addEventListener("resize", () => { map.resize(); updateScale(); renderLabels(); });

    /* deep link: #/geo?sel=person:123 opens that record selected */
    const params = (A.state.route && A.state.route.params) || {};
    if (params.panels) {
      const [l, r] = params.panels.split(",");
      state.panels = { left: l !== "0", right: r !== "0" };
    }
    applyPanels();
  };
})();
