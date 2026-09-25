# Tutorial 00 — Overview: what this platform is and why it's shaped this way

This is the starting point for a junior engineer joining this project. It
assumes no prior knowledge of test data management (TDM) and walks through
the problem, the vocabulary, and how to navigate the repository.

## 1. The problem, in plain terms

Imagine a hospital network's software teams need a "test" version of their
patient database to build and test software against. Three bad options:

1. **Use real production data, copied into test.** Fast, but now every
   laptop, CI runner, and lower-environment database that touches this copy
   is a HIPAA liability. This is the single most common real-world cause of
   healthcare data breaches that have nothing to do with sophisticated
   attackers — it's a test database with real patient records in it that
   wasn't secured like production.
2. **Hand-write fake test data.** Safe, but hand-written fixtures are small,
   unrealistic, and don't scale — they don't have the volume, the edge
   cases, or the referential complexity of real data, so tests built against
   them miss real bugs.
3. **Use production data, but with identifying fields blanked out /
   replaced with "REDACTED."** Better than nothing, but naive redaction
   usually breaks joins (every "REDACTED" patient ID looks the same, so you
   can no longer tell which claims belong to which patient) and often still
   leaves indirectly identifying information (a rare diagnosis plus a ZIP
   code plus an age can re-identify someone even with the name removed).

This platform exists to do a fourth, much harder thing well: **produce data
that is realistic enough to test against, safe enough to never be a breach
if leaked, small enough to be cheap to store and refresh, and provably
correct enough that a compliance officer can sign off on it.**

## 2. Key vocabulary

| Term | Meaning in this project |
|---|---|
| PHI / PII | Protected Health Information / Personally Identifiable Information — the two categories of data this platform must never leak into a lower environment |
| Subsetting | Taking a smaller, representative slice of a large dataset while preserving the relationships between rows (a subset of patients plus *all* their related claims, not claims from unrelated patients) |
| Masking | Replacing a real sensitive value with a fake one, in a way that's consistent (same real value → same fake value) so relationships between tables still work |
| Pseudonymization / tokenization | A specific style of masking where a real value is replaced by a "token" that has no mathematical relationship to the real value an attacker could exploit, and the mapping back to the real value (if it needs to exist) is stored separately and strictly access-controlled |
| Synthetic data | Data that was never derived from any real record at all — generated from statistical models/rules to look realistic |
| Certification | An automated, evidence-producing check that a dataset actually meets its masking policy before anyone is allowed to use it |
| Snapshot | A named, versioned, point-in-time test dataset that a team can request/refresh |
| Referential integrity | The property that relationships between records (a claim belongs to a patient, an encounter belongs to a provider) still hold after subsetting/masking |
| Lower environment | Any non-production environment: dev, test, QA, performance, UAT, sandbox |
| Footprint | How much storage and compute a lower environment's test data is consuming — a real cost and risk surface that has to be managed, not ignored |

## 3. How the repository is organized

Start with `ARCHITECTURE.md` — it explains the six "planes" the system is
split into (control, data, metadata, security/governance, UI,
infrastructure) and why. Every folder in this repository maps to one of
those planes:

- `services/control-plane` → control plane
- `services/data-plane` → data plane
- `services/governance-service` → security/governance plane
- the PostgreSQL schema owned by the control plane → metadata plane
- `frontend/` → UI
- `infra/` → infrastructure
- `libs/contracts` → shared types used *between* planes (not a plane itself)

If you're asked to work on "the thing that decides what to mask," that's
the data plane's masking module
(`services/data-plane/src/data_plane/masking/`). If you're asked to work on
"the thing that decides who's allowed to request it," that's the
security/governance plane's RBAC module. Keeping this mental map — "which
plane owns this concern?" — is the single most useful habit for navigating
this codebase.

## 4. How work happens: the phase process

This project is built in 22 ordered phases (see `ROADMAP.md`). Every phase,
regardless of size, follows the same eight-step process described in
`CONTRIBUTING.md`: inspect existing code, write down expected problems,
implement, test, document, remove resolved problems, leave unresolved
problems with repro details, and never declare a phase done with failing
required tests. Reading `problems_master.md` at the start of any session
tells you exactly what's known-broken or known-missing right now.

## 5. What "done" looks like for the whole project

By Phase 22, this repository will contain a runnable (locally, via Docker
Compose) demonstration of: discovering PHI/PII in a synthetic source
schema, subsetting and masking it with referential integrity intact,
generating synthetic data for gaps, certifying the output, publishing it as
a versioned snapshot, exposing all of that through a control-plane API and
a React console, with CI/CD, observability, and disaster-recovery
considerations demonstrated throughout — all built and documented at a
level a junior engineer can learn from and a principal engineer would sign
off on.

## 6. Where to go next

- Read `ARCHITECTURE.md` in full.
- Skim the ADRs in `docs/adr/` — each one is a short "why we chose X over Y."
- Read `DATA_GOVERNANCE.md` to understand the classification/masking/
  certification model in more depth.
- Check `problems_master.md` for current known issues before starting any
  new work.
