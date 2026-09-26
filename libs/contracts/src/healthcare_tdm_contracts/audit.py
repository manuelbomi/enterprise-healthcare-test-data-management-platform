"""Audit event contracts.

Every plane emits AuditEvent records to the security/governance plane for
any security- or governance-relevant action. See SECURITY.md and
THREAT_MODEL.md (Security/governance plane: Repudiation) for why these are
treated as immutable evidence rather than ordinary application logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    """Kinds of events that must produce an immutable audit record.

    This enum is deliberately explicit and closed (rather than a free-text
    "event name" field) so that every audit-worthy action in the system is
    a conscious, reviewable addition to this contract.
    """

    ACCESS_REQUESTED = "access_requested"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    CLASSIFICATION_CONFIRMED = "classification_confirmed"
    CLASSIFICATION_CHANGED = "classification_changed"
    POLICY_APPROVED = "policy_approved"
    POLICY_REJECTED = "policy_rejected"
    POLICY_CHANGED = "policy_changed"
    JOB_REQUESTED = "job_requested"
    JOB_PUBLISHED = "job_published"
    CERTIFICATION_PASSED = "certification_passed"
    CERTIFICATION_FAILED = "certification_failed"
    SNAPSHOT_ACCESSED = "snapshot_accessed"
    # Phase 11 additions -- wired to real control-plane lifecycle/
    # governance mutations (see `control_plane.platform.audit`). Added
    # rather than overloading an existing value, because none of the
    # values above (written for the certification/classification
    # domain in Phase 0) describe "a dataset version was revoked" or
    # "an environment's dataset request was rolled back" precisely
    # enough for an auditor to trust the event type alone.
    DATASET_VERSION_REGISTERED = "dataset_version_registered"
    DATASET_VERSION_REVOKED = "dataset_version_revoked"
    DATASET_VERSION_ROLLED_BACK = "dataset_version_rolled_back"
    ENVIRONMENT_REQUEST_CREATED = "environment_request_created"
    REFRESH_EXECUTED = "refresh_executed"
    CONSUMER_REQUEST_SUBMITTED = "consumer_request_submitted"
    CONSUMER_REQUEST_FULFILLED = "consumer_request_fulfilled"
    # Phase 18B (`docs/problems/problems_final_review.md` P3-4): the two new terminal
    # outcomes for a `ConsumerDatasetRequest` besides FULFILLED --
    # REJECTED (a platform administrator declined it) and CANCELLED (the
    # requesting consumer withdrew it) -- each need their own auditable
    # record, the same reasoning `CONSUMER_REQUEST_FULFILLED` already
    # established for the third possible outcome.
    CONSUMER_REQUEST_REJECTED = "consumer_request_rejected"
    CONSUMER_REQUEST_CANCELLED = "consumer_request_cancelled"
    # Phase 13 additions -- `docs/problems/problems_phase_13.md` found that
    # `ACCESS_GRANTED`/`ACCESS_REQUESTED` above (defined since Phase 0)
    # had never actually been wired to any real mutation, and that
    # nothing recorded "who accessed a provisioned dataset version"
    # specifically, as opposed to "who requested/fulfilled a
    # provisioning request" (`CONSUMER_REQUEST_SUBMITTED`/
    # `CONSUMER_REQUEST_FULFILLED` above, which are about the request
    # workflow, not actual use of the resulting data). Rather than
    # overload `ACCESS_GRANTED` (whose name suggests a generic
    # permission grant, not specifically "this dataset version was
    # used"), this phase adds a precise, dataset-version-scoped event --
    # see `control_plane.api.v1.lifecycle.record_dataset_version_access`.
    DATASET_VERSION_ACCESSED = "dataset_version_accessed"
    # Generating an Audit Evidence Package (Phase 13) is itself a
    # governance-relevant action worth its own auditable record -- see
    # `control_plane.domain.evidence.EvidenceRepository`.
    EVIDENCE_PACKAGE_GENERATED = "evidence_package_generated"


class AuditEvent(BaseModel):
    """An immutable record of a security- or governance-relevant action.

    Producers append; nothing in the application layer is expected to
    expose an update or delete path for these records (see SECURITY.md,
    "Immutable audit evidence"). The actual append-only storage mechanism
    is a security/governance plane implementation detail (Phase 3).
    """

    event_id: UUID = Field(default_factory=uuid4)
    event_type: AuditEventType
    actor: str = Field(..., description="Identity of the user or system that performed the action.")
    subject: str = Field(
        ..., description="What the action was performed on, e.g. a dataset name or job ID."
    )
    outcome: str = Field(..., description="Short outcome description, e.g. 'allowed', 'denied'.")
    detail: dict[str, str] = Field(
        default_factory=dict, description="Additional structured context for this event."
    )
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
