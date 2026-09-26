"""Cross-cutting platform-integrity controls (Phase 11).

`ARCHITECTURE.md` section 2.4 describes RBAC, the immutable audit
event log, and readiness as eventual `services/governance-service`
responsibilities. As of this phase, that service remains a structural
scaffold (see `docs/adr/0014-masking-governance-lives-in-control-plane.md`),
so -- for exactly the same same-transaction reasons ADR-0014 already
gives for Phase 10's governance domain -- this phase's real,
DB-integrated controls live here instead:
`docs/adr/0015-platform-integrity-controls-in-control-plane.md` is the
decision record.

Module map
----------
- `rbac.py` -- a real, enforced authorization-check abstraction
  (`Role`, `Permission`, `authorize()`). Not a no-op: an insufficiently-
  privileged actor is rejected, proven by
  `services/control-plane/tests/test_platform_rbac.py` and the
  end-to-end API tests in `test_failure_injection.py`.
- `audit.py` -- `AuditLogRepository`, an append-only writer/reader for
  `healthcare_tdm_contracts.AuditEvent`, wired into the real Phase 7/10
  mutations this phase gates with RBAC.
- `readiness.py` -- dependency-aware readiness checks (database
  connectivity, catalog artifact availability), distinct from the
  Phase 0 liveness-only `/api/v1/health`.
- `retry.py` -- a small, generic retry-with-backoff helper, used by
  the readiness database check (see `docs/problems/problems_phase_11.md` P11-6 for
  why it is deliberately *not* used for data-plane job execution).
- `dead_letter.py` -- `DeadLetterStore`, a durable record of
  individually-isolated job/sweep failures (wired into
  `control_plane.domain.lifecycle.scheduler`).
"""
