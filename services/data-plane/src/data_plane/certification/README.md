# `data_plane.certification` — the Certified Test Dataset Pipeline (Phase 6)

Ties every prior phase together into one orchestrated pipeline, and adds
the work that is genuinely new to this phase: an independent VALIDATE
gate layer, a CERTIFY stage producing a machine-readable
`CertificationReport`, and a PUBLISH stage that is a real, enforced state
transition.

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

**Read [`docs/CERTIFICATION_VS_MASKING.md`](../../../../../docs/CERTIFICATION_VS_MASKING.md)
before treating "masking ran" as equivalent to "certified" — it is not,
and this package exists specifically because of that gap.**

## Module map

| Module | Responsibility |
|---|---|
| `pipeline.py` | `run_certification_pipeline` — calls Phase 1 (ingest), Phase 2 (profile/classify), Phase 4 (subset), Phase 3 (mask), and Phase 5 (optional synthetic) in sequence, then runs VALIDATE/CERTIFY/PUBLISH. |
| `gates.py` | The eleven required certification gates — each an independent re-derivation of an earlier phase's claims, not a re-trust of them. |
| `report.py` | `certify()` — decides `CERTIFIED` vs. `FAILED` from gate results; the one place that decision is made. |
| `state_machine.py` | The enforced six-state `CertificationStatus` lifecycle (`transition`/`publish`/`revoke`) — invalid transitions raise. |
| `signing.py` | HMAC-based tamper-evidence for a persisted report (`sign_report`/`verify_report_signature`). |
| `cli.py` | `python -m data_plane.certification.cli`, the end-to-end entry point. |

## Running it

```bash
# From services/data-plane, with the package installed (pip install -e .):

# 1. Resolve dev keys (masking + certification signing). NEVER commit these -- see SECURITY.md.
python -m data_plane.certification.cli --generate-dev-key
export TDM_MASKING_HMAC_KEY=<printed masking key>
export TDM_CERTIFICATION_HMAC_KEY=<printed signing key>

# 2. Run the full pipeline against a freshly generated tiny-scale estate:
python -m data_plane.certification.cli --scale tiny --out-dir data/tmp/certification-run \
    --strategy fixed_population --param count=10 --publish

# ...or against an existing estate, with optional synthetic scenarios:
python -m data_plane.certification.cli --estate-dir data/tmp/synthetic-estate \
    --out-dir data/tmp/certification-run --strategy percentage --param percentage=20 \
    --scenario high_cost_claims --scenario invalid_claim_references
```

This prints every gate's PASS/FAIL outcome, the row-count reconciliation
trail, and the final `CertificationStatus`, and writes
`certification_report.json` (`healthcare_tdm_contracts.CertificationReport`)
under `--out-dir`, alongside every intermediate stage's own real output
(`estate/`, `catalog.json`, `subset/`, `masked/`, `final/`).

## The eleven required certification gates

See `gates.py` for the full implementation and reasoning; summary:

| Gate | What it independently re-derives |
|---|---|
| `phi_pii_policy_coverage` | Re-resolves the masking policy against every sensitive catalog column; fails if any resolves to `PASSTHROUGH`. |
| `masking_completion` | Phase 3's own validation, PLUS a "did masking actually do anything" check (nonzero rows/files). |
| `referential_integrity` | Phase 4's `SubsetValidationReport` engine-bug verdict — hard fail, no exceptions. |
| `schema_validation` | Reads the final estate back from disk; checks row counts and per-physical-group schema consistency. |
| `data_quality_thresholds` | The final dataset is non-degenerate (nonzero total rows, nonzero anchor entity). |
| `row_count_reconciliation` | Phase 4's `SubsetManifest.selected_counts` vs. the final on-disk counts — no entity may shrink. |
| `orphan_detection` | Phase 4's known/injected orphan counts, against a configurable threshold. |
| `provenance` | Phase 5's `SyntheticGenerationManifest.provenance_row_counts` rollup accounts for every final row. |
| `manifest_generation` | Every expected manifest artifact file actually exists on disk. |
| `policy_version_recorded` | The masking policy's name/version is non-blank. |
| `masking_version_recorded` | The masking engine's version (`data_plane.masking.engine.MASKING_ENGINE_VERSION`) is non-blank. |

## The six-state certification lifecycle

`DRAFT -> PROCESSING -> (CERTIFIED | FAILED)`; `CERTIFIED -> PUBLISHED |
REVOKED`; `PUBLISHED -> REVOKED`. `FAILED` and `REVOKED` are terminal.
Every transition goes through `state_machine.transition()`, which
consults `healthcare_tdm_contracts.CERTIFICATION_STATUS_TRANSITIONS` and
raises `InvalidCertificationTransitionError` for anything not listed —
this is enforced by code, not merely documented. See
`tests/certification/test_state_machine.py` for the full adversarial
test suite (attempting to publish a DRAFT/PROCESSING/FAILED/REVOKED
report, attempting to skip CERTIFIED entirely, attempting to revoke a
report with no reason, ...) and
`tests/certification/test_pipeline_against_real_estate.py` for
end-to-end adversarial tests that inject a real policy defect and
confirm a real pipeline run against real data produces `FAILED`, not
`CERTIFIED`.

## Tamper evidence, honestly

A persisted `certification_report.json` can be hand-edited by anyone
with filesystem access. `signing.py` computes a keyed HMAC-SHA256
signature over the report's substantive fields at CERTIFY time (and
re-signs on every subsequent transition); `verify_report_signature`
detects any edit made without also recomputing a valid signature under
the same key. **This is a detection mechanism, not a prevention
mechanism**, and it is only as strong as the secrecy of the signing key
— see `signing.py`'s module docstring for the honest limitations
(consistent with ADR-0006's equivalent admission about the masking
key), and `docs/CERTIFICATION_VS_MASKING.md`.

## What this phase does and does not cover

- Reuses every prior phase's real engine unmodified — this package adds
  no new data-transformation logic, only orchestration, gate-checking,
  and the certification report/state-machine/signing mechanism.
- Does **not** wire into a control-plane orchestrated job or a
  metadata-plane snapshot registry yet — same scope boundary Phases 3/4/5
  documented for their own outputs (`problems_phase_03.md` P3-1,
  `problems_phase_04.md` P4-1/P4-2, `problems_phase_05.md` P5-3). See
  `problems_phase_06.md`.
- Does **not** implement a distribution-shape-preservation data-quality
  check (mean/variance/percentile comparison against the source estate)
  — `data_quality_thresholds` is a minimal non-degeneracy check, not a
  statistical fidelity guarantee. See `problems_phase_03.md` P3-4 and
  `problems_phase_06.md`.
