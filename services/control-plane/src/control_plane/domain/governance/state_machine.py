"""The enforced `PolicyApprovalStatus`/`ConsumerRequestStatus` transition
rules.

Mirrors `control_plane.domain.lifecycle.state_machine` (Phase 7), which
itself mirrors `data_plane.certification.state_machine` (Phase 6): each
transition *table* is data, living in
`healthcare_tdm_contracts.POLICY_APPROVAL_STATUS_TRANSITIONS`/
`CONSUMER_REQUEST_STATUS_TRANSITIONS`; this module is the one place that
*enforces* either -- every status change on a `MaskingPolicyVersionRow`
goes through `transition()`, and every status change on a
`ConsumerDatasetRequestRow` goes through
`transition_consumer_request()` (added Phase 18B,
`problems_final_review.md` P3-4) -- each raises its own
`Invalid*TransitionError` for anything not listed in its table.
"""

from __future__ import annotations

from healthcare_tdm_contracts import (
    CONSUMER_REQUEST_STATUS_TRANSITIONS,
    POLICY_APPROVAL_STATUS_TRANSITIONS,
    ConsumerRequestStatus,
    PolicyApprovalStatus,
)

from control_plane.domain.governance.errors import (
    InvalidConsumerRequestTransitionError,
    InvalidPolicyApprovalTransitionError,
)


def transition(current: PolicyApprovalStatus, target: PolicyApprovalStatus) -> PolicyApprovalStatus:
    """Validate `current -> target` against
    `POLICY_APPROVAL_STATUS_TRANSITIONS` and return `target` on success.
    Raises `InvalidPolicyApprovalTransitionError` otherwise. A no-op
    transition (`current == target`) is always rejected, the same
    convention `control_plane.domain.lifecycle.state_machine` and
    `data_plane.certification.state_machine` both use."""

    allowed = POLICY_APPROVAL_STATUS_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidPolicyApprovalTransitionError(
            f"Cannot transition masking policy version approval status from "
            f"{current.value!r} to {target.value!r}. Allowed from {current.value!r}: "
            f"{sorted(s.value for s in allowed) or 'none (terminal)'}."
        )
    return target


def transition_consumer_request(
    current: ConsumerRequestStatus, target: ConsumerRequestStatus
) -> ConsumerRequestStatus:
    """Validate `current -> target` against
    `CONSUMER_REQUEST_STATUS_TRANSITIONS` and return `target` on success.
    Raises `InvalidConsumerRequestTransitionError` otherwise -- in
    particular, this is what makes FULFILLED/REJECTED/CANCELLED real
    terminal states: a second call to fulfill/reject/cancel an already-
    resolved `ConsumerDatasetRequest` is rejected by code here, not
    merely undocumented."""

    allowed = CONSUMER_REQUEST_STATUS_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidConsumerRequestTransitionError(
            f"Cannot transition consumer dataset request status from "
            f"{current.value!r} to {target.value!r}. Allowed from {current.value!r}: "
            f"{sorted(s.value for s in allowed) or 'none (terminal)'}."
        )
    return target


__all__ = ["transition", "transition_consumer_request"]
