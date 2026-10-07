"""Shadow-polygon sweep geometry — CLAUDE.md §7.5, shared pipeline/Lambda surface.

Import surface frozen for pipeline/shade.py and lambdas/shade_slot (§7.5: same
code, vendored; only numpy + shapely may be imported here):

    from shared.shadow import shadow_sweep_polygon

    poly = shadow_sweep_polygon(footprint_utm, sun_altitude_deg, sun_azimuth_deg)

- ``footprint_utm``: shapely Polygon (or MultiPolygon) in UTM metres (x east,
  y north). Ring orientation is irrelevant — the sweep is orientation-agnostic.
- ``sun_altitude_deg`` / ``sun_azimuth_deg``: degrees; azimuth clockwise from
  true north (§7.5 convention).
- Shadow direction is ``azimuth + 180°`` (away from the sun); displacement in
  UTM metres is ``dx = L*sin(θ)``, ``dy = L*cos(θ)``.
- Sweep length ``L``: when the caller passes ``height_m``, the §7.5 formula
  ``L = min(h / tan(alt), max_length)`` applies (production pipeline path, which
  owns the real §7.2 heights); without it, ``L = max_length`` — callers that
  already computed ``h / tan(alt)`` upstream pass that result as ``max_length``
  (the §9 tests do exactly this, with ``max_length=10.0``).
- Returns the swept shadow polygon (footprint ∪ translated footprint ∪ the
  connecting quad for every exterior edge), simplified with ``tolerance=0.5``.
- Returns ``None`` for ``sun_altitude_deg < ALT_FLOOR_DEG`` (5°) — the §7.5
  full-shade sentinel species: callers set shade = 1.0 for the slot and skip.
- ``shade_fraction`` and the sidewalk-offset helper live in shared/geometry.py.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

__all__ = ["ALT_FLOOR_DEG", "MAX_SHADOW_LENGTH_M", "shadow_sweep_polygon"]

ALT_FLOOR_DEG = 5.0
MAX_SHADOW_LENGTH_M = 250.0


def _shadow_length(
    sun_altitude_deg: float, max_length: float, height_m: float | None
) -> float:
    """Sweep length L in metres (§7.5: L = min(h / tan(alt), cap)).

    ``max_length`` is the §7.5 cap (default 250 m). Without ``height_m``, the
    caller has already computed L upstream (the §9 tests pass ``h / tan(alt)``
    this way) and ``max_length`` rides in as that length.
    """
    if height_m is None:
        return float(min(max(max_length, 0.0), MAX_SHADOW_LENGTH_M))
    if height_m <= 0.0 or sun_altitude_deg >= 90.0:
        return 0.0
    length = height_m / np.tan(np.radians(sun_altitude_deg))
    return float(min(max(length, 0.0), max_length))


def _exterior_edges(geom: BaseGeometry):
    """Yield each exterior-ring edge of a (Multi)Polygon as coordinate pairs."""
    geoms = geom.geoms if hasattr(geom, "geoms") else [geom]
    for g in geoms:
        coords = list(g.exterior.coords)
        # Adjacent-pair sweep; shapely rings repeat the first coord at the end.
        yield from pairwise(coords)


def shadow_sweep_polygon(
    footprint_utm: BaseGeometry,
    sun_altitude_deg: float,
    sun_azimuth_deg: float,
    max_length: float = MAX_SHADOW_LENGTH_M,
    height_m: float | None = None,
):
    """Return the swept shadow polygon for one building footprint, or None.

    ``sun_altitude_deg < ALT_FLOOR_DEG`` -> None (§7.5 full-shade sentinel).
    """
    if sun_altitude_deg < ALT_FLOOR_DEG:
        return None
    if footprint_utm.is_empty:
        return None

    theta = np.radians((sun_azimuth_deg + 180.0) % 360.0)
    length = _shadow_length(sun_altitude_deg, max_length, height_m)
    dx = length * float(np.sin(theta))
    dy = length * float(np.cos(theta))

    geom = footprint_utm.buffer(0)  # normalise self-intersections
    if dx == 0.0 and dy == 0.0:
        return geom

    translated = shapely.transform(
        geom, lambda coords: coords + np.array([dx, dy]), include_z=False
    )

    # Connecting quad for every exterior edge e_i: e_i -> e_i + (dx, dy).
    pieces = [geom, translated]
    pieces += [
        Polygon([a, b, (b[0] + dx, b[1] + dy), (a[0] + dx, a[1] + dy)]).buffer(0)
        for a, b in _exterior_edges(geom)
    ]

    return unary_union(pieces).simplify(tolerance=0.5)
