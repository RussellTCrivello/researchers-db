/* ============================================================================
   SIRAJ · components/fields.js — one control per field type, everywhere
   ----------------------------------------------------------------------------
   The record form, the inline-create pop-up and the filter builder all ask the
   same question: "what input does this field need?"  Until now each screen grew
   its own answer, which is how a filter ends up as a bare text box while the
   form next to it offers a searchable dropdown.

   This module is that answer, once:

       const el = A.control(field, { value, mode: "form" | "filter", onChange })

   * `mode: "form"`   — the full treatment: inline creation, image upload,
                        help text, required markers.
   * `mode: "filter"` — the same widget, minus the record-only extras, plus the
                        range/multi shortcuts a filter needs.

   Controls
     text · textarea · url · int · float · bool · tags
     select   → <select> for short vocabularies, searchable combobox for long ones
     fk       → searchable combobox with inline create
     date     → date picker + optional time picker + a precision selector, so a
                researcher can record "1950", "12 March 1947" or
                "12 March 1947, 09:30" and the registry keeps exactly that much
                precision instead of inventing a midnight
   ========================================================================== */
(function () {
  "use strict";

  const A = window.App;
  const { t, esc } = A;

  /* ------------------------------------------------------------- helpers --- */

  /** Split a stored value into its date and time parts (both optional). */
  function splitMoment(value) {
    const s = String(value == null ? "" : value).trim();
    if (!s) return { date: "", time: "" };
    const m = s.match(/^(\d{3,4}(?:-\d{2}(?:-\d{2})?)?)(?:[T ](\d{2}:\d{2}(?::\d{2})?))?/);
    if (!m) return { date: "", time: "", raw: s };
    return { date: m[1] || "", time: m[2] || "", raw: s };
  }

  /** Recombine the parts into the ISO form the API stores. */
  function joinMoment(date, time) {
    const d = String(date || "").trim();
    if (!d) return "";
    if (!time) return d;
    return `${d}T${String(time).slice(0, 5)}${String(time).length > 5 ? String(time).slice(5, 8) : ""}`;
  }

  /** Human display: 1947-03-12 09:30 → "12 Mar 1947, 09:30" (locale-aware enough). */
  function formatMoment(value, opts) {
    opts = opts || {};
    const s = String(value == null ? "" : value).trim();
    if (!s) return "";
    const ar = A.state.lang === "ar";
    const legacy = s.match(/^(c\.\s?\d{3,4}s?|\d{3,4}s|\d{3,4}\?)$/);   // circa / decade
    if (legacy) return s;
    const p = splitMoment(s);
    if (!p.date) return s;
    const bits = p.date.split("-");
    let out;
    if (bits.length === 1) out = bits[0];
    else if (bits.length === 2) {
      const month = Number(bits[1]);
      out = opts.numeric || !month
        ? `${bits[0]}-${bits[1]}`
        : ar ? `${bits[1]}/${bits[0]}` : `${monthName(month, ar)} ${bits[0]}`;
    } else {
      const day = Number(bits[2]), month = Number(bits[1]);
      out = opts.numeric
        ? `${bits[0]}-${bits[1]}-${bits[2]}`
        : ar ? `${day} ${monthName(month, ar)} ${bits[0]}` : `${day} ${monthName(month, ar)} ${bits[0]}`;
    }
    if (p.time && opts.time !== false) out += `, ${p.time.slice(0, 5)}`;
    return out;
  }

  function monthName(n, ar) {
    const en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const arabic = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
    return (ar ? arabic : en)[n - 1] || String(n);
  }

  /** Precision of a stored moment — used by the picker's little selector. */
  function precisionOf(value) {
    const p = splitMoment(value);
    if (!p.date) return "year";
    const parts = p.date.split("-").length;
    if (parts === 1) return "year";
    if (parts === 2) return "month";
    return p.time ? "minute" : "day";
  }

  /* --------------------------------------------------------- date control --- */
  /**
   * Date (and, where it matters, time) input.
   *
   * `field.time` decides whether the time row is offered; `allowTime` lets a
   * filter ask for a time on any date field ("changed after 14:30 yesterday").
   */
  A.dateControl = function (opts) {
    opts = opts || {};
    const field = opts.field || { type: "date" };
    const allowTime = opts.allowTime !== undefined ? opts.allowTime : !!field.time;
    /* Filter mode: one date field (+ an optional time), no precision select and no
       "now" button — a filter bound does not need to state how precisely it knows
       the boundary, and `ts_of()` expands a partial bound downwards anyway. */
    const compact = opts.compact !== undefined ? opts.compact : opts.mode === "filter";
    const wrap = document.createElement("div");
    wrap.className = "date-control";
    let value = String(opts.value == null ? "" : opts.value);

    const precision = opts.precision || precisionOf(value);
    const parts = splitMoment(value);
    const raw = parts.raw || "";

    wrap.innerHTML = `
      <div class="date-row">
        <input type="date" data-date value="${esc(parts.date && parts.date.length >= 10 ? parts.date : "")}"
               aria-label="${esc(opts.label || field.label_en || "date")}">
        ${allowTime ? `<input type="time" data-time value="${esc(parts.time.slice(0, 5))}"
               aria-label="${esc(t("fields.time") || "time")}"
               ${compact && !parts.time ? "hidden" : ""}>` : ""}
        ${allowTime && compact ? `<button type="button" class="btn sm ghost" data-time-toggle
               title="${esc(t("fields.time") || "time")}" aria-label="${esc(t("fields.time") || "time")}"
               ${parts.time ? "hidden" : ""}>◷</button>` : ""}
        ${allowTime && !compact ? `<button type="button" class="btn sm ghost" data-today
               title="${esc(t("fields.now") || "now")}">${esc(t("fields.now") || "now")}</button>` : ""}
      </div>
      ${compact ? "" : `<div class="date-row secondary">
        <select data-precision class="precision" aria-label="${esc(t("fields.precision") || "precision")}">
          ${["year", "month", "day"].concat(allowTime ? ["minute"] : []).map(p =>
            `<option value="${p}" ${precision === p ? "selected" : ""}>${esc(t("fields.precision." + p) || p)}</option>`).join("")}
        </select>
        ${raw && !parts.date ? `<span class="chip legacy" title="${esc(raw)}">${esc(raw)}</span>` : ""}
        <span class="date-preview">${esc(formatMoment(value))}</span>
      </div>`}`;

    const dateIn = wrap.querySelector("[data-date]");
    const timeIn = wrap.querySelector("[data-time]");
    const precSel = wrap.querySelector("[data-precision]");
    const preview = wrap.querySelector(".date-preview");
    const setPreview = (txt) => { if (preview) preview.textContent = txt; };

    function emit() {
      let out = "";
      const d = dateIn.value;                       // YYYY-MM-DD or ""
      const pr = precSel ? precSel.value : (timeIn && timeIn.value ? "minute" : "day");
      if (d) {
        const bits = d.split("-");
        if (pr === "year") out = bits[0];
        else if (pr === "month") out = `${bits[0]}-${bits[1]}`;
        else out = d;
        if (pr === "minute" && timeIn && timeIn.value) out = `${d}T${timeIn.value}`;
      }
      value = out;
      setPreview(formatMoment(out) || "—");
      if (timeIn && precSel) timeIn.hidden = precSel.value !== "minute";
      if (opts.onChange) opts.onChange(out || null);
    }

    // keep the date input usable for partial precision: fill missing parts so the
    // native picker has something to show, but never let it invent them back
    function syncDateInput() {
      const d = dateIn.value;
      if (!d) return;
      const bits = d.split("-");
      if (!precSel) return;
      const pr = precSel.value;
      if (pr === "year") dateIn.value = `${bits[0]}-01-01`;
      else if (pr === "month") dateIn.value = `${bits[0]}-${bits[1]}-01`;
    }

    /* Typing a full date while the select says "year" must not silently throw the
       month and day away: the control promotes itself to the precision of what
       was actually entered.  Lowering the select afterwards still truncates —
       that is the deliberate way to say "I only know the year". */
    const RANK = { year: 1, month: 2, day: 3, minute: 4 };
    function promote() {
      const d = dateIn.value;
      if (!d || !precSel) return;
      let want = "day";
      if (timeIn && timeIn.value && precSel.value === "minute") want = "minute";
      if (RANK[precSel.value] < RANK[want]) precSel.value = want;
    }

    [dateIn, timeIn, precSel].forEach(el => {
      if (!el) return;
      el.addEventListener("change", () => { promote(); syncDateInput(); emit(); });
      el.addEventListener("input", () => { if (el !== dateIn) emit(); else promote(); });
    });

    const timeToggle = wrap.querySelector("[data-time-toggle]");
    if (timeToggle) timeToggle.onclick = () => {
      timeToggle.hidden = true;
      if (timeIn) { timeIn.hidden = false; timeIn.focus(); }
    };

    const todayBtn = wrap.querySelector("[data-today]");
    if (todayBtn) todayBtn.onclick = () => {
      const now = new Date();
      const pad = n => String(n).padStart(2, "0");
      dateIn.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
      if (timeIn) timeIn.value = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
      if (precSel) precSel.value = timeIn ? "minute" : "day";
      emit();
    };

    // An empty field starts at day precision: someone who opens the picker and
    // chooses a date means that date.  Historical precision (a bare year) is one
    // click away in the precision select.
    if (precSel && !parts.date && !raw) precSel.value = "day";
    if (timeIn && precSel) timeIn.hidden = precSel.value !== "minute";

    wrap.getValue = () => value;
    wrap.setValue = (v) => {
      value = String(v == null ? "" : v);
      const p = splitMoment(value);
      dateIn.value = p.date && p.date.length >= 10 ? p.date
        : p.date && p.date.length === 7 ? `${p.date}-01`
        : p.date ? `${p.date}-01-01` : "";
      if (timeIn) timeIn.value = p.time.slice(0, 5);
      if (precSel) precSel.value = precisionOf(value);
      if (timeIn && precSel) timeIn.hidden = precSel.value !== "minute";
      setPreview(formatMoment(value) || "—");
    };
    return wrap;
  };

  /* ------------------------------------------------------------ the router --- */
  /**
   * Build the control for a field.  Returns a detached element whose
   * `getValue()` / `setValue()` are the only contract the caller needs.
   */
  A.control = function (field, opts) {
    opts = opts || {};
    const mode = opts.mode || "form";
    let value = opts.value === undefined || opts.value === null ? "" : opts.value;
    const set = (v) => {
      value = v;
      if (opts.onChange) opts.onChange(v);
    };
    let el;

    switch (field.type) {
      case "select":
        el = (A.isLargeList && A.isLargeList(field))
          ? A.combobox({
              domain: field.domain, value: value || null, size: opts.size || "sm",
              placeholder: opts.placeholder || t("common.search"),
              onSelect: (it) => set(it ? it.id : null),
              onClear: () => set(null)
            })
          : (() => {
              const sel = document.createElement("select");
              sel.innerHTML = `<option value="">${esc(t("common.select"))}</option>` +
                (A.domainOptions(field.domain) || []).map(o =>
                  `<option value="${o.id}" ${String(value) === String(o.id) ? "selected" : ""}>
                     ${esc(A.state.lang === "ar" ? o.label_ar : o.label_en)}</option>`).join("");
              sel.onchange = () => set(sel.value ? Number(sel.value) : null);
              return sel;
            })();
        break;

      case "fk":
        el = A.combobox({
          entity: field.ref, value: value ? Number(value) : null, size: opts.size || "sm",
          /* personal preference → instance setting → on.  The settings screen
             offers "use for me only" for this key, so the consumer has to read
             the same three levels. */
          allowCreate: opts.allowCreate !== undefined
            ? opts.allowCreate
            : String(A.resolvePref
                ? A.resolvePref("inline_create", "ui.inline_create", "true")
                : (A.setting ? A.setting("ui.inline_create", "true") : "true")) !== "false",
          placeholder: opts.placeholder || t("common.search"),
          onSelect: (it) => set(it ? it.id : null),
          onClear: () => set(null)
        });
        break;

      case "date":
        el = A.dateControl({
          field, value: value || "", allowTime: opts.allowTime, mode,
          onChange: (v) => set(v)
        });
        break;

      case "bool": {
        const lab = document.createElement("label");
        lab.className = "check";
        lab.innerHTML = `<input type="checkbox" ${value === 1 || value === true ? "checked" : ""}>
          ${esc(opts.label || t("common.yes"))}`;
        lab.querySelector("input").onchange = (e) => set(e.target.checked ? 1 : 0);
        el = lab;
        break;
      }

      case "int":
      case "float": {
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = field.type === "float" ? "any" : "1";
        inp.value = value === "" ? "" : value;
        inp.placeholder = opts.placeholder || "";
        inp.oninput = () => set(inp.value === "" ? null : Number(inp.value));
        el = inp;
        break;
      }

      case "textarea": {
        const ta = document.createElement("textarea");
        ta.rows = opts.rows || (mode === "filter" ? 1 : 3);
        ta.value = value;
        ta.placeholder = opts.placeholder || "";
        ta.oninput = () => set(ta.value || null);
        el = ta;
        break;
      }

      case "url": {
        const inp = document.createElement("input");
        inp.type = "text";
        inp.value = value;
        inp.placeholder = opts.placeholder || "https://";
        inp.oninput = () => set(inp.value || null);
        el = inp;
        break;
      }

      case "tags":
        el = A.multiCombo({
          domain: field.tag_domain || "topic", values: value || [],
          size: opts.size || "sm",
          onChange: (v) => set(v)
        });
        break;

      default: {
        const inp = document.createElement("input");
        inp.type = "text";
        inp.value = value;
        if (field.max_len) inp.maxLength = field.max_len;
        inp.placeholder = opts.placeholder || "";
        inp.oninput = () => set(inp.value || null);
        el = inp;
      }
    }

    if (el && el.nodeType === 1) {
      el.classList.add("control", `control-${field.type}`);
      el.dataset.field = field.key || "";
      el.getValue = () => value;
      el.setValue = (v) => {
        value = v;
        if (el.tagName === "SELECT") el.value = v == null ? "" : String(v);
        else if (el.tagName === "INPUT") {
          if (el.type === "checkbox") el.checked = !!v;
          else el.value = v == null ? "" : v;
        } else if (el.tagName === "TEXTAREA") el.value = v == null ? "" : v;
        else if (el.setValue) el.setValue(v);
      };
    }
    return el;
  };

  A.formatMoment = formatMoment;
  A.splitMoment = splitMoment;
  A.joinMoment = joinMoment;
  A.momentPrecision = precisionOf;

  /* --------------------------------------------------------- filter picker --- */
  /**
   * A grouped, searchable field picker for the filter builder: the same groups
   * and labels the record form shows, so a filter can be described in the
   * vocabulary of the form the data was entered with.
   */
  A.fieldPicker = function (opts) {
    opts = opts || {};
    const fields = opts.fields || [];
    const selected = opts.value || "";
    const wrap = document.createElement("div");
    wrap.className = "field-picker";
    const groups = {};
    fields.forEach(f => { (groups[f.group || "main"] = groups[f.group || "main"] || []).push(f); });

    wrap.innerHTML = `
      <button type="button" class="btn sm picker-btn" data-open>
        <span data-current>${esc(labelOf(fields.find(f => f.key === selected)) || t("list.chooseField"))}</span>
        <span class="caret">▾</span>
      </button>
      <div class="picker-pop" hidden>
        <input type="search" data-filter placeholder="${esc(t("common.search"))}">
        <div class="picker-list" data-list>
          ${Object.keys(groups).map(g => `
            <div class="picker-group" data-group>
              <div class="picker-group-title">${esc(t("group." + g) || g)}</div>
              ${groups[g].map(f => `
                <button type="button" class="picker-item" data-key="${esc(f.key)}"
                        data-type="${esc(f.type)}">
                  <span class="picker-icon">${esc(iconFor(f.type))}</span>
                  <span class="picker-label">${esc(labelOf(f))}</span>
                  ${f.derived ? `<span class="pill tiny">ƒ</span>` : ""}
                  ${f.type === "date" ? `<span class="pill tiny">${esc(f.time ? "date+time" : "date")}</span>` : ""}
                </button>`).join("")}
            </div>`).join("")}
        </div>
      </div>`;

    function labelOf(f) {
      return f ? (A.state.lang === "ar" ? (f.label_ar || f.label_en) : (f.label_en || f.label_ar)) : "";
    }
    function iconFor(type) {
      return ({ text: "A", textarea: "¶", url: "🔗", int: "#", float: "#", date: "◷",
                select: "▤", fk: "⇄", bool: "☑", tags: "◇" })[type] || "·";
    }

    const pop = wrap.querySelector(".picker-pop");
    const btn = wrap.querySelector("[data-open]");
    const search = wrap.querySelector("[data-filter]");
    btn.onclick = () => {
      pop.hidden = !pop.hidden;
      if (!pop.hidden) { search.value = ""; filterList(""); search.focus(); }
    };
    search.oninput = () => filterList(search.value);
    function filterList(q) {
      const needle = A.normText(q);
      wrap.querySelectorAll("[data-group]").forEach(g => {
        let shown = 0;
        g.querySelectorAll("[data-key]").forEach(it => {
          const match = !needle || A.normText(it.textContent).includes(needle);
          it.hidden = !match;
          if (match) shown++;
        });
        g.hidden = !shown;
      });
    }
    wrap.querySelectorAll("[data-key]").forEach(it => {
      it.onclick = () => {
        pop.hidden = true;
        wrap.querySelector("[data-current]").textContent =
          labelOf(fields.find(f => f.key === it.dataset.key));
        if (opts.onPick) opts.onPick(it.dataset.key);
      };
    });
    document.addEventListener("click", (ev) => {
      if (!wrap.isConnected) return;
      if (!wrap.contains(ev.target)) pop.hidden = true;
    });
    return wrap;
  };
})();
