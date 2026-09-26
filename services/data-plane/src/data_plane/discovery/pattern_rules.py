"""Rule-based (pattern/heuristic) classification.

Consulted only for columns the schema layer (`schema_rules.py`) does not
recognize — i.e., columns that are not a literal field of one of the 14
known Phase 1 entities. In the real Phase 1 estate this fires for exactly
the columns the schema-drift edge cases introduce: the claims warehouse's
renamed `amount_paid`/new `adjustment_reason_code` (current-quarter
batch), and the partner lab feed's v1 abbreviated field names (`pat_id`,
`test_cd`, `test_nm`, `result`, `collected_dt`, `delivered_dt`), plus the
pipeline-metadata-only fields both partner formats add (`delivered_at`,
`late_arrival`). See `services/data-plane/src/data_plane/reference_data/
writers/parquet_writer.py` and `writers/partner_writer.py`.

Each detector is a column-name regex (case-insensitive) plus a fixed
confidence and reason. When a column matches more than one detector, the
highest-confidence match wins (ties broken by list order). If nothing
matches at all, the engine (`engine.py`) applies DATA_GOVERNANCE.md B.1's
conservative-default rule itself, rather than this module guessing.

Honesty note (do not remove)
-----------------------------
Regex/name-based detection like this is a triage tool, not a compliance
guarantee. See `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for exactly
what it can and cannot prove — in particular, it has no access to actual
column *values* by default (see `sample_values` support below, which
covers exactly two of the weakest name-only cases: email and SSN shape)
and no semantic understanding of what a column means in context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from healthcare_tdm_contracts import SensitivityCategory

DI = SensitivityCategory.DIRECT_IDENTIFIER
QI = SensitivityCategory.QUASI_IDENTIFIER
PHI = SensitivityCategory.PHI
PII = SensitivityCategory.PII
SENSITIVE = SensitivityCategory.SENSITIVE
NON_SENSITIVE = SensitivityCategory.NON_SENSITIVE


@dataclass(frozen=True)
class PatternDetector:
    """A single rule-based detector.

    `column_pattern` is matched against the column name (case-insensitive,
    `re.search`). `value_pattern`, if set, is matched against sample
    values (see `engine.py`); a value-pattern match alone can fire the
    detector even if the column name doesn't match, which is how this
    engine catches an oddly-named column that nonetheless clearly holds
    (e.g.) email addresses.
    """

    detector_id: str
    category: SensitivityCategory
    confidence: float
    reason: str
    column_pattern: re.Pattern[str] | None = None
    value_pattern: re.Pattern[str] | None = None


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


PATTERN_DETECTORS: list[PatternDetector] = [
    PatternDetector(
        detector_id="pattern:ssn",
        category=DI,
        confidence=0.95,
        reason="Column name matches a Social Security Number naming pattern.",
        column_pattern=_re(r"(^|_)ssn(_|$)|social_security"),
        value_pattern=_re(r"^\d{3}-?\d{2}-?\d{4}$"),
    ),
    PatternDetector(
        detector_id="pattern:email",
        category=DI,
        confidence=0.95,
        reason="Column name matches an email-address naming pattern.",
        column_pattern=_re(r"e[-_]?mail"),
        value_pattern=_re(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    ),
    PatternDetector(
        detector_id="pattern:phone",
        category=DI,
        confidence=0.85,
        reason="Column name matches a phone/fax number naming pattern.",
        column_pattern=_re(r"phone|fax|mobile|telephone"),
    ),
    PatternDetector(
        detector_id="pattern:person_name",
        category=DI,
        confidence=0.9,
        reason="Column name matches a person-name naming pattern (first/last/middle/full/patient/member name).",
        column_pattern=_re(r"(^|_)(first|last|middle|full|patient|member)_name$"),
    ),
    PatternDetector(
        detector_id="pattern:medical_record_number",
        category=DI,
        confidence=0.95,
        reason="Column name matches a medical-record-number naming pattern.",
        column_pattern=_re(r"\bmrn\b|medical_record"),
    ),
    PatternDetector(
        detector_id="pattern:patient_link_id",
        category=DI,
        confidence=0.9,
        reason=(
            "Column name matches a patient/member linking-identifier naming "
            "pattern (including common abbreviations, e.g. a legacy partner "
            "feed's 'pat_id')."
        ),
        column_pattern=_re(r"^(member_id|patient_id|subscriber_id|pat_id|mbr_id)$"),
    ),
    PatternDetector(
        detector_id="pattern:account_number",
        category=DI,
        confidence=0.85,
        reason="Column name matches a health-plan account/group/policy-number naming pattern.",
        column_pattern=_re(r"group_number|account_number|policy_number"),
    ),
    PatternDetector(
        detector_id="pattern:npi",
        category=PII,
        confidence=0.7,
        reason=(
            "Column name matches an NPI (National Provider Identifier) naming "
            "pattern. NPIs identify providers, not patients, but this detector "
            "cannot confirm that from the name alone (see "
            "docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md); treated conservatively "
            "as PII rather than assumed non-sensitive."
        ),
        column_pattern=_re(r"\bnpi\b"),
    ),
    PatternDetector(
        detector_id="pattern:pipeline_metadata",
        category=NON_SENSITIVE,
        confidence=0.65,
        reason="Column name matches an ETL/pipeline-metadata naming pattern (batch/delivery/schema-version bookkeeping).",
        column_pattern=_re(
            r"extract_batch|source_extracted_at|delivered_at|delivered_dt|"
            r"late_arrival|schema_version|row_version|batch_id"
        ),
    ),
    PatternDetector(
        detector_id="pattern:surrogate_key",
        category=QI,
        confidence=0.75,
        reason="Column name matches an internal surrogate-key naming pattern that typically joins to a specific member/record.",
        column_pattern=_re(r"(^|_)(coverage|claim|claim_line|prescription|encounter|lab_result|address)_id$"),
    ),
    PatternDetector(
        detector_id="pattern:date",
        category=QI,
        confidence=0.6,
        reason="Column name matches a date/timestamp naming pattern; treated as a quasi-identifier by default absent schema context (see DATA_GOVERNANCE.md B.1).",
        column_pattern=_re(r"_date$|^date_|dob|birth|_dt$|_at$"),
    ),
    PatternDetector(
        detector_id="pattern:zip",
        category=QI,
        confidence=0.85,
        reason="Column name matches a ZIP/postal code naming pattern.",
        column_pattern=_re(r"zip"),
    ),
    PatternDetector(
        detector_id="pattern:city",
        category=QI,
        confidence=0.75,
        reason="Column name matches a city naming pattern.",
        column_pattern=_re(r"^city$|city_name"),
    ),
    PatternDetector(
        detector_id="pattern:clinical_fact",
        category=PHI,
        confidence=0.75,
        reason="Column name matches a clinical fact naming pattern (diagnosis/procedure/drug/lab test/result).",
        column_pattern=_re(
            r"diagnos|procedure|ndc|drug_name|test_cd|test_code|test_nm|"
            r"test_name|^result$|result_value|abnormal"
        ),
    ),
    PatternDetector(
        detector_id="pattern:financial_amount",
        category=SENSITIVE,
        confidence=0.7,
        reason="Column name matches a financial-amount naming pattern.",
        column_pattern=_re(r"amount|charge|billed|allowed|paid"),
    ),
]


#: Phase 18B (`docs/problems/problems_final_review.md` P3-10, narrowed -- see
#: `match_all`'s own docstring for exactly what this does and does not
#: fix): entity names this repository's own schema
#: (`data_plane.reference_data.domain`) already treats as
#: business/organizational, not personal -- `Provider` (a specific
#: provider or practice, `_R_PROVIDER_PII` in `schema_rules.py`) and
#: `Pharmacy` (a dispensing business, not a patient). Matched
#: case-insensitively against `ColumnToClassify.entity`.
BUSINESS_ENTITY_NAMES = frozenset({"provider", "pharmacy"})


def match_all(
    column: str, sample_values: list[str] | None = None, entity: str | None = None
) -> list[PatternDetector]:
    """Return every detector that matches this column (by name and/or
    sample value), unsorted. `engine.py` picks the highest-confidence
    match.

    ``entity``, if given, is `ColumnToClassify.entity` -- the owning
    entity name, when the caller knows one, for a column that reached
    this fallback layer because it is *not* a literal field of that
    entity as `schema_rules.py` knows it (a schema-drift/renamed
    variant, e.g. `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`'s exact
    "novel source system with no schema entry" example, but for an
    entity name this repository *does* still recognize).

    Phase 18B (`docs/problems/problems_final_review.md` P3-10, narrowed, not closed):
    when ``entity`` is one of `BUSINESS_ENTITY_NAMES` and `pattern:npi`
    matches, this now returns a confidence-boosted, reason-clarified
    variant of that hit instead of the generic one -- schema-level
    entity context (which the pattern layer previously ignored entirely)
    resolves exactly the ambiguity `pattern:npi`'s own reason names
    ("cannot confirm [provider vs. some other role] from the name
    alone"), for this one case where a recognized business entity name
    is available. This does **not** close the underlying structural gap:
    a truly novel source system with an entity name this repository has
    never seen at all still gets the unmodified, lower-confidence guess
    -- entity-name recognition is itself necessarily a fixed, finite
    list, the same limitation every other schema-based mechanism in this
    engine already has."""

    hits: list[PatternDetector] = []
    values = sample_values or []
    entity_key = entity.strip().lower() if entity else None
    for detector in PATTERN_DETECTORS:
        name_hit = bool(detector.column_pattern and detector.column_pattern.search(column))
        value_hit = bool(
            detector.value_pattern
            and any(detector.value_pattern.match(v) for v in values if isinstance(v, str) and v)
        )
        if not (name_hit or value_hit):
            continue
        if detector.detector_id == "pattern:npi" and entity_key in BUSINESS_ENTITY_NAMES:
            hits.append(
                replace(
                    detector,
                    detector_id="pattern:npi+entity_context",
                    confidence=0.95,
                    reason=(
                        f"Column name matches an NPI naming pattern, and the owning entity "
                        f"({entity!r}) is one this repository's own schema "
                        f"(data_plane.reference_data.domain) already treats as a business/"
                        f"provider entity, not a patient one -- unlike the generic 'pattern:npi' "
                        f"guess, this is not a name-only inference (see "
                        f"docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md section 1's 'no semantic/"
                        f"contextual understanding' discussion of exactly this case)."
                    ),
                )
            )
        else:
            hits.append(detector)
    return hits


__all__ = ["BUSINESS_ENTITY_NAMES", "PATTERN_DETECTORS", "PatternDetector", "match_all"]
