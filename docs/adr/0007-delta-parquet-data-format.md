# ADR-0007: Parquet as the baseline data format, with Delta Lake for versioned/mutable tables

## Status

Accepted

## Context

The data plane needs a storage format for datasets moving through
discovery, subsetting, masking, and synthetic generation, and for published
snapshots. Requirements:

- Efficient for large, columnar, analytical workloads (Spark reads/writes)
- Supports schema evolution as source systems change over time
- Supports the platform's own versioning/snapshot model (ADR/feature in
  Phase 13) — being able to say "this snapshot is exactly what existed at
  this point" and to refresh without corrupting prior snapshots
- Works the same way locally (against MinIO) and in the cloud (S3/ADLS) and
  is Databricks-compatible, per the project's stated stack preference

## Decision

Use **Parquet** as the baseline columnar file format for all data-plane
outputs. Use **Delta Lake** (an open table format built on Parquet, adding a
transaction log) for datasets that need versioning, ACID writes, or
time-travel semantics — which in this platform is most published snapshots
and any table the refresh/orchestration system updates in place rather than
writing as a brand-new object each time.

Plain Parquet (no Delta transaction log) remains appropriate for
one-shot, immutable outputs (e.g., a single synthetic-data export job that
never gets updated in place) where Delta's extra bookkeeping isn't needed.

Both formats are read/write-compatible with PySpark and with the
Databricks runtime, satisfying the "Databricks-compatible implementation
where practical" stack preference without requiring a Databricks account to
develop against locally (a local Spark session + Delta Lake's open-source
package + MinIO stands in for it during development).

## Consequences

- Two formats to understand instead of one — mitigated by a clear rule
  (versioned/mutable → Delta, one-shot/immutable → Parquet) documented here
  and reinforced in `docs/tutorial/`.
- Delta Lake's transaction log gives the snapshot/versioning system
  (Phase 13) a natural implementation substrate instead of having to build
  versioning semantics from scratch on bare Parquet.
- Both formats are broadly supported by the broader data ecosystem (query
  engines, BI tools, other Spark-compatible platforms), keeping the
  platform's outputs usable outside the platform itself.
