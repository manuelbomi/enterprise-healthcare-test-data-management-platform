"""A real, but deliberately minimal, identity-verification mechanism.

**Why this module exists (`problems_final_review.md` P0-1).** Before
Phase 18A, `control_plane.platform.rbac.authorize()` was real, enforced
code, but every one of its four call sites trusted a plain
`actor_role` string the *caller* supplied in the request body -- there
was no authentication anywhere in this repository (no JWT, no OAuth, no
session token, no API key). A caller who wanted to revoke any dataset
version simply sent `{"actor_role": "PLATFORM_ADMIN", ...}` and nothing
checked whether that claim was true. This module closes that gap: a
real login endpoint (`control_plane.api.v1.auth`) issues a signed JWT
naming a verified role, and `get_current_actor` below is now the *only*
place `actor_role` may come from -- every RBAC call site that used to
read `body.actor_role` now reads `AuthenticatedActor.role` instead.

**Scope boundary -- read this before extending.** This is a REAL,
working, testable JWT issuance/verification layer, not a no-op or a
placeholder. It is also DELIBERATELY MINIMAL, and must not be mistaken
for a production identity provider:

- There is no user database, no signup/self-service provisioning API,
  no password reset flow, no MFA, no OAuth/OIDC federation, no session
  revocation list.
- The identities it recognizes are a small, fixed set of SYNTHETIC demo
  users (`SEEDED_DEMO_USERS` below), one per `control_plane.platform.rbac.Role`,
  with a publicly-documented, hardcoded synthetic password each --
  exactly the same "clearly-labeled, non-secret demo credential" pattern
  this repository already uses for `docker-compose.yml`'s Postgres/MinIO
  dev credentials. Hashing these passwords would add no real
  confidentiality (the plaintext is committed in this file already), so
  this module deliberately does not pretend otherwise; it compares them
  with `hmac.compare_digest` only to avoid a cheap timing side channel,
  not to claim any secrecy the passwords don't have.
- A real deployment of this platform would replace this whole module
  with `services/governance-service`'s real identity provider
  (`ARCHITECTURE.md` section 2.4) -- every phase since Phase 10 has
  correctly deferred that build-out rather than faking it, and this
  module does not change that; it exists only to give the RBAC layer a
  REAL (if minimal) verified identity to authorize against, sized for a
  portfolio/teaching repository, not a production system.

Every other actor-attribution field in this service (`revoked_by`,
`performed_by`, `requested_by`, `generated_by`, `accessed_by`) remains
exactly what `control_plane.platform.rbac`'s docstring already, honestly,
called it: advisory metadata, not a security control. Only `actor_role`
-- the one field an authorization *decision* is made from -- is now
backed by a verified identity.
"""

from __future__ import annotations

import hmac
import secrets as _stdlib_secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as _pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from control_plane.platform.rbac import Role

#: Mirrors `data_plane.certification.signing.ENV_VAR`'s resolution
#: convention exactly (environment variable, then a gitignored `.env`
#: fallback, then a `--generate-dev-key` CLI helper) -- see this
#: module's `__main__` block and `services/control-plane/.env.example`.
ENV_VAR = "TDM_CONTROL_PLANE_JWT_SIGNING_KEY"

#: Mirrors `data_plane.masking.secrets.MIN_KEY_BYTES`/
#: `data_plane.certification.signing.MIN_KEY_BYTES`.
MIN_KEY_BYTES = 16

_ALGORITHM = "HS256"
_DEFAULT_TOKEN_LIFETIME = timedelta(minutes=30)


class MissingSigningKeyError(RuntimeError):
    """Raised when no JWT signing key can be resolved."""


class WeakSigningKeyError(RuntimeError):
    """Raised when a resolved key is implausibly short to be a real secret."""


class InvalidCredentialsError(RuntimeError):
    """Raised by `authenticate_demo_user` for an unknown username or a
    password that does not match."""


class InvalidTokenError(RuntimeError):
    """Raised by `decode_access_token` for a missing, expired,
    signature-invalid, or malformed-claims access token."""


@dataclass(frozen=True)
class AuthenticatedActor:
    """The verified result of decoding a real, signed access token --
    the only shape `control_plane.platform.rbac.authorize()` should ever
    be called with an `actor_role` derived from, post-Phase-18A."""

    username: str
    role: Role


