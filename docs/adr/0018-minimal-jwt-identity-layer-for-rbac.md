# ADR-0018: A real, deliberately minimal JWT identity layer backs RBAC, instead of a production identity provider

## Status

Accepted

## Context

`docs/problems/problems_final_review.md` P0-1 (Phase 17's principal-engineer
production-readiness review) found the single most consequential gap in
the whole platform: `control_plane.platform.rbac.authorize()` was real,
enforced code, but every one of its four call sites (dataset-version
revoke, environment rollback, policy-version approve/reject) trusted a
plain `actor_role` string the *caller* supplied in the request body.
Nothing verified that claim. A caller who wanted to revoke any dataset
version simply sent `{"actor_role": "PLATFORM_ADMIN", ...}` and
succeeded regardless of who they actually were. `THREAT_MODEL.md`'s own
spoofing mitigation ("no plane trusts a caller's claim about identity
without verifying it through the security/governance plane") was the
literal opposite of the real code.

`ARCHITECTURE.md` section 2.4 has always named `services/governance-service`
as the eventual home for a real identity provider, and every phase since
Phase 10 has correctly deferred building one out rather than faking it
(ADR-0014, ADR-0015, ADR-0016 all make the same "not yet, and don't fake
it" call for adjacent capabilities). This phase (18A) had to decide: fix
P0-1 for real, without either (a) building a disproportionate production
identity provider (a real IdP would need a user database, password
hashing/rotation, MFA, OAuth/OIDC federation with a real provider, session
revocation — none of which is proportionate to a synthetic-data,
never-deployed portfolio repository), or (b) papering over the gap with
another unverified field.

## Decision

Add `control_plane.platform.auth`, a real, working, testable JWT
issuance/verification layer, deliberately sized to close exactly this
gap and no more:

- `POST /api/v1/auth/login` authenticates against a small, fixed,
  SYNTHETIC set of demo identities (`SEEDED_DEMO_USERS`, one per
  `control_plane.platform.rbac.Role`) and issues a signed, short-lived
  (30 minute) JWT naming the verified role.
- `get_current_actor` (a FastAPI dependency built on `fastapi.security.HTTPBearer`)
  verifies that JWT's signature and expiry and returns an
  `AuthenticatedActor(username, role)`. Every RBAC call site
  (`revoke_dataset_version`, `rollback_environment_request`,
  `approve_policy_version`, `reject_policy_version`, and the newly-gated
  `run_due_refreshes` — see P1-2) now derives `actor.role` from this
  dependency instead of trusting a request-body field.
- The signing key follows this repository's existing
  `TDM_MASKING_HMAC_KEY`/`TDM_CERTIFICATION_HMAC_KEY` convention exactly:
  an environment variable (`TDM_CONTROL_PLANE_JWT_SIGNING_KEY`), a
  gitignored `.env` fallback, and a `--generate-dev-key` CLI helper — no
  hardcoded or committed key.
- The seeded demo users' passwords are deliberately plaintext and
  publicly documented in `control_plane.platform.auth`'s own module
  docstring, the same way `docker-compose.yml`'s Postgres/MinIO dev
  credentials already are elsewhere in this repository — hashing a
  password that is committed in source alongside the comparison code
  adds no real confidentiality, so this module says so honestly instead
  of pretending otherwise.

Every other actor-attribution field in this service (`revoked_by`,
`performed_by`, `requested_by`, `generated_by`, `accessed_by`) is
*unchanged* by this decision — it remains exactly what
`docs/problems/problems_phase_11.md` P11-4 already, honestly, called it: advisory
metadata, not a security control. Only `actor_role` — the one field an
authorization *decision* is made from — needed to move behind real
verification.

## Consequences

- `authorize()` itself did not change at all — it never trusted
  anything. Only *where its `role` argument comes from* changed, which
  is why the diff to `control_plane.platform.rbac` is a docstring update
  plus one new `Permission` (`RUN_SCHEDULER`, for P1-2), not a rewrite.
- Every pre-existing test/demo script that called an RBAC-gated endpoint
  with `{"actor_role": "..."}` in its body now calls
  `POST /api/v1/auth/login` first and sends `Authorization: Bearer
  <token>` instead — a real, if broad, test-suite change (see
  `services/control-plane/tests/conftest.py`'s `auth_header` helper).
- This is explicitly **not** a production identity provider. It has no
  user database, no self-service provisioning, no password reset flow,
  no MFA, no OAuth/OIDC federation, no session revocation list. A real
  deployment of this platform would replace this whole module with
  `services/governance-service`'s real identity provider — this
  decision does not claim otherwise, and `control_plane.platform.auth`'s
  own module docstring says so explicitly, so a future reader does not
  mistake this for more than it is.
- `THREAT_MODEL.md` and `SECURITY.md` are updated (Phase 18A) to
  describe this real mechanism accurately, replacing the false
  "token-based auth... on every request" claim P1-1 found.
