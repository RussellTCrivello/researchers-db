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
    { re: /^\/military\/([\w-]+)\/new$/, view: "milForm", keys: ["entity"] },
    { re: /^\/military\/([\w-]+)\/(\d+)$/, view: "milForm", keys: ["entity", "id"] },
    { re: /^\/military\/([\w-]+)$/, view: "milList", keys: ["entity"] },
    { re: /^\/import$/, view: "import" },
    { re: /^\/export$/, view: "export" },
    { re: /^\/changelog$/, view: "changelog" },
    { re: /^\/vocabularies$/, view: "vocabularies" },
    { re: /^\/numbering$/, view: "numbering" },
    { re: /^\/settings$/, view: "settings" },
    { re: /^\/maintenance$/, view: "maintenance" },
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
    syncShellChrome();
    /* A record form may live in a dialog.  Any navigation that is not *that*
       form closes it, so a dialog can never float over somebody else's page —
       and if the draft is dirty, the person is asked before it is dropped. */
    const openForm = App.forms && App.forms.active && App.forms.active();
    if (openForm) {
      const here = "#" + String(location.hash || "").replace(/^#/, "");
      const belongs = (route.view === "recordNew" || route.view === "recordEdit") &&
        openForm.back.dataset.formRoute === here;
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
      a.classList.toggle("active", route.path === target ||
        (a.dataset.route && route.path.startsWith("/" + a.dataset.route)));
    });
    // entity nav highlight
    document.querySelectorAll("[data-entity-nav]").forEach(a => {
      a.classList.toggle("active", route.params.entity === a.dataset.entityNav &&
        route.view.startsWith("list") || route.params.entity === a.dataset.entityNav && route.view.startsWith("record"));
    });
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
      window.scrollTo({ top: 0, behavior: "auto" });
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

  function buildEntityNav() {
    const box = document.getElementById("entityNav");
    box.innerHTML = (App.state.meta.entities || []).map(e => `
      <a class="nav-item" data-entity-nav="${e.key}" href="#/entity/${e.key}">
        <span class="ico" data-icon="${e.icon}"></span>
        <span>${esc(App.state.lang === "ar" ? e.plural_ar : e.plural_en)}</span>
      </a>`).join("");
    hydrateIcons(box);
    syncShellChrome();
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
    document.getElementById("langToggle").onclick = async () => {
      const list = App.state.locales || [];
      const idx = list.findIndex(l => l.code === App.state.lang);
      const next = (list[(idx + 1) % Math.max(list.length, 1)] || {}).code ||
                   (App.state.lang === "ar" ? "en" : "ar");
      await App.loadMessages(next);
      App.setLang(next);
      buildEntityNav(); buildActors();
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
    buildEntityNav();
    buildActors();
    wireShell();
    document.getElementById("buildInfo").textContent =
      `SIRAJ v1.0 · ${(App.state.meta.entities || []).length} entities · ${(App.state.meta.lookup_domains || []).length} vocabularies`;
    const size = App.state.meta.db ? Math.round(App.state.meta.db.size_bytes / 1024) : 0;
    document.getElementById("footStats").textContent = `SQLite · ${size} KB · schema 1.0.0`;
    measureChrome();
    window.addEventListener("resize", measureChrome);
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
