# ADR-0011: Track masking policy version and masking engine version as two distinct identifiers

## Status

Accepted

## Context

Phase 6's certification pipeline (`ROADMAP.md`) is required to record, on
every `CertificationReport`, "which policy version" and "which masking
version" produced the dataset being certified — an auditor reviewing a
certified snapshot months later needs to be able to answer "what exact
rules and what exact code masked this data?" without re-deriving it from
source history.

Two of these already existed before Phase 6:

- `healthcare_tdm_contracts.MaskingPolicy.version` (`libs/contracts/.../masking.py`)
  was already a required, versioned field, and Phase 3's
  `data_plane.masking.policy.DEFAULT_POLICY` already sets a real value
  (`POLICY_NAME = "phase3-default"`, `POLICY_VERSION = 1`). This answers
  "which *rules* were configured?"

One did not exist:

- Nothing recorded which version of the masking **engine's code**
  (`data_plane.masking.engine.MaskingEngine`) actually executed those
  rules. A policy version left unchanged does not guarantee identical
  masked output if the engine's technique implementations change (for
  example, a bug fix to `_date_shift`'s offset calculation, or a change to
  how `FORMAT_PRESERVING_SYNTHETIC` derives its digest) — the policy is a
  *specification*, the engine is an *implementation* of it, and they can
  version independently.

## Decision

Two separate version identifiers are recorded on every masking run and
carried into a certification report:

1. **Policy version** — `MaskingPolicy.name` + `MaskingPolicy.version`
   (unchanged Phase 0/3 contract; no new field needed).
2. **Masking engine version** — a new module-level constant,
   `data_plane.masking.engine.MASKING_ENGINE_VERSION` (a plain semver
   string, `"1.0.0"` as of this ADR), bumped whenever a change to
   `engine.py` could change masked output for the same policy/key/input.
   `MaskingRunReport` (`data_plane.masking.dataset_masker`) now carries
   this value (`masking_engine_version` field) so it is recorded
   alongside every run's other summary data, and the masking CLI's
   `masking_run_summary.json` includes both identifiers (`policy_name`,
   `policy_version`, `masking_engine_version`).

Neither identifier is a database-backed, control-plane-approved version
registry (that remains `docs/problems/problems_phase_03.md` P3-3's tracked gap) — both
are still plain constants in code, consistent with how `DEFAULT_POLICY`
itself is documented as an honest stand-in. This ADR only fixes *that a
version identifier exists and is recorded*, not *how policy versions are
approved/stored long-term*.

## Consequences

- `services/data-plane/src/data_plane/certification/pipeline.py` (Phase
  6) records both identifiers on every `CertificationReport`, and two of
  its certification gates (`check_policy_version_recorded`,
  `check_masking_version_recorded`) fail a certification run outright if
  either is missing/blank — making "the dataset's masking provenance is
  fully identified" an enforced certification precondition, not a
  best-effort label.
- A future engine change that could alter masked output for unchanged
  policy/key/input must bump `MASKING_ENGINE_VERSION` — this is a
  process/code-review expectation, not something enforced automatically
  (no test can prove a change "would" alter output for every possible
  input); flagged here so a future contributor knows to do it.
- This remains a lighter-weight stand-in for a real, database-backed
  policy/version registry (`docs/problems/problems_phase_03.md` P3-3, still open) —
  the identifiers are trustworthy for reproducing *this repository's*
  masking runs, not yet a governed approval record a compliance team
  could audit independently of the source tree.
