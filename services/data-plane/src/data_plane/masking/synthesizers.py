"""Deterministic, format-preserving synthetic value generation.

Given a digest (already HMAC-keyed -- see `engine.py`) and a
`MaskingFieldType`, produce a value that *looks* like the real thing
(an SSN-shaped string, an email-shaped string, a phone-shaped string, a
plausible dollar amount, ...) without carrying any relationship to the
real value beyond "derived from the same deterministic seed."

Why this is idempotent
-----------------------
Every function here is seeded from `int.from_bytes(digest, "big")`, where
`digest` is the caller's HMAC digest of `(scope, real_value)` (see
`engine.MaskingEngine._digest`). Re-running the engine with the same key
and the same input always produces the same digest, so it always produces
the same synthetic value -- this is what "idempotent" means for this
module (see `docs/adr/0006-deterministic-masking-strategy.md`). A fresh
`Faker` instance is reseeded per call via `seed_instance`, never via the
global `random` module, so concurrent/interleaved calls cannot leak state
between columns.
"""

from __future__ import annotations

from faker import Faker

from healthcare_tdm_contracts import MaskingFieldType

#: One shared Faker instance, reseeded per call. Faker is somewhat
#: expensive to construct; reseeding an existing instance is the
#: documented, supported way to get a fresh deterministic sequence
#: (https://faker.readthedocs.io/en/stable/#seeding-the-generator).
_fake = Faker()
Faker.seed(0)  # neutralize any ambient global seed; every call below reseeds explicitly


def _seed_from_digest(digest: bytes) -> int:
    # 8 bytes is plenty of entropy for a Faker seed and keeps the int
    # small/portable across platforms.
    return int.from_bytes(digest[:8], "big")


def _seeded() -> Faker:
    return _fake


def synthesize(field_type: MaskingFieldType, digest: bytes, original: object) -> object:
    """Return a deterministic, plausibly-shaped synthetic value.

    `original` is used only to decide *shape* fallbacks (e.g. whether a
    generic value looks numeric); it never influences the seed directly
    (the seed is `digest`, which the caller already derived from the
    original value + scope + secret key -- see `engine.py`). Passing the
    raw original in here as well would be redundant, not a leak, but
    keeping the seed derivation in one place (the engine) is cleaner.
    """

    seed = _seed_from_digest(digest)
    fake = _seeded()
    fake.seed_instance(seed)

    if field_type is MaskingFieldType.SSN:
        return fake.numerify("###-##-####")
    if field_type is MaskingFieldType.EMAIL:
        return fake.user_name() + "@" + fake.free_email_domain()
    if field_type is MaskingFieldType.PHONE:
        return fake.numerify("(###) ###-####")
    if field_type is MaskingFieldType.FIRST_NAME:
        return fake.first_name()
    if field_type is MaskingFieldType.LAST_NAME:
        return fake.last_name()
    if field_type is MaskingFieldType.FULL_NAME:
        return fake.name()
    if field_type is MaskingFieldType.STREET_ADDRESS:
        return fake.street_address()
    if field_type is MaskingFieldType.CITY:
        return fake.city()
    if field_type is MaskingFieldType.ZIP_CODE:
        return fake.numerify("#####")
    if field_type is MaskingFieldType.IDENTIFIER:
        return "SYN-MASKED-" + fake.hexify("^^^^^^^^", upper=True)
    if field_type is MaskingFieldType.NUMERIC:
        return _synthesize_numeric(original, seed)

    # GENERIC and DATE (DATE is handled by the engine's dedicated
    # DATE_SHIFT technique; if it ever reaches here as a fallback,
    # format-preserving char-class substitution is still a safe default).
    return _format_preserving_generic(original, seed)


def _synthesize_numeric(original: object, seed: int) -> object:
    """A deterministic pseudo-random number of roughly the same order of
    magnitude as `original`. Preserves plausibility per-value; does NOT
    preserve the dataset's overall distribution -- see
    `problems_phase_03.md` P3-4 for why that's an explicit, documented
    limitation rather than a bug.
    """

    try:
        magnitude = abs(float(original)) if original is not None else 0.0
    except (TypeError, ValueError):
        magnitude = 0.0

    # Scale a seed-derived fraction into [0, 2x the original magnitude],
    # with a sane floor so a zero/near-zero original still yields a
    # plausible small positive figure rather than always 0.
    ceiling = max(magnitude * 2.0, 100.0)
    fraction = (seed % 1_000_000) / 1_000_000.0
    value = round(fraction * ceiling, 2)
    if isinstance(original, int) and not isinstance(original, bool):
        return int(value)
    return value


def _format_preserving_generic(original: object, seed: int) -> object:
    """Char-class-preserving substitution: every digit becomes a
    deterministically-chosen digit, every letter a deterministically-
    chosen letter of the same case, everything else (punctuation,
    whitespace) is left as-is. Works for arbitrary alphanumeric-shaped
    identifiers (MRNs, group numbers, ...) without needing a dedicated
    `MaskingFieldType`.
    """

    if original is None:
        return None
    text = str(original)
    if text == "":
        return text

    # A tiny local PRNG derived from `seed`, advanced per character, so
    # the whole string is deterministic without importing `random` (and
    # without perturbing the shared Faker instance's state).
    state = seed or 1

    def _next() -> int:
        nonlocal state
        # xorshift64 -- fast, deterministic, good-enough distribution for
        # picking among 10/26 choices; not a cryptographic PRNG (it does
        # not need to be: it is fed by an already-HMAC-keyed digest).
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        return state

    out_chars: list[str] = []
    for ch in text:
        if ch.isdigit():
            out_chars.append(str(_next() % 10))
        elif ch.isalpha() and ch.isupper():
            out_chars.append(chr(ord("A") + _next() % 26))
        elif ch.isalpha():
            out_chars.append(chr(ord("a") + _next() % 26))
        else:
            out_chars.append(ch)
    return "".join(out_chars)


__all__ = ["synthesize"]
