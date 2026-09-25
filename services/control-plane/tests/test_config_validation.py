"""Tests for `control_plane.config.Settings`'s Phase 11 validators.

Before this phase, `Settings` was "thin" -- every field had a type
annotation but nothing validated the *value* beyond that (see
`config.py`'s own new module comment). These tests prove a real
misconfiguration now fails fast at construction time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from control_plane.config import Settings


def test_default_settings_are_valid() -> None:
    Settings()  # must not raise


def test_rejects_an_unrecognized_log_level() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        Settings(log_level="VERY_LOUD")


def test_normalizes_log_level_case() -> None:
    settings = Settings(log_level="debug")
    assert settings.log_level == "DEBUG"


def test_rejects_an_api_prefix_missing_the_leading_slash() -> None:
    with pytest.raises(ValidationError, match="api_v1_prefix"):
        Settings(api_v1_prefix="api/v1")


def test_rejects_a_database_url_with_no_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="not-a-real-url-at-all")


def test_rejects_a_lifecycle_database_url_with_no_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(lifecycle_database_url="  ")


def test_accepts_a_real_looking_sqlite_url() -> None:
    settings = Settings(lifecycle_database_url="sqlite:///data/tmp/x.db")
    assert settings.lifecycle_database_url == "sqlite:///data/tmp/x.db"


def test_accepts_a_real_looking_postgres_url() -> None:
    settings = Settings(database_url="postgresql+psycopg://user:pass@host:5432/db")
    assert "postgresql" in settings.database_url


def test_rejects_a_cors_origin_missing_a_scheme() -> None:
    with pytest.raises(ValidationError, match="cors_allowed_origins"):
        Settings(cors_allowed_origins="example.com")


def test_accepts_valid_cors_origins() -> None:
    settings = Settings(cors_allowed_origins="http://localhost:5173,https://tdm.example.org")
    assert settings.cors_allowed_origins_list == ["http://localhost:5173", "https://tdm.example.org"]
