# ADR-0002: Multi-package `src/` layout instead of a single monolithic requirements.txt

## Status

Accepted

## Context

The platform has multiple Python components with different runtime
concerns and different deployment lifecycles:

- `control-plane` — a FastAPI web service, deployed as a long-running API
- `data-plane` — PySpark jobs, run as batch jobs (locally or on a Spark
  cluster/Databricks), not a web service
- `governance-service` — a smaller service owning RBAC/audit/secrets
- `contracts` — shared Pydantic models used by all of the above

We need to decide how to lay these out: one big repository-wide
`requirements.txt` and a single `src/` tree, or separate installable
packages.

A single flat layout is simpler to start with — one virtual environment,
one dependency file. But it has real costs at the scale this project is
modeling:

- `data-plane` needs `pyspark` and data-engineering dependencies that
  `control-plane` (a lightweight API service) has no business depending on
  — a flat layout forces every service to carry every other service's
  dependency weight, which is exactly the kind of bloat a real lower
  environment footprint-management effort (this platform's own subject
  matter) would flag.
- Services need to be independently deployable (different containers,
  different scaling characteristics, different teams in a real
  organization). A flat layout makes it easy to accidentally create hidden
  coupling between them (an import that reaches across a boundary that
  should be a network call).
- Shared code (contract models used by more than one service) needs a home
  that isn't "inside" any one service, or every service ends up vendoring
  its own copy and they drift.

## Decision

Each deployable unit is its own installable Python package with its own
`pyproject.toml` and a `src/<package_name>/` layout:

```
services/control-plane/   -> package: control_plane
services/data-plane/      -> package: data_plane
services/governance-service/ -> package: governance_service
libs/contracts/           -> package: healthcare_tdm_contracts
```

`libs/contracts` has no dependency on any service package. Services may
depend on `libs/contracts` (as a local/editable install in development, and
as a versioned package in a real deployment pipeline). Dependencies flow
one direction only: services → libs, never libs → services, and never
service → service (if two services need to share logic, that logic belongs
in a lib, or the interaction happens over the network, not an import).

The `src/` layout (package code under `src/<name>/` rather than directly
under the project root) is used in every package specifically so tests
exercise the *installed* package, not an accidental import of the working
directory — a common source of "works on my machine, breaks in CI"
Python bugs.

Each package's tests live alongside it (`services/control-plane/tests/`,
etc.) rather than in one giant top-level `tests/` directory, so a package's
tests travel with it and CI can run/scope them per package.

## Consequences

- More `pyproject.toml` files to maintain than a single flat file.
- Local development requires installing multiple packages (`pip install -e
  services/control-plane -e services/data-plane -e ... -e libs/contracts`,
  or a small bootstrap script — to be added in Phase 1/2) rather than one
  `pip install -r requirements.txt`.
- In exchange: each service's container image only needs to install its own
  dependencies (smaller images, faster builds, smaller attack surface);
  dependency version conflicts between, e.g., FastAPI's stack and PySpark's
  stack are structurally impossible instead of something to work around;
  and the package boundaries make the plane-separation architecture
  (ADR-0003) enforceable by tooling, not just convention.
