"""Audit Evidence Package aggregation (Phase 13).

See `control_plane.domain.evidence.repository` for the full module
docstring and `docs/adr/0016-audit-evidence-lives-in-control-plane.md`
for why this domain lives here rather than `services/governance-service`.
"""

from control_plane.domain.evidence.repository import (
    EvidenceRepository,
    compute_bundle_checksum,
    verify_bundle_checksum,
)

__all__ = ["EvidenceRepository", "compute_bundle_checksum", "verify_bundle_checksum"]
