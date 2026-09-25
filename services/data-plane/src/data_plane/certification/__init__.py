"""`data_plane.certification` -- the Certified Test Dataset Pipeline (Phase 6).

Ties together every prior phase's already-real, independently-runnable
engine into one orchestrated pipeline, and adds the work that is genuinely
new to this phase: an independent VALIDATE-stage gate-checking layer, a
CERTIFY stage that produces a machine-readable, tamper-evidenced
`healthcare_tdm_contracts.CertificationReport`, and a PUBLISH stage that is
a real, enforced state transition -- not a convention.

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

This package does not reimplement any earlier phase:

- INGEST is `data_plane.reference_data` (Phase 1).
- PROFILE + CLASSIFY is `data_plane.discovery` (Phase 2).
- SUBSET is `data_plane.subsetting` (Phase 4).
- MASK is `data_plane.masking` (Phase 3).
- GENERATE OPTIONAL SYNTHETIC DATA is `data_plane.synthetic` (Phase 5).

This package calls each of those in sequence (`pipeline.py`) and is
responsible only for the stages after MASK: VALIDATE (`gates.py`), CERTIFY
(`report.py`), and PUBLISH (`state_machine.py`).

**A dataset is not publishable simply because masking ran.** See
`docs/CERTIFICATION_VS_MASKING.md` for the full explanation, and
`problems_phase_03.md` P3-1 for why Phase 3's own masking validation was
always documented as a *precursor* to this phase, not a replacement for
it.

## Module map

| Module | Responsibility |
|---|---|
| `gates.py` | The eleven required certification gates, each an independent re-derivation (not a re-trust) of an earlier phase's claims. |
| `report.py` | `certify()` -- turns gate results into a `CertificationReport` with the correct `CertificationStatus` (`CERTIFIED` only if every gate passed). |
| `state_machine.py` | The enforced six-state `CertificationStatus` lifecycle: `transition()`, `publish()`, `revoke()`. Invalid transitions raise, they are not merely discouraged. |
| `signing.py` | HMAC-based tamper-evidence: `sign_report()` / `verify_report_signature()`. |
| `pipeline.py` | `run_certification_pipeline()` -- the end-to-end INGEST -> ... -> PUBLISH orchestrator. |
| `cli.py` | `python -m data_plane.certification.cli`, the command-line entry point. |
"""

from __future__ import annotations
