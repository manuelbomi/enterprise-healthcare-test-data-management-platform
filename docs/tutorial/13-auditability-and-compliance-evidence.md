# Tutorial 13 — Auditability and compliance evidence

This tutorial walks through real, runnable code:
`control_plane.platform.audit` (extended this phase) and
`control_plane.domain.evidence` (new this phase), exposed at
`/api/v1/lifecycle/dataset-versions/{id}/access`,
`/api/v1/lifecycle/refresh-runs`, `/api/v1/lifecycle/rollback-events`,
and `/api/v1/evidence/dataset-versions/{id}/package`. Read
[ADR-0016](../adr/0016-audit-evidence-lives-in-control-plane.md) first
-- it explains why this phase's aggregation lives in
`services/control-plane` rather than `services/governance-service`,
mirroring [ADR-0014](../adr/0014-masking-governance-lives-in-control-plane.md)
and [ADR-0015](../adr/0015-platform-integrity-controls-in-control-plane.md)'s
reasoning. Read `docs/COMPLIANCE_EVIDENCE.md` before treating anything
this phase produces as more than what it honestly is.

## The problem this phase solves

`ROADMAP.md` Phase 13 asks for two things: an audit-event model that
covers who requested/accessed/approved a dataset, what produced it,
when/where it was provisioned, and its refresh/revocation history; and
an "Audit Evidence Package" that bundles a dataset manifest,
classification summary, masking report, integrity report, quality
report, policy versions, approvals, lineage, timestamps, and hash/
checksum metadata into one export.

Phase 11 already built a real, DB-backed, append-only audit log
(`control_plane.platform.audit.AuditLogRepository`), wired into most of
the platform's sensitive mutations. So the first job this phase did was
not "build an audit log" -- it was **audit the audit log**: read every
route handler in `api/v1/lifecycle.py`/`api/v1/governance.py`, and check
which of this phase's exact requirements ("who accessed it", "refresh
history", "revocation history") were genuinely covered versus only
apparently covered.

## What was already real, and what this phase found missing

Reading the existing code turned up two concrete, narrow gaps (recorded
in `problems_phase_13.md` before any code was written):

1. **"Who accessed it" was never actually recorded.**
   `AuditEventType.ACCESS_GRANTED`/`ACCESS_REQUESTED` had existed in
   `healthcare_tdm_contracts.audit` since Phase 0, but neither was ever
   emitted anywhere in this codebase -- only `ACCESS_DENIED` (an RBAC
   rejection) was wired. `CONSUMER_REQUEST_SUBMITTED`/
   `CONSUMER_REQUEST_FULFILLED` record the *provisioning workflow*, not
   an engineer or consumer actually using the resulting data. Nothing
   answered "who looked at/used this dataset version."
2. **"Refresh history" and rollback-based revocation history were not
   actually queryable.** `LifecycleRepository.refresh()`/`rollback()`
   each return the one `RefreshRunRecord`/`RollbackRecord` they just
   created -- but there was no method, and no endpoint, that could list
   `RefreshRunRow`/`RollbackEventRow` rows *after the fact*. A real
   auditor asking "show me every refresh this dataset has ever had"
   could not be answered by this service at all before this phase.

Both are small, concrete, and now fixed:

```python
# services/control-plane/src/control_plane/domain/lifecycle/repository.py
def list_refresh_runs(self, *, dataset_name=None, request_id=None, limit=200) -> list[RefreshRunRecord]: ...
def list_rollback_events(self, *, dataset_name=None, request_id=None, limit=200) -> list[RollbackRecord]: ...
```

exposed at `GET /api/v1/lifecycle/refresh-runs` and
`GET /api/v1/lifecycle/rollback-events`, and:

```python
# healthcare_tdm_contracts/audit.py
DATASET_VERSION_ACCESSED = "dataset_version_accessed"
```

wired to a new, real mutation,
`POST /api/v1/lifecycle/dataset-versions/{version_id}/access`, which
checks the dataset version exists and then appends a real audit event
-- the same three-line convention (resolve repository, call it,
translate exceptions) every other route handler in this router already
follows.

## The Audit Evidence Package: a real aggregation, not a new source of truth

`control_plane.domain.evidence.EvidenceRepository.build_evidence_package`
is the one genuinely new piece of business logic this phase adds. Given
a `version_id`, it:

1. Reads the real Phase 7 `DatasetVersion` (the manifest), every real
   `EnvironmentDatasetRequest` referencing its `dataset_name` (where
   provisioned), and every real Phase 10 `ConsumerDatasetRequest` (who
   requested it).
2. Reads the real Phase 7 refresh/rollback history via the two new
   methods above, and the version's own revocation fields.
