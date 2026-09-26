"""Centralized enterprise masking governance endpoints (Phase 10).

Reuses `api/v1/lifecycle.py`'s `get_db_session` dependency rather than
redefining it, the same way `api/v1/capacity.py` (Phase 8) does -- a
test overriding `get_db_session` transparently points every router
(lifecycle, capacity, governance) at the same temporary database, and
`GovernanceRepository`'s internal `LifecycleRepository` is guaranteed to
share the exact same `Session`/transaction as this router's own calls.

Route handlers do exactly three things, the same convention
`api/v1/lifecycle.py` establishes: resolve a `GovernanceRepository` via
dependency injection, call one of its methods, and translate domain
exceptions to HTTP status codes. No business logic lives here -- see
`control_plane.domain.governance.repository` for that.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from healthcare_tdm_contracts import (
    AuditEventType,
    BusinessConsumer,
    ConsumerDatasetRequest,
    Environment,
    MaskingPolicy,
    MaskingPolicyVersion,
    PolicyApproval,
    PolicyApprovalStatus,
    RefreshCadenceType,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_audit_log, get_db_session
from control_plane.domain.governance import (
    BusinessConsumerNotFoundError,
    ConsumerDatasetRequestNotFoundError,
    GovernanceRepository,
    InvalidConsumerRequestTransitionError,
    InvalidPolicyApprovalTransitionError,
    MaskingPolicyVersionNotFoundError,
    PolicyVersionNotApprovedError,
)
from control_plane.domain.lifecycle import NoActiveDatasetVersionError
from control_plane.platform.audit import AuditLogRepository
from control_plane.platform.auth import AuthenticatedActor, get_current_actor
from control_plane.platform.rbac import AuthorizationError, Permission, Role, authorize

router = APIRouter(prefix="/governance", tags=["governance"])


def get_governance_repository(session: Session = Depends(get_db_session)) -> GovernanceRepository:
    return GovernanceRepository(session)


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------


class DraftPolicyVersionRequest(BaseModel):
    masking_policy: MaskingPolicy
    masking_engine_version: str
    created_by: str
    notes: str = ""


class PolicyApprovalActionRequest(BaseModel):
    performed_by: str
    comments: str = ""


class PolicyApprovalDecisionRequest(PolicyApprovalActionRequest):
    """Used only by `approve_policy_version`/`reject_policy_version`
    below -- `submit_policy_version_for_approval` (drafting/submitting,
    a lower-sensitivity action) keeps using the plain
    `PolicyApprovalActionRequest` unchanged. Phase 11: the caller must
    hold `Permission.APPROVE_POLICY_VERSION`/`Permission.REJECT_POLICY_VERSION`
    (only `COMPLIANCE_APPROVER`/`PLATFORM_ADMIN` hold either). Phase 18A
    (`problems_final_review.md` P0-1): this used to carry its own
    `actor_role` field, trusted directly from the request body -- it no
    longer does. The role checked now comes from the caller's verified
    bearer token (`AuthenticatedActor`, `Depends(get_current_actor)`) --
    see `control_plane.platform.auth`'s module docstring. This class is
    kept distinct from its parent (rather than merged, now that its
    field set matches) as a placeholder for a future decision-specific
    field (e.g. a required rejection reason)."""


class RegisterBusinessConsumerRequest(BaseModel):
    code: str
    display_name: str
    description: str = ""
    contact: str = ""


class SubmitConsumerRequestBody(BaseModel):
    business_consumer_id: UUID
    dataset_name: str
    environment: Environment
    policy_version_id: UUID
    subset_size_hint: str = ""
    refresh_cadence_type: RefreshCadenceType
    performance_requirements: str = ""
    requested_by: str
    notes: str = ""


class FulfillConsumerRequestBody(BaseModel):
    triggered_by: str = Field(default="governance-service")


class ResolveConsumerRequestBody(BaseModel):
    """Phase 18B (`problems_final_review.md` P3-4): shared request body
    for both `reject_consumer_request`/`cancel_consumer_request` -- same
    shape (who + an optional free-text reason), same as
    `FulfillConsumerRequestBody`'s own "who triggered this" convention."""

    performed_by: str = Field(default="governance-service")
    reason: str = Field(default="")


# ----------------------------------------------------------------------
# Masking policy versions
# ----------------------------------------------------------------------


