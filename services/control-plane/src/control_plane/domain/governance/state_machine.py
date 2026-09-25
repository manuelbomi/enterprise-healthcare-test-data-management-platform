"""The enforced `PolicyApprovalStatus` transition rule.

Mirrors `control_plane.domain.lifecycle.state_machine` (Phase 7), which
itself mirrors `data_plane.certification.state_machine` (Phase 6): the
transition *table* is data, living in
`healthcare_tdm_contracts.POLICY_APPROVAL_STATUS_TRANSITIONS`; this
module is the one place that *enforces* it -- every status change on a
`MaskingPolicyVersionRow` goes through `transition()`, which raises
`InvalidPolicyApprovalTransitionError` for anything not listed in that
table.
"""

from __future__ import annotations

from healthcare_tdm_contracts import POLICY_APPROVAL_STATUS_TRANSITIONS, PolicyApprovalStatus

from control_plane.domain.governance.errors import InvalidPolicyApprovalTransitionError


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


__all__ = ["transition"]
