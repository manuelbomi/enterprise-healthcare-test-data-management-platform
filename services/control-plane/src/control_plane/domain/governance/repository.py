"""`GovernanceRepository` -- the one place that reads and writes the
Phase 10 centralized masking governance tables
(`control_plane.db.models`).

Owns the business logic `ROADMAP.md` Phase 10 asks for: drafting and
approving a `MaskingPolicyVersion` (a governed, versioned snapshot of a
real Phase 3 `MaskingPolicy`) through an enforced approval workflow,
registering `BusinessConsumer`s (the two named organizational arms,
`LEFT_ARM`/`RIGHT_ARM`), and letting a consumer submit a
`ConsumerDatasetRequest` that can only ever reference an *already
approved* policy version -- never supply its own masking rules (see
`healthcare_tdm_contracts.governance`'s module docstring for why that is
true by construction, not just by convention).

The headline integration point is `fulfill_consumer_request`: it does
not reimplement scheduling, refresh cadence, or capacity accounting --
it calls directly into `control_plane.domain.lifecycle.LifecycleRepository`
(Phase 7), within the *same* `sqlalchemy.orm.Session` this repository was
constructed with, so a consumer's demand becomes a real
`EnvironmentDatasetRequest` row Phase 7's scheduler/refresh machinery
and Phase 8's `CapacityPlanner` already know how to operate on. See
ADR-0014 for why this whole domain lives in `services/control-plane`
rather than `services/governance-service`.

Every public method takes/returns typed `healthcare_tdm_contracts`
Pydantic shapes, never a raw ORM row, mirroring
`control_plane.domain.lifecycle.repository.LifecycleRepository` exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from healthcare_tdm_contracts import (
    BusinessConsumer,
    ConsumerDatasetRequest,
    ConsumerRequestStatus,
    Environment,
    MaskingPolicy,
    MaskingPolicyVersion,
    PolicyApproval,
    PolicyApprovalStatus,
    RefreshCadenceType,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from control_plane.db.models import (
    BusinessConsumerRow,
    ConsumerDatasetRequestRow,
    MaskingPolicyVersionRow,
    PolicyApprovalRow,
)
from control_plane.domain.governance import state_machine as approval_state_machine
from control_plane.domain.governance.state_machine import transition_consumer_request
from control_plane.domain.governance.errors import (
    BusinessConsumerNotFoundError,
    ConsumerDatasetRequestNotFoundError,
    DuplicateBusinessConsumerCodeError,
    MaskingPolicyVersionNotFoundError,
    PolicyVersionNotApprovedError,
)
from control_plane.domain.lifecycle.repository import LifecycleRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


class GovernanceRepository:
    """Business logic + persistence for the Phase 10 centralized masking
    governance domain. One instance per request/unit-of-work, exactly
    like `LifecycleRepository` -- cheap to construct, holds only the
    session reference (and a `LifecycleRepository` sharing that same
    session, for the real Phase 7 integration `fulfill_consumer_request`
    performs)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.lifecycle = LifecycleRepository(session)

    # ------------------------------------------------------------------
    # Masking policy versions (governance over Phase 3's MaskingPolicy)
    # ------------------------------------------------------------------

    def draft_policy_version(
        self,
        *,
        masking_policy: MaskingPolicy,
        masking_engine_version: str,
        created_by: str,
        notes: str = "",
    ) -> MaskingPolicyVersion:
        """Draft a new `MaskingPolicyVersion` wrapping a real Phase 3
        `MaskingPolicy` (e.g. `data_plane.masking.policy.DEFAULT_POLICY`).

        `policy_version` is taken directly from `masking_policy.version`
        (ADR-0011: `MaskingPolicy.version` is already the authoritative
        version number for this `policy_name`) -- this method does not
        invent a second, independent version counter. Raises `ValueError`
        if a `MaskingPolicyVersion` for this exact
        `(policy_name, policy_version)` already exists, mirroring
        `DatasetVersionRow`'s uniqueness constraint.
        """

        existing = self._session.scalars(
            select(MaskingPolicyVersionRow).where(
                MaskingPolicyVersionRow.policy_name == masking_policy.name,
                MaskingPolicyVersionRow.policy_version == masking_policy.version,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"MaskingPolicyVersion already exists for policy_name={masking_policy.name!r} "
                f"policy_version={masking_policy.version!r} (policy_version_id={existing.policy_version_id})."
            )

        row = MaskingPolicyVersionRow(
            policy_version_id=_new_id(),
            policy_name=masking_policy.name,
            policy_version=masking_policy.version,
            masking_policy_json=masking_policy.model_dump_json(),
            masking_engine_version=masking_engine_version,
            approval_status=PolicyApprovalStatus.DRAFT.value,
            created_at=_now(),
            created_by=created_by,
            notes=notes,
            superseded_by_version_id=None,
        )
        self._session.add(row)
        self._session.flush()
        return self._policy_version_to_contract(row)

    def submit_policy_version_for_approval(
        self, policy_version_id: UUID | str, *, performed_by: str, comments: str = ""
    ) -> MaskingPolicyVersion:
        """DRAFT -> PENDING_APPROVAL."""

        return self._transition_policy_version(
            policy_version_id,
            target=PolicyApprovalStatus.PENDING_APPROVAL,
            performed_by=performed_by,
            comments=comments,
        )

    def approve_policy_version(
        self, policy_version_id: UUID | str, *, performed_by: str, comments: str = ""
    ) -> MaskingPolicyVersion:
        """PENDING_APPROVAL -> APPROVED.

        Also transitions any *other* currently-APPROVED
        `MaskingPolicyVersion` of the same `policy_name` to SUPERSEDED,
        and records this version's id on that superseded version --
        there is exactly one currently-usable approved version per
        `policy_name` at any time, which is what makes "both arms use
        the same approved policy version" a checkable invariant rather
        than merely a convention.
        """

        row = self._get_policy_version_row(policy_version_id)
        for other in self._session.scalars(
            select(MaskingPolicyVersionRow).where(
                MaskingPolicyVersionRow.policy_name == row.policy_name,
                MaskingPolicyVersionRow.approval_status == PolicyApprovalStatus.APPROVED.value,
                MaskingPolicyVersionRow.policy_version_id != row.policy_version_id,
            )
        ).all():
            approval_state_machine.transition(
                PolicyApprovalStatus.APPROVED, PolicyApprovalStatus.SUPERSEDED
            )
            other.approval_status = PolicyApprovalStatus.SUPERSEDED.value
            other.superseded_by_version_id = row.policy_version_id

        return self._transition_policy_version(
            policy_version_id,
            target=PolicyApprovalStatus.APPROVED,
            performed_by=performed_by,
            comments=comments,
        )

    def reject_policy_version(
        self, policy_version_id: UUID | str, *, performed_by: str, comments: str = ""
    ) -> MaskingPolicyVersion:
        """PENDING_APPROVAL -> REJECTED. Terminal -- see
        `PolicyApprovalStatus.REJECTED`'s docstring."""

        if not comments.strip():
            raise ValueError("A rejection reason (comments) is required.")
        return self._transition_policy_version(
            policy_version_id,
            target=PolicyApprovalStatus.REJECTED,
            performed_by=performed_by,
            comments=comments,
        )

    def get_policy_version(self, policy_version_id: UUID | str) -> MaskingPolicyVersion:
        return self._policy_version_to_contract(self._get_policy_version_row(policy_version_id))

    def list_policy_versions(
        self, *, policy_name: str | None = None, approval_status: PolicyApprovalStatus | None = None
    ) -> list[MaskingPolicyVersion]:
        stmt = select(MaskingPolicyVersionRow)
        if policy_name is not None:
            stmt = stmt.where(MaskingPolicyVersionRow.policy_name == policy_name)
        if approval_status is not None:
            stmt = stmt.where(MaskingPolicyVersionRow.approval_status == approval_status.value)
        stmt = stmt.order_by(MaskingPolicyVersionRow.policy_name, MaskingPolicyVersionRow.policy_version)
        return [self._policy_version_to_contract(r) for r in self._session.scalars(stmt).all()]

    def get_approved_policy_version(self, policy_name: str) -> MaskingPolicyVersion:
        """The single currently-APPROVED `MaskingPolicyVersion` for
        `policy_name` -- the one and only version any
        `ConsumerDatasetRequest` may reference right now. Raises
        `MaskingPolicyVersionNotFoundError` if none is approved yet."""

        row = self._session.scalars(
            select(MaskingPolicyVersionRow).where(
                MaskingPolicyVersionRow.policy_name == policy_name,
                MaskingPolicyVersionRow.approval_status == PolicyApprovalStatus.APPROVED.value,
            )
        ).first()
        if row is None:
            raise MaskingPolicyVersionNotFoundError(
                f"No APPROVED MaskingPolicyVersion for policy_name={policy_name!r}."
            )
        return self._policy_version_to_contract(row)

    def list_policy_approvals(self, policy_version_id: UUID | str) -> list[PolicyApproval]:
        stmt = (
            select(PolicyApprovalRow)
            .where(PolicyApprovalRow.policy_version_id == str(policy_version_id))
            .order_by(PolicyApprovalRow.performed_at)
        )
        return [self._approval_to_contract(r) for r in self._session.scalars(stmt).all()]

    # ------------------------------------------------------------------
    # Business consumers
    # ------------------------------------------------------------------

    def register_business_consumer(
        self, *, code: str, display_name: str, description: str = "", contact: str = ""
    ) -> BusinessConsumer:
        """Register a new business consumer (e.g. `LEFT_ARM`, `RIGHT_ARM`).
        Raises `DuplicateBusinessConsumerCodeError` if `code` is already
        registered -- use `get_or_create_business_consumer` for an
        idempotent seed path (what the Phase 10 demo/tests use)."""

        existing = self._session.scalars(
            select(BusinessConsumerRow).where(BusinessConsumerRow.code == code)
        ).first()
        if existing is not None:
            raise DuplicateBusinessConsumerCodeError(f"BusinessConsumer code={code!r} already registered.")

        row = BusinessConsumerRow(
            business_consumer_id=_new_id(),
            code=code,
            display_name=display_name,
            description=description,
            contact=contact,
            is_active=True,
            created_at=_now(),
        )
        self._session.add(row)
        self._session.flush()
        return self._consumer_to_contract(row)

    def get_or_create_business_consumer(
        self, *, code: str, display_name: str, description: str = "", contact: str = ""
    ) -> BusinessConsumer:
        """Idempotent seed helper: returns the existing `BusinessConsumer`
        for `code` if one exists, else registers it. Real business
        consumers are provisioned once; this exists so a demo/test script
        can be re-run safely without a duplicate-code error."""

        existing = self._session.scalars(
            select(BusinessConsumerRow).where(BusinessConsumerRow.code == code)
        ).first()
        if existing is not None:
            return self._consumer_to_contract(existing)
        return self.register_business_consumer(
            code=code, display_name=display_name, description=description, contact=contact
        )

    def get_business_consumer(self, business_consumer_id: UUID | str) -> BusinessConsumer:
        return self._consumer_to_contract(self._get_consumer_row(business_consumer_id))

    def get_business_consumer_by_code(self, code: str) -> BusinessConsumer:
        row = self._session.scalars(
            select(BusinessConsumerRow).where(BusinessConsumerRow.code == code)
        ).first()
        if row is None:
            raise BusinessConsumerNotFoundError(f"No BusinessConsumer with code={code!r}.")
        return self._consumer_to_contract(row)

    def list_business_consumers(self) -> list[BusinessConsumer]:
        stmt = select(BusinessConsumerRow).order_by(BusinessConsumerRow.code)
        return [self._consumer_to_contract(r) for r in self._session.scalars(stmt).all()]

    # ------------------------------------------------------------------
    # Consumer dataset requests
    # ------------------------------------------------------------------

    def submit_consumer_request(
        self,
        *,
        business_consumer_id: UUID | str,
        dataset_name: str,
        environment: Environment,
        policy_version_id: UUID | str,
        subset_size_hint: str,
        refresh_cadence_type: RefreshCadenceType,
        performance_requirements: str = "",
        requested_by: str,
        notes: str = "",
    ) -> ConsumerDatasetRequest:
        """Submit a business consumer's request for a dataset.

        Note what this signature does **not** accept: any masking rule,
        technique, or policy override. `policy_version_id` is the only
        masking-governance reference a caller can supply, and it must
        already be APPROVED (`PolicyVersionNotApprovedError` otherwise)
        -- see `healthcare_tdm_contracts.governance`'s module docstring
        and `test_governance_repository.py`'s
        `test_consumer_cannot_attach_custom_masking_rules`.
        """

        consumer_row = self._get_consumer_row(business_consumer_id)
        policy_row = self._get_policy_version_row(policy_version_id)
        if PolicyApprovalStatus(policy_row.approval_status) is not PolicyApprovalStatus.APPROVED:
            raise PolicyVersionNotApprovedError(
                f"MaskingPolicyVersion {policy_row.policy_version_id} "
                f"(policy_name={policy_row.policy_name!r}, policy_version={policy_row.policy_version!r}) "
                f"has approval_status={policy_row.approval_status!r}, not 'approved'. A ConsumerDatasetRequest "
                "may only reference an APPROVED MaskingPolicyVersion."
            )

        row = ConsumerDatasetRequestRow(
            consumer_request_id=_new_id(),
            business_consumer_id=consumer_row.business_consumer_id,
            business_consumer_code=consumer_row.code,
            dataset_name=dataset_name,
            environment=environment.value,
            policy_version_id=policy_row.policy_version_id,
            masking_policy_name=policy_row.policy_name,
            masking_policy_version=policy_row.policy_version,
            subset_size_hint=subset_size_hint,
            refresh_cadence_type=refresh_cadence_type.value,
            performance_requirements=performance_requirements,
            requested_by=requested_by,
            requested_at=_now(),
            status=ConsumerRequestStatus.SUBMITTED.value,
            environment_request_id=None,
            notes=notes,
        )
        self._session.add(row)
        self._session.flush()
        return self._request_to_contract(row)

    def fulfill_consumer_request(
        self, consumer_request_id: UUID | str, *, triggered_by: str
    ) -> ConsumerDatasetRequest:
        """Resolve a submitted `ConsumerDatasetRequest` into a real Phase
        7 `EnvironmentDatasetRequest` -- this is the "schedule into the
        existing refresh calendar/capacity plan, not a parallel
        implementation" mechanism ROADMAP.md Phase 10 asks for.

        If the consumer's requested `refresh_cadence_type` differs from
        the currently-resolved policy for `(environment, dataset_name)`,
        this first calls `LifecycleRepository.upsert_policy` (a real
        Phase 7 write) so the new/updated `EnvironmentDatasetRequest`
        picks up the consumer's requested cadence -- not a governance-
        layer reimplementation of cadence math (`control_plane.domain.
        lifecycle.cadence` remains the only place that logic lives).
        Then calls `LifecycleRepository.request_environment`, which is
        idempotent per `(environment, dataset_name)` -- if another
        consumer already has an active request for the same dataset in
        the same environment, this reuses that exact
        `EnvironmentDatasetRequest` row rather than creating a
        duplicate, which is itself a demonstration of shared
        infrastructure serving multiple consumers.
        """

        row = self._get_request_row(consumer_request_id)
        transition_consumer_request(ConsumerRequestStatus(row.status), ConsumerRequestStatus.FULFILLED)
        environment = Environment(row.environment)
        cadence_type = RefreshCadenceType(row.refresh_cadence_type)

        current_policy = self.lifecycle.resolve_policy(environment, row.dataset_name)
        if current_policy.cadence_type is not cadence_type:
            self.lifecycle.upsert_policy(
                environment=environment,
                dataset_name=row.dataset_name,
                cadence_type=cadence_type,
                interval_days=None,
                retention_days=current_policy.retention_days,
                grace_period_days=current_policy.grace_period_days,
                on_demand_allowed=current_policy.on_demand_allowed,
            )

        env_request = self.lifecycle.request_environment(
            environment=environment,
            dataset_name=row.dataset_name,
            requested_by=triggered_by,
            consumer=row.business_consumer_code,
        )

        row.status = ConsumerRequestStatus.FULFILLED.value
        row.environment_request_id = str(env_request.request_id)
        self._session.flush()
        return self._request_to_contract(row)

    def reject_consumer_request(
        self, consumer_request_id: UUID | str, *, performed_by: str, reason: str = ""
    ) -> ConsumerDatasetRequest:
        """Phase 18B (`docs/problems/problems_final_review.md` P3-4): SUBMITTED ->
        REJECTED. Terminal -- a platform administrator declined to
        fulfill this request; see `ConsumerRequestStatus.REJECTED`'s
        docstring. Raises `InvalidConsumerRequestTransitionError` if the
        request is not currently SUBMITTED (e.g. already FULFILLED,
        already REJECTED, or CANCELLED) -- exactly the terminal-state
        enforcement this finding was about the *absence* of."""

        row = self._get_request_row(consumer_request_id)
        transition_consumer_request(ConsumerRequestStatus(row.status), ConsumerRequestStatus.REJECTED)
        row.status = ConsumerRequestStatus.REJECTED.value
        row.resolution_notes = f"rejected by {performed_by}: {reason}" if reason else f"rejected by {performed_by}"
        self._session.flush()
        return self._request_to_contract(row)

    def cancel_consumer_request(
        self, consumer_request_id: UUID | str, *, performed_by: str, reason: str = ""
    ) -> ConsumerDatasetRequest:
        """Phase 18B (`docs/problems/problems_final_review.md` P3-4): SUBMITTED ->
        CANCELLED. Terminal -- the requesting consumer withdrew the
        request before it was fulfilled; see
        `ConsumerRequestStatus.CANCELLED`'s docstring. Same transition
        enforcement as `reject_consumer_request` (same source status,
        different terminal outcome, same table entry)."""

        row = self._get_request_row(consumer_request_id)
        transition_consumer_request(ConsumerRequestStatus(row.status), ConsumerRequestStatus.CANCELLED)
        row.status = ConsumerRequestStatus.CANCELLED.value
        row.resolution_notes = f"cancelled by {performed_by}: {reason}" if reason else f"cancelled by {performed_by}"
        self._session.flush()
        return self._request_to_contract(row)

    def get_consumer_request(self, consumer_request_id: UUID | str) -> ConsumerDatasetRequest:
        return self._request_to_contract(self._get_request_row(consumer_request_id))

    def list_consumer_requests(
        self,
        *,
        business_consumer_id: UUID | str | None = None,
        environment: Environment | None = None,
        dataset_name: str | None = None,
    ) -> list[ConsumerDatasetRequest]:
        stmt = select(ConsumerDatasetRequestRow)
        if business_consumer_id is not None:
            stmt = stmt.where(ConsumerDatasetRequestRow.business_consumer_id == str(business_consumer_id))
        if environment is not None:
            stmt = stmt.where(ConsumerDatasetRequestRow.environment == environment.value)
        if dataset_name is not None:
            stmt = stmt.where(ConsumerDatasetRequestRow.dataset_name == dataset_name)
        stmt = stmt.order_by(ConsumerDatasetRequestRow.requested_at)
        return [self._request_to_contract(r) for r in self._session.scalars(stmt).all()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition_policy_version(
        self,
        policy_version_id: UUID | str,
        *,
        target: PolicyApprovalStatus,
        performed_by: str,
        comments: str,
    ) -> MaskingPolicyVersion:
        row = self._get_policy_version_row(policy_version_id)
        current = PolicyApprovalStatus(row.approval_status)
        approval_state_machine.transition(current, target)
        row.approval_status = target.value

        approval_row = PolicyApprovalRow(
            approval_id=_new_id(),
            policy_version_id=row.policy_version_id,
            status=target.value,
            performed_by=performed_by,
            performed_at=_now(),
            comments=comments,
        )
        self._session.add(approval_row)
        self._session.flush()
        return self._policy_version_to_contract(row)

    def _get_policy_version_row(self, policy_version_id: UUID | str) -> MaskingPolicyVersionRow:
        row = self._session.get(MaskingPolicyVersionRow, str(policy_version_id))
        if row is None:
            raise MaskingPolicyVersionNotFoundError(
                f"No MaskingPolicyVersion with policy_version_id={policy_version_id!r}."
            )
        return row

    def _get_consumer_row(self, business_consumer_id: UUID | str) -> BusinessConsumerRow:
        row = self._session.get(BusinessConsumerRow, str(business_consumer_id))
        if row is None:
            raise BusinessConsumerNotFoundError(
                f"No BusinessConsumer with business_consumer_id={business_consumer_id!r}."
            )
        return row

    def _get_request_row(self, consumer_request_id: UUID | str) -> ConsumerDatasetRequestRow:
        row = self._session.get(ConsumerDatasetRequestRow, str(consumer_request_id))
        if row is None:
            raise ConsumerDatasetRequestNotFoundError(
                f"No ConsumerDatasetRequest with consumer_request_id={consumer_request_id!r}."
            )
        return row

    def _policy_version_to_contract(self, row: MaskingPolicyVersionRow) -> MaskingPolicyVersion:
        return MaskingPolicyVersion(
            policy_version_id=UUID(row.policy_version_id),
            policy_name=row.policy_name,
            policy_version=row.policy_version,
            masking_policy=MaskingPolicy.model_validate_json(row.masking_policy_json),
            masking_engine_version=row.masking_engine_version,
            approval_status=PolicyApprovalStatus(row.approval_status),
            created_at=row.created_at,
            created_by=row.created_by,
            notes=row.notes,
            superseded_by_version_id=(
                UUID(row.superseded_by_version_id) if row.superseded_by_version_id else None
            ),
        )

    def _approval_to_contract(self, row: PolicyApprovalRow) -> PolicyApproval:
        return PolicyApproval(
            approval_id=UUID(row.approval_id),
            policy_version_id=UUID(row.policy_version_id),
            status=PolicyApprovalStatus(row.status),
            performed_by=row.performed_by,
            performed_at=row.performed_at,
            comments=row.comments,
        )

    def _consumer_to_contract(self, row: BusinessConsumerRow) -> BusinessConsumer:
        return BusinessConsumer(
            business_consumer_id=UUID(row.business_consumer_id),
            code=row.code,
            display_name=row.display_name,
            description=row.description,
            contact=row.contact,
            is_active=row.is_active,
            created_at=row.created_at,
        )

    def _request_to_contract(self, row: ConsumerDatasetRequestRow) -> ConsumerDatasetRequest:
        return ConsumerDatasetRequest(
            consumer_request_id=UUID(row.consumer_request_id),
            business_consumer_id=UUID(row.business_consumer_id),
            business_consumer_code=row.business_consumer_code,
            dataset_name=row.dataset_name,
            environment=Environment(row.environment),
            policy_version_id=UUID(row.policy_version_id),
            masking_policy_name=row.masking_policy_name,
            masking_policy_version=row.masking_policy_version,
            subset_size_hint=row.subset_size_hint,
            refresh_cadence_type=RefreshCadenceType(row.refresh_cadence_type),
            performance_requirements=row.performance_requirements,
            requested_by=row.requested_by,
            requested_at=row.requested_at,
            status=ConsumerRequestStatus(row.status),
            environment_request_id=(
                UUID(row.environment_request_id) if row.environment_request_id else None
            ),
            notes=row.notes,
            resolution_notes=row.resolution_notes,
        )


__all__ = ["GovernanceRepository"]
