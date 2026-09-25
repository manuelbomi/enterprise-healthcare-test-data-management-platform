"""Read-only JSON-artifact repositories (Phase 9).

Phase 2's `control_plane.catalog.CatalogRepository` established the
pattern (ADR-0009): a data-plane engine writes a typed JSON artifact to
disk; the control plane reads it directly, coupled only through the
shared `libs/contracts` shape, never by importing `data_plane`. Phase 6/7
extended this idea to real, database-backed state
(`control_plane.domain.lifecycle`) for the pieces that had become
genuine metadata-plane concerns -- but four real, already-working
data-plane engines still only produce a JSON artifact and nothing else:
masking (`masking_run_summary.json`), subsetting
(`subset_manifest.json`), synthetic scenario generation
(`synthetic_generation_manifest.json`), and certification
(`certification_report.json`). See `ARCHITECTURE.md`'s Phase 3/4/5/6
notes for why each of those stops at "writes a JSON artifact" today.

This package is the Phase 9 read-only API surface over those four
artifact types, one repository module per type, each following
`CatalogRepository`'s exact shape (`list_*`, `get_*`, a
`*NotAvailableError` the API layer turns into HTTP 503/404, not 500).

Unlike the Phase 2 catalog (exactly one artifact, one configured path),
these engines are run repeatedly, into different output directories
(one per job/demo run -- see `scripts/demo_phase7_lifecycle.py` and
`data_plane.certification.pipeline.run_certification_pipeline`, which
writes `<out_dir>/subset/subset_manifest.json`,
`<out_dir>/masked/masking_run_summary.json`,
`<out_dir>/final/synthetic_generation_manifest.json`, and
`<out_dir>/certification_report.json` for a single pipeline run). So
each repository here is configured with a *root directory* and
recursively scans it (`Path.rglob(<well-known filename>)`) for every
matching artifact under it, rather than a single fixed path -- "every
job run this environment has ever produced," not "the one most recent
catalog." A local/dev/portfolio-scale root directory (a few dozen runs
at most) makes an `rglob` scan on every request perfectly adequate; see
`problems_phase_09.md` for the tracked concurrency/performance caveats
this shares with ADR-0009's catalog design.
"""

from __future__ import annotations

from control_plane.artifacts.certification import (
    CertificationArtifactNotAvailableError,
    CertificationReportRecord,
    CertificationReportRepository,
)
from control_plane.artifacts.masking import (
    MaskingArtifactNotAvailableError,
    MaskingRunRecord,
    MaskingRunSummary,
    MaskingRunRepository,
)
from control_plane.artifacts.subsetting import (
    SubsetArtifactNotAvailableError,
    SubsetManifestRecord,
    SubsetManifestRepository,
)
from control_plane.artifacts.synthetic import (
    SyntheticArtifactNotAvailableError,
    SyntheticManifestRecord,
    SyntheticManifestRepository,
)

__all__ = [
    "CertificationArtifactNotAvailableError",
    "CertificationReportRecord",
    "CertificationReportRepository",
    "MaskingArtifactNotAvailableError",
    "MaskingRunRecord",
    "MaskingRunRepository",
    "MaskingRunSummary",
    "SubsetArtifactNotAvailableError",
    "SubsetManifestRecord",
    "SubsetManifestRepository",
    "SyntheticArtifactNotAvailableError",
    "SyntheticManifestRecord",
    "SyntheticManifestRepository",
]
