# CLAUDE.md — MASTER BUILD PROMPT
# Project: CHHAYA (छाया) — shade-aware & flood-aware pedestrian routing for Indian cities
# Hackathon: WeMakeDevs × AWS "Environmental Hacks" (Bharat Builds Tour event 02), Oct 8–11 2026
# Track: Heat and Water

## 0. YOUR ROLE AND OPERATING RULES

You are the lead engineer on a 4-day hackathon team. You write production-quality but hackathon-scoped code. Rules:

1. Scope discipline. Build exactly the MVP in §2 first, end to end, before any stretch item. One working feature beats five that almost work — this is literally the judging criterion.
2. Never guess AWS API shapes, CLI flags, or library signatures. If unsure, check the official docs (WebFetch), run `aws <service> <command> help`, or `python -c "help(obj)"`. Wrong guesses cost deploy cycles we don't have.
3. Every geospatial computation must be visually verified before it is merged: produce a PNG/HTML plot and ask a human to confirm. Shadow direction bugs (azimuth convention, degrees vs radians, CRS mix-ups) look plausible and are only caught by eye.
4. Freeze the data contracts in §6 on day 1. Frontend and backend build in parallel against them. Changing a contract requires updating this file first.
5. Prefer small dependency sets in Lambda. Routing Lambda = `numpy` + `networkx` only. Shade Lambda = `numpy` + `shapely` only. No geopandas/osmnx/pyproj/pandas/scipy inside Lambda. Those run in the local pipeline only.
6. Free-tier guardrails in §4 are hard constraints.
7. Keep a running `docs/DECISIONS.md` (one line per decision) and `docs/AI_TOOLS.md` (rules require listing AI coding tools used).
8. Commit small, commit often, conventional-commit messages. All work happens after the hackathon clock started; never import pre-existing project code.
9. When blocked > 20 minutes on an AWS deploy issue, write the exact error string into `docs/BLOCKERS.md` and propose the fallback from §11 instead of spinning.

## 1. CONTEXT

- Judging: (1) Idea and impact, (2) Built on AWS — mandatory for prizes, (3) Design and usability — would someone not on the team know what to do with it?, (4) Execution — working beats polished, (5) 3-minute demo video — no live demo; if the video doesn't show it, it doesn't count.
- Submission = public GitHub repo + YouTube demo video ≤ 3 min (public/unlisted) + short writeup (problem, build, where AWS fits, AI tools used).
- Team is in India; all AWS resources in `ap-south-1` (Mumbai) unless a service is unavailable there (then `us-east-1` for that one service, documented in DECISIONS.md).
- AWS account is a new Free-plan account: $100 credits at signup, up to $100 more by exploring services; account closes after 6 months or when credits are gone; no bill is possible on Free plan, but credit exhaustion freezes the account mid-hackathon, so waste is still fatal.

## 2. PRODUCT DEFINITION

Problem: In Indian cities, walking 1–2 km in May heat or July monsoon is dangerous — heatstroke on exposed roads, waterlogged underpasses and low streets. Map apps optimise distance only.

Solution: A mobile-first web app. User enters origin, destination, departure time, and mode (Summer / Monsoon). App shows two routes on a map:
- DIRECT: shortest walking path.
- CHHAYA: cost-optimised path — in Summer mode, maximise building shade at that time of day; in Monsoon mode, avoid low-lying/waterlogging-prone streets and underpasses.
Plus a comparison card: "6 min longer · 65% shaded vs 20% · 11 fewer minutes in direct sun" or "4 min longer · avoids 2 flood-prone streets and 1 underpass".

