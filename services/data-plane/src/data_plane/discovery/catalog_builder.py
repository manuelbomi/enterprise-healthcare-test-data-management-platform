"""Build the data catalog: classify every scanned column and attach the
catalog-level metadata (`dataset`, `column`, `classification`, `masking
requirement`, `source`, `owner`, `retention classification`) the Phase 2
spec's catalog representation requires.

Owner and retention-classification assignment are simple, documented
lookup tables (below) — not a policy engine (that's the control plane's
job, later phases). They exist so the catalog is readable end to end
today; treat them as illustrative defaults, exactly like
`DEFAULT_MASKING_BY_TIER` (see its docstring on `CatalogEntry.
masking_requirement` in `libs/contracts`).
"""

from __future__ import annotations

import json
from pathlib import Path

from healthcare_tdm_contracts import (
    CatalogEntry,
    ClassificationTier,
    MaskingStrategy,
    RetentionClassification,
    SensitivityCategory,
    SourceSystemType,
)

from data_plane.discovery.engine import ClassificationEngine, ColumnToClassify

#: Preview default masking strategy per tier. NOT the authoritative
#: masking policy (see `CatalogEntry.masking_requirement` docstring) —
#: that is `MaskingPolicy`/`MaskingRule` (Phase 3).
DEFAULT_MASKING_BY_TIER: dict[ClassificationTier, MaskingStrategy] = {
    ClassificationTier.DIRECT_IDENTIFIER: MaskingStrategy.DETERMINISTIC_TOKENIZATION,
    ClassificationTier.QUASI_IDENTIFIER: MaskingStrategy.GENERALIZATION,
    ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE: MaskingStrategy.SYNTHETIC_REPLACEMENT,
    ClassificationTier.NON_SENSITIVE: MaskingStrategy.PASSTHROUGH,
}

#: Which team owns/stewards each simulated source system (see
#: `reference_data/README.md` "Why each dataset exists" for why these
#: groupings match the estate's own system boundaries).
OWNER_BY_SOURCE_SYSTEM: dict[str, str] = {
    SourceSystemType.POSTGRES_ENROLLMENT.value: "Enrollment Data Engineering",
    SourceSystemType.OBJECT_STORAGE_CLAIMS_PARQUET.value: "Claims Data Engineering",
    SourceSystemType.S3_CLINICAL_DATA_LAKE.value: "Clinical Data Engineering",
    SourceSystemType.ADLS_PBM_EXTRACT.value: "Pharmacy Benefit Management Integration",
    SourceSystemType.PARTNER_LAB_FEED.value: "Partner Integrations",
}

#: Datasets that are small, mostly-static reference/code vocabulary
#: (product catalog, code tables, directories) rather than per-member
#: transactional data — these keep the same rows indefinitely in test
#: environments regardless of any one column's category, per
#: DATA_GOVERNANCE.md B.5.
REFERENCE_DATASETS: frozenset[str] = frozenset(
    {"plan", "diagnosis", "procedure", "pharmacy", "provider"}
)

#: Default retention classification by category, for datasets not in
#: `REFERENCE_DATASETS` (see `RetentionClassification` docstring: this is
#: illustrative, not a certified retention schedule).
RETENTION_BY_CATEGORY: dict[SensitivityCategory, RetentionClassification] = {
    SensitivityCategory.DIRECT_IDENTIFIER: RetentionClassification.EXTENDED,
    SensitivityCategory.PHI: RetentionClassification.EXTENDED,
    SensitivityCategory.QUASI_IDENTIFIER: RetentionClassification.STANDARD,
    SensitivityCategory.PII: RetentionClassification.STANDARD,
    SensitivityCategory.SENSITIVE: RetentionClassification.STANDARD,
    SensitivityCategory.NON_SENSITIVE: RetentionClassification.EPHEMERAL,
}


def _retention_for(dataset: str, category: SensitivityCategory) -> RetentionClassification:
    if dataset in REFERENCE_DATASETS:
        return RetentionClassification.PERSISTENT_REFERENCE
    return RETENTION_BY_CATEGORY[category]


def build_catalog(
    columns: list[ColumnToClassify], engine: ClassificationEngine | None = None
) -> list[CatalogEntry]:
    """Classify every scanned column and build the full `CatalogEntry` list."""

    engine = engine or ClassificationEngine()
    entries: list[CatalogEntry] = []
    for item in columns:
        classification = engine.classify_column(item)
        category = classification.category or SensitivityCategory.SENSITIVE
        entries.append(
            CatalogEntry(
                classification=classification,
                masking_requirement=DEFAULT_MASKING_BY_TIER[classification.tier],
                owner=OWNER_BY_SOURCE_SYSTEM.get(item.source_system, "Unassigned"),
                retention_classification=_retention_for(item.dataset, category),
            )
        )
    return entries


def write_catalog(entries: list[CatalogEntry], path: Path) -> Path:
    """Write the catalog as a JSON array of `CatalogEntry` objects."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [json.loads(entry.model_dump_json()) for entry in entries]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_catalog(path: Path) -> list[CatalogEntry]:
    """Read a catalog JSON artifact back into `CatalogEntry` objects.

    Used by this package's own tests/CLI and mirrored (independently, per
    ADR-0003/ADR-0009) by `control_plane.catalog.repository` — the
    control plane does not import `data_plane`, so it does not call this
    function directly; it has its own copy of this same, small amount of
    logic against the shared `libs/contracts` shape.
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    return [CatalogEntry.model_validate(row) for row in raw]


__all__ = [
    "DEFAULT_MASKING_BY_TIER",
    "OWNER_BY_SOURCE_SYSTEM",
    "REFERENCE_DATASETS",
    "RETENTION_BY_CATEGORY",
    "build_catalog",
    "load_catalog",
    "write_catalog",
]
