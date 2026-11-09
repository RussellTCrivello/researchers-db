/* ============================================================================
   SIRAJ · reports.js — report centre, generic section renderer, deep search
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, icon, hydrateIcons, toast, fmtNum, chart } = A;

  const REPORT_LIST = [
    { key: "overview", icon: "grid" },
    { key: "quality", icon: "check-circle" },
    { key: "institutions", icon: "building" },
    { key: "geography", icon: "map-pin" },
    { key: "network", icon: "share" },
    { key: "timeline", icon: "clock" },
    { key: "sources", icon: "book" },
    { key: "workflow", icon: "check" },
    { key: "indicators", icon: "activity" },
    { key: "custom", icon: "sliders" }
  ];

  const NAMES = {
    overview: ["Registry overview", "نظرة عامة على السجل"],
    quality: ["Data quality & completeness", "جودة البيانات والاكتمال"],
    institutions: ["Institutional network", "الشبكة المؤسسية"],
    geography: ["Geographic distribution", "التوزيع الجغرافي"],
    network: ["Relationship network", "شبكة العلاقات"],
    timeline: ["Chronology", "التقرير الزمني"],
    sources: ["Sources & evidence", "المصادر والأدلة"],
    workflow: ["Review progress", "سير المراجعة"],
    indicators: ["Indicator report", "تقرير المؤشرات"],
    custom: ["Custom pivot", "تقرير محوري مخصص"]
  };

  function nameOf(key) {
    const n = NAMES[key] || [key, key];
    return A.state.lang === "ar" ? n[1] : n[0];
  }

  A.views.reports = async function (root, params) {
    A.crumbs([{ label: t("nav.reports") }]);
    const current = params.key || "overview";
    root.innerHTML = A.pageHead(t("rep.title"), t("rep.subtitle"), "")
      + `<div class="split">
          <div>
            <div class="card" id="reportHost"><div class="empty">${t("rep.empty")}</div></div>
          </div>
          <div>
            <div class="card tight">
              <div class="card-head" style="padding:14px 16px 0"><h3>${t("rep.pick")}</h3></div>
              <div class="stack" style="padding:12px 16px 16px">
                ${REPORT_LIST.map(r => `<a class="nav-item" style="color:var(--text);background:${r.key === current ? "var(--ink-50)" : "transparent"}"
                  href="#/reports/${r.key}">${icon(r.icon)} <span>${esc(nameOf(r.key))}</span></a>`).join("")}
              </div>
            </div>
            <div class="card" id="paramsCard"></div>
          </div>
        </div>`;
    hydrateIcons(root);
    await generate(root, current);
    if (!A.fresh(root)) return;
    renderParams(root, current);
  };

  function renderParams(root, key) {
    const card = root.querySelector("#paramsCard");
    if (!card) return;
    if (key !== "custom") {
      card.innerHTML = `<div class="card-head"><h3>${t("rep.params")}</h3></div>
        <p class="muted small">${A.t("ui.theseReportsRunAgainstTheWholeDatabase")}</p>`;
      return;
    }
    const entities = A.state.meta.entities || [];
    const e0 = entities[0] ? entities[0].key : "person";
    card.innerHTML = `<div class="card-head"><h3>${t("rep.custom")}</h3></div>
      <div class="field"><label>${t("exp.entity")}</label>
        <select id="pvEntity">${entities.map(e =>
          `<option value="${e.key}">${esc(A.state.lang === "ar" ? e.plural_ar : e.plural_en)}</option>`).join("")}</select></div>
      <div class="field"><label>${t("rep.groupBy")}</label><select id="pvGroup"></select></div>
      <div class="field"><label>${t("rep.metric")}</label>
        <select id="pvMetric">${["count", "sum", "avg", "min", "max"].map(v =>
          `<option value="${v}">${esc(t("rep.value.metric." + v))}</option>`).join("")}</select></div>
      <div class="field"><label>${t("rep.chart")}</label>
        <select id="pvChart">${["bar", "pie", "table", "timeline"].map(v =>
          `<option value="${v}">${esc(t("rep.value.chart." + v))}</option>`).join("")}</select></div>
      <button class="btn primary" id="pvRun">${t("rep.generate")}</button>`;
    const eSel = card.querySelector("#pvEntity");
    const gSel = card.querySelector("#pvGroup");
    function fillGroups() {
      /* own fields + fields derived from related tables */
      const own = A.registry(eSel.value).filter(f => f.filterable && f.kind === "field");
      const der = A.registry(eSel.value).filter(f => f.filterable && f.kind === "derived");
      gSel.innerHTML =
        `<optgroup label="${esc(t("common.record") || "Record")}">` +
        own.map(f => `<option value="${f.key}">${esc(A.fieldLabelSafe(f))}</option>`).join("") +
        `</optgroup>` +
        (der.length ? `<optgroup label="${esc(A.t("ui.relatedTables"))}">` +
          der.map(f => `<option value="${f.key}">ƒ ${esc(A.fieldLabelSafe(f))}</option>`).join("") +
          `</optgroup>` : "");
    }
    fillGroups();
    eSel.onchange = fillGroups;
    card.querySelector("#pvRun").onclick = async () => {
      const params = {
        entity: eSel.value, group_by: gSel.value,
        metric: card.querySelector("#pvMetric").value,
        chart: card.querySelector("#pvChart").value
      };
      await generate(root, "custom", params);
    };
  }

  async function generate(root, key, params) {
    const host = root.querySelector("#reportHost");
    if (!host) return;
    host.innerHTML = `<div class="skeleton" style="width:40%"></div>
      <div class="skeleton" style="width:80%;margin-top:10px"></div>`;
    let report;
    try {
      report = await api.post(`/api/reports/${key}`, { params: params || {} });
    } catch (err) {
      if (!host.isConnected) return;
      host.innerHTML = `<div class="notice err">${esc(err.message)}</div>`;
      return;
    }
    if (!host.isConnected) return;   // the user navigated away while we waited
    host.innerHTML = renderReport(report, key, params);
    hydrateIcons(host);
    const printBtn = host.querySelector("[data-print]");
    if (printBtn) printBtn.onclick = () => window.print();
    host.querySelectorAll("[data-exp]").forEach(b => {
      b.onclick = () => {
        const fmt = b.dataset.exp;
        const url = `/api/reports/${key}/export?format=${fmt}&params=${encodeURIComponent(JSON.stringify(params || {}))}`;
        A.download(url);
      };
    });
  }

  function renderReport(report, key, params) {
    const title = A.state.lang === "ar" ? report.title_ar : report.title_en;
    const subtitle = A.state.lang === "ar" ? report.description_ar : report.description_en;
    const summary = (report.summary || []).map(s => `
      <div class="kpi-mini">
        <div class="v">${typeof s.value === "number" ? fmtNum(s.value) : esc(s.value)}${s.unit === "%" ? "%" : ""}</div>
        <div class="l">${esc(A.state.lang === "ar" ? (s.label_ar || s.label_en) : (s.label_en || s.label_ar))}</div>
      </div>`).join("");
    const sections = (report.sections || []).map(renderSection).join("");
    return `<div class="report-sheet">
      <div class="card-head">
        <div>
          <h2>${esc(title)}</h2>
          <div class="card-sub">${esc(subtitle || "")}</div>
        </div>
        <div class="btn-row no-print">
          <button class="btn sm" data-print>${icon("print")} ${t("common.print")}</button>
          <button class="btn sm" data-exp="xlsx">${icon("download")} XLSX</button>
          <button class="btn sm" data-exp="csv">CSV</button>
          <button class="btn sm" data-exp="json">JSON</button>
        </div>
      </div>
      <div class="report-meta">
        <span>${t("rep.generated")}: ${esc(A.fmtDate(report.generated_at, true))}</span>
        <span>${(report.sections || []).length} ${t("rep.sections")}</span>
        ${params && Object.keys(params).length ? `<span class="mono-cell">${esc(JSON.stringify(params))}</span>` : ""}
      </div>
      <div class="grid auto" style="margin-bottom:16px">${summary}</div>
      ${sections}
    </div>`;
  }

  function renderSection(sec) {
    const title = A.state.lang === "ar" ? (sec.title_ar || sec.title_en) : (sec.title_en || sec.title_ar);
    const cols = sec.columns || [];
    const rows = sec.rows || [];
    let body = "";
    if (sec.type === "bar" || sec.type === "pie" || sec.type === "timeline" || sec.type === "line") {
      const chartRows = rows.map(r => {
        const labelKey = cols[0] ? cols[0].key : "label_en";
        const valueKey = cols[1] ? cols[1].key : "value";
        return {
          label_en: r[labelKey], label_ar: r.label_ar || r[labelKey],
          value: Number(r[valueKey] || r.value || 0), color: r.color
        };
      });
      body = A.chart(sec.type, chartRows);
    }
    if (sec.type === "table" || sec.type === "matrix" || sec.type === "cards" || sec.type === "bar") {
      body += `<div class="table-wrap" style="margin-top:${body ? "12px" : "0"}">
        <table class="data compact"><thead><tr>
          ${cols.map(c => `<th>${esc(A.state.lang === "ar" ? (c.label_ar || c.label_en) : (c.label_en || c.label_ar))}</th>`).join("")}
        </tr></thead><tbody>
          ${rows.length ? rows.map(r => `<tr>
            ${cols.map((c, i) => {
              const v = r[c.key];
              if (c.key === "completeness_pct") {
                const cls = v >= 90 ? "good" : v >= 60 ? "fair" : "poor";
                return `<td style="min-width:120px"><div class="flex" style="gap:8px">
                  <div class="progress ${cls}" style="flex:1"><span style="width:${Math.min(100, v || 0)}%"></span></div>
                  <span class="small">${v ?? 0}%</span></div></td>`;
              }
              if (c.key === "status") {
                const map = { good: "green", fair: "amber", poor: "red" };
                return `<td>${A.badge(String(v || ""), map[v] || "gray")}</td>`;
              }
              if (typeof v === "number") return `<td class="num">${fmtNum(v)}</td>`;
              return `<td${i === 0 ? ' class="row-title"' : ""}>${esc(v === null || v === undefined ? "—" : String(v))}</td>`;
            }).join("")}</tr>`).join("")
            : `<tr><td colspan="${cols.length}" class="empty">${t("list.noRecords")}</td></tr>`}
        </tbody></table></div>`;
    }
    return `<div style="margin-bottom:22px">
      <h3 style="margin-bottom:8px;border-bottom:1px solid var(--border);padding-bottom:4px">${esc(title)}</h3>
      ${body}
      ${sec.note ? `<div class="small muted" style="margin-top:6px">${esc(sec.note)}</div>` : ""}
    </div>`;
  }

  /* ============================================================ search === */
  A.views.search = async function (root, params, route) {
    A.crumbs([{ label: t("nav.search") }]);
    const q = route.params.q || "";
    root.innerHTML = A.pageHead(t("search.title"), t("search.subtitle"), "")
      + `<div class="card">
          <div class="flex wrap">
            <div class="search-box" style="max-width:520px;flex:1">
              ${icon("search")}<input id="dq" value="${esc(q)}" placeholder="${esc(t("search.placeholder"))}">
            </div>
            <select class="ghost-select" id="scope">
              <option value="">${esc(t("search.all"))}</option>
              ${(A.state.meta.entities || []).map(e =>
                `<option value="${e.key}">${esc(A.state.lang === "ar" ? e.plural_ar : e.plural_en)}</option>`).join("")}
            </select>
            <button class="btn primary" id="go">${t("search.do")}</button>
          </div>
          <div class="small muted" style="margin-top:8px">${A.t("ui.searchIgnoresArabicDiacriticsAndLetter")}</div>
        </div>
        <div id="results"></div>`;
    hydrateIcons(root);
    const dq = root.querySelector("#dq");
    const prefOr = (name, key, fallback) =>
      A.resolvePref ? A.resolvePref(name, key, fallback) : A.setting(key, fallback);
    const minChars = Math.max(1, Number(prefOr("search_min_chars", "search.min_chars", 2)) || 2);
    const limit = Math.max(5, Number(prefOr("search_results_limit", "search.results_limit", 20)) || 20);
    const go = async () => {
      const term = dq.value.trim();
      if (!term) return;
      if (term.length < minChars) {
        toast(A.t("ui.searchNeedsMoreChars", { n: minChars }) || `Type at least ${minChars} characters`, "warn");
        return;
      }
      const scope = root.querySelector("#scope").value;
      location.hash = `#/search?q=${encodeURIComponent(term)}${scope ? "&entity=" + scope : ""}`;
      const res = await api.get(`/api/search?q=${encodeURIComponent(term)}&limit=${limit}${scope ? `&entity=${scope}` : ""}`);
      renderResults(root.querySelector("#results"), res);
    };
    root.querySelector("#go").onclick = go;
    dq.onkeydown = (e) => { if (e.key === "Enter") go(); };
    if (q) {
      const scope = route.params.entity || "";
      root.querySelector("#scope").value = scope;
      const res = await api.get(`/api/search?q=${encodeURIComponent(q)}&limit=25${scope ? `&entity=${scope}` : ""}`);
      renderResults(root.querySelector("#results"), res);
    }
  };

  function renderResults(host, res) {
    if (!res.total) {
      host.innerHTML = `<div class="card"><div class="empty">${esc(t("search.noResults"))}</div></div>`;
      return;
    }
    host.innerHTML = `<div class="card"><div class="card-head"><h3>${fmtNum(res.total)} ${t("search.results")}</h3></div>
      ${res.groups.map(g => `
        <div style="margin-bottom:14px">
          <div class="small muted" style="margin-bottom:6px">${icon(g.icon)} ${esc(A.state.lang === "ar" ? g.label_ar : g.label_en)}</div>
          ${g.items.map(it => `
            <a href="#/entity/${g.entity}/${it.id}" class="flex" style="gap:10px;padding:7px 9px;border-radius:8px;color:var(--text)"
               onmouseover="this.style.background='var(--ink-50)'" onmouseout="this.style.background='transparent'">
              <span class="mono-cell badge gray">${esc(it.code)}</span>
              <span><b>${esc(it.title)}</b>
                <div class="small muted">${esc(A.truncate(it.snippet || "", 110))}</div></span>
            </a>`).join("")}
        </div>`).join("")}
    </div>`;
    hydrateIcons(host);
  }
})();
