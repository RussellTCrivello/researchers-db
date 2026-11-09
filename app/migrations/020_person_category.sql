-- 020: the Leader becomes a categorized Person.
--
-- The separate commander ("Leader") table is removed.  A person record now
-- carries a CATEGORY (military / civilian / other — an owner-reviewable
-- vocabulary) and, when the category is 'military', the military-specific
-- attributes: rank, branch, commission date, service status and biography.
-- Each category shows the attributes relevant to that classification; the
-- military ones are exactly what the commander record used to hold.
--
-- Every military reference to a commander now points at a person —
-- a commander IS a person (018 linked them; this folds them):
--   military_unit.commander_id       -> person(id)
--   command_assignment.commander_id  -> person(id)
--   commander_trait                  -> person_trait(person_id -> person(id))
--
-- No data is lost: every commander row becomes (or merges into) a person
-- row with category='military' and its service attributes.  Table swaps use
-- stash + DROP + CREATE under the same name (never RENAME — a rename would
-- rewrite every child's REFERENCES clause to the temporary name).  The
-- runner commits around PRAGMA statements so foreign_keys=OFF is effective.

PRAGMA foreign_keys=OFF;

-- 1. person gains category + the military attributes ---------------------
ALTER TABLE person ADD COLUMN category TEXT;
ALTER TABLE person ADD COLUMN rank_title TEXT;
ALTER TABLE person ADD COLUMN branch TEXT;
ALTER TABLE person ADD COLUMN commission_date TEXT;
ALTER TABLE person ADD COLUMN service_status TEXT;
ALTER TABLE person ADD COLUMN military_biography TEXT;
CREATE INDEX IF NOT EXISTS ix_person_category ON person(category);

-- 2. the category + military vocabularies --------------------------------
-- Seeded here (the ledger path) AND in app/military/seed.py's lazy path so
-- both converge on the same bilingual rows.  Codes are the readable labels
-- the person rows store.
INSERT INTO lookup_domain (domain, label_en, label_ar, sort_order, is_system)
SELECT 'person_category', 'Person category', 'فئة الشخص', 60, 1
WHERE NOT EXISTS (SELECT 1 FROM lookup_domain WHERE domain = 'person_category');
INSERT INTO lookup_domain (domain, label_en, label_ar, sort_order, is_system)
SELECT 'military_service_status', 'Service status', 'حالة الخدمة', 61, 1
WHERE NOT EXISTS (SELECT 1 FROM lookup_domain WHERE domain = 'military_service_status');
INSERT INTO lookup_domain (domain, label_en, label_ar, sort_order, is_system)
SELECT 'military_branch', 'Service branch', 'السلاح', 62, 1
WHERE NOT EXISTS (SELECT 1 FROM lookup_domain WHERE domain = 'military_branch');

INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'person_category', 'military', 'Military', 'عسكري', 10, 'green', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'person_category' AND code = 'military');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'person_category', 'civilian', 'Civilian', 'مدني', 20, 'blue', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'person_category' AND code = 'civilian');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'person_category', 'other', 'Other', 'آخر', 30, 'slate', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'person_category' AND code = 'other');

INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_service_status', 'Active', 'Active', 'على قيد الخدمة', 10, 'green', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_service_status' AND code = 'Active');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_service_status', 'Reserve', 'Reserve', 'احتياط', 20, 'slate', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_service_status' AND code = 'Reserve');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_service_status', 'Retired', 'Retired', 'متقاعد', 30, 'gray', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_service_status' AND code = 'Retired');

INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_branch', 'Army', 'Army', 'القوات البرية', 10, 'green', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_branch' AND code = 'Army');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_branch', 'Navy', 'Navy', 'القوات البحرية', 20, 'blue', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_branch' AND code = 'Navy');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_branch', 'Air Force', 'Air Force', 'القوات الجوية', 30, 'blue', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_branch' AND code = 'Air Force');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_branch', 'Joint', 'Joint', 'مشترك', 40, 'slate', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_branch' AND code = 'Joint');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_branch', 'Gendarmerie', 'Gendarmerie', 'الدرك', 50, 'amber', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_branch' AND code = 'Gendarmerie');
INSERT INTO lookup (domain, code, label_en, label_ar, sort_order, color, is_active, is_system, created_at, updated_at)
SELECT 'military_branch', 'Coast Guard', 'Coast Guard', 'حرس السواحل', 60, 'amber', 1, 1, datetime('now'), datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM lookup WHERE domain = 'military_branch' AND code = 'Coast Guard');

