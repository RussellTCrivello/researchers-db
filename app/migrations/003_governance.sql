-- Governance systems were listed as a help table but had no home in the model.
ALTER TABLE institution ADD COLUMN governance_id INTEGER REFERENCES lookup(id);
CREATE INDEX IF NOT EXISTS ix_inst_gov ON institution(governance_id);
