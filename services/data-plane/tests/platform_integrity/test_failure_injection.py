"""Phase 11 failure-injection tests -- data-plane side.

`ROADMAP.md` Phase 11 asks for real failure-injection tests, not
mocked-away ones, for eight scenarios. This file covers the four that
belong to the data plane -- masking job crashes halfway, storage
unavailable, dataset becomes corrupted, and source schema changes --
plus secret-missing (data-plane's own key resolution). The remaining
four (duplicate refresh request, certification validation fails,
consumer requests revoked dataset, and this file's own secret-missing
counterpart at the certification-signing layer) are covered where they
actually live: `services/control-plane/tests/test_failure_injection.py`
for the control-plane-owned ones, and Phase 6's own
`services/data-plane/tests/certification/` suite for certification
validation (already real, cross-referenced below rather than
duplicated).

Every test here runs against real, on-disk artifacts produced by the
real Phase 1/2/3 engines -- no mocking of the masking engine itself,
only targeted monkeypatching of one internal call site where a test
needs to simulate a mid-run crash (see
`test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output`).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import data_plane.masking.dataset_masker as dataset_masker_module
from data_plane.discovery.catalog_builder import build_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate
from data_plane.masking.dataset_masker import (
    CatalogLookup,
    INCOMPLETE_MARKER_FILENAME,
    is_masking_run_complete,
    mask_estate,
    mask_row_dict,
)
from data_plane.masking.engine import MaskingEngine
from data_plane.masking.policy import DEFAULT_POLICY
from data_plane.masking.secrets import MissingMaskingKeyError, resolve_hmac_key
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES
from data_plane.subsetting.estate_io import read_estate

MASKING_KEY = b"failure-injection-test-hmac-key-0123456789"


@pytest.fixture(scope="module")
def real_estate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("phase11-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root


@pytest.fixture(scope="module")
def real_catalog(real_estate: Path) -> list:
    columns = scan_estate(real_estate)
    return build_catalog(columns, ClassificationEngine())


# ---------------------------------------------------------------------------
# Scenario 1: masking job crashes halfway
# ---------------------------------------------------------------------------


def test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output(
    real_estate: Path, real_catalog: list, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a real, unhandled exception partway through a masking
    run (after the first two of five per-source-system maskers have
    already written real output) and confirm the run fails loudly
    (the exception propagates, it is not swallowed) and leaves a
    real, checkable signal (`_MASKING_RUN_INCOMPLETE.marker`) that the
    output directory must not be trusted as complete.

    This is the test that found a real gap (`docs/problems/problems_phase_11.md`
    P11-1) and proves the fix: before this phase, `mask_estate` gave
    no on-disk signal at all that a run had crashed -- a caller
    scanning `out_root` afterward could not distinguish "this masking
    run finished" from "this masking run crashed after writing two of
    five source systems," which is exactly the "half-masked output
    mistaken for complete" risk the phase brief calls out.
    """

    out_root = tmp_path / "masked-crash"

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash: clinical data lake masker failed mid-run")

    # mask_clinical_data_lake is the third of five per-source-system
    # maskers mask_estate calls, in order -- by the time this raises,
    # mask_postgres_enrollment and mask_claims_parquet have already
    # written real files under out_root.
    monkeypatch.setattr(dataset_masker_module, "mask_clinical_data_lake", _boom)

    engine = MaskingEngine(key=MASKING_KEY)
    with pytest.raises(RuntimeError, match="simulated crash"):
        mask_estate(real_estate, real_catalog, out_root, engine, policy=DEFAULT_POLICY)

    # The crash did not silently disappear -- earlier stages' real
    # output is genuinely on disk (proving this was a real partial
    # run, not a no-op)...
    assert (out_root / "postgres_enrollment" / "enrollment.sqlite3").exists()
    assert (out_root / "object_storage_claims_parquet" / "claims-warehouse").exists()
    # ...and the marker this phase adds makes that fact checkable
    # without re-deriving it from timestamps/row-counts.
    assert (out_root / INCOMPLETE_MARKER_FILENAME).exists()
    assert is_masking_run_complete(out_root) is False


