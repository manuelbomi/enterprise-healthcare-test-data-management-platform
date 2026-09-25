# Chapter 16 — Platform integrity

## The concept

A platform can have every capability Chapters 5-15 describe and still
be unsafe to run in production if it doesn't also handle *failure*
well: a job crashing halfway through, a duplicate request arriving
twice, a caller with no permission attempting a sensitive action, a
transient database blip. Platform integrity is the set of controls that
make a system's *unhappy paths* — not just its happy path — behave
correctly and observably. `docs/PLATFORM_INTEGRITY.md` frames this as
an honest, control-by-control account: which controls already existed
from earlier phases, which are genuinely new, and which remain real,
documented gaps — never a claim of full coverage for its own sake.

## Readiness vs. liveness — a real, deliberate distinction

`control_plane.platform.readiness` separates two questions a container
orchestrator needs answered differently:

- **Liveness** (`/api/v1/health`) — "is the process up at all?"
- **Readiness** (`/api/v1/ready`) — "can this process serve real traffic
  right now?" — checks the lifecycle database is actually reachable
  (`SELECT 1`, with retry), and reports (informationally, never gating)
  whether the Chapter 6 catalog artifact is present.

Conflating the two would mean a transient database blip causes an
orchestrator to kill and restart an otherwise-healthy process, instead
of simply pausing traffic to it until the database recovers. Chapter 18
covers how a real Kubernetes deployment wires these to different probe
types.

## RBAC — a real, closed permission table, not a no-op

`control_plane.platform.rbac` defines a small, closed set of roles
(`VIEWER`, `REQUESTER`, `DATA_STEWARD`, and a compliance/security
reviewer role), most of which are granted **no** permissions by default.
`authorize()` raises `AuthorizationError` — never silently allows — for
any `(role, permission)` pair not explicitly listed. This is enforced at
the API layer for the platform's highest-sensitivity mutations:
revoking a dataset version, rolling an environment back, approving or
rejecting a governed masking policy (Chapter 9's masking policy,
governed the way Chapter 19 describes).
`services/control-plane/tests/test_failure_injection.py` proves this
over real HTTP: a `REQUESTER`-role actor attempting to revoke a dataset
version gets HTTP 403, not 200.

What this deliberately does *not* do, documented rather than hidden:
verify the caller-supplied role actually belongs to the caller-supplied
identity string — there is still no identity provider anywhere in this
repository. RBAC here answers "if you claim this role, are you allowed
to do this," not "are you who you claim to be."

## Audit logging, retry, and dead-letter handling

- **`control_plane.platform.audit.AuditLogRepository`** — the first
  real, durable, append-only wiring of the audit-event contract, with
  no `update`/`delete` method of any kind on the class at all. That
  absence *is* the immutability guarantee — there is no code path in
  this codebase that can modify or remove a row once written. Chapter 19
  covers this in depth.
- **`control_plane.platform.retry.retry_with_backoff`** — wired into
  exactly one real call site (the readiness database check), and
  deliberately *not* wired into data-plane job execution, because a
  masking job that crashes mid-run can leave a partially-written output
  directory with no atomicity guarantee — blindly retrying against the
  same output path risks making corruption worse, not safer.
- **`control_plane.platform.dead_letter.DeadLetterStore`** — a durable,
  queryable record of individually-isolated job/sweep failures, wired
  into the scheduled refresh sweep (Chapter 13) so a failed scheduled
  refresh is recorded durably, not only returned to the one synchronous
  caller of that sweep.

## Eight real failure-injection scenarios

This is the part of the chapter worth internalizing: these are not
theoretical descriptions of what *should* happen on failure — each row
is a real test that actually injects the failure and checks the result.

| # | Scenario | Test |
|---|---|---|
| 1 | Masking job crashes halfway | `test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output` |
| 2 | Source schema changes | `test_a_column_not_in_the_catalog_falls_back_to_safe_masking_not_raw_passthrough` |
| 3 | Storage unavailable | `test_storage_unavailable_fails_cleanly_without_a_leaked_stack_trace_of_raw_data` |
| 4 | Duplicate refresh request | `test_duplicate_refresh_requests_do_not_corrupt_state` |
| 5 | Certification validation fails | `test_a_failed_certification_report_cannot_be_registered_as_a_dataset_version` |
| 6 | Secret missing | `test_masking_with_no_key_anywhere_fails_fast_before_any_output_is_written` |
| 7 | Dataset becomes corrupted | `test_corrupted_masked_parquet_is_rejected_downstream_not_silently_misread` |
| 8 | Consumer requests revoked dataset | `test_consumer_cannot_fulfill_request_against_a_dataset_whose_only_version_is_revoked` |

Scenario 1 found a genuine gap while being built, not a hypothetical
one: a masking run that crashes mid-way used to leave no signal that its
output was incomplete. The fix — a checkable
`_MASKING_RUN_INCOMPLETE.marker` — is a real, if partial, mitigation:
individual per-source-system files still aren't written atomically
(`problems_phase_11.md` P11-1), which is exactly why retry is not
blindly wired into job execution (above).

## Where to go next

Continue to [Chapter 17 — CI/CD](17-ci-cd.md), or read
`docs/PLATFORM_INTEGRITY.md` in full for every control this repository
checked, including the ones marked "not built" (container health) and
why.
