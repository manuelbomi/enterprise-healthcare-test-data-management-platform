# Problems — Phase 9 (React/TypeScript Enterprise TDM Web Console)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before/during implementation, updated as work proceeded,
resolved entries removed once fixed and tested. Anything left below at
the end of the phase is a genuine open issue for a later phase.

## Per-page build-vs-placeholder decisions

The Phase 9 prompt explicitly asked for an honest, page-by-page call:
add a small new read-only control-plane endpoint where an artifact
already exists and the effort is low, or build an honest "not yet
available" placeholder where it isn't. Recorded here so the reasoning
survives independently of the code:

- **Masking Policies, Subsetting Jobs, Synthetic Data, Certification** —
  added new endpoints. Phases 3/4/5/6 are real, tested, working engines
  that already write a well-typed JSON artifact per run
  (`masking_run_summary.json`, `subset_manifest.json`,
  `synthetic_generation_manifest.json`, `certification_report.json`).
  Three of the four (`SubsetManifest`, `SyntheticGenerationManifest`,
  `CertificationReport`) were *already* real `libs/contracts` Pydantic
  models — reading and serving them cost nothing beyond a thin
  repository + router, following ADR-0009's exact pattern. The fourth
  (masking) has no `libs/contracts` shape (`MaskingRunReport` is a
  data-plane-local `@dataclass`); rather than promote it into
  `libs/contracts` (a bigger, cross-cutting change out of this phase's
  scope) a small control-plane-local mirror model
  (`control_plane.artifacts.masking.MaskingRunSummary`) was added
  instead, matching the exact JSON shape both `data_plane.masking.cli`
  and `data_plane.certification.pipeline` already write. See P9-1 below
  for the tracked follow-up.
- **Data Sources, Sensitive Data Discovery** — no new endpoint needed.
  Both are different aggregations/filters over the real, already-served
  Phase 2 catalog (`GET /api/v1/catalog`, `/catalog/datasets`).
- **Audit Trail** — honest placeholder (`NotYetAvailable` component).
  `ROADMAP.md` Phase 13 owns this; there is no security/governance-plane
  audit event log to read from at all (`ARCHITECTURE.md` section 2.4 is
  a design target, not built).
- **Platform Health** — wired to the real (if minimal) root health
  endpoint (`GET /api/v1/health`, liveness only, Phase 0). The page's
  own copy says explicitly that this is liveness-only and that full
  platform integrity (dependency-aware readiness, failure injection) is
  `ROADMAP.md` Phase 11, not yet built — it does not pretend to be more
  than it is.
- **Environment Provisioning, Refresh Calendar, Capacity & Cost,
  Datasets, Dataset Detail** — all backed by real, already-existing
  Phase 7/8 endpoints; no new endpoints needed. These pages are
  read-only views; in-console write workflows (request/refresh/rollback
  from the UI, not just via the API) are out of this phase's scope — see
  P9-2.

## Open problems

### P9-1 — Masking run summary has no shared `libs/contracts` shape

- **Phase:** 9
- **Status:** open
- **Description:** `control_plane.artifacts.masking.MaskingRunSummary`
  is a control-plane-local Pydantic model that mirrors (by hand) the
  exact JSON shape `data_plane.masking.cli.main` and
  `data_plane.certification.pipeline._write_masking_summary` write.
  Unlike subsetting/synthetic/certification, there is no shared
  `libs/contracts` type for a masking run summary
  (`data_plane.masking.dataset_masker.MaskingRunReport` is a
  data-plane-local `@dataclass`, never promoted to a contract). If the
  JSON shape either writer produces ever changes, `MaskingRunSummary`
  must be updated by hand and could silently drift.
- **Repro / detail:** Compare
  `services/control-plane/src/control_plane/artifacts/masking.py`'s
  `MaskingRunSummary` fields against the `json.dumps({...})` call in
  `services/data-plane/src/data_plane/masking/cli.py`'s `main` and
  `services/data-plane/src/data_plane/certification/pipeline.py`'s
  `_write_masking_summary` — they must stay in lockstep by convention,
  not by a shared type.
- **Affected files:**
  `services/control-plane/src/control_plane/artifacts/masking.py`,
  `services/data-plane/src/data_plane/masking/cli.py`,
  `services/data-plane/src/data_plane/certification/pipeline.py`
- **Owner for resolution:** Not currently scheduled by name. A future
  phase promoting `MaskingRunReport`/its JSON summary shape into
  `libs/contracts` (mirroring `SubsetManifest`) would close this
  cleanly and let `frontend/src/api/types.ts`'s `MaskingRunSummary`
  interface be regenerated/verified against it too (Phase 19's
  contract-testing concern, per `docs/adr/0008-frontend-stack.md`).

### P9-2 — Console is read-only; no in-UI write workflows

- **Phase:** 9
- **Status:** open (deliberately out of scope)
- **Description:** Every page in this console reads real data; none of
  them offer a form to request a dataset into an environment, trigger a
  refresh, roll back, revoke a version, or register a masking policy
  change from the browser. All of that is fully exercised at the API
  layer (`services/control-plane/tests/test_lifecycle_api.py`,
  `scripts/demo_phase7_lifecycle.py`) — this phase's scope (per the
  prompt) was the console's *screens*, not a write-workflow UI on top of
  already-real write endpoints.
