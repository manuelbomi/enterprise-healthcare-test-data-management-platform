# `data_plane.subsetting` — referentially intact data subsetting (Phase 4)

Selects a smaller, representative population from the Phase 1 synthetic
estate while guaranteeing referential closure across all five simulated
source systems: whatever relationships a selected row participates in are
either fully present in the subset, or provably, legitimately absent (a
pre-existing Phase 1 source orphan, or an intentional negative-test
injection) — never silently broken by the selection logic itself.

**Read [`docs/tutorial/04-subsetting-and-referential-closure.md`](../../../../../docs/tutorial/04-subsetting-and-referential-closure.md)
for the full walkthrough with real output before using this package.**

## Module map

| Module | Responsibility |
|---|---|
| `estate_io.py` | Reads the real, on-disk Phase 1 estate into plain row dicts, per dataset, across all five source systems. |
| `selection.py` | The six anchor-selection strategies (`SubsettingStrategy`); each decides only *which Member IDs are selected*. |
| `closure.py` | The referential-closure graph walk: given selected Member IDs, pulls every related row across all five source systems and classifies any dangling reference found. |
| `negative_testing.py` | The explicit, opt-in mechanism for intentionally injecting a dangling reference, for negative testing only. |
| `validation.py` | Turns `closure`'s (and, optionally, `negative_testing`'s) findings into a three-way integrity verdict (`IntegrityStatus`). |
| `writer.py` | Writes the selected rows back to disk, mirroring the source estate's five-source-system layout. |
| `manifest.py` | Assembles the `healthcare_tdm_contracts.SubsetManifest` a subsetting run produces. |
| `engine.py` | `run_subsetting`, the end-to-end orchestrator. |
| `cli.py` | `python -m data_plane.subsetting.cli`, the command-line entry point. |

## Running it

```bash
# From services/data-plane, with the package installed (pip install -e .):

# 1. Generate a synthetic estate (Phase 1 CLI) if you don't have one yet:
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

# 2. Select a subset, e.g. a fixed population of 8 members:
python -m data_plane.subsetting.cli --estate-dir data/tmp/synthetic-estate \
    --out-dir data/tmp/synthetic-estate-subset \
    --strategy fixed_population --param count=8
```

This prints a source-vs-selected row count table, every relationship edge
traversed, estimated storage, and the integrity status/findings, and
writes a subset estate mirroring the source estate's layout, plus
`subset_manifest.json` (`healthcare_tdm_contracts.SubsetManifest`) with
the same information in durable, typed, machine-readable form.

## The six strategies

Every strategy takes its parameters via one or more `--param key=value`
flags. Real parameter examples (see
`data_plane.subsetting.selection` for full parameter lists):

| Strategy | Example |
|---|---|
| `percentage` | `--param percentage=25` |
| `fixed_population` | `--param count=8` |
| `stratified` | `--param strata_field=gender --param per_stratum=3` |
| `date_window` | `--param start_date=2025-01-01 --param end_date=2025-03-31` |
| `business_rule` | `--param coverage_status=active --param claim_status=paid --param min_matching_claims=1` |
| `risk_edge_case` | `--param max_members=10` (optional; omit for the full risk pool) |

Every strategy only decides the anchor Member population; `closure.py`'s
graph walk is applied identically afterward regardless of which strategy
produced it — see the tutorial for why that split is the whole mechanism
behind guaranteeing referential closure without six separate
implementations of it.

## Orphans: pre-existing vs. engine-introduced vs. intentional

This is the core of the phase's "prevent dangling relationships unless
intentionally injected for negative testing" requirement, and it is
implemented as three distinct `DanglingReference.category` values
(`closure.py`):

1. **`"source_orphan"`** — the Phase 1 estate already had this orphan
   (see `reference_data/edge_cases.py`), and it happened to be reachable
   from the selected population (e.g. a selected member's claim
   referencing a provider that was never created). Reported, not a bug.
2. **`"engine_bug"`** — the referenced id *did* exist somewhere in the
   source estate, but this package's own closure logic failed to include
   it in the subset. This should never happen; if it does,
   `IntegrityStatus.FAILED` is returned and the subset must not be
   published. Covered by
   `tests/subsetting/test_closure.py::test_closure_never_introduces_a_new_dangling_reference`,
   which selects every member in the estate (the largest, most
   orphan-exposing closure possible) and asserts zero `engine_bug`
   findings.
3. **`"negative_test_injection"`** — produced only by
   `negative_testing.inject_negative_test_orphan`, called only when a
   caller explicitly opts in (`--negative-test` / `negative_test=True`).
   Never produced by `closure.py` itself.

`validation.validate_subset`'s verdict rule: any `engine_bug` finding
fails the whole run; any `source_orphan` or `negative_test_injection`
finding (with no `engine_bug`) downgrades a clean pass to
`PASSED_WITH_KNOWN_ORPHANS` — still a valid, publishable subset, with the
orphan reported by relationship and count, never silently dropped.

Not every one of Phase 1's orphan categories is even *reachable* this
way — see the tutorial's "Reachable vs. unreachable orphans" section for
the full explanation of why (short version: an orphan whose own foreign
key points at a nonexistent Member, like an orphan `Address` row, can
never be pulled in by a Member-anchored forward selection, no matter how
large the subset).

## What this phase does and does not cover

- Covers every relationship the Phase 1 spec's own example names
  (Member -> Coverage -> Claim -> ClaimLine -> Diagnosis/Procedure;
  Claim -> Provider; Member -> Prescription -> Pharmacy; Member ->
  Encounter -> LabResult), plus the two additional real relationships the
  estate itself has (Coverage -> Plan, Encounter/Prescription ->
  Provider).
- Population size/percentage is fully configurable; nothing hardcodes
  "10,000 members." The same code path demonstrated here at `tiny` scale
  (a few dozen members) is what would run unmodified against a real
  `performance`-scale estate to select a real 10,000-member subset — see
  `docs/problems/problems_phase_04.md` P4-3 for the tracked follow-up on actually
  benchmarking that, now done in Phase 14: a real `performance`-scale
  estate (20,400 members) selected 408 members in 8.777s with no memory
  issues — see `docs/SCALE_AND_PERFORMANCE.md`.
- Does **not** discover relationships automatically from the data the way
  `discovery`'s pattern layer discovers columns — `closure.py`'s graph is
  hand-authored against the known Phase 1 entity relationships. A future
  source system with a new relationship needs a new edge added by hand.
- Does **not** yet write to a metadata-plane snapshot registry or emit an
  audit event (neither exists yet — same scope boundary Phase 3's
  masking module documents; see `ARCHITECTURE.md` section 2.2). A
  subsetting run today produces a self-contained `subset_manifest.json`
  next to its output, the same pattern Phase 3 established with
  `masking_run_summary.json`.
