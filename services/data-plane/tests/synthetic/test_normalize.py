"""`normalize_rows`/`normalize_estate_rows`: every row in a list ends up
with the same key set before being handed to `data_plane.subsetting.writer`
-- specifically the bug this module exists to prevent
(`write_pbm_extract`'s `csv.DictWriter` raising on a heterogeneous key
set derived from `rows[0].keys()` alone)."""

from __future__ import annotations

from data_plane.subsetting.estate_io import RawEstate
from data_plane.synthetic.normalize import normalize_estate_rows, normalize_rows


def test_normalize_rows_backfills_missing_keys_with_none() -> None:
    rows = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
    normalized = normalize_rows(rows)
    assert normalized[0] == {"a": 1, "b": 2, "c": None}
    assert normalized[1] == {"a": 3, "b": None, "c": 4}


def test_normalize_rows_is_a_noop_for_already_homogeneous_rows() -> None:
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    normalized = normalize_rows(rows)
    assert normalized == rows


def test_normalize_rows_handles_empty_list() -> None:
    assert normalize_rows([]) == []


def test_normalize_estate_rows_homogenizes_every_list_field() -> None:
    estate = RawEstate()
    estate.prescription = [
        {"prescription_id": "SYN-RX-SCEN-0000001", "data_provenance": "masked_production_like"},
        {
            "prescription_id": "SYN-RX-SCEN-0000002",
            "data_provenance": "synthetic",
            "scenario_type": "unusual_prescription_combinations",
        },
    ]
    normalize_estate_rows(estate)
    keys_per_row = [set(r.keys()) for r in estate.prescription]
    assert keys_per_row[0] == keys_per_row[1]
    assert estate.prescription[0]["scenario_type"] is None


def test_normalize_estate_rows_homogenizes_each_claim_batch_independently() -> None:
    estate = RawEstate()
    estate.claim.batches["claims-2024Q4"] = [{"claim_id": "A", "amount_paid": 1.0}]
    estate.claim.batches["synthetic-scenarios"] = [
        {"claim_id": "B", "paid_amount": 2.0, "scenario_type": "normal_claims"}
    ]
    normalize_estate_rows(estate)
    # Each batch is normalized independently -- schema drift between
    # batches (Phase 1's own `amount_paid`/`paid_amount` rename) is a
    # real, legitimate feature of this estate and must not be erased by
    # normalization forcing every batch onto one shared schema.
    assert set(estate.claim.batches["claims-2024Q4"][0].keys()) == {"claim_id", "amount_paid"}
    assert set(estate.claim.batches["synthetic-scenarios"][0].keys()) == {
        "claim_id",
        "paid_amount",
        "scenario_type",
    }
