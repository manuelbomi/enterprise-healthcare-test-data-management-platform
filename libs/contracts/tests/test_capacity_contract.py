"""Smoke tests for the Phase 8 capacity-planning contracts
(`healthcare_tdm_contracts.capacity`).

Consistent with `test_lifecycle_contract.py`'s scope note: these
contracts have no behavior beyond validation and the documented default
data. The actual real, on-disk footprint measurement lives in
`data_plane.capacity` and the actual real, DB-backed capacity planning
lives in `control_plane.domain.capacity` -- both tested against real
data in their own packages.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from healthcare_tdm_contracts import (
    DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS,
    DEFAULT_PRODUCTION_BASELINE_BYTES,
    TERABYTE_BYTES,
    CompressionMeasurement,
    DatasetVersionFootprint,
    DatasetVersionStatus,
    Environment,
    EnvironmentCapacityRequirement,
    FootprintMeasurementReport,
    IllustrativeCapacityScenario,
    VacuumCandidate,
)


def test_terabyte_bytes_is_decimal() -> None:
    assert TERABYTE_BYTES == 1_000_000_000_000


def test_default_production_baseline_matches_roadmap_example() -> None:
    assert DEFAULT_PRODUCTION_BASELINE_BYTES == 100 * TERABYTE_BYTES


def test_default_requirements_cover_every_environment() -> None:
    envs = {r.environment for r in DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS}
    assert envs == set(Environment)


def test_default_requirements_match_roadmap_worked_example() -> None:
    by_env = {r.environment: r for r in DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS}
    assert by_env[Environment.QA].target_pct_of_production == pytest.approx(0.10)
    assert by_env[Environment.SIT].target_pct_of_production == pytest.approx(0.05)
    assert by_env[Environment.UAT].target_pct_of_production == pytest.approx(0.15)


def test_performance_is_its_own_share_tier_at_full_scale() -> None:
    by_env = {r.environment: r for r in DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS}
    performance = by_env[Environment.PERFORMANCE]
    assert performance.target_pct_of_production == pytest.approx(1.0)
    assert performance.share_tier == "performance"
    # Every non-performance environment shares the same tier so the
    # illustrative model can meaningfully compare "5 independent copies"
    # against "1 shared standard snapshot + 1 standalone performance copy".
    other_tiers = {r.share_tier for r in DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS if r.environment != Environment.PERFORMANCE}
    assert other_tiers == {"standard"}


def test_requirement_rejects_zero_and_negative_percentage() -> None:
    with pytest.raises(ValidationError):
        EnvironmentCapacityRequirement(environment=Environment.DEV, target_pct_of_production=0.0)
    with pytest.raises(ValidationError):
        EnvironmentCapacityRequirement(environment=Environment.DEV, target_pct_of_production=-0.1)


def test_requirement_rejects_more_than_100_percent() -> None:
    with pytest.raises(ValidationError):
        EnvironmentCapacityRequirement(environment=Environment.DEV, target_pct_of_production=1.5)


def test_illustrative_scenario_defaults_to_roadmap_example() -> None:
    scenario = IllustrativeCapacityScenario()
    assert scenario.production_baseline_bytes == DEFAULT_PRODUCTION_BASELINE_BYTES
    assert len(scenario.requirements) == 5


def test_compression_measurement_round_trips() -> None:
    m = CompressionMeasurement(
        source_path="data/tmp/estate/claim.parquet",
        row_count=100,
        column_count=8,
        compressed_bytes=2_000,
        uncompressed_estimate_bytes=8_000,
        compression_ratio=4.0,
    )
    assert m.compression_ratio == 4.0
    assert m.method == "parquet_on_disk_vs_in_memory_csv_reencode"


def test_footprint_report_overall_ratio_is_none_with_no_parquet() -> None:
    report = FootprintMeasurementReport(root_path="data/tmp/estate", total_bytes=100, total_file_count=1)
    assert report.overall_parquet_compression_ratio is None


def test_footprint_report_overall_ratio_aggregates_measurements() -> None:
    m1 = CompressionMeasurement(
        source_path="a.parquet", row_count=10, column_count=2,
        compressed_bytes=100, uncompressed_estimate_bytes=400, compression_ratio=4.0,
    )
    m2 = CompressionMeasurement(
        source_path="b.parquet", row_count=10, column_count=2,
        compressed_bytes=100, uncompressed_estimate_bytes=200, compression_ratio=2.0,
    )
    report = FootprintMeasurementReport(
        root_path="data/tmp/estate", total_bytes=200, total_file_count=2, parquet_compression=[m1, m2]
    )
    assert report.total_parquet_compressed_bytes == 200
    assert report.total_parquet_uncompressed_estimate_bytes == 600
    assert report.overall_parquet_compression_ratio == pytest.approx(3.0)


def test_dataset_version_footprint_physical_copy_count_defaults_to_one() -> None:
    footprint = DatasetVersionFootprint(
        version_id=uuid4(),
        dataset_name="claims",
        version_number=1,
        status=DatasetVersionStatus.ACTIVE,
        storage_footprint_bytes=1_000,
        row_counts={"member": 10},
        total_row_count=10,
        retention_days=90,
        referenced_by_environments=[Environment.DEV, Environment.QA, Environment.SIT],
        estimated_compute_unit_hours=0.001,
    )
    assert footprint.physical_copy_count == 1
    assert len(footprint.referenced_by_environments) == 3


def test_vacuum_candidate_requires_reclaimable_bytes_nonnegative() -> None:
    with pytest.raises(ValidationError):
        VacuumCandidate(
            version_id=uuid4(),
            dataset_name="claims",
            version_number=1,
            status=DatasetVersionStatus.REVOKED,
            storage_uri="data/tmp/claims/v1",
            reclaimable_bytes=-1,
            reason="test",
        )
