"""The eleven required scenario generators.

Each function below is a real, distinct generator producing one
`ScenarioBatch`: a self-contained set of rows (across whichever entities
the scenario needs) plus the metadata (`ScenarioType`, `DataProvenance`,
a human description, and the anchor IDs) `manifest.py` needs to record
what was produced.

## Provenance classification, and why

Per scenario, one of two `DataProvenance` values applies -- never a third
option, and never left ambiguous:

- `DataProvenance.SYNTHETIC` -- schema-conformant *and* referentially
  valid. Safe to use as a normal positive-path fixture by anything that
  doesn't specifically care this row was fabricated (an aggregate
  distribution check, a UI screenshot, a load-test corpus).
- `DataProvenance.NEGATIVE_TEST` -- deliberately, specifically broken in
  one documented way. Must only ever be consumed by a test that is
  exercising the corresponding rejection/validation path. A downstream
  certification pipeline (`ROADMAP.md` Phase 6) that ingests
  `NEGATIVE_TEST` rows as if they were normal data has a bug, and the
  provenance tag is exactly what lets it detect that.

| Scenario | Provenance | Why |
|---|---|---|
| `normal_claims` | SYNTHETIC | Ordinary, fully valid claims -- the baseline positive case. |
| `high_cost_claims` | SYNTHETIC | Valid claims, just statistically rare (catastrophic-cost tail) -- not broken, just underrepresented in a random subset. |
| `duplicate_claims` | NEGATIVE_TEST | Exercises dedup/idempotency handling; a real pipeline should detect and flag this, not treat it as two claims. |
| `invalid_claim_references` | NEGATIVE_TEST | A dangling `member_id`/`coverage_id` -- referential integrity is intentionally broken. |
| `expired_coverage` | NEGATIVE_TEST | A claim serviced after its coverage's `term_date` -- an impossible/should-be-rejected business state. |
| `missing_provider` | NEGATIVE_TEST | A claim/encounter with no resolvable provider (null, or a dangling reference) -- exercises "provider required" business rules. |
| `unusual_prescription_combinations` | SYNTHETIC | Valid prescriptions, just an unusual (interaction-risk-worthy) combination -- not a data-quality defect. |
| `missing_laboratory_values` | SYNTHETIC | A pending/uncollected lab result (`result_value=None`) is a common, schema-valid real-world state, not a broken record. |
| `boundary_dates` | SYNTHETIC | Dates at the edges of valid ranges (leap day, same-day coverage, year boundary) -- valid, just rare. |
| `null_heavy_records` | SYNTHETIC | Every nullable field actually null -- valid per schema, exercises null-handling without violating any constraint. |
| `very_large_claim_histories` | SYNTHETIC | A member with an unusually large claim volume -- valid data, a scale/pagination edge case, not a corruption. |

Every generator takes a `ScenarioContext` (shared RNG/Faker/ID
allocator/reference pool) and a `count` (how many scenario instances to
produce -- the exact meaning of "one instance" is documented per
function, since it varies: one claim for `normal_claims`, one member with
many claims for `very_large_claim_histories`, ...).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from faker import Faker
from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.reference_data.domain import (
    Claim,
    ClaimLine,
    Coverage,
    Encounter,
    LabResult,
    Member,
    MemberDemographics,
    Prescription,
)
from data_plane.synthetic.ids import ScenarioIdAllocator
from data_plane.synthetic.provenance import tag_row
from data_plane.synthetic.reference_pool import ReferencePool


def _iso(d: date) -> str:
    return d.isoformat()


@dataclass
class ScenarioContext:
    """Shared state every scenario generator draws from."""

    rng: random.Random
    faker: Faker
    id_alloc: ScenarioIdAllocator
    pool: ReferencePool
    batch_id: str


@dataclass
class ScenarioBatch:
    """One scenario generator's output."""

    scenario: ScenarioType
    provenance: DataProvenance
    description: str
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    anchor_ids: list[str] = field(default_factory=list)

    def row_counts(self) -> dict[str, int]:
        return {entity: len(rows) for entity, rows in self.rows.items() if rows}

    def add(self, entity: str, row: dict[str, Any]) -> None:
        self.rows.setdefault(entity, []).append(row)


