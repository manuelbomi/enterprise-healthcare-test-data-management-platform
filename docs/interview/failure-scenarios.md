# Failure scenarios: what this repository actually broke on purpose, and what happened

A senior engineer asked "how does this fail, and how do you recover" should
not answer in the abstract — this repository has real, passing tests that
inject each failure and a real runbook for each one. This document walks
through what was actually tested (`ROADMAP.md` Phase 11's eight
failure-injection scenarios, `docs/PLATFORM_INTEGRITY.md` section 15) plus
the two example questions the spec calls out specifically — partial
masking-job recovery and schema drift — in the depth an interview answer
needs.

## The eight failure-injection scenarios, and where each one actually lives

| # | Scenario | Test | Runbook |
|---|---|---|---|
| 1 | Masking job crashes halfway | `services/data-plane/tests/platform_integrity/test_failure_injection.py::test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output` | [`masking-job-failure-recovery.md`](../runbooks/masking-job-failure-recovery.md) |
| 2 | Source schema changes | `...::test_a_column_not_in_the_catalog_falls_back_to_safe_masking_not_raw_passthrough` | (this file, section below) |
| 3 | Storage unavailable | `...::test_storage_unavailable_fails_cleanly_without_a_leaked_stack_trace_of_raw_data` | [`masking-job-failure-recovery.md`](../runbooks/masking-job-failure-recovery.md) |
| 4 | Duplicate refresh/registration request | `services/control-plane/tests/test_failure_injection.py::test_duplicate_refresh_requests_do_not_corrupt_state`, `::test_duplicate_dataset_version_registration_is_idempotent` | [`duplicate-requests-and-revoked-datasets.md`](../runbooks/duplicate-requests-and-revoked-datasets.md) |
| 5 | Certification validation fails | `...::test_a_failed_certification_report_cannot_be_registered_as_a_dataset_version` | [`snapshot-refresh-failure.md`](../runbooks/snapshot-refresh-failure.md) |
| 6 | Secret missing | `services/data-plane/tests/platform_integrity/test_failure_injection.py::test_masking_with_no_key_anywhere_fails_fast_before_any_output_is_written` | [`masking-job-failure-recovery.md`](../runbooks/masking-job-failure-recovery.md) |
| 7 | Dataset becomes corrupted | `...::test_corrupted_masked_parquet_is_rejected_downstream_not_silently_misread` | [`masking-job-failure-recovery.md`](../runbooks/masking-job-failure-recovery.md) |
| 8 | Consumer requests revoked dataset | `services/control-plane/tests/test_failure_injection.py::test_consumer_cannot_fulfill_request_against_a_dataset_whose_only_version_is_revoked` | [`duplicate-requests-and-revoked-datasets.md`](../runbooks/duplicate-requests-and-revoked-datasets.md) |

Four of these are data-plane-owned (1, 2, 3, 6 for its data-plane half —
secret missing is also independently tested at the certification-signing
layer), four are control-plane-owned (4, 5, 6's control-plane half, 8) — see
`services/data-plane/tests/platform_integrity/test_failure_injection.py`'s
own module docstring for exactly which half lives where.
`docs/PLATFORM_INTEGRITY.md` section 15 is the authoritative index; this
document expands the two the spec specifically asks about.

## Q: How would you recover from a partially completed masking job?

**The mechanism:** `data_plane.masking.dataset_masker.mask_estate` writes a
`_MASKING_RUN_INCOMPLETE.marker` file at the *start* of every run and
removes it only on clean completion. `is_masking_run_complete(out_root)`
checks for its absence. This was a real gap found during Phase 11 — before
it existed, there was no on-disk signal that a masking run had crashed
partway through; an output directory containing a mix of fully-written
files (source systems processed before the crash) and nothing at all for
source systems not yet reached could be mistaken for a small-but-complete
dataset.

**The recovery procedure** (full detail in
[`masking-job-failure-recovery.md`](../runbooks/masking-job-failure-recovery.md)):

1. **Check the marker first, not the file contents.**
   `is_masking_run_complete(Path("path/to/masked/output"))` returning
   `False` means the run is untrustworthy regardless of how many files look
   fine — `test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output`
   proves a real, injected mid-run crash leaves the marker in place, and
   `test_a_clean_masking_run_removes_the_incomplete_marker` proves a clean
   run doesn't.
2. **Delete the entire incomplete output directory. Never attempt to
   "resume."** `mask_estate` has no resume capability — mixing one run's
   partial output with a second run's (possibly a different key or policy
   version) output would silently produce an inconsistent, unauditable
   dataset. This is the runbook's single most important instruction, and it
   exists precisely because the completion marker only proves the run *as a
   whole* finished or didn't — it does not make each individual
   per-source-system writer's output atomic. A masker that writes rows
   incrementally (e.g. `mask_clinical_data_lake`) can still leave one
   truncated file for whichever source system was mid-write when the crash
   happened, indistinguishable from a clean write except that the
   whole-run marker correctly shows incomplete. This is a real, honestly
   documented remaining gap (`problems_phase_11.md` P11-1) — the runbook's
   "delete everything, never resume" rule is the safe mitigation for it
   today, not a claim the gap is closed.
