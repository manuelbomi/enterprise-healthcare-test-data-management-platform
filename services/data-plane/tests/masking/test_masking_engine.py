"""Unit tests for `data_plane.masking.engine.MaskingEngine`.

Covers every `MaskingTechnique`, plus the cross-cutting requirements the
Phase 3 promptbook calls out explicitly: determinism, collision handling,
referential integrity (scope-level, here; dataset-level integration is in
`test_dataset_masker_against_real_estate.py`), null handling, malformed
values, idempotency, and secret absence (the "why HASHING is weak"
demonstration).
"""

from __future__ import annotations

import re

import pytest

from healthcare_tdm_contracts import MaskingFieldType, MaskingTechnique

from data_plane.masking.engine import INVALID_DATE_MARKER, MaskingEngine
from data_plane.masking.token_vault import HmacTokenVault

KEY_A = b"unit-test-key-a-0123456789abcdef"
KEY_B = b"unit-test-key-b-fedcba9876543210"


def _engine(key: bytes = KEY_A) -> MaskingEngine:
    return MaskingEngine(key=key)


# --------------------------------------------------------------------------
# Determinism / idempotency
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "technique,field_type",
    [
        (MaskingTechnique.HASHING, MaskingFieldType.GENERIC),
        (MaskingTechnique.HMAC_PSEUDONYMIZATION, MaskingFieldType.GENERIC),
        (MaskingTechnique.TOKENIZATION, MaskingFieldType.IDENTIFIER),
        (MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, MaskingFieldType.SSN),
        (MaskingTechnique.EMAIL_MASK, MaskingFieldType.EMAIL),
        (MaskingTechnique.PHONE_MASK, MaskingFieldType.PHONE),
        (MaskingTechnique.ADDRESS_REPLACEMENT, MaskingFieldType.STREET_ADDRESS),
        (MaskingTechnique.NAME_REPLACEMENT, MaskingFieldType.FULL_NAME),
        (MaskingTechnique.DATE_SHIFT, MaskingFieldType.DATE),
    ],
)
def test_same_input_same_key_is_deterministic(technique, field_type) -> None:
    engine = _engine()
    value = "SYN-MBR-000123" if field_type != MaskingFieldType.DATE else "2020-01-15"
    first = engine.mask_value(value, technique=technique, scope="test-scope", field_type=field_type)
    second = engine.mask_value(value, technique=technique, scope="test-scope", field_type=field_type)
    assert first == second


def test_rerunning_the_engine_twice_is_idempotent_end_to_end() -> None:
    # Two independently constructed engines, same key -- simulates two
    # separate process runs (e.g. two CI jobs), not just two calls on one
    # instance.
    engine_1 = _engine()
    engine_2 = _engine()
    value = "jane.doe@example.com"
    masked_1 = engine_1.mask_value(
        value, technique=MaskingTechnique.EMAIL_MASK, scope="member-id-global",
        field_type=MaskingFieldType.EMAIL,
    )
    masked_2 = engine_2.mask_value(
        value, technique=MaskingTechnique.EMAIL_MASK, scope="member-id-global",
        field_type=MaskingFieldType.EMAIL,
    )
    assert masked_1 == masked_2


def test_different_keys_produce_different_output() -> None:
    value = "SYN-MBR-000123"
    masked_a = _engine(KEY_A).mask_value(
        value, technique=MaskingTechnique.TOKENIZATION, scope="member-id-global",
        field_type=MaskingFieldType.IDENTIFIER,
    )
    masked_b = _engine(KEY_B).mask_value(
        value, technique=MaskingTechnique.TOKENIZATION, scope="member-id-global",
        field_type=MaskingFieldType.IDENTIFIER,
    )
    assert masked_a != masked_b


def test_different_scopes_produce_different_output_for_the_same_value() -> None:
    # ADR-0006: different scopes must not be correlatable.
    engine = _engine()
    value = "SYN-MBR-000123"
    scope_a = engine.mask_value(
        value, technique=MaskingTechnique.HMAC_PSEUDONYMIZATION, scope="scope-a"
    )
    scope_b = engine.mask_value(
        value, technique=MaskingTechnique.HMAC_PSEUDONYMIZATION, scope="scope-b"
    )
    assert scope_a != scope_b


