"""Deterministic synthetic routing fixture — Phase 3 tests (no AWS required).

The real data/graph.pkl is upload-only (gitignored, multi-MB) and does not exist
in CI sandboxes. This module builds a small stand-in with the same §6.3 contract
attrs so tests/test_route_api.py can exercise the full engine:
20 nodes / 30 directed edges, a hand-crafted scenario plus a default_rng(42)
jitter on filler edges only (designed edges stay exact so assertions hold).

Scenario layout (5 cols x 4 rows, node id = row * 5 + col), lengths in metres:

    row 0  (0,0) --120-- (0,1) --120-- (0,2) --120-- (0,3) --120-- (0,4)
                          (0,1)->(0,2) is an UNDERPASS
    row 1  (1,0) --120-- (1,1) --120-- (1,2) --120-- (1,3) --120-- (1,4)
             fully shaded corridor; hop (1,1)->(1,2) has flood_risk 0.9
    row 2  (2,0) --120-- (2,1) --120-- (2,2) --120-- (2,3) --120-- (2,4)
             safe, flood-free corridor
    row 3  filler row

Designed properties the tests rely on (deterministic):
  * (0,0)->(0,2): direct = main road incl. underpass (240 m);
    shade mode prefers the fully-shaded (1,0)->(1,1)->(1,2) bypass (440 m);
    flood+monsoon must skip the underpass and detours via row 2 (640 m).
  * (1,0)->(1,2): direct = 240 m via the flood-prone hop; flood+monsoon
    switches to the longer flood-free row-2 bypass (440 m).
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import networkx as nx
import numpy as np
from shapely.geometry import LineString

SEED = 42
SLOTS = 48

# Grid origin (inside the real coverage area, Karol Bagh) and spacing (metres).
LON0, LAT0 = 77.190, 28.6450
COL_STEP_M, ROW_STEP_M = 120.0, 100.0
_M_PER_DEG_LAT = 110_574.0
_M_PER_DEG_LON = 111_320.0 * np.cos(np.deg2rad(LAT0))

H_LENGTH = COL_STEP_M
V_LENGTH = ROW_STEP_M


def node_xy(node: int) -> tuple[float, float]:
    """Grid node -> (lon, lat). id = row * 5 + col; row 0 = north."""
    row, col = divmod(node, 5)
    lat = LAT0 - row * ROW_STEP_M / _M_PER_DEG_LAT
    lon = LON0 + col * COL_STEP_M / _M_PER_DEG_LON
    return lon, lat


def _shade(base: float) -> np.ndarray:
    return np.full(SLOTS, base, dtype=np.float16)


def _geom(u: int, v: int) -> LineString:
    x0, y0 = node_xy(u)
    x1, y1 = node_xy(v)
    return LineString([(x0, y0), (x1, y1)])


# (u, v, length_m, shade_summer, shade_monsoon, flood_risk, kwargs) — hand-crafted.
EDGES: list[tuple[int, int, float, float, float, float, dict]] = [
    # row 0 — the exposed main corridor; (0,1)->(0,2) is the underpass.
    (0, 1, H_LENGTH, 0.0, 0.0, 0.05, {"name": "Main Road"}),
    (1, 2, H_LENGTH, 1.0, 1.0, 0.0, {"name": "Main Underpass", "is_underpass": True}),
    (2, 3, H_LENGTH, 0.3, 0.3, 0.05, {"name": "East Road"}),
    (3, 4, H_LENGTH, 0.3, 0.3, 0.05, {"name": "East Road"}),
    # row 1 — shaded bypass; second hop heavily flood-prone.
    (5, 6, H_LENGTH, 1.0, 1.0, 0.05, {"name": "Bazar Road"}),
    (6, 7, H_LENGTH, 1.0, 1.0, 0.9, {"name": "Bazar Low"}),
    (7, 8, H_LENGTH, 1.0, 1.0, 0.05, {"name": "Bazar Road"}),
    (8, 9, H_LENGTH, 1.0, 1.0, 0.05, {"name": "Bazar Road"}),
    # row 2 — the safe flood-free corridor; one bridge (flood 0.0 per §6.3).
    (10, 11, H_LENGTH, 0.5, 0.5, 0.0, {"name": "Safe Street"}),
    (11, 12, H_LENGTH, 0.5, 0.5, 0.0, {"name": "Safe Street"}),
    (12, 13, H_LENGTH, 0.5, 0.5, 0.0, {"is_bridge": True, "name": "Footbridge"}),
    (13, 14, H_LENGTH, 0.5, 0.5, 0.05, {"name": "Safe Street"}),
    # row 3 — filler.
    (15, 16, H_LENGTH, 0.3, 0.3, 0.1, {}),
    (16, 17, H_LENGTH, 0.3, 0.3, 0.1, {}),
    (17, 18, H_LENGTH, 0.3, 0.3, 0.1, {}),
    (18, 19, H_LENGTH, 0.3, 0.3, 0.1, {}),
    # vertical connectors col 0 and the two that close the designed detours:
    # (7->2)  lets the shade route climb back to the main-road destination;
    # (12->7) lets the monsoon detour climb back from row 2 via row 1.
    (0, 5, V_LENGTH, 1.0, 1.0, 0.0, {"name": "Col-zero Lane"}),
    (5, 10, V_LENGTH, 1.0, 1.0, 0.0, {"name": "Col-zero Lane"}),
    (10, 15, V_LENGTH, 0.3, 0.3, 0.0, {}),
    (1, 6, V_LENGTH, 0.2, 0.2, 0.0, {}),
    (6, 11, V_LENGTH, 0.2, 0.2, 0.0, {}),
    (7, 2, V_LENGTH, 1.0, 1.0, 0.0, {"name": "Bazar Up-lane"}),
    (12, 7, V_LENGTH, 1.0, 1.0, 0.0, {"name": "Safe Up-lane"}),
    (11, 6, V_LENGTH, 0.2, 0.2, 0.0, {}),
    (12, 11, V_LENGTH, 0.5, 0.5, 0.0, {}),
    (3, 8, V_LENGTH, 0.2, 0.2, 0.0, {}),
    (8, 13, V_LENGTH, 0.2, 0.2, 0.0, {}),
    # three reverse hops so return routes behave like two-way streets.
    (2, 1, H_LENGTH, 0.0, 0.0, 0.05, {"name": "Main Road"}),
    (6, 5, H_LENGTH, 1.0, 1.0, 0.05, {"name": "Bazar Road"}),
    (11, 10, H_LENGTH, 0.5, 0.5, 0.0, {"name": "Safe Street"}),
]

# Filler-edge shade jitter: deterministic rng(42); designed (named) edges exact.
_JITTER_INDICES = {i for i, e in enumerate(EDGES) if "name" not in e[6]}


def build_fixtures() -> tuple[
    nx.MultiDiGraph, np.ndarray, np.ndarray, np.ndarray, dict
]:
    """Returns (graph, shade_summer (E,48), shade_monsoon (E,48), flood (E,), coverage geojson)."""
    rng = np.random.default_rng(SEED)

    G = nx.MultiDiGraph()
    G.graph["crs"] = "epsg:4326"
    for nid in range(20):
        lon, lat = node_xy(nid)
        G.add_node(nid, x=lon, y=lat, x_m=lon, y_m=lat)

    shade_summer = np.zeros((len(EDGES), SLOTS), dtype=np.float16)
    shade_monsoon = np.zeros((len(EDGES), SLOTS), dtype=np.float16)
    flood = np.zeros(len(EDGES), dtype=np.float16)

    for i, (u, v, length, sh_s, sh_m, fl, kwargs) in enumerate(EDGES):
        if i in _JITTER_INDICES:
            sh_s = float(np.clip(sh_s + rng.uniform(-0.02, 0.02), 0.0, 1.0))
        shade_summer[i] = _shade(sh_s)
        shade_monsoon[i] = _shade(sh_m)
        flood[i] = np.float16(fl)
        attrs = {
            "length_m": float(length),
            "length": float(
                length
            ),  # osmnx alias kept so direct can use weight="length"
            "highway": "residential",
            "width_m": 8.0,
            "is_underpass": bool(kwargs.get("is_underpass", False)),
            "is_bridge": bool(kwargs.get("is_bridge", False)),
            "shade_summer": shade_summer[i],
            "shade_monsoon": shade_monsoon[i],
            "flood_risk": np.float16(fl),
            "geometry": _geom(u, v),
        }
        if kwargs.get("name"):
            attrs["name"] = kwargs["name"]
        G.add_edge(u, v, key=0, **attrs)

    ring = [
        (LON0 - 0.002, LAT0 + 0.002),
        (LON0 + 0.012, LAT0 + 0.002),
        (LON0 + 0.012, LAT0 - 0.005),
        (LON0 - 0.002, LAT0 - 0.005),
    ]
    coverage = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"area": "fixture"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }
    return G, shade_summer, shade_monsoon, flood, coverage


def write_fixtures(directory: Path) -> Path:
    """Write the bundle with the same file names as repo data/ so the engine's
    local-dir loader can consume either the real precompute or this fixture."""
    G, sh_s, sh_m, flood, coverage = build_fixtures()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "graph.pkl").open("wb") as fh:
        pickle.dump(G, fh, protocol=5)
    np.save(directory / "shade_summer.npy", sh_s)
    np.save(directory / "shade_monsoon.npy", sh_m)
    np.save(directory / "flood.npy", flood)
    (directory / "coverage.geojson").write_text(json.dumps(coverage))
    return directory


if __name__ == "__main__":
    out = write_fixtures(Path(__file__).resolve().parent / "tests_fixtures")
    print(f"fixtures written to {out}")
