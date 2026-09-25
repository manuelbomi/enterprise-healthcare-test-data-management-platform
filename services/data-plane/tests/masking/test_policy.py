"""Tests for `data_plane.masking.policy`: rule resolution, precedence,
and the cross-system linkage-scope table that makes referential integrity
possible in the first place.
"""

from __future__ import annotations

from healthcare_tdm_contracts import ClassificationTier, MaskingTechnique

from data_plane.masking.policy import (
    DEFAULT_POLICY,
    LINKAGE_SCOPES,
    linkage_scope_for_column,
    resolve_rule,
)


def test_member_id_and_partner_alias_pat_id_share_the_same_linkage_scope() -> None:
    assert linkage_scope_for_column("member_id") == linkage_scope_for_column("pat_id")
    assert linkage_scope_for_column("member_id") == "member-id-global"


def test_every_linkage_alias_maps_to_its_declared_scope() -> None:
    for scope, aliases in LINKAGE_SCOPES.values():
        for alias in aliases:
            assert linkage_scope_for_column(alias) == scope


def test_unknown_column_has_no_linkage_scope() -> None:
    assert linkage_scope_for_column("billed_amount") is None


def test_direct_identifier_member_id_resolves_to_tokenization_with_linkage() -> None:
    resolved = resolve_rule(DEFAULT_POLICY, tier=ClassificationTier.DIRECT_IDENTIFIER, column="member_id")
    assert resolved.technique is MaskingTechnique.TOKENIZATION
    assert resolved.preserve_linkage is True
    assert resolved.scope == "member-id-global"


def test_direct_identifier_ssn_resolves_to_format_preserving_synthetic() -> None:
    resolved = resolve_rule(DEFAULT_POLICY, tier=ClassificationTier.DIRECT_IDENTIFIER, column="ssn")
    assert resolved.technique is MaskingTechnique.FORMAT_PRESERVING_SYNTHETIC
    assert resolved.preserve_linkage is False


def test_non_sensitive_tier_is_always_passthrough_even_for_identifier_shaped_names() -> None:
    # Pharmacy.zip_code and Pharmacy.pharmacy_id are classified
    # NON_SENSITIVE (business/public directory data -- see
    # discovery/schema_rules.py) even though their *names* would match
    # the "zip"/identifier field-pattern rules used for DI/QI tiers. The
    # tier must win: PASSTHROUGH tiers are never re-activated by a
    # field-name coincidence.
    for column in ("zip_code", "pharmacy_id", "city", "email_notes"):
        resolved = resolve_rule(DEFAULT_POLICY, tier=ClassificationTier.NON_SENSITIVE, column=column)
        assert resolved.technique is MaskingTechnique.PASSTHROUGH, column


def test_quasi_identifier_surrogate_keys_get_tokenization_not_generalization() -> None:
    # DATA_GOVERNANCE.md B.2 allows deterministic masking for
    # quasi-identifiers "depending on policy" -- this policy chooses
    # tokenization for surrogate keys that need to keep joining.
    for column in ("claim_id", "coverage_id", "encounter_id", "provider_id", "prescription_id"):
        resolved = resolve_rule(DEFAULT_POLICY, tier=ClassificationTier.QUASI_IDENTIFIER, column=column)
        assert resolved.technique is MaskingTechnique.TOKENIZATION, column
        assert resolved.preserve_linkage is True, column


def test_quasi_identifier_dates_get_date_shift() -> None:
    resolved = resolve_rule(DEFAULT_POLICY, tier=ClassificationTier.QUASI_IDENTIFIER, column="admit_date")
    assert resolved.technique is MaskingTechnique.DATE_SHIFT


def test_field_type_falls_back_to_inference_for_unpinned_generic_fallback_rule() -> None:
    # "billed_amount" has no dedicated _FieldRule, so it hits the tier
    # fallback (field_type=GENERIC on the rule itself), and resolve_rule
    # should fall back to field_types.infer_field_type -> NUMERIC.
    resolved = resolve_rule(
        DEFAULT_POLICY, tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE, column="billed_amount"
    )
    assert resolved.field_type.value == "numeric"


def test_unknown_column_at_a_masked_tier_still_resolves_via_tier_fallback() -> None:
    resolved = resolve_rule(
        DEFAULT_POLICY, tier=ClassificationTier.DIRECT_IDENTIFIER, column="some_never_seen_column"
    )
    assert resolved.technique is not None
