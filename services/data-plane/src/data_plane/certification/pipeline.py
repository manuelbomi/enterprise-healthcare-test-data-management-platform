"""`run_certification_pipeline` -- the end-to-end orchestrator.

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

This function calls each prior phase's real, already-implemented engine
in sequence, against a real estate -- it does not reimplement any of
them:

1. **INGEST** -- `data_plane.reference_data` generates the estate (or an
   existing `estate_dir` is reused, so this pipeline can also certify a
   dataset someone else already ingested).
2. **PROFILE + CLASSIFY** -- `data_plane.discovery` scans the estate and
   classifies every column into the data catalog.
3. **SUBSET** -- `data_plane.subsetting` selects a referentially closed
   population.
4. **MASK** -- `data_plane.masking` applies the policy-driven masking
   engine to the subset, using the catalog from step 2.
5. **GENERATE OPTIONAL SYNTHETIC DATA** -- `data_plane.synthetic`
   augments the masked subset with requested scenarios, if any were
   requested.
6. **VALIDATE** -- `data_plane.certification.gates` runs all eleven
   required gates against the real artifacts every step above produced.
7. **CERTIFY** -- `data_plane.certification.report.certify` decides
   `CERTIFIED` vs. `FAILED` from the gate results, signs the report.
8. **PUBLISH** -- only performed if `auto_publish=True` **and** the
   report is `CERTIFIED`; a `FAILED` report is never auto-published (and
   `state_machine.publish` would reject the attempt outright even if
   something tried).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from healthcare_tdm_contracts import (
    CertificationReport,
    MaskingPolicy,
    ScenarioType,
    SubsettingStrategy,
    SyntheticGenerationManifest,
)

from data_plane.certification import gates as g
from data_plane.certification import report as report_mod
from data_plane.certification import state_machine
from data_plane.discovery.catalog_builder import build_catalog, write_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate
from data_plane.masking.dataset_masker import MaskingRunReport, mask_estate
from data_plane.masking.engine import MaskingEngine
from data_plane.masking.policy import DEFAULT_POLICY
from data_plane.masking.validation import ValidationReport as MaskingValidationReport
from data_plane.masking.validation import validate_masking_run
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import get_scale_profile
from data_plane.subsetting.engine import run_subsetting
from data_plane.subsetting.estate_io import read_estate
from data_plane.synthetic.engine import generate_synthetic_scenarios


@dataclass
class CertificationPipelineResult:
    """Everything a caller (CLI, test) needs from one full pipeline run."""

    report: CertificationReport
    report_path: Path
    estate_dir: Path
    catalog_path: Path
    subset_dir: Path
    masked_dir: Path
    final_dir: Path


def _numeric_column_values(estate, entity: str, column: str) -> list[float]:
    """Every real, present, numeric value of `column` across `entity`'s
    rows in `estate` (a `data_plane.subsetting.estate_io.RawEstate`) --
    used by `check_distribution_shape` (Phase 18A / P1-9) to compare a
    column's value distribution before vs. after masking. Non-numeric/
    null values are skipped (never coerced), matching this pipeline's
    existing "never silently fabricate a value" convention."""

    container = getattr(estate, entity, None)
    if container is None:
        return []
    rows = container.all_rows() if hasattr(container, "all_rows") else container
    values: list[float] = []
    for row in rows:
        value = row.get(column)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def _build_row_count_trail(
    source_counts: dict[str, int],
    selected_counts: dict[str, int],
    final_counts: dict[str, int],
) -> dict[str, str]:
    entities = sorted(set(source_counts) | set(selected_counts) | set(final_counts))
    return {
        entity: (
            f"source={source_counts.get(entity, 0)} "
            f"selected={selected_counts.get(entity, 0)} "
            f"final={final_counts.get(entity, 0)}"
        )
        for entity in entities
    }


def run_certification_pipeline(
    out_dir: Path,
    *,
    estate_dir: Path | None = None,
    scale: str = "tiny",
    seed: int = 20240101,
    subset_strategy: SubsettingStrategy = SubsettingStrategy.FIXED_POPULATION,
    subset_parameters: dict[str, str] | None = None,
    masking_key: bytes,
    masking_policy: MaskingPolicy | None = None,
    synthetic_scenarios: list[ScenarioType] | None = None,
    synthetic_counts: dict[ScenarioType, int] | None = None,
    strict_orphans: bool = False,
    max_allowed_orphans: int | None = None,
    dataset_name: str | None = None,
    actor: str = "certification-pipeline",
    signing_key: bytes | None = None,
    auto_publish: bool = False,
) -> CertificationPipelineResult:
    """Run one full INGEST -> ... -> CERTIFY (-> PUBLISH) certification
    pipeline, writing every stage's real output under `out_dir`.

    `masking_key` is required explicitly (never resolved from the
    environment inside this function) so a caller -- a test, the CLI --
    controls exactly which key is used and this module has no hidden
    dependency on process environment state, mirroring how
    `data_plane.masking.engine.MaskingEngine` itself takes a key rather
    than resolving one. `signing_key`, if omitted, produces an unsigned
    report (see `signing.py`'s module docstring for why this is an
    honest, documented degradation rather than a silent one).
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    policy = masking_policy or DEFAULT_POLICY
    subset_parameters = subset_parameters or {}

    # -- 1. INGEST ----------------------------------------------------
    if estate_dir is None:
        estate_dir = out_dir / "estate"
        profile = get_scale_profile(scale)
        generator = EstateGenerator(profile, DEFAULT_EDGE_CASE_CONFIG, seed=seed)
        generated = generator.generate()
        write_estate(generated, estate_dir)

    # -- 2. PROFILE + CLASSIFY ----------------------------------------
    catalog_path = out_dir / "catalog.json"
    columns = scan_estate(estate_dir)
    catalog_entries = build_catalog(columns, ClassificationEngine())
    write_catalog(catalog_entries, catalog_path)

    # -- 3. SUBSET ------------------------------------------------------
    subset_dir = out_dir / "subset"
    subset_result = run_subsetting(estate_dir, subset_dir, subset_strategy, subset_parameters)
    subset_manifest = subset_result.manifest

    # -- 4. MASK ----------------------------------------------------------
    masked_dir = out_dir / "masked"
    masking_engine = MaskingEngine(key=masking_key)
    masking_report = mask_estate(subset_dir, catalog_entries, masked_dir, masking_engine, policy=policy)
    masking_validation = validate_masking_run(linkage_samples=masking_report.linkage_samples)
    masking_summary_path = masked_dir / "masking_run_summary.json"
    _write_masking_summary(masking_summary_path, masking_report, masking_validation, policy)

    # -- 5. GENERATE OPTIONAL SYNTHETIC DATA ------------------------------
    synthetic_manifest: SyntheticGenerationManifest | None = None
    synthetic_manifest_path: Path | None = None
    if synthetic_scenarios:
        final_dir = out_dir / "final"
        synthetic_result = generate_synthetic_scenarios(
            final_dir,
            synthetic_scenarios,
            base_estate_dir=masked_dir,
            counts=synthetic_counts,
            seed=seed,
        )
        synthetic_manifest = synthetic_result.manifest
        synthetic_manifest_path = final_dir / "synthetic_generation_manifest.json"
    else:
        final_dir = masked_dir

    # Phase 18A (P1-9): read SUBSET's own pre-mask output back from disk
    # (the same physical layout `final_dir` uses) so
    # `check_distribution_shape` below can compare a real numeric
    # column's value distribution before vs. after MASK/optional
    # synthetic augmentation -- neither side is re-derived or
    # hand-built, both are read straight from what earlier pipeline
    # stages actually wrote.
    subset_estate = read_estate(subset_dir)

    final_estate = read_estate(final_dir)
    final_counts = final_estate.row_counts()
    # What the pipeline's OWN last-run stage claims the final estate
    # contains: the synthetic-generation manifest's total if that stage
    # ran (synthetic augmentation legitimately adds rows on top of
    # SUBSET's counts -- see `check_row_count_reconciliation`'s >=
    # semantics for that comparison instead), otherwise SUBSET's own
    # `selected_counts`. `check_schema_validation` re-reads the estate
    # from disk and compares against THIS, catching a read/write
    # inconsistency in the pipeline's own last write step -- a different,
    # narrower question than row-count *reconciliation* across stages.
    expected_final_counts = (
        synthetic_manifest.total_row_counts if synthetic_manifest is not None else subset_manifest.selected_counts
    )

    # -- 6. VALIDATE ------------------------------------------------------
    gate_results = [
        g.check_phi_pii_policy_coverage(catalog_entries, policy),
        g.check_masking_completion(
            masking_validation, masking_report.rows_processed, len(masking_report.files_written)
        ),
        g.check_referential_integrity(subset_result.validation, strict=strict_orphans),
        g.check_schema_validation(final_estate, expected_final_counts),
        g.check_data_quality_thresholds(final_counts),
        g.check_row_count_reconciliation(subset_manifest, final_counts),
        g.check_orphan_detection(subset_manifest, max_allowed_orphans=max_allowed_orphans),
        g.check_provenance(final_counts, synthetic_manifest),
        g.check_manifest_generation(
            subset_dir / "subset_manifest.json", masking_summary_path, synthetic_manifest_path
        ),
        g.check_policy_version_recorded(policy),
        g.check_masking_version_recorded(masking_report.masking_engine_version),
        # Phase 18A (P1-9): compare claim.billed_amount's value
        # distribution before (SUBSET output) vs. after (final output)
        # masking/optional synthetic augmentation -- see
        # check_distribution_shape's own docstring for exactly what
        # this does and does not verify.
        g.check_distribution_shape(
            _numeric_column_values(subset_estate, "claim", "billed_amount"),
            _numeric_column_values(final_estate, "claim", "billed_amount"),
            column_label="claim.billed_amount",
        ),
    ]

    # -- 7. CERTIFY ---------------------------------------------------------
    draft = report_mod.build_draft_report(
        dataset_name=dataset_name or f"{scale}-{subset_strategy.value}",
        scale_profile=subset_manifest.scale_profile,
        subset_manifest_id=subset_manifest.manifest_id,
        synthetic_generation_manifest_id=synthetic_manifest.manifest_id if synthetic_manifest else None,
        masking_policy_name=policy.name,
        masking_policy_version=policy.version,
        masking_engine_version=masking_report.masking_engine_version,
    )
    processing = report_mod.start_processing(draft, actor=actor)
    row_count_trail = _build_row_count_trail(
        subset_manifest.source_counts, subset_manifest.selected_counts, final_counts
    )
    certified = report_mod.certify(
        processing,
        gate_results,
        row_count_reconciliation=row_count_trail,
        actor=actor,
        signing_key=signing_key,
    )

    # -- 8. PUBLISH (only if requested AND certified) ------------------
    final_report = certified
    if auto_publish and certified.status.value == "certified":
        final_report = state_machine.publish(certified, actor=actor, signing_key=signing_key)

    report_path = out_dir / "certification_report.json"
    report_path.write_text(final_report.model_dump_json(indent=2), encoding="utf-8")

    return CertificationPipelineResult(
        report=final_report,
        report_path=report_path,
        estate_dir=estate_dir,
        catalog_path=catalog_path,
        subset_dir=subset_dir,
        masked_dir=masked_dir,
        final_dir=final_dir,
    )


def _write_masking_summary(
    path: Path,
    masking_report: MaskingRunReport,
    masking_validation: MaskingValidationReport,
    policy: MaskingPolicy,
) -> None:
    """Write `masking_run_summary.json`, matching
    `data_plane.masking.cli`'s own summary shape (including this ADR-0011
    version metadata) -- `mask_estate` itself does not write this file
    (only the CLI does), and this pipeline needs it on disk for
    `gates.check_manifest_generation` to find, so it writes the same
    artifact the CLI would have."""

    import json

    path.write_text(
        json.dumps(
            {
                "rows_processed": masking_report.rows_processed,
                "columns_masked": masking_report.columns_masked,
                "technique_counts": masking_report.technique_counts,
                "files_written": [str(p) for p in masking_report.files_written],
                "warning_count": len(masking_report.warnings),
                "masking_engine_version": masking_report.masking_engine_version,
                "policy_name": policy.name,
                "policy_version": policy.version,
                "validation_passed": masking_validation.passed,
                "validation_checks": masking_validation.checks_run,
                "validation_failures": masking_validation.failures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


__all__ = ["CertificationPipelineResult", "run_certification_pipeline"]
