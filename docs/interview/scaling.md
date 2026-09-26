# Scaling: from a laptop to a 500 TB estate, honestly

This is the hardest set of interview questions to answer well, because the
honest answer requires saying, out loud, exactly which numbers below are
*measured* and which are *modeled* — the same discipline
`docs/CAPACITY_COST_TRADEOFFS.md` and `docs/SCALE_AND_PERFORMANCE.md`
already apply to this repository's own documentation. Overclaiming
cluster-scale numbers this repository never measured would be a worse
interview answer than admitting the boundary of what was actually run.

## Q: How would you safely create QA data from a 500 TB healthcare estate?

**The pipeline doesn't change with scale — only the numbers feeding it do.**
The same nine-stage pipeline `docs/interview/system-design.md` describes
(`INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK -> GENERATE -> VALIDATE ->
CERTIFY -> PUBLISH`) runs unmodified whether the source estate is this
repository's `tiny` scale profile (a few hundred rows) or a real 500 TB
production estate — every stage's code
(`data_plane.discovery`/`subsetting`/`masking`/`certification`) is written
against `pandas`/local files today and is designed to be re-platformed onto
Spark without changing its logic (`ARCHITECTURE.md` section 2.2's "every job
here is designed to be run either locally... or on Spark," and Phase 14's
real, if partial, proof of that — see the Databricks/Spark question below).
Concretely, for a 500 TB estate:

1. **Never subset naively against the full 500 TB.** `data_plane.subsetting`'s
   six sizing strategies (`healthcare_tdm_contracts.SubsettingStrategy`:
   `percentage`, `fixed_population`, `stratified`, `date_window`,
   `business_rule`, `risk_edge_case`) select a referentially-closed
   population anchored at `Member` *before* masking touches anything —
   masking a 500 TB estate to produce a 10 TB QA copy is far more expensive
   than subsetting first, then masking only the ~10 TB that survives
   selection. `data_plane.subsetting.closure` walks the relationship graph
   so every claim/encounter/diagnosis reachable from a selected member comes
   along, and nothing else does.
2. **Guarantee rare-case coverage without inflating the subset.** A
   percentage-based subset of a 500 TB estate will, by construction, under-
   represent rare conditions/claim patterns proportionally to its size
   (`docs/CAPACITY_COST_TRADEOFFS.md` section 5) — this is where Phase 4's
   `risk_edge_case` strategy and Phase 5's synthetic scenario generation
   (`data_plane.synthetic.scenarios`) matter at this scale specifically:
   a guaranteed rare scenario costs a *fixed*, small number of rows
   regardless of whether the base estate is 5 GB or 500 TB
   (`docs/CAPACITY_COST_TRADEOFFS.md` section 6).
3. **Mask deterministically so the resulting QA data is still testable.**
   [ADR-0006](../adr/0006-deterministic-masking-strategy.md)'s keyed
   pseudonymization is what makes the *resulting* QA copy — however large —
   actually usable: joins across every table/system keep working. See
   `docs/interview/tradeoffs.md` item 1 for the referential-integrity
   tradeoff this depends on.
4. **Certify the final output, not the plan.** The same eleven
   certification gates (`data_plane.certification.gates`) that run against
   this repository's `tiny`-scale estate are what would gate a real 500 TB
   pipeline's QA output before publish — the gate logic does not change
   with data volume; only the wall-clock cost of running it does.
5. **Never let 50 teams turn "10% of 500 TB" into fifty separate 50 TB
   copies.** See the next question — this is exactly what Phase 7/8's
   shared-snapshot architecture prevents by construction.

**What is honestly modeled here, not measured:** this repository has never
run any of these stages against 500 TB of real (or synthetic) data.
`healthcare_tdm_contracts.capacity.IllustrativeCapacityScenario` /
`control_plane.domain.capacity.planner.illustrative_capacity_plan` implement
`ROADMAP.md`'s own worked example — "Production: 100 TB, QA 10%, SIT 5%,
UAT 15%" — as a *real, runnable, configurable* model (not hand-waved prose),
extended honestly to DEV and PERFORMANCE. Running it against the default
100 TB scenario produces a real, deterministic answer:

