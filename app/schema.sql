-- ============================================================================
--  SIRAJ · Research Registry Database  —  SQLite schema (v1.0)
--  Bilingual (AR/EN) registry of persons, places, institutions, events,
--  relationships and sources, with audit trail, import/export and reporting.
--
--  Conventions
--  -----------
--  * Every business entity has: id (surrogate PK) + code (stable human key),
--    record_status_id, authentication_id, primary_source_id, researcher_notes,
--    created_*/updated_* audit columns, deleted_at (soft delete), version.
--  * All controlled vocabularies live in one `lookup` table keyed by `domain`,
--    so new vocabularies never require a schema migration.
--  * Dates are ISO-ish text with an explicit precision flag, because historical
--    records frequently have "1876" or "c. 1876" rather than a full date.
--  * Text-to-text relations (place -> persons, institution -> partners ...)
--    are normalised into `relationship`, never stored as delimited ID lists.
--  * Timestamps are UTC ISO-8601 strings.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 0. Meta / infrastructure
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

-- Vocabulary domains. Describes the "help tables" themselves (self-describing
-- metadata: the admin UI can render labels and counts for each vocabulary).
CREATE TABLE IF NOT EXISTS lookup_domain (
    domain          TEXT PRIMARY KEY,
    label_en        TEXT NOT NULL,
    label_ar        TEXT NOT NULL,
    description_en  TEXT,
    description_ar  TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 100,
    is_system       INTEGER NOT NULL DEFAULT 0
);

-- Single controlled-vocabulary table for every "help table".
CREATE TABLE IF NOT EXISTS lookup (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL REFERENCES lookup_domain(domain) ON UPDATE CASCADE,
    code            TEXT NOT NULL,
    label_en        TEXT NOT NULL,
    label_ar        TEXT NOT NULL,
    description_en  TEXT,
    description_ar  TEXT,
    parent_id       INTEGER REFERENCES lookup(id) ON DELETE SET NULL,
    sort_order      INTEGER NOT NULL DEFAULT 100,
    color           TEXT,
    meta            TEXT,                       -- JSON blob (iso2/iso3/flag/…)
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_system       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (domain, code)
);
CREATE INDEX IF NOT EXISTS ix_lookup_domain ON lookup(domain, sort_order, id);
CREATE INDEX IF NOT EXISTS ix_lookup_parent ON lookup(parent_id);

-- UI languages. Adding a row + a locale JSON file adds a language (see docs).
CREATE TABLE IF NOT EXISTS locale (
    code        TEXT PRIMARY KEY,               -- BCP-47, e.g. en, ar, fr, tr
    name_en     TEXT NOT NULL,
    name_native TEXT NOT NULL,
    dir         TEXT NOT NULL DEFAULT 'ltr' CHECK (dir IN ('ltr','rtl')),
    is_active   INTEGER NOT NULL DEFAULT 1,
    is_default  INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 100
);

