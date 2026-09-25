# Roadmap

This repository is built as a **21-phase promptbook-driven project** (Phase 0
through Phase 17, split fix/delete cycles 18A/18B, and a Final release
phase). Each phase is scoped to be independently completable, testable, and
documented before the next begins. Phases are not sprints with fixed dates —
they are ordered units of work. A phase is not "done" until its required
tests pass (see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the per-phase
process).

This file tracks the *plan*. Day-to-day open issues live in
[`problems_master.md`](problems_master.md). The exact phase prompts this
roadmap follows come from the private planning document that seeded this
project; the table below is the authoritative phase order and scope for this
repository going forward.

## Phase index

| Phase | Theme | Status |
|---|---|---|
| 0 | Repository operating rules, architecture, conventions, ADRs, scaffolding | **Complete** |
| 1 | Synthetic healthcare data estate across 5 heterogeneous source systems | **Complete** |
| 2 | PHI/PII discovery and classification engine + data catalog | **Complete** |
| 3 | Enterprise deterministic masking engine (pseudonymization/tokenization) | **Complete** |
| 4 | Referentially intact, production-scale data subsetting | **Complete** |
| 5 | Synthetic test data generation (scenario/edge-case data) | **Complete** |
| 6 | Certified test dataset pipeline (ingest→...→certify→publish) | Not started |
| 7 | Dataset lifecycle and refresh management (versions, cadence, retention) | Not started |
| 8 | Storage and compute footprint management / capacity planning | Not started |
| 9 | React/TypeScript enterprise TDM web console | Not started |
| 10 | Centralized enterprise masking standard (multi-business-unit governance) | Not started |
| 11 | Platform integrity (health, resiliency, failure injection) | Not started |
| 12 | Production CI/CD and cloud testing (GitHub Actions, K8s, Terraform) | Not started |
| 13 | Auditability and compliance evidence | Not started |
| 14 | Scale and performance engineering (PySpark benchmarks) | Not started |
| 15 | Complete junior-engineer tutorial (20 chapters) | Not started |
| 16 | Interview / system design documentation | Not started |
| 17 | Principal-engineer production readiness review (findings only, no fixes) | Not started |
| 18A | Fix/delete cycle for P0/P1 findings from Phase 17 | Not started |
| 18B | Fix/delete cycle for P2/P3 findings from Phase 17 | Not started |
| Final | Recruiter/interviewer-ready release (README rewrite, demo, checklist) | Not started |

## Phase 5 — what was actually delivered

- A real synthetic *scenario* generator
  (`services/data-plane/src/data_plane/synthetic/`) that supplements an
  already-subsetted-and-masked estate (or produces a standalone dataset)
  with deliberately constructed test scenarios, reusing Phase 4's
  `estate_io.py` read path and `writer.py` write path rather than
  reinventing them — distinct from Phase 1's `reference_data` package,
  which builds an entire estate from nothing and injects its own edge
  cases as part of that build (Phase 5 only ever augments/supplements,
  one pipeline stage later per `ARCHITECTURE.md`)
- All eleven required scenarios, implemented as real, distinct generator
  functions (`data_plane/synthetic/scenarios.py`) producing either
  schema-valid records (`normal_claims`, `high_cost_claims`,
  `unusual_prescription_combinations`, `missing_laboratory_values`,
  `boundary_dates`, `null_heavy_records`, `very_large_claim_histories`)
  or deliberately, specifically broken ones
  (`duplicate_claims`, `invalid_claim_references`, `expired_coverage`,
  `missing_provider`), each demonstrated against a real generated
  estate — see `docs/tutorial/05-synthetic-scenario-generation.md`
- `healthcare_tdm_contracts.DataProvenance` (`masked_production_like` /
  `synthetic` / `negative_test`): the vocabulary that makes "never allow
  synthetic records to be mistaken for real records" concrete, tagged
  **both** per-row (`data_provenance` column, added to every row across
  all five on-disk formats, including retagging every pre-existing base
  row `masked_production_like` when augmenting) and per-manifest
  (`SyntheticGenerationManifest.provenance_row_counts`) — see
  `data_plane/synthetic/provenance.py` for why neither alone is
  sufficient
- A scenario-sub-range ID convention
  (`data_plane/synthetic/ids.ScenarioIdAllocator`): scenario-generated
  entities use `SYN-<ENTITY>-SCEN-<seq>`, which cannot collide with
  Phase 1 estate-native `SYN-<ENTITY>-<seq>` IDs by construction;
  negative-test dangling references use the further-distinguished
  `SYN-<ENTITY>-SCEN-NX-<tag>-<seq>` shape