```
Naive total (5 independent copies):  140.0 TB
  tier=standard   : shared snapshot = 15.0 TB   (covers DEV, QA, SIT, UAT)
  tier=performance: shared snapshot = 100.0 TB  (PERFORMANCE alone)
Shared total: 115.0 TB
Savings: 25.0 TB (17.9%)
```

This is arithmetic over a configurable model, not a benchmark — pass it a
500 TB production figure instead of 100 TB and it produces the
proportionally scaled answer (`docs/CAPACITY_COST_TRADEOFFS.md` section 4).
**Why PERFORMANCE is modeled at 100%, not a shared percentage, and why that
matters even more at 500 TB:** subsetting undermines the entire purpose of
performance testing (query plans, index behavior, cache eviction — all of
which only degrade at real volume). A senior engineer's honest answer names
this exception rather than presenting "shrink everything to 10%" as a
universal rule.

## Q: How do you manage weekly refreshes across 50 teams?

**The real mechanism, demonstrated with two consumers, designed to
generalize to fifty:** Phase 7's `healthcare_tdm_contracts.RefreshPolicy`
(the contract type `control_plane.domain.lifecycle` reads/writes)
+ `cadence.py` gives every environment a runtime-configurable refresh
cadence (`PUT /api/v1/lifecycle/refresh-policies`, never hardcoded) — this
repository's own five example environments run DEV/QA weekly, SIT biweekly,
UAT release-driven, PERFORMANCE monthly/on-demand, each with correctly
computed `next_refresh_at` demonstrated in a real run
(`scripts/demo_phase7_lifecycle.py`). Phase 10's
`healthcare_tdm_contracts.BusinessConsumer`/`ConsumerDatasetRequest`
(likewise contract types `control_plane.domain.governance` operates on)
is the layer that scales this from "five environments" to "N organizational
consumers": a `ConsumerDatasetRequest` carries its own subset-size hint and
refresh cadence, and `GovernanceRepository.fulfill_consumer_request` calls
directly into the *same* `LifecycleRepository` (same `Session`, same
transaction — [ADR-0014](../adr/0014-masking-governance-lives-in-control-plane.md))
that already schedules refreshes for every other environment. There is no
second, parallel scheduling implementation for governed consumers — a fifty-
first `BusinessConsumer` would use the identical code path the two seeded
rows (`LEFT_ARM`, `RIGHT_ARM`) already exercise in
`scripts/demo_phase10_governance.py`.

