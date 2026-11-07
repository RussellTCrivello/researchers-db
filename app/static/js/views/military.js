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
  function milNav(active) {
    const item = (href, label, key) =>
      `<a class="mil-nav-item${active === key ? " on" : ""}" href="${href}">${esc(label)}</a>`;
    return `<div class="mil-nav">
      <div class="mil-nav-group">${esc(t("mil.tab.command"))}</div>
      ${item("#/military", t("mil.nav.workspace"), "workspace")}
      ${item("#/military/units/tree", t("mil.nav.unitsTree"), "units")}
      ${item("#/military/regions/tree", t("mil.nav.regionsTree"), "regions")}
      <div class="mil-nav-group">${esc(t("mil.tab.records"))}</div>
      ${ENTITIES.map(k => item("#/military/" + k + "s", entLabel(k), "e:" + k)).join("")}
      <div class="mil-nav-group">${esc(t("mil.tab.admin"))}</div>
      ${item("#/military/naming", t("mil.nav.naming"), "naming")}
      ${item("#/military/audit", t("mil.nav.audit"), "audit")}
      <span class="flex"></span>
      <select class="ghost-select" id="milRole" title="${esc(t("mil.role.label"))}">
        ${["admin", "staff", "viewer"].map(r =>
          `<option value="${r}"${r === role() ? " selected" : ""}>${esc(t("mil.role." + r))}</option>`).join("")}
      </select>
    </div>`;
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
    const data = await mreq("GET", "/" + entity + "s?limit=500");
    return data.records || [];
  }
  function refLabelOf(entity, rec) {
    if (!rec) return "";
    return `${rec.docname || "#" + rec.id} · ${rec.name || rec.full_name || rec.exercise_name || ""}`;
  }

  /* ====================================================== view: workspace */
  A.views.military = async function (root) {
    A.crumbs([{ label: t("nav.military") }, { label: t("mil.title") }]);
    const [m, d] = await Promise.all([meta(), mreq("GET", "/summary")]);
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
      <div class="grid c2">
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.upcomingDeployments"))}</h3>
          <a class="btn sm" href="#/military/deployments">${esc(t("common.view"))}</a></div>
          ${table([t("mil.col.name"), t("mil.col.unit"), t("mil.col.start"), t("common.status")],
            lists.upcoming_deployments, r => `
            <tr><td><a href="#/military/deployments/${r.id}">${esc(r.name)}</a></td>
              <td>${esc(r.unit_name)}</td><td class="nowrap mono-cell">${esc(r.start_date)}</td>
              <td>${chip(r.status)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.upcomingTrainings"))}</h3>
          <a class="btn sm" href="#/military/trainings">${esc(t("common.view"))}</a></div>
          ${table([t("mil.col.exercise"), t("mil.col.unit"), t("mil.col.dates"), t("mil.col.participants")],
            lists.upcoming_trainings, r => `
            <tr><td><a href="#/military/trainings/${r.id}">${esc(r.exercise_name)}</a></td>
              <td>${esc(r.unit_name)}</td><td class="nowrap mono-cell">${esc(r.start_date)} → ${esc(r.end_date)}</td>
              <td>${fmtNum(r.participant_count)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.lowReadiness"))}</h3>
          <a class="btn sm" href="#/military/units">${esc(t("common.view"))}</a></div>
          ${table([t("mil.col.unit"), t("common.status"), t("mil.col.readiness")],
            lists.low_readiness_units, r => `
            <tr><td><a href="#/military/units/${r.id}">${esc(r.name)}</a></td>
              <td>${chip(r.status)}</td><td>${chip(r.readiness_tier || "—")}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.list.unitReadiness"))}</h3></div>
          ${table([t("mil.col.unit"), t("common.status"), t("mil.col.personnel"), t("mil.col.classification")],
            lists.unit_readiness, r => `
            <tr><td><a href="#/military/units/${r.id}">${esc(r.name)}</a></td>
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

  /* ========================================================= view: list */
  A.views.milList = async function (root, params) {
    const entity = params.entity;
    const m = await meta();
    const spec = m.entities[entity];
    if (!spec) { location.hash = "#/military"; return; }
    A.crumbs([{ label: t("nav.military"), href: "#/military" }, { label: entLabel(entity) }]);
    const data = await mreq("GET", "/" + entity + "s?limit=200");
    const names = spec.fields.map(f => f.name);
    const cols = ["name", "full_name", "exercise_name", "code", "entity_type"]
      .filter(n => names.includes(n)).slice(0, 1)
      .concat(["status", "category", "role", "condition", "echelon", "region_type"]
        .filter(n => names.includes(n)).slice(0, 1))
      .concat(["unit_id", "start_date", "quantity", "author"]
        .filter(n => names.includes(n)).slice(0, 2));
    const colSpecs = cols.map(n => spec.fields.find(f => f.name === n));
    /* reference columns resolve labels from a pre-fetched id map (sync render) */
    const refMap = {};
    await Promise.all(colSpecs.filter(f => f && f.type === "ref").map(async f => {
      if (!refMap[f.entity]) {
        const rows = await refOptions(f.entity);
        refMap[f.entity] = {};
        rows.forEach(r => { refMap[f.entity][r.id] = r; });
      }
    }));

    const rowHtml = r => `
      <tr data-search="${esc(JSON.stringify(r).toLowerCase())}">
        <td class="mono-cell">${esc(r.docname)}</td>
        ${colSpecs.map(f => `<td>${cell(r, f, refMap)}</td>`).join("")}
        <td><a class="btn sm" href="#/military/${entity}s/${r.id}">${esc(t("common.edit"))}</a></td>
      </tr>`;
    let offset = data.records.length;
    const total = data.total;

    root.innerHTML = milNav("e:" + entity) +
      A.pageHead(entLabel(entity), t("mil.list.count", { n: fmtNum(total) }), `
        <a class="btn primary" href="#/military/${entity}s/new">${icon("plus")} ${esc(t("common.new"))}</a>`) +
      `<div class="card">
        <div class="btn-row" style="margin-bottom:12px">
          <input id="milSearch" type="search" class="grow"
            placeholder="${esc(t("mil.search.placeholder"))}" style="max-width:320px">
        </div>
        ${table([t("mil.form.docname")].concat(colSpecs.map(fieldLabel), [t("common.actions")]),
          data.records, rowHtml)}
        ${total > offset ? `<div class="btn-row" style="margin-top:12px">
          <button id="milMore" class="btn">
            ${esc(t("mil.list.loadMore", { n: fmtNum(Math.min(200, total - offset)) }))}
          </button></div>` : ""}
      </div>`;
    bindChrome(root);
    const search = root.querySelector("#milSearch");
    search.oninput = () => {
      const q = search.value.trim().toLowerCase();
      root.querySelectorAll("tbody tr[data-search]").forEach(tr => {
        tr.style.display = !q || tr.dataset.search.includes(q) ? "" : "none";
      });
    };
    /* server-side pagination: append the next page on demand (volume-safe) */
    const more = root.querySelector("#milMore");
    if (more) more.onclick = async () => {
      more.disabled = true;
      const page = await mreq("GET", "/" + entity + "s?limit=200&offset=" + offset);
      root.querySelector("tbody").insertAdjacentHTML("beforeend", page.records.map(rowHtml).join(""));
      offset += page.records.length;
      if (offset >= total) { more.remove(); return; }
      more.disabled = false;
      more.textContent = t("mil.list.loadMore", { n: fmtNum(Math.min(200, total - offset)) });
    };
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
        control = `<select name="${f.name}"><option value=""></option>${(refs[f.entity] || []).map(r =>
          `<option value="${r.id}"${Number(v) === r.id ? " selected" : ""}>${esc(refLabelOf(f.entity, r))}</option>`).join("")}</select>`;
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
      `<div class="card"><form id="milForm" class="form-grid">${fieldsHtml}</form>
        ${id ? `<hr class="hr-soft"><div class="small muted">
          ${esc(t("mil.form.created"))}: ${esc(record.created_at || "—")} · ${esc(record.created_by || "—")} ·
          ${esc(t("mil.form.modified"))}: ${esc(record.modified_at || "—")} · ${esc(record.modified_by || "—")}
        </div>` : ""}
        <div class="btn-row" style="margin-top:16px">
          <button class="btn primary" id="milSave">${icon("save")} ${esc(t("common.save"))}</button>
          <a class="btn" href="#/military/${entity}s">${esc(t("common.cancel"))}</a>
        </div>
      </div>`;

    if (entity === "unit" && id) {
      root.querySelector(".card .btn-row").insertAdjacentHTML("beforeend",
        `<a class="btn" href="#/military/units/${id}/force">${icon("activity")} ${esc(t("mil.force.title"))}</a>`);
    }
    bindChrome(root);
    const form = root.querySelector("#milForm");

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

    root.innerHTML = milNav(kind) +
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
    root.innerHTML = milNav("units") +
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
              ? `<a href="#/military/deployments/${d.current_deployment.id}">${esc(d.current_deployment.name)}</a>`
              : "—"}</div>
          <div class="k-foot">${d.current_deployment ? chip(d.current_deployment.status) : ""}</div></div>
      </div>
      <div class="grid c2">
        <div class="card"><div class="card-head"><h3>${esc(t("mil.force.children"))}</h3></div>
          ${table([t("mil.col.unit"), t("mil.form.docname"), t("common.status"), t("mil.col.personnel")],
            d.children, r => `<tr><td><a href="#/military/units/${r.id}">${esc(r.name)}</a></td>
              <td class="mono-cell">${esc(r.docname)}</td><td>${chip(r.status)}</td>
              <td>${fmtNum(r.direct_personnel)}</td></tr>`)}</div>
        <div class="card"><div class="card-head"><h3>${esc(t("mil.force.siblings"))}</h3></div>
          ${table([t("mil.col.unit"), t("common.status")], d.siblings, r =>
            `<tr><td><a href="#/military/units/${r.id}">${esc(r.name)}</a></td>
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
    const data = await mreq("GET", "/naming/status");
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
