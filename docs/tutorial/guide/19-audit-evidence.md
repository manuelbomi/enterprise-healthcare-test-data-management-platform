# Chapter 19 — Audit evidence

## The concept

Every chapter so far has shown a real check happening — classification,
masking, certification, RBAC denial. Audit evidence is the discipline of
making those checks *reconstructible after the fact*, for someone who
wasn't watching at the time: an auditor asking "who requested this
dataset, who approved the policy it was masked under, when was it
refreshed, who has accessed it since" needs an answer built from durable
records, not from someone's memory of what happened. `THREAT_MODEL.md`
names the failure mode this defends against directly, under
"Repudiation": a user denying they requested a dataset containing a
sensitive classification tier. The mitigation it names — "every
approval-worthy action emits an immutable audit event before the action
is allowed to proceed" — is not aspirational in this repository; it is
real, running code.

## Auditing the audit log, not just building one

This repository's own process is worth learning from here: a real,
DB-backed, append-only audit log
(`control_plane.platform.audit.AuditLogRepository`, Chapter 16) already
existed before this capability was built out further. So the first real
work this phase did was not "build an audit log" — it was **audit the
audit log**: read every route handler that touches sensitive state, and
check which of "who requested/accessed/approved a dataset," "refresh
history," and "revocation history" were genuinely covered versus only
apparently covered. That review found two concrete, narrow gaps:

1. **"Who accessed it" was never actually recorded.** An
   `ACCESS_GRANTED`/`ACCESS_REQUESTED` event type had existed in the
   audit contract since the beginning, but neither was ever emitted
   anywhere — only `ACCESS_DENIED` (an RBAC rejection) was wired.
   Nothing answered "who looked at/used this dataset version." Fixed by
   a new `POST /api/v1/lifecycle/dataset-versions/{id}/access` endpoint.
2. **Refresh/rollback history was not actually queryable after the
   fact.** `refresh()`/`rollback()` each returned the one record they
   just created, but nothing could list every `RefreshRunRow`/
   `RollbackEventRow` for a dataset later. Fixed by two new repository
   methods, `list_refresh_runs`/`list_rollback_events`, exposed at
   `GET /api/v1/lifecycle/refresh-runs` and
   `GET /api/v1/lifecycle/rollback-events`.

## The Audit Evidence Package: a real aggregation, not a new source of truth

`control_plane.domain.evidence.EvidenceRepository.build_evidence_package`
is the one genuinely new piece of business logic here. Given a dataset
version id, it aggregates, from real rows this platform already
produced across earlier chapters — never inventing anything:

1. The real Chapter 13 `DatasetVersion` and every environment/consumer
   request referencing it.
2. Refresh/rollback history and revocation fields (item 2 above).
3. The real Chapter 9/19-governed `MaskingPolicyVersion` and its full
   approval trail (see the governance model this builds on).
4. A classification rollup from the real Chapter 6 catalog.
5. Every real audit event whose subject matches this dataset version or
   its related requests, merged into one deduplicated, most-recent-first
   trail.
6. If (and only if) the caller supplies a real `CertificationReport`
   (Chapter 12) in the request, embeds it and extracts an
   integrity/quality report from its gate results — and says so
   explicitly when one wasn't supplied, rather than fabricating those
   fields.
7. A SHA-256 checksum over the whole package, recorded as its own
   `EVIDENCE_PACKAGE_GENERATED` audit event.

## Try it yourself

```bash
# 1. Register a dataset version (Chapter 13).
curl -X POST http://localhost:8000/api/v1/lifecycle/dataset-versions \
  -d '{"dataset_name": "member", "certification_report": {...}, ...}'

# 2. Record that a QA engineer accessed it.
curl -X POST http://localhost:8000/api/v1/lifecycle/dataset-versions/<version_id>/access \
  -d '{"accessed_by": "qa-engineer@example.org", "environment": "qa", "purpose": "regression run"}'

# 3. Generate the Audit Evidence Package.
curl -X POST http://localhost:8000/api/v1/evidence/dataset-versions/<version_id>/package \
  -d '{"generated_by": "auditor@example.org"}'
```

The response is one `AuditEvidencePackage` JSON document containing
every item 1-7 above, including the access event from step 2 and the
`EVIDENCE_PACKAGE_GENERATED` event the call itself just produced.
`test_evidence_repository.py::test_tampering_with_a_generated_package_is_detected`
proves the checksum mechanism actually catches a mutated field.

## What this package is not

`bundle_checksum` is a plain SHA-256 digest, not the keyed HMAC
signature Chapter 12's certification report uses — it detects accidental
corruption after export; it is not a non-repudiation guarantee against
someone with database write access. And, most importantly, every
generated package carries its own `compliance_disclaimer` field, stating
verbatim what `docs/COMPLIANCE_EVIDENCE.md` says at length: this package
is evidence in support of an organization's own compliance program — it
is not itself a HIPAA (or any other) certification, attestation, or
guarantee.

## Where to go next

Continue to
[Chapter 20 — Operating TDM as a product](20-operating-tdm-as-a-product.md),
or read `docs/tutorial/13-auditability-and-compliance-evidence.md` and
`docs/COMPLIANCE_EVIDENCE.md` in full.
