"""§9 last row — §7.6 sanity gate as a repeatable pytest.

Loads data/graph.pkl if built and re-runs the exact §7.6 gate table from
pipeline/build_graph.py. Skipped cleanly (pytest.skip) when graph.pkl is
absent — e.g. fresh clones or CI-less machines — so it can never break runs
where the precompute hasn't happened.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
GRAPH_PKL = ROOT / "data" / "graph.pkl"


def _contract_attr(graph, node, attr):
    attrs = graph.nodes[node]
    assert attr in attrs, f"node {node} missing {attr}"
    return attrs[attr]


@pytest.fixture(name="graph")
def fixture_graph():
    if not GRAPH_PKL.exists():
        pytest.skip(f"{GRAPH_PKL.name} not built yet — run pipeline/build_graph.py (skipped, not failed)")
    with open(GRAPH_PKL, "rb") as fh:
        return pickle.load(fh)


def test_graph_pickle_loads_with_contract_attrs(graph):
    """§6.3 attrs present: node x/y (WGS84) + x_m/y_m (UTM); eight edge attrs."""
    node = next(iter(graph.nodes))
    for attr in ("x", "y", "x_m", "y_m"):
        _contract_attr(graph, node, attr)
    u, v, attrs = next(iter(graph.edges(data=True)))
    for attr in ("length_m", "highway", "width_m", "is_underpass",
                 "is_bridge", "shade_summer", "shade_monsoon", "flood_risk"):
        assert attr in attrs, f"edge {u}->{v} missing {attr}"
    assert len(attrs["shade_summer"]) == 48 and len(attrs["shade_monsoon"]) == 48


def test_sanity_gate_table_passes_on_built_graph(graph):
    """The exact §7.6 gate re-run independently from the pickled graph:
    slot monotonicity, underpass == 1.0, flood range, NaN-free, >=95%
    weakly-connected. Deliberate duplication of build_graph thresholds — a
    gate test that trusts the builder would only test the builder against
    itself."""
    shade_s, shade_m, flood, up = [], [], [], []
    for _, _, attrs in graph.edges(data=True):
        shade_s.append(attrs["shade_summer"])
        shade_m.append(attrs["shade_monsoon"])
        flood.append(float(attrs["flood_risk"]))
        if attrs["is_underpass"]:
            up.append(np.asarray(attrs["shade_summer"], dtype=float))
    summer = np.asarray(shade_s, dtype=float)
    monsoon = np.asarray(shade_m, dtype=float)
    flood = np.asarray(flood, dtype=float)

    mean24_s, mean44_s, mean4_s = (float(summer[:, s].mean()) for s in (24, 44, 4))
    assert mean24_s < mean44_s, f"§7.6 gate: 13:00 shade {mean24_s:.3f} not below 18:00 {mean44_s:.3f}"
    assert mean4_s > mean24_s, f"§7.6 gate: 08:00 shade {mean4_s:.3f} not above 13:00 {mean24_s:.3f}"
    for arr in (summer, monsoon, flood):
        assert not np.isnan(arr).any(), "§7.6 gate: NaN present in shade/flood"
    assert flood.min() >= 0.0 and flood.max() <= 1.0, f"§7.6 gate: flood_risk outside [0,1]: [{flood.min()}, {flood.max()}]"
    up_all = np.concatenate(up) if up else np.array([1.0])
    assert up_all.min() >= 1.0, f"§7.6 gate: underpass shade below 1.0 (min {up_all.min()})"

    largest = max(nx.weakly_connected_components(graph), key=len)
    kept_pct = 100.0 * len(largest) / len(graph.nodes)
    assert kept_pct >= 95.0, f"§7.6 gate: largest weak component {kept_pct:.2f}% < 95"
