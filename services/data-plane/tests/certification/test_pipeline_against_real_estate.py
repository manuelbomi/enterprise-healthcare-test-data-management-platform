"""End-to-end tests of `data_plane.certification.pipeline.run_certification_pipeline`
against a real, generated Phase 1 estate -- the actual
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH pipeline,
run for real, not mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from healthcare_tdm_contracts import (
    CertificationStatus,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    MaskingTechnique,
    ScenarioType,
    SubsettingStrategy,
    ClassificationTier,
)

from data_plane.certification.pipeline import run_certification_pipeline
from data_plane.certification.state_machine import InvalidCertificationTransitionError, publish
from data_plane.certification import signing


def test_pipeline_reaches_certified_for_a_healthy_tiny_scale_run(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    result = run_certification_pipeline(
        tmp_path / "run1",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "8"},
        masking_key=masking_key,
        signing_key=signing_key,
    )

    report = result.report
    assert report.status is CertificationStatus.CERTIFIED
    assert report.gates, "certification report must record real gate results"
    assert all(gate.passed for gate in report.gates)
    assert len(report.gates) == 11, "all eleven required certification gates must run"
    assert report.certified_at is not None
    assert report.masking_policy_name and report.masking_policy_version >= 1
    assert report.masking_engine_version == "1.0.0"
    assert report.subset_manifest_id is not None
    assert report.integrity_signature is not None
    assert signing.verify_report_signature(report, signing_key) is True
    assert result.report_path.exists()


def test_pipeline_with_auto_publish_reaches_published(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    result = run_certification_pipeline(
        tmp_path / "run2",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "8"},
        masking_key=masking_key,
        signing_key=signing_key,
        auto_publish=True,
    )
    assert result.report.status is CertificationStatus.PUBLISHED
    assert result.report.published_at is not None


def test_pipeline_with_optional_synthetic_scenarios_still_certifies(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    result = run_certification_pipeline(
        tmp_path / "run3",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "10"},
        masking_key=masking_key,
        signing_key=signing_key,
        synthetic_scenarios=[ScenarioType.HIGH_COST_CLAIMS, ScenarioType.INVALID_CLAIM_REFERENCES],
    )
    report = result.report
    assert report.status is CertificationStatus.CERTIFIED
    assert report.synthetic_generation_manifest_id is not None
    provenance_gate = next(g for g in report.gates if g.gate.value == "provenance")
    assert provenance_gate.passed is True
    assert provenance_gate.metrics["total_final_rows"] == provenance_gate.metrics["total_tagged_rows"]


def test_pipeline_generates_its_own_estate_when_none_given(
    tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    """The INGEST stage itself, run for real (not via the shared
    session-scoped `real_estate` fixture) -- proves the pipeline can
    start from nothing, per the phase's "INGEST" requirement."""

    result = run_certification_pipeline(
        tmp_path / "run4",
        estate_dir=None,
        scale="tiny",
        subset_strategy=SubsettingStrategy.PERCENTAGE,
        subset_parameters={"percentage": "50"},
        masking_key=masking_key,
        signing_key=signing_key,
    )
    assert result.estate_dir.exists()
    assert (result.estate_dir / "manifest.json").exists()
    assert result.report.status is CertificationStatus.CERTIFIED


# ---------------------------------------------------------------------------
# Adversarial: a real end-to-end run that MUST fail certification, and MUST
# NOT be publishable, even when the operator explicitly asks for auto-publish.
# ---------------------------------------------------------------------------


