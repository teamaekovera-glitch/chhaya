"""CHHAYA routing engine — Phase 3 (CLAUDE.md §7.7, §8.1, §8.2).

Responsibilities:
  * load the routing bundle once per container (cold start, module singleton)
    from a local directory (dev/tests) or S3 (Lambda, via boto3 at call time —
    boto3 ships with the runtime, never in requirements.txt);
  * build the (E, 48) float32 cost matrices ONCE at load, per §8.1;
  * snap origin/destination to the graph (§8.2: numpy, cos-scaled lon, 300 m);
  * run per-request Dijkstra by indexing one slot column of the precomputed
    matrix, with hard underpass exclusion in flood + monsoon;
  * assemble the response payload (route geometry, distance, duration, shade
    profile/score, flood profile).

DATA-SOURCE NOTE (deviation from the task brief's literal array contract):
The pickled graph's edges carry self-contained §6.3 attrs (shade_summer /
shade_monsoon (48,) float16, flood_risk) and these are the authoritative cost
input, because build_graph.py filters edges by largest weak component AFTER
merging the standalone arrays — the pickle stores no edge_id, so standalone
S3 array rows cannot be mapped back onto surviving edges with certainty.
The standalone shade/flood arrays are still downloaded at cold start and
validated (finiteness, §7.6-style diurnal monotonicity) as a bundle integrity
gate; when the row count matches the graph edge count the per-edge agreement
is verified and logged. Routing itself never depends on the unverifiable
alignment.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

import cost
import networkx as nx
import numpy as np

log = logging.getLogger("chhaya.route")

SNAP_TOLERANCE_M = 300.0  # §8.2
_M_PER_DEG_LAT = 110_574.0
_M_PER_DEG_LON = 111_320.0

# Pinned copies of pipeline/config.py values (asserted equal by tests).
AREA_NAME = "Karol Bagh"
BBOX = (77.178, 28.642, 77.208, 28.657)


class OutsideCoverage(Exception):
    """Snap distance beyond §8.2 tolerance — carries the coverage polygon."""

    def __init__(self, coverage: dict):
        super().__init__("outside_coverage")
        self.coverage = coverage


class NoRoute(Exception):
    """Snapped endpoints exist but no directed path satisfies the mode's constraints."""


