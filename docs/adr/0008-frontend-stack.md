# ADR-0008: React + TypeScript + Vite for the UI, talking only to the control plane

## Status

Accepted

## Context

The UI's job is narrow: let engineers/stewards/auditors request test data,
inspect job/snapshot status, review classifications, and view certification
evidence. It is not a data-visualization-heavy analytics tool and it never
needs direct access to raw data (see `THREAT_MODEL.md`, UI section — the
control plane's API contract only ever returns already-safe data).

## Decision

Build the UI as a single-page application with React + TypeScript + Vite:

- **React** for component-based UI, broadly known, large ecosystem — a
  reasonable default for a teaching project so contributors can focus on
  the domain rather than an unfamiliar framework.
- **TypeScript** in strict mode so the UI's data contracts (mirroring
  `libs/contracts` Pydantic models via generated or hand-maintained
  TypeScript types) are checked at compile time — important in a system
  where a UI bug that mishandles a data shape could plausibly mean
  "accidentally displaying something it shouldn't."
- **Vite** for fast local dev and a simple, modern build pipeline, avoiding
  the configuration overhead of older bundler setups.

The UI communicates with the platform exclusively through the control
plane's public REST API (see `ARCHITECTURE.md` section 4). It has no
direct database connection, no direct object storage access, and no direct
Spark access. This is a security boundary, not just a convenience: it means
every piece of data the UI can possibly render has already passed through
the control plane's authorization and the data plane's masking/
certification, by construction.

Accessibility is a first-class requirement, not a later pass: components
are built semantic-HTML-first, keyboard-navigable, with ARIA used only
where semantic HTML can't express the interaction. This matters both
because it's good engineering practice and because large regulated
organizations frequently have accessibility compliance obligations that a
teaching platform should model correctly.

## Consequences

- The UI cannot offer any "just this once, direct query" shortcut — every
  feature must be backed by a control-plane API endpoint, which is slightly
  more upfront work but keeps the security boundary real rather than
  aspirational.
- TypeScript types for API payloads need to be kept in sync with the
  Python contracts in `libs/contracts`; this is tracked as a contract-testing
  concern (Phase 19) rather than solved by, e.g., a shared runtime language.
- Vite's dev server and build output are used as-is in local development;
  a production build/serving strategy (static hosting behind the control
  plane, a CDN, etc.) is decided in the infrastructure phases.
