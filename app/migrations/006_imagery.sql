-- Imagery for profile / card / gallery views: every entity that is presented as
-- a "profile" carries an image link plus alt text (accessibility + captions).
ALTER TABLE person ADD COLUMN image_alt TEXT;
ALTER TABLE institution ADD COLUMN image_url TEXT;
ALTER TABLE institution ADD COLUMN image_alt TEXT;
ALTER TABLE place ADD COLUMN image_url TEXT;
ALTER TABLE place ADD COLUMN image_alt TEXT;
ALTER TABLE event ADD COLUMN image_url TEXT;
ALTER TABLE event ADD COLUMN image_alt TEXT;
