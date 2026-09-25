# tdm-governance-service

The security/governance plane: RBAC decisions, the immutable audit event
log, the secrets provider adapter, and the certification evidence store.
See `ARCHITECTURE.md` section 2.4 and `THREAT_MODEL.md` at the repository
root.

Every other plane calls into this service to check permissions, emit audit
events, or resolve secrets. This service never calls into the others — see
`docs/adr/0003-plane-separation.md`.

## Phase 0 status

Structural scaffold only. See `problems_master.md` and `ROADMAP.md`
(Phase 3) for what's next.

## Layout

```
src/governance_service/
├── api/     # RBAC / authorization decision endpoints (Phase 3)
└── audit/    # Immutable audit event log (Phase 3)
```
