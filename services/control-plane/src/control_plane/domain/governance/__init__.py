"""Centralized enterprise masking governance (Phase 10) -- a governed,
versioned wrapper around Phase 3's `MaskingPolicy` with a real approval
workflow, plus the named business consumers (`LEFT_ARM`, `RIGHT_ARM`)
that request datasets exclusively through an *approved* policy version,
never their own masking rules. See ADR-0014 for why this domain lives
in `services/control-plane` rather than `services/governance-service`.

Module map
----------
- `state_machine.py` -- the enforced `PolicyApprovalStatus` transition
  table (mirrors `control_plane.domain.lifecycle.state_machine`, which
  itself mirrors `data_plane.certification.state_machine`) plus, since
  Phase 18B (`problems_final_review.md` P3-4), the enforced
  `ConsumerRequestStatus` transition table (REJECTED/CANCELLED terminal
  states).
- `errors.py` -- domain-specific exceptions, mapped to HTTP status codes
  by `control_plane.api.v1.governance`.
- `repository.py` -- `GovernanceRepository`, the one place that reads/
  writes the Phase 10 tables (`control_plane.db.models`) and calls
  directly into `control_plane.domain.lifecycle.LifecycleRepository`
  (Phase 7) to schedule a consumer's demand into the platform's real,
  existing refresh/capacity machinery.
"""

from control_plane.domain.governance.errors import (
    BusinessConsumerNotFoundError,
    ConsumerDatasetRequestNotFoundError,
    DuplicateBusinessConsumerCodeError,
    InvalidConsumerRequestTransitionError,
    InvalidPolicyApprovalTransitionError,
    MaskingPolicyVersionNotFoundError,
    PolicyVersionNotApprovedError,
)
from control_plane.domain.governance.repository import GovernanceRepository

__all__ = [
    "BusinessConsumerNotFoundError",
    "ConsumerDatasetRequestNotFoundError",
    "DuplicateBusinessConsumerCodeError",
    "GovernanceRepository",
    "InvalidConsumerRequestTransitionError",
    "InvalidPolicyApprovalTransitionError",
    "MaskingPolicyVersionNotFoundError",
    "PolicyVersionNotApprovedError",
]