# --------------------------------------------------------------------------
# Referential integrity (same scope -> same masked value, the mechanism
# `policy.LINKAGE_SCOPES` relies on)
# --------------------------------------------------------------------------


def test_same_scope_same_value_produces_same_token_regardless_of_column_name() -> None:
    # This is the engine-level mechanism behind "member_id and pat_id
    # (its partner-feed alias) mask to the same token" -- see
    # policy.LINKAGE_SCOPES and test_dataset_masker_against_real_estate.py
    # for the end-to-end proof against real files.
    engine = _engine()
    real_value = "SYN-MBR-000007"
    as_member_id = engine.mask_value(
        real_value, technique=MaskingTechnique.TOKENIZATION, scope="member-id-global",
        field_type=MaskingFieldType.IDENTIFIER,
    )
    as_pat_id = engine.mask_value(
        real_value, technique=MaskingTechnique.TOKENIZATION, scope="member-id-global",
        field_type=MaskingFieldType.IDENTIFIER,
    )
    assert as_member_id == as_pat_id
    assert as_member_id.startswith("TKN-")


# --------------------------------------------------------------------------
# Collision handling
# --------------------------------------------------------------------------


def test_hmac_token_vault_default_length_has_no_collisions_across_many_distinct_values() -> None:
    vault = HmacTokenVault(KEY_A)  # default 12 hex chars = 48 bits
    tokens = {vault.tokenize(f"SYN-MBR-{i:06d}", "member-id-global") for i in range(2000)}
    assert len(tokens) == 2000  # every distinct input produced a distinct token
    assert vault.token_count() == 2000


def test_hmac_token_vault_short_length_can_collide_and_is_detectable() -> None:
    # Deliberately shrink the token space (2 hex chars = 8 bits = 256
    # possible tokens) so a collision is virtually guaranteed across many
    # distinct inputs -- proves the engine's collision surface is real and
    # that shrinking `token_hex_length` is a genuine (mis)configuration
    # risk an operator could hit, not just a theoretical concern.
    vault = HmacTokenVault(KEY_A, token_hex_length=2)
    tokens = [vault.tokenize(f"SYN-MBR-{i:06d}", "member-id-global") for i in range(500)]
    assert len(set(tokens)) < len(tokens), "expected a collision with an 8-bit token space"


def test_same_value_same_scope_is_not_a_collision() -> None:
    vault = HmacTokenVault(KEY_A)
    first = vault.tokenize("SYN-MBR-000007", "member-id-global")
    second = vault.tokenize("SYN-MBR-000007", "member-id-global")
    assert first == second
    assert vault.token_count() == 1


# --------------------------------------------------------------------------
# Null handling
# --------------------------------------------------------------------------


def test_null_is_preserved_by_default_across_every_technique() -> None:
    engine = _engine()
    for technique, field_type in [
        (MaskingTechnique.HASHING, MaskingFieldType.GENERIC),
        (MaskingTechnique.HMAC_PSEUDONYMIZATION, MaskingFieldType.GENERIC),
        (MaskingTechnique.TOKENIZATION, MaskingFieldType.IDENTIFIER),
        (MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, MaskingFieldType.SSN),
        (MaskingTechnique.EMAIL_MASK, MaskingFieldType.EMAIL),
        (MaskingTechnique.PHONE_MASK, MaskingFieldType.PHONE),
        (MaskingTechnique.ADDRESS_REPLACEMENT, MaskingFieldType.STREET_ADDRESS),
        (MaskingTechnique.NAME_REPLACEMENT, MaskingFieldType.FULL_NAME),
        (MaskingTechnique.DATE_SHIFT, MaskingFieldType.DATE),
        (MaskingTechnique.REDACTION, MaskingFieldType.GENERIC),
        (MaskingTechnique.PASSTHROUGH, MaskingFieldType.GENERIC),
    ]:
        result = engine.mask_value(None, technique=technique, scope="s", field_type=field_type)
        assert result is None, technique


def test_nullification_always_nullifies_even_when_preserve_null_is_false() -> None:
    engine = _engine()
    assert engine.mask_value(
        "some value", technique=MaskingTechnique.NULLIFICATION, scope="s", preserve_null=False
    ) is None


