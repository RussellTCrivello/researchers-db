/* Military Organization — Brigade Information Management System.
 * Self-contained interface: no external libraries. Schema-driven from
 * GET /api/military/meta — lists and forms are generated from the same field
 * specs the server validates against.
 * ALL DATA RENDERED HERE IS FICTIONAL SAMPLE DATA.
 */
"use strict";

/* ------------------------------------------------------------------ */
/* state + localization layer (namespaced keys: mil.*)                */
/* ------------------------------------------------------------------ */
const S = {
  meta: null,
  lang: localStorage.getItem("mil.lang") || "en",
  role: localStorage.getItem("mil.role") || "admin",
  refs: {},        // entity -> options for ref selects
};

const L10N = {
  en: {
    "mil.brand": "BRIGADE COMMAND",
    "mil.subtitle": "Military Organization · BIMS",
    "mil.disclaimer": "ALL data shown is FICTIONAL sample data. Every unit, commander, place and operation is invented for demonstration and does not depict any real military organization.",
    "mil.nav.command": "Command",
    "mil.nav.records": "Records",
    "mil.nav.admin": "Administration",
    "mil.nav.workspace": "Workspace",
    "mil.nav.units_tree": "Force Tree",
    "mil.nav.regions_tree": "Region Tree",
    "mil.nav.naming": "Naming Series",
    "mil.nav.audit": "Audit Log",
    "mil.workspace.title": "Brigade Command Workspace",
    "mil.kpi.active_units": "Active Units",
    "mil.kpi.current_deployments": "Current Deployments",
    "mil.kpi.open_missions": "Open Missions",
    "mil.kpi.training_this_year": "Training This Year",
    "mil.kpi.active_commanders": "Active Commanders",
    "mil.chart.unit_status": "Units by Status",
    "mil.chart.unit_type": "Units by Echelon",
    "mil.chart.region_distribution": "Units by Region",
    "mil.list.upcoming_deployments": "Upcoming / Open Deployments",
    "mil.list.upcoming_trainings": "Upcoming Trainings",
    "mil.list.low_readiness_units": "Low-Readiness Units",
    "mil.list.unit_readiness": "Unit Readiness",
    "mil.list.recent_activity": "Recent Activity",
    "mil.action.new": "New",
    "mil.action.save": "Save",
    "mil.action.cancel": "Cancel",
    "mil.action.delete": "Delete",
    "mil.action.confirm_delete": "Confirm delete?",
    "mil.action.back": "Back",
    "mil.action.open": "Open",
    "mil.action.load_sample": "Load fictional sample data",
    "mil.action.reset_sample": "Reset sample data",
    "mil.action.clear_sample": "Clear sample data",
    "mil.action.preview": "Preview next name",
    "mil.action.adjust": "Adjust counter",
    "mil.search.placeholder": "Search…",
    "mil.form.created": "Created",
    "mil.form.modified": "Modified",
    "mil.form.docname": "Document Name",
    "mil.form.saved": "Saved",
    "mil.form.deleted": "Deleted",
    "mil.form.required": "required",
    "mil.tree.expand": "Expand / collapse",
    "mil.tree.search": "Filter tree…",
    "mil.tree.subtree_personnel": "Subtree personnel",
    "mil.tree.breadcrumb": "Path",
    "mil.naming.title": "Naming Series Administration",
    "mil.naming.help": "Counters are per series and partition (year / category). Previews are advisory and do not reserve a value. Adjustments are administrator-only and logged.",
    "mil.naming.partition": "Partition",
    "mil.naming.current": "Current",
    "mil.naming.next": "Next",
    "mil.audit.title": "Audit Log",
    "mil.viewer.blocked": "Viewer role is read-only.",
    "mil.err.generic": "Request failed",
    "mil.empty": "No records",
  },
  ar: {
    "mil.brand": "قيادة اللواء",
    "mil.subtitle": "التنظيم العسكري · نظام إدارة اللواء",
    "mil.disclaimer": "جميع البيانات المعروضة هي بيانات افتراضية للعرض فقط. كل وحدة وقائد ومكان وعملية مختلقة للعرض ولا تمثل أي منظمة عسكرية حقيقية.",
    "mil.nav.command": "القيادة",
    "mil.nav.records": "السجلات",
    "mil.nav.admin": "الإدارة",
    "mil.nav.workspace": "مساحة العمل",
    "mil.nav.units_tree": "شجرة القوات",
    "mil.nav.regions_tree": "شجرة المناطق",
    "mil.nav.naming": "سلاسل التسمية",
    "mil.nav.audit": "سجل التدقيق",
    "mil.workspace.title": "مساحة عمل قيادة اللواء",
    "mil.kpi.active_units": "الوحدات النشطة",
    "mil.kpi.current_deployments": "النشر الحالي",
    "mil.kpi.open_missions": "المهام المفتوحة",
    "mil.kpi.training_this_year": "التدريب هذا العام",
    "mil.kpi.active_commanders": "القادة النشطون",
    "mil.chart.unit_status": "الوحدات حسب الحالة",
    "mil.chart.unit_type": "الوحدات حسب المستوى",
    "mil.chart.region_distribution": "الوحدات حسب المنطقة",
    "mil.list.upcoming_deployments": "عمليات النشر القادمة والمفتوحة",
    "mil.list.upcoming_trainings": "التدريبات القادمة",
    "mil.list.low_readiness_units": "وحدات ذات جاهزية منخفضة",
    "mil.list.unit_readiness": "جاهزية الوحدات",
    "mil.list.recent_activity": "النشاط الأخير",
    "mil.action.new": "جديد",
    "mil.action.save": "حفظ",
    "mil.action.cancel": "إلغاء",
    "mil.action.delete": "حذف",
    "mil.action.confirm_delete": "تأكيد الحذف؟",
    "mil.action.back": "رجوع",
    "mil.action.open": "فتح",
    "mil.action.load_sample": "تحميل بيانات افتراضية",
    "mil.action.reset_sample": "إعادة ضبط البيانات",
    "mil.action.clear_sample": "مسح البيانات",
    "mil.action.preview": "معاينة الاسم التالي",
    "mil.action.adjust": "تعديل العداد",
    "mil.search.placeholder": "بحث…",
    "mil.form.created": "تاريخ الإنشاء",
    "mil.form.modified": "آخر تعديل",
    "mil.form.docname": "اسم المستند",
    "mil.form.saved": "تم الحفظ",
    "mil.form.deleted": "تم الحذف",
    "mil.form.required": "مطلوب",
    "mil.tree.expand": "توسيع / طي",
    "mil.tree.search": "تصفية الشجرة…",
    "mil.tree.subtree_personnel": "قوة الشجرة الفرعية",
    "mil.tree.breadcrumb": "المسار",
    "mil.naming.title": "إدارة سلاسل التسمية",
    "mil.naming.help": "العدادات حسب السلسلة والقسم (السنة / الفئة). المعاينات إرشادية ولا تحجز قيمة. التعديلات للمسؤولين فقط وتسجل.",
    "mil.naming.partition": "القسم",
    "mil.naming.current": "الحالي",
    "mil.naming.next": "التالي",
    "mil.audit.title": "سجل التدقيق",
    "mil.viewer.blocked": "دور المعرض للقراءة فقط.",
    "mil.err.generic": "فشل الطلب",
    "mil.empty": "لا توجد سجلات",
  },
};

