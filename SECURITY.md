# Security Policy

This repository is a **portfolio / teaching project**. It contains no
production systems, no real customer or patient data, and no real
credentials. That said, it is designed and documented to the standard a real
regulated-industry platform would require, because the point is to teach
that standard.

## Data handling rules (non-negotiable)

1. **No real PHI/PII, ever.** Every dataset, fixture, screenshot, log sample,
   or example in this repository must be synthetic. If you are ever unsure
   whether a piece of data is real, do not commit it — ask first.
2. **No real secrets, ever.** No API keys, passwords, connection strings,
   tokens, or certificates — not even "throwaway" ones, and not even in
   history that gets rewritten later. Use `*.env.example` files with
   placeholder values (e.g. `DATABASE_URL=postgresql://tdm:tdm@localhost:5432/tdm_metadata`
   using an obviously local/dev value) and read real values from environment
   variables or a secrets provider at runtime.
3. **No real company/employer/client names.** Do not reference any real
   organization anywhere in code, docs, commit messages, or fixtures.
4. Secrets are always resolved through the secrets-provider adapter
   (`services/governance-service`), never hardcoded or read ad hoc from
   config files, so the same code path works locally (env vars) and in the
   cloud (a real secret manager).

## Reporting a security issue

Because this is a personal/portfolio project rather than a production
service with a user base, there is no formal bug bounty. If you find a
security issue in the design or code (for example, a masking approach that
is not actually irreversible, or a place where the architecture would leak
sensitive data in a real deployment), please open an issue describing:

- The affected component/file
- The nature of the weakness
- The realistic impact if this pattern were used in a production deployment
- A suggested fix, if you have one

## Security principles this platform is designed to demonstrate

- **Least privilege** — RBAC roles are scoped to the minimum action needed
  (e.g., "request a subset of classification tier X" is a distinct
  permission from "approve a masking policy change"). As of Phase 18A,
  the role an authorization decision is made against is derived from a
  real, verified bearer token (`POST /api/v1/auth/login`,
  `control_plane.platform.auth`), not a caller-supplied field — see
  `THREAT_MODEL.md` section 3 (Control plane) and
  [ADR-0018](docs/adr/0018-minimal-jwt-identity-layer-for-rbac.md) for
  exactly what this does and does not cover (a deliberately minimal
  mechanism for a small set of seeded demo identities, not a production
  identity provider).
- **Defense in depth** — classification, masking, and certification are
  three independent checks; a failure in one does not silently bypass the
  others.
- **Immutable audit evidence** — security-relevant events (who requested
  what, what was approved, what was published) are append-only and are
  never editable through the application layer.
- **Encryption assumptions are documented, not implied.** Where this
  platform assumes data is encrypted at rest (object storage, database) or
  in transit (TLS between services), that assumption is written down
  explicitly in `THREAT_MODEL.md` and the relevant ADR, including what is
  *not* covered by this repository (e.g., we do not implement a KMS; we
  document the interface a real one would plug into).
- **Deterministic, non-reversible masking** — masked values are derived via
  one-way, keyed transformations; the mapping back to a real value exists
  only inside the governed token vault, not in the masked dataset itself.
- **Certified before published** — no masked/synthetic dataset is available
  to consumers until it has passed automated certification checks, and that
  certification is itself an auditable artifact.

## Scope

This policy covers the code, configuration, and documentation in this
repository. It does not cover any real infrastructure, because none is
deployed from this repository as delivered — the Terraform/Helm/Compose
assets here are teaching examples for a reader to adapt, not a live
environment.
