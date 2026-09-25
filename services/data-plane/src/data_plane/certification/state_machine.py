"""The enforced `CertificationStatus` state machine.

`healthcare_tdm_contracts.CERTIFICATION_STATUS_TRANSITIONS` documents the
allowed-transition table as data. This module is where that table is
actually *enforced*: every status change to a `CertificationReport` must
go through `transition()` (or its `publish()`/`revoke()` convenience
wrappers), which raises `InvalidCertificationTransitionError` for
anything not in the table, rather than the table being a comment a caller
could ignore.

This is the concrete mechanism behind this phase's core requirement: "A
FAILED dataset must not be publishable." `CERTIFICATION_STATUS_TRANSITIONS[FAILED]`
is the empty set, so `publish()` on a FAILED report raises before any
other code runs -- see `tests/certification/test_state_machine.py` for
the adversarial tests that exercise exactly this.
"""

from __future__ import annotations

from datetime import datetime, timezone

from healthcare_tdm_contracts import (
    CERTIFICATION_STATUS_TRANSITIONS,
    CertificationReport,
    CertificationStatus,
    CertificationStatusEvent,
)

from data_plane.certification.signing import raise_if_tampered, sign_report


class InvalidCertificationTransitionError(RuntimeError):
    """Raised when a requested `CertificationStatus` transition is not in
    `CERTIFICATION_STATUS_TRANSITIONS` -- an invalid transition is
    rejected by this code path, not merely discouraged by convention."""


def transition(
    report: CertificationReport,
    new_status: CertificationStatus,
    *,
    actor: str,
    reason: str = "",
    signing_key: bytes | None = None,
    extra_updates: dict[str, object] | None = None,
) -> CertificationReport:
    """Move `report` from its current status to `new_status`, or raise.

    Returns a **new** `CertificationReport` (reports are treated as
    immutable snapshots, consistent with every other `libs/contracts`
    manifest/report shape) with `status`, `updated_at`, and
    `status_history` updated, freshly (re-)signed if `signing_key` is
    given. `extra_updates` (used by `publish`/`revoke` to also set
    `published_at`/`revoked_at`/`revoked_reason` in the *same* update) is
    applied **before** signing -- every field change belonging to this
    transition must be part of the content that gets signed, or the
    resulting signature would not cover the report's true final state
    (a bug caught by this module's own tests: signing before applying
    `published_at` produced a report whose own freshly-computed
    signature immediately failed re-verification).

    If `report.integrity_signature` is already set and `signing_key` is
    given, the *current* signature is verified first
    (`signing.raise_if_tampered`) -- a report whose recorded content does
    not match its own signature must never be allowed to transition
    further, because at that point its `status` field itself cannot be
    trusted to be what it claims.
    """

    if report.integrity_signature is not None and signing_key is not None:
        raise_if_tampered(report, signing_key)

    allowed = CERTIFICATION_STATUS_TRANSITIONS.get(report.status, frozenset())
    if new_status not in allowed:
        raise InvalidCertificationTransitionError(
            f"Cannot transition certification report {report.report_id} from "
            f"{report.status.value!r} to {new_status.value!r}. Allowed next state(s) from "
            f"{report.status.value!r}: {sorted(s.value for s in allowed) or '(none -- terminal state)'}."
        )

    now = datetime.now(timezone.utc)
    event = CertificationStatusEvent(status=new_status, occurred_at=now, actor=actor, reason=reason)
    updated = report.model_copy(
        update={
            "status": new_status,
            "updated_at": now,
            "status_history": [*report.status_history, event],
            **(extra_updates or {}),
        }
    )

    if signing_key is not None:
        updated = sign_report(updated, signing_key)

    return updated


def publish(
    report: CertificationReport, *, actor: str, signing_key: bytes | None = None
) -> CertificationReport:
    """Publish a certified dataset.

    Sugar over `transition(..., CertificationStatus.PUBLISHED)`, but
    checked explicitly and eagerly here (not only via the transition
    table) so the specific, named requirement this phase calls out --
    "A FAILED dataset must not be publishable" -- has its own,
    unambiguous guard and error message, not just a generic "invalid
    transition" message. (The transition table would reject this exact
    same call for a different reason too: `FAILED`'s allowed-transition
    set is empty, so `publish()` on a FAILED report is doubly rejected.)
    """

    if report.status is not CertificationStatus.CERTIFIED:
        raise InvalidCertificationTransitionError(
            f"Cannot publish certification report {report.report_id}: status is "
            f"{report.status.value!r}, not 'certified'. Only a CERTIFIED report -- every "
            "required gate passed -- may be published. See docs/CERTIFICATION_VS_MASKING.md."
        )

    now = datetime.now(timezone.utc)
    return transition(
        report,
        CertificationStatus.PUBLISHED,
        actor=actor,
        signing_key=signing_key,
        extra_updates={"published_at": now, "updated_at": now},
    )


def revoke(
    report: CertificationReport,
    *,
    actor: str,
    reason: str,
    signing_key: bytes | None = None,
) -> CertificationReport:
    """Revoke a CERTIFIED or PUBLISHED dataset's certification.

    `reason` is required (unlike `transition`'s optional `reason`) -- a
    revocation with no recorded reason is exactly the kind of governance
    gap `SECURITY.md`/`DATA_GOVERNANCE.md` warn against for any action
    that changes whether a dataset is considered safe to use.
    """

    if not reason.strip():
        raise ValueError("revoke() requires a non-empty reason.")

    now = datetime.now(timezone.utc)
    return transition(
        report,
        CertificationStatus.REVOKED,
        actor=actor,
        reason=reason,
        signing_key=signing_key,
        extra_updates={"revoked_at": now, "revoked_reason": reason, "updated_at": now},
    )


__all__ = ["InvalidCertificationTransitionError", "publish", "revoke", "transition"]
