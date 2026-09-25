"""`ReferencePool`/`build_minimal_reference_pool`, and the engine-level
"top up only what's missing" behavior when a base estate is missing an
entire reference-table entity."""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import ScenarioType

from data_plane.subsetting.estate_io import RawEstate, read_estate
from data_plane.subsetting.writer import write_subset_estate
from data_plane.synthetic.engine import generate_synthetic_scenarios
from data_plane.synthetic.ids import ScenarioIdAllocator
from data_plane.synthetic.reference_pool import ReferencePool, build_minimal_reference_pool


def test_reference_pool_from_estate_reads_real_ids(real_estate: Path) -> None:
    estate = read_estate(real_estate)
    pool = ReferencePool.from_estate(estate)
    assert pool.is_complete()
    assert set(pool.provider_ids) == {p["provider_id"] for p in estate.provider}


def test_reference_pool_from_empty_estate_is_incomplete() -> None:
    pool = ReferencePool.from_estate(RawEstate())
    assert not pool.is_complete()


def test_build_minimal_reference_pool_appends_to_estate_and_is_complete() -> None:
    estate = RawEstate()
    id_alloc = ScenarioIdAllocator()
    pool = build_minimal_reference_pool(estate, id_alloc, "batch-1", rng_seed=1)
    assert pool.is_complete()
    assert estate.plan and estate.provider and estate.pharmacy and estate.diagnosis and estate.procedure
    # Every generated reference row is tagged SYNTHETIC.
    assert all(r["data_provenance"] == "synthetic" for r in estate.provider)
    # Reference rows are prerequisite fixtures, not one of the eleven
    # named scenarios -- no scenario_type tag.
    assert all("scenario_type" not in r for r in estate.provider)


def test_engine_tops_up_only_the_missing_entity_not_the_whole_pool(tmp_path: Path) -> None:
    """A base estate with real Plans but zero Providers should still use
    its own real Plan ids in generated scenario rows (Coverage.plan_id),
    while only Provider ids come from the fallback minimal pool."""

    base_estate = RawEstate()
    base_estate.plan = [
        {
            "plan_id": "SYN-PLN-0001",
            "plan_name": "Real Base Plan",
            "plan_type": "HMO",
            "metal_tier": "Gold",
            "market_segment": "Commercial",
        }
    ]
    # No providers, pharmacies, diagnoses, or procedures at all.
    base_dir = tmp_path / "base"
    write_subset_estate(base_estate, base_dir)

    result = generate_synthetic_scenarios(
        tmp_path / "out",
        [ScenarioType.NORMAL_CLAIMS],
        base_estate_dir=base_dir,
        seed=1,
    )
    reloaded = read_estate(tmp_path / "out")

    # The base estate's own real plan id is still used by generated
    # coverage rows (not silently replaced by a freshly generated one).
    plan_ids_used = {c["plan_id"] for c in reloaded.coverage}
    assert "SYN-PLN-0001" in plan_ids_used

    # Only one plan exists in the output -- the base one was NOT
    # discarded in favor of a fresh fallback plan.
    assert len(reloaded.plan) == 1

    # Providers, which WERE missing, come from the fallback pool.
    assert reloaded.provider
    assert result.manifest.mode == "augment"
