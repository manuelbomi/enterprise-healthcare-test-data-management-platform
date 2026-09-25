# Runbook: masking job crash / corrupted output recovery

> **Status:** REAL procedure (Phase 11), backed by real, passing tests
> against real code -- not aspirational. See the "Backing tests" line
> under each step for exactly what proves the described behavior.

## Symptom

A masking run (`python -m data_plane.masking.cli`, or the MASK stage of
`data_plane.certification.pipeline.run_certification_pipeline`) either:

(a) crashed partway through (an unhandled exception, e.g. a malformed
value the masking engine could not handle, an out-of-memory condition,
a killed process), or

(b) appears to have finished, but a downstream stage (certification's
VALIDATE gates, or a manual inspection) finds a Parquet/NDJSON/CSV file
under the masked output directory that fails to parse.

## Impact

- The masked output directory (`out_root` passed to
  `data_plane.masking.dataset_masker.mask_estate`) may contain a mix of
  fully-written files (from source systems processed before the crash)
  and no file at all for source systems not yet reached -- it must
  **never** be treated as a complete, safe-to-publish masked dataset.
- If this masking run was part of a certification pipeline run
  (`run_certification_pipeline`), the pipeline itself will already have
  failed loudly (the exception propagates all the way up -- there is no
  `try/except` in `pipeline.py` around the MASK stage) and no
  `certification_report.json` will have been written for this attempt,
  so there is no risk of a partially-masked dataset being certified.
  The risk this runbook addresses is a **standalone** masking run (the
  CLI run directly, not through the full pipeline) whose output
  directory might be inspected or reused without realizing it's
  incomplete.

## Diagnosis

1. **Check for the completion marker** (Phase 11's real, concrete
   signal — this is the actual mechanism, not a suggestion):

   ```python
   from pathlib import Path
   from data_plane.masking.dataset_masker import is_masking_run_complete

   is_masking_run_complete(Path("path/to/masked/output"))  # False -> untrustworthy
   ```

   Equivalently, check for the marker file directly:
   `ls path/to/masked/output/_MASKING_RUN_INCOMPLETE.marker` — if it
   exists, the run did not finish.

   **Backing test**:
   `services/data-plane/tests/platform_integrity/test_failure_injection.py::test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output`
   (proves a real, injected mid-run crash leaves the marker in place)
   and `::test_a_clean_masking_run_removes_the_incomplete_marker` (proves
   a normal run does not).

2. **If the marker is absent** (the run claims to be complete) but a
   specific file still fails to parse, this is genuine file-level
   corruption, not a crash — check the process's exit code/logs for the
   run that produced it (was it interrupted at the OS level after
   `mask_estate` returned but before the file was fully flushed to
   disk? A disk-full condition partway through a later, unrelated
   write?).

   **Backing test**:
   `...::test_corrupted_masked_parquet_is_rejected_downstream_not_silently_misread`
   (proves `pandas.read_parquet` and
   `data_plane.subsetting.estate_io.read_estate` both raise a clear
   exception against real, truncated Parquet bytes — corruption is
   caught, not silently misread as valid, smaller data).

3. **Check whether storage itself was the problem** (out of space, a
   misconfigured/unavailable mount) rather than a code bug — a
   `mask_estate` call whose `out_root` path is fundamentally
   unwritable fails immediately with a real `OSError`, before any
   output is written at all.

   **Backing test**: `...::test_storage_unavailable_fails_cleanly_without_a_leaked_stack_trace_of_raw_data`.

## Resolution

1. **Delete the entire incomplete output directory.** Do not attempt to
   "resume" a partial masking run by re-running only the remaining
   source systems — `mask_estate` has no resume capability, and mixing
   one run's partial output with a second, possibly different run's
   (different key, different policy version) output would silently
   produce an inconsistent, unauditable dataset.
2. Fix the underlying cause:
   - A code bug (an unhandled value shape) → file/update the relevant
     problem entry, fix, add a regression test (the same
     `CONTRIBUTING.md` process every phase follows), then re-run.
   - Storage unavailable → resolve the infrastructure issue (free disk
     space, fix the mount/permissions), then re-run.
   - Corruption discovered after the fact with no failed run to
     explain it → treat as a possible infrastructure/hardware issue;
     escalate per `SECURITY.md` if there is any reason to suspect
     tampering rather than an honest hardware/transient failure.
3. Re-run the masking job from scratch against a fresh output
   directory. Masking is deterministic and idempotent for the same
   (estate, catalog, key, policy) inputs (Phase 3: 
   `test_masking_is_idempotent_across_two_independent_runs`) — a clean
   re-run produces the same masked values as the run that crashed
   would have, had it succeeded.
4. If this masking run was feeding a certification pipeline, re-run the
   full pipeline (not just the masking stage in isolation) so
   certification's own VALIDATE gates re-check the fresh output
   end-to-end.

## Prevention / follow-up

- **Known, honestly documented remaining gap** (`problems_phase_11.md`
  P11-1): the completion marker proves the *run as a whole* finished
  or didn't, but does not make each individual per-source-system
  masker's writes atomic — a masker that writes rows incrementally
  (`mask_clinical_data_lake`) can still leave one truncated file for
  the specific source system that was mid-write when a crash happened,
  indistinguishable from a clean write except that the marker for the
  *whole run* will correctly show incomplete. This runbook's Step 1
  ("delete the entire incomplete output directory, never resume")
  is the safe mitigation for that gap today.
- If this failure recurs for the same root cause, track it in
  `problems_master.md` against `services/data-plane/src/data_plane/masking/`
  rather than treating each occurrence as a one-off retry.