### MVP (must be in the demo video)
M1. Coverage: one neighbourhood (~2×2 km), configured as `AREA_NAME` + `BBOX` in `pipeline/config.py`. Coverage polygon drawn on the map; points outside give a clear message.
M2. Precomputed per-street shade fraction for every 15-minute slot 07:00–18:45 IST (48 slots) for two representative dates: Summer = May 15, Monsoon = July 15.
M3. Precomputed per-street flood-risk score 0–1 from Copernicus GLO-30 DEM (HAND + TWI via pysheds) + OSM tunnel/underpass flags + optional manual hotspot list.
M4. Routing API on Lambda behind API Gateway: direct route + Chhaya route, both as GeoJSON with stats.
M5. React + MapLibre frontend on Amplify Hosting, map tiles and place search from Amazon Location Service, departure-time picker, mode toggle, comparison card, mobile layout.
M6. Standard-map baseline: Amazon Location Routes `CalculateRoutes` (pedestrian) drawn as a grey third line for honest comparison.
M7. CloudWatch logs + custom metrics + one dashboard (screenshot goes in the video).
M8. Everything deployed from `infra/template.yaml` with SAM CLI (also counts as an AWS open-source tool).

### Stretch (strict order; only after M1–M8 work end to end)
S1. Crowd reports: "This street is waterlogged now" button → DynamoDB with 6-hour TTL → raises flood cost on nearby edges in real time; report pins on map.
S2. Shade pipeline as a Step Functions state machine (Map state over 96 season×slot items → shade Lambda → assemble Lambda).
S3. Bedrock one-line route advice in English + Hindi.
S4. Time slider that animates the Chhaya route across the day.
S5. Trees (`natural=tree`) as partial shade sources.
S6. Second neighbourhood via Step Functions Distributed Map over tiles.

## 3. ARCHITECTURE
Browser (React + MapLibre, Amplify Hosting)
│ tiles / autocomplete / baseline route → Amazon Location Service (API key, referer-restricted)
│ POST /route, /advice, /report, GET /reports → API Gateway (HTTP API, CORS)
▼
Lambda route (python3.12 x86_64, numpy+networkx, loads graph from S3 at cold start, caches in memory)
Lambda report (boto3 → DynamoDB "ChhayaReports", TTL)
Lambda advice (boto3 → Bedrock Converse)
S3 bucket graph.pkl, nodes.npz, buildings.npz, edges.npz, shade_*.npy, flood.npy, coverage.geojson
Step Functions ShadePipeline: Map(96 items, MaxConcurrency 20) → Lambda shade_slot → Lambda assemble_graph
CloudWatch logs, EMF metrics (route_ms, extra_min, shade_gain_pct), dashboard; X-Ray tracing on
Local pipeline (laptop): osmnx → geopandas/pyproj → pysheds → shapely/pvlib → uploads artefacts to S3

Why each service (this goes in the writeup verbatim): Location Service = real map tiles, geocoding, and the honest baseline route; Lambda + API Gateway = pay-nothing routing API; S3 = artefact store; Amplify = CI-deployed frontend; Step Functions = parallel shade precompute; DynamoDB = live crowd reports; Bedrock = plain-language advice; CloudWatch = we can show it working.

Not used, on purpose: RDS/Aurora (no relational need), EKS/ECS (no containers needed), Cognito (anonymous reports are fine for MVP; Location uses API keys), App Runner (not on Free plan).

## 4. FREE-TIER GUARDRAILS (hard constraints)

