# Roadmap

This repository is built as a **22-phase promptbook-driven project**. Each
phase is scoped to be independently completable, testable, and documented
before the next begins. Phases are not sprints with fixed dates — they are
ordered units of work. A phase is not "done" until its required tests pass
(see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the per-phase process).

This file tracks the *plan*. Day-to-day open issues live in
[`problems_master.md`](problems_master.md).

## Phase index

| Phase | Theme | Status |
|---|---|---|
| 0 | Architecture, repository structure, conventions, ADRs, scaffolding | **Complete** |
| 1 | Metadata plane: PostgreSQL schema, SQLAlchemy models, Alembic migrations | Not started |
| 2 | Control plane skeleton: FastAPI app, health/readiness, config, RBAC stubs | Not started |
| 3 | Security/governance plane: audit event log, secrets adapter, RBAC model | Not started |
| 4 | Local infrastructure: Docker Compose (Postgres, MinIO), dev bootstrap scripts | Not started |
| 5 | Object storage abstraction: MinIO adapter + S3/Azure adapter interfaces | Not started |
| 6 | Synthetic source data: reference synthetic healthcare schema + generators | Not started |
| 7 | PHI/PII discovery & classification engine | Not started |
| 8 | Data subsetting engine (single-system, referential-integrity-preserving) | Not started |
| 9 | Deterministic masking engine (pseudonymization/tokenization) | Not started |
| 10 | Cross-system referential integrity for masking (multi-source) | Not started |
| 11 | Masking certification: automated pass/fail evidence generation | Not started |
| 12 | Synthetic data generation engine (no-source-row scenarios) | Not started |
| 13 | Snapshot & versioning system, refresh cadence & orchestration | Not started |
| 14 | Job orchestration in control plane (submit, track, retry, schedule) | Not started |
| 15 | Storage/compute footprint management & lower-environment capacity planning | Not started |
| 16 | UI: React/TypeScript/Vite console (request, inspect, certify data) | Not started |
| 17 | Observability: structured logging, metrics, tracing across planes | Not started |
| 18 | CI/CD: GitHub Actions (lint, unit, integration, data-quality, E2E gates) | Not started |
| 19 | Testing depth: contract tests, data-quality tests, Playwright E2E suite | Not started |
| 20 | Kubernetes/Helm deployment shape + Terraform examples (AWS/Azure) | Not started |
| 21 | Disaster recovery drills, runbooks, chaos/failure-mode testing | Not started |
| 22 | Hardening, documentation pass, tutorial completion, portfolio polish | Not started |

## Phase 0 — what was actually delivered

- Repository structure across six architectural planes
- `ARCHITECTURE.md` describing the system, its planes, and their interfaces
- ADRs recording the foundational technical decisions (`docs/adr/`)
- `SECURITY.md`, `THREAT_MODEL.md`, `DATA_GOVERNANCE.md`, `CONTRIBUTING.md`
- `docs/tutorial/`, `docs/runbooks/`, `docs/diagrams/` seeded with real content
- `problems_master.md` established as the live problem-tracking process
- Empty/scaffold Python packages for `control-plane`, `data-plane`,
  `governance-service`, and the shared `contracts` library, each with a
  `pyproject.toml` and a documented purpose but no business logic
- Empty/scaffold React + TypeScript + Vite frontend
- Docker Compose, Terraform, and Helm scaffolding (structure only, not wired
  to real infrastructure yet)
- GitHub Actions CI workflow skeleton

## Non-goals for Phase 0

- No working application. Nothing here should be expected to run end to end.
- No real database migrations, no real masking logic, no real UI screens.
- No dependency installation was run (`pip install` / `npm install`) — config
  files are in place so a later phase can do this deliberately, once there is
  something worth installing dependencies for.
