# DEMO.md — a 5-minute, live, interview-ready walkthrough

Every step below was **actually run, in order, in this environment**, while
writing this document (Windows, Git Bash, Python 3.14.4, Node/npm for the
frontend), immediately after a clean `python -m pytest -q` pass across all
four Python packages and a clean `npm run build`. Nothing here is a
plausible-looking command that was never executed — where a real value
(a token, a version ID) is echoed below, it is the literal value that run
produced.

**Talking point to open with:** "This is a synthetic-data-only reference
implementation of an enterprise healthcare Test Data Management platform —
discovery, masking, subsetting, certification, lifecycle, and RBAC, all real
and running locally. I'll show the pipeline actually run, the security
control actually enforced, and the console actually calling the real API."

Assumes `./scripts/bootstrap.sh` (or `scripts\bootstrap.ps1`) has already
been run once. Commands use POSIX shell syntax; PowerShell users substitute
`$env:VAR = 'value'` for `export VAR=value`.

---

## Step 0 — one-time setup (before the interview starts)

```bash
./scripts/bootstrap.sh
```

Installs `libs/contracts` and all three Python services in editable mode.
Do this before the interview, not during it.

## Step 1 — start the control plane (Terminal 1)

```bash
cd services/control-plane
export TDM_CONTROL_PLANE_JWT_SIGNING_KEY=$(python -m control_plane.platform.auth --generate-dev-key)
python -m uvicorn control_plane.main:app --port 8000
```

Real output confirming it's live:

```
$ curl -s http://localhost:8000/api/v1/health
{"status":"ok","service":"control-plane"}

$ curl -s http://localhost:8000/api/v1/ready
{"status":"ready","service":"control-plane","checks":[
  {"name":"database","healthy":true,"required":true,"detail":"reachable"},
  {"name":"catalog_artifact","healthy":false,"required":false,"detail":"not found ..."}
]}
```

**Talking point:** `/ready` genuinely checks the database dependency, not
just process liveness — the `catalog_artifact` check is honestly `false`
because Step 3 hasn't run yet in this fresh session; it's marked
`"required": false` for exactly that reason.

## Step 2 — log in as a seeded synthetic demo identity (Terminal 2)

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo.platform_admin","password":"platform-admin-demo-pw-syn-5"}'
```

Real response (JWT re-issued fresh on every login; the shape below is what
this run actually returned):

```json
{"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...","token_type":"bearer","role":"platform_admin","expires_at":"2026-09-26T12:30:53.422365Z"}
```

**Talking point:** "There are five fixed, publicly-documented synthetic demo
identities, one per role — this is deliberately not a production identity
provider ([ADR-0018](docs/adr/0018-minimal-jwt-identity-layer-for-rbac.md)).
What matters here is that it's a *real* signed JWT that every RBAC-gated
endpoint actually verifies — not a caller-supplied role field, which is
exactly what Phase 17's readiness review found and Phase 18A fixed."

## Step 3 — run the real end-to-end certification pipeline (Terminal 2)

```bash
cd ../../services/data-plane
python -m data_plane.certification.cli --generate-dev-key
# copy the two printed keys into the next two exports:
export TDM_MASKING_HMAC_KEY=<printed masking key>
export TDM_CERTIFICATION_HMAC_KEY=<printed certification key>

python -m data_plane.certification.cli --scale tiny --seed 42 \
  --out-dir data/tmp/certification-run \
  --strategy fixed_population --param count=10 \
  --scenario high_cost_claims --scenario invalid_claim_references \
  --publish
```

Real, captured output from this exact run (generates a synthetic estate,
classifies it, subsets it, masks it, injects two synthetic scenarios, runs
**12 independent certification gates**, and publishes):

```
Certification report: data\tmp\certification-run\certification_report.json
Dataset: tiny-fixed_population  Status: PUBLISHED
Masking policy: phase3-default v1
Masking engine version: 1.0.0
Gates:
  [PASS] phi_pii_policy_coverage: All 88 sensitive catalog column(s) resolve to a real masking technique.
  [PASS] masking_completion: 218 row(s) masked across 10 file(s); 22 masking validation check(s) passed.
  [PASS] referential_integrity: No engine-introduced dangling references. 3 known source orphan(s) and 0 injected negative-test orphan(s) present and accepted (strict=False).
  [PASS] schema_validation: 14 entities schema-validated cleanly.
  [PASS] data_quality_thresholds: 249 total row(s) across 14 entities; 13 member row(s).
  [PASS] row_count_reconciliation: 14 entities reconciled; no row loss detected.
  [PASS] orphan_detection: 3 known/injected orphan reference(s) detected across 3 relationship(s); no threshold configured (report-only).
  [PASS] provenance: Provenance rollup accounts for all 249 row(s).
  [PASS] manifest_generation: All 3 expected manifest artifact(s) present on disk.
  [PASS] policy_version_recorded: Masking policy 'phase3-default' version 1 recorded.
  [PASS] masking_version_recorded: Masking engine version '1.0.0' recorded.
  [PASS] distribution_shape: claim.billed_amount: masked mean 37217.35 within 10.0x of source mean 6539.42 (17 source / 23 masked values compared).