function t(key, fallback) {
  const dict = L10N[S.lang] || L10N.en;
  return dict[key] || L10N.en[key] || fallback || key;
}

/* ------------------------------------------------------------------ */
/* api helpers                                                        */
/* ------------------------------------------------------------------ */
async function api(path, options) {
  const opts = Object.assign({ headers: {} }, options || {});
  opts.headers["X-Military-Role"] = S.role;
  opts.headers["X-Actor"] = "ui:" + S.role;
  if (opts.body && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch("/api/military" + path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const err = (data && data.detail && data.detail.error) || (data && data.error) || {};
    const error = new Error(err.message || t("mil.err.generic"));
    error.status = res.status;
    error.code = err.code || "error";
    error.field = err.field;
    throw error;
  }
  return data;
}

function toast(message, kind) {
  const host = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast" + (kind ? " " + kind : "");
  el.textContent = message;
  host.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ------------------------------------------------------------------ */
/* shell                                                              */
/* ------------------------------------------------------------------ */
function buildNav() {
  const groups = [
    ["mil.nav.command", [
      ["#/workspace", "mil.nav.workspace"],
      ["#/trees/units", "mil.nav.units_tree"],
      ["#/trees/regions", "mil.nav.regions_tree"],
    ]],
    ["mil.nav.records", (S.meta ? Object.keys(S.meta.entities) : []).map((key) => [
      "#/list/" + key, S.meta.entities[key].label])],
    ["mil.nav.admin", [
      ["#/naming", "mil.nav.naming"],
      ["#/audit", "mil.nav.audit"],
    ]],
  ];
  const current = location.hash || "#/workspace";
  const nav = document.getElementById("nav");
  nav.innerHTML = groups.map(([group, items]) =>
    `<div class="nav-group">${esc(group.startsWith("mil.") ? t(group) : group)}</div>` +
    items.map(([href, label]) => {
      const text = label.startsWith("mil.") ? t(label) : label;
      const active = current === href || current.startsWith(href + "/") ||
        (href.startsWith("#/list/") && current.startsWith(href));
      return `<a class="nav-item${active ? " active" : ""}" href="${href}">${esc(text)}</a>`;
    }).join("")
  ).join("");
}

function applyShell() {
  document.documentElement.lang = S.lang;
  document.documentElement.dir = S.lang === "ar" ? "rtl" : "ltr";
  document.getElementById("disclaimer").textContent = t("mil.disclaimer");
  document.getElementById("role-pill").textContent = S.role;
  document.getElementById("role-select").value = S.role;
  document.getElementById("lang-select").value = S.lang;
  document.querySelector(".brand").innerHTML =
    esc(t("mil.brand")) + `<small>${esc(t("mil.subtitle"))}</small>`;
}

/* ------------------------------------------------------------------ */
/* shared renderers                                                   */
/* ------------------------------------------------------------------ */
function statusBadge(status) {
  if (!status) return "";
  const ok = ["Active", "Serviceable", "Executed", "Completed", "Excellent", "Satisfactory"];
  const warn = ["Training", "Standby", "Planned", "Ongoing", "Suspended", "Limited",
    "Reserve", "Needs Improvement", "Reorganizing", "Stand-down", "In Refit"];
  const cls = ok.includes(status) ? "ok" : warn.includes(status) ? "warn" : "bad";
  return `<span class="badge ${cls}">${esc(status)}</span>`;
}

function chartRows(entries) {
  if (!entries || !entries.length) return `<div class="empty">${esc(t("mil.empty"))}</div>`;
  const max = Math.max.apply(null, entries.map((e) => e.count)) || 1;
  return entries.map((e) =>
    `<div class="chart-row"><div class="key" title="${esc(e.key)}">${esc(e.key)}</div>` +
    `<div class="bar-wrap"><div class="bar" style="width:${Math.round(e.count / max * 100)}%"></div></div>` +
    `<div class="num">${e.count}</div></div>`).join("");
}

function refOptions(entity) {
  return S.refs[entity] || [];
}

function refLabel(entity, record) {
  if (!record) return "";
  return `${record.docname || "#" + record.id} · ${record.name || record.full_name || record.exercise_name || ""}`;
}

async function ensureRefs(fields) {
  const needed = new Set(fields.filter((f) => f.type === "ref").map((f) => f.entity));
  await Promise.all(Array.from(needed).map(async (entity) => {
    if (S.refs[entity]) return;
    const data = await api("/" + entity + "?limit=500");
    S.refs[entity] = data.records;
  }));
}

/* ------------------------------------------------------------------ */
/* view: workspace                                                    */
/* ------------------------------------------------------------------ */
async function viewWorkspace() {
  setTitle(t("mil.workspace.title"));
  const data = await api("/summary");
  const c = data.cards, ch = data.charts, lists = data.lists;
  const kpis = [
    ["mil.kpi.active_units", c.active_units, "active"],
    ["mil.kpi.current_deployments", c.current_deployments, "is_current = 1"],
    ["mil.kpi.open_missions", c.open_missions, "Planned + Ongoing"],
    ["mil.kpi.training_this_year", c.training_this_year, new Date().getFullYear()],
    ["mil.kpi.active_commanders", c.active_commanders, "status = Active"],
  ];
  const table = (cols, rows, render) =>
    rows.length
      ? `<table class="list"><thead><tr>${cols.map((c2) => `<th>${esc(c2)}</th>`).join("")}</tr></thead>` +
        `<tbody>${rows.map(render).join("")}</tbody></table>`
      : `<div class="empty">${esc(t("mil.empty"))}</div>`;

  return `
    <div class="grid cols-5">
      ${kpis.map(([label, value, foot]) => `
        <div class="kpi"><div class="label">${esc(t(label))}</div>
        <div class="value">${value}</div><div class="foot">${esc(String(foot))}</div></div>`).join("")}
    </div>
    <div class="grid cols-3" style="margin-top:16px">
      <div class="panel"><h2>${esc(t("mil.chart.unit_status"))}</h2>${chartRows(ch.unit_status)}</div>
      <div class="panel"><h2>${esc(t("mil.chart.unit_type"))}</h2>${chartRows(ch.unit_type)}</div>
      <div class="panel"><h2>${esc(t("mil.chart.region_distribution"))}</h2>${chartRows(ch.region_distribution)}</div>
    </div>
    <div class="grid cols-2">
      <div class="panel"><h2>${esc(t("mil.list.upcoming_deployments"))}</h2>
        ${table(["Name", "Unit", "Start", "Status"], lists.upcoming_deployments, (r) =>
          `<tr><td><a href="#/edit/deployment/${r.id}">${esc(r.name)}</a></td>
           <td>${esc(r.unit_name)}</td><td class="mono">${esc(r.start_date)}</td>
           <td>${statusBadge(r.status)}</td></tr>`)}</div>
      <div class="panel"><h2>${esc(t("mil.list.upcoming_trainings"))}</h2>
        ${table(["Exercise", "Unit", "Dates", "Participants"], lists.upcoming_trainings, (r) =>
          `<tr><td><a href="#/edit/training/${r.id}">${esc(r.exercise_name)}</a></td>
           <td>${esc(r.unit_name)}</td><td class="mono">${esc(r.start_date)} → ${esc(r.end_date)}</td>
           <td>${r.participant_count}</td></tr>`)}</div>
      <div class="panel"><h2>${esc(t("mil.list.low_readiness_units"))}</h2>
        ${table(["Unit", "Status", "Readiness"], lists.low_readiness_units, (r) =>
          `<tr><td><a href="#/edit/unit/${r.id}">${esc(r.name)}</a></td>
           <td>${statusBadge(r.status)}</td>
           <td>${esc(r.readiness_tier || "—")}</td></tr>`)}</div>
      <div class="panel"><h2>${esc(t("mil.list.unit_readiness"))}</h2>
        ${table(["Unit", "Status", "Personnel", "Classification"], lists.unit_readiness, (r) =>
          `<tr><td><a href="#/edit/unit/${r.id}">${esc(r.name)}</a></td>
           <td>${statusBadge(r.status)}</td><td>${r.direct_personnel}</td>
           <td>${esc(r.classification_name || "—")}</td></tr>`)}</div>
      <div class="panel" style="grid-column:1/-1"><h2>${esc(t("mil.list.recent_activity"))}</h2>
        ${table(["When", "Actor", "Action", "Record", "Summary"], lists.recent_activity, (r) =>
          `<tr><td class="mono">${esc(r.at)}</td><td>${esc(r.actor)}</td>
           <td>${esc(r.action)} · ${esc(r.entity)}</td>
           <td class="mono">${esc(r.docname || "#" + (r.record_id || ""))}</td>
           <td class="muted">${esc(r.summary || "")}</td></tr>`)}</div>
    </div>
    <div class="panel">
      <h2>Sample Data</h2>
      <p class="muted">${esc(t("mil.disclaimer"))}</p>
      <div class="actions">
        <button data-act="sample">${esc(t("mil.action.load_sample"))}</button>
        <button data-act="sample-reset">${esc(t("mil.action.reset_sample"))}</button>
        <button class="danger" data-act="sample-clear">${esc(t("mil.action.clear_sample"))}</button>
      </div>
    </div>`;
}

function bindWorkspace(root) {
  root.addEventListener("click", async (ev) => {
    const act = ev.target.getAttribute && ev.target.getAttribute("data-act");
    if (!act) return;
    if (S.role === "viewer") { toast(t("mil.viewer.blocked"), "err"); return; }
    try {
      if (act === "sample") {
        await api("/sample", { method: "POST", body: {} });
        toast(t("mil.form.saved"), "ok"); route();
      } else if (act === "sample-reset") {
        await api("/sample", { method: "POST", body: { force: true } });
        toast(t("mil.form.saved"), "ok"); route();
      } else if (act === "sample-clear") {
        const btn = ev.target;
        if (!btn.classList.contains("armed")) {
          btn.classList.add("armed"); btn.textContent = t("mil.action.confirm_delete");
          setTimeout(() => { btn.classList.remove("armed"); btn.textContent = t("mil.action.clear_sample"); }, 4000);
          return;
        }
        await api("/sample", { method: "DELETE" });
        toast(t("mil.form.deleted"), "ok"); route();
      }
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ------------------------------------------------------------------ */
/* view: lists                                                        */
/* ------------------------------------------------------------------ */
function listColumns(entity, fields) {
  const pick = [];
  const names = fields.map((f) => f.name);
  for (const candidate of ["name", "full_name", "exercise_name", "code", "entity_type"]) {
    if (names.includes(candidate)) { pick.push(candidate); break; }
  }
  for (const candidate of ["status", "category", "role", "condition", "echelon", "region_type"]) {
    if (names.includes(candidate)) { pick.push(candidate); break; }
  }
  for (const candidate of ["unit_id", "start_date", "quantity", "author"]) {
    if (names.includes(candidate)) pick.push(candidate);
    if (pick.length >= 4) break;
  }
  return pick.slice(0, 4);
}

function cellValue(entity, record, field) {
  const value = record[field.name];
  if (value == null || value === "") return "—";
  if (field.type === "ref") {
    const ref = refOptions(field.entity).find((r) => r.id === value);
    return esc(ref ? refLabel(field.entity, ref) : "#" + value);
  }
  if (field.type === "bool") return value ? "✓" : "—";
  if (field.name === "status" || field.name === "condition") return statusBadge(value);
  return esc(String(value));
}

async function viewList(entity) {
  const spec = S.meta.entities[entity];
  if (!spec) { location.hash = "#/workspace"; return ""; }
  await ensureRefs(spec.fields);
  setTitle(spec.label);
  const data = await api("/" + entity + "?limit=200");
  const cols = listColumns(entity, spec.fields);
  const colSpecs = cols.map((name) => spec.fields.find((f) => f.name === name));
  return `
    <div class="panel">
      <div class="toolbar">
        <input type="search" id="search" placeholder="${esc(t("mil.search.placeholder"))}">
        <span class="muted">${data.total} record(s)</span>
        <span class="spacer"></span>
        <a class="btn primary" href="#/new/${entity}">+ ${esc(t("mil.action.new"))} ${esc(spec.label)}</a>
      </div>
      <table class="list">
        <thead><tr><th>${esc(t("mil.form.docname"))}</th>
        ${colSpecs.map((f) => `<th>${esc(f.label)}</th>`).join("")}<th></th></tr></thead>
        <tbody id="rows">
        ${data.records.map((r) => `
          <tr data-search="${esc(JSON.stringify(r).toLowerCase())}">
            <td class="docname">${esc(r.docname)}</td>
            ${colSpecs.map((f) => `<td>${cellValue(entity, r, f)}</td>`).join("")}
            <td><a class="btn small" href="#/edit/${entity}/${r.id}">${esc(t("mil.action.open"))}</a></td>
          </tr>`).join("")}
        </tbody>
      </table>
      ${data.records.length ? "" : `<div class="empty">${esc(t("mil.empty"))}</div>`}
    </div>`;
}

function bindList(root) {
  const search = root.querySelector("#search");
  if (!search) return;
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    root.querySelectorAll("#rows tr").forEach((tr) => {
      tr.style.display = !q || tr.getAttribute("data-search").includes(q) ? "" : "none";
    });
  });
}

/* ------------------------------------------------------------------ */
/* view: forms                                                        */
/* ------------------------------------------------------------------ */
async function viewForm(entity, id) {
  const spec = S.meta.entities[entity];
  if (!spec) { location.hash = "#/workspace"; return ""; }
  await ensureRefs(spec.fields);
  const creating = !id;
  let record = { };
  if (!creating) {
    const data = await api("/" + entity + "/" + id);
    record = data.record;
  }
  setTitle((creating ? t("mil.action.new") : spec.label) + " · " + spec.label);

  const fieldsHtml = spec.fields.map((f) => {
    const value = record[f.name];
    const req = f.required ? ` <span class="req">*</span>` : "";
    let control = "";
    if (f.type === "choice") {
      control = `<select name="${f.name}">
        <option value=""></option>
        ${f.options.map((o) =>
          `<option value="${esc(o)}"${String(value) === o ? " selected" : ""}>${esc(o)}</option>`).join("")}
      </select>`;
    } else if (f.type === "ref") {
      control = `<select name="${f.name}">
        <option value=""></option>
        ${refOptions(f.entity).map((r) =>
          `<option value="${r.id}"${Number(value) === r.id ? " selected" : ""}>${esc(refLabel(f.entity, r))}</option>`).join("")}
      </select>`;
    } else if (f.type === "textarea") {
      control = `<textarea name="${f.name}" rows="3">${esc(value || "")}</textarea>`;
    } else if (f.type === "bool") {
      control = `<select name="${f.name}">
        <option value="1"${value ? " selected" : ""}>✓ yes</option>
        <option value="0"${value ? "" : " selected"}>— no</option>
      </select>`;
    } else {
      const inputType = f.type === "date" ? "date" : f.type === "int" ? "number" : "text";
      control = `<input type="${inputType}" name="${f.name}" value="${esc(value == null ? "" : value)}"
        ${f.min != null ? `min="${f.min}"` : ""}>`;
    }
    return `<div class="field" data-field="${f.name}">
      <label>${esc(f.label)}${req}</label>${control}
      <div class="err"></div></div>`;
  }).join("");

  const sysFields = creating ? "" : `
    <div class="form-grid" style="margin-top:18px">
      <div class="field readonly"><label>${esc(t("mil.form.docname"))}</label>
        <div class="static">${esc(record.docname)}</div></div>
      <div class="field readonly"><label>${esc(t("mil.form.created"))}</label>
        <div class="static">${esc(record.created_at)} · ${esc(record.created_by)}</div></div>
      <div class="field readonly"><label>${esc(t("mil.form.modified"))}</label>
        <div class="static">${esc(record.modified_at || "—")} · ${esc(record.modified_by || "—")}</div></div>
    </div>`;

  const extraActions = [];
  if (entity === "unit" && !creating) {
    extraActions.push(`<a class="btn" href="#/trees/units?focus=${record.id}">Open in Force Tree</a>`);
    extraActions.push(`<a class="btn" href="#/units/${record.id}/force">Force Summary</a>`);
  }
  if (entity === "armament" && !creating) {
    extraActions.push(`<a class="btn" href="#/armaments/${record.id}/holdings">Holdings</a>`);
  }

  return `
    <div class="panel">
      <div class="actions">
        <a class="btn" href="#/list/${entity}">← ${esc(t("mil.action.back"))}</a>
        ${extraActions.join("")}
        <span class="spacer"></span>
        ${creating ? "" : `<button class="danger" id="delete-btn">${esc(t("mil.action.delete"))}</button>`}
      </div>
      <form id="record-form" style="margin-top:14px">
        <div class="form-grid">${fieldsHtml}</div>
        ${sysFields}
        <div class="actions" style="margin-top:18px">
          <button class="primary" type="submit">${esc(t("mil.action.save"))}</button>
          <a class="btn" href="#/list/${entity}">${esc(t("mil.action.cancel"))}</a>
        </div>
      </form>
    </div>`;
}

function bindForm(root, entity, id) {
  const form = root.querySelector("#record-form");
  const spec = S.meta.entities[entity];

  function collect() {
    const payload = {};
    spec.fields.forEach((f) => {
      const el = form.elements[f.name];
      if (!el) return;
      let value = el.value;
      if (f.type === "int" && value !== "") value = Number(value);
      if (f.type === "bool") value = el.value === "1";
      if (f.type === "ref" && value !== "") value = Number(value);
      payload[f.name] = value === "" ? null : value;
    });
    return payload;
  }

  function clearErrors() {
    form.querySelectorAll(".field").forEach((f) => {
      f.classList.remove("invalid");
      const err = f.querySelector(".err");
      if (err) err.textContent = "";
    });
  }

  function showErrors(err) {
    clearErrors();
    if (err.field) {
      const field = form.querySelector(`.field[data-field="${err.field}"]`);
      if (field) {
        field.classList.add("invalid");
        field.querySelector(".err").textContent = err.message;
      }
    }
    toast(err.message, "err");
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (S.role === "viewer") { toast(t("mil.viewer.blocked"), "err"); return; }
    clearErrors();
    const payload = collect();
    try {
      const res = id
        ? await api("/" + entity + "/" + id, { method: "PATCH", body: payload })
        : await api("/" + entity, { method: "POST", body: payload });
      toast(t("mil.form.saved"), "ok");
      location.hash = "#/edit/" + entity + "/" + res.record.id;
    } catch (err) {
      showErrors(err);
    }
  });

  const del = root.querySelector("#delete-btn");
  if (del) {
    del.addEventListener("click", async () => {
      if (S.role !== "admin") { toast(t("mil.viewer.blocked"), "err"); return; }
      if (!del.classList.contains("armed")) {
        del.classList.add("armed");
        del.textContent = t("mil.action.confirm_delete");
        setTimeout(() => {
          del.classList.remove("armed");
          del.textContent = t("mil.action.delete");
        }, 4000);
        return;
      }
      try {
        await api("/" + entity + "/" + id, { method: "DELETE" });
        toast(t("mil.form.deleted"), "ok");
        location.hash = "#/list/" + entity;
      } catch (err) {
        toast(err.message, "err");
      }
    });
  }
}

/* ------------------------------------------------------------------ */
/* view: trees                                                        */
/* ------------------------------------------------------------------ */
async function viewTree(kind, focusId) {
  const isUnits = kind === "units";
  const entity = isUnits ? "unit" : "region";
  const spec = S.meta.entities[entity];
  await ensureRefs(spec.fields);
  const data = await api("/" + (isUnits ? "units/tree" : "regions/tree"));
  setTitle(isUnits ? t("mil.nav.units_tree") : t("mil.nav.regions_tree"));

  function nodeHtml(node) {
    const badge = isUnits ? statusBadge(node.status) : `<span class="badge">${esc(node.region_type || "")}</span>`;
    const personnel = isUnits
      ? `<span class="meta">Σ ${node.subtree_personnel != null ? node.subtree_personnel : "?"} · ${esc(t("mil.tree.subtree_personnel"))}</span>`
      : "";
    const hasKids = node.children && node.children.length;
    return `<li>
      <details ${focusId && Number(focusId) === node.id ? "open" : hasKids ? "open" : ""}>
        <summary><div class="node" data-id="${node.id}">
          <span class="toggle">${hasKids ? "▾" : "·"}</span>
          <a class="name" href="#/edit/${entity}/${node.id}">${esc(node.name)}</a>
          <span class="docname">${esc(node.docname)}</span>
          ${badge}${personnel}
        </div></summary>
        ${hasKids ? `<ul>${node.children.map(nodeHtml).join("")}</ul>` : ""}
      </details>
    </li>`;
  }

  return `
    <div class="panel">
      <div class="toolbar">
        <input type="search" id="tree-search" placeholder="${esc(t("mil.tree.search"))}">
        <span class="spacer"></span>
        <a class="btn primary" href="#/new/${entity}">+ ${esc(t("mil.action.new"))} ${esc(spec.label)}</a>
      </div>
      <div class="tree" id="tree"><ul>${data.tree.map(nodeHtml).join("")}</ul></div>
    </div>`;
}

function bindTree(root) {
  const search = root.querySelector("#tree-search");
  if (!search) return;
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    root.querySelectorAll("#tree li").forEach((li) => {
      const match = !q || li.textContent.toLowerCase().includes(q);
      li.style.display = match ? "" : "none";
      if (q && match) {
        let parent = li.parentElement;
        while (parent && parent.id !== "tree") {
          if (parent.tagName === "DETAILS") parent.open = true;
          if (parent.tagName === "LI") parent.style.display = "";
          parent = parent.parentElement;
        }
      }
    });
  });
}

/* ------------------------------------------------------------------ */
/* view: force summary + armament holdings                            */
/* ------------------------------------------------------------------ */
async function viewForce(unitId) {
  const data = await api("/units/" + unitId + "/force-summary");
  setTitle("Force Summary · " + data.unit.name);
  return `
    <div class="panel">
      <div class="actions"><a class="btn" href="#/trees/units">← ${esc(t("mil.action.back"))}</a>
        <a class="btn" href="#/edit/unit/${data.unit.id}">${esc(t("mil.action.open"))}</a></div>
      <h2 style="margin-top:12px">${esc(data.unit.name)} <span class="docname">${esc(data.unit.docname)}</span>
        ${statusBadge(data.unit.status)}</h2>
      <p>${esc(t("mil.tree.subtree_personnel"))}: <strong>${data.subtree_personnel}</strong>
        · direct: ${data.unit.direct_personnel}</p>
      <h3>Current deployment</h3>
      ${data.current_deployment
        ? `<p><a href="#/edit/deployment/${data.current_deployment.id}">${esc(data.current_deployment.name)}</a>
           ${statusBadge(data.current_deployment.status)}
           <span class="mono">${esc(data.current_deployment.start_date)} →
           ${esc(data.current_deployment.end_date || "…")}</span></p>`
        : `<p class="muted">${esc(t("mil.empty"))}</p>`}
      <h3>Children</h3>
      ${data.children.length ? `<table class="list"><tbody>${data.children.map((c) =>
        `<tr><td><a href="#/edit/unit/${c.id}">${esc(c.name)}</a></td>
         <td class="docname">${esc(c.docname)}</td><td>${esc(c.echelon)}</td>
         <td>${statusBadge(c.status)}</td><td>${c.direct_personnel}</td></tr>`).join("")}
        </tbody></table>` : `<div class="empty">${esc(t("mil.empty"))}</div>`}
      <h3>Siblings</h3>
      ${data.siblings.length ? `<table class="list"><tbody>${data.siblings.map((c) =>
        `<tr><td><a href="#/edit/unit/${c.id}">${esc(c.name)}</a></td>
         <td>${statusBadge(c.status)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty">${esc(t("mil.empty"))}</div>`}
      <h3>Recent missions</h3>
      ${data.missions.length ? `<table class="list"><tbody>${data.missions.map((m) =>
        `<tr><td><a href="#/edit/mission/${m.id}">${esc(m.name)}</a></td>
         <td>${statusBadge(m.status)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty">${esc(t("mil.empty"))}</div>`}
      <h3>Top armament</h3>
      ${data.armament_top.length ? `<table class="list"><tbody>${data.armament_top.map((a) =>
        `<tr><td>${esc(a.name)}</td><td>${esc(a.category || "")}</td>
         <td>${a.quantity}</td><td>${statusBadge(a.condition)}</td></tr>`).join("")}
        </tbody></table>` : `<div class="empty">${esc(t("mil.empty"))}</div>`}
    </div>`;
}

async function viewHoldings(armamentId) {
  const data = await api("/armaments/" + armamentId + "/holdings");
  setTitle("Holdings · " + data.armament.name);
  return `
    <div class="panel">
      <div class="actions"><a class="btn" href="#/list/armament">← ${esc(t("mil.action.back"))}</a>
        <a class="btn" href="#/edit/armament/${data.armament.id}">${esc(t("mil.action.open"))}</a></div>
      <h2 style="margin-top:12px">${esc(data.armament.name)}
        <span class="docname">${esc(data.armament.docname)}</span></h2>
      <p>Total quantity across units: <strong>${data.total_quantity}</strong></p>
      <table class="list">
        <thead><tr><th>Unit</th><th>Quantity</th><th>Condition</th><th>Acquired</th></tr></thead>
        <tbody>${data.holdings.map((h) =>
          `<tr><td><a href="#/edit/unit/${h.unit_id}">${esc(h.unit_name)}</a></td>
           <td>${h.quantity}</td><td>${statusBadge(h.condition)}</td>
           <td>${esc(h.acquisition_year || "—")}</td></tr>`).join("")}</tbody>
      </table>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* view: naming administration                                        */
/* ------------------------------------------------------------------ */
async function viewNaming() {
  setTitle(t("mil.naming.title"));
  const data = await api("/naming/status");
  const byEntity = {};
  data.series.forEach((s) => {
    (byEntity[s.entity] = byEntity[s.entity] || []).push(s);
  });
  return `
    <div class="panel">
      <h2>${esc(t("mil.naming.title"))}</h2>
      <p class="muted">${esc(t("mil.naming.help"))}</p>
      <div class="toolbar">
        <select id="preview-entity">
          ${Object.keys(S.meta.entities).map((e) =>
            `<option value="${e}">${esc(S.meta.entities[e].label)}</option>`).join("")}
        </select>
        <button class="primary" id="preview-btn">${esc(t("mil.action.preview"))}</button>
        <span class="mono" id="preview-out"></span>
      </div>
      ${Object.keys(byEntity).map((entity) => `
        <h3>${esc(S.meta.entities[entity] ? S.meta.entities[entity].label : entity)}</h3>
        <table class="list naming-grid">
          <thead><tr><th>Series</th><th>${esc(t("mil.naming.partition"))}</th>
          <th>${esc(t("mil.naming.current"))}</th><th>${esc(t("mil.naming.next"))}</th>
          <th></th></tr></thead>
          <tbody>${byEntity[entity].map((s) => `
            <tr>
              <td class="mono">${esc(s.label)}${s.is_default ? " ★" : ""}</td>
              <td class="mono">${esc(s.partition || "(default)")}</td>
              <td class="counter">${s.current_value}</td>
              <td class="docname">${esc(s.next_preview)}</td>
              <td>${S.role === "admin"
                ? `<button class="small" data-adjust="${s.id}" data-partition="${esc(s.partition)}"
                     data-label="${esc(s.label)}">${esc(t("mil.action.adjust"))}</button>` : ""}</td>
            </tr>`).join("")}</tbody>
        </table>`).join("")}
    </div>`;
}

function bindNaming(root) {
  const btn = root.querySelector("#preview-btn");
  btn.addEventListener("click", async () => {
    try {
      const entity = root.querySelector("#preview-entity").value;
      const res = await api("/naming/preview", { method: "POST", body: { entity } });
      root.querySelector("#preview-out").textContent = res.next + " (advisory)";
    } catch (err) { toast(err.message, "err"); }
  });
  root.addEventListener("click", async (ev) => {
    const id = ev.target.getAttribute && ev.target.getAttribute("data-adjust");
    if (!id) return;
    if (S.role !== "admin") { toast(t("mil.viewer.blocked"), "err"); return; }
    const label = ev.target.getAttribute("data-label");
    const partition = ev.target.getAttribute("data-partition");
    const raw = window.prompt(`New counter value for ${label} [${partition || "default"}]:`);
    if (raw == null || raw === "") return;
    try {
      await api("/naming/counter", {
        method: "PUT",
        body: { option_id: Number(id), partition: partition, new_value: Number(raw), label },
      });
      toast(t("mil.form.saved"), "ok");
      route();
    } catch (err) { toast(err.message, "err"); }
  });
}

/* ------------------------------------------------------------------ */
/* view: audit                                                        */
/* ------------------------------------------------------------------ */
async function viewAudit() {
  setTitle(t("mil.audit.title"));
  if (S.role !== "admin") {
    return `<div class="panel"><div class="empty">${esc(t("mil.viewer.blocked"))}</div></div>`;
  }
  const data = await api("/audit/log?limit=100");
  return `
    <div class="panel">
      <h2>${esc(t("mil.audit.title"))}</h2>
      <table class="list">
        <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th>
        <th>Record</th><th>Summary</th></tr></thead>
        <tbody>${data.records.map((r) =>
          `<tr><td class="mono">${esc(r.at)}</td><td>${esc(r.actor)}</td>
           <td>${esc(r.action)}</td><td>${esc(r.entity)}</td>
           <td class="mono">${esc(r.docname || "#" + (r.record_id || ""))}</td>
           <td class="muted">${esc(r.summary || "")}</td></tr>`).join("")}</tbody>
      </table>
      ${data.records.length ? "" : `<div class="empty">${esc(t("mil.empty"))}</div>`}
    </div>`;
}

/* ------------------------------------------------------------------ */
/* router                                                             */
/* ------------------------------------------------------------------ */
function setTitle(title) {
  document.getElementById("page-title").textContent = title;
}

async function route() {
  const hash = location.hash || "#/workspace";
  const view = document.getElementById("view");
  buildNav();
  view.innerHTML = `<div class="panel"><div class="empty">…</div></div>`;
  try {
    const parts = hash.replace(/^#\//, "").split("/");
    let html = "", binder = null, args = [];
    if (parts[0] === "list" && parts[1]) {
      html = await viewList(parts[1]); binder = bindList;
    } else if (parts[0] === "new" && parts[1]) {
      html = await viewForm(parts[1], null);
      binder = (root) => bindForm(root, parts[1], null);
    } else if (parts[0] === "edit" && parts[1] && parts[2]) {
      html = await viewForm(parts[1], Number(parts[2]));
      binder = (root) => bindForm(root, parts[1], Number(parts[2]));
    } else if (parts[0] === "trees" && parts[1]) {
      const focus = (hash.split("?focus=")[1] || "").split("&")[0];
      html = await viewTree(parts[1], focus); binder = bindTree;
    } else if (parts[0] === "units" && parts[2] === "force") {
      html = await viewForce(Number(parts[1]));
    } else if (parts[0] === "armaments" && parts[2] === "holdings") {
      html = await viewHoldings(Number(parts[1]));
    } else if (parts[0] === "naming") {
      html = await viewNaming(); binder = bindNaming;
    } else if (parts[0] === "audit") {
      html = await viewAudit();
    } else {
      html = await viewWorkspace(); binder = bindWorkspace;
    }
    view.innerHTML = html;
    if (binder) binder(view);
  } catch (err) {
    view.innerHTML = `<div class="panel"><div class="empty">${esc(err.message)}</div></div>`;
  }
}

/* ------------------------------------------------------------------ */
/* boot                                                               */
/* ------------------------------------------------------------------ */
async function boot() {
  try {
    S.meta = await api("/meta");
  } catch (err) {
    document.getElementById("view").innerHTML =
      `<div class="panel"><div class="empty">API unavailable: ${esc(err.message)}</div></div>`;
    return;
  }
  applyShell();
  document.getElementById("role-select").addEventListener("change", (ev) => {
    S.role = ev.target.value;
    localStorage.setItem("mil.role", S.role);
    applyShell();
    route();
  });
  document.getElementById("lang-select").addEventListener("change", (ev) => {
    S.lang = ev.target.value;
    localStorage.setItem("mil.lang", S.lang);
    applyShell();
    route();
  });
  window.addEventListener("hashchange", route);
  route();
}

boot();
