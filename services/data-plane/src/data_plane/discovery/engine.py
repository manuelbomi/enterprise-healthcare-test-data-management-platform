"""The classification engine: combines schema-based, rule-based, and
manual-override classification into one `ColumnClassification` per column.

Precedence (highest wins)
--------------------------
1. **Manual override** (`overrides.py`) — a human data steward's decision
   always wins, at confidence 1.0.
2. **Schema-based** (`schema_rules.py`) — the column is a literal field of
   one of the 14 known Phase 1 entities, at confidence 1.0.
3. **Rule-based** (`pattern_rules.py`) — the highest-confidence pattern
   detector that matches the column name and/or sample values.
4. **Conservative default** — nothing matched at all. Per
   DATA_GOVERNANCE.md B.1 ("nothing is treated as safe to leave unmasked
   purely on an automated classifier's say-so"), this defaults to
   `SENSITIVE` at low confidence, never to `NON_SENSITIVE` — an unknown
   column is never assumed harmless.

This module intentionally does **not** claim that this precedence, or any
combination of detectors, constitutes proof of HIPAA compliance. See
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from healthcare_tdm_contracts import (
    TIER_BY_CATEGORY,
    ClassificationMethod,
    ColumnClassification,
    SensitivityCategory,
)

from data_plane.discovery import pattern_rules, schema_rules
from data_plane.discovery.overrides import ManualOverride, load_overrides

#: Classifications at or below this confidence have not earned automated
#: trust: DATA_GOVERNANCE.md B.1's "human-confirmable status" applies.
#: Exposed here (rather than only as the hardcoded 0.7 in
#: `ColumnClassification.needs_review`) so engine-level code/tests can
#: reference a single named constant.
LOW_CONFIDENCE_THRESHOLD = 0.7

#: Confidence assigned when no schema entry and no pattern detector
#: matched at all (the "true unknown" case).
NO_MATCH_CONFIDENCE = 0.3
NO_MATCH_REASON = (
    "No schema entry and no rule-based detector matched this column. "
    "Per DATA_GOVERNANCE.md B.1, an unrecognized column defaults to the "
    "conservative SENSITIVE category rather than being assumed safe; "
    "requires data-steward review before being treated as authoritative."
)


@dataclass
class ColumnToClassify:
    """One column the engine is asked to classify."""

    source_system: str
    dataset: str
    entity: str | None
    column: str
    sample_values: list[str] = field(default_factory=list)


class ClassificationEngine:
    """Stateful only in that it holds a loaded override table; otherwise
    every method is a pure function of its inputs, which keeps this
    independently unit-testable per `CONTRIBUTING.md`."""

    def __init__(self, overrides: dict[tuple[str, str, str], ManualOverride] | None = None) -> None:
        self.overrides = overrides if overrides is not None else load_overrides()

    def classify_column(self, item: ColumnToClassify) -> ColumnClassification:
        override = self.overrides.get((item.source_system, item.dataset, item.column))
        if override is not None:
            category = override.category
            confidence = 1.0
            detector = f"manual_override:{override.confirmed_by}"
            method = ClassificationMethod.MANUAL_OVERRIDE
            reason = override.reason
            confirmed_by = override.confirmed_by
        else:
            category, confidence, detector, method, reason = self._auto_classify(item)
            confirmed_by = None

        tier = TIER_BY_CATEGORY[category]
        return ColumnClassification(
            source_system=item.source_system,
            dataset=item.dataset,
            column=item.column,
            tier=tier,
            category=category,
            confidence=confidence,
            detector=detector,
            method=method,
            reason=reason,
            confirmed_by=confirmed_by,
        )

    def classify_columns(self, items: list[ColumnToClassify]) -> list[ColumnClassification]:
        return [self.classify_column(item) for item in items]

    @staticmethod
    def _auto_classify(
        item: ColumnToClassify,
    ) -> tuple[SensitivityCategory, float, str, ClassificationMethod, str]:
        if item.entity is not None:
            schema_rule = schema_rules.lookup(item.entity, item.column)
            if schema_rule is not None:
                return (
                    schema_rule.category,
                    1.0,
                    f"schema:{item.entity}.{item.column}",
                    ClassificationMethod.SCHEMA_BASED,
                    schema_rule.reason,
                )

        matches = pattern_rules.match_all(item.column, item.sample_values)
        if matches:
            best = max(matches, key=lambda d: d.confidence)
            return (best.category, best.confidence, best.detector_id, ClassificationMethod.RULE_BASED, best.reason)

        return (
            SensitivityCategory.SENSITIVE,
            NO_MATCH_CONFIDENCE,
            "fallback:no_match",
            ClassificationMethod.RULE_BASED,
            NO_MATCH_REASON,
        )


__all__ = [
    "LOW_CONFIDENCE_THRESHOLD",
    "NO_MATCH_CONFIDENCE",
    "NO_MATCH_REASON",
    "ClassificationEngine",
    "ColumnToClassify",
]
