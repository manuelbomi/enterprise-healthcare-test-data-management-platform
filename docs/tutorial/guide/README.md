# The Complete Tutorial — zero to understanding this repository

This is the Phase 15 tutorial `ROADMAP.md` asks for: a path from **never
having heard of Test Data Management** to **understanding this entire
repository**, in twenty chapters, for a junior data engineer. It assumes
nothing about the reader's prior knowledge and builds up every concept
before showing how this specific codebase implements it.

## How this relates to `docs/tutorial/00-overview.md` and the numbered chapters

`docs/tutorial/` already contains `00-overview.md` and a set of
deep-dive chapters (`01-planes-and-data-flow.md` through
`09-centralized-masking-governance.md`, and
`13-auditability-and-compliance-evidence.md`) — one per phase that
introduced a capability worth a dedicated walkthrough. Those chapters
were each written by the phase that built the thing they describe, and
every one of them **assumes you already know what TDM, PHI, subsetting,
masking, and certification mean** — they dive straight into this
repository's real code, module by module, with real captured output.

This guide is different on purpose, and the two are meant to be read
together, not as competitors:

- **Read this guide first, chapter by chapter, if you are new.** Each
  chapter here teaches its concept from first principles — what it is,
  why it exists, what goes wrong without it — the way a principal
  engineer would explain it to a new hire on day one.
- **Each chapter here ends by linking to the matching `0X`/`13` chapter
  (or ADR/doc) for implementation depth**, instead of re-explaining that
  chapter's own worked examples a second time. If you want to actually
  read the code, run the CLI, and see the full real output for a given
  concept, that existing chapter (or doc) is where the depth lives.
- **Neither set duplicates the other.** This guide teaches concepts;
  the numbered chapters are the implementation reference. If a claim in
  this guide and a numbered chapter ever appear to disagree, the
  numbered chapter (closer to the real code, written by the phase that
  built it) wins — file a problem in `docs/problems/problems_master.md` and fix this
  guide.

## Why the files live in `docs/tutorial/guide/`, not `docs/tutorial/10-...md`

Every existing filename `docs/tutorial/0X-...md`/`13-...md` is linked
from real, already-shipped documentation elsewhere in this repository —
`ARCHITECTURE.md`, `CONTRIBUTING.md`, ADRs, runbooks, `ROADMAP.md`,
service READMEs, and more (checked by grepping the whole repository for
`docs/tutorial/0` and `docs/tutorial/1` before choosing a scheme — see
`docs/problems/problems_phase_15.md`). Reusing or renumbering any of those filenames
for this phase's twenty chapters would silently break every one of
those links. This guide's own twenty chapters therefore live in a new,
non-colliding subdirectory with their own `01`-`20` sequence, matching
the spec's own chapter numbers exactly (Chapter 1 is
`01-what-is-test-data-management.md`, Chapter 20 is
`20-operating-tdm-as-a-product.md`), so there is never any ambiguity
about which chapter number in the spec a given file corresponds
to.

## The twenty chapters

