/* ============================================================================
   SIRAJ · dashboard.js — control panel
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, fmtNum, icon, chart, hydrateIcons } = A;

  A.views.dashboard = async function (root) {
    A.crumbs([{ label: t("nav.dashboard") }]);
    const d = await api.get("/api/dashboard");
    const cards = d.cards || [];
    const totalRecords = d.totals.records;

    const kpis = cards.map((c, i) => `
      <div class="kpi" style="--kpi-color:${A.PALETTE[i % A.PALETTE.length]}">
        <div class="k-label">${icon(c.icon)} ${esc(A.state.lang === "ar" ? c.label_ar : c.label_en)}</div>
        <div class="k-value">${fmtNum(c.total)}</div>
        <div class="k-foot"><b>+${fmtNum(c.new_30d)}</b> ${esc(t("dash.new30"))}
          <span>· ${fmtNum(c.updated_30d)} ${esc(t("dash.updated30"))}</span></div>
      </div>`).join("");

    const coverage = Object.keys(d.coverage || {}).map(k => {
      const pct = d.coverage[k];
      const cls = pct >= 75 ? "good" : pct >= 40 ? "fair" : "poor";
      return `<div style="margin-bottom:10px">
        <div class="flex" style="justify-content:space-between">
          <span class="small">${esc(A.pluralOf(k))}</span>
          <span class="small muted">${pct}%</span></div>
        <div class="progress ${cls}"><span style="width:${Math.min(100, pct)}%"></span></div></div>`;
    }).join("");

    const recent = (d.recent_changes || []).map(r => `
      <tr>
        <td class="nowrap mono-cell">${esc(r.entity_code || ("#" + r.entity_id))}</td>
        <td>${esc(A.label(r.entity_type))}</td>
        <td>${esc(r.action)}</td>
        <td>${esc(r.field_label || "—")}</td>
        <td class="small muted">${esc(String(r.new_value || "").slice(0, 42))}</td>
        <td class="nowrap small muted">${esc(r.actor || "—")}</td>
        <td class="nowrap small muted">${esc(A.ago(r.changed_at))}</td>
      </tr>`).join("");

    root.innerHTML = A.pageHead(t("dash.title"), t("dash.subtitle"), `
      <button class="btn primary" id="quickNew">${icon("plus")} ${t("common.new")}</button>
      <a class="btn" href="#/reports">${icon("chart")} ${t("nav.reports")}</a>
      <a class="btn" href="#/import">${icon("upload")} ${t("nav.import")}</a>
      <a class="btn" href="#/export">${icon("download")} ${t("nav.export")}</a>`)
      + `<div class="grid auto" style="margin-bottom:18px">${kpis}</div>
      <div class="grid c2">
        <div class="card">
          <div class="card-head"><h3>${t("dash.statusDist")}</h3>
            <span class="card-sub">${fmtNum(totalRecords)} ${t("common.records")}</span></div>
          ${chart("pie", (d.status_distribution || []).map(s => ({
            label_en: s.label_en, label_ar: s.label_ar, value: s.n, color: s.color })))}
        </div>
        <div class="card">
          <div class="card-head"><h3>${t("dash.authDist")}</h3></div>
          ${chart("bar", (d.authentication_distribution || []).map(s => ({
            label_en: s.label_en, label_ar: s.label_ar, value: s.n, color: s.color })), { showPct: true })}
        </div>
      </div>
      <div class="grid c2">
        <div class="card">
          <div class="card-head"><h3>${t("dash.activity")}</h3></div>
          ${chart("line", (d.monthly_activity || []).map(m => ({
            label_en: m.month, label_ar: m.month, value: (m.created || 0) + (m.updated || 0) })))}
          <div class="chart-legend"><span><i style="background:#17395c"></i>${A.t("ui.createdUpdated")}</span></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>${t("dash.coverage")}</h3></div>
          <p class="card-sub" style="margin-top:-6px">${t("dash.coverageHint")}</p>
          ${coverage}
          <hr class="hr-soft">
          <div class="stat-line"><span>${t("common.total")}</span><b>${fmtNum(d.totals.records)}</b></div>
          <div class="stat-line"><span>${t("nav.changelog")}</span><b>${fmtNum(d.totals.change_log)}</b></div>
          <div class="stat-line"><span>${t("imp.jobs")}</span><b>${fmtNum(d.totals.open_imports)}</b></div>
          <div class="stat-line"><span>${t("list.saved")}</span><b>${fmtNum(d.totals.saved_views)}</b></div>
          <div class="stat-line"><span>${t("adm.users")}</span><b>${fmtNum(d.totals.active_users)}</b></div>
        </div>
      </div>
      <div class="grid c3">
        <div class="card">
          <div class="card-head"><h3>${t("dash.countries")}</h3></div>
          ${chart("bar", (d.top_countries || []).map(c => ({
            label_en: c.label_en, label_ar: c.label_ar, value: c.n })))}
        </div>
        <div class="card">
          <div class="card-head"><h3>${t("dash.relTypes")}</h3></div>
          ${chart("bar", (d.relationship_types || []).map(c => ({
            label_en: c.label_en, label_ar: c.label_ar, value: c.n, color: c.color })))}
        </div>
        <div class="card">
          <div class="card-head"><h3>${t("dash.quick")}</h3></div>
          <div class="stack">
            ${(A.state.meta.entities || []).map(e => `
              <a class="btn" href="#/entity/${e.key}/new" style="justify-content:flex-start">
                ${icon(e.icon)} ${t("common.add")} — ${esc(A.state.lang === "ar" ? e.label_ar : e.label_en)}
              </a>`).join("")}
          </div>
          <hr class="hr-soft">
          <div class="btn-row">
            <a class="btn sm" href="#/search">${icon("search")} ${t("nav.search")}</a>
            <a class="btn sm" href="#/changelog">${icon("history")} ${t("nav.changelog")}</a>
            <a class="btn sm" href="#/vocabularies">${icon("list")} ${t("nav.vocabularies")}</a>
          </div>
        </div>
      </div>
      <div class="card tight">
        <div class="card-head" style="padding:14px 16px 0"><h3>${t("dash.recent")}</h3>
          <a class="btn sm" href="#/changelog">${t("common.view")}</a></div>
        <div class="table-wrap" style="border:0;border-radius:0">
          <table class="data compact">
            <thead><tr>
              <th>${t("common.code")}</th><th>${t("log.entity")}</th><th>${t("log.action")}</th>
              <th>${t("log.field")}</th><th>${t("rec.newValue")}</th><th>${t("log.actor")}</th>
              <th>${t("log.when")}</th></tr></thead>
            <tbody>${recent || `<tr><td colspan="7" class="empty">${t("list.noRecords")}</td></tr>`}</tbody>
          </table>
        </div>
      </div>`;

    hydrateIcons(root);
    const qn = root.querySelector("#quickNew");
    if (qn) qn.onclick = () => {
      const first = (A.state.meta.entities || [])[0];
      location.hash = `#/entity/${first.key}/new`;
    };
  };
})();
