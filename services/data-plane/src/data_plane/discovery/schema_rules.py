"""Schema-based classification: the authoritative source of truth.

Every column of every one of the 14 Phase 1 entities
(`data_plane.reference_data.domain`) is classified here explicitly, by a
human, once — not guessed at by a pattern. This is deliberately the
*first* thing the classification engine (`engine.py`) checks: if a column
is a literal field of a known entity, its classification comes from here
at confidence 1.0, and the rule-based pattern layer (`pattern_rules.py`)
is never consulted for it.

Why per-(entity, column), not just per-column-name
----------------------------------------------------
The same column *name* can mean different things on different entities —
most importantly, `Diagnosis.diagnosis_code` and `Procedure.procedure_code`
(rows of a small, non-patient-specific *code vocabulary* table — knowing
that code "SYN-ICD-10-E11.9" means "Type 2 diabetes without complications"
reveals nothing about any specific person) are NON_SENSITIVE, while
`ClaimLine.diagnosis_code`/`ClaimLine.procedure_code` (a specific code
value attached, via `claim_id`, to a specific claim and therefore a
specific member) are PHI. A column-name-only classifier cannot make this
distinction; keying on (entity, column) lets it.

See `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for what this table
cannot prove even though every value in it was authored with intent
(e.g., it cannot verify the *data actually matches* what the schema says
it should contain).
"""

from __future__ import annotations

from dataclasses import dataclass

from healthcare_tdm_contracts import SensitivityCategory


@dataclass(frozen=True)
class SchemaRule:
    """A single (entity, column) -> category rule, with its rationale."""

    category: SensitivityCategory
    reason: str


# Reusable reasons, so the table below stays scannable and the rationale
# text stays consistent across the many columns that share it.
_R_DIRECT_LINK = (
    "Uniquely links this row to a specific enrolled member across every "
    "source system in the estate; treated as a direct identifier even "
    "though the value itself is a synthetic surrogate key."
)
_R_NAME = "Person's name; a HIPAA Safe Harbor direct identifier."
_R_SSN = "Social Security Number; a HIPAA Safe Harbor direct identifier."
_R_MRN = "Medical record number; a HIPAA Safe Harbor direct identifier."
_R_EMAIL = "Email address; a HIPAA Safe Harbor direct identifier."
_R_PHONE = "Phone number; a HIPAA Safe Harbor direct identifier."
_R_STREET = (
    "Street-level address line; a geographic subdivision smaller than "
    "state, a HIPAA Safe Harbor direct identifier."
)
_R_ACCOUNT_NUMBER = (
    "Health-plan account/group number; a HIPAA Safe Harbor direct "
    "identifier (account numbers)."
)
_R_DATE_ON_MEMBER = (
    "Date tied to a specific member. HIPAA Safe Harbor treats all date "
    "elements (other than year) related to an individual as identifiers; "
    "modeled here as a quasi-identifier (re-identifying in combination) "
    "per DATA_GOVERNANCE.md B.1's own 'date of birth' example."
)
_R_DEMOGRAPHIC_QUASI = (
    "Demographic attribute that, combined with other quasi-identifiers, "
    "narrows re-identification risk (DATA_GOVERNANCE.md B.1 lists 'sex' "
    "as its worked example of this category)."
)
_R_GEO_QUASI = "Geographic subdivision smaller than state; re-identifying in combination."
_R_GEO_NON_SENSITIVE = (
    "State-level (or coarser) geography alone; HIPAA Safe Harbor does not "
    "require removing state-level geography."
)
_R_SURROGATE_KEY = (
    "Internal surrogate key with no meaning outside this estate, but it "
    "joins directly to a specific member/record and so is treated as "
    "re-identifying in combination, not as harmless."
)
_R_PROVIDER_PII = (
    "Identifies a specific provider (a real person or practice), not the "
    "patient; provider directory data is often public (e.g., the NPI "
    "registry), so it is treated as PII rather than a patient direct "
    "identifier — see docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md."
)
_R_BUSINESS_NON_SENSITIVE = "Business/organization attribute; does not identify or describe a person."
_R_CLINICAL_FACT = "Reveals a specific clinical fact about a specific person's care."
_R_FINANCIAL = "Financial amount; sensitive for business/fraud reasons, not identity or health."
_R_CODE_TABLE_NON_SENSITIVE = (
    "Row of a small, non-patient-specific code/reference vocabulary table; "
    "knowing the code's definition reveals nothing about any individual "
    "person on its own."
)
_R_OPERATIONAL_NON_SENSITIVE = "Operational/status metadata; not identifying, not clinical."
_R_PIPELINE_METADATA = "ETL/pipeline metadata about the extract itself, not about a person."


def _s(category: SensitivityCategory, reason: str) -> SchemaRule:
    return SchemaRule(category=category, reason=reason)


