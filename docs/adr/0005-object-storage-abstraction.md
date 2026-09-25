# ADR-0005: A single storage-adapter interface, with MinIO for local dev and S3/Azure adapters for cloud

## Status

Accepted

## Context

Actual test-data artifacts (subsets, masked datasets, synthetic datasets,
snapshots) are large, binary/columnar, and best served by object storage
rather than a relational database. The platform must run:

- Locally, on a laptop, with no cloud account required, for development and
  for anyone following the tutorial
- In real cloud environments, which for a healthcare/life-sciences platform
  realistically means AWS S3 and/or Azure Blob Storage/ADLS, and potentially
  other object stores/open-source healthcare data repositories over time

Writing data-plane job code directly against a specific vendor's SDK would
mean either duplicating every job per cloud, or coupling the entire data
plane to one vendor, both of which contradict the "cloud test data
management" premise of the project — this platform is explicitly supposed
to demonstrate portability across storage backends.

## Decision

Define a single storage-adapter interface in `libs/contracts` (conceptually:
`get_object`, `put_object`, `list_objects`, `delete_object`,
`generate_presigned_url`, each scoped to a bucket/container + key, plus a
factory that resolves the concrete adapter from configuration). Data-plane
and control-plane code is written only against this interface.

Concrete adapters:

- **MinIO** — the default for local development via Docker Compose. MinIO
  is S3-API-compatible, so in practice the MinIO adapter and the AWS S3
  adapter can share almost all of their implementation, differing mainly in
  endpoint/credential configuration. This is deliberate: it means the code
  path exercised locally is extremely close to the code path exercised in
  AWS, minimizing "works locally, breaks in the cloud" surprises.
- **AWS S3** — production cloud adapter for AWS-hosted deployments.
- **Azure Blob / ADLS** — production cloud adapter for Azure-hosted
  deployments, for organizations (common in healthcare) standardized on
  Azure.
- Additional adapters for other open-source healthcare data repositories are
  added behind the same interface as needed, rather than growing
  vendor-specific code paths through the data plane.

Which adapter is active is a configuration/environment concern resolved at
startup (e.g., via an environment variable and the secrets provider for
credentials), never a code branch inside job logic.

## Consequences

- Slightly more upfront abstraction work than calling `boto3` directly.
- Job logic (subsetting, masking, synthetic generation) is portable across
  local dev and any supported cloud without modification — a job tested
  against MinIO locally is, by construction, exercising the same interface
  it will use against S3 or ADLS in production.
- New backends (a different cloud, a different open-source object store) are
  additive — implement the interface, register the adapter — rather than
  requiring changes throughout the data plane.
- The interface itself becomes a contract that needs its own tests (does
  every adapter actually satisfy the same behavioral guarantees?) — this is
  tracked as a data-quality/contract-testing concern for Phase 5.
