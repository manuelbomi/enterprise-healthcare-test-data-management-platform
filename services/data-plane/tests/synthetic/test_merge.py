"""`merge_scenario_batch`: appends a `ScenarioBatch`'s rows into a
`RawEstate`, special-casing `claim` into its own dedicated Parquet batch."""

from __future__ import annotations

import pytest
from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.subsetting.estate_io import RawEstate
from data_plane.synthetic.merge import merge_scenario_batch
from data_plane.synthetic.provenance import SYNTHETIC_CLAIM_BATCH_NAME
from data_plane.synthetic.scenarios import ScenarioBatch


def test_merge_appends_plain_list_entities() -> None:
    estate = RawEstate()
    batch = ScenarioBatch(
        scenario=ScenarioType.NORMAL_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description="test",
        rows={"member": [{"member_id": "SYN-MBR-SCEN-000001"}]},
    )
    merge_scenario_batch(estate, batch)
    assert estate.member == [{"member_id": "SYN-MBR-SCEN-000001"}]


def test_merge_routes_claim_rows_into_the_dedicated_synthetic_batch() -> None:
    estate = RawEstate()
    estate.claim.batches["claims-2024Q4"] = [{"claim_id": "SYN-CLM-000001"}]
    batch = ScenarioBatch(
        scenario=ScenarioType.HIGH_COST_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description="test",
        rows={"claim": [{"claim_id": "SYN-CLM-SCEN-0000001"}]},
    )
    merge_scenario_batch(estate, batch)
    assert estate.claim.batches["claims-2024Q4"] == [{"claim_id": "SYN-CLM-000001"}]
    assert estate.claim.batches[SYNTHETIC_CLAIM_BATCH_NAME] == [{"claim_id": "SYN-CLM-SCEN-0000001"}]


def test_merge_appends_across_multiple_batches_into_the_same_claim_batch() -> None:
    estate = RawEstate()
    batch1 = ScenarioBatch(
        scenario=ScenarioType.NORMAL_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description="a",
        rows={"claim": [{"claim_id": "A"}]},
    )
    batch2 = ScenarioBatch(
        scenario=ScenarioType.DUPLICATE_CLAIMS,
        provenance=DataProvenance.NEGATIVE_TEST,
        description="b",
        rows={"claim": [{"claim_id": "B"}]},
    )
    merge_scenario_batch(estate, batch1)
    merge_scenario_batch(estate, batch2)
    assert len(estate.claim.batches[SYNTHETIC_CLAIM_BATCH_NAME]) == 2


def test_merge_rejects_an_unrecognized_entity_key() -> None:
    estate = RawEstate()
    batch = ScenarioBatch(
        scenario=ScenarioType.NORMAL_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description="test",
        rows={"not_a_real_entity": [{"x": 1}]},
    )
    with pytest.raises(ValueError, match="not_a_real_entity"):
        merge_scenario_batch(estate, batch)


def test_merge_skips_empty_row_lists() -> None:
    estate = RawEstate()
    batch = ScenarioBatch(
        scenario=ScenarioType.NORMAL_CLAIMS,
        provenance=DataProvenance.SYNTHETIC,
        description="test",
        rows={"member": []},
    )
    merge_scenario_batch(estate, batch)  # must not raise
    assert estate.member == []
