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

## Phase 12 status

`azure/main.tf` now has real, structurally valid resource definitions
(AKS, Azure Database for PostgreSQL Flexible Server, an ADLS Gen2-
enabled Storage Account, Azure Container Registry, Key Vault, and the
least-privilege role assignments between them) — `terraform fmt -check`
and `terraform validate` (against a local, `-backend=false` init) both
pass; see `problems_phase_12.md` for the exact commands run and their
output. `terraform plan`/`apply` were never run against a real Azure
subscription — there is no `azurerm` credential anywhere in this
repository or its CI. See `docs/AZURE_PRODUCTION_DEPLOYMENT.md` for the
full narrative this file implements, including exactly what is
Azure-specific here versus what the storage-adapter/plane-separation
architecture (ADR-0003, ADR-0005) keeps portable to `aws/` (kept as a
lighter, structural-placeholder example — the AWS equivalents of each
Azure resource above are named in `aws/main.tf`'s own comments) or to
any other cloud.