DI = SensitivityCategory.DIRECT_IDENTIFIER
QI = SensitivityCategory.QUASI_IDENTIFIER
PHI = SensitivityCategory.PHI
PII = SensitivityCategory.PII
SENSITIVE = SensitivityCategory.SENSITIVE
NON_SENSITIVE = SensitivityCategory.NON_SENSITIVE


#: entity name (matches `data_plane.reference_data.domain` class names,
#: and the logical `entity` used by the reference-data manifest/scanner)
#: -> { field name -> SchemaRule }. Covers every field of all 14 Phase 1
#: entities, by construction (asserted in
#: `tests/discovery/test_schema_rules.py`).
SCHEMA_RULES: dict[str, dict[str, SchemaRule]] = {
    "Member": {
        "member_id": _s(DI, _R_DIRECT_LINK),
        "first_name": _s(DI, _R_NAME),
        "last_name": _s(DI, _R_NAME),
        "date_of_birth": _s(QI, _R_DATE_ON_MEMBER),
        "gender": _s(QI, _R_DEMOGRAPHIC_QUASI),
        "ssn": _s(DI, _R_SSN),
        "medical_record_number": _s(DI, _R_MRN),
        "effective_date": _s(QI, _R_DATE_ON_MEMBER),
        "term_date": _s(QI, _R_DATE_ON_MEMBER),
        "is_active": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "row_version": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
        "extract_batch_id": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
    },
    "MemberDemographics": {
        "member_id": _s(DI, _R_DIRECT_LINK),
        "middle_name": _s(DI, _R_NAME),
        "race": _s(QI, _R_DEMOGRAPHIC_QUASI),
        "ethnicity": _s(QI, _R_DEMOGRAPHIC_QUASI),
        "preferred_language": _s(QI, _R_DEMOGRAPHIC_QUASI),
        "marital_status": _s(QI, _R_DEMOGRAPHIC_QUASI),
        "email": _s(DI, _R_EMAIL),
        "phone": _s(DI, _R_PHONE),
    },
    "Address": {
        "address_id": _s(QI, _R_SURROGATE_KEY),
        "member_id": _s(DI, _R_DIRECT_LINK),
        "address_type": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "line1": _s(DI, _R_STREET),
        "line2": _s(DI, _R_STREET),
        "city": _s(QI, _R_GEO_QUASI),
        "state": _s(NON_SENSITIVE, _R_GEO_NON_SENSITIVE),
        "zip_code": _s(QI, _R_GEO_QUASI),
        "country": _s(NON_SENSITIVE, _R_GEO_NON_SENSITIVE),
        "effective_date": _s(QI, _R_DATE_ON_MEMBER),
    },
    "Plan": {
        "plan_id": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "plan_name": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "plan_type": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "metal_tier": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "market_segment": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
    },
    "Coverage": {
        "coverage_id": _s(QI, _R_SURROGATE_KEY),
        "member_id": _s(DI, _R_DIRECT_LINK),
        "plan_id": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "group_number": _s(DI, _R_ACCOUNT_NUMBER),
        "effective_date": _s(QI, _R_DATE_ON_MEMBER),
        "term_date": _s(QI, _R_DATE_ON_MEMBER),
        "coverage_status": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "row_version": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
    },
    "Provider": {
        "provider_id": _s(PII, _R_PROVIDER_PII),
        "npi": _s(PII, _R_PROVIDER_PII),
        "provider_name": _s(PII, _R_PROVIDER_PII),
        "provider_type": _s(NON_SENSITIVE, _R_BUSINESS_NON_SENSITIVE),
        "specialty": _s(NON_SENSITIVE, _R_BUSINESS_NON_SENSITIVE),
        "city": _s(NON_SENSITIVE, "Provider practice location; business/public directory info."),
        "state": _s(NON_SENSITIVE, _R_GEO_NON_SENSITIVE),
        "is_active": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
    },
    "Diagnosis": {
        "diagnosis_code": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "description": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "code_system": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
    },
    "Procedure": {
        "procedure_code": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "description": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
        "code_system": _s(NON_SENSITIVE, _R_CODE_TABLE_NON_SENSITIVE),
    },
    "Claim": {
        "claim_id": _s(QI, _R_SURROGATE_KEY),
        "member_id": _s(DI, _R_DIRECT_LINK),
        "coverage_id": _s(QI, _R_SURROGATE_KEY),
        "provider_id": _s(PII, _R_PROVIDER_PII),
        "claim_type": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "status": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "service_date": _s(QI, _R_DATE_ON_MEMBER),
        "submitted_date": _s(QI, _R_DATE_ON_MEMBER),
        "adjudicated_date": _s(QI, _R_DATE_ON_MEMBER),
        "billed_amount": _s(SENSITIVE, _R_FINANCIAL),
        "allowed_amount": _s(SENSITIVE, _R_FINANCIAL),
        "paid_amount": _s(SENSITIVE, _R_FINANCIAL),
        "source_extracted_at": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
        "extract_batch_id": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
    },
    "ClaimLine": {
        "claim_line_id": _s(QI, _R_SURROGATE_KEY),
        "claim_id": _s(QI, _R_SURROGATE_KEY),
        "line_number": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "diagnosis_code": _s(
            PHI, _R_CLINICAL_FACT + " (this row's diagnosis code, joined to a specific claim)."
        ),
        "procedure_code": _s(
            PHI, _R_CLINICAL_FACT + " (this row's procedure code, joined to a specific claim)."
        ),
        "units": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "charge_amount": _s(SENSITIVE, _R_FINANCIAL),
        "allowed_amount": _s(SENSITIVE, _R_FINANCIAL),
        "paid_amount": _s(SENSITIVE, _R_FINANCIAL),
        "revenue_code": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
    },
    "Pharmacy": {
        "pharmacy_id": _s(NON_SENSITIVE, _R_BUSINESS_NON_SENSITIVE),
        "pharmacy_name": _s(NON_SENSITIVE, _R_BUSINESS_NON_SENSITIVE),
        "chain_name": _s(NON_SENSITIVE, _R_BUSINESS_NON_SENSITIVE),
        "city": _s(NON_SENSITIVE, "Pharmacy business location, not patient geography."),
        "state": _s(NON_SENSITIVE, _R_GEO_NON_SENSITIVE),
        "zip_code": _s(NON_SENSITIVE, "Pharmacy business zip code, not patient geography."),
        "npi": _s(PII, _R_PROVIDER_PII),
    },
    "Prescription": {
        "prescription_id": _s(QI, _R_SURROGATE_KEY),
        "member_id": _s(DI, _R_DIRECT_LINK),
        "pharmacy_id": _s(NON_SENSITIVE, _R_BUSINESS_NON_SENSITIVE),
        "prescriber_provider_id": _s(PII, _R_PROVIDER_PII),
        "ndc_code": _s(PHI, _R_CLINICAL_FACT + " (specific drug dispensed to this member)."),
        "drug_name": _s(PHI, _R_CLINICAL_FACT + " (specific drug dispensed to this member)."),
        "days_supply": _s(PHI, _R_CLINICAL_FACT + " (medication dosing detail)."),
        "quantity": _s(PHI, _R_CLINICAL_FACT + " (medication dosing detail)."),
        "fill_date": _s(QI, _R_DATE_ON_MEMBER),
        "refill_number": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "status": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
    },
    "Encounter": {
        "encounter_id": _s(QI, _R_SURROGATE_KEY),
        "member_id": _s(DI, _R_DIRECT_LINK),
        "provider_id": _s(PII, _R_PROVIDER_PII),
        "encounter_type": _s(PHI, _R_CLINICAL_FACT + " (type of care episode)."),
        "admit_date": _s(QI, _R_DATE_ON_MEMBER),
        "discharge_date": _s(QI, _R_DATE_ON_MEMBER),
        "facility_name": _s(
            QI,
            "Facility name, combined with dates, can narrow re-identification "
            "risk at small/specialized facilities.",
        ),
        "status": _s(NON_SENSITIVE, _R_OPERATIONAL_NON_SENSITIVE),
        "source_extracted_at": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
    },
    "LabResult": {
        "lab_result_id": _s(QI, _R_SURROGATE_KEY),
        "encounter_id": _s(QI, _R_SURROGATE_KEY),
        "member_id": _s(DI, _R_DIRECT_LINK),
        "test_code": _s(PHI, _R_CLINICAL_FACT + " (specific lab test ordered for this member)."),
        "test_name": _s(PHI, _R_CLINICAL_FACT + " (specific lab test ordered for this member)."),
        "result_value": _s(PHI, _R_CLINICAL_FACT + " (this member's specific lab result)."),
        "result_unit": _s(NON_SENSITIVE, "Unit of measure; meaningless without the result value."),
        "reference_range": _s(
            NON_SENSITIVE, "Population reference range for the test; not specific to this member."
        ),
        "abnormal_flag": _s(PHI, _R_CLINICAL_FACT + " (whether this member's result was abnormal)."),
        "collected_date": _s(QI, _R_DATE_ON_MEMBER),
        "resulted_date": _s(QI, _R_DATE_ON_MEMBER),
        "source": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
        "schema_version": _s(NON_SENSITIVE, _R_PIPELINE_METADATA),
    },
}


def lookup(entity: str, column: str) -> SchemaRule | None:
    """Return the authoritative schema rule for `(entity, column)`, or
    `None` if this column is not a literal field of the known entity
    (schema drift, a partner-specific abbreviation, or a genuinely
    unknown source) — in which case the caller should fall through to the
    rule-based pattern layer."""

    return SCHEMA_RULES.get(entity, {}).get(column)


__all__ = ["SCHEMA_RULES", "SchemaRule", "lookup"]