def _broken_policy_leaving_direct_identifiers_unmasked() -> MaskingPolicy:
    return MaskingPolicy(
        name="adversarial-broken-policy",
        version=1,
        rules=[
            MaskingRule(
                tier=ClassificationTier.DIRECT_IDENTIFIER,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="broken-scope",
                technique=MaskingTechnique.PASSTHROUGH,
            ),
            MaskingRule(
                tier=ClassificationTier.QUASI_IDENTIFIER,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="broken-scope",
                technique=MaskingTechnique.PASSTHROUGH,
            ),
            MaskingRule(
                tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="broken-scope",
                technique=MaskingTechnique.PASSTHROUGH,
            ),
            MaskingRule(
                tier=ClassificationTier.NON_SENSITIVE,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="broken-scope",
                technique=MaskingTechnique.PASSTHROUGH,
            ),
        ],
    )


def test_a_real_pipeline_run_with_a_broken_policy_produces_failed_not_certified(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    """The central adversarial demonstration this phase requires: run the
    REAL pipeline end to end against the REAL estate, but with a policy
    that leaves every direct-identifier/quasi-identifier/sensitive-
    clinical column completely unmasked (PASSTHROUGH). Masking itself
    'succeeds' (it runs to completion, produces output files, Phase 3's
    own validation may even pass -- there is no raw-value comparison
    failure because nothing was supposed to look different). The
    certification pipeline must still produce FAILED, not CERTIFIED,
    because the PHI/PII policy coverage gate independently re-derives
    the policy's real behavior rather than trusting that "masking ran."
    """

    broken_policy = _broken_policy_leaving_direct_identifiers_unmasked()

    result = run_certification_pipeline(
        tmp_path / "run-adversarial",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "8"},
        masking_key=masking_key,
        masking_policy=broken_policy,
        signing_key=signing_key,
    )

    report = result.report
    assert report.status is CertificationStatus.FAILED
    coverage_gate = next(g for g in report.gates if g.gate.value == "phi_pii_policy_coverage")
    assert coverage_gate.passed is False
    assert not report.is_publishable


def test_auto_publish_never_publishes_a_failed_pipeline_run(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    """Even with `auto_publish=True`, a real pipeline run that fails
    certification must end in FAILED, never PUBLISHED."""

    broken_policy = _broken_policy_leaving_direct_identifiers_unmasked()

    result = run_certification_pipeline(
        tmp_path / "run-adversarial-autopublish",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "8"},
        masking_key=masking_key,
        masking_policy=broken_policy,
        signing_key=signing_key,
        auto_publish=True,
    )

    assert result.report.status is CertificationStatus.FAILED
    assert result.report.published_at is None


def test_manually_attempting_to_publish_a_failed_pipeline_report_is_rejected(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    """The final bypass attempt: take the real, on-disk FAILED report a
    real pipeline run produced and try to call `publish()` on it
    directly, exactly as a rogue caller bypassing the pipeline's own
    (correct) decision not to auto-publish might try."""

    broken_policy = _broken_policy_leaving_direct_identifiers_unmasked()
    result = run_certification_pipeline(
        tmp_path / "run-adversarial-manual-publish",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "8"},
        masking_key=masking_key,
        masking_policy=broken_policy,
        signing_key=signing_key,
    )
    assert result.report.status is CertificationStatus.FAILED

    with pytest.raises(InvalidCertificationTransitionError):
        publish(result.report, actor="attacker", signing_key=signing_key)


def test_row_count_reconciliation_gate_uses_real_subset_manifest_counts(
    real_estate: Path, tmp_path: Path, masking_key: bytes, signing_key: bytes
) -> None:
    """Confirms gate 6 (row-count reconciliation) really is wired to
    Phase 4's own `SubsetManifest.selected_counts`, not a placeholder --
    every entity present in the real subset manifest must appear in the
    certification report's row-count reconciliation trail."""

    result = run_certification_pipeline(
        tmp_path / "run5",
        estate_dir=real_estate,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "6"},
        masking_key=masking_key,
        signing_key=signing_key,
    )
    report = result.report
    reconciliation_gate = next(g for g in report.gates if g.gate.value == "row_count_reconciliation")
    assert reconciliation_gate.passed is True
    assert set(report.row_count_reconciliation) >= {"member", "claim", "coverage"}
