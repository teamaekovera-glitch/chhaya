# CHHAYA (छाया) — shade- & flood-aware pedestrian routing

Mobile-first web app for walking routes in Indian cities. Given origin, destination,
departure time and mode (**Summer** / **Monsoon**), it shows a **DIRECT** shortest path and
a **CHHAYA** cost-optimised path — shaded streets in summer heat, streets avoiding
flood-prone low points and underpasses in the monsoon — plus an honest comparison card
and a standard-map baseline route. Coverage area: Karol Bagh, Delhi.

WeMakeDevs × AWS "Environmental Hacks" (Bharat Builds Tour 02), Oct 8–11 2026 · Heat & Water track.

## Layout (CLAUDE.md §5)

```
CLAUDE.md          master build prompt — contracts & phase plan (read first)
docs/              DECISIONS.md · AI_TOOLS.md · BLOCKERS.md · DEPLOY.md
pipeline/          local geospatial pipeline (OSM → shade → flood → graph), config.py is the contract anchor
lambdas/           route (numpy+networkx) · report · advice · shade_slot · assemble_graph
infra/             template.yaml (SAM) · samconfig.toml
web/               Vite + React 18 + TypeScript + MapLibre, Amplify Hosting
tests/             pytest gates (§9)
demo/              scenarios.json — origin/dest pairs that show the effect
```

## Status

**Phase 0 — skeleton.** `infra/template.yaml` (GraphBucket, RouteFunction stub, HTTP API + CORS,
Location API key, dashboard), `web/` map centred on Karol Bagh. Backend deploy + Amplify hosting
are pending AWS credentials — see `docs/DEPLOY.md` and `docs/BLOCKERS.md`.

## Run locally

```bash
# web
cd web && npm ci && npm run dev    # needs VITE_LOCATION_API_KEY; falls back to demo tiles without it
# tests
python3 -m pytest tests/
```

## Where AWS fits

Location Service (tiles, search, baseline routes) · Lambda + HTTP API (routing) · S3 (graph +
shade artefacts) · Amplify Hosting (frontend) · Step Functions (shade precompute, Phase 2) ·
DynamoDB (crowd reports, stretch) · Bedrock (advice, stretch) · CloudWatch (metrics + dashboard).
Details: `CLAUDE.md` §3.
