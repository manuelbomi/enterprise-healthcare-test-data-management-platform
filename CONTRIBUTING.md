# Contributing

This repository is built phase by phase against a fixed 22-phase roadmap
(see `ROADMAP.md`). This document defines the conventions every phase — and
every contribution within a phase — must follow. It exists so a junior
engineer picking up any phase can work the same way a principal engineer
would.

## The per-phase process

Every phase (including this one, Phase 0) follows the same eight steps:

1. **Inspect existing code first.** Read what's already there before writing
   anything. Do not assume; check.
2. **Write/update the phase's problems file.** Before implementing, record
   what you expect to be hard or unresolved in `docs/problems/problems_master.md` (or a
   phase-specific problems file it links to), so the record of *known
   issues* exists before and independent of the implementation.
3. **Implement.** Build the smallest correct increment that satisfies the
   phase's scope — do not reach ahead into later phases.
4. **Test.** Every new behavior needs a test. Data-transformation code needs
   data-quality tests, not just unit tests of function signatures.
5. **Document.** Update the relevant docs (`ARCHITECTURE.md` if the design
   changed, an ADR if a decision was made, `docs/tutorial/` if a junior
   engineer would need a walkthrough, runbooks if an operational procedure
   changed).
6. **Remove resolved problems from the problems file.** Once a problem is
   actually fixed and tested, delete it from `docs/problems/problems_master.md` — don't
   leave stale entries.
7. **Leave unresolved problems with reproduction details.** If something is
   known-broken or out of scope for this phase, it stays in
   `docs/problems/problems_master.md` with enough detail (steps, expected vs. actual,
   affected files) that the next person doesn't have to rediscover it.
8. **Do not declare a phase complete if required tests fail.** A red test
   suite means the phase isn't done, full stop — even if the code "looks
   right."

## Architecture Decision Records (ADRs)

Any decision that would be expensive to reverse, or that a future
contributor would reasonably ask "why did we do it this way?" about, gets an
ADR in `docs/adr/`. Use the existing ADRs as a template. ADRs are numbered
sequentially and are never renumbered or deleted — a reversed decision gets
a new ADR that supersedes the old one, and the old one is marked
"Superseded by ADR-XXXX."

## Repository conventions

### Layout

- `services/` — independently deployable Python services, one directory
  per plane-owning service (`control-plane`, `data-plane`,
  `governance-service`). Each has its own `pyproject.toml`, `src/` package,
  and `tests/`.
- `libs/` — shared Python libraries used by more than one service
  (currently `contracts`, the shared Pydantic contract models). Libraries
  in here must not depend on any service — dependencies flow one way, from
  services to libs, never the reverse.
- `frontend/` — the single React/TypeScript/Vite application.
- `infra/` — infrastructure as code and local dev environment definitions.
  Nothing in here should contain a real secret or a real cloud account ID.
- `docs/` — all documentation that isn't a top-level policy file.

### Python

- Python 3.11+.
- Each service/lib is its own installable package with a `pyproject.toml`
  (see [ADR-0002](docs/adr/0002-python-project-layout.md) for why a
  multi-package `src/` layout was chosen over a single monolithic
  requirements.txt).
- Format with `black`, lint with `ruff`, type-check with `mypy` where
  practical. These are configured per-package in each `pyproject.toml`.
- Every public function/class gets a docstring explaining *purpose and
  contract*, not just restating the signature — this codebase is a teaching
  artifact, so the "why" matters as much as the "what."

### TypeScript / React

- Strict TypeScript (`strict: true`).
- Accessible-by-default component architecture: semantic HTML first, ARIA
  only where semantic HTML can't express the interaction, keyboard
  navigation considered for every interactive component.
- Functional components + hooks; no class components.

### Commit conventions

- Conventional, imperative subject lines (`Add subsetting job contract`,
  not `Added` or `Adds`).
- A commit does one coherent thing. Scaffolding and implementation can be
  separate commits within the same phase.
- Never commit real secrets, real PHI/PII, or real organization names (see
  `SECURITY.md` and `DATA_GOVERNANCE.md`). This is enforced by review, not
  (yet) by tooling — a future phase may add a pre-commit secret scanner.

### Testing

- `pytest` for all Python services/libs.
- Data-transformation logic (subsetting, masking, synthetic generation) gets
  data-quality tests in addition to unit tests: row-count/shape assertions,
  referential-integrity assertions, "no raw identifier leaked" assertions.
- Contract tests verify the Pydantic models in `libs/contracts` are honored
  by both producer and consumer services.
- Playwright for frontend E2E tests, added once there are real screens to
  test.
- CI (`.github/workflows/`) runs lint, type-check, and test for every
  package that has one; a package with no tests yet is not silently
  skipped — its CI job is either present-and-passing-trivially or the gap is
  tracked in `docs/problems/problems_master.md`.

### Branching

This is a solo/portfolio project; direct commits to the working branch are
fine during scaffolding phases. Once CI is live (Phase 18), prefer
short-lived feature branches merged after CI passes.

## Definition of done (per phase)

A phase is done when:

- The code it scoped exists and does what its documentation says
- Its tests exist and pass
- Its docs (README/ARCHITECTURE/ADR/tutorial as applicable) are updated
- `docs/problems/problems_master.md` reflects reality: resolved problems removed,
  unresolved problems documented with repro details
- No real secrets, PHI/PII, or real organization names were introduced
