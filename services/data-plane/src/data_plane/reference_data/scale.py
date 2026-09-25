"""Configurable scale profiles for the synthetic healthcare estate.

Four named profiles, per the Phase 1 promptbook: ``tiny`` (fast, for
unit tests and CI), ``developer`` (a full local-dev-sized estate),
``qa`` (large enough to exercise realistic subsetting/masking behavior),
and ``performance`` (load-test scale). Row counts are deliberately kept
well below what a real performance environment would hold — this is a
*teaching* platform meant to run on a laptop, not a load-testing rig; see
``ARCHITECTURE.md`` and the "Non-goals" note in ``ROADMAP.md`` Phase 0.

Counts are derived from ``member_count`` via small fan-out ratios, so the
whole estate scales together and stays internally proportionate at every
profile.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleProfile:
    """Row-count parameters for one named scale profile.

    All fan-out fields are *maximums*; the generator picks a random count
    between 0 (or 1, where a minimum makes sense) and the maximum for each
    member, so the estate has realistic variance rather than every member
    looking identical.
    """

    name: str
    member_count: int
    plan_count: int
    provider_count: int
    pharmacy_count: int
    diagnosis_code_count: int
    procedure_code_count: int
    max_addresses_per_member: int
    max_coverages_per_member: int
    max_claims_per_member: int
    max_claim_lines_per_claim: int
    max_encounters_per_member: int
    max_lab_results_per_encounter: int
    max_prescriptions_per_member: int

    def approx_total_rows(self) -> int:
        """Rough order-of-magnitude row estimate, used for logging/docs only."""

        def avg(n: int) -> float:
            return max(1, n) / 2

        members = self.member_count
        addresses = members * avg(self.max_addresses_per_member)
        coverages = members * avg(self.max_coverages_per_member)
        claims = members * avg(self.max_claims_per_member)
        claim_lines = claims * avg(self.max_claim_lines_per_claim)
        encounters = members * avg(self.max_encounters_per_member)
        lab_results = encounters * avg(self.max_lab_results_per_encounter)
        prescriptions = members * avg(self.max_prescriptions_per_member)
        return int(
            members
            + addresses
            + coverages
            + claims
            + claim_lines
            + encounters
            + lab_results
            + prescriptions
            + self.plan_count
            + self.provider_count
            + self.pharmacy_count
            + self.diagnosis_code_count
            + self.procedure_code_count
        )


SCALE_PROFILES: dict[str, ScaleProfile] = {
    "tiny": ScaleProfile(
        name="tiny",
        member_count=25,
        plan_count=6,
        provider_count=10,
        pharmacy_count=5,
        diagnosis_code_count=30,
        procedure_code_count=30,
        max_addresses_per_member=2,
        max_coverages_per_member=2,
        max_claims_per_member=4,
        max_claim_lines_per_claim=3,
        max_encounters_per_member=3,
        max_lab_results_per_encounter=3,
        max_prescriptions_per_member=3,
    ),
    "developer": ScaleProfile(
        name="developer",
        member_count=250,
        plan_count=12,
        provider_count=60,
        pharmacy_count=25,
        diagnosis_code_count=80,
        procedure_code_count=80,
        max_addresses_per_member=2,
        max_coverages_per_member=2,
        max_claims_per_member=6,
        max_claim_lines_per_claim=4,
        max_encounters_per_member=4,
        max_lab_results_per_encounter=4,
        max_prescriptions_per_member=4,
    ),
    "qa": ScaleProfile(
        name="qa",
        member_count=2_500,
        plan_count=18,
        provider_count=400,
        pharmacy_count=150,
        diagnosis_code_count=150,
        procedure_code_count=150,
        max_addresses_per_member=2,
        max_coverages_per_member=3,
        max_claims_per_member=8,
        max_claim_lines_per_claim=5,
        max_encounters_per_member=5,
        max_lab_results_per_encounter=4,
        max_prescriptions_per_member=5,
    ),
    "performance": ScaleProfile(
        name="performance",
        member_count=20_000,
        plan_count=25,
        provider_count=1_500,
        pharmacy_count=600,
        diagnosis_code_count=200,
        procedure_code_count=200,
        max_addresses_per_member=2,
        max_coverages_per_member=3,
        max_claims_per_member=10,
        max_claim_lines_per_claim=5,
        max_encounters_per_member=6,
        max_lab_results_per_encounter=4,
        max_prescriptions_per_member=6,
    ),
}


def get_scale_profile(name: str) -> ScaleProfile:
    """Resolve a scale profile by name.

    Raises ``KeyError`` with the list of valid names if ``name`` is not a
    known profile, rather than silently falling back to a default — a
    caller asking for the wrong profile should fail loudly.
    """

    try:
        return SCALE_PROFILES[name]
    except KeyError as exc:
        valid = ", ".join(sorted(SCALE_PROFILES))
        raise KeyError(f"Unknown scale profile {name!r}. Valid profiles: {valid}") from exc


__all__ = ["SCALE_PROFILES", "ScaleProfile", "get_scale_profile"]
