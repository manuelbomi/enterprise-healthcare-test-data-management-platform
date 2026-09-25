"""Read-only repository over `certification_report.json` artifacts
(Phase 6's `data_plane.certification.cli` /
`data_plane.certification.pipeline.run_certification_pipeline` output).
See `control_plane.artifacts` (package docstring) for why this scans a
root directory tree rather than reading one fixed path, and ADR-0009 for
the JSON-artifact-handoff pattern this follows.

This repository is also how Phase 9's Dataset Detail page resolves
certification evidence for a Phase 7 `DatasetVersion`:
`DatasetVersion.certification_report_id` is looked up here via
`get_report`, the same way it is looked up in-process by
`scripts/demo_phase7_lifecycle.py`-style callers, just over HTTP instead
of a shared Python object -- see `api/v1/certification.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from healthcare_tdm_contracts import CertificationReport
from pydantic import BaseModel


class CertificationArtifactNotAvailableError(RuntimeError):
    """Raised when the configured root contains no certification report artifacts."""


class CertificationReportRecord(BaseModel):
    """One discovered certification run: its report plus where it was found."""

    source_path: str
    report: CertificationReport


class CertificationReportRepository:
    """Read-only access to every `certification_report.json` under a
    configured root directory."""

    ARTIFACT_FILENAME = "certification_report.json"

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _discover(self) -> list[CertificationReportRecord]:
        if not self._root.exists():
            raise CertificationArtifactNotAvailableError(
                f"Certification artifact root '{self._root}' does not exist. "
                "Run 'python -m data_plane.certification.cli' (see "
                "docs/tutorial/06-certification-pipeline.md), then point "
                "TDM_CONTROL_PLANE_CERTIFICATION_ARTIFACTS_ROOT at a "
                "directory containing its output."
            )
        records: list[CertificationReportRecord] = []
        for path in sorted(self._root.rglob(self.ARTIFACT_FILENAME)):
            raw = json.loads(path.read_text(encoding="utf-8"))
            records.append(
                CertificationReportRecord(source_path=str(path), report=CertificationReport.model_validate(raw))
            )
        return records

    def list_reports(self) -> list[CertificationReportRecord]:
        return self._discover()

    def get_report(self, report_id: UUID) -> CertificationReportRecord | None:
        for record in self._discover():
            if record.report.report_id == report_id:
                return record
        return None


__all__ = [
    "CertificationArtifactNotAvailableError",
    "CertificationReportRecord",
    "CertificationReportRepository",
]
