"""The tokenization abstraction: `MaskingTechnique.TOKENIZATION`.

ADR-0006 draws a distinction the masking engine has to actually implement,
not just describe: a keyed HMAC digest and a "token vault" are two
different shapes of the same idea (deterministic, keyed replacement of a
real value with a fake one), and a real platform needs to be able to swap
between them without changing every call site. This module is that seam:
`TokenVault` is the abstract interface, `HmacTokenVault` is the default,
stateless implementation this phase actually uses, and
`InMemoryRandomTokenVault` demonstrates the alternative (a real, storable
mapping) for teaching purposes -- see `problems_phase_03.md` P3-2 for why
neither of these is a production-grade governed vault yet.

Why the default is stateless (HMAC-derived), not a stored random mapping
--------------------------------------------------------------------------
ADR-0006 says the reverse mapping, "if it needs to exist at all... lives
only in a governed token vault owned by the security/governance plane --
never inside the masked dataset itself." This phase has no governed vault
service to store a mapping in (`services/governance-service` is still
scaffolding), so the default vault here deliberately stores *nothing*: the
token is `f(real_value, scope, secret_key)`, recomputable from the same
inputs but not derivable from the token alone without the key, and there
is no mapping file anywhere for a breach to steal. This is *more*
conservative than a stored-mapping vault, not a shortcut -- it is exactly
the property ADR-0006 asks for ("without ever storing a reversible mapping
outside the governed token vault").
"""

from __future__ import annotations

import hmac
import hashlib
from abc import ABC, abstractmethod

TOKEN_PREFIX = "TKN-"


class TokenVault(ABC):
    """Abstraction over "real value -> stable token" lookup/creation.

    A `MaskingEngine` depends only on this interface (see `engine.py`),
    never on a concrete implementation, so the storage strategy can change
    (stateless HMAC today; a real governed vault service later) without
    touching masking logic.
    """

    @abstractmethod
    def tokenize(self, value: str, scope: str) -> str:
        """Return the stable token for `value` within `scope`. Calling
        this twice with the same `(value, scope)` MUST return the same
        token (determinism is the whole point -- see ADR-0006)."""

    @abstractmethod
    def token_count(self) -> int:
        """Number of distinct tokens this vault instance has produced or
        holds. Used by tests/validation to reason about cardinality (e.g.
        detecting collisions -- see `validation.assert_no_collisions`)."""


class HmacTokenVault(TokenVault):
    """Stateless, deterministic token vault: `token = "TKN-" +
    HMAC-SHA256(key, scope + value)[:token_hex_length].upper()`.

    This is the default vault the masking policy uses for every
    `TOKENIZATION`-technique column (see `policy.py`). `token_hex_length`
    is deliberately configurable (default 12 hex chars = 48 bits) so
    tests can shrink it to force and detect a collision on purpose (see
    `services/data-plane/tests/masking/test_engine.py`,
    "collision handling").
    """

    def __init__(self, key: bytes, *, token_hex_length: int = 12) -> None:
        if token_hex_length < 1 or token_hex_length > 64:
            raise ValueError("token_hex_length must be between 1 and 64")
        self._key = key
        self._token_hex_length = token_hex_length
        self._seen: set[str] = set()

    def tokenize(self, value: str, scope: str) -> str:
        digest = hmac.new(self._key, f"{scope}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
        token = TOKEN_PREFIX + digest[: self._token_hex_length].upper()
        self._seen.add(token)
        return token

    def token_count(self) -> int:
        return len(self._seen)


class InMemoryRandomTokenVault(TokenVault):
    """Demonstration-only vault backed by an in-memory random mapping,
    showing the *other* classic tokenization shape (a stored, randomly
    generated token with no cryptographic relationship to the real
    value, looked up through a table).

    NOT used by the default masking policy and NOT durable -- the mapping
    lives only in process memory and is lost when the process exits. A
    real implementation of this shape would need to live in a governed,
    access-controlled, durable store (see `problems_phase_03.md` P3-2);
    building that store is explicitly out of scope for this phase. Kept
    here so the codebase demonstrates understanding of the tradeoff
    between the two vault shapes (stateless/keyed vs. stored/random)
    rather than only ever implementing one.
    """

    def __init__(self) -> None:
        import secrets as _secrets

        self._secrets = _secrets
        self._by_scope: dict[str, dict[str, str]] = {}
        self._tokens: set[str] = set()

    def tokenize(self, value: str, scope: str) -> str:
        scoped = self._by_scope.setdefault(scope, {})
        if value in scoped:
            return scoped[value]
        token = TOKEN_PREFIX + self._secrets.token_hex(6).upper()
        while token in self._tokens:  # pragma: no cover - astronomically unlikely
            token = TOKEN_PREFIX + self._secrets.token_hex(6).upper()
        scoped[value] = token
        self._tokens.add(token)
        return token

    def token_count(self) -> int:
        return len(self._tokens)


__all__ = [
    "TOKEN_PREFIX",
    "HmacTokenVault",
    "InMemoryRandomTokenVault",
    "TokenVault",
]
