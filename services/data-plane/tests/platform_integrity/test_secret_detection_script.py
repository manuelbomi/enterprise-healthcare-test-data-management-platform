"""Tests for the repo-wide secret-detection script
(`scripts/security/detect_secrets.py`), Phase 11's generalization of
Phase 3's scoped `test_no_secrets_committed.py`.

Two things are proven here: the scanner actually detects secret-shaped
content (a positive-control test, using synthetic content -- never a
real secret), and running it for real against this repository's
current tracked tree comes back clean (the same "run it for real, not
mocked" bar the phase brief sets for its failure-injection tests, even
though this isn't itself one of the eight required scenarios).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "security" / "detect_secrets.py"


def _load_detect_secrets():
    spec = importlib.util.spec_from_file_location("detect_secrets", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["detect_secrets"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def detect_secrets():
    return _load_detect_secrets()


def test_script_exists_and_is_importable(detect_secrets) -> None:
    assert hasattr(detect_secrets, "scan_text")
    assert hasattr(detect_secrets, "scan_paths")
    assert hasattr(detect_secrets, "main")


def test_detects_a_bare_64_char_hex_string(detect_secrets) -> None:
    fake_key = "a" * 64  # shaped like secrets.token_hex(32), never a real key
    findings = detect_secrets.scan_text("fake/path.py", f"SOME_KEY = '{fake_key}'\n")
    assert any(f.rule == "hex64" for f in findings)


def test_detects_an_aws_access_key_id_shape(detect_secrets) -> None:
    findings = detect_secrets.scan_text("fake/path.env", "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n")
    assert any(f.rule == "aws_access_key_id" for f in findings)


def test_detects_a_pem_private_key_header(detect_secrets) -> None:
    findings = detect_secrets.scan_text("fake/path.pem", "-----BEGIN RSA PRIVATE KEY-----\n")
    assert any(f.rule == "pem_private_key" for f in findings)


def test_detects_a_known_secret_env_var_assigned_a_real_looking_value(detect_secrets) -> None:
    findings = detect_secrets.scan_text(
        "fake/.env", "TDM_MASKING_HMAC_KEY=" + "b" * 40 + "\n"
    )
    assert any(f.rule == "known_secret_env_var_assigned" for f in findings)


def test_detects_a_generic_assigned_secret_pattern(detect_secrets) -> None:
    findings = detect_secrets.scan_text(
        "fake/config.py", 'password = "hunter2hunter2"\n'
    )
    assert any(f.rule == "generic_assigned_secret" for f in findings)


def test_does_not_flag_ordinary_short_placeholder_values(detect_secrets) -> None:
    # This is exactly the kind of content this repository's own
    # example/test fixtures use (short, obviously-fake) -- the scanner
    # must not flag it, or it would be too noisy to ever wire into a
    # real pre-commit hook.
    findings = detect_secrets.scan_text(
        "fake/test.py",
        'MASKING_KEY = b"unit-test-only-not-a-real-secret-key-material"\n'
        'password = "short"\n',
    )
    assert findings == []


def test_running_against_the_real_tracked_repository_tree_is_clean(detect_secrets) -> None:
    paths = detect_secrets._git_ls_files(REPO_ROOT)
    findings = detect_secrets.scan_paths(paths, repo_root=REPO_ROOT)
    assert findings == [], f"detect_secrets found potential secrets in the real tree: {findings}"
