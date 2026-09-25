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

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.domain.governance import (
    BusinessConsumerNotFoundError,
    ConsumerDatasetRequestNotFoundError,
    GovernanceRepository,
    InvalidPolicyApprovalTransitionError,
    MaskingPolicyVersionNotFoundError,
    PolicyVersionNotApprovedError,
)
from control_plane.domain.lifecycle import NoActiveDatasetVersionError

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


@router.post("/policy-versions/{policy_version_id}/approve", response_model=MaskingPolicyVersion)
def approve_policy_version(
    policy_version_id: UUID,
    body: PolicyApprovalActionRequest,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> MaskingPolicyVersion:
    """Approve a PENDING_APPROVAL policy version. Also supersedes any
    other currently-APPROVED version of the same `policy_name` -- see
    `GovernanceRepository.approve_policy_version`."""

    try:
        return repository.approve_policy_version(
            policy_version_id, performed_by=body.performed_by, comments=body.comments
        )
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidPolicyApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/policy-versions/{policy_version_id}/reject", response_model=MaskingPolicyVersion)
def reject_policy_version(
    policy_version_id: UUID,
    body: PolicyApprovalActionRequest,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> MaskingPolicyVersion:
    try:
        return repository.reject_policy_version(
            policy_version_id, performed_by=body.performed_by, comments=body.comments
        )
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidPolicyApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    body: SubmitConsumerRequestBody, repository: GovernanceRepository = Depends(get_governance_repository)
) -> ConsumerDatasetRequest:
    """Submit a business consumer's request for a dataset, referencing
    an APPROVED `MaskingPolicyVersion` by id. Rejected with 409 if that
    policy version is not APPROVED -- see
    `GovernanceRepository.submit_consumer_request`."""

    try:
        return repository.submit_consumer_request(
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


@router.post("/consumer-requests/{consumer_request_id}/fulfill", response_model=ConsumerDatasetRequest)
def fulfill_consumer_request(
    consumer_request_id: UUID,
    body: FulfillConsumerRequestBody,
    repository: GovernanceRepository = Depends(get_governance_repository),
) -> ConsumerDatasetRequest:
    """Resolve a submitted request into a real Phase 7
    `EnvironmentDatasetRequest` -- see
    `GovernanceRepository.fulfill_consumer_request`. Rejected with 409
    if no ACTIVE Phase 7 `DatasetVersion` has been registered yet for
    this request's `dataset_name`."""

    try:
        return repository.fulfill_consumer_request(consumer_request_id, triggered_by=body.triggered_by)
    except ConsumerDatasetRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoActiveDatasetVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
