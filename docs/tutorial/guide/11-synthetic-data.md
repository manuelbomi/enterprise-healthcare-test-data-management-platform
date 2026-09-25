# Chapter 11 — Synthetic data

## The concept

Synthetic data is data that was never derived from any real record at
all — generated from statistical models, rules, or a fake-data library
to look realistic, with no real person or real event behind it anywhere
in its history. This is a stronger property than masking: a masked
value started as a real value and was transformed; a synthetic value
never started as anything real. Synthetic data solves two different
problems in this platform, at two different pipeline stages, and this
repository deliberately builds two separate components for them rather
than one.

## Two components, two jobs, not one

| | `data_plane.reference_data` (Phase 1) | `data_plane.synthetic` (Phase 5) |
|---|---|---|
| Job | Build the *entire* estate from nothing | *Supplement* an already-subsetted-and-masked dataset (or a standalone dataset) |
| When it runs | First — before anything else in the pipeline exists | One stage later, after masking: `... -> MASK -> GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> ...` |
| Edge cases | Injects its own (Chapter 1's `tiny`-scale estate already contains every category) | Targets specific, on-demand QA scenarios that may not occur naturally in a random subset |

`data_plane.reference_data/README.md` makes this distinction explicit:
"this package generates the *source-side* estate itself" — everything
Chapters 1, 3, 5, 6, 7, and 9 of this guide have been running against
came from here. It spans five heterogeneous simulated source systems
(PostgreSQL/SQLite enrollment, a Parquet claims warehouse, an NDJSON
clinical data lake, a CSV PBM extract, and a partner lab feed in two
shapes), at one of four named scale profiles: `tiny` (25 members,
CI/unit-test default), `developer` (250), `qa` (2,500), `performance`
(20,000).

`data_plane.synthetic/README.md` is explicit about *not* being confused
with the above: it implements eleven required scenario generators
(`scenarios.py`) — a high-cost claim, a claim referencing a member that
doesn't exist, a member with an unusually deep claim history, and eight
more — each producing either a schema-valid `SYNTHETIC` record or a
deliberately, specifically broken `NEGATIVE_TEST` one.

## Try both, end to end

```bash
cd services/data-plane

# Phase 1: build the base estate
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

# Phase 5: augment a subset of it with two named scenarios
python -m data_plane.subsetting.cli --estate-dir data/tmp/synthetic-estate \
    --out-dir data/tmp/synthetic-estate-subset --strategy fixed_population --param count=8
python -m data_plane.synthetic.cli \
    --base-estate-dir data/tmp/synthetic-estate-subset \
    --out-dir data/tmp/synthetic-estate-scenarios \
    --scenario high_cost_claims --scenario invalid_claim_references
```

This prints, per scenario, its provenance and row count, the full
provenance rollup, and writes the combined estate plus
`synthetic_generation_manifest.json`.

## Never mistaken for real data: two independent mechanisms

Every row this platform ever produces carries a `data_provenance`
column (`MASKED_PRODUCTION_LIKE` / `SYNTHETIC` / `NEGATIVE_TEST` —
`healthcare_tdm_contracts.DataProvenance`) — the authoritative signal,
because it survives arbitrary downstream re-shuffling of rows. Every
manifest also carries a provenance rollup, and every scenario-generated
claim lands in a dedicated `synthetic-scenarios` Parquet batch — the
fast, human/audit-facing signal. `data_plane.synthetic.provenance`'s
module docstring explains why neither signal alone is sufficient (the
same belt-and-suspenders reasoning Chapter 8 covers for Phase 4's
three-way orphan classification). This matters because it is exactly
what Chapter 12's certification pipeline checks: the `provenance` gate
verifies the provenance rollup accounts for every final row, so a
synthetic or negative-test record can never silently be presented as
real masked data downstream.

## Why generating fake data well is itself hard

It's tempting to think of synthetic generation as "just call a
fake-data library." Two things this platform's real code has to get
right that a naive approach wouldn't:

1. **IDs must never collide with real (or already-synthetic) IDs.**
   `data_plane.synthetic.ids.ScenarioIdAllocator` mints scenario-sub-range
   IDs (`SYN-<ENTITY>-SCEN-<seq>`) that can never collide with Phase 1's
   own estate-native IDs, plus self-describing dangling-reference IDs
   (`...-SCEN-NX-<tag>-<seq>`) for negative-test scenarios specifically,
   so a broken reference is always identifiable as intentional.
2. **Referenced entities (Plan, Provider, Pharmacy, Diagnosis,
   Procedure) must exist and be consistent.**
   `data_plane.synthetic.reference_pool.ReferencePool` draws these from
   a real base estate (or generates them fresh in standalone mode) so a
   synthetic claim references a Provider that's actually there, not a
   fabricated ID no other table knows about.

## Where to go next

Continue to [Chapter 12 — Dataset certification](12-dataset-certification.md),
or read `docs/tutorial/02-synthetic-data-estate.md` and
`docs/tutorial/05-synthetic-scenario-generation.md` for the full
implementation-depth walkthroughs of both components.
