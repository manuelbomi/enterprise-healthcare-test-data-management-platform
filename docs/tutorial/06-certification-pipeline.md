# Tutorial 06 — The certified test dataset pipeline

This tutorial walks through real, runnable code: `data_plane.certification`,
the package that ties every prior phase together into one pipeline and
adds the two things none of them provide on their own — an independent
VALIDATE stage and an enforced CERTIFY/PUBLISH lifecycle.

## The pipeline, end to end

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

Every stage left of `VALIDATE` is a phase you've already met:

| Stage | Package | Tutorial |
|---|---|---|
| INGEST | `data_plane.reference_data` | 02 |
| PROFILE + CLASSIFY | `data_plane.discovery` | 03 |
| SUBSET | `data_plane.subsetting` | 04 |
| MASK | `data_plane.masking` | (Phase 3 README) |
| GENERATE OPTIONAL SYNTHETIC DATA | `data_plane.synthetic` | 05 |

This phase does not reimplement any of them —
`data_plane.certification.pipeline.run_certification_pipeline` calls each
one's real engine, in order, against a real estate. What's new is
everything from `VALIDATE` onward.

## Why "masking ran cleanly" isn't the bar

**Read [`docs/CERTIFICATION_VS_MASKING.md`](../CERTIFICATION_VS_MASKING.md)
in full before continuing** — it's short, and it's the reasoning this
whole phase is built to satisfy. The one-sentence version: masking can
succeed, produce output, and pass its own validation, while a *different*
kind of problem elsewhere in the pipeline (an incomplete masking policy,
a referential-integrity defect from an earlier stage, a degenerate final
dataset) goes completely unnoticed by masking's own report, because
masking was never designed to check for those things.

## Try it yourself: a healthy run, real output

```bash
cd services/data-plane

# 1. Resolve dev keys (masking key + certification signing key):
python -m data_plane.certification.cli --generate-dev-key
export TDM_MASKING_HMAC_KEY=<printed masking key>
export TDM_CERTIFICATION_HMAC_KEY=<printed signing key>

# 2. Run the full pipeline: generate a tiny estate, subset it, mask it,
#    augment it with two synthetic scenarios, certify, and publish:
python -m data_plane.certification.cli --scale tiny --seed 42 \
    --out-dir data/tmp/certification-run \
    --strategy fixed_population --param count=10 \
    --scenario high_cost_claims --scenario invalid_claim_references \
    --publish
```

Real output from exactly this command:

```
Certification report: data\tmp\certification-run\certification_report.json
Dataset: tiny-fixed_population  Status: PUBLISHED
Masking policy: phase3-default v1
Masking engine version: 1.0.0
Gates:
  [PASS] phi_pii_policy_coverage: All 88 sensitive catalog column(s) resolve to a real masking technique.
  [PASS] masking_completion: 218 row(s) masked across 10 file(s); 22 masking validation check(s) passed.
  [PASS] referential_integrity: No engine-introduced dangling references. 3 known source orphan(s) and 0 injected negative-test orphan(s) present and accepted (strict=False).
  [PASS] schema_validation: 14 entities schema-validated cleanly.
  [PASS] data_quality_thresholds: 249 total row(s) across 14 entities; 13 member row(s).
  [PASS] row_count_reconciliation: 14 entities reconciled; no row loss detected.
  [PASS] orphan_detection: 3 known/injected orphan reference(s) detected across 3 relationship(s); no threshold configured (report-only).
  [PASS] provenance: Provenance rollup accounts for all 249 row(s).
  [PASS] manifest_generation: All 3 expected manifest artifact(s) present on disk.
  [PASS] policy_version_recorded: Masking policy 'phase3-default' version 1 recorded.
  [PASS] masking_version_recorded: Masking engine version '1.0.0' recorded.
Row count reconciliation:
               address: source=38 selected=18 final=18
                 claim: source=55 selected=17 final=23
            claim_line: source=88 selected=33 final=52
              coverage: source=38 selected=17 final=20
             diagnosis: source=30 selected=20 final=20
             encounter: source=34 selected=16 final=16
            lab_result: source=50 selected=22 final=22
                member: source=26 selected=10 final=13
   member_demographics: source=24 selected=10 final=10
              pharmacy: source=5 selected=4 final=4
                  plan: source=6 selected=6 final=6
          prescription: source=47 selected=16 final=16
             procedure: source=30 selected=19 final=19
              provider: source=10 selected=10 final=10
Published at: 2026-09-25 17:22:20.408948+00:00
```

