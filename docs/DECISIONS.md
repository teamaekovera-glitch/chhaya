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
