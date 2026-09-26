# Diagrams

Source diagrams for this project, written as [Mermaid](https://mermaid.js.org/)
so they render natively in GitHub's Markdown viewer without any build step,
and stay diffable in version control (a `.mmd`/embedded-in-Markdown text
file diffs cleanly; a binary diagram export does not).

## Index

| File | Shows |
|---|---|
| [`system-context.mmd`](system-context.mmd) | The platform's six planes and how external actors (engineers, auditors, source systems, cloud storage) interact with it |
| [`data-flow-sequence.mmd`](data-flow-sequence.mmd) | Sequence diagram of a single snapshot request, plane by plane (companion to `docs/tutorial/01-planes-and-data-flow.md`) |
| [`plane-dependency.mmd`](plane-dependency.mmd) | Allowed dependency directions between planes/packages (companion to ADR-0002 and ADR-0003) |

The same system-context and plane-dependency diagrams also appear rendered
inline in `ARCHITECTURE.md`; the source files here exist so they can be
reused (e.g., embedded in a slide, exported to an image) without having to
extract them from prose.

## Conventions

- One diagram, one concern. Don't try to cram the whole system into a single
  diagram — that's why there are three files here instead of one.
- Every diagram file starts with a one-line comment (`%%`) stating what it
  shows and which doc it's a companion to, so it's never orphaned context.
- When a diagram and the prose describing it (in `ARCHITECTURE.md` or a
  tutorial doc) disagree after a design change, fix both in the same
  change — a stale diagram is worse than no diagram.

## Note on Phase 0 scope

These are Mermaid source only; no pre-rendered PNG/SVG exports exist yet
(tracked as `P0-4` in `docs/problems/problems_master.md`, low priority since GitHub
renders Mermaid natively).
