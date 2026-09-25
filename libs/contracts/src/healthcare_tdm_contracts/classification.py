"""Classification contracts.

Defines the PHI/PII classification model described in DATA_GOVERNANCE.md
(section B.1). These shapes are produced by the data plane's discovery
engine (`services/data-plane/src/data_plane/discovery`, implemented in
Phase 2) and consumed by the control plane's catalog API
(`services/control-plane/src/control_plane/api/v1/catalog.py`) and,
eventually, the security/governance plane's access-control checks.

Two labels, on purpose
-----------------------
This module defines *two* classification vocabularies rather than one,
because they answer two different questions and collapsing them into a
single enum would lose information:

- :class:`ClassificationTier` (four values) answers "how must this column
  be **handled**?" It is exactly the four-tier model
  `DATA_GOVERNANCE.md` section B.1 defines, and it is what
  `MaskingRule`/`MaskingPolicy` (see `masking.py`) key their masking
  strategy off of. This enum existed before Phase 2 (Phase 0 scaffolding)
  and is left unchanged so `DATA_GOVERNANCE.md` and every existing
  masking-policy reference stays valid.
- :class:`SensitivityCategory` (six values — `direct_identifier`,
  `quasi_identifier`, `phi`, `pii`, `sensitive`, `non_sensitive`, per the
  Phase 2 promptbook) answers "what **kind** of sensitive data is this,
  and why?" It is the label the discovery engine's detectors reason about
  and the label shown in the data catalog, because "PHI" and "PII" are
  the vocabulary a data steward or auditor actually uses in conversation,
  while "quasi-identifier" is a de-identification-science term a steward
  may not use for a clinical fact like a diagnosis code.

These two labels are **not** a 1:1 renaming of each other — they overlap
by design, because PHI/PII are legal/industry umbrella terms while
direct-identifier/quasi-identifier are re-identification-risk terms, and
a single column can honestly be described by more than one of the six
labels at once (a name is both a `direct_identifier` and `PII`; a
diagnosis code is both `PHI` and, in combination with other fields, a
`quasi_identifier`). Because the catalog needs one primary label per
column, this module fixes a precedence order (see
`SensitivityCategory.precedence()`) and documents it, rather than
pretending the six labels are a clean partition. See
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for the full discussion.

`TIER_BY_CATEGORY` is the (documented, overridable) default mapping from
the fine-grained category to the coarse masking-policy tier, so every
`ColumnClassification` can always answer both questions consistently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ClassificationTier(str, Enum):
    """The four classification tiers a column can be assigned.

    See DATA_GOVERNANCE.md section B.1 for the full definition and
    handling rules for each tier. Ordered here from most to least
    sensitive; code that needs to compare "is at least as sensitive as"
    can rely on this ordering. This is the tier `MaskingRule` (see
    `masking.py`) keys its masking strategy off of.
    """

    DIRECT_IDENTIFIER = "direct_identifier"
    QUASI_IDENTIFIER = "quasi_identifier"
    SENSITIVE_CLINICAL_ATTRIBUTE = "sensitive_clinical_attribute"
    NON_SENSITIVE = "non_sensitive"


class SensitivityCategory(str, Enum):
    """The six catalog-facing classification labels (Phase 2 promptbook).

    Meaning assigned by this engine (see module docstring for why a
    precedence order is needed rather than a disjoint partition):

    DIRECT_IDENTIFIER
        Uniquely and directly identifies a specific person by itself
        (name, SSN, MRN, email, phone, street address, a member/patient
        linking key, a health-plan account/group number).
    QUASI_IDENTIFIER
        Not unique alone, but re-identifying in combination (dates tied
        to an individual, ZIP/city, sex, race/ethnicity, marital status,
        preferred language, internal surrogate keys that join to a
        specific member/record).
    PHI
        Reveals a sensitive health/clinical *fact* about a specific
        person's care, but is not itself an identifying key (diagnosis
        code, procedure code, drug/NDC, lab test/result, encounter type).
    PII
        Personal information about an identifiable real individual who is
        not the patient being cared for (a provider's or pharmacy's NPI,
        a provider's name) — or other patient-adjacent personal metadata
        that doesn't fit the direct/quasi-identifier or PHI buckets.
    SENSITIVE
        Sensitive for reasons other than identity or health — business or
        financial data (billed/allowed/paid amounts) — and this engine's
        own conservative default for any column no detector recognized
        (see DATA_GOVERNANCE.md B.1: never default an unknown column to
        "safe").
    NON_SENSITIVE
        Passes through unmodified: status/type codes, booleans,
        code-system labels, pipeline/ETL batch metadata.
    """

    DIRECT_IDENTIFIER = "direct_identifier"
    QUASI_IDENTIFIER = "quasi_identifier"
    PHI = "phi"
    PII = "pii"
    SENSITIVE = "sensitive"
    NON_SENSITIVE = "non_sensitive"

    @classmethod
    def precedence(cls) -> list["SensitivityCategory"]:
        """Most-to-least-severe order, used when more than one category
        could plausibly apply and the catalog needs a single primary
        label (see module docstring)."""

        return [
            cls.DIRECT_IDENTIFIER,
            cls.QUASI_IDENTIFIER,
            cls.PHI,
            cls.PII,
            cls.SENSITIVE,
            cls.NON_SENSITIVE,
        ]


#: Default category -> tier mapping. Conservative by construction: every
#: category except NON_SENSITIVE maps to a tier that is masked/generalized
#: in some way, never passed through. `PII` and `SENSITIVE` do not have a
#: dedicated tier in the four-tier `DATA_GOVERNANCE.md` model, so they are
#: folded into the nearest tier that is at least as conservative:
#: `PII` -> `QUASI_IDENTIFIER` (a non-patient identifying attribute still
#: contributes to re-identification risk), `SENSITIVE` ->
#: `SENSITIVE_CLINICAL_ATTRIBUTE` (treated with the same "handle with
#: extra care" tier as a clinical fact, even though the reason is
#: business/financial sensitivity rather than health sensitivity).
TIER_BY_CATEGORY: dict[SensitivityCategory, ClassificationTier] = {
    SensitivityCategory.DIRECT_IDENTIFIER: ClassificationTier.DIRECT_IDENTIFIER,
    SensitivityCategory.QUASI_IDENTIFIER: ClassificationTier.QUASI_IDENTIFIER,
    SensitivityCategory.PHI: ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
    SensitivityCategory.PII: ClassificationTier.QUASI_IDENTIFIER,
    SensitivityCategory.SENSITIVE: ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
    SensitivityCategory.NON_SENSITIVE: ClassificationTier.NON_SENSITIVE,
}

#: Inverse, used only to backfill `category` when a caller constructs a
#: `ColumnClassification` the old (Phase 0) way, passing only `tier`. Picks
#: the single category each tier maps to under `TIER_BY_CATEGORY` above
#: (PHI, not SENSITIVE, for the clinical tier — PHI is the more common
#: case and SENSITIVE is reserved for the "nothing matched" fallback).
_CATEGORY_BY_TIER: dict[ClassificationTier, SensitivityCategory] = {
    ClassificationTier.DIRECT_IDENTIFIER: SensitivityCategory.DIRECT_IDENTIFIER,
    ClassificationTier.QUASI_IDENTIFIER: SensitivityCategory.QUASI_IDENTIFIER,
    ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE: SensitivityCategory.PHI,
    ClassificationTier.NON_SENSITIVE: SensitivityCategory.NON_SENSITIVE,
}


class ClassificationMethod(str, Enum):
    """How a `ColumnClassification` was produced.

    Mirrors the Phase 2 promptbook's required support matrix: schema-based
    classification (the column is a literal field of a known entity),
    rule-based classification (a name/value-pattern detector fired), and
    manual override (a human data steward set or corrected the label).
    """

    SCHEMA_BASED = "schema_based"
    RULE_BASED = "rule_based"
    MANUAL_OVERRIDE = "manual_override"


class ColumnClassification(BaseModel):
    """The classification of a single column in a single known dataset.

    A row of this shape is what the discovery engine produces and what the
    metadata plane's classification store persists. `confidence` and
    `confirmed_by` exist because classification is not purely automated —
    per DATA_GOVERNANCE.md, low-confidence classifications default to the
    more conservative tier until a human data steward confirms them; see
    `needs_review`.
    """

    source_system: str = Field(
        ..., description="Logical name of the source system, e.g. 'ehr-synthetic'."
    )
    dataset: str = Field(..., description="Table or dataset name within the source system.")
    column: str = Field(..., description="Column name being classified.")
    tier: ClassificationTier
    category: SensitivityCategory | None = Field(
        default=None,
        description=(
            "Fine-grained catalog label (direct_identifier/quasi_identifier/"
            "phi/pii/sensitive/non_sensitive). If omitted, backfilled from "
            "`tier` via the default mapping for backward compatibility with "
            "Phase 0-era callers that only set `tier`."
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Discovery engine's confidence in this classification."
    )
    detector: str = Field(
        ..., description="Name of the rule/pattern detector that produced this classification."
    )
    method: ClassificationMethod = Field(
        default=ClassificationMethod.RULE_BASED,
        description="Which mechanism produced this classification.",
    )
    reason: str = Field(
        default="",
        description="Human-readable rationale for this classification (audit/explainability).",
    )
    confirmed_by: str | None = Field(
        default=None,
        description=(
            "Identity of the data steward who confirmed this classification, "
            "or None if it is still automated-only and unconfirmed."
        ),
    )
    confirmed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _backfill_category(self) -> "ColumnClassification":
        if self.category is None:
            self.category = _CATEGORY_BY_TIER.get(self.tier, SensitivityCategory.SENSITIVE)
        return self

    @property
    def needs_review(self) -> bool:
        """True when this classification has not been confirmed by a human
        and its confidence is below the engine's conservative-review
        threshold (`data_plane.discovery.engine.LOW_CONFIDENCE_THRESHOLD`,
        duplicated here as a plain float so `libs/contracts` has no
        dependency on the data-plane package — see ADR-0003).

        This is the queryable form of DATA_GOVERNANCE.md B.1's rule that
        "nothing is treated as safe to leave unmasked purely on an
        automated classifier's say-so below a configured confidence
        threshold" — it flags for review rather than silently overriding
        the detector's own (honestly reported) confidence.
        """

        return self.confirmed_by is None and self.confidence < 0.7
