# infra/docker

Local development / CI integration infrastructure via Docker Compose:
PostgreSQL (metadata plane), MinIO (local S3-compatible object storage),
and, as of Phase 12, the real `control-plane`, `governance-service`, and
`frontend` application containers, built from each service's own
`Dockerfile` (`services/control-plane/Dockerfile`,
`services/governance-service/Dockerfile`, `frontend/Dockerfile`). See
`ARCHITECTURE.md` section 2.6.

## Usage

Run from the **repository root** (build contexts are relative to this
compose file's directory, and the app service builds need the whole
workspace):

```bash
docker compose -f infra/docker/docker-compose.yml up -d --build
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready    # checks the real Postgres container above
curl http://localhost:8001/health
curl http://localhost:8080/                 # the console, nginx-served
curl http://localhost:8080/api/v1/health    # console -> nginx reverse proxy -> control-plane
```

- PostgreSQL: `localhost:5432`, database `tdm_metadata`
- MinIO API: `localhost:9000`, console: `localhost:9001`
- control-plane API: `localhost:8000`
- governance-service: `localhost:8001`
- frontend console: `localhost:8080`

Host ports are overridable (e.g. to avoid a clash with another project
already using `5432`/`8000` on your machine) via environment variables,
each defaulting to the port above: `TDM_POSTGRES_HOST_PORT`,
`TDM_CONTROL_PLANE_HOST_PORT`, `TDM_GOVERNANCE_SERVICE_HOST_PORT`,
`TDM_FRONTEND_HOST_PORT`. Example:

```bash
TDM_POSTGRES_HOST_PORT=15432 TDM_CONTROL_PLANE_HOST_PORT=18000 \
  docker compose -f infra/docker/docker-compose.yml up -d --build postgres control-plane
```

`data-plane` is deliberately not containerized here — see
`problems_phase_12.md` for the explicit decision record (it is a
PySpark/pandas batch/CLI toolkit, not a long-running service).

All credentials in `docker-compose.yml` and `.env.example` are obvious
local-development-only placeholders. See `SECURITY.md`.

## Phase 12 status

Real, verified: `docker compose up -d --build postgres control-plane
governance-service frontend` brings up all four containers healthy, and
`GET /api/v1/ready` on the real control-plane container reports the
real Postgres container as `"healthy": true, "detail": "reachable"` --
this is the first time this repository has proven its metadata-plane
database against real application code in a real container (previously
tracked as open in `problems_master.md` P0-2 and `problems_phase_01.md`
P1-1). See `problems_phase_12.md` for the full verification record,
including one real bug found and fixed while verifying (`frontend/nginx.conf`'s
reverse-proxy rewrite) and one real external blocker (MinIO's Docker
Hub images are no longer publicly pullable as of this phase --
`minio` service remains defined for documentation/future-adapter
purposes but could not be started in this environment; not a defect in
this repository).
