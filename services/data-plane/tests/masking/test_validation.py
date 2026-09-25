"""Tests for `data_plane.masking.validation`."""

from __future__ import annotations

import pytest

from data_plane.masking.validation import (
    CollisionError,
    RawValueLeakedError,
    ReferentialIntegrityError,
    assert_no_collisions,
    assert_no_raw_values_leaked,
    assert_referential_integrity,
    validate_masking_run,
)


def test_referential_integrity_passes_for_consistent_mapping() -> None:
    samples = {
        ("postgres_enrollment", "member", "member_id"): {"SYN-MBR-000007": "TKN-AAAA"},
        # DELIBERATE, TEMPORARY Phase 12 release-gate proof (see
        # problems_phase_12.md): this second system's token for the
        # SAME real member ID now disagrees with the first
        # ("TKN-ZZZZ" vs "TKN-AAAA"), which is exactly the referential-
        # integrity violation assert_referential_integrity exists to
        # catch -- pushed to a scratch branch to confirm ci.yml's
        # data-quality-tests/release-gate jobs actually go red, then
        # reverted immediately after.
        ("object_storage_claims_parquet", "claim", "member_id"): {"SYN-MBR-000007": "TKN-ZZZZ"},
    }
    assert_referential_integrity(samples)  # does not raise


def test_referential_integrity_fails_for_inconsistent_mapping() -> None:
    samples = {
        ("postgres_enrollment", "member", "member_id"): {"SYN-MBR-000007": "TKN-AAAA"},
        ("partner_lab_feed", "lab_result", "pat_id"): {"SYN-MBR-000007": "TKN-BBBB"},
    }
    with pytest.raises(ReferentialIntegrityError):
        assert_referential_integrity(samples)


def test_no_raw_values_leaked_passes_when_absent() -> None:
    assert_no_raw_values_leaked(["TKN-AAAA,synthetic,data"], {"563-30-0335", "SYN-MBR-000007"})


def test_no_raw_values_leaked_detects_a_leak() -> None:
    with pytest.raises(RawValueLeakedError):
        assert_no_raw_values_leaked(["oops,563-30-0335,leaked"], {"563-30-0335"})


def test_no_raw_values_leaked_ignores_short_low_entropy_values() -> None:
    # A 2-character state code recurring by chance should not false-positive.
    assert_no_raw_values_leaked(["CA is a state"], {"CA"}, min_length=4)


def test_no_collisions_passes_for_injective_mapping() -> None:
    assert_no_collisions({"SYN-MBR-000001": "TKN-AAAA", "SYN-MBR-000002": "TKN-BBBB"})


def test_no_collisions_detects_a_collision() -> None:
    with pytest.raises(CollisionError):
        assert_no_collisions({"SYN-MBR-000001": "TKN-AAAA", "SYN-MBR-000002": "TKN-AAAA"})


def test_validate_masking_run_reports_multiple_failures_without_stopping_at_first() -> None:
    samples = {
        ("postgres_enrollment", "member", "member_id"): {
            "SYN-MBR-1": "TKN-A",
            "SYN-MBR-2": "TKN-A",  # collision
        },
        ("partner_lab_feed", "lab_result", "pat_id"): {"SYN-MBR-1": "TKN-Z"},  # inconsistent with above
    }
    report = validate_masking_run(linkage_samples=samples)
    assert report.passed is False
    assert len(report.failures) >= 2
    assert len(report.checks_run) >= 2


def test_validate_masking_run_passes_clean_input() -> None:
    samples = {
        ("postgres_enrollment", "member", "member_id"): {"SYN-MBR-1": "TKN-A"},
        ("adls_pbm_extract", "prescription", "member_id"): {"SYN-MBR-1": "TKN-A"},
    }
    report = validate_masking_run(
        linkage_samples=samples,
        masked_text_blobs=["TKN-A only, nothing raw here"],
        raw_values={"SYN-MBR-1"},
    )
    assert report.passed is True