- Region `ap-south-1`. Verify on day 1 that Location Service (Maps v2 / Places v2 / Routes v2) and Bedrock on-demand models exist there: `aws bedrock list-foundation-models --region ap-south-1 --by-inference-type ON_DEMAND`. If Bedrock model list is empty/unsuitable, point ONLY the advice Lambda at `us-east-1` via env `BEDROCK_REGION` (plain cross-region API call is fine; "cross-Region inference profiles" are what's not supported on Free plan).
- Set an AWS Budget alert at $5 of credit usage (console, first hour).
- Lambda: memory 1769 MB for route (one full vCPU, faster cold start), 512 MB others; timeout 25 s for route (API Gateway HTTP API caps integration at 30 s), 300 s for shade_slot; no provisioned concurrency; no VPC.
- Lambda zip + layers ≤ 250 MB unzipped. Check with `du -sh .aws-sam/build/<Fn>`. If any function exceeds this, switch that function to a container image (ECR is on the Free plan) — do not fight with layer tricks.
- Build Lambda deps with `pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 --target ...` (or `sam build --use-container` if Docker is available). Never ship host-compiled wheels.
- S3: artefacts < 100 MB total; one bucket; no versioning; lifecycle not needed.
- DynamoDB: on-demand capacity, TTL enabled; one table.
- Step Functions: Standard workflow (4,000 state transitions/month always free); one run ≈ 300 transitions. Do not re-run casually; run the pipeline locally for iteration, use Step Functions for the final build + demo.
- Amplify: one app, one branch, manual trigger builds only if build minutes get burnt.
- Location Service: API key restricted by `AllowReferers` to the Amplify domain + `http://localhost:5173/*`; tile requests are the main cost — don't leave the map open on a 5-second auto-refresh.
- Bedrock: smallest capable model available on demand in region (prefer an Amazon Nova Micro/Lite class model); max 150 output tokens; cache advice per (mode, slot, rounded delta) in memory.
- CloudWatch: log level INFO, no debug spam in loops; metrics via EMF (free) not `PutMetricData` loops.
- No NAT gateways, no load balancers, no EC2, no RDS. Ever.

## 5. REPO LAYOUT
chhaya/
CLAUDE.md # this file
README.md # problem, demo gif, architecture, where AWS fits, run instructions
docs/DECISIONS.md docs/AI_TOOLS.md docs/BLOCKERS.md docs/architecture.png docs/video_script.md
pipeline/ # runs on laptop; Python 3.12; uv or venv
config.py # AREA_NAME, BBOX (west, south, east, north), UTM EPSG, dates, slots, weights, S3 bucket
fetch_osm.py # osmnx → graph + buildings + trees + water → data/raw/*.gpkg
heights.py # fill building heights, log fill-rate stats
dem_flood.py # Copernicus GLO-30 from S3 → pysheds HAND/TWI → per-edge flood_risk
solar.py # pvlib wrapper (local) + pure-numpy NOAA implementation (shared with Lambda) + equivalence test
shade.py # shadow polygons per slot, per-edge shade fraction (both sidewalk offsets, take max)
build_graph.py # assemble graph.pkl + nodes.npz + coverage.geojson, sanity checks
export_arrays.py # buildings.npz / edges.npz as shapely ragged arrays for the Lambda pipeline
upload.py # boto3 upload to S3
plots/ # sanity PNG/HTML outputs (committed, small)
shared/solar_numpy.py # vendored into shade Lambda and used by pipeline tests
lambdas/
route/ handler.py cost.py graph_loader.py requirements.txt
report/ handler.py requirements.txt
advice/ handler.py requirements.txt
shade_slot/ handler.py solar_numpy.py shadow.py requirements.txt
assemble_graph/ handler.py requirements.txt
infra/
template.yaml # SAM: S3, DynamoDB, 5 Lambdas, HTTP API + CORS, Step Functions, Location API key, dashboard
statemachine.asl.json
samconfig.toml
web/ # Vite + React 18 + TypeScript + maplibre-gl
src/ api.ts map/ components/ state/
amplify.yml
tests/ # pytest: solar equivalence, shadow direction, cost monotonicity, API contract
demo/ # scenarios.json (3 origin/dest pairs that show the effect), screenshots

## 6. DATA CONTRACTS (frozen after day 1)

### 6.1 Coordinate systems
- Compute CRS: metric UTM zone of the area centroid. `zone = int((lon + 180) // 6) + 1`; EPSG = `32600 + zone` (Delhi → EPSG:32643). Stored in `config.UTM_EPSG`.
- Storage/API CRS: WGS84 lon/lat (EPSG:4326). GeoJSON order is `[lon, lat]`.
- Timezone: IST = UTC+05:30 fixed, no DST. Never use pytz in Lambda.

### 6.2 Slots and dates
- `SLOTS = 48`; slot `i` = 07:00 + 15·i minutes IST, i ∈ [0, 47] (07:00 … 18:45). Requests outside 07:00–18:59 clamp to nearest slot and set `"clamped": true`.
- `SEASON_DATES = {"summer": "2026-05-15", "monsoon": "2026-07-15"}`.

### 6.3 Graph (`graph.pkl`, pickled `networkx.MultiDiGraph`, built with osmnx `network_type="walk"`, simplified, projected back to WGS84)
Node attrs: `x` (lon), `y` (lat), `x_m`, `y_m` (UTM).
Edge attrs (all required, all edges):
- `length_m: float`
- `highway: str`, `width_m: float` (from lookup in §8.4), `is_underpass: bool` (tunnel=* or layer<0), `is_bridge: bool`
- `shade_summer: np.ndarray[float16, shape (48,)]`, `shade_monsoon: np.ndarray[float16, shape (48,)]` — fraction of edge length in shadow, 0..1; underpasses/tunnels = 1.0; slots with sun altitude < 5° = 1.0
- `flood_risk: float16` in 0..1 (bridges = 0.0)
- `geometry: shapely.LineString` in WGS84
Also `nodes.npz` with `ids (int64)`, `lon`, `lat` (float64) for snapping without osmnx; `coverage.geojson` = convex hull of nodes buffered 50 m (WGS84).

### 6.4 Lambda-pipeline arrays (`buildings.npz`, `edges.npz`) — produced by `shapely.to_ragged_array`, consumed by `shapely.from_ragged_array`; include `height_m`, `edge_ids`, `width_m`, `utm_epsg`, and a 2×3 affine of UTM origin so Lambda never needs pyproj. Per-slot outputs: `shade/{season}/{slot:02d}.npy` float16 shape (E,).

### 6.5 Routing API
`POST /route`
```json
{"origin":[77.21,28.63],"dest":[77.22,28.64],"time":"15:30","mode":"summer"}
```
`time` is IST `HH:MM` or `"now"`. Response 200:
```json
{
 "mode":"summer","slot":34,"slot_time":"15:30","clamped":false,
 "direct": {"geometry":{"type":"LineString","coordinates":[[lon,lat],...]},
            "distance_m":1420,"duration_min":18.2,"shade_pct":21,"sun_minutes":14.4,
            "flood_exposure":0.31,"underpasses":1,"risky_segments":[{"name":"…","risk":0.8}]},
 "chhaya": {…same shape…},
 "baseline": {"geometry":{…},"distance_m":1390,"duration_min":17.5} ,
 "delta": {"extra_min":6.1,"extra_m":480,"shade_gain_pct":44,"sun_minutes_saved":10.9,"flood_exposure_drop":0.22,"underpasses_avoided":1},
 "summary_en":"6 min longer, 65% shaded vs 21%.",
 "summary_hi":"6 मिनट लंबा, 65% छाया बनाम 21%।"
}
```
Errors: 400 `{"error":"outside_coverage","coverage":<GeoJSON polygon>}`, 400 `{"error":"bad_request","detail":"…"}`. `baseline` is `null` if the Location Routes call fails (never fail the whole request because of it). `summary_*` are template strings, not Bedrock.

`POST /advice` body = the `/route` response minus geometries → `{"en":"…","hi":"…","model":"…"}` (≤ 40 words each). On any Bedrock error return the template summaries with `"model":"fallback"`.

`POST /report` `{"lon":..,"lat":..,"type":"waterlogged"|"blocked"|"shade_tip","note":"…"}` → 201 `{"id":"…","expires_at":…}`. Stored as `pk="active"`, `sk="<ISO8601>#<uuid>"`, `ttl` = now + 6 h epoch seconds, `geohash7`, `lon`, `lat`, `type`, `note`.
`GET /reports` → active reports (Query `pk="active"` and `sk > now-6h`).

### 6.6 Walking speed: 1.3 m/s. `duration_min = distance_m / 1.3 / 60`. `sun_minutes = Σ length_i·(1−shade_i)/1.3/60`.

## 7. MODULE SPECS

### 7.1 pipeline/fetch_osm.py
- `osmnx>=2.0`. Bbox tuple order is `(west, south, east, north)` i.e. left, bottom, right, top — this changed in v2, do not use north/south/east/west kwargs.
- `G = ox.graph_from_bbox(BBOX, network_type="walk", simplify=True, retain_all=False)`; buildings = `ox.features_from_bbox(BBOX, tags={"building": True})`; trees = `{"natural": "tree"}`; water = `{"natural": "water", "waterway": True}`.
- Log counts; abort with a loud message if buildings < 500 (coverage too thin — pick another area).
- Save to `data/raw/{graph.graphml, buildings.gpkg, trees.gpkg, water.gpkg}`. Use `ox.save_graphml`/`ox.load_graphml`.

### 7.2 pipeline/heights.py
Height precedence per building: `height` tag (parse "12", "12 m", "12.5m"; ignore feet) → `building:levels` × 3.2 + 1.0 → by `building` value: `apartments` 18, `commercial`/`office`/`retail` 12, `residential`/`house` 9, `industrial` 10, `school`/`hospital` 12, else 8. Record `height_source` and print the fill-rate table; the writeup states this assumption. Optional: if a Google Open Buildings 2.5D Temporal height GeoTIFF for the bbox is dropped in `data/ext/ob_height.tif` (exported from Earth Engine `GOOGLE/Research/open-buildings-temporal/v1`, use only where presence > 0.5), use its zonal median as the second priority.

### 7.3 pipeline/dem_flood.py
- Tile: `s3://copernicus-dem-30m/Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif` (`10` = arc-seconds; Delhi → `N28_00_E077_00`). Read with rasterio using `--no-sign-request` semantics (`AWS_NO_SIGN_REQUEST=YES`), window-clip to bbox + 2 km margin.
- Burn OSM water by −10 m; pysheds: `fill_pits → fill_depressions → resolve_flats → flowdir → accumulation → compute_hand` (stream mask = accumulation ≥ threshold; start at 200 cells, tune so that ≥ 1 stream crosses the area); TWI = ln(acc_area / tan(slope)).
- Per edge: sample both rasters every 10 m along the UTM geometry, take mean. `flood_risk = clip(0.5·rank_norm(TWI) + 0.5·(1 − rank_norm(HAND)), 0, 1)` using rank normalisation within the area. Manual hotspots `data/hotspots.geojson` (points, e.g. known waterlogging spots from news/municipal lists) add +0.5 within 100 m. Bridges → 0.0. Underpasses keep their value but get the separate `is_underpass` penalty.
- Output `data/flood.parquet` (edge_id, flood_risk, hand, twi) + `plots/flood_map.png`. Be honest in the writeup: 30 m DEM gives relative, not street-exact, risk; hotspots and crowd reports correct it.

### 7.4 shared/solar_numpy.py + pipeline/solar.py
- Pure-numpy NOAA solar position (fractional year, equation of time, declination, hour angle → zenith, azimuth from north clockwise) for arrays of datetimes at one lat/lon. Validate in `tests/test_solar.py` against `pvlib.solarposition.get_solarposition` for both season dates × 48 slots: max abs error < 0.5° in both altitude and azimuth. Lambda uses only the numpy version.

### 7.5 pipeline/shade.py (and lambdas/shade_slot/shadow.py — same code, vendored)
For season, slot: compute sun altitude `alt`, azimuth `az` (from north, clockwise, degrees) at area centroid.
- If `alt < 5°`: shade = 1.0 for all edges; skip.
- Shadow length `L = min(h / tan(alt), 250 m)`. Shadow direction (away from sun) `θ = az + 180°`. Displacement `dx = L·sin(θ)`, `dy = L·cos(θ)` in UTM metres (x east, y north).
- Shadow polygon of footprint `P` = `unary_union([P, translate(P, dx, dy)] + [quad(e_i, e_i + (dx,dy)) for each edge e_i of P.exterior])`. Simplify with `tolerance=0.5`. Trees (stretch S5): circle r=4 m, h=7 m, partial opacity 0.7.
- Shade union: `STRtree` over shadow polygons; for each street edge compute two sidewalk lines `offset_curve(±(width_m/2 − 1.5))` (fallback to centreline if offset fails); shade fraction for a line = `line.intersection(union_of_candidate_shadows).length / line.length`; `edge_shade = max(left, right)` (a walker picks the shady side). Subtract the building's own footprint intersections (streets don't run through buildings; ignore).
- Output `data/shade_{season}.npy` float16 shape (E, 48), and `plots/shadows_{season}_{slot}.png` for slots 0, 16, 24, 32, 44 with buildings, shadows, and a sun-direction arrow. A human must confirm: morning shadows point west, evening shadows point east, noon shadows short and pointing north (northern hemisphere, Delhi lat 28.6°).

