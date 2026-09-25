# Why "masking ran" does not mean "certified"

This document is required reading before treating a successful masking
run (`data_plane.masking.cli` exiting `0`, or
`masking_run_summary.json`'s `"validation_passed": true`) as sufficient
evidence that a dataset is safe to publish to a lower environment. It is
not — and this file explains, concretely, why `data_plane.certification`
(Phase 6) exists as an independent pipeline stage rather than simply
gating publication on Phase 3's own report. This matches the honest tone
`DATA_GOVERNANCE.md` and `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`
already set for this repository: overclaiming safety is worse than not
claiming it.

**The short version: masking is one stage in a nine-stage pipeline.
"Masking completed without error" is a necessary condition for
publication, never a sufficient one.** `ARCHITECTURE.md`'s own pipeline
diagram already says this:

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

`VALIDATE` and `CERTIFY` are stages *after* `MASK`, not descriptions of
what `MASK` itself does. A dataset that never reaches them was never
certified, no matter how cleanly masking ran.

## Concretely, five ways "masking ran cleanly" can still be unsafe to publish

1. **Masking could have run against an incomplete or wrong
   classification.** `data_plane.masking` (Phase 3) masks whatever the
   Phase 2 catalog told it to mask — no more, no less (see
   `services/data-plane/src/data_plane/masking/README.md`, "Security
   tradeoffs" item 6). If discovery under-classified a column (see
   `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for the documented ways
   that happens — free text, a novel column name, schema drift a
   detector doesn't recognize), masking will pass that column through
   untouched and report success, because from its own perspective
   nothing went wrong. `data_plane.certification.gates.check_phi_pii_policy_coverage`
   exists specifically to catch this class of problem: it independently
   re-resolves the masking policy against every catalog column, rather
   than trusting that "masking exited 0" means "everything sensitive was
   masked."

2. **A referential-integrity check could have failed at a different
   pipeline stage than masking itself checks.** Phase 3's own validation
   (`data_plane.masking.validation`) checks referential integrity
   *within the masked run* (the same real value maps to the same masked
   value everywhere). It does not, and was never scoped to, check
   whether Phase 4's subsetting stage introduced a dangling reference in
   the first place — that is a different failure mode, checked by
   `data_plane.subsetting.validation` and re-verified independently by
   `data_plane.certification.gates.check_referential_integrity`. A
   masking run reports success even if the row it just masked
   *shouldn't have been there* (or is missing a row it should reference)
   — masking has no way to know that; it only transforms values.

3. **A data-quality threshold could have been missed entirely.** Nothing
   in the masking stage checks whether the *output* dataset is
   degenerate — zero rows, a missing anchor entity, a schema-drifted
   Parquet batch with heterogeneous columns within itself. Masking a
   dataset down to zero usable rows is still "masking completed
   successfully" by Phase 3's own definition.
   `data_plane.certification.gates.check_data_quality_thresholds` and
   `check_schema_validation` are new checks this phase adds precisely
   because nothing upstream of them makes this claim.

4. **PHI/PII policy coverage could be incomplete for newly-discovered
   columns.** A real deployment's source schema changes over time. A
   newly added column that discovery correctly flags as sensitive still
   needs the *masking policy* updated to route it to a real technique —
   `data_plane.masking.policy.DEFAULT_POLICY`'s tier-wide fallback rules
   happen to make this hard to get wrong in this repository's default
   policy (every tier except `NON_SENSITIVE` resolves to a real
   technique by construction), but that is a property of *this specific
   policy's design*, not a guarantee the masking engine itself enforces
   for any policy someone might configure. `check_phi_pii_policy_coverage`
   makes this an explicit, independently-checked certification gate
   rather than an accident of the default policy's conservatism — see
   `services/data-plane/tests/certification/test_gates.py` and
   `tests/certification/test_pipeline_against_real_estate.py`'s
   adversarial tests, which construct a deliberately broken policy and
   confirm a **real pipeline run** against **real data** produces
   `FAILED`, not `CERTIFIED`.

5. **Row counts could have silently changed between SUBSET and the final
   published output**, in a way no single phase's own report would
   catch (each phase only reports on its own input/output, not the whole
   pipeline's history). `check_row_count_reconciliation` reuses Phase
   4's `SubsetManifest.selected_counts` as its baseline specifically so
   this comparison spans the whole pipeline, not just one stage.

## The certification gates, and the new policy decisions behind them

Every one of the eleven required gates
(`healthcare_tdm_contracts.CertificationGateType`,
`data_plane.certification.gates`) is either a genuinely new check (no
prior phase computes it at all — schema validation, data-quality
thresholds, manifest-artifact-existence, policy/engine version
recording) or an *independent re-derivation* of an earlier phase's own
claim, never a re-trust of it. Two of these gates required a real,
documented policy decision this phase had to make explicitly, because
neither is a mechanical pass-through of an earlier phase's verdict:

- **Is `IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS` acceptable for
  certification?** Phase 4 already distinguishes a real engine bug
  (`"engine_bug"`, always a defect) from a pre-existing source orphan or
  an intentional negative-test injection (`"source_orphan"`/
  `"negative_test_injection"`, expected and documented). This phase's
  decision: `check_referential_integrity` treats `engine_bug` findings as
  an always-hard failure (no exceptions, no `strict` override), and
  treats known/injected orphans as **acceptable by default** — they are
  documented, expected, non-defect conditions, and refusing to certify
  any dataset that legitimately carries forward a Phase 1 edge case
  would make certification impossible for realistic data. A caller that
  needs a stricter bar (e.g. a target environment with a zero-orphan
  requirement) can set `strict=True`, which rejects any known/injected
  orphan too. `check_orphan_detection` is a second, independent gate on
  top of this — it *reports* the same orphan counts and can additionally
  enforce a numeric ceiling (`max_allowed_orphans`) distinct from the
  hard engine-bug gate.

- **How much data-quality checking is "enough" for this phase's scope?**
  This phase deliberately does **not** implement distribution-shape
  preservation (mean/variance/percentile comparison of masked numeric
  fields against the source estate) — `problems_phase_03.md` P3-4
  already documents that `data_plane.masking.synthesizers`'s numeric
  replacement preserves per-value plausibility, not dataset-wide
  distribution shape, and that closing this gap is real future work, not
  something achievable as a side effect of this phase. `check_data_quality_thresholds`
  is intentionally a minimal non-degeneracy check (nonzero rows, nonzero
  anchor entity), not a statistical-fidelity guarantee — see
  `problems_phase_06.md` for this tracked as an honest, explicit gap
  rather than a silently narrower implementation than the name implies.

## The tamper-evidence mechanism, and its real limit

A `CertificationReport` is persisted as `certification_report.json`.
Anyone with filesystem access can hand-edit that file — change
`"status": "failed"` to `"status": "certified"` directly, with no code
involved at all. `data_plane.certification.signing` computes a keyed
HMAC-SHA256 signature over the report's substantive fields at CERTIFY
time and re-signs on every subsequent transition;
`verify_report_signature`/`raise_if_tampered` catch any edit made
without also recomputing a matching signature under the same key —
`state_machine.transition` calls this check before accepting a
previously-signed report as trustworthy, so a hand-edited file cannot be
walked forward to `PUBLISHED` through this codebase's own APIs.

**This is honestly a detection mechanism, not a prevention mechanism,**
and it has the same real limit ADR-0006 already admits for the masking
HMAC key: anyone who has both filesystem write access to the report file
*and* the signing key can forge a new, internally-consistent signature
for a hand-edited report, and this mechanism cannot tell the difference.
A production deployment would keep the signing key in the security/
governance plane's secrets provider (not implemented yet —
`problems_phase_03.md` P3-2 tracks the identical gap for the masking
vault) and would very likely also emit signed `AuditEvent`s to an
append-only log for every transition, so a forged file could still be
caught by cross-referencing an independent audit trail the file itself
cannot rewrite. Neither of those exists in this repository yet; this
mechanism is a real, working demonstration of *how* tamper-evidence
works, deliberately not oversold as a hardened production control. See
`services/data-plane/src/data_plane/certification/signing.py`'s module
docstring and `problems_phase_06.md` for this limitation tracked
explicitly.

## What "certified" still does not mean

Even a `CERTIFIED` report from this pipeline is not a HIPAA compliance
guarantee, for the same underlying reason
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` gives for the discovery
engine it ultimately depends on: certification re-derives and
cross-checks what earlier phases did, but it does not independently
re-discover PHI/PII from the data's actual content. A dataset can pass
every one of the eleven gates here and still contain a sensitive value
in a column no detector — schema-based, pattern-based, or this phase's
own policy-coverage gate — has ever been told to look for. This
document's honest claim is narrower and load-bearing anyway: **this
pipeline proves that every check this repository knows how to run
actually ran and actually passed against the real, final output — not
merely that an earlier stage claimed success.**
