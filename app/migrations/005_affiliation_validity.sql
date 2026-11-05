-- Declared vs verified affiliation, with an optional validity window, so that a
-- person's institutional home can change over time without losing history.
ALTER TABLE person ADD COLUMN affiliation_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE person ADD COLUMN affiliation_start TEXT;
ALTER TABLE person ADD COLUMN affiliation_end TEXT;
