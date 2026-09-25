# healthcare-tdm-contracts

Shared, typed contracts used *between* planes of the
enterprise-healthcare-test-data-management-platform. See
[ADR-0002](../../docs/adr/0002-python-project-layout.md) and
[ADR-0003](../../docs/adr/0003-plane-separation.md) for why this exists as
its own package.

## Rules for this package

- **No business logic.** This package defines *shapes* (Pydantic models,
  enums, protocol/interface definitions) — never algorithms, never I/O.
  If you find yourself writing a function that *does* something (masks a
  value, queries a database, calls storage), it belongs in a service
  package, not here.
- **No dependency on any service package.** `libs/contracts` must be
  installable and importable with nothing but its own declared
  dependencies (currently just `pydantic`). This is what lets every
  service depend on it without pulling in unrelated dependency weight.
- **Every model documents its own contract.** Docstrings on these models
  are the interface documentation between planes — a data-plane engineer
  and a control-plane engineer should each be able to read a model here
  and know exactly what the other side expects, without reading the other
  side's code.

## Contents (Phase 0 scaffold)

- `jobs` — the `JobRequest`/`JobResult` contract the control plane uses to
  submit work to the data plane, and job status/type enums.
- `classification` — the PHI/PII classification tiers/categories and the
  `ColumnClassification` shape used between discovery, policy, and
  governance. Implemented in Phase 2 — see
  `services/data-plane/src/data_plane/discovery/`.
- `catalog` — the `CatalogEntry` data-catalog row shape (classification +
  masking requirement + owner + retention classification), produced by
  discovery and served by the control plane's catalog API. Implemented in
  Phase 2 — see ADR-0009 for why it moves between planes as a JSON
  artifact today.
- `masking` — the `MaskingPolicy` shape and related enums.
- `audit` — the `AuditEvent` shape emitted by every plane to the
  security/governance plane.
- `storage` — the storage adapter `Protocol` interface (see
  [ADR-0005](../../docs/adr/0005-object-storage-abstraction.md)) that every
  concrete backend (MinIO/S3/Azure) will implement in a later phase.
- `snapshots` — the `SnapshotRecord` shape used by the metadata plane's
  snapshot registry.
- `subsetting` — the `SubsettingStrategy`/`SubsetManifest` shapes.
  Implemented in Phase 4 — see
  `services/data-plane/src/data_plane/subsetting/`.
- `synthetic` — the `DataProvenance`/`ScenarioType`/
  `SyntheticGenerationManifest` shapes. Implemented in Phase 5 — see
  `services/data-plane/src/data_plane/synthetic/`.
- `certification` — the `CertificationStatus`/`CertificationGateResult`/
  `CertificationReport` shapes for the certified test dataset pipeline.
  Implemented in Phase 6 — see
  `services/data-plane/src/data_plane/certification/` and
  `docs/CERTIFICATION_VS_MASKING.md`.

None of these are wired to a real database, API, or storage backend yet —
that begins in Phase 1 onward. This package currently defines the
*vocabulary* the rest of the system will speak.
