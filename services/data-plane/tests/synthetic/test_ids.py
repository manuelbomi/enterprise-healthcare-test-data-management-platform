"""`ScenarioIdAllocator`: scenario-sub-range IDs never collide with Phase 1
estate-native IDs (by construction) and never collide with each other."""

from __future__ import annotations

import re

from data_plane.synthetic.ids import ScenarioIdAllocator

_PHASE1_ID_RE = re.compile(r"^SYN-[A-Z]+-\d+$")
_SCENARIO_ID_RE = re.compile(r"^SYN-[A-Z]+-SCEN-\d+$")
_DANGLING_ID_RE = re.compile(r"^SYN-[A-Z]+-SCEN-NX-[A-Z]+-\d+$")


def test_next_id_matches_scenario_sub_range_shape() -> None:
    alloc = ScenarioIdAllocator()
    member_id = alloc.next_id("MBR")
    assert _SCENARIO_ID_RE.match(member_id)
    assert not _PHASE1_ID_RE.match(member_id)  # never mistaken for a Phase 1 estate-native ID


def test_next_id_increments_independently_per_entity_prefix() -> None:
    alloc = ScenarioIdAllocator()
    assert alloc.next_id("MBR") == "SYN-MBR-SCEN-000001"
    assert alloc.next_id("MBR") == "SYN-MBR-SCEN-000002"
    assert alloc.next_id("CLM", width=7) == "SYN-CLM-SCEN-0000001"


def test_dangling_id_is_self_describing_and_distinct_from_next_id() -> None:
    alloc = ScenarioIdAllocator()
    real_id = alloc.next_id("MBR")
    dangling_id = alloc.dangling_id("MBR", "MEMBER")
    assert _DANGLING_ID_RE.match(dangling_id)
    assert dangling_id != real_id
    assert "NX" in dangling_id and "MEMBER" in dangling_id


def test_dangling_id_counter_is_independent_of_next_id_counter() -> None:
    alloc = ScenarioIdAllocator()
    alloc.next_id("PRV")
    alloc.next_id("PRV")
    first_dangling = alloc.dangling_id("PRV", "PROVIDER")
    assert first_dangling == "SYN-PRV-SCEN-NX-PROVIDER-000001"


def test_no_id_collision_across_many_allocations() -> None:
    alloc = ScenarioIdAllocator()
    ids = {alloc.next_id("MBR") for _ in range(500)}
    assert len(ids) == 500
    dangling = {alloc.dangling_id("MBR", "MEMBER") for _ in range(500)}
    assert len(dangling) == 500
    assert ids.isdisjoint(dangling)
