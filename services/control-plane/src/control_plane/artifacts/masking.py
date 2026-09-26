"""Read-only repository over `masking_run_summary.json` artifacts
(Phase 3's `data_plane.masking.cli` / `data_plane.certification.pipeline`
output).

`MaskingRunReport` (`data_plane.masking.dataset_masker`) is still a
data-plane-local `@dataclass`, not a `libs/contracts` Pydantic model --
that stays as-is (it is the in-process return value of `mask_estate`,
never itself serialized to disk). What *is* serialized to disk,
`masking_run_summary.json`, now has a real shared contract: Phase 18B
(`problems_final_review.md` P3-7, tracked since `problems_phase_09.md`)
promoted the Pydantic model that used to be defined here, duplicating
the exact JSON shape both `data_plane.masking.cli.main` and
`data_plane.certification.pipeline._write_masking_summary` wrote by
hand, into `healthcare_tdm_contracts.MaskingRunSummary` -- both real
writers now construct that shared class directly (see either module's
own docstring), and this reader now imports the same class rather than
maintaining its own mirror of it. `MaskingRunRecord` below (this
artifact's on-disk location plus its parsed summary) remains
control-plane-local, since "where on disk this repository found it" is
not part of the shared shape any writer produces.
"""

from __future__ import annotations

import json
from pathlib import Path

from healthcare_tdm_contracts import MaskingRunSummary
from pydantic import BaseModel


class MaskingArtifactNotAvailableError(RuntimeError):
    """Raised when the configured root contains no masking run artifacts."""


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
