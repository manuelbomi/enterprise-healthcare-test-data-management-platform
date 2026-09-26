"""Apply the masking engine to the real, on-disk Phase 1 synthetic estate,
using the real Phase 2 catalog to decide which technique masks which
column.

This is the "catalog classification -> masking policy -> masked output"
integration point `ARCHITECTURE.md` section 2.2 describes for the data
plane's `Masking` component, and it deliberately mirrors
`data_plane.discovery.scanner`'s per-source-system function shape
(`mask_postgres_enrollment` <-> `scan_postgres_enrollment`, etc.) so the
two packages read side by side easily -- discovery figures out what a
column *is*, masking decides what to *do* about it, and both walk the
exact same five-source-system estate layout independently (this module
does not import `discovery` at runtime; it consumes the same
`CatalogEntry` shape `discovery.catalog_builder.write_catalog` already
produced -- see `docs/adr/0009-catalog-artifact-handoff.md`'s
plane-separation reasoning, which applies just as well within the data
plane between these two sibling subpackages).

Every masked output file lives at the same relative path under a new
output root as its unmasked counterpart under the estate root, so a
masked estate is a drop-in replacement for the original for anything that
only cares about referential shape, not real values.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import pandas as pd

from healthcare_tdm_contracts import CatalogEntry, MaskingPolicy

from data_plane.masking.engine import MASKING_ENGINE_VERSION, MaskingEngine, MaskingWarning
from data_plane.masking.policy import DEFAULT_POLICY, resolve_rule


@dataclass
class MaskingRunReport:
    """Summary of one `mask_estate` run -- printed by the CLI and used by
    `validation.py`/tests to check the run actually did what it claims.
    """

    rows_processed: int = 0
    columns_masked: int = 0
    technique_counts: dict[str, int] = field(default_factory=dict)
    files_written: list[Path] = field(default_factory=list)
    warnings: list[MaskingWarning] = field(default_factory=list)
    #: (source_system, dataset, column) -> {original_value: masked_value},
    #: kept ONLY for columns with preserve_linkage=True, and only up to a
    #: small cap, so validation/tests can check cross-system consistency
    #: without holding the whole estate's value space in memory.
    linkage_samples: dict[tuple[str, str, str], dict[str, str]] = field(default_factory=dict)
    #: Which version of `data_plane.masking.engine.MaskingEngine`'s code
    #: produced this run -- see `MASKING_ENGINE_VERSION`'s docstring for
    #: why this is tracked separately from the policy's own `version`.
    #: Recorded here (not just read from the module constant by callers)
    #: so a `masking_run_summary.json`/certification report is a
    #: self-contained record of what ran, without needing to cross-
    #: reference the engine's source code at read time.
    masking_engine_version: str = MASKING_ENGINE_VERSION

    def record(self, technique_value: str) -> None:
        self.columns_masked += 1
        self.technique_counts[technique_value] = self.technique_counts.get(technique_value, 0) + 1


_LINKAGE_SAMPLE_CAP = 50


# ---------------------------------------------------------------------------
# Phase 18A (resolves `docs/problems/problems_final_review.md` P1-6): atomic per-file
# writes.
#
# Before this phase, `mask_estate`'s own docstring honestly documented a
# real gap: the run-level `INCOMPLETE_MARKER_FILENAME` marker proves the
# *run as a whole* did not finish, but does NOT guarantee any individual
# per-source-system masker's OWN output file is itself complete -- a
# crash mid-write (e.g. `mask_clinical_data_lake` writing NDJSON rows
# into an already-open file handle one at a time) could leave one
# truncated, plausible-looking file at its final path, indistinguishable
# from a valid file except via the separate marker.
#
# The fix below is the standard one for this exact problem: every writer
# in this module now writes its full output to a temporary path in the
# SAME directory as its final destination, then atomically renames it
# into place (`os.replace`, which POSIX and Windows both guarantee is
# atomic for a rename within the same filesystem/volume) only once the
# write has fully succeeded. A crash mid-write now leaves, at most, a
# stray `.tmp-*` file that was never renamed -- the final path either
# does not exist yet, or holds the complete, previous (or current)
# write, NEVER a partial one. See
# `tests/masking/test_dataset_masker_atomic_writes.py` for a real
# regression test that simulates a crash mid-write and asserts no
# partial file is ever visible at the final path.
# ---------------------------------------------------------------------------


def _temp_path_for(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")


def _atomic_write_via(path: Path, write: Callable[[Path], None]) -> None:
    """Call `write(tmp_path)` (any callable that fully writes its output
    to the given path, e.g. `df.to_parquet`/`df.to_csv`, or a whole
    SQLite file being moved into place), then atomically replace `path`
    with the result. On any exception, the temporary file is removed and
    `path` is left exactly as it was before this call -- never a
    partially-written file at the final path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _temp_path_for(path)
    try:
        write(tmp_path)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    else:
        os.replace(tmp_path, path)


