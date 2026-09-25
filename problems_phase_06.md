# Problems — Phase 6 (Certified Test Dataset Pipeline)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before implementation began (this initial version), updated as
work proceeded, resolved entries removed once fixed and tested. Anything
left below at the end of the phase is a genuine open issue for a later
phase.

## Risks identified before/during implementation, and how they were resolved

Written as work proceeded, per `CONTRIBUTING.md` step 2; kept here
(rather than deleted) as the record of what was anticipated versus what
actually happened, since every one of these was successfully resolved
and is now verified by a real, passing test:

- **The central risk this whole phase exists to address: a dataset
  should not become publishable just because masking ran without
  error.** Resolved architecturally, not just documented:
  `data_plane.certification.gates` never reads
  `MaskingRunReport`/`SubsetManifest`/`SyntheticGenerationManifest`
  fields and forwards their verdicts unchanged -- every gate either
  independently re-derives its answer (`check_phi_pii_policy_coverage`
  re-resolves the masking policy against the catalog itself;
  `check_schema_validation` re-reads the final estate from disk) or
  applies a documented, new policy decision on top of an earlier
  phase's raw data (`check_referential_integrity`'s
  `passed_with_known_orphans` acceptance rule;
  `check_row_count_reconciliation`'s >= semantics). Verified end to end
  by a **real pipeline run against real data** with a deliberately
  broken masking policy
  (`tests/certification/test_pipeline_against_real_estate.py::test_a_real_pipeline_run_with_a_broken_policy_produces_failed_not_certified`),
  which shows ten of eleven gates passing (masking genuinely did run,
  process rows, and pass Phase 3's own validation) while the eleventh
  (`phi_pii_policy_coverage`) alone catches the real defect and the
  pipeline correctly produces `FAILED`. See
  `docs/CERTIFICATION_VS_MASKING.md`.
- **`check_schema_validation`'s per-physical-group heterogeneous-key
  check initially flagged the Phase 1 estate's own, intentional design
  as a defect.** Discovered by actually running the pipeline against a
  real generated estate (not just hand-built fixtures): comparing key
  sets across `claim`'s two schema-drifted Parquet batches
  (`claims-2024Q4`'s `paid_amount` vs. `claims-2025Q1`'s
  `amount_paid`/`adjustment_reason_code`) and across `lab_result`'s
  EHR-vs-partner-feed sources produced false-positive failures, because
  that heterogeneity is Phase 1's documented schema-drift edge case
  (`reference_data/README.md`), not a writer bug. Resolved by checking
  key-set consistency **within** each physical group (one Parquet batch,
  one partner file) rather than across the merged logical-entity view --
  see `gates.py`'s `check_schema_validation` docstring and
  `tests/certification/test_gates.py::test_schema_validation_tolerates_intentional_schema_drift_across_claim_batches`.
- **Setting `certified_at`/`published_at`/`revoked_at` *after* signing a
  report invalidated the very signature just computed.** Discovered by
  an actual end-to-end CLI run raising `TamperedCertificationReportError`
  on its own freshly-produced, never-hand-edited report. The bug:
  `report.certify()`/`state_machine.publish()`/`state_machine.revoke()`
  each called `transition()` (which signs) and *then* set the
  denormalized timestamp field via a second `model_copy`, so the
  recorded signature covered the pre-timestamp content while the saved
  report carried the post-timestamp content. Resolved by adding
  `transition()`'s `extra_updates` parameter, applied **before** signing,
  so every field belonging to one transition is part of what gets
  signed. Covered by
  `tests/certification/test_state_machine.py::test_publish_then_revoke_round_trip_preserves_valid_signature`.
- **`check_schema_validation`'s row-count comparison broke once optional
  synthetic scenario generation legitimately grew row counts.** Passing
  `SubsetManifest.selected_counts` (the pre-synthetic-augmentation
  count) as the "expected" count for a post-synthetic final estate
  produced spurious mismatches. Resolved by having the pipeline choose
  the right baseline for the right gate:
  `check_schema_validation` compares against whichever stage last wrote
  the final estate's own claimed counts (the synthetic manifest's
  `total_row_counts` when that stage ran, otherwise the subset
  manifest's `selected_counts`), while `check_row_count_reconciliation`
  is the separate gate responsible for the growth-tolerant,
  whole-pipeline comparison (final >= selected, never <). Covered by
  `tests/certification/test_pipeline_against_real_estate.py::test_pipeline_with_optional_synthetic_scenarios_still_certifies`.
- **Signing key management needed its own story, independent of the
  masking key.** Resolved by mirroring (not reusing)
  `data_plane.masking.secrets`'s pattern exactly for a new, independent
  `TDM_CERTIFICATION_HMAC_KEY`
  (`data_plane/certification/signing.py`) -- a certification signing key
  and a masking encryption key are different secrets with different
  blast radii if leaked, so they must be independently rotatable, never
  the same value.

## Open problems

### P6-1 — Certification is not yet wired as a control-plane orchestrated job or a metadata-plane evidence/snapshot registry

- **Status:** open (deliberately deferred; same shape of gap Phases 3/4/5
  documented for their own outputs)
- **Description:** `healthcare_tdm_contracts.JobType.CERTIFICATION`
  already exists (Phase 0 scaffolding), but nothing submits a
  `JobRequest` to this package or consumes a `JobResult` from it yet --
  `data_plane.certification.cli` is a standalone CLI entry point,
  exactly like every other phase's data-plane CLI today. Likewise,
  `ARCHITECTURE.md`'s `Certifier -> Evidence` edge (security/governance
  plane's certification evidence store) and `Certifier -> AuditLog` edge
  do not exist -- a certification run writes a self-contained,
  HMAC-signed `certification_report.json` next to its output instead of
  to a governed evidence store.
- **Repro / detail:** N/A -- scope boundary, not a bug.
- **Affected files:** `services/data-plane/src/data_plane/certification/cli.py`,
  `libs/contracts/src/healthcare_tdm_contracts/jobs.py`
- **Owner for resolution:** a future job-orchestration phase for the
  control-plane wiring (**correction:** this used to say "Phase 14 (job
  orchestration)" — Phase 14 actually happened and its scope was
  scale/performance benchmark tooling, not job-orchestration wiring;
  that remains unscheduled by name, see `problems_phase_14.md`);
  `services/governance-service` (not currently scheduled by name) for a
  real certification evidence store.

