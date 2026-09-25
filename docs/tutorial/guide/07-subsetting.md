# Chapter 7 — Subsetting

## The concept

Production healthcare data can have millions of members, tens of
millions of claims. A lower environment almost never needs — and almost
never has the storage/compute budget for — a full copy. **Subsetting**
is the practice of selecting a smaller, representative slice of a large
dataset for use in a lower environment. The hard part is not picking a
smaller number of rows; the hard part is picking a smaller number of
rows *without breaking the relationships between them*. A subset of
"2% of members" that includes a member's claims but not that member's
coverage record, or that includes a claim line but not the claim it
belongs to, is a broken subset — tests run against it will fail for
reasons that have nothing to do with the code under test.

## How this repository actually subsets

`data_plane.subsetting` splits this into two independent concerns,
deliberately:

1. **Which rows are the anchor selection?** — `selection.py` implements
   six strategies (`SubsettingStrategy`), each deciding only *which
   Member IDs are selected*:

   | Strategy | Example parameter |
   |---|---|
   | `percentage` | `--param percentage=25` |
   | `fixed_population` | `--param count=8` |
   | `stratified` | `--param strata_field=gender --param per_stratum=3` |
   | `date_window` | `--param start_date=2025-01-01 --param end_date=2025-03-31` |
   | `business_rule` | `--param coverage_status=active --param claim_status=paid --param min_matching_claims=1` |
   | `risk_edge_case` | `--param max_members=10` |

2. **Given that anchor selection, what else must come with it?** —
   `closure.py` (Chapter 8) walks every relationship reachable from the
   selected members, identically, regardless of which of the six
   strategies produced the selection. This split is the whole mechanism
   behind guaranteeing referential closure without six separate,
   strategy-specific implementations of it.

## Try it yourself

```bash
cd services/data-plane
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
python -m data_plane.subsetting.cli --estate-dir data/tmp/synthetic-estate \
    --out-dir data/tmp/synthetic-estate-subset \
    --strategy fixed_population --param count=8
```

Real output from running exactly this command against a fresh `tiny`
estate:

```
Strategy: fixed_population -- Fixed population of 8 requested; 26 available; 8 selected
Subset written: .../data/tmp/synthetic-estate-subset
Row counts (source -> selected):
               address:      38 -> 12
                 claim:      53 -> 16
            claim_line:      92 -> 26
              coverage:      36 -> 11
             diagnosis:      30 -> 18
             encounter:      39 -> 13
            lab_result:      55 -> 13
                member:      26 -> 8
   member_demographics:      24 -> 8
              pharmacy:       5 -> 4
                  plan:       6 -> 6
          prescription:      43 -> 12
             procedure:      30 -> 16
              provider:      10 -> 10
Estimated storage: source=236,250 bytes, subset=70,640 bytes
Integrity status: passed_with_known_orphans
Manifest: .../data/tmp/synthetic-estate-subset/subset_manifest.json
```

8 selected members out of 26 pulled 16 of 53 claims, 26 of 92 claim
lines, and every other related row across all five source systems —
not a flat 8/26 (~31%) ratio applied uniformly to every table, because
different members have different numbers of claims, addresses, and
encounters. That's what "representative" actually means here: the
*relationships* determined how much of each table came along, not a
fixed percentage per table.

## Why this is genuinely hard: relationships span source systems

This wouldn't be especially hard if every table lived in one relational
database with real foreign keys. It's hard here because the estate
spans five heterogeneous source systems (Chapter 11) — PostgreSQL/
SQLite, Parquet, NDJSON, CSV, and a partner flat-file/JSON feed — with
no cross-database foreign key mechanism holding them together. Chapter
8 covers exactly how `closure.py` still guarantees referential integrity
across that boundary.

## Scale: this is not a toy-data-only mechanism

The exact same code path demonstrated above at `tiny` scale (26 members)
is what runs, unmodified, against a real `performance`-scale estate.
Phase 14's real benchmark proved this: a real `performance`-scale estate
(20,400 members) selected 408 members in 8.777 seconds with no memory
issues — see `docs/SCALE_AND_PERFORMANCE.md`.

## Where to go next

Continue to [Chapter 8 — Referential integrity](08-referential-integrity.md),
then read `docs/tutorial/04-subsetting-and-referential-closure.md` for
the full implementation-depth walkthrough (including every relationship
edge this repository's closure graph knows about).
