#!/usr/bin/env python3
"""Repo-wide secret-detection scan.

`docs/problems/problems_phase_03.md`'s masking secret ("no secrets committed" test,
`services/data-plane/tests/masking/test_no_secrets_committed.py`) and
`docs/problems/problems_phase_06.md`'s certification signing secret
(`test_certification_no_secrets_committed.py`) each have a real,
automated regression test -- but each is scoped to the one specific
secret its own phase introduced (`TDM_MASKING_HMAC_KEY`,
`TDM_CERTIFICATION_HMAC_KEY`). `CONTRIBUTING.md`'s commit-conventions
section names this gap directly: "Never commit real secrets ... This
is enforced by review, not (yet) by tooling -- a future phase may add
a pre-commit secret scanner." This script is that generalization: a
single, repo-wide scan for secret-shaped content, independent of which
phase/module introduced it, runnable standalone today (`python
scripts/security/detect_secrets.py`) and intended to be wired into a
pre-commit hook and/or CI (Phase 12 -- see `docs/problems/problems_phase_11.md`
P11-3 for why CI wiring itself is out of this phase's scope).

Detection patterns (all conservative -- tuned to avoid false positives
against this repository's own extensive use of realistic-looking
example/fixture data):

- A bare 64+ character hex string (what `secrets.token_hex(32)` -- the
  shape both this repository's HMAC keys use -- produces).
- `<KNOWN_ENV_VAR>=<looks like a real value>` for every secret-shaped
  environment variable this repository actually defines
  (`TDM_MASKING_HMAC_KEY`, `TDM_CERTIFICATION_HMAC_KEY`).
- AWS-shaped access key IDs (`AKIA[0-9A-Z]{16}`).
- PEM-format private key headers (`-----BEGIN ... PRIVATE KEY-----`).
- A generic `(password|secret|api[_-]?key|token)\\s*[:=]\\s*"<12+ char value>"`
  heuristic, deliberately narrow (quoted, assigned, 12+ chars) to avoid
  flagging this file's own docstrings or a short/obviously-fake test
  fixture value.

Usage: `python scripts/security/detect_secrets.py` (exits 1 and prints
findings if anything is flagged, exits 0 with no output otherwise).
Scans `git ls-files --cached --others --exclude-standard` (tracked +
about-to-be-tracked-if-committed files), the same set
`test_no_secrets_committed.py` already established as the meaningful
one for "will this end up in the repo" (see that test's own
docstring).
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_HEX64_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PEM_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_GENERIC_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)\b(password|secret|api[_-]?key|token)\b\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']"
)

#: Every secret-shaped environment variable this repository actually
#: defines. Kept as an explicit, closed list (not a regex over "any
#: all-caps var containing KEY") so a legitimate, non-secret env var
#: name (e.g. `TDM_CONTROL_PLANE_API_V1_PREFIX`) can never trip this
#: check -- see each module's own docstring for why these two exist.
_KNOWN_SECRET_ENV_VARS = ("TDM_MASKING_HMAC_KEY", "TDM_CERTIFICATION_HMAC_KEY")
_ASSIGNED_KNOWN_SECRET_RES = [
    re.compile(rf"{re.escape(var)}\s*=\s*[\"']?[0-9a-fA-F]{{16,}}[\"']?") for var in _KNOWN_SECRET_ENV_VARS
]

_TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".example", ".sh", ".ps1", ".env", ".tf", ".js", ".ts", ".tsx",
}

#: Files that legitimately document/generate secret-shaped strings as
#: part of explaining detection itself (this script and its own test)
#: -- excluded so the scanner does not flag its own pattern source as
#: a finding.
_SELF_EXCLUDED_PATHS = {
    "scripts/security/detect_secrets.py",
    "services/data-plane/tests/platform_integrity/test_secret_detection_script.py",
}


@dataclass
class Finding:
    path: str
    line_number: int
    rule: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_number}: [{self.rule}] {self.excerpt.strip()[:100]}"


def _git_ls_files(repo_root: Path = REPO_ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted({line for line in result.stdout.splitlines() if line.strip()})


def scan_text(path: str, text: str) -> list[Finding]:
    """Scan one file's already-read text content for secret-shaped
    patterns. Pure function (no filesystem/git access) so it is
    directly, cheaply unit-testable against synthetic content --
    see `services/data-plane/tests/platform_integrity/test_secret_detection_script.py`.
    """

    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _HEX64_RE.search(line):
            findings.append(Finding(path, line_number, "hex64", line))
        if _AWS_ACCESS_KEY_RE.search(line):
            findings.append(Finding(path, line_number, "aws_access_key_id", line))
        if _PEM_PRIVATE_KEY_RE.search(line):
            findings.append(Finding(path, line_number, "pem_private_key", line))
        for pattern in _ASSIGNED_KNOWN_SECRET_RES:
            if pattern.search(line):
                findings.append(Finding(path, line_number, "known_secret_env_var_assigned", line))
        match = _GENERIC_ASSIGNED_SECRET_RE.search(line)
        if match:
            findings.append(Finding(path, line_number, "generic_assigned_secret", line))
    return findings


def scan_paths(paths: list[str], *, repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Scan every path in `paths` (relative to `repo_root`) that looks
    like a text file. Missing/unreadable/binary files are skipped, not
    errored -- this mirrors `test_no_secrets_committed.py`'s own
    defensive handling."""

    findings: list[Finding] = []
    for rel_path in paths:
        if rel_path in _SELF_EXCLUDED_PATHS:
            continue
        suffix = Path(rel_path).suffix
        if suffix not in _TEXT_SUFFIXES and not rel_path.endswith(".env.example"):
            continue
        full_path = repo_root / rel_path
        try:
            text = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, OSError):
            continue
        findings.extend(scan_text(rel_path, text))
    return findings


def main() -> int:
    paths = _git_ls_files()
    findings = scan_paths(paths)
    if findings:
        print(f"detect_secrets: {len(findings)} potential secret(s) found:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("detect_secrets: clean -- no secret-shaped content found in the tracked tree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
