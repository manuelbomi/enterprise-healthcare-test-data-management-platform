# What the Audit Evidence Package is -- and is not

This document is required reading before treating a Phase 13
`AuditEvidencePackage` (`healthcare_tdm_contracts.evidence`, generated
by `control_plane.domain.evidence.EvidenceRepository`, exposed at
`POST /api/v1/evidence/dataset-versions/{version_id}/package`) as proof
of regulatory compliance. It is not, and this file explains, concretely,
why -- matching the honest tone `docs/CERTIFICATION_VS_MASKING.md` and
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` already set for this
repository: overclaiming safety (or compliance) is worse than not
claiming it.

## The one-sentence version

**This package is evidence in support of an organization's own privacy/
security/compliance program (e.g. a HIPAA compliance program). It is
NOT itself a certification, attestation, or guarantee of HIPAA or any
other regulatory compliance.** That determination is made by an
organization's own qualified compliance/legal personnel, informed by
evidence such as this package -- not by software. This exact sentence
is `healthcare_tdm_contracts.evidence.COMPLIANCE_DISCLAIMER`, and every
generated package carries it verbatim in its own
`compliance_disclaimer` field, so the claim travels with the evidence
itself, not just this document.

## What is genuinely real in this package

Every one of these fields is a re-export of an already-real artifact
this platform produced in an earlier phase -- not fabricated for this
package, not simulated:

- **Dataset manifest** (`dataset_manifest`) -- the real, registered
  Phase 7 `DatasetVersion` row: `storage_uri`, `size_bytes`,
  `row_counts`, `created_at`/`created_by`, current lifecycle `status`.
- **Provisioning** (`environment_requests`) -- every real Phase 7
  `EnvironmentDatasetRequest` currently or previously pointed at this
  dataset -- "where" it was provisioned.
- **Who requested it** (`consumer_requests`) -- every real Phase 10
  `ConsumerDatasetRequest` against this `dataset_name`, with
  `requested_by` and `requested_at`.
- **Classification summary** (`classification_summary`) -- a rollup of
  the real Phase 2 PHI/PII catalog entries for this `dataset_name`
  (column count, counts by `SensitivityCategory`, how many still need
  data-steward review).
- **Masking report** (`masking_policy_version`,
  `masking_policy_approvals`) -- the real, governed Phase 10
  `MaskingPolicyVersion` this dataset version's masking run used, and
  its complete approval-workflow history (every DRAFT ->
  PENDING_APPROVAL -> APPROVED/REJECTED transition, who performed it,
  when).
- **Refresh / rollback / revocation history** (`refresh_history`,
  `rollback_history`, `revocation`) -- every real Phase 7
  `RefreshRunRecord`/`RollbackRecord` ever executed against this
  dataset, and its current revocation state if any.
- **Audit trail** (`audit_trail`) -- every real Phase 11
  `AuditEvent` this dataset version (or a request that references it)
  has produced: registration, refreshes, rollbacks, policy
  approvals/rejections, access-denials, and the Phase 13
  `DATASET_VERSION_ACCESSED`/`EVIDENCE_PACKAGE_GENERATED` events.
- **Bundle checksum** (`bundle_checksum`) -- a real, keyed HMAC-SHA256
  digest over the package's own canonical JSON, computed at generation
  time (see "The checksum is a keyed integrity check, not a
  non-repudiation signature" below).

## What is only as real as what the caller supplies

`services/control-plane` does **not** durably store either a full
Phase 6 `CertificationReport` or a full Phase 4 `SubsetManifest` --
only a bare `certification_report_id` and a few scalar fields
(`masking_policy_name`/`masking_policy_version`,
`masking_engine_version`) are persisted at dataset-version
registration time (see `control_plane.db.models.DatasetVersionRow`).
The full reports/manifests exist only as `data_plane`-local JSON
artifacts.

So: `certification_report` and `subset_manifest` on the package are
populated **only if the caller supplies the real artifact** in the
package-generation request body, and are embedded verbatim -- never
re-derived, never re-verified by `services/control-plane` (which does
not depend on `data_plane` at all -- see ADR-0003, plane separation).
When they are supplied, `integrity_report`/`quality_report` are
extracted from the supplied report's own gate results
(`REFERENTIAL_INTEGRITY`/`ORPHAN_DETECTION`/`ROW_COUNT_RECONCILIATION`
for integrity; `DATA_QUALITY_THRESHOLDS`/`SCHEMA_VALIDATION`/
`PHI_PII_POLICY_COVERAGE`/`MASKING_COMPLETION` for quality). When they
are not supplied, those fields are left genuinely empty (`{}`), and
`provenance_notes` says exactly why -- this package never fabricates a
gate result it does not actually have.

## The checksum is a keyed integrity check, not a non-repudiation signature

**Phase 18A update** (`docs/problems/problems_final_review.md` P1-7, resolved):
`bundle_checksum` is now a **keyed HMAC-SHA256** digest over the
package's own canonical JSON (every field except itself), computed by
`control_plane.platform.evidence_signing.compute_bundle_checksum` and
verifiable with `verify_bundle_checksum` -- the same guarantee
`data_plane.certification.signing` gives
`CertificationReport.integrity_signature`. Before Phase 18A, this was a
plain, *unkeyed* `hashlib.sha256` digest: forging a self-consistent
checksum required only database write access, no key at all, a real
inconsistency with the certification signature's stronger guarantee.
That inconsistency is now closed.

**The residual limitation neither mechanism solves** (read
`docs/TAMPER_EVIDENCE_LIMITATIONS.md` for the single, canonical
statement of this, rather than this section restating it): both
mechanisms are *detection*, not *prevention*, and both are only as
strong as the secrecy of their signing key -- anyone with **both**
database/file write access **and** the key can still forge a new,
internally-consistent signature/checksum. Closing that fully would need
a real external KMS/HSM integration with key isolation this repository
does not implement (see `SECURITY.md`). See `docs/problems/problems_phase_13.md`
P13-2 for the longer-standing, still-open non-repudiation gap
(asymmetric signatures) this keying does not attempt to solve either.

## What this package does not do

- It does not verify identity. `generated_by` (who generated the
  package) and `accessed_by` (who recorded accessing a dataset version,
  via `POST /api/v1/lifecycle/dataset-versions/{id}/access`) are
  caller-supplied free-text strings, exactly like every other actor
  field in this service (`revoked_by`, `performed_by`, ...) -- there is
  still no identity provider anywhere in this repository. See
  `control_plane.platform.rbac`'s module docstring for the same honest
  caveat stated for RBAC's `actor_role`.
- It does not enforce RBAC. Any caller may generate an evidence package
  or record a dataset access -- neither endpoint is gated by
  `control_plane.platform.rbac.authorize()`. See `docs/problems/problems_phase_13.md`
  P13-3.
- It does not independently re-run any certification gate, re-check any
  referential integrity constraint, or re-verify any signature on a
  supplied `CertificationReport`. It packages evidence that other real
  pipeline stages already produced; it does not re-produce that
  evidence itself.
- It does not know about, or certify against, any specific regulation's
  specific control catalog (HIPAA's Security Rule safeguards, SOC 2
  criteria, etc.). It is generic evidence -- a data steward or auditor
  maps it to whatever control framework their organization uses.

## How an organization would actually use this

A privacy/security/compliance program typically needs to answer
questions like "who had access to this test dataset, when, and under
what masking policy" or "show me every dataset version that was ever
revoked and why." This package is designed to answer exactly those
questions with real, checksum-verified evidence, in one export, per
dataset version -- the raw material a compliance review, an internal
audit, or an external auditor's evidence request would actually ask
for. Using it correctly means treating it as *an input* to that human
judgment call, never as the judgment call itself.
