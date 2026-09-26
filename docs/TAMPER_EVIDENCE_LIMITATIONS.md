# Tamper-evidence limitations (read this once, for both mechanisms)

This platform has exactly two tamper-evidence mechanisms:

| Mechanism | Protects | Module | Algorithm |
|---|---|---|---|
| Certification report signature | `healthcare_tdm_contracts.CertificationReport.integrity_signature` | `data_plane.certification.signing` | Keyed HMAC-SHA256 |
| Evidence package checksum | `healthcare_tdm_contracts.AuditEvidencePackage.bundle_checksum` | `control_plane.platform.evidence_signing` | Keyed HMAC-SHA256 (Phase 18A -- see below) |

Before Phase 18A, these two mechanisms were **inconsistently strong**:
the certification signature was a keyed HMAC (forging it required both
file access and the signing key), but the evidence-package checksum was
a plain, unkeyed `hashlib.sha256` digest (forging it required only
database write access -- no key at all). `docs/problems/problems_final_review.md`
P1-7 named this inconsistency as a real, unresolved gap: an auditor
relying on either artifact needed to understand a subtle difference in
strength between two things that otherwise look like the same kind of
guarantee.

**Phase 18A's fix**: the evidence-package checksum is now also a keyed
HMAC-SHA256, computed and verified the same way the certification
signature already was. Both mechanisms are now consistently strong.

## The one, honest, residual limitation (this is the part a keyed HMAC does NOT solve)

**Both mechanisms are *detection*, not *prevention*, mechanisms, and
both are only as strong as the secrecy of their signing key.**

Concretely: anyone who has **both** (a) write access to the
database/file holding the signed artifact, **and** (b) the relevant
signing key, can forge a new, internally-consistent
signature/checksum for hand-edited content, and neither mechanism can
tell the difference. Making both mechanisms keyed closes the gap where
one of them could be forged with *database access alone, no key
needed* -- it does not, and cannot, close the gap where an attacker has
both. That would require the signing key to live somewhere the
database-holding party cannot also read it (a real external KMS/HSM
integration with hardware- or service-enforced key isolation, per-signer
scoped credentials, etc.) -- explicitly out of scope for this
repository, for the same reason no real cloud credentials exist
anywhere else in it (`SECURITY.md`, `THREAT_MODEL.md` section 4). Both
signing modules' own docstrings link back to this file rather than each
restating (and risking inconsistently restating) this same limitation.

## What this means in practice

- If you are evaluating this platform's evidence for a real compliance
  program: both `integrity_signature` and `bundle_checksum` tell you
  "this artifact has not been modified since it was signed/checksummed
  by someone holding the key," not "no one with database access could
  possibly have forged this." The second, stronger claim needs a real
  KMS/HSM-backed signer this repository does not implement.
- If you are extending this platform: do not add a third tamper-evidence
  mechanism with a different strength than these two without updating
  this file -- the whole point of this document is that a reader should
  only ever need to learn this limitation once, not re-derive it per
  artifact.
- Neither mechanism claims to be a cryptographic non-repudiation
  signature (public/private keypair, independently verifiable without
  sharing a secret) -- see `docs/interview/tradeoffs.md` item 3 and
  `docs/problems/problems_phase_13.md` P13-2 for why that is real future work, not
  something either mechanism today pretends to be.
