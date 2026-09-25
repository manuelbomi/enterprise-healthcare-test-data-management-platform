# ADR-0003: Separate the system into six independent planes

## Status

Accepted

## Context

A TDM platform for a large regulated organization is not built or operated
by one team. In reality, data engineering owns the transformation logic,
platform/SRE owns infrastructure, security/compliance owns governance and
audit, and a product team owns the orchestration and UI. Those groups have
different change cadences, different risk tolerances, and different
on-call responsibilities. A monolithic design that mixes these concerns
makes every change risky (a UI tweak that can somehow affect masking logic)
and makes it hard to reason about "who is allowed to change what."

There's also a technical reason: the data plane needs to scale
independently (Spark compute scales with data volume) from the control
plane (scales with request rate) and from the UI (scales with concurrent
users). Coupling them into one deployable unit would force them to share a
scaling profile that fits none of them well.

## Decision

The system is decomposed into six planes, each with a single
responsibility and a narrow, explicit interface to the others (see
`ARCHITECTURE.md` section 2 for the full breakdown and the interface
table):

1. Control plane — orchestration and policy decisions
2. Data plane — actual data transformation
3. Metadata plane — system of record
4. Security/governance plane — trust, audit, secrets
5. UI — human interface, talks only to the control plane
6. Infrastructure — the substrate everything runs on

The rule that makes this real rather than aspirational: **a plane may only
be reached through its published interface** (REST API, a typed job
contract, a database it owns, a well-defined adapter interface) — never by
one plane importing another plane's internal implementation code. This is
enforced structurally by the package layout in ADR-0002 (data plane code
cannot import control plane internals because they are different
installable packages with no dependency edge between them) and will be
enforced at runtime by network boundaries once services are actually
deployed as separate processes (Phase 2 onward).

## Consequences

- More upfront design work: every cross-plane interaction needs an
  explicit contract (see `libs/contracts`) instead of a convenient shared
  in-process function call.
- Slightly more latency for cross-plane calls that go over a network instead
  of an in-process call, once services are actually deployed separately.
- In exchange: each plane can be developed, tested, deployed, and scaled
  independently; a bug or outage in the data plane (e.g., a stuck Spark job)
  cannot corrupt the audit log or bypass RBAC, because the security/
  governance plane is a separate system the data plane can only *call*, not
  reach into; and the architecture directly models how a real enterprise
  organization would divide ownership, which is the point of a teaching
  repository aimed at engineers who will work in exactly this kind of
  organization.
