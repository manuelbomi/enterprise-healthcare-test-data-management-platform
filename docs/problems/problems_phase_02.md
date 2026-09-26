# Problems — Phase 2 (PHI/PII Discovery and Classification)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process.
Written before implementation began, updated as work proceeded. Resolved
entries are removed (not marked resolved) once fixed and tested; anything
left below at the end of the phase is a genuine open issue for a later
phase to pick up. Design decisions made *while* resolving anticipated
risks are recorded in the relevant ADR/docstring/limitations doc instead
of here, so this file stays a live list of what's actually still wrong —
see `docs/adr/0009-catalog-artifact-handoff.md` (how the control plane
reads the catalog without importing data-plane internals) and
`libs/contracts/src/healthcare_tdm_contracts/classification.py` (how the
six-label `SensitivityCategory` relates to the existing four-tier
`ClassificationTier`) for that history.

## Open problems

### P2-1 — Pattern detectors cannot tell "whose" identifier a column is

- **Status:** open (by design; documented, not a defect)
- **Description:** A name-based detector for `npi` cannot tell, from the
  column name alone, whether a given NPI column belongs to a `Provider`/
  `Pharmacy` (business/professional identifier) table or, in a different
  source system, would belong to a person acting in a different role. The
  engine gets this right for the actual Phase 1 estate only because the
  schema-based layer (which *does* know the owning entity) takes
  precedence over the pattern layer for every column that is a literal
  field of one of the 14 known domain entities — an unknown/novel source
  system without a schema entry would fall back to the pattern layer's
  weaker, context-free guess.
- **Repro / detail:** N/A — structural limitation of name/pattern
  matching, not reproducible as a bug. See
  `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`, "No semantic/contextual
  understanding."
- **Affected files:**
  `services/data-plane/src/data_plane/discovery/pattern_rules.py`
- **Owner for resolution:** Not resolvable by pattern matching alone;
  would need an Expert Determination-style human review process or a much
  richer entity-resolution model. Out of scope for what this phase
  honestly claims (automated triage + mandatory human confirmation below
  a confidence threshold, per `DATA_GOVERNANCE.md` B.1).

### P2-2 — Free-text/narrative fields are not modeled in the Phase 1 estate

- **Status:** open (out of scope for this phase; flagged for later)
- **Description:** None of the 14 Phase 1 entities contain a free-text
  clinical note field (e.g., "chief complaint," "clinical note"). Real
  EHR extracts commonly do, and free text is exactly where pattern/regex
  PHI detection is weakest — a note field can contain an embedded name,
  MRN, or diagnosis in prose that no column-name or simple value-regex
  heuristic reliably catches. Because the estate doesn't have such a
  field, this phase's engine has not been exercised against that failure
  mode, even though `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` names it
  as the single biggest reason this is not a HIPAA-compliance guarantee.
- **Repro / detail:** N/A — gap in test coverage caused by a gap in the
  underlying synthetic estate, not a bug to reproduce.
- **Affected files:**
  `services/data-plane/src/data_plane/reference_data/domain.py` (would
  need a free-text field added to some entity),
  `services/data-plane/src/data_plane/discovery/`
- **Owner for resolution:** A later phase (or Phase 1 addendum) that adds
  a free-text field to the reference estate, plus a discovery-engine
  enhancement (NLP/NER-based detection) — explicitly out of scope for a
  regex/schema-based engine per this phase's own honesty requirement.

### P2-3 — Catalog does not version per-batch/per-schema-variant datasets

- **Status:** open (deferred design tradeoff)
- **Description:** The claims Parquet dataset (`claim`) has two on-disk
  batches with different schemas (legacy `paid_amount` vs. current
  `amount_paid` + `adjustment_reason_code` — see
  `reference_data/writers/parquet_writer.py`). The catalog represents
  both variants' columns under a single logical dataset name (`claim`)
  rather than as two distinct versioned dataset shapes. This is accurate
  (both columns really do exist somewhere in the `claim` dataset) but
  coarser than a production catalog, which would usually track schema
  versions explicitly.
- **Repro / detail:** Generate a `tiny`-scale estate and run discovery
  (see `services/data-plane/src/data_plane/discovery/README.md`), then
  inspect the produced `catalog.json` for `dataset == "claim"`: both
  `paid_amount` and `amount_paid`/`adjustment_reason_code` appear as
  separate column rows under the same dataset name.
- **Affected files:**
  `services/data-plane/src/data_plane/discovery/catalog_builder.py`
- **Owner for resolution:** A later phase that adds explicit dataset
  versioning to the catalog model — ties naturally into the
  snapshot/refresh work in `ROADMAP.md` Phase 7 (dataset lifecycle).

### P2-4 — Catalog handoff between planes is a JSON artifact, not the metadata-plane DB

- **Status:** open (deliberately deferred; interim design per ADR-0009)
- **Description:** The control plane reads the catalog from a JSON file
  the data-plane discovery CLI writes to disk
  (`TDM_CONTROL_PLANE_CATALOG_PATH`), not from the real metadata-plane
  PostgreSQL schema described in `ADR-0004`. That schema doesn't exist yet
  — `services/control-plane/src/control_plane/db/` is still an empty
  scaffold, and standing up Postgres (`infra/docker-compose`) is Phase 4
  work. The artifact handoff is a deliberate, documented interim
  mechanism (see `docs/adr/0009-catalog-artifact-handoff.md`), not an
  oversight, but it means there is currently no locking/concurrency story
  if two discovery runs write the file at once, and no query filtering
  beyond what the control plane does in memory after loading the whole
  file.
- **Repro / detail:** N/A — works as designed for a single-writer,
  single-reader local/dev setup; would need rework before a concurrent
  multi-writer production deployment.
- **Affected files:**
  `services/data-plane/src/data_plane/discovery/catalog_builder.py`,
  `services/control-plane/src/control_plane/catalog/repository.py`
- **Owner for resolution:** Whichever later phase stands up the real
  metadata-plane PostgreSQL schema and migrates the classification store
  there per `DATA_GOVERNANCE.md` B.1 ("tracked in the metadata plane's
  classification store").