### 7.6 pipeline/build_graph.py
Attach arrays to edges (ordering by stable `edge_id` = index in `edges.parquet`), write `graph.pkl` (python `pickle`, protocol 5), `nodes.npz`, `coverage.geojson`. Sanity checks that must pass (assert, print table): mean shade at slot 24 (13:00) < mean shade at slot 44 (18:00); mean shade at slot 4 (08:00) > mean shade at slot 24; all underpasses have shade 1.0; flood_risk in [0,1]; no NaN; graph is weakly connected ≥ 95% of nodes in largest component (drop the rest).

### 7.7 lambdas/route
- Cold start: download `graph.pkl` + `nodes.npz` from S3 (`GRAPH_BUCKET`, `GRAPH_KEY`) to `/tmp`, unpickle, keep in module global. Log `cold_start_ms`.
- Snap: nearest node by numpy over `nodes.npz` using scaled lon (`dlon·cos(lat)`); reject if > 300 m from any node → `outside_coverage`.
- Cost (see §8.1) as a callable weight for `networkx.shortest_path(G, s, t, weight=fn)`; direct uses `weight="length_m"`.
- Stats per route computed from edge attrs; `risky_segments` = top 3 edges by `flood_risk·length` with `name` from edge `name` attr if present.
- Baseline: call Location Routes v2 `CalculateRoutes` (`TravelMode: "Pedestrian"`, `LegGeometryFormat: "Simple"`) via boto3 `geo-routes` client; 3 s timeout; failure → `null`. (Alternatively call it from the browser with the API key; choose one and document.)
- EMF metrics: `RouteLatencyMs`, `ExtraMin`, `ShadeGainPct`, `ColdStart`. `Tracing: Active`.
- Stretch S1: before pathfinding, Query active reports, map each to nearest edge (same numpy snap over edge midpoints), add `report_boost = 0.3·count` (cap 1.0) into the flood term.

