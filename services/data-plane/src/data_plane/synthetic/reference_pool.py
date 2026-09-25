"""The pool of reference/code-table IDs (Plan, Provider, Pharmacy,
Diagnosis, Procedure) scenario generators link new records against, so
"configurable relationships" (the phase's own requirement: "synthetic
generation must preserve schema and configurable relationships") means
something concrete: a generated Claim references a *real* (or, in
standalone mode, a plausibly-synthesized) Provider, the same way Phase 1's
generator threads consistent identifiers across the whole estate.

Two sources for the pool:

- **Augment mode** (`ReferencePool.from_estate`): drawn from the base
  estate this run is augmenting (already-subsetted, already-masked or
  synthetic) -- new scenario claims link to the *same* providers/plans
  that estate already has, so the scenario rows compose naturally with
  the rest of the dataset.
- **Standalone mode** (`build_minimal_reference_pool`): no base estate
  exists, so a small, self-contained set of reference rows is generated
  first (tagged `DataProvenance.SYNTHETIC`, no `scenario_type` -- they
  aren't one of the eleven named scenarios themselves, just the
  prerequisite fixtures scenario rows link against), and the pool is
  built from those.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from healthcare_tdm_contracts import DataProvenance

from data_plane.reference_data.domain import Diagnosis, Pharmacy, Plan, Procedure, Provider
from data_plane.subsetting.estate_io import RawEstate
from data_plane.synthetic.ids import ScenarioIdAllocator
from data_plane.synthetic.provenance import tag_rows

_PLAN_TYPES = ["HMO", "PPO", "EPO", "POS", "HDHP"]
_SPECIALTIES = ["Internal Medicine", "Cardiology", "Orthopedics", "Behavioral Health", "Pediatrics"]


@dataclass
class ReferencePool:
    """Read-only view of the IDs a scenario generator may link against."""

    plan_ids: list[str] = field(default_factory=list)
    provider_ids: list[str] = field(default_factory=list)
    pharmacy_ids: list[str] = field(default_factory=list)
    diagnosis_codes: list[str] = field(default_factory=list)
    procedure_codes: list[str] = field(default_factory=list)

    def is_complete(self) -> bool:
        return bool(
            self.plan_ids and self.provider_ids and self.pharmacy_ids
            and self.diagnosis_codes and self.procedure_codes
        )

    @classmethod
    def from_estate(cls, estate: RawEstate) -> "ReferencePool":
        return cls(
            plan_ids=[r["plan_id"] for r in estate.plan if r.get("plan_id")],
            provider_ids=[r["provider_id"] for r in estate.provider if r.get("provider_id")],
            pharmacy_ids=[r["pharmacy_id"] for r in estate.pharmacy if r.get("pharmacy_id")],
            diagnosis_codes=[r["diagnosis_code"] for r in estate.diagnosis if r.get("diagnosis_code")],
            procedure_codes=[r["procedure_code"] for r in estate.procedure if r.get("procedure_code")],
        )


#: Every reference-table entity `build_minimal_reference_pool` can generate.
ALL_REFERENCE_ENTITIES = frozenset({"plan", "provider", "pharmacy", "diagnosis", "procedure"})


def build_minimal_reference_pool(
    estate: RawEstate,
    id_alloc: ScenarioIdAllocator,
    batch_id: str,
    rng_seed: int = 0,
    only: frozenset[str] | None = None,
) -> ReferencePool:
    """Generate a small, self-contained reference-table fixture set,
    append it to `estate`, and return the resulting pool.

    Also used by "augment" mode as a *fallback* when the base estate's
    own reference pool is missing an entity entirely (e.g. a subset
    aggressive enough to have trimmed every Provider) -- every scenario
    generator needs somewhere real to link a Claim/Prescription/Encounter,
    and this guarantees one exists.

    `only` restricts which entities are actually generated and appended
    to `estate` (default: all five, `ALL_REFERENCE_ENTITIES` -- the
    standalone-mode case, where nothing exists yet). The "augment mode,
    top up only what's missing" fallback passes `only={"provider"}` (for
    example) so a base estate that already has real Plans/Pharmacies/
    Diagnoses/Procedures isn't polluted with redundant fabricated ones
    for entities it didn't actually need topped up -- see `engine.py`.
    An entity not in `only` returns an empty list in the result
    `ReferencePool` for that field.
    """

    entities = only if only is not None else ALL_REFERENCE_ENTITIES

    plans = [
        tag_rows(
            [
                Plan(
                    plan_id=id_alloc.next_id("PLN", width=4),
                    plan_name=f"SYN Scenario {t} Plan",
                    plan_type=t,
                    metal_tier="Silver",
                    market_segment="Commercial",
                ).model_dump()
            ],
            provenance=DataProvenance.SYNTHETIC,
            batch_id=batch_id,
        )[0]
        for t in _PLAN_TYPES[:2]
    ] if "plan" in entities else []

    providers = [
        tag_rows(
            [
                Provider(
                    provider_id=id_alloc.next_id("PRV", width=5),
                    npi="9" + str(100000000 + i),
                    provider_name=f"SYN Scenario Provider {i}",
                    provider_type="Individual",
                    specialty=specialty,
                    city="Springfield",
                    state="IL",
                ).model_dump()
            ],
            provenance=DataProvenance.SYNTHETIC,
            batch_id=batch_id,
        )[0]
        for i, specialty in enumerate(_SPECIALTIES, start=1)
    ] if "provider" in entities else []

    pharmacies = [
        tag_rows(
            [
                Pharmacy(
                    pharmacy_id=id_alloc.next_id("PHM", width=5),
                    pharmacy_name="SYN Scenario Pharmacy",
                    chain_name="SynRx",
                    city="Springfield",
                    state="IL",
                    zip_code="62704",
                    npi="8" + str(200000001),
                ).model_dump()
            ],
            provenance=DataProvenance.SYNTHETIC,
            batch_id=batch_id,
        )[0]
    ] if "pharmacy" in entities else []

    diagnoses = [
        tag_rows(
            [
                Diagnosis(
                    diagnosis_code=f"SYN-SCEN-DX{i:02d}",
                    description=f"Scenario-fixture diagnosis {i}",
                ).model_dump()
            ],
            provenance=DataProvenance.SYNTHETIC,
            batch_id=batch_id,
        )[0]
        for i in range(1, 6)
    ] if "diagnosis" in entities else []

    procedures = [
        tag_rows(
            [
                Procedure(
                    procedure_code=f"SYN-SCEN-PX{i:02d}",
                    description=f"Scenario-fixture procedure {i}",
                ).model_dump()
            ],
            provenance=DataProvenance.SYNTHETIC,
            batch_id=batch_id,
        )[0]
        for i in range(1, 6)
    ] if "procedure" in entities else []

    estate.plan.extend(plans)
    estate.provider.extend(providers)
    estate.pharmacy.extend(pharmacies)
    estate.diagnosis.extend(diagnoses)
    estate.procedure.extend(procedures)

    return ReferencePool(
        plan_ids=[p["plan_id"] for p in plans],
        provider_ids=[p["provider_id"] for p in providers],
        pharmacy_ids=[p["pharmacy_id"] for p in pharmacies],
        diagnosis_codes=[d["diagnosis_code"] for d in diagnoses],
        procedure_codes=[p["procedure_code"] for p in procedures],
    )


__all__ = ["ALL_REFERENCE_ENTITIES", "ReferencePool", "build_minimal_reference_pool"]
