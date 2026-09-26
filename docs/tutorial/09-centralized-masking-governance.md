# Tutorial 09 — Centralized enterprise masking governance

This tutorial walks through real, runnable code:
`control_plane.domain.governance` (a real, DB-backed masking policy
approval workflow, plus two named business consumers that request
datasets through it), exposed at `/api/v1/governance`. Read
[ADR-0014](../adr/0014-masking-governance-lives-in-control-plane.md)
first -- it explains why this domain lives in `services/control-plane`
rather than `services/governance-service`, which is the single most
important design decision this phase made.

## The problem this phase solves

A large enterprise TDM platform is not used by one team. `ROADMAP.md`
Phase 10's scenario: two organizational arms, `LEFT_ARM` and `RIGHT_ARM`,
both need masked test data. They will legitimately want different
things -- different subset sizes, different refresh cadences, different
environments, different performance requirements. What they must **not**
be allowed to do is each define their own masking rules for sensitive
fields. If `LEFT_ARM` and `RIGHT_ARM` could each configure their own SSN
masking technique, this platform's entire value proposition (ADR-0006's
deterministic, keyed masking; a governed, auditable, single source of
truth for "how is PHI/PII actually protected") collapses into two
uncoordinated, unauditable pipelines that happen to share infrastructure.

This phase's job is to make "one centrally governed masking standard,
many consumers" a real, enforced architecture -- not a policy document
nobody can verify against running code.

## What already existed, and what this phase adds

Phase 3 already produced a real, versioned `MaskingPolicy`
(`data_plane.masking.policy.DEFAULT_POLICY`, `POLICY_NAME`/
`POLICY_VERSION`) and ADR-0011 already recorded two version identifiers
(`masking_policy_version`, `masking_engine_version`) on every masking run
and certification report. What was missing, and what
`docs/problems/problems_phase_03.md`'s P3-3 named Phase 10 as the owner of: nothing
*governed* that policy -- no database-backed record of who approved a
given policy version, no enforced state machine over its approval
lifecycle, and no concept of a "business consumer" that could only ever
request data through an approved version.

This phase adds four new contracts
(`healthcare_tdm_contracts.governance`) and a new control-plane domain
(`control_plane.domain.governance`):

| Contract | Purpose |
|---|---|
| `MaskingPolicyVersion` | A governed, immutable snapshot of a real Phase 3 `MaskingPolicy` (the full rule set, not just its name/version) |
| `PolicyApproval` | An append-only log of every approval-workflow action against a `MaskingPolicyVersion` |
| `BusinessConsumer` | One organizational arm (`LEFT_ARM`, `RIGHT_ARM`) |
| `ConsumerDatasetRequest` | One business consumer's request for a dataset, referencing an APPROVED `MaskingPolicyVersion` by foreign key -- **never** a masking rule of its own |

## The approval workflow is a real, enforced state machine

`PolicyApprovalStatus` has five states:
`draft -> pending_approval -> approved -> superseded`, with a `rejected`
branch off `pending_approval`. This is the *third* time this repository
uses this exact pattern -- a transition table as data
(`healthcare_tdm_contracts.POLICY_APPROVAL_STATUS_TRANSITIONS`) enforced
by one function (`control_plane.domain.governance.state_machine.transition`)
that every status change must go through:

```python
# data_plane.certification.state_machine   (Phase 6)
# control_plane.domain.lifecycle.state_machine   (Phase 7)
# control_plane.domain.governance.state_machine   (Phase 10, this file)
```

Approving a new policy version does one more thing beyond the bare
transition: it also transitions any *other* currently-`approved` version
of the same `policy_name` to `superseded`
(`GovernanceRepository.approve_policy_version`). That is what makes
"the currently-approved policy version for `phase3-default`" a
well-defined, single answer at any point in time
(`GovernanceRepository.get_approved_policy_version`) -- not a race
between two simultaneously-valid versions.

## Governance is structural, not just conventional

This is the detail worth reading twice: `ConsumerDatasetRequest` has **no
field** that could carry a masking rule, technique, or policy override.
Look at its fields: `dataset_name`, `environment`, `policy_version_id`,
`subset_size_hint`, `refresh_cadence_type`, `performance_requirements`.
The *only* masking-policy reference is `policy_version_id`, a foreign
key. `GovernanceRepository.submit_consumer_request`'s parameters mirror
this exactly -- there is no `masking_rules=` or `custom_policy=` argument
anywhere for a consumer to pass.

The one real enforcement point is checking that foreign key:

```python
# control_plane/domain/governance/repository.py
policy_row = self._get_policy_version_row(policy_version_id)
if PolicyApprovalStatus(policy_row.approval_status) is not PolicyApprovalStatus.APPROVED:
    raise PolicyVersionNotApprovedError(...)
```

`test_governance_repository.py::test_consumer_cannot_attach_custom_masking_rules`
proves both halves of this: it introspects `ConsumerDatasetRequest.model_fields`
and `GovernanceRepository.submit_consumer_request`'s signature (no
forbidden field/parameter exists), and then demonstrates the one real
attempted bypass -- submitting a request against a `draft` policy
version -- being rejected with `PolicyVersionNotApprovedError`. The demo
script's Step 9 does the same thing end-to-end over HTTP (409).

## RIGHT_ARM's additional QA capacity: real Phase 7/8 integration, not a parallel system

