"""The eleven required certification gates (`ROADMAP.md` Phase 6).

Every function here is an **independent re-derivation**, not a re-trust,
of an earlier phase's own claims -- `ARCHITECTURE.md` section 2.2 warns
explicitly that a real certifier "must not simply trust [masking
validation's] own report," and `docs/problems/problems_phase_03.md` P3-1 says the same
about needing "a durable certification evidence record ... and a publish
gate" beyond what Phase 3 itself checks. Concretely:

- `check_masking_completion` and `check_referential_integrity` take
  Phase 3's `ValidationReport` and Phase 4's `SubsetValidationReport` as
  *inputs*, but this module makes its own, separately-documented PASS/FAIL
  policy decision on top of them (see each function's docstring) rather
  than just echoing `.passed`.
- `check_schema_validation` and `check_row_count_reconciliation` read the
  dataset back from disk after every pipeline stage has run, rather than
  trusting any prior stage's self-reported counts.
- `check_phi_pii_policy_coverage` re-resolves the masking policy against
  the catalog itself, so a catalog column the masking policy would (for
  any reason) leave unmasked is caught here even if no prior phase's own
  report would ever mention it.

See `docs/CERTIFICATION_VS_MASKING.md` for the full "masking ran" !=
"certified" argument these gates exist to make concrete.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from healthcare_tdm_contracts import (
    CatalogEntry,
    CertificationGateResult,
    CertificationGateType,
    ClassificationTier,
    IntegrityStatus,
    MaskingPolicy,
    MaskingTechnique,
    SubsetManifest,
    SyntheticGenerationManifest,
)

from data_plane.masking.policy import resolve_rule
from data_plane.masking.validation import ValidationReport as MaskingValidationReport
from data_plane.subsetting.estate_io import RawEstate
from data_plane.subsetting.validation import SubsetValidationReport

#: Tiers a masking policy MUST route to a real (non-PASSTHROUGH) technique.
#: `NON_SENSITIVE` is intentionally excluded -- passthrough is correct,
#: documented behavior for that tier (see `masking/policy.py`).
_TIERS_REQUIRING_PROTECTION = frozenset(
    {
        ClassificationTier.DIRECT_IDENTIFIER,
        ClassificationTier.QUASI_IDENTIFIER,
        ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
    }
)


def check_phi_pii_policy_coverage(
    catalog_entries: list[CatalogEntry], policy: MaskingPolicy
) -> CertificationGateResult:
    """GATE 1 -- does the masking policy actually cover every sensitive
    catalog column?

    Independently re-resolves `policy`'s rule for every catalog entry
    whose tier requires protection (everything except `NON_SENSITIVE`)
    and fails if any of them resolves to `MaskingTechnique.PASSTHROUGH`.
    This is the gate that would catch, e.g., a newly-discovered PHI
    column the catalog correctly classified but whose masking policy has
    no real rule for -- see `docs/CERTIFICATION_VS_MASKING.md`'s
    "PHI policy coverage could be incomplete for newly-discovered
    columns" scenario, and
    `tests/certification/test_gates.py::test_phi_pii_policy_coverage_gate_fails_when_a_sensitive_column_resolves_to_passthrough`
    for the adversarial proof.
    """

    gaps: list[str] = []
    checked = 0
    for entry in catalog_entries:
        tier = entry.classification.tier
        if tier not in _TIERS_REQUIRING_PROTECTION:
            continue
        checked += 1
        resolved = resolve_rule(policy, tier=tier, column=entry.column)
        if resolved.technique is MaskingTechnique.PASSTHROUGH:
            gaps.append(f"{entry.source}.{entry.dataset}.{entry.column} (tier={tier.value})")

    passed = not gaps
    detail = (
        f"All {checked} sensitive catalog column(s) resolve to a real masking technique."
        if passed
        else f"{len(gaps)} sensitive column(s) resolve to PASSTHROUGH under policy "
        f"{policy.name!r} v{policy.version}: {', '.join(gaps)}"
    )
    return CertificationGateResult(
        gate=CertificationGateType.PHI_PII_POLICY_COVERAGE,
        passed=passed,
        detail=detail,
        metrics={"sensitive_columns_checked": str(checked), "coverage_gaps": str(len(gaps))},
    )


def check_masking_completion(
    masking_validation: MaskingValidationReport, rows_processed: int, files_written: int
) -> CertificationGateResult:
    """GATE 2 -- did masking actually run, and did Phase 3's own
    validation (referential integrity within the masked run, no raw
    value leakage, no collisions) pass?

    This gate's own policy addition on top of `masking_validation.passed`:
    a masking run that processed zero rows or wrote zero files "passes"
    Phase 3's validation vacuously (there is nothing to fail), which this
    gate refuses to certify as "masking completion" -- masking must have
    actually done something.
    """

    reasons: list[str] = []
    if not masking_validation.passed:
        reasons.append(f"masking validation failed: {'; '.join(masking_validation.failures)}")
    if rows_processed <= 0:
        reasons.append("zero rows were processed by the masking engine")
    if files_written <= 0:
        reasons.append("zero output files were written by the masking engine")

    passed = not reasons
    detail = (
        f"{rows_processed} row(s) masked across {files_written} file(s); "
        f"{len(masking_validation.checks_run)} masking validation check(s) passed."
        if passed
        else "; ".join(reasons)
    )
    return CertificationGateResult(
        gate=CertificationGateType.MASKING_COMPLETION,
        passed=passed,
        detail=detail,
        metrics={
            "rows_processed": str(rows_processed),
            "files_written": str(files_written),
            "masking_checks_run": str(len(masking_validation.checks_run)),
        },
    )


def check_referential_integrity(
    subset_validation: SubsetValidationReport, *, strict: bool = False
) -> CertificationGateResult:
    """GATE 3 -- did the SUBSET stage introduce any real (engine-bug)
    dangling reference?

    Policy decision (see `docs/CERTIFICATION_VS_MASKING.md` for the
    reasoning): `IntegrityStatus.FAILED` (an `engine_bug` finding) always
    fails this gate -- that is a genuine defect and can never be
    certified. `PASSED_WITH_KNOWN_ORPHANS` (a pre-existing source orphan
    or an intentional negative-test injection, per Phase 4's three-way
    classification) is accepted by default, because those orphans are
    documented, expected, and not a defect in this run -- **unless**
    `strict=True`, which a caller can set for target environments that
    require a zero-orphan dataset regardless of provenance.
    """

    if subset_validation.status is IntegrityStatus.FAILED:
        return CertificationGateResult(
            gate=CertificationGateType.REFERENTIAL_INTEGRITY,
            passed=False,
            detail=(
                f"Subsetting engine introduced {sum(subset_validation.engine_bug_counts.values())} "
                f"dangling reference(s) not attributable to a source orphan or negative-test "
                f"injection: {subset_validation.engine_bug_counts}"
            ),
            metrics={"engine_bug_relationships": str(len(subset_validation.engine_bug_counts))},
        )

    known_orphans = sum(subset_validation.known_orphan_counts.values())
    injected = sum(subset_validation.injected_negative_test_orphan_counts.values())
    if strict and (known_orphans or injected):
        return CertificationGateResult(
            gate=CertificationGateType.REFERENTIAL_INTEGRITY,
            passed=False,
            detail=(
                f"strict mode: {known_orphans} known source orphan(s) and {injected} injected "
                "negative-test orphan(s) are present; strict certification requires zero."
            ),
            metrics={"known_orphans": str(known_orphans), "injected_orphans": str(injected)},
        )

    return CertificationGateResult(
        gate=CertificationGateType.REFERENTIAL_INTEGRITY,
        passed=True,
        detail=(
            f"No engine-introduced dangling references. {known_orphans} known source orphan(s) "
            f"and {injected} injected negative-test orphan(s) present and accepted "
            f"(strict={strict})."
        ),
        metrics={"known_orphans": str(known_orphans), "injected_orphans": str(injected)},
    )


def check_orphan_detection(
    subset_manifest: SubsetManifest, *, max_allowed_orphans: int | None = None
) -> CertificationGateResult:
    """GATE -- ORPHAN_DETECTION.

    Reuses `SubsetManifest.known_orphan_counts` /
    `injected_negative_test_orphan_counts` directly (Phase 4's own,
    already-computed data -- not re-derived from scratch, per this
    phase's design note to reuse Phase 4's manifest as a real gate
    input). The new policy decision this gate makes: orphans are
    *reported*, and only *fail* certification if their total count
    exceeds `max_allowed_orphans` (default `None` = no limit, i.e. report
    only) -- distinct from `check_referential_integrity`'s hard
    engine-bug gate, this one is a tunable data-quality-style threshold a
    stricter target environment can set.
    """

    total = sum(subset_manifest.known_orphan_counts.values()) + sum(
        subset_manifest.injected_negative_test_orphan_counts.values()
    )
    passed = max_allowed_orphans is None or total <= max_allowed_orphans
    detail = (
        f"{total} known/injected orphan reference(s) detected across "
        f"{len(subset_manifest.known_orphan_counts) + len(subset_manifest.injected_negative_test_orphan_counts)} "
        f"relationship(s)"
        + (
            f"; within the allowed threshold of {max_allowed_orphans}."
            if passed and max_allowed_orphans is not None
            else "; no threshold configured (report-only)."
            if max_allowed_orphans is None
            else f"; exceeds the allowed threshold of {max_allowed_orphans}."
        )
    )
    return CertificationGateResult(
        gate=CertificationGateType.ORPHAN_DETECTION,
        passed=passed,
        detail=detail,
        metrics={
            "total_orphans": str(total),
            "max_allowed_orphans": "unbounded" if max_allowed_orphans is None else str(max_allowed_orphans),
        },
    )


def check_schema_validation(final_estate: RawEstate, expected_counts: dict[str, int]) -> CertificationGateResult:
    """GATE -- SCHEMA_VALIDATION.

    Reads the actually-written final estate back into memory
    (`final_estate`, produced by `data_plane.subsetting.estate_io.read_estate`
    against the pipeline's final output directory) and checks two things
    no prior phase's own report checks: (1) row counts actually readable
    back from disk match `expected_counts` (the counts the pipeline's own
    upstream stages *claim* to have written), and (2) every *physical*
    on-disk group of rows (a single table, a single Parquet batch, a
    single partner-feed file) has a single consistent key set within
    itself -- heterogeneous keys within one physical file/table broke a
    real writer once before (Phase 5's own `docs/problems/problems_phase_05.md` risk
    log documents exactly this bug for the PBM CSV writer). This is
    deliberately checked **per physical group, not per logical entity**:
    `claim`'s two Parquet batches (`claims-2024Q4` vs `claims-2025Q1`)
    and `lab_result`'s EHR-vs-partner-feed (and partner v1-vs-v2) sources
    have *intentionally* different columns by design (Phase 1's
    documented schema drift), so comparing key sets across those
    boundaries would flag expected, benign heterogeneity as a defect.
    This is "strictly more than any single prior phase's own validation"
    by construction: it is the only check in this pipeline that re-reads
    the final artifact from disk rather than trusting an in-memory
    report object.
    """

    mismatches: list[str] = []
    heterogeneous: list[str] = []

    actual_counts = final_estate.row_counts()
    for entity, expected in expected_counts.items():
        actual = actual_counts.get(entity, 0)
        if actual != expected:
            mismatches.append(f"{entity}: expected {expected}, found {actual} on disk")

    def _check_group(label: str, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        key_sets = {frozenset(row.keys()) for row in rows}
        if len(key_sets) > 1:
            heterogeneous.append(f"{label} ({len(key_sets)} distinct key sets across its rows)")

    for entity in expected_counts:
        if entity == "claim":
            for batch_name, batch_rows in final_estate.claim.batches.items():
                _check_group(f"claim[batch={batch_name}]", batch_rows)
        elif entity == "lab_result":
            _check_group("lab_result[ehr]", final_estate.lab_result_ehr)
            for file_name, (_fieldnames, rows) in final_estate.lab_result_partner.v1_files.items():
                _check_group(
                    f"lab_result[partner_v1={file_name}]",
                    [cast(dict[str, object], dict(r)) for r in rows],
                )
            for file_name, v2_rows in final_estate.lab_result_partner.v2_files.items():
                _check_group(f"lab_result[partner_v2={file_name}]", v2_rows)
        else:
            _check_group(entity, getattr(final_estate, entity, []))

    passed = not mismatches and not heterogeneous
    details = []
    if mismatches:
        details.append("row-count mismatch(es): " + "; ".join(mismatches))
    if heterogeneous:
        details.append("heterogeneous row schema(s): " + "; ".join(heterogeneous))
    detail = "; ".join(details) if details else f"{len(expected_counts)} entities schema-validated cleanly."

    return CertificationGateResult(
        gate=CertificationGateType.SCHEMA_VALIDATION,
        passed=passed,
        detail=detail,
        metrics={"entities_checked": str(len(expected_counts)), "mismatches": str(len(mismatches))},
    )


def check_data_quality_thresholds(
    final_row_counts: dict[str, int], *, min_total_rows: int = 1, anchor_entity: str = "member"
) -> CertificationGateResult:
    """GATE -- DATA_QUALITY_THRESHOLDS.

    A minimal, honest data-quality bar: the final dataset must not be
    degenerate. Fails if the total row count across every entity is
    below `min_total_rows`, or if the anchor entity (`member` by default
    -- every other entity's referential closure is anchored to it, per
    Phase 4) has zero rows. See `docs/problems/problems_phase_03.md` P3-4 and
    `docs/problems/problems_phase_06.md` for why this is deliberately NOT a
    distribution-shape-preservation check (mean/variance/percentile
    comparison against the source estate) -- that is real future work,
    not something this phase's scope claims to solve.
    """

    total = sum(final_row_counts.values())
    anchor_count = final_row_counts.get(anchor_entity, 0)
    reasons: list[str] = []
    if total < min_total_rows:
        reasons.append(f"total row count {total} is below the minimum {min_total_rows}")
    if anchor_count <= 0:
        reasons.append(f"anchor entity {anchor_entity!r} has zero rows")

    passed = not reasons
    detail = (
        f"{total} total row(s) across {len(final_row_counts)} entities; "
        f"{anchor_count} {anchor_entity} row(s)."
        if passed
        else "; ".join(reasons)
    )
    return CertificationGateResult(
        gate=CertificationGateType.DATA_QUALITY_THRESHOLDS,
        passed=passed,
        detail=detail,
        metrics={"total_rows": str(total), f"{anchor_entity}_rows": str(anchor_count)},
    )


def check_row_count_reconciliation(
    subset_manifest: SubsetManifest, final_row_counts: dict[str, int]
) -> CertificationGateResult:
    """GATE -- ROW_COUNT_RECONCILIATION.

    Reuses `SubsetManifest.selected_counts` (Phase 4's own, already-
    computed record of what SUBSET wrote) as the baseline, and compares
    it against `final_row_counts` (independently re-read from the
    actually-published final estate, after MASK and any optional
    synthetic augmentation). The new policy decision: a final count may
    legitimately be *greater than or equal to* the subset's selected
    count (synthetic scenario generation only ever adds rows -- see
    `data_plane.synthetic`), but must never be *less than* it -- any
    entity that shrank between SUBSET and the final published output
    means rows were silently lost somewhere in MASK or the write-back
    path, which is always a defect, never expected behavior.
    """

    losses: dict[str, str] = {}
    trail: dict[str, str] = {}
    for entity, selected in subset_manifest.selected_counts.items():
        final = final_row_counts.get(entity, 0)
        trail[entity] = f"selected={selected} final={final}"
        if final < selected:
            losses[entity] = f"selected {selected} -> final {final} (lost {selected - final})"

    passed = not losses
    detail = (
        f"{len(subset_manifest.selected_counts)} entities reconciled; no row loss detected."
        if passed
        else "Row count loss detected: " + "; ".join(f"{k}: {v}" for k, v in losses.items())
    )
    return CertificationGateResult(
        gate=CertificationGateType.ROW_COUNT_RECONCILIATION,
        passed=passed,
        detail=detail,
        metrics=trail,
    )


def check_provenance(
    final_row_counts: dict[str, int],
    synthetic_manifest: SyntheticGenerationManifest | None,
) -> CertificationGateResult:
    """GATE -- PROVENANCE.

    If the optional GENERATE SYNTHETIC DATA stage ran, verifies its own
    `provenance_row_counts` rollup accounts for every row in the final
    output (i.e. no row was written without a `data_provenance` tag --
    Phase 5's own core safety requirement, re-checked independently here
    rather than trusted). If that stage did not run, this gate passes
    trivially and says so explicitly -- the whole dataset is uniformly
    `masked_production_like` by construction with no synthetic step
    involved, so there is nothing to reconcile.
    """

    if synthetic_manifest is None:
        return CertificationGateResult(
            gate=CertificationGateType.PROVENANCE,
            passed=True,
            detail="No synthetic scenario stage ran; provenance is uniformly masked-production-like "
            "by construction.",
            metrics={"synthetic_stage_ran": "false"},
        )

    total_final = sum(final_row_counts.values())
    total_provenance = sum(synthetic_manifest.provenance_row_counts.values())
    passed = total_provenance == total_final
    detail = (
        f"Provenance rollup accounts for all {total_final} row(s)."
        if passed
        else f"Provenance rollup covers {total_provenance} row(s) but the final estate has "
        f"{total_final} row(s) -- {abs(total_final - total_provenance)} row(s) are untagged."
    )
    return CertificationGateResult(
        gate=CertificationGateType.PROVENANCE,
        passed=passed,
        detail=detail,
        metrics={"total_final_rows": str(total_final), "total_tagged_rows": str(total_provenance)},
    )


def check_distribution_shape(
    source_values: list[float],
    masked_values: list[float],
    *,
    column_label: str,
    max_mean_ratio: float = 10.0,
    min_sample_size: int = 5,
) -> CertificationGateResult:
    """GATE -- DISTRIBUTION_SHAPE (Phase 18A, resolves
    `docs/problems/problems_final_review.md` P1-9: "no statistical distribution-shape
    verification anywhere in the pipeline").

    **What this checks**: whether `masked_values` (a numeric column
    AFTER masking/subsetting) is grossly distorted relative to
    `source_values` (the SAME column BEFORE masking, i.e. straight out
    of SUBSET) -- specifically:

    1. **Degenerate collapse**: `source_values` has real variation (at
       least one non-zero value) but every `masked_values` entry is
       zero -- masking collapsed all variation in this column, which is
       never correct behavior for a column meant to preserve
       plausibility (as opposed to a column deliberately redacted to a
       constant, which is a different, explicit policy choice this gate
       does not evaluate).
    2. **Order-of-magnitude mean shift**: the ratio between
       `masked_values`' mean and `source_values`' mean (larger over
       smaller) exceeds `max_mean_ratio` -- e.g. a source column
       averaging hundreds of dollars whose masked counterpart averages
       tens of thousands, or vice versa.

    **What this deliberately does NOT check** (see
    `docs/CERTIFICATION_VS_MASKING.md` and `docs/problems/problems_phase_03.md` P3-4 /
    `docs/problems/problems_phase_06.md` P6-3, both of which this gate finally closes
    as an *automated, enforced* check rather than only a documented,
    honest gap): this is NOT a rigorous statistical test. It does not
    compare variance, percentiles, or the shape of the distribution
    beyond its mean, and it does not use a real statistical test (e.g.
    Kolmogorov-Smirnov). It is a real, lightweight, gross-distortion
    sanity check -- proportionate to this repository's stated scope, not
    a claim that masked numeric data faithfully preserves the source's
    full statistical distribution (`data_plane.masking.synthesizers`'
    numeric replacement only ever claimed same-order-of-magnitude
    plausibility, never distributional fidelity; this gate now actually
    verifies that claim rather than leaving it unchecked).

    Passes trivially (with `metrics` explaining why) if either side has
    fewer than `min_sample_size` values -- too few values to compare
    meaningfully without risking a false positive on a tiny/edge-case
    population.
    """

    if len(source_values) < min_sample_size or len(masked_values) < min_sample_size:
        return CertificationGateResult(
            gate=CertificationGateType.DISTRIBUTION_SHAPE,
            passed=True,
            detail=(
                f"{column_label}: too few values to compare meaningfully "
                f"(source={len(source_values)}, masked={len(masked_values)}, "
                f"minimum={min_sample_size}) -- passing trivially."
            ),
            metrics={
                "column": column_label,
                "source_count": str(len(source_values)),
                "masked_count": str(len(masked_values)),
            },
        )

    source_mean = sum(source_values) / len(source_values)
    masked_mean = sum(masked_values) / len(masked_values)

    reasons: list[str] = []
    if source_mean != 0 and all(v == 0 for v in masked_values):
        reasons.append(
            f"source has real variation (mean={source_mean:.2f}) but every masked value is zero "
            "-- masking collapsed all variation in this column"
        )
    elif source_mean != 0 and masked_mean != 0:
        ratio = max(source_mean, masked_mean) / min(source_mean, masked_mean)
        if ratio > max_mean_ratio:
            reasons.append(
                f"source mean {source_mean:.2f} vs. masked mean {masked_mean:.2f} "
                f"(ratio {ratio:.1f}x) exceeds the allowed {max_mean_ratio}x order-of-magnitude "
                "threshold"
            )

    passed = not reasons
    detail = (
        f"{column_label}: masked mean {masked_mean:.2f} within {max_mean_ratio}x of source mean "
        f"{source_mean:.2f} ({len(source_values)} source / {len(masked_values)} masked values compared)."
        if passed
        else f"{column_label}: " + "; ".join(reasons)
    )
    return CertificationGateResult(
        gate=CertificationGateType.DISTRIBUTION_SHAPE,
        passed=passed,
        detail=detail,
        metrics={
            "column": column_label,
            "source_mean": f"{source_mean:.4f}",
            "masked_mean": f"{masked_mean:.4f}",
            "source_count": str(len(source_values)),
            "masked_count": str(len(masked_values)),
        },
    )


def check_manifest_generation(
    subset_manifest_path: Path,
    masking_summary_path: Path,
    synthetic_manifest_path: Path | None,
) -> CertificationGateResult:
    """GATE -- MANIFEST_GENERATION.

    Every prior stage claims to write a durable manifest artifact next to
    its output (`subset_manifest.json`, `masking_run_summary.json`,
    optionally `synthetic_generation_manifest.json`) -- this gate is the
    literal check that those files actually exist on disk, not merely
    that an in-memory object was returned.
    """

    missing = [
        str(p)
        for p in (subset_manifest_path, masking_summary_path, synthetic_manifest_path)
        if p is not None and not p.exists()
    ]
    passed = not missing
    expected = 2 + (1 if synthetic_manifest_path is not None else 0)
    detail = (
        f"All {expected} expected manifest artifact(s) present on disk."
        if passed
        else f"Missing manifest artifact(s): {', '.join(missing)}"
    )
    return CertificationGateResult(
        gate=CertificationGateType.MANIFEST_GENERATION,
        passed=passed,
        detail=detail,
        metrics={"expected_manifests": str(expected), "missing": str(len(missing))},
    )


def check_policy_version_recorded(policy: MaskingPolicy) -> CertificationGateResult:
    """GATE -- POLICY_VERSION_RECORDED. See docs/adr/0011 for why this is
    tracked as its own identifier."""

    passed = bool(policy.name) and policy.version >= 1
    detail = (
        f"Masking policy {policy.name!r} version {policy.version} recorded."
        if passed
        else f"Masking policy version is not properly recorded (name={policy.name!r}, "
        f"version={policy.version})."
    )
    return CertificationGateResult(
        gate=CertificationGateType.POLICY_VERSION_RECORDED,
        passed=passed,
        detail=detail,
        metrics={"policy_name": policy.name, "policy_version": str(policy.version)},
    )


def check_masking_version_recorded(masking_engine_version: str) -> CertificationGateResult:
    """GATE -- MASKING_VERSION_RECORDED. See docs/adr/0011 for why this is
    tracked separately from the policy version."""

    passed = bool(masking_engine_version.strip())
    detail = (
        f"Masking engine version {masking_engine_version!r} recorded."
        if passed
        else "Masking engine version is missing/blank."
    )
    return CertificationGateResult(
        gate=CertificationGateType.MASKING_VERSION_RECORDED,
        passed=passed,
        detail=detail,
        metrics={"masking_engine_version": masking_engine_version},
    )


__all__ = [
    "check_data_quality_thresholds",
    "check_distribution_shape",
    "check_manifest_generation",
    "check_masking_completion",
    "check_masking_version_recorded",
    "check_orphan_detection",
    "check_phi_pii_policy_coverage",
    "check_policy_version_recorded",
    "check_provenance",
    "check_referential_integrity",
    "check_row_count_reconciliation",
    "check_schema_validation",
]
