-- Where data-entry surfaces live: a full page or a dialog over the list it came
-- from.  Two keys, both instance-wide defaults that any user may override for
-- themselves in the interface (localStorage), because how someone likes to type
-- is a personal preference, not a policy.
INSERT OR IGNORE INTO setting (key, value) VALUES ('ui.form_mode', 'page');
INSERT OR IGNORE INTO setting (key, value) VALUES ('ui.form_dialog_size', 'xl');
