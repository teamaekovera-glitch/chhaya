# CHHAYA — Submission (Heat and Water track)

**Team Aekovera · WeMakeDevs × AWS Environmental Hacks (Bharat Builds Tour event 02) · Oct 8–11 2026**

## The pitch

In Indian summers, walking one kilometre at the wrong hour is a health decision made for you
by a rickshaw driver's instinct. Karol Bagh, Delhi hits exposed-asphalt heat through the
afternoon, and every monsoon the same low streets flood ankle-deep. Map apps optimise
distance. **CHHAYA answers a different question: given *when* you're walking, what does the
street feel like?** It shows the direct route against a cost-optimised one that is measurably
more shaded in the afternoon sun or measurably drier in July monsoon — both on one map, with
the trade-off in minutes stated plainly, and a standard-map pedestrian route drawn beside
them both as the honest baseline. Coverage is a real Delhi neighbourhood (Karol Bagh, ~4,663
buildings / ~10.7k walk edges), not a synthetic toy grid.

## The environmental pipeline, in four plain paragraphs

**1. The urban fabric.** CHHAYA starts from the OpenStreetMap walking graph of the
neighbourhood: every footway, lane, and residential street becomes an edge in a directed
graph, and every mapped building becomes a shadow-casting solid. A height ladder fills
building heights where OSM has none — direct `height=` tags first, then
`building:levels × 3.2 m + 1`, then a type-based default (apartments 18 m, commercial 12 m,
residential 9 m, fallback 8 m). For Karol Bagh that ladder is dead honest about itself: 0%
of buildings carry a measured height tag, 2.6% get a level-derived value, and 96.8% ride on
the type default — a gap the writeup states up front, not hides.

**2. Where the sun actually is.** A pure-numpy implementation of the NOAA solar-position
algorithm computes the sun's altitude and azimuth for all 48 fifteen-minute slots between
07:00 and 18:45 IST, for two representative dates: mid-May (summer heat) and mid-July
(monsoon). This is not an approximation the team trusts on faith: `tests/test_solar.py`
validates it against the independent `pvlib` reference to under 0.5° error in both altitude
and azimuth, for every slot of both dates. The same math runs in the pipeline and (as a
vendored copy) ships in the shade Lambda — one solar canon, no drift.

**3. Shadows, turned into a per-street number.** For each slot, every building footprint is
swept along the anti-solar azimuth by its shadow length (height ÷ tan(sun altitude), capped at
250 m) to make a shadow polygon; the union of all polygons is then intersected with both
sidewalk offset lines of every street, and the street's shade fraction is the better of the
two sides — because a walker picks the shady side. The result is a float16 array of
`shade[edge, slot]` per season: 10,662 edges × 48 slots, precomputed and stored, so the
routing engine never waits on geometry at request time. Direction bugs are the classic
silent killer in this code (degrees vs radians, azimuth-from-north vs from-south), so the
pipeline renders slot plots (morning shadows point west, evening east, noon short and
north) and a human signs off before the arrays are accepted — a gate, not a screenshot.

**4. Water, from terrain.** Flood risk comes from the Copernicus GLO-30 digital elevation
model, read unauthenticated straight from its public S3 bucket and clipped to the area plus
a 2 km margin. From the DEM, pysheds derives HAND (height-above-nearest-drainage) and TWI
(topographic wetness index); both are rank-normalised across the neighbourhood and blended
50/50 into a per-edge `flood_risk` in 0–1, with OSM tunnel/underpass and bridge flags layered
on top (underpasses flagged for avoidance, bridges zeroed — they drain). A 30 m DEM cannot
say which *kerb* floods first, and CHHAYA says so: it produces **relative, not street-exact**
risk, and the design reserves room (stretch scope) for resident "this is waterlogged now"
reports to correct it over time.

Routing then costs each edge as
`length × (1 + a_shade·(1−shade) + a_flood·flood_risk + a_under·is_underpass)` with mode
weights set so the choice is meaningful but bounded: summer `a_shade = 2.0`, monsoon
`a_flood = 4.0` / `a_under = 5.0`. Cost can never drop below plain distance, so DIRECT is
always the true shortest path — the CHHAYA route buys comfort with minutes and the
comparison card shows exactly how many.

## Design decisions worth calling out

