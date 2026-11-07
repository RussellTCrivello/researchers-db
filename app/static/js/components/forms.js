/* ============================================================================
   SIRAJ · forms.js — advanced inputs
     • combobox      searchable drop-down for foreign keys and large vocabularies
     • multiCombo    chip-based multi-select with the same search + create flow
     • quickCreate   inline "add a new record without leaving the form" modal
     • registry      unified field catalogue (own fields + derived fields)
   No dependencies.
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, icon, toast, hydrateIcons } = A;

  /* ---------------------------------------------------------- registry --- */
  A.registry = function (entity) {
    const meta = A.state.meta || {};
    const fields = ((meta.fields || {})[entity] || []).map(f => ({ ...f, kind: "field" }));
    const derived = ((meta.derived || {})[entity] || []).map(d => ({ ...d, kind: "derived" }));
    return fields.concat(derived);
  };
  A.regField = function (entity, key) {
    return A.registry(entity).find(f => f.key === key) || null;
  };
  A.regLabel = function (f) {
    if (!f) return "";
    return A.state.lang === "ar" ? (f.label_ar || f.label_en) : (f.label_en || f.label_ar);
  };
  A.isLargeList = function (f) {
    if (!f) return false;
    if (f.type === "fk") return true;
    if (f.type === "select") return (A.domainOptions(f.domain) || []).length > 14;
    return false;
  };

  /* ------------------------------------------------------------ recents --- */
  function recentsKey(kind, scope) { return `siraj.recent.${kind}.${scope}`; }
  function getRecents(kind, scope) {
    try { return JSON.parse(localStorage.getItem(recentsKey(kind, scope)) || "[]"); }
    catch (e) { return []; }
  }
  function pushRecent(kind, scope, item) {
    if (!item || !item.id) return;
    const list = getRecents(kind, scope).filter(x => x.id !== item.id);
    list.unshift({ id: item.id, code: item.code, label: item.label, hint: item.hint });
    localStorage.setItem(recentsKey(kind, scope), JSON.stringify(list.slice(0, 8)));
  }

  /* ------------------------------------------- floating combo menus --- */
  /**
   * Dropdowns live inside scroll/overflow shells (dialogs, cards). Absolute
   * menus get clipped there, so an open menu is portaled to <body> and pinned
   * with position:fixed against the input — always in the foreground.
   */
  function floatComboMenu(anchor, menu) {
    if (!anchor || !menu) return;
    const r = anchor.getBoundingClientRect();
    const gap = 4;
    const maxH = 320;
    const spaceBelow = window.innerHeight - r.bottom - gap - 8;
    const spaceAbove = r.top - gap - 8;
    const openUp = spaceBelow < 160 && spaceAbove > spaceBelow;
    const height = Math.max(120, Math.min(maxH, openUp ? spaceAbove : spaceBelow));
    if (menu.parentElement !== document.body) document.body.appendChild(menu);
    menu.classList.add("is-floating");
    menu.hidden = false;
    menu.style.position = "fixed";
    menu.style.left = `${Math.round(r.left)}px`;
    menu.style.width = `${Math.round(r.width)}px`;
    menu.style.right = "auto";
    menu.style.zIndex = "400";
    menu.style.maxHeight = `${Math.round(height)}px`;
    if (openUp) {
      menu.style.top = "auto";
      menu.style.bottom = `${Math.round(window.innerHeight - r.top + gap)}px`;
    } else {
      menu.style.bottom = "auto";
      menu.style.top = `${Math.round(r.bottom + gap)}px`;
    }
  }
  function parkComboMenu(host, menu) {
    if (!menu) return;
    menu.hidden = true;
    menu.classList.remove("is-floating");
    menu.style.position = "";
    menu.style.left = "";
    menu.style.right = "";
    menu.style.top = "";
    menu.style.bottom = "";
    menu.style.width = "";
    menu.style.maxHeight = "";
    menu.style.zIndex = "";
    if (host && menu.parentElement !== host) host.appendChild(menu);
  }

  /* ----------------------------------------------------------- combobox --- */
  /**
   * opts: { entity | domain, value, placeholder, allowCreate, excludeIds,
   *         onSelect(item), onClear(), disabled, size }
   */
  A.combobox = function (opts) {
    opts = opts || {};
    const isDomain = !!opts.domain;
    const scopeKey = isDomain ? `domain:${opts.domain}` : `entity:${opts.entity}`;
    const wrap = document.createElement("div");
    wrap.className = "combo" + (opts.size === "sm" ? " sm" : "");
    wrap.innerHTML = `
      <div class="combo-input">
        <span class="combo-ico">${icon(isDomain ? "list" : "search")}</span>
        <input type="text" autocomplete="off" spellcheck="false"
               placeholder="${esc(opts.placeholder || (isDomain ? t("common.select") : t("common.search")))}"
               ${opts.disabled ? "disabled" : ""}>
        <button type="button" class="combo-clear" hidden aria-label="clear">×</button>
      </div>
      <div class="combo-menu" hidden></div>`;

    const input = wrap.querySelector("input");
    const clearBtn = wrap.querySelector(".combo-clear");
    const menu = wrap.querySelector(".combo-menu");
    const anchor = wrap.querySelector(".combo-input");
    let value = opts.value || null;
    let selected = null;
    let items = [];
    let cursor = -1;
    let open = false;
    let timer = null;
    let repositionBound = false;

    function domainItems(q) {
      const filters = opts.filters || {};
      let raw = A.domainOptions(opts.domain) || [];
      if (filters.parent_id != null && filters.parent_id !== "") {
        const pid = Number(filters.parent_id);
        raw = raw.filter(o => Number(o.parent_id) === pid);
      } else if (filters.require_parent) {
        raw = [];
      }
      const all = raw.map(o => ({
        id: o.id, code: o.code, label: o.label_en, label_ar: o.label_ar,
        parent_id: o.parent_id, hint: ""
      }));
      if (!q) return all;
      const nq = A.normText(q);
      return all.filter(o => A.normText(`${o.code} ${o.label} ${o.label_ar}`).includes(nq));
    }

    async function fetchItems(q) {
      if (isDomain) return domainItems(q);
      const params = new URLSearchParams({ limit: String(opts.limit || 30) });
      if (q) params.set("q", q);
      const filters = opts.filters || {};
      if (filters.country_id) params.set("country_id", String(filters.country_id));
      if (filters.place_types) {
        const types = Array.isArray(filters.place_types)
          ? filters.place_types.join(",") : String(filters.place_types);
        if (types) params.set("place_types", types);
      }
      try { return await api.get(`/api/options/${opts.entity}?${params}`); }
      catch (e) { toast(e.message, "err"); return []; }
    }

    function labelFor(it) {
      return A.state.lang === "ar" && it.label_ar ? it.label_ar : it.label;
    }

    function render(q) {
      const list = [];
      const filtered = !!(opts.filters && (opts.filters.country_id
        || opts.filters.place_types || opts.filters.parent_id || opts.filters.require_parent));
      if (!q && !filtered) {
        const rec = getRecents(isDomain ? "domain" : "entity", scopeKey)
          .filter(x => !opts.excludeIds || !opts.excludeIds.includes(x.id));
        if (rec.length) {
          list.push(`<div class="combo-head">${esc(t("common.recent") || "Recent")}</div>`);
          rec.forEach(it => list.push(rowHtml(it, false)));
        }
        if (rec.length && items.length) list.push(`<div class="combo-head">${esc(t("common.all"))}</div>`);
      }
      items.forEach(it => list.push(rowHtml(it, true)));
      menu.innerHTML = list.join("") || `<div class="combo-empty">${esc(t("search.noResults"))}</div>`;
      if (opts.allowCreate) {
        let label;
        if (isDomain) {
          const dom = (A.state.meta.lookup_domains || []).find(d => d.domain === opts.domain);
          label = dom
            ? (A.state.lang === "ar" ? (dom.label_ar || dom.label_en) : (dom.label_en || dom.label_ar))
            : opts.domain;
        } else {
          label = A.state.lang === "ar" ? (A.label(opts.entity) || opts.entity) : A.pluralOf(opts.entity);
        }
        const needParent = !!(opts.filters && opts.filters.require_parent);
        const blocked = needParent && !(opts.filters && opts.filters.parent_id);
        menu.insertAdjacentHTML("beforeend",
          `<button type="button" class="combo-create" data-create ${blocked ? "disabled" : ""}>
             ${icon("plus")} ${t("common.add")} — ${esc(label)}${q ? ` “${esc(q)}”` : ""}</button>`);
      }
      menu.querySelectorAll("[data-id]").forEach(el => {
        el.onclick = () => select(items.find(i => String(i.id) === el.dataset.id) || {
          id: Number(el.dataset.id), label: el.dataset.label, code: el.dataset.code
        });
      });
      const create = menu.querySelector("[data-create]");
      if (create) {
        create.onclick = () => {
          if (create.disabled) {
            return toast(t("adm.parentRequired") || t("common.required"), "warn");
          }
          close();
          if (isDomain) createDomainValue(q);
          else A.quickCreate(opts.entity, q, (rec) => select(rec));
        };
      }
      hydrateIcons(menu);
    }

    function slugCode(text, domain) {
      const base = String(text || "").trim()
        .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
        .replace(/[^\w\u0600-\u06FF]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .slice(0, 40) || "new";
      const prefix = domain === "governorate" || domain === "district"
        ? ((opts.filters && opts.filters.parent_id)
          ? (String((A.lookupById(opts.filters.parent_id) || {}).code || "") + "-")
          : "")
        : "";
      let code = (prefix + base).replace(/_+/g, "_").slice(0, 48);
      const taken = new Set((A.domainOptions(domain) || []).map(o => o.code));
      if (!taken.has(code)) return code;
      let n = 2;
      while (taken.has(`${code}_${n}`)) n += 1;
      return `${code}_${n}`;
    }

    async function createDomainValue(q) {
      const name = String(q || input.value || "").trim();
      if (!name) {
        toast(t("common.required"), "warn");
        input.focus();
        return;
      }
      const parentId = opts.filters && opts.filters.parent_id
        ? Number(opts.filters.parent_id) : null;
      if (opts.filters && opts.filters.require_parent && !parentId) {
        return toast(t("adm.parentRequired") || t("common.required"), "warn");
      }
      try {
        const payload = {
          domain: opts.domain,
          code: slugCode(name, opts.domain),
          label_en: name,
          label_ar: name,
          parent_id: parentId,
          sort_order: 900,
          color: opts.domain === "country" ? "green"
            : opts.domain === "governorate" ? "teal" : "green"
        };
        const res = await api.post("/api/lookups", payload);
        App.state.meta = await api.get(`/api/meta?lang=${A.state.lang}`);
        const created = {
          id: res.id, code: payload.code, label: name, label_ar: name,
          parent_id: parentId
        };
        select(created);
        toast(t("common.saved"), "ok");
      } catch (err) {
        toast(err.message || String(err), "err");
      }
    }

    function rowHtml(it, indexed) {
      const display = labelFor(it);
      const alt = A.state.lang === "ar" ? it.label : it.label_ar;
      return `<button type="button" class="combo-row ${indexed && cursor === items.indexOf(it) ? "active" : ""}"
                data-id="${it.id}" data-label="${esc(display)}" data-code="${esc(it.code || "")}">
        <span class="c-code">${esc(it.code || "#")}</span>
        <span class="c-main">${esc(display)}
          ${alt && alt !== display ? `<span class="c-alt">${esc(alt)}</span>` : ""}
          ${it.hint ? `<span class="c-hint">${esc(it.hint)}</span>` : ""}</span>
      </button>`;
    }

    async function load(q) {
      items = (await fetchItems(q)) || [];
      if (opts.excludeIds) items = items.filter(i => !opts.excludeIds.includes(i.id));
      cursor = -1;
      render(q);
      if (open) floatComboMenu(anchor, menu);
    }

    function reposition() {
      if (!open) return;
      if (!wrap.isConnected) { close(); return; }
      floatComboMenu(anchor, menu);
    }
    function bindReposition(on) {
      if (on === repositionBound) return;
      repositionBound = on;
      const method = on ? "addEventListener" : "removeEventListener";
      window[method]("resize", reposition, true);
      window[method]("scroll", reposition, true);
    }

    function openMenu() {
      if (open) {
        floatComboMenu(anchor, menu);
        return;
      }
      open = true;
      wrap.classList.add("open");
      floatComboMenu(anchor, menu);
      bindReposition(true);
      load(input.value.trim());
    }
    function close() {
      if (!open && menu.hidden) return;
      open = false;
      wrap.classList.remove("open");
      bindReposition(false);
      parkComboMenu(wrap, menu);
    }
    function select(it) {
      if (!it) return;
      value = it.id;
      selected = it;
      input.value = labelFor(it);
      clearBtn.hidden = false;
      pushRecent(isDomain ? "domain" : "entity", scopeKey, it);
      close();
      if (opts.onSelect) opts.onSelect(it);
      wrap.dispatchEvent(new CustomEvent("combo:change", { detail: it }));
    }
    function clear() {
      value = null; selected = null; input.value = "";
      clearBtn.hidden = true;
      if (opts.onClear) opts.onClear();
      if (opts.onSelect) opts.onSelect(null);
      wrap.dispatchEvent(new CustomEvent("combo:change", { detail: null }));
    }

    input.addEventListener("focus", openMenu);
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (!q) return openMenu();
      timer = setTimeout(() => load(q), 190);
      clearBtn.hidden = !q;
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { close(); input.blur(); return; }
      if (!open) { openMenu(); return; }
      const rows = Array.from(menu.querySelectorAll("[data-id]"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        cursor = Math.max(0, Math.min(rows.length - 1, cursor + (e.key === "ArrowDown" ? 1 : -1)));
        rows.forEach((r, i) => r.classList.toggle("active", i === cursor));
        if (rows[cursor]) rows[cursor].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (rows[cursor]) rows[cursor].click();
        else if (rows.length) rows[0].click();
      } else if (e.key === "Tab") {
        close();
      }
    });
    clearBtn.onclick = (e) => { e.stopPropagation(); clear(); input.focus(); };
    const onDocClick = (e) => {
      if (!wrap.isConnected) {
        document.removeEventListener("mousedown", onDocClick);
        bindReposition(false);
        parkComboMenu(wrap, menu);
        return;
      }
      if (wrap.contains(e.target) || menu.contains(e.target)) return;
      close();
    };
    document.addEventListener("mousedown", onDocClick);

    wrap.getValue = () => value;
    wrap.getSelected = () => selected;
    wrap.setValue = async (id, display) => {
      if (!id) { clear(); return; }
      value = id;
      clearBtn.hidden = false;
      if (display) { input.value = display; return; }
      try {
        const list = await api.get(`/api/options/${opts.entity || "__"}?ids=${id}`);
        if (list && list.length) {
          selected = list[0];
          input.value = labelFor(selected);
        }
      } catch (e) { input.value = `#${id}`; }
    };
    wrap.setDomainValue = (id) => {
      const it = domainItems("").find(x => String(x.id) === String(id));
      if (it) select(it);
    };
    wrap.setFilters = (next) => {
      opts.filters = Object.assign({}, opts.filters || {}, next || {});
      if (opts.filters.parent_id) opts.filters.require_parent = false;
      if (open) load(input.value.trim());
    };
    wrap.focus = () => input.focus();
    if (value) {
      if (isDomain) wrap.setDomainValue(value);
      else wrap.setValue(value, opts.valueLabel);
    }
    return wrap;
  };

  /* -------------------------------------------------------- multi combo --- */
  A.multiCombo = function (opts) {
    opts = opts || {};
    const isDomain = !!opts.domain;
    const wrap = document.createElement("div");
    wrap.className = "combo multi";
    let values = (opts.values || []).map(Number);
    let cache = {};                      // id → item
    wrap.innerHTML = `<div class="combo-input chips">
        <span class="chips-box"></span>
        <input type="text" autocomplete="off" placeholder="${esc(opts.placeholder || t("common.select"))}">
      </div>
      <div class="combo-menu" hidden></div>`;
    const box = wrap.querySelector(".chips-box");
    const input = wrap.querySelector("input");
    const menu = wrap.querySelector(".combo-menu");
    const anchor = wrap.querySelector(".combo-input");
    let items = [];
    let multiOpen = false;
    let multiRepositionBound = false;

    function paintChips() {
      box.innerHTML = values.map(id => {
        const it = cache[id] || { label: `#${id}`, code: "" };
        return `<span class="chip" data-chip="${id}">${esc(it.code ? it.code + " · " : "")}${esc(A.truncate(it.label, 26))}
          <span class="x" data-x="${id}">×</span></span>`;
      }).join("");
      box.querySelectorAll("[data-x]").forEach(x => {
        x.onclick = () => { remove(Number(x.dataset.x)); };
      });
    }
    function remove(id) {
      values = values.filter(v => v !== id);
      paintChips();
      if (opts.onChange) opts.onChange(values.slice());
    }
    function add(item) {
      if (!item || values.includes(item.id)) return;
      cache[item.id] = item;
      values.push(item.id);
      paintChips();
      if (opts.onChange) opts.onChange(values.slice());
    }
    async function hydrate() {
      if (!values.length) return;
      if (isDomain) {
        (A.domainOptions(opts.domain) || []).forEach(o => {
          cache[o.id] = { id: o.id, code: o.code, label: A.state.lang === "ar" ? o.label_ar : o.label_en };
        });
      } else {
        try {
          const list = await api.get(`/api/options/${opts.entity}?ids=${values.join(",")}`);
          list.forEach(i => { cache[i.id] = i; });
        } catch (e) { /* ignore */ }
      }
      paintChips();
    }

    async function load(q) {
      if (isDomain) {
        const all = (A.domainOptions(opts.domain) || []).map(o => ({
          id: o.id, code: o.code, label: o.label_en, label_ar: o.label_ar
        }));
        const nq = A.normText(q);
        items = all.filter(o => !values.includes(o.id) &&
          (!q || A.normText(`${o.code} ${o.label} ${o.label_ar}`).includes(nq)));
      } else {
        try {
          const list = await api.get(`/api/options/${opts.entity}?limit=30${q ? `&q=${encodeURIComponent(q)}` : ""}`);
          items = list.filter(i => !values.includes(i.id));
        } catch (e) { items = []; }
      }
      menu.innerHTML = items.map(it => `
        <button type="button" class="combo-row" data-id="${it.id}">
          <span class="c-code">${esc(it.code || "#")}</span>
          <span class="c-main">${esc(A.state.lang === "ar" && it.label_ar ? it.label_ar : it.label)}
            ${it.hint ? `<span class="c-hint">${esc(it.hint)}</span>` : ""}</span>
        </button>`).join("") || `<div class="combo-empty">${esc(t("search.noResults"))}</div>`;
      menu.querySelectorAll("[data-id]").forEach(el => {
        el.onclick = () => {
          add(items.find(i => String(i.id) === el.dataset.id));
          input.value = "";
          load("");
        };
      });
      openMultiMenu();
    }

    function repositionMulti() {
      if (!multiOpen) return;
      if (!wrap.isConnected) { closeMultiMenu(); return; }
      floatComboMenu(anchor, menu);
    }
    function bindMultiReposition(on) {
      if (on === multiRepositionBound) return;
      multiRepositionBound = on;
      const method = on ? "addEventListener" : "removeEventListener";
      window[method]("resize", repositionMulti, true);
      window[method]("scroll", repositionMulti, true);
    }
    function openMultiMenu() {
      multiOpen = true;
      wrap.classList.add("open");
      floatComboMenu(anchor, menu);
      bindMultiReposition(true);
    }
    function closeMultiMenu() {
      multiOpen = false;
      wrap.classList.remove("open");
      bindMultiReposition(false);
      parkComboMenu(wrap, menu);
    }

    input.addEventListener("focus", () => load(""));
    let timer = null;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => load(input.value.trim()), 190);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !input.value && values.length) remove(values[values.length - 1]);
      if (e.key === "Escape") { closeMultiMenu(); }
      if (e.key === "Enter") {
        e.preventDefault();
        const first = menu.querySelector("[data-id]");
        if (first) first.click();
      }
    });
    const onDocClickMulti = (e) => {
      if (!wrap.isConnected) {
        document.removeEventListener("mousedown", onDocClickMulti);
        bindMultiReposition(false);
        parkComboMenu(wrap, menu);
        return;
      }
      if (wrap.contains(e.target) || menu.contains(e.target)) return;
      closeMultiMenu();
    };
    document.addEventListener("mousedown", onDocClickMulti);

    wrap.getValue = () => values.slice();
    wrap.setValue = (ids) => { values = (ids || []).map(Number); hydrate(); };
    hydrate();
    return wrap;
  };

  /* ------------------------------------------------------- quick create --- */
  /**
   * Inline creation of a related record without leaving the current form.
   * Only the required fields of the target entity are shown; optional fields
   * can be completed later from the record itself.
   */
  A.quickCreate = function (entity, presetName, onCreated, depth) {
    depth = depth || 0;
    const reg = A.registry(entity).filter(f => f.kind === "field" && !f.system);
    const required = reg.filter(f => f.required && !f.read_only && f.key !== "code");
    const extras = reg.filter(f => !f.required && !f.read_only && f.key !== "code" &&
      ["name_en", "classification_id", "country_id", "place_type_id", "institution_type_id",
       "source_type_id", "event_type_id", "record_status_id", "authentication_id"].includes(f.key));
    const fields = required.concat(extras.filter(f => !required.includes(f)));
    const nameField = entity === "source" ? "title" : (entity === "event" ? "title_ar" : "name_ar");
    let nameValue = presetName || "";

    const body = document.createElement("div");
    body.innerHTML = `<div class="notice small">${A.t("ui.enterTheMinimumNowTheRemainingFieldsCa")}</div>
      <div class="grid c2" data-fields></div>
      <div data-err></div>`;
    const grid = body.querySelector("[data-fields]");
    const state = {};

    fields.forEach(f => {
      const box = document.createElement("div");
      box.className = "field";
      box.innerHTML = `<label>${esc(A.regLabel(f))}${f.required ? ' <span class="req">*</span>' : ""}</label>`;
      if ((A.isLargeList(f) || f.type === "fk") && depth < 2) {
        const combo = A.combobox({
          entity: f.ref, domain: f.type === "select" ? f.domain : undefined,
          allowCreate: f.type === "fk", size: "sm",
          onSelect: (it) => { state[f.key] = it ? it.id : null; }
        });
        box.appendChild(combo);
      } else if (f.type === "select") {
        const sel = document.createElement("select");
        sel.innerHTML = `<option value="">${esc(t("common.select"))}</option>` +
          (A.domainOptions(f.domain) || []).map(o =>
            `<option value="${o.id}">${esc(A.state.lang === "ar" ? o.label_ar : o.label_en)}</option>`).join("");
        sel.onchange = () => { state[f.key] = sel.value ? Number(sel.value) : null; };
        box.appendChild(sel);
      } else if (f.type === "textarea") {
        const ta = document.createElement("textarea");
        ta.rows = 2;
        ta.oninput = () => { state[f.key] = ta.value || null; };
        box.appendChild(ta);
      } else {
        const inp = document.createElement("input");
        inp.type = f.type === "date" ? "text" : (f.type === "int" || f.type === "float" ? "number" : "text");
        if (f.key === nameField) inp.value = nameValue;
        if (f.key === nameField) state[f.key] = nameValue || null;
        inp.oninput = () => { state[f.key] = inp.value || null; };
        box.appendChild(inp);
      }
      grid.appendChild(box);
    });

    body.classList.add("form-dialog-quick");
    const entIcon = (A.entitySpec(entity) || {}).icon || "file";
    const m = A.modal({
      title: `${t("common.add")} — ${A.label(entity)}`,
      subtitle: A.pluralOf(entity),
      body, size: "wide",
      cls: "form-dialog form-dialog--quick",
      mark: `<div class="form-dialog-mark" data-entity="${esc(entity)}">${icon(entIcon)}</div>`,
      buttons: [
        { label: t("common.cancel") },
        {
          label: `${t("common.save")} & ${t("common.select")}`, cls: "primary gold",
          onClick: async (close) => {
            const missing = required.filter(f => state[f.key] === undefined || state[f.key] === null ||
              state[f.key] === "");
            const errBox = body.querySelector("[data-err]");
            if (missing.length) {
              errBox.innerHTML = `<div class="notice err">${esc(t("common.required"))}: ` +
                missing.map(f => esc(A.regLabel(f))).join(", ") + "</div>";
              return;
            }
            try {
              const res = await api.post(`/api/${entity}`,
                { ...state, _reason: "created inline from a related field" });
              const rec = res.record;
              toast(`${t("rec.createdOk")} · ${rec.code}`, "ok");
              close();
              if (onCreated) {
                onCreated({
                  id: rec.id, code: rec.code, label: rec._title,
                  label_ar: rec.name_ar || rec.title_ar, hint: ""
                });
              }
            } catch (err) {
              errBox.innerHTML = `<div class="notice err">${esc(err.message)}</div>`;
            }
          }
        }
      ]
    });
    return m;
  };

  /* ------------------------------------------- relationship composer --- */
  /**
   * One composer for every surface that creates a typed link: the atlas side
   * panel, a dossier tab, or a temporary modal.  The *fields* are the same; only
   * the host changes — so a workspace never has to leave itself for a form page.
   *
   *   A.composeRelationship({
   *     host,                         // element to fill (required)
   *     source: { type, id, title },  // the record already in context
   *     target: { type, id, title }?, // optional pre-selected other end
   *     onSaved(record), onCancel(),
   *     onPickRequest(setTarget),     // optional: "choose the other end on the map"
   *   })
   */
  A.composeRelationship = function (opts) {
    opts = opts || {};
    const host = opts.host;
    if (!host) throw new Error("composeRelationship needs a host");
    const source = opts.source || {};
    const entityTypes = (A.domainOptions("entity_type") || [])
      .filter(x => x.code !== "relationship" && x.code !== "source");
    const draftStatus = (A.domainOptions("record_status") || [])
      .find(s => s.code === "draft");

    let targetCombo = null;
    let typeCombo = null;
    let sourceCombo = null;
    let pickArmed = false;

    host.classList.add("rel-composer");
    host.hidden = false;
    host.innerHTML = `
      <div class="rel-composer-head">
        <h3>${esc(t("rec.addRelationship"))}</h3>
        <button type="button" class="icon-btn" data-rc-cancel aria-label="${esc(t("common.cancel"))}">×</button>
      </div>
      <p class="rel-composer-from muted small">${esc(t("atlas.composerFrom"))}
        <b dir="auto">${esc(source.title || source.code || ("#" + source.id))}</b>
        <span class="badge gray">${esc(A.label(source.type) || source.type || "")}</span>
      </p>
      <div class="field"><label>${esc(A.t("ui.otherEntityType"))}</label>
        <select data-rc-etype>${entityTypes.map(x =>
          `<option value="${esc(x.code)}" ${(opts.target && opts.target.type) === x.code ? "selected" : ""}>
            ${esc(A.state.lang === "ar" ? x.label_ar : x.label_en)}</option>`).join("")}</select></div>
      <div class="field"><label>${esc(A.t("ui.otherRecord"))}</label>
        <div data-rc-target></div>
        ${opts.onPickRequest ? `<button type="button" class="btn ghost sm" data-rc-pick
            style="margin-top:6px">${esc(t("atlas.pickOnMap"))}</button>
          <div class="hint" data-rc-pick-hint hidden>${esc(t("atlas.pickOnMapHint"))}</div>` : ""}
      </div>
      <div class="field"><label>${esc(A.t("ui.relationshipType"))}</label>
        <div data-rc-type></div></div>
      <div class="grid c2">
        <div class="field"><label>${esc(A.t("ui.startDate"))}</label>
          <input data-rc-start placeholder="1948"></div>
        <div class="field"><label>${esc(A.t("ui.endDate"))}</label>
          <input data-rc-end placeholder="1975"></div>
      </div>
      <div class="field"><label>${esc(t("common.source"))}</label>
        <div data-rc-source></div></div>
      <div class="field"><label>${esc(A.t("ui.description"))}</label>
        <textarea data-rc-desc rows="2"></textarea></div>
      <div class="field"><label>${esc(t("common.reason"))}</label>
        <input data-rc-reason placeholder="${esc(t("common.reasonPh"))}"></div>
      <div class="rel-composer-acts">
        <button type="button" class="btn primary sm" data-rc-save>${esc(t("common.save"))}</button>
        <button type="button" class="btn ghost sm" data-rc-cancel2>${esc(t("common.cancel"))}</button>
      </div>
      <div data-rc-err></div>`;

    const etypeSel = host.querySelector("[data-rc-etype]");
    const mountTarget = (preset) => {
      const box = host.querySelector("[data-rc-target]");
      box.innerHTML = "";
      targetCombo = A.combobox({
        entity: etypeSel.value, allowCreate: true, limit: 30, size: "sm",
        value: preset && preset.id ? Number(preset.id) : null,
        valueLabel: preset && (preset.title || preset.label) || null,
        excludeIds: source.type === etypeSel.value ? [Number(source.id)] : [],
        placeholder: `${t("common.search")} — ${A.label(etypeSel.value) || etypeSel.value}`
      });
      box.appendChild(targetCombo);
    };
    mountTarget(opts.target && opts.target.type === etypeSel.value ? opts.target : null);
    etypeSel.onchange = () => mountTarget(null);

    typeCombo = A.combobox({ domain: "relationship_type", size: "sm" });
    host.querySelector("[data-rc-type]").appendChild(typeCombo);
    sourceCombo = A.combobox({ entity: "source", allowCreate: true, limit: 30, size: "sm" });
    host.querySelector("[data-rc-source]").appendChild(sourceCombo);

    function setTarget(rec) {
      if (!rec || !rec.type || !rec.id) return;
      etypeSel.value = rec.type;
      mountTarget({ id: rec.id, title: rec.title || rec.label });
      pickArmed = false;
      const hint = host.querySelector("[data-rc-pick-hint]");
      if (hint) hint.hidden = true;
      const pickBtn = host.querySelector("[data-rc-pick]");
      if (pickBtn) pickBtn.classList.remove("is-on");
    }

    const cancel = () => {
      host.hidden = true;
      host.innerHTML = "";
      host.classList.remove("rel-composer");
      if (opts.onCancel) opts.onCancel();
    };
    host.querySelectorAll("[data-rc-cancel], [data-rc-cancel2]").forEach(b => {
      b.onclick = cancel;
    });

    const pickBtn = host.querySelector("[data-rc-pick]");
    if (pickBtn && opts.onPickRequest) {
      pickBtn.onclick = () => {
        pickArmed = !pickArmed;
        pickBtn.classList.toggle("is-on", pickArmed);
        const hint = host.querySelector("[data-rc-pick-hint]");
        if (hint) hint.hidden = !pickArmed;
        opts.onPickRequest(pickArmed ? setTarget : null);
      };
    }

    host.querySelector("[data-rc-save]").onclick = async () => {
      const err = host.querySelector("[data-rc-err]");
      err.innerHTML = "";
      const targetId = targetCombo && targetCombo.getValue();
      const relType = typeCombo && typeCombo.getValue();
      if (!targetId) {
        err.innerHTML = `<div class="notice err small">${esc(t("common.select"))}</div>`;
        return;
      }
      if (!relType) {
        err.innerHTML = `<div class="notice err small">${esc(t("common.required"))}: ${esc(A.t("ui.relationshipType"))}</div>`;
        return;
      }
      const other = targetCombo.getSelected && targetCombo.getSelected();
      const otherName = other
        ? ((A.state.lang === "ar" && other.label_ar) ? other.label_ar : (other.label || other.code || ""))
        : "";
      try {
        const res = await api.post("/api/relationship", {
          entity1_type: source.type,
          entity1_id: source.id,
          entity1_name: source.title || null,
          entity2_type: etypeSel.value,
          entity2_id: targetId,
          entity2_name: otherName || null,
          relationship_type_id: relType,
          source_id: (sourceCombo && sourceCombo.getValue()) || null,
          start_date: host.querySelector("[data-rc-start]").value || null,
          end_date: host.querySelector("[data-rc-end]").value || null,
          description: host.querySelector("[data-rc-desc]").value || null,
          record_status_id: draftStatus ? draftStatus.id : null,
          _reason: host.querySelector("[data-rc-reason]").value || "relationship added from workspace"
        });
        toast(t("common.saved"), "ok");
        host.hidden = true;
        host.innerHTML = "";
        host.classList.remove("rel-composer");
        if (opts.onSaved) opts.onSaved(res.record || res);
      } catch (e) {
        err.innerHTML = `<div class="notice err small">${esc(e.message)}</div>`;
      }
    };

    hydrateIcons(host);
    return { setTarget, cancel, el: host };
  };

  /**
   * Workspace-native create: same minimum fields as quickCreate, but mounted in
   * a host the caller already owns (desk rail, atlas panel). No modal, no route.
   */
  A.composeEntity = function (opts) {
    opts = opts || {};
    const host = opts.host;
    if (!host) throw new Error("composeEntity needs a host");
    const entityTypes = (A.domainOptions("entity_type") || [])
      .filter(x => x.code !== "relationship" && x.code !== "source");
    const at = opts.at || opts.preset || null;
    const hasCoords = at && Number.isFinite(Number(at.lat)) && Number.isFinite(Number(at.lon || at.lng));
    let entity = opts.entity
      || (hasCoords ? "place" : null)
      || (entityTypes[0] && entityTypes[0].code)
      || "person";

    host.classList.add("ent-composer");
    host.hidden = false;

    function paint() {
      const reg = A.registry(entity).filter(f => f.kind === "field" && !f.system);
      const required = reg.filter(f => f.required && !f.read_only && f.key !== "code");
      const extras = reg.filter(f => !f.required && !f.read_only && f.key !== "code" &&
        ["name_en", "classification_id", "country_id", "place_type_id", "institution_type_id",
         "source_type_id", "event_type_id", "record_status_id", "authentication_id"].includes(f.key));
      const fields = required.concat(extras.filter(f => !required.includes(f)));
      const nameField = entity === "source" ? "title" : (entity === "event" ? "title_ar" : "name_ar");
      const state = {};
      if (hasCoords && entity === "place") {
        state.latitude = Number(at.lat);
        state.longitude = Number(at.lon != null ? at.lon : at.lng);
        state.geo_precision = at.precision || "exact";
        state.geocoding_method = at.method || "map_pick";
      }

      host.innerHTML = `
        <div class="rel-composer-head">
          <h3>${esc(t("common.add"))} — <span data-ec-label>${esc(A.label(entity) || entity)}</span></h3>
          <button type="button" class="icon-btn" data-ec-cancel aria-label="${esc(t("common.cancel"))}">×</button>
        </div>
        ${hasCoords ? `<p class="rel-composer-from muted small">${esc(t("geo.addAtCoords"))}
          <b dir="ltr">${Number(at.lat).toFixed(5)}, ${Number(at.lon != null ? at.lon : at.lng).toFixed(5)}</b></p>` : ""}
        <div class="field"><label>${esc(t("desk.type"))}</label>
          <select data-ec-etype>${entityTypes.map(x =>
            `<option value="${esc(x.code)}" ${x.code === entity ? "selected" : ""}>
              ${esc(A.state.lang === "ar" ? x.label_ar : x.label_en)}</option>`).join("")}</select></div>
        <div class="grid c2" data-ec-fields></div>
        <div class="rel-composer-acts">
          <button type="button" class="btn primary sm" data-ec-save>${esc(t("common.save"))}</button>
          <button type="button" class="btn ghost sm" data-ec-cancel2>${esc(t("common.cancel"))}</button>
        </div>
        <div data-ec-err></div>`;

      const grid = host.querySelector("[data-ec-fields]");
      fields.forEach(f => {
        const box = document.createElement("div");
        box.className = "field";
        box.innerHTML = `<label>${esc(A.regLabel(f))}${f.required ? ' <span class="req">*</span>' : ""}</label>`;
        if ((A.isLargeList(f) || f.type === "fk")) {
          const combo = A.combobox({
            entity: f.ref, domain: f.type === "select" ? f.domain : undefined,
            allowCreate: false, size: "sm",
            onSelect: (it) => { state[f.key] = it ? it.id : null; }
          });
          box.appendChild(combo);
        } else if (f.type === "select") {
          const sel = document.createElement("select");
          sel.innerHTML = `<option value="">${esc(t("common.select"))}</option>` +
            (A.domainOptions(f.domain) || []).map(o =>
              `<option value="${o.id}">${esc(A.state.lang === "ar" ? o.label_ar : o.label_en)}</option>`).join("");
          sel.onchange = () => { state[f.key] = sel.value ? Number(sel.value) : null; };
          box.appendChild(sel);
        } else if (f.type === "textarea") {
          const ta = document.createElement("textarea");
          ta.rows = 2;
          ta.oninput = () => { state[f.key] = ta.value || null; };
          box.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.type = f.type === "date" ? "text" : (f.type === "int" || f.type === "float" ? "number" : "text");
          if (f.key === nameField) state[f.key] = null;
          inp.oninput = () => { state[f.key] = inp.value || null; };
          box.appendChild(inp);
        }
        grid.appendChild(box);
      });

      const cancel = () => {
        host.hidden = true;
        host.innerHTML = "";
        host.classList.remove("ent-composer");
        if (opts.onCancel) opts.onCancel();
      };
      host.querySelectorAll("[data-ec-cancel], [data-ec-cancel2]").forEach(b => { b.onclick = cancel; });
      host.querySelector("[data-ec-etype]").onchange = (ev) => {
        entity = ev.target.value;
        paint();
      };
      host.querySelector("[data-ec-save]").onclick = async () => {
        const errBox = host.querySelector("[data-ec-err]");
        errBox.innerHTML = "";
        const missing = required.filter(f => state[f.key] === undefined || state[f.key] === null || state[f.key] === "");
        if (missing.length) {
          errBox.innerHTML = `<div class="notice err small">${esc(t("common.required"))}: ` +
            missing.map(f => esc(A.regLabel(f))).join(", ") + "</div>";
          return;
        }
        try {
          const res = await api.post(`/api/${entity}`,
            { ...state, _reason: "created from workspace composer" });
          const rec = res.record;
          toast(`${t("rec.createdOk")} · ${rec.code}`, "ok");
          host.hidden = true;
          host.innerHTML = "";
          host.classList.remove("ent-composer");
          if (opts.onSaved) {
            opts.onSaved({
              id: rec.id, type: entity, code: rec.code,
              title: rec._title || rec.name_ar || rec.name_en || rec.title_ar || rec.code
            });
          }
        } catch (err) {
          errBox.innerHTML = `<div class="notice err small">${esc(err.message)}</div>`;
        }
      };
      return { cancel, el: host };
    }

    return paint();
  };

  /* ---------------------------------------------------- precise location --- */
  /**
   * A location control: separate latitude and longitude fields, or a click on
   * the map. A place name is never accepted here. `onChange` fires only when
   * the user sets a point; `show` displays an existing point without counting
   * as an edit.
   */
  A.coordControl = function (opts) {
    opts = opts || {};
    const el = document.createElement("div");
    el.className = "coord-desk";
    const lat0 = opts.lat != null && opts.lat !== "" ? Number(opts.lat).toFixed(6) : "";
    const lon0 = opts.lon != null && opts.lon !== "" ? Number(opts.lon).toFixed(6) : "";
    el.innerHTML = `
      <p class="hint">${esc(opts.hint || t("geo.preciseHint"))}</p>
      <div class="coord-desk-pair">
        <div class="coord-desk-axis">
          <label for="${esc("coord-lat-" + Math.random().toString(36).slice(2, 8))}">${esc(t("desk.lat"))}</label>
          <input type="text" dir="ltr" data-coord-lat autocomplete="off"
                 inputmode="decimal" placeholder="33.315200"
                 value="${esc(lat0)}">
        </div>
        <div class="coord-desk-axis">
          <label>${esc(t("desk.lon"))}</label>
          <input type="text" dir="ltr" data-coord-lon autocomplete="off"
                 inputmode="decimal" placeholder="44.366100"
                 value="${esc(lon0)}">
        </div>
      </div>
      <div class="coord-desk-err" data-coord-err></div>
      <div class="coord-desk-map" data-coord-map></div>
      <div class="muted small">${esc(t("geo.pickOnMap"))}</div>`;
    const latInput = el.querySelector("[data-coord-lat]");
    const lonInput = el.querySelector("[data-coord-lon]");
    const err = el.querySelector("[data-coord-err]");
    const canvas = el.querySelector("[data-coord-map]");
    let user = null;
    let map = null;
    let attribEl = null;
    let marker = null;

    function writeInput(lat, lon) {
      latInput.value = Number(lat).toFixed(6);
      lonInput.value = Number(lon).toFixed(6);
    }
    function moveMarker(lat, lon, zoom) {
      if (!map || !window.maplibregl) return;
      if (!map.loaded()) { map.once("load", () => moveMarker(lat, lon, zoom)); return; }
      const ll = [Number(lon), Number(lat)];
      if (!marker) {
        if (A.geopin) {
          marker = A.geopin.marker(map, ll, {
            etype: (opts && opts.etype) || "place",
            label: (opts && opts.label) || "",
            selected: true, size: "lg", showLabel: false, draggable: true
          });
        } else {
          marker = new window.maplibregl.Marker({ color: "#8a1c1c", draggable: true })
            .setLngLat(ll).addTo(map);
        }
        if (marker) {
          marker.on("dragend", () => {
            const p = marker.getLngLat();
            commit(p.lat, p.lng, "map_pick");
          });
        }
      } else {
        marker.setLngLat(ll);
      }
      if (zoom) map.easeTo({ center: ll, zoom: Math.max(map.getZoom(), 13), duration: 280 });
    }
    function commit(lat, lon, method) {
      user = { lat: Number(lat), lon: Number(lon), method: method || "coordinate_entry" };
      writeInput(user.lat, user.lon);
      err.textContent = "";
      moveMarker(user.lat, user.lon, true);
      if (opts.onChange) opts.onChange(user);
    }
    function show(lat, lon) {
      if (lat == null || lon == null || lat === "" || lon === "") return;
      writeInput(lat, lon);
      moveMarker(lat, lon, true);
    }
    async function parseFields(sourceEl) {
      const latQ = latInput.value.trim();
      const lonQ = lonInput.value.trim();
      /* a full pair pasted into either box splits into both fields */
      if (sourceEl && sourceEl.value && /[,;]/.test(sourceEl.value)) {
        try {
          const res = await api.get("/api/map/parse?q=" + encodeURIComponent(sourceEl.value.trim()));
          if (res.ok) { commit(res.lat, res.lon, "coordinate_entry"); return; }
        } catch (e) { /* fall through to the two-field path */ }
      }
      if (!latQ && !lonQ) {
        user = null; err.textContent = "";
        if (opts.onChange) opts.onChange(null);
        return;
      }
      if (!latQ || !lonQ) {
        user = null;
        err.textContent = t("geo.preciseNeedPair");
        if (opts.onChange) opts.onChange(null);
        return;
      }
      try {
        const res = await api.get("/api/map/parse?q=" + encodeURIComponent(latQ + ", " + lonQ));
        if (!res.ok) {
          user = null;
          err.textContent = res.message || t("geo.preciseNeedPair");
          if (opts.onChange) opts.onChange(null);
          return;
        }
        commit(res.lat, res.lon, "coordinate_entry");
      } catch (e) {
        err.textContent = e.message || t("geo.preciseNeedPair");
      }
    }
    [latInput, lonInput].forEach(inp => {
      inp.addEventListener("change", () => parseFields(inp));
      inp.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); parseFields(inp); }
      });
    });

    if (window.maplibregl) {
      const centerLat = Number(A.setting("map.center_lat", "33.3152"));
      const centerLon = Number(A.setting("map.center_lon", "44.3661"));
      const startLat = opts.lat != null ? Number(opts.lat) : centerLat;
      const startLon = opts.lon != null ? Number(opts.lon) : centerLon;
      /* Boot on the quiet graphical bed and honour the default map view the
         way the list and inspect maps do: the bundled street pack paints over
         it, and a raster choice becomes the bed underneath. (Booting the
         picker straight at OSM bypassed both — and third-party tile servers
         answer some deployments with policy block cards instead of tiles.) */
      map = new window.maplibregl.Map({
        container: canvas,
        style: { version: 8, sources: {}, layers: [
            { id: "bg", type: "background", paint: { "background-color": "#d5e0ea" } }
          ] },
        center: [startLon, startLat],
        zoom: opts.lat != null ? 12 : Number(A.setting("map.zoom", "5")),
        attributionControl: false
      });
      map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), "top-right");
      const repaintPack = () => {
        if (!map || !A.loadVectormap || !A.applyVectormapLayers) return;
        A.loadVectormap().then(inflated => {
          if (map) A.applyVectormapLayers(map, inflated, { fit: false });
        }).catch(() => { /* the pack is optional; the pick still answers */ });
      };
      (async () => {
        try {
          const mapCfg = A.mapConfig ? await A.mapConfig().catch(() => null) : null;
          const defaultProvider = (A.mapDefault && A.mapDefault().provider) || "local";
          const entry = ((mapCfg && mapCfg.providers) || []).find(p => p.id === defaultProvider) || null;
          const boot = (A.geopin && A.geopin.secondaryStyle)
            ? A.geopin.secondaryStyle(defaultProvider, mapCfg)
            : null;
          if (!map) return;
          if (boot && boot.sources && Object.keys(boot.sources).length) {
            map.setStyle(boot);
            map.once("styledata", repaintPack);
          } else {
            repaintPack();
          }
          /* attribution travels with the provider by contract */
          if (entry) {
            const text = A.state.lang === "ar" ? entry.attribution_ar : entry.attribution_en;
            if (text && map && canvas.parentElement) {
              attribEl = document.createElement("div");
              attribEl.className = "inspect-map-attrib small muted";
              attribEl.innerHTML = `<a href="${esc(entry.attribution_url || "#")}" target="_blank"`
                + ` rel="noopener noreferrer">${esc(text)}</a>`;
              canvas.parentElement.insertBefore(attribEl, canvas.nextSibling);
            }
          }
        } catch (e) { repaintPack(); }
      })();
      map.on("load", () => {
        if (opts.lat != null && opts.lon != null) show(opts.lat, opts.lon);
        map.resize();
      });
      map.on("click", (ev) => commit(ev.lngLat.lat, ev.lngLat.lng, "map_pick"));
    } else {
      canvas.innerHTML = `<div class="notice small">${esc(t("geo.preciseNeedPair"))}</div>`;
    }

    return {
      el,
      show,
      userPoint() { return user; },
      destroy() {
        if (map) { map.remove(); map = null; }
        if (attribEl) { attribEl.remove(); attribEl = null; }
      }
    };
  };

  /* --------------------------------------------------------- validation --- */
  A.normText = function (s) {
    return String(s || "").toLowerCase()
      .replace(/[\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىي]/g, "ي").replace(/ة/g, "ه")
      .replace(/\s+/g, " ").trim();
  };
})();
