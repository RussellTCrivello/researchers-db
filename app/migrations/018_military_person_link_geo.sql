-- Commander ↔ individual link, and the unit's own geography.
--
-- person_id: a commander IS a person first. The commander record carries the
-- service side (rank, branch, commission, appointments); the linked person
-- record carries the individual's identity, life, relationships and geography.
-- The link is what lets the commander dossier encompass all of it.
--
-- latitude / longitude / geometry_source on military_unit and
-- operational_deployment mirror the registry's own-coordinate columns
-- (place/institution/person). The map shows a unit's OWN location — the same
-- rule the registry keeps ("every entity resolves to its OWN coordinates
-- first"): a commander's personal coordinates must never stand in for the
-- unit's.
ALTER TABLE commander ADD COLUMN person_id INTEGER REFERENCES person(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_commander_person ON commander(person_id);

ALTER TABLE military_unit ADD COLUMN latitude REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90));
ALTER TABLE military_unit ADD COLUMN longitude REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180));
ALTER TABLE military_unit ADD COLUMN geometry_source TEXT;
CREATE INDEX IF NOT EXISTS ix_military_unit_geo ON military_unit(latitude, longitude);

ALTER TABLE operational_deployment ADD COLUMN latitude REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90));
ALTER TABLE operational_deployment ADD COLUMN longitude REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180));
ALTER TABLE operational_deployment ADD COLUMN geometry_source TEXT;
CREATE INDEX IF NOT EXISTS ix_deployment_geo ON operational_deployment(latitude, longitude);
