-- Places form a hierarchy (country -> governorate -> city -> quarter/site).
-- Adds a self-reference so a place can sit inside another place.
ALTER TABLE place ADD COLUMN parent_place_id INTEGER REFERENCES place(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_place_parent ON place(parent_place_id);
