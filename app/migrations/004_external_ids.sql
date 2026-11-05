-- External / authority identifiers (VIAF, Wikidata, ORCID, library catalogue,
-- legacy numbers from a previous spreadsheet) kept separate from the registry code.
CREATE TABLE IF NOT EXISTS entity_external_id (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    scheme      TEXT NOT NULL,          -- viaf | wikidata | orcid | legacy | other
    value       TEXT NOT NULL,
    url         TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (entity_type, entity_id, scheme, value)
);
CREATE INDEX IF NOT EXISTS ix_extid_entity ON entity_external_id(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_extid_value ON entity_external_id(scheme, value);
