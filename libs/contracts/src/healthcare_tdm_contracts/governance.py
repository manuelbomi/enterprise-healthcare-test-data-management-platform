"""Centralized enterprise masking governance contracts (Phase 10).

`ROADMAP.md` Phase 10 asks for a single, centrally governed masking
standard that multiple organizational arms/business units consume,
without any arm being able to redefine sensitive-field masking for
itself. Concretely: Phase 3 already produces a real, versioned
`MaskingPolicy` (`data_plane.masking.policy.DEFAULT_POLICY`,
`POLICY_NAME`/`POLICY_VERSION`) and Phase 7/8 already give this platform
a real, database-backed dataset lifecycle and capacity plane
(`Environment`, `EnvironmentDatasetRequest`, `RefreshCadenceType`,
`CapacityPlanner`). This module adds the missing piece between them: a
governed, *approved* wrapper around a `MaskingPolicy`
(`MaskingPolicyVersion` + `PolicyApproval`), and the two named business
consumers (`BusinessConsumer`) that request datasets
(`ConsumerDatasetRequest`) exclusively through that one approved wrapper
-- never by attaching their own masking rules.

Why `ConsumerDatasetRequest`, not `DatasetRequest`
----------------------------------------------------
`healthcare_tdm_contracts.lifecycle.EnvironmentDatasetRequest` (Phase 7)
already owns the name "dataset request" for one environment's standing
pointer at a `DatasetVersion`. This module's request shape is a
different thing one layer up -- a *business consumer's* ask, which
resolves into (and is fulfilled by creating/reusing) exactly one
`EnvironmentDatasetRequest` via
`control_plane.domain.governance.repository.GovernanceRepository`. Using
a distinct name (`ConsumerDatasetRequest`) avoids the naming collision
the Phase 10 prompt explicitly calls out, and the `environment_request_id`
field below is the literal foreign key proving the consumer's demand
rides Phase 7's existing machinery rather than a second, parallel one.

Governance is structural, not just conventional
---------------------------------------------------
`ConsumerDatasetRequest` has no field of any kind that could carry a
masking rule, technique, or policy override -- only a `policy_version_id`
foreign key to an *already-approved* `MaskingPolicyVersion`. There is no
constructor path, in this model or in
`GovernanceRepository.submit_consumer_request`, that accepts anything
resembling a custom masking rule. `test_governance_repository.py`'s
`test_consumer_cannot_attach_custom_masking_rules` asserts this by
introspecting the model's fields and the repository method's signature,
in the same spirit as Phase 6's adversarial bypass tests
(`docs/CERTIFICATION_VS_MASKING.md`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.lifecycle import Environment, RefreshCadenceType
from healthcare_tdm_contracts.masking import MaskingPolicy


class PolicyApprovalStatus(str, Enum):
    """The five-state lifecycle of one `MaskingPolicyVersion`'s approval.

    Enforced as a real state machine (not just documentation) by
    `control_plane.domain.governance.state_machine.transition` -- the
    same split `data_plane.certification.state_machine` (Phase 6) and
    `control_plane.domain.lifecycle.state_machine` (Phase 7) already
    establish: the transition table is data (this module,
    `POLICY_APPROVAL_STATUS_TRANSITIONS`), the enforcement is code (the
    `governance` domain package).

    DRAFT
        A `MaskingPolicyVersion` has been created (wrapping a real
        `MaskingPolicy`) but has not been submitted for approval. Not
        usable by any `ConsumerDatasetRequest` yet.
    PENDING_APPROVAL
        Submitted; awaiting a governance decision.
    APPROVED
        A reviewer approved it (`PolicyApproval` records who/when).
        The *only* status a `ConsumerDatasetRequest` may reference.
    REJECTED
        A reviewer rejected it. Terminal -- a rejected version is never
        retried in place; a new `MaskingPolicyVersion` (new
        `policy_version`) is drafted instead, exactly like a `FAILED`
        `CertificationReport` is never retried in place (Phase 6).
    SUPERSEDED
        A later version of the same `policy_name` was approved. Terminal
        for this version, but still fully readable/auditable -- every
        `ConsumerDatasetRequest` that referenced it while it was APPROVED
        keeps its `policy_version_id` unchanged (immutable history,
        matching how a `REVOKED` `DatasetVersion` in Phase 7 is never
        deleted, only marked).
    """

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


#: The allowed-transition table (data only -- enforcement lives in
#: `control_plane.domain.governance.state_machine`).
POLICY_APPROVAL_STATUS_TRANSITIONS: dict[
    PolicyApprovalStatus, frozenset[PolicyApprovalStatus]
] = {
    PolicyApprovalStatus.DRAFT: frozenset({PolicyApprovalStatus.PENDING_APPROVAL}),
    PolicyApprovalStatus.PENDING_APPROVAL: frozenset(
        {PolicyApprovalStatus.APPROVED, PolicyApprovalStatus.REJECTED}
    ),
    PolicyApprovalStatus.APPROVED: frozenset({PolicyApprovalStatus.SUPERSEDED}),
    PolicyApprovalStatus.REJECTED: frozenset(),
    PolicyApprovalStatus.SUPERSEDED: frozenset(),
}


class MaskingPolicyVersion(BaseModel):
    """A governed, versioned wrapper around a real Phase 3 `MaskingPolicy`.

    This is deliberately *not* a duplicate of `MaskingPolicy.name`/
    `MaskingPolicy.version` (ADR-0011 already made those real, required
    fields) -- it wraps the *entire* policy content
    (`masking_policy`, the full `MaskingRule` list) as an immutable,
    approvable snapshot, the way `DatasetVersion` (Phase 7) wraps an
    entire `CertificationReport`'s masking provenance rather than only
    storing its `report_id`. Storing the full policy here means an
    approved policy version's exact rule set survives even if
    `data_plane.masking.policy.DEFAULT_POLICY` is later changed in code
    -- an auditor reviewing `ConsumerDatasetRequest`s from a year ago can
    see exactly which rules were approved and in force at the time,
    independent of source-tree history. See ADR-0014.
    """

    policy_version_id: UUID = Field(default_factory=uuid4)
    policy_name: str = Field(
        ..., description="Matches MaskingPolicy.name, e.g. 'phase3-default'."
    )
    policy_version: int = Field(
        ..., ge=1, description="Matches MaskingPolicy.version. Monotonically increasing per policy_name."
    )
    masking_policy: MaskingPolicy = Field(
        ..., description="The full, real Phase 3 policy content this version governs."
    )
    masking_engine_version: str = Field(
        ..., description="data_plane.masking.engine.MASKING_ENGINE_VERSION at the time this version "
        "was drafted -- recorded for the same reproducibility reason ADR-0011 records it on every "
        "masking run and CertificationReport."
    )
    approval_status: PolicyApprovalStatus = PolicyApprovalStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str
    notes: str = Field(default="")
    superseded_by_version_id: UUID | None = Field(
        default=None,
        description="Set when a later MaskingPolicyVersion of the same policy_name is approved.",
    )


class PolicyApproval(BaseModel):
    """One append-only governance decision against a `MaskingPolicyVersion`
    -- who acted, when, and the resulting status. Mirrors
    `RefreshRunRecord`/`RollbackRecord` (Phase 7): the *current* status
    lives on the parent row (`MaskingPolicyVersion.approval_status`),
    while every action that ever changed it is preserved here, forever,
    as the audit trail a compliance reviewer needs.
    """

    approval_id: UUID = Field(default_factory=uuid4)
    policy_version_id: UUID
    status: PolicyApprovalStatus = Field(
        ..., description="The status this MaskingPolicyVersion transitioned to as a result of this action."
    )
    performed_by: str
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    comments: str = Field(default="")


class BusinessConsumer(BaseModel):
    """One organizational arm/business unit that consumes centrally
    governed test data (`ROADMAP.md` Phase 10's `LEFT_ARM`/`RIGHT_ARM`).

    A plain reference/dimension row -- no state machine of its own
    (unlike `MaskingPolicyVersion`/`PolicyApproval`, `ConsumerDatasetRequest`
    below) because a business consumer does not itself go through an
    approval workflow; it is provisioned once by a platform
    administrator and then submits requests, each of which is
    individually governed.
    """

    business_consumer_id: UUID = Field(default_factory=uuid4)
    code: str = Field(..., description="Short, stable identifier, e.g. 'LEFT_ARM' or 'RIGHT_ARM'.")
    display_name: str
    description: str = Field(default="")
    contact: str = Field(default="")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConsumerRequestStatus(str, Enum):
    """Lifecycle of one `ConsumerDatasetRequest`.

    SUBMITTED
        Recorded, but not yet resolved into a Phase 7
        `EnvironmentDatasetRequest`.
    FULFILLED
        `GovernanceRepository.fulfill_consumer_request` has called into
        `LifecycleRepository.request_environment` (real Phase 7
        machinery) and recorded the resulting
        `environment_request_id` here.
    """

    SUBMITTED = "submitted"
    FULFILLED = "fulfilled"


class ConsumerDatasetRequest(BaseModel):
    """One business consumer's request for a dataset in an environment,
    governed by reference to an *approved* `MaskingPolicyVersion`.

    Deliberately carries no field that could express a masking rule,
    technique, or policy override -- see the module docstring
    ("Governance is structural, not just conventional"). Everything a
    consumer *may* vary (`subset_size_hint`, `refresh_cadence_type`,
    `environment`, `performance_requirements`) is business/operational
    parameterization, never masking policy.
    """

    consumer_request_id: UUID = Field(default_factory=uuid4)
    business_consumer_id: UUID
    business_consumer_code: str = Field(
        default="", description="Denormalized from BusinessConsumer.code for audit convenience."
    )
    dataset_name: str
    environment: Environment
    policy_version_id: UUID = Field(
        ..., description="FK to an APPROVED MaskingPolicyVersion. The only masking-policy reference "
        "this model carries -- see the module docstring."
    )
    masking_policy_name: str = Field(
        default="", description="Denormalized from the referenced MaskingPolicyVersion, for audit "
        "convenience even after a later SUPERSEDED transition."
    )
    masking_policy_version: int = Field(default=0)
    subset_size_hint: str = Field(
        default="", description="The consumer's own sizing request, e.g. '2% of patients, >=50 per "
        "rare condition' -- business parameterization, never a masking rule."
    )
    refresh_cadence_type: RefreshCadenceType
    performance_requirements: str = Field(default="")
    requested_by: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ConsumerRequestStatus = ConsumerRequestStatus.SUBMITTED
    environment_request_id: UUID | None = Field(
        default=None,
        description="FK to the Phase 7 EnvironmentDatasetRequest this request was fulfilled into -- "
        "the literal mechanism proving this demand was scheduled into the existing refresh "
        "calendar/capacity plan rather than a parallel implementation.",
    )
    notes: str = Field(default="")


__all__ = [
    "POLICY_APPROVAL_STATUS_TRANSITIONS",
    "BusinessConsumer",
    "ConsumerDatasetRequest",
    "ConsumerRequestStatus",
    "MaskingPolicyVersion",
    "PolicyApproval",
    "PolicyApprovalStatus",
]
