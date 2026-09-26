"""Storage and compute footprint / capacity-planning contracts (Phase 8).

`ROADMAP.md` Phase 8 asks the platform to calculate or estimate, for
every dataset/environment: source size, subset size, compressed size,
row count, storage footprint, refresh frequency, retention, estimated
processing volume, and estimated compute demand — and to build a
`CapacityPlanner` service around that, using Phase 7's real
`DatasetVersion`/`EnvironmentDatasetRequest` model (one immutable
artifact, many environment pointers) as the concrete mechanism that
makes "don't blindly create N independent copies" a real number, not a
slogan.

This module is deliberately split into two families of shapes, matching
the two different *kinds* of number this phase produces (see
`docs/adr/0013-capacity-planning-plane-split.md` and
`docs/CAPACITY_COST_TRADEOFFS.md` for the full reasoning):

**Real, measured/derived shapes** (built from data that actually exists
on disk or in the Phase 7 database, never fabricated):

- `CompressionMeasurement` / `FootprintMeasurementReport` — real,
  on-disk Parquet-vs-re-encoded-CSV size measurements
  (`data_plane.capacity.footprint`, the data-plane side).
- `PartitionSummary` — real, on-disk Hive-style partition layout
  analysis (`data_plane.capacity.partitioning`).
- `DatasetVersionFootprint` / `EnvironmentCapacityDemand` / `CapacityPlan`
  / `VacuumCandidate` — built from real, already-registered
  `DatasetVersion`/`EnvironmentDatasetRequest` rows
  (`control_plane.domain.capacity.planner`, the control-plane side).

**Illustrative, configurable scenario shapes** (a scaled hypothetical
model, never presented as a measurement):

- `EnvironmentCapacityRequirement` / `IllustrativeCapacityScenario` /
  `IllustrativeCapacityPlan` — the "Production: 100 TB, QA 10%, SIT 5%,
  UAT 15%" example from `ROADMAP.md`, made into a real, runnable,
  configurable model rather than a one-off calculation.

- `IncrementalRefreshEstimate` — a modeled illustration of what a real
  incremental-refresh engine (which this repository does not build —
  see `problems_phase_08.md` P8-2's sibling reasoning) would have
  saved relative to Phase 7's actual full-reprocessing `refresh()`,
  computed from two real, already-registered dataset versions' row
  counts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.lifecycle import DatasetVersionStatus, Environment, RefreshCadenceType

#: One terabyte, decimal (10^12 bytes) — the convention storage vendors
#: and `ROADMAP.md`'s own "Production: 100 TB" example use. Exposed so
#: every caller building a byte figure from a TB figure uses the same
#: conversion rather than each guessing at TB vs. TiB.
TERABYTE_BYTES: int = 10**12

#: `ROADMAP.md` Phase 8's own worked example, taken as the default
#: illustrative production baseline for `IllustrativeCapacityScenario`
#: when a caller doesn't supply one.
DEFAULT_PRODUCTION_BASELINE_BYTES: int = 100 * TERABYTE_BYTES


# ---------------------------------------------------------------------
# Real, on-disk footprint measurement (data-plane producer)
# ---------------------------------------------------------------------


class CompressionMeasurement(BaseModel):
    """The result of measuring one real Parquet file's compressed
    on-disk size against a re-encoding of the *same* rows as CSV --
    `data_plane.capacity.footprint.measure_parquet_compression`'s
    output.

    `uncompressed_estimate_bytes` is honestly a proxy, not a bit-for-bit
    "Parquet with compression turned off" byte count (pandas/pyarrow
    does not expose that directly without rewriting the file a second
    time) -- CSV is a reasonable, real, row-oriented, uncompressed
    stand-in, and `method` records exactly how it was derived so no
    reader mistakes this for something more precise than it is.
    """

    source_path: str
    row_count: int = Field(..., ge=0)
    column_count: int = Field(..., ge=0)
    compressed_bytes: int = Field(..., ge=0, description="Actual on-disk size of the Parquet file.")
    uncompressed_estimate_bytes: int = Field(
        ..., ge=0, description="Size of the same rows re-encoded as CSV in memory."
    )
    compression_ratio: float = Field(
        ..., ge=0, description="uncompressed_estimate_bytes / compressed_bytes; >1 means Parquet is smaller."
    )
    method: str = Field(
        default="parquet_on_disk_vs_in_memory_csv_reencode",
        description="How uncompressed_estimate_bytes was derived -- see this model's docstring.",
    )
    measured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FootprintMeasurementReport(BaseModel):
    """Aggregate, real, on-disk footprint measurement for a directory
    tree (an estate, a subset, a masked/certified output directory) --
    `data_plane.capacity.footprint.measure_directory_footprint`'s
    output. `bytes_by_extension`/`file_count_by_extension` are real
    counts of what is actually on disk (Parquet, CSV, NDJSON/JSON,
    SQLite `.db`, partner extract files, ...), demonstrating the
    platform's real multi-format estate (ADR-0007) rather than assuming
    everything is Parquet.
    """

    root_path: str
    total_bytes: int = Field(..., ge=0)
    total_file_count: int = Field(..., ge=0)
    bytes_by_extension: dict[str, int] = Field(default_factory=dict)
    file_count_by_extension: dict[str, int] = Field(default_factory=dict)
    parquet_compression: list[CompressionMeasurement] = Field(
        default_factory=list,
        description="One CompressionMeasurement per Parquet file found under root_path, if any.",
    )
    measured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_parquet_compressed_bytes(self) -> int:
        return sum(m.compressed_bytes for m in self.parquet_compression)

    @property
    def total_parquet_uncompressed_estimate_bytes(self) -> int:
        return sum(m.uncompressed_estimate_bytes for m in self.parquet_compression)

    @property
    def overall_parquet_compression_ratio(self) -> float | None:
        compressed = self.total_parquet_compressed_bytes
        if compressed == 0:
            return None
        return self.total_parquet_uncompressed_estimate_bytes / compressed


class PartitionSummary(BaseModel):
    """Real, on-disk Hive-style partition layout analysis (`key=value`
    directory segments, e.g. `batch=claims-2025Q1/`) for one dataset
    directory -- `data_plane.capacity.partitioning.analyze_partitions`'s
    output. Demonstrates that partitioning (ADR-0007's Parquet/Delta
    baseline) is a real, already-present property of this platform's
    output, not merely a design claim.
    """

    root_path: str
    partition_key: str | None = Field(
        default=None, description="The Hive partition key found (e.g. 'batch'), or None if unpartitioned."
    )
    partition_count: int = Field(..., ge=0)
    bytes_by_partition: dict[str, int] = Field(default_factory=dict)
    file_count_by_partition: dict[str, int] = Field(default_factory=dict)
    measured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------
# Real, DB-backed capacity planning (control-plane producer)
# ---------------------------------------------------------------------


class DatasetVersionFootprint(BaseModel):
    """The real storage/compute footprint of one already-registered
    `DatasetVersion`, built entirely from data Phase 7 already persists
    (`size_bytes`, `row_counts`, `retention_days`,
    `referenced_by_environments`) -- see
    `control_plane.domain.capacity.planner.CapacityPlanner.dataset_version_footprint`.
    `physical_copy_count` is always `1` by construction: a `DatasetVersion`
    is Phase 7's single immutable artifact, referenced (never copied) by
    every environment in `referenced_by_environments` -- the field is
    included specifically so this fact is visible in this phase's own
    output, not just asserted in prose.
    """

    version_id: UUID
    dataset_name: str
    version_number: int
    status: DatasetVersionStatus
    storage_footprint_bytes: int = Field(..., ge=0, description="DatasetVersion.size_bytes, as registered.")
    row_counts: dict[str, int] = Field(default_factory=dict)
    total_row_count: int = Field(..., ge=0)
    retention_days: int = Field(..., ge=1)
    referenced_by_environments: list[Environment] = Field(default_factory=list)
    physical_copy_count: int = Field(
        default=1, description="Always 1 -- one immutable artifact, referenced by every environment above."
    )
    estimated_compute_unit_hours: float = Field(
        ..., ge=0, description="See control_plane.domain.capacity.estimator's module docstring for the heuristic."
    )


class EnvironmentCapacityDemand(BaseModel):
    """The real storage/compute demand one `EnvironmentDatasetRequest`
    places on the platform -- built from that request, the
    `DatasetVersion` it currently points at, and the `RefreshPolicy`
    that governs it (all real, already-registered Phase 7 data). See
    `control_plane.domain.capacity.planner.CapacityPlanner.environment_capacity_demand`.
    """

    request_id: UUID
    environment: Environment
    dataset_name: str
    current_version_id: UUID
    current_version_number: int
    attributed_storage_bytes: int = Field(
        ...,
        ge=0,
        description="The DatasetVersion's storage_footprint_bytes -- what this environment needs, which "
        "may already be shared with other environments pointing at the same version (see CapacityPlan "
        "for the naive-vs-shared comparison across ALL environments together).",
    )
    total_row_count: int = Field(..., ge=0)
    refresh_cadence_type: RefreshCadenceType
    refresh_interval_days: int | None = Field(
        default=None, description="Resolved interval in days, or None for RELEASE_DRIVEN/ON_DEMAND cadences."
    )
    retention_days: int = Field(..., ge=1)
    estimated_refreshes_per_year: float | None = Field(
        default=None, description="365 / refresh_interval_days, or None when there is no fixed cadence."
    )
    estimated_annual_processing_volume_rows: float | None = Field(
        default=None, description="total_row_count * estimated_refreshes_per_year, or None."
    )
    estimated_annual_compute_unit_hours: float | None = Field(default=None)


class CapacityPlan(BaseModel):
    """The real, DB-backed aggregate capacity report --
    `control_plane.domain.capacity.planner.CapacityPlanner.capacity_plan`'s
    output. `naive_total_storage_bytes` vs. `shared_total_storage_bytes`
    is the concrete answer to "how much does Phase 7's shared-immutable-
    snapshot architecture actually save," computed from real registered
    data, not a hypothetical -- see `docs/CAPACITY_COST_TRADEOFFS.md`.
    """

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dataset_name: str | None = Field(default=None, description="None = every dataset, aggregated together.")
    dataset_version_footprints: list[DatasetVersionFootprint] = Field(default_factory=list)
    environment_demands: list[EnvironmentCapacityDemand] = Field(default_factory=list)
    environment_count: int = Field(..., ge=0)
    distinct_dataset_version_count: int = Field(..., ge=0)
    naive_total_storage_bytes: int = Field(
        ...,
        ge=0,
        description="What storage would cost if every EnvironmentDatasetRequest owned an independent "
        "physical copy of its DatasetVersion's measured size -- sum over ALL environment requests, "
        "counting a shared version's size once per environment referencing it.",
    )
    shared_total_storage_bytes: int = Field(
        ...,
        ge=0,
        description="What storage actually costs under Phase 7's real architecture -- sum over only the "
        "DISTINCT DatasetVersions actually referenced, each counted exactly once regardless of how many "
        "environments point at it.",
    )
    storage_savings_bytes: int = Field(..., description="naive_total_storage_bytes - shared_total_storage_bytes.")
    storage_savings_pct: float = Field(
        ..., description="storage_savings_bytes / naive_total_storage_bytes, or 0.0 if naive total is 0."
    )


class VacuumCandidate(BaseModel):
    """A `DatasetVersion` this phase's real, DB-backed analysis has
    determined is safe to physically delete: its status is
    EXPIRED/REVOKED/ROLLED_BACK *and* zero `EnvironmentDatasetRequest`
    rows currently reference it. See
    `control_plane.domain.capacity.planner.CapacityPlanner.vacuum_candidates`
    and `problems_phase_08.md` P8-3 for why this is read-only (identifies
    candidates; does not delete anything)."""

    version_id: UUID
    dataset_name: str
    version_number: int
    status: DatasetVersionStatus
    storage_uri: str
    reclaimable_bytes: int = Field(..., ge=0)
    reason: str


class IncrementalRefreshEstimate(BaseModel):
    """A modeled illustration of what an incremental refresh (reprocess
    only what changed) would have saved relative to Phase 7's actual
    `refresh()`, which always repoints an environment at a whole new,
    fully-reprocessed `DatasetVersion`. Built from two real,
    already-registered dataset versions' row counts -- the arithmetic is
    real, the *savings* are a documented illustration of an unbuilt
    capability, never a claim that incremental refresh exists in this
    repository. See `data_plane.capacity.incremental` and
    `docs/CAPACITY_COST_TRADEOFFS.md`.
    """

    dataset_name: str
    previous_version_id: UUID
    previous_version_number: int
    current_version_id: UUID
    current_version_number: int
    previous_total_row_count: int = Field(..., ge=0)
    current_total_row_count: int = Field(..., ge=0)
    row_count_delta_by_entity: dict[str, int] = Field(default_factory=dict)
    unchanged_row_estimate: int = Field(
        ..., ge=0, description="min(previous, current) per entity, summed -- rows a real incremental "
        "refresh would plausibly not need to reprocess."
    )
    full_reprocess_row_count: int = Field(
        ..., ge=0, description="current_total_row_count -- what Phase 7's actual refresh() reprocesses today."
    )
    estimated_incremental_row_count: int = Field(
        ..., ge=0, description="full_reprocess_row_count - unchanged_row_estimate, the modeled incremental "
        "workload."
    )
    estimated_savings_pct: float = Field(..., description="1 - (estimated_incremental / full_reprocess), or 0.0.")


# ---------------------------------------------------------------------
# Illustrative, configurable percentage-of-production scenarios
# ---------------------------------------------------------------------


class EnvironmentCapacityRequirement(BaseModel):
    """One environment's configured target size, as a percentage of a
    (real or illustrative) production baseline -- the real,
    general-purpose model behind `ROADMAP.md` Phase 8's "Production:
    100 TB, QA requirement: 10%, SIT requirement: 5%, UAT requirement:
    15%" example. Never hardcoded into engine logic -- see
    `DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS` for the seed values this
    phase ships, which a caller can override entirely via
    `IllustrativeCapacityScenario.requirements`.

    `share_tier` groups environments that are modeled as sharing one
    physical snapshot, mirroring the real Phase 7 mechanism where every
    `EnvironmentDatasetRequest` for the same `dataset_name` points at one
    `DatasetVersion` -- a shared tier's modeled storage cost is the
    *largest* `target_pct_of_production` in that tier (a smaller
    requirement can safely consume a proportionally larger, over-
    provisioned shared snapshot; it can never safely consume a smaller
    one than its own requirement). See
    `control_plane.domain.capacity.planner.illustrative_capacity_plan`.
    """

    environment: Environment
    target_pct_of_production: float = Field(
        ..., gt=0, le=1.0, description="Fraction of the production baseline this environment targets, e.g. 0.10 for 10%."
    )
    share_tier: str = Field(
        default="standard",
        description="Environments with the same share_tier are modeled as sharing one physical snapshot.",
    )
    rationale: str = Field(default="")


#: `ROADMAP.md` Phase 8's worked example, extended honestly to all five
#: `Environment` values (the example only names QA/SIT/UAT): DEV and QA
#: share the "standard" tier at 10%, SIT at 5%, UAT at 15% (the most
#: demanding "standard" requirement -- the tier's modeled shared snapshot
#: is sized to it). PERFORMANCE is modeled at 100% in its own
#: "performance" tier -- see this module's docstring and
#: `docs/CAPACITY_COST_TRADEOFFS.md` for why performance testing is the
#: one case where subsetting undermines realism rather than merely
#: costing less, so it is not folded into the "standard" tier's savings.
DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS: list[EnvironmentCapacityRequirement] = [
    EnvironmentCapacityRequirement(
        environment=Environment.DEV,
        target_pct_of_production=0.10,
        share_tier="standard",
        rationale="Dev needs a realistic but small working set; sized the same as QA by default.",
    ),
    EnvironmentCapacityRequirement(
        environment=Environment.QA,
        target_pct_of_production=0.10,
        share_tier="standard",
        rationale="ROADMAP.md Phase 8 worked example: QA requirement 10% of production.",
    ),
    EnvironmentCapacityRequirement(
        environment=Environment.SIT,
        target_pct_of_production=0.05,
        share_tier="standard",
        rationale="ROADMAP.md Phase 8 worked example: SIT requirement 5% of production.",
    ),
    EnvironmentCapacityRequirement(
        environment=Environment.UAT,
        target_pct_of_production=0.15,
        share_tier="standard",
        rationale="ROADMAP.md Phase 8 worked example: UAT requirement 15% of production -- the most "
        "demanding 'standard' tier requirement, so that tier's shared snapshot is sized to it.",
    ),
    EnvironmentCapacityRequirement(
        environment=Environment.PERFORMANCE,
        target_pct_of_production=1.00,
        share_tier="performance",
        rationale="Performance/load testing needs production-representative volume for valid results; "
        "subsetting undermines the very thing being tested, so this environment is its own tier rather "
        "than sharing the smaller 'standard' snapshot.",
    ),
]


class IllustrativeCapacityScenario(BaseModel):
    """The input to `control_plane.domain.capacity.planner.illustrative_capacity_plan`
    -- a hypothetical production size plus a set of per-environment
    requirements. `label` exists so every plan built from this scenario
    can be displayed with an unmistakable "this is a model, not a
    measurement" marker (see `docs/CAPACITY_COST_TRADEOFFS.md`)."""

    scenario_id: UUID = Field(default_factory=uuid4)
    label: str = Field(default="illustrative")
    production_baseline_bytes: int = Field(default=DEFAULT_PRODUCTION_BASELINE_BYTES, ge=0)
    requirements: list[EnvironmentCapacityRequirement] = Field(
        default_factory=lambda: list(DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS)
    )