| # | Chapter | Real code it points to | Matching implementation-depth chapter |
|---|---|---|---|
| 1 | [What Test Data Management is](01-what-is-test-data-management.md) | The whole repository | `docs/tutorial/00-overview.md` |
| 2 | [Why regulated enterprises need TDM](02-why-regulated-enterprises-need-tdm.md) | `DATA_GOVERNANCE.md`, `SECURITY.md`, `THREAT_MODEL.md` | — |
| 3 | [PHI vs PII](03-phi-vs-pii.md) | `libs/contracts/.../classification.py`, `data_plane.discovery` | `docs/tutorial/03-phi-pii-classification.md` |
| 4 | [Production vs lower environments](04-production-vs-lower-environments.md) | `healthcare_tdm_contracts.lifecycle.Environment`, `control_plane.domain.lifecycle` | `docs/tutorial/07-dataset-lifecycle-and-refresh.md` |
| 5 | [Data profiling](05-data-profiling.md) | `data_plane.discovery.scanner` | `docs/tutorial/03-phi-pii-classification.md` |
| 6 | [Sensitive-data classification](06-sensitive-data-classification.md) | `data_plane.discovery.engine`/`schema_rules`/`pattern_rules`/`overrides` | `docs/tutorial/03-phi-pii-classification.md` |
| 7 | [Subsetting](07-subsetting.md) | `data_plane.subsetting.selection` | `docs/tutorial/04-subsetting-and-referential-closure.md` |
| 8 | [Referential integrity](08-referential-integrity.md) | `data_plane.subsetting.closure`/`validation` | `docs/tutorial/04-subsetting-and-referential-closure.md` |
| 9 | [Masking](09-masking.md) | `data_plane.masking.engine`/`policy` | `data_plane/masking/README.md`, ADR-0006, ADR-0010 |
| 10 | [Deterministic pseudonymization](10-deterministic-pseudonymization.md) | `data_plane.masking.engine` (`HMAC_PSEUDONYMIZATION`, `TOKENIZATION`), `token_vault.py` | ADR-0006 |
| 11 | [Synthetic data](11-synthetic-data.md) | `data_plane.reference_data`, `data_plane.synthetic` | `docs/tutorial/02-synthetic-data-estate.md`, `docs/tutorial/05-synthetic-scenario-generation.md` |
| 12 | [Dataset certification](12-dataset-certification.md) | `data_plane.certification.gates`/`report`/`state_machine` | `docs/tutorial/06-certification-pipeline.md`, `docs/CERTIFICATION_VS_MASKING.md` |
| 13 | [Snapshots and refresh cadence](13-snapshots-and-refresh-cadence.md) | `control_plane.domain.lifecycle` | `docs/tutorial/07-dataset-lifecycle-and-refresh.md` |
| 14 | [Storage techniques](14-storage-techniques.md) | `data_plane.reference_data.writers`, `data_plane.capacity.footprint` | `docs/tutorial/08-storage-compute-capacity-planning.md`, ADR-0007 |
| 15 | [Capacity planning](15-capacity-planning.md) | `data_plane.capacity`, `control_plane.domain.capacity` | `docs/tutorial/08-storage-compute-capacity-planning.md`, `docs/CAPACITY_COST_TRADEOFFS.md` |
| 16 | [Platform integrity](16-platform-integrity.md) | `control_plane.platform` | `docs/PLATFORM_INTEGRITY.md` |
| 17 | [CI/CD](17-ci-cd.md) | `.github/workflows/`, `services/*/Dockerfile` | `docs/problems/problems_phase_12.md` |
| 18 | [Cloud testing](18-cloud-testing.md) | `infra/k8s/helm/`, `infra/terraform/` | `docs/AZURE_PRODUCTION_DEPLOYMENT.md` |
| 19 | [Audit evidence](19-audit-evidence.md) | `control_plane.platform.audit`, `control_plane.domain.evidence` | `docs/tutorial/13-auditability-and-compliance-evidence.md`, `docs/COMPLIANCE_EVIDENCE.md` |
| 20 | [Operating TDM as a product](20-operating-tdm-as-a-product.md) | Synthesis of Phases 7/8/10/11/13 + `ROADMAP.md`/`CONTRIBUTING.md` | Chapters 13-19 of this guide |

## Ground rules this guide follows (same rules the rest of the repository follows)

- Every code reference points at a file that actually exists in this
  repository, as of Phase 15. Nothing describes unbuilt functionality
  as if it were real.
- Every captured "expected output" block was produced by actually
  running the named command against this repository's real code — see
  `docs/problems/problems_phase_15.md` for exactly which commands were run.
- All data shown anywhere in this guide is synthetic, generated by
  `data_plane.reference_data`/`data_plane.synthetic`, per
  `DATA_GOVERNANCE.md` Part A. No chapter here introduces a real name,
  a real organization, or a real secret.
