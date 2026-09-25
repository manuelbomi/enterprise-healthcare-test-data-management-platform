"""Tests for EstateGenerator: row counts, determinism, and cross-system
referential integrity (the "soft" contract described in README.md).
"""

from __future__ import annotations

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES


def _generate_tiny(seed: int = 20240101):
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=seed)
    return generator.generate()


def test_generate_tiny_produces_every_entity() -> None:
    estate = _generate_tiny()

    assert len(estate.members) >= SCALE_PROFILES["tiny"].member_count
    assert estate.demographics
    assert estate.addresses
    assert estate.plans
    assert estate.coverages
    assert estate.providers
    assert estate.diagnoses
    assert estate.procedures
    assert estate.claims
    assert estate.claim_lines
    assert estate.pharmacies
    assert estate.prescriptions
    assert estate.encounters
    assert estate.lab_results


def test_generation_is_deterministic_for_a_fixed_seed() -> None:
    estate_a = _generate_tiny(seed=999)
    estate_b = _generate_tiny(seed=999)

    assert [m.member_id for m in estate_a.members] == [m.member_id for m in estate_b.members]
    assert [c.claim_id for c in estate_a.claims] == [c.claim_id for c in estate_b.claims]
    assert estate_a.manifest() == estate_b.manifest()


def test_different_seeds_produce_different_content() -> None:
    estate_a = _generate_tiny(seed=1)
    estate_b = _generate_tiny(seed=2)

    assert [m.first_name for m in estate_a.members] != [m.first_name for m in estate_b.members]


def test_all_identifiers_use_the_documented_synthetic_prefix() -> None:
    estate = _generate_tiny()
    assert all(m.member_id.startswith("SYN-MBR-") for m in estate.members)
    assert all(c.claim_id.startswith("SYN-CLM-") for c in estate.claims)
    assert all(p.provider_id.startswith("SYN-PRV-") for p in estate.providers)
    assert all(rx.prescription_id.startswith("SYN-RX-") for rx in estate.prescriptions)
    assert all(lr.lab_result_id.startswith("SYN-LAB-") for lr in estate.lab_results)


def test_cross_system_referential_integrity_holds_for_most_but_not_all_claims() -> None:
    """Most Claim.member_id values resolve to a real Member (the "soft" FK
    contract across systems, upheld by construction) -- but not all,
    because orphan records are an intentional edge case. See README.md,
    "How referential integrity works"."""

    estate = _generate_tiny()
    member_ids = {m.member_id for m in estate.members}
    resolvable = sum(1 for c in estate.claims if c.member_id in member_ids)

    assert resolvable / len(estate.claims) > 0.80
    assert resolvable < len(estate.claims)  # at least one orphan exists


def test_coverage_foreign_keys_always_resolve_within_postgres_system() -> None:
    """Unlike cross-system references, Coverage->Member and Coverage->Plan
    are real, enforced foreign keys within the same simulated Postgres
    system (see postgres_models.py) -- so every Coverage row must resolve,
    with no exceptions."""

    estate = _generate_tiny()
    member_ids = {m.member_id for m in estate.members}
    plan_ids = {p.plan_id for p in estate.plans}

    assert all(c.member_id in member_ids for c in estate.coverages)
    assert all(c.plan_id in plan_ids for c in estate.coverages)


def test_claim_lines_reference_claims_mostly_but_not_always() -> None:
    estate = _generate_tiny()
    claim_ids = {c.claim_id for c in estate.claims}
    resolvable = sum(1 for cl in estate.claim_lines if cl.claim_id in claim_ids)

    assert resolvable > 0
    assert resolvable < len(estate.claim_lines)
