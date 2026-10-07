# DECISIONS.md — one line per decision (§0 rule 7)

## Kickoff (2026-10-07)

- Coverage area locked: **Karol Bagh, Delhi** — chosen over Connaught Place for denser mid-rise fabric, which makes the shade contrast more visible in the demo (decision sheet).
- BBOX locked: `(77.178, 28.642, 77.208, 28.657)` (west, south, east, north), EPSG:32643 — `pipeline/config.py`.
- GLO-30 tile stem: `Copernicus_DSM_COG_10_N28_00_E077_00_DEM`; bucket `copernicus-dem-30m` is read unauthenticated, and the exact TIFF key is discovered with `aws s3 ls` before the first open (only listed, never assumed).
- **Deviation from §7.9 (CLAUDE.md):** `LocationApiKey.AllowActions` additionally includes `geo-maps:GetStyleDescriptor` — MapLibre fetches the Maps v2 style descriptor at init, and without this action the map renders blank behind a working tile cache (decision sheet, verified against AWS CFN docs).
- Place search uses Places v2 `SearchText` only (single call, coordinates included, BBox-filtered); the `Autocomplete` → `GetPlace` pair from §7.10 is dropped.
- Baseline route (`geo-routes:CalculateRoutes`, pedestrian) is called **from the browser** with the referer-restricted API key — the route Lambda needs no `geo-routes` IAM, keeping its permission surface at S3-get only.
- `summary_en` / `summary_hi` are template strings (§6.5); Bedrock advice is deferred to Phase 3 stretch and the Bedrock model ID is **runtime-discovered** via `list-foundation-models --by-inference-type ON_DEMAND` after credentials exist — no model ID is hardcoded anywhere in Phase 0.
- CloudWatch dashboard ships as a minimal Phase 0 widget row; the §7.9 metric set (ExtraMin, ShadeGainPct, route latency, invocations, errors) expands in Phase 3 when EMF metrics exist.
- Deploy("/route" smoke test) is one-command-pending on AWS credentials; `docs/BLOCKERS.md` carries the blocker.

## Phase 1 (2026-10-07)

