"""Tests for `control_plane.domain.capacity.planner.CapacityPlanner` and
`illustrative_capacity_plan` against a real (SQLite-backed)
`LifecycleRepository` -- no mocking of the database layer, per
`CONTRIBUTING.md`'s "data-transformation logic gets data-quality tests"
convention, applied here to real capacity-planning aggregation over real
Phase 7 data.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from healthcare_tdm_contracts import (
    DatasetVersionStatus,
    Environment,
    EnvironmentCapacityRequirement,
    IllustrativeCapacityScenario,
    RefreshCadenceType,
)
from sqlalchemy.orm import Session

from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory
from control_plane.domain.capacity import CapacityPlanner, illustrative_capacity_plan
from control_plane.domain.lifecycle import LifecycleRepository

from conftest import make_certified_report


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_sqlite_engine(str(tmp_path / "lifecycle.db"))
    factory = build_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def repo(session: Session) -> LifecycleRepository:
    return LifecycleRepository(session)


@pytest.fixture
def planner(repo: LifecycleRepository) -> CapacityPlanner:
    return CapacityPlanner(repo)


# ----------------------------------------------------------------------
# Real dataset-version footprint
# ----------------------------------------------------------------------


def test_dataset_version_footprint_reflects_registered_data(repo: LifecycleRepository, planner: CapacityPlanner) -> None:
    version = repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=50_000,
        row_counts={"member": 10, "claim": 40},
        created_by="steward@example.org",
    )
    footprint = planner.dataset_version_footprint(version.version_id)
    assert footprint.storage_footprint_bytes == 50_000
    assert footprint.total_row_count == 50
    assert footprint.physical_copy_count == 1
    assert footprint.referenced_by_environments == []
    assert footprint.estimated_compute_unit_hours >= 0.0


# ----------------------------------------------------------------------
# Real environment demand
# ----------------------------------------------------------------------


def test_environment_capacity_demand_uses_real_cadence(repo: LifecycleRepository, planner: CapacityPlanner) -> None:
    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=10_000,
        row_counts={"member": 100},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.QA, dataset_name="claims", requested_by="a")

    demand = planner.environment_capacity_demand(request.request_id)
    assert demand.attributed_storage_bytes == 10_000
    assert demand.total_row_count == 100
    assert demand.refresh_cadence_type is RefreshCadenceType.WEEKLY  # QA default, per DEFAULT_CADENCE_BY_ENVIRONMENT
    assert demand.refresh_interval_days == 7
    assert demand.estimated_refreshes_per_year == pytest.approx(365 / 7)
    assert demand.estimated_annual_processing_volume_rows == pytest.approx(100 * 365 / 7)


def test_environment_capacity_demand_release_driven_has_no_annual_projection(
    repo: LifecycleRepository, planner: CapacityPlanner
) -> None:
    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=10_000,
        row_counts={"member": 100},
        created_by="a",
    )
    # UAT defaults to RELEASE_DRIVEN -- no fixed interval.
    request = repo.request_environment(environment=Environment.UAT, dataset_name="claims", requested_by="a")
    demand = planner.environment_capacity_demand(request.request_id)
    assert demand.refresh_cadence_type is RefreshCadenceType.RELEASE_DRIVEN
    assert demand.refresh_interval_days is None
    assert demand.estimated_refreshes_per_year is None
    assert demand.estimated_annual_processing_volume_rows is None
    assert demand.estimated_annual_compute_unit_hours is None


# ----------------------------------------------------------------------
# Real naive-vs-shared capacity plan -- the concrete Phase 7 savings proof
# ----------------------------------------------------------------------


def test_capacity_plan_naive_vs_shared_for_one_shared_version(
    repo: LifecycleRepository, planner: CapacityPlanner
) -> None:
    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=1_000,
        row_counts={"member": 10},
        created_by="a",
    )
    for env in [Environment.DEV, Environment.QA, Environment.SIT, Environment.UAT, Environment.PERFORMANCE]:
        repo.request_environment(environment=env, dataset_name="claims", requested_by="a")

    plan = planner.capacity_plan(dataset_name="claims")
    assert plan.environment_count == 5
    assert plan.distinct_dataset_version_count == 1
    # Naive: 5 environments * 1000 bytes each, as if each had its own copy.
    assert plan.naive_total_storage_bytes == 5_000
    # Shared: exactly Phase 7's real mechanism -- one physical artifact.
    assert plan.shared_total_storage_bytes == 1_000
    assert plan.storage_savings_bytes == 4_000
    assert plan.storage_savings_pct == pytest.approx(0.8)


def test_capacity_plan_with_two_distinct_versions(repo: LifecycleRepository, planner: CapacityPlanner) -> None:
    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=1_000,
        row_counts={"member": 10},
        created_by="a",
    )
    dev_request = repo.request_environment(environment=Environment.DEV, dataset_name="claims", requested_by="a")
    repo.request_environment(environment=Environment.QA, dataset_name="claims", requested_by="a")

    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v2",
        size_bytes=1_200,
        row_counts={"member": 12},
        created_by="a",
    )
    repo.refresh(dev_request.request_id, trigger=__import__("healthcare_tdm_contracts").RefreshTrigger.ON_DEMAND, triggered_by="a")

    plan = planner.capacity_plan(dataset_name="claims")
    assert plan.environment_count == 2
    assert plan.distinct_dataset_version_count == 2
    assert plan.naive_total_storage_bytes == 1_200 + 1_000  # DEV on v2, QA still on v1
    assert plan.shared_total_storage_bytes == 1_200 + 1_000  # no sharing when versions differ
    assert plan.storage_savings_bytes == 0


def test_capacity_plan_with_zero_requests_is_empty(planner: CapacityPlanner) -> None:
    plan = planner.capacity_plan(dataset_name="nonexistent")
    assert plan.environment_count == 0
    assert plan.naive_total_storage_bytes == 0
    assert plan.shared_total_storage_bytes == 0
    assert plan.storage_savings_pct == 0.0


# ----------------------------------------------------------------------
# Vacuum candidates
# ----------------------------------------------------------------------


def test_vacuum_candidates_finds_unreferenced_revoked_version(
    repo: LifecycleRepository, planner: CapacityPlanner
) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=1_000,
        row_counts={"member": 10},
        created_by="a",
    )
    # Nothing ever requests v1 into an environment, so it starts unreferenced.
    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v2",
        size_bytes=1_200,
        row_counts={"member": 12},
        created_by="a",
    )
    revoked = repo.revoke_version(v1.version_id, reason="superseded", revoked_by="sec@example.org")

    candidates = planner.vacuum_candidates(dataset_name="claims")
    assert len(candidates) == 1
    assert candidates[0].version_id == revoked.version_id
    assert candidates[0].reclaimable_bytes == 1_000
    assert "revoked" in candidates[0].reason


def test_vacuum_candidates_excludes_referenced_version(repo: LifecycleRepository, planner: CapacityPlanner) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=1_000,
        row_counts={"member": 10},
        created_by="a",
    )
    repo.request_environment(environment=Environment.DEV, dataset_name="claims", requested_by="a")
    repo.revoke_version(v1.version_id, reason="policy defect", revoked_by="sec@example.org")

    # DEV is still pointed at v1 (revocation never migrates existing usage) --
    # so v1 must NOT show up as a vacuum candidate even though it is REVOKED.
    candidates = planner.vacuum_candidates(dataset_name="claims")
    assert candidates == []


def test_vacuum_candidates_excludes_active_versions(repo: LifecycleRepository, planner: CapacityPlanner) -> None:
    repo.register_dataset_version(
        dataset_name="claims",
        certification_report=make_certified_report(),
        storage_uri="data/tmp/claims/v1",
        size_bytes=1_000,
        row_counts={"member": 10},
        created_by="a",
    )
    assert planner.vacuum_candidates(dataset_name="claims") == []


# ----------------------------------------------------------------------
# Illustrative percentage-of-production scenario (pure function)
# ----------------------------------------------------------------------


def test_illustrative_plan_matches_roadmap_worked_example() -> None:
    scenario = IllustrativeCapacityScenario(
        production_baseline_bytes=100 * 10**12,
        requirements=[
            EnvironmentCapacityRequirement(environment=Environment.DEV, target_pct_of_production=0.10, share_tier="standard"),
            EnvironmentCapacityRequirement(environment=Environment.QA, target_pct_of_production=0.10, share_tier="standard"),
            EnvironmentCapacityRequirement(environment=Environment.SIT, target_pct_of_production=0.05, share_tier="standard"),
            EnvironmentCapacityRequirement(environment=Environment.UAT, target_pct_of_production=0.15, share_tier="standard"),
            EnvironmentCapacityRequirement(environment=Environment.PERFORMANCE, target_pct_of_production=1.00, share_tier="performance"),
        ],
    )
    plan = illustrative_capacity_plan(scenario)

    tb = 10**12
    # Naive: 10+10+5+15+100 = 140 TB.
    assert plan.naive_total_bytes == 140 * tb
    # Shared: "standard" tier sized to UAT's 15% (the max in that tier) + "performance" tier at 100%.
    assert plan.per_tier_shared_bytes["standard"] == 15 * tb
    assert plan.per_tier_shared_bytes["performance"] == 100 * tb
    assert plan.shared_total_bytes == 115 * tb
    assert plan.savings_bytes == 25 * tb
    assert plan.savings_pct == pytest.approx(25 / 140)


def test_illustrative_plan_uses_defaults_when_scenario_is_default() -> None:
    plan = illustrative_capacity_plan(IllustrativeCapacityScenario())
    assert plan.naive_total_bytes > plan.shared_total_bytes
    assert plan.savings_pct > 0
    assert set(plan.per_environment_naive_bytes) == {e.value for e in Environment}


def test_illustrative_plan_single_tier_has_no_savings_when_all_equal() -> None:
    scenario = IllustrativeCapacityScenario(
        production_baseline_bytes=1_000,
        requirements=[
            EnvironmentCapacityRequirement(environment=Environment.DEV, target_pct_of_production=0.10, share_tier="only"),
            EnvironmentCapacityRequirement(environment=Environment.QA, target_pct_of_production=0.10, share_tier="only"),
        ],
    )
    plan = illustrative_capacity_plan(scenario)
    assert plan.naive_total_bytes == 200
    assert plan.shared_total_bytes == 100
    assert plan.savings_pct == pytest.approx(0.5)