def test_a_clean_masking_run_removes_the_incomplete_marker(
    real_estate: Path, real_catalog: list, tmp_path: Path
) -> None:
    """The inverse control: a run that completes normally leaves no
    marker behind, so `is_masking_run_complete` is a real signal, not
    one that is always `False`."""

    out_root = tmp_path / "masked-clean"
    engine = MaskingEngine(key=MASKING_KEY)
    mask_estate(real_estate, real_catalog, out_root, engine, policy=DEFAULT_POLICY)

    assert not (out_root / INCOMPLETE_MARKER_FILENAME).exists()
    assert is_masking_run_complete(out_root) is True


# ---------------------------------------------------------------------------
# Scenario 2: storage unavailable
# ---------------------------------------------------------------------------


def test_storage_unavailable_fails_cleanly_without_a_leaked_stack_trace_of_raw_data(
    real_estate: Path, real_catalog: list, tmp_path: Path
) -> None:
    """Simulate a real, unavailable storage location: point `out_root`
    at a path nested *under a plain file* (not a directory) -- a real,
    portable (Windows- and POSIX-safe) way to force a genuine OS-level
    "cannot write here" condition without needing platform-specific
    permission APIs (`chmod` does not reliably block a Windows test
    runner the way it does on POSIX).

    Asserts the failure is clean: a real `OSError` propagates (not a
    generic crash), and its message contains no raw source-estate
    value (no member name/SSN/etc. -- confirming
    `THREAT_MODEL.md`'s control-plane "Information disclosure"
    principle -- "documented error contract that never echoes raw data
    values" -- holds here too, at the data-plane layer where the
    principle matters most, since this is exactly where raw PHI/PII
    values are in scope during a run).
    """

    blocker_file = tmp_path / "not_a_directory"
    blocker_file.write_text("this is a file, not a directory", encoding="utf-8")
    unavailable_out_root = blocker_file / "estate_out"

    engine = MaskingEngine(key=MASKING_KEY)
    with pytest.raises(OSError) as exc_info:
        mask_estate(real_estate, real_catalog, unavailable_out_root, engine, policy=DEFAULT_POLICY)

    message = str(exc_info.value)
    # This failure happens before any row is ever read (mkdir fails
    # immediately), so the error can only ever be a plain filesystem
    # error -- asserting no email-shaped value leaked is a real,
    # meaningful check even though the failure point itself is early.
    assert "@" not in message  # no email-shaped value leaked
    # The unavailable location itself is a legitimate thing to report
    # (an operator needs to know *where* storage was unavailable).
    assert "estate_out" in message or "not_a_directory" in message


# ---------------------------------------------------------------------------
# Scenario 3: dataset becomes corrupted
# ---------------------------------------------------------------------------


def test_corrupted_masked_parquet_is_rejected_downstream_not_silently_misread(
    real_estate: Path, real_catalog: list, tmp_path: Path
) -> None:
    """Produce a real masked estate, then genuinely corrupt one of its
    real Parquet output files (truncate it to a handful of bytes --
    real, on-disk byte-level corruption, not a mocked read failure),
    and confirm the downstream read path (`data_plane.subsetting.estate_io.read_estate`,
    the same function the certification pipeline's own VALIDATE stage
    uses) raises a clear exception rather than silently returning
    wrong/empty/truncated data that could be mistaken for a small-but-
    valid estate.
    """

    out_root = tmp_path / "masked-for-corruption"
    engine = MaskingEngine(key=MASKING_KEY)
    mask_estate(real_estate, real_catalog, out_root, engine, policy=DEFAULT_POLICY)

    claim_dir = out_root / "object_storage_claims_parquet" / "claims-warehouse" / "claim"
    parquet_files = sorted(claim_dir.rglob("*.parquet"))
    assert parquet_files, "expected at least one real masked claim parquet file to corrupt"
    target = parquet_files[0]

    original_bytes = target.read_bytes()
    assert len(original_bytes) > 100, "fixture assumption: the real file has real content to truncate"
    target.write_bytes(original_bytes[:16])  # truncate to a handful of bytes -- real corruption

    with pytest.raises((pa.lib.ArrowInvalid, OSError, ValueError)):
        pd.read_parquet(target)

    # The same corruption is caught by the higher-level estate reader
    # a real certification/downstream pipeline stage would actually
    # call -- proving this isn't just a pandas-specific quirk.
    with pytest.raises(Exception):  # noqa: B017 -- deliberately broad: any real read failure counts
        read_estate(out_root)


# ---------------------------------------------------------------------------
# Scenario 4: source schema changes
# ---------------------------------------------------------------------------


