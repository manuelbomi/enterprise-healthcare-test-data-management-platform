# ADR-0019: A distinct, clearly-labeled governed registration endpoint, alongside the pre-existing ungoverned one

## Status

Accepted

## Context

`docs/problems/problems_phase_10.md` P10-1 and `docs/problems/problems_final_review.md` P1-8 both
found the same gap: `LifecycleRepository.register_dataset_version`
(Phase 7, `POST /api/v1/lifecycle/dataset-versions`) never calls into
`GovernanceRepository.get_approved_policy_version` (Phase 10). An
operator can run the certification pipeline with a hand-built
`MaskingPolicy` that was never drafted/approved through Phase 10's
governance workflow at all, and Phase 7 registers the resulting
`DatasetVersion` without complaint — the only reason this hasn't caused
a real problem is that every demo script and test happens to pass the
actually-approved policy object by convention, not because anything
enforces it.

Phase 18A had to decide how to close this. Two options were considered:

1. **Make governance enforcement mandatory** on the existing
   `POST /dataset-versions` endpoint. This is the semantically cleanest
   fix, but it is a breaking change to every pre-Phase-10 caller: every
   demo script (`demo_phase7_lifecycle.py`), every tutorial chapter
   (`docs/tutorial/07-dataset-lifecycle-and-refresh.md`), and dozens of
   existing tests across `test_lifecycle_api.py`,
   `test_lifecycle_repository.py`, `test_capacity_api.py`,
   `test_evidence_api.py`/`test_evidence_repository.py`, and
   `test_failure_injection.py` register a dataset version via a
   hand-built `CertificationReport` with no corresponding drafted/
   approved `MaskingPolicyVersion` at all — none of them exercise Phase
   10 governance, because most of them predate it or deliberately test
   Phase 7 in isolation (`ADR-0003`'s plane-separation discipline
   applies just as much to phase-scoped test isolation). Retrofitting
   governance as a mandatory precondition on this one endpoint would
   force every one of those call sites to first draft/submit/approve a
   matching policy version, a disproportionately large blast radius for
   a Phase 18A fix-cycle item.
2. **Add a second, distinct, clearly-labeled endpoint** that enforces
   governance, leaving the original endpoint's behavior unchanged but
   honestly re-documented as the explicitly ungoverned path.

## Decision

Add `POST /api/v1/lifecycle/dataset-versions/governed`
(`register_dataset_version_governed` in `api/v1/lifecycle.py`), which
independently re-derives (via `GovernanceRepository.get_approved_policy_version`
— never trusting the certification report's own claim) whether the
certification report's `masking_policy_name`/`masking_policy_version`
actually match the currently-APPROVED `MaskingPolicyVersion`, rejecting
registration with HTTP 409 if not.

The pre-existing `POST /api/v1/lifecycle/dataset-versions` endpoint is
left functionally unchanged, but its docstring now explicitly says what
it always implicitly was: the **ungoverned/direct** registration path,
cross-referencing this ADR and the governed alternative.

## Consequences

- No existing test, demo script, or tutorial chapter needed to change
  its registration call to keep passing — this decision closes P1-8 as
  a genuinely new, additive capability rather than a breaking change.
- A real deployment that wants Phase 10 governance to actually mean
  something end to end should route all dataset-version registration
  through the governed endpoint (or build automation — a CI job, an
  orchestrator step — that always calls it), and should treat any use
  of the ungoverned endpoint as an explicit, auditable exception. This
  ADR does not itself remove or deprecate the ungoverned path; a future
  phase could revisit that once every caller has migrated, at which
  point the ungoverned endpoint would be superseded here, matching
  `CONTRIBUTING.md`'s ADR-numbering convention (a reversed decision gets
  a new ADR that supersedes this one; this one is never renumbered or
  deleted).
- `register_dataset_version_governed` records the same
  `DATASET_VERSION_REGISTERED` audit event as the ungoverned path, with
  an additional `governed: "true"` / `approved_policy_version_id` detail
  field, so an auditor reading the audit trail (or a Phase 13
  `AuditEvidencePackage`) can distinguish which path a given
  registration went through.
- See `services/control-plane/tests/test_lifecycle_governed_registration.py`
  for the regression proof: the same registration that the ungoverned
  endpoint accepts unconditionally is rejected by the governed endpoint
  both when no policy was ever approved and when the certification
  report names a policy version that does not match the currently
  APPROVED one.
