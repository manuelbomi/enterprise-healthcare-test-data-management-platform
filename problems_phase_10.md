# Problems — Phase 10 (Centralized Enterprise Masking Standard / Multi-Business-Unit Governance)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before/during implementation, updated as work proceeded,
resolved entries removed once fixed and tested. Anything left below at
the end of the phase is a genuine open issue for a later phase.

## Risks identified before/during implementation, and how they were resolved

- **Where does this domain live -- `services/governance-service` (its
  name-match) or `services/control-plane` (where the machinery it must
  integrate with actually lives)?** Resolved by inspecting
  `services/governance-service/` directly: it is a structural scaffold
  only (empty `api/__init__.py`/`audit/__init__.py`, no database, no
  FastAPI app). Phase 10's hardest requirement -- RIGHT_ARM's additional
  QA capacity request must be scheduled into Phase 7's *existing*
  refresh calendar and Phase 8's *existing* capacity plan, not a
  parallel system -- needs a same-transaction call into
  `LifecycleRepository`, which only a same-service, same-`Session`
  integration can give it honestly. Built in
  `services/control-plane/src/control_plane/domain/governance/`
  instead; documented as
  [ADR-0014](docs/adr/0014-masking-governance-lives-in-control-plane.md)
  since this was a meaningful, reversible-but-costly-to-reverse
  decision. This also resolves `problems_phase_03.md`'s P3-3 ("masking
  policy is not yet control-plane-managed/versioned in a database"),
  whose own text named Phase 10 as its owner.
- **How to prevent a business consumer from attaching its own masking
  rules, not just discourage it by convention?** Resolved structurally:
  `healthcare_tdm_contracts.ConsumerDatasetRequest` has no field of any
  kind that could carry a masking rule/technique/override -- only a
  `policy_version_id` foreign key. `GovernanceRepository.submit_consumer_request`'s
  signature has no such parameter either. The one real path a consumer
  has to influence masking at all (`policy_version_id`) is checked
  against `MaskingPolicyVersion.approval_status` and rejected
  (`PolicyVersionNotApprovedError`, HTTP 409) unless it is APPROVED.
  Verified by `test_consumer_cannot_attach_custom_masking_rules`
  (introspects both the model's fields and the method's signature, then
  demonstrates the real rejection) and
  `scripts/demo_phase10_governance.py` Step 9 (RIGHT_ARM drafts its own
  unreviewed policy revision and is rejected attempting to use it).
- **How to prove "both arms use the same approved policy version" is
  actually enforced, not just true by the way the demo happens to be
  written?** Resolved by making `MaskingPolicyVersion.approval_status`
  APPROVED singular per `policy_name` at any time:
  `approve_policy_version` transitions any *other* currently-APPROVED
  version of the same `policy_name` to SUPERSEDED as part of approving
  a new one (`GovernanceRepository.approve_policy_version`,
  `test_approving_a_new_version_supersedes_the_previous_approved_version`).
  So `get_approved_policy_version(policy_name)` is always a single,
  well-defined answer a consumer request resolves against -- not a race
  between multiple simultaneously-"approved" versions.
- **Mirror the state-machine pattern already used twice (Phase 6
  certification, Phase 7 dataset version), not invent a third
  convention.** Resolved: `PolicyApprovalStatus`/
  `POLICY_APPROVAL_STATUS_TRANSITIONS` (data, in
  `healthcare_tdm_contracts.governance`) plus
  `control_plane.domain.governance.state_machine.transition`
  (enforcement) is a structural copy of
  `control_plane.domain.lifecycle.state_machine`, which is itself a
  structural copy of `data_plane.certification.state_machine`.

## Open problems

### P10-1 — No enforced link between a Phase 6/7 `DatasetVersion`'s recorded masking policy and Phase 10's governed `MaskingPolicyVersion`

- **Status:** open
- **Description:** `DatasetVersion.masking_policy_name`/
  `masking_policy_version` (Phase 7, from ADR-0011) and
  `MaskingPolicyVersion.policy_name`/`policy_version` (Phase 10) are
  correlated *by convention* (matching strings), not by a database
  foreign key or a certification-pipeline-time check. Nothing in
  `LifecycleRepository.register_dataset_version` verifies that the
  `CertificationReport` it is registering actually used the
  *currently-approved* `MaskingPolicyVersion`'s exact rule content --
  an operator could run the Phase 6 pipeline with a masking policy that
  was never drafted/approved through Phase 10 at all, and Phase 7 would
  register it without complaint. `scripts/demo_phase10_governance.py`
  demonstrates the *correct* path (it explicitly passes
  `masking_policy=DEFAULT_POLICY`, the same object just approved,
  into `run_certification_pipeline`) but nothing *enforces* that
  discipline.
- **Repro / detail:** Call `run_certification_pipeline(..., masking_policy=some_other_policy)`
  with a hand-built `MaskingPolicy` that was never drafted through
  `POST /api/v1/governance/policy-versions`, then
  `POST /api/v1/lifecycle/dataset-versions` with the resulting report --
  it registers successfully.