### 7.8 lambdas/advice
Bedrock Converse API, system prompt: "You are a concise walking-safety assistant for Indian cities. Reply with JSON {en, hi} only, ≤ 40 words each, mention the specific trade-off numbers given." Temperature 0.2. Wrap in try/except → fallback.

### 7.9 infra/template.yaml (SAM)
Resources: `GraphBucket` (S3), `ReportsTable` (DynamoDB, PAY_PER_REQUEST, TTL attr `ttl`), `RouteFunction`, `ReportFunction`, `AdviceFunction`, `ShadeSlotFunction`, `AssembleGraphFunction`, `HttpApi` (`AWS::Serverless::HttpApi` with `CorsConfiguration` allowing the Amplify domain + localhost), `ShadePipeline` (`AWS::Serverless::StateMachine`, DefinitionUri `statemachine.asl.json`), `LocationApiKey` (`AWS::Location::APIKey` with `Restrictions.AllowActions: ["geo-maps:GetTile","geo-maps:GetStaticMap","geo-places:Autocomplete","geo-places:GetPlace","geo-places:SearchText","geo-routes:CalculateRoutes"]`, `AllowReferers`, `AllowResources: ["arn:aws:geo-maps:ap-south-1::provider/default","arn:aws:geo-places:ap-south-1::provider/default","arn:aws:geo-routes:ap-south-1::provider/default"]` — verify exact ARN format in docs before deploying), `Dashboard` (`AWS::CloudWatch::Dashboard` with route latency, invocations, errors, ExtraMin, ShadeGainPct). Outputs: `ApiUrl`, `BucketName`, `LocationApiKeyValue` (or document retrieval via `aws location describe-key --key-name … --query Key`).
IAM: least privilege per function (S3 GetObject on bucket only; DynamoDB PutItem/Query on table; `bedrock:InvokeModel` on the one model ARN; `geo-routes:CalculateRoutes`).
`statemachine.asl.json`: `Map` over input `items` (96 objects `{season, slot}`), `MaxConcurrency: 20`, `ItemProcessor` → `ShadeSlotFunction` with retry (2 attempts, backoff), then `AssembleGraphFunction`, then `Succeed`. Input generator script `infra/run_pipeline.sh`.

