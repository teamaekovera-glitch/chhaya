# DEPLOY.md — exact commands to bring the Phase 0 stack live

Run once AWS credentials exist (`aws sts get-caller-identity` succeeds). Commands are
ordered; §0 rule 9 applies — 20 minutes stuck on one error → `docs/BLOCKERS.md` + §11 fallback.

## 0. Before anything deploys (user, console — the plan's first action)

Set the **$5 budget alert** in the AWS console (Billing → Budgets → Create budget →
Cost budget → $5 → alert at 100% of budget, email the team address). This precedes every
deploy — a burned credit balance freezes the account mid-hackathon (§4).

## 1. Verify credentials + region

```bash
aws sts get-caller-identity                 # who am I
aws configure set region ap-south-1         # everything lives in Mumbai (§1)
aws bedrock list-foundation-models --region ap-south-1 --by-inference-type ON_DEMAND \
  --query 'modelSummaries[].modelId'        # Phase 3 input; record in DECISIONS.md, do not hardcode
```

## 2. Toolchain (this build environment has no Docker, no aws-cli, no sam-cli)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install awscli aws-sam-cli
sam --version
```

## 3. Build + validate + deploy the backend stack

```bash
cd infra
sam validate                                # template parse + SAM transform (works offline)
sam build
sam deploy --guided                         # accepts samconfig.toml defaults: stack chhaya-mvp, ap-south-1
```

**No-Docker fallback (§4) when `sam build` is not usable:** `sam build` without Docker
host-installs wheels for the host interpreter (py3.13) — wrong ABI for the python3.12
runtime. The Phase 0 stub handler imports neither numpy nor networkx, so its smoke test
works either way. Before Phase 3 ships code that imports them, build the dependency set
for the Lambda runtime explicitly:

```bash
pip install --platform manylinux2014_x86_64 --only-binary=:all: \
  --python-version 3.12 --implementation cp \
  --target .aws-sam/build/RouteFunction numpy networkx
# then deploy; and check the §4 size guard: du -sh .aws-sam/build/RouteFunction
```

Never ship host-compiled wheels.

## 4. Verify the Phase 0 done-when

```bash
# a) Backend
API_URL=$(aws cloudformation describe-stacks --stack-name chhaya-mvp \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' --output text)
curl "$API_URL/route"                       # expect {"ok": true}
curl -X POST "$API_URL/route" -H 'content-type: application/json' \
  -d '{"origin":[77.19,28.65],"dest":[77.20,28.65],"time":"15:30","mode":"summer"}'

# b) Location key value (referers + env wiring)
aws location describe-key --key-name chhaya-location-key --include-keyholder \
  --query Key --output text
# → console: Location → API keys → chhaya-location-key → Restrictions →
#   add the Amplify domain referer:  https://<amplify-domain>/*   (keep localhost:5173)

# c) Frontend (Amplify Hosting)
#   console: Amplify Hosting → Host web app → connect repo teamaekovera-glitch/chhaya,
#   branch feat/phase-0-skeleton (then main after merge), artifact base directory web/dist.
#   Environment variables (console, NEVER in the repo):
#     VITE_LOCATION_API_KEY=<key from (b)>
#     VITE_API_URL=$API_URL
#     VITE_AWS_REGION=ap-south-1
#   amplify.yml writes them to .env.production at build time (§11 gotcha).
#   Post-deploy: tighten HttpApi CorsConfiguration AllowOrigins from "*" to the Amplify
#   domain + http://localhost:5173 (infra/template.yaml) and re-deploy.
```

## 5. Phase 0 "done when" (§10)

- [ ] `curl $ApiUrl/route` returns `{"ok":true}`
- [ ] Amplify URL shows a Location map centred on Karol Bagh (77.193, 28.6495)
- [ ] Both URLs shared in team chat
- [ ] $5 budget alert confirmed set

## 6. Phase 2 artifact upload (pipeline/upload.py — ready-but-creds-pending)

The full precompute writes S3-bound artifacts that `pipeline/upload.py` uploads in
one pass. `graph.pkl` is upload-ONLY (multi-MB pickle, gitignored; committed
artifacts cap at ~10 MB per the commit-data policy):

| local file (data/) | bucket key | committed to git? |
| ------------------ | ---------- | ----------------- |
| graph.pkl | `graph/graph.pkl` | no — upload-only (see DECISIONS.md for byte size) |
| nodes.npz | `graph/nodes.npz` | yes |
| coverage.geojson | `graph/coverage.geojson` | yes |
| buildings.npz | `arrays/buildings.npz` | yes (§6.4 ragged arrays) |
| edges.npz | `arrays/edges.npz` | yes (§6.4 ragged arrays) |
| shade_summer.npy | `shade/summer.npy` | yes (float16 (E,48)) |
| shade_monsoon.npy | `shade/monsoon.npy` | yes (float16 (E,48)) |
| flood.npy | `flood/flood.npy` | yes (float16 per-edge) |

```bash
python pipeline/upload.py            # dry-run: lists the plan, sends nothing
export GRAPH_BUCKET=<bucket-name>    # explicit go-signal; bucket must exist
python pipeline/upload.py --execute  # actual upload via the default credential chain
```

DEPLOYMENT GATE: the Phase 3 route Lambda reads exactly these five keys
(`graph/graph.pkl`, `shade/summer.npy`, `shade/monsoon.npy`, `flood/flood.npy`,
`graph/coverage.geojson`) from `GraphBucket` at cold start — the upload above
MUST have completed before the first `POST /route`, or the handler answers 500
with a loud `no routing bundle configured` / download error in CloudWatch
(docs/BLOCKERS.md owns the creds-pending row).

## 7. Phase 3 — routing API deploy path (handler + engine live)

`infra/template.yaml` now ships the real Phase 3 RouteFunction: 1024 MB / 30 s,
S3 read policy on GraphBucket, explicit bundle-key env vars
(`S3_KEY_GRAPH` / `S3_KEY_SHADE_SUMMER` / `S3_KEY_SHADE_MONSOON` /
`S3_KEY_FLOOD` / `S3_KEY_COVERAGE`), `WALK_SPEED_MPS=1.1`, and a dedicated
`GET /route/stats` event. No geo-routes IAM is added — the baseline
CalculateRoutes call runs in the browser with the referer-restricted Location
key (docs/DECISIONS.md).

Build + deploy is the SAME § 3 sequence (no flag changes):

```bash
cd infra
sam build && sam validate && sam deploy --guided   # first time; later: sam deploy
# §4 size guard after build:
du -sh .aws-sam/build/RouteFunction                # keep < 250 MB unzipped
```

Wheel fallback reminder (no Docker in CI/sandbox, §3): if `sam build` host-
installs wheels, rebuild setuptools/pip-free with
`pip install --platform manylinux2014_x86_64 --implementation cp
--python-version 3.12 --only-binary=:all: -t .aws-sam/build/RouteFunction
-r lambdas/route/requirements.txt` before zipping — numpy/networkx/shapely only.

Smoke + contract path (replace `$API_URL`, coords are inside the Karol Bagh
BBOX 77.178–77.208 / 28.642–28.657):

```bash
# Phase 0 smoke still answers (contract unchanged):
curl "$API_URL/route"

# Graph summary (§6.6):
curl "$API_URL/route/stats"
# → {"area":"Karol Bagh","n_edges":...,"n_nodes":...,"bbox":[77.178,...],
#    "slots":48,"seasons":["summer","monsoon"],"weights":{...}}

# Direct route:
curl -X POST "$API_URL/route" -H 'content-type: application/json' -d '{
  "origin": [77.1830, 28.6440], "destination": [77.2050, 28.6550],
  "mode": "direct", "time": "15:30"}'