Published at: 2026-09-26 12:05:08.707945+00:00
```

**Talking point:** "This is the actual `INGEST → PROFILE → CLASSIFY → SUBSET
→ MASK → GENERATE SYNTHETIC → VALIDATE → CERTIFY → PUBLISH` pipeline. Every
gate independently re-derives its answer against the *final* output — it
doesn't trust masking's own exit code. `distribution_shape` is the newest
gate, added in Phase 18A after the readiness review found nothing verified
the masked data wasn't degenerately distorted."

## Step 4 — register the certified dataset as a real dataset version, and prove RBAC live (Terminal 2)

```python
python3 - <<'PYEOF'
import json, urllib.request

report = json.load(open("data/tmp/certification-run/certification_report.json"))
body = {
    "dataset_name": "tiny-fixed_population-demo",
    "certification_report": report,
    "storage_uri": "file://data/tmp/certification-run/final",
    "size_bytes": 1048576,
    "row_counts": {"member": 13, "claim": 23},
    "created_by": "demo.platform_admin",
    "retention_days": 30,
    "notes": "DEMO.md walkthrough dataset version",
}
req = urllib.request.Request(
    "http://localhost:8000/api/v1/lifecycle/dataset-versions",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
with urllib.request.urlopen(req) as resp:
    print(resp.status); print(resp.read().decode())
PYEOF
```

Real result: `201`, a real `version_id` (e.g. `f397b72a-97c4-4b81-8371-fbbbb2873dda`),
`"status":"active"`. Confirm it via `GET /api/v1/lifecycle/dataset-versions`
and `GET /api/v1/audit/events` — the registration itself already produced a
real, append-only `dataset_version_registered` audit event with
`"actor":"demo.platform_admin"`.

Now the RBAC demonstration — three calls to the *same* endpoint
(`POST /api/v1/lifecycle/dataset-versions/{version_id}/revoke`), three
different, real outcomes, captured in this exact run:

```bash
VID=<the version_id from above>

# (a) No token at all:
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  http://localhost:8000/api/v1/lifecycle/dataset-versions/$VID/revoke \
  -H "Content-Type: application/json" -d '{"reason":"demo","revoked_by":"demo"}'
# => 401

# (b) A real, verified token — but the wrong role (demo.viewer):
VTOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo.viewer","password":"viewer-demo-pw-syn-1"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  http://localhost:8000/api/v1/lifecycle/dataset-versions/$VID/revoke \
  -H "Authorization: Bearer $VTOKEN" -H "Content-Type: application/json" \
  -d '{"reason":"demo","revoked_by":"demo"}'
# => 403

# (c) The right role (demo.platform_admin):
ATOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo.platform_admin","password":"platform-admin-demo-pw-syn-5"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST http://localhost:8000/api/v1/lifecycle/dataset-versions/$VID/revoke \
  -H "Authorization: Bearer $ATOKEN" -H "Content-Type: application/json" \
  -d '{"reason":"DEMO.md walkthrough: revoke demonstration","revoked_by":"demo.platform_admin"}'
# => 200, "status":"revoked"
```

`GET /api/v1/audit/events` now shows, in this exact run, all three:
an `access_denied` event for `demo.viewer` (`"permission":"revoke_dataset_version"`),
and the allowed `dataset_version_revoked` event recording `"actor":"demo.platform_admin"`
— the *verified* identity from the bearer token, not a caller-supplied field.

**Talking point:** "401 with no token, 403 for the wrong role, 200 for the
right one — and the audit log records who actually did it, verified, not
claimed. This exact 401→403→200 sequence is the concrete fix for the single
highest-severity finding (P0-1) the Phase 17 production-readiness review
found."

## Step 5 — the React console, talking to the same live server (Terminal 3)

```bash
cd frontend
npm install   # first time only
npm run dev
```

Open `http://localhost:5173`. Confirmed in this run: the Vite dev server
proxies `/api/*` straight to the control plane on `:8000` with no extra
configuration —

```
$ curl -s http://localhost:5173/api/v1/lifecycle/dataset-versions
[{"version_id":"f397b72a-...","dataset_name":"tiny-fixed_population-demo", ... "status":"revoked", ...}]
```

Walk through, in order: **Dashboard** (composed tiles from four live APIs) →
**Data Catalog** (real Phase 2 classification data, if Step 3's discovery
step was also run against this session's catalog path) → **Datasets**
(shows the exact dataset version Step 4 just registered and revoked, live)
→ **Audit Trail** (shows the exact 401/403/200 sequence from Step 4, live,
filterable). See `README.md` §16 for what every other page shows and why no
screenshot images are included in this release.

**Talking point to close with:** "Everything you just watched — the
pipeline run, the RBAC enforcement, the audit trail, the console — is the
same real code path, no seeded fixtures standing in for it. What I'd tell
you *not* to trust yet is in `README.md` §19: a production identity
provider, a real object-storage adapter, and free-text PHI detection are all
still open, and I can point you at exactly where."

---

## Cleanup

```bash
# Ctrl+C both the uvicorn and npm run dev processes.
rm -rf services/data-plane/data/tmp/certification-run services/control-plane/data/tmp/control-plane
```

(`data/tmp/` is gitignored everywhere in this repository — nothing above
needs to be, or will be, committed.)
