/* ============================================================================
   SIRAJ · app.js — bootstrap + hash router + shell wiring
   ========================================================================== */
(function () {
  "use strict";
  const { t, api, icon, toast, esc, hydrateIcons } = window.App;

  const ROUTES = [
    { re: /^\/?$/, view: "dashboard" },
    { re: /^\/dashboard$/, view: "dashboard" },
    { re: /^\/search$/, view: "search" },
    { re: /^\/reports\/([\w-]+)$/, view: "reports", keys: ["key"] },
    { re: /^\/reports$/, view: "reports" },
    { re: /^\/structures$/, view: "structures" },
    { re: /^\/map$/, view: "map" },
    { re: /^\/geo$/, view: "geomap" },
    { re: /^\/desk$/, view: "desk" },
    { re: /^\/military$/, view: "military" },
    { re: /^\/military\/(forces|operations|training|command)$/, view: "milDomain", keys: ["domain"] },
    { re: /^\/military\/(units|regions)\/tree$/, view: "milTree", keys: ["kind"] },
    { re: /^\/military\/units\/(\d+)\/force$/, view: "milForce", keys: ["id"] },
    { re: /^\/military\/([\w-]+)\/(\d+)\/show$/, view: "milDossier", keys: ["entity", "id"] },
    { re: /^\/military\/armaments\/(\d+)\/holdings$/, view: "milHoldings", keys: ["id"] },
    { re: /^\/military\/naming$/, view: "milNaming" },
    { re: /^\/military\/audit$/, view: "milAudit" },
    { re: /^\/military\/([\w-]+)\/new$/, view: "recordNew", keys: ["entity"] },
    { re: /^\/military\/([\w-]+)\/(\d+)\/edit$/, view: "recordEdit", keys: ["entity", "id"] },
    { re: /^\/military\/([\w-]+)\/(\d+)$/, view: "recordEdit", keys: ["entity", "id"] },
    { re: /^\/military\/([\w-]+)$/, view: "milList", keys: ["entity"] },
    { re: /^\/import$/, view: "import" },
    { re: /^\/export$/, view: "export" },
    { re: /^\/changelog$/, view: "changelog" },
    { re: /^\/vocabularies$/, view: "vocabularies" },
    { re: /^\/numbering$/, view: "numbering" },
    { re: /^\/settings$/, view: "settings" },
    { re: /^\/maintenance$/, view: "maintenance" },
    /* military entities share the unified list engine, form engine and
       settings; only the record *dossier* keeps its military layout */
    { re: /^\/entity\/(unit|region|division|classification|armament|holding|deployment|mission|training|assignment|trait|note)\/(\d+)$/, view: "milDossier", keys: ["entity", "id"] },
    { re: /^\/entity\/([\w-]+)\/new$/, view: "recordNew", keys: ["entity"] },
    { re: /^\/entity\/([\w-]+)\/(\d+)\/edit$/, view: "recordEdit", keys: ["entity", "id"] },
    { re: /^\/entity\/([\w-]+)\/(\d+)$/, view: "record", keys: ["entity", "id"] },
    { re: /^\/entity\/([\w-]+)$/, view: "list", keys: ["entity"] }
  ];

  const App = window.App;
  App.views = App.state.views || (App.state.views = {});

  function parseHash() {
    const raw = location.hash.replace(/^#/, "") || "/dashboard";
    const [path, qs] = raw.split("?");
    const params = {};
    if (qs) new URLSearchParams(qs).forEach((v, k) => { params[k] = v; });
    for (const r of ROUTES) {
      const m = path.match(r.re);
      if (m) {
        (r.keys || []).forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); });
        return { view: r.view, params, path };
      }
    }
    return { view: "notFound", params, path };
  }

  async function render() {
    const route = parseHash();
    App.state.route = route;
    /* stay-in-place: remember the screen a record form was opened from — the
       shared record forms return to it after save/cancel, they do not
       navigate the person away */
    if (!/\/(new|edit)$/.test(location.hash || "")) {
      App.state.formOrigin = location.hash || "";
    }
    syncShellChrome();
    /* A record form may live in a dialog.  Any navigation that is not *that*
       form closes it, so a dialog can never float over somebody else's page —
       and if the draft is dirty, the person is asked before it is dropped. */
    const openForm = App.forms && App.forms.active && App.forms.active();
    if (openForm) {
      const here = "#" + String(location.hash || "").replace(/^#/, "");
      /* the form "belongs" on the screen it was opened over — an in-place
         overlay or a route dialog alike.  Its opening address is recorded on
         its backdrop; only a real navigation outlives the form */
      const belongs = openForm.back.dataset.formRoute === here;
      if (!belongs) {
        if (App.forms.dirty && App.forms.dirty()) {
          const discard = await App.confirmDialog({
            title: t("form.discardTitle"), message: t("form.discardBody"),
            confirmLabel: t("common.confirm")
          });
          if (!discard) {
            /* stay on the form: put the address back where the dialog is */
            history.replaceState(null, "", openForm.back.dataset.formRoute);
            return;
          }
        }
        App.forms.close(true);
      }
    }
    const view = document.getElementById("view");
    document.querySelectorAll(".nav-item").forEach(a => {
      const target = a.getAttribute("href").replace(/^#/, "");
      const on = route.path === target ||
        (a.dataset.route && route.path.startsWith("/" + a.dataset.route));
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    // entity nav highlight — a pre-filtered link (Commanders) claims its
    // exact query; the plain link stays active for any other query
    document.querySelectorAll("[data-entity-nav]").forEach(a => {
      const onEntity = route.params.entity === a.dataset.entityNav &&
        (route.view.startsWith("list") || route.view.startsWith("record"));
      const haveQ = route.params.q || "";
      let active = onEntity;
      if (active && (a.dataset.q || "") !== haveQ) {
        const claimed = [...document.querySelectorAll(
          `[data-entity-nav="${a.dataset.entityNav}"][data-q]`)].map(x => x.dataset.q);
        active = a.dataset.q ? false : !claimed.includes(haveQ);
      }
      a.classList.toggle("active", active);
      if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    revealActiveNav();
    if ((route.view === "record" || route.view === "milDossier") &&
        route.params && route.params.entity && route.params.id) {
      const crumbs = document.querySelector(".crumbs");
      const label = crumbs && crumbs.lastElementChild
        ? crumbs.lastElementChild.textContent.trim() : "";
      if (label) {
        const e = (App.state.meta.entities || []).find(x => x.key === route.params.entity);
        navRecentAdd({ href: "#" + route.path, label, ent: route.params.entity,
                       icon: e ? e.icon : "file" });
        buildRecentNav();
      }
    }
    const token = String((App._seq = (App._seq || 0) + 1));
    view.dataset.render = token;
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("scrim").classList.remove("show");
    /* a record form that opens as a dialog keeps the page underneath it: the
       skeleton is for a page render, not for something that will be covered */
    const dialogForm = (route.view === "recordNew" || route.view === "recordEdit") &&
      App.formMode && App.formMode() === "dialog";
    if (!dialogForm) {
      view.innerHTML = `<div class="card"><div class="skeleton" style="width:40%"></div>
        <div class="skeleton" style="width:80%;margin-top:10px"></div></div>`;
      view.dataset.surface = "";
    }
    try {
      /* a view that listens on `document` (keys, resize) must let go of it
         before it is replaced, or the listeners pile up across navigations */
      if (App._dispose) {
        try { App._dispose(); } catch (e) { console.error(e); }
        App._dispose = null;
      }
      /* the geographic view owns a WebGL context; nothing else may keep it alive */
      if (route.view !== "geomap" && App.geoDispose) App.geoDispose();
      const fn = App.views[route.view];
      const ent = route.params && route.params.entity;
      /* the registry owns /entity/<key> routes; /military/* has its own meta */
      if (ent && !route.path.startsWith("/military") &&
          !(App.state.meta.entities || []).some(e => e.key === ent)) {
        view.innerHTML = `<div class="card"><h2>${esc(t("common.error"))}</h2>
          <div class="notice">${esc(ent)} — ${esc(t("ui.unknownEntity"))}</div>
          <div class="btn-row" style="margin-top:12px">
            <a class="btn primary" href="#/dashboard">${esc(t("nav.dashboard"))}</a></div></div>`;
        return;
      }
      if (!fn) {
        view.innerHTML = `<div class="card"><h2>Not found</h2><p class="muted">${esc(route.path)}</p></div>`;
        return;
      }
      await fn(view, route.params, route);
      App._dispose = typeof fn.__dispose === "function" ? fn.__dispose : null;
      hydrateIcons(view);
      /* an in-place form refresh keeps the reader's eye where it was */
      if (App._keepScroll) App._keepScroll = false;
      else window.scrollTo({ top: 0, behavior: "auto" });
      if (shellFullscreen()) notifyLayout();
    } catch (err) {
      console.error(err);
      view.innerHTML = `<div class="card"><h2>${esc(t("common.error"))}</h2>
        <div class="notice err">${esc(err.message || String(err))}</div>
        <div class="btn-row" style="margin-top:12px"><button class="btn" onclick="location.reload()">${esc(t("common.refresh"))}</button></div></div>`;
    }
  }
  App.rerender = render;
  /** True when `el` still belongs to the most recent render (guards async views). */
  App.fresh = function (el) {
    return !!(el && el.isConnected && el.dataset.render === String(App._seq));
  };
  App.go = (hash) => { location.hash = hash; };
  App.parseHash = parseHash;

  /* ------------------------------------------------ sidebar: living nav ---
     The sidebar is a command deck, not a link dump.  Five layers cooperate:
       1. a filter deck — type and every section opens itself around the
          matches (Alt+F jumps here; Esc or the clear button restores the fold);
       2. a Pinned section — star any entry and it docks to the top;
       3. a Recent sub-group — the last records you opened, dismissable;
       4. the layered accordion (sections fold, the military twelve sit in
          themed sub-groups) with open state persisted per browser;
       5. live count badges + per-row quick add and pin stars, revealed on
          hover so the resting sidebar stays calm.
     Count badges load lazily per section through the unified query API and
     cache for two minutes; they are decoration, so a failed count never
     breaks navigation. */
  const MIL_NAV_GROUPS = [
    { key: "org", i18n: "nav.mil.org", items: [
      { ent: "unit", label: "nav.mil.units", icon: "shield" },
      { ent: "region", label: "nav.mil.regions", icon: "globe" },
      { ent: "division", label: "nav.mil.branches", icon: "layers" },
      { ent: "classification", label: "nav.mil.categories", icon: "list" }] },
    { key: "ops", i18n: "nav.mil.ops", items: [
      { ent: "deployment", label: "nav.mil.deployments", icon: "compass" },
      { ent: "mission", label: "nav.mil.tasks", icon: "check" },
      { ent: "training", label: "nav.mil.training", icon: "activity" }] },
    { key: "logi", i18n: "nav.mil.logi", items: [
      { ent: "armament", label: "nav.mil.armaments", icon: "crosshair" },
      { ent: "holding", label: "nav.mil.holdings", icon: "database" }] },
    { key: "lead", i18n: "nav.mil.lead", items: [
      /* the Leader is a person: Commanders is the military-category register */
      { ent: "person", label: "nav.mil.commanders", icon: "user",
        q: "category:military" },
      { ent: "trait", label: "nav.mil.traits", icon: "chart" },
      { ent: "assignment", label: "nav.mil.assignments", icon: "calendar" }] },
    { key: "rec", i18n: "nav.mil.rec", items: [
      { ent: "note", label: "nav.mil.notes", icon: "edit" }] },
  ];
  const MIL_NAV_ENTS = new Set(MIL_NAV_GROUPS.flatMap(g => g.items.map(i => i.ent))
    .filter(k => k !== "person"));
  const NAV_COUNT_TTL = 120000;      // badge freshness window, ms
  const NAV_RECENT_MAX = 8;          // recent rows kept
  const NAV_RECENT_TTL = 30 * 864e5; // recent rows expire after 30 days

  function navStoreRead(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key) || "") || fallback; }
    catch (e) { return fallback; }
  }
  function navStoreWrite(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  /* ------------------------------------------------------- accordion state */
  function navAccState() { return navStoreRead("siraj.navAcc", {}); }
  function navAccSet(box, open) {
    box.classList.toggle("open", open);
    const head = box.querySelector(":scope > .nav-sec-head, :scope > .nav-sub-head");
    if (head) head.setAttribute("aria-expanded", String(open));
    const k = (box.classList.contains("nav-sub") ? "sub:" : "sec:") +
      (box.dataset.sub || box.dataset.sec || "");
    const state = navAccState();
    state[k] = open;
    navStoreWrite("siraj.navAcc", state);
    if (open && box.classList.contains("nav-sec")) navLoadCounts(box);
  }
  /** Restore persisted folds; default: data-default="open" sections only. */
  function navAccApply() {
    const state = navAccState();
    document.querySelectorAll("#nav .nav-sec, #nav .nav-sub").forEach(box => {
      const k = (box.classList.contains("nav-sub") ? "sub:" : "sec:") +
        (box.dataset.sub || box.dataset.sec || "");
      const open = state[k] !== undefined ? !!state[k] : box.dataset.default === "open";
      box.classList.toggle("open", open);
      const head = box.querySelector(":scope > .nav-sec-head, :scope > .nav-sub-head");
      if (head) head.setAttribute("aria-expanded", String(open));
    });
  }
  function revealActiveNav() {
    const active = document.querySelector("#nav .nav-item.active");
    if (!active) return;
    let el = active.parentElement;
    while (el && el.id !== "nav") {
      if (el.classList && (el.classList.contains("nav-sub") ||
                           el.classList.contains("nav-sec"))) {
        if (!el.classList.contains("open")) navAccSet(el, true);
      }
      el = el.parentElement;
    }
  }

  /* ------------------------------------------------------------- pin store */
  function navPins() { return navStoreRead("siraj.navPins", []); }
  function navPinKey(p) { return (p.ent || "") + "|" + (p.q || ""); }
  function navPinToggle(entry) {
    const pins = navPins();
    const i = pins.findIndex(p => navPinKey(p) === navPinKey(entry));
    if (i >= 0) pins.splice(i, 1); else pins.push(entry);
    navStoreWrite("siraj.navPins", pins);
    document.querySelectorAll(".nav-pin").forEach(btn => {
      const on = pins.some(p => navPinKey(p) ===
        navPinKey({ ent: btn.dataset.pinEnt, q: btn.dataset.pinQ }));
      btn.classList.toggle("on", on);
      const label = t(on ? "nav.unpin" : "nav.pin");
      btn.setAttribute("aria-label", label);
      btn.title = label;
    });
    buildPinnedNav();
  }

  /* ----------------------------------------------------------- recent store */
  function navRecent() {
    const now = Date.now();
    const kept = navStoreRead("siraj.navRecent", [])
      .filter(r => r && r.href && now - (r.ts || 0) < NAV_RECENT_TTL);
    if (kept.length) navStoreWrite("siraj.navRecent", kept);
    return kept;
  }
  function navRecentAdd(entry) {
    const list = navRecent().filter(r => r.href !== entry.href);
    list.unshift({ ...entry, ts: Date.now() });
    navStoreWrite("siraj.navRecent", list.slice(0, NAV_RECENT_MAX));
  }
  function navRecentDrop(href) {
    navStoreWrite("siraj.navRecent", navRecent().filter(r => r.href !== href));
  }

  /* --------------------------------------------------------- count badges */
  function navCountKey(ent, q) { return ent + "|" + (q || ""); }
  /** Fill every unfilled [data-count] badge under root, cached for two minutes. */
  async function navLoadCounts(root) {
    const spans = (root || document).querySelectorAll("[data-count]:not([data-filled])");
    const jobs = [];
    spans.forEach(sp => {
      const key = sp.dataset.countKey || "";
      const cut = key.indexOf("|");
      const ent = cut >= 0 ? key.slice(0, cut) : key;
      const q = cut >= 0 ? key.slice(cut + 1) : "";
      if (!ent) return;
      const cached = App._navCounts[key];
      const paint = (total) => {
        sp.textContent = String(total);
        sp.classList.toggle("zero", total === 0);
        sp.hidden = false;
        sp.dataset.filled = "1";
      };
      if (cached && Date.now() - cached.ts < NAV_COUNT_TTL) { paint(cached.total); return; }
      jobs.push((async () => {
        try {
          const body = { page_size: 1 };
          if (q) body.query = q;
          const out = await api.post(`/api/${ent}/query`, body);
          const total = (out && typeof out.total === "number") ? out.total : 0;
          App._navCounts[key] = { total, ts: Date.now() };
          paint(total);
        } catch (e) { /* counts are decoration — never break navigation */ }
      })());
    });
    if (jobs.length) await Promise.all(jobs);
  }

  /* ----------------------------------------------------------- nav filter */
  function navRowOf(el) { return el.closest(".nav-row") || el; }
  function navFilterApply(text) {
    const nav = document.getElementById("nav");
    const q = String(text || "").trim().toLowerCase();
    const empty = document.getElementById("navEmpty");
    const chip = document.getElementById("navFilterCount");
    const clearBtn = document.getElementById("navFilterClear");
    if (clearBtn) clearBtn.hidden = !q;
    let matches = 0;
    nav.querySelectorAll(".nav-item").forEach(item => {
      const hay = (item.dataset.match || item.textContent || "").toLowerCase();
      const hit = !q || hay.includes(q);
      navRowOf(item).hidden = !hit;
      if (hit && q) matches++;
    });
    nav.querySelectorAll(".nav-sec, .nav-sub").forEach(box => {
      const any = [...box.querySelectorAll(".nav-item")].some(x => !navRowOf(x).hidden);
      if (q) {
        box.hidden = !any;
        const head = box.querySelector(":scope > .nav-sec-head, :scope > .nav-sub-head");
        if (head) head.setAttribute("aria-expanded", "true");
      } else {
        box.hidden = box.dataset.empty === "1";
      }
    });
    nav.classList.toggle("filtering", !!q);
    if (empty) empty.hidden = !(q && matches === 0);
    if (chip) {
      chip.hidden = !q;
      if (q) chip.textContent = t("nav.filterMatches", { n: matches });
    }
    if (!q) navAccApply();   // hand the folds back to the persisted state
  }

  /* --------------------------------------------------------- row templates */
  /** Resolved label + search corpus for a nav entry (pins replay the same shape). */
  function navItemData(it) {
    const e = (App.state.meta.entities || []).find(x => x.key === it.ent) || null;
    const text = it.label ? t(it.label)
      : (e ? (App.state.lang === "ar" ? e.plural_ar : e.plural_en) : it.ent);
    const extra = e ? ` ${e.plural_en} ${e.plural_ar}` : "";
    return {
      text,
      icon: it.icon || (e && e.icon) || "file",
      match: `${it.ent} ${text}${extra} ${it.q || ""}`.toLowerCase(),
    };
  }
  /** data-i18n-aria rides along so setLang refreshes, but the label is
      applied at build time too — rows are born after translate() ran. */
  function navAria(key) {
    return `data-i18n-aria="${key}" aria-label="${esc(t(key))}" title="${esc(t(key))}"`;
  }
  function navEntityRow(it) {
    const d = navItemData(it);
    const href = `#/entity/${it.ent}${it.q ? `?q=${encodeURIComponent(it.q)}` : ""}`;
    const pinned = navPins().some(p => navPinKey(p) === navPinKey(it));
    return `<div class="nav-row">
      <a class="nav-item" data-entity-nav="${esc(it.ent)}"${it.q ? ` data-q="${esc(it.q)}"` : ""}
         href="${href}" data-match="${esc(d.match)}">
        <span class="ico" data-icon="${esc(d.icon)}"></span>
        <span class="nav-label">${esc(d.text)}</span>
        <span class="nav-count" data-count data-count-key="${esc(navCountKey(it.ent, it.q))}" hidden></span>
      </a>
      <span class="nav-tools">
        <a class="nav-tool nav-add" href="#/entity/${esc(it.ent)}/new" ${navAria("nav.addNew")}>
          <span class="ico" data-icon="plus"></span></a>
        <button class="nav-tool nav-pin${pinned ? " on" : ""}" type="button"
                data-pin-ent="${esc(it.ent)}"${it.q ? ` data-pin-q="${esc(it.q)}"` : ""}
                data-pin-label="${esc(it.label || "")}" data-pin-icon="${esc(it.icon || "")}"
                ${navAria(pinned ? "nav.unpin" : "nav.pin")}>
          <span class="ico" data-icon="star"></span></button>
      </span>
    </div>`;
  }
  function navRecentRow(r) {
    return `<div class="nav-row">
      <a class="nav-item" href="${esc(r.href)}" title="${esc(r.label)}">
        <span class="ico" data-icon="${esc(r.icon || "file")}"></span>
        <span class="nav-label">${esc(r.label)}</span>
      </a>
      <span class="nav-tools">
        <button class="nav-tool nav-recent-drop" type="button" data-drop="${esc(r.href)}"
                ${navAria("nav.recentDrop")}>
          <span class="ico" data-icon="x"></span></button>
      </span>
    </div>`;
  }

  /* ------------------------------------------------------------ builders */
  function buildPinnedNav() {
    const box = document.getElementById("pinnedNav");
    const sec = document.getElementById("navPinnedSec");
    if (!box || !sec) return;
    const pins = navPins();
    sec.dataset.empty = pins.length ? "0" : "1";
    if (!document.getElementById("nav").classList.contains("filtering")) {
      sec.hidden = !pins.length;
    }
    box.innerHTML = pins.map(p => navEntityRow(p)).join("");
    hydrateIcons(box);
  }
  function buildRecentNav() {
    const box = document.getElementById("recentNav");
    const sub = document.getElementById("navRecentSub");
    if (!box || !sub) return;
    const recs = navRecent();
    sub.dataset.empty = recs.length ? "0" : "1";
    if (!document.getElementById("nav").classList.contains("filtering")) {
      sub.hidden = !recs.length;
    }
    box.innerHTML = recs.map(navRecentRow).join("");
    hydrateIcons(box);
  }
  function buildNav() {
    const box = document.getElementById("milNav");
    box.innerHTML = MIL_NAV_GROUPS.map(g => `
      <div class="nav-sub" data-sub="${g.key}">
        <button class="nav-sub-head" type="button" aria-expanded="false" aria-controls="navSub-${g.key}">
          <span class="nav-sub-dot" data-tone="${g.key}" aria-hidden="true"></span>
          <span class="nav-sub-title">${esc(t(g.i18n))}</span>
          <span class="nav-sub-caret" aria-hidden="true"></span>
        </button>
        <div class="nav-sub-body" id="navSub-${g.key}"><div class="nav-sub-inner">
          ${g.items.map(navEntityRow).join("")}
        </div></div>
      </div>`).join("");
    const reg = document.getElementById("entityNav");
    reg.innerHTML = (App.state.meta.entities || [])
      .filter(e => !MIL_NAV_ENTS.has(e.key))
      .map(e => navEntityRow({ ent: e.key, icon: e.icon })).join("");
    /* static items carry a runtime-built search corpus so a third language
       stays additive — nothing bilingual is hardcoded in markup. */
    document.querySelectorAll("#nav .nav-item:not([data-match])").forEach(item => {
      item.dataset.match =
        `${item.textContent || ""} ${item.dataset.route || ""}`.trim().toLowerCase();
    });
    hydrateIcons(box);
    hydrateIcons(reg);
    buildPinnedNav();
    buildRecentNav();
    navAccApply();
    revealActiveNav();
    document.querySelectorAll("#nav .nav-sec.open").forEach(sec => navLoadCounts(sec));
    syncShellChrome();
    const inp = document.getElementById("navFilter");
    if (inp && inp.value) navFilterApply(inp.value);
  }

  function buildActors() {
    const sel = document.getElementById("actorSelect");
    const users = (App.state.meta.users || []).filter(u => u.is_active);
    sel.innerHTML = users.map(u =>
      `<option value="${esc(u.username)}" ${u.username === App.state.actor ? "selected" : ""}>
        ${esc(App.state.lang === "ar" ? (u.display_name || u.username) : (u.display_name || u.username))} · ${esc(u.role)}
      </option>`).join("");
    sel.onchange = () => {
      App.state.actor = sel.value;
      localStorage.setItem("siraj.actor", sel.value);
      toast(`${t("log.actor")}: ${sel.value}`, "ok", 1600);
    };
  }

  function sidebarCollapsed() {
    return document.documentElement.classList.contains("sidebar-collapsed");
  }
  function shellFullscreen() {
    return document.body.classList.contains("shell-fs");
  }
  function fullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }

  /** Icon rail: keep each destination's name on the link for keyboard and pointer. */
  function syncNavTitles() {
    const collapsed = sidebarCollapsed();
    document.querySelectorAll("#nav .nav-item").forEach(a => {
      const label = a.querySelector("span:not(.ico)");
      const text = label ? label.textContent.trim() : "";
      if (collapsed && text) a.title = text;
      else a.removeAttribute("title");
    });
  }

  function syncShellChrome() {
    const collapsed = sidebarCollapsed();
    const fs = shellFullscreen();
    const collapseBtn = document.getElementById("sidebarCollapse");
    if (collapseBtn) {
      const label = t(collapsed ? "shell.expandSidebar" : "shell.collapseSidebar");
      collapseBtn.title = label;
      collapseBtn.setAttribute("aria-label", label);
      collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    const fsBtn = document.getElementById("fullscreenToggle");
    if (fsBtn) {
      const label = t(fs ? "shell.exitFullscreen" : "shell.enterFullscreen");
      fsBtn.title = label;
      fsBtn.setAttribute("aria-label", label);
      fsBtn.setAttribute("aria-pressed", fs ? "true" : "false");
      fsBtn.classList.toggle("is-on", fs);
    }
    syncNavTitles();
  }

  /**
   * Maps and decks size themselves from the viewport once. After the rail or
   * the full-screen chrome moves, give those frames the height that is left
   * and tell every listener the window changed.
   */
  function fitWorkspace() {
    const fs = shellFullscreen();
    document.querySelectorAll(".geo-workspace, .desk, .viz-deck").forEach(el => {
      if (!fs) {
        if (el.dataset.fsFit) {
          el.style.height = "";
          el.style.minHeight = "";
          delete el.dataset.fsFit;
        }
        return;
      }
      if (!el.getClientRects().length) return;
      /* below this width the desk becomes a scrolling stack; a forced height clips it */
      if (el.classList.contains("desk") && window.innerWidth <= 1080) {
        el.style.height = "";
        el.style.minHeight = "";
        delete el.dataset.fsFit;
        return;
      }
      const top = el.getBoundingClientRect().top;
      const view = el.closest(".view");
      const pad = view ? (parseFloat(getComputedStyle(view).paddingBottom) || 0) : 0;
      const h = Math.max(240, Math.round(window.innerHeight - top - pad));
      el.style.height = h + "px";
      el.style.minHeight = "0px";
      el.dataset.fsFit = "1";
    });
  }

  let shellResize = false;
  function notifyLayout() {
    const pass = () => {
      fitWorkspace();
      if (App.measureChrome) App.measureChrome();
      requestAnimationFrame(() => {
        shellResize = true;
        window.dispatchEvent(new Event("resize"));
        shellResize = false;
      });
    };
    requestAnimationFrame(pass);
    setTimeout(pass, 240);
  }

  function toggleSidebar() {
    const next = !sidebarCollapsed();
    document.documentElement.classList.toggle("sidebar-collapsed", next);
    try { localStorage.setItem("siraj.sidebar", next ? "collapsed" : "expanded"); }
    catch (e) { /* a private window still toggles for this visit */ }
    syncShellChrome();
    notifyLayout();
  }

  async function setShellFullscreen(on) {
    document.body.classList.toggle("shell-fs", on);
    if (on) {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("scrim").classList.remove("show");
    }
    syncShellChrome();
    try {
      if (on && !fullscreenElement()) {
        const el = document.documentElement;
        const req = el.requestFullscreen || el.webkitRequestFullscreen;
        if (req) await req.call(el);
      } else if (!on && fullscreenElement()) {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) await exit.call(document);
      }
    } catch (e) { /* the view still fills the window if the browser refuses */ }
    notifyLayout();
  }

  function wireShell() {
    /* one delegated listener: pin stars, recent dismissals and the folding
       of section / sub-group heads */
    const nav = document.getElementById("nav");
    nav.addEventListener("click", (e) => {
      const pin = e.target.closest(".nav-pin");
      if (pin) {
        navPinToggle({
          ent: pin.dataset.pinEnt, q: pin.dataset.pinQ || null,
          label: pin.dataset.pinLabel || null, icon: pin.dataset.pinIcon || null,
        });
        return;
      }
      const drop = e.target.closest(".nav-recent-drop");
      if (drop) {
        navRecentDrop(drop.dataset.drop);
        buildRecentNav();
        return;
      }
      const head = e.target.closest(".nav-sec-head, .nav-sub-head");
      if (!head) return;
      navAccSet(head.parentElement, !head.parentElement.classList.contains("open"));
    });
    /* --- filter deck: live matching, Esc/Enter aware, Alt+F from anywhere -- */
    const navFilter = document.getElementById("navFilter");
    if (navFilter) {
      navFilter.addEventListener("input", () => navFilterApply(navFilter.value));
      navFilter.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          navFilter.value = "";
          navFilterApply("");
        } else if (e.key === "Enter") {
          e.preventDefault();
          const first = nav.querySelector(".nav-item:not([hidden])");
          if (first) first.click();
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          const first = nav.querySelector(
            "button.nav-sec-head, button.nav-sub-head, a.nav-item");
          if (first) first.focus();
        }
      });
      document.getElementById("navFilterClear").onclick = () => {
        navFilter.value = "";
        navFilterApply("");
        navFilter.focus();
      };
    }
    function syncFoldBtn(allOpen) {
      const btn = document.getElementById("navFoldAll");
      btn.classList.toggle("all-open", allOpen);
      const label = t(allOpen ? "nav.collapseAll" : "nav.expandAll");
      btn.setAttribute("aria-label", label);
      btn.title = label;
    }
    document.getElementById("navFoldAll").onclick = () => {
      const boxes = [...nav.querySelectorAll(".nav-sec, .nav-sub")].filter(b => !b.hidden);
      const anyOpen = boxes.some(b => b.classList.contains("open"));
      boxes.forEach(b => navAccSet(b, !anyOpen));
      syncFoldBtn(!anyOpen);
    };
    syncFoldBtn(nav.querySelectorAll(".nav-sec.open, .nav-sub.open").length > 0);
    /* --- roving keyboard across the nav list (arrows, Home/End) ----------- */
    nav.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && navFilter && navFilter.value) {
        e.preventDefault();
        navFilter.value = "";
        navFilterApply("");
        return;
      }
      const el = document.activeElement;
      if (!el || el === navFilter || !nav.contains(el)) return;
      const items = [...nav.querySelectorAll(
        "button.nav-sec-head, button.nav-sub-head, a.nav-item")]
        .filter(x => x.offsetParent !== null);
      const i = items.indexOf(el);
      if (i < 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault(); (items[i + 1] || items[0]).focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault(); (items[i - 1] || items[items.length - 1]).focus();
      } else if (e.key === "Home") {
        e.preventDefault(); items[0].focus();
      } else if (e.key === "End") {
        e.preventDefault(); items[items.length - 1].focus();
      } else if ((e.key === "ArrowRight" || e.key === "ArrowLeft") &&
                 (el.classList.contains("nav-sec-head") ||
                  el.classList.contains("nav-sub-head"))) {
        e.preventDefault();
        navAccSet(el.parentElement, e.key === "ArrowRight");
      }
    });
    document.getElementById("langToggle").onclick = async () => {
      const list = App.state.locales || [];
      const idx = list.findIndex(l => l.code === App.state.lang);
      const next = (list[(idx + 1) % Math.max(list.length, 1)] || {}).code ||
                   (App.state.lang === "ar" ? "en" : "ar");
      await App.loadMessages(next);
      App.setLang(next);
      buildNav(); buildActors();
      document.getElementById("globalSearch").placeholder = t("search.placeholder");
      document.getElementById("buildInfo").textContent =
        `SIRAJ v1.0 · ${(App.state.meta.entities || []).length} entities`;
      render();
    };
    document.getElementById("themeToggle").onclick = () => {
      App.setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    };
    const gs = document.getElementById("globalSearch");
    gs.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && gs.value.trim()) {
        location.hash = `#/search?q=${encodeURIComponent(gs.value.trim())}`;
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement.tagName !== "INPUT" &&
          document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault(); gs.focus(); gs.select();
      }
      if (e.altKey && (e.key === "f" || e.key === "F") &&
          document.activeElement.tagName !== "INPUT" &&
          document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault();
        const nf = document.getElementById("navFilter");
        if (nf) { nf.focus(); nf.select(); }
      }
    });
    document.getElementById("sidebarOpen").onclick = () => {
      document.getElementById("sidebar").classList.add("open");
      document.getElementById("scrim").classList.add("show");
    };
    document.getElementById("sidebarClose").onclick = () => {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("scrim").classList.remove("show");
    };
    document.getElementById("scrim").onclick = () => {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("scrim").classList.remove("show");
    };
    document.getElementById("sidebarCollapse").onclick = toggleSidebar;
    document.getElementById("fullscreenToggle").onclick = () => {
      setShellFullscreen(!shellFullscreen());
    };
    document.addEventListener("fullscreenchange", () => {
      if (fullscreenElement()) return;
      if (!shellFullscreen()) return;
      document.body.classList.remove("shell-fs");
      syncShellChrome();
      notifyLayout();
    });
    document.addEventListener("webkitfullscreenchange", () => {
      if (fullscreenElement()) return;
      if (!shellFullscreen()) return;
      document.body.classList.remove("shell-fs");
      syncShellChrome();
      notifyLayout();
    });
    /* a real window resize while full screen must remeasure; the synthetic
       resize dispatched by notifyLayout must not start another pass */
    window.addEventListener("resize", () => {
      if (shellResize || !shellFullscreen()) return;
      fitWorkspace();
      requestAnimationFrame(() => {
        shellResize = true;
        window.dispatchEvent(new Event("resize"));
        shellResize = false;
      });
    });
    syncShellChrome();
  }

  async function boot() {
    try {
      await App.loadManifest();
      /* language: the visitor's own choice wins; otherwise the instance default
         (`display.default_language`), read from /api/meta — so a first visit opens
         in the language the registry was configured for, not a hardcoded one */
      const personal = localStorage.getItem("siraj.lang");
      const meta0 = personal ? null : await api.get("/api/meta?lang=en");
      const wanted = personal || (meta0 && meta0.settings &&
        meta0.settings["display.default_language"]) || App.state.lang;
      const active = App.state.locales.some(l => l.code === wanted)
        ? wanted
        : (App.state.locales.find(l => l.default) || App.state.locales[0] || {}).code || "ar";
      App.state.lang = active;
      await App.loadMessages("en");
      await App.loadMessages(active);
      App.state.meta = await api.get(`/api/meta?lang=${App.state.lang}`);
    } catch (err) {
      document.getElementById("view").innerHTML =
        `<div class="card"><h2>Cannot reach the API</h2>
         <div class="notice err">${esc(err.message)}</div></div>`;
      return;
    }
    App.setLang(App.state.lang, { silent: true });
    App.applyAppearance();
    buildNav();
    buildActors();
    wireShell();
    document.getElementById("buildInfo").textContent =
      `SIRAJ v1.0 · ${(App.state.meta.entities || []).length} entities · ${(App.state.meta.lookup_domains || []).length} vocabularies`;
    const size = App.state.meta.db ? Math.round(App.state.meta.db.size_bytes / 1024) : 0;
    document.getElementById("footStats").textContent = `SQLite · ${size} KB · schema 1.0.0`;
    measureChrome();
    window.addEventListener("resize", measureChrome);
    /* Add and edit buttons never navigate.  A plain click on a form link opens
       the shared record form as an overlay on the current screen; modified
       clicks keep their link semantics (new tab, new window). */
    document.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey
          || e.shiftKey || e.altKey) return;
      const a = e.target && e.target.closest && e.target.closest('a[href^="#/"]');
      if (!a || (a.target && a.target !== "_self")) return;
      const href = a.getAttribute("href") || "";
      const m = href.match(/^#\/entity\/([\w-]+)\/(?:new|(\d+)\/edit)$/)
        || href.match(/^#\/military\/([\w-]+)\/(?:new|(\d+)\/edit)$/);
      if (!m) return;
      e.preventDefault();
      Promise.resolve(App.forms.open(m[1], m[2] ? Number(m[2]) : null))
        .catch(err => console.error(err));
    });
    if (!location.hash) location.hash = "#/dashboard";
    window.addEventListener("hashchange", render);
    render();
  }

  document.addEventListener("DOMContentLoaded", boot);

  // shared helpers used by views
  /** Publish the sticky top-bar height so sticky panels can sit exactly below it. */
  function measureChrome() {
    const bar = document.querySelector(".topbar");
    if (bar) {
      document.documentElement.style.setProperty("--topbar-h", bar.offsetHeight + "px");
    }
  }
  App.measureChrome = measureChrome;

  App.crumbs = function (items) {
    const el = document.getElementById("crumbs");
    el.innerHTML = items.map((it, i) =>
      it.href && i < items.length - 1
        ? `<a href="${it.href}">${esc(it.label)}</a><span>›</span>`
        : `<span>${esc(it.label)}</span>`).join("");
  };
  App.pageHead = function (title, subtitle, actionsHtml) {
    return `<div class="page-head">
      <div class="titles"><h1>${esc(title)}</h1>${subtitle ? `<div class="sub">${esc(subtitle)}</div>` : ""}</div>
      ${actionsHtml ? `<div class="actions">${actionsHtml}</div>` : ""}</div>`;
  };
  App.download = function (url) {
    const a = document.createElement("a");
    a.href = url; a.rel = "noopener"; document.body.appendChild(a); a.click(); a.remove();
  };
})();
