/* ============================================================================
   SIRAJ · admin.js — import wizard, export screen, change log, vocabularies,
   numbering, settings, maintenance
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, icon, hydrateIcons, toast, fmtNum } = A;

  /* ============================================================ IMPORT === */
  A.views.import = async function (root) {
    A.crumbs([{ label: t("nav.import") }]);
    const entities = A.state.meta.entities || [];
    let st = { step: 1, entity: entities[0].key, format: "xlsx", lang: A.state.lang,
      upload: null, mapping: {}, mode: "create", status: "in_review", report: null };

    root.innerHTML = A.pageHead(t("imp.title"), t("imp.subtitle"), "")
      + `<div class="wizard-steps" id="steps"></div>
         <div id="wizard" class="stack"></div>
         <div class="card" id="jobsCard"></div>`;
    hydrateIcons(root);
    const host = root.querySelector("#wizard");
    const stepsEl = root.querySelector("#steps");

    function paintSteps() {
      stepsEl.innerHTML = [1, 2, 3, 4].map(n => `
        <div class="step ${st.step === n ? "active" : ""} ${st.step > n ? "done" : ""}">
          <span class="n">${st.step > n ? "✓" : n}</span>
          <span>${t("imp.step" + n)}</span></div>`).join("");
    }

    function step1() {
      host.innerHTML = `<div class="card">
        <div class="card-head"><h3>1 · ${t("imp.step1")}</h3></div>
        <div class="grid c2">
          <div class="field"><label>${t("exp.entity")}</label>
            <select id="impEntity">${entities.map(e =>
              `<option value="${e.key}" ${st.entity === e.key ? "selected" : ""}>${esc(A.state.lang === "ar" ? e.plural_ar : e.plural_en)}</option>`).join("")}</select></div>
          <div class="field"><label>${t("exp.format")}</label>
            <select id="impFormat">
              <option value="xlsx" ${st.format === "xlsx" ? "selected" : ""}>XLSX</option>
              <option value="csv" ${st.format === "csv" ? "selected" : ""}>CSV</option>
              <option value="json" ${st.format === "json" ? "selected" : ""}>JSON</option>
            </select></div>
          <div class="field"><label>${t("exp.lang")}</label>
            <select id="impLang">
              <option value="ar" ${st.lang === "ar" ? "selected" : ""}>العربية</option>
              <option value="en" ${st.lang === "en" ? "selected" : ""}>English</option>
              <option value="both">AR + EN</option>
            </select></div>
        </div>
        <div class="notice">${t("imp.templateHint")}</div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn" id="dlTpl">${icon("download")} ${t("imp.downloadTemplate")}</button>
          <button class="btn primary" id="toStep2">${t("common.next")} →</button>
        </div></div>`;
      host.querySelector("#impEntity").onchange = (e) => { st.entity = e.target.value; };
      host.querySelector("#impFormat").onchange = (e) => { st.format = e.target.value; };
      host.querySelector("#impLang").onchange = (e) => { st.lang = e.target.value; };
      host.querySelector("#dlTpl").onclick = () => {
        A.download(`/api/import/template/${st.entity}?format=${st.format}&lang=${st.lang}`);
      };
      host.querySelector("#toStep2").onclick = () => { st.step = 2; paint(); };
    }

    function step2() {
      host.innerHTML = `<div class="card">
        <div class="card-head"><h3>2 · ${t("imp.step2")} — ${esc(A.pluralOf(st.entity))}</h3></div>
        <div class="dropzone" id="dz">
          <div class="big">⤒</div>
          <div>${t("imp.dropHint")}</div>
          <div class="small" style="margin-top:6px">${t("imp.formatNote")}</div>
          <input type="file" id="fileInput" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.json" style="display:none">
        </div>
        <div id="upResult" style="margin-top:12px"></div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn" id="back1">← ${t("common.back")}</button>
          <button class="btn primary" id="toStep3" disabled>${t("common.next")} →</button>
        </div></div>`;
      const dz = host.querySelector("#dz");
      const fi = host.querySelector("#fileInput");
      dz.onclick = () => fi.click();
      dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("hover"); };
      dz.ondragleave = () => dz.classList.remove("hover");
      dz.ondrop = (e) => {
        e.preventDefault(); dz.classList.remove("hover");
        if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
      };
      fi.onchange = () => { if (fi.files.length) upload(fi.files[0]); };
      async function upload(file) {
        const fd = new FormData();
        fd.append("entity", st.entity);
        fd.append("file", file);
        dz.innerHTML = `<div class="big">⏳</div><div>${t("common.loading")}</div>`;
        try {
          const res = await api.upload("/api/import/preview", fd);
          st.upload = res;
          st.mapping = Object.assign({}, res.mapping);
          st.filename = file.name;
          dz.innerHTML = `<div class="big">✓</div><div><b>${esc(file.name)}</b></div>
            <div class="small">${fmtNum(res.total_rows)} ${t("imp.rowsFound")} · ${res.columns.length} ${t("imp.columns")} · ${esc(res.format)}</div>`;
          host.querySelector("#toStep3").disabled = false;
          const warn = [];
          if (res.missing_required.length) warn.push(
            `${t("imp.missingRequired")}: <b>${res.missing_required.map(k => {
              const f = A.fieldsOf(st.entity).find(x => x.key === k); return esc(A.fieldLabelSafe(f));
            }).join(", ")}</b>`);
          if (res.unmapped_columns.length) warn.push(
            `${t("imp.unmapped")}: ${res.unmapped_columns.map(esc).join(", ")}`);
          const upRes = host.querySelector("#upResult");
          if (upRes) upRes.innerHTML = warn.length
            ? `<div class="notice warn">${warn.join("<br>")}</div>` : "";
        } catch (err) {
          dz.innerHTML = `<div class="big">✕</div><div>${esc(err.message)}</div>`;
        }
      }
      host.querySelector("#back1").onclick = () => { st.step = 1; paint(); };
      host.querySelector("#toStep3").onclick = () => { if (st.upload) { st.step = 3; paint(); } };
    }

    function step3() {
      const fields = A.fieldsOf(st.entity);
      const cols = st.upload.columns;
      const statuses = A.domainOptions("record_status");
      host.innerHTML = `<div class="card">
        <div class="card-head"><h3>3 · ${t("imp.step3")}</h3>
          <span class="card-sub">${fmtNum(st.upload.total_rows)} ${t("imp.rowsFound")}</span></div>
        <div class="split" style="gap:18px">
          <div>
            <div class="small muted" style="margin-bottom:6px">${t("imp.mappingHint")}</div>
            <div class="map-grid" id="mapGrid">
              ${cols.map(c => `<div class="map-row ${st.mapping[c] ? "" : "unmapped"}">
                <div class="col" title="${esc(c)}">${esc(A.truncate(c, 30))}</div>
                <select data-col="${esc(c)}">
                  <option value="">— ${t("common.none")} —</option>
                  ${fields.map(f => `<option value="${f.key}" ${st.mapping[c] === f.key ? "selected" : ""}>
                    ${esc(A.fieldLabelSafe(f))}</option>`).join("")}
                </select></div>`).join("")}
            </div>
          </div>
          <div>
            <div class="field"><label>${t("imp.mode")}</label>
              <select id="impMode">
                <option value="create" ${st.mode === "create" ? "selected" : ""}>${t("imp.mode.create")}</option>
                <option value="upsert" ${st.mode === "upsert" ? "selected" : ""}>${t("imp.mode.upsert")}</option>
                <option value="update_only" ${st.mode === "update_only" ? "selected" : ""}>${t("imp.mode.update_only")}</option>
              </select></div>
            <div class="field"><label>${t("imp.defaultStatus")}</label>
              <select id="impStatus">${statuses.map(s =>
                `<option value="${s.code}" ${st.status === s.code ? "selected" : ""}>${esc(A.state.lang === "ar" ? s.label_ar : s.label_en)}</option>`).join("")}</select></div>
            <div class="notice">${t("imp.dryRunNote")}</div>
            <div class="btn-row" style="margin-top:12px">
              <button class="btn" id="back2">← ${t("common.back")}</button>
              <button class="btn primary" id="validate">${icon("check")} ${t("imp.validate")}</button>
            </div>
          </div>
        </div>
        <div id="reportHost" style="margin-top:16px"></div></div>`;
      hydrateIcons(host);
      host.querySelectorAll("[data-col]").forEach(sel => {
        sel.onchange = () => {
          st.mapping[sel.dataset.col] = sel.value;
          sel.closest(".map-row").classList.toggle("unmapped", !sel.value);
        };
      });
      host.querySelector("#impMode").onchange = (e) => { st.mode = e.target.value; };
      host.querySelector("#impStatus").onchange = (e) => { st.status = e.target.value; };
      host.querySelector("#back2").onclick = () => { st.step = 2; paint(); };
      host.querySelector("#validate").onclick = async () => {
        const reportHost = host.querySelector("#reportHost");
        reportHost.innerHTML = `<div class="skeleton" style="width:50%"></div>`;
        try {
          const res = await api.post("/api/import/validate", {
            entity: st.entity, upload_id: st.upload.upload_id, filename: st.filename,
            mapping: st.mapping, mode: st.mode, default_status: st.status
          });
          st.report = res;
          reportHost.innerHTML = reportBlock(res, true);
          reportHost.querySelector("[data-commit]").onclick = async () => {
            try {
              const done = await api.post("/api/import/commit", {
                entity: st.entity, upload_id: st.upload.upload_id, filename: st.filename,
                mapping: st.mapping, mode: st.mode, default_status: st.status,
                reason: "import"
              });
              st.report = done;
              reportHost.innerHTML = reportBlock(done, false);
              toast(t("imp.committed"), "ok");
              loadJobs();
            } catch (err) { toast(err.message, "err", 7000); }
          };
        } catch (err) {
          reportHost.innerHTML = `<div class="notice err">${esc(err.message)}</div>`;
        }
      };
    }

    function reportBlock(r, dry) {
      const stat = (label, val, cls) => `<div class="kpi-mini"><div class="v" style="color:${cls || "inherit"}">${fmtNum(val)}</div>
        <div class="l">${label}</div></div>`;
      return `<div class="card" style="box-shadow:none">
        <div class="card-head"><h3>${t("imp.report")}</h3>
          <span class="badge ${r.failed ? "amber" : "green"}">${dry ? "dry run" : "committed"}</span></div>
        <div class="grid c4">
          ${stat(t("imp.willCreate"), r.created, "var(--green)")}
          ${stat(t("imp.willUpdate"), r.updated, "var(--ink-600)")}
          ${stat(t("imp.willFail"), r.failed, "var(--red)")}
          ${stat(t("common.total"), r.total)}
        </div>
        ${r.errors && r.errors.length ? `<div style="margin-top:12px">
          <div class="small" style="margin-bottom:6px"><b>${t("imp.rowErrors")}</b></div>
          <div class="table-wrap scroll-y"><table class="data compact"><thead><tr>
            <th>#</th><th>${t("log.field")}</th><th>${t("common.error")}</th></tr></thead><tbody>
            ${r.errors.slice(0, 100).map(e => `<tr><td class="num">${e.row}</td>
              <td class="mono-cell">${esc(e.field || "—")}</td><td>${esc(e.message)}</td></tr>`).join("")}
          </tbody></table></div></div>` : ""}
        <div class="btn-row" style="margin-top:12px">
          ${dry && r.failed < r.total ? `<button class="btn gold" data-commit>${icon("check")} ${t("imp.commit")}</button>` : ""}
          <button class="btn" id="again">${t("imp.startOver")}</button>
          <a class="btn" href="#/entity/${st.entity}">${t("common.view")} →</a>
        </div></div>`;
    }

    async function loadJobs() {
      const jobs = await api.get("/api/import/jobs?limit=12");
      if (!A.fresh(root)) return;
      root.querySelector("#jobsCard").innerHTML = `<div class="card-head"><h3>${t("imp.jobs")}</h3></div>
        ${jobs.length ? `<div class="table-wrap"><table class="data compact"><thead><tr>
          <th>${t("log.when")}</th><th>${t("log.entity")}</th><th>${t("exp.format")}</th>
          <th>${t("imp.mode")}</th><th class="num">+</th><th class="num">↻</th>
          <th class="num">✕</th><th>${t("common.status")}</th><th>${t("log.actor")}</th></tr></thead><tbody>
          ${jobs.map(j => `<tr>
            <td class="small nowrap">${esc(A.fmtDate(j.started_at, true))}</td>
            <td>${esc(A.label(j.entity_type))}</td>
            <td>${esc(j.format || "")}</td>
            <td class="small">${esc(j.mode)}${j.dry_run ? " · dry" : ""}</td>
            <td class="num">${fmtNum(j.created_rows)}</td>
            <td class="num">${fmtNum(j.updated_rows)}</td>
            <td class="num">${fmtNum(j.failed_rows)}</td>
            <td>${A.badge(j.status, j.failed_rows ? "amber" : "green")}</td>
            <td class="small">${esc(j.actor || "")}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty small">${t("list.noRecords")}</div>`}`;
    }

    function paint() {
      paintSteps();
      if (st.step === 1) step1();
      else if (st.step === 2) step2();
      else step3();
      hydrateIcons(host);
      const again = host.querySelector("#again");
      if (again) again.onclick = () => { st = { step: 1, entity: st.entity, format: "xlsx",
        lang: A.state.lang, upload: null, mapping: {}, mode: "create", status: "in_review", report: null };
        paint(); };
    }
    paint();
    loadJobs();
  };

  /* ============================================================ EXPORT === */
  A.views.export = async function (root) {
    A.crumbs([{ label: t("nav.export") }]);
    const entities = A.state.meta.entities || [];
    root.innerHTML = A.pageHead(t("exp.title"), t("exp.subtitle"), "");
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="grid c3">
        <div class="field"><label>${t("exp.entity")}</label>
          <select id="exE">${entities.map(e =>
            `<option value="${e.key}">${esc(A.state.lang === "ar" ? e.plural_ar : e.plural_en)}</option>`).join("")}</select></div>
        <div class="field"><label>${t("exp.format")}</label>
          <select id="exF"><option value="xlsx">XLSX</option><option value="csv">CSV</option>
            <option value="tsv">TSV</option><option value="json">JSON</option></select></div>
        <div class="field"><label>${t("exp.lang")}</label>
          <select id="exL"><option value="ar">العربية</option><option value="en">English</option>
            <option value="both">AR + EN</option></select></div>
      </div>
      <label class="check" style="margin-bottom:10px"><input type="checkbox" id="exR" checked> ${t("exp.resolve")}</label>
      <div class="field"><label>${t("exp.filters")}</label>
        <textarea id="exFilters" rows="4" style="font-family:var(--mono);font-size:.8rem">{"where":[],"logic":"and","include_deleted":false}</textarea>
        <div class="hint">${A.state.lang === "ar"
          ? 'مثال: {"where":[{"field":"nationality_id","op":"eq","value":2}],"logic":"and"}'
          : 'Example: {"where":[{"field":"nationality_id","op":"eq","value":2}],"logic":"and"}'}</div></div>
      <div class="field"><label>${t("exp.columns")}</label>
        <div class="flex wrap" id="exCols"></div></div>
      <div class="notice">${t("exp.note")}</div>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn primary gold" id="exGo">${icon("download")} ${t("exp.run")}</button>
      </div>`;
    root.appendChild(card);
    hydrateIcons(root);
    function paintCols() {
      const fields = A.fieldsOf(card.querySelector("#exE").value);
      card.querySelector("#exCols").innerHTML = fields.map(f => `
        <label class="check" style="min-width:150px"><input type="checkbox" data-c="${f.key}"
          ${f.in_list ? "checked" : ""}> ${esc(A.fieldLabelSafe(f))}</label>`).join("");
    }
    paintCols();
    card.querySelector("#exE").onchange = paintCols;
    card.querySelector("#exGo").onclick = async () => {
      let filters = {};
      try { filters = JSON.parse(card.querySelector("#exFilters").value || "{}"); }
      catch (e) { return toast("Invalid JSON", "err"); }
      const columns = Array.from(card.querySelectorAll("[data-c]:checked")).map(c => c.dataset.c);
      const res = await fetch(`/api/export/${card.querySelector("#exE").value}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Actor": A.state.actor },
        body: JSON.stringify({
          format: card.querySelector("#exF").value, columns,
          lang: card.querySelector("#exL").value,
          resolve: card.querySelector("#exR").checked, filters
        })
      });
      if (!res.ok) return toast(await res.text(), "err");
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const nm = (cd.match(/filename="?([^";]+)"?/) || [])[1] || "export";
      const url = URL.createObjectURL(blob);
      A.download(url); setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast(t("common.export") + " ✓", "ok");
    };
  };

  /* ========================================================= CHANGE LOG === */
  A.views.changelog = async function (root) {
    A.crumbs([{ label: t("nav.changelog") }]);
    root.innerHTML = A.pageHead(t("adm.changelog"), t("adm.changelogHint"), "")
      + `<div class="card tight">
          <div class="toolbar">
            <select class="ghost-select" id="lgEntity"><option value="">${t("log.entity")}: ${t("common.all")}</option>
              ${(A.state.meta.entities || []).map(e => `<option value="${e.key}">${esc(A.pluralOf(e.key))}</option>`).join("")}</select>
            <select class="ghost-select" id="lgAction"><option value="">${t("log.action")}: ${t("common.all")}</option>
              ${["create", "update", "delete", "restore", "import"].map(a => `<option>${a}</option>`).join("")}</select>
            <input class="ghost-select" id="lgActor" placeholder="${t("log.actor")}" style="width:130px">
            <div class="search-box" style="max-width:260px">${icon("search")}
              <input id="lgQ" placeholder="${t("common.search")}"></div>
            <span class="spacer"></span>
            <button class="btn sm" id="lgGo">${t("common.refresh")}</button>
          </div>
          <div id="logTable"></div></div>`;
    hydrateIcons(root);
    let page = 1;
    async function load() {
      const p = new URLSearchParams({ page: String(page), page_size: "50" });
      ["lgEntity", "lgAction"].forEach(id => {
        const v = root.querySelector("#" + id).value; if (v) p.set(id === "lgEntity" ? "entity_type" : "action", v);
      });
      const actor = root.querySelector("#lgActor").value; if (actor) p.set("actor", actor);
      const q = root.querySelector("#lgQ").value; if (q) p.set("q", q);
      const res = await api.get(`/api/changelog?${p.toString()}`);
      if (!root.querySelector("#logTable")) return;
      root.querySelector("#logTable").innerHTML = `<div class="table-wrap" style="border:0">
        <table class="data compact"><thead><tr>
          <th>${t("log.when")}</th><th>${t("log.entity")}</th><th>${t("common.code")}</th>
          <th>${t("log.action")}</th><th>${t("log.field")}</th><th>${t("rec.oldValue")}</th>
          <th>${t("rec.newValue")}</th><th>${t("log.actor")}</th><th>${t("common.reason")}</th>
        </tr></thead><tbody>
        ${res.items.map(r => `<tr>
          <td class="small nowrap" title="${esc(r.changed_at)}">${esc(A.ago(r.changed_at))}</td>
          <td>${esc(A.label(r.entity_type))}</td>
          <td class="mono-cell">${esc(r.entity_code || (r.entity_id ? "#" + r.entity_id : "—"))}</td>
          <td>${A.badge(r.action, { create: "green", update: "blue", delete: "red", restore: "teal" }[r.action] || "gray")}</td>
          <td class="small">${esc(r.field_label || r.field_key || "—")}</td>
          <td class="small muted">${esc(A.truncate(r.old_value || "", 34))}</td>
          <td class="small">${esc(A.truncate(r.new_value || "", 34))}</td>
          <td class="small">${esc(r.actor || "—")}</td>
          <td class="small muted">${esc(A.truncate(r.reason || r.notes || "", 40))}</td>
        </tr>`).join("") || `<tr><td colspan="9" class="empty">${t("list.noRecords")}</td></tr>`}
        </tbody></table></div>
        <div class="pager"><span class="info">${fmtNum(res.total)} ${t("common.records")}</span>
          <span class="spacer"></span>
          <div class="pages"><button data-p="${page - 1}" ${page <= 1 ? "disabled" : ""}>‹</button>
            <button class="active">${page}</button>
            <button data-p="${page + 1}" ${page >= res.pages ? "disabled" : ""}>›</button></div></div>`;
      root.querySelectorAll("[data-p]").forEach(b => {
        b.onclick = () => { page = Math.max(1, Number(b.dataset.p)); load(); };
      });
    }
    root.querySelector("#lgGo").onclick = () => { page = 1; load(); };
    root.querySelector("#lgQ").onkeydown = (e) => { if (e.key === "Enter") { page = 1; load(); } };
    ["lgEntity", "lgAction"].forEach(id => root.querySelector("#" + id).onchange = () => { page = 1; load(); });
    await load();
  };

  /* ========================================================= VOCABULARIES === */
  A.views.vocabularies = async function (root) {
    A.crumbs([{ label: t("nav.vocabularies") }]);
    const domains = await api.get("/api/lookup-domains");
    root.innerHTML = A.pageHead(t("adm.vocab"), t("adm.vocabHint"),
      `<button class="btn primary" id="addVal">${icon("plus")} ${t("adm.addValue")}</button>`)
      + `<div class="split">
          <div class="card tight"><div class="toolbar">
            <div class="search-box" style="max-width:280px">${icon("search")}
              <input id="vocQ" placeholder="${t("common.search")}"></div>
            <span class="spacer"></span><span class="small muted">${domains.length} ${A.t("ui.lists")}</span>
          </div><div id="vocTable"></div></div>
          <div class="card" id="domainInfo"></div>
        </div>`;
    hydrateIcons(root);
    let active = domains[0] ? domains[0].domain : "record_status";
    function paintDomains(filter) {
      const list = domains.filter(d => !filter ||
        (d.domain + " " + d.label_en + " " + d.label_ar).toLowerCase().includes(filter.toLowerCase()));
      if (!root.querySelector("#domainInfo")) return;
      root.querySelector("#vocTable").innerHTML = `<div class="table-wrap" style="border:0">
        <table class="data compact"><thead><tr>
          <th>${t("log.entity")}</th><th>${A.t("ui.label")}</th>
          <th class="num">${t("common.values")}</th></tr></thead><tbody>
          ${list.map(d => `<tr class="${d.domain === active ? "selected" : ""}" data-dom="${d.domain}" style="cursor:pointer">
            <td class="mono-cell">${esc(d.domain)}</td>
            <td>${esc(A.state.lang === "ar" ? d.label_ar : d.label_en)}</td>
            <td class="num">${fmtNum(d.n)}</td></tr>`).join("")}
        </tbody></table></div>`;
      root.querySelectorAll("[data-dom]").forEach(tr => {
        tr.onclick = () => { active = tr.dataset.dom; paintDomains(filter); paintValues(); };
      });
    }
    const PARENT_OF = { governorate: "country", district: "governorate" };
    function parentLabel(v) {
      if (!v.parent_id) return "—";
      const hit = A.lookupById(v.parent_id);
      if (!hit) return `#${v.parent_id}`;
      return A.state.lang === "ar" ? (hit.label_ar || hit.label_en) : (hit.label_en || hit.label_ar);
    }
    async function paintValues() {
      const values = await api.get(`/api/lookups?domain=${active}&include_inactive=true`);
      const d = domains.find(x => x.domain === active) || {};
      const parentDomain = PARENT_OF[active];
      root.querySelector("#domainInfo").innerHTML = `
        <div class="card-head"><h3>${esc(A.state.lang === "ar" ? d.label_ar : d.label_en)}</h3>
          <span class="mono-cell small muted">${esc(active)}</span></div>
        <div class="table-wrap scroll-y"><table class="data compact"><thead><tr>
          <th>${t("adm.code")}</th><th>${t("adm.labelEn")}</th><th>${t("adm.labelAr")}</th>
          ${parentDomain ? `<th>${esc(t("adm.parent") || "Parent")}</th>` : ""}
          <th class="num">${t("adm.order")}</th><th>${t("adm.active")}</th><th></th></tr></thead><tbody>
          ${values.map(v => `<tr data-v="${v.id}">
            <td class="mono-cell">${esc(v.code)}</td>
            <td contenteditable="true" data-f="label_en">${esc(v.label_en)}</td>
            <td contenteditable="true" data-f="label_ar" dir="rtl">${esc(v.label_ar)}</td>
            ${parentDomain ? `<td class="small">${esc(parentLabel(v))}</td>` : ""}
            <td class="num" contenteditable="true" data-f="sort_order">${v.sort_order}</td>
            <td>${v.is_active ? A.badge(t("common.yes"), "green") : A.badge(t("common.no"), "gray")}</td>
            <td class="nowrap">
              <button class="icon-btn" data-save="${v.id}" title="${t("common.save")}">${icon("save")}</button>
              <button class="icon-btn" data-off="${v.id}" title="${t("adm.deactivate")}">${icon("x")}</button>
            </td></tr>`).join("")}
        </tbody></table></div>
        <div class="small muted" style="margin-top:8px">${A.t("ui.labelsAndOrderAreEditableDirectlyInThe")}</div>`;
      hydrateIcons(root.querySelector("#domainInfo"));
      root.querySelectorAll("[data-save]").forEach(b => {
        b.onclick = async () => {
          const tr = b.closest("[data-v]");
          const payload = {};
          tr.querySelectorAll("[data-f]").forEach(td => {
            payload[td.dataset.f] = td.dataset.f === "sort_order" ? Number(td.textContent) : td.textContent;
          });
          try {
            await api.put(`/api/lookups/${b.dataset.save}`, payload);
            toast(t("common.saved"), "ok");
          } catch (err) { toast(err.message, "err"); }
        };
      });
      root.querySelectorAll("[data-off]").forEach(b => {
        b.onclick = async () => {
          if (!confirm(t("common.confirm") + "?")) return;
          await api.del(`/api/lookups/${b.dataset.off}`);
          paintValues();
        };
      });
    }
    root.querySelector("#vocQ").oninput = (e) => paintDomains(e.target.value);
    root.querySelector("#addVal").onclick = () => {
      function parentFieldHtml(domain) {
        const parentDomain = PARENT_OF[domain];
        if (!parentDomain) return "";
        const parentOpts = A.domainOptions(parentDomain) || [];
        const parentLabelTxt = A.state.lang === "ar"
          ? ((domains.find(x => x.domain === parentDomain) || {}).label_ar || parentDomain)
          : ((domains.find(x => x.domain === parentDomain) || {}).label_en || parentDomain);
        return `<div class="field span2" id="avParentWrap"><label>${esc(t("adm.parent") || "Parent")}
          (${esc(parentLabelTxt)})</label>
          <select id="avParent"><option value="">${esc(t("common.select"))}</option>
            ${parentOpts.map(o => `<option value="${o.id}">${esc(A.state.lang === "ar"
              ? (o.label_ar || o.label_en) : (o.label_en || o.label_ar))}
              (${esc(o.code)})</option>`).join("")}
          </select></div>`;
      }
      const body = `<div class="grid c2">
        <div class="field"><label>${t("log.entity")}</label><select id="avDomain">
          ${domains.map(d => `<option value="${d.domain}" ${d.domain === active ? "selected" : ""}>
            ${esc(A.state.lang === "ar" ? d.label_ar : d.label_en)}</option>`).join("")}</select></div>
        <div class="field"><label>${t("adm.code")}</label><input id="avCode" placeholder="my_code"></div>
        <div class="field"><label>${t("adm.labelEn")}</label><input id="avEn"></div>
        <div class="field"><label>${t("adm.labelAr")}</label><input id="avAr" dir="rtl"></div>
        <div id="avParentSlot">${parentFieldHtml(active)}</div>
        <div class="field"><label>${t("adm.order")}</label><input id="avOrder" type="number" value="100"></div>
        <div class="field"><label>${t("adm.color")}</label><select id="avColor">
          ${["green", "blue", "indigo", "amber", "orange", "red", "rose", "teal", "violet", "gray", "slate"]
            .map(c => `<option value="${c}">${c}</option>`).join("")}</select></div>
      </div>`;
      const dlg = A.modal({
        title: t("adm.addValue"), body, size: "slim",
        buttons: [{ label: t("common.cancel") },
          { label: t("common.save"), cls: "primary", onClick: async (close, b) => {
              try {
                const domain = b.querySelector("#avDomain").value;
                const parentEl = b.querySelector("#avParent");
                const needParent = !!PARENT_OF[domain];
                if (needParent && (!parentEl || !parentEl.value)) {
                  return toast(t("adm.parentRequired") || t("common.required"), "warn");
                }
                await api.post("/api/lookups", {
                  domain,
                  code: b.querySelector("#avCode").value,
                  label_en: b.querySelector("#avEn").value,
                  label_ar: b.querySelector("#avAr").value,
                  sort_order: Number(b.querySelector("#avOrder").value),
                  color: b.querySelector("#avColor").value,
                  parent_id: parentEl && parentEl.value ? Number(parentEl.value) : null
                });
                close();
                App.state.meta = await api.get(`/api/meta?lang=${A.state.lang}`);
                A.rerender();
              } catch (err) { toast(err.message, "err"); }
            } }]
      });
      const domainSel = dlg.body.querySelector("#avDomain");
      if (domainSel) {
        domainSel.onchange = () => {
          const slot = dlg.body.querySelector("#avParentSlot");
          if (slot) slot.innerHTML = parentFieldHtml(domainSel.value);
        };
      }
    };
    paintDomains();
    paintValues();
  };

  /* =========================================================== NUMBERING === */
  A.views.numbering = async function (root) {
    A.crumbs([{ label: t("nav.numbering") }]);
    const seqs = await api.get("/api/sequences");
    root.innerHTML = A.pageHead(t("adm.numbering"), t("adm.numberingHint"), "")
      + `<div class="grid c2">${seqs.map(s => `
        <div class="card" data-seq="${s.entity_type}">
          <div class="card-head"><h3>${esc(A.pluralOf(s.entity_type))}</h3>
            <span class="mono-cell badge gray">${esc(s.preview)}</span></div>
          <div class="grid c2">
            <div class="field"><label>${t("adm.prefix")}</label><input data-k="prefix" value="${esc(s.prefix)}"></div>
            <div class="field"><label>${t("adm.separator")}</label><input data-k="separator" value="${esc(s.separator)}"></div>
            <div class="field"><label>${t("adm.suffix")}</label><input data-k="suffix" value="${esc(s.suffix || "")}"></div>
            <div class="field"><label>${t("adm.padding")}</label><input data-k="padding" type="number" value="${s.padding}"></div>
            <div class="field"><label>${t("adm.nextValue")}</label><input data-k="next_value" type="number" value="${s.next_value}"></div>
            <div class="field"><label>${t("adm.resetPolicy")}</label>
              <select data-k="reset_policy">
                ${["never", "yearly", "monthly"].map(p => `<option ${s.reset_policy === p ? "selected" : ""}>${p}</option>`).join("")}
              </select></div>
          </div>
          <div class="field"><label>${t("adm.template")}</label>
            <input data-k="template" value="${esc(s.template || "{prefix}{sep}{number}{suffix}")}" class="mono-cell">
            <div class="hint">{prefix} {sep} {number} {suffix}</div></div>
          <div class="btn-row">
            <button class="btn sm primary" data-saveseq>${icon("save")} ${t("common.save")}</button>
            <span class="small muted">${t("adm.preview")}: <b data-preview>${esc(s.preview)}</b></span>
            <span class="spacer"></span>
            <span class="small muted">${t("adm.inUse")}: ${fmtNum(s.in_use)}</span>
          </div>
        </div>`).join("")}</div>`;
    hydrateIcons(root);
    root.querySelectorAll("[data-saveseq]").forEach(b => {
      b.onclick = async () => {
        const card = b.closest("[data-seq]");
        const payload = {};
        card.querySelectorAll("[data-k]").forEach(el => {
          payload[el.dataset.k] = ["padding", "next_value"].includes(el.dataset.k)
            ? Number(el.value) : el.value;
        });
        try {
          const res = await api.put(`/api/sequences/${card.dataset.seq}`, payload);
          card.querySelector("[data-preview]").textContent = res.next_preview;
          toast(t("common.saved"), "ok");
        } catch (err) { toast(err.message, "err"); }
      };
    });
  };

  /* ------------------------------------------------- data-entry surface --- */
  /**
   * The one preference that changes the shape of the whole application, so it
   * gets a real control rather than a line in a key/value dump:
   *   · three modes, each with a miniature of what it looks like;
   *   · two scopes — "everyone" (the instance default, admin only) and "me"
   *     (a personal override on this device);
   *   · an immediate effect and a way back to the instance default.
   */
  const FORM_MODES = [
    { code: "page", label: "adm.formModePage", hint: "adm.formModePageHint" },
    { code: "dialog", label: "adm.formModeDialog", hint: "adm.formModeDialogHint" },
    { code: "auto", label: "adm.formModeAuto", hint: "adm.formModeAutoHint" }
  ];

  function modePreview(mode) {
    const dialog = mode === "dialog" || mode === "auto";
    return `<div class="mode-preview ${mode}" aria-hidden="true">
        <div class="mp-page">
          <div class="mp-bar"></div>
          <div class="mp-rows">${"<i></i>".repeat(4)}</div>
          ${dialog ? `<div class="mp-dialog ${mode === "auto" ? "auto" : ""}">
              <div class="mp-dialog-head"></div><div class="mp-dialog-body"></div>
              <div class="mp-dialog-foot"></div></div>` : `<div class="mp-form">
              <div class="mp-field"></div><div class="mp-field"></div><div class="mp-field wide"></div>
              <div class="mp-dialog-foot"></div></div>`}
        </div>
      </div>`;
  }

  function surfaceCard(settings) {
    const instance = A.setting("ui.form_mode", "page");
    const personal = A.pref("form_mode", "default");
    const width = A.pref("form_dialog_size", "default");
    const resolved = A.formMode();
    /* what is actually in force: the personal override, or the instance default */
    const effective = personal === "default" ? instance : personal;
    return `<div class="card" id="surfaceCard">
        <div class="card-head">
          <h3>${icon("sliders")} ${esc(t("adm.formModeTitle"))}</h3>
          <span class="pill">${esc(t("adm.formModeActive"))}: ${esc(t("adm.formMode." + resolved))}</span>
        </div>
        <p class="muted small" style="margin-top:-6px">${esc(t("adm.formModeIntro"))}</p>

        <div class="mode-grid" role="radiogroup" aria-label="${esc(t("adm.formModeTitle"))}">
          ${FORM_MODES.map(m => `
            <button type="button" class="mode-card ${effective === m.code ? "selected" : ""}"
                    data-form-mode="${m.code}" role="radio"
                    aria-checked="${effective === m.code}">
              ${modePreview(m.code)}
              <b>${esc(t(m.label))}</b>
              <span class="small muted">${esc(t(m.hint))}</span>
            </button>`).join("")}
        </div>

        <div class="surface-row">
          <div class="field">
            <label>${esc(t("adm.formModeScope"))}</label>
            <div class="seg" role="group">
              <button class="seg-btn ${personal === "default" ? "active" : ""}" data-scope="default">
                ${esc(t("adm.formModeInstance"))}</button>
              <button class="seg-btn ${personal !== "default" ? "active" : ""}" data-scope="personal">
                ${esc(t("adm.formModePersonal"))}</button>
            </div>
            <div class="hint" id="scopeHint">
              ${personal === "default"
                ? esc(t("adm.formModeFollowingInstance", { value: t("adm.formMode." + instance) }))
                : esc(t("adm.formModeOverridingInstance", { value: t("adm.formMode." + instance) }))}
            </div>
          </div>
          <div class="field" id="sizeField" ${A.formMode() === "page" ? "hidden" : ""}>
            <label>${esc(t("adm.formDialogSize"))}</label>
            <select id="dialogSize">
              <option value="default" ${width === "default" ? "selected" : ""}>${esc(t("adm.configDefault") + " · " + t("adm.formDialogSize." + A.setting("ui.form_dialog_size", "xl")))}</option>
              <option value="wide" ${width === "wide" ? "selected" : ""}>${esc(t("adm.formDialogSize.wide"))}</option>
              <option value="xl" ${width === "xl" ? "selected" : ""}>${esc(t("adm.formDialogSize.xl"))}</option>
            </select>
            <div class="hint">${esc(t("adm.formDialogSizeHint"))}</div>
          </div>
          <div class="field">
            <label>${esc(t("adm.formModeTry"))}</label>
            <button class="btn sm" id="tryForm" data-try-form>
              ${icon("plus")} ${esc(t("adm.formModeTryButton"))}</button>
            <div class="hint">${esc(t("adm.formModeTryHint"))}</div>
          </div>
        </div>

      </div>`;
  }

  function wireSurfaceCard(root) {
    const card = root.querySelector("#surfaceCard");
    if (!card) return;
    /* One decision, one place.  The scope says *who* the choice is for:
       "everyone" writes the audited instance setting (`ui.form_mode`, through the
       same validated API the registry uses), "me" writes the personal preference
       in this browser.  A choice is never written twice or half-way. */
    const mine = () => A.pref("form_mode", "default") !== "default";

    /* the instance value goes to the server and into the cached meta, so
       `A.setting()` and `A.formMode()` see it without a reload */
    async function setInstance(key, value) {
      try {
        await api.put("/api/settings", { [key]: value });
        A.state.meta.settings = Object.assign({}, A.state.meta.settings, { [key]: String(value) });
        toast(t("common.saved"), "ok");
      } catch (err) {
        toast(err.message, "err", 6000);
      }
      A.rerender();
    }

    const apply = (mode) => {
      if (mine()) {
        A.setPref("form_mode", mode);
        A.rerender();
        toast(t("adm.formModeSaved", { value: t("adm.formMode." + mode) }), "ok", 2600);
      } else {
        setInstance("ui.form_mode", mode);
      }
    };
    card.querySelectorAll("[data-form-mode]").forEach(btn => {
      btn.onclick = () => apply(btn.dataset.formMode);
    });
    card.querySelectorAll("[data-scope]").forEach(btn => {
      btn.onclick = () => {
        if (btn.dataset.scope === "personal") {
          /* start from what everyone has, so the override is a visible change */
          A.setPref("form_mode", A.setting("ui.form_mode", "page"));
          A.rerender();
        } else {
          A.setPref("form_mode", "default");
          A.rerender();
          toast(t("adm.formModeFollowingInstance",
                  { value: t("adm.formMode." + A.setting("ui.form_mode", "page")) }), "ok", 2600);
        }
      };
    });
    const size = card.querySelector("#dialogSize");
    if (size) size.onchange = () => {
      const chosen = size.value === "default" ? A.setting("ui.form_dialog_size", "xl") : size.value;
      if (mine()) {
        A.setPref("form_dialog_size", size.value);
        A.rerender();
      } else {
        setInstance("ui.form_dialog_size", chosen);
      }
    };
    const tryBtn = card.querySelector("[data-try-form]");
    if (tryBtn) tryBtn.onclick = () => {
      const entity = (A.state.meta.entities || [])[0];
      /* come back here when the trial form is dismissed */
      A.forms.open(entity.key, null, { returnTo: "#/settings" });
    };
  }

  /* ============================================================ SETTINGS === */
  /* ========================================================== SETTINGS === */
  /* The screen is generated from the registry the API serves, so a setting
     cannot exist in the backend and be missing here — and nothing here can
     invent a key the backend would refuse. */

  const PREF_OF = {                         // setting key → personal preference name
    "map.provider": "map_provider",
    "display.theme": "theme",
    "display.density": "density",
    "display.page_size": "page_size",
    "display.default_language": "language",
    "ui.form_mode": "form_mode",
    "ui.form_dialog_size": "form_dialog_size",
    "ui.inline_create": "inline_create",
    "search.min_chars": "search_min_chars",
    "search.results_limit": "search_results_limit"
  };

  function settingValue(field, value) {
    if (String(value) === "true") return t("common.on");
    if (String(value) === "false") return t("common.off");
    const choice = (field.choices || []).find(c => String(c.value) === String(value));
    if (choice) return A.state.lang === "ar" ? choice.label_ar : choice.label_en;
    const key = `adm.value.${field.key.replace(/\./g, "_")}.${value}`;
    const label = t(key);
    return label === key ? String(value) : label;
  }

  function settingControl(f, value) {
    const id = `cfg-${f.key.replace(/\./g, "-")}`;
    if (f.kind === "bool") {
      return `<label class="cfg-switch">
          <input type="checkbox" id="${id}" data-set="${esc(f.key)}" data-kind="bool"
                 ${String(value) === "true" ? "checked" : ""}>
          <span class="cfg-track"><span class="cfg-knob"></span></span>
          <span class="cfg-on">${esc(t("common.on"))}</span><span class="cfg-off">${esc(t("common.off"))}</span>
        </label>`;
    }
    if (f.kind === "enum") {
      const option = (v) =>
        `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(settingValue(f, v))}</option>`;
      const choices = f.choices || [];
      const groups = f.choice_groups || [];
      if (choices.length && groups.length) {
        const body = groups.map(g => {
          const members = choices.filter(c => c.group === g.id).map(c => option(c.value)).join("");
          const label = A.state.lang === "ar" ? g.label_ar : g.label_en;
          return members ? `<optgroup label="${esc(label)}">${members}</optgroup>` : "";
        }).join("");
        return `<select class="ghost-select" id="${id}" data-set="${esc(f.key)}" data-kind="enum">${body}</select>`;
      }
      return `<select class="ghost-select" id="${id}" data-set="${esc(f.key)}" data-kind="enum">
          ${(f.values || []).map(option).join("")}
        </select>`;
    }
    if (f.kind === "int") {
      return `<input type="number" class="cfg-number" id="${id}" data-set="${esc(f.key)}" data-kind="int"
                value="${esc(value)}" ${f.minimum !== null ? `min="${f.minimum}"` : ""}
                ${f.maximum !== null ? `max="${f.maximum}"` : ""}>
              <span class="small muted" dir="ltr">${f.minimum !== null ? esc(fmtNum(f.minimum)) : "—"}
                – ${f.maximum !== null ? esc(fmtNum(f.maximum)) : "—"}</span>`;
    }
    return `<input type="text" id="${id}" data-set="${esc(f.key)}" value="${esc(value)}">`;
  }

  function settingRow(f, lang) {
    const isDefault = String(f.value) === String(f.default);
    const label = lang === "ar" ? f.label_ar : f.label_en;
    const help = lang === "ar" ? f.help_ar : f.help_en;
    const pref = PREF_OF[f.key];
    const personal = pref ? A.pref(pref, "default") : "default";
    return `<div class="cfg-row" data-row="${esc(f.key)}">
        <div class="cfg-label">
          <label class="cfg-name" for="cfg-${f.key.replace(/\./g, "-")}">${esc(label)}</label>
          <div class="cfg-key mono-cell" dir="ltr">${esc(f.key)}</div>
          <div class="small muted cfg-help">${esc(help)}</div>
          <div class="cfg-meta small muted">
            <span>${esc(t("adm.configUsedBy"))} <span class="mono-cell" dir="ltr">${esc(f.effect || "—")}</span></span>
            ${f.requires === "restart" ? `<span class="badge amber">${esc(t("adm.configRestart"))}</span>` : ""}
          </div>
        </div>
        <div class="cfg-control">
          <div class="cfg-input">${settingControl(f, f.value)}</div>
          <div class="cfg-badges">
            <span class="badge ${isDefault ? "gray" : "blue"}" data-badge="${esc(f.key)}">
              ${esc(isDefault ? t("adm.configDefault") : t("adm.configInstance"))}</span>
            <span class="small muted">${esc(t("adm.configDefaultValue"))}: <b>${esc(settingValue(f, f.default))}</b></span>
            ${isDefault ? "" : `<button type="button" class="btn ghost sm" data-reset="${esc(f.key)}"
                title="${esc(t("adm.configReset"))}">${icon("undo")} ${esc(t("adm.configReset"))}</button>`}
            ${f.personal ? `<button type="button" class="btn ghost sm" data-mine="${esc(f.key)}"
                title="${esc(t("adm.configAsMineHint"))}">${icon("user")} ${esc(personal === "default"
                  ? t("adm.configAsMine") : t("adm.configMine", { value: personal }))}</button>` : ""}
          </div>
        </div>
      </div>`;
  }

  function settingGroups(doc, lang) {
    return doc.groups.map(g => {
      const fields = doc.fields.filter(f => f.group === g.key);
      if (!fields.length) return "";
      const changed = fields.filter(f => String(f.value) !== String(f.default)).length;
      return `<div class="card cfg-card" data-group="${esc(g.key)}">
          <div class="card-head">
            <h3>${icon(g.icon || "sliders")} ${esc(lang === "ar" ? g.label_ar : g.label_en)}</h3>
            <span class="spacer"></span>
            <span class="pill small">${fields.length} ${esc(t("adm.configKeys"))}</span>
            ${changed ? `<button type="button" class="btn ghost sm" data-reset-group="${esc(g.key)}">
                ${icon("undo")} ${esc(t("adm.configResetGroup"))}</button>` : ""}
          </div>
          ${fields.map(f => settingRow(f, lang)).join("")}
        </div>`;
    }).join("");
  }

  A.views.settings = async function (root) {
    A.crumbs([{ label: t("nav.settings") }]);
    const lang = A.state.lang;
    const [doc, users, locales, meta] = await Promise.all([
      api.get("/api/settings"), api.get("/api/users"), api.get("/api/locales"),
      Promise.resolve(A.state.meta)
    ]);
    const initial = Object.assign({}, doc.settings);

    root.innerHTML = A.pageHead(t("adm.settings"), t("adm.settingsHint"), `
        <div class="btn-row">
          <button class="btn ghost" id="cfgDownload">${icon("download")} ${t("adm.configDownload")}</button>
          <button class="btn" id="cfgResetAll">${icon("undo")} ${t("adm.configResetAll")}</button>
          <button class="btn primary" id="cfgSave" disabled>${icon("save")} ${t("common.save")}</button>
        </div>`)
      + `<div class="cfg-bar" id="cfgBar" hidden>
          <span class="badge amber" id="cfgCount"></span>
          <span class="small muted">${esc(t("adm.configPendingHint"))}</span>
          <span class="spacer"></span>
          <span class="small muted mono-cell" id="cfgDiff"></span>
        </div>
        <div id="cfgProblems"></div>
        <div class="stack" style="margin-bottom:16px">${surfaceCard(doc.settings)}</div>
        <div class="stack cfg-groups">${settingGroups(doc, lang)}</div>
        <div class="split" style="margin-top:16px">
          <div class="card"><div class="card-head"><h3>${icon("users")} ${t("adm.users")}</h3></div>
            <table class="data compact"><thead><tr><th>${t("common.name")}</th><th>${t("log.actor")}</th>
              <th>${t("common.status")}</th></tr></thead><tbody>
              ${users.map(u => `<tr><td>${esc(u.display_name)}</td>
                <td class="mono-cell">${esc(u.username)}</td>
                <td>${A.badge(u.role, u.is_active ? "green" : "gray")}</td></tr>`).join("")}
            </tbody></table>
            <div class="btn-row" style="margin-top:10px">
              <input id="nuName" placeholder="username" style="max-width:130px;padding:6px 8px;border:1px solid var(--border-strong);border-radius:8px">
              <select id="nuRole" class="ghost-select">
                ${["viewer", "researcher", "reviewer", "admin"].map(r => `<option>${r}</option>`).join("")}</select>
              <button class="btn sm" id="nuAdd">${t("common.add")}</button>
            </div>
            <div class="small muted" style="margin-top:8px">${esc(t("adm.usersHint"))}</div>
          </div>
          <div class="stack">
            <div class="card"><div class="card-head"><h3>${icon("globe")} ${t("adm.locales")}</h3></div>
              <table class="data compact"><thead><tr><th>${t("adm.code")}</th><th>${t("common.name")}</th>
                <th>dir</th><th>${t("common.status")}</th></tr></thead><tbody>
                ${locales.map(l => `<tr><td class="mono-cell">${esc(l.code)}</td>
                  <td>${esc(l.name_native)} (${esc(l.name_en)})</td><td>${esc(l.dir)}</td>
                  <td>${A.badge(l.is_active ? t("common.yes") : t("common.no"), l.is_active ? "green" : "gray")}</td></tr>`).join("")}
              </tbody></table>
              <div class="small muted" style="margin-top:8px">${t("adm.localesHint")}</div>
            </div>
            <div class="card"><div class="card-head"><h3>${icon("database")} ${t("adm.configWhere")}</h3></div>
              <div class="stat-line"><span>${t("adm.configStorage")}</span>
                <b class="mono-cell">setting (key, value)</b></div>
              <div class="stat-line"><span>${t("adm.configKeys")}</span>
                <b>${doc.fields.length}</b></div>
              <div class="stat-line"><span>${t("adm.configOverrides")}</span>
                <b>${doc.overrides}</b></div>
              <div class="stat-line"><span>${t("adm.configDb")}</span>
                <b class="mono-cell">${esc((meta.db && meta.db.path) || "—")}</b></div>
              <div class="small muted" style="margin-top:8px">${esc(t("adm.configWhereHint"))}</div>
            </div>
          </div>
        </div>`;
    hydrateIcons(root);
    wireSurfaceCard(root);

    const save = root.querySelector("#cfgSave");
    const bar = root.querySelector("#cfgBar");
    const pending = () => {
      const out = {};
      root.querySelectorAll("[data-set]").forEach(el => {
        const v = el.dataset.kind === "bool" ? (el.checked ? "true" : "false") : el.value;
        if (String(v) !== String(initial[el.dataset.set])) out[el.dataset.set] = v;
      });
      return out;
    };
    const refresh = () => {
      const p = pending();
      const keys = Object.keys(p);
      save.disabled = keys.length === 0;
      bar.hidden = keys.length === 0;
      root.querySelector("#cfgCount").textContent =
        t("adm.configPending", { n: keys.length });
      root.querySelector("#cfgDiff").textContent = keys.join(" · ");
      root.querySelectorAll("[data-row]").forEach(row => {
        const el = row.querySelector("[data-set]");
        const dirty = el && String(el.dataset.kind === "bool"
          ? (el.checked ? "true" : "false") : el.value) !== String(initial[el.dataset.set]);
        row.classList.toggle("dirty", !!dirty);
      });
    };
    root.querySelectorAll("[data-set]").forEach(el => {
      el.addEventListener("change", refresh);
      el.addEventListener("input", refresh);
    });

    save.onclick = async () => {
      const payload = pending();
      if (!Object.keys(payload).length) return;
      save.disabled = true;
      try {
        await api.put("/api/settings", payload);
        toast(t("adm.configSaved", { n: Object.keys(payload).length }), "ok");
        Object.assign(initial, payload);
        /* settings that change what the interface looks like take effect at once */
        A.applyAppearance();
        A.rerender();
      } catch (err) {
        save.disabled = false;
        const problems = (err.payload && err.payload.problems) || [];
        root.querySelector("#cfgProblems").innerHTML = problems.length
          ? `<div class="notice err"><b>${esc(t("adm.configInvalid"))}</b><ul style="margin:6px 0 0 18px">
              ${problems.map(p => `<li><span class="mono-cell">${esc(p.key || "?")}</span> — ${esc(p.message)}</li>`).join("")}
            </ul></div>`
          : `<div class="notice err">${esc(err.message)}</div>`;
        problems.forEach(p => {
          const row = root.querySelector(`[data-row="${CSS.escape(p.key || "")}"]`);
          if (row) row.classList.add("invalid");
        });
        toast(t("adm.configInvalid"), "err", 5000);
      }
    };
    root.querySelectorAll("[data-reset]").forEach(btn => {
      btn.onclick = async () => {
        await api.post("/api/settings/reset", { keys: [btn.dataset.reset] });
        A.rerender();
      };
    });
    root.querySelectorAll("[data-reset-group]").forEach(btn => {
      btn.onclick = async () => {
        await api.post("/api/settings/reset", { group: btn.dataset.resetGroup });
        toast(t("common.saved"), "ok");
        A.rerender();
      };
    });
    root.querySelector("#cfgResetAll").onclick = async () => {
      const ok = await A.confirmDialog({
        title: t("adm.configResetAll"), message: t("adm.configResetAllBody"),
        confirmLabel: t("adm.configResetAll")
      });
      if (!ok) return;
      await api.post("/api/settings/reset", {});
      toast(t("adm.configResetDone"), "ok");
      A.rerender();
    };
    root.querySelectorAll("[data-mine]").forEach(btn => {
      btn.onclick = async () => {
        const key = btn.dataset.mine;
        const pref = PREF_OF[key];
        const field = doc.fields.find(f => f.key === key);
        const el = root.querySelector(`[data-set="${CSS.escape(key)}"]`);
        const value = el.dataset.kind === "bool" ? (el.checked ? "true" : "false") : el.value;
        if (!pref) return;
        if (!A.setPref(pref, value)) { toast(t("adm.configAsMineRefused"), "err"); return; }
        if (pref === "language" && App.setLang) await App.setLang(value, { silent: false });
        else A.applyAppearance();
        toast(t("adm.configMineSet", { value: settingValue(field, value) }), "ok");
        A.rerender();
      };
    });
    root.querySelector("#cfgDownload").onclick = () => {
      const body = JSON.stringify({ exported_at: new Date().toISOString(),
        settings: doc.settings, overrides: doc.overrides }, null, 2);
      const url = URL.createObjectURL(new Blob([body], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url; a.download = "siraj-settings.json"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    };
    root.querySelector("#nuAdd").onclick = async () => {
      const username = root.querySelector("#nuName").value.trim();
      if (!username) return;
      try {
        await api.post("/api/users", { username, display_name: username,
          role: root.querySelector("#nuRole").value });
        A.rerender();
      } catch (err) { toast(err.message, "err"); }
    };
    refresh();
  };

  /* ========================================================= MAINTENANCE === */
  A.views.maintenance = async function (root) {
    A.crumbs([{ label: t("nav.maintenance") }]);
    const meta = A.state.meta;
    root.innerHTML = A.pageHead(t("adm.maintenance"), t("adm.maintenanceHint"), "")
      + `<div class="grid c2">
          <div class="card"><div class="card-head"><h3>${t("nav.maintenance")}</h3></div>
            <div class="stat-line"><span>Database</span><b class="mono-cell">${esc(meta.db.path)}</b></div>
            <div class="stat-line"><span>Size</span><b>${fmtNum(Math.round(meta.db.size_bytes / 1024))} KB</b></div>
            <div class="stat-line"><span>Schema</span><b>1.0.0</b></div>
            <div class="stat-line"><span>${t("log.entity")}</span><b>${(meta.entities || []).length}</b></div>
            <div class="stat-line"><span>${t("adm.vocab")}</span><b>${(meta.lookup_domains || []).length}</b></div>
            <div class="btn-row" style="margin-top:14px">
              <button class="btn primary" id="doBackup">${icon("database")} ${t("adm.backup")}</button>
              <button class="btn" id="doDump">${icon("download")} ${t("adm.dump")}</button>
              <button class="btn" id="doReindex">${icon("refresh")} ${t("adm.reindex")}</button>
              <button class="btn" id="doVacuum">${icon("sliders")} ${t("adm.vacuum")}</button>
              <button class="btn" id="doPurge" title="${esc(t("adm.purgeHint"))}">${icon("trash")} ${t("adm.purge")}</button>
            </div>
          </div>
          <div class="card"><div class="card-head"><h3>${A.t("ui.system")}</h3></div>
            <dl class="dl">
              <dt>API</dt><dd class="mono-cell">FastAPI + SQLite (WAL + FTS5)</dd>
              <dt>Schema version</dt><dd class="mono-cell">1.0.0</dd>
              <dt>Languages</dt><dd>العربية · English</dd>
              <dt>${A.t("ui.actingUser")}</dt>
              <dd class="mono-cell">${esc(A.state.actor)}</dd>
            </dl>
            <div class="notice" style="margin-top:12px">${A.t("ui.backupsUseSqliteSOnlineBackupApiSoThey")}</div>
          </div>
        </div>`;
    hydrateIcons(root);
    root.querySelector("#doBackup").onclick = () => A.download("/api/maintenance/backup");
    root.querySelector("#doDump").onclick = () => A.download("/api/maintenance/export-all");
    root.querySelector("#doReindex").onclick = async () => {
      const res = await api.post("/api/maintenance/reindex");
      toast(`${res.documents} documents indexed`, "ok");
    };
    root.querySelector("#doVacuum").onclick = async () => {
      const res = await api.post("/api/maintenance/vacuum");
      toast(`${Math.round(res.size_bytes / 1024)} KB`, "ok");
    };
    /* staging files and unreferenced media: preview first, then remove */
    root.querySelector("#doPurge").onclick = async () => {
      const preview = await api.post("/api/maintenance/purge-working-files",
                                     { older_than_hours: 24, dry_run: true });
      const mb = (preview.bytes_reclaimable / 1048576).toFixed(1);
      const yes = await A.confirmDialog({
        title: t("adm.purge"),
        message: t("adm.purgeConfirm", { files: preview.staging.files + preview.orphan_media.files, mb }),
        confirmLabel: t("adm.purge"),
      });
      if (!yes) return;
      const res = await api.post("/api/maintenance/purge-working-files", { older_than_hours: 24 });
      toast(t("adm.purgeDone", { files: res.files_removed, mb: (res.bytes_freed / 1048576).toFixed(1) }), "ok");
    };
  };
})();
