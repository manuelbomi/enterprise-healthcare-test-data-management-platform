"""Tests for `data_plane.subsetting.negative_testing`, against the real
generated Phase 1 estate."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.subsetting.closure import build_closure
from data_plane.subsetting.estate_io import read_estate
from data_plane.subsetting.negative_testing import inject_negative_test_orphan
from data_plane.subsetting.validation import validate_subset


@pytest.fixture(scope="module")
def estate(real_estate: Path):
    return read_estate(real_estate)


def test_injection_removes_a_provider_and_breaks_its_referencing_claims(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    closure = build_closure(estate, all_member_ids)
    provider_count_before = len(closure.selected.provider)

    injected = inject_negative_test_orphan(closure, count=1)

    assert injected, "expected at least one selected provider to be removable at this scale"
    assert len(closure.selected.provider) == provider_count_before - 1
    for finding in injected:
        assert finding.category == "negative_test_injection"
        assert finding.relationship == "claim.provider_id"


def test_injected_dangling_reference_is_reported_not_hidden(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    closure = build_closure(estate, all_member_ids)
    injected = inject_negative_test_orphan(closure, count=1)

    report = validate_subset(closure, injected)
    assert report.passed is True  # intentional injection must not fail the run
    if injected:
        assert sum(report.injected_negative_test_orphan_counts.values()) == len(injected)


def test_injection_rejects_unsupported_relationship(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    closure = build_closure(estate, all_member_ids)
    with pytest.raises(ValueError):
        inject_negative_test_orphan(closure, relationship="member.demographics_id", count=1)


def test_injection_rejects_nonpositive_count(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    closure = build_closure(estate, all_member_ids)
    with pytest.raises(ValueError):
        inject_negative_test_orphan(closure, count=0)


def test_injection_on_empty_selection_returns_nothing(estate) -> None:
    closure = build_closure(estate, set())
    injected = inject_negative_test_orphan(closure, count=1)
    assert injected == []
