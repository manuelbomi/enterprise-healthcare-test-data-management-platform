# Chapter 10 — Deterministic pseudonymization

## The concept

**Pseudonymization** replaces a real identifier with a substitute
("pseudonym"/token) that carries no mathematical relationship an
attacker could exploit to recover the original — as opposed to
**anonymization**, which aims to remove the ability to re-identify a
person at all (usually by discarding information, not substituting it).
**Deterministic** means the same real input always produces the same
output, given the same secret key and scope. This repository's ADR-0006
states the design principle directly: masking of an identifier is a
pure, deterministic function of `(real_value, masking_scope,
secret_salt/key)`. Two independent jobs, run against the same scope and
key, always produce the same masked value for the same real value —
which is *why* a masked member ID keeps matching across every table and
every source system that references it (Chapter 8's referential
integrity, surviving all the way through masking).

## The two techniques that implement this for real

`data_plane.masking.engine.MaskingEngine` implements this principle two
ways:

- **`HMAC_PSEUDONYMIZATION`** — a keyed HMAC-SHA256 digest of
  `(real_value, scope)` under the secret key. Deterministic, one-way,
  and — critically — *keyed*, unlike plain hashing.
- **`TOKENIZATION`** — issues a `TKN-...` token via a `TokenVault`
  abstraction (`token_vault.py`). The default `HmacTokenVault` is
  stateless: the token is recomputable from `(value, scope, key)` but
  never persists a real-value -> token mapping anywhere. There is
  therefore no mapping file for a breach to steal, at the cost of no way
  to look up "what value does this token correspond to" without already
  knowing (or brute-forcing) the real value — a documented, deliberate
  limitation (`token_vault.py`'s module docstring). An
  `InMemoryRandomTokenVault` alternative exists to demonstrate the
  opposite tradeoff (a stored, reversible mapping) for teaching purposes.

## Why "keyed" is the entire point — proven with a real attack, not just asserted

This repository doesn't just claim unkeyed hashing is weak; it builds a
real dictionary attack and shows it succeed against `HASHING` and fail
against `HMAC_PSEUDONYMIZATION`:

```python
# services/data-plane/tests/masking/test_masking_engine.py
def test_hashing_technique_never_uses_the_key_and_is_therefore_dictionary_attackable():
    ...
```

This test builds a real 10,000-candidate-value dictionary/rainbow-table
attack. Against `HASHING` (unkeyed SHA-256), it succeeds — anyone can
precompute `SHA256(candidate)` for every candidate and match it against
a masked value with no key needed at all. Against
`HMAC_PSEUDONYMIZATION`, the same attack fails, because the attacker
doesn't have the key. This is why the default masking policy
(`policy.py`) never routes a `DIRECT_IDENTIFIER` column to `HASHING` —
it exists in the engine as an explicitly required technique (and as a
teaching artifact demonstrating *why* the keyed primitive matters), not
as something the default policy would actually use to protect an
identifier.

## The tradeoff this is honest about

Determinism cuts both ways, and `data_plane/masking/README.md`'s
"Security tradeoffs" section says so directly: **determinism is not
anonymization if the key leaks.** Every deterministic technique here is
`masked = f(real_value, scope, key)` — a pure function, not a random
draw. Anyone who has the key (and the scope string) can recompute `f`
for any candidate value and check it against a masked value — a full
break for any input space small enough to enumerate (a 9-digit SSN, a
4-digit PIN). This is exactly why ADR-0006 requires the key to be
managed by a real secrets provider (out of scope for the phase that
built this — tracked in `docs/problems/problems_phase_03.md` P3-2) and never stored
alongside the masked data. It is a *deliberate* tradeoff, not an
oversight: a platform that needed stronger protection against key
compromise, at the cost of losing joinability, would use independent
random masking per occurrence instead — which is precisely what this
platform does not do, because joinability across tables and systems is
its whole value proposition.

## Where this key actually comes from, today

```bash
cd services/data-plane
python -m data_plane.masking.cli --generate-dev-key
```

prints a freshly generated, local-dev-only HMAC key
(`data_plane.masking.secrets`), resolved at runtime from
`TDM_MASKING_HMAC_KEY` or a gitignored `.env` file — never hardcoded,
never committed. See `SECURITY.md`'s "Secrets are always resolved
through the secrets-provider adapter" principle for where this is
headed architecturally (`services/governance-service`, still a
scaffold as of this phase).

## Where to go next

Continue to [Chapter 11 — Synthetic data](11-synthetic-data.md), or read
[ADR-0006](../../adr/0006-deterministic-masking-strategy.md) in full and
`data_plane.masking.token_vault`'s module docstring for the complete
reasoning.
