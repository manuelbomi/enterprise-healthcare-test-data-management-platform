# tdm-governance-service

The security/governance plane: RBAC decisions, the immutable audit event
log, the secrets provider adapter, and the certification evidence store.
See `ARCHITECTURE.md` section 2.4 and `THREAT_MODEL.md` at the repository
root.

Every other plane calls into this service to check permissions, emit audit
events, or resolve secrets. This service never calls into the others — see
`docs/adr/0003-plane-separation.md`.

## Phase 0 status

Structural scaffold only. See `docs/problems/problems_master.md` and `ROADMAP.md`
(Phase 3) for what's next.

## Phase 10 note

`ROADMAP.md` Phase 10 (centralized enterprise masking governance --
policy-version approval workflow, named business consumers) sounds like
it belongs here by name, but was implemented in
`services/control-plane/src/control_plane/domain/governance/` instead,
because it needed a same-transaction integration with that service's
own Phase 7/8 schema, and this service has no database or FastAPI app
yet to build that integration against. See
`docs/adr/0014-masking-governance-lives-in-control-plane.md` for the
full reasoning. *Who is authorized* to approve a masking policy version
(RBAC) remains this service's eventual, still-unbuilt responsibility --
Phase 10 does not enforce that check.

## Layout

```
src/governance_service/
├── api/     # RBAC / authorization decision endpoints (Phase 3)
└── audit/    # Immutable audit event log (Phase 3)
```
