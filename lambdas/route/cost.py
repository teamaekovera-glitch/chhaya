"""CHHAYA edge-cost model — Phase 3 (CLAUDE.md §8.1, exact).

Lambda cannot import pipeline/ (§0 rule 5: the route Lambda ships only numpy +
networkx + shapely), so WEIGHTS is a dict-literal copy of pipeline/config.py.
tests/test_route_api.py::test_weights_pinned_to_config asserts the copy equals
the source of truth — change pipeline/config.py first (§0 rule 4), then here.

Cost semantics (§8.1):
    direct : length_m                                       (mode "direct")
    shade  : length_m * (1 + a_shade * (1 - shade[slot]))   (season-dependent)
    flood  : length_m * (1 + a_flood * flood_risk)          (season-dependent)
             + hard underpass avoidance when season == "monsoon"
             (is_underpass edges are excluded by the Dijkstra weight fn)

The (1 - shade) sign follows §8.1 verbatim: cost is always >= length_m, so a
direct route is the distance lower bound and both aware modes can only pay a
premium. The task brief's "1 + a * shade" is a sign typo — taken literally it
would make walkers prefer sun-exposed streets and violates that invariant.
"""

from __future__ import annotations

import numpy as np

SLOTS = 48
SEASONS = ("summer", "monsoon")
MODES = ("direct", "shade", "flood")

# Pinned copy of pipeline/config.py WEIGHTS (§8.1) — asserted equal by test.
WEIGHTS = {
    "summer": {"a_shade": 2.0, "a_flood": 0.0, "a_under": 0.0},
    "monsoon": {"a_shade": 0.5, "a_flood": 4.0, "a_under": 5.0},
}


def shade_cost_matrix(
    lengths: np.ndarray, shade_rows: np.ndarray, season: str
) -> np.ndarray:
    """(E, 48) float32: length_m * (1 + a_shade[season] * (1 - shade[i, slot])).

    shade_rows: (E, 48) per-edge shade fraction in 0..1 (§6.3 attrs or the
    standalone S3 array — same values by construction, see docs in routing.py).
    """
    a = WEIGHTS[season]["a_shade"]
    shade = np.clip(shade_rows.astype(np.float32), 0.0, 1.0)
    return lengths[:, None] * (1.0 + a * (1.0 - shade))


def flood_cost_matrix(
    lengths: np.ndarray, flood_rows: np.ndarray, season: str
) -> np.ndarray:
    """(E, 48) float32, slot-invariant columns: length_m * (1 + a_flood[season] * flood_risk).

    Flood risk is a single per-edge value (§6.3) — the 48-slot shape exists so a
    per-request Dijkstra indexes one column of the same matrix for every mode.
    In summer a_flood is 0.0, so the matrix degenerates to pure lengths.
    """
    a = WEIGHTS[season]["a_flood"]
    eff = np.clip(flood_rows.astype(np.float32), 0.0, 1.0)
    col = lengths * (1.0 + a * eff)
    return np.repeat(col[:, None], SLOTS, axis=1)
