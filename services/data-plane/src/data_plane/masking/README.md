# `data_plane.masking` — enterprise data masking engine (Phase 3)

Applies a policy-driven masking engine to the Phase 1 synthetic estate,
using the Phase 2 data catalog's classification to decide which of
eleven masking techniques masks which column. Every deterministic
technique is a keyed function of `(real_value, scope, secret_key)` per
[ADR-0006](../../../../../docs/adr/0006-deterministic-masking-strategy.md),
so the same real value always maps to the same masked value within a
scope — this is what lets a masked member ID keep joining across every
table and every source system it appears in.

**Read [`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`](../../../../../docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md)
and the "Security tradeoffs" section below before treating this engine's
output as a de-identification guarantee.** It masks what the Phase 2
catalog told it to mask; it does not independently verify that the
catalog's classification was correct.

## Module map

| Module | Responsibility |
|---|---|
| `secrets.py` | Resolves the HMAC key from `TDM_MASKING_HMAC_KEY` or a gitignored `.env` file. Never hardcodes one. |
| `field_types.py` | Infers a `MaskingFieldType` (email/phone/ssn/name/...) from a bare column name, as a fallback. |
| `synthesizers.py` | Deterministic, `Faker`-backed format-preserving synthetic value generation, seeded from an HMAC digest. |
| `token_vault.py` | The `TokenVault` abstraction (`MaskingTechnique.TOKENIZATION`): a stateless, HMAC-derived default (`HmacTokenVault`) and a demonstration stored-random-token alternative (`InMemoryRandomTokenVault`). |
| `engine.py` | `MaskingEngine`: implements every `MaskingTechnique` as `masked = f(real_value, scope, secret_key)`. |
| `policy.py` | The default `MaskingPolicy`, rule resolution, and the cross-system `LINKAGE_SCOPES` table. |
| `dataset_masker.py` | Applies `engine` + `policy` to the real, on-disk Phase 1 estate, using the real Phase 2 catalog. |
| `validation.py` | Lightweight masking validation (referential integrity, no-raw-value-leakage, collision detection). |
| `cli.py` | `python -m data_plane.masking.cli`, the end-to-end entry point. |

## Running it

```bash
# From services/data-plane, with the package installed (pip install -e .):

# 1. Generate a synthetic estate (Phase 1 CLI) if you don't have one yet:
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

# 2. Run discovery against it (Phase 2 CLI) to produce a catalog:
python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \
    --out data/tmp/synthetic-estate/catalog.json

# 3. Resolve a local dev HMAC key. NEVER commit this value -- see SECURITY.md.
python -m data_plane.masking.cli --generate-dev-key
export TDM_MASKING_HMAC_KEY=<the printed value>
# ...or copy .env.example to .env in this directory and paste it in.

# 4. Mask the estate using the catalog's classification:
python -m data_plane.masking.cli --estate-dir data/tmp/synthetic-estate \
    --catalog data/tmp/synthetic-estate/catalog.json \
    --out-dir data/tmp/synthetic-estate-masked
```

This prints a per-technique breakdown and a validation summary, and
writes a masked estate mirroring the source estate's layout, plus
`masking_run_summary.json` with the same information in machine-readable
form.

## The eleven masking techniques

