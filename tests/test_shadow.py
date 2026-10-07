"""CLAUDE.md §9 shadow-direction gates — exact closed-form sweep cases.

Standalone: no network, no OSM data, no AWS credentials — pure shapely +
shared.shadow. The §9 case: a 10 m square building at 45° sun altitude casts a
10 m shadow; azimuth 180° (sun due south) sweeps it due north, azimuth 90°
(sun due east) sweeps it due west; polygon area equals footprint area + one
10 m sweep strip. ``alt < 5°`` returns the §7.5 full-shade sentinel (None).
"""

from __future__ import annotations

import pytest
from shapely.geometry import MultiPolygon, Polygon

from shared.shadow import (
    ALT_FLOOR_DEG,
    MAX_SHADOW_LENGTH_M,
    shadow_sweep_polygon,
)

# 10 m square footprint at the UTM origin (§9 geometry).
SQUARE = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
FOOTPRINT_AREA = 100.0

# Simplify tolerance (§7.5) bounds how far vertices may move.
GEOM_TOL = 0.5


def _sweep(alt, az, **kwargs):
    return shadow_sweep_polygon(SQUARE, alt, az, **kwargs)


def test_sun_due_south_sweeps_shadow_due_north():
    poly = _sweep(45.0, 180.0, max_length=10.0)
    assert poly is not None
    minx, miny, maxx, maxy = poly.bounds
    # Sun due south -> shadow due north: the union spans y in [0, 20].
    assert maxy == pytest.approx(20.0, abs=GEOM_TOL)
    assert miny == pytest.approx(0.0, abs=GEOM_TOL)
    # No lateral drift for a due-north sweep.
    assert minx == pytest.approx(0.0, abs=GEOM_TOL)
    assert maxx == pytest.approx(10.0, abs=GEOM_TOL)


def test_sun_due_east_sweeps_shadow_due_west():
    poly = _sweep(45.0, 90.0, max_length=10.0)
    assert poly is not None
    minx, miny, maxx, maxy = poly.bounds
    # Sun due east -> shadow due west: the union spans x in [-10, 10].
    assert minx == pytest.approx(-10.0, abs=GEOM_TOL)
    assert maxx == pytest.approx(10.0, abs=GEOM_TOL)
    assert miny == pytest.approx(0.0, abs=GEOM_TOL)
    assert maxy == pytest.approx(10.0, abs=GEOM_TOL)


def test_sun_due_north_sweeps_shadow_due_south():
    """Delhi never sees the sun due north, but the convention must hold."""
    poly = _sweep(45.0, 0.0, max_length=10.0)
    assert poly is not None
    _, miny, _, maxy = poly.bounds
    assert miny == pytest.approx(-10.0, abs=GEOM_TOL)
    assert maxy == pytest.approx(10.0, abs=GEOM_TOL)


def test_morning_sun_southeast_sweeps_shadow_northwest():
    """§7.5 diagonal case: sun az 135° -> shadow (dx, dy) = (-5, +5) m for
    L = 7.071 m (dx = L·sin(315°) = -L/√2, dy = +L/√2) — north-west drift."""
    poly = _sweep(45.0, 135.0, max_length=7.0710678)
    minx, miny, maxx, maxy = poly.bounds
    assert minx == pytest.approx(-5.0, abs=GEOM_TOL)  # west drift
    assert miny == pytest.approx(0.0, abs=GEOM_TOL)
    assert maxy == pytest.approx(15.0, abs=GEOM_TOL)  # north drift
    assert maxx == pytest.approx(10.0, abs=GEOM_TOL)


@pytest.mark.parametrize("alt,az", [(45.0, 180.0), (45.0, 90.0)])
def test_area_equals_footprint_plus_sweep_strip(alt, az):
    """§9: area ~= footprint area + one 10 m sweep strip (100 + 10*10 = 200)."""
    poly = _sweep(alt, az, max_length=10.0)
    assert poly.area == pytest.approx(FOOTPRINT_AREA + 10.0 * 10.0, rel=0.02)


def test_low_sun_altitude_returns_none_sentinel():
    """§7.5: alt < 5 deg -> None; the caller sets shade = 1.0 for the slot."""
    assert _sweep(ALT_FLOOR_DEG - 0.1, 180.0) is None
    assert _sweep(0.0, 180.0) is None
    assert _sweep(-10.0, 180.0) is None
    # Exactly at the floor the sweep still runs (floor is exclusive).
    assert _sweep(ALT_FLOOR_DEG, 180.0) is not None


def test_height_path_applies_the_7_5_formula_and_250_m_cap():
    """h/tan path: 10 m height at 45 deg sweeps 10 m; a 100 m height at 5.1 deg
    hits the 250 m cap (§7.5 L = min(h/tan(alt), 250 m)) — uncapped would be
    ~1120 m."""
    capped = _sweep(45.0, 180.0, height_m=10.0)
    assert capped.area == pytest.approx(200.0, rel=0.02)

    poly = _sweep(5.1, 180.0, height_m=100.0)
    _, miny, _, maxy = poly.bounds
    assert (maxy - miny) <= MAX_SHADOW_LENGTH_M + 10.0 + GEOM_TOL
    # At the cap the sweep's far edge is footprint top (y=10) + 250 m, not
    # the uncapped ~1120 m.
    assert maxy == pytest.approx(10.0 + MAX_SHADOW_LENGTH_M, abs=GEOM_TOL + 1.0)
    assert maxy < 500.0


def test_overhead_sun_sweeps_nothing():
    """Sun at 90 deg: no cast shadow even with height supplied."""
    poly = _sweep(90.0, 180.0, height_m=10.0)
    assert poly is not None
    assert poly.area == pytest.approx(FOOTPRINT_AREA, rel=0.02)


def test_empty_footprint_returns_none():
    assert shadow_sweep_polygon(Polygon(), 45.0, 180.0) is None


def test_multipolygon_footprint_is_swept_whole():
    two = MultiPolygon(
        [
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
            Polygon([(100, 0), (120, 0), (120, 10), (100, 10)]),
        ]
    )
    poly = shadow_sweep_polygon(two, 45.0, 180.0, max_length=10.0)
    assert poly is not None
    # Both footprints (200 m²) plus two 10 m sweep strips (400 m²) = 600 m².
    assert poly.area == pytest.approx(600.0, rel=0.02)
    _, _, maxx, _ = poly.bounds
    assert maxx == pytest.approx(120.0, abs=GEOM_TOL)
