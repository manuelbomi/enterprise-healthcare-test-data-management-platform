# Problems — Phase 15 (Complete Junior-Engineer Tutorial)

Written before implementation, per `CONTRIBUTING.md`. Updated after
implementation to record what was actually resolved vs. what remains
open (moved to `problems_master.md` if broader than this phase).

## Context this phase starts from

`docs/tutorial/` already contains `00-overview.md` plus numbered
deep-dive chapters `01-planes-and-data-flow.md` through
`09-centralized-masking-governance.md` and
`13-auditability-and-compliance-evidence.md` (no `10`/`11`/`12`/`14` —
Phases 10-12 and 14 did not add a numbered chapter under this exact
naming scheme). Each of those was written by the phase that introduced
the capability it documents, and each assumes the reader already knows
what TDM/PHI/subsetting/masking/certification *mean* — they are
implementation-detail deep dives into this repo's actual code, not an
onboarding path.

`ROADMAP.md` Phase 15's own chapter list is a different, 20-chapter
arc: "zero to understanding the complete repository" for a junior data
engineer, starting from first principles ("What is TDM," "Why regulated
enterprises need TDM," "PHI vs PII," "production vs lower
environments") that the existing 00/01-09/13 chapters never explain
from scratch. Before writing anything, this phase had to answer one
structural question honestly: **how do the two chapter sets relate,
and where do the twenty new files live so nothing already pointing at
`docs/tutorial/0X-...md`/`docs/tutorial/13-...md` breaks?**

## Decision 1 — filenames/numbering (made before writing any chapter)

`grep -rn "docs/tutorial/0" .` and `grep -rn "docs/tutorial/1" .` across
the whole repository (excluding `docs/tutorial/` itself) turned up real
cross-references from `ARCHITECTURE.md`, `CONTRIBUTING.md`,
`docs/adr/0007-...md`, `docs/diagrams/README.md`,
`docs/PLATFORM_INTEGRITY.md`, `docs/runbooks/duplicate-requests-and-revoked-datasets.md`,
`README.md`, `ROADMAP.md`, `problems_phase_04.md`, `problems_phase_05.md`,
`problems_phase_07.md`, `scripts/README.md`,
`services/control-plane/README.md`,
`services/data-plane/src/data_plane/subsetting/README.md`, and
`services/data-plane/src/data_plane/synthetic/README.md` — every one of
them pointing at an *existing* filename (`00-overview.md` through
`09-centralized-masking-governance.md`, `13-auditability-and-compliance-evidence.md`).
None of them ever reference a `docs/tutorial/10-...md`,
`11-...md`, `12-...md`, or `14-...md` that doesn't exist, and none
reference a path under a `guide/` subdirectory (which does not exist
yet). So:

- **Renumbering or reusing any existing `docs/tutorial/0X-...md`/`13-...md`
  filename was ruled out** — it would silently break every one of the
  cross-references above.
- **A new `docs/tutorial/guide/` subdirectory, with its own `01-...md`
  through `20-...md` sequence plus a `README.md` index, was chosen**
  instead. This has zero collision risk (a distinct directory), keeps
  the promptbook's own chapter numbers (1-20) intact and legible, and
  lets `docs/tutorial/00-overview.md` and this new
  `docs/tutorial/guide/README.md` cross-link to each other without
  either one owning or duplicating the other's numbering.

## Decision 2 — how the two chapter sets relate (made before writing any chapter)

The existing `01-09`/`13` chapters are treated as the *implementation-detail
reference* for the concept each corresponds to; the new `guide/01-20`
chapters are the *onboarding narrative* — each one teaches its concept
from first principles for a reader who has never seen this repository,
then explicitly links out to the matching existing tutorial chapter (or
README/ADR/doc, where no numbered chapter exists for that concept) for
"exactly how this repository implements it," rather than duplicating
that content. Concretely: `guide/07-subsetting.md` teaches what
subsetting/referential closure mean in general, then says "see
`../04-subsetting-and-referential-closure.md` for exactly how this
repository implements it, in `data_plane.subsetting`" — and stops,
rather than re-deriving Chapter 04's own worked example. This is stated
explicitly in `docs/tutorial/guide/README.md` and in
`docs/tutorial/00-overview.md`'s updated "Where to go next" section, so
a new reader landing in `docs/tutorial/` is never left guessing which
set to read first (answer: `guide/` first, then the matching `0X`
chapter for depth on any topic).

## Decision 3 — Chapter 20, "Operating TDM as a product"

This repository never built a dedicated "operating TDM as a product"
subsystem — there is no single module named `product` or `operations`.
Rather than invent unbuilt functionality, `guide/20-operating-tdm-as-a-product.md`
synthesizes this chapter from real, already-built product-operations
material that exists across phases: Phase 7 lifecycle/refresh
(`control_plane.domain.lifecycle`), Phase 8 capacity
(`data_plane.capacity`, `control_plane.domain.capacity`), Phase 10
governance (`control_plane.domain.governance`), Phase 11 platform
integrity (`control_plane.platform`), Phase 13 audit evidence
(`control_plane.domain.evidence`), plus the process itself
(`ROADMAP.md`, `CONTRIBUTING.md`, `problems_master.md`). It is explicit,
in the chapter text, that this is a synthesis across real subsystems,
not a description of one unbuilt "product operations" module.

## What is, and is not, tested this phase

This phase is documentation-only — it adds no new application code to
any service or library, and no new pytest test file. Per
`CONTRIBUTING.md` step 4 ("every new behavior needs a test"): there is
no new *behavior* here, so there is nothing new to add a pytest test
for, and fabricating a test against prose would be dishonest busywork,
not a real check. What this phase substitutes for tests, consistent
with `CONTRIBUTING.md`'s spirit ("do not declare a phase complete if
required tests fail" — nothing here should be taken on faith either):

1. **Every code/module/CLI-flag claim in every new chapter was checked
   against the real source file it names** (module maps, CLI flags,
   API routes, contract field names) before being written down — not
   inferred from an earlier phase's README/ADR prose alone.
2. **Every "expected output" block that looks like a captured terminal
   session was produced by actually running the real CLI against a
   freshly generated estate in this environment**, not hand-typed:
   - `python -m data_plane.reference_data.cli --scale tiny --out-dir ...`
   - `python -m data_plane.discovery.cli --estate-dir ... --out ...`
   - `python -m data_plane.subsetting.cli --estate-dir ... --out-dir ... --strategy fixed_population --param count=8`
   - `python -m data_plane.masking.cli --estate-dir ... --catalog ... --out-dir ...` (using a
     freshly generated, throwaway, never-committed dev HMAC key)
   - `python -m data_plane.certification.cli --scale tiny --out-dir ... --strategy fixed_population --param count=10 --scenario high_cost_claims --publish`
   - `python -m data_plane.capacity.cli footprint ...`
   All of the above were run in this session against this repository's
   own real code; the row counts, gate results, technique breakdowns,
   and byte counts quoted in the new chapters are the real numbers
   those runs produced, not numbers copied from an older phase's
   tutorial without re-running them. Chapters covering Phase 7/8/9/10/11/13
   behavior that is already demonstrated end-to-end with real captured
   output in the existing `docs/tutorial/07-...md`/`08-...md`/`09-...md`/`13-...md`
   chapters (via `scripts/demo_phase7_lifecycle.py`,
   `scripts/demo_phase8_capacity.py`, `scripts/demo_phase10_governance.py`)
   quote that already-real, already-verified output rather than
   re-running the same demo scripts a second time to produce a second,
   equally-real but redundant transcript.
3. **The full workspace test suite was run, unmodified, before and
   after writing all documentation**, to prove editing/adding
   Markdown files under `docs/tutorial/guide/` and updating
   `ROADMAP.md`/`docs/tutorial/00-overview.md`/`README.md` did not
   touch, and could not have touched, any application code path:
   `libs/contracts` 62 passed, `services/control-plane` 195 passed,
   `services/data-plane` 439 passed, `services/governance-service` 2
   passed — 698 total, unchanged from the count recorded in
   `problems_phase_14.md`.

## Resolved by this phase

- `docs/tutorial/guide/README.md` — the index and orientation document
  explaining Decision 1/2 above to a new reader, with a table mapping
  each of the 20 new chapters to the existing `0X`/`13` chapter (or
  other doc) it links out to for implementation depth, where one
  exists.
- `docs/tutorial/guide/01-what-is-test-data-management.md` through
  `docs/tutorial/guide/20-operating-tdm-as-a-product.md` — twenty new
  chapters, each pointing at real repository code/tests/docs, each with
  at least one small real example and, where a captured terminal
  session is shown, real output from an actual run in this environment
  (see "What is, and is not, tested this phase" above).
- `docs/tutorial/00-overview.md` — new "Where to go next" pointer to
  the new guide, stating explicitly that it is the onboarding path and
  the existing numbered chapters are the implementation-depth
  reference.
- `README.md` — one new line pointing a new reader at
  `docs/tutorial/guide/README.md` alongside the existing
  `docs/tutorial/00-overview.md` link.
- `ROADMAP.md` — Phase 15 marked **Complete** in the phase index table,
  and a new "Phase 15 — what was actually delivered" section added
  immediately above the existing "Phase 14 — what was actually
  delivered" section (most-recent-phase-first ordering, matching every
  other phase transition in that file).

