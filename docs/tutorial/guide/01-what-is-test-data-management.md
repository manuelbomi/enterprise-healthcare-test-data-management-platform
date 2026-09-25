# Chapter 1 — What Test Data Management is

## The problem, before the term

Every piece of software that touches a database needs to be tested
against *some* data before it ships. Where does that data come from?

For a small side project, the answer is "whatever I typed in by hand."
For an enterprise healthcare platform with dozens of teams, hundreds of
databases and files, and millions of patient records, that answer stops
working almost immediately:

- Hand-typed fixtures are too small and too clean. They don't have the
  volume, the messy edge cases, the duplicate records, the missing
  fields, or the cross-system relationships that real production data
  has — so tests built against them pass, and the same code still
  breaks in production against real data shapes it never saw.
- Copying production data into a test database is fast and realistic,
  but if that production data contains real patient information, every
  laptop, CI runner, and test database that now holds a copy of it is a
  new place a data breach can happen — for no gain to the business,
  since nobody's testing needs actually require the *real* patient
  named in that record.

**Test Data Management (TDM)** is the discipline — and, in this
repository, the *platform* — that exists to solve this well: to
consistently produce data for non-production use that is realistic
enough to test against, safe enough to never cause a breach if it
leaks, cheap enough to store and refresh on a schedule, and provably
correct enough that a compliance officer can sign off on it having gone
through a real process. That last sentence is copied nearly verbatim
from `docs/tutorial/00-overview.md`, because it is the single most
important sentence in this entire repository — every phase this
platform is built from exists to make one clause of it real.

## TDM is a pipeline, not a single tool

There is no one piece of software called "the TDM tool." TDM is a
*sequence* of distinct capabilities, each of which this repository
builds as its own real, testable component:

```mermaid
flowchart LR
    A[Real or synthetic\nsource data] --> B[Profile & classify\n(Ch. 5-6)]
    B --> C[Subset\n(Ch. 7-8)]
    C --> D[Mask / pseudonymize\n(Ch. 9-10)]
    D --> E[Fill gaps with\nsynthetic data (Ch. 11)]
    E --> F[Certify\n(Ch. 12)]
    F --> G[Publish as a\nsnapshot (Ch. 13)]
    G --> H[Used in dev/test/QA/UAT\n(Ch. 4)]
```

This exact sequence is `ARCHITECTURE.md`'s own pipeline description
(`INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK -> GENERATE OPTIONAL
SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH`), and it is not
theoretical — `data_plane.certification.pipeline.run_certification_pipeline`
runs exactly this sequence against real code, calling Phase 1's
generator, Phase 2's discovery engine, Phase 4's subsetting engine,
Phase 3's masking engine, and Phase 5's synthetic-scenario generator in
order. Chapters 5 through 13 of this guide walk through each stage.

## Why this repository is a good place to learn TDM from

This repository is a from-scratch, portfolio-grade build of an
enterprise TDM platform, using **only synthetic data** — see
`DATA_GOVERNANCE.md` Part A. That means you can read every module,
run every CLI, and see real output, without ever touching anything
sensitive. `services/data-plane/src/data_plane/reference_data` (Chapter
11) generates a completely fake but realistically-shaped multi-system
healthcare estate — fake members, fake claims, fake lab results — so
every later stage of the pipeline has something real to work on.

Try it now — this is the same command every later chapter in this
guide builds on:

```bash
cd services/data-plane
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
```

Real output from running exactly this command:

```
Generated 'tiny' scale estate (seed=20240101).
  Enrollment DB: sqlite:///.../data/tmp/synthetic-estate/postgres_enrollment/enrollment.sqlite3
  Files written: 11
  Manifest:      .../data/tmp/synthetic-estate/manifest.json
                  member: 26
     member_demographics: 24
                 address: 38
                    plan: 6
                coverage: 36
                provider: 10
               diagnosis: 30
               procedure: 30
                   claim: 53
              claim_line: 92
                pharmacy: 5
            prescription: 43
               encounter: 39
              lab_result: 55
```

Every one of those 483 rows is fake — no real member, claim, or lab
result exists anywhere in this repository. That single property is what
makes it safe to build, run, and publish every example in this guide.

## What "the platform" actually is, structurally

`ARCHITECTURE.md` decomposes the system into six planes (control, data,
metadata, security/governance, UI, infrastructure), each owned by a
different real folder in this repository:

| Plane | Folder |
|---|---|
| Control | `services/control-plane` |
| Data | `services/data-plane` |
| Metadata | PostgreSQL schema under `services/control-plane/src/control_plane/db` |
| Security/governance | `services/governance-service` (scaffold) + `control_plane.platform`/`.domain.governance`/`.domain.evidence` |
| UI | `frontend/` |
| Infrastructure | `infra/` |

Keeping this map in your head — "which plane owns this concern?" — is,
per `docs/tutorial/00-overview.md`, the single most useful habit for
navigating this codebase, and it is why almost every chapter in this
guide names the real folder its topic lives in.

## Where to go next

Read `docs/tutorial/00-overview.md` for the original Phase 0 framing of
this same material, then continue to
[Chapter 2 — Why regulated enterprises need TDM](02-why-regulated-enterprises-need-tdm.md).
