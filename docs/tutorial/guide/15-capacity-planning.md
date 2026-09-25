# Chapter 15 — Capacity planning

## The concept

Storage and compute cost real money, and lower environments — plural,
per Chapter 4 — can silently accumulate far more footprint than anyone
intended if nobody is tracking it: five environments, each thinking
they need "their own copy," each refreshed on their own schedule, with
old versions nobody ever cleans up. Capacity planning is the discipline
of making that footprint visible and quantified, before it becomes an
unpleasant budget surprise, and identifying what can safely be reclaimed.

## Two packages, split on purpose

`ROADMAP.md` Phase 8 asks for two genuinely different things:
*measuring* real bytes off real files (only meaningful against a real
directory on disk — Chapter 14's `data_plane.capacity`), and *planning*
capacity across dataset versions and environments the metadata plane
already tracks (only meaningful against the database — Chapter 13's
`control_plane.domain.lifecycle`). Mixing them into one module would
mean either the data plane reaching into the control plane's database,
or the control plane reaching into object storage directly — both
violate plane separation ([ADR-0003](../../adr/0003-plane-separation.md)).
[ADR-0013](../../adr/0013-capacity-planning-plane-split.md) records the
full reasoning for splitting `data_plane.capacity` (real measurement)
from `control_plane.domain.capacity` (real aggregation over already-
registered data).

## What Chapter 13's architecture already bought, made into a number

Chapter 13 established that `EnvironmentDatasetRequest` rows reference
one `DatasetVersion`, never a physical copy. `CapacityPlanner.capacity_plan`
turns that architectural fact into a concrete comparison: it sums the
exact same `DatasetVersion.size_bytes` once per environment request
(`naive_total_storage_bytes` — "what if each environment had its own
copy") and once per *distinct* version actually referenced
(`shared_total_storage_bytes` — the real total). Real output from
`scripts/demo_phase8_capacity.py`
(`docs/tutorial/08-storage-compute-capacity-planning.md`):

```
STEP 4 -- Real capacity plan: naive-if-independent-copies vs. Phase 7's real shared-snapshot cost
Environments requesting this dataset: 5
Distinct physical dataset versions actually stored: 1
Naive total (if each environment had its own copy): 2,341,005 bytes
Actual shared total (Phase 7's real architecture):   468,201 bytes
Savings: 1,872,804 bytes (80.0%)
```

`2,341,005` is exactly `5 x 468,201` — five environments, each counted
as if it owned an independent copy of the same real measured size. This
ratio is a mechanical consequence of the architecture Chapter 13
describes, not a number this phase invents — and it is not universal:
`services/control-plane/tests/test_capacity_planner.py` covers the
adversarial case where two environments are on *different* versions, and
correctly reports zero storage savings, because sharing only saves
storage when environments actually use the same version.

## Vacuum candidates: reclaiming what's genuinely unreferenced

```
STEP 5 -- Vacuum candidates: an unreferenced, revoked version is identified as reclaimable
Vacuum candidates: 1
  version_number=2 status=revoked reclaimable_bytes=153,844 reason='status=revoked, unreferenced by any environment request'
Version 1 (still referenced by 5 environments) correctly does NOT appear above.
```

A version only qualifies as reclaimable if it is *both* revoked/expired
*and* unreferenced by any current `EnvironmentDatasetRequest` — a
version still in active use, even if flagged revoked, is never
mistakenly offered up for deletion.

## What is real, and what is honestly a model or illustration

| Number | Real or modeled? |
|---|---|
| On-disk bytes, Parquet compression ratios | **Real** — `data_plane.capacity.footprint` |
| Naive-vs-shared storage totals, vacuum candidates | **Real** — real `size_bytes`, summed over real registered rows |
| Compute-unit-hours / annual processing volume | **Modeled** — a documented, unbenchmarked throughput constant (`ROWS_PER_COMPUTE_UNIT_HOUR`) applied to real row counts |
| Incremental-refresh savings | **Modeled** — real row-count deltas, describing what an incremental-refresh engine *would* save if this platform built one (it does not) |
| "Production 100 TB, QA 10%, ..." scenario | **Illustrative** — a configurable hypothetical, never measured |

`docs/CAPACITY_COST_TRADEOFFS.md` is explicit that overclaiming
precision is worse than being honest about which of these four
categories a number belongs to — every capacity contract in
`healthcare_tdm_contracts.capacity` documents which kind it is in its
own docstring.

## Where to go next

Continue to [Chapter 16 — Platform integrity](16-platform-integrity.md),
or read `docs/tutorial/08-storage-compute-capacity-planning.md` and
`docs/CAPACITY_COST_TRADEOFFS.md` in full.
