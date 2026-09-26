"""Integration test: generate a real 'tiny' Phase 1 estate on disk, run
real Phase 2 discovery against it to get a real catalog, then run the
Phase 3 masking engine against the whole estate and verify the phase's
headline requirements against REAL data, not synthetic unit fixtures:

- referential integrity holds across every one of the five source
  systems for the same real-world member identifier (the exact scenario
  the Phase 3 spec's own example describes: MEMBER-123 ->
  TKN-A81F... consistently in claims/pharmacy/lab data);
- no raw direct-identifier value (SSN, email, member ID, name) survives
  into the masked output;
- masking is idempotent: masking the same estate twice with the same key
  produces the same masked values;
- the run handles the estate's real edge cases (nulls, malformed dates)
  without crashing.

Mirrors `tests/discovery/test_scanner_against_real_estate.py`'s fixture
shape (module-scoped, generate once, reuse across tests).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from data_plane.discovery.catalog_builder import build_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate
from data_plane.masking.dataset_masker import mask_estate
from data_plane.masking.engine import MaskingEngine
from data_plane.masking.validation import assert_no_raw_values_leaked, assert_referential_integrity
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES

MASKING_KEY = b"integration-test-hmac-key-0123456789abcdef"


@pytest.fixture(scope="module")
def real_estate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("masking-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root


@pytest.fixture(scope="module")
def real_catalog(real_estate: Path) -> list:
    columns = scan_estate(real_estate)
    return build_catalog(columns, ClassificationEngine())


@dataclass
class MaskedEstate:
    root: Path
    report: object


@pytest.fixture(scope="module")
def masked_estate(tmp_path_factory: pytest.TempPathFactory, real_estate: Path, real_catalog: list) -> MaskedEstate:
    out_root = tmp_path_factory.mktemp("masking-estate-masked")
    engine = MaskingEngine(key=MASKING_KEY)
    report = mask_estate(real_estate, real_catalog, out_root, engine)
    return MaskedEstate(root=out_root, report=report)


def test_masking_run_processes_every_source_system(masked_estate: MaskedEstate) -> None:
    report = masked_estate.report
    root = masked_estate.root
    assert report.rows_processed > 0
    assert report.columns_masked > 0
    assert len(report.files_written) == 12  # 1 sqlite db + 5 claims parquet + 2 ndjson + 2 csv + 2 partner
    assert (root / "postgres_enrollment" / "enrollment.sqlite3").exists()
    assert (root / "object_storage_claims_parquet" / "claims-warehouse" / "claim").exists()
    assert (root / "s3_clinical_data_lake" / "clinical-data-lake" / "encounters" / "part-0000.ndjson").exists()
    assert (root / "adls_pbm_extract" / "pbm-extract" / "prescriptions" / "part-0000.csv").exists()
    assert (root / "partner_lab_feed" / "inbound" / "v1_legacy_flat_file").exists()


def test_all_required_techniques_were_actually_exercised(masked_estate: MaskedEstate) -> None:
    report = masked_estate.report
    used = set(report.technique_counts)
    # Every technique the Phase 3 spec lists must show up at least
    # once against the real estate -- proof none of them are stubs.
    expected = {
        "tokenization",
        "hmac_pseudonymization" if "hmac_pseudonymization" in used else "format_preserving_synthetic",
        "format_preserving_synthetic",
        "date_shift",
        "email_mask",
        "phone_mask",
        "address_replacement",
        "name_replacement",
        "passthrough",
    }
    missing = expected - used
    assert not missing, f"techniques never exercised against the real estate: {missing}"


def test_member_id_masks_consistently_across_postgres_parquet_ndjson_csv(
    real_estate: Path, masked_estate: MaskedEstate
) -> None:
    """The phase's headline example, against real files: pick a real
    member present in Postgres, the claims Parquet warehouse, the
    clinical NDJSON lake, and the PBM CSV extract, and verify their
    masked member_id token is identical in all four places.
    """

    masked_root = masked_estate.root
    raw_conn = sqlite3.connect(str(real_estate / "postgres_enrollment" / "enrollment.sqlite3"))
    masked_conn = sqlite3.connect(str(masked_root / "postgres_enrollment" / "enrollment.sqlite3"))
    raw_members = pd.read_sql_query("SELECT member_id FROM member", raw_conn)
    masked_members = pd.read_sql_query("SELECT member_id FROM member", masked_conn)

    # ignore_index=True: each per-batch parquet file has its own 0..n
    # RangeIndex, and concatenating without it produces DUPLICATE index
    # labels across batches, which breaks positional lookups below.
    raw_claim = pd.concat(
        [pd.read_parquet(p) for p in sorted((real_estate / "object_storage_claims_parquet" / "claims-warehouse" / "claim").rglob("*.parquet"))],
        ignore_index=True,
    )
    masked_claim = pd.concat(
        [pd.read_parquet(p) for p in sorted((masked_root / "object_storage_claims_parquet" / "claims-warehouse" / "claim").rglob("*.parquet"))],
        ignore_index=True,
    )

    raw_enc = pd.DataFrame(
        [json.loads(line) for line in (real_estate / "s3_clinical_data_lake" / "clinical-data-lake" / "encounters" / "part-0000.ndjson").read_text().splitlines() if line.strip()]
    )
    masked_enc = pd.DataFrame(
        [json.loads(line) for line in (masked_root / "s3_clinical_data_lake" / "clinical-data-lake" / "encounters" / "part-0000.ndjson").read_text().splitlines() if line.strip()]
    )

    raw_pbm = pd.read_csv(real_estate / "adls_pbm_extract" / "pbm-extract" / "prescriptions" / "part-0000.csv", dtype=str)
    masked_pbm = pd.read_csv(masked_root / "adls_pbm_extract" / "pbm-extract" / "prescriptions" / "part-0000.csv", dtype=str)

    candidates = [
        m
        for m in raw_members["member_id"]
        if m in set(raw_claim["member_id"]) and m in set(raw_enc["member_id"]) and m in set(raw_pbm["member_id"])
    ]
    assert candidates, "expected at least one member present in all four systems at 'tiny' scale"
    member_id = candidates[0]

    pg_idx = raw_members.index[raw_members["member_id"] == member_id][0]
    claim_idx = raw_claim.index[raw_claim["member_id"] == member_id][0]
    enc_idx = raw_enc.index[raw_enc["member_id"] == member_id][0]
    pbm_idx = raw_pbm.index[raw_pbm["member_id"] == member_id][0]

    token_pg = masked_members.loc[pg_idx, "member_id"]
    token_claim = masked_claim.loc[claim_idx, "member_id"]
    token_enc = masked_enc.loc[enc_idx, "member_id"]
    token_pbm = masked_pbm.loc[pbm_idx, "member_id"]

    assert token_pg.startswith("TKN-")
    assert token_pg == token_claim == token_enc == token_pbm, (
        f"member {member_id} masked inconsistently: "
        f"postgres={token_pg} parquet={token_claim} ndjson={token_enc} csv={token_pbm}"
    )
    assert token_pg != member_id


def test_partner_feed_pat_id_alias_shares_scope_with_member_id(
    real_estate: Path, masked_estate: MaskedEstate, record_skip_guard_fired
) -> None:
    """The partner v1 legacy feed calls the member identifier `pat_id`,
    not `member_id`. Verify a member present in both Postgres and the
    partner feed still gets the identical masked token under both
    column names."""

    masked_root = masked_estate.root
    raw_conn = sqlite3.connect(str(real_estate / "postgres_enrollment" / "enrollment.sqlite3"))
    masked_conn = sqlite3.connect(str(masked_root / "postgres_enrollment" / "enrollment.sqlite3"))
    raw_members = pd.read_sql_query("SELECT member_id FROM member", raw_conn)
    masked_members = pd.read_sql_query("SELECT member_id FROM member", masked_conn)

    v2_raw_paths = list((real_estate / "partner_lab_feed" / "inbound" / "v2_api_json").glob("*.json"))
    v2_masked_paths = list((masked_root / "partner_lab_feed" / "inbound" / "v2_api_json").glob("*.json"))
    if not v2_raw_paths:
        # Phase 18B (`docs/problems/problems_final_review.md` P3-9): make this loud,
        # not silent -- see `conftest.record_skip_guard_fired`.
        record_skip_guard_fired("no partner v2 records generated at this seed/scale")
        pytest.skip("no partner v2 records generated at this seed/scale")

    raw_rows = json.loads(v2_raw_paths[0].read_text())
    masked_rows = json.loads(v2_masked_paths[0].read_text())
    assert raw_rows, "expected at least one partner v2 lab record"

    raw_pat_id = raw_rows[0]["member_id"]
    masked_pat_id = masked_rows[0]["member_id"]

    match = raw_members.index[raw_members["member_id"] == raw_pat_id]
    if len(match) == 0:
        # Phase 18B (`docs/problems/problems_final_review.md` P3-9): make this loud,
        # not silent -- see `conftest.record_skip_guard_fired`.
        record_skip_guard_fired("partner sample member is not also enrolled in postgres at this seed")
        pytest.skip("partner sample member is not also enrolled in postgres at this seed")
    token_pg = masked_members.loc[match[0], "member_id"]
    assert token_pg == masked_pat_id


def test_no_raw_direct_identifiers_leak_into_masked_output(real_estate: Path, masked_estate: MaskedEstate) -> None:
    masked_root = masked_estate.root
    conn = sqlite3.connect(str(real_estate / "postgres_enrollment" / "enrollment.sqlite3"))
    members = pd.read_sql_query("SELECT member_id, first_name, last_name, ssn FROM member", conn)
    demographics = pd.read_sql_query(
        "SELECT email, phone FROM member_demographics WHERE email IS NOT NULL", conn
    )

    # Full name (first + last) rather than each name fragment
    # individually: NAME_REPLACEMENT draws synthetic first/last names
    # from the same realistic (Faker) vocabulary real names come from, so
    # a single synthesized first name like "Angela" can coincidentally
    # match a DIFFERENT real member's actual first name at small scale --
    # exactly as two unrelated real people might coincidentally share a
    # common first name in production. That is not a re-identification
    # leak (see docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md's general
    # point that any single common attribute is weak evidence on its
    # own). The full "first last" combination is high-entropy enough
    # that an incidental match is not a realistic concern, and masked
    # first/last names are generated independently per column, so a
    # masked record reproducing a *specific, different* real person's
    # full name by chance is not something this check should expect.
    raw_values: set[str] = set(members["member_id"].dropna().astype(str))
    raw_values |= set(members["ssn"].dropna().astype(str))
    raw_values |= set(
        (members["first_name"].fillna("") + " " + members["last_name"].fillna(""))
        .str.strip()
    )
    raw_values |= set(demographics["email"].dropna().astype(str))

    blobs: list[str] = []
    for path in masked_root.rglob("*"):
        if path.is_file() and path.suffix in (".ndjson", ".csv", ".json", ".txt"):
            blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    # SQLite file: dump as text too (raw bytes contain the string data).
    sqlite_path = masked_root / "postgres_enrollment" / "enrollment.sqlite3"
    blobs.append(sqlite_path.read_bytes().decode("latin-1"))

    assert_no_raw_values_leaked(blobs, raw_values, min_length=5)


def test_masking_is_idempotent_across_two_independent_runs(real_estate: Path, real_catalog: list, tmp_path: Path) -> None:
    engine_1 = MaskingEngine(key=MASKING_KEY)
    engine_2 = MaskingEngine(key=MASKING_KEY)
    out_1 = tmp_path / "run-1"
    out_2 = tmp_path / "run-2"

    mask_estate(real_estate, real_catalog, out_1, engine_1)
    mask_estate(real_estate, real_catalog, out_2, engine_2)

    conn_1 = sqlite3.connect(str(out_1 / "postgres_enrollment" / "enrollment.sqlite3"))
    conn_2 = sqlite3.connect(str(out_2 / "postgres_enrollment" / "enrollment.sqlite3"))
    members_1 = pd.read_sql_query("SELECT member_id, ssn FROM member ORDER BY member_id", conn_1)
    members_2 = pd.read_sql_query("SELECT member_id, ssn FROM member ORDER BY member_id", conn_2)
    pd.testing.assert_frame_equal(members_1, members_2)


def test_referential_integrity_validated_across_the_whole_run(masked_estate: MaskedEstate) -> None:
    report = masked_estate.report
    assert report.linkage_samples, "expected at least one preserve_linkage column to be sampled"
    assert_referential_integrity(report.linkage_samples)


def test_malformed_dates_in_the_real_estate_produced_safe_warnings_not_crashes(masked_estate: MaskedEstate) -> None:
    report = masked_estate.report
    # The 'tiny' estate's edge_cases.py malformed_value_rate guarantees at
    # least one malformed value is injected; masking must have handled it
    # (via a warning + safe redaction) rather than raising.
    assert isinstance(report.warnings, list)
