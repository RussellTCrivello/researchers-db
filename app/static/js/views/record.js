/* ============================================================================
   SIRAJ · record.js — record dossier + create/edit form
     • profile hero (portrait, badges, key facts, KPI strip, completeness ring)
     • "related tables" panel: fields derived from related tables
     • ego network diagram for persons & institutions
     • searchable comboboxes everywhere a field points at another table,
       with inline creation of the missing record (A.quickCreate)
     • image upload / alt text, sticky action bar, dirty-state guard
   ========================================================================== */
(function () {
  "use strict";
  const A = window.App;
  const { t, api, esc, icon, hydrateIcons, toast, fmtNum } = A;

  const GROUP_ORDER = ["identity", "life", "career", "location", "geo", "timing", "link",
    "detail", "people", "profile", "content", "assessment", "research", "history",
    "contact", "meta", "system"];

  const NAME_FIELD = { person: "name_ar", institution: "name_ar", place: "name_ar",
    source: "title", event: "title_ar", relationship: "description" };

  function dv(rec, key) {
    const d = rec._derived || {};
    return d[key];
  }
  function dLabel(entity, key) {
    return A.regLabel(A.regField(entity, key));
  }
  function hasDV(rec, key) {
    const v = dv(rec, key);
    return v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length);
  }

  /* ------------------------------------------------------- completeness --- */
  function ring(pct, label) {
    const v = Math.max(0, Math.min(100, Number(pct) || 0));
    const C = 2 * Math.PI * 26;
    const off = C * (1 - v / 100);
    const color = v >= 75 ? "#1d7a52" : v >= 40 ? "#b5751a" : "#a4302e";
    return `<svg class="ring" viewBox="0 0 64 64" role="img" aria-label="${esc(label)}">
      <circle cx="32" cy="32" r="26" fill="none" stroke="rgba(125,139,150,.22)" stroke-width="6"/>
      <circle cx="32" cy="32" r="26" fill="none" stroke="${color}" stroke-width="6"
              stroke-linecap="round" stroke-dasharray="${C.toFixed(1)}"
              stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 32 32)"/>
      <text x="32" y="37" text-anchor="middle">${v}%</text></svg>`;
  }

  /* ------------------------------------------------------------- ego net --- */
  function egoNetwork(rec) {
    const rels = (rec.relationships || []).filter(r => r.other_id).slice(0, 16);
    if (!rels.length) return "";
    const W = 560, H = 320, cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) / 2 - 62;
    const nodes = rels.map((r, i) => {
      const ang = (i / rels.length) * Math.PI * 2 - Math.PI / 2;
      return { r, x: cx + R * Math.cos(ang), y: cy + R * Math.sin(ang) };
    });
    const shape = (r) => ({ person: "circle", institution: "rect", place: "diamond",
      source: "book", event: "sq" }[r.other_type] || "circle");
    const nodeSvg = nodes.map(n => {
      const typeLabel = A.label(n.r.other_type);
      const relLabel = A.state.lang === "ar" ? (n.r.type_ar || n.r.type_en) : (n.r.type_en || "");
      const short = A.truncate(n.r.other_name || "", 16);
      let glyph = "";
      if (shape(n.r) === "circle") glyph = `<circle class="n-node" cx="${n.x}" cy="${n.y}" r="9"/>`;
      else if (shape(n.r) === "rect") glyph = `<rect class="n-node" x="${n.x - 8}" y="${n.y - 8}" width="16" height="16" rx="2"/>`;
      else if (shape(n.r) === "diamond") glyph = `<polygon class="n-node" points="${n.x},${n.y - 10} ${n.x + 10},${n.y} ${n.x},${n.y + 10} ${n.x - 10},${n.y}"/>`;
      else glyph = `<rect class="n-node" x="${n.x - 8}" y="${n.y - 10}" width="16" height="20" rx="1.5"/>`;
      const left = n.x < cx;
      return `<a href="#/entity/${n.r.other_type}/${n.r.other_id}">
        <title>${esc(n.r.other_name || "")} — ${esc(relLabel)} (${esc(typeLabel)})</title>
        <line class="e-line" x1="${cx}" y1="${cy}" x2="${n.x}" y2="${n.y}"/>
        ${glyph}
        <text class="n-label" x="${n.x + (left ? -13 : 13)}" y="${n.y + 3}"
              text-anchor="${left ? "end" : "start"}">${esc(short)}</text></a>`;
    }).join("");
    return `<div class="ego">
      <div class="sectionlabel">${t("rec.relationsMap")}</div>
      <svg viewBox="0 0 ${W} ${H}" role="img">
        ${nodeSvg}
        <circle class="n-center" cx="${cx}" cy="${cy}" r="15"/>
        <text class="n-label" x="${cx}" y="${cy + 32}" text-anchor="middle"
              style="font-weight:700">${esc(A.truncate(rec._title || "", 22))}</text>
      </svg></div>`;
  }

  /* ============================================================ detail === */
  A.views.record = async function (root, params) {
    const { entity, id } = params;
    root.dataset.surface = `record:${entity}:${id}`;
    const rec = await api.get(`/api/${entity}/${id}`);
    const spec = A.entitySpec(entity) || {};
    const title = A.dispTitle(rec, entity) || rec.code;
    A.crumbs([{ label: A.pluralOf(entity), href: `#/entity/${entity}` }, { label: title }]);

    const status = rec._labels && rec._labels.record_status_id;
    const auth = rec._labels && rec._labels.authentication_id;
    const portrait = rec.image_url;
    const completeness = dv(rec, "completeness");

    /* key facts: a handful of the most telling values */
    const factKeys = {
      person: ["classification_id", "nationality_id", "affiliated_institution_id", "birth_place_id"],
      institution: ["institution_type_id", "country_id", "governance_id", "founded_year"],
      place: ["place_type_id", "country_id", "parent_place_id"],
      source: ["source_type_id", "publication_date", "publisher"],
      event: ["event_type_id", "start_date", "place_id"],
      relationship: ["relationship_type_id", "entity1_name", "entity2_name"]
    }[entity] || [];
    const facts = factKeys.map(k => {
      const f = A.regField(entity, k);
      if (!f) return "";
      const lab = (rec._labels || {})[k];
      const ref = (rec._refs || {})[k];
      const raw = rec[k];
      if (lab) {
        return `<span class="hfact">${esc(A.regLabel(f))}: <b>${esc(A.state.lang === "ar" ? lab.ar : lab.en)}</b></span>`;
      }
      if (ref) {
        return `<span class="hfact">${esc(A.regLabel(f))}:
          <a href="#/entity/${f.ref}/${ref.id}"><b>${esc(A.truncate(ref.label || "", 40))}</b></a></span>`;
      }
      if (raw === null || raw === undefined || raw === "") return "";
      if (k === "publisher" || k === "entity1_name" || k === "entity2_name") {
        return `<span class="hfact">${esc(A.regLabel(f))}: <b>${esc(A.truncate(String(raw), 34))}</b></span>`;
      }
      return `<span class="hfact">${esc(A.regLabel(f))}: <b>${esc(raw)}</b></span>`;
    }).join("");

    /* KPI strip — counts computed from related tables */
    const NOT_A_KPI = ["birth_year", "death_year", "age_at_death", "founded_year", "year",
      "start_year", "end_year", "duration_years", "has_coords", "completeness"];
    const statKeys = A.registry(entity)
      .filter(f => f.kind === "derived" && f.type === "int" && !NOT_A_KPI.includes(f.key))
      .map(f => f.key)
      .filter(k => hasDV(rec, k))
      .slice(0, 6);
    const stats = statKeys.map(k =>
      `<div><b>${fmtNum(dv(rec, k))}</b><span>${esc(dLabel(entity, k))}</span></div>`).join("");
    const hasSide = stats || (completeness !== null && completeness !== undefined);
    const canHaveEvents = ["person", "institution", "place"].includes(entity);
    const eventIds = canHaveEvents
      ? (rec.relationships || [])
          .filter(r => r.other_type === "event" && r.other_id)
          .map(r => Number(r.other_id))
          .filter((eid, i, arr) => eid && arr.indexOf(eid) === i)
      : [];
    const relRows = canHaveEvents
      ? (rec.relationships || []).filter(r => r.other_type !== "event")
      : (rec.relationships || []);
    const relCount = relRows.length;

    root.innerHTML = `
      ${rec.deleted_at ? `<div class="notice warn">${t("rec.inTrash")}
        <button class="btn sm" id="recRestoreInline">${icon("undo")} ${t("common.restore")}</button></div>` : ""}
      <div class="hero">
        <div class="portrait">${portrait
          ? `<img src="${esc(portrait)}" alt="${esc(rec.image_alt || title)}"
                  onerror="this.parentNode.textContent='${esc(A.initials(title))}'">`
          : esc(A.initials(title))}</div>
        <div>
          <div class="htitle">
            <h1>${esc(title)}</h1>
            <span class="badge gray mono-cell">${esc(rec.code)}</span>
            ${status ? A.statusBadge(status) : ""}
            ${auth ? A.statusBadge(auth) : ""}
            ${rec.deleted_at ? `<span class="badge red">${esc(t("common.deleted"))}</span>` : ""}
          </div>
          <div class="hmeta">
            ${spec ? `<span>${esc(A.state.lang === "ar" ? spec.plural_ar : spec.plural_en)}</span>` : ""}
            <span>${t("common.updated")}: ${esc(A.ago(rec.updated_at))}</span>
            <span>${t("common.by") || "by"} ${esc(rec.updated_by || "—")}</span>
            <span>v${esc(rec.version)}</span>
          </div>
          ${facts ? `<div class="hfacts">${facts}</div>` : ""}
        </div>
        ${hasSide ? `<div class="hero-side">
          ${completeness !== null && completeness !== undefined
            ? `<div class="completeness">${ring(completeness, dLabel(entity, "completeness"))}
                 <div class="small muted">${esc(dLabel(entity, "completeness"))}</div></div>`
            : ""}
          ${stats ? `<div class="hstats">${stats}</div>` : ""}
        </div>` : "<div></div>"}
      </div>
      <div class="toolbar no-print" style="margin-bottom:12px">
        <a class="btn primary" href="#/entity/${entity}/${id}/edit">${icon("edit")} ${t("common.edit")}</a>
        <button class="btn" id="recPrint">${icon("print")} ${t("common.print")}</button>
        <button class="btn" id="recExport">${icon("download")} ${t("common.export")}</button>
        <button class="btn" id="recDuplicates">${icon("share")} ${t("common.duplicates") || "Duplicates"}</button>
        ${["person", "institution", "place"].includes(entity)
          ? `<a class="btn" data-open-diagram href="#/map?focus=${esc(entity)}:${id}">
               ${icon("link")} ${t("map.openInDiagram")}</a>`
          : ""}
        <span class="spacer"></span>
        ${rec.deleted_at
          ? `<button class="btn" id="recRestore">${icon("undo")} ${t("common.restore")}</button>`
          : `<button class="btn danger" id="recDelete">${icon("trash")} ${t("common.delete")}</button>`}
      </div>
      <div class="tabs" id="recTabs">
        <button class="active" data-tab="overview">${t("common.details")}</button>
        ${canHaveEvents ? `<button data-tab="events">${icon("calendar")} ${t("inspect.tab.events")} (${eventIds.length})</button>` : ""}
        <button data-tab="relations">${t("rec.relationships")} (${relCount})</button>
        <button data-tab="citations">${t("rec.citations")} (${(rec.citations || []).length})</button>
        <button data-tab="files">${t("rec.attachments")} (${(rec.attachments || []).length})</button>
        <button data-tab="derived">Ƒ ${A.t("ui.relatedTables2")}</button>
        ${spec && spec.has_positions ? `<button data-tab="positions">${t("rec.positions")} (${(rec.positions || []).length})</button>` : ""}
        <button data-tab="position">◉ ${t("crce.tab")}</button>
        <button data-tab="history">${t("rec.history")}</button>
      </div>
      <div id="tabBody"></div>`;

    hydrateIcons(root);
    const tabs = {
      overview: () => overviewTab(),
      derived: () => derivedTab(),
      position: () => positionTab(),
      positions: () => positionsTab(),
      relations: () => relationsTab(),
      events: () => eventsTab(),
      citations: () => citationsTab(),
      files: () => filesTab(),
      history: () => historyTab()
    };
    const body = root.querySelector("#tabBody");
    function show(name) {
      root.querySelectorAll("#recTabs button").forEach(b =>
        b.classList.toggle("active", b.dataset.tab === name));
      body.innerHTML = "";
      tabs[name]().forEach(el => body.appendChild(el));
      hydrateIcons(body);
    }
    root.querySelectorAll("#recTabs button").forEach(b => { b.onclick = () => show(b.dataset.tab); });
    show("overview");

    root.querySelector("#recPrint").onclick = () => window.print();
    const ex = root.querySelector("#recExport");
    if (ex) ex.onclick = () => A.openExportModal(entity);
    const dupBtn = root.querySelector("#recDuplicates");
    if (dupBtn) dupBtn.onclick = () => A.openDuplicates(entity);
    const del = root.querySelector("#recDelete");
    if (del) del.onclick = () => deleteRec(entity, id);
    const rst = root.querySelector("#recRestore") || root.querySelector("#recRestoreInline");
    if (rst) rst.onclick = async () => {
      await api.post(`/api/${entity}/${id}/restore`);
      toast(t("common.restored"), "ok"); A.rerender();
    };

    /* ---- tabs --------------------------------------------------------- */
    function fieldValue(f) {
      const v = rec[f.key];
      if (v === null || v === undefined || v === "") return `<span class="empty-val">—</span>`;
      const lab = (rec._labels || {})[f.key];
      const ref = (rec._refs || {})[f.key];
      if (lab) return A.badge(A.state.lang === "ar" ? lab.ar : lab.en, lab.color);
      if (ref) {
        return `<a href="#/entity/${f.ref}/${ref.id}">${esc(ref.label || "")}</a>
          <span class="kv-sub mono-cell">${esc(ref.code || "")}</span>`;
      }
      if (f.type === "url") return `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(A.truncate(v, 60))}</a>`;
      if (f.type === "bool") return v ? t("common.yes") : t("common.no");
      if (f.type === "textarea") return esc(v).replace(/\n/g, "<br>");
      return esc(v);
    }

    function overviewTab() {
      const nodes = [];
      const wrap = document.createElement("div");
      wrap.className = "stack";
      const fields = A.fieldsOf(entity).filter(f => f.group !== "system");
      const groups = {};
      fields.forEach(f => {
        const v = rec[f.key];
        if (v === null || v === undefined || v === "") return;
        (groups[f.group] = groups[f.group] || []).push(f);
      });
      GROUP_ORDER.filter(g => groups[g]).forEach(g => {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `<div class="card-head"><h3>${esc(t("form.groups." + g))}</h3>
            <span class="badge gray">${groups[g].length}</span></div>
          <dl class="dl">${groups[g].map(f =>
            `<dt>${esc(A.fieldLabelSafe(f))}</dt><dd>${fieldValue(f)}</dd>`).join("")}</dl>`;
        wrap.appendChild(card);
      });
      if (portrait) {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `<div class="card-head"><h3>${A.t("ui.portrait")}</h3></div>
          <div class="flex" style="gap:14px;align-items:flex-start">
            <img src="${esc(portrait)}" alt="${esc(rec.image_alt || title)}"
                 style="width:168px;height:168px;object-fit:cover;border-radius:14px;border:1px solid var(--border)">
            ${rec.image_alt ? `<div class="small muted">${esc(rec.image_alt)}</div>` : ""}
          </div>`;
        wrap.appendChild(card);
      }
      if ((rec.tags || []).length) {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `<div class="card-head"><h3>${t("rec.specializations")}</h3></div>
          <div class="pill-list">${rec.tags.map(tg =>
            `<span class="chip">${esc(A.state.lang === "ar" ? (tg.label_ar || tg.label_en) : tg.label_en)}</span>`).join("")}</div>`;
        wrap.appendChild(card);
      }
      if ((rec.relationships || []).length && ["person", "institution", "place", "event"].includes(entity)) {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = egoNetwork(rec);
        if (card.innerHTML.trim()) wrap.appendChild(card);
      }
      const sys = document.createElement("div");
      sys.className = "card";
      sys.innerHTML = `<div class="card-head"><h3>${t("rec.system")}</h3></div>
        <dl class="dl">
          <dt>${t("common.created")}</dt><dd>${esc(A.fmtDate(rec.created_at, true))} · ${esc(rec.created_by || "—")}</dd>
          <dt>${t("common.updated")}</dt><dd>${esc(A.fmtDate(rec.updated_at, true))} · ${esc(rec.updated_by || "—")}</dd>
          <dt>${t("common.code")}</dt><dd class="mono-cell">${esc(rec.code)}</dd>
          <dt>v</dt><dd>${esc(rec.version)}</dd>
        </dl>`;
      wrap.appendChild(sys);
      nodes.push(wrap);
      return nodes;
    }

    function derivedTab() {
      const list = A.registry(entity).filter(f => f.kind === "derived");
      const card = document.createElement("div");
      card.className = "card";
      const filled = list.filter(f => hasDV(rec, f.key));
      card.innerHTML = `<div class="card-head"><h3>Ƒ ${A.t("ui.fieldsDerivedFromRelatedTables")}</h3>
          <span class="badge gray">${filled.length} / ${list.length}</span></div>
        <div class="notice small">${A.t("ui.theseValuesAreNeverStoredOrEditedTheyA")}</div>
        <dl class="dl">${list.map(f => {
          const v = dv(rec, f.key);
          let out = `<span class="empty-val">—</span>`;
          if (f.key === "completeness" && v !== null && v !== undefined) {
            out = `<div class="flex" style="gap:8px;max-width:240px">
              <div class="progress ${v >= 75 ? "good" : v >= 40 ? "fair" : "poor"}" style="flex:1">
                <span style="width:${Math.min(100, v)}%"></span></div><b>${v}%</b></div>`;
          } else if (v !== null && v !== undefined && v !== "") {
            out = esc(Array.isArray(v) ? v.join(" · ") : v);
          }
          return `<dt>ƒ ${esc(A.regLabel(f))}</dt><dd>${out}
            <div class="kv-sub">${esc(f.help_ar && A.state.lang === "ar" ? f.help_ar : (f.help_en || f.expr || ""))}</div></dd>`;
        }).join("")}</dl>`;
      return [card];
    }

    /* ---- the position tab: CRCE -----------------------------------------
       One standard, one order of questions, for every kind of record: what this
       is, where the point is, in which reference system, in which direction and
       from what, how sure we are, what it relates to, and what must be said
       before the point is believed. Nothing here is filled in to look complete. */
    function positionTab() {
      const card = document.createElement("div");
      card.className = "card crce-card";
      card.innerHTML = `<div class="card-head"><h3>◉ ${esc(t("crce.title"))}</h3>
        <span class="muted small">${esc(t("crce.subtitle"))}</span></div>
        <div class="crce-body"><div class="ap-loading">${esc(t("common.loading"))}</div></div>`;
      setTimeout(async () => {
        const host = card.querySelector(".crce-body");
        try {
          /* the geometry travels with the standard, so it is fetched once and then
             every mark on every screen is drawn from the same description */
          await A.crce.standard();
          const d = await A.api.get(`/api/crce/dossier/${entity}/${id}`);
          host.innerHTML = A.crce.panel(d);
          const mark = host.querySelector("[data-crce-mark]");
          if (mark) A.crce.attach(mark, d, { size: 96 });
        } catch (err) {
          host.innerHTML = `<div class="notice err">${esc(err.message)}</div>`;
        }
      }, 0);
      return [card];
    }

    function positionsTab() {
      const card = document.createElement("div");
      card.className = "card";
      const rows = rec.positions || [];
      card.innerHTML = `<div class="card-head"><h3>${t("rec.positions")}</h3>
        <a class="btn sm" href="#/entity/${entity}/${id}/edit">${icon("edit")} ${t("common.edit")}</a></div>
        ${rows.length ? `<div class="table-wrap"><table class="data compact"><thead><tr>
          <th>${A.t("ui.position")}</th>
          <th>${A.t("ui.institution")}</th>
          <th>${A.t("ui.from")}</th>
          <th>${A.t("ui.to")}</th>
          <th>${t("common.notes")}</th></tr></thead><tbody>
          ${rows.map(p => `<tr>
            <td>${esc(A.state.lang === "ar" ? (p.title_ar || p.title_en) : (p.title_en || p.title_ar))}
              ${p.is_current ? A.badge(t("common.yes"), "green") : ""}</td>
            <td>${p.institution_id
              ? `<a href="#/entity/institution/${p.institution_id}">${esc(A.state.lang === "ar"
                ? (p.institution_ar || p.institution_en || "") : (p.institution_en || ""))}</a>`
              : "—"}</td>
            <td>${esc(p.start_date || "—")}</td><td>${esc(p.end_date || "—")}</td>
            <td>${esc(p.notes || "—")}</td></tr>`).join("")}
          </tbody></table></div>` : `<div class="empty">${t("list.noRecords")}</div>`}`;
      return [card];
    }

    function relationsTab() {
      const card = document.createElement("div");
      card.className = "card";
      const rows = entity === "event" ? (rec.relationships || []) : relRows;
      const isEvent = entity === "event";
      const participants = isEvent
        ? rows.filter(r => r.other_type === "person" || r.other_type === "institution")
        : [];
      const title = isEvent ? t("rec.participants") : t("rec.relationships");
      const addLabel = isEvent ? t("rec.addParticipant") : t("rec.addRelationship");
      card.innerHTML = `<div class="card-head"><h3>${esc(title)}</h3>
        <button class="btn sm primary" id="addRel">${icon("plus")} ${esc(addLabel)}</button></div>
        ${isEvent ? `<div class="notice small" style="margin-bottom:10px">${esc(t("rec.participantsHint"))}</div>` : ""}
        ${isEvent && participants.length ? `<div class="pill-list" style="margin-bottom:12px">
          ${participants.map(r => `<a class="chip" href="#/entity/${r.other_type}/${r.other_id}">
            <span class="badge gray">${esc(A.label(r.other_type))}</span>
            ${esc(A.truncate(r.other_name || "", 40))}
            <span class="muted small">${esc(A.state.lang === "ar" ? (r.type_ar || r.type_en) : (r.type_en || ""))}</span>
          </a>`).join("")}
        </div>` : ""}
        ${rows.length ? `<div class="table-wrap"><table class="data compact"><thead><tr>
          <th>${t("log.entity")}</th><th>${A.t("ui.type")}</th>
          <th>${A.t("ui.from")}</th><th>${A.t("ui.to")}</th>
          <th>${t("common.source")}</th></tr></thead><tbody>
          ${rows.map(r => `<tr>
            <td><a href="#/entity/${r.other_type}/${r.other_id}">${esc(A.truncate(r.other_name || "", 48))}</a>
              <span class="kv-sub">${esc(A.label(r.other_type))}</span></td>
            <td>${esc(A.state.lang === "ar" ? (r.type_ar || r.type_en) : (r.type_en || ""))}
              ${r.outgoing ? "→" : "←"}</td>
            <td>${esc(r.start_date || "—")}</td><td>${esc(r.end_date || "—")}</td>
            <td class="small">${esc(r.source_title || (r.source_id ? "#" + r.source_id : "—"))}</td></tr>`).join("")}
          </tbody></table></div>` : `<div class="empty">${esc(isEvent ? t("rec.noParticipants") : t("rec.noRelationships"))}</div>`}`;
      setTimeout(() => {
        const b = card.querySelector("#addRel");
        if (b) b.onclick = () => addRelationship(entity, rec);
      }, 0);
      return [card];
    }

    function eventsTab() {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `<div class="card-head"><h3>${esc(t("inspect.tab.events"))}</h3>
        <button class="btn sm primary" id="addEvent">${icon("plus")} ${esc(t("rec.addEvent"))}</button></div>
        <div data-rec-events>
          <div class="skeleton" style="width:70%"></div>
          <div class="skeleton" style="width:92%;margin-top:8px"></div>
        </div>`;
      setTimeout(() => {
        const b = card.querySelector("#addEvent");
        if (b) b.onclick = () => addEvent(entity, rec);
        loadRecordEvents(card.querySelector("[data-rec-events]"), eventIds);
      }, 0);
      return [card];
    }

    async function loadRecordEvents(host, ids) {
      if (!host) return;
      if (!ids.length) {
        host.innerHTML = `<div class="empty">${esc(t("rec.noEvents"))}</div>`;
        return;
      }
      try {
        const full = await Promise.all(ids.map(eid =>
          api.get(`/api/event/${eid}`).catch(() => null)));
        const events = full.filter(Boolean);
        if (!events.length) {
          host.innerHTML = `<div class="empty">${esc(t("rec.noEvents"))}</div>`;
          return;
        }
        host.innerHTML = `<div class="table-wrap"><table class="data compact"><thead><tr>
          <th>${esc(t("inspect.tab.events"))}</th>
          <th>${esc(A.t("ui.type"))}</th>
          <th>${esc(A.t("ui.from"))}</th>
          <th>${esc(A.t("ui.to"))}</th>
          <th>${esc(A.label("place"))}</th></tr></thead><tbody>
          ${events.map(ev => {
            const titleEv = A.dispTitle(ev, "event") || ev.code || `#${ev.id}`;
            const typeLab = (ev._labels || {}).event_type_id;
            const typeTxt = typeLab
              ? (A.state.lang === "ar" ? (typeLab.ar || typeLab.en) : (typeLab.en || typeLab.ar))
              : "";
            const placeRef = (ev._refs || {}).place_id;
            return `<tr>
              <td><a href="#/entity/event/${ev.id}">${esc(A.truncate(titleEv, 56))}</a>
                ${ev.code ? `<span class="kv-sub mono-cell">${esc(ev.code)}</span>` : ""}</td>
              <td>${esc(typeTxt || "—")}</td>
              <td>${esc(ev.start_date || "—")}</td>
              <td>${esc(ev.end_date || "—")}</td>
              <td>${ev.place_id
                ? `<a href="#/entity/place/${ev.place_id}">${esc((placeRef && placeRef.label) || "—")}</a>`
                : "—"}</td></tr>`;
          }).join("")}
          </tbody></table></div>`;
      } catch (err) {
        host.innerHTML = `<div class="notice err small">${esc(err.message || String(err))}</div>`;
      }
    }

    function citationsTab() {
      const card = document.createElement("div");
      card.className = "card";
      const rows = rec.citations || rec.evidence || [];
      const summary = rec.evidence_summary || {};
      card.innerHTML = `<div class="card-head"><h3>${t("rec.citations")}</h3>
        <button class="btn sm primary" id="addCite">${icon("plus")} ${t("rec.linkSource")}</button></div>
        ${rec._refs && rec._refs.primary_source_id ? `<div class="notice ok small" style="margin-bottom:10px">
          ${t("common.source")}: <a href="#/entity/source/${rec._refs.primary_source_id.id}">
          ${esc(rec._refs.primary_source_id.label)}</a> — <b>${A.t("ui.primary") || "primary"}</b></div>` : ""}
        ${summary.disputed ? `<div class="notice warn small" style="margin-bottom:10px">
          ${esc(A.state.lang === "ar"
            ? "هذا السجل متنازع عليه: يوجد دليل يناقض أحد ادعاءاته."
            : "This record is contested: at least one source contradicts a claim.")}</div>` : ""}
        <div id="citeBody">${A.evidence.list(rows, { empty: t("rec.noCitations") })}</div>`;
      setTimeout(() => {
        const b = card.querySelector("#addCite");
        if (b) b.onclick = () => A.evidence.addDialog({
          entityType: entity, entityId: id, onSaved: () => A.rerender()
        });
        A.evidence.bind(card, () => A.rerender());
      }, 0);
      return [card];
    }

    function filesTab() {
      const card = document.createElement("div");
      card.className = "card";
      const rows = rec.attachments || [];
      card.innerHTML = `<div class="card-head"><h3>${t("rec.attachments")}</h3>
        <label class="btn sm primary">${icon("upload")} ${t("rec.uploadFile")}
          <input type="file" id="attFile" style="display:none"></label></div>
        ${rows.length ? `<table class="data compact"><thead><tr><th>${t("common.name")}</th>
          <th>${A.t("ui.size")}</th>
          <th>${A.t("ui.kind")}</th>
          <th>${t("log.when")}</th><th></th></tr></thead><tbody>
          ${rows.map(a => `<tr><td>${icon("file")} ${esc(a.filename)}</td>
            <td>${fmtNum(Math.round((a.size_bytes || 0) / 1024))} KB</td>
            <td>${esc(a.kind || "—")}</td>
            <td class="small muted">${esc(A.ago(a.uploaded_at))}</td>
            <td class="nowrap">
              <a class="icon-btn" href="/api/attachments/${a.id}/download" title="${t("common.export")}">${icon("download")}</a>
              <button class="icon-btn" data-attdel="${a.id}">${icon("trash")}</button></td></tr>`).join("")}
          </tbody></table>` : `<div class="empty">${t("list.noRecords")}</div>`}`;
      setTimeout(() => {
        const inp = card.querySelector("#attFile");
        inp.onchange = async () => {
          if (!inp.files.length) return;
          const fd = new FormData();
          fd.append("file", inp.files[0]);
          fd.append("kind", "scan");
          try {
            await api.upload(`/api/${entity}/${id}/attachments`, fd);
            toast(t("common.saved"), "ok"); A.rerender();
          } catch (err) { toast(err.message, "err"); }
        };
        card.querySelectorAll("[data-attdel]").forEach(b => {
          b.onclick = async () => {
            await api.del(`/api/attachments/${b.dataset.attdel}`);
            toast(t("common.deleted"), "ok"); A.rerender();
          };
        });
      }, 0);
      return [card];
    }

    function historyTab() {
      const card = document.createElement("div");
      card.className = "card";
      const rows = rec.history || [];
      card.innerHTML = `<div class="card-head"><h3>${t("rec.history")}</h3></div>
        <div class="timeline">${rows.map(h => `
          <div class="item">
            <div class="when">${esc(A.fmtDate(h.changed_at, true))} · ${esc(h.actor || "—")}
              ${h.reviewed_by ? `· rev: ${esc(h.reviewed_by)}` : ""}
              <span class="mono-cell">${esc((h.tx_id || "").slice(0, 8))}</span></div>
            <div class="what">
              <b>${esc(h.action)}</b>
              ${h.field_label ? ` — ${esc(h.field_label)}` : (h.notes ? ` — ${esc(h.notes)}` : "")}
              ${h.old_value ? `<div class="small muted">${esc(t("rec.oldValue"))}: ${esc(A.truncate(h.old_value, 160))}</div>` : ""}
              ${h.new_value ? `<div class="small">${esc(t("rec.newValue"))}: ${esc(A.truncate(h.new_value, 160))}</div>` : ""}
              ${h.reason ? `<div class="small muted">↳ ${esc(h.reason)}</div>` : ""}
              ${h.source_title ? `<div class="small muted">${t("common.source")}: ${esc(h.source_title)}</div>` : ""}
            </div>
          </div>`).join("") || `<div class="empty">${t("list.noRecords")}</div>`}</div>`;
      return [card];
    }
  };

  async function deleteRec(entity, id) {
    const ok = await A.confirmDialog({
      title: t("rec.deleteTitle"), message: t("rec.deleteBody"), danger: true,
      confirmLabel: t("common.delete"),
      extra: `<div class="field" style="margin-top:10px"><label>${t("common.reason")}</label>
        <input id="delR2" placeholder="${esc(t("common.reasonPh"))}"></div>`
    });
    if (!ok) return;
    const reason = (document.getElementById("delR2") || {}).value || "";
    try {
      await api.del(`/api/${entity}/${id}?reason=${encodeURIComponent(reason)}`);
      toast(t("common.deleted"), "ok");
      location.hash = `#/entity/${entity}`;
    } catch (err) { toast(err.message, "err"); }
  }

  /* ------------------------------------------------------------- events --- */
  /**
   * Events are first-class records. From a person / institution / place, open
   * the full event form (not a mini-dialog), pre-linked to the host.
   */
  function addEvent(entity, rec) {
    if (!rec || !rec.id) return;
    const placeId = entity === "place"
      ? rec.id
      : (entity === "person" ? rec.birthplace_id : rec.place_id) || null;
    A.state.eventSeed = {
      host: (entity === "person" || entity === "institution")
        ? { entity_type: entity, entity_id: rec.id,
            label: A.dispTitle(rec, entity) || rec.code || "" }
        : null,
      place_id: placeId || null,
      place_label: entity === "place"
        ? (A.dispTitle(rec, "place") || rec.code || "")
        : ""
    };
    const behind = `#${String(location.hash || "").replace(/^#/, "")}`
      || `#/entity/${entity}/${rec.id}`;
    A.state.formReturnTo = behind;
    location.hash = "#/entity/event/new";
  }
  A.addEvent = addEvent;

  /* ------------------------------------------------------- relationships --- */
  async function addRelationship(entity, rec, onSaved) {
    const types = A.domainOptions("relationship_type");
    const entityTypes = A.domainOptions("entity_type");
    /* From an event, prefer linking people/organisations as participants. */
    const preferred = entity === "event"
      ? ["person", "institution", "place", "event"]
      : null;
    const typeOpts = entityTypes
      .filter(x => x.code !== "relationship" && x.code !== "source")
      .sort((a, b) => {
        if (!preferred) return 0;
        return preferred.indexOf(a.code) - preferred.indexOf(b.code);
      });
    const body = `
      <div class="grid c2">
        <div class="field"><label>${A.t("ui.otherEntityType")}</label>
          <select id="relEtype">${typeOpts
            .map(x => `<option value="${x.code}" ${preferred && x.code === preferred[0] ? "selected" : ""}>${esc(A.state.lang === "ar" ? x.label_ar : x.label_en)}</option>`).join("")}</select></div>
        <div class="field"><label>${A.t("ui.otherRecord")}</label>
          <div id="relTargetHost"></div></div>
      </div>
      <div class="grid c2">
        <div class="field"><label>${A.t("ui.relationshipType")}</label>
          <div id="relTypeHost"></div></div>
        <div class="field"><label>${t("common.source")}</label>
          <div id="relSourceHost"></div></div>
      </div>
      <div class="grid c2">
        <div class="field"><label>${A.t("ui.startDate")}</label><input id="relStart" placeholder="1948"></div>
        <div class="field"><label>${A.t("ui.endDate")}</label><input id="relEnd" placeholder="1975"></div>
      </div>
      <div class="field"><label>${A.t("ui.description")}</label>
        <textarea id="relDesc" rows="2"></textarea></div>
      <div class="field"><label>${t("common.reason")}</label><input id="relReason" placeholder="${esc(t("common.reasonPh"))}"></div>`;
    const m = A.modal({
      title: t("rec.addRelationship"), body, size: "wide",
      buttons: [
        { label: t("common.cancel") },
        { label: t("common.save"), cls: "primary", onClick: async (close, bodyEl) => {
            const target = targetCombo.getValue();
            if (!target) return toast(t("common.select"), "warn");
            try {
              const otherType = m.body.querySelector("#relEtype").value;
              const otherItem = targetCombo.getSelected ? targetCombo.getSelected() : null;
              const otherName = otherItem
                ? ((A.state.lang === "ar" && otherItem.label_ar)
                    ? otherItem.label_ar : (otherItem.label || otherItem.code || ""))
                : "";
              await api.post("/api/relationship", {
                entity1_type: entity, entity1_id: rec.id, entity1_name: rec._title,
                entity2_type: otherType, entity2_id: target,
                entity2_name: otherName || null,
                relationship_type_id: typeCombo.getValue(),
                source_id: sourceCombo.getValue() || null,
                start_date: bodyEl.querySelector("#relStart").value || null,
                end_date: bodyEl.querySelector("#relEnd").value || null,
                description: bodyEl.querySelector("#relDesc").value || null,
                record_status_id: (A.domainOptions("record_status").find(s => s.code === "draft") || {}).id,
                _reason: bodyEl.querySelector("#relReason").value || "relationship added"
              });
              toast(t("common.saved"), "ok"); close();
              if (typeof onSaved === "function") onSaved();
              else A.rerender();
            } catch (err) { toast(err.message, "err"); }
          } }
      ]
    });
    const etypeSel = m.body.querySelector("#relEtype");
    let targetCombo = A.combobox({ entity: etypeSel.value, allowCreate: true, limit: 30 });
    const mountTarget = () => {
      m.body.querySelector("#relTargetHost").innerHTML = "";
      targetCombo = A.combobox({ entity: etypeSel.value, allowCreate: true, limit: 30 });
      m.body.querySelector("#relTargetHost").appendChild(targetCombo);
    };
    mountTarget();
    etypeSel.onchange = mountTarget;
    const typeCombo = A.combobox({ domain: "relationship_type" });
    m.body.querySelector("#relTypeHost").appendChild(typeCombo);
    const sourceCombo = A.combobox({ entity: "source", allowCreate: true, limit: 30 });
    m.body.querySelector("#relSourceHost").appendChild(sourceCombo);
  }
  A.addRelationship = addRelationship;

  /* ------------------------------------------------------------- source --- */
  async function linkSource(entity, id, cb) {
    const body = `
      <div class="field"><label>${t("common.source")}</label><div id="srcHost"></div></div>
      <div class="field"><label>${t("common.notes")}</label><input id="srcNote"></div>
      <div class="notice small">${A.t("ui.searchForTheSourceOrCreateANewOneStrai")}</div>`;
    const m = A.modal({
      title: t("rec.linkSource"), body, size: "slim",
      buttons: [
        { label: t("common.cancel") },
        { label: t("common.save"), cls: "primary", onClick: async (close, b) => {
            const sid = combo.getValue();
            if (!sid) return toast(t("common.select"), "warn");
            await api.post(`/api/${entity}/${id}/citations`,
              { source_id: sid, note: b.querySelector("#srcNote").value || null });
            toast(t("common.saved"), "ok"); close(); cb && cb();
          } }
      ]
    });
    const combo = A.combobox({ entity: "source", allowCreate: true, limit: 30 });
    m.body.querySelector("#srcHost").appendChild(combo);
  }
  A.linkSource = linkSource;

  /* ============================================================== form === */
  async function buildForm(entity, rec) {
    const spec = A.entitySpec(entity) || {};
    const fields = A.fieldsOf(entity);
    const isNew = !rec;
    const form = document.createElement("form");
    form.className = "record-form";
    form.noValidate = true;
    /* the editor is not a submitting form — Enter/Ctrl+S are handled by the
       action bar; anything else must not reload the page and drop the draft */
    form.addEventListener("submit", (e) => e.preventDefault());
    form.dataset.entity = entity;

    /* Dirty means "the collected values differ from what the record was", not
       "a change event fired".  The old boolean was set by *any* input event —
       including typing a search string inside a combobox, or a combobox merely
       prefilling its label — so a form nobody had touched offered to discard
       changes.  The baseline is captured once the prefills have settled. */
    let dirty = false;
    let baseline = null;
    const snap = () => JSON.stringify(typeof form._collect === "function" ? form._collect() : {});
    /* The marker lives in the action bar, and in dialog mode that bar is *moved* into
       the dialog footer — so it must be looked up once it exists, not assumed to be a
       descendant of the form. */
    let dirtyEl = null;
    function dirtyNode() {
      if (dirtyEl && dirtyEl.isConnected) return dirtyEl;
      const scope = form.closest(".modal") || document;
      dirtyEl = scope.querySelector(".formbar [data-dirty]");
      return dirtyEl;
    }
    function paintDirty() {
      const d = dirtyNode();
      if (d) d.textContent = dirty ? (t("form.unsaved") || "●") : "";
    }
    function refreshDirty() {
      if (baseline === null) return dirty;          // still settling: assume clean
      dirty = snap() !== baseline;
      paintDirty();
      return dirty;
    }
    function markDirty() { requestAnimationFrame(refreshDirty); }
    function captureBaseline() { baseline = snap(); dirty = false; paintDirty(); }
    form.addEventListener("input", markDirty);
    form.addEventListener("change", markDirty);

    let nextCode = "";
    if (isNew) {
      try { nextCode = (await api.get(`/api/${entity}/next-code`)).code; } catch (e) { nextCode = ""; }
    }

    const groups = {};
    fields.filter(f => !f.system).forEach(f => { (groups[f.group] = groups[f.group] || []).push(f); });

    GROUP_ORDER.filter(g => groups[g]).forEach(g => {
      const fs = document.createElement("fieldset");
      fs.className = "field-group";
      fs.innerHTML = `<legend>${esc(t("form.groups." + g) || g)}</legend>
        <div class="form-grid"></div>`;
      const grid = fs.querySelector(".form-grid");
      groups[g].forEach(f => {
        /* longitude is the other half of the coordinate control, not its own box */
        if (entity === "place" && f.key === "longitude") return;
        grid.appendChild(fieldEl(f));
      });
      form.appendChild(fs);
    });

    if ((spec.tags || []).length) {
      const fs = document.createElement("fieldset");
      fs.className = "field-group";
      fs.innerHTML = `<legend>${t("rec.specializations")}</legend>
        <div class="flex wrap" data-tags></div>
        <div class="flex" style="margin-top:8px">
          <input data-taginput placeholder="${A.t("ui.addATagAndPressEnter")}" style="max-width:320px">
          <button type="button" class="btn sm" data-tagadd>${t("common.add")}</button>
        </div>`;
      form.appendChild(fs);
      initTags(fs);
    }

    /* Events first: participants (who was there) before optional coordinate tooling. */
    if (entity === "event") initParticipants();

    const LOC_FK = { person: "birthplace_id", institution: "place_id", event: "place_id" };
    if (LOC_FK[entity]) initPreciseLocation(LOC_FK[entity]);

    if (spec.has_positions) {
      const fs = document.createElement("fieldset");
      fs.className = "field-group";
      fs.innerHTML = `<legend>${t("rec.positions")}</legend>
        <div class="pos-editor" data-posbox></div>
        <button type="button" class="btn sm" data-addpos>${icon("plus")} ${t("rec.addPosition")}</button>`;
      form.appendChild(fs);
      initPositions(fs, (rec && rec.positions) || []);
    }

    /* derived (read-only) preview panel — computed from related tables */
    if (rec) {
      const derived = A.registry(entity).filter(f => f.kind === "derived" && hasDV(rec, f.key));
      if (derived.length) {
        const fs = document.createElement("fieldset");
        fs.className = "field-group";
        fs.innerHTML = `<legend>Ƒ ${A.t("ui.computedFromRelatedTablesReadOnly")}</legend>
          <div class="statgrid">${derived.map(f => {
            const v = dv(rec, f.key);
            return `<div class="statcard"><b>${f.type === "int" ? fmtNum(v) : esc(A.truncate(String(v), 22))}</b>
              <span>${esc(A.regLabel(f))}</span></div>`;
          }).join("")}</div>`;
        form.appendChild(fs);
      }
    }

    const meta = document.createElement("fieldset");
    meta.className = "field-group";
    meta.innerHTML = `<legend>${t("log.actor")}</legend>
      <div class="form-grid">
        <div class="field"><label>${t("common.reason")}</label>
          <input data-reason placeholder="${esc(t("common.reasonPh"))}"></div>
        <div class="field"><label>${t("common.source")}</label>
          <div data-source-host></div></div>
      </div>`;
    form.appendChild(meta);
    const sourceCombo = A.combobox({ entity: "source", allowCreate: true, limit: 30,
      placeholder: t("common.source"), size: "sm" });
    meta.querySelector("[data-source-host]").appendChild(sourceCombo);

    /* -------------------------------------------------------- fieldEl --- */
    function fieldEl(f) {
      const wrap = document.createElement("div");
      wrap.className = "field" + (f.type === "textarea" ? " span2" : "");
      wrap.dataset.field = f.key;
      let val = rec ? rec[f.key] : (f.key === "code" ? nextCode : "");
      /* a brand-new record starts on the workflow default (draft) instead of
         showing an empty required dropdown the server would have to fix up */
      if (!rec && !val && f.key === "record_status_id") {
        const opt = (A.domainOptions(f.domain) || []).find(o => /^draft$/i.test(o.code || ""));
        if (opt) val = opt.id;
      }
      /* event opened from a place / person / institution — carry the place link */
      if (!rec && !val && entity === "event" && f.key === "place_id"
          && A.state.eventSeed && A.state.eventSeed.place_id) {
        val = A.state.eventSeed.place_id;
      }
      const help = A.state.lang === "ar" ? f.help_ar : f.help_en;
      const helpHtml = help ? `<div class="hint">${esc(help)}</div>` : "";
      wrap.innerHTML = `<label>${esc(A.fieldLabelSafe(f))}${f.required ? ' <span class="req">*</span>' : ""}
        ${f.unique ? `<span class="muted small">· ${A.t("ui.unique")}</span>` : ""}</label>`;

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.dataset.k = f.key;
      hidden.value = val === null || val === undefined ? "" : val;

      const hierarchicalPlace = entity === "place"
        && (f.key === "country_id" || f.key === "governorate_id" || f.key === "district_id");
      if (f.type === "select" && !A.isLargeList(f) && !hierarchicalPlace) {
        const sel = document.createElement("select");
        sel.dataset.k = f.key;
        const storeCode = f.store === "code";
        let opts = A.domainOptions(f.domain) || [];
        /* relationship endpoints cannot point at a relationship or a source */
        if (entity === "relationship" && (f.key === "entity1_type" || f.key === "entity2_type")) {
          opts = opts.filter(o => o.code !== "relationship" && o.code !== "source");
        }
        const selected = storeCode
          ? String(val || "")
          : String(val === null || val === undefined ? "" : val);
        sel.innerHTML = `<option value="">${esc(t("common.select"))}</option>` +
          opts.map(o => {
            const ov = storeCode ? o.code : o.id;
            const match = storeCode
              ? selected === String(o.code)
              : selected === String(o.id);
            return `<option value="${esc(String(ov))}" ${match ? "selected" : ""}>
            ${esc(A.state.lang === "ar" ? o.label_ar : o.label_en)}</option>`;
          }).join("");
        if (entity === "place" && f.key === "country_id") {
          sel.addEventListener("change", () => {
            cascadeAdminUnits({ from: "country" });
            markDirty();
          });
        }
        wrap.appendChild(sel);
      } else if (f.type === "select" || f.type === "fk") {
        /* Relationship entity1/entity2: the FK target follows entity*_type. */
        const relSide = entity === "relationship" && (f.key === "entity1_id" || f.key === "entity2_id")
          ? (f.key === "entity1_id" ? "1" : "2")
          : null;
        const typeKey = relSide ? `entity${relSide}_type` : null;
        const nameKey = relSide ? `entity${relSide}_name` : null;
        const typeVal = typeKey && form
          ? ((form.querySelector(`[data-k="${typeKey}"]`) || {}).value || (rec && rec[typeKey]) || "person")
          : null;
        const fkEntity = relSide
          ? (typeVal || "person")
          : (f.type === "fk" ? f.ref : undefined);
        /* any field pointing at another table → searchable dropdown + inline create */
        let placeFilters = null;
        if (entity === "place" && f.key === "parent_place_id") {
          placeFilters = { country_id: currentCountryId() };
        } else if (entity === "place" && f.key === "governorate_id") {
          const cid = currentCountryId();
          placeFilters = cid ? { parent_id: cid } : { require_parent: true };
        } else if (entity === "place" && f.key === "district_id") {
          const gid = currentGovernorateId();
          placeFilters = gid ? { parent_id: gid } : { require_parent: true };
        }
        const vocabCreate = entity === "place"
          && (f.key === "country_id" || f.key === "governorate_id" || f.key === "district_id");
        const seedLabel = (!rec && entity === "event" && f.key === "place_id"
          && A.state.eventSeed && Number(A.state.eventSeed.place_id) === Number(val))
          ? (A.state.eventSeed.place_label || "") : "";
        const combo = A.combobox({
          entity: f.type === "fk" ? fkEntity : undefined,
          domain: f.type === "select" ? f.domain : undefined,
          allowCreate: f.type === "fk" || vocabCreate,
          value: val ? Number(val) : null,
          valueLabel: seedLabel || undefined,
          size: "sm",
          filters: placeFilters || undefined,
          placeholder: `${t("common.search")} — ${A.fieldLabelSafe(f)}`,
          onSelect: (it) => {
            hidden.value = it ? it.id : "";
            if ((f.key === "birthplace_id" || f.key === "place_id") && form._onPlacePick) {
              form._onPlacePick(it);
            }
            if (entity === "place" && f.key === "country_id") {
              cascadeAdminUnits({ from: "country" });
            } else if (entity === "place" && f.key === "governorate_id") {
              applyGovernorateSelection(it);
            } else if (entity === "place" && f.key === "district_id") {
              applyDistrictSelection(it);
            }
            if (nameKey && it) {
              const nameEl = form.querySelector(`[data-k="${nameKey}"]`);
              if (nameEl) {
                nameEl.value = (A.state.lang === "ar" && it.label_ar) ? it.label_ar
                  : (it.label || it.label_ar || it.code || "");
              }
            }
            markDirty();
          },
          onClear: () => {
            hidden.value = "";
            if (nameKey) {
              const nameEl = form.querySelector(`[data-k="${nameKey}"]`);
              if (nameEl) nameEl.value = "";
            }
            if (entity === "place" && f.key === "country_id") {
              cascadeAdminUnits({ from: "country" });
            } else if (entity === "place" && f.key === "governorate_id") {
              cascadeAdminUnits({ from: "governorate" });
            }
            markDirty();
          }
        });
        if (relSide) {
          wrap.dataset.relSide = relSide;
          wrap.dataset.fkHost = "1";
        }
        if (entity === "place" && f.key === "parent_place_id") {
          form._parentPlaceCombo = combo;
        }
        if (entity === "place" && f.key === "country_id") {
          form._countryCombo = combo;
        }
        if (entity === "place" && f.key === "governorate_id") {
          form._governorateCombo = combo;
        }
        if (entity === "place" && f.key === "district_id") {
          form._districtCombo = combo;
        }
        wrap.appendChild(combo);
        wrap.appendChild(hidden);
      } else if (f.type === "textarea") {
        const ta = document.createElement("textarea");
        ta.dataset.k = f.key;
        ta.rows = 3;
        ta.value = val || "";
        wrap.appendChild(ta);
      } else if (f.type === "bool") {
        const l = document.createElement("label");
        l.className = "check";
        l.innerHTML = `<input type="checkbox" data-k="${f.key}" ${val ? "checked" : ""}> ${t("common.yes")}`;
        wrap.appendChild(l);
      } else if (f.type === "url" && f.key === "image_url") {
        wrap.appendChild(imageEditor(f, val, hidden));
        wrap.appendChild(hidden);
      } else if (entity === "place" && f.key === "latitude") {
        wrap.classList.add("span2");
        const lon0 = rec && rec.longitude != null ? rec.longitude : null;
        const lat0 = val === "" || val == null ? null : Number(val);
        const lonH = document.createElement("input");
        lonH.type = "hidden";
        lonH.dataset.k = "longitude";
        lonH.value = lon0 == null ? "" : lon0;
        hidden.value = lat0 == null ? "" : lat0;
        const ctl = A.coordControl({
          lat: lat0, lon: lon0,
          onChange: (p) => {
            hidden.value = p ? String(p.lat) : "";
            lonH.value = p ? String(p.lon) : "";
            stampGeo(p);
            if (p) fillPlaceFromPoint(p);
            markDirty();
          }
        });
        wrap.appendChild(ctl.el);
        wrap.appendChild(hidden);
        wrap.appendChild(lonH);
        form._coord = ctl;
      } else if (f.type === "int" || f.type === "float") {
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = f.type === "float" ? "any" : "1";
        inp.dataset.k = f.key;
        inp.value = val === null || val === undefined ? "" : val;
        wrap.appendChild(inp);
      } else if (f.type === "url") {
        const inp = document.createElement("input");
        inp.type = "text";
        inp.dataset.k = f.key;
        inp.value = val || "";
        inp.placeholder = "https://";
        wrap.appendChild(inp);
      } else if (f.type === "date") {
        /* date (and time, where it matters) — year → month → day → minute, and
           the registry keeps exactly the precision the researcher entered */
        const control = A.dateControl({
          field: f, value: val || "", label: A.fieldLabelSafe(f),
          onChange: (v) => { hidden.value = v || ""; markDirty(); }
        });
        wrap.appendChild(control);
        wrap.appendChild(hidden);
      } else {
        const inp = document.createElement("input");
        inp.type = "text";
        inp.dataset.k = f.key;
        inp.value = val || "";
        if (f.max_len) inp.maxLength = f.max_len;
        wrap.appendChild(inp);
      }
      if (helpHtml) wrap.insertAdjacentHTML("beforeend", helpHtml);
      if (f.read_only) {
        wrap.querySelectorAll("[data-k], select, textarea, input").forEach(el => { el.disabled = true; });
      }
      return wrap;
    }

    /* image field: URL + upload + alt text */
    function imageEditor(f, val, hidden) {
      const box = document.createElement("div");
      box.className = "flex wrap";
      box.style.gap = "8px";
      const url = document.createElement("input");
      url.type = "text";
      url.placeholder = "https://… /api/media/…";
      url.value = val || "";
      url.style.flex = "1";
      url.oninput = () => { hidden.value = url.value; paint(); };
      const alt = document.createElement("input");
      alt.type = "text";
      alt.placeholder = A.t("ui.imageAltText");
      alt.value = rec && rec.image_alt ? rec.image_alt : "";
      alt.dataset.k = "image_alt";
      alt.style.flex = "1";
      const pick = document.createElement("label");
      pick.className = "btn sm";
      pick.innerHTML = `${icon("upload")} ${A.t("ui.upload")}
        <input type="file" accept="image/*" style="display:none">`;
      const prev = document.createElement("div");
      prev.style.cssText = "width:64px;height:64px;border-radius:12px;overflow:hidden;background:var(--ink-100);display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--ink-600)";
      function paint() {
        const v = url.value.trim();
        prev.innerHTML = v ? `<img src="${esc(v)}" alt="" style="width:100%;height:100%;object-fit:cover">`
          : esc(A.initials(rec ? rec._title : "?"));
      }
      pick.querySelector("input").onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append("file", file);
        try {
          const res = await api.upload("/api/media", fd);
          url.value = res.url;
          hidden.value = res.url;
          if (!alt.value) alt.value = file.name.replace(/\.[^.]+$/, "");
          paint(); markDirty();
          toast(t("common.saved"), "ok");
        } catch (err) { toast(err.message, "err"); }
      };
      paint();
      box.append(prev, url, alt, pick);
      return box;
    }

    function initTags(fs) {
      const box = fs.querySelector("[data-tags]");
      let tags = (rec && rec.tags ? rec.tags.slice() : []);
      function paint() {
        box.innerHTML = tags.map((tg, i) =>
          `<span class="chip">${esc(A.state.lang === "ar" ? (tg.label_ar || tg.label_en) : tg.label_en)}
            <span class="x" data-i="${i}">×</span></span>`).join("");
        box.querySelectorAll(".x").forEach(x => {
          x.onclick = () => { tags.splice(Number(x.dataset.i), 1); paint(); };
        });
      }
      paint();
      fs.querySelector("[data-tagadd]").onclick = () => {
        const inp = fs.querySelector("[data-taginput]");
        const v = inp.value.trim();
        if (!v) return;
        tags.push({ label_en: v, domain: (spec.tags || ["keyword"])[0] });
        inp.value = ""; paint();
      };
      fs.querySelector("[data-taginput]").onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); fs.querySelector("[data-tagadd]").click(); }
      };
      form._tags = () => tags;
    }

    function initPositions(fs, positions) {
      const box = fs.querySelector("[data-posbox]");
      let rows = positions.map(p => ({ ...p }));
      function paint() {
        box.innerHTML = rows.map((p, i) => `
          <div class="pos-row" data-i="${i}">
            <div><label>${A.t("ui.titleAr")}</label>
              <input data-p="title_ar" value="${esc(p.title_ar || "")}"></div>
            <div><label>${A.t("ui.titleEn")}</label>
              <input data-p="title_en" value="${esc(p.title_en || "")}"></div>
            <div class="pos-inst"><label>${A.t("ui.institution")}</label>
              <div data-insthost="${i}"></div></div>
            <div><label>${A.t("ui.from")}</label>
              <input data-p="start_date" value="${esc(p.start_date || "")}" placeholder="1950"></div>
            <div><label>${A.t("ui.to")}</label>
              <input data-p="end_date" value="${esc(p.end_date || "")}" placeholder="1960"></div>
            <button type="button" class="icon-btn" data-pdel="${i}">${icon("x")}</button>
          </div>`).join("") || `<div class="muted small">${t("list.noRecords")}</div>`;
        box.querySelectorAll("[data-p]").forEach(inp => {
          inp.oninput = inp.onchange = () => {
            const i = Number(inp.closest("[data-i]").dataset.i);
            rows[i][inp.dataset.p] = inp.value === "" ? null : inp.value;
            if (inp.dataset.p === "end_date") rows[i].is_current = !inp.value;
          };
        });
        box.querySelectorAll("[data-pdel]").forEach(b => {
          b.onclick = () => { rows.splice(Number(b.dataset.pdel), 1); paint(); };
        });
        box.querySelectorAll("[data-insthost]").forEach(host => {
          const i = Number(host.dataset.insthost);
          const combo = A.combobox({
            entity: "institution", allowCreate: true, size: "sm", limit: 30,
            value: rows[i].institution_id || null,
            placeholder: A.t("ui.findAnInstitution"),
            onSelect: (it) => { rows[i].institution_id = it ? it.id : null; }
          });
          host.appendChild(combo);
        });
        hydrateIcons(box);
      }
      paint();
      fs.querySelector("[data-addpos]").onclick = () => {
        rows.push({ sort_order: (rows.length + 1) * 10 });
        paint();
      };
      form._positions = () => rows;
    }

    function lookupId(domain, code) {
      const opt = (A.domainOptions(domain) || []).find(o => o.code === code);
      return opt ? String(opt.id) : "";
    }
    function currentCountryId() {
      const el = form.querySelector('[data-k="country_id"]');
      const v = el && el.value;
      return v ? Number(v) : null;
    }
    function currentGovernorateId() {
      const el = form.querySelector('[data-k="governorate_id"]');
      const v = el && el.value;
      return v ? Number(v) : null;
    }
    function lookupLabel(opt) {
      if (!opt) return "";
      return A.state.lang === "ar"
        ? (opt.label_ar || opt.label_en || opt.label || "")
        : (opt.label_en || opt.label_ar || opt.label || "");
    }
    function setLookupField(key, id, label, { autofill } = {}) {
      const hidden = form.querySelector(`[data-k="${key}"]`);
      if (!hidden) return;
      if (autofill) {
        const empty = !String(hidden.value || "").trim();
        const wasAuto = hidden.dataset.autofill === "1";
        if (!empty && !wasAuto && id != null) return false;
      }
      hidden.value = id != null && id !== "" ? String(id) : "";
      if (autofill) {
        if (id) hidden.dataset.autofill = "1";
        else delete hidden.dataset.autofill;
      }
      const combo = form[`_${key.replace(/_id$/, "")}Combo`]
        || (key === "country_id" ? form._countryCombo
          : key === "governorate_id" ? form._governorateCombo
          : key === "district_id" ? form._districtCombo : null);
      if (combo && combo.setValue) {
        if (id) combo.setValue(Number(id), label || "");
        else {
          const clearBtn = combo.querySelector(".combo-clear");
          if (clearBtn && !clearBtn.hidden) clearBtn.click();
          else {
            const input = combo.querySelector("input");
            if (input) input.value = "";
          }
        }
      } else if (hidden.tagName === "SELECT") {
        hidden.value = id != null && id !== "" ? String(id) : "";
      }
      return true;
    }
    function clearLookupIfFilteredOut(key, parentId, domain) {
      const hidden = form.querySelector(`[data-k="${key}"]`);
      if (!hidden || !hidden.value) return;
      const opt = (A.domainOptions(domain) || [])
        .find(o => String(o.id) === String(hidden.value));
      if (!opt || (parentId && Number(opt.parent_id) !== Number(parentId))) {
        setLookupField(key, null, "");
      }
    }
    function cascadeAdminUnits({ from } = {}) {
      const cid = currentCountryId();
      const gid = currentGovernorateId();
      if (form._parentPlaceCombo && form._parentPlaceCombo.setFilters) {
        form._parentPlaceCombo.setFilters({ country_id: cid || null });
      }
      if (form._governorateCombo && form._governorateCombo.setFilters) {
        form._governorateCombo.setFilters(
          cid ? { parent_id: cid, require_parent: false }
            : { parent_id: null, require_parent: true });
      }
      if (form._districtCombo && form._districtCombo.setFilters) {
        form._districtCombo.setFilters(
          gid ? { parent_id: gid, require_parent: false }
            : { parent_id: null, require_parent: true });
      }
      if (from === "country") {
        clearLookupIfFilteredOut("governorate_id", cid, "governorate");
        const nextGid = currentGovernorateId();
        clearLookupIfFilteredOut("district_id", nextGid, "district");
        if (!nextGid) setLookupField("district_id", null, "");
      } else if (from === "governorate") {
        clearLookupIfFilteredOut("district_id", gid, "district");
        if (!gid) setLookupField("district_id", null, "");
      }
    }
    function applyGovernorateSelection(it) {
      /* reverse: governorate → country */
      if (it && it.parent_id) {
        const country = A.lookupById(Number(it.parent_id))
          || (A.domainOptions("country") || []).find(o => Number(o.id) === Number(it.parent_id));
        if (country) {
          setLookupField("country_id", country.id, lookupLabel(country), { autofill: true });
        } else {
          setLookupField("country_id", it.parent_id, "", { autofill: true });
        }
      }
      cascadeAdminUnits({ from: "governorate" });
    }
    function applyDistrictSelection(it) {
      /* reverse: district → governorate → country */
      if (it && it.parent_id) {
        const gov = A.lookupById(Number(it.parent_id))
          || (A.domainOptions("governorate") || []).find(o => Number(o.id) === Number(it.parent_id));
        if (gov) {
          setLookupField("governorate_id", gov.id, lookupLabel(gov), { autofill: true });
          if (gov.parent_id) {
            const country = A.lookupById(Number(gov.parent_id))
              || (A.domainOptions("country") || []).find(o => Number(o.id) === Number(gov.parent_id));
            if (country) {
              setLookupField("country_id", country.id, lookupLabel(country), { autofill: true });
            } else {
              setLookupField("country_id", gov.parent_id, "", { autofill: true });
            }
          }
        } else {
          setLookupField("governorate_id", it.parent_id, "", { autofill: true });
        }
      }
      cascadeAdminUnits({ from: "governorate" });
    }
    function setAutofill(el, value) {
      if (!el || value == null || value === "") return false;
      const empty = !String(el.value || "").trim();
      const wasAuto = el.dataset.autofill === "1";
      if (!empty && !wasAuto) return false;
      el.value = value;
      el.dataset.autofill = "1";
      return true;
    }
    function matchGovernorate(countryId, name) {
      if (!countryId || !name) return null;
      const n = A.normText(name);
      return (A.domainOptions("governorate") || []).find(o =>
        Number(o.parent_id) === Number(countryId)
        && (A.normText(o.label_en) === n || A.normText(o.label_ar) === n
          || A.normText(o.label_en).includes(n) || A.normText(o.label_ar).includes(n)));
    }
    function stampGeo(point) {
      if (!point) return;
      const prec = form.querySelector('[data-k="geo_precision"]');
      const meth = form.querySelector('[data-k="geocoding_method"]');
      const src = form.querySelector('[data-k="geometry_source"]');
      const precId = lookupId("geo_precision", "exact");
      const methId = lookupId("geocoding_method", point.method) || lookupId("geocoding_method", "manual");
      if (prec && precId) prec.value = precId;
      if (meth && methId) meth.value = methId;
      if (src && !src.value) src.value = point.method === "map_pick" ? "map pick" : "typed coordinates";
    }
    async function fillPlaceFromPoint(point) {
      if (!point || entity !== "place") return;
      try {
        const info = await api.get(
          `/api/map/reverse?lat=${encodeURIComponent(point.lat)}&lon=${encodeURIComponent(point.lon)}`);
        const gaz = info.gazetteer || {};
        const near = (info.nearby_places || [])[0] || {};
        const countryId = (info.country_lookup && info.country_lookup.id)
          || lookupId("country", (info.country && info.country.iso_a2) || "");
        if (countryId) {
          const cl = info.country_lookup || {};
          const label = A.state.lang === "ar"
            ? (cl.label_ar || cl.label_en || info.country?.name_ar || "")
            : (cl.label_en || cl.label_ar || info.country?.name_en || "");
          setLookupField("country_id", countryId, label, { autofill: true });
          cascadeAdminUnits({ from: "country" });
        }
        setAutofill(form.querySelector('[data-k="name_en"]'), gaz.name_en || near.label_en || "");
        setAutofill(form.querySelector('[data-k="name_ar"]'), gaz.name_ar || near.label_ar || "");
        setAutofill(form.querySelector('[data-k="city"]'),
          gaz.name_en || near.city || near.label_en || "");
        const gov = matchGovernorate(countryId || currentCountryId(), gaz.region || near.region || "");
        if (gov) {
          setLookupField("governorate_id", gov.id, lookupLabel(gov), { autofill: true });
          cascadeAdminUnits({ from: "governorate" });
        }
      } catch (e) {
        /* coordinates still stand; reverse fill is best-effort */
      }
    }
    function initPreciseLocation(fkKey) {
      const fs = document.createElement("fieldset");
      fs.className = "field-group";
      fs.innerHTML = `<legend>${esc(t("geo.preciseTitle"))}</legend>
        <div data-loc-host></div>
        <div class="notice small" data-loc-note hidden></div>`;
      form.appendChild(fs);
      let userLoc = null;
      let linkedCoords = null;
      const note = fs.querySelector("[data-loc-note]");
      const ctl = A.coordControl({
        onChange: (p) => { userLoc = p; if (note) note.hidden = true; markDirty(); }
      });
      fs.querySelector("[data-loc-host]").appendChild(ctl.el);
      form._location = () => userLoc;
      form._coordEntity = ctl;
      form._locationGuard = () => {
        if (userLoc && Number.isFinite(Number(userLoc.lat)) && Number.isFinite(Number(userLoc.lon))) return "";
        const hid = form.querySelector(`[data-k="${fkKey}"]`);
        if (hid && hid.value && linkedCoords === false) return t("geo.preciseUnlocated");
        return "";
      };
      form._onPlacePick = async (it) => {
        linkedCoords = null;
        if (!it) { if (note) note.hidden = true; return; }
        try {
          const place = await api.get(`/api/place/${it.id}`);
          if (place.latitude != null && place.longitude != null) {
            linkedCoords = true;
            ctl.show(place.latitude, place.longitude);
            if (note) note.hidden = true;
          } else {
            linkedCoords = false;
            if (note) {
              note.hidden = false;
              note.textContent = t("geo.preciseUnlocated");
            }
          }
        } catch (e) {
          if (note) { note.hidden = false; note.textContent = e.message || ""; }
        }
      };
      if (rec && rec[fkKey]) {
        form._onPlacePick({ id: rec[fkKey] });
      }
    }
    function initParticipants() {
      const fs = document.createElement("fieldset");
      fs.className = "field-group";
      fs.innerHTML = `<legend>${esc(t("rec.participants"))}</legend>
        <p class="hint">${esc(t("rec.participantsHint"))}</p>
        <div data-partbox></div>
        <button type="button" class="btn sm" data-addpart>${esc(t("rec.addParticipant"))}</button>`;
      form.appendChild(fs);
      const box = fs.querySelector("[data-partbox]");
      let rows = ((rec && rec.relationships) || [])
        .filter(r => (r.other_type === "person" || r.other_type === "institution")
          && (r.type_code === "had_participant" || r.type_code === "participated_in"))
        .map(r => ({ entity_type: r.other_type, entity_id: r.other_id }));
      /* seed from a host person/institution when creating an event from their dossier */
      const seedHost = (!rec && A.state.eventSeed && A.state.eventSeed.host)
        ? A.state.eventSeed.host : null;
      if (seedHost && seedHost.entity_id
          && !rows.some(r => r.entity_type === seedHost.entity_type
            && Number(r.entity_id) === Number(seedHost.entity_id))) {
        rows.unshift({
          entity_type: seedHost.entity_type,
          entity_id: seedHost.entity_id,
          _label: seedHost.label || ""
        });
      }
      function paint() {
        box.innerHTML = rows.map((p, i) => `
          <div class="part-row" data-i="${i}">
            <div><label>${esc(t("log.entity"))}</label>
              <select data-ptype>
                <option value="person" ${p.entity_type === "person" ? "selected" : ""}>${esc(A.label("person"))}</option>
                <option value="institution" ${p.entity_type === "institution" ? "selected" : ""}>${esc(A.label("institution"))}</option>
              </select></div>
            <div><label>${esc(t("common.name"))}</label><div data-parthost="${i}"></div></div>
            <button type="button" class="icon-btn" data-pdel="${i}" aria-label="${esc(t("common.delete"))}">×</button>
          </div>`).join("") || `<div class="muted small">${esc(t("rec.noParticipants"))}</div>`;
        box.querySelectorAll("[data-ptype]").forEach(sel => {
          sel.onchange = () => {
            const i = Number(sel.closest("[data-i]").dataset.i);
            rows[i].entity_type = sel.value;
            rows[i].entity_id = null;
            paint();
            markDirty();
          };
        });
        box.querySelectorAll("[data-pdel]").forEach(b => {
          b.onclick = () => { rows.splice(Number(b.dataset.pdel), 1); paint(); markDirty(); };
        });
        box.querySelectorAll("[data-parthost]").forEach(host => {
          const i = Number(host.dataset.parthost);
          const combo = A.combobox({
            entity: rows[i].entity_type || "person",
            allowCreate: true, size: "sm", limit: 30,
            value: rows[i].entity_id || null,
            valueLabel: rows[i]._label || "",
            placeholder: t("common.search"),
            onSelect: (it) => { rows[i].entity_id = it ? it.id : null; markDirty(); },
            onClear: () => { rows[i].entity_id = null; markDirty(); }
          });
          host.appendChild(combo);
        });
      }
      paint();
      fs.querySelector("[data-addpart]").onclick = () => {
        rows.push({ entity_type: "person", entity_id: null });
        paint();
        markDirty();
      };
      form._participants = () => rows
        .filter(r => r.entity_id)
        .map(r => ({ entity_type: r.entity_type, entity_id: r.entity_id }));
    }

    form._collect = () => {
      const data = {};
      form.querySelectorAll("[data-k]").forEach(el => {
        const key = el.dataset.k;
        if (el.type === "checkbox") data[key] = el.checked;
        else if (el.value === "") data[key] = null;
        else data[key] = el.value;
      });
      /* keep legacy text columns in sync for reports that still read region/district */
      if (entity === "place") {
        const gov = (A.domainOptions("governorate") || [])
          .find(o => String(o.id) === String(data.governorate_id || ""));
        const dist = (A.domainOptions("district") || [])
          .find(o => String(o.id) === String(data.district_id || ""));
        if (gov) data.region = lookupLabel(gov);
        if (dist) data.district = lookupLabel(dist);
      }
      if (form._tags) data.tags = form._tags();
      if (form._positions) data.positions = form._positions();
      if (typeof form._location === "function") {
        const loc = form._location();
        if (loc) data._location = { lat: loc.lat, lon: loc.lon, method: loc.method };
      }
      if (typeof form._participants === "function") data._participants = form._participants();
      data._reason = (form.querySelector("[data-reason]") || {}).value || null;
      data._source_id = sourceCombo.getValue() || null;
      if (rec) data._version = rec.version;
      return data;
    };
    form._validate = () => {
      let ok = true;
      form.querySelectorAll(".field").forEach(f => {
        f.classList.remove("error");
        const e = f.querySelector(".err");
        if (e) e.remove();
      });
      fields.filter(f => f.required && !f.read_only).forEach(f => {
        if (f.key === "code") return;
        const box = form.querySelector(`.field[data-field="${f.key}"]`);
        if (!box) return;
        const el = box.querySelector("[data-k]");
        if (!el) return;
        const empty = el.type === "checkbox" ? false : !String(el.value || "").trim();
        if (empty) {
          ok = false;
          box.classList.add("error");
          const e = document.createElement("div");
          e.className = "err";
          e.textContent = t("common.required");
          box.appendChild(e);
        }
      });
      if (entity === "place") {
        const lat = form.querySelector('[data-k="latitude"]');
        const lon = form.querySelector('[data-k="longitude"]');
        const hasLat = lat && String(lat.value || "").trim() !== "";
        const hasLon = lon && String(lon.value || "").trim() !== "";
        if (hasLat !== hasLon) {
          ok = false;
          toast(t("geo.preciseNeedPair"), "warn");
        }
      }
      if (ok && typeof form._locationGuard === "function") {
        const msg = form._locationGuard();
        if (msg) { ok = false; toast(msg, "warn"); }
      }
      const first = form.querySelector(".field.error");
      if (first) {
        toast(t("common.required"), "warn");
        first.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      return ok;
    };
    form._isDirty = () => refreshDirty();
    form._resetDirty = () => captureBaseline();
    if (entity === "relationship") {
      wireRelationshipEntityFields(form);
      applyRelationshipPrefills(form);
    }
    /* prefills (a combobox resolving its label, a date control normalising a
       value) arrive after the fields are built: let them land, then set the mark */
    setTimeout(() => { if (baseline === null) captureBaseline(); }, 700);
    requestAnimationFrame(() => { if (baseline === null) captureBaseline(); });
    /* consume one-shot seed used when opening an event from a host record */
    if (entity === "event" && !rec && A.state.eventSeed) A.state.eventSeed = null;
    return form;
  }

  /** Prefill Entity Type / Entity from `#/entity/relationship/new?entity1_type=…&entity1_id=…`. */
  function applyRelationshipPrefills(form) {
    const p = (A.state.route && A.state.route.params) || {};
    ["1", "2"].forEach(side => {
      const typeKey = `entity${side}_type`;
      const idKey = `entity${side}_id`;
      const typeSel = form.querySelector(`[data-k="${typeKey}"]`);
      const nameEl = form.querySelector(`[data-k="entity${side}_name"]`);
      if (typeSel && p[typeKey]) {
        typeSel.value = p[typeKey];
        typeSel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (p[idKey]) {
        const id = Number(p[idKey]);
        setTimeout(async () => {
          const host = form.querySelector(`.field[data-field="entity${side}_id"]`);
          const combo = host && host.querySelector(".combo");
          const hidden = host && host.querySelector(`input[data-k="entity${side}_id"]`);
          if (hidden) hidden.value = String(id);
          if (combo && combo.setValue) {
            await combo.setValue(id);
            const it = combo.getSelected && combo.getSelected();
            if (nameEl && it) {
              nameEl.value = (A.state.lang === "ar" && it.label_ar)
                ? it.label_ar : (it.label || it.label_ar || it.code || "");
            }
          }
        }, 80);
      }
    });
  }

  /**
   * Relationship form: Entity Type N filters Entity N, and choosing a record
   * fills Entity Name N. Changing the type remounts the FK combobox against
   * that entity and clears a stale id/name pair.
   */
  function wireRelationshipEntityFields(form) {
    ["1", "2"].forEach(side => {
      const typeSel = form.querySelector(`[data-k="entity${side}_type"]`);
      const host = form.querySelector(`.field[data-field="entity${side}_id"]`);
      const nameEl = form.querySelector(`[data-k="entity${side}_name"]`);
      if (!typeSel || !host) return;

      const remount = (keepValue) => {
        const etype = typeSel.value || "person";
        const allowed = ["person", "institution", "place", "event"];
        const entityRef = allowed.includes(etype) ? etype : "person";
        const hidden = host.querySelector(`input[data-k="entity${side}_id"]`)
          || (() => {
            const h = document.createElement("input");
            h.type = "hidden"; h.dataset.k = `entity${side}_id`;
            return h;
          })();
        const prev = keepValue ? (hidden.value || null) : null;
        /* drop the old combobox; keep the label */
        Array.from(host.querySelectorAll(".combo, input[data-k]")).forEach(el => el.remove());
        hidden.value = prev || "";
        const combo = A.combobox({
          entity: entityRef,
          allowCreate: true,
          value: prev ? Number(prev) : null,
          size: "sm",
          placeholder: `${t("common.search")} — ${esc(A.label(entityRef) || entityRef)}`,
          onSelect: (it) => {
            hidden.value = it ? it.id : "";
            if (nameEl && it) {
              nameEl.value = (A.state.lang === "ar" && it.label_ar)
                ? it.label_ar : (it.label || it.label_ar || it.code || "");
            }
            markDirtySafe(form);
          },
          onClear: () => {
            hidden.value = "";
            if (nameEl) nameEl.value = "";
            markDirtySafe(form);
          }
        });
        host.appendChild(combo);
        host.appendChild(hidden);
      };

      typeSel.addEventListener("change", () => {
        remount(false);
        if (nameEl) nameEl.value = "";
        markDirtySafe(form);
      });
      /* Ensure the first paint targets the selected type (not the schema default). */
      remount(true);
    });
  }

  function markDirtySafe(form) {
    try {
      if (form && typeof form._isDirty === "function") {
        form.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } catch (e) { /* form may be mid-teardown */ }
  }

  /* ---------------------------------------------- dialog form chrome --- */
  /**
   * Wrap a record form for the popup surface: section rail + numbered groups.
   * Full-page edit keeps the plain form; only dialog mode gets this shell.
   */
  function wrapFormDialog(entity, form, { isNew, rec } = {}) {
    const shell = document.createElement("div");
    shell.className = "form-dialog-shell";
    const rail = document.createElement("aside");
    rail.className = "form-dialog-rail";
    const modeLabel = isNew ? (t("rec.new") || "New") : (t("rec.edit") || "Edit");
    rail.innerHTML = `<div class="form-dialog-rail-head">
        <span class="eyebrow">${esc(modeLabel)}</span>
        <strong>${esc(A.label(entity))}</strong>
        ${!isNew && rec ? `<span class="mono-cell small muted">${esc(rec.code || "")}</span>` : ""}
      </div>
      <nav class="form-dialog-nav" aria-label="${esc(t("form.sections") || "Sections")}"></nav>`;
    const nav = rail.querySelector(".form-dialog-nav");
    const main = document.createElement("div");
    main.className = "form-dialog-main";

    const sections = Array.from(form.querySelectorAll(":scope > .field-group"));
    sections.forEach((fs, i) => {
      const n = i + 1;
      const id = `fd-sec-${entity}-${n}`;
      fs.id = id;
      fs.classList.add("form-section");
      fs.dataset.n = String(n);
      const legend = fs.querySelector(":scope > legend");
      const label = (legend && legend.textContent.trim()) || String(n);
      if (legend) {
        legend.innerHTML = `<span class="form-section-n" aria-hidden="true">${n}</span>`
          + `<span class="form-section-label">${esc(label)}</span>`;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "form-dialog-nav-item" + (i === 0 ? " is-active" : "");
      btn.dataset.goto = id;
      btn.innerHTML = `<span class="n">${n}</span><span class="l">${esc(label)}</span>`;
      btn.onclick = () => {
        const target = form.querySelector(`#${CSS.escape(id)}`);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        nav.querySelectorAll(".form-dialog-nav-item").forEach(b =>
          b.classList.toggle("is-active", b === btn));
      };
      nav.appendChild(btn);
    });

    if ("IntersectionObserver" in window && sections.length) {
      const io = new IntersectionObserver((entries) => {
        const visible = entries
          .filter(e => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible || !visible.target.id) return;
        nav.querySelectorAll(".form-dialog-nav-item").forEach(b =>
          b.classList.toggle("is-active", b.dataset.goto === visible.target.id));
      }, { root: main, threshold: [0.18, 0.4, 0.6], rootMargin: "-12% 0px -55% 0px" });
      sections.forEach(fs => io.observe(fs));
      form._dialogIo = io;
    }

    main.appendChild(form);
    shell.append(rail, main);
    return shell;
  }

  /* -------------------------------------------------------- form shell --- */
  /**
   * The action bar of a record form, shared by both surfaces.  It is the same
   * markup in a full page (`.formbar`, sticky at the foot of the form) and in a
   * dialog (`.modal-foot > .formbar`, static) — so a click target, a keyboard
   * shortcut or a test selector is identical wherever the form appears.
   */
  function formActions(form, ctx) {
    const { entity, rec } = ctx;
    const isNew = !rec;
    const bar = document.createElement("div");
    bar.className = "formbar no-print" + (ctx.mode === "dialog" ? " in-dialog" : "");
    bar.innerHTML = `<button type="button" class="btn primary" data-save>${icon("save")} ${t("common.save")}</button>
      ${isNew ? `<button type="button" class="btn" data-save-new>${t("common.save")} + ${t("common.new")}</button>` : ""}
      <a class="btn ghost" href="${isNew ? `#/entity/${entity}` : `#/entity/${entity}/${rec.id}`}"
         data-cancel>${t("common.cancel")}</a>
      <span class="dirty" data-dirty></span>
      <span class="spacer"></span>
      <span class="field-note">${A.t("ui.fieldsMarkedAreComputedAutomaticallyFr")}</span>`;
    let saving = false;
    async function save(andNew) {
      if (saving) return;
      if (!form._validate()) return;
      const payload = form._collect();
      saving = true;
      bar.querySelector("[data-save]").disabled = true;
      try {
        if (isNew) {
          const res = await api.post(`/api/${entity}`, payload);
          toast(t("rec.createdOk"), "ok");
          form._resetDirty();
          if (ctx.onSaved) await ctx.onSaved(res.record, andNew);
        } else {
          const res = await api.put(`/api/${entity}/${rec.id}`, payload);
          toast(t("rec.savedOk"), "ok");
          form._resetDirty();
          if (ctx.onSaved) await ctx.onSaved(res.record || rec, false);
        }
      } catch (err) {
        if (err.status === 409) toast(t("rec.versionConflict"), "err", 7000);
        else toast(err.message, "err", 6000);
      } finally {
        saving = false;
        const btn = bar.querySelector("[data-save]");
        if (btn && btn.isConnected) btn.disabled = false;
      }
    }
    bar.querySelector("[data-save]").onclick = () => save(false);
    const sn = bar.querySelector("[data-save-new]");
    if (sn) sn.onclick = () => save(true);
    form.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(false); }
    });
    const cancel = bar.querySelector("[data-cancel]");
    cancel.onclick = async (e) => {
      if (!form._isDirty()) return;
      e.preventDefault();
      const ok = await A.confirmDialog({
        title: t("form.discardTitle") || t("common.cancel"),
        message: t("form.discardBody") || "",
        confirmLabel: t("common.confirm")
      });
      if (ok) {
        if (ctx.onCancel) ctx.onCancel();
        else location.hash = cancel.getAttribute("href");
      }
    };
    return { bar, save };
  }

  /** Ask before throwing away a draft — used by Escape, the × and the backdrop. */
  async function confirmDiscard(form) {
    if (!form._isDirty()) return true;
    return await A.confirmDialog({
      title: t("form.discardTitle") || t("common.cancel"),
      message: t("form.discardBody") || "",
      confirmLabel: t("common.confirm")
    });
  }

  /** Swap the hash *without* adding a history entry, then redraw. */
  function replaceRoute(hash) {
    history.replaceState(null, "", hash);
    A.rerender();
  }

  /* ------------------------------------------------------- page surface --- */
  async function renderForm(root, entity, rec, params) {
    const isNew = !rec;
    const heading = isNew ? `${t("rec.new")} — ${A.label(entity)}`
      : `${t("rec.edit")} — ${(rec._title || rec.code)}`;
    A.crumbs([{ label: A.pluralOf(entity), href: `#/entity/${entity}` }]
      .concat(rec ? [{ label: rec._title || rec.code, href: `#/entity/${entity}/${rec.id}` }] : [])
      .concat([{ label: isNew ? t("rec.new") : t("common.edit") }]));
    root.innerHTML = A.pageHead(heading,
      isNew ? "" : `${t("common.code")}: ${rec.code} · v${rec.version}`) +
      `<div data-form-host></div>`;
    const host = root.querySelector("[data-form-host]");
    const form = await buildForm(entity, rec);
    /* another navigation may have re-rendered the view while the metadata was
       loading — drop this render instead of stacking a second form */
    if (!host.isConnected || host !== root.querySelector("[data-form-host]")) return;
    host.appendChild(form);
    hydrateIcons(root);

    const { bar } = formActions(form, {
      entity, rec, mode: "page",
      onSaved: (record, andNew) => {
        if (andNew) return renderForm(root, entity, null, params);
        location.hash = `#/entity/${entity}/${record.id}`;
      }
    });
    form.appendChild(bar);
    hydrateIcons(bar);
  }

  /* ----------------------------------------------------- dialog surface --- */
  let activeDialog = null;

  /**
   * The same form, over the page it belongs to: a new record opens over its
   * list, an edit opens over its dossier.  Closing it puts you back exactly
   * where you were, with the hash swapped rather than pushed, so browser Back
   * still means "leave the list" and not "reopen the dialog".
   */
  async function openFormDialog(root, entity, rec, params) {
    A.forms.close(true);                       // never stack two record forms
    const isNew = !rec;
    /* where closing returns to: normally the list a new record joins or the
       dossier being edited — but a caller may say "bring them back to me"
       (the settings screen's "open a form" button does exactly that). */
    const returnTo = A.state.formReturnTo;
    A.state.formReturnTo = null;
    const behind = returnTo || (isNew ? `#/entity/${entity}` : `#/entity/${entity}/${rec.id}`);

    /* 1 · the page behind the dialog — the list a new record will join, or the
           dossier being edited.  If that page is already on screen (the usual
           case: you clicked "New" in the list) it is left alone, so the dialog
           opens over live content instead of a re-painted copy. */
    const want = returnTo || (isNew ? `list:${entity}` : `record:${entity}:${rec && rec.id}`);
    if (!returnTo && root.dataset.surface !== want) {
      if (isNew) await A.views.list(root, Object.assign({}, params, { dialogBehind: true }));
      else await A.views.record(root, Object.assign({}, params, { dialogBehind: true }));
    }

    /* 2 · the form itself */
    const form = await buildForm(entity, rec);
    if (!root.isConnected || A.state.route.view === "notFound") return;
    form.classList.add("in-dialog");
    const body = wrapFormDialog(entity, form, { isNew, rec });

    const title = isNew ? `${t("rec.new")} — ${A.label(entity)}`
      : `${t("rec.edit")} — ${(rec._title || rec.code)}`;
    const entIcon = (A.entitySpec(entity) || {}).icon || "file";
    const dlg = A.modal({
      title,
      subtitle: isNew ? A.pluralOf(entity) : `${rec.code} · v${rec.version}`,
      size: A.formDialogSize(),
      cls: "form-dialog",
      mark: `<div class="form-dialog-mark" data-entity="${esc(entity)}">${icon(entIcon)}</div>`,
      body,
      focus: "input,select,textarea",
      onRequestClose: async () => await confirmDiscard(form),
      onClose: (reason) => {
        if (activeDialog === dlg) activeDialog = null;
        if (A.state.formDialog === dlg) A.state.formDialog = null;
        /* however it was dismissed — ×, Escape, the backdrop — put the address
           back on the page that is now visible, so a reload is not a 404 of the
           form and Back does not reopen it */
        if (String(reason || "").startsWith("saved")) return;
        const cur = "#" + (location.hash || "").replace(/^#/, "");
        if (cur === `#/entity/${entity}/new` || cur === `#/entity/${entity}/${rec && rec.id}/edit`) {
          /* the page behind is already correct — only the address was wrong */
          history.replaceState(null, "", behind);
        }
      }
    });
    activeDialog = dlg;
    A.state.formDialog = dlg;
    dlg.back.dataset.formDialog = entity;
    /* the address this dialog is presenting: a later route change to a *different*
       form (another record, another entity, the list) must not leave it floating
       over a page it does not describe — see app.js render() */
    dlg.back.dataset.formRoute = "#" + String(location.hash || "").replace(/^#/, "");

    const { bar } = formActions(form, {
      entity, rec, mode: "dialog",
      onSaved: (record, andNew) => {
        if (andNew) {
          /* keep the surface open and start a clean draft of the same shape */
          dlg.close("saved-new");
          replaceRoute(`#/entity/${entity}/new`);
          return;
        }
        dlg.close("saved");
        replaceRoute(`#/entity/${entity}/${record.id}`);
      },
      onCancel: () => { dlg.close("cancel"); replaceRoute(behind); }
    });
    if (dlg.foot) dlg.foot.appendChild(bar);
    else form.appendChild(bar);
    hydrateIcons(dlg.back);
    /* the ×, Escape and the backdrop all run the same dirty guard (onRequestClose) */
  }

  /**
   * Close whatever form is on top — used when the route changes underneath it
   * (a sidebar click, Back) so a dialog can never float over someone else's page.
   */
  A.forms = {
    active: () => activeDialog,
    /** Is the open form holding changes the person has not saved? */
    dirty() {
      const form = activeDialog && activeDialog.back.querySelector("form");
      return !!(form && form._isDirty && form._isDirty());
    },
    close(silent) {
      if (!activeDialog) return;
      const d = activeDialog;
      activeDialog = null;
      A.state.formDialog = null;
      d.close(silent === false ? undefined : "route");
    },
    mode: A.formMode,
    /**
     * Open a record form in whichever surface the user's preference picks.
     * `opts.returnTo` names the page to come back to when the form is dismissed
     * (the settings screen's "open a form" button uses it).
     */
    open(entity, id, opts) {
      if (opts && opts.returnTo) A.state.formReturnTo = opts.returnTo;
      location.hash = id ? `#/entity/${entity}/${id}/edit` : `#/entity/${entity}/new`;
    }
  };

  A.views.recordNew = async function (root, params) {
    if (A.formMode() === "dialog") return openFormDialog(root, params.entity, null, params);
    await renderForm(root, params.entity, null, params);
  };

  A.views.recordEdit = async function (root, params) {
    const { entity, id } = params;
    const rec = await api.get(`/api/${entity}/${id}`);
    if (A.formMode() === "dialog") return openFormDialog(root, entity, rec, params);
    await renderForm(root, entity, rec, params);
  };
})();
