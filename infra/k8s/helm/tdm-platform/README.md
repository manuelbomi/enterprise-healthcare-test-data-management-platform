# tdm-platform Helm chart

Kubernetes deployment shape for the enterprise healthcare test data
management platform. See `ARCHITECTURE.md` section 2.6 and
`docs/AZURE_PRODUCTION_DEPLOYMENT.md`.

## Phase 12 status

Real templates (`templates/`): Deployment + Service for
`control-plane`, `governance-service`, and `frontend` (the three
services with a real `Dockerfile` as of this phase — see
`services/control-plane/Dockerfile`,
`services/governance-service/Dockerfile`, `frontend/Dockerfile`), a
ConfigMap + Secret-template split for the control plane's
configuration, and a disabled-by-default Ingress. `data-plane` has no
template here — see `docs/problems/problems_phase_12.md` for the decision record.

Postgres itself is **not** templated as an in-cluster StatefulSet —
`values.yaml`'s `postgresql.externalHost` documents the intended real
shape (a managed database, e.g. Azure Database for PostgreSQL Flexible
Server via `infra/terraform/azure`), consistent with `ARCHITECTURE.md`
section 2.6's "cloud storage adapters" pattern: application code is
identical regardless of where Postgres actually runs.

## Usage

```bash
helm lint infra/k8s/helm/tdm-platform
helm template demo infra/k8s/helm/tdm-platform
# Against a real cluster:
helm install tdm infra/k8s/helm/tdm-platform \
  --set controlPlane.image.repository=<your-registry>/tdm-control-plane \
  --set governanceService.image.repository=<your-registry>/tdm-governance-service \
  --set frontend.image.repository=<your-registry>/tdm-console
```

No real cluster is targeted from this repository — see
`infra/terraform/README.md`'s identical rule for Terraform.