- **Repro / detail:** N/A — a UI gap, not a bug. `POST
  /api/v1/lifecycle/environment-requests/{id}/refresh`, `/rollback`, and
  `POST /api/v1/lifecycle/dataset-versions/{id}/revoke` all work today
  via the API; there is simply no button for them yet.
- **Affected files:** `frontend/src/pages/EnvironmentProvisioningPage.tsx`,
  `frontend/src/pages/DatasetDetailPage.tsx`
- **Owner for resolution:** Not currently scheduled by name — a natural
  fit for a later UI-polish pass once the write-workflow UX (confirmation
  dialogs, optimistic updates, RBAC-gating once the governance plane
  exists) is itself in scope.

### P9-3 — New artifact repositories inherit ADR-0009's concurrency/scan-cost caveats, and add one more (multi-run scanning)

- **Phase:** 9
- **Status:** open (expected — same tradeoff ADR-0009 already accepted)
- **Description:** `control_plane.artifacts.{masking,subsetting,synthetic,
  certification}` each do an unbounded `Path.rglob(<filename>)` over the
  configured root directory on *every* request (no caching, unlike
  `CatalogRepository`'s lazy-load-and-cache-until-`reload()` pattern) —
  correct and adequate for a local/dev/portfolio-scale artifact root (a
  few dozen runs at most), but would not scale to a root directory with
  thousands of historical runs, and has no locking story for a
  concurrent writer (the same gap ADR-0009 documents for the catalog).
- **Repro / detail:** Point `TDM_CONTROL_PLANE_CERTIFICATION_ARTIFACTS_ROOT`
  (or any of the other three) at a directory with many thousands of
  nested `certification_report.json` files and observe per-request
  latency grow linearly with artifact count.
- **Affected files:**
  `services/control-plane/src/control_plane/artifacts/*.py`
- **Owner for resolution:** Not currently scheduled by name — tracked
  alongside ADR-0009's own open item (`problems_phase_02.md` P2-4:
  superseded once the metadata plane's real PostgreSQL schema exists
  and lifecycle registration becomes the single source of truth for
  "what runs exist," at which point these directory scans become
  unnecessary rather than needing to be optimized).

### P9-4 — Dataset Detail's "source systems" is deliberately not a precise per-version lineage edge

- **Phase:** 9
- **Status:** open (documented limitation, not a bug)
- **Description:** No artifact in this platform records which of the
  five simulated source systems contributed rows to one specific
  `DatasetVersion` — `SubsetManifest` records per-*entity* row counts
  (`source_counts`/`selected_counts`), not per-*source-system* counts.
  `DatasetDetailPage`'s "Source systems" section says this explicitly
  and links to the Data Catalog rather than fabricating a lineage edge
  that doesn't exist.
- **Repro / detail:** N/A — see
  `frontend/src/pages/DatasetDetailPage.tsx`'s module docstring and its
  "Source systems" section copy for the honest statement.
- **Affected files:** `frontend/src/pages/DatasetDetailPage.tsx`,
  `libs/contracts/src/healthcare_tdm_contracts/subsetting.py`
- **Owner for resolution:** Not currently scheduled by name — would
  require `SubsetManifest` (or a new artifact) to record per-source-
  system provenance during subsetting, a data-plane change out of this
  phase's scope.

### P9-5 — `frontend/src/api/types.ts` is hand-maintained, not generated

- **Phase:** 9
- **Status:** open (pre-existing, tracked since Phase 0/ADR-0008)
- **Description:** Every TypeScript interface in `types.ts` was written
  by hand, field-for-field, against the current `libs/contracts` Pydantic
  models. There is no automated check that they stay in sync if a Python
  contract changes.
- **Repro / detail:** Change a field name/type in, e.g.,
  `libs/contracts/src/healthcare_tdm_contracts/capacity.py`'s
  `CapacityPlan`, and nothing in either test suite will fail until a
  human notices the frontend rendering `undefined`.
- **Affected files:** `frontend/src/api/types.ts`, every
  `libs/contracts` module it mirrors.
- **Owner for resolution:** `ROADMAP.md` Phase 19 (contract testing),
  per `docs/adr/0008-frontend-stack.md`'s own "Consequences" section
  (unchanged by this phase).

## Environment note (verification, not a product defect)

While verifying live data flow (control plane + Vite dev server +
Playwright against a real browser), this sandboxed development
environment was found to intercept any HTTP request whose path starts
with `/api` on a locally-forwarded frontend dev-server port, regardless
of which process actually owns that port — confirmed with both `curl`
and a real Chromium instance launched by Playwright, and confirmed to
be specific to the dev-server port rather than the control plane's own
port (direct requests to the control plane's own port were never
affected). This is a property of the sandbox this phase was built in,
not of the application. It was worked around, without changing the
application's real `/api/v1` route prefix (used throughout the backend,
every prior phase's tests, and this repository's documentation), by
using the frontend's already-documented `VITE_API_BASE_URL` escape
hatch (`.env.example`) to call the control plane cross-origin directly,
which in turn motivated the one real, permanent, useful addition this
produced: opt-in CORS support
(`TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS`, empty/off by default,
covered by `services/control-plane/tests/test_cors.py`). A real
deployment or a plain local machine without this sandbox's networking
behavior would never need `VITE_API_BASE_URL` or CORS at all — the
default same-origin dev-proxy path (`vite.config.ts`) is untouched and
remains the documented default.

## Resolved problems

_(None yet — this section will list problems that were opened and then
resolved in a later phase, kept briefly for history before being pruned.)_