@contextmanager
def _atomic_text_writer(path: Path, *, newline: str | None = None) -> Iterator[TextIO]:
    """Context manager: open a temporary file (in `path`'s own
    directory) for text writing, yield the handle for a caller to write
    incrementally (e.g. row by row), and atomically replace `path` with
    it only on clean exit. On an exception raised inside the `with`
    block, the temporary file is closed and removed, and `path` is left
    untouched -- the same guarantee `_atomic_write_via` gives a
    single-call writer, extended to an incremental one."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _temp_path_for(path)
    handle = tmp_path.open("w", encoding="utf-8", newline=newline)
    try:
        yield handle
    except BaseException:
        handle.close()
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    else:
        handle.close()
        os.replace(tmp_path, path)


class CatalogLookup:
    """`(source_system, dataset, column) -> CatalogEntry`, built once per
    run from the catalog artifact `discovery.cli` produced."""

    def __init__(self, entries: list[CatalogEntry]) -> None:
        self._by_key: dict[tuple[str, str, str], CatalogEntry] = {
            (e.source, e.dataset, e.column): e for e in entries
        }

    def get(self, source_system: str, dataset: str, column: str) -> CatalogEntry | None:
        return self._by_key.get((source_system, dataset, column))


def mask_row_dict(
    row: dict[str, Any],
    *,
    source_system: str,
    dataset: str,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> dict[str, Any]:
    """Mask every present key of `row` using the catalog's classification
    for `(source_system, dataset, column)`.

    A column present in the row but absent from the catalog (should not
    happen against a catalog produced by a discovery run over the same
    estate, but defensive against drift) falls back to the conservative
    `HMAC_PSEUDONYMIZATION` technique rather than passing the raw value
    through -- consistent with `DATA_GOVERNANCE.md` B.1's "never default
    an unknown column to safe."
    """

    from healthcare_tdm_contracts import MaskingFieldType, MaskingTechnique

    masked: dict[str, Any] = {}
    for column, value in row.items():
        entry = catalog.get(source_system, dataset, column)
        if entry is None:
            digest_scope = f"unclassified:{source_system}:{dataset}:{column}"
            masked[column] = engine.mask_value(
                value,
                technique=MaskingTechnique.HMAC_PSEUDONYMIZATION,
                scope=digest_scope,
                field_type=MaskingFieldType.GENERIC,
            )
            report.record(MaskingTechnique.HMAC_PSEUDONYMIZATION.value)
            continue

        resolved = resolve_rule(policy, tier=entry.classification.tier, column=column)
        masked_value = engine.mask_value(
            value,
            technique=resolved.technique,
            scope=resolved.scope,
            field_type=resolved.field_type,
            preserve_format=resolved.preserve_format,
            preserve_null=resolved.preserve_null,
            parameters=resolved.parameters,
        )
        masked[column] = masked_value
        report.record(resolved.technique.value)

        if resolved.preserve_linkage and value is not None:
            key = (source_system, dataset, column)
            samples = report.linkage_samples.setdefault(key, {})
            if len(samples) < _LINKAGE_SAMPLE_CAP:
                samples[str(value)] = str(masked_value)

    return masked


def _mask_dataframe(
    df: pd.DataFrame,
    *,
    source_system: str,
    dataset: str,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> pd.DataFrame:
    if df.empty:
        return df
    records = df.to_dict(orient="records")
    masked_records = [
        mask_row_dict(
            {k: (None if pd.isna(v) else v) for k, v in r.items()},
            source_system=source_system,
            dataset=dataset,
            catalog=catalog,
            engine=engine,
            policy=policy,
            report=report,
        )
        for r in records
    ]
    report.rows_processed += len(masked_records)
    return pd.DataFrame(masked_records, columns=df.columns)


# ---------------------------------------------------------------------------
# Per-source-system maskers (mirrors discovery/scanner.py's shape).
# ---------------------------------------------------------------------------


def mask_postgres_enrollment(
    sqlite_in: Path,
    sqlite_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not sqlite_in.exists():
        return
    sqlite_out.parent.mkdir(parents=True, exist_ok=True)

    table_to_dataset = {
        "member": "member",
        "member_demographics": "member_demographics",
        "address": "address",
        "plan": "plan",
        "coverage": "coverage",
        "provider": "provider",
    }

    def _write(tmp_path: Path) -> None:
        # Phase 18A (P1-6): the whole SQLite output file is built at a
        # temporary path first -- `mask_estate`'s atomic-rename move
        # into `sqlite_out` only happens once every table below has
        # been written and committed successfully.
        if tmp_path.exists():
            tmp_path.unlink()
        source_conn = sqlite3.connect(str(sqlite_in))
        out_conn = sqlite3.connect(str(tmp_path))
        try:
            for table, dataset in table_to_dataset.items():
                try:
                    df = pd.read_sql_query(f"SELECT * FROM {table}", source_conn)
                except pd.errors.DatabaseError:
                    continue
                masked = _mask_dataframe(
                    df,
                    source_system="postgres_enrollment",
                    dataset=dataset,
                    catalog=catalog,
                    engine=engine,
                    policy=policy,
                    report=report,
                )
                masked.to_sql(table, out_conn, index=False, if_exists="replace")
            out_conn.commit()
        finally:
            source_conn.close()
            out_conn.close()

    _atomic_write_via(sqlite_out, _write)
    report.files_written.append(sqlite_out)


def mask_claims_parquet(
    bucket_in: Path,
    bucket_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not bucket_in.exists():
        return
    entity_datasets = {"claim", "claim_line", "diagnosis", "procedure"}
    for dataset in entity_datasets:
        dataset_dir = bucket_in / dataset
        if not dataset_dir.exists():
            continue
        for parquet_path in sorted(dataset_dir.rglob("*.parquet")):
            relative = parquet_path.relative_to(bucket_in)
            out_path = bucket_out / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df = pd.read_parquet(parquet_path)
            masked = _mask_dataframe(
                df,
                source_system="object_storage_claims_parquet",
                dataset=dataset,
                catalog=catalog,
                engine=engine,
                policy=policy,
                report=report,
            )
            def _write_parquet(tmp_path: Path, *, _masked: pd.DataFrame = masked) -> None:
                _masked.to_parquet(tmp_path, index=False)

            _atomic_write_via(out_path, _write_parquet)
            report.files_written.append(out_path)


def mask_clinical_data_lake(
    bucket_in: Path,
    bucket_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not bucket_in.exists():
        return
    for folder, dataset in (("encounters", "encounter"), ("lab_results", "lab_result")):
        path = bucket_in / folder / "part-0000.ndjson"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        out_path = bucket_out / folder / "part-0000.ndjson"
        # Phase 18A (P1-6): this is the exact writer
        # `docs/problems/problems_final_review.md` P1-6 named as the concrete
        # example -- rows written incrementally into an already-open
        # file handle, previously at `out_path` directly. It now writes
        # to a temporary path and is atomically renamed into place only
        # on clean completion (`_atomic_text_writer`); a crash mid-write
        # leaves no partial file visible at `out_path`.
        with _atomic_text_writer(out_path) as f:
            for row in rows:
                masked = mask_row_dict(
                    row,
                    source_system="s3_clinical_data_lake",
                    dataset=dataset,
                    catalog=catalog,
                    engine=engine,
                    policy=policy,
                    report=report,
                )
                f.write(json.dumps(masked) + "\n")
                report.rows_processed += 1
        report.files_written.append(out_path)


def mask_pbm_extract(
    container_in: Path,
    container_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not container_in.exists():
        return
    for folder, dataset in (("prescriptions", "prescription"), ("pharmacies", "pharmacy")):
        path = container_in / folder / "part-0000.csv"
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_csv(path, dtype=str)
        masked = _mask_dataframe(
            df,
            source_system="adls_pbm_extract",
            dataset=dataset,
            catalog=catalog,
            engine=engine,
            policy=policy,
            report=report,
        )
        out_path = container_out / folder / "part-0000.csv"

        def _write_csv(tmp_path: Path, *, _masked: pd.DataFrame = masked) -> None:
            _masked.to_csv(tmp_path, index=False)

        _atomic_write_via(out_path, _write_csv)
        report.files_written.append(out_path)


def mask_partner_lab_feed(
    partner_in: Path,
    partner_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    inbound_in = partner_in / "inbound"
    if not inbound_in.exists():
        return

    for v1_path in sorted((inbound_in / "v1_legacy_flat_file").glob("*.txt")):
        with v1_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        out_path = partner_out / "inbound" / "v1_legacy_flat_file" / v1_path.name
        with _atomic_text_writer(out_path, newline="") as out_f:
            out_f.write("|".join(fieldnames) + "\n")
            for row in rows:
                masked = mask_row_dict(
                    dict(row),
                    source_system="partner_lab_feed",
                    dataset="lab_result",
                    catalog=catalog,
                    engine=engine,
                    policy=policy,
                    report=report,
                )
                out_f.write("|".join(str(masked.get(col, "") or "") for col in fieldnames) + "\n")
                report.rows_processed += 1
        report.files_written.append(out_path)

    for v2_path in sorted((inbound_in / "v2_api_json").glob("*.json")):
        payload = json.loads(v2_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else []
        masked_rows = [
            mask_row_dict(
                row,
                source_system="partner_lab_feed",
                dataset="lab_result",
                catalog=catalog,
                engine=engine,
                policy=policy,
                report=report,
            )
            for row in rows
        ]
        report.rows_processed += len(masked_rows)
        out_path = partner_out / "inbound" / "v2_api_json" / v2_path.name

        def _write_json(tmp_path: Path, *, _rows: list[Any] = masked_rows) -> None:
            tmp_path.write_text(json.dumps(_rows, indent=2), encoding="utf-8")

        _atomic_write_via(out_path, _write_json)
        report.files_written.append(out_path)


#: Phase 11: the sentinel file `mask_estate` writes at the start of a
#: run and removes only on clean completion -- see `mask_estate`'s
#: docstring and `is_masking_run_complete` below. Named with a leading
#: underscore (not a dotfile) so it sorts to the top of a directory
#: listing and is unmistakably not part of the masked data itself.
INCOMPLETE_MARKER_FILENAME = "_MASKING_RUN_INCOMPLETE.marker"


def is_masking_run_complete(out_root: Path) -> bool:
    """`True` iff `out_root` both exists and holds no
    `_MASKING_RUN_INCOMPLETE.marker` -- i.e. the most recent
    `mask_estate` run into `out_root` either has not started or
    finished successfully, never "crashed partway through." A caller
    (an operator, a future certification gate, a test) should treat
    `out_root` as untrustworthy -- do not read it as a complete masked
    estate -- whenever this returns `False`.

    Before Phase 18A, this did **not** guarantee every individual file
    under `out_root` was itself complete/uncorrupted (see
    `docs/problems/problems_phase_11.md` P11-1 / `docs/problems/problems_final_review.md` P1-6: a
    per-source-system masker that wrote rows incrementally, e.g.
    `mask_clinical_data_lake`, could leave one truncated file for the
    source system that was mid-write when a crash happened). Phase 18A
    made every per-source-system writer in this module atomic
    (write-to-temp-path-then-`os.replace`, via `_atomic_write_via`/
    `_atomic_text_writer`), so that gap is now closed too: a crash
    mid-write leaves, at most, a stray `.tmp-*` file, never a partial
    file at its final path. This function's own guarantee (the *run as
    a whole* did or did not finish) is unchanged and remains useful on
    its own -- it is the cheap, single-check way to know whether ANY
    per-source-system masker was still in flight, without having to stat
    every individual output file.
    """

    return out_root.exists() and not (out_root / INCOMPLETE_MARKER_FILENAME).exists()


def mask_estate(
    estate_root: Path,
    catalog_entries: list[CatalogEntry],
    out_root: Path,
    engine: MaskingEngine,
    *,
    policy: MaskingPolicy | None = None,
) -> MaskingRunReport:
    """Mask every one of the five simulated source systems under
    `estate_root`, writing the masked estate to `out_root` (mirroring the
    same relative layout `reference_data.estate_writer.write_estate`
    produced), using `catalog_entries` (the real Phase 2 discovery output)
    to decide which technique masks which column.

    **Phase 11 crash-safety note**: before any output is written, this
    function writes `out_root / _MASKING_RUN_INCOMPLETE.marker`. That
    marker is removed only if every one of the five per-source-system
    maskers below completes without raising -- if any of them raises
    (a real, unhandled exception, exactly the "masking job crashes
    halfway" failure-injection scenario), the exception propagates
    unchanged (this function does not swallow it) and the marker is
    left in place, so `is_masking_run_complete(out_root)` reports
    `False` rather than a caller mistaking a partial `out_root` for a
    finished one. This is a real, tested mitigation for a real gap
    found while writing this phase's failure-injection tests.

    **Phase 18A update (`docs/problems/problems_final_review.md` P1-6, now resolved):**
    `docs/problems/problems_phase_11.md` P11-1 originally, honestly, noted this marker
    alone did not make each individual per-source-system masker's own
    writes atomic. Every writer below (`mask_postgres_enrollment`,
    `mask_claims_parquet`, `mask_clinical_data_lake`, `mask_pbm_extract`,
    `mask_partner_lab_feed`) now writes to a temporary path in its
    destination directory and atomically renames it into place only on
    clean completion (`_atomic_write_via`/`_atomic_text_writer`), so a
    crash mid-write can no longer leave a truncated, plausible-looking
    file at its final path -- see
    `tests/masking/test_dataset_masker_atomic_writes.py` for a real
    regression test that simulates exactly that crash.
    """

    policy = policy or DEFAULT_POLICY
    catalog = CatalogLookup(catalog_entries)
    report = MaskingRunReport()

    out_root.mkdir(parents=True, exist_ok=True)
    marker_path = out_root / INCOMPLETE_MARKER_FILENAME
    marker_path.write_text(
        json.dumps({"started_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8"
    )

    mask_postgres_enrollment(
        estate_root / "postgres_enrollment" / "enrollment.sqlite3",
        out_root / "postgres_enrollment" / "enrollment.sqlite3",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_claims_parquet(
        estate_root / "object_storage_claims_parquet" / "claims-warehouse",
        out_root / "object_storage_claims_parquet" / "claims-warehouse",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_clinical_data_lake(
        estate_root / "s3_clinical_data_lake" / "clinical-data-lake",
        out_root / "s3_clinical_data_lake" / "clinical-data-lake",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_pbm_extract(
        estate_root / "adls_pbm_extract" / "pbm-extract",
        out_root / "adls_pbm_extract" / "pbm-extract",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_partner_lab_feed(
        estate_root / "partner_lab_feed",
        out_root / "partner_lab_feed",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )

    marker_path.unlink(missing_ok=True)
    report.warnings = list(engine.warnings)
    return report


__all__ = [
    "CatalogLookup",
    "INCOMPLETE_MARKER_FILENAME",
    "MaskingRunReport",
    "is_masking_run_complete",
    "mask_claims_parquet",
    "mask_clinical_data_lake",
    "mask_estate",
    "mask_pbm_extract",
    "mask_partner_lab_feed",
    "mask_postgres_enrollment",
    "mask_row_dict",
]
