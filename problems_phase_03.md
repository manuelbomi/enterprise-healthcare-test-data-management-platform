# Problems — Phase 3 (Enterprise Data Masking)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before implementation began (this initial version), updated as
work proceeded, resolved entries removed once fixed and tested. Anything
left below at the end of the phase is a genuine open issue for a later
phase. Design decisions made while resolving anticipated risks are
recorded in `libs/contracts/src/healthcare_tdm_contracts/masking.py`
docstrings, `docs/adr/0006-deterministic-masking-strategy.md`, and
`services/data-plane/src/data_plane/masking/README.md` instead of here.

## Risks identified before implementation, and how they were resolved

Written before implementation began, per `CONTRIBUTING.md` step 2; kept
here (rather than deleted) as the record of what was anticipated versus
what actually happened, since every one of these was successfully
resolved and is now verified by a real, passing test:

- **Extending `MaskingStrategy`/`MaskingRule` without breaking the
  existing 4-value contract** Phase 2's catalog already depends on.
  Resolved: added additive vocabulary (`MaskingTechnique`,
  `MaskingFieldType`) and new *optional* `MaskingRule` fields; the
  existing 4 `MaskingStrategy` values and `MaskingRule.tier`/`scope` are
  unchanged. `services/data-plane/tests/discovery/test_catalog_builder.py`
  (Phase 2's own test suite) still passes unmodified. See
  [ADR-0010](docs/adr/0010-masking-technique-vocabulary.md).
- **HMAC key management** must never hardcode or commit a key. Resolved:
  `TDM_MASKING_HMAC_KEY` env var, gitignored `.env` fallback, a
  `--generate-dev-key` CLI helper that never writes to disk, and
  `services/data-plane/tests/masking/test_no_secrets_committed.py`,
  which scans the actual git-tracked (and about-to-be-tracked) source
  tree.
- **Referential integrity across all 5 heterogeneous source systems**
  requires the *same* scope string for every column alias that carries
  the same real-world identifier (`member_id` in 4 systems, `pat_id` in
  the partner v1 legacy feed). Resolved:
  `data_plane.masking.policy.LINKAGE_SCOPES`, verified end to end
  against a real generated estate in
  `test_dataset_masker_against_real_estate.py` (not just synthetic unit
  fixtures) — a real member ID was confirmed to mask identically across
  Postgres, Parquet, NDJSON, and CSV, and a real partner-feed record was
  confirmed to match its Postgres counterpart under the `pat_id`/
  `member_id` alias.
- **Format-preserving synthetic replacement** needed to look plausible
  while staying deterministic/idempotent. Resolved: a shared `Faker`
  instance reseeded per call from the HMAC digest of `(scope, value)`,
  never from Python's global RNG — verified by
  `test_synthesizers.py::test_calling_synthesize_repeatedly_does_not_perturb_unrelated_calls`.
- **Date shifting on the estate's real malformed date-like strings**
  (`edge_cases.py`, `malformed_value_rate`) must not crash. Resolved:
  unparsable input is redacted (`INVALID_DATE_MARKER`) with a recorded
  `MaskingWarning`, tested directly against the literal `"TBD"` sentinel
  the estate injects.
- **Plain (unkeyed) `HASHING`** is a required technique but a
  known-weak pattern per ADR-0006. Resolved: implemented (never as the
  default for `DIRECT_IDENTIFIER`), and
  `test_masking_engine.py::test_hashing_technique_never_uses_the_key_and_is_therefore_dictionary_attackable`
  builds a real 10,000-candidate dictionary attack that succeeds against
  it and fails against the keyed `HMAC_PSEUDONYMIZATION` technique.
- **Five different I/O paths** (SQLite, Parquet, NDJSON, CSV, two
  partner shapes) each needing to mirror their source layout in the
  masked output. Resolved: a generic `mask_row_dict` used by every
  per-source-system writer in `dataset_masker.py`, mirroring
  `discovery/scanner.py`'s per-system function shape.

## Open problems

### P3-1 — Masking certification here is intentionally partial

- **Status:** open (deliberately deferred; scoped to this phase's own
  requirement, "implement masking validation")
- **Description:** `data_plane/masking/validation.py` checks the things
  this phase's promptbook explicitly asks for (no raw direct-identifier
  values leak into masked output, referential integrity holds across the
  masked estate, no masked-token collisions, idempotency across two
  runs). It is **not** the full "Certified test dataset pipeline"
  (`ROADMAP.md` Phase 6: ingest -> ... -> certify -> publish), which
  needs distribution-shape tolerance checks, a durable certification
  evidence record in the governance plane, and a publish gate — none of
  which exist yet.
