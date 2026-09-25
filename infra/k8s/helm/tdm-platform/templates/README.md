# templates

Kubernetes manifest templates (Deployments, Services, ConfigMaps, etc.) for
each of the platform's deployable services. Empty as of Phase 0 — this
chart currently only fixes `Chart.yaml` and `values.yaml`'s shape. Real
templates are added in Phase 20, once each service has a working container
image to deploy (control-plane in Phase 2, governance-service in Phase 3,
frontend in Phase 16).
