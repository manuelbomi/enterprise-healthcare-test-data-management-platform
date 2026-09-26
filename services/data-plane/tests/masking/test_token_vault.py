"""Tests for the `TokenVault` abstraction: the default stateless
`HmacTokenVault` and the demonstration-only `InMemoryRandomTokenVault`.
"""

from __future__ import annotations

from data_plane.masking.token_vault import (
    TOKEN_PREFIX,
    HmacTokenVault,
    InMemoryRandomTokenVault,
)

KEY = b"token-vault-test-key-0123456789"


def test_hmac_token_vault_is_deterministic() -> None:
    vault_1 = HmacTokenVault(KEY)
    vault_2 = HmacTokenVault(KEY)
    assert vault_1.tokenize("SYN-MBR-000007", "member-id-global") == vault_2.tokenize(
        "SYN-MBR-000007", "member-id-global"
    )


def test_hmac_token_vault_token_is_prefixed_and_uppercase_hex() -> None:
    vault = HmacTokenVault(KEY)
    token = vault.tokenize("SYN-MBR-000007", "member-id-global")
    assert token.startswith(TOKEN_PREFIX)
    hex_part = token[len(TOKEN_PREFIX) :]
    assert hex_part == hex_part.upper()
    int(hex_part, 16)  # raises if not valid hex


def test_hmac_token_vault_different_scope_different_token() -> None:
    vault = HmacTokenVault(KEY)
    a = vault.tokenize("SYN-MBR-000007", "scope-a")
    b = vault.tokenize("SYN-MBR-000007", "scope-b")
    assert a != b


def test_hmac_token_vault_has_no_stored_reverse_mapping() -> None:
    # The whole point of the default (stateless) vault: nothing about its
    # internal state lets you go from token -> real value without the key
    # and the original value. Confirm no such mapping attribute exists.
    vault = HmacTokenVault(KEY)
    vault.tokenize("SYN-MBR-000007", "member-id-global")
    assert not hasattr(vault, "_by_scope")  # that's the *random* vault's shape, not this one


def test_in_memory_random_token_vault_is_stateful_and_reusable() -> None:
    vault = InMemoryRandomTokenVault()
    first = vault.tokenize("SYN-MBR-000007", "member-id-global")
    second = vault.tokenize("SYN-MBR-000007", "member-id-global")
    assert first == second  # still deterministic *within this process*, via storage
    assert vault.token_count() == 1


def test_in_memory_random_token_vault_tokens_are_not_derivable_from_value() -> None:
    # Unlike HmacTokenVault, two independently constructed random vaults
    # produce DIFFERENT tokens for the same value -- proving there is no
    # cryptographic relationship, only a stored lookup.
    vault_1 = InMemoryRandomTokenVault()
    vault_2 = InMemoryRandomTokenVault()
    assert vault_1.tokenize("SYN-MBR-000007", "s") != vault_2.tokenize("SYN-MBR-000007", "s")


def test_in_memory_random_token_vault_mapping_is_not_durable() -> None:
    # Demonstrates the documented limitation (docs/problems/problems_phase_03.md P3-2):
    # a fresh vault has no memory of a previous vault's tokens.
    vault_1 = InMemoryRandomTokenVault()
    token = vault_1.tokenize("SYN-MBR-000007", "s")
    vault_2 = InMemoryRandomTokenVault()
    assert vault_2.tokenize("SYN-MBR-000007", "s") != token
