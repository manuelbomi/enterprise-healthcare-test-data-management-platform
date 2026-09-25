# Problems — Phase 12 (Production CI/CD and cloud testing)

Written before implementation per `CONTRIBUTING.md`'s per-phase process
(step 2), then updated as real work uncovered real findings (step 6/7).
Every "resolved" item below was actually run and observed, not assumed.

## Expected-hard items (written before implementation)

- CI has never run against this repository (`problems_master.md` P0-2) —
  the biggest risk is that `.github/workflows/ci.yml`'s Phase-0-era
  jobs simply fail on first real run (stale package layout, lint
  drift accumulated across 11 unreviewed phases, etc.). Addressed by
  running every command locally first, exactly as the workflow invokes
  it, before wiring it in — see "Resolved" below for what that
  actually caught.
- No Dockerfile exists anywhere in the repository yet (`problems_phase_11.md`
  P11-2). `services/governance-service` in particular has no FastAPI
  app at all (`ARCHITECTURE.md` section 2.4: "structural scaffold") —
  building a real container for it means either faking business logic
  that doesn't exist, or giving it a real (if minimal) liveness
  endpoint first. Chose the latter — see "Resolved" below.
- `docker-compose.yml`'s Postgres container has never been started
  against real application code (`problems_master.md` P0-2 references
  this indirectly; `ARCHITECTURE.md`'s own Phase 7/8/11 notes describe
  `lifecycle_database_url` defaulting to SQLite specifically because
  Postgres was never verified). Risk: the control plane's SQLAlchemy
  models might not actually be Postgres-compatible despite the
  "Postgres-portable by construction" claims in `ARCHITECTURE.md`'s
  Phase 7 note.
