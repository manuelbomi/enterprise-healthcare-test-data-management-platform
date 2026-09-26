"""SQLAlchemy models for the PostgreSQL-bound slice of the estate.

Per ``docs/adr/0004-postgresql-metadata-store.md``, PostgreSQL is this
platform's relational system-of-record technology of choice. Here it
plays a *different* role than the metadata plane's own PostgreSQL
database (``services/control-plane/src/control_plane/db``, built out in
ROADMAP.md Phase "metadata plane"): this module models a **simulated
source system** — a fictional health plan's enrollment/eligibility and
provider-directory database — that the platform will later discover,
subset, and mask. Do not confuse the two: this is business data the
platform ingests, not the platform's own catalog/lineage/snapshot schema.

Why these six entities live in Postgres and the rest do not
------------------------------------------------------------
Member, MemberDemographics, Address, Coverage, Plan, and Provider are the
kind of master/reference data a real enrollment system keeps in an OLTP
relational database: read/written transactionally, genuinely relational
(a Coverage row is meaningless without its Member and Plan), and small
relative to claims/clinical volume. Claims, clinical, pharmacy, and
partner-lab data are higher-volume, append-mostly extracts — a much
better fit for columnar/object storage (see ADR-0007), which is exactly
how they are modeled in this estate (``writers/parquet_writer.py``,
``writers/s3_writer.py``, ``writers/adls_writer.py``,
``writers/partner_writer.py``).

Portable across SQLite (default local generation) and real PostgreSQL
---------------------------------------------------------------------
These models intentionally avoid Postgres-only column types (no JSONB,
no native UUID) so the exact same models and the exact same
``write_postgres_entities`` function work against a local SQLite file
(the default, zero-infrastructure path used by the generator CLI and the
test suite) and against a real PostgreSQL DSN
(``postgresql+psycopg://...``, per ADR-0004) once
``infra/docker-compose`` is running (Phase 4). Only the connection URL
changes.

Real foreign keys vs. intentional orphans
------------------------------------------
``Coverage.member_id -> Member.member_id`` and ``Coverage.plan_id ->
Plan.plan_id`` are real, enforced foreign keys: a real enrollment OLTP
database would reject an orphaned coverage row, so this estate does not
attempt to inject one there (see ``generator.py``, coverage generation
always resolves a plan_id that exists — the "coverage references a
nonexistent plan" edge case exists as *logical* data, but only in a
simulated way that respects Postgres's own guarantees; see
``README.md`` for where genuine orphans do live).

``Address.member_id`` deliberately has **no** database-level foreign key.
This models a common real-world situation: address data is frequently
sourced from a separate address-standardization vendor and merged in
without an enforced relationship, which is exactly the kind of soft
cross-feed reference this platform's referential-integrity story is
built to handle. The generator uses this to inject genuine orphan
``Address`` rows that a real Postgres table would still happily accept.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from data_plane.reference_data.domain import (
    Address as AddressDomain,
)
from data_plane.reference_data.domain import (
    Coverage as CoverageDomain,
)
from data_plane.reference_data.domain import (
    Member as MemberDomain,
)
from data_plane.reference_data.domain import (
    MemberDemographics as MemberDemographicsDomain,
)
from data_plane.reference_data.domain import (
    Plan as PlanDomain,
)
from data_plane.reference_data.domain import (
    Provider as ProviderDomain,
)


class Base(DeclarativeBase):
    """Declarative base for the simulated enrollment/provider-directory database."""


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class MemberRow(Base):
    __tablename__ = "member"

    member_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(1), nullable=True)
    ssn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    medical_record_number: Mapped[str] = mapped_column(String(32))
    effective_date: Mapped[date] = mapped_column(Date)
    term_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    extract_batch_id: Mapped[str] = mapped_column(String(64), default="")

    demographics: Mapped["MemberDemographicsRow"] = relationship(
        back_populates="member", uselist=False
    )
    coverages: Mapped[list["CoverageRow"]] = relationship(back_populates="member")


class MemberDemographicsRow(Base):
    __tablename__ = "member_demographics"

    member_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("member.member_id"), primary_key=True
    )
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    race: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ethnicity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    member: Mapped[MemberRow] = relationship(back_populates="demographics")


class AddressRow(Base):
    __tablename__ = "address"

    address_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Deliberately no ForeignKey("member.member_id") -- see module docstring.
    member_id: Mapped[str] = mapped_column(String(32), index=True)
    address_type: Mapped[str] = mapped_column(String(16))
    line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="US")
    effective_date: Mapped[date] = mapped_column(Date)


class PlanRow(Base):
    __tablename__ = "plan"

    plan_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    plan_name: Mapped[str] = mapped_column(String(255))
    plan_type: Mapped[str] = mapped_column(String(16))
    metal_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    market_segment: Mapped[str] = mapped_column(String(32))

    coverages: Mapped[list["CoverageRow"]] = relationship(back_populates="plan")


class CoverageRow(Base):
    __tablename__ = "coverage"

    coverage_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(32), ForeignKey("member.member_id"))
    plan_id: Mapped[str] = mapped_column(String(16), ForeignKey("plan.plan_id"))
    group_number: Mapped[str] = mapped_column(String(32))
    effective_date: Mapped[date] = mapped_column(Date)
    term_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage_status: Mapped[str] = mapped_column(String(16), default="active")
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    member: Mapped[MemberRow] = relationship(back_populates="coverages")
    plan: Mapped[PlanRow] = relationship(back_populates="coverages")


class ProviderRow(Base):
    __tablename__ = "provider"

    provider_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    npi: Mapped[str] = mapped_column(String(10))
    provider_name: Mapped[str] = mapped_column(String(255))
    provider_type: Mapped[str] = mapped_column(String(16))
    specialty: Mapped[str] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


def create_sqlite_engine(db_path: str) -> Engine:
    """Create a local SQLite engine at ``db_path`` (used by default -- no
    infrastructure required to run the generator)."""

    return create_engine(f"sqlite:///{db_path}")


def create_postgres_engine(database_url: str) -> Engine:
    """Create an engine against a real PostgreSQL DSN, e.g.
    ``postgresql+psycopg://tdm:tdm@localhost:5432/tdm_source_enrollment``.

    Uses the same models/writer as :func:`create_sqlite_engine` -- see the
    module docstring for why that portability was a deliberate design
    goal.

    Pool resilience (`problems_final_review.md` P2-1, mirrors
    `control_plane.db.models.create_postgres_engine`): `pool_pre_ping`
    detects a connection that went stale server-side before handing it
    to a caller instead of surfacing that failure mid-query;
    `pool_recycle` bounds connection lifetime against load-balancer/proxy
    idle timeouts; `pool_size`/`max_overflow` are explicit, sane defaults.
    Postgres-only -- SQLite has no equivalent staleness failure mode.
    """

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


def write_postgres_entities(
    engine: Engine,
    members: Iterable[MemberDomain],
    demographics: Iterable[MemberDemographicsDomain],
    addresses: Iterable[AddressDomain],
    plans: Iterable[PlanDomain],
    coverages: Iterable[CoverageDomain],
    providers: Iterable[ProviderDomain],
) -> None:
    """Create the schema (if needed) and bulk-load the enrollment estate.

    Order matters for the tables with real foreign keys: plans and
    members before coverages, members before demographics.
    """

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        for plan in plans:
            session.add(
                PlanRow(
                    plan_id=plan.plan_id,
                    plan_name=plan.plan_name,
                    plan_type=plan.plan_type,
                    metal_tier=plan.metal_tier,
                    market_segment=plan.market_segment,
                )
            )
        for provider in providers:
            session.add(
                ProviderRow(
                    provider_id=provider.provider_id,
                    npi=provider.npi,
                    provider_name=provider.provider_name,
                    provider_type=provider.provider_type,
                    specialty=provider.specialty,
                    city=provider.city,
                    state=provider.state,
                    is_active=provider.is_active,
                )
            )
        session.flush()

        for member in members:
            session.add(
                MemberRow(
                    member_id=member.member_id,
                    first_name=member.first_name,
                    last_name=member.last_name,
                    date_of_birth=_parse_date(member.date_of_birth),
                    gender=member.gender,
                    ssn=member.ssn,
                    medical_record_number=member.medical_record_number,
                    effective_date=_parse_date(member.effective_date),
                    term_date=_parse_date(member.term_date),
                    is_active=member.is_active,
                    row_version=member.row_version,
                    extract_batch_id=member.extract_batch_id,
                )
            )
        session.flush()

        for demo in demographics:
            session.add(
                MemberDemographicsRow(
                    member_id=demo.member_id,
                    middle_name=demo.middle_name,
                    race=demo.race,
                    ethnicity=demo.ethnicity,
                    preferred_language=demo.preferred_language,
                    marital_status=demo.marital_status,
                    email=demo.email,
                    phone=demo.phone,
                )
            )

        for addr in addresses:
            session.add(
                AddressRow(
                    address_id=addr.address_id,
                    member_id=addr.member_id,
                    address_type=addr.address_type,
                    line1=addr.line1,
                    line2=addr.line2,
                    city=addr.city,
                    state=addr.state,
                    zip_code=addr.zip_code,
                    country=addr.country,
                    effective_date=_parse_date(addr.effective_date),
                )
            )

        for cov in coverages:
            session.add(
                CoverageRow(
                    coverage_id=cov.coverage_id,
                    member_id=cov.member_id,
                    plan_id=cov.plan_id,
                    group_number=cov.group_number,
                    effective_date=_parse_date(cov.effective_date),
                    term_date=_parse_date(cov.term_date),
                    coverage_status=cov.coverage_status,
                    row_version=cov.row_version,
                )
            )

        session.commit()


__all__ = [
    "AddressRow",
    "Base",
    "CoverageRow",
    "MemberDemographicsRow",
    "MemberRow",
    "PlanRow",
    "ProviderRow",
    "create_postgres_engine",
    "create_sqlite_engine",
    "write_postgres_entities",
]
