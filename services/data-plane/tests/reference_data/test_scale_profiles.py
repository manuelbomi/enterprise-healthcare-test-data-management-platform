"""Tests for the configurable scale profiles.

These are fast, config-only tests -- they do not run the generator, they
just verify the profile parameters themselves are sane and strictly
increasing, per the Phase 1 spec requirement to "support
configurable scale profiles: tiny, developer, qa, performance."
"""

from __future__ import annotations

import pytest

from data_plane.reference_data.scale import SCALE_PROFILES, get_scale_profile


def test_all_four_named_profiles_exist() -> None:
    assert set(SCALE_PROFILES) == {"tiny", "developer", "qa", "performance"}


def test_member_counts_strictly_increase_with_scale() -> None:
    order = ["tiny", "developer", "qa", "performance"]
    counts = [SCALE_PROFILES[name].member_count for name in order]
    assert counts == sorted(counts)
    assert len(set(counts)) == len(counts)  # strictly increasing, no ties


def test_tiny_profile_is_small_enough_for_fast_ci() -> None:
    tiny = SCALE_PROFILES["tiny"]
    assert tiny.member_count <= 100
    assert tiny.approx_total_rows() < 2000


def test_performance_profile_is_the_largest() -> None:
    perf = SCALE_PROFILES["performance"]
    for name, profile in SCALE_PROFILES.items():
        if name != "performance":
            assert perf.approx_total_rows() > profile.approx_total_rows()


def test_get_scale_profile_unknown_name_raises_with_helpful_message() -> None:
    with pytest.raises(KeyError, match="tiny"):
        get_scale_profile("does-not-exist")
