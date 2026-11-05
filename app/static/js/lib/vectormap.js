/* ============================================================================
   SIRAJ · lib/vectormap.js — inflate the compressed offline street pack for MapLibre
   ----------------------------------------------------------------------------
   The server ships `gaza.vectormap.json(.gz)`: delta-packed OSM polylines plus
   place/area labels. This module unpacks them into GeoJSON FeatureCollections
   the map can add as sources. No registry access; pure cartography.
   ========================================================================== */
(function (A) {
  "use strict";

  function unpack(p) {
    const out = [];
    let la = 0, lg = 0;
    if (!Array.isArray(p)) return out;
    for (let i = 0; i + 1 < p.length; i += 2) {
      la += p[i]; lg += p[i + 1];
      out.push([lg / 1e5, la / 1e5]); /* GeoJSON is [lon, lat] */
    }
    return out;
  }

  function lineFeatures(list, kind) {
    const features = [];
    for (const f of (list || [])) {
      const coords = unpack(f.p);
      if (coords.length < 2) continue;
      features.push({
        type: "Feature",
        properties: { k: f.k || kind, n: f.n || "", kind },
        geometry: { type: "LineString", coordinates: coords }
      });
    }
    return features;
  }

  function polyFeatures(list, kind) {
    const features = [];
    for (const f of (list || [])) {
      const coords = unpack(f.p);
      if (coords.length < 3) continue;
      const ring = coords.slice();
      const a = ring[0], b = ring[ring.length - 1];
      if (a[0] !== b[0] || a[1] !== b[1]) ring.push(a.slice());
      features.push({
        type: "Feature",
        properties: { k: f.k || kind, n: f.n || "", kind },
        geometry: { type: "Polygon", coordinates: [ring] }
      });
    }
    return features;
  }

  function pointFeatures(list, kind) {
    const features = [];
    for (const f of (list || [])) {
      if (!Number.isFinite(f.lat) || !Number.isFinite(f.lng)) continue;
      features.push({
        type: "Feature",
        properties: {
          k: f.k || kind, r: f.r || 1,
          n: f.n || "", na: f.na || "", ne: f.ne || "",
          kind
        },
        geometry: { type: "Point", coordinates: [f.lng, f.lat] }
      });
    }
    return features;
  }

  /**
   * @param {object} bm raw vectormap JSON (v1 or v2)
   * @returns {{ roads, water, green, places, bbox, stats }}
   */
  A.inflateVectormap = function inflateVectormap(bm) {
    if (!bm || typeof bm !== "object") throw new Error("invalid vectormap");
    const roads = {
      type: "FeatureCollection",
      features: lineFeatures(bm.roads, "road").concat(lineFeatures(bm.rail, "rail"))
    };
    const water = {
      type: "FeatureCollection",
      features: polyFeatures(bm.water, "water").concat(lineFeatures(bm.waterLines, "water"))
    };
    const green = {
      type: "FeatureCollection",
      features: polyFeatures(bm.green, "green")
    };
    const places = {
      type: "FeatureCollection",
      features: pointFeatures(bm.places, "place").concat(pointFeatures(bm.areas || [], "area"))
    };
    return {
      v: bm.v || 1,
      bbox: bm.bbox,
      source: bm.source || "",
      roads, water, green, places,
      stats: {
        roads: (bm.roads || []).length,
        places: (bm.places || []).length,
        areas: (bm.areas || []).length
      }
    };
  };

  /** Fetch the bundled pack (prefers gzip). Cached on A._vectormapCache. */
  A.loadVectormap = async function loadVectormap() {
    if (A._vectormapCache) return A._vectormapCache;
    const res = await fetch("/api/geo/vectormap", {
      headers: { "Accept-Encoding": "gzip" },
      credentials: "same-origin"
    });
    if (!res.ok) throw new Error("vectormap unavailable");
    const raw = await res.json();
    const inflated = A.inflateVectormap(raw);
    A._vectormapCache = inflated;
    return inflated;
  };

  /**
   * Paint the street pack onto a MapLibre map. Idempotent: replaces sources.
   * Layers sit under registry markers (beforeId optional).
   */
  A.applyVectormapLayers = function applyVectormapLayers(map, inflated, opts) {
    opts = opts || {};
    if (!map || !inflated) return;
    const before = opts.beforeId || null;
    const add = (id, source, layers) => {
      if (map.getSource(id)) {
        map.getSource(id).setData(source);
      } else {
        map.addSource(id, { type: "geojson", data: source });
      }
      for (const layer of layers) {
        if (map.getLayer(layer.id)) continue;
        const spec = Object.assign({}, layer, { source: id });
        if (before && map.getLayer(before)) map.addLayer(spec, before);
        else map.addLayer(spec);
      }
    };

    add("vm-green", inflated.green, [{
      id: "vm-green-fill", type: "fill",
      paint: { "fill-color": "#c5ddb0", "fill-opacity": 0.55 }
    }]);
    add("vm-water", inflated.water, [
      { id: "vm-water-fill", type: "fill", filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#a8c8e0", "fill-opacity": 0.7 } },
      { id: "vm-water-line", type: "line", filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#6a9cc4", "line-width": 1.2 } }
    ]);
    add("vm-roads", inflated.roads, [
      { id: "vm-roads-major", type: "line",
        filter: ["in", ["get", "k"], ["literal", ["motorway", "trunk", "primary", "secondary", "major"]]],
        paint: { "line-color": "#c9a06a", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.2, 16, 4] } },
      { id: "vm-roads-minor", type: "line",
        filter: ["!", ["in", ["get", "k"], ["literal", ["motorway", "trunk", "primary", "secondary", "major"]]]],
        paint: { "line-color": "#b8b0a4", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.4, 16, 1.8] } }
    ]);
    add("vm-places", inflated.places, [{
      id: "vm-places-dot", type: "circle",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "r"], 1, 2, 6, 5],
        "circle-color": "#5a4632",
        "circle-opacity": 0.85,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#fff8ec"
      },
      minzoom: 12
    }]);

    if (opts.fit && inflated.bbox) {
      const b = inflated.bbox;
      map.fitBounds([[b.w, b.s], [b.e, b.n]], { padding: 40, duration: opts.animate === false ? 0 : 800 });
    }
  };

  A.removeVectormapLayers = function removeVectormapLayers(map) {
    if (!map) return;
    ["vm-places-dot", "vm-roads-minor", "vm-roads-major", "vm-water-line", "vm-water-fill", "vm-green-fill"]
      .forEach(id => { try { if (map.getLayer(id)) map.removeLayer(id); } catch (e) { /* style swap */ } });
    ["vm-places", "vm-roads", "vm-water", "vm-green"]
      .forEach(id => { try { if (map.getSource(id)) map.removeSource(id); } catch (e) { /* */ } });
  };
})(window.App || (window.App = {}));
