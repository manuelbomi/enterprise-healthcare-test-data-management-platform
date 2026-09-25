"""Security regression test: no certification HMAC signing key or
key-shaped secret is ever committed to the git-tracked source tree.

Mirrors `tests/masking/test_no_secrets_committed.py` exactly (same
approach, same rationale), scoped to the second secret this repository
now has: `TDM_CERTIFICATION_HMAC_KEY`
(`data_plane.certification.signing`) — a different secret from the
masking HMAC key, with a different blast radius if leaked (see
`signing.py`'s module docstring), so it gets its own independent proof
that it is never committed, rather than assuming the masking test's
coverage extends to it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

_HEX64_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

_ASSIGNED_SECRET_RE = re.compile(
    r"TDM_CERTIFICATION_HMAC_KEY\s*=\s*[\"']?[0-9a-fA-F]{32,}[\"']?"
)

_TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".example", ".sh", ".ps1", ".env",
}


def _git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted({line for line in result.stdout.splitlines() if line.strip()})


@pytest.fixture(scope="module")
def tracked_files() -> list[str]:
    return _git_ls_files()


def test_env_example_contains_only_a_placeholder_certification_key(tracked_files: list[str]) -> None:
    example_files = [p for p in tracked_files if Path(p).name.endswith(".env.example")]
    assert example_files, "expected at least one .env.example to exist and be tracked"
    for rel_path in example_files:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert not _ASSIGNED_SECRET_RE.search(text), (
            f"{rel_path} assigns a real-looking TDM_CERTIFICATION_HMAC_KEY value"
        )


def test_no_tracked_file_contains_a_real_looking_certification_key(tracked_files: list[str]) -> None:
    offending: list[str] = []
    for rel_path in tracked_files:
        suffix = Path(rel_path).suffix
        if suffix not in _TEXT_SUFFIXES and Path(rel_path).name != ".env.example":
            continue
        full_path = REPO_ROOT / rel_path
        try:
            text = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if _ASSIGNED_SECRET_RE.search(text):
            offending.append(rel_path)
    assert not offending, f"real-looking certification signing key assignment found in: {offending}"


def test_certification_source_never_hardcodes_a_default_key_literal(tracked_files: list[str]) -> None:
    certification_source_files = [
        p for p in tracked_files
        if p.startswith("services/data-plane/src/data_plane/certification/") and p.endswith(".py")
    ]
    assert certification_source_files, "expected the certification package's source files to be tracked"
    for rel_path in certification_source_files:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert not _HEX64_RE.search(text), f"{rel_path} contains a 64-hex-char literal"


def test_a_freshly_generated_dev_signing_key_is_never_found_in_the_tracked_tree(
    tracked_files: list[str],
) -> None:
    from data_plane.certification.signing import generate_dev_key

    fresh_key = generate_dev_key()
    for rel_path in tracked_files:
        suffix = Path(rel_path).suffix
        if suffix not in _TEXT_SUFFIXES:
            continue
        try:
            text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        assert fresh_key not in text
