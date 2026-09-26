"""The default masking policy and rule-resolution logic.

Builds a real `MaskingPolicy` (the `libs/contracts` shape) out of
`MaskingRule`s that carry Phase 3's engine-level detail (`technique`,
`field_type`, `field_pattern`, `preserve_linkage`), and resolves, for a
given `(source_system, dataset, column, tier)`, which rule actually
applies -- the "catalog classification -> masking policy -> masked
output" integration point `ARCHITECTURE.md` section 2.2 describes.

Precedence
-----------
`MaskingPolicy.rules` is an ordered list. `resolve_rule` returns the
*first* rule that matches, so more specific rules (a `field_pattern` that
matches this column) must be listed before the tier-wide default rule
for the same tier. `DEFAULT_POLICY` below is built with that ordering by
construction; `_policy_rules()` is a single function so the ordering
invariant lives in one place.

Cross-system referential integrity (`LINKAGE_SCOPES`)
--------------------------------------------------------
This is the mechanism behind the phase's headline requirement: every
column-name alias that carries the *same* real-world identifier across
every dataset/source system in the Phase 1 estate is mapped to the *same*
scope string. Since `masked = f(real_value, scope, secret_key)`
(`engine.py`), two columns with the same scope and the same real value
always produce the same masked value -- e.g. `member_id` (Postgres
enrollment, Parquet claims, NDJSON clinical lake, CSV PBM extract) and
`pat_id` (the partner feed's legacy v1 alias for the same field) all
resolve to `LINKAGE_SCOPES["member"]`, so a member's masked token is
identical everywhere they appear. See
`services/data-plane/src/data_plane/discovery/scanner.py` and
`writers/partner_writer.py` for where these exact column-name aliases
come from in the real estate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcare_tdm_contracts import (
    ClassificationTier,
    MaskingFieldType,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    MaskingTechnique,
)

from data_plane.masking.field_types import infer_field_type

POLICY_NAME = "phase3-default"
POLICY_VERSION = 1

#: name -> (scope string, column-name aliases that carry that identifier
#: across the estate). Every alias resolves to the same scope, which is
#: what makes cross-system joins keep working after masking.
LINKAGE_SCOPES: dict[str, tuple[str, frozenset[str]]] = {
    "member": (
        "member-id-global",
        frozenset({"member_id", "patient_id", "subscriber_id", "pat_id", "mbr_id"}),
    ),
    "provider": ("provider-id-global", frozenset({"provider_id", "prescriber_provider_id"})),
    "coverage": ("coverage-id-global", frozenset({"coverage_id"})),
    "claim": ("claim-id-global", frozenset({"claim_id"})),
    "claim_line": ("claim-line-id-global", frozenset({"claim_line_id"})),
    "encounter": ("encounter-id-global", frozenset({"encounter_id"})),
    "prescription": ("prescription-id-global", frozenset({"prescription_id"})),
    "lab_result": ("lab-result-id-global", frozenset({"lab_result_id"})),
    "address": ("address-id-global", frozenset({"address_id"})),
}
#: `pharmacy_id`/`plan_id` are deliberately NOT here: both are classified
#: NON_SENSITIVE (business/reference-code identifiers, not patient data --
#: see `schema_rules.py`), so their tier's strategy is PASSTHROUGH and
#: they are never masked at all. Leaving them untouched is *already*
#: consistent everywhere they appear, so no linkage scope is needed.

#: bare column name -> linkage scope string, flattened from
#: `LINKAGE_SCOPES` for O(1) lookup.
_SCOPE_BY_COLUMN: dict[str, str] = {
    alias: scope for scope, aliases in LINKAGE_SCOPES.values() for alias in aliases
}


def linkage_scope_for_column(column: str) -> str | None:
    """Return the shared cross-system scope for `column` if it is a known
    identifier alias, else `None`."""

    return _SCOPE_BY_COLUMN.get(column)


@dataclass(frozen=True)
class _FieldRule:
    """One `field_pattern` -> engine-detail mapping, before it is wrapped
    into a full `MaskingRule` per tier. Kept separate from `MaskingRule`
    itself so the same field-level intent (e.g. "this looks like an
    email") can be expressed once, independent of which `tier`/`strategy`
    a particular catalog run assigns the column (the same field name
    could, in principle, show up in more than one tier across different
    columns)."""

    field_pattern: str
    technique: MaskingTechnique
    field_type: MaskingFieldType = MaskingFieldType.GENERIC
    scope: str | None = None
    preserve_linkage: bool = False
    parameters: dict[str, str] | None = None


#: Field-specific rules, most-specific-first. Applied within whichever
#: tier the catalog assigned the column -- e.g. `ssn` is
#: DIRECT_IDENTIFIER per `schema_rules.py`, and gets
#: FORMAT_PRESERVING_SYNTHETIC/SSN-shaped output; `member_id` is also
#: DIRECT_IDENTIFIER and gets TOKENIZATION with the shared linkage scope.
_FIELD_RULES: list[_FieldRule] = [
    # Identifiers that must keep joining across tables/systems.
    *[
        _FieldRule(
            field_pattern=rf"^{re.escape(alias)}$",
            technique=MaskingTechnique.TOKENIZATION,
            field_type=MaskingFieldType.IDENTIFIER,
            scope=scope,
            preserve_linkage=True,
        )
        for scope, aliases in LINKAGE_SCOPES.values()
        for alias in aliases
    ],
    # Content-shaped direct identifiers -> plausible synthetic replacement.
    _FieldRule(r"(^|_)ssn(_|$)", MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC, MaskingFieldType.SSN),
    _FieldRule(r"e[-_]?mail", MaskingTechnique.EMAIL_MASK, MaskingFieldType.EMAIL),
    _FieldRule(r"phone|fax|mobile|telephone", MaskingTechnique.PHONE_MASK, MaskingFieldType.PHONE),
    _FieldRule(r"^first_name$", MaskingTechnique.NAME_REPLACEMENT, MaskingFieldType.FIRST_NAME),
    _FieldRule(r"^last_name$", MaskingTechnique.NAME_REPLACEMENT, MaskingFieldType.LAST_NAME),
    _FieldRule(
        r"(^|_)(middle|full|patient|member)_name$",
        MaskingTechnique.NAME_REPLACEMENT,
        MaskingFieldType.FULL_NAME,
    ),
    _FieldRule(
        r"(^|_)line1$|(^|_)line2$",
        MaskingTechnique.ADDRESS_REPLACEMENT,
        MaskingFieldType.STREET_ADDRESS,
    ),
    _FieldRule(r"^city$|city_name", MaskingTechnique.ADDRESS_REPLACEMENT, MaskingFieldType.CITY),
    _FieldRule(r"zip", MaskingTechnique.ADDRESS_REPLACEMENT, MaskingFieldType.ZIP_CODE),
    _FieldRule(
        r"\bmrn\b|medical_record",
        MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC,
        MaskingFieldType.IDENTIFIER,
    ),
    _FieldRule(
        r"group_number|account_number|policy_number",
        MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC,
        MaskingFieldType.GENERIC,
    ),
    # Quasi-identifier dates -> deterministic date shift, not tokenization.
    _FieldRule(
        r"_date$|^date_|dob|birth|_dt$|fill_date|admit_date|discharge_date|"
        r"collected_date|resulted_date|service_date|submitted_date|adjudicated_date|"
        r"effective_date|term_date",
        MaskingTechnique.DATE_SHIFT,
        MaskingFieldType.DATE,
    ),
]


def _matches(pattern: str, column: str) -> bool:
    return re.search(pattern, column, re.IGNORECASE) is not None


def _default_technique_for_strategy(strategy: MaskingStrategy) -> MaskingTechnique:
    return {
        MaskingStrategy.DETERMINISTIC_TOKENIZATION: MaskingTechnique.HMAC_PSEUDONYMIZATION,
        MaskingStrategy.GENERALIZATION: MaskingTechnique.DATE_SHIFT,
        MaskingStrategy.SYNTHETIC_REPLACEMENT: MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC,
        MaskingStrategy.PASSTHROUGH: MaskingTechnique.PASSTHROUGH,
    }[strategy]


#: Coarse per-tier default, used only when no `_FieldRule` matched.
DEFAULT_TECHNIQUE_BY_STRATEGY: dict[MaskingStrategy, MaskingTechnique] = {
    strategy: _default_technique_for_strategy(strategy) for strategy in MaskingStrategy
}

_TIER_TO_STRATEGY: dict[ClassificationTier, MaskingStrategy] = {
    ClassificationTier.DIRECT_IDENTIFIER: MaskingStrategy.DETERMINISTIC_TOKENIZATION,
    ClassificationTier.QUASI_IDENTIFIER: MaskingStrategy.GENERALIZATION,
    ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE: MaskingStrategy.SYNTHETIC_REPLACEMENT,
    ClassificationTier.NON_SENSITIVE: MaskingStrategy.PASSTHROUGH,
}

_TIER_TO_SCOPE: dict[ClassificationTier, str] = {
    ClassificationTier.DIRECT_IDENTIFIER: "direct-identifier-default",
    ClassificationTier.QUASI_IDENTIFIER: "quasi-identifier-default",
    ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE: "sensitive-clinical-default",
    ClassificationTier.NON_SENSITIVE: "non-sensitive-default",
}


def _build_default_policy() -> MaskingPolicy:
    rules: list[MaskingRule] = []
    for tier, strategy in _TIER_TO_STRATEGY.items():
        # Field-specific overrides only apply within tiers that are
        # actually masked. NON_SENSITIVE's strategy is PASSTHROUGH by
        # definition (DATA_GOVERNANCE.md B.2) -- e.g. Pharmacy.zip_code
        # and Provider.city are classified NON_SENSITIVE precisely
        # because they are business/directory data, not patient
        # geography (see schema_rules.py), and must stay untouched even
        # though their *names* would otherwise match the "zip"/"city"
        # content-shape rules below. Letting a field-pattern rule
        # override a PASSTHROUGH tier would silently re-introduce
        # masking DATA_GOVERNANCE.md says this tier must not have.
        if strategy is not MaskingStrategy.PASSTHROUGH:
            for field_rule in _FIELD_RULES:
                rules.append(
                    MaskingRule(
                        tier=tier,
                        strategy=strategy,
                        scope=field_rule.scope or _TIER_TO_SCOPE[tier],
                        field_pattern=field_rule.field_pattern,
                        technique=field_rule.technique,
                        field_type=field_rule.field_type,
                        preserve_linkage=field_rule.preserve_linkage,
                        parameters=field_rule.parameters or {},
                    )
                )
        # Tier-wide fallback (no field_pattern): last in this tier's block.
        rules.append(
            MaskingRule(
                tier=tier,
                strategy=strategy,
                scope=_TIER_TO_SCOPE[tier],
                field_pattern=None,
                technique=DEFAULT_TECHNIQUE_BY_STRATEGY[strategy],
                field_type=MaskingFieldType.GENERIC,
                preserve_linkage=False,
            )
        )
    return MaskingPolicy(name=POLICY_NAME, version=POLICY_VERSION, rules=rules)


#: The Phase 3 default policy. A real deployment would load an
#: approved/versioned policy from the control plane instead (see
#: `docs/problems/problems_phase_03.md` P3-3); this constant is this phase's honest
#: stand-in, exactly like `catalog_builder.DEFAULT_MASKING_BY_TIER` was
#: Phase 2's.
DEFAULT_POLICY: MaskingPolicy = _build_default_policy()


@dataclass(frozen=True)
class ResolvedMasking:
    """The fully-resolved engine instructions for one column."""

    technique: MaskingTechnique
    scope: str
    field_type: MaskingFieldType
    preserve_format: bool
    preserve_null: bool
    preserve_linkage: bool
    parameters: dict[str, str]
    rule: MaskingRule


def resolve_rule(
    policy: MaskingPolicy,
    *,
    tier: ClassificationTier,
    column: str,
) -> ResolvedMasking:
    """Resolve which rule in `policy` applies to `column` at `tier`.

    Field-pattern rules for this tier are tried in policy order (most
    specific first, by construction -- see module docstring); the
    tier-wide rule (no `field_pattern`) is the fallback. A field name
    that matches a linkage-scope alias (`linkage_scope_for_column`)
    always wins even if a more general content-shape pattern would also
    match, because referential integrity is a harder requirement than
    "looks plausible" -- this falls out naturally here because linkage
    rules are listed first in `_FIELD_RULES`.
    """

    field_rules = [r for r in policy.rules if r.tier is tier and r.field_pattern is not None]
    fallback = next((r for r in policy.rules if r.tier is tier and r.field_pattern is None), None)

    matched = next((r for r in field_rules if _matches(r.field_pattern, column)), None)
    rule = matched or fallback
    if rule is None:
        raise ValueError(f"No masking rule found for tier={tier!r} in policy {policy.name!r}")

    return ResolvedMasking(
        technique=rule.technique or DEFAULT_TECHNIQUE_BY_STRATEGY[rule.strategy],
        scope=rule.scope,
        field_type=rule.field_type
        if rule.field_type != MaskingFieldType.GENERIC
        else infer_field_type(column),
        preserve_format=rule.preserve_format,
        preserve_null=rule.preserve_null,
        preserve_linkage=rule.preserve_linkage or linkage_scope_for_column(column) is not None,
        parameters=dict(rule.parameters),
        rule=rule,
    )


__all__ = [
    "DEFAULT_POLICY",
    "DEFAULT_TECHNIQUE_BY_STRATEGY",
    "LINKAGE_SCOPES",
    "POLICY_NAME",
    "POLICY_VERSION",
    "ResolvedMasking",
    "linkage_scope_for_column",
    "resolve_rule",
]
