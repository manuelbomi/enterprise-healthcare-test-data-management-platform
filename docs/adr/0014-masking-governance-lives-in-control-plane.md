# ADR-0014: Centralized masking governance (Phase 10) lives in `services/control-plane`, not `services/governance-service`

## Status

Accepted

## Context

`ROADMAP.md` Phase 10 asks for a single, centrally governed masking
standard serving multiple organizational arms/business units: a
`MaskingPolicyVersion`/`PolicyApproval` approval workflow wrapping
Phase 3's real `MaskingPolicy`, two named `BusinessConsumer`s
(`LEFT_ARM`, `RIGHT_ARM`), and a `ConsumerDatasetRequest` a consumer
submits that can only ever reference an *approved* policy version --
never its own masking rules. Critically, the phase also requires that a
consumer's demand (e.g. "RIGHT_ARM requests additional QA capacity")
gets *scheduled into the existing refresh calendar/capacity plan*
rather than becoming a second, parallel implementation -- meaning this
new domain must call directly into Phase 7's
`control_plane.domain.lifecycle.LifecycleRepository` and be visible to
Phase 8's `control_plane.domain.capacity.CapacityPlanner`.

`ARCHITECTURE.md` section 2.4 names `services/governance-service` as
the security/governance plane: RBAC, the immutable audit event log, the
secrets provider adapter, and the certification evidence store -- "every
other plane calls into this one ... this plane never calls into the
others." On its name alone, "masking policy governance" sounds like it
belongs there. Two things make that the wrong call for *this* phase's
concrete scope:

1. **`services/governance-service` is a structural scaffold only.**
   `services/governance-service/src/governance_service/` contains empty
   `api/__init__.py` and `audit/__init__.py` placeholders and nothing
   else (see the service's own README: "Structural scaffold only").
   There is no FastAPI app, no database session/engine wiring, no
   `pyproject.toml` dependency on `sqlalchemy`. Standing up a second
   real, database-backed service is a much larger unit of work than
   Phase 10's actual scope, and `ROADMAP.md` reserves the
   security/governance plane's real build-out for a later phase
   (`docs/problems/problems_master.md` tracks this; `ARCHITECTURE.md` section 2.4
   remains a design target, not yet built code, as of Phase 9).
2. **The phase's hardest requirement is a same-transaction integration
   with Phase 7/8, which already live in `services/control-plane`.**
   `GovernanceRepository.fulfill_consumer_request` must call
   `LifecycleRepository.request_environment`/`upsert_policy` in the same
   unit of work that updates the `ConsumerDatasetRequest` row, so a
   partial failure (e.g. the environment-request write succeeds but the
   consumer-request status update fails) cannot leave the two domains'
   state inconsistent. That requires one shared `sqlalchemy.orm.Session`
   against one shared `Engine`/schema. If this domain lived in
   `services/governance-service` instead, the only way to satisfy "call
   into the existing Phase 7/8 machinery" would be an HTTP call to
   `services/control-plane`'s API from inside `services/governance-service`
   -- which (a) does not exist yet as reusable inter-service HTTP client
   infrastructure anywhere in this repository, (b) would make "schedule
   into the existing capacity plan" eventually-consistent across a
   network call instead of transactional, and (c) would be exactly the
   kind of "fake it" integration ADR-0012 explicitly rejected for the
   Airflow/Databricks seam -- looking like a real cross-service
   integration without the infrastructure to back it.

`ARCHITECTURE.md` section 2.1 already positions the control plane as
owning "the policy engine: resolving which masking policy ... applies"
-- centralized masking-policy *governance* (draft/approve/version) is a
natural extension of that responsibility, not a violation of it. RBAC
(who is *allowed* to approve a policy version) remains out of this
phase's scope and genuinely belongs to `services/governance-service`
once it exists for real -- this ADR does not claim otherwise.

## Decision

Phase 10's centralized masking governance domain
(`MaskingPolicyVersion`, `PolicyApproval`, `BusinessConsumer`,
`ConsumerDatasetRequest`) is implemented in
`services/control-plane/src/control_plane/domain/governance/`, with its
tables added to the same `control_plane.db.models` schema/`Base` Phase 7
already defined (so `init_schema()` creates them in the same engine),
and its endpoints exposed at `/api/v1/governance/*`
(`services/control-plane/src/control_plane/api/v1/governance.py`),
mirroring the exact module layout, state-machine pattern, and
repository/API conventions Phase 7 (`domain/lifecycle`) and Phase 8
(`domain/capacity`) already established in this same service.

`control_plane.domain.governance.repository.GovernanceRepository` is
constructed with one `sqlalchemy.orm.Session` and internally composes a
`control_plane.domain.lifecycle.repository.LifecycleRepository` sharing
that exact session (`self.lifecycle = LifecycleRepository(session)`),
so `fulfill_consumer_request` calling
`self.lifecycle.request_environment(...)` is a real, same-transaction
write against the same schema `CapacityPlanner` already reads --
verified end-to-end in `scripts/demo_phase10_governance.py` and
`test_governance_repository.py::test_right_arm_additional_qa_capacity_uses_existing_lifecycle_machinery`.

`services/governance-service` is left untouched (still the Phase 0
structural scaffold) -- this decision does not claim Phase 10 satisfies
`ARCHITECTURE.md` section 2.4's RBAC/audit-log/secrets-provider scope,
only that *masking policy version governance* specifically belongs
alongside the lifecycle/capacity domains it must transactionally
integrate with.

## Consequences

- `ConsumerDatasetRequest.policy_version_id` is a real foreign key
  (`consumer_dataset_request.policy_version_id ->
  masking_policy_version.policy_version_id`) enforced at the database
  level within one schema, not a cross-service reference that could
  point at a policy version that was deleted/never existed in another
  service's database.
- `PolicyApprovalStatus`'s who-can-approve question (RBAC) is
  deliberately NOT enforced by this phase -- `approve_policy_version`
  accepts any `performed_by` string, the same honest gap
  `control_plane.domain.lifecycle`'s `revoked_by`/`performed_by` fields
  already have (no RBAC check anywhere in this service yet). Tracked in
  `docs/problems/problems_phase_10.md`; real RBAC enforcement is
  `services/governance-service`'s eventual job once it is built out for
  real, and this domain's `performed_by` fields are exactly the fields
  a future RBAC check would gate.
- If `services/governance-service` is built out for real in a later
  phase, this domain's *policy version approval decision* could still
  reasonably be split further (e.g. the RBAC check moves there while
  the versioned-policy storage/scheduling-integration stays here) --
  this ADR is a decision about where the *transactional* governance
  logic lives today, not a permanent claim that no part of it will ever
  move.
- Consistent with `ARCHITECTURE.md`'s existing Phase 3/4/5/6/7 "note"
  pattern: this ADR is the authoritative answer to "why is masking
  *governance* in control-plane when masking *execution* is in
  data-plane and RBAC is supposed to be governance-service" -- see
  `ARCHITECTURE.md`'s Phase 10 note, which points here.
