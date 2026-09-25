"""Tests asserting every required edge-case category is actually present,
even at the `tiny` scale profile, per the Phase 1 promptbook:
"Include edge cases: missing records, nulls, duplicate records, orphan
records, malformed values, late-arriving data, schema drift examples."
"""

from __future__ import annotations

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES


def _generate_tiny():
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    return generator.generate()


def test_missing_records_present() -> None:
    estate = _generate_tiny()
    assert estate.edge_cases.members_with_no_coverage >= 1
    assert estate.edge_cases.claims_with_no_lines >= 1


def test_nulls_present() -> None:
    estate = _generate_tiny()
    assert estate.edge_cases.null_fields_injected >= 1
    assert any(m.date_of_birth is None for m in estate.members)


def test_duplicate_records_present() -> None:
    estate = _generate_tiny()
    assert estate.edge_cases.duplicate_persons_injected >= 1
    assert estate.edge_cases.duplicate_rows_injected >= 1

    # Duplicate persons: two distinct member_ids sharing name + DOB.
    seen: dict[tuple[str, str, str | None], int] = {}
    for m in estate.members:
        key = (m.first_name, m.last_name, m.date_of_birth)
        seen[key] = seen.get(key, 0) + 1
    assert any(count > 1 for count in seen.values())

    # Duplicate rows: the same claim_id appears more than once.
    claim_id_counts: dict[str, int] = {}
    for c in estate.claims:
        claim_id_counts[c.claim_id] = claim_id_counts.get(c.claim_id, 0) + 1
    assert any(count > 1 for count in claim_id_counts.values())


def test_orphan_records_present_across_multiple_categories() -> None:
    estate = _generate_tiny()
    orphans = estate.edge_cases.orphan_records_injected
    assert orphans  # non-empty dict
    assert sum(orphans.values()) >= 5
    # Spot-check a couple of the documented categories exist.
    assert "address" in orphans
    assert "claim.member_id" in orphans
    assert "claim_line.claim_id" in orphans


def test_malformed_values_present() -> None:
    estate = _generate_tiny()
    assert estate.edge_cases.malformed_values_injected >= 1

    negative_claim_amounts = [c for c in estate.claims if (c.paid_amount or 0) < 0]
    malformed_zips = [a for a in estate.addresses if a.zip_code in {"ABCDE", "1234", "00000-XXXX"}]
    assert negative_claim_amounts or malformed_zips


def test_late_arriving_data_present() -> None:
    estate = _generate_tiny()
    assert estate.edge_cases.late_arriving_records_injected >= 1


def test_schema_drift_batches_documented() -> None:
    estate = _generate_tiny()
    assert len(estate.edge_cases.schema_drift_batches) >= 2

    # Both claims-warehouse batches actually exist in the generated data.
    batches = {c.extract_batch_id for c in estate.claims}
    assert "claims-2024Q4" in batches or "claims-2025Q1" in batches

    # Both partner lab feed schema versions actually exist.
    partner_versions = {
        lr.schema_version for lr in estate.lab_results if lr.source == "partner_reference_lab"
    }
    assert "v1" in partner_versions
    assert "v2" in partner_versions
