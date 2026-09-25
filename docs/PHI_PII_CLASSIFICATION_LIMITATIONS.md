# What PHI/PII classification can and cannot prove

This document is required reading before trusting, extending, or citing
the discovery/classification engine built in Phase 2
(`services/data-plane/src/data_plane/discovery/`) as evidence of
anything. It exists because `DATA_GOVERNANCE.md` and `SECURITY.md`
require this repository to be honest about what its own tooling actually
demonstrates, and because overclaiming compliance is worse than not
claiming it — a false sense of safety is a real risk in a system whose
entire purpose is keeping real PHI/PII out of lower environments.

**The short version: this engine is a triage tool. It is not a HIPAA
compliance guarantee, and nothing it produces should be presented to an
auditor, security reviewer, or compliance officer as proof that a dataset
contains no PHI/PII.** `DATA_GOVERNANCE.md` B.1 itself says as much:
classification "always has a confidence score and a human-confirmable
status" and "nothing is treated as safe to leave unmasked purely on an
automated classifier's say-so" — this document explains *why* that rule
exists, concretely, rather than just stating it.

## What this engine actually does

Three layers, combined by `data_plane.discovery.engine.ClassificationEngine`:

1. **Schema-based** (`schema_rules.py`) — a human explicitly classified
   every field of the 14 known Phase 1 entities, once. This is as
   trustworthy as the human who wrote it and as current as the last time
   someone updated it when the schema changed.
2. **Rule-based** (`pattern_rules.py`) — regular expressions matched
   against column *names* (and, for two detectors, a handful of sample
   *values*: email shape, SSN shape).
3. **Manual override** (`overrides.py`) — a human, explicitly, per column.

None of these is, or claims to be, semantic understanding of the data.

## What it can prove

- **That a column whose name matches a known pattern was flagged.** If a
  column is literally named `ssn` or `email`, this engine will
  (correctly, with high confidence) flag it.
- **That every field of the 14 documented reference-data entities has an
  explicit, human-reviewed classification with a written rationale** —
  not a guess, for those 14 entities' literal fields. See
  `schema_rules.py`.
- **That an unrecognized column is never silently treated as safe.** The
  conservative-default fallback (`engine.NO_MATCH_CONFIDENCE`,
  `SensitivityCategory.SENSITIVE`) guarantees an unknown column is flagged
  for review, not passed through.
- **That every classification carries a confidence score and a reason**,
  so a human reviewer can audit *why* the engine decided what it decided
  — this is what makes low-confidence output actionable rather than an
  opaque label.
- **That a demonstrated, working override mechanism exists** for a human
  to correct the engine in either direction (see
  `manual_overrides.yaml`'s two worked examples), with a mandatory
  `confirmed_by` identity and reason — i.e., an audit trail for "who
  decided this."

## What it cannot prove — and why

### 1. No semantic/contextual understanding

A regex matching a column name has no idea what the column actually
*means*. Concretely, in this engine:

- `pattern:npi` cannot tell whether a given NPI column belongs to a
  provider (business identifier, often public) or, in some other source
  system, a person in a different role. It gets this right for the real
  Phase 1 estate only because the schema layer (which does know the
  owning entity) takes precedence for every column that's a literal field
  of a known entity. A novel source system with no schema entry gets the
  pattern layer's weaker guess. See `problems_phase_02.md` P2-1.
- The engine has no idea what a `specialty` value like "Behavioral
  Health" *means* until a human tells it (`manual_overrides.yaml`'s first
  worked example) — it cannot infer sensitivity from cell *values* in
  general, only from the two narrow cases (email shape, SSN shape) it was
  explicitly built to sniff.

### 2. Free text is the biggest gap, and it isn't covered by tests here

None of the 14 Phase 1 entities include a free-text clinical note field.
Real EHR extracts routinely do (chief complaint, progress notes,
discharge summaries). A name, MRN, or diagnosis embedded in a sentence
inside a "notes" column will not be caught by any column-name pattern
(the *column* might be named innocuously, e.g. `comments`) and is very
unlikely to be reliably caught by a simple value-regex either — that
requires NLP/named-entity recognition, which this engine does not
attempt. This is the single largest reason this is not a de-identification
guarantee, and it is explicitly **untested** here because the underlying
synthetic estate doesn't yet model it (`problems_phase_02.md` P2-2).

