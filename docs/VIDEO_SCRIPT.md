# CHHAYA — demo video script (2:45 target)

WeMakeDevs × AWS Environmental Hacks · Heat and Water track. Judging shows a video, not a
live demo — everything below is shot, not claimed. Total runtime target **2:45**, hard cap
3:00. Screen-recording viewport: 1180 × 820 (the app is judged at phone width too — one
cutaway at 0:55 shows the 480px card). Voiceover is plain English; Hindi titles only where
marked. Recorded from the running app with `?mock=1` until credentials land (per
`docs/BLOCKERS.md`); the script stays valid either way because every number spoken maps to a
committed artefact or a QA verdict.

**Cue convention:** [VO] voiceover · [SHOT] what is on screen · [CUT hard] a hard edit point ·
[B-ROLL] supporting plot/console footage · [STORYBOARD] the PR #7 QA capture whose recorded
verdict backs this shot exists.

---

## 0:00 — The problem (0:00–0:25)

[SHOT] Full-bleed photo sequence: a Karol Bagh arterial road at 1 PM, sun beating on exposed
asphalt; cut to the same class of street ankle-deep in monsoon water. Two text cards, three
words each: `MAY: 45°C ASPHALT.` / `JULY: THE UNDERPASS IS A LAKE.`

[VO] "Walking two kilometres in Karol Bagh in May is a decision your body pays for. The same
streets flood every July. Your map app optimises distance. It has no idea what time it is,
and no idea where the water is."

[CUT hard at 0:25]

## 0:25 — Summer demo (0:25–1:15)

[STORYBOARD tc-1] App boots: Karol Bagh centred, coverage outline drawn, pickers filled with
real places, three route lines on the map.

[VO] "This is CHHAYA. Pick where you're walking from, where to, and — this is the part that
matters — when."

[SHOT] Origin "Karol Bagh Metro Station", destination a market block ~1.2 km away. Departure
strip set to **1:30 PM**. Mode: **Chhaya ☀ Summer**. Press Find route.

[SHOT] The DIRECT line draws (grey), then the CHHAYA line (green) takes a visibly different
path — denser lanes, hugged by built blocks. The comparison card states the trade.

[VO] "Two routes. Direct: fastest. Chhaya: minutes longer, but look at the card — more of
your walk is in building shadow at exactly this hour. Not a generic 'shady route'. Shadow
computed for 1:30 PM on May the fifteenth, per street, from the actual buildings."

[B-ROLL] Cut in `pipeline/plots/shadows_summer_00.png` (8 AM, long shadows west) for two
seconds, then `shadows_summer_44.png` (6 PM, east) — dawn/plot/dusk contrast in twelve frames.
The 8:00 AM screenshot cutaway belongs here (STORYBOARD tc-1 before/after pair): same two
places, morning slot, the answer reorders with the sun.

[STORYBOARD tc-3] Quick 3-second beat: slide the departure strip left to 8:00 AM; the
comparison chips and the shade sparkline behind the strip update live.

[VO] "Slide the time of day and the route changes with the sun. Forty-eight slots a day, two
seasons, precomputed — so it answers in under a second."

[CUT hard at 1:15]

## 1:15 — Monsoon demo (1:15–2:00)

[SHOT] Toggle to **Chhaya 🌧 Monsoon** (STORYBOARD tc-2: same geometry, monsoon styling warm
blue, flood chips replace shade chips — recording backed by the tc-2 verdict).

[VO] "Now July. Same two buildings, different question: not 'where is the shade', but 'where
does the water go when it rains'."

[SHOT] The CHHAYA line re-plans, bending away from the low ground between the two points.
Flood chips on the card read plainly.

[VO] "Under the neighbourhood is a mapping entry every routing engine ignores: elevation. We
read the Copernicus 30-metre DEM, compute how far above the nearest drainage every street
sits, and rank the whole area. The direct route crosses streets we score riskiest. The Chhaya
route goes around."

[B-ROLL] `pipeline/plots/flood_map.png` full-screen for four seconds — colour-coded flood risk
over the street network, with the DEM source named on the frame.

[VO (over plot)] "Honest footnote, said out loud: thirty-metre terrain data gives relative
risk, not kerb-exact truth. So CHHAYA keeps the numbers conservative and — one tap lets a
resident report what they're standing in." *(stretch item; if it didn't ship, cut this line —
see ROADMAP.)*

[CUT hard at 2:00]

## 2:00 — What's under it, all on AWS (2:00–2:35)

[SHOT] Architecture card (the README diagram, one static frame, 4 seconds), then a quick
console tour: SAM stack in CloudFormation; one `POST /route` in the Lambda logs with
`RouteLatencyMs` EMF line; the Step Functions re-precompute execution green; the CloudWatch
`chhaya` dashboard — route latency, errors, executions.

[VO] "The whole thing is one SAM stack. The route answer comes from a Lambda that loads a
precomputed shadow-and-flood graph from S3 — no database, no containers, nothing warm. Map
tiles, place search, and the grey baseline route — the line every other map would give you —
come from Amazon Location Service, key-locked to this one domain. Every service here is on
the free tier, guarded by a five-dollar budget alert that existed before anything deployed."

[CUT hard at 2:35]

## 2:35 — Impact + what's next (2:35–2:45)

[SHOT] Back to the app, phone-frame inset. Text: `CHHAYA (छाया) — shade for summer, dry feet for monsoon.`

[VO] "It knows the sun's position to half a degree. It knows where the water goes. What it
doesn't know yet is *your* street tomorrow morning — that's second neighbourhoods, crowd
reports, and advice in Hindi. Walk smart."

[END CARD] Repo URL · team credit · "Built with OpenStreetMap, Copernicus DEM, AWS" ·
Heat and Water track badge.

---

## Shot list (recorder's checklist)

| # | Duration | Screen / asset | Storyboard evidence of the interaction |
| --- | --- | --- | --- |
| 1 | 0:00–0:25 | street photography (local footage, two stills + text cards) | — |
| 2 | 0:25–0:35 | app boot, coverage outline, pickers filled | PR #7 tc-1 (boot, before) |
| 3 | 0:35–0:55 | 1:30 PM summer: direct + chhaya lines + comparison card | PR #7 tc-1 (boot, after) |
| 4 | 0:55–1:05 | strip slide to 8:00 AM, chips/sparkline update | PR #7 tc-3 (recording) |
| 5 | 1:05–1:15 | B-roll: shadows_summer_00 → _44 with sun arrows | — (pipeline plots) |
| 6 | 1:15–1:25 | monsoon toggle, line recolor + re-plan | PR #7 tc-2 (recording) |
| 7 | 1:25–1:40 | monsoon route divergence, flood chips | PR #7 tc-2 (before/after) |
| 8 | 1:40–1:52 | B-roll: flood_map.png with DEM source caption | — (pipeline plot) |
| 9 | 2:00–2:04 | architecture slide (README diagram frame) | — |
| 10 | 2:04–2:20 | Lambda log POST /route + EMF metric line | — (console, post-credentials) |
| 11 | 2:20–2:27 | Step Functions execution green | — (console) |
| 12 | 2:27–2:35 | CloudWatch dashboard | — (console) |
| 13 | 2:35–2:45 | phone-frame app + end card | — |

**If credentials never land** (β fallback, per `docs/BLOCKERS.md`): shot 10–12 substitute the
CloudFormation template in the editor + one `?mock=1` recording labelled "API mocked for
recording — live deploy step pending" on-screen. It is on the record in the submission
write-up, not hidden; judging weights execution, and every other minute shows real
built-and-tested code.
