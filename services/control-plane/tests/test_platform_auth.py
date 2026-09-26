"""Unit + real-HTTP tests for `control_plane.platform.auth` and
`api/v1/auth.py` -- proving Phase 18A's fix for `problems_final_review.md`
P0-1 is real: a caller can no longer claim an arbitrary `actor_role`
via a request-body field, and every RBAC-gated endpoint now requires a
verified bearer token.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app
from control_plane.platform.auth import (
    SEEDED_DEMO_USERS,
    AuthenticatedActor,
    InvalidCredentialsError,
    InvalidTokenError,
    MissingSigningKeyError,
    authenticate_demo_user,
    create_access_token,
    decode_access_token,
    demo_credentials_for_role,
    generate_dev_key,
    resolve_signing_key,
)
from control_plane.platform.rbac import Role

from conftest import auth_header


def _client(db_path: Path) -> TestClient:
    engine = create_sqlite_engine(str(db_path))
    factory = build_session_factory(engine)

    def _override() -> Iterator[Session]:
        with session_scope(factory) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return _client(tmp_path / "auth.db")


# ---------------------------------------------------------------------------
# Unit tests: authenticate_demo_user / create_access_token / decode_access_token
# ---------------------------------------------------------------------------


def test_every_role_has_exactly_one_seeded_demo_user() -> None:
    seeded_roles = {role for _password, role in SEEDED_DEMO_USERS.values()}
    assert seeded_roles == set(Role)


def test_authenticate_demo_user_succeeds_for_a_real_seeded_credential() -> None:
    username, password = demo_credentials_for_role(Role.COMPLIANCE_APPROVER)
    assert authenticate_demo_user(username, password) is Role.COMPLIANCE_APPROVER


def test_authenticate_demo_user_rejects_a_wrong_password() -> None:
    username, _ = demo_credentials_for_role(Role.PLATFORM_ADMIN)
    with pytest.raises(InvalidCredentialsError):
        authenticate_demo_user(username, "definitely-not-the-password")


def test_authenticate_demo_user_rejects_an_unknown_username() -> None:
    with pytest.raises(InvalidCredentialsError):
        authenticate_demo_user("nobody@example.org", "anything")


def test_create_and_decode_access_token_round_trips() -> None:
    key = generate_dev_key().encode("utf-8")
    token, expires_at = create_access_token("demo.platform_admin", Role.PLATFORM_ADMIN, key)
    actor = decode_access_token(token, key)
    assert actor == AuthenticatedActor(username="demo.platform_admin", role=Role.PLATFORM_ADMIN)
    assert expires_at is not None


def test_decode_access_token_rejects_a_token_signed_with_a_different_key() -> None:
    key_a = generate_dev_key().encode("utf-8")
    key_b = generate_dev_key().encode("utf-8")
    token, _ = create_access_token("demo.viewer", Role.VIEWER, key_a)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, key_b)


def test_decode_access_token_rejects_an_expired_token() -> None:
    """A forged-old-timestamp token proves expiry is actually enforced,
    not merely present as an unchecked claim."""

    import datetime

    key = generate_dev_key().encode("utf-8")
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    payload = {"sub": "demo.viewer", "role": Role.VIEWER.value, "iat": past, "exp": past}
    expired_token = pyjwt.encode(payload, key, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(expired_token, key)


def test_decode_access_token_rejects_an_unrecognized_role_claim() -> None:
    key = generate_dev_key().encode("utf-8")
    payload = {"sub": "demo.viewer", "role": "super_root", "iat": 0, "exp": 9_999_999_999}
    token = pyjwt.encode(payload, key, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, key)


def test_resolve_signing_key_raises_when_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TDM_CONTROL_PLANE_JWT_SIGNING_KEY", raising=False)
    with pytest.raises(MissingSigningKeyError):
        resolve_signing_key(search_dirs=[tmp_path])


# ---------------------------------------------------------------------------
# Real HTTP tests: POST /api/v1/auth/login + every RBAC-gated endpoint
# ---------------------------------------------------------------------------


def test_login_with_valid_seeded_credentials_returns_a_usable_token(client: TestClient) -> None:
    username, password = demo_credentials_for_role(Role.DATA_STEWARD)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "data_steward"
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_with_invalid_credentials_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "demo.platform_admin", "password": "wrong"}
    )
    assert response.status_code == 401


def test_login_with_unknown_username_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "not-a-real-user", "password": "whatever"}
    )
    assert response.status_code == 401


def test_a_rejected_bearer_token_never_reaches_rbac(client: TestClient) -> None:
    """A syntactically-present but garbage bearer token is rejected with
    401 (authentication failure), never a 403 (an authorization
    decision, which would imply RBAC ran against a role it should never
    have derived from unverified input)."""

    response = client.post(
        "/api/v1/lifecycle/dataset-versions/00000000-0000-0000-0000-000000000000/revoke",
        json={"reason": "x", "revoked_by": "attacker@example.org"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/lifecycle/dataset-versions/00000000-0000-0000-0000-000000000000/revoke",
        "/api/v1/lifecycle/environment-requests/00000000-0000-0000-0000-000000000000/rollback",
        "/api/v1/lifecycle/scheduler/run-due",
    ],
)
def test_every_lifecycle_rbac_gated_endpoint_rejects_a_missing_token(client: TestClient, path: str) -> None:
    response = client.post(path, json={})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/governance/policy-versions/00000000-0000-0000-0000-000000000000/approve",
        "/api/v1/governance/policy-versions/00000000-0000-0000-0000-000000000000/reject",
    ],
)
def test_every_governance_rbac_gated_endpoint_rejects_a_missing_token(client: TestClient, path: str) -> None:
    response = client.post(path, json={"performed_by": "a"})
    assert response.status_code == 401


def test_a_stolen_but_expired_token_is_rejected_end_to_end(client: TestClient) -> None:
    """Reproduces the exact live-demonstration shape from
    `problems_final_review.md` P0-1 with the fix applied: a caller
    presenting SOME credential-shaped thing still cannot bypass identity
    verification just because it looks like a token."""

    response = client.post(
        "/api/v1/lifecycle/scheduler/run-due",
        headers={"Authorization": "Bearer " + pyjwt.encode(
            {"sub": "attacker", "role": "platform_admin", "exp": 0}, "wrong-key", algorithm="HS256"
        )},
    )
    assert response.status_code == 401


def test_platform_admin_can_call_run_due_via_helper(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lifecycle/scheduler/run-due", headers=auth_header(client, Role.PLATFORM_ADMIN)
    )
    assert response.status_code == 200