| Decision | What we chose | Why |
| --- | --- | --- |
| Coverage area | Karol Bagh, over Connaught Place | Denser mid-rise fabric makes the shade contrast *visible* on the map: in an open plaza the optimized and direct routes converge to the same line and the demo dies. In Karol Bagh's shallow blocks and verandas the two lines genuinely diverge. |
| Baseline route | Amazon Location Routes `CalculateRoutes`, called **from the browser** with the referer-restricted API key | Keeps the route Lambda's IAM surface down to a single S3-get; the baseline is a comparison line the video draws once, not a feature whose availability should ride on Lambda latency. |
| Place search | Places v2 `SearchText` in **one** call, `Filter.BoundingBox` locked to the coverage area | `Autocomplete` returns no coordinates; a two-call `Autocomplete`→`GetPlace` chain buys latency for nothing when `SearchText` returns positions directly and stays inside the Karol Bagh bbox. |
| Location API key actions | Adds `geo-maps:GetStyleDescriptor` beyond the obvious tile/places/routes actions | MapLibre fetches the *style descriptor* to initialise a Maps v2 style — without that action the map renders blank behind a "working" tile cache. Found in the CFN reference for `AWS::Location::APIKey` restrictions before it cost us a deploy cycle. |
| Bedrock advice | Deferred out of the MVP (stretch) | The advice line adds demo polish, not walking value; the per-(mode, slot) template summaries already speak the trade-off. Keeping it out means one less region-availability risk (Bedrock on-demand model IDs in `ap-south-1` are runtime-verified, not assumed) and one less fallback path to test under the clock. |
| Solar math | One accurate-NOAA implementation, validated against pvlib, vendored into Lambda | Truncated fractional-year series drifts near zenith; the accurate form clears the 0.5° gate. One canon means the pipeline and the Lambda cannot disagree. |
| Honesty as a contract | 30 m DEM = relative risk; heights are 96.8% type-default; 0 underpasses mapped in this extract (so the `a_under` penalty is live code with no Karol Bagh targets yet) | Judging values execution over theatre. Every claim in the README maps to a file, a test, or a plot; every gap is stated where the claim would otherwise sit. |

## Demo outline (the 2.5–3-minute video; full script in [`docs/VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md))

1. **Problem, 0:00** — a real street photo composite: exposed midday Karol Bagh road, a
   flooded one in July. Distance-optimised maps do not know what these two things are. (15 s)
2. **Summer demo, 0:25** — pick Karol Bagh places, set 1:30 PM, Summer mode: DIRECT line
   appears, CHHAYA line diverges into shade, comparison card states the trade (extra minutes
   for shade %). Slide the departure to 8:00 AM: the same two places reorder the world —
   shade follows the sun, not the destination. (50 s)
3. **Monsoon demo, 1:15** — toggle Monsoon: the route re-plans around high-`flood_risk`
   streets. Show the flood-risk plot (GLO-30/HAND/TWI) as the "we can see the terrain" proof.
   (45 s)
4. **Architecture + AWS, 2:00** — SAM stack diagram; Lambda logs with route latency, Step
   Functions execution, the CloudWatch dashboard; where each service sits and what it costs
   (mostly nothing, on the free plan). (35 s)
5. **Impact + what's next, 2:40** — second neighbourhoods, crowd reports, advice;
   restate the honest status (live once credentials land). Close. (20 s)

## Honest status

| Surface | State |
| --- | --- |
| Codebase (pipeline → routing → UI → infra, PRs #1–#7) | merged on `main`; 96 pytest passing (2 skipped) + 21 vitest green per PR |
| Data artefacts (shade × 48 slots × 2 seasons, flood, graph, coverage) | committed in-repo and quality-gated (plots reviewed; sanity gate in `build_graph.py`) |
| Live AWS deploy (API GW + Lambda, S3 bundle, Location key, Amplify URL) | ⏳ blocked only on credentials — staged commands in [`docs/DEPLOY.md`](DEPLOY.md), tracked rows in [`docs/BLOCKERS.md`](BLOCKERS.md) |
| Video (≤ 3 min, no live demo) | script + storyboard cue points ready in [`docs/VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md); on-camera recording is a human action |

**Where AWS fits:** Amazon Location Service (tiles, search, baseline routes) · Lambda +
API Gateway HTTP API (routing) · S3 (artefacts) · Step Functions (repeatable re-precompute) ·
SAM/CloudFormation (single deployable stack) · CloudWatch (visibility) · Amplify Hosting
(frontend). No relational database, no containers, nothing outside `ap-south-1` (Bedrock, if
added later, is the only candidate and is runtime-verified first per `DECISIONS.md`).

**AI tools used:** Obvious (agent, build + review + QA) and Claude (pre-kickoff contract
authoring) — full table in [`docs/AI_TOOLS.md`](AI_TOOLS.md).

**Data credits:** © OpenStreetMap contributors (network + buildings); Copernicus GLO-30 DEM
via its public S3 distribution; Amazon Location Service (tiles/search/routes); pvlib as the
independent solar-position reference (test-only dependency).
