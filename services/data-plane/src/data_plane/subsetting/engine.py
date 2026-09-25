"""Top-level orchestration: run one full subsetting job end to end against
the real, on-disk Phase 1 estate.

`run_subsetting` is what the CLI (`cli.py`) and the integration tests
call. It wires together every other module in this package in order:

1. `estate_io.read_estate` -- read the real multi-format estate into memory.
2. `selection.select_population` -- pick the anchor Member population for
   the requested `SubsettingStrategy`.
3. `closure.build_closure` -- graph-walk the referential closure of that
   population across all five source systems.
4. `negative_testing.inject_negative_test_orphan` -- only if the caller
   explicitly opted in.
5. `validation.validate_subset` -- classify every dangling reference found.
6. `writer.write_subset_estate` -- write the subset, mirroring the source
   estate's on-disk layout.
7. `manifest.build_manifest` -- assemble and persist the `SubsetManifest`.

This mirrors `data_plane.masking.dataset_masker.mask_estate`'s role for
masking: the one function a CLI or a future control-plane job submission
calls to run the whole pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from healthcare_tdm_contracts import SubsetManifest, SubsettingStrategy

from data_plane.subsetting.closure import DanglingReference, build_closure
from data_plane.subsetting.estate_io import read_estate
from data_plane.subsetting.manifest import build_manifest
from data_plane.subsetting.negative_testing import inject_negative_test_orphan
from data_plane.subsetting.selection import select_population
from data_plane.subsetting.validation import SubsetValidationReport, validate_subset
from data_plane.subsetting.writer import write_subset_estate


@dataclass
class SubsettingRunResult:
    """Everything a caller (CLI, test, future control-plane job) needs
    from one `run_subsetting` call."""

    manifest: SubsetManifest
    validation: SubsetValidationReport
    files_written: list[Path] = field(default_factory=list)
    out_root: Path = Path()


def _detect_scale_profile(estate_root: Path) -> str:
    """Best-effort read of the source estate's own `manifest.json`
    (written by `reference_data.estate_writer.write_estate`) to record
    which scale profile this subset was drawn from. Falls back to
    `"unknown"` rather than raising -- a missing/foreign manifest.json
    should not block subsetting."""

    manifest_path = estate_root / "manifest.json"
    if not manifest_path.exists():
        return "unknown"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(payload.get("scale_profile", "unknown"))
    except (json.JSONDecodeError, OSError):
        return "unknown"


def run_subsetting(
    estate_root: Path,
    out_root: Path,
    strategy: SubsettingStrategy,
    parameters: dict[str, str],
    *,
    negative_test: bool = False,
    negative_test_relationship: str = "claim.provider_id",
    negative_test_count: int = 1,
    manifest_version: int = 1,
) -> SubsettingRunResult:
    """Run one subsetting job: `strategy`/`parameters` selects the anchor
    Member population from the real estate at `estate_root`, the
    referential closure of that population is written to `out_root`, and
    a `SubsetManifest` is written alongside it as `subset_manifest.json`.
    """

    estate = read_estate(estate_root)
    scale_profile = _detect_scale_profile(estate_root)

    selection = select_population(estate, strategy, parameters)
    closure = build_closure(estate, selection.member_ids)

    negative_dangling: list[DanglingReference] = []
    if negative_test:
        negative_dangling = inject_negative_test_orphan(
            closure, relationship=negative_test_relationship, count=negative_test_count
        )

    validation = validate_subset(closure, negative_dangling)

    files_written = write_subset_estate(closure.selected, out_root)

    manifest = build_manifest(
        scale_profile=scale_profile,
        source_estate=estate,
        closure=closure,
        selection=selection,
        strategy=strategy,
        validation=validation,
        negative_testing=negative_test,
        estate_root=estate_root,
        out_root=out_root,
        version=manifest_version,
    )

    manifest_path = out_root / "subset_manifest.json"
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    files_written.append(manifest_path)

    return SubsettingRunResult(
        manifest=manifest, validation=validation, files_written=files_written, out_root=out_root
    )


__all__ = ["SubsettingRunResult", "run_subsetting"]
