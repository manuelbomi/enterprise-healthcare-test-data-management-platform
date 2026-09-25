# scripts

Developer utility scripts.

- `bootstrap.sh` / `bootstrap.ps1` — install every Python workspace package
  (`libs/contracts`, each `services/*`) in editable mode plus dev extras, in
  the dependency order required for local development. Run this after
  cloning, before running any tests. See the script's own header comment
  for *why* this exists as a script rather than `pyproject.toml` `file:`
  URL dependencies — a real pip bug hit in Phase 1 when the repo's parent
  directory name contains a space.

Planned for later phases:

- `dev-up.sh` / `dev-up.ps1` — start local infrastructure (`docker compose up`)
  and wait for health checks to pass (Phase 4/11).
- `lint-all.sh` / `test-all.sh` — run lint/tests across every package,
  used both locally and by CI (Phase 12).

Each script, once added, must be documented here with what it does and
when to use it.
