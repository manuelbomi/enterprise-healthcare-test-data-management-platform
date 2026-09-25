# infra/terraform

Example, teaching-oriented infrastructure-as-code for deploying this
platform's cloud dependencies (object storage, managed PostgreSQL,
secrets, IAM) to AWS or Azure. See `ARCHITECTURE.md` section 2.6 and
`docs/adr/0005-object-storage-abstraction.md`.

## Important

These are **examples for a reader to adapt**, not a turnkey production
deployment, and they are never applied against any real account from this
repository. No real account IDs, subscription IDs, resource names, or
state backends are configured here — every placeholder is clearly marked.
Before using any of this against a real cloud account, replace every
placeholder, review the security posture (see `THREAT_MODEL.md`), and get
it reviewed the way any production infrastructure change would be.

## Layout

```
aws/       # Example AWS deployment (S3 bucket for snapshots, RDS Postgres, IAM)
azure/      # Example Azure deployment (Blob/ADLS container, Azure Database for PostgreSQL)
modules/     # Shared reusable modules referenced by both
```

## Phase 0 status

Structural scaffold only — provider/backend blocks and a README per
directory establishing intent. Real resource definitions are added in
Phase 20, once there is a real deployment shape (Kubernetes/Helm) for
them to support.
