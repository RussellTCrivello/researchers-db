# Design review of the proposed registry schema
### SIRAJ · سِراج — bilingual research registry (persons · places · institutions · relationships · sources)

**Scope of this document.** A critical read of the six tables you specified (Character / Places /
Institution / Relationships / Sources / Help tables + change log), followed by the field-by-field
mapping to what is actually implemented in this project, and the items I recommend but deliberately
left for phase 2.

---

## خلاصة بالعربية

تصميمك صحيح في جوهره: خمسة كيانات أساسية + جدول علاقات + جدول مصادر + جداول مساعدة + سجل تغييرات —
وهذه هي البنية الصحيحة لأي سجل بحثي جدّي. أهم خمس ملاحظات:

1. **قوائم المعرّفات النصية** («Associated Institutional IDs»، «Affiliate Identifiers»، «Associated Personal IDs»)
   يجب أن تتحول كلها إلى صفوف في جدول العلاقات، وإلا تفقد التطابق بين الجهتين.
2. **المناصب السابقة** لا تُخزَّن في خلية واحدة؛ تحتاج جدولاً فرعياً بالتواريخ والمؤسسة وحالة السريان.
3. **«Primary Source ID» واحد** لا يكفي؛ معظم المعلومات تُسندها مصادر متعددة، والعكس صحيح — لذلك أضفتُ
   جدول ربط متعدد لمتعدد (source_link) مع إبقاء المصدر الأساسي.
4. **التواريخ تحتاج درجة دقة** (سنة فقط، تقريبي، غير مؤكد)، وإلا انكسر الفرز والتقارير الزمنية.
5. **الترقيم والتحقق والتكرار**: يجب أن يكون المعرّف ثابتاً لا يُعاد استخدامه، مع جدول ترقيم قابل للضبط،
   ومنع التكرار، وحفظ «معرّفات قديمة/خارجية» (VIAF، Wikidata، ORCID، أرقام الجداول السابقة).

كل نقطة من هذه النقاط مُنفَّذة في المشروع، وتفصيلها في الأقسام التالية، مع قائمة بما أوصي به للمرحلة القادمة
(الصلاحيات، حماية البيانات الشخصية للأحياء، تسلسل الحالات، سُبل النشر والبحث الصرفي العربي).

---

## 1. What the original design gets right

| Decision | Why it is sound |
|---|---|
| A **relationship table** rather than per-pair tables | The registry is a graph (person ↔ institution ↔ place ↔ event). One typed edge table scales without schema changes. |
| **Separate sources table** with reliability assessment | Evidence management is what separates a research registry from a contact list. |
| **Help tables** for every controlled list | Prevents vocabulary drift, which is the most common long-term failure in biographical databases. |
| **Authentication level** *and* **record status** as distinct columns | "How well is this known?" and "where is this in the editorial workflow?" are genuinely different questions. Most projects conflate them. |
| **Researcher's notes** per record + **change log** | Editorial reasoning is data; without it a reviewer cannot reconstruct *why* a record says what it says. |
| Bilingual columns from day one | Retrofitting bilingualism is expensive and always loses data. |

## 2. Issues found — and what was done about them

### 2.1 Redundant text lists of identifiers  ⚠️ most important
`Associated Institutional IDs`, `Associated Personal IDs`, `Affiliate Identifiers`,
`Partner Identifiers`, `Associated Personnel Identifiers`, `Institutional Relations` are ID lists
stored as text. They duplicate the relationship table and immediately drift out of sync: delete a
person, and five text fields still reference them.

**Implemented:** every such link is a row in `relationship` (`entity1_type/id`, `entity2_type/id`,
`relationship_type_id`, dates, source, authentication). The free-text summaries are retained only as
*display* fields (`institutional_relations`) with in-form help text pointing to the graph.

### 2.2 "Previous Positions" as a single cell
A cell cannot be filtered, dated, attributed to an institution, or rendered on a timeline.

**Implemented:** child table `person_position` (title AR/EN, institution FK, country, place, start/end
dates + precision, `is_current`, order, notes) with a repeatable-row editor in the record form and a
dedicated detail tab.

### 2.3 One `Primary Source ID` per record
Most claims are supported by several sources, and a single source (a biographical dictionary, an
archive box) supports hundreds of records. A one-to-one column cannot express either direction.

