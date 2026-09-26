# Problems Master

Live index of open problems across all phases. Process defined in
`CONTRIBUTING.md`: every phase writes/updates this file before implementing,
removes problems it resolves, and leaves unresolved problems here with
reproduction details for the next phase to pick up. This file should always
reflect current reality — if a problem below is fixed, delete its entry
rather than marking it "done."

## How to use this file

Each entry should have:

- **ID** — `P<phase>-<n>`, e.g. `P0-1`
- **Phase** — which phase introduced/owns it
- **Status** — `open` or `blocked` (resolved entries are deleted, not
  marked resolved)
- **Description** — what's wrong or missing
- **Repro / detail** — enough detail that someone else could pick this up
  without re-deriving it
- **Affected files**

---

## Open problems

### P0-3 — Storage adapter interface is a design sketch, not an implementation

- **Phase:** 0
- **Status:** open (expected — out of scope for Phase 0)
- **Description:** `libs/contracts` documents the intended storage adapter
  contract in comments/docstrings, but there is no working MinIO, S3, or
  Azure Blob/ADLS adapter yet.
- **Repro / detail:** N/A — no code to exercise yet.
- **Affected files:** `libs/contracts/src/healthcare_tdm_contracts/`
- **Owner for resolution:** Not currently scheduled by name in
  `ROADMAP.md`. (Correction made during Phase 5: this entry previously
  said "Owner: Phase 5 (object storage abstraction)," a stale reference
  to an earlier draft phase order. The current `ROADMAP.md` Phase 5 is
  "Synthetic test data generation," not object storage, and Phase 5's
  own real, on-disk local-filesystem reads/writes -- see
  `services/data-plane/src/data_plane/synthetic/` -- do not touch this
  gap. Every data-plane phase through Phase 5 continues to read/write a
  local filesystem path directly, not through a `StorageBackend` adapter.
  Phase 8, "Storage and compute footprint management / capacity
  planning," was the closest candidate and is now complete -- as
  anticipated, its scope was real footprint *measurement* and *planning*
  (`data_plane.capacity`, `control_plane.domain.capacity`), not
  implementing this adapter; see `docs/problems/problems_phase_08.md` P8-2 for the
  concrete way that gap continues to matter (`CapacityPlanner` still
  trusts caller-supplied `size_bytes` rather than independently
  re-deriving it through a storage adapter). This entry remains open,
  not scheduled by name.)

### P0-4 — Diagrams are Mermaid source only; no rendered/exported images yet

- **Phase:** 0
- **Status:** open
- **Description:** `docs/diagrams/` contains Mermaid `.mmd` source and a
  README explaining the diagram set, but no pre-rendered PNG/SVG exports.
  Mermaid renders natively on GitHub, so this is low priority, but a
  polished portfolio pass may want static exports for contexts that don't
  render Mermaid (e.g., a PDF export of the docs).
- **Repro / detail:** N/A
- **Affected files:** `docs/diagrams/`
- **Owner for resolution:** Phase 22 (hardening / portfolio polish).

---

## Resolved problems

- **P0-1** (`npm install` had not been performed for `frontend/`) --
  resolved in Phase 9: `npm install` now runs cleanly (435 packages),
  and `frontend/` is a real, working, tested console. See
  `ROADMAP.md`'s Phase 9 section and `docs/problems/problems_phase_09.md`.
- **P0-2** (no CI runs had ever been executed against this repository)
  -- resolved in Phase 12: `.github/workflows/ci.yml` was rewritten
  into real lint/typecheck/unit/integration/data-quality/security/
  frontend jobs plus a release-gate job, and actually triggered and
  observed running on GitHub Actions, including a real, deliberate
  failure that was confirmed to block the release gate before being
  reverted. This also resolves the related "Postgres never verified
  against real application code" gap `ARCHITECTURE.md`'s Phase 7/8/11
  notes independently flagged: `infra/docker/docker-compose.yml` now
  runs a real control-plane container against a real Postgres
  container, and `GET /api/v1/ready` reports the database reachable.
  See `ROADMAP.md`'s Phase 12 section and `docs/problems/problems_phase_12.md` for
  the full account, including the real workflow run IDs/URLs.
