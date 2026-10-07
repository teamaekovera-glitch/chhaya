#!/usr/bin/env python3
"""CHHAYA Phase 1 — per-edge flood_risk from Copernicus GLO-30 (§7.3).

Read path (locked in the decision sheet):
  - bucket `s3://copernicus-dem-30m/` is a public S3-backed resource: read it
    UNAUTHENTICATED (rasterio env AWS_NO_SIGN_REQUEST=YES). No AWS credentials
    exist in the build sandbox, so key discovery uses an unsigned boto3 list
    (same semantics as `aws s3 ls`) instead of a signed call.
  - the exact TIFF object key under the tile stem is DISCOVERED FIRST via list
    (never hardcoded in committed code), then window-clipped to bbox + 2 km.

Flood chain (§7.3):
  burn OSM water by -10 m  ->  pysheds fill_pits / fill_depressions /
  resolve_flats / flowdir / accumulation / compute_hand (stream mask starts at
  200 cells and halves until at least one stream crosses the area).
  TWI = ln(acc_area / tan(slope)); slope is computed with numpy gradients on
  the cell grid rather than pysheds' own slope helper (digital check: pysheds
  0.5 CELL_SLOPES semantics differ across versions; the gradient form is exact
  for a regular grid).
  Per edge: sample HAND and TWI every 10 m along the UTM geometry, take the
  mean, then rank-normalise across edges inside the area:
      flood_risk = clip(0.5*rank_norm(TWI) + 0.5*(1 - rank_norm(HAND)), 0, 1)
  bridges -> 0.0; underpasses keep their value (the `is_underpass` penalty is
  applied later at routing, per §8.1). Manual hotspots (data/hotspots.geojson,
  optional) add +0.5 within 100 m.

Output: data/flood.parquet (u, v, key, edge_id, length_m, flood_risk, hand,
        twi, is_underpass + geometry WGS84) + plots/flood_map.png.

NOTE: numpy is pinned < 2.2 (pipeline/requirements.txt) because pysheds 0.5
calls np.in1d, removed in numpy 2.2+.

Honesty note for the writeup: a 30 m DEM gives relative, not street-exact,
risk; hotspots and crowd reports correct it.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import pandas as pd
import rasterio
from config import BBOX, UTM_EPSG
from scipy.stats import rankdata
from shapely.geometry import Point, mapping

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dem_flood")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DATA = ROOT / "data"
PLOTS = Path(__file__).resolve().parent / "plots"

BUCKET = "copernicus-dem-30m"
# tile stem per §7.3: N{lat:02d}_00_E{lon:03d}_00; Delhi (77.19E, 28.65N) -> N28_00_E077_00
LAT_TILE, LON_TILE = 28, 77
DEM_STEM = f"Copernicus_DSM_COG_10_N{LAT_TILE:02d}_00_E{LON_TILE:03d}_00_DEM"
MARGIN_M = 2000
SAMPLE_SPACING_M = 10
MAX_SAMPLES_PER_EDGE = 100
STREAM_START_CELLS = 200
STREAM_MIN_CELLS = 20
HOTSPOT_BOOST = 0.5
HOTSPOT_RADIUS_M = 100.0
WATER_BURN_M = -10.0


# ------------------------------------------------------------- GLO-30 read

def discover_tif_key() -> str:
    """List the tile stem prefix unauthenticated and return the exact raster key.

    The key is a lookup result, never a hardcoded constant (decision sheet:
    "listed, never assumed"). All sibling objects under the stem are logged.
    """
    import boto3
    from botocore import UNSIGNED
    from botocore.client import Config

    client = boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    prefix = f"{DEM_STEM}/"
    log.info("listing s3://%s/%s (unsigned) ...", BUCKET, prefix)
    resp = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=50)
    keys = sorted(obj["Key"] for obj in resp.get("Contents", []))
    if not keys:
        raise FileNotFoundError(
            f"tile stem s3://{BUCKET}/{prefix} not found - GLO-30 Public overlay is "
            "country-limited; try sibling tiles (N28_00_E076_00 etc.) per §11"
        )
    log.info("objects under stem:\n%s", json.dumps(keys, indent=2))
    tifs = [k for k in keys if k.endswith(".tif")]
    # The tile contains auxiliary rasters (AUXFILES/EDM etc.) whose data are
    # flag values, not elevations - the main DEM object is named exactly
    # "<stem>.tif" under the stem's DEM/ folder. Filtering to it is the fix
    # for picking an auxiliary mask and reading -9999 everywhere.
    main = [k for k in tifs if k.endswith(f"{DEM_STEM}.tif")]
    if not main:
        raise FileNotFoundError(
            f"main DEM object <{DEM_STEM}.tif> not found under {prefix} (all keys: {keys})"
        )
    return main[0]


def fetch_dem_window(dst: Path) -> tuple[float, float]:
    """Window-clip GLO-30 to bbox + margin and reproject to UTM.

    Returns the (cell_width_m, cell_height_m) of the saved UTM raster.
    """
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    west, south, east, north = BBOX
    key = discover_tif_key()
    url = f"s3://{BUCKET}/{key}"
    log.info("opening %s unsigned (window = bbox + %d m margin)", url, MARGIN_M)

    lat_pad = MARGIN_M / 111_000.0
    lon_pad = MARGIN_M / (111_000.0 * float(np.cos(np.deg2rad((south + north) / 2))))
    # WarpedVRT reprojects on read - rasterio.warp.reproject on this tile
    # window emitted all-nodata despite success return codes (probed before
    # committing), so bounds go in as an explicit transform: the
    # left/bottom/right/top keywords are NOT WarpedVRT parameters and a
    # loose-kwargs call silently ignores them.
    import pyproj
    from rasterio.transform import Affine

    tr = pyproj.Transformer.from_crs(4326, UTM_EPSG, always_xy=True)
    xs, ys = tr.transform(
        [west - lon_pad, east + lon_pad, west - lon_pad, east + lon_pad],
        [south - lat_pad, south - lat_pad, north + lat_pad, north + lat_pad],
    )
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    grid_res = 28.5  # ~248 E x 203 N cells over bbox + margin
    vrt_width = int(np.ceil((xmax - xmin) / grid_res))
    vrt_height = int(np.ceil((ymax - ymin) / grid_res))
    vrt_transform = Affine(grid_res, 0, xmin, 0, -grid_res, ymax)
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"), rasterio.open(url) as src, WarpedVRT(
        src,
        crs=f"EPSG:{UTM_EPSG}",
        resampling=Resampling.bilinear,
        transform=vrt_transform,
        width=vrt_width,
        height=vrt_height,
    ) as vrt:
        dem_utm = vrt.read(1).astype(np.float32)
        utm_transform = vrt.transform
        utm_h, utm_w = dem_utm.shape
        src_nodata = vrt.nodata if vrt.nodata is not None else -9999.0
        valid = int((dem_utm != src_nodata).sum())
    log.info("vrt %dx%d UTM cells, nodata=%s, valid=%d", utm_w, utm_h, src_nodata, valid)
    if valid == 0:
        raise RuntimeError("WarpedVRT read produced no valid DEM cells - tile/window mismatch")

    dst.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "driver": "GTiff",
        "height": utm_h,
        "width": utm_w,
        "count": 1,
        "dtype": "float32",
        "crs": f"EPSG:{UTM_EPSG}",
        "transform": utm_transform,
        "nodata": src_nodata,
    }
    with rasterio.open(dst, "w", **meta) as out:
        # rasterio 1.5 requires band-stacked (1, h, w) input for write();
        # write_band(1, 2d) is the 1.3-compatible idiom that works in both.
        out.write_band(1, dem_utm)
    cell_w, cell_h = float(utm_transform.a), float(abs(utm_transform.e))
    log.info("wrote %s (%dx%d UTM cells, cell=%.2f x %.2f m)", dst, utm_w, utm_h, cell_w, cell_h)
    return cell_w, cell_h


# ---------------------------------------------------------------- hydrology

def water_burn_mask(shape: tuple[int, int], transform) -> np.ndarray:
    """Rasterize OSM water (polygons; waterway lines buffered 5 m) as a burn mask."""
    water = gpd.read_file(RAW / "water.gpkg").to_crs(f"EPSG:{UTM_EPSG}")
    if len(water) == 0:
        log.warning("no OSM water features in the bbox - flood chain runs on raw DEM")
        return np.zeros(shape, dtype=np.uint8)
    polys = water[water.geometry.geom_type.isin(("Polygon", "MultiPolygon"))].geometry
    lines = water[water.geometry.geom_type.isin(("LineString", "MultiLineString"))].geometry.buffer(5.0)
    to_burn = gpd.GeoSeries(pd.concat([polys, lines], ignore_index=True), crs=f"EPSG:{UTM_EPSG}")
    from rasterio.features import rasterize as _rasterize
    mask = _rasterize(
        [(mapping(g), 1) for g in to_burn if not g.is_empty],
        out_shape=shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    )
    log.info("water burn mask covers %d cells", int(mask.sum()))
    return mask


def hydrology(dst: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """pysheds HAND + TWI + accumulation over the water-burned UTM DEM."""
    from pysheds import sgrid

    grid = sgrid.sGrid.from_raster(str(dst))
    dem = grid.read_raster(str(dst))  # pysheds Raster (fill_pits etc. need .nodata)
    cell_w, cell_h = float(grid.affine.a), float(abs(grid.affine.e))
    log.info("pysheds grid %dx%d, cell=%.2f x %.2f m", grid.shape[1], grid.shape[0], cell_w, cell_h)

    water_mask = water_burn_mask(dem.shape, grid.affine)
    if water_mask.any():
        burned = np.where(water_mask == 1, dem + WATER_BURN_M, dem)
        if not isinstance(burned, sgrid.Raster):
            burned = sgrid.Raster(np.asarray(burned), grid.viewfinder)
        dem = burned
    else:
        log.info("no water cells - DEM unmodified")

    nodata = grid.nodata
    filled = grid.fill_pits(dem)
    filled = grid.fill_depressions(filled)
    inflated = grid.resolve_flats(filled)
    fdir = grid.flowdir(inflated, nodata_out=nodata)
    acc = grid.accumulation(fdir, nodata_out=0.0)

    # stream threshold: start at 200 cells, halve until a stream crosses the area
    threshold, stream_cells, mask = STREAM_START_CELLS, 0, np.zeros(dem.shape, dtype=bool)
    while threshold >= STREAM_MIN_CELLS:
        mask = acc >= threshold
        stream_cells = int(mask.sum())
        if stream_cells > 0:
            break
        log.info("stream threshold %d cells yields nothing - halving", threshold)
        threshold //= 2
    if stream_cells == 0:
        raise RuntimeError(f"no stream cells even at the {STREAM_MIN_CELLS}-cell threshold (max acc={float(acc.max()):.0f})")
    log.info("stream mask: threshold=%d cells, stream_cells=%d, max acc=%.0f", threshold, stream_cells, float(acc.max()))

    hand_raw = grid.compute_hand(fdir, inflated, mask.astype("float64"), nodata_out=0.0).astype("float64")
    hand = np.where(acc >= threshold, hand_raw, 0.0)

    # slope (m/m) and TWI = ln(acc_area / tan(slope)); gradient on the regular grid
    gy, gx = np.gradient(dem, cell_h, cell_w)
    slope = np.maximum(np.hypot(gx, gy), 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        twi = np.log(np.maximum(acc * cell_w * cell_h, 1e-9) / slope)
    finite = np.isfinite(twi)
    twi = np.where(finite, twi, float(np.median(twi[finite])) if finite.any() else 0.0)

    info = {
        "stream_threshold_cells": int(threshold),
        "stream_cells": stream_cells,
        "cell_m": [cell_w, cell_h],
        "dem_min_m": float(np.nanmin(dem)),
        "dem_max_m": float(np.nanmax(dem)),
    }
    log.info("hydrology done: %s", info)
    return hand, twi, acc, info


# ------------------------------------------------------------- edge scoring

def rank_norm(v: np.ndarray) -> np.ndarray:
    """Rank-normalise finite values to [0,1]; NaN stays NaN."""
    finite = np.isfinite(v)
    out = np.full(v.shape, np.nan)
    if int(finite.sum()) > 1:
        out[finite] = rankdata(v[finite]) / int(finite.sum())
    return out


def sample_along_geometry(geom, arr: np.ndarray, transform) -> np.ndarray:
    """Sample a raster every ~10 m along a UTM line geometry (nearest cell)."""
    length = float(geom.length)
    n = max(2, min(int(length // SAMPLE_SPACING_M) + 1, MAX_SAMPLES_PER_EDGE))
    pts = [geom.interpolate(t, normalized=True) for t in np.linspace(0.0, 1.0, n)]
    inv = ~transform
    vals = np.full(len(pts), np.nan)
    for i, p in enumerate(pts):
        col, row = inv * (p.x, p.y)
        c, r = int(col), int(row)
        if 0 <= r < arr.shape[0] and 0 <= c < arr.shape[1]:
            vals[i] = float(arr[r, c])
    return vals


def hotspots_boost(edge_mids: list[Point]) -> np.ndarray:
    """+HOTSPOT_BOOST to edges whose midpoint is within HOTSPOT_RADIUS_M of a hotspot."""
    boost = np.zeros(len(edge_mids))
    hp_file = DATA / "hotspots.geojson"
    if not hp_file.exists():
        log.info("no data/hotspots.geojson - no manual hotspot boost")
        return boost
    hp = gpd.read_file(hp_file).to_crs(f"EPSG:{UTM_EPSG}")
    if len(hp) == 0:
        return boost
    mids = gpd.GeoDataFrame(geometry=gpd.GeoSeries(edge_mids, crs=f"EPSG:{UTM_EPSG}"))
    joined = gpd.sjoin_nearest(mids, hp[hp.geometry.notna()], how="left", distance_col="dist_m")
    if "dist_m" in joined:
        boost = (joined["dist_m"].fillna(np.inf) <= HOTSPOT_RADIUS_M).to_numpy() * HOTSPOT_BOOST
    log.info("manual hotspots: %d edges boosted", int((boost > 0).sum()))
    return boost


def build_edge_table(hand: np.ndarray, twi: np.ndarray, transform, hydro_info: dict) -> gpd.GeoDataFrame:
    """Project graph to UTM, sample rasters per edge, score, and save flood.parquet."""
    G = ox.load_graphml(RAW / "graph.graphml")
    G_utm = ox.project_graph(G, to_crs=f"EPSG:{UTM_EPSG}")
    _, edges = ox.graph_to_gdfs(G_utm)
    log.info("scoring %d edges", len(edges))

    hand_samples = [sample_along_geometry(g, hand, transform) for g in edges.geometry]
    twi_samples = [sample_along_geometry(g, twi, transform) for g in edges.geometry]
    hand_mean = np.array([np.mean(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan for v in hand_samples])
    twi_mean = np.array([np.mean(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan for v in twi_samples])
    n_hand_out = int(np.isnan(hand_mean).sum())
    n_twi_out = int(np.isnan(twi_mean).sum())
    log.info("samples outside raster window: hand=%d, twi=%d of %d edges", n_hand_out, n_twi_out, len(edges))
    if n_hand_out > len(edges) * 0.2:
        log.warning("more than 20%% of edges sampled outside the DEM window - check MARGIN_M")

    twi_n = rank_norm(twi_mean)
    hand_n = rank_norm(hand_mean)
    risk = np.clip(0.5 * np.nan_to_num(twi_n, nan=0.5) + 0.5 * (1.0 - np.nan_to_num(hand_n, nan=0.5)), 0.0, 1.0)

    edges["u"] = edges.index.get_level_values("u")
    edges["v"] = edges.index.get_level_values("v")
    edges["key"] = edges.index.get_level_values("key")
    edges["edge_id"] = np.arange(len(edges), dtype=np.int64)
    edges["flood_risk"] = np.round(risk, 4)
    edges["hand"] = np.round(hand_mean, 2)
    edges["twi"] = np.round(twi_mean, 2)
    edges["length_m"] = np.round(edges.length, 1)

    # tunnel/bridge flags: OSM stores "yes"/"no"/"culvert" and NaN in object columns;
    # a bool cast on "no" would be truthy, so match the osm truthy tag values explicitly
    tunnel_col = edges.get("tunnel", pd.Series(False, index=edges.index))
    tunnel = tunnel_col.astype(str).str.lower().isin({"yes", "true", "culvert", "building_passage"})
    layer_num = pd.to_numeric(edges.get("layer", pd.Series(0, index=edges.index)), errors="coerce").fillna(0)
    edges["is_underpass"] = (tunnel | (layer_num < 0)).to_numpy()
    bridge_col = edges.get("bridge", pd.Series(False, index=edges.index))
    bridge = bridge_col.astype(str).str.lower().isin({"yes", "true", "viaduct", "aqueduct"}).to_numpy()
    edges["is_bridge"] = bridge

    # hotspot boost by UTM midpoint
    mids = [g.interpolate(0.5, normalized=True) for g in edges.geometry]
    edges["flood_risk"] = np.clip(edges["flood_risk"].to_numpy() + hotspots_boost(mids), 0.0, 1.0)
    edges["flood_risk"] = np.where(bridge, 0.0, edges["flood_risk"])

    keep = ["u", "v", "key", "edge_id", "length_m", "flood_risk", "hand", "twi", "is_underpass", "is_bridge", "geometry"]
    out_wgs = edges[keep].to_crs(4326)
    out_wgs.to_parquet(DATA / "flood.parquet", index=False)

    summary = {
        **hydro_info,
        "edges": len(out_wgs),
        "edges_outside_dem": {"hand": n_hand_out, "twi": n_twi_out},
        "flood_risk_mean": float(out_wgs["flood_risk"].mean()),
        "flood_risk_p90": float(out_wgs["flood_risk"].quantile(0.9)),
        "flood_risk_max": float(out_wgs["flood_risk"].max()),
        "hand_mean_m": float(np.nanmean(out_wgs["hand"])),
        "twi_mean": float(np.nanmean(out_wgs["twi"])),
        "bridges": int(bridge.sum()),
        "underpasses": int(out_wgs["is_underpass"].sum()),
    }
    (DATA / "flood_stats.json").write_text(json.dumps(summary, indent=2))
    log.info("flood stats:\n%s", json.dumps(summary, indent=2))
    return out_wgs


# -------------------------------------------------------------------- plot

def plot_flood_map(edges: gpd.GeoDataFrame) -> Path:
    """Edges coloured by flood_risk over a light basemap of buildings."""
    PLOTS.mkdir(parents=True, exist_ok=True)
    buildings = gpd.read_file(DATA / "buildings_heights.gpkg").to_crs(f"EPSG:{UTM_EPSG}")
    edges_utm = edges.to_crs(f"EPSG:{UTM_EPSG}")

    fig, ax = plt.subplots(figsize=(12, 12), dpi=160)
    buildings.plot(ax=ax, color="#d9d9d9", edgecolor="none", zorder=1)
    edges_utm.plot(
        ax=ax, column="flood_risk", cmap="Blues", linewidth=1.6, zorder=2,
        legend=True, legend_kwds={"label": "flood_risk (0 = safe, 1 = high)", "shrink": 0.6},
    )
    hp_file = DATA / "hotspots.geojson"
    if hp_file.exists():
        hp = gpd.read_file(hp_file).to_crs(f"EPSG:{UTM_EPSG}")
        hp.plot(ax=ax, color="red", marker="x", markersize=60, zorder=3, label="manual hotspots")
        ax.legend(loc="lower left")
    ax.set_title(f"Karol Bagh — per-edge flood_risk (GLO-30 HAND+TWI, {len(edges)} edges)")
    ax.set_aspect("equal")
    out = PLOTS / "flood_map.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out)
    return out


# -------------------------------------------------------------------- main

def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    dem_tif = DATA / "dem_utm.tif"
    if not dem_tif.exists():
        fetch_dem_window(dem_tif)
    with rasterio.open(dem_tif) as src:
        transform = src.transform

    hand, twi, _acc, hydro_info = hydrology(dem_tif)
    edges = build_edge_table(hand, twi, transform, hydro_info)
    plot_flood_map(edges)


if __name__ == "__main__":
    main()
