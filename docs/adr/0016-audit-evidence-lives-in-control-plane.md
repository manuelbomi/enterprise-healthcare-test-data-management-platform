# ADR-0016: Phase 13's Audit Evidence Package aggregation lives in `services/control-plane`

## Status

Accepted

## Context

`ROADMAP.md` Phase 13 ("Auditability and Compliance Evidence") asks for
two things: (1) an immutable-style audit-event model covering who
requested/accessed/approved a dataset, what source/subset/masking
policy/certification produced it, when/where it was provisioned, and
its refresh/revocation history; and (2) an "Audit Evidence Package"
that bundles a dataset manifest, classification summary, masking
report, integrity report, quality report, policy versions, approvals,
lineage, timestamps, and hash/checksum metadata into one coherent
export.

`ARCHITECTURE.md` section 2.4 names both the "immutable audit event
log" and the "certification evidence store" as
`services/governance-service` responsibilities. As of this phase, that
service remains exactly what
[ADR-0014](0014-masking-governance-lives-in-control-plane.md) and
[ADR-0015](0015-platform-integrity-controls-in-control-plane.md) both
already found it to be: a structural scaffold with no database, no
FastAPI app, and no `sqlalchemy` dependency. Nothing about that has
changed since Phase 11. The same question those two ADRs already
answered for their own phases needed answering again here: *where does
this code live*?

Two concrete facts made the answer the same as ADR-0014/0015's:

1. **Phase 11's audit log already lives in `services/control-plane`,**
   as `control_plane.platform.audit.AuditLogRepository`, DB-backed
   against `control_plane.db.models.AuditEventRow`, in the exact same
   schema/session as `DatasetVersionRow`, `MaskingPolicyVersionRow`,
   `EnvironmentDatasetRequestRow`, and `ConsumerDatasetRequestRow`.
   Extending its event-type coverage (adding
   `DATASET_VERSION_ACCESSED`/`EVIDENCE_PACKAGE_GENERATED` to the
   existing `AuditEventType` enum) and adding the two small read
   endpoints this phase needed (`GET /api/v1/lifecycle/refresh-runs`,
   `GET /api/v1/lifecycle/rollback-events`) are natural, same-service
   extensions of code that already exists there — not a new
   architectural decision, just more of ADR-0015's.
2. **The Audit Evidence Package aggregator must join across every one
   of those tables in a single, consistent read** (a dataset version's
   manifest, its environment/consumer requests, its refresh/rollback
   history, its masking policy version + approvals, and the audit
   events whose `subject` matches any of those ids). Doing that join
   honestly requires one `sqlalchemy.orm.Session` against one schema —
   exactly the same "a same-transaction integration requires a
   same-service integration" reasoning ADR-0014 gives for Phase 10's
   `GovernanceRepository` composing `LifecycleRepository`, restated
   here for a read-only aggregation instead of a write. If this
   aggregator lived in `services/governance-service` instead, it would
   need either a second, out-of-band read connection into
   `services/control-plane`'s own PostgreSQL database (breaking the
   "each service owns its own schema" boundary this repository has
   followed since Phase 0) or an HTTP call fanned out across five or
   six of `services/control-plane`'s own endpoints and reassembled
   client-side — infrastructure this repository does not have (see
   ADR-0014's identical rejection of an HTTP-call-shaped integration
   for the same reason: it does not exist yet, and faking it would be
   exactly the kind of "looks like a real integration without the
   infrastructure to back it" ADR-0012 already rejected once).

The one piece of this phase that is *not* simply "more audit log" is
the bundle checksum and the caller-supplied `CertificationReport`/
`SubsetManifest` embedding. Both are new, but neither one changes this
decision: the checksum is a pure function over the aggregated
`AuditEvidencePackage` (no new storage dependency), and the
caller-supplied artifacts are embedded verbatim exactly the way
`LifecycleRepository.register_dataset_version` already accepts a full
`CertificationReport` as a request body without durably storing it —
an established pattern in this same service, not a new one.

## Decision

Phase 13's evidence aggregation lives in
`services/control-plane/src/control_plane/domain/evidence/`
(`EvidenceRepository`), composing `LifecycleRepository` (Phase 7,
extended this phase with `list_refresh_runs`/`list_rollback_events`),
`GovernanceRepository` (Phase 10), and `AuditLogRepository` (Phase 11,
extended this phase with two new `AuditEventType` values) — all
sharing the one `sqlalchemy.orm.Session` `EvidenceRepository` is
constructed with — plus an independently-constructed `CatalogRepository`
(Phase 2, a separate file-backed artifact per ADR-0009, not part of
this schema/session, so a missing catalog file degrades the package
gracefully instead of failing it outright).

Its endpoint, `POST /api/v1/evidence/dataset-versions/{version_id}/package`
(`control_plane.api.v1.evidence`), mirrors the exact
resolve-repository/call-method/translate-exceptions convention every
other router in this service already uses. `services/governance-service`
is left untouched — this decision does not claim Phase 13 satisfies
`ARCHITECTURE.md` section 2.4's RBAC responsibility (the new endpoints
this phase adds remain unauthenticated/unauthorized by role, tracked
honestly in `problems_phase_13.md` P13-3, the same acknowledged gap
ADR-0015 already leaves for most Phase 7/10/11 mutations), only that
the evidence *aggregation and packaging* belongs alongside the tables
it must read in one consistent transaction.

## Consequences

- Every substantive field `AuditEvidencePackage` fills in from stored
  control-plane data is a real join against real rows in one schema —
  never an eventually-consistent read across two services' databases.
- `CertificationReport`/`SubsetManifest` are embedded verbatim only
  when the caller supplies them (`services/control-plane` still does
  not durably store either — see `problems_phase_13.md` P13-1); this
  ADR does not change that, and does not claim it should be fixed here.
- If `services/governance-service` is built out for real in a later
  phase, RBAC enforcement for the evidence-generation and
  access-recording endpoints this phase adds is the natural piece to
  move there first, mirroring the exact qualification ADR-0014 and
  ADR-0015 both already make about their own decisions — this ADR does
  not claim the current location or its RBAC gap is permanent, only
  that it is the correct integration point for *this* phase's scope.
- The bundle checksum (`AuditEvidencePackage.bundle_checksum`) is a
  plain SHA-256 digest, not a keyed HMAC like
  `data_plane.certification.signing`'s `CertificationReport.integrity_signature`
  — an honest, narrower guarantee (accidental-corruption detection, not
  non-repudiation), documented in `docs/COMPLIANCE_EVIDENCE.md` and
  `problems_phase_13.md` P13-2.
