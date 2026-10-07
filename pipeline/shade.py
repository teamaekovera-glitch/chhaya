#!/usr/bin/env python3
"""CHHAYA Phase 1 — shade engine (§7.5) and the 500 m test-tile run.

Shadow math (§7.5, exact contract):
  For a season/slot compute sun altitude alt and azimuth az (deg from north,
  clockwise) at the area centroid (pipeline/solar.py -> shared/solar_numpy.py).
  alt < 5 deg: shade = 1.0 for every edge, done.
  Shadow length L = min(h / tan(alt), 250 m); direction away from sun
  theta = az + 180 deg; displacement dx = L*sin(theta), dy = L*cos(theta)
  in UTM metres (x east, y north).
  Shadow polygon of footprint P = unary_union([P, translate(P, dx, dy)] +
  [quad(e_i, e_i + d) over each exterior edge]); simplify(tolerance=0.5).
  Per street edge, two sidewalk lines offset_curve(+(w/2 - 1.5)) and
  -(w/2 - 1.5) (fallback: centreline); fraction of line length inside the
  union of candidate shadow polygons (STRtree query); edge shade = max of the
  two sides; building-footprint intersections are ignored (streets don't run
  through buildings).

Phase 1 scope (§10): a 500 m test tile around the coverage centroid for the
gate slots, so a human can confirm shadow DIRECTION (morning shadows point
west, evening east, noon short and north). Plots carry buildings, shadow
polygons, an arrow toward the sun, and per-edge shade colours.

  Run:  python shade.py --test-tile --season summer --slots 0,16,24,32,44
  Out:  data/shade_testtile_{season}.parquet  (u, v, key, slot, shade)
        pipeline/plots/shadows_{season}_{slot:02d}.png
        pipeline/plots/shadows_{season}_PRIME.png  (alias of PRIME_SLOT 36 = 16:00)

SOLAR SOURCE: the canonical implementation is shared/solar_numpy.py (parallel
tests worker). Until it lands on main, set CHHAYA_LOCAL_SUN=1 to use the
env-guarded local NOAA fallback below - INTERIM ONLY, never the production
path; runs without the env var fail loudly instead of forking the math quietly.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # config + shared imports resolve from repo root

from config import AREA_NAME, SLOT_START_MINUTES

from pipeline import solar as solar_mod
from shared.geometry import shade_fraction, sidewalk_offset_lines
from shared.shadow import shadow_sweep_polygon

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("shade")

DATA = ROOT / "data"
RAW = DATA / "raw"
PLOTS = Path(__file__).resolve().parent / "plots"
TILE_SIZE_M = 500.0
SHADOW_MAX_M = 250.0
MIN_SUN_ALT_DEG = 5.0
SIMPLIFY_TOL_M = 0.5
GATE_SLOTS = (0, 16, 24, 32, 44)
PRIME_SLOT = 36  # 16:00 IST — warm-afternoon framing for the demo PRIME plot

# Width lookup (m) per §8.4
WIDTH_LOOKUP = {
    "motorway": 24.0, "motorway_link": 24.0, "trunk": 24.0, "trunk_link": 24.0,
    "primary": 20.0, "primary_link": 20.0,
    "secondary": 15.0, "secondary_link": 15.0,
    "tertiary": 12.0, "tertiary_link": 12.0,
    "residential": 8.0, "unclassified": 8.0,
    "living_street": 6.0,
    "service": 5.0,
    "footway": 3.0, "path": 3.0, "pedestrian": 3.0, "steps": 3.0,
}
WIDTH_DEFAULT_M = 8.0


def width_for(highway_value: object) -> float:
    return WIDTH_LOOKUP.get(str(highway_value).strip().lower(), WIDTH_DEFAULT_M)


# ------------------------------------------------------------- solar sources

def ist_time(season: str, slot: int) -> datetime:
    """IST wall-clock datetime for a (season, slot) - interim-fallback helper."""
    from config import SEASON_DATES

    minutes = SLOT_START_MINUTES + 15 * slot
    hh, mm = divmod(minutes, 60)
    d = pd.Timestamp(SEASON_DATES[season]).date()
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def local_sun(times_ist: list[datetime], lon: float, lat: float) -> tuple[np.ndarray, np.ndarray]:
    """INTERIM NOAA solar position, guarded by CHHAYA_LOCAL_SUN=1 (test-tile only)."""
    if os.environ.get("CHHAYA_LOCAL_SUN") != "1":
        raise RuntimeError(
            "shared/solar_numpy.py is not on origin/main yet. Interim local run: "
            "set CHHAYA_LOCAL_SUN=1 (env-guarded NOAA fallback, test tile only) "
            "or poll main for the shared module and re-run."
        )
    log.warning("CHHAYA_LOCAL_SUN=1 -> interim local NOAA solver; NOT the shared canonical path")
    jds = np.array([_julian_date(t) for t in times_ist])
    return _noaa_solar_positions(jds, lon, lat)


def _julian_date(dt: datetime) -> float:
    """Meeus Julian Date for a Gregorian calendar datetime (utc or tz-aware)."""
    y, m = dt.year, dt.month
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    day_frac = dt.day + dt.hour / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day_frac + b - 1524.5


def _noaa_solar_positions(jd: np.ndarray, lon: float, lat: float) -> tuple[np.ndarray, np.ndarray]:
    """NOAA solar position equations. Returns (apparent altitude, azimuth from
    north clockwise), both degrees."""
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = (357.52911 + t * (35999.05029 - 0.0001537 * t)) % 360.0
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = np.radians(m)
    c = ((1.914602 - t * (0.004817 + 0.000014 * t)) * np.sin(mr)
         + (0.019993 - 0.000101 * t) * np.sin(2 * mr)
         + 0.000289 * np.sin(3 * mr))
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * np.sin(np.radians(omega))
    mean_obliq = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * np.cos(np.radians(omega))

    obliq_rad = np.radians(obliq)
    app_long_rad = np.radians(app_long)
    decl_rad = np.arcsin(np.sin(obliq_rad) * np.sin(app_long_rad))
    lat_rad = math.radians(lat)
    sin_lat, cos_lat = np.sin(lat_rad), np.cos(lat_rad)
    y = np.tan(obliq_rad / 2.0) ** 2
    l0_rad = np.radians(l0)
    eq_time = 4.0 * np.degrees(
        y * np.sin(2 * l0_rad)
        - 2 * e * np.sin(mr)
        + 4 * e * np.sin(mr) * np.cos(2 * l0_rad)
        - 0.5 * y**2 * np.sin(4 * l0_rad)
        - 1.25 * e**2 * np.sin(2 * mr)
    )

    ut = np.array([(dt.hour * 60 + dt.minute + dt.second / 60.0) for dt in
                   [t0 if t0.tzinfo else t0.replace(microsecond=0) for t0 in _jd_to_datetimes(jd)]])
    true_solar = np.mod(ut + eq_time + 4.0 * lon, 1440.0)
    hour_angle = np.radians(true_solar / 4.0 - 180.0)

    cos_zen = sin_lat * np.sin(decl_rad) + cos_lat * np.cos(decl_rad) * np.cos(hour_angle)
    zen = np.degrees(np.arccos(np.clip(cos_zen, -1.0, 1.0)))
    alt_true = 90.0 - zen

    az = np.mod(np.degrees(np.arctan2(
        np.sin(hour_angle),
        cos_lat * np.cos(decl_rad) * np.cos(hour_angle) - sin_lat * np.sin(decl_rad),
    )) + 180.0, 360.0)

    # NOAA refraction correction to apparent altitude
    refr = np.zeros_like(zen)
    hi = np.radians(alt_true)
    mask_hi = (alt_true > 5.0) & (alt_true <= 85.0)
    mask_lo = (alt_true > -0.575) & (alt_true <= 5.0)
    ta = np.tan(hi)
    refr[mask_hi] = (58.1 / ta[mask_hi] - 0.07 / ta[mask_hi] ** 3 + 0.000086 / ta[mask_hi] ** 5)
    refr[mask_lo] = 1735.0 + alt_true[mask_lo] * (-518.2 + alt_true[mask_lo] * (103.4 + alt_true[mask_lo] * (-12.79 + alt_true[mask_lo] * 0.711)))
    refr /= 3600.0
    return alt_true + refr, az


def _jd_to_datetimes(jd: np.ndarray) -> list[datetime]:
    base = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)  # JD 2451545.0
    return [base + timedelta(days=float(j - 2451545.0)) for j in jd]


def sun_alt_az(season: str, slot: int, lon: float, lat: float) -> tuple[float, float]:
    """Altitude and azimuth for one (season, slot); shared module is canonical."""
    ist = solar_mod.season_slot_times(season, slot)
    try:
        alt, az = solar_mod.solar_position([ist], lon, lat)
    except ImportError as exc:
        log.error("shared solar module unavailable (%s) - falling back behind the env guard", exc)
        alt, az = local_sun([ist_time(season, slot)], lon, lat)
    # Shared canon returns 0-d scalars for a single timestamp.
    return float(np.asarray(alt).reshape(-1)[0]), float(np.asarray(az).reshape(-1)[0])


# ---------------------------------------------------------------- shadow math
# Per §7.5 the canonical shadow/geometry math lives in shared/shadow.py and
# shared/geometry.py (merged via PR #2); these are thin adapters, never forks.

def shadow_polygon(footprint: Polygon, height_m: float, alt_deg: float, az_deg: float) -> Polygon | None:
    """§7.5 shadow polygon of a building footprint (UTM metres)."""
    return shadow_sweep_polygon(footprint, alt_deg, az_deg, height_m=height_m)


def edge_shade(centre_line: LineString, width_m: float, tree: STRtree, shadows: list[Polygon]) -> float:
    """edge shade = max of the two sidewalk fractions (walker picks the shady side)."""
    return max(
        shade_fraction(side, _shadow_union(side, tree, shadows))
        for side in sidewalk_offset_lines(centre_line, width_m)
    )


def _shadow_union(side: LineString, tree: STRtree, shadows: list[Polygon]):
    """Union of the shadow polygons whose STRtree candidates intersect `side`."""
    idxs = tree.query(side, predicate="intersects")
    if len(idxs) == 0:
        return None
    return unary_union([shadows[i] for i in np.atleast_1d(idxs)])


# ------------------------------------------------------------------ test tile

def load_test_tile() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, tuple[float, float]]:
    """Buildings (with heights) and walk edges clipped to a 500 m UTM square
    centred on COVERAGE_CENTROID. Edges are clipped to the tile so shade
    fractions measure only the in-tile walk stretch."""
    import pyproj
    from config import COVERAGE_CENTROID, UTM_EPSG

    buildings = gpd.read_file(DATA / "buildings_heights.gpkg").to_crs(f"EPSG:{UTM_EPSG}")
    G_utm = ox.project_graph(ox.load_graphml(RAW / "graph.graphml"), to_crs=f"EPSG:{UTM_EPSG}")
    _, edges = ox.graph_to_gdfs(G_utm)
    # u/v/key live in the edges MultiIndex; gpd.clip drops it, so flatten first.
    edges = edges.reset_index()

    lon, lat = COVERAGE_CENTROID
    cx, cy = pyproj.Transformer.from_crs(4326, f"EPSG:{UTM_EPSG}", always_xy=True).transform(lon, lat)
    half = TILE_SIZE_M / 2.0
    tile = Polygon([(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)])

    b_tile = gpd.clip(buildings, tile)
    e_tile = gpd.clip(edges, tile).copy().dropna(subset=["geometry"])
    e_tile = e_tile[~e_tile.geometry.is_empty]
    log.info("test tile: %d buildings / %d edge segments in a %d m square at (%.0f, %.0f)",
             len(b_tile), len(e_tile), int(TILE_SIZE_M), cx, cy)
    if len(b_tile) == 0 or len(e_tile) == 0:
        raise RuntimeError("test tile is empty - COVERAGE_CENTROID mis-set?")
    return b_tile, e_tile, (cx, cy)


def shade_for_slot(season: str, slot: int, b_tile: gpd.GeoDataFrame,
                   e_tile: gpd.GeoDataFrame, lon: float, lat: float) -> tuple[pd.DataFrame, dict]:
    """Per-edge shade fractions for one (season, slot) over the test tile."""
    alt, az = sun_alt_az(season, slot, lon, lat)
    sun = {"season": season, "slot": slot, "alt_deg": round(alt, 2), "az_deg": round(az, 2)}

    if alt < MIN_SUN_ALT_DEG:
        log.info("sun alt %.1f < %.1f -> shade = 1.0 for all edges (§7.5 skip)", alt, MIN_SUN_ALT_DEG)
        rows = [
            {"u": r.u, "v": r.v, "key": r.key, "slot": slot, "shade": 1.0}
            for r in e_tile.itertuples()
        ]
        return pd.DataFrame(rows), sun

    shadows = [
        p for p in (shadow_polygon(r.geometry, float(r.height_m), alt, az) for r in b_tile.itertuples())
        if p is not None
    ]
    tree = STRtree(shadows)
    log.info("slot %02d: %d shadow polygons, %d buildings", slot, len(shadows), len(b_tile))

    rows = []
    for r in e_tile.itertuples():
        width = width_for(r.highway) if getattr(r, "highway", None) else WIDTH_DEFAULT_M
        rows.append({"u": r.u, "v": r.v, "key": r.key,
                     "slot": slot, "shade": edge_shade(r.geometry, width, tree, shadows)})
    return pd.DataFrame(rows), sun


# --------------------------------------------------------------------- plot

def plot_shadows(season: str, slot: int, sun: dict, b_tile: gpd.GeoDataFrame,
                 e_tile: gpd.GeoDataFrame, shade_df: pd.DataFrame, cx: float, cy: float) -> Path:
    """Buildings + shadow polygons + shaded edges + an arrow toward the sun.

    The plot is the §0 rule 3 human gate: morning shadows must point west,
    evening shadows east, noon shadows short and north, and the arrow must
    point back at the shadow-travel direction by construction (arrow = toward
    the sun; shadows stretch away from it).
    """
    from config import UTM_EPSG

    # recompute the shadow polygons for drawing
    shadows = []
    if sun["alt_deg"] >= MIN_SUN_ALT_DEG:  # §7.5 skip threshold on the drawn slot
        shadows = [p for p in (
            shadow_polygon(r.geometry, float(r.height_m), sun["alt_deg"], sun["az_deg"])
            for r in b_tile.itertuples()
        ) if p is not None]

    fig, ax = plt.subplots(figsize=(11, 11), dpi=160)
    if shadows:
        gpd.GeoSeries(pd.Series(shadows), crs=f"EPSG:{UTM_EPSG}").plot(
            ax=ax, color="#252525", alpha=0.40, edgecolor="none", zorder=2,
        )
    b_tile.plot(ax=ax, color="#9e9e9e", edgecolor="#666666", linewidth=0.4, zorder=3)
    merged = e_tile.merge(shade_df, on=["u", "v", "key"], how="inner")
    cmap = "Greens" if season == "summer" else "Purples"
    if len(merged):
        merged.plot(ax=ax, column="shade", cmap=cmap, linewidth=2.2, vmin=0.0, vmax=1.0,
                    zorder=4, legend=True,
                    legend_kwds={"label": "edge shade fraction (max of 2 sidewalks)", "shrink": 0.55})
    else:
        log.warning("plot: no edge/shade rows merged for slot %d", slot)

    # arrow toward the sun (az from north, cw): unit vector (sin az, cos az) in
    # UTM (x east, y north) - shadows must stretch the OPPOSITE way, by contract
    if sun["alt_deg"] > 0:
        arrow = 120.0
        ax.annotate(
            "", xy=(cx + arrow * math.sin(math.radians(sun["az_deg"])) / 2,
                    cy + arrow * math.cos(math.radians(sun["az_deg"])) / 2),
            xytext=(cx - arrow * math.sin(math.radians(sun["az_deg"])) / 2,
                    cy - arrow * math.cos(math.radians(sun["az_deg"])) / 2),
            arrowprops={"arrowstyle": "->", "color": "#e8a33d", "lw": 3}, zorder=10,
        )
        ax.text(cx, cy - 30, f"sun\naz {sun['az_deg']:.0f}° alt {sun['alt_deg']:.1f}°",
                color="#8a5a10", fontsize=9, ha="center", va="top", zorder=11)

    ax.set_title(f"{AREA_NAME} 500 m test tile — {season} slot {slot:02d} "
                 f"(sun az {sun['az_deg']:.0f}°, alt {sun['alt_deg']:.1f}°)")
    ax.set_aspect("equal")
    PLOTS.mkdir(parents=True, exist_ok=True)
    out = PLOTS / f"shadows_{season}_{slot:02d}.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out)
    return out


# ---------------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="CHHAYA Phase 1 - test-tile shade engine (§7.5)")
    ap.add_argument("--test-tile", action="store_true", required=True,
                    help="run the 500 m test tile at the coverage centroid (Phase 1 scope)")
    ap.add_argument("--season", choices=["summer", "monsoon"], required=True)
    ap.add_argument("--slots", default=",".join(str(s) for s in GATE_SLOTS),
                    help="comma-separated slot indices (default: the five gate slots)")
    ap.add_argument("--local-sun", action="store_true",
                    help="permit the interim CHHAYA_LOCAL_SUN=1 fallback for this run "
                         "(flag sets the env var; shared/solar_numpy.py stays canonical)")
    args = ap.parse_args()

    if args.local_sun:
        os.environ["CHHAYA_LOCAL_SUN"] = "1"

    b_tile, e_tile, (cx, cy) = load_test_tile()

    all_rows: list[pd.DataFrame] = []
    from config import COVERAGE_CENTROID

    for slot in [int(s) for s in args.slots.split(",") if str(s).strip() != ""]:
        shade_df, sun = shade_for_slot(args.season, slot, b_tile, e_tile, COVERAGE_CENTROID[0], COVERAGE_CENTROID[1])
        all_rows.append(shade_df)
        plot_shadows(args.season, slot, sun, b_tile, e_tile, shade_df, cx, cy)
        log.info("slot %02d: mean shade %.3f, max %.3f, sun %s",
                 slot, float(shade_df["shade"].mean()), float(shade_df["shade"].max()), sun)
        if slot == PRIME_SLOT:
            src = PLOTS / f"shadows_{args.season}_{slot:02d}.png"
            dst = PLOTS / f"shadows_{args.season}_PRIME.png"
            dst.write_bytes(src.read_bytes())
            log.info("wrote %s (alias of slot %02d = 16:00 IST)", dst, slot)

    out = pd.concat(all_rows, ignore_index=True)
    out_path = DATA / f"shade_testtile_{args.season}.parquet"
    out.to_parquet(out_path, index=False)
    log.info("wrote %s (%d slot-edge rows)", out_path, len(out))


if __name__ == "__main__":
    main()
