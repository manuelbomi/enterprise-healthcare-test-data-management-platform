"""Tamper-evidence for a persisted `CertificationReport`.

A `CertificationReport` is written to disk as JSON
(`certification_report.json`, mirroring `subset_manifest.json` and
`masking_run_summary.json`'s pattern from Phases 3/4). Anyone with
filesystem access to that file can hand-edit it -- for example, changing
`"status": "failed"` to `"status": "certified"`, or `"certified"` to
`"published"` without ever calling `state_machine.publish()`. This module
is this phase's answer to that specific attack: a keyed HMAC-SHA256
signature over the report's substantive fields, computed at CERTIFY time
(and re-computed at every subsequent status transition), verified before
`state_machine.transition` accepts a report as its current, trustworthy
state.

**Honest limitation** (documented in full, once, at
`docs/TAMPER_EVIDENCE_LIMITATIONS.md` -- read it rather than relying on
this summary): this is a *detection* mechanism, not a *prevention*
mechanism, and it is only as strong as the secrecy of the signing key.
Anyone who has both write access to the report file **and** the
signing key can forge a new, internally-consistent signature for a
hand-edited report and this module cannot tell the difference -- exactly
the same tradeoff ADR-0006 documents for the masking HMAC key, and the
exact same limitation `control_plane.platform.evidence_signing`
documents for the Phase 13 `AuditEvidencePackage.bundle_checksum` (Phase
18A made that mechanism a keyed HMAC too, matching this one, closing the
inconsistency `docs/problems/problems_final_review.md` P1-7 found between them). A
production deployment would keep this key in the security/governance
plane's secrets provider (not implemented yet -- `docs/problems/problems_phase_03.md`
P3-2 tracks the same gap for the masking vault) and would likely also
append signed events to an append-only audit log
(`healthcare_tdm_contracts.AuditEvent`) rather than relying solely on a
single signature field on a single file, so a forged file could still be
caught by cross-referencing the audit trail. Neither of those exists yet;
this module is deliberately honest about being a teaching-grade
demonstration of the *mechanism*, not a hardened, production control.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable
from pathlib import Path

import secrets as _stdlib_secrets

from healthcare_tdm_contracts import CertificationReport

ENV_VAR = "TDM_CERTIFICATION_HMAC_KEY"

#: Minimum acceptable key length in bytes, mirroring
#: `data_plane.masking.secrets.MIN_KEY_BYTES`.
MIN_KEY_BYTES = 16


class MissingCertificationKeyError(RuntimeError):
    """Raised when no HMAC signing key can be resolved."""


class WeakCertificationKeyError(RuntimeError):
    """Raised when a resolved key is implausibly short to be a real secret."""


class TamperedCertificationReportError(RuntimeError):
    """Raised when a report's `integrity_signature` does not match a
    freshly recomputed signature over its current fields -- the report
    was modified (by hand or otherwise) after it was last signed."""


def generate_dev_key() -> str:
    """A throwaway, cryptographically random hex key for local
    development/testing only -- mirrors
    `data_plane.masking.secrets.generate_dev_key` exactly, including its
    "never persisted by this function" guarantee."""

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
    # services/data-plane/src/data_plane/certification/signing.py -> services/data-plane
    service_root = here.parents[3]
    repo_root = here.parents[5] if len(here.parents) > 5 else service_root
    seen: set[Path] = set()
    for candidate in (Path.cwd(), service_root, repo_root):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def resolve_signing_key(*, search_dirs: Iterable[Path] | None = None) -> bytes:
    """Resolve the certification signing key as raw bytes.

    Resolution order mirrors `data_plane.masking.secrets.resolve_hmac_key`
    exactly (environment variable, then a gitignored `.env` file). Kept as
    an independent function (not a shared import) rather than reusing the
    masking module's key -- a certification signing key and a masking
    encryption/pseudonymization key are different secrets with different
    blast radii if leaked (see this module's docstring), so they must be
    independently rotatable.
    """

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
        raise MissingCertificationKeyError(
            f"{ENV_VAR} is not set. The certification pipeline refuses to sign a report "
            "without an explicit key (an unsigned report offers no tamper evidence at all).\n"
            "To fix this for local development:\n"
            "  1. Generate a throwaway dev key:\n"
            "       python -m data_plane.certification.cli --generate-dev-key\n"
            "  2. Export it for this shell session only, e.g.:\n"
            f"       export {ENV_VAR}=<the printed value>\n"
            "     ...or copy services/data-plane/.env.example to "
            "services/data-plane/.env (gitignored) and paste it in.\n"
            "Never hardcode a key in source, and never commit a .env file -- see SECURITY.md."
        )

    encoded = value.encode("utf-8")
    if len(encoded) < MIN_KEY_BYTES:
        raise WeakCertificationKeyError(
            f"{ENV_VAR} resolved from {source} is only {len(encoded)} bytes long; a real key "
            f"should be at least {MIN_KEY_BYTES} bytes. Generate a proper key with "
            "'python -m data_plane.certification.cli --generate-dev-key'."
        )
    return encoded


def _canonical_payload(report: CertificationReport) -> bytes:
    """The exact, stable byte sequence a signature is computed over: every
    substantive field of `report` EXCEPT `integrity_signature` itself
    (signing a field that includes itself is circular) and `updated_at`
    (a signature must be stable across a no-op re-read/re-save, and
    `updated_at` is bookkeeping, not a substantive fact about the
    dataset's certification -- every field that *does* change meaning,
    including `status` and `status_history`, is included).
    """

    payload = report.model_dump(mode="json", exclude={"integrity_signature", "updated_at"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_signature(report: CertificationReport, key: bytes) -> str:
    """Compute (but do not attach) the HMAC-SHA256 hex digest for `report`
    under `key`. Pure function: same report content + same key always
    produces the same signature, exactly the determinism property
    `docs/adr/0006-deterministic-masking-strategy.md` establishes for
    masking, applied here to certification evidence instead of data
    values."""

    return hmac.new(key, _canonical_payload(report), hashlib.sha256).hexdigest()


def sign_report(report: CertificationReport, key: bytes) -> CertificationReport:
    """Return a copy of `report` with `integrity_signature` set to a fresh
    signature over its current fields. Must be called again after every
    field change that should be covered by the signature (in particular,
    every `state_machine.transition`)."""

    signature = compute_signature(report, key)
    return report.model_copy(update={"integrity_signature": signature})


def verify_report_signature(report: CertificationReport, key: bytes) -> bool:
    """True iff `report.integrity_signature` matches a freshly recomputed
    signature over `report`'s current fields. False (never raises) for an
    unsigned report (`integrity_signature is None`) or a mismatched one --
    callers that need a hard failure should use
    `raise_if_tampered` instead."""

    if report.integrity_signature is None:
        return False
    expected = compute_signature(report, key)
    return hmac.compare_digest(expected, report.integrity_signature)


def raise_if_tampered(report: CertificationReport, key: bytes) -> None:
    """Raise `TamperedCertificationReportError` unless `report`'s
    signature verifies. This is the function
    `data_plane.certification.state_machine.transition` calls before
    accepting a report as its authoritative current state -- the concrete
    mechanism behind "a hand-edited certification report JSON file is
    caught, not silently trusted."""

    if not verify_report_signature(report, key):
        raise TamperedCertificationReportError(
            f"Certification report {report.report_id} failed signature verification -- its "
            "content does not match its recorded integrity_signature. This report has been "
            "modified since it was last signed (directly edited, or signed under a different "
            "key) and must not be trusted or transitioned. Re-run certification from scratch."
        )


__all__ = [
    "ENV_VAR",
    "MIN_KEY_BYTES",
    "MissingCertificationKeyError",
    "TamperedCertificationReportError",
    "WeakCertificationKeyError",
    "compute_signature",
    "generate_dev_key",
    "raise_if_tampered",
    "resolve_signing_key",
    "sign_report",
    "verify_report_signature",
]
