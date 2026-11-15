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

  Military Organization (migrations 015–020): region · division · military_unit ·
           classification · armament · unit_armament · operational_deployment ·
           mission · training · command_assignment · person_trait · note
           (see §3 below)
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
| `person` | individuals | `name_ar`, `name_en`, `name_original`(+`_lang`), `name_transliteration`, `birth_date`(+`_precision`), `death_date`(+`_precision`), `nationality_id`, `birthplace_id`, `birthplace_text`, `classification_id`, `current_status_id`, `current_position`, `affiliated_institution_id`, `affiliated_country_id`, `declared_affiliation`, `affiliation_verified/start/end`, `cv_url`, `public_activity`, `institutional_relations`, `website`, `social_accounts`, `primary_source_id`, `documentation_id`, `authentication_id`, `record_status_id`, `researcher_notes`, **`category`** (military / civilian / other, migration `020`) and — for a military person — `rank_title`, `branch`, `commission_date`, `service_status`, `military_biography` (category-conditional fields; the Leader is a categorized person) |
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

### Military Organization tables (migrations 015–020)

The Brigade Command module ([MILITARY_ORG.md](MILITARY_ORG.md) has the full field-by-field
data dictionary) adds its own tables beside the registry ones and never touches registry
rows. `015` lays the core schema, `017` adds the unit emblem, `018` links commanders to
persons and gives units their **own** geography, `019` adds leadership assessments, and
`020` folds the Leader table into categorized persons:

| Table | Purpose | Notable columns |
|---|---|---|
`region` · `division` | the command-region tree and its divisions | `parent_id`, `path`, `depth` on region; `region_id` on division |
`military_unit` | the force tree | `parent_id`, `path`, `depth`; `commander_id` → `person` and `current_deployment_id` → `operational_deployment` (service-synced pointers, never client-set); `direct_personnel` (the only entered strength — subtree strength is computed); `latitude`, `longitude`, `geometry_source` — the unit's **own** location, never its commander's (migration `018`); `image_url`, `image_alt` — the unit emblem (migration `017`) |
`classification` | equipment/holding classification (flat) | `category` (`Combat · Support · Reserve · Training`), `readiness_tier` |
`armament` · `unit_armament` | armaments and where they are held | the bridge carries `quantity`, `condition`, `acquisition_year` |
`operational_deployment` | deployments | `is_current` (one per unit, pointer-synced to `military_unit.current_deployment_id`); `latitude`, `longitude`, `geometry_source` — its own location (migration `018`) |
`mission` · `training` | missions and exercises | training `participant_count` is checked against **computed** subtree personnel |
`command_assignment` | command appointments (current + historic) | `commander_id` → `person` (a military-category person); overlap refused; `assigned_date`, `relieved_date`, `is_current` |
`person_trait` | assessed leadership qualities (migrations `019` → `020`) | `person_id` → `person`; `quality`/`level` vocabularies; each row is a **judgment** carrying its basis — `assessed_by`/`evidence_note`/`source` (at least one required) and `assessed_at` — never an unexplained score |
`note` | polymorphic notes on any military record or person | `entity_type`, `target_id` (allowlisted), `note_text`, `author`, `note_at` |
`naming_series_option` · `naming_counter` · `naming_adjustment_log` · `mil_meta` | the naming-series engine | 19 series options with year/category partitions, per-partition counters, audited counter adjustments, and the module's marker metadata |
`audit_log` | the module's append-only audit trail (shared table) | `actor`, `action`, `old_json`, `new_json` |

Migration `020` also gave `person` its `category` (see *Core entities* above) and
re-pointed every `commander_id` at `person(id)`, folding the former `commander` table in
with no data loss.

### Views
`v_person_full` (person + institution/place/status/auth labels), `v_relationship_full`
(relationship + type/status/source labels) — convenience projections for reports and exports.

## 4. Vocabulary domains (33)

`record_status` · `authentication_level` · `documentation_level` · `entity_type` ·
`country` · `governorate` · `district` · `municipality` · `village` · `person_category` ·
`person_classification` · `military_service_status` · `community` · `military_branch` ·
`person_status` · `place_type` · `leadership_quality` · `institution_type` ·
`leadership_level` · `institution_subcategory` · `relationship_type` (with
inverse/symmetric metadata) · `evidence_support_type` · `relation_direction` ·
`source_type` · `source_reliability` · `external_party_type` · `event_type` ·
`governance_system` · `indicator_area` · `date_precision` · `geo_precision` ·
`geocoding_method` · `language`

The `country`, `governorate`, `district`, `municipality` and `village` domains carry the
geo-reference vocabulary (thousands of values in a seeded database); the rest are small
controlled lists. `leadership_quality` / `leadership_level` serve the Military Organization's
assessments. Add a value at **Administration → Vocabularies** (or `POST /api/lookups`); no
migration needed.

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

## 9. Positions are per-record

**A record's coordinates belong to the record, never to a place it is associated
with.** Linking a person to Amsterdam is an association; it does not assign
Amsterdam's coordinates to the person. Several persons linked to one place hold
several distinct points, and none of them moves the place.

* **Columns.** `person`, `institution`, `event` and `place` each carry their own
  `latitude`, `longitude`, `geo_precision`, `geocoding_method`,
  `geo_uncertainty_m` and `geometry_source` (migration `013` added them to the
  first three; `place` has carried them since the base schema and `011`).
  A coordinate pair is only ever written to the record it describes —
  never onto a linked place, and never through a synthetic coordinate-named
  place (that behaviour was removed with `013`, which lifts any such historical
  points back onto their records and retires the synthetic places).
* **Association is not a position.** Foreign keys (`birthplace_id`,
  `affiliated_institution_id`, `place_id`, `parent_place_id`) name places; they
  are never repurposed to store a point. An entity may be linked to a place
  that has no coordinates at all — the link stays valid, and the entity keeps
  its own coordinates (or none).
* **Resolution** (`app/geo/mapdata.py` is the only authority): a record is
  plotted at **its own** coordinates; such a point is classed `precise`. A
  record with no coordinates of its own may still be *shown* at the place it is
  linked to — classed `associated`, visually distinct, labelled as the
  associated place, never presented as the record's own position. A record with
  neither is `unlocated`: counted, never drawn at a made-up place.
* **Provenance.** How a point was obtained is stored with it (`geocoding_method`
  — manual, typed, map pick — plus `geo_precision` and the uncertainty radius);
  `app/crce.py` renders the same distinction on the research dossiers
  (`inherited` ⇔ associated).
* **Discovery** (`mapdata.network()` / `GET /api/map/network`): selecting a
  record returns every geographical point connected to it through the
  registry's own links — foreign-key associations and relationship rows in both
  directions — breadth-first, bounded by depth (1–3) and a point budget. Each
  point keeps its identity and carries `via`: the link that brought it there,
  naming the intermediate record for indirect hops. No point is ever merged
  with another because of a shared name, city, or similar coordinates.
