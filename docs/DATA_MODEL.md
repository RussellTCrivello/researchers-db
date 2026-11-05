# Data model

SQLite (WAL mode + FTS5). The schema lives in `app/schema.sql` (fresh installs) and
`app/migrations/*.sql` (incremental changes, applied once and recorded in `schema_migration`).

## 1. Entity map

```
                      ┌──────────────┐        ┌────────────────────┐
                      │   lookup     │◄───────┤  lookup_domain     │
                      │ (vocabularies)│        └────────────────────┘
                      └──────┬───────┘
        ┌────────────────────┼─────────────────────────┬───────────────┐
        │                    │                         │               │
  ┌─────▼─────┐        ┌─────▼──────┐            ┌─────▼──────┐  ┌─────▼─────┐
  │  person   │        │ institution│            │   place    │  │  event    │
  │           │        │            │            │ (self-ref  │  │           │
  │           │        │            │            │  hierarchy)│  │           │
  └──┬──┬──┬──┘        └──┬───┬─────┘            └──┬───┬─────┘  └──┬───┬────┘
     │  │  │              │   │                     │   │           │   │
     │  │  └──────────────┴───┴─────────┬───────────┴───┴───────────┘   │
     │  │                    ┌──────────▼─────────┐                     │
     │  │                    │   relationship     │  (typed graph edge)  │
     │  │                    └──────────┬─────────┘                     │
     │  │                               │                               │
     │  │        ┌──────────────┐       │      ┌────────────────┐       │
     │  │        │person_position│      │      │    source      │◄──────┘
     │  │        └──────────────┘       │      └───┬────────┬───┘
     │  │                               │          │        │
     │  │        ┌──────────────┐       │   ┌──────▼──────┐ │
     │  └───────►│  source_link │◄──────┴───┤ attachments │ │
     │           │ (many-many)  │           └─────────────┘ │
     │           └──────────────┘                           │
     │  ┌──────────────┐   ┌─────────────────────┐  ┌───────▼──────────┐
     └─►│ entity_tag   │◄──┤ tag                 │  │ entity_external_id│
        └──────────────┘   └─────────────────────┘  └───────────────────┘

  Support: sequence · saved_view · import_job · change_log · setting · app_user ·
           locale · search_doc (FTS5) · schema_migration · app_meta
```

## 2. Conventions

| Rule | Detail |
|---|---|
| Identity | `id` INTEGER PK (surrogate) + `code` TEXT UNIQUE (human, generated, never reused) |
| Audit columns | `created_at`, `created_by`, `updated_at`, `updated_by`, `version`, `deleted_at` |
| Soft delete | `deleted_at` set instead of `DELETE`; `include_deleted` reveals |
| Concurrency | `version` increments on write; clients send `_version`; mismatch → HTTP 409 |
| Vocabularies | `*_id` → `lookup.id`; the domain is declared in `app/schemas.py` |
| Historical dates | TEXT, holding **exactly** the precision that is known: `1950` · `1950-05` · `1950-05-12` · `1950-05-12T21:45` · the legacy research forms `c. 1850`, `1850s`, `1850?`. A time is an optional suffix, never a separate type, so a decade is never silently promoted to a day |
| Timestamps | UTC ISO-8601 seconds (`2026-11-01T20:47:52Z`) |
| Booleans | INTEGER 0/1 |
| JSON columns | `lookup.meta`, `saved_view.filters`, `import_job.report` |
| Graph edges | `relationship(entity1_type, entity1_id, …)`; `*_type` stores the vocabulary **code** |
| Denormalised snapshots | `relationship.entity1_name/entity2_name` kept for resilient display only |

## 3. Tables

### Core entities
| Table | Purpose | Notable columns |
|---|---|---|
| `person` | individuals | `name_ar`, `name_en`, `name_original`(+`_lang`), `name_transliteration`, `birth_date`(+`_precision`), `death_date`(+`_precision`), `nationality_id`, `birthplace_id`, `birthplace_text`, `classification_id`, `current_status_id`, `current_position`, `affiliated_institution_id`, `affiliated_country_id`, `declared_affiliation`, `affiliation_verified/start/end`, `cv_url`, `public_activity`, `institutional_relations`, `website`, `social_accounts`, `primary_source_id`, `documentation_id`, `authentication_id`, `record_status_id`, `researcher_notes` |
| `person_position` | previous/current positions | `person_id`, `title_ar`, `title_en`, `institution_id`, `country_id`, `place_id`, `start_date`, `end_date`, `is_current`, `sort_order` |
| `place` | places | `name_ar`, `name_en`, `name_original`(+`_lang`), `place_type_id`, `country_id`, `region`, `city`, `district`, `parent_place_id`, `latitude`, `longitude`, `geo_precision`, `geo_description`, `research_significance` |
| `institution` | institutions | `name_ar`, `name_en`, `abbreviation`, `institution_type_id`, `subcategory_id`, `founded_date`(+`_precision`), `closed_date`, `country_id`, `city`, `place_id`, `address`, `current_leadership`, `founders_text`, `objectives`, `org_structure`, `governance_id`, `website`, `official_accounts`, `research_significance` |
| `event` | dated events | `title_ar`, `title_en`, `event_type_id`, `start_date`, `end_date`, `place_id`, `description`, `significance` |
| `relationship` | typed graph edge | `entity1_type/id/name`, `entity2_type/id/name`, `relationship_type_id`, `direction`, `description`, `start_date`, `end_date`, `is_current`, `source_id`, `authentication_id`, `last_review_date` |
| `source` | evidence | `title`, `title_ar`, `source_type_id`, `publisher`, `url`, `publication_date`(+`_precision`), `access_date`, `language`, `isbn_issn`, `archive_reference`, `supported_information`, `reliability_id`, `verification_notes` |