3. Looks up the real, governed Phase 10 `MaskingPolicyVersion` matching
   this dataset version's `masking_policy_name`/`masking_policy_version`,
   plus its full `PolicyApproval` trail.
4. Reads the real Phase 2 catalog (via `CatalogRepository`) and builds a
   classification rollup for this `dataset_name` -- degrading gracefully
   (an empty summary plus a note, not a failure) if no catalog artifact
   is configured.
5. Merges every real Phase 11 `AuditEvent` whose `subject` matches the
   dataset version id, or one of its environment/consumer request ids,
   into one deduplicated, most-recent-first trail -- "who
   accessed/approved it," answered from real rows, not reconstructed.
6. If (and only if) the caller supplies a real Phase 6
   `CertificationReport` and/or Phase 4 `SubsetManifest` in the request
   body, embeds them verbatim and extracts an `integrity_report`/
   `quality_report` from the certification report's own gate results.
7. Computes a SHA-256 checksum over the whole package's canonical JSON
   and records an `EVIDENCE_PACKAGE_GENERATED` audit event.

Step 6 is the one place this phase is deliberately incomplete, and says
so out loud: `services/control-plane` has never durably stored a full
`CertificationReport` or `SubsetManifest` (only a bare
`certification_report_id` and a few scalar fields are persisted at
registration time -- see `control_plane.db.models.DatasetVersionRow`).
Rather than fabricate integrity/quality evidence that does not exist in
this service, `EvidenceRepository` leaves those fields empty and adds an
explicit `provenance_notes` entry explaining why, whenever a report
wasn't supplied. See `problems_phase_13.md` P13-1.

## A worked example

```bash
# 1. Register a dataset version (Phase 7 -- unchanged from Tutorial 07).
curl -X POST http://localhost:8000/api/v1/lifecycle/dataset-versions \
  -d '{"dataset_name": "member", "certification_report": {...}, ...}'

# 2. Record that a QA engineer accessed it (new this phase).
curl -X POST http://localhost:8000/api/v1/lifecycle/dataset-versions/<version_id>/access \
  -d '{"accessed_by": "qa-engineer@example.org", "environment": "qa", "purpose": "regression run"}'

# 3. Generate the Audit Evidence Package (new this phase).
curl -X POST http://localhost:8000/api/v1/evidence/dataset-versions/<version_id>/package \
  -d '{"generated_by": "auditor@example.org"}'
```

The response is one `AuditEvidencePackage` JSON document: a dataset
manifest, provisioning/consumer request history, classification
summary, masking policy version + approvals, refresh/rollback/
revocation history, the merged audit trail (including the access event
from step 2 and the `EVIDENCE_PACKAGE_GENERATED` event this call itself
just produced), a `bundle_checksum`, and a `provenance_notes` list
explaining that `integrity_report`/`quality_report` are empty because no
`CertificationReport` was supplied. Passing the real report from step 1
in the request body would populate those fields too --
`test_evidence_repository.py::test_with_certification_report_integrity_and_quality_reports_are_populated`
demonstrates exactly that.

## The checksum, honestly

`bundle_checksum` is a plain SHA-256 digest, not the keyed HMAC
`data_plane.certification.signing` uses for
`CertificationReport.integrity_signature`. It detects accidental
corruption after export; it is not a non-repudiation guarantee against
someone with database write access. `docs/COMPLIANCE_EVIDENCE.md`
explains this distinction in full, and
`control_plane.domain.evidence.verify_bundle_checksum` is the function
`test_evidence_repository.py::test_tampering_with_a_generated_package_is_detected`
uses to prove the mechanism actually catches a mutated field.

## What this phase does not claim

Read `docs/COMPLIANCE_EVIDENCE.md` in full before using any of this in
a real compliance conversation. The short version: this package is
evidence in support of an organization's own privacy/security/
compliance program. It is not itself a HIPAA (or any other regulatory)
certification, attestation, or guarantee -- every generated package
says so, verbatim, in its own `compliance_disclaimer` field.

## Tests worth reading

- `services/control-plane/tests/test_evidence_repository.py` -- builds
  a fully-wired scenario (registration, governance approval, consumer
  fulfillment, refresh, rollback, revocation) and asserts the package
  actually reflects each real row, not just that the method returns
  without raising.
- `services/control-plane/tests/test_evidence_api.py` -- the same
  aggregation, exercised over real HTTP.
- `services/control-plane/tests/test_lifecycle_repository.py`/
  `test_lifecycle_api.py` -- the new `list_refresh_runs`/
  `list_rollback_events` read methods and the new access-recording
  endpoint.
- `libs/contracts/tests/test_evidence_contract.py` -- the
  `AuditEvidencePackage` shape round-trips, and its disclaimer never
  claims a compliance guarantee.
