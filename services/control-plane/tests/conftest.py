"""Shared fixtures for control-plane tests.

`sample_catalog_path` builds a small, hand-authored catalog fixture using
only `healthcare_tdm_contracts` (never `data_plane` -- see ADR-0003: the
control plane's tests must not depend on the data plane's package). It
covers a deliberate mix of categories/tiers/review states so the catalog
API's filtering can be exercised meaningfully.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from healthcare_tdm_contracts import (
    CatalogEntry,
    ClassificationMethod,
    ClassificationTier,
    ColumnClassification,
    MaskingStrategy,
    RetentionClassification,
    SensitivityCategory,
)


def _entry(
    *,
    source_system: str,
    dataset: str,
    column: str,
    category: SensitivityCategory,
    tier: ClassificationTier,
    confidence: float,
    method: ClassificationMethod,
    masking_requirement: MaskingStrategy,
    owner: str,
    retention: RetentionClassification,
    confirmed_by: str | None = None,
) -> CatalogEntry:
    return CatalogEntry(
        classification=ColumnClassification(
            source_system=source_system,
            dataset=dataset,
            column=column,
            tier=tier,
            category=category,
            confidence=confidence,
            detector=f"test:{method.value}",
            method=method,
            reason="Fixture row for control-plane catalog API tests.",
            confirmed_by=confirmed_by,
        ),
        masking_requirement=masking_requirement,
        owner=owner,
        retention_classification=retention,
    )


SAMPLE_ENTRIES: list[CatalogEntry] = [
    _entry(
        source_system="postgres_enrollment",
        dataset="member",
        column="ssn",
        category=SensitivityCategory.DIRECT_IDENTIFIER,
        tier=ClassificationTier.DIRECT_IDENTIFIER,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.EXTENDED,
    ),
    _entry(
        source_system="postgres_enrollment",
        dataset="member",
        column="date_of_birth",
        category=SensitivityCategory.QUASI_IDENTIFIER,
        tier=ClassificationTier.QUASI_IDENTIFIER,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.GENERALIZATION,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.STANDARD,
    ),
    _entry(
        source_system="s3_clinical_data_lake",
        dataset="lab_result",
        column="test_name",
        category=SensitivityCategory.PHI,
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.SYNTHETIC_REPLACEMENT,
        owner="Clinical Data Engineering",
        retention=RetentionClassification.EXTENDED,
    ),
    _entry(
        source_system="postgres_enrollment",
        dataset="provider",
        column="npi",
        category=SensitivityCategory.PII,
        tier=ClassificationTier.QUASI_IDENTIFIER,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.GENERALIZATION,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.STANDARD,
    ),
    _entry(
        source_system="object_storage_claims_parquet",
        dataset="claim",
        column="adjustment_reason_code",
        category=SensitivityCategory.SENSITIVE,
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        confidence=0.3,
        method=ClassificationMethod.RULE_BASED,
        masking_requirement=MaskingStrategy.SYNTHETIC_REPLACEMENT,
        owner="Claims Data Engineering",
        retention=RetentionClassification.STANDARD,
    ),  # low confidence, unconfirmed -> needs_review True
    _entry(
        source_system="postgres_enrollment",
        dataset="plan",
        column="plan_name",
        category=SensitivityCategory.NON_SENSITIVE,
        tier=ClassificationTier.NON_SENSITIVE,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.PASSTHROUGH,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.PERSISTENT_REFERENCE,
    ),
    _entry(
        source_system="postgres_enrollment",
        dataset="provider",
        column="specialty",
        category=SensitivityCategory.SENSITIVE,
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        confidence=1.0,
        method=ClassificationMethod.MANUAL_OVERRIDE,
        masking_requirement=MaskingStrategy.SYNTHETIC_REPLACEMENT,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.STANDARD,
        confirmed_by="data-governance-steward@example.org",
    ),
]


@pytest.fixture
def sample_catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.json"
    payload = [json.loads(entry.model_dump_json()) for entry in SAMPLE_ENTRIES]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
