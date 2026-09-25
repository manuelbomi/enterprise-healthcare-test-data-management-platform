# Chapter 12 — Dataset certification

## The concept

Every prior chapter in this guide has shown one engine's *own* claim
that it did its job correctly — masking's own validation, subsetting's
own integrity verdict. **Certification** is the step that refuses to
simply trust those self-reports. `docs/CERTIFICATION_VS_MASKING.md`
states the gap directly: "masking ran" is not equivalent to "certified"
— a masking run can complete successfully and still have missed a
column, and nothing before this stage independently re-checks that.
Certification is an automated, evidence-producing gate between "a
pipeline produced output" and "this output is allowed to be published
and used" — not an afterthought, and not something that trusts any
earlier stage's own word for it.

## The full pipeline, and what's genuinely new here

`data_plane.certification.pipeline.run_certification_pipeline` runs the
complete sequence this guide has been building toward since Chapter 1:

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

It calls Phase 1 (ingest), Phase 2 (profile/classify), Phase 4 (subset),
Phase 3 (mask), and Phase 5 (optional synthetic) *unmodified* — this
package adds no new data-transformation logic. What's genuinely new is
the last three stages: an independent VALIDATE gate layer, a CERTIFY
stage producing a machine-readable `CertificationReport`, and a PUBLISH
stage that is a real, enforced state transition.

## The eleven gates — each an independent re-derivation, not a re-trust

| Gate | What it independently re-derives |
|---|---|
| `phi_pii_policy_coverage` | Re-resolves the masking policy against every sensitive catalog column |
| `masking_completion` | Masking's own validation, plus a "did masking actually do anything" check |
| `referential_integrity` | Subsetting's own engine-bug verdict (Chapter 8) — hard fail, no exceptions |
| `schema_validation` | Reads the final estate back from disk; checks row counts and schema consistency |
| `data_quality_thresholds` | The final dataset is non-degenerate |
| `row_count_reconciliation` | No entity may shrink between selection and final output |
| `orphan_detection` | Known/injected orphan counts against a configurable threshold |
| `provenance` | Chapter 11's provenance rollup accounts for every final row |
| `manifest_generation` | Every expected manifest artifact actually exists on disk |
| `policy_version_recorded` | The masking policy's name/version is non-blank |
| `masking_version_recorded` | The masking engine's version is non-blank |

## Try it yourself

```bash
cd services/data-plane
python -m data_plane.certification.cli --generate-dev-key
export TDM_MASKING_HMAC_KEY=<printed masking key>
export TDM_CERTIFICATION_HMAC_KEY=<printed signing key>
python -m data_plane.certification.cli --scale tiny --out-dir data/tmp/certification-run \
    --strategy fixed_population --param count=10 --scenario high_cost_claims --publish
```

Real output from running exactly this command (fresh `tiny` estate,
fresh throwaway dev keys):

```
Dataset: tiny-fixed_population  Status: PUBLISHED
Masking policy: phase3-default v1
Masking engine version: 1.0.0
Gates:
  [PASS] phi_pii_policy_coverage: All 88 sensitive catalog column(s) resolve to a real masking technique.
  [PASS] masking_completion: 201 row(s) masked across 11 file(s); 23 masking validation check(s) passed.
  [PASS] referential_integrity: No engine-introduced dangling references. 1 known source orphan(s) and 0 injected negative-test orphan(s) present and accepted (strict=False).
  [PASS] schema_validation: 14 entities schema-validated cleanly.
  [PASS] data_quality_thresholds: 226 total row(s) across 14 entities; 13 member row(s).
  [PASS] row_count_reconciliation: 14 entities reconciled; no row loss detected.
  [PASS] orphan_detection: 1 known/injected orphan reference(s) detected across 1 relationship(s); no threshold configured (report-only).
  [PASS] provenance: Provenance rollup accounts for all 226 row(s).
  [PASS] manifest_generation: All 3 expected manifest artifact(s) present on disk.
  [PASS] policy_version_recorded: Masking policy 'phase3-default' version 1 recorded.
  [PASS] masking_version_recorded: Masking engine version '1.0.0' recorded.
```

All 11 gates passed, and the run's status went all the way to
`PUBLISHED` because `--publish` was supplied. This is a real run against
real, freshly generated code in this environment, not a hand-typed
illustration — 226 total rows (the 10-member subset plus the
`high_cost_claims` synthetic scenario's added rows) reconciled across 14
entities with zero row loss.

## The lifecycle is enforced by code, not just documented

`CertificationStatus` has six states:
`DRAFT -> PROCESSING -> (CERTIFIED | FAILED)`; `CERTIFIED -> PUBLISHED |
REVOKED`; `PUBLISHED -> REVOKED`. Every transition goes through
`state_machine.transition()`, which raises
`InvalidCertificationTransitionError` for anything not in the
transition table. `tests/certification/test_pipeline_against_real_estate.py`
proves this adversarially — it injects a real policy defect into a real
pipeline run against real data and confirms the result is `FAILED`, not
`CERTIFIED`, demonstrating this isn't just a happy-path demo.

## Tamper evidence, honestly

`signing.py` computes a keyed HMAC-SHA256 signature over a persisted
`certification_report.json`'s substantive fields. This is a *detection*
mechanism, not a *prevention* mechanism — anyone with filesystem access
can still hand-edit the file; the signature only lets
`verify_report_signature` detect that an edit happened without also
recomputing a valid signature under the same key. `signing.py`'s module
docstring and `docs/CERTIFICATION_VS_MASKING.md` are explicit about this
limit.

## Where to go next

Continue to
[Chapter 13 — Snapshots and refresh cadence](13-snapshots-and-refresh-cadence.md),
or read `docs/tutorial/06-certification-pipeline.md` and
`docs/CERTIFICATION_VS_MASKING.md` for the full implementation depth.
