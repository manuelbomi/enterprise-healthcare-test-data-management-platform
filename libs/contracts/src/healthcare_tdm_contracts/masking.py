"""Masking policy contracts.

Defines the shape of a masking policy: the mapping from a classification
tier (see classification.py) to a masking strategy. See
DATA_GOVERNANCE.md (section B.2) for the policy model and
docs/adr/0006-deterministic-masking-strategy.md for why masking of
identifiers must be deterministic and keyed rather than random.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.classification import ClassificationTier


class MaskingStrategy(str, Enum):
    """How a value is transformed for a given classification tier.

    DETERMINISTIC_TOKENIZATION: masked = f(real_value, scope, secret_key).
        Same real value + same scope always yields the same masked value,
        preserving joinability. Used for direct identifiers. See ADR-0006.
    GENERALIZATION: reduce precision (e.g., date of birth -> birth year)
        rather than replace the value outright. Commonly used for
        quasi-identifiers.
    SYNTHETIC_REPLACEMENT: replace with an unrelated, generated value that
        carries no relationship to the original at all. Used where the
        policy decides the underlying fact is too sensitive to carry
        through even in de-identified form.
    PASSTHROUGH: value is not modified. Used for non-sensitive columns.
    """

    DETERMINISTIC_TOKENIZATION = "deterministic_tokenization"
    GENERALIZATION = "generalization"
    SYNTHETIC_REPLACEMENT = "synthetic_replacement"
    PASSTHROUGH = "passthrough"


class MaskingRule(BaseModel):
    """A single tier -> strategy mapping within a policy."""

    tier: ClassificationTier
    strategy: MaskingStrategy
    scope: str = Field(
        ...,
        description=(
            "Joinability scope for deterministic strategies, e.g. "
            "'patient-id-global' or 'qa-claims-env'. Two values masked "
            "under the same scope with the same key produce the same "
            "output; different scopes must not be correlatable."
        ),
    )
    parameters: dict[str, str] = Field(
        default_factory=dict,
        description="Strategy-specific parameters (e.g., generalization precision).",
    )


class MaskingPolicy(BaseModel):
    """A versioned, named set of masking rules.

    Every data-plane masking job resolves and records the exact policy
    version it used (see ARCHITECTURE.md section 3.1 and the lineage
    model), so a masked output is always reproducible and auditable
    against the policy that produced it.
    """

    name: str
    version: int = Field(..., ge=1)
    rules: list[MaskingRule]
    approved_by: str | None = Field(
        default=None, description="Identity that approved this policy version, if approved."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
