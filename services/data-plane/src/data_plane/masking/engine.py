"""The masking engine: `masked = f(real_value, scope, secret_key)`.

Implements every `MaskingTechnique` (see `libs/contracts/.../masking.py`)
as a pure function of its inputs plus the engine's own secret key, per
`docs/adr/0006-deterministic-masking-strategy.md`. Nothing here reads the
key from anywhere except what the caller passes to `MaskingEngine.__init__`
(see `secrets.py` for how a caller resolves that key) -- the engine itself
never touches an environment variable or a file.

Determinism, and why it matters for referential integrity
------------------------------------------------------------
Every technique below (other than `NULLIFICATION`/`REDACTION`/
`PASSTHROUGH`, which are constant or length-preserving by definition) is
seeded from `hmac.new(key, f"{scope}:{value}".encode(), sha256).digest()`.
Two calls with the same `(key, scope, value)` always produce the same
digest, and every downstream synthesizer (`synthesizers.py`,
`token_vault.py`) is itself a pure function of that digest -- so the same
real value, masked under the same scope with the same key, always
produces the same masked value, *no matter which table, file, or source
system it appears in*. That is the entire mechanism behind this phase's
core requirement (a member ID masking to the same token across Postgres,
Parquet, S3-NDJSON, ADLS-CSV, and the partner feed): it falls out of using
the same `scope` string for every column alias that carries that
identifier (see `policy.py`'s `LINKAGE_SCOPES`), not from any special
cross-file bookkeeping in this module.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import date, timedelta

from healthcare_tdm_contracts import MaskingFieldType, MaskingTechnique

from data_plane.masking import synthesizers
from data_plane.masking.token_vault import HmacTokenVault, TokenVault

#: Marker returned by REDACTION when `preserve_format` is False.
REDACTION_MARKER = "***REDACTED***"
#: Marker returned when DATE_SHIFT cannot parse the input as an ISO date
#: (the Phase 1 estate deliberately injects malformed date-like strings,
#: e.g. "TBD" -- see reference_data/edge_cases.py). Shifting a value that
#: cannot be parsed as a date is undefined, and silently passing the raw
#: (possibly still-sensitive-looking) string through would violate "no raw
#: value leaks"; redacting it is the safe, documented fallback.
INVALID_DATE_MARKER = "INVALID-DATE-REDACTED"

#: Default deterministic date-shift window: +/- 365 days.
DEFAULT_MAX_SHIFT_DAYS = 365


@dataclass
class MaskingWarning:
    """One non-fatal issue encountered while masking a value (e.g. a
    malformed date). Collected on `MaskingEngine.warnings` so a caller can
    surface/report them without the engine raising and aborting a whole
    run over one bad cell -- consistent with how the Phase 1 estate
    itself treats malformed values as an expected, not exceptional,
    condition.
    """

    technique: MaskingTechnique
    scope: str
    original_repr: str
    message: str


@dataclass
class MaskingEngine:
    """Applies `MaskingTechnique`s to individual values.

    `key` must be resolved by the caller (see `secrets.resolve_hmac_key`)
    -- this class never reads it from the environment itself, which keeps
    it trivially unit-testable with a throwaway key and keeps "where does
    the key come from" a single-responsibility concern of `secrets.py`.
    """

    key: bytes
    token_vault: TokenVault = field(default=None)  # type: ignore[assignment]
    warnings: list[MaskingWarning] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("MaskingEngine requires a non-empty key")
        if self.token_vault is None:
            self.token_vault = HmacTokenVault(self.key)

    # -- core digest -------------------------------------------------
    def _digest(self, scope: str, value: object) -> bytes:
        return hmac.new(self.key, f"{scope}:{value}".encode("utf-8"), hashlib.sha256).digest()

    # -- public API ----------------------------------------------------
    def mask_value(
        self,
        value: object,
        *,
        technique: MaskingTechnique,
        scope: str,
        field_type: MaskingFieldType = MaskingFieldType.GENERIC,
        preserve_format: bool = False,
        preserve_null: bool = True,
        parameters: dict[str, str] | None = None,
    ) -> object:
        """Mask a single value according to `technique`.

        `value is None` short-circuits to `None` whenever `preserve_null`
        is True (the default) for every technique except NULLIFICATION
        (which produces None regardless, so the flag is a no-op for it).
        This is deliberate: a masking engine that turned an absent value
        into a masked-*looking* value would manufacture a fact ("this
        member has an SSN on file") that was not true of the source data.
        """

        parameters = parameters or {}

        if value is None and preserve_null and technique is not MaskingTechnique.NULLIFICATION:
            return None

        if technique is MaskingTechnique.PASSTHROUGH:
            return value

        if technique is MaskingTechnique.NULLIFICATION:
            return None

        if technique is MaskingTechnique.REDACTION:
            return self._redact(value, preserve_format=preserve_format, parameters=parameters)

        if technique is MaskingTechnique.HASHING:
            return self._hash_unkeyed(value, scope)

        if technique is MaskingTechnique.HMAC_PSEUDONYMIZATION:
            return self._hmac_pseudonymize(value, scope, parameters=parameters)

        if technique is MaskingTechnique.TOKENIZATION:
            return self.token_vault.tokenize(str(value), scope)

        if technique is MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC:
            digest = self._digest(scope, value)
            return synthesizers.synthesize(field_type, digest, value)

        if technique is MaskingTechnique.EMAIL_MASK:
            digest = self._digest(scope, value)
            return synthesizers.synthesize(MaskingFieldType.EMAIL, digest, value)

        if technique is MaskingTechnique.PHONE_MASK:
            digest = self._digest(scope, value)
            return synthesizers.synthesize(MaskingFieldType.PHONE, digest, value)

        if technique is MaskingTechnique.ADDRESS_REPLACEMENT:
            digest = self._digest(scope, value)
            resolved_type = (
                field_type
                if field_type in (MaskingFieldType.STREET_ADDRESS, MaskingFieldType.CITY,
                                   MaskingFieldType.ZIP_CODE)
                else MaskingFieldType.STREET_ADDRESS
            )
            return synthesizers.synthesize(resolved_type, digest, value)

        if technique is MaskingTechnique.NAME_REPLACEMENT:
            digest = self._digest(scope, value)
            resolved_type = (
                field_type
                if field_type in (MaskingFieldType.FIRST_NAME, MaskingFieldType.LAST_NAME,
                                   MaskingFieldType.FULL_NAME)
                else MaskingFieldType.FULL_NAME
            )
            return synthesizers.synthesize(resolved_type, digest, value)

        if technique is MaskingTechnique.DATE_SHIFT:
            return self._date_shift(value, scope, parameters=parameters)

        raise ValueError(f"Unsupported masking technique: {technique}")  # pragma: no cover

    # -- technique implementations --------------------------------------
    def _redact(self, value: object, *, preserve_format: bool, parameters: dict[str, str]) -> object:
        if value is None:
            return None
        redact_char = parameters.get("redact_char", "*")
        if preserve_format:
            text = str(value)
            return redact_char * len(text)
        return REDACTION_MARKER

    def _hash_unkeyed(self, value: object, scope: str) -> str:
        """Deliberately weak: SHA-256 with NO secret key -- see
        `MaskingTechnique.HASHING`'s docstring and
        `docs/adr/0006-deterministic-masking-strategy.md`. Included
        because it is an explicitly required technique and legitimate for
        values whose input space is not exhaustively guessable, but this
        engine's default policy (`policy.py`) never routes
        DIRECT_IDENTIFIER-tier columns to it.
        """

        digest = hashlib.sha256(f"{scope}:{value}".encode("utf-8")).hexdigest()
        return "HASH-" + digest[:16]

    def _hmac_pseudonymize(self, value: object, scope: str, *, parameters: dict[str, str]) -> str:
        digest = hmac.new(self.key, f"{scope}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
        length = int(parameters.get("output_length", "32"))
        return digest[:length]

    def _date_shift(self, value: object, scope: str, *, parameters: dict[str, str]) -> object:
        if value is None:
            return None
        max_shift = int(parameters.get("max_shift_days", str(DEFAULT_MAX_SHIFT_DAYS)))
        try:
            parsed = date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            self.warnings.append(
                MaskingWarning(
                    technique=MaskingTechnique.DATE_SHIFT,
                    scope=scope,
                    original_repr=repr(value),
                    message="Could not parse value as an ISO date; redacted instead of shifted.",
                )
            )
            return INVALID_DATE_MARKER

        digest = self._digest(scope, value)
        span = 2 * max_shift + 1
        offset = (int.from_bytes(digest[:4], "big") % span) - max_shift
        shifted = parsed + timedelta(days=offset)
        return shifted.isoformat()


__all__ = [
    "DEFAULT_MAX_SHIFT_DAYS",
    "INVALID_DATE_MARKER",
    "REDACTION_MARKER",
    "MaskingEngine",
    "MaskingWarning",
]
