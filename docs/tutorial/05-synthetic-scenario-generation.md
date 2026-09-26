# Tutorial 05 — Synthetic scenario generation

This tutorial walks through real, runnable code: `data_plane.synthetic`,
the package that supplements an already-subsetted-and-masked dataset (or
produces a standalone dataset) with specific test scenarios a QA/test
engineer needs on demand — a high-cost claim, a claim referencing a
member that doesn't exist, a member with an unusually deep claim history
— scenarios that may not occur naturally, or often enough, in a random
subset.

## This is not Phase 1, again

Tutorial 02 already covered a synthetic data generator:
`data_plane.reference_data`, which builds the entire estate from nothing
and injects its own edge cases (nulls, duplicates, orphans, malformed
values, late-arriving data, schema drift) as part of that build. It is
reasonable to ask why this phase exists separately, instead of just
asking Phase 1 to generate more edge cases.

The answer is *where each one sits in the pipeline*. `ARCHITECTURE.md`
describes the pipeline as:

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK -> GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

Phase 1 *is* the ingest source for everything left of `SUBSET` — it plays
the role of "the production systems," fully synthetic so no real PHI/PII
ever enters this repository. This phase runs *after* `MASK`: its input
(in the pipeline's intended shape) is already a smaller, already-masked
dataset, and its job is narrow — add specific, requested scenario records
on top, not rebuild an estate. A QA engineer asking "give me a claim
referencing a member that doesn't exist" doesn't want to regenerate the
whole estate and hope one shows up; they want that one scenario, on
demand, added to the dataset they already have.

## Three kinds of data, never conflated

This phase's core safety requirement is a single sentence in its own
spec: *never allow synthetic records to be mistaken for real
records.* Concretely, that means every row in this platform's output
belongs to exactly one of three categories
(`healthcare_tdm_contracts.DataProvenance`), and the category is always
explicit, never inferred:

| `DataProvenance` | What it means | Produced by |
|---|---|---|
| `MASKED_PRODUCTION_LIKE` | Derived from a real production row, transformed by the Phase 3 masking engine. | Phase 3 (`data_plane.masking`) |
| `SYNTHETIC` | Wholly fabricated, schema-conformant, referentially valid — safe as a normal positive-path fixture. | Phase 1 and this phase |
| `NEGATIVE_TEST` | Wholly fabricated and *deliberately* broken in one documented way — only ever a fixture for a rejection/validation-path test. | This phase |

(Phase 1's own output is, strictly, `SYNTHETIC` too — it is a stand-in
for what Phase 3 would otherwise be masking. In a real deployment,
`MASKED_PRODUCTION_LIKE` is what Phase 3 actually produces from real
source data; this repository's Phase 1 estate exists specifically so
Phases 2 onward have somewhere realistic to run against without ever
touching real PHI/PII — see `ARCHITECTURE.md` section 1.)

## Why provenance is tagged twice: per-row and per-batch

`data_plane.synthetic.provenance` adds a `data_provenance` column to
*every* row this phase writes, across every one of the five simulated
source systems' on-disk formats (SQLite, Parquet, NDJSON, CSV, and the
partner feed's two shapes) — plus `scenario_type` on rows belonging to a
named scenario, and `synthetic_batch_id` linking a row back to the exact
generation run that produced it.

This is deliberately **both** a row-level and a batch-level signal, for
the same reason Phase 4 reports its orphan classification both per-row
(`DanglingReference.category`) and per-manifest
(`SubsetManifest.known_orphan_counts`): a per-row column is the only
signal that survives arbitrary downstream re-shuffling of rows (a single
Parquet row group pulled out of context still says what it is), while a
per-batch/manifest rollup is what makes a human audit or a quick
sanity-check fast without reading every row. Claim rows get an additional
signal at a third granularity: every scenario-generated claim lands in
its own dedicated Parquet batch, `synthetic-scenarios`, next to Phase 1's
`claims-2024Q4`/`claims-2025Q1` batches — so a directory listing of the
claims warehouse already shows the split before a single file is opened.

### "Augment" mode tags the *base* rows too

Running this phase against an existing estate means rewriting every file
that estate lives in, to merge in the new scenario rows. If this phase
only tagged the *new* rows, a downstream reader would see
`data_provenance` present on some rows and absent on others, and could
reasonably — but wrongly — read "absent" as "not synthetic, therefore
real." `provenance.tag_base_estate_as_masked_production_like` closes that
gap: every row already present in the base estate is tagged
`MASKED_PRODUCTION_LIKE` (idempotently — a row that's already tagged is
left alone) as part of the same run, so the output's provenance coverage
is complete, not partial.

## ID convention: a second, human-legible signal

Phase 1 mints IDs shaped `SYN-<ENTITY>-<seq>` (e.g. `SYN-MBR-000007`).
This phase's `data_plane.synthetic.ids.ScenarioIdAllocator` mints IDs in
a distinct sub-range, `SYN-<ENTITY>-SCEN-<seq>` (e.g.
`SYN-MBR-SCEN-000001`) — the extra `SCEN` segment means the two ID spaces
can never collide *by construction*, not merely by convention. Negative-
test scenarios that need a reference to something that provably doesn't
exist go one step further: `SYN-<ENTITY>-SCEN-NX-<tag>-<seq>` (`NX` =
"nonexistent"), e.g. `SYN-MBR-SCEN-NX-MEMBER-000001` — a real example
from the walkthrough below.

This is a *secondary* signal only — always trust `data_provenance`
first, programmatically. The ID convention exists so a human skimming a
row in a debugger or a spreadsheet already has a strong hint before
checking the authoritative column.

## The eleven scenarios, and their provenance classification

`data_plane.synthetic.scenarios` implements one generator function per
scenario. Each is classified `SYNTHETIC` or `NEGATIVE_TEST` based on
whether it's schema-and-business valid (just rare) or deliberately
broken in a specific way a rejection path needs to be tested against:

| Scenario | Provenance | What it produces |
|---|---|---|
| `normal_claims` | `SYNTHETIC` | Ordinary, fully valid claims — realistic amounts, a real provider/coverage. |
| `high_cost_claims` | `SYNTHETIC` | Claims billed $75,000-$350,000 — valid, just statistically rare. |
| `duplicate_claims` | `NEGATIVE_TEST` | A claim row written twice, identical, same `claim_id` — simulates a source-system replay. |
| `invalid_claim_references` | `NEGATIVE_TEST` | A claim whose `member_id`/`coverage_id` reference nothing in the dataset. |
| `expired_coverage` | `NEGATIVE_TEST` | A claim serviced after its coverage's `term_date`. |
| `missing_provider` | `NEGATIVE_TEST` | A claim/encounter with `provider_id=None`, or a dangling provider reference. |
| `unusual_prescription_combinations` | `SYNTHETIC` | Two interaction-risk drugs filled same-day, plus an outlier refill pattern. |
| `missing_laboratory_values` | `SYNTHETIC` | A lab result collected but never resulted (`result_value=None`) — a common, valid "pending" state. |
| `boundary_dates` | `SYNTHETIC` | Same-day coverage, a leap-day service date, "today," and a Dec-31-to-Jan-1 year boundary. |
| `null_heavy_records` | `SYNTHETIC` | A member/claim with every individually-nullable field actually null, all at once. |
| `very_large_claim_histories` | `SYNTHETIC` | One member with an unusually large claim volume — a scale/pagination edge case. |

Every generator shares the same shape: it takes a `ScenarioContext`
(shared RNG, Faker instance, `ScenarioIdAllocator`, and a `ReferencePool`
of real Plan/Provider/Pharmacy/Diagnosis/Procedure IDs to link against —
"configurable relationships" in the phase's own words) and a `count`, and
returns a `ScenarioBatch`: the rows produced, per entity, plus the
scenario's provenance and a human description.

See `data_plane/synthetic/scenarios.py`'s module docstring for the full
reasoning behind each provenance classification — it's written as a
table with a one-line justification per scenario, not left to be
inferred.

## Two modes: augment, and standalone

```bash
cd services/data-plane

# Augment an existing (e.g. Phase 4 subsetted) estate with scenarios:
python -m data_plane.synthetic.cli \
    --base-estate-dir data/tmp/synthetic-estate-subset \
    --out-dir data/tmp/synthetic-estate-scenarios \
    --scenario high_cost_claims --scenario invalid_claim_references

# Generate a standalone scenario-only dataset (no base estate at all):
python -m data_plane.synthetic.cli \
    --out-dir data/tmp/synthetic-scenarios-standalone \
    --scenario missing_provider --scenario expired_coverage

# Every one of the eleven required scenarios in one run:
python -m data_plane.synthetic.cli --out-dir data/tmp/synthetic-scenarios-all --all-scenarios
```

In **augment** mode, `base_estate_dir` is read with
`data_plane.subsetting.estate_io.read_estate` — the exact same reader
Phase 4 uses, reused rather than reinvented, because a subsetted and/or
masked estate lives in the exact same five-source-system on-disk layout
the raw Phase 1 estate does. The output is written back with
`data_plane.subsetting.writer.write_subset_estate`, also reused directly.
In **standalone** mode, no base estate exists, so a small, self-contained
reference-table fixture set (a couple of Plans, five Providers, a
Pharmacy, five Diagnosis/Procedure codes — tagged `SYNTHETIC`, but not
tied to any of the eleven named scenarios themselves) is generated first,
and scenarios link against that instead.

## Try it yourself: real output

```bash
# 1. Generate a small estate (Tutorial 02):
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

# 2. Subset it (Tutorial 04):
python -m data_plane.subsetting.cli --estate-dir data/tmp/synthetic-estate \
    --out-dir data/tmp/synthetic-estate-subset \
    --strategy fixed_population --param count=8

# 3. Augment the subset with every required scenario:
python -m data_plane.synthetic.cli \
    --base-estate-dir data/tmp/synthetic-estate-subset \
    --out-dir data/tmp/synthetic-estate-scenarios \
    --all-scenarios --seed 42
```

Real output from exactly this command:

```
Mode: augment (base: data\tmp\synthetic-estate-subset)
Output: data\tmp\synthetic-estate-scenarios
Scenarios generated:
  normal_claims                        provenance=synthetic        rows=25
  high_cost_claims                     provenance=synthetic        rows=28
  duplicate_claims                     provenance=negative_test    rows=18
  invalid_claim_references             provenance=negative_test    rows=9
  expired_coverage                     provenance=negative_test    rows=15
  missing_provider                     provenance=negative_test    rows=18
  unusual_prescription_combinations    provenance=synthetic        rows=9
  missing_laboratory_values            provenance=synthetic        rows=6
  boundary_dates                       provenance=synthetic        rows=16
  null_heavy_records                   provenance=synthetic        rows=9
  very_large_claim_histories           provenance=synthetic        rows=629
Total row counts (entity -> count):
               address: 12
                 claim: 296
            claim_line: 460
              coverage: 33
             diagnosis: 18
             encounter: 16
            lab_result: 16
                member: 39
   member_demographics: 11
              pharmacy: 4
                  plan: 6
          prescription: 18
             procedure: 16
              provider: 10
Provenance row counts:
  masked_production_like  : 173
  synthetic               : 737
  negative_test           : 45
Estimated output storage: 139,357 bytes
Manifest: data\tmp\synthetic-estate-scenarios\synthetic_generation_manifest.json
```

`member: 39` = the base subset's 8 members plus 31 scenario-generated
members (one or more per scenario that needs its own member). `claim:
296` is dominated by `very_large_claim_histories` alone contributing 250
of them (the default) — the scale/volume edge case doing exactly what
it's for.

### Proving the distinction actually holds

Reading the output back with the same `read_estate` reader Phase 4 uses:

```python
from pathlib import Path
from data_plane.subsetting.estate_io import read_estate

estate = read_estate(Path("data/tmp/synthetic-estate-scenarios"))

masked = [m for m in estate.member if m["data_provenance"] == "masked_production_like"][0]
synthetic = [m for m in estate.member if m["data_provenance"] == "synthetic"][0]
print(masked["member_id"], masked["data_provenance"])
print(synthetic["member_id"], synthetic["data_provenance"], synthetic["scenario_type"])
```

```
SYN-MBR-000007 masked_production_like
SYN-MBR-SCEN-000001 synthetic normal_claims
```

And a real `invalid_claim_references` row — a genuinely dangling
reference, injected on purpose, self-describing at a glance even before
reading `data_provenance`:

```json
{
  "claim_id": "SYN-CLM-SCEN-0000012",
  "member_id": "SYN-MBR-SCEN-NX-MEMBER-000001",
  "coverage_id": "SYN-COV-SCEN-NX-COVERAGE-000001",
  "provider_id": "SYN-PRV-00004",
  "billed_amount": 420.91,
  "data_provenance": "negative_test",
  "scenario_type": "invalid_claim_references"
}
```

Notice `provider_id` here is a *real* provider from the base estate
(`SYN-PRV-00004`, no `SCEN` segment) — this scenario's whole point is
that the member/coverage references are broken while everything else
about the claim is ordinary, which is exactly what "configurable
relationships" (linking new records to real reference data where the
scenario doesn't call for breaking that link) means in practice.

## The manifest

`synthetic_generation_manifest.json`
(`healthcare_tdm_contracts.SyntheticGenerationManifest`) is this phase's
durable, typed record — the same "self-contained JSON artifact next to
the output" pattern Phase 3's `masking_run_summary.json` and Phase 4's
`subset_manifest.json` already established. It records: which mode ran,
which base estate (if any) and — when that base estate has its own
`subset_manifest.json` — that manifest's `manifest_id`, so lineage traces
all the way back through the Phase 4 run this augmented; the seed; the ID
convention (spelled out in the manifest itself, not just in this
document); every scenario generated with its own row counts and anchor
IDs; total row counts per entity; and the full provenance rollup.

## What this phase does and does not cover

- Covers all eleven required scenarios as real, distinct generator
  functions producing schema-valid (`SYNTHETIC`) or deliberately-broken
  (`NEGATIVE_TEST`) records, in both augment and standalone modes.
- Reuses Phase 4's `estate_io.py`/`writer.py` read/write path rather than
  reinventing it — this phase's output is a drop-in five-source-system
  estate for the exact same reason Phase 4's subset output already is.
- Does **not** yet learn scenario parameters (cost thresholds, drug
  interaction pairs, boundary dates) from real distribution statistics —
  every scenario's shape is hand-authored, matching this phase's own
  scope (implement the eleven required scenarios correctly, not a
  general-purpose statistical scenario-inference engine). See
  `docs/problems/problems_phase_05.md`.
- Does **not** yet wire into a control-plane job or a metadata-plane
  snapshot registry — same documented scope boundary Phases 3 and 4 left
  for their own outputs (`ARCHITECTURE.md` section 2.2,
  `docs/problems/problems_phase_04.md` P4-1/P4-2). `data_plane.synthetic.cli` is a
  standalone entry point today, exactly like `subsetting.cli` and
  `masking.cli`.
