#!/usr/bin/env python3
"""CHHAYA Phase 1 fallback parser - live-API map.osm -> pipeline inputs.

Overpass was unreachable from the build sandbox (406/SSL drops from the egress
proxy; see docs/BLOCKERS.md). The Karol Bagh bbox came from the live OSM API
/api/0.6/map, which contains ONLY raw nodes/ways/relations - no client-side
network simplification or walk-routing filtering, which is what fetch_osm.py
(osmnx) would normally produce. This script rebuilds those pipeline inputs
from the same data so Phase 1 can proceed unchanged:

    data/raw/map.osm        (in,  from the live API)
    -> data/raw/graph.graphml  walk MultiDiGraph (osmnx- attrs, both directions)
    -> data/raw/buildings.gpkg  closed building ways (Polygon, 4326)
    -> data/raw/trees.gpkg      natural=tree nodes (Point, 4326)
    -> data/raw/water.gpkg      natural=water + waterway lines (4326)

Walk semantics mirror osmnx network_type=walk: include pedestrian-accessible
highway classes (no motorway/platforms), split ways at shared nodes, add BOTH
directions for every edge (foot traffic ignores vehicular oneway).

Run:    python parse_map_osm.py
Then:   heights.py expects buildings.gpkg; dem_flood.py and shade.py expect
        graph.graphml - the same contracts as the osmnx fetch path.
"""
from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parse_map_osm")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

WALK_HIGHWAYS = {
    "footway", "path", "pedestrian", "steps", "living_street", "residential",
    "unclassified", "tertiary", "tertiary_link", "secondary", "secondary_link",
    "primary", "primary_link", "trunk", "trunk_link", "service", "track",
}
KEEP_TAGS = {"name", "building", "building:levels", "height", "highway",
             "natural", "waterway", "waterway:insert_depth_m"}


def parse_map_osm(path: Path) -> tuple[dict[int, tuple[float, float]], list[dict]]:
    """Two-pass iterparse: (1) all node coords, (2) ways + tags."""
    coords: dict[int, tuple[float, float]] = {}
    with path.open("rb") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == "node":
                coords[int(elem.get("id"))] = (float(elem.get("lon")), float(elem.get("lat")))
                elem.clear()
            elif elem.tag == "way":
                break
    ways: list[dict] = []
    with path.open("rb") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == "way":
                refs = [int(nd.get("ref")) for nd in elem.iterfind("nd")]
                tags = {t.get("k"): t.get("v") for t in elem.iterfind("tag")}
                ways.append({"id": int(elem.get("id")), "refs": refs, "tags": tags})
                elem.clear()
    return coords, ways


