#!/usr/bin/env python3
"""CHHAYA Phase 1 — fetch the Karol Bagh OSM walking network and feature layers.

§7.1: osmnx>=2.0. The bbox tuple order is (west, south, east, north) - the v2
convention (left, bottom, right, top); do NOT pass north/south/east/west kwargs.

Outputs (data/raw/):
    graph.graphml      simplified walk network (MultiDiGraph)
    buildings.gpkg     building footprints
    trees.gpkg         natural=tree points (strech S5 source; kept small)
    water.gpkg         natural=water polygons + waterway lines (flood burn mask)

Run:    python fetch_osm.py        (from pipeline/, with .venv active on PATH)
Done:   counts logged; loud abort if buildings < 500; fetch runs exactly once -
        subsequent runs load the cached GraphML/GPKG files instead of refetching.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import osmnx as ox
from config import AREA_NAME, BBOX

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_osm")

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
MIN_BUILDINGS = 500  # coverage sanity floor (§7.1)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    west, south, east, north = BBOX
    log.info("Fetching OSM for %s area bbox=(%.3f, %.3f, %.3f, %.3f)", AREA_NAME, west, south, east, north)

    # ---- graph ----
    graph_path = RAW / "graph.graphml"
    if graph_path.exists():
        G = ox.load_graphml(graph_path)
        log.info("Loaded cached graph: %d nodes / %d edges", len(G.nodes), len(G.edges))
    else:
        G = ox.graph_from_bbox(BBOX, network_type="walk", simplify=True, retain_all=False)
        ox.save_graphml(G, graph_path)
        log.info("Fetched graph: %d nodes / %d edges -> %s", len(G.nodes), len(G.edges), graph_path)

    # ---- feature layers ----
    layers = {
        "buildings": {"building": True},
        "trees": {"natural": "tree"},
        "water": {"natural": "water", "waterway": True},
    }
    for name, tags in layers.items():
        gpkg = RAW / f"{name}.gpkg"
        if gpkg.exists():
            gdf = gpd.read_file(gpkg)
            log.info("Loaded cached %s: %d features", name, len(gdf))
        else:
            gdf = ox.features_from_bbox(BBOX, tags=tags)
            # keep only useful columns: geometry + identity tags
            keep = [c for c in ("name", "building", "building:levels", "height", "natural", "waterway") if c in gdf.columns]
            gdf = gdf[keep + ["geometry"]]
            gdf.to_file(gpkg, driver="GPKG")
            log.info("Fetched %s: %d features -> %s", name, len(gdf), gpkg)

    n_buildings = len(gpd.read_file(RAW / "buildings.gpkg"))
    if n_buildings < MIN_BUILDINGS:
        log.critical("ABORT: only %d buildings inside the bbox (< %d) - coverage too thin, pick another area (§7.1).", n_buildings, MIN_BUILDINGS)
        sys.exit(2)
    log.info("Coverage OK: %d buildings >= %d", n_buildings, MIN_BUILDINGS)

    counts = {"nodes": len(G.nodes), "edges": len(G.edges), "buildings": n_buildings,
              "trees": len(gpd.read_file(RAW / "trees.gpkg")), "water": len(gpd.read_file(RAW / "water.gpkg"))}
    (RAW / "fetch_counts.json").write_text(json.dumps(counts, indent=2))
    log.info("counts: %s", counts)


if __name__ == "__main__":
    main()