This is the other headline requirement: when RIGHT_ARM asks for
additional QA capacity, that demand must be scheduled into the
*existing* refresh calendar and be visible in the *existing* capacity
plan -- not become a second, governance-layer-local bookkeeping system.

`GovernanceRepository` is constructed with one `sqlalchemy.orm.Session`
and internally composes a `LifecycleRepository` sharing that exact
session:

```python
class GovernanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.lifecycle = LifecycleRepository(session)   # Phase 7, same transaction
```

`fulfill_consumer_request` calls straight into it -- first
`upsert_policy` (only if the consumer's requested cadence differs from
what is currently configured for that `(environment, dataset_name)`),
then `request_environment` (Phase 7's own idempotent-per-`(environment,
dataset_name)` method):

```python
def fulfill_consumer_request(self, consumer_request_id, *, triggered_by):
    ...
    if current_policy.cadence_type is not cadence_type:
        self.lifecycle.upsert_policy(...)          # real Phase 7 write
    env_request = self.lifecycle.request_environment(...)  # real Phase 7 write
    row.environment_request_id = str(env_request.request_id)
```

The result is a real `EnvironmentDatasetRequest` row. Phase 8's
`CapacityPlanner` -- completely unmodified by this phase -- reads that
same table and reports the new demand. No new capacity-accounting code
was written for this phase; there was nothing to write.

## Try it yourself: a real, end-to-end run

```bash
python scripts/demo_phase10_governance.py
```

Real output from exactly this command:

```
STEP 1 -- Draft, submit, and approve the centrally governed masking policy
Wrapping the real Phase 3 DEFAULT_POLICY: name='phase3-default' version=1 rule_count=82 masking_engine_version='1.0.0'
Drafted MaskingPolicyVersion ... (status=draft)
Submitted for approval (status=pending_approval)
APPROVED by compliance-steward@example.org -> status=approved

STEP 3 -- Run two real Phase 6 certification pipelines under the SAME governed policy
  LEFT_ARM: report=...  status=PUBLISHED  policy=phase3-default@1  engine=1.0.0  gates_passed=11/11
  RIGHT_ARM: report=... status=PUBLISHED  policy=phase3-default@1  engine=1.0.0  gates_passed=11/11

STEP 5 -- Both arms request datasets, referencing the SAME approved policy version
  LEFT_ARM  -> policy_version_id=93698fab-ae0d-43ac-9992-f58eaba074a6
  RIGHT_ARM -> policy_version_id=93698fab-ae0d-43ac-9992-f58eaba074a6
  CONFIRMED: both arms' requests resolve to the identical governed policy_version_id.

STEP 6 -- Real Phase 8 capacity plan BEFORE RIGHT_ARM's additional QA capacity request
  environment_count=2  distinct_dataset_version_count=2  shared_total_storage_bytes=173105
    dev          left-arm-member-claims-subset    cadence=weekly
    dev          right-arm-member-claims-subset   cadence=weekly

STEP 7 -- RIGHT_ARM requests ADDITIONAL QA capacity (different cadence, higher volume)
  Fulfilled into a REAL Phase 7 EnvironmentDatasetRequest: ...
  Phase 7 confirms: environment=qa dataset_name=right-arm-member-claims-subset consumer='RIGHT_ARM'
  Phase 7 refresh policy for (QA, right-arm-member-claims-subset): cadence_type=biweekly

STEP 8 -- Real Phase 8 capacity plan AFTER: RIGHT_ARM's QA demand is now visible
  environment_count=3 (was 2)
    dev          left-arm-member-claims-subset    cadence=weekly
    dev          right-arm-member-claims-subset   cadence=weekly
    qa           right-arm-member-claims-subset   cadence=biweekly
  This demand was produced entirely by Phase 7/8's existing, unmodified machinery.

STEP 9 -- Adversarial: a consumer cannot bypass governance with an unapproved policy version
  RIGHT_ARM drafts its OWN policy revision (status=draft) -- still not approved.
  Attempt rejected: HTTP 409 -> MaskingPolicyVersion ... has approval_status='draft', not 'approved'...
```

## The endpoints

All under `/api/v1/governance`:

- `POST /policy-versions` / `GET /policy-versions` / `GET /policy-versions/{id}`
- `GET /policy-versions/approved/{policy_name}` -- the single currently-usable version
- `POST /policy-versions/{id}/submit` / `/approve` / `/reject`
- `GET /policy-versions/{id}/approvals` -- the audit trail
- `POST /business-consumers` / `GET /business-consumers` / `GET /business-consumers/{id}`
- `POST /consumer-requests` / `GET /consumer-requests` / `GET /consumer-requests/{id}`
- `POST /consumer-requests/{id}/fulfill` -- the real Phase 7 integration point

## What this phase deliberately does not solve

`docs/problems/problems_phase_10.md` records the honest gaps -- read it before treating
this as more complete than it is. The two worth knowing up front:

- **P10-1**: nothing today verifies, at `DatasetVersion` registration
  time, that a certification run actually used the currently-approved
  `MaskingPolicyVersion`'s exact content -- the demo script does this
  correctly (it passes the approved policy object explicitly into the
  certification pipeline), but nothing *enforces* it yet.
- **P10-2**: there is no RBAC check on who may approve a policy version
  -- `performed_by` is any caller-supplied string, the same
  already-documented gap every other actor field in this service has.
  That is `services/governance-service`'s eventual job once it is built
  out for real.
