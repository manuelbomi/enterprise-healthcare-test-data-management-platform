"""Tests for the six anchor-selection strategies (`data_plane.subsetting.
selection`), against the real generated Phase 1 estate."""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcare_tdm_contracts import SubsettingStrategy

from data_plane.subsetting.estate_io import read_estate
from data_plane.subsetting.selection import (
    select_business_rule,
    select_date_window,
    select_fixed_population,
    select_percentage,
    select_population,
    select_risk_edge_case,
    select_stratified,
)


@pytest.fixture(scope="module")
def estate(real_estate: Path):
    return read_estate(real_estate)


def test_select_percentage_selects_roughly_the_requested_fraction(estate) -> None:
    total = len(estate.member)
    result = select_percentage(estate, percentage=50)
    assert result.member_ids <= {str(m["member_id"]) for m in estate.member}
    assert len(result.member_ids) == round(total * 0.5)


def test_select_percentage_is_deterministic_for_the_same_seed(estate) -> None:
    first = select_percentage(estate, percentage=30, seed=7)
    second = select_percentage(estate, percentage=30, seed=7)
    assert first.member_ids == second.member_ids


def test_select_percentage_rejects_out_of_range_values(estate) -> None:
    with pytest.raises(ValueError):
        select_percentage(estate, percentage=0)
    with pytest.raises(ValueError):
        select_percentage(estate, percentage=150)


def test_select_fixed_population_selects_exact_count(estate) -> None:
    result = select_fixed_population(estate, count=5)
    assert len(result.member_ids) == 5


def test_select_fixed_population_caps_at_available_population(estate) -> None:
    total = len(estate.member)
    result = select_fixed_population(estate, count=total + 10_000)
    assert len(result.member_ids) == total
    assert result.resolved_parameters["capped_at_available"] == "True"


def test_select_stratified_represents_every_stratum(estate) -> None:
    result = select_stratified(estate, strata_field="gender", per_stratum=3)
    genders = {str(m.get("gender")) for m in estate.member}
    selected_genders = {
        str(next(m for m in estate.member if str(m["member_id"]) == member_id).get("gender"))
        for member_id in result.member_ids
    }
    assert selected_genders == genders  # every stratum represented (tiny scale has >=3 per gender)


def test_select_date_window_only_selects_members_with_claims_in_range(estate) -> None:
    result = select_date_window(estate, start_date="1900-01-01", end_date="2100-01-01")
    claim_member_ids = {str(c["member_id"]) for c in estate.claim.all_rows()}
    assert result.member_ids <= claim_member_ids


def test_select_date_window_empty_range_selects_nothing(estate) -> None:
    result = select_date_window(estate, start_date="1900-01-01", end_date="1900-01-02")
    assert result.member_ids == set()


def test_select_date_window_rejects_inverted_range(estate) -> None:
    with pytest.raises(ValueError):
        select_date_window(estate, start_date="2025-06-01", end_date="2025-01-01")


def test_select_business_rule_only_selects_active_members(estate) -> None:
    result = select_business_rule(estate, coverage_status="active", claim_status="paid", min_matching_claims=1)
    active_ids = {c["member_id"] for c in estate.coverage if c.get("coverage_status") == "active"}
    assert result.member_ids <= active_ids


def test_select_business_rule_high_threshold_selects_fewer_members(estate) -> None:
    loose = select_business_rule(estate, min_matching_claims=1)
    strict = select_business_rule(estate, min_matching_claims=50)
    assert strict.member_ids <= loose.member_ids
    assert len(strict.member_ids) == 0


def test_select_risk_edge_case_finds_members_touching_known_edge_cases(estate) -> None:
    result = select_risk_edge_case(estate)
    # Phase 1's edge-case injection guarantees at least one hit per
    # category at every scale profile (reference_data/edge_cases.py's
    # `minimum=1` floor), so the risk pool must be non-empty.
    assert result.member_ids
    assert result.member_ids <= {str(m["member_id"]) for m in estate.member}


def test_select_risk_edge_case_max_members_caps_the_pool(estate, record_skip_guard_fired) -> None:
    full = select_risk_edge_case(estate)
    if len(full.member_ids) < 2:
        # Phase 18B (`docs/problems/problems_final_review.md` P3-9): make this loud,
        # not silent -- see `conftest.record_skip_guard_fired`.
        record_skip_guard_fired("risk pool too small at this seed/scale to test capping")
        pytest.skip("risk pool too small at this seed/scale to test capping")
    capped = select_risk_edge_case(estate, max_members=1)
    assert len(capped.member_ids) == 1
    assert capped.member_ids <= full.member_ids


def test_select_population_dispatches_every_strategy(estate) -> None:
    cases: dict[SubsettingStrategy, dict[str, str]] = {
        SubsettingStrategy.PERCENTAGE: {"percentage": "20"},
        SubsettingStrategy.FIXED_POPULATION: {"count": "5"},
        SubsettingStrategy.STRATIFIED: {"strata_field": "gender", "per_stratum": "2"},
        SubsettingStrategy.DATE_WINDOW: {"start_date": "2000-01-01", "end_date": "2100-01-01"},
        SubsettingStrategy.BUSINESS_RULE: {"min_matching_claims": "1"},
        SubsettingStrategy.RISK_EDGE_CASE: {},
    }
    for strategy, params in cases.items():
        result = select_population(estate, strategy, params)
        assert isinstance(result.member_ids, set)


def test_select_population_rejects_unknown_strategy(estate) -> None:
    with pytest.raises(ValueError):
        select_population(estate, "not-a-real-strategy", {})  # type: ignore[arg-type]
