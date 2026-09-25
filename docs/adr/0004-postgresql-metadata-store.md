# ADR-0004: PostgreSQL as the metadata plane's system of record

## Status

Accepted

## Context

The metadata plane needs to durably store: the data catalog, classification
records, job lineage, and the snapshot registry. This data is:

- Highly relational (a snapshot references a job run, which references a
  source dataset, which has many classified columns, etc.)
- Read and written transactionally — e.g., "record that a job started" and
  "check whether a quota is exceeded" need to be consistent
- Not itself PHI/PII-bearing (it stores *labels about* data — "column X is
  classified as a direct identifier" — never the data values themselves), so
  it does not need to be a specialized data-lake technology
- Relatively small in volume compared to the actual test datasets the
  platform manages (those live in object storage, not here)

## Decision

Use PostgreSQL as the metadata plane's system of record, accessed via
SQLAlchemy models from the control plane (which owns the metadata plane's
schema) and via typed contracts (`libs/contracts`) from other planes that
need to read or write metadata.

We did not choose a NoSQL document store because the metadata is
genuinely relational with real referential-integrity requirements (a
snapshot must reference a real job run; a classification must reference a
real column) — exactly the kind of guarantee a relational database with
foreign keys gives for free and a document store makes the application
responsible for reimplementing. We did not choose to store metadata
alongside the actual data files (e.g., as Delta table metadata only)
because the metadata plane needs to be queryable independently of whether
a given Spark cluster is up, and needs strong transactional guarantees for
things like quota checks that don't belong in a data-lake engine.

Schema migrations are managed with Alembic (introduced in Phase 1, when the
first real schema is written).

## Consequences

- We take on operating a relational database (even if just via a managed
  service or a single Docker Compose container in dev) as a dependency of
  the control plane.
- We get: strong referential integrity for exactly the kind of data that
  needs it, mature tooling (Alembic migrations, broad ORM support via
  SQLAlchemy), and a technology every contributor is likely to already
  understand, which matters for a teaching repository.
- Actual test data (rows of masked/synthetic healthcare records) never
  lives in PostgreSQL — it lives in object storage as Parquet/Delta,
  referenced by metadata rows. This keeps the metadata database small and
  keeps the "no PHI/PII in the metadata plane" property structurally true
  rather than merely policy.
