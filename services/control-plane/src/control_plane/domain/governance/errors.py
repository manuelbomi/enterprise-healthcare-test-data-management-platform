"""Domain-specific exceptions for `control_plane.domain.governance`.

Raised by `GovernanceRepository`; caught and translated to HTTP status
codes by `control_plane.api.v1.governance` -- the exact convention
`control_plane.domain.lifecycle.errors` already established for Phase 7.
"""

from __future__ import annotations


class MaskingPolicyVersionNotFoundError(LookupError):
    """No `MaskingPolicyVersionRow` exists for the given identifier."""


class BusinessConsumerNotFoundError(LookupError):
    """No `BusinessConsumerRow` exists for the given identifier or code."""


class ConsumerDatasetRequestNotFoundError(LookupError):
    """No `ConsumerDatasetRequestRow` exists for the given identifier."""


class InvalidPolicyApprovalTransitionError(RuntimeError):
    """An attempted `PolicyApprovalStatus` transition is not listed in
    `healthcare_tdm_contracts.POLICY_APPROVAL_STATUS_TRANSITIONS`."""


class InvalidConsumerRequestTransitionError(RuntimeError):
    """Phase 18B (`problems_final_review.md` P3-4): an attempted
    `ConsumerRequestStatus` transition is not listed in
    `healthcare_tdm_contracts.CONSUMER_REQUEST_STATUS_TRANSITIONS` -- e.g.
    trying to fulfill/reject/cancel a request that is already in one of
    the three terminal states."""


class PolicyVersionNotApprovedError(RuntimeError):
    """A `ConsumerDatasetRequest` tried to reference a `MaskingPolicyVersion`
    whose `approval_status` is not APPROVED.

    This is the concrete, enforced mechanism behind `ROADMAP.md` Phase
    10's "consumers MUST NOT independently redefine sensitive-field
    masking": the *only* way a request can carry a masking-policy
    reference at all is a `policy_version_id` foreign key, and this
    exception is raised the moment that foreign key does not point at an
    approved version -- there is no separate code path that would let a
    request bypass this check with its own rules (there is nowhere to
    put them; see `healthcare_tdm_contracts.governance`'s module
    docstring)."""


class DuplicateBusinessConsumerCodeError(RuntimeError):
    """Attempted to register a `BusinessConsumer` with a `code` that is
    already in use."""


__all__ = [
    "BusinessConsumerNotFoundError",
    "ConsumerDatasetRequestNotFoundError",
    "DuplicateBusinessConsumerCodeError",
    "InvalidConsumerRequestTransitionError",
    "InvalidPolicyApprovalTransitionError",
    "MaskingPolicyVersionNotFoundError",
    "PolicyVersionNotApprovedError",
]
