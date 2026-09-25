# Chapter 8 — Referential integrity

## The concept

Referential integrity is the property that relationships between
records still hold: a claim line's `diagnosis_code` still points at a
real diagnosis row, a claim's `member_id` still points at a real member.
Databases enforce this within themselves via foreign key constraints.
The hard version of this problem — the one this platform exists to
solve — is keeping that property true *after* subsetting or masking,
and *across* independent systems that have no shared foreign-key
mechanism at all (Chapter 7). `ARCHITECTURE.md` section 3.1 calls this
"the hardest problem this platform solves."

## Two different mechanisms, on purpose

`data_plane.reference_data/README.md` is explicit that the estate
itself uses two different integrity mechanisms, because that's how a
real enterprise's data estate actually works:

1. **Within PostgreSQL/SQLite, referential integrity is real and
   enforced** — `Coverage.member_id -> Member.member_id` is a genuine
   SQLAlchemy `ForeignKey`. The database itself would reject a
   dangling reference.
2. **Across systems, referential integrity is "soft"** — a logical
   contract the generator upholds by construction (every entity is
   built from the same in-memory generation pass, threading IDs
   through), not a database constraint, because no cross-database
   foreign key spanning Postgres and an S3-shaped bucket exists.

Subsetting inherits exactly this split, which is why closure has to be
walked in code (`data_plane.subsetting.closure`) rather than delegated
to a database.

## How closure actually works

`closure.py` is a hand-authored graph walk: given a set of selected
Member IDs, it pulls every related row across all five source systems —
Coverage, Claim, ClaimLine, Diagnosis, Procedure, Prescription,
Pharmacy, Encounter, LabResult, Provider — and classifies any dangling
reference it finds into exactly one of three categories:

| Category | Meaning | Acceptable? |
|---|---|---|
| `source_orphan` | The Phase 1 estate already had this orphan (a deliberately injected edge case), and it happened to be reachable from the selected population | Yes — reported, not a bug |
| `engine_bug` | The referenced ID *did* exist in the source estate, but this package's own closure logic failed to include it | **No — hard fail, `IntegrityStatus.FAILED`, must not be published** |
| `negative_test_injection` | Produced only by `negative_testing.inject_negative_test_orphan`, called only when a caller explicitly opts in | Yes — this is the whole point of negative testing (see below) |

This three-way split matters because "a subset has a dangling
reference" is not automatically a defect — it might be a real,
pre-existing data-quality problem the subset is supposed to faithfully
preserve, or a deliberately injected one for a specific test. Silently
dropping *any* of the three, or conflating them, would either hide a
real engine bug or make negative testing impossible.

## Real output: what "passed_with_known_orphans" actually means

Continuing Chapter 7's real run (`fixed_population`, count=8):

```
Integrity status: passed_with_known_orphans
  OK   coverage.plan_id: 0 dangling references (fully closed)
  OK   claim_line.diagnosis_code: 0 dangling references (fully closed)
  OK   claim_line.procedure_code: 0 dangling references (fully closed)
  OK   prescription.pharmacy_id: 0 dangling references (fully closed)
  OK   lab_result.encounter_id: 0 dangling references (fully closed)
  OK   claim.provider_id: 0 dangling references (fully closed)
  OK   encounter.provider_id: 1 pre-existing source orphan(s) legitimately present in this subset (Phase 1 edge case, not a defect)
  OK   prescription.prescriber_provider_id: 0 dangling references (fully closed)
```

Seven of eight relationships are perfectly closed (0 dangling
references); one (`encounter.provider_id`) has exactly one pre-existing
`source_orphan` that happened to be pulled into this particular subset —
correctly downgrading the verdict from a clean pass to
`PASSED_WITH_KNOWN_ORPHANS`, not a silent pass and not a failure. Had
even one of those findings instead been an `engine_bug`, the whole run
would report `FAILED`.

## The guarantee this repository actually tests for

`services/data-plane/tests/subsetting/test_closure.py::test_closure_never_introduces_a_new_dangling_reference`
selects *every* member in the estate — the largest, most
orphan-exposing closure possible — and asserts **zero** `engine_bug`
findings. That is the real, adversarial test backing the claim "this
platform's own subsetting logic never breaks a relationship that was
intact in the source."

## Not every orphan is even reachable — and that's fine

An orphan whose *own* foreign key points at a nonexistent Member (like
an orphan `Address` row) can never be pulled in by a Member-anchored
forward selection, no matter how large the subset — the walk only ever
follows edges *outward* from a selected member, never discovers rows
that reference a member from the outside without also being reachable
from it. This is documented, not a gap, in
`data_plane.subsetting/README.md`'s "Reachable vs. unreachable orphans"
discussion (see `docs/tutorial/04-subsetting-and-referential-closure.md`
for the full explanation).

## Where to go next

Continue to [Chapter 9 — Masking](09-masking.md), or read
`docs/tutorial/04-subsetting-and-referential-closure.md` for the
complete relationship-graph reference and every edge this repository's
closure walk knows about.
