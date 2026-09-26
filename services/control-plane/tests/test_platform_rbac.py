"""Unit tests for `control_plane.platform.rbac` -- proving `authorize()`
is a real, enforced check, not a no-op that always allows (the
anti-pattern `problems_phase_11.md` explicitly calls out avoiding).
"""

from __future__ import annotations

import pytest

from control_plane.platform.rbac import ROLE_PERMISSIONS, AuthorizationError, Permission, Role, authorize


@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (Role.COMPLIANCE_APPROVER, Permission.REVOKE_DATASET_VERSION),
        (Role.COMPLIANCE_APPROVER, Permission.APPROVE_POLICY_VERSION),
        (Role.COMPLIANCE_APPROVER, Permission.REJECT_POLICY_VERSION),
        (Role.DATA_STEWARD, Permission.ROLLBACK_DATASET_VERSION),
        (Role.PLATFORM_ADMIN, Permission.REVOKE_DATASET_VERSION),
        (Role.PLATFORM_ADMIN, Permission.ROLLBACK_DATASET_VERSION),
        (Role.PLATFORM_ADMIN, Permission.APPROVE_POLICY_VERSION),
        (Role.PLATFORM_ADMIN, Permission.REJECT_POLICY_VERSION),
        (Role.PLATFORM_ADMIN, Permission.RUN_SCHEDULER),
    ],
)
def test_authorize_allows_a_permitted_role(role: Role, permission: Permission) -> None:
    authorize(role, permission)  # must not raise


@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (Role.VIEWER, Permission.REVOKE_DATASET_VERSION),
        (Role.VIEWER, Permission.APPROVE_POLICY_VERSION),
        (Role.REQUESTER, Permission.REVOKE_DATASET_VERSION),
        (Role.REQUESTER, Permission.ROLLBACK_DATASET_VERSION),
        (Role.REQUESTER, Permission.APPROVE_POLICY_VERSION),
        (Role.DATA_STEWARD, Permission.REVOKE_DATASET_VERSION),
        (Role.DATA_STEWARD, Permission.APPROVE_POLICY_VERSION),
        (Role.DATA_STEWARD, Permission.REJECT_POLICY_VERSION),
        (Role.COMPLIANCE_APPROVER, Permission.ROLLBACK_DATASET_VERSION),
        (Role.VIEWER, Permission.RUN_SCHEDULER),
        (Role.REQUESTER, Permission.RUN_SCHEDULER),
        (Role.DATA_STEWARD, Permission.RUN_SCHEDULER),
        (Role.COMPLIANCE_APPROVER, Permission.RUN_SCHEDULER),
    ],
)
def test_authorize_rejects_an_insufficiently_privileged_role(role: Role, permission: Permission) -> None:
    with pytest.raises(AuthorizationError) as exc_info:
        authorize(role, permission)
    assert role.value in str(exc_info.value)
    assert permission.value in str(exc_info.value)


def test_no_role_is_granted_every_permission_except_platform_admin() -> None:
    # A real, closed permission table: only the explicit "break-glass"
    # role holds everything. Any other role holding every permission
    # would be a sign the table degenerated into a no-op allow-all.
    all_permissions = frozenset(Permission)
    for role, permissions in ROLE_PERMISSIONS.items():
        if role is Role.PLATFORM_ADMIN:
            assert permissions == all_permissions
        else:
            assert permissions != all_permissions


def test_viewer_and_requester_hold_no_sensitive_permissions_at_all() -> None:
    assert ROLE_PERMISSIONS[Role.VIEWER] == frozenset()
    assert ROLE_PERMISSIONS[Role.REQUESTER] == frozenset()


def test_authorization_error_is_a_permission_error_subclass() -> None:
    # Callers that only know to catch PermissionError (a stdlib
    # convention) should still catch this.
    assert issubclass(AuthorizationError, PermissionError)
