# Tradeoffs: the real decisions this repository made, and why

An interviewer probing system design depth usually isn't looking for "the
right answer" — they're looking for whether you can name the alternative you
rejected and the concrete cost you accepted instead. Every tradeoff below is
a decision this repository actually made, recorded in an ADR or a
`problems_phase_NN.md` file *before or as* the decision was made
(`CONTRIBUTING.md`'s process requires writing the problems file before
implementing), not reconstructed after the fact to sound good in an
interview.

## 1. Deterministic pseudonymization vs. true (random) anonymization

**Decision:** [ADR-0006](../adr/0006-deterministic-masking-strategy.md) —
`masked = f(real_value, scope, secret_key)`, a pure, *keyed* function of the
real value, never independent randomness per occurrence.

**The alternative and its cost:** random masking (an independently random
fake value per row) is simpler and gives a stronger per-value privacy
guarantee in isolation, but breaks referential integrity immediately — the
same real patient ID would map to a different random value in every table
it appears in, making every join meaningless for testing. Deterministic
masking's cost is the mirror image: it introduces a real re-identification
risk if implemented naively (an unkeyed hash is reversible by a
dictionary/rainbow-table attack against plausible real values), which is
exactly why the ADR requires it be **keyed** — the secret key is what
prevents that attack, and losing control of the key (per `THREAT_MODEL.md`'s
asset table: "The masking key/salt material... compromise breaks the
non-reversible guarantee of masked data") is the single most consequential
operational failure this design can have. `data_plane.masking.engine.MaskingEngine`
implements the keyed side; `services/data-plane/tests/masking/test_no_secrets_committed.py`
and `scripts/security/detect_secrets.py` (Phase 11) are the concrete
controls against the key itself ending up committed to source.

**Where this repository chose the other side deliberately:** quasi-
identifiers and sensitive clinical attributes may use non-deterministic
generalization or synthetic replacement instead (`DATA_GOVERNANCE.md` B.2)
specifically *because* joinability isn't required for them and the
platform prefers the stronger privacy property when it can afford to.

## 2. SQLite locally, PostgreSQL-portable by construction

**Decision:** [ADR-0004](../adr/0004-postgresql-metadata-store.md) chose
PostgreSQL as the metadata plane's system of record, but Phase 7's actual
schema (`control_plane.db.models`) was written to run against SQLite
locally with zero infrastructure — no `JSONB`, no native `UUID` columns,
deliberately mirroring the same portable-column-type discipline
`data_plane.reference_data.postgres_models` already established for the
synthetic estate's own PostgreSQL-shaped source system.

**The alternative and its cost:** requiring a real PostgreSQL instance for
every phase from Phase 7 onward would have meant every contributor (and
every reviewer of this portfolio) needing Docker Compose running before
they could run a single test. The chosen tradeoff — write portable SQL,
test against SQLite by default, verify against real Postgres separately —
means the *portability itself* has to be verified independently, which is a
real, admitted gap until Phase 12: `problems_phase_07.md` P7-1 tracked
"Real PostgreSQL verification remains deferred" as an open problem the whole
time Phase 7-11 ran only against SQLite. Phase 12 closed it for real, not
just in theory: `infra/docker/docker-compose.yml`'s real `control-plane`
container against a real `postgres` container, with `GET /api/v1/ready`
confirmed reporting the database reachable — see `problems_master.md`'s
resolved-problems section for the exact before/after. The honest lesson: a
portability decision made in an ADR isn't proven until something actually
exercises the other backend — writing portable SQL and *believing* it works
against Postgres are different claims.

## 3. Checksum vs. HMAC vs. asymmetric signature for tamper-evidence

This repository actually built **two different tiers** of tamper-evidence
for two different artifacts, and the difference between them is the whole
answer to this tradeoff:

| Artifact | Mechanism | Guarantee | Real limit |
|---|---|---|---|
| `CertificationReport` (`certification_report.json`) | Keyed HMAC-SHA256 (`data_plane.certification.signing`) | Non-repudiation-*shaped*: forging a valid edit requires the signing key, not just file write access | The key itself has no secrets-provider-backed storage yet (`problems_phase_03.md` P3-2's identical vault gap); anyone with both file access *and* the key can still forge a consistent edit — this is a **detection**, not **prevention**, mechanism (`docs/CERTIFICATION_VS_MASKING.md`) |
| `AuditEvidencePackage.bundle_checksum` (Phase 13) | Plain SHA-256 (`control_plane.domain.evidence.compute_bundle_checksum`) | Accidental-corruption/truncation detection only | Uses **no secret key at all** — anyone with database write access can edit the underlying rows and regenerate a self-consistent checksum for a freshly-regenerated package ([ADR-0016](../adr/0016-audit-evidence-lives-in-control-plane.md)'s Consequences; `problems_phase_13.md` P13-2) |

**Why not the same mechanism for both?** The certification report is a
single, self-contained file that has to prove its own integrity
*independent of the database* (it's the artifact certification's state
machine walks forward on). The evidence package is a live aggregation
*from* the database — a keyed signature over it would only be as
trustworthy as the same database access that could edit the rows feeding
it, so the honest scoping was to call it what it is (corruption detection)
rather than oversell it as non-repudiation. **What this repository never
built, for either artifact:** an asymmetric signature (public/private
keypair), which would let a *third party* (an auditor with only the public
key) verify authenticity without being trusted with anything that could
forge new signatures — a real production deployment wanting external,
independently-verifiable non-repudiation would want this for the evidence
package specifically, backed by a real secrets provider. This repository
does not implement it; naming that gap explicitly is a better interview
answer than implying it's already covered.

## 4. Shared immutable snapshots vs. per-environment copies

**Decision:** Phase 7's `EnvironmentDatasetRequest.current_version_id` is a
foreign key into `DatasetVersion`, never a copy of `storage_uri` — many
environments point at one immutable, versioned artifact
(`ARCHITECTURE.md`'s Phase 7 note: "the concrete mechanism satisfying
`ROADMAP.md` Phase 7's 'avoid unnecessary duplicate physical copies'
requirement").

**The alternative and its cost:** a per-environment physical copy is
simpler to reason about in isolation (each environment "owns" its data, no
shared-state coordination) but costs storage linearly in the number of
consuming environments. Phase 8 *quantified* this tradeoff rather than just
asserting it: a real run of `scripts/demo_phase8_capacity.py` against five
real environments sharing one dataset version measured **1,872,804 bytes
saved out of 2,341,005 bytes naive (80.0% savings)** —
`control_plane.domain.capacity.planner.CapacityPlanner.capacity_plan`
computes both totals from real registered `size_bytes` values
(`docs/CAPACITY_COST_TRADEOFFS.md` section 3). The real cost of sharing:
an environment with a genuinely different subset percentage, masking
policy, or refresh timing *cannot* share a snapshot — Phase 7's own
"visibility over automation" decision (revocation never silently migrates
an environment already on a revoked version) is the other side of this
same tradeoff: sharing buys storage efficiency at the cost of coordinated
change being explicit rather than automatic. See `docs/interview/scaling.md`
for the full "how do you prevent 50 teams from each making a 20 TB copy"
answer built on this mechanism.

## 5. Local-mode Spark vs. a real cluster

**Decision:** [ADR-0017](../adr/0017-pyspark-benchmark-tooling-in-data-plane.md) —
every `SparkSession` this repository builds
(`data_plane.spark.session.get_local_spark_session`) uses `master("local[*]")`.
There is no `spark-worker`/`spark-master` service anywhere in `infra/`.

**The alternative and its cost:** standing up a real Kubernetes-native or
standalone Spark cluster is a substantial infrastructure undertaking Phase
14 deliberately scoped out (consistent with Phase 12's decision not to
containerize `services/data-plane` at all — `problems_phase_12.md`). The
cost of *not* doing this is real and stated plainly in every number Phase
14 produced: `docs/SCALE_AND_PERFORMANCE.md` reports real Catalyst query
plans, real Arrow-vectorized `pandas_udf` execution, real broadcast joins,
and real wall-clock throughput (1,707 records/sec at `qa` scale rising to
12,714 records/sec at `performance` scale for `spark_masking[claim]`) — but
every one of those numbers is "one JVM process on one machine," never
extrapolated to cluster-scale. The document is explicit that this is a
deliberate stopping point, not an oversight: fabricating a "what this would
do on a 20-node cluster" number would violate the same honesty convention
`docs/CAPACITY_COST_TRADEOFFS.md` and `docs/COMPLIANCE_EVIDENCE.md` already
established for this repository. See `docs/interview/scaling.md` for how
this local-mode evidence is used honestly to reason about (not measure)
cluster behavior.

## 6. Synthetic vs. masked-production-like data

**When should you use synthetic data rather than masked data?** This
repository's answer is concrete, not philosophical: they solve different
problems, and Phase 5 (`data_plane.synthetic`) exists specifically because
Phase 3/4 (masking + subsetting) alone leave a gap neither one can close.

- **Masked-production-like data** (Phase 3 + Phase 4) preserves the
  *actual, observed* shape of production — real distributions, real
  co-occurrence patterns, real relative volumes — because it starts from a
  real (subsetted) population and transforms values in place. Its weakness,
  documented honestly in `docs/CAPACITY_COST_TRADEOFFS.md` section 5: **rare
  edge cases become rarer** in direct proportion to subset size. A 2%
  subset contains roughly 2% of however many instances of a rare
  claim pattern exist in production — which might be zero.
- **Synthetic data** (Phase 5's eleven scenario generators,
  `data_plane.synthetic.scenarios`) is deliberately constructed, not
  observed — a high-cost claim, an unusual prescription combination, a
  claim referencing a member that doesn't exist. Its storage/generation
  cost is *fixed and small* regardless of the base subset's size
  (`docs/CAPACITY_COST_TRADEOFFS.md` section 6: "guaranteeing a rare
  scenario's presence costs a constant, small amount of storage/compute,
  not a proportional share of production's"). This is precisely why
  certification runs synthetic generation *after* subsetting/masking
  (`INGEST -> ... -> MASK -> GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE`)
  rather than trying to solve rare-case coverage by making the subset
  itself bigger.

**The rule this repository enforces so the two are never confused:** every
row carries an explicit `healthcare_tdm_contracts.DataProvenance` tag
(`masked_production_like` / `synthetic` / `negative_test`), both per-row
(`data_provenance` column, added across all five on-disk formats,
retroactively applied to every pre-existing base row when augmenting) and
per-manifest (`SyntheticGenerationManifest.provenance_row_counts`) — see
`data_plane.synthetic.provenance`'s module docstring for why neither alone
is sufficient (a manifest-only rollup can't tell you which *specific* row
is synthetic; a per-row tag alone can't give you a fast aggregate count).
**Use masked data when the test needs realistic, observed-shape volume and
distribution. Use synthetic data when the test needs a specific, guaranteed
scenario that may not occur naturally (or often enough) in any subset size
you can afford to store** — and never let one be mistaken for the other,
which is exactly the failure mode `DataProvenance` exists to make
impossible.

## 7. How do you version masking policies?

Two genuinely distinct identifiers, tracked separately, per
[ADR-0011](../adr/0011-masking-and-policy-versioning-for-certification.md) —
because "the rules didn't change" and "the code that executes the rules
didn't change" are different claims that can independently be false:

1. **Policy version** — `MaskingPolicy.name` + `MaskingPolicy.version`
   (`healthcare_tdm_contracts`, e.g. `DEFAULT_POLICY`'s
   `POLICY_NAME = "phase3-default"`, `POLICY_VERSION = 1`). Answers "which
   *rules* were configured?"
2. **Masking engine version** — `data_plane.masking.engine.MASKING_ENGINE_VERSION`,
   a semver constant bumped whenever a change to `engine.py` could alter
   masked output for the same policy/key/input (e.g. a bug fix to
   `_date_shift`'s offset calculation). Answers "which *implementation*
   ran those rules?"

Both are recorded on every `CertificationReport`, and two certification
gates (`check_policy_version_recorded`, `check_masking_version_recorded`)
fail a run outright if either is missing — making "this dataset's masking
provenance is fully identified" an enforced precondition, not a
best-effort label.

**The honest limit, stated in the ADR itself:** neither identifier is a
database-backed, control-plane-*approved* version registry by itself — they
are plain code constants, trustworthy for reproducing *this repository's*
masking runs but not yet independently auditable outside the source tree
(`problems_phase_03.md` P3-3, still open as of this ADR). That governance
layer is what Phase 10 actually built on top: `control_plane.domain.governance`'s
`MaskingPolicyVersion`/`PolicyApproval` wraps a real `MaskingPolicy` in a
governed, immutable, database-backed snapshot with an enforced five-state
approval workflow (`draft` -> `pending_approval` -> `approved`/`rejected` ->
`superseded`, `control_plane.domain.governance.state_machine`) — a
`ConsumerDatasetRequest` can only ever reference an **approved**
`policy_version_id` by foreign key, never its own masking rules
(`test_consumer_cannot_attach_custom_masking_rules`). So the full answer has
two layers: the *engine* versions itself lightly (ADR-0011's constants,
still code-only), while the *policy* versions itself heavily (Phase 10's
governed, approved, database-enforced workflow) — because a policy change
is a business/compliance decision that needs an approval trail, while an
engine version bump is a code-review-time developer discipline, not
something every masking run needs a human to approve.
