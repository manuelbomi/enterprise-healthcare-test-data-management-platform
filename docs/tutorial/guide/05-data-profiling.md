# Chapter 5 — Data profiling

## The concept

Before you can decide what a column *means* (Chapter 6) or how to
protect it (Chapter 9), you have to know what's actually in it.
**Data profiling** is the step of looking at a real dataset — its
columns, their types, a sample of their actual values, null rates,
cardinality — before making any decision about it. Skipping profiling
and classifying purely from a schema definition or a column name is
how real-world "surprises" happen: a column named `notes` that turns
out to contain free-text mental health details, or a column that a
schema calls `VARCHAR(50)` but that, in practice, only ever holds one of
six code values.

`ARCHITECTURE.md`'s pipeline names this as its own explicit stage:
`INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK -> ...` — profiling
comes immediately after ingesting the data and immediately *before*
classification, on purpose: classification needs profiling's output as
an input.

## Where this repository actually does it

This repository does not have a module literally named "profiling" —
the profiling step is folded into `data_plane.discovery.scanner`, the
part of Phase 2's discovery engine that reads the real, on-disk estate
before anything is classified. Rather than describe an unbuilt
"profiler" module, it's worth being precise about what `scanner.py`
actually does, because it *is* real, working profiling, just not under
that name:

- It reads all five real source systems the estate is spread across
  (SQLite, Parquet, NDJSON, CSV, and both shapes of the partner lab
  feed) — see `scanner.py`'s module docstring.
- For every column it finds, it captures up to five real, non-null
  sample values (`_SAMPLE_SIZE = 5` in `scanner.py`), producing a
  `ColumnToClassify` per column:

```python
# services/data-plane/src/data_plane/discovery/engine.py
class ColumnToClassify:
    """One column the engine is asked to classify."""
    source_system: str
    dataset: str
    entity: str | None
    column: str
    sample_values: list[str] = field(default_factory=list)
```

This is the profiling contract: `source_system`/`dataset`/`entity`/
`column` are the *shape* facts (where this column lives), and
`sample_values` is the *content* fact — what's actually in it. Chapter
6's classification engine consumes exactly this object; nothing about a
column's classification is decided without first having real sample
values in hand.

## Why sampling values (not just reading a schema) matters here

`data_plane.discovery/README.md`'s own example is the clearest
demonstration: the claims Parquet warehouse's current-quarter batch
renames `paid_amount` to `amount_paid` and adds a new
`adjustment_reason_code` column; the partner lab feed's legacy v1 file
uses abbreviated names (`pat_id`, `test_cd`, `test_nm`, `result`,
`collected_dt`). None of these on-disk column names are literal fields
of the Phase 1 domain model — a classifier that only ever consulted a
fixed schema definition would never see them at all. Profiling reads
what's *actually on disk*, which is what lets discovery's pattern layer
(Chapter 6) catch this schema drift instead of silently missing it.
`services/data-plane/tests/discovery/test_scanner_against_real_estate.py`
proves every one of these drifted/abbreviated columns is actually found.

## Try it yourself

Profiling isn't exposed as its own separate CLI command in this
repository — it runs as the first internal step of
`python -m data_plane.discovery.cli` (Chapter 6's command). You can see
its result indirectly in the catalog it produces: every `CatalogEntry`'s
underlying classification was made *from* real sampled values, not from
a column name alone. Generate an estate and run discovery to see this
end to end:

```bash
cd services/data-plane
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \
    --out data/tmp/synthetic-estate/catalog.json
```

`data/tmp/synthetic-estate/catalog.json` is the real, on-disk result —
open it and look at any entry's `sample_values`-derived classification
confidence to see the profiling step's influence directly.

## Where to go next

Continue to
[Chapter 6 — Sensitive-data classification](06-sensitive-data-classification.md),
which is the step that consumes this chapter's output, then
`docs/tutorial/03-phi-pii-classification.md` for the full
implementation-depth walkthrough.
