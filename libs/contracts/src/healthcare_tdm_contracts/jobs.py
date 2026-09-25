"""Job submission contracts.

Defines the shape the control plane uses to submit work to the data plane,
and the shape the data plane reports back. See ARCHITECTURE.md section 4
("Interfaces between planes") and docs/tutorial/01-planes-and-data-flow.md
for how these are used in a real request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobType(str, Enum):
    """The kinds of work the data plane can be asked to perform."""

    DISCOVERY = "discovery"
    SUBSETTING = "subsetting"
    MASKING = "masking"
    SYNTHETIC_GENERATION = "synthetic_generation"
    CERTIFICATION = "certification"


class JobStatus(str, Enum):
    """Lifecycle states of a submitted job.

    QUEUED -> RUNNING -> (SUCCEEDED | FAILED). CANCELLED is a distinct
    terminal state reached only via explicit cancellation, never inferred.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRequest(BaseModel):
    """A unit of work submitted by the control plane to the data plane.

    A single user-facing request (e.g., "give me a snapshot") typically
    becomes a small DAG of JobRequests (subsetting -> masking ->
    certification), not one JobRequest — the control plane's orchestrator
    (Phase 14) owns sequencing that DAG. Each JobRequest is independently
    idempotent via `idempotency_key`.
    """

    job_id: UUID = Field(default_factory=uuid4)
    job_type: JobType
    source_system: str = Field(..., description="Logical name of the source system to operate on.")
    dataset: str = Field(..., description="Table or dataset name within the source system.")
    policy_version: int | None = Field(
        default=None,
        description="Masking policy version to apply, required for MASKING jobs.",
    )
    sizing_rule: str | None = Field(
        default=None,
        description="Subsetting sizing rule reference, required for SUBSETTING jobs.",
    )
    target_environment: str = Field(
        ..., description="Lower environment this job's output is ultimately destined for."
    )
    idempotency_key: str = Field(
        ..., description="Caller-supplied key; resubmitting the same key must not duplicate work."
    )
    requested_by: str = Field(..., description="Identity of the requesting user or system.")
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobResult(BaseModel):
    """The outcome of a JobRequest, as reported back to the control plane."""

    job_id: UUID
    status: JobStatus
    output_ref: str | None = Field(
        default=None, description="Storage reference to the job's output, if it produced one."
    )
    rows_processed: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
