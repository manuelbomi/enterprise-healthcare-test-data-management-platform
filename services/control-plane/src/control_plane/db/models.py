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

Phase 10 (`control_plane.domain.governance`) adds four more tables to
this same schema/engine, deliberately kept in this one module rather
than a separate one -- `GovernanceRepository` (Phase 10) calls directly
into `LifecycleRepository` (Phase 7) within the *same*
`sqlalchemy.orm.Session`, so both domains' tables must live behind one
`Base`/one `init_schema()` call for that to be a real, transactional
integration rather than a two-database integration masquerading as one:

- `MaskingPolicyVersionRow` -- one governed, versioned snapshot of a
  real Phase 3 `MaskingPolicy` (`healthcare_tdm_contracts.MaskingPolicyVersion`).
- `PolicyApprovalRow` -- an append-only log of every approval-workflow
  action taken against a `MaskingPolicyVersionRow`.
- `BusinessConsumerRow` -- one organizational arm/business unit
  (`LEFT_ARM`, `RIGHT_ARM`).
- `ConsumerDatasetRequestRow` -- one business consumer's request for a
  dataset, referencing an *approved* `MaskingPolicyVersionRow` by
  foreign key and, once fulfilled, an `EnvironmentDatasetRequestRow` by
  foreign key -- never a masking rule of its own.

Phase 11 (`control_plane.platform`) adds two more tables to this same
schema/engine, for the same same-transaction reason Phase 10's tables
were added here rather than to a separate service (see ADR-0014 and
`docs/adr/0015-platform-integrity-controls-in-control-plane.md`):

- `AuditEventRow` -- an append-only log of security/governance-relevant
  actions (`healthcare_tdm_contracts.AuditEvent`), written by
  `control_plane.platform.audit.AuditLogRepository`. No code path in
  this module or `AuditLogRepository` ever updates or deletes a row --
  immutability is structural (no method exists to do it), the same
  property `THREAT_MODEL.md`'s "Repudiation" mitigation for the
  security/governance plane requires.
- `DeadLetterEventRow` -- an append-only log of individually-isolated
  job/sweep failures (e.g. one failed request inside a
  `LocalRefreshOrchestrator.run_due_refreshes` sweep -- see
  `docs/adr/0012-refresh-orchestration-abstraction.md`'s "isolate one
  request's failure from the others" principle), written by
  `control_plane.platform.dead_letter.DeadLetterStore`. This is this
  phase's concrete answer to "dead-letter handling concepts": a
  durable, queryable record of *what failed and why*, distinct from
  the audit log (which records actions taken, not failures) and from
  `RefreshSweepResult.errors` (which is only visible to the single
  caller of that one sweep and is never persisted).

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


class MaskingPolicyVersionRow(Base):
    __tablename__ = "masking_policy_version"
    __table_args__ = (
        UniqueConstraint("policy_name", "policy_version", name="uq_masking_policy_version"),
    )

    policy_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_name: Mapped[str] = mapped_column(String(255), index=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    masking_policy_json: Mapped[str] = mapped_column(
        Text, doc="JSON-serialized healthcare_tdm_contracts.MaskingPolicy (full rule set)."
    )
    masking_engine_version: Mapped[str] = mapped_column(String(64))
    approval_status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="")
    superseded_by_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PolicyApprovalRow(Base):
    __tablename__ = "policy_approval"

    approval_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("masking_policy_version.policy_version_id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    performed_by: Mapped[str] = mapped_column(String(255))
    performed_at: Mapped[datetime] = mapped_column(DateTime)
    comments: Mapped[str] = mapped_column(Text, default="")


class BusinessConsumerRow(Base):
    __tablename__ = "business_consumer"

    business_consumer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ConsumerDatasetRequestRow(Base):
    __tablename__ = "consumer_dataset_request"

    consumer_request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_consumer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("business_consumer.business_consumer_id"), index=True
    )
    business_consumer_code: Mapped[str] = mapped_column(String(64), default="")
    dataset_name: Mapped[str] = mapped_column(String(255), index=True)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    policy_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("masking_policy_version.policy_version_id")
    )
    masking_policy_name: Mapped[str] = mapped_column(String(255), default="")
    masking_policy_version: Mapped[int] = mapped_column(Integer, default=0)
    subset_size_hint: Mapped[str] = mapped_column(String(512), default="")
    refresh_cadence_type: Mapped[str] = mapped_column(String(32))
    performance_requirements: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[str] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    environment_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("environment_dataset_request.request_id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")


class AuditEventRow(Base):
    """See the module docstring's "Phase 11" note. Append-only by
    construction: `AuditLogRepository` (`control_plane.platform.audit`)
    only ever `INSERT`s a row here -- there is no update/delete method
    anywhere in this codebase for this table."""

    __tablename__ = "audit_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(512), index=True)
    outcome: Mapped[str] = mapped_column(String(64))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class DeadLetterEventRow(Base):
    """See the module docstring's "Phase 11" note. Append-only, written
    by `control_plane.platform.dead_letter.DeadLetterStore`."""

    __tablename__ = "dead_letter_event"

    dead_letter_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(512), index=True)
    reason: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)


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
    Idempotent -- safe to call on every process start.

    **This is the from-scratch path only** (a fresh test/dev SQLite file
    with nothing in it yet, or a brand-new deployment's first-ever
    start). It cannot alter an existing table once a database already
    has rows in it -- no add/rename/drop column, no type change, no new
    index on an existing table. For a real deployment carrying real
    data across an upgrade, use the Phase 18A Alembic setup instead
    (`services/control-plane/alembic.ini` + `migrations/`, resolves
    `problems_final_review.md` P1-3): `alembic upgrade head` from
    `services/control-plane/`. Every future change to the models in
    this module should ship together with a new Alembic migration
    (`alembic revision --autogenerate -m "..."`, reviewed before
    committing), not a hand edit assuming `create_all` will handle it --
    see `migrations/versions/*_phase18a_initial_schema.py`'s own
    docstring and `services/control-plane/tests/test_migrations.py` for
    the real, executed proof this baseline migration matches this exact
    schema."""

    Base.metadata.create_all(engine)


__all__ = [
    "AuditEventRow",
    "Base",
    "BusinessConsumerRow",
    "ConsumerDatasetRequestRow",
    "DatasetVersionRow",
    "DeadLetterEventRow",
    "EnvironmentDatasetRequestRow",
    "MaskingPolicyVersionRow",
    "PolicyApprovalRow",
    "RefreshPolicyRow",
    "RefreshRunRow",
    "RollbackEventRow",
    "create_postgres_engine",
    "create_sqlite_engine",
    "init_schema",
]
