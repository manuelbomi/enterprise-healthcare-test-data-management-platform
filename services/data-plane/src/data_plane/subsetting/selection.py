"""The six anchor-selection strategies (`SubsettingStrategy`).

Every function in this module answers exactly one question: *which Member
IDs are selected?* None of them touch any other entity's relationships --
that is `closure.build_closure`'s job, called identically regardless of
which strategy produced the anchor set. This split is what lets six very
different real-world sizing rules ("2% of patients", "exactly 10,000
patients", "50 patients per rare condition", "patients active in Q1 2025",
"patients with an active plan and at least one paid claim", "patients that
exercise a known edge case") all guarantee a referentially closed subset
without six separate referential-integrity implementations.

Every strategy is deterministic given the same `RawEstate` and the same
`seed` parameter (default `20240101`, matching
`reference_data.generator.EstateGenerator`'s own default) -- reproducible
subsets are as important for test/debugging purposes as reproducible
estates are (see `reference_data/generator.py`'s docstring).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from healthcare_tdm_contracts import SubsettingStrategy

from data_plane.subsetting.estate_io import RawEstate

#: Values the Phase 1 estate's generator writes into a malformed field to
#: simulate bad data (see `reference_data/generator.py`). Reused here by
#: `select_risk_edge_case` to find members that exercise that exact edge
#: case, rather than re-deriving the list independently.
_MALFORMED_DISCHARGE_DATES = {"TBD", "UNKNOWN", ""}
_MALFORMED_LAB_VALUES = {"PENDING", ">999", "see note"}
_MALFORMED_ZIP_CODES = {"ABCDE", "1234", "00000-XXXX"}
_ORPHAN_PROVIDER_ID_CLAIM = "SYN-PRV-99999"
_ORPHAN_PROVIDER_ID_ENCOUNTER = "SYN-PRV-99998"
_ORPHAN_DIAGNOSIS_CODE = "SYN-Z99.9-UNMAPPED"

DEFAULT_SEED = 20240101


@dataclass
class SelectionResult:
    """The anchor Member ID set a strategy selected, plus bookkeeping a
    caller turns into `SubsetSelectionCriteria`/`SubsetManifest` fields.
    """

    member_ids: set[str]
    resolved_parameters: dict[str, str] = field(default_factory=dict)
    description: str = ""


def _all_member_ids(estate: RawEstate) -> list[str]:
    return [str(m["member_id"]) for m in estate.member if m.get("member_id") is not None]


def select_percentage(estate: RawEstate, *, percentage: float, seed: int = DEFAULT_SEED) -> SelectionResult:
    """Select a random `percentage` (0-100) of the source Member population.

    This is the shape of the phase's own headline example scaled down:
    "select 10,000 members" out of a much larger population is exactly
    "select N% of members" for whatever N that count represents; this
    function is what runs underneath both phrasings.
    """

    if not 0 < percentage <= 100:
        raise ValueError(f"percentage must be in (0, 100], got {percentage}")
    all_ids = _all_member_ids(estate)
    target = max(1, round(len(all_ids) * (percentage / 100.0))) if all_ids else 0
    rng = random.Random(seed)
    selected = set(rng.sample(all_ids, min(target, len(all_ids))))
    return SelectionResult(
        member_ids=selected,
        resolved_parameters={"percentage": str(percentage), "seed": str(seed)},
        description=f"{percentage}% random sample of {len(all_ids)} members -> {len(selected)} selected",
    )


def select_fixed_population(estate: RawEstate, *, count: int, seed: int = DEFAULT_SEED) -> SelectionResult:
    """Select an exact target Member count, capped at the available
    population (never an error -- a `tiny`-scale estate legitimately has
    fewer than 10,000 members; see this phase's operational notes on
    scaling the same code path to a real 10,000-member subset).
    """

    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    all_ids = _all_member_ids(estate)
    rng = random.Random(seed)
    target = min(count, len(all_ids))
    selected = set(rng.sample(all_ids, target))
    capped = target < count
    return SelectionResult(
        member_ids=selected,
        resolved_parameters={"requested_count": str(count), "seed": str(seed), "capped_at_available": str(capped)},
        description=(
            f"Fixed population of {count} requested; {len(all_ids)} available; {len(selected)} selected"
            + (" (capped at available population)" if capped else "")
        ),
    )


def select_stratified(
    estate: RawEstate,
    *,
    strata_field: str = "gender",
    per_stratum: int,
    seed: int = DEFAULT_SEED,
) -> SelectionResult:
    """Select up to `per_stratum` members from each distinct value of
    `strata_field`, so every stratum (e.g. every gender, every preferred
    language) is represented in the subset rather than the largest
    stratum crowding out smaller ones the way a plain random sample would.

    `strata_field` is looked up on `Member` first (e.g. `gender`) and
    falls back to `MemberDemographics` (e.g. `race`, `ethnicity`,
    `preferred_language`, `marital_status`) for members that have a
    demographics row.
    """

    if per_stratum < 1:
        raise ValueError(f"per_stratum must be >= 1, got {per_stratum}")

    demographics_by_member = {
        str(d["member_id"]): d for d in estate.member_demographics if d.get("member_id") is not None
    }
    strata: dict[str, list[str]] = {}
    for m in estate.member:
        member_id = m.get("member_id")
        if member_id is None:
            continue
        member_id = str(member_id)
        value = m.get(strata_field)
        if value is None:
            demo = demographics_by_member.get(member_id)
            value = demo.get(strata_field) if demo else None
        strata.setdefault(str(value), []).append(member_id)

    rng = random.Random(seed)
    selected: set[str] = set()
    per_stratum_selected: dict[str, int] = {}
    for value, ids in sorted(strata.items()):
        take = min(per_stratum, len(ids))
        chosen = rng.sample(ids, take)
        selected.update(chosen)
        per_stratum_selected[value] = take

    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(per_stratum_selected.items()))
    return SelectionResult(
        member_ids=selected,
        resolved_parameters={
            "strata_field": strata_field,
            "per_stratum": str(per_stratum),
            "seed": str(seed),
            "strata_found": str(len(strata)),
        },
        description=(
            f"Stratified sample by '{strata_field}': up to {per_stratum} per stratum across "
            f"{len(strata)} strata -> {len(selected)} selected ({breakdown})"
        ),
    )


def select_date_window(
    estate: RawEstate, *, start_date: str, end_date: str
) -> SelectionResult:
    """Select every member with at least one claim whose `service_date`
    falls within `[start_date, end_date]` (inclusive, ISO-8601 strings) --
    e.g. "give me everyone who had activity in Q1 2025". Malformed/
    unparsable dates are skipped rather than raising, consistent with how
    the rest of this platform treats the estate's injected malformed
    values as expected, not exceptional (see `masking/engine.py`'s
    `_date_shift`).
    """

    if start_date > end_date:
        raise ValueError(f"start_date {start_date!r} must be <= end_date {end_date!r}")

    selected: set[str] = set()
    considered = 0
    for claim in estate.claim.all_rows():
        service_date = claim.get("service_date")
        member_id = claim.get("member_id")
        if not isinstance(service_date, str) or member_id is None:
            continue
        considered += 1
        if start_date <= service_date[:10] <= end_date:
            selected.add(str(member_id))

    return SelectionResult(
        member_ids=selected,
        resolved_parameters={"start_date": start_date, "end_date": end_date},
        description=(
            f"Members with >=1 claim service_date in [{start_date}, {end_date}] "
            f"(considered {considered} claims) -> {len(selected)} selected"
        ),
    )


def select_business_rule(
    estate: RawEstate,
    *,
    coverage_status: str = "active",
    claim_status: str = "paid",
    min_matching_claims: int = 1,
) -> SelectionResult:
    """Select members matching a business predicate: has a coverage row in
    `coverage_status` AND at least `min_matching_claims` claims in
    `claim_status`. A stand-in for the kind of rule a real TDM consumer
    actually asks for ("give me active members with real claims history
    to test the claims-adjudication UI against"), as opposed to a pure
    statistical sample.
    """

    if min_matching_claims < 1:
        raise ValueError(f"min_matching_claims must be >= 1, got {min_matching_claims}")

    active_member_ids = {
        str(c["member_id"])
        for c in estate.coverage
        if c.get("coverage_status") == coverage_status and c.get("member_id") is not None
    }

    matching_claim_counts: dict[str, int] = {}
    for claim in estate.claim.all_rows():
        if claim.get("status") != claim_status:
            continue
        member_id = claim.get("member_id")
        if member_id is None:
            continue
        matching_claim_counts[str(member_id)] = matching_claim_counts.get(str(member_id), 0) + 1

    selected = {
        member_id
        for member_id in active_member_ids
        if matching_claim_counts.get(member_id, 0) >= min_matching_claims
    }

    return SelectionResult(
        member_ids=selected,
        resolved_parameters={
            "coverage_status": coverage_status,
            "claim_status": claim_status,
            "min_matching_claims": str(min_matching_claims),
        },
        description=(
            f"Members with coverage_status='{coverage_status}' AND >= {min_matching_claims} "
            f"claim(s) with status='{claim_status}': {len(active_member_ids)} active, "
            f"-> {len(selected)} selected"
        ),
    )


def select_risk_edge_case(
    estate: RawEstate, *, max_members: int | None = None, seed: int = DEFAULT_SEED
) -> SelectionResult:
    """Select members that touch one or more of the Phase 1 estate's known
    injected edge cases -- exactly the population an edge-case/negative
    QA test suite wants over-represented, rather than hoping a plain
    random sample happens to include enough rare cases.

    Detected signals (see `reference_data/generator.py`/`edge_cases.py`
    for where each one is injected): a claim referencing a nonexistent
    provider, an encounter referencing a nonexistent provider, a claim
    line referencing an unmapped diagnosis code, a claim with a negative
    (malformed) paid amount, a prescription with a negative (malformed)
    fill quantity, an encounter with a malformed discharge date, a member
    with zero coverage rows, and an address with a malformed ZIP code.
    """

    signal_hits: dict[str, set[str]] = {}

    claim_id_to_member_id: dict[str, str] = {}
    orphan_provider_claims: set[str] = set()
    malformed_paid_claims: set[str] = set()
    for claim in estate.claim.all_rows():
        member_id = claim.get("member_id")
        claim_id = claim.get("claim_id")
        if member_id is None or claim_id is None:
            continue
        claim_id_to_member_id[str(claim_id)] = str(member_id)
        if claim.get("provider_id") == _ORPHAN_PROVIDER_ID_CLAIM:
            orphan_provider_claims.add(str(member_id))
        paid = claim.get("paid_amount")
        if isinstance(paid, (int, float)) and paid < 0:
            malformed_paid_claims.add(str(member_id))
    signal_hits["claim.provider_id_orphan"] = orphan_provider_claims
    signal_hits["claim.malformed_negative_paid_amount"] = malformed_paid_claims

    unmapped_diagnosis: set[str] = set()
    for line in estate.claim_line:
        if line.get("diagnosis_code") == _ORPHAN_DIAGNOSIS_CODE:
            member_id = claim_id_to_member_id.get(str(line.get("claim_id")))
            if member_id:
                unmapped_diagnosis.add(member_id)
    signal_hits["claim_line.diagnosis_code_orphan"] = unmapped_diagnosis

    orphan_provider_encounters: set[str] = set()
    malformed_discharge: set[str] = set()
    for enc in estate.encounter:
        member_id = enc.get("member_id")
        if member_id is None:
            continue
        if enc.get("provider_id") == _ORPHAN_PROVIDER_ID_ENCOUNTER:
            orphan_provider_encounters.add(str(member_id))
        if enc.get("discharge_date") in _MALFORMED_DISCHARGE_DATES:
            malformed_discharge.add(str(member_id))
    signal_hits["encounter.provider_id_orphan"] = orphan_provider_encounters
    signal_hits["encounter.malformed_discharge_date"] = malformed_discharge

    malformed_rx: set[str] = set()
    for rx in estate.prescription:
        member_id = rx.get("member_id")
        if member_id is None:
            continue
        quantity = rx.get("quantity")
        if isinstance(quantity, (int, float)) and quantity < 0:
            malformed_rx.add(str(member_id))
    signal_hits["prescription.malformed_negative_quantity"] = malformed_rx

    no_coverage_members = {str(m["member_id"]) for m in estate.member if m.get("member_id") is not None} - {
        str(c["member_id"]) for c in estate.coverage if c.get("member_id") is not None
    }
    signal_hits["member.no_coverage"] = no_coverage_members

    malformed_zip_members: set[str] = set()
    all_member_ids_set = {str(m["member_id"]) for m in estate.member if m.get("member_id") is not None}
    for addr in estate.address:
        if addr.get("zip_code") in _MALFORMED_ZIP_CODES and addr.get("member_id") in all_member_ids_set:
            malformed_zip_members.add(str(addr["member_id"]))
    signal_hits["address.malformed_zip_code"] = malformed_zip_members

    risk_pool: set[str] = set()
    for ids in signal_hits.values():
        risk_pool.update(ids)

    selected = risk_pool
    if max_members is not None and len(risk_pool) > max_members:
        rng = random.Random(seed)
        selected = set(rng.sample(sorted(risk_pool), max_members))

    resolved_parameters = {name: str(len(ids)) for name, ids in signal_hits.items()}
    resolved_parameters["max_members"] = str(max_members) if max_members is not None else "unbounded"
    resolved_parameters["seed"] = str(seed)

    breakdown = ", ".join(f"{name}={len(ids)}" for name, ids in signal_hits.items())
    return SelectionResult(
        member_ids=selected,
        resolved_parameters=resolved_parameters,
        description=(
            f"Risk/edge-case pool of {len(risk_pool)} members touching >=1 known edge case "
            f"({breakdown}) -> {len(selected)} selected"
        ),
    )


def select_population(
    estate: RawEstate, strategy: SubsettingStrategy, parameters: dict[str, str]
) -> SelectionResult:
    """Dispatch to the strategy function named by `strategy`, parsing
    string-valued `parameters` (the shape `SubsetSelectionCriteria`
    carries) into each function's typed keyword arguments. Used by
    `data_plane.subsetting.engine.run_subsetting` and the CLI so callers
    never need to know each strategy's own function name.
    """

    seed = int(parameters["seed"]) if "seed" in parameters else DEFAULT_SEED

    if strategy is SubsettingStrategy.PERCENTAGE:
        return select_percentage(estate, percentage=float(parameters["percentage"]), seed=seed)
    if strategy is SubsettingStrategy.FIXED_POPULATION:
        return select_fixed_population(estate, count=int(parameters["count"]), seed=seed)
    if strategy is SubsettingStrategy.STRATIFIED:
        return select_stratified(
            estate,
            strata_field=parameters.get("strata_field", "gender"),
            per_stratum=int(parameters["per_stratum"]),
            seed=seed,
        )
    if strategy is SubsettingStrategy.DATE_WINDOW:
        return select_date_window(
            estate, start_date=parameters["start_date"], end_date=parameters["end_date"]
        )
    if strategy is SubsettingStrategy.BUSINESS_RULE:
        return select_business_rule(
            estate,
            coverage_status=parameters.get("coverage_status", "active"),
            claim_status=parameters.get("claim_status", "paid"),
            min_matching_claims=int(parameters.get("min_matching_claims", "1")),
        )
    if strategy is SubsettingStrategy.RISK_EDGE_CASE:
        max_members = int(parameters["max_members"]) if "max_members" in parameters else None
        return select_risk_edge_case(estate, max_members=max_members, seed=seed)

    raise ValueError(f"Unsupported subsetting strategy: {strategy}")  # pragma: no cover


__all__ = [
    "DEFAULT_SEED",
    "SelectionResult",
    "select_business_rule",
    "select_date_window",
    "select_fixed_population",
    "select_percentage",
    "select_population",
    "select_risk_edge_case",
    "select_stratified",
]