Notice `claim` grows from `selected=17` to `final=23` — the two synthetic
scenarios (`high_cost_claims`, `invalid_claim_references`) added six new
claims on top of the masked subset. `row_count_reconciliation` treats
that as expected (final >= selected), not a defect — see
`data_plane.certification.gates.check_row_count_reconciliation`'s
docstring for why growth is fine but shrinkage never is.

## Try it yourself: a real, adversarial FAILED run

This is the demonstration that matters most for this phase's own claim.
The following Python (not the CLI, which only ever loads the real default
policy) runs the **exact same pipeline, against the same real estate**,
but with a deliberately misconfigured masking policy that routes every
sensitive column to `PASSTHROUGH` (i.e., leaves it completely unmasked):

```python
from pathlib import Path
from healthcare_tdm_contracts import (
    SubsettingStrategy, MaskingPolicy, MaskingRule,
    MaskingStrategy, MaskingTechnique, ClassificationTier,
)
from data_plane.certification.pipeline import run_certification_pipeline
from data_plane.certification.state_machine import publish, InvalidCertificationTransitionError

broken_policy = MaskingPolicy(
    name="broken-demo-policy", version=1,
    rules=[
        MaskingRule(tier=t, strategy=MaskingStrategy.PASSTHROUGH,
                    scope="broken", technique=MaskingTechnique.PASSTHROUGH)
        for t in (ClassificationTier.DIRECT_IDENTIFIER, ClassificationTier.QUASI_IDENTIFIER,
                  ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE, ClassificationTier.NON_SENSITIVE)
    ],
)

result = run_certification_pipeline(
    Path("data/tmp/certification-run-broken"),
    scale="tiny", seed=42,
    subset_strategy=SubsettingStrategy.FIXED_POPULATION,
    subset_parameters={"count": "10"},
    masking_key=b"...",
    masking_policy=broken_policy,
    signing_key=b"...",
    auto_publish=True,  # <-- explicitly asked for, and it still won't happen
)
```

Real output:

```
Status: FAILED
  [FAIL] phi_pii_policy_coverage: 88 sensitive column(s) resolve to PASSTHROUGH under
         policy 'broken-demo-policy' v1: postgres_enrollment.member.member_id
         (tier=direct_identifier), postgres_enrollment.member.first_name
         (tier=direct_identifier), postgres_enrollment.member.ssn
         (tier=direct_identifier), ... [85 more]
  [PASS] masking_completion: 218 row(s) masked across 10 file(s); 22 masking validation check(s) passed.
  [PASS] referential_integrity: No engine-introduced dangling references. ...
  [PASS] schema_validation: 14 entities schema-validated cleanly.
  [PASS] data_quality_thresholds: 218 total row(s) across 14 entities; 10 member row(s).
  [PASS] row_count_reconciliation: 14 entities reconciled; no row loss detected.
  [PASS] orphan_detection: 3 known/injected orphan reference(s) detected across 3 relationship(s); no threshold configured (report-only).
  [PASS] provenance: No synthetic scenario stage ran; provenance is uniformly masked-production-like by construction.
  [PASS] manifest_generation: All 2 expected manifest artifact(s) present on disk.
  [PASS] policy_version_recorded: Masking policy 'broken-demo-policy' version 1 recorded.
  [PASS] masking_version_recorded: Masking engine version '1.0.0' recorded.
published_at: None
Manual publish() attempt raised: Cannot publish certification report ...: status is
  'failed', not 'certified'. Only a CERTIFIED report -- every required gate passed --
  may be published. See docs/CERTIFICATION_VS_MASKING.md.
```

