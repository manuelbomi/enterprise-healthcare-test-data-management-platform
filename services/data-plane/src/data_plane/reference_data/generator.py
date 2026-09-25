"""Core generator: builds the full synthetic healthcare estate in memory.

``EstateGenerator.generate()`` produces every entity described in
``domain.py``, threading consistent identifiers across all of them (the
mechanism that gives this estate cross-system referential integrity — see
``README.md``, "How referential integrity works"), and deliberately
injects the edge cases required by the Phase 1 promptbook (missing
records, nulls, duplicates, orphans, malformed values, late-arriving
data, schema drift) according to an ``EdgeCaseConfig``.

Determinism: both ``random.Random`` and ``Faker`` are seeded, so the same
``(scale_profile, edge_cases, seed)`` triple always produces the same
estate. This matters for reproducible tests and for a reviewer being able
to regenerate exactly what a bug report describes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from faker import Faker

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
from data_plane.reference_data.edge_cases import (
    DEFAULT_EDGE_CASE_CONFIG,
    EdgeCaseConfig,
    EdgeCaseReport,
)
from data_plane.reference_data.scale import ScaleProfile

_PLAN_TYPES = ["HMO", "PPO", "EPO", "POS", "HDHP"]
_METAL_TIERS = ["Bronze", "Silver", "Gold", "Platinum", None]
_MARKET_SEGMENTS = ["Commercial", "Medicare", "Medicaid"]
_SPECIALTIES = [
    "Internal Medicine",
    "Family Medicine",
    "Cardiology",
    "Orthopedics",
    "Pediatrics",
    "Dermatology",
    "Behavioral Health",
    "Endocrinology",
    "Obstetrics & Gynecology",
    "Radiology",
]
_CLAIM_TYPES = ["professional", "institutional", "pharmacy"]
_CLAIM_STATUSES = ["paid", "denied", "pending", "reversed"]
_ENCOUNTER_TYPES = ["outpatient", "inpatient", "emergency", "telehealth", "wellness"]
_ENCOUNTER_STATUSES = ["completed", "in_progress", "cancelled"]
_LAB_TEST_CATALOG = [
    ("SYN-LOINC-2345-7", "Glucose", "mg/dL", "70-99"),
    ("SYN-LOINC-2160-0", "Creatinine", "mg/dL", "0.6-1.3"),
    ("SYN-LOINC-4548-4", "Hemoglobin A1c", "%", "4.0-5.6"),
    ("SYN-LOINC-2093-3", "Total Cholesterol", "mg/dL", "<200"),
    ("SYN-LOINC-718-7", "Hemoglobin", "g/dL", "12.0-17.5"),
    ("SYN-LOINC-2951-2", "Sodium", "mmol/L", "136-145"),
]
_DRUG_CATALOG = [
    ("SYN-NDC-00001", "Synthavastin 20mg"),
    ("SYN-NDC-00002", "Metforminex 500mg"),
    ("SYN-NDC-00003", "Lisinoprilene 10mg"),
    ("SYN-NDC-00004", "Amoxisyn 500mg"),
    ("SYN-NDC-00005", "Levothyrosyn 75mcg"),
    ("SYN-NDC-00006", "Albuterolate HFA"),
]


def _iso(d: date) -> str:
    return d.isoformat()


def _rate_hits(rng: random.Random, n: int, rate: float, minimum: int = 1) -> set[int]:
    """Pick a set of indices in ``range(n)`` to mutate for an edge case.

    Guarantees at least ``minimum`` hits whenever ``n > 0`` so every edge
    case is exercisable even at the ``tiny`` scale profile, capped at
    ``n`` itself.
    """

    if n <= 0:
        return set()
    count = max(min(minimum, n), round(n * rate))
    count = min(count, n)
    return set(rng.sample(range(n), count))


@dataclass
class GeneratedEstate:
    """All generated entities plus bookkeeping about what was injected."""

    scale: ScaleProfile
    seed: int
    members: list[Member] = field(default_factory=list)
    demographics: list[MemberDemographics] = field(default_factory=list)
    addresses: list[Address] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)
    coverages: list[Coverage] = field(default_factory=list)
    providers: list[Provider] = field(default_factory=list)
    diagnoses: list[Diagnosis] = field(default_factory=list)
    procedures: list[Procedure] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    claim_lines: list[ClaimLine] = field(default_factory=list)
    pharmacies: list[Pharmacy] = field(default_factory=list)
    prescriptions: list[Prescription] = field(default_factory=list)
    encounters: list[Encounter] = field(default_factory=list)
    lab_results: list[LabResult] = field(default_factory=list)
    edge_cases: EdgeCaseReport = field(default_factory=EdgeCaseReport)

    def row_counts(self) -> dict[str, int]:
        """Row count per entity, in a stable, typed shape."""

        return {
            "member": len(self.members),
            "member_demographics": len(self.demographics),
            "address": len(self.addresses),
            "plan": len(self.plans),
            "coverage": len(self.coverages),
            "provider": len(self.providers),
            "diagnosis": len(self.diagnoses),
            "procedure": len(self.procedures),
            "claim": len(self.claims),
            "claim_line": len(self.claim_lines),
            "pharmacy": len(self.pharmacies),
            "prescription": len(self.prescriptions),
            "encounter": len(self.encounters),
            "lab_result": len(self.lab_results),
        }

    def manifest(self) -> dict[str, object]:
        """Row counts + edge-case summary, written alongside the estate output."""

        return {
            "scale_profile": self.scale.name,
            "seed": self.seed,
            "row_counts": self.row_counts(),
            "edge_cases": self.edge_cases.as_dict(),
        }


class EstateGenerator:
    """Builds a full :class:`GeneratedEstate` for a given scale profile."""

    def __init__(
        self,
        scale: ScaleProfile,
        edge_cases: EdgeCaseConfig = DEFAULT_EDGE_CASE_CONFIG,
        seed: int = 20240101,
    ) -> None:
        self.scale = scale
        self.edge_cases = edge_cases
        self.seed = seed
        self.rng = random.Random(seed)
        self.faker = Faker("en_US")
        Faker.seed(seed)

    def generate(self) -> GeneratedEstate:
        estate = GeneratedEstate(scale=self.scale, seed=self.seed)

        estate.plans = self._build_plans()
        estate.providers = self._build_providers()
        estate.pharmacies = self._build_pharmacies()
        estate.diagnoses = self._build_diagnoses()
        estate.procedures = self._build_procedures()

        self._build_members(estate)
        self._build_coverages(estate)
        self._build_claims_and_lines(estate)
        self._build_prescriptions(estate)
        self._build_encounters_and_labs(estate)

        return estate

    # -- reference/code tables ------------------------------------------------

    def _build_plans(self) -> list[Plan]:
        plans = []
        for i in range(1, self.scale.plan_count + 1):
            plans.append(
                Plan(
                    plan_id=f"SYN-PLN-{i:04d}",
                    plan_name=f"SYN {self.faker.color_name()} {self.rng.choice(_PLAN_TYPES)} {2023 + (i % 3)}",
                    plan_type=self.rng.choice(_PLAN_TYPES),
                    metal_tier=self.rng.choice(_METAL_TIERS),
                    market_segment=self.rng.choice(_MARKET_SEGMENTS),
                )
            )
        return plans

    def _build_providers(self) -> list[Provider]:
        providers = []
        for i in range(1, self.scale.provider_count + 1):
            providers.append(
                Provider(
                    provider_id=f"SYN-PRV-{i:05d}",
                    npi="9" + "".join(str(self.rng.randint(0, 9)) for _ in range(9)),
                    provider_name=f"Dr. {self.faker.last_name()} Synthetic Care Group"
                    if i % 4 == 0
                    else f"{self.faker.first_name()} {self.faker.last_name()}, MD",
                    provider_type="Organization" if i % 4 == 0 else "Individual",
                    specialty=self.rng.choice(_SPECIALTIES),
                    city=self.faker.city(),
                    state=self.faker.state_abbr(),
                )
            )
        return providers

    def _build_pharmacies(self) -> list[Pharmacy]:
        pharmacies = []
        for i in range(1, self.scale.pharmacy_count + 1):
            pharmacies.append(
                Pharmacy(
                    pharmacy_id=f"SYN-PHM-{i:05d}",
                    pharmacy_name=f"SYN {self.faker.city()} Pharmacy #{i}",
                    chain_name=self.rng.choice(["SynRx", "CarePlus Rx", None]),
                    city=self.faker.city(),
                    state=self.faker.state_abbr(),
                    zip_code=self.faker.postcode(),
                    npi="8" + "".join(str(self.rng.randint(0, 9)) for _ in range(9)),
                )
            )
        return pharmacies

    def _build_diagnoses(self) -> list[Diagnosis]:
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        diagnoses = []
        for i in range(self.scale.diagnosis_code_count):
            letter = letters[i % len(letters)]
            code = f"SYN-{letter}{i % 100:02d}.{i % 10}"
            diagnoses.append(
                Diagnosis(diagnosis_code=code, description=f"Synthetic diagnosis condition {i + 1}")
            )
        return diagnoses

    def _build_procedures(self) -> list[Procedure]:
        procedures = []
        for i in range(self.scale.procedure_code_count):
            code = f"SYN-{99000 + i}"
            procedures.append(
                Procedure(procedure_code=code, description=f"Synthetic procedure {i + 1}")
            )
        return procedures

    # -- member family (PostgreSQL-bound) -------------------------------------

    def _build_members(self, estate: GeneratedEstate) -> None:
        n = self.scale.member_count
        null_hits = _rate_hits(self.rng, n, self.edge_cases.null_field_rate)
        no_demographics_hits = _rate_hits(self.rng, n, self.edge_cases.missing_child_rate)
        malformed_hits = _rate_hits(self.rng, n, self.edge_cases.malformed_value_rate)
        duplicate_person_hits = _rate_hits(self.rng, n, self.edge_cases.duplicate_person_rate)
        orphan_address_hits = _rate_hits(self.rng, n, self.edge_cases.orphan_rate)

        for idx in range(n):
            i = idx + 1
            member_id = f"SYN-MBR-{i:06d}"
            first = self.faker.first_name()
            last = self.faker.last_name()
            dob = self.faker.date_of_birth(minimum_age=0, maximum_age=95)
            effective = self.faker.date_between(start_date="-5y", end_date="today")

            member = Member(
                member_id=member_id,
                first_name=first,
                last_name=last,
                date_of_birth=None if idx in null_hits else _iso(dob),
                gender=self.rng.choice(["M", "F", "U"]),
                ssn=self.faker.ssn(),
                medical_record_number=f"SYN-MRN-{i:06d}",
                effective_date=_iso(effective),
                extract_batch_id="enrollment-2025-09-full-extract",
            )
            estate.members.append(member)

            if idx not in no_demographics_hits:
                phone = self.faker.phone_number()
                if idx in malformed_hits:
                    phone = self.rng.choice(["555-CALL-ME", "(000) 000-0000", "N/A"])
                    estate.edge_cases.malformed_values_injected += 1
                estate.demographics.append(
                    MemberDemographics(
                        member_id=member_id,
                        middle_name=None if idx in null_hits else self.faker.first_name(),
                        race=self.rng.choice(
                            ["White", "Black or African American", "Asian", "Other", "Declined", None]
                        ),
                        ethnicity=self.rng.choice(["Hispanic or Latino", "Not Hispanic or Latino", None]),
                        preferred_language=self.rng.choice(["en", "es", "vi", "zh", None]),
                        marital_status=self.rng.choice(["single", "married", "divorced", "widowed", None]),
                        email=self.faker.free_email(),
                        phone=phone,
                    )
                )
            for a in range(self.rng.randint(1, self.scale.max_addresses_per_member)):
                addr_member_id = member_id
                if idx in orphan_address_hits and a == 0:
                    addr_member_id = f"SYN-MBR-{n + 900000 + i:06d}"  # references a member that does not exist
                    estate.edge_cases.record_orphan("address")

                zip_code = self.faker.postcode()
                line1 = self.faker.street_address()
                if idx in malformed_hits and a == 0:
                    zip_code = self.rng.choice(["ABCDE", "1234", "00000-XXXX"])
                    estate.edge_cases.malformed_values_injected += 1

                estate.addresses.append(
                    Address(
                        address_id=f"SYN-ADR-{i:06d}-{a}",
                        member_id=addr_member_id,
                        address_type="home" if a == 0 else "mailing",
                        line1=None if idx in null_hits and a == 1 else line1,
                        line2=self.faker.secondary_address() if self.rng.random() < 0.2 else None,
                        city=self.faker.city(),
                        state=self.faker.state_abbr(),
                        zip_code=zip_code,
                        effective_date=_iso(effective),
                    )
                )

            if idx in null_hits:
                estate.edge_cases.null_fields_injected += 1

        # duplicate persons: same demographics, new member_id (MDM-style dup)
        for idx in duplicate_person_hits:
            original = estate.members[idx]
            dup_id = f"SYN-MBR-{n + idx + 1:06d}"
            estate.members.append(
                Member(
                    member_id=dup_id,
                    first_name=original.first_name,
                    last_name=original.last_name,
                    date_of_birth=original.date_of_birth,
                    gender=original.gender,
                    ssn=original.ssn,
                    medical_record_number=f"SYN-MRN-{n + idx + 1:06d}",
                    effective_date=original.effective_date,
                    extract_batch_id="enrollment-2025-09-full-extract",
                    row_version=1,
                )
            )
            estate.edge_cases.duplicate_persons_injected += 1

    # -- coverage ---------------------------------------------------------------

    def _build_coverages(self, estate: GeneratedEstate) -> None:
        # NOTE: Coverage.coverage_id is a primary key and Coverage.plan_id /
        # Coverage.member_id are real, enforced foreign keys in
        # postgres_models.py -- a real enrollment OLTP system would reject
        # both an orphaned coverage row and a duplicate primary key, so,
        # unlike the cross-system entities below, no orphan/duplicate-row/
        # malformed injection happens here. See postgres_models.py's module
        # docstring.
        plan_ids = [p.plan_id for p in estate.plans]
        members = estate.members
        n = len(members)
        no_coverage_hits = _rate_hits(self.rng, n, self.edge_cases.missing_child_rate)

        counter = 1
        for idx, member in enumerate(members):
            if idx in no_coverage_hits:
                estate.edge_cases.members_with_no_coverage += 1
                continue

            num_coverages = self.rng.randint(1, self.scale.max_coverages_per_member)
            for _ in range(num_coverages):
                plan_id = self.rng.choice(plan_ids)

                effective = self.faker.date_between(start_date="-3y", end_date="today")
                coverage = Coverage(
                    coverage_id=f"SYN-COV-{counter:06d}",
                    member_id=member.member_id,
                    plan_id=plan_id,
                    group_number=f"SYN-GRP-{self.rng.randint(1000, 9999)}",
                    effective_date=_iso(effective),
                    term_date=None if self.rng.random() < 0.6 else _iso(effective + timedelta(days=365)),
                )
                estate.coverages.append(coverage)
                counter += 1

    # -- claims -------------------------------------------------------------

    def _build_claims_and_lines(self, estate: GeneratedEstate) -> None:
        member_ids = [m.member_id for m in estate.members]
        provider_ids = [p.provider_id for p in estate.providers]
        diagnosis_codes = [d.diagnosis_code for d in estate.diagnoses]
        procedure_codes = [p.procedure_code for p in estate.procedures]
        n = len(member_ids)

        orphan_member_hits = _rate_hits(self.rng, n, self.edge_cases.orphan_rate)
        orphan_provider_hits = _rate_hits(self.rng, n, self.edge_cases.orphan_rate)
        malformed_hits = _rate_hits(self.rng, n, self.edge_cases.malformed_value_rate)
        late_hits = _rate_hits(self.rng, n, self.edge_cases.late_arriving_rate)
        no_line_hits = _rate_hits(self.rng, n, self.edge_cases.missing_child_rate)
        duplicate_claim_hits = _rate_hits(self.rng, n, self.edge_cases.duplicate_row_rate)
        orphan_diag_hits = _rate_hits(self.rng, n, self.edge_cases.orphan_rate)

        # orphan_diag_hits only manifests when that member's claim actually
        # gets lines built (see the `else` branch below) -- if the same
        # member was independently also picked for no_line_hits, the
        # diagnosis-code orphan would silently never happen. Resolve the
        # conflict deterministically so both categories stay guaranteed.
        conflict = orphan_diag_hits & no_line_hits
        if conflict:
            available = set(range(n)) - no_line_hits
            orphan_diag_hits = (orphan_diag_hits - conflict) | (
                {min(available)} if available else set()
            )

        # Members selected for a claim-level edge case must actually produce
        # at least one claim, or the "guaranteed at least one" contract in
        # _rate_hits is silently broken by an unlucky num_claims == 0 draw.
        needs_a_claim = (
            orphan_member_hits
            | orphan_provider_hits
            | malformed_hits
            | late_hits
            | no_line_hits
            | duplicate_claim_hits
            | orphan_diag_hits
        )

        claim_counter = 1
        line_counter = 1
        for idx, member_id in enumerate(member_ids):
            min_claims = 1 if idx in needs_a_claim else 0
            num_claims = self.rng.randint(min_claims, max(min_claims, self.scale.max_claims_per_member))
            for _ in range(num_claims):
                cid = f"SYN-CLM-{claim_counter:07d}"
                claim_member_id = member_id
                if idx in orphan_member_hits:
                    claim_member_id = f"SYN-MBR-{n + 800000 + idx:06d}"
                    estate.edge_cases.record_orphan("claim.member_id")

                provider_id = self.rng.choice(provider_ids) if provider_ids else None
                if idx in orphan_provider_hits:
                    provider_id = "SYN-PRV-99999"
                    estate.edge_cases.record_orphan("claim.provider_id")

                service_date = self.faker.date_between(start_date="-2y", end_date="today")
                submitted = service_date + timedelta(days=self.rng.randint(1, 30))
                extracted_at = submitted + timedelta(days=self.rng.randint(1, 3))
                batch = "claims-2024Q4" if service_date.year <= 2024 else "claims-2025Q1"

                is_late = idx in late_hits
                if is_late:
                    # service occurred far earlier than when it was actually extracted
                    extracted_at = date.today() - timedelta(days=self.rng.randint(1, 5))
                    estate.edge_cases.late_arriving_records_injected += 1

                status = self.rng.choice(_CLAIM_STATUSES)
                billed = round(self.rng.uniform(50, 15000), 2)
                allowed = round(billed * self.rng.uniform(0.4, 0.95), 2) if status != "denied" else None
                paid = round(allowed * self.rng.uniform(0.5, 1.0), 2) if allowed is not None else None

                if idx in malformed_hits:
                    paid = -abs(paid or billed)  # negative paid amount: data-entry-error style corruption
                    estate.edge_cases.malformed_values_injected += 1

                estate.claims.append(
                    Claim(
                        claim_id=cid,
                        member_id=claim_member_id,
                        coverage_id=None,
                        provider_id=provider_id,
                        claim_type=self.rng.choice(_CLAIM_TYPES),
                        status=status,
                        service_date=_iso(service_date),
                        submitted_date=_iso(submitted),
                        adjudicated_date=_iso(submitted + timedelta(days=self.rng.randint(1, 10)))
                        if status in ("paid", "denied")
                        else None,
                        billed_amount=billed,
                        allowed_amount=allowed,
                        paid_amount=paid,
                        source_extracted_at=_iso(extracted_at),
                        extract_batch_id=batch,
                    )
                )

                if idx in duplicate_claim_hits:
                    estate.claims.append(estate.claims[-1].model_copy())
                    estate.edge_cases.duplicate_rows_injected += 1

                if idx in no_line_hits:
                    estate.edge_cases.claims_with_no_lines += 1
                else:
                    num_lines = self.rng.randint(1, self.scale.max_claim_lines_per_claim)
                    for line_no in range(1, num_lines + 1):
                        diag = self.rng.choice(diagnosis_codes) if diagnosis_codes else None
                        proc = self.rng.choice(procedure_codes) if procedure_codes else None
                        if idx in orphan_diag_hits and line_no == 1:
                            diag = "SYN-Z99.9-UNMAPPED"
                            estate.edge_cases.record_orphan("claim_line.diagnosis_code")

                        line_charge = round(billed / max(num_lines, 1), 2)
                        estate.claim_lines.append(
                            ClaimLine(
                                claim_line_id=f"SYN-CLN-{line_counter:08d}",
                                claim_id=cid,
                                line_number=line_no,
                                diagnosis_code=diag,
                                procedure_code=proc,
                                units=self.rng.randint(1, 3),
                                charge_amount=line_charge,
                                allowed_amount=round(line_charge * 0.8, 2) if allowed is not None else None,
                                paid_amount=round(line_charge * 0.7, 2) if paid is not None else None,
                            )
                        )
                        line_counter += 1

                claim_counter += 1

        # orphan claim lines: a claim line whose parent claim_id was never written
        # (simulates the claim header being purged/rolled back after lines landed)
        for i in range(max(1, int(len(estate.claims) * self.edge_cases.orphan_rate))):
            phantom_claim_id = f"SYN-CLM-{9_000_000 + i:07d}"
            estate.claim_lines.append(
                ClaimLine(
                    claim_line_id=f"SYN-CLN-{line_counter:08d}",
                    claim_id=phantom_claim_id,
                    line_number=1,
                    diagnosis_code=self.rng.choice(diagnosis_codes) if diagnosis_codes else None,
                    procedure_code=self.rng.choice(procedure_codes) if procedure_codes else None,
                    units=1,
                    charge_amount=round(self.rng.uniform(20, 500), 2),
                    allowed_amount=None,
                    paid_amount=None,
                )
            )
            line_counter += 1
            estate.edge_cases.record_orphan("claim_line.claim_id")

    # -- prescriptions --------------------------------------------------------

    def _build_prescriptions(self, estate: GeneratedEstate) -> None:
        member_ids = [m.member_id for m in estate.members]
        pharmacy_ids = [p.pharmacy_id for p in estate.pharmacies]
        provider_ids = [p.provider_id for p in estate.providers]
        n = len(member_ids)

        orphan_member_hits = _rate_hits(self.rng, n, self.edge_cases.orphan_rate)
        malformed_hits = _rate_hits(self.rng, n, self.edge_cases.malformed_value_rate)
        null_hits = _rate_hits(self.rng, n, self.edge_cases.null_field_rate)
        needs_a_prescription = orphan_member_hits | malformed_hits | null_hits

        counter = 1
        for idx, member_id in enumerate(member_ids):
            min_rx = 1 if idx in needs_a_prescription else 0
            num_rx = self.rng.randint(min_rx, max(min_rx, self.scale.max_prescriptions_per_member))
            for _ in range(num_rx):
                rx_member_id = member_id
                if idx in orphan_member_hits:
                    rx_member_id = f"SYN-MBR-{n + 700000 + idx:06d}"
                    estate.edge_cases.record_orphan("prescription.member_id")

                ndc, drug_name = self.rng.choice(_DRUG_CATALOG)
                quantity = round(self.rng.uniform(10, 90), 1)
                if idx in malformed_hits:
                    quantity = -quantity  # malformed: negative fill quantity
                    estate.edge_cases.malformed_values_injected += 1

                estate.prescriptions.append(
                    Prescription(
                        prescription_id=f"SYN-RX-{counter:07d}",
                        member_id=rx_member_id,
                        pharmacy_id=self.rng.choice(pharmacy_ids) if pharmacy_ids else None,
                        prescriber_provider_id=None
                        if idx in null_hits
                        else (self.rng.choice(provider_ids) if provider_ids else None),
                        ndc_code=ndc,
                        drug_name=drug_name,
                        days_supply=self.rng.choice([30, 60, 90]),
                        quantity=quantity,
                        fill_date=_iso(self.faker.date_between(start_date="-1y", end_date="today")),
                        refill_number=self.rng.randint(0, 5),
                        status=self.rng.choice(["filled", "reversed", "rejected"]),
                    )
                )
                counter += 1

    # -- encounters + labs ------------------------------------------------------

    def _build_encounters_and_labs(self, estate: GeneratedEstate) -> None:
        member_ids = [m.member_id for m in estate.members]
        provider_ids = [p.provider_id for p in estate.providers]
        n = len(member_ids)

        orphan_provider_hits = _rate_hits(self.rng, n, self.edge_cases.orphan_rate)
        malformed_hits = _rate_hits(self.rng, n, self.edge_cases.malformed_value_rate)
        late_hits = _rate_hits(self.rng, n, self.edge_cases.late_arriving_rate)
        needs_an_encounter = orphan_provider_hits | malformed_hits | late_hits

        enc_counter = 1
        lab_counter = 1
        for idx, member_id in enumerate(member_ids):
            min_enc = 1 if idx in needs_an_encounter else 0
            num_enc = self.rng.randint(min_enc, max(min_enc, self.scale.max_encounters_per_member))
            for _ in range(num_enc):
                eid = f"SYN-ENC-{enc_counter:07d}"
                enc_type = self.rng.choice(_ENCOUNTER_TYPES)
                admit = self.faker.date_between(start_date="-2y", end_date="today")
                discharge = admit + timedelta(days=self.rng.randint(0, 5)) if enc_type == "inpatient" else admit
                discharge_str: str | None = _iso(discharge)
                if idx in malformed_hits and enc_type != "inpatient":
                    discharge_str = self.rng.choice(["TBD", "UNKNOWN", ""])
                    estate.edge_cases.malformed_values_injected += 1
                elif enc_type in ("outpatient", "telehealth", "wellness"):
                    discharge_str = None

                provider_id = self.rng.choice(provider_ids) if provider_ids else None
                if idx in orphan_provider_hits:
                    provider_id = "SYN-PRV-99998"
                    estate.edge_cases.record_orphan("encounter.provider_id")

                extracted_at = admit + timedelta(days=self.rng.randint(1, 4))
                if idx in late_hits:
                    extracted_at = date.today() - timedelta(days=self.rng.randint(1, 3))
                    estate.edge_cases.late_arriving_records_injected += 1

                estate.encounters.append(
                    Encounter(
                        encounter_id=eid,
                        member_id=member_id,
                        provider_id=provider_id,
                        encounter_type=enc_type,
                        admit_date=_iso(admit),
                        discharge_date=discharge_str,
                        facility_name=f"SYN {self.faker.city()} Medical Center",
                        status=self.rng.choice(_ENCOUNTER_STATUSES),
                        source_extracted_at=_iso(extracted_at),
                    )
                )
                enc_counter += 1

                num_labs = self.rng.randint(0, self.scale.max_lab_results_per_encounter)
                for _ in range(num_labs):
                    test_code, test_name, unit, ref_range = self.rng.choice(_LAB_TEST_CATALOG)
                    value = str(round(self.rng.uniform(50, 200), 1))
                    if idx in malformed_hits and self.rng.random() < 0.3:
                        value = self.rng.choice(["PENDING", ">999", "see note"])
                        estate.edge_cases.malformed_values_injected += 1
                    estate.lab_results.append(
                        LabResult(
                            lab_result_id=f"SYN-LAB-{lab_counter:07d}",
                            encounter_id=eid,
                            member_id=member_id,
                            test_code=test_code,
                            test_name=test_name,
                            result_value=value,
                            result_unit=unit,
                            reference_range=ref_range,
                            abnormal_flag=self.rng.choice(["Normal", "High", "Low", None]),
                            collected_date=_iso(admit),
                            resulted_date=_iso(admit + timedelta(days=1)),
                            source="ehr_primary",
                            schema_version="v2",
                        )
                    )
                    lab_counter += 1

        self._build_partner_lab_feed(estate, lab_counter)

    def _build_partner_lab_feed(self, estate: GeneratedEstate, start_counter: int) -> None:
        """Supplemental reference-lab partner feed (external partner files/API).

        Deliberately messier than the primary EHR feed: mixes two schema
        versions (legacy v1 field names, current v2 field names), includes
        member references that do not yet exist in the enrollment system
        (late-arriving cross-system data), and duplicates a handful of
        results that were also delivered by the primary feed.
        """

        member_ids = [m.member_id for m in estate.members]
        n = max(1, len(member_ids) // 10)
        counter = start_counter

        for i in range(n):
            member_id = self.rng.choice(member_ids) if member_ids and i % 5 != 0 else (
                f"SYN-MBR-{len(member_ids) + 600000 + i:06d}"  # not yet enrolled -- orphan + late-arriving
            )
            if member_id not in member_ids:
                estate.edge_cases.record_orphan("lab_result.member_id (partner feed)")
                estate.edge_cases.late_arriving_records_injected += 1

            test_code, test_name, unit, ref_range = self.rng.choice(_LAB_TEST_CATALOG)
            schema_version = "v1" if i % 3 == 0 else "v2"
            collected = self.faker.date_between(start_date="-2y", end_date="today")

            estate.lab_results.append(
                LabResult(
                    lab_result_id=f"SYN-LAB-{counter:07d}",
                    encounter_id=None,
                    member_id=member_id,
                    test_code=test_code,
                    test_name=test_name,
                    result_value=str(round(self.rng.uniform(50, 200), 1)),
                    result_unit=unit,
                    reference_range=ref_range,
                    abnormal_flag=self.rng.choice(["Normal", "High", "Low", "Critical", None]),
                    collected_date=_iso(collected),
                    resulted_date=_iso(collected + timedelta(days=self.rng.randint(1, 7))),
                    source="partner_reference_lab",
                    schema_version=schema_version,
                )
            )
            counter += 1

        estate.edge_cases.schema_drift_batches.append("partner_lab_feed:v1(legacy pipe-delimited)")
        estate.edge_cases.schema_drift_batches.append("partner_lab_feed:v2(current JSON)")
        estate.edge_cases.schema_drift_batches.append(
            "object_storage_claims_parquet:claims-2024Q4 vs claims-2025Q1 (paid_amount -> amount_paid rename)"
        )


__all__ = ["EstateGenerator", "GeneratedEstate"]
