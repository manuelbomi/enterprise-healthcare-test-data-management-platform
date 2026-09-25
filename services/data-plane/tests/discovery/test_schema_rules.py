"""Schema-based classification must cover every field of every one of the
14 Phase 1 entities, exactly -- no more, no less. This is the test that
keeps `schema_rules.py` from silently drifting out of sync with
`reference_data/domain.py` as either file changes.
"""

from __future__ import annotations

from data_plane.discovery.schema_rules import SCHEMA_RULES, lookup
from data_plane.reference_data import domain

_ENTITY_CLASSES = {
    "Member": domain.Member,
    "MemberDemographics": domain.MemberDemographics,
    "Address": domain.Address,
    "Plan": domain.Plan,
    "Coverage": domain.Coverage,
    "Provider": domain.Provider,
    "Diagnosis": domain.Diagnosis,
    "Procedure": domain.Procedure,
    "Claim": domain.Claim,
    "ClaimLine": domain.ClaimLine,
    "Pharmacy": domain.Pharmacy,
    "Prescription": domain.Prescription,
    "Encounter": domain.Encounter,
    "LabResult": domain.LabResult,
}


def test_schema_rules_cover_all_fourteen_entities() -> None:
    assert set(SCHEMA_RULES) == set(_ENTITY_CLASSES)


def test_schema_rules_cover_every_field_of_every_entity_exactly() -> None:
    for entity_name, entity_cls in _ENTITY_CLASSES.items():
        domain_fields = set(entity_cls.model_fields)
        schema_fields = set(SCHEMA_RULES[entity_name])
        assert schema_fields == domain_fields, (
            f"{entity_name}: schema_rules has {schema_fields - domain_fields} extra "
            f"and is missing {domain_fields - schema_fields}"
        )


def test_every_schema_rule_has_a_non_empty_reason() -> None:
    for entity_name, fields in SCHEMA_RULES.items():
        for column, rule in fields.items():
            assert rule.reason.strip(), f"{entity_name}.{column} has an empty reason"


def test_lookup_returns_none_for_unknown_entity_or_column() -> None:
    assert lookup("Member", "member_id") is not None
    assert lookup("Member", "not_a_real_field") is None
    assert lookup("NotAnEntity", "anything") is None


def test_known_direct_identifiers_classified_correctly() -> None:
    assert lookup("Member", "ssn").category.value == "direct_identifier"
    assert lookup("Member", "first_name").category.value == "direct_identifier"
    assert lookup("MemberDemographics", "email").category.value == "direct_identifier"
    assert lookup("Address", "line1").category.value == "direct_identifier"


def test_reference_code_table_rows_are_non_sensitive() -> None:
    # Diagnosis/Procedure as free-standing code-vocabulary rows reveal
    # nothing about any specific person.
    assert lookup("Diagnosis", "diagnosis_code").category.value == "non_sensitive"
    assert lookup("Procedure", "procedure_code").category.value == "non_sensitive"


def test_same_field_name_different_entity_can_differ() -> None:
    # A diagnosis_code attached to a specific claim line IS a clinical
    # fact about a specific person; the free-standing code table is not.
    # This is the whole reason schema_rules is keyed by (entity, column)
    # rather than by column name alone.
    assert lookup("Diagnosis", "diagnosis_code").category.value == "non_sensitive"
    assert lookup("ClaimLine", "diagnosis_code").category.value == "phi"