### 7.10 web/
- Vite + React 18 + TypeScript + `maplibre-gl`. Env: `VITE_API_URL`, `VITE_LOCATION_API_KEY`, `VITE_AWS_REGION=ap-south-1`.
- Map style: Amazon Location Maps v2 Standard style descriptor URL with the API key (verify exact URL format in the Maps v2 docs; pattern is `https://maps.geo.{region}.amazonaws.com/v2/styles/{Style}/descriptor?key={key}`). Add Location attribution.
- Search: Places v2 `Autocomplete` for typeahead (note: Autocomplete returns no coordinates) then `GetPlace` for the position; or `SearchText` with `Filter.BoundingBox = BBOX` in one call. Bias to area centroid; restrict to the coverage bbox.
- UI (mobile-first, max-width 480 px card over the map): origin, destination, time (default "now", 15-min steps), mode segmented control Summer ☀ / Monsoon 🌧, "Find route" button, comparison card, legend (direct = grey dashed, chhaya = green in summer / blue in monsoon, baseline = light grey), coverage polygon outline, "Report waterlogging here" FAB (S1), advice line (S3), time slider (S4).
- Drawing: GeoJSON sources + line layers; shade route styled with a `line-gradient` or per-segment colouring by shade value is a nice-to-have; plain line is acceptable.
- Loading, error, and outside-coverage states must be designed, not raw alerts.
- `amplify.yml`: `npm ci && npm run build`, artifacts `dist/**`. Amplify env vars set in console; never commit the key (it is referer-restricted anyway).

