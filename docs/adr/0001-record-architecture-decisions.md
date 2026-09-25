# ADR-0001: Record architecture decisions as ADRs

## Status

Accepted

## Context

This project is explicitly a teaching artifact as well as a working system.
Junior engineers reading this repository later need to understand not just
*what* the architecture is (covered in `ARCHITECTURE.md`) but *why* specific,
often-debatable decisions were made — and senior engineers extending the
system need a durable record so decisions aren't silently re-litigated or
accidentally reversed.

## Decision

We record significant architectural decisions as Architecture Decision
Records (ADRs) in `docs/adr/`, one Markdown file per decision, numbered
sequentially (`0001`, `0002`, ...). Each ADR follows this shape:

- **Status** — Proposed, Accepted, Superseded
- **Context** — the problem/forces at play
- **Decision** — what we chose
- **Consequences** — what this makes easier, what it makes harder, what it
  costs

A decision that reverses an earlier one gets a *new* ADR that says it
supersedes the old one; the old ADR's Status is updated to
`Superseded by ADR-XXXX`, but its content is never deleted or rewritten —
the history of "we used to think X" is itself valuable.

## Consequences

- Every ADR is a small amount of extra writing at decision time.
- In exchange, nobody has to reverse-engineer intent from code or commit
  messages later, and a decision is never silently reversed without a
  paper trail.
- ADRs are referenced from `ARCHITECTURE.md` and from code comments where a
  non-obvious choice is implemented, so a reader can jump straight to the
  reasoning.