| Technique | What it does | Used for (by the default policy) |
|---|---|---|
| `REDACTION` | Fixed or format-preserving redaction marker | Available for any field a policy author wants irreversibly blanked |
| `NULLIFICATION` | Replace with `None` | Available; not used by the default policy (nulling a value that was present would manufacture a false "this field is empty" fact for tiers that don't need it) |
| `HASHING` | Unkeyed SHA-256 -- **deliberately weak, see below** | Never the default for `DIRECT_IDENTIFIER`; available for lower-sensitivity fields |
| `HMAC_PSEUDONYMIZATION` | Keyed HMAC-SHA256 digest | Generic direct-identifier fallback |
| `TOKENIZATION` | `TokenVault`-issued `TKN-...` token | Every identifier that must keep joining across tables/systems (`member_id`, `claim_id`, `provider_id`, ...) |
| `FORMAT_PRESERVING_SYNTHETIC` | Deterministically-seeded, shape-plausible fake value | SSNs, MRNs, group numbers, financial amounts |
| `DATE_SHIFT` | Deterministic +/- day offset | Every quasi-identifier date field |
| `EMAIL_MASK` | Format-preserving synthetic email | `email` |
| `PHONE_MASK` | Format-preserving synthetic phone number | `phone`, `fax`, `mobile` |
| `ADDRESS_REPLACEMENT` | Format-preserving synthetic street/city/ZIP | `line1`, `line2`, `city`, `zip_code` |
| `NAME_REPLACEMENT` | Format-preserving synthetic person name | `first_name`, `last_name`, `*_name` |

See `data_plane.masking.policy._FIELD_RULES` for the exact column-name
patterns each technique is wired to, and
`data_plane.masking.policy.LINKAGE_SCOPES` for which identifier column
names (including cross-system aliases like the partner feed's `pat_id`)
share a scope.

## Worked before/after example (real output, `tiny` scale, seed 20240101)

Running the pipeline above against a real generated `tiny` estate
produced this (member `SYN-MBR-000007`, a real row in the generated
estate -- every value below is synthetic/generator-produced, never real
PHI/PII, per `DATA_GOVERNANCE.md` Part A):

| System | Field | Before | After |
|---|---|---|---|
| Postgres (`member`) | `member_id` | `SYN-MBR-000007` | `TKN-3E12A234F802` |
| Postgres (`member`) | `first_name` | `Lee` | `Douglas` |
| Postgres (`member`) | `last_name` | `Dunlap` | `Fischer` |
| Postgres (`member`) | `ssn` | `563-30-0335` | `569-68-9229` |
| Parquet (`claim`) | `member_id` | `SYN-MBR-000007` | `TKN-3E12A234F802` |
| NDJSON (`encounters`) | `member_id` | `SYN-MBR-000007` | `TKN-3E12A234F802` |
| CSV (`prescriptions`) | `member_id` | `SYN-MBR-000007` | `TKN-3E12A234F802` |
| Partner v2 JSON (`lab_result`, member `SYN-MBR-000013`) | `member_id` | `SYN-MBR-000013` | `TKN-DDB2EAE9AF8C` |
| Partner v2 JSON | `test_name` | `Creatinine` | `Jqcrvyxwkt` |
| Partner v2 JSON | `abnormal_flag` | `Normal` | `Tuzqem` |
| Partner v2 JSON | `collected_date` | `2025-04-05` | `2025-04-05` shifted deterministically (differs per field/key) |

Note `member_id` is `TKN-3E12A234F802` in **four** independent files
across four different formats (SQLite, Parquet, NDJSON, CSV) -- the same
real value, the same scope (`member-id-global`), the same key, always
producing the same token. `SYN-MBR-000013` similarly matches between
Postgres and the partner feed's `member_id` field (v2 shape); the same
mechanism covers the partner feed's legacy `pat_id` alias for the v1
flat-file shape.
`services/data-plane/tests/masking/test_dataset_masker_against_real_estate.py`
asserts this holds generally (any member present in multiple systems),
not just for these two specific members.

## Security tradeoffs (read this before relying on this engine)

This section exists because `DATA_GOVERNANCE.md` and `SECURITY.md`
require this repository to be honest about what its own tooling
demonstrates, matching the tone of
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for the discovery engine.

1. **Deterministic masking is not anonymization if the key leaks.**
   Every deterministic technique here is `masked = f(real_value, scope,
   key)` -- a *pure function*, not a random draw. Anyone who has the key
   (and the same scope string) can recompute `f` for any candidate real
   value and check it against a masked value, which is a full break for
   any input space small enough to enumerate (e.g. a 4-digit PIN, a
   9-digit SSN). This is the entire reason ADR-0006 requires the key to
   be managed by a real secrets provider (out of scope for this phase --
   see `problems_phase_03.md` P3-2) and never stored alongside the
   masked data. **Determinism is a deliberate tradeoff, not a mistake**:
   it is what makes cross-table and cross-system joins keep working after
   masking, which is this platform's whole value proposition (see
   `ARCHITECTURE.md` section 3.1). A platform that needed stronger
   protection against key compromise, at the cost of losing joinability,
   would use independent random masking per occurrence instead --
   ADR-0006 documents exactly this tradeoff.
2. **Unkeyed `HASHING` is deliberately weak, and this repository proves
   it rather than just asserting it.**
   `services/data-plane/tests/masking/test_masking_engine.py::test_hashing_technique_never_uses_the_key_and_is_therefore_dictionary_attackable`
   builds a real dictionary/rainbow-table attack against 10,000 candidate
   values and shows it succeeds against `HASHING` and fails against
   `HMAC_PSEUDONYMIZATION`. `HASHING` is included because it is an
   explicitly required technique and is legitimate for fields whose input
   space is not exhaustively guessable (and, more broadly, as a teaching
   artifact showing *why* ADR-0006 insists on a keyed primitive) -- but
   the default policy (`policy.py`) never routes a `DIRECT_IDENTIFIER`
   column to it.
3. **Format-preserving synthetic replacement trades realism for a small,
   real re-identification signal.** A masked SSN still *looks* like an
   SSN, a masked name still *looks* like a plausible name. This is
   intentional -- test data that doesn't look real doesn't exercise
   validation logic realistically -- but it does mean the *shape* of a
   masked value (its length, character classes, whether it parses as a
   valid-looking value) is preserved, which a sufficiently motivated
   adversary could use as a weak signal in combination with other
   evidence. This is the same category of tradeoff
   `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` describes for
   quasi-identifier combination risk: not modeled or scored here.
4. **Referential integrity is a deliberate re-identification tradeoff.**
   Because the same real member ID always masks to the same token
   everywhere, an adversary who can observe the masked data across
   multiple tables/systems can still perform the same linkage attacks a
   legitimate analyst can (e.g. correlating a masked member's claims with
   their masked lab results) -- masking removes the *real identity*, not
   the *linkability*. This is exactly what ADR-0006 asks for
   (`ARCHITECTURE.md` section 3.1: "the hardest problem this platform
   solves is keeping a patient ID consistent after masking"), and it is
   why `DATA_GOVERNANCE.md` B.4's access-control rules apply to masked,
   linkable data too, not only to raw PHI/PII.
5. **`TOKENIZATION`'s default vault stores nothing, which is more
   conservative than it might look, not less.** `HmacTokenVault` never
   persists a real-value -> token mapping anywhere; the token is
   recomputable from `(value, scope, key)` but not derivable from the
   token alone. There is therefore no mapping file for a breach to steal
   -- but there is also no way to look up "what member does `TKN-A81F...`
   correspond to" without already knowing (or brute-forcing) the real
   value, which is a real limitation for legitimate re-identification
   workflows (e.g. a support engineer debugging a specific masked test
   case). A production deployment needing that capability would use a
   governed, access-controlled, audited vault service instead -- see
   `problems_phase_03.md` P3-2 and `token_vault.py`'s module docstring.
6. **This engine masks what the catalog told it to mask -- no more, no
   less.** If the Phase 2 catalog under-classifies a column (see
   `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for the documented ways
   that can happen -- free text, novel column names, ...), this engine
   will pass that column through untouched, because from its perspective
   the catalog said it was safe. Masking correctness is bounded by
   classification correctness; this phase does not add an independent
   content-based safety net on top of Phase 2's classification.
7. **Numeric synthetic replacement preserves per-value plausibility, not
   dataset-wide distribution shape.** A masked `billed_amount` looks like
   a plausible dollar figure on its own, but the masked dataset's overall
   distribution of amounts (mean, variance, clustering) is not tuned to
   match the original's -- see `problems_phase_03.md` P3-4.

## What "masking validation" here does and does not prove

`validation.py` checks referential integrity, absence of raw
direct-identifier values in masked output, and token-collision freedom
-- against the specific masked run it's given. It is **not** the full
certification pipeline `ROADMAP.md` Phase 6 describes (which also needs
distribution-shape tolerance checks and a durable, auditable
certification record), and per `ARCHITECTURE.md` section 2.2, a real
certifier must not simply trust this module's own report -- it should
independently re-derive these checks. See `problems_phase_03.md` P3-1.
