"""Tests for `data_plane.certification.signing` -- the tamper-evidence
mechanism for a persisted `CertificationReport`.
"""

from __future__ import annotations

from healthcare_tdm_contracts import CertificationReport, CertificationStatus

from data_plane.certification import signing


def _report(**overrides: object) -> CertificationReport:
    defaults: dict[str, object] = {"dataset_name": "test-dataset"}
    defaults.update(overrides)
    return CertificationReport(**defaults)


def test_sign_then_verify_succeeds(signing_key: bytes) -> None:
    report = _report()
    signed = signing.sign_report(report, signing_key)
    assert signed.integrity_signature is not None
    assert signing.verify_report_signature(signed, signing_key) is True


def test_unsigned_report_never_verifies(signing_key: bytes) -> None:
    report = _report()
    assert report.integrity_signature is None
    assert signing.verify_report_signature(report, signing_key) is False


def test_verifying_with_the_wrong_key_fails(signing_key: bytes) -> None:
    report = _report()
    signed = signing.sign_report(report, signing_key)
    wrong_key = b"a-completely-different-signing-key-0000000000000"
    assert signing.verify_report_signature(signed, wrong_key) is False


def test_hand_editing_the_status_field_after_signing_is_detected(signing_key: bytes) -> None:
    """The core adversarial scenario this module exists for: someone with
    filesystem access to a persisted certification_report.json hand-edits
    `"status": "failed"` to `"status": "certified"` (simulated here as an
    in-memory field edit, exactly equivalent to editing the JSON and
    reloading it) without recomputing the signature. Verification must
    catch this.
    """

    report = _report(status=CertificationStatus.FAILED)
    signed = signing.sign_report(report, signing_key)
    assert signing.verify_report_signature(signed, signing_key) is True

    tampered = signed.model_copy(update={"status": CertificationStatus.CERTIFIED})
    assert signing.verify_report_signature(tampered, signing_key) is False


def test_hand_editing_status_via_json_round_trip_is_detected(signing_key: bytes, tmp_path) -> None:
    """Same attack as above, but through an actual JSON file on disk --
    the realistic shape of the attack this module documents itself as
    defending against."""

    import json

    report = _report(status=CertificationStatus.FAILED)
    signed = signing.sign_report(report, signing_key)

    path = tmp_path / "certification_report.json"
    path.write_text(signed.model_dump_json(indent=2), encoding="utf-8")

    # Simulate a human hand-editing the JSON file directly.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    payload["status"] = "published"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    reloaded = CertificationReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded.status is CertificationStatus.PUBLISHED
    assert signing.verify_report_signature(reloaded, signing_key) is False


def test_raise_if_tampered_raises_on_mismatch(signing_key: bytes) -> None:
    report = _report(status=CertificationStatus.CERTIFIED)
    signed = signing.sign_report(report, signing_key)
    tampered = signed.model_copy(update={"status": CertificationStatus.PUBLISHED})

    import pytest

    with pytest.raises(signing.TamperedCertificationReportError):
        signing.raise_if_tampered(tampered, signing_key)


def test_raise_if_tampered_passes_on_untouched_report(signing_key: bytes) -> None:
    report = _report(status=CertificationStatus.CERTIFIED)
    signed = signing.sign_report(report, signing_key)
    signing.raise_if_tampered(signed, signing_key)  # must not raise


def test_signature_is_deterministic_for_identical_content(signing_key: bytes) -> None:
    report = _report()
    sig1 = signing.compute_signature(report, signing_key)
    sig2 = signing.compute_signature(report, signing_key)
    assert sig1 == sig2


def test_resolve_signing_key_raises_when_unset(monkeypatch) -> None:
    monkeypatch.delenv(signing.ENV_VAR, raising=False)
    import pytest

    with pytest.raises(signing.MissingCertificationKeyError):
        signing.resolve_signing_key(search_dirs=[])


def test_resolve_signing_key_rejects_a_weak_key(monkeypatch) -> None:
    monkeypatch.setenv(signing.ENV_VAR, "short")
    import pytest

    with pytest.raises(signing.WeakCertificationKeyError):
        signing.resolve_signing_key(search_dirs=[])


def test_generate_dev_key_is_never_the_same_twice() -> None:
    assert signing.generate_dev_key() != signing.generate_dev_key()