### Links and metadata
| Table | Purpose |
|---|---|
`source_link` | many-to-many citation; optional `field_key` to cite a specific field
`entity_tag` / `tag` | specialisations, expertise, keywords (multi-valued)
`entity_external_id` | VIAF / Wikidata / ORCID / legacy numbers, with URL
`attachment` | uploaded files (CV, scans, images) with mime, size, kind
`lookup` / `lookup_domain` | every controlled vocabulary, with `parent_id`, `color`, `meta`, `is_system`
`locale` | interface languages (code, native name, direction, active/default)
`sequence` | numbering rules per entity (prefix, separator, suffix, padding, template, reset policy)
`saved_view` | stored filter/column/sort presets per entity
`import_job` | one row per import batch (mode, counts, mapping, error report, actor)
`change_log` | field-level audit trail (`tx_id`, action, field, old/new, reason, source, actor, reviewer)
`search_doc` | FTS5 index (title, body, normalised text)
`setting`, `app_user`, `app_meta`, `schema_migration` | configuration, actors, version, migrations

### Views
`v_person_full` (person + institution/place/status/auth labels), `v_relationship_full`
(relationship + type/status/source labels) — convenience projections for reports and exports.

## 4. Vocabulary domains (21)

`record_status` · `authentication_level` · `documentation_level` · `entity_type` ·
`country` (57 ISO-coded) · `person_classification` · `person_status` · `place_type` ·
`institution_type` · `institution_subcategory` · `relationship_type` (33, with
inverse/symmetric metadata) · `relation_direction` · `source_type` · `source_reliability` ·
`external_party_type` · `event_type` · `governance_system` · `indicator_area` ·
`date_precision` · `geo_precision` · `language`

Add a value at **Administration → Vocabularies** (or `POST /api/lookups`); no migration needed.

## 5. Indexes

Every foreign key used for filtering has an index (`ix_*`), plus: `place(latitude, longitude)`,
`relationship(entity1_type, entity1_id)` and `(entity2_type, entity2_id)`,
`change_log(entity_type, entity_id, changed_at DESC)`, `change_log(changed_at DESC)`,
`search_doc` (FTS5), `source_link(source_id)` and `(entity_type, entity_id)`.

Uniqueness: `person.code`, `place.code`, `institution.code`, `event.code`, `relationship.code`,
`source.code`, `lookup(domain, code)`, `tag(domain, label_en)`,
`relationship(entity1_type, entity1_id, relationship_type_id, entity2_type, entity2_id)`,
`source_link(source_id, entity_type, entity_id, field_key)`.

## 6. SQL helpers registered per connection

| Function | Use |
|---|---|
`norm(text)` | Arabic/Latin normalisation, used by `LIKE` filters and search |
`year_of(text)` | extracts the year from `1876`, `c. 1876`, `1876-05-12`, `1950s` — used by date filters, sorting and decade reports |
`ts_of(text)` | the same value as a comparable moment (`1876` → `1876-01-01 00:00:00`, `…T21:45` → `… 21:45:00`) — used by every date comparison and by date sorting, so mixed precisions compare on one timeline |

## 7. Migrating to PostgreSQL

All SQL is standard except `strftime(...)` defaults and the two custom functions. Steps:
1. replace the in-schema timestamp defaults with `now()` / `CURRENT_TIMESTAMP`;
2. implement `norm()`/`year_of()` as `IMMUTABLE` PL/pgSQL functions (or generated columns);
3. replace FTS5 (`search_doc`) with `tsvector` + GIN and an Arabic configuration
   (or keep search in OpenSearch);
4. `app/repo.py` and `app/db.py` are the only modules that know about the driver — everything else
   speaks plain SQL.

## 8. The date-and-time model

A registry of historical records cannot store dates as timestamps: a birth year is often all that is
known, and `c. 1850` is a real, publishable value. SIRAJ therefore keeps dates as **text that carries
its own precision**, and adds time as an optional suffix:

| Shape | Meaning | Precise to |
|---|---|---|
| `1950` | the year | year |
| `1950-05` | the month | month |
| `1950-05-12` | the day | day |
| `1950-05-12T21:45` | a moment (also accepted as `1950-05-12 21:45`, `…:45`, with `Z`/`±hh:mm`) | minute |
| `c. 1850`, `1850s`, `1850?` | approximate / decade / uncertain — legacy research forms, preserved verbatim | year |

Accepted input is parsed by `schemas.parse_date_value()`, which never guesses: `1912-13`, `1912-02-31`,
`31/03/1991` and `25:00` are refused with a message that lists the accepted forms. The canonical value
is what gets stored (`1950-05-12 21:45` → `1950-05-12T21:45`); the UTC suffix is dropped because these
are wall-clock dates in the researcher's calendar, not events on a server.

* **Which fields ask for a time:** `schemas.TIME_AWARE_FIELDS` — `event.start_date/end_date`,
  `relationship.start_date/end_date/last_review_date`, `source.publication_date/access_date`. Every other date column
  still *accepts* a time through the API or an import; it simply does not prompt for one.
  `meta.fields[entity][key].time` tells any client which is which.
* **Comparison:** `ts_of()` (SQLite, registered per connection next to `norm()` and `year_of()`)
  expands missing parts downwards, so `1950 < 1950-03 < 1950-03-14 09:30` holds across mixed precision.
* **Preservation:** lowering the precision in the interface (`date + time` → `year`) truncates
  deliberately and is the only way a component of a stored date is ever lost. Editing an unrelated field
  never touches the date.
* **Migration:** none was required — the seed data contained only `YYYY` and `YYYY-MM-DD`, and the
  parser accepts the old shapes unchanged.
