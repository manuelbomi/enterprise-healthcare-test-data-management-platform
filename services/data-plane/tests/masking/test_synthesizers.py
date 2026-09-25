"""Tests for `data_plane.masking.synthesizers`: format-preserving
synthetic value generation is plausible, deterministic, and independent
of the shared `Faker` instance's ambient state.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from healthcare_tdm_contracts import MaskingFieldType

from data_plane.masking.synthesizers import synthesize

KEY = b"synth-test-key-0123456789abcdef"


def _digest(scope: str, value: str) -> bytes:
    return hmac.new(KEY, f"{scope}:{value}".encode("utf-8"), hashlib.sha256).digest()


def test_synthesize_is_deterministic_for_the_same_digest() -> None:
    digest = _digest("s", "123-45-6789")
    a = synthesize(MaskingFieldType.SSN, digest, "123-45-6789")
    b = synthesize(MaskingFieldType.SSN, digest, "123-45-6789")
    assert a == b


def test_synthesize_differs_for_different_digests() -> None:
    a = synthesize(MaskingFieldType.SSN, _digest("s", "111-11-1111"), "111-11-1111")
    b = synthesize(MaskingFieldType.SSN, _digest("s", "222-22-2222"), "222-22-2222")
    assert a != b


def test_ssn_shape() -> None:
    result = synthesize(MaskingFieldType.SSN, _digest("s", "1"), "123-45-6789")
    assert re.fullmatch(r"\d{3}-\d{2}-\d{4}", result)


def test_email_shape() -> None:
    result = synthesize(MaskingFieldType.EMAIL, _digest("s", "1"), "a@b.com")
    assert re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", result)


def test_phone_shape() -> None:
    result = synthesize(MaskingFieldType.PHONE, _digest("s", "1"), "555-000-1111")
    assert re.fullmatch(r"\(\d{3}\) \d{3}-\d{4}", result)


def test_zip_shape() -> None:
    result = synthesize(MaskingFieldType.ZIP_CODE, _digest("s", "1"), "94110")
    assert re.fullmatch(r"\d{5}", result)


def test_identifier_shape() -> None:
    result = synthesize(MaskingFieldType.IDENTIFIER, _digest("s", "1"), "SYN-CLM-0000001")
    assert result.startswith("SYN-MASKED-")


def test_numeric_preserves_rough_magnitude_and_sign_agnostic() -> None:
    result = synthesize(MaskingFieldType.NUMERIC, _digest("s", "1"), 250.75)
    assert isinstance(result, float)
    assert 0 <= result <= 501.5 + 1e-6


def test_numeric_int_input_returns_int_output() -> None:
    result = synthesize(MaskingFieldType.NUMERIC, _digest("s", "1"), 3)
    assert isinstance(result, int)


def test_numeric_handles_none_original_without_crashing() -> None:
    result = synthesize(MaskingFieldType.NUMERIC, _digest("s", "1"), None)
    assert isinstance(result, float)


def test_generic_preserves_length_and_char_classes() -> None:
    result = synthesize(MaskingFieldType.GENERIC, _digest("s", "1"), "GRP-99A(x)")
    assert len(result) == len("GRP-99A(x)")
    assert result[3] == "-"


def test_generic_handles_none_and_empty_string() -> None:
    assert synthesize(MaskingFieldType.GENERIC, _digest("s", "1"), None) is None
    assert synthesize(MaskingFieldType.GENERIC, _digest("s", "1"), "") == ""


def test_calling_synthesize_repeatedly_does_not_perturb_unrelated_calls() -> None:
    # Regression guard: reseeding the shared Faker instance per call must
    # not leak sequence state between unrelated field types/digests.
    digest_1 = _digest("s", "value-one")
    digest_2 = _digest("s", "value-two")
    first_pass = [
        synthesize(MaskingFieldType.EMAIL, digest_1, "a"),
        synthesize(MaskingFieldType.SSN, digest_2, "b"),
    ]
    second_pass = [
        synthesize(MaskingFieldType.EMAIL, digest_1, "a"),
        synthesize(MaskingFieldType.SSN, digest_2, "b"),
    ]
    assert first_pass == second_pass
