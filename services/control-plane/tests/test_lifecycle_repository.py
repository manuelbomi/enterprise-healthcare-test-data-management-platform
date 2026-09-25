"""Tests for `control_plane.domain.lifecycle.repository.LifecycleRepository`
against a real (SQLite-backed) session -- no mocking of the database
layer, per `CONTRIBUTING.md`'s "data-transformation logic gets
data-quality tests" convention applied to this phase's domain logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from healthcare_tdm_contracts import (
    CertificationStatus,
    DatasetVersionStatus,
    Environment,
    EnvironmentRequestStatus,
    RefreshCadenceType,
    RefreshTrigger,
)
from sqlalchemy.orm import Session

from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory
from control_plane.domain.lifecycle import (
    CannotSelectRevokedVersionError,
    InvalidDatasetVersionTransitionError,
    LifecycleRepository,
    LocalRefreshOrchestrator,
    NoActiveDatasetVersionError,
    OnDemandRefreshNotAllowedError,
)

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


# ----------------------------------------------------------------------
# Dataset version registration
# ----------------------------------------------------------------------


def test_register_dataset_version_from_certified_report(repo: LifecycleRepository) -> None:
    report = make_certified_report()
    version = repo.register_dataset_version(
        dataset_name="tiny-fixed_population",
        certification_report=report,
        storage_uri="data/tmp/certification-run",
        size_bytes=123_456,
        row_counts={"member": 10, "claim": 42},
        created_by="steward@example.org",
    )
    assert version.version_number == 1
    assert version.status is DatasetVersionStatus.ACTIVE
    assert version.certification_report_id == report.report_id
    assert version.masking_policy_version == 1
    assert version.expires_at is not None
    assert version.referenced_by_environments == []


def test_register_dataset_version_rejects_non_certified_report(repo: LifecycleRepository) -> None:
    draft_report = make_certified_report(status=CertificationStatus.DRAFT)
    with pytest.raises(ValueError, match="CERTIFIED or PUBLISHED"):
        repo.register_dataset_version(
            dataset_name="tiny-fixed_population",
            certification_report=draft_report,
            storage_uri="data/tmp/certification-run",
            size_bytes=1,
            row_counts={},
            created_by="steward@example.org",
        )


def test_register_dataset_version_increments_version_number(repo: LifecycleRepository) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-1",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    v2 = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-2",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    assert v1.version_number == 1
    assert v2.version_number == 2


# ----------------------------------------------------------------------
# Refresh policy defaults / cadence
# ----------------------------------------------------------------------


def test_default_cadence_for_all_five_environments(repo: LifecycleRepository) -> None:
    expected = {
        Environment.DEV: RefreshCadenceType.WEEKLY,
        Environment.QA: RefreshCadenceType.WEEKLY,
        Environment.SIT: RefreshCadenceType.BIWEEKLY,
        Environment.UAT: RefreshCadenceType.RELEASE_DRIVEN,
        Environment.PERFORMANCE: RefreshCadenceType.MONTHLY,
    }
    for env, cadence_type in expected.items():
        policy = repo.get_or_create_default_policy(env)
        assert policy.cadence_type is cadence_type
        assert policy.on_demand_allowed is True


def test_upsert_policy_bumps_policy_version(repo: LifecycleRepository) -> None:
    p1 = repo.upsert_policy(
        environment=Environment.DEV,
        dataset_name=None,
        cadence_type=RefreshCadenceType.WEEKLY,
        interval_days=7,
        retention_days=90,
        grace_period_days=3,
        on_demand_allowed=True,
    )
    assert p1.policy_version == 1
    p2 = repo.upsert_policy(
        environment=Environment.DEV,
        dataset_name=None,
        cadence_type=RefreshCadenceType.WEEKLY,
        interval_days=3,
        retention_days=90,
        grace_period_days=3,
        on_demand_allowed=True,
    )
    assert p2.policy_version == 2
    assert p2.interval_days == 3


# ----------------------------------------------------------------------
# Environment requests: avoiding duplicate physical copies
# ----------------------------------------------------------------------


def test_request_environment_requires_an_active_version(repo: LifecycleRepository) -> None:
    with pytest.raises(NoActiveDatasetVersionError):
        repo.request_environment(environment=Environment.DEV, dataset_name="nope", requested_by="a")


def test_two_environments_requesting_same_dataset_share_one_physical_version(
    repo: LifecycleRepository,
) -> None:
    version = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="single-physical-location",
        size_bytes=999,
        row_counts={},
        created_by="a",
    )
    dev_request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    qa_request = repo.request_environment(environment=Environment.QA, dataset_name="ds", requested_by="b")

    assert dev_request.current_version_id == version.version_id
    assert qa_request.current_version_id == version.version_id

    refreshed_version = repo.get_version(version.version_id)
    assert set(refreshed_version.referenced_by_environments) == {Environment.DEV, Environment.QA}


def test_request_environment_is_idempotent_per_environment_dataset_pair(
    repo: LifecycleRepository,
) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    first = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    second = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    assert first.request_id == second.request_id


def test_next_refresh_at_computed_per_cadence_for_all_five_environments(
    repo: LifecycleRepository,
) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    requests = {
        env: repo.request_environment(environment=env, dataset_name="ds", requested_by="a")
        for env in Environment
    }

    dev = requests[Environment.DEV]
    qa = requests[Environment.QA]
    sit = requests[Environment.SIT]
    uat = requests[Environment.UAT]
    perf = requests[Environment.PERFORMANCE]

    assert dev.next_refresh_at is not None
    assert (dev.next_refresh_at - dev.requested_at) == timedelta(days=7)
    assert (qa.next_refresh_at - qa.requested_at) == timedelta(days=7)
    assert (sit.next_refresh_at - sit.requested_at) == timedelta(days=14)
    assert uat.next_refresh_at is None  # release-driven: no fixed schedule
    assert (perf.next_refresh_at - perf.requested_at) == timedelta(days=30)


# ----------------------------------------------------------------------
# Refresh
# ----------------------------------------------------------------------


def test_on_demand_refresh_updates_schedule_and_records_run(repo: LifecycleRepository) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    assert request.last_refresh_at is None

    run = repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="qa-engineer")
    assert run.succeeded is True
    assert run.trigger is RefreshTrigger.ON_DEMAND

    refreshed = repo.get_request(request.request_id)
    assert refreshed.last_refresh_at is not None
    assert refreshed.next_refresh_at is not None


def test_on_demand_refresh_rejected_when_policy_disallows_it(repo: LifecycleRepository) -> None:
    repo.upsert_policy(
        environment=Environment.UAT,
        dataset_name=None,
        cadence_type=RefreshCadenceType.RELEASE_DRIVEN,
        interval_days=None,
        retention_days=90,
        grace_period_days=3,
        on_demand_allowed=False,
    )
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.UAT, dataset_name="ds", requested_by="a")
    with pytest.raises(OnDemandRefreshNotAllowedError):
        repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")


def test_refreshing_moves_environment_onto_newer_active_version(repo: LifecycleRepository) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-1",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    assert request.current_version_number == 1

    v2 = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-2",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    run = repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")
    assert run.resulting_version_id == v2.version_id
    assert run.previous_version_id == v1.version_id

    updated = repo.get_request(request.request_id)
    assert updated.current_version_number == 2


# ----------------------------------------------------------------------
# Rollback
# ----------------------------------------------------------------------


def test_rollback_moves_pointer_and_marks_from_version_rolled_back(repo: LifecycleRepository) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-1",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-2",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")  # now on v2

    rollback = repo.rollback(
        request.request_id, to_version_number=1, performed_by="oncall@example.org", reason="v2 broke the build"
    )
    assert rollback.to_version_number == 1
    assert rollback.from_version_number == 2

    updated_request = repo.get_request(request.request_id)
    assert updated_request.current_version_number == 1

    v1_after = repo.get_version(v1.version_id)
    assert v1_after.status is DatasetVersionStatus.ACTIVE  # rolled back TO -> active again

    v2_after = repo.list_versions(dataset_name="ds")[1]
    assert v2_after.status is DatasetVersionStatus.ROLLED_BACK  # nothing references it anymore


def test_rollback_refuses_a_revoked_target_version(repo: LifecycleRepository) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-1",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-2",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")
    repo.revoke_version(v1.version_id, reason="known defect", revoked_by="security@example.org")

    with pytest.raises(CannotSelectRevokedVersionError):
        repo.rollback(request.request_id, to_version_number=1, performed_by="a", reason="try anyway")


def test_rollback_sharing_from_version_with_another_environment_does_not_change_its_status(
    repo: LifecycleRepository,
) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-1",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    dev_request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    repo.request_environment(environment=Environment.QA, dataset_name="ds", requested_by="a")  # also on v1

    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri-2",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    repo.refresh(dev_request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")  # dev -> v2
    repo.rollback(dev_request.request_id, to_version_number=1, performed_by="a", reason="rollback dev only")

    v1_status = repo.list_versions(dataset_name="ds")[0].status
    # QA is still on v1, so it must remain ACTIVE, never ROLLED_BACK.
    assert v1_status is DatasetVersionStatus.ACTIVE


# ----------------------------------------------------------------------
# Revocation
# ----------------------------------------------------------------------


def test_revoke_requires_a_reason(repo: LifecycleRepository) -> None:
    version = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    with pytest.raises(ValueError):
        repo.revoke_version(version.version_id, reason="   ", revoked_by="a")


def test_revoke_is_terminal_and_blocks_future_selection(repo: LifecycleRepository) -> None:
    version = repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    revoked = repo.revoke_version(version.version_id, reason="policy defect discovered", revoked_by="sec")
    assert revoked.status is DatasetVersionStatus.REVOKED
    assert revoked.revoked_reason == "policy defect discovered"

    with pytest.raises(InvalidDatasetVersionTransitionError):
        repo.revoke_version(version.version_id, reason="again", revoked_by="sec")

    # No ACTIVE version left -> a brand-new environment request must fail.
    with pytest.raises(NoActiveDatasetVersionError):
        repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")


def test_revoke_does_not_move_an_environment_already_using_it(repo: LifecycleRepository) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    version = repo.list_versions(dataset_name="ds")[0]
    repo.revoke_version(version.version_id, reason="defect", revoked_by="sec")

    # The environment's own pointer is left untouched by revocation --
    # documented, deliberate: see DatasetVersionStatus.REVOKED's docstring.
    still_pointing = repo.get_request(request.request_id)
    assert still_pointing.current_version_id == version.version_id
    assert still_pointing.status is EnvironmentRequestStatus.ACTIVE


# ----------------------------------------------------------------------
# Retention / expiry
# ----------------------------------------------------------------------


def test_apply_retention_expires_versions_past_their_window(repo: LifecycleRepository) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
        retention_days=1,
    )
    version = repo.list_versions(dataset_name="ds")[0]
    assert version.status is DatasetVersionStatus.ACTIVE

    far_future = datetime.now(timezone.utc) + timedelta(days=10)
    expired = repo.apply_retention(as_of=far_future)
    assert len(expired) == 1
    assert expired[0].version_id == version.version_id
    assert repo.get_version(version.version_id).status is DatasetVersionStatus.EXPIRED


# ----------------------------------------------------------------------
# Orchestration abstraction
# ----------------------------------------------------------------------


def test_local_refresh_orchestrator_finds_due_requests_and_runs_them(repo: LifecycleRepository) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")

    orchestrator = LocalRefreshOrchestrator(repo)
    not_yet_due = orchestrator.due_refreshes(as_of=datetime.now(timezone.utc))
    assert request.request_id not in {r.request_id for r in not_yet_due}

    far_future = datetime.now(timezone.utc) + timedelta(days=30)
    due = orchestrator.due_refreshes(as_of=far_future)
    assert request.request_id in {r.request_id for r in due}

    sweep = orchestrator.run_due_refreshes(as_of=far_future, triggered_by="scheduler-sweep")
    assert len(sweep.results) == 1
    assert sweep.results[0].trigger.value == "scheduled"
    assert not sweep.errors


def test_release_driven_uat_is_never_due_automatically(repo: LifecycleRepository) -> None:
    repo.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(),
        storage_uri="uri",
        size_bytes=1,
        row_counts={},
        created_by="a",
    )
    repo.request_environment(environment=Environment.UAT, dataset_name="ds", requested_by="a")

    orchestrator = LocalRefreshOrchestrator(repo)
    far_future = datetime.now(timezone.utc) + timedelta(days=365)
    due = orchestrator.due_refreshes(as_of=far_future)
    assert due == []  # release-driven: next_refresh_at is always None, never "due"


# ----------------------------------------------------------------------
# Phase 13: refresh/rollback history read methods
# ----------------------------------------------------------------------


def test_list_refresh_runs_returns_history_most_recent_first(repo: LifecycleRepository) -> None:
    repo.register_dataset_version(
        dataset_name="ds", certification_report=make_certified_report(), storage_uri="uri-1",
        size_bytes=1, row_counts={}, created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")

    assert repo.list_refresh_runs(dataset_name="ds") == []  # nothing run yet

    first = repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")
    repo.register_dataset_version(
        dataset_name="ds", certification_report=make_certified_report(), storage_uri="uri-2",
        size_bytes=1, row_counts={}, created_by="a",
    )
    second = repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="b")

    runs = repo.list_refresh_runs(dataset_name="ds")
    assert [r.run_id for r in runs] == [second.run_id, first.run_id]  # most recent first
    assert all(r.dataset_name == "ds" for r in runs)

    scoped = repo.list_refresh_runs(request_id=request.request_id)
    assert len(scoped) == 2

    other_dataset = repo.list_refresh_runs(dataset_name="some-other-dataset")
    assert other_dataset == []


def test_list_rollback_events_fills_in_version_numbers(repo: LifecycleRepository) -> None:
    v1 = repo.register_dataset_version(
        dataset_name="ds", certification_report=make_certified_report(), storage_uri="uri-1",
        size_bytes=1, row_counts={}, created_by="a",
    )
    request = repo.request_environment(environment=Environment.DEV, dataset_name="ds", requested_by="a")
    v2 = repo.register_dataset_version(
        dataset_name="ds", certification_report=make_certified_report(), storage_uri="uri-2",
        size_bytes=1, row_counts={}, created_by="a",
    )
    repo.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")  # now on v2

    assert repo.list_rollback_events(dataset_name="ds") == []  # nothing rolled back yet

    rollback = repo.rollback(
        request.request_id, to_version_number=1, performed_by="oncall@example.org", reason="v2 broke the build"
    )

    events = repo.list_rollback_events(dataset_name="ds")
    assert len(events) == 1
    assert events[0].rollback_id == rollback.rollback_id
    assert events[0].from_version_id == v2.version_id
    assert events[0].from_version_number == 2
    assert events[0].to_version_id == v1.version_id
    assert events[0].to_version_number == 1

    scoped = repo.list_rollback_events(request_id=request.request_id)
    assert len(scoped) == 1
