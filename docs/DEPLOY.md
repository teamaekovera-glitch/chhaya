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
