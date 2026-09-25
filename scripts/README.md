# scripts

Developer utility scripts.

- `bootstrap.sh` / `bootstrap.ps1` — install every Python workspace package
  (`libs/contracts`, each `services/*`) in editable mode plus dev extras, in
  the dependency order required for local development. Run this after
  cloning, before running any tests. See the script's own header comment
  for *why* this exists as a script rather than `pyproject.toml` `file:`
  URL dependencies — a real pip bug hit in Phase 1 when the repo's parent
  directory name contains a space.
- `demo_phase7_lifecycle.py` — an end-to-end demonstration of Phase 7
  (dataset lifecycle and refresh management): runs the real Phase 6
  certification pipeline twice to produce two real `CertificationReport`s,
  then registers/requests-into-5-environments/refreshes/rolls-back/
  revokes them through the real `services/control-plane` API (via
  `TestClient`, backed by a real on-disk SQLite database). A standalone
  operator script, not part of either service's installed package -- see
  its own module docstring for why that's consistent with ADR-0003. Run
  with `python scripts/demo_phase7_lifecycle.py` from the repository
  root (both `data_plane` and `control_plane` must be installed, i.e.
  `bootstrap.sh` already run). See
  `docs/tutorial/07-dataset-lifecycle-and-refresh.md`.
- `demo_phase10_governance.py` — an end-to-end demonstration of Phase 10
  (centralized enterprise masking governance): drafts/approves the real
  Phase 3 `DEFAULT_POLICY` as a governed `MaskingPolicyVersion`,
  registers the two named business consumers (`LEFT_ARM`/`RIGHT_ARM`),
  runs two real Phase 6 certification pipelines (different subset
  sizes, the identical governed policy object) to produce two real
  `DatasetVersion`s, has both consumers submit and fulfill
  `ConsumerDatasetRequest`s that resolve to the identical
  `policy_version_id`, has RIGHT_ARM request additional QA capacity
  (its own refresh cadence) and shows that demand appear in Phase 7's
  real lifecycle API and Phase 8's real capacity plan before/after, and
  demonstrates a rejected adversarial attempt to submit a request
  against an unapproved policy version. Run with
  `python scripts/demo_phase10_governance.py` from the repository root
  (both `data_plane` and `control_plane` must be installed). See
  `docs/tutorial/09-centralized-masking-governance.md` and
  `docs/adr/0014-masking-governance-lives-in-control-plane.md`.

Planned for later phases:

- `dev-up.sh` / `dev-up.ps1` — start local infrastructure (`docker compose up`)
  and wait for health checks to pass (Phase 4/11).
- `lint-all.sh` / `test-all.sh` — run lint/tests across every package,
  used both locally and by CI (Phase 12).

Each script, once added, must be documented here with what it does and
when to use it.