-- 3. fold commander rows into person -------------------------------------
CREATE TEMP TABLE _cmd_map (commander_id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL);
INSERT INTO _cmd_map (commander_id, person_id)
SELECT id, person_id FROM commander WHERE person_id IS NOT NULL;

-- commanders without a linked individual: their own identity becomes the
-- person row (data preservation — the same human, moved, never invented)
INSERT INTO person (code, name_ar, name_en, category, rank_title, branch,
                    commission_date, service_status, military_biography,
                    created_at, created_by, updated_at, updated_by)
SELECT c.docname, c.full_name, c.full_name, 'military', c.rank_title, c.branch,
       c.commission_date, c.status, c.biography, c.created_at, c.created_by,
       COALESCE(c.modified_at, c.created_at), c.modified_by
FROM commander c WHERE c.person_id IS NULL;
INSERT INTO _cmd_map (commander_id, person_id)
SELECT c.id, p.id FROM commander c JOIN person p ON p.code = c.docname
WHERE c.person_id IS NULL;

-- linked commanders copy their service attributes onto the person (the
-- fresh columns are empty, so nothing is overwritten)
UPDATE person SET
    category = 'military',
    rank_title = (SELECT c.rank_title FROM commander c JOIN _cmd_map m ON m.commander_id = c.id WHERE m.person_id = person.id),
    branch = (SELECT c.branch FROM commander c JOIN _cmd_map m ON m.commander_id = c.id WHERE m.person_id = person.id),
    commission_date = (SELECT c.commission_date FROM commander c JOIN _cmd_map m ON m.commander_id = c.id WHERE m.person_id = person.id),
    service_status = (SELECT c.status FROM commander c JOIN _cmd_map m ON m.commander_id = c.id WHERE m.person_id = person.id),
    military_biography = (SELECT c.biography FROM commander c JOIN _cmd_map m ON m.commander_id = c.id WHERE m.person_id = person.id)
WHERE id IN (SELECT person_id FROM _cmd_map);

-- 4. notes that targeted a commander now target the person ---------------
UPDATE note SET target_id = (SELECT m.person_id FROM _cmd_map m
                             WHERE m.commander_id = note.target_id)
WHERE entity_type = 'commander'
  AND target_id IN (SELECT commander_id FROM _cmd_map);
UPDATE note SET entity_type = 'person' WHERE entity_type = 'commander';

-- 5. traits: commander_trait -> person_trait(person_id -> person) --------
CREATE TABLE person_trait (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    person_id     INTEGER NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
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
INSERT INTO person_trait (id, docname, person_id, quality, level, assessed_by,
                          assessed_at, evidence_note, source, created_at,
                          created_by, modified_at, modified_by)
SELECT t.id, t.docname, m.person_id, t.quality, t.level, t.assessed_by,
       t.assessed_at, t.evidence_note, t.source, t.created_at,
       t.created_by, t.modified_at, t.modified_by
FROM commander_trait t JOIN _cmd_map m ON m.commander_id = t.commander_id;
DROP TABLE commander_trait;
CREATE INDEX IF NOT EXISTS ix_trait_person ON person_trait(person_id);
CREATE INDEX IF NOT EXISTS ix_trait_quality ON person_trait(quality);

-- 6. command_assignment: commander_id now references person --------------
CREATE TEMP TABLE _asg_stash AS SELECT * FROM command_assignment;
DROP TABLE command_assignment;
CREATE TABLE command_assignment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    docname       TEXT NOT NULL UNIQUE,
    unit_id       INTEGER NOT NULL REFERENCES military_unit(id) ON DELETE RESTRICT,
    commander_id  INTEGER NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
    role          TEXT NOT NULL DEFAULT 'Commanding Officer',
    assigned_date TEXT NOT NULL,
    relieved_date TEXT,
    is_current    INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    notes         TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    modified_at   TEXT,
    modified_by   TEXT
);
INSERT INTO command_assignment (id, docname, unit_id, commander_id, role,
                                assigned_date, relieved_date, is_current,
                                notes, created_at, created_by,
                                modified_at, modified_by)
