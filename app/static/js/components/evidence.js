/* ==========================================================================
   Evidence — one source, many claims
   --------------------------------------------------------------------------
   A citation is not a bibliography entry: it is a statement that *this* source
   says *this* about *that*. So every card answers four questions in order:

     1. what does the source say          → supported_claim, page_or_timestamp
     2. how does it bear on the claim     → supports · contradicts · context
     3. how good is the source            → reliability  (an assessment of the source)
     4. how well is the claim verified    → verification (an assessment of the claim)

   3 and 4 are deliberately separate: a reliable source can be wrong about one
   thing, an unreliable one can be right about another. Contradictions are not
   errors to be cleaned up — they are shown beside the support, and the record is
   flagged disputed rather than silently resolved.
   ========================================================================== */
(function () {
  const SUPPORT = {
    supports: { cls: "ok", icon: "✓" },
    contradicts: { cls: "danger", icon: "✕" },
    contextualizes: { cls: "gray", icon: "○" }
  };

  const lang = () => (window.App && App.state && App.state.lang) || "ar";
  const text = (en, ar) => (lang() === "ar" ? (ar || en || "") : (en || ar || ""));
  const esc = (s) => (window.App && App.esc ? App.esc(String(s == null ? "" : s)) : String(s == null ? "" : s));

  /* ------------------------------------------------------------- labels --- */
  function supportLabel(kind) {
    const k = kind || "supports";
    const labels = {
      supports: ["Supports", "يؤيد"],
      contradicts: ["Contradicts", "يناقض"],
      contextualizes: ["Gives context", "يقدم سياقاً"]
    }[k] || [k, k];
    return text(labels[0], labels[1]);
  }

  function badge(kind) {
    const k = kind || "supports";
    const meta = SUPPORT[k] || SUPPORT.supports;
    return `<span class="ev-badge ev-${esc(meta.cls)}" title="${esc(supportLabel(k))}">` +
           `${meta.icon} ${esc(supportLabel(k))}</span>`;
  }

  /* ------------------------------------------------------------- one card --- */
  function card(row, opts) {
    opts = opts || {};
    const title = text(row.title, row.title_ar) || row.source_code || ("#" + row.source_id);
    const type = text(row.source_type_en, row.source_type_ar);
    const reliability = text(row.reliability_en, row.reliability_ar);
    const verification = text(row.verification_en, row.verification_ar);
    const bits = [];
    if (type) bits.push(esc(type));
    if (row.publisher) bits.push(esc(row.publisher));
    if (row.publication_date) bits.push(esc(row.publication_date));
    if (row.page_or_timestamp) {
      bits.push(`<span class="ev-page">${esc(text("p.", "ص."))} ${esc(row.page_or_timestamp)}</span>`);
    }

    const meta = [];
    if (reliability) {
      meta.push(`<span class="ev-meta-k">${esc(text("Source reliability", "موثوقية المصدر"))}</span>
                 <span class="ev-meta-v">${esc(reliability)}</span>`);
    }
    /* Always shown, even when nobody has assessed the claim yet. An absent
       assessment is information: it tells the reader that this claim has not
       been reviewed, which is different from a claim reviewed and doubted. A
       missing row would let the two look identical. */
    meta.push(`<span class="ev-meta-k">${esc(text("Claim verification", "التحقق من الادعاء"))}</span>` +
              (verification
                ? `<span class="ev-meta-v">${esc(verification)}</span>`
                : `<span class="ev-meta-v ev-meta-none">${esc(text("Not yet assessed", "لم يُقيَّم بعد"))}</span>`));
    if (row.reviewer) {
      meta.push(`<span class="ev-meta-k">${esc(text("Reviewed by", "راجعه"))}</span>
                 <span class="ev-meta-v">${esc(row.reviewer)}${row.review_date ? " · " + esc(row.review_date) : ""}</span>`);
    }

    return `
      <article class="ev-card ev-${esc(row.support_type || "supports")}" data-evidence="${row.id}">
        <header class="ev-head">
          ${badge(row.support_type)}
          <a class="ev-title" href="#/entity/source/${row.source_id}" dir="auto">${esc(title)}</a>
          <span class="mono-cell small muted">${esc(row.source_code || "")}</span>
          ${opts.removable === false ? "" :
            `<button class="icon-btn ev-remove" data-unlink="${row.id}"
                     title="${esc(text("Withdraw this evidence link", "سحب رابط الدليل"))}"
                     aria-label="${esc(text("Withdraw this evidence link", "سحب رابط الدليل"))}">✕</button>`}
        </header>
        ${bits.length ? `<div class="ev-sub small muted">${bits.join(" · ")}</div>` : ""}
        ${row.supported_claim ? `<blockquote class="ev-claim" dir="auto">${esc(row.supported_claim)}</blockquote>` : ""}
        ${row.field_key ? `<div class="ev-field small"><span class="ev-meta-k">${esc(text("Supports field", "يدعم الحقل"))}</span>
          <code>${esc(row.field_key)}</code></div>` : ""}
        ${meta.length ? `<dl class="ev-meta">${meta.map((m) => m).join("")}</dl>` : ""}
        ${row.url ? `<a class="ev-link small" href="${esc(row.url)}" target="_blank"
                       rel="noopener noreferrer">${esc(text("Open the source", "فتح المصدر"))} ↗</a>` : ""}
        ${row.notes ? `<div class="ev-note small muted" dir="auto">${esc(row.notes)}</div>` : ""}
      </article>`;
  }

  /* --------------------------------------------------------- the whole list --- */
  /**
   * `rows` come straight from the API: entity citations, or a relationship's
   * evidence list. `summary` is optional and only affects the header line.
   */
  function list(rows, opts) {
    opts = opts || {};
    rows = rows || [];
    if (!rows.length) {
      return `<div class="ev-empty muted small">${esc(
        opts.empty || text("No source is linked to this claim yet.",
                           "لا يوجد مصدر مرتبط بهذا الادعاء بعد."))}</div>`;
    }
    const contradicts = rows.filter((r) => r.support_type === "contradicts").length;
    const head = `<div class="ev-list-head">
        <span>${esc(text("Evidence", "الأدلة"))} <b>${rows.length}</b></span>
        ${contradicts ? `<span class="ev-badge ev-danger" title="${esc(text("Contested", "متنازع عليه"))}">
            ⚠ ${esc(text("contested", "متنازع عليه"))} · ${contradicts}</span>` : ""}
      </div>`;
    return `<div class="ev-list">${opts.head === false ? "" : head}` +
           rows.map((r) => card(r, opts)).join("") + `</div>`;
  }

  /** Wire the withdraw buttons inside a container. */
  function bind(root, onChange) {
    if (!root) return;
    root.querySelectorAll("[data-unlink]").forEach((btn) => {
      btn.onclick = async () => {
        if (!window.confirm(text("Withdraw this evidence link? The source itself is kept.",
                                 "سحب رابط الدليل؟ يبقى المصدر نفسه محفوظاً."))) return;
        try {
          await App.api.del(`/api/citations/${btn.dataset.unlink}`);
          App.toast(text("Evidence withdrawn", "تم سحب الدليل"), "ok");
          onChange && onChange();
        } catch (err) {
          App.toast(err.message, "err");
        }
      };
    });
  }

  /* --------------------------------------------------------- add a claim --- */
  /**
   * The add form asks for the claim, not just the source: what the document
   * says, where, how it bears on the record, and — optionally — how well the
   * claim itself has been verified. Everything except the source is optional,
   * because a researcher often links first and annotates later.
   */
  function addDialog(opts) {
    opts = opts || {};
    const isRelationship = opts.relationshipId != null;
    const fixedSource = opts.sourceId != null;
    const pickTarget = fixedSource && opts.entityId == null && opts.relationshipId == null;
    const body = `
      ${fixedSource ? `<div class="field"><label>${esc(text("Source", "المصدر"))}</label>
        <div class="notice ok small">${esc(opts.sourceTitle || ("#" + opts.sourceId))}</div></div>`
        : `<div class="field"><label>${esc(text("Source", "المصدر"))}</label><div id="evSrcHost"></div></div>`}
      ${pickTarget ? `
      <div class="field"><label>${esc(text("About which record?", "عن أي سجل؟"))}</label>
        <div class="field-row">
          <select id="evTgtType">${["person", "institution", "place", "event", "relationship"].map(k =>
            `<option value="${k}">${esc((App.label && App.label(k)) || k)}</option>`).join("")}</select>
          <div id="evTgtHost" style="flex:1"></div>
        </div></div>` : ""}
      <div class="field"><label>${esc(text("What does the source say?", "ماذا يقول المصدر؟"))}</label>
        <textarea id="evClaim" rows="3" dir="auto"
          placeholder="${esc(text("The statement supported, in your words or quoted.",
                                  "الادعاء المدعوم، بصياغتك أو منقولاً."))}"></textarea></div>
      <div class="field-row">
        <div class="field"><label>${esc(text("Where (page, folio, time)", "الموضع (صفحة، ورقة، وقت)"))}</label>
          <input id="evPage" dir="auto" placeholder="${esc(text("p. 43", "ص. 43"))}"></div>
        <div class="field"><label>${esc(text("How it bears on the claim", "كيف يتعامل مع الادعاء"))}</label>
          <select id="evSupport"></select></div>
      </div>
      <div class="field-row">
        <div class="field"><label>${esc(text("Verification of this claim", "التحقق من هذا الادعاء"))}</label>
          <select id="evVerif"><option value="">${esc(text("Not assessed", "غير مقيَّم"))}</option></select></div>
        <div class="field"><label>${esc(text("Notes", "ملاحظات"))}</label><input id="evNote" dir="auto"></div>
      </div>
      ${isRelationship ? "" : `<div class="field"><label>${esc(text("Supports which field? (optional)", "يدعم أي حقل؟ (اختياري)"))}</label>
        <input id="evField" dir="auto" placeholder="birth_date"></div>`}
      ${pickTarget ? `<div class="notice small">${esc(text(
        "Reliability describes the source; verification describes this claim.",
        "الموثوقية تصف المصدر، والتحقق يصف هذا الادعاء."))}</div>` : ""}
      <div class="notice small">${esc(text(
        "Reliability describes the source; verification describes this claim. A contradiction is recorded beside the support, never instead of it.",
        "الموثوقية تصف المصدر، والتحقق يصف هذا الادعاء. يُسجَّل التعارض إلى جانب التأييد لا بدلاً منه."))}</div>`;

    const m = App.modal({
      title: opts.title || (fixedSource
        ? text("Record a claim this source makes", "تسجيل ادعاء يصدر عن هذا المصدر")
        : text("Link a source to this claim", "ربط مصدر بهذا الادعاء")),
      body, size: "slim",
      buttons: [
        { label: App.t("common.cancel") },
        { label: App.t("common.save"), cls: "primary", onClick: async (close, b) => {
            const sourceId = fixedSource ? opts.sourceId : srcCombo.getValue();
            if (!sourceId) return App.toast(App.t("common.select"), "warn");
            const payload = {
              source_id: sourceId,
              supported_claim: b.querySelector("#evClaim").value.trim() || null,
              page_or_timestamp: b.querySelector("#evPage").value.trim() || null,
              support_type: b.querySelector("#evSupport").value || "supports",
              verification: b.querySelector("#evVerif").value || null,
              note: b.querySelector("#evNote").value.trim() || null
            };
            if (isRelationship) payload.relationship_id = opts.relationshipId;
            else if (pickTarget) {
              /* the claim is about a record the researcher names here */
              const tt = b.querySelector("#evTgtType").value;
              const tid = tgtCombo && tgtCombo.getValue();
              if (!tid) return App.toast(App.t("common.select"), "warn");
              if (tt === "relationship") payload.relationship_id = Number(tid);
              else { payload.entity_type = tt; payload.entity_id = Number(tid); }
              const field = b.querySelector("#evField");
              if (field && field.value.trim()) payload.field_key = field.value.trim();
            } else {
              payload.entity_type = opts.entityType;
              payload.entity_id = opts.entityId;
              const field = b.querySelector("#evField");
              if (field && field.value.trim()) payload.field_key = field.value.trim();
            }
            try {
              await App.api.post("/api/evidence", payload);
              App.toast(App.t("common.saved"), "ok");
              close();
              opts.onSaved && opts.onSaved();
            } catch (err) {
              App.toast(err.message, "err", 5000);
            }
          } }
      ]
    });

    let srcCombo = null;
    if (!fixedSource) {
      srcCombo = App.combobox({ entity: "source", allowCreate: true, limit: 30 });
      m.body.querySelector("#evSrcHost").appendChild(srcCombo);
    }
    /* a fixed-source claim still needs a target: type select + combobox,
       remounted on type change — the same two-step picker the relationship
       composer uses */
    let tgtCombo = null;
    const mountTarget = () => {
      const host = m.body.querySelector("#evTgtHost");
      if (!host) return;
      host.innerHTML = "";
      tgtCombo = App.combobox({
        entity: m.body.querySelector("#evTgtType").value,
        allowCreate: true, limit: 30,
        placeholder: App.t("common.search")
      });
      host.appendChild(tgtCombo);
    };
    const tgtType = m.body.querySelector("#evTgtType");
    if (tgtType) {
      mountTarget();
      tgtType.onchange = mountTarget;
    }

    // the three support types come from the server's controlled list
    const supportSel = m.body.querySelector("#evSupport");
    const types = (window.App.data && App.data.evidenceSupportTypes) || [
      { code: "supports", label_en: "Supports", label_ar: "يؤيد" },
      { code: "contradicts", label_en: "Contradicts", label_ar: "يناقض" },
      { code: "contextualizes", label_en: "Gives context", label_ar: "يقدم سياقاً" }
    ];
    supportSel.innerHTML = types.map((s) =>
      `<option value="${esc(s.code)}">${esc(text(s.label_en, s.label_ar))}</option>`).join("");

    // verification levels come from the same authentication_level vocabulary as
    // the records, so a claim cannot invent a level the methodology lacks
    const verif = m.body.querySelector("#evVerif");
    App.api.get("/api/lookups?domain=authentication_level").then((doc) => {
      const rows = Array.isArray(doc) ? doc : ((doc && (doc.values || doc.items)) || []);
      if (rows.length) {
        verif.innerHTML = `<option value="">${esc(text("Not assessed", "غير مقيَّم"))}</option>` +
          rows.map((r) => `<option value="${esc(r.code)}">${esc(text(r.label_en, r.label_ar))}</option>`).join("");
      }
    }).catch(() => { /* the default list is enough */ });
    return m;
  }

  window.App = window.App || {};
  App.evidence = { list, card, badge, bind, addDialog, supportLabel };
})();
