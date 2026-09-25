"""Read-only repository over `synthetic_generation_manifest.json`
artifacts (Phase 5's `data_plane.synthetic.cli` /
`data_plane.certification.pipeline` output). See `control_plane.artifacts`
(package docstring) for why this scans a root directory tree rather than
reading one fixed path, and ADR-0009 for the JSON-artifact-handoff
pattern this follows.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from healthcare_tdm_contracts import SyntheticGenerationManifest
from pydantic import BaseModel


class SyntheticArtifactNotAvailableError(RuntimeError):
    """Raised when the configured root contains no synthetic generation manifest artifacts."""


class SyntheticManifestRecord(BaseModel):
    """One discovered synthetic scenario generation run: its manifest
    plus where it was found."""

    source_path: str
    manifest: SyntheticGenerationManifest


class SyntheticManifestRepository:
    """Read-only access to every `synthetic_generation_manifest.json`
    under a configured root directory."""

    ARTIFACT_FILENAME = "synthetic_generation_manifest.json"

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _discover(self) -> list[SyntheticManifestRecord]:
        if not self._root.exists():
            raise SyntheticArtifactNotAvailableError(
                f"Synthetic-generation artifact root '{self._root}' does not "
                "exist. Run 'python -m data_plane.synthetic.cli' (see "
                "docs/tutorial/05-synthetic-scenario-generation.md), then "
                "point TDM_CONTROL_PLANE_SYNTHETIC_ARTIFACTS_ROOT at a "
                "directory containing its output."
            )
        records: list[SyntheticManifestRecord] = []
        for path in sorted(self._root.rglob(self.ARTIFACT_FILENAME)):
            raw = json.loads(path.read_text(encoding="utf-8"))
            records.append(
                SyntheticManifestRecord(
                    source_path=str(path), manifest=SyntheticGenerationManifest.model_validate(raw)
                )
            )
        return records

    def list_manifests(self) -> list[SyntheticManifestRecord]:
        return self._discover()

    def get_manifest(self, manifest_id: UUID) -> SyntheticManifestRecord | None:
        for record in self._discover():
            if record.manifest.manifest_id == manifest_id:
                return record
        return None


__all__ = [
    "SyntheticArtifactNotAvailableError",
    "SyntheticManifestRecord",
    "SyntheticManifestRepository",
]
