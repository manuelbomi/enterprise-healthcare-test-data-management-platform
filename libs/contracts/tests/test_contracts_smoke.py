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
    TIER_BY_CATEGORY,
    AuditEvent,
    AuditEventType,
    CatalogEntry,
    ClassificationMethod,
    ClassificationTier,
    ColumnClassification,
    IntegrityStatus,
    JobRequest,
    JobStatus,
    JobType,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    ObjectRef,
    RelationshipEdge,
    RetentionClassification,
    ScaleProfileName,
    SensitivityCategory,
    SnapshotRecord,
    SnapshotStatus,
    SourceDatasetDescriptor,
    SourceSystemType,
    StorageBackend,
    SubsetManifest,
    SubsetSelectionCriteria,
    SubsettingStrategy,
)


def test_column_classification_round_trip() -> None:
    classification = ColumnClassification(
        source_system="ehr-synthetic",
        dataset="patients",
        column="mrn",
        tier=ClassificationTier.DIRECT_IDENTIFIER,
        category=SensitivityCategory.DIRECT_IDENTIFIER,
        confidence=0.98,
        detector="pattern:mrn-format",
        method=ClassificationMethod.RULE_BASED,
        reason="Column name matches the medical-record-number pattern.",
    )
    assert classification.confirmed_by is None
    assert ColumnClassification.model_validate_json(classification.model_dump_json()) == classification


def test_column_classification_backfills_category_from_tier() -> None:
    classification = ColumnClassification(
        source_system="ehr-synthetic",
        dataset="patients",
        column="mrn",
        tier=ClassificationTier.DIRECT_IDENTIFIER,
        confidence=0.98,
        detector="pattern:mrn-format",
    )
    assert classification.category == SensitivityCategory.DIRECT_IDENTIFIER


def test_column_classification_needs_review_below_confidence_threshold() -> None:
    low_confidence = ColumnClassification(
        source_system="ehr-synthetic",
        dataset="patients",
        column="notes",
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        category=SensitivityCategory.SENSITIVE,
        confidence=0.3,
        detector="fallback:no-match",
    )
    assert low_confidence.needs_review is True

    confirmed = low_confidence.model_copy(update={"confirmed_by": "steward.jane"})
    assert confirmed.needs_review is False

    high_confidence = low_confidence.model_copy(update={"confidence": 0.95})
    assert high_confidence.needs_review is False


def test_sensitivity_category_is_closed_enum_with_six_values() -> None:
    assert {c.value for c in SensitivityCategory} == {
        "direct_identifier",
        "quasi_identifier",
        "phi",
        "pii",
        "sensitive",
        "non_sensitive",
    }
    assert set(TIER_BY_CATEGORY) == set(SensitivityCategory)


def test_catalog_entry_composes_classification() -> None:
    entry = CatalogEntry(
        classification=ColumnClassification(
            source_system="postgres_enrollment",
            dataset="member",
            column="ssn",
            tier=ClassificationTier.DIRECT_IDENTIFIER,
            category=SensitivityCategory.DIRECT_IDENTIFIER,
            confidence=1.0,
            detector="schema:Member.ssn",
            method=ClassificationMethod.SCHEMA_BASED,
            reason="Explicit schema entry for the known Member entity.",
        ),
        masking_requirement=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
        owner="Enrollment Data Engineering",
        retention_classification=RetentionClassification.EXTENDED,
    )
    assert entry.dataset == "member"
    assert entry.column == "ssn"
    assert entry.source == "postgres_enrollment"
    assert CatalogEntry.model_validate_json(entry.model_dump_json()) == entry


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


def test_source_dataset_descriptor_round_trip() -> None:
    descriptor = SourceDatasetDescriptor(
        entity="ClaimLine",
        source_system=SourceSystemType.OBJECT_STORAGE_CLAIMS_PARQUET,
        storage_format="parquet",
        location="claims-warehouse/claim_line",
        row_count=1234,
        scale_profile=ScaleProfileName.TINY,
    )
    assert (
        SourceDatasetDescriptor.model_validate_json(descriptor.model_dump_json())
        == descriptor
    )


def test_source_system_type_is_closed_enum() -> None:
    assert {s.value for s in SourceSystemType} == {
        "postgres_enrollment",
        "object_storage_claims_parquet",
        "s3_clinical_data_lake",
        "adls_pbm_extract",
        "partner_lab_feed",
    }


def test_subsetting_strategy_has_all_six_required_strategies() -> None:
    assert {s.value for s in SubsettingStrategy} == {
        "percentage",
        "fixed_population",
        "stratified",
        "date_window",
        "business_rule",
        "risk_edge_case",
    }


def test_subset_manifest_round_trip() -> None:
    manifest = SubsetManifest(
        scale_profile="tiny",
        selection=SubsetSelectionCriteria(
            strategy=SubsettingStrategy.FIXED_POPULATION,
            parameters={"count": "8"},
            description="Fixed population of 8",
        ),
        source_counts={"member": 26},
        selected_counts={"member": 8},
        relationship_edges=[RelationshipEdge(parent_entity="Member", child_entity="Coverage", edge_count=11)],
        filter_criteria={"requested_count": "8"},
        estimated_source_storage_bytes=131_764,
        estimated_subset_storage_bytes=70_640,
        integrity_status=IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS,
        known_orphan_counts={"encounter.provider_id": 1},
    )
    assert SubsetManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.selection_ratio("member") == 8 / 26
    assert manifest.selection_ratio("claim") is None  # not present in source_counts


def test_subset_manifest_requires_integrity_status() -> None:
    with pytest.raises(ValidationError):
        SubsetManifest(
            scale_profile="tiny",
            selection=SubsetSelectionCriteria(strategy=SubsettingStrategy.PERCENTAGE, parameters={"percentage": "10"}),
        )  # type: ignore[call-arg]


def test_integrity_status_is_closed_enum_with_three_values() -> None:
    assert {s.value for s in IntegrityStatus} == {"passed", "passed_with_known_orphans", "failed"}