- Extended `libs/contracts`: `DataProvenance`, `ScenarioType` (the eleven
  scenarios), `ScenarioGenerationRecord`, `SyntheticGenerationManifest` —
  the durable, typed record of a generation run's mode (augment/
  standalone), lineage back to a Phase 4 `SubsetManifest` when one
  exists, per-scenario counts, and the full provenance rollup
  (`libs/contracts/src/healthcare_tdm_contracts/synthetic.py`)
- Both augment mode (reads an existing masked/subsetted estate, tags its
  rows, merges scenarios on top) and standalone mode (generates a small
  self-contained reference-table fixture set first, zero
  `masked_production_like` rows in the output by construction) run end
  to end against a real generated `tiny`-scale estate and a real Phase 4
  subset of it
- 85 new tests (62 in `services/data-plane`, 5 new in `libs/contracts`
  on top of the 18 already there) — see `problems_phase_05.md` for what's
  still open

## Phase 4 — what was actually delivered

- A real subsetting engine
  (`services/data-plane/src/data_plane/subsetting/`) that selects a
  referentially closed population from the real Phase 1 estate, anchored
  at `Member`, and pulls every related row across all five simulated
  source systems (`estate_io.py` reads, `closure.py` graph-walks,
  `writer.py` writes back in the same multi-format shape) — the same
  "read the real multi-format estate, do something per-row, write a new
  estate" pattern Phase 3's `dataset_masker.py` established
- All six required sizing strategies
  (`healthcare_tdm_contracts.SubsettingStrategy`), implemented as real,
  working code and each demonstrated against the real generated estate:
  `percentage`, `fixed_population`, `stratified`, `date_window`,
  `business_rule`, `risk_edge_case` (`data_plane/subsetting/selection.py`)
- Extended `libs/contracts`:
  `SubsettingStrategy`, `IntegrityStatus`, `SubsetSelectionCriteria`,
  `RelationshipEdge`, `SubsetManifest` — the durable, typed record of a
  subsetting run's source counts, selected counts, relationship edge
  counts, filter criteria, timestamp, version, estimated storage, and
  integrity status