#: The fixed, small set of SYNTHETIC demo identities this module
#: recognizes -- one per `Role`, so every RBAC permission in
#: `control_plane.platform.rbac.ROLE_PERMISSIONS` has at least one demo
#: identity that can actually obtain a token naming it. See this
#: module's docstring for why these passwords are deliberately
#: plaintext, public, and committed.
SEEDED_DEMO_USERS: dict[str, tuple[str, Role]] = {
    "demo.viewer": ("viewer-demo-pw-syn-1", Role.VIEWER),
    "demo.requester": ("requester-demo-pw-syn-2", Role.REQUESTER),
    "demo.data_steward": ("data-steward-demo-pw-syn-3", Role.DATA_STEWARD),
    "demo.compliance_approver": ("compliance-approver-demo-pw-syn-4", Role.COMPLIANCE_APPROVER),
    "demo.platform_admin": ("platform-admin-demo-pw-syn-5", Role.PLATFORM_ADMIN),
}


def demo_credentials_for_role(role: Role) -> tuple[str, str]:
    """`(username, password)` for the seeded demo identity holding
    `role` -- used by tests and `scripts/demo_*` so there is exactly one
    place these pairings are defined."""

    for username, (password, seeded_role) in SEEDED_DEMO_USERS.items():
        if seeded_role is role:
            return username, password
    raise KeyError(f"No seeded demo user is assigned role {role!r}.")  # pragma: no cover - defensive


def authenticate_demo_user(username: str, password: str) -> Role:
    """Verify `username`/`password` against `SEEDED_DEMO_USERS`, returning
    the role it holds. Raises `InvalidCredentialsError` (never leaks
    whether the *username* or the *password* was wrong -- a real login
    endpoint should not narrow that down for an attacker) otherwise."""

    record = SEEDED_DEMO_USERS.get(username)
    if record is None or not hmac.compare_digest(record[0], password):
        raise InvalidCredentialsError("Invalid username or password.")
    return record[1]


def generate_dev_key() -> str:
    """A throwaway, cryptographically random hex key for local
    development/testing only -- mirrors
    `data_plane.masking.secrets.generate_dev_key`/
    `data_plane.certification.signing.generate_dev_key` exactly,
    including its "never persisted by this function" guarantee."""

    return _stdlib_secrets.token_hex(32)  # 256 bits


