/* ============================================================================
   SIRAJ · mapfilters.js — field filters for the map desk and the geographic map
   ----------------------------------------------------------------------------
   These sit on top of the filters those views already have (layer chips, and
   on the geographic map the text box and the status menu). They do not replace
   them. Every clause is sent to the database through the same filter engine
   the lists use, and both the marks and the lists are whatever that query
   returned.

   A field applies only to the layers that actually have it. Filtering people
   by year of birth leaves places, institutions and events as the layer chips
   set them.
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc } = A;
  const LAYERS = ["person", "institution", "place", "event"];
  const NO_VALUE = new Set(["is_null", "not_null", "empty", "not_empty"]);
  const TYPE_OPS = {
    text: ["contains", "not_contains", "starts", "ends", "equals", "empty", "not_empty"],
    textarea: ["contains", "not_contains", "equals", "empty", "not_empty"],
    url: ["contains", "empty", "not_empty"],
    select: ["eq", "ne", "in", "not_in", "empty", "not_empty"],
    fk: ["eq", "ne", "in", "not_in", "is_null", "not_null"],
    date: ["on", "before", "after", "between", "year_eq", "year_gte", "year_lte", "is_null", "not_null"],
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

  function entityLabel(key) {
    if (!key) return t("mf.anyLayer");
    const e = ((A.state.meta || {}).entities || []).find(x => x.key === key);
    if (!e) return key;
    return A.state.lang === "ar" ? (e.label_ar || e.label_en) : (e.label_en || e.label_ar);
  }

  function optLabel(o) {
    if (!o) return "";
    return A.state.lang === "ar" ? (o.label_ar || o.label_en) : (o.label_en || o.label_ar);
  }

  function fieldsFor(entity) {
    const keys = entity ? [entity] : LAYERS;
    const seen = new Map();
    keys.forEach(key => {
      (A.registry(key) || []).forEach(f => {
        if (f.filterable === false) return;
        if (!seen.has(f.key)) seen.set(f.key, Object.assign({}, f, { _layers: [key] }));
        else if (seen.get(f.key)._layers.indexOf(key) < 0) seen.get(f.key)._layers.push(key);
      });
    });
    return [...seen.values()];
  }

  function ready(row) {
    if (!row || !row.field || !row.op) return false;
    if (NO_VALUE.has(row.op)) return true;
    if (row.op === "between") {
      return Array.isArray(row.value) && row.value.some(v => v !== null && v !== undefined && String(v) !== "");
    }
    if (Array.isArray(row.value)) return row.value.length > 0;
    return row.value !== null && row.value !== undefined && String(row.value) !== "";
  }

  function blankState(state) {
    state.query = state.query || "";
    state.logic = state.logic === "or" ? "or" : "and";
    state.where = Array.isArray(state.where) ? state.where : [];
    state.auth = state.auth || "";
    state.doc = state.doc || "";
    state.relType = state.relType || "";
    state.tagIds = Array.isArray(state.tagIds) ? state.tagIds : [];
    state.warnings = Array.isArray(state.warnings) ? state.warnings : [];
    return state;
  }

  function activeCount(state) {
    blankState(state);
    let n = 0;
    if (String(state.query || "").trim()) n += 1;
    if (state.auth) n += 1;
    if (state.doc) n += 1;
    if (state.relType) n += 1;
    if (state.tagIds.length) n += 1;
    n += state.where.filter(ready).length;
    return n;
  }

  function toPayload(state) {
    blankState(state);
    const where = state.where.filter(ready).map(row => {
      const clause = { field: row.field, op: row.op, value: row.value };
      if (row.entity) clause.entity = row.entity;
      return clause;
    });
    if (state.auth) where.push({ field: "authentication_id", op: "eq", value: Number(state.auth) });
    if (state.doc) where.push({ field: "documentation_id", op: "eq", value: Number(state.doc) });
    const out = {};
    if (state.q) out.q = String(state.q).trim();
    if (state.status) out.status_ids = [Number(state.status)];
    if (String(state.query || "").trim()) out.query = String(state.query).trim();
    if (where.length) out.where = where;
    if (state.logic === "or") out.logic = "or";
    if (state.relType) out.has_relationship_type = Number(state.relType);
    if (state.tagIds.length) out.tag_ids = state.tagIds.map(Number);
    return out;
  }

  function domainSelect(domain, value) {
    const opts = A.domainOptions(domain) || [];
    return `<option value="">${esc(t("mf.any"))}</option>` +
      opts.map(o => `<option value="${o.id}" ${String(value) === String(o.id) ? "selected" : ""}>${esc(optLabel(o))}</option>`).join("");
  }

  function valueEditor(field, row, onEdit) {
    const wrap = document.createElement("div");
    wrap.className = "mf-value";
    const touch = () => { if (onEdit) onEdit(); };
    if (!field || NO_VALUE.has(row.op)) return wrap;
    if (row.op === "between") {
      const box = document.createElement("div");
      box.className = "mf-range";
      const bounds = Array.isArray(row.value) ? row.value.slice(0, 2) : ["", ""];
      const boundValues = [bounds[0] || "", bounds[1] || ""];
      const push = () => { row.value = [boundValues[0], boundValues[1]]; touch(); };
      const lo = A.control(field, {
        mode: "filter", value: boundValues[0], allowTime: true,
        onChange: (v) => { boundValues[0] = v || ""; push(); }
      });
      const hi = A.control(field, {
        mode: "filter", value: boundValues[1], allowTime: true,
        onChange: (v) => { boundValues[1] = v || ""; push(); }
      });
      if (lo) box.appendChild(lo);
      const sep = document.createElement("span");
      sep.className = "mf-range-sep";
      sep.textContent = "→";
      box.appendChild(sep);
      if (hi) box.appendChild(hi);
      wrap.appendChild(box);
      return wrap;
    }
    const multi = row.op === "in" || row.op === "not_in";
    if (multi && (field.type === "select" || field.type === "fk") && A.multiCombo) {
      wrap.appendChild(A.multiCombo({
        values: Array.isArray(row.value) ? row.value : [],
        onChange: (v) => { row.value = v; touch(); },
        domain: field.type === "select" ? field.domain : undefined,
        entity: field.type === "fk" ? field.ref : undefined,
        size: "sm",
        placeholder: t("common.search")
      }));
      return wrap;
    }
    const control = A.control(field, {
      mode: "filter",
      value: row.value === null || row.value === undefined ? "" : row.value,
      allowTime: true,
      placeholder: field.type === "date" ? "YYYY" : t("common.value"),
      onChange: (v) => { row.value = v; touch(); }
    });
    if (control) wrap.appendChild(control);
    return wrap;
  }

  function mount(host, opts) {
    opts = opts || {};
    const state = blankState(opts.state || {});
    host.classList.add("map-filters");
    host.dataset.mapFilters = "1";
    const qid = "mfq-" + Math.random().toString(36).slice(2, 8);
    let timer = 0;
    let allTags = [];

    function syncCount() {
      const badge = host.querySelector("[data-mf-count]");
      if (!badge) return;
      const n = activeCount(state);
      badge.hidden = !n;
      badge.textContent = String(n);
    }

    function schedule(immediate) {
      syncCount();
      clearTimeout(timer);
      if (!opts.onApply) return;
      if (immediate) { opts.onApply(); return; }
      timer = setTimeout(() => opts.onApply(), 350);
    }

    function paintTags() {
      const box = host.querySelector("[data-mf-tags]");
      const search = host.querySelector("[data-mf-tag-q]");
      if (!box) return;
      const needle = search ? search.value.trim() : "";
      const norm = needle.toLowerCase();
      const rows = allTags.filter(tag => {
        if (!needle) return true;
        return (tag.label_en || "").toLowerCase().includes(norm) ||
          (tag.label_ar || "").includes(needle) ||
          (tag.domain || "").toLowerCase().includes(norm);
      }).slice(0, 60);
      if (!rows.length) {
        box.innerHTML = `<p class="mf-empty">${esc(t("geo.nothingFound"))}</p>`;
        return;
      }
      box.innerHTML = rows.map(tag => {
        const on = state.tagIds.some(id => Number(id) === Number(tag.id));
        return `<label class="mf-tag">
          <input type="checkbox" data-tag="${tag.id}" ${on ? "checked" : ""}>
          <span>${esc(optLabel(tag))}</span>
          <em>${esc(tag.domain || "")}</em>
        </label>`;
      }).join("");
      box.querySelectorAll("[data-tag]").forEach(input => {
        input.onchange = () => {
          const id = Number(input.dataset.tag);
          if (input.checked) {
            if (!state.tagIds.some(x => Number(x) === id)) state.tagIds.push(id);
          } else {
            state.tagIds = state.tagIds.filter(x => Number(x) !== id);
          }
          schedule(true);
        };
      });
    }

    function paintRows() {
      const box = host.querySelector("[data-mf-rows]");
      if (!box) return;
      box.innerHTML = "";
      if (!state.where.length) {
        const empty = document.createElement("p");
        empty.className = "mf-empty";
        empty.textContent = t("mf.noClauses");
        box.appendChild(empty);
      }
      state.where.forEach(row => {
        const fields = fieldsFor(row.entity || "");
        const field = fields.find(f => f.key === row.field) || fields[0];
        if (field && row.field !== field.key) row.field = field.key;
        const el = document.createElement("div");
        el.className = "mf-row";
        const top = document.createElement("div");
        top.className = "mf-row-top";
        const entity = document.createElement("select");
        entity.innerHTML = `<option value="">${esc(t("mf.anyLayer"))}</option>` +
          LAYERS.map(key => `<option value="${key}" ${row.entity === key ? "selected" : ""}>${esc(entityLabel(key))}</option>`).join("");
        entity.value = row.entity || "";
        entity.onchange = () => {
          row.entity = entity.value;
          const next = fieldsFor(row.entity);
          if (!next.some(f => f.key === row.field) && next[0]) {
            row.field = next[0].key;
            row.op = opsFor(next[0].type)[0];
            row.value = null;
          }
          paintRows();
          schedule(true);
        };
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "icon-btn";
        remove.setAttribute("aria-label", t("mf.remove"));
        remove.textContent = "✕";
        remove.onclick = () => {
          state.where = state.where.filter(item => item !== row);
          paintRows();
          schedule(true);
        };
        top.append(entity, remove);
        const fieldHost = document.createElement("div");
        fieldHost.className = "mf-field";
        if (A.fieldPicker) {
          fieldHost.appendChild(A.fieldPicker({
            fields: fields,
            value: row.field,
            onPick: (key) => {
              const picked = fields.find(f => f.key === key);
              row.field = key;
              row.op = opsFor(picked ? picked.type : "text")[0];
              row.value = null;
              paintRows();
              schedule(true);
            }
          }));
        }
        const op = document.createElement("select");
        op.innerHTML = opsFor(field ? field.type : "text")
          .map(name => `<option value="${name}" ${row.op === name ? "selected" : ""}>${esc(opLabel(name))}</option>`).join("");
        op.value = row.op || opsFor(field ? field.type : "text")[0];
        op.onchange = () => {
          row.op = op.value;
          if (NO_VALUE.has(row.op)) row.value = null;
          paintRows();
          schedule(true);
        };
        el.append(top, fieldHost, op, valueEditor(field, row, () => schedule(false)));
        const hint = document.createElement("p");
        hint.className = "mf-applies";
        const layers = field && field._layers ? field._layers : [];
        hint.textContent = layers.length ? (t("mf.appliesTo") + " " + layers.map(entityLabel).join(" · ")) : "";
        if (hint.textContent) el.appendChild(hint);
        box.appendChild(el);
      });
      syncCount();
    }

    host.innerHTML = `
      <div class="mf-head">
        <strong>${esc(t("mf.title"))}</strong>
        <span class="badge" data-mf-count hidden></span>
        <button type="button" class="btn sm ghost" data-mf-clear>${esc(t("mf.clear"))}</button>
      </div>
      <p class="mf-note">${esc(t("mf.note"))}</p>
      <label class="mf-label" for="${qid}">${esc(t("mf.query"))}</label>
      <input id="${qid}" data-mf-query type="search" autocomplete="off" dir="auto"
             placeholder="${esc(t("mf.queryPlaceholder"))}"
             aria-label="${esc(t("mf.query"))}" value="${esc(state.query || "")}">
      <div class="mf-warn" data-mf-warn hidden></div>
      <details class="mf-more" open>
        <summary>${esc(t("mf.more"))}</summary>
        <div class="mf-logic logic-toggle" role="group">
          <button type="button" data-logic="and" class="${state.logic === "or" ? "" : "active"}">AND</button>
          <button type="button" data-logic="or" class="${state.logic === "or" ? "active" : ""}">OR</button>
        </div>
        <div data-mf-rows></div>
        <button type="button" class="btn sm" data-mf-add>${esc(t("mf.add"))}</button>
        <label class="mf-label">${esc(t("mf.auth"))}</label>
        <select data-mf-auth>${domainSelect("authentication_level", state.auth)}</select>
        <label class="mf-label">${esc(t("mf.doc"))}</label>
        <select data-mf-doc>${domainSelect("documentation_level", state.doc)}</select>
        <label class="mf-label">${esc(t("mf.rel"))}</label>
        <select data-mf-rel>${domainSelect("relationship_type", state.relType)}</select>
        <label class="mf-label">${esc(t("mf.tags"))}</label>
        <p class="mf-note">${esc(t("mf.tagsHint"))}</p>
        <input data-mf-tag-q type="search" autocomplete="off" placeholder="${esc(t("mf.tagSearch"))}"
               aria-label="${esc(t("mf.tagSearch"))}">
        <div class="mf-tags" data-mf-tags></div>
      </details>
      <button type="button" class="btn sm primary" data-mf-apply>${esc(t("mf.apply"))}</button>`;

    const query = host.querySelector("[data-mf-query]");
    query.addEventListener("input", () => {
      state.query = query.value;
      schedule(false);
    });
    query.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); state.query = query.value; schedule(true); }
    });
    host.querySelector("[data-mf-clear]").onclick = () => {
      state.query = "";
      state.logic = "and";
      state.where = [];
      state.auth = "";
      state.doc = "";
      state.relType = "";
      state.tagIds = [];
      query.value = "";
      host.querySelector("[data-mf-auth]").value = "";
      host.querySelector("[data-mf-doc]").value = "";
      host.querySelector("[data-mf-rel]").value = "";
      host.querySelectorAll("[data-logic]").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.logic === "and");
      });
      paintRows();
      paintTags();
      schedule(true);
    };
    host.querySelector("[data-mf-add]").onclick = () => {
      const first = fieldsFor("")[0];
      if (!first) return;
      state.where.push({ entity: "", field: first.key, op: opsFor(first.type)[0], value: null });
      paintRows();
    };
    host.querySelector("[data-mf-apply]").onclick = () => schedule(true);
    host.querySelectorAll("[data-logic]").forEach(btn => {
      btn.onclick = () => {
        state.logic = btn.dataset.logic;
        host.querySelectorAll("[data-logic]").forEach(other => {
          other.classList.toggle("active", other === btn);
        });
        schedule(true);
      };
    });
    host.querySelector("[data-mf-auth]").onchange = (ev) => { state.auth = ev.target.value; schedule(true); };
    host.querySelector("[data-mf-doc]").onchange = (ev) => { state.doc = ev.target.value; schedule(true); };
    host.querySelector("[data-mf-rel]").onchange = (ev) => { state.relType = ev.target.value; schedule(true); };
    const tagSearch = host.querySelector("[data-mf-tag-q]");
    tagSearch.addEventListener("input", () => paintTags());
    paintRows();
    api.get("/api/tags").then(rows => { allTags = rows || []; paintTags(); }).catch(() => { allTags = []; paintTags(); });

    return {
      setWarnings(list) {
        state.warnings = list || [];
        const box = host.querySelector("[data-mf-warn]");
        if (!box) return;
        const text = state.warnings.filter(Boolean).join(" · ");
        box.hidden = !text;
        box.textContent = text;
      }
    };
  }

  A.mapFilters = { mount, toPayload, activeCount, ready };
})();
