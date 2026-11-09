-- Unit emblem: the unit's image, same contract as the registry's image_url
-- (shared imageEditor in the record form, /api/media upload, dossier hero).
ALTER TABLE military_unit ADD COLUMN image_url TEXT;
ALTER TABLE military_unit ADD COLUMN image_alt TEXT;
