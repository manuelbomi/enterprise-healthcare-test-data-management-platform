"""Security regression test: no HMAC key or key-shaped secret is ever
committed to the git-tracked source tree.

This is the concrete, automated version of `SECURITY.md` rule 2 ("No
real secrets, ever ... not even 'throwaway' ones") for this phase's own
key. It does not merely trust the code's docstrings; it inspects the
actual tracked files via `git ls-files`, exactly like a reviewer or a
pre-commit secret scanner would (`CONTRIBUTING.md` notes a real scanner
is "a future phase" -- this test is this phase's stand-in for one, scoped
to the one secret this phase introduces).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

#: A real key looks like 32+ bytes of hex (64+ hex characters) -- exactly
#: what `secrets.generate_dev_key()` produces. No tracked file should
#: ever contain a bare token that long and that hex-shaped assigned to
#: anything; a real key that long has no legitimate reason to be
#: committed (docs/tests use short, obviously-fake placeholder strings
#: instead -- see every `KEY = b"..."` in this test suite, none of which
#: are 64 hex characters).
_HEX64_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

#: A real, "live-looking" assigned env value: KEY=<64+ hex chars>, with
#: no placeholder wording around it.
_ASSIGNED_SECRET_RE = re.compile(
    r"TDM_MASKING_HMAC_KEY\s*=\s*[\"']?[0-9a-fA-F]{32,}[\"']?"
)

#: Text files only (skip binary fixtures/parquet/sqlite if any ever get
#: tracked, which they should not per .gitignore, but be defensive).
_TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".example", ".sh", ".ps1", ".env",
}


def _git_ls_files() -> list[str]:
    # --cached (already committed/staged) + --others --exclude-standard
    # (new files this phase added that are not yet staged, but WOULD be
    # tracked if committed, i.e. not matched by .gitignore). This is the
    # meaningful set for "will this secret end up in the repo", not just
    # "has it already been committed" -- this phase's own new files
    # (data_plane/masking/*.py, .env.example, ...) are not committed yet
    # (CONTRIBUTING.md/the orchestrating process commits after review),
    # so checking only `--cached` would silently skip everything this
    # phase just wrote.
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


def test_no_dotenv_file_is_git_tracked(tracked_files: list[str]) -> None:
    # Only *.env.example files may be tracked -- a real .env (with a real
    # or even locally-generated key in it) must never be committed. This
    # mirrors the root .gitignore's own `.env` / `.env.*` / `!.env.example`
    # rules -- this test proves those rules are actually effective against
    # the current tracked tree, not just present in .gitignore.
    for path in tracked_files:
        name = Path(path).name
        if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
            pytest.fail(f"A real .env-shaped file is git-tracked: {path}")


def test_env_example_files_contain_only_placeholder_values(tracked_files: list[str]) -> None:
    example_files = [p for p in tracked_files if Path(p).name.endswith(".env.example")]
    assert example_files, "expected at least one .env.example to exist and be tracked"
    for rel_path in example_files:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert not _HEX64_RE.search(text), f"{rel_path} contains a real-looking 64-hex-char secret"
        assert not _ASSIGNED_SECRET_RE.search(text), f"{rel_path} assigns a real-looking secret value"


def test_no_tracked_file_contains_a_real_looking_hmac_key(tracked_files: list[str]) -> None:
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
    assert not offending, f"real-looking HMAC key assignment found in: {offending}"


def test_masking_source_never_hardcodes_a_default_key_literal(tracked_files: list[str]) -> None:
    masking_source_files = [
        p for p in tracked_files
        if p.startswith("services/data-plane/src/data_plane/masking/") and p.endswith(".py")
    ]
    assert masking_source_files, "expected the masking package's source files to be tracked"
    for rel_path in masking_source_files:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert not _HEX64_RE.search(text), f"{rel_path} contains a 64-hex-char literal"


def test_a_freshly_generated_dev_key_is_never_found_in_the_tracked_tree(
    tracked_files: list[str],
) -> None:
    # Belt-and-suspenders: generate a real key the way a developer would,
    # and confirm it does not appear anywhere already committed (it
    # can't, since it's random each run -- this asserts the property
    # rather than assuming it).
    from data_plane.masking.secrets import generate_dev_key

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
