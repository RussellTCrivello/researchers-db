/* ============================================================================
   SIRAJ · views/military.js — Military Organization (Brigade Command workspace)
   ----------------------------------------------------------------------------
   The Military Organization (BIMS) lives inside the shell like every other
   workspace: one navigation, one locale mechanism (mil.* keys), one theme, one
   design language.  Data comes from the self-contained /api/military API
   (its own SQLite file; the registry is never touched).  Every record shown is
   FICTIONAL sample data unless the operator replaces it.
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, fmtNum, icon, toast, chart, badge, hydrateIcons } = A;

  /* ------------------------------------------------------ meta + roles --- */
  let META = null;
  async function meta() {
    if (!META) META = await mreq("GET", "/meta");
    return META;
  }
  function role() {
    try { return localStorage.getItem("siraj.mil.role") || "admin"; } catch (e) { return "admin"; }
  }
  function setRole(r) {
    try { localStorage.setItem("siraj.mil.role", r); } catch (e) {}
  }
  /** Fetch against /api/military with the demonstration role header. */
  async function mreq(method, path, body) {
    try {
      return await api.raw(method, "/api/military" + path, body,
        { headers: { "X-Military-Role": role() } });
    } catch (err) {
      const e = err && err.payload && (err.payload.detail || err.payload);
      if (e && e.error) {
        err.code = e.error.code;
        err.field = e.error.field;
        err.message = e.error.message || err.message;
      }
      throw err;
    }
  }

  /* ------------------------------------------------------- vocabulary ---- */
  const ENTITIES = ["region", "division", "classification", "commander", "unit",
    "deployment", "mission", "armament", "holding", "training", "assignment", "note"];

  const STATUS_COLOR = {
    Active: "green", Serviceable: "green", Completed: "green", Executed: "green",
    Excellent: "green", Satisfactory: "teal",
    Training: "blue", Standby: "blue", Planned: "blue", Ongoing: "blue",
    Suspended: "amber", Limited: "amber", Reserve: "amber", Mobilized: "amber",
    "Needs Improvement": "amber", "In Refit": "amber", Reorganizing: "amber",
    Attached: "violet", Cancelled: "red", Unserviceable: "red",
    "Stand-down": "red", Disbanded: "red", Unsatisfactory: "red", Retired: "gray"
  };
  function chip(v) {
    if (v == null || v === "") return badge("—", "gray");
    return badge(String(v), STATUS_COLOR[String(v)] || "gray");
  }

  const entLabel = (key) => {
    const spec = (META && META.entities && META.entities[key]) || {};
    return A.state.lang === "ar" ? (spec.label_ar || spec.label || key)
      : (spec.label_en || spec.label || key);
  };
  const fieldLabel = (f) =>
    A.state.lang === "ar" ? (f.label_ar || f.label || f.name) : (f.label_en || f.label || f.name);

  /* ------------------------------------------------------- shared chrome - */
  /* the four command domains — the primary organisation of the workspace */
  const DOMAINS = {
    forces: ["unit", "region", "division", "classification", "armament", "holding"],
    operations: ["deployment", "mission"],
    training: ["training"],
    command: ["commander", "assignment", "note"]
  };
  const DOMAIN_OF = {};
  Object.keys(DOMAINS).forEach(d => DOMAINS[d].forEach(e => { DOMAIN_OF[e] = d; }));
  const DOMAIN_LABEL = {
    forces: "mil.domain.forces", operations: "mil.domain.operations",
    training: "mil.domain.training", command: "mil.domain.command"
  };
  const DOMAIN_PRIMARY = {
    forces: "unit", operations: "deployment", training: "training", command: "commander"
  };
  const DOMAIN_SUMMARY_LIST = {
    forces: ["mil.list.lowReadiness", "low_readiness_units"],
    operations: ["mil.list.upcomingDeployments", "upcoming_deployments"],
    training: ["mil.list.upcomingTrainings", "upcoming_trainings"],
    command: ["mil.list.recentActivity", "recent_activity"]
  };

  function milNav(active) {
    const domainOfActive = active.startsWith("e:") ? DOMAIN_OF[active.slice(2)]
      : active.startsWith("tree:") ? "forces"
      : active.startsWith("domain:") ? active.slice(7) : null;
    const item = (href, label, key) =>
      `<a class="mil-nav-item${active === key ? " on" : ""}" href="${href}">${esc(label)}</a>`;
    const tier1 =
      item("#/military", t("mil.nav.workspace"), "workspace") +
      Object.keys(DOMAINS).map(d =>
        item("#/military/" + d, t(DOMAIN_LABEL[d]), "domain:" + d)).join("") +
      item("#/military/naming", t("mil.nav.naming"), "naming") +
      item("#/military/audit", t("mil.nav.audit"), "audit");
    let tier2 = "";
    if (domainOfActive) {
      const extras = domainOfActive === "forces"
        ? item("#/military/units/tree", t("mil.nav.unitsTree"), "tree:units") +
          item("#/military/regions/tree", t("mil.nav.regionsTree"), "tree:regions")
        : "";
      tier2 = `<div class="mil-nav mil-nav-sub">
        ${item("#/military/" + domainOfActive, t("mil.domain.hub"), "domain:" + domainOfActive)}
        ${DOMAINS[domainOfActive].map(k => item("#/military/" + k + "s", entLabel(k), "e:" + k)).join("")}
        ${extras}
      </div>`;
    }
    return `<div class="mil-nav">${tier1}<span class="flex"></span>
      <select class="ghost-select" id="milRole" title="${esc(t("mil.role.label"))}">
        ${["admin", "staff", "viewer"].map(r =>
          `<option value="${r}"${r === role() ? " selected" : ""}>${esc(t("mil.role." + r))}</option>`).join("")}
      </select></div>${tier2}`;
  }

  function bindChrome(root) {
    hydrateIcons(root);
    const sel = root.querySelector("#milRole");
    if (sel) sel.onchange = () => {
      setRole(sel.value);
      toast(t("mil.role.switched", { role: sel.value }), "ok");
      A.rerender();
    };
  }

  function table(cols, rows, render) {
    return `<div class="table-wrap"><table class="data compact">
      <thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${rows.length ? rows.map(render).join("")
        : `<tr><td colspan="${cols.length}" class="empty">${esc(t("list.noRecords"))}</td></tr>`}</tbody>
    </table></div>`;
  }

  async function refOptions(entity) {
    /* fetch EVERY option row (paged) — a fixed cap silently drops linked
       records from dropdowns at volume */
    const out = [];
    let offset = 0;
    for (;;) {
      const data = await mreq("GET", "/" + entity + "s?limit=500&offset=" + offset);
      const rows = data.records || [];
      out.push(...rows);
      offset += rows.length;
      if (!rows.length || rows.length < 500 || offset >= (data.total || 0)) break;
    }
    return out;
  }
  function refLabelOf(entity, rec) {
    if (!rec) return "";
    return `${rec.docname || "#" + rec.id} · ${rec.name || rec.full_name || rec.exercise_name || ""}`;
  }

  /* searchable, selectable dropdown for linked (ref) fields — the plain
     <select> cannot carry 1,000+ options at volume */
  function refCombo(f, v, refs) {
    const rows = refs[f.entity] || [];
    const cur = rows.find(r => Number(v) === r.id);
    return `<div class="refcombo" data-entity="${esc(f.entity)}">
      <input type="hidden" name="${f.name}" value="${v == null || v === "" ? "" : Number(v)}">
      <input type="text" class="refcombo-input" autocomplete="off" spellcheck="false"
        placeholder="${esc(t("mil.combo.search"))}" role="combobox"
        aria-expanded="false" value="${cur ? esc(refLabelOf(f.entity, cur)) : ""}">
      <div class="refcombo-list" role="listbox" hidden></div>
    </div>`;
  }

  function bindRefCombos(root, refs) {
    root.querySelectorAll(".refcombo").forEach(box => {
      const entity = box.dataset.entity;
      const rows = refs[entity] || [];
      const hidden = box.querySelector("input[type=hidden]");
      const input = box.querySelector(".refcombo-input");
      const list = box.querySelector(".refcombo-list");
      const render = (q) => {
        const needle = (q || "").trim().toLowerCase();
        const matches = rows.filter(r => !needle ||
          refLabelOf(entity, r).toLowerCase().includes(needle)).slice(0, 80);
        list.innerHTML = matches.length
          ? matches.map(r => `<div class="refcombo-item" role="option" data-id="${r.id}">${esc(refLabelOf(entity, r))}</div>`).join("")
          : `<div class="refcombo-empty">${esc(t("mil.combo.noMatch"))}</div>`;
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      };
      const close = () => {
        list.hidden = true;
        input.setAttribute("aria-expanded", "false");
      };
      input.addEventListener("focus", () => render(input.value));
      input.addEventListener("input", () => {
        hidden.value = "";            // typed text invalidates the selection
        render(input.value);
      });
      list.addEventListener("mousedown", (ev) => {
        const item = ev.target.closest(".refcombo-item");
        if (!item) return;
        ev.preventDefault();
        const rec = rows.find(r => r.id === Number(item.dataset.id));
        hidden.value = rec.id;
        input.value = refLabelOf(entity, rec);
        close();
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
      });
      input.addEventListener("blur", () => {
        setTimeout(close, 120);
        const rec = rows.find(r => r.id === Number(hidden.value));
        input.value = rec ? refLabelOf(entity, rec) : "";
      });
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") { close(); input.blur(); return; }
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.preventDefault();
          if (list.hidden) { render(input.value); return; }
          const items = [...list.querySelectorAll(".refcombo-item")];
          if (!items.length) return;
          let idx = items.findIndex(el => el.classList.contains("active"));
          items.forEach(el => el.classList.remove("active"));
          idx = ev.key === "ArrowDown"
            ? Math.min(items.length - 1, idx + 1)
            : Math.max(0, idx - 1);
          items[idx].classList.add("active");
          items[idx].scrollIntoView({ block: "nearest" });
        }
        if (ev.key === "Enter") {
          const active = list.querySelector(".refcombo-item.active");
          if (active) {
            ev.preventDefault();
            active.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
          }
        }
      });
    });
  }

  /* ====================================================== view: workspace */
  A.views.military = async function (root) {
    A.crumbs([{ label: t("nav.military") }, { label: t("mil.title") }]);
    const [m, d, qual] = await Promise.all([
      meta(), mreq("GET", "/summary"), mreq("GET", "/quality")]);
    const c = d.cards, ch = d.charts, lists = d.lists;
    const kpis = [
      ["mil.kpi.activeUnits", c.active_units, "status = Active"],
      ["mil.kpi.currentDeployments", c.current_deployments, "is_current = 1"],
      ["mil.kpi.openMissions", c.open_missions, "Planned + Ongoing"],
      ["mil.kpi.trainingYear", c.training_this_year, String(new Date().getFullYear())],
      ["mil.kpi.activeCommanders", c.active_commanders, "status = Active"]
    ];
    const chartRows = (arr) => (arr || []).map(r => ({ label_en: r.key, label_ar: r.key, value: r.count }));

    root.innerHTML =
      milNav("workspace") +
      A.pageHead(t("mil.title"), t("mil.subtitle"), `
        <button class="btn primary" id="milSample">${icon("plus")} ${esc(t("mil.action.loadSample"))}</button>
        <button class="btn" id="milSampleReset">${icon("history")} ${esc(t("mil.action.resetSample"))}</button>
        <button class="btn" id="milSampleClear">${icon("trash")} ${esc(t("mil.action.clearSample"))}</button>`) +
      `<div class="notice">${icon("eye")} ${esc(t("mil.disclaimer"))}</div>
      <div class="grid auto" style="margin-bottom:18px">
        ${kpis.map((k, i) => `
          <div class="kpi" style="--kpi-color:${A.PALETTE[i % A.PALETTE.length]}">
            <div class="k-label">${esc(t(k[0]))}</div>
            <div class="k-value">${fmtNum(k[1])}</div>
            <div class="k-foot"><span class="muted">${esc(String(k[2]))}</span></div>
          </div>`).join("")}
      </div>
      <div class="grid c3">
        <div class="card"><div class="card-head"><h3>${esc(t("mil.chart.unitStatus"))}</h3></div>
          ${chart("bar", chartRows(ch.unit_status))}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.chart.unitType"))}</h3></div>
          ${chart("bar", chartRows(ch.unit_type))}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.chart.regionDist"))}</h3></div>
          ${chart("bar", chartRows(ch.region_distribution))}</div>
      </div>
      <div class="card" style="margin-bottom:18px">
        <div class="card-head"><h3>${esc(t("mil.quality.title"))}</h3></div>
        <div class="small muted" style="margin-bottom:10px">${esc(t("mil.quality.subtitle"))}</div>
        ${(qual.buckets || []).length ? Object.entries(qual.entities || {})
          .filter(([, q]) => q.total > 0).map(([e, q]) => `
          <div class="qrow">
            <span class="qlabel">${esc(entLabel(e))}</span>
            <span class="qbar">${qual.buckets.map((b, i) => {
              const n = q.histogram[b] || 0;
              return n ? `<span class="qseg q${i}" style="width:${(100 * n / q.total).toFixed(1)}%"
                title="${esc(b)}: ${n}"></span>` : "";
            }).join("")}</span>
            <span class="qnum small muted">${fmtNum(q.total)}</span>
          </div>`).join("") : `<div class="empty">${esc(t("list.noRecords"))}</div>`}
        <div class="btn-row" style="margin-top:10px">
          ${(qual.buckets || []).map((b, i) =>
            `<span class="chip q${i}">${esc(b)}</span>`).join(" ")}
        </div>
      </div>
      <div class="grid c2">
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.upcomingDeployments"))}</h3>
          <a class="btn sm" href="#/military/deployments">${esc(t("common.view"))}</a></div>
          ${table([t("mil.col.name"), t("mil.col.unit"), t("mil.col.start"), t("common.status")],
            lists.upcoming_deployments, r => `
            <tr><td><a href="#/military/deployments/${r.id}/show">${esc(r.name)}</a></td>
              <td>${esc(r.unit_name)}</td><td class="nowrap mono-cell">${esc(r.start_date)}</td>
              <td>${chip(r.status)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.upcomingTrainings"))}</h3>
          <a class="btn sm" href="#/military/trainings">${esc(t("common.view"))}</a></div>
          ${table([t("mil.col.exercise"), t("mil.col.unit"), t("mil.col.dates"), t("mil.col.participants")],
            lists.upcoming_trainings, r => `
            <tr><td><a href="#/military/trainings/${r.id}/show">${esc(r.exercise_name)}</a></td>
              <td>${esc(r.unit_name)}</td><td class="nowrap mono-cell">${esc(r.start_date)} → ${esc(r.end_date)}</td>
              <td>${fmtNum(r.participant_count)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.lowReadiness"))}</h3>
          <a class="btn sm" href="#/military/units">${esc(t("common.view"))}</a></div>
          ${table([t("mil.col.unit"), t("common.status"), t("mil.col.readiness")],
            lists.low_readiness_units, r => `
            <tr><td><a href="#/military/units/${r.id}/show">${esc(r.name)}</a></td>
              <td>${chip(r.status)}</td><td>${chip(r.readiness_tier || "—")}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.unitReadiness"))}</h3></div>
          ${table([t("mil.col.unit"), t("common.status"), t("mil.col.personnel"), t("mil.col.classification")],
            lists.unit_readiness, r => `
            <tr><td><a href="#/military/units/${r.id}/show">${esc(r.name)}</a></td>
              <td>${chip(r.status)}</td><td>${fmtNum(r.direct_personnel)}</td>
              <td>${esc(r.classification_name || "—")}</td></tr>`)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h3>${esc(t("mil.list.recentActivity"))}</h3>
          <a class="btn sm" href="#/military/audit">${esc(t("common.view"))}</a></div>
        ${table([t("mil.col.when"), t("mil.col.actor"), t("mil.col.action"), t("mil.col.record"), t("mil.col.summary")],
          lists.recent_activity, r => `
          <tr><td class="nowrap mono-cell">${esc(r.at)}</td><td>${esc(r.actor)}</td>
            <td>${esc(r.action)} · ${esc(r.entity)}</td>
            <td class="mono-cell">${esc(r.docname || "#" + (r.record_id || ""))}</td>
            <td class="small muted">${esc(r.summary || "")}</td></tr>`)}</div>`;

    bindChrome(root);
    const run = async (fn) => {
      if (role() === "viewer") { toast(t("mil.role.viewerBlocked"), "err"); return; }
      try { await fn(); A.rerender(); } catch (err) { toast(err.message, "err"); }
    };
    root.querySelector("#milSample").onclick = () =>
      run(() => mreq("POST", "/sample", {}));
    root.querySelector("#milSampleReset").onclick = () =>
      run(() => mreq("POST", "/sample", { force: true }));
    root.querySelector("#milSampleClear").onclick = async () => {
      const ok = await A.confirmDialog({
        title: t("mil.action.clearSample"), message: t("mil.action.confirmDelete"),
        confirmLabel: t("common.confirm")
      });
      if (ok) run(() => mreq("DELETE", "/sample"));
    };
  };

  /* ===================================================== view: domain hub */
  A.views.milDomain = async function (root, params) {
    const domain = params.domain;
    if (!DOMAINS[domain]) { location.hash = "#/military"; return; }
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: t(DOMAIN_LABEL[domain]) }]);
    const [qual, summary] = await Promise.all([
      mreq("GET", "/quality"), mreq("GET", "/summary")]);
    const entities = DOMAINS[domain];
    const totals = entities.map(e => ({
      key: e, total: ((qual.entities || {})[e] || {}).total || 0
    }));
    const primary = DOMAIN_PRIMARY[domain];
    const [listTitleKey, listKey] = DOMAIN_SUMMARY_LIST[domain];
    const rows = (summary.lists || {})[listKey] || [];
    const listRow = r => `
      <tr>
        <td class="mono-cell">${esc(r.docname || "")}</td>
        <td>${esc(r.name || r.exercise_name || r.title || "—")}</td>
        <td>${esc(r.unit_name || r.start_date || "")}</td>
        <td>${r.status ? chip(r.status) : "—"}</td>
        <td class="nowrap">${r.id ? `<a class="btn sm" href="#/military/${{
            upcoming_deployments: "deployments", upcoming_trainings: "trainings",
            low_readiness_units: "units", recent_activity: "units",
            unit_readiness: "units"
          }[listKey] || "units"}/${r.id}/show">${esc(t("common.view"))}</a>` : ""}</td>
      </tr>`;

    root.innerHTML = milNav("domain:" + domain) +
      A.pageHead(t(DOMAIN_LABEL[domain]), t("mil.domain.subtitle"), `
        <a class="btn primary" href="#/military/${primary}s/new">${icon("plus")} ${esc(t("common.new"))} — ${esc(entLabel(primary))}</a>`) +
      `<div class="grid auto" style="margin-bottom:18px">
        ${totals.map((tn, i) => `
          <div class="kpi" style="--kpi-color:${A.PALETTE[i % A.PALETTE.length]}">
            <div class="k-label">${esc(entLabel(tn.key))}</div>
            <div class="k-value">${fmtNum(tn.total)}</div>
            <div class="k-foot"><a class="muted" href="#/military/${tn.key}s">${esc(t("mil.domain.manage"))}</a></div>
          </div>`).join("")}
      </div>
      <div class="card" style="margin-bottom:18px">
        <div class="card-head"><h3>${esc(t("mil.domain.manageAll"))}</h3></div>
        <div class="grid c3">
          ${entities.map(e => `
            <div class="card inner">
              <div class="card-head"><h4>${esc(entLabel(e))}</h4>
                <span class="badge slate">${fmtNum(((qual.entities || {})[e] || {}).total || 0)}</span></div>
              <div class="btn-row">
                <a class="btn sm" href="#/military/${e}s">${esc(t("mil.domain.manage"))}</a>
                <a class="btn sm" href="#/military/${e}s/new">${icon("plus")} ${esc(t("common.new"))}</a>
                ${e === "unit" ? `<a class="btn sm" href="#/military/units/tree">${esc(t("mil.nav.unitsTree"))}</a>` : ""}
                ${e === "region" ? `<a class="btn sm" href="#/military/regions/tree">${esc(t("mil.nav.regionsTree"))}</a>` : ""}
              </div>
            </div>`).join("")}
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h3>${esc(t(listTitleKey))}</h3>
          <span class="badge slate">${fmtNum(rows.length)}</span></div>
        ${rows.length ? `
        <div class="table-wrap"><table class="data">
          <thead><tr><th>${esc(t("mil.form.docname"))}</th><th>${esc(t("mil.dossier.name"))}</th>
            <th>${esc(t("mil.col.unit"))}</th><th>${esc(t("common.status"))}</th>
            <th>${esc(t("common.actions"))}</th></tr></thead>
          <tbody>${rows.map(listRow).join("")}</tbody>
        </table></div>` : `<div class="empty">${esc(t("list.noRecords"))}</div>`}
      </div>`;
    bindChrome(root);
  };

  /* ========================================================= view: list */
  A.views.milList = async function (root, params) {
    const entity = params.entity;
    const m = await meta();
    const spec = m.entities[entity];
    if (!spec) { location.hash = "#/military"; return; }
    A.crumbs([{ label: t("nav.military"), href: "#/military" }, { label: entLabel(entity) }]);
    const names = spec.fields.map(f => f.name);
    const cols = ["name", "full_name", "exercise_name", "code", "entity_type"]
      .filter(n => names.includes(n)).slice(0, 1)
      .concat(["status", "category", "role", "condition", "echelon", "region_type"]
        .filter(n => names.includes(n)).slice(0, 1))
      .concat(["unit_id", "start_date", "quantity", "author"]
        .filter(n => names.includes(n)).slice(0, 2));
    const colSpecs = cols.map(n => spec.fields.find(f => f.name === n));
    /* reference columns resolve labels from a fully paged id map */
    const refMap = {};
    await Promise.all(colSpecs.filter(f => f && f.type === "ref").map(async f => {
      if (!refMap[f.entity]) {
        const rows = await refOptions(f.entity);
        refMap[f.entity] = {};
        rows.forEach(r => { refMap[f.entity][r.id] = r; });
      }
    }));

    const state = { q: "", sort: "id", direction: "asc", filters: {}, offset: 0,
      rows: [], mode: localStorage.getItem("siraj.mil.vm." + entity) || "table" };
    /* deep links: #/military/deployments?unit_id=5 opens pre-filtered */
    const hashQuery = (location.hash.split("?")[1] || "");
    new URLSearchParams(hashQuery).forEach((v, k) => {
      if (k === "q") state.q = v;
      else if (k === "sort") state.sort = v;
      else if (k === "direction") state.direction = v;
      else if (names.includes(k)) state.filters[k] = v;
    });
    const facets = spec.fields.filter(f => f.type === "choice");
    const rowHtml = r => `
      <tr data-search="${esc(JSON.stringify(r).toLowerCase())}">
        <td class="mono-cell">${esc(r.docname)}</td>
        ${colSpecs.map(f => `<td>${cell(r, f, refMap)}</td>`).join("")}
        <td class="nowrap">
          <a class="btn sm" href="#/military/${entity}s/${r.id}/show">${esc(t("common.view"))}</a>
          <a class="btn sm" href="#/military/${entity}s/${r.id}">${esc(t("common.edit"))}</a>
        </td>
      </tr>`;
    const cardHtml = r => `
      <div class="card inner">
        <div class="card-head"><h4>${esc(r.name || r.full_name || r.exercise_name || r.docname || "#" + r.id)}</h4>
          ${r.status ? chip(r.status) : ""}</div>
        <div class="small muted mono-cell">${esc(r.docname || "")}</div>
        <div class="small">${colSpecs.map(f => `${esc(fieldLabel(f))}: ${cell(r, f, refMap)}`).join(" · ")}</div>
        <div class="btn-row" style="margin-top:8px">
          <a class="btn sm" href="#/military/${entity}s/${r.id}/show">${esc(t("common.view"))}</a>
          <a class="btn sm" href="#/military/${entity}s/${r.id}">${esc(t("common.edit"))}</a>
        </div>
      </div>`;
    const query = () => {
      const p = new URLSearchParams();
      if (state.q) p.set("q", state.q);
      if (state.sort !== "id" || state.direction !== "asc") {
        p.set("sort", state.sort);
        p.set("direction", state.direction);
      }
      Object.entries(state.filters).forEach(([k, v]) => { if (v) p.set(k, v); });
      return p.toString();
    };
    const th = (label, key) =>
      `<th class="sortable" data-sort="${esc(key)}" aria-sort="${
        state.sort === key ? (state.direction === "asc" ? "ascending" : "descending") : "none"
      }">${esc(label)}</th>`;
    const isTree = entity === "unit" || entity === "region";

    root.innerHTML = milNav("e:" + entity) +
      A.pageHead(entLabel(entity), t("mil.list.count", { n: "—" }), `
        <a class="btn primary" href="#/military/${entity}s/new">${icon("plus")} ${esc(t("common.new"))}</a>`) +
      `<div class="card">
        <div class="btn-row" style="margin-bottom:12px">
          <input id="milSearch" type="search" class="grow" value="${esc(state.q)}"
            placeholder="${esc(t("mil.search.placeholder"))}" style="max-width:240px">
          ${facets.map(f => `<select class="ghost-select milFacet" data-field="${f.name}">
            <option value="">${esc(fieldLabel(f))}: ${esc(t("mil.list.all"))}</option>
            ${(f.options || []).map(o => `<option value="${esc(o)}"${state.filters[f.name] === o ? " selected" : ""}>${esc(o)}</option>`).join("")}
          </select>`).join("")}
          <button class="btn sm" id="milClearFilters">${esc(t("mil.list.clearFilters"))}</button>
          <span class="vmodes">
            <button class="btn sm${state.mode === "table" ? " primary" : ""}" id="milVmTable">${esc(t("mil.view.table"))}</button>
            <button class="btn sm${state.mode === "cards" ? " primary" : ""}" id="milVmCards">${esc(t("mil.view.cards"))}</button>
          </span>
          ${isTree ? `<a class="btn sm" href="#/military/${entity}s/tree">${esc(t("mil.view.tree"))}</a>` : ""}
          <button class="btn sm" id="milImport">${icon("plus")} ${esc(t("mil.import.button"))}</button>
          <button class="btn sm" id="milExport">${icon("download")} ${esc(t("mil.list.export"))}</button>
        </div>
        <div id="milImportPanel" class="import-panel" hidden>
          <div class="btn-row" style="margin-bottom:8px">
            <input type="file" id="milImportFile" accept=".csv,text/csv">
            <select class="ghost-select" id="milImportMode">
              <option value="create">${esc(t("mil.import.modeCreate"))}</option>
              <option value="upsert">${esc(t("mil.import.modeUpsert"))}</option>
            </select>
            <button class="btn primary" id="milImportRun">${esc(t("mil.import.run"))}</button>
            <span class="small muted">${esc(t("mil.import.hint"))}</span>
          </div>
          <div id="milImportReport"></div>
        </div>
        <div id="milTableWrap" class="table-wrap"><table class="data">
          <thead><tr>${th(t("mil.form.docname"), "docname")}${
            colSpecs.map(f => th(fieldLabel(f), f.name)).join("")
          }<th>${esc(t("common.actions"))}</th></tr></thead>
          <tbody></tbody>
        </table></div>
        <div id="milCardGrid" class="grid c3" hidden></div>
        <div class="btn-row" style="margin-top:12px">
          <button id="milMore" class="btn" hidden></button>
        </div>
      </div>`;
    bindChrome(root);

    const renderAll = () => {
      const tbody = root.querySelector("tbody");
      const grid = root.querySelector("#milCardGrid");
      const wrap = root.querySelector("#milTableWrap");
      if (!state.rows.length) {
        tbody.innerHTML = `<tr><td colspan="${colSpecs.length + 2}" class="empty">${esc(t("list.noRecords"))}</td></tr>`;
        grid.innerHTML = `<div class="empty">${esc(t("list.noRecords"))}</div>`;
      } else {
        tbody.innerHTML = state.rows.map(rowHtml).join("");
        grid.innerHTML = state.rows.map(cardHtml).join("");
      }
      wrap.hidden = state.mode !== "table";
      grid.hidden = state.mode !== "cards";
    };
    const moreBtn = root.querySelector("#milMore");
    const loadPage = async (append) => {
      const data = await mreq("GET", "/" + entity + "s?limit=200&offset="
        + state.offset + (query() ? "&" + query() : ""));
      if (!append) state.rows = [];
      state.rows.push(...data.records);
      state.offset += data.records.length;
      renderAll();
      const sub = root.querySelector(".page-head .sub");
      if (sub) sub.textContent = t("mil.list.count", { n: fmtNum(data.total) });
      const rest = data.total - state.offset;
      if (rest > 0) {
        moreBtn.hidden = false;
        moreBtn.textContent = t("mil.list.loadMore", { n: fmtNum(Math.min(200, rest)) });
      } else {
        moreBtn.hidden = true;
      }
    };
    const reset = () => { state.offset = 0; loadPage(false); };
    const setMode = (mode) => {
      state.mode = mode;
      localStorage.setItem("siraj.mil.vm." + entity, mode);
      root.querySelector("#milVmTable").classList.toggle("primary", mode === "table");
      root.querySelector("#milVmCards").classList.toggle("primary", mode === "cards");
      renderAll();
    };

    let searchTimer;
    root.querySelector("#milSearch").oninput = (ev) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.q = ev.target.value.trim();
        reset();
      }, 250);
    };
    root.querySelectorAll(".milFacet").forEach(sel => {
      sel.onchange = () => {
        state.filters[sel.dataset.field] = sel.value;
        reset();
      };
    });
    root.querySelector("#milClearFilters").onclick = () => {
      state.q = "";
      state.filters = {};
      root.querySelector("#milSearch").value = "";
      root.querySelectorAll(".milFacet").forEach(sel => { sel.value = ""; });
      reset();
    };
    root.querySelectorAll("th.sortable").forEach(el => {
      el.onclick = () => {
        const key = el.dataset.sort;
        state.direction = (state.sort === key && state.direction === "asc") ? "desc" : "asc";
        state.sort = key;
        reset();
      };
    });
    moreBtn.onclick = () => loadPage(true);
    root.querySelector("#milVmTable").onclick = () => setMode("table");
    root.querySelector("#milVmCards").onclick = () => setMode("cards");
    root.querySelector("#milExport").onclick = async () => {
      const res = await mreq("GET", "/" + entity + "s/export.csv"
        + (query() ? "?" + query() : ""));
      const blob = new Blob([res.csv], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = res.filename;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(t("mil.list.export") + " ✓", "ok");
    };

    /* CSV import through the full rule engine (staff+; per-row report) */
    const panel = root.querySelector("#milImportPanel");
    root.querySelector("#milImport").onclick = () => { panel.hidden = !panel.hidden; };
    root.querySelector("#milImportRun").onclick = async () => {
      if (role() === "viewer") { toast(t("mil.role.viewerBlocked"), "err"); return; }
      const file = root.querySelector("#milImportFile").files[0];
      if (!file) { toast(t("mil.import.pickFile"), "err"); return; }
      const text = await file.text();
      const mode = root.querySelector("#milImportMode").value;
      try {
        const res = await mreq("POST", "/" + entity + "s/import.csv", { csv: text, mode });
        const s = res.summary;
        const errs = res.results.filter(r => r.status === "error");
        root.querySelector("#milImportReport").innerHTML = `
          <div class="notice">${esc(t("mil.import.summary",
            { created: s.created, updated: s.updated, errors: s.errors }))}</div>
          ${errs.length ? `<div class="table-wrap"><table class="data">
            <thead><tr><th>${esc(t("mil.import.line"))}</th>
              <th>${esc(t("mil.dossier.status"))}</th>
              <th>${esc(t("mil.import.message"))}</th></tr></thead>
            <tbody>${errs.map(r => `<tr><td>${r.line}</td>
              <td>${chip("error")}</td><td>${esc(r.message)}</td></tr>`).join("")}</tbody>
          </table></div>` : ""}`;
        toast(t("mil.import.done"), s.errors ? "err" : "ok");
        reset();
      } catch (err) { toast(err.message, "err"); }
    };
    await loadPage(false);
  };

  function cell(rec, f, refMap) {
    const v = rec[f.name];
    if (v == null || v === "") return "—";
    if (f.type === "bool") return v ? "✓" : "—";
    if (f.name === "status" || f.name === "condition" || f.name === "readiness_tier"
        || f.name === "assessment") return chip(v);
    if (f.type === "ref") {
      const r = (refMap[f.entity] || {})[v];
      return esc(r ? refLabelOf(f.entity, r) : "#" + v);
    }
    return esc(String(v));
  }

  /* ========================================================= view: form */
  A.views.milForm = async function (root, params) {
    const entity = params.entity, id = params.id ? Number(params.id) : null;
    const m = await meta();
    const spec = m.entities[entity];
    if (!spec) { location.hash = "#/military"; return; }
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: entLabel(entity), href: "#/military/" + entity + "s" },
      { label: id ? "#" + id : t("common.new") }]);
    const record = id ? (await mreq("GET", "/" + entity + "s/" + id)).record : {};
    const refs = {};
    await Promise.all(spec.fields.filter(f => f.type === "ref").map(async f => {
      if (!refs[f.entity]) refs[f.entity] = await refOptions(f.entity);
    }));

    const fieldsHtml = spec.fields.map(f => {
      const v = record[f.name];
      const req = f.required ? ` <span class="req">*</span>` : "";
      let control;
      if (f.type === "choice") {
        control = `<select name="${f.name}"><option value=""></option>${f.options.map(o =>
          `<option value="${esc(o)}"${String(v) === o ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
      } else if (f.type === "ref") {
        control = refCombo(f, v, refs);
      } else if (f.type === "textarea") {
        control = `<textarea name="${f.name}" rows="3">${esc(v || "")}</textarea>`;
      } else if (f.type === "bool") {
        control = `<select name="${f.name}">
          <option value="1"${v ? " selected" : ""}>${esc(t("common.yes"))}</option>
          <option value="0"${v ? "" : " selected"}>${esc(t("common.no"))}</option></select>`;
      } else {
        const type = f.type === "date" ? "date" : f.type === "int" ? "number" : "text";
        control = `<input type="${type}" name="${f.name}" value="${esc(v == null ? "" : v)}"
          ${f.min != null ? `min="${f.min}"` : ""}>`;
      }
      return `<div class="field" data-field="${f.name}">
        <label>${esc(fieldLabel(f))}${req}</label>${control}
        <div class="err"></div></div>`;
    }).join("");

    root.innerHTML = milNav("e:" + entity) +
      A.pageHead((id ? t("common.edit") : t("common.new")) + " — " + entLabel(entity),
        record.docname || "", `
        <a class="btn" href="#/military/${entity}s">${icon("undo")} ${esc(t("common.back"))}</a>
        ${id ? `<button class="btn" id="milDelete">${icon("trash")} ${esc(t("common.delete"))}</button>` : ""}`) +
      `<div class="card">${id ? "" : `
        <div class="name-preview" id="milNamePreview">
          <span class="chip violet" id="milNameChip">${esc(t("mil.naming.preview"))} —</span>
          <span class="small muted">${esc(t("mil.naming.previewHint"))}</span>
        </div>`}
        <form id="milForm" class="form-grid">${fieldsHtml}</form>
        ${id ? `<hr class="hr-soft"><div class="small muted">
          ${esc(t("mil.form.created"))}: ${esc(record.created_at || "—")} · ${esc(record.created_by || "—")} ·
          ${esc(t("mil.form.modified"))}: ${esc(record.modified_at || "—")} · ${esc(record.modified_by || "—")}
        </div>` : ""}
        <div class="btn-row" style="margin-top:16px">
          <button class="btn primary" id="milSave">${icon("save")} ${esc(t("common.save"))}</button>
          <a class="btn" href="#/military/${entity}s">${esc(t("common.cancel"))}</a>
        </div>
      </div>`;

    if (id) {
      root.querySelector(".card .btn-row").insertAdjacentHTML("beforeend",
        `<a class="btn" href="#/military/${entity}s/${id}/show">${icon("eye")} ${esc(t("common.view"))}</a>`);
    }
    if (entity === "unit" && id) {
      root.querySelector(".card .btn-row").insertAdjacentHTML("beforeend",
        `<a class="btn" href="#/military/units/${id}/force">${icon("activity")} ${esc(t("mil.force.title"))}</a>`);
    }
    bindChrome(root);
    const form = root.querySelector("#milForm");
    bindRefCombos(root, refs);

    /* live advisory document-name preview (automated numbering control) */
    if (!id) {
      const chip = root.querySelector("#milNameChip");
      let timer;
      const refreshPreview = async () => {
        const payload = { entity };
        spec.fields.forEach(f => {
          if (f.type === "choice") {
            const el = form.elements[f.name];
            if (el && el.value) payload[f.name] = el.value;
          }
        });
        try {
          const res = await mreq("POST", "/naming/preview", payload);
          chip.textContent = t("mil.naming.preview") + ": " + res.next;
        } catch (e) { /* advisory only — never block the form */ }
      };
      form.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(refreshPreview, 400);
      });
      form.addEventListener("change", () => {
        clearTimeout(timer);
        timer = setTimeout(refreshPreview, 150);
      });
      refreshPreview();
    }

    const clearErrors = () => form.querySelectorAll(".field").forEach(el => {
      el.classList.remove("invalid");
      const e = el.querySelector(".err");
      if (e) e.textContent = "";
    });
    const showErrors = (err) => {
      clearErrors();
      if (err.field) {
        const el = form.querySelector(`.field[data-field="${err.field}"]`);
        if (el) {
          el.classList.add("invalid");
          el.querySelector(".err").textContent = err.message;
        }
      }
      toast(err.message, "err");
    };
    root.querySelector("#milSave").onclick = async () => {
      if (role() === "viewer") { toast(t("mil.role.viewerBlocked"), "err"); return; }
      clearErrors();
      const payload = {};
      spec.fields.forEach(f => {
        const el = form.elements[f.name];
        if (!el) return;
        let v = el.value;
        if (f.type === "int" && v !== "") v = Number(v);
        if (f.type === "bool") v = el.value === "1";
        if (f.type === "ref" && v !== "") v = Number(v);
        payload[f.name] = v === "" ? null : v;
      });
      try {
        const res = id
          ? await mreq("PATCH", "/" + entity + "s/" + id, payload)
          : await mreq("POST", "/" + entity + "s", payload);
        toast(t("common.saved"), "ok");
        location.hash = "#/military/" + entity + "s/" + res.record.id;
      } catch (err) { showErrors(err); }
    };
    const del = root.querySelector("#milDelete");
    if (del) del.onclick = async () => {
      if (role() !== "admin") { toast(t("mil.role.viewerBlocked"), "err"); return; }
      const ok = await A.confirmDialog({
        title: t("common.delete"), message: t("mil.action.confirmDelete"),
        confirmLabel: t("common.confirm")
      });
      if (!ok) return;
      try {
        await mreq("DELETE", "/" + entity + "s/" + id);
        toast(t("common.deleted"), "ok");
        location.hash = "#/military/" + entity + "s";
      } catch (err) { toast(err.message, "err"); }
    };
  };

  /* ====================================================== view: dossier */
  const FICTIONAL_SUFFIX = " (fictional note)";
  const RELATED = {
    unit: [["deployments", "unit_id"], ["missions", "unit_id"],
           ["holdings", "unit_id"], ["trainings", "unit_id"],
           ["assignments", "unit_id"], ["units", "parent_id"]],
    region: [["regions", "parent_id"], ["units", "region_id"]],
    division: [["units", "division_id"]],
    classification: [["units", "classification_id"]],
    commander: [["assignments", "commander_id"]],
    deployment: [["missions", "deployment_id"]],
    armament: [["holdings", "armament_id"]],
    training: [], holding: [], assignment: [], note: []
  };

  A.views.milDossier = async function (root, params) {
    const entity = params.entity;
    const id = Number(params.id);
    const m = await meta();
    const spec = m.entities[entity];
    if (!spec) { location.hash = "#/military"; return; }
    const rec = (await mreq("GET", "/" + entity + "s/" + id)).record;
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: entLabel(entity), href: "#/military/" + entity + "s" },
      { label: rec.docname || "#" + id }]);

    const refMap = {};
    await Promise.all(spec.fields.filter(f => f.type === "ref").map(async f => {
      if (!refMap[f.entity]) {
        const rows = await refOptions(f.entity);
        refMap[f.entity] = {};
        rows.forEach(r => { refMap[f.entity][r.id] = r; });
      }
    }));

    const relData = await Promise.all((RELATED[entity] || []).map(async ([slug, fk]) => {
      const data = await mreq("GET", "/" + slug + "?limit=10&sort=id&direction=desc&"
        + fk + "=" + id);
      return { slug, fk, rows: data.records || [], total: data.total || 0 };
    }));
    const relLimit = 10;
    const notes = await mreq("GET",
      "/notes?limit=50&sort=id&direction=desc&entity_type=" + entity + "&target_id=" + id);

    const labelOf = (slug) => entLabel(slug.replace(/s$/, ""));
    const relRow = (slug, r) => `
      <tr>
        <td class="mono-cell">${esc(r.docname || "#" + r.id)}</td>
        <td>${esc(r.name || r.full_name || r.exercise_name || r.note_text || "—")}</td>
        <td>${r.status ? chip(r.status) : (r.start_date ? esc(r.start_date) : "—")}</td>
        <td class="nowrap">
          <a class="btn sm" href="#/military/${slug.replace(/s$/, "")}s/${r.id}/show">${esc(t("common.view"))}</a>
        </td>
      </tr>`;

    root.innerHTML = milNav("e:" + entity) +
      A.pageHead(rec.docname || "#" + id, entLabel(entity), `
        <a class="btn" href="#/military/${entity}s">${icon("undo")} ${esc(t("common.back"))}</a>
        <a class="btn primary" href="#/military/${entity}s/${id}">${icon("edit") || ""} ${esc(t("common.edit"))}</a>`) +
      `<div class="card">
        <div class="card-head"><h2>${esc(t("mil.dossier.fields"))}</h2></div>
        <dl class="dossier-grid">
          ${spec.fields.map(f => `
            <div class="dfield"><dt>${esc(fieldLabel(f))}</dt>
              <dd>${cell(rec, f, refMap)}</dd></div>`).join("")}
          <div class="dfield"><dt>${esc(t("mil.form.created"))}</dt>
            <dd>${esc(rec.created_at || "—")} · ${esc(rec.created_by || "—")}</dd></div>
          <div class="dfield"><dt>${esc(t("mil.form.modified"))}</dt>
            <dd>${esc(rec.modified_at || "—")} · ${esc(rec.modified_by || "—")}</dd></div>
        </dl>
      </div>
      ${relData.filter(d => d.rows.length || d.total).map(d => `
      <div class="card">
        <div class="card-head"><h2>${esc(labelOf(d.slug))}</h2>
          <span class="badge slate" data-relcount="${esc(d.slug)}">${fmtNum(d.total)}</span>
          ${d.total > d.rows.length ? `
            <button class="btn sm" data-relmore="${esc(d.slug)}"
              data-relfk="${esc(d.fk)}" data-relid="${id}">${esc(t("mil.dossier.showMore"))}</button>
            <a class="btn sm" style="margin-left:6px"
              href="#/military/${d.slug}?${esc(d.fk)}=${id}">${esc(t("mil.dossier.seeAll"))}</a>` : ""}</div>
        <div class="table-wrap"><table class="data">
          <thead><tr><th>${esc(t("mil.form.docname"))}</th><th>${esc(t("mil.dossier.name"))}</th>
            <th>${esc(t("mil.dossier.status"))}</th><th>${esc(t("common.actions"))}</th></tr></thead>
          <tbody data-relbody="${esc(d.slug)}">${d.rows.map(r => relRow(d.slug, r)).join("")}</tbody>
        </table></div>
      </div>`).join("")}
      <div class="card" id="milNotesCard">
        <div class="card-head"><h2>${esc(t("mil.dossier.notes"))}</h2>
          <span class="badge slate">${fmtNum(notes.total || (notes.records || []).length)}</span></div>
        ${role() === "viewer" ? "" : `
        <div class="btn-row" style="margin-bottom:12px">
          <input id="milNoteText" class="grow" placeholder="${esc(t("mil.dossier.notePlaceholder"))}">
          <button class="btn primary" id="milNoteAdd">${icon("plus")} ${esc(t("mil.dossier.addNote"))}</button>
        </div>`}
        ${(notes.records || []).length ? `
        <div class="table-wrap"><table class="data">
          <thead><tr><th>${esc(t("mil.form.docname"))}</th><th>${esc(t("mil.dossier.noteText"))}</th>
            <th>${esc(t("mil.form.author"))}</th><th>${esc(t("mil.form.date"))}</th></tr></thead>
          <tbody>${(notes.records || []).map(n => `
            <tr><td class="mono-cell">${esc(n.docname || "")}</td>
              <td>${esc(n.note_text || "")}</td>
              <td>${esc(n.author || "—")}</td>
              <td>${esc(n.note_at || "—")}</td></tr>`).join("")}</tbody>
        </table></div>` : `<div class="empty">${esc(t("mil.dossier.noRelated"))}</div>`}
      </div>`;
    bindChrome(root);
    /* show more — append the next page of a related panel */
    root.querySelectorAll("[data-relmore]").forEach(btn => {
      btn.onclick = async () => {
        const slug = btn.dataset.relmore;
        const fk = btn.dataset.relfk;
        const tbody = root.querySelector(`tbody[data-relbody="${slug}"]`);
        const loaded = tbody.querySelectorAll("tr").length;
        btn.disabled = true;
        const data = await mreq("GET", "/" + slug + "?limit=" + relLimit
          + "&offset=" + loaded + "&sort=id&direction=desc&" + fk + "=" + btn.dataset.relid);
        tbody.insertAdjacentHTML("beforeend",
          (data.records || []).map(r => relRow(slug, r)).join(""));
        btn.disabled = false;
        if (tbody.querySelectorAll("tr").length >= (data.total || 0)) btn.remove();
      };
    });
    const addBtn = root.querySelector("#milNoteAdd");
    if (addBtn) addBtn.onclick = async () => {
      const text = root.querySelector("#milNoteText").value.trim();
      if (!text) return;
      try {
        await mreq("POST", "/notes", {
          entity_type: entity, target_id: id,
          note_text: text + FICTIONAL_SUFFIX, author: "app-user"
        });
        toast(t("common.saved"), "ok");
        A.rerender();
      } catch (err) { toast(err.message, "err"); }
    };
  };

  /* ========================================================= view: tree */
  A.views.milTree = async function (root, params) {
    const kind = params.kind === "regions" ? "regions" : "units";
    const entity = kind === "units" ? "unit" : "region";
    await meta();
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: kind === "units" ? t("mil.nav.unitsTree") : t("mil.nav.regionsTree") }]);
    const data = await mreq("GET", "/" + kind + "/tree");

    const nodeHtml = (n, depth) => {
      const hasKids = n.children && n.children.length;
      const extra = kind === "units"
        ? ` <span class="small muted">Σ ${fmtNum(n.subtree_personnel != null ? n.subtree_personnel : 0)} · ${esc(t("mil.tree.subtreePersonnel"))}</span>`
        : "";
      return `<li><details${hasKids && depth < 1 ? " open" : ""}>
        <summary><div class="mil-node">
          <span class="mil-toggle">${hasKids ? "▾" : "·"}</span>
          <a href="#/military/${entity}s/${n.id}"><b>${esc(n.name)}</b></a>
          <span class="mono-cell small">${esc(n.docname)}</span>
          ${kind === "units" ? chip(n.status) : badge(n.region_type || "—", "slate")}${extra}
        </div></summary>
        ${hasKids ? `<ul>${n.children.map(c => nodeHtml(c, depth + 1)).join("")}</ul>` : ""}
      </details></li>`;
    };

    root.innerHTML = milNav("tree:" + kind) +
      A.pageHead(kind === "units" ? t("mil.nav.unitsTree") : t("mil.nav.regionsTree"),
        t("mil.tree.subtitle"), `
        <a class="btn primary" href="#/military/${entity}s/new">${icon("plus")} ${esc(t("common.new"))}</a>`) +
      `<div class="card">
        <input id="milTreeSearch" type="search" placeholder="${esc(t("mil.tree.filter"))}"
          style="max-width:320px;margin-bottom:12px">
        <div class="mil-tree"><ul>${data.tree.map(n => nodeHtml(n, 0)).join("")}</ul></div>
      </div>`;
    bindChrome(root);
    const search = root.querySelector("#milTreeSearch");
    search.oninput = () => {
      const q = search.value.trim().toLowerCase();
      root.querySelectorAll(".mil-tree li").forEach(li => {
        const match = !q || li.textContent.toLowerCase().includes(q);
        li.style.display = match ? "" : "none";
        if (q && match) {
          let p = li.parentElement;
          while (p && !p.classList.contains("mil-tree")) {
            if (p.tagName === "DETAILS") p.open = true;
            if (p.tagName === "LI") p.style.display = "";
            p = p.parentElement;
          }
        }
      });
    };
  };

  /* ==================================================== view: force sum */
  A.views.milForce = async function (root, params) {
    const id = Number(params.id);
    await meta();
    const d = await mreq("GET", "/units/" + id + "/force-summary");
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: t("mil.nav.unitsTree"), href: "#/military/units/tree" },
      { label: d.unit.name }]);
    root.innerHTML = milNav("tree:units") +
      A.pageHead(t("mil.force.title"), d.unit.name + " · " + d.unit.docname, `
        <a class="btn" href="#/military/units/${id}">${icon("edit")} ${esc(t("common.edit"))}</a>
        <a class="btn" href="#/military/units/tree">${icon("undo")} ${esc(t("common.back"))}</a>`) +
      `<div class="grid auto" style="margin-bottom:18px">
        <div class="kpi"><div class="k-label">${esc(t("mil.tree.subtreePersonnel"))}</div>
          <div class="k-value">${fmtNum(d.subtree_personnel)}</div>
          <div class="k-foot">${esc(t("mil.force.direct"))}: ${fmtNum(d.unit.direct_personnel)}</div></div>
        <div class="kpi"><div class="k-label">${esc(t("mil.force.currentDeployment"))}</div>
          <div class="k-value" style="font-size:15px;line-height:1.4">${
            d.current_deployment
              ? `<a href="#/military/deployments/${d.current_deployment.id}/show">${esc(d.current_deployment.name)}</a>`
              : "—"}</div>
          <div class="k-foot">${d.current_deployment ? chip(d.current_deployment.status) : ""}</div></div>
      </div>
      <div class="grid c2">
        <div class="card"><div class="card-head"><h3>${esc(t("mil.force.children"))}</h3></div>
          ${table([t("mil.col.unit"), t("mil.form.docname"), t("common.status"), t("mil.col.personnel")],
            d.children, r => `<tr><td><a href="#/military/units/${r.id}/show">${esc(r.name)}</a></td>
              <td class="mono-cell">${esc(r.docname)}</td><td>${chip(r.status)}</td>
              <td>${fmtNum(r.direct_personnel)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.force.siblings"))}</h3></div>
          ${table([t("mil.col.unit"), t("common.status")], d.siblings, r =>
            `<tr><td><a href="#/military/units/${r.id}/show">${esc(r.name)}</a></td>
             <td>${chip(r.status)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.force.missions"))}</h3></div>
          ${table([t("mil.col.name"), t("common.status")], d.missions, r =>
            `<tr><td><a href="#/military/missions/${r.id}">${esc(r.name)}</a></td>
             <td>${chip(r.status)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.force.armament"))}</h3></div>
          ${table([t("mil.col.name"), t("mil.col.quantity"), t("mil.col.condition")],
            d.armament_top, r => `<tr><td>${esc(r.name)}</td>
             <td>${fmtNum(r.quantity)}</td><td>${chip(r.condition)}</td></tr>`)}</div>
      </div>`;
    bindChrome(root);
  };

  /* =================================================== view: holdings */
  A.views.milHoldings = async function (root, params) {
    const id = Number(params.id);
    await meta();
    const d = await mreq("GET", "/armaments/" + id + "/holdings");
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: entLabel("armament"), href: "#/military/armaments" },
      { label: d.armament.name }]);
    root.innerHTML = milNav("e:armament") +
      A.pageHead(t("mil.holdings.title"), d.armament.name + " · " + d.armament.docname, `
        <a class="btn" href="#/military/armaments">${icon("undo")} ${esc(t("common.back"))}</a>`) +
      `<div class="card"><p>${esc(t("mil.holdings.total"))}: <b>${fmtNum(d.total_quantity)}</b></p>
        ${table([t("mil.col.unit"), t("mil.col.quantity"), t("mil.col.condition"), t("mil.col.acquired")],
          d.holdings, r => `<tr>
          <td><a href="#/military/units/${r.unit_id}">${esc(r.unit_name)}</a></td>
          <td>${fmtNum(r.quantity)}</td><td>${chip(r.condition)}</td>
          <td>${esc(r.acquisition_year || "—")}</td></tr>`)}</div>`;
    bindChrome(root);
  };

  /* ==================================================== view: naming */
  A.views.milNaming = async function (root) {
    await meta();
    A.crumbs([{ label: t("nav.military"), href: "#/military" }, { label: t("mil.naming.title") }]);
    const [data, history] = await Promise.all([
      mreq("GET", "/naming/status"), mreq("GET", "/naming/history?limit=50")]);
    const byEntity = {};
    data.series.forEach(s => { (byEntity[s.entity] = byEntity[s.entity] || []).push(s); });

    root.innerHTML = milNav("naming") +
      A.pageHead(t("mil.naming.title"), t("mil.naming.help"), "") +
      `<div class="card">
        <div class="btn-row" style="margin-bottom:14px">
          <select id="milPrevEntity">${ENTITIES.map(k =>
            `<option value="${k}">${esc(entLabel(k))}</option>`).join("")}</select>
          <button class="btn primary" id="milPreview">${icon("eye")} ${esc(t("mil.action.preview"))}</button>
          <span class="mono-cell" id="milPrevOut"></span>
        </div>
        ${Object.keys(byEntity).map(entity => `
          <h3 style="margin:16px 0 8px">${esc(entLabel(entity))}</h3>
          ${table([t("mil.naming.series"), t("mil.naming.partition"), t("mil.naming.current"),
            t("mil.naming.next"), t("common.actions")], byEntity[entity], s => `
            <tr>
              <td class="mono-cell">${esc(s.label)}${s.is_default ? " ★" : ""}</td>
              <td class="mono-cell">${esc(s.partition || "(default)")}</td>
              <td>${fmtNum(s.current_value)}</td>
              <td class="mono-cell small">${esc(s.next_preview || "")}</td>
              <td>${role() === "admin" ? `
                <span class="flex" style="gap:6px">
                  <input type="number" min="0" style="width:90px" data-counter="${s.id}"
                    data-partition="${esc(s.partition)}" data-label="${esc(s.label)}">
                  <button class="btn sm" data-adjust="${s.id}">${esc(t("mil.action.adjust"))}</button>
                </span>` : ""}</td>
            </tr>`).join("")}`).join("")}
      </div>
      <div class="card" style="margin-top:18px">
        <div class="card-head"><h3>${esc(t("mil.naming.history"))}</h3>
          <span class="badge slate">${fmtNum((history.records || []).length)}</span></div>
        ${(history.records || []).length ? `
        <div class="table-wrap"><table class="data">
          <thead><tr><th>${esc(t("mil.naming.series"))}</th>
            <th>${esc(t("mil.naming.partition"))}</th>
            <th>${esc(t("mil.naming.oldValue"))}</th><th>${esc(t("mil.naming.newValue"))}</th>
            <th>${esc(t("mil.form.author"))}</th><th>${esc(t("mil.form.date"))}</th></tr></thead>
          <tbody>${(history.records || []).map(h => `
            <tr><td class="mono-cell">${esc(h.label)}</td>
              <td class="mono-cell">${esc(h.partition || "(default)")}</td>
              <td>${fmtNum(h.old_value)}</td><td>${fmtNum(h.new_value)}</td>
              <td>${esc(h.actor)}</td><td class="mono-cell small">${esc(h.at)}</td></tr>`).join("")}</tbody>
        </table></div>` : `<div class="empty">${esc(t("mil.dossier.noRelated"))}</div>`}
      </div>`;
    bindChrome(root);
    root.querySelector("#milPreview").onclick = async () => {
      try {
        const entity = root.querySelector("#milPrevEntity").value;
        const res = await mreq("POST", "/naming/preview", { entity });
        root.querySelector("#milPrevOut").textContent =
          res.next + " · " + t("mil.naming.advisory");
      } catch (err) { toast(err.message, "err"); }
    };
    root.querySelectorAll("[data-adjust]").forEach(btn => {
      btn.onclick = async () => {
        if (role() !== "admin") { toast(t("mil.role.viewerBlocked"), "err"); return; }
        const input = root.querySelector(`input[data-counter="${btn.dataset.adjust}"]`);
        const value = Number(input.value);
        if (!Number.isFinite(value) || value < 0) { toast(t("mil.naming.badValue"), "err"); return; }
        try {
          await mreq("PUT", "/naming/counter", {
            option_id: Number(btn.dataset.adjust),
            partition: input.dataset.partition,
            new_value: value,
            label: input.dataset.label
          });
          toast(t("common.saved"), "ok");
          A.rerender();
        } catch (err) { toast(err.message, "err"); }
      };
    });
  };

  /* ====================================================== view: audit */
  A.views.milAudit = async function (root) {
    await meta();
    A.crumbs([{ label: t("nav.military"), href: "#/military" }, { label: t("mil.audit.title") }]);
    if (role() !== "admin") {
      root.innerHTML = milNav("audit") +
        A.pageHead(t("mil.audit.title"), "", "") +
        `<div class="card"><div class="empty">${esc(t("mil.role.viewerBlocked"))}</div></div>`;
      bindChrome(root);
      return;
    }
    const data = await mreq("GET", "/audit/log?limit=100");
    root.innerHTML = milNav("audit") +
      A.pageHead(t("mil.audit.title"), t("mil.audit.subtitle"), "") +
      `<div class="card">
        ${table([t("mil.col.when"), t("mil.col.actor"), t("mil.col.action"),
          t("mil.col.record"), t("mil.col.summary")], data.records, r => `
          <tr><td class="nowrap mono-cell">${esc(r.at)}</td><td>${esc(r.actor)}</td>
            <td>${esc(r.action)} · ${esc(r.entity)}</td>
            <td class="mono-cell">${esc(r.docname || "#" + (r.record_id || ""))}</td>
            <td class="small muted">${esc(r.summary || "")}</td></tr>`)}</div>`;
    bindChrome(root);
  };
})();
