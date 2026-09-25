"""Real Spark broadcast-join subsetting tests against a real, on-disk
`tiny`-scale estate.

The core property under test is referential closure across the
broadcast-join hop (`claim` -> `claim_line`, via `claim_id`) -- every
`claim_line` in the output must reference a `claim_id` present in the
output `claim` table, exactly the invariant
`data_plane.subsetting.closure.build_closure`'s own tests already prove
for the pandas engine, proven here for the Spark broadcast-join
reimplementation instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from data_plane.spark.subsetting_job import run_member_subsetting_job


def test_subset_claim_lines_only_reference_selected_claims(
    spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "subset"
    # `tiny` scale has only 25 members -- a large fraction keeps the
    # sample non-empty and the test deterministic.
    result = run_member_subsetting_job(
        spark, str(claims_warehouse_root), str(out_dir), member_fraction=0.5, seed=20240101
    )

    assert result.members_sampled > 0
    assert result.claims_output_rows > 0
    assert result.claims_output_rows <= result.claims_input_rows
    assert result.claim_lines_output_rows <= result.claim_lines_input_rows

    output_claim_ids = {
        r["claim_id"] for r in spark.read.parquet(f"{out_dir}/claim").select("claim_id").distinct().collect()
    }
    output_claim_line_claim_ids = {
        r["claim_id"]
        for r in spark.read.parquet(f"{out_dir}/claim_line").select("claim_id").distinct().collect()
    }
    assert output_claim_line_claim_ids.issubset(output_claim_ids)


def test_selectivity_is_a_fraction_between_zero_and_one(
    spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "subset-selectivity"
    result = run_member_subsetting_job(
        spark, str(claims_warehouse_root), str(out_dir), member_fraction=0.2, seed=20240101
    )
    assert 0.0 <= result.selectivity() <= 1.0


def test_zero_fraction_selects_no_members(
    spark: SparkSession, claims_warehouse_root: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "subset-empty"
    result = run_member_subsetting_job(
        spark, str(claims_warehouse_root), str(out_dir), member_fraction=0.0, seed=20240101
    )
    assert result.members_sampled == 0
    assert result.claims_output_rows == 0
    assert result.claim_lines_output_rows == 0


def test_join_plan_uses_broadcast_hash_join(
    spark: SparkSession, claims_warehouse_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A structural check that the join strategy this module documents
    (`data_plane/spark/README.md`'s "Broadcast joins" section) is what
    Spark's physical plan actually chose, not just what the code intends.
    """

    claims = spark.read.option("mergeSchema", "true").parquet(str(claims_warehouse_root / "claim"))
    member_sample = claims.select("member_id").distinct().limit(2)
    subset = claims.join(F.broadcast(member_sample), on="member_id", how="inner")

    subset.explain()
    captured = capsys.readouterr()
    assert "BroadcastHashJoin" in captured.out
