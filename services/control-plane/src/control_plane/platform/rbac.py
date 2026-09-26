"""A real, enforced role-based authorization check.

`ARCHITECTURE.md` section 2.4 names RBAC as a `services/governance-service`
responsibility; `problems_phase_07.md` P7-6 and `problems_phase_10.md`
P10-2 both explicitly deferred it ("no RBAC anywhere in this service
yet"). This module is Phase 11's answer -- not a full identity/auth
system (out of scope, per the phase brief), but a real permission-table
lookup that actually rejects an insufficiently-privileged actor,
enforced at the API layer for the platform's highest-sensitivity
mutations: revoking a dataset version, rolling an environment back,
approving/rejecting a governed masking policy version, and (Phase 18A)
running a scheduled bulk refresh sweep.

What makes this "real" rather than a no-op:

- `ROLE_PERMISSIONS` is a real, closed table -- most roles are granted
  *no* permissions here at all (`VIEWER`, `REQUESTER`).
- `authorize()` raises `AuthorizationError` (never silently allows) for
  any `(role, permission)` pair not explicitly listed.
- `services/control-plane/tests/test_platform_rbac.py` proves this
  with unit tests, and `test_failure_injection.py` proves it end to
  end over real HTTP requests (a `REQUESTER`-role actor attempting to
  revoke a dataset version gets HTTP 403, not 200).

**Phase 18A update (`problems_final_review.md` P0-1, now resolved):**
before this phase, `role` here was accepted from a caller-supplied,
*unverified* `actor_role` request-body field -- this module answered
"if you claim this role, are you allowed to do this," never "are you
who you claim to be," and nothing in the codebase verified the claim at
all. `control_plane.platform.auth` now closes that gap with a real (but
deliberately minimal -- see its own module docstring) JWT
issuance/verification layer: every API-layer call site below resolves
`role` from `control_plane.platform.auth.AuthenticatedActor.role`
(`Depends(get_current_actor)`, which verifies a signed token) instead of
trusting a request field. `authorize()` itself is unchanged -- it never
trusted anything to begin with; only *where its `role` argument comes
from* changed. Every other actor-attribution field in this service
(`revoked_by`, `performed_by`, `requested_by`, `generated_by`,
`accessed_by`) remains what `problems_phase_11.md` P11-4 already,
honestly, called it: advisory metadata, not a security control -- only
the field an authorization *decision* is made from needed to move
behind real verification.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Roles a caller may claim via a request's `actor_role` field.

    Deliberately small and named after real TDM-platform job
    functions, not generic "admin/user" labels -- this is the
    permission table `DATA_GOVERNANCE.md` implies exists ("who can
    approve a masking policy change, who can view certification
    evidence" -- `ARCHITECTURE.md` section 2.4's own RBAC examples).
    """

    #: Read-only access -- can list/view, never mutate.
    VIEWER = "viewer"
    #: Can request/refresh a dataset into an environment (ordinary
    #: day-to-day consumer of the platform), but not revoke/rollback/
    #: approve anything.
    REQUESTER = "requester"
    #: Owns the data engineering side of the pipeline -- can register
    #: dataset versions and roll an environment back to an earlier one.
    DATA_STEWARD = "data_steward"
    #: The compliance/security reviewer role -- the only role that may
    #: approve or reject a governed masking policy version, and the
    #: only role that may revoke a dataset version outright (a stronger
    #: action than a rollback, since it blocks the version for every
    #: future selection, not just one environment's pointer).
    COMPLIANCE_APPROVER = "compliance_approver"
    #: Superset of every permission below -- an explicit, auditable
    #: "break-glass" role, not a default.
    PLATFORM_ADMIN = "platform_admin"


class Permission(str, Enum):
    """The sensitive actions this phase gates. Deliberately a small,
    closed set -- see `problems_phase_11.md` P11-4 for what is *not*
    yet gated (every other lifecycle/governance mutation)."""

    REVOKE_DATASET_VERSION = "revoke_dataset_version"
    ROLLBACK_DATASET_VERSION = "rollback_dataset_version"
    APPROVE_POLICY_VERSION = "approve_policy_version"
    REJECT_POLICY_VERSION = "reject_policy_version"
    #: Phase 18A (`problems_final_review.md` P1-2): `POST
    #: /api/v1/lifecycle/scheduler/run-due` executes a SCHEDULED refresh
    #: for every currently-due request in one call -- a larger blast
    #: radius than any single-request mutation this table already
    #: gated, yet it previously had no RBAC check at all. Restricted to
    #: `PLATFORM_ADMIN` only (not even `DATA_STEWARD`), reflecting that
    #: in a real deployment this endpoint should only ever be invoked by
    #: a trusted internal scheduler, never an arbitrary API caller.
    RUN_SCHEDULER = "run_scheduler"


#: The real permission table. A role not listed here (or a permission
#: not in its set) is denied -- `authorize()` never falls back to
#: "allow by default."
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(),
    Role.REQUESTER: frozenset(),
    Role.DATA_STEWARD: frozenset({Permission.ROLLBACK_DATASET_VERSION}),
    Role.COMPLIANCE_APPROVER: frozenset(
        {
            Permission.REVOKE_DATASET_VERSION,
            Permission.APPROVE_POLICY_VERSION,
            Permission.REJECT_POLICY_VERSION,
        }
    ),
    Role.PLATFORM_ADMIN: frozenset(
        {
            Permission.REVOKE_DATASET_VERSION,
            Permission.ROLLBACK_DATASET_VERSION,
            Permission.APPROVE_POLICY_VERSION,
            Permission.REJECT_POLICY_VERSION,
            Permission.RUN_SCHEDULER,
        }
    ),
}


class AuthorizationError(PermissionError):
    """Raised by `authorize()` when `role` does not hold `permission`.
    Callers at the API layer translate this to HTTP 403 -- never to a
    generic 500, since an authorization failure is an expected,
    recoverable condition, the same convention every other domain
    exception in this service follows (see
    `control_plane.domain.lifecycle.errors`'s module docstring)."""

    def __init__(self, role: Role, permission: Permission) -> None:
        self.role = role
        self.permission = permission
        super().__init__(
            f"Role {role.value!r} is not permitted to perform "
            f"{permission.value!r}. Allowed roles for this action: "
            f"{sorted(r.value for r, perms in ROLE_PERMISSIONS.items() if permission in perms)}."
        )


def authorize(role: Role, permission: Permission) -> None:
    """Raise `AuthorizationError` unless `role` holds `permission`.
    Returns `None` (no value) on success -- callers proceed with the
    action; there is no "maybe" outcome."""

    if permission not in ROLE_PERMISSIONS.get(role, frozenset()):
        raise AuthorizationError(role, permission)


__all__ = ["AuthorizationError", "Permission", "ROLE_PERMISSIONS", "Role", "authorize"]