def _new_member(
    ctx: ScenarioContext,
    *,
    effective: date,
    dob: date | None = None,
    gender: str | None = None,
    ssn: str | None = None,
) -> dict[str, Any]:
    member_id = ctx.id_alloc.next_id("MBR")
    return Member(
        member_id=member_id,
        first_name=ctx.faker.first_name(),
        last_name=ctx.faker.last_name(),
        date_of_birth=_iso(dob) if dob else _iso(ctx.faker.date_of_birth(minimum_age=0, maximum_age=95)),
        gender=gender if gender is not None else ctx.rng.choice(["M", "F", "U"]),
        ssn=ssn if ssn is not None else ctx.faker.ssn(),
        medical_record_number=f"SYN-MRN-SCEN-{member_id.rsplit('-', 1)[-1]}",
        effective_date=_iso(effective),
        extract_batch_id="synthetic-scenarios",
    ).model_dump()


def _new_coverage(
    ctx: ScenarioContext,
    *,
    member_id: str,
    effective: date,
    term_date: date | None = None,
    coverage_status: str = "active",
) -> dict[str, Any]:
    return Coverage(
        coverage_id=ctx.id_alloc.next_id("COV"),
        member_id=member_id,
        plan_id=ctx.rng.choice(ctx.pool.plan_ids),
        group_number=f"SYN-GRP-SCEN-{ctx.rng.randint(1000, 9999)}",
        effective_date=_iso(effective),
        term_date=_iso(term_date) if term_date else None,
        coverage_status=coverage_status,
    ).model_dump()


