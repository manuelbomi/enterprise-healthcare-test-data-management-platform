"""Tests for `data_plane.certification.gates` -- the VALIDATE-stage
certification gates.

Several of these are the explicit "inject a known problem and confirm the
gate catches it" adversarial tests the phase requires: an unmasked PHI
column (policy coverage gap), a real referential-integrity engine bug,
row-count loss between SUBSET and the final output, and so on.
"""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import (
    CatalogEntry,
    ClassificationTier,
    ColumnClassification,
    IntegrityStatus,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    MaskingTechnique,
    RetentionClassification,
    SubsetManifest,
    SubsetSelectionCriteria,
    SubsettingStrategy,
    SyntheticGenerationManifest,
)

from data_plane.certification import gates
from data_plane.masking.policy import DEFAULT_POLICY
from data_plane.masking.validation import ValidationReport as MaskingValidationReport
from data_plane.subsetting.estate_io import RawEstate
from data_plane.subsetting.validation import SubsetValidationReport


def _catalog_entry(
    *,
    column: str = "ssn",
    dataset: str = "member",
    source_system: str = "postgres_enrollment",
    tier: ClassificationTier = ClassificationTier.DIRECT_IDENTIFIER,
) -> CatalogEntry:
    classification = ColumnClassification(
        source_system=source_system,
        dataset=dataset,
        column=column,
        tier=tier,
        confidence=1.0,
        detector="test",
    )
    return CatalogEntry(
        classification=classification,
        masking_requirement=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
        owner="Test Owner",
        retention_classification=RetentionClassification.STANDARD,
    )


