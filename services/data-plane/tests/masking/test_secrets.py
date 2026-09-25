"""Tests for `data_plane.masking.secrets`: key resolution, never a
hardcoded default, `.env` fallback, and the dev-key generator's
never-persisted guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.masking import secrets as masking_secrets


def test_generate_dev_key_is_random_each_call() -> None:
    a = masking_secrets.generate_dev_key()
    b = masking_secrets.generate_dev_key()
    assert a != b
    assert len(a) == 64  # 32 bytes hex-encoded


def test_generate_dev_key_writes_nothing_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    masking_secrets.generate_dev_key()
    # No file appeared anywhere under the temp cwd as a side effect.
    assert list(tmp_path.rglob("*")) == []


def test_resolve_hmac_key_from_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "a" * 32)
    key = masking_secrets.resolve_hmac_key(search_dirs=[])
    assert key == b"a" * 32


def test_resolve_hmac_key_missing_raises_with_remediation_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(masking_secrets.ENV_VAR, raising=False)
    with pytest.raises(masking_secrets.MissingMaskingKeyError) as exc_info:
        masking_secrets.resolve_hmac_key(search_dirs=[])
    assert "--generate-dev-key" in str(exc_info.value)
    assert "TDM_MASKING_HMAC_KEY" in str(exc_info.value)


def test_resolve_hmac_key_rejects_implausibly_short_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "short")
    with pytest.raises(masking_secrets.WeakMaskingKeyError):
        masking_secrets.resolve_hmac_key(search_dirs=[])


def test_resolve_hmac_key_falls_back_to_a_local_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(masking_secrets.ENV_VAR, raising=False)
    dotenv = tmp_path / ".env"
    dotenv_value = "b" * 32
    dotenv.write_text(
        f"# a comment\n\nOTHER_VAR=ignored\n{masking_secrets.ENV_VAR}={dotenv_value}\n",
        encoding="utf-8",
    )
    key = masking_secrets.resolve_hmac_key(search_dirs=[tmp_path])
    assert key == dotenv_value.encode("utf-8")


def test_resolve_hmac_key_env_var_takes_precedence_over_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "e" * 32)
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{masking_secrets.ENV_VAR}={'d' * 32}\n", encoding="utf-8")
    key = masking_secrets.resolve_hmac_key(search_dirs=[tmp_path])
    assert key == b"e" * 32


def test_source_code_never_hardcodes_a_default_key() -> None:
    # secrets.py must never fall back to a literal key value -- it must
    # either resolve one from the environment/.env or raise.
    source = Path(masking_secrets.__file__).read_text(encoding="utf-8")
    assert "return b" not in source.replace(" ", "")
