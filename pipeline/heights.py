#!/usr/bin/env python3
"""CHHAYA Phase 1 — fill building heights per §7.2 precedence.

Per building, height comes from the first available source:
    1. `height` tag            - parsed as "12", "12 m", "12.5 m"; feet values are ignored
    2. `building:levels`       - levels * 3.2 + 1.0
    3. type default (§8 style ladder):
       apartments 18 | commercial/office/retail 12 | residential/house 9 |
       industrial 10 | school/hospital 12 | else 8

Every row gets `height_m` (float) and `height_source` (height_tag / levels / type_default /
type:fallback-8). The fill-rate table prints to stdout; the writeup repeats the rates
because it forces the design assumption out of the repo. Optionally overrides rank 2 with
a Google Open Buildings 2.5D Temporal raster when `data/ext/ob_height.tif` exists
(zonal median where presence > 0.5) - the raster is not part of Phase 1 unless provided.

Run:    python heights.py
Output: data/buildings_heights.gpkg  (buildings + height_m + height_source)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("heights")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "buildings_heights.gpkg"
EXT_RASTER = ROOT / "data" / "ext" / "ob_height.tif"

# type ladder from §7.2 — building value → metres (skip empty values "-1", "yes", "roof")
TYPE_HEIGHT = {
    "apartments": 18.0,
    "commercial": 12.0,
    "office": 12.0,
    "retail": 12.0,
    "residential": 9.0,
    "house": 9.0,
    "industrial": 10.0,
    "school": 12.0,
    "hospital": 12.0,
}
DEFAULT_HEIGHT = 8.0

_LEVELS_RE = re.compile(r"^\s*(\d+(\.\d+)?)\s*$")


def _parse_height_tag(value: object) -> float | None:
    """Parse `height` tag: metres only ("12", "12 m", "12.5 m"); feet ("12'", "12 ft") ignored."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().lower()
    if "'" in text or "ft" in text or "feet" in text:
        return None
    m = _LEVELS_RE.match(text.replace("m", "").strip()) if text else None
    if m:
        return float(m.group(1))
    return None


def _parse_levels(value: object) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    m = _LEVELS_RE.match(str(value).strip())
    return float(m.group(1)) if m else None


def _type_height(building_value: object) -> tuple[float, str]:
    h = TYPE_HEIGHT.get(str(building_value).strip().lower())
    if h is not None:
        return h, "type_default"
    return DEFAULT_HEIGHT, "type_fallback"


def main() -> None:
    gdf = gpd.read_file(RAW / "buildings.gpkg")
    n = len(gdf)

    heights = np.full(n, np.nan)
    sources = np.full(n, "", dtype=object)

    h_tag = gdf["height"].map(_parse_height_tag) if "height" in gdf else pd.Series(np.nan, index=gdf.index)
    levels = gdf["building:levels"].map(_parse_levels) if "building:levels" in gdf else pd.Series(np.nan, index=gdf.index)
    use_tag = h_tag.notna().to_numpy()
    use_levels = (~h_tag.notna() & levels.notna()).to_numpy()
    use_type = (~h_tag.notna() & ~levels.notna()).to_numpy()

    heights[use_tag] = h_tag[use_tag].to_numpy()
    sources[use_tag] = "height_tag"
    heights[use_levels] = (levels[use_levels] * 3.2 + 1.0).to_numpy()
    sources[use_levels] = "levels"
    for idx in gdf.index[use_type]:
        h, src = _type_height(gdf.at[idx, "building"])
        heights[idx] = h
        sources[idx] = src

    # Optional Google Open Buildings override (rank between tag and levels).
    if EXT_RASTER.exists():
        log.info("external ob_height.tif present - applying zonal median where presence > 0.5 (not implemented in Phase 1 ramp); recorded in DECISIONS.md")

    gdf["height_m"] = np.round(heights, 1)
    gdf["height_source"] = sources
    gdf.to_file(OUT, driver="GPKG")

    counts = gdf["height_source"].value_counts()
    mean_by = gdf.groupby("height_source")["height_m"].mean().round(1)
    print("\nfill-rate table (§7.2)")
    print(f"{'source':14s} {'count':>7s} {'fill%':>7s} {'mean_h':>8s}")
    for src in ["height_tag", "levels", "type_default", "type_fallback"]:
        c = int(counts.get(src, 0))
        pct = 100.0 * c / n if n else 0.0
        mean = mean_by.get(src, float("nan"))
        print(f"{src:14s} {c:7d} {pct:6.1f}% {mean:7.1f}m")
    total_tag = 100.0 * (counts.get("height_tag", 0) + counts.get("levels", 0)) / n if n else 0.0
    print(f"{'TOTAL osm-tagged':14s} {'':7s} {total_tag:6.1f}%")
    log.info("wrote %s (%d buildings)", OUT, n)


if __name__ == "__main__":
    main()
