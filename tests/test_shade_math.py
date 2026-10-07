"""CLAUDE.md §8/§9 shade-math gates on synthetic geometry (no OSM, no AWS).

Covers the shared/geometry.py helpers the Phase 2 shade pipeline builds on:
- sidewalk offsets ±(width/2 − 1.5) on a straight LineString produce two
  parallel lines;
- shade_fraction computes union-of-intersections correctly on hand-drawn
  two-shadow toy geometry;
- max(left, right) picks the shadier side ("a walker picks the shady side",
  §7.5).
"""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from shared.geometry import (
    SIDEWALK_CLEARANCE_M,
    shade_fraction,
    sidewalk_offset_lines,
)

# Straight 100 m centreline along +x at y=0 (UTM metres).
CENTRELINE = LineString([(0.0, 0.0), (100.0, 0.0)])


def _parallel_at_offset(line: LineString, ref: LineString, distance: float) -> bool:
    """True when `line` is straight, parallel to ref, and exactly `distance` away."""
    if line.geom_type != "LineString" or len(line.coords) != len(ref.coords):
        return False
    for (x1, y1), (x2, y2) in zip(line.coords, ref.coords):
        if (x1 - x2) ** 2 > 1e-9:  # an offset of a straight E-W line shifts y only
            return False
    return bool(line.distance(ref) == pytest.approx(distance, abs=1e-6))


class TestSidewalkOffsets:
    """§7.5: two candidate sidewalk lines at ±(width/2 − 1.5)."""

    def test_residential_8m_yields_parallel_lines_at_2_5m(self):
        right, left = sidewalk_offset_lines(CENTRELINE, width_m=8.0)
        expected = 8.0 / 2.0 - SIDEWALK_CLEARANCE_M  # 2.5 m
        assert right != left
        assert _parallel_at_offset(right, CENTRELINE, expected)
        assert _parallel_at_offset(left, CENTRELINE, expected)
        assert right.length == pytest.approx(100.0)
        assert left.length == pytest.approx(100.0)

    def test_wide_arterial_24m_yields_10_5m_offsets(self):
        right, left = sidewalk_offset_lines(CENTRELINE, width_m=24.0)
        expected = 24.0 / 2.0 - SIDEWALK_CLEARANCE_M  # 10.5 m
        assert _parallel_at_offset(right, CENTRELINE, expected)
        assert _parallel_at_offset(left, CENTRELINE, expected)

    def test_narrow_3m_footway_falls_back_to_centreline(self):
        """width 3 m -> clearance 0.0 m -> both candidates are the centreline."""
        right, left = sidewalk_offset_lines(CENTRELINE, width_m=3.0)
        assert right == CENTRELINE
        assert left == CENTRELINE

    def test_offsets_are_mirror_images_about_the_centreline(self):
        right, left = sidewalk_offset_lines(CENTRELINE, width_m=12.0)
        shift = 2.0 * (12.0 / 2.0 - SIDEWALK_CLEARANCE_M)
        moved = LineString([(x, y + shift) for x, y in right.coords])
        assert left.equals(moved) or left.symmetric_difference(moved).length < 1e-6


class TestShadeFraction:
    """§7.5: fraction of the sidewalk inside the union of candidate shadows."""

    def test_union_of_two_partial_shadows_hand_drawn(self):
        # Sidewalk from (0,0) to (100,0); two 30 m shadow bands cover
        # [10,40] and [60,90], with a 20 m gap between them.
        band_a = Polygon([(10, -5), (40, -5), (40, 5), (10, 5)])
        band_b = Polygon([(60, -5), (90, -5), (90, 5), (60, 5)])
        shadow_union = unary_union([band_a, band_b])
        frac = shade_fraction(CENTRELINE, shadow_union)
        assert frac == pytest.approx(60.0 / 100.0)  # 30 + 30 shaded metres

    def test_overlapping_bands_do_not_double_count(self):
        band_a = Polygon([(0, -5), (50, -5), (50, 5), (0, 5)])
        band_b = Polygon([(30, -5), (80, -5), (80, 5), (30, 5)])
        shadow_union = unary_union([band_a, band_b])
        # Union covers [0, 80] = 80 m, though the raw bands sum to 100 m.
        frac = shade_fraction(CENTRELINE, shadow_union)
        assert frac == pytest.approx(0.80)

    def test_no_shadow_union_gives_zero(self):
        far_band = Polygon([(500, -5), (600, -5), (600, 5), (500, 5)])
        assert shade_fraction(CENTRELINE, far_band) == 0.0

    def test_null_and_degenerate_inputs_give_zero(self):
        band = Polygon([(0, -5), (10, -5), (10, 5), (0, 5)])
        assert shade_fraction(None, band) == 0.0
        assert shade_fraction(CENTRELINE, None) == 0.0
        degenerate = LineString([(0.0, 0.0), (0.0, 0.0)])
        assert shade_fraction(degenerate, band) == 0.0

    def test_fully_covered_sidewalk_gives_one(self):
        band = Polygon([(-10, -5), (110, -5), (110, 5), (-10, 5)])
        assert shade_fraction(CENTRELINE, band) == pytest.approx(1.0)


class TestShadierSide:
    """§7.5: edge shade = max(left, right) — a walker picks the shady side."""

    def test_max_picks_the_shadier_of_two_offsets(self):
        # 8 m street: sidewalks at y = ±2.5 m. Full-length envelope bands for
        # each side (each covers its own sidewalk's entire 100 m length).
        right, left = sidewalk_offset_lines(CENTRELINE, width_m=8.0)
        right_band = Polygon([(-10.0, -10.0), (110.0, -10.0), (110.0, -2.2), (-10.0, -2.2)])
        left_band = Polygon([(-10.0, 2.2), (110.0, 2.2), (110.0, 10.0), (-10.0, 10.0)])
        assert shade_fraction(right, right_band) == pytest.approx(1.0)
        assert shade_fraction(left, left_band) == pytest.approx(1.0)

        # A band grazing only the right side (y in [-4, -1] covers y=-2.5 but
        # not the left sidewalk at y=+2.5) over x in [0, 50]: 50% vs 0%.
        grazes_right = Polygon([(0.0, -4.0), (50.0, -4.0), (50.0, -1.0), (0.0, -1.0)])
        fr_right = shade_fraction(right, grazes_right)
        fr_left = shade_fraction(left, grazes_right)
        assert fr_right == pytest.approx(0.5)
        assert fr_left == 0.0
        assert max(fr_right, fr_left) == fr_right

    def test_union_across_both_sides_before_max(self):
        """§7.5: shadows are unioned across buildings first; both sidewalk
        candidates are scored against the SAME union."""
        right, left = sidewalk_offset_lines(CENTRELINE, width_m=8.0)
        band_right = Polygon([(10.0, -10.0), (40.0, -10.0), (40.0, -2.0), (10.0, -2.0)])
        band_left = Polygon([(50.0, 2.0), (90.0, 2.0), (90.0, 10.0), (50.0, 10.0)])
        shadow_union = unary_union([band_right, band_left])

        fr_right = shade_fraction(right, shadow_union)
        fr_left = shade_fraction(left, shadow_union)
        assert fr_right == pytest.approx(30.0 / 100.0)
        assert fr_left == pytest.approx(40.0 / 100.0)
        assert max(fr_right, fr_left) == pytest.approx(0.40)
        # Each side intersects only its own band — no cross-double-counting.
        assert fr_right + fr_left < 1.0
