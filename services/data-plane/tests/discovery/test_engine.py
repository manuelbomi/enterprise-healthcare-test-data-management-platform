"""Tests for `ClassificationEngine`'s precedence: manual override >
schema-based > rule-based > conservative default.
"""

from __future__ import annotations

from healthcare_tdm_contracts import ClassificationMethod, ClassificationTier, SensitivityCategory

from data_plane.discovery.engine import (
    NO_MATCH_CONFIDENCE,
    ClassificationEngine,
    ColumnToClassify,
)
from data_plane.discovery.overrides import ManualOverride


def test_schema_based_classification_used_when_entity_and_column_known() -> None:
    engine = ClassificationEngine(overrides={})
    result = engine.classify_column(
        ColumnToClassify(
            source_system="postgres_enrollment", dataset="member", entity="Member", column="ssn"
        )
    )
    assert result.method == ClassificationMethod.SCHEMA_BASED
    assert result.category == SensitivityCategory.DIRECT_IDENTIFIER
    assert result.tier == ClassificationTier.DIRECT_IDENTIFIER
    assert result.confidence == 1.0
    assert result.confirmed_by is None


def test_rule_based_fallback_used_when_column_not_in_schema() -> None:
    engine = ClassificationEngine(overrides={})
    result = engine.classify_column(
        ColumnToClassify(
            source_system="object_storage_claims_parquet",
            dataset="claim",
            entity="Claim",
            column="amount_paid",  # schema-drifted rename; not a literal Claim field
        )
    )
    assert result.method == ClassificationMethod.RULE_BASED
    assert result.category == SensitivityCategory.SENSITIVE
    assert result.detector == "pattern:financial_amount"


def test_rule_based_fallback_uses_entity_context_for_a_drifted_npi_column() -> None:
    """Phase 18B (`docs/problems/problems_final_review.md` P3-10, narrowed): a column
    that is not a literal `Provider` schema field (so schema-based
    classification does not fire) but whose owning entity is still the
    recognized `Provider` business entity gets the confidence-boosted,
    entity-context-aware `pattern:npi+entity_context` hit, not the
    generic name-only guess -- proven end-to-end through
    `ClassificationEngine`, not just `pattern_rules.match_all` directly."""

    engine = ClassificationEngine(overrides={})
    result = engine.classify_column(
        ColumnToClassify(
            source_system="postgres_enrollment",
            dataset="provider",
            entity="Provider",
            column="referring-npi",  # schema-drifted variant; not a literal Provider field
        )
    )
    assert result.method == ClassificationMethod.RULE_BASED
    assert result.detector == "pattern:npi+entity_context"
    assert result.category == SensitivityCategory.PII
    assert result.confidence == 0.95


def test_conservative_default_when_nothing_matches() -> None:
    engine = ClassificationEngine(overrides={})
    result = engine.classify_column(
        ColumnToClassify(
            source_system="unknown_system",
            dataset="unknown_dataset",
            entity=None,
            column="totally_unrecognizable_xyz123",
        )
    )
    assert result.method == ClassificationMethod.RULE_BASED
    assert result.detector == "fallback:no_match"
    assert result.category == SensitivityCategory.SENSITIVE
    assert result.confidence == NO_MATCH_CONFIDENCE
    assert result.needs_review is True


def test_manual_override_beats_schema_based() -> None:
    override = ManualOverride(
        source_system="postgres_enrollment",
        dataset="member",
        column="ssn",
        category=SensitivityCategory.NON_SENSITIVE,
        reason="Test: pretend this column is actually harmless.",
        confirmed_by="test.steward",
    )
    engine = ClassificationEngine(overrides={("postgres_enrollment", "member", "ssn"): override})
    result = engine.classify_column(
        ColumnToClassify(
            source_system="postgres_enrollment", dataset="member", entity="Member", column="ssn"
        )
    )
    assert result.method == ClassificationMethod.MANUAL_OVERRIDE
    assert result.category == SensitivityCategory.NON_SENSITIVE
    assert result.confidence == 1.0
    assert result.confirmed_by == "test.steward"
    assert result.needs_review is False


def test_manual_override_beats_rule_based_and_no_match_fallback() -> None:
    override = ManualOverride(
        source_system="object_storage_claims_parquet",
        dataset="claim",
        column="adjustment_reason_code",
        category=SensitivityCategory.NON_SENSITIVE,
        reason="Confirmed harmless internal code.",
        confirmed_by="test.steward",
    )
    engine = ClassificationEngine(
        overrides={("object_storage_claims_parquet", "claim", "adjustment_reason_code"): override}
    )
    result = engine.classify_column(
        ColumnToClassify(
            source_system="object_storage_claims_parquet",
            dataset="claim",
            entity="Claim",
            column="adjustment_reason_code",
        )
    )
    assert result.method == ClassificationMethod.MANUAL_OVERRIDE
    assert result.category == SensitivityCategory.NON_SENSITIVE


def test_classify_columns_preserves_order() -> None:
    engine = ClassificationEngine(overrides={})
    items = [
        ColumnToClassify("postgres_enrollment", "member", "Member", "ssn"),
        ColumnToClassify("postgres_enrollment", "member", "Member", "is_active"),
    ]
    results = engine.classify_columns(items)
    assert [r.column for r in results] == ["ssn", "is_active"]


def test_default_overrides_loaded_when_none_passed() -> None:
    engine = ClassificationEngine()
    assert ("postgres_enrollment", "provider", "specialty") in engine.overrides
