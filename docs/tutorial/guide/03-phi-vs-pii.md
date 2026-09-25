# Chapter 3 — PHI vs PII

## The plain-language distinction

- **PII (Personally Identifiable Information)** is any information that
  identifies (or could help identify) a specific person — a name, a
  Social Security Number, an email address, a home address. PII exists
  in every industry, not just healthcare.
- **PHI (Protected Health Information)** is health information *tied to
  an identifiable person* — a diagnosis, a lab result, a prescription,
  a claim. PHI is specific to healthcare (it's the "P" in HIPAA), and it
  is regulated even more strictly than generic PII in most
  jurisdictions, because the sensitivity of the underlying *fact*
  (someone's mental health diagnosis, someone's HIV status) is high even
  independent of whether the person's name is directly attached.

The two overlap constantly and are not a clean either/or. A patient's
name on a lab report is both PII (it identifies a person) and, in that
context, part of a PHI record (the record is about their health). A
diagnosis code sitting in a free-standing reference-vocabulary table,
with no patient attached, is neither.

## Why this repository defines two separate vocabularies, not one

`libs/contracts/src/healthcare_tdm_contracts/classification.py` is
explicit that collapsing PHI/PII into one label would lose information,
and defines two:

- **`ClassificationTier`** (four values: `DIRECT_IDENTIFIER`,
  `QUASI_IDENTIFIER`, `SENSITIVE_CLINICAL_ATTRIBUTE`, `NON_SENSITIVE`) —
  answers "how must this column be *handled*?" This is
  `DATA_GOVERNANCE.md` section B.1's four-tier model, and it's what a
  masking rule keys off of (Chapter 9).
- **`SensitivityCategory`** (six values: `direct_identifier`,
  `quasi_identifier`, `phi`, `pii`, `sensitive`, `non_sensitive`) —
  answers "what *kind* of sensitive data is this, and why?" This is the
  vocabulary a data steward or auditor actually uses, and it's the label
  the data catalog shows.

A single column can honestly carry more than one `SensitivityCategory`
label at once — a name is both `direct_identifier` and `pii`; a
diagnosis code is both `phi` and, combined with other fields, a
`quasi_identifier`. Because a catalog entry needs one primary label, the
module fixes a documented precedence order
(`SensitivityCategory.precedence()`) rather than pretending the six
labels are a clean partition — see
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for the full discussion of
what that precedence order does and doesn't solve.

## The example this repository already proves in real code

`services/data-plane/src/data_plane/discovery/README.md` gives the
canonical example for why classification is per-(entity, column), not
per-column-name — and it is exactly PHI-vs-PII-adjacent reasoning:

> `Diagnosis.diagnosis_code` (a free-standing code-vocabulary row) is
> `non_sensitive`; `ClaimLine.diagnosis_code` (a specific code value
> attached, via `claim_id`, to a specific member's specific claim) is
> `phi`.

Same column name, same data type, wildly different classification —
because the second one is a health fact tied to an identifiable person
(PHI) and the first one is not tied to anyone at all.

## Try it yourself

Run discovery against a real generated estate and look at the category
breakdown it prints:

```bash
cd services/data-plane
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \
    --out data/tmp/synthetic-estate/catalog.json
```

Real output from running exactly this command against a fresh `tiny`
estate:

```
Scanned 141 columns across 5 source systems.
Catalog written: .../data/tmp/synthetic-estate/catalog.json
By category:
   direct_identifier: 20
       non_sensitive: 53
                 phi: 18
                 pii: 7
    quasi_identifier: 35
           sensitive: 8
Flagged for steward review (confidence < 0.7, unconfirmed): 4
```

Notice `phi` (18) and `pii` (7) are reported as separate counts, even
though both are also folded into the coarser `direct_identifier`/
`quasi_identifier`/`sensitive` counts elsewhere via `ClassificationTier`
— this is the two-vocabulary design in action, on real output from real
code, not a diagram.

## Where to go next

For exactly how the discovery engine decides these labels (schema
rules, pattern rules, manual overrides, and their precedence), read
[Chapter 6 — Sensitive-data classification](06-sensitive-data-classification.md)
in this guide, then
`docs/tutorial/03-phi-pii-classification.md` for the full
implementation-depth walkthrough with real per-column output, and
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` before trusting this
engine's output for anything beyond triage. Then continue to
[Chapter 4 — Production vs lower environments](04-production-vs-lower-environments.md).
