/* ============================================================================
   SIRAJ · lib/tilecache.js — automatic offline tile memory
   ----------------------------------------------------------------------------
   Two tiers, one contract:

     L1  IndexedDB in the browser  — survives reload, works with no server
     L2  /api/geo/browse-cache/*   — durable SQLite on disk, shared sessions

   Every raster tile the map actually asks for is stored (gzip on the server,
   raw ArrayBuffer in IDB). On the next visit — online or offline — the same
   window paints from the cache. Styles are rewritten to the `siraj://tile/…`
   protocol so MapLibre never talks to third-party hosts directly once the
   cache layer is installed.
   ========================================================================== */
(function (A) {
  "use strict";

  const DB_NAME = "siraj-tile-cache";
  const DB_VER = 1;
  const STORE = "tiles";
  const META = "meta";
  const MAX_ENTRIES = 12000;          /* ~ soft cap; oldest evicted on write */
  const PROTO = "siraj";

  let dbPromise = null;
  let protocolReady = false;
  let stats = { hits: 0, misses: 0, writes: 0, bytes: 0, entries: 0 };

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error("IndexedDB unavailable")); return; }
      const req = indexedDB.open(DB_NAME, DB_VER);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          const os = db.createObjectStore(STORE, { keyPath: "key" });
          os.createIndex("touched", "touched", { unique: false });
          os.createIndex("provider", "provider", { unique: false });
        }
        if (!db.objectStoreNames.contains(META)) {
          db.createObjectStore(META, { keyPath: "id" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error("IDB open failed"));
    });
    return dbPromise;
  }

  function idbGet(key) {
    return openDb().then(db => new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).get(key);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    })).catch(() => null);
  }

  function idbPut(row) {
    return openDb().then(db => new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(row);
      tx.oncomplete = () => { stats.writes += 1; resolve(true); };
      tx.onerror = () => reject(tx.error);
    })).then(() => maybeEvict()).catch(() => false);
  }

  function maybeEvict() {
    return openDb().then(db => new Promise((resolve) => {
      const tx = db.transaction(STORE, "readwrite");
      const os = tx.objectStore(STORE);
      const countReq = os.count();
      countReq.onsuccess = () => {
        stats.entries = countReq.result;
        if (countReq.result <= MAX_ENTRIES) { resolve(); return; }
        const idx = os.index("touched");
        const drop = countReq.result - MAX_ENTRIES + 200;
        let removed = 0;
        idx.openCursor().onsuccess = (e) => {
          const cursor = e.target.result;
          if (!cursor || removed >= drop) return;
          cursor.delete();
          removed += 1;
          cursor.continue();
        };
      };
      tx.oncomplete = () => resolve();
    })).catch(() => {});
  }

  function tileKey(provider, src, z, x, y) {
    return `${provider}|${src}|${z}|${x}|${y}`;
  }

  async function fetchUpstream(provider, src, z, x, y) {
    const url = `/api/geo/browse-cache/${encodeURIComponent(provider)}/${z}/${x}/${y}` +
      `?src=${encodeURIComponent(src || "base")}`;
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`tile ${res.status}`);
    const buf = await res.arrayBuffer();
    const ctype = res.headers.get("content-type") || "image/png";
    return { data: buf, contentType: ctype };
  }

  async function loadTile(provider, src, z, x, y) {
    const key = tileKey(provider, src, z, x, y);
    const cached = await idbGet(key);
    if (cached && cached.data) {
      stats.hits += 1;
      /* touch asynchronously */
      idbPut(Object.assign({}, cached, { touched: Date.now() }));
      return { data: cached.data, cacheControl: "max-age=86400" };
    }
    stats.misses += 1;
    try {
      const got = await fetchUpstream(provider, src, z, x, y);
      await idbPut({
        key, provider, src, z, x, y,
        data: got.data,
        contentType: got.contentType,
        touched: Date.now(),
        bytes: got.data.byteLength
      });
      stats.bytes += got.data.byteLength;
      return { data: got.data, cacheControl: "max-age=86400" };
    } catch (err) {
      /* last resort: transparent 1×1 PNG so MapLibre does not abort the style */
      const empty = Uint8Array.from([
        0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0x00,0x00,0x00,0x0d,0x49,0x48,0x44,0x52,
        0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x06,0x00,0x00,0x00,0x1f,0x15,0xc4,
        0x89,0x00,0x00,0x00,0x0a,0x49,0x44,0x41,0x54,0x78,0x9c,0x63,0x00,0x01,0x00,0x00,
        0x05,0x00,0x01,0x0d,0x0a,0x2d,0xb4,0x00,0x00,0x00,0x00,0x49,0x45,0x4e,0x44,0xae,
        0x42,0x60,0x82
      ]);
      return { data: empty.buffer };
    }
  }

  function installProtocol() {
    if (protocolReady || !window.maplibregl || !window.maplibregl.addProtocol) return false;
    try {
      window.maplibregl.addProtocol(PROTO, (params) => {
        /* siraj://tile/{provider}/{src}/{z}/{x}/{y} */
        const path = String(params.url || "").replace(/^siraj:\/\/tile\//, "");
        const parts = path.split("/");
        if (parts.length < 5) {
          return Promise.reject(new Error("bad siraj tile url"));
        }
        const [provider, src, z, x, y] = parts;
        return loadTile(provider, src, Number(z), Number(x), Number(y));
      });
      protocolReady = true;
      return true;
    } catch (e) {
      return false;
    }
  }

  /**
   * Rewrite a MapLibre style so every raster source pulls through the cache
   * protocol. Vector-local styles (no tiles) are returned unchanged.
   */
  function wrapStyle(provider) {
    installProtocol();
    if (!provider || !provider.style) return provider && provider.style;
    const style = JSON.parse(JSON.stringify(provider.style));
    if (provider.kind === "vector-local" || provider.kind === "vector-streets") return style;
    const sources = style.sources || {};
    Object.keys(sources).forEach(sid => {
      const src = sources[sid];
      if (!src || src.type !== "raster") return;
      /* keep attribution; replace tile endpoints with the cache protocol */
      src.tiles = [`${PROTO}://tile/${provider.id}/${sid}/{z}/{x}/{y}`];
      delete src.url;
    });
    return style;
  }

  async function refreshStats() {
    try {
      const db = await openDb();
      stats.entries = await new Promise((resolve) => {
        const tx = db.transaction(STORE, "readonly");
        const req = tx.objectStore(STORE).count();
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(0);
      });
      const remote = await fetch("/api/geo/browse-cache/stats").then(r => r.ok ? r.json() : null).catch(() => null);
      return { local: { ...stats }, remote: remote && remote.stats ? remote.stats : null };
    } catch (e) {
      return { local: { ...stats }, remote: null };
    }
  }

  async function clearLocal() {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    stats = { hits: 0, misses: 0, writes: 0, bytes: 0, entries: 0 };
  }

  async function clearAll() {
    await clearLocal();
    try { await fetch("/api/geo/browse-cache", { method: "DELETE" }); } catch (e) { /* */ }
  }

  A.tilecache = {
    installProtocol, wrapStyle, refreshStats, clearLocal, clearAll,
    stats: () => ({ ...stats }),
    ready: () => protocolReady
  };

  /* install early so the first map style can use the protocol */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installProtocol);
  } else {
    installProtocol();
  }
})(window.App || (window.App = {}));
