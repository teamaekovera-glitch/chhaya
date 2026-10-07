#!/usr/bin/env python3
"""CHHAYA Phase 2 — assemble graph.pkl + nodes.npz + coverage.geojson (§7.6).

Consumes (ordering contract): edge_id is the row order of data/flood.parquet,
which was written from `ox.graph_to_gdfs(G_utm)` order of the walk MultiDiGraph
in pipeline/dem_flood.py. pipeline/shade.py writes data/shade_{season}.npy in
that same edge_id order (float16 shape (E, 48)) — row i of every array is the
same physical edge. Rebuilding the graph here re-projects the same GraphML with
osmnx and walks its edges in the identical deterministic order, then asserts
the alignment instead of assuming it (edge_id vs pre-join order identity).

Outputs (§6.3):
    data/graph.pkl      MultiDiGraph, pickle protocol 5 (upload-only artifact)
    data/nodes.npz      ids (int64), lon, lat (float64) for snapping without osmnx
    data/coverage.geojson  convex hull of nodes buffered 50 m, WGS84

Node attrs: x (lon), y (lat), x_m, y_m (UTM).
Edge attrs: length_m, highway, width_m (§8.4 lookup), is_underpass, is_bridge,
shade_summer / shade_monsoon (float16 (48,) views on the (E, 48) arrays),
flood_risk (float16), geometry (LineString WGS84).

§7.6 sanity gate — hard asserts with a printed table (any failure aborts):
    mean shade slot 24 (13:00)  <  mean shade slot 44 (18:00)
    mean shade slot 4  (08:00)  >  mean shade slot 24
    all underpass shade == 1.0; flood_risk in [0,1]; no NaN anywhere;
    weakly connected largest component >= 95% of nodes (drop the rest + log).

Run:    python build_graph.py
"""
from __future__ import annotations

import json
import logging
import pickle
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # config resolves from repo root

from config import SLOTS, UTM_EPSG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_graph")

RAW = ROOT / "data" / "raw"
DATA = ROOT / "data"

GRAPH_PKL = DATA / "graph.pkl"
NODES_NPZ = DATA / "nodes.npz"
COVERAGE_GEOJSON = DATA / "coverage.geojson"

MIN_SIZE_PCT = 95.0  # §7.6 connectivity floor
# §8.4 width lookup (m) — same ladder as pipeline/shade.py WIDTH_LOOKUP.
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


def print_gate_table(rows: list[tuple[str, str, object, str, bool]]) -> None:
    """The §7.6 table: what is asserted, observed value, threshold, verdict."""
    print("\nsanity gate (§7.6)")
    print(f"{'check':52s} {'value':>14s} {'threshold':>12s}  verdict")
    for name, op, value, threshold, ok in rows:
        val = f"{value:.4f}" if isinstance(value, float) else str(value)
        verdict = "PASS" if ok else "FAIL"
        print(f"{name:52s} {val:>14s} {' ' + op + ' ' + threshold:>12s}  {verdict}")
    print()


def load_full_area() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """UTM-projected edges in the CANONICAL pipeline edge order + WGS84 nodes.

    Canonical order == ox.graph_to_gdfs row order (adjacency insertion) with the
    (u, v, key) columns lifted out — the exact order dem_flood scored and
    shade.py's full run wrote its (E, 48) arrays in. build_graph previously
    sorted lexicographically here and assumed the two orders were equal; the
    §7.6 join guard disproved that (same 10,662-edge multiset, different
    sequence). Positional arrays have identity only under the shared order, so
    the loader now reproduces shade.py's loading path instead of re-sorting.
    """
    G = ox.load_graphml(RAW / "graph.graphml")
    G_utm = ox.project_graph(G, to_crs=f"EPSG:{UTM_EPSG}")
    nodes, edges = ox.graph_to_gdfs(G_utm)
    edges = edges.reset_index()
    nodes_wgs = nodes.to_crs(4326)
    edges["u"] = edges["u"].astype("int64")
    edges["v"] = edges["v"].astype("int64")
    return nodes_wgs, edges


def attach_arrays(edges: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict, dict]:
    """Join flood_risk by edge_id and attach the per-season shade arrays.

    The contract says GraphML rebuild order matches the flood.parquet edge_id
    order — asserted here (u/v/key/column identity), never assumed.
    """
    edges = edges.reset_index(drop=True)
    flood = pd.read_parquet(DATA / "flood.parquet")
    if list(flood["u"]) != list(edges["u"]) or list(flood["v"]) != list(edges["v"]) \
            or list(flood["key"]) != list(edges["key"]):
        raise RuntimeError(
            "GraphML rebuild order differs from flood.parquet edge_id order — "
            "refusing to attach scores to mismatched edges (contract §7.6)"
        )
    edges = edges.merge(flood[["edge_id", "flood_risk", "is_underpass", "is_bridge"]],
                        left_index=True, right_on="edge_id", how="inner", validate="one_to_one")
    edges = edges.reset_index(drop=True)

    shade: dict[str, np.ndarray] = {}
    for season in ("summer", "monsoon"):
        arr = np.load(DATA / f"shade_{season}.npy")
        if arr.shape != (len(edges), SLOTS):
            raise RuntimeError(
                f"shade_{season}.npy shape {arr.shape} != ({len(edges)}, {SLOTS}) "
                "- run pipeline/shade.py --full before build_graph.py"
            )
        shade[season] = arr
    edges["shade_summer"] = list(shade["summer"].astype(np.float16))
    edges["shade_monsoon"] = list(shade["monsoon"].astype(np.float16))
    edges["length_m"] = np.round(edges.geometry.to_crs(f"EPSG:{UTM_EPSG}").length, 1)
    return edges, shade, flood


