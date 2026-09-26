"""Regression tests for Phase 18A's atomic-write fix
(`docs/problems/problems_final_review.md` P1-6): "masking's per-source-system writers
aren't atomic; a crash mid-write can leave a corrupt/partial file."

Each test below simulates a real crash *mid-write* (an exception raised
partway through writing a file's content) and proves no truncated,
partial file is ever left visible at the file's final path -- the exact
scenario `mask_clinical_data_lake`'s pre-Phase-18A code (writing NDJSON
rows into an already-open file handle one at a time) was named as the
concrete example of in `docs/problems/problems_final_review.md` P1-6.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_plane.discovery.catalog_builder import build_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate
from data_plane.masking.dataset_masker import (
    CatalogLookup,
    MaskingRunReport,
    _atomic_text_writer,
    _atomic_write_via,
    mask_clinical_data_lake,
)
from data_plane.masking.engine import MaskingEngine
from data_plane.masking.policy import DEFAULT_POLICY
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES

MASKING_KEY = b"atomic-write-test-hmac-key-0123456789abcdef"


# ---------------------------------------------------------------------------
# Unit tests: the atomic-write primitives themselves.
# ---------------------------------------------------------------------------


def test_atomic_write_via_leaves_no_file_at_all_when_the_writer_crashes(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"

    def _crashing_writer(tmp: Path) -> None:
        tmp.write_bytes(b"partial-content-that-must-never-be-visible")
        raise RuntimeError("simulated crash mid-write")

    with pytest.raises(RuntimeError):
        _atomic_write_via(target, _crashing_writer)

    assert not target.exists(), "a crash mid-write must never leave a partial file at the final path"
    # No stray temp file left behind either.
    assert list(tmp_path.glob(".*.tmp-*")) == []


def test_atomic_write_via_preserves_the_previous_file_on_a_crash(tmp_path: Path) -> None:
    """The specific scenario a naive in-place write gets wrong: if
    `target` already holds a valid PREVIOUS write, a crash while
    producing the NEXT one must never corrupt or truncate it."""

    target = tmp_path / "out.bin"
    target.write_bytes(b"previous-good-content")

    def _crashing_writer(tmp: Path) -> None:
        tmp.write_bytes(b"new-partial-content")
        raise RuntimeError("simulated crash mid-write")

    with pytest.raises(RuntimeError):
        _atomic_write_via(target, _crashing_writer)

    assert target.read_bytes() == b"previous-good-content"


def test_atomic_write_via_replaces_the_file_only_on_full_success(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    _atomic_write_via(target, lambda tmp: tmp.write_bytes(b"complete-content"))
    assert target.read_bytes() == b"complete-content"


def test_atomic_text_writer_leaves_no_partial_file_when_the_caller_crashes_mid_write(tmp_path: Path) -> None:
    target = tmp_path / "out.ndjson"

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with _atomic_text_writer(target) as f:
            f.write('{"row": 1}\n')
            f.write('{"row": 2}\n')
            raise _Boom("simulated crash after writing two of many rows")

    assert not target.exists()
    assert list(tmp_path.glob(".*.tmp-*")) == []


def test_atomic_text_writer_writes_the_complete_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.ndjson"
    with _atomic_text_writer(target) as f:
        for i in range(5):
            f.write(json.dumps({"row": i}) + "\n")
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5


# ---------------------------------------------------------------------------
# Integration test: a real per-source-system masker crashing mid-write.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_estate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("atomic-write-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root


@pytest.fixture(scope="module")
def real_catalog(real_estate: Path) -> list:
    columns = scan_estate(real_estate)
    return build_catalog(columns, ClassificationEngine())


def test_mask_clinical_data_lake_crash_mid_write_leaves_no_truncated_ndjson_file(
    tmp_path: Path, real_estate: Path, real_catalog: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces `docs/problems/problems_final_review.md` P1-6's exact named example:
    `mask_clinical_data_lake` writes NDJSON rows one at a time. Force a
    crash partway through the `encounters` file (after at least one row
    has been written to the underlying handle) and prove `part-0000.ndjson`
    is never left as a truncated, plausible-looking partial file at its
    final path -- either it does not exist at all (first write), or (in
    a second run, simulated by pre-seeding a previous good file) it
    still holds the previous, complete content."""

    catalog = CatalogLookup(real_catalog)
    engine = MaskingEngine(key=MASKING_KEY)
    out_root = tmp_path / "masked"

    call_count = {"n": 0}
    from data_plane.masking import dataset_masker as masker_module

    real_mask_row_dict = masker_module.mask_row_dict

    def _crash_on_third_row(*args: object, **kwargs: object) -> dict:
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated masking-engine crash mid-write")
        return real_mask_row_dict(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(masker_module, "mask_row_dict", _crash_on_third_row)

    out_path = out_root / "encounters" / "part-0000.ndjson"

    with pytest.raises(RuntimeError, match="simulated masking-engine crash mid-write"):
        mask_clinical_data_lake(
            real_estate / "s3_clinical_data_lake" / "clinical-data-lake",
            out_root,
            catalog=catalog,
            engine=engine,
            policy=DEFAULT_POLICY,
            report=MaskingRunReport(),
        )

    assert not out_path.exists(), (
        "a crash partway through writing encounters/part-0000.ndjson must never leave a "
        "truncated file visible at its final path"
    )
    assert list((out_root / "encounters").glob(".*.tmp-*")) == [], "no stray temp file should remain either"


def test_mask_clinical_data_lake_crash_mid_write_does_not_corrupt_a_previous_good_run(
    tmp_path: Path, real_estate: Path, real_catalog: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario that matters most operationally: a SECOND masking
    run crashes partway through re-writing `encounters/part-0000.ndjson`
    -- the file from the FIRST, successful run must survive completely
    unmodified, never truncated to whatever the second run had written
    before it crashed."""

    catalog = CatalogLookup(real_catalog)
    engine = MaskingEngine(key=MASKING_KEY)
    out_root = tmp_path / "masked"

    # First, real, successful run.
    mask_clinical_data_lake(
        real_estate / "s3_clinical_data_lake" / "clinical-data-lake",
        out_root,
        catalog=catalog,
        engine=engine,
        policy=DEFAULT_POLICY,
        report=MaskingRunReport(),
    )
    out_path = out_root / "encounters" / "part-0000.ndjson"
    assert out_path.exists()
    good_content = out_path.read_bytes()
    assert good_content  # the fixture estate has real encounter rows

    # Second run crashes partway through.
    from data_plane.masking import dataset_masker as masker_module

    call_count = {"n": 0}
    real_mask_row_dict = masker_module.mask_row_dict

    def _crash_on_third_row(*args: object, **kwargs: object) -> dict:
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated crash on the second run")
        return real_mask_row_dict(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(masker_module, "mask_row_dict", _crash_on_third_row)

    with pytest.raises(RuntimeError, match="simulated crash on the second run"):
        mask_clinical_data_lake(
            real_estate / "s3_clinical_data_lake" / "clinical-data-lake",
            out_root,
            catalog=catalog,
            engine=engine,
            policy=DEFAULT_POLICY,
            report=MaskingRunReport(),
        )

    assert out_path.read_bytes() == good_content, (
        "the previous, complete run's file must be untouched -- never truncated by a "
        "later run that crashed partway through re-writing it"
    )
