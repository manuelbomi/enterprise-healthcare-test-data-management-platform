# enterprise-healthcare-test-data-management-platform

A production-oriented, tutorial-quality **Cloud Test Data Management (TDM) platform**
for large, regulated healthcare / life-sciences environments — built to teach junior
engineers while demonstrating senior/principal-level architecture.

> **Status:** Phase 0 — architecture, repository structure, and conventions only.
> No business logic is implemented yet. See [`ROADMAP.md`](ROADMAP.md) for the
> full 22-phase build plan and [`problems_master.md`](problems_master.md) for the
> live list of open problems.

## What this project is

Regulated healthcare organizations need realistic, referentially-consistent,
**non-identifying** data in their lower environments (dev/test/QA/perf/UAT) so
that engineers, testers, and pipelines can work without ever touching real
Protected Health Information (PHI) or Personally Identifiable Information (PII).

This repository is a from-scratch, portfolio-grade reference implementation of
the platform that makes that possible, covering:

- **Discovery & classification** of PHI/PII across heterogeneous source systems
- **Deterministic masking**, pseudonymization, and tokenization with referential
  integrity preserved *across* tables and *across* systems
- **Data subsetting** — pulling a small, representative, referentially-intact
  slice of a large production-shaped dataset
- **Synthetic data generation** for scenarios where no safe source data exists
- **Certified masking** — automated, auditable proof that a dataset meets a
  masking policy before it is allowed into a lower environment
- **Snapshots & versioning** of test data sets, with a refresh cadence and
  orchestration layer
- **Cloud storage & compute footprint management** for lower-environment
  capacity planning and cost control
- **Security, governance, and audit evidence** — RBAC, immutable audit events,
  encryption assumptions, and policy-as-code
- **CI/CD, observability, and disaster-recovery** considerations throughout

## What this project is *not*

- It is **not** connected to, and does not reference, any real company,
  employer, client, insurer, consulting firm, or proprietary platform.
- It contains **no real PHI, PII, credentials, or secrets** — ever. All
  healthcare data used anywhere in this repository (fixtures, examples,
  screenshots, docs) is synthetic and clearly labeled as such.
- It is **not** a finished product. It is built incrementally, phase by phase,
  as a teaching artifact. Each phase is documented, tested, and left in a
  working state before the next begins.

## Architecture at a glance

The platform is organized into six planes/layers, kept intentionally decoupled
so each can be reasoned about, tested, and scaled independently:

1. **Control plane** — orchestration, workflow/job scheduling, policy
   enforcement, REST/API surface (FastAPI)
2. **Data plane** — the engines that actually touch data: subsetting, masking,
   synthetic generation, format conversion (PySpark, SQL, Delta/Parquet)
3. **Metadata plane** — system of record for catalogs, lineage, job runs,
   snapshots, and data classifications (PostgreSQL)
4. **Security / governance plane** — RBAC, secrets handling, audit event
   pipeline, policy definitions, certification evidence
5. **UI** — engineer/analyst-facing console for requesting, inspecting, and
   certifying test data (React + TypeScript + Vite)
6. **Infrastructure** — local dev via Docker Compose/MinIO, cloud adapters for
   AWS S3 and Azure Blob/ADLS, Kubernetes/Helm, and Terraform examples

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design, component
diagrams, and the interfaces between planes.

## Repository layout

```
.
├── ARCHITECTURE.md            # System design, planes, interfaces
├── ROADMAP.md                 # 22-phase build plan
├── SECURITY.md                # Security posture & how to report issues
├── THREAT_MODEL.md            # STRIDE-based threat model
├── DATA_GOVERNANCE.md         # PHI/PII handling policy for this repo
├── CONTRIBUTING.md            # Dev conventions, workflow, phase process
├── problems_master.md         # Live index of open problems across phases
├── docs/
│   ├── tutorial/               # Junior-engineer-facing walkthroughs
│   ├── adr/                    # Architecture Decision Records
│   ├── runbooks/                # Operational runbooks
│   └── diagrams/                # Source diagrams (Mermaid) + descriptions
├── services/
│   ├── control-plane/          # FastAPI control-plane service
│   ├── data-plane/             # PySpark data engineering jobs
│   └── governance-service/     # Security/governance & audit service
├── libs/
│   └── contracts/               # Shared Python contracts (Pydantic schemas)
├── frontend/                   # React + TypeScript + Vite console
├── infra/
│   ├── docker/                  # Docker Compose for local dev
│   ├── terraform/               # AWS / Azure example infrastructure
│   └── k8s/helm/                 # Helm chart skeleton
├── .github/workflows/          # CI/CD pipelines
└── scripts/                    # Developer utility scripts
```

## Preferred stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Control plane | Python, FastAPI, Pydantic, SQLAlchemy |
| Data engineering | PySpark, SQL, Delta Lake / Parquet |
| Metadata store | PostgreSQL |
| Object storage | MinIO (local), AWS S3 / Azure Blob-ADLS adapters |
| Infra | Docker Compose, Kubernetes, Helm, Terraform |
| Testing | pytest, Playwright, data-quality/contract tests |
| CI/CD | GitHub Actions |
| Observability | structured logging, metrics, traces, audit events |

## Getting started

This is **Phase 0**: architecture and scaffolding only. There is no runnable
application yet. Once later phases add real implementations, this section
will be updated with concrete `docker compose up`, `pip install`, and
`npm install` instructions. For now:

- Read [`ARCHITECTURE.md`](ARCHITECTURE.md) to understand the system.
- New to Test Data Management entirely? Start with
  [`docs/tutorial/guide/README.md`](docs/tutorial/guide/README.md) — a
  complete, twenty-chapter, zero-to-understanding-this-repository
  tutorial (Phase 15).
- Read [`docs/tutorial/00-overview.md`](docs/tutorial/00-overview.md) for a
  guided walkthrough aimed at junior engineers.
- Read [`ROADMAP.md`](ROADMAP.md) to see what's next.

## License

See [`LICENSE`](LICENSE).