## Left open

- **P15-1 (open, by design)** — This phase does not retroactively add a
  numbered `docs/tutorial/10-...md`/`11-...md`/`12-...md`/`14-...md`
  implementation-depth chapter for Phases 10-12/14 (centralized masking
  governance already has `09-centralized-masking-governance.md`;
  platform integrity, CI/CD, cloud testing, and scale/performance do
  not have a dedicated numbered chapter, only `docs/PLATFORM_INTEGRITY.md`,
  `docs/AZURE_PRODUCTION_DEPLOYMENT.md`, and
  `docs/SCALE_AND_PERFORMANCE.md`). The new `guide/16-platform-integrity.md`,
  `guide/17-ci-cd.md`, and `guide/18-cloud-testing.md` chapters link out
  to those existing docs directly rather than to a numbered tutorial
  chapter that does not exist — filling that specific gap (a dedicated
  `docs/tutorial/1X-...md` deep dive matching the `01-09`/`13` house
  style for Phases 10-12/14) was out of this phase's scope, which is the
  20-chapter onboarding arc the promptbook names, not a retroactive
  pass over earlier phases' documentation gaps.
- **P15-2 (open, by design)** — Chapter 20 ("Operating TDM as a
  product") is, by construction (see Decision 3 above), a synthesis
  across five phases' worth of real material rather than a single
  module's documentation. A future phase that builds a genuine
  "operate TDM as a product" capability (e.g. a unified operator
  dashboard or SLO/on-call runbook spanning refresh, capacity,
  governance, integrity, and audit evidence in one place) should treat
  this chapter as the current honest baseline to extend, not as
  evidence such a unified capability already exists in code today.
- **P15-3 (open, by design)** — No Mermaid diagram added by this phase
  has been rendered to a static image, consistent with the
  already-open `P0-4` in `problems_master.md` (diagrams are Mermaid
  source only, rendered natively by GitHub's Markdown viewer).
