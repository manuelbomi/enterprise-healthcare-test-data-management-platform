# Chapter 6 — Sensitive-data classification

## The concept

Classification is the decision, made once and recorded durably for
every column of every dataset, of *what kind* of sensitive data (if
any) that column holds, and therefore *how* it must be handled
downstream. Get this step wrong — under-classify a column as safe when
it isn't — and every later stage of the pipeline (subsetting, masking,
certification) inherits the mistake, because they all trust this step's
answer rather than re-deriving it from scratch. `data_plane.masking`'s
own README says this outright: "this engine masks what the catalog told
it to mask — no more, no less." Classification correctness is the floor
everything else stands on.

## How this repository actually decides, precedence by precedence

`data_plane.discovery.engine.ClassificationEngine.classify_column` is
the one function that makes this decision, and it consults four layers
in a fixed, documented order — the first layer that has an answer wins:

```python
# services/data-plane/src/data_plane/discovery/engine.py (classify_column, abbreviated)
override = self.overrides.get((source_system, dataset, column))
if override is not None:
    category, confidence = override.category, 1.0          # 1. manual override
else:
    schema_rule = schema_rules.lookup(entity, column)
    if schema_rule is not None:
        category, confidence = schema_rule.category, 1.0    # 2. schema-based rule
    else:
        matches = pattern_rules.match_all(column, sample_values)
        if matches:
            category, confidence = best_match(matches)       # 3. pattern-based rule
        else:
            category, confidence = SensitivityCategory.SENSITIVE, NO_MATCH_CONFIDENCE  # 4. conservative default
```

1. **Manual override** (`overrides.py` + `manual_overrides.yaml`) —
   steward-authored corrections, highest precedence, confidence 1.0,
   always signed with a `confirmed_by` identity.
2. **Schema-based rule** (`schema_rules.py`) — authoritative,
   human-authored classification for every field of all 14 Phase 1
   entities, keyed by `(entity, column)` (not just column name — see
   Chapter 3's `Diagnosis.diagnosis_code` vs. `ClaimLine.diagnosis_code`
   example for why that distinction matters). Confidence 1.0.
3. **Pattern-based rule** (`pattern_rules.py`) — column-name (and, for a
   couple of detectors, sample-value) regex heuristics, consulted only
   when the schema layer doesn't recognize the column at all — exactly
   the schema-drifted/abbreviated columns Chapter 5 described
   (`amount_paid`, `adjustment_reason_code`, `pat_id`, `test_cd`, ...).
4. **Conservative default** — if nothing above matches, the column is
   classified `SENSITIVE`, never `NON_SENSITIVE`. This is
   `DATA_GOVERNANCE.md` B.1's rule made literal in code: "nothing is
   treated as 'safe to leave unmasked' purely on an automated
   classifier's say-so below a configured confidence threshold."

## Try it yourself

```bash
cd services/data-plane
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \
    --out data/tmp/synthetic-estate/catalog.json
```

Real output from running exactly this command against a fresh `tiny`
estate:

```
Scanned 141 columns across 5 source systems.
Catalog written: .../data/tmp/synthetic-estate/catalog.json
By category:
   direct_identifier: 20
       non_sensitive: 53
                 phi: 18
                 pii: 7
    quasi_identifier: 35
           sensitive: 8
Flagged for steward review (confidence < 0.7, unconfirmed): 4
```

The "Flagged for steward review" line is the confidence threshold in
action: any column whose classification confidence came in below 0.7
(only possible via the pattern layer or the conservative default — the
override and schema layers are always confidence 1.0) and that no
steward has yet confirmed is surfaced explicitly, rather than silently
trusted. `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` documents exactly
what this engine can and cannot prove — read it before treating any of
this as a guarantee rather than a triage tool.

## Where to go next

Read `docs/tutorial/03-phi-pii-classification.md` for the full
per-column implementation walkthrough (including real classification
output for specific columns), then continue to
[Chapter 7 — Subsetting](07-subsetting.md).
