"""Data catalog contract.

Defines :class:`CatalogEntry`, the row shape the discovery engine's
catalog (`services/data-plane/src/data_plane/discovery/catalog_builder.py`)
produces and the control plane's catalog API
(`services/control-plane/src/control_plane/api/v1/catalog.py`) serves.

Deliberately a thin wrapper around :class:`ColumnClassification`
(composition, not duplication — see `classification.py`) plus the extra
fields the Phase 2 spec's catalog representation requires that are
not properties of the classification itself: masking requirement, owning
team, and retention classification. See ADR-0009
(`docs/adr/0009-catalog-artifact-handoff.md`) for why this shape is
handed between planes as a JSON artifact today rather than a database
row, and `docs/problems/problems_phase_02.md` (P2-4) for the tracked follow-up.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.classification import ColumnClassification
from healthcare_tdm_contracts.masking import MaskingStrategy


class RetentionClassification(str, Enum):
    """How long test-data derived from this column is expected to be kept.

    Illustrative labels, not a certified retention schedule — see
    DATA_GOVERNANCE.md section B.5 ("Retention and refresh"), which this
    engine implements a simplified, per-column preview of. The real
    expiry/refresh cadence is tracked per-*snapshot* by the metadata
    plane's snapshot registry (ROADMAP.md Phase 7), not per-column; this
    label is discovery's best-effort input to that later policy decision.
    """

    EPHEMERAL = "ephemeral"
    STANDARD = "standard"
    EXTENDED = "extended"
    PERSISTENT_REFERENCE = "persistent_reference"


class CatalogEntry(BaseModel):
    """One row of the PHI/PII data catalog: a classified column, plus the
    catalog-level metadata a data steward or auditor needs alongside it.
    """

    classification: ColumnClassification = Field(
        ..., description="The underlying column classification (dataset, column, tier, etc.)."
    )
    masking_requirement: MaskingStrategy = Field(
        ...,
        description=(
            "DEFAULT preview of the masking strategy this column's tier implies "
            "(see catalog_builder.DEFAULT_MASKING_BY_TIER). This is NOT the "
            "authoritative masking policy — that is `MaskingPolicy`/`MaskingRule` "
            "(masking.py), versioned and enforced by the masking engine built in "
            "Phase 3. This field exists so the catalog is useful to read on its "
            "own, before Phase 3 exists."
        ),
    )
    owner: str = Field(
        ..., description="Team/role accountable for this dataset (data steward contact)."
    )
    retention_classification: RetentionClassification

    @property
    def dataset(self) -> str:
        return self.classification.dataset

    @property
    def column(self) -> str:
        return self.classification.column

    @property
    def source(self) -> str:
        return self.classification.source_system


__all__ = ["CatalogEntry", "RetentionClassification"]
