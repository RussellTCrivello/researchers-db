-- 016_geo_admin_chain — the six-level geographical chain reaches physical
-- locations.  place already links country_id / governorate_id / district_id
-- (012); the chain continues with municipality → village → community so a
-- physical location can be pinned at any administrative depth while the unit
-- hierarchy itself stays in `lookup`.  Additive: the migration runner applies
-- each file once and records it, so re-running is a no-op and existing data
-- is never touched.
ALTER TABLE place ADD COLUMN municipality_id INTEGER REFERENCES lookup(id);
ALTER TABLE place ADD COLUMN village_id INTEGER REFERENCES lookup(id);
ALTER TABLE place ADD COLUMN community_id INTEGER REFERENCES lookup(id);
CREATE INDEX IF NOT EXISTS ix_place_municipality ON place(municipality_id);
CREATE INDEX IF NOT EXISTS ix_place_village ON place(village_id);
CREATE INDEX IF NOT EXISTS ix_place_community ON place(community_id);

-- Deeper units are optional on a place (a country-level site needs no village),
-- but when present they must nest: village under municipality, community under
-- village.  The API enforces that on write; these indexes keep the cascade
-- lookups (children of a selected unit) fast at world scale.
CREATE INDEX IF NOT EXISTS ix_lookup_domain_parent ON lookup(domain, parent_id, sort_order);
