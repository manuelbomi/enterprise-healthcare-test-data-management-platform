"""Deterministic masking, pseudonymization, and tokenization (Phase 3).

Applies a resolved `MaskingPolicy`
(`libs/contracts/src/healthcare_tdm_contracts/masking.py`) to a dataset.
Identifier masking is deterministic and keyed -- see
`docs/adr/0006-deterministic-masking-strategy.md` -- so that referential
integrity survives masking both within one table and across every table
and source system that shares the same masking scope.

Module map
-----------
- `secrets` -- resolves the HMAC key from the environment/a gitignored
  `.env` file; never hardcodes one. See `SECURITY.md`.
- `field_types` -- infers a `MaskingFieldType` (email/phone/ssn/name/...)
  from a bare column name, as a fallback for columns the default policy
  doesn't already pin down.
- `synthesizers` -- deterministic, `Faker`-backed format-preserving
  synthetic value generation, seeded from an HMAC digest.
- `token_vault` -- the `TokenVault` abstraction (`MaskingTechnique.
  TOKENIZATION`) and its default, stateless HMAC-derived implementation.
- `engine` -- `MaskingEngine`, which implements every `MaskingTechnique`
  as `masked = f(real_value, scope, secret_key)`.
- `policy` -- the default `MaskingPolicy`/rule-resolution logic, including
  the cross-system linkage-scope table that is the actual mechanism
  behind this phase's referential-integrity requirement.
- `dataset_masker` -- applies `engine` + `policy` to the real, on-disk
  Phase 1 estate, using the real Phase 2 catalog to decide which
  technique masks which column.
- `validation` -- lightweight masking validation (not the full Phase 6
  certification pipeline -- see `docs/problems/problems_phase_03.md` P3-1).
- `cli` -- `python -m data_plane.masking.cli`, the end-to-end entry point.

Certification (the independent, later-phase verifier `ARCHITECTURE.md`
section 2.2 describes) is implemented alongside masking but is a
distinct, later-phase concern -- see `docs/problems/problems_phase_03.md` P3-1 for the
exact scope boundary between this phase's `validation.py` and that
future work.
"""

from data_plane.masking.engine import MaskingEngine
from data_plane.masking.policy import DEFAULT_POLICY

__all__ = ["DEFAULT_POLICY", "MaskingEngine"]
