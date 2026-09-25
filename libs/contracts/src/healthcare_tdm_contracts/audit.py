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