- **Affected files:**
  `services/control-plane/src/control_plane/domain/lifecycle/repository.py`
  (`register_dataset_version`), `services/control-plane/src/control_plane/domain/governance/repository.py`
- **Owner for resolution:** A future phase (or a Phase 10 follow-up) that
  adds a real gate -- either a certification gate
  (`data_plane.certification.gates`) that checks the report's
  `masking_policy_name`/`masking_policy_version` against a governance
  API's currently-approved version, or a `LifecycleRepository`-side
  check against `GovernanceRepository.get_approved_policy_version`.
  Deliberately out of this phase's scope (`ROADMAP.md` Phase 10 asks for
  the governance layer and the consumer-request integration, not a
  retrofit of Phase 6/7's own gates).

### P10-2 — No RBAC enforcement on who may approve a policy version or register a business consumer

- **Status:** open (deliberately deferred, consistent with every other
  actor-attribution field in this service)
- **Description:** `PolicyApproval.performed_by`,
  `MaskingPolicyVersion.created_by`, and every other actor field in this
  domain accept any caller-supplied string -- there is no check that
  `performed_by="compliance-steward@example.org"` is actually an
  authorized approver. This is the same, already-documented gap
  `control_plane.domain.lifecycle`'s `revoked_by`/`performed_by` fields
  have (no RBAC anywhere in `services/control-plane` yet).
- **Repro / detail:** `POST /api/v1/governance/policy-versions/{id}/approve`
  succeeds with any `performed_by` value, including one that has never
  been registered as a `BusinessConsumer` or any other identity.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/governance.py`,
  `services/control-plane/src/control_plane/domain/governance/repository.py`
- **Owner for resolution:** `services/governance-service`, once it is
  built out for real (RBAC is explicitly that service's responsibility
  per `ARCHITECTURE.md` section 2.4) -- see
  `docs/adr/0014-masking-governance-lives-in-control-plane.md`'s
  Consequences section for why this domain's transactional logic still
  lives in `services/control-plane` even though the RBAC check over it
  belongs elsewhere.

### P10-3 — `ConsumerDatasetRequest` has no REJECTED/CANCELLED terminal state

- **Status:** open (minor)
- **Description:** `ConsumerRequestStatus` only has `SUBMITTED` and
  `FULFILLED`. There is no way to record "this business consumer's
  request was reviewed and declined" (e.g. capacity budget exceeded) or
  "the consumer withdrew this request" -- only omission (never calling
  `/fulfill`) represents that today, which is not a queryable, auditable
  state the way Phase 7's `EnvironmentRequestStatus.RETIRED` or Phase
  6's `CertificationStatus.FAILED` are for their own domains.
- **Repro / detail:** N/A -- a design gap, not a defect.
- **Affected files:** `libs/contracts/src/healthcare_tdm_contracts/governance.py`
  (`ConsumerRequestStatus`), `services/control-plane/src/control_plane/domain/governance/repository.py`
- **Owner for resolution:** Not currently scheduled by name; low
  priority since the phase's required demonstrations (both arms
  fulfilled, one rejected at the policy-version-approval boundary) do
  not need it.

### P10-4 — No frontend UI for this domain

- **Status:** open (out of this phase's explicit scope)
- **Description:** `ROADMAP.md` Phase 10's own scope is backend
  governance (`MaskingPolicyVersion`/`PolicyApproval`/
  `BusinessConsumer`/`ConsumerDatasetRequest`, real endpoints, tests) --
  it does not ask for a new `frontend/` page, and none was added.
  `frontend/`'s existing Masking Policies page (Phase 9) still reads
  Phase 3's JSON-artifact-backed `masking_run_summary.json`, not this
  phase's new `/api/v1/governance` endpoints.
- **Repro / detail:** N/A
- **Affected files:** `frontend/src/pages/`
- **Owner for resolution:** Not currently scheduled by name; a natural
  fit for a later console-enhancement pass once RBAC (P10-2) exists to
  gate who can approve a policy version through the UI.

### P10-5 — Real PostgreSQL remains unverified against this schema

- **Status:** open (inherited from Phase 7/8, unchanged by this phase)
- **Description:** `MaskingPolicyVersionRow`/`PolicyApprovalRow`/
  `BusinessConsumerRow`/`ConsumerDatasetRequestRow` were added to the
  exact same Postgres-portable `control_plane.db.models.Base` Phase 7
  already uses (no JSONB/native UUID columns), but -- like every table
  in that module -- have only been exercised against local SQLite in
  this environment (`infra/docker-compose` is not running here).
- **Repro / detail:** Point `TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL`
  at a real `postgresql+psycopg://...` DSN and re-run
  `test_governance_repository.py`/`test_governance_api.py`.
- **Affected files:** `services/control-plane/src/control_plane/db/models.py`
- **Owner for resolution:** Same as `problems_phase_07.md`'s equivalent
  entry -- not scheduled by name; a real infra/CI phase's job.
