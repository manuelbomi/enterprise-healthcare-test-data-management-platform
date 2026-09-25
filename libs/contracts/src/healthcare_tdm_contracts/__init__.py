"""healthcare_tdm_contracts — shared typed contracts between planes.

This package intentionally contains only data shapes (Pydantic models,
enums, and Protocol interfaces) and zero business logic. See the package
README for the rules that keep it that way.

Phase 0 note: these models define the *vocabulary* the rest of the
platform will use starting in Phase 1. They are not yet wired to a real
database, API, or storage backend.
"""

from healthcare_tdm_contracts.audit import AuditEvent, AuditEventType
from healthcare_tdm_contracts.classification import (
    ClassificationTier,
    ColumnClassification,
)
from healthcare_tdm_contracts.jobs import JobRequest, JobResult, JobStatus, JobType
from healthcare_tdm_contracts.masking import MaskingPolicy, MaskingRule, MaskingStrategy
from healthcare_tdm_contracts.snapshots import SnapshotRecord, SnapshotStatus
from healthcare_tdm_contracts.storage import ObjectRef, StorageBackend

__all__ = [
    "AuditEvent",
    "AuditEventType",
    "ClassificationTier",
    "ColumnClassification",
    "JobRequest",
    "JobResult",
    "JobStatus",
    "JobType",
    "MaskingPolicy",
    "MaskingRule",
    "MaskingStrategy",
    "ObjectRef",
    "SnapshotRecord",
    "SnapshotStatus",
    "StorageBackend",
]

__version__ = "0.1.0"
