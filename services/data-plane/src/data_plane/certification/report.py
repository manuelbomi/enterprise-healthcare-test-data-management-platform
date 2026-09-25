"""Build and CERTIFY a `CertificationReport`.

`certify()` is the single place in this whole package that decides
whether a run becomes `CERTIFIED` or `FAILED` -- the concrete answer to
this phase's core requirement, "a dataset must not be publishable simply
because masking ran." Every prior phase's own report/manifest
(`MaskingRunReport.warnings`, `SubsetManifest.integrity_status`, ...) can
claim success and this function can still produce `FAILED`, because it
does not trust those claims directly -- it trusts only the
`CertificationGateResult`s `gates.run_all_gates` independently computed
from them (see `docs/CERTIFICATION_VS_MASKING.md`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from healthcare_tdm_contracts import (
    CertificationGateResult,
    CertificationReport,
    CertificationStatus,
)

from data_plane.certification.state_machine import InvalidCertificationTransitionError, transition


def build_draft_report(
    *,
    dataset_name: str,
    scale_profile: str = "unknown",
    subset_manifest_id: UUID | None = None,
    synthetic_generation_manifest_id: UUID | None = None,
    masking_policy_name: str = "",
    masking_policy_version: int = 0,
    masking_engine_version: str = "",
    notes: str = "",
) -> CertificationReport:
    """A fresh, `DRAFT`-status report -- the starting point of one
    certification run. Nothing has been validated yet."""

    return CertificationReport(
        dataset_name=dataset_name,
        scale_profile=scale_profile,
        subset_manifest_id=subset_manifest_id,
        synthetic_generation_manifest_id=synthetic_generation_manifest_id,
        masking_policy_name=masking_policy_name,
        masking_policy_version=masking_policy_version,
        masking_engine_version=masking_engine_version,
        notes=notes,
    )


def start_processing(report: CertificationReport, *, actor: str) -> CertificationReport:
    """`DRAFT -> PROCESSING`: the pipeline is now actively running gates."""

    return transition(report, CertificationStatus.PROCESSING, actor=actor)


def certify(
    report: CertificationReport,
    gates: list[CertificationGateResult],
    *,
    row_count_reconciliation: dict[str, str] | None = None,
    actor: str,
    signing_key: bytes | None = None,
) -> CertificationReport:
    """Attach `gates` to `report` and transition it to `CERTIFIED` (every
    gate passed) or `FAILED` (at least one did not).

    Requires `report.status is PROCESSING` -- calling this on a `DRAFT`
    report (skipping `start_processing`), or calling it twice on an
    already-`CERTIFIED`/`FAILED` report, is rejected, because a
    certification decision must be made exactly once per report from a
    known starting state, not layered on top of an already-decided one.

    An empty `gates` list is treated as a failure (`bool(gates) and
    all(...)`), not a vacuous pass -- a certification run that recorded
    zero gate results proves nothing.
    """

    if report.status is not CertificationStatus.PROCESSING:
        raise InvalidCertificationTransitionError(
            f"certify() requires a report currently in 'processing' status, got "
            f"{report.status.value!r}. Call start_processing() first."
        )

    with_gates = report.model_copy(
        update={
            "gates": list(gates),
            "row_count_reconciliation": dict(row_count_reconciliation or {}),
        }
    )

    all_passed = bool(gates) and all(g.passed for g in gates)
    new_status = CertificationStatus.CERTIFIED if all_passed else CertificationStatus.FAILED

    extra_updates: dict[str, object] = {}
    if new_status is CertificationStatus.CERTIFIED:
        now = datetime.now(timezone.utc)
        extra_updates = {"certified_at": now, "updated_at": now}

    return transition(
        with_gates,
        new_status,
        actor=actor,
        signing_key=signing_key,
        extra_updates=extra_updates,
    )


__all__ = ["build_draft_report", "certify", "start_processing"]
