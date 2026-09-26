"""Smoke tests for the Phase 6 certification contracts
(`healthcare_tdm_contracts.certification`).

Consistent with `test_contracts_smoke.py`'s Phase 0 scope note: these
contracts have no behavior beyond validation and the documented
transition-table data. The actual enforcement (state machine, signing)
lives in `data_plane.certification` and is tested there against real
pipeline runs.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from healthcare_tdm_contracts import (
    CERTIFICATION_STATUS_TRANSITIONS,
    CertificationGateResult,
    CertificationGateType,
    CertificationReport,
    CertificationStatus,
    CertificationStatusEvent,
)


def test_certification_status_has_all_six_required_states() -> None:
    assert {s.value for s in CertificationStatus} == {
        "draft",
        "processing",
        "failed",
        "certified",
        "published",
        "revoked",
    }


def test_certification_gate_type_has_all_eleven_required_gates_plus_the_phase18a_addition() -> None:
    assert {g.value for g in CertificationGateType} == {
        "phi_pii_policy_coverage",
        "masking_completion",
        "referential_integrity",
        "schema_validation",
        "data_quality_thresholds",
        "row_count_reconciliation",
        "orphan_detection",
        "provenance",
        "manifest_generation",
        "policy_version_recorded",
        "masking_version_recorded",
        # Phase 18A (problems_final_review.md P1-9): a twelfth gate,
        # added after the original eleven Phase 6 gates above.
        "distribution_shape",
    }


def test_transition_table_covers_every_status() -> None:
    assert set(CERTIFICATION_STATUS_TRANSITIONS) == set(CertificationStatus)


def test_failed_and_revoked_are_terminal_in_the_transition_table() -> None:
    assert CERTIFICATION_STATUS_TRANSITIONS[CertificationStatus.FAILED] == frozenset()
    assert CERTIFICATION_STATUS_TRANSITIONS[CertificationStatus.REVOKED] == frozenset()


def test_transition_table_never_allows_skipping_certified_to_reach_published() -> None:
    # DRAFT and PROCESSING must never be able to reach PUBLISHED directly.
    assert CertificationStatus.PUBLISHED not in CERTIFICATION_STATUS_TRANSITIONS[CertificationStatus.DRAFT]
    assert CertificationStatus.PUBLISHED not in CERTIFICATION_STATUS_TRANSITIONS[CertificationStatus.PROCESSING]


def test_certification_report_defaults_to_draft_and_not_publishable() -> None:
    report = CertificationReport(dataset_name="test-dataset")
    assert report.status is CertificationStatus.DRAFT
    assert report.is_publishable is False
    assert report.all_gates_passed is False  # no gates recorded yet


def test_certification_report_all_gates_passed_requires_at_least_one_gate() -> None:
    report = CertificationReport(dataset_name="test-dataset", gates=[])
    assert report.all_gates_passed is False


def test_certification_report_all_gates_passed_is_false_if_any_gate_failed() -> None:
    report = CertificationReport(
        dataset_name="test-dataset",
        gates=[
            CertificationGateResult(gate=CertificationGateType.MASKING_COMPLETION, passed=True),
            CertificationGateResult(gate=CertificationGateType.SCHEMA_VALIDATION, passed=False),
        ],
    )
    assert report.all_gates_passed is False


def test_certification_report_is_publishable_only_when_certified() -> None:
    for status in CertificationStatus:
        report = CertificationReport(dataset_name="test-dataset", status=status)
        assert report.is_publishable == (status is CertificationStatus.CERTIFIED)


def test_certification_report_round_trips_through_json() -> None:
    report = CertificationReport(
        dataset_name="tiny-fixed_population",
        status=CertificationStatus.CERTIFIED,
        masking_policy_name="phase3-default",
        masking_policy_version=1,
        masking_engine_version="1.0.0",
        gates=[
            CertificationGateResult(
                gate=CertificationGateType.ROW_COUNT_RECONCILIATION,
                passed=True,
                detail="14 entities reconciled",
                metrics={"member": "selected=10 final=10"},
            ),
        ],
        status_history=[
            CertificationStatusEvent(status=CertificationStatus.PROCESSING, actor="pipeline"),
            CertificationStatusEvent(status=CertificationStatus.CERTIFIED, actor="pipeline"),
        ],
        row_count_reconciliation={"member": "source=26 selected=10 final=10"},
        integrity_signature="deadbeef",
    )
    assert CertificationReport.model_validate_json(report.model_dump_json()) == report


def test_certification_gate_result_requires_gate_and_passed() -> None:
    with pytest.raises(ValidationError):
        CertificationGateResult()  # type: ignore[call-arg]
