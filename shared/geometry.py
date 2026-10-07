"""Sidewalk-offset and shade-fraction helpers — CLAUDE.md §7.5/§8, shared surface.

Import surface frozen for pipeline/shade.py and lambdas/shade_slot:

    from shared.geometry import shade_fraction

    frac = shade_fraction(sidewalk_line, shadow_union)

- ``shade_fraction(sidewalk_line, shadow_union) -> float``: length of the part
  of ``sidewalk_line`` inside the union of shadow polygons, divided by the
  line's own length. 0.0 for an empty/degenerate line. ``shadow_union`` may be
  a single (Multi)Polygon or a geometry collection from ``unary_union``.
- ``sidewalk_offset_lines(line, width_m)`` returns the two §7.5 candidate
  sidewalk lines ``offset_curve(±(width_m/2 − 1.5))``; when the offset fails
  or degenerates (§7.5 fallback), both candidates are the centreline itself.
  Order is ``(offset_right_side, offset_left_side)`` relative to the line's
  direction — callers take ``max()`` of the two shade fractions anyway
  ("a walker picks the shady side").
- All inputs are shapely geometries in metres (UTM) — lengths are metric.
"""

from __future__ import annotations

from shapely.geometry.base import BaseGeometry

__all__ = ["SIDEWALK_CLEARANCE_M", "shade_fraction", "sidewalk_offset_lines"]

# §7.5: walker stands 1.5 m in from the kerb on either side of the carriageway.
SIDEWALK_CLEARANCE_M = 1.5


def shade_fraction(sidewalk_line: BaseGeometry, shadow_union: BaseGeometry) -> float:
    """Fraction of the sidewalk line's length that lies inside the shadow union.

    Per §7.5: ``line.intersection(union_of_candidate_shadows).length / line.length``.
    """
    if sidewalk_line is None or sidewalk_line.is_empty:
        return 0.0
    line_length = float(sidewalk_line.length)
    if line_length <= 0.0:
        return 0.0
    if shadow_union is None or shadow_union.is_empty:
        return 0.0
    inside = sidewalk_line.intersection(shadow_union)
    inside_length = float(getattr(inside, "length", 0.0))
    return float(min(max(inside_length / line_length, 0.0), 1.0))


def sidewalk_offset_lines(line: BaseGeometry, width_m: float):
    """The two candidate sidewalk lines for a street edge, per §7.5.

    Returns ``(right_offset, left_offset)`` at ``±(width_m/2 − 1.5)`` metres
    from the centreline. Falls back to the centreline for both when the offset
    raises or degenerates to an empty geometry — matching §7.5's "fallback to
    centreline if offset fails" verbatim.
    """
    clearance = abs(width_m / 2.0 - SIDEWALK_CLEARANCE_M)
    if clearance == 0.0:
        return line, line
    try:
        right = line.offset_curve(-clearance)
        left = line.offset_curve(clearance)
    except (AttributeError, ValueError, TypeError):
        return line, line

    if right.is_empty or not hasattr(right, "length"):
        right = line
    if left.is_empty or not hasattr(left, "length"):
        left = line
    return right, left
