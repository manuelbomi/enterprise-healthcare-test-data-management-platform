"""Metadata plane schema: SQLAlchemy models and session management.

The control plane owns the PostgreSQL schema described in
ARCHITECTURE.md section 2.3 (catalog, lineage, snapshot registry,
classification store) and docs/adr/0004-postgresql-metadata-store.md.

Phase 7 adds the first real, database-backed slice of this schema: the
dataset lifecycle and refresh management tables (`models.py`) --
dataset versions, refresh policies, environment dataset requests,
refresh runs, and rollback events -- accessed through
`control_plane.domain.lifecycle.repository.LifecycleRepository`, never
directly by API route handlers. See `control_plane/domain/lifecycle/`
and `docs/adr/0012-refresh-orchestration-abstraction.md`.

Earlier planned tables (catalog, lineage, classification store) remain
out of scope for this module and are still served via the Phase 2 JSON
artifact handoff (`control_plane.catalog`, ADR-0009) until a future
phase migrates them here.
"""

from control_plane.db.models import (
    Base,
    DatasetVersionRow,
    EnvironmentDatasetRequestRow,
    RefreshPolicyRow,
    RefreshRunRow,
    RollbackEventRow,
    create_postgres_engine,
    create_sqlite_engine,
    init_schema,
)
from control_plane.db.session import build_session_factory, get_engine_for_url, session_scope

__all__ = [
    "Base",
    "DatasetVersionRow",
    "EnvironmentDatasetRequestRow",
    "RefreshPolicyRow",
    "RefreshRunRow",
    "RollbackEventRow",
    "build_session_factory",
    "create_postgres_engine",
    "create_sqlite_engine",
    "get_engine_for_url",
    "init_schema",
    "session_scope",
]