def test_preserve_null_false_still_masks_a_present_value() -> None:
    engine = _engine()
    result = engine.mask_value(
        "SYN-MBR-000123",
        technique=MaskingTechnique.TOKENIZATION,
        scope="member-id-global",
        field_type=MaskingFieldType.IDENTIFIER,
        preserve_null=False,
    )
    assert result != "SYN-MBR-000123"
    assert result.startswith("TKN-")


# --------------------------------------------------------------------------
# Malformed values
# --------------------------------------------------------------------------


def test_date_shift_on_malformed_value_redacts_instead_of_crashing() -> None:
    engine = _engine()
    # "TBD" is a real malformed-date sentinel this estate injects (see
    # reference_data/edge_cases.py, malformed_value_rate).
    result = engine.mask_value(
        "TBD", technique=MaskingTechnique.DATE_SHIFT, scope="quasi-identifier-default",
        field_type=MaskingFieldType.DATE,
    )
    assert result == INVALID_DATE_MARKER
    assert len(engine.warnings) == 1
    assert engine.warnings[0].technique is MaskingTechnique.DATE_SHIFT


def test_date_shift_on_valid_iso_date_shifts_within_configured_window() -> None:
    from datetime import date

    engine = _engine()
    original = date.fromisoformat("2020-06-15")
    result = engine.mask_value(
        "2020-06-15",
        technique=MaskingTechnique.DATE_SHIFT,
        scope="quasi-identifier-default",
        field_type=MaskingFieldType.DATE,
        parameters={"max_shift_days": "30"},
    )
    shifted = date.fromisoformat(result)
    assert abs((shifted - original).days) <= 30
    assert result != "2020-06-15"


def test_format_preserving_generic_handles_empty_string_and_mixed_punctuation() -> None:
    engine = _engine()
    assert engine.mask_value(
        "", technique=MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, scope="s",
        field_type=MaskingFieldType.GENERIC,
    ) == ""
    result = engine.mask_value(
        "GRP-99A(x)", technique=MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, scope="s",
        field_type=MaskingFieldType.GENERIC,
    )
    assert len(result) == len("GRP-99A(x)")
    assert result[3] == "-" and result[7] == "(" and result[9] == ")"


# --------------------------------------------------------------------------
# Redaction / nullification / passthrough
# --------------------------------------------------------------------------


def test_redaction_fixed_marker() -> None:
    engine = _engine()
    assert engine.mask_value("123-45-6789", technique=MaskingTechnique.REDACTION, scope="s") == "***REDACTED***"


def test_redaction_preserve_format_keeps_length() -> None:
    engine = _engine()
    result = engine.mask_value(
        "123-45-6789", technique=MaskingTechnique.REDACTION, scope="s", preserve_format=True
    )
    assert result == "*" * len("123-45-6789")


def test_passthrough_returns_value_unchanged() -> None:
    engine = _engine()
    assert engine.mask_value("active", technique=MaskingTechnique.PASSTHROUGH, scope="s") == "active"
    assert engine.mask_value(True, technique=MaskingTechnique.PASSTHROUGH, scope="s") is True


# --------------------------------------------------------------------------
# Format-preserving synthetic replacement actually looks plausible
# --------------------------------------------------------------------------


def test_ssn_synthesis_is_ssn_shaped() -> None:
    engine = _engine()
    result = engine.mask_value(
        "123-45-6789", technique=MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, scope="s",
        field_type=MaskingFieldType.SSN,
    )
    assert re.fullmatch(r"\d{3}-\d{2}-\d{4}", result)
    assert result != "123-45-6789"


def test_email_mask_is_email_shaped() -> None:
    engine = _engine()
    result = engine.mask_value(
        "jane.doe@example.com", technique=MaskingTechnique.EMAIL_MASK, scope="s",
        field_type=MaskingFieldType.EMAIL,
    )
    assert re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", result)
    assert result != "jane.doe@example.com"


def test_phone_mask_is_phone_shaped() -> None:
    engine = _engine()
    result = engine.mask_value(
        "555-123-4567", technique=MaskingTechnique.PHONE_MASK, scope="s",
        field_type=MaskingFieldType.PHONE,
    )
    assert re.fullmatch(r"\(\d{3}\) \d{3}-\d{4}", result)