3. **Fix the root cause** — a code bug (file/fix/regression-test per
   `CONTRIBUTING.md`'s process), storage unavailability (resolve the
   infrastructure issue), or, if corruption appears with no failed run to
   explain it, escalate per `SECURITY.md` on suspicion of tampering.
4. **Re-run from scratch against a fresh output directory.** Masking is
   deterministic and idempotent for identical `(estate, catalog, key,
   policy)` inputs (Phase 3's `test_masking_is_idempotent_across_two_independent_runs`)
   — a clean re-run produces exactly the values the crashed run would have
   produced, had it succeeded.
5. **If this masking run fed a certification pipeline, re-run the whole
   pipeline**, not just the masking stage — so certification's own VALIDATE
   gates re-check the fresh output end-to-end, per
   `docs/interview/system-design.md`'s "never trust an earlier stage's own
   report" principle.

**Why retries aren't blindly automated here:** `control_plane.platform.retry.retry_with_backoff`
(Phase 11) exists and is real, but is deliberately wired into exactly one
call site — the `/api/v1/ready` database connectivity check, a read-only,
side-effect-free operation. It is **not** wired into masking/subsetting/
certification job execution, because this exact failure-injection test
discovered that a mid-run crash can leave a non-atomic, partially-written
output directory — blindly retrying against the same output path in that
state risks making corruption *worse* (a second run's writes interleaving
with the first run's partial ones), not safer, until the underlying
per-file-atomicity gap is closed. See `docs/PLATFORM_INTEGRITY.md` section 4
and `problems_phase_11.md` P11-6.

**One more thing a certification-pipeline run gets for free:** if the crash
happens *inside* `data_plane.certification.pipeline.run_certification_pipeline`
rather than a standalone CLI run, the exception propagates all the way up
with no `try/except` swallowing it around the MASK stage, so no
`certification_report.json` is ever written for that attempt — there is no
risk of a partially-masked dataset ever being certified. The runbook's
scope is specifically the standalone masking-CLI case, where an incomplete
output directory might otherwise be inspected or reused without anyone
realizing it's incomplete.

## Q: How do you handle schema drift?

Schema drift shows up at three different pipeline stages in this
repository, and each one has a real, different, tested answer — "handle
schema drift" is not one mechanism here, it's three independent defenses
because drift can be missed at any one of them.

**1. At classification time — drift can be silently invisible if nobody
updates the schema layer.** `data_plane.discovery.engine.ClassificationEngine`
combines schema-based classification (`schema_rules.py`, authoritative only
for columns someone explicitly entered) with rule-based pattern detection
(`pattern_rules.py`) as a fallback. `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`
section 7 states this limit explicitly: if the underlying estate changes (a
field renamed, a new entity added) and nobody updates `schema_rules.py`,
that drift is invisible until the pattern-based fallback layer picks up
whatever it can — which is not guaranteed to be correct (points 1-3 of that
same document: column-name conventions aren't universal, and a genuinely
novel column name might match no detector at all). The safety net is the
conservative-default rule: an unrecognized column defaults to
`SensitivityCategory.SENSITIVE` at low confidence rather than being passed
through as safe. Concretely, Phase 2's own scanner (`discovery/scanner.py`)
was built by reading the *actual* generated files, not just the schema, and
it genuinely caught real schema-drift columns the schema-only layer would
have missed (`amount_paid`, `adjustment_reason_code`, `pat_id`, `test_cd` —
`ARCHITECTURE.md`'s Phase 2 note, `ROADMAP.md`'s Phase 2 section).

**2. At masking time — a column the catalog has never seen must fail safe,
not pass through raw.** This is failure-injection scenario 2 from the table
above, and it's the most direct answer to "what happens when the source
schema changes between classification and masking." The test
(`test_a_column_not_in_the_catalog_falls_back_to_safe_masking_not_raw_passthrough`)
simulates exactly this: a brand-new column
(`newly_added_sensitive_field`) that a catalog built from an *earlier* scan
never saw appears in a row when `data_plane.masking.dataset_masker.mask_row_dict`
runs. The code has a defensive fallback for this specific case (its own
inline comment: "should not happen against a catalog produced by a
discovery run over the same estate, but defensive against drift") — the
test proves the fallback actually fires: the previously-unseen column's raw
value is never passed through untouched (`masked["newly_added_sensitive_field"]
!= raw_value`), and it isn't nulled out either (`is not None`), i.e. it gets
masked conservatively rather than either leaking or silently disappearing.
This mirrors `ARCHITECTURE.md`'s Phase 2 note and `DATA_GOVERNANCE.md` B.1's
governing principle stated once, at the top of the stack: **never default
an unknown column to safe.**

**3. At certification time — degenerate or schema-drifted output must fail
the run, not pass silently.** `data_plane.certification.gates.check_schema_validation`
is a certification gate added specifically because nothing upstream of it
checks whether the *final* output is internally schema-consistent — e.g. a
Parquet batch with heterogeneous columns within itself, which "masking
completed successfully" by Phase 3's own definition would not catch
(`docs/CERTIFICATION_VS_MASKING.md` item 3). This is the last line of
defense: even if drift slipped past classification and past masking's
per-row fallback, a certification run against the resulting dataset is
required to independently re-verify schema consistency before `CERTIFIED`
is ever reached.

**The honest limit across all three layers:** none of this is semantic
understanding of the data. `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`'s
section 2 names the biggest remaining gap directly: free-text fields (a
name or diagnosis embedded in a sentence inside a `notes` column) are not
covered by any column-name pattern or the two narrow value-regex detectors
this engine has (email shape, SSN shape) — that would require NLP/named-
entity recognition, which this repository does not attempt, and it is
explicitly untested here because the synthetic estate doesn't model it
(`problems_phase_02.md` P2-2). A senior engineer's honest answer names this
limit rather than implying pattern-based drift detection is a complete
solution.

## The release gate: a real, observed failure, not a hypothetical one

Beyond data-plane failure injection, Phase 12 proved the CI release gate
itself actually blocks a broken build, not just that the YAML says it
should. On a scratch verification branch: commit `d575396` deliberately
broke `services/data-plane/tests/masking/test_validation.py::test_referential_integrity_passes_for_consistent_mapping`
so the same real member ID mapped to two different tokens across two
source systems — exactly the cross-system linkage inconsistency
`assert_referential_integrity` exists to catch. [CI run
#36187426321](https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform/actions/runs/36187426321)
**FAILED** as required — both the unit-test job and the data-quality-tests
job failed, and, critically, the `release-gate` job also failed, printing
its own designed message: `"One or more required checks failed — release
gate BLOCKED."` Commit `dcc5008` (`git revert d575396 --no-edit`) reverted
the breakage; [CI run
#36187642266](https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform/actions/runs/36187642266)
**SUCCEEDED**, the gate re-opening immediately with no other change needed.
See `problems_phase_12.md`'s "Deliberate-failure experiment" section for
the full account, including why this one experiment was chosen to prove
both the "masking tests fail" and "referential-integrity tests fail"
release-gate requirements from `ROADMAP.md` at once, rather than four
separate broken-commit round trips.

## Dead-letter handling for isolated job failures

`control_plane.platform.dead_letter.DeadLetterStore` (Phase 11, a new
`dead_letter_event` table) is wired into the one place this codebase
already isolates one item's failure from a batch:
`LocalRefreshOrchestrator.run_due_refreshes`
([ADR-0012](../adr/0012-refresh-orchestration-abstraction.md)'s "isolate
one request's failure from the others" principle). Before this phase, a
failed scheduled refresh inside a sweep was only visible in the one
synchronous HTTP response to whoever triggered the sweep
(`RefreshSweepResult.errors`), which disappears the moment that response is
sent — nobody polling later would ever see it. `test_scheduler_sweep_wires_a_real_failure_into_the_dead_letter_store`
proves a durable, queryable record now survives past that one response.
The honest scope limit: this is one dead-letter table for one orchestrator
sweep, not a general job-queue dead-letter system — every other job path in
this repository (a standalone masking CLI run, a certification pipeline
run) still fails by raising an exception to its caller, not by landing in
this store.