- `shared/solar_numpy.py` uses the **accurate** NOAA/Meeus formulation (fractional-year day-of-year terms + declination + equation-of-time, azimuth from true north clockwise) rather than the §7.4 truncated fractional-year series, which is retained as `solar_position_truncated` for comparison only — the accurate variant clears the §9 0.5° azimuth gate where the truncated series degrades near zenith. Fractional-year unit choice: **degrees** (per the §7.4 text's γ-in-degrees table), logged here per the brief's either/or rule.
- Sun azimuth convention locked: **degrees clockwise from true north** (§7.5); shadow direction is `azimuth + 180°`, UTM sweep displacement `dx = L·sin(θ_adj)`, `dy = L·cos(θ_adj)`, `θ_adj = (azimuth + 180°) mod 360`.
- Published `shared.shadow` import surface adds an **optional `height_m`** kwarg beyond the brief's literal signature: `shadow_sweep_polygon(footprint_utm, sun_altitude_deg, sun_azimuth_deg, max_length=250.0, height_m=None)`. Without `height_m`, `max_length` rides in as an already-computed sweep distance (`h / tan(alt)`, which the §9 tests pass as `max_length=10.0`); with it, `L = min(h / tan(alt), max_length)` per §7.5. Phase 2 callers write against this dual-path surface, not the literal one.
- `shade_fraction(sidewalk_line, shadow_union)` and `sidewalk_offset_lines(linestring, width_m)` live in `shared/geometry.py` (brief named shared/geometry.py as the helper home; it did not specify the second helper's name — this is it).
- pvlib stays a **test-only** dep (§0 rule 5, never a Lambda dep), listed in `tests/requirements.txt`; pytest imports it solely for the §9 equivalence gate.

## Phase 1 — data layer run log (feat/branch: feat/phase-1-data, 2026-10-07)

- **OSM**: Overpass API was unreachable from this environment (SSL EOF / 504); fetched the
  Karol Bagh BBOX extract directly from `api.openstreetmap.org` as `data/raw/map.osm`
  (7.3 MB, 6,195 ways) and added `pipeline/parse_map_osm.py` to convert it into the same
  gpkg/graphml outputs `fetch_osm.py` would have produced. Counts: 4,663 buildings, 36
  trees, 4 water features, walk graph 4,425 nodes / 10,662 directed edges — above the
  500-building abort floor, so the run proceeded.
- **Heights** (`pipeline/heights.py`, §7.2 ladder): 0 direct `height` tags, 122 (2.6%)
  from `building:levels`, 28 (0.6%) from type defaults, 4,513 (96.8%) from the 8 m
  fallback. Fill-rate table committed to this file as the §7.2 record.
- **DEM/flood**: `s3://copernicus-dem-30m` read unauthenticated as planned. Exact object
  discovered via `aws s3 ls` on the stem (no hardcoded key in code); main DEM object =
  `Copernicus_DSM_COG_10_N28_00_E077_00_DEM/Copernicus_DSM_COG_10_N28_00_E077_00_DEM.tif`.
  Reprojection via explicit-transform WarpedVRT (`rasterio.warp.reproject` returned
  all-nodata on this window despite success codes — probe recorded).
  248×203 UTM cells, cell = 28.5 m, elevations 199.9–264.2 m, 50,344 valid cells.
  Water burn mask covered 49 cells; stream threshold 200 accumulation cells → 2,085
  stream cells (max accum 11,835). 10,662 edges scored, 0 outside the DEM window.
  flood_risk: mean 0.500, p90 0.700, max 0.75 (bridges 0, underpasses 0).
  Outputs: `data/flood.parquet`, `pipeline/plots/flood_map.png`.
- **Shade test tile**: 500 m square at the coverage centroid, 583 buildings / 692 edge
  segments per season. `pipeline/solar.py` corrected to the shared canon signature
  `(lat, lon, when_utc)`; shadow/geometry helpers in `pipeline/shade.py` replaced with
  thin adapters over `shared/shadow.py` + `shared/geometry.py` (no local forks).
  Summer slots (16 noon-area, 24 post-noon, 32/44 evening, 00 morning) mean edge shade
  0.33–0.85; monsoon slots 0.34–0.82. Five slot PNGs per season written (sun arrow +
  shaded walks): morning shadows west, evening east, noon short NNE — direction gate
  internally consistent for human review.
- **Library quirks** (for reproducibility): rasterio 1.5.2 requires band-stacked writes
  (`write_band`); pysheds 0.5 `sgrid.Raster` takes nodata from the viewfinder, not
  kwargs; numpy pinned <2.2 for pysheds (`np.in1d` removal).
- **Human gate PENDING**: the ten shadow PNGs (5 summer + 5 monsoon) still need eyes
  that did not write the code before Phase 2 starts.

## Phase 2 — full-area precompute + graph assembly (2026-10-07)

- **Full-area shade run completed**: Karol Bagh bbox, 4,663 buildings / 10,662 edges,
  both seasons × 48 slots = 96 computations, `data/shade_{summer,monsoon}.npy` float16
  (10662, 48). Run fully SERIAL at ~2.1–3.5 s/slot (~2.5 min/season, ~5 min total) —
  far under the task's 45 min threshold, so no slot parallelism was added.
- **Pre-filter rewrite (correctness first)**: the first draft pre-selected candidate
  edges via a half-day *mean-sun* shadow tree; that tree is not a geometric superset
  of a slot's shadows (mean azimuth ≠ covering azimuth), so it could produce false
  zeros. Replaced with a sound necessity test: each centreline buffered by
  12 m (max sidewalk offset 10.5 m + margin) is tested once against each slot's own
  shadow STRtree (vectorised). An empty box-intersection there implies zero shade
  geometrically; ~40% of edges are skipped at noon, ~25% at low sun.
- **§7.6 sanity gate numbers** (full area, summer): mean slot 04 (08:00) > mean slot 24
  (13:00) < mean slot 44 (18:00) — monotonicity holds; underpass shade == 1.0 (vacuous:
  0 underpasses in Karol Bagh); flood_risk in [0,1]; arrays NaN-free; largest weakly
  connected component >= 95% of nodes. Full table in build_graph stdout / test run.
- **shapely 2.2 ragged payload**: `to_ragged_array` returns a variable-arity third
  element — a 1-tuple (offsets) for pure linework, 2-tuple (type codes, offsets) for
  polygons. `export_arrays.py` persists it slot-by-slot (`types_0..N` + `n_types`) and
  round-trips BOTH npz files through `from_ragged_array` with area/length equality
  asserts. This is the exact Phase 5 Lambda load path; it is verified once here so the
  Lambda contract is proven, not assumed.
- **graph.pkl stays gitignored (upload-only)**; committed data artifacts are the small
  §6.3/§6.4 files (see `.gitignore` allowlist + DEPLOY.md §6). Byte sizes are recorded
  in `data/graph_stats.json` (gitignored, printed in build logs) and in the PR body.
- **upload.py is write-guarded**: refuses to run without GRAPH_BUCKET env + explicit
  `--execute`; default is a dry-run listing. Logged in BLOCKERS.md as
  ready-but-creds-pending.


## Phase 5 — Step Functions re-precompute + CloudWatch dashboard (2026-10-07)

Scope (§10 Phase 5 exactly): extend-only on the frozen Phase 0 template, one state
machine, one stub Lambda, one dashboard. No Bedrock, no DynamoDB, no frontend.

- **Manifest writer is a Lambda stub, not the direct S3 integration**
  (`arn:aws:states:::s3:putObject` with `ResultWriter`/`Parameters.Bucket` style).
  Justification (per the brief's stated preference): the stub is explicit and fully
  testable with botocore Stubs and local fakes, requires no Docker, keeps the manifest
  document shaped by Python (scalar `graph_size_bytes` from `head_object` instead of
  an ASL-composed JSON body), and adds no new integration IAM surface. The ASL stays
  single-service (lambda:invoke only), so `test_task_states_use_lambda_invoke_integration`
  holds for all Task states.
- **Map over seasons, not slots**: `RunShadeSeason` iterates `$.seasons` =
  `["summer", "monsoon"]` (the §6.2 season values), `MaxConcurrency: 2`. The task text's
  "Map over 96 slot items" belongs to the future real compute; the MVP stub is
  season-grained, matching brief (a) "Map state over [summer, monsoon] season params".
- **Lambda stub now, real compute later — same env surface**: `precompute_handler` takes
  the SAME `GRAPH_BUCKET` + `S3_KEY_GRAPH` env names the route Lambda uses, because a
  future real compute swaps in without touching the state machine contract. Handler
  event: `{season, GRAPH_BUCKET, S3_KEY_GRAPH}` (ASL `Parameters.Payload` uses
  `season.$` path composition). Validation order: validate event (§6.2 seasons) ->
  head_object (size > 0) -> §7.6 minimums (non-empty graph reachability keys,
  connectivity >= 0.95) -> manifest `s3://<GRAPH_BUCKET>/manifest/{season}.json`.
  The Fail state `NotifyValidationFailure` is the only terminal; Catch wires on both
  Task states point there.
- **Verified AWS API shapes against live docs before writing** (AWS-SDK signature check
  required by the brief; pages fetched 2026-10-07):
  - Step Functions Map: `ItemProcessor` required; `(Legacy)Iterator` deprecated —
    https://docs.aws.amazon.com/step-functions/latest/dg/state-map.md
  - Optimized Lambda integration `arn:aws:states:::lambda:invoke` with
    `Parameters.FunctionName.$`/`Payload.$` —
    https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html
  - SAM `AWS::Serverless::StateMachine` with `DefinitionSubstitutions` map —
    https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-resource-statemachine.html
  - CloudWatch dashboard body = JSON `widgets` array with per-widget `x/y/width/height`
    + metric-widget `properties.metrics` —
    https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/CloudWatch-Dashboard-Body-Structure.html
  - S3 `head_object` returns `ContentLength` (botocore shape, stubbed in tests).
- **Dashboard** = `Dashboard` (`AWS::CloudWatch::Dashboard`, name `chhaya-mvp`), six
  widgets, region-agnostic (`"region": "${AWS::Region}"` in every metric widget's JSON;
  nothing hardcodes a region). Widgets:
  (1) header Text widget titled "CHHAYA operational notes" (route API + re-precompute
  line, the $5-budget-alert ops note, blockers pointer to docs/BLOCKERS.md — Phase 5
  adds no rows there),
  (2) RouteFunction `AWS/Lambda` Invocations, (3) Duration, (4) Errors — the Phase 3
  metric set preserved (`${RouteFunction}` substituted at deploy),
  (5) `AWS/States` ExecutionsStarted + ExecutionsFailed for `PrecomputeStateMachine`,
  (6) HttpApi 4xx/5xx (`${HttpApi}`). Period 300 s throughout; scope stays 4-6 widgets
  per §7.9.
  ("$5 alert" ROI framing); scope stays 4–6 widgets per §7.9.
- **Offline-MVP note**: the state machine is invoked AFTER push/upload in the current
  offline-MVP shape (handler `head_object`-only), so `ValidateGraph` reads the already
  uploaded bundle; when the real compute Lambda lands, this same ASL's Map item payload
  grows a slot list without any state-name or wire change.