class IllustrativeCapacityPlan(BaseModel):
    """The output of `illustrative_capacity_plan`: naive (every
    environment its own independently-sized copy) vs. shared-by-tier
    (Phase 7's real sharing mechanism, modeled) totals for a
    hypothetical production baseline. Always carries the
    `IllustrativeCapacityScenario` it was computed from, so a caller can
    never separate the numbers from the assumptions that produced them.
    """

    scenario: IllustrativeCapacityScenario
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    per_environment_naive_bytes: dict[str, int] = Field(default_factory=dict)
    per_tier_shared_bytes: dict[str, int] = Field(default_factory=dict)
    naive_total_bytes: int = Field(..., ge=0)
    shared_total_bytes: int = Field(..., ge=0)
    savings_bytes: int = Field(...)
    savings_pct: float = Field(...)


class SavedIllustrativeCapacityPlan(BaseModel):
    """One historical, persisted `IllustrativeCapacityPlan` snapshot --
    Phase 18B (`problems_final_review.md` P3-3, resolved: "illustrative
    capacity scenarios are stateless; nothing can be saved/compared over
    time"). Written by
    `control_plane.domain.capacity.scenario_history.CapacityScenarioHistoryRepository`.
    `saved_plan_id` is distinct from `plan.scenario.scenario_id` -- the
    same scenario could in principle be saved more than once, and each
    save is its own historical point, never updated in place."""

    saved_plan_id: UUID = Field(default_factory=uuid4)
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    plan: IllustrativeCapacityPlan


__all__ = [
    "DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS",
    "DEFAULT_PRODUCTION_BASELINE_BYTES",
    "TERABYTE_BYTES",
    "CapacityPlan",
    "CompressionMeasurement",
    "DatasetVersionFootprint",
    "EnvironmentCapacityDemand",
    "EnvironmentCapacityRequirement",
    "FootprintMeasurementReport",
    "IllustrativeCapacityPlan",
    "IllustrativeCapacityScenario",
    "IncrementalRefreshEstimate",
    "PartitionSummary",
    "SavedIllustrativeCapacityPlan",
    "VacuumCandidate",
]
