"""A real, enforced role-based authorization check.

`ARCHITECTURE.md` section 2.4 names RBAC as a `services/governance-service`
responsibility; `problems_phase_07.md` P7-6 and `problems_phase_10.md`
P10-2 both explicitly deferred it ("no RBAC anywhere in this service
yet"). This module is Phase 11's answer -- not a full identity/auth
system (out of scope, per the phase brief), but a real permission-table
lookup that actually rejects an insufficiently-privileged actor,
enforced at the API layer for the platform's highest-sensitivity
mutations: revoking a dataset version, rolling an environment back, and
approving/rejecting a governed masking policy version.

What makes this "real" rather than a no-op:

- `ROLE_PERMISSIONS` is a real, closed table -- most roles are granted
  *no* permissions here at all (`VIEWER`, `REQUESTER`).
- `authorize()` raises `AuthorizationError` (never silently allows) for
  any `(role, permission)` pair not explicitly listed.
- `services/control-plane/tests/test_platform_rbac.py` proves this
  with unit tests, and `test_failure_injection.py` proves it end to
  end over real HTTP requests (a `REQUESTER`-role actor attempting to
  revoke a dataset version gets HTTP 403, not 200).

What this deliberately does not do (see `problems_phase_11.md` P11-4):
verify that the caller-supplied `actor_role` actually belongs to the
caller-supplied `revoked_by`/`performed_by` identity string -- there is
still no identity provider anywhere in this repository. This module
answers "if you claim this role, are you allowed to do this," not "are
you who you claim to be." A real deployment would resolve `actor_role`
from a verified identity/session, not accept it as a request field.
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
