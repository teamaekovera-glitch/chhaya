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
