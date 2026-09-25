# Chapter 17 — CI/CD

## The concept

Continuous Integration/Continuous Delivery (CI/CD) is the automation
that runs every check a codebase needs — lint, type-check, unit tests,
integration tests, data-quality tests, security checks — on every
change, and blocks a release if any of them fail. Without it, "did this
change break anything" depends on someone remembering to run the right
commands by hand, which does not scale past one contributor and does
not survive a bad day. For a platform whose entire value proposition is
"we can prove this data is safe" (Chapter 2), CI/CD is also where that
proof gets re-checked automatically, every time, rather than trusted
once and forgotten.

## The real workflow files, and what each one does

`.github/workflows/ci.yml`'s jobs are split by *concern* rather than one
job per package, so the Actions UI reads as "what kind of check failed":

| Job | What it checks |
|---|---|
| `lint-python` | `ruff check` across every workspace package |
| `typecheck-python` | `mypy` across every workspace package (data-plane's own known gap is called out non-blocking, not hidden) |
| `unit-tests` | `pytest` per package, matrixed |
| `integration-tests` | Control-plane against a real Postgres container, not SQLite |
| `data-quality-tests` | Masking correctness / no-raw-value-leakage, subsetting referential integrity, certification gates, synthetic-scenario provenance, and platform failure-injection scenarios (Chapter 16) |
| `security-checks` | Repo-wide committed-secret scan, `pip-audit` dependency vulnerability scan |
| `frontend-lint` / `frontend-*` | The React console's own checks |
| `release-gate` | The single job every one of the above must pass for a release to proceed |

Three more workflows chain off this one via GitHub Actions'
`workflow_run` trigger (a real cross-workflow dependency, gated on
`github.event.workflow_run.conclusion == 'success'`):
`container-build.yml` (build + scan the three real Dockerfiles —
`services/control-plane/Dockerfile`,
`services/governance-service/Dockerfile`, `frontend/Dockerfile`) and
`e2e.yml` (Playwright), followed by the promotion chain
`deploy-qa.yml -> deploy-staging-uat.yml -> deploy-production.yml`, each
one only running after the previous one's workflow succeeded.

## Proving the gate actually blocks a broken build — not just describing it

`ROADMAP.md` Phase 12 requires: "A release must fail if unit tests
fail, integration tests fail, masking tests fail, referential-integrity
tests fail, critical security validation fails." This repository proved
that requirement for real rather than only writing it down: a real
commit (`d575396`) deliberately edited
`services/data-plane/tests/masking/test_validation.py` so the same
member ID mapped to two *different* tokens across two source systems —
exactly the cross-system linkage inconsistency
`data_plane.masking.validation.assert_referential_integrity` exists to
catch (Chapter 10's referential-integrity guarantee). This was confirmed
failing locally first, then pushed, and the CI run genuinely failed and
blocked `release-gate` before the change was reverted — see
`problems_phase_12.md` for the exact GitHub Actions run IDs of both the
real failure and the real fix. A fully green run across all three
workflows (CI, container build, Playwright E2E) was independently
confirmed afterward — `problems_phase_12.md` records seven real bugs
found and fixed during this process (a CORS misconfiguration, an nginx
CVE, and others), each verified by a real, subsequent green run, not
assumed fixed.

## Try it yourself: run exactly what CI runs

Every job above is nothing more than a named, automated wrapper around
commands you can run directly — which is the whole point (CI should
never be the *only* place a check can run):

```bash
# What lint-python runs, for one package:
ruff check services/data-plane/src services/data-plane/tests

# What unit-tests runs, for one package:
cd services/data-plane && python -m pytest -q

# What data-quality-tests runs (a subset):
cd services/data-plane && python -m pytest -q tests/masking tests/subsetting tests/certification
```

Every command in this guide's earlier chapters (discovery, masking,
subsetting, certification CLIs) is exactly what a real engineer working
on this platform would also run locally before ever pushing — CI is
the same checks, automated and gated, not a separate, opaque process.

## Where to go next

Continue to [Chapter 18 — Cloud testing](18-cloud-testing.md), or read
`problems_phase_12.md` in full for the complete, real incident log of
this phase's CI/CD build-out, including every run ID.
