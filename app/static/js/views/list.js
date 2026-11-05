/* ============================================================================
   SIRAJ · list.js — data views (table / cards / gallery / list), deep filters,
   column & card-layout control, bulk actions, saved views, export.
   Any field — including derived fields from related tables — can be shown,
   filtered, sorted and laid out.
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, fmtNum, icon, hydrateIcons, toast } = A;

  const state = A.listState = {};

  const ENTITY_GLYPH = {
    person: "user", institution: "building", place: "map-pin",
    source: "book", relationship: "link", event: "calendar"
  };
  const MAP_ENTITIES = new Set(["person", "institution", "place", "event"]);
  /* People, places and organizations keep the table and the record on one page. */
  const INSPECT_ENTITIES = new Set(["person", "institution", "place"]);
  function canInspect(entity) { return INSPECT_ENTITIES.has(entity); }
  function viewsFor(entity) {
    const base = ["table", "cards", "gallery", "list"];
    return MAP_ENTITIES.has(entity) ? base.concat("map") : base;
  }

  /* ------------------------------------------------------------ state --- */
  function defaultLayout(entity) {
    const isPerson = entity === "person";
    const facts = {
      person: ["classification_id", "nationality_id"],
      institution: ["institution_type_id", "country_id"],
      place: ["place_type_id", "country_id"],
      source: ["source_type_id", "publication_date"],
      event: ["event_type_id", "start_date"],
      relationship: ["relationship_type_id", "start_date"]
    }[entity] || [];
    const stats = {
      person: ["relationships_count", "citations_count", "positions_count"],
      institution: ["persons_count", "relationships_count"],
      place: ["institutions_count", "persons_born_count"],
      source: ["citations_count", "primary_for_count"],
      event: ["participants_count"],
      relationship: ["duration_years"]
    }[entity] || [];
    const hasImagery = ["person", "institution", "place", "event"].includes(entity);
    return {
      imageField: hasImagery ? "image_url" : null,
      titleField: isPerson ? "name_ar" : (entity === "source" ? "title" : (entity === "event" ? "title_ar" : "name_ar")),
      subtitleField: isPerson ? "name_en" : (entity === "source" ? "title_ar" : (entity === "event" ? "title_en" : "name_en")),
      badgeField: "record_status_id",
      factFields: facts,
      statFields: stats
    };
  }

  function initialState(entity) {
    let savedCols = null, savedLayout = null, savedView = null;
    try {
      savedCols = JSON.parse(localStorage.getItem("siraj.cols." + entity) || "null");
      savedLayout = JSON.parse(localStorage.getItem("siraj.layout." + entity) || "null");
      savedView = localStorage.getItem("siraj.view." + entity);
    } catch (e) { /* ignore */ }
    const fields = A.registry(entity).filter(f => f.kind === "field");
    const defaults = fields.filter(f => f.in_list).map(f => f.key);
    return {
      q: "", query: "", queryDraft: "", queryInfo: null,
      page: 1, page_size: (A.pageSize ? A.pageSize() : 25), pages_loaded: 1,
      sort: null, order: "desc",
      include_deleted: false, only_deleted: false, logic: "and", where: [],
      columns: savedCols && savedCols.length ? savedCols : defaults.slice(0, 9),
      view: savedView || "table",
      layout: Object.assign(defaultLayout(entity), savedLayout || {}),
      selected: new Set(), inspectId: null, inspectTab: "details",
      showFilters: false, data: null, savedViews: [], loading: false
    };
  }

  function persist(entity) {
    const st = state[entity];
    localStorage.setItem("siraj.cols." + entity, JSON.stringify(st.columns));
    localStorage.setItem("siraj.layout." + entity, JSON.stringify(st.layout));
    localStorage.setItem("siraj.view." + entity, st.view);
  }

  /* --------------------------------------------------------- operators --- */
  const TYPE_OPS = {
    text: ["contains", "not_contains", "starts", "ends", "equals", "empty", "not_empty"],
    textarea: ["contains", "not_contains", "equals", "empty", "not_empty"],
    url: ["contains", "empty", "not_empty"],
    select: ["eq", "ne", "in", "not_in", "empty", "not_empty"],
    fk: ["eq", "ne", "in", "not_in", "is_null", "not_null"],
    date: ["on", "before", "after", "between", "year_eq", "year_gte", "year_lte",
           "is_null", "not_null"],
    int: ["eq", "gte", "lte", "between", "is_null", "not_null"],
    float: ["eq", "gte", "lte", "between", "is_null", "not_null"],
    bool: ["eq"]
  };
  function opsFor(type) { return TYPE_OPS[type] || ["contains"]; }

  function opLabel(op) {
    const map = {
      contains: t("list.contains"), not_contains: t("common.no") + " ∋", starts: "▸",
      ends: "◂", equals: t("list.equalsField"), eq: "=", ne: "≠", in: "∈", not_in: "∉",
      between: t("list.between"), gte: "≥", lte: "≤", gt: ">", lt: "<",
      is_null: t("list.isNull"), not_null: t("list.notNull"),
      empty: t("list.isEmpty"), not_empty: t("list.isNotEmpty"),
      on: t("list.onDay"), before: t("list.before"), after: t("list.after"),
      year_eq: "= " + (t("common.year") || "YYYY"), year_gte: "≥ YYYY", year_lte: "≤ YYYY"
    };
    return map[op] || op;
  }

  /* ------------------------------------------------------ filter panel --- */
  function filterPanel(entity) {
    const st = state[entity];
    const reg = A.registry(entity).filter(f => f.filterable && f.kind === "field");
    const derived = A.registry(entity).filter(f => f.filterable && f.kind === "derived");
    const box = document.createElement("div");
    box.className = "card";
    box.innerHTML = `
      <div class="card-head">
        <h3>${icon("filter")} ${t("list.filters")}</h3>
        <div class="btn-row">
          <div class="logic-toggle">
            <button data-logic="and" class="${st.logic === "and" ? "active" : ""}">AND</button>
            <button data-logic="or" class="${st.logic === "or" ? "active" : ""}">OR</button>
          </div>
          <button class="btn sm" data-add>${icon("plus")} ${t("list.addFilter")}</button>
          <button class="btn sm ghost" data-add-pick title="${esc(t("list.chooseField"))}">${icon("search")} ${esc(t("list.chooseField"))}</button>
          <button class="btn sm" data-add-derived>${icon("share")} ${A.t("ui.relatedTableFilter")}</button>
          <button class="btn sm ghost" data-clear>${t("list.clearFilters")}</button>
        </div>
      </div>
      <div class="filters" data-rows></div>
      <hr class="hr-soft">
      <div class="flex wrap">
        <label class="check"><input type="checkbox" data-del ${st.include_deleted ? "checked" : ""}> ${t("list.includeDeleted")}</label>
        <label class="check"><input type="checkbox" data-onlydel ${st.only_deleted ? "checked" : ""}> ${t("common.trash") || "Recycle bin"}</label>
        <span class="spacer"></span>
        <button class="btn sm primary" data-apply>${t("common.apply")}</button>
      </div>`;
    const rowsBox = box.querySelector("[data-rows]");
    st.where.forEach(row => rowsBox.appendChild(filterRowEl(entity, row, reg, derived)));
    if (!st.where.length) {
      rowsBox.innerHTML = `<div class="muted small">${A.t("ui.noFiltersYetAddOneFromTheRecordSOwnFie")}</div>`;
    }
    box.querySelector("[data-add]").onclick = () => {
      const first = reg[0];
      st.where.push({ field: first.key, op: opsFor(first.type)[0], value: null });
      renderFilters(entity);
    };
    /* add a clause for a *named* field: the grouped, searchable picker */
    const pickHost = box.querySelector("[data-add-pick]");
    if (pickHost && A.fieldPicker) {
      pickHost.onclick = (ev) => {
        ev.stopPropagation();
        const all = reg.concat(derived.map(f => Object.assign({}, f, { derived: true })));
        const picker = A.fieldPicker({
          fields: all,
          onPick: (key) => {
            const f = all.find(x => x.key === key);
            st.where.push({ field: key, op: opsFor(f ? f.type : "text")[0], value: null,
                            derived: !!f.derived });
            renderFilters(entity);
          }
        });
        picker.classList.add("floating");
        const btnRect = pickHost.getBoundingClientRect();
        picker.style.cssText = `position:fixed; z-index:200; inset-inline-start:${btnRect.left}px;` +
                               ` inset-block-start:${btnRect.bottom + 4}px;`;
        picker.querySelector("[data-open]").click();
        document.body.appendChild(picker);
        const close = (e2) => {
          if (!picker.contains(e2.target)) { picker.remove(); document.removeEventListener("mousedown", close); }
        };
        setTimeout(() => document.addEventListener("mousedown", close), 0);
      };
    }
    box.querySelector("[data-add-derived]").onclick = () => {
      const first = derived[0] || reg[0];
      st.where.push({ field: first.key, op: opsFor(first.type)[0], value: null, derived: true });
      renderFilters(entity);
    };
    box.querySelector("[data-clear]").onclick = () => {
      st.where = []; st.logic = "and"; st.q = ""; st.include_deleted = false; st.only_deleted = false;
      const qEl = document.querySelector("[data-list-q]");
      if (qEl) qEl.value = "";
      reload(entity);
    };
    box.querySelectorAll("[data-logic]").forEach(b => {
      b.onclick = () => { st.logic = b.dataset.logic; renderFilters(entity); reload(entity); };
    });
    box.querySelector("[data-del]").onchange = (e) => {
      st.include_deleted = e.target.checked; if (e.target.checked) st.only_deleted = false;
      reload(entity);
    };
    box.querySelector("[data-onlydel]").onchange = (e) => {
      st.only_deleted = e.target.checked; if (e.target.checked) st.include_deleted = false;
      reload(entity);
    };
    box.querySelector("[data-apply]").onclick = () => reload(entity);
    hydrateIcons(box);
    return box;
  }

  function filterRowEl(entity, row, reg, derived) {
    const all = reg.concat(derived);
    const el = document.createElement("div");
    el.className = "filter-row";
    const fsel = document.createElement("select");
    fsel.className = "filter-field";
    const optgroups = derived.length
      ? `<optgroup label="${esc(t("common.record") || "Record")}">` +
        reg.map(f => `<option value="${f.key}" ${row.field === f.key ? "selected" : ""}>${esc(A.regLabel(f))}</option>`).join("") +
        `</optgroup><optgroup label="${esc(A.t("ui.relatedTables"))}">` +
        derived.map(f => `<option value="${f.key}" ${row.field === f.key ? "selected" : ""}>${esc(A.regLabel(f))}</option>`).join("") +
        `</optgroup>`
      : reg.map(f => `<option value="${f.key}" ${row.field === f.key ? "selected" : ""}>${esc(A.regLabel(f))}</option>`).join("");
    fsel.innerHTML = optgroups;
    fsel.onchange = () => {
      const nf = all.find(f => f.key === fsel.value);
      row.field = fsel.value;
      row.op = opsFor(nf ? nf.type : "text")[0];
      row.value = null;
      renderFilters(entity);
    };
    const field = all.find(f => f.key === row.field);
    const osel = document.createElement("select");
    osel.innerHTML = opsFor(field ? field.type : "text")
      .map(o => `<option value="${o}" ${row.op === o ? "selected" : ""}>${esc(opLabel(o))}</option>`).join("");
    osel.onchange = () => { row.op = osel.value; renderFilters(entity); };
    const rm = document.createElement("button");
    rm.className = "icon-btn rm";
    rm.innerHTML = icon("x");
    rm.onclick = () => { state[entity].where = state[entity].where.filter(r => r !== row); renderFilters(entity); };
    el.append(fsel, osel, rm);
    el.appendChild(valueEditor(field, row));
    return el;
  }

  /**
   * The value editor of a filter row is *the same control the record form uses*
   * (`A.control` — combobox with inline creation, vocabulary select, date+time
   * picker, multi-select chips …).  A filter can therefore be described with the
   * vocabulary the data was entered with, not with a bare text box.
   */
  function valueEditor(field, row) {
    const wrap = document.createElement("div");
    wrap.className = "wide filter-value";
    if (!field || ["is_null", "not_null", "empty", "not_empty"].includes(row.op)) return wrap;

    /* ranges: two of the same control, side by side */
    if (row.op === "between") {
      const box = document.createElement("div");
      box.className = "flex range";
      const bounds = Array.isArray(row.value) ? row.value.slice(0, 2) : ["", ""];
      const boundValues = [bounds[0] || "", bounds[1] || ""];
      const push = () => { row.value = [boundValues[0], boundValues[1]]; };
      const lo = A.control(field, {
        mode: "filter", value: boundValues[0], allowTime: true,
        onChange: (v) => { boundValues[0] = v || ""; push(); }
      });
      const hi = A.control(field, {
        mode: "filter", value: boundValues[1], allowTime: true,
        onChange: (v) => { boundValues[1] = v || ""; push(); }
      });
      if (lo && lo.getValue) box.append(lo);
      const sep = document.createElement("span");
      sep.className = "range-sep";
      sep.textContent = "→";
      if (hi && hi.getValue) box.append(sep, hi);
      wrap.appendChild(box);
      return wrap;
    }

    /* moment-aware operators take one date control */
    if (field.type === "date") {
      const control = A.control(field, {
        mode: "filter", value: row.value || "", allowTime: true,
        onChange: (v) => { row.value = v || null; }
      });
      wrap.appendChild(control);
      return wrap;
    }

    const multi = ["in", "not_in"].includes(row.op);
    if (multi && (field.type === "select" || field.type === "fk")) {
      const mc = A.multiCombo(Object.assign({
        values: Array.isArray(row.value) ? row.value : [],
        onChange: (v) => { row.value = v; }
      }, {
        domain: field.type === "select" ? field.domain : undefined,
        entity: field.type === "fk" ? field.ref : undefined,
        size: "sm",
        placeholder: A.t("ui.searchAndAdd")
      }));
      wrap.appendChild(mc);
      return wrap;
    }

    const control = A.control(field, {
      mode: "filter", value: row.value === null || row.value === undefined ? "" : row.value,
      allowTime: true,
      placeholder: field.type === "date" ? "YYYY" : t("common.value"),
      onChange: (v) => { row.value = v; }
    });
    if (control) wrap.appendChild(control);
    return wrap;
  }

  /** How the typed query was read — a query nobody can check is a guess. */
  function queryEcho(st) {
    if (!st.query) return "";
    const warn = (st.queryInfo && st.queryInfo.warnings) || [];
    return `<div class="query-echo" data-query-echo>
        <span class="qk">${esc(t("list.queryUnderstood"))}</span>
        <code dir="ltr">${esc((st.queryInfo && st.queryInfo.echo) || st.query)}</code>
        ${warn.length ? `<span class="qwarn">${esc(warn.join(" · "))}</span>` : ""}
      </div>`;
  }

  function renderFilters(entity) {
    const host = document.querySelector("[data-filters-host]");
    if (!host) return;
    host.innerHTML = "";
    host.appendChild(filterPanel(entity));
    hydrateIcons(host);
  }

  /* ----------------------------------------------------------- query --- */
  function payload(entity) {
    const st = state[entity];
    /* A typed query is the *same* filter, written as text. When one is in force it
       is the authority and the builder's clauses are empty, so the two spellings
       can never disagree about which rows are on screen. */
    return {
      query: st.query || undefined,
      q: st.q || undefined,
      where: st.where.filter(r => r.field && r.op),
      logic: st.logic,
      include_deleted: st.include_deleted,
      only_deleted: st.only_deleted,
      page: st.page, page_size: st.page_size,
      sort: st.sort || undefined, order: st.order
    };
  }

  async function applyQuery(entity) {
    const st = state[entity];
    const bar = document.querySelector("[data-query]");
    const text = String(st.queryDraft || (bar ? bar.value : st.query) || "").trim();
    if (!text) return clearQuery(entity);
    try {
      const parsed = await api.post("/api/query/parse", { entity, query: text });
      st.query = text;
      st.queryDraft = text;
      st.queryInfo = { echo: parsed.echo, warnings: parsed.warnings || [] };
      st.q = ""; st.where = [{ op: "eq" }]; st.page = 1;
      if (parsed.payload && parsed.payload.sort) st.sort = parsed.payload.sort.key;
      if (parsed.payload && parsed.payload.sort) st.order = parsed.payload.sort.dir;
      setHash(entity, text);
      await reload(entity);
      if (st.queryInfo.warnings.length) {
        toast(st.queryInfo.warnings.join(" · "), "warn");
      }
    } catch (err) {
      toast(err.message, "err");
    }
  }

  /** The address bar carries the query, so a view can be sent to a colleague. */
  function setHash(entity, text) {
    const base = `#/entity/${entity}`;
    history.replaceState(null, "", text ? `${base}?q=${encodeURIComponent(text)}` : base);
  }

  function clearQuery(entity) {
    const st = state[entity];
    st.query = ""; st.queryDraft = ""; st.queryInfo = null;
    st.where = [{ op: "eq" }]; st.q = ""; st.page = 1;
    setHash(entity, "");
    reload(entity);
  }

  async function reload(entity) {
    const st = state[entity];
    st.pages_loaded = 1;
    st.loading = true;
    draw(entity);
    try {
      const [data, kpi] = await Promise.all([
        api.post(`/api/${entity}/query`, payload(entity)),
        api.post(`/api/${entity}/kpi`, payload(entity)).catch(() => null)
      ]);
      st.data = data;
      st.kpi = kpi;
    } catch (err) {
      toast(err.message, "err");
      st.data = { items: [], total: 0, pages: 1, page: 1 };
    }
    st.loading = false;
    draw(entity);
    scrollViewportTo(entity, 0);
  }

  /** Append the next page instead of replacing the list ("show more"). */
  async function loadMore(entity) {
    const st = state[entity];
    if (st.loading || !st.data) return;
    const next = (st.data.page || 1) + (st.pages_loaded || 1);
    if ((st.data.items || []).length >= (st.data.total || 0)) return;
    const btn = document.querySelector("[data-load-more]");
    if (btn) { btn.disabled = true; btn.classList.add("busy"); }
    try {
      const data = await api.post(`/api/${entity}/query`,
        Object.assign(payload(entity), { page: next }));
      st.data.items = (st.data.items || []).concat(data.items || []);
      st.data.total = data.total;
      st.data.pages = data.pages;
      st.pages_loaded = (st.pages_loaded || 1) + 1;
      drawViewport(entity);
    } catch (err) {
      toast(err.message, "err");
      if (btn) { btn.disabled = false; btn.classList.remove("busy"); }
    }
  }

  function scrollViewportTo(entity, top) {
    const vp = document.querySelector("[data-scroll-body]");
    if (!vp) return;
    try { vp.scrollTo({ top: top, behavior: "smooth" }); } catch (e) { vp.scrollTop = top; }
  }

  /** Re-render only the scrollable body + pager (keeps the page itself still). */
  function drawViewport(entity) {
    const st = state[entity];
    const body = document.querySelector("[data-scroll-body]");
    const footer = document.querySelector("[data-list-footer]");
    if (body) body.innerHTML = viewBody(entity, st.data || { items: [], total: 0 });
    if (footer) footer.innerHTML = pager(entity, st.data || { items: [], total: 0 });
    hydrateIcons(body || document.body);
    wireViewport(entity);
  }

  /* -------------------------------------------------------- value cell --- */
  function cellHtml(entity, item, f) {
    if (f.kind === "derived") {
      const v = (item._derived || {})[f.key];
      if (v === null || v === undefined || v === "") return `<span class="muted">—</span>`;
      if (f.key === "completeness") {
        const cls = v >= 75 ? "good" : v >= 40 ? "fair" : "poor";
        return `<div class="flex" style="gap:7px;min-width:110px">
          <div class="progress ${cls}" style="flex:1"><span style="width:${Math.min(100, v)}%"></span></div>
          <span class="small">${v}%</span></div>`;
      }
      if (f.type === "int") return `<span class="num">${fmtNum(v)}</span>`;
      return esc(A.truncate(v, 70));
    }
    const v = item[f.key];
    const lab = (item._labels || {})[f.key];
    const ref = (item._refs || {})[f.key];
    if (v === null || v === undefined || v === "") return `<span class="muted">—</span>`;
    if (lab) return A.badge(A.state.lang === "ar" ? lab.ar : lab.en, lab.color);
    if (ref) return `<a href="#/entity/${f.ref}/${ref.id}" title="${esc(ref.label || "")}">${esc(A.truncate(ref.label || "", 40))}</a>`;
    if (f.type === "date") return esc(v);
    if (f.type === "bool") return v ? t("common.yes") : t("common.no");
    if (f.type === "url") return `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(A.truncate(v, 32))}</a>`;
    if (f.type === "float") return esc(Number(v).toFixed(4).replace(/0+$/, "").replace(/\.$/, ""));
    if (f.key === "code") return `<span class="mono-cell">${esc(v)}</span>`;
    return esc(A.truncate(v, 70));
  }

  function derivedValue(item, key) {
    return (item._derived || {})[key];
  }

  /* ------------------------------------------------------------- draw --- */
  function draw(entity) {
    const st = state[entity];
    const host = document.querySelector("[data-table-host]");
    if (!host) return;
    disposeListMap(entity);
    disposeInspectMap(entity);
    const data = st.data || { items: [], total: 0, pages: 1, page: 1 };
    const canPick = canInspect(entity) && st.view !== "map";
    const inspectOpen = canPick && !!st.inspectId;

    host.innerHTML = `
      <div class="list-shell">
      ${kpiStrip(entity)}
      <div class="card tight list-card">
        <div class="toolbar list-toolbar" data-list-toolbar>
          <div class="search-box" style="max-width:260px">
            ${icon("search")}
            <input data-list-q placeholder="${esc(t("common.search"))}" value="${esc(st.q)}">
          </div>
          <div class="querybar ${st.query ? "on" : ""}" data-querybar>
            <span class="qmark" aria-hidden="true">⌗</span>
            <input data-query dir="ltr" spellcheck="false" autocomplete="off"
                   value="${esc(st.query || st.queryDraft || "")}"
                   placeholder="${esc(t("list.queryPlaceholder"))}"
                   title="${esc(t("list.queryHelp"))}"
                   aria-label="${esc(t("list.queryHelp"))}">
            <button class="icon-btn" data-query-copy
                    title="${esc(t("list.queryFromFilters"))}"
                    aria-label="${esc(t("list.queryFromFilters"))}">⧉</button>
            ${st.query ? `<button class="icon-btn" data-query-clear
                    title="${esc(t("common.clear"))}" aria-label="${esc(t("common.clear"))}">×</button>` : ""}
          </div>
          <button class="btn sm" data-toggle-filters>${icon("filter")} ${t("list.filters")}${st.where.filter(r => r.field).length ? ` (${st.where.filter(r => r.field).length})` : ""}</button>
          <div class="viewswitch" data-viewswitch>
            ${viewsFor(entity).map(v => `
              <button data-view="${v}" class="${st.view === v ? "active" : ""}" title="${t("view." + v) || v}">
                ${icon({ table: "list", cards: "grid", gallery: "columns", list: "file", map: "map-pin" }[v])}
                <span class="hide-sm">${t("view." + v) || v}</span></button>`).join("")}
          </div>
          <button class="btn sm" data-layout>${icon("sliders")} ${t("view.layout") || "Layout"}</button>
          <button class="btn sm" data-cols>${icon("columns")} ${t("list.columns")}</button>
          <button class="btn sm" data-saved>${icon("save")} ${t("list.saved")}${(st.savedViews || []).length ? ` (${st.savedViews.length})` : ""}</button>
          <span class="spacer"></span>
          <button class="btn sm" data-dups>${icon("share")} ${A.t("ui.duplicates")}</button>
          <button class="btn sm" data-export>${icon("download")} ${t("common.export")}</button>
          <a class="btn sm primary" href="#/entity/${entity}/new">${icon("plus")} ${t("common.add")}</a>
        </div>
        ${queryEcho(st)}
        ${filterChips(entity, data)}
        ${bulkBar(entity)}
        <div class="list-stage${inspectOpen ? " tri no-map" : ""}" data-list-stage>
          <div class="list-scroll${canPick ? " can-inspect" : ""}"
               data-scroll-body tabindex="0" aria-label="${esc(A.pluralOf(entity))}">
            ${st.loading ? loadingBlock() : viewBody(entity, data)}
          </div>
          ${inspectOpen ? inspectShell() : ""}
        </div>
        <div class="list-footer" data-list-footer>${pager(entity, data)}</div>
      </div>
      </div>`;
    hydrateIcons(host);
    wire(entity, host);
    wireViewport(entity);
    wireAutoLoad(entity);
    bindInspect(entity);
    measureToolbar(host);
    fitShell();
    if (st.view === "map" && MAP_ENTITIES.has(entity)) {
      requestAnimationFrame(() => mountListMap(entity));
    }
    if (inspectOpen) fillInspect(entity, st.inspectId);
  }

  /**
   * Size the list shell to the viewport so the toolbar, filter dock and pager
   * stay on screen and only the data area scrolls — whatever the window height,
   * page-head wrapping or browser zoom.  Bypassed on small screens, where the
   * page itself scrolls.
   */
  function fitShell() {
    const shell = document.querySelector(".list-shell");
    if (!shell) return;
    if (window.innerWidth <= 900) { shell.style.height = ""; return; }
    const top = shell.getBoundingClientRect().top;
    const foot = document.querySelector(".foot");
    const footH = foot ? foot.offsetHeight : 0;
    const view = shell.closest(".view") || shell.parentElement;
    const padBottom = view ? (parseFloat(getComputedStyle(view).paddingBottom) || 0) : 0;
    const height = Math.max(340, Math.round(window.innerHeight - top - footH - padBottom - 6));
    shell.style.height = height + "px";
  }

  /** Publish the toolbar height so the sticky filter dock can sit right below it. */
  function measureToolbar(host) {
    const bar = (host || document).querySelector("[data-list-toolbar]");
    if (!bar) return;
    const apply = () => document.documentElement.style
      .setProperty("--list-toolbar-h", bar.offsetHeight + "px");
    apply();
    if (window.ResizeObserver) new ResizeObserver(apply).observe(bar);
  }

  function kpiStrip(entity) {
    const st = state[entity];
    const tiles = (st.kpi && st.kpi.tiles) || [];
    if (!tiles.length) return "";
    const cls = (tile) => {
      if (tile.tone === "warn") return "kpi-tile warn";
      if (tile.derived) return "kpi-tile derived";
      return "kpi-tile";
    };
    return `<div class="kpistrip">${tiles.map(tile => `
      <div class="${cls(tile)}" title="${esc(tile.label_en)}">
        ${tile.derived ? `<span class="kpi-fx">ƒ</span>` : ""}
        <b>${tile.unit === "%" ? tile.value + "%" : fmtNum(tile.value)}</b>
        <span>${esc(A.state.lang === "ar" ? (tile.label_ar || tile.label_en) : tile.label_en)}</span>
      </div>`).join("")}</div>`;
  }

  function loadingBlock() {
    return `<div style="padding:18px"><div class="skeleton" style="width:60%"></div>
      <div class="skeleton" style="width:90%;margin-top:8px"></div>
      <div class="skeleton" style="width:75%;margin-top:8px"></div></div>`;
  }

  function filterChips(entity, data) {
    const st = state[entity];
    const rows = st.where.filter(r => r.field);
    if (!rows.length) return "";
    const chips = rows.map(r => {
      const f = A.regField(entity, r.field);
      let v = r.value;
      if (Array.isArray(v)) v = v.length > 2 ? `${v.length} ${t("common.values")}` : v.join(" – ");
      else if (v && typeof v === "object") v = v.label || "";
      if (typeof v === "number" && f && (f.type === "select" || f.type === "fk")) {
        const lk = f.type === "select" ? A.domainOptions(f.domain).find(o => o.id === v) : null;
        if (lk) v = A.state.lang === "ar" ? lk.label_ar : lk.label_en;
        else v = "#" + v;
      }
      return `<span class="filter-chip" title="${esc(opLabel(r.op))}">
        <b>${esc(A.regLabel(f))}</b> ${esc(opLabel(r.op))} ${esc(v === null || v === undefined ? "" : v)}</span>`;
    }).join("");
    return `<div class="toolbar" style="padding-top:8px;padding-bottom:8px">${chips}
      <button class="btn sm ghost" data-clear-chips>${t("list.clearFilters")}</button></div>`;
  }

  function bulkBar(entity) {
    const st = state[entity];
    if (!st.selected.size) return "";
    return `<div class="toolbar" style="background:var(--ink-50)">
      <b>${st.selected.size} ${t("list.selected")}</b>
      <button class="btn sm" data-bulk-status>${t("list.bulkStatus")}</button>
      <button class="btn sm" data-bulk-merge>${A.t("ui.mergeSelected")}</button>
      <button class="btn sm" data-bulk-restore>${t("list.bulkRestore")}</button>
      <button class="btn sm danger" data-bulk-delete>${t("list.bulkDelete")}</button>
      <button class="btn sm ghost" data-bulk-clear>${t("common.reset")}</button>
    </div>`;
  }

  function pager(entity, data) {
    const st = state[entity];
    const shown = (data.items || []).length;
    const total = data.total || 0;
    const hasMore = shown < total;
    const pct = total ? Math.round((shown / total) * 100) : 0;
    return `<div class="pager">
      <span class="info"><b>${fmtNum(shown)}</b> / ${fmtNum(total)}
        ${st.only_deleted ? (t("common.trash") || "deleted") : t("common.records")}</span>
      <div class="load-progress" title="${pct}%"><span style="width:${pct}%"></span></div>
      <select class="ghost-select" data-pagesize>${[10, 25, 50, 100, 200].map(n =>
        `<option value="${n}" ${st.page_size === n ? "selected" : ""}>${n} / ${t("common.page")}</option>`).join("")}</select>
      <span class="spacer"></span>
      ${hasMore ? `<button class="btn sm primary" data-load-more>
        ${icon("plus")} ${A.t("ui.loadMore")}
        <span class="muted small">${fmtNum(Math.min(st.page_size, total - shown))}</span></button>` : ""}
      <div class="pages">
        <button data-page="${Math.max(1, data.page - 1)}" ${data.page <= 1 ? "disabled" : ""}
          title="${esc(t("common.page"))}">‹</button>
        ${pageButtons(data)}
        <button data-page="${Math.min(data.pages, data.page + 1)}" ${data.page >= data.pages ? "disabled" : ""}
          title="${esc(t("common.page"))}">›</button>
      </div>
      <span class="info">${t("common.page")} ${data.page} ${t("common.of")} ${data.pages}</span>
    </div>`;
  }

  function pageButtons(data) {
    const pages = data.pages || 1, cur = data.page || 1;
    const arr = Array.from(new Set([1, pages, cur, cur - 1, cur + 1]))
      .filter(p => p >= 1 && p <= pages).sort((a, b) => a - b);
    let html = "", prev = 0;
    arr.forEach(p => {
      if (p - prev > 1) html += `<button disabled>…</button>`;
      html += `<button data-page="${p}" class="${p === cur ? "active" : ""}">${p}</button>`;
      prev = p;
    });
    return html;
  }

  /* -------------------------------------------------------- view bodies --- */
  function viewBody(entity, data) {
    const st = state[entity];
    if (st.view === "map" && MAP_ENTITIES.has(entity)) {
      return mapViewShell(entity, data);
    }
    if (!data.items.length) {
      return `<div class="empty"><div class="big">🗂</div>
        <div>${st.q || st.where.length ? t("list.noMatch") : t("list.noRecords")}</div>
        <div class="small">${st.q || st.where.length ? t("list.hint") : ""}</div></div>`;
    }
    if (st.view === "table") return tableView(entity, data);
    if (st.view === "list") return rowView(entity, data);
    return cardView(entity, data, st.view === "gallery");
  }

  /* ---------------------------------------------------------- list map --- */
  function disposeListMap(entity) {
    const st = state[entity];
    if (st && st._listPins) {
      st._listPins.forEach(m => { try { m.remove(); } catch (e) { /* */ } });
      st._listPins = null;
    }
    if (st && st._listMap) {
      try { st._listMap.remove(); } catch (e) { /* already gone */ }
      st._listMap = null;
      st._listMapMarkers = null;
    }
  }

  function mapViewShell(entity, data) {
    return `<div class="list-map" data-list-map>
      <aside class="list-map-side">
        <div class="list-map-meta">
          <span data-map-count>…</span>
          <a class="btn ghost sm" href="#/geo">${esc(t("view.openGeo"))}</a>
        </div>
        <ul class="list-map-rows" data-map-rows>
          <li class="muted small">${esc(t("common.loading"))}</li>
        </ul>
      </aside>
      <div class="list-map-canvas" data-map-canvas></div>
      <div class="list-map-card" data-map-card hidden></div>
    </div>`;
  }

  async function mountListMap(entity) {
    const st = state[entity];
    const host = document.querySelector("[data-list-map]");
    if (!host || !window.maplibregl) return;
    disposeListMap(entity);
    const canvas = host.querySelector("[data-map-canvas]");
    const rowsEl = host.querySelector("[data-map-rows]");
    const countEl = host.querySelector("[data-map-count]");
    const cardEl = host.querySelector("[data-map-card]");
    let points = [];
    try {
      const q = (st.q || "").trim();
      const res = await api.get(`/api/map/features?layers=${encodeURIComponent(entity)}&limit=4000&zoom=4`
        + (q ? `&filters=${encodeURIComponent(JSON.stringify({ q }))}` : ""));
      points = (res.points || []).filter(p => p.entity_type === entity);
      if (res.truncated) {
        countEl.textContent = t("view.mapTruncated", {
          n: points.length, total: (res.per_layer && res.per_layer[entity]) || points.length
        });
      } else {
        countEl.textContent = `${fmtNum(points.length)} · ${esc(t("view.mapLocated"))}`;
      }
    } catch (err) {
      rowsEl.innerHTML = `<li class="err small">${esc(err.message)}</li>`;
      return;
    }
    if (!points.length) {
      rowsEl.innerHTML = `<li class="muted small">${esc(t("view.mapEmpty"))}</li>`;
      countEl.textContent = t("view.mapEmpty");
      return;
    }
    const pageIds = new Set((st.data && st.data.items || []).map(i => i.id));
    const sorted = points.slice().sort((a, b) => {
      const ap = pageIds.has(a.id) ? 0 : 1, bp = pageIds.has(b.id) ? 0 : 1;
      return ap - bp;
    });
    rowsEl.innerHTML = sorted.slice(0, 400).map(p => {
      const label = A.state.lang === "ar" ? (p.label_ar || p.label_en) : (p.label_en || p.label_ar);
      const onPage = pageIds.has(p.id);
      const chip = A.geopin
        ? A.geopin.chipHtml({ etype: entity, label: label || p.code, size: "sm" })
        : `<span class="geo-dot" style="background:var(--accent,#17395c)"></span>`;
      return `<li class="list-map-row${onPage ? " on-page" : ""}" data-id="${p.id}"
                  data-lat="${p.lat}" data-lon="${p.lon}">
        ${chip}
        <span class="list-map-main">
          <span dir="auto">${esc(label || p.code || ("#" + p.id))}</span>
          <span class="muted small" dir="ltr">${esc(p.code || "")}</span>
        </span>
      </li>`;
    }).join("");

    const bootStyle = (A.geopin && A.geopin.secondaryStyle)
      ? A.geopin.secondaryStyle("osm")
      : { version: 8, sources: {}, layers: [{ id: "bg", type: "background",
          paint: { "background-color": "#e8eef4" } }] };
    const map = new window.maplibregl.Map({
      container: canvas,
      style: bootStyle,
      center: [44.4, 33.3],
      zoom: 4,
      attributionControl: false
    });
    st._listMap = map;
    st._listPins = [];
    map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      const bounds = new window.maplibregl.LngLatBounds();
      const budget = Math.min(points.length, 200);
      for (let i = 0; i < budget; i++) {
        const p = points[i];
        const label = A.state.lang === "ar" ? (p.label_ar || p.label_en) : (p.label_en || p.label_ar);
        bounds.extend([p.lon, p.lat]);
        if (A.geopin) {
          const m = A.geopin.marker(map, [p.lon, p.lat], {
            etype: entity, label: label || p.code, size: "sm", showLabel: false
          });
          if (m) {
            const el = m.getElement();
            if (el) el.onclick = (ev) => { ev.stopPropagation(); openPoint(p); };
            st._listPins.push(m);
          }
        }
      }
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 48, maxZoom: 10, duration: 0 });
    });

    function openPoint(p) {
      if (!p) return;
      map.easeTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 8), duration: 500 });
      const label = A.state.lang === "ar" ? (p.label_ar || p.label_en) : (p.label_en || p.label_ar);
      cardEl.hidden = false;
      cardEl.innerHTML = `
        <button type="button" class="icon-btn list-map-close" data-close aria-label="${esc(t("common.close"))}">×</button>
        <div class="badge">${esc(A.label(entity))}</div>
        <h3 dir="auto">${esc(label || p.code || "")}</h3>
        <div class="muted small" dir="ltr">${esc(p.code || "")} · ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</div>
        <div class="btn-row" style="margin-top:10px">
          <a class="btn sm primary" href="#/entity/${esc(entity)}/${p.id}">${esc(t("common.view"))}</a>
          <a class="btn sm" href="#/map?focus=${esc(entity)}:${p.id}">${esc(t("geo.showOnAtlas"))}</a>
          <a class="btn sm" href="#/geo">${esc(t("view.openGeo"))}</a>
        </div>`;
      cardEl.querySelector("[data-close]").onclick = () => { cardEl.hidden = true; };
      rowsEl.querySelectorAll(".list-map-row").forEach(r =>
        r.classList.toggle("active", Number(r.dataset.id) === p.id));
    }

    rowsEl.querySelectorAll(".list-map-row").forEach(row => {
      row.onclick = () => openPoint(points.find(p => p.id === Number(row.dataset.id)));
    });
  }

  /* ------------------------------------------- record beside the list --- */
  const INSPECT_STATS = {
    person: ["relationships_count", "citations_count", "positions_count", "completeness"],
    institution: ["persons_count", "relationships_count", "positions_count", "completeness"],
    place: ["children_count", "institutions_count", "persons_born_count", "relationships_count", "completeness"]
  };
  const INSPECT_GROUPS = ["identity", "life", "career", "location", "geo", "timing", "link",
    "detail", "people", "profile", "content", "assessment", "research", "history",
    "contact", "meta"];

  function inspectShell() {
    return `<aside class="inspect" data-inspect aria-label="${esc(t("inspect.aria"))}">
      <div class="inspect-head">
        <span class="inspect-head-label">${icon("file")} ${esc(t("common.details"))}</span>
        <div class="inspect-nav">
          <button type="button" class="icon-btn" data-inspect-prev
                  title="${esc(t("inspect.prev"))}" aria-label="${esc(t("inspect.prev"))}">‹</button>
          <span data-inspect-index>—</span>
          <button type="button" class="icon-btn" data-inspect-next
                  title="${esc(t("inspect.next"))}" aria-label="${esc(t("inspect.next"))}">›</button>
        </div>
        <span class="spacer"></span>
        <a class="icon-btn" data-inspect-edit href="#" hidden title="${esc(t("common.edit"))}"
           aria-label="${esc(t("common.edit"))}">${icon("edit")}</a>
        <a class="icon-btn" data-inspect-full href="#" hidden title="${esc(t("inspect.full"))}"
           aria-label="${esc(t("inspect.full"))}">${icon("maximize")}</a>
        <button type="button" class="icon-btn" data-inspect-close hidden
                title="${esc(t("common.close"))}"
                aria-label="${esc(t("common.close"))}">${icon("x")}</button>
      </div>
      <div class="inspect-id" data-inspect-id></div>
      <div class="inspect-tabs" data-inspect-tabs role="tablist"></div>
      <div class="inspect-body" data-inspect-body role="tabpanel"></div>
    </aside>`;
  }

  function mapPaneShell() {
    return `<aside class="inspect-map-pane" data-inspect-map-pane aria-label="${esc(t("inspect.map"))}">
      <div class="inspect-head">
        <span class="inspect-head-label">${icon("map-pin")} ${esc(t("inspect.map"))}</span>
        <span class="spacer"></span>
        <a class="btn ghost sm" href="#/geo">${esc(t("view.openGeo"))}</a>
      </div>
      <div class="inspect-map-wrap">
        <div class="inspect-map" data-inspect-map></div>
        <div class="inspect-caption" data-inspect-caption hidden></div>
      </div>
    </aside>`;
  }

  function removeInspectPanes(entity) {
    disposeInspectMap(entity);
    const stage = document.querySelector("[data-list-stage]");
    const pane = document.querySelector("[data-inspect]");
    const mapPane = document.querySelector("[data-inspect-map-pane]");
    if (pane) pane.remove();
    if (mapPane) mapPane.remove();
    if (stage) stage.classList.remove("tri");
  }

  function ensureMapPane(entity) {
    const stage = document.querySelector("[data-list-stage]");
    if (!stage) return null;
    let mapPane = stage.querySelector("[data-inspect-map-pane]");
    if (!mapPane) {
      const wrap = document.createElement("div");
      wrap.innerHTML = mapPaneShell();
      mapPane = wrap.firstElementChild;
      stage.appendChild(mapPane);
      hydrateIcons(mapPane);
    }
    stage.classList.remove("no-map");
    mapPane.hidden = false;
    void entity;
    return mapPane;
  }

  function removeMapPane(entity) {
    disposeInspectMap(entity);
    const stage = document.querySelector("[data-list-stage]");
    const mapPane = document.querySelector("[data-inspect-map-pane]");
    if (mapPane) mapPane.remove();
    if (stage) stage.classList.add("no-map");
  }

  function bindInspect(entity) {
    const pane = document.querySelector("[data-inspect]");
    if (!pane) return;
    const on = (sel, fn) => { const el = document.querySelector(sel); if (el) el.onclick = fn; };
    on("[data-inspect-close]", () => closeInspect(entity));
    on("[data-inspect-prev]", () => stepInspect(entity, -1));
    on("[data-inspect-next]", () => stepInspect(entity, 1));
  }

  function inspectIds(entity) {
    return ((state[entity] && state[entity].data && state[entity].data.items) || [])
      .map(i => i.id);
  }

  function stepInspect(entity, delta) {
    const st = state[entity];
    const ids = inspectIds(entity);
    if (!ids.length) return;
    const idx = ids.indexOf(st.inspectId);
    const next = idx < 0 ? 0 : idx + delta;
    if (next < 0 || next >= ids.length) return;
    openInspect(entity, ids[next]);
  }

  function syncInspectNav(entity) {
    const st = state[entity];
    const pane = document.querySelector("[data-inspect]");
    if (!pane || !st) return;
    const ids = inspectIds(entity);
    const idx = st.inspectId != null ? ids.indexOf(st.inspectId) : -1;
    const label = pane.querySelector("[data-inspect-index]");
    if (label) {
      label.textContent = idx >= 0
        ? `${idx + 1} ${t("inspect.of")} ${ids.length}`
        : "—";
    }
    const prev = pane.querySelector("[data-inspect-prev]");
    const next = pane.querySelector("[data-inspect-next]");
    if (prev) prev.disabled = idx <= 0;
    if (next) next.disabled = idx < 0 || idx >= ids.length - 1;
    const edit = pane.querySelector("[data-inspect-edit]");
    const full = pane.querySelector("[data-inspect-full]");
    const closeBtn = pane.querySelector("[data-inspect-close]");
    if (edit) {
      edit.hidden = !st.inspectId;
      if (st.inspectId) edit.href = `#/entity/${entity}/${st.inspectId}/edit`;
    }
    if (full) {
      full.hidden = !st.inspectId;
      if (st.inspectId) full.href = `#/entity/${entity}/${st.inspectId}`;
    }
    if (closeBtn) closeBtn.hidden = !st.inspectId;
  }

  function refreshInspect(entity) {
    const st = state[entity];
    if (st && st.inspectId) fillInspect(entity, st.inspectId);
  }

  function disposeInspectMap(entity) {
    const st = state[entity];
    if (st && st._inspectPin) {
      try { st._inspectPin.remove(); } catch (e) { /* */ }
      st._inspectPin = null;
    }
    if (st && st._inspectMap) {
      try { st._inspectMap.remove(); } catch (e) { /* already gone */ }
      st._inspectMap = null;
    }
  }

  function markInspected(entity) {
    const id = state[entity] && state[entity].inspectId;
    document.querySelectorAll("[data-scroll-body] [data-id]").forEach(el => {
      el.classList.toggle("inspected", id != null && Number(el.dataset.id) === Number(id));
    });
  }

  function ensureInspectPane(entity) {
    const stage = document.querySelector("[data-list-stage]");
    if (!stage) return null;
    stage.classList.add("tri");
    if (!stage.querySelector("[data-inspect-map-pane]")) stage.classList.add("no-map");
    let pane = stage.querySelector("[data-inspect]");
    if (!pane) {
      const wrap = document.createElement("div");
      wrap.innerHTML = inspectShell();
      pane = wrap.firstElementChild;
      stage.appendChild(pane);
      hydrateIcons(pane);
    }
    bindInspect(entity);
    return pane;
  }

  function closeInspect(entity) {
    const st = state[entity];
    if (!st) return;
    st.inspectId = null;
    st._inspectSeq = (st._inspectSeq || 0) + 1;
    removeInspectPanes(entity);
    markInspected(entity);
  }

  function openInspect(entity, id) {
    const st = state[entity];
    if (!canInspect(entity) || st.view === "map" || !id) return;
    const same = st.inspectId === id && document.querySelector("[data-inspect-ready]");
    st.inspectId = id;
    ensureInspectPane(entity);
    markInspected(entity);
    syncInspectNav(entity);
    const row = document.querySelector(`[data-scroll-body] [data-id="${id}"]`);
    if (row && row.scrollIntoView) {
      const body = document.querySelector("[data-scroll-body]");
      const rect = row.getBoundingClientRect();
      const box = body ? body.getBoundingClientRect() : null;
      if (box && (rect.top < box.top || rect.bottom > box.bottom)) {
        row.scrollIntoView({ block: "nearest" });
      }
    }
    if (!same) fillInspect(entity, id);
    else syncInspectNav(entity);
    requestAnimationFrame(() => {
      const map = state[entity] && state[entity]._inspectMap;
      if (map) { try { map.resize(); } catch (e) { /* not ready */ } }
    });
  }

  function refName(ref, fallback) {
    if (!ref) return fallback || "";
    const ar = A.state.lang === "ar";
    return (ar ? (ref.name_ar || ref.label || ref.name_en) : (ref.name_en || ref.label || ref.name_ar))
      || fallback || "";
  }

  function inspectFieldValue(entity, rec, f) {
    const key = f.key;
    const lab = (rec._labels || {})[key];
    const ref = (rec._refs || {})[key];
    const raw = rec[key];
    if (lab) return A.badge(A.state.lang === "ar" ? lab.ar : lab.en, lab.color);
    if (ref) return `<a href="#/entity/${esc(f.ref)}/${ref.id}">${esc(refName(ref))}</a>`;
    if (raw === null || raw === undefined || raw === "") return `<span class="empty-val">—</span>`;
    if (f.type === "url") {
      return `<a href="${esc(raw)}" target="_blank" rel="noopener">${esc(A.truncate(String(raw), 48))}</a>`;
    }
    if (f.type === "bool") return raw ? esc(t("common.yes")) : esc(t("common.no"));
    if (f.type === "textarea") return esc(A.truncate(String(raw), 280)).replace(/\n/g, "<br>");
    if (f.type === "float" && (key === "latitude" || key === "longitude")) {
      return `<span dir="ltr">${esc(Number(raw).toFixed(5))}</span>`;
    }
    return esc(String(raw));
  }

  function inspectIdentityHtml(entity, rec) {
    const title = A.dispTitle(rec, entity) || rec.code || "";
    const enName = rec.name_en && rec.name_en !== title ? rec.name_en : "";
    const subtitle = enName || (rec.name_original && rec.name_original !== title ? rec.name_original : "");
    const status = rec._labels && rec._labels.record_status_id;
    const comp = (rec._derived || {}).completeness;
    const img = rec.image_url
      ? `<img src="${esc(rec.image_url)}" alt="">`
      : `<span class="initials">${esc(A.initials(title))}</span>`;
    return `<div class="inspect-portrait">${img}</div>
      <div style="min-width:0;flex:1">
        <div class="inspect-kicker">${esc(A.label(entity))}</div>
        <h3 dir="auto">${esc(title)}</h3>
        ${subtitle ? `<div class="inspect-sub" dir="auto">${esc(subtitle)}</div>` : ""}
        <div class="flex wrap" style="gap:5px;margin-top:5px">
          <span class="badge gray mono-cell">${esc(rec.code || "")}</span>
          ${status ? A.statusBadge(status) : ""}
          ${comp != null ? `<span class="badge gray">${esc(String(comp))}%</span>` : ""}
        </div>
        <div class="inspect-actions">
          <a class="btn sm" href="#/map?focus=${esc(entity)}:${rec.id}">${icon("link")} ${esc(t("geo.showOnAtlas"))}</a>
        </div>
      </div>`;
  }

  function linkedEventIds(rec) {
    return (rec.relationships || [])
      .filter(r => r.other_type === "event" && r.other_id)
      .map(r => Number(r.other_id))
      .filter((id, i, arr) => id && arr.indexOf(id) === i);
  }

  function nonEventRelations(rec) {
    return (rec.relationships || []).filter(r => r.other_type !== "event");
  }

  function inspectTabsFor(entity, rec) {
    const spec = A.entitySpec(entity) || {};
    const tabs = [
      { key: "details", label: t("inspect.tab.details") }
    ];
    /* Events lead the related-record frontier — ahead of relations and positions. */
    if (entity !== "event") {
      tabs.push({ key: "events", label: t("inspect.tab.events"),
        n: linkedEventIds(rec).length });
    }
    const rels = entity === "event" ? (rec.relationships || []) : nonEventRelations(rec);
    tabs.push(
      { key: "relations", label: t("inspect.tab.relations"),
        n: rels.length }
    );
    if (spec.has_positions) {
      tabs.push({ key: "positions", label: t("inspect.tab.positions"),
        n: (rec.positions || []).length });
    }
    tabs.push(
      { key: "citations", label: t("inspect.tab.citations"),
        n: (rec.citations || rec.evidence || []).length },
      { key: "attachments", label: t("inspect.tab.attachments"),
        n: (rec.attachments || []).length },
      { key: "history", label: t("inspect.tab.history"),
        n: (rec.history || []).length }
    );
    return tabs;
  }

  function paintInspectTabs(entity, rec) {
    const st = state[entity];
    const host = document.querySelector("[data-inspect-tabs]");
    if (!host) return;
    const tabs = inspectTabsFor(entity, rec);
    if (!tabs.some(tb => tb.key === st.inspectTab)) st.inspectTab = "details";
    host.innerHTML = tabs.map(tb => `
      <button type="button" role="tab" data-inspect-tab="${tb.key}"
              class="${st.inspectTab === tb.key ? "active" : ""}"
              aria-selected="${st.inspectTab === tb.key ? "true" : "false"}">
        ${esc(tb.label)}${tb.n ? `<span class="n">${fmtNum(tb.n)}</span>` : ""}
      </button>`).join("");
    host.querySelectorAll("[data-inspect-tab]").forEach(btn => {
      btn.onclick = () => {
        st.inspectTab = btn.dataset.inspectTab;
        paintInspectTabs(entity, rec);
        paintInspectTab(entity, rec, st._inspectLoc || {});
      };
    });
  }

  function paintInspectTab(entity, rec, loc) {
    const st = state[entity];
    const body = document.querySelector("[data-inspect-body]");
    if (!body) return;
    const tab = st.inspectTab || "details";
    if (tab === "details") body.innerHTML = inspectDetailsHtml(entity, rec, loc);
    else if (tab === "positions") body.innerHTML = inspectPositionsHtml(entity, rec);
    else if (tab === "relations") body.innerHTML = inspectRelationsHtml(entity, rec);
    else if (tab === "events") body.innerHTML = inspectEventsHtml(entity, rec);
    else if (tab === "citations") body.innerHTML = inspectCitationsHtml(entity, rec);
    else if (tab === "attachments") body.innerHTML = inspectAttachmentsHtml(entity, rec);
    else if (tab === "history") body.innerHTML = inspectHistoryHtml(entity, rec);
    else body.innerHTML = "";
    body.dataset.inspectReady = "1";
    body.setAttribute("data-inspect-ready", "1");
    hydrateIcons(body);
    wireInspectTab(entity, rec, body);
    if (tab === "events") loadInspectEvents(entity, rec, body);
  }

  function inspectDetailsHtml(entity, rec, loc) {
    const fields = A.fieldsOf(entity).filter(f => f.group !== "system");
    const groups = {};
    fields.forEach(f => {
      const v = rec[f.key];
      if (v === null || v === undefined || v === "") return;
      (groups[f.group] = groups[f.group] || []).push(f);
    });
    const stats = (INSPECT_STATS[entity] || []).map(key => {
      const f = A.regField(entity, key);
      const v = (rec._derived || {})[key];
      if (!f || v === null || v === undefined || v === "") return "";
      const shown = key === "completeness" ? `${v}%` : fmtNum(v);
      return `<div><b>${esc(String(shown))}</b><span>${esc(A.regLabel(f))}</span></div>`;
    }).join("");
    const tags = (rec.tags || []).map(tg =>
      `<span class="chip">${esc(A.state.lang === "ar" ? (tg.label_ar || tg.label_en) : (tg.label_en || tg.label_ar))}</span>`
    ).join("");
    let placeLine = "";
    if (loc && loc.label) {
      placeLine = loc.placeId
        ? `<a href="#/entity/place/${loc.placeId}">${esc(loc.label)}</a>`
        : esc(loc.label);
    }
    const sections = INSPECT_GROUPS.filter(g => groups[g]).map(g => `
      <div class="inspect-section">
        <div class="inspect-section-title">${esc(t("form.groups." + g) || g)}</div>
        <dl class="dl inspect-dl compact">${groups[g].map(f =>
          `<dt>${esc(A.fieldLabelSafe(f))}</dt><dd>${inspectFieldValue(entity, rec, f)}</dd>`
        ).join("")}</dl>
      </div>`).join("");
    return `<div data-inspect-ready>
      <div class="inspect-loc">${esc(t("inspect.anchor." + entity))}${placeLine ? " · " + placeLine : ""}</div>
      ${stats ? `<div class="inspect-stats">${stats}</div>` : ""}
      ${tags ? `<div class="inspect-tags" style="margin-bottom:10px">${tags}</div>` : ""}
      ${sections || `<div class="inspect-empty">${esc(t("list.noRecords"))}</div>`}
      <div class="inspect-section">
        <div class="inspect-section-title">${esc(t("rec.system"))}</div>
        <dl class="dl inspect-dl compact">
          <dt>${esc(t("common.created"))}</dt>
          <dd>${esc(A.fmtDate(rec.created_at, true))} · ${esc(rec.created_by || "—")}</dd>
          <dt>${esc(t("common.updated"))}</dt>
          <dd>${esc(A.fmtDate(rec.updated_at, true))} · ${esc(rec.updated_by || "—")}</dd>
          <dt>v</dt><dd>${esc(rec.version)}</dd>
        </dl>
      </div>
    </div>`;
  }

  function inspectPositionsHtml(entity, rec) {
    const rows = rec.positions || [];
    return `<div data-inspect-ready>
      <div class="flex" style="margin-bottom:8px">
        <button type="button" class="btn sm primary" data-add-pos>
          ${icon("plus")} ${esc(t("rec.addPosition"))}</button>
      </div>
      ${rows.length ? `<div class="table-wrap"><table class="data compact"><thead><tr>
        <th>${esc(A.t("ui.position"))}</th>
        <th>${esc(A.t("ui.institution"))}</th>
        <th>${esc(A.t("ui.from"))}</th>
        <th>${esc(A.t("ui.to"))}</th></tr></thead><tbody>
        ${rows.map(p => `<tr>
          <td>${esc(A.state.lang === "ar" ? (p.title_ar || p.title_en) : (p.title_en || p.title_ar))}
            ${p.is_current ? A.badge(t("common.yes"), "green") : ""}</td>
          <td>${p.institution_id
            ? `<a href="#/entity/institution/${p.institution_id}">${esc(A.state.lang === "ar"
                ? (p.institution_ar || p.institution_en || "") : (p.institution_en || p.institution_ar || ""))}</a>`
            : "—"}</td>
          <td>${esc(p.start_date || "—")}</td>
          <td>${esc(p.end_date || "—")}</td></tr>`).join("")}
        </tbody></table></div>`
        : `<div class="inspect-empty">${esc(t("list.noRecords"))}</div>`}
    </div>`;
  }

  function inspectRelationsHtml(entity, rec) {
    const rows = entity === "event" ? (rec.relationships || []) : nonEventRelations(rec);
    return `<div data-inspect-ready>
      <div class="flex" style="margin-bottom:8px">
        <button type="button" class="btn sm primary" data-add-rel>
          ${icon("plus")} ${esc(t("rec.addRelationship"))}</button>
      </div>
      ${rows.length ? `<div class="table-wrap"><table class="data compact"><thead><tr>
        <th>${esc(t("log.entity"))}</th>
        <th>${esc(A.t("ui.type"))}</th>
        <th>${esc(A.t("ui.from"))}</th>
        <th>${esc(A.t("ui.to"))}</th></tr></thead><tbody>
        ${rows.map(r => `<tr>
          <td><a href="#/entity/${esc(r.other_type)}/${r.other_id}">${esc(A.truncate(r.other_name || "", 40))}</a>
            <span class="kv-sub">${esc(A.label(r.other_type))}</span></td>
          <td>${esc(A.state.lang === "ar" ? (r.type_ar || r.type_en) : (r.type_en || r.type_ar || ""))}
            ${r.outgoing ? "→" : "←"}</td>
          <td>${esc(r.start_date || "—")}</td>
          <td>${esc(r.end_date || "—")}</td></tr>`).join("")}
        </tbody></table></div>`
        : `<div class="inspect-empty">${esc(t("rec.noRelationships"))}</div>`}
    </div>`;
  }

  function eventTypeLabel(ev) {
    const lab = (ev._labels || {}).event_type_id;
    if (lab) return A.state.lang === "ar" ? (lab.ar || lab.en) : (lab.en || lab.ar);
    return "";
  }

  function eventPlaceLabel(ev) {
    const ref = (ev._refs || {}).place_id;
    return ref ? (ref.label || "") : "";
  }

  function inspectEventsHtml(entity, rec) {
    void entity; void rec;
    return `<div data-inspect-ready>
      <div class="flex" style="margin-bottom:8px">
        <button type="button" class="btn sm primary" data-add-event>
          ${icon("plus")} ${esc(t("rec.addEvent"))}</button>
      </div>
      <div data-inspect-events>
        <div class="skeleton" style="width:70%"></div>
        <div class="skeleton" style="width:92%;margin-top:8px"></div>
      </div>
    </div>`;
  }

  function renderInspectEvents(host, events) {
    if (!host) return;
    if (!events.length) {
      host.innerHTML = `<div class="inspect-empty">${esc(t("rec.noEvents"))}</div>`;
      return;
    }
    host.innerHTML = `<div class="table-wrap"><table class="data compact"><thead><tr>
      <th>${esc(t("inspect.tab.events"))}</th>
      <th>${esc(A.t("ui.type"))}</th>
      <th>${esc(A.t("ui.from"))}</th>
      <th>${esc(A.t("ui.to"))}</th>
      <th>${esc(A.label("place"))}</th></tr></thead><tbody>
      ${events.map(ev => {
        const title = A.dispTitle(ev, "event") || ev.code || `#${ev.id}`;
        const place = eventPlaceLabel(ev);
        const placeId = ev.place_id;
        return `<tr>
          <td><a href="#/entity/event/${ev.id}">${esc(A.truncate(title, 48))}</a>
            ${ev.code ? `<span class="kv-sub mono-cell">${esc(ev.code)}</span>` : ""}</td>
          <td>${esc(eventTypeLabel(ev) || "—")}</td>
          <td>${esc(ev.start_date || "—")}</td>
          <td>${esc(ev.end_date || "—")}</td>
          <td>${placeId
            ? `<a href="#/entity/place/${placeId}">${esc(place || "—")}</a>`
            : "—"}</td></tr>`;
      }).join("")}
      </tbody></table></div>`;
  }

  async function loadInspectEvents(entity, rec, body) {
    const host = body.querySelector("[data-inspect-events]");
    if (!host) return;
    const ids = linkedEventIds(rec);
    if (!ids.length) {
      renderInspectEvents(host, []);
      return;
    }
    try {
      const full = await Promise.all(ids.map(id =>
        api.get(`/api/event/${id}`).catch(() => null)));
      renderInspectEvents(host, full.filter(Boolean));
    } catch (err) {
      host.innerHTML = `<div class="notice err small">${esc(err.message || String(err))}</div>`;
    }
    void entity;
  }

  function inspectCitationsHtml(entity, rec) {
    const rows = rec.citations || rec.evidence || [];
    const summary = rec.evidence_summary || {};
    return `<div data-inspect-ready>
      <div class="flex" style="margin-bottom:8px">
        <button type="button" class="btn sm primary" data-add-cite>
          ${icon("plus")} ${esc(t("rec.linkSource"))}</button>
      </div>
      ${rec._refs && rec._refs.primary_source_id ? `<div class="notice ok small" style="margin-bottom:8px">
        ${esc(t("common.source"))}: <a href="#/entity/source/${rec._refs.primary_source_id.id}">
        ${esc(rec._refs.primary_source_id.label)}</a></div>` : ""}
      ${summary.disputed ? `<div class="notice warn small" style="margin-bottom:8px">
        ${esc(A.state.lang === "ar"
          ? "هذا السجل متنازع عليه: يوجد دليل يناقض أحد ادعاءاته."
          : "This record is contested: at least one source contradicts a claim.")}</div>` : ""}
      <div data-cite-body>${A.evidence
        ? A.evidence.list(rows, { empty: t("rec.noCitations") })
        : (rows.length ? "" : `<div class="inspect-empty">${esc(t("rec.noCitations"))}</div>`)}</div>
    </div>`;
  }

  function inspectAttachmentsHtml(entity, rec) {
    const rows = rec.attachments || [];
    return `<div data-inspect-ready>
      <div class="flex" style="margin-bottom:8px">
        <label class="btn sm primary">${icon("upload")} ${esc(t("rec.uploadFile"))}
          <input type="file" data-att-file style="display:none"></label>
      </div>
      ${rows.length ? `<table class="data compact"><thead><tr>
        <th>${esc(t("common.name"))}</th>
        <th>${esc(A.t("ui.size"))}</th>
        <th></th></tr></thead><tbody>
        ${rows.map(a => `<tr>
          <td>${icon("file")} ${esc(a.filename)}</td>
          <td>${fmtNum(Math.round((a.size_bytes || 0) / 1024))} KB</td>
          <td class="nowrap">
            <a class="icon-btn" href="/api/attachments/${a.id}/download"
               title="${esc(t("common.export"))}">${icon("download")}</a>
            <button type="button" class="icon-btn" data-att-del="${a.id}"
                    title="${esc(t("common.delete"))}">${icon("trash")}</button>
          </td></tr>`).join("")}
        </tbody></table>`
        : `<div class="inspect-empty">${esc(t("list.noRecords"))}</div>`}
    </div>`;
  }

  function inspectHistoryHtml(entity, rec) {
    const rows = rec.history || [];
    return `<div data-inspect-ready>
      ${rows.length ? `<div class="inspect-timeline">${rows.map(h => `
        <div class="item">
          <div class="when">${esc(A.fmtDate(h.changed_at, true))} · ${esc(h.actor || "—")}
            <span class="mono-cell">${esc((h.tx_id || "").slice(0, 8))}</span></div>
          <div class="what">
            <b>${esc(h.action)}</b>
            ${h.field_label ? ` — ${esc(h.field_label)}` : (h.notes ? ` — ${esc(h.notes)}` : "")}
            ${h.old_value ? `<div class="small muted">${esc(t("rec.oldValue"))}: ${esc(A.truncate(h.old_value, 120))}</div>` : ""}
            ${h.new_value ? `<div class="small">${esc(t("rec.newValue"))}: ${esc(A.truncate(h.new_value, 120))}</div>` : ""}
            ${h.reason ? `<div class="small muted">↳ ${esc(h.reason)}</div>` : ""}
          </div>
        </div>`).join("")}</div>`
        : `<div class="inspect-empty">${esc(t("list.noRecords"))}</div>`}
    </div>`;
  }

  function wireInspectTab(entity, rec, body) {
    const reload = () => refreshInspect(entity);
    const addRel = body.querySelector("[data-add-rel]");
    if (addRel) addRel.onclick = () => {
      if (A.addRelationship) A.addRelationship(entity, rec, reload);
      else toast(t("common.error"), "err");
    };
    const addEvent = body.querySelector("[data-add-event]");
    if (addEvent) addEvent.onclick = () => {
      if (A.addEvent) A.addEvent(entity, rec);
      else toast(t("common.error"), "err");
    };
    const addCite = body.querySelector("[data-add-cite]");
    if (addCite) addCite.onclick = () => {
      if (A.evidence && A.evidence.addDialog) {
        A.evidence.addDialog({ entityType: entity, entityId: rec.id, onSaved: reload });
      } else if (A.linkSource) {
        A.linkSource(entity, rec.id, reload);
      }
    };
    if (A.evidence && A.evidence.bind) A.evidence.bind(body, reload);
    const addPos = body.querySelector("[data-add-pos]");
    if (addPos) addPos.onclick = () => addPositionDialog(entity, rec, reload);
    const file = body.querySelector("[data-att-file]");
    if (file) file.onchange = async () => {
      if (!file.files.length) return;
      const fd = new FormData();
      fd.append("file", file.files[0]);
      fd.append("kind", "scan");
      try {
        await api.upload(`/api/${entity}/${rec.id}/attachments`, fd);
        toast(t("common.saved"), "ok");
        reload();
      } catch (err) { toast(err.message, "err"); }
    };
    body.querySelectorAll("[data-att-del]").forEach(b => {
      b.onclick = async () => {
        try {
          await api.del(`/api/attachments/${b.dataset.attDel}`);
          toast(t("common.deleted"), "ok");
          reload();
        } catch (err) { toast(err.message, "err"); }
      };
    });
  }

  function addPositionDialog(entity, rec, onSaved) {
    const body = `
      <div class="grid c2">
        <div class="field"><label>${esc(A.t("ui.titleAr"))}</label>
          <input id="posAr"></div>
        <div class="field"><label>${esc(A.t("ui.titleEn"))}</label>
          <input id="posEn"></div>
      </div>
      <div class="field"><label>${esc(A.t("ui.institution"))}</label>
        <div id="posInstHost"></div></div>
      <div class="grid c2">
        <div class="field"><label>${esc(A.t("ui.from"))}</label>
          <input id="posFrom" placeholder="1950"></div>
        <div class="field"><label>${esc(A.t("ui.to"))}</label>
          <input id="posTo" placeholder="1960"></div>
      </div>
      <div class="field"><label>${esc(t("common.notes"))}</label>
        <input id="posNotes"></div>`;
    const m = A.modal({
      title: t("rec.addPosition"), body, size: "wide",
      buttons: [
        { label: t("common.cancel") },
        { label: t("common.save"), cls: "primary", onClick: async (close, el) => {
            const titleAr = el.querySelector("#posAr").value.trim();
            const titleEn = el.querySelector("#posEn").value.trim();
            if (!titleAr && !titleEn) return toast(t("common.select"), "warn");
            const end = el.querySelector("#posTo").value.trim() || null;
            const next = (rec.positions || []).map(p => ({
              title_ar: p.title_ar, title_en: p.title_en,
              institution_id: p.institution_id, start_date: p.start_date,
              end_date: p.end_date, notes: p.notes, is_current: p.is_current,
              sort_order: p.sort_order
            }));
            next.push({
              title_ar: titleAr || null, title_en: titleEn || null,
              institution_id: instCombo.getValue() || null,
              start_date: el.querySelector("#posFrom").value.trim() || null,
              end_date: end, notes: el.querySelector("#posNotes").value.trim() || null,
              is_current: !end, sort_order: (next.length + 1) * 10
            });
            try {
              await api.put(`/api/${entity}/${rec.id}`, {
                positions: next, version: rec.version,
                _reason: "position added from list"
              });
              toast(t("common.saved"), "ok");
              close();
              onSaved && onSaved();
            } catch (err) { toast(err.message, "err"); }
          } }
      ]
    });
    const instCombo = A.combobox({
      entity: "institution", allowCreate: true, limit: 30,
      placeholder: A.t("ui.findAnInstitution")
    });
    m.body.querySelector("#posInstHost").appendChild(instCombo);
  }

  async function locateRecord(entity, rec) {
    if (entity === "place") {
      if (rec.latitude != null && rec.longitude != null) {
        return { lat: Number(rec.latitude), lon: Number(rec.longitude), label: A.dispTitle(rec, "place") || "" };
      }
      return { label: "" };
    }
    const key = entity === "person" ? "birthplace_id" : "place_id";
    const ref = (rec._refs || {})[key];
    if (!rec[key]) return { label: "" };
    try {
      const place = await api.get(`/api/place/${rec[key]}`);
      const label = A.dispTitle(place, "place") || refName(ref);
      if (place.latitude == null || place.longitude == null) return { label, placeId: place.id };
      return {
        lat: Number(place.latitude), lon: Number(place.longitude),
        label, placeId: place.id
      };
    } catch (e) {
      return { label: refName(ref), placeId: rec[key] };
    }
  }

  function showUnlocated() {
    removeMapPane();
  }

  function mountInspectMap(entity, loc) {
    disposeInspectMap(entity);
    if (loc.lat == null || loc.lon == null || !window.maplibregl) {
      removeMapPane(entity);
      return;
    }
    ensureMapPane(entity);
    const canvas = document.querySelector("[data-inspect-map]");
    if (!canvas) {
      removeMapPane(entity);
      return;
    }
    canvas.classList.remove("is-empty");
    canvas.innerHTML = "";
    const bootStyle = (A.geopin && A.geopin.secondaryStyle)
      ? A.geopin.secondaryStyle("osm")
      : { version: 8, sources: {}, layers: [{ id: "bg", type: "background",
          paint: { "background-color": "#e8eef4" } }] };
    const map = new window.maplibregl.Map({
      container: canvas,
      style: bootStyle,
      center: [loc.lon, loc.lat],
      zoom: 8,
      attributionControl: false
    });
    state[entity]._inspectMap = map;
    state[entity]._inspectPin = null;
    map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      const title = (loc.label || loc.code || "").toString();
      if (A.geopin) {
        state[entity]._inspectPin = A.geopin.marker(map, [loc.lon, loc.lat], {
          etype: entity, label: title, selected: true, size: "lg", showLabel: !!title
        });
      }
      try { map.resize(); } catch (e) { /* container not laid out yet */ }
    });
    requestAnimationFrame(() => { try { map.resize(); } catch (e) { /* gone */ } });
  }

  async function fillInspect(entity, id) {
    const st = state[entity];
    const seq = (st._inspectSeq = (st._inspectSeq || 0) + 1);
    ensureInspectPane(entity);
    const pane = document.querySelector("[data-inspect]");
    if (!pane) return;
    disposeInspectMap(entity);
    removeMapPane(entity);
    const idHost = pane.querySelector("[data-inspect-id]");
    const tabs = pane.querySelector("[data-inspect-tabs]");
    const body = pane.querySelector("[data-inspect-body]");
    if (idHost) idHost.innerHTML = `<div class="skeleton" style="width:70%"></div>`;
    if (tabs) tabs.innerHTML = "";
    if (body) {
      body.innerHTML = `<div class="skeleton" style="width:70%"></div>
        <div class="skeleton" style="width:92%;margin-top:8px"></div>
        <div class="skeleton" style="width:58%;margin-top:8px"></div>`;
    }
    syncInspectNav(entity);
    try {
      const rec = await api.get(`/api/${entity}/${id}`);
      if (seq !== st._inspectSeq || !document.querySelector("[data-inspect]")) return;
      const loc = await locateRecord(entity, rec);
      if (seq !== st._inspectSeq || !document.querySelector("[data-inspect]")) return;
      st._inspectLoc = loc;
      st._inspectRec = rec;
      const liveId = document.querySelector("[data-inspect-id]");
      const liveCap = document.querySelector("[data-inspect-caption]");
      if (!liveId) return;
      liveId.innerHTML = inspectIdentityHtml(entity, rec);
      hydrateIcons(liveId);
      paintInspectTabs(entity, rec);
      paintInspectTab(entity, rec, loc);
      syncInspectNav(entity);
      if (loc && loc.lat != null && loc.lon != null) {
        if (liveCap) {
          liveCap.hidden = false;
          liveCap.innerHTML = `<span>${esc(t("inspect.anchor." + entity))}</span>
            <b dir="ltr">${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}</b>`;
        }
        mountInspectMap(entity, loc);
      } else {
        showUnlocated();
      }
    } catch (err) {
      if (seq !== st._inspectSeq) return;
      const liveBody = document.querySelector("[data-inspect-body]");
      if (liveBody) {
        liveBody.innerHTML = `<div class="notice err small">${esc(err.message || String(err))}</div>`;
      }
      removeMapPane(entity);
    }
  }

  function tableView(entity, data) {
    const st = state[entity];
    const reg = A.registry(entity);
    const cols = st.columns.map(k => reg.find(f => f.key === k)).filter(Boolean);
    const allChecked = data.items.length && data.items.every(i => st.selected.has(i.id));
    const head = cols.map(f => `<th class="${f.sortable ? "sortable" : ""} ${f.kind === "derived" ? "derived-col" : ""}" data-sort="${f.key}"
        title="${esc(f.kind === "derived" ? (t("common.derived") || "derived") : "")}">
        ${f.kind === "derived" ? "ƒ " : ""}${esc(A.regLabel(f))}${st.sort === f.key ? (st.order === "asc" ? " ▲" : " ▼") : ""}</th>`).join("");
    const preview = canInspect(entity) ? ` title="${esc(t("inspect.preview"))}"` : "";
    const rows = data.items.map(item => `
      <tr data-id="${item.id}" class="${st.selected.has(item.id) ? "selected" : ""}${st.inspectId === item.id ? " inspected" : ""}"
          ${st.inspectId === item.id ? 'aria-current="true"' : ""}>
        <td class="nowrap"><input type="checkbox" data-pick="${item.id}" ${st.selected.has(item.id) ? "checked" : ""}></td>
        ${cols.map((f, idx) => {
          if (idx === 0) {
            return `<td class="${f.key === "code" ? "nowrap" : ""}">
              <a class="row-title" href="#/entity/${entity}/${item.id}"${preview}>
                ${f.kind === "derived" ? esc(A.truncate(derivedValue(item, f.key) ?? "", 44))
                  : esc(A.truncate(String(item[f.key] ?? item._title ?? ""), 46))}</a>
              ${f.key === "code" ? "" : `<span class="kv-sub mono-cell">${esc(item.code)}</span>`}</td>`;
          }
          return `<td class="${f.type === "int" || f.type === "float" ? "num" : ""} ${f.key === "code" ? "nowrap" : ""}">
            ${cellHtml(entity, item, f)}</td>`;
        }).join("")}
        <td class="actions nowrap no-print">
          <a class="icon-btn" href="#/entity/${entity}/${item.id}" title="${esc(t("common.view"))}">${icon("eye")}</a>
          <a class="icon-btn" href="#/entity/${entity}/${item.id}/edit" title="${esc(t("common.edit"))}">${icon("edit")}</a>
          <button class="icon-btn" data-del="${item.id}" title="${esc(t("common.delete"))}">${icon("trash")}</button>
        </td></tr>`).join("");
    return `<div class="table-wrap" style="border:0;border-radius:0">
      <table class="data ${A.state.density === "compact" ? "compact" : ""}">
        <thead><tr>
          <th style="width:34px"><input type="checkbox" data-pick-all ${allChecked ? "checked" : ""}></th>
          ${head}<th class="no-print">${t("common.actions")}</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
  }

  function cardFacts(entity, item) {
    const st = state[entity];
    return (st.layout.factFields || []).map(key => {
      const f = A.regField(entity, key);
      if (!f) return "";
      if (f.kind === "derived") {
        const v = derivedValue(item, key);
        return v === null || v === undefined || v === "" ? "" :
          `<span>${esc(A.regLabel(f))}: <b>${esc(v)}</b></span>`;
      }
      const lab = (item._labels || {})[key];
      const ref = (item._refs || {})[key];
      if (lab) return `<span>${esc(A.state.lang === "ar" ? lab.ar : lab.en)}</span>`;
      if (ref) return `<span>${esc(A.truncate(ref.label || "", 26))}</span>`;
      const v = item[key];
      if (v === null || v === undefined || v === "") return "";
      if (f.type === "date") return `<span>${esc(v)}</span>`;
      if (f.type === "url") return `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(A.truncate(v, 22))}</a>`;
      return `<span>${esc(A.truncate(String(v), 30))}</span>`;
    }).join("");
  }

  function cardStats(entity, item) {
    const st = state[entity];
    return (st.layout.statFields || []).map(key => {
      const f = A.regField(entity, key);
      const v = derivedValue(item, key);
      if (!f || v === null || v === undefined) return "";
      return `<div><b>${fmtNum(v)}</b><span>${esc(A.regLabel(f))}</span></div>`;
    }).join("");
  }

  function cardView(entity, data, gallery) {
    const st = state[entity];
    const L = st.layout;
    return `<div class="cardgrid ${gallery ? "gallery" : ""}" style="padding:14px">
      ${data.items.map(item => {
        const title = L.titleField ? (item[L.titleField] || A.dispTitle(item, entity)) : A.dispTitle(item, entity);
        const subtitle = L.subtitleField ? item[L.subtitleField] : null;
        const img = L.imageField ? item[L.imageField] : null;
        const badge = L.badgeField ? (item._labels || {})[L.badgeField] : null;
        const facts = cardFacts(entity, item);
        const stats = cardStats(entity, item);
        return `<article class="ecard ${gallery ? "gallery" : ""}${st.inspectId === item.id ? " inspected" : ""}"
          data-id="${item.id}" ${st.inspectId === item.id ? 'aria-current="true"' : ""}>
          <div class="quick no-print">
            <a class="icon-btn" href="#/entity/${entity}/${item.id}/edit" title="${esc(t("common.edit"))}">${icon("edit")}</a>
            <button class="icon-btn" data-del="${item.id}" title="${esc(t("common.delete"))}">${icon("trash")}</button>
          </div>
          <div class="media${img ? "" : " plain"}">
            ${img ? `<img src="${esc(img)}" alt="" loading="lazy"
                       onerror="this.parentNode.innerHTML='<span class=\\'initials\\'>${esc(A.initials(title))}</span>'">`
                  : `<span class="initials">${esc(A.initials(title))}</span>`}
            <div class="media-badges">
              <span class="badge gray mono-cell">${esc(item.code)}</span>
              ${badge ? `<span class="badge ${badge.color || "gray"}">${esc(A.state.lang === "ar" ? badge.ar : badge.en)}</span>` : ""}
            </div>
          </div>
          <div class="body">
            <div class="code">${esc(A.label(entity))}${item.deleted_at ? " · " + (t("common.deleted")) : ""}</div>
            <h4><a href="#/entity/${entity}/${item.id}"${canInspect(entity) ? ` title="${esc(t("inspect.preview"))}"` : ""}>${esc(A.truncate(title || "", 60))}</a></h4>
            ${subtitle ? `<div class="sub">${esc(A.truncate(subtitle, 60))}</div>` : ""}
            ${facts ? `<div class="factline">${facts}</div>` : ""}
            ${stats ? `<div class="statrow">${stats}</div>` : ""}
          </div>
        </article>`;
      }).join("")}</div>`;
  }

  function rowView(entity, data) {
    const st = state[entity];
    const L = st.layout;
    return `<div class="rowlist">
      ${data.items.map(item => {
        const title = L.titleField ? (item[L.titleField] || A.dispTitle(item, entity)) : A.dispTitle(item, entity);
        const subtitle = L.subtitleField ? item[L.subtitleField] : null;
        const img = L.imageField ? item[L.imageField] : null;
        const stats = (L.statFields || []).slice(0, 3).map(key => {
          const f = A.regField(entity, key);
          const v = derivedValue(item, key);
          return f && v !== null && v !== undefined ? `<span><b>${fmtNum(v)}</b> ${esc(A.regLabel(f))}</span>` : "";
        }).join("");
        return `<div class="rrow${st.inspectId === item.id ? " inspected" : ""}" data-id="${item.id}"
          ${st.inspectId === item.id ? 'aria-current="true"' : ""}>
          <div class="ravatar">${img ? `<img src="${esc(img)}" alt="" onerror="this.replaceWith(document.createTextNode('${esc(A.initials(title))}'))">`
            : esc(A.initials(title))}</div>
          <div><div class="rtitle"><a href="#/entity/${entity}/${item.id}"${canInspect(entity) ? ` title="${esc(t("inspect.preview"))}"` : ""}>${esc(A.truncate(title || "", 70))}</a></div>
            <div class="rmeta">${esc(item.code)}${subtitle ? " · " + esc(A.truncate(subtitle, 50)) : ""}</div></div>
          <div class="rstats">${stats}</div>
          <div class="nowrap">
            <a class="icon-btn" href="#/entity/${entity}/${item.id}/edit">${icon("edit")}</a>
            <button class="icon-btn" data-del="${item.id}">${icon("trash")}</button></div>
        </div>`;
      }).join("")}</div>`;
  }

  /* --------------------------------------------------------- wiring --- */
  function wire(entity, host) {
    const st = state[entity];
    const qEl = host.querySelector("[data-list-q]");
    let qt;
    if (qEl) qEl.oninput = () => {
      st.q = qEl.value;
      // typing in the search box means the typed query is no longer the authority
      if (st.query) { st.query = ""; st.queryInfo = null; }
      clearTimeout(qt);
      qt = setTimeout(() => { st.page = 1; reload(entity); }, 320);
    };

    /* The query bar speaks the same filter engine, in text.  Applying one clears
       the builder's clauses: two spellings of one filter must never disagree. */
    const qBar = host.querySelector("[data-query]");
    if (qBar) {
      qBar.oninput = () => { st.queryDraft = qBar.value; };
      qBar.onkeydown = (ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); applyQuery(entity); }
        if (ev.key === "Escape") { qBar.value = ""; clearQuery(entity); }
      };
    }
    if (!state._resizeBound) {
      state._resizeBound = true;
      let rt;
      window.addEventListener("resize", () => {
        clearTimeout(rt);
        rt = setTimeout(() => {
          fitShell(); measureToolbar(document); syncDockOffset();
          Object.keys(state).forEach(ent => {
            const map = state[ent] && state[ent]._inspectMap;
            if (map) { try { map.resize(); } catch (e) { /* pane already gone */ } }
          });
        }, 120);
      });
    }
    const on = (sel, fn) => { const el = host.querySelector(sel); if (el) el.onclick = fn; };
    on("[data-query-clear]", () => clearQuery(entity));
    on("[data-query-copy]", async () => {
      const bare = payload(entity);
      delete bare.query;
      try {
        const res = await api.post("/api/query/render", { entity, payload: bare });
        if (!res.query) return toast(t("list.queryEmpty"), "warn");
        st.query = res.query; st.queryDraft = res.query; st.queryInfo = null;
        st.q = ""; st.where = [{ op: "eq" }]; st.page = 1;
        setHash(entity, res.query);
        if (res.unsupported && res.unsupported.length) {
          toast(t("list.queryPartial") + ": " + res.unsupported.join(", "), "warn");
        }
        await reload(entity);
      } catch (err) { toast(err.message, "err"); }
    });
    on("[data-toggle-filters]", () => {
      st.showFilters = !st.showFilters;
      const dock = document.querySelector("[data-filters-host]");
      if (dock) dock.classList.toggle("hidden", !st.showFilters);
      renderFilters(entity);
      syncDockOffset();
    });
    host.querySelectorAll("[data-view]").forEach(b => {
      b.onclick = () => {
        disposeListMap(entity);
        st.view = b.dataset.view;
        persist(entity);
        draw(entity);
      };
    });
    on("[data-layout]", () => openLayout(entity));
    on("[data-cols]", () => openColumns(entity));
    on("[data-saved]", () => openSavedViews(entity));
    on("[data-dups]", () => openDuplicates(entity));
    on("[data-export]", () => A.openExportModal(entity));
    on("[data-clear-chips]", () => { st.where = []; st.q = ""; st.page = 1; reload(entity); });
    on("[data-bulk-clear]", () => { st.selected.clear(); draw(entity); });
    on("[data-bulk-delete]", () => bulkAction(entity, "delete"));
    on("[data-bulk-restore]", () => bulkAction(entity, "restore"));
    on("[data-bulk-status]", () => bulkSetStatus(entity));
    on("[data-bulk-merge]", () => {
      const ids = Array.from(st.selected);
      if (ids.length < 2) return toast(A.t("ui.selectAtLeastTwoRecords"), "warn");
      mergeDialog(entity, ids[0], ids.slice(1), () => { st.selected.clear(); reload(entity); });
    });
    host.dataset.listEntity = entity;
    if (!host._inspectEsc) {
      host._inspectEsc = true;
      host.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        const ent = host.dataset.listEntity;
        if (!ent || !state[ent] || !state[ent].inspectId) return;
        if (ev.target.closest("input, textarea, select")) return;
        ev.preventDefault();
        closeInspect(ent);
      });
    }
    syncDockOffset();
  }

  /** Keep the sticky filter dock directly under the sticky toolbar. */
  function syncDockOffset() {
    const bar = document.querySelector("[data-list-toolbar]");
    const dock = document.querySelector("[data-filters-host]");
    if (dock && bar) dock.style.setProperty("--dock-top", `calc(var(--topbar-h) + ${bar.offsetHeight}px)`);
  }

  /** Wiring for everything that is re-rendered on "load more". */
  function wireViewport(entity) {
    const st = state[entity];
    const body = document.querySelector("[data-scroll-body]");
    const footer = document.querySelector("[data-list-footer]");
    const scope = [body, footer].filter(Boolean);
    if (!scope.length) return;
    const all = (sel) => scope.flatMap(el => Array.from(el.querySelectorAll(sel)));

    all("[data-sort]").forEach(th => {
      th.onclick = () => {
        const key = th.dataset.sort;
        if (st.sort === key) st.order = st.order === "asc" ? "desc" : "asc";
        else { st.sort = key; st.order = "asc"; }
        st.page = 1;
        reload(entity);
      };
    });
    all("[data-page]").forEach(b => {
      b.onclick = () => { st.page = Number(b.dataset.page); reload(entity); };
    });
    all("[data-load-more]").forEach(b => { b.onclick = () => loadMore(entity); });
    all("[data-pagesize]").forEach(sel => {
      sel.onchange = (e) => { st.page_size = Number(e.target.value); st.page = 1; reload(entity); };
    });
    all("[data-pick-all]").forEach(pickAll => {
      pickAll.onchange = () => {
        (st.data.items || []).forEach(i => pickAll.checked ? st.selected.add(i.id) : st.selected.delete(i.id));
        draw(entity);
      };
    });
    all("[data-pick]").forEach(cb => {
      cb.onchange = () => {
        const id = Number(cb.dataset.pick);
        if (cb.checked) st.selected.add(id); else st.selected.delete(id);
        draw(entity);
      };
    });
    all("[data-del]").forEach(b => {
      b.onclick = (e) => { e.preventDefault(); deleteRecord(entity, Number(b.dataset.del), () => reload(entity)); };
    });

    if (body && canInspect(entity) && !body.dataset.inspectWired) {
      body.dataset.inspectWired = "1";
      body.addEventListener("click", (ev) => {
        const cur = state[entity];
        if (!cur || cur.view === "map") return;
        if (ev.target.closest("button, input, textarea, select, label")) return;
        const row = ev.target.closest("[data-id]");
        if (!row || !body.contains(row)) return;
        const id = Number(row.dataset.id);
        if (!id) return;
        const link = ev.target.closest("a");
        if (link) {
          const href = link.getAttribute("href") || "";
          const self = href === `#/entity/${entity}/${id}`;
          if (!self || link.classList.contains("icon-btn")) return;
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
          ev.preventDefault();
        }
        openInspect(entity, id);
      });
      body.addEventListener("keydown", (ev) => {
        const cur = state[entity];
        if (!cur || cur.view === "map") return;
        if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
        if (ev.target.closest("input, textarea, select")) return;
        const items = Array.from(body.querySelectorAll("[data-id]"));
        if (!items.length) return;
        const curIdx = items.findIndex(el => Number(el.dataset.id) === cur.inspectId);
        let next = ev.key === "ArrowDown" ? curIdx + 1 : curIdx - 1;
        if (curIdx < 0) next = ev.key === "ArrowDown" ? 0 : items.length - 1;
        next = Math.max(0, Math.min(items.length - 1, next));
        ev.preventDefault();
        openInspect(entity, Number(items[next].dataset.id));
      });
    }
  }

  /** Infinite-ish scrolling: append the next page when the user reaches the end. */
  function wireAutoLoad(entity) {
    const body = document.querySelector("[data-scroll-body]");
    if (!body) return;
    body.onscroll = () => {
      const st = state[entity];
      const nearEnd = body.scrollTop + body.clientHeight >= body.scrollHeight - 160;
      if (nearEnd && (st.data.items || []).length < (st.data.total || 0) &&
          (!st.autoLoadAt || Date.now() - st.autoLoadAt > 600)) {
        st.autoLoadAt = Date.now();
        loadMore(entity);
      }
    };
  }

  /* ------------------------------------------------- column chooser --- */
  function openColumns(entity) {
    const st = state[entity];
    const reg = A.registry(entity);
    const groups = {};
    reg.forEach(f => {
      const g = f.kind === "derived" ? "derived" : f.group;
      (groups[g] = groups[g] || []).push(f);
    });
    const body = `<div class="notice small">${A.t("ui.fieldsMarkedAreComputedFromRelatedTabl")}</div>
      <div class="flex wrap" style="margin:10px 0">
        <button class="btn sm" data-preset="default">${t("common.reset")}</button>
        <button class="btn sm" data-preset="all">${t("common.all")}</button>
        <button class="btn sm" data-preset="derived">ƒ ${t("common.derived") || "derived"}</button>
      </div>
      ${Object.keys(groups).map(g => `
        <div style="margin-bottom:12px">
          <div class="sectionlabel">${esc(g === "derived" ? (A.t("ui.relatedTables")) : (t("form.groups." + g) || g))}</div>
          <div class="layout-grid">
            ${groups[g].map(f => `<label class="check">
              <input type="checkbox" data-col="${f.key}" ${st.columns.includes(f.key) ? "checked" : ""}>
              ${f.kind === "derived" ? "ƒ " : ""}${esc(A.regLabel(f))}</label>`).join("")}
          </div></div>`).join("")}
      <div class="flex" style="margin-top:8px">
        <input id="colOrder" placeholder="${A.t("ui.customOrderCommaSeparatedFieldKeys")}"
          value="${esc(st.columns.join(","))}" style="flex:1;padding:7px 9px;border:1px solid var(--border-strong);border-radius:8px;font:inherit;font-size:.83rem">
      </div>`;
    const m = A.modal({
      title: t("list.columns"), body, size: "wide",
      buttons: [
        { label: t("common.cancel") },
        { label: t("common.apply"), cls: "primary", onClick: (close, el) => {
            const order = (el.querySelector("#colOrder").value || "").split(",")
              .map(s => s.trim()).filter(Boolean);
            const checked = Array.from(el.querySelectorAll("[data-col]:checked")).map(c => c.dataset.col);
            const final = order.filter(k => checked.includes(k));
            checked.forEach(k => { if (!final.includes(k)) final.push(k); });
            st.columns = final.length ? final : ["code"];
            persist(entity);
            close(); draw(entity);
          } }
      ]
    });
    m.body.querySelectorAll("[data-preset]").forEach(b => {
      b.onclick = () => {
        const p = b.dataset.preset;
        m.body.querySelectorAll("[data-col]").forEach(c => {
          if (p === "all") c.checked = true;
          else if (p === "derived") c.checked = A.regField(entity, c.dataset.col).kind === "derived";
          else c.checked = A.regField(entity, c.dataset.col).in_list;
        });
        const checked = Array.from(m.body.querySelectorAll("[data-col]:checked")).map(c => c.dataset.col);
        m.body.querySelector("#colOrder").value = checked.join(",");
      };
    });
  }

  /* --------------------------------------------------- card layout --- */
  function openLayout(entity) {
    const st = state[entity];
    const reg = A.registry(entity).filter(f => !f.system);
    const textish = reg.filter(f => ["text", "textarea"].includes(f.type) || f.kind === "derived");
    const selectish = reg.filter(f => f.type === "select");
    const numish = reg.filter(f => f.kind === "derived" && f.type === "int");
    const opt = (f, sel) => `<option value="${f.key}" ${sel === f.key ? "selected" : ""}>${esc(A.regLabel(f))}</option>`;

    const body = `<div class="grid c2">
        <div class="field"><label>${A.t("ui.imageField")}</label>
          <select id="lyImage"><option value="">—</option>
            ${reg.filter(f => f.type === "url" || f.key === "image_url").map(f => opt(f, st.layout.imageField)).join("")}
          </select>
          <div class="field-note">${A.t("ui.rendersAnIllustratedCardWhenAUrlIsPres")}</div></div>
        <div class="field"><label>${A.t("ui.titleField")}</label>
          <select id="lyTitle">${textish.map(f => opt(f, st.layout.titleField)).join("")}</select></div>
        <div class="field"><label>${A.t("ui.subtitleField")}</label>
          <select id="lySub"><option value="">—</option>${textish.map(f => opt(f, st.layout.subtitleField)).join("")}</select></div>
        <div class="field"><label>${A.t("ui.badgeField")}</label>
          <select id="lyBadge"><option value="">—</option>${selectish.map(f => opt(f, st.layout.badgeField)).join("")}</select></div>
      </div>
      <div class="sectionlabel">${A.t("ui.factLinesUpTo4")}</div>
      <div class="layout-grid">${reg.map(f => `<label class="check"><input type="checkbox" data-fact="${f.key}"
        ${(st.layout.factFields || []).includes(f.key) ? "checked" : ""}> ${f.kind === "derived" ? "ƒ " : ""}${esc(A.regLabel(f))}</label>`).join("")}</div>
      <div class="sectionlabel">${A.t("ui.statFiguresOnTheCard")}</div>
      <div class="layout-grid">${(numish.length ? numish : reg).map(f => `<label class="check"><input type="checkbox" data-stat="${f.key}"
        ${(st.layout.statFields || []).includes(f.key) ? "checked" : ""}> ${esc(A.regLabel(f))}</label>`).join("")}</div>
      <div class="layout-preview" data-preview></div>`;
    const m = A.modal({
      title: (t("view.layout") || "Card layout") + " — " + A.pluralOf(entity),
      body, size: "wide",
      buttons: [
        { label: t("common.cancel") },
        { label: t("common.apply"), cls: "primary", onClick: (close, el) => {
            st.layout = {
              imageField: el.querySelector("#lyImage").value || null,
              titleField: el.querySelector("#lyTitle").value || null,
              subtitleField: el.querySelector("#lySub").value || null,
              badgeField: el.querySelector("#lyBadge").value || null,
              factFields: Array.from(el.querySelectorAll("[data-fact]:checked")).map(c => c.dataset.fact).slice(0, 4),
              statFields: Array.from(el.querySelectorAll("[data-stat]:checked")).map(c => c.dataset.stat).slice(0, 4)
            };
            persist(entity);
            close();
            if (st.view === "table") { st.view = "cards"; persist(entity); }
            draw(entity);
          } }
      ]
    });
    const preview = () => {
      const sample = (st.data && st.data.items && st.data.items[0]) || {};
      const el = m.body.querySelector("[data-preview]");
      const tmp = { ...st.layout,
        factFields: Array.from(m.body.querySelectorAll("[data-fact]:checked")).map(c => c.dataset.fact).slice(0, 4),
        statFields: Array.from(m.body.querySelectorAll("[data-stat]:checked")).map(c => c.dataset.stat).slice(0, 4),
        imageField: m.body.querySelector("#lyImage").value || null,
        badgeField: m.body.querySelector("#lyBadge").value || null };
      const saved = state[entity].layout;
      state[entity].layout = tmp;
      el.innerHTML = `<div class="sectionlabel">${A.t("ui.preview")}</div>
        <div class="cardgrid" style="grid-template-columns:minmax(0,260px)">${cardView(entity, { items: [sample] }, false)}</div>`;
      state[entity].layout = saved;
    };
    m.body.querySelectorAll("select, [data-fact], [data-stat]").forEach(el => {
      el.addEventListener("change", preview);
    });
    preview();
  }

  /* -------------------------------------------------------- saved views --- */
  async function openSavedViews(entity) {
    const st = state[entity];
    const views = await api.get(`/api/saved-views?entity_type=${entity}`);
    st.savedViews = views;
    const body = `
      <div class="field"><label>${t("list.viewName")}</label><input id="viewName" placeholder="…"></div>
      <div class="notice small">${t("list.exportWhat")}</div>
      <hr class="hr-soft">
      ${views.length ? `<table class="data compact"><thead><tr><th>${t("common.name")}</th><th></th></tr></thead><tbody>
        ${views.map(v => `<tr><td>${esc(v.name)}</td><td class="nowrap right">
          <button class="btn sm" data-load="${v.id}">${t("common.apply")}</button>
          <button class="btn sm ghost" data-un="${v.id}">${t("common.delete")}</button></td></tr>`).join("")}
      </tbody></table>` : `<div class="muted small">${t("list.noRecords")}</div>`}`;
    const m = A.modal({
      title: t("list.saved"), body, size: "slim",
      buttons: [
        { label: t("common.close") },
        { label: t("list.saveView"), cls: "primary", onClick: async (close, el) => {
            const name = el.querySelector("#viewName").value.trim();
            if (!name) return toast(t("list.viewName"), "warn");
            await api.post("/api/saved-views", {
              name, entity_type: entity, filters: payload(entity),
              columns: st.columns,
              sort: { view: st.view, layout: st.layout }
            });
            toast(t("common.saved"), "ok");
            close(); openSavedViews(entity);
          } }
      ]
    });
    m.body.querySelectorAll("[data-load]").forEach(b => {
      b.onclick = () => {
        const v = views.find(x => String(x.id) === b.dataset.load);
        if (!v) return;
        st.where = (v.filters.where || []).map(r => ({ ...r }));
        st.logic = v.filters.logic || "and";
        st.q = v.filters.q || "";
        st.include_deleted = !!v.filters.include_deleted;
        st.only_deleted = !!v.filters.only_deleted;
        if (v.columns && v.columns.length) st.columns = v.columns;
        try {
          const sort = typeof v.sort === "string" ? JSON.parse(v.sort) : v.sort;
          if (sort && sort.view) st.view = sort.view;
          if (sort && sort.layout) st.layout = Object.assign(st.layout, sort.layout);
        } catch (e) { /* ignore */ }
        st.page = 1;
        persist(entity);
        m.close(); renderFilters(entity); reload(entity);
      };
    });
    m.body.querySelectorAll("[data-un]").forEach(b => {
      b.onclick = async () => { await api.del(`/api/saved-views/${b.dataset.un}`); m.close(); openSavedViews(entity); };
    });
  }

  /* --------------------------------------------------------- duplicates --- */
  async function openDuplicates(entity) {
    const res = await api.get(`/api/${entity}/duplicates`);
    const groups = res.groups || [];
    const body = groups.length ? `
      <div class="notice small">${A.t("ui.recordsWhoseNamesCollideAfterArabicNor")}</div>
      ${groups.map((g, i) => `<div class="card" style="box-shadow:none;padding:10px 12px">
        <div class="flex"><b>${esc(g.records[0].title)}</b>
          <span class="badge amber">${g.count}</span><span class="spacer"></span>
          <button class="btn sm" data-merge-group="${i}">${A.t("ui.merge")}</button></div>
        <table class="data compact" style="margin-top:6px">
          <thead><tr><th>${t("common.code")}</th><th>${t("common.name")}</th>
            <th class="num">${A.t("ui.completeness")}</th>
            <th>${t("common.updated")}</th><th></th></tr></thead>
          <tbody>${g.records.map(r => `<tr>
            <td class="mono-cell">${esc(r.code)}</td><td>${esc(r.title)}</td>
            <td class="num">${r.completeness === null || r.completeness === undefined ? "—" : r.completeness + "%"}</td>
            <td class="small muted">${esc(A.ago(r.updated_at))}</td>
            <td><a class="icon-btn" href="#/entity/${entity}/${r.id}" target="_blank">${icon("eye")}</a></td>
          </tr>`).join("")}</tbody></table></div>`).join("")}`
      : `<div class="empty">${A.t("ui.noDuplicateCandidatesFound")}</div>`;
    /* focus goes to the dialog itself, never to the first "Merge" button: a
       stray Enter must not merge two real records */
    const m = A.modal({ title: `${t("common.duplicates") || "Duplicates"} — ${A.pluralOf(entity)}`,
                        body, size: "wide", focus: ".modal-title" });
    m.body.querySelectorAll("[data-merge-group]").forEach(b => {
      b.onclick = () => {
        const g = groups[Number(b.dataset.mergeGroup)];
        mergeDialog(entity, g.records[0].id, g.records.slice(1).map(r => r.id), () => {
          m.close(); reload(entity);
        });
      };
    });
  }

  function mergeDialog(entity, keepId, mergeIds, done) {
    const st = state[entity];
    const all = (st.data && st.data.items) || [];
    const describe = (id) => {
      const it = all.find(i => i.id === id);
      return it ? `${it.code} · ${esc(it._title || "")}` : `#${id}`;
    };
    const body = `<div class="notice warn">${A.t("ui.thePrimaryRecordIsKeptRelationshipsCit")}</div>
      <div class="field"><label>${A.t("ui.primaryRecord")}</label>
        <select id="mgKeep">${[keepId].concat(mergeIds).map(id =>
          `<option value="${id}">${describe(id)}</option>`).join("")}</select></div>
      <div class="field"><label>${t("common.reason")}</label><input id="mgReason" value="duplicate merge"></div>
      <div data-plan></div>`;
    const m = A.modal({
      title: A.t("ui.mergeRecords"), body, size: "slim",
      buttons: [
        { label: t("common.cancel") },
        { label: A.t("ui.previewPlan"), onClick: async (close, el) => {
            const keep = Number(el.querySelector("#mgKeep").value);
            const plan = await api.post(`/api/${entity}/${keep}/merge`,
              { merge_ids: mergeIds.filter(i => i !== keep), dry_run: true });
            el.querySelector("[data-plan]").innerHTML = `
              <div class="notice ok small">${A.t("ui.willMerge")}
                ${plan.merged.length} → <b>${esc(plan.keep.code)}</b> ·
                ${A.t("ui.fieldsToFill")}: ${plan.fields_filled.length}</div>`;
          } },
        { label: A.t("ui.mergeNow"), cls: "danger", onClick: async (close, el) => {
            const keep = Number(el.querySelector("#mgKeep").value);
            const ids = mergeIds.filter(i => i !== keep);
            /* a merge hides records: state exactly what will happen, and ask */
            const ok = await A.confirmDialog({
              title: A.t("ui.mergeRecords"),
              message: `${A.t("ui.willMerge")} ${ids.length} → ${describe(keep)}. ` +
                       `${A.t("ui.thePrimaryRecordIsKeptRelationshipsCit")}`,
              confirmLabel: A.t("ui.mergeNow"), danger: true
            });
            if (!ok) return;
            try {
              const res = await api.post(`/api/${entity}/${keep}/merge`,
                { merge_ids: ids, reason: el.querySelector("#mgReason").value });
              toast(`${A.t("ui.merged")} ${res.merged.length} → ${res.keep.code}`, "ok");
              close();
              done && done();
            } catch (err) { toast(err.message, "err"); }
          } }
      ]
    });
  }

  /* ------------------------------------------------------------ actions --- */
  async function deleteRecord(entity, id, cb) {
    const ok = await A.confirmDialog({
      title: t("rec.deleteTitle"), message: t("rec.deleteBody"), danger: true,
      confirmLabel: t("common.delete"),
      extra: `<div class="field" style="margin-top:12px"><label>${esc(t("common.reason"))}</label>
        <input id="delReason" placeholder="${esc(t("common.reasonPh"))}"></div>`
    });
    if (!ok) return;
    const reason = (document.getElementById("delReason") || {}).value || "";
    try {
      await api.del(`/api/${entity}/${id}?reason=${encodeURIComponent(reason)}`);
      toast(t("common.deleted"), "ok");
      cb && cb();
    } catch (err) { toast(err.message, "err"); }
  }
  A.deleteRecord = deleteRecord;

  async function bulkAction(entity, action) {
    const st = state[entity];
    const ids = Array.from(st.selected);
    const ok = await A.confirmDialog({
      title: `${action} — ${ids.length} ${t("common.records")}`,
      message: action === "delete" ? t("rec.deleteBody") : "",
      danger: action === "delete", confirmLabel: t("common.confirm")
    });
    if (!ok) return;
    try {
      const res = await api.post(`/api/${entity}/bulk`, { ids, action });
      toast(`${res.ok} ok · ${res.failed} failed`, res.failed ? "warn" : "ok");
      st.selected.clear();
      reload(entity);
    } catch (err) { toast(err.message, "err"); }
  }

  async function bulkSetStatus(entity) {
    const st = state[entity];
    const options = A.domainOptions("record_status");
    A.modal({
      title: t("list.bulkStatus"), size: "slim",
      body: `<div class="field"><label>${t("common.status")}</label>
          <select id="bulkStatus">${options.map(o =>
            `<option value="${o.id}">${esc(A.state.lang === "ar" ? o.label_ar : o.label_en)}</option>`).join("")}</select></div>
        <div class="field"><label>${t("common.reason")}</label><input id="bulkReason"></div>`,
      buttons: [
        { label: t("common.cancel") },
        { label: t("common.save"), cls: "primary", onClick: async (close, body) => {
            try {
              const res = await api.post(`/api/${entity}/bulk`, {
                ids: Array.from(st.selected), action: "status",
                patch: { record_status_id: Number(body.querySelector("#bulkStatus").value) },
                reason: body.querySelector("#bulkReason").value
              });
              toast(`${res.ok} ok · ${res.failed} failed`, "ok");
              st.selected.clear(); close(); reload(entity);
            } catch (err) { toast(err.message, "err"); }
          } }
      ]
    });
  }

  /* ------------------------------------------------------------- view --- */
  A.views.list = async function (root, params) {
    const entity = params.entity;
    root.dataset.surface = "list:" + entity;
    if (!state[entity]) state[entity] = initialState(entity);
    const st = state[entity];
    if (!st.savedViews || !st.savedViews.length) {
      try { st.savedViews = await api.get(`/api/saved-views?entity_type=${entity}`); } catch (e) { /* ignore */ }
    }
    const spec = A.entitySpec(entity) || {};
    if (params && typeof params.q === "string" && params.q !== st.query) {
      st.query = params.q;
      st.queryInfo = null;
      st.q = ""; st.where = [{ op: "eq" }]; st.page = 1;
    }
    A.crumbs([{ label: t("nav.entities") }, { label: A.pluralOf(entity) }]);
    root.innerHTML = A.pageHead(
      A.pluralOf(entity),
      A.state.lang === "ar" ? spec.description_ar : spec.description_en,
      `<a class="btn" href="#/reports/custom">${icon("chart")} ${t("nav.reports")}</a>
       <button class="btn" id="listExport">${icon("download")} ${t("common.export")}</button>
       <a class="btn primary" href="#/entity/${entity}/new">${icon("plus")} ${t("common.add")}</a>`)
      + `<div class="filter-dock${st.showFilters ? "" : " hidden"}" data-filters-host
             aria-label="${esc(t("list.filters"))}"></div>
         <div data-table-host></div>`;
    hydrateIcons(root);
    root.querySelector("#listExport").onclick = () => A.openExportModal(entity);
    renderFilters(entity);
    await reload(entity);
  };
  A.views.list.__dispose = function () {
    Object.keys(state).forEach(entity => {
      if (!state[entity]) return;
      disposeListMap(entity);
      disposeInspectMap(entity);
    });
  };

  A.openExportModal = openExport;
  A.listPayload = payload;
  A.openLayout = openLayout;
  A.openDuplicates = openDuplicates;
  A.mergeDialog = mergeDialog;

  /* ---------------------------------------------------------- export --- */
  function openExport(entity, presetFilters) {
    const st = state[entity];
    const reg = A.registry(entity);
    const body = `
      <div class="grid c2">
        <div class="field"><label>${t("exp.format")}</label>
          <select id="exFormat"><option value="xlsx">XLSX — Excel workbook</option>
            <option value="csv" selected>CSV — UTF-8 with BOM</option>
            <option value="tsv">TSV</option><option value="json">JSON</option></select></div>
        <div class="field"><label>${t("exp.lang")}</label>
          <select id="exLang"><option value="ar">العربية</option><option value="en">English</option>
            <option value="both">AR + EN</option></select></div>
      </div>
      <label class="check" style="margin-bottom:10px"><input type="checkbox" id="exResolve" checked> ${t("exp.resolve")}</label>
      <div class="small muted" style="margin-bottom:6px">${t("exp.columns")}</div>
      <div class="flex wrap" style="margin-bottom:8px">
        <button class="btn sm" id="exAll">${t("common.all")}</button>
        <button class="btn sm" id="exVisible">${t("list.columns")}</button>
        <button class="btn sm" id="exNone">${t("common.reset")}</button>
      </div>
      <div class="grid c2" style="gap:4px 12px;max-height:300px;overflow:auto">
        ${reg.filter(f => !f.system).map(f => `<label class="check"><input type="checkbox" data-excol="${f.key}"
          ${st.columns.includes(f.key) ? "checked" : ""}> ${f.kind === "derived" ? "ƒ " : ""}${esc(A.regLabel(f))}</label>`).join("")}
      </div>
      <hr class="hr-soft"><div class="small muted">${t("exp.note")}</div>`;
    const m = A.modal({
      title: t("exp.title") + " — " + A.pluralOf(entity), body, size: "wide",
      buttons: [
        { label: t("common.cancel") },
        { label: t("exp.run"), cls: "primary gold", onClick: async (close, el) => {
            const columns = Array.from(el.querySelectorAll("[data-excol]:checked")).map(c => c.dataset.excol);
            const fmt = el.querySelector("#exFormat").value;
            const res = await fetch(`/api/export/${entity}`, {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-Actor": A.state.actor },
              body: JSON.stringify({
                format: fmt, columns, lang: el.querySelector("#exLang").value,
                resolve: el.querySelector("#exResolve").checked,
                filters: presetFilters || payload(entity)
              })
            });
            if (!res.ok) { toast(await res.text(), "err"); return; }
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const name = (cd.match(/filename="?([^";]+)"?/) || [])[1] || `export.${fmt}`;
            const url = URL.createObjectURL(blob);
            A.download(url);
            setTimeout(() => URL.revokeObjectURL(url), 4000);
            toast(t("common.export") + " ✓", "ok");
            close();
          } }
      ]
    });
    m.body.querySelector("#exAll").onclick = () => m.body.querySelectorAll("[data-excol]").forEach(c => c.checked = true);
    m.body.querySelector("#exNone").onclick = () => m.body.querySelectorAll("[data-excol]").forEach(c => c.checked = c.dataset.excol === "code");
    m.body.querySelector("#exVisible").onclick = () => m.body.querySelectorAll("[data-excol]")
      .forEach(c => c.checked = st.columns.includes(c.dataset.excol));
  }
})();