def test_name_replacement_is_a_plausible_name_not_the_original() -> None:
    engine = _engine()
    result = engine.mask_value(
        "Dunlap", technique=MaskingTechnique.NAME_REPLACEMENT, scope="s",
        field_type=MaskingFieldType.LAST_NAME,
    )
    assert isinstance(result, str) and result.isalpha()
    assert result != "Dunlap"


def test_address_replacement_produces_a_street_address() -> None:
    engine = _engine()
    result = engine.mask_value(
        "742 Evergreen Terrace", technique=MaskingTechnique.ADDRESS_REPLACEMENT, scope="s",
        field_type=MaskingFieldType.STREET_ADDRESS,
    )
    assert isinstance(result, str) and any(ch.isdigit() for ch in result)
    assert result != "742 Evergreen Terrace"


# --------------------------------------------------------------------------
# Secret absence / weak-hash demonstration
# --------------------------------------------------------------------------


def test_hashing_technique_never_uses_the_key_and_is_therefore_dictionary_attackable() -> None:
    """Demonstrates, rather than just asserts, why `HASHING` (unkeyed) is
    weaker than `HMAC_PSEUDONYMIZATION` (keyed) -- see ADR-0006 and
    `MaskingTechnique.HASHING`'s docstring. An attacker who does not know
    the secret key but *does* know the plausible input space (here, a
    small set of 4-digit PINs) can precompute the unkeyed hash of every
    candidate and immediately reverse any masked value -- a dictionary
    attack. The same attack against HMAC_PSEUDONYMIZATION fails, because
    the attacker's precomputed table (built with no key) never matches
    the keyed engine's real output.
    """

    engine_no_secret_knowledge = _engine(KEY_A)  # the "real" engine, key unknown to attacker
    scope = "quasi-identifier-default"
    plausible_pins = [f"{i:04d}" for i in range(10_000)]  # attacker's guess space

    # Attacker precomputes the unkeyed hash of every candidate (no key
    # needed for HASHING -- that's the whole weakness).
    attacker_hash_table = {
        engine_no_secret_knowledge.mask_value(pin, technique=MaskingTechnique.HASHING, scope=scope): pin
        for pin in plausible_pins
    }
    secret_pin = "4821"
    masked_hash = engine_no_secret_knowledge.mask_value(
        secret_pin, technique=MaskingTechnique.HASHING, scope=scope
    )
    assert attacker_hash_table[masked_hash] == secret_pin  # dictionary attack succeeds

    # Now the same attack against the keyed technique: the attacker still
    # doesn't know the key, so their precomputed (unkeyed-equivalent)
    # table is built with a DIFFERENT key and never matches.
    attacker_engine = _engine(b"attacker-guessed-key-wrong-0000")
    attacker_hmac_table = {
        attacker_engine.mask_value(pin, technique=MaskingTechnique.HMAC_PSEUDONYMIZATION, scope=scope): pin
        for pin in plausible_pins
    }
    masked_hmac = engine_no_secret_knowledge.mask_value(
        secret_pin, technique=MaskingTechnique.HMAC_PSEUDONYMIZATION, scope=scope
    )
    assert masked_hmac not in attacker_hmac_table  # dictionary attack fails


def test_engine_never_exposes_the_raw_key_in_any_masked_output() -> None:
    engine = _engine()
    key_text = KEY_A.decode("utf-8")
    outputs = [
        engine.mask_value("123-45-6789", technique=t, scope="s", field_type=ft)
        for t, ft in [
            (MaskingTechnique.HASHING, MaskingFieldType.GENERIC),
            (MaskingTechnique.HMAC_PSEUDONYMIZATION, MaskingFieldType.GENERIC),
            (MaskingTechnique.TOKENIZATION, MaskingFieldType.IDENTIFIER),
            (MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, MaskingFieldType.SSN),
        ]
    ]
    for output in outputs:
        assert key_text not in str(output)


def test_engine_requires_a_non_empty_key() -> None:
    with pytest.raises(ValueError):
        MaskingEngine(key=b"")
