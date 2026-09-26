"""Post-selection integrity validation for a subsetting run.

Turns the `DanglingReference` findings `closure.build_closure` (and,
optionally, `negative_testing.inject_negative_test_orphan`) already
computed into the three-way verdict `docs/problems/problems_phase_04.md`'s operational
notes require: a subsetting engine must never *introduce* a dangling
relationship itself, but a subset legitimately *carrying forward* a
pre-existing Phase 1 source orphan -- or *intentionally containing* one
injected for negative testing -- is not a defect and must be reported,
not silently dropped or treated as a bug.

This module does not re-walk the estate; it only classifies findings
`closure.py` already produced. See `docs/tutorial/04-subsetting-and-
referential-closure.md`, "What integrity validation actually checks", for
a worked example of all three outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from healthcare_tdm_contracts import IntegrityStatus

from data_plane.subsetting.closure import ClosureResult, DanglingReference

#: Every relationship `closure.build_closure` checks, in the order it
#: checks them -- used only to print a "0 dangling references" line for
#: relationships with nothing to report, so a validation report is a
#: complete checklist, not just a list of problems.
CHECKED_RELATIONSHIPS = (
    "coverage.plan_id",
    "claim_line.diagnosis_code",
    "claim_line.procedure_code",
    "prescription.pharmacy_id",
    "lab_result.encounter_id",
    "claim.provider_id",
    "encounter.provider_id",
    "prescription.prescriber_provider_id",
)


@dataclass
class SubsetValidationReport:
    """The result of validating one subsetting run's referential integrity."""

    status: IntegrityStatus
    known_orphan_counts: dict[str, int] = field(default_factory=dict)
    injected_negative_test_orphan_counts: dict[str, int] = field(default_factory=dict)
    engine_bug_counts: dict[str, int] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status is not IntegrityStatus.FAILED


def _tally(findings: list[DanglingReference], category: str) -> dict[str, int]:
    tally: dict[str, int] = {}
    for finding in findings:
        if finding.category != category:
            continue
        tally[finding.relationship] = tally.get(finding.relationship, 0) + 1
    return tally


def validate_subset(
    closure: ClosureResult,
    negative_test_dangling: list[DanglingReference] | None = None,
) -> SubsetValidationReport:
    """Classify every dangling reference `closure.build_closure` (and,
    optionally, a negative-test injection step) found and produce a
    `SubsetValidationReport`.

    Verdict rule: any `"engine_bug"` finding fails the whole run
    (`IntegrityStatus.FAILED`) -- that is a real defect and must never be
    silently accepted. Otherwise, any `"source_orphan"` or
    `"negative_test_injection"` finding downgrades the run to
    `PASSED_WITH_KNOWN_ORPHANS` (still a valid, publishable subset -- the
    orphan is reported, not hidden). With no findings at all, the run is
    a clean `PASSED`.
    """

    all_findings = list(closure.dangling) + list(negative_test_dangling or [])

    engine_bug_counts = _tally(all_findings, "engine_bug")
    known_orphan_counts = _tally(all_findings, "source_orphan")
    injected_counts = _tally(all_findings, "negative_test_injection")

    if engine_bug_counts:
        status = IntegrityStatus.FAILED
    elif known_orphan_counts or injected_counts:
        status = IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS
    else:
        status = IntegrityStatus.PASSED

    findings: list[str] = []
    for relationship in CHECKED_RELATIONSHIPS:
        bug = engine_bug_counts.get(relationship, 0)
        orphan = known_orphan_counts.get(relationship, 0)
        injected = injected_counts.get(relationship, 0)
        if bug:
            findings.append(
                f"FAIL {relationship}: {bug} dangling reference(s) that exist in the source estate "
                "but were not carried into the subset (engine bug)"
            )
        if orphan:
            findings.append(
                f"OK   {relationship}: {orphan} pre-existing source orphan(s) legitimately present "
                "in this subset (Phase 1 edge case, not a defect)"
            )
        if injected:
            findings.append(
                f"OK   {relationship}: {injected} dangling reference(s) intentionally injected for "
                "negative testing"
            )
        if not (bug or orphan or injected):
            findings.append(f"OK   {relationship}: 0 dangling references (fully closed)")

    return SubsetValidationReport(
        status=status,
        known_orphan_counts=known_orphan_counts,
        injected_negative_test_orphan_counts=injected_counts,
        engine_bug_counts=engine_bug_counts,
        findings=findings,
    )


__all__ = ["CHECKED_RELATIONSHIPS", "SubsetValidationReport", "validate_subset"]
