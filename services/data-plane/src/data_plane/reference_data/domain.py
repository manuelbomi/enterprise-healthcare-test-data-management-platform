"""Canonical in-memory entity shapes for the synthetic healthcare estate.

These are the fourteen entities required by the Phase 1 spec, plus
two small reference/code-vocabulary tables (``Diagnosis``, ``Procedure``)
that ``ClaimLine`` rows join against. They are deliberately **not**
`libs/contracts` models: `libs/contracts` holds cross-plane *interface*
contracts (job requests, audit events, masking policy...); these are
data-plane business/domain records describing the fake healthcare estate
itself, which is squarely a data-plane concern (see
``docs/adr/0002-python-project-layout.md`` and ``docs/adr/0003-plane-
separation.md``).

Design choices that matter for later phases
--------------------------------------------
- Every identifier uses an obviously-synthetic, prefixed format
  (``SYN-MBR-000001``, ``SYN-CLM-0000001``, ...) — never a format that
  could be mistaken for a real-world identifier. See
  ``DATA_GOVERNANCE.md`` Part A.
- Date/timestamp fields are modeled as ``str`` (ISO-8601 when clean)
  rather than ``datetime``/``date``. This is intentional: several edge
  cases this phase must model (malformed values, schema drift) are
  *type-valid-but-semantically-wrong* string values arriving from
  loosely-typed file/API extracts (e.g. ``"TBD"`` instead of a real
  discharge date). Using ``str`` lets the generator inject those values
  without fighting Pydantic validation, which mirrors how a real
  file-based extract would actually arrive. The six entities that are
  materialized into PostgreSQL (see ``postgres_models.py``) are converted
  to real ``Date``/``DateTime`` columns at write time, and the generator
  never injects malformed dates into that subset — a real OLTP schema
  would reject them, and that rejection-at-the-boundary is itself part of
  what this estate is meant to demonstrate (see ``README.md``,
  "Why Postgres data has no malformed values").
- Money fields are ``float | None`` rather than ``Decimal`` for the same
  reason: it keeps the generator and writers simple for a teaching
  repository. A production system would use fixed-point/``Decimal``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Entity(BaseModel):
    """Base class for every estate entity.

    ``extra="allow"`` because the schema-drift edge case (see
    ``edge_cases.py``) deliberately writes rows with renamed/added columns
    for some batches — the generator represents that as extra fields
    added onto an otherwise-normal record.
    """

    model_config = ConfigDict(extra="allow")


class Member(_Entity):
    member_id: str
    first_name: str
    last_name: str
    date_of_birth: str | None
    gender: str | None
    ssn: str | None
    medical_record_number: str
    effective_date: str
    term_date: str | None = None
    is_active: bool = True
    row_version: int = 1
    extract_batch_id: str = ""


class MemberDemographics(_Entity):
    member_id: str
    middle_name: str | None = None
    race: str | None = None
    ethnicity: str | None = None
    preferred_language: str | None = None
    marital_status: str | None = None
    email: str | None = None
    phone: str | None = None


class Address(_Entity):
    address_id: str
    member_id: str
    address_type: str
    line1: str | None
    line2: str | None = None
    city: str | None
    state: str | None
    zip_code: str | None
    country: str = "US"
    effective_date: str


class Plan(_Entity):
    plan_id: str
    plan_name: str
    plan_type: str
    metal_tier: str | None
    market_segment: str


class Coverage(_Entity):
    coverage_id: str
    member_id: str
    plan_id: str
    group_number: str
    effective_date: str
    term_date: str | None = None
    coverage_status: str = "active"
    row_version: int = 1


class Provider(_Entity):
    provider_id: str
    npi: str
    provider_name: str
    provider_type: str
    specialty: str
    city: str | None
    state: str | None
    is_active: bool = True


class Diagnosis(_Entity):
    diagnosis_code: str
    description: str
    code_system: str = "SYN-ICD-10"


class Procedure(_Entity):
    procedure_code: str
    description: str
    code_system: str = "SYN-CPT"


class Claim(_Entity):
    claim_id: str
    member_id: str
    coverage_id: str | None
    provider_id: str | None
    claim_type: str
    status: str
    service_date: str
    submitted_date: str
    adjudicated_date: str | None
    billed_amount: float
    allowed_amount: float | None
    paid_amount: float | None
    source_extracted_at: str
    extract_batch_id: str = ""


class ClaimLine(_Entity):
    claim_line_id: str
    claim_id: str
    line_number: int
    diagnosis_code: str | None
    procedure_code: str | None
    units: int
    charge_amount: float
    allowed_amount: float | None
    paid_amount: float | None
    revenue_code: str | None = None


class Pharmacy(_Entity):
    pharmacy_id: str
    pharmacy_name: str
    chain_name: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    npi: str


class Prescription(_Entity):
    prescription_id: str
    member_id: str
    pharmacy_id: str | None
    prescriber_provider_id: str | None
    ndc_code: str
    drug_name: str
    days_supply: int
    quantity: float
    fill_date: str
    refill_number: int
    status: str


class Encounter(_Entity):
    encounter_id: str
    member_id: str
    provider_id: str | None
    encounter_type: str
    admit_date: str
    discharge_date: str | None
    facility_name: str
    status: str
    source_extracted_at: str


class LabResult(_Entity):
    lab_result_id: str
    encounter_id: str | None
    member_id: str
    test_code: str
    test_name: str
    result_value: str | None
    result_unit: str | None
    reference_range: str | None
    abnormal_flag: str | None
    collected_date: str
    resulted_date: str | None
    source: str = "ehr_primary"
    schema_version: str = "v2"


__all__ = [
    "Address",
    "Claim",
    "ClaimLine",
    "Coverage",
    "Diagnosis",
    "Encounter",
    "LabResult",
    "Member",
    "MemberDemographics",
    "Pharmacy",
    "Plan",
    "Prescription",
    "Procedure",
    "Provider",
]
