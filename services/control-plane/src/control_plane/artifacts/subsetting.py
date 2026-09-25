"""Read-only repository over `subset_manifest.json` artifacts (Phase 4's
`data_plane.subsetting.cli` / `data_plane.certification.pipeline`
output). See `control_plane.artifacts` (package docstring) for why this
scans a root directory tree rather than reading one fixed path, and
ADR-0009 for the JSON-artifact-handoff pattern this follows.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from healthcare_tdm_contracts import SubsetManifest
from pydantic import BaseModel


class SubsetArtifactNotAvailableError(RuntimeError):
    """Raised when the configured root contains no subset manifest artifacts."""


class SubsetManifestRecord(BaseModel):
    """One discovered subsetting run: its manifest plus where it was found."""

    source_path: str
    manifest: SubsetManifest


class SubsetManifestRepository:
    """Read-only access to every `subset_manifest.json` under a
    configured root directory."""

    ARTIFACT_FILENAME = "subset_manifest.json"

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _discover(self) -> list[SubsetManifestRecord]:
        if not self._root.exists():
            raise SubsetArtifactNotAvailableError(
                f"Subsetting artifact root '{self._root}' does not exist. Run "
                "'python -m data_plane.subsetting.cli' (see "
                "docs/tutorial/04-subsetting-and-referential-closure.md), then "
                "point TDM_CONTROL_PLANE_SUBSETTING_ARTIFACTS_ROOT at a "
                "directory containing its output."
            )
        records: list[SubsetManifestRecord] = []
        for path in sorted(self._root.rglob(self.ARTIFACT_FILENAME)):
            raw = json.loads(path.read_text(encoding="utf-8"))
            records.append(SubsetManifestRecord(source_path=str(path), manifest=SubsetManifest.model_validate(raw)))
        return records

    def list_manifests(self) -> list[SubsetManifestRecord]:
        return self._discover()

    def get_manifest(self, manifest_id: UUID) -> SubsetManifestRecord | None:
        for record in self._discover():
            if record.manifest.manifest_id == manifest_id:
                return record
        return None


__all__ = [
    "SubsetArtifactNotAvailableError",
    "SubsetManifestRecord",
    "SubsetManifestRepository",
]
