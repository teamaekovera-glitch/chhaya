"""CHHAYA pipeline configuration — single source of truth for area, time grid, and cost weights.

Data contracts live in CLAUDE.md §6; changing any value here requires updating that file
first (§0 rule 4). Locked at kickoff — see docs/DECISIONS.md.
"""

# ---- Coverage area (locked at kickoff) ----
AREA_NAME = "Karol Bagh"

# (west, south, east, north) in WGS84 lon/lat — osmnx 2.x bbox order (§7.1).
BBOX = (77.178, 28.642, 77.208, 28.657)

# Metric CRS: UTM zone of the bbox centroid (§6.1).
# zone = int((77.193 + 180) // 6) + 1 = 43 -> EPSG:32643.

UTM_EPSG = 32643

# (lon, lat) — map centre for the web app (§7.10).
COVERAGE_CENTROID = (77.193, 28.6495)

# ---- Time grid (§6.2) ----
SLOTS = 48  # slot i starts at 07:00 + 15*i minutes IST (07:00 ... 18:45)
SLOT_START_MINUTES = 7 * 60
SEASON_DATES = {"summer": "2026-05-15", "monsoon": "2026-07-15"}

# ---- Edge cost weights (§8.1 — mirrored in lambdas/route/cost.py, Phase 3) ----
WEIGHTS = {
    "summer": {"a_shade": 2.0, "a_flood": 0.0, "a_under": 0.0},
    "monsoon": {"a_shade": 0.5, "a_flood": 4.0, "a_under": 5.0},
}

# ---- AWS artefact store (§3; region locked at kickoff) ----
# Bucket names are globally unique — adjust in docs/DEPLOY.md if the exact name is taken.
S3_BUCKET = "chhaya-mvp-graph"
AWS_REGION = "ap-south-1"
