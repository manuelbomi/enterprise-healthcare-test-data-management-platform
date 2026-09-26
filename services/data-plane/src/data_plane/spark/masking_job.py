"""A real PySpark reimplementation of Phase 3's masking engine, applied to
the claims warehouse Parquet extract, at horizontal-scale row counts
(hundreds of thousands of rows -- see `docs/SCALE_AND_PERFORMANCE.md`).

Why this operation, specifically
---------------------------------
`ROADMAP.md` Phase 14 asks for "Spark/PySpark implementations for
operations that should scale horizontally" -- not a wholesale Spark
reimplementation of every masking technique. Masking a single wide,
row-independent column (every row's masked value depends only on that
row's own value, the scope, and the key -- never on any other row) is
the textbook case for a vectorized, embarrassingly-parallel Spark job:
no shuffle is required at all, every partition can be masked completely
independently, and the per-row cost (one HMAC-SHA256 call) is small
enough that Python UDF call overhead matters -- exactly what a
`pandas_udf` (Arrow-vectorized, batches of rows per Python call instead
of one Python call per row) is for. Compare this to
`data_plane.subsetting_job`, which is the *other* Phase 14 operation
(a join, which does need real Spark shuffle/broadcast machinery).

This module does not reimplement `data_plane.masking.engine.MaskingEngine`
-- it *reuses* it, unmodified, inside the pandas UDF (see
`_hmac_pseudonymize_udf`). This is deliberate: the whole point of
ADR-0006's "masked = f(value, scope, key)" design is that the same
function, given the same key and scope, produces the same masked token
no matter what executes it -- a single Python process (Phase 3's `mask_estate`)
or a Spark executor's worker process (this module). `tests/spark/test_masking_job.py`
proves this equivalence directly: the same real value, masked by the
pandas engine and by this Spark job under the same key/scope, produces
byte-for-byte the same token.

Reads the real Phase 1 claims warehouse extract
(`object_storage_claims_parquet/claims-warehouse/claim/`), which is
written as two Hive-partitioned batches with two different schemas
(`docs/adr/0007-delta-parquet-data-format.md`,
`reference_data/writers/parquet_writer.py`'s module docstring) --
`option("mergeSchema", "true")` is required to read both batches as one
DataFrame, which is itself a real demonstration of Parquet schema
evolution (see this package's README).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import cast

from healthcare_tdm_contracts import MaskingFieldType, MaskingTechnique
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.pandas.functions import pandas_udf
from pyspark.sql.types import StringType
from pyspark.sql.udf import UserDefinedFunction

from data_plane.masking.engine import MaskingEngine
from data_plane.masking.policy import LINKAGE_SCOPES

#: The claims-warehouse `claim` table's own linkage scope for its member
#: identifier column -- the exact same scope string
#: `data_plane.masking.policy.resolve_rule` resolves for `member_id`
#: against the DIRECT_IDENTIFIER classification tier, so a value masked
#: by this job and a value masked by Phase 3's `mask_estate` under the
#: same key are provably the same token (see this module's docstring).
MEMBER_ID_SCOPE = LINKAGE_SCOPES["member"][0]
CLAIM_ID_SCOPE = LINKAGE_SCOPES["claim"][0]

#: Columns masked by `run_claims_masking_job`, and the scope each uses.
#: `billed_amount`/`allowed_amount`/`amount_paid`/`paid_amount` are
#: deliberately left untouched here -- Phase 3's real policy
#: (`data_plane/masking/policy.py`) classifies claim monetary amounts as
#: a sensitive clinical/financial attribute masked by date-shifting *dates*,
#: not amounts; reproducing that whole policy resolution in Spark is out
#: of this phase's scope (see `docs/problems/problems_phase_14.md`). This job masks the
#: two DIRECT_IDENTIFIER columns every row actually has, which is enough
#: to demonstrate the real mechanism at scale.
DEFAULT_MASKED_COLUMNS: dict[str, str] = {
    "member_id": MEMBER_ID_SCOPE,
    "claim_id": CLAIM_ID_SCOPE,
}


@dataclass
class SparkMaskingResult:
    """What one `run_claims_masking_job` call actually did -- deliberately
    the same shape of "self-contained run record" every other data-plane
    engine in this repository produces (`MaskingRunReport`,
    `SubsetManifest`, `CertificationReport`), scoped down to what a
    benchmark harness needs.
    """

    input_path: str
    output_path: str
    rows_read: int
    rows_written: int
    columns_masked: list[str]
    elapsed_seconds: float
    read_elapsed_seconds: float
    write_elapsed_seconds: float

    def records_per_second(self) -> float:
        return self.rows_written / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0


def _hmac_pseudonymize_udf(key: bytes, scope: str) -> UserDefinedFunction:
    """Build a `pandas_udf`-wrapped column expression that masks a string
    column with `MaskingTechnique.HMAC_PSEUDONYMIZATION`, using the real
    `MaskingEngine` (see module docstring for why reusing it -- not
    reimplementing the HMAC logic -- is the point).

    A `pandas_udf` receives one `pandas.Series` per Arrow-batch call
    (batch size controlled by `spark.sql.execution.arrow.maxRecordsPerBatch`,
    10,000 rows by default) rather than one Python call per row, which is
    what makes this fast enough to matter relative to the row-by-row
    `mask_row_dict` loop `data_plane.masking.dataset_masker` uses -- see
    `docs/SCALE_AND_PERFORMANCE.md` for the measured difference.
    """

    # pyspark's `pandas_udf` overloads don't resolve cleanly under mypy
    # strict mode -- a well-known ecosystem gap, not a real type error
    # (verified against a real Spark job in tests/spark/test_masking_job.py).
    @pandas_udf(StringType())  # type: ignore
    def _mask(series):  # type: ignore[no-untyped-def]
        import pandas as pd

        engine = MaskingEngine(key=key)

        def _mask_one(value: object) -> object:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            return engine.mask_value(
                value,
                technique=MaskingTechnique.HMAC_PSEUDONYMIZATION,
                scope=scope,
                field_type=MaskingFieldType.GENERIC,
            )

        return series.map(_mask_one)

    return cast(UserDefinedFunction, _mask)


def mask_columns(
    df: DataFrame,
    *,
    key: bytes,
    columns: dict[str, str] | None = None,
) -> DataFrame:
    """Apply `MaskingTechnique.HMAC_PSEUDONYMIZATION` to every column in
    `columns` (name -> linkage scope), returning a new DataFrame. Pure
    column-at-a-time `withColumn` -- Catalyst can (and, per this phase's
    documentation, does) pipeline these into the same single-pass scan
    over each partition; no intermediate action or collection happens
    here.
    """

    columns = columns if columns is not None else DEFAULT_MASKED_COLUMNS
    result = df
    for column, scope in columns.items():
        if column not in result.columns:
            continue
        result = result.withColumn(column, _hmac_pseudonymize_udf(key, scope)(F.col(column)))
    return result


def run_claims_masking_job(
    spark: SparkSession,
    input_root: str,
    output_root: str,
    *,
    key: bytes,
    columns: dict[str, str] | None = None,
    status_filter: str | None = None,
) -> SparkMaskingResult:
    """Mask the real `claim` table of the claims-warehouse Parquet extract
    at `input_root` (an estate's
    `object_storage_claims_parquet/claims-warehouse` directory) and write
    the masked result to `output_root`, re-partitioned by the same
    `batch=` Hive partition column the source already uses.

    `status_filter`, if given (e.g. `"PAID"`), is applied as a
    `DataFrame.filter` *before* any column is touched -- against a
    Parquet source this becomes a predicate pushed down into the file
    scan itself (row groups whose min/max statistics for `status` cannot
    match are skipped entirely, never deserialized), which is exactly the
    "predicate pushdown" behavior this phase is required to document; see
    this package's README for how to see it in `df.explain()`.

    Never calls `.collect()` or `.toPandas()` on the (potentially large)
    row data -- `.count()` is used only for the small scalar row-count
    metrics this result records, per this phase's "avoid collecting
    large datasets to the driver" requirement.
    """

    claim_dir = f"{input_root}/claim"

    read_start = time.perf_counter()
    df = spark.read.option("mergeSchema", "true").parquet(claim_dir)
    if status_filter is not None:
        df = df.filter(F.col("status") == status_filter)
    rows_read = df.count()
    read_elapsed = time.perf_counter() - read_start

    masked_columns = columns if columns is not None else DEFAULT_MASKED_COLUMNS
    masked_df = mask_columns(df, key=key, columns=masked_columns)

    # Cache before writing: `masked_df` is about to be consumed by both
    # the write action and the row-count action below, and without
    # caching, Spark would re-run the full read+mask pipeline a second
    # time for the count (see this package's README, "Caching").
    masked_df.cache()
    write_start = time.perf_counter()
    writer = masked_df.write.mode("overwrite")
    if "batch" in masked_df.columns:
        writer = writer.partitionBy("batch")
    writer.parquet(output_root)
    write_elapsed = time.perf_counter() - write_start

    # Counted from the in-memory (cached) DataFrame that was just
    # written, not by re-reading `output_root` -- a `status_filter`/
    # `member_fraction` of 0 can legitimately produce zero output rows,
    # which leaves no Parquet files (and therefore no inferable schema)
    # for a fresh `spark.read.parquet(output_root)` call to see.
    rows_written = masked_df.count()
    masked_df.unpersist()
    total_elapsed = read_elapsed + write_elapsed

    return SparkMaskingResult(
        input_path=claim_dir,
        output_path=output_root,
        rows_read=rows_read,
        rows_written=rows_written,
        columns_masked=[c for c in masked_columns if c in df.columns],
        elapsed_seconds=total_elapsed,
        read_elapsed_seconds=read_elapsed,
        write_elapsed_seconds=write_elapsed,
    )


__all__ = [
    "CLAIM_ID_SCOPE",
    "DEFAULT_MASKED_COLUMNS",
    "MEMBER_ID_SCOPE",
    "SparkMaskingResult",
    "mask_columns",
    "run_claims_masking_job",
]
