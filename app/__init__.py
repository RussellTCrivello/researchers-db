"""SIRAJ · سِراج — bilingual research registry.

Package map
-----------
``app.db``          connections, migrations, numbering, audit trail, FTS helpers
``app.schemas``     single source of truth: entities, fields, derived fields, validation
``app.repo``        read/write layer, filter engine, duplicates & merge
``app.transfer``    import pipeline and export engine
``app.reports``     the nine reports plus the ad-hoc pivot
``app.stats``       dashboard aggregates
``app.seed``        vocabularies, locales, users, sequences, synthetic demo data
``app.server``      FastAPI application (``app.server.api``) and cross-platform launcher
``app.cli``         command line interface (init/serve/migrate/backup/stats/export/user)
"""
__version__ = "1.1.0"
SCHEMA_VERSION = "1.0.0"
