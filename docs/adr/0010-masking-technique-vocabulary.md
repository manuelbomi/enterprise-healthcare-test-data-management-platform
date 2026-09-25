# ADR-0010: Split masking vocabulary into policy-level `MaskingStrategy` and engine-level `MaskingTechnique`

## Status

Accepted

## Context

Phase 0 scaffolded `MaskingStrategy` (`libs/contracts/.../masking.py`) as
a four-value enum (`DETERMINISTIC_TOKENIZATION`, `GENERALIZATION`,
`SYNTHETIC_REPLACEMENT`, `PASSTHROUGH`) and `MaskingRule`/`MaskingPolicy`
as the shape a masking policy is expressed in. Phase 2's data catalog
(`CatalogEntry.masking_requirement`) already depends on those four
values as a stable, coarse preview of "roughly what will happen to this
column," and the control plane may eventually expose them in a policy
UI.

Phase 3 has to implement a real masking engine that supports eleven
distinct, concretely different operations (redaction, nullification,
unkeyed hashing, HMAC pseudonymization, vault-style tokenization,
format-preserving synthetic replacement, date shifting, email masking,
phone masking, address replacement, name replacement). Several of these
map to the *same* coarse `MaskingStrategy` — e.g. `SYNTHETIC_REPLACEMENT`
is implemented by format-preserving-synthetic, email-mask, phone-mask,
address-replacement, *or* name-replacement, depending on what shape the
underlying field actually is. Forcing the engine to key its behavior off
the existing four-value enum would mean either (a) growing
`MaskingStrategy` to eleven-plus values, breaking the catalog's stable,
intentionally-coarse public vocabulary and forcing every future technique
addition to also be a catalog-facing change, or (b) inventing a
parallel, undocumented convention (e.g. `MaskingRule.parameters["technique"]`
as an untyped string) that loses type safety and discoverability.

## Decision

Add two new, additive enums to `libs/contracts/.../masking.py`:
`MaskingTechnique` (the concrete engine-level operation) and
`MaskingFieldType` (the semantic content-shape a field has, used to pick
a plausible synthetic replacement). `MaskingRule` gains optional fields
(`field_pattern`, `technique`, `field_type`, `preserve_format`,
`preserve_null`, `preserve_linkage`) that carry this detail without
changing the meaning or requiredness of any Phase 0 field
(`tier`/`strategy`/`scope`/`parameters` are unchanged, so every existing
caller that only knows about those four fields keeps working).

This mirrors the precedent `classification.py` already set for
`ClassificationTier` vs. `SensitivityCategory`: two vocabularies, at two
different levels of granularity, answering two different questions,
rather than one vocabulary trying to serve both.

`data_plane.masking.policy.DEFAULT_TECHNIQUE_BY_STRATEGY` is the
documented default mapping from the coarse strategy to a concrete
technique, used whenever a `MaskingRule` doesn't pin a `technique`
explicitly — so a policy author can still work at the coarse level
(`strategy` only) and get sensible behavior, or drop to the fine level
(`technique`, `field_pattern`, `field_type`) for precise control.

## Consequences

- The data catalog (`CatalogEntry.masking_requirement`) and any future
  policy UI never need to change when the masking engine grows a new
  technique — they only ever see the stable four-value `MaskingStrategy`.
- The masking engine (`services/data-plane/src/data_plane/masking/`) has
  a typed, discoverable vocabulary for its real behavior instead of an
  untyped parameters dict, and `MaskingRule.technique`/`field_type` are
  visible in the same Pydantic model an auditor or policy reviewer
  already reads for `tier`/`strategy`/`scope`.
- `MaskingRule` grew six new optional fields. This is intentionally a
  wide, permissive shape rather than several narrower rule types (e.g.
  separate `TokenizationRule`/`RedactionRule` classes), trading a small
  amount of "some fields are meaningless for some techniques" fuzziness
  for a single, simple, serializable rule shape that every part of the
  system (policy resolution, the catalog, a future policy-editing UI)
  can treat uniformly. If this becomes unwieldy as more techniques are
  added, a follow-up ADR should consider a tagged-union rule shape
  instead.
- Two enums to keep synchronized in spirit (a new `MaskingTechnique`
  should usually be reachable from at least one `MaskingStrategy` via
  `DEFAULT_TECHNIQUE_BY_STRATEGY` or an explicit field-pattern rule) —
  the same maintenance cost ADR-0006/`classification.py` already accepted
  for `ClassificationTier`/`SensitivityCategory`.
