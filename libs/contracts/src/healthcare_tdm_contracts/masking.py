"""Masking policy contracts.

Defines the shape of a masking policy: the mapping from a classification
tier (see classification.py) to a masking strategy. See
DATA_GOVERNANCE.md (section B.2) for the policy model and
docs/adr/0006-deterministic-masking-strategy.md for why masking of
identifiers must be deterministic and keyed rather than random.

Two masking vocabularies, on purpose (Phase 3)
------------------------------------------------
Mirroring `classification.py`'s documented split between
`ClassificationTier` (how must this be handled?) and `SensitivityCategory`
(what kind of sensitive data is this?), this module defines *two*
masking vocabularies rather than force-fitting Phase 3's engine-level
detail into the Phase 0 `MaskingStrategy` enum:

- :class:`MaskingStrategy` (4 values, unchanged since Phase 0) is the
  coarse, **policy-preview** vocabulary the data catalog
  (`CatalogEntry.masking_requirement`, `libs/contracts/catalog.py`) and
  any future control-plane policy UI reason about — "what family of
  transformation does this tier get, roughly?" It is intentionally
  small and stable so catalog/API consumers never need to know about
  engine internals.
- :class:`MaskingTechnique` (new) is the concrete, **engine-level**
  operation the Phase 3 masking engine
  (`services/data-plane/src/data_plane/masking/`) actually executes for
  a given column. Multiple techniques can implement the same coarse
  `MaskingStrategy` (e.g. `SYNTHETIC_REPLACEMENT` is implemented by
  `FORMAT_PRESERVING_SYNTHETIC`, `EMAIL_MASK`, `PHONE_MASK`,
  `ADDRESS_REPLACEMENT`, or `NAME_REPLACEMENT`, depending on what shape
  the field actually is), and `DETERMINISTIC_TOKENIZATION` is
  implemented by either `HMAC_PSEUDONYMIZATION` or `TOKENIZATION`
  depending on whether the policy wants a raw keyed digest or a
  vault-style `TKN-...` token. See `MaskingRule.technique` and
  `data_plane.masking.policy` for the strategy -> technique mapping.

This is deliberately not a 1:1 renaming for the same reason
`classification.py` gives: collapsing "what family of transform" and
"which concrete operation" into one enum would either make the catalog's
public vocabulary churn every time the engine grows a new technique, or
make the engine unable to express real distinctions the catalog doesn't
need to know about.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.classification import ClassificationTier


class MaskingStrategy(str, Enum):
    """How a value is transformed for a given classification tier.

    DETERMINISTIC_TOKENIZATION: masked = f(real_value, scope, secret_key).
        Same real value + same scope always yields the same masked value,
        preserving joinability. Used for direct identifiers. See ADR-0006.
    GENERALIZATION: reduce precision (e.g., date of birth -> birth year)
        rather than replace the value outright. Commonly used for
        quasi-identifiers.
    SYNTHETIC_REPLACEMENT: replace with an unrelated, generated value that
        carries no relationship to the original at all. Used where the
        policy decides the underlying fact is too sensitive to carry
        through even in de-identified form.
    PASSTHROUGH: value is not modified. Used for non-sensitive columns.
    """

    DETERMINISTIC_TOKENIZATION = "deterministic_tokenization"
    GENERALIZATION = "generalization"
    SYNTHETIC_REPLACEMENT = "synthetic_replacement"
    PASSTHROUGH = "passthrough"


class MaskingTechnique(str, Enum):
    """The concrete, engine-level masking operation (Phase 3).

    See the module docstring ("Two masking vocabularies, on purpose") for
    why this is a separate, finer-grained enum from `MaskingStrategy`.
    Implemented by `data_plane.masking.engine.MaskingEngine`.
    """

    #: Replace with a fixed or format-preserving redaction marker.
    REDACTION = "redaction"
    #: Replace with null/None.
    NULLIFICATION = "nullification"
    #: Unkeyed one-way hash. Deliberately weak (no secret key) -- see
    #: ADR-0006's warning about dictionary/rainbow-table attacks. Never
    #: the default technique for DIRECT_IDENTIFIER columns.
    HASHING = "hashing"
    #: Keyed HMAC digest: masked = HMAC(secret_key, scope + real_value).
    #: Deterministic and, without the key, not feasibly reversible.
    HMAC_PSEUDONYMIZATION = "hmac_pseudonymization"
    #: Deterministic, vault-shaped token (e.g. "TKN-A81F...") produced
    #: through the `data_plane.masking.token_vault.TokenVault`
    #: abstraction -- the technique used for cross-system join keys.
    TOKENIZATION = "tokenization"
    #: Deterministically-seeded, plausibly-shaped fake value for a
    #: generic field (not specifically an email/phone/name/address).
    FORMAT_PRESERVING_SYNTHETIC = "format_preserving_synthetic"
    #: Shift a date by a deterministic, keyed offset.
    DATE_SHIFT = "date_shift"
    #: Format-preserving synthetic replacement specialized for email
    #: addresses.
    EMAIL_MASK = "email_mask"
    #: Format-preserving synthetic replacement specialized for phone
    #: numbers.
    PHONE_MASK = "phone_mask"
    #: Format-preserving synthetic replacement specialized for street
    #: address / city / postal code fields.
    ADDRESS_REPLACEMENT = "address_replacement"
    #: Format-preserving synthetic replacement specialized for person
    #: names.
    NAME_REPLACEMENT = "name_replacement"
    #: Value is not modified.
    PASSTHROUGH = "passthrough"


class MaskingFieldType(str, Enum):
    """The semantic content-shape of a field, used by
    `FORMAT_PRESERVING_SYNTHETIC` (and its named specializations) to pick
    a plausible fake value. Independent of `ClassificationTier`: an SSN
    and an email are both `DIRECT_IDENTIFIER`-tier but need very
    differently-shaped synthetic replacements.
    """

    GENERIC = "generic"
    IDENTIFIER = "identifier"
    SSN = "ssn"
    EMAIL = "email"
    PHONE = "phone"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FULL_NAME = "full_name"
    STREET_ADDRESS = "street_address"
    CITY = "city"
    ZIP_CODE = "zip_code"
    DATE = "date"
    NUMERIC = "numeric"


class MaskingRule(BaseModel):
    """A single tier -> strategy mapping within a policy, optionally
    narrowed to a specific field and carrying the engine-level detail
    Phase 3 needs to actually execute it.

    The `tier`/`strategy`/`scope`/`parameters` fields are unchanged from
    Phase 0 -- a policy consumer that only knows about those four fields
    (e.g. the Phase 2 catalog) keeps working unmodified. Every field
    below is new in Phase 3 and optional, so existing callers that
    construct `MaskingRule(tier=..., strategy=..., scope=...)` are not
    broken.
    """

    tier: ClassificationTier
    strategy: MaskingStrategy
    scope: str = Field(
        ...,
        description=(
            "Joinability scope for deterministic strategies, e.g. "
            "'patient-id-global' or 'qa-claims-env'. Two values masked "
            "under the same scope with the same key produce the same "
            "output; different scopes must not be correlatable. When "
            "`preserve_linkage` is True, every column across every "
            "dataset/source system that carries the same real-world "
            "identifier MUST resolve to the same scope string -- that is "
            "what makes cross-system referential integrity hold (see "
            "docs/adr/0006-deterministic-masking-strategy.md)."
        ),
    )
    parameters: dict[str, str] = Field(
        default_factory=dict,
        description="Strategy-specific parameters (e.g., generalization precision).",
    )
    field_pattern: str | None = Field(
        default=None,
        description=(
            "Optional case-insensitive regex matched against a bare column "
            "name. When set, this rule only applies to columns whose name "
            "matches it, and takes precedence over a tier-wide rule with no "
            "`field_pattern` (see `data_plane.masking.policy.resolve_rule`, "
            "which tries rules in policy order and returns the first match, "
            "most-specific-first by convention). When omitted, this rule is "
            "the tier-wide default for every column at `tier` that no more "
            "specific rule matches."
        ),
    )
    technique: MaskingTechnique | None = Field(
        default=None,
        description=(
            "Concrete engine-level operation to run. If omitted, the engine "
            "picks a default technique from `strategy` (see "
            "`data_plane.masking.policy.DEFAULT_TECHNIQUE_BY_STRATEGY`)."
        ),
    )
    field_type: MaskingFieldType = Field(
        default=MaskingFieldType.GENERIC,
        description=(
            "Semantic shape hint for FORMAT_PRESERVING_SYNTHETIC and its "
            "named specializations (EMAIL_MASK, PHONE_MASK, "
            "ADDRESS_REPLACEMENT, NAME_REPLACEMENT)."
        ),
    )
    preserve_format: bool = Field(
        default=False,
        description=(
            "For REDACTION: replace each character with a redaction "
            "character, keeping the original length/shape, instead of a "
            "fixed marker string."
        ),
    )
    preserve_null: bool = Field(
        default=True,
        description=(
            "If True (default), a real None/null value stays null after "
            "masking rather than being replaced with a masked-looking "
            "'null' value -- masking should never manufacture a fact "
            "('has a value') that was not present in the source. "
            "NULLIFICATION ignores this flag (it always produces null by "
            "definition)."
        ),
    )
    preserve_linkage: bool = Field(
        default=False,
        description=(
            "True when this column participates in cross-row/cross-system "
            "joins that must keep working after masking (e.g. member_id). "
            "Informational/asserted-on by `data_plane.masking.validation`; "
            "the actual join-preserving behavior comes from using the same "
            "deterministic `scope` for every aliased column, not from this "
            "flag alone."
        ),
    )


class MaskingPolicy(BaseModel):
    """A versioned, named set of masking rules.

    Every data-plane masking job resolves and records the exact policy
    version it used (see ARCHITECTURE.md section 3.1 and the lineage
    model), so a masked output is always reproducible and auditable
    against the policy that produced it.
    """

    name: str
    version: int = Field(..., ge=1)
    rules: list[MaskingRule]
    approved_by: str | None = Field(
        default=None, description="Identity that approved this policy version, if approved."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MaskingRunSummary(BaseModel):
    """The shared, typed shape of one `masking_run_summary.json` artifact.

    Phase 18B (`problems_final_review.md` P3-7, tracked since
    `problems_phase_09.md`): before this class existed, both real
    writers of this artifact --
    `data_plane.masking.cli.main` and
    `data_plane.certification.pipeline._write_masking_summary` -- built
    the identical JSON shape by hand with a raw `dict`/`json.dumps`, and
    the one real *reader*,
    `control_plane.artifacts.masking.MaskingRunSummary`, duplicated that
    same shape again as a control-plane-local Pydantic model (explicitly
    documented there as "no shared typed contract... yet"). This class
    is that shared contract: both writers now construct it and call
    `.model_dump_json()`, and the control-plane reader now imports this
    class directly instead of maintaining its own mirror -- one typed
    shape, not three copies of the same field list.
    """

    rows_processed: int = 0
    columns_masked: int = 0
    technique_counts: dict[str, int] = Field(default_factory=dict)
    files_written: list[str] = Field(default_factory=list)
    warning_count: int = 0
    masking_engine_version: str = ""
    policy_name: str | None = None
    policy_version: int | None = None
    validation_passed: bool = False
    validation_checks: list[str] = Field(default_factory=list)
    validation_failures: list[str] = Field(default_factory=list)
