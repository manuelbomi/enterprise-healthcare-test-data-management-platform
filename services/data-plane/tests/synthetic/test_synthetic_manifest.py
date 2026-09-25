"""`build_manifest`/`count_provenance`: the durable, typed record of one
synthetic generation run, including lineage back to a Phase 4
`SubsetManifest` when the base estate has one."""

from __future__ import annotations

import json
from pathlib import Path

from healthcare_tdm_contracts import SubsetManifest

from data_plane.synthetic.manifest import count_provenance
from data_plane.subsetting.estate_io import RawEstate
from data_plane.synthetic.engine import generate_synthetic_scenarios
from healthcare_tdm_contracts import ScenarioType


def test_count_provenance_across_every_entity_shape() -> None:
    estate = RawEstate()
    estate.member = [{"data_provenance": "synthetic"}, {"data_provenance": "masked_production_like"}]
    estate.claim.batches["b"] = [{"data_provenance": "negative_test"}]
    estate.lab_result_partner.v2_files["f.json"] = [{"data_provenance": "synthetic"}]

    counts = count_provenance(estate)
    assert counts == {"synthetic": 2, "masked_production_like": 1, "negative_test": 1}


def test_count_provenance_ignores_untagged_rows() -> None:
    estate = RawEstate()
    estate.member = [{"member_id": "no-tag"}]
    assert count_provenance(estate) == {}


def test_manifest_resolves_lineage_to_base_subset_manifest(subset_estate: Path, tmp_path: Path) -> None:
    result = generate_synthetic_scenarios(
        tmp_path / "out",
        [ScenarioType.NORMAL_CLAIMS],
        base_estate_dir=subset_estate,
        seed=1,
    )
    base_manifest = SubsetManifest.model_validate_json(
        (subset_estate / "subset_manifest.json").read_text(encoding="utf-8")
    )
    assert result.manifest.base_subset_manifest_id == base_manifest.manifest_id


def test_manifest_has_no_lineage_in_standalone_mode(tmp_path: Path) -> None:
    result = generate_synthetic_scenarios(
        tmp_path / "out", [ScenarioType.NORMAL_CLAIMS], base_estate_dir=None, seed=1
    )
    assert result.manifest.base_subset_manifest_id is None
    assert result.manifest.base_estate_dir is None


def test_manifest_round_trips_through_json(tmp_path: Path) -> None:
    generate_synthetic_scenarios(
        tmp_path / "out", [ScenarioType.NORMAL_CLAIMS, ScenarioType.MISSING_PROVIDER], base_estate_dir=None, seed=1
    )
    manifest_path = tmp_path / "out" / "synthetic_generation_manifest.json"
    reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert reloaded["mode"] == "standalone"
    assert {s["scenario"] for s in reloaded["scenarios"]} == {"normal_claims", "missing_provider"}
