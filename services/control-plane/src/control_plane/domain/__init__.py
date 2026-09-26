"""Domain layer: orchestration and policy logic.

This is where control-plane business logic lives — job DAG construction,
policy resolution, capacity/quota checks. Code here must not perform I/O
directly against a specific database driver or HTTP client; it depends on
narrow interfaces (repositories, clients) so it stays unit-testable
without a running Postgres/network. Concrete I/O implementations live in
`control_plane.db` and future `control_plane.clients` modules.

Phase 0 scope: this module is an empty placeholder establishing where
orchestration/policy code will live starting Phase 2 (orchestration) and
a future job-orchestration phase (job DAG execution) — not Phase 14,
which actually happened and turned out to be scale/performance
benchmark tooling (`data_plane.spark`/`data_plane.benchmarks`), not job
DAG execution; see `ROADMAP.md` and `docs/problems/problems_phase_14.md`. Job DAG
execution remains unscheduled by name.

Phase 7 adds the first real subpackage here: `domain.lifecycle`
(dataset versions, refresh policies, environment requests, the refresh
orchestration abstraction). It depends only on a `sqlalchemy.orm.Session`
handed to it by the caller (never opens its own connection), keeping it
unit-testable without a running API process -- see
`domain/lifecycle/__init__.py`.
"""
