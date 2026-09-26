"""Edge-case injection configuration and bookkeeping.

The Phase 1 spec requires the estate to intentionally include:
missing records, nulls, duplicate records, orphan records, malformed
values, late-arriving data, and schema drift. This module defines the
knobs that control how much of each is injected and a small report
object the generator fills in, so tests and documentation can assert on
*what was actually injected* rather than just hoping the rates worked
out.

Rates are expressed as fractions of the relevant population and are
combined with a floor (at least one occurrence, even at the ``tiny``
scale profile) so every edge case is always exercisable — including in
CI, which typically only runs the ``tiny`` profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EdgeCaseConfig:
    """Injection rates for each edge-case category.

    Every rate is a fraction (0.0-1.0) of the relevant population. The
    generator always injects *at least one* instance of every category
    regardless of rate/population size, so edge cases are never silently
    absent at small scale.
    """

    null_field_rate: float = 0.06
    duplicate_person_rate: float = 0.02
    duplicate_row_rate: float = 0.015
    orphan_rate: float = 0.02
    malformed_value_rate: float = 0.03
    late_arriving_rate: float = 0.04
    missing_child_rate: float = 0.05


DEFAULT_EDGE_CASE_CONFIG = EdgeCaseConfig()


@dataclass
class EdgeCaseReport:
    """Running tally of edge cases actually injected during a generation run.

    Populated by ``generator.EstateGenerator`` as it works; surfaced in
    the run manifest (``generator.GeneratedEstate.manifest``) and asserted
    on directly in tests (``tests/reference_data/test_edge_cases.py``).
    """

    null_fields_injected: int = 0
    duplicate_persons_injected: int = 0
    duplicate_rows_injected: int = 0
    orphan_records_injected: dict[str, int] = field(default_factory=dict)
    malformed_values_injected: int = 0
    late_arriving_records_injected: int = 0
    members_with_no_coverage: int = 0
    claims_with_no_lines: int = 0
    schema_drift_batches: list[str] = field(default_factory=list)

    def record_orphan(self, entity: str, count: int = 1) -> None:
        self.orphan_records_injected[entity] = self.orphan_records_injected.get(entity, 0) + count

    def as_dict(self) -> dict[str, object]:
        return {
            "null_fields_injected": self.null_fields_injected,
            "duplicate_persons_injected": self.duplicate_persons_injected,
            "duplicate_rows_injected": self.duplicate_rows_injected,
            "orphan_records_injected": dict(self.orphan_records_injected),
            "malformed_values_injected": self.malformed_values_injected,
            "late_arriving_records_injected": self.late_arriving_records_injected,
            "members_with_no_coverage": self.members_with_no_coverage,
            "claims_with_no_lines": self.claims_with_no_lines,
            "schema_drift_batches": list(self.schema_drift_batches),
        }


__all__ = ["DEFAULT_EDGE_CASE_CONFIG", "EdgeCaseConfig", "EdgeCaseReport"]