def _broken_policy_leaving_direct_identifiers_unmasked() -> MaskingPolicy:
    """A deliberately misconfigured policy: every DIRECT_IDENTIFIER
    column resolves to PASSTHROUGH (i.e. left completely unmasked) --
    simulating exactly the "unmasked PHI column" adversarial scenario
    the phase's promptbook calls out."""

    return MaskingPolicy(
        name="broken-test-policy",
        version=1,
        rules=[
            MaskingRule(
                tier=ClassificationTier.DIRECT_IDENTIFIER,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="broken-scope",
                technique=MaskingTechnique.PASSTHROUGH,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# GATE: PHI/PII policy coverage
# ---------------------------------------------------------------------------


def test_phi_pii_policy_coverage_passes_under_the_real_default_policy() -> None:
    entries = [
        _catalog_entry(column="ssn", tier=ClassificationTier.DIRECT_IDENTIFIER),
        _catalog_entry(column="member_id", tier=ClassificationTier.DIRECT_IDENTIFIER),
        _catalog_entry(column="date_of_birth", tier=ClassificationTier.QUASI_IDENTIFIER),
        _catalog_entry(column="status_code", tier=ClassificationTier.NON_SENSITIVE),
    ]
    result = gates.check_phi_pii_policy_coverage(entries, DEFAULT_POLICY)
    assert result.passed is True


def test_phi_pii_policy_coverage_gate_fails_when_a_sensitive_column_resolves_to_passthrough() -> None:
    """Adversarial test: inject an unmasked PHI/direct-identifier column
    by using a deliberately broken policy, and confirm the gate catches
    it rather than certifying it."""

    entries = [_catalog_entry(column="ssn", tier=ClassificationTier.DIRECT_IDENTIFIER)]
    broken_policy = _broken_policy_leaving_direct_identifiers_unmasked()

    result = gates.check_phi_pii_policy_coverage(entries, broken_policy)

    assert result.passed is False
    assert "ssn" in result.detail


def test_phi_pii_policy_coverage_ignores_non_sensitive_columns() -> None:
    entries = [_catalog_entry(column="status_code", tier=ClassificationTier.NON_SENSITIVE)]
    broken_policy = _broken_policy_leaving_direct_identifiers_unmasked()
    result = gates.check_phi_pii_policy_coverage(entries, broken_policy)
    assert result.passed is True  # nothing sensitive to check


# ---------------------------------------------------------------------------
# GATE: masking completion
# ---------------------------------------------------------------------------


def test_masking_completion_passes_when_validation_passed_and_work_was_done() -> None:
    validation = MaskingValidationReport(checks_run=["a", "b"], passed=True, failures=[])
    result = gates.check_masking_completion(validation, rows_processed=100, files_written=5)
    assert result.passed is True


def test_masking_completion_fails_when_masking_validation_failed() -> None:
    validation = MaskingValidationReport(checks_run=["a"], passed=False, failures=["a: broke"])
    result = gates.check_masking_completion(validation, rows_processed=100, files_written=5)
    assert result.passed is False


def test_masking_completion_fails_when_zero_rows_were_processed() -> None:
    """A vacuously-passing masking validation (nothing to check) must not
    be certified as 'masking completion' -- masking must have actually
    done something."""

    validation = MaskingValidationReport(checks_run=[], passed=True, failures=[])
    result = gates.check_masking_completion(validation, rows_processed=0, files_written=0)
    assert result.passed is False


# ---------------------------------------------------------------------------
# GATE: referential integrity
# ---------------------------------------------------------------------------


def test_referential_integrity_passes_on_a_clean_subset() -> None:
    validation = SubsetValidationReport(status=IntegrityStatus.PASSED)
    result = gates.check_referential_integrity(validation)
    assert result.passed is True


def test_referential_integrity_accepts_known_orphans_by_default() -> None:
    validation = SubsetValidationReport(
        status=IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS,
        known_orphan_counts={"claim.provider_id": 1},
    )
    result = gates.check_referential_integrity(validation, strict=False)
    assert result.passed is True


def test_referential_integrity_rejects_known_orphans_in_strict_mode() -> None:
    validation = SubsetValidationReport(
        status=IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS,
        known_orphan_counts={"claim.provider_id": 1},
    )
    result = gates.check_referential_integrity(validation, strict=True)
    assert result.passed is False


def test_referential_integrity_gate_fails_on_a_real_engine_bug() -> None:
    """Adversarial test: inject a known referential-integrity problem
    (an `engine_bug`-classified dangling reference -- Phase 4's own
    vocabulary for 'this is a real defect, never expected') and confirm
    the gate fails, regardless of `strict`."""

    validation = SubsetValidationReport(
        status=IntegrityStatus.FAILED,
        engine_bug_counts={"claim_line.diagnosis_code": 3},
    )
    result = gates.check_referential_integrity(validation, strict=False)
    assert result.passed is False
    assert "engine" in result.detail.lower() or "dangling" in result.detail.lower()


# ---------------------------------------------------------------------------
# GATE: orphan detection
# ---------------------------------------------------------------------------


def _subset_manifest(**overrides: object) -> SubsetManifest:
    defaults: dict[str, object] = dict(
        scale_profile="tiny",
        selection=SubsetSelectionCriteria(strategy=SubsettingStrategy.FIXED_POPULATION),
        source_counts={"member": 100},
        selected_counts={"member": 10},
        integrity_status=IntegrityStatus.PASSED,
    )
    defaults.update(overrides)
    return SubsetManifest(**defaults)


def test_orphan_detection_report_only_by_default() -> None:
    manifest = _subset_manifest(known_orphan_counts={"claim.provider_id": 5})
    result = gates.check_orphan_detection(manifest)
    assert result.passed is True  # no threshold configured


def test_orphan_detection_fails_when_over_threshold() -> None:
    manifest = _subset_manifest(known_orphan_counts={"claim.provider_id": 5})
    result = gates.check_orphan_detection(manifest, max_allowed_orphans=2)
    assert result.passed is False


def test_orphan_detection_passes_when_within_threshold() -> None:
    manifest = _subset_manifest(known_orphan_counts={"claim.provider_id": 2})
    result = gates.check_orphan_detection(manifest, max_allowed_orphans=5)
    assert result.passed is True


# ---------------------------------------------------------------------------
# GATE: row-count reconciliation
# ---------------------------------------------------------------------------


def test_row_count_reconciliation_passes_when_counts_match() -> None:
    manifest = _subset_manifest(selected_counts={"member": 10, "claim": 20})
    result = gates.check_row_count_reconciliation(manifest, {"member": 10, "claim": 20})
    assert result.passed is True


def test_row_count_reconciliation_passes_when_synthetic_augmentation_adds_rows() -> None:
    manifest = _subset_manifest(selected_counts={"member": 10, "claim": 20})
    result = gates.check_row_count_reconciliation(manifest, {"member": 12, "claim": 25})
    assert result.passed is True


def test_row_count_reconciliation_fails_on_data_loss() -> None:
    """Adversarial test: simulate a masking/write-back bug that silently
    dropped rows between SUBSET and the final output."""

    manifest = _subset_manifest(selected_counts={"member": 10, "claim": 20})
    result = gates.check_row_count_reconciliation(manifest, {"member": 10, "claim": 15})
    assert result.passed is False
    assert "claim" in result.detail


# ---------------------------------------------------------------------------
# GATE: schema validation
# ---------------------------------------------------------------------------


def test_schema_validation_passes_on_a_consistent_estate() -> None:
    estate = RawEstate(member=[{"member_id": "SYN-MBR-000001", "first_name": "A"}])
    result = gates.check_schema_validation(estate, {"member": 1})
    assert result.passed is True


def test_schema_validation_fails_on_row_count_mismatch() -> None:
    estate = RawEstate(member=[{"member_id": "SYN-MBR-000001"}])
    result = gates.check_schema_validation(estate, {"member": 2})
    assert result.passed is False


def test_schema_validation_fails_on_heterogeneous_rows_within_one_physical_table() -> None:
    """Adversarial test: two rows of the SAME logical entity, from the
    SAME physical table, with different key sets -- the exact shape of
    bug `problems_phase_05.md`'s risk log documents for the PBM CSV
    writer. Must be caught."""

    estate = RawEstate(
        member=[
            {"member_id": "SYN-MBR-000001", "first_name": "A"},
            {"member_id": "SYN-MBR-000002", "first_name": "B", "extra_column": "unexpected"},
        ]
    )
    result = gates.check_schema_validation(estate, {"member": 2})
    assert result.passed is False
    assert "member" in result.detail


def test_schema_validation_tolerates_intentional_schema_drift_across_claim_batches() -> None:
    """Claim's two Parquet batches legitimately have different columns
    (Phase 1's documented schema drift) -- this must NOT be flagged."""

    from data_plane.subsetting.estate_io import ParquetDataset

    estate = RawEstate(
        claim=ParquetDataset(
            batches={
                "claims-2024Q4": [{"claim_id": "SYN-CLM-000001", "paid_amount": "10.00"}],
                "claims-2025Q1": [
                    {"claim_id": "SYN-CLM-000002", "amount_paid": "20.00", "adjustment_reason_code": "X"}
                ],
            }
        )
    )
    result = gates.check_schema_validation(estate, {"claim": 2})
    assert result.passed is True


# ---------------------------------------------------------------------------
# GATE: data quality thresholds
# ---------------------------------------------------------------------------


def test_data_quality_thresholds_passes_with_a_healthy_dataset() -> None:
    result = gates.check_data_quality_thresholds({"member": 10, "claim": 20})
    assert result.passed is True


def test_data_quality_thresholds_fails_on_an_empty_dataset() -> None:
    result = gates.check_data_quality_thresholds({"member": 0, "claim": 0})
    assert result.passed is False


# ---------------------------------------------------------------------------
# GATE: provenance
# ---------------------------------------------------------------------------


def test_provenance_passes_trivially_with_no_synthetic_stage() -> None:
    result = gates.check_provenance({"member": 10}, None)
    assert result.passed is True


def test_provenance_passes_when_rollup_accounts_for_every_row() -> None:
    manifest = SyntheticGenerationManifest(
        mode="augment",
        seed=1,
        provenance_row_counts={"masked_production_like": 8, "synthetic": 2},
    )
    result = gates.check_provenance({"member": 10}, manifest)
    assert result.passed is True


def test_provenance_gate_fails_when_rollup_does_not_account_for_every_row() -> None:
    """Adversarial test: a synthetic manifest whose own provenance rollup
    undercounts the final estate -- i.e. some rows were written without a
    provenance tag."""

    manifest = SyntheticGenerationManifest(
        mode="augment",
        seed=1,
        provenance_row_counts={"masked_production_like": 5},
    )
    result = gates.check_provenance({"member": 10}, manifest)
    assert result.passed is False


# ---------------------------------------------------------------------------
# GATE: manifest generation
# ---------------------------------------------------------------------------


def test_manifest_generation_passes_when_all_files_exist(tmp_path: Path) -> None:
    subset_manifest = tmp_path / "subset_manifest.json"
    masking_summary = tmp_path / "masking_run_summary.json"
    subset_manifest.write_text("{}")
    masking_summary.write_text("{}")
    result = gates.check_manifest_generation(subset_manifest, masking_summary, None)
    assert result.passed is True


def test_manifest_generation_fails_when_a_required_file_is_missing(tmp_path: Path) -> None:
    subset_manifest = tmp_path / "subset_manifest.json"
    masking_summary = tmp_path / "masking_run_summary.json"
    subset_manifest.write_text("{}")
    # masking_summary deliberately not written.
    result = gates.check_manifest_generation(subset_manifest, masking_summary, None)
    assert result.passed is False


def test_manifest_generation_requires_synthetic_manifest_when_path_given(tmp_path: Path) -> None:
    subset_manifest = tmp_path / "subset_manifest.json"
    masking_summary = tmp_path / "masking_run_summary.json"
    synthetic_manifest = tmp_path / "synthetic_generation_manifest.json"
    subset_manifest.write_text("{}")
    masking_summary.write_text("{}")
    result = gates.check_manifest_generation(subset_manifest, masking_summary, synthetic_manifest)
    assert result.passed is False


# ---------------------------------------------------------------------------
# GATE: policy version / masking version recorded
# ---------------------------------------------------------------------------


def test_policy_version_recorded_passes_for_the_real_default_policy() -> None:
    result = gates.check_policy_version_recorded(DEFAULT_POLICY)
    assert result.passed is True


def test_masking_version_recorded_fails_when_blank() -> None:
    result = gates.check_masking_version_recorded("")
    assert result.passed is False


def test_masking_version_recorded_passes_when_present() -> None:
    result = gates.check_masking_version_recorded("1.0.0")
    assert result.passed is True
