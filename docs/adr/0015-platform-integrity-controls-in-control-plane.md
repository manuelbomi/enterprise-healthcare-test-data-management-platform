# ADR-0015: Phase 11's platform-integrity controls (RBAC, audit log, readiness, dead-letter) live in `services/control-plane`, enforced at the API layer

## Status

Accepted

## Context

`ROADMAP.md` Phase 11 ("Platform Integrity") asks for RBAC, audit
logging, readiness checks, and a dead-letter concept, among other
cross-cutting controls. `ARCHITECTURE.md` section 2.4 names all of
these as eventual `services/governance-service` responsibilities. As
of this phase, that service remains exactly what
[ADR-0014](0014-masking-governance-lives-in-control-plane.md) found it
to be for Phase 10: a structural scaffold with no database, no FastAPI
app, and no `sqlalchemy` dependency. Two questions needed real answers,
not hand-waves: *where does this code live*, and — for RBAC
specifically — *at which layer is it enforced* (the API router, or the
domain repository underneath it)?

## Decision

### Where: `services/control-plane/src/control_plane/platform/`

For the same reason ADR-0014 gives for Phase 10's governance domain:
the controls this phase adds must integrate, transactionally, with
data that already lives in `control_plane.db.models` (Phase 7's
`DatasetVersionRow`, Phase 10's `MaskingPolicyVersionRow`). An audit
event recording "this dataset version was revoked" is only meaningful
if it is guaranteed to be consistent with whether the revocation
itself actually committed — that requires one shared
`sqlalchemy.orm.Session`, which only a same-service integration can
give honestly (ADR-0014's own reasoning, restated here because it
applies just as directly to this phase's controls).
`services/governance-service` remains untouched.

### At which layer: RBAC is enforced at the API router, not the domain repository

`LifecycleRepository.revoke_version` and
`GovernanceRepository.approve_policy_version` (the two most
sensitive mutations this phase gates) do **not** take an `actor_role`
parameter or call `control_plane.platform.rbac.authorize()`
themselves. Enforcement happens in `api/v1/lifecycle.py`/
`api/v1/governance.py`'s route handlers, *before* the repository is
called at all.

This was not the first design considered — putting the check inside
the repository (mirroring how `state_machine.transition` enforcement
lives in the domain layer, not the API layer) looked more consistent
with this codebase's existing conventions at first. It was rejected
for a concrete, discovered reason: an `AuthorizationError` raised
*inside* a repository call, after an audit-denial event had already
been added to the same `Session`, would be rolled back by
`control_plane.db.session.session_scope`'s blanket
`except Exception: session.rollback()` — silently destroying the very
denial record `THREAT_MODEL.md`'s "Repudiation" mitigation exists to
preserve. Enforcing at the API layer means a denial is recorded (and
`session.commit()`ed immediately) *before* any exception is raised at
all, so the record survives the request's ultimate `HTTPException`.

The honest cost of this decision: a future caller of
`LifecycleRepository.revoke_version` directly (a script, a test, a
different future API layer) would bypass the RBAC check entirely,
since the repository itself does not enforce it. This is an accepted,
documented tradeoff for this phase's scope — see
`problems_phase_11.md` P11-4 for the narrower, related gap (RBAC is
only wired to four endpoints total) this ADR does not attempt to
close.

## Consequences

- `control_plane.platform.audit.AuditLogRepository`,
  `control_plane.platform.dead_letter.DeadLetterStore`, and
  `control_plane.platform.rbac.authorize()` are all real, tested,
  DB-integrated (the first two) or pure-function (the third)
  mechanisms — not stubs, not a no-op RBAC that always allows (see
  `test_platform_rbac.py`'s explicit proof of both directions:
  permitted roles succeed, others are rejected).
- If `services/governance-service` is built out for real in a later
  phase, `control_plane.platform.rbac`'s permission table is the
  natural piece to move there first (it has no database dependency at
  all, unlike `audit.py`/`dead_letter.py`, which would need either a
  cross-service call or a schema migration to move cleanly) — this
  ADR does not claim the current location is permanent, only that it
  is the correct integration point for *this* phase's scope, the same
  qualification ADR-0014 makes for its own decision.
- Every other lifecycle/governance mutation this phase did not gate
  (register a dataset version, request/refresh an environment,
  draft/submit a policy version, register a consumer, submit/fulfill a
  consumer request) remains open to any caller regardless of role —
  tracked honestly in `problems_phase_11.md` P11-4, not hidden.
