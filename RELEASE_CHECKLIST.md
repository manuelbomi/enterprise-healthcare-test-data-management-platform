# Release Checklist — Final Phase (Recruiter/Interviewer-Ready Release)

Every check below was **actually executed** in this environment on
2026-09-26, immediately before this checklist was written — none of these
results are assumed or carried over from an earlier phase's own claim
without being re-run. Where a result differs from a prior phase's snapshot
(e.g. `docs/problems/problems_final_review.md`'s Phase 18B test table), that is called out
explicitly rather than silently reconciled.

## 1. Backend test suites (`python -m pytest -q`, run fresh, per package)

| Package | Command | Result |
|---|---|---|
| `libs/contracts` | `python -m pytest -q` | **62 passed**, 0 failed |
| `services/control-plane` | `python -m pytest -q` | **265 passed**, 0 failed (82.30s) |
| `services/data-plane` | `python -m pytest -q` | **459 passed**, 0 failed (70.61s) |
| `services/governance-service` | `python -m pytest -q` | **2 passed**, 0 failed |
| **Backend total** | | **788 passed, 0 failed, 0 unexpected skips** |

`services/data-plane`'s known data-dependent skip guards
(`docs/problems/problems_final_review.md` P3-9 mechanism) reported "2/3 known
data-dependent guard(s) fired this run" — both are the seed/scale-dependent
guards this mechanism exists to surface loudly, not a silent regression;
neither is a `@pytest.mark.skip`/`xfail` hiding a real failure. **788
matches the Phase 18B baseline exactly (62+265+459+2) — no regression found
anywhere in the backend suite.**

## 2. Frontend (`frontend/`)

| Check | Command | Result |
|---|---|---|
| Unit/component tests | `npm test -- --run` | **40 passed** (11 files) |
| Lint | `npm run lint` | **0 errors** |
| Production build | `npm run build` | **Passes** — `dist/assets/index-*.js` 286.28 kB (89.48 kB gzip) |

Matches the Phase 18B baseline (40 passed / 0 lint errors / ~286 kB bundle)
exactly — no regression.

## 3. Security checks

| Check | Command | Result |
|---|---|---|
| Secrets scan | `python scripts/security/detect_secrets.py` | **Clean** — "no secret-shaped content found in the tracked tree" |
| Doc/code citation cross-check | `python scripts/check_doc_code_citations.py` | **Clean** — 194 module-path + 26 route citations across 26 doc files, all resolve against the live source tree |
| Frontend dependency audit | `npm audit` | **0 vulnerabilities** across 485 dependencies |
| Python dependency audit | `python scripts/security/dependency_scan.py` | See note below — **not clean**, but not a repository regression either |
| No real org/vendor names | `grep -ril` for Epic/Cerner/Optum/UnitedHealth/Anthem/Kaiser/Humana/Aetna/Cigna/Athenahealth/Meditech/Allscripts | **0 matches** |
| No real PHI/PII | Repository-wide convention (`DATA_GOVERNANCE.md`, `SECURITY.md`); every dataset traced to `data_plane.reference_data`/`data_plane.synthetic` | **Consistent with prior-phase verification; no new data files introduced this phase** |

**Python dependency audit, explained honestly:** `dependency_scan.py`
reported 52 known advisories across 9 packages (`pillow`, `pip`, `pyasn1`,
`pytest`, `sqlparse`, plus 5 packages this scan itself lists as skipped for
being editable-installed local workspace packages, which are not real
findings). This ran against the shared Python environment available in this
task's sandbox, not an isolated, repository-scoped virtualenv — confirmed by
`pip show forgezen-sdk` returning a real, installed, unrelated package
(`forgezen-sdk`, "Official Python SDK for the ForgeZen Public API") that no
`pyproject.toml` in this repository declares as a dependency at all. Cross-
checking the remaining four flagged package names against every
`pyproject.toml` in this repository: `pillow`, `pyasn1`, and `sqlparse` are
declared by **none** of them (pure environment noise, not a repository
finding). `pytest>=8.0` **is** a real, declared dev-only dependency of every
Python package here, and the installed `8.4.2` has one open advisory
(`PYSEC-2026-1845`, fixed in `9.0.3`) — real, low-risk (a dev/test-only tool,
never shipped in any runtime artifact), and **left open, not fixed, in this
documentation-only release phase** (bumping a pinned dependency is an
application-code/config change, out of this phase's scope per its own
instructions). Flagged here for a follow-up maintenance pass rather than
silently omitted.

## 4. `docs/problems/problems_final_review.md` — current state

**11 findings remain open (6 P2 + 5 P3), unchanged by this phase** (this
phase is documentation/release-prep only; it does not fix or delete any
finding):

- P2: P2-4, P2-5, P2-6, P2-7, P2-8, P2-13
- P3: P3-1, P3-2, P3-5, P3-6, P3-10

Every one of these is summarized honestly in `README.md` §19 and linked
directly to this file rather than re-derived — see `docs/problems/problems_final_review.md`
itself for the authoritative, full reasoning behind each.

## 5. Documentation cross-references

| Item | Status |
|---|---|
| `ROADMAP.md` phase table | Updated this phase — Final Phase marked **Complete**, closing section added |
| `CHANGELOG.md` | Reflects Phase 0–18B (`[0.2.0]`/`[0.1.0]`); this Final Phase is a release-prep/documentation phase, not a new functional version — no new entry required by its own versioning convention (§ "PATCH — a documentation/citation-accuracy-only change" does not strictly apply either, since no code or contract changed; see `CHANGELOG.md`'s own convention section) |
| `README.md` | Rewritten this phase — 21/21 required sections present (see mapping below) |
| `DEMO.md` | New this phase — every command actually run and captured, per §6 below |
| Synthetic-data statement | Present verbatim, prominently, near the top of `README.md` |
| No HIPAA/regulatory-approval claim | Confirmed absent; `README.md` §20 explicitly states the negative |

### README.md section mapping (all 21 required sections present)

| # | Required section | README.md heading |
|---|---|---|
| 1 | Enterprise problem | `## 1. Enterprise problem` |
| 2 | Architecture diagram | `## 2. Architecture diagram` |
| 3 | Core capabilities | `## 3. Core capabilities` |
| 4 | Cloud Test Data Management | `## 4. Cloud Test Data Management` |
| 5 | PHI/PII masking | `## 5. PHI/PII masking` |
| 6 | Referential integrity | `## 6. Referential integrity` |
| 7 | Production-scale subsetting | `## 7. Production-scale subsetting` |
| 8 | Synthetic generation | `## 8. Synthetic generation` |
| 9 | Certified datasets | `## 9. Certified datasets` |
| 10 | Refresh cadence | `## 10. Refresh cadence` |
| 11 | Storage/compute optimization | `## 11. Storage/compute optimization` |
| 12 | Platform integrity | `## 12. Platform integrity` |
| 13 | Audit evidence | `## 13. Audit evidence` |
| 14 | Technology stack | `## 14. Technology stack` |
| 15 | Local quick start | `## 15. Local quick start` |
| 16 | Screenshots | `## 16. Screenshots` |
| 17 | Architecture decisions | `## 17. Architecture decisions` |
| 18 | Testing strategy | `## 18. Testing strategy` |
| 19 | Security limitations | `## 19. Security limitations (read this section)` |
| 20 | Production deployment model | `## 20. Production deployment model` |
| 21 | Tutorial links | `## 21. Tutorial links` |

## 6. `DEMO.md` — verification

Every command in `DEMO.md` was executed in this environment, in the order
written, immediately before this checklist:

1. Started `services/control-plane` via `uvicorn` with a freshly generated
   dev JWT signing key — `GET /api/v1/health` and `GET /api/v1/ready` both
   returned real, healthy responses.
2. Logged in as `demo.platform_admin` via `POST /api/v1/auth/login` — got
   back a real, signed JWT.
3. Ran `python -m data_plane.certification.cli --scale tiny --seed 42 ...
   --publish` — the real 12-gate certification pipeline, all 12 gates
   PASS, `Status: PUBLISHED`.
4. Registered the resulting `certification_report.json` as a real dataset
   version against the live server (`201`, real `version_id`), then proved
   RBAC live against `POST .../revoke`: no token → `401`; `demo.viewer`
   token (wrong role) → `403`; `demo.platform_admin` token (right role) →
   `200`, `"status":"revoked"`. `GET /api/v1/audit/events` showed the real
   `access_denied` and `dataset_version_revoked` events, the latter
   recording the verified actor identity.
5. Started `frontend` via `npm run dev` — confirmed the Vite proxy forwards
   `/api/*` to the live control plane (`curl http://localhost:5173/api/v1/lifecycle/dataset-versions`
   returned the real dataset version registered in step 4).

All dev-server processes and generated `data/tmp/` artifacts from this
verification run were stopped/removed after verification; `git status`
remained clean throughout (everything written lands under a `**/data/tmp/`
path this repository's `.gitignore` already excludes).

## 7. Regressions found during this phase

**None.** No test failure, lint failure, or build failure was observed
anywhere in this phase's verification. (One pre-existing, real, low-risk
finding — the `pytest` advisory in §3 — was surfaced by running the
existing dependency-scan tooling as instructed, not newly introduced; it is
explicitly left open per this phase's own "documentation/release-prep only,
do not modify application code" scope.)

One documentation staleness issue, found incidentally while researching this
phase and **not fixed** (out of this phase's explicit deliverable list —
flagged for a future pass): `frontend/src/pages/README.md`'s inventory table
still describes `AuditTrailPage` as "Honest placeholder (Phase 13 not built
yet)," but Phase 18A (`docs/problems/problems_final_review.md` P1-4) rewrote that page to
call the real `GET /api/v1/audit/events` endpoint — `README.md` §16 in this
release describes the page correctly; `frontend/src/pages/README.md` itself
was not updated in Phase 18A and still needs a one-line correction.

## 8. Links

- Full phase-by-phase history: [`ROADMAP.md`](ROADMAP.md)
- Versioned summary: [`CHANGELOG.md`](CHANGELOG.md)
- Current open findings (authoritative): [`docs/problems/problems_final_review.md`](docs/problems/problems_final_review.md)
- Recruiter/interviewer entry point: [`README.md`](README.md)
- Live, tested walkthrough: [`DEMO.md`](DEMO.md)