def _new_claim_with_lines(
    ctx: ScenarioContext,
    batch: ScenarioBatch,
    *,
    member_id: str,
    coverage_id: str | None,
    provider_id: str | None,
    service_date: date,
    billed_amount: float,
    status: str = "paid",
    num_lines: int = 2,
) -> str:
    claim_id = ctx.id_alloc.next_id("CLM", width=7)
    submitted = service_date + timedelta(days=ctx.rng.randint(1, 20))
    allowed = round(billed_amount * ctx.rng.uniform(0.5, 0.9), 2) if status != "denied" else None
    paid = round(allowed * ctx.rng.uniform(0.6, 1.0), 2) if allowed is not None else None

    claim = Claim(
        claim_id=claim_id,
        member_id=member_id,
        coverage_id=coverage_id,
        provider_id=provider_id,
        claim_type=ctx.rng.choice(["professional", "institutional", "pharmacy"]),
        status=status,
        service_date=_iso(service_date),
        submitted_date=_iso(submitted),
        adjudicated_date=_iso(submitted + timedelta(days=ctx.rng.randint(1, 10))) if status in ("paid", "denied") else None,
        billed_amount=billed_amount,
        allowed_amount=allowed,
        paid_amount=paid,
        source_extracted_at=_iso(submitted + timedelta(days=1)),
        extract_batch_id="synthetic-scenarios",
    ).model_dump()
    batch.add("claim", tag_row(claim, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

    for line_no in range(1, num_lines + 1):
        line = ClaimLine(
            claim_line_id=ctx.id_alloc.next_id("CLN", width=8),
            claim_id=claim_id,
            line_number=line_no,
            diagnosis_code=ctx.rng.choice(ctx.pool.diagnosis_codes) if ctx.pool.diagnosis_codes else None,
            procedure_code=ctx.rng.choice(ctx.pool.procedure_codes) if ctx.pool.procedure_codes else None,
            units=ctx.rng.randint(1, 3),
            charge_amount=round(billed_amount / num_lines, 2),
            allowed_amount=round((allowed or 0) / num_lines, 2) if allowed is not None else None,
            paid_amount=round((paid or 0) / num_lines, 2) if paid is not None else None,
        ).model_dump()
        batch.add(
            "claim_line",
            tag_row(line, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario),
        )

    return claim_id


# ---------------------------------------------------------------------------
# 1. normal_claims
# ---------------------------------------------------------------------------


def generate_normal_claims(ctx: ScenarioContext, count: int = 5) -> ScenarioBatch:
    """`count` ordinary, fully valid members-with-a-claim: realistic
    amounts ($50-$5,000), a real provider/coverage, 1-3 claim lines,
    a paid/denied/pending status mix. The positive-path baseline every
    other scenario is a deliberate deviation from."""

    batch = ScenarioBatch(
        scenario=ScenarioType.NORMAL_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count} ordinary, fully valid claim(s) with realistic amounts and a real provider/coverage.",
    )
    for _ in range(count):
        effective = ctx.faker.date_between(start_date="-3y", end_date="-30d")
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage = _new_coverage(ctx, member_id=member["member_id"], effective=effective)
        batch.add("coverage", tag_row(coverage, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        service_date = ctx.faker.date_between(start_date=effective, end_date="today")
        claim_id = _new_claim_with_lines(
            ctx,
            batch,
            member_id=member["member_id"],
            coverage_id=coverage["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids),
            service_date=service_date,
            billed_amount=round(ctx.rng.uniform(50, 5000), 2),
            status=ctx.rng.choice(["paid", "denied", "pending"]),
        )
        batch.anchor_ids.append(claim_id)
    return batch


# ---------------------------------------------------------------------------
# 2. high_cost_claims
# ---------------------------------------------------------------------------

HIGH_COST_MIN = 75_000.0
HIGH_COST_MAX = 350_000.0


def generate_high_cost_claims(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` catastrophic-cost claims (e.g. a NICU stay, a transplant):
    billed amounts between `HIGH_COST_MIN` and `HIGH_COST_MAX`, a real
    provider/coverage, otherwise fully valid. A random subset of a large
    estate may contain zero of these by chance; this scenario guarantees
    a QA engineer always has some to test cost-tier logic against."""

    batch = ScenarioBatch(
        scenario=ScenarioType.HIGH_COST_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count} catastrophic-cost claim(s), billed ${HIGH_COST_MIN:,.0f}-${HIGH_COST_MAX:,.0f}.",
    )
    for _ in range(count):
        effective = ctx.faker.date_between(start_date="-2y", end_date="-30d")
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage = _new_coverage(ctx, member_id=member["member_id"], effective=effective)
        batch.add("coverage", tag_row(coverage, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        service_date = ctx.faker.date_between(start_date=effective, end_date="today")
        claim_id = _new_claim_with_lines(
            ctx,
            batch,
            member_id=member["member_id"],
            coverage_id=coverage["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids),
            service_date=service_date,
            billed_amount=round(ctx.rng.uniform(HIGH_COST_MIN, HIGH_COST_MAX), 2),
            status="paid",
            num_lines=ctx.rng.randint(3, 8),
        )
        batch.anchor_ids.append(claim_id)
    return batch


# ---------------------------------------------------------------------------
# 3. duplicate_claims
# ---------------------------------------------------------------------------


def generate_duplicate_claims(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` claims that are each written TWICE -- byte-for-byte
    identical rows sharing the same `claim_id` -- simulating a source
    system replaying/redelivering the same extract. Negative-test: a
    correct pipeline must detect and collapse/flag this, not silently
    double-count billed/paid amounts."""

    batch = ScenarioBatch(
        scenario=ScenarioType.DUPLICATE_CLAIMS,
        provenance=DataProvenance.NEGATIVE_TEST,
        description=f"{count} claim(s) each duplicated (identical row, same claim_id, written twice).",
    )
    for _ in range(count):
        effective = ctx.faker.date_between(start_date="-2y", end_date="-30d")
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=DataProvenance.SYNTHETIC, batch_id=ctx.batch_id))
        coverage = _new_coverage(ctx, member_id=member["member_id"], effective=effective)
        batch.add("coverage", tag_row(coverage, provenance=DataProvenance.SYNTHETIC, batch_id=ctx.batch_id))

        service_date = ctx.faker.date_between(start_date=effective, end_date="today")
        claim_id = _new_claim_with_lines(
            ctx,
            batch,
            member_id=member["member_id"],
            coverage_id=coverage["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids),
            service_date=service_date,
            billed_amount=round(ctx.rng.uniform(100, 3000), 2),
        )
        # Re-append an exact duplicate of the claim row just written (not
        # the claim lines -- a source-system replay typically re-sends the
        # claim header; duplicating every line too would be a different,
        # noisier scenario).
        duplicate_of = next(r for r in batch.rows["claim"] if r["claim_id"] == claim_id)
        batch.add("claim", dict(duplicate_of))
        batch.anchor_ids.append(claim_id)
    return batch


# ---------------------------------------------------------------------------
# 4. invalid_claim_references
# ---------------------------------------------------------------------------


def generate_invalid_claim_references(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` claims referencing a `member_id` and `coverage_id` that do
    not exist anywhere in the dataset -- a dangling reference, injected
    on purpose (distinct from Phase 1's *incidental* orphans: this phase
    always uses the self-describing `SYN-...-SCEN-NX-...` sentinel shape,
    see `ids.py`). For negative-test / referential-integrity-validation
    fixtures only: "give me a claim referencing a member that doesn't
    exist" is this phase's own stated example use case."""

    batch = ScenarioBatch(
        scenario=ScenarioType.INVALID_CLAIM_REFERENCES,
        provenance=DataProvenance.NEGATIVE_TEST,
        description=f"{count} claim(s) with a member_id/coverage_id that references nothing in the dataset.",
    )
    for _ in range(count):
        dangling_member_id = ctx.id_alloc.dangling_id("MBR", "MEMBER")
        dangling_coverage_id = ctx.id_alloc.dangling_id("COV", "COVERAGE")
        service_date = ctx.faker.date_between(start_date="-1y", end_date="today")
        claim_id = _new_claim_with_lines(
            ctx,
            batch,
            member_id=dangling_member_id,
            coverage_id=dangling_coverage_id,
            provider_id=ctx.rng.choice(ctx.pool.provider_ids),
            service_date=service_date,
            billed_amount=round(ctx.rng.uniform(50, 2000), 2),
        )
        batch.anchor_ids.append(claim_id)
    return batch


# ---------------------------------------------------------------------------
# 5. expired_coverage
# ---------------------------------------------------------------------------


def generate_expired_coverage(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` claims with a `service_date` that falls AFTER the
    referenced Coverage's `term_date` -- an impossible/should-be-rejected
    business state (care rendered after coverage lapsed). Negative-test:
    exercises eligibility/coverage-window validation logic."""

    batch = ScenarioBatch(
        scenario=ScenarioType.EXPIRED_COVERAGE,
        provenance=DataProvenance.NEGATIVE_TEST,
        description=f"{count} claim(s) serviced after their coverage's term_date.",
    )
    for _ in range(count):
        effective = ctx.faker.date_between(start_date="-3y", end_date="-1y")
        term = effective + timedelta(days=ctx.rng.randint(90, 300))
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=DataProvenance.SYNTHETIC, batch_id=ctx.batch_id))
        coverage = _new_coverage(
            ctx, member_id=member["member_id"], effective=effective, term_date=term, coverage_status="terminated"
        )
        batch.add("coverage", tag_row(coverage, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        service_date = term + timedelta(days=ctx.rng.randint(1, 60))
        claim_id = _new_claim_with_lines(
            ctx,
            batch,
            member_id=member["member_id"],
            coverage_id=coverage["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids),
            service_date=service_date,
            billed_amount=round(ctx.rng.uniform(100, 4000), 2),
        )
        batch.anchor_ids.append(claim_id)
    return batch


# ---------------------------------------------------------------------------
# 6. missing_provider
# ---------------------------------------------------------------------------


def generate_missing_provider(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` claim+encounter pairs with no resolvable provider: half
    have `provider_id=None` (schema allows this -- a real "not yet
    assigned" state), half reference a dangling, nonexistent provider id.
    Both forms are real-world "missing provider" shapes; negative-test:
    exercises "provider required for adjudication" business rules that
    Pydantic's schema alone cannot enforce."""

    batch = ScenarioBatch(
        scenario=ScenarioType.MISSING_PROVIDER,
        provenance=DataProvenance.NEGATIVE_TEST,
        description=f"{count} claim(s)/encounter(s) with no resolvable provider (null or dangling provider_id).",
    )
    for i in range(count):
        effective = ctx.faker.date_between(start_date="-2y", end_date="-30d")
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=DataProvenance.SYNTHETIC, batch_id=ctx.batch_id))
        coverage = _new_coverage(ctx, member_id=member["member_id"], effective=effective)
        batch.add("coverage", tag_row(coverage, provenance=DataProvenance.SYNTHETIC, batch_id=ctx.batch_id))

        provider_id = None if i % 2 == 0 else ctx.id_alloc.dangling_id("PRV", "PROVIDER")
        service_date = ctx.faker.date_between(start_date=effective, end_date="today")
        claim_id = _new_claim_with_lines(
            ctx,
            batch,
            member_id=member["member_id"],
            coverage_id=coverage["coverage_id"],
            provider_id=provider_id,
            service_date=service_date,
            billed_amount=round(ctx.rng.uniform(50, 2000), 2),
        )
        batch.anchor_ids.append(claim_id)

        encounter = Encounter(
            encounter_id=ctx.id_alloc.next_id("ENC", width=7),
            member_id=member["member_id"],
            provider_id=provider_id,
            encounter_type="outpatient",
            admit_date=_iso(service_date),
            discharge_date=_iso(service_date),
            facility_name="SYN Scenario Clinic",
            status="completed",
            source_extracted_at=_iso(service_date + timedelta(days=1)),
        ).model_dump()
        batch.add("encounter", tag_row(encounter, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
    return batch


# ---------------------------------------------------------------------------
# 7. unusual_prescription_combinations
# ---------------------------------------------------------------------------

_INTERACTION_RISK_PAIRS = [
    ("SYN-NDC-00001", "Synthavastin 20mg", "SYN-NDC-00003", "Lisinoprilene 10mg"),
    ("SYN-NDC-00002", "Metforminex 500mg", "SYN-NDC-00006", "Albuterolate HFA"),
]


def generate_unusual_prescription_combinations(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` members each filling two flagged-as-interaction-risk drugs
    on the same day, plus an outlier days-supply/refill-number
    combination (e.g. a 90-day supply on a 9th refill) -- schema-valid,
    but the kind of combination a drug-interaction / utilization-review
    rule engine specifically needs fixtures for."""

    batch = ScenarioBatch(
        scenario=ScenarioType.UNUSUAL_PRESCRIPTION_COMBINATIONS,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count} member(s) with same-day interaction-risk drug combinations and outlier refill patterns.",
    )
    for i in range(count):
        effective = ctx.faker.date_between(start_date="-2y", end_date="-30d")
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        ndc_a, name_a, ndc_b, name_b = _INTERACTION_RISK_PAIRS[i % len(_INTERACTION_RISK_PAIRS)]
        fill_date = ctx.faker.date_between(start_date=effective, end_date="today")
        for ndc, name, refill in ((ndc_a, name_a, 0), (ndc_b, name_b, 8)):
            rx = Prescription(
                prescription_id=ctx.id_alloc.next_id("RX", width=7),
                member_id=member["member_id"],
                pharmacy_id=ctx.rng.choice(ctx.pool.pharmacy_ids),
                prescriber_provider_id=ctx.rng.choice(ctx.pool.provider_ids),
                ndc_code=ndc,
                drug_name=name,
                days_supply=90,
                quantity=round(ctx.rng.uniform(60, 90), 1),
                fill_date=_iso(fill_date),
                refill_number=refill,
                status="filled",
            ).model_dump()
            batch.add("prescription", tag_row(rx, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        batch.anchor_ids.append(member["member_id"])
    return batch


# ---------------------------------------------------------------------------
# 8. missing_laboratory_values
# ---------------------------------------------------------------------------


def generate_missing_laboratory_values(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` lab results ordered/collected but never resulted:
    `result_value`, `result_unit`, `abnormal_flag`, and `resulted_date`
    all null, only `collected_date` present. Schema-valid (every one of
    those fields is optional) -- a genuinely common real-world "pending"
    state, not a data-quality defect -- included so null-handling logic
    downstream of lab ingestion always has a fixture to exercise."""

    batch = ScenarioBatch(
        scenario=ScenarioType.MISSING_LABORATORY_VALUES,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count} lab result(s) collected but never resulted (result_value/unit/flag all null).",
    )
    for _ in range(count):
        effective = ctx.faker.date_between(start_date="-1y", end_date="-30d")
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        collected = ctx.faker.date_between(start_date=effective, end_date="today")
        lab = LabResult(
            lab_result_id=ctx.id_alloc.next_id("LAB", width=7),
            encounter_id=None,
            member_id=member["member_id"],
            test_code="SYN-LOINC-2345-7",
            test_name="Glucose",
            result_value=None,
            result_unit=None,
            reference_range="70-99",
            abnormal_flag=None,
            collected_date=_iso(collected),
            resulted_date=None,
            source="ehr_primary",
            schema_version="v2",
        ).model_dump()
        batch.add("lab_result_ehr", tag_row(lab, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        batch.anchor_ids.append(lab["lab_result_id"])
    return batch


# ---------------------------------------------------------------------------
# 9. boundary_dates
# ---------------------------------------------------------------------------


def generate_boundary_dates(ctx: ScenarioContext, count: int = 1) -> ScenarioBatch:
    """One coverage+claim set per boundary case (``count`` scales how many
    times the full set of boundary cases is repeated): same-day coverage
    (`effective_date == term_date`), a leap-day service date (Feb 29 on a
    leap year), a claim serviced exactly `today`, and a coverage that
    starts on Dec 31 and a claim serviced the very next day (Jan 1 of the
    following year) -- the classic off-by-one date-window bugs live at
    exactly these edges."""

    batch = ScenarioBatch(
        scenario=ScenarioType.BOUNDARY_DATES,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count}x the boundary-date case set (same-day coverage, leap day, today, year-end/year-start).",
    )
    for _ in range(max(1, count)):
        # Case A: coverage effective_date == term_date (a single covered day).
        same_day = ctx.faker.date_between(start_date="-2y", end_date="-30d")
        member_a = _new_member(ctx, effective=same_day)
        batch.add("member", tag_row(member_a, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage_a = _new_coverage(ctx, member_id=member_a["member_id"], effective=same_day, term_date=same_day)
        batch.add("coverage", tag_row(coverage_a, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        claim_a = _new_claim_with_lines(
            ctx, batch, member_id=member_a["member_id"], coverage_id=coverage_a["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids), service_date=same_day,
            billed_amount=round(ctx.rng.uniform(50, 500), 2), num_lines=1,
        )
        batch.anchor_ids.append(claim_a)

        # Case B: leap day service date (Feb 29, 2024 is a real leap year).
        leap_day = date(2024, 2, 29)
        member_b = _new_member(ctx, effective=date(2023, 1, 1))
        batch.add("member", tag_row(member_b, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage_b = _new_coverage(ctx, member_id=member_b["member_id"], effective=date(2023, 1, 1))
        batch.add("coverage", tag_row(coverage_b, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        claim_b = _new_claim_with_lines(
            ctx, batch, member_id=member_b["member_id"], coverage_id=coverage_b["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids), service_date=leap_day,
            billed_amount=round(ctx.rng.uniform(50, 500), 2), num_lines=1,
        )
        batch.anchor_ids.append(claim_b)

        # Case C: serviced exactly today.
        today = date.today()
        member_c = _new_member(ctx, effective=today - timedelta(days=365))
        batch.add("member", tag_row(member_c, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage_c = _new_coverage(ctx, member_id=member_c["member_id"], effective=today - timedelta(days=365))
        batch.add("coverage", tag_row(coverage_c, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        claim_c = _new_claim_with_lines(
            ctx, batch, member_id=member_c["member_id"], coverage_id=coverage_c["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids), service_date=today,
            billed_amount=round(ctx.rng.uniform(50, 500), 2), num_lines=1, status="pending",
        )
        batch.anchor_ids.append(claim_c)

        # Case D: coverage starts Dec 31, claim serviced Jan 1 of the next year.
        dec_31 = date(2023, 12, 31)
        jan_1 = date(2024, 1, 1)
        member_d = _new_member(ctx, effective=dec_31)
        batch.add("member", tag_row(member_d, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage_d = _new_coverage(ctx, member_id=member_d["member_id"], effective=dec_31)
        batch.add("coverage", tag_row(coverage_d, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        claim_d = _new_claim_with_lines(
            ctx, batch, member_id=member_d["member_id"], coverage_id=coverage_d["coverage_id"],
            provider_id=ctx.rng.choice(ctx.pool.provider_ids), service_date=jan_1,
            billed_amount=round(ctx.rng.uniform(50, 500), 2), num_lines=1,
        )
        batch.anchor_ids.append(claim_d)
    return batch


# ---------------------------------------------------------------------------
# 10. null_heavy_records
# ---------------------------------------------------------------------------


def generate_null_heavy_records(ctx: ScenarioContext, count: int = 3) -> ScenarioBatch:
    """`count` members with every nullable field actually null: no DOB,
    no gender, no SSN, no demographics, plus a claim with no coverage, no
    provider, no adjudicated_date, no allowed/paid amount. Every value is
    individually valid per the schema (all `| None` fields); the scenario
    is the *combination* -- a record that is maximally sparse, which
    tends to be exactly what breaks naive "assume every field is
    present" downstream code."""

    batch = ScenarioBatch(
        scenario=ScenarioType.NULL_HEAVY_RECORDS,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count} member(s)/claim(s) with every nullable field set to null.",
    )
    for _ in range(count):
        member_id = ctx.id_alloc.next_id("MBR")
        member = Member(
            member_id=member_id,
            first_name=ctx.faker.first_name(),
            last_name=ctx.faker.last_name(),
            date_of_birth=None,
            gender=None,
            ssn=None,
            medical_record_number=f"SYN-MRN-SCEN-{member_id.rsplit('-', 1)[-1]}",
            effective_date=_iso(ctx.faker.date_between(start_date="-2y", end_date="-30d")),
            term_date=None,
            extract_batch_id="synthetic-scenarios",
        ).model_dump()
        batch.add("member", tag_row(member, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        demographics = MemberDemographics(
            member_id=member_id,
            middle_name=None,
            race=None,
            ethnicity=None,
            preferred_language=None,
            marital_status=None,
            email=None,
            phone=None,
        ).model_dump()
        batch.add(
            "member_demographics",
            tag_row(demographics, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario),
        )

        service_date = ctx.faker.date_between(start_date="-1y", end_date="today")
        claim_id = ctx.id_alloc.next_id("CLM", width=7)
        claim = Claim(
            claim_id=claim_id,
            member_id=member_id,
            coverage_id=None,
            provider_id=None,
            claim_type=ctx.rng.choice(["professional", "institutional", "pharmacy"]),
            status="pending",
            service_date=_iso(service_date),
            submitted_date=_iso(service_date),
            adjudicated_date=None,
            billed_amount=round(ctx.rng.uniform(50, 1000), 2),
            allowed_amount=None,
            paid_amount=None,
            source_extracted_at=_iso(service_date),
            extract_batch_id="synthetic-scenarios",
        ).model_dump()
        batch.add("claim", tag_row(claim, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        batch.anchor_ids.append(claim_id)
    return batch


# ---------------------------------------------------------------------------
# 11. very_large_claim_histories
# ---------------------------------------------------------------------------


def generate_very_large_claim_histories(
    ctx: ScenarioContext, count: int = 1, claims_per_member: int = 250
) -> ScenarioBatch:
    """`count` member(s), each with `claims_per_member` claims (each with
    1-2 lines) spanning several years -- a volume/scale edge case a
    normally-sized subset would rarely produce, needed to test
    pagination, timeout handling, and UI performance against a single
    member with an unusually deep claim history."""

    batch = ScenarioBatch(
        scenario=ScenarioType.VERY_LARGE_CLAIM_HISTORIES,
        provenance=DataProvenance.SYNTHETIC,
        description=f"{count} member(s) each with {claims_per_member} claims (a claim-volume scale edge case).",
    )
    for _ in range(count):
        effective = date.today() - timedelta(days=365 * 5)
        member = _new_member(ctx, effective=effective)
        batch.add("member", tag_row(member, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))
        coverage = _new_coverage(ctx, member_id=member["member_id"], effective=effective)
        batch.add("coverage", tag_row(coverage, provenance=batch.provenance, batch_id=ctx.batch_id, scenario=batch.scenario))

        for _ in range(claims_per_member):
            service_date = ctx.faker.date_between(start_date=effective, end_date="today")
            _new_claim_with_lines(
                ctx,
                batch,
                member_id=member["member_id"],
                coverage_id=coverage["coverage_id"],
                provider_id=ctx.rng.choice(ctx.pool.provider_ids),
                service_date=service_date,
                billed_amount=round(ctx.rng.uniform(50, 2000), 2),
                num_lines=ctx.rng.randint(1, 2),
            )
        batch.anchor_ids.append(member["member_id"])
    return batch


SCENARIO_GENERATORS = {
    ScenarioType.NORMAL_CLAIMS: generate_normal_claims,
    ScenarioType.HIGH_COST_CLAIMS: generate_high_cost_claims,
    ScenarioType.DUPLICATE_CLAIMS: generate_duplicate_claims,
    ScenarioType.INVALID_CLAIM_REFERENCES: generate_invalid_claim_references,
    ScenarioType.EXPIRED_COVERAGE: generate_expired_coverage,
    ScenarioType.MISSING_PROVIDER: generate_missing_provider,
    ScenarioType.UNUSUAL_PRESCRIPTION_COMBINATIONS: generate_unusual_prescription_combinations,
    ScenarioType.MISSING_LABORATORY_VALUES: generate_missing_laboratory_values,
    ScenarioType.BOUNDARY_DATES: generate_boundary_dates,
    ScenarioType.NULL_HEAVY_RECORDS: generate_null_heavy_records,
    ScenarioType.VERY_LARGE_CLAIM_HISTORIES: generate_very_large_claim_histories,
}

DEFAULT_SCENARIO_COUNTS: dict[ScenarioType, int] = {
    ScenarioType.NORMAL_CLAIMS: 5,
    ScenarioType.HIGH_COST_CLAIMS: 3,
    ScenarioType.DUPLICATE_CLAIMS: 3,
    ScenarioType.INVALID_CLAIM_REFERENCES: 3,
    ScenarioType.EXPIRED_COVERAGE: 3,
    ScenarioType.MISSING_PROVIDER: 3,
    ScenarioType.UNUSUAL_PRESCRIPTION_COMBINATIONS: 3,
    ScenarioType.MISSING_LABORATORY_VALUES: 3,
    ScenarioType.BOUNDARY_DATES: 1,
    ScenarioType.NULL_HEAVY_RECORDS: 3,
    ScenarioType.VERY_LARGE_CLAIM_HISTORIES: 1,
}

__all__ = [
    "DEFAULT_SCENARIO_COUNTS",
    "HIGH_COST_MAX",
    "HIGH_COST_MIN",
    "SCENARIO_GENERATORS",
    "ScenarioBatch",
    "ScenarioContext",
    "generate_boundary_dates",
    "generate_duplicate_claims",
    "generate_expired_coverage",
    "generate_high_cost_claims",
    "generate_invalid_claim_references",
    "generate_missing_laboratory_values",
    "generate_missing_provider",
    "generate_normal_claims",
    "generate_null_heavy_records",
    "generate_unusual_prescription_combinations",
    "generate_very_large_claim_histories",
]