- **Repro / detail:** N/A — scope boundary, not a bug. See
  `ARCHITECTURE.md` section 2.2 ("Certification ... implemented as an
  independent verifier") for why later-phase certification must not
  simply trust this module's own report.
- **Affected files:** `services/data-plane/src/data_plane/masking/validation.py`
- **Owner for resolution:** Phase 6 (certified test dataset pipeline).

### P3-2 — Token vault is in-memory/demo only, not a governed vault service

- **Status:** open (deliberately deferred; consistent with ADR-0006)
- **Description:** `data_plane/masking/token_vault.py` provides a
  `TokenVault` abstraction with a default deterministic (HMAC-derived,
  stateless) implementation and a demo `InMemoryRandomTokenVault` that
  shows the alternative "store a random token + real value" approach.
  Neither is a durable, access-controlled vault owned by the
  security/governance plane. ADR-0006 already says the real reverse
  mapping "lives only in a governed token vault owned by the
  security/governance plane" — that service does not exist yet
  (`services/governance-service` is still mostly scaffolding).
- **Repro / detail:** N/A — `InMemoryRandomTokenVault`'s mapping is
  process-local and lost on exit by construction; this is documented in
  its own docstring as demo-only, never used by the default masking
  policy.
- **Affected files:** `services/data-plane/src/data_plane/masking/token_vault.py`
- **Owner for resolution:** A later phase that builds a real vault
  service inside `services/governance-service` (not currently scheduled
  by name in `ROADMAP.md`; tracked here so it isn't forgotten).

### P3-3 — Masking policy is not yet control-plane-managed/versioned in a database

- **Status:** open (deliberately deferred; same shape of problem as
  ADR-0009's catalog handoff)
- **Description:** `data_plane/masking/policy.py`'s `DEFAULT_POLICY` is a
  Python constant, not a control-plane-approved, database-stored,
  versioned policy an operator can edit without a code change. The
  `MaskingPolicy` contract already supports `approved_by`/`version`, but
  nothing today persists or serves policy versions the way ADR-0009
  describes for the catalog.
- **Repro / detail:** N/A — matches Phase 2's own catalog-handoff
  tradeoff; not a regression introduced by this phase.
- **Affected files:** `services/data-plane/src/data_plane/masking/policy.py`
- **Owner for resolution:** Phase 10 (centralized enterprise masking
  standard / multi-business-unit governance) per `ROADMAP.md`.

### P3-4 — Format-preserving synthetic replacement for money amounts is a simple magnitude-preserving heuristic

- **Status:** open (documented limitation, not a defect)
- **Description:** `synthesizers.py`'s numeric path derives a
  deterministic pseudo-random number of the same order of magnitude as
  the original (so a masked `billed_amount` still looks like a plausible
  dollar figure), but it does not attempt to preserve the *statistical
  distribution* of amounts across the dataset (mean, variance, realistic
  clustering around common billed amounts) — only per-value plausibility.
- **Repro / detail:** Mask a `tiny`-scale estate and compare the
  distribution of masked `billed_amount` to the original; they will not
  match closely beyond "same rough order of magnitude."
- **Affected files:** `services/data-plane/src/data_plane/masking/synthesizers.py`
- **Owner for resolution:** Distribution-shape preservation is explicitly
  a data-quality/certification concern (`ARCHITECTURE.md` section 3.2,
  `DATA_GOVERNANCE.md` B.3) for a later phase, not this one.
