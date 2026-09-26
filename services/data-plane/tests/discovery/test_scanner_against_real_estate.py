"""Integration test: generate a real 'tiny' Phase 1 estate on disk (same
generator/writer path `reference_data`'s own tests use) and scan it with
`scanner.scan_estate`, verifying the scanner finds real columns across
all five source systems -- including the schema-drift columns that only
exist because a real file was written, not because a schema said they
should ('amount_paid', 'adjustment_reason_code', partner v1's abbreviated
field names). This is the test operational note #5 in the Phase 2 task
refers to: discovery actually run against the real Phase 1 estate.
"""

from __future__ import annotations

import pytest

from data_plane.discovery.catalog_builder import build_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES


@pytest.fixture(scope="module")
def scanned_columns(tmp_path_factory: pytest.TempPathFactory):
    output_root = tmp_path_factory.mktemp("discovery-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return scan_estate(output_root)


def _find(columns, source_system: str, dataset: str, column: str):
    return next(
        (
            c
            for c in columns
            if c.source_system == source_system and c.dataset == dataset and c.column == column
        ),
        None,
    )


def test_scan_covers_all_five_source_systems(scanned_columns) -> None:
    systems = {c.source_system for c in scanned_columns}
    assert systems == {
        "postgres_enrollment",
        "object_storage_claims_parquet",
        "s3_clinical_data_lake",
        "adls_pbm_extract",
        "partner_lab_feed",
    }


def test_scan_finds_all_fourteen_datasets(scanned_columns) -> None:
    datasets_by_system: dict[str, set[str]] = {}
    for c in scanned_columns:
        datasets_by_system.setdefault(c.source_system, set()).add(c.dataset)

    assert datasets_by_system["postgres_enrollment"] == {
        "member",
        "member_demographics",
        "address",
        "plan",
        "coverage",
        "provider",
    }
    assert datasets_by_system["object_storage_claims_parquet"] == {
        "claim",
        "claim_line",
        "diagnosis",
        "procedure",
    }
    assert datasets_by_system["s3_clinical_data_lake"] == {"encounter", "lab_result"}
    assert datasets_by_system["adls_pbm_extract"] == {"prescription", "pharmacy"}
    assert datasets_by_system["partner_lab_feed"] == {"lab_result"}


def test_scan_finds_real_schema_drift_columns_not_in_domain_model(scanned_columns) -> None:
    # These columns exist ONLY because the writer actually renamed/added
    # them on disk (writers/parquet_writer.py) -- a schema-only classifier
    # (keyed on reference_data/domain.py's Pydantic fields) would never
    # see them.
    assert _find(scanned_columns, "object_storage_claims_parquet", "claim", "amount_paid")
    assert _find(scanned_columns, "object_storage_claims_parquet", "claim", "adjustment_reason_code")
    # Legacy batch's original name should ALSO still be present (both
    # schema-drifted batches are unioned into one dataset -- see
    # scanner.py's docstring and docs/problems/problems_phase_02.md P2-3).
    assert _find(scanned_columns, "object_storage_claims_parquet", "claim", "paid_amount")


def test_scan_finds_partner_v1_abbreviated_columns(scanned_columns) -> None:
    for column in ("pat_id", "test_cd", "test_nm", "result", "collected_dt", "delivered_dt"):
        assert _find(scanned_columns, "partner_lab_feed", "lab_result", column), column
    # v2's fuller field names should also be present (unioned).
    assert _find(scanned_columns, "partner_lab_feed", "lab_result", "member_id")
    assert _find(scanned_columns, "partner_lab_feed", "lab_result", "test_code")


def test_full_discovery_pipeline_classifies_every_scanned_column(scanned_columns) -> None:
    entries = build_catalog(scanned_columns, ClassificationEngine())
    assert len(entries) == len(scanned_columns)
    # Every entry must have a usable classification -- no column is left
    # completely unclassified.
    for entry in entries:
        assert entry.classification.category is not None
        assert 0.0 <= entry.classification.confidence <= 1.0

    # Spot-check: the real schema-drift columns end up correctly
    # classified end to end (schema layer for the legacy name, rule-based
    # layer for the renamed/new columns).
    by_key = {
        (e.classification.source_system, e.classification.dataset, e.classification.column): e
        for e in entries
    }
    assert by_key[("object_storage_claims_parquet", "claim", "paid_amount")].classification.method.value == "schema_based"
    assert by_key[("object_storage_claims_parquet", "claim", "amount_paid")].classification.method.value == "rule_based"
    assert by_key[("object_storage_claims_parquet", "claim", "adjustment_reason_code")].classification.method.value == "manual_override"
    assert by_key[("postgres_enrollment", "provider", "specialty")].classification.method.value == "manual_override"