def sanity_gate(edges: gpd.GeoDataFrame, shade: dict[str, np.ndarray],
                nodes_wgs: gpd.GeoDataFrame) -> int:
    """Hard-assert the §7.6 table; returns the surviving node count after the
    connectivity drop (mutates graph via the caller's return arguments)."""
    rows = []

    summer = shade["summer"]
    mean24 = float(np.mean(summer[:, 24]))
    mean44 = float(np.mean(summer[:, 44]))
    mean4 = float(np.mean(summer[:, 4]))
    # §7.6 encodes the diurnal asymmetry: morning and late-afternoon shade must
    # both exceed solar-noon shade (low sun = long shadows across the streets).
    rows.append(("mean shade slot 24 (13:00) < slot 44 (18:00)", "lt", mean24, f"{mean44:.4f}", mean24 < mean44))
    rows.append(("mean shade slot 4 (08:00) > slot 24 (13:00)", "gt", mean4, f"{mean24:.4f}", mean4 > mean24))

    up_mask = edges["is_underpass"].to_numpy(dtype=bool)
    if up_mask.any():
        up_min = min(float(np.min(shade[s][up_mask])) for s in ("summer", "monsoon"))
        up_ok = up_min >= 1.0 - 1e-6
    else:
        up_min, up_ok = 1.0, True  # vacuously true — no underpasses in the area
    rows.append(("all underpass shade == 1.0 (min over underpass edges)", "ge",
                 up_min, "1.0000", up_ok))

    flood = edges["flood_risk"].to_numpy(float)
    flood_ok = bool(np.all((flood >= 0.0) & (flood <= 1.0)))
    rows.append(("flood_risk in [0, 1]", "in", float(np.max(flood)), "[0,1]", flood_ok))

    nan_free = all(not np.isnan(np.asarray(a, float)).any() for a in (summer, shade["monsoon"], flood))
    rows.append(("no NaN in shade/flood arrays", "==", 0, "0", nan_free))

    # connectivity: weakly-connected largest component on a MultiDiGraph.
    # add_edges_from alone (3-tuples with the multigraph key) builds the node
    # set correctly; a pre-pass add_nodes_from(zip(u, v)) does NOT — networkx
    # misreads (u, v) node pairs and manufactures one tuple-node per edge
    # (observed: 15,087 nodes / 29.07% component). Endpoints self-register.
    G_d = nx.MultiDiGraph()
    G_d.add_edges_from(zip(edges["u"], edges["v"], edges["key"]))
    largest_nodes = max(nx.weakly_connected_components(G_d), key=len)
    kept_pct = 100.0 * len(largest_nodes) / len(G_d.nodes)
    rows.append(("weakly-connected largest component ≥ 95% nodes", "ge",
                 round(kept_pct, 2), "95.00", kept_pct >= MIN_SIZE_PCT))
    print_gate_table(rows)
    assert kept_pct >= MIN_SIZE_PCT, f"largest weak component only {kept_pct:.2f}% of nodes"

    assert mean24 < mean44, "§7.6 gate failed: 13:00 shade not below 18:00"
    assert mean4 > mean24, "§7.6 gate failed: 08:00 shade not above 13:00"
    assert up_ok, "§7.6 gate failed: underpass shade below 1.0"
    assert flood_ok, "§7.6 gate failed: flood_risk outside [0,1]"
    assert nan_free, "§7.6 gate failed: NaN present"

    return len(largest_nodes)