### P6-2 — The tamper-evidence signature is a detection mechanism, not a prevention mechanism, and has no independent audit-trail cross-check

- **Status:** open (documented limitation, not a defect; consistent with
  ADR-0006's identical admission about the masking key)
- **Description:** `data_plane.certification.signing`'s HMAC signature
  catches a report hand-edited without also recomputing a matching
  signature under the same key. It cannot catch a forgery by anyone who
  has both filesystem write access to the report AND the signing key --
  there is no independent, append-only audit log
  (`healthcare_tdm_contracts.AuditEvent`) a forged file could be
  cross-referenced against, because no such log is wired up yet (same
  gap `problems_phase_03.md` P3-2 documents for the masking token
  vault).
- **Repro / detail:** N/A -- see `signing.py`'s module docstring and
  `docs/CERTIFICATION_VS_MASKING.md`'s "Tamper evidence, honestly"
  section for the full, honest explanation.
- **Affected files:** `services/data-plane/src/data_plane/certification/signing.py`
- **Owner for resolution:** A later phase that builds a real, governed
  evidence store and audit log inside `services/governance-service` (not
  currently scheduled by name in `ROADMAP.md`; tracked here so it isn't
  forgotten, same as P3-2).

### P6-3 — `data_quality_thresholds` is a minimal non-degeneracy check, not a distribution-shape-preservation guarantee

- **Status:** open (documented limitation, not a defect; this phase does
  not close `problems_phase_03.md` P3-4, and does not claim to)
- **Description:** `gates.check_data_quality_thresholds` verifies the
  final dataset isn't empty/degenerate (nonzero total rows, nonzero
  anchor-entity rows). It does not compare the masked dataset's
  statistical distribution (mean, variance, percentile shape of numeric
  fields like `billed_amount`) against the source estate's --
  `problems_phase_03.md` P3-4 already documents that
  `data_plane.masking.synthesizers`'s numeric replacement preserves
  per-value plausibility, not dataset-wide distribution shape, and nothing
  in this phase changes that.