- A three-way orphan classification
  (`data_plane/subsetting/closure.py`'s `DanglingReference.category`)
  that distinguishes a pre-existing Phase 1 source orphan (reachable from
  a real selected member, carried through and reported) from a genuine
  engine bug (an id that existed in the source but was dropped by the
  subsetting logic itself — verified never to happen against the real
  estate) from an intentional negative-test injection
  (`data_plane/subsetting/negative_testing.py`, opt-in only) — see
  `docs/tutorial/04-subsetting-and-referential-closure.md` for the full
  "reachable vs. unreachable orphans" explanation
- Population size/percentage is fully runtime-configurable (never
  hardcoded); the same code path demonstrated at `tiny` scale is what
  would run unmodified against a real `performance`-scale estate for a
  real 10,000-member subset (not yet benchmarked at that scale — see
  `problems_phase_04.md` P4-3)
- 61 new tests (57 in `services/data-plane`, 4 in `libs/contracts`) — see
  `problems_phase_04.md` for what's still open

## Phase 3 — what was actually delivered

- A real, policy-driven masking engine
  (`services/data-plane/src/data_plane/masking/`) implementing eleven
  masking techniques: redaction, nullification, unkeyed hashing,
  HMAC-based deterministic pseudonymization, a `TokenVault` tokenization
  abstraction (with a stateless HMAC-derived default and a demonstration
  stored-random-token alternative), format-preserving synthetic
  replacement, date shifting, and named specializations for email,
  phone, address, and name fields
- Extended `libs/contracts` masking shapes: `MaskingTechnique`,
  `MaskingFieldType`, and new optional `MaskingRule` fields
  (`field_pattern`, `technique`, `field_type`, `preserve_format`,
  `preserve_null`, `preserve_linkage`), additive and backward-compatible
  with the Phase 0 `MaskingStrategy`/`MaskingRule` shapes Phase 2's
  catalog already depends on — see
  [ADR-0010](docs/adr/0010-masking-technique-vocabulary.md)
- A cross-system linkage-scope table
  (`data_plane/masking/policy.LINKAGE_SCOPES`) that is the actual
  mechanism behind this phase's core requirement: a member identifier
  masks to the identical token everywhere it appears, including under
  the partner feed's legacy `pat_id` alias for the same field
- An HMAC secret key management story with no hardcoded/committed key
  anywhere: `TDM_MASKING_HMAC_KEY` env var, a gitignored `.env` fallback,
  and a `--generate-dev-key` CLI helper that never writes a key to disk
  — enforced by an automated test that scans the git-tracked (and
  about-to-be-tracked) source tree for leaked secrets
- Run end to end against the real Phase 1 synthetic estate using the
  real Phase 2 catalog to decide which technique masks which column
  (`python -m data_plane.masking.cli`), producing a masked copy of the
  `tiny` scale profile with a real member ID verified to map to the same
  masked token across Postgres, Parquet, the S3-style NDJSON clinical
  lake, and the ADLS-style CSV PBM extract (and the partner feed, under
  its `pat_id` alias)
- Masking validation (`data_plane/masking/validation.py`): referential
  integrity, no-raw-value-leakage, and token-collision checks — a
  lighter-weight precursor to the full certification pipeline
  (`ROADMAP.md` Phase 6), not a replacement for it (see
  `problems_phase_03.md` P3-1)
- 101 new tests in `services/data-plane` (210 total across the four
  Python workspace packages) covering determinism, collision handling,
  referential integrity, null handling, malformed values, idempotency,
  and secret absence — see `problems_phase_03.md` for what's still open

## Phase 2 — what was actually delivered

- A configurable, three-layer PHI/PII classification engine
  (`services/data-plane/src/data_plane/discovery/`): schema-based
  (every field of all 14 Phase 1 entities, explicitly), rule-based
  (column-name/value pattern detectors), and manual override (steward
  corrections, signed with a `confirmed_by` identity), combined with a
  documented precedence order and DATA_GOVERNANCE.md B.1's
  conservative-default rule for unrecognized columns
- Extended `libs/contracts` classification/catalog shapes:
  `SensitivityCategory` (6 labels), `ClassificationMethod`, `CatalogEntry`,
  `RetentionClassification`, built on top of (not duplicating) the
  existing Phase 0 `ClassificationTier`/`ColumnClassification`
- Run against the real, generated Phase 1 estate (not just the schema):
  a scanner (`discovery/scanner.py`) reads the actual SQLite/Parquet/
  NDJSON/CSV/partner files and catches real schema-drift columns
  (`amount_paid`, `adjustment_reason_code`, `pat_id`, `test_cd`, ...) a
  schema-only classifier would miss
- A data catalog (classification + masking requirement + source + owner +
  retention classification per column), produced as a JSON artifact and
  served read-only by the control plane
  (`GET /api/v1/catalog`, `/catalog/summary`, `/catalog/datasets`,
  `/catalog/{source_system}/{dataset}/{column}`) — see
  [ADR-0009](docs/adr/0009-catalog-artifact-handoff.md) for the
  plane-separation-respecting handoff design
- `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`: an honest account of what
  pattern/schema-based classification can and cannot prove (no free-text/
  NLP coverage, no semantic understanding, no combination/re-identification
  risk scoring) — this is explicitly not presented as a HIPAA compliance
  guarantee
- Tests across both affected packages (`libs/contracts`,
  `services/data-plane`, `services/control-plane`) — see
  `problems_phase_02.md` for what's still open

## Phase 1 — what was actually delivered

- A completely synthetic, multi-system healthcare data estate: Member,
  MemberDemographics, Address, Coverage, Plan, Provider, Claim, ClaimLine,
  Diagnosis, Procedure, Prescription, Pharmacy, Encounter, LabResult
- Distributed across 5 simulated heterogeneous sources: PostgreSQL-shaped
  (SQLAlchemy models), Parquet object storage, S3-compatible NDJSON,
  Azure/ADLS-compatible CSV, and an external partner file/API feed
- 4 configurable scale profiles (tiny/developer/qa/performance) and required
  edge cases (nulls, duplicates, orphans, malformed values, late-arriving
  data, schema drift), each guaranteed present and covered by tests
- See `services/data-plane/src/data_plane/reference_data/README.md` and
  `docs/tutorial/02-synthetic-data-estate.md` for details

## Phase 0 — what was actually delivered

- Repository structure across six architectural planes
- `ARCHITECTURE.md` describing the system, its planes, and their interfaces
- ADRs recording the foundational technical decisions (`docs/adr/`)
- `SECURITY.md`, `THREAT_MODEL.md`, `DATA_GOVERNANCE.md`, `CONTRIBUTING.md`
- `docs/tutorial/`, `docs/runbooks/`, `docs/diagrams/` seeded with real content
- `problems_master.md` established as the live problem-tracking process
- Empty/scaffold Python packages for `control-plane`, `data-plane`,
  `governance-service`, and the shared `contracts` library, each with a
  `pyproject.toml` and a documented purpose but no business logic
- Empty/scaffold React + TypeScript + Vite frontend
- Docker Compose, Terraform, and Helm scaffolding (structure only, not wired
  to real infrastructure yet)
- GitHub Actions CI workflow skeleton

## Non-goals for Phase 0

- No working application. Nothing here should be expected to run end to end.
- No real database migrations, no real masking logic, no real UI screens.
- No dependency installation was run (`pip install` / `npm install`) — config
  files are in place so a later phase can do this deliberately, once there is
  something worth installing dependencies for.
