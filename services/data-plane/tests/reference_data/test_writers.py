"""Integration tests: write a full 'tiny' estate to disk and read every
format back with the tool a real consumer would use (sqlite3, pandas/
pyarrow for Parquet, plain json/csv for the rest), verifying the files
actually exist, are non-empty, and are loadable with the expected shape.
"""

from __future__ import annotations

import csv
import json
import sqlite3

import pandas as pd
import pytest

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES


@pytest.fixture(scope="module")
def written_tiny_estate(tmp_path_factory: pytest.TempPathFactory):
    output_root = tmp_path_factory.mktemp("synthetic-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    written = write_estate(estate, output_root)
    return estate, written


def test_manifest_written_and_matches_in_memory_counts(written_tiny_estate) -> None:
    estate, written = written_tiny_estate
    manifest = json.loads(written.manifest_path.read_text(encoding="utf-8"))

    assert manifest["scale_profile"] == "tiny"
    assert manifest["row_counts"]["member"] == len(estate.members)
    assert manifest["row_counts"]["claim"] == len(estate.claims)
    assert manifest["edge_cases"]["duplicate_persons_injected"] >= 1


def test_postgres_enrollment_system_readable_via_sqlite(written_tiny_estate) -> None:
    estate, written = written_tiny_estate
    assert written.enrollment_database_url.startswith("sqlite:///")
    db_path = written.enrollment_database_url.removeprefix("sqlite:///")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM member")
        (member_count,) = cur.fetchone()
        assert member_count == len(estate.members)

        cur.execute("SELECT COUNT(*) FROM coverage")
        (coverage_count,) = cur.fetchone()
        assert coverage_count > 0

        # Referential integrity: every coverage.plan_id must resolve.
        cur.execute(
            "SELECT COUNT(*) FROM coverage c LEFT JOIN plan p ON c.plan_id = p.plan_id "
            "WHERE p.plan_id IS NULL"
        )
        (unresolved,) = cur.fetchone()
        assert unresolved == 0

        # Orphan addresses (no FK) should exist: at least one member_id
        # in `address` that does not exist in `member`.
        cur.execute(
            "SELECT COUNT(*) FROM address a LEFT JOIN member m ON a.member_id = m.member_id "
            "WHERE m.member_id IS NULL"
        )
        (orphan_addresses,) = cur.fetchone()
        assert orphan_addresses >= 1
    finally:
        conn.close()


def test_claims_warehouse_parquet_readable_and_shows_schema_drift(written_tiny_estate) -> None:
    _, written = written_tiny_estate
    bucket_dir = written.output_root / "object_storage_claims_parquet" / "claims-warehouse"

    legacy_path = bucket_dir / "claim" / "batch=claims-2024Q4" / "part-0000.parquet"
    current_path = bucket_dir / "claim" / "batch=claims-2025Q1" / "part-0000.parquet"

    existing = [p for p in (legacy_path, current_path) if p.exists()]
    assert existing, "expected at least one claims batch to exist"

    for path in existing:
        df = pd.read_parquet(path)
        assert len(df) > 0

    if legacy_path.exists() and current_path.exists():
        legacy_df = pd.read_parquet(legacy_path)
        current_df = pd.read_parquet(current_path)
        assert "paid_amount" in legacy_df.columns
        assert "amount_paid" not in legacy_df.columns
        assert "amount_paid" in current_df.columns
        assert "paid_amount" not in current_df.columns
        assert "adjustment_reason_code" in current_df.columns

    claim_line_df = pd.read_parquet(bucket_dir / "claim_line" / "part-0000.parquet")
    assert len(claim_line_df) > 0
    diagnosis_df = pd.read_parquet(bucket_dir / "diagnosis" / "part-0000.parquet")
    assert len(diagnosis_df) > 0
    procedure_df = pd.read_parquet(bucket_dir / "procedure" / "part-0000.parquet")
    assert len(procedure_df) > 0


def test_clinical_data_lake_ndjson_readable(written_tiny_estate) -> None:
    _, written = written_tiny_estate
    bucket_dir = written.output_root / "s3_clinical_data_lake" / "clinical-data-lake"

    encounters_path = bucket_dir / "encounters" / "part-0000.ndjson"
    lines = encounters_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) > 0
    first = json.loads(lines[0])
    assert first["encounter_id"].startswith("SYN-ENC-")

    labs_path = bucket_dir / "lab_results" / "part-0000.ndjson"
    lab_lines = labs_path.read_text(encoding="utf-8").strip().splitlines()
    assert all(json.loads(line)["source"] == "ehr_primary" for line in lab_lines)


def test_pbm_extract_csv_readable(written_tiny_estate) -> None:
    _, written = written_tiny_estate
    container_dir = written.output_root / "adls_pbm_extract" / "pbm-extract"

    with (container_dir / "pharmacies" / "part-0000.csv").open(newline="", encoding="utf-8") as f:
        pharmacy_rows = list(csv.DictReader(f))
    assert len(pharmacy_rows) > 0
    assert pharmacy_rows[0]["pharmacy_id"].startswith("SYN-PHM-")

    with (container_dir / "prescriptions" / "part-0000.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        rx_rows = list(csv.DictReader(f))
    assert len(rx_rows) > 0


def test_partner_lab_feed_has_both_schema_versions(written_tiny_estate) -> None:
    _, written = written_tiny_estate
    partner_dir = written.output_root / "partner_lab_feed" / "inbound"

    v1_files = list((partner_dir / "v1_legacy_flat_file").glob("*.txt"))
    v2_files = list((partner_dir / "v2_api_json").glob("*.json"))
    assert v1_files, "expected at least one legacy v1 flat file"
    assert v2_files, "expected at least one v2 JSON payload file"

    v1_lines = v1_files[0].read_text(encoding="utf-8").strip().splitlines()
    assert v1_lines[0].startswith("pat_id|test_cd|")
    assert len(v1_lines) > 1  # header + at least one data row

    v2_payload = json.loads(v2_files[0].read_text(encoding="utf-8"))
    assert isinstance(v2_payload, list)
    assert len(v2_payload) > 0
    assert "member_id" in v2_payload[0]
    assert "late_arrival" in v2_payload[0]
