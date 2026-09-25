# infra/docker

Local development infrastructure via Docker Compose: PostgreSQL (metadata
plane) and MinIO (local S3-compatible object storage). See
`ARCHITECTURE.md` section 2.6.

## Usage

```bash
docker compose -f infra/docker/docker-compose.yml up -d
```

- PostgreSQL: `localhost:5432`, database `tdm_metadata`
- MinIO API: `localhost:9000`, console: `localhost:9001`

All credentials in `docker-compose.yml` and `.env.example` are obvious
local-development-only placeholders. See `SECURITY.md`.

## Phase 0 status

This compose file has not yet been run/validated in this environment.
Application services are intentionally not containerized here yet — see
`ROADMAP.md` Phase 4.
