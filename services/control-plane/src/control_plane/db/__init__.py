"""Metadata plane schema: SQLAlchemy models and session management.

The control plane owns the PostgreSQL schema described in
ARCHITECTURE.md section 2.3 (catalog, lineage, snapshot registry,
classification store) and docs/adr/0004-postgresql-metadata-store.md.

Phase 0 scope: this module is an empty placeholder. Real models and
Alembic migrations are added in Phase 1, which is deliberately the first
implementation phase because every other plane depends on the metadata
plane existing.
"""