## 8. ALGORITHMS (exact)

### 8.1 Edge cost
flood_eff = min(1.0, flood_risk + hotspot_bonus + report_boost)
w = length_m * (1 + a_shade*(1 - shade[season][slot]) + a_flood*flood_eff + a_under*is_underpass)
summer : a_shade = 2.0, a_flood = 0.0, a_under = 0.0
monsoon: a_shade = 0.5, a_flood = 4.0, a_under = 5.0
Weights live in `config.WEIGHTS`, mirrored in `lambdas/route/cost.py`. Cost is always ≥ length_m, so direct route is always the distance lower bound.

### 8.2 Snap tolerance 300 m. 8.3 Slot from time: `slot = round((minutes_since_0700)/15)`, clamp 0..47. 8.4 Width lookup (m): motorway/trunk 24, primary 20, secondary 15, tertiary 12, residential/unclassified 8, living_street 6, service 5, footway/path/pedestrian/steps 3, default 8.

## 9. TESTS AND VALIDATION GATES (pytest, run before every deploy)
- `test_solar.py`: numpy NOAA vs pvlib < 0.5° (both dates, 48 slots).
- `test_shadow.py`: a 10 m square building, sun alt 45°, az 180° (south) → shadow polygon extends 10 m due north; az 90° (east) → extends west. Area ≈ footprint + 10 m sweep.
- `test_cost.py`: cost ≥ length always; raising shade lowers summer cost; underpass raises monsoon cost; weights symmetric for direct.
- `test_api_contract.py`: `/route` response validates against a JSON schema matching §6.5; outside-coverage returns 400 with polygon.
- `test_graph_sanity.py`: the §7.6 assertions on the built graph.
- Manual gate (human): `plots/shadows_summer_{slot}.png` reviewed; three demo scenarios in `demo/scenarios.json` show a visible route difference (if not, retune `a_shade`/`a_flood` and record in DECISIONS.md).

## 10. BUILD ORDER (each phase has a "done when"; do not start the next phase early)

