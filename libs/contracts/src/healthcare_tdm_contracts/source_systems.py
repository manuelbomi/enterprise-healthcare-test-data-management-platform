"""Source system vocabulary shared across planes.

The platform provisions test data that originates from multiple
heterogeneous *source systems* (an enrollment database, a claims
warehouse, a clinical data lake, a pharmacy benefit manager extract, an
external partner feed, ...). Every plane needs a common, closed vocabulary
for naming those systems and for describing the scale at which a dataset
was generated:

- The data plane's reference synthetic data estate (see
  ``services/data-plane/src/data_plane/reference_data``) is organized by
  source system and is generated at a chosen scale profile.
- Discovery (Phase 7) will classify columns per ``(source_system,
  dataset)`` pair, reusing ``ColumnClassification.source_system`` as a
  free-form string today; ``SourceSystemType`` gives that string a closed,
  typed vocabulary going forward.
- Subsetting/masking (Phases 8-10) need to know which datasets are
  Postgres-bound (real foreign keys enforceable) versus file/object-store
  bound (referential integrity is a *logical* contract enforced by the
  producing job, not the storage engine) — see
  ``docs/adr/0004-postgresql-metadata-store.md`` and
  ``docs/adr/0005-object-storage-abstraction.md``.

No business logic lives here — only the shared shapes, per the package
README.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SourceSystemType(str, Enum):
    """The heterogeneous simulated source systems this platform ingests from.

    Each member corresponds to one of the five source-system categories
    called out in ``ARCHITECTURE.md`` / ``ROADMAP.md`` Phase 6 ("reference
    synthetic healthcare schema + generators"): a relational operational
    database, a generic object-storage/Parquet data warehouse, an
    S3-compatible data lake, an Azure/ADLS-compatible extract, and an
    external partner file/API feed.
    """

    POSTGRES_ENROLLMENT = "postgres_enrollment"
    OBJECT_STORAGE_CLAIMS_PARQUET = "object_storage_claims_parquet"
    S3_CLINICAL_DATA_LAKE = "s3_clinical_data_lake"
    ADLS_PBM_EXTRACT = "adls_pbm_extract"
    PARTNER_LAB_FEED = "partner_lab_feed"


class ScaleProfileName(str, Enum):
    """Named data-volume profiles for generated/provisioned datasets.

    See ``data_plane.reference_data.scale`` for the concrete row-count
    parameters each profile resolves to. Kept here (rather than only in
    the data plane) because later phases (subsetting sizing rules, control
    plane job requests, capacity planning in Phase 15) need to reference a
    scale profile by name without depending on the data-plane package.
    """

    TINY = "tiny"
    DEVELOPER = "developer"
    QA = "qa"
    PERFORMANCE = "performance"


class SourceDatasetDescriptor(BaseModel):
    """Describes where one logical dataset/entity lives in the source estate.

    This is the shape the (future) data catalog uses to answer "what is
    ``claim_line``, which system owns it, and how do I read it back" —
    produced once by the reference data generator's manifest and consumed
    by discovery (Phase 7) and subsetting (Phase 8).
    """

    entity: str = Field(..., description="Logical entity name, e.g. 'Member' or 'ClaimLine'.")
    source_system: SourceSystemType
    storage_format: str = Field(
        ..., description="Concrete on-disk/on-wire format, e.g. 'sqlite_table', 'parquet', "
        "'ndjson', 'csv', 'pipe_delimited_flat_file'."
    )
    location: str = Field(
        ..., description="Bucket/container/schema-qualified location of the dataset."
    )
    row_count: int = Field(..., ge=0)
    scale_profile: ScaleProfileName


__all__ = [
    "ScaleProfileName",
    "SourceDatasetDescriptor",
    "SourceSystemType",
]
