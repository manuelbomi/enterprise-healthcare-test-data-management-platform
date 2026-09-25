"""Provenance tagging: `tag_row`/`tag_rows` (new rows) and
`tag_base_estate_as_masked_production_like` (existing base-estate rows,
including the ParquetDataset/PartnerLabFeedData nested shapes)."""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.subsetting.estate_io import read_estate
from data_plane.synthetic.provenance import (
    DATA_PROVENANCE_FIELD,
    SCENARIO_TYPE_FIELD,
    SYNTHETIC_BATCH_ID_FIELD,
    tag_base_estate_as_masked_production_like,
    tag_row,
    tag_rows,
)


def test_tag_row_adds_provenance_and_batch_id_without_mutating_input() -> None:
    original = {"member_id": "SYN-MBR-000001"}
    tagged = tag_row(original, provenance=DataProvenance.SYNTHETIC, batch_id="batch-1")
    assert original == {"member_id": "SYN-MBR-000001"}  # not mutated
    assert tagged[DATA_PROVENANCE_FIELD] == "synthetic"
    assert tagged[SYNTHETIC_BATCH_ID_FIELD] == "batch-1"
    assert SCENARIO_TYPE_FIELD not in tagged  # no scenario given


def test_tag_row_includes_scenario_type_when_given() -> None:
    tagged = tag_row(
        {"claim_id": "SYN-CLM-SCEN-0000001"},
        provenance=DataProvenance.NEGATIVE_TEST,
        batch_id="batch-1",
        scenario=ScenarioType.INVALID_CLAIM_REFERENCES,
    )
    assert tagged[SCENARIO_TYPE_FIELD] == "invalid_claim_references"
    assert tagged[DATA_PROVENANCE_FIELD] == "negative_test"


def test_tag_rows_tags_every_row() -> None:
    rows = [{"a": 1}, {"a": 2}]
    tagged = tag_rows(rows, provenance=DataProvenance.SYNTHETIC, batch_id="b")
    assert all(r[DATA_PROVENANCE_FIELD] == "synthetic" for r in tagged)
    assert len(tagged) == 2


def test_tag_base_estate_marks_every_entity_masked_production_like(real_estate: Path) -> None:
    estate = read_estate(real_estate)
    tag_base_estate_as_masked_production_like(estate, batch_id="run-1")

    assert estate.member and all(r[DATA_PROVENANCE_FIELD] == "masked_production_like" for r in estate.member)
    assert estate.coverage and all(r[DATA_PROVENANCE_FIELD] == "masked_production_like" for r in estate.coverage)
    assert estate.claim.all_rows()
    assert all(r[DATA_PROVENANCE_FIELD] == "masked_production_like" for r in estate.claim.all_rows())

    partner_rows = estate.lab_result_partner.all_rows()
    if partner_rows:
        assert all(r[DATA_PROVENANCE_FIELD] == "masked_production_like" for r in partner_rows)
    # v1 partner files: the field must also be present in `fieldnames`, or
    # writer.write_partner_lab_feed would silently drop it on write.
    for fieldnames, rows in estate.lab_result_partner.v1_files.values():
        if rows:
            assert DATA_PROVENANCE_FIELD in fieldnames


def test_tag_base_estate_is_idempotent(real_estate: Path) -> None:
    estate = read_estate(real_estate)
    tag_base_estate_as_masked_production_like(estate, batch_id="run-1")
    first_pass = [dict(r) for r in estate.member]

    tag_base_estate_as_masked_production_like(estate, batch_id="run-2-should-not-overwrite")
    assert estate.member == first_pass  # setdefault: second call changes nothing
