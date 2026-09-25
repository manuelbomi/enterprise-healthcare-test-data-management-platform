"""The referential-closure graph walk: the actual mechanism behind every
one of the six subsetting strategies.

Given a `RawEstate` (see `estate_io.py`) and a selected set of anchor
Member IDs, `build_closure` walks the known relationship graph forward
from `Member` -- Coverage, Claim, ClaimLine, Diagnosis/Procedure,
Prescription, Pharmacy, Encounter, LabResult, and the reference entities
(Plan, Provider) those pull in by reference -- and returns exactly the
rows that belong to the selected population, across all five source
systems.

This module is deliberately the *only* place selection logic touches
relationships. Every strategy in `selection.py` only ever decides *which
Member IDs are selected*; once that set exists, `build_closure` is called
identically regardless of which strategy produced it. That is what
guarantees every strategy produces a referentially closed subset with no
strategy-specific referential-integrity bugs to re-litigate six times.

See `docs/tutorial/04-subsetting-and-referential-closure.md` for a full
walkthrough with real output, and this module's `_check_dangling` for the
mechanism behind distinguishing a pre-existing source orphan (expected,
reported) from a closure bug this engine introduced itself (a real
defect -- never expected to occur, and covered by
`tests/subsetting/test_closure.py::test_closure_never_introduces_a_new_dangling_reference`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from healthcare_tdm_contracts import RelationshipEdge

from data_plane.subsetting.estate_io import PartnerLabFeedData, ParquetDataset, RawEstate

DanglingCategory = Literal["engine_bug", "source_orphan", "negative_test_injection"]


@dataclass(frozen=True)
class DanglingReference:
    """One child row in the subset whose referenced parent id did not make
    it into the subset.

    `category` is the core of this phase's "prevent dangling relationships
    unless intentionally injected" requirement:

    - ``"source_orphan"``: `missing_id` never existed in the *source*
      estate's parent table either -- a pre-existing Phase 1 edge case
      (`reference_data/edge_cases.py`) that happened to be reachable from
      the selected population. Legitimate, expected, reported.
    - ``"engine_bug"``: `missing_id` *does* exist in the source estate's
      parent table, but `build_closure` failed to include it in the
      subset. This should never happen; if it does, it is a real defect
      in this module, not an artifact of the source data.
    - ``"negative_test_injection"``: produced by
      `data_plane.subsetting.negative_testing`, an intentional, opt-in
      dangling reference created for negative testing, never emitted by
      `build_closure` itself.
    """

    relationship: str
    missing_id: str
    category: DanglingCategory


@dataclass
class ClosureResult:
    """Output of one `build_closure` call: the selected rows (same shape
    as `RawEstate`) plus the accounting needed to build a `SubsetManifest`
    (`relationship_edges`) and to validate it (`dangling`)."""

    selected: RawEstate
    edges: list[RelationshipEdge] = field(default_factory=list)
    dangling: list[DanglingReference] = field(default_factory=list)


def _values(rows: list[dict[str, object]], key: str) -> set[str]:
    """Distinct, non-null values of `key` across `rows`, coerced to str.

    Coercion to `str` matters because pandas may read an identifier
    column back as a numeric dtype in edge cases (empty/short files);
    every identifier in this estate is a string by design
    (`reference_data/domain.py`), so comparisons must be string-to-string.
    """

    out: set[str] = set()
    for row in rows:
        value = row.get(key)
        if value is None or (isinstance(value, float) and value != value):  # NaN guard
            continue
        out.add(str(value))
    return out


def _filter(rows: list[dict[str, object]], key: str, allowed: set[str]) -> list[dict[str, object]]:
    return [r for r in rows if r.get(key) is not None and str(r.get(key)) in allowed]


def _edge(parent: str, child: str, count: int) -> RelationshipEdge:
    return RelationshipEdge(parent_entity=parent, child_entity=child, edge_count=count)


def _check_dangling(
    relationship: str,
    referenced_ids: set[str],
    selected_parent_ids: set[str],
    all_source_parent_ids: set[str],
) -> list[DanglingReference]:
    """For every id `referenced_ids` points at that did not make it into
    `selected_parent_ids`, classify it as an engine bug (it existed
    somewhere in the source and should have been pulled in) or a
    pre-existing source orphan (it never existed anywhere)."""

    findings: list[DanglingReference] = []
    for missing_id in sorted(referenced_ids - selected_parent_ids):
        category: DanglingCategory = "engine_bug" if missing_id in all_source_parent_ids else "source_orphan"
        findings.append(DanglingReference(relationship=relationship, missing_id=missing_id, category=category))
    return findings


def build_closure(estate: RawEstate, selected_member_ids: set[str]) -> ClosureResult:
    """Walk the full relationship graph forward from `selected_member_ids`
    and return every row, across all five source systems, that belongs to
    the selected population -- see the module docstring for the graph
    shape.
    """

    selected = RawEstate()
    edges: list[RelationshipEdge] = []
    dangling: list[DanglingReference] = []

    # -- Member (anchor) -----------------------------------------------
    selected.member = _filter(estate.member, "member_id", selected_member_ids)
    edges.append(_edge("(selection)", "Member", len(selected.member)))

    # -- MemberDemographics (1:1 child of Member) -----------------------
    selected.member_demographics = _filter(estate.member_demographics, "member_id", selected_member_ids)
    edges.append(_edge("Member", "MemberDemographics", len(selected.member_demographics)))

    # -- Address (Member's own addresses; see module docstring on why
    #    orphan addresses -- whose member_id never matches a real member
    #    -- can never be pulled in by this filter, by construction) -----
    selected.address = _filter(estate.address, "member_id", selected_member_ids)
    edges.append(_edge("Member", "Address", len(selected.address)))

    # -- Coverage --------------------------------------------------------
    selected.coverage = _filter(estate.coverage, "member_id", selected_member_ids)
    edges.append(_edge("Member", "Coverage", len(selected.coverage)))

    # -- Plan (referenced by Coverage; real enforced FK in the source, see
    #    postgres_models.py, so no orphan is expected here) -------------
    referenced_plan_ids = _values(selected.coverage, "plan_id")
    all_plan_ids = _values(estate.plan, "plan_id")
    selected.plan = _filter(estate.plan, "plan_id", referenced_plan_ids)
    edges.append(_edge("Coverage", "Plan", len(selected.plan)))
    dangling += _check_dangling(
        "coverage.plan_id", referenced_plan_ids, _values(selected.plan, "plan_id"), all_plan_ids
    )

    # -- Claim (both schema-drifted batches) -----------------------------
    selected_claim_batches: dict[str, list[dict[str, object]]] = {}
    for batch, rows in estate.claim.batches.items():
        selected_claim_batches[batch] = _filter(rows, "member_id", selected_member_ids)
    selected.claim = ParquetDataset(batches=selected_claim_batches)
    selected_claims = selected.claim.all_rows()
    edges.append(_edge("Member", "Claim", len(selected_claims)))

    # -- ClaimLine ---------------------------------------------------------
    selected_claim_ids = _values(selected_claims, "claim_id")
    selected.claim_line = _filter(estate.claim_line, "claim_id", selected_claim_ids)
    edges.append(_edge("Claim", "ClaimLine", len(selected.claim_line)))
    # NOTE: the source estate also injects claim_line rows whose claim_id
    # points at a claim header that was never written at all (see
    # reference_data/generator.py, "orphan claim lines"). Those claim_line
    # rows are unreachable from any real, selected Claim (their claim_id
    # never matches a real claim's id, selected or not), so they are never
    # pulled in here -- consistent with how Address/Claim.member_id
    # orphans (whose member_id references a nonexistent Member) are never
    # reachable from a real, selected Member either. See
    # docs/tutorial/04-subsetting-and-referential-closure.md,
    # "Reachable vs. unreachable orphans".

    # -- Diagnosis / Procedure (reference/code tables, trimmed to what the
    #    selected claim lines actually use) -----------------------------
    referenced_diag_codes = _values(selected.claim_line, "diagnosis_code")
    referenced_proc_codes = _values(selected.claim_line, "procedure_code")
    all_diag_codes = _values(estate.diagnosis, "diagnosis_code")
    all_proc_codes = _values(estate.procedure, "procedure_code")
    selected.diagnosis = _filter(estate.diagnosis, "diagnosis_code", referenced_diag_codes)
    selected.procedure = _filter(estate.procedure, "procedure_code", referenced_proc_codes)
    edges.append(_edge("ClaimLine", "Diagnosis", len(selected.diagnosis)))
    edges.append(_edge("ClaimLine", "Procedure", len(selected.procedure)))
    dangling += _check_dangling(
        "claim_line.diagnosis_code", referenced_diag_codes, _values(selected.diagnosis, "diagnosis_code"), all_diag_codes
    )
    dangling += _check_dangling(
        "claim_line.procedure_code", referenced_proc_codes, _values(selected.procedure, "procedure_code"), all_proc_codes
    )

    # -- Prescription ------------------------------------------------------
    selected.prescription = _filter(estate.prescription, "member_id", selected_member_ids)
    edges.append(_edge("Member", "Prescription", len(selected.prescription)))

    # -- Pharmacy (referenced by Prescription) ---------------------------
    referenced_pharmacy_ids = _values(selected.prescription, "pharmacy_id")
    all_pharmacy_ids = _values(estate.pharmacy, "pharmacy_id")
    selected.pharmacy = _filter(estate.pharmacy, "pharmacy_id", referenced_pharmacy_ids)
    edges.append(_edge("Prescription", "Pharmacy", len(selected.pharmacy)))
    dangling += _check_dangling(
        "prescription.pharmacy_id", referenced_pharmacy_ids, _values(selected.pharmacy, "pharmacy_id"), all_pharmacy_ids
    )

    # -- Encounter -----------------------------------------------------
    selected.encounter = _filter(estate.encounter, "member_id", selected_member_ids)
    edges.append(_edge("Member", "Encounter", len(selected.encounter)))

    # -- LabResult (EHR-primary NDJSON feed) ------------------------------
    selected.lab_result_ehr = _filter(estate.lab_result_ehr, "member_id", selected_member_ids)
    edges.append(_edge("Encounter", "LabResult (EHR)", len(selected.lab_result_ehr)))
    referenced_encounter_ids = _values(selected.lab_result_ehr, "encounter_id")
    all_encounter_ids = _values(estate.encounter, "encounter_id")
    dangling += _check_dangling(
        "lab_result.encounter_id",
        referenced_encounter_ids,
        _values(selected.encounter, "encounter_id"),
        all_encounter_ids,
    )

    # -- LabResult (partner reference-lab feed) --------------------------
    v1_out: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for name, (fieldnames, v1_rows) in estate.lab_result_partner.v1_files.items():
        v1_out[name] = (fieldnames, [r for r in v1_rows if r.get("pat_id") in selected_member_ids])
    v2_out: dict[str, list[dict[str, object]]] = {}
    for name, v2_rows in estate.lab_result_partner.v2_files.items():
        v2_out[name] = [r for r in v2_rows if r.get("member_id") in selected_member_ids]
    selected.lab_result_partner = PartnerLabFeedData(v1_files=v1_out, v2_files=v2_out)
    edges.append(_edge("Member", "LabResult (partner feed)", len(selected.lab_result_partner.all_rows())))
    # NOTE: partner-feed lab results whose member_id/pat_id references a
    # Member that has not (yet) been enrolled anywhere -- a deliberate
    # late-arriving-data edge case, see generator.py's
    # `_build_partner_lab_feed` -- are unreachable here for the same
    # reason as orphan Address/Claim.member_id rows above.

    # -- Provider (referenced by Claim, Encounter, and Prescription) -----
    claim_provider_ids = _values(selected_claims, "provider_id")
    encounter_provider_ids = _values(selected.encounter, "provider_id")
    prescriber_provider_ids = _values(selected.prescription, "prescriber_provider_id")
    referenced_provider_ids = claim_provider_ids | encounter_provider_ids | prescriber_provider_ids
    all_provider_ids = _values(estate.provider, "provider_id")
    selected.provider = _filter(estate.provider, "provider_id", referenced_provider_ids)
    selected_provider_ids = _values(selected.provider, "provider_id")
    edges.append(_edge("Claim/Encounter/Prescription", "Provider", len(selected.provider)))
    dangling += _check_dangling("claim.provider_id", claim_provider_ids, selected_provider_ids, all_provider_ids)
    dangling += _check_dangling(
        "encounter.provider_id", encounter_provider_ids, selected_provider_ids, all_provider_ids
    )
    dangling += _check_dangling(
        "prescription.prescriber_provider_id", prescriber_provider_ids, selected_provider_ids, all_provider_ids
    )

    return ClosureResult(selected=selected, edges=edges, dangling=dangling)


__all__ = ["ClosureResult", "DanglingCategory", "DanglingReference", "build_closure"]