**Implemented:** `primary_source_id` is kept (it is genuinely useful as "the source that anchors this
record"), *plus* a many-to-many `source_link(source_id, entity_type, entity_id, field_key, note)`
that can even cite a **specific field**. Reports measure citation coverage per source and per entity.

### 2.4 Declared vs verified affiliation
"Declared Institutional Affiliation" and "Affiliated Institution ID" look like the same fact, but one
is a claim by the subject and the other is your finding. Mixing them silently loses the distinction.

**Implemented:** `declared_affiliation` (text, as stated) + `affiliated_institution_id` (your
conclusion) + `affiliation_verified` (bool) + `affiliation_start`/`affiliation_end` (validity window).
Historical affiliation changes are additionally expressible as dated `relationship` rows.

### 2.5 Life dates
The Character table had *Date of Birth* and *Current Status* but no *Date of Death* — the single most
queried field in any biographical register.

**Implemented:** `death_date` + `death_precision` + a `person_status` vocabulary
(active / retired / deceased / whereabouts unknown / unknown).

### 2.6 Dates need precision, not just values
`1876`, `c. 1876`, `1876s`, `before 1900`, `1293 AH` are normal in historical sources. A single `DATE`
column either rejects them or sorts them wrongly (`"c. 1876"` sorts before `"1876"` lexically).

**Implemented:** every historical date is stored as text with a companion `*_precision` vocabulary
(exact / day / month / year / approximate / uncertain / range / unknown) and a SQL function
`year_of()` used by filters, sorting, timelines and decade reports.
*Recommended for phase 2:* full EDTF-style intervals (`1900/1950`, `1900~`).

### 2.7 Name variants and identity resolution
Three name columns are not enough to answer "is this the same person as that other record?" —
transliteration, patronymic chains, honorifics (الدكتور، الشيخ، بك، هانم) and spelling variants all
interfere.

**Implemented:** `name_transliteration`, `name_original_lang`, Arabic-aware normalisation for search
(hamza forms, taa marbuta, diacritics, definite article), a duplicate-name check in the quality
report, stable non-reusable codes, and an `entity_external_id` table for VIAF / Wikidata / ORCID /
library authority / legacy spreadsheet numbers.
*Recommended:* an explicit `name_variant` child table (variant, script, period, source) — the model
already supports it as a next migration.

### 2.8 Nothing prevented duplicate identifiers
There was no statement about uniqueness or about what an identifier even *is*.

**Implemented:** a `sequence` table with prefix/separator/suffix/padding/template/reset policy, unique
constraints on `code`, a rule that codes are **never rewritten and never reused**, and a
`legacy_id`-style side table (`entity_external_id`) so imported external numbers never pollute the
registry's own numbering.

### 2.9 Thirteen help tables → one vocabulary table
Thirteen tiny tables mean thirteen migrations every time a value is added, and thirteen join paths.

**Implemented:** a single `lookup` table keyed by `domain` (21 domains, 271 values seeded), with
`parent_id` (hierarchies), `color` (UI), `meta` (JSON, e.g. ISO codes per country), `is_system`
(system values can be deactivated but not deleted), plus a self-describing `lookup_domain` table so
the admin UI can list, count and label every vocabulary. Adding a vocabulary is now *one row*.

### 2.10 Status vocabularies imply a workflow that was not specified
`Record Status` and `Authentication Level` are ordered scales; without allowed transitions and role
rules, any record can jump from "draft" to "published" without review.

**Implemented:** the vocabularies are ordered and colour-coded, and the review report shows the
backlog by status. *Recommended next:* a transition table (`allowed_transitions`) with role checks —
the data model already stores the reviewer and review date needed to enforce it.

### 2.11 Places: precision, hierarchy, and administrative change
`Latitude`/`Longitude` with no precision or geocoding source is a common source of false confidence;
and places nest (quarter → city → governorate → country). Administrative units also change name and
boundary over time (Mosul *vilayet* vs Nineveh *governorate*).

**Implemented:** `parent_place_id` self-reference, `geo_precision`, `geo_description`, `district`,
`region`, `city`, `country` (ISO-coded vocabulary) and coordinate range checks (-90/90, -180/180).
*Recommended:* `place_name_history(place_id, name, language, valid_from, valid_to, source)` and a
bounding box for regions.

### 2.12 Institutions: founders and leadership as free text
`Founders` and `Current Leadership` as text cannot answer "which institutions did this person found?"

**Implemented:** both kept as display text, but the authoritative form is a `relationship` row
(`founder_of`, `director_of`, `board_member_of`, `employed_by` …) with dates and a source;
`Areas of Expertise` became tags (`tag` + `entity_tag`), and the unused *governance systems*
vocabulary is now attached to institutions (`governance_id`).

### 2.13 External party types and indicator areas had no home
Two vocabularies were listed but no column consumed them.

**Implemented:** `governance_system` → `institution.governance_id`; `indicator_area` is used as the
dimension of the **indicator report** (coverage, geocoding, sourcing, partnership metrics).
`external_party_type` is exposed for relationship-endpoint classification and for the planned
"external partner" module.

### 2.14 The change log needed to be an audit trail, not a note
`Transaction Number | Field Changed | Old | New | Reason | New Source ID | Researcher/Reviewer`
is the right shape but needs: a snapshot of the record code, an explicit action type, grouping of one
save into one transaction, actor identity, and immutability.

**Implemented:** `change_log` with `tx_id` (one per save), `action` (create/update/delete/restore/
import/bulk), `entity_code` snapshot, `field_label`, `old_value`/`new_value`, `reason`,
`source_id`, `actor`, `reviewed_by`, `notes`, `changed_at`, indexed by entity and by time. The UI
shows it per record and globally with filters. Soft delete means the log remains meaningful after a
record "disappears".

### 2.15 Soft delete and referential safety
Deleting a person who is referenced by 40 relationships and 12 sources must not cascade silently.

**Implemented:** `deleted_at` soft delete (recoverable, hidden from lists, visible with
`include_deleted`), explicit `restore`, and a separate `hard delete` for admins that removes the row,
its tags and its search document and records the deletion with a clear "HARD DELETE" note.

### 2.16 Attachments and link rot
`Curriculum Vitae`, `Image Link`, `Website` are URL columns. Links die; the evidence disappears.

**Implemented:** `attachment` table + upload/download/delete endpoints + a record detail "Attachments"
tab (25 MB cap). *Recommended:* checksum + periodic link checking + a rights/licence column.

### 2.17 Bilingual model: two languages is not "multilingual"
Bilingual columns are the right trade-off for Arabic/English and are what is implemented (every label
is bilingual: fields, vocabularies, reports, exports, UI). Genuine *n*-language support needs a
translation table.

**Implemented:** UI is fully bilingual AR/EN with RTL/LTR switching, and addition of a language is a
configuration step: one row in `locale` + one JSON bundle in `static/js/locales/` (bundles for `fr` and
`tr` are prepared as inactive). **Recommended for Arabic-first projects:** a
`translation(entity_type, entity_id, field, lang, value, source)` table when a third full-content
language is required.

### 2.18 Arabic search
Standard `LIKE` on Arabic fails for أربعة أسباب: التشكيل، الهمزات (أ/إ/آ/ا)، التاء المربوطة/الهاء،
و«ال» التعريف. A searcher who types `الموصل` must find `موصل` and vice versa.

**Implemented:** SQLite FTS5 index with a normalised shadow column (diacritics, tatweel, hamza
folding, taa marbuta, definite article, Latin accent stripping) and prefix matching, so `موصل`,
`الموصل`, `أحمد`/`احمد` all match, plus automatic re-indexing on every write.
*Recommended:* Arabic stemming/root-based search (Elasticsearch/OpenSearch with an Arabic analyser)
when the corpus exceeds roughly 10⁵ records.

### 2.19 Import was not addressed in the design
A registry lives or dies by its bulk-load path: legacy spreadsheets, Arabic filenames, CP1256
encodings, "c. 1876" dates, names in the wrong column.

**Implemented:** a four-step pipeline (template → upload → map/validate → commit) with
Excel/CSV/TSV/JSON support, automatic encoding detection (UTF-8 / UTF-8-BOM / CP1256 / CP1252),
header auto-mapping in both languages, value resolution by code **or** English **or** Arabic label,
dry-run validation with per-row error reports, three match modes (create / upsert / update-only),
per-row savepoints so one bad row cannot poison a batch, and an `import_job` record for every batch.

### 2.20 Export and reporting were implied but not specified
**Implemented:** CSV (UTF-8 BOM for Excel + Arabic), TSV, JSON and XLSX (RTL sheets, styled headers,
frozen panes, auto-filter), column selection, label language (AR / EN / both), code resolution — always
respecting the current filters and column set. Nine production reports plus an ad-hoc pivot builder,
each printable and exportable.

### 2.21 Not in your list but usually needed
* **Rights / licence / provenance** per source and attachment.
* **Sensitive-data policy**: living persons' personal data (birthplace, contact, image) is
  personal data under GDPR and similar regimes. The schema supports minimisation and deletion, but a
  policy + role-based access is required before public exposure.
* **Publication/works entity** (`work`, `work_author`, `citation`) if the registry is also meant to
  become bibliometric — `indicator_area` already anticipates it.
* **Authentication/authorisation**: v1 ships without login (single-tenant, trusted environment) and
  records the acting user via a header-driven actor selector. See `docs/OPERATIONS.md` §Security.

## 3. Field-by-field mapping

### Character table → `person`

| Your column | Implemented as | Note |
|---|---|---|
| Identification Number | `code` | Auto-generated (`PER-0001`), unique, non-reusable |
| Name in Arabic | `name_ar` | Required |
| Name in Original Language | `name_original` + `name_original_lang` | Language separated out |
| Name in English | `name_en` | |
| — | `name_transliteration` | **added** (identity resolution) |
| Image Link | `image_url` | Plus attachments for durable images |
| Date of Birth | `birth_date` + `birth_precision` | **precision added** |
| — | `death_date` + `death_precision` | **added** |
| Nationality | `nationality_id` → vocabulary `country` | Normalised to ISO-coded list |
| Place of Birth | `birthplace_id` (FK place) + `birthplace_text` | Both structured and "as stated" |
| Occupation/Classification | `classification_id` → `person_classification` | 14 seeded values |
| Specialization | `tag` / `entity_tag` (domain `specialization`) | Multi-valued |
| Current Status | `current_status_id` → `person_status` | Life state |
| — | `current_position` | **added** (status ≠ position) |
| Previous Positions | `person_position` child table | **normalised** |
| Affiliated Institution ID | `affiliated_institution_id` | |
| Affiliated Country | `affiliated_country_id` | |
| Declared Institutional Affiliation | `declared_affiliation` + `affiliation_verified` + validity dates | **separated claim from finding** |
| Curriculum Vitae | `cv_url` + attachments | |
| Public Activity | `public_activity` | |
| Institutional Relations | `institutional_relations` (text) **+** `relationship` rows | Structured form is authoritative |
| Official Website/Account | `website` + `social_accounts` | |
| Primary Source ID | `primary_source_id` **+** `source_link` (many-to-many) | **extended** |
| Authentication Level | `authentication_id` → `authentication_level` | 6-step scale |
| Record Status | `record_status_id` → `record_status` | 8 values, colour-coded |
| Date Last Updated | `updated_at` / `updated_by` / `version` | Automatic + concurrency control |
| Researcher's Notes | `researcher_notes` | |
| — | `documentation_id` | **added** (your help table existed, no column used it) |
| — | `created_*`, `deleted_at`, `entity_external_id` | **added** |

`place`, `institution`, `relationship`, `source` follow the same pattern; the full field list per
entity is in `docs/DATA_MODEL.md` and is itself the source of truth for forms, filters, exports,
import templates and reports (`app/schemas.py`).

## 4. Conventions I standardised (and recommend you keep)

1. `id` (surrogate, never exposed in URLs to end users beyond the app) **and** `code` (human key).
2. `*_id` = foreign key or vocabulary id; `*_at` = UTC ISO-8601 timestamp; `is_*` = boolean;
   `*_precision` = companion to a free-form historical date.
3. All controlled vocabulary in one table; never a hard-coded `CHECK` list in application code.
4. Every write goes through the repository layer, which alone writes the audit trail and the search
   index — no ad-hoc `INSERT` from a route.
5. Nothing is deleted without a log entry; nothing is numbered twice.
6. Labels are data (bilingual), never string literals in the code.

## 5. Deliberate scope limits (phase 2 candidates)

| Area | Current state | Next step |
|---|---|---|
| Authentication / SSO | Actor selector + roles in `app_user` | OIDC/SAML login, per-role permissions, row-level rules for sensitive records |
| Workflow enforcement | Status vocabulary + review report | Allowed-transition table, "submit/approve/publish" actions, reviewer assignment |
| Arabic morphology | Normalisation + prefix FTS + duplicate detection on normalised names | Arabic analyser / stemming engine |
| Name variants | Transliteration field + external IDs | `name_variant` table with script/period/source |
| Place name history | Current names + hierarchy | `place_name_history` with validity periods |
| Works/publications | Not modelled | `work`, `work_author`, `work_citation` + bibliometric indicators |
| Digital preservation | Local `uploads/` + checksums absent | Object storage (S3/MinIO), checksums, link-rot checks |
| Scale | SQLite (WAL, FTS5) — comfortable to ~10⁵–10⁶ rows | PostgreSQL + OpenSearch; `app/repo.py` isolates the SQL |


---

## 6. Addendum — phase 2: interface, related-table fields, imagery

The schema review above is unchanged. Phase 2 was about making the *interface* keep up with the
data model: enterprise registries fail not because fields are missing, but because entering and
browsing them is slow. Three design decisions were taken.

### 6.1 A field that points at another table is a search box, not a `<select>`

A dropdown listing 300 institutions is a lookup table rendered as punishment: the user scrolls,
mis-clicks, and — worse — leaves the form to create the institution that is missing. So every
foreign key and every large vocabulary now renders as a combobox with:

* server-side search across `code`, English and Arabic labels, using the same normalisation as the
  database (so `احمد` finds `أحمد`);
* recent choices first (per field, remembered locally);
* **inline creation**: “＋ Add …” opens a compact pop-up with only the target's required fields,
  creating the record through the normal API (numbering, validation, audit, FTS all apply) and
  selecting it in place. Creation can nest one level (institution → place) and then stops.

The rule is enforced by construction: fields are declared `fk`/`select` in `schemas.py`, and the
form builder decides the widget from the metadata, so a new relation cannot be added “as a plain
text box” by accident.

### 6.2 Fields derived from related tables are first-class

Enterprise users constantly ask questions the base table cannot answer: *how many relationships
does this scholar have? which institution is his, by name? how complete is this record?* Answering
them with joins in the UI duplicates SQL in JavaScript and rots.

Instead, derived fields are **declared once** in `DERIVED_FIELDS` (SQL expression + type + label +
help) and then behave like stored fields everywhere: column chooser, filter builder, sort, export,
saved views, card layouts and report pivots. `/api/meta` publishes each expression so a data
steward can audit how a number was produced, and the record page has a dedicated *Related tables*
tab listing all of them.

Consequences accepted: derived fields are read-only (they can never be edited or imported), they
cost one correlated subquery each (fine at this scale, and the query layer is isolated for a future
materialised-view or PostgreSQL migration), and they never appear in the base table's write path.

### 6.3 The same data, several visual grammars

A registry of people, institutions, places and events is browsed in different moods: scanning
(a dense table), recognising (cards with portraits), surveying a collection (gallery), or reading a
queue (rows). All four views share one filter/sort/column state, and the **card layout builder**
lets the user decide which field is the image, the title, the subtitle, the badge and which derived
figures appear as KPI figures — so “profile cards” and “entity cards” come from the same screen
without a developer.

Imagery became a first-class attribute (`image_url` + `image_alt` on person/institution/place/event,
upload endpoint, alt text used for accessibility and captions). Cards degrade to an initials band or
a compact placeholder strip when no image exists, so a half-catalogued collection still looks
intentional rather than broken.

### 6.4 Duplicates are a workflow, not an error message

Unique codes prevent accidental double-entry with the *same* code, but real duplicates arrive with
different codes and different spellings. `find_duplicates` groups records whose names collide after
Arabic normalisation; `merge_records` previews the operation (`dry_run`), fills empty fields from the
duplicates, moves links/positions/citations/relationships/attachments, soft-deletes the absorbed
records (recoverable) and writes the whole operation to the audit trail under one `tx_id`.
Data loss is impossible by construction: nothing is hard-deleted and every field that changed is
logged with its old and new value.

---

*This review is the design rationale for what is implemented. Where the implementation chose
something different from the specification above, the difference is intentional and is noted in the
mapping tables.*
