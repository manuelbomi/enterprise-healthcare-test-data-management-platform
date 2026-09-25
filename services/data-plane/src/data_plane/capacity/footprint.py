"""Real, on-disk storage-footprint measurement (Phase 8).

Everything in this module reads actual bytes off actual files -- no
estimation, no configuration-driven guessing. It is the data-plane half
of `docs/adr/0013-capacity-planning-plane-split.md`'s split: real
measurement lives here (this module operates on filesystem paths, same
as every other data-plane engine); aggregating those numbers across
registered dataset versions/environments is
`control_plane.domain.capacity.planner`'s job, over there.

`measure_directory_footprint` is a productionized version of the same
`directory_size_bytes` helper `scripts/demo_phase7_lifecycle.py` already
used ad hoc to compute the `size_bytes` it passed to
`POST /api/v1/lifecycle/dataset-versions` -- this module gives that
pattern a real home instead of leaving it as a one-off script helper,
and extends it with a per-format breakdown and real Parquet compression
measurement.

Compression measurement is real but honestly scoped
------------------------------------------------------
`measure_parquet_compression` reads a real Parquet file (written by
`data_plane.reference_data.writers.parquet_writer`, or any other
pandas-written Parquet output the pipeline produces), and re-encodes the
*same* in-memory rows as CSV to get an "uncompressed, row-oriented"
comparison point. This is a genuinely real measurement of two genuinely
different on-disk representations of the same data -- but it is *not* a
bit-for-bit "Parquet with compression disabled" byte count (neither
pandas nor pyarrow exposes that without writing the file a second time
with different codec settings), and CSV re-encoding also drops Parquet's
columnar/typed encoding efficiency, not just its compression codec. See
`healthcare_tdm_contracts.capacity.CompressionMeasurement.method` and
`docs/CAPACITY_COST_TRADEOFFS.md` for the honest framing.
"""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import CompressionMeasurement, FootprintMeasurementReport

#: File extensions this module treats as "Parquet" for compression
#: measurement purposes.
_PARQUET_EXTENSIONS = {".parquet"}


def directory_size_bytes(path: Path) -> int:
    """Total bytes of every regular file under `path`, recursively. The
    same computation `scripts/demo_phase7_lifecycle.py`'s
    `directory_size_bytes` helper already performed inline -- kept here
    as the one real implementation both that script and this phase's own
    demo/tests use."""

    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def measure_parquet_compression(parquet_path: Path) -> CompressionMeasurement:
    """Measure one real Parquet file's on-disk (compressed) size against
    a re-encoding of its actual rows as CSV. Raises `FileNotFoundError`
    if `parquet_path` does not exist, and `ImportError` with a clear
    message if `pandas`/`pyarrow` are not installed (they are declared
    dependencies of this package -- see `pyproject.toml` -- so this is a
    defensive message, not an expected path)."""

    if not parquet_path.exists():
        raise FileNotFoundError(f"No such Parquet file: {parquet_path}")

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover -- pandas is a declared dependency
        raise ImportError(
            "measure_parquet_compression requires pandas (and pyarrow), both declared "
            "dependencies of services/data-plane."
        ) from exc

    frame = pd.read_parquet(parquet_path)
    compressed_bytes = parquet_path.stat().st_size
    csv_bytes = frame.to_csv(index=False).encode("utf-8")
    uncompressed_estimate_bytes = len(csv_bytes)
    ratio = (uncompressed_estimate_bytes / compressed_bytes) if compressed_bytes else 0.0

    return CompressionMeasurement(
        source_path=str(parquet_path),
        row_count=len(frame),
        column_count=len(frame.columns),
        compressed_bytes=compressed_bytes,
        uncompressed_estimate_bytes=uncompressed_estimate_bytes,
        compression_ratio=ratio,
    )


def measure_directory_footprint(root: Path) -> FootprintMeasurementReport:
    """Real, on-disk footprint measurement for an entire directory tree
    (an estate, a subset, a masked/certified output directory).

    Reports total bytes and per-extension breakdown across every file
    actually present -- Parquet, CSV, NDJSON/JSON, SQLite `.db`, and any
    other format the multi-format synthetic estate (ADR-0007, Phase 1)
    writes -- and, for every `.parquet` file found, a real
    `measure_parquet_compression` result.
    """

    if not root.exists():
        return FootprintMeasurementReport(root_path=str(root), total_bytes=0, total_file_count=0)

    bytes_by_ext: dict[str, int] = {}
    count_by_ext: dict[str, int] = {}
    parquet_measurements: list[CompressionMeasurement] = []

    for f in root.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower() or "(none)"
        size = f.stat().st_size
        bytes_by_ext[ext] = bytes_by_ext.get(ext, 0) + size
        count_by_ext[ext] = count_by_ext.get(ext, 0) + 1
        if ext in _PARQUET_EXTENSIONS:
            try:
                parquet_measurements.append(measure_parquet_compression(f))
            except Exception:  # noqa: BLE001 -- a single unreadable/corrupt file must not abort the whole scan
                continue

    return FootprintMeasurementReport(
        root_path=str(root),
        total_bytes=sum(bytes_by_ext.values()),
        total_file_count=sum(count_by_ext.values()),
        bytes_by_extension=bytes_by_ext,
        file_count_by_extension=count_by_ext,
        parquet_compression=parquet_measurements,
    )


__all__ = ["directory_size_bytes", "measure_directory_footprint", "measure_parquet_compression"]
