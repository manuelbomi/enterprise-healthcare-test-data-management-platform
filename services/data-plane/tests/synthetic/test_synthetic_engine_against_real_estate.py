"""Integration tests: `generate_synthetic_scenarios` end to end, in both
modes, against a real generated 'tiny' Phase 1 estate and a real Phase 4
subset of it -- mirroring
`tests/subsetting/test_engine_against_real_estate.py`'s "exercise the
whole pipeline against real data" shape, plus this phase's own specific
safety requirement: provable provenance separation and drop-in
readability of the output."""

from __future__ import annotations

from pathlib import Path

import pytest
from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.subsetting.estate_io import read_estate
from data_plane.synthetic.engine import generate_synthetic_scenarios
from data_plane.synthetic.provenance import SYNTHETIC_CLAIM_BATCH_NAME


def test_augment_mode_merges_scenarios_into_the_base_estate(subset_estate: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = generate_synthetic_scenarios(
        out_dir,
        list(ScenarioType),
        base_estate_dir=subset_estate,
        seed=7,
    )
    manifest = result.manifest
    assert manifest.mode == "augment"
    assert manifest.base_estate_dir == str(subset_estate)
    assert set(manifest.scenario_types()) == set(ScenarioType)

    # Every entity's total count is at least what the base subset had
    # (scenarios only add rows, in augment mode, never remove any).
    base_estate = read_estate(subset_estate)
    base_counts = base_estate.row_counts()
    for entity, base_count in base_counts.items():
        assert manifest.total_row_counts.get(entity, 0) >= base_count

    # Provenance rollup accounts for every row, with all three categories
    # represented (base rows are masked_production_like; both new
    # provenance categories appear because --all-scenarios requests both
    # SYNTHETIC and NEGATIVE_TEST scenarios).
    provenance_total = sum(manifest.provenance_row_counts.values())
    assert provenance_total == sum(manifest.total_row_counts.values())
    assert manifest.provenance_row_counts[DataProvenance.MASKED_PRODUCTION_LIKE.value] > 0
    assert manifest.provenance_row_counts[DataProvenance.SYNTHETIC.value] > 0
    assert manifest.provenance_row_counts[DataProvenance.NEGATIVE_TEST.value] > 0


def test_augmented_output_is_readable_back_by_estate_io(subset_estate: Path, tmp_path: Path) -> None:
    """A downstream consumer that only knows the five-source-system
    on-disk layout (discovery, masking, another subsetting run) can read
    this phase's output as a drop-in estate -- same guarantee Phase 4's
    writer already proves for its own output."""

    out_dir = tmp_path / "out"
    generate_synthetic_scenarios(out_dir, [ScenarioType.NORMAL_CLAIMS, ScenarioType.HIGH_COST_CLAIMS], base_estate_dir=subset_estate, seed=3)

    reloaded = read_estate(out_dir)
    assert reloaded.member  # non-empty
    assert SYNTHETIC_CLAIM_BATCH_NAME in reloaded.claim.batches

    # Every row -- old and new -- carries a recognized data_provenance.
    for row in reloaded.member:
        assert row["data_provenance"] in {"masked_production_like", "synthetic", "negative_test"}
    for row in reloaded.claim.all_rows():
        assert row["data_provenance"] in {"masked_production_like", "synthetic", "negative_test"}


def test_synthetic_scenario_ids_never_collide_with_base_estate_ids(subset_estate: Path, tmp_path: Path) -> None:
    """Proves the ID sub-range convention holds against real data: no
    scenario-generated Member ID equals (or looks like) a base-estate
    Member ID."""

    out_dir = tmp_path / "out"
    generate_synthetic_scenarios(out_dir, [ScenarioType.NORMAL_CLAIMS], base_estate_dir=subset_estate, seed=5)

    base_estate = read_estate(subset_estate)
    base_member_ids = {m["member_id"] for m in base_estate.member}

    reloaded = read_estate(out_dir)
    scenario_member_ids = {
        m["member_id"] for m in reloaded.member if m.get("data_provenance") == "synthetic"
    }
    assert scenario_member_ids  # the scenario actually produced members
    assert scenario_member_ids.isdisjoint(base_member_ids)
    assert all("-SCEN-" in mid for mid in scenario_member_ids)
    assert all("-SCEN-" not in mid for mid in base_member_ids)


def test_standalone_mode_has_zero_masked_production_like_rows(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = generate_synthetic_scenarios(out_dir, list(ScenarioType), base_estate_dir=None, seed=11)
    manifest = result.manifest
    assert manifest.mode == "standalone"
    assert manifest.provenance_row_counts.get(DataProvenance.MASKED_PRODUCTION_LIKE.value, 0) == 0
    assert manifest.provenance_row_counts[DataProvenance.SYNTHETIC.value] > 0
    assert manifest.provenance_row_counts[DataProvenance.NEGATIVE_TEST.value] > 0

    reloaded = read_estate(out_dir)
    all_rows = (
        reloaded.member
        + reloaded.coverage
        + reloaded.claim.all_rows()
        + reloaded.claim_line
    )
    assert all_rows
    assert all(row.get("data_provenance") != "masked_production_like" for row in all_rows)


def test_no_scenarios_requested_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        generate_synthetic_scenarios(tmp_path / "out", [], base_estate_dir=None)


def test_missing_base_estate_dir_falls_back_gracefully_when_none(tmp_path: Path) -> None:
    # base_estate_dir=None is standalone mode, not an error.
    result = generate_synthetic_scenarios(tmp_path / "out", [ScenarioType.NORMAL_CLAIMS], base_estate_dir=None)
    assert result.manifest.mode == "standalone"


def test_custom_counts_are_honored(tmp_path: Path) -> None:
    result = generate_synthetic_scenarios(
        tmp_path / "out",
        [ScenarioType.HIGH_COST_CLAIMS],
        base_estate_dir=None,
        counts={ScenarioType.HIGH_COST_CLAIMS: 7},
        seed=2,
    )
    record = next(s for s in result.manifest.scenarios if s.scenario is ScenarioType.HIGH_COST_CLAIMS)
    assert record.row_counts["claim"] == 7


def test_generation_is_deterministic_for_a_fixed_seed(tmp_path: Path) -> None:
    r1 = generate_synthetic_scenarios(tmp_path / "out1", [ScenarioType.NORMAL_CLAIMS], base_estate_dir=None, seed=99)
    r2 = generate_synthetic_scenarios(tmp_path / "out2", [ScenarioType.NORMAL_CLAIMS], base_estate_dir=None, seed=99)
    ids1 = sorted(m["member_id"] for m in read_estate(tmp_path / "out1").member)
    ids2 = sorted(m["member_id"] for m in read_estate(tmp_path / "out2").member)
    assert ids1 == ids2
    assert r1.manifest.total_row_counts == r2.manifest.total_row_counts
