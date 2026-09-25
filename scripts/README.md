# scripts

Developer utility scripts. As of Phase 0 this directory is a placeholder —
no scripts exist yet because there is nothing runnable to script against.

Planned for early phases:

- `bootstrap.sh` / `bootstrap.ps1` — install all Python packages
  (`libs/contracts`, each `services/*`) in editable mode plus the frontend
  dependencies, in one command (Phase 1/2, see ADR-0002).
- `dev-up.sh` — start local infrastructure (`docker compose up`) and wait
  for health checks to pass (Phase 4).
- `lint-all.sh` / `test-all.sh` — run lint/tests across every package,
  used both locally and by CI (Phase 18).

Each script, once added, must be documented here with what it does and
when to use it.
