"""Smoke tests for the Phase 7 dataset lifecycle contracts
(`healthcare_tdm_contracts.lifecycle`).

Consistent with `test_certification_contract.py`'s scope note: these
contracts have no behavior beyond validation and the documented
transition-table/default-cadence data. The actual enforcement (state
machine, cadence computation, the refresh scheduler abstraction) lives
in `control_plane.domain.lifecycle` and is tested there against a real
SQLite-backed repository.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from healthcare_tdm_contracts import (
    DATASET_VERSION_STATUS_TRANSITIONS,
    DEFAULT_CADENCE_BY_ENVIRONMENT,
    DEFAULT_INTERVAL_DAYS_BY_CADENCE,
    DatasetVersion,
    DatasetVersionStatus,
    Environment,
    EnvironmentDatasetRequest,
    RefreshCadenceType,
    RefreshPolicy,
)


def test_environment_has_all_five_required_environments() -> None:
    assert {e.value for e in Environment} == {"dev", "qa", "sit", "uat", "performance"}


def test_every_environment_has_a_default_cadence() -> None:
    assert set(DEFAULT_CADENCE_BY_ENVIRONMENT) == set(Environment)


def test_default_cadence_matches_roadmap_demonstration_defaults() -> None:
    assert DEFAULT_CADENCE_BY_ENVIRONMENT[Environment.DEV] is RefreshCadenceType.WEEKLY
    assert DEFAULT_CADENCE_BY_ENVIRONMENT[Environment.QA] is RefreshCadenceType.WEEKLY
    assert DEFAULT_CADENCE_BY_ENVIRONMENT[Environment.SIT] is RefreshCadenceType.BIWEEKLY
    assert DEFAULT_CADENCE_BY_ENVIRONMENT[Environment.UAT] is RefreshCadenceType.RELEASE_DRIVEN
    assert DEFAULT_CADENCE_BY_ENVIRONMENT[Environment.PERFORMANCE] is RefreshCadenceType.MONTHLY


def test_default_interval_days_covers_every_cadence_type() -> None:
    assert set(DEFAULT_INTERVAL_DAYS_BY_CADENCE) == set(RefreshCadenceType)
    assert DEFAULT_INTERVAL_DAYS_BY_CADENCE[RefreshCadenceType.WEEKLY] == 7
    assert DEFAULT_INTERVAL_DAYS_BY_CADENCE[RefreshCadenceType.BIWEEKLY] == 14
    assert DEFAULT_INTERVAL_DAYS_BY_CADENCE[RefreshCadenceType.MONTHLY] == 30
    assert DEFAULT_INTERVAL_DAYS_BY_CADENCE[RefreshCadenceType.RELEASE_DRIVEN] is None
    assert DEFAULT_INTERVAL_DAYS_BY_CADENCE[RefreshCadenceType.ON_DEMAND] is None


def test_dataset_version_status_transition_table_covers_every_status() -> None:
    assert set(DATASET_VERSION_STATUS_TRANSITIONS) == set(DatasetVersionStatus)


def test_revoked_is_terminal() -> None:
    assert DATASET_VERSION_STATUS_TRANSITIONS[DatasetVersionStatus.REVOKED] == frozenset()


def test_rolled_back_can_return_to_active_or_be_revoked() -> None:
    assert DATASET_VERSION_STATUS_TRANSITIONS[DatasetVersionStatus.ROLLED_BACK] == frozenset(
        {DatasetVersionStatus.ACTIVE, DatasetVersionStatus.REVOKED}
    )


def test_expired_can_only_move_to_revoked() -> None:
    assert DATASET_VERSION_STATUS_TRANSITIONS[DatasetVersionStatus.EXPIRED] == frozenset(
        {DatasetVersionStatus.REVOKED}
    )


def test_dataset_version_defaults_to_active() -> None:
    version = DatasetVersion(
        dataset_name="tiny-fixed_population",
        version_number=1,
        certification_report_id=uuid4(),
        masking_policy_name="phase3-default",
        masking_policy_version=1,
        masking_engine_version="1.0.0",
        storage_uri="data/tmp/certification-run",
        size_bytes=1024,
        created_by="test-user@example.org",
    )
    assert version.status is DatasetVersionStatus.ACTIVE
    assert version.referenced_by_environments == []


def test_dataset_version_round_trips_through_json() -> None:
    version = DatasetVersion(
        dataset_name="tiny-fixed_population",
        version_number=2,
        certification_report_id=uuid4(),
        masking_policy_name="phase3-default",
        masking_policy_version=1,
        masking_engine_version="1.0.0",
        storage_uri="data/tmp/certification-run",
        size_bytes=2048,
        row_counts={"member": 10, "claim": 42},
        created_by="test-user@example.org",
        referenced_by_environments=[Environment.DEV, Environment.QA],
    )
    assert DatasetVersion.model_validate_json(version.model_dump_json()) == version


def test_environment_dataset_request_requires_environment_and_dataset() -> None:
    with pytest.raises(ValidationError):
        EnvironmentDatasetRequest()  # type: ignore[call-arg]


def test_refresh_policy_defaults_allow_on_demand() -> None:
    policy = RefreshPolicy(environment=Environment.UAT, cadence_type=RefreshCadenceType.RELEASE_DRIVEN)
    assert policy.on_demand_allowed is True
    assert policy.dataset_name is None
    assert policy.policy_version == 1
