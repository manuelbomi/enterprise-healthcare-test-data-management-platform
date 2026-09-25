"""Each of the eleven required scenario generators, exercised directly:
correct provenance, schema-valid rows for the positive scenarios, and
provably-broken-in-the-documented-way rows for the negative-test ones."""

from __future__ import annotations

import random
from datetime import date

import pytest
from faker import Faker
from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.reference_data.domain import Claim, Coverage, LabResult, Member, Prescription
from data_plane.subsetting.estate_io import RawEstate
from data_plane.synthetic.ids import ScenarioIdAllocator
from data_plane.synthetic.reference_pool import build_minimal_reference_pool
from data_plane.synthetic.scenarios import (
    DEFAULT_SCENARIO_COUNTS,
    SCENARIO_GENERATORS,
    ScenarioContext,
    generate_boundary_dates,
    generate_duplicate_claims,
    generate_expired_coverage,
    generate_high_cost_claims,
    generate_invalid_claim_references,
    generate_missing_laboratory_values,
    generate_missing_provider,
    generate_normal_claims,
    generate_null_heavy_records,
    generate_unusual_prescription_combinations,
    generate_very_large_claim_histories,
    HIGH_COST_MIN,
)


@pytest.fixture()
def ctx() -> ScenarioContext:
    estate = RawEstate()
    id_alloc = ScenarioIdAllocator()
    faker = Faker("en_US")
    Faker.seed(1234)
    pool = build_minimal_reference_pool(estate, id_alloc, "test-batch", rng_seed=1234)
    return ScenarioContext(rng=random.Random(1234), faker=faker, id_alloc=id_alloc, pool=pool, batch_id="test-batch")


def test_every_scenario_type_has_a_registered_generator() -> None:
    assert set(SCENARIO_GENERATORS) == set(ScenarioType)
    assert set(DEFAULT_SCENARIO_COUNTS) == set(ScenarioType)


def test_normal_claims_are_schema_valid_and_synthetic(ctx: ScenarioContext) -> None:
    batch = generate_normal_claims(ctx, count=3)
    assert batch.provenance is DataProvenance.SYNTHETIC
    assert len(batch.rows["member"]) == 3
    assert len(batch.rows["claim"]) == 3
    for row in batch.rows["member"]:
        Member.model_validate(row)  # raises if schema-invalid
    for row in batch.rows["claim"]:
        Claim.model_validate(row)
        assert 50 <= row["billed_amount"] <= 5000


def test_high_cost_claims_exceed_threshold_and_are_synthetic(ctx: ScenarioContext) -> None:
    batch = generate_high_cost_claims(ctx, count=3)
    assert batch.provenance is DataProvenance.SYNTHETIC
    for row in batch.rows["claim"]:
        Claim.model_validate(row)
        assert row["billed_amount"] >= HIGH_COST_MIN


def test_duplicate_claims_are_exact_duplicates_and_negative_test(ctx: ScenarioContext) -> None:
    batch = generate_duplicate_claims(ctx, count=2)
    assert batch.provenance is DataProvenance.NEGATIVE_TEST
    claim_ids = [row["claim_id"] for row in batch.rows["claim"]]
    # Every claim_id appears exactly twice (the original + its duplicate).
    assert len(claim_ids) == 4
    assert len(set(claim_ids)) == 2
    for cid in set(claim_ids):
        duplicates = [row for row in batch.rows["claim"] if row["claim_id"] == cid]
        assert len(duplicates) == 2
        assert duplicates[0] == duplicates[1]


def test_invalid_claim_references_point_at_nothing_real(ctx: ScenarioContext) -> None:
    batch = generate_invalid_claim_references(ctx, count=2)
    assert batch.provenance is DataProvenance.NEGATIVE_TEST
    for row in batch.rows["claim"]:
        assert row["member_id"] not in ctx.pool.provider_ids  # sanity: not accidentally a real id
        assert "-NX-" in row["member_id"]
        assert "-NX-" in row["coverage_id"]
        # No member row was created for this dangling reference anywhere.
        assert "member" not in batch.rows or row["member_id"] not in {m["member_id"] for m in batch.rows.get("member", [])}


def test_expired_coverage_claim_is_after_coverage_term_date(ctx: ScenarioContext) -> None:
    batch = generate_expired_coverage(ctx, count=2)
    assert batch.provenance is DataProvenance.NEGATIVE_TEST
    coverage_by_id = {c["coverage_id"]: c for c in batch.rows["coverage"]}
    for row in batch.rows["claim"]:
        coverage = coverage_by_id[row["coverage_id"]]
        term = date.fromisoformat(coverage["term_date"])
        service = date.fromisoformat(row["service_date"])
        assert service > term
        Coverage.model_validate(coverage)