def write_graph(edges: gpd.GeoDataFrame, nodes_wgs: gpd.GeoDataFrame,
                largest_nodes: set[int]) -> None:
    """Write graph.pkl (protocol 5), nodes.npz, coverage.geojson, dropping
    nodes outside the largest weak component (§7.6) log-first."""
    n_before = len(edges)
    kept = edges[edges["u"].isin(largest_nodes) & edges["v"].isin(largest_nodes)].reset_index(drop=True)
    log.info("connectivity drop: %d -> %d edges (%d dropped)", n_before, len(kept), n_before - len(kept))

    G_out = nx.MultiDiGraph()
    G_out.graph["crs"] = "epsg:4326"
    lonlat = nodes_wgs.geometry  # already WGS84 (load_full_area reprojects)
    utm = nodes_wgs.to_crs(f"EPSG:{UTM_EPSG}")  # CRS-aware pass, not relabelling
    for nid, row in nodes_wgs.iterrows():
        if nid in largest_nodes:
            G_out.add_node(nid, x=float(row.geometry.x), y=float(row.geometry.y))
            # x_m / y_m come from the UTM projection that travel distances use
            G_out.nodes[nid]["x_m"] = float(utm.loc[nid].x)
            G_out.nodes[nid]["y_m"] = float(utm.loc[nid].y)

    # §6.3: edge geometry is stored WGS84 — one vectorised CRS pass, not per-row
    geom_wgs = kept.geometry.to_crs(4326)
    names = kept["name"] if "name" in kept.columns else pd.Series([None] * len(kept), index=kept.index)
    for pos, r in enumerate(kept.itertuples(index=False)):
        name = names.iloc[pos]
        attrs = {
            "length_m": float(r.length_m),
            "length": float(r.length_m),  # osmnx-alias kept so direct routing can use weight="length"
            "highway": str(r.highway),
            "width_m": width_for(r.highway),
            "is_underpass": bool(r.is_underpass),
            "is_bridge": bool(r.is_bridge),
            "shade_summer": np.asarray(r.shade_summer, dtype=np.float16),
            "shade_monsoon": np.asarray(r.shade_monsoon, dtype=np.float16),
            "flood_risk": np.float16(r.flood_risk),
            "geometry": geom_wgs.iloc[pos],
        }
        if name is not None and str(name) not in ("nan", ""):
            attrs["name"] = str(name)
        G_out.add_edge(r.u, r.v, key=r.key, **attrs)

    with GRAPH_PKL.open("wb") as fh:
        pickle.dump(G_out, fh, protocol=5)
    log.info("wrote %s (%.1f MiB, %d nodes / %d edges)",
             GRAPH_PKL, GRAPH_PKL.stat().st_size / 1048576, len(G_out.nodes), len(G_out.edges))

    ids = np.array(sorted(G_out.nodes), dtype=np.int64)
    np.savez(
        NODES_NPZ,
        ids=ids,
        lon=np.array([G_out.nodes[i]["x"] for i in ids], dtype=np.float64),
        lat=np.array([G_out.nodes[i]["y"] for i in ids], dtype=np.float64),
    )
    log.info("wrote %s (%d nodes, %.2f MiB)", NODES_NPZ,
             len(ids), NODES_NPZ.stat().st_size / 1048576)

    from shapely.ops import unary_union

    hull = unary_union(lonlat.geometry.tolist()).convex_hull.buffer(50.0 / 111_320.0)
    hull_gdf = gpd.GeoDataFrame(geometry=[hull], crs=4326)
    hull_gdf.to_file(COVERAGE_GEOJSON, driver="GeoJSON")
    log.info("wrote %s (convex hull + 50 m buffer, %d vertices)", COVERAGE_GEOJSON,
             len(hull.exterior.coords))


def main() -> None:
    nodes_wgs, edges = load_full_area()
    log.info("full area: %d edges / %d nodes (UTM, deterministic edge_id order)", len(edges), len(nodes_wgs))
    edges, shade, _flood = attach_arrays(edges)  # flood df already merged into edges
    n_largest_nodes = sanity_gate(edges, shade, nodes_wgs)

    # §3 S3 set: per-edge flood_risk as a flat float16 array in edge_id order
    np.save(DATA / "flood.npy", edges["flood_risk"].to_numpy(dtype=np.float16))
    log.info("wrote %s (float16, %d edges)", DATA / "flood.npy", len(edges))

    # sanity_gate returned the largest weak component's node count (§7.6);
    # write_graph needs the node SET, recomputed here on the full edge list
    # (add_edges_from alone — nx >= 3.6 add_nodes_from(zip(u, v)) would mint
    # pair-tuple phantom nodes)
    G_check = nx.MultiDiGraph()
    G_check.add_edges_from(zip(edges["u"], edges["v"], edges["key"]))
    largest_nodes = max(nx.weakly_connected_components(G_check), key=len)
    assert len(largest_nodes) == n_largest_nodes, "gate/main connectivity disagree"

    write_graph(edges, nodes_wgs, largest_nodes)
    stats = {
        "edges": len(edges),
        "nodes": len(nodes_wgs),
        "edges_after_connectivity_drop": int((edges["u"].isin(largest_nodes) & edges["v"].isin(largest_nodes)).sum()),
        "graph_pkl_bytes": GRAPH_PKL.stat().st_size,
        "nodes_npz_bytes": NODES_NPZ.stat().st_size,
    }
    (DATA / "graph_stats.json").write_text(json.dumps(stats, indent=2))
    log.info("stats:\n%s", json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