**Who actually decides *when* "weekly" runs:** `control_plane.domain.lifecycle.scheduler.RefreshOrchestrator`
(an `ABC` with exactly two methods, `due_refreshes`/`run_due_refreshes`) is
the seam a real production deployment's scheduler plugs into
([ADR-0012](../adr/0012-refresh-orchestration-abstraction.md)). At 50 teams'
scale, that seam matters more, not less: `LocalRefreshOrchestrator` is a
real, tested, in-process implementation exposed over HTTP
(`GET /api/v1/lifecycle/scheduler/due`, `POST /api/v1/lifecycle/scheduler/run-due`)
so an *external* scheduler (Airflow, a Databricks Workflow, a Kubernetes
CronJob) can either fan out one task per due request (per-request
retry/alerting) or trigger one sweep and let this service isolate failures
itself, per [ADR-0012](../adr/0012-refresh-orchestration-abstraction.md)'s
own worked example of both integration shapes. **The honest limit at 50-team
scale:** `run_due_refreshes` has no distributed lock — two scheduler
instances (or an Airflow retry racing an in-flight sweep) calling
`run-due` concurrently is a real, open gap
(`problems_phase_07.md` P7-2, restated in
`docs/runbooks/duplicate-requests-and-revoked-datasets.md`'s "the one gap
this does NOT close" section). A real 50-team deployment would need the
external scheduler's own concurrency control (Airflow's single-active-DAG-
run semantics, or a Kubernetes CronJob's `concurrencyPolicy: Forbid`) —
this repository does not implement that itself, and says so.

## Q: How do you prevent each team from making another 20 TB copy?

**This is Phase 7/8's architecture, not a policy.** `EnvironmentDatasetRequest.current_version_id`
is a foreign key into `DatasetVersion` — requesting a dataset into a new
environment or for a new consumer never copies `storage_uri`, it points at
the existing one. A team's "new" 20 TB request against an *already-
registered* dataset version costs zero additional physical storage by
construction, not by convention a well-meaning team member has to remember
to follow.

**This is quantified, not just asserted.** A real run of
`scripts/demo_phase8_capacity.py` against five real environments sharing one
registered dataset version measured:

```
Environments requesting this dataset: 5
Distinct physical dataset versions actually stored: 1
Naive total (if each environment had its own copy): 2,341,005 bytes
Actual shared total (Phase 7's real architecture):   468,201 bytes
Savings: 1,872,804 bytes (80.0%)
```

`control_plane.domain.capacity.planner.CapacityPlanner.capacity_plan`
computes both the naive total (what N independent copies would cost) and
the actual shared total (what the real foreign-key architecture costs) from
real registered `DatasetVersion.size_bytes` rows — this is arithmetic over
real data, not a projection. Scale this to a hypothetical "50 teams, each
wanting a 20 TB QA copy weekly": if all 50 can genuinely share the same
dataset version (same subset percentage, same masking policy, same refresh
timing), the naive-vs-shared ratio is 50:1 regardless of whether each
"copy" would have been 20 TB or 20 GB — `docs/CAPACITY_COST_TRADEOFFS.md`
section 3 states this explicitly: "the percentage savings scales with the
number of sharing environments, not with dataset size."

**The one honest caveat, and it's the real answer to "what if a team
insists on their own copy":** sharing only works if the requesting team is
genuinely willing to use the *same* version. A team with a real requirement
for a different subset percentage, a different masking policy, or
different refresh timing cannot share — `docs/CAPACITY_COST_TRADEOFFS.md`
section 4 works through exactly this case for PERFORMANCE testing (modeled
at 100% of production, in its own `share_tier`, specifically because
subsetting would invalidate what performance testing measures). A senior
engineer's answer here should distinguish "we architecturally prevent
*unnecessary* duplicate copies" (true, and quantified above) from "we
prevent all duplicate copies" (false, and would be the wrong design goal —
some duplication reflects a genuinely different requirement, not waste).
The remaining honest gap: nothing in this repository yet *deletes* storage
for versions nobody references any more — `CapacityPlanner.vacuum_candidates`
identifies them (a real, live-computed query over expired/revoked/
rolled-back versions referenced by zero environments) but is deliberately
read-only, because no storage adapter exists yet to delete through
(`problems_phase_08.md` P8-3, `problems_master.md` P0-3).

## Q: How would Databricks/Spark fit?

**The honest framing first:** every Spark job this repository has written
(`data_plane.spark.session.get_local_spark_session`) runs `master("local[*]")`
— one JVM process on one machine. There is no `spark-worker`/`spark-master`
service anywhere in `infra/`, and no real Delta Lake write is executed
anywhere (`delta-spark` remains a declared, unwired dependency —
[ADR-0017](../adr/0017-pyspark-benchmark-tooling-in-data-plane.md)). Any
answer to this question has to say that plainly before citing a single
number, because Databricks *is* a managed Spark cluster — the honest answer
is about what would carry over unmodified versus what has never been
exercised at all.

**What would carry over unmodified:** every Spark job here is written to be
Databricks-compatible in the literal sense — no vendor-specific API is used
anywhere. `data_plane.spark.masking_job.run_claims_masking_job` reuses
Phase 3's real `MaskingEngine` unmodified inside an Arrow-vectorized
`pandas_udf` (proven byte-for-byte identical to the pandas engine's own
output under the same key/scope —
`tests/spark/test_masking_job.py::test_masked_member_id_matches_pandas_engine`);
`data_plane.spark.subsetting_job.run_member_subsetting_job` reimplements
Phase 4's referential-closure concept as two broadcast joins
(`claims.join(F.broadcast(member_sample), on="member_id")`). Both are chosen
specifically because they're the operations that most plausibly benefit
from horizontal scaling: masking is embarrassingly row-independent (no
shuffle needed at all — a `pandas_udf` just needs Arrow-batched execution
instead of one Python call per row), and referential-closure subsetting
*is* a join between one large table and one small table — the textbook
broadcast-join case.

