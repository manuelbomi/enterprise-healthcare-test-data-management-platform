"""`generate_synthetic_scenarios`, the end-to-end orchestrator.

Two modes, both producing the same on-disk, five-source-system estate
shape (`data_plane.subsetting.writer.write_subset_estate`) plus a
`synthetic_generation_manifest.json`:

- **augment** (`base_estate_dir` given): read an existing estate --
  typically a Phase 4 subsetted-and-masked output, but anything sharing
  the same on-disk layout works (the raw Phase 1 estate, a masked-only
  estate, a previous synthetic-generation run's own output) --, tag
  every row already present as `MASKED_PRODUCTION_LIKE` (see
  `provenance.tag_base_estate_as_masked_production_like` for why that
  tagging happens even though this phase didn't produce those rows), add
  the requested scenarios on top, and write the combined estate back out.
- **standalone** (`base_estate_dir=None`): no real input at all -- a
  minimal reference-table fixture set is generated first
  (`reference_pool.build_minimal_reference_pool`), then the requested
  scenarios are generated against it. The output contains zero
  `MASKED_PRODUCTION_LIKE` rows by construction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from faker import Faker
from healthcare_tdm_contracts import ScenarioType, SyntheticGenerationManifest

from data_plane.subsetting.estate_io import RawEstate, read_estate
from data_plane.subsetting.writer import write_subset_estate
from data_plane.synthetic.manifest import build_manifest
from data_plane.synthetic.merge import merge_scenario_batch
from data_plane.synthetic.normalize import normalize_estate_rows
from data_plane.synthetic.provenance import tag_base_estate_as_masked_production_like
from data_plane.synthetic.reference_pool import ReferencePool, build_minimal_reference_pool
from data_plane.synthetic.scenarios import (
    DEFAULT_SCENARIO_COUNTS,
    SCENARIO_GENERATORS,
    ScenarioBatch,
    ScenarioContext,
)
from data_plane.synthetic.ids import ScenarioIdAllocator


@dataclass
class GenerationResult:
    manifest: SyntheticGenerationManifest
    out_root: Path
    files_written: list[Path]
    batches: list[ScenarioBatch]


def generate_synthetic_scenarios(
    out_dir: Path,
    scenarios: list[ScenarioType],
    *,
    base_estate_dir: Path | None = None,
    counts: dict[ScenarioType, int] | None = None,
    seed: int = 90000,
) -> GenerationResult:
    """Generate `scenarios` (each with `counts.get(scenario)` instances,
    falling back to `DEFAULT_SCENARIO_COUNTS`) and write the result to
    `out_dir`.

    Raises `ValueError` for an empty `scenarios` list (nothing to do --
    almost certainly a caller mistake, not a legitimate "generate
    nothing" request).
    """

    if not scenarios:
        raise ValueError("At least one scenario must be requested.")

    batch_id = str(uuid4())
    rng = random.Random(seed)
    faker = Faker("en_US")
    Faker.seed(seed)
    id_alloc = ScenarioIdAllocator()

    if base_estate_dir is not None:
        estate = read_estate(base_estate_dir)
        tag_base_estate_as_masked_production_like(estate, batch_id=batch_id)
        pool = ReferencePool.from_estate(estate)
        if not pool.is_complete():
            # The base estate is missing at least one reference-table
            # entity entirely (e.g. an aggressively small subset with no
            # Provider rows at all) -- every scenario needs somewhere
            # real to link a Claim/Prescription/Encounter, so top up only
            # the missing entities with a minimal synthetic reference set
            # rather than fail the whole run, and rather than discard (or
            # pollute with redundant fabricated rows) the base estate's
            # own perfectly good ids for entities that *weren't* missing.
            missing = frozenset(
                entity
                for entity, ids in (
                    ("plan", pool.plan_ids),
                    ("provider", pool.provider_ids),
                    ("pharmacy", pool.pharmacy_ids),
                    ("diagnosis", pool.diagnosis_codes),
                    ("procedure", pool.procedure_codes),
                )
                if not ids
            )
            fallback = build_minimal_reference_pool(estate, id_alloc, batch_id, rng_seed=seed, only=missing)
            pool = ReferencePool(
                plan_ids=pool.plan_ids or fallback.plan_ids,
                provider_ids=pool.provider_ids or fallback.provider_ids,
                pharmacy_ids=pool.pharmacy_ids or fallback.pharmacy_ids,
                diagnosis_codes=pool.diagnosis_codes or fallback.diagnosis_codes,
                procedure_codes=pool.procedure_codes or fallback.procedure_codes,
            )
        mode = "augment"
    else:
        estate = RawEstate()
        pool = build_minimal_reference_pool(estate, id_alloc, batch_id, rng_seed=seed)
        mode = "standalone"

    ctx = ScenarioContext(rng=rng, faker=faker, id_alloc=id_alloc, pool=pool, batch_id=batch_id)

    batches: list[ScenarioBatch] = []
    for scenario in scenarios:
        generator = SCENARIO_GENERATORS[scenario]
        count = (counts or {}).get(scenario, DEFAULT_SCENARIO_COUNTS[scenario])
        batch = generator(ctx, count=count)
        batches.append(batch)
        merge_scenario_batch(estate, batch)

    normalize_estate_rows(estate)
    files_written = write_subset_estate(estate, out_dir)

    manifest = build_manifest(
        mode=mode,
        batches=batches,
        estate=estate,
        seed=seed,
        base_estate_dir=base_estate_dir,
        out_root=out_dir,
    )
    manifest_path = out_dir / "synthetic_generation_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    files_written = list(files_written) + [manifest_path]

    return GenerationResult(manifest=manifest, out_root=out_dir, files_written=files_written, batches=batches)


__all__ = ["GenerationResult", "generate_synthetic_scenarios"]