def test_missing_provider_has_null_or_dangling_provider(ctx: ScenarioContext) -> None:
    batch = generate_missing_provider(ctx, count=4)
    assert batch.provenance is DataProvenance.NEGATIVE_TEST
    seen_null = False
    seen_dangling = False
    for row in batch.rows["claim"]:
        if row["provider_id"] is None:
            seen_null = True
        else:
            assert row["provider_id"] not in ctx.pool.provider_ids
            assert "-NX-" in row["provider_id"]
            seen_dangling = True
    assert seen_null and seen_dangling
    for row in batch.rows["encounter"]:
        assert row["provider_id"] is None or "-NX-" in row["provider_id"]


def test_unusual_prescription_combinations_are_schema_valid_and_synthetic(ctx: ScenarioContext) -> None:
    batch = generate_unusual_prescription_combinations(ctx, count=2)
    assert batch.provenance is DataProvenance.SYNTHETIC
    assert len(batch.rows["prescription"]) == 4  # 2 members x 2 drugs each
    for row in batch.rows["prescription"]:
        Prescription.model_validate(row)
    # Each member's pair of fills share the same fill_date (same-day combination).
    by_member: dict[str, list[str]] = {}
    for row in batch.rows["prescription"]:
        by_member.setdefault(row["member_id"], []).append(row["fill_date"])
    for fill_dates in by_member.values():
        assert len(set(fill_dates)) == 1


def test_missing_laboratory_values_have_null_result_fields(ctx: ScenarioContext) -> None:
    batch = generate_missing_laboratory_values(ctx, count=2)
    assert batch.provenance is DataProvenance.SYNTHETIC
    for row in batch.rows["lab_result_ehr"]:
        LabResult.model_validate(row)
        assert row["result_value"] is None
        assert row["result_unit"] is None
        assert row["abnormal_flag"] is None
        assert row["resulted_date"] is None
        assert row["collected_date"] is not None


def test_boundary_dates_includes_leap_day_and_same_day_coverage(ctx: ScenarioContext) -> None:
    batch = generate_boundary_dates(ctx, count=1)
    assert batch.provenance is DataProvenance.SYNTHETIC
    service_dates = {row["service_date"] for row in batch.rows["claim"]}
    assert "2024-02-29" in service_dates  # leap day
    assert "2024-01-01" in service_dates  # year-boundary crossing
    same_day_coverages = [c for c in batch.rows["coverage"] if c["effective_date"] == c["term_date"]]
    assert same_day_coverages


def test_null_heavy_records_null_every_nullable_field(ctx: ScenarioContext) -> None:
    batch = generate_null_heavy_records(ctx, count=2)
    assert batch.provenance is DataProvenance.SYNTHETIC
    for row in batch.rows["member"]:
        Member.model_validate(row)
        assert row["date_of_birth"] is None
        assert row["gender"] is None
        assert row["ssn"] is None
    for row in batch.rows["claim"]:
        Claim.model_validate(row)
        assert row["coverage_id"] is None
        assert row["provider_id"] is None
        assert row["allowed_amount"] is None
        assert row["paid_amount"] is None


def test_very_large_claim_histories_produces_the_requested_volume(ctx: ScenarioContext) -> None:
    batch = generate_very_large_claim_histories(ctx, count=1, claims_per_member=25)
    assert batch.provenance is DataProvenance.SYNTHETIC
    assert len(batch.rows["member"]) == 1
    assert len(batch.rows["claim"]) == 25


@pytest.mark.parametrize("scenario", list(ScenarioType))
def test_every_generator_tags_every_row_with_a_valid_provenance(ctx: ScenarioContext, scenario: ScenarioType) -> None:
    """Every row produced by every generator carries a recognized
    `data_provenance` value and the run's `synthetic_batch_id` -- no row
    is ever left untagged. Individual entities within one scenario batch
    may legitimately carry a *different* provenance than the batch's own
    headline `ScenarioGenerationRecord.provenance` (e.g. `expired_coverage`
    tags its supporting Member row `SYNTHETIC` -- the member itself is a
    perfectly ordinary member -- while the Claim/Coverage rows that
    actually demonstrate the expired-coverage condition are tagged
    `NEGATIVE_TEST`); what must never happen is a row with no tag at all,
    or a claim/anchor entity not matching the batch's declared provenance.
    """

    generator = SCENARIO_GENERATORS[scenario]
    batch = generator(ctx, count=1)
    assert batch.rows, "generator produced no rows at all"

    valid_values = {DataProvenance.SYNTHETIC.value, DataProvenance.NEGATIVE_TEST.value}
    for entity, rows in batch.rows.items():
        for row in rows:
            assert row["data_provenance"] in valid_values, f"{entity} row missing/invalid data_provenance"
            assert row["synthetic_batch_id"] == "test-batch"

    # The entity that actually anchors this scenario (claim for most,
    # prescription/lab_result for the drug/lab scenarios) matches the
    # batch's own declared provenance -- that's the field a manifest
    # reader relies on.
    anchor_entity = "claim" if "claim" in batch.rows else next(iter(batch.rows))
    assert all(row["data_provenance"] == batch.provenance.value for row in batch.rows[anchor_entity])
