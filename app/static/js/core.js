/* ============================================================================
   SIRAJ · core.js — state, i18n, API client, UI primitives, charts
   No external dependencies: everything renders from inline SVG + DOM.
   ========================================================================== */
(function () {
  "use strict";

  const FALLBACK = {
    en: { "common.loading": "Loading…", "common.save": "Save", "common.cancel": "Cancel" },
    ar: { "common.loading": "جارٍ التحميل…", "common.save": "حفظ", "common.cancel": "إلغاء" }
  };

  /* Languages are data, not code: locales/index.json is the single place that
     declares which languages exist, their direction and their display name.
     Adding a language = drop locales/<code>.json + one manifest entry. */
  const LOCALE_MANIFEST = "/static/js/locales/index.json";
  const DEFAULT_LOCALES = [
    { code: "ar", name: "العربية", en_name: "Arabic", dir: "rtl", default: true },
    { code: "en", name: "English", en_name: "English", dir: "ltr" }
  ];

  const App = window.App = {
    state: {
      lang: localStorage.getItem("siraj.lang") || "ar",
      theme: localStorage.getItem("siraj.theme") || "light",
      actor: localStorage.getItem("siraj.actor") || "researcher",
      density: "comfortable",
      views: {},
      meta: null,
      locales: DEFAULT_LOCALES.slice(),
      messages: {},
      route: null
    }
  };

  /* ------------------------------------------------------------- i18n --- */
  function t(key, vars) {
    const bundle = App.state.messages[App.state.lang] || {};
    const en = App.state.messages.en || {};
    // resolution order: active language → English → built-in safety net → key.
    // A partially translated language therefore degrades gracefully.
    let s = bundle[key] || en[key] || (FALLBACK[App.state.lang] || {})[key] || key;
    if (vars) Object.keys(vars).forEach(k => { s = s.replace(new RegExp("\\{" + k + "\\}", "g"), vars[k]); });
    return s;
  }

  async function loadManifest() {
    try {
      const res = await fetch(LOCALE_MANIFEST, { cache: "no-cache" });
      if (!res.ok) throw new Error("missing manifest");
      const list = await res.json();
      if (Array.isArray(list) && list.length) App.state.locales = list;
    } catch (e) {
      App.state.locales = DEFAULT_LOCALES.slice();
    }
    return App.state.locales;
  }

  function localeInfo(code) {
    const list = App.state.locales || DEFAULT_LOCALES;
    return list.find(l => l.code === (code || App.state.lang)) || list[0] || DEFAULT_LOCALES[0];
  }

  async function loadMessages(lang) {
    if (App.state.messages[lang]) return App.state.messages[lang];
    try {
      const res = await fetch(`/static/js/locales/${lang}.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error("missing bundle");
      App.state.messages[lang] = await res.json();
    } catch (e) {
      App.state.messages[lang] = Object.assign({}, FALLBACK[lang] || {});
    }
    return App.state.messages[lang];
  }

  function setLang(lang, opts) {
    App.state.lang = lang;
    localStorage.setItem("siraj.lang", lang);
    applyDir();
    document.querySelectorAll("[data-i18n]").forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    if (App.rerender && !(opts && opts.silent)) App.rerender();
  }

  function applyDir() {
    const rtl = localeInfo().dir === "rtl";
    // the toggle advertises the language you would switch *to*, which is the
    // only unambiguous label when three or more locales are installed
    const btn = document.getElementById("langToggle");
    if (btn) {
      const next = (App.state.locales || []).find(l => l.code !== App.state.lang) || {};
      const SHORT = { ar: "ع", en: "EN", fr: "FR", tr: "TR", fa: "ف", ur: "ا" };
      btn.textContent = SHORT[next.code] || String(next.code || "").toUpperCase();
      btn.title = (App.state.locales || [])
        .map(l => l.name_native || l.name || l.code).join(" / ");
      btn.setAttribute("aria-label", `${App.state.lang} → ${next.code || ""}`);
    }
    document.documentElement.lang = App.state.lang;
    document.documentElement.dir = rtl ? "rtl" : "ltr";
  }

  /* --------------------------------------------------------- preferences --- */
  /**
   * Two layers, deliberately:
   *   · the *instance* default lives in the database (`setting` table, admin),
   *   · a *personal* override lives in localStorage, because how a person likes
   *     to type is a preference, not a policy.
   * `pref()` resolves both and never returns junk.
   */
  const PREFS = {
    theme: { key: "siraj.theme", fallback: "default",
             allowed: ["default", "light", "dark", "system"] },
    density: { key: "siraj.density", fallback: "default",
               allowed: ["default", "comfortable", "compact"] },
    page_size: { key: "siraj.page_size", fallback: "default", allowed: null,
                 check: (v) => /^\d+$/.test(v) && Number(v) >= 5 && Number(v) <= 500 },
    language: { key: "siraj.lang", fallback: "default", allowed: null },
    form_mode: { key: "siraj.form_mode", fallback: "default",
                 allowed: ["default", "page", "dialog", "auto"] },
    form_dialog_size: { key: "siraj.form_dialog_size", fallback: "default",
                        allowed: ["default", "wide", "xl"] }
  };

  function pref(name, fallback) {
    const spec = PREFS[name];
    if (!spec) return localStorage.getItem("siraj." + name) || fallback;
    const local = localStorage.getItem(spec.key);
    const ok = local && (spec.allowed ? spec.allowed.includes(local)
                                      : (spec.check ? spec.check(local) : true));
    if (ok) return local;
    return fallback === undefined ? spec.fallback : fallback;
  }

  function setPref(name, value) {
    const spec = PREFS[name];
    const key = spec ? spec.key : "siraj." + name;
    if (spec) {
      if (spec.allowed && !spec.allowed.includes(value)) return false;
      if (!spec.allowed && spec.check && !spec.check(String(value))) return false;
    }
    if (value === "default" || value === null || value === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
    document.dispatchEvent(new CustomEvent("siraj:pref", { detail: { name, value } }));
    return true;
  }

  /** Personal preference if the person set one, otherwise the instance value. */
  function resolvePref(prefName, settingName, fallback) {
    const personal = pref(prefName, "default");
    if (personal !== "default" && personal !== "") return personal;
    return setting(settingName, fallback);
  }

  function theme() { return resolvePref("theme", "display.theme", "light"); }
  function density() { return resolvePref("density", "display.density", "comfortable"); }

  function pageSize() {
    const n = Number(resolvePref("page_size", "display.page_size", "25"));
    return Number.isFinite(n) && n >= 5 && n <= 500 ? Math.round(n) : 25;
  }

  /**
   * Paint the appearance settings.  `system` follows the operating system and
   * keeps following it: the media query is listened to, not sampled once.
   */
  let systemQuery = null;
  function applyAppearance() {
    const want = theme();
    const dark = want === "dark" ||
      (want === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.dataset.themeChoice = want;
    const dense = density() === "compact";
    document.body.classList.toggle("density-compact", dense);
    App.state.theme = want;
    App.state.density = dense ? "compact" : "comfortable";
    if (!systemQuery) {
      systemQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const reapply = () => { if (theme() === "system") applyAppearance(); };
      if (systemQuery.addEventListener) systemQuery.addEventListener("change", reapply);
      else if (systemQuery.addListener) systemQuery.addListener(reapply);
    }
    document.dispatchEvent(new CustomEvent("siraj:appearance",
      { detail: { theme: want, density: App.state.density } }));
  }

  /** The instance-wide value of a setting, as served by /api/meta. */
  function setting(name, fallback) {
    const all = (App.state.meta && App.state.meta.settings) || {};
    const v = all[name];
    return (v === undefined || v === null || v === "") ? fallback : String(v);
  }

  /** Which surface data-entry opens on: "page" or "dialog" ("auto" resolved). */
  function formMode() {
    const personal = pref("form_mode", "default");
    const chosen = personal !== "default" ? personal : setting("ui.form_mode", "page");
    if (chosen === "auto") {
      return window.matchMedia("(min-width: 960px)").matches ? "dialog" : "page";
    }
    return chosen === "dialog" ? "dialog" : "page";
  }

  /** Same answer, but tells the caller *why* — needed by the settings screen. */
  function formModeSource() {
    const personal = pref("form_mode", "default");
    if (personal !== "default") return { mode: personal, source: "personal" };
    const instance = setting("ui.form_mode", "page");
    return { mode: instance, source: "instance" };
  }

  /** The default base map for every map surface that has one: the personal
   *  choice for this browser, else the instance setting, else the offline pack.
   *  Honoured by the map workspace, the record panels, the list maps and the
   *  desk — one answer wherever maps appear. */
  function mapDefault() {
    return { provider: resolvePref("map_provider", "map.provider", "local") };
  }

  /** /api/map/config, fetched once per page: provider catalogue with styles,
   *  families, and the offline pack inventory. */
  let mapConfigCache = null;
  function mapConfig() {
    if (!mapConfigCache) {
      mapConfigCache = fetch("/api/map/config").then(r => {
        if (!r.ok) throw new Error("map config " + r.status);
        return r.json();
      }).catch(err => {
        mapConfigCache = null;
        throw err;
      });
    }
    return mapConfigCache;
  }

  App.pref = pref;
  App.setPref = setPref;
  App.setting = setting;
  App.resolvePref = resolvePref;
  App.mapDefault = mapDefault;
  App.mapConfig = mapConfig;
  App.theme = theme;
  App.density = density;
  App.pageSize = pageSize;
  App.applyAppearance = applyAppearance;
  App.formMode = formMode;
  App.formModeSource = formModeSource;
  App.formDialogSize = function () {
    const personal = pref("form_dialog_size", "default");
    return personal !== "default" ? personal : setting("ui.form_dialog_size", "xl");
  };

  function setTheme(value) {
    setPref("theme", value);
    applyAppearance();
  }

  /* -------------------------------------------------------------- API --- */
  async function request(method, url, body, opts) {
    opts = opts || {};
    const headers = Object.assign({
      "X-Actor": App.state.actor,
      /* every request may touch the military facade; the workspace role
         selector persists this key and the API re-checks it server-side */
      "X-Military-Role": (function () {
        try { return localStorage.getItem("siraj.mil.role") || "admin"; }
        catch (e) { return "admin"; }
      })()
    }, opts.headers || {});
    let payload;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    const res = await fetch(url, { method, headers, body: payload });
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const msg = (data && data.error) ? data.error :
        (typeof data === "string" ? data : `HTTP ${res.status}`);
      const err = new Error(msg); err.status = res.status; err.payload = data;
      throw err;
    }
    return data;
  }

  const api = {
    get: (u) => request("GET", u),
    post: (u, b) => request("POST", u, b === undefined ? {} : b),
    put: (u, b) => request("PUT", u, b),
    del: (u) => request("DELETE", u),
    upload: (u, fd) => request("POST", u, fd),
    raw: request
  };

  /* --------------------------------------------------------- metadata --- */
  function entitySpec(key) {
    return (App.state.meta.entities || []).find(e => e.key === key);
  }
  function fieldsOf(key) {
    return (App.state.meta.fields || {})[key] || [];
  }
  function label(entityKey) {
    const e = entitySpec(entityKey);
    if (!e) return entityKey;
    return App.state.lang === "ar" ? e.label_ar : e.label_en;
  }
  function pluralOf(entityKey) {
    const e = entitySpec(entityKey);
    if (!e) return entityKey;
    return App.state.lang === "ar" ? e.plural_ar : e.plural_en;
  }
  function fieldLabel(f) {
    if (!f) return "";
    return App.state.lang === "ar" ? (f.label_ar || f.label_en) : (f.label_en || f.label_ar);
  }
  function fieldLabelSafe(f) {
    if (!f) return "";
    return fieldLabel(f) || f.key || "";
  }
  function dispTitle(rec, entityKey) {
    if (!rec) return "";
    const order = App.state.lang === "ar"
      ? ["name_ar", "title_ar", "title", "name_original", "name_en", "title_en"]
      : ["name_en", "name_original", "name_ar", "title", "title_en", "title_ar"];
    for (const k of order) if (rec[k]) return String(rec[k]);
    return rec._title || rec.code || "";
  }
  function domainOptions(domain) {
    return ((App.state.meta.lookups || {})[domain] || []);
  }
  function lookupById(id) {
    if (id == null || id === "") return null;
    const want = Number(id);
    const all = App.state.meta.lookups || {};
    for (const d of Object.keys(all)) {
      const hit = all[d].find(x => Number(x.id) === want);
      if (hit) return hit;
    }
    return null;
  }

  /* ----------------------------------------------------------- format --- */
  function fmtNum(n) {
    if (n === null || n === undefined || n === "") return "—";
    /* Latin digits in both languages: registry figures, codes and years stay
       unambiguous and match what appears in exports and reports. */
    return Number(n).toLocaleString("en-US");
  }
  function fmtDate(v, withTime) {
    if (!v) return "—";
    const s = String(v);
    if (/^\d{3,4}$/.test(s)) return s;
    const d = new Date(/T/.test(s) ? s : s + "T00:00:00Z");
    if (isNaN(d)) return s;
    const opts = withTime
      ? { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }
      : { year: "numeric", month: "short", day: "2-digit" };
    return d.toLocaleDateString(App.state.lang === "ar" ? "ar-EG" : "en-GB", opts);
  }
  function ago(v) {
    if (!v) return "—";
    const d = new Date(v); if (isNaN(d)) return fmtDate(v, true);
    const secs = (Date.now() - d.getTime()) / 1000;
    const units = [[31536000, "y"], [2592000, "mo"], [86400, "d"], [3600, "h"], [60, "m"]];
    for (const [s, u] of units) {
      if (secs >= s) {
        return t("time.ago", { n: Math.floor(secs / s), u: t("time.unit." + u) });
      }
    }
    return t("time.justNow");
  }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function truncate(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }
  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/).slice(0, 2);
    return parts.map(p => p[0] || "").join("");
  }

  /* ------------------------------------------------------------ icons --- */
  const PATHS = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5S20 17 20 21"/>',
    users: '<circle cx="9" cy="8" r="3.4"/><path d="M2.5 20c0-3.6 2.9-5.6 6.5-5.6s6.5 2 6.5 5.6"/><path d="M17 5.2a3.4 3.4 0 010 6.4M18 14.6c2.4.5 4 2.3 4 5.4"/>',
    building: '<rect x="4" y="3" width="16" height="18" rx="1.6"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2"/>',
    "map-pin": '<path d="M12 21s7-5.6 7-11a7 7 0 10-14 0c0 5.4 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/>',
    link: '<path d="M9.5 14.5l5-5"/><path d="M8 17H6.5a3.5 3.5 0 010-7H9M16 7h1.5a3.5 3.5 0 010 7H15"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 016.5 3H20v15H6.5A2.5 2.5 0 004 20.5z"/><path d="M4 18.5A2.5 2.5 0 016.5 16H20"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
    upload: '<path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M4 16v3.5A1.5 1.5 0 005.5 21h13a1.5 1.5 0 001.5-1.5V16"/>',
    download: '<path d="M12 4v12m0 0l-4.5-4.5M12 16l4.5-4.5"/><path d="M4 16v3.5A1.5 1.5 0 005.5 21h13a1.5 1.5 0 001.5-1.5V16"/>',
    history: '<path d="M3.5 12a8.5 8.5 0 108.5-8.5A8.5 8.5 0 005 7"/><path d="M3.5 3v4.5H8"/><path d="M12 7.5V12l3 2"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    hash: '<path d="M9 3L7 21M17 3l-2 18M4 9h16M3 15h16"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5l1.4 2.4 2.7-.6.6 2.7 2.4 1.4-1.3 2.5 1.3 2.5-2.4 1.4-.6 2.7-2.7-.6L12 21.5l-1.4-2.4-2.7.6-.6-2.7L4.9 15.6l1.3-2.5-1.3-2.5 2.4-1.4.6-2.7 2.7.6z"/>',
    database: '<ellipse cx="12" cy="6" rx="8" ry="3.2"/><path d="M4 6v12c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2V6"/><path d="M4 12c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="M4.5 12.5l5 5L20 7"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.5 9"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    share: '<circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="6" r="2.6"/><circle cx="18" cy="18" r="2.6"/><path d="M8.4 10.8l7.2-3.6M8.4 13.2l7.2 3.6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.5l3.5 2"/>',
    activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    filter: '<path d="M3.5 5h17l-6.5 8v6l-4 2v-8z"/>',
    edit: '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="M14.5 5.5L18.5 9.5"/>',
    trash: '<path d="M4 7h16M9 7V4.5h6V7M6.5 7l.9 13h9.2l.9-13"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    save: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7M8 20v-6h8v6"/>',
    undo: '<path d="M9 8H4V3"/><path d="M4 8a8 8 0 1116 3"/>',
    print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="1.5"/><path d="M7 14h10v6H7z"/>',
    columns: '<rect x="3.5" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="16" rx="1"/><rect x="16.5" y="4" width="4" height="16" rx="1"/>',
    file: '<path d="M6 3h7l5 5v13H6z"/><path d="M13 3v5h5"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    ruler: '<path d="M3 15.5L15.5 3 21 8.5 8.5 21z"/><path d="M8 11l2 2M11 8l2 2M14 5l2 2"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    crosshair: '<circle cx="12" cy="12" r="7"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/>',
    "panel-left": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "panel-right": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    maximize: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    minimize: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 3 2.6 15 0 18M12 3c-2.6 3-2.6 15 0 18"/>',
    shield: '<path d="M12 2.5l8 3v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z"/><path d="M8.5 12l2.5 2.5 4.5-4.5"/>'
  };
  function icon(name, cls) {
    const p = PATHS[name] || PATHS.grid;
    return `<span class="ico ${cls || ""}"><svg viewBox="0 0 24 24" aria-hidden="true">${p}</svg></span>`;
  }
  function hydrateIcons(root) {
    (root || document).querySelectorAll("[data-icon]").forEach(el => {
      if (el.dataset.done) return;
      el.innerHTML = `<svg viewBox="0 0 24 24">${PATHS[el.dataset.icon] || PATHS.grid}</svg>`;
      el.dataset.done = "1";
    });
  }

  /* ----------------------------------------------------------- toasts --- */
  function toast(msg, type, ms) {
    const box = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = "toast " + (type || "");
    el.innerHTML = `<div>${esc(msg)}</div>`;
    box.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(6px)";
      setTimeout(() => el.remove(), 220); }, ms || 3800);
  }

  /* ------------------------------------------------------------ modal --- */
  /**
   * The one dialog primitive.  Everything the product puts on top of a page uses
   * it, so everything behaves the same:
   *
   *   · a real `role="dialog"` + `aria-modal` + a labelled title;
   *   · focus moves in, then cycles inside (Tab / Shift+Tab never escape);
   *   · `Escape` and a backdrop click ask to close — and can be *refused*
   *     (`onRequestClose`), which is how an unsaved draft survives an accident;
   *   · closing returns focus to whatever opened it;
   *   · the page behind is locked while any dialog is open (a counter, so nested
   *     dialogs — a combobox "create new source" inside a form — behave).
   */
  const MODAL_SIZES = { slim: "slim", wide: "wide", xl: "xl", full: "full" };
  let openModals = 0;
  let lastFocus = null;
  let modalSeq = 0;
  const modalStack = [];        // the topmost dialog owns Escape and Tab

  function lockScroll(on) {
    openModals = Math.max(0, openModals + (on ? 1 : -1));
    document.body.classList.toggle("modal-open", openModals > 0);
  }

  function focusables(root) {
    return Array.from(root.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),' +
      'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
    )).filter(el => el.offsetParent !== null || el === document.activeElement);
  }

  function modal(opts) {
    opts = opts || {};
    const root = document.getElementById("modalRoot");
    if (!lastFocus || !document.body.contains(lastFocus)) lastFocus = document.activeElement;
    const back = document.createElement("div");
    back.className = "modal-back";
    const size = MODAL_SIZES[opts.size] || "";
    const id = "modal-title-" + (++modalSeq);
    const extraCls = opts.cls ? ` ${opts.cls}` : "";
    back.innerHTML = `
      <div class="modal ${size}${extraCls}" role="dialog" aria-modal="true" aria-labelledby="${id}"
           ${opts.describedBy ? `aria-describedby="${esc(opts.describedBy)}"` : ""}>
        <div class="modal-head">
          ${opts.mark || ""}
          <div class="modal-title" tabindex="-1">
            <h3 id="${id}">${esc(opts.title || "")}</h3>
            ${opts.subtitle ? `<div class="modal-sub">${esc(opts.subtitle)}</div>` : ""}
          </div>
          <div class="spacer"></div>
          ${opts.headActions || ""}
          <button class="icon-btn" data-close aria-label="${esc(t("common.close") || "close")}">${icon("x")}</button>
        </div>
        <div class="modal-body"></div>
        ${opts.footer === false ? "" : '<div class="modal-foot"></div>'}
      </div>`;
    root.appendChild(back);
    lockScroll(true);
    modalStack.push(back);

    const shell = back.querySelector(".modal");
    const body = back.querySelector(".modal-body");
    const foot = back.querySelector(".modal-foot");
    if (typeof opts.body === "string") body.innerHTML = opts.body;
    else if (opts.body) body.appendChild(opts.body);
    if (opts.buttons && foot) {
      opts.buttons.forEach(b => {
        const btn = document.createElement("button");
        btn.className = "btn " + (b.cls || "");
        btn.textContent = b.label;
        btn.onclick = () => b.onClick ? b.onClick(close, body) : close();
        foot.appendChild(btn);
      });
    }

    let closed = false;
    let busy = false;

    async function requestClose(reason) {
      if (closed || busy) return false;
      if (opts.onRequestClose) {
        busy = true;
        let allow = false;
        try { allow = await opts.onRequestClose(reason); }
        finally { busy = false; }
        if (!allow) return false;
      }
      close(reason);
      return true;
    }

    function close(reason) {
      if (closed) return;
      closed = true;
      const at = modalStack.indexOf(back);
      if (at >= 0) modalStack.splice(at, 1);
      back.classList.add("closing");
      lockScroll(false);
      document.removeEventListener("keydown", onKey, true);
      const finish = () => {
        back.remove();
        if (opts.restoreFocus !== false && lastFocus && document.body.contains(lastFocus)) {
          try { lastFocus.focus({ preventScroll: true }); } catch (e) { /* detached */ }
        }
        if (opts.onClose) opts.onClose(reason);
      };
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
      else setTimeout(finish, 90);
    }

    function onKey(e) {
      /* a confirmation opened on top of this dialog handles its own keys */
      if (modalStack[modalStack.length - 1] !== back) return;
      if (closed) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        if (opts.dismissable === false) return;
        e.preventDefault();
        requestClose("escape");
        return;
      }
      if (e.key !== "Tab") return;
      const list = focusables(shell);
      if (!list.length) return;
      const first = list[0], last = list[list.length - 1];
      if (e.shiftKey && (document.activeElement === first || !shell.contains(document.activeElement))) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    back.querySelectorAll("[data-close]").forEach(b => {
      b.onclick = () => (opts.dismissable === false ? null : requestClose("button"));
    });
    back.addEventListener("mousedown", e => {
      if (e.target === back && opts.dismissable !== false) requestClose("backdrop");
    });
    hydrateIcons(back);
    setTimeout(() => {
      if (opts.noFocus) return;
      /* `focus` resolves against the whole dialog, so a view can park the
         cursor on the heading instead of on the first (possibly destructive)
         control; the heading carries tabindex="-1" for exactly that. */
      const target = (opts.focus && shell.querySelector(opts.focus)) ||
                     focusables(body)[0] || shell;
      if (target && target.focus) target.focus({ preventScroll: true });
    }, 40);

    return { close, requestClose, body, foot, back, shell,
             setTitle: (txt) => {
               const h = back.querySelector(`#${id}`);
               if (h) h.textContent = txt;
             } };
  }

  function confirmDialog(opts) {
    return new Promise(resolve => {
      /* the answer must be captured *before* the dialog closes: closing fires
         onClose, and a late resolve() would be ignored — which used to make
         every confirmation resolve to "cancelled". */
      let settled = false;
      const answer = (value) => { if (!settled) { settled = true; resolve(value); } };
      /* requirePhrase: destructive actions make the person type the exact
         phrase (e.g. "CLEAR ALL DATA") before the confirm button engages. */
      const phrase = opts.requirePhrase || "";
      const m = modal({
        title: opts.title || t("common.confirm"), size: "slim",
        body: `<p>${opts.message || ""}</p>` + (opts.extra || "") +
          (phrase ? `<div class="field" style="margin-top:10px">
            <label class="small muted">${esc(t("common.typeToConfirm"))}</label>
            <input type="text" id="__confirmPhrase" class="grow" autocomplete="off"
                   spellcheck="false" placeholder="${esc(phrase)}">
          </div>` : ""),
        buttons: [
          { label: opts.cancelLabel || t("common.cancel"), cls: "", onClick: (c) => { answer(false); c(); } },
          { label: opts.confirmLabel || t("common.confirm"),
            cls: opts.danger ? "danger" : "primary", onClick: (c, bodyEl) => {
              if (phrase) {
                const inp = bodyEl ? bodyEl.querySelector("#__confirmPhrase") : null;
                if (!inp || inp.value.trim() !== phrase) {
                  toast(t("common.typeToConfirm"), "err");
                  return;                       // keep the dialog open
                }
              }
              answer(true); c();
            } }
        ],
        onClose: () => answer(false)
      });
      return m;
    });
  }

  function drawer(opts) { return modal(Object.assign({ size: "wide" }, opts)); }

  /* ----------------------------------------------------------- badges --- */
  function badge(text, color) {
    return `<span class="badge ${color || "gray"}">${esc(text)}</span>`;
  }
  function statusBadge(labels) {
    if (!labels) return '<span class="badge gray">—</span>';
    return `<span class="badge ${labels.color || "gray"}">${esc(App.state.lang === "ar" ? labels.ar : labels.en)}</span>`;
  }

  /* ----------------------------------------------------------- charts --- */
  const PALETTE = ["#17395c", "#c9a227", "#1d7a52", "#5b3f97", "#166d75", "#a4302e",
                   "#33689a", "#b5751a", "#54626f", "#7c9ab5"];

  function chart(type, rows, opts) {
    opts = opts || {};
    rows = (rows || []).filter(r => r);
    const labelOf = r => (App.state.lang === "ar" ? (r.label_ar || r.label_en) : (r.label_en || r.label_ar)) || "—";
    const valueOf = r => Number(r.value !== undefined ? r.value : (r.v !== undefined ? r.v : 0)) || 0;
    if (!rows.length) return `<div class="empty small">${esc(t("list.noRecords"))}</div>`;
    if (type === "pie" || type === "donut") return pieChart(rows, labelOf, valueOf, opts);
    if (type === "line") return lineChart(rows, labelOf, valueOf, opts);
    if (type === "timeline") return timelineChart(rows, labelOf, valueOf, opts);
    return barChart(rows, labelOf, valueOf, opts);
  }

  function barChart(rows, labelOf, valueOf, opts) {
    const max = Math.max.apply(null, rows.map(valueOf).concat([1]));
    const total = rows.reduce((a, r) => a + valueOf(r), 0) || 1;
    return `<div class="bars">` + rows.map((r, i) => {
      const v = valueOf(r);
      const pct = Math.max(1.5, (v / max) * 100);
      const color = r.color && r.color !== "gray" ? cssColor(r.color) : PALETTE[i % PALETTE.length];
      return `<div class="bar-row">
        <div class="lab" title="${esc(labelOf(r))}">${esc(truncate(labelOf(r), 34))}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
        <div class="val">${fmtNum(v)}${opts.showPct ? ` <span class="muted small">(${Math.round(v / total * 100)}%)</span>` : ""}</div>
      </div>`;
    }).join("") + `</div>`;
  }

  const CSS_COLORS = {
    green: "#1d7a52", blue: "#33689a", indigo: "#3d4f9c", amber: "#b5751a", orange: "#c2701b",
    red: "#a4302e", rose: "#a8446b", teal: "#166d75", violet: "#5b3f97", gray: "#7d8b96",
    slate: "#54626f"
  };
  function cssColor(name) { return CSS_COLORS[name] || name || PALETTE[0]; }

  function pieChart(rows, labelOf, valueOf) {
    const total = rows.reduce((a, r) => a + valueOf(r), 0) || 1;
    const R = 72, C = 90, r0 = 0;
    let angle = -Math.PI / 2;
    const arcs = rows.map((row, i) => {
      const v = valueOf(row);
      const slice = (v / total) * Math.PI * 2;
      const x1 = C + R * Math.cos(angle), y1 = C + R * Math.sin(angle);
      angle += slice;
      const x2 = C + R * Math.cos(angle), y2 = C + R * Math.sin(angle);
      const large = slice > Math.PI ? 1 : 0;
      const color = row.color && row.color !== "gray" ? cssColor(row.color) : PALETTE[i % PALETTE.length];
      const d = rows.length === 1
        ? `M ${C} ${C - R} A ${R} ${R} 0 1 1 ${C - 0.01} ${C - R} Z`
        : `M ${C} ${C} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
      return `<path class="arc" d="${d}" fill="${color}"><title>${esc(labelOf(row))}: ${fmtNum(v)} (${Math.round(v / total * 100)}%)</title></path>`;
    }).join("");
    const legend = rows.map((row, i) => {
      const color = row.color && row.color !== "gray" ? cssColor(row.color) : PALETTE[i % PALETTE.length];
      return `<span><i style="background:${color}"></i>${esc(labelOf(row))} · ${fmtNum(valueOf(row))}</span>`;
    }).join("");
    return `<div class="flex" style="justify-content:center">
      <svg viewBox="0 0 180 180" style="max-width:230px">${arcs}</svg></div>
      <div class="chart-legend">${legend}</div>`;
  }

  function lineChart(rows, labelOf, valueOf) {
    const W = 640, H = 190, pad = 26;
    const max = Math.max.apply(null, rows.map(valueOf).concat([1]));
    const step = rows.length > 1 ? (W - pad * 2) / (rows.length - 1) : 0;
    const pts = rows.map((r, i) => {
      const x = pad + i * step;
      const y = H - pad - (valueOf(r) / max) * (H - pad * 2);
      return [x, y, r];
    });
    const line = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const area = `${pad},${H - pad} ${line} ${(pad + (rows.length - 1) * step).toFixed(1)},${H - pad}`;
    const dots = pts.map(p => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3.2" fill="#17395c"><title>${esc(labelOf(p[2]))}: ${fmtNum(valueOf(p[2]))}</title></circle>`).join("");
    const ticks = [0, 0.5, 1].map(f => `<line x1="${pad}" x2="${W - pad}" y1="${H - pad - f * (H - pad * 2)}" y2="${H - pad - f * (H - pad * 2)}" stroke="currentColor" stroke-opacity=".12"/><text x="${pad - 6}" y="${H - pad - f * (H - pad * 2) + 3}" text-anchor="end">${Math.round(max * f)}</text>`).join("");
    const labels = pts.filter((p, i) => rows.length <= 14 || i % Math.ceil(rows.length / 12) === 0)
      .map(p => `<text x="${p[0].toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(truncate(labelOf(p[2]), 8))}</text>`).join("");
    return `<div class="chart"><svg viewBox="0 0 ${W} ${H}">${ticks}
      <polygon points="${area}" fill="#33689a" fill-opacity=".12"/>
      <polyline points="${line}" fill="none" stroke="#17395c" stroke-width="2.2" stroke-linejoin="round"/>
      ${dots}${labels}</svg></div>`;
  }

  function timelineChart(rows, labelOf, valueOf) {
    const max = Math.max.apply(null, rows.map(valueOf).concat([1]));
    return `<div class="chart"><svg viewBox="0 0 640 170">` + rows.map((r, i) => {
      const w = rows.length ? Math.min(46, 560 / rows.length - 6) : 20;
      const x = 40 + i * (560 / Math.max(1, rows.length)) + 3;
      const h = (valueOf(r) / max) * 110;
      return `<rect x="${x.toFixed(1)}" y="${(140 - h).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}"
                rx="3" fill="${PALETTE[i % PALETTE.length]}" fill-opacity=".85">
                <title>${esc(labelOf(r))}: ${fmtNum(valueOf(r))}</title></rect>
              <text x="${(x + w / 2).toFixed(1)}" y="156" text-anchor="middle">${esc(truncate(labelOf(r), 7))}</text>`;
    }).join("") + `<line x1="30" y1="140" x2="620" y2="140" stroke="currentColor" stroke-opacity=".25"/></svg></div>`;
  }

  /* -------------------------------------------------------- bootstrap --- */
  Object.assign(App, {
    t, api, label, fieldLabel, dispTitle, domainOptions, lookupById,
    fmtDate, fmtNum, ago, esc, truncate, initials,
    toast, modal, confirmDialog, drawer,
    badge, statusBadge, icon, chart, setLang, setTheme, applyDir,
    loadManifest, localeInfo, LOCALE_MANIFEST,
    fieldLabelSafe
  });
  App.views = App.state.views;
  App.loadMessages = loadMessages;
  App.entitySpec = entitySpec;
  App.fieldsOf = fieldsOf;
  App.pluralOf = pluralOf;
  App.hydrateIcons = hydrateIcons;
  App.cssColor = cssColor;
  App.PALETTE = PALETTE;

  window.addEventListener("DOMContentLoaded", () => {
    setTheme(App.state.theme);
    applyDir();
    hydrateIcons(document);
  });
})();
