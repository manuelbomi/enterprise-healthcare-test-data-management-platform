"""Smoke tests for healthcare_tdm_contracts.

Phase 0 scope: these contracts have no behavior beyond validation, so the
tests here only confirm that every model can be constructed with valid
data and rejects obviously invalid data. Behavioral tests belong to the
services that use these contracts, added as each phase implements them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from healthcare_tdm_contracts import (
    AuditEvent,
    AuditEventType,
    ClassificationTier,
    ColumnClassification,
    JobRequest,
    JobStatus,
    JobType,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    ObjectRef,
    SnapshotRecord,
    SnapshotStatus,
    StorageBackend,
)


def test_column_classification_round_trip() -> None:
    classification = ColumnClassification(
        source_system="ehr-synthetic",
        dataset="patients",
        column="mrn",
        tier=ClassificationTier.DIRECT_IDENTIFIER,
        confidence=0.98,
        detector="pattern:mrn-format",
    )
    assert classification.confirmed_by is None
    assert ColumnClassification.model_validate_json(classification.model_dump_json()) == classification


def test_column_classification_confidence_must_be_in_unit_range() -> None:
    with pytest.raises(ValidationError):
        ColumnClassification(
            source_system="ehr-synthetic",
            dataset="patients",
            column="mrn",
            tier=ClassificationTier.DIRECT_IDENTIFIER,
            confidence=1.5,
            detector="pattern:mrn-format",
        )


def test_masking_policy_with_rules() -> None:
    policy = MaskingPolicy(
        name="default-patient-policy",
        version=1,
        rules=[
            MaskingRule(
                tier=ClassificationTier.DIRECT_IDENTIFIER,
                strategy=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
                scope="patient-id-global",
            ),
            MaskingRule(
                tier=ClassificationTier.NON_SENSITIVE,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="n/a",
            ),
        ],
    )
    assert len(policy.rules) == 2


def test_job_request_requires_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        JobRequest(
            job_type=JobType.SUBSETTING,
            source_system="ehr-synthetic",
            dataset="patients",
            target_environment="qa-claims",
            requested_by="test.user",
        )  # type: ignore[call-arg]


def test_job_request_defaults() -> None:
    job = JobRequest(
        job_type=JobType.SUBSETTING,
        source_system="ehr-synthetic",
        dataset="patients",
        target_environment="qa-claims",
        idempotency_key="req-0001",
        requested_by="test.user",
    )
    # JobRequest itself carries no status field; JobResult (reported back
    # by the data plane) is what tracks lifecycle status.
    assert job.job_id is not None


def test_snapshot_record_references_storage_and_job() -> None:
    snapshot = SnapshotRecord(
        dataset="patients",
        version=1,
        target_environment="qa-claims",
        status=SnapshotStatus.PUBLISHED,
        storage_ref=ObjectRef(backend=StorageBackend.MINIO, bucket="tdm-snapshots", key="patients/v1.parquet"),
        source_job_id="00000000-0000-0000-0000-000000000000",
        policy_version=1,
        refresh_cadence="weekly",
    )
    assert snapshot.storage_ref.backend == StorageBackend.MINIO


def test_audit_event_type_is_closed_enum() -> None:
    event = AuditEvent(
        event_type=AuditEventType.ACCESS_DENIED,
        actor="test.user",
        subject="dataset:patients",
        outcome="denied",
    )
    assert event.event_type == AuditEventType.ACCESS_DENIED


def test_job_status_enum_values() -> None:
    assert {s.value for s in JobStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }
