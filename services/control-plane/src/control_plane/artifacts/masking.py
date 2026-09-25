"""Read-only repository over `masking_run_summary.json` artifacts
(Phase 3's `data_plane.masking.cli` / `data_plane.certification.pipeline`
output).

`MaskingRunReport` (`data_plane.masking.dataset_masker`) is a data-plane-
local `@dataclass`, not a `libs/contracts` Pydantic model -- unlike
`SubsetManifest`/`SyntheticGenerationManifest`/`CertificationReport`,
there is no shared typed contract for a masking run summary yet (tracked
as a follow-up in `problems_phase_09.md`). `MaskingRunSummary` below is a
control-plane-local Pydantic model that mirrors the exact JSON shape both
`data_plane.masking.cli.main` and
`data_plane.certification.pipeline._write_masking_summary` write --
duplicated, typed parsing of a JSON shape, exactly the same deliberate
cost ADR-0009 already accepts for the catalog artifact ("a small amount
of duplicated logic... the deliberate cost of not sharing an in-process
function across the plane boundary").
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class MaskingArtifactNotAvailableError(RuntimeError):
    """Raised when the configured root contains no masking run artifacts."""


class MaskingRunSummary(BaseModel):
    """Mirrors the JSON object `masking_run_summary.json` contains."""

    rows_processed: int = 0
    columns_masked: int = 0
    technique_counts: dict[str, int] = Field(default_factory=dict)
    files_written: list[str] = Field(default_factory=list)
    warning_count: int = 0
    masking_engine_version: str = ""
    policy_name: str | None = None
    policy_version: int | None = None
    validation_passed: bool = False
    validation_checks: list[str] = Field(default_factory=list)
    validation_failures: list[str] = Field(default_factory=list)


class MaskingRunRecord(BaseModel):
    """One discovered masking run: its summary plus where it was found."""

    source_path: str
    summary: MaskingRunSummary


class MaskingRunRepository:
    """Read-only access to every `masking_run_summary.json` under a
    configured root directory -- see the package docstring
    (`control_plane.artifacts`) for why this scans a directory tree
    rather than reading one fixed path."""

    ARTIFACT_FILENAME = "masking_run_summary.json"

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _discover(self) -> list[MaskingRunRecord]:
        if not self._root.exists():
            raise MaskingArtifactNotAvailableError(
                f"Masking artifact root '{self._root}' does not exist. Run "
                "'python -m data_plane.masking.cli' (see "
                "docs/tutorial/03-masking-and-pseudonymization.md) or the "
                "certification pipeline, then point "
                "TDM_CONTROL_PLANE_MASKING_ARTIFACTS_ROOT at a directory "
                "containing its output."
            )
        records: list[MaskingRunRecord] = []
        for path in sorted(self._root.rglob(self.ARTIFACT_FILENAME)):
            raw = json.loads(path.read_text(encoding="utf-8"))
            records.append(MaskingRunRecord(source_path=str(path), summary=MaskingRunSummary.model_validate(raw)))
        return records

    def list_runs(self) -> list[MaskingRunRecord]:
        return self._discover()

    def get_run(self, source_path: str) -> MaskingRunRecord | None:
        for record in self._discover():
            if record.source_path == source_path:
                return record
        return None


__all__ = [
    "MaskingArtifactNotAvailableError",
    "MaskingRunRecord",
    "MaskingRunRepository",
    "MaskingRunSummary",
]
