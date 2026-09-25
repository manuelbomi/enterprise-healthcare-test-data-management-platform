# Chapter 9 — Masking

## The concept

Masking is the act of replacing a real sensitive value with a
substitute value before the data leaves a trusted boundary. The naive
version — blank it out, replace it with `"REDACTED"` — is not good
enough for two concrete reasons Chapter 1 already named: it breaks
joins (every redacted member ID looks identical, so you can no longer
tell which claims belong to which member), and it destroys realism
(test data that doesn't look real doesn't exercise validation logic
realistically). A real masking engine has to solve both at once: be
*consistent* (same real value -> same masked value, so relationships
keep working) and *realistic* (the masked value still looks like a
plausible value of its type), while never being derivable back to the
real value without a secret an attacker doesn't have.

## Eleven techniques, one policy-driven engine

`data_plane.masking.engine.MaskingEngine` implements eleven distinct
`MaskingTechnique`s, each a deterministic (or, for a couple, explicitly
non-deterministic-by-design) function:

| Technique | What it does |
|---|---|
| `REDACTION` | Fixed or format-preserving redaction marker |
| `NULLIFICATION` | Replace with `None` |
| `HASHING` | Unkeyed SHA-256 — deliberately weak, see Chapter 10 |
| `HMAC_PSEUDONYMIZATION` | Keyed HMAC-SHA256 digest |
| `TOKENIZATION` | `TokenVault`-issued `TKN-...` token |
| `FORMAT_PRESERVING_SYNTHETIC` | Deterministically-seeded, shape-plausible fake value |
| `DATE_SHIFT` | Deterministic +/- day offset |
| `EMAIL_MASK` / `PHONE_MASK` / `ADDRESS_REPLACEMENT` / `NAME_REPLACEMENT` | Format-preserving synthetic replacements for their named field type |

`data_plane.masking.policy` is what decides *which* technique applies
to *which* column — and it decides this from the real Chapter 6 catalog,
not from a hardcoded list: a column's `ClassificationTier` resolves,
through `policy._FIELD_RULES`, to a masking rule. This is the concrete
mechanism behind "catalog classification -> masking policy -> masked
output," wired end to end (`ARCHITECTURE.md` section 2.2).

## Try it yourself

Continuing the pipeline from Chapters 6-8:

```bash
cd services/data-plane
python -m data_plane.masking.cli --generate-dev-key
export TDM_MASKING_HMAC_KEY=<the printed value>   # never commit this
python -m data_plane.masking.cli --estate-dir data/tmp/synthetic-estate-subset \
    --catalog data/tmp/synthetic-estate/catalog.json \
    --out-dir data/tmp/synthetic-estate-masked
```

Real output from running exactly this pipeline (fresh `tiny` estate,
`fixed_population` subset of 8 members, freshly generated throwaway dev
key):

```
Masked estate written: .../data/tmp/synthetic-estate-masked
Rows processed: 173
Column-values masked: 1524
By technique:
           address_replacement: 48
                    date_shift: 247
                    email_mask: 8
   format_preserving_synthetic: 328
              name_replacement: 24
                   passthrough: 561
                    phone_mask: 8
                  tokenization: 300
Files written: 11
Warnings (malformed values encountered, handled safely): 71
Validation: PASSED (23 checks)
```

Notice `passthrough` (561) is the largest single bucket — most columns
in a real dataset are non-sensitive and correctly pass through
unmodified; masking only touches what classification actually flagged.

## The worked before/after example (from `data_plane/masking/README.md`)

```
| System                | Field       | Before             | After               |
|-----------------------|-------------|---------------------|----------------------|
| Postgres (member)     | member_id   | SYN-MBR-000007      | TKN-3E12A234F802     |
| Postgres (member)     | first_name  | Lee                 | Douglas              |
| Postgres (member)     | ssn         | 563-30-0335         | 569-68-9229          |
| Parquet (claim)       | member_id   | SYN-MBR-000007      | TKN-3E12A234F802     |
| NDJSON (encounters)   | member_id   | SYN-MBR-000007      | TKN-3E12A234F802     |
| CSV (prescriptions)   | member_id   | SYN-MBR-000007      | TKN-3E12A234F802     |
```

`member_id` maps to the exact same token (`TKN-3E12A234F802`) in **four
independent files across four different formats** — this is Chapter 10's
subject, and it's the entire reason masking has to be deterministic
rather than a random substitution per occurrence.

## Read this before trusting the engine's output

`data_plane/masking/README.md`'s "Security tradeoffs" section is
required reading, not optional context — it explains, with a real
demonstrated attack (see Chapter 10), exactly which properties this
engine gives you and which it deliberately does not.

## Where to go next

Continue to
[Chapter 10 — Deterministic pseudonymization](10-deterministic-pseudonymization.md),
then read `services/data-plane/src/data_plane/masking/README.md` and
[ADR-0006](../../adr/0006-deterministic-masking-strategy.md)/
[ADR-0010](../../adr/0010-masking-technique-vocabulary.md) for the full
implementation depth.
