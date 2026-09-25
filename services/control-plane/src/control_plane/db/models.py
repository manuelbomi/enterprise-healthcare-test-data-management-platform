"""Metadata plane schema: SQLAlchemy models for Phase 7 (dataset
lifecycle and refresh management) -- the first real, database-backed
domain model this service owns (see `ARCHITECTURE.md` section 2.3 and
`docs/adr/0004-postgresql-metadata-store.md`).

Portable across SQLite and real PostgreSQL, following the exact pattern
`data_plane.reference_data.postgres_models` established in Phase 1: no
Postgres-only column types (no JSONB, no native UUID). UUIDs are stored
as `String(36)`; the one genuinely semi-structured field
(`DatasetVersionRow.row_counts_json`) is stored as `Text` containing a
JSON string, serialized/deserialized in
`control_plane.domain.lifecycle.repository`, not here -- this module
stays a pure schema definition, no business logic (same "no business
logic" rule `libs/contracts` documents for its own shapes).

Table map
---------
- `DatasetVersionRow` -- one immutable, registered dataset version
  (`healthcare_tdm_contracts.DatasetVersion`). Environment-agnostic by
  design: many `EnvironmentDatasetRequestRow` rows may reference the
  same `DatasetVersionRow` at once. This is the actual mechanism behind
  "avoid unnecessary duplicate physical copies" -- see
  `docs/adr/0012-refresh-orchestration-abstraction.md`.
- `RefreshPolicyRow` -- a configured refresh cadence/retention policy,
  scoped to one environment and (optionally) one dataset.
- `EnvironmentDatasetRequestRow` -- one environment's standing request
  for a dataset: a pointer (`current_version_id`, a foreign key, never a
  copy) plus its own refresh-schedule state. Unique per
  `(environment, dataset_name)`.
- `RefreshRunRow` -- an append-only log of every refresh execution
  (scheduled or on-demand).
- `RollbackEventRow` -- an append-only log of every rollback, per
  `EnvironmentDatasetRequestRow`.

Real PostgreSQL verification remains deferred, same honest pattern
`problems_phase_01.md` P1-1 established: these models and
`create_sqlite_engine`/`create_postgres_engine` below are exercised
against local SQLite by this phase's tests
(`services/control-plane/tests/test_lifecycle_repository.py`,
`test_lifecycle_api.py`); no real Postgres instance has been started
against this schema yet (`infra/docker-compose` is not running in this
environment). See `problems_phase_07.md`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for the metadata plane's dataset lifecycle schema."""


class DatasetVersionRow(Base):
    __tablename__ = "dataset_version"
    __table_args__ = (
        UniqueConstraint("dataset_name", "version_number", name="uq_dataset_version_number"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(255), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    certification_report_id: Mapped[str] = mapped_column(String(36))
    masking_policy_name: Mapped[str] = mapped_column(String(255))
    masking_policy_version: Mapped[int] = mapped_column(Integer)
    masking_engine_version: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_counts_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(255))
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class RefreshPolicyRow(Base):
    __tablename__ = "refresh_policy"

    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cadence_type: Mapped[str] = mapped_column(String(32))
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=3)
    on_demand_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class EnvironmentDatasetRequestRow(Base):
    __tablename__ = "environment_dataset_request"
    __table_args__ = (
        UniqueConstraint("environment", "dataset_name", name="uq_environment_dataset"),
    )

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    dataset_name: Mapped[str] = mapped_column(String(255), index=True)
    current_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_version.version_id")
    )
    status: Mapped[str] = mapped_column(String(32), default="active")
    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("refresh_policy.policy_id"))
    policy_version: Mapped[int] = mapped_column(Integer)
    consumer: Mapped[str] = mapped_column(String(255), default="")
    requested_by: Mapped[str] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefreshRunRow(Base):
    __tablename__ = "refresh_run"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("environment_dataset_request.request_id")
    )
    environment: Mapped[str] = mapped_column(String(32))
    dataset_name: Mapped[str] = mapped_column(String(255))
    trigger: Mapped[str] = mapped_column(String(16))
    triggered_by: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resulting_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class RollbackEventRow(Base):
    __tablename__ = "rollback_event"

    rollback_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("environment_dataset_request.request_id")
    )
    environment: Mapped[str] = mapped_column(String(32))
    dataset_name: Mapped[str] = mapped_column(String(255))
    from_version_id: Mapped[str] = mapped_column(String(36))
    to_version_id: Mapped[str] = mapped_column(String(36))
    performed_by: Mapped[str] = mapped_column(String(255))
    performed_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(Text)


def create_sqlite_engine(db_path: str) -> Engine:
    """Create a local SQLite engine at ``db_path`` (or ``:memory:``) --
    the default, zero-infrastructure path used by tests and local dev.
    Mirrors `data_plane.reference_data.postgres_models.create_sqlite_engine`.
    """

    return create_engine(f"sqlite:///{db_path}")


def create_postgres_engine(database_url: str) -> Engine:
    """Create an engine against a real PostgreSQL DSN, e.g.
    ``postgresql+psycopg://tdm:tdm@localhost:5432/tdm_metadata`` (see
    `docs/adr/0004-postgresql-metadata-store.md`). Uses the exact same
    models as :func:`create_sqlite_engine` -- see the module docstring
    for why that portability is deliberate. Not yet exercised against a
    real Postgres instance in this environment; see the module docstring.
    """

    return create_engine(database_url)


def init_schema(engine: Engine) -> None:
    """Create every table in this module if it does not already exist.
    Idempotent -- safe to call on every process start."""

    Base.metadata.create_all(engine)


__all__ = [
    "Base",
    "DatasetVersionRow",
    "EnvironmentDatasetRequestRow",
    "RefreshPolicyRow",
    "RefreshRunRow",
    "RollbackEventRow",
    "create_postgres_engine",
    "create_sqlite_engine",
    "init_schema",
]
