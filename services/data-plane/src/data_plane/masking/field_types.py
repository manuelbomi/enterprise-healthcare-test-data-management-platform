"""Infer a `MaskingFieldType` from a bare column name.

Used as a *fallback* when a `MaskingRule` in the active policy does not
pin down `field_type` explicitly (`data_plane.masking.policy` pins it
explicitly for the columns the Phase 1 estate is known to have; this
module exists so an unrecognized column still gets a sensible synthetic
shape instead of falling back to the generic char-class-preserving
substitution for everything).

Deliberately mirrors the shape of
`data_plane.discovery.pattern_rules` (small, ordered, regex-based
detectors, first match wins) rather than reusing it directly -- this
module answers a different question ("what does this value look like?")
than discovery's ("how sensitive is this?"), and per ADR-0003/the
package boundary between `discovery` and `masking` (both live under
`data_plane`, so this is an intra-plane, not cross-plane, design choice),
keeping them independent avoids coupling a classification concern to a
synthesis concern that will evolve for different reasons.

Honesty note, consistent with `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`:
this is name-based pattern matching, not content inspection. It picks a
*plausible* synthetic shape, not a verified one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcare_tdm_contracts import MaskingFieldType


@dataclass(frozen=True)
class _FieldTypeDetector:
    field_type: MaskingFieldType
    pattern: re.Pattern[str]


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


#: Ordered, first-match-wins. More specific patterns are listed first.
_DETECTORS: list[_FieldTypeDetector] = [
    _FieldTypeDetector(MaskingFieldType.SSN, _re(r"(^|_)ssn(_|$)|social_security")),
    _FieldTypeDetector(MaskingFieldType.EMAIL, _re(r"e[-_]?mail")),
    _FieldTypeDetector(MaskingFieldType.PHONE, _re(r"phone|fax|mobile|telephone")),
    _FieldTypeDetector(MaskingFieldType.FIRST_NAME, _re(r"(^|_)first_name$")),
    _FieldTypeDetector(MaskingFieldType.LAST_NAME, _re(r"(^|_)last_name$")),
    _FieldTypeDetector(
        MaskingFieldType.FULL_NAME,
        _re(r"(^|_)(middle|full|patient|member|provider|prescriber|pharmacy)_name$|"
            r"^provider_name$|^pharmacy_name$"),
    ),
    _FieldTypeDetector(MaskingFieldType.ZIP_CODE, _re(r"zip")),
    _FieldTypeDetector(MaskingFieldType.CITY, _re(r"^city$|city_name")),
    _FieldTypeDetector(
        MaskingFieldType.STREET_ADDRESS, _re(r"(^|_)line1$|(^|_)line2$|street|address_line")
    ),
    _FieldTypeDetector(
        MaskingFieldType.IDENTIFIER,
        _re(
            r"^(member_id|patient_id|subscriber_id|pat_id|mbr_id)$|"
            r"(^|_)(coverage|claim|claim_line|prescription|encounter|"
            r"lab_result|address|provider|pharmacy|plan)_id$|"
            r"^(claim_id|coverage_id|provider_id|pharmacy_id|plan_id)$|"
            r"\bnpi\b|medical_record|\bmrn\b|group_number|account_number|policy_number"
        ),
    ),
    _FieldTypeDetector(MaskingFieldType.DATE, _re(r"_date$|^date_|dob|birth|_dt$")),
    _FieldTypeDetector(
        MaskingFieldType.NUMERIC,
        _re(r"amount|charge|billed|allowed|paid|quantity|units|days_supply"),
    ),
]


def infer_field_type(column: str) -> MaskingFieldType:
    """Return the best-guess `MaskingFieldType` for a bare column name, or
    `MaskingFieldType.GENERIC` if nothing matches."""

    for detector in _DETECTORS:
        if detector.pattern.search(column):
            return detector.field_type
    return MaskingFieldType.GENERIC


__all__ = ["infer_field_type"]
