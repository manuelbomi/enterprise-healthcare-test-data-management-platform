"""healthcare_tdm_contracts — shared typed contracts between planes.

This package intentionally contains only data shapes (Pydantic models,
enums, and Protocol interfaces) and zero business logic. See the package
README for the rules that keep it that way.

Phase 0 note: these models define the *vocabulary* the rest of the
platform will use starting in Phase 1. They are not yet wired to a real
database, API, or storage backend.
"""

from healthcare_tdm_contracts.audit import AuditEvent, AuditEventType
from healthcare_tdm_contracts.catalog import CatalogEntry, RetentionClassification
from healthcare_tdm_contracts.classification import (
    TIER_BY_CATEGORY,
    ClassificationMethod,
    ClassificationTier,
    ColumnClassification,
    SensitivityCategory,
)
from healthcare_tdm_contracts.jobs import JobRequest, JobResult, JobStatus, JobType
from healthcare_tdm_contracts.masking import (
    MaskingFieldType,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    MaskingTechnique,
)
from healthcare_tdm_contracts.snapshots import SnapshotRecord, SnapshotStatus
from healthcare_tdm_contracts.source_systems import (
    ScaleProfileName,
    SourceDatasetDescriptor,
    SourceSystemType,
)
from healthcare_tdm_contracts.storage import ObjectRef, StorageBackend

__all__ = [
    "TIER_BY_CATEGORY",
    "AuditEvent",
    "AuditEventType",
    "CatalogEntry",
    "ClassificationMethod",
    "ClassificationTier",
    "ColumnClassification",
    "JobRequest",
    "JobResult",
    "JobStatus",
    "JobType",
    "MaskingFieldType",
    "MaskingPolicy",
    "MaskingRule",
    "MaskingStrategy",
    "MaskingTechnique",
    "ObjectRef",
    "RetentionClassification",
    "ScaleProfileName",
    "SensitivityCategory",
    "SnapshotRecord",
    "SnapshotStatus",
    "SourceDatasetDescriptor",
    "SourceSystemType",
    "StorageBackend",
]

__version__ = "0.1.0"
