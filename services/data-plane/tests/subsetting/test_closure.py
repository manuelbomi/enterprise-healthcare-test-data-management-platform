"""Tests for `data_plane.subsetting.closure` -- the referential-closure
graph walk -- against the real generated Phase 1 estate.

The central property under test: `build_closure` must never itself
introduce a dangling reference (`DanglingReference.category ==
"engine_bug"`). Every dangling reference it finds must trace back to a
pre-existing Phase 1 source orphan (`"source_orphan"`) -- see
`reference_data/edge_cases.py` for where those are injected and
`docs/tutorial/04-subsetting-and-referential-closure.md`, "Reachable vs.
unreachable orphans", for why only some of the estate's orphan categories
are even reachable from a Member-anchored selection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.subsetting.closure import build_closure
from data_plane.subsetting.estate_io import read_estate


@pytest.fixture(scope="module")
def estate(real_estate: Path):
    return read_estate(real_estate)


def test_closure_never_introduces_a_new_dangling_reference(estate) -> None:
    """Select every member the estate has (the largest possible closure,
    and therefore the case most likely to expose a bug) and assert every
    dangling reference found is a pre-existing source orphan, never an
    engine bug."""

    all_member_ids = {str(m["member_id"]) for m in estate.member}
    result = build_closure(estate, all_member_ids)

    engine_bugs = [d for d in result.dangling if d.category == "engine_bug"]
    assert engine_bugs == [], f"closure introduced dangling references it should not have: {engine_bugs}"


def test_closure_of_empty_selection_is_empty(estate) -> None:
    result = build_closure(estate, set())
    assert result.selected.row_counts() == {
        "member": 0,
        "member_demographics": 0,
        "address": 0,
        "plan": 0,
        "coverage": 0,
        "provider": 0,
        "diagnosis": 0,
        "procedure": 0,
        "claim": 0,
        "claim_line": 0,
        "pharmacy": 0,
        "prescription": 0,
        "encounter": 0,
        "lab_result": 0,
    }
    assert result.dangling == []


def test_closure_of_a_single_member_only_includes_that_members_rows(estate) -> None:
    member_id = str(estate.member[0]["member_id"])
    result = build_closure(estate, {member_id})

    assert {str(m["member_id"]) for m in result.selected.member} == {member_id}
    assert all(str(c["member_id"]) == member_id for c in result.selected.coverage)
    assert all(str(c["member_id"]) == member_id for c in result.selected.claim.all_rows())
    assert all(str(e["member_id"]) == member_id for e in result.selected.encounter)


def test_closure_claim_lines_only_reference_selected_claims(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    result = build_closure(estate, all_member_ids)
    selected_claim_ids = {str(c["claim_id"]) for c in result.selected.claim.all_rows()}
    for line in result.selected.claim_line:
        assert str(line["claim_id"]) in selected_claim_ids


def test_closure_diagnosis_and_procedure_tables_are_trimmed_to_referenced_codes(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    result = build_closure(estate, all_member_ids)

    referenced_diag = {
        str(line["diagnosis_code"]) for line in result.selected.claim_line if line.get("diagnosis_code")
    }
    selected_diag = {str(d["diagnosis_code"]) for d in result.selected.diagnosis}
    # Every selected diagnosis code is actually referenced (no unused rows
    # carried along), and every *resolvable* referenced code is present
    # (the unmapped orphan code is expected to be absent -- see
    # test_closure_never_introduces_a_new_dangling_reference).
    assert selected_diag <= referenced_diag
    all_source_diag_codes = {str(d["diagnosis_code"]) for d in estate.diagnosis}
    assert (referenced_diag & all_source_diag_codes) <= selected_diag


def test_closure_provider_table_is_trimmed_to_referenced_providers(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    result = build_closure(estate, all_member_ids)

    referenced_providers = {
        str(c["provider_id"]) for c in result.selected.claim.all_rows() if c.get("provider_id")
    }
    referenced_providers |= {
        str(e["provider_id"]) for e in result.selected.encounter if e.get("provider_id")
    }
    selected_providers = {str(p["provider_id"]) for p in result.selected.provider}
    assert selected_providers <= referenced_providers


def test_closure_relationship_edges_have_nonnegative_counts(estate) -> None:
    all_member_ids = {str(m["member_id"]) for m in estate.member}
    result = build_closure(estate, all_member_ids)
    assert result.edges
    for edge in result.edges:
        assert edge.edge_count >= 0
