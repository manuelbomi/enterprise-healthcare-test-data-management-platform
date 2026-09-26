# `data_plane.synthetic` — synthetic scenario generation (Phase 5)

Supplements an already-subsetted-and-masked dataset (or produces a
standalone dataset) with deliberately constructed *scenario* records a
QA/test engineer needs on demand — a high-cost claim, a claim referencing
a member that doesn't exist, a member with an unusually deep claim
history — scenarios that may not occur naturally, or often enough, in a
random subset.

**Read [`docs/tutorial/05-synthetic-scenario-generation.md`](../../../../../docs/tutorial/05-synthetic-scenario-generation.md)
for the full walkthrough with real output before using this package.**

Not to be confused with `data_plane.reference_data` (Phase 1), which
generates the *entire* synthetic estate from nothing and injects its own
edge cases as part of that build. This package runs one pipeline stage
later (`ARCHITECTURE.md`: `... -> MASK -> GENERATE OPTIONAL SYNTHETIC
DATA -> VALIDATE -> ...`) and only ever augments/supplements.

## Module map

| Module | Responsibility |
|---|---|
| `ids.py` | `ScenarioIdAllocator` — mints scenario-sub-range IDs (`SYN-<ENTITY>-SCEN-<seq>`) that can never collide with Phase 1 estate-native IDs, plus self-describing dangling-reference IDs (`...-SCEN-NX-<tag>-<seq>`) for negative-test scenarios. |
| `provenance.py` | Adds `data_provenance`/`scenario_type`/`synthetic_batch_id` columns to every row this phase writes, and tags every pre-existing base-estate row `MASKED_PRODUCTION_LIKE` in an "augment" run. |
| `reference_pool.py` | `ReferencePool` — the Plan/Provider/Pharmacy/Diagnosis/Procedure IDs scenario generators link new records against; drawn from a base estate, or generated fresh in standalone mode. |
| `scenarios.py` | The eleven required scenario generator functions (`SCENARIO_GENERATORS`), each producing a `ScenarioBatch`. |
| `merge.py` | Merges a `ScenarioBatch`'s rows into a `RawEstate` (reused from `data_plane.subsetting.estate_io`), routing claims into a dedicated `synthetic-scenarios` Parquet batch. |
| `normalize.py` | Homogenizes row key sets before writing, so heterogeneous provenance-column sets across generators never break `data_plane.subsetting.writer`'s CSV writer. |
| `manifest.py` | Assembles the `healthcare_tdm_contracts.SyntheticGenerationManifest` a generation run produces. |
| `engine.py` | `generate_synthetic_scenarios`, the end-to-end orchestrator (both augment and standalone modes). |
| `cli.py` | `python -m data_plane.synthetic.cli`, the command-line entry point. |

## Running it

```bash
# From services/data-plane, with the package installed (pip install -e .):

# Augment an existing estate (e.g. a Phase 4 subset) with scenarios:
python -m data_plane.synthetic.cli \
    --base-estate-dir data/tmp/synthetic-estate-subset \
    --out-dir data/tmp/synthetic-estate-scenarios \
    --scenario high_cost_claims --scenario invalid_claim_references

# Generate a standalone scenario-only dataset:
python -m data_plane.synthetic.cli \
    --out-dir data/tmp/synthetic-scenarios-standalone \
    --all-scenarios
```

This prints, per scenario, its provenance and row count, the total row
counts per entity, the full provenance rollup, and writes the combined
estate (same five-source-system layout as Phase 1/3/4) plus
`synthetic_generation_manifest.json`.

## Why "never mistaken for a real record" needed two mechanisms, not one

Every row carries a `data_provenance` column (`MASKED_PRODUCTION_LIKE` /
`SYNTHETIC` / `NEGATIVE_TEST`) — the authoritative signal, because it
survives arbitrary downstream re-shuffling of rows. Every manifest also
carries a provenance rollup, and every scenario-generated Claim lands in
a dedicated `synthetic-scenarios` Parquet batch — the fast,
human/audit-facing signal. Neither alone is sufficient: see
`provenance.py`'s module docstring for the full reasoning (the same
belt-and-suspenders pattern Phase 4 already uses for its three-way
orphan classification).

## What this phase does and does not cover

- Implements all eleven required scenarios as real, distinct generator
  functions (`scenarios.py`), each schema-valid (`SYNTHETIC`) or
  deliberately, specifically broken (`NEGATIVE_TEST`) — see that module's
  docstring for the per-scenario provenance justification table.
- Reuses `data_plane.subsetting.estate_io`/`writer.py` for reading and
  writing the multi-format estate rather than reimplementing them.
- Does **not** learn scenario parameters from real distribution
  statistics (cost thresholds, drug-interaction pairs, boundary dates are
  hand-authored) — see `docs/problems/problems_phase_05.md`.
- Does **not** yet wire into a control-plane job or metadata-plane
  snapshot registry — same scope boundary Phases 3/4 documented for
  their own outputs.