### 3. Column-name conventions are not universal

`pattern_rules.py`'s detectors were tuned against this repository's own
naming conventions (and the specific schema-drift/abbreviation cases the
real Phase 1 estate introduces: `pat_id`, `test_cd`, `amount_paid`). A
column named `p_identifier`, `ssn_num`, or `bday` in a different source
system might not match any detector at all — the conservative "no match"
default (`SENSITIVE`, low confidence) catches this *safely* (it doesn't
silently pass the column through), but "safely defaulted to a low-
confidence guess pending human review" is not the same claim as
"correctly classified."

### 4. Context-dependent identifiability is not modeled

Whether a piece of data is identifying depends on context outside any
single column: population size, other data an adversary might combine it
with, time. This engine classifies one column at a time
(`(source_system, dataset, column)`); it has no k-anonymity/l-diversity
analysis, no cross-column combination risk scoring, and no notion of
"this ZIP+birth-year combination narrows a population of 3,000 down to 2
people." `DATA_GOVERNANCE.md` B.1's quasi-identifier tier exists
precisely because *combinations* re-identify, but this engine only labels
individual columns as quasi-identifying — actually assessing combination
risk (Expert Determination-style statistical disclosure analysis) is a
distinct, harder problem this phase does not attempt.

### 5. Values are (mostly) not inspected

Only two detectors (`pattern:ssn`, `pattern:email`) look at sample values
at all, and only as a secondary signal. The engine does not scan the full
column, does not validate that a column's actual contents match its
declared classification, and cannot detect e.g. a "notes" field that
happens to contain a stray SSN in one row out of ten thousand.

### 6. The six-label taxonomy overlaps by design

`SensitivityCategory` (`DIRECT_IDENTIFIER`, `QUASI_IDENTIFIER`, `PHI`,
`PII`, `SENSITIVE`, `NON_SENSITIVE`) is not a mathematically disjoint
partition — PHI/PII are legal/industry umbrella terms and
direct/quasi-identifier are de-identification-science terms, so a single
column can honestly be described by more than one label at once (a name
is both a direct identifier and PII). This engine picks one *primary*
label per column via a fixed precedence order
(`SensitivityCategory.precedence()`, most-to-least severe). That
precedence choice is a modeling decision, documented in
`libs/contracts/src/healthcare_tdm_contracts/classification.py`, not an
objective fact about the data — a different, equally defensible system
could reasonably label the same column differently.

### 7. Coverage is exactly what was built, nothing more

Schema-based classification is authoritative *only* for the columns
someone explicitly entered into `schema_rules.py`. If the underlying
Phase 1 entities change (a field renamed, a new entity added) and nobody
updates `schema_rules.py`, that drift is silently invisible until the
rule-based fallback layer picks up whatever it can (which, per points 1–3
above, is not guaranteed to be correct). `tests/discovery/
test_schema_rules.py` guards against schema/domain drift *within this
repository's own test suite*, which is a testing safeguard, not a runtime
guarantee for a production deployment.

## What this means in practice

- Treat every classification with `confidence < 0.7` (the majority-
  confirmed-below-threshold below `ColumnClassification.needs_review`) as
  **provisional**, not authoritative — that is the entire point of the
  `needs_review` flag and the catalog's `GET /api/v1/catalog?needs_review=true`
  filter.
- Treat every classification, even a high-confidence one, as a **starting
  point for human review**, not a final answer — especially before it is
  used to justify *not* masking something.
- If this platform (or a derivative of it) is ever pointed at a real
  source system with real data, a real HIPAA Safe Harbor or Expert
  Determination review by a qualified person is required regardless of
  what this engine reports. This repository's entire purpose is to keep
  real PHI/PII out of the systems it touches in the first place
  (`DATA_GOVERNANCE.md` Part A) — this classification engine is built and
  tested exclusively against synthetic data, and running it against real
  patient data would itself be a `DATA_GOVERNANCE.md` violation.