**Real, measured evidence this actually works, at the one scale it was
measured at** (`docs/SCALE_AND_PERFORMANCE.md`, real runs, Windows,
PySpark 4.2.0, `local[*]`, 28 CPUs):

| | `qa` scale (10,726 claims) | `performance` scale (105,936 claims) |
|---|---|---|
| `spark_masking[claim]` records/sec | 1,707 | **12,714** |

A 7.4x throughput increase for a 9.9x row-count increase — Spark's fixed
per-job overhead (query planning, Arrow batch setup, JVM<->Python worker
round trips) amortizes over more rows; the crossover point where paying
that overhead becomes worthwhile is somewhere between 10K and 106K rows
*on this specific job, on this specific machine*. Real captured
`df.explain()` output proves the mechanism, not just the number:
`PushedFilters` in the physical plan proves predicate pushdown reached the
Parquet reader itself (filtering `claim` by `status`), and
`BroadcastHashJoin`/`BroadcastExchange` (not `SortMergeJoin`) prove the
large `claim` table was read once and never shuffled during subsetting.

**What genuinely does not carry over, and would need real work on a real
Databricks workspace:**

- **Cluster-scale numbers were never measured, and this repository never
  claims otherwise.** `docs/SCALE_AND_PERFORMANCE.md` states outright that
  a distributed executor fleet's behavior — real network shuffle cost, real
  data skew across partitions, real autoscaling — was never exercised.
  Extrapolating the `local[*]` throughput curve above to a cluster would be
  a guess, not evidence; the honest position is that the curve's *shape*
  (fixed overhead amortizing with scale) is the transferable finding, not
  its absolute numbers.
- **Data skew is documented conceptually, not reproduced.** The Phase 1
  estate's bounded-random member->claim fan-out doesn't produce a
  realistically skewed key, and fabricating one just to report a skew
  number would violate this repository's own honesty convention
  (`problems_phase_14.md` P14-2).
- **No real Delta Lake write exists anywhere.** [ADR-0007](../adr/0007-delta-parquet-data-format.md)
  already chose Delta for versioned/mutable tables, but Phase 14
  deliberately didn't execute one — resolving `io.delta:delta-spark_*`
  Maven coordinates requires a live network fetch with no guaranteed warm
  cache in every review environment, a larger runtime dependency than
  benchmark tooling warranted. `OPTIMIZE`/`ZORDER`/`VACUUM`/the transaction
  log are documented conceptually in `data_plane/spark/README.md`, not
  measured (`problems_phase_14.md` P14-1) — this is exactly the piece a
  real Databricks migration would need to build for real, since Databricks'
  own value proposition leans heavily on managed Delta.
- **Neither Spark job is wired into the control plane's job orchestrator.**
  `JobType.SPARK_MASKING`/`SPARK_SUBSETTING` don't exist — this is the same
  "engine exists, job-submission plumbing does not yet" gap
  `ARCHITECTURE.md`'s Phase 3/4 notes already document for the pandas-engine
  versions of these same two operations (`problems_phase_14.md` P14-4). A
  Databricks Workflow submitting these jobs is architecturally exactly the
  kind of external trigger [ADR-0012](../adr/0012-refresh-orchestration-abstraction.md)
  already designed a seam for (the same `due_refreshes`/`run_due_refreshes`
  pattern) — but that seam has never been pointed at a Spark job
  specifically, only at refresh execution.
- **The comparison itself is not apples-to-apples yet.** `spark_masking[claim]`
  masks only two columns of one table with one technique
  (`HMAC_PSEUDONYMIZATION`); the pandas comparison masks the full Phase 3
  policy across all fourteen entities and eight techniques
  (`problems_phase_14.md` P14-5) — reimplementing Phase 3's entire policy in
  Spark was explicitly out of Phase 14's scope. A real Databricks migration
  would need to close this gap before treating the local-mode numbers above
  as a real capacity-planning input.
