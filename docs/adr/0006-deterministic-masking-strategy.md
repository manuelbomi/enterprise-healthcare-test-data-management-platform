# ADR-0006: Deterministic, keyed masking to preserve cross-system referential integrity

## Status

Accepted

## Context

The hardest requirement in the whole platform: a patient's identifier
appears in many tables and often in many *source systems* (an EHR-shaped
system, a claims-shaped system, a scheduling-shaped system in this project's
synthetic reference data). After masking, tests still need to join across
those tables/systems the same way production code does — a masked claim
still needs to point at the same masked patient as a masked encounter for
that patient.

Two broad approaches exist:

1. **Random masking** — replace each real value with an independently
   random fake value. Simple, but breaks referential integrity immediately:
   the same real patient ID would map to a different random value in every
   table it appears in, making joins meaningless.
2. **Deterministic masking** — replace each real value with a fake value
   derived as a pure function of the real value plus a scope and a secret
   key: `masked = f(real_value, scope, key)`. The same real value in the
   same scope always produces the same masked value, wherever it appears,
   so joins keep working.

Deterministic masking introduces its own risk: if it is implemented naively
(e.g., a straight hash with no secret key), it becomes reversible by
dictionary/rainbow-table attack — an attacker with a list of plausible real
values (e.g., all valid SSNs in a range) could precompute the mapping.

## Decision

Masking of identifiers is implemented as a deterministic, **keyed**
transformation: `masked = f(real_value, scope, secret_key)`, where:

- `scope` defines the joinability boundary (e.g., "patient IDs across all
  systems in this refresh cycle" is one scope, so the same real patient ID
  maps to the same masked value everywhere it appears within that scope,
  while a different scope — e.g., a different downstream environment with
  its own policy — can legitimately produce a different masked value for
  the same real input, preventing cross-scope correlation).
- `secret_key` is never stored alongside the masked data, is managed
  through the secrets provider adapter (governance plane), and is rotated
  according to policy. Without the key, the transformation cannot be
  inverted or brute-forced at the scale that matters (the exact primitive —
  keyed HMAC-based tokenization vs. format-preserving encryption, chosen
  per data type — is a data-plane implementation decision made in Phase 9,
  not fixed by this ADR, but it must be keyed, not a bare hash).
- The **reverse mapping** (masked value → real value), if it needs to exist
  at all for a given use case, lives only in a governed token vault owned by
  the security/governance plane — never inside the masked dataset itself,
  and never derivable from the masked dataset without the key.

Quasi-identifiers and sensitive clinical attributes may use non-deterministic
generalization or synthetic replacement instead (see `DATA_GOVERNANCE.md`
B.2) where joinability is not required and additional risk reduction is
preferred over preserving exact value relationships.

## Consequences

- Requires careful key management (rotation, access control) — a weak point
  if handled casually, which is exactly why it's owned by the
  security/governance plane and documented in `THREAT_MODEL.md` rather than
  left as an implicit assumption inside the data plane.
- Enables the platform's core value proposition: masked/subsetted data that
  is actually usable for realistic testing, because joins and multi-table/
  multi-system workflows keep working.
- Certification (ADR/feature added in Phase 11) must verify determinism and
  non-reversibility as explicit, automated checks — not just verify that
  "some transformation happened."
