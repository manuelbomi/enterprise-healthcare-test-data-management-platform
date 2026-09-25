"""Snapshot registry contracts.

A SnapshotRecord is the metadata plane's system-of-record entry for a
published, versioned test-data snapshot. See DATA_GOVERNANCE.md (B.5,
retention/refresh) and ARCHITECTURE.md section 3.4 (disaster recovery) for
why snapshots are immutable once published and always traceable back to
the job run and policy version that produced them.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.storage import ObjectRef


class SnapshotStatus(str, Enum):
    """Lifecycle of a snapshot after its producing job succeeds.

    PENDING_CERTIFICATION -> CERTIFIED -> PUBLISHED. A snapshot that fails
    certification is REJECTED and never becomes visible to consumers (see
    docs/runbooks/snapshot-refresh-failure.md). EXPIRED is reached via the
    retention/refresh policy, not deletion of the record.
    """

    PENDING_CERTIFICATION = "pending_certification"
    CERTIFIED = "certified"
    PUBLISHED = "published"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SnapshotRecord(BaseModel):
    """A single versioned test-data snapshot."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    dataset: str = Field(..., description="Logical dataset name this snapshot is a version of.")
    version: int = Field(..., ge=1)
    target_environment: str
    status: SnapshotStatus
    storage_ref: ObjectRef
    source_job_id: UUID = Field(..., description="Job run (see jobs.JobResult) that produced this snapshot.")
    policy_version: int = Field(..., description="Masking policy version applied, for reproducibility.")
    row_counts: dict[str, int] = Field(
        default_factory=dict, description="Row counts per table/entity in the snapshot."
    )
    refresh_cadence: str = Field(
        ..., description="Human-readable cadence, e.g. 'weekly', 'on-demand'."
    )
    published_at: datetime | None = None
    expires_at: datetime | None = None