- Deployment gates ("a release must fail if unit/integration/masking/
  referential-integrity tests fail, or critical security validation
  fails") need to be *proven*, not just written — a CI YAML file that
  looks correct but was never watched to actually go red is not a
  real gate.
- data-plane is a PySpark/pandas batch/CLI toolkit with no long-running
  service entry point — unclear whether it needs a container at all
  for this phase's scope.

## Resolved (found and fixed during this phase)

- **Ruff lint was actually failing** — three unused-import findings
  (`services/control-plane/tests/test_capacity_planner.py`'s
  `DatasetVersionStatus`, `services/data-plane/tests/capacity/test_incremental.py`'s
  `CertificationStatus`, `services/data-plane/src/data_plane/capacity/cli.py`'s
  `json`, `services/control-plane/src/control_plane/domain/governance/repository.py`'s
  `json`, `services/data-plane/src/data_plane/synthetic/scenarios.py`'s
  `tag_rows`) plus one unused local variable in
  `services/data-plane/tests/synthetic/test_synthetic_manifest.py`.
  This is direct, concrete proof of `problems_master.md` P0-2's
  underlying concern — several phases' worth of code had never
  actually been run through the CI lint step, because CI had never
  run. Fixed (`ruff check --fix` plus one manual edit for the unused
  local variable); `ruff check` is now clean across all four Python
  packages and wired as a hard-blocking `lint-python` CI job.
- **A real mypy strict-mode bug** —
  `control_plane.platform.audit.AuditLogRepository._to_contract` passed
  `row.event_id` (a `str` column) directly into `AuditEvent(event_id=...)`,
  which the `libs/contracts` model types as `UUID`. Every existing test
  happened to pass anyway (nothing asserted the field's runtime type),
  so this was a real, live type-safety gap invisible without mypy
  actually running. Fixed with `UUID(row.event_id)`;
  `services/control-plane` and `libs/contracts` are now mypy-clean and
  wired as hard-blocking `typecheck-python` CI steps.
- **`services/data-plane` has 15 pre-existing mypy strict-mode
  findings** (`masking/policy.py`, `synthesizers.py`, `engine.py`,
  `dataset_masker.py`, `cli.py`; `synthetic/provenance.py`,
  `reference_pool.py`, `manifest.py`), all predating Phase 12 (Phases 3
  and 5). None are behavior bugs caught by any existing test (413
  data-plane tests all still pass); they are real strict-mode
  typing gaps (`str | None` vs `str`, `object` vs `str`, literal-type
  narrowing across an `if`/`elif` chain, etc.). Fixing all 15 is out of
  this phase's scope (CI/CD, not a data-plane refactor) — the CI
  `typecheck-python` job runs `mypy services/data-plane/src` and
  reports every finding as a build annotation, but is explicitly
  `continue-on-error: true` for this one step only, so it cannot
  silently regress further (every future finding still shows up in the
  Actions log) without blocking the release gate on a pre-existing,
  unrelated gap. Left open, not silently fixed or silently ignored —
  a reasonable owner is whichever future phase next touches
  `data_plane.masking`/`data_plane.synthetic` in depth.
- **`governance_service` had no FastAPI app to containerize** — added
  the minimal liveness-only pattern `control_plane.main` itself started
  with in Phase 0 (`governance_service/main.py`, `api/health.py`, one
  test). This is a genuinely new, real (if intentionally small)
  addition, not a Phase-12-scope violation — it exists specifically so
  every service directory has something real to build, containerize,
  health-check, and deploy, matching this phase's actual scope
  ("container build hooks", "Docker Compose integration environment",
  "Kubernetes manifests"). RBAC/audit/secrets/evidence-store business
  logic remains explicitly out of scope here, per `ARCHITECTURE.md`
  section 2.4.
- **`scripts/security/dependency_scan.py`'s `pip-audit` lookup was
  PATH-fragile** — `shutil.which("pip-audit")` failed on a machine
  where `pip install pip-audit` succeeded (`pip show pip-audit` finds
  it) but the console-script entry point isn't on `PATH` (a per-user
  Windows install in this environment). Fixed with a fallback to
  `python -m pip_audit` when the bare command isn't found on `PATH`,
  probed with `--version` so a genuinely-missing package still reports
  the same explicit failure as before. Verified both code paths
  locally.
- **nginx reverse-proxy path bug in `frontend/nginx.conf`, found and
  fixed while verifying the built container** — using a variable in
  `proxy_pass` (needed for deferred DNS resolution against Docker
  Compose's embedded DNS, `resolver 127.0.0.11`) silently disables
  nginx's normal location-prefix URI rewrite. The first version of this
  file forwarded every request under `/api/` to the literal path
  `/api/` on the backend, regardless of the real requested path (a real
  `GET /api/v1/health` through the container reached control-plane as
  `GET /api/` and got a real 404 — reproduced and confirmed via
  `docker logs`). Fixed by proxying to
  `http://$control_plane_upstream$request_uri` instead, which forwards
  the full original path. Re-verified: `curl http://localhost:8080/api/v1/health`
  through the container now returns `200 {"status":"ok","service":"control-plane"}`.
  A second, unrelated nginx bug in the same file (bare
  `proxy_pass http://control-plane:8000/...;` crashes nginx at startup
  with `host not found in upstream` when the container is run
  standalone, outside the Compose network, because nginx resolves a
  literal upstream hostname at config-load time) was found first and
  fixed with the `resolver` + variable pattern that then caused the bug
  above — both are documented in `frontend/nginx.conf`'s own comments.
- **MinIO's Docker Hub images are no longer publicly pullable** —
  `docker pull minio/minio:latest` and `docker pull quay.io/minio/minio:latest`
  both fail in this environment (`pull access denied` /
  `401 Unauthorized`); a Docker Hub API query confirms `minio/minio`
  returns `{"message":"object not found"}` and `bitnami/minio` has zero
  published tags. This is an external, real change (MinIO Inc.
  restructured its public image distribution after its 2024/2025
  AGPLv3 licensing dispute), not a defect in this repository's compose
  file — `docker-compose.yml`'s `minio` service definition is left in
  place (documenting the intended local S3-compatible target per
  ADR-0005) but could not be started in this environment. This phase's
  actual Postgres-verification goal did not depend on MinIO — no
  application code reads/writes object storage yet (`problems_master.md`
  P0-3, still open) — so this blocker did not prevent the
  control-plane/Postgres integration verification below. Tracked here
  rather than silently worked around; a maintained MinIO alternative
  (self-built from source, or a different S3-compatible test double
  such as `localstack`) is future work.
- **Port collisions with an unrelated, already-running project on this
  machine** (`forgezen_*` containers occupying host ports 5432 and
  8000) — real, and specific to this verification environment, not a
  defect. Fixed durably (not just worked around for this session) by
  making every app-service host port in `docker-compose.yml`
  interpolated with an overridable default
  (`${TDM_POSTGRES_HOST_PORT:-5432}`, etc.), documented in
  `infra/docker/README.md`. Verified the override actually works via
  environment variables (a first attempt using a separate Compose
  override file failed because Compose merges — rather than replaces —
  `ports:` lists across `-f` files, which would have bound *both*
  ports and still collided; env-var interpolation was the correct
  fix).

## Real verification performed this phase

- **Docker images**: `docker build` succeeded locally for all three
  Dockerfiles (`tdm-control-plane`, `tdm-governance-service`,
  `tdm-console`); each container was run standalone and answered its
  real health endpoint (`/api/v1/health`, `/health`, `/`) with `200`.
- **Docker Compose integration environment, including real Postgres**:
  `docker compose -f infra/docker/docker-compose.yml up -d --build
  postgres control-plane governance-service frontend` brought up all
  four containers healthy. `GET /api/v1/ready` on the real
  control-plane container returned:
  `{"status":"ready","service":"control-plane","checks":[{"name":"database","healthy":true,"required":true,"detail":"reachable"},{"name":"catalog_artifact","healthy":false,"required":false,"detail":"not found ..."}]}`
  — the `database` check is real: `control_plane.platform.readiness.check_database`
  opened a real SQLAlchemy connection and ran `SELECT 1` against the
  real `tdm-postgres` container, not SQLite. **This resolves
  `problems_master.md` P0-2's Postgres-side concern and the identical
  gap referenced in `ARCHITECTURE.md`'s Phase 7/8/11 notes** ("what
  remains unverified against a real Postgres instance") — see that
  file's own text, now updated. The frontend container's nginx proxy
  was also verified end to end: `curl http://localhost:8080/api/v1/health`
  (through nginx, through the Compose network, to the real
  control-plane container) returned the same `200` response.
- **`pytest` — real counts, this environment, before vs. after this
  phase's fixes** (`libs/contracts`, `services/control-plane`,
  `services/data-plane`, `services/governance-service`):
  - Before: 59 + 171 + 413 + 1 = **644 passing**, 0 failing (baseline
    unchanged from Phase 11's own reported counts).
  - After: 59 + 171 + 413 + **2** = **645 passing**, 0 failing — the
    one new test is `services/governance-service/tests/test_health_api.py`,
    the only net-new test this phase adds (every other change was a
    fix to pre-existing code, not new business logic).
- **`ruff check`**: clean across all four Python packages (was not,
  before this phase's fixes — see "Resolved" above).
- **`mypy`**: clean for `libs/contracts`, `services/control-plane`,
  `services/governance-service`; 15 pre-existing findings in
  `services/data-plane`, reported but non-blocking (see "Resolved"
  above).
- **Frontend**: `npm run lint` (clean), `npm run build` (tsc + vite
  build, succeeds, produces `frontend/dist`), `npm run test` (39/39
  Vitest tests passing, 11 files) — all unchanged from Phase 9/11's own
  reported state; this phase did not modify any frontend application
  source, only added `Dockerfile`/`nginx.conf`.
- **Workflow YAML validity**: every file under `.github/workflows/`
  parses as valid YAML (`python -c "import yaml; yaml.safe_load(...)"`)
  and passes `actionlint` (run via `docker run rhysd/actionlint`) with
  zero errors — the only output was five informational shellcheck
  warnings (`SC2034`, an intentionally-unused loop counter in a
  `for i in $(seq 1 N); do ...; done` retry-polling idiom used in
  several "wait for readiness" steps), not a real problem.
- **Helm**: `helm lint infra/k8s/helm/tdm-platform` passes (0 charts
  failed); `helm template` renders successfully both with default
  values and with `controlPlane.dbSecret.create=true` +
  `ingress.enabled=true` set, confirmed the conditional `Secret` and
  `Ingress` manifests render correctly with the expected fields. Run
  via `docker run alpine/helm:3.15.4` (Helm is not installed locally in
  this environment).
- **Terraform**: `terraform fmt -check`/`fmt` and `terraform validate`
  (after `terraform init -backend=false`) both pass for
  `infra/terraform/azure/main.tf` and (unchanged, still passing)
  `infra/terraform/aws/main.tf`. Run via `docker run hashicorp/terraform:1.9`
  (Terraform is not installed locally in this environment). `fmt`
  caught real alignment issues on first pass (fixed by `terraform fmt`
  itself). No `plan`/`apply` was run; no Azure/AWS credentials exist in
  this environment or repository.
- **CI actually running on GitHub Actions**: see the dedicated section
  below — this is the one item this file does not claim without a
  linked, real run.

## Real CI verification (GitHub Actions)

<!-- Filled in after pushing the verification branch/PR and observing
     real `gh run list`/`gh run view` output — see the phase-12 handback
     report for the actual run URLs/IDs and the deliberate-failure
     experiment's result. This section intentionally starts as a
     placeholder in source control history; by the time this file is
     part of the final `main` state, it reflects what was actually
     observed. -->

## Explicit decisions / scope boundaries

- **`data-plane` is not containerized this phase.** It is a
  PySpark/pandas batch/CLI toolkit
  (`python -m data_plane.<discovery|masking|subsetting|synthetic|certification>.cli`),
  not a long-running service with a port to expose — there is nothing
  for a Kubernetes `Deployment`/Docker Compose long-running service to
  run. No code anywhere in `services/data-plane` actually creates a
  `SparkSession` yet (`grep -r "SparkSession" services/data-plane/src`
  returns nothing) despite `pyspark`/`delta-spark` being declared
  dependencies — every job today runs against pandas. A real
  Spark-backed container (with a JDK, `spark-submit` entry point, and
  a real cluster-mode config) is anticipated no earlier than Phase 14
  ("Scale and performance engineering (PySpark benchmarks)"), once
  code actually needs one — building a container for code that never
  imports `pyspark.sql.SparkSession` today would be theater, not real
  infrastructure. `docker-compose.yml`, the Helm chart, and this
  document all say so explicitly rather than silently omitting it.
- **Deployment promotion workflows (`deploy-qa.yml`,
  `deploy-staging-uat.yml`, `deploy-production.yml`) deploy to a Docker
  Compose stand-in, never a real cloud target.** No AWS/Azure
  credential exists in this repository or its CI. This is documented
  in each workflow's own header comment and in
  `docs/AZURE_PRODUCTION_DEPLOYMENT.md` section 5 ("what a real rollout
  would add").
- **The `production` GitHub Environment's manual-approval protection
  rule** (if configured — see the phase-12 handback report for whether
  a required-reviewer rule was actually added via the GitHub API during
  this phase, and how it was verified) is a real GitHub feature, not
  simulated in YAML; it is documented here rather than assumed.
