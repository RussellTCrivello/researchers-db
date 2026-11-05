-- 008 · the typed settings registry
--
-- The application now declares every setting in app/settings.py (type, default,
-- allowed values, bilingual help, and the code path that honours it).  This
-- migration writes the defaults for the keys that were added with the registry,
-- so a database created by an earlier build lists the whole configuration in
-- `SELECT * FROM setting` and in /api/settings.
--
-- A row is an *override*: deleting it makes the declared default apply again
-- (POST /api/settings/reset does exactly that, and audits it).  INSERT OR IGNORE
-- keeps every value an operator has already chosen.

INSERT OR IGNORE INTO setting (key, value) VALUES ('display.theme', 'light');
INSERT OR IGNORE INTO setting (key, value) VALUES ('display.density', 'comfortable');
INSERT OR IGNORE INTO setting (key, value) VALUES ('display.page_size', '25');
INSERT OR IGNORE INTO setting (key, value) VALUES ('display.default_language', 'ar');
INSERT OR IGNORE INTO setting (key, value) VALUES ('ui.inline_create', 'true');
INSERT OR IGNORE INTO setting (key, value) VALUES ('search.min_chars', '2');
INSERT OR IGNORE INTO setting (key, value) VALUES ('search.results_limit', '20');
INSERT OR IGNORE INTO setting (key, value) VALUES ('import.default_mode', 'create');
INSERT OR IGNORE INTO setting (key, value) VALUES ('export.max_rows', '50000');
INSERT OR IGNORE INTO setting (key, value) VALUES ('validation.min_completeness', '0');
INSERT OR IGNORE INTO setting (key, value) VALUES ('validation.require_reason_for_delete', 'false');
INSERT OR IGNORE INTO setting (key, value) VALUES ('audit.retention_days', '0');
INSERT OR IGNORE INTO setting (key, value) VALUES ('maintenance.backup_includes_files', 'true');
INSERT OR IGNORE INTO setting (key, value) VALUES ('maintenance.vacuum_after_import', 'false');
