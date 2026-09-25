"""Classification contracts.

Defines the PHI/PII classification model described in DATA_GOVERNANCE.md
(section B.1). These shapes are produced by the data plane's discovery
engine (Phase 7) and consumed by the control plane's policy engine and the
security/governance plane's access-control checks.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ClassificationTier(str, Enum):
    """The four classification tiers a column can be assigned.

    See DATA_GOVERNANCE.md section B.1 for the full definition and
    handling rules for each tier. Ordered here from most to least
    sensitive; code that needs to compare "is at least as sensitive as"
    can rely on this ordering.
    """

    DIRECT_IDENTIFIER = "direct_identifier"
    QUASI_IDENTIFIER = "quasi_identifier"
    SENSITIVE_CLINICAL_ATTRIBUTE = "sensitive_clinical_attribute"
    NON_SENSITIVE = "non_sensitive"


class ColumnClassification(BaseModel):
    """The classification of a single column in a single known dataset.

    A row of this shape is what the discovery engine produces and what the
    metadata plane's classification store persists. `confidence` and
    `confirmed_by` exist because classification is not purely automated —
    per DATA_GOVERNANCE.md, low-confidence classifications default to the
    more conservative tier until a human data steward confirms them.
    """

    source_system: str = Field(
        ..., description="Logical name of the source system, e.g. 'ehr-synthetic'."
    )
    dataset: str = Field(..., description="Table or dataset name within the source system.")
    column: str = Field(..., description="Column name being classified.")
    tier: ClassificationTier
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Discovery engine's confidence in this classification."
    )
    detector: str = Field(
        ..., description="Name of the rule/pattern detector that produced this classification."
    )
    confirmed_by: str | None = Field(
        default=None,
        description=(
            "Identity of the data steward who confirmed this classification, "
            "or None if it is still automated-only and unconfirmed."
        ),
    )
    confirmed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