- **Repro / detail:** Mask a `tiny`-scale estate and compare the
  distribution of masked `billed_amount` to the original; they will not
  match closely beyond "same rough order of magnitude" -- unchanged from
  Phase 3.
- **Affected files:** `services/data-plane/src/data_plane/certification/gates.py`,
  `services/data-plane/src/data_plane/masking/synthesizers.py`
- **Owner for resolution:** Not currently scheduled by name; a future
  data-quality-focused phase once the metadata plane holds real
  aggregate statistics to compare against (same owner note as P5-1).

### P6-4 — Gate policy thresholds (`strict_orphans`, `max_allowed_orphans`) are pipeline-caller parameters, not a per-target-environment governed policy

- **Status:** open (documented limitation, not a defect)
- **Description:** `run_certification_pipeline(strict_orphans=...,
  max_allowed_orphans=...)` lets a caller tune two of the certification
  gates' acceptance thresholds, but there is no control-plane-managed
  policy that says, for example, "the `qa` target environment accepts
  known orphans, but `uat` requires zero." A caller must know and pass
  the right values for the target environment itself today.
- **Repro / detail:** N/A -- no per-environment policy registry exists
  yet (same shape of gap `problems_phase_03.md` P3-3 documents for the
  masking policy itself not being control-plane-managed/versioned in a
  database).
- **Affected files:** `services/data-plane/src/data_plane/certification/gates.py`,
  `services/data-plane/src/data_plane/certification/pipeline.py`
- **Owner for resolution:** Phase 10 (centralized enterprise masking
  standard / multi-business-unit governance), same owner as P3-3.

### P6-5 — A certification run always re-executes SUBSET and MASK from scratch; no incremental/cached re-certification path

- **Status:** open (documented limitation, not a defect)
- **Description:** `run_certification_pipeline` re-runs subsetting and
  masking every time it is invoked, even if the caller only wants to
  re-certify an already-produced masked dataset (e.g. after fixing a
  policy defect and wanting to prove the fix without regenerating
  everything from the raw estate again). There is no "certify this
  already-masked directory" shortcut today, and no dataset
  lifecycle/refresh-cadence integration.
- **Repro / detail:** N/A -- architectural limitation, consistent with
  this phase's own scope (implement the pipeline correctly end to end,
  not a caching/incremental-refresh system).
- **Affected files:** `services/data-plane/src/data_plane/certification/pipeline.py`
- **Owner for resolution:** `ROADMAP.md` Phase 7 (dataset lifecycle and
  refresh management).

### P6-6 — `masking_completion` and `phi_pii_policy_coverage` are complementary, narrower-than-they-sound gates, not redundant ones

- **Status:** open (documented limitation, not a defect -- noted so a
  future reader doesn't mistake one for making the other redundant)
- **Description:** `check_masking_completion`'s "did masking do
  anything" heuristic (`rows_processed > 0`, `files_written > 0`) would
  be satisfied by a run that only ever touched non-sensitive/passthrough
  columns -- it is not, by itself, evidence that anything *sensitive*
  was actually masked. That specific claim is
  `check_phi_pii_policy_coverage`'s job alone. The two gates are
  deliberately layered (one confirms "the engine ran and processed
  real data," the other confirms "the policy the engine used actually
  covers every sensitive column"), not two independent checks of the
  same claim -- a reader auditing gate coverage should not assume either
  one alone is sufficient.
- **Repro / detail:** N/A -- design clarification, not a bug.
- **Affected files:** `services/data-plane/src/data_plane/certification/gates.py`
- **Owner for resolution:** N/A; documented for clarity.