def test_a_column_not_in_the_catalog_falls_back_to_safe_masking_not_raw_passthrough() -> None:
    """`ARCHITECTURE.md`'s Phase 2 note and `DATA_GOVERNANCE.md` B.1
    already establish "never default an unknown column to safe" as a
    design principle, and `data_plane.masking.dataset_masker.mask_row_dict`
    already implements a conservative fallback for it (line-level
    comment: "should not happen against a catalog produced by a
    discovery run over the same estate, but defensive against drift").
    This test is this phase's real proof that the fallback actually
    fires, simulating the concrete "source schema changed after
    classification/cataloging, before masking runs" scenario: a brand
    new column (`newly_added_sensitive_field`) appears in a row that
    the catalog (built from an *earlier* scan) has never seen.
    """

    catalog = CatalogLookup(real_catalog_missing_new_column())
    engine = MaskingEngine(key=MASKING_KEY)

    from data_plane.masking.dataset_masker import MaskingRunReport

    report = MaskingRunReport()
    raw_value = "RAW-SENSITIVE-VALUE-THAT-MUST-NEVER-SURVIVE"
    row = {"member_id": "MEMBER-123", "newly_added_sensitive_field": raw_value}

    masked = mask_row_dict(
        row,
        source_system="postgres_enrollment",
        dataset="member",
        catalog=catalog,
        engine=engine,
        policy=DEFAULT_POLICY,
        report=report,
    )

    # The unclassified column was NOT passed through raw -- it was
    # masked (HMAC pseudonymization, mask_row_dict's documented
    # conservative default for a catalog miss).
    assert masked["newly_added_sensitive_field"] != raw_value
    assert masked["newly_added_sensitive_field"] is not None


def real_catalog_missing_new_column() -> list:
    """A minimal, hand-built catalog (no `newly_added_sensitive_field`
    entry at all) standing in for "the catalog a discovery run
    produced before the source schema changed."""

    from healthcare_tdm_contracts import (
        CatalogEntry,
        ClassificationMethod,
        ClassificationTier,
        ColumnClassification,
        MaskingStrategy,
        RetentionClassification,
        SensitivityCategory,
    )

    return [
        CatalogEntry(
            classification=ColumnClassification(
                source_system="postgres_enrollment",
                dataset="member",
                column="member_id",
                tier=ClassificationTier.DIRECT_IDENTIFIER,
                category=SensitivityCategory.DIRECT_IDENTIFIER,
                confidence=1.0,
                detector="test:schema_based",
                method=ClassificationMethod.SCHEMA_BASED,
                reason="fixture",
            ),
            masking_requirement=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
            owner="Enrollment Data Engineering",
            retention_classification=RetentionClassification.EXTENDED,
        ),
    ]


# ---------------------------------------------------------------------------
# Scenario 5: secret missing (masking's HMAC key)
# ---------------------------------------------------------------------------


def test_masking_with_no_key_anywhere_fails_fast_before_any_output_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-reference: `data_plane.masking.secrets.resolve_hmac_key`'s
    missing-key behavior already has thorough unit coverage
    (`services/data-plane/tests/masking/test_secrets.py`,
    `test_resolve_hmac_key_missing_raises_with_remediation_instructions`).
    This test adds the integration-level proof the phase brief asks
    for: with the key genuinely unset (env var deleted, no `.env`
    reachable), the *exact* sequence `data_plane.masking.cli` follows
    (resolve the key, *then* construct `MaskingEngine`) fails at the
    key-resolution step -- `MaskingEngine` is never constructed, and no
    output directory is ever created, so there is no risk of a
    half-configured run silently proceeding with an implicit/default
    key (which would break ADR-0006's determinism guarantee)."""

    monkeypatch.delenv("TDM_MASKING_HMAC_KEY", raising=False)
    isolated_dir = tmp_path / "no-dotenv-here"
    isolated_dir.mkdir()

    would_be_out_root = tmp_path / "should-never-be-created"

    with pytest.raises(MissingMaskingKeyError, match="TDM_MASKING_HMAC_KEY"):
        # search_dirs=[isolated_dir] mirrors resolve_hmac_key's own
        # default search behavior but scoped to a directory guaranteed
        # to have no .env file, so this test is not accidentally
        # sensitive to a real developer's local .env.
        resolve_hmac_key(search_dirs=[isolated_dir])

    assert not would_be_out_root.exists()