SELECT a.id, a.docname, a.unit_id, m.person_id, a.role, a.assigned_date,
       a.relieved_date, a.is_current, a.notes, a.created_at, a.created_by,
       a.modified_at, a.modified_by
FROM _asg_stash a JOIN _cmd_map m ON m.commander_id = a.commander_id;
DROP TABLE _asg_stash;
CREATE INDEX IF NOT EXISTS ix_assignment_unit ON command_assignment(unit_id);
CREATE INDEX IF NOT EXISTS ix_assignment_commander ON command_assignment(commander_id);

-- 7. military_unit: commander_id now references person -------------------
-- stash + DROP + CREATE under the same name: the child tables (mission,
-- training, unit_armament, operational_deployment, command_assignment) keep
-- their untouched REFERENCES military_unit(id) clauses and resolve to the
-- new table by name.
CREATE TEMP TABLE _unit_stash AS SELECT * FROM military_unit;
DROP TABLE military_unit;
CREATE TABLE military_unit (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    docname               TEXT NOT NULL UNIQUE,
    code                  TEXT UNIQUE,
    name                  TEXT NOT NULL,
    echelon               TEXT NOT NULL DEFAULT 'Brigade',
    parent_id             INTEGER REFERENCES military_unit(id) ON DELETE RESTRICT,
    classification_id     INTEGER REFERENCES classification(id) ON DELETE RESTRICT,
    role                  TEXT,
    status                TEXT NOT NULL DEFAULT 'Active',
    commander_id          INTEGER REFERENCES person(id) ON DELETE RESTRICT,
    current_deployment_id INTEGER,
    direct_personnel      INTEGER NOT NULL DEFAULT 0 CHECK (direct_personnel >= 0),
    division_id           INTEGER REFERENCES division(id) ON DELETE RESTRICT,
    region_id             INTEGER REFERENCES region(id) ON DELETE RESTRICT,
    formation_date        TEXT,
    headquarters          TEXT,
    notes                 TEXT,
    image_url             TEXT,
    image_alt             TEXT,
    latitude              REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90)),
    longitude             REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    geometry_source       TEXT,
    path                  TEXT NOT NULL DEFAULT '',
    depth                 INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    created_by            TEXT NOT NULL,
    modified_at           TEXT,
    modified_by           TEXT
);
INSERT INTO military_unit (id, docname, code, name, echelon, parent_id,
                           classification_id, role, status, commander_id,
                           current_deployment_id, direct_personnel, division_id,
                           region_id, formation_date, headquarters, notes,
                           image_url, image_alt, latitude, longitude,
                           geometry_source, path, depth, created_at,
                           created_by, modified_at, modified_by)
SELECT u.id, u.docname, u.code, u.name, u.echelon, u.parent_id,
       u.classification_id, u.role, u.status,
       (SELECT m.person_id FROM _cmd_map m WHERE m.commander_id = u.commander_id),
       u.current_deployment_id, u.direct_personnel, u.division_id,
       u.region_id, u.formation_date, u.headquarters, u.notes,
       u.image_url, u.image_alt, u.latitude, u.longitude,
       u.geometry_source, u.path, u.depth, u.created_at,
       u.created_by, u.modified_at, u.modified_by
FROM _unit_stash u ORDER BY u.depth, u.id;
DROP TABLE _unit_stash;
CREATE INDEX IF NOT EXISTS idx_unit_parent ON military_unit(parent_id);
CREATE INDEX IF NOT EXISTS idx_unit_path ON military_unit(path);
CREATE INDEX IF NOT EXISTS idx_unit_status ON military_unit(status);
CREATE INDEX IF NOT EXISTS ix_military_unit_geo ON military_unit(latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_military_unit_commander ON military_unit(commander_id);

-- 8. the Leader table is gone -------------------------------------------
DROP TABLE commander;
DROP TABLE _cmd_map;

PRAGMA foreign_keys=ON;