Read that gate list carefully: **ten of the eleven gates pass, including
`masking_completion`** — masking ran, processed 218 rows, wrote 10
files, and Phase 3's own validation (referential integrity within the
run, no collisions) reported clean. Only `phi_pii_policy_coverage`
catches the real problem, because it is the one gate that independently
re-resolves the masking policy against the catalog rather than trusting
that "masking exited successfully" means "masking did the right thing."
The pipeline correctly produces `FAILED`, `auto_publish=True` is
silently honored as "don't publish a failed report" rather than raising,
and a subsequent *manual* attempt to call `publish()` directly on the
resulting report is rejected by `state_machine.py`'s enforced transition
table — see
`services/data-plane/tests/certification/test_pipeline_against_real_estate.py`
for this exact scenario as an automated test (`test_a_real_pipeline_run_with_a_broken_policy_produces_failed_not_certified`,
`test_auto_publish_never_publishes_a_failed_pipeline_run`,
`test_manually_attempting_to_publish_a_failed_pipeline_report_is_rejected`).

## The six-state lifecycle, enforced by code

```
DRAFT -> PROCESSING -> CERTIFIED -> PUBLISHED
                     \-> FAILED         \-> REVOKED
                                CERTIFIED -> REVOKED
```

`FAILED` and `REVOKED` are terminal — there is no transition out of
either. Every transition (including `publish()`/`revoke()`, which are
convenience wrappers) is checked against
`healthcare_tdm_contracts.CERTIFICATION_STATUS_TRANSITIONS` by
`data_plane.certification.state_machine.transition()`, which raises
`InvalidCertificationTransitionError` for anything not listed. This is
not a soft convention a caller could route around — try it:

```python
>>> from healthcare_tdm_contracts import CertificationReport, CertificationStatus
>>> from data_plane.certification.state_machine import transition
>>> draft = CertificationReport(dataset_name="x")
>>> transition(draft, CertificationStatus.PUBLISHED, actor="me")
Traceback (most recent call last):
    ...
data_plane.certification.state_machine.InvalidCertificationTransitionError:
Cannot transition certification report ... from 'draft' to 'published'.
Allowed next state(s) from 'draft': ['processing'].
```

## Tamper evidence: a hand-edited report is caught

`certification_report.json` is a plain file. `data_plane.certification.signing`
computes a keyed HMAC-SHA256 signature over the report's content at
CERTIFY time (`integrity_signature`), re-signed on every subsequent
transition. Try hand-editing a real report's status field and re-loading
it:

```python
>>> import json
>>> from pathlib import Path
>>> from healthcare_tdm_contracts import CertificationReport
>>> from data_plane.certification import signing
>>>
>>> path = Path("data/tmp/certification-run/certification_report.json")
>>> payload = json.loads(path.read_text())
>>> payload["status"] = "published"  # it was actually "certified"
>>> path.write_text(json.dumps(payload))
>>>
>>> reloaded = CertificationReport.model_validate_json(path.read_text())
>>> signing.verify_report_signature(reloaded, key)
False
```

See `docs/CERTIFICATION_VS_MASKING.md`'s "Tamper evidence, honestly"
section for exactly what this mechanism does and does not protect
against — it is deliberately not oversold.

## Policy version and masking engine version

Every `CertificationReport` records **two** separate version identifiers
(`docs/adr/0011-masking-and-policy-versioning-for-certification.md`):

- `masking_policy_name` / `masking_policy_version` — which *rules* were
  configured (`data_plane.masking.policy.DEFAULT_POLICY.name`/`.version`).
- `masking_engine_version` — which *implementation* of those rules
  actually ran (`data_plane.masking.engine.MASKING_ENGINE_VERSION`).

Two certification gates (`policy_version_recorded`,
`masking_version_recorded`) fail outright if either is missing or blank
— an auditor reading a certified report months later can always answer
"what exact rules, and what exact code, masked this data?"

## What this phase does and does not cover

- Every gate is real, independently computed code — not a placeholder
  that always returns `passed=True`. See
  `services/data-plane/tests/certification/test_gates.py` for a unit
  test of each gate's pass *and* fail path.
- Does **not** wire into a control-plane orchestrated job or a
  metadata-plane snapshot registry yet — the same scope boundary Phases
  3/4/5 documented for their own outputs. See `docs/problems/problems_phase_06.md`.
- Does **not** implement distribution-shape-preservation data-quality
  checks (statistical fidelity against the source estate) — see
  `docs/problems/problems_phase_03.md` P3-4 and `docs/problems/problems_phase_06.md`.
- The tamper-evidence signature is a real, working mechanism with an
  honestly documented limit (key secrecy) — read
  `docs/CERTIFICATION_VS_MASKING.md` before treating it as a hardened
  security control.
