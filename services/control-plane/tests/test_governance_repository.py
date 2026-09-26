"""Tests for `control_plane.domain.governance.repository.GovernanceRepository`
against a real (SQLite-backed) session -- no mocking of the database
layer, mirroring `test_lifecycle_repository.py`'s convention exactly.

The headline assertions this file proves, per `ROADMAP.md` Phase 10:

- `test_left_arm_and_right_arm_resolve_to_same_approved_policy_version`
  -- both named business consumers' `ConsumerDatasetRequest`s resolve to
  the identical `policy_version_id` (and `masking_policy_name`/
  `masking_policy_version`), even though they request different
  datasets, environments, subset sizes, cadences, and performance
  requirements.
- `test_consumer_cannot_attach_custom_masking_rules` -- there is no
  field on `ConsumerDatasetRequest`, and no parameter on
  `GovernanceRepository.submit_consumer_request`, that could carry a
  custom masking rule; the only masking-policy reference is a foreign
  key that must point at an APPROVED `MaskingPolicyVersion`, enforced by
  `PolicyVersionNotApprovedError` when it does not.
- `test_right_arm_additional_qa_capacity_uses_existing_lifecycle_machinery`
  -- RIGHT_ARM's request for additional QA capacity resolves into a real
  Phase 7 `EnvironmentDatasetRequest` and shows up in Phase 8's real
  `CapacityPlanner.capacity_plan()` output, rather than any
  governance-layer-local bookkeeping.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from healthcare_tdm_contracts import (
    ConsumerDatasetRequest,
    ConsumerRequestStatus,
    Environment,
    PolicyApprovalStatus,
    RefreshCadenceType,
)
from sqlalchemy.orm import Session

from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory
from control_plane.domain.capacity import CapacityPlanner
from control_plane.domain.governance import (
    DuplicateBusinessConsumerCodeError,
    GovernanceRepository,
    InvalidConsumerRequestTransitionError,
    InvalidPolicyApprovalTransitionError,
    PolicyVersionNotApprovedError,
)

from conftest import make_certified_report, make_sample_masking_policy


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_sqlite_engine(str(tmp_path / "governance.db"))
    factory = build_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def repo(session: Session) -> GovernanceRepository:
    return GovernanceRepository(session)


# ----------------------------------------------------------------------
# Policy version drafting + approval workflow
# ----------------------------------------------------------------------


def test_draft_submit_approve_workflow_records_approvals(repo: GovernanceRepository) -> None:
    policy = make_sample_masking_policy(version=1)
    version = repo.draft_policy_version(
        masking_policy=policy,
        masking_engine_version="1.0.0",
        created_by="governance-admin@example.org",
        notes="Phase 10 governed default policy.",
    )
    assert version.approval_status is PolicyApprovalStatus.DRAFT
    assert version.policy_name == "phase3-default"
    assert version.policy_version == 1
    assert version.masking_policy.rules == policy.rules

    submitted = repo.submit_policy_version_for_approval(
        version.policy_version_id, performed_by="governance-admin@example.org"
    )
    assert submitted.approval_status is PolicyApprovalStatus.PENDING_APPROVAL

    approved = repo.approve_policy_version(
        version.policy_version_id,
        performed_by="compliance-steward@example.org",
        comments="Reviewed against DATA_GOVERNANCE.md B.2; approved.",
    )
    assert approved.approval_status is PolicyApprovalStatus.APPROVED

    approvals = repo.list_policy_approvals(version.policy_version_id)
    assert [a.status for a in approvals] == [
        PolicyApprovalStatus.PENDING_APPROVAL,
        PolicyApprovalStatus.APPROVED,
    ]
    assert approvals[-1].performed_by == "compliance-steward@example.org"

    assert repo.get_approved_policy_version("phase3-default").policy_version_id == version.policy_version_id


def test_cannot_approve_a_policy_version_still_in_draft(repo: GovernanceRepository) -> None:
    version = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    with pytest.raises(InvalidPolicyApprovalTransitionError):
        repo.approve_policy_version(version.policy_version_id, performed_by="reviewer@example.org")


def test_cannot_approve_twice(repo: GovernanceRepository) -> None:
    version = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    repo.submit_policy_version_for_approval(version.policy_version_id, performed_by="admin@example.org")
    repo.approve_policy_version(version.policy_version_id, performed_by="reviewer@example.org")
    with pytest.raises(InvalidPolicyApprovalTransitionError):
        repo.approve_policy_version(version.policy_version_id, performed_by="reviewer@example.org")


def test_reject_requires_a_reason(repo: GovernanceRepository) -> None:
    version = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    repo.submit_policy_version_for_approval(version.policy_version_id, performed_by="admin@example.org")
    with pytest.raises(ValueError):
        repo.reject_policy_version(version.policy_version_id, performed_by="reviewer@example.org", comments="")


def test_approving_a_new_version_supersedes_the_previous_approved_version(
    repo: GovernanceRepository,
) -> None:
    v1 = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(version=1),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    repo.submit_policy_version_for_approval(v1.policy_version_id, performed_by="admin@example.org")
    repo.approve_policy_version(v1.policy_version_id, performed_by="reviewer@example.org")

    v2 = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(version=2),
        masking_engine_version="1.1.0",
        created_by="admin@example.org",
        notes="Tightened SSN masking technique.",
    )
    repo.submit_policy_version_for_approval(v2.policy_version_id, performed_by="admin@example.org")
    repo.approve_policy_version(v2.policy_version_id, performed_by="reviewer@example.org")

    v1_after = repo.get_policy_version(v1.policy_version_id)
    assert v1_after.approval_status is PolicyApprovalStatus.SUPERSEDED
    assert v1_after.superseded_by_version_id == v2.policy_version_id

    assert repo.get_approved_policy_version("phase3-default").policy_version_id == v2.policy_version_id


# ----------------------------------------------------------------------
# Business consumers
# ----------------------------------------------------------------------


def test_register_left_arm_and_right_arm(repo: GovernanceRepository) -> None:
    left = repo.register_business_consumer(
        code="LEFT_ARM", display_name="Left Arm Business Unit", description="Claims operations arm."
    )
    right = repo.register_business_consumer(
        code="RIGHT_ARM", display_name="Right Arm Business Unit", description="Clinical analytics arm."
    )
    assert {c.code for c in repo.list_business_consumers()} == {"LEFT_ARM", "RIGHT_ARM"}
    assert left.business_consumer_id != right.business_consumer_id


def test_duplicate_business_consumer_code_rejected(repo: GovernanceRepository) -> None:
    repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    with pytest.raises(DuplicateBusinessConsumerCodeError):
        repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm Again")


def test_get_or_create_business_consumer_is_idempotent(repo: GovernanceRepository) -> None:
    first = repo.get_or_create_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    second = repo.get_or_create_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    assert first.business_consumer_id == second.business_consumer_id


# ----------------------------------------------------------------------
# Consumer dataset requests: governance enforcement
# ----------------------------------------------------------------------


def _approved_policy_version(repo: GovernanceRepository, *, version: int = 1):
    v = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(version=version),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    repo.submit_policy_version_for_approval(v.policy_version_id, performed_by="admin@example.org")
    return repo.approve_policy_version(v.policy_version_id, performed_by="reviewer@example.org")


def test_consumer_request_rejected_if_policy_version_not_approved(repo: GovernanceRepository) -> None:
    consumer = repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    draft_version = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    with pytest.raises(PolicyVersionNotApprovedError):
        repo.submit_consumer_request(
            business_consumer_id=consumer.business_consumer_id,
            dataset_name="left-arm-member-claims-subset",
            environment=Environment.DEV,
            policy_version_id=draft_version.policy_version_id,
            subset_size_hint="1% of members",
            refresh_cadence_type=RefreshCadenceType.WEEKLY,
            requested_by="left-arm-lead@example.org",
        )

    # Still not approved even after being submitted for approval (PENDING_APPROVAL).
    repo.submit_policy_version_for_approval(draft_version.policy_version_id, performed_by="admin@example.org")
    with pytest.raises(PolicyVersionNotApprovedError):
        repo.submit_consumer_request(
            business_consumer_id=consumer.business_consumer_id,
            dataset_name="left-arm-member-claims-subset",
            environment=Environment.DEV,
            policy_version_id=draft_version.policy_version_id,
            subset_size_hint="1% of members",
            refresh_cadence_type=RefreshCadenceType.WEEKLY,
            requested_by="left-arm-lead@example.org",
        )


def test_consumer_cannot_attach_custom_masking_rules(repo: GovernanceRepository) -> None:
    """Adversarial/structural test, in the spirit of Phase 6's
    certification bypass tests: prove there is no code path -- neither a
    model field nor a repository-method parameter -- through which a
    consumer could attach its own masking rule/technique/policy
    override to a request, and that the one real path (an unapproved
    `policy_version_id`) is actively rejected, not silently accepted."""

    forbidden_terms = {
        "masking_rule",
        "masking_rules",
        "rule",
        "rules",
        "technique",
        "masking_policy",
        "custom_policy",
        "policy_override",
        "override_policy",
    }

    model_fields = set(ConsumerDatasetRequest.model_fields.keys())
    assert model_fields.isdisjoint(forbidden_terms), (
        f"ConsumerDatasetRequest must not expose a masking-rule field; found: "
        f"{model_fields & forbidden_terms}"
    )

    signature_params = set(inspect.signature(repo.submit_consumer_request).parameters.keys())
    assert signature_params.isdisjoint(forbidden_terms), (
        f"GovernanceRepository.submit_consumer_request must not accept a masking-rule "
        f"parameter; found: {signature_params & forbidden_terms}"
    )

    # The only masking-policy reference the model/method DOES accept is a
    # foreign key, and it must be an APPROVED one -- demonstrated for real:
    consumer = repo.register_business_consumer(code="RIGHT_ARM", display_name="Right Arm")
    unapproved = repo.draft_policy_version(
        masking_policy=make_sample_masking_policy(),
        masking_engine_version="1.0.0",
        created_by="admin@example.org",
    )
    with pytest.raises(PolicyVersionNotApprovedError):
        repo.submit_consumer_request(
            business_consumer_id=consumer.business_consumer_id,
            dataset_name="right-arm-member-claims-subset",
            environment=Environment.DEV,
            policy_version_id=unapproved.policy_version_id,
            subset_size_hint="5% of members",
            refresh_cadence_type=RefreshCadenceType.WEEKLY,
            requested_by="right-arm-lead@example.org",
        )


def test_left_arm_and_right_arm_resolve_to_same_approved_policy_version(
    repo: GovernanceRepository,
) -> None:
    approved = _approved_policy_version(repo)
    left = repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    right = repo.register_business_consumer(code="RIGHT_ARM", display_name="Right Arm")

    left_request = repo.submit_consumer_request(
        business_consumer_id=left.business_consumer_id,
        dataset_name="left-arm-member-claims-subset",
        environment=Environment.DEV,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="1% of members, >=25 per rare condition",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        performance_requirements="standard dev-loop latency",
        requested_by="left-arm-lead@example.org",
    )
    right_request = repo.submit_consumer_request(
        business_consumer_id=right.business_consumer_id,
        dataset_name="right-arm-member-claims-subset",
        environment=Environment.QA,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="8% of members, high-volume regression set",
        refresh_cadence_type=RefreshCadenceType.BIWEEKLY,
        performance_requirements="sub-200ms p95 query latency under load",
        requested_by="right-arm-lead@example.org",
    )

    # Different datasets, environments, subset sizes, cadences, and
    # performance requirements -- but the SAME governed policy version.
    assert left_request.policy_version_id == right_request.policy_version_id == approved.policy_version_id
    assert left_request.masking_policy_name == right_request.masking_policy_name == "phase3-default"
    assert left_request.masking_policy_version == right_request.masking_policy_version == 1
    assert left_request.dataset_name != right_request.dataset_name
    assert left_request.environment != right_request.environment
    assert left_request.refresh_cadence_type != right_request.refresh_cadence_type
    assert left_request.subset_size_hint != right_request.subset_size_hint


# ----------------------------------------------------------------------
# Fulfillment: real Phase 7/8 integration
# ----------------------------------------------------------------------


def test_fulfill_consumer_request_creates_real_environment_dataset_request(
    repo: GovernanceRepository,
) -> None:
    approved = _approved_policy_version(repo)
    consumer = repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")

    report = make_certified_report(dataset_name="left-arm-member-claims-subset")
    repo.lifecycle.register_dataset_version(
        dataset_name="left-arm-member-claims-subset",
        certification_report=report,
        storage_uri="data/tmp/left-arm-run",
        size_bytes=10_000,
        row_counts={"member": 10, "claim": 40},
        created_by="left-arm-lead@example.org",
    )

    submitted = repo.submit_consumer_request(
        business_consumer_id=consumer.business_consumer_id,
        dataset_name="left-arm-member-claims-subset",
        environment=Environment.DEV,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="1% of members",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="left-arm-lead@example.org",
    )
    assert submitted.status is ConsumerRequestStatus.SUBMITTED
    assert submitted.environment_request_id is None

    fulfilled = repo.fulfill_consumer_request(submitted.consumer_request_id, triggered_by="governance-service")
    assert fulfilled.status is ConsumerRequestStatus.FULFILLED
    assert fulfilled.environment_request_id is not None

    env_request = repo.lifecycle.get_request(fulfilled.environment_request_id)
    assert env_request.dataset_name == "left-arm-member-claims-subset"
    assert env_request.environment is Environment.DEV
    assert env_request.consumer == "LEFT_ARM"


# ----------------------------------------------------------------------
# Phase 18B (`problems_final_review.md` P3-4): REJECTED/CANCELLED
# terminal states
# ----------------------------------------------------------------------


def test_reject_consumer_request_is_a_real_terminal_state(repo: GovernanceRepository) -> None:
    approved = _approved_policy_version(repo)
    consumer = repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")

    submitted = repo.submit_consumer_request(
        business_consumer_id=consumer.business_consumer_id,
        dataset_name="left-arm-member-claims-subset",
        environment=Environment.DEV,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="1% of members",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="left-arm-lead@example.org",
    )

    rejected = repo.reject_consumer_request(
        submitted.consumer_request_id,
        performed_by="platform-admin@example.org",
        reason="dataset not appropriate for this consumer",
    )
    assert rejected.status is ConsumerRequestStatus.REJECTED
    assert rejected.environment_request_id is None
    assert "platform-admin@example.org" in rejected.resolution_notes
    assert "dataset not appropriate for this consumer" in rejected.resolution_notes

    # Terminal: a second resolution attempt of any kind is rejected, not
    # silently allowed to flip the status again.
    with pytest.raises(InvalidConsumerRequestTransitionError):
        repo.reject_consumer_request(submitted.consumer_request_id, performed_by="someone-else")
    with pytest.raises(InvalidConsumerRequestTransitionError):
        repo.cancel_consumer_request(submitted.consumer_request_id, performed_by="someone-else")
    with pytest.raises(InvalidConsumerRequestTransitionError):
        repo.fulfill_consumer_request(submitted.consumer_request_id, triggered_by="scheduler")


def test_cancel_consumer_request_is_a_real_terminal_state(repo: GovernanceRepository) -> None:
    approved = _approved_policy_version(repo)
    consumer = repo.register_business_consumer(code="RIGHT_ARM", display_name="Right Arm")

    submitted = repo.submit_consumer_request(
        business_consumer_id=consumer.business_consumer_id,
        dataset_name="right-arm-member-claims-subset",
        environment=Environment.QA,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="1% of members",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="right-arm-lead@example.org",
    )

    cancelled = repo.cancel_consumer_request(
        submitted.consumer_request_id,
        performed_by="right-arm-lead@example.org",
        reason="business need went away",
    )
    assert cancelled.status is ConsumerRequestStatus.CANCELLED
    assert "business need went away" in cancelled.resolution_notes

    with pytest.raises(InvalidConsumerRequestTransitionError):
        repo.fulfill_consumer_request(submitted.consumer_request_id, triggered_by="scheduler")


def test_a_fulfilled_consumer_request_cannot_later_be_rejected_or_cancelled(
    repo: GovernanceRepository,
) -> None:
    """The other direction of terminal-state enforcement: once
    FULFILLED, a request must not be able to retroactively become
    REJECTED/CANCELLED -- a real environment provisioning, once done, is
    not silently undone by a status flip."""

    approved = _approved_policy_version(repo)
    consumer = repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    repo.lifecycle.register_dataset_version(
        dataset_name="left-arm-member-claims-subset",
        certification_report=make_certified_report(dataset_name="left-arm-member-claims-subset"),
        storage_uri="data/tmp/left-arm-run",
        size_bytes=10_000,
        row_counts={"member": 10, "claim": 40},
        created_by="left-arm-lead@example.org",
    )
    submitted = repo.submit_consumer_request(
        business_consumer_id=consumer.business_consumer_id,
        dataset_name="left-arm-member-claims-subset",
        environment=Environment.DEV,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="1% of members",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="left-arm-lead@example.org",
    )
    fulfilled = repo.fulfill_consumer_request(submitted.consumer_request_id, triggered_by="governance-service")
    assert fulfilled.status is ConsumerRequestStatus.FULFILLED

    with pytest.raises(InvalidConsumerRequestTransitionError):
        repo.reject_consumer_request(submitted.consumer_request_id, performed_by="platform-admin@example.org")
    with pytest.raises(InvalidConsumerRequestTransitionError):
        repo.cancel_consumer_request(submitted.consumer_request_id, performed_by="left-arm-lead@example.org")


def test_right_arm_additional_qa_capacity_uses_existing_lifecycle_machinery(
    repo: GovernanceRepository,
) -> None:
    approved = _approved_policy_version(repo)
    left = repo.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    right = repo.register_business_consumer(code="RIGHT_ARM", display_name="Right Arm")

    for name in ("left-arm-member-claims-subset", "right-arm-member-claims-subset"):
        repo.lifecycle.register_dataset_version(
            dataset_name=name,
            certification_report=make_certified_report(dataset_name=name),
            storage_uri=f"data/tmp/{name}-run",
            size_bytes=10_000,
            row_counts={"member": 10, "claim": 40},
            created_by="platform@example.org",
        )

    left_dev = repo.submit_consumer_request(
        business_consumer_id=left.business_consumer_id,
        dataset_name="left-arm-member-claims-subset",
        environment=Environment.DEV,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="1% of members",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="left-arm-lead@example.org",
    )
    repo.fulfill_consumer_request(left_dev.consumer_request_id, triggered_by="governance-service")

    right_dev = repo.submit_consumer_request(
        business_consumer_id=right.business_consumer_id,
        dataset_name="right-arm-member-claims-subset",
        environment=Environment.DEV,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="4% of members",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="right-arm-lead@example.org",
    )
    repo.fulfill_consumer_request(right_dev.consumer_request_id, triggered_by="governance-service")

    planner = CapacityPlanner(repo.lifecycle)
    plan_before = planner.capacity_plan()
    assert plan_before.environment_count == 2
    assert not any(
        d.environment is Environment.QA and d.dataset_name == "right-arm-member-claims-subset"
        for d in plan_before.environment_demands
    )

    # RIGHT_ARM requests ADDITIONAL QA capacity, with its own (different)
    # refresh cadence -- this must schedule into the EXISTING Phase 7/8
    # machinery, not create a parallel system.
    right_qa = repo.submit_consumer_request(
        business_consumer_id=right.business_consumer_id,
        dataset_name="right-arm-member-claims-subset",
        environment=Environment.QA,
        policy_version_id=approved.policy_version_id,
        subset_size_hint="10% of members, high-volume regression set",
        refresh_cadence_type=RefreshCadenceType.BIWEEKLY,
        performance_requirements="parallel regression suite, sub-200ms p95",
        requested_by="right-arm-lead@example.org",
        notes="Additional QA capacity for the Q3 regression push.",
    )
    fulfilled_qa = repo.fulfill_consumer_request(right_qa.consumer_request_id, triggered_by="governance-service")
    assert fulfilled_qa.environment_request_id is not None

    # Real Phase 7 state: a new EnvironmentDatasetRequest now exists for QA.
    qa_env_request = repo.lifecycle.get_request(fulfilled_qa.environment_request_id)
    assert qa_env_request.environment is Environment.QA
    assert qa_env_request.consumer == "RIGHT_ARM"

    # Real Phase 7 policy: QA's cadence for this dataset now reflects
    # RIGHT_ARM's request, computed by control_plane.domain.lifecycle.cadence
    # -- not reimplemented here.
    qa_policy = repo.lifecycle.resolve_policy(Environment.QA, "right-arm-member-claims-subset")
    assert qa_policy.cadence_type is RefreshCadenceType.BIWEEKLY

    # Real Phase 8 state: CapacityPlanner (unmodified from Phase 8) now
    # reports the additional demand, with no governance-layer-local
    # capacity bookkeeping of its own.
    plan_after = planner.capacity_plan()
    assert plan_after.environment_count == plan_before.environment_count + 1
    right_qa_demand = next(
        d
        for d in plan_after.environment_demands
        if d.environment is Environment.QA and d.dataset_name == "right-arm-member-claims-subset"
    )
    assert right_qa_demand.refresh_cadence_type is RefreshCadenceType.BIWEEKLY
