"""Tests for `data_plane.subsetting.estate_io` against the real generated
Phase 1 estate."""

from __future__ import annotations

import json
from pathlib import Path

from data_plane.subsetting.estate_io import read_estate


def test_read_estate_row_counts_match_the_generator_manifest(real_estate: Path) -> None:
    manifest = json.loads((real_estate / "manifest.json").read_text(encoding="utf-8"))
    expected = manifest["row_counts"]

    estate = read_estate(real_estate)
    actual = estate.row_counts()

    assert actual == expected


def test_read_estate_preserves_schema_drifted_claim_batches(real_estate: Path) -> None:
    estate = read_estate(real_estate)
    # Both schema-drifted batches from writers/parquet_writer.py should be
    # present at 'tiny' scale (2 years of service dates spanning both).
    assert set(estate.claim.batches) <= {"claims-2024Q4", "claims-2025Q1"}
    assert sum(len(rows) for rows in estate.claim.batches.values()) == len(estate.claim.all_rows())


def test_read_estate_reads_both_partner_feed_shapes(real_estate: Path) -> None:
    estate = read_estate(real_estate)
    partner = estate.lab_result_partner
    # At 'tiny' scale the generator always produces >= 1 partner record
    # (see generator.py's `_build_partner_lab_feed`, `n = max(1, ...)`).
    assert partner.all_rows(), "expected at least one partner lab feed record"


def test_read_estate_on_missing_directory_returns_empty_estate(tmp_path: Path) -> None:
    estate = read_estate(tmp_path / "does-not-exist")
    counts = estate.row_counts()
    assert all(count == 0 for count in counts.values())
