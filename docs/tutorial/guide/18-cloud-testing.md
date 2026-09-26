# Chapter 18 — Cloud testing

## The concept

"Cloud testing," in the context this platform builds for, means two
related things: proving that the infrastructure-as-code that would
deploy this platform to a real cloud is *itself* correct (before ever
running it against a real account), and proving that the platform's
architecture is *portable* across clouds rather than accidentally
locked to one vendor's specific APIs. Both matter for a regulated
enterprise: a bad Terraform plan applied against a live account is an
expensive, sometimes destructive mistake, and a platform locked to one
cloud vendor can't follow an organization that changes providers or runs
multi-cloud.

## What this repository actually validated, and what it deliberately never did

This repository is explicit that **no infrastructure command in this
repository has ever been run against a real cloud account** — read that
sentence again, because it's the most important thing to understand
before reading `infra/`. What *was* run, for real, in a local Docker
environment:

- `helm lint infra/k8s/helm/tdm-platform` — 0 charts failed.
- `helm template`, rendered twice — once with default values, once with
  `controlPlane.dbSecret.create=true` and `ingress.enabled=true` set —
  confirming the conditional `Secret`/`Ingress` manifests actually
  render with the expected fields, not just that the chart parses.
- `terraform fmt -check`/`fmt` and `terraform validate` (after
  `terraform init -backend=false`) for both
  `infra/terraform/azure/main.tf` and `infra/terraform/aws/main.tf` —
  `fmt` caught real alignment issues on the first pass, fixed by
  `terraform fmt` itself.
- **No `terraform plan`/`apply` was ever run.** No Azure or AWS
  credential exists anywhere in this repository or its CI workflows.

This is the honest boundary of "cloud testing" as this platform
currently practices it: real, local validation that the infrastructure
definitions are syntactically and structurally correct, not a real
deployment. `docs/AZURE_PRODUCTION_DEPLOYMENT.md`'s own opening
paragraph states this explicitly.

## What stays cloud-portable, and why — proven against a second cloud's Terraform

This repository didn't just assert portability; it proved it by writing
a real, validated Terraform configuration for a *second* cloud
(`infra/terraform/aws/main.tf`) alongside the original
(`infra/terraform/azure/main.tf`), and documenting, resource by
resource, which pieces are genuinely cloud-specific versus which pieces
this platform's own earlier architectural decisions already made
portable:

| Stays portable | Because of |
|---|---|
| Plane separation (control-plane / data-plane / governance-service as independent processes) | [ADR-0003](../../adr/0003-plane-separation.md) — nothing about how they talk to each other changes based on cloud |
| PostgreSQL as the metadata-plane engine | [ADR-0004](../../adr/0004-postgresql-metadata-store.md) — pure SQLAlchemy against a standard wire protocol; only the connection URL changes |
| Kubernetes/Helm as the deployment abstraction | `infra/k8s/helm/tdm-platform` has no cloud-provider-specific API objects — it runs unmodified against AKS, EKS, GKE, or a local `kind`/`minikube` cluster |
| Docker Compose as the integration-environment baseline | The same `infra/docker/docker-compose.yml` Chapter 17's CI uses locally is what the deploy-* workflows use as their documented stand-in for a real deployment target |

| Genuinely cloud-specific | Example |
|---|---|
| `infra/terraform/azure/main.tf`'s resource blocks | `azurerm_kubernetes_cluster`, `azurerm_postgresql_flexible_server`, `azurerm_storage_account`, `azurerm_key_vault` — Azure's own resource model and RBAC |
| Managed Postgres offering | Connection string shape, firewall rules, SKU tiers differ from AWS RDS — the *database itself* (schema, SQLAlchemy models) is 100% portable |
| Secrets provider backing store | Azure Key Vault vs. AWS Secrets Manager — the application-level secrets-provider adapter interface (`SECURITY.md`) is what stays constant |

## The one honestly-flagged remaining gap

The storage-adapter interface
([ADR-0005](../../adr/0005-object-storage-abstraction.md)) is meant to
make MinIO (local), AWS S3, and Azure Blob/ADLS interchangeable behind
one interface. As of this repository's current state, **this interface
is still a design contract, not implemented code** (tracked as `P0-3` in
`docs/problems/problems_master.md`, still open) — every data-plane job reads/writes a
local filesystem path directly. `infra/terraform/azure/main.tf`'s
storage resources provision the *target* this adapter will eventually
write to; nothing in this repository makes the data plane actually use
it yet. This is `docs/AZURE_PRODUCTION_DEPLOYMENT.md`'s own honestly
named largest portability gap, not something it claims to have closed.

## Where to go next

Continue to [Chapter 19 — Audit evidence](19-audit-evidence.md), or read
`docs/AZURE_PRODUCTION_DEPLOYMENT.md` in full for the complete
deployment-shape diagram and every real artifact behind it.