# Shade route for the same ask (summer weighting, a_shade=2.0):
curl -X POST "$API_URL/route" -H 'content-type: application/json' -d '{
  "origin": [77.1830, 28.6440], "destination": [77.2050, 28.6550],
  "mode": "shade", "season": "summer", "time": "15:30"}'

# Flood-aware monsoon route (hard underpass avoidance):
curl -X POST "$API_URL/route" -H 'content-type: application/json' -d '{
  "origin": [77.1830, 28.6440], "destination": [77.2050, 28.6550],
  "mode": "flood", "season": "monsoon", "time": "15:30"}'
```

Response shape (§6.5): `route` ([[lng,lat],...]), `distance_m`, `duration_s`
(at the 1.1 m/s env walk speed), `shade_profile` (48 length-weighted floats —
built from per-edge arrays that already carry the max of both walk sides),
`shade_score` (the profile value at `slot`), `flood_profile` (per season),
`mode`, `season`, `slot`, plus `slot_time` and `clamped`. Errors are
`400 outside_coverage` (with the loaded coverage polygon) / `400 no_route` /
`400 bad_request`; the `/advice` path returns `501` until Phase 6.

Warm-latency watch (§4): the first POST after deploy pays the cold-start
download + engine build (watch the `ColdStartMs` EMF line in CloudWatch →
`chhaya` namespace); warm repeats hit the 64-entry LRU and should stay well
under the 2 s budget.


## 9. Phase 5 — ops deploy path (state machine + dashboard, same stack bootstrap order)

Same stack (`sam deploy --guided` on the existing `chhaya` stack) — no second stack:
SAM adds two resources to it, `PrecomputeHandlerFunction` and `PrecomputeStateMachine`,
plus the `ChhayaOpsDashboard`, in CREATE order below. Nothing from Phase 0–3 is touched;
their resources keep their addresses.

Bootstrap order:

1. Deploy the stack (`sam deploy` as in §3). Create order inside CloudFormation:
   the precompute Lambda first (its only dependency is S3 read/write), then the state machine
   (`DefinitionSubstitutions.PrecomputeHandlerArn` substitutes the Lambda's ARN),
   then the dashboard — safe because the dashboard only reads metric lines, so a
   widget can go "no data" on the first minute without failing the change set.
2. Start a run through the state machine (Summer + Monsoon in one execution):

```bash
aws stepfunctions start-execution \
  --state-machine-arn "$(aws cloudformation describe-stacks --stack-name chhaya \
    --query 'Stacks[0].Outputs[?OutputKey==`PrecomputeStateMachineArn`].OutputValue' --output text)" \
  --input '{"seasons": ["summer", "monsoon"]}'
```

3. Watch it: `aws stepfunctions describe-execution --execution-arn <arn>` until
   `status` is `SUCCEEDED`. The two `RunShadeSeason` branches each produced
   `s3://<GraphBucket>/manifest/{season}.json`; `aws s3 ls s3://<GraphBucket>/manifest/`
   should show both. A failed run surfaces in `ExecutionsFailed`.
4. Dashboard: CloudWatch console → Dashboards → `ChhayaOpsDashboard` — six widgets,
   Phase-3 route metrics (Invocations / Duration / Errors), HttpApi 4xx/5xx, the state
   machine's `ExecutionsStarted/ExecutionsFailed`, and the operational-notes text
   widget. Region is whatever §1 pinned; no region pins in the dashboard JSON itself.
5. Re-run semantics: every state-machine execution rewrites
   `manifest/{season}.json` for the same bucket/key inputs — idempotent, so a re-run
   after fixing data needs no manual S3 cleanup. `ValidateGraph` failures stop the
   run with `NotifyValidationFailure` before any manifest write (the handler validates
   before it uploads — the state machine is invoked post-upload in the offline MVP).
