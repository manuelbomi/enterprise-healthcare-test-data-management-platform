"""Tests for `data_plane.subsetting.writer`: writing a closure result back
to disk must round-trip cleanly (read it back with `estate_io.read_estate`
and get the same row counts) and must be readable by the sibling
`discovery` subpackage's scanner -- proof a subset estate is a genuine
drop-in replacement for the full estate, not just superficially similar
files."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.discovery.scanner import scan_estate
from data_plane.subsetting.closure import build_closure
from data_plane.subsetting.estate_io import read_estate
from data_plane.subsetting.selection import select_fixed_population
from data_plane.subsetting.writer import write_subset_estate


@pytest.fixture(scope="module")
def subset_root(real_estate: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    estate = read_estate(real_estate)
    selection = select_fixed_population(estate, count=10)
    closure = build_closure(estate, selection.member_ids)
    out_root = tmp_path_factory.mktemp("subset-written")
    write_subset_estate(closure.selected, out_root)
    return out_root


def test_written_subset_round_trips_through_read_estate(real_estate: Path, subset_root: Path) -> None:
    estate = read_estate(real_estate)
    selection = select_fixed_population(estate, count=10)
    closure = build_closure(estate, selection.member_ids)

    round_tripped = read_estate(subset_root)
    assert round_tripped.row_counts() == closure.selected.row_counts()


def test_written_subset_is_readable_by_discovery_scanner(subset_root: Path) -> None:
    columns = scan_estate(subset_root)
    systems = {c.source_system for c in columns}
    assert systems == {
        "postgres_enrollment",
        "object_storage_claims_parquet",
        "s3_clinical_data_lake",
        "adls_pbm_extract",
        "partner_lab_feed",
    } or systems <= {
        "postgres_enrollment",
        "object_storage_claims_parquet",
        "s3_clinical_data_lake",
        "adls_pbm_extract",
        "partner_lab_feed",
    }
    assert columns, "expected the written subset to be scannable by discovery"


def test_writing_an_empty_estate_produces_no_files(tmp_path: Path) -> None:
    from data_plane.subsetting.estate_io import RawEstate

    written = write_subset_estate(RawEstate(), tmp_path / "empty-subset")
    assert written == []