Phase 0 — Skeleton (Thu morning). Repo, layouts, `config.py` with real `AREA_NAME`/`BBOX`, `template.yaml` with hello-world `RouteFunction` + HTTP API, deployed: `curl $ApiUrl/route` returns `{"ok":true}`. Vite app on Amplify shows a Location map centred on the area. Budget alert set. Done when both URLs are shared in the team chat.
Phase 1 — Data (Thu). fetch_osm, heights, 500 m test tile shade with plots verified by a human, flood raster plotted. Done when `plots/` has approved shadow PNGs.
Phase 2 — Full precompute + graph (Fri morning). Both seasons × 48 slots for the whole bbox, flood per edge, `graph.pkl` on S3, sanity gate passing.
Phase 3 — Routing API (Fri). Real `/route`, EMF metrics, dashboard. Done when `demo/scenarios.json` returns two different routes with sensible deltas, latency < 2 s warm.
Phase 4 — Frontend (Fri–Sat). Search, time, mode, both routes, comparison card, baseline, mobile layout, error states. Done when a non-team member completes a search on a phone without help.
Phase 5 — Stretch in order S1 → S2 → S3 → S4 → S5 (Sat). Each one gated on the previous being deployed and demoed.
Phase 6 — Ship (Sun). Feature freeze 10:00 IST. README, architecture diagram, `docs/video_script.md` (3 min: 0:00 problem shot of a real hot/flooded street, 0:25 demo summer, 1:15 demo monsoon + report, 2:00 architecture + CloudWatch dashboard, 2:40 impact + what's next), record, upload YouTube, submit form, publish Builder Center blog post.

## 11. KNOWN GOTCHAS AND FALLBACKS (researched)
- OSMnx 2.x bbox order `(west, south, east, north)`; `network_type="walk"` already filters ways with separately mapped sidewalks.
- Sparse OSM heights in India are normal; the type-based default is the honest fallback. State the fill rate in the writeup.
- Copernicus GLO-30 is a surface model (includes buildings/vegetation), 30 m cells, 2021 release. HAND/TWI are relative indicators; combine with hotspots and crowd reports.
- Lambda 250 MB unzipped hard limit includes layers. Fallback: container image via ECR (Free plan OK, up to 10 GB).
- HTTP API 30 s integration limit → route Lambda timeout 25 s; if networkx callable-weight Dijkstra is slow on a big graph, precompute a per-request numpy weight vector and use `scipy.sparse.csgraph.dijkstra` only if scipy fits the size budget; otherwise shrink bbox.
- Location Places `Autocomplete` returns no coordinates; use `GetPlace` or `SearchText`.
- `Amazon Location` API keys use action names with `geo-maps:`, `geo-places:`, `geo-routes:` prefixes, not `geo:`.
- Bedrock on Free plan: no cross-Region inference profiles; use an in-Region on-demand model ID and request model access in the console first. If none in `ap-south-1`, set `BEDROCK_REGION=us-east-1` for the advice Lambda only.
- If Step Functions fights back past Sat 18:00 IST: keep the local pipeline as the source of truth, leave the state machine deployed as "pipeline v2 (in progress)" and say so honestly in the video.
- If Amplify build fails on env vars: ensure `VITE_` prefix and that `amplify.yml` writes them to `.env.production` during the build step.
- Never commit `samconfig.toml` with account IDs you don't want public; it's a public repo. Use placeholders + `docs/DEPLOY.md`.

## 12. DELIVERABLES CHECKLIST
[ ] Public repo with history starting at kickoff  [ ] Live Amplify URL  [ ] `/route` live  [ ] 3 demo scenarios  [ ] Video ≤ 3 min showing: the problem, both modes, the comparison card, the AWS console (Lambda, Step Functions run, CloudWatch dashboard, Location usage)  [ ] README with "Where AWS fits" + assumptions + AI tools used  [ ] Architecture diagram  [ ] Builder Center blog post link  [ ] Submission form sent before deadline (check schedule page for the exact hour)

## 13. HOW TO WORK WITH ME
Start every session by reading this file and `docs/DECISIONS.md`. State which phase and module you are on. Produce code in complete files, not fragments. After each module, print the command to run it and the expected output. Ask one precise question when blocked by a product decision; otherwise pick the simplest option and log it in DECISIONS.md.
