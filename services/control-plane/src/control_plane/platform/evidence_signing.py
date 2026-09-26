"""Keyed HMAC-SHA256 tamper-evidence for an `AuditEvidencePackage`'s
bundle checksum (Phase 18A, resolves `docs/problems/problems_final_review.md` P1-7).

**Before this phase**, `control_plane.domain.evidence.repository`'s
`bundle_checksum` was a plain, UNKEYED `hashlib.sha256` digest --
anyone with database write access alone (no key needed at all) could
edit the underlying rows and regenerate a self-consistent checksum,
strictly *weaker* than `data_plane.certification.signing`'s keyed
HMAC-SHA256 over a `CertificationReport`, even though an
`AuditEvidencePackage` is the artifact `docs/COMPLIANCE_EVIDENCE.md`
says an organization would present to an auditor. This module closes
that inconsistency: the bundle checksum is now a keyed HMAC-SHA256,
computed and verified exactly the same way
`data_plane.certification.signing` already does for a
`CertificationReport` (same algorithm, same canonical-JSON-payload
construction, same key-resolution convention).

**Read `docs/TAMPER_EVIDENCE_LIMITATIONS.md` for the one, honest,
residual limitation this keying does NOT solve** (and which no software
change to this module could solve on its own): both this mechanism and
`data_plane.certification.signing`'s are *detection*, not *prevention*,
mechanisms, and both are only as strong as the secrecy of their signing
key -- anyone with both database/file write access AND the key can
forge a new, internally-consistent signature/checksum for hand-edited
content. Making the two mechanisms consistently keyed (this phase's
fix) means a reader evaluating either one now sees the SAME limitation
stated once, not two different, inconsistently-strength artifacts that
require piecing the difference together themselves.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets as _stdlib_secrets
from collections.abc import Iterable
from pathlib import Path

from healthcare_tdm_contracts import AuditEvidencePackage

#: An independent secret from the masking/certification/JWT-signing
#: keys -- a leaked evidence-package key lets an attacker forge evidence
#: bundles, a different blast radius from any of the others, so it must
#: be independently rotatable, per this repository's established
#: per-purpose-key convention (see `data_plane.masking.secrets`,
#: `data_plane.certification.signing`, `control_plane.platform.auth`).
ENV_VAR = "TDM_EVIDENCE_HMAC_KEY"

#: Mirrors every other key-strength floor in this repository.
MIN_KEY_BYTES = 16


class MissingEvidenceSigningKeyError(RuntimeError):
    """Raised when no HMAC signing key can be resolved."""


class WeakEvidenceSigningKeyError(RuntimeError):
    """Raised when a resolved key is implausibly short to be a real secret."""


def generate_dev_key() -> str:
    """A throwaway, cryptographically random hex key for local
    development/testing only -- mirrors
    `data_plane.certification.signing.generate_dev_key` exactly."""

    return _stdlib_secrets.token_hex(32)  # 256 bits


def _read_dotenv_value(path: Path, var: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == var:
            return value.strip().strip('"').strip("'")
    return None


def _default_search_dirs() -> Iterable[Path]:
    here = Path(__file__).resolve()
    # services/control-plane/src/control_plane/platform/evidence_signing.py
    # -> services/control-plane
    service_root = here.parents[3]
    repo_root = here.parents[5] if len(here.parents) > 5 else service_root
    seen: set[Path] = set()
    for candidate in (Path.cwd(), service_root, repo_root):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def resolve_signing_key(*, search_dirs: Iterable[Path] | None = None) -> bytes:
    """Resolve the evidence-package HMAC key as raw bytes. Resolution
    order mirrors `data_plane.certification.signing.resolve_signing_key`
    exactly (environment variable, then a gitignored `.env` file)."""

    import os

    value = os.environ.get(ENV_VAR)
    source = "environment variable"
    if not value:
        for directory in search_dirs if search_dirs is not None else _default_search_dirs():
            value = _read_dotenv_value(directory / ".env", ENV_VAR)
            if value:
                source = f"{directory / '.env'}"
                break

    if not value:
        raise MissingEvidenceSigningKeyError(
            f"{ENV_VAR} is not set. The control plane refuses to compute or verify an "
            "AuditEvidencePackage bundle checksum without an explicit key (an unkeyed checksum "
            "offers no tamper evidence beyond accidental-corruption detection -- see "
            "docs/TAMPER_EVIDENCE_LIMITATIONS.md).\n"
            "To fix this for local development:\n"
            "  1. Generate a throwaway dev key:\n"
            "       python -m control_plane.platform.evidence_signing --generate-dev-key\n"
            "  2. Export it for this shell session only, e.g.:\n"
            f"       export {ENV_VAR}=<the printed value>\n"
            "     ...or copy services/control-plane/.env.example to "
            "services/control-plane/.env (gitignored) and paste it in.\n"
            "Never hardcode a key in source, and never commit a .env file -- see SECURITY.md."
        )

    encoded = value.encode("utf-8")
    if len(encoded) < MIN_KEY_BYTES:
        raise WeakEvidenceSigningKeyError(
            f"{ENV_VAR} resolved from {source} is only {len(encoded)} bytes long; a real key "
            f"should be at least {MIN_KEY_BYTES} bytes. Generate a proper key with "
            "'python -m control_plane.platform.evidence_signing --generate-dev-key'."
        )
    return encoded


def _canonical_payload(package: AuditEvidencePackage) -> bytes:
    """The exact byte sequence the checksum is computed over: every
    field except `bundle_checksum` itself (checksumming a field that
    includes itself is circular), serialized the same
    `sort_keys=True, separators=(",", ":")` way
    `data_plane.certification.signing._canonical_payload` uses for
    `CertificationReport.integrity_signature`."""

    payload = package.model_dump(mode="json", exclude={"bundle_checksum"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_bundle_checksum(package: AuditEvidencePackage, key: bytes) -> str:
    """Compute the keyed HMAC-SHA256 hex digest for `package` under
    `key`. Phase 18A: this used to be a plain, unkeyed `hashlib.sha256`
    digest -- see this module's docstring for why that was inconsistent
    with `data_plane.certification.signing`'s stronger guarantee for a
    `CertificationReport`, and `docs/TAMPER_EVIDENCE_LIMITATIONS.md` for
    what a keyed HMAC still does not solve."""

    return hmac.new(key, _canonical_payload(package), hashlib.sha256).hexdigest()


def verify_bundle_checksum(package: AuditEvidencePackage, key: bytes) -> bool:
    """True iff `package.bundle_checksum` matches a freshly recomputed,
    keyed checksum over `package`'s current fields under `key`. False
    (never raises) for an empty/missing checksum or a mismatched one."""

    if not package.bundle_checksum:
        return False
    expected = compute_bundle_checksum(package, key)
    return hmac.compare_digest(expected, package.bundle_checksum)


__all__ = [
    "ENV_VAR",
    "MIN_KEY_BYTES",
    "MissingEvidenceSigningKeyError",
    "WeakEvidenceSigningKeyError",
    "compute_bundle_checksum",
    "generate_dev_key",
    "resolve_signing_key",
    "verify_bundle_checksum",
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="control-plane evidence-package HMAC signing key utility (see this module's docstring)."
    )
    parser.add_argument(
        "--generate-dev-key",
        action="store_true",
        help="Print a fresh, throwaway local-dev/test-only signing key and exit.",
    )
    args = parser.parse_args()
    if args.generate_dev_key:
        print(generate_dev_key())
    else:
        parser.print_help()
