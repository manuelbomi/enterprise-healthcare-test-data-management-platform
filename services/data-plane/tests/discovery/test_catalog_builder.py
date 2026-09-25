"""Tests for `catalog_builder`: masking-requirement/owner/retention
attachment, and the JSON artifact round trip.
"""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import MaskingStrategy, RetentionClassification

from data_plane.discovery.catalog_builder import build_catalog, load_catalog, write_catalog
from data_plane.discovery.engine import ClassificationEngine, ColumnToClassify


def _engine() -> ClassificationEngine:
    return ClassificationEngine(overrides={})


def test_direct_identifier_gets_tokenization_and_extended_retention() -> None:
    entries = build_catalog(
        [ColumnToClassify("postgres_enrollment", "member", "Member", "ssn")], _engine()
    )
    (entry,) = entries
    assert entry.masking_requirement == MaskingStrategy.DETERMINISTIC_TOKENIZATION
    assert entry.retention_classification == RetentionClassification.EXTENDED
    assert entry.owner == "Enrollment Data Engineering"
    assert entry.dataset == "member"
    assert entry.column == "ssn"
    assert entry.source == "postgres_enrollment"


def test_non_sensitive_gets_passthrough_and_ephemeral_retention() -> None:
    entries = build_catalog(
        [ColumnToClassify("postgres_enrollment", "coverage", "Coverage", "coverage_status")], _engine()
    )
    (entry,) = entries
    assert entry.masking_requirement == MaskingStrategy.PASSTHROUGH
    assert entry.retention_classification == RetentionClassification.EPHEMERAL


def test_reference_dataset_always_persistent_regardless_of_category() -> None:
    # Plan.plan_name is non_sensitive by category, but "plan" is a
    # reference/code-vocabulary dataset, so retention is
    # PERSISTENT_REFERENCE, not EPHEMERAL.
    entries = build_catalog(
        [ColumnToClassify("postgres_enrollment", "plan", "Plan", "plan_name")], _engine()
    )
    (entry,) = entries
    assert entry.retention_classification == RetentionClassification.PERSISTENT_REFERENCE


def test_unassigned_owner_for_unknown_source_system() -> None:
    entries = build_catalog(
        [ColumnToClassify("some_new_system", "widgets", None, "widget_id")], _engine()
    )
    (entry,) = entries
    assert entry.owner == "Unassigned"


def test_write_and_load_catalog_round_trips(tmp_path: Path) -> None:
    entries = build_catalog(
        [
            ColumnToClassify("postgres_enrollment", "member", "Member", "ssn"),
            ColumnToClassify("postgres_enrollment", "member", "Member", "is_active"),
        ],
        _engine(),
    )
    out_path = tmp_path / "catalog.json"
    write_catalog(entries, out_path)
    assert out_path.exists()

    loaded = load_catalog(out_path)
    assert len(loaded) == 2
    assert {e.column for e in loaded} == {"ssn", "is_active"}
    assert loaded == entries