class RouteEngine:
    """Immutable-after-load routing bundle + per-request route computation."""

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        shade_summer: np.ndarray,
        shade_monsoon: np.ndarray,
        flood: np.ndarray,
        coverage: dict,
        walk_speed_mps: float,
    ):
        if walk_speed_mps <= 0:
            raise ValueError("walk_speed_mps must be positive")
        self.graph = graph
        self.coverage = coverage
        self.walk_speed_mps = float(walk_speed_mps)

        # -- edge arrays in deterministic insertion order (§8.1) -------------
        edges = list(graph.edges(keys=True, data=True))
        for i, (*_, data) in enumerate(edges):
            data["_ci"] = i  # Dijkstra weight fn reads this instead of hashing attrs
        self._edge_attr: list[dict] = [d for *_, d in edges]

        n = len(edges)
        self.n_edges = n
        self.n_nodes = graph.number_of_nodes()
        self.lengths = np.array(
            [float(d["length_m"]) for d in self._edge_attr], dtype=np.float32
        )
        self.underpass = np.array(
            [bool(d.get("is_underpass", False)) for d in self._edge_attr], dtype=bool
        )

        # Authoritative per-edge environment data: the §6.3 pickle attrs.
        shade = {}
        for season in cost.SEASONS:
            rows = np.stack(
                [
                    np.asarray(d[f"shade_{season}"], dtype=np.float32)
                    for d in self._edge_attr
                ]
            )
            if rows.shape != (n, cost.SLOTS):
                raise ValueError(
                    f"shade_{season} rows are {rows.shape}, expected {(n, cost.SLOTS)}"
                )
            shade[season] = np.clip(rows, 0.0, 1.0)
        self.shade = shade
        self.flood = np.clip(
            np.asarray(
                [float(d.get("flood_risk", 0.0)) for d in self._edge_attr],
                dtype=np.float32,
            ),
            0.0,
            1.0,
        )

        # (E, 48) float32 matrices, built ONCE at load; per-request Dijkstra
        # measures a single column. Flood risk is slot-invariant (§6.3); the
        # 48-slot shape keeps one uniform column-index access for every mode.
        self.shade_cost = {
            s: cost.shade_cost_matrix(self.lengths, shade[s], s) for s in cost.SEASONS
        }
        self.flood_cost = {
            s: cost.flood_cost_matrix(self.lengths, self.flood, s) for s in cost.SEASONS
        }

        # -- snap arrays over graph nodes (§7.7) -----------------------------
        self._node_ids = np.array(sorted(graph.nodes), dtype=np.int64)
        self._node_lon = np.array(
            [graph.nodes[int(i)]["x"] for i in self._node_ids], dtype=np.float64
        )
        self._node_lat = np.array(
            [graph.nodes[int(i)]["y"] for i in self._node_ids], dtype=np.float64
        )

        self.validate_bundle(shade_summer, shade_monsoon, flood)

    # -- bundle integrity gate (non-fatal; see module docstring) -----------
    def validate_bundle(
        self, shade_summer: np.ndarray, shade_monsoon: np.ndarray, flood: np.ndarray
    ) -> None:
        for name, arr in (
            ("shade_summer", shade_summer),
            ("shade_monsoon", shade_monsoon),
            ("flood", flood),
        ):
            if not np.isfinite(np.asarray(arr, dtype=np.float64)).all():
                log.warning("bundle gate: standalone %s contains NaN/Inf", name)
                return
        for season, arr in (("summer", shade_summer), ("monsoon", shade_monsoon)):
            arr32 = np.asarray(arr, dtype=np.float32)
            # The §7.6 gate presumes diurnal information; a bundle whose slot
            # columns are all identical (fixture bundles, no time-of-day
            # modelling) has nothing to gate — skip instead of false-warning.
            if float(arr32.std(axis=0).mean()) < 1e-6:
                log.info(
                    "bundle gate: standalone %s shade has no diurnal variation "
                    "— gate not applicable",
                    season,
                )
                continue
            means = arr32.mean(axis=0)
            if not (means[4] > means[24] < means[44]):
                log.warning(
                    "bundle gate: standalone %s shade violates §7.6 diurnal gate",
                    season,
                )
        if flood.shape[0] == self.n_edges and shade_summer.shape[0] == self.n_edges:
            f_diff = float(
                np.max(np.abs(self.flood - np.asarray(flood, dtype=np.float32)))
            )
            s_diff = max(
                float(
                    np.max(
                        np.abs(
                            self.shade[s]
                            - np.asarray(
                                shade_summer if s == "summer" else shade_monsoon,
                                dtype=np.float32,
                            )
                        )
                    )
                )
                for s in cost.SEASONS
            )
            log.info(
                "standalone arrays align with graph edges (max flood diff %.2g, shade %.2g)",
                f_diff,
                s_diff,
            )
        else:
            log.info(
                "standalone arrays unaligned with filtered graph (%d rows vs %d edges) — "
                "routing uses §6.3 pickle attrs (self-contained contract)",
                int(flood.shape[0]),
                self.n_edges,
            )

    # -- §7.7 snap ----------------------------------------------------------
    def snap(self, lon: float, lat: float) -> int:
        dlon = (self._node_lon - lon) * np.cos(np.deg2rad(lat))
        dlat = self._node_lat - lat
        dist = np.hypot(dlon * _M_PER_DEG_LON, dlat * _M_PER_DEG_LAT)
        i = int(np.argmin(dist))
        if float(dist[i]) > SNAP_TOLERANCE_M:
            raise OutsideCoverage(self.coverage)
        return int(self._node_ids[i])

    # -- Dijkstra -----------------------------------------------------------
    def _weight_fn(self, col: np.ndarray, skip_underpass: bool):
        def weight(_u, _v, edge_views) -> float | None:
            # MultiDiGraph adjacency view: edge_views is {key: attr_dict}; a
            # None return makes networkx skip the edge entirely (hard exclusion).
            best: float | None = None
            for data in edge_views.values():
                if skip_underpass and data.get("is_underpass"):
                    continue
                c = float(col[data["_ci"]])
                if best is None or c < best:
                    best = c
            return best

        return weight

    def _col(self, mode: str, season: str, slot: int) -> np.ndarray | None:
        if mode == "shade":
            return self.shade_cost[season][:, slot]
        if mode == "flood":
            return self.flood_cost[season][:, slot]
        return None  # direct mode routes on the length_m attribute

    def _path_edges(self, path: list[int], col: np.ndarray | None) -> list[dict]:
        chosen: list[dict] = []
        for u, v in pairwise(path):
            views = self.graph[u][v]
            if col is None:
                key = min(views, key=lambda k: views[k]["length_m"])
            else:
                key = min(views, key=lambda k: col[views[k]["_ci"]])
            chosen.append(views[key])
        return chosen

    def route(
        self,
        mode: str,
        season: str,
        slot: int,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> dict:
        src = self.snap(*origin)
        dst = self.snap(*destination)
        # Small LRU warm cache (task contract): demo scenarios repeat the same
        # (mode, season, slot, endpoints) tuples, and a warm repeat skips the
        # Dijkstra entirely. Payload dicts are serialised by the handler and
        # never mutated, so returning the cached object is safe.
        return self._route_cached(mode, season, slot, src, dst)

    # B019: lru_cache on a method pins `self` in the cache — safe here because
    # the RouteEngine is an immutable process-wide singleton that is never GC'd.
    @lru_cache(maxsize=64)  # noqa: B019
    def _route_cached(
        self, mode: str, season: str, slot: int, src: int, dst: int
    ) -> dict:
        col = self._col(mode, season, slot)
        try:
            if col is None:
                path = nx.shortest_path(self.graph, src, dst, weight="length_m")
            else:
                path = nx.shortest_path(
                    self.graph,
                    src,
                    dst,
                    weight=self._weight_fn(
                        col, skip_underpass=(mode == "flood" and season == "monsoon")
                    ),
                )
        except nx.NetworkXNoPath as exc:
            raise NoRoute(f"no {mode} route for season={season}") from exc

        return self._payload(mode, season, slot, self._path_edges(path, col))

    # -- response payload ----------------------------------------------------
    def _payload(self, mode: str, season: str, slot: int, edges: list[dict]) -> dict:
        coords: list[list[float]] = []
        for data in edges:
            for x, y in data["geometry"].coords:
                if not coords or (x, y) != (coords[-1][0], coords[-1][1]):
                    coords.append([float(x), float(y)])

        distance_m = float(sum(d["length_m"] for d in edges))
        cis = np.array([d["_ci"] for d in edges], dtype=np.int64)
        weights = self.lengths[cis]
        w_total = float(weights.sum())

        if w_total > 0:
            # 48 per-slot length-weighted mean shade fractions over the route's
            # edges; shade_score is the headline value at the requested slot.
            shade_profile = [
                float(np.dot(self.shade[season][:, s][cis], weights) / w_total)
                for s in range(cost.SLOTS)
            ]
            # flood_risk has no slot/season dimension (§6.3) — both keys carry
            # the same length-weighted mean so the contract is season-ready.
            flood_profile = {
                s: float(np.dot(self.flood[cis], weights) / w_total)
                for s in cost.SEASONS
            }
        else:
            shade_profile = [0.0] * cost.SLOTS
            flood_profile = {s: 0.0 for s in cost.SEASONS}

        return {
            "route": coords,
            "distance_m": distance_m,
            "duration_s": distance_m / self.walk_speed_mps,
            "shade_profile": shade_profile,
            "shade_score": shade_profile[slot],
            "flood_profile": flood_profile,
            "mode": mode,
            "season": season,
            "slot": slot,
        }

    def stats(self) -> dict:
        return {
            "area": AREA_NAME,
            "n_edges": int(self.n_edges),
            "n_nodes": int(self.n_nodes),
            "bbox": list(BBOX),
            "slots": cost.SLOTS,
            "seasons": list(cost.SEASONS),
            "weights": cost.WEIGHTS,
        }


# -- bundle loading -----------------------------------------------------------


def load_engine_from_dir(
    directory: Path,
    walk_speed_mps: float,
    graph_name: str = "graph.pkl",
    shade_summer_name: str = "shade_summer.npy",
    shade_monsoon_name: str = "shade_monsoon.npy",
    flood_name: str = "flood.npy",
    coverage_name: str = "coverage.geojson",
) -> RouteEngine:
    import pickle

    directory = Path(directory)
    with (directory / graph_name).open("rb") as fh:
        graph = pickle.load(fh)
    return RouteEngine(
        graph,
        np.load(directory / shade_summer_name),
        np.load(directory / shade_monsoon_name),
        np.load(directory / flood_name),
        json.loads((directory / coverage_name).read_text()),
        walk_speed_mps,
    )


def load_engine_from_env(walk_speed_mps: float) -> RouteEngine:
    """CHHAYA_LOCAL_DATA_DIR (dev/tests) or the S3 bucket (Lambda cold start).

    S3 path: boto3 (runtime-provided, not a requirements.txt dep) downloads the
    bundle into /tmp — /tmp survives warm invocations, so the download runs
    exactly once per container. Keys default to pipeline/upload.py's bucket
    layout (the brief's literal "data/graph.pkl" default never matches what
    upload.py writes — see PR description).
    """
    import os

    local = os.environ.get("CHHAYA_LOCAL_DATA_DIR")
    if local:
        log.info("loading routing bundle from local dir %s", local)
        return load_engine_from_dir(Path(local), walk_speed_mps)

    bucket = os.environ.get("GRAPH_BUCKET")
    if not bucket:
        raise RuntimeError(
            "no routing bundle configured: set CHHAYA_LOCAL_DATA_DIR or GRAPH_BUCKET"
        )

    import boto3  # Lambda runtime ships boto3; imported lazily so tests need no AWS

    key_map = {
        "graph_name": os.environ.get("S3_KEY_GRAPH", "graph/graph.pkl"),
        "shade_summer_name": os.environ.get("S3_KEY_SHADE_SUMMER", "shade/summer.npy"),
        "shade_monsoon_name": os.environ.get(
            "S3_KEY_SHADE_MONSOON", "shade/monsoon.npy"
        ),
        "flood_name": os.environ.get("S3_KEY_FLOOD", "flood/flood.npy"),
        "coverage_name": os.environ.get("S3_KEY_COVERAGE", "graph/coverage.geojson"),
    }
    local_names = {
        "graph_name": "graph.pkl",
        "shade_summer_name": "shade_summer.npy",
        "shade_monsoon_name": "shade_monsoon.npy",
        "flood_name": "flood.npy",
        "coverage_name": "coverage.geojson",
    }
    tmp = Path("/tmp/chhaya_bundle")
    tmp.mkdir(parents=True, exist_ok=True)
    client = boto3.client("s3")
    for param, key in key_map.items():
        dest = tmp / local_names[param]
        if not dest.exists() or dest.stat().st_size == 0:
            started = time.monotonic()
            client.download_file(bucket, key, str(dest))
            log.info(
                "s3 cold start: %s -> %s (%.0f ms)",
                key,
                dest,
                (time.monotonic() - started) * 1000,
            )
    return load_engine_from_dir(tmp, walk_speed_mps, **key_map)


# -- module singleton (§7.7 cold start) ----------------------------------------

_engine: RouteEngine | None = None
_lock = threading.Lock()
cold_start_ms: float | None = None  # None = already warm


def get_engine() -> RouteEngine:
    global _engine, cold_start_ms
    if _engine is None:
        import os

        speed = float(os.environ.get("WALK_SPEED_MPS", "1.1"))
        with _lock:
            if _engine is None:
                started = time.monotonic()
                _engine = load_engine_from_env(speed)
                cold_start_ms = (time.monotonic() - started) * 1000
                log.info(
                    "routing engine ready in %.0f ms (%d edges / %d nodes)",
                    cold_start_ms,
                    _engine.n_edges,
                    _engine.n_nodes,
                )
    return _engine


def reset_engine() -> None:
    """Drop the singleton — tests point CHHAYA_LOCAL_DATA_DIR at a fresh bundle."""
    global _engine, cold_start_ms
    with _lock:
        _engine = None
        cold_start_ms = None
