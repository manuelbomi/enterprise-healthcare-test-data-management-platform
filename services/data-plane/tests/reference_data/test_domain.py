"""Unit tests for the canonical domain entity shapes.

Confirms every entity can be constructed with the minimal realistic shape
the generator produces, and that the "allow extra fields" contract
(needed for the schema-drift edge case) actually works.
"""

from __future__ import annotations

from data_plane.reference_data.domain import (
    Address,
    Claim,
    ClaimLine,
    Coverage,
    Diagnosis,
    Encounter,
    LabResult,
    Member,
    MemberDemographics,
    Pharmacy,
    Plan,
    Prescription,
    Procedure,
    Provider,
)


def test_member_round_trip() -> None:
    member = Member(
        member_id="SYN-MBR-000001",
        first_name="Testy",
        last_name="Synth",
        date_of_birth="1980-01-01",
        gender="F",
        ssn="000-00-0000",
        medical_record_number="SYN-MRN-000001",
        effective_date="2024-01-01",
    )
    assert member.member_id.startswith("SYN-MBR-")
    assert Member.model_validate(member.model_dump()) == member


def test_member_allows_none_date_of_birth_for_null_edge_case() -> None:
    member = Member(
        member_id="SYN-MBR-000002",
        first_name="Nully",
        last_name="Synth",
        date_of_birth=None,
        gender=None,
        ssn=None,
        medical_record_number="SYN-MRN-000002",
        effective_date="2024-01-01",
    )
    assert member.date_of_birth is None


def test_entity_allows_extra_fields_for_schema_drift() -> None:
    """Schema-drift batches add unexpected columns (see writers/parquet_writer.py);
    the domain layer must not reject them."""

    claim = Claim(
        claim_id="SYN-CLM-0000001",
        member_id="SYN-MBR-000001",
        coverage_id=None,
        provider_id="SYN-PRV-00001",
        claim_type="professional",
        status="paid",
        service_date="2024-01-01",
        submitted_date="2024-01-05",
        adjudicated_date="2024-01-10",
        billed_amount=100.0,
        allowed_amount=80.0,
        paid_amount=70.0,
        source_extracted_at="2024-01-11",
        adjustment_reason_code="A1",  # not declared on Claim -- must be allowed
    )
    assert claim.model_dump()["adjustment_reason_code"] == "A1"


def test_all_fourteen_plus_reference_entities_instantiate() -> None:
    """Smoke-instantiate every entity required by the Phase 1 promptbook
    (14 named entities + the two reference/code tables)."""

    MemberDemographics(member_id="SYN-MBR-000001")
    Address(
        address_id="SYN-ADR-000001-0",
        member_id="SYN-MBR-000001",
        address_type="home",
        line1="1 Fake St",
        city="Faketown",
        state="CA",
        zip_code="90000",
        effective_date="2024-01-01",
    )
    Plan(
        plan_id="SYN-PLN-0001",
        plan_name="SYN Gold PPO",
        plan_type="PPO",
        metal_tier="Gold",
        market_segment="Commercial",
    )
    Provider(
        provider_id="SYN-PRV-00001",
        npi="9000000001",
        provider_name="Dr. Synth",
        provider_type="Individual",
        specialty="Internal Medicine",
        city="Faketown",
        state="CA",
    )
    Coverage(
        coverage_id="SYN-COV-000001",
        member_id="SYN-MBR-000001",
        plan_id="SYN-PLN-0001",
        group_number="SYN-GRP-1000",
        effective_date="2024-01-01",
    )
    Diagnosis(diagnosis_code="SYN-E11.9", description="Synthetic condition")
    Procedure(procedure_code="SYN-99213", description="Synthetic procedure")
    ClaimLine(
        claim_line_id="SYN-CLN-00000001",
        claim_id="SYN-CLM-0000001",
        line_number=1,
        diagnosis_code="SYN-E11.9",
        procedure_code="SYN-99213",
        units=1,
        charge_amount=50.0,
        allowed_amount=40.0,
        paid_amount=35.0,
    )
    Pharmacy(
        pharmacy_id="SYN-PHM-00001",
        pharmacy_name="SYN Pharmacy",
        chain_name=None,
        city="Faketown",
        state="CA",
        zip_code="90000",
        npi="8000000001",
    )
    Prescription(
        prescription_id="SYN-RX-0000001",
        member_id="SYN-MBR-000001",
        pharmacy_id="SYN-PHM-00001",
        prescriber_provider_id="SYN-PRV-00001",
        ndc_code="SYN-NDC-00001",
        drug_name="Synthavastin 20mg",
        days_supply=30,
        quantity=30.0,
        fill_date="2024-01-01",
        refill_number=0,
        status="filled",
    )
    Encounter(
        encounter_id="SYN-ENC-0000001",
        member_id="SYN-MBR-000001",
        provider_id="SYN-PRV-00001",
        encounter_type="outpatient",
        admit_date="2024-01-01",
        discharge_date="2024-01-01",
        facility_name="SYN Medical Center",
        status="completed",
        source_extracted_at="2024-01-02",
    )
    LabResult(
        lab_result_id="SYN-LAB-0000001",
        encounter_id="SYN-ENC-0000001",
        member_id="SYN-MBR-000001",
        test_code="SYN-LOINC-2345-7",
        test_name="Glucose",
        result_value="90",
        result_unit="mg/dL",
        reference_range="70-99",
        abnormal_flag="Normal",
        collected_date="2024-01-01",
        resulted_date="2024-01-02",
    )
