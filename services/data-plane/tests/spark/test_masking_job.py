"""Real Spark job tests against a real, on-disk `tiny`-scale estate's
claims-warehouse Parquet extract -- no mocking of Spark or of the
filesystem, per `CONTRIBUTING.md`'s data-quality-test convention.

The single most important property under test:
`run_claims_masking_job`'s `pandas_udf` and Phase 3's pure-Python
`MaskingEngine` must produce byte-for-byte the same masked token for the
same real value under the same key/scope (`ADR-0006`'s determinism
guarantee) -- `test_masked_member_id_matches_pandas_engine` proves this
directly rather than asserting it by inspection of the source code.
"""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import MaskingFieldType, MaskingTechnique
from pyspark.sql import SparkSession

from data_plane.masking.engine import MaskingEngine
from data_plane.spark.masking_job import (
    CLAIM_ID_SCOPE,
    MEMBER_ID_SCOPE,
    run_claims_masking_job,
)

TEST_KEY = b"spark-masking-job-test-hmac-key-0123456789"


def test_masked_member_id_matches_pandas_engine(spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path) -> None:
    raw_df = spark.read.option("mergeSchema", "true").parquet(str(claims_warehouse_root / "claim"))
    sample = raw_df.select("claim_id", "member_id").limit(1).collect()[0]
    raw_claim_id, raw_member_id = sample["claim_id"], sample["member_id"]

    out_dir = tmp_path / "masked-member-only"
    result = run_claims_masking_job(
        spark,
        str(claims_warehouse_root),
        str(out_dir),
        key=TEST_KEY,
        columns={"member_id": MEMBER_ID_SCOPE},  # leave claim_id as a stable join key
    )

    masked_df = spark.read.parquet(str(out_dir))
    masked_row = masked_df.filter(masked_df.claim_id == raw_claim_id).select("member_id").collect()[0]

    pandas_engine = MaskingEngine(key=TEST_KEY)
    expected = pandas_engine.mask_value(
        raw_member_id,
        technique=MaskingTechnique.HMAC_PSEUDONYMIZATION,
        scope=MEMBER_ID_SCOPE,
        field_type=MaskingFieldType.GENERIC,
    )

    assert masked_row["member_id"] == expected
    assert masked_row["member_id"] != raw_member_id
    assert result.rows_written == raw_df.count()
    assert result.columns_masked == ["member_id"]


def test_default_columns_masks_member_id_and_claim_id(
    spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "masked-default"
    raw_df = spark.read.option("mergeSchema", "true").parquet(str(claims_warehouse_root / "claim"))
    raw_member_ids = {r["member_id"] for r in raw_df.select("member_id").distinct().collect()}
    raw_claim_ids = {r["claim_id"] for r in raw_df.select("claim_id").distinct().collect()}

    result = run_claims_masking_job(spark, str(claims_warehouse_root), str(out_dir), key=TEST_KEY)

    masked_df = spark.read.parquet(str(out_dir))
    masked_member_ids = {r["member_id"] for r in masked_df.select("member_id").distinct().collect()}
    masked_claim_ids = {r["claim_id"] for r in masked_df.select("claim_id").distinct().collect()}

    assert result.columns_masked == ["member_id", "claim_id"]
    assert masked_member_ids.isdisjoint(raw_member_ids)
    assert masked_claim_ids.isdisjoint(raw_claim_ids)
    assert result.records_per_second() > 0


def test_masking_is_deterministic_across_two_runs(
    spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path
) -> None:
    """Same key, same scope, same value -> same token, whether it is
    computed by one Spark job run or a second, independent one -- the
    Spark-side analogue of
    `tests/masking/test_dataset_masker_against_real_estate.py`'s
    idempotency check.
    """

    out_a = tmp_path / "run-a"
    out_b = tmp_path / "run-b"
    run_claims_masking_job(spark, str(claims_warehouse_root), str(out_a), key=TEST_KEY)
    run_claims_masking_job(spark, str(claims_warehouse_root), str(out_b), key=TEST_KEY)

    a = {(r["claim_id"], r["member_id"]) for r in spark.read.parquet(str(out_a)).collect()}
    b = {(r["claim_id"], r["member_id"]) for r in spark.read.parquet(str(out_b)).collect()}
    assert a == b


def test_status_filter_applies_predicate_pushdown(
    spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "masked-paid-only"
    result = run_claims_masking_job(
        spark, str(claims_warehouse_root), str(out_dir), key=TEST_KEY, status_filter="paid"
    )

    masked_df = spark.read.parquet(str(out_dir))
    statuses = {r["status"] for r in masked_df.select("status").distinct().collect()}
    assert statuses == {"paid"}
    assert result.rows_written == masked_df.count()
    assert result.rows_written > 0


def test_caching_persists_a_dataframe_across_repeated_actions(
    spark: SparkSession, claims_warehouse_root: Path
) -> None:
    """A structural (not timing-based -- see this repo's honesty
    conventions) check of the caching mechanism `docs/SCALE_AND_PERFORMANCE.md`
    and `data_plane/spark/README.md` describe: an uncached DataFrame
    reports no storage level in use; after `.cache()`, it does, and
    repeated actions against it keep returning the same, correct result.
    """

    df = spark.read.parquet(str(claims_warehouse_root / "claim_line"))
    assert df.storageLevel.useMemory is False

    df.cache()
    try:
        first_count = df.count()
        second_count = df.count()
        assert first_count == second_count
        assert df.storageLevel.useMemory is True
    finally:
        df.unpersist()


def test_mask_columns_skips_missing_columns(spark: SparkSession, claims_warehouse_root: Path) -> None:
    from data_plane.spark.masking_job import mask_columns

    df = spark.read.parquet(str(claims_warehouse_root / "diagnosis"))
    result = mask_columns(df, key=TEST_KEY, columns={"member_id": MEMBER_ID_SCOPE, "claim_id": CLAIM_ID_SCOPE})
    # `diagnosis` has neither column -- mask_columns must be a no-op, not raise.
    assert result.columns == df.columns
    assert result.count() == df.count()
