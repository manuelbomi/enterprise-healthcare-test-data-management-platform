"""Tests for `data_plane.certification.state_machine` -- the enforced
six-state `CertificationStatus` lifecycle.

Several of these are the explicit "attempt to bypass certification"
adversarial tests the phase requires: trying to publish a DRAFT/
PROCESSING/FAILED report, trying to skip straight from DRAFT to
PUBLISHED, trying to un-revoke a report, and so on. Every one of these
must be REJECTED BY CODE, not merely discouraged by convention.
"""

from __future__ import annotations

import pytest
from healthcare_tdm_contracts import CertificationReport, CertificationStatus

from data_plane.certification import signing
from data_plane.certification.state_machine import (
    InvalidCertificationTransitionError,
    publish,
    revoke,
    transition,
)


def _report(status: CertificationStatus) -> CertificationReport:
    return CertificationReport(dataset_name="adversarial-test-dataset", status=status)


# ---------------------------------------------------------------------------
# Legitimate transitions succeed.
# ---------------------------------------------------------------------------


def test_draft_to_processing_succeeds() -> None:
    report = _report(CertificationStatus.DRAFT)
    updated = transition(report, CertificationStatus.PROCESSING, actor="tester")
    assert updated.status is CertificationStatus.PROCESSING
    assert len(updated.status_history) == 1
    assert updated.status_history[0].actor == "tester"


def test_processing_to_certified_succeeds() -> None:
    report = _report(CertificationStatus.PROCESSING)
    updated = transition(report, CertificationStatus.CERTIFIED, actor="tester")
    assert updated.status is CertificationStatus.CERTIFIED


def test_processing_to_failed_succeeds() -> None:
    report = _report(CertificationStatus.PROCESSING)
    updated = transition(report, CertificationStatus.FAILED, actor="tester")
    assert updated.status is CertificationStatus.FAILED


def test_certified_to_published_via_publish_succeeds() -> None:
    report = _report(CertificationStatus.CERTIFIED)
    updated = publish(report, actor="tester")
    assert updated.status is CertificationStatus.PUBLISHED
    assert updated.published_at is not None


def test_certified_to_revoked_succeeds() -> None:
    report = _report(CertificationStatus.CERTIFIED)
    updated = revoke(report, actor="tester", reason="policy defect discovered")
    assert updated.status is CertificationStatus.REVOKED
    assert updated.revoked_reason == "policy defect discovered"
    assert updated.revoked_at is not None


def test_published_to_revoked_succeeds() -> None:
    report = _report(CertificationStatus.PUBLISHED)
    updated = revoke(report, actor="tester", reason="incident response")
    assert updated.status is CertificationStatus.REVOKED


# ---------------------------------------------------------------------------
# Adversarial bypass attempts: every one of these MUST be rejected.
# ---------------------------------------------------------------------------


def test_cannot_publish_a_draft_report() -> None:
    """Attempted bypass: publish a dataset for which certification was
    never even started."""

    report = _report(CertificationStatus.DRAFT)
    with pytest.raises(InvalidCertificationTransitionError):
        publish(report, actor="attacker")


def test_cannot_publish_a_processing_report() -> None:
    """Attempted bypass: publish while gates are still (notionally)
    running."""

    report = _report(CertificationStatus.PROCESSING)
    with pytest.raises(InvalidCertificationTransitionError):
        publish(report, actor="attacker")


def test_cannot_publish_a_failed_report() -> None:
    """Attempted bypass: the phase's own named requirement -- 'A FAILED
    dataset must not be publishable.'"""

    report = _report(CertificationStatus.FAILED)
    with pytest.raises(InvalidCertificationTransitionError):
        publish(report, actor="attacker")


def test_cannot_publish_an_already_published_report_again() -> None:
    report = _report(CertificationStatus.PUBLISHED)
    with pytest.raises(InvalidCertificationTransitionError):
        publish(report, actor="attacker")


def test_cannot_publish_a_revoked_report() -> None:
    """Attempted bypass: re-publish a dataset whose certification was
    revoked -- REVOKED is terminal."""

    report = _report(CertificationStatus.REVOKED)
    with pytest.raises(InvalidCertificationTransitionError):
        publish(report, actor="attacker")


