-- Place administrative units: governorate and district as controlled vocabularies
-- (lookup domains with parent_id), referenced from place instead of free text.
ALTER TABLE place ADD COLUMN governorate_id INTEGER REFERENCES lookup(id);
ALTER TABLE place ADD COLUMN district_id INTEGER REFERENCES lookup(id);
CREATE INDEX IF NOT EXISTS ix_place_governorate ON place(governorate_id);
CREATE INDEX IF NOT EXISTS ix_place_district ON place(district_id);

-- Backfill governorate from the free-text region column when labels match.
UPDATE place
   SET governorate_id = (
     SELECT g.id FROM lookup g
     WHERE g.domain = 'governorate' AND g.is_active = 1
       AND g.parent_id = place.country_id
       AND (
         lower(g.label_en) = lower(trim(place.region))
         OR g.label_ar = trim(place.region)
       )
     LIMIT 1
   )
 WHERE place.region IS NOT NULL AND trim(place.region) != ''
   AND place.governorate_id IS NULL;

-- Backfill district from free-text district when labels match under that governorate.
UPDATE place
   SET district_id = (
     SELECT d.id FROM lookup d
     WHERE d.domain = 'district' AND d.is_active = 1
       AND d.parent_id = place.governorate_id
       AND (
         lower(d.label_en) = lower(trim(place.district))
         OR d.label_ar = trim(place.district)
       )
     LIMIT 1
   )
 WHERE place.district IS NOT NULL AND trim(place.district) != ''
   AND place.governorate_id IS NOT NULL
   AND place.district_id IS NULL;

-- Countries are editable reference data (new countries can be added in Vocabularies).
UPDATE lookup SET is_system = 0 WHERE domain = 'country';
