# Tutorial 01 — Walking through a request, plane by plane

This tutorial traces a single hypothetical request end to end through the
architecture, so the plane boundaries in `ARCHITECTURE.md` feel concrete
rather than abstract. Nothing described here is implemented yet as of
Phase 0 — this is a walkthrough of the *design*, written so later phases
have a clear behavioral target and so a junior engineer can see how the
pieces are meant to fit before any of them exist.

## Scenario

A QA engineer needs a fresh test dataset: "500 synthetic-shaped patients
with their claims and encounters, masked, refreshed weekly, for the
`qa-claims` environment."

## Step by step

**1. UI → Control plane.** The engineer fills out a request form in the
React console. The frontend calls the control plane's REST API
(`POST /api/v1/snapshot-requests`) with a typed payload: target dataset,
sizing rule, target environment, desired refresh cadence. The UI never
talks to anything else — see ADR-0008.

**2. Control plane: AuthZ.** Before anything else happens, the control
plane asks the security/governance plane "is this user allowed to request
a snapshot for `qa-claims` at this classification tier?" If no, the request
is rejected and an audit event is still emitted (a denied request is itself
governance-relevant).

**3. Control plane: policy resolution.** The control plane's policy engine
resolves which masking policy version and which subsetting rule apply to
the requested source dataset, based on the metadata plane's current
classification records for that dataset.

**4. Control plane: capacity check.** Before submitting any job, the
control plane checks current storage/compute footprint for the `qa-claims`
environment against its quota (footprint management, Phase 15). If the
request would exceed quota, it's rejected with a clear reason rather than
silently queued forever.

**5. Control plane → Data plane: job submission.** The control plane
submits a job (or a small DAG of jobs: subset → mask → certify) to the data
plane, using the typed `JobRequest` contract from `libs/contracts`. This
is a submission, not a function call — the control plane does not do the
data work itself and does not block waiting for it; it tracks status.

**6. Data plane: subsetting.** The subsetting engine pulls a referentially
consistent slice: 500 patients plus every claim/encounter that references
one of those patients — not a naive `LIMIT 500` on each table
independently, which would produce orphaned claims pointing at patients
that didn't make the cut.

**7. Data plane: masking.** The masking engine applies the resolved policy:
direct identifiers become deterministic tokens (ADR-0006), quasi-identifiers
are generalized or masked per policy, sensitive clinical attributes are
handled per policy (masked or synthetically replaced), non-sensitive fields
pass through.

**8. Data plane: certification.** An automated check re-verifies the output
independently of what the masking job "claims" it did: no raw direct
identifiers detectable in the output, referential integrity holds (every
claim's patient reference resolves to a patient present in the same
output), volume/shape within tolerance of the sizing rule. Only a passing
result is eligible to be published.

**9. Data plane → Metadata plane.** Every step above writes lineage: which
job ran, on which policy version, with what inputs, with what result. The
certification result becomes durable, auditable evidence in the security/
governance plane's certification evidence store — referenceable later by
an auditor without having to re-run anything.

**10. Metadata plane: snapshot registered.** A new versioned snapshot
record is created: storage location, size, row counts, source job run,
refresh cadence, expiry.

**11. Control plane → UI.** The engineer's console shows the request as
complete, with a link to inspect the snapshot's metadata (row counts,
certification status) and — for an authorized role — the certification
evidence.

**12. Refresh, later.** On the configured weekly cadence, the control
plane's orchestrator automatically resubmits an equivalent job (same
policy resolution logic, re-run against then-current source shape),
producing a new snapshot version rather than mutating the old one in
place, so any environment still pointed at the prior version keeps working
until it's explicitly moved to the new one.

## What to notice

- The UI never sees raw data, ever — only already-masked/certified results
  and metadata about them.
- The data plane never makes an authorization decision — that's entirely
  the control plane's + security/governance plane's job, enforced *before*
  a job is submitted.
- Certification does not trust the job that produced the data — it
  independently re-checks the output. This "don't trust, verify" pattern
  shows up repeatedly in this platform's design and is worth internalizing.
- Every step that matters for compliance produces a durable record
  somewhere (metadata plane for operational lineage, security/governance
  plane for audit/certification evidence) — nothing that matters is "just a
  log line" that could roll off and be lost.
