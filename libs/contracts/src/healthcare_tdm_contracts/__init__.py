"""healthcare_tdm_contracts — shared typed contracts between planes.

This package intentionally contains only data shapes (Pydantic models,
enums, and Protocol interfaces) and zero business logic. See the package
README for the rules that keep it that way.

Phase 0 note: these models define the *vocabulary* the rest of the
platform will use starting in Phase 1. They are not yet wired to a real
database, API, or storage backend.
"""

from healthcare_tdm_contracts.audit import AuditEvent, AuditEventType
from healthcare_tdm_contracts.capacity import (
    DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS,
    DEFAULT_PRODUCTION_BASELINE_BYTES,
    TERABYTE_BYTES,
    CapacityPlan,
    CompressionMeasurement,
    DatasetVersionFootprint,
    EnvironmentCapacityDemand,
    EnvironmentCapacityRequirement,
    FootprintMeasurementReport,
    IllustrativeCapacityPlan,
    IllustrativeCapacityScenario,
    IncrementalRefreshEstimate,
    PartitionSummary,
    SavedIllustrativeCapacityPlan,
    VacuumCandidate,
)
from healthcare_tdm_contracts.catalog import CatalogEntry, RetentionClassification
from healthcare_tdm_contracts.certification import (
    CERTIFICATION_STATUS_TRANSITIONS,
    CertificationGateResult,
    CertificationGateType,
    CertificationReport,
    CertificationStatus,
    CertificationStatusEvent,
)
from healthcare_tdm_contracts.classification import (
    TIER_BY_CATEGORY,
    ClassificationMethod,
    ClassificationTier,
    ColumnClassification,
    SensitivityCategory,
)
from healthcare_tdm_contracts.evidence import COMPLIANCE_DISCLAIMER, AuditEvidencePackage
from healthcare_tdm_contracts.governance import (
    CONSUMER_REQUEST_STATUS_TRANSITIONS,
    POLICY_APPROVAL_STATUS_TRANSITIONS,
    BusinessConsumer,
    ConsumerDatasetRequest,
    ConsumerRequestStatus,
    MaskingPolicyVersion,
    PolicyApproval,
    PolicyApprovalStatus,
)
from healthcare_tdm_contracts.jobs import JobRequest, JobResult, JobStatus, JobType
from healthcare_tdm_contracts.lifecycle import (
    DATASET_VERSION_STATUS_TRANSITIONS,
    DEFAULT_CADENCE_BY_ENVIRONMENT,
    DEFAULT_INTERVAL_DAYS_BY_CADENCE,
    DatasetVersion,
    DatasetVersionStatus,
    Environment,
    EnvironmentDatasetRequest,
    EnvironmentRequestStatus,
    RefreshCadenceType,
    RefreshPolicy,
    RefreshRunRecord,
    RefreshTrigger,
    RollbackRecord,
)
from healthcare_tdm_contracts.masking import (
    MaskingFieldType,
    MaskingPolicy,
    MaskingRule,
    MaskingRunSummary,
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
from healthcare_tdm_contracts.subsetting import (
    IntegrityStatus,
    RelationshipEdge,
    SubsetManifest,
    SubsetSelectionCriteria,
    SubsettingStrategy,
)
from healthcare_tdm_contracts.synthetic import (
    DataProvenance,
    ScenarioGenerationRecord,
    ScenarioType,
    SyntheticGenerationManifest,
)

__all__ = [
    "TIER_BY_CATEGORY",
    "CERTIFICATION_STATUS_TRANSITIONS",
    "CONSUMER_REQUEST_STATUS_TRANSITIONS",
    "COMPLIANCE_DISCLAIMER",
    "DATASET_VERSION_STATUS_TRANSITIONS",
    "DEFAULT_CADENCE_BY_ENVIRONMENT",
    "DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS",
    "DEFAULT_INTERVAL_DAYS_BY_CADENCE",
    "DEFAULT_PRODUCTION_BASELINE_BYTES",
    "POLICY_APPROVAL_STATUS_TRANSITIONS",
    "TERABYTE_BYTES",
    "AuditEvent",
    "AuditEventType",
    "AuditEvidencePackage",
    "BusinessConsumer",
    "CapacityPlan",
    "CatalogEntry",
    "CertificationGateResult",
    "CertificationGateType",
    "CertificationReport",
    "CertificationStatus",
    "CertificationStatusEvent",
    "ClassificationMethod",
    "ClassificationTier",
    "ColumnClassification",
    "CompressionMeasurement",
    "ConsumerDatasetRequest",
    "ConsumerRequestStatus",
    "DataProvenance",
    "DatasetVersion",
    "DatasetVersionFootprint",
    "DatasetVersionStatus",
    "Environment",
    "EnvironmentCapacityDemand",
    "EnvironmentCapacityRequirement",
    "EnvironmentDatasetRequest",
    "EnvironmentRequestStatus",
    "FootprintMeasurementReport",
    "IllustrativeCapacityPlan",
    "IllustrativeCapacityScenario",
    "IncrementalRefreshEstimate",
    "IntegrityStatus",
    "JobRequest",
    "JobResult",
    "JobStatus",
    "JobType",
    "MaskingFieldType",
    "MaskingPolicy",
    "MaskingPolicyVersion",
    "MaskingRule",
    "MaskingRunSummary",
    "MaskingStrategy",
    "MaskingTechnique",
    "ObjectRef",
    "PartitionSummary",
    "PolicyApproval",
    "PolicyApprovalStatus",
    "RefreshCadenceType",
    "RefreshPolicy",
    "RefreshRunRecord",
    "RefreshTrigger",
    "RelationshipEdge",
    "RetentionClassification",
    "RollbackRecord",
    "SavedIllustrativeCapacityPlan",
    "ScaleProfileName",
    "ScenarioGenerationRecord",
    "ScenarioType",
    "SensitivityCategory",
    "SnapshotRecord",
    "SnapshotStatus",
    "SourceDatasetDescriptor",
    "SourceSystemType",
    "StorageBackend",
    "SubsetManifest",
    "SubsetSelectionCriteria",
    "SubsettingStrategy",
    "SyntheticGenerationManifest",
    "VacuumCandidate",
]

__version__ = "0.1.0"
