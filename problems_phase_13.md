# Problems — Phase 13 (Auditability and Compliance Evidence)

Written before implementation, per `CONTRIBUTING.md`. Updated after
implementation to record what was actually resolved vs. what remains
open (moved to `problems_master.md` if broader than this phase).

## Context this phase starts from

Phase 11 (`control_plane.platform.audit`) already built a real,
DB-backed, append-only `AuditLogRepository` wired to the Phase 0
`healthcare_tdm_contracts.AuditEvent` contract, exposed read-only at
`GET /api/v1/audit/events`, and already wired into dataset version
register/revoke/rollback, refresh, policy approve/reject, and consumer
request submit/fulfill. Phase 6 already produces a real HMAC-signed
`CertificationReport`. Phase 10 has `MaskingPolicyVersion`/
`PolicyApproval`. Phase 7 has `DatasetVersion`/refresh/rollback
mutations. Phase 4 has `SubsetManifest`. Phase 2 has the catalog.

Concrete gaps identified by inspection before writing any code:

1. `AuditEventType.ACCESS_GRANTED`/`ACCESS_REQUESTED` are defined in
   `libs/contracts` since Phase 0 but **never emitted anywhere** —
   only `ACCESS_DENIED` is wired (to RBAC rejections). There is no
   event at all for "a consumer/engineer accessed a provisioned
   dataset version," which this phase's brief explicitly requires
   ("who accessed ... it").
2. `LifecycleRepository` has no read method to list past
   `RefreshRunRecord`/`RollbackRecord` rows after the fact — `refresh()`
   and `rollback()` each return the *one* record they just created, but
   nothing queries `RefreshRunRow`/`RollbackEventRow` historically. So
   "refresh history" / a rollback-based view of "revocation history"
   were not actually retrievable via any repository method or API
   endpoint before this phase, only the terminal `DatasetVersion.status
   == REVOKED`/`ROLLED_BACK` fields were.
3. Neither `CertificationReport` (Phase 6) nor `SubsetManifest` (Phase
   4) is durably stored by `services/control-plane` — only
   `DatasetVersionRow.certification_report_id` (a bare UUID) and a few
   scalar fields (`masking_policy_name/version`, `masking_engine_version`)
   are persisted at registration time. The full reports/manifests exist
   only as data-plane-local JSON artifacts.

## Expected/known issues going in (still true after implementation)

- **P13-1 (open, by design)** — An Audit Evidence Package's
  `certification_report`/`subset_manifest` fields can only be populated
  if the caller supplies the actual Phase 6/Phase 4 artifacts in the
  generation request body; `services/control-plane` has no durable
  store for either (see gap 3 above — this phase does not add one,
  that is a bigger cross-plane storage decision out of scope here).
  When omitted, `integrity_report`/`quality_report`/`lineage` fields
  that would come from them are left empty with an explicit
  `provenance_notes` entry explaining why, never silently faked.
- **P13-2 (open, by design)** — The evidence package's
  `bundle_checksum` is a plain SHA-256 digest over the package's own
  canonical JSON, computed and stored by the same process that also
  wrote every row the package reads. This detects accidental
  corruption/truncation after export (e.g. in transit, or a copy/paste
  into a ticket), but — exactly like `data_plane.certification.signing`
  documents for `CertificationReport.integrity_signature` — it is
  **not** a cryptographic non-repudiation guarantee: anyone with
  write access to the control-plane database can edit the underlying
  rows and regenerate a self-consistent checksum for a new package.
  A production deployment would want the same keyed-HMAC (or better,
  asymmetric-signature) treatment `signing.py` already gives
  `CertificationReport`, ideally from a real secrets provider — not
  implemented for the *bundle* here. Documented, not hidden, in
  `docs/COMPLIANCE_EVIDENCE.md`.
- **P13-3 (open)** — The new endpoints this phase adds
  (`POST /api/v1/lifecycle/dataset-versions/{id}/access`,
  `POST /api/v1/evidence/dataset-versions/{id}/package`) are **not**
  RBAC-gated — any caller can record a (self-reported) access event or
  generate an evidence package, the same honestly-documented gap
  `problems_phase_11.md` P11-4 already tracks for most other
  lifecycle/governance mutations. `accessed_by`/`generated_by` remain
  caller-supplied free-text identity strings with no verification, the
  same limitation `control_plane.platform.rbac`'s own module docstring
  already documents for `revoked_by`/`performed_by`.
- **P13-4 (open)** — `EvidenceRepository`'s `audit_trail` aggregation
  only pulls events whose `subject` matches the dataset version id, or
  one of its known `EnvironmentDatasetRequest`/`ConsumerDatasetRequest`
  ids. An audit event recorded under some other ad hoc subject string
  referring to the same dataset (e.g. free text rather than an id) would
  not be found. This is a real, narrow limitation of `AuditEventRow`
  having no foreign key to a dataset version — tracked here rather than
  fixed, since introducing that FK retroactively is a schema-migration
  decision bigger than this phase's scope.
- **P13-5 (open)** — This phase does not reach into `data_plane` to make
  a masking/certification *run itself* append to the same audit log
  (still `problems_phase_11.md` P11-5's gap, unchanged and out of scope
  here — the evidence package instead re-exports whatever `data_plane`
  artifact the caller supplies).

## Resolved by this phase

- The "who accessed it" gap (issue 1 above): `AuditEventType.
  DATASET_VERSION_ACCESSED` is added and wired to a real new endpoint,
  `POST /api/v1/lifecycle/dataset-versions/{version_id}/access`, which
  checks the version exists and then appends a real audit event.
- The "refresh history"/rollback-history read gap (issue 2 above):
  `LifecycleRepository.list_refresh_runs`/`list_rollback_events` are
  added (real DB reads over `RefreshRunRow`/`RollbackEventRow`),
  exposed at `GET /api/v1/lifecycle/refresh-runs` and
  `GET /api/v1/lifecycle/rollback-events`.
- The Audit Evidence Package itself: `healthcare_tdm_contracts.evidence.
  AuditEvidencePackage`, built by a new
  `control_plane.domain.evidence.EvidenceRepository.build_evidence_package`,
  exposed at `POST /api/v1/evidence/dataset-versions/{version_id}/package`
  — a real aggregation of the dataset manifest, classification summary,
  masking policy version + approvals, provisioning/refresh/rollback/
  revocation history, and the relevant audit trail (all genuinely
  DB/artifact-backed, Phase 2/6/7/10/11 data), plus a real SHA-256
  bundle checksum, and (when supplied) the caller's own Phase 6/4
  artifacts embedded verbatim.
