-- ===========================================================================
-- 010 · Evidence links: one source, many claims
-- ===========================================================================
--
-- The supplied schema attached one primary source to each record and one entity
-- to each source. That cannot express a document that supports several people,
-- an institution and three relationships at once — and it cannot express
-- disagreement, because the second source overwrites the first.
--
-- `evidence` is the claim link: (source) → (entity | relationship | a field of
-- one), with the exact statement supported, where it appears in the source, the
-- type of support, and its own verification state. A source is stored once in
-- `source` and linked to every claim it supports.
--
-- `evidence` supersedes `source_link`, which is kept only so an old database
-- can be read by an old binary, every row is copied below.

CREATE TABLE IF NOT EXISTS evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    -- exactly one target: an entity, or a relationship row
    entity_type         TEXT,                 -- person|institution|place|event
    entity_id           INTEGER,
    relationship_id     INTEGER REFERENCES relationship(id) ON DELETE CASCADE,
    -- provenance at field level: 'birth_date' means this source supports that field
    field_key           TEXT,
    supported_claim     TEXT,                 -- the statement in the source, in the
                                              -- researcher's words (a quotation or a
                                              -- faithful paraphrase of one)
    page_or_timestamp   TEXT,                 -- page, folio, column, minute:second
    support_type        TEXT NOT NULL DEFAULT 'supports'
                        CHECK (support_type IN ('supports','contradicts','contextualizes')),
    verification_id     INTEGER REFERENCES lookup(id),   -- authentication_level domain
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

-- One source may not assert the same thing about the same target twice, but a
-- *contradiction* is a different claim and is allowed alongside a support.
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_entity
    ON evidence (source_id, entity_type, entity_id, IFNULL(field_key, ''), support_type)
    WHERE relationship_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_relationship
    ON evidence (source_id, relationship_id, IFNULL(field_key, ''), support_type)
    WHERE relationship_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_evidence_entity
    ON evidence (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_evidence_relationship
    ON evidence (relationship_id);
CREATE INDEX IF NOT EXISTS ix_evidence_source
    ON evidence (source_id);

-- ---- backfill 1: every legacy source_link row becomes a support claim -----
INSERT INTO evidence (source_id, entity_type, entity_id, field_key, supported_claim,
                      support_type, notes, created_at, created_by)
SELECT sl.source_id, sl.entity_type, sl.entity_id, sl.field_key,
       CASE WHEN sl.field_key IS NOT NULL
            THEN 'Supports the value recorded in ' || sl.field_key
            ELSE NULL END,
       'supports', sl.note, sl.created_at, NULL
FROM source_link sl
WHERE NOT EXISTS (
    SELECT 1 FROM evidence e
    WHERE e.source_id = sl.source_id
      AND e.relationship_id IS NULL
      AND e.entity_type = sl.entity_type
      AND e.entity_id = sl.entity_id
      AND IFNULL(e.field_key, '') = IFNULL(sl.field_key, '')
      AND e.support_type = 'supports');

-- ---- backfill 2: a relationship's primary source becomes a claim ----------
-- relationship.source_id stays as the *preferred* source, the evidence row is
-- what the diagram and the drawer read, so a relationship has an evidence list
-- like every other claim.
INSERT INTO evidence (source_id, relationship_id, supported_claim, support_type,
                      created_at, created_by)
SELECT r.source_id, r.id, NULL, 'supports', r.created_at, r.created_by
FROM relationship r
WHERE r.source_id IS NOT NULL
  AND r.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM evidence e
    WHERE e.relationship_id = r.id AND e.source_id = r.source_id
      AND e.support_type = 'supports');

-- ---- a lookup domain for the support type --------------------------------
INSERT OR IGNORE INTO lookup_domain (domain, label_en, label_ar, description_en,
                                     description_ar, sort_order, is_system)
VALUES ('evidence_support_type', 'Evidence support type', 'نوع الدعم في الدليل',
        'How a source bears on a claim: it supports the claim, contradicts it, or gives context without asserting it.',
        'كيف يتعامل المصدر مع الادعاء: يؤيده أو يناقضه أو يقدم سياقاً دون تأكيده.',
        95, 1);

INSERT OR IGNORE INTO lookup (domain, code, label_en, label_ar, sort_order, is_active, is_system)
VALUES ('evidence_support_type', 'supports', 'Supports', 'يؤيد', 10, 1, 1);

INSERT OR IGNORE INTO lookup (domain, code, label_en, label_ar, sort_order, is_active, is_system)
VALUES ('evidence_support_type', 'contradicts', 'Contradicts', 'يناقض', 20, 1, 1);

INSERT OR IGNORE INTO lookup (domain, code, label_en, label_ar, sort_order, is_active, is_system)
VALUES ('evidence_support_type', 'contextualizes', 'Gives context', 'يقدم سياقاً', 30, 1, 1);
