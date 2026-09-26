"""Login endpoint (Phase 18A, resolves `docs/problems/problems_final_review.md` P0-1).

One route: exchange a seeded demo identity's username/password for a
signed JWT naming its role. See `control_plane.platform.auth`'s module
docstring for this mechanism's deliberate scope boundary (a real, but
minimal, identity-verification layer -- not a production identity
provider).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.platform.auth import (
    InvalidCredentialsError,
    MissingSigningKeyError,
    WeakSigningKeyError,
    authenticate_demo_user,
    create_access_token,
    resolve_signing_key,
)
from control_plane.platform.rbac import Role

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    expires_at: datetime


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    """Authenticate against `control_plane.platform.auth.SEEDED_DEMO_USERS`
    and, on success, issue a signed access token naming the verified
    role. Every RBAC-gated endpoint in this service (dataset-version
    revoke, environment rollback, policy-version approve/reject,
    scheduler run-due) now requires the `Authorization: Bearer <token>`
    header this endpoint returns -- see `control_plane.platform.auth`'s
    module docstring for why this replaces the pre-Phase-18A
    caller-supplied `actor_role` request field."""

    try:
        role = authenticate_demo_user(body.username, body.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        key = resolve_signing_key()
    except (MissingSigningKeyError, WeakSigningKeyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    token, expires_at = create_access_token(body.username, role, key)
    return LoginResponse(access_token=token, role=role, expires_at=expires_at)


__all__ = ["router"]
