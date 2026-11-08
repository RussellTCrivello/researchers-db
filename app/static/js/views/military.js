/* ============================================================================
   SIRAJ · views/military.js — Military Organization (Brigade Command workspace)
   ----------------------------------------------------------------------------
   The Military Organization (BIMS) lives inside the shell like every other
   workspace: one navigation, one locale mechanism (mil.* keys), one theme, one
   design language.  Data comes from the self-contained /api/military API
   (its own SQLite module; the registry is only read to show the individual
   linked to a commander).  Every record shown is
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
    "deployment", "mission", "armament", "holding", "training", "assignment", "note",
    "trait"];

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
    /* the value is data, the label is language */
    return badge(String(A.optLabel(v)), STATUS_COLOR[String(v)] || "gray");
  }

  const entLabel = (key) => {
    const spec = (META && META.entities && META.entities[key]) || {};
    return A.state.lang === "ar" ? (spec.label_ar || spec.label || key)
      : (spec.label_en || spec.label || key);
  };
  const fieldLabel = (f) =>
    A.state.lang === "ar" ? (f.label_ar || f.label || f.name) : (f.label_en || f.label || f.name);

  /** Normalise a route slug ("units" or "unit") to the canonical entity key. */
  function entityKey(slug) {
    const s = String(slug || "");
    if (ENTITIES.includes(s)) return s;
    const bare = s.replace(/s$/, "");
    return ENTITIES.includes(bare) ? bare : null;
  }

  /* ------------------------------------------------------- shared chrome - */
  /* the four command domains — the primary organisation of the workspace */
  const DOMAINS = {
    forces: ["unit", "region", "division", "classification", "armament", "holding"],
    operations: ["deployment", "mission"],
    training: ["training"],
    command: ["commander", "assignment", "trait", "note"]
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
          item("#/military/regions/tree", t("mil.nav.regionsTree"), "tree:regions") +
          item("#/structures?source=units", t("mil.nav.structure"), "structure")
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
      A.pageHead(t("mil.title"), t("mil.subtitle"), "") +
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

  /* ============================================ view: unified entity list */
  /**
   * Every military table is browsed through the SAME list engine that serves
   * People / Places / Organizations — table, cards, gallery and list views, the
   * deep filter builder, column and card-layout control, saved views, bulk
   * actions and multi-format export — under the military workspace chrome.
   */
  A.views.milList = async function (root, params) {
    const entity = entityKey(params.entity);
    if (!entity) { location.hash = "#/military"; return; }
    /* units and regions offer the hierarchy tree right in the list's own view
       switcher — the tree is a view of the same screen, not a trip elsewhere */
    root.innerHTML = milNav("e:" + entity) +
      `<div class="toolbar" style="margin:10px 0">
        <a class="btn sm" href="#/military/${DOMAIN_OF[entity]}">${icon("undo")} ${esc(t("common.back"))}</a>
        <span class="spacer"></span>
        <button class="btn sm" id="milImportBtn">${icon("upload")} ${esc(t("mil.import.button"))}</button>
      </div>
      <div data-mil-list-host></div>`;
    if (A.hydrateIcons) A.hydrateIcons(root);
    const importBtn = root.querySelector("#milImportBtn");
    if (importBtn) importBtn.onclick = () =>
      (location.hash = `#/import?entity=${encodeURIComponent(entity)}`);
    /* deep links: #/military/deployments?unit_id=5 opens pre-filtered */
    const filters = [];
    const spec = (await meta()).entities[entity];
    const names = new Set(((spec && spec.fields) || []).map(f => f.name));
    new URLSearchParams(location.hash.split("?")[1] || "").forEach((v, k) => {
      if (k !== "q" && k !== "sort" && k !== "direction" && names.has(k)) {
        filters.push({ field: k, op: "eq", value: v });
      }
    });
    await A.views.list(root.querySelector("[data-mil-list-host]"),
                       { entity, filters, q: params.q });
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: t(DOMAIN_LABEL[DOMAIN_OF[entity]]), href: "#/military/" + DOMAIN_OF[entity] },
      { label: entLabel(entity) }]);
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
    /* vocabulary-linked values display as their bilingual label */
    if (f.type === "select" && f.domain) {
      const o = (A.domainOptions(f.domain) || [])
        .find(x => x.code === v || String(x.id) === String(v));
      if (o) return esc(A.state.lang === "ar"
        ? (o.label_ar || o.label_en) : (o.label_en || o.label_ar));
    }
    return esc(String(v));
  }

  /* ====================================================== view: dossier */
  const FICTIONAL_SUFFIX = " (fictional note)";
  const RELATED = {
    unit: [["deployments", "unit_id"], ["missions", "unit_id"],
           ["holdings", "unit_id"], ["trainings", "unit_id"],
           ["assignments", "unit_id"], ["units", "parent_id"]],
    region: [["regions", "parent_id"], ["units", "region_id"]],
    division: [["units", "division_id"]],
    classification: [["units", "classification_id"]],
    commander: [["assignments", "commander_id"], ["traits", "commander_id"]],
    deployment: [["missions", "deployment_id"]],
    armament: [["holdings", "armament_id"]],
    training: [], holding: [], assignment: [], note: []
  };

  /**
   * The unit dossier — the workspace's flagship profile.  Emblem, identity,
   * structure, operations, logistics, training, the command roster (past and
   * current) and notes, tabbed like the registry's person profile: one screen
   * that answers "what is this unit?" without a single detour.
   */
  const REL_LIMIT = 10;
  let DOSSIER_TAB = null;      /* a quick-add returns to the tab it fed */
  let DOSSIER_FLASH = null;    /* the record that was just added */
  const HOST_PRESET = {
    unit: "unit_id", region: "region_id", division: "division_id",
    classification: "classification_id", commander: "commander_id",
    armament: "armament_id", deployment: "deployment_id"
  };
  const NEXT_ECHELON = { Brigade: "Battalion", Battalion: "Company",
    Company: "Platoon", Platoon: "Squadron" };
  const LEVEL_COLOR = { Exceptional: "green", Outstanding: "blue",
    Proficient: "slate", Developing: "amber" };
  const LEVEL_RANK = { Exceptional: 4, Outstanding: 3, Proficient: 2, Developing: 1 };
  const LEVEL_HEX = { green: "#2f8f5b", blue: "#3b7dd8",
    slate: "#7a8b99", amber: "#c98a1b" };
  const vocabLabel = (domain, code) => {
    const o = (A.domainOptions(domain) || [])
      .find(x => x.code === code || String(x.id) === String(code));
    if (!o) return code || "";
    return A.state.lang === "ar"
      ? (o.label_ar || o.label_en || code) : (o.label_en || o.label_ar || code);
  };
  const ADD_LABEL = {
    unit: "mil.doss.addSubunit", deployment: "mil.doss.addDeployment",
    mission: "mil.doss.addMission", holding: "mil.doss.addHolding",
    training: "mil.doss.addTraining", assignment: "mil.doss.appointCommander"
  };
  const TAB_FOR = { unit: "structure", region: "structure", division: "structure",
    classification: "structure", deployment: "operations", mission: "operations",
    holding: "logistics", training: "training", assignment: "command",
    commander: "command", trait: "rel:traits", note: "notes" };
  let DOSS_MAP = null;   /* the dossier map (MapLibre instance + its pins) */
  function disposeDossierMap() {
    if (!DOSS_MAP) return;
    (DOSS_MAP.pins || []).forEach(pin => { try { pin.remove(); } catch (e) { /* */ } });
    if (DOSS_MAP.attrib) { try { DOSS_MAP.attrib.remove(); } catch (e) { /* */ } }
    try { DOSS_MAP.map.remove(); } catch (e) { /* already gone */ }
    DOSS_MAP = null;
  }

  function relHead(label, d, id, addKey) {
    return `<div class="card-head"><h2>${esc(label)}</h2>
      <span class="badge slate">${fmtNum(d.total || 0)}</span>
      ${addKey ? `<button class="btn sm primary" data-add="${esc(addKey)}">${icon("plus")} ${esc(t(ADD_LABEL[addKey] || "rec.new"))}</button>` : ""}
      ${(d.total || 0) > (d.rows || []).length ? `
        <button class="btn sm" data-relmore="${esc(d.slug)}"
          data-relfk="${esc(d.fk)}" data-relid="${id}">${esc(t("mil.dossier.showMore"))}</button>
        <a class="btn sm" style="margin-left:6px"
          href="#/military/${esc(d.slug)}?${esc(d.fk)}=${id}">${esc(t("mil.dossier.seeAll"))}</a>` : ""}</div>`;
  }

  function relTable(label, d, id, cols, rowFn, addKey) {
    const rows = d.rows || [];
    return `<div class="card">
      ${relHead(label, d, id, addKey)}
      ${rows.length ? `<div class="table-wrap"><table class="data">
        <thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody data-relbody="${esc(d.slug)}">${rows.map(r => rowFn(r)).join("")}</tbody>
      </table></div>` : `<div class="empty">${esc(t("mil.dossier.noRelated"))}</div>`}
    </div>`;
  }

  const viewBtn = (slug, r) => `<td class="nowrap">
    <a class="btn sm" href="#/military/${esc(slug.replace(/s$/, ""))}s/${r.id}/show">${esc(t("common.view"))}</a></td>`;

  A.views.milDossier = async function (root, params) {
    const entity = entityKey(params.entity);
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
    /* related rows name their own links: commanders on assignments,
       armament on holdings */
    for (const e of ["commander", "armament"]) {
      if (!refMap[e]) {
        const rows = await refOptions(e);
        refMap[e] = {};
        rows.forEach(r => { refMap[e][r.id] = r; });
      }
    }
    const refName = (e, rid) => {
      const r = (refMap[e] || {})[rid];
      return esc(r ? refLabelOf(e, r) : (rid ? "#" + rid : "—"));
    };
    const refLink = (e, rid) => {
      if (!rid) return "—";
      if (e === "person") {
        return `<a href="#/entity/person/${esc(rid)}"><b>${esc(t("mil.ind.tab"))} · #${esc(rid)}</b></a>`;
      }
      return `<a href="#/military/${esc(e)}s/${rid}/show"><b>${refName(e, rid)}</b></a>`;
    };

    const relData = await Promise.all((RELATED[entity] || []).map(async ([slug, fk]) => {
      const data = await mreq("GET", "/" + slug + "?limit=" + REL_LIMIT
        + "&sort=id&direction=desc&" + fk + "=" + id);
      return { slug, fk, rows: data.records || [], total: data.total || 0 };
    }));
    const relBy = {};
    relData.forEach(d => { relBy[d.slug] = d; });
    const relOf = (slug) => relBy[slug] || {
      slug, fk: "unit_id", rows: [], total: 0
    };

    /* a note does not collect notes about itself */
    const notes = entity === "note" ? { records: [], total: 0 } : await mreq("GET",
      "/notes?limit=50&sort=id&direction=desc&entity_type=" + entity + "&target_id=" + id);

    /* hero stats — the force rollup answers "how big is this command?" */
    let subtree = null, curDep = null, topArm = [];
    if (entity === "unit") {
      try {
        const fs = await mreq("GET", "/units/" + id + "/force-summary");
        subtree = fs.subtree_personnel;
        curDep = fs.current_deployment || null;
        topArm = fs.armament_top || [];
      } catch (e) { /* the dossier still renders without the rollup */ }
    }

    const labelOf = (slug) => entLabel(slug.replace(/s$/, ""));
    const statusOf = (r) => r.status ? chip(r.status) : (r.start_date ? esc(r.start_date) : "—");

    /* -- hero facts: the handful of values that identify the unit -------- */
    let facts = "";
    const fl = (n) => {
      const f = spec.fields.find(x => x.name === n);
      return f ? fieldLabel(f) : n;
    };
    if (entity === "unit") {
      const F = [
        [fl("classification_id"), refLink("classification", rec.classification_id)],
        [fl("parent_id"), refLink("unit", rec.parent_id)],
        [fl("division_id"), refLink("division", rec.division_id)],
        [fl("region_id"), refLink("region", rec.region_id)],
        [fl("commander_id"), refLink("commander", rec.commander_id)],
        [fl("role"), rec.role ? esc(rec.role) : ""],
        [fl("headquarters"), rec.headquarters ? esc(rec.headquarters) : ""],
        [fl("formation_date"), rec.formation_date ? esc(rec.formation_date) : ""]
      ];
      facts = F.filter(([k, v]) => k && v && v !== "—")
        .map(([k, v]) => `<span class="hfact">${esc(k)}: <b>${v}</b></span>`).join("");
    } else if (entity === "commander") {
      const CF = [
        [fl("rank_title"), rec.rank_title ? chip(rec.rank_title) : ""],
        [fl("branch"), rec.branch ? chip(rec.branch) : ""],
        [fl("status"), rec.status ? chip(rec.status) : ""],
        [fl("commission_date"), rec.commission_date ? esc(rec.commission_date) : ""],
        [fl("person_id"), rec.person_id ? refLink("person", rec.person_id) : ""]
      ];
      facts = CF.filter(([k, v]) => k && v && v !== "—")
        .map(([k, v]) => `<span class="hfact">${esc(k)}: <b>${v}</b></span>`).join("");
    } else {
      facts = spec.fields
        .filter(f => f.type !== "textarea" && rec[f.name] != null && rec[f.name] !== "")
        .slice(0, 5)
        .map(f => `<span class="hfact">${esc(fieldLabel(f))}: <b>${cell(rec, f, refMap)}</b></span>`)
        .join("");
    }

    const stat = (b, s) => `<div><b>${b}</b><span>${esc(s)}</span></div>`;
    const relCount = (slug) => fmtNum(relOf(slug).total || 0);
    let stats = "";
    if (entity === "unit") {
      stats = stat(fmtNum(rec.direct_personnel || 0), t("mil.force.direct")) +
        (subtree != null ? stat(fmtNum(subtree), t("mil.tree.subtreePersonnel")) : "") +
        stat(relCount("units"), t("mil.force.children")) +
        stat(relCount("deployments"), entLabel("deployment")) +
        stat(relCount("missions"), t("mil.force.missions")) +
        stat(relCount("holdings"), entLabel("holding")) +
        stat(relCount("trainings"), entLabel("training")) +
        stat(relCount("assignments"), t("mil.doss.commanders"));
    } else {
      stats = relData.map(d => stat(fmtNum(d.total || 0), labelOf(d.slug))).join("");
    }

    const portrait = rec.image_url
      ? `<img src="${esc(rec.image_url)}" alt="${esc(rec.image_alt || rec.name || rec.docname || "")}">`
      : esc(A.initials(rec.name || rec.full_name || rec.exercise_name || rec.docname || "?"));
    const canEdit = role() !== "viewer";
    const emblemBtn = (entity === "unit" && canEdit)
      ? `<label class="emblem-btn" title="${esc(t("mil.doss.changeEmblem"))}">${icon("upload")}
          <input type="file" accept="image/*" id="emblemFile" hidden></label>` : "";

    /* quick-add: the full record form, pre-linked to this dossier's context */
    const seedFor = (addKey) => {
      const sh = {};
      const preset = HOST_PRESET[entity];
      const fields = (m.entities[addKey] && m.entities[addKey].fields) || [];
      const has = (k) => fields.some(f => (f.name || f.key) === k);
      if (addKey === "unit" && entity === "unit") {
        sh.parent_id = id;                      /* a sub-unit of THIS unit */
        if (rec.division_id) sh.division_id = rec.division_id;
        if (rec.region_id) sh.region_id = rec.region_id;
        if (rec.classification_id) sh.classification_id = rec.classification_id;
        if (rec.role) sh.role = rec.role;       /* like parent, like child */
        const ne = NEXT_ECHELON[rec.echelon];   /* Brigade → Battalion → … */
        if (ne) sh.echelon = ne;
      } else if (preset && has(preset)) {
        sh[preset] = id;
      }
      if (addKey === "mission" && entity === "unit" && curDep && has("deployment_id")) {
        sh.deployment_id = curDep.id;           /* missions belong to the tour */
      }
      return sh;
    };
    const menuKeys = Object.keys(ADD_LABEL)
      .filter(k => Object.keys(seedFor(k)).length > 0);

    root.innerHTML = milNav("e:" + entity) +
      A.pageHead(rec.docname || "#" + id, entLabel(entity), `
        <a class="btn" href="#/military/${entity}s">${icon("undo")} ${esc(t("common.back"))}</a>
        ${canEdit && menuKeys.length ? `<details class="mil-add-menu">
          <summary class="btn primary">${icon("plus")} ${esc(t("rec.new"))}</summary>
          <div class="mil-add-menu-list">
            ${menuKeys.map(k => `<button class="btn sm" data-add="${esc(k)}">${icon("plus")} ${esc(t(ADD_LABEL[k]))}</button>`).join("")}
            <div class="hint">${esc(t("mil.doss.quickAddHint"))}</div>
          </div></details>` : ""}
        <a class="btn primary" href="#/military/${entity}s/${id}/edit">${icon("edit") || ""} ${esc(t("common.edit"))}</a>
        ${role() === "admin" ? `<button class="btn danger" id="milDelete">${icon("trash")} ${esc(t("common.delete"))}</button>` : ""}`) +
      `<div class="hero">
        <div class="portrait" id="milPortrait">${portrait}${emblemBtn}</div>
        <div>
          <div class="htitle">
            <h1>${esc(rec.name || rec.full_name || rec.exercise_name || rec.docname || "#" + id)}</h1>
            ${rec.docname ? `<span class="badge mono">${esc(rec.docname)}</span>` : ""}
            ${statusOf(rec)}
            ${rec.echelon ? `<span class="badge slate">${esc(String(A.optLabel(rec.echelon)))}</span>` : ""}
          </div>
          <div class="hmeta">
            <span>${esc(entLabel(entity))}</span>
            ${rec.code ? `<span>${esc(rec.code)}</span>` : ""}
            ${rec.modified_at ? `<span>${esc(t("mil.form.modified"))}: ${esc(rec.modified_at)}</span>` : ""}
            ${curDep ? `<span>${esc(t("mil.force.currentDeployment"))}: ${esc(curDep.name || curDep.docname || "")}</span>` : ""}
          </div>
          <div class="hfacts">${facts}</div>
        </div>
        <div class="hero-side"><div class="hstats">${stats}</div></div>
      </div>
      <div class="tabs" id="milDossTabs"></div>
      <div id="tabBody"></div>`;

    /* ---------------------------------------------------------- tabs --- */
    const TABS = [{ key: "overview", label: t("mil.domain.hub") }];
    if (entity === "unit") {
      TABS.push({ key: "structure", label: t("mil.doss.structure"), n: relOf("units").total });
      TABS.push({ key: "operations", label: t("mil.doss.operations"),
        n: (relOf("deployments").total || 0) + (relOf("missions").total || 0) });
      TABS.push({ key: "map", label: t("mil.map.tab") });
      TABS.push({ key: "logistics", label: t("mil.doss.logistics"), n: relOf("holdings").total });
      TABS.push({ key: "training", label: t("mil.domain.training"), n: relOf("trainings").total });
      TABS.push({ key: "command", label: t("mil.domain.command"), n: relOf("assignments").total });
    } else {
      if (entity === "commander") {
        TABS.push({ key: "individual", label: t("mil.ind.tab") });
      }
      (RELATED[entity] || []).forEach(([slug]) => {
        const d = relOf(slug);
        TABS.push({ key: "rel:" + slug, label: labelOf(slug), n: d.total });
      });
    }
    if (entity !== "note") {
      TABS.push({ key: "notes", label: t("mil.dossier.notes"),
        n: notes.total || (notes.records || []).length });
    }
    TABS.push({ key: "history", label: t("rec.history") });

    root.querySelector("#milDossTabs").innerHTML = TABS.map((tb, i) =>
      `<button data-tab="${esc(tb.key)}" class="${i === 0 ? "active" : ""}">${esc(tb.label)}${
        tb.n ? ` <span class="badge slate">${fmtNum(tb.n)}</span>` : ""}</button>`).join("");

    /* ------------------------------------------------ row renderers ---- */
    const childRow = (r) => `<tr data-rid="${r.id}">
      <td class="mono-cell">${esc(r.docname || "#" + r.id)}</td>
      <td><a href="#/military/units/${r.id}/show"><b>${esc(r.name || "—")}</b></a></td>
      <td>${esc(r.echelon ? String(A.optLabel(r.echelon)) : "—")}</td>
      <td>${statusOf(r)}</td>
      <td>${fmtNum(r.direct_personnel || 0)}</td>${viewBtn("units", r)}</tr>`;
    const depRow = (r) => `<tr data-rid="${r.id}">
      <td class="mono-cell">${esc(r.docname || "#" + r.id)}</td>
      <td><a href="#/military/deployments/${r.id}/show"><b>${esc(r.name || "—")}</b></a></td>
      <td>${esc(r.deployment_type || "—")}</td>
      <td class="nowrap">${esc(r.start_date || "—")} → ${esc(r.end_date || "…")}</td>
      <td>${statusOf(r)}</td>
      <td>${esc(r.location || "—")}</td>${viewBtn("deployments", r)}</tr>`;
    const misRow = (r) => `<tr data-rid="${r.id}">
      <td class="mono-cell">${esc(r.docname || "#" + r.id)}</td>
      <td><a href="#/military/missions/${r.id}/show"><b>${esc(r.name || "—")}</b></a></td>
      <td>${esc(r.mission_type || "—")}</td>
      <td class="nowrap">${esc(r.start_date || "—")} → ${esc(r.end_date || "…")}</td>
      <td>${statusOf(r)}</td>
      <td>${esc(r.area || "—")}</td>${viewBtn("missions", r)}</tr>`;
    const holdRow = (r) => `<tr data-rid="${r.id}">
      <td><a href="#/military/armaments/${r.armament_id}/show"><b>${esc(refName("armament", r.armament_id))}</b></a></td>
      <td>${fmtNum(r.quantity || 0)}</td>
      <td>${r.condition ? chip(r.condition) : "—"}</td>
      <td>${esc(r.acquisition_year || "—")}</td>${viewBtn("holdings", r)}</tr>`;
    const trainRow = (r) => `<tr data-rid="${r.id}">
      <td class="mono-cell">${esc(r.docname || "#" + r.id)}</td>
      <td><a href="#/military/trainings/${r.id}/show"><b>${esc(r.exercise_name || "—")}</b></a></td>
      <td>${esc(r.training_type || "—")}</td>
      <td class="nowrap">${esc(r.start_date || "—")} → ${esc(r.end_date || "…")}</td>
      <td>${fmtNum(r.participant_count || 0)}</td>
      <td>${r.assessment ? chip(r.assessment) : "—"}</td>${viewBtn("trainings", r)}</tr>`;
    const asgRow = (r) => `<tr data-rid="${r.id}">
      <td>${refLink("commander", r.commander_id)}</td>
      <td>${esc(r.role || "—")}</td>
      <td class="nowrap">${esc(r.assigned_date || "—")} → ${esc(r.relieved_date || "…")}</td>
      <td>${r.is_current
        ? `<span class="badge green">${esc(t("mil.doss.current"))}</span>`
        : `<span class="badge gray">${esc(t("mil.doss.past"))}</span>`}</td>
      <td class="nowrap">${r.is_current && canEdit
        ? `<button class="btn sm" data-relieve="${r.id}">${icon("undo")} ${esc(t("mil.doss.relieve"))}</button> ` : ""}
        <a class="btn sm" href="#/military/assignments/${r.id}/show">${esc(t("common.view"))}</a></td></tr>`;
    const traitRow = (r) => `<tr data-rid="${r.id}">
      <td><b>${esc(vocabLabel("leadership_quality", r.quality))}</b></td>
      <td>${r.level ? `<span class="badge ${LEVEL_COLOR[r.level] || "slate"}">${esc(vocabLabel("leadership_level", r.level))}</span>` : "—"}</td>
      <td>${esc(r.assessed_by || "—")}</td>
      <td class="nowrap">${esc(r.assessed_at || "—")}</td>
      <td>${esc(A.truncate(r.source || r.evidence_note || "", 64))}</td>
      ${viewBtn("traits", r)}</tr>`;
    const genRow = (slug, r) => `<tr data-rid="${r.id}">
      <td class="mono-cell">${esc(r.docname || "#" + r.id)}</td>
      <td>${esc(r.name || r.full_name || r.exercise_name || r.note_text || "—")}</td>
      <td>${statusOf(r)}</td>${viewBtn(slug, r)}</tr>`;

    const COLS = {
      units: [t("mil.form.docname"), t("mil.dossier.name"), t("mil.doss.colType"),
        t("mil.dossier.status"), t("mil.col.personnel"), t("mil.col.action")],
      deployments: [t("mil.form.docname"), t("mil.dossier.name"), t("mil.doss.colType"),
        t("mil.col.dates"), t("mil.dossier.status"), t("mil.doss.colLocation"),
        t("mil.col.action")],
      missions: [t("mil.form.docname"), t("mil.dossier.name"), t("mil.doss.colType"),
        t("mil.col.dates"), t("mil.dossier.status"), t("mil.doss.colLocation"),
        t("mil.col.action")],
      holdings: [t("mil.dossier.name"), t("mil.col.quantity"), t("mil.col.condition"),
        t("mil.col.acquired"), t("mil.col.action")],
      trainings: [t("mil.form.docname"), t("mil.col.exercise"), t("mil.doss.colType"),
        t("mil.col.dates"), t("mil.col.participants"), t("mil.col.readiness"),
        t("mil.col.action")],
      assignments: [t("mil.doss.colCommander"), t("mil.doss.colRole"), t("mil.col.dates"),
        t("mil.dossier.status"), t("mil.col.action")],
      traits: [fl("quality"), fl("level"), fl("assessed_by"), fl("assessed_at"),
        fl("evidence_note"), t("mil.col.action")],
      generic: [t("mil.form.docname"), t("mil.dossier.name"), t("mil.dossier.status"),
        t("mil.col.action")]
    };
    const ROWS = {
      units: childRow, deployments: depRow, missions: misRow,
      holdings: holdRow, trainings: trainRow, assignments: asgRow,
      traits: traitRow
    };
    const relCard = (slug, label, addKey) => relTable(label || labelOf(slug), relOf(slug), id,
      COLS[slug] || COLS.generic,
      ROWS[slug] ? ROWS[slug] : (r) => genRow(slug, r), addKey);

    /* ------------------------------------------------------------ tabs body */
    const body = root.querySelector("#tabBody");

    /* -- leadership profile: what sets this leader apart, with its basis -- */
    /* The fan reads the recorded assessments (never invents any): each spoke
       is one assessed quality, its length the recorded level. The command
       record below is database counts fetched from /leader-record. */
    function leaderFan(rows) {
      const shown = rows.slice(0, 8);
      if (!shown.length) return "";
      const W = 560, H = 320, cx = W / 2, cy = H / 2 + 4;
      const spokes = shown.map((r, i) => {
        const ang = (i / shown.length) * Math.PI * 2 - Math.PI / 2;
        const lvl = LEVEL_RANK[r.level] || 1;
        const len = 38 + lvl * 24;
        const cos = Math.cos(ang), sin = Math.sin(ang);
        return {
          r, lvl, ang,
          x: cx + len * cos, y: cy + len * sin,
          lx: cx + (len + 16) * cos, ly: cy + (len + 16) * sin,
          color: LEVEL_HEX[LEVEL_COLOR[r.level] || "slate"] || LEVEL_HEX.slate,
          anchor: cos < -0.15 ? "end" : (cos > 0.15 ? "start" : "middle")
        };
      });
      return `<svg class="mil-lead-fan-svg" viewBox="0 0 ${W} ${H}" role="img">
        ${[1, 2, 3, 4].map(lvl => `<circle cx="${cx}" cy="${cy}" r="${38 + lvl * 24}"
          fill="none" stroke="rgba(125,139,150,.18)" stroke-dasharray="3 5"/>`).join("")}
        ${spokes.map(sp => `
          <line x1="${cx}" y1="${cy}" x2="${sp.x}" y2="${sp.y}"
            stroke="${sp.color}" stroke-width="${1.5 + sp.lvl * 0.6}" stroke-linecap="round"/>
          <circle cx="${sp.x}" cy="${sp.y}" r="${3 + sp.lvl}" fill="${sp.color}"/>
          <text class="mil-lead-label" x="${sp.lx}" y="${sp.ly + 4}"
            text-anchor="${sp.anchor}">${esc(vocabLabel("leadership_quality", sp.r.quality))}</text>`).join("")}
        <circle cx="${cx}" cy="${cy}" r="26" fill="rgba(125,139,150,.14)"
          stroke="rgba(125,139,150,.35)"/>
        <text x="${cx}" y="${cy + 4}" text-anchor="middle"
          style="font-weight:700">${esc(A.initials(rec.full_name || rec.docname || ""))}</text>
      </svg>`;
    }

    function leaderSection() {
      const d = relOf("traits");
      const rows = d.rows || [];
      return `<div class="card mil-lead-card">
        <div class="card-head"><h2>${esc(t("mil.lead.title"))}</h2>
          <span class="badge slate">${fmtNum(d.total || 0)}</span>
          ${canEdit ? `<button class="btn sm primary" data-add="trait">${icon("plus")} ${esc(t("mil.lead.addAssessment"))}</button>` : ""}
          ${(d.total || 0) > rows.length ? `
            <a class="btn sm" href="#/military/traits?commander_id=${id}">${esc(t("mil.dossier.seeAll"))}</a>` : ""}</div>
        ${rows.length ? `
          <div class="mil-lead-fan">${leaderFan(rows)}</div>
          <div class="mil-lead-chips">${rows.slice(0, 6).map(r => `
            <span class="badge ${LEVEL_COLOR[r.level] || "slate"}">${esc(vocabLabel("leadership_quality", r.quality))}${r.level ? " · " + esc(vocabLabel("leadership_level", r.level)) : ""}</span>`).join("")}
          </div>` : `<div class="empty">${esc(t("mil.lead.noAssessments"))}</div>`}
        <h3 class="mil-lead-sub">${esc(t("mil.lead.recordTitle"))}</h3>
        <div class="mil-lead-record" id="milLeadRecord">
          <div class="small muted">${esc(t("common.loading"))}</div>
        </div>
        <div class="small muted mil-lead-basis">${esc(t("mil.lead.basisNote"))}</div>
      </div>`;
    }

    async function mountLeaderRecord(body) {
      const host = body.querySelector("#milLeadRecord");
      if (!host) return;
      try {
        const d = await mreq("GET", `/commanders/${id}/leader-record`);
        host.innerHTML = `<div class="statgrid">
          <div class="statcard"><b>${fmtNum(d.units_commanded)}</b><span>${esc(t("mil.lead.unitsCommanded"))}</span></div>
          <div class="statcard"><b>${esc(d.max_echelon || "—")}</b><span>${esc(t("mil.lead.maxEchelon"))}</span></div>
          <div class="statcard"><b>${fmtNum(d.personnel_under_command)}</b><span>${esc(t("mil.lead.personnel"))}</span></div>
          <div class="statcard"><b>${fmtNum(d.deployments_covered)}</b><span>${esc(t("mil.lead.deployments"))}</span></div>
          <div class="statcard"><b>${fmtNum(d.appointments)}</b><span>${esc(t("mil.lead.appointments"))}</span></div>
          <div class="statcard"><b>${d.years_of_service != null ? fmtNum(d.years_of_service) : "—"}</b><span>${esc(t("mil.lead.service"))}</span></div>
        </div>`;
      } catch (err) {
        host.innerHTML = `<div class="notice err small">${esc(err.message)}</div>`;
      }
    }

    function paintTab(key) {
      disposeDossierMap();
      if (key === "overview") {
        body.innerHTML = `<div class="card">
          <div class="card-head"><h2>${esc(t("mil.dossier.fields"))}</h2></div>
          <dl class="dossier-grid">
            ${spec.fields.map(f => `
              <div class="dfield"><dt>${esc(fieldLabel(f))}</dt>
                <dd>${cell(rec, f, refMap)}</dd></div>`).join("")}
          </dl>
        </div>
        ${entity === "commander" ? leaderSection() : ""}
        ${entity === "unit" && topArm.length ? `<div class="card">
          <div class="card-head"><h2>${esc(t("mil.force.armament"))}</h2></div>
          <div class="table-wrap"><table class="data">
            <thead><tr><th>${esc(t("mil.dossier.name"))}</th><th>${esc(t("mil.doss.colType"))}</th>
              <th>${esc(t("mil.col.quantity"))}</th><th>${esc(t("mil.col.condition"))}</th></tr></thead>
            <tbody>${topArm.map(a => `<tr><td>${esc(a.name || "—")}</td>
              <td>${esc(a.category || "—")}</td><td>${fmtNum(a.quantity || 0)}</td>
              <td>${a.condition ? chip(a.condition) : "—"}</td></tr>`).join("")}</tbody>
          </table></div>
        </div>` : ""}`;
        if (entity === "commander") mountLeaderRecord(body);
        return;
      }
      if (key === "structure") {
        const d = relOf("units");
        body.innerHTML = `<div class="statgrid" style="margin-bottom:12px">
          <div class="statcard"><b>${fmtNum(d.total || 0)}</b><span>${esc(t("mil.force.children"))}</span></div>
          <div class="statcard"><b>${fmtNum(subtree != null ? subtree : (rec.direct_personnel || 0))}</b>
            <span>${esc(t("mil.tree.subtreePersonnel"))}</span></div>
          <div class="statcard"><b>${refName("division", rec.division_id)}</b><span>${esc(entLabel("division"))}</span></div>
          <div class="statcard"><b>${refName("region", rec.region_id)}</b><span>${esc(entLabel("region"))}</span></div>
          <div class="statcard"><b>${refName("classification", rec.classification_id)}</b>
            <span>${esc(t("mil.col.classification"))}</span></div>
          <div class="statcard"><b>${rec.parent_id ? refName("unit", rec.parent_id) : "—"}</b>
            <span>${esc(t("mil.force.siblings"))} · ${fmtNum((relOf("units").total || 0))}</span></div>
        </div>
        ${relCard("units", t("mil.force.children"), "unit")}`;
        return;
      }
      if (key === "operations") {
        body.innerHTML =
          (curDep ? `<div class="card"><div class="card-head"><h2>${esc(t("mil.force.currentDeployment"))}</h2></div>
            <div style="padding:4px 2px"><a href="#/military/deployments/${curDep.id}/show"><b>${esc(curDep.name || curDep.docname || "#" + curDep.id)}</b></a>
            ${curDep.status ? " · " + chip(curDep.status) : ""}
            ${curDep.location ? ` <span class="hfact">${esc(t("mil.doss.colLocation"))}: <b>${esc(curDep.location)}</b></span>` : ""}</div>
          </div>` : "") +
          relCard("deployments", entLabel("deployment"), "deployment") +
          relCard("missions", t("mil.force.missions"), "mission");
        return;
      }
      if (key === "logistics") {
        const d = relOf("holdings");
        const qty = (d.rows || []).reduce((s, r) => s + (r.quantity || 0), 0);
        body.innerHTML = `<div class="statgrid" style="margin-bottom:12px">
          <div class="statcard"><b>${fmtNum(d.total || 0)}</b><span>${esc(t("mil.doss.weaponry"))}</span></div>
          <div class="statcard"><b>${fmtNum(qty)}</b><span>${esc(t("mil.holdings.total"))}</span></div>
        </div>` + relCard("holdings", t("mil.doss.weaponry"), "holding");
        return;
      }
      if (key === "training") {
        body.innerHTML = relCard("trainings", t("mil.domain.training"), "training");
        return;
      }
      if (key === "command") {
        const d = relOf("assignments");
        const rows = (d.rows || []).slice().sort((a, b) =>
          (b.is_current ? 1 : 0) - (a.is_current ? 1 : 0)
          || String(b.assigned_date || "").localeCompare(String(a.assigned_date || "")));
        body.innerHTML = `<div class="card">
          <div class="card-head"><h2>${esc(t("mil.doss.commanders"))}</h2>
            <span class="badge slate">${fmtNum(d.total || 0)}</span>
            ${canEdit ? `<button class="btn sm primary" data-add="assignment">${icon("plus")} ${esc(t("mil.doss.appointCommander"))}</button>` : ""}
            ${(d.total || 0) > rows.length ? `
              <button class="btn sm" data-relmore="${esc(d.slug)}"
                data-relfk="${esc(d.fk)}" data-relid="${id}">${esc(t("mil.dossier.showMore"))}</button>
              <a class="btn sm" style="margin-left:6px"
                href="#/military/${esc(d.slug)}?${esc(d.fk)}=${id}">${esc(t("mil.dossier.seeAll"))}</a>` : ""}</div>
          <div style="padding:2px 2px 10px">${esc(t("mil.doss.colCommander"))}:
            ${refLink("commander", rec.commander_id)}</div>
          ${rows.length ? `<div class="table-wrap"><table class="data">
            <thead><tr>${COLS.assignments.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
            <tbody data-relbody="assignments">${rows.map(asgRow).join("")}</tbody>
          </table></div>` : `<div class="empty">${esc(t("mil.dossier.noRelated"))}</div>`}
        </div>`;
        return;
      }
      if (key === "map") {
        body.innerHTML = milMapShell();
        mountDossierMap(body);
        return;
      }
      if (key === "individual") {
        paintIndividualTab(body);
        return;
      }
      if (key === "notes") {
        body.innerHTML = `<div class="card" id="milNotesCard">
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
        const addBtn = body.querySelector("#milNoteAdd");
        if (addBtn) addBtn.onclick = async () => {
          const text = body.querySelector("#milNoteText").value.trim();
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
        return;
      }
      if (key === "history") {
        body.innerHTML = `<div class="card">
          <div class="card-head"><h2>${esc(t("rec.history"))}</h2></div>
          <dl class="dossier-grid">
            <div class="dfield"><dt>${esc(t("mil.form.created"))}</dt>
              <dd>${esc(rec.created_at || "—")} · ${esc(rec.created_by || "—")}</dd></div>
            <div class="dfield"><dt>${esc(t("mil.form.modified"))}</dt>
              <dd>${esc(rec.modified_at || "—")} · ${esc(rec.modified_by || "—")}</dd></div>
            <div class="dfield"><dt>${esc(t("mil.form.docname"))}</dt>
              <dd><span class="mono-cell">${esc(rec.docname || "—")}</span></dd></div>
          </dl>
        </div>`;
        return;
      }
      if (key.startsWith("rel:")) {
        const slug = key.slice(4);
        body.innerHTML = relCard(slug, null, slug.replace(/s$/, ""));
        return;
      }
      body.innerHTML = "";
    }

    /* --------------------------------------------------------- unit map --- */
    /* The map shows the unit's OWN location: its own coordinates and those of
       its deployments. The commander's personal location is deliberately not
       here — service.unit_geo serves unit-owned rows only — and the caption
       and tests keep that distinction visible. */
    function milMapShell() {
      return `<div class="card mil-map-card">
        <div class="card-head"><h2>${esc(t("mil.map.tab"))}</h2>
          ${canEdit ? `<a class="btn sm" href="#/military/units/${id}/edit">${icon("edit")} ${esc(t("common.edit"))}</a>` : ""}</div>
        <div class="mil-map-caption">
          <b>${esc(t("mil.map.ownCaption"))}</b>
          <span class="small muted">${esc(t("mil.map.notCommander"))}</span>
        </div>
        <div class="mil-map-canvas" id="milMapCanvas"></div>
        <div class="mil-map-strip" id="milMapStrip"></div>
      </div>`;
    }

    async function mountDossierMap(body) {
      const canvas = body.querySelector("#milMapCanvas");
      const strip = body.querySelector("#milMapStrip");
      if (!canvas) return;
      let geo = null;
      try {
        geo = await mreq("GET", `/units/${id}/geo`);
      } catch (err) {
        canvas.innerHTML = `<div class="notice err small">${esc(err.message)}</div>`;
        return;
      }
      if (!body.querySelector("#milMapCanvas")) return;   /* tab switched away */
      const u = geo.unit || {};
      const deps = geo.deployments || [];
      const pts = [];
      if (u.lat != null && u.lon != null) {
        pts.push({ lat: Number(u.lat), lon: Number(u.lon), label: u.label || "",
          kind: "unit", title: t("mil.map.ownPin") });
      }
      deps.forEach(d => {
        if (d.lat == null || d.lon == null) return;
        pts.push({ lat: Number(d.lat), lon: Number(d.lon), label: d.label || "",
          kind: "deployment",
          title: t("mil.map.deployments") + ": " + (d.label || "") +
            (d.location ? " · " + d.location : "") });
      });

      /* every line below says whose location it is — the unit's own position
         first, then each deployment; never anyone's personal coordinates */
      const fmt = (v) => v == null ? "—" : Number(v).toFixed(5);
      strip.innerHTML = `
        <div class="mil-map-legend">
          <span class="mil-map-key"><i class="mil-map-dot own"></i>${esc(t("mil.map.ownPin"))}</span>
          <span class="mil-map-key"><i class="mil-map-dot dep"></i>${esc(t("mil.map.deployments"))}</span>
        </div>
        <div class="mil-map-row own">
          <b dir="auto">${esc(u.label || rec.name || rec.docname || "")}</b>
          <span class="mono-cell" dir="ltr">${esc(fmt(u.lat))}, ${esc(fmt(u.lon))}</span>
          ${u.geometry_source ? `<span class="small muted">${esc(t("mil.map.source"))}: ${esc(u.geometry_source)}</span>` : ""}
          ${u.headquarters ? `<span class="small muted">${esc(t("mil.doss.colLocation"))}: ${esc(u.headquarters)}</span>` : ""}
        </div>
        ${deps.map(d => `
          <div class="mil-map-row">
            <a href="#/military/deployments/${d.id}/show"><b dir="auto">${esc(d.label || "#" + d.id)}</b></a>
            <span class="small">${esc(d.start_date || "—")} → ${esc(d.end_date || "…")}</span>
            ${d.location ? `<span class="small muted">${esc(d.location)}</span>` : ""}
            ${d.lat != null && d.lon != null
              ? `<span class="mono-cell small" dir="ltr">${esc(fmt(d.lat))}, ${esc(fmt(d.lon))}</span>`
              : `<span class="small muted">${esc(t("mil.map.noCoords"))}</span>`}
          </div>`).join("")}`;

      if (!pts.length || !window.maplibregl) {
        canvas.classList.add("is-empty");
        canvas.innerHTML = `<div class="empty">
          <b>${esc(t("mil.map.empty"))}</b>
          <div class="small muted" style="margin-top:6px">${esc(t("mil.map.emptyHint"))}</div>
          ${canEdit ? `<a class="btn sm" style="margin-top:10px" href="#/military/units/${id}/edit">${icon("edit")} ${esc(t("mil.map.addLocation"))}</a>` : ""}
        </div>`;
        return;
      }
      const bootStyle = { version: 8, sources: {}, layers: [{ id: "bg", type: "background",
        paint: { "background-color": "#e8eef4" } }] };
      let map;
      try {
        map = new window.maplibregl.Map({
          container: canvas, style: bootStyle,
          center: [pts[0].lon, pts[0].lat], zoom: 8, attributionControl: false
        });
      } catch (e) {
        canvas.innerHTML = `<div class="notice err small">${esc(t("common.error"))}</div>`;
        return;
      }
      DOSS_MAP = { map, pins: [], attrib: null };
      map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.on("load", () => {
        if (pts.length > 1) {
          const b = new window.maplibregl.LngLatBounds();
          pts.forEach(pt => b.extend([pt.lon, pt.lat]));
          try { map.fitBounds(b, { padding: 52, duration: 0 }); } catch (e) { /* */ }
        }
        pts.forEach(pt => {
          if (!A.geopin) return;
          const pin = A.geopin.marker(map, [pt.lon, pt.lat], {
            etype: pt.kind, label: pt.label,
            selected: pt.kind === "unit", size: pt.kind === "unit" ? "lg" : "md",
            showLabel: !!pt.label, title: pt.title
          });
          if (DOSS_MAP) DOSS_MAP.pins.push(pin);
        });
      });
    }

    /* commander ↔ individual: the commander dossier encompasses the linked
       person's identity, life and relationships (person_id is the bridge) */
    async function paintIndividualTab(body) {
      if (!rec.person_id) {
        body.innerHTML = `<div class="card">
          <div class="card-head"><h2>${esc(t("mil.ind.tab"))}</h2></div>
          <div class="empty">
            <b>${esc(t("mil.ind.notLinked"))}</b>
            <div class="small muted" style="margin:6px 0 10px">${esc(t("mil.ind.linkHint"))}</div>
            <div class="btn-row">
              <input id="milIndQuery" class="grow" value="${esc(rec.full_name || "")}"
                placeholder="${esc(t("mil.ind.find"))}">
              <button class="btn primary" id="milIndSearch">${icon("search")} ${esc(t("mil.ind.find"))}</button>
            </div>
            <div id="milIndResults"></div>
          </div>
        </div>`;
        const run = async () => {
          const q = body.querySelector("#milIndQuery").value.trim();
          const host = body.querySelector("#milIndResults");
          host.innerHTML = `<div class="small muted">${esc(t("common.loading"))}</div>`;
          try {
            const res = await api.get(`/api/person?q=${encodeURIComponent(q)}&limit=6`);
            const items = res.items || [];
            host.innerHTML = items.length ? items.map(pr => `
              <div class="mil-ind-cand">
                <span class="badge mono">${esc(pr.code || "#" + pr.id)}</span>
                <b dir="auto">${esc(pr.name_en || pr.name_ar || "")}</b>
                ${pr.name_ar ? `<span class="small muted" dir="auto">${esc(pr.name_ar)}</span>` : ""}
                ${pr.birth_date ? `<span class="small muted">${esc(pr.birth_date)}</span>` : ""}
                ${canEdit ? `<button class="btn sm primary" data-indlink="${pr.id}">${icon("link")} ${esc(t("mil.ind.link"))}</button>` : ""}
                <a class="btn sm" href="#/entity/person/${pr.id}">${esc(t("common.view"))}</a>
              </div>`).join("")
              : `<div class="small muted">${esc(t("mil.dossier.noRelated"))}</div>`;
            host.querySelectorAll("[data-indlink]").forEach(btn => {
              btn.onclick = async () => {
                try {
                  await mreq("PATCH", `/commanders/${id}`,
                    { person_id: Number(btn.dataset.indlink) });
                  toast(t("common.saved"), "ok");
                  A.rerender();
                } catch (err) { toast(err.message, "err"); }
              };
            });
          } catch (err) {
            host.innerHTML = `<div class="notice err small">${esc(err.message)}</div>`;
          }
        };
        body.querySelector("#milIndSearch").onclick = run;
        body.querySelector("#milIndQuery").addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") run();
        });
        return;
      }
      body.innerHTML = `<div class="card"><div class="small muted">${esc(t("common.loading"))}</div></div>`;
      let person;
      try {
        person = await api.get(`/api/person/${rec.person_id}`);
      } catch (err) {
        body.innerHTML = `<div class="card"><div class="notice err small">${esc(err.message)}</div></div>`;
        return;
      }
      const pr = person.record || person;
      const lab = (k) => (pr._labels && pr._labels[k])
        ? (A.state.lang === "ar" ? pr._labels[k].ar : pr._labels[k].en) : "";
      const rref = (k) => (pr._refs && pr._refs[k])
        ? (pr._refs[k].label || pr._refs[k].name_en || "") : "";
      const rels = (pr.relationships || []).slice(0, 8);
      const poss = (pr.positions || []).slice(0, 6);
      body.innerHTML = `<div class="card">
        <div class="card-head"><h2>${esc(t("mil.ind.linked"))}</h2>
          <a class="btn sm" href="#/entity/person/${pr.id}">${icon("link")} ${esc(t("mil.ind.open"))}</a></div>
        <div class="mil-ind-hero">
          ${pr.image_url
            ? `<img class="mil-ind-portrait" src="${esc(pr.image_url)}" alt="${esc(pr.image_alt || "")}">`
            : `<span class="mil-ind-portrait">${esc(A.initials(pr.name_en || pr.name_ar || ""))}</span>`}
          <div>
            <h3 dir="auto">${esc(pr.name_en || pr.name_ar || "")}</h3>
            ${pr.name_ar ? `<div class="muted" dir="auto">${esc(pr.name_ar)}</div>` : ""}
            ${pr.name_original ? `<div class="small muted" dir="auto">${esc(pr.name_original)}</div>` : ""}
            <div class="flex wrap" style="gap:5px;margin-top:6px">
              <span class="badge mono">${esc(pr.code || "#" + pr.id)}</span>
              ${lab("classification_id") ? `<span class="badge slate">${esc(lab("classification_id"))}</span>` : ""}
              ${lab("nationality_id") ? `<span class="badge slate">${esc(lab("nationality_id"))}</span>` : ""}
            </div>
          </div>
        </div>
        <dl class="dossier-grid">
          <div class="dfield"><dt>${esc(t("mil.ind.birth"))}</dt>
            <dd>${esc(pr.birth_date || "—")}${pr.birthplace_text ? " · " + esc(pr.birthplace_text) : (rref("birthplace_id") ? " · " + esc(rref("birthplace_id")) : "")}</dd></div>
          <div class="dfield"><dt>${esc(t("mil.ind.death"))}</dt><dd>${esc(pr.death_date || "—")}</dd></div>
          <div class="dfield"><dt>${esc(t("mil.ind.nationality"))}</dt>
            <dd>${esc(lab("nationality_id") || rref("nationality_id") || "—")}</dd></div>
          <div class="dfield"><dt>${esc(t("mil.ind.position"))}</dt><dd>${esc(pr.current_position || "—")}</dd></div>
        </dl>
        ${poss.length ? `<div class="mil-ind-sec"><h4>${esc(t("mil.ind.positions"))}</h4>
          ${poss.map(po => `<div class="mil-ind-rel"><b dir="auto">${esc(po.title_en || po.title_ar || "")}</b>
            <span class="small muted" dir="auto">${esc(po.institution_en || po.institution_ar || "")}</span>
            <span class="small">${esc(po.start_date || "—")} → ${esc(po.end_date || "…")}</span></div>`).join("")}
        </div>` : ""}
        ${rels.length ? `<div class="mil-ind-sec"><h4>${esc(t("mil.ind.relationships"))}</h4>
          ${rels.map(rl => `<div class="mil-ind-rel">
            <a href="#/entity/${esc(rl.other_type || "person")}/${rl.other_id}"><b dir="auto">${esc(rl.other_name || "")}</b></a>
            <span class="small muted" dir="auto">${esc(A.state.lang === "ar" ? (rl.type_ar || rl.type_en || "") : (rl.type_en || ""))}</span>
            <span class="small">${esc(rl.start_date || "—")}${rl.end_date ? " → " + esc(rl.end_date) : ""}</span></div>`).join("")}
        </div>` : ""}
      </div>`;
    }

    bindChrome(root);
    root.querySelectorAll("#milDossTabs [data-tab]").forEach(btn => {
      btn.onclick = () => {
        root.querySelectorAll("#milDossTabs [data-tab]")
          .forEach(b => b.classList.toggle("active", b === btn));
        paintTab(btn.dataset.tab);
      };
    });
    const startTab = (DOSSIER_TAB && TABS.some(tb => tb.key === DOSSIER_TAB))
      ? DOSSIER_TAB : TABS[0].key;
    DOSSIER_TAB = null;
    root.querySelectorAll("#milDossTabs [data-tab]")
      .forEach(b => b.classList.toggle("active", b.dataset.tab === startTab));
    paintTab(startTab);
    if (DOSSIER_FLASH) {
      const el = body.querySelector(`[data-rid="${DOSSIER_FLASH.id}"]`);
      if (el) el.classList.add("row-flash");
      DOSSIER_FLASH = null;
    }

    /* emblem upload — the same /api/media + record write the edit form uses */
    const emblemFile = root.querySelector("#emblemFile");
    if (emblemFile) emblemFile.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        const res = await api.upload("/api/media", fd);
        await api.raw("PUT", `/api/${entity}/${id}`, {
          image_url: res.url,
          image_alt: rec.image_alt || file.name.replace(/\.[^.]+$/, "")
        }, { headers: { "X-Military-Role": role() } });
        toast(t("common.saved"), "ok");
        A.rerender();
      } catch (err) { toast(err.message, "err"); }
    };

    /* delete lives on the record view, as on the registry record page */
    const delBtn = root.querySelector("#milDelete");
    if (delBtn) delBtn.onclick = async () => {
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
    /* show more — append the next page of a related table (any tab) */
    body.addEventListener("click", async (ev) => {
      const btn = ev.target.closest("[data-relmore]");
      if (!btn) return;
      const slug = btn.dataset.relmore;
      const fk = btn.dataset.relfk;
      const tbody = body.querySelector(`tbody[data-relbody="${slug}"]`);
      if (!tbody) return;
      const loaded = tbody.querySelectorAll("tr").length;
      btn.disabled = true;
      const data = await mreq("GET", "/" + slug + "?limit=" + REL_LIMIT
        + "&offset=" + loaded + "&sort=id&direction=desc&" + fk + "=" + btn.dataset.relid);
      const rowFn = ROWS[slug] ? ROWS[slug] : (r) => genRow(slug, r);
      tbody.insertAdjacentHTML("beforeend",
        (data.records || []).map(r => rowFn(r)).join(""));
      btn.disabled = false;
      if (tbody.querySelectorAll("tr").length >= (data.total || 0)) btn.remove();
    });

    /* quick-add + quick actions — every panel feeds the same context */
    root.addEventListener("click", async (ev) => {
      const add = ev.target.closest("[data-add]");
      if (add) {
        const dd = add.closest("details");
        if (dd) dd.open = false;
        const key = add.dataset.add;
        if (!key) return;
        try {
          await A.forms.open(key, null, { seed: seedFor(key) });
        } catch (err) { toast(err.message, "err"); }
        return;
      }
      const rel = ev.target.closest("[data-relieve]");
      if (rel) {
        const ok = await A.confirmDialog({
          title: t("mil.doss.relieve"), message: t("mil.doss.relieveConfirm"),
          confirmLabel: t("common.confirm")
        });
        if (!ok) return;
        try {
          await mreq("PATCH", "/assignments/" + rel.dataset.relieve, {
            is_current: false,
            relieved_date: new Date().toISOString().slice(0, 10)
          });
          toast(t("common.saved"), "ok");
          A.rerender();
        } catch (err) { toast(err.message, "err"); }
      }
    });

    /* a saved quick-add lands on the tab it fed and announces itself */
    function onRecordSaved(ev) {
      const d = ev.detail || {};
      if (!d.record) return;
      d.handled = true;
      DOSSIER_TAB = TAB_FOR[d.entity] || null;
      DOSSIER_FLASH = { id: d.record.id };
      A._keepScroll = true;
      A.rerender();
    }
    document.addEventListener("siraj:record-saved", onRecordSaved);
    A.views.milDossier.__dispose = () => {
      document.removeEventListener("siraj:record-saved", onRecordSaved);
      disposeDossierMap();
    };
  };

  /* ========================================================= view: tree */
  /* ============================================ shared: hierarchy tree --- */
  /**
   * ONE hierarchy explorer for parent/child entities (military units, command
   * regions).  The list view's "Tree" mode and the dedicated tree screens
   * share it — no second tree engine can grow.  Every visible string rides the
   * locale system: switch the language and the whole tree follows.
   */
  /**
   * ONE hierarchy explorer for parent/child entities (military units, command
   * regions).  The list view's "Tree" mode and the dedicated tree screens
   * share it — no second tree engine can grow.  The primary filters live here
   * as default "All" options: every select-backed field becomes a control, the
   * text search refines further, and the tree keeps a match in its context by
   * revealing ancestors and the subtree below.  Every visible string rides the
   * locale system: switch the language and the whole tree follows.
   */
  A.entityTree = function (host, opts) {
    const entity = (opts && opts.entity) === "region" ? "region" : "unit";
    const kind = entity === "region" ? "regions" : "units";
    const nodes = (opts && opts.tree) || [];

    /* every node with its ancestor path — the filter reveals context through it */
    const flat = [];
    (function walk(ns, parents) {
      (ns || []).forEach(n => {
        flat.push({ n: n, parents: parents });
        if (n.children && n.children.length) walk(n.children, parents.concat([n]));
      });
    })(nodes, []);

    /* the default filter set: select-backed fields as "All" dropdowns, then
       the text search.  Options come from the field metadata when the field is
       a vocabulary; a free-choice field with no declared options offers the
       values that actually occur (a field with a single value is no filter). */
    let filters = [];
    const state = { q: "", sel: {} };

    const optionVals = f => {
      const declared = (f.options || f.values || []).filter(Boolean);
      if (declared.length >= 2) return declared;
      const key = f.name || f.key;
      const seen = {};
      flat.forEach(e => {
        const v = e.n[key];
        if (v != null && v !== "") seen[String(v)] = true;
      });
      const found = Object.keys(seen).sort();
      return found.length >= 2 ? found : [];
    };

    const nodeHtml = (k, depth, openAll) => {
      const n = k.n;
      const hasKids = k.kids.length > 0;
      const extra = kind === "units"
        ? ` <span class="small muted">\u03a3 ${fmtNum(n.subtree_personnel != null ? n.subtree_personnel : 0)} · ${esc(t("mil.tree.subtreePersonnel"))}</span>`
        : "";
      return `<li><details${hasKids && (openAll || depth < 1) ? " open" : ""}>
        <summary><div class="mil-node">
          <span class="mil-toggle">${hasKids ? "\u25be" : "\u00b7"}</span>
          <a href="#/entity/${entity}/${n.id}/edit"><b>${esc(n.name)}</b></a>
          <span class="mono-cell small">${esc(n.docname)}</span>
          ${kind === "units" ? chip(n.status) : badge(n.region_type ? A.optLabel(n.region_type, "region_type") : "\u2014", "slate")}${extra}
        </div></summary>
        ${hasKids ? `<ul>${k.kids.map(c => nodeHtml(c, depth + 1, openAll)).join("")}</ul>` : ""}
      </details></li>`;
    };

    const selfMatch = n => {
      const q = state.q;
      if (q) {
        const text = [n.name, n.docname, n.code, n.role, n.headquarters, n.description]
          .filter(Boolean).join(" ").toLowerCase();
        if (!text.includes(q)) return false;
      }
      return filters.every(f => {
        const v = state.sel[f.key];
        return !v || String(n[f.key] == null ? "" : n[f.key]) === v;
      });
    };

    const subtreeHas = n => selfMatch(n) ||
      (n.children || []).some(c => subtreeHas(c));

    const draw = () => {
      const any = state.q || filters.some(f => state.sel[f.key]);
      let shown = 0;
      const build = (n, matchedAbove) => {
        const me = selfMatch(n);
        if (!(me || matchedAbove || subtreeHas(n))) return null;
        shown += 1;
        const kids = (n.children || [])
          .map(c => build(c, matchedAbove || me)).filter(Boolean);
        return { n: n, kids: kids };
      };
      const kept = nodes.map(n => build(n, false)).filter(Boolean);
      const box = host.querySelector(".mil-tree");
      if (!box) return;
      box.innerHTML = kept.length
        ? `<ul>${kept.map(k => nodeHtml(k, 0, any)).join("")}</ul>`
        : `<div class="empty">${esc(t("list.noMatch"))}</div>`;
      const count = host.querySelector("[data-tree-count]");
      if (count) {
        count.textContent = t("mil.tree.showing",
          { n: fmtNum(shown), m: fmtNum(flat.length) });
      }
    };

    host.innerHTML = `
      <div class="mil-tree-bar">
        <div class="search-box">${icon("search")}
          <input data-tree-filter type="search" placeholder="${esc(t("mil.tree.filter"))}"></div>
        <span data-tree-sels></span>
        <span class="small muted" data-tree-count></span>
      </div>
      <div class="mil-tree"></div>`;
    hydrateIcons(host);

    const search = host.querySelector("[data-tree-filter]");
    search.oninput = () => { state.q = search.value.trim().toLowerCase(); draw(); };

    /* metadata adds the primary-filter selects beside the search */
    (async () => {
      try {
        const meta = opts && opts.meta ? opts.meta : await api.get("/api/military/meta");
        const ent = (meta.entities || {})[entity] || {};
        filters = (ent.fields || [])
          .filter(f => (f.type === "choice" || f.type === "select"))
          .map(f => ({
            key: f.name || f.key,
            label: A.state.lang === "ar"
              ? (f.label_ar || f.label_en || f.name)
              : (f.label_en || f.label_ar || f.name),
            options: optionVals(f),
          }))
          .filter(f => f.options.length >= 2);
        const sels = host.querySelector("[data-tree-sels]");
        if (sels) {
          sels.innerHTML = filters.map(f => `
            <label class="field-ctl"><span class="cap">${esc(f.label)}</span>
              <select class="select-ctl sm" data-tree-sel="${esc(f.key)}">
                <option value="">${esc(t("mil.tree.all"))}</option>
                ${f.options.map(o => `<option value="${esc(o)}">${esc(A.optLabel(o, f.key))}</option>`).join("")}
              </select>
            </label>`).join("");
          sels.querySelectorAll("[data-tree-sel]").forEach(sel => {
            sel.onchange = () => {
              state.sel[sel.getAttribute("data-tree-sel")] = sel.value;
              sel.classList.toggle("is-set", !!sel.value);
              draw();
            };
          });
        }
      } catch (e) { /* the search bar works on its own */ }
      draw();
    })();
  };

  A.views.milTree = async function (root, params) {
    const kind = params.kind === "regions" ? "regions" : "units";
    const entity = kind === "units" ? "unit" : "region";
    await meta();
    A.crumbs([{ label: t("nav.military"), href: "#/military" },
      { label: kind === "units" ? t("mil.nav.unitsTree") : t("mil.nav.regionsTree") }]);
    const data = await mreq("GET", "/" + kind + "/tree");

    root.innerHTML = milNav("tree:" + kind) +
      A.pageHead(kind === "units" ? t("mil.nav.unitsTree") : t("mil.nav.regionsTree"),
        t("mil.tree.subtitle"), `
        <a class="btn primary" href="#/military/${entity}s/new">${icon("plus")} ${esc(t("common.new"))}</a>`) +
      `<div class="card"><div data-tree-host></div></div>`;
    bindChrome(root);
    A.entityTree(root.querySelector("[data-tree-host]"),
      { entity, tree: data.tree || [] });
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
            </tr>`)}`).join("")}
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
