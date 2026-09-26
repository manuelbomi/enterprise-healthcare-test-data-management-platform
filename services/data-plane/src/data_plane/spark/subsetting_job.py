"""A real PySpark reimplementation of one Phase 4 subsetting concept --
"select N% of members, then pull every claim (and every claim line) that
belongs to them" -- using an explicit broadcast join, at horizontal-scale
row counts.

Why this operation, specifically
---------------------------------
`data_plane.subsetting.closure.build_closure` (Phase 4) walks the
referential graph in pure Python/pandas: given a set of selected Member
IDs, it filters every dependent table down to rows that reference one of
them. That closure walk is exactly a join -- `claim` joined to a small
set of selected `member_id`s, then `claim_line` joined to the resulting
`claim_id`s -- and a join between one *large* table (claims, claim lines)
and one *small* table (a sampled few percent of members) is the textbook
case for Spark's broadcast join strategy: instead of shuffling both sides
of the join across the network (a sort-merge join, expensive at real
cluster scale), the small side is serialized once and sent to every
executor, and the large side is filtered locally, partition by partition,
with **no shuffle of the large table at all**. This is the second of the
two Phase 14 operations chosen to scale horizontally (the first is
`data_plane.spark.masking_job`, which needs no join/shuffle at all); see
`docs/SCALE_AND_PERFORMANCE.md` for the measured broadcast-vs-shuffle
comparison and this package's README for how to see the difference in
`df.explain()`.

This is a real subsetting *operation* (referentially closed: every
`claim_line` in the output belongs to a `claim` in the output, which
belongs to a selected member), not a reimplementation of Phase 4's full
six-strategy `selection.py` (percentage/targeted/rare-condition-coverage/
...). Only the "random N% of members, full closure" case is implemented
here -- see `docs/problems/problems_phase_14.md` for what is deliberately left out of
scope.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


@dataclass
class SparkSubsettingResult:
    """What one `run_member_subsetting_job` call actually did."""

    member_fraction_requested: float
    members_sampled: int
    claims_input_rows: int
    claims_output_rows: int
    claim_lines_input_rows: int
    claim_lines_output_rows: int
    elapsed_seconds: float

    def selectivity(self) -> float:
        """Fraction of input claims that made it into the subset -- should
        track `member_fraction_requested` reasonably closely (claims are
        roughly uniformly distributed across members in the Phase 1
        estate), a cheap sanity check a benchmark report can print.
        """

        return self.claims_output_rows / self.claims_input_rows if self.claims_input_rows else 0.0


def _sample_member_ids(claims: DataFrame, *, fraction: float, seed: int) -> DataFrame:
    """The small side of the broadcast join: a `fraction` sample of the
    *distinct* member ids present in `claims`. `.distinct()` here does
    shuffle (a hash-partitioned aggregation, unavoidable for exact
    deduplication) -- but it shuffles only the (small) `member_id` column
    projection, not the wide claims rows, and it happens exactly once,
    before the broadcast join this function's caller performs. See this
    package's README for the honest accounting of which stages in this
    job do and do not shuffle.
    """

    return claims.select("member_id").distinct().sample(fraction=fraction, seed=seed)


def run_member_subsetting_job(
    spark: SparkSession,
    input_root: str,
    output_root: str,
    *,
    member_fraction: float = 0.02,
    seed: int = 20240101,
) -> SparkSubsettingResult:
    """Select `member_fraction` of the distinct members referenced by the
    claims-warehouse `claim` table at `input_root`, then write every claim
    and every claim line belonging to those members to `output_root/claim`
    and `output_root/claim_line`, via two broadcast joins (never a
    sort-merge shuffle join between two large tables).

    Never calls `.collect()`/`.toPandas()` on `claims`, `claim_lines`, or
    either subset DataFrame -- only `.count()` (a scalar aggregate action)
    is used, for the row-count metrics this result records, per this
    phase's "avoid collecting large datasets to the driver" requirement.
    """

    claim_dir = f"{input_root}/claim"
    claim_line_dir = f"{input_root}/claim_line"

    start = time.perf_counter()

    claims = spark.read.option("mergeSchema", "true").parquet(claim_dir)
    claim_lines = spark.read.parquet(claim_line_dir)
    claims_input_rows = claims.count()
    claim_lines_input_rows = claim_lines.count()

    member_sample = _sample_member_ids(claims, fraction=member_fraction, seed=seed)
    members_sampled = member_sample.count()

    # Broadcast join #1: filter the large `claims` table down to the
    # sampled members. The join key side (`member_sample`) is small
    # (a few percent of the member population) -- `F.broadcast(...)`
    # tells Catalyst to send it to every executor rather than shuffling
    # `claims` itself.
    subset_claims = claims.join(F.broadcast(member_sample), on="member_id", how="inner")

    # Broadcast join #2: the referential closure's second hop --
    # `claim_line` has no `member_id` of its own (see
    # `reference_data/domain.py::ClaimLine`), only `claim_id`, so the
    # closure walk is a second broadcast join against the (still small)
    # set of claim ids selected by join #1.
    subset_claim_ids = subset_claims.select("claim_id").distinct()
    subset_claim_lines = claim_lines.join(
        F.broadcast(subset_claim_ids), on="claim_id", how="inner"
    )

    # Cache before writing -- each subset DataFrame is consumed by both
    # its own write action and its own row-count action below (see
    # `data_plane/spark/README.md`, "Caching").
    subset_claims.cache()
    subset_claim_lines.cache()

    writer = subset_claims.write.mode("overwrite")
    if "batch" in subset_claims.columns:
        writer = writer.partitionBy("batch")
    writer.parquet(f"{output_root}/claim")
    subset_claim_lines.write.mode("overwrite").parquet(f"{output_root}/claim_line")

    # Counted from the in-memory (cached) DataFrames that were just
    # written, not by re-reading `output_root` -- a `member_fraction` of
    # 0 legitimately produces zero output rows, which leaves no Parquet
    # files (and therefore no inferable schema) for a fresh
    # `spark.read.parquet(...)` call to see.
    claims_output_rows = subset_claims.count()
    claim_lines_output_rows = subset_claim_lines.count()
    subset_claims.unpersist()
    subset_claim_lines.unpersist()

    elapsed = time.perf_counter() - start

    return SparkSubsettingResult(
        member_fraction_requested=member_fraction,
        members_sampled=members_sampled,
        claims_input_rows=claims_input_rows,
        claims_output_rows=claims_output_rows,
        claim_lines_input_rows=claim_lines_input_rows,
        claim_lines_output_rows=claim_lines_output_rows,
        elapsed_seconds=elapsed,
    )


__all__ = ["SparkSubsettingResult", "run_member_subsetting_job"]