def build_outputs(coords, ways) -> None:
    # ---------- buildings ----------
    b_rows: list[dict] = []
    skipped_open = 0
    for w in ways:
        if "building" not in w["tags"]:
            continue
        pts = [coords[r] for r in w["refs"] if r in coords]
        if len(pts) < 4 or pts[0] != pts[-1]:
            skipped_open += 1
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            continue
        b_rows.append({"osmid": w["id"], "geometry": poly,
                       **{k: w["tags"].get(k) for k in ("name", "building", "building:levels", "height")}})
    buildings = gpd.GeoDataFrame(b_rows, geometry="geometry", crs="EPSG:4326")
    buildings.to_file(RAW / "buildings.gpkg", driver="GPKG")
    log.info("buildings.gpkg: %d polygons (%d open/invalid skipped)", len(buildings), skipped_open)

    # ---------- water ----------
    w_rows: list[dict] = []
    for w in ways:
        t = w["tags"]
        poly_water = t.get("natural") == "water"
        is_line = t.get("waterway") not in (None, "riverbank")
        if not poly_water and not is_line:
            continue
        pts = [coords[r] for r in w["refs"] if r in coords]
        if len(pts) < 2:
            continue
        if pts[0] == pts[-1] and len(pts) >= 4:
            geom: LineString | Polygon = Polygon(pts)
        else:
            geom = LineString(pts)
        w_row = {"osmid": w["id"], "geometry": geom}
        for k in ("name", "natural", "waterway"):
            if t.get(k):
                w_row[k] = t[k]
        w_rows.append(w_row)
    water = gpd.GeoDataFrame(w_rows, geometry="geometry", crs="EPSG:4326")
    water.to_file(RAW / "water.gpkg", driver="GPKG")
    log.info("water.gpkg: %d features", len(water))

    # ---------- trees ----------
    t_rows: list[dict] = []
    with RAW.joinpath("map.osm").open("rb") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == "node":
                tags = {t.get("k"): t.get("v") for t in elem.iterfind("tag")}
                if tags.get("natural") == "tree":
                    t_row = {"osmid": int(elem.get("id")),
                             "geometry": Point(float(elem.get("lon")), float(elem.get("lat")))}
                    if tags.get("name"):
                        t_row["name"] = tags["name"]
                    t_rows.append(t_row)
                elem.clear()
    trees = gpd.GeoDataFrame(t_rows, geometry="geometry", crs="EPSG:4326")
    trees.to_file(RAW / "trees.gpkg", driver="GPKG")
    log.info("trees.gpkg: %d points", len(trees))

    # ---------- walk graph ----------
    G = nx.MultiDiGraph()
    G.graph.update(crs="epsg:4326")
    for nid, (lon, lat) in coords.items():
        G.add_node(nid, x=lon, y=lat)
    edge_pair_keys: dict[tuple[int, int], int | dict[int, int]] = defaultdict(int)
    n_edges = 0
    for w in ways:
        hw = w["tags"].get("highway")
        if not hw or hw not in WALK_HIGHWAYS:
            continue
        # split the node list at missing refs (bbox-clipped ways)
        seq: list[int] = []
        for r in w["refs"]:
            if r in coords:
                seq.append(r)
            else:
                if len(seq) >= 2:
                    _add_edges(G, seq, w, edge_pair_keys)
                    n_edges += 1
                seq = []
        if len(seq) >= 2:
            _add_edges(G, seq, w, edge_pair_keys)
            n_edges += 1
    # strip attributes osmnx does not persist cleanly in GraphML
    import osmnx as ox
    for _u, _v, k, d in G.edges(keys=True, data=True):
        d.pop("osmid", None)
    isolates = list(nx.isolates(G))
    G.remove_nodes_from(isolates)
    log.info("removed %d isolated nodes (building/amenity nodes with no walk edge)", len(isolates))
    ox.save_graphml(G, RAW / "graph.graphml")
    counts = {"nodes": len(G.nodes), "edges": len(G.edges), "walk_ways": n_edges,
              "buildings": len(buildings), "trees": len(trees), "water": len(water)}
    (RAW / "fetch_counts.json").write_text(pd.Series(counts).to_json(indent=2))
    log.info("graph.graphml: %d nodes / %d edges (from %d walk ways)", len(G.nodes), len(G.edges), n_edges)
    log.info("counts: %s", counts)


def _add_edges(G, seq: list[int], way: dict, pair_keys) -> None:
    hw = way["tags"].get("highway", "")
    name = way["tags"].get("name")
    osmid = way["id"]
    for a, b in pairwise(seq):
        lon1, lat1 = G.nodes[a]["x"], G.nodes[a]["y"]
        lon2, lat2 = G.nodes[b]["x"], G.nodes[b]["y"]
        length = _haversine_m(lat1, lon1, lat2, lon2)
        k = pair_keys[(a, b)]
        if a != b:
            pair_keys[(b, a)] = k  # mirror key so the reverse edge matches
        G.add_edge(a, b, key=k, osmid=osmid, name=name, highway=hw, length=length, oneway=False)
        G.add_edge(b, a, key=k, osmid=osmid, name=name, highway=hw, length=length, oneway=False)
        pair_keys[(a, b)] = k + 1
        if a != b:
            pair_keys[(b, a)] = k + 1


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


if __name__ == "__main__":
    coords, ways = parse_map_osm(RAW / "map.osm")
    build_outputs(coords, ways)
