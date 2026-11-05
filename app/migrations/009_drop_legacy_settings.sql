-- 009 · remove settings that no code path reads
--
-- The phase-6 settings screen wrote every key it had ever seen back to the
-- database, so a key that had been replaced kept a row behind even though
-- nothing reads it (`ui.autosave_drafts`, superseded by `ui.inline_create`).
-- The registry in app/settings.py is now the only list of settings that exist,
-- `PUT /api/settings` refuses an unknown key, and `settings.ensure()` seeds a
-- default only for declared keys — so this row can never come back.
--
-- A row is only an override. Deleting one is therefore safe — an undeclared key has no
-- consumer and no declared default, so nothing changes except what
-- `SELECT * FROM setting` shows an operator.

DELETE FROM setting WHERE key NOT IN (
    'display.theme', 'display.density', 'display.page_size', 'display.default_language',
    'ui.form_mode', 'ui.form_dialog_size', 'ui.inline_create',
    'search.min_chars', 'search.results_limit',
    'import.max_rows', 'import.default_mode', 'export.max_rows',
    'validation.require_source_on_publish', 'validation.min_completeness',
    'validation.require_reason_for_delete',
    'audit.retention_days',
    'maintenance.backup_includes_files', 'maintenance.vacuum_after_import'
);