@router.post("/policy-versions", response_model=MaskingPolicyVersion, status_code=201)
def draft_policy_version(
    body: DraftPolicyVersionRequest, repository: GovernanceRepository = Depends(get_governance_repository)
) -> MaskingPolicyVersion:
    """Draft a new governed `MaskingPolicyVersion` wrapping a real Phase
    3 `MaskingPolicy`. Starts in DRAFT -- not usable by any
    `ConsumerDatasetRequest` until submitted and approved."""

    try:
        return repository.draft_policy_version(
            masking_policy=body.masking_policy,
            masking_engine_version=body.masking_engine_version,
            created_by=body.created_by,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/policy-versions", response_model=list[MaskingPolicyVersion])
def list_policy_versions(
    policy_name: str | None = None,
    approval_status: PolicyApprovalStatus | None = None,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> list[MaskingPolicyVersion]:
    return repository.list_policy_versions(policy_name=policy_name, approval_status=approval_status)


@router.get("/policy-versions/{policy_version_id}", response_model=MaskingPolicyVersion)
def get_policy_version(
    policy_version_id: UUID, repository: GovernanceRepository = Depends(get_governance_repository)
) -> MaskingPolicyVersion:
    try:
        return repository.get_policy_version(policy_version_id)
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/policy-versions/approved/{policy_name}", response_model=MaskingPolicyVersion)
def get_approved_policy_version(
    policy_name: str, repository: GovernanceRepository = Depends(get_governance_repository)
) -> MaskingPolicyVersion:
    """The single currently-APPROVED `MaskingPolicyVersion` for
    `policy_name` -- what a real `ConsumerDatasetRequest` submission
    would look up first."""

    try:
        return repository.get_approved_policy_version(policy_name)
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/policy-versions/{policy_version_id}/submit", response_model=MaskingPolicyVersion)
def submit_policy_version(
    policy_version_id: UUID,
    body: PolicyApprovalActionRequest,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> MaskingPolicyVersion:
    try:
        return repository.submit_policy_version_for_approval(
            policy_version_id, performed_by=body.performed_by, comments=body.comments
        )
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidPolicyApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _authorize_or_deny(
    *,
    actor_role: Role,
    permission: Permission,
    audit: AuditLogRepository,
    session: Session,
    actor: str,
    subject: str,
) -> None:
    """Shared RBAC-check-then-deny helper for `approve_policy_version`/
    `reject_policy_version` -- see `api.v1.lifecycle.revoke_dataset_version`'s
    docstring for why the denial audit event is committed immediately
    (survives the `HTTPException` this then raises)."""

    try:
        authorize(actor_role, permission)
    except AuthorizationError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=actor,
            subject=subject,
            outcome="denied",
            detail={"permission": permission.value, "actor_role": actor_role.value},
        )
        session.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/policy-versions/{policy_version_id}/approve", response_model=MaskingPolicyVersion)
def approve_policy_version(
    policy_version_id: UUID,
    body: PolicyApprovalDecisionRequest,
    actor: AuthenticatedActor = Depends(get_current_actor),
    repository: GovernanceRepository = Depends(get_governance_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> MaskingPolicyVersion:
    """Approve a PENDING_APPROVAL policy version. Also supersedes any
    other currently-APPROVED version of the same `policy_name` -- see
    `GovernanceRepository.approve_policy_version`.

    Phase 11: requires the caller to hold
    `Permission.APPROVE_POLICY_VERSION` -- resolves
    `problems_phase_10.md` P10-2 for this one endpoint specifically
    (every other governance mutation remains ungated; see
    `problems_phase_11.md` P11-4). Phase 18A
    (`problems_final_review.md` P0-1): the role is now a verified claim
    from the caller's bearer token (`Depends(get_current_actor)`), not a
    caller-supplied `body.actor_role` field -- see
    `control_plane.platform.auth`'s module docstring."""

    _authorize_or_deny(
        actor_role=actor.role,
        permission=Permission.APPROVE_POLICY_VERSION,
        audit=audit,
        session=session,
        actor=actor.username,
        subject=str(policy_version_id),
    )
    try:
        result = repository.approve_policy_version(
            policy_version_id, performed_by=body.performed_by, comments=body.comments
        )
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidPolicyApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        # Phase 18B (`problems_final_review.md` P2-13): the audit
        # trail's own `actor` field -- what `docs/COMPLIANCE_EVIDENCE.md`
        # says an auditor would rely on -- now records the verified
        # bearer-token identity (`actor.username`), not the unverified
        # `body.performed_by` free-text field. `body.performed_by`
        # itself is unchanged (still recorded on the domain-level
        # `PolicyApproval` row, still free text -- this closes the
        # *audit-trail* half of the gap, not every occurrence of
        # caller-supplied attribution platform-wide; see the module
        # docstring cross-reference this finding's entry now carries).
        event_type=AuditEventType.POLICY_APPROVED,
        actor=actor.username,
        subject=str(policy_version_id),
        outcome="allowed",
        detail={"comments": body.comments, "actor_role": actor.role.value, "performed_by": body.performed_by},
    )
    return result


@router.post("/policy-versions/{policy_version_id}/reject", response_model=MaskingPolicyVersion)
def reject_policy_version(
    policy_version_id: UUID,
    body: PolicyApprovalDecisionRequest,
    actor: AuthenticatedActor = Depends(get_current_actor),
    repository: GovernanceRepository = Depends(get_governance_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> MaskingPolicyVersion:
    """Phase 11: requires the caller to hold
    `Permission.REJECT_POLICY_VERSION` -- see `approve_policy_version`'s
    docstring, including Phase 18A's switch to a verified bearer token."""

    _authorize_or_deny(
        actor_role=actor.role,
        permission=Permission.REJECT_POLICY_VERSION,
        audit=audit,
        session=session,
        actor=actor.username,
        subject=str(policy_version_id),
    )
    try:
        result = repository.reject_policy_version(
            policy_version_id, performed_by=body.performed_by, comments=body.comments
        )
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidPolicyApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(
        # Phase 18B (`problems_final_review.md` P2-13): see
        # `approve_policy_version`'s identical comment above -- the
        # audit trail's `actor` field is now the verified bearer-token
        # identity, not the unverified `body.performed_by`.
        event_type=AuditEventType.POLICY_REJECTED,
        actor=actor.username,
        subject=str(policy_version_id),
        outcome="allowed",
        detail={"comments": body.comments, "actor_role": actor.role.value, "performed_by": body.performed_by},
    )
    return result


@router.get("/policy-versions/{policy_version_id}/approvals", response_model=list[PolicyApproval])
def list_policy_approvals(
    policy_version_id: UUID, repository: GovernanceRepository = Depends(get_governance_repository)
) -> list[PolicyApproval]:
    return repository.list_policy_approvals(policy_version_id)


# ----------------------------------------------------------------------
# Business consumers
# ----------------------------------------------------------------------


@router.post("/business-consumers", response_model=BusinessConsumer, status_code=201)
def register_business_consumer(
    body: RegisterBusinessConsumerRequest,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> BusinessConsumer:
    try:
        return repository.register_business_consumer(
            code=body.code,
            display_name=body.display_name,
            description=body.description,
            contact=body.contact,
        )
    except Exception as exc:  # DuplicateBusinessConsumerCodeError
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/business-consumers", response_model=list[BusinessConsumer])
def list_business_consumers(
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> list[BusinessConsumer]:
    return repository.list_business_consumers()


@router.get("/business-consumers/{business_consumer_id}", response_model=BusinessConsumer)
def get_business_consumer(
    business_consumer_id: UUID, repository: GovernanceRepository = Depends(get_governance_repository)
) -> BusinessConsumer:
    try:
        return repository.get_business_consumer(business_consumer_id)
    except BusinessConsumerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Consumer dataset requests
# ----------------------------------------------------------------------


@router.post("/consumer-requests", response_model=ConsumerDatasetRequest, status_code=201)
def submit_consumer_request(
    body: SubmitConsumerRequestBody,
    repository: GovernanceRepository = Depends(get_governance_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> ConsumerDatasetRequest:
    """Submit a business consumer's request for a dataset, referencing
    an APPROVED `MaskingPolicyVersion` by id. Rejected with 409 if that
    policy version is not APPROVED -- see
    `GovernanceRepository.submit_consumer_request`."""

    try:
        result = repository.submit_consumer_request(
            business_consumer_id=body.business_consumer_id,
            dataset_name=body.dataset_name,
            environment=body.environment,
            policy_version_id=body.policy_version_id,
            subset_size_hint=body.subset_size_hint,
            refresh_cadence_type=body.refresh_cadence_type,
            performance_requirements=body.performance_requirements,
            requested_by=body.requested_by,
            notes=body.notes,
        )
    except BusinessConsumerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PolicyVersionNotApprovedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.CONSUMER_REQUEST_SUBMITTED,
        actor=body.requested_by,
        subject=str(result.consumer_request_id),
        outcome="allowed",
        detail={"dataset_name": body.dataset_name, "environment": body.environment.value},
    )
    return result


@router.post("/consumer-requests/{consumer_request_id}/fulfill", response_model=ConsumerDatasetRequest)
def fulfill_consumer_request(
    consumer_request_id: UUID,
    body: FulfillConsumerRequestBody,
    repository: GovernanceRepository = Depends(get_governance_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> ConsumerDatasetRequest:
    """Resolve a submitted request into a real Phase 7
    `EnvironmentDatasetRequest` -- see
    `GovernanceRepository.fulfill_consumer_request`. Rejected with 409
    if no ACTIVE Phase 7 `DatasetVersion` has been registered yet for
    this request's `dataset_name` -- including when the only version
    that ever existed has since been REVOKED (Phase 11's governance-layer
    extension of Phase 7's revocation guarantee; see
    `test_failure_injection.py::test_consumer_cannot_fulfill_request_against_a_revoked_dataset_version`)."""

    try:
        result = repository.fulfill_consumer_request(consumer_request_id, triggered_by=body.triggered_by)
    except ConsumerDatasetRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoActiveDatasetVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidConsumerRequestTransitionError as exc:
        # Phase 18B (P3-4): the request is not currently SUBMITTED (e.g.
        # already FULFILLED, REJECTED, or CANCELLED) -- refused, not a
        # 500, exactly like the other two `Invalid*TransitionError`
        # cases this router already translates.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.CONSUMER_REQUEST_FULFILLED,
        actor=body.triggered_by,
        subject=str(consumer_request_id),
        outcome="allowed",
        detail={"environment_request_id": str(result.environment_request_id)},
    )
    return result


@router.post("/consumer-requests/{consumer_request_id}/reject", response_model=ConsumerDatasetRequest)
def reject_consumer_request(
    consumer_request_id: UUID,
    body: ResolveConsumerRequestBody,
    repository: GovernanceRepository = Depends(get_governance_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> ConsumerDatasetRequest:
    """Phase 18B (`problems_final_review.md` P3-4): SUBMITTED -> REJECTED.
    Terminal. Rejected with 409 if the request is not currently
    SUBMITTED (e.g. already FULFILLED/REJECTED/CANCELLED) -- see
    `GovernanceRepository.reject_consumer_request`."""

    try:
        result = repository.reject_consumer_request(
            consumer_request_id, performed_by=body.performed_by, reason=body.reason
        )
    except ConsumerDatasetRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidConsumerRequestTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.CONSUMER_REQUEST_REJECTED,
        actor=body.performed_by,
        subject=str(consumer_request_id),
        outcome="allowed",
        detail={"reason": body.reason},
    )
    return result


@router.post("/consumer-requests/{consumer_request_id}/cancel", response_model=ConsumerDatasetRequest)
def cancel_consumer_request(
    consumer_request_id: UUID,
    body: ResolveConsumerRequestBody,
    repository: GovernanceRepository = Depends(get_governance_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> ConsumerDatasetRequest:
    """Phase 18B (`problems_final_review.md` P3-4): SUBMITTED -> CANCELLED.
    Terminal. Rejected with 409 if the request is not currently
    SUBMITTED -- see `GovernanceRepository.cancel_consumer_request`."""

    try:
        result = repository.cancel_consumer_request(
            consumer_request_id, performed_by=body.performed_by, reason=body.reason
        )
    except ConsumerDatasetRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidConsumerRequestTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.CONSUMER_REQUEST_CANCELLED,
        actor=body.performed_by,
        subject=str(consumer_request_id),
        outcome="allowed",
        detail={"reason": body.reason},
    )
    return result


@router.get("/consumer-requests", response_model=list[ConsumerDatasetRequest])
def list_consumer_requests(
    business_consumer_id: UUID | None = None,
    environment: Environment | None = None,
    dataset_name: str | None = None,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> list[ConsumerDatasetRequest]:
    return repository.list_consumer_requests(
        business_consumer_id=business_consumer_id, environment=environment, dataset_name=dataset_name
    )


@router.get("/consumer-requests/{consumer_request_id}", response_model=ConsumerDatasetRequest)
def get_consumer_request(
    consumer_request_id: UUID, repository: GovernanceRepository = Depends(get_governance_repository)
) -> ConsumerDatasetRequest:
    try:
        return repository.get_consumer_request(consumer_request_id)
    except ConsumerDatasetRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["get_governance_repository", "router"]
