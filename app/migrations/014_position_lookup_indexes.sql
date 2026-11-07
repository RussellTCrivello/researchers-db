-- 014_position_lookup_indexes.sql — indexes for the own-position write paths.
--
-- 013 put per-record coordinates on person, institution and event. The map
-- queries (bbox filters in geo.mapdata.features) and the association walks
-- (birthplace_id, place_id) then read columns that only place had indexes on.
-- Add the matching lookups here — plain CREATE INDEX IF NOT EXISTS, the same
-- convention as 002 and the ix_place_geo line in schema.sql. No data changes.

CREATE INDEX IF NOT EXISTS ix_person_geo ON person(latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_institution_geo ON institution(latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_event_geo ON event(latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_person_birthplace ON person(birthplace_id);
CREATE INDEX IF NOT EXISTS ix_institution_place ON institution(place_id);