def test_cannot_skip_directly_from_draft_to_published_via_raw_transition() -> None:
    """Attempted bypass: call the lower-level `transition()` directly to
    skip CERTIFIED entirely, in case a caller thinks `publish()`'s extra
    checks are the only guard. The transition table itself must also
    reject this."""

    report = _report(CertificationStatus.DRAFT)
    with pytest.raises(InvalidCertificationTransitionError):
        transition(report, CertificationStatus.PUBLISHED, actor="attacker")


def test_cannot_skip_directly_from_processing_to_published() -> None:
    report = _report(CertificationStatus.PROCESSING)
    with pytest.raises(InvalidCertificationTransitionError):
        transition(report, CertificationStatus.PUBLISHED, actor="attacker")


def test_cannot_transition_a_failed_report_anywhere() -> None:
    """FAILED is terminal: not to CERTIFIED, not back to PROCESSING, not
    to PUBLISHED. A failed run must be re-run as a brand new report."""

    report = _report(CertificationStatus.FAILED)
    for target in (
        CertificationStatus.CERTIFIED,
        CertificationStatus.PROCESSING,
        CertificationStatus.PUBLISHED,
        CertificationStatus.DRAFT,
    ):
        with pytest.raises(InvalidCertificationTransitionError):
            transition(report, target, actor="attacker")


def test_cannot_transition_a_revoked_report_anywhere() -> None:
    report = _report(CertificationStatus.REVOKED)
    for target in CertificationStatus:
        if target is CertificationStatus.REVOKED:
            continue
        with pytest.raises(InvalidCertificationTransitionError):
            transition(report, target, actor="attacker")


def test_cannot_revoke_a_draft_report() -> None:
    """Only CERTIFIED or PUBLISHED datasets have a certification worth
    revoking."""

    report = _report(CertificationStatus.DRAFT)
    with pytest.raises(InvalidCertificationTransitionError):
        revoke(report, actor="attacker", reason="trying to revoke a draft")


def test_cannot_revoke_without_a_reason() -> None:
    report = _report(CertificationStatus.CERTIFIED)
    with pytest.raises(ValueError):
        revoke(report, actor="attacker", reason="   ")


def test_cannot_move_backwards_from_certified_to_processing() -> None:
    report = _report(CertificationStatus.CERTIFIED)
    with pytest.raises(InvalidCertificationTransitionError):
        transition(report, CertificationStatus.PROCESSING, actor="attacker")


# ---------------------------------------------------------------------------
# Signature-aware transitions: a tampered report must not be transitioned.
# ---------------------------------------------------------------------------


def test_transition_rejects_a_tampered_signed_report_with_forged_status(signing_key: bytes) -> None:
    """A report DRAFTed/FAILED, then hand-edited to claim CERTIFIED status
    without ever going through `report.certify()`, must be rejected --
    even though the forged status alone would otherwise satisfy
    `publish()`'s eager status check."""

    report = _report(CertificationStatus.FAILED)
    signed = signing.sign_report(report, signing_key)
    forged = signed.model_copy(update={"status": CertificationStatus.CERTIFIED})

    with pytest.raises(signing.TamperedCertificationReportError):
        publish(forged, actor="attacker", signing_key=signing_key)


def test_transition_rejects_a_tampered_signed_report_with_other_field_changed(signing_key: bytes) -> None:
    """Even when the forged report's `status` is legitimately CERTIFIED,
    tampering with any other signed field (here: silently upgrading the
    recorded masking policy version, as if to hide that an older,
    less-protective policy was actually used) must still be caught."""

    report = _report(CertificationStatus.CERTIFIED)
    signed = signing.sign_report(report, signing_key)
    tampered = signed.model_copy(update={"masking_policy_version": 999})

    with pytest.raises(signing.TamperedCertificationReportError):
        publish(tampered, actor="attacker", signing_key=signing_key)


def test_publish_then_revoke_round_trip_preserves_valid_signature(signing_key: bytes) -> None:
    report = _report(CertificationStatus.CERTIFIED)
    signed = signing.sign_report(report, signing_key)

    published = publish(signed, actor="tester", signing_key=signing_key)
    assert signing.verify_report_signature(published, signing_key) is True

    revoked = revoke(published, actor="tester", reason="incident", signing_key=signing_key)
    assert signing.verify_report_signature(revoked, signing_key) is True
    assert revoked.status is CertificationStatus.REVOKED
