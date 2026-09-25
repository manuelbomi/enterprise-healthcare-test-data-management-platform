"""Integration tests: run `data_plane.subsetting.engine.run_subsetting`
end to end, for every one of the six required strategies, against a real
generated 'tiny' Phase 1 estate -- mirroring
`tests/masking/test_dataset_masker_against_real_estate.py`'s "exercise the
whole pipeline against real data, not synthetic unit fixtures" shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcare_tdm_contracts import IntegrityStatus, SubsetManifest, SubsettingStrategy

from data_plane.subsetting.engine import run_subsetting

STRATEGY_PARAMETERS: dict[SubsettingStrategy, dict[str, str]] = {
    SubsettingStrategy.PERCENTAGE: {"percentage": "25"},
    SubsettingStrategy.FIXED_POPULATION: {"count": "8"},
    SubsettingStrategy.STRATIFIED: {"strata_field": "gender", "per_stratum": "3"},
    SubsettingStrategy.DATE_WINDOW: {"start_date": "2000-01-01", "end_date": "2100-01-01"},
    SubsettingStrategy.BUSINESS_RULE: {
        "coverage_status": "active",
        "claim_status": "paid",
        "min_matching_claims": "1",
    },
    SubsettingStrategy.RISK_EDGE_CASE: {},
}


@pytest.mark.parametrize("strategy", list(SubsettingStrategy))
def test_every_strategy_produces_a_valid_referentially_closed_subset(
    real_estate: Path, tmp_path_factory: pytest.TempPathFactory, strategy: SubsettingStrategy
) -> None:
    out_dir = tmp_path_factory.mktemp(f"subset-{strategy.value}")
    result = run_subsetting(real_estate, out_dir, strategy, STRATEGY_PARAMETERS[strategy])

    manifest = result.manifest
    assert manifest.selection.strategy is strategy
    assert manifest.integrity_status in (IntegrityStatus.PASSED, IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS)
    assert manifest.integrity_status is not IntegrityStatus.FAILED

    # Every selected count is <= its source count -- a subset never grows
    # an entity beyond what the source estate actually had.
    for entity, selected in manifest.selected_counts.items():
        assert selected <= manifest.source_counts[entity]

    assert manifest.selected_counts["member"] >= 1
    assert manifest.estimated_subset_storage_bytes <= manifest.estimated_source_storage_bytes

    manifest_path = out_dir / "subset_manifest.json"
    assert manifest_path.exists()
    reloaded = SubsetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert reloaded == manifest


def test_fixed_population_subset_actually_shrinks_the_estate(real_estate: Path, tmp_path: Path) -> None:
    result = run_subsetting(
        real_estate, tmp_path / "out", SubsettingStrategy.FIXED_POPULATION, {"count": "5"}
    )
    manifest = result.manifest
    assert manifest.selected_counts["member"] == 5
    assert manifest.source_counts["member"] > 5
    assert manifest.selected_counts["claim"] <= manifest.source_counts["claim"]


def test_negative_test_run_is_reported_as_known_orphans_not_failure(real_estate: Path, tmp_path: Path) -> None:
    result = run_subsetting(
        real_estate,
        tmp_path / "out",
        SubsettingStrategy.FIXED_POPULATION,
        {"count": "20"},
        negative_test=True,
        negative_test_count=1,
    )
    manifest = result.manifest
    assert manifest.selection.negative_testing is True
    assert result.validation.passed is True
    if manifest.injected_negative_test_orphan_counts:
        assert manifest.integrity_status is IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS


def test_manifest_scale_profile_is_detected_from_the_estates_own_manifest(real_estate: Path, tmp_path: Path) -> None:
    result = run_subsetting(
        real_estate, tmp_path / "out", SubsettingStrategy.FIXED_POPULATION, {"count": "3"}
    )
    generator_manifest = json.loads((real_estate / "manifest.json").read_text(encoding="utf-8"))
    assert result.manifest.scale_profile == generator_manifest["scale_profile"] == "tiny"


def test_invalid_strategy_parameters_raise(real_estate: Path, tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        run_subsetting(real_estate, tmp_path / "out", SubsettingStrategy.FIXED_POPULATION, {})
