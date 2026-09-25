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

### P0-1 — No dependency installation has been performed

- **Phase:** 0
- **Status:** open (deliberately deferred)
- **Description:** `pip install` has not been run for any of the Python
  packages (`services/control-plane`, `services/data-plane`,
  `services/governance-service`, `libs/contracts`), and `npm install` has
  not been run for `frontend/`. Config files (`pyproject.toml`,
  `package.json`) are in place and should be installable, but this has not
  been verified by actually running the install.
- **Repro / detail:** Run `pip install -e .` inside any
  `services/*/` or `libs/contracts/` directory, and `npm install` inside
  `frontend/`. Expected: succeeds cleanly. Not yet verified because Phase 0
  is scaffolding-only per the operating instructions for this build.
- **Affected files:** `services/*/pyproject.toml`, `libs/contracts/pyproject.toml`,
  `frontend/package.json`
- **Owner for resolution:** Phase 1 (metadata plane) and Phase 2 (control
  plane skeleton) should be the first phases to actually install and run
  their respective packages.

### P0-2 — No CI runs have been executed against this repository yet

- **Phase:** 0
- **Status:** open (deliberately deferred)
- **Description:** `.github/workflows/ci.yml` is a skeleton pipeline
  definition. It has not been executed (no GitHub remote/Actions run yet
  exists for this local repository).
- **Repro / detail:** Push this repository to GitHub and confirm the
  workflow triggers and its jobs (currently mostly placeholder steps)
  succeed.
- **Affected files:** `.github/workflows/ci.yml`
- **Owner for resolution:** Phase 18 (CI/CD).

### P0-3 — Storage adapter interface is a design sketch, not an implementation

- **Phase:** 0
- **Status:** open (expected — out of scope for Phase 0)
- **Description:** `libs/contracts` documents the intended storage adapter
  contract in comments/docstrings, but there is no working MinIO, S3, or
  Azure Blob/ADLS adapter yet.
- **Repro / detail:** N/A — no code to exercise yet. Tracked so Phase 5
  starts from a known contract rather than re-deriving it.
- **Affected files:** `libs/contracts/src/healthcare_tdm_contracts/`
- **Owner for resolution:** Phase 5 (object storage abstraction).

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

_(None yet — this section will list problems that were opened and then
resolved in a later phase, kept briefly for history before being pruned.)_