def _read_dotenv_value(path: Path, var: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == var:
            return value.strip().strip('"').strip("'")
    return None


def _default_search_dirs() -> Iterable[Path]:
    here = Path(__file__).resolve()
    # services/control-plane/src/control_plane/platform/auth.py -> services/control-plane
    service_root = here.parents[3]
    repo_root = here.parents[5] if len(here.parents) > 5 else service_root
    seen: set[Path] = set()
    for candidate in (Path.cwd(), service_root, repo_root):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def resolve_signing_key(*, search_dirs: Iterable[Path] | None = None) -> bytes:
    """Resolve the JWT signing key as raw bytes.

    Resolution order mirrors `data_plane.certification.signing.resolve_signing_key`
    exactly (environment variable, then a gitignored `.env` file). An
    independent secret from the masking/certification keys -- a leaked
    JWT signing key lets an attacker mint tokens for any role, a
    different (and larger) blast radius than either of those, so it
    must be independently rotatable.
    """

    import os

    value = os.environ.get(ENV_VAR)
    source = "environment variable"
    if not value:
        for directory in search_dirs if search_dirs is not None else _default_search_dirs():
            value = _read_dotenv_value(directory / ".env", ENV_VAR)
            if value:
                source = f"{directory / '.env'}"
                break

    if not value:
        raise MissingSigningKeyError(
            f"{ENV_VAR} is not set. The control plane refuses to issue or verify a JWT without an "
            "explicit signing key (an unsigned/unkeyed token offers no identity verification at "
            "all -- see control_plane.platform.auth's module docstring).\n"
            "To fix this for local development:\n"
            "  1. Generate a throwaway dev key:\n"
            "       python -m control_plane.platform.auth --generate-dev-key\n"
            "  2. Export it for this shell session only, e.g.:\n"
            f"       export {ENV_VAR}=<the printed value>\n"
            "     ...or copy services/control-plane/.env.example to "
            "services/control-plane/.env (gitignored) and paste it in.\n"
            "Never hardcode a key in source, and never commit a .env file -- see SECURITY.md."
        )

    encoded = value.encode("utf-8")
    if len(encoded) < MIN_KEY_BYTES:
        raise WeakSigningKeyError(
            f"{ENV_VAR} resolved from {source} is only {len(encoded)} bytes long; a real key "
            f"should be at least {MIN_KEY_BYTES} bytes. Generate a proper key with "
            "'python -m control_plane.platform.auth --generate-dev-key'."
        )
    return encoded


def create_access_token(
    username: str, role: Role, key: bytes, *, lifetime: timedelta = _DEFAULT_TOKEN_LIFETIME
) -> tuple[str, datetime]:
    """Issue a signed JWT naming `username`/`role`, returning
    `(token, expires_at)`. Called only by `control_plane.api.v1.auth.login`
    after `authenticate_demo_user` has already verified the caller's
    credentials -- this function itself does not check anything, it only
    encodes already-verified claims."""

    now = datetime.now(timezone.utc)
    expires_at = now + lifetime
    payload = {"sub": username, "role": role.value, "iat": now, "exp": expires_at}
    token = _pyjwt.encode(payload, key, algorithm=_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str, key: bytes) -> AuthenticatedActor:
    """Verify `token`'s signature and expiry under `key`, returning the
    `AuthenticatedActor` its claims name. Raises `InvalidTokenError` for
    any failure (expired, bad signature, malformed/missing claims,
    unrecognized role) -- never returns a partially-trusted result."""

    try:
        payload = _pyjwt.decode(token, key, algorithms=[_ALGORITHM])
    except _pyjwt.PyJWTError as exc:
        raise InvalidTokenError(f"Invalid or expired access token: {exc}") from exc

    username = payload.get("sub")
    role_value = payload.get("role")
    if not username or role_value is None:
        raise InvalidTokenError("Access token is missing required claims ('sub'/'role').")
    try:
        role = Role(role_value)
    except ValueError as exc:
        raise InvalidTokenError(f"Access token names an unrecognized role {role_value!r}.") from exc
    return AuthenticatedActor(username=username, role=role)


#: `auto_error=False` so a missing token produces this module's own,
#: more specific 401 message (pointing at `POST /api/v1/auth/login`)
#: rather than FastAPI's generic "Not authenticated".
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedActor:
    """FastAPI dependency: verify the request's `Authorization: Bearer
    <token>` header and return the identity/role it names.

    This is now the ONLY place in this service `actor_role` may be
    trusted from -- see the module docstring. Every route that used to
    take `authorize(body.actor_role, ...)` (a caller-supplied,
    unverified field) now takes `actor: AuthenticatedActor =
    Depends(get_current_actor)` and calls `authorize(actor.role, ...)`
    instead. Raises HTTP 401 for a missing/invalid/expired token, and
    HTTP 500 (a server misconfiguration, not a caller error) if this
    process has no usable signing key at all.
    """

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token. Call POST /api/v1/auth/login to obtain one.",
        )
    try:
        key = resolve_signing_key()
    except (MissingSigningKeyError, WeakSigningKeyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        return decode_access_token(credentials.credentials, key)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


__all__ = [
    "ENV_VAR",
    "MIN_KEY_BYTES",
    "AuthenticatedActor",
    "InvalidCredentialsError",
    "InvalidTokenError",
    "MissingSigningKeyError",
    "SEEDED_DEMO_USERS",
    "WeakSigningKeyError",
    "authenticate_demo_user",
    "create_access_token",
    "decode_access_token",
    "demo_credentials_for_role",
    "generate_dev_key",
    "get_current_actor",
    "resolve_signing_key",
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="control-plane JWT signing key utility (see this module's docstring)."
    )
    parser.add_argument(
        "--generate-dev-key",
        action="store_true",
        help="Print a fresh, throwaway local-dev/test-only signing key and exit.",
    )
    args = parser.parse_args()
    if args.generate_dev_key:
        print(generate_dev_key())
    else:
        parser.print_help()