-- Application users (actors for the audit trail / reviewer fields).
CREATE TABLE IF NOT EXISTS app_user (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email        TEXT,
    role         TEXT NOT NULL DEFAULT 'researcher'
                 CHECK (role IN ('viewer','researcher','reviewer','admin')),
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Generic key/value settings (numbering defaults, display defaults, etc.)
CREATE TABLE IF NOT EXISTS setting (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ---------------------------------------------------------------------------
-- 1. Sources (referenced by everything, so created early)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    code                  TEXT NOT NULL UNIQUE,
    title                 TEXT NOT NULL,           -- Source Name / Title
    title_ar              TEXT,
    source_type_id        INTEGER REFERENCES lookup(id),
    publisher             TEXT,
    url                   TEXT,
    publication_date      TEXT,
    publication_precision TEXT,
    access_date           TEXT,
    supported_information TEXT,                    -- what claim this source backs
    entity_type           TEXT,                    -- legacy single link (kept for
    entity_id             INTEGER,                 -- 1:1 citations; see source_link)
    reliability_id        INTEGER REFERENCES lookup(id),
    verification_notes    TEXT,
    record_status_id      INTEGER REFERENCES lookup(id),
    authentication_id     INTEGER REFERENCES lookup(id),
    language              TEXT,
    isbn_issn             TEXT,
    archive_reference     TEXT,
    researcher_notes      TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by            TEXT,
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by            TEXT,
    deleted_at            TEXT,
    version               INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_source_type ON source(source_type_id);
CREATE INDEX IF NOT EXISTS ix_source_status ON source(record_status_id);
CREATE INDEX IF NOT EXISTS ix_source_entity ON source(entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- 2. Places
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS place (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    image_url                TEXT,
    image_alt                TEXT,
    code                   TEXT NOT NULL UNIQUE,
    name_ar                TEXT,
    name_original          TEXT,
    name_en                TEXT,
    name_original_lang     TEXT,
    place_type_id          INTEGER REFERENCES lookup(id),
    country_id             INTEGER REFERENCES lookup(id),   -- lookup domain 'country'
    region                 TEXT,                            -- legacy free-text governorate
    governorate_id         INTEGER REFERENCES lookup(id),   -- lookup domain 'governorate'
    city                   TEXT,
    district               TEXT,                            -- legacy free-text district
    district_id            INTEGER REFERENCES lookup(id),   -- lookup domain 'district'
    latitude               REAL CHECK (latitude  IS NULL OR (latitude  BETWEEN -90  AND 90)),
    longitude              REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    geo_precision          TEXT,                            -- exact/approx/centroid
    geocoding_method       TEXT,                            -- how the point was obtained
    geo_uncertainty_m      REAL,                            -- radius of the doubt, metres
    geometry_source        TEXT,                            -- which map/source supplied it
    parent_place_id        INTEGER REFERENCES place(id) ON DELETE SET NULL,
    geo_description        TEXT,
    research_significance  TEXT,
    primary_source_id      INTEGER REFERENCES source(id) ON DELETE SET NULL,
    documentation_id       INTEGER REFERENCES lookup(id),
    authentication_id      INTEGER REFERENCES lookup(id),
    record_status_id       INTEGER REFERENCES lookup(id),
    researcher_notes       TEXT,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by             TEXT,
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by             TEXT,
    deleted_at             TEXT,
    version                INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_place_country ON place(country_id);
CREATE INDEX IF NOT EXISTS ix_place_type ON place(place_type_id);
CREATE INDEX IF NOT EXISTS ix_place_status ON place(record_status_id);
CREATE INDEX IF NOT EXISTS ix_place_geo ON place(latitude, longitude);

-- ---------------------------------------------------------------------------
-- 3. Institutions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS institution (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    image_url                TEXT,
    image_alt                TEXT,
    code                   TEXT NOT NULL UNIQUE,
    name_ar                TEXT,
    name_original          TEXT,
    name_en                TEXT,
    name_original_lang     TEXT,
    abbreviation           TEXT,
    institution_type_id    INTEGER REFERENCES lookup(id),
    subcategory_id         INTEGER REFERENCES lookup(id),
    founded_date           TEXT,
    founded_precision      TEXT,
    closed_date            TEXT,
    country_id             INTEGER REFERENCES lookup(id),
    city                   TEXT,
    place_id               INTEGER REFERENCES place(id) ON DELETE SET NULL,
    address                TEXT,
    -- own position — recorded for the institution alone, never inherited
    -- from the linked place
    latitude               REAL CHECK (latitude  IS NULL OR (latitude  BETWEEN -90  AND 90)),
    longitude              REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    geo_precision          TEXT,
    geocoding_method       TEXT,
    geo_uncertainty_m      REAL,
    geometry_source        TEXT,
    current_leadership     TEXT,
    founders_text          TEXT,
    objectives             TEXT,
    org_structure          TEXT,
    governance_id          INTEGER REFERENCES lookup(id),
    website                TEXT,
    official_accounts      TEXT,
    research_significance  TEXT,
    primary_source_id      INTEGER REFERENCES source(id) ON DELETE SET NULL,
    documentation_id       INTEGER REFERENCES lookup(id),
    authentication_id      INTEGER REFERENCES lookup(id),
    record_status_id       INTEGER REFERENCES lookup(id),
    researcher_notes       TEXT,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by             TEXT,
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by             TEXT,
    deleted_at             TEXT,
    version                INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_inst_type ON institution(institution_type_id);
CREATE INDEX IF NOT EXISTS ix_inst_country ON institution(country_id);
CREATE INDEX IF NOT EXISTS ix_inst_status ON institution(record_status_id);
CREATE INDEX IF NOT EXISTS ix_institution_geo ON institution(latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_institution_place ON institution(place_id);

-- ---------------------------------------------------------------------------
-- 4. Persons
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    code                     TEXT NOT NULL UNIQUE,
    name_ar                  TEXT,
    name_original            TEXT,
    name_en                  TEXT,
    name_original_lang       TEXT,
    name_transliteration     TEXT,
    image_url                TEXT,
    image_alt                TEXT,
    birth_date               TEXT,
    birth_precision          TEXT,
    death_date               TEXT,
    death_precision          TEXT,
    nationality_id           INTEGER REFERENCES lookup(id),
    birthplace_id            INTEGER REFERENCES place(id) ON DELETE SET NULL,
    birthplace_text          TEXT,
    classification_id        INTEGER REFERENCES lookup(id),
    current_status_id        INTEGER REFERENCES lookup(id),  -- alive/deceased/unknown
    current_position         TEXT,
    affiliated_institution_id INTEGER REFERENCES institution(id) ON DELETE SET NULL,
    affiliated_country_id    INTEGER REFERENCES lookup(id),
    declared_affiliation     TEXT,
    cv_url                   TEXT,
    public_activity          TEXT,
    affiliation_verified     INTEGER NOT NULL DEFAULT 0,
    affiliation_start        TEXT,
    affiliation_end          TEXT,
    institutional_relations  TEXT,
    website                  TEXT,
    social_accounts          TEXT,
    -- own position — recorded for the person alone, never inherited from
    -- a linked place (linking is association, not assignment)
    latitude                 REAL CHECK (latitude  IS NULL OR (latitude  BETWEEN -90  AND 90)),
    longitude                REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    geo_precision            TEXT,
    geocoding_method         TEXT,
    geo_uncertainty_m        REAL,
    geometry_source          TEXT,
    primary_source_id        INTEGER REFERENCES source(id) ON DELETE SET NULL,
    documentation_id         INTEGER REFERENCES lookup(id),
    authentication_id        INTEGER REFERENCES lookup(id),
    record_status_id         INTEGER REFERENCES lookup(id),
    researcher_notes         TEXT,
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by               TEXT,
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by               TEXT,
    deleted_at               TEXT,
    version                  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_person_inst ON person(affiliated_institution_id);
CREATE INDEX IF NOT EXISTS ix_person_class ON person(classification_id);
CREATE INDEX IF NOT EXISTS ix_person_nat ON person(nationality_id);
CREATE INDEX IF NOT EXISTS ix_person_status ON person(record_status_id);
CREATE INDEX IF NOT EXISTS ix_person_birth ON person(birth_date);
CREATE INDEX IF NOT EXISTS ix_person_geo ON person(latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_person_birthplace ON person(birthplace_id);

-- "Previous Positions" as a repeating child table (1 person -> N positions).
CREATE TABLE IF NOT EXISTS person_position (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id         INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    title_ar          TEXT,
    title_en          TEXT,
    institution_id    INTEGER REFERENCES institution(id) ON DELETE SET NULL,
    institution_text  TEXT,
    country_id        INTEGER REFERENCES lookup(id),
    place_id          INTEGER REFERENCES place(id) ON DELETE SET NULL,
    start_date        TEXT,
    end_date          TEXT,
    start_precision   TEXT,
    end_precision     TEXT,
    is_current        INTEGER NOT NULL DEFAULT 0,
    sort_order        INTEGER NOT NULL DEFAULT 100,
    notes             TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_pperson ON person_position(person_id, sort_order);
CREATE INDEX IF NOT EXISTS ix_pinst ON person_position(institution_id);

-- ---------------------------------------------------------------------------
-- 5. Events (referenced by lookup domain 'event_type')
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    image_url                TEXT,
    image_alt                TEXT,
    code               TEXT NOT NULL UNIQUE,
    title_ar           TEXT,
    title_en           TEXT,
    event_type_id      INTEGER REFERENCES lookup(id),
    start_date         TEXT,
    start_precision    TEXT,
    end_date           TEXT,
    place_id           INTEGER REFERENCES place(id) ON DELETE SET NULL,
    -- own position — the venue point, independent of the person and the place
    latitude           REAL CHECK (latitude  IS NULL OR (latitude  BETWEEN -90  AND 90)),
    longitude          REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    geo_precision      TEXT,
    geocoding_method   TEXT,
    geo_uncertainty_m  REAL,
    geometry_source    TEXT,
    description        TEXT,
    significance       TEXT,
    primary_source_id  INTEGER REFERENCES source(id) ON DELETE SET NULL,
    documentation_id   INTEGER REFERENCES lookup(id),
    authentication_id  INTEGER REFERENCES lookup(id),
    record_status_id   INTEGER REFERENCES lookup(id),
    researcher_notes   TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by         TEXT,
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by         TEXT,
    deleted_at         TEXT,
    version            INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_event_type ON event(event_type_id);
CREATE INDEX IF NOT EXISTS ix_event_place ON event(place_id);
CREATE INDEX IF NOT EXISTS ix_event_geo ON event(latitude, longitude);

-- ---------------------------------------------------------------------------
-- 6. Relationships (the graph between any two entities)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationship (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT NOT NULL UNIQUE,
    entity1_type        TEXT NOT NULL,      -- person | place | institution | event
    entity1_id          INTEGER NOT NULL,
    entity1_name        TEXT,               -- snapshot for resilient display
    entity2_type        TEXT NOT NULL,
    entity2_id          INTEGER NOT NULL,
    entity2_name        TEXT,
    relationship_type_id INTEGER REFERENCES lookup(id),
    direction           TEXT NOT NULL DEFAULT 'directed'
                        CHECK (direction IN ('directed','symmetric')),
    description         TEXT,
    start_date          TEXT,
    end_date            TEXT,
    start_precision     TEXT,
    end_precision       TEXT,
    is_current          INTEGER NOT NULL DEFAULT 0,
    source_id           INTEGER REFERENCES source(id) ON DELETE SET NULL,
    authentication_id   INTEGER REFERENCES lookup(id),
    record_status_id    INTEGER REFERENCES lookup(id),
    last_review_date    TEXT,
    researcher_notes    TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by          TEXT,
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by          TEXT,
    deleted_at          TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    UNIQUE (entity1_type, entity1_id, relationship_type_id, entity2_type, entity2_id)
);
CREATE INDEX IF NOT EXISTS ix_rel_e1 ON relationship(entity1_type, entity1_id);
CREATE INDEX IF NOT EXISTS ix_rel_e2 ON relationship(entity2_type, entity2_id);
CREATE INDEX IF NOT EXISTS ix_rel_type ON relationship(relationship_type_id);
CREATE INDEX IF NOT EXISTS ix_rel_status ON relationship(record_status_id);

-- ---------------------------------------------------------------------------
-- 7. Tags (specialisations / areas of expertise / free keywords)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tag (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    domain     TEXT NOT NULL,               -- specialization | expertise | keyword
    label_en   TEXT NOT NULL,
    label_ar   TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (domain, label_en)
);
CREATE TABLE IF NOT EXISTS entity_tag (
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    tag_id      INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (entity_type, entity_id, tag_id)
);
CREATE INDEX IF NOT EXISTS ix_etag_tag ON entity_tag(tag_id);

-- ---------------------------------------------------------------------------
-- 8. Many-to-many source citations (one source may back many records)
-- ---------------------------------------------------------------------------
-- Evidence links: one source, many claims (see migrations/010).
-- A claim is about an entity, one field of an entity, or a relationship row.
CREATE TABLE IF NOT EXISTS evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    entity_type         TEXT,
    entity_id           INTEGER,
    relationship_id     INTEGER REFERENCES relationship(id) ON DELETE CASCADE,
    field_key           TEXT,
    supported_claim     TEXT,
    page_or_timestamp   TEXT,
    support_type        TEXT NOT NULL DEFAULT 'supports'
                        CHECK (support_type IN ('supports','contradicts','contextualizes')),
    verification_id     INTEGER REFERENCES lookup(id),
    reviewer            TEXT,
    review_date         TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by          TEXT,
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by          TEXT,
    CHECK ((relationship_id IS NULL AND entity_type IS NOT NULL AND entity_id IS NOT NULL)
        OR (relationship_id IS NOT NULL AND entity_id IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_entity
    ON evidence (source_id, entity_type, entity_id, IFNULL(field_key, ''), support_type)
    WHERE relationship_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_relationship
    ON evidence (source_id, relationship_id, IFNULL(field_key, ''), support_type)
    WHERE relationship_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_evidence_entity ON evidence (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_evidence_relationship ON evidence (relationship_id);
CREATE INDEX IF NOT EXISTS ix_evidence_source ON evidence (source_id);

CREATE TABLE IF NOT EXISTS source_link (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    field_key   TEXT,                    -- optional: which field it supports
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (source_id, entity_type, entity_id, field_key)
);
CREATE INDEX IF NOT EXISTS ix_slink_entity ON source_link(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_slink_source ON source_link(source_id);

-- ---------------------------------------------------------------------------
-- 9. Attachments (CVs, scans, images) — stored under app/data/uploads
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attachment (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    entity_id    INTEGER NOT NULL,
    filename     TEXT NOT NULL,       -- original name
    stored_name  TEXT NOT NULL,       -- on-disk name
    mime         TEXT,
    size_bytes   INTEGER,
    kind         TEXT,                -- cv | image | scan | other
    note         TEXT,
    uploaded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    uploaded_by  TEXT
);
CREATE INDEX IF NOT EXISTS ix_att_entity ON attachment(entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- 9b. External / authority identifiers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_external_id (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    scheme      TEXT NOT NULL,
    value       TEXT NOT NULL,
    url         TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (entity_type, entity_id, scheme, value)
);
CREATE INDEX IF NOT EXISTS ix_extid_entity ON entity_external_id(entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- 10. Audit trail: field-level change log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS change_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id         TEXT,                    -- groups all rows of one transaction
    entity_type   TEXT NOT NULL,
    entity_id     INTEGER,
    entity_code   TEXT,
    action        TEXT NOT NULL            -- create | update | delete | restore
                  CHECK (action IN ('create','update','delete','restore','import','bulk')),
    field_key     TEXT,
    field_label   TEXT,
    old_value     TEXT,
    new_value     TEXT,
    reason        TEXT,
    source_id     INTEGER REFERENCES source(id) ON DELETE SET NULL,
    actor         TEXT,                    -- researcher / reviewer username
    reviewed_by   TEXT,
    notes         TEXT,
    changed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_chlog_entity ON change_log(entity_type, entity_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS ix_chlog_time ON change_log(changed_at DESC);
CREATE INDEX IF NOT EXISTS ix_chlog_actor ON change_log(actor);

-- ---------------------------------------------------------------------------
-- 11. Numbering control
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sequence (
    entity_type  TEXT PRIMARY KEY,
    prefix       TEXT NOT NULL DEFAULT '',
    separator    TEXT NOT NULL DEFAULT '-',
    suffix       TEXT NOT NULL DEFAULT '',
    padding      INTEGER NOT NULL DEFAULT 4,
    next_value   INTEGER NOT NULL DEFAULT 1,
    template     TEXT,                     -- e.g. {prefix}{sep}{number}{suffix}
    reset_policy TEXT NOT NULL DEFAULT 'never'
                 CHECK (reset_policy IN ('never','yearly','monthly')),
    last_reset   TEXT,
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_by   TEXT
);

-- ---------------------------------------------------------------------------
-- 12. Saved views / filter presets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_view (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    filters     TEXT NOT NULL,          -- JSON
    columns     TEXT,                   -- JSON array of visible columns
    sort        TEXT,                   -- JSON
    is_shared   INTEGER NOT NULL DEFAULT 1,
    owner       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (name, entity_type)
);

-- ---------------------------------------------------------------------------
-- 13. Import jobs (traceability for every batch load)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_job (
    id           TEXT PRIMARY KEY,      -- uuid
    entity_type  TEXT NOT NULL,
    filename     TEXT,
    format       TEXT,
    mode         TEXT,                  -- create | upsert | update_only
    dry_run      INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'running',
    total_rows   INTEGER NOT NULL DEFAULT 0,
    created_rows INTEGER NOT NULL DEFAULT 0,
    updated_rows INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows  INTEGER NOT NULL DEFAULT 0,
    mapping      TEXT,                  -- JSON resolved column->field map
    report       TEXT,                  -- JSON per-row errors
    actor        TEXT,
    started_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_import_started ON import_job(started_at DESC);

-- ---------------------------------------------------------------------------
-- 14. Full-text search index (Arabic-aware normalised shadow column)
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS search_doc USING fts5(
    entity_type UNINDEXED,
    entity_id   UNINDEXED,
    code        UNINDEXED,
    title,
    body,
    norm,
    tokenize = "unicode61 remove_diacritics 2"
);

-- ---------------------------------------------------------------------------
-- 15. Convenience views (read-only projections used by reports)
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_person_full AS
SELECT p.*,
       inst.name_en  AS affiliated_institution_en,
       inst.name_ar  AS affiliated_institution_ar,
       pl.name_en    AS birthplace_en,
       pl.name_ar    AS birthplace_ar,
       rs.code       AS status_code,
       rs.label_en   AS status_en,
       rs.label_ar   AS status_ar,
       al.code       AS auth_code,
       al.label_en   AS auth_en,
       al.label_ar   AS auth_ar
FROM person p
LEFT JOIN institution inst ON inst.id = p.affiliated_institution_id
LEFT JOIN place       pl   ON pl.id   = p.birthplace_id
LEFT JOIN lookup      rs   ON rs.id   = p.record_status_id
LEFT JOIN lookup      al   ON al.id   = p.authentication_id;

CREATE VIEW IF NOT EXISTS v_relationship_full AS
SELECT r.*, rt.label_en AS type_en, rt.label_ar AS type_ar, rt.code AS type_code,
       rs.code AS status_code, s.title AS source_title
FROM relationship r
LEFT JOIN lookup rt ON rt.id = r.relationship_type_id
LEFT JOIN lookup rs ON rs.id = r.record_status_id
LEFT JOIN source s  ON s.id  = r.source_id;
