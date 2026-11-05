-- Geographic provenance: a coordinate is only as good as the way it was obtained.
-- Storing the method, the radius of the doubt and the map it came from keeps a city
-- centroid from being read as a verified street address, which the research
-- standards for this registry forbid.
ALTER TABLE place ADD COLUMN geocoding_method TEXT;
ALTER TABLE place ADD COLUMN geo_uncertainty_m REAL;
ALTER TABLE place ADD COLUMN geometry_source TEXT;
