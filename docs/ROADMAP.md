# CHHAYA — Roadmap (what we cut, and why)

The master prompt's stretch list (S1–S6) was gated on one rule: MVP end-to-end first, then
stretch only if the clock allowed. Phase 6 arrived with the MVP complete (PRs #1–#7, all
gates green) and the live deploy pending credentials — so the stretch items below stay cut.
Each is written so the next person can pick it up with the decision context intact, not as a
wish list.

## S1 — Crowd reports ("this street is waterlogged now") · **cut, closest to done**

*What:* a "report waterlogging here" FAB on the map → one DynamoDB table
(`ChhayaReports`, on-demand, TTL 6 h) → report count boosts `flood_risk` on nearby edges at
route time (`report_boost = 0.3·count`, capped 1.0) and pins render on the map. Report
Lambda = boto3-only per the §0 rule-5 budget.

*Needs:* the DynamoDB table + `report` Lambda wired into `infra/template.yaml`, one extra
IAM statement, and a Query pass in the route handler before pathfinding (the report-boost
cost hook exists in the master prompt §7.7 stretch spec verbatim — the handler change is
additive, not a rewrite).

*Why cut:* the MVP story demoed cleanly without live reports, and every new runtime surface
under the credential-pending state multiplies what stays unverified. Residents *correcting
the 30 m DEM's relative risk* is the single most valuable follow-up — it attacks CHHAYA's
most-stated data limitation directly — which is exactly why it is first in line, not
forgotten.

## S3 — Bedrock route advice (English + Hindi, one line) · **cut deliberately**

*What:* POST `/advice` takes the route response minus geometries and returns ≤ 40-word
trade-off sentences in `{en, hi}` from a Bedrock Converse call at temperature 0.2, falling
back to the template summaries (`"model": "fallback"`) on any error.

*Needs:* `list-foundation-models --by-inference-type ON_DEMAND` to name a real on-demand
model at deploy time — Bedrock on-demand availability in `ap-south-1` is a **runtime-
discovery fact, never hardcoded** (tracked in `docs/DECISIONS.md` since kickoff) — plus a
one-statement IAM grant, and either an in-region model or `BEDROCK_REGION=us-east-1` for
this Lambda alone (cross-Region inference profiles are off the Free plan).

*Why cut:* the advice line adds demo polish, not walking value — the comparison card already
states the trade in numbers, and `summary_en`/`summary_hi` exist as template strings today.
Under a hard 4-day clock we chose one less region-availability risk and one less fallback
path to test. If reviving: keep the fallback contract exactly as written; it is what makes
the feature safe to bolt on.

## S4 — Time slider animating the Chhaya route across the day · **cut, partial byproduct shipped**

*What:* the departure strip becomes a scrubber: as it sweeps 07:00→18:45, the CHHAYA line
re-queries and re-draws, so the shadow's retreat across a street is visible as motion.

*Needs:* a 48-step debounce over the existing slot-strip control and one re-render gate.
Almost everything else — the strip UI, the slot-index contract, the per-slot arrays — already
exists (`web/src/components/TimeStrip.tsx`, 48-slot profile in the route response).

*Why cut:* the tc-3 recording already shows the route adapting when the slot changes; the
animation adds the same information at higher render cost and a re-recording burden the
video deadline couldn't absorb. Best value of the four backlogs if a second demo day appears.

## S5 — Trees as partial shade sources · **cut at Phase 1**

*What:* `natural=tree` points become shade circles (r = 4 m, h = 7 m, opacity 0.7) unioned
into the slot shadow geometry, softening edge shade on unblanketed streets.

*Needs:* nothing new in the boilerplate — `pipeline/fetch_osm.py` already extracts trees;
the Karol Bagh extract found **36 trees** — plus one union-add and the 0.7 opacity rule in
the shadow pass.

*Why cut:* 36 trees in ~2 km² is noise: it would change per-edge shade fractions by fractions
of a percent while doubling the shadow-union cost at every one of 96 slot computations, and a
`trees.gpkg`-driven rerun re-tests every gate. Connaught Place or Lutyens' green fabric would
be the honest first target — and that reinforces the second-neighbourhood choice below.

## S6 — Second neighbourhood via Step Functions Distributed Map · **cut by design, and its absence proves the thesis**

*What:* tile the coverage decision (BBOX + name) and fan a Distributed Map over
neighbourhoods so the pipeline scales past Karol Bagh without code changes.

*Needs:* the state machine (deployed in PR #6) extended with a Distributed Map child, and
`pipeline/config.py` promoted from constants to a parameter file. Real compute (not the
season-grained stub) must land in the shade-slot path first — the Phase 5 stub keeps the
wire contract but doesn't yet do the full per-slot computation.

*Why cut:* a second neighbourhood duplicates the demo's risk profile while proving nothing
the first one hasn't. Distributed Map also sits outside the always-free tier at any useful
fan-out, which makes it a correctness/plan-policy risk for zero demo gain. The moment one
neighbourhood's deploy is verified end-to-end, this is the natural next served area.

---

**Sequencing statement (the honest one):** if the deploy clock had run spare after Phase 5
verification, the order would have been S1 → S3 → S4 → S5/S6, exactly the master prompt's
order — crowd reports first because they correct the product's biggest stated limitation
with the smallest new surface.
