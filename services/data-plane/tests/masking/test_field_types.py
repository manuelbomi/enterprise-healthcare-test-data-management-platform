"""Tests for `data_plane.masking.field_types.infer_field_type`."""

from __future__ import annotations

from healthcare_tdm_contracts import MaskingFieldType

from data_plane.masking.field_types import infer_field_type


def test_infers_common_field_types() -> None:
    assert infer_field_type("ssn") is MaskingFieldType.SSN
    assert infer_field_type("email") is MaskingFieldType.EMAIL
    assert infer_field_type("phone") is MaskingFieldType.PHONE
    assert infer_field_type("first_name") is MaskingFieldType.FIRST_NAME
    assert infer_field_type("last_name") is MaskingFieldType.LAST_NAME
    assert infer_field_type("zip_code") is MaskingFieldType.ZIP_CODE
    assert infer_field_type("city") is MaskingFieldType.CITY
    assert infer_field_type("line1") is MaskingFieldType.STREET_ADDRESS
    assert infer_field_type("member_id") is MaskingFieldType.IDENTIFIER
    assert infer_field_type("pat_id") is MaskingFieldType.IDENTIFIER
    assert infer_field_type("admit_date") is MaskingFieldType.DATE
    assert infer_field_type("billed_amount") is MaskingFieldType.NUMERIC


def test_unrecognized_column_falls_back_to_generic() -> None:
    assert infer_field_type("some_totally_unknown_column") is MaskingFieldType.GENERIC


def test_case_insensitive() -> None:
    assert infer_field_type("SSN") is MaskingFieldType.SSN
    assert infer_field_type("Email") is MaskingFieldType.EMAIL
