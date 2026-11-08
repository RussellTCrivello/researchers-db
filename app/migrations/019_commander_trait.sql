-- Leadership qualities: the assessments that set a leader apart.
--
-- A commander is a person first (018), and their service record is facts.
-- Qualities are different in kind: they are JUDGMENTS, so each one carries
-- its basis — who assessed it, when, on what evidence — and lives in its own
-- auditable row rather than as an unexplained score on the commander record.
-- The vocabulary is data (lookup domains leadership_quality / leadership_level,
-- seeded by app.military.seed), not scattered literals.
CREATE TABLE IF NOT EXISTS commander_trait (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    commander_id  INTEGER NOT NULL REFERENCES commander(id) ON DELETE RESTRICT,
    quality       TEXT NOT NULL,
    level         TEXT,
    assessed_by   TEXT,
    assessed_at   TEXT,
    evidence_note TEXT,
    source        TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    modified_at   TEXT,
    modified_by   TEXT
);
CREATE INDEX IF NOT EXISTS ix_trait_commander ON commander_trait(commander_id);
CREATE INDEX IF NOT EXISTS ix_trait_quality ON commander_trait(quality);

-- The vocabulary is data, seeded here so the ledger path (every server start)
-- and the lazy path (app.military.dbm._ensure_trait_table) both converge on
-- the same bilingual rows. Codes are the readable labels assessment rows store.
INSERT INTO lookup_domain (domain, label_en, label_ar, sort_order, is_system)
SELECT 'leadership_quality', 'Leadership Quality', 'الصفة القيادية', 80, 1
WHERE NOT EXISTS (SELECT 1 FROM lookup_domain WHERE domain = 'leadership_quality');
INSERT INTO lookup_domain (domain, label_en, label_ar, sort_order, is_system)
SELECT 'leadership_level', 'Leadership Level', 'مستوى القيادة', 81, 1
WHERE NOT EXISTS (SELECT 1 FROM lookup_domain WHERE domain = 'leadership_level');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Decisiveness', 'Decisiveness', 'الحسم', 10, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Decisiveness');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Tactical Acumen', 'Tactical Acumen', 'البراعة التكتيكية', 20, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Tactical Acumen');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Strategic Vision', 'Strategic Vision', 'الرؤية الاستراتيجية', 30, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Strategic Vision');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Leadership Under Fire', 'Leadership Under Fire', 'القيادة تحت النار', 40, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Leadership Under Fire');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Discipline', 'Discipline', 'الانضباط', 50, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Discipline');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Initiative', 'Initiative', 'المبادرة', 60, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Initiative');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Resilience', 'Resilience', 'المرونة والصبر', 70, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Resilience');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Logistics Mastery', 'Logistics Mastery', 'إتقان الإمداد', 80, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Logistics Mastery');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Training & Development', 'Training & Development', 'التدريب والتطوير', 90, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Training & Development');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Coalition Building', 'Coalition Building', 'بناء التحالفات', 100, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Coalition Building');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Intelligence & Deception', 'Intelligence & Deception', 'الاستخبارات والخداع', 110, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Intelligence & Deception');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_quality', 'Communication', 'Communication', 'التواصل', 120, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_quality' AND code = 'Communication');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_level', 'Exceptional', 'Exceptional', 'استثنائي', 10, 'green', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_level' AND code = 'Exceptional');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_level', 'Outstanding', 'Outstanding', 'متميز', 20, 'blue', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_level' AND code = 'Outstanding');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_level', 'Proficient', 'Proficient', 'بارع', 30, 'slate', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_level' AND code = 'Proficient');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'leadership_level', 'Developing', 'Developing', 'قيد التطوير', 40, 'amber', 1, 0, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'leadership_level' AND code = 'Developing');
